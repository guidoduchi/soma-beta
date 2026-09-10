from __future__ import annotations

import hmac
import re
from dataclasses import dataclass
from typing import Any, Protocol

from soma.foundation.application.command_boundary import (
    CommandBoundary,
    CommandEnvelope,
    CommandExecutionResult,
    PreparedMutation,
)
from soma.foundation.audit.registry import AuditRegistry
from soma.foundation.audit.writer import AuditEventInput, AuditResultRef, AuditWriter
from soma.foundation.errors import IntegrityFailure, PersistenceFailure, SomaError, ValidationError
from soma.foundation.identifiers import new_uuid4, utc_epoch_seconds
from soma.foundation.persistence.connections import ConnectionFactory
from soma.foundation.persistence.uow import UnitOfWork
from soma.ticket_import.providers.sr_customer_reconciliation import TicketImportSrCustomerReconciliationProvider
from soma.ticket_import.providers.sr_identity_evidence import TicketImportSrIdentityEvidenceProvider
from soma.ticket_import.providers.sr_source_evidence import TicketImportSrSourceEvidenceProvider
from soma.tickets.audit_registry import build_tickets_audit_registry
from soma.tickets.import_mutations import (
    ServiceRequestCreateFromSourceMutation,
    ServiceRequestCreateFromSourceResult,
    ServiceRequestCustomerReviewMutation,
    ServiceRequestCustomerReviewResult,
    ServiceRequestImportMutationResult,
    ServiceRequestImportMutationService,
    ServiceRequestSourceProjectionMutation,
)
from soma.tickets.sr_references import ServiceRequestCustomerClassificationParticipant
from soma.tickets.sr_source_projection import AcceptedSrFieldDeltaSet

from ..audit_registry import build_ticket_import_audit_registry
from ..repositories.proposals import ProposalRecord, ProposalRepository


_HEX64_RE = re.compile(r"[0-9a-f]{64}\Z")
_METADATA_RESULT_TYPES = frozenset({"proposal_disposition", "proposal_equivalence_decision"})
_TERMINAL_SR_STATUSES = frozenset({"Closed", "Resolved", "Cancelled"})
_REVIEWED_SR_SOURCE_CORRECTION_KINDS = frozenset(
    {"sr_terminal_reversal_review", "sr_suspension_regression_review"}
)


class ServiceRequestImportMutationParticipant(Protocol):
    def source_identity_base_token(self, reader: Any, official_sr_no: str) -> str: ...

    def create_or_adopt_from_source(
        self,
        uow: UnitOfWork,
        mutation: ServiceRequestCreateFromSourceMutation,
    ) -> ServiceRequestCreateFromSourceResult: ...

    def source_acceptance_base_token(self, reader: Any, service_request_id: str) -> str: ...

    def apply_accepted_source_projection(
        self,
        uow: UnitOfWork,
        mutation: ServiceRequestSourceProjectionMutation,
    ) -> ServiceRequestImportMutationResult: ...

    def customer_reconciliation_base_token(
        self,
        reader: Any,
        service_request_id: str,
        target_customer_org_id: str,
    ) -> str: ...

    def set_customer_from_review(
        self,
        uow: UnitOfWork,
        mutation: ServiceRequestCustomerReviewMutation,
    ) -> ServiceRequestCustomerReviewResult: ...


@dataclass(frozen=True, slots=True)
class ProposalDecisionResult:
    proposal_id: str
    decision: str
    revision: int
    owner_result_refs: tuple[tuple[str, str], ...]
    replayed: bool


def _validate_fingerprint(value: str, *, field_name: str = "proposal_fingerprint") -> str:
    if not isinstance(value, str) or _HEX64_RE.fullmatch(value) is None:
        raise ValidationError(f"{field_name} must be lowercase SHA-256 hex")
    return value


