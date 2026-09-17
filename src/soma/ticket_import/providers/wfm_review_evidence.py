from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from soma.foundation.errors import IntegrityFailure, SomaError
from soma.foundation.identifiers import require_uuid4
from soma.objectives_tasks.services.wfm_import import WfmImportBaseTarget, WfmImportReader
from soma.ticket_import.profiles import require_profile_versions
from soma.ticket_import.reconciliation.wfm_service_provider import (
    _SourceField,
    _SourceObservation,
    _desired_source_projection,
    _lifecycle_from_source,
    _source_projection_changes,
)
from soma.tickets.rfc_import_reader import RfcImportReader

_PUBLISHED_RUN_STATES = frozenset(
    {"staged", "waiting_review", "recovery_required", "partially_accepted", "accepted", "rejected"}
)


@dataclass(frozen=True, slots=True)
class ReviewedWfmCreateCandidate:
    task_no: str
    rfc_no: str
    rfc_id: str
    source_lifecycle_class: str
    base_state_token: str


@dataclass(frozen=True, slots=True)
class ReviewedWfmSourceProjectionCandidate:
    task_id: str
    task_no: str
    rfc_no: str
    rfc_id: str
    expected_source_projection_revision: int
    provider_status_token: str | None
    provider_lifecycle_class: str
    source_plan_start_utc: int | None
    source_plan_end_utc: int | None
    source_observation_id: str
    base_state_token: str
    changes: tuple[object, ...]


