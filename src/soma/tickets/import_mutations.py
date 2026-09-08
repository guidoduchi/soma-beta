from __future__ import annotations

import hmac
from dataclasses import dataclass
from typing import Any, Protocol

from soma.foundation.audit.writer import AuditEventInput, AuditResultRef
from soma.foundation.errors import SomaError
from soma.foundation.identifiers import new_uuid4, utc_epoch_seconds
from soma.foundation.persistence.uow import UnitOfWork
from soma.foundation.strict_json import sha256_canonical_json

from .repositories.sr_references import ServiceRequestReferenceRepository, SrCustomerRelationshipRecord
from .sr_references import (
    ServiceRequestCustomerClassificationParticipant,
    build_customer_preview_state,
    current_reference_token,
)
from .sr_source_projection import (
    AcceptedSrFieldDeltaSet,
    SrSourceEvidenceProvider,
    SrSourceProjectionApplyResult,
    SrSourceProjectionService,
)
from .validation import validate_official_sr_no


class AcceptedSrCustomerProposalProvider(Protocol):
    def validate_accepted_relationship_proposal(
        self,
        reader: Any,
        *,
        proposal_id: str,
        service_request_id: str,
        customer_org_id: str,
    ) -> str: ...


@dataclass(frozen=True, slots=True)
class ServiceRequestCreateFromSourceMutation:
    official_sr_no: str
    base_state_token: str
    accepted_command_id: str
    actor_kind: str = "local_user"
    actor_id: str | None = None


@dataclass(frozen=True, slots=True)
class ServiceRequestCreateFromSourceResult:
    service_request_id: str
    result_refs: tuple[tuple[str, str], ...]
    audit_events: tuple[AuditEventInput, ...]


@dataclass(frozen=True, slots=True)
class ServiceRequestSourceProjectionMutation:
    service_request_id: str
    base_state_token: str
    accepted_delta_set: AcceptedSrFieldDeltaSet


@dataclass(frozen=True, slots=True)
class ServiceRequestImportMutationResult:
    result_refs: tuple[tuple[str, str], ...]
    projection_result: SrSourceProjectionApplyResult
    audit_events: tuple[AuditEventInput, ...] = ()


@dataclass(frozen=True, slots=True)
class ServiceRequestCustomerReviewMutation:
    service_request_id: str
    target_customer_org_id: str
    expected_prior_customer_org_id: str | None
    base_state_token: str
    reconciliation_proposal_id: str
    source_observation_id: str
    accepted_command_id: str
    reason_category: str | None
    review_fingerprint: str
    actor_kind: str = "local_user"
    actor_id: str | None = None


@dataclass(frozen=True, slots=True)
class ServiceRequestCustomerReviewResult:
    result_refs: tuple[tuple[str, str], ...]
    audit_events: tuple[AuditEventInput, ...]
    resulting_revision: int


