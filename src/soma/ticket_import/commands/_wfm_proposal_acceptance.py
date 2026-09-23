from __future__ import annotations

import hmac
from typing import Any

from soma.foundation.application.command_boundary import PreparedMutation
from soma.foundation.errors import SomaError
from soma.foundation.identifiers import new_uuid4, utc_epoch_seconds
from soma.foundation.persistence.uow import UnitOfWork
from soma.objectives_tasks.services.wfm_import import (
    WfmCreateOrAdoptFromSourceMutation,
    WfmImportBaseTarget,
    WfmImportMutationParticipant,
    WfmImportReader,
    WfmReviewedOperationalPlanMutation,
    WfmSourceProjectionAcceptanceMutation,
)
from soma.ticket_import.providers.wfm_competing_attempt_evidence import TicketImportWfmCompetingAttemptEvidenceProvider
from soma.ticket_import.providers.wfm_review_evidence import (
    TicketImportWfmReviewEvidenceProvider,
    _load_published_source,
)
from soma.tickets.rfc_import_mutations import RfcCreateFromSourceMutation
from soma.tickets.rfc_import_reader import RfcImportReader

from ..repositories.proposals import ProposalChangeRecord, ProposalRecord
from ..reconciliation.engine import ProposalChangeDraft
from ._proposal_writes import pending_write_from_draft
from ..reconciliation.wfm_follow_on import build_wfm_follow_on_proposals
from ..reconciliation.wfm_sr_link import build_wfm_task_name_sr_link_proposals


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


