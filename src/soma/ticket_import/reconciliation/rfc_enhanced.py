from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

from soma.foundation.errors import IntegrityFailure, SomaError
from soma.foundation.identifiers import require_uuid4
from soma.foundation.strict_json import sha256_canonical_json
from soma.ticket_import.profiles.registry import require_field_spec, require_profile_versions
from soma.tickets.rfc_import_reader import RfcImportReader
from soma.tickets.validation import validate_rfc_no

from .engine import ProposalChangeDraft, ReconciliationProposalDraft

_SOURCE_FAMILY = "rfc_enhanced"
_PROPOSAL_FINGERPRINT_SCHEMA = "SOMA_IMPORT_PROPOSAL_FINGERPRINT_V1"
_HEX64_RE = re.compile(r"[0-9a-f]{64}\Z")
_TERMINAL_STATUS_CLASSES = frozenset({"terminal_closed", "terminal_cancelled"})
_STATUS_CLASSES = {
    "Implement": "implement_eligible",
    "Closed": "terminal_closed",
    "Cancelled": "terminal_cancelled",
}
_CURRENT_VALUE_COLUMNS = {
    "summary": "summary_text",
    "external_created_at": "external_created_at_utc",
    "creator": "creator_text",
    "customer_account_number": "customer_account_number_text",
    "customer_account_name": "customer_account_name_text",
    "severity": "severity_text",
    "status": "status_text",
    "owner_external_id": "owner_external_id_text",
    "owner_name": "owner_name_text",
    "l1_handler_name": "l1_handler_name_text",
    "l2_handler_name": "l2_handler_name_text",
    "last_update": "last_update_utc",
}


@dataclass(frozen=True, slots=True)
class RfcEnhancedProjectionProposalBuildResult:
    canonical_rfc_no: str
    rfc_id: str | None
    scope_status: str
    proposals: tuple[ReconciliationProposalDraft, ...]
    chronology_blocked_fields: tuple[str, ...]
    chronology_review_fields: tuple[str, ...]
    identity_owner_required: bool


@dataclass(frozen=True, slots=True)
class _SourceField:
    source_observation_field_id: str
    field_key: str
    field_class: str
    value_state: str
    value_kind: str
    normalized_text: str | None
    integer_value: int | None
    vocabulary_id: str | None
    field_logical_sha256: str


@dataclass(frozen=True, slots=True)
class _SourceObservation:
    import_run_id: str
    source_observation_id: str
    canonical_rfc_no: str
    row_logical_sha256: str
    source_row_chronology_utc: int | None
    source_profile_id: str
    header_registry_id: str
    vocabulary_registry_id: str
    parser_profile_id: str
    fields: tuple[_SourceField, ...]


def _require_sha256(value: str, *, label: str) -> str:
    if not isinstance(value, str) or _HEX64_RE.fullmatch(value) is None:
        raise IntegrityFailure(f"{label} is not lowercase SHA-256 hex")
    return value


