from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

from soma.foundation.errors import SomaError, ValidationError
from soma.foundation.identifiers import new_uuid4, utc_epoch_seconds
from soma.foundation.persistence.uow import UnitOfWork

from ..profiles.registry import require_field_spec, require_profile_ids


_HEX64 = re.compile(r"[0-9a-f]{64}\Z")
_SR_NO = re.compile(r"[0-9]{8}\Z")
_RFC_NO = re.compile(r"NC[0-9]{14}\Z")
_WFM_NO = re.compile(r"TK[0-9]{14}\Z")
_MAX_BATCH_OBSERVATIONS = 2_000
_MAX_FIELDS_PER_OBSERVATION = 64


@dataclass(frozen=True, slots=True)
class NormalizedFieldEvidence:
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
class NormalizedObservationEvidence:
    entity_kind: str
    identity_state: str
    canonical_primary_id: str | None
    canonical_parent_rfc_no: str | None
    row_ordinal: int
    sheet_ordinal: int
    row_logical_sha256: str
    source_row_chronology_utc: int | None
    fields: tuple[NormalizedFieldEvidence, ...] = ()


@dataclass(frozen=True, slots=True)
class StagedObservationResult:
    source_observation_id: str
    field_ids: tuple[str, ...]


def _validate_sha256(value: str, label: str) -> None:
    if not isinstance(value, str) or _HEX64.fullmatch(value) is None:
        raise ValidationError(f"{label} must be lowercase SHA-256 hex")


def _validate_text(value: str | None, *, max_utf8_bytes: int, max_lines: int, label: str) -> None:
    if value is None:
        return
    if not isinstance(value, str) or "\x00" in value:
        raise ValidationError(f"{label} must be valid NUL-free text")
    try:
        encoded = value.encode("utf-8", errors="strict")
    except UnicodeEncodeError as exc:
        raise ValidationError(f"{label} must be valid Unicode text") from exc
    if len(encoded) > max_utf8_bytes:
        raise ValidationError(f"{label} exceeds the source-profile byte ceiling")
    if max_lines == 1 and ("\r" in value or "\n" in value):
        raise ValidationError(f"{label} must be one line")
    if value.count("\n") + 1 > max_lines:
        raise ValidationError(f"{label} exceeds the source-profile line ceiling")


def _validate_identity(source_family: str, observation: NormalizedObservationEvidence) -> None:
    if observation.identity_state == "invalid":
        if (
            observation.entity_kind != "invalid_row"
            or observation.canonical_primary_id is not None
            or observation.canonical_parent_rfc_no is not None
        ):
            raise ValidationError("invalid source rows cannot carry canonical identity")
        return
    if observation.identity_state != "valid":
        raise ValidationError("identity_state must be valid or invalid")
    identity = observation.canonical_primary_id
    if source_family == "advanced_search_sr":
        if observation.entity_kind != "service_request" or identity is None or _SR_NO.fullmatch(identity) is None:
            raise ValidationError("Advanced Search valid identity must be exactly eight ASCII digits")
        if observation.canonical_parent_rfc_no is not None:
            raise ValidationError("Service Request observations cannot carry a parent RFC")
    elif source_family == "rfc_enhanced":
        if observation.entity_kind != "rfc" or identity is None or _RFC_NO.fullmatch(identity) is None:
            raise ValidationError("RFC source identity must be exact NC+14 ASCII digits")
        if observation.canonical_parent_rfc_no is not None:
            raise ValidationError("RFC observations cannot carry a parent RFC")
    elif source_family == "wfm_service_provider":
        parent = observation.canonical_parent_rfc_no
        if (
            observation.entity_kind != "wfm"
            or identity is None
            or _WFM_NO.fullmatch(identity) is None
            or parent is None
            or _RFC_NO.fullmatch(parent) is None
        ):
            raise ValidationError("WFM identity requires exact TK+14 and owning NC+14")
    else:
        raise SomaError("IMPORT_SOURCE_FAMILY_INVALID", "source family is outside the closed LLD-04 registry")


def _validate_field(source_family: str, field: NormalizedFieldEvidence) -> None:
    spec = require_field_spec(source_family, field.field_key)
    if field.field_class != spec.field_class or field.value_kind != spec.value_kind:
        raise SomaError("IMPORT_SOURCE_PROFILE_MISMATCH", "normalized field class/kind disagrees with source profile")
    if field.value_state not in {"usable", "blank", "unknown", "malformed"}:
        raise ValidationError("field value_state is outside the closed staging vocabulary")
    if field.vocabulary_id != spec.vocabulary_id:
        raise SomaError("IMPORT_SOURCE_PROFILE_MISMATCH", "normalized controlled-field vocabulary disagrees with source profile")
    _validate_sha256(field.field_logical_sha256, "field_logical_sha256")
    _validate_text(
        field.source_text,
        max_utf8_bytes=spec.max_utf8_bytes,
        max_lines=spec.max_lines,
        label=field.field_key,
    )
    if field.normalized_text is not None:
        _validate_text(
            field.normalized_text,
            max_utf8_bytes=spec.max_utf8_bytes,
            max_lines=spec.max_lines,
            label=f"{field.field_key} normalized value",
        )
    if field.value_state == "usable":
        if field.source_text is None:
            raise ValidationError("usable source field requires bounded source_text evidence")
        if field.value_kind in {"text", "controlled"}:
            if field.normalized_text is None or field.integer_value is not None:
                raise ValidationError("usable text/controlled field requires normalized_text only")
        else:
            if field.normalized_text is not None or type(field.integer_value) is not int or field.integer_value < 0:
                raise ValidationError("usable instant/duration field requires a nonnegative integer value only")
    elif field.normalized_text is not None or field.integer_value is not None:
        raise ValidationError("non-usable source fields cannot carry normalized authority")


