from __future__ import annotations

import hmac
from dataclasses import dataclass
from typing import Any, Protocol

from soma.foundation.application.command_boundary import CommandBoundary, CommandEnvelope, PreparedMutation
from soma.foundation.audit.writer import AuditEventInput, AuditResultRef, AuditWriter
from soma.foundation.errors import SomaError, ValidationError
from soma.foundation.identifiers import new_uuid4, utc_epoch_seconds
from soma.foundation.persistence.connections import ConnectionFactory
from soma.foundation.persistence.uow import ReadSnapshot, UnitOfWork
from soma.foundation.strict_json import sha256_canonical_json

from .audit_registry import build_tickets_audit_registry
from .repositories.sr_references import (
    ServiceRequestReferenceRepository,
    SrContactRelationshipRecord,
    SrCustomerRelationshipRecord,
)
from .validation import validate_optional_sha256, validate_reason_category


_REFERENCE_ROLES = ("customer_contact", "current_handler_reference")


class ServiceRequestCustomerClassificationParticipant(Protocol):
    def preview_customer_change(self, reader: Any, sr_id: str, new_customer_org_id: str | None) -> object: ...

    def apply_customer_change(
        self,
        uow: UnitOfWork,
        sr_id: str,
        new_customer_org_id: str | None,
        command_context: dict[str, object],
    ) -> object: ...


@dataclass(frozen=True, slots=True)
class ReferenceChangePreview:
    eligible: bool
    base_revision: int
    review_fingerprint: str
    warnings: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class ServiceRequestReferenceMutationResult:
    service_request_id: str
    reference_role: str
    relationship_id: str | None
    target_reference_id: str | None
    revision: int
    replayed: bool
    no_change: bool


@dataclass(frozen=True, slots=True)
class _ContactPreviewState:
    preview: ReferenceChangePreview
    current_relationship: SrContactRelationshipRecord | None
    current_customer_org_id: str | None
    target_contact_id: str | None
    target_contact_revision: int | None
    target_contact_lifecycle: str | None
    target_affiliation_id: str | None
    target_affiliation_customer_org_id: str | None
    supporting_source_observation_id: str | None
    target_invalid: bool
    handler_stale: bool
    affiliation_mismatch: bool


@dataclass(frozen=True, slots=True)
class _CustomerPreviewState:
    preview: ReferenceChangePreview
    current_relationship: SrCustomerRelationshipRecord | None
    target_customer_org_id: str | None
    target_customer_revision: int | None
    target_customer_lifecycle: str | None
    target_invalid: bool


def _validate_reference_role(reference_role: str) -> str:
    if reference_role not in _REFERENCE_ROLES:
        raise ValidationError("reference_role must be customer_contact or current_handler_reference")
    return reference_role


def _require_sr_revision(connection: Any, service_request_id: str) -> int:
    row = connection.execute(
        "SELECT revision FROM service_requests WHERE service_request_id=?",
        (service_request_id,),
    ).fetchone()
    if row is None:
        raise SomaError("NOT_FOUND", "Service Request does not exist")
    return int(row[0])


def _customer_master_state(connection: Any, customer_org_id: str | None) -> tuple[int | None, str | None, bool]:
    if customer_org_id is None:
        return None, None, False
    row = connection.execute(
        "SELECT revision,lifecycle_state FROM customer_organizations WHERE customer_org_id=?",
        (customer_org_id,),
    ).fetchone()
    if row is None:
        return None, None, True
    revision = int(row[0])
    lifecycle = str(row[1])
    return revision, lifecycle, lifecycle != "active"


def _contact_master_state(connection: Any, contact_id: str | None) -> tuple[int | None, str | None, bool]:
    if contact_id is None:
        return None, None, False
    row = connection.execute(
        "SELECT revision,lifecycle_state FROM contacts WHERE contact_id=?",
        (contact_id,),
    ).fetchone()
    if row is None:
        return None, None, True
    revision = int(row[0])
    lifecycle = str(row[1])
    return revision, lifecycle, lifecycle != "active"


def _current_affiliation(connection: Any, contact_id: str | None) -> tuple[str | None, str | None]:
    if contact_id is None:
        return None, None
    row = connection.execute(
        "SELECT contact_affiliation_id,customer_org_id FROM contact_affiliations "
        "WHERE contact_id=? AND is_current=1",
        (contact_id,),
    ).fetchone()
    if row is None:
        return None, None
    return str(row[0]), str(row[1])


