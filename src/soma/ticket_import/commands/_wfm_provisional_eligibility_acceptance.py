from __future__ import annotations

import hmac
from typing import Any

from soma.foundation.application.command_boundary import PreparedMutation
from soma.foundation.errors import SomaError
from soma.foundation.identifiers import new_uuid4, utc_epoch_seconds
from soma.foundation.persistence.uow import UnitOfWork
from soma.ticket_import.providers.wfm_provisional_eligibility_evidence import (
    TicketImportWfmProvisionalEligibilityEvidenceProvider,
)
from soma.tickets.rfc_wfm_provisional import (
    RfcWfmProvisionalEligibilityMutation,
    RfcWfmProvisionalEligibilityService,
)

from ..repositories.proposals import ProposalRecord


def prepare_wfm_provisional_eligibility_accept(
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
        or proposal.target_business_id is None
        or proposal.risk_class != "high"
    ):
        raise SomaError("IMPORT_PROPOSAL_STALE", "WFM provisional RFC eligibility proposal binding is invalid")

    candidate = TicketImportWfmProvisionalEligibilityEvidenceProvider().revalidate(
        uow.connection,
        expected_import_run_id=proposal.import_run_id,
        expected_source_observation_id=proposal.source_observation_id,
        expected_rfc_no=proposal.target_business_id,
        expected_target_internal_id=proposal.target_internal_id,
    )
    if not hmac.compare_digest(candidate.base_state_token, base_token):
        raise SomaError("IMPORT_PROPOSAL_STALE", "WFM provisional RFC eligibility base state changed")

    changes = service._repository.list_changes(uow.connection, proposal.proposal_id)
    if len(changes) != 1:
        raise SomaError("IMPORT_PROPOSAL_STALE", "WFM provisional RFC eligibility requires exactly one status change")
    change = changes[0]
    if (
        change.ordinal != 0
        or change.field_key != "status"
        or change.change_kind != "set"
        or change.value_kind != "controlled"
        or change.before_text != candidate.before_status_text
        or change.after_text != "Implement"
        or change.before_integer is not None
        or change.after_integer is not None
        or change.source_observation_field_id != candidate.source_observation_field_id
    ):
        raise SomaError("IMPORT_PROPOSAL_STALE", "WFM provisional RFC eligibility proposal encoding changed")

    delta = service._rfc_source_provider.build_source_projection_delta(
        uow.connection,
        rfc_id=candidate.rfc_id,
        expected_import_run_id=proposal.import_run_id,
        expected_source_observation_id=proposal.source_observation_id,
        source_observation_field_id=candidate.source_observation_field_id,
        expected_field_key="status",
    )
    if (
        delta.value != "Implement"
        or delta.status_class != "implement_eligible"
        or delta.status_authority != "wfm_provisional"
    ):
        raise SomaError("IMPORT_PROPOSAL_STALE", "WFM RFC Status evidence no longer proves provisional eligibility")

    disposition_id = new_uuid4()
    orchestration_audit_id = new_uuid4()
    decided_at = utc_epoch_seconds()
    owner = RfcWfmProvisionalEligibilityService(service._rfc_source_provider)
    mutation = RfcWfmProvisionalEligibilityMutation(
        rfc_no=candidate.rfc_no,
        source_status_delta=delta,
        base_state_token=base_token,
        accepted_command_id=command_id,
        review_fingerprint=proposal.proposal_fingerprint,
        actor_kind=actor_kind,
        actor_id=actor_id,
    )

    def apply(inner: UnitOfWork):
        owner_result = owner.accept_provisional_implement_eligibility_from_wfm(inner, mutation)
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
