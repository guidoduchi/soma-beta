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
class AdvancedSearchSrCurrentHandlerProposalBuildResult:
    canonical_sr_no: str
    service_request_id: str | None
    scope_status: str
    resolution_state: str
    matcher_scope: str | None
    matcher_explanation: str | None
    supporting_sr_source_field_observation_id: str | None
    supporting_source_observation_field_id: str | None
    proposals: tuple[ReconciliationProposalDraft, ...]


def _usable_current_run_handler(source_fields: tuple[_SourceField, ...]) -> _SourceField | None:
    field = next((candidate for candidate in source_fields if candidate.field_key == "current_handler_label"), None)
    if field is None:
        return None
    if field.field_class != "active" or field.value_kind != "text":
        raise IntegrityFailure("Advanced Search Current Handler field disagrees with the active text registry")
    if field.value_state != "usable":
        return None
    if field.normalized_text is None or field.integer_value is not None:
        raise IntegrityFailure("usable Advanced Search Current Handler field lacks exact text authority")
    return field


def _result(
    *,
    source,
    service_request_id: str | None,
    scope_status: str,
    resolution_state: str,
    matcher_scope: str | None = None,
    matcher_explanation: str | None = None,
    supporting_owner_observation_id: str | None = None,
    supporting_source_field_id: str | None = None,
    proposals: tuple[ReconciliationProposalDraft, ...] = (),
) -> AdvancedSearchSrCurrentHandlerProposalBuildResult:
    return AdvancedSearchSrCurrentHandlerProposalBuildResult(
        canonical_sr_no=source.canonical_sr_no,
        service_request_id=service_request_id,
        scope_status=scope_status,
        resolution_state=resolution_state,
        matcher_scope=matcher_scope,
        matcher_explanation=matcher_explanation,
        supporting_sr_source_field_observation_id=supporting_owner_observation_id,
        supporting_source_observation_field_id=supporting_source_field_id,
        proposals=proposals,
    )


