from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from soma.foundation.errors import IntegrityFailure, SomaError
from soma.foundation.identifiers import require_uuid4
from soma.reference.queries.matching import ReferenceMatcher
from soma.ticket_import.parsing.sr_candidates import extract_sr_candidates
from soma.ticket_import.profiles import require_profile_versions
from soma.tickets.rfc_import_reader import RfcImportReader
from soma.tickets.service_request_import_reader import ServiceRequestImportReader

from .rfc_source_evidence import TicketImportRfcSourceEvidenceProvider

_PUBLISHED_RUN_STATES = frozenset(
    {"staged", "waiting_review", "recovery_required", "partially_accepted", "accepted", "rejected"}
)


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

    def _revalidate_wfm_sr_link_candidate(
        self,
        reader: Any,
        *,
        expected_import_run_id: str,
        expected_source_observation_id: str,
        canonical_rfc_id: str,
        rfc_no: str,
        source_observation_field_id: str,
        canonical_sr_id: str,
    ) -> ReviewedRfcSrLinkCandidate:
        versions = require_profile_versions("wfm_service_provider")
        row = reader.execute(
            "SELECT o.canonical_primary_id,o.canonical_parent_rfc_no,o.entity_kind,o.identity_state,"
            "r.source_family,r.source_profile_id,r.header_registry_id,r.vocabulary_registry_id,"
            "r.parser_profile_id,r.run_state "
            "FROM source_observations o JOIN import_runs r ON r.import_run_id=o.import_run_id "
            "WHERE o.import_run_id=? AND o.source_observation_id=?",
            (expected_import_run_id, expected_source_observation_id),
        ).fetchone()
        if (
            row is None
            or row[0] is None
            or row[1] is None
            or str(row[1]) != rfc_no
            or str(row[2]) != "wfm"
            or str(row[3]) != "valid"
            or str(row[4]) != "wfm_service_provider"
            or str(row[5]) != versions.source_profile_id
            or str(row[6]) != versions.header_registry_id
            or str(row[7]) != versions.vocabulary_registry_id
            or str(row[8]) != versions.parser_profile_id
            or str(row[9]) not in _PUBLISHED_RUN_STATES
        ):
            raise SomaError("IMPORT_PROPOSAL_STALE", "WFM Task Name SR-link source evidence changed")

        field = reader.execute(
            "SELECT field_key,field_class,value_state,value_kind,normalized_text,integer_value "
            "FROM source_observation_fields WHERE source_observation_field_id=? AND source_observation_id=?",
            (source_observation_field_id, expected_source_observation_id),
        ).fetchone()
        if (
            field is None
            or str(field[0]) != "task_name"
            or str(field[1]) != "active"
            or str(field[2]) != "usable"
            or str(field[3]) != "text"
            or field[4] is None
            or field[5] is not None
        ):
            raise SomaError("IMPORT_PROPOSAL_STALE", "WFM Task Name SR-link field evidence changed")
        task_name = str(field[4])

        current_projection = self._rfc_reader.current_source_projection(reader, canonical_rfc_id)
        summary = None if current_projection is None else current_projection.get("summary_text")
        if summary is not None:
            if not isinstance(summary, str):
                raise IntegrityFailure("accepted RFC Summary authority is invalid")
            for mention in extract_sr_candidates(summary):
                if self._sr_reader.get_by_official(reader, mention.official_sr_no) is not None:
                    raise SomaError(
                        "IMPORT_PROPOSAL_STALE",
                        "accepted RFC Summary now has precedence over WFM Task Name SR-link fallback",
                    )

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
        if official_sr_no not in {candidate.official_sr_no for candidate in extract_sr_candidates(task_name)}:
            raise SomaError(
                "IMPORT_PROPOSAL_STALE",
                "WFM Task Name no longer contains the reviewed Service Request candidate",
            )
        return ReviewedRfcSrLinkCandidate(
            requested_rfc_id=canonical_rfc_id,
            rfc_no=rfc_no,
            service_request_id=canonical_sr_id,
            official_sr_no=official_sr_no,
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
        family = reader.execute(
            "SELECT r.source_family FROM source_observations o "
            "JOIN import_runs r ON r.import_run_id=o.import_run_id "
            "WHERE o.import_run_id=? AND o.source_observation_id=?",
            (expected_import_run_id, expected_source_observation_id),
        ).fetchone()
        if family is None:
            raise SomaError("IMPORT_PROPOSAL_STALE", "RFC/SR link source observation disappeared")
        if str(family[0]) == "wfm_service_provider":
            return self._revalidate_wfm_sr_link_candidate(
                reader,
                expected_import_run_id=expected_import_run_id,
                expected_source_observation_id=expected_source_observation_id,
                canonical_rfc_id=canonical_rfc_id,
                rfc_no=rfc_no,
                source_observation_field_id=source_observation_field_id,
                canonical_sr_id=canonical_sr_id,
            )
        if str(family[0]) != "rfc_enhanced":
            raise SomaError("IMPORT_PROPOSAL_STALE", "RFC/SR link source family is unsupported")
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