def _load_source_observation(
    reader: Any,
    *,
    import_run_id: str,
    source_observation_id: str,
) -> _SourceObservation:
    run = reader.execute(
        "SELECT source_family,source_profile_id,header_registry_id,vocabulary_registry_id,parser_profile_id,run_state "
        "FROM import_runs WHERE import_run_id=?",
        (import_run_id,),
    ).fetchone()
    if run is None:
        raise SomaError("IMPORT_RUN_NOT_FOUND", "Enhanced RFC proposal parent run does not exist")
    expected = require_profile_versions(_SOURCE_FAMILY)
    if (
        str(run[0]) != _SOURCE_FAMILY
        or tuple(str(run[index]) for index in range(1, 5))
        != (
            expected.source_profile_id,
            expected.header_registry_id,
            expected.vocabulary_registry_id,
            expected.parser_profile_id,
        )
    ):
        raise SomaError("IMPORT_SOURCE_PROFILE_MISMATCH", "Enhanced RFC proposal run uses stale source profiles")
    if str(run[5]) != "validating":
        raise SomaError("IMPORT_RUN_STALE", "Enhanced RFC proposals may only be built during validating publication")

    observation = reader.execute(
        "SELECT import_run_id,source_family,entity_kind,identity_state,canonical_primary_id,canonical_parent_rfc_no,"
        "row_logical_sha256,source_row_chronology_utc FROM source_observations WHERE source_observation_id=?",
        (source_observation_id,),
    ).fetchone()
    if observation is None:
        raise SomaError("IMPORT_RUN_STALE", "Enhanced RFC proposal source observation disappeared")
    if (
        str(observation[0]) != import_run_id
        or str(observation[1]) != _SOURCE_FAMILY
        or str(observation[2]) != "rfc"
        or str(observation[3]) != "valid"
        or observation[4] is None
        or observation[5] is not None
    ):
        raise IntegrityFailure("Enhanced RFC proposal source observation identity authority is invalid")
    canonical_rfc_no = validate_rfc_no(str(observation[4]))
    row_hash = _require_sha256(str(observation[6]), label="Enhanced RFC source row logical hash")
    chronology = None if observation[7] is None else int(observation[7])
    if chronology is not None and chronology < 0:
        raise IntegrityFailure("Enhanced RFC source row chronology is invalid")

    rows = reader.execute(
        "SELECT source_observation_field_id,field_key,field_class,value_state,value_kind,normalized_text,integer_value,"
        "vocabulary_id,field_logical_sha256 FROM source_observation_fields WHERE source_observation_id=? "
        "ORDER BY field_key ASC",
        (source_observation_id,),
    ).fetchall()
    fields: list[_SourceField] = []
    seen_keys: set[str] = set()
    for row in rows:
        field_id = require_uuid4(str(row[0]))
        field_key = str(row[1])
        if field_key in seen_keys:
            raise IntegrityFailure("Enhanced RFC proposal source observation repeats a field key")
        seen_keys.add(field_key)
        spec = require_field_spec(_SOURCE_FAMILY, field_key)
        field_class = str(row[2])
        value_state = str(row[3])
        value_kind = str(row[4])
        vocabulary_id = None if row[7] is None else str(row[7])
        if field_class != spec.field_class or value_kind != spec.value_kind or vocabulary_id != spec.vocabulary_id:
            raise IntegrityFailure("Enhanced RFC proposal source field disagrees with the accepted profile registry")
        if value_state not in {"usable", "blank", "unknown", "malformed"}:
            raise IntegrityFailure("Enhanced RFC proposal source field has an invalid value state")
        normalized_text = None if row[5] is None else str(row[5])
        integer_value = None if row[6] is None else int(row[6])
        if value_state == "usable":
            if value_kind in {"text", "controlled"}:
                if normalized_text is None or integer_value is not None:
                    raise IntegrityFailure("usable Enhanced RFC text field has invalid normalized authority")
            elif value_kind == "instant":
                if normalized_text is not None or integer_value is None or integer_value < 0:
                    raise IntegrityFailure("usable Enhanced RFC instant field has invalid normalized authority")
            else:
                raise IntegrityFailure("Enhanced RFC proposal source field kind is unsupported")
        elif normalized_text is not None or integer_value is not None:
            raise IntegrityFailure("non-usable Enhanced RFC source field carries normalized authority")
        fields.append(
            _SourceField(
                source_observation_field_id=field_id,
                field_key=field_key,
                field_class=field_class,
                value_state=value_state,
                value_kind=value_kind,
                normalized_text=normalized_text,
                integer_value=integer_value,
                vocabulary_id=vocabulary_id,
                field_logical_sha256=_require_sha256(
                    str(row[8]),
                    label="Enhanced RFC source field logical hash",
                ),
            )
        )

    return _SourceObservation(
        import_run_id=import_run_id,
        source_observation_id=source_observation_id,
        canonical_rfc_no=canonical_rfc_no,
        row_logical_sha256=row_hash,
        source_row_chronology_utc=chronology,
        source_profile_id=str(run[1]),
        header_registry_id=str(run[2]),
        vocabulary_registry_id=str(run[3]),
        parser_profile_id=str(run[4]),
        fields=tuple(fields),
    )