class SourceObservationRepository:
    """LLD-04-only persistence for unpublished normalized parser evidence."""

    @staticmethod
    def _require_validating_run(
        reader: Any,
        import_run_id: str,
        *,
        expected_revision: int,
    ) -> tuple[str, str]:
        row = reader.execute(
            "SELECT source_family,source_profile_id,header_registry_id,run_state,revision "
            "FROM import_runs WHERE import_run_id=?",
            (import_run_id,),
        ).fetchone()
        if row is None:
            raise SomaError("IMPORT_RUN_NOT_FOUND", "import run does not exist")
        if str(row[3]) != "validating" or int(row[4]) != expected_revision:
            raise SomaError("IMPORT_RUN_STALE", "import run is no longer the expected validating run")
        source_family = str(row[0])
        expected_profile, expected_headers = require_profile_ids(source_family)
        if str(row[1]) != expected_profile or str(row[2]) != expected_headers:
            raise SomaError("IMPORT_SOURCE_PROFILE_MISMATCH", "import run profile/header registry is not the accepted version")
        return source_family, str(row[1])

    @classmethod
    def stage_observations(
        cls,
        uow: UnitOfWork,
        *,
        import_run_id: str,
        expected_run_revision: int,
        observations: tuple[NormalizedObservationEvidence, ...],
    ) -> tuple[StagedObservationResult, ...]:
        if not observations or len(observations) > _MAX_BATCH_OBSERVATIONS:
            raise ValidationError("staging batch must contain 1..2000 observations")
        source_family, _profile = cls._require_validating_run(
            uow.connection,
            import_run_id,
            expected_revision=expected_run_revision,
        )
        seen_locator: set[tuple[int, int]] = set()
        for observation in observations:
            if type(observation.row_ordinal) is not int or observation.row_ordinal < 1:
                raise ValidationError("row_ordinal must be a positive integer")
            if type(observation.sheet_ordinal) is not int or observation.sheet_ordinal < 1:
                raise ValidationError("sheet_ordinal must be a positive integer")
            if observation.source_row_chronology_utc is not None and (
                type(observation.source_row_chronology_utc) is not int
                or observation.source_row_chronology_utc < 0
            ):
                raise ValidationError("source_row_chronology_utc must be a nonnegative whole-second instant")
            _validate_sha256(observation.row_logical_sha256, "row_logical_sha256")
            _validate_identity(source_family, observation)
            locator = (observation.sheet_ordinal, observation.row_ordinal)
            if locator in seen_locator:
                raise ValidationError("one staging batch cannot repeat a physical row locator")
            seen_locator.add(locator)
            if len(observation.fields) > _MAX_FIELDS_PER_OBSERVATION:
                raise ValidationError("source observation exceeds the bounded semantic-field count")
            keys: set[str] = set()
            for field in observation.fields:
                if field.field_key in keys:
                    raise SomaError("SOURCE_DUPLICATE_SEMANTIC_HEADER", "source observation repeats a canonical field")
                keys.add(field.field_key)
                _validate_field(source_family, field)

        now = utc_epoch_seconds()
        results: list[StagedObservationResult] = []
        for observation in observations:
            observation_id = new_uuid4()
            uow.connection.execute(
                "INSERT INTO source_observations("
                "source_observation_id,import_run_id,source_family,entity_kind,identity_state,canonical_primary_id,"
                "canonical_parent_rfc_no,row_ordinal,sheet_ordinal,row_logical_sha256,source_row_chronology_utc,"
                "presence_state,recorded_at_utc) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (
                    observation_id,
                    import_run_id,
                    source_family,
                    observation.entity_kind,
                    observation.identity_state,
                    observation.canonical_primary_id,
                    observation.canonical_parent_rfc_no,
                    observation.row_ordinal,
                    observation.sheet_ordinal,
                    observation.row_logical_sha256,
                    observation.source_row_chronology_utc,
                    "observed_valid_identity" if observation.identity_state == "valid" else "observed_invalid_identity",
                    now,
                ),
            )
            field_ids: list[str] = []
            for field in observation.fields:
                field_id = new_uuid4()
                uow.connection.execute(
                    "INSERT INTO source_observation_fields("
                    "source_observation_field_id,source_observation_id,field_key,field_class,value_state,value_kind,"
                    "source_text,normalized_text,integer_value,vocabulary_id,field_logical_sha256) "
                    "VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                    (
                        field_id,
                        observation_id,
                        field.field_key,
                        field.field_class,
                        field.value_state,
                        field.value_kind,
                        field.source_text,
                        field.normalized_text,
                        field.integer_value,
                        field.vocabulary_id,
                        field.field_logical_sha256,
                    ),
                )
                field_ids.append(field_id)
            results.append(StagedObservationResult(observation_id, tuple(field_ids)))
        return tuple(results)

    @staticmethod
    def cleanup_unpublished(
        uow: UnitOfWork,
        *,
        import_run_id: str,
        expected_run_revision: int,
    ) -> None:
        SourceObservationRepository._require_validating_run(
            uow.connection,
            import_run_id,
            expected_revision=expected_run_revision,
        )
        uow.connection.execute("DELETE FROM import_findings WHERE import_run_id=?", (import_run_id,))
        uow.connection.execute(
            "DELETE FROM source_observation_fields WHERE source_observation_id IN "
            "(SELECT source_observation_id FROM source_observations WHERE import_run_id=?)",
            (import_run_id,),
        )
        uow.connection.execute("DELETE FROM source_observations WHERE import_run_id=?", (import_run_id,))
