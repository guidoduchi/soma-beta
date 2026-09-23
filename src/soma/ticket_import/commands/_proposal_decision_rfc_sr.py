from __future__ import annotations

import hmac
from typing import Any

from soma.foundation.application.command_boundary import CommandEnvelope, PreparedMutation
from soma.foundation.errors import IntegrityFailure, SomaError, ValidationError
from soma.foundation.identifiers import new_uuid4, utc_epoch_seconds
from soma.foundation.persistence.uow import UnitOfWork
from soma.ticket_import.providers.rfc_identity_evidence import TicketImportRfcIdentityEvidenceProvider
from soma.ticket_import.providers.rfc_review_evidence import TicketImportRfcReviewEvidenceProvider
from soma.ticket_import.providers.rfc_source_evidence import TicketImportRfcSourceEvidenceProvider
from soma.tickets.import_mutations import ServiceRequestContactReviewMutation
from soma.tickets.rfc_import_mutations import (
    RfcCreateFromSourceMutation,
    RfcCustomerReviewMutation,
    RfcImportMutationService,
    RfcSourceProjectionMutation,
    RfcSrLinkReviewMutation,
)
from soma.tickets.rfc_import_reader import RfcImportReader
from soma.tickets.rfc_source_projection import RfcTerminalCascadeCaptureParticipant
from soma.tickets.service_request_import_reader import ServiceRequestImportReader as _CurrentHandlerImportReader

from ._proposal_decision_public_core import *  # noqa: F401,F403
from ._proposal_decision_public_core import ProposalDecisionService as _CoreProposalDecisionService
from ._proposal_writes import pending_write_from_draft
from ._proposal_decision_core import (
    _REVIEWED_SR_SOURCE_CORRECTION_KINDS,
    _SR_CONTACT_PROPOSAL_ROLES,
    _validate_fingerprint,
    _validate_optional_reason,
)
from ..repositories.proposals import ProposalRecord
from ..reconciliation.rfc_follow_on import build_rfc_identity_follow_on_proposals


_RFC_CURRENT_VALUE_COLUMNS = {
    "summary": "summary_text",
    "external_created_at": "external_created_at_utc",
    "creator": "creator_text",
    "customer_account_number": "customer_account_number_text",
    "customer_account_name": "customer_account_name_text",
    "severity": "severity_text",
    "status": "status_text",
    "owner_external_id": "owner_external_id_text",
    "owner_name": "owner_name_text",
    "l1_handler_name": "l1_handler_name_text",
    "l2_handler_name": "l2_handler_name_text",
    "last_update": "last_update_utc",
}
_RFC_TERMINAL_CLASSES = frozenset({"terminal_closed", "terminal_cancelled"})


