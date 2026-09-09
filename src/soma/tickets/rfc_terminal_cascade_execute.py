from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol

from soma.foundation.application.command_boundary import CommandBoundary, CommandEnvelope, PreparedMutation
from soma.foundation.audit.writer import AuditEventInput, AuditResultRef, AuditWriter
from soma.foundation.errors import SomaError, ValidationError
from soma.foundation.identifiers import new_uuid4, require_uuid4, utc_epoch_seconds
from soma.foundation.persistence.connections import ConnectionFactory
from soma.foundation.persistence.uow import UnitOfWork

from .audit_registry import build_tickets_audit_registry
from .queries.rfc_terminal_cascade import (
    RfcTerminalCascadeImpactProviderPage,
    RfcTerminalCascadePreviewService,
    RfcTerminalCascadeProposalSnapshot,
    terminal_cascade_preview_fingerprint,
)
from .rfc_terminal_cascade import (
    RfcTerminalCascadeCaptureService,
    RfcTerminalTaskParticipant,
    RfcTerminalCascadeStateResult,
    _request_uuid,
    _state_response,
    _state_result_from_execution,
)
from .rfc_terminal_review import RfcTerminalCascadeExecutionReview

_EXECUTE_ACTION = "tickets.rfc.terminal_cascade.execute"
_TARGET_TYPE = "rfc_terminal_cascade_proposal"
_MAX_PARTICIPANT_RESULT_REFS = 64
_TASK_RESULT_TYPES = frozenset({"task", "objective"})
_COMMUNICATION_RESULT_TYPES = frozenset({"communication_link"})


@dataclass(frozen=True, slots=True)
class DeliberateActionTargetV1:
    target_type: str
    target_id: str


class RfcTerminalTaskExecutionParticipant(RfcTerminalTaskParticipant, Protocol):
    def revalidate_terminal_cascade(
        self,
        uow: UnitOfWork,
        proposal_snapshot: RfcTerminalCascadeProposalSnapshot,
        reviewed_exact_count: int,
        reviewed_provider_fingerprint: str,
    ) -> str: ...

    def apply_terminal_cascade(
        self,
        uow: UnitOfWork,
        proposal_snapshot: RfcTerminalCascadeProposalSnapshot,
    ) -> tuple[AuditResultRef, ...]: ...


class RfcTerminalCommunicationExecutionParticipant(Protocol):
    def revalidate_terminal_cascade(
        self,
        uow: UnitOfWork,
        proposal_snapshot: RfcTerminalCascadeProposalSnapshot,
        reviewed_exact_count: int,
        reviewed_provider_fingerprint: str,
    ) -> str: ...

    def apply_terminal_cascade(
        self,
        uow: UnitOfWork,
        proposal_snapshot: RfcTerminalCascadeProposalSnapshot,
    ) -> tuple[AuditResultRef, ...]: ...


class DeliberateActionProofProvider(Protocol):
    def validate_and_consume(
        self,
        uow: UnitOfWork,
        proof: object,
        expected_action: str,
        target: DeliberateActionTargetV1,
        base_revision: int,
        preview_fingerprint: str | None,
    ) -> object: ...


def _normalize_result_refs(
    raw: object,
    *,
    allowed_types: frozenset[str],
    participant_name: str,
) -> tuple[AuditResultRef, ...]:
    if not isinstance(raw, tuple) or len(raw) > _MAX_PARTICIPANT_RESULT_REFS:
        raise SomaError(
            "RFC_TERMINAL_CASCADE_PARTICIPANT_FAILED",
            f"{participant_name} terminal cascade apply returned invalid result references",
        )
    normalized: list[AuditResultRef] = []
    seen: set[tuple[str, str]] = set()
    for ref in raw:
        if not isinstance(ref, AuditResultRef) or ref.result_type not in allowed_types:
            raise SomaError(
                "RFC_TERMINAL_CASCADE_PARTICIPANT_FAILED",
                f"{participant_name} terminal cascade apply returned an invalid result reference type",
            )
        try:
            result_id = require_uuid4(ref.result_id)
        except ValidationError as exc:
            raise SomaError(
                "RFC_TERMINAL_CASCADE_PARTICIPANT_FAILED",
                f"{participant_name} terminal cascade apply returned a non-canonical result identity",
            ) from exc
        key = (ref.result_type, result_id)
        if key in seen:
            raise SomaError(
                "RFC_TERMINAL_CASCADE_PARTICIPANT_FAILED",
                f"{participant_name} terminal cascade apply returned duplicate result references",
            )
        seen.add(key)
        normalized.append(AuditResultRef(ref.result_type, result_id))
    return tuple(normalized)


