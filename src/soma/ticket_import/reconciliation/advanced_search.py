from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

from soma.foundation.errors import IntegrityFailure, SomaError
from soma.foundation.identifiers import require_uuid4
from soma.foundation.strict_json import sha256_canonical_json
from soma.ticket_import.profiles.registry import require_field_spec, require_profile_versions
from soma.tickets.import_mutations import ServiceRequestImportReader
from soma.tickets.validation import validate_official_sr_no

from .engine import ProposalChangeDraft, ReconciliationProposalDraft


_SOURCE_FAMILY = "advanced_search_sr"
_PROPOSAL_FINGERPRINT_SCHEMA = "SOMA_IMPORT_PROPOSAL_FINGERPRINT_V1"
_HEX64_RE = re.compile(r"[0-9a-f]{64}\Z")
_TERMINAL_SR_STATUSES = frozenset({"Closed", "Resolved", "Cancelled"})
_PROJECTION_COLUMNS = {
    "problem_summary": "problem_summary_observation_id",
    "report_date": "report_date_observation_id",
    "customer_contact_label": "customer_contact_observation_id",
    "customer_severity": "customer_severity_observation_id",
    "current_handler_label": "current_handler_observation_id",
    "status": "status_observation_id",
    "customer_org_label": "customer_org_observation_id",
    "customer_account_code": "customer_account_code_observation_id",
    "suspend_planned_end": "suspend_planned_end_observation_id",
    "suspension_duration": "suspension_duration_observation_id",
    "last_update": "last_update_observation_id",
}


@dataclass(frozen=True, slots=True)
class AdvancedSearchSrProjectionProposalBuildResult:
    canonical_sr_no: str
    service_request_id: str | None
    scope_status: str
    proposals: tuple[ReconciliationProposalDraft, ...]
    chronology_blocked_fields: tuple[str, ...]


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
    canonical_sr_no: str
    row_logical_sha256: str
    source_row_chronology_utc: int | None
    source_profile_id: str
    header_registry_id: str
    vocabulary_registry_id: str
    parser_profile_id: str
    fields: tuple[_SourceField, ...]


@dataclass(frozen=True, slots=True)
class _CurrentField:
    value_state: str
    value_kind: str
    value: str | int | None
    source_chronology_utc: int | None


@dataclass(frozen=True, slots=True)
class _CandidateValue:
    value_state: str
    value_kind: str
    value: str | int | None


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
        raise SomaError("IMPORT_RUN_NOT_FOUND", "Advanced Search proposal parent run does not exist")
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
        raise SomaError("IMPORT_SOURCE_PROFILE_MISMATCH", "Advanced Search proposal run uses stale source profiles")
    if str(run[5]) != "validating":
        raise SomaError("IMPORT_RUN_STALE", "Advanced Search proposals may only be built during validating publication")

    observation = reader.execute(
        "SELECT import_run_id,source_family,entity_kind,identity_state,canonical_primary_id,canonical_parent_rfc_no,"
        "row_logical_sha256,source_row_chronology_utc FROM source_observations WHERE source_observation_id=?",
        (source_observation_id,),
    ).fetchone()
    if observation is None:
        raise SomaError("IMPORT_RUN_STALE", "Advanced Search proposal source observation disappeared")
    if (
        str(observation[0]) != import_run_id
        or str(observation[1]) != _SOURCE_FAMILY
        or str(observation[2]) != "service_request"
        or str(observation[3]) != "valid"
        or observation[4] is None
        or observation[5] is not None
    ):
        raise IntegrityFailure("Advanced Search proposal source observation identity authority is invalid")
    canonical_sr_no = validate_official_sr_no(str(observation[4]))
    row_hash = _require_sha256(str(observation[6]), label="Advanced Search source row logical hash")
    chronology = None if observation[7] is None else int(observation[7])
    if chronology is not None and chronology < 0:
        raise IntegrityFailure("Advanced Search source row chronology is invalid")

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
            raise IntegrityFailure("Advanced Search proposal source observation repeats a field key")
        seen_keys.add(field_key)
        spec = require_field_spec(_SOURCE_FAMILY, field_key)
        field_class = str(row[2])
        value_state = str(row[3])
        value_kind = str(row[4])
        vocabulary_id = None if row[7] is None else str(row[7])
        if field_class != spec.field_class or value_kind != spec.value_kind or vocabulary_id != spec.vocabulary_id:
            raise IntegrityFailure("Advanced Search proposal source field disagrees with the accepted profile registry")
        if value_state not in {"usable", "blank", "unknown", "malformed"}:
            raise IntegrityFailure("Advanced Search proposal source field has an invalid value state")
        normalized_text = None if row[5] is None else str(row[5])
        integer_value = None if row[6] is None else int(row[6])
        if value_state == "usable":
            if value_kind in {"text", "controlled"}:
                if normalized_text is None or integer_value is not None:
                    raise IntegrityFailure("usable Advanced Search text field has invalid normalized authority")
            elif value_kind in {"instant", "duration_seconds"}:
                if normalized_text is not None or integer_value is None or integer_value < 0:
                    raise IntegrityFailure("usable Advanced Search numeric field has invalid normalized authority")
            else:
                raise IntegrityFailure("Advanced Search proposal source field kind is unsupported")
        elif normalized_text is not None or integer_value is not None:
            raise IntegrityFailure("non-usable Advanced Search source field carries normalized authority")
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
                    label="Advanced Search source field logical hash",
                ),
            )
        )

    return _SourceObservation(
        import_run_id=import_run_id,
        source_observation_id=source_observation_id,
        canonical_sr_no=canonical_sr_no,
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
        "WHERE import_run_id=? AND source_family=? AND entity_kind='service_request' AND identity_state='valid' "
        "AND canonical_primary_id=? ORDER BY source_observation_id ASC",
        (source.import_run_id, _SOURCE_FAMILY, source.canonical_sr_no),
    ).fetchall()
    if not rows:
        raise IntegrityFailure("Advanced Search proposal source identity disappeared during scope classification")
    hashes = {_require_sha256(str(row[1]), label="Advanced Search duplicate row logical hash") for row in rows}
    if len(hashes) > 1:
        return "conflict"
    representative = str(rows[0][0])
    if len(rows) > 1 and representative != source.source_observation_id:
        return "equivalent_duplicate_suppressed"
    if len(rows) > 1:
        return "equivalent_duplicate_representative"
    return "unique"


