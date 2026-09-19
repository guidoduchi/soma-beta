from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from soma.foundation.errors import IntegrityFailure
from soma.foundation.identifiers import require_uuid4
from soma.foundation.strict_json import sha256_canonical_json
from soma.tickets.rfc_import_mutations import RfcImportMutationService
from soma.tickets.rfc_import_reader import RfcImportReader

from .engine import ProposalChangeDraft, ReconciliationProposalDraft
from .rfc_enhanced import _load_source_observation, _require_sha256, _scope_status

_PROPOSAL_FINGERPRINT_SCHEMA = "SOMA_IMPORT_PROPOSAL_FINGERPRINT_V1"


@dataclass(frozen=True, slots=True)
class RfcEnhancedIdentityProposalBuildResult:
    canonical_rfc_no: str
    rfc_id: str | None
    scope_status: str
    proposals: tuple[ReconciliationProposalDraft, ...]


def _source_authority(source) -> dict[str, object]:
    return {
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


def build_rfc_enhanced_identity_proposals(
    reader: Any,
    *,
    import_run_id: str,
    source_observation_id: str,
    rfc_reader: RfcImportReader | None = None,
) -> RfcEnhancedIdentityProposalBuildResult:
    canonical_run_id = require_uuid4(import_run_id)
    canonical_observation_id = require_uuid4(source_observation_id)
    source = _load_source_observation(
        reader,
        import_run_id=canonical_run_id,
        source_observation_id=canonical_observation_id,
    )
    scope_status = _scope_status(reader, source)
    if scope_status in {"conflict", "equivalent_duplicate_suppressed"}:
        return RfcEnhancedIdentityProposalBuildResult(
            canonical_rfc_no=source.canonical_rfc_no,
            rfc_id=None,
            scope_status=scope_status,
            proposals=(),
        )

    authority = RfcImportReader() if rfc_reader is None else rfc_reader
    target = authority.get_by_number(reader, source.canonical_rfc_no)
    if target is not None:
        rfc_id = target.get("rfc_id")
        if not isinstance(rfc_id, str):
            raise IntegrityFailure("RFC import reader returned invalid proposal target identity")
        canonical_rfc_id = require_uuid4(rfc_id)
        if target.get("rfc_no") != source.canonical_rfc_no:
            raise IntegrityFailure("RFC import reader returned a mismatched exact identity")
        return RfcEnhancedIdentityProposalBuildResult(
            canonical_rfc_no=source.canonical_rfc_no,
            rfc_id=canonical_rfc_id,
            scope_status=scope_status,
            proposals=(),
        )

    change = ProposalChangeDraft(
        ordinal=0,
        field_key="rfc_no",
        change_kind="create",
        value_kind="identity",
        before_text=None,
        after_text=source.canonical_rfc_no,
        before_integer=None,
        after_integer=None,
        source_observation_field_id=None,
    )
    base_state_token = _require_sha256(
        RfcImportMutationService.source_identity_base_token(reader, source.canonical_rfc_no),
        label="RFC source identity base token",
    )
    proposal_identity = {
        "proposal_kind": "rfc_create_or_adopt",
        "evidence_mode": "observed_row",
        "risk_class": "medium",
        "target_kind": "rfc",
        "target_internal_id": None,
        "target_business_id": source.canonical_rfc_no,
    }
    proposal_fingerprint = sha256_canonical_json(
        {
            "schema": _PROPOSAL_FINGERPRINT_SCHEMA,
            "source": _source_authority(source),
            "proposal": proposal_identity,
            "changes": [change.fingerprint_object()],
        }
    )
    proposal = ReconciliationProposalDraft(
        import_run_id=source.import_run_id,
        evidence_mode="observed_row",
        source_observation_id=source.source_observation_id,
        proposal_kind="rfc_create_or_adopt",
        target_kind="rfc",
        target_internal_id=None,  # type: ignore[arg-type]
        target_business_id=source.canonical_rfc_no,
        risk_class="medium",
        base_state_token_sha256=base_state_token,
        proposal_fingerprint_sha256=proposal_fingerprint,
        changes=(change,),
    )
    return RfcEnhancedIdentityProposalBuildResult(
        canonical_rfc_no=source.canonical_rfc_no,
        rfc_id=None,
        scope_status=scope_status,
        proposals=(proposal,),
    )
