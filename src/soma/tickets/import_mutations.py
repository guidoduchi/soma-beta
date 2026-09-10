from __future__ import annotations

import hmac
from dataclasses import dataclass
from typing import Any, Protocol

from soma.foundation.audit.writer import AuditEventInput, AuditResultRef
from soma.foundation.errors import SomaError
from soma.foundation.identifiers import new_uuid4, utc_epoch_seconds
from soma.foundation.persistence.uow import UnitOfWork
from soma.foundation.strict_json import sha256_canonical_json

from .repositories.sr_references import (
    ServiceRequestReferenceRepository,
    SrContactRelationshipRecord,
    SrCustomerRelationshipRecord,
)
from .sr_references import (
    ServiceRequestCustomerClassificationParticipant,
    build_contact_preview_state,
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


class AcceptedSrContactProposalProvider(Protocol):
    def validate_sr_contact_acceptance(
        self,
        reader: Any,
        proposal_id: str,
        sr_id: str,
        reference_role: str,
        target_contact_id: str,
        source_observation_field_id: str,
        command_context: dict[str, object],
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


@dataclass(frozen=True, slots=True)
class ServiceRequestContactReviewMutation:
    service_request_id: str
    reference_role: str
    target_contact_id: str
    expected_prior_contact_id: str | None
    base_state_token: str
    reconciliation_proposal_id: str
    source_observation_id: str
    source_observation_field_id: str
    accepted_command_id: str
    proposal_revision: int
    proposal_fingerprint: str
    reason_category: str | None
    review_fingerprint: str
    actor_kind: str = "local_user"
    actor_id: str | None = None


@dataclass(frozen=True, slots=True)
class ServiceRequestContactReviewResult:
    result_refs: tuple[tuple[str, str], ...]
    audit_events: tuple[AuditEventInput, ...]
    resulting_revision: int


class ServiceRequestImportReader:
    """Small LLD-03 reader used by LLD-04 without exposing private relationship SQL."""

    @staticmethod
    def get_by_official(reader: Any, eight_digit_sr_no: str) -> dict[str, object] | None:
        official = validate_official_sr_no(eight_digit_sr_no)
        row = reader.execute(
            "SELECT service_request_id,official_sr_no,local_sr_no,revision FROM service_requests WHERE official_sr_no=?",
            (official,),
        ).fetchone()
        if row is None:
            return None
        return {
            "service_request_id": str(row[0]),
            "official_sr_no": str(row[1]),
            "local_sr_no": None if row[2] is None else str(row[2]),
            "revision": int(row[3]),
        }

    @staticmethod
    def current_source_projection(reader: Any, service_request_id: str) -> dict[str, object] | None:
        return SrSourceProjectionService.current(reader, service_request_id)

    @staticmethod
    def current_reference_context(reader: Any, service_request_id: str) -> dict[str, object]:
        sr = reader.execute(
            "SELECT revision FROM service_requests WHERE service_request_id=?",
            (service_request_id,),
        ).fetchone()
        if sr is None:
            raise SomaError("NOT_FOUND", "Service Request does not exist")
        repository = ServiceRequestReferenceRepository()
        customer = repository.current_customer(reader, service_request_id)
        contacts: dict[str, object | None] = {}
        for role in ("customer_contact", "current_handler_reference"):
            relationship = repository.current_contact(reader, service_request_id, role)
            contacts[role] = (
                None
                if relationship is None
                else {
                    "relationship_id": relationship.relationship_id,
                    "contact_id": relationship.contact_id,
                    "customer_org_context_id": relationship.customer_org_context_id,
                    "supporting_source_observation_id": relationship.supporting_source_observation_id,
                }
            )
        return {
            "service_request_id": service_request_id,
            "revision": int(sr[0]),
            "customer_org_id": None if customer is None else customer.customer_org_id,
            "customer_relationship_id": None if customer is None else customer.relationship_id,
            "contacts": contacts,
        }

    @staticmethod
    def source_acceptance_base_token(reader: Any, service_request_id: str) -> str:
        return ServiceRequestImportMutationService.source_acceptance_base_token(reader, service_request_id)


class ServiceRequestImportMutationService:
    """LLD-03 owner boundary used by LLD-04's already-open UnitOfWork."""

    def __init__(
        self,
        evidence_provider: SrSourceEvidenceProvider,
        *,
        customer_proposal_provider: AcceptedSrCustomerProposalProvider | None = None,
        contact_proposal_provider: AcceptedSrContactProposalProvider | None = None,
        classification_participant: ServiceRequestCustomerClassificationParticipant | None = None,
    ) -> None:
        self._projection_service = SrSourceProjectionService(evidence_provider)
        self._customer_proposal_provider = customer_proposal_provider
        self._contact_proposal_provider = contact_proposal_provider
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

    @classmethod
    def contact_reconciliation_base_token(
        cls,
        reader: Any,
        service_request_id: str,
        reference_role: str,
        target_contact_id: str,
        source_observation_field_id: str,
    ) -> str:
        if reference_role not in {"customer_contact", "current_handler_reference"}:
            raise SomaError("IMPORT_PROPOSAL_STALE", "SR Contact reconciliation role is invalid")
        base = cls.source_acceptance_base_token(reader, service_request_id)
        metadata = reader.execute(
            "SELECT matching_profile_id FROM reference_metadata WHERE singleton_guard=1"
        ).fetchone()
        if metadata is None:
            raise SomaError("IMPORT_PROPOSAL_STALE", "reference matching metadata is unavailable")
        contact = reader.execute(
            "SELECT revision,lifecycle_state FROM contacts WHERE contact_id=?",
            (target_contact_id,),
        ).fetchone()
        affiliation = reader.execute(
            "SELECT contact_affiliation_id,customer_org_id FROM contact_affiliations "
            "WHERE contact_id=? AND is_current=1",
            (target_contact_id,),
        ).fetchone()
        target = None if contact is None else {"revision": int(contact[0]), "lifecycle_state": str(contact[1])}
        affiliation_token = (
            None
            if affiliation is None
            else {"contact_affiliation_id": str(affiliation[0]), "customer_org_id": str(affiliation[1])}
        )
        return sha256_canonical_json(
            {
                "schema": "SR_CONTACT_RECONCILIATION_BASE_V1",
                "service_request_id": service_request_id,
                "source_acceptance_base_token": base,
                "matching_profile_id": str(metadata[0]),
                "reference_role": reference_role,
                "target_contact_id": target_contact_id,
                "target_contact": target,
                "target_current_affiliation": affiliation_token,
                "source_observation_field_id": source_observation_field_id,
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

    @classmethod
    def _classification_result_refs(cls, participant_result: object) -> tuple[tuple[str, str], ...]:
        if participant_result == "INDETERMINATE":
            raise cls._classification_failure()
        if participant_result is None or participant_result == "NO_CHANGE" or participant_result == ():
            return ()
        if not isinstance(participant_result, tuple):
            raise cls._classification_failure()
        refs: list[tuple[str, str]] = []
        for item in participant_result:
            if not isinstance(item, tuple) or len(item) != 2:
                raise cls._classification_failure()
            result_type, result_id = item
            if result_type != "sr_classification_event" or not isinstance(result_id, str) or not result_id:
                raise cls._classification_failure()
            refs.append((result_type, result_id))
        if len(set(refs)) != len(refs):
            raise cls._classification_failure()
        return tuple(refs)

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
            classification_refs = self._classification_result_refs(participant_result)
        except SomaError as exc:
            if exc.code == "SR_CUSTOMER_CLASSIFICATION_PARTICIPANT_FAILED":
                raise
            raise self._classification_failure() from exc
        except Exception as exc:
            raise self._classification_failure() from exc

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
            result_refs=(("service_request_customer_history", new_relationship_id), *classification_refs),
            audit_events=(owner_audit,),
            resulting_revision=base_revision + 1,
        )

    @staticmethod
    def _supporting_accepted_contact_observation(
        reader: Any,
        *,
        service_request_id: str,
        reference_role: str,
        source_observation_field_id: str,
    ) -> str | None:
        if reference_role == "customer_contact":
            projection_column = "customer_contact_observation_id"
            expected_field_key = "customer_contact_label"
            required = False
        elif reference_role == "current_handler_reference":
            projection_column = "current_handler_observation_id"
            expected_field_key = "current_handler_label"
            required = True
        else:
            raise SomaError("IMPORT_PROPOSAL_STALE", "SR Contact reconciliation role is invalid")
        row = reader.execute(
            f"SELECT o.sr_source_field_observation_id,o.field_key,o.value_state,o.source_observation_field_id "
            f"FROM sr_current_source_projection p JOIN sr_source_field_observations o "
            f"ON o.sr_source_field_observation_id=p.{projection_column} WHERE p.service_request_id=?",
            (service_request_id,),
        ).fetchone()
        if row is None:
            if required:
                raise SomaError(
                    "IMPORT_PROPOSAL_STALE",
                    "Current Handler Contact reconciliation requires current accepted handler source evidence",
                )
            return None
        exact = (
            str(row[1]) == expected_field_key
            and str(row[2]) == "usable"
            and str(row[3]) == source_observation_field_id
        )
        if not exact:
            if required:
                raise SomaError(
                    "IMPORT_PROPOSAL_STALE",
                    "Current Handler Contact reconciliation source pointer changed",
                )
            return None
        return str(row[0])

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
        if current_contact_id != mutation.expected_prior_contact_id:
            raise SomaError("IMPORT_PROPOSAL_STALE", "Service Request Contact no longer matches proposal before-state")
        if current_contact_id == mutation.target_contact_id:
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

    def set_customer_contact_from_review(
        self,
        uow: UnitOfWork,
        mutation: ServiceRequestContactReviewMutation,
    ) -> ServiceRequestContactReviewResult:
        return self._set_contact_from_review(uow, mutation, expected_role="customer_contact")

    def set_current_handler_contact_reference_from_review(
        self,
        uow: UnitOfWork,
        mutation: ServiceRequestContactReviewMutation,
    ) -> ServiceRequestContactReviewResult:
        return self._set_contact_from_review(uow, mutation, expected_role="current_handler_reference")