def _scope_status(reader: Any, source: _SourceObservation) -> str:
    rows = reader.execute(
        "SELECT source_observation_id,row_logical_sha256 FROM source_observations "
        "WHERE import_run_id=? AND source_family=? AND entity_kind='rfc' AND identity_state='valid' "
        "AND canonical_primary_id=? ORDER BY source_observation_id ASC",
        (source.import_run_id, _SOURCE_FAMILY, source.canonical_rfc_no),
    ).fetchall()
    if not rows:
        raise IntegrityFailure("Enhanced RFC proposal source identity disappeared during scope classification")
    hashes = {_require_sha256(str(row[1]), label="Enhanced RFC duplicate row logical hash") for row in rows}
    if len(hashes) > 1:
        return "conflict"
    representative = str(rows[0][0])
    if len(rows) > 1 and representative != source.source_observation_id:
        return "equivalent_duplicate_suppressed"
    if len(rows) > 1:
        return "equivalent_duplicate_representative"
    return "unique"


def _usable_value(field: _SourceField) -> str | int | None:
    if field.value_state != "usable" or field.field_class != "active":
        return None
    if field.value_kind in {"text", "controlled"}:
        return field.normalized_text
    if field.value_kind == "instant":
        return field.integer_value
    raise IntegrityFailure("active Enhanced RFC field kind is outside the current projection contract")


def _change(
    *,
    ordinal: int,
    field: _SourceField,
    current_value: object,
    candidate_value: str | int,
) -> ProposalChangeDraft:
    before_text: str | None = None
    after_text: str | None = None
    before_integer: int | None = None
    after_integer: int | None = None
    if field.value_kind in {"text", "controlled"}:
        before_text = None if current_value is None else str(current_value)
        after_text = str(candidate_value)
    else:
        before_integer = None if current_value is None else int(current_value)
        after_integer = int(candidate_value)
    return ProposalChangeDraft(
        ordinal=ordinal,
        field_key=field.field_key,
        change_kind="set",
        value_kind=field.value_kind,
        before_text=before_text,
        after_text=after_text,
        before_integer=before_integer,
        after_integer=after_integer,
        source_observation_field_id=field.source_observation_field_id,
    )


