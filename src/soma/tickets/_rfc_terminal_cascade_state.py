from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Protocol

from soma.foundation.application.command_boundary import CommandBoundary, CommandEnvelope, PreparedMutation
from soma.foundation.audit.writer import AuditEventInput, AuditResultRef, AuditWriter
from soma.foundation.errors import SomaError, ValidationError
from soma.foundation.identifiers import new_uuid4, require_uuid4, utc_epoch_seconds
from soma.foundation.persistence.connections import ConnectionFactory
from soma.foundation.persistence.uow import UnitOfWork
from soma.foundation.strict_json import sha256_canonical_json

from .audit_registry import build_tickets_audit_registry

_SCOPE_PROFILE = "SOMA_RFC_TERMINAL_CASCADE_SCOPE_V1"
_PROPOSAL_CONTRACT_VERSION = 1
_TERMINAL_CLASSES = frozenset({"terminal_closed", "terminal_cancelled"})
_TASK_NO_RE = re.compile(r"TK[0-9]{14}\Z")
_SHA256_HEX_RE = re.compile(r"[0-9a-f]{64}\Z")


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


@dataclass(frozen=True, slots=True)
class RfcTerminalCascadeStateResult:
    proposal_id: str
    trigger_rfc_id: str
    state: str
    proposal_revision: int
    terminal_epoch_id: str
    terminal_status_class: str
    terminal_status_evidence_id: str
    scope_kind: str
    scope_fingerprint: str
    captured_rfc_count: int
    captured_wfm_count: int
    replayed: bool = False
    no_change: bool = False

    def to_response(self) -> dict[str, Any]:
        return {
            "proposal_id": self.proposal_id,
            "trigger_rfc_id": self.trigger_rfc_id,
            "state": self.state,
            "proposal_revision": self.proposal_revision,
            "terminal_epoch_id": self.terminal_epoch_id,
            "terminal_status_class": self.terminal_status_class,
            "terminal_status_evidence_id": self.terminal_status_evidence_id,
            "scope_kind": self.scope_kind,
            "scope_fingerprint": self.scope_fingerprint,
            "captured_rfc_count": self.captured_rfc_count,
            "captured_wfm_count": self.captured_wfm_count,
        }


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


def _request_uuid(value: object, *, field: str) -> str:
    if not isinstance(value, str):
        raise ValidationError(f"{field} must be canonical UUIDv4")
    try:
        return require_uuid4(value)
    except ValidationError as exc:
        raise ValidationError(f"{field} must be canonical UUIDv4") from exc


def _positive_revision(value: object, *, field: str, participant: bool = False) -> int:
    if type(value) is not int or value <= 0:
        code = "RFC_TERMINAL_CASCADE_PARTICIPANT_FAILED" if participant else "PERSISTENCE_FAILURE"
        raise SomaError(code, f"{field} must be a positive integer")
    return value


def _nonnegative_count(value: object, *, field: str) -> int:
    if type(value) is not int or value < 0:
        raise SomaError("PERSISTENCE_FAILURE", f"{field} must be a non-negative integer")
    return value


def _state_response(
    *,
    proposal_id: str,
    trigger_rfc_id: str,
    state: str,
    proposal_revision: int,
    terminal_epoch_id: str,
    terminal_status_class: str,
    terminal_status_evidence_id: str,
    scope_kind: str,
    scope_fingerprint: str,
    captured_rfc_count: int,
    captured_wfm_count: int,
) -> dict[str, Any]:
    return {
        "proposal_id": proposal_id,
        "trigger_rfc_id": trigger_rfc_id,
        "state": state,
        "proposal_revision": proposal_revision,
        "terminal_epoch_id": terminal_epoch_id,
        "terminal_status_class": terminal_status_class,
        "terminal_status_evidence_id": terminal_status_evidence_id,
        "scope_kind": scope_kind,
        "scope_fingerprint": scope_fingerprint,
        "captured_rfc_count": captured_rfc_count,
        "captured_wfm_count": captured_wfm_count,
    }