def _load_current_field(
    reader: Any,
    *,
    service_request_id: str,
    field_key: str,
    current_projection: dict[str, object] | None,
) -> _CurrentField | None:
    if current_projection is None:
        return None
    projection_column = _PROJECTION_COLUMNS[field_key]
    observation_id = current_projection.get(projection_column)
    if observation_id is None:
        return None
    if not isinstance(observation_id, str):
        raise IntegrityFailure("Service Request source projection contains a non-text observation identity")
    row = reader.execute(
        "SELECT field_key,value_state,value_kind,text_value,integer_value,source_chronology_utc "
        "FROM sr_source_field_observations WHERE sr_source_field_observation_id=? AND service_request_id=?",
        (observation_id, service_request_id),
    ).fetchone()
    if row is None:
        raise IntegrityFailure("Service Request source projection points to missing field observation")
    if str(row[0]) != field_key:
        raise IntegrityFailure("Service Request source projection points to the wrong field observation")
    value_state = str(row[1])
    value_kind = str(row[2])
    if value_state not in {"usable", "explicit_clear"}:
        raise IntegrityFailure("current Service Request source observation has invalid value state")
    if value_state == "explicit_clear":
        if field_key != "current_handler_label" or value_kind != "text" or row[3] is not None or row[4] is not None:
            raise IntegrityFailure("current Service Request explicit clear observation is invalid")
        value: str | int | None = None
    elif value_kind in {"text", "controlled"}:
        if row[3] is None or row[4] is not None:
            raise IntegrityFailure("current Service Request text source observation is invalid")
        value = str(row[3])
    elif value_kind in {"instant", "duration_seconds"}:
        if row[3] is not None or type(row[4]) is not int:
            raise IntegrityFailure("current Service Request numeric source observation is invalid")
        value = int(row[4])
    else:
        raise IntegrityFailure("current Service Request source observation kind is invalid")
    chronology = None if row[5] is None else int(row[5])
    if chronology is not None and chronology < 0:
        raise IntegrityFailure("current Service Request source observation chronology is invalid")
    return _CurrentField(
        value_state=value_state,
        value_kind=value_kind,
        value=value,
        source_chronology_utc=chronology,
    )


def _candidate(field: _SourceField) -> _CandidateValue | None:
    if field.value_state == "usable":
        value: str | int | None
        if field.value_kind in {"text", "controlled"}:
            value = field.normalized_text
        else:
            value = field.integer_value
        return _CandidateValue("usable", field.value_kind, value)
    if field.field_key == "current_handler_label" and field.value_state == "blank" and field.value_kind == "text":
        return _CandidateValue("explicit_clear", "text", None)
    return None


def _same_value(current: _CurrentField | None, candidate: _CandidateValue) -> bool:
    return current is not None and (
        current.value_state == candidate.value_state
        and current.value_kind == candidate.value_kind
        and current.value == candidate.value
    )


def _change(
    *,
    ordinal: int,
    field: _SourceField,
    current: _CurrentField | None,
    candidate: _CandidateValue,
) -> ProposalChangeDraft:
    before_text = None
    before_integer = None
    after_text = None
    after_integer = None
    if current is not None:
        if current.value_kind in {"text", "controlled"}:
            before_text = None if current.value is None else str(current.value)
        else:
            before_integer = None if current.value is None else int(current.value)
    if candidate.value_kind in {"text", "controlled"}:
        after_text = None if candidate.value is None else str(candidate.value)
    else:
        after_integer = None if candidate.value is None else int(candidate.value)
    return ProposalChangeDraft(
        ordinal=ordinal,
        field_key=field.field_key,
        change_kind="clear" if candidate.value_state == "explicit_clear" else "set",
        value_kind=candidate.value_kind,
        before_text=before_text,
        after_text=after_text,
        before_integer=before_integer,
        after_integer=after_integer,
        source_observation_field_id=field.source_observation_field_id,
    )


def _field_set_base_token(
    authority: ServiceRequestImportReader,
    reader: Any,
    service_request_id: str,
    changes: tuple[ProposalChangeDraft, ...],
) -> str:
    field_keys = tuple(change.field_key for change in changes)
    return _require_sha256(
        authority.source_field_set_base_token(reader, service_request_id, field_keys),
        label="Service Request source field-set base token",
    )


def _proposal(
    *,
    source: _SourceObservation,
    service_request_id: str,
    proposal_kind: str,
    risk_class: str,
    base_state_token: str,
    changes: tuple[ProposalChangeDraft, ...],
) -> ReconciliationProposalDraft:
    if not changes:
        raise IntegrityFailure("Advanced Search proposal construction requires at least one change")
    proposal_identity = {
        "proposal_kind": proposal_kind,
        "evidence_mode": "observed_row",
        "risk_class": risk_class,
        "target_kind": "service_request",
        "target_internal_id": service_request_id,
        "target_business_id": source.canonical_sr_no,
    }
    source_authority = {
        "import_run_id": source.import_run_id,
        "source_family": _SOURCE_FAMILY,
        "source_profile_id": source.source_profile_id,
        "header_registry_id": source.header_registry_id,
        "vocabulary_registry_id": source.vocabulary_registry_id,
        "parser_profile_id": source.parser_profile_id,
        "source_observation_id": source.source_observation_id,
        "canonical_primary_id": source.canonical_sr_no,
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
        proposal_kind=proposal_kind,
        target_kind="service_request",
        target_internal_id=service_request_id,
        target_business_id=source.canonical_sr_no,
        risk_class=risk_class,
        base_state_token_sha256=base_state_token,
        proposal_fingerprint_sha256=proposal_fingerprint,
        changes=changes,
    )