def _current_handler_pointer(connection: Any, service_request_id: str) -> str | None:
    row = connection.execute(
        "SELECT current_handler_observation_id FROM sr_current_source_projection WHERE service_request_id=?",
        (service_request_id,),
    ).fetchone()
    return None if row is None or row[0] is None else str(row[0])


def _supporting_observation_valid(
    connection: Any,
    *,
    service_request_id: str,
    observation_id: str,
    expected_field_key: str,
    require_usable: bool,
) -> bool:
    row = connection.execute(
        "SELECT field_key,value_state FROM sr_source_field_observations "
        "WHERE sr_source_field_observation_id=? AND service_request_id=?",
        (observation_id, service_request_id),
    ).fetchone()
    if row is None or str(row[0]) != expected_field_key:
        return False
    return not require_usable or str(row[1]) == "usable"


def current_reference_token(connection: Any, service_request_id: str, *, sr_revision: int | None = None) -> str:
    revision = _require_sr_revision(connection, service_request_id) if sr_revision is None else sr_revision
    repository = ServiceRequestReferenceRepository()
    customer = repository.current_customer(connection, service_request_id)
    customer_token: dict[str, object] | None = None
    if customer is not None:
        customer_revision, customer_lifecycle, _ = _customer_master_state(connection, customer.customer_org_id)
        customer_token = {
            "relationship_id": customer.relationship_id,
            "customer_org_id": customer.customer_org_id,
            "target_revision": customer_revision,
            "target_lifecycle": customer_lifecycle,
        }

    contacts: dict[str, object | None] = {}
    for role in _REFERENCE_ROLES:
        relationship = repository.current_contact(connection, service_request_id, role)
        if relationship is None:
            contacts[role] = None
            continue
        contact_revision, contact_lifecycle, _ = _contact_master_state(connection, relationship.contact_id)
        affiliation_id, affiliation_customer = _current_affiliation(connection, relationship.contact_id)
        contacts[role] = {
            "relationship_id": relationship.relationship_id,
            "contact_id": relationship.contact_id,
            "customer_org_context_id": relationship.customer_org_context_id,
            "target_revision": contact_revision,
            "target_lifecycle": contact_lifecycle,
            "current_affiliation_id": affiliation_id,
            "current_affiliation_customer_org_id": affiliation_customer,
            "supporting_source_observation_id": relationship.supporting_source_observation_id,
        }

    return sha256_canonical_json(
        {
            "schema": "SR_REFERENCE_TOKEN_V1",
            "service_request_id": service_request_id,
            "sr_revision": revision,
            "customer": customer_token,
            "contacts": contacts,
            "current_handler_observation_id": _current_handler_pointer(connection, service_request_id),
        }
    )


def build_customer_preview_state(
    connection: Any,
    *,
    service_request_id: str,
    customer_org_id: str | None,
) -> _CustomerPreviewState:
    revision = _require_sr_revision(connection, service_request_id)
    repository = ServiceRequestReferenceRepository()
    current = repository.current_customer(connection, service_request_id)
    target_revision, target_lifecycle, target_invalid = _customer_master_state(connection, customer_org_id)
    warnings: list[str] = []
    if target_invalid:
        warnings.append("SR_REFERENCE_TARGET_INVALID")

    for role in _REFERENCE_ROLES:
        relationship = repository.current_contact(connection, service_request_id, role)
        if relationship is None or customer_org_id is None:
            continue
        _affiliation_id, affiliation_customer = _current_affiliation(connection, relationship.contact_id)
        if affiliation_customer is not None and affiliation_customer != customer_org_id:
            warnings.append("SR_CONTACT_AFFILIATION_REVIEW_REQUIRED")

    token = current_reference_token(connection, service_request_id, sr_revision=revision)
    fingerprint = sha256_canonical_json(
        {
            "schema": "SR_CUSTOMER_CHANGE_REVIEW_V1",
            "service_request_id": service_request_id,
            "base_revision": revision,
            "reference_token": token,
            "current_relationship_id": None if current is None else current.relationship_id,
            "current_customer_org_id": None if current is None else current.customer_org_id,
            "target_customer_org_id": customer_org_id,
            "target_customer_revision": target_revision,
            "target_customer_lifecycle": target_lifecycle,
        }
    )
    return _CustomerPreviewState(
        preview=ReferenceChangePreview(
            eligible=not target_invalid,
            base_revision=revision,
            review_fingerprint=fingerprint,
            warnings=tuple(sorted(set(warnings))),
        ),
        current_relationship=current,
        target_customer_org_id=customer_org_id,
        target_customer_revision=target_revision,
        target_customer_lifecycle=target_lifecycle,
        target_invalid=target_invalid,
    )


