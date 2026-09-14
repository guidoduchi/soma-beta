from __future__ import annotations

import hmac
from typing import Any

from soma.foundation.application.command_boundary import PreparedMutation
from soma.foundation.errors import IntegrityFailure, SomaError
from soma.foundation.identifiers import new_uuid4, utc_epoch_seconds
from soma.foundation.persistence.uow import UnitOfWork
from soma.tickets.import_mutations import ServiceRequestContactReviewMutation

from ._proposal_decision_public_core import *  # noqa: F401,F403
from ._proposal_decision_public_core import ProposalDecisionService as _CoreProposalDecisionService
from ..repositories.proposals import ProposalRecord
from soma.tickets.service_request_import_reader import ServiceRequestImportReader as _CurrentHandlerImportReader


class ProposalDecisionService(_CoreProposalDecisionService):
    """Public proposal-decision service with certified Current Handler evidence-rebind support."""

    def _prepare_sr_contact_accept(
        self,
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
        if proposal.proposal_kind != "sr_current_handler_reconciliation":
            return super()._prepare_sr_contact_accept(
                uow,
                proposal=proposal,
                run=run,
                base_token=base_token,
                proposal_revision=proposal_revision,
                command_id=command_id,
                reason=reason,
                actor_kind=actor_kind,
                actor_id=actor_id,
            )

        reference_role = "current_handler_reference"
        if (
            proposal.evidence_mode != "observed_row"
            or proposal.source_observation_id is None
            or proposal.target_kind != "service_request"
            or proposal.target_internal_id is None
            or proposal.target_business_id is None
            or proposal.risk_class != "high"
        ):
            raise SomaError("IMPORT_PROPOSAL_STALE", "SR Contact reconciliation proposal binding is incomplete")
        target_identity = uow.connection.execute(
            "SELECT official_sr_no FROM service_requests WHERE service_request_id=?",
            (proposal.target_internal_id,),
        ).fetchone()
        if (
            target_identity is None
            or target_identity[0] is None
            or str(target_identity[0]) != proposal.target_business_id
        ):
            raise SomaError("IMPORT_PROPOSAL_STALE", "proposal target identity no longer matches the Service Request")
        changes = self._repository.list_changes(uow.connection, proposal.proposal_id)
        if len(changes) != 1:
            raise SomaError("IMPORT_PROPOSAL_STALE", "SR Contact reconciliation requires exactly one identity change")
        change = changes[0]
        if change.after_text is None or change.source_observation_field_id is None:
            raise SomaError("IMPORT_PROPOSAL_STALE", "SR Contact reconciliation target/source identity is missing")

        reference_context = self._sr_import_reader.current_reference_context(
            uow.connection,
            proposal.target_internal_id,
        )
        current_customer_org_id = reference_context.get("customer_org_id")
        if current_customer_org_id is not None and not isinstance(current_customer_org_id, str):
            raise IntegrityFailure("Service Request import reference context Customer identity is invalid")
        candidate = self._sr_contact_provider.revalidate_reviewed_candidate(
            uow.connection,
            expected_import_run_id=proposal.import_run_id,
            source_observation_id=proposal.source_observation_id,
            service_request_id=proposal.target_internal_id,
            canonical_sr_no=proposal.target_business_id,
            reference_role=reference_role,
            current_customer_org_id=current_customer_org_id,
            field_key=change.field_key,
            change_kind=change.change_kind,
            value_kind=change.value_kind,
            before_text=change.before_text,
            after_text=change.after_text,
            before_integer=change.before_integer,
            after_integer=change.after_integer,
            source_observation_field_id=change.source_observation_field_id,
        )
        contacts = reference_context.get("contacts")
        if not isinstance(contacts, dict):
            raise IntegrityFailure("Service Request import reference context Contact map is invalid")
        current_ref = contacts.get(reference_role)
        if current_ref is None:
            current_contact_id = None
            current_supporting_observation_id = None
        elif isinstance(current_ref, dict) and isinstance(current_ref.get("contact_id"), str):
            current_contact_id = str(current_ref["contact_id"])
            raw_support = current_ref.get("supporting_source_observation_id")
            if raw_support is not None and not isinstance(raw_support, str):
                raise IntegrityFailure("Service Request Current Handler support identity is invalid")
            current_supporting_observation_id = None if raw_support is None else str(raw_support)
        else:
            raise IntegrityFailure("Service Request import reference context Contact identity is invalid")
        if current_contact_id != candidate.prior_contact_id:
            raise SomaError("IMPORT_PROPOSAL_STALE", "Service Request Contact no longer matches proposal before-state")

        projection = _CurrentHandlerImportReader.current_source_projection(
            uow.connection,
            proposal.target_internal_id,
        )
        if projection is None:
            raise SomaError("IMPORT_PROPOSAL_STALE", "Current Handler source projection disappeared")
        handler_authority = projection.get("current_handler_authority")
        if not isinstance(handler_authority, dict) or handler_authority.get("value_state") != "usable":
            raise SomaError("IMPORT_PROPOSAL_STALE", "Current Handler accepted source authority is no longer usable")
        accepted_handler_observation_id = handler_authority.get("sr_source_field_observation_id")
        accepted_source_field_id = handler_authority.get("source_observation_field_id")
        if not isinstance(accepted_handler_observation_id, str) or not isinstance(accepted_source_field_id, str):
            raise IntegrityFailure("Current Handler accepted source authority identity is invalid")
        if accepted_source_field_id != candidate.source_observation_field_id:
            raise SomaError("IMPORT_PROPOSAL_STALE", "Current Handler supporting source field changed")
        if current_contact_id == candidate.contact_id and current_supporting_observation_id == accepted_handler_observation_id:
            raise SomaError("IMPORT_PROPOSAL_STALE", "Contact reconciliation no longer represents a material relationship change")

        current_base = self._sr_import_mutations.contact_reconciliation_base_token(
            uow.connection,
            proposal.target_internal_id,
            reference_role,
            candidate.contact_id,
            candidate.source_observation_field_id,
        )
        if not hmac.compare_digest(current_base, base_token):
            raise SomaError("IMPORT_PROPOSAL_STALE", "Service Request Contact reconciliation base state changed")

        disposition_id = new_uuid4()
        orchestration_audit_id = new_uuid4()
        decided_at = utc_epoch_seconds()
        mutation = ServiceRequestContactReviewMutation(
            service_request_id=proposal.target_internal_id,
            reference_role=reference_role,
            target_contact_id=candidate.contact_id,
            expected_prior_contact_id=candidate.prior_contact_id,
            base_state_token=base_token,
            reconciliation_proposal_id=proposal.proposal_id,
            source_observation_id=candidate.source_observation_id,
            source_observation_field_id=candidate.source_observation_field_id,
            accepted_command_id=command_id,
            proposal_revision=proposal_revision,
            proposal_fingerprint=proposal.proposal_fingerprint,
            reason_category=reason,
            review_fingerprint=proposal.proposal_fingerprint,
            actor_kind=actor_kind,
            actor_id=actor_id,
        )

        def apply(inner: UnitOfWork):
            owner_result = self._sr_import_mutations.set_current_handler_contact_reference_from_review(inner, mutation)
            self._repository.transition_accept(
                inner,
                proposal=proposal,
                run=run,
                decided_at_utc=decided_at,
                disposition_id=disposition_id,
                reason_category=reason,
                command_id=command_id,
            )
            orchestration = self._orchestration_audit(
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
            response_factory=lambda inner: self._decision_response(
                inner,
                proposal_id=proposal.proposal_id,
                command_id=command_id,
            ),
        )
