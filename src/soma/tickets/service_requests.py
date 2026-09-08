from __future__ import annotations

import hashlib
from dataclasses import dataclass
from typing import Any

from soma.foundation.application.command_boundary import (
    CommandBoundary,
    CommandEnvelope,
    PreparedMutation,
)
from soma.foundation.audit.writer import AuditEventInput, AuditResultRef, AuditWriter
from soma.foundation.errors import SomaError, ValidationError
from soma.foundation.identifiers import new_uuid4, utc_epoch_seconds
from soma.foundation.persistence.connections import ConnectionFactory
from soma.foundation.persistence.uow import ReadSnapshot, UnitOfWork

from .audit_registry import build_tickets_audit_registry
from .validation import validate_official_sr_no, validate_review_context_id


@dataclass(frozen=True, slots=True)
class ServiceRequestIdentityResult:
    service_request_id: str
    official_sr_no: str | None
    local_sr_no: str | None
    revision: int
    replayed: bool
    no_change: bool


class ServiceRequestService:
    def __init__(self, connection_factory: ConnectionFactory) -> None:
        self._factory = connection_factory
        self._boundary = CommandBoundary(
            connection_factory,
            AuditWriter(build_tickets_audit_registry()),
        )

    def _result(self, service_request_id: str, *, replayed: bool, no_change: bool) -> ServiceRequestIdentityResult:
        with ReadSnapshot(self._factory) as snapshot:
            row = snapshot.connection.execute(
                "SELECT official_sr_no,local_sr_no,revision FROM service_requests WHERE service_request_id=?",
                (service_request_id,),
            ).fetchone()
        if row is None:
            raise SomaError("NOT_FOUND", "Service Request does not exist")
        return ServiceRequestIdentityResult(
            service_request_id=service_request_id,
            official_sr_no=None if row[0] is None else str(row[0]),
            local_sr_no=None if row[1] is None else str(row[1]),
            revision=int(row[2]),
            replayed=replayed,
            no_change=no_change,
        )

    def create_manual_service_request(
        self,
        *,
        command_id: str,
        official_sr_no: str | None = None,
        actor_kind: str = "local_user",
        actor_id: str | None = None,
    ) -> ServiceRequestIdentityResult:
        official = None if official_sr_no is None else validate_official_sr_no(official_sr_no)
        envelope = CommandEnvelope(
            command_id=command_id,
            command_type="CreateManualServiceRequest",
            target_type="service_request",
            target_id=None,
            semantic_payload={"official_sr_no": official, "creation_class": "manual"},
        )

        def prepare(uow: UnitOfWork) -> PreparedMutation:
            if official is not None:
                existing = uow.connection.execute(
                    "SELECT service_request_id FROM service_requests WHERE official_sr_no=?",
                    (official,),
                ).fetchone()
                if existing is not None:
                    raise SomaError(
                        "SR_OFFICIAL_ID_CONFLICT",
                        "official Service Request identity already belongs to another Service Request",
                    )
                local_no = None
            else:
                allocator = uow.connection.execute(
                    "SELECT next_value FROM sr_local_id_allocator WHERE singleton_guard=1"
                ).fetchone()
                if allocator is None:
                    raise SomaError("PERSISTENCE_FAILURE", "Service Request local ID allocator is missing")
                next_value = int(allocator[0])
                if next_value >= 100_000_000:
                    raise SomaError(
                        "SR_LOCAL_ID_EXHAUSTED",
                        "non-reusable local Service Request identity space is exhausted",
                    )
                local_no = f"LSR-{next_value:08d}"

            service_request_id = new_uuid4()
            audit_event_id = new_uuid4()
            now = utc_epoch_seconds()

            def apply(inner: UnitOfWork) -> AuditEventInput:
                if local_no is not None:
                    inner.connection.execute(
                        "UPDATE sr_local_id_allocator SET next_value=next_value+1 WHERE singleton_guard=1"
                    )
                inner.connection.execute(
                    "INSERT INTO service_requests("
                    "service_request_id,official_sr_no,local_sr_no,revision,created_at_utc,updated_at_utc"
                    ") VALUES (?, ?, ?, 1, ?, ?)",
                    (service_request_id, official, local_no, now, now),
                )
                return AuditEventInput(
                    audit_event_id=audit_event_id,
                    action_type="ticket.service_request.created",
                    action_version=1,
                    actor_kind=actor_kind,
                    actor_id=actor_id,
                    target_type="service_request",
                    target_id=service_request_id,
                    command_id=command_id,
                    payload_schema="ServiceRequestAuditV1",
                    payload_version=1,
                    payload={
                        "service_request_id": service_request_id,
                        "resulting_revision": 1,
                        "identity_kind": "official" if official is not None else "local",
                        "source_or_creation_class": "manual",
                    },
                    resulting_event_refs=(AuditResultRef("service_request", service_request_id),),
                )

            return PreparedMutation(False, "service_request", service_request_id, apply)

        result = self._boundary.execute(envelope, prepare)
        assert result.result_id is not None
        return self._result(result.result_id, replayed=result.replayed, no_change=result.no_change)

    def attach_official_identity(
        self,
        *,
        command_id: str,
        service_request_id: str,
        base_revision: int,
        official_sr_no: str,
        review_context_id: str,
        actor_kind: str = "local_user",
        actor_id: str | None = None,
    ) -> ServiceRequestIdentityResult:
        official = validate_official_sr_no(official_sr_no)
        review_context = validate_review_context_id(review_context_id)
        envelope = CommandEnvelope(
            command_id=command_id,
            command_type="AttachOfficialServiceRequestIdentity",
            target_type="service_request",
            target_id=service_request_id,
            semantic_payload={
                "official_sr_no": official,
                "review_context_id": review_context,
            },
            base_revisions={"service_request": base_revision},
        )

        def prepare(uow: UnitOfWork) -> PreparedMutation:
            row = uow.connection.execute(
                "SELECT official_sr_no,local_sr_no,revision FROM service_requests WHERE service_request_id=?",
                (service_request_id,),
            ).fetchone()
            if row is None:
                raise SomaError("NOT_FOUND", "Service Request does not exist")
            if int(row[2]) != base_revision:
                raise SomaError("STALE_REVISION", "Service Request revision changed")
            current_official = None if row[0] is None else str(row[0])
            if current_official == official:
                return PreparedMutation(True, None, None)
            if current_official is not None:
                raise ValidationError("official Service Request identity is immutable once attached")
            conflict = uow.connection.execute(
                "SELECT service_request_id FROM service_requests WHERE official_sr_no=? AND service_request_id<>?",
                (official, service_request_id),
            ).fetchone()
            if conflict is not None:
                raise SomaError(
                    "SR_OFFICIAL_ID_CONFLICT",
                    "official Service Request identity already belongs to another Service Request",
                )
            audit_event_id = new_uuid4()
            now = utc_epoch_seconds()
            fingerprint = hashlib.sha256(official.encode("ascii")).hexdigest()

            def apply(inner: UnitOfWork) -> AuditEventInput:
                inner.connection.execute(
                    "UPDATE service_requests SET official_sr_no=?,revision=revision+1,updated_at_utc=? "
                    "WHERE service_request_id=?",
                    (official, now, service_request_id),
                )
                return AuditEventInput(
                    audit_event_id=audit_event_id,
                    action_type="ticket.service_request.official_identity_attached",
                    action_version=1,
                    actor_kind=actor_kind,
                    actor_id=actor_id,
                    target_type="service_request",
                    target_id=service_request_id,
                    command_id=command_id,
                    payload_schema="ServiceRequestIdentityAuditV1",
                    payload_version=1,
                    payload={
                        "service_request_id": service_request_id,
                        "prior_identity_kind": "local" if row[1] is not None else "unofficial",
                        "official_sr_no_fingerprint": fingerprint,
                        "resulting_revision": base_revision + 1,
                        "review_context_id": review_context,
                    },
                    resulting_event_refs=(AuditResultRef("service_request", service_request_id),),
                )

            return PreparedMutation(False, "service_request", service_request_id, apply)

        result = self._boundary.execute(envelope, prepare)
        return self._result(service_request_id, replayed=result.replayed, no_change=result.no_change)