def _state_result_from_execution(execution: Any) -> RfcTerminalCascadeStateResult:
    if execution.response_schema != "RfcTerminalCascadeStateV1" or execution.response_version != 1:
        raise SomaError("PERSISTENCE_FAILURE", "terminal cascade command replay response schema is invalid")
    response = execution.response
    required = {
        "proposal_id",
        "trigger_rfc_id",
        "state",
        "proposal_revision",
        "terminal_epoch_id",
        "terminal_status_class",
        "terminal_status_evidence_id",
        "scope_kind",
        "scope_fingerprint",
        "captured_rfc_count",
        "captured_wfm_count",
    }
    if not isinstance(response, dict) or set(response) != required:
        raise SomaError("PERSISTENCE_FAILURE", "terminal cascade command replay response shape is invalid")
    proposal_id = _stored_uuid(response["proposal_id"], field="terminal cascade proposal identity")
    trigger_rfc_id = _stored_uuid(response["trigger_rfc_id"], field="terminal cascade trigger RFC identity")
    state = response["state"]
    if state not in {"pending", "executed", "superseded"}:
        raise SomaError("PERSISTENCE_FAILURE", "terminal cascade command replay state is invalid")
    proposal_revision = _positive_revision(response["proposal_revision"], field="terminal cascade proposal revision")
    terminal_epoch_id = response["terminal_epoch_id"]
    terminal_status_class = response["terminal_status_class"]
    terminal_status_evidence_id = response["terminal_status_evidence_id"]
    scope_kind = response["scope_kind"]
    scope_fingerprint = response["scope_fingerprint"]
    if not isinstance(terminal_epoch_id, str) or not terminal_epoch_id:
        raise SomaError("PERSISTENCE_FAILURE", "terminal cascade command replay epoch is invalid")
    if terminal_status_class not in _TERMINAL_CLASSES:
        raise SomaError("PERSISTENCE_FAILURE", "terminal cascade command replay status class is invalid")
    if not isinstance(terminal_status_evidence_id, str) or not terminal_status_evidence_id:
        raise SomaError("PERSISTENCE_FAILURE", "terminal cascade command replay evidence identity is invalid")
    if scope_kind not in {"exact_rfc", "root_branch"}:
        raise SomaError("PERSISTENCE_FAILURE", "terminal cascade command replay scope kind is invalid")
    if not isinstance(scope_fingerprint, str) or _SHA256_HEX_RE.fullmatch(scope_fingerprint) is None:
        raise SomaError("PERSISTENCE_FAILURE", "terminal cascade command replay scope fingerprint is invalid")
    captured_rfc_count = _nonnegative_count(response["captured_rfc_count"], field="terminal cascade RFC count")
    captured_wfm_count = _nonnegative_count(response["captured_wfm_count"], field="terminal cascade WFM count")
    if captured_rfc_count < 1:
        raise SomaError("PERSISTENCE_FAILURE", "terminal cascade command replay omitted RFC membership")
    return RfcTerminalCascadeStateResult(
        proposal_id=proposal_id,
        trigger_rfc_id=trigger_rfc_id,
        state=state,
        proposal_revision=proposal_revision,
        terminal_epoch_id=terminal_epoch_id,
        terminal_status_class=terminal_status_class,
        terminal_status_evidence_id=terminal_status_evidence_id,
        scope_kind=scope_kind,
        scope_fingerprint=scope_fingerprint,
        captured_rfc_count=captured_rfc_count,
        captured_wfm_count=captured_wfm_count,
        replayed=bool(execution.replayed),
        no_change=bool(execution.no_change),
    )


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