def build_contact_preview_state(
    connection: Any,
    *,
    service_request_id: str,
    reference_role: str,
    contact_id: str | None,
    supporting_source_observation_id: str | None,
) -> _ContactPreviewState:
    role = _validate_reference_role(reference_role)
    revision = _require_sr_revision(connection, service_request_id)
    repository = ServiceRequestReferenceRepository()
    current = repository.current_contact(connection, service_request_id, role)
    customer_relationship = repository.current_customer(connection, service_request_id)
    current_customer = None if customer_relationship is None else customer_relationship.customer_org_id
    contact_revision, contact_lifecycle, target_invalid = _contact_master_state(connection, contact_id)
    affiliation_id, affiliation_customer = _current_affiliation(connection, contact_id)
    handler_stale = False

    if contact_id is None and supporting_source_observation_id is not None:
        target_invalid = True
    elif contact_id is not None and role == "current_handler_reference":
        current_pointer = _current_handler_pointer(connection, service_request_id)
        handler_stale = (
            supporting_source_observation_id is None
            or supporting_source_observation_id != current_pointer
            or not _supporting_observation_valid(
                connection,
                service_request_id=service_request_id,
                observation_id=supporting_source_observation_id,
                expected_field_key="current_handler_label",
                require_usable=True,
            )
        )
    elif contact_id is not None and supporting_source_observation_id is not None:
        target_invalid = target_invalid or not _supporting_observation_valid(
            connection,
            service_request_id=service_request_id,
            observation_id=supporting_source_observation_id,
            expected_field_key="customer_contact_label",
            require_usable=False,
        )

    affiliation_mismatch = (
        contact_id is not None
        and current_customer is not None
        and affiliation_customer is not None
        and affiliation_customer != current_customer
    )
    warnings: list[str] = []
    if target_invalid:
        warnings.append("SR_REFERENCE_TARGET_INVALID")
    if handler_stale:
        warnings.append("SR_HANDLER_REFERENCE_STALE")
    if affiliation_mismatch:
        warnings.append("SR_CONTACT_AFFILIATION_REVIEW_REQUIRED")

    token = current_reference_token(connection, service_request_id, sr_revision=revision)
    fingerprint = sha256_canonical_json(
        {
            "schema": "SR_CONTACT_REFERENCE_REVIEW_V1",
            "service_request_id": service_request_id,
            "reference_role": role,
            "base_revision": revision,
            "reference_token": token,
            "current_relationship_id": None if current is None else current.relationship_id,
            "current_contact_id": None if current is None else current.contact_id,
            "current_customer_org_context_id": None if current is None else current.customer_org_context_id,
            "current_supporting_source_observation_id": None if current is None else current.supporting_source_observation_id,
            "current_sr_customer_org_id": current_customer,
            "target_contact_id": contact_id,
            "target_contact_revision": contact_revision,
            "target_contact_lifecycle": contact_lifecycle,
            "target_affiliation_id": affiliation_id,
            "target_affiliation_customer_org_id": affiliation_customer,
            "supporting_source_observation_id": supporting_source_observation_id,
            "current_handler_observation_id": _current_handler_pointer(connection, service_request_id),
        }
    )
    return _ContactPreviewState(
        preview=ReferenceChangePreview(
            eligible=not target_invalid and not handler_stale and not affiliation_mismatch,
            base_revision=revision,
            review_fingerprint=fingerprint,
            warnings=tuple(sorted(set(warnings))),
        ),
        current_relationship=current,
        current_customer_org_id=current_customer,
        target_contact_id=contact_id,
        target_contact_revision=contact_revision,
        target_contact_lifecycle=contact_lifecycle,
        target_affiliation_id=affiliation_id,
        target_affiliation_customer_org_id=affiliation_customer,
        supporting_source_observation_id=supporting_source_observation_id,
        target_invalid=target_invalid,
        handler_stale=handler_stale,
        affiliation_mismatch=affiliation_mismatch,
    )


