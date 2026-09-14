from __future__ import annotations

import hmac

from soma.foundation.audit.writer import AuditEventInput, AuditResultRef
from soma.foundation.errors import SomaError
from soma.foundation.identifiers import new_uuid4, utc_epoch_seconds
from soma.foundation.persistence.uow import UnitOfWork

from ._import_mutations_core import *  # noqa: F401,F403
from ._import_mutations_core import (
    ServiceRequestContactReviewMutation,
    ServiceRequestContactReviewResult,
    ServiceRequestImportMutationService as _CoreServiceRequestImportMutationService,
)
from .repositories.sr_references import SrContactRelationshipRecord
from .sr_references import build_contact_preview_state


class ServiceRequestImportMutationService(_CoreServiceRequestImportMutationService):
    """LLD-03 import mutation service with certified Current Handler evidence-rebind materiality."""

    def _set_contact_from_review(
        self,
        uow: UnitOfWork,
        mutation: ServiceRequestContactReviewMutation,
        *,
        expected_role: str,
    ) -> ServiceRequestContactReviewResult:
        if self._contact_proposal_provider is None:
            raise SomaError("IMPORT_PROPOSAL_BLOCKED", "Contact reconciliation proposal provider is not configured")
        if mutation.reference_role != expected_role:
            raise SomaError("IMPORT_PROPOSAL_STALE", "SR Contact reconciliation role no longer matches owner operation")
        current_base = self.contact_reconciliation_base_token(
            uow.connection,
            mutation.service_request_id,
            mutation.reference_role,
            mutation.target_contact_id,
            mutation.source_observation_field_id,
        )
        if not hmac.compare_digest(current_base, mutation.base_state_token):
            raise SomaError("IMPORT_PROPOSAL_STALE", "Service Request Contact reconciliation base state changed")

        supporting_observation_id = self._supporting_accepted_contact_observation(
            uow.connection,
            service_request_id=mutation.service_request_id,
            reference_role=mutation.reference_role,
            source_observation_field_id=mutation.source_observation_field_id,
        )
        state = build_contact_preview_state(
            uow.connection,
            service_request_id=mutation.service_request_id,
            reference_role=mutation.reference_role,
            contact_id=mutation.target_contact_id,
            supporting_source_observation_id=supporting_observation_id,
        )
        if state.handler_stale or state.target_invalid or state.affiliation_mismatch:
            raise SomaError("IMPORT_PROPOSAL_STALE", "reviewed Contact reference is no longer eligible")
        current_contact_id = None if state.current_relationship is None else state.current_relationship.contact_id
        current_supporting_observation_id = (
            None if state.current_relationship is None else state.current_relationship.supporting_source_observation_id
        )
        if current_contact_id != mutation.expected_prior_contact_id:
            raise SomaError("IMPORT_PROPOSAL_STALE", "Service Request Contact no longer matches proposal before-state")
        if current_contact_id == mutation.target_contact_id and (
            mutation.reference_role != "current_handler_reference"
            or current_supporting_observation_id == supporting_observation_id
        ):
            raise SomaError("IMPORT_PROPOSAL_STALE", "Contact reconciliation no longer represents a material relationship change")

        evidence_state = self._contact_proposal_provider.validate_sr_contact_acceptance(
            uow.connection,
            mutation.reconciliation_proposal_id,
            mutation.service_request_id,
            mutation.reference_role,
            mutation.target_contact_id,
            mutation.source_observation_field_id,
            {
                "command_id": mutation.accepted_command_id,
                "proposal_revision": mutation.proposal_revision,
                "proposal_fingerprint": mutation.proposal_fingerprint,
            },
        )
        if evidence_state != "VALID":
            raise SomaError("IMPORT_PROPOSAL_STALE", "SR Contact proposal evidence is no longer exact")

        prior_relationship_id = None if state.current_relationship is None else state.current_relationship.relationship_id
        new_relationship_id = new_uuid4()
        audit_event_id = new_uuid4()
        now = utc_epoch_seconds()
        if prior_relationship_id is not None:
            self._reference_repository.supersede_contact(
                uow,
                prior_relationship_id,
                closed_at_utc=now,
                command_id=mutation.accepted_command_id,
            )
        self._reference_repository.insert_contact(
            uow,
            SrContactRelationshipRecord(
                relationship_id=new_relationship_id,
                service_request_id=mutation.service_request_id,
                reference_role=mutation.reference_role,
                contact_id=mutation.target_contact_id,
                customer_org_context_id=state.current_customer_org_id,
                relationship_state="active",
                origin_kind="advanced_search_review",
                reconciliation_proposal_id=mutation.reconciliation_proposal_id,
                supporting_source_observation_id=supporting_observation_id,
                opened_at_utc=now,
                closed_at_utc=None,
                opened_command_id=mutation.accepted_command_id,
                closed_command_id=None,
                reason_category=mutation.reason_category,
            ),
        )
        base_revision = state.preview.base_revision
        updated = uow.connection.execute(
            "UPDATE service_requests SET revision=revision+1,updated_at_utc=? WHERE service_request_id=? AND revision=?",
            (now, mutation.service_request_id, base_revision),
        )
        if updated.rowcount != 1:
            raise SomaError("IMPORT_PROPOSAL_STALE", "Service Request revision changed during Contact reconciliation")

        owner_audit = AuditEventInput(
            audit_event_id=audit_event_id,
            action_type="ticket.service_request.contact_reference_changed",
            action_version=1,
            actor_kind=mutation.actor_kind,
            actor_id=mutation.actor_id,
            target_type="service_request",
            target_id=mutation.service_request_id,
            reason_category=mutation.reason_category,
            command_id=mutation.accepted_command_id,
            proposal_id=mutation.reconciliation_proposal_id,
            payload_schema="ServiceRequestReferenceAuditV1",
            payload_version=1,
            payload={
                "service_request_id": mutation.service_request_id,
                "reference_role": mutation.reference_role,
                "prior_reference_id": current_contact_id,
                "new_reference_id": mutation.target_contact_id,
                "customer_org_context_id": state.current_customer_org_id,
                "source_observation_id": mutation.source_observation_id,
                "resulting_revision": base_revision + 1,
                "reason_category": mutation.reason_category,
                "review_fingerprint": mutation.review_fingerprint,
            },
            resulting_event_refs=(AuditResultRef("service_request_contact_history", new_relationship_id),),
        )
        return ServiceRequestContactReviewResult(
            result_refs=(("service_request_contact_history", new_relationship_id),),
            audit_events=(owner_audit,),
            resulting_revision=base_revision + 1,
        )
