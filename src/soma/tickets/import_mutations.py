from __future__ import annotations

import hmac
from dataclasses import dataclass
from typing import Any

from soma.foundation.errors import SomaError
from soma.foundation.persistence.uow import UnitOfWork
from soma.foundation.strict_json import sha256_canonical_json

from .sr_references import current_reference_token
from .sr_source_projection import (
    AcceptedSrFieldDeltaSet,
    SrSourceEvidenceProvider,
    SrSourceProjectionApplyResult,
    SrSourceProjectionService,
)


@dataclass(frozen=True, slots=True)
class ServiceRequestSourceProjectionMutation:
    service_request_id: str
    base_state_token: str
    accepted_delta_set: AcceptedSrFieldDeltaSet


@dataclass(frozen=True, slots=True)
class ServiceRequestImportMutationResult:
    result_refs: tuple[tuple[str, str], ...]
    projection_result: SrSourceProjectionApplyResult


class ServiceRequestImportMutationService:
    """LLD-03 owner boundary used by LLD-04's already-open UnitOfWork."""

    def __init__(self, evidence_provider: SrSourceEvidenceProvider) -> None:
        self._projection_service = SrSourceProjectionService(evidence_provider)

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
