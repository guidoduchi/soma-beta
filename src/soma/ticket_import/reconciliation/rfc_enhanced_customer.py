from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from soma.foundation.errors import IntegrityFailure
from soma.foundation.identifiers import require_uuid4
from soma.foundation.strict_json import sha256_canonical_json
from soma.reference.queries.matching import ReferenceMatcher
from soma.tickets.rfc_import_mutations import RfcImportMutationService
from soma.tickets.rfc_import_reader import RfcImportReader

from .engine import ProposalChangeDraft, ReconciliationProposalDraft
from .rfc_enhanced import _SourceField, _load_source_observation, _scope_status

_PROPOSAL_FINGERPRINT_SCHEMA = "SOMA_IMPORT_PROPOSAL_FINGERPRINT_V1"


@dataclass(frozen=True, slots=True)
class RfcEnhancedCustomerProposalBuildResult:
    canonical_rfc_no: str
    rfc_id: str | None
    scope_status: str
    resolution_state: str
    matcher_explanation: str | None
    proposals: tuple[ReconciliationProposalDraft, ...]


def _usable_customer_text(source_fields: tuple[_SourceField, ...], field_key: str) -> _SourceField | None:
    field = next((candidate for candidate in source_fields if candidate.field_key == field_key), None)
    if field is None:
        return None
    if field.field_class != "active" or field.value_kind != "text":
        raise IntegrityFailure("Enhanced RFC Customer source field disagrees with the active text registry")
    if field.value_state != "usable":
        return None
    if field.normalized_text is None or field.integer_value is not None:
        raise IntegrityFailure("usable Enhanced RFC Customer source field lacks exact text authority")
    return field


def _proposal(
    *,
    source,
    rfc_id: str,
    current_customer_org_id: str | None,
    target_customer_org_id: str,
    source_field: _SourceField,
    base_state_token: str,
) -> ReconciliationProposalDraft:
    change = ProposalChangeDraft(
        ordinal=0,
        field_key="customer_org_id",
        change_kind="set",
        value_kind="identity",
        before_text=current_customer_org_id,
        after_text=target_customer_org_id,
        before_integer=None,
        after_integer=None,
        source_observation_field_id=source_field.source_observation_field_id,
    )
    proposal_identity = {
        "proposal_kind": "rfc_customer_reconciliation",
        "evidence_mode": "observed_row",
        "risk_class": "high",
        "target_kind": "rfc",
        "target_internal_id": rfc_id,
        "target_business_id": source.canonical_rfc_no,
    }
    source_authority = {
        "import_run_id": source.import_run_id,
        "source_family": "rfc_enhanced",
        "source_profile_id": source.source_profile_id,
        "header_registry_id": source.header_registry_id,
        "vocabulary_registry_id": source.vocabulary_registry_id,
        "parser_profile_id": source.parser_profile_id,
        "source_observation_id": source.source_observation_id,
        "canonical_primary_id": source.canonical_rfc_no,
        "row_logical_sha256": source.row_logical_sha256,
        "source_row_chronology_utc": source.source_row_chronology_utc,
        "fields": [
            {
                "source_observation_field_id": field.source_observation_field_id,
                "field_key": field.field_key,
                "field_logical_sha256": field.field_logical_sha256,
            }
            for field in source.fields
        ],
    }
    fingerprint = sha256_canonical_json(
        {
            "schema": _PROPOSAL_FINGERPRINT_SCHEMA,
            "source": source_authority,
            "proposal": proposal_identity,
            "changes": [change.fingerprint_object()],
        }
    )
    return ReconciliationProposalDraft(
        import_run_id=source.import_run_id,
        evidence_mode="observed_row",
        source_observation_id=source.source_observation_id,
        proposal_kind="rfc_customer_reconciliation",
        target_kind="rfc",
        target_internal_id=rfc_id,
        target_business_id=source.canonical_rfc_no,
        risk_class="high",
        base_state_token_sha256=base_state_token,
        proposal_fingerprint_sha256=fingerprint,
        changes=(change,),
    )