def _load_published_source(
    reader: Any,
    *,
    expected_import_run_id: str,
    expected_source_observation_id: str,
) -> _SourceObservation:
    run_id = require_uuid4(expected_import_run_id)
    observation_id = require_uuid4(expected_source_observation_id)
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
        raise SomaError("IMPORT_PROPOSAL_STALE", "WFM proposal source observation no longer exists")
    if (
        str(row[8]) not in _PUBLISHED_RUN_STATES
        or str(row[9]) != "wfm_service_provider"
        or str(row[10]) != "wfm_service_provider"
        or str(row[11]) != "wfm"
        or str(row[12]) != "valid"
        or row[0] is None
        or row[1] is None
    ):
        raise SomaError("IMPORT_PROPOSAL_STALE", "WFM proposal source observation is no longer published valid authority")
    if (
        str(row[4]) != versions.source_profile_id
        or str(row[5]) != versions.header_registry_id
        or str(row[6]) != versions.vocabulary_registry_id
        or str(row[7]) != versions.parser_profile_id
    ):
        raise SomaError("IMPORT_PROPOSAL_STALE", "WFM proposal source profile versions changed")

    field_rows = reader.execute(
        "SELECT source_observation_field_id,field_key,field_class,value_state,value_kind,source_text,normalized_text,"
        "integer_value,vocabulary_id,field_logical_sha256 FROM source_observation_fields "
        "WHERE source_observation_id=? ORDER BY field_key,source_observation_field_id",
        (observation_id,),
    ).fetchall()
    fields: list[_SourceField] = []
    seen: set[str] = set()
    for field_row in field_rows:
        key = str(field_row[1])
        if key in seen:
            raise IntegrityFailure("published WFM observation repeats a semantic field")
        seen.add(key)
        value_state = str(field_row[3])
        value_kind = str(field_row[4])
        normalized_text = None if field_row[6] is None else str(field_row[6])
        integer_value = None if field_row[7] is None else int(field_row[7])
        if value_state == "usable":
            if value_kind in {"text", "controlled"} and (normalized_text is None or integer_value is not None):
                raise IntegrityFailure("published usable WFM text authority is invalid")
            if value_kind == "instant" and (normalized_text is not None or integer_value is None):
                raise IntegrityFailure("published usable WFM instant authority is invalid")
        elif normalized_text is not None or integer_value is not None:
            raise IntegrityFailure("published non-usable WFM evidence carries normalized authority")
        fields.append(
            _SourceField(
                source_observation_field_id=str(field_row[0]),
                field_key=key,
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


class TicketImportWfmReviewEvidenceProvider:
    """Writer-side revalidation of reviewed WFM identity and source-projection proposals."""

    def __init__(self) -> None:
        self._rfc_reader = RfcImportReader()

    def _resolve_parent_rfc(self, reader: Any, source: _SourceObservation) -> str:
        rfc = self._rfc_reader.get_by_number(reader, source.canonical_parent_rfc_no)
        if rfc is None or not isinstance(rfc.get("rfc_id"), str):
            raise SomaError("IMPORT_PROPOSAL_STALE", "reviewed WFM parent RFC no longer resolves")
        rfc_id = require_uuid4(str(rfc["rfc_id"]))
        if rfc.get("rfc_no") != source.canonical_parent_rfc_no:
            raise IntegrityFailure("RFC import reader returned mismatched WFM parent identity")
        return rfc_id

    def revalidate_create_candidate(
        self,
        reader: Any,
        *,
        expected_import_run_id: str,
        expected_source_observation_id: str,
        expected_task_no: str,
        expected_parent_rfc_no: str,
    ) -> ReviewedWfmCreateCandidate:
        source = _load_published_source(
            reader,
            expected_import_run_id=expected_import_run_id,
            expected_source_observation_id=expected_source_observation_id,
        )
        if source.canonical_task_no != expected_task_no or source.canonical_parent_rfc_no != expected_parent_rfc_no:
            raise SomaError("IMPORT_PROPOSAL_STALE", "reviewed WFM source identity changed")
        if WfmImportReader.task_no_status(reader, expected_task_no) != "ABSENT":
            raise SomaError("IMPORT_PROPOSAL_STALE", "reviewed WFM Task No is no longer absent")
        rfc_id = self._resolve_parent_rfc(reader, source)
        _status_token, lifecycle, _status_field = _lifecycle_from_source(source)
        base = WfmImportReader.source_acceptance_base_token(
            reader,
            WfmImportBaseTarget("wfm_create_or_adopt", expected_task_no, None),
        )
        return ReviewedWfmCreateCandidate(
            task_no=expected_task_no,
            rfc_no=expected_parent_rfc_no,
            rfc_id=rfc_id,
            source_lifecycle_class=lifecycle,
            base_state_token=base,
        )

    def revalidate_source_projection_candidate(
        self,
        reader: Any,
        *,
        expected_import_run_id: str,
        expected_source_observation_id: str,
        expected_task_id: str,
        expected_task_no: str,
        expected_parent_rfc_no: str,
    ) -> ReviewedWfmSourceProjectionCandidate:
        task_id = require_uuid4(expected_task_id)
        source = _load_published_source(
            reader,
            expected_import_run_id=expected_import_run_id,
            expected_source_observation_id=expected_source_observation_id,
        )
        if source.canonical_task_no != expected_task_no or source.canonical_parent_rfc_no != expected_parent_rfc_no:
            raise SomaError("IMPORT_PROPOSAL_STALE", "reviewed WFM source identity changed")
        if WfmImportReader.task_no_status(reader, expected_task_no) != "ACTIVE":
            raise SomaError("IMPORT_PROPOSAL_STALE", "reviewed WFM Task No is no longer active")
        identity = WfmImportReader.get_by_task_no(reader, expected_task_no)
        if identity is None or identity.get("task_id") != task_id:
            raise SomaError("IMPORT_PROPOSAL_STALE", "reviewed WFM Task identity changed")
        rfc_id = self._resolve_parent_rfc(reader, source)
        if identity.get("current_rfc_id") != rfc_id:
            raise SomaError("IMPORT_PROPOSAL_STALE", "reviewed WFM parent RFC assignment changed")

        current = WfmImportReader.source_projection(reader, task_id)
        desired_status, desired_lifecycle, desired_start, desired_end = _desired_source_projection(source, current)
        changes = _source_projection_changes(
            source=source,
            current=current,
            desired_status_token=desired_status,
            desired_lifecycle=desired_lifecycle,
            desired_start=desired_start,
            desired_end=desired_end,
        )
        if not changes:
            raise SomaError("IMPORT_PROPOSAL_STALE", "reviewed WFM source projection is no longer a material change")
        base = WfmImportReader.source_acceptance_base_token(
            reader,
            WfmImportBaseTarget("wfm_source_projection", expected_task_no, task_id),
        )
        return ReviewedWfmSourceProjectionCandidate(
            task_id=task_id,
            task_no=expected_task_no,
            rfc_no=expected_parent_rfc_no,
            rfc_id=rfc_id,
            expected_source_projection_revision=0 if current is None else int(current["source_projection_revision"]),
            provider_status_token=desired_status,
            provider_lifecycle_class=desired_lifecycle,
            source_plan_start_utc=desired_start,
            source_plan_end_utc=desired_end,
            source_observation_id=source.source_observation_id,
            base_state_token=base,
            changes=changes,
        )
