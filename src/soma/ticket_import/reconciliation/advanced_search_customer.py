from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from soma.foundation.errors import IntegrityFailure
from soma.foundation.identifiers import require_uuid4
from soma.reference.queries.matching import ReferenceMatcher
from soma.tickets.service_request_import_reader import ServiceRequestImportReader

from .advanced_search import _SourceField, _load_source_observation, _proposal, _scope_status
from .engine import ProposalChangeDraft, ReconciliationProposalDraft


@dataclass(frozen=True, slots=True)
class AdvancedSearchSrCustomerProposalBuildResult:
    canonical_sr_no: str
    service_request_id: str | None
    scope_status: str
    resolution_state: str
    matcher_explanation: str | None
    proposals: tuple[ReconciliationProposalDraft, ...]


def _usable_customer_text(source_fields: tuple[_SourceField, ...], field_key: str) -> _SourceField | None:
    field = next((candidate for candidate in source_fields if candidate.field_key == field_key), None)
    if field is None:
        return None
    if field.field_class != "active" or field.value_kind != "text":
        raise IntegrityFailure("Advanced Search Customer source field disagrees with the active text registry")
    if field.value_state != "usable":
        return None
    if field.normalized_text is None or field.integer_value is not None:
        raise IntegrityFailure("usable Advanced Search Customer source field lacks exact text authority")
    return field


def build_advanced_search_sr_customer_reconciliation_proposals(
    reader: Any,
    *,
    import_run_id: str,
    source_observation_id: str,
    sr_reader: ServiceRequestImportReader | None = None,
) -> AdvancedSearchSrCustomerProposalBuildResult:
    canonical_run_id = require_uuid4(import_run_id)
    canonical_observation_id = require_uuid4(source_observation_id)
    source = _load_source_observation(
        reader,
        import_run_id=canonical_run_id,
        source_observation_id=canonical_observation_id,
    )
    scope_status = _scope_status(reader, source)
    if scope_status in {"conflict", "equivalent_duplicate_suppressed"}:
        return AdvancedSearchSrCustomerProposalBuildResult(
            canonical_sr_no=source.canonical_sr_no,
            service_request_id=None,
            scope_status=scope_status,
            resolution_state="scope_blocked",
            matcher_explanation=None,
            proposals=(),
        )

    authority = ServiceRequestImportReader() if sr_reader is None else sr_reader
    target = authority.get_by_official(reader, source.canonical_sr_no)
    if target is None:
        return AdvancedSearchSrCustomerProposalBuildResult(
            canonical_sr_no=source.canonical_sr_no,
            service_request_id=None,
            scope_status=scope_status,
            resolution_state="service_request_missing",
            matcher_explanation=None,
            proposals=(),
        )
    service_request_id = target.get("service_request_id")
    if not isinstance(service_request_id, str):
        raise IntegrityFailure("Service Request import reader returned invalid Customer proposal target identity")
    canonical_service_request_id = require_uuid4(service_request_id)
    if target.get("official_sr_no") != source.canonical_sr_no:
        raise IntegrityFailure("Service Request import reader returned a mismatched Customer proposal identity")

    account = _usable_customer_text(source.fields, "customer_account_code")
    label = _usable_customer_text(source.fields, "customer_org_label")
    if account is None:
        return AdvancedSearchSrCustomerProposalBuildResult(
            canonical_sr_no=source.canonical_sr_no,
            service_request_id=canonical_service_request_id,
            scope_status=scope_status,
            resolution_state="account_code_unusable",
            matcher_explanation=None,
            proposals=(),
        )

    match = ReferenceMatcher.match_customer_org(
        reader,
        raw_account_code=account.normalized_text,
        raw_name=None if label is None else label.normalized_text,
        limit=2,
    )
    if (
        match.state != "UNIQUE_CANDIDATE"
        or match.candidate_count != 1
        or len(match.candidate_ids) != 1
        or match.explanation != "ACCOUNT_CODE_MATCH"
    ):
        return AdvancedSearchSrCustomerProposalBuildResult(
            canonical_sr_no=source.canonical_sr_no,
            service_request_id=canonical_service_request_id,
            scope_status=scope_status,
            resolution_state=match.state.lower(),
            matcher_explanation=match.explanation,
            proposals=(),
        )

    candidate_customer_org_id = require_uuid4(match.candidate_ids[0])
    reference_context = authority.current_reference_context(reader, canonical_service_request_id)
    current_customer = reference_context.get("customer_org_id")
    if current_customer is not None:
        if not isinstance(current_customer, str):
            raise IntegrityFailure("Service Request import reader returned invalid current Customer identity")
        current_customer = require_uuid4(current_customer)
    if current_customer == candidate_customer_org_id:
        return AdvancedSearchSrCustomerProposalBuildResult(
            canonical_sr_no=source.canonical_sr_no,
            service_request_id=canonical_service_request_id,
            scope_status=scope_status,
            resolution_state="already_current",
            matcher_explanation=match.explanation,
            proposals=(),
        )

    change = ProposalChangeDraft(
        ordinal=0,
        field_key="customer_org_id",
        change_kind="set",
        value_kind="identity",
        before_text=current_customer,
        after_text=candidate_customer_org_id,
        before_integer=None,
        after_integer=None,
        source_observation_field_id=account.source_observation_field_id,
    )
    base_state_token = authority.customer_reconciliation_base_token(
        reader,
        canonical_service_request_id,
        candidate_customer_org_id,
    )
    proposal = _proposal(
        source=source,
        service_request_id=canonical_service_request_id,
        proposal_kind="sr_customer_reconciliation",
        risk_class="high",
        base_state_token=base_state_token,
        changes=(change,),
    )
    return AdvancedSearchSrCustomerProposalBuildResult(
        canonical_sr_no=source.canonical_sr_no,
        service_request_id=canonical_service_request_id,
        scope_status=scope_status,
        resolution_state="unique_candidate",
        matcher_explanation=match.explanation,
        proposals=(proposal,),
    )
