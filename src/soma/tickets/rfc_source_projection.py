from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Protocol

from soma.foundation.audit.writer import AuditEventInput, AuditResultRef
from soma.foundation.errors import SomaError
from soma.foundation.identifiers import new_uuid4, utc_epoch_seconds
from soma.foundation.persistence.uow import UnitOfWork
from soma.tickets.queries.rfc_lifecycle import RfcLifecycleProjection, RfcLifecycleQueryService


_FIELD_SPECS: dict[str, tuple[str, str, str]] = {
    "summary": ("summary_text", "summary_evidence_id", "text"),
    "external_created_at": ("external_created_at_utc", "external_created_evidence_id", "instant"),
    "creator": ("creator_text", "creator_evidence_id", "text"),
    "customer_account_number": ("customer_account_number_text", "customer_account_number_evidence_id", "text"),
    "customer_account_name": ("customer_account_name_text", "customer_account_name_evidence_id", "text"),
    "severity": ("severity_text", "severity_evidence_id", "text"),
    "status": ("status_text", "status_evidence_id", "controlled"),
    "owner_external_id": ("owner_external_id_text", "owner_external_id_evidence_id", "text"),
    "owner_name": ("owner_name_text", "owner_name_evidence_id", "text"),
    "l1_handler_name": ("l1_handler_name_text", "l1_handler_name_evidence_id", "text"),
    "l2_handler_name": ("l2_handler_name_text", "l2_handler_name_evidence_id", "text"),
    "last_update": ("last_update_utc", "last_update_evidence_id", "instant"),
}
_FIELD_ORDER = tuple(_FIELD_SPECS)
_STATUS_CLASSES = frozenset({"pre_implement", "implement_eligible", "terminal_closed", "terminal_cancelled"})
_STATUS_AUTHORITIES = frozenset({"enhanced_rfc", "wfm_provisional"})
_TERMINAL_STATUS_CLASSES = frozenset({"terminal_closed", "terminal_cancelled"})
_HEX64_RE = re.compile(r"[0-9a-f]{64}\Z")


class RfcSourceEvidenceProvider(Protocol):
    def validate_accepted_delta(
        self,
        uow: UnitOfWork,
        rfc_id: str,
        delta: "RfcAcceptedFieldDelta",
        evidence_id: str,
    ) -> str: ...

    def has_accepted_source_provenance(self, uow: UnitOfWork, rfc_id: str) -> str: ...

    def source_freshness_token(self, uow: UnitOfWork, rfc_id: str) -> str: ...


class RfcTerminalCascadeCaptureParticipant(Protocol):
    def capture_pending(
        self,
        uow: UnitOfWork,
        *,
        trigger_rfc_id: str,
        terminal_epoch_id: str,
        terminal_status_class: str,
        terminal_status_evidence_id: str,
        accepted_command_id: str,
    ) -> str: ...


@dataclass(frozen=True, slots=True)
class RfcAcceptedFieldDelta:
    field_key: str
    value_kind: str
    value: str | int
    evidence_id: str
    status_class: str | None = None
    status_authority: str | None = None


@dataclass(frozen=True, slots=True)
class RfcSourceProjectionApplyResult:
    lifecycle_projection: RfcLifecycleProjection
    changed_field_keys: tuple[str, ...]
    source_evidence_ids: tuple[str, ...]
    pending_cascade_proposal_id: str | None
    no_change: bool
    result_refs: tuple[tuple[str, str], ...]
    audit_events: tuple[AuditEventInput, ...]


def _invalid(message: str) -> SomaError:
    return SomaError("RFC_SOURCE_PROJECTION_INVALID", message)


def _validate_delta_shape(delta: RfcAcceptedFieldDelta) -> tuple[str, str, str]:
    try:
        value_column, evidence_column, expected_kind = _FIELD_SPECS[delta.field_key]
    except KeyError as exc:
        raise _invalid("RFC source field is outside the closed accepted field registry") from exc
    if delta.value_kind != expected_kind:
        raise _invalid("RFC source field value kind does not match the closed field registry")
    if not isinstance(delta.evidence_id, str) or not delta.evidence_id:
        raise _invalid("RFC source evidence identity is required")
    if expected_kind == "instant":
        if type(delta.value) is not int or delta.value < 0:
            raise _invalid("RFC instant source value must be a non-negative integer")
    elif not isinstance(delta.value, str) or not delta.value:
        raise _invalid("RFC text/controlled source value must be non-empty text")
    if delta.field_key == "status":
        if delta.status_class not in _STATUS_CLASSES or delta.status_authority not in _STATUS_AUTHORITIES:
            raise _invalid("RFC Status requires accepted class and source authority")
    elif delta.status_class is not None or delta.status_authority is not None:
        raise _invalid("status classification/authority may appear only on RFC Status")
    return value_column, evidence_column, expected_kind