class ServiceRequestReferenceService:
    """Authoritative LLD-03 canonical Customer/Contact relationship mutations for Service Requests."""

    def __init__(
        self,
        connection_factory: ConnectionFactory,
        classification_participant: ServiceRequestCustomerClassificationParticipant,
    ) -> None:
        self._factory = connection_factory
        self._classification_participant = classification_participant
        self._repository = ServiceRequestReferenceRepository()
        self._boundary = CommandBoundary(
            connection_factory,
            AuditWriter(build_tickets_audit_registry()),
        )

    def _result(
        self,
        *,
        command_id: str,
        service_request_id: str,
        reference_role: str,
        fallback_relationship_id: str | None,
        replayed: bool,
        no_change: bool,
    ) -> ServiceRequestReferenceMutationResult:
        with ReadSnapshot(self._factory) as snapshot:
            revision = _require_sr_revision(snapshot.connection, service_request_id)
            if reference_role == "customer":
                current = self._repository.current_customer(snapshot.connection, service_request_id)
                relationship_id = None if current is None else current.relationship_id
                target_id = None if current is None else current.customer_org_id
            else:
                current_contact = self._repository.current_contact(snapshot.connection, service_request_id, reference_role)
                relationship_id = None if current_contact is None else current_contact.relationship_id
                target_id = None if current_contact is None else current_contact.contact_id
            if relationship_id is None:
                relationship_id = fallback_relationship_id
        return ServiceRequestReferenceMutationResult(
            service_request_id=service_request_id,
            reference_role=reference_role,
            relationship_id=relationship_id,
            target_reference_id=target_id,
            revision=revision,
            replayed=replayed,
            no_change=no_change,
        )

    @staticmethod
    def _participant_failure(exc: BaseException | None = None) -> SomaError:
        error = SomaError(
            "SR_CUSTOMER_CLASSIFICATION_PARTICIPANT_FAILED",
            "LLD-06 could not determinately apply Service Request Customer classification consequences",
        )
        if exc is not None:
            error.__cause__ = exc
        return error

    def set_customer(
        self,
        *,
        command_id: str,
        service_request_id: str,
        base_revision: int,
        customer_org_id: str | None,
        reason_category: str,
        review_fingerprint: str | None = None,
        actor_kind: str = "local_user",
        actor_id: str | None = None,
    ) -> ServiceRequestReferenceMutationResult:
        reason = validate_reason_category(reason_category)
        fingerprint = validate_optional_sha256(review_fingerprint, field="review_fingerprint")
        envelope = CommandEnvelope(
            command_id=command_id,
            command_type="SetServiceRequestCustomer",
            target_type="service_request",
            target_id=service_request_id,
            semantic_payload={
                "customer_org_id": customer_org_id,
                "reason_category": reason,
                "review_fingerprint": fingerprint,
            },
            base_revisions={"service_request": base_revision},
            authorizing_fingerprints={} if fingerprint is None else {"review": fingerprint},
        )

        def prepare(uow: UnitOfWork) -> PreparedMutation:
            state = build_customer_preview_state(
                uow.connection,
                service_request_id=service_request_id,
                customer_org_id=customer_org_id,
            )
            if state.preview.base_revision != base_revision:
                raise SomaError("SR_REFERENCE_STALE", "Service Request revision changed")
            current_customer = None if state.current_relationship is None else state.current_relationship.customer_org_id
            if current_customer == customer_org_id:
                return PreparedMutation(True, None, None)
            if state.target_invalid:
                raise SomaError("SR_REFERENCE_TARGET_INVALID", "Customer Organization is missing or archived")
            if fingerprint is not None and not hmac.compare_digest(fingerprint, state.preview.review_fingerprint):
                raise SomaError("SR_REFERENCE_STALE", "Service Request Customer review context changed")

            prior_relationship_id = None if state.current_relationship is None else state.current_relationship.relationship_id
            new_relationship_id = new_uuid4() if customer_org_id is not None else None
            result_relationship_id = new_relationship_id or prior_relationship_id
            if result_relationship_id is None:
                raise SomaError("PERSISTENCE_FAILURE", "material Customer change has no relationship history identity")
            audit_event_id = new_uuid4()
            now = utc_epoch_seconds()

            def apply(inner: UnitOfWork) -> AuditEventInput:
                if prior_relationship_id is not None:
                    self._repository.supersede_customer(
                        inner,
                        prior_relationship_id,
                        closed_at_utc=now,
                        command_id=command_id,
                    )
                if new_relationship_id is not None and customer_org_id is not None:
                    self._repository.insert_customer(
                        inner,
                        SrCustomerRelationshipRecord(
                            relationship_id=new_relationship_id,
                            service_request_id=service_request_id,
                            customer_org_id=customer_org_id,
                            relationship_state="active",
                            origin_kind="manual_review",
                            reconciliation_proposal_id=None,
                            opened_at_utc=now,
                            closed_at_utc=None,
                            opened_command_id=command_id,
                            closed_command_id=None,
                            reason_category=reason,
                        ),
                    )
                updated = inner.connection.execute(
                    "UPDATE service_requests SET revision=revision+1,updated_at_utc=? "
                    "WHERE service_request_id=? AND revision=?",
                    (now, service_request_id, base_revision),
                )
                if updated.rowcount != 1:
                    raise SomaError("SR_REFERENCE_STALE", "Service Request revision changed")

                command_context: dict[str, object] = {
                    "command_id": command_id,
                    "actor_kind": actor_kind,
                    "actor_id": actor_id,
                    "reason_category": reason,
                    "review_fingerprint": fingerprint,
                    "base_revision": base_revision,
                    "resulting_revision": base_revision + 1,
                }
                try:
                    participant_result = self._classification_participant.apply_customer_change(
                        inner,
                        service_request_id,
                        customer_org_id,
                        command_context,
                    )
                except SomaError as exc:
                    if exc.code == "SR_CUSTOMER_CLASSIFICATION_PARTICIPANT_FAILED":
                        raise
                    raise self._participant_failure(exc) from exc
                except Exception as exc:
                    raise self._participant_failure(exc) from exc
                if participant_result == "INDETERMINATE":
                    raise self._participant_failure()

                return AuditEventInput(
                    audit_event_id=audit_event_id,
                    action_type="ticket.service_request.customer_changed",
                    action_version=1,
                    actor_kind=actor_kind,
                    actor_id=actor_id,
                    target_type="service_request",
                    target_id=service_request_id,
                    reason_category=reason,
                    command_id=command_id,
                    payload_schema="ServiceRequestReferenceAuditV1",
                    payload_version=1,
                    payload={
                        "service_request_id": service_request_id,
                        "reference_role": "customer",
                        "prior_reference_id": current_customer,
                        "new_reference_id": customer_org_id,
                        "customer_org_context_id": customer_org_id,
                        "source_observation_id": None,
                        "resulting_revision": base_revision + 1,
                        "reason_category": reason,
                        "review_fingerprint": fingerprint,
                    },
                    resulting_event_refs=(
                        AuditResultRef("service_request_customer_history", result_relationship_id),
                    ),
                )

            return PreparedMutation(
                False,
                "service_request_customer_history",
                result_relationship_id,
                apply,
            )

        result = self._boundary.execute(envelope, prepare)
        return self._result(
            command_id=command_id,
            service_request_id=service_request_id,
            reference_role="customer",
            fallback_relationship_id=result.result_id,
            replayed=result.replayed,
            no_change=result.no_change,
        )

    def set_contact_reference(
        self,
        *,
        command_id: str,
        service_request_id: str,
        base_revision: int,
        reference_role: str,
        contact_id: str | None,
        supporting_sr_source_field_observation_id: str | None,
        reason_category: str,
        review_fingerprint: str | None = None,
        actor_kind: str = "local_user",
        actor_id: str | None = None,
    ) -> ServiceRequestReferenceMutationResult:
        role = _validate_reference_role(reference_role)
        reason = validate_reason_category(reason_category)
        fingerprint = validate_optional_sha256(review_fingerprint, field="review_fingerprint")
        envelope = CommandEnvelope(
            command_id=command_id,
            command_type="SetServiceRequestContactReference",
            target_type="service_request",
            target_id=service_request_id,
            semantic_payload={
                "reference_role": role,
                "contact_id": contact_id,
                "supporting_sr_source_field_observation_id": supporting_sr_source_field_observation_id,
                "reason_category": reason,
                "review_fingerprint": fingerprint,
            },
            base_revisions={"service_request": base_revision},
            authorizing_fingerprints={} if fingerprint is None else {"review": fingerprint},
        )

        def prepare(uow: UnitOfWork) -> PreparedMutation:
            state = build_contact_preview_state(
                uow.connection,
                service_request_id=service_request_id,
                reference_role=role,
                contact_id=contact_id,
                supporting_source_observation_id=supporting_sr_source_field_observation_id,
            )
            if state.preview.base_revision != base_revision:
                raise SomaError("SR_REFERENCE_STALE", "Service Request revision changed")
            current = state.current_relationship
            if (
                (current is None and contact_id is None)
                or (
                    current is not None
                    and current.contact_id == contact_id
                    and current.customer_org_context_id == state.current_customer_org_id
                    and current.supporting_source_observation_id == supporting_sr_source_field_observation_id
                )
            ):
                return PreparedMutation(True, None, None)
            if state.handler_stale:
                raise SomaError(
                    "SR_HANDLER_REFERENCE_STALE",
                    "Current Handler Contact resolution no longer binds the exact current accepted handler observation",
                )
            if state.target_invalid:
                raise SomaError("SR_REFERENCE_TARGET_INVALID", "Contact or supporting source observation is not eligible")
            if fingerprint is not None and not hmac.compare_digest(fingerprint, state.preview.review_fingerprint):
                raise SomaError("SR_REFERENCE_STALE", "Service Request Contact review context changed")
            if state.affiliation_mismatch and fingerprint is None:
                raise SomaError(
                    "SR_CONTACT_AFFILIATION_REVIEW_REQUIRED",
                    "Contact current affiliation differs from the Service Request Customer context",
                )

            prior_relationship_id = None if current is None else current.relationship_id
            prior_contact_id = None if current is None else current.contact_id
            new_relationship_id = new_uuid4() if contact_id is not None else None
            result_relationship_id = new_relationship_id or prior_relationship_id
            if result_relationship_id is None:
                raise SomaError("PERSISTENCE_FAILURE", "material Contact change has no relationship history identity")
            audit_event_id = new_uuid4()
            now = utc_epoch_seconds()

            def apply(inner: UnitOfWork) -> AuditEventInput:
                if prior_relationship_id is not None:
                    self._repository.supersede_contact(
                        inner,
                        prior_relationship_id,
                        closed_at_utc=now,
                        command_id=command_id,
                    )
                if new_relationship_id is not None and contact_id is not None:
                    self._repository.insert_contact(
                        inner,
                        SrContactRelationshipRecord(
                            relationship_id=new_relationship_id,
                            service_request_id=service_request_id,
                            reference_role=role,
                            contact_id=contact_id,
                            customer_org_context_id=state.current_customer_org_id,
                            relationship_state="active",
                            origin_kind="manual_review",
                            reconciliation_proposal_id=None,
                            supporting_source_observation_id=supporting_sr_source_field_observation_id,
                            opened_at_utc=now,
                            closed_at_utc=None,
                            opened_command_id=command_id,
                            closed_command_id=None,
                            reason_category=reason,
                        ),
                    )
                updated = inner.connection.execute(
                    "UPDATE service_requests SET revision=revision+1,updated_at_utc=? "
                    "WHERE service_request_id=? AND revision=?",
                    (now, service_request_id, base_revision),
                )
                if updated.rowcount != 1:
                    raise SomaError("SR_REFERENCE_STALE", "Service Request revision changed")
                return AuditEventInput(
                    audit_event_id=audit_event_id,
                    action_type="ticket.service_request.contact_reference_changed",
                    action_version=1,
                    actor_kind=actor_kind,
                    actor_id=actor_id,
                    target_type="service_request",
                    target_id=service_request_id,
                    reason_category=reason,
                    command_id=command_id,
                    payload_schema="ServiceRequestReferenceAuditV1",
                    payload_version=1,
                    payload={
                        "service_request_id": service_request_id,
                        "reference_role": role,
                        "prior_reference_id": prior_contact_id,
                        "new_reference_id": contact_id,
                        "customer_org_context_id": state.current_customer_org_id,
                        "source_observation_id": supporting_sr_source_field_observation_id,
                        "resulting_revision": base_revision + 1,
                        "reason_category": reason,
                        "review_fingerprint": fingerprint,
                    },
                    resulting_event_refs=(
                        AuditResultRef("service_request_contact_history", result_relationship_id),
                    ),
                )

            return PreparedMutation(
                False,
                "service_request_contact_history",
                result_relationship_id,
                apply,
            )

        result = self._boundary.execute(envelope, prepare)
        return self._result(
            command_id=command_id,
            service_request_id=service_request_id,
            reference_role=role,
            fallback_relationship_id=result.result_id,
            replayed=result.replayed,
            no_change=result.no_change,
        )
