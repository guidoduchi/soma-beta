from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from soma.foundation.errors import IntegrityFailure
from soma.foundation.identifiers import require_uuid4
from soma.tickets.service_request_import_reader import ServiceRequestImportReader

from .advanced_search import _load_source_observation, _proposal, _scope_status
from .engine import ProposalChangeDraft, ReconciliationProposalDraft


@dataclass(frozen=True, slots=True)
class AdvancedSearchSrIdentityProposalBuildResult:
    canonical_sr_no: str
    service_request_id: str | None
    scope_status: str
    proposals: tuple[ReconciliationProposalDraft, ...]


def build_advanced_search_sr_identity_proposals(
    reader: Any,
    *,
    import_run_id: str,
    source_observation_id: str,
    sr_reader: ServiceRequestImportReader | None = None,
) -> AdvancedSearchSrIdentityProposalBuildResult:
    canonical_run_id = require_uuid4(import_run_id)
    canonical_observation_id = require_uuid4(source_observation_id)
    source = _load_source_observation(
        reader,
        import_run_id=canonical_run_id,
        source_observation_id=canonical_observation_id,
    )
    scope_status = _scope_status(reader, source)
    if scope_status in {"conflict", "equivalent_duplicate_suppressed"}:
        return AdvancedSearchSrIdentityProposalBuildResult(
            canonical_sr_no=source.canonical_sr_no,
            service_request_id=None,
            scope_status=scope_status,
            proposals=(),
        )

    authority = ServiceRequestImportReader() if sr_reader is None else sr_reader
    target = authority.get_by_official(reader, source.canonical_sr_no)
    if target is not None:
        service_request_id = target.get("service_request_id")
        if not isinstance(service_request_id, str):
            raise IntegrityFailure("Service Request import reader returned invalid proposal target identity")
        canonical_service_request_id = require_uuid4(service_request_id)
        if target.get("official_sr_no") != source.canonical_sr_no:
            raise IntegrityFailure("Service Request import reader returned a mismatched official identity")
        return AdvancedSearchSrIdentityProposalBuildResult(
            canonical_sr_no=source.canonical_sr_no,
            service_request_id=canonical_service_request_id,
            scope_status=scope_status,
            proposals=(),
        )

    change = ProposalChangeDraft(
        ordinal=0,
        field_key="official_sr_no",
        change_kind="create",
        value_kind="identity",
        before_text=None,
        after_text=source.canonical_sr_no,
        before_integer=None,
        after_integer=None,
        source_observation_field_id=None,
    )
    base_state_token = authority.source_identity_base_token(reader, source.canonical_sr_no)
    proposal = _proposal(
        source=source,
        service_request_id=None,
        proposal_kind="sr_create_or_adopt",
        risk_class="medium",
        base_state_token=base_state_token,
        changes=(change,),
    )
    return AdvancedSearchSrIdentityProposalBuildResult(
        canonical_sr_no=source.canonical_sr_no,
        service_request_id=None,
        scope_status=scope_status,
        proposals=(proposal,),
    )
