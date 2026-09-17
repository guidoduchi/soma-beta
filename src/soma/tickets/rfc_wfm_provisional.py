from __future__ import annotations

import hmac
from dataclasses import dataclass
from typing import Any

from soma.foundation.audit.writer import AuditEventInput
from soma.foundation.errors import SomaError
from soma.foundation.strict_json import sha256_canonical_json

from .rfc_source_projection import (
    RfcAcceptedFieldDelta,
    RfcSourceEvidenceProvider,
    RfcSourceProjectionApplyResult,
    RfcSourceProjectionService,
)
from .validation import validate_rfc_no


_TERMINAL_STATUS_CLASSES = frozenset({"terminal_closed", "terminal_cancelled"})


@dataclass(frozen=True, slots=True)
class RfcWfmProvisionalEligibilityMutation:
    rfc_no: str
    source_status_delta: RfcAcceptedFieldDelta
    base_state_token: str
    accepted_command_id: str
    review_fingerprint: str
    actor_kind: str = "local_user"
    actor_id: str | None = None


@dataclass(frozen=True, slots=True)
class RfcWfmProvisionalEligibilityResult:
    rfc_id: str
    projection_result: RfcSourceProjectionApplyResult
    result_refs: tuple[tuple[str, str], ...]
    audit_events: tuple[AuditEventInput, ...]


class RfcWfmProvisionalEligibilityService:
    """LLD-03 owner for reviewed WFM fallback Implement eligibility."""

    def __init__(self, evidence_provider: RfcSourceEvidenceProvider) -> None:
        self._projection = RfcSourceProjectionService(evidence_provider)

    @staticmethod
    def base_state_token(reader: Any, rfc_no: str) -> str:
        canonical = validate_rfc_no(rfc_no)
        rfc = reader.execute(
            "SELECT rfc_id,local_archive_state FROM rfcs WHERE rfc_no=?",
            (canonical,),
        ).fetchone()
        availability = "active_or_missing"
        status_state: dict[str, object] | None = None
        if rfc is not None:
            rfc_id = str(rfc[0])
            archive_state = str(rfc[1])
            if archive_state == "archived":
                availability = "archived"
            elif archive_state != "active":
                raise SomaError("PERSISTENCE_FAILURE", "RFC archive authority is invalid")
            projection = reader.execute(
                "SELECT status_text,status_class,status_authority,status_evidence_id "
                "FROM rfc_current_source_projection WHERE rfc_id=?",
                (rfc_id,),
            ).fetchone()
            if projection is not None and str(projection[1]) != "unknown":
                status_state = {
                    "status_text": None if projection[0] is None else str(projection[0]),
                    "status_class": str(projection[1]),
                    "status_authority": None if projection[2] is None else str(projection[2]),
                    "status_evidence_id": None if projection[3] is None else str(projection[3]),
                }
        return sha256_canonical_json(
            {
                "schema": "RFC_WFM_PROVISIONAL_ELIGIBILITY_BASE_V1",
                "rfc_no": canonical,
                "availability": availability,
                "accepted_status": status_state,
            }
        )

    def accept_provisional_implement_eligibility_from_wfm(
        self,
        uow: Any,
        mutation: RfcWfmProvisionalEligibilityMutation,
    ) -> RfcWfmProvisionalEligibilityResult:
        canonical = validate_rfc_no(mutation.rfc_no)
        current_token = self.base_state_token(uow.connection, canonical)
        if not hmac.compare_digest(current_token, mutation.base_state_token):
            raise SomaError("IMPORT_PROPOSAL_STALE", "WFM provisional RFC eligibility base state changed")

        row = uow.connection.execute(
            "SELECT rfc_id,local_archive_state FROM rfcs WHERE rfc_no=?",
            (canonical,),
        ).fetchone()
        if row is None:
            raise SomaError("IMPORT_PROPOSAL_STALE", "reviewed provisional RFC identity has not been created")
        rfc_id = str(row[0])
        if str(row[1]) != "active":
            raise SomaError("IMPORT_PROPOSAL_STALE", "reviewed provisional RFC is no longer active")

        delta = mutation.source_status_delta
        if (
            delta.field_key != "status"
            or delta.value_kind != "controlled"
            or delta.value != "Implement"
            or delta.status_class != "implement_eligible"
            or delta.status_authority != "wfm_provisional"
        ):
            raise SomaError("IMPORT_PROPOSAL_STALE", "WFM provisional RFC eligibility evidence is invalid")

        current = uow.connection.execute(
            "SELECT status_class,status_authority FROM rfc_current_source_projection WHERE rfc_id=?",
            (rfc_id,),
        ).fetchone()
        if current is not None:
            current_class = str(current[0])
            current_authority = None if current[1] is None else str(current[1])
            if current_authority == "enhanced_rfc":
                raise SomaError(
                    "IMPORT_PROPOSAL_STALE",
                    "accepted Enhanced RFC status has precedence over WFM provisional eligibility",
                )
            if current_class in _TERMINAL_STATUS_CLASSES:
                raise SomaError(
                    "IMPORT_PROPOSAL_STALE",
                    "terminal RFC lifecycle cannot be reversed by WFM provisional eligibility",
                )
            if current_class == "implement_eligible" and current_authority == "wfm_provisional":
                raise SomaError("IMPORT_PROPOSAL_STALE", "RFC is already provisionally Implement eligible")

        projection = self._projection.apply_accepted_field_deltas(
            uow,
            rfc_id=rfc_id,
            accepted_command_id=mutation.accepted_command_id,
            deltas=(delta,),
            review_fingerprint=mutation.review_fingerprint,
            actor_kind=mutation.actor_kind,
            actor_id=mutation.actor_id,
        )
        if projection.no_change:
            raise SomaError("IMPORT_PROPOSAL_STALE", "WFM provisional RFC eligibility no longer changes owner state")
        return RfcWfmProvisionalEligibilityResult(
            rfc_id=rfc_id,
            projection_result=projection,
            result_refs=projection.result_refs,
            audit_events=projection.audit_events,
        )