def build_rfc_enhanced_customer_reconciliation_proposals(
    reader: Any,
    *,
    import_run_id: str,
    source_observation_id: str,
    rfc_reader: RfcImportReader | None = None,
) -> RfcEnhancedCustomerProposalBuildResult:
    canonical_run_id = require_uuid4(import_run_id)
    canonical_observation_id = require_uuid4(source_observation_id)
    source = _load_source_observation(
        reader,
        import_run_id=canonical_run_id,
        source_observation_id=canonical_observation_id,
    )
    scope_status = _scope_status(reader, source)
    if scope_status in {"conflict", "equivalent_duplicate_suppressed"}:
        return RfcEnhancedCustomerProposalBuildResult(
            canonical_rfc_no=source.canonical_rfc_no,
            rfc_id=None,
            scope_status=scope_status,
            resolution_state="scope_blocked",
            matcher_explanation=None,
            proposals=(),
        )

    authority = RfcImportReader() if rfc_reader is None else rfc_reader
    target = authority.get_by_number(reader, source.canonical_rfc_no)
    if target is None:
        return RfcEnhancedCustomerProposalBuildResult(
            canonical_rfc_no=source.canonical_rfc_no,
            rfc_id=None,
            scope_status=scope_status,
            resolution_state="rfc_identity_pending",
            matcher_explanation=None,
            proposals=(),
        )
    rfc_id = target.get("rfc_id")
    if not isinstance(rfc_id, str):
        raise IntegrityFailure("RFC import reader returned invalid Customer proposal target identity")
    canonical_rfc_id = require_uuid4(rfc_id)
    if target.get("rfc_no") != source.canonical_rfc_no:
        raise IntegrityFailure("RFC import reader returned a mismatched Customer proposal identity")
    current_customer = target.get("customer_org_id")
    if current_customer is not None:
        if not isinstance(current_customer, str):
            raise IntegrityFailure("RFC import reader returned invalid current Customer identity")
        current_customer = require_uuid4(current_customer)

    account = _usable_customer_text(source.fields, "customer_account_number")
    label = _usable_customer_text(source.fields, "customer_account_name")
    if account is None:
        return RfcEnhancedCustomerProposalBuildResult(
            canonical_rfc_no=source.canonical_rfc_no,
            rfc_id=canonical_rfc_id,
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
        resolution_state = (
            "non_authoritative_name_candidate"
            if match.state == "UNIQUE_CANDIDATE"
            and match.explanation == "ACCOUNT_CODE_UNRESOLVED_NAME_CANDIDATE"
            else match.state.lower()
        )
        return RfcEnhancedCustomerProposalBuildResult(
            canonical_rfc_no=source.canonical_rfc_no,
            rfc_id=canonical_rfc_id,
            scope_status=scope_status,
            resolution_state=resolution_state,
            matcher_explanation=match.explanation,
            proposals=(),
        )

    candidate_customer_org_id = require_uuid4(match.candidate_ids[0])
    if current_customer == candidate_customer_org_id:
        return RfcEnhancedCustomerProposalBuildResult(
            canonical_rfc_no=source.canonical_rfc_no,
            rfc_id=canonical_rfc_id,
            scope_status=scope_status,
            resolution_state="already_current",
            matcher_explanation=match.explanation,
            proposals=(),
        )

    base_state_token = RfcImportMutationService.customer_reconciliation_base_token(
        reader,
        canonical_rfc_id,
        candidate_customer_org_id,
    )
    proposal = _proposal(
        source=source,
        rfc_id=canonical_rfc_id,
        current_customer_org_id=current_customer,
        target_customer_org_id=candidate_customer_org_id,
        source_field=account,
        base_state_token=base_state_token,
    )
    return RfcEnhancedCustomerProposalBuildResult(
        canonical_rfc_no=source.canonical_rfc_no,
        rfc_id=canonical_rfc_id,
        scope_status=scope_status,
        resolution_state="unique_candidate",
        matcher_explanation=match.explanation,
        proposals=(proposal,),
    )
