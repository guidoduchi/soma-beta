from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date
from typing import Any

from soma.foundation.errors import IntegrityFailure
from soma.foundation.identifiers import require_uuid4
from soma.foundation.strict_json import sha256_canonical_json
from soma.tickets.rfc_import_mutations import RfcImportMutationService
from soma.tickets.rfc_import_reader import RfcImportReader
from soma.tickets.service_request_import_reader import ServiceRequestImportReader

from .engine import ProposalChangeDraft, ReconciliationProposalDraft
from .rfc_enhanced import _SourceField, _load_source_observation, _scope_status

_PROPOSAL_FINGERPRINT_SCHEMA = "SOMA_IMPORT_PROPOSAL_FINGERPRINT_V1"
_STRONG_RE = re.compile(r"(?<![A-Za-z0-9])(?:SR|TT)[ \t]*([0-9]{8})(?![A-Za-z0-9])", re.IGNORECASE)
_WEAK_RE = re.compile(r"(?<![A-Za-z0-9])([0-9]{8})(?![A-Za-z0-9])")


@dataclass(frozen=True, slots=True)
class SrCandidateMention:
    official_sr_no: str
    strength: str
    mention_count: int


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


def _valid_date_token(token: str) -> bool:
    if len(token) != 8 or not token.isascii() or not token.isdigit():
        return False
    candidates = (
        (int(token[0:4]), int(token[4:6]), int(token[6:8])),
        (int(token[4:8]), int(token[2:4]), int(token[0:2])),
        (int(token[4:8]), int(token[0:2]), int(token[2:4])),
    )
    for year, month, day in candidates:
        try:
            date(year, month, day)
        except ValueError:
            continue
        return True
    return False


def extract_sr_candidates(text: str) -> tuple[SrCandidateMention, ...]:
    if not isinstance(text, str) or "\x00" in text:
        raise IntegrityFailure("Enhanced RFC Summary candidate source is invalid text")
    counts: dict[str, int] = {}
    strengths: dict[str, str] = {}
    strong_digit_spans: list[tuple[int, int]] = []
    for match in _STRONG_RE.finditer(text):
        token = match.group(1)
        strong_digit_spans.append(match.span(1))
        counts[token] = counts.get(token, 0) + 1
        strengths[token] = "strong"
    for match in _WEAK_RE.finditer(text):
        span = match.span(1)
        if any(span[0] < strong_end and strong_start < span[1] for strong_start, strong_end in strong_digit_spans):
            continue
        token = match.group(1)
        if _valid_date_token(token):
            continue
        counts[token] = counts.get(token, 0) + 1
        strengths.setdefault(token, "weak")
    return tuple(
        SrCandidateMention(
            official_sr_no=token,
            strength=strengths[token],
            mention_count=counts[token],
        )
        for token in sorted(counts)
    )


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
) -> RfcEnhancedSrLinkProposalBuildResult:
    canonical_run_id = require_uuid4(import_run_id)
    canonical_observation_id = require_uuid4(source_observation_id)
    source = _load_source_observation(
        reader,
        import_run_id=canonical_run_id,
        source_observation_id=canonical_observation_id,
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