class ProposalDecisionService(_CoreProposalDecisionService):
    """Public proposal-decision service with SR evidence-rebind and RFC import owner support."""

    def __init__(
        self,
        *args: Any,
        rfc_import_mutation_service: RfcImportMutationService | None = None,
        rfc_terminal_capture_participant: RfcTerminalCascadeCaptureParticipant | None = None,
        **kwargs: Any,
    ) -> None:
        super().__init__(*args, **kwargs)
        self._rfc_identity_provider = TicketImportRfcIdentityEvidenceProvider()
        self._rfc_source_provider = TicketImportRfcSourceEvidenceProvider()
        self._rfc_review_provider = TicketImportRfcReviewEvidenceProvider()
        self._rfc_import_reader = RfcImportReader()
        self._rfc_import_mutations = (
            RfcImportMutationService(
                self._rfc_source_provider,
                terminal_capture_participant=rfc_terminal_capture_participant,
            )
            if rfc_import_mutation_service is None
            else rfc_import_mutation_service
        )

    def _prepare_rfc_create_accept(
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
        if (
            proposal.evidence_mode != "observed_row"
            or proposal.source_observation_id is None
            or proposal.target_kind != "rfc"
            or proposal.target_internal_id is not None
            or proposal.target_business_id is None
            or proposal.risk_class != "medium"
        ):
            raise SomaError("IMPORT_PROPOSAL_STALE", "RFC identity creation proposal binding is invalid")
        changes = self._repository.list_changes(uow.connection, proposal.proposal_id)
        if len(changes) != 1:
            raise SomaError("IMPORT_PROPOSAL_STALE", "RFC identity creation requires exactly one immutable change")
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
            raise SomaError("IMPORT_PROPOSAL_STALE", "RFC identity creation proposal encoding is invalid")
        self._rfc_identity_provider.validate_observed_identity(
            uow.connection,
            expected_import_run_id=proposal.import_run_id,
            source_observation_id=proposal.source_observation_id,
            canonical_rfc_no=proposal.target_business_id,
        )
        current_base = self._rfc_import_mutations.source_identity_base_token(
            uow.connection,
            proposal.target_business_id,
        )
        if not hmac.compare_digest(current_base, base_token):
            raise SomaError("IMPORT_PROPOSAL_STALE", "RFC identity base state changed")

        disposition_id = new_uuid4()
        orchestration_audit_id = new_uuid4()
        decided_at = utc_epoch_seconds()
        mutation = RfcCreateFromSourceMutation(
            rfc_no=proposal.target_business_id,
            base_state_token=base_token,
            accepted_command_id=command_id,
            actor_kind=actor_kind,
            actor_id=actor_id,
        )

        def apply(inner: UnitOfWork):
            owner_result = self._rfc_import_mutations.create_or_adopt_from_source(inner, mutation)
            follow_on_drafts = build_rfc_identity_follow_on_proposals(
                inner.connection,
                import_run_id=proposal.import_run_id,
                source_observation_id=proposal.source_observation_id,
            )
            follow_on_writes = tuple(pending_write_from_draft(draft) for draft in follow_on_drafts)
            self._repository.transition_accept(
                inner,
                proposal=proposal,
                run=run,
                decided_at_utc=decided_at,
                disposition_id=disposition_id,
                reason_category=reason,
                command_id=command_id,
            )
            self._repository.insert_follow_on_pending_set(
                inner,
                import_run_id=proposal.import_run_id,
                expected_run_revision=run.revision + 1,
                writes=follow_on_writes,
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

    def _prepare_rfc_source_projection_accept(
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
        if (
            proposal.evidence_mode != "observed_row"
            or proposal.source_observation_id is None
            or proposal.target_kind != "rfc"
            or proposal.target_internal_id is None
            or proposal.target_business_id is None
            or proposal.risk_class not in {"medium", "high"}
        ):
            raise SomaError("IMPORT_PROPOSAL_STALE", "RFC source projection proposal binding is invalid")
        target = self._rfc_import_reader.get_by_number(uow.connection, proposal.target_business_id)
        if target is None or target.get("rfc_id") != proposal.target_internal_id:
            raise SomaError("IMPORT_PROPOSAL_STALE", "proposal target identity no longer matches the RFC")
        current_base = self._rfc_import_mutations.source_acceptance_base_token(
            uow.connection,
            proposal.target_internal_id,
        )
        if not hmac.compare_digest(current_base, base_token):
            raise SomaError("IMPORT_PROPOSAL_STALE", "RFC source projection base state changed")

        changes = self._repository.list_changes(uow.connection, proposal.proposal_id)
        if not changes or len(changes) > len(_RFC_CURRENT_VALUE_COLUMNS):
            raise SomaError("IMPORT_PROPOSAL_STALE", "RFC source projection change set is empty or exceeds field registry")
        if len({change.field_key for change in changes}) != len(changes):
            raise SomaError("IMPORT_PROPOSAL_STALE", "RFC source projection proposal repeats a field")
        current = self._rfc_import_reader.current_source_projection(uow.connection, proposal.target_internal_id)
        deltas = []
        terminal_sensitive = False
        for change in changes:
            column = _RFC_CURRENT_VALUE_COLUMNS.get(change.field_key)
            if column is None:
                raise SomaError("IMPORT_PROPOSAL_STALE", "RFC source projection contains an unallowlisted field")
            if (
                change.change_kind != "set"
                or change.source_observation_field_id is None
                or change.value_kind not in {"text", "controlled", "instant"}
            ):
                raise SomaError("IMPORT_PROPOSAL_STALE", "RFC source projection change encoding is invalid")
            delta = self._rfc_source_provider.build_source_projection_delta(
                uow.connection,
                rfc_id=proposal.target_internal_id,
                expected_import_run_id=proposal.import_run_id,
                expected_source_observation_id=proposal.source_observation_id,
                source_observation_field_id=change.source_observation_field_id,
                expected_field_key=change.field_key,
            )
            if delta.value_kind != change.value_kind:
                raise SomaError("IMPORT_PROPOSAL_STALE", "RFC source projection value kind changed")
            if delta.value_kind in {"text", "controlled"}:
                if (
                    change.after_text != delta.value
                    or change.after_integer is not None
                    or change.before_integer is not None
                ):
                    raise SomaError("IMPORT_PROPOSAL_STALE", "RFC source projection text evidence changed")
                current_value = None if current is None else current.get(column)
                expected_before = None if current_value is None else str(current_value)
                if change.before_text != expected_before:
                    raise SomaError("IMPORT_PROPOSAL_STALE", "RFC source projection before-state changed")
            else:
                if (
                    change.after_integer != delta.value
                    or change.after_text is not None
                    or change.before_text is not None
                ):
                    raise SomaError("IMPORT_PROPOSAL_STALE", "RFC source projection instant evidence changed")
                current_value = None if current is None else current.get(column)
                expected_before = None if current_value is None else int(current_value)
                if change.before_integer != expected_before:
                    raise SomaError("IMPORT_PROPOSAL_STALE", "RFC source projection before-state changed")
            if change.field_key == "status":
                current_class = None if current is None else current.get("status_class")
                if delta.status_class in _RFC_TERMINAL_CLASSES or current_class in _RFC_TERMINAL_CLASSES:
                    terminal_sensitive = True
            deltas.append(delta)

        expected_risk = "high" if terminal_sensitive else "medium"
        if proposal.risk_class != expected_risk:
            raise SomaError("IMPORT_PROPOSAL_STALE", "RFC source projection risk classification changed")

        disposition_id = new_uuid4()
        orchestration_audit_id = new_uuid4()
        decided_at = utc_epoch_seconds()
        mutation = RfcSourceProjectionMutation(
            rfc_id=proposal.target_internal_id,
            base_state_token=base_token,
            deltas=tuple(deltas),
            accepted_command_id=command_id,
            review_fingerprint=proposal.proposal_fingerprint,
            actor_kind=actor_kind,
            actor_id=actor_id,
        )

        def apply(inner: UnitOfWork):
            owner_result = self._rfc_import_mutations.apply_accepted_source_projection(inner, mutation)
            if owner_result.projection_result.no_change:
                raise SomaError("IMPORT_PROPOSAL_STALE", "RFC source projection no longer represents a material change")
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

    def _prepare_rfc_customer_accept(
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
        if (
            proposal.evidence_mode != "observed_row"
            or proposal.source_observation_id is None
            or proposal.target_kind != "rfc"
            or proposal.target_internal_id is None
            or proposal.target_business_id is None
            or proposal.risk_class != "high"
        ):
            raise SomaError("IMPORT_PROPOSAL_STALE", "RFC Customer reconciliation proposal binding is invalid")
        changes = self._repository.list_changes(uow.connection, proposal.proposal_id)
        if len(changes) != 1:
            raise SomaError("IMPORT_PROPOSAL_STALE", "RFC Customer reconciliation requires exactly one identity change")
        change = changes[0]
        if (
            change.ordinal != 0
            or change.field_key != "customer_org_id"
            or change.change_kind != "set"
            or change.value_kind != "identity"
            or change.after_text is None
            or change.before_integer is not None
            or change.after_integer is not None
            or change.source_observation_field_id is None
        ):
            raise SomaError("IMPORT_PROPOSAL_STALE", "RFC Customer reconciliation proposal encoding is invalid")
        candidate = self._rfc_review_provider.revalidate_customer_candidate(
            uow.connection,
            expected_import_run_id=proposal.import_run_id,
            expected_source_observation_id=proposal.source_observation_id,
            rfc_id=proposal.target_internal_id,
            rfc_no=proposal.target_business_id,
            source_observation_field_id=change.source_observation_field_id,
            expected_customer_org_id=change.after_text,
        )
        if candidate.current_customer_org_id != change.before_text:
            raise SomaError("IMPORT_PROPOSAL_STALE", "RFC Customer before-state changed")
        if candidate.current_customer_org_id == candidate.customer_org_id:
            raise SomaError("IMPORT_PROPOSAL_STALE", "RFC Customer proposal no longer represents a material change")
        current_base = self._rfc_import_mutations.customer_reconciliation_base_token(
            uow.connection,
            candidate.rfc_id,
            candidate.customer_org_id,
        )
        if not hmac.compare_digest(current_base, base_token):
            raise SomaError("IMPORT_PROPOSAL_STALE", "RFC Customer reconciliation base state changed")

        disposition_id = new_uuid4()
        orchestration_audit_id = new_uuid4()
        decided_at = utc_epoch_seconds()
        mutation = RfcCustomerReviewMutation(
            rfc_id=candidate.rfc_id,
            target_customer_org_id=candidate.customer_org_id,
            expected_prior_customer_org_id=candidate.current_customer_org_id,
            base_state_token=base_token,
            accepted_command_id=command_id,
            reason_category=reason,
            review_fingerprint=proposal.proposal_fingerprint,
            actor_kind=actor_kind,
            actor_id=actor_id,
        )

        def apply(inner: UnitOfWork):
            owner_result = self._rfc_import_mutations.set_customer_from_review(inner, mutation)
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

    def _prepare_rfc_sr_link_accept(
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
        if (
            proposal.evidence_mode != "observed_row"
            or proposal.source_observation_id is None
            or proposal.target_kind != "sr_rfc_relationship"
            or proposal.target_internal_id is None
            or proposal.target_business_id is None
            or proposal.risk_class not in {"medium", "high"}
        ):
            raise SomaError("IMPORT_PROPOSAL_STALE", "RFC/SR link candidate proposal binding is invalid")
        changes = self._repository.list_changes(uow.connection, proposal.proposal_id)
        if len(changes) != 1:
            raise SomaError("IMPORT_PROPOSAL_STALE", "RFC/SR link candidate requires exactly one identity change")
        change = changes[0]
        if (
            change.ordinal != 0
            or change.field_key != "service_request_id"
            or change.change_kind != "candidate"
            or change.value_kind != "identity"
            or change.before_text is not None
            or change.after_text is None
            or change.before_integer is not None
            or change.after_integer is not None
            or change.source_observation_field_id is None
        ):
            raise SomaError("IMPORT_PROPOSAL_STALE", "RFC/SR link candidate proposal encoding is invalid")
        candidate = self._rfc_review_provider.revalidate_sr_link_candidate(
            uow.connection,
            expected_import_run_id=proposal.import_run_id,
            expected_source_observation_id=proposal.source_observation_id,
            requested_rfc_id=proposal.target_internal_id,
            rfc_no=proposal.target_business_id,
            source_observation_field_id=change.source_observation_field_id,
            service_request_id=change.after_text,
        )
        context = self._rfc_import_mutations.sr_link_candidate_context(
            uow.connection,
            candidate.service_request_id,
            candidate.requested_rfc_id,
        )
        if context.duplicate_active:
            raise SomaError("IMPORT_PROPOSAL_STALE", "reviewed RFC/SR relationship is already active")
        if context.risk_class != proposal.risk_class:
            raise SomaError("IMPORT_PROPOSAL_STALE", "RFC/SR relationship risk context changed")
        if not hmac.compare_digest(context.base_state_token, base_token):
            raise SomaError("IMPORT_PROPOSAL_STALE", "RFC/SR relationship base state changed")

        disposition_id = new_uuid4()
        orchestration_audit_id = new_uuid4()
        decided_at = utc_epoch_seconds()
        mutation = RfcSrLinkReviewMutation(
            service_request_id=candidate.service_request_id,
            requested_rfc_id=candidate.requested_rfc_id,
            base_state_token=base_token,
            accepted_command_id=command_id,
            reason_category=reason,
            actor_kind=actor_kind,
            actor_id=actor_id,
        )

        def apply(inner: UnitOfWork):
            owner_result = self._rfc_import_mutations.link_sr_from_review(inner, mutation)
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

    def accept(
        self,
        *,
        command_id: str,
        proposal_id: str,
        proposal_revision: int,
        proposal_fingerprint: str,
        base_state_token: str,
        reason_category: str | None = None,
        actor_kind: str = "local_user",
        actor_id: str | None = None,
    ) -> ProposalDecisionResult:
        if type(proposal_revision) is not int or proposal_revision <= 0:
            raise ValidationError("proposal_revision must be a positive integer")
        fingerprint = _validate_fingerprint(proposal_fingerprint)
        base_token = _validate_fingerprint(base_state_token, field_name="base_state_token")
        reason = _validate_optional_reason(reason_category)
        envelope = CommandEnvelope(
            command_id=command_id,
            command_type="AcceptReconciliationProposal",
            target_type="reconciliation_proposal",
            target_id=proposal_id,
            semantic_payload={
                "decision": "accepted",
                "proposal_revision": proposal_revision,
                "proposal_fingerprint": fingerprint,
                "base_state_token": base_token,
                "reason_category": reason,
            },
            base_revisions={"proposal": proposal_revision},
            authorizing_fingerprints={"proposal": fingerprint, "base_state": base_token},
        )

        def prepare(uow: UnitOfWork) -> PreparedMutation:
            proposal = self._repository.require_pending(uow.connection, proposal_id)
            if (
                proposal.revision != proposal_revision
                or not hmac.compare_digest(proposal.proposal_fingerprint, fingerprint)
                or not hmac.compare_digest(proposal.base_state_token, base_token)
            ):
                raise SomaError("IMPORT_PROPOSAL_STALE", "proposal revision/fingerprint/base state changed")
            if proposal.risk_class == "blocked":
                raise SomaError("IMPORT_PROPOSAL_BLOCKED", "blocked reconciliation proposal cannot be accepted")
            run = self._repository.get_run(uow.connection, proposal.import_run_id)
            if run.run_state not in {"staged", "waiting_review", "recovery_required"}:
                raise SomaError("IMPORT_PROPOSAL_STALE", "parent import run no longer permits proposal acceptance")
            self._repository.require_current_recovery_authorization(uow.connection, run)
            if proposal.proposal_kind == "rfc_create_or_adopt":
                return self._prepare_rfc_create_accept(
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
            if proposal.proposal_kind == "rfc_source_projection":
                return self._prepare_rfc_source_projection_accept(
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
            if proposal.proposal_kind == "rfc_customer_reconciliation":
                return self._prepare_rfc_customer_accept(
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
            if proposal.proposal_kind == "sr_rfc_link_candidate":
                return self._prepare_rfc_sr_link_accept(
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
            if proposal.proposal_kind == "sr_create_or_adopt":
                return self._prepare_sr_create_accept(
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
            if proposal.proposal_kind == "sr_source_projection":
                return self._prepare_sr_source_projection_accept(
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
            if proposal.proposal_kind in _REVIEWED_SR_SOURCE_CORRECTION_KINDS:
                return self._prepare_sr_source_projection_accept(
                    uow,
                    proposal=proposal,
                    run=run,
                    base_token=base_token,
                    proposal_revision=proposal_revision,
                    command_id=command_id,
                    reason=reason,
                    actor_kind=actor_kind,
                    actor_id=actor_id,
                    precedence_basis="reviewed_correction",
                )
            if proposal.proposal_kind == "sr_customer_reconciliation":
                return self._prepare_sr_customer_accept(
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
            if proposal.proposal_kind in _SR_CONTACT_PROPOSAL_ROLES:
                return self._prepare_sr_contact_accept(
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
            if proposal.proposal_kind == "sr_source_disappearance_review":
                return self._prepare_sr_disappearance_accept(
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
            raise SomaError(
                "IMPORT_PROPOSAL_BLOCKED",
                "proposal kind has no implemented owning-domain acceptance participant",
            )

        return self._result_from_execution(self._boundary.execute(envelope, prepare))

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
