from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from soma.foundation.errors import IntegrityFailure, SomaError
from soma.foundation.identifiers import require_uuid4
from soma.reference.queries.matching import ReferenceMatcher
from soma.ticket_import.parsing.sr_candidates import extract_sr_candidates
from soma.tickets.rfc_import_reader import RfcImportReader
from soma.tickets.service_request_import_reader import ServiceRequestImportReader

from .rfc_source_evidence import TicketImportRfcSourceEvidenceProvider


@dataclass(frozen=True, slots=True)
class ReviewedRfcCustomerCandidate:
    rfc_id: str
    rfc_no: str
    current_customer_org_id: str | None
    customer_org_id: str
    account_code: str
    source_observation_field_id: str


@dataclass(frozen=True, slots=True)
class ReviewedRfcSrLinkCandidate:
    requested_rfc_id: str
    rfc_no: str
    service_request_id: str
    official_sr_no: str
    source_observation_field_id: str


class TicketImportRfcReviewEvidenceProvider:
    """Writer-side revalidation for reviewed Enhanced RFC Customer and SR-link candidates."""

    def __init__(self) -> None:
        self._source = TicketImportRfcSourceEvidenceProvider()
        self._rfc_reader = RfcImportReader()
        self._sr_reader = ServiceRequestImportReader()

    def revalidate_customer_candidate(
        self,
        reader: Any,
        *,
        expected_import_run_id: str,
        expected_source_observation_id: str,
        rfc_id: str,
        rfc_no: str,
        source_observation_field_id: str,
        expected_customer_org_id: str,
    ) -> ReviewedRfcCustomerCandidate:
        canonical_rfc_id = require_uuid4(rfc_id)
        canonical_customer_id = require_uuid4(expected_customer_org_id)
        target = self._rfc_reader.get_by_number(reader, rfc_no)
        if target is None or target.get("rfc_id") != canonical_rfc_id:
            raise SomaError("IMPORT_PROPOSAL_STALE", "RFC Customer target identity changed")
        delta = self._source.build_source_projection_delta(
            reader,
            rfc_id=canonical_rfc_id,
            expected_import_run_id=expected_import_run_id,
            expected_source_observation_id=expected_source_observation_id,
            source_observation_field_id=source_observation_field_id,
            expected_field_key="customer_account_number",
        )
        if delta.value_kind != "text" or not isinstance(delta.value, str):
            raise SomaError("IMPORT_PROPOSAL_STALE", "RFC Customer Account Number evidence changed")
        match = ReferenceMatcher.match_customer_org(
            reader,
            raw_account_code=delta.value,
            raw_name=None,
            limit=2,
        )
        if (
            match.state != "UNIQUE_CANDIDATE"
            or match.candidate_count != 1
            or len(match.candidate_ids) != 1
            or match.candidate_ids[0] != canonical_customer_id
            or match.explanation != "ACCOUNT_CODE_MATCH"
        ):
            raise SomaError("IMPORT_PROPOSAL_STALE", "RFC Customer Account Number no longer resolves uniquely")
        current_customer = target.get("customer_org_id")
        if current_customer is not None:
            if not isinstance(current_customer, str):
                raise IntegrityFailure("RFC Customer identity authority is invalid")
            current_customer = require_uuid4(current_customer)
        return ReviewedRfcCustomerCandidate(
            rfc_id=canonical_rfc_id,
            rfc_no=rfc_no,
            current_customer_org_id=current_customer,
            customer_org_id=canonical_customer_id,
            account_code=delta.value,
            source_observation_field_id=source_observation_field_id,
        )

    def revalidate_sr_link_candidate(
        self,
        reader: Any,
        *,
        expected_import_run_id: str,
        expected_source_observation_id: str,
        requested_rfc_id: str,
        rfc_no: str,
        source_observation_field_id: str,
        service_request_id: str,
    ) -> ReviewedRfcSrLinkCandidate:
        canonical_rfc_id = require_uuid4(requested_rfc_id)
        canonical_sr_id = require_uuid4(service_request_id)
        target = self._rfc_reader.get_by_number(reader, rfc_no)
        if target is None or target.get("rfc_id") != canonical_rfc_id:
            raise SomaError("IMPORT_PROPOSAL_STALE", "RFC/SR link target identity changed")
        delta = self._source.build_source_projection_delta(
            reader,
            rfc_id=canonical_rfc_id,
            expected_import_run_id=expected_import_run_id,
            expected_source_observation_id=expected_source_observation_id,
            source_observation_field_id=source_observation_field_id,
            expected_field_key="summary",
        )
        if delta.value_kind != "text" or not isinstance(delta.value, str):
            raise SomaError("IMPORT_PROPOSAL_STALE", "RFC Summary evidence changed")
        sr_row = reader.execute(
            "SELECT official_sr_no FROM service_requests WHERE service_request_id=?",
            (canonical_sr_id,),
        ).fetchone()
        if sr_row is None or sr_row[0] is None:
            raise SomaError("IMPORT_PROPOSAL_STALE", "candidate Service Request no longer exists")
        official_sr_no = str(sr_row[0])
        exact = self._sr_reader.get_by_official(reader, official_sr_no)
        if exact is None or exact.get("service_request_id") != canonical_sr_id:
            raise SomaError("IMPORT_PROPOSAL_STALE", "candidate Service Request identity changed")
        if official_sr_no not in {candidate.official_sr_no for candidate in extract_sr_candidates(delta.value)}:
            raise SomaError("IMPORT_PROPOSAL_STALE", "RFC Summary no longer contains the reviewed Service Request candidate")
        return ReviewedRfcSrLinkCandidate(
            requested_rfc_id=canonical_rfc_id,
            rfc_no=rfc_no,
            service_request_id=canonical_sr_id,
            official_sr_no=official_sr_no,
            source_observation_field_id=source_observation_field_id,
        )
