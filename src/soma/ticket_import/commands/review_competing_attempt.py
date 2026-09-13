from __future__ import annotations

import hmac
import re
from typing import Any

from soma.foundation.application.command_boundary import CommandBoundary, CommandEnvelope, PreparedMutation
from soma.foundation.audit.writer import AuditWriter
from soma.foundation.errors import IntegrityFailure, SomaError, ValidationError
from soma.foundation.identifiers import new_uuid4, require_uuid4, utc_epoch_seconds
from soma.foundation.persistence.connections import ConnectionFactory
from soma.foundation.persistence.uow import UnitOfWork
from soma.objectives_tasks.services.task_activity_review import (
    WfmActivityReviewCommandContext,
    WfmActivityReviewParticipant,
)
from soma.objectives_tasks.services.wfm_import import WfmImportReader
from soma.tickets.rfc_import_reader import RfcImportReader

from ..audit_registry import build_ticket_import_audit_registry
from ..providers.wfm_competing_attempt_evidence import TicketImportWfmCompetingAttemptEvidenceProvider
from ..repositories.proposals import ProposalRecord, ProposalRepository
from .decide_proposal import ProposalDecisionResult, ProposalDecisionService


_HEX64_RE = re.compile(r"[0-9a-f]{64}\Z")
_DECISIONS = frozenset({"distinct_activity", "same_activity", "retry_lineage", "unresolved_source_error"})
_METADATA_RESULT_TYPES = frozenset({"proposal_disposition", "proposal_equivalence_decision"})
_STALE_PARTICIPANT_CODES = frozenset({"TASK_NOT_FOUND", "TASK_STALE", "TASK_ACTIVITY_REVIEW_STALE"})


def _fingerprint(value: object, *, label: str) -> str:
    if not isinstance(value, str) or _HEX64_RE.fullmatch(value) is None:
        raise ValidationError(f"{label} must be lowercase SHA-256 hex")
    return value


def _reason(value: object) -> str:
    if not isinstance(value, str):
        raise ValidationError("reason_category must be text")
    try:
        encoded = value.encode("utf-8", errors="strict")
    except UnicodeEncodeError as exc:
        raise ValidationError("reason_category must be valid Unicode") from exc
    if not encoded or len(encoded) > 128 or "\x00" in value or "\r" in value or "\n" in value:
        raise ValidationError("reason_category violates its 1..128 UTF-8 byte one-line contract")
    return value