class ServiceRequestImportMutationService:
    """LLD-03 owner boundary used by LLD-04's already-open UnitOfWork."""

    def __init__(
        self,
        evidence_provider: SrSourceEvidenceProvider,
        *,
        customer_proposal_provider: AcceptedSrCustomerProposalProvider | None = None,
        classification_participant: ServiceRequestCustomerClassificationParticipant | None = None,
    ) -> None:
        self._projection_service = SrSourceProjectionService(evidence_provider)
        self._customer_proposal_provider = customer_proposal_provider
        self._classification_participant = classification_participant
        self._reference_repository = ServiceRequestReferenceRepository()

    @staticmethod
    def source_identity_base_token(reader: Any, official_sr_no: str) -> str:
        official = validate_official_sr_no(official_sr_no)
        row = reader.execute(
            "SELECT service_request_id,local_sr_no,revision FROM service_requests WHERE official_sr_no=?",
            (official,),
        ).fetchone()
        target = None
        if row is not None:
            target = {
                "service_request_id": str(row[0]),
                "local_sr_no": None if row[1] is None else str(row[1]),
                "revision": int(row[2]),
            }
        return sha256_canonical_json(
            {
                "schema": "SR_SOURCE_IDENTITY_BASE_V1",
                "official_sr_no": official,
                "target": target,
            }
        )

    def create_or_adopt_from_source(
        self,
        uow: UnitOfWork,
        mutation: ServiceRequestCreateFromSourceMutation,
    ) -> ServiceRequestCreateFromSourceResult:
        official = validate_official_sr_no(mutation.official_sr_no)
        current_token = self.source_identity_base_token(uow.connection, official)
        if not hmac.compare_digest(current_token, mutation.base_state_token):
            raise SomaError("IMPORT_PROPOSAL_STALE", "Service Request identity base state changed")
        existing = uow.connection.execute(
            "SELECT service_request_id FROM service_requests WHERE official_sr_no=?",
            (official,),
        ).fetchone()
        if existing is not None:
            raise SomaError(
                "IMPORT_PROPOSAL_STALE",
                "exact Service Request identity already exists and no domain creation remains",
            )

        service_request_id = new_uuid4()
        audit_event_id = new_uuid4()
        now = utc_epoch_seconds()
        uow.connection.execute(
            "INSERT INTO service_requests("
            "service_request_id,official_sr_no,local_sr_no,revision,created_at_utc,updated_at_utc"
            ") VALUES (?, ?, NULL, 1, ?, ?)",
            (service_request_id, official, now, now),
        )
        owner_audit = AuditEventInput(
            audit_event_id=audit_event_id,
            action_type="ticket.service_request.created",
            action_version=1,
            actor_kind=mutation.actor_kind,
            actor_id=mutation.actor_id,
            target_type="service_request",
            target_id=service_request_id,
            command_id=mutation.accepted_command_id,
            payload_schema="ServiceRequestAuditV1",
            payload_version=1,
            payload={
                "service_request_id": service_request_id,
                "resulting_revision": 1,
                "identity_kind": "official",
                "source_or_creation_class": "accepted_source",
            },
            resulting_event_refs=(AuditResultRef("service_request", service_request_id),),
        )
        refs = (("service_request", service_request_id),)
        return ServiceRequestCreateFromSourceResult(
            service_request_id=service_request_id,
            result_refs=refs,
            audit_events=(owner_audit,),
        )

    @staticmethod
    def source_acceptance_base_token(reader: Any, service_request_id: str) -> str:
        sr = reader.execute(
            "SELECT official_sr_no,revision FROM service_requests WHERE service_request_id=?",
            (service_request_id,),
        ).fetchone()
        if sr is None:
            raise SomaError("NOT_FOUND", "Service Request does not exist")
        projection = reader.execute(
            "SELECT problem_summary_observation_id,report_date_observation_id,customer_contact_observation_id,"
            "customer_severity_observation_id,current_handler_observation_id,status_observation_id,"
            "customer_org_observation_id,customer_account_code_observation_id,suspend_planned_end_observation_id,"
            "suspension_duration_observation_id,last_update_observation_id,revision "
            "FROM sr_current_source_projection WHERE service_request_id=?",
            (service_request_id,),
        ).fetchone()
        projection_token = None
        if projection is not None:
            projection_token = {
                "problem_summary": projection[0],
                "report_date": projection[1],
                "customer_contact": projection[2],
                "customer_severity": projection[3],
                "current_handler": projection[4],
                "status": projection[5],
                "customer_org": projection[6],
                "customer_account_code": projection[7],
                "suspend_planned_end": projection[8],
                "suspension_duration": projection[9],
                "last_update": projection[10],
                "revision": int(projection[11]),
            }
        return sha256_canonical_json(
            {
                "schema": "SR_SOURCE_ACCEPTANCE_BASE_V1",
                "service_request_id": service_request_id,
                "official_sr_no": None if sr[0] is None else str(sr[0]),
                "sr_revision": int(sr[1]),
                "source_projection": projection_token,
                "reference_token": current_reference_token(
                    reader,
                    service_request_id,
                    sr_revision=int(sr[1]),
                ),
            }
        )

    @classmethod
    def customer_reconciliation_base_token(
        cls,
        reader: Any,
        service_request_id: str,
        target_customer_org_id: str,
    ) -> str:
        base = cls.source_acceptance_base_token(reader, service_request_id)
        metadata = reader.execute(
            "SELECT matching_profile_id,customer_reference_generation FROM reference_metadata WHERE singleton_guard=1"
        ).fetchone()
        if metadata is None:
            raise SomaError("IMPORT_PROPOSAL_STALE", "reference matching metadata is unavailable")
        customer = reader.execute(
            "SELECT revision,lifecycle_state FROM customer_organizations WHERE customer_org_id=?",
            (target_customer_org_id,),
        ).fetchone()
        target = None if customer is None else {"revision": int(customer[0]), "lifecycle_state": str(customer[1])}
        return sha256_canonical_json(
            {
                "schema": "SR_CUSTOMER_RECONCILIATION_BASE_V1",
                "service_request_id": service_request_id,
                "source_acceptance_base_token": base,
                "matching_profile_id": str(metadata[0]),
                "customer_reference_generation": int(metadata[1]),
                "target_customer_org_id": target_customer_org_id,
                "target_customer": target,
            }
        )

    def apply_accepted_source_projection(
        self,
        uow: UnitOfWork,
        mutation: ServiceRequestSourceProjectionMutation,
    ) -> ServiceRequestImportMutationResult:
        try:
            current_token = self.source_acceptance_base_token(uow.connection, mutation.service_request_id)
        except SomaError as exc:
            if exc.code == "NOT_FOUND":
                raise SomaError("IMPORT_PROPOSAL_STALE", "Service Request target no longer exists") from exc
            raise
        if not hmac.compare_digest(current_token, mutation.base_state_token):
            raise SomaError("IMPORT_PROPOSAL_STALE", "Service Request source acceptance base token changed")
        projection_result = self._projection_service.apply_accepted_field_deltas(
            uow,
            mutation.service_request_id,
            mutation.accepted_delta_set,
        )
        if projection_result.no_change:
            raise SomaError(
                "IMPORT_PROPOSAL_STALE",
                "accepted source projection proposal no longer represents a material owner mutation",
            )
        refs = tuple(
            ("sr_source_field_observation", observation_id)
            for observation_id in projection_result.inserted_observation_ids
        )
        return ServiceRequestImportMutationResult(
            result_refs=refs,
            projection_result=projection_result,
        )

    @staticmethod
    def _classification_failure() -> SomaError:
        return SomaError(
            "SR_CUSTOMER_CLASSIFICATION_PARTICIPANT_FAILED",
            "LLD-06 could not determinately apply Service Request Customer classification consequences",
        )

    def set_customer_from_review(
        self,
        uow: UnitOfWork,
        mutation: ServiceRequestCustomerReviewMutation,
    ) -> ServiceRequestCustomerReviewResult:
        if self._customer_proposal_provider is None:
            raise SomaError("IMPORT_PROPOSAL_BLOCKED", "Customer reconciliation proposal provider is not configured")
        if self._classification_participant is None:
            raise self._classification_failure()
        try:
            current_base = self.customer_reconciliation_base_token(
                uow.connection,
                mutation.service_request_id,
                mutation.target_customer_org_id,
            )
        except SomaError as exc:
            if exc.code == "NOT_FOUND":
                raise SomaError("IMPORT_PROPOSAL_STALE", "Service Request target no longer exists") from exc
            raise
        if not hmac.compare_digest(current_base, mutation.base_state_token):
            raise SomaError("IMPORT_PROPOSAL_STALE", "Service Request Customer reconciliation base state changed")

        state = build_customer_preview_state(
            uow.connection,
            service_request_id=mutation.service_request_id,
            customer_org_id=mutation.target_customer_org_id,
        )
        if state.target_invalid:
            raise SomaError("IMPORT_PROPOSAL_STALE", "reviewed Customer Organization is missing or archived")
        current_customer = None if state.current_relationship is None else state.current_relationship.customer_org_id
        if current_customer != mutation.expected_prior_customer_org_id:
            raise SomaError("IMPORT_PROPOSAL_STALE", "Service Request current Customer no longer matches proposal before-state")
        if current_customer == mutation.target_customer_org_id:
            raise SomaError("IMPORT_PROPOSAL_STALE", "Customer reconciliation no longer represents a material relationship change")

        validated_source_observation_id = self._customer_proposal_provider.validate_accepted_relationship_proposal(
            uow.connection,
            proposal_id=mutation.reconciliation_proposal_id,
            service_request_id=mutation.service_request_id,
            customer_org_id=mutation.target_customer_org_id,
        )
        if validated_source_observation_id != mutation.source_observation_id:
            raise SomaError("IMPORT_PROPOSAL_STALE", "Customer reconciliation source observation changed")

        prior_relationship_id = None if state.current_relationship is None else state.current_relationship.relationship_id
        new_relationship_id = new_uuid4()
        audit_event_id = new_uuid4()
        now = utc_epoch_seconds()
        if prior_relationship_id is not None:
            self._reference_repository.supersede_customer(
                uow,
                prior_relationship_id,
                closed_at_utc=now,
                command_id=mutation.accepted_command_id,
            )
        self._reference_repository.insert_customer(
            uow,
            SrCustomerRelationshipRecord(
                relationship_id=new_relationship_id,
                service_request_id=mutation.service_request_id,
                customer_org_id=mutation.target_customer_org_id,
                relationship_state="active",
                origin_kind="advanced_search_review",
                reconciliation_proposal_id=mutation.reconciliation_proposal_id,
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
            raise SomaError("IMPORT_PROPOSAL_STALE", "Service Request revision changed during Customer reconciliation")

        command_context: dict[str, object] = {
            "command_id": mutation.accepted_command_id,
            "actor_kind": mutation.actor_kind,
            "actor_id": mutation.actor_id,
            "reason_category": mutation.reason_category,
            "review_fingerprint": mutation.review_fingerprint,
            "base_revision": base_revision,
            "resulting_revision": base_revision + 1,
            "reconciliation_proposal_id": mutation.reconciliation_proposal_id,
        }
        try:
            participant_result = self._classification_participant.apply_customer_change(
                uow,
                mutation.service_request_id,
                mutation.target_customer_org_id,
                command_context,
            )
        except SomaError as exc:
            if exc.code == "SR_CUSTOMER_CLASSIFICATION_PARTICIPANT_FAILED":
                raise
            raise self._classification_failure() from exc
        except Exception as exc:
            raise self._classification_failure() from exc
        if participant_result == "INDETERMINATE":
            raise self._classification_failure()

        owner_audit = AuditEventInput(
            audit_event_id=audit_event_id,
            action_type="ticket.service_request.customer_changed",
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
                "reference_role": "customer",
                "prior_reference_id": current_customer,
                "new_reference_id": mutation.target_customer_org_id,
                "customer_org_context_id": mutation.target_customer_org_id,
                "source_observation_id": mutation.source_observation_id,
                "resulting_revision": base_revision + 1,
                "reason_category": mutation.reason_category,
                "review_fingerprint": mutation.review_fingerprint,
            },
            resulting_event_refs=(AuditResultRef("service_request_customer_history", new_relationship_id),),
        )
        return ServiceRequestCustomerReviewResult(
            result_refs=(("service_request_customer_history", new_relationship_id),),
            audit_events=(owner_audit,),
            resulting_revision=base_revision + 1,
        )
