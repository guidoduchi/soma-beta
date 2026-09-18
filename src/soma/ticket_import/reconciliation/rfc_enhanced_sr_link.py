from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from soma.foundation.errors import IntegrityFailure
from soma.foundation.identifiers import require_uuid4
from soma.foundation.strict_json import sha256_canonical_json
from soma.ticket_import.parsing.sr_candidates import SrCandidateMention, extract_sr_candidates
from soma.tickets.rfc_import_mutations import RfcImportMutationService
from soma.tickets.rfc_import_reader import RfcImportReader
from soma.tickets.service_request_import_reader import ServiceRequestImportReader

from .engine import ProposalChangeDraft, ReconciliationProposalDraft
from .rfc_enhanced import _SourceField, _load_source_observation, _scope_status

_PROPOSAL_FINGERPRINT_SCHEMA = "SOMA_IMPORT_PROPOSAL_FINGERPRINT_V1"


@dataclass(frozen=True, slots=True)
class RfcEnhancedSrLinkProposalBuildResult:
    canonical_rfc_no: str
    rfc_id: str | None
    scope_status: str
    resolution_state: str
    candidates: tuple[SrCandidateMention, ...]
    proposals: tuple[ReconciliationProposalDraft, ...]


def _summary_field(fields: tuple[_SourceField, ...]) -> _SourceField | None:
    field = next((candidate for candidate in fields if candidate.field_key == "summary"), None)
    if field is None or field.value_state != "usable":
        return None
    if field.field_class != "active" or field.value_kind != "text" or field.normalized_text is None:
        raise IntegrityFailure("usable Enhanced RFC Summary field has invalid authority")
    if field.integer_value is not None:
        raise IntegrityFailure("Enhanced RFC Summary unexpectedly carries integer authority")
    return field


def _proposal(
    *,
    source,
    rfc_id: str,
    service_request_id: str,
    official_sr_no: str,
    summary_field: _SourceField,
    risk_class: str,
    base_state_token: str,
) -> ReconciliationProposalDraft:
    change = ProposalChangeDraft(
        ordinal=0,
        field_key="service_request_id",
        change_kind="candidate",
        value_kind="identity",
        before_text=None,
        after_text=service_request_id,
        before_integer=None,
        after_integer=None,
        source_observation_field_id=summary_field.source_observation_field_id,
    )
    proposal_identity = {
        "proposal_kind": "sr_rfc_link_candidate",
        "evidence_mode": "observed_row",
        "risk_class": risk_class,
        "target_kind": "sr_rfc_relationship",
        "target_internal_id": rfc_id,
        "target_business_id": source.canonical_rfc_no,
        "candidate_service_request_id": service_request_id,
        "candidate_official_sr_no": official_sr_no,
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
        "summary_field": {
            "source_observation_field_id": summary_field.source_observation_field_id,
            "field_logical_sha256": summary_field.field_logical_sha256,
        },
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
        proposal_kind="sr_rfc_link_candidate",
        target_kind="sr_rfc_relationship",
        target_internal_id=rfc_id,
        target_business_id=source.canonical_rfc_no,
        risk_class=risk_class,
        base_state_token_sha256=base_state_token,
        proposal_fingerprint_sha256=fingerprint,
        changes=(change,),
    )


def build_rfc_enhanced_sr_link_candidate_proposals(
    reader: Any,
    *,
    import_run_id: str,
    source_observation_id: str,
    rfc_reader: RfcImportReader | None = None,
    sr_reader: ServiceRequestImportReader | None = None,
    allowed_run_states: frozenset[str] = frozenset({"validating"}),
) -> RfcEnhancedSrLinkProposalBuildResult:
    canonical_run_id = require_uuid4(import_run_id)
    canonical_observation_id = require_uuid4(source_observation_id)
    source = _load_source_observation(
        reader,
        import_run_id=canonical_run_id,
        source_observation_id=canonical_observation_id,
        allowed_run_states=allowed_run_states,
    )
    scope_status = _scope_status(reader, source)
    if scope_status in {"conflict", "equivalent_duplicate_suppressed"}:
        return RfcEnhancedSrLinkProposalBuildResult(
            canonical_rfc_no=source.canonical_rfc_no,
            rfc_id=None,
            scope_status=scope_status,
            resolution_state="scope_blocked",
            candidates=(),
            proposals=(),
        )

    summary = _summary_field(source.fields)
    if summary is None:
        return RfcEnhancedSrLinkProposalBuildResult(
            canonical_rfc_no=source.canonical_rfc_no,
            rfc_id=None,
            scope_status=scope_status,
            resolution_state="summary_unusable",
            candidates=(),
            proposals=(),
        )
    candidates = extract_sr_candidates(summary.normalized_text)
    if not candidates:
        return RfcEnhancedSrLinkProposalBuildResult(
            canonical_rfc_no=source.canonical_rfc_no,
            rfc_id=None,
            scope_status=scope_status,
            resolution_state="no_candidates",
            candidates=(),
            proposals=(),
        )

    rfc_authority = RfcImportReader() if rfc_reader is None else rfc_reader
    target = rfc_authority.get_by_number(reader, source.canonical_rfc_no)
    if target is None:
        return RfcEnhancedSrLinkProposalBuildResult(
            canonical_rfc_no=source.canonical_rfc_no,
            rfc_id=None,
            scope_status=scope_status,
            resolution_state="rfc_identity_pending",
            candidates=candidates,
            proposals=(),
        )
    rfc_id = target.get("rfc_id")
    if not isinstance(rfc_id, str):
        raise IntegrityFailure("RFC import reader returned invalid SR-link target identity")
    canonical_rfc_id = require_uuid4(rfc_id)
    if target.get("rfc_no") != source.canonical_rfc_no:
        raise IntegrityFailure("RFC import reader returned mismatched SR-link target identity")

    sr_authority = ServiceRequestImportReader() if sr_reader is None else sr_reader
    proposals: list[ReconciliationProposalDraft] = []
    for candidate in candidates:
        sr = sr_authority.get_by_official(reader, candidate.official_sr_no)
        if sr is None:
            continue
        service_request_id = sr.get("service_request_id")
        if not isinstance(service_request_id, str):
            raise IntegrityFailure("Service Request import reader returned invalid SR-link identity")
        canonical_sr_id = require_uuid4(service_request_id)
        if sr.get("official_sr_no") != candidate.official_sr_no:
            raise IntegrityFailure("Service Request import reader returned mismatched SR-link business identity")
        context = RfcImportMutationService.sr_link_candidate_context(
            reader,
            canonical_sr_id,
            canonical_rfc_id,
        )
        if context.duplicate_active:
            continue
        proposals.append(
            _proposal(
                source=source,
                rfc_id=canonical_rfc_id,
                service_request_id=canonical_sr_id,
                official_sr_no=candidate.official_sr_no,
                summary_field=summary,
                risk_class=context.risk_class,
                base_state_token=context.base_state_token,
            )
        )

    return RfcEnhancedSrLinkProposalBuildResult(
        canonical_rfc_no=source.canonical_rfc_no,
        rfc_id=canonical_rfc_id,
        scope_status=scope_status,
        resolution_state="existing_matches" if proposals else "no_existing_unlinked_matches",
        candidates=candidates,
        proposals=tuple(proposals),
    )