def _validate_reason(value: str) -> str:
    if not isinstance(value, str):
        raise ValidationError("reason_category must be a string")
    encoded = value.encode("utf-8", errors="strict")
    if not encoded or len(encoded) > 120 or "\x00" in value or "\r" in value or "\n" in value:
        raise ValidationError("reason_category violates the LLD-04 1..120 UTF-8 byte one-line contract")
    return value


def _validate_optional_reason(value: str | None) -> str | None:
    return None if value is None else _validate_reason(value)


def _build_acceptance_audit_registry() -> AuditRegistry:
    registry = build_ticket_import_audit_registry()
    registry.extend(build_tickets_audit_registry())
    return registry


class ProposalDecisionService:
    """LLD-04 proposal decision authority; owner mutations remain injected cross-packet participants."""

    def __init__(
        self,
        connection_factory: ConnectionFactory,
        *,
        sr_import_mutation_service: ServiceRequestImportMutationParticipant | None = None,
        sr_customer_classification_participant: ServiceRequestCustomerClassificationParticipant | None = None,
    ) -> None:
        self._factory = connection_factory
        self._repository = ProposalRepository()
        self._sr_source_provider = TicketImportSrSourceEvidenceProvider()
        self._sr_identity_provider = TicketImportSrIdentityEvidenceProvider()
        self._sr_customer_provider = TicketImportSrCustomerReconciliationProvider()
        self._sr_import_mutations = (
            ServiceRequestImportMutationService(
                self._sr_source_provider,
                customer_proposal_provider=self._sr_customer_provider,
                classification_participant=sr_customer_classification_participant,
            )
            if sr_import_mutation_service is None
            else sr_import_mutation_service
        )
        self._boundary = CommandBoundary(
            connection_factory,
            AuditWriter(_build_acceptance_audit_registry()),
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
            raise PersistenceFailure("proposal decision response target disappeared before commit")
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
    def _result_from_execution(execution: CommandExecutionResult) -> ProposalDecisionResult:
        if execution.response_schema != "ProposalDecisionResultV1" or execution.response_version != 1:
            raise IntegrityFailure("proposal decision result schema/version is invalid")
        response = execution.response
        if not isinstance(response, dict):
            raise IntegrityFailure("proposal decision result payload is invalid")
        proposal_id = response.get("proposal_id")
        decision = response.get("decision")
        revision = response.get("revision")
        refs = response.get("owner_result_refs")
        if (
            not isinstance(proposal_id, str)
            or decision not in {"accepted", "rejected", "deferred"}
            or type(revision) is not int
            or revision <= 0
            or not isinstance(refs, list)
        ):
            raise IntegrityFailure("proposal decision result fields are invalid")
        owner_refs: list[tuple[str, str]] = []
        for ref in refs:
            if (
                not isinstance(ref, dict)
                or set(ref) != {"type", "id"}
                or not isinstance(ref.get("type"), str)
                or not ref.get("type")
                or not isinstance(ref.get("id"), str)
                or not ref.get("id")
            ):
                raise IntegrityFailure("proposal decision owner result ref is invalid")
            owner_refs.append((str(ref["type"]), str(ref["id"])))
        return ProposalDecisionResult(
            proposal_id=proposal_id,
            decision=str(decision),
            revision=revision,
            owner_result_refs=tuple(owner_refs),
            replayed=execution.replayed,
        )

    @staticmethod
    def _orchestration_audit(
        *,
        audit_event_id: str,
        command_id: str,
        proposal: ProposalRecord,
        proposal_revision: int,
        reason: str | None,
        actor_kind: str,
        actor_id: str | None,
        disposition_id: str,
        owner_result_refs: tuple[tuple[str, str], ...],
    ) -> AuditEventInput:
        return AuditEventInput(
            audit_event_id=audit_event_id,
            action_type="ticket_import.proposal_decided",
            action_version=1,
            actor_kind=actor_kind,
            actor_id=actor_id,
            target_type="reconciliation_proposal",
            target_id=proposal.proposal_id,
            reason_category=reason,
            command_id=command_id,
            import_run_id=proposal.import_run_id,
            proposal_id=proposal.proposal_id,
            payload_schema="ImportProposalDecisionAuditV1",
            payload_version=1,
            payload={
                "proposal_id": proposal.proposal_id,
                "proposal_kind": proposal.proposal_kind,
                "decision": "accepted",
                "proposal_revision": proposal_revision,
                "reason_category": reason,
                "owner_result_refs": [
                    {"type": result_type, "id": result_id}
                    for result_type, result_id in owner_result_refs
                ],
            },
            resulting_event_refs=(
                AuditResultRef("proposal_disposition", disposition_id),
                *(AuditResultRef(result_type, result_id) for result_type, result_id in owner_result_refs),
            ),
        )

    def _prepare_sr_create_accept(
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
            or proposal.target_kind != "service_request"
            or proposal.target_internal_id is not None
            or proposal.target_business_id is None
        ):
            raise SomaError("IMPORT_PROPOSAL_STALE", "SR identity creation proposal binding is incomplete")
        self._sr_identity_provider.validate_observed_identity(
            uow.connection,
            expected_import_run_id=proposal.import_run_id,
            source_observation_id=proposal.source_observation_id,
            canonical_sr_no=proposal.target_business_id,
        )
        current_base = self._sr_import_mutations.source_identity_base_token(
            uow.connection,
            proposal.target_business_id,
        )
        if not hmac.compare_digest(current_base, base_token):
            raise SomaError("IMPORT_PROPOSAL_STALE", "Service Request identity base state changed")

        disposition_id = new_uuid4()
        orchestration_audit_id = new_uuid4()
        decided_at = utc_epoch_seconds()
        mutation = ServiceRequestCreateFromSourceMutation(
            official_sr_no=proposal.target_business_id,
            base_state_token=base_token,
            accepted_command_id=command_id,
            actor_kind=actor_kind,
            actor_id=actor_id,
        )

        def apply(inner: UnitOfWork):
            owner_result = self._sr_import_mutations.create_or_adopt_from_source(inner, mutation)
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

    @staticmethod
    def _require_reviewed_source_correction_shape(
        connection: Any,
        *,
        proposal: ProposalRecord,
        changes: list[Any],
    ) -> None:
        if proposal.risk_class != "high" or len(changes) != 1:
            raise SomaError(
                "IMPORT_PROPOSAL_STALE",
                "reviewed SR source correction must remain one high-risk field change",
            )
        change = changes[0]
        if proposal.proposal_kind == "sr_terminal_reversal_review":
            if (
                change.field_key != "status"
                or change.change_kind != "set"
                or change.value_kind != "controlled"
                or change.before_text is None
                or change.after_text is None
                or change.before_integer is not None
                or change.after_integer is not None
                or change.source_observation_field_id is None
            ):
                raise SomaError("IMPORT_PROPOSAL_STALE", "terminal correction proposal encoding is invalid")
            row = connection.execute(
                "SELECT o.value_state,o.value_kind,o.text_value FROM sr_current_source_projection p "
                "JOIN sr_source_field_observations o ON o.sr_source_field_observation_id=p.status_observation_id "
                "WHERE p.service_request_id=?",
                (proposal.target_internal_id,),
            ).fetchone()
            if (
                row is None
                or str(row[0]) != "usable"
                or str(row[1]) != "controlled"
                or row[2] is None
                or str(row[2]) not in _TERMINAL_SR_STATUSES
                or str(row[2]) != change.before_text
                or change.after_text == change.before_text
            ):
                raise SomaError(
                    "IMPORT_PROPOSAL_STALE",
                    "terminal correction no longer matches the accepted terminal source state",
                )
            return
        if proposal.proposal_kind == "sr_suspension_regression_review":
            if (
                change.field_key != "suspension_duration"
                or change.change_kind != "set"
                or change.value_kind != "duration_seconds"
                or change.before_text is not None
                or change.after_text is not None
                or type(change.before_integer) is not int
                or change.before_integer <= 0
                or change.after_integer != 0
                or change.source_observation_field_id is None
            ):
                raise SomaError("IMPORT_PROPOSAL_STALE", "suspension regression proposal encoding is invalid")
            row = connection.execute(
                "SELECT o.value_state,o.value_kind,o.integer_value FROM sr_current_source_projection p "
                "JOIN sr_source_field_observations o "
                "ON o.sr_source_field_observation_id=p.suspension_duration_observation_id "
                "WHERE p.service_request_id=?",
                (proposal.target_internal_id,),
            ).fetchone()
            if (
                row is None
                or str(row[0]) != "usable"
                or str(row[1]) != "duration_seconds"
                or type(row[2]) is not int
                or int(row[2]) <= 0
                or int(row[2]) != change.before_integer
            ):
                raise SomaError(
                    "IMPORT_PROPOSAL_STALE",
                    "suspension regression no longer matches the accepted nonzero source duration",
                )
            return
        raise IntegrityFailure("unsupported reviewed SR source correction kind")

    def _prepare_sr_source_projection_accept(
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
        precedence_basis: str = "source_chronology",
    ) -> PreparedMutation:
        if (
            proposal.evidence_mode != "observed_row"
            or proposal.source_observation_id is None
            or proposal.target_kind != "service_request"
            or proposal.target_internal_id is None
            or proposal.target_business_id is None
        ):
            raise SomaError("IMPORT_PROPOSAL_STALE", "SR source projection proposal binding is incomplete")
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
        try:
            current_base = self._sr_import_mutations.source_acceptance_base_token(
                uow.connection,
                proposal.target_internal_id,
            )
        except SomaError as exc:
            if exc.code == "NOT_FOUND":
                raise SomaError("IMPORT_PROPOSAL_STALE", "Service Request target no longer exists") from exc
            raise
        if not hmac.compare_digest(current_base, base_token):
            raise SomaError("IMPORT_PROPOSAL_STALE", "Service Request owner base state changed")
        changes = self._repository.list_changes(uow.connection, proposal.proposal_id)
        if not changes or len(changes) > 11:
            raise SomaError("IMPORT_PROPOSAL_STALE", "SR source projection change set is empty or exceeds field registry")
        if len({change.field_key for change in changes}) != len(changes):
            raise SomaError("IMPORT_PROPOSAL_STALE", "SR source projection proposal repeats a field")
        if precedence_basis == "reviewed_correction":
            self._require_reviewed_source_correction_shape(
                uow.connection,
                proposal=proposal,
                changes=changes,
            )
        elif precedence_basis != "source_chronology":
            raise IntegrityFailure("unsupported SR source projection precedence basis")
        deltas = []
        for change in changes:
            if change.source_observation_field_id is None:
                raise SomaError("IMPORT_PROPOSAL_STALE", "SR source projection change lacks source field evidence")
            deltas.append(
                self._sr_source_provider.build_source_projection_delta(
                    uow.connection,
                    service_request_id=proposal.target_internal_id,
                    expected_import_run_id=proposal.import_run_id,
                    expected_source_observation_id=proposal.source_observation_id,
                    source_observation_field_id=change.source_observation_field_id,
                    field_key=change.field_key,
                    change_kind=change.change_kind,
                    change_value_kind=change.value_kind,
                    after_text=change.after_text,
                    after_integer=change.after_integer,
                    precedence_basis=precedence_basis,
                )
            )

        disposition_id = new_uuid4()
        audit_event_id = new_uuid4()
        decided_at = utc_epoch_seconds()
        mutation = ServiceRequestSourceProjectionMutation(
            service_request_id=proposal.target_internal_id,
            base_state_token=base_token,
            accepted_delta_set=AcceptedSrFieldDeltaSet(
                accepted_command_id=command_id,
                deltas=tuple(deltas),
            ),
        )

        def apply(inner: UnitOfWork):
            owner_result = self._sr_import_mutations.apply_accepted_source_projection(inner, mutation)
            self._repository.transition_accept(
                inner,
                proposal=proposal,
                run=run,
                decided_at_utc=decided_at,
                disposition_id=disposition_id,
                reason_category=reason,
                command_id=command_id,
            )
            return self._orchestration_audit(
                audit_event_id=audit_event_id,
                command_id=command_id,
                proposal=proposal,
                proposal_revision=proposal_revision,
                reason=reason,
                actor_kind=actor_kind,
                actor_id=actor_id,
                disposition_id=disposition_id,
                owner_result_refs=owner_result.result_refs,
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

    def _prepare_sr_customer_accept(
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
            or proposal.target_kind != "service_request"
            or proposal.target_internal_id is None
            or proposal.target_business_id is None
        ):
            raise SomaError("IMPORT_PROPOSAL_STALE", "SR Customer reconciliation proposal binding is incomplete")
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
            raise SomaError("IMPORT_PROPOSAL_STALE", "SR Customer reconciliation requires exactly one identity change")
        change = changes[0]
        if change.after_text is None:
            raise SomaError("IMPORT_PROPOSAL_STALE", "SR Customer reconciliation target identity is missing")
        current_base = self._sr_import_mutations.customer_reconciliation_base_token(
            uow.connection,
            proposal.target_internal_id,
            change.after_text,
        )
        if not hmac.compare_digest(current_base, base_token):
            raise SomaError("IMPORT_PROPOSAL_STALE", "Service Request Customer reconciliation base state changed")
        candidate = self._sr_customer_provider.revalidate_reviewed_candidate(
            uow.connection,
            proposal_id=proposal.proposal_id,
            expected_import_run_id=proposal.import_run_id,
            source_observation_id=proposal.source_observation_id,
            service_request_id=proposal.target_internal_id,
            canonical_sr_no=proposal.target_business_id,
            field_key=change.field_key,
            change_kind=change.change_kind,
            value_kind=change.value_kind,
            before_text=change.before_text,
            after_text=change.after_text,
            before_integer=change.before_integer,
            after_integer=change.after_integer,
            source_observation_field_id=change.source_observation_field_id,
        )

        disposition_id = new_uuid4()
        orchestration_audit_id = new_uuid4()
        decided_at = utc_epoch_seconds()
        mutation = ServiceRequestCustomerReviewMutation(
            service_request_id=proposal.target_internal_id,
            target_customer_org_id=candidate.customer_org_id,
            expected_prior_customer_org_id=candidate.prior_customer_org_id,
            base_state_token=base_token,
            reconciliation_proposal_id=proposal.proposal_id,
            source_observation_id=candidate.source_observation_id,
            accepted_command_id=command_id,
            reason_category=reason,
            review_fingerprint=proposal.proposal_fingerprint,
            actor_kind=actor_kind,
            actor_id=actor_id,
        )

        def apply(inner: UnitOfWork):
            owner_result = self._sr_import_mutations.set_customer_from_review(inner, mutation)
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
            raise SomaError(
                "IMPORT_PROPOSAL_BLOCKED",
                "proposal kind has no implemented owning-domain acceptance participant",
            )

        return self._result_from_execution(self._boundary.execute(envelope, prepare))

    def reject(
        self,
        *,
        command_id: str,
        proposal_id: str,
        proposal_revision: int,
        proposal_fingerprint: str,
        reason_category: str,
        actor_kind: str = "local_user",
        actor_id: str | None = None,
    ) -> ProposalDecisionResult:
        return self._decide(
            command_id=command_id,
            proposal_id=proposal_id,
            proposal_revision=proposal_revision,
            proposal_fingerprint=proposal_fingerprint,
            reason_category=reason_category,
            decision="rejected",
            command_type="RejectReconciliationProposal",
            actor_kind=actor_kind,
            actor_id=actor_id,
        )

    def defer(
        self,
        *,
        command_id: str,
        proposal_id: str,
        proposal_revision: int,
        proposal_fingerprint: str,
        reason_category: str,
        actor_kind: str = "local_user",
        actor_id: str | None = None,
    ) -> ProposalDecisionResult:
        return self._decide(
            command_id=command_id,
            proposal_id=proposal_id,
            proposal_revision=proposal_revision,
            proposal_fingerprint=proposal_fingerprint,
            reason_category=reason_category,
            decision="deferred",
            command_type="DeferReconciliationProposal",
            actor_kind=actor_kind,
            actor_id=actor_id,
        )

    def _decide(
        self,
        *,
        command_id: str,
        proposal_id: str,
        proposal_revision: int,
        proposal_fingerprint: str,
        reason_category: str,
        decision: str,
        command_type: str,
        actor_kind: str,
        actor_id: str | None,
    ) -> ProposalDecisionResult:
        if type(proposal_revision) is not int or proposal_revision <= 0:
            raise ValidationError("proposal_revision must be a positive integer")
        fingerprint = _validate_fingerprint(proposal_fingerprint)
        reason = _validate_reason(reason_category)
        envelope = CommandEnvelope(
            command_id=command_id,
            command_type=command_type,
            target_type="reconciliation_proposal",
            target_id=proposal_id,
            semantic_payload={
                "decision": decision,
                "proposal_revision": proposal_revision,
                "proposal_fingerprint": fingerprint,
                "reason_category": reason,
            },
            base_revisions={"proposal": proposal_revision},
            authorizing_fingerprints={"proposal": fingerprint},
        )

        def prepare(uow: UnitOfWork) -> PreparedMutation:
            proposal = self._repository.require_pending(uow.connection, proposal_id)
            if proposal.revision != proposal_revision or proposal.proposal_fingerprint != fingerprint:
                raise SomaError("IMPORT_PROPOSAL_STALE", "proposal revision or fingerprint changed")
            run = self._repository.get_run(uow.connection, proposal.import_run_id)
            if run.run_state not in {"staged", "waiting_review", "recovery_required"}:
                raise SomaError("IMPORT_PROPOSAL_STALE", "parent import run no longer permits proposal decisions")
            self._repository.require_current_recovery_authorization(uow.connection, run)

            disposition_id = new_uuid4()
            equivalence_id = new_uuid4()
            audit_event_id = new_uuid4()
            decided_at = utc_epoch_seconds()

            def apply(inner: UnitOfWork) -> AuditEventInput:
                self._repository.transition_decision(
                    inner,
                    proposal=proposal,
                    run=run,
                    decision=decision,
                    decided_at_utc=decided_at,
                    disposition_id=disposition_id,
                    equivalence_id=equivalence_id,
                    reason_category=reason,
                    command_id=command_id,
                )
                return AuditEventInput(
                    audit_event_id=audit_event_id,
                    action_type="ticket_import.proposal_decided",
                    action_version=1,
                    actor_kind=actor_kind,
                    actor_id=actor_id,
                    target_type="reconciliation_proposal",
                    target_id=proposal_id,
                    reason_category=reason,
                    command_id=command_id,
                    import_run_id=proposal.import_run_id,
                    proposal_id=proposal_id,
                    payload_schema="ImportProposalDecisionAuditV1",
                    payload_version=1,
                    payload={
                        "proposal_id": proposal_id,
                        "proposal_kind": proposal.proposal_kind,
                        "decision": decision,
                        "proposal_revision": proposal_revision,
                        "reason_category": reason,
                        "owner_result_refs": [],
                    },
                    resulting_event_refs=(
                        AuditResultRef("proposal_disposition", disposition_id),
                        AuditResultRef("proposal_equivalence_decision", equivalence_id),
                    ),
                )

            return PreparedMutation(
                False,
                "reconciliation_proposal",
                proposal_id,
                apply,
                response_schema="ProposalDecisionResultV1",
                response_factory=lambda inner: self._decision_response(
                    inner,
                    proposal_id=proposal_id,
                    command_id=command_id,
                ),
            )

        return self._result_from_execution(self._boundary.execute(envelope, prepare))