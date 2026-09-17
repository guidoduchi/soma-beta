from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from soma.foundation.errors import IntegrityFailure
from soma.foundation.identifiers import require_uuid4
from soma.foundation.strict_json import sha256_canonical_json
from soma.objectives_tasks.services.wfm_import import WfmImportBaseTarget, WfmImportReader
from soma.tickets.rfc_import_reader import RfcImportReader

from ..profiles import require_profile_versions
from .engine import ProposalChangeDraft, ReconciliationProposalDraft

_PROPOSAL_FINGERPRINT_SCHEMA = "SOMA_IMPORT_PROPOSAL_FINGERPRINT_V1"
_PUBLISHED_BUILD_STATE = "validating"
_TASK_STATUS_VOCABULARY = "WFM_TASK_STATUS_V1"


@dataclass(frozen=True, slots=True)
class _SourceField:
    source_observation_field_id: str
    field_key: str
    field_class: str
    value_state: str
    value_kind: str
    source_text: str | None
    normalized_text: str | None
    integer_value: int | None
    vocabulary_id: str | None
    field_logical_sha256: str


@dataclass(frozen=True, slots=True)
class _SourceObservation:
    import_run_id: str
    source_observation_id: str
    canonical_task_no: str
    canonical_parent_rfc_no: str
    row_logical_sha256: str
    source_row_chronology_utc: int | None
    source_profile_id: str
    header_registry_id: str
    vocabulary_registry_id: str
    parser_profile_id: str
    fields: tuple[_SourceField, ...]


@dataclass(frozen=True, slots=True)
class WfmServiceProviderProposalBuildResult:
    canonical_task_no: str
    canonical_parent_rfc_no: str
    task_no_status: str
    task_id: str | None
    rfc_id: str | None
    scope_status: str
    resolution_state: str
    blocked_finding_code: str | None
    proposals: tuple[ReconciliationProposalDraft, ...]


def _load_source_observation(
    reader: Any,
    *,
    import_run_id: str,
    source_observation_id: str,
) -> _SourceObservation:
    run_id = require_uuid4(import_run_id)
    observation_id = require_uuid4(source_observation_id)
    versions = require_profile_versions("wfm_service_provider")
    row = reader.execute(
        "SELECT o.canonical_primary_id,o.canonical_parent_rfc_no,o.row_logical_sha256,o.source_row_chronology_utc,"
        "r.source_profile_id,r.header_registry_id,r.vocabulary_registry_id,r.parser_profile_id,r.run_state,"
        "r.source_family,o.source_family,o.entity_kind,o.identity_state "
        "FROM source_observations o JOIN import_runs r ON r.import_run_id=o.import_run_id "
        "WHERE o.import_run_id=? AND o.source_observation_id=?",
        (run_id, observation_id),
    ).fetchone()
    if row is None:
        raise IntegrityFailure("WFM reconciliation source observation does not exist")
    if (
        str(row[8]) != _PUBLISHED_BUILD_STATE
        or str(row[9]) != "wfm_service_provider"
        or str(row[10]) != "wfm_service_provider"
        or str(row[11]) != "wfm"
        or str(row[12]) != "valid"
        or row[0] is None
        or row[1] is None
    ):
        raise IntegrityFailure("WFM reconciliation source observation is outside validating WFM authority")
    if (
        str(row[4]) != versions.source_profile_id
        or str(row[5]) != versions.header_registry_id
        or str(row[6]) != versions.vocabulary_registry_id
        or str(row[7]) != versions.parser_profile_id
    ):
        raise IntegrityFailure("WFM reconciliation source profile versions changed")

    field_rows = reader.execute(
        "SELECT source_observation_field_id,field_key,field_class,value_state,value_kind,source_text,normalized_text,"
        "integer_value,vocabulary_id,field_logical_sha256 FROM source_observation_fields "
        "WHERE source_observation_id=? ORDER BY field_key,source_observation_field_id",
        (observation_id,),
    ).fetchall()
    fields: list[_SourceField] = []
    seen_keys: set[str] = set()
    for field_row in field_rows:
        field_key = str(field_row[1])
        if field_key in seen_keys:
            raise IntegrityFailure("WFM source observation repeats a semantic field")
        seen_keys.add(field_key)
        value_state = str(field_row[3])
        value_kind = str(field_row[4])
        normalized_text = None if field_row[6] is None else str(field_row[6])
        integer_value = None if field_row[7] is None else int(field_row[7])
        if value_state == "usable":
            if value_kind in {"text", "controlled"} and (normalized_text is None or integer_value is not None):
                raise IntegrityFailure("usable WFM text evidence has invalid typed authority")
            if value_kind == "instant" and (normalized_text is not None or integer_value is None):
                raise IntegrityFailure("usable WFM instant evidence has invalid typed authority")
        elif normalized_text is not None or integer_value is not None:
            raise IntegrityFailure("non-usable WFM evidence unexpectedly carries normalized authority")
        fields.append(
            _SourceField(
                source_observation_field_id=str(field_row[0]),
                field_key=field_key,
                field_class=str(field_row[2]),
                value_state=value_state,
                value_kind=value_kind,
                source_text=None if field_row[5] is None else str(field_row[5]),
                normalized_text=normalized_text,
                integer_value=integer_value,
                vocabulary_id=None if field_row[8] is None else str(field_row[8]),
                field_logical_sha256=str(field_row[9]),
            )
        )
    return _SourceObservation(
        import_run_id=run_id,
        source_observation_id=observation_id,
        canonical_task_no=str(row[0]),
        canonical_parent_rfc_no=str(row[1]),
        row_logical_sha256=str(row[2]),
        source_row_chronology_utc=None if row[3] is None else int(row[3]),
        source_profile_id=str(row[4]),
        header_registry_id=str(row[5]),
        vocabulary_registry_id=str(row[6]),
        parser_profile_id=str(row[7]),
        fields=tuple(fields),
    )


def _scope_status(reader: Any, source: _SourceObservation) -> str:
    rows = reader.execute(
        "SELECT source_observation_id,row_logical_sha256 FROM source_observations "
        "WHERE import_run_id=? AND source_family='wfm_service_provider' AND entity_kind='wfm' "
        "AND identity_state='valid' AND canonical_primary_id=? ORDER BY source_observation_id",
        (source.import_run_id, source.canonical_task_no),
    ).fetchall()
    if not rows:
        raise IntegrityFailure("WFM reconciliation source identity disappeared")
    row_hashes = {str(row[1]) for row in rows}
    if len(row_hashes) > 1:
        return "conflict"
    if len(rows) > 1 and str(rows[0][0]) != source.source_observation_id:
        return "equivalent_duplicate_suppressed"
    return "reviewable"


def _field(source: _SourceObservation, field_key: str) -> _SourceField | None:
    return next((candidate for candidate in source.fields if candidate.field_key == field_key), None)


def _source_authority(source: _SourceObservation) -> dict[str, object]:
    return {
        "import_run_id": source.import_run_id,
        "source_family": "wfm_service_provider",
        "source_profile_id": source.source_profile_id,
        "header_registry_id": source.header_registry_id,
        "vocabulary_registry_id": source.vocabulary_registry_id,
        "parser_profile_id": source.parser_profile_id,
        "source_observation_id": source.source_observation_id,
        "canonical_primary_id": source.canonical_task_no,
        "canonical_parent_rfc_no": source.canonical_parent_rfc_no,
        "row_logical_sha256": source.row_logical_sha256,
        "source_row_chronology_utc": source.source_row_chronology_utc,
        "fields": [
            {
                "source_observation_field_id": item.source_observation_field_id,
                "field_key": item.field_key,
                "field_logical_sha256": item.field_logical_sha256,
            }
            for item in source.fields
        ],
    }


def _proposal_fingerprint(
    *,
    source: _SourceObservation,
    proposal_identity: dict[str, object],
    changes: tuple[ProposalChangeDraft, ...],
) -> str:
    return sha256_canonical_json(
        {
            "schema": _PROPOSAL_FINGERPRINT_SCHEMA,
            "source": _source_authority(source),
            "proposal": proposal_identity,
            "changes": [change.fingerprint_object() for change in changes],
        }
    )


def _lifecycle_from_source(source: _SourceObservation) -> tuple[str | None, str, _SourceField | None]:
    status = _field(source, "task_status")
    if status is None:
        return None, "unknown", None
    if status.field_class != "active" or status.value_kind != "controlled":
        raise IntegrityFailure("WFM Task Status field has invalid authority class/kind")
    if status.value_state == "usable":
        if status.vocabulary_id != _TASK_STATUS_VOCABULARY:
            raise IntegrityFailure("usable WFM Task Status is not bound to WFM_TASK_STATUS_V1")
        if status.normalized_text == "Complete":
            return "Complete", "complete", status
        if status.normalized_text == "Plan Cancel":
            return "Plan Cancel", "plan_cancel", status
        raise IntegrityFailure("usable WFM Task Status is outside the closed vocabulary")
    if status.value_state == "unknown" and status.source_text:
        return status.source_text, "active", status
    return None, "unknown", status


def _desired_source_projection(
    source: _SourceObservation,
    current: dict[str, object] | None,
) -> tuple[str | None, str, int | None, int | None]:
    source_status_token, source_lifecycle, status_field = _lifecycle_from_source(source)
    if current is None:
        current_status_token = None
        current_lifecycle = "unknown"
        current_start = None
        current_end = None
    else:
        current_status_token = current.get("provider_status_token")
        current_lifecycle = current.get("provider_lifecycle_class")
        current_start = current.get("source_plan_start_utc")
        current_end = current.get("source_plan_end_utc")
        if current_status_token is not None and not isinstance(current_status_token, str):
            raise IntegrityFailure("current WFM provider status authority is invalid")
        if current_lifecycle not in {"unknown", "active", "complete", "plan_cancel"}:
            raise IntegrityFailure("current WFM provider lifecycle authority is invalid")
        if current_start is not None and type(current_start) is not int:
            raise IntegrityFailure("current WFM source-plan start authority is invalid")
        if current_end is not None and type(current_end) is not int:
            raise IntegrityFailure("current WFM source-plan end authority is invalid")

    if status_field is None:
        desired_status_token = current_status_token
        desired_lifecycle = current_lifecycle
    elif status_field.value_state == "usable":
        desired_status_token = source_status_token
        desired_lifecycle = source_lifecycle
    elif status_field.value_state == "unknown" and source_status_token is not None:
        if current_lifecycle in {"complete", "plan_cancel"}:
            desired_status_token = current_status_token
            desired_lifecycle = current_lifecycle
        else:
            desired_status_token = source_status_token
            desired_lifecycle = "active"
    else:
        desired_status_token = current_status_token
        desired_lifecycle = current_lifecycle

    planned_start = _field(source, "planned_start")
    planned_end = _field(source, "planned_end")
    if planned_start is None and planned_end is None:
        desired_start, desired_end = current_start, current_end
    elif planned_start is None or planned_end is None:
        desired_start, desired_end = current_start, current_end
    elif planned_start.field_class != "active" or planned_end.field_class != "active":
        raise IntegrityFailure("WFM source-plan fields have invalid authority class")
    elif planned_start.value_kind != "instant" or planned_end.value_kind != "instant":
        raise IntegrityFailure("WFM source-plan fields have invalid value kind")
    elif planned_start.value_state == "blank" and planned_end.value_state == "blank":
        desired_start, desired_end = None, None
    elif planned_start.value_state == "usable" and planned_end.value_state == "usable":
        if planned_start.integer_value is None or planned_end.integer_value is None:
            raise IntegrityFailure("usable WFM source plan is missing integer authority")
        if planned_end.integer_value <= planned_start.integer_value:
            raise IntegrityFailure("usable WFM source plan interval is invalid")
        desired_start, desired_end = planned_start.integer_value, planned_end.integer_value
    else:
        desired_start, desired_end = current_start, current_end

    return desired_status_token, str(desired_lifecycle), desired_start, desired_end


def _create_proposal(
    *,
    source: _SourceObservation,
    rfc_id: str,
    base_state_token: str,
    source_lifecycle_class: str,
) -> ReconciliationProposalDraft:
    changes = (
        ProposalChangeDraft(
            ordinal=0,
            field_key="task_no",
            change_kind="create",
            value_kind="identity",
            before_text=None,
            after_text=source.canonical_task_no,
            before_integer=None,
            after_integer=None,
            source_observation_field_id=None,
        ),
        ProposalChangeDraft(
            ordinal=1,
            field_key="rfc_no",
            change_kind="link",
            value_kind="identity",
            before_text=None,
            after_text=source.canonical_parent_rfc_no,
            before_integer=None,
            after_integer=None,
            source_observation_field_id=None,
        ),
    )
    identity = {
        "proposal_kind": "wfm_create_or_adopt",
        "evidence_mode": "observed_row",
        "risk_class": "medium",
        "target_kind": "wfm",
        "target_internal_id": None,
        "target_business_id": source.canonical_task_no,
        "parent_rfc_id": rfc_id,
        "parent_rfc_no": source.canonical_parent_rfc_no,
        "source_lifecycle_class": source_lifecycle_class,
    }
    return ReconciliationProposalDraft(
        import_run_id=source.import_run_id,
        evidence_mode="observed_row",
        source_observation_id=source.source_observation_id,
        proposal_kind="wfm_create_or_adopt",
        target_kind="wfm",
        target_internal_id=None,
        target_business_id=source.canonical_task_no,
        risk_class="medium",
        base_state_token_sha256=base_state_token,
        proposal_fingerprint_sha256=_proposal_fingerprint(source=source, proposal_identity=identity, changes=changes),
        changes=changes,
    )


def _source_projection_changes(
    *,
    source: _SourceObservation,
    current: dict[str, object] | None,
    desired_status_token: str | None,
    desired_lifecycle: str,
    desired_start: int | None,
    desired_end: int | None,
) -> tuple[ProposalChangeDraft, ...]:
    current_status = None if current is None else current.get("provider_status_token")
    current_lifecycle = "unknown" if current is None else str(current.get("provider_lifecycle_class"))
    current_start = None if current is None else current.get("source_plan_start_utc")
    current_end = None if current is None else current.get("source_plan_end_utc")
    changes: list[ProposalChangeDraft] = []

    status_field = _field(source, "task_status")
    if current_status != desired_status_token or current_lifecycle != desired_lifecycle:
        changes.append(
            ProposalChangeDraft(
                ordinal=len(changes),
                field_key="task_status",
                change_kind="set" if desired_status_token is not None else "clear",
                value_kind="controlled",
                before_text=None if current_status is None else str(current_status),
                after_text=desired_status_token,
                before_integer=None,
                after_integer=None,
                source_observation_field_id=None if status_field is None else status_field.source_observation_field_id,
            )
        )

    start_field = _field(source, "planned_start")
    end_field = _field(source, "planned_end")
    if current_start != desired_start:
        changes.append(
            ProposalChangeDraft(
                ordinal=len(changes),
                field_key="planned_start",
                change_kind="set" if desired_start is not None else "clear",
                value_kind="instant",
                before_text=None,
                after_text=None,
                before_integer=None if current_start is None else int(current_start),
                after_integer=desired_start,
                source_observation_field_id=None if start_field is None else start_field.source_observation_field_id,
            )
        )
    if current_end != desired_end:
        changes.append(
            ProposalChangeDraft(
                ordinal=len(changes),
                field_key="planned_end",
                change_kind="set" if desired_end is not None else "clear",
                value_kind="instant",
                before_text=None,
                after_text=None,
                before_integer=None if current_end is None else int(current_end),
                after_integer=desired_end,
                source_observation_field_id=None if end_field is None else end_field.source_observation_field_id,
            )
        )
    return tuple(changes)


def _source_projection_proposal(
    *,
    source: _SourceObservation,
    task_id: str,
    base_state_token: str,
    current: dict[str, object] | None,
    desired_status_token: str | None,
    desired_lifecycle: str,
    desired_start: int | None,
    desired_end: int | None,
    changes: tuple[ProposalChangeDraft, ...],
) -> ReconciliationProposalDraft:
    current_revision = 0 if current is None else int(current["source_projection_revision"])
    identity = {
        "proposal_kind": "wfm_source_projection",
        "evidence_mode": "observed_row",
        "risk_class": "medium",
        "target_kind": "wfm",
        "target_internal_id": task_id,
        "target_business_id": source.canonical_task_no,
        "parent_rfc_no": source.canonical_parent_rfc_no,
        "expected_source_projection_revision": current_revision,
        "provider_status_token": desired_status_token,
        "provider_lifecycle_class": desired_lifecycle,
        "source_plan_start_utc": desired_start,
        "source_plan_end_utc": desired_end,
    }
    return ReconciliationProposalDraft(
        import_run_id=source.import_run_id,
        evidence_mode="observed_row",
        source_observation_id=source.source_observation_id,
        proposal_kind="wfm_source_projection",
        target_kind="wfm",
        target_internal_id=task_id,
        target_business_id=source.canonical_task_no,
        risk_class="medium",
        base_state_token_sha256=base_state_token,
        proposal_fingerprint_sha256=_proposal_fingerprint(source=source, proposal_identity=identity, changes=changes),
        changes=changes,
    )


def build_wfm_service_provider_proposals(
    reader: Any,
    *,
    import_run_id: str,
    source_observation_id: str,
    wfm_reader: type[WfmImportReader] = WfmImportReader,
    rfc_reader: RfcImportReader | None = None,
) -> WfmServiceProviderProposalBuildResult:
    source = _load_source_observation(
        reader,
        import_run_id=import_run_id,
        source_observation_id=source_observation_id,
    )
    scope_status = _scope_status(reader, source)
    if scope_status in {"conflict", "equivalent_duplicate_suppressed"}:
        return WfmServiceProviderProposalBuildResult(
            canonical_task_no=source.canonical_task_no,
            canonical_parent_rfc_no=source.canonical_parent_rfc_no,
            task_no_status="UNKNOWN",
            task_id=None,
            rfc_id=None,
            scope_status=scope_status,
            resolution_state="scope_blocked",
            blocked_finding_code=None,
            proposals=(),
        )

    task_no_status = wfm_reader.task_no_status(reader, source.canonical_task_no)
    if task_no_status == "RETIRED":
        return WfmServiceProviderProposalBuildResult(
            canonical_task_no=source.canonical_task_no,
            canonical_parent_rfc_no=source.canonical_parent_rfc_no,
            task_no_status=task_no_status,
            task_id=None,
            rfc_id=None,
            scope_status=scope_status,
            resolution_state="retired_blocked",
            blocked_finding_code="WFM_TASK_ID_RETIRED",
            proposals=(),
        )
    if task_no_status not in {"ACTIVE", "ABSENT"}:
        raise IntegrityFailure("LLD-05 returned an invalid WFM Task No status")

    rfc_authority = RfcImportReader() if rfc_reader is None else rfc_reader
    rfc = rfc_authority.get_by_number(reader, source.canonical_parent_rfc_no)
    if rfc is None:
        return WfmServiceProviderProposalBuildResult(
            canonical_task_no=source.canonical_task_no,
            canonical_parent_rfc_no=source.canonical_parent_rfc_no,
            task_no_status=task_no_status,
            task_id=None,
            rfc_id=None,
            scope_status=scope_status,
            resolution_state="parent_rfc_missing",
            blocked_finding_code=None,
            proposals=(),
        )
    rfc_id = rfc.get("rfc_id")
    if not isinstance(rfc_id, str):
        raise IntegrityFailure("RFC import reader returned invalid WFM parent identity")
    canonical_rfc_id = require_uuid4(rfc_id)
    if rfc.get("rfc_no") != source.canonical_parent_rfc_no:
        raise IntegrityFailure("RFC import reader returned mismatched WFM parent business identity")

    source_status_token, source_lifecycle, _status_field = _lifecycle_from_source(source)
    del source_status_token
    if task_no_status == "ABSENT":
        base_token = wfm_reader.source_acceptance_base_token(
            reader,
            WfmImportBaseTarget("wfm_create_or_adopt", source.canonical_task_no, None),
        )
        proposal = _create_proposal(
            source=source,
            rfc_id=canonical_rfc_id,
            base_state_token=base_token,
            source_lifecycle_class=source_lifecycle,
        )
        return WfmServiceProviderProposalBuildResult(
            canonical_task_no=source.canonical_task_no,
            canonical_parent_rfc_no=source.canonical_parent_rfc_no,
            task_no_status=task_no_status,
            task_id=None,
            rfc_id=canonical_rfc_id,
            scope_status=scope_status,
            resolution_state="create_review",
            blocked_finding_code=None,
            proposals=(proposal,),
        )

    identity = wfm_reader.get_by_task_no(reader, source.canonical_task_no)
    if identity is None:
        raise IntegrityFailure("ACTIVE WFM Task No does not resolve current identity")
    task_id = identity.get("task_id")
    current_rfc_id = identity.get("current_rfc_id")
    if not isinstance(task_id, str) or not isinstance(current_rfc_id, str):
        raise IntegrityFailure("WFM import reader returned invalid active identity")
    canonical_task_id = require_uuid4(task_id)
    if require_uuid4(current_rfc_id) != canonical_rfc_id:
        return WfmServiceProviderProposalBuildResult(
            canonical_task_no=source.canonical_task_no,
            canonical_parent_rfc_no=source.canonical_parent_rfc_no,
            task_no_status=task_no_status,
            task_id=canonical_task_id,
            rfc_id=canonical_rfc_id,
            scope_status=scope_status,
            resolution_state="parent_rfc_review_required",
            blocked_finding_code=None,
            proposals=(),
        )

    current_source = wfm_reader.source_projection(reader, canonical_task_id)
    desired_status, desired_lifecycle, desired_start, desired_end = _desired_source_projection(source, current_source)
    changes = _source_projection_changes(
        source=source,
        current=current_source,
        desired_status_token=desired_status,
        desired_lifecycle=desired_lifecycle,
        desired_start=desired_start,
        desired_end=desired_end,
    )
    if not changes:
        return WfmServiceProviderProposalBuildResult(
            canonical_task_no=source.canonical_task_no,
            canonical_parent_rfc_no=source.canonical_parent_rfc_no,
            task_no_status=task_no_status,
            task_id=canonical_task_id,
            rfc_id=canonical_rfc_id,
            scope_status=scope_status,
            resolution_state="no_source_change",
            blocked_finding_code=None,
            proposals=(),
        )

    base_token = wfm_reader.source_acceptance_base_token(
        reader,
        WfmImportBaseTarget("wfm_source_projection", source.canonical_task_no, canonical_task_id),
    )
    proposal = _source_projection_proposal(
        source=source,
        task_id=canonical_task_id,
        base_state_token=base_token,
        current=current_source,
        desired_status_token=desired_status,
        desired_lifecycle=desired_lifecycle,
        desired_start=desired_start,
        desired_end=desired_end,
        changes=changes,
    )
    return WfmServiceProviderProposalBuildResult(
        canonical_task_no=source.canonical_task_no,
        canonical_parent_rfc_no=source.canonical_parent_rfc_no,
        task_no_status=task_no_status,
        task_id=canonical_task_id,
        rfc_id=canonical_rfc_id,
        scope_status=scope_status,
        resolution_state="source_review",
        blocked_finding_code=None,
        proposals=(proposal,),
    )
