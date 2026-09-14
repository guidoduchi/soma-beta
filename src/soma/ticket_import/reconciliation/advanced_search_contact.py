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
class AdvancedSearchSrContactProposalBuildResult:
    canonical_sr_no: str
    service_request_id: str | None
    scope_status: str
    resolution_state: str
    matcher_scope: str | None
    matcher_explanation: str | None
    proposals: tuple[ReconciliationProposalDraft, ...]


def _usable_customer_contact_label(source_fields: tuple[_SourceField, ...]) -> _SourceField | None:
    field = next((candidate for candidate in source_fields if candidate.field_key == "customer_contact_label"), None)
    if field is None:
        return None
    if field.field_class != "active" or field.value_kind != "text":
        raise IntegrityFailure("Advanced Search Customer Contact field disagrees with the active text registry")
    if field.value_state != "usable":
        return None
    if field.normalized_text is None or field.integer_value is not None:
        raise IntegrityFailure("usable Advanced Search Customer Contact field lacks exact text authority")
    return field


def build_advanced_search_sr_contact_reconciliation_proposals(
    reader: Any,
    *,
    import_run_id: str,
    source_observation_id: str,
    sr_reader: ServiceRequestImportReader | None = None,
) -> AdvancedSearchSrContactProposalBuildResult:
    canonical_run_id = require_uuid4(import_run_id)
    canonical_observation_id = require_uuid4(source_observation_id)
    source = _load_source_observation(
        reader,
        import_run_id=canonical_run_id,
        source_observation_id=canonical_observation_id,
    )
    scope_status = _scope_status(reader, source)
    if scope_status in {"conflict", "equivalent_duplicate_suppressed"}:
        return AdvancedSearchSrContactProposalBuildResult(
            canonical_sr_no=source.canonical_sr_no,
            service_request_id=None,
            scope_status=scope_status,
            resolution_state="scope_blocked",
            matcher_scope=None,
            matcher_explanation=None,
            proposals=(),
        )

    authority = ServiceRequestImportReader() if sr_reader is None else sr_reader
    target = authority.get_by_official(reader, source.canonical_sr_no)
    if target is None:
        return AdvancedSearchSrContactProposalBuildResult(
            canonical_sr_no=source.canonical_sr_no,
            service_request_id=None,
            scope_status=scope_status,
            resolution_state="service_request_missing",
            matcher_scope=None,
            matcher_explanation=None,
            proposals=(),
        )
    service_request_id = target.get("service_request_id")
    if not isinstance(service_request_id, str):
        raise IntegrityFailure("Service Request import reader returned invalid Contact proposal target identity")
    canonical_service_request_id = require_uuid4(service_request_id)
    if target.get("official_sr_no") != source.canonical_sr_no:
        raise IntegrityFailure("Service Request import reader returned a mismatched Contact proposal identity")

    label = _usable_customer_contact_label(source.fields)
    if label is None:
        return AdvancedSearchSrContactProposalBuildResult(
            canonical_sr_no=source.canonical_sr_no,
            service_request_id=canonical_service_request_id,
            scope_status=scope_status,
            resolution_state="customer_contact_unusable",
            matcher_scope=None,
            matcher_explanation=None,
            proposals=(),
        )

    reference_context = authority.current_reference_context(reader, canonical_service_request_id)
    current_customer = reference_context.get("customer_org_id")
    if current_customer is not None:
        if not isinstance(current_customer, str):
            raise IntegrityFailure("Service Request import reader returned invalid Contact matcher Customer scope")
        current_customer = require_uuid4(current_customer)
    matcher_scope = "UNBOUND" if current_customer is None else current_customer

    contacts = reference_context.get("contacts")
    if not isinstance(contacts, dict):
        raise IntegrityFailure("Service Request import reader returned invalid Contact relationship context")
    current_relationship = contacts.get("customer_contact")
    prior_contact_id: str | None = None
    if current_relationship is not None:
        if not isinstance(current_relationship, dict):
            raise IntegrityFailure("Service Request import reader returned invalid current Customer Contact relationship")
        raw_prior_contact_id = current_relationship.get("contact_id")
        if not isinstance(raw_prior_contact_id, str):
            raise IntegrityFailure("Service Request import reader returned invalid current Customer Contact identity")
        prior_contact_id = require_uuid4(raw_prior_contact_id)

    match = ReferenceMatcher.match_contact(
        reader,
        scope=matcher_scope,
        raw_name=label.normalized_text,
        limit=2,
    )
    if match.state != "UNIQUE_CANDIDATE" or match.candidate_count != 1 or len(match.candidate_ids) != 1:
        return AdvancedSearchSrContactProposalBuildResult(
            canonical_sr_no=source.canonical_sr_no,
            service_request_id=canonical_service_request_id,
            scope_status=scope_status,
            resolution_state=match.state.lower(),
            matcher_scope=matcher_scope,
            matcher_explanation=match.explanation,
            proposals=(),
        )

    candidate_contact_id = require_uuid4(match.candidate_ids[0])
    if candidate_contact_id == prior_contact_id:
        return AdvancedSearchSrContactProposalBuildResult(
            canonical_sr_no=source.canonical_sr_no,
            service_request_id=canonical_service_request_id,
            scope_status=scope_status,
            resolution_state="already_current",
            matcher_scope=matcher_scope,
            matcher_explanation=match.explanation,
            proposals=(),
        )

    change = ProposalChangeDraft(
        ordinal=0,
        field_key="contact_id",
        change_kind="set",
        value_kind="identity",
        before_text=prior_contact_id,
        after_text=candidate_contact_id,
        before_integer=None,
        after_integer=None,
        source_observation_field_id=label.source_observation_field_id,
    )
    base_state_token = authority.contact_reconciliation_base_token(
        reader,
        canonical_service_request_id,
        "customer_contact",
        candidate_contact_id,
        label.source_observation_field_id,
    )
    proposal = _proposal(
        source=source,
        service_request_id=canonical_service_request_id,
        proposal_kind="sr_contact_reconciliation",
        risk_class="high",
        base_state_token=base_state_token,
        changes=(change,),
    )
    return AdvancedSearchSrContactProposalBuildResult(
        canonical_sr_no=source.canonical_sr_no,
        service_request_id=canonical_service_request_id,
        scope_status=scope_status,
        resolution_state="unique_candidate",
        matcher_scope=matcher_scope,
        matcher_explanation=match.explanation,
        proposals=(proposal,),
    )