def prepare_wfm_provisional_rfc_accept(
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
        or proposal.target_kind != "rfc"
        or proposal.target_internal_id is not None
        or proposal.target_business_id is None
        or proposal.risk_class != "high"
    ):
        raise SomaError("IMPORT_PROPOSAL_STALE", "WFM provisional RFC proposal binding is invalid")
    changes = service._repository.list_changes(uow.connection, proposal.proposal_id)
    if len(changes) != 1:
        raise SomaError("IMPORT_PROPOSAL_STALE", "WFM provisional RFC proposal requires exactly one identity change")
    change = changes[0]
    if (
        change.ordinal != 0
        or change.field_key != "rfc_no"
        or change.change_kind != "create"
        or change.value_kind != "identity"
        or change.before_text is not None
        or change.after_text != proposal.target_business_id
        or change.before_integer is not None
        or change.after_integer is not None
        or change.source_observation_field_id is not None
    ):
        raise SomaError("IMPORT_PROPOSAL_STALE", "WFM provisional RFC proposal encoding is invalid")

    candidate = TicketImportWfmReviewEvidenceProvider().revalidate_provisional_rfc_candidate(
        uow.connection,
        expected_import_run_id=proposal.import_run_id,
        expected_source_observation_id=proposal.source_observation_id,
        expected_parent_rfc_no=proposal.target_business_id,
    )
    if not hmac.compare_digest(candidate.base_state_token, base_token):
        raise SomaError("IMPORT_PROPOSAL_STALE", "WFM provisional RFC identity base state changed")

    disposition_id = new_uuid4()
    orchestration_audit_id = new_uuid4()
    decided_at = utc_epoch_seconds()
    mutation = RfcCreateFromSourceMutation(
        rfc_no=candidate.rfc_no,
        base_state_token=base_token,
        accepted_command_id=command_id,
        actor_kind=actor_kind,
        actor_id=actor_id,
    )

    def apply(inner: UnitOfWork):
        owner_result = service._rfc_import_mutations.create_or_adopt_from_source(inner, mutation)
        source = _load_published_source(
            inner.connection,
            expected_import_run_id=proposal.import_run_id,
            expected_source_observation_id=proposal.source_observation_id,
        )
        sr_link_drafts = build_wfm_task_name_sr_link_proposals(inner.connection, source=source)
        sr_link_writes = tuple(pending_write_from_draft(draft) for draft in sr_link_drafts)
        service._repository.transition_accept(
            inner,
            proposal=proposal,
            run=run,
            decided_at_utc=decided_at,
            disposition_id=disposition_id,
            reason_category=reason,
            command_id=command_id,
        )
        service._repository.insert_follow_on_pending_set(
            inner,
            import_run_id=proposal.import_run_id,
            expected_run_revision=run.revision + 1,
            writes=sr_link_writes,
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
        follow_on_drafts = build_wfm_follow_on_proposals(
            inner.connection,
            import_run_id=proposal.import_run_id,
            source_observation_id=candidate.source_observation_id,
        )
        follow_on_writes = tuple(pending_write_from_draft(draft) for draft in follow_on_drafts)
        service._repository.transition_accept(
            inner,
            proposal=proposal,
            run=run,
            decided_at_utc=decided_at,
            disposition_id=disposition_id,
            reason_category=reason,
            command_id=command_id,
        )
        service._repository.insert_follow_on_pending_set(
            inner,
            import_run_id=proposal.import_run_id,
            expected_run_revision=run.revision + 1,
            writes=follow_on_writes,
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


def prepare_wfm_plan_reconciliation_accept(
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
        or proposal.target_kind != "task_plan"
        or proposal.target_internal_id is None
        or proposal.target_business_id is None
        or proposal.risk_class != "high"
    ):
        raise SomaError("IMPORT_PROPOSAL_STALE", "WFM plan-reconciliation proposal binding is invalid")

    evidence = TicketImportWfmCompetingAttemptEvidenceProvider().load_exact(
        uow.connection,
        expected_import_run_id=proposal.import_run_id,
        source_observation_id=proposal.source_observation_id,
    )
    if evidence.task_no != proposal.target_business_id:
        raise SomaError("IMPORT_PROPOSAL_STALE", "WFM plan target Task No changed")
    if WfmImportReader.task_no_status(uow.connection, evidence.task_no) != "ACTIVE":
        raise SomaError("IMPORT_PROPOSAL_STALE", "WFM plan target is no longer ACTIVE")
    identity = WfmImportReader.get_by_task_no(uow.connection, evidence.task_no)
    if identity is None or identity.get("task_id") != proposal.target_internal_id:
        raise SomaError("IMPORT_PROPOSAL_STALE", "WFM plan target identity changed")
    task_revision = identity.get("task_revision")
    current_rfc_id = identity.get("current_rfc_id")
    if type(task_revision) is not int or task_revision <= 0 or not isinstance(current_rfc_id, str):
        raise SomaError("IMPORT_PROPOSAL_STALE", "WFM plan target owner authority is invalid")
    parent = RfcImportReader().get_by_number(uow.connection, evidence.parent_rfc_no)
    if parent is None or parent.get("rfc_id") != current_rfc_id:
        raise SomaError("IMPORT_PROPOSAL_STALE", "WFM plan parent RFC authority changed")

    source = WfmImportReader.source_projection(uow.connection, proposal.target_internal_id)
    if (
        source is None
        or source.get("accepted_source_observation_id") != evidence.source_observation_id
        or source.get("source_plan_start_utc") != evidence.planned_start_utc
        or source.get("source_plan_end_utc") != evidence.planned_end_utc
    ):
        raise SomaError("IMPORT_PROPOSAL_STALE", "WFM plan proposal is not bound to the current accepted source plan")
    source_revision = source.get("source_projection_revision")
    if type(source_revision) is not int or source_revision <= 0:
        raise SomaError("IMPORT_PROPOSAL_STALE", "WFM source-plan revision authority is invalid")

    operational = WfmImportReader.operational_plan_context(uow.connection, proposal.target_internal_id)
    if operational is None:
        expected_plan_revision = 0
        before_start = None
        before_end = None
    else:
        expected_plan_revision = operational.get("revision")
        before_start = operational.get("start_utc")
        before_end = operational.get("end_utc")
        if (
            type(expected_plan_revision) is not int
            or expected_plan_revision <= 0
            or type(before_start) is not int
            or type(before_end) is not int
            or before_start < 0
            or before_end <= before_start
        ):
            raise SomaError("IMPORT_PROPOSAL_STALE", "WFM operational-plan authority is invalid")
    if before_start == evidence.planned_start_utc and before_end == evidence.planned_end_utc:
        raise SomaError("IMPORT_PROPOSAL_STALE", "WFM plan proposal no longer represents a material change")

    current_token = WfmImportReader.source_acceptance_base_token(
        uow.connection,
        WfmImportBaseTarget("wfm_plan_reconciliation", evidence.task_no, proposal.target_internal_id),
    )
    if not hmac.compare_digest(current_token, base_token):
        raise SomaError("IMPORT_PROPOSAL_STALE", "WFM plan-reconciliation base state changed")

    changes = service._repository.list_changes(uow.connection, proposal.proposal_id)
    if len(changes) != 2:
        raise SomaError("IMPORT_PROPOSAL_STALE", "WFM plan reconciliation requires exactly two plan changes")
    start_change, end_change = changes
    expected = (
        (start_change, 0, "planned_start", before_start, evidence.planned_start_utc, evidence.planned_start_field_id),
        (end_change, 1, "planned_end", before_end, evidence.planned_end_utc, evidence.planned_end_field_id),
    )
    for change, ordinal, field_key, before_value, after_value, field_id in expected:
        if (
            change.ordinal != ordinal
            or change.field_key != field_key
            or change.change_kind != "set"
            or change.value_kind != "instant"
            or change.before_text is not None
            or change.after_text is not None
            or change.before_integer != before_value
            or change.after_integer != after_value
            or change.source_observation_field_id != field_id
        ):
            raise SomaError("IMPORT_PROPOSAL_STALE", "WFM plan proposal changes no longer match owner/source authority")

    disposition_id = new_uuid4()
    orchestration_audit_id = new_uuid4()
    decided_at = utc_epoch_seconds()
    mutation = WfmReviewedOperationalPlanMutation(
        task_id=proposal.target_internal_id,
        task_no=evidence.task_no,
        expected_task_revision=task_revision,
        expected_current_plan_revision=expected_plan_revision,
        expected_source_projection_revision=source_revision,
        accepted_source_observation_id=evidence.source_observation_id,
        start_utc=evidence.planned_start_utc,
        end_utc=evidence.planned_end_utc,
        base_state_token=base_token,
        accepted_command_id=command_id,
        reason_category=reason,
        actor_kind=actor_kind,
        actor_id=actor_id,
    )

    def apply(inner: UnitOfWork):
        owner_result = WfmImportMutationParticipant.apply_reviewed_operational_plan_from_source(inner, mutation)
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