def _refs_payload(refs: tuple[AuditResultRef, ...]) -> list[dict[str, str]]:
    return [
        {"result_type": ref.result_type, "result_id": ref.result_id}
        for ref in refs
    ]


class RfcTerminalCascadeExecutionService:
    """LLD-03 owner for reviewed, deliberate RFC terminal-cascade execution."""

    def __init__(
        self,
        connection_factory: ConnectionFactory,
        task_participant: RfcTerminalTaskExecutionParticipant,
        communication_participant: RfcTerminalCommunicationExecutionParticipant,
        deliberate_action_proof_provider: DeliberateActionProofProvider,
    ) -> None:
        self._capture = RfcTerminalCascadeCaptureService(task_participant)
        self._task_participant = task_participant
        self._communication_participant = communication_participant
        self._proof_provider = deliberate_action_proof_provider
        self._preview_reader = RfcTerminalCascadePreviewService(
            connection_factory,
            task_participant,
            communication_participant,
        )
        self._boundary = CommandBoundary(
            connection_factory,
            AuditWriter(build_tickets_audit_registry()),
        )

    @staticmethod
    def _revalidate_participant(
        participant: object,
        uow: UnitOfWork,
        proposal: RfcTerminalCascadeProposalSnapshot,
        *,
        reviewed_exact_count: int,
        reviewed_provider_fingerprint: str,
        participant_name: str,
    ) -> None:
        try:
            status = participant.revalidate_terminal_cascade(
                uow,
                proposal,
                reviewed_exact_count,
                reviewed_provider_fingerprint,
            )
        except Exception as exc:
            raise SomaError(
                "RFC_TERMINAL_CASCADE_PARTICIPANT_FAILED",
                f"{participant_name} terminal cascade revalidation failed",
            ) from exc
        if status == "STALE":
            raise SomaError(
                "RFC_TERMINAL_CASCADE_STALE",
                f"{participant_name} terminal cascade impact authority changed after review",
            )
        if status != "READY":
            raise SomaError(
                "RFC_TERMINAL_CASCADE_PARTICIPANT_FAILED",
                f"{participant_name} terminal cascade impact authority is indeterminate",
            )

    @staticmethod
    def _apply_participant(
        participant: object,
        uow: UnitOfWork,
        proposal: RfcTerminalCascadeProposalSnapshot,
        *,
        allowed_types: frozenset[str],
        participant_name: str,
    ) -> tuple[AuditResultRef, ...]:
        try:
            raw_refs = participant.apply_terminal_cascade(uow, proposal)
        except Exception as exc:
            raise SomaError(
                "RFC_TERMINAL_CASCADE_PARTICIPANT_FAILED",
                f"{participant_name} terminal cascade apply failed",
            ) from exc
        return _normalize_result_refs(
            raw_refs,
            allowed_types=allowed_types,
            participant_name=participant_name,
        )

    def execute(
        self,
        *,
        command_id: str,
        proposal_id: str,
        proposal_revision: int,
        execution_review: RfcTerminalCascadeExecutionReview,
        deliberate_action_proof: object,
        actor_kind: str = "local_user",
        actor_id: str | None = None,
    ) -> RfcTerminalCascadeStateResult:
        canonical_proposal_id = _request_uuid(proposal_id, field="proposal_id")
        if not isinstance(execution_review, RfcTerminalCascadeExecutionReview):
            raise ValidationError("execution_review must be RfcTerminalCascadeExecutionReview")

        envelope = CommandEnvelope(
            command_id=command_id,
            command_type="ExecuteRfcTerminalCascade",
            target_type=_TARGET_TYPE,
            target_id=canonical_proposal_id,
            semantic_payload={
                "proposal_id": canonical_proposal_id,
                "execution_review": execution_review.to_response(),
            },
            base_revisions={_TARGET_TYPE: proposal_revision},
            authorizing_fingerprints={"preview_fingerprint": execution_review.preview_fingerprint},
        )

        def prepare(uow: UnitOfWork) -> PreparedMutation:
            state = self._preview_reader._load_pending_state_by_id(
                uow.connection,
                proposal_id=canonical_proposal_id,
            )
            if state.proposal_revision != proposal_revision:
                raise SomaError(
                    "RFC_TERMINAL_CASCADE_STALE",
                    "RFC terminal cascade proposal revision changed after review",
                )
            proposal = self._preview_reader._persisted_snapshot(
                uow.connection,
                state=state,
            )

            current_scope = self._capture.capture_scope(
                uow,
                trigger_rfc_id=state.trigger_rfc_id,
                terminal_epoch_id=state.terminal_epoch_id,
                terminal_status_class=state.terminal_status_class,
                terminal_status_evidence_id=state.terminal_status_evidence_id,
            )
            persisted_member_count = len(proposal.rfc_members) + len(proposal.wfm_members)
            current_member_count = len(current_scope.rfc_members) + len(current_scope.wfm_members)
            if (
                current_scope.scope_kind != state.scope_kind
                or current_scope.scope_fingerprint != state.scope_fingerprint
                or current_member_count != persisted_member_count
            ):
                raise SomaError(
                    "RFC_TERMINAL_CASCADE_STALE",
                    "RFC terminal cascade RFC/WFM scope changed after review",
                )

            self._revalidate_participant(
                self._task_participant,
                uow,
                proposal,
                reviewed_exact_count=execution_review.task_objective_exact_count,
                reviewed_provider_fingerprint=execution_review.task_objective_provider_fingerprint,
                participant_name="Task/Objective",
            )
            self._revalidate_participant(
                self._communication_participant,
                uow,
                proposal,
                reviewed_exact_count=execution_review.communication_exact_count,
                reviewed_provider_fingerprint=execution_review.communication_provider_fingerprint,
                participant_name="Communication",
            )

            task_meta = RfcTerminalCascadeImpactProviderPage(
                domain="TASKS_OBJECTIVES",
                status="READY",
                exact_count=execution_review.task_objective_exact_count,
                provider_fingerprint=execution_review.task_objective_provider_fingerprint,
            )
            communication_meta = RfcTerminalCascadeImpactProviderPage(
                domain="COMMUNICATIONS",
                status="READY",
                exact_count=execution_review.communication_exact_count,
                provider_fingerprint=execution_review.communication_provider_fingerprint,
            )
            current_preview_fingerprint = terminal_cascade_preview_fingerprint(
                proposal_id=proposal.proposal_id,
                proposal_revision=proposal.proposal_revision,
                persisted_scope_fingerprint=proposal.scope_fingerprint,
                current_scope_fingerprint=current_scope.scope_fingerprint,
                persisted_member_count=persisted_member_count,
                current_member_count=current_member_count,
                stale_reasons=(),
                task_page=task_meta,
                communication_page=communication_meta,
            )
            if current_preview_fingerprint != execution_review.preview_fingerprint:
                raise SomaError(
                    "RFC_TERMINAL_CASCADE_STALE",
                    "RFC terminal cascade reviewed preview no longer matches current authority",
                )

            target = DeliberateActionTargetV1(
                target_type=_TARGET_TYPE,
                target_id=canonical_proposal_id,
            )
            try:
                validated = self._proof_provider.validate_and_consume(
                    uow,
                    deliberate_action_proof,
                    _EXECUTE_ACTION,
                    target,
                    proposal_revision,
                    execution_review.preview_fingerprint,
                )
            except Exception as exc:
                raise SomaError(
                    "RFC_TERMINAL_CASCADE_CONFIRMATION_REQUIRED",
                    "RFC terminal cascade deliberate-action proof is invalid or unavailable",
                ) from exc
            if validated is None:
                raise SomaError(
                    "RFC_TERMINAL_CASCADE_CONFIRMATION_REQUIRED",
                    "RFC terminal cascade deliberate-action proof did not validate",
                )

            audit_event_id = new_uuid4()
            executed_at_utc = utc_epoch_seconds()
            resulting_revision = state.proposal_revision + 1
            response = _state_response(
                proposal_id=canonical_proposal_id,
                trigger_rfc_id=state.trigger_rfc_id,
                state="executed",
                proposal_revision=resulting_revision,
                terminal_epoch_id=state.terminal_epoch_id,
                terminal_status_class=state.terminal_status_class,
                terminal_status_evidence_id=state.terminal_status_evidence_id,
                scope_kind=state.scope_kind,
                scope_fingerprint=state.scope_fingerprint,
                captured_rfc_count=state.captured_rfc_count,
                captured_wfm_count=state.captured_wfm_count,
            )

            def apply(inner: UnitOfWork) -> AuditEventInput:
                task_refs = self._apply_participant(
                    self._task_participant,
                    inner,
                    proposal,
                    allowed_types=_TASK_RESULT_TYPES,
                    participant_name="Task/Objective",
                )
                communication_refs = self._apply_participant(
                    self._communication_participant,
                    inner,
                    proposal,
                    allowed_types=_COMMUNICATION_RESULT_TYPES,
                    participant_name="Communication",
                )
                combined_refs = task_refs + communication_refs
                if len(set((ref.result_type, ref.result_id) for ref in combined_refs)) != len(combined_refs):
                    raise SomaError(
                        "RFC_TERMINAL_CASCADE_PARTICIPANT_FAILED",
                        "terminal cascade participants returned duplicate result references",
                    )

                updated = inner.connection.execute(
                    "UPDATE rfc_terminal_cascade_proposals "
                    "SET proposal_state='executed',revision=revision+1,executed_at_utc=?,executed_command_id=? "
                    "WHERE rfc_terminal_cascade_proposal_id=? AND proposal_state='pending' AND revision=?",
                    (executed_at_utc, command_id, canonical_proposal_id, state.proposal_revision),
                )
                if updated.rowcount != 1:
                    raise SomaError(
                        "RFC_TERMINAL_CASCADE_STALE",
                        "RFC terminal cascade proposal changed before execution publication",
                    )

                return AuditEventInput(
                    audit_event_id=audit_event_id,
                    action_type="ticket.rfc.terminal_cascade_executed",
                    action_version=1,
                    actor_kind=actor_kind,
                    actor_id=actor_id,
                    target_type=_TARGET_TYPE,
                    target_id=canonical_proposal_id,
                    reason_category=None,
                    command_id=command_id,
                    proposal_id=canonical_proposal_id,
                    payload_schema="RfcTerminalCascadeAuditV1",
                    payload_version=1,
                    payload={
                        "proposal_id": canonical_proposal_id,
                        "proposal_revision": resulting_revision,
                        "terminal_epoch_id": state.terminal_epoch_id,
                        "scope_fingerprint": state.scope_fingerprint,
                        "reviewed_preview_fingerprint": execution_review.preview_fingerprint,
                        "state_transition": "pending_to_executed",
                        "task_participant_result_refs": _refs_payload(task_refs),
                        "communication_participant_result_refs": _refs_payload(communication_refs),
                        "reason_category": None,
                    },
                    resulting_event_refs=(
                        AuditResultRef("rfc_terminal_cascade_proposal", canonical_proposal_id),
                        *combined_refs,
                    ),
                )

            return PreparedMutation(
                False,
                "rfc_terminal_cascade_proposal",
                canonical_proposal_id,
                apply,
                response_schema="RfcTerminalCascadeStateV1",
                response=response,
            )

        return _state_result_from_execution(self._boundary.execute(envelope, prepare))