class RfcSourceProjectionService:
    """LLD-03 owner of accepted RFC source projection inside LLD-04's shared UnitOfWork."""

    def __init__(
        self,
        evidence_provider: RfcSourceEvidenceProvider,
        *,
        terminal_capture_participant: RfcTerminalCascadeCaptureParticipant | None = None,
    ) -> None:
        self._evidence_provider = evidence_provider
        self._terminal_capture = terminal_capture_participant

    @staticmethod
    def _current(reader: Any, rfc_id: str) -> dict[str, Any] | None:
        cursor = reader.execute("SELECT * FROM rfc_current_source_projection WHERE rfc_id=?", (rfc_id,))
        row = cursor.fetchone()
        if row is None:
            return None
        names = tuple(column[0] for column in cursor.description)
        return {name: value for name, value in zip(names, row, strict=True)}

    @staticmethod
    def _require_outer_receipt(uow: UnitOfWork, accepted_command_id: str) -> None:
        receipt = uow.connection.execute(
            "SELECT 1 FROM command_receipts WHERE command_id=?",
            (accepted_command_id,),
        ).fetchone()
        if receipt is None:
            raise SomaError("PERSISTENCE_FAILURE", "accepted RFC source projection requires the outer command receipt")

    @staticmethod
    def _assert_rfc_exists(uow: UnitOfWork, rfc_id: str) -> None:
        if uow.connection.execute("SELECT 1 FROM rfcs WHERE rfc_id=?", (rfc_id,)).fetchone() is None:
            raise SomaError("NOT_FOUND", "RFC does not exist")

    @staticmethod
    def _pending_for_epoch(reader: Any, rfc_id: str, terminal_epoch_id: str) -> Any | None:
        return reader.execute(
            "SELECT rfc_terminal_cascade_proposal_id,revision FROM rfc_terminal_cascade_proposals "
            "WHERE trigger_rfc_id=? AND terminal_epoch_id=? AND proposal_state='pending'",
            (rfc_id, terminal_epoch_id),
        ).fetchone()

    @staticmethod
    def _supersede_pending_for_reversal(
        uow: UnitOfWork,
        *,
        rfc_id: str,
        terminal_epoch_id: str,
        accepted_command_id: str,
        occurred_at_utc: int,
    ) -> None:
        pending = RfcSourceProjectionService._pending_for_epoch(uow.connection, rfc_id, terminal_epoch_id)
        if pending is None:
            return
        updated = uow.connection.execute(
            "UPDATE rfc_terminal_cascade_proposals SET proposal_state='superseded',revision=revision+1,"
            "superseded_at_utc=?,superseded_command_id=? "
            "WHERE rfc_terminal_cascade_proposal_id=? AND proposal_state='pending' AND revision=?",
            (occurred_at_utc, accepted_command_id, str(pending[0]), int(pending[1])),
        )
        if updated.rowcount != 1:
            raise SomaError("RFC_TERMINAL_CASCADE_STALE", "pending terminal cascade changed during reviewed reversal")

    @staticmethod
    def _verify_captured_proposal(
        uow: UnitOfWork,
        *,
        proposal_id: str,
        rfc_id: str,
        terminal_epoch_id: str,
        terminal_status_class: str,
        terminal_status_evidence_id: str,
        accepted_command_id: str,
    ) -> None:
        proposal = uow.connection.execute(
            "SELECT trigger_rfc_id,terminal_epoch_id,terminal_status_class,terminal_status_evidence_id,proposal_state,"
            "created_command_id FROM rfc_terminal_cascade_proposals WHERE rfc_terminal_cascade_proposal_id=?",
            (proposal_id,),
        ).fetchone()
        if proposal is None or tuple(proposal) != (
            rfc_id,
            terminal_epoch_id,
            terminal_status_class,
            terminal_status_evidence_id,
            "pending",
            accepted_command_id,
        ):
            raise SomaError(
                "RFC_TERMINAL_CASCADE_PARTICIPANT_FAILED",
                "terminal capture participant did not persist the exact pending proposal",
            )
        member = uow.connection.execute(
            "SELECT 1 FROM rfc_terminal_cascade_rfc_members "
            "WHERE rfc_terminal_cascade_proposal_id=? AND rfc_id=?",
            (proposal_id, rfc_id),
        ).fetchone()
        if member is None:
            raise SomaError(
                "RFC_TERMINAL_CASCADE_PARTICIPANT_FAILED",
                "terminal capture participant omitted the triggering RFC from immutable membership",
            )

    @staticmethod
    def _status_is_terminal(status_class: str | None) -> bool:
        return status_class in _TERMINAL_STATUS_CLASSES

    def apply_accepted_field_deltas(
        self,
        uow: UnitOfWork,
        *,
        rfc_id: str,
        accepted_command_id: str,
        deltas: tuple[RfcAcceptedFieldDelta, ...],
        review_fingerprint: str | None = None,
        actor_kind: str = "local_user",
        actor_id: str | None = None,
    ) -> RfcSourceProjectionApplyResult:
        self._require_outer_receipt(uow, accepted_command_id)
        self._assert_rfc_exists(uow, rfc_id)
        if review_fingerprint is not None and _HEX64_RE.fullmatch(review_fingerprint) is None:
            raise _invalid("RFC source review fingerprint must be lowercase SHA-256 hex")
        if len(deltas) > len(_FIELD_SPECS):
            raise _invalid("RFC source delta set exceeds the closed field registry")

        current = self._current(uow.connection, rfc_id)
        prior_projection_revision = None if current is None else int(current["revision"])
        prior_status_class = "unknown" if current is None else str(current["status_class"])
        prior_terminal_epoch = None if current is None or current["terminal_epoch_id"] is None else str(current["terminal_epoch_id"])

        seen: set[str] = set()
        changes: dict[str, object] = {}
        changed_fields: list[str] = []
        evidence_ids: list[str] = []
        accepted_status_delta: RfcAcceptedFieldDelta | None = None

        for delta in deltas:
            value_column, evidence_column, _expected_kind = _validate_delta_shape(delta)
            if delta.field_key in seen:
                raise _invalid("RFC source delta set contains the same field more than once")
            seen.add(delta.field_key)
            provider_state = self._evidence_provider.validate_accepted_delta(uow, rfc_id, delta, delta.evidence_id)
            if provider_state != "VALID":
                raise _invalid("RFC source delta no longer resolves to exact accepted LLD-04 evidence")

            if delta.field_key == "status":
                current_authority = None if current is None else current["status_authority"]
                if current_authority == "enhanced_rfc" and delta.status_authority == "wfm_provisional":
                    continue
                same_status = (
                    current is not None
                    and current["status_text"] == delta.value
                    and current["status_class"] == delta.status_class
                    and current["status_authority"] == delta.status_authority
                )
                if same_status:
                    continue
                accepted_status_delta = delta
                changes[value_column] = delta.value
                changes[evidence_column] = delta.evidence_id
                changes["status_class"] = delta.status_class
                changes["status_authority"] = delta.status_authority
            else:
                if current is not None and current[value_column] == delta.value:
                    continue
                changes[value_column] = delta.value
                changes[evidence_column] = delta.evidence_id
            changed_fields.append(delta.field_key)
            evidence_ids.append(delta.evidence_id)

        if not changes:
            lifecycle = RfcLifecycleQueryService.get_from_connection(uow.connection, rfc_id=rfc_id)
            return RfcSourceProjectionApplyResult(
                lifecycle_projection=lifecycle,
                changed_field_keys=(),
                source_evidence_ids=(),
                pending_cascade_proposal_id=None,
                no_change=True,
                result_refs=(),
                audit_events=(),
            )

        resulting_status_class = prior_status_class
        resulting_terminal_epoch = prior_terminal_epoch
        pending_cascade_proposal_id: str | None = None
        now = utc_epoch_seconds()

        if accepted_status_delta is not None:
            assert accepted_status_delta.status_class is not None
            resulting_status_class = accepted_status_delta.status_class
            was_terminal = self._status_is_terminal(prior_status_class)
            becomes_terminal = self._status_is_terminal(resulting_status_class)
            if not was_terminal and becomes_terminal:
                if self._terminal_capture is None:
                    raise SomaError(
                        "RFC_TERMINAL_CASCADE_PARTICIPANT_FAILED",
                        "terminal RFC source acceptance requires exact cascade capture participant",
                    )
                resulting_terminal_epoch = new_uuid4()
                changes["terminal_epoch_id"] = resulting_terminal_epoch
                pending_cascade_proposal_id = self._terminal_capture.capture_pending(
                    uow,
                    trigger_rfc_id=rfc_id,
                    terminal_epoch_id=resulting_terminal_epoch,
                    terminal_status_class=resulting_status_class,
                    terminal_status_evidence_id=accepted_status_delta.evidence_id,
                    accepted_command_id=accepted_command_id,
                )
                if not isinstance(pending_cascade_proposal_id, str) or not pending_cascade_proposal_id:
                    raise SomaError(
                        "RFC_TERMINAL_CASCADE_PARTICIPANT_FAILED",
                        "terminal capture participant returned no pending proposal identity",
                    )
                self._verify_captured_proposal(
                    uow,
                    proposal_id=pending_cascade_proposal_id,
                    rfc_id=rfc_id,
                    terminal_epoch_id=resulting_terminal_epoch,
                    terminal_status_class=resulting_status_class,
                    terminal_status_evidence_id=accepted_status_delta.evidence_id,
                    accepted_command_id=accepted_command_id,
                )
            elif was_terminal and becomes_terminal:
                if prior_terminal_epoch is None:
                    raise SomaError("PERSISTENCE_FAILURE", "terminal RFC projection is missing terminal epoch identity")
                resulting_terminal_epoch = prior_terminal_epoch
                changes["terminal_epoch_id"] = prior_terminal_epoch
            elif was_terminal and not becomes_terminal:
                if review_fingerprint is None:
                    raise SomaError(
                        "RFC_STATUS_REVERSAL_REVIEW_REQUIRED",
                        "terminal RFC source presentation requires exact reviewed reversal context",
                    )
                if prior_terminal_epoch is None:
                    raise SomaError("PERSISTENCE_FAILURE", "terminal RFC projection is missing terminal epoch identity")
                self._supersede_pending_for_reversal(
                    uow,
                    rfc_id=rfc_id,
                    terminal_epoch_id=prior_terminal_epoch,
                    accepted_command_id=accepted_command_id,
                    occurred_at_utc=now,
                )
                resulting_terminal_epoch = None
                changes["terminal_epoch_id"] = None
            else:
                resulting_terminal_epoch = None
                changes["terminal_epoch_id"] = None

        if current is None:
            columns = ["rfc_id", *changes.keys(), "revision"]
            placeholders = ",".join("?" for _ in columns)
            uow.connection.execute(
                f"INSERT INTO rfc_current_source_projection({','.join(columns)}) VALUES ({placeholders})",
                [rfc_id, *changes.values(), 1],
            )
            resulting_projection_revision = 1
        else:
            assignments = ",".join(f"{column}=?" for column in changes)
            updated = uow.connection.execute(
                f"UPDATE rfc_current_source_projection SET {assignments},revision=revision+1 "
                "WHERE rfc_id=? AND revision=?",
                [*changes.values(), rfc_id, prior_projection_revision],
            )
            if updated.rowcount != 1:
                raise _invalid("RFC source projection changed before accepted deltas were applied")
            resulting_projection_revision = int(prior_projection_revision) + 1

        lifecycle = RfcLifecycleQueryService.get_from_connection(uow.connection, rfc_id=rfc_id)
        ordered_changed_fields = tuple(field for field in _FIELD_ORDER if field in changed_fields)
        evidence_by_field = {field: evidence for field, evidence in zip(changed_fields, evidence_ids, strict=True)}
        ordered_evidence_ids = tuple(evidence_by_field[field] for field in ordered_changed_fields)
        audit_event_id = new_uuid4()
        result_refs: list[tuple[str, str]] = [("rfc_source_projection", rfc_id)]
        audit_refs: list[AuditResultRef] = [AuditResultRef("rfc_source_projection", rfc_id)]
        if pending_cascade_proposal_id is not None:
            result_refs.append(("rfc_terminal_cascade_proposal", pending_cascade_proposal_id))
            audit_refs.append(AuditResultRef("rfc_terminal_cascade_proposal", pending_cascade_proposal_id))

        audit = AuditEventInput(
            audit_event_id=audit_event_id,
            action_type="ticket.rfc.source_projection_applied",
            action_version=1,
            actor_kind=actor_kind,
            actor_id=actor_id,
            target_type="rfc",
            target_id=rfc_id,
            command_id=accepted_command_id,
            payload_schema="RfcSourceProjectionAuditV1",
            payload_version=1,
            payload={
                "rfc_id": rfc_id,
                "prior_projection_revision": prior_projection_revision,
                "resulting_projection_revision": resulting_projection_revision,
                "changed_field_keys": list(ordered_changed_fields),
                "source_evidence_ids": list(ordered_evidence_ids),
                "status_class_before": prior_status_class,
                "status_class_after": resulting_status_class,
                "terminal_epoch_id": resulting_terminal_epoch,
                "pending_cascade_proposal_id": pending_cascade_proposal_id,
                "review_fingerprint": review_fingerprint,
            },
            resulting_event_refs=tuple(audit_refs),
        )
        return RfcSourceProjectionApplyResult(
            lifecycle_projection=lifecycle,
            changed_field_keys=ordered_changed_fields,
            source_evidence_ids=ordered_evidence_ids,
            pending_cascade_proposal_id=pending_cascade_proposal_id,
            no_change=False,
            result_refs=tuple(result_refs),
            audit_events=(audit,),
        )
