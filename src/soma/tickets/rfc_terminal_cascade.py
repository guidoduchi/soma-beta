from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Protocol

from soma.foundation.errors import SomaError, ValidationError
from soma.foundation.identifiers import new_uuid4, require_uuid4, utc_epoch_seconds
from soma.foundation.persistence.uow import UnitOfWork
from soma.foundation.strict_json import sha256_canonical_json

_SCOPE_PROFILE = "SOMA_RFC_TERMINAL_CASCADE_SCOPE_V1"
_PROPOSAL_CONTRACT_VERSION = 1
_TERMINAL_CLASSES = frozenset({"terminal_closed", "terminal_cancelled"})
_TASK_NO_RE = re.compile(r"TK[0-9]{14}\Z")


@dataclass(frozen=True, slots=True)
class RfcTerminalCascadeRfcMember:
    rfc_id: str
    captured_rfc_revision: int
    captured_role: str


@dataclass(frozen=True, slots=True)
class RfcTerminalCascadeWfmMember:
    task_id: str
    owning_rfc_id: str
    captured_task_revision: int
    captured_task_no: str


@dataclass(frozen=True, slots=True)
class RfcTerminalCascadeScope:
    trigger_rfc_id: str
    terminal_epoch_id: str
    terminal_status_class: str
    terminal_status_evidence_id: str
    scope_kind: str
    rfc_members: tuple[RfcTerminalCascadeRfcMember, ...]
    wfm_members: tuple[RfcTerminalCascadeWfmMember, ...]
    scope_fingerprint: str


class RfcTerminalTaskParticipant(Protocol):
    def capture_applicable_wfms(
        self,
        uow: UnitOfWork,
        rfc_ids: tuple[str, ...],
    ) -> tuple[RfcTerminalCascadeWfmMember, ...]: ...


def terminal_cascade_scope_payload(
    *,
    trigger_rfc_id: str,
    terminal_epoch_id: str,
    terminal_status_class: str,
    terminal_status_evidence_id: str,
    scope_kind: str,
    rfc_members: tuple[RfcTerminalCascadeRfcMember, ...],
    wfm_members: tuple[RfcTerminalCascadeWfmMember, ...],
) -> dict[str, Any]:
    return {
        "schema": _SCOPE_PROFILE,
        "proposal_contract_version": _PROPOSAL_CONTRACT_VERSION,
        "trigger_rfc_id": trigger_rfc_id,
        "terminal_epoch_id": terminal_epoch_id,
        "terminal_status_class": terminal_status_class,
        "terminal_status_evidence_id": terminal_status_evidence_id,
        "scope_kind": scope_kind,
        "rfc_members": [
            {
                "rfc_id": member.rfc_id,
                "captured_rfc_revision": member.captured_rfc_revision,
                "captured_role": member.captured_role,
            }
            for member in rfc_members
        ],
        "wfm_members": [
            {
                "task_id": member.task_id,
                "owning_rfc_id": member.owning_rfc_id,
                "captured_task_revision": member.captured_task_revision,
                "captured_task_no": member.captured_task_no,
            }
            for member in wfm_members
        ],
    }


def terminal_cascade_scope_fingerprint(
    *,
    trigger_rfc_id: str,
    terminal_epoch_id: str,
    terminal_status_class: str,
    terminal_status_evidence_id: str,
    scope_kind: str,
    rfc_members: tuple[RfcTerminalCascadeRfcMember, ...],
    wfm_members: tuple[RfcTerminalCascadeWfmMember, ...],
) -> str:
    return sha256_canonical_json(
        terminal_cascade_scope_payload(
            trigger_rfc_id=trigger_rfc_id,
            terminal_epoch_id=terminal_epoch_id,
            terminal_status_class=terminal_status_class,
            terminal_status_evidence_id=terminal_status_evidence_id,
            scope_kind=scope_kind,
            rfc_members=rfc_members,
            wfm_members=wfm_members,
        )
    )


def _stored_uuid(value: object, *, field: str) -> str:
    if not isinstance(value, str):
        raise SomaError("PERSISTENCE_FAILURE", f"stored {field} is not a UUID string")
    try:
        return require_uuid4(value)
    except ValidationError as exc:
        raise SomaError("PERSISTENCE_FAILURE", f"stored {field} is not canonical UUIDv4") from exc