def _proposal(
    *,
    source: _SourceObservation,
    rfc_id: str,
    risk_class: str,
    base_state_token: str,
    changes: tuple[ProposalChangeDraft, ...],
) -> ReconciliationProposalDraft:
    if not changes:
        raise IntegrityFailure("Enhanced RFC proposal construction requires at least one change")
    proposal_identity = {
        "proposal_kind": "rfc_source_projection",
        "evidence_mode": "observed_row",
        "risk_class": risk_class,
        "target_kind": "rfc",
        "target_internal_id": rfc_id,
        "target_business_id": source.canonical_rfc_no,
    }
    source_authority = {
        "import_run_id": source.import_run_id,
        "source_family": _SOURCE_FAMILY,
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
    proposal_fingerprint = sha256_canonical_json(
        {
            "schema": _PROPOSAL_FINGERPRINT_SCHEMA,
            "source": source_authority,
            "proposal": proposal_identity,
            "changes": [change.fingerprint_object() for change in changes],
        }
    )
    return ReconciliationProposalDraft(
        import_run_id=source.import_run_id,
        evidence_mode="observed_row",
        source_observation_id=source.source_observation_id,
        proposal_kind="rfc_source_projection",
        target_kind="rfc",
        target_internal_id=rfc_id,
        target_business_id=source.canonical_rfc_no,
        risk_class=risk_class,
        base_state_token_sha256=base_state_token,
        proposal_fingerprint_sha256=proposal_fingerprint,
        changes=changes,
    )


def build_rfc_enhanced_source_projection_proposals(
    reader: Any,
    *,
    import_run_id: str,
    source_observation_id: str,
    rfc_reader: RfcImportReader | None = None,
) -> RfcEnhancedProjectionProposalBuildResult:
    canonical_run_id = require_uuid4(import_run_id)
    canonical_observation_id = require_uuid4(source_observation_id)
    source = _load_source_observation(
        reader,
        import_run_id=canonical_run_id,
        source_observation_id=canonical_observation_id,
    )
    scope_status = _scope_status(reader, source)
    if scope_status in {"conflict", "equivalent_duplicate_suppressed"}:
        return RfcEnhancedProjectionProposalBuildResult(
            canonical_rfc_no=source.canonical_rfc_no,
            rfc_id=None,
            scope_status=scope_status,
            proposals=(),
            chronology_blocked_fields=(),
            chronology_review_fields=(),
            identity_owner_required=False,
        )

    authority = RfcImportReader() if rfc_reader is None else rfc_reader
    target = authority.get_by_number(reader, source.canonical_rfc_no)
    if target is None:
        return RfcEnhancedProjectionProposalBuildResult(
            canonical_rfc_no=source.canonical_rfc_no,
            rfc_id=None,
            scope_status=scope_status,
            proposals=(),
            chronology_blocked_fields=(),
            chronology_review_fields=(),
            identity_owner_required=True,
        )
    rfc_id = target.get("rfc_id")
    if not isinstance(rfc_id, str):
        raise IntegrityFailure("RFC import reader returned invalid proposal target identity")
    canonical_rfc_id = require_uuid4(rfc_id)
    if target.get("rfc_no") != source.canonical_rfc_no:
        raise IntegrityFailure("RFC import reader returned a mismatched exact identity")

    current = authority.current_source_projection(reader, canonical_rfc_id)
    current_row_chronology = None if current is None or current.get("last_update_utc") is None else int(current["last_update_utc"])
    chronology_blocked: set[str] = set()
    chronology_review: set[str] = set()
    candidate_changes: list[tuple[_SourceField, object, str | int]] = []

    for field in source.fields:
        if field.field_class != "active":
            continue
        column = _CURRENT_VALUE_COLUMNS.get(field.field_key)
        if column is None:
            raise IntegrityFailure("active Enhanced RFC field is outside the LLD-03 current projection registry")
        candidate_value = _usable_value(field)
        if candidate_value is None:
            continue
        current_value = None if current is None else current.get(column)
        if current_value == candidate_value:
            continue
        if current_value is not None:
            if source.source_row_chronology_utc is None or current_row_chronology is None:
                chronology_review.add(field.field_key)
            elif source.source_row_chronology_utc <= current_row_chronology:
                chronology_blocked.add(field.field_key)
                continue
        candidate_changes.append((field, current_value, candidate_value))

    if not candidate_changes:
        return RfcEnhancedProjectionProposalBuildResult(
            canonical_rfc_no=source.canonical_rfc_no,
            rfc_id=canonical_rfc_id,
            scope_status=scope_status,
            proposals=(),
            chronology_blocked_fields=tuple(sorted(chronology_blocked)),
            chronology_review_fields=tuple(sorted(chronology_review)),
            identity_owner_required=False,
        )

    changes = tuple(
        _change(
            ordinal=ordinal,
            field=field,
            current_value=current_value,
            candidate_value=candidate_value,
        )
        for ordinal, (field, current_value, candidate_value) in enumerate(candidate_changes)
    )

    risk_class = "medium"
    for field, current_value, candidate_value in candidate_changes:
        if field.field_key != "status":
            continue
        source_class = _STATUS_CLASSES.get(str(candidate_value))
        current_class = None if current is None else current.get("status_class")
        if source_class in _TERMINAL_STATUS_CLASSES or current_class in _TERMINAL_STATUS_CLASSES:
            risk_class = "high"
            break

    base_state_token = _require_sha256(
        authority.source_acceptance_base_token(reader, canonical_rfc_id),
        label="RFC source acceptance base token",
    )
    proposal = _proposal(
        source=source,
        rfc_id=canonical_rfc_id,
        risk_class=risk_class,
        base_state_token=base_state_token,
        changes=changes,
    )
    return RfcEnhancedProjectionProposalBuildResult(
        canonical_rfc_no=source.canonical_rfc_no,
        rfc_id=canonical_rfc_id,
        scope_status=scope_status,
        proposals=(proposal,),
        chronology_blocked_fields=tuple(sorted(chronology_blocked)),
        chronology_review_fields=tuple(sorted(chronology_review)),
        identity_owner_required=False,
    )