def build_advanced_search_sr_source_projection_proposals(
    reader: Any,
    *,
    import_run_id: str,
    source_observation_id: str,
    sr_reader: ServiceRequestImportReader | None = None,
) -> AdvancedSearchSrProjectionProposalBuildResult:
    canonical_run_id = require_uuid4(import_run_id)
    canonical_observation_id = require_uuid4(source_observation_id)
    source = _load_source_observation(
        reader,
        import_run_id=canonical_run_id,
        source_observation_id=canonical_observation_id,
    )
    scope_status = _scope_status(reader, source)
    if scope_status in {"conflict", "equivalent_duplicate_suppressed"}:
        return AdvancedSearchSrProjectionProposalBuildResult(
            canonical_sr_no=source.canonical_sr_no,
            service_request_id=None,
            scope_status=scope_status,
            proposals=(),
            chronology_blocked_fields=(),
        )

    authority = ServiceRequestImportReader() if sr_reader is None else sr_reader
    target = authority.get_by_official(reader, source.canonical_sr_no)
    if target is None:
        return AdvancedSearchSrProjectionProposalBuildResult(
            canonical_sr_no=source.canonical_sr_no,
            service_request_id=None,
            scope_status=scope_status,
            proposals=(),
            chronology_blocked_fields=(),
        )
    service_request_id = target.get("service_request_id")
    if not isinstance(service_request_id, str):
        raise IntegrityFailure("Service Request import reader returned invalid proposal target identity")
    canonical_service_request_id = require_uuid4(service_request_id)
    if target.get("official_sr_no") != source.canonical_sr_no:
        raise IntegrityFailure("Service Request import reader returned a mismatched official identity")

    current_projection = authority.current_source_projection(reader, canonical_service_request_id)
    ordinary: list[tuple[_SourceField, _CurrentField | None, _CandidateValue]] = []
    terminal_entry: list[tuple[_SourceField, _CurrentField | None, _CandidateValue]] = []
    reviewed_terminal: list[tuple[_SourceField, _CurrentField | None, _CandidateValue]] = []
    reviewed_suspension: list[tuple[_SourceField, _CurrentField | None, _CandidateValue]] = []
    chronology_blocked: set[str] = set()

    for field in source.fields:
        if field.field_class != "active":
            continue
        if field.field_key not in _PROJECTION_COLUMNS:
            raise IntegrityFailure("active Advanced Search field is outside the LLD-03 SR source projection registry")
        candidate = _candidate(field)
        if candidate is None:
            continue
        current = _load_current_field(
            reader,
            service_request_id=canonical_service_request_id,
            field_key=field.field_key,
            current_projection=current_projection,
        )
        if current is not None and current.value_kind != candidate.value_kind:
            raise IntegrityFailure("current Service Request source field kind disagrees with Advanced Search registry")
        if _same_value(current, candidate):
            continue

        if (
            field.field_key == "status"
            and current is not None
            and current.value_state == "usable"
            and current.value in _TERMINAL_SR_STATUSES
            and candidate.value_state == "usable"
            and candidate.value != current.value
        ):
            reviewed_terminal.append((field, current, candidate))
            continue
        if (
            field.field_key == "suspension_duration"
            and current is not None
            and current.value_state == "usable"
            and isinstance(current.value, int)
            and current.value > 0
            and candidate.value_state == "usable"
            and candidate.value == 0
        ):
            reviewed_suspension.append((field, current, candidate))
            continue

        source_chronology = source.source_row_chronology_utc
        if source_chronology is None or (
            current is not None
            and (current.source_chronology_utc is None or source_chronology <= current.source_chronology_utc)
        ):
            chronology_blocked.add(field.field_key)
            continue

        if field.field_key == "status" and candidate.value in _TERMINAL_SR_STATUSES:
            terminal_entry.append((field, current, candidate))
        else:
            ordinary.append((field, current, candidate))

    proposals: list[ReconciliationProposalDraft] = []
    if ordinary:
        ordered = sorted(ordinary, key=lambda item: item[0].field_key.encode("utf-8"))
        changes = tuple(
            _change(ordinal=index, field=field, current=current, candidate=candidate)
            for index, (field, current, candidate) in enumerate(ordered)
        )
        proposals.append(
            _proposal(
                source=source,
                service_request_id=canonical_service_request_id,
                proposal_kind="sr_source_projection",
                risk_class="medium",
                base_state_token=_field_set_base_token(
                    authority,
                    reader,
                    canonical_service_request_id,
                    changes,
                ),
                changes=changes,
            )
        )
    if terminal_entry:
        if len(terminal_entry) != 1:
            raise IntegrityFailure("Advanced Search source row contains more than one status field")
        field, current, candidate = terminal_entry[0]
        changes = (_change(ordinal=0, field=field, current=current, candidate=candidate),)
        proposals.append(
            _proposal(
                source=source,
                service_request_id=canonical_service_request_id,
                proposal_kind="sr_source_projection",
                risk_class="high",
                base_state_token=_field_set_base_token(
                    authority,
                    reader,
                    canonical_service_request_id,
                    changes,
                ),
                changes=changes,
            )
        )
    if reviewed_terminal:
        if len(reviewed_terminal) != 1:
            raise IntegrityFailure("Advanced Search source row contains more than one status correction")
        field, current, candidate = reviewed_terminal[0]
        changes = (_change(ordinal=0, field=field, current=current, candidate=candidate),)
        proposals.append(
            _proposal(
                source=source,
                service_request_id=canonical_service_request_id,
                proposal_kind="sr_terminal_reversal_review",
                risk_class="high",
                base_state_token=_field_set_base_token(
                    authority,
                    reader,
                    canonical_service_request_id,
                    changes,
                ),
                changes=changes,
            )
        )
    if reviewed_suspension:
        if len(reviewed_suspension) != 1:
            raise IntegrityFailure("Advanced Search source row contains more than one suspension regression")
        field, current, candidate = reviewed_suspension[0]
        changes = (_change(ordinal=0, field=field, current=current, candidate=candidate),)
        proposals.append(
            _proposal(
                source=source,
                service_request_id=canonical_service_request_id,
                proposal_kind="sr_suspension_regression_review",
                risk_class="high",
                base_state_token=_field_set_base_token(
                    authority,
                    reader,
                    canonical_service_request_id,
                    changes,
                ),
                changes=changes,
            )
        )

    return AdvancedSearchSrProjectionProposalBuildResult(
        canonical_sr_no=source.canonical_sr_no,
        service_request_id=canonical_service_request_id,
        scope_status=scope_status,
        proposals=tuple(proposals),
        chronology_blocked_fields=tuple(sorted(chronology_blocked, key=lambda value: value.encode("utf-8"))),
    )