def _positive_revision(value: object, *, field: str, participant: bool = False) -> int:
    if type(value) is not int or value <= 0:
        code = "RFC_TERMINAL_CASCADE_PARTICIPANT_FAILED" if participant else "PERSISTENCE_FAILURE"
        raise SomaError(code, f"{field} must be a positive integer")
    return value


class RfcTerminalCascadeCaptureService:
    """LLD-03 owner for atomic pending terminal-cascade proposal capture."""

    def __init__(self, task_participant: RfcTerminalTaskParticipant) -> None:
        self._task_participant = task_participant

    @staticmethod
    def _require_outer_receipt(uow: UnitOfWork, accepted_command_id: str) -> None:
        if uow.connection.execute(
            "SELECT 1 FROM command_receipts WHERE command_id=?",
            (accepted_command_id,),
        ).fetchone() is None:
            raise SomaError(
                "PERSISTENCE_FAILURE",
                "terminal cascade capture requires the outer accepted command receipt",
            )

    @staticmethod
    def _validate_terminal_projection(
        uow: UnitOfWork,
        *,
        trigger_rfc_id: str,
        terminal_epoch_id: str,
        terminal_status_class: str,
        terminal_status_evidence_id: str,
    ) -> None:
        if terminal_status_class not in _TERMINAL_CLASSES:
            raise SomaError("RFC_TERMINAL_CASCADE_STALE", "terminal cascade capture requires terminal RFC status")
        if not isinstance(terminal_status_evidence_id, str) or not terminal_status_evidence_id:
            raise SomaError("RFC_TERMINAL_CASCADE_STALE", "terminal cascade capture requires exact status evidence")
        row = uow.connection.execute(
            "SELECT status_class,status_evidence_id,terminal_epoch_id FROM rfc_current_source_projection WHERE rfc_id=?",
            (trigger_rfc_id,),
        ).fetchone()
        if row is None or tuple(row) != (
            terminal_status_class,
            terminal_status_evidence_id,
            terminal_epoch_id,
        ):
            raise SomaError(
                "RFC_TERMINAL_CASCADE_STALE",
                "terminal cascade capture no longer matches current RFC terminal evidence",
            )

    @staticmethod
    def _capture_rfc_scope(
        uow: UnitOfWork,
        *,
        trigger_rfc_id: str,
    ) -> tuple[str, tuple[RfcTerminalCascadeRfcMember, ...]]:
        trigger_id = _stored_uuid(trigger_rfc_id, field="trigger RFC identity")
        trigger = uow.connection.execute(
            "SELECT revision FROM rfcs WHERE rfc_id=?",
            (trigger_id,),
        ).fetchone()
        if trigger is None:
            raise SomaError("NOT_FOUND", "trigger RFC does not exist")
        trigger_revision = _positive_revision(trigger[0], field="stored RFC revision")

        parent = uow.connection.execute(
            "SELECT parent_rfc_id FROM rfc_hierarchy_edges WHERE child_rfc_id=? AND edge_state='active'",
            (trigger_id,),
        ).fetchone()
        children = uow.connection.execute(
            "SELECT child.rfc_id,child.revision FROM rfc_hierarchy_edges edge "
            "JOIN rfcs child ON child.rfc_id=edge.child_rfc_id "
            "WHERE edge.parent_rfc_id=? AND edge.edge_state='active' ORDER BY child.rfc_id ASC",
            (trigger_id,),
        ).fetchall()

        if parent is not None:
            if children:
                raise SomaError("PERSISTENCE_FAILURE", "RFC hierarchy violates the two-level forest invariant")
            _stored_uuid(parent[0], field="RFC parent identity")
            return (
                "exact_rfc",
                (
                    RfcTerminalCascadeRfcMember(
                        rfc_id=trigger_id,
                        captured_rfc_revision=trigger_revision,
                        captured_role="subordinate",
                    ),
                ),
            )

        root_role = "root" if children else "standalone"
        members: list[RfcTerminalCascadeRfcMember] = [
            RfcTerminalCascadeRfcMember(
                rfc_id=trigger_id,
                captured_rfc_revision=trigger_revision,
                captured_role=root_role,
            )
        ]
        previous_child_id: str | None = None
        for child_id_raw, child_revision_raw in children:
            child_id = _stored_uuid(child_id_raw, field="RFC child identity")
            if previous_child_id is not None and child_id.encode("utf-8") <= previous_child_id.encode("utf-8"):
                raise SomaError("PERSISTENCE_FAILURE", "RFC child ordering/identity is not canonical")
            previous_child_id = child_id
            members.append(
                RfcTerminalCascadeRfcMember(
                    rfc_id=child_id,
                    captured_rfc_revision=_positive_revision(
                        child_revision_raw,
                        field="stored child RFC revision",
                    ),
                    captured_role="subordinate",
                )
            )
        return "root_branch", tuple(members)

    @staticmethod
    def _normalize_wfm_members(
        raw_members: object,
        *,
        rfc_ids: tuple[str, ...],
    ) -> tuple[RfcTerminalCascadeWfmMember, ...]:
        if not isinstance(raw_members, (tuple, list)):
            raise SomaError(
                "RFC_TERMINAL_CASCADE_PARTICIPANT_FAILED",
                "Task participant returned an invalid WFM capture collection",
            )
        allowed_rfc_ids = frozenset(rfc_ids)
        seen_task_ids: set[str] = set()
        seen_task_nos: set[str] = set()
        normalized: list[RfcTerminalCascadeWfmMember] = []
        for raw in raw_members:
            if not isinstance(raw, RfcTerminalCascadeWfmMember):
                raise SomaError(
                    "RFC_TERMINAL_CASCADE_PARTICIPANT_FAILED",
                    "Task participant returned an invalid WFM capture member",
                )
            try:
                task_id = require_uuid4(raw.task_id)
                owning_rfc_id = require_uuid4(raw.owning_rfc_id)
            except ValidationError as exc:
                raise SomaError(
                    "RFC_TERMINAL_CASCADE_PARTICIPANT_FAILED",
                    "Task participant returned a non-canonical identity",
                ) from exc
            if owning_rfc_id not in allowed_rfc_ids:
                raise SomaError(
                    "RFC_TERMINAL_CASCADE_PARTICIPANT_FAILED",
                    "Task participant returned a WFM outside the captured RFC scope",
                )
            revision = _positive_revision(
                raw.captured_task_revision,
                field="captured Task revision",
                participant=True,
            )
            if not isinstance(raw.captured_task_no, str) or _TASK_NO_RE.fullmatch(raw.captured_task_no) is None:
                raise SomaError(
                    "RFC_TERMINAL_CASCADE_PARTICIPANT_FAILED",
                    "Task participant returned an invalid immutable WFM Task No.",
                )
            if task_id in seen_task_ids or raw.captured_task_no in seen_task_nos:
                raise SomaError(
                    "RFC_TERMINAL_CASCADE_PARTICIPANT_FAILED",
                    "Task participant returned duplicate WFM identity",
                )
            seen_task_ids.add(task_id)
            seen_task_nos.add(raw.captured_task_no)
            normalized.append(
                RfcTerminalCascadeWfmMember(
                    task_id=task_id,
                    owning_rfc_id=owning_rfc_id,
                    captured_task_revision=revision,
                    captured_task_no=raw.captured_task_no,
                )
            )
        normalized.sort(key=lambda member: (member.owning_rfc_id.encode("utf-8"), member.task_id.encode("utf-8")))
        return tuple(normalized)

    def capture_scope(
        self,
        uow: UnitOfWork,
        *,
        trigger_rfc_id: str,
        terminal_epoch_id: str,
        terminal_status_class: str,
        terminal_status_evidence_id: str,
    ) -> RfcTerminalCascadeScope:
        self._validate_terminal_projection(
            uow,
            trigger_rfc_id=trigger_rfc_id,
            terminal_epoch_id=terminal_epoch_id,
            terminal_status_class=terminal_status_class,
            terminal_status_evidence_id=terminal_status_evidence_id,
        )
        scope_kind, rfc_members = self._capture_rfc_scope(uow, trigger_rfc_id=trigger_rfc_id)
        rfc_ids = tuple(member.rfc_id for member in rfc_members)
        try:
            raw_wfms = self._task_participant.capture_applicable_wfms(uow, rfc_ids)
        except Exception as exc:
            raise SomaError(
                "RFC_TERMINAL_CASCADE_PARTICIPANT_FAILED",
                "Task participant failed while capturing applicable WFMs",
            ) from exc
        wfm_members = self._normalize_wfm_members(raw_wfms, rfc_ids=rfc_ids)
        fingerprint = terminal_cascade_scope_fingerprint(
            trigger_rfc_id=trigger_rfc_id,
            terminal_epoch_id=terminal_epoch_id,
            terminal_status_class=terminal_status_class,
            terminal_status_evidence_id=terminal_status_evidence_id,
            scope_kind=scope_kind,
            rfc_members=rfc_members,
            wfm_members=wfm_members,
        )
        return RfcTerminalCascadeScope(
            trigger_rfc_id=trigger_rfc_id,
            terminal_epoch_id=terminal_epoch_id,
            terminal_status_class=terminal_status_class,
            terminal_status_evidence_id=terminal_status_evidence_id,
            scope_kind=scope_kind,
            rfc_members=rfc_members,
            wfm_members=wfm_members,
            scope_fingerprint=fingerprint,
        )

    def capture_pending(
        self,
        uow: UnitOfWork,
        *,
        trigger_rfc_id: str,
        terminal_epoch_id: str,
        terminal_status_class: str,
        terminal_status_evidence_id: str,
        accepted_command_id: str,
    ) -> str:
        self._require_outer_receipt(uow, accepted_command_id)
        if uow.connection.execute(
            "SELECT 1 FROM rfc_terminal_cascade_proposals "
            "WHERE trigger_rfc_id=? AND terminal_epoch_id=? AND proposal_state='pending'",
            (trigger_rfc_id, terminal_epoch_id),
        ).fetchone() is not None:
            raise SomaError(
                "RFC_TERMINAL_CASCADE_STALE",
                "a pending terminal cascade already exists for this RFC terminal epoch",
            )

        scope = self.capture_scope(
            uow,
            trigger_rfc_id=trigger_rfc_id,
            terminal_epoch_id=terminal_epoch_id,
            terminal_status_class=terminal_status_class,
            terminal_status_evidence_id=terminal_status_evidence_id,
        )
        proposal_id = new_uuid4()
        now = utc_epoch_seconds()
        uow.connection.execute(
            "INSERT INTO rfc_terminal_cascade_proposals("
            "rfc_terminal_cascade_proposal_id,trigger_rfc_id,terminal_epoch_id,terminal_status_class,"
            "terminal_status_evidence_id,scope_kind,scope_fingerprint,proposal_state,revision,created_at_utc,"
            "created_command_id,executed_at_utc,executed_command_id,superseded_at_utc,superseded_command_id"
            ") VALUES (?, ?, ?, ?, ?, ?, ?, 'pending', 1, ?, ?, NULL, NULL, NULL, NULL)",
            (
                proposal_id,
                scope.trigger_rfc_id,
                scope.terminal_epoch_id,
                scope.terminal_status_class,
                scope.terminal_status_evidence_id,
                scope.scope_kind,
                scope.scope_fingerprint,
                now,
                accepted_command_id,
            ),
        )
        for ordinal, member in enumerate(scope.rfc_members):
            uow.connection.execute(
                "INSERT INTO rfc_terminal_cascade_rfc_members("
                "rfc_terminal_cascade_proposal_id,rfc_id,captured_rfc_revision,captured_role,ordinal"
                ") VALUES (?, ?, ?, ?, ?)",
                (
                    proposal_id,
                    member.rfc_id,
                    member.captured_rfc_revision,
                    member.captured_role,
                    ordinal,
                ),
            )
        for ordinal, member in enumerate(scope.wfm_members):
            uow.connection.execute(
                "INSERT INTO rfc_terminal_cascade_wfm_members("
                "rfc_terminal_cascade_proposal_id,task_id,owning_rfc_id,captured_task_revision,captured_task_no,ordinal"
                ") VALUES (?, ?, ?, ?, ?, ?)",
                (
                    proposal_id,
                    member.task_id,
                    member.owning_rfc_id,
                    member.captured_task_revision,
                    member.captured_task_no,
                    ordinal,
                ),
            )
        return proposal_id
