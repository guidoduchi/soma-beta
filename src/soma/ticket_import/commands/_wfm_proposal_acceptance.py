from __future__ import annotations

import hmac
from typing import Any

from soma.foundation.application.command_boundary import PreparedMutation
from soma.foundation.errors import SomaError
from soma.foundation.identifiers import new_uuid4, utc_epoch_seconds
from soma.foundation.persistence.uow import UnitOfWork
from soma.objectives_tasks.services.wfm_import import (
    WfmCreateOrAdoptFromSourceMutation,
    WfmImportMutationParticipant,
    WfmSourceProjectionAcceptanceMutation,
)
from soma.ticket_import.providers.wfm_review_evidence import TicketImportWfmReviewEvidenceProvider

from ..repositories.proposals import ProposalChangeRecord, ProposalRecord
from ..reconciliation.engine import ProposalChangeDraft


def _same_change(persisted: ProposalChangeRecord, recomputed: ProposalChangeDraft) -> bool:
    return (
        persisted.ordinal == recomputed.ordinal
        and persisted.field_key == recomputed.field_key
        and persisted.change_kind == recomputed.change_kind
        and persisted.value_kind == recomputed.value_kind
        and persisted.before_text == recomputed.before_text
        and persisted.after_text == recomputed.after_text
        and persisted.before_integer == recomputed.before_integer
        and persisted.after_integer == recomputed.after_integer
        and persisted.source_observation_field_id == recomputed.source_observation_field_id
    )


def _prepared_result(service: Any, proposal: ProposalRecord, command_id: str, apply) -> PreparedMutation:
    return PreparedMutation(
        False,
        "reconciliation_proposal",
        proposal.proposal_id,
        apply,
        response_schema="ProposalDecisionResultV1",
        response_factory=lambda inner: service._decision_response(
            inner,
            proposal_id=proposal.proposal_id,
            command_id=command_id,
        ),
    )


def prepare_wfm_create_accept(
    service: Any,
    uow: UnitOfWork,
    *,
    proposal: ProposalRecord,
    run: Any,
    base_token: str,
    proposal_revision: int,
    command_id: str,
    reason: str | None,
    actor_kind: str,
    actor_id: str | None,
) -> PreparedMutation:
    if (
        proposal.evidence_mode != "observed_row"
        or proposal.source_observation_id is None
        or proposal.target_kind != "wfm"
        or proposal.target_internal_id is not None
        or proposal.target_business_id is None
        or proposal.risk_class != "medium"
    ):
        raise SomaError("IMPORT_PROPOSAL_STALE", "WFM create/adopt proposal binding is invalid")
    changes = service._repository.list_changes(uow.connection, proposal.proposal_id)
    if len(changes) != 2:
        raise SomaError("IMPORT_PROPOSAL_STALE", "WFM create/adopt proposal requires exactly two identity changes")
    task_change, rfc_change = changes
    if (
        task_change.ordinal != 0
        or task_change.field_key != "task_no"
        or task_change.change_kind != "create"
        or task_change.value_kind != "identity"
        or task_change.before_text is not None
        or task_change.after_text != proposal.target_business_id
        or task_change.before_integer is not None
        or task_change.after_integer is not None
        or task_change.source_observation_field_id is not None
        or rfc_change.ordinal != 1
        or rfc_change.field_key != "rfc_no"
        or rfc_change.change_kind != "link"
        or rfc_change.value_kind != "identity"
        or rfc_change.before_text is not None
        or rfc_change.after_text is None
        or rfc_change.before_integer is not None
        or rfc_change.after_integer is not None
        or rfc_change.source_observation_field_id is not None
    ):
        raise SomaError("IMPORT_PROPOSAL_STALE", "WFM create/adopt proposal encoding is invalid")

    candidate = TicketImportWfmReviewEvidenceProvider().revalidate_create_candidate(
        uow.connection,
        expected_import_run_id=proposal.import_run_id,
        expected_source_observation_id=proposal.source_observation_id,
        expected_task_no=proposal.target_business_id,
        expected_parent_rfc_no=rfc_change.after_text,
    )
    if not hmac.compare_digest(candidate.base_state_token, base_token):
        raise SomaError("IMPORT_PROPOSAL_STALE", "WFM create/adopt base state changed")

    disposition_id = new_uuid4()
    orchestration_audit_id = new_uuid4()
    decided_at = utc_epoch_seconds()
    mutation = WfmCreateOrAdoptFromSourceMutation(
        task_no=candidate.task_no,
        expected_task_id=None,
        rfc_id=candidate.rfc_id,
        source_lifecycle_class=candidate.source_lifecycle_class,
        base_state_token=base_token,
        accepted_command_id=command_id,
        actor_kind=actor_kind,
        actor_id=actor_id,
    )

    def apply(inner: UnitOfWork):
        owner_result = WfmImportMutationParticipant.create_or_adopt_wfm_from_source(inner, mutation)
        service._repository.transition_accept(
            inner,
            proposal=proposal,
            run=run,
            decided_at_utc=decided_at,
            disposition_id=disposition_id,
            reason_category=reason,
            command_id=command_id,
        )
        orchestration = service._orchestration_audit(
            audit_event_id=orchestration_audit_id,
            command_id=command_id,
            proposal=proposal,
            proposal_revision=proposal_revision,
            reason=reason,
            actor_kind=actor_kind,
            actor_id=actor_id,
            disposition_id=disposition_id,
            owner_result_refs=owner_result.result_refs,
        )
        return (*owner_result.audit_events, orchestration)

    return _prepared_result(service, proposal, command_id, apply)