class WfmCompetingAttemptReviewService:
    """Dedicated LLD-04 orchestration for reviewed WFM competing-attempt proposals."""

    def __init__(
        self,
        connection_factory: ConnectionFactory,
        *,
        rfc_reader: RfcImportReader | None = None,
        wfm_reader: WfmImportReader | None = None,
        activity_participant: type[WfmActivityReviewParticipant] = WfmActivityReviewParticipant,
        evidence_provider: TicketImportWfmCompetingAttemptEvidenceProvider | None = None,
    ) -> None:
        self._repository = ProposalRepository()
        self._rfc_reader = RfcImportReader() if rfc_reader is None else rfc_reader
        self._wfm_reader = WfmImportReader() if wfm_reader is None else wfm_reader
        self._activity_participant = activity_participant
        self._evidence = (
            TicketImportWfmCompetingAttemptEvidenceProvider()
            if evidence_provider is None
            else evidence_provider
        )
        self._boundary = CommandBoundary(
            connection_factory,
            AuditWriter(build_ticket_import_audit_registry()),
        )

    def _decision_response(
        self,
        uow: UnitOfWork,
        *,
        proposal_id: str,
        command_id: str,
    ) -> dict[str, object]:
        proposal = self._repository.get(uow.connection, proposal_id)
        if proposal is None:
            raise IntegrityFailure("competing-attempt proposal disappeared before response materialization")
        refs = uow.connection.execute(
            "SELECT r.result_type,r.result_id FROM audit_event_results r "
            "JOIN audit_events e ON e.audit_event_id=r.audit_event_id "
            "WHERE e.command_id=? AND e.action_type='ticket_import.proposal_decided' "
            "ORDER BY r.result_type ASC,r.result_id ASC",
            (command_id,),
        ).fetchall()
        owner_refs = [
            {"type": str(row[0]), "id": str(row[1])}
            for row in refs
            if str(row[0]) not in _METADATA_RESULT_TYPES
        ]
        return {
            "proposal_id": proposal_id,
            "decision": proposal.proposal_state,
            "revision": proposal.revision,
            "owner_result_refs": owner_refs,
        }

    @staticmethod
    def _require_proposal_shape(proposal: ProposalRecord) -> None:
        if (
            proposal.proposal_kind != "wfm_competing_attempt_review"
            or proposal.risk_class != "high"
            or proposal.evidence_mode != "observed_row"
            or proposal.source_observation_id is None
            or proposal.target_kind != "activity_lineage"
            or proposal.target_internal_id is None
            or proposal.target_business_id is None
        ):
            raise SomaError("IMPORT_PROPOSAL_STALE", "competing-attempt proposal binding is incomplete")

    def resolve(
        self,
        *,
        command_id: str,
        proposal_id: str,
        proposal_revision: int,
        proposal_fingerprint: str,
        base_state_token: str,
        decision: str,
        activity_review_fingerprint: str,
        reason_category: str,
        actor_kind: str = "local_user",
        actor_id: str | None = None,
    ) -> ProposalDecisionResult:
        canonical_proposal_id = require_uuid4(proposal_id)
        if type(proposal_revision) is not int or proposal_revision <= 0:
            raise ValidationError("proposal_revision must be a positive integer")
        proposal_fp = _fingerprint(proposal_fingerprint, label="proposal_fingerprint")
        base_token = _fingerprint(base_state_token, label="base_state_token")
        review_fp = _fingerprint(activity_review_fingerprint, label="activity_review_fingerprint")
        if decision not in _DECISIONS:
            raise ValidationError("decision is outside the WFM activity-review vocabulary")
        reason = _reason(reason_category)

        envelope = CommandEnvelope(
            command_id=command_id,
            command_type="ResolveWfmCompetingAttemptReview",
            target_type="reconciliation_proposal",
            target_id=canonical_proposal_id,
            semantic_payload={
                "proposal_revision": proposal_revision,
                "proposal_fingerprint": proposal_fp,
                "base_state_token": base_token,
                "decision": decision,
                "activity_review_fingerprint": review_fp,
                "reason_category": reason,
            },
            base_revisions={"proposal": proposal_revision},
            authorizing_fingerprints={
                "proposal": proposal_fp,
                "base_state": base_token,
                "activity_review": review_fp,
            },
        )

        def prepare(uow: UnitOfWork) -> PreparedMutation:
            proposal = self._repository.require_pending(uow.connection, canonical_proposal_id)
            if (
                proposal.revision != proposal_revision
                or not hmac.compare_digest(proposal.proposal_fingerprint, proposal_fp)
                or not hmac.compare_digest(proposal.base_state_token, base_token)
            ):
                raise SomaError("IMPORT_PROPOSAL_STALE", "proposal revision/fingerprint/base state changed")
            self._require_proposal_shape(proposal)

            run = self._repository.get_run(uow.connection, proposal.import_run_id)
            if run.run_state not in {"staged", "waiting_review", "recovery_required"}:
                raise SomaError("IMPORT_PROPOSAL_STALE", "parent import run no longer permits review resolution")
            self._repository.require_current_recovery_authorization(uow.connection, run)

            changes = self._repository.list_changes(uow.connection, proposal.proposal_id)
            if len(changes) != 1:
                raise SomaError("IMPORT_PROPOSAL_STALE", "competing-attempt proposal must contain one conflict identity")
            change = changes[0]
            if (
                change.ordinal != 0
                or change.field_key != "competing_attempt_counterpart"
                or change.change_kind != "conflict"
                or change.value_kind != "identity"
                or change.before_text is not None
                or change.after_text is None
                or change.before_integer is not None
                or change.after_integer is not None
                or change.source_observation_field_id is not None
            ):
                raise SomaError("IMPORT_PROPOSAL_STALE", "competing-attempt proposal change binding is invalid")
            counterpart_task_id = require_uuid4(change.after_text)
            expected_lineage_id = require_uuid4(proposal.target_internal_id)

            evidence = self._evidence.load_exact(
                uow.connection,
                expected_import_run_id=proposal.import_run_id,
                source_observation_id=proposal.source_observation_id,
            )
            if evidence.task_no != proposal.target_business_id:
                raise SomaError("IMPORT_PROPOSAL_STALE", "proposal target Task No no longer matches source evidence")

            rfc = self._rfc_reader.get_by_number(uow.connection, evidence.parent_rfc_no)
            if rfc is None:
                raise SomaError("IMPORT_PROPOSAL_STALE", "owning RFC identity no longer exists")
            rfc_id = rfc.get("rfc_id")
            if not isinstance(rfc_id, str):
                raise IntegrityFailure("RFC import reader returned invalid identity")

            if self._wfm_reader.task_no_status(uow.connection, evidence.task_no) != "ACTIVE":
                raise SomaError("IMPORT_PROPOSAL_STALE", "WFM Task No is no longer ACTIVE")
            identity = self._wfm_reader.get_by_task_no(uow.connection, evidence.task_no)
            if identity is None:
                raise SomaError("IMPORT_PROPOSAL_STALE", "WFM Task identity disappeared")
            task_id = identity.get("task_id")
            current_rfc_id = identity.get("current_rfc_id")
            task_revision = identity.get("task_revision")
            if (
                not isinstance(task_id, str)
                or current_rfc_id != rfc_id
                or type(task_revision) is not int
                or task_revision <= 0
            ):
                raise SomaError("IMPORT_PROPOSAL_STALE", "WFM identity/RFC authority changed")

            source_projection = self._wfm_reader.source_projection(uow.connection, task_id)
            if (
                source_projection is None
                or source_projection.get("accepted_source_observation_id") != evidence.source_observation_id
                or source_projection.get("source_plan_start_utc") != evidence.planned_start_utc
                or source_projection.get("source_plan_end_utc") != evidence.planned_end_utc
            ):
                raise SomaError(
                    "IMPORT_PROPOSAL_STALE",
                    "exact WFM source observation is not the current accepted source-plan authority",
                )

            try:
                conflict = self._wfm_reader.activity_conflicts(
                    uow.connection,
                    {
                        "task_no": evidence.task_no,
                        "current_rfc_id": rfc_id,
                        "task_id": task_id,
                    },
                    {"start_utc": evidence.planned_start_utc, "end_utc": evidence.planned_end_utc},
                    counterpart_task_id,
                )
            except SomaError as exc:
                if exc.code in {"TASK_STALE", "WFM_TASK_NO_RETIRED"}:
                    raise SomaError("IMPORT_PROPOSAL_STALE", "WFM conflict authority changed") from exc
                raise

            selected = conflict.get("selected_counterpart")
            if (
                conflict.get("classification") != "SAME_REVIEWED_LINEAGE_OVERLAP"
                or conflict.get("activity_lineage_id") != expected_lineage_id
                or conflict.get("subject_task_id") != task_id
                or not isinstance(selected, dict)
                or selected.get("task_id") != counterpart_task_id
                or type(selected.get("task_revision")) is not int
                or int(selected["task_revision"]) <= 0
                or conflict.get("conflict_fingerprint") != base_token
            ):
                raise SomaError("IMPORT_PROPOSAL_STALE", "WFM competing-attempt conflict authority changed")

            seed_tasks = tuple(
                sorted(
                    (
                        (task_id, task_revision),
                        (counterpart_task_id, int(selected["task_revision"])),
                    ),
                    key=lambda item: item[0],
                )
            )
            disposition_id = new_uuid4()
            orchestration_audit_id = new_uuid4()
            decided_at = utc_epoch_seconds()

            def apply(inner: UnitOfWork):
                try:
                    owner = self._activity_participant.apply_reviewed_activity_relationship(
                        inner,
                        seed_tasks=seed_tasks,
                        decision=decision,
                        review_fingerprint=review_fp,
                        reason_category=reason,
                        command_context=WfmActivityReviewCommandContext(
                            command_id=command_id,
                            actor_kind=actor_kind,
                            actor_id=actor_id,
                        ),
                    )
                except SomaError as exc:
                    if exc.code in _STALE_PARTICIPANT_CODES:
                        raise SomaError(
                            "IMPORT_PROPOSAL_STALE",
                            "WFM activity-review authority changed after conflict revalidation",
                        ) from exc
                    if exc.code == "TASK_ACTIVITY_LINEAGE_CONFLICT":
                        raise SomaError(
                            "IMPORT_PROPOSAL_BLOCKED",
                            "WFM activity-review decision conflicts with current lineage authority",
                        ) from exc
                    raise

                self._repository.transition_accept(
                    inner,
                    proposal=proposal,
                    run=run,
                    decided_at_utc=decided_at,
                    disposition_id=disposition_id,
                    reason_category=reason,
                    command_id=command_id,
                )
                return ProposalDecisionService._orchestration_audit(
                    audit_event_id=orchestration_audit_id,
                    command_id=command_id,
                    proposal=proposal,
                    proposal_revision=proposal_revision,
                    reason=reason,
                    actor_kind=actor_kind,
                    actor_id=actor_id,
                    disposition_id=disposition_id,
                    owner_result_refs=owner.result_refs,
                )

            return PreparedMutation(
                False,
                "reconciliation_proposal",
                proposal.proposal_id,
                apply,
                response_schema="ProposalDecisionResultV1",
                response_factory=lambda inner: self._decision_response(
                    inner,
                    proposal_id=proposal.proposal_id,
                    command_id=command_id,
                ),
            )

        execution = self._boundary.execute(envelope, prepare)
        return ProposalDecisionService._result_from_execution(execution)