def build_advanced_search_sr_current_handler_reconciliation_proposals(
    reader: Any,
    *,
    import_run_id: str,
    source_observation_id: str,
    sr_reader: ServiceRequestImportReader | None = None,
) -> AdvancedSearchSrCurrentHandlerProposalBuildResult:
    canonical_run_id = require_uuid4(import_run_id)
    canonical_observation_id = require_uuid4(source_observation_id)
    source = _load_source_observation(
        reader,
        import_run_id=canonical_run_id,
        source_observation_id=canonical_observation_id,
    )
    scope_status = _scope_status(reader, source)
    if scope_status in {"conflict", "equivalent_duplicate_suppressed"}:
        return _result(
            source=source,
            service_request_id=None,
            scope_status=scope_status,
            resolution_state="scope_blocked",
        )

    authority = ServiceRequestImportReader() if sr_reader is None else sr_reader
    target = authority.get_by_official(reader, source.canonical_sr_no)
    if target is None:
        return _result(
            source=source,
            service_request_id=None,
            scope_status=scope_status,
            resolution_state="service_request_missing",
        )
    service_request_id = target.get("service_request_id")
    if not isinstance(service_request_id, str):
        raise IntegrityFailure("Service Request import reader returned invalid Current Handler proposal target identity")
    canonical_service_request_id = require_uuid4(service_request_id)
    if target.get("official_sr_no") != source.canonical_sr_no:
        raise IntegrityFailure("Service Request import reader returned a mismatched Current Handler proposal identity")

    current_run_handler = _usable_current_run_handler(source.fields)
    if current_run_handler is None:
        return _result(
            source=source,
            service_request_id=canonical_service_request_id,
            scope_status=scope_status,
            resolution_state="current_handler_unusable",
        )

    projection = authority.current_source_projection(reader, canonical_service_request_id)
    if projection is None:
        return _result(
            source=source,
            service_request_id=canonical_service_request_id,
            scope_status=scope_status,
            resolution_state="current_handler_not_accepted",
        )
    handler_authority = projection.get("current_handler_authority")
    if handler_authority is None:
        return _result(
            source=source,
            service_request_id=canonical_service_request_id,
            scope_status=scope_status,
            resolution_state="current_handler_not_accepted",
        )
    if not isinstance(handler_authority, dict):
        raise IntegrityFailure("Service Request import reader returned invalid Current Handler authority")
    if handler_authority.get("value_state") != "usable" or handler_authority.get("value_kind") != "text":
        return _result(
            source=source,
            service_request_id=canonical_service_request_id,
            scope_status=scope_status,
            resolution_state="accepted_handler_not_usable",
        )
    accepted_label = handler_authority.get("text_value")
    supporting_owner_observation_id = handler_authority.get("sr_source_field_observation_id")
    supporting_source_field_id = handler_authority.get("source_observation_field_id")
    if not isinstance(accepted_label, str):
        raise IntegrityFailure("accepted Current Handler authority lacks text")
    if not isinstance(supporting_owner_observation_id, str) or not isinstance(supporting_source_field_id, str):
        raise IntegrityFailure("accepted Current Handler authority lacks immutable identities")
    supporting_owner_observation_id = require_uuid4(supporting_owner_observation_id)
    supporting_source_field_id = require_uuid4(supporting_source_field_id)
    if current_run_handler.normalized_text != accepted_label:
        return _result(
            source=source,
            service_request_id=canonical_service_request_id,
            scope_status=scope_status,
            resolution_state="current_run_handler_not_accepted",
            supporting_owner_observation_id=supporting_owner_observation_id,
            supporting_source_field_id=supporting_source_field_id,
        )

    reference_context = authority.current_reference_context(reader, canonical_service_request_id)
    current_customer = reference_context.get("customer_org_id")
    if current_customer is not None:
        if not isinstance(current_customer, str):
            raise IntegrityFailure("Service Request import reader returned invalid Handler matcher Customer scope")
        current_customer = require_uuid4(current_customer)
    matcher_scope = "UNBOUND" if current_customer is None else current_customer

    contacts = reference_context.get("contacts")
    if not isinstance(contacts, dict):
        raise IntegrityFailure("Service Request import reader returned invalid Handler relationship context")
    current_relationship = contacts.get("current_handler_reference")
    prior_contact_id: str | None = None
    prior_supporting_owner_observation_id: str | None = None
    if current_relationship is not None:
        if not isinstance(current_relationship, dict):
            raise IntegrityFailure("Service Request import reader returned invalid current Handler Contact relationship")
        raw_prior_contact = current_relationship.get("contact_id")
        if not isinstance(raw_prior_contact, str):
            raise IntegrityFailure("Service Request import reader returned invalid current Handler Contact identity")
        prior_contact_id = require_uuid4(raw_prior_contact)
        raw_prior_support = current_relationship.get("supporting_source_observation_id")
        if raw_prior_support is not None:
            if not isinstance(raw_prior_support, str):
                raise IntegrityFailure("Service Request import reader returned invalid Handler support identity")
            prior_supporting_owner_observation_id = require_uuid4(raw_prior_support)

    match = ReferenceMatcher.match_contact(
        reader,
        scope=matcher_scope,
        raw_name=current_run_handler.normalized_text,
        limit=2,
    )
    if match.state != "UNIQUE_CANDIDATE" or match.candidate_count != 1 or len(match.candidate_ids) != 1:
        return _result(
            source=source,
            service_request_id=canonical_service_request_id,
            scope_status=scope_status,
            resolution_state=match.state.lower(),
            matcher_scope=matcher_scope,
            matcher_explanation=match.explanation,
            supporting_owner_observation_id=supporting_owner_observation_id,
            supporting_source_field_id=supporting_source_field_id,
        )

    candidate_contact_id = require_uuid4(match.candidate_ids[0])
    if (
        candidate_contact_id == prior_contact_id
        and prior_supporting_owner_observation_id == supporting_owner_observation_id
    ):
        return _result(
            source=source,
            service_request_id=canonical_service_request_id,
            scope_status=scope_status,
            resolution_state="already_current",
            matcher_scope=matcher_scope,
            matcher_explanation=match.explanation,
            supporting_owner_observation_id=supporting_owner_observation_id,
            supporting_source_field_id=supporting_source_field_id,
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
        source_observation_field_id=supporting_source_field_id,
    )
    base_state_token = authority.contact_reconciliation_base_token(
        reader,
        canonical_service_request_id,
        "current_handler_reference",
        candidate_contact_id,
        supporting_source_field_id,
    )
    proposal = _proposal(
        source=source,
        service_request_id=canonical_service_request_id,
        proposal_kind="sr_current_handler_reconciliation",
        risk_class="high",
        base_state_token=base_state_token,
        changes=(change,),
    )
    resolution_state = "support_rebind" if candidate_contact_id == prior_contact_id else "unique_candidate"
    return _result(
        source=source,
        service_request_id=canonical_service_request_id,
        scope_status=scope_status,
        resolution_state=resolution_state,
        matcher_scope=matcher_scope,
        matcher_explanation=match.explanation,
        supporting_owner_observation_id=supporting_owner_observation_id,
        supporting_source_field_id=supporting_source_field_id,
        proposals=(proposal,),
    )