def prepare_wfm_source_projection_accept(
    service: Any,
    uow: UnitOfWork,
    *,
    proposal: ProposalRecord,
    run: Any,
    base_token: str,
    proposal_revision: int,
    command_id: str,
    reason: str | None,
    actor_kind: str,
    actor_id: str | None,
) -> PreparedMutation:
    if (
        proposal.evidence_mode != "observed_row"
        or proposal.source_observation_id is None
        or proposal.target_kind != "wfm"
        or proposal.target_internal_id is None
        or proposal.target_business_id is None
        or proposal.risk_class != "medium"
    ):
        raise SomaError("IMPORT_PROPOSAL_STALE", "WFM source-projection proposal binding is invalid")
    parent_row = uow.connection.execute(
        "SELECT canonical_parent_rfc_no FROM source_observations WHERE source_observation_id=? AND import_run_id=?",
        (proposal.source_observation_id, proposal.import_run_id),
    ).fetchone()
    if parent_row is None or parent_row[0] is None:
        raise SomaError("IMPORT_PROPOSAL_STALE", "WFM source-projection parent RFC evidence disappeared")
    parent_rfc_no = str(parent_row[0])

    candidate = TicketImportWfmReviewEvidenceProvider().revalidate_source_projection_candidate(
        uow.connection,
        expected_import_run_id=proposal.import_run_id,
        expected_source_observation_id=proposal.source_observation_id,
        expected_task_id=proposal.target_internal_id,
        expected_task_no=proposal.target_business_id,
        expected_parent_rfc_no=parent_rfc_no,
    )
    if not hmac.compare_digest(candidate.base_state_token, base_token):
        raise SomaError("IMPORT_PROPOSAL_STALE", "WFM source-projection base state changed")
    changes = service._repository.list_changes(uow.connection, proposal.proposal_id)
    if len(changes) != len(candidate.changes) or not changes:
        raise SomaError("IMPORT_PROPOSAL_STALE", "WFM source-projection change set changed")
    if any(not _same_change(persisted, recomputed) for persisted, recomputed in zip(changes, candidate.changes, strict=True)):
        raise SomaError("IMPORT_PROPOSAL_STALE", "WFM source-projection evidence no longer matches the reviewed change set")

    disposition_id = new_uuid4()
    orchestration_audit_id = new_uuid4()
    decided_at = utc_epoch_seconds()
    mutation = WfmSourceProjectionAcceptanceMutation(
        task_id=candidate.task_id,
        task_no=candidate.task_no,
        expected_source_projection_revision=candidate.expected_source_projection_revision,
        provider_status_token=candidate.provider_status_token,
        provider_lifecycle_class=candidate.provider_lifecycle_class,
        source_plan_start_utc=candidate.source_plan_start_utc,
        source_plan_end_utc=candidate.source_plan_end_utc,
        accepted_source_observation_id=candidate.source_observation_id,
        base_state_token=base_token,
        accepted_command_id=command_id,
    )

    def apply(inner: UnitOfWork):
        owner_result = WfmImportMutationParticipant.apply_wfm_source_projection(inner, mutation)
        service._repository.transition_accept(
            inner,
            proposal=proposal,
            run=run,
            decided_at_utc=decided_at,
            disposition_id=disposition_id,
            reason_category=reason,
            command_id=command_id,
        )
        orchestration = service._orchestration_audit(
            audit_event_id=orchestration_audit_id,
            command_id=command_id,
            proposal=proposal,
            proposal_revision=proposal_revision,
            reason=reason,
            actor_kind=actor_kind,
            actor_id=actor_id,
            disposition_id=disposition_id,
            owner_result_refs=owner_result.result_refs,
        )
        return (*owner_result.audit_events, orchestration)

    return _prepared_result(service, proposal, command_id, apply)