class RfcTerminalCascadeRefreshService:
    """Standalone governed refresh for stale pending RFC terminal-cascade proposals."""

    def __init__(self, connection_factory: ConnectionFactory, task_participant: RfcTerminalTaskParticipant) -> None:
        self._capture = RfcTerminalCascadeCaptureService(task_participant)
        self._boundary = CommandBoundary(
            connection_factory,
            AuditWriter(build_tickets_audit_registry()),
        )

    @staticmethod
    def _load_pending(uow: UnitOfWork, *, proposal_id: str) -> tuple[str, int, str, str, str, str, str, int, int]:
        row = uow.connection.execute(
            "SELECT trigger_rfc_id,revision,terminal_epoch_id,terminal_status_class,terminal_status_evidence_id,"
            "scope_kind,scope_fingerprint,"
            "(SELECT COUNT(*) FROM rfc_terminal_cascade_rfc_members rm WHERE rm.rfc_terminal_cascade_proposal_id=p.rfc_terminal_cascade_proposal_id),"
            "(SELECT COUNT(*) FROM rfc_terminal_cascade_wfm_members wm WHERE wm.rfc_terminal_cascade_proposal_id=p.rfc_terminal_cascade_proposal_id),"
            "proposal_state FROM rfc_terminal_cascade_proposals p WHERE rfc_terminal_cascade_proposal_id=?",
            (proposal_id,),
        ).fetchone()
        if row is None:
            raise SomaError("NOT_FOUND", "RFC terminal cascade proposal does not exist")
        if row[9] != "pending":
            raise SomaError("RFC_TERMINAL_CASCADE_NOT_PENDING", "RFC terminal cascade proposal is not pending")
        trigger_rfc_id = _stored_uuid(row[0], field="terminal cascade trigger RFC identity")
        revision = _positive_revision(row[1], field="terminal cascade proposal revision")
        terminal_epoch_id = row[2]
        terminal_status_class = row[3]
        terminal_status_evidence_id = row[4]
        scope_kind = row[5]
        scope_fingerprint = row[6]
        if not isinstance(terminal_epoch_id, str) or not terminal_epoch_id:
            raise SomaError("PERSISTENCE_FAILURE", "stored terminal cascade epoch is invalid")
        if terminal_status_class not in _TERMINAL_CLASSES:
            raise SomaError("PERSISTENCE_FAILURE", "stored terminal cascade status class is invalid")
        if not isinstance(terminal_status_evidence_id, str) or not terminal_status_evidence_id:
            raise SomaError("PERSISTENCE_FAILURE", "stored terminal cascade evidence identity is invalid")
        if scope_kind not in {"exact_rfc", "root_branch"}:
            raise SomaError("PERSISTENCE_FAILURE", "stored terminal cascade scope kind is invalid")
        if not isinstance(scope_fingerprint, str) or _SHA256_HEX_RE.fullmatch(scope_fingerprint) is None:
            raise SomaError("PERSISTENCE_FAILURE", "stored terminal cascade scope fingerprint is invalid")
        captured_rfc_count = _nonnegative_count(row[7], field="captured RFC count")
        captured_wfm_count = _nonnegative_count(row[8], field="captured WFM count")
        if captured_rfc_count < 1:
            raise SomaError("PERSISTENCE_FAILURE", "pending terminal cascade omitted RFC membership")
        return (
            trigger_rfc_id,
            revision,
            terminal_epoch_id,
            terminal_status_class,
            terminal_status_evidence_id,
            scope_kind,
            scope_fingerprint,
            captured_rfc_count,
            captured_wfm_count,
        )

    @staticmethod
    def _current_terminal_binding(
        uow: UnitOfWork,
        *,
        trigger_rfc_id: str,
        terminal_epoch_id: str,
    ) -> tuple[str, str]:
        row = uow.connection.execute(
            "SELECT status_class,status_evidence_id,terminal_epoch_id "
            "FROM rfc_current_source_projection WHERE rfc_id=?",
            (trigger_rfc_id,),
        ).fetchone()
        if (
            row is None
            or row[2] is None
            or str(row[2]) != terminal_epoch_id
            or row[0] not in _TERMINAL_CLASSES
            or not isinstance(row[1], str)
            or not row[1]
        ):
            raise SomaError(
                "RFC_TERMINAL_CASCADE_STALE",
                "RFC terminal cascade proposal no longer belongs to the current terminal epoch",
            )
        return str(row[0]), str(row[1])

    @staticmethod
    def _insert_replacement(
        uow: UnitOfWork,
        *,
        replacement_id: str,
        scope: RfcTerminalCascadeScope,
        command_id: str,
        created_at_utc: int,
    ) -> None:
        uow.connection.execute(
            "INSERT INTO rfc_terminal_cascade_proposals("
            "rfc_terminal_cascade_proposal_id,trigger_rfc_id,terminal_epoch_id,terminal_status_class,"
            "terminal_status_evidence_id,scope_kind,scope_fingerprint,proposal_state,revision,created_at_utc,"
            "created_command_id,executed_at_utc,executed_command_id,superseded_at_utc,superseded_command_id"
            ") VALUES (?, ?, ?, ?, ?, ?, ?, 'pending', 1, ?, ?, NULL, NULL, NULL, NULL)",
            (
                replacement_id,
                scope.trigger_rfc_id,
                scope.terminal_epoch_id,
                scope.terminal_status_class,
                scope.terminal_status_evidence_id,
                scope.scope_kind,
                scope.scope_fingerprint,
                created_at_utc,
                command_id,
            ),
        )
        for ordinal, member in enumerate(scope.rfc_members):
            uow.connection.execute(
                "INSERT INTO rfc_terminal_cascade_rfc_members("
                "rfc_terminal_cascade_proposal_id,rfc_id,captured_rfc_revision,captured_role,ordinal"
                ") VALUES (?, ?, ?, ?, ?)",
                (
                    replacement_id,
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
                    replacement_id,
                    member.task_id,
                    member.owning_rfc_id,
                    member.captured_task_revision,
                    member.captured_task_no,
                    ordinal,
                ),
            )

    def refresh(
        self,
        *,
        command_id: str,
        proposal_id: str,
        proposal_revision: int,
        actor_kind: str = "local_user",
        actor_id: str | None = None,
    ) -> RfcTerminalCascadeStateResult:
        canonical_proposal_id = _request_uuid(proposal_id, field="proposal_id")
        envelope = CommandEnvelope(
            command_id=command_id,
            command_type="RefreshRfcTerminalCascadeProposal",
            target_type="rfc_terminal_cascade_proposal",
            target_id=canonical_proposal_id,
            semantic_payload={"proposal_id": canonical_proposal_id},
            base_revisions={"rfc_terminal_cascade_proposal": proposal_revision},
        )

        def prepare(uow: UnitOfWork) -> PreparedMutation:
            (
                trigger_rfc_id,
                stored_revision,
                terminal_epoch_id,
                prior_status_class,
                prior_evidence_id,
                prior_scope_kind,
                prior_scope_fingerprint,
                prior_rfc_count,
                prior_wfm_count,
            ) = self._load_pending(uow, proposal_id=canonical_proposal_id)
            if stored_revision != proposal_revision:
                raise SomaError(
                    "RFC_TERMINAL_CASCADE_STALE",
                    "RFC terminal cascade proposal revision changed before refresh",
                )
            current_status_class, current_evidence_id = self._current_terminal_binding(
                uow,
                trigger_rfc_id=trigger_rfc_id,
                terminal_epoch_id=terminal_epoch_id,
            )
            scope = self._capture.capture_scope(
                uow,
                trigger_rfc_id=trigger_rfc_id,
                terminal_epoch_id=terminal_epoch_id,
                terminal_status_class=current_status_class,
                terminal_status_evidence_id=current_evidence_id,
            )
            unchanged = (
                current_status_class == prior_status_class
                and current_evidence_id == prior_evidence_id
                and scope.scope_kind == prior_scope_kind
                and scope.scope_fingerprint == prior_scope_fingerprint
            )
            if unchanged:
                return PreparedMutation(
                    True,
                    None,
                    None,
                    response_schema="RfcTerminalCascadeStateV1",
                    response=_state_response(
                        proposal_id=canonical_proposal_id,
                        trigger_rfc_id=trigger_rfc_id,
                        state="pending",
                        proposal_revision=stored_revision,
                        terminal_epoch_id=terminal_epoch_id,
                        terminal_status_class=prior_status_class,
                        terminal_status_evidence_id=prior_evidence_id,
                        scope_kind=prior_scope_kind,
                        scope_fingerprint=prior_scope_fingerprint,
                        captured_rfc_count=prior_rfc_count,
                        captured_wfm_count=prior_wfm_count,
                    ),
                )

            replacement_id = new_uuid4()
            audit_event_id = new_uuid4()
            now = utc_epoch_seconds()
            response = _state_response(
                proposal_id=replacement_id,
                trigger_rfc_id=trigger_rfc_id,
                state="pending",
                proposal_revision=1,
                terminal_epoch_id=terminal_epoch_id,
                terminal_status_class=current_status_class,
                terminal_status_evidence_id=current_evidence_id,
                scope_kind=scope.scope_kind,
                scope_fingerprint=scope.scope_fingerprint,
                captured_rfc_count=len(scope.rfc_members),
                captured_wfm_count=len(scope.wfm_members),
            )

            def apply(inner: UnitOfWork) -> AuditEventInput:
                updated = inner.connection.execute(
                    "UPDATE rfc_terminal_cascade_proposals SET proposal_state='superseded',revision=revision+1,"
                    "superseded_at_utc=?,superseded_command_id=? "
                    "WHERE rfc_terminal_cascade_proposal_id=? AND proposal_state='pending' AND revision=?",
                    (now, command_id, canonical_proposal_id, stored_revision),
                )
                if updated.rowcount != 1:
                    raise SomaError(
                        "RFC_TERMINAL_CASCADE_STALE",
                        "RFC terminal cascade proposal changed before refresh publication",
                    )
                self._insert_replacement(
                    inner,
                    replacement_id=replacement_id,
                    scope=scope,
                    command_id=command_id,
                    created_at_utc=now,
                )
                return AuditEventInput(
                    audit_event_id=audit_event_id,
                    action_type="ticket.rfc.terminal_cascade_refreshed",
                    action_version=1,
                    actor_kind=actor_kind,
                    actor_id=actor_id,
                    target_type="rfc_terminal_cascade_proposal",
                    target_id=canonical_proposal_id,
                    reason_category=None,
                    command_id=command_id,
                    payload_schema="RfcTerminalCascadeRefreshAuditV1",
                    payload_version=1,
                    payload={
                        "prior_proposal_id": canonical_proposal_id,
                        "prior_proposal_revision": stored_revision,
                        "resulting_prior_proposal_revision": stored_revision + 1,
                        "replacement_proposal_id": replacement_id,
                        "replacement_proposal_revision": 1,
                        "terminal_epoch_id": terminal_epoch_id,
                        "prior_terminal_status_class": prior_status_class,
                        "replacement_terminal_status_class": current_status_class,
                        "prior_terminal_status_evidence_id": prior_evidence_id,
                        "replacement_terminal_status_evidence_id": current_evidence_id,
                        "prior_scope_fingerprint": prior_scope_fingerprint,
                        "replacement_scope_fingerprint": scope.scope_fingerprint,
                        "state_transition": "pending_to_superseded_with_replacement_pending",
                        "reason_category": None,
                    },
                    resulting_event_refs=(
                        AuditResultRef("rfc_terminal_cascade_proposal", replacement_id),
                    ),
                )

            return PreparedMutation(
                False,
                "rfc_terminal_cascade_proposal",
                replacement_id,
                apply,
                response_schema="RfcTerminalCascadeStateV1",
                response=response,
            )

        return _state_result_from_execution(self._boundary.execute(envelope, prepare))
