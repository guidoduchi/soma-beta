from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from soma.foundation.errors import IntegrityFailure, SomaError
from soma.foundation.identifiers import require_uuid4
from soma.ticket_import.reconciliation.wfm_service_provider import _field, _lifecycle_from_source
from soma.tickets.rfc_import_reader import RfcImportReader
from soma.tickets.rfc_wfm_provisional import RfcWfmProvisionalEligibilityService

from .wfm_review_evidence import _load_published_source

_RFC_STATUS_VOCABULARY = "RFC_STATUS_V1"
_TERMINAL_STATUS_CLASSES = frozenset({"terminal_closed", "terminal_cancelled"})


@dataclass(frozen=True, slots=True)
class ReviewedWfmProvisionalEligibilityCandidate:
    rfc_id: str
    rfc_no: str
    source_observation_field_id: str
    before_status_text: str | None
    base_state_token: str


class TicketImportWfmProvisionalEligibilityEvidenceProvider:
    """Writer-side exact revalidation for reviewed WFM fallback RFC eligibility."""

    def __init__(self) -> None:
        self._rfc_reader = RfcImportReader()

    def revalidate(
        self,
        reader: Any,
        *,
        expected_import_run_id: str,
        expected_source_observation_id: str,
        expected_rfc_no: str,
        expected_target_internal_id: str | None,
    ) -> ReviewedWfmProvisionalEligibilityCandidate:
        source = _load_published_source(
            reader,
            expected_import_run_id=expected_import_run_id,
            expected_source_observation_id=expected_source_observation_id,
        )
        if source.canonical_parent_rfc_no != expected_rfc_no:
            raise SomaError("IMPORT_PROPOSAL_STALE", "reviewed WFM provisional RFC identity changed")

        _task_status_token, lifecycle, _task_status_field = _lifecycle_from_source(source)
        if lifecycle != "active":
            raise SomaError("IMPORT_PROPOSAL_STALE", "reviewed WFM is no longer active nonterminal evidence")

        rfc_status = _field(source, "rfc_status")
        if rfc_status is None:
            raise SomaError("IMPORT_PROPOSAL_STALE", "reviewed WFM RFC Status evidence disappeared")
        if (
            rfc_status.field_class != "active"
            or rfc_status.value_state != "usable"
            or rfc_status.value_kind != "controlled"
            or rfc_status.vocabulary_id != _RFC_STATUS_VOCABULARY
            or rfc_status.normalized_text != "Implement"
        ):
            raise SomaError("IMPORT_PROPOSAL_STALE", "reviewed WFM RFC Status no longer proves Implement eligibility")

        target = self._rfc_reader.get_by_number(reader, expected_rfc_no)
        if target is None or not isinstance(target.get("rfc_id"), str):
            raise SomaError("IMPORT_PROPOSAL_STALE", "reviewed provisional RFC identity has not been accepted")
        rfc_id = require_uuid4(str(target["rfc_id"]))
        if target.get("rfc_no") != expected_rfc_no:
            raise IntegrityFailure("RFC import reader returned mismatched provisional RFC identity")
        if expected_target_internal_id is not None and require_uuid4(expected_target_internal_id) != rfc_id:
            raise SomaError("IMPORT_PROPOSAL_STALE", "reviewed provisional RFC target identity changed")

        current = self._rfc_reader.current_source_projection(reader, rfc_id)
        before_status_text: str | None = None
        if current is not None:
            status_class = str(current.get("status_class", "unknown"))
            status_authority = current.get("status_authority")
            if status_authority is not None and not isinstance(status_authority, str):
                raise IntegrityFailure("RFC status authority is invalid")
            if status_authority == "enhanced_rfc":
                raise SomaError("IMPORT_PROPOSAL_STALE", "accepted Enhanced RFC status now has precedence")
            if status_class in _TERMINAL_STATUS_CLASSES:
                raise SomaError("IMPORT_PROPOSAL_STALE", "terminal RFC lifecycle cannot receive provisional eligibility")
            if status_class == "implement_eligible" and status_authority == "wfm_provisional":
                raise SomaError("IMPORT_PROPOSAL_STALE", "RFC is already provisionally Implement eligible")
            value = current.get("status_text")
            if value is not None:
                if not isinstance(value, str):
                    raise IntegrityFailure("RFC status text authority is invalid")
                before_status_text = value

        base = RfcWfmProvisionalEligibilityService.base_state_token(reader, expected_rfc_no)
        return ReviewedWfmProvisionalEligibilityCandidate(
            rfc_id=rfc_id,
            rfc_no=expected_rfc_no,
            source_observation_field_id=rfc_status.source_observation_field_id,
            before_status_text=before_status_text,
            base_state_token=base,
        )
