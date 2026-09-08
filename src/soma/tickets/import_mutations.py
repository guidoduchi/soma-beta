from __future__ import annotations

import hmac
from dataclasses import dataclass
from typing import Any

from soma.foundation.audit.writer import AuditEventInput, AuditResultRef
from soma.foundation.errors import SomaError
from soma.foundation.identifiers import new_uuid4, utc_epoch_seconds
from soma.foundation.persistence.uow import UnitOfWork
from soma.foundation.strict_json import sha256_canonical_json

from .sr_references import current_reference_token
from .sr_source_projection import (
    AcceptedSrFieldDeltaSet,
    SrSourceEvidenceProvider,
    SrSourceProjectionApplyResult,
    SrSourceProjectionService,
)
from .validation import validate_official_sr_no


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


class ServiceRequestImportMutationService:
    """LLD-03 owner boundary used by LLD-04's already-open UnitOfWork."""

    def __init__(self, evidence_provider: SrSourceEvidenceProvider) -> None:
        self._projection_service = SrSourceProjectionService(evidence_provider)

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
