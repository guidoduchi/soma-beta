from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

from soma.foundation.errors import IntegrityFailure, SomaError, ValidationError
from soma.foundation.identifiers import new_uuid4, require_uuid4, utc_epoch_seconds
from soma.foundation.persistence.uow import UnitOfWork

from ..profiles.registry import require_field_spec, require_profile_versions


_HEX64 = re.compile(r"[0-9a-f]{64}\Z")
_SR_NO = re.compile(r"[0-9]{8}\Z")
_RFC_NO = re.compile(r"NC[0-9]{14}\Z")
_WFM_NO = re.compile(r"TK[0-9]{14}\Z")
_MAX_BATCH_OBSERVATIONS = 2_000
_MAX_FIELDS_PER_OBSERVATION = 64
_FINDING_SEVERITIES = frozenset({"info", "warning", "error", "high_risk"})
_FINDING_SCOPES = frozenset(
    {"workbook", "sheet", "row", "field", "identity", "chronology", "replay", "proposal", "population"}
)


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


@dataclass(frozen=True, slots=True)
class StagedFieldEvidence:
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

    def normalized(self) -> NormalizedFieldEvidence:
        return NormalizedFieldEvidence(
            field_key=self.field_key,
            field_class=self.field_class,
            value_state=self.value_state,
            value_kind=self.value_kind,
            source_text=self.source_text,
            normalized_text=self.normalized_text,
            integer_value=self.integer_value,
            vocabulary_id=self.vocabulary_id,
            field_logical_sha256=self.field_logical_sha256,
        )


@dataclass(frozen=True, slots=True)
class StagedFindingEvidence:
    import_finding_id: str
    source_observation_id: str | None
    field_key: str | None
    finding_code: str
    severity: str
    scope_kind: str
    message_text: str
    recorded_at_utc: int


@dataclass(frozen=True, slots=True)
class StagedObservationEvidence:
    source_observation_id: str
    source_family: str
    entity_kind: str
    identity_state: str
    canonical_primary_id: str | None
    canonical_parent_rfc_no: str | None
    row_ordinal: int
    sheet_ordinal: int
    row_logical_sha256: str
    source_row_chronology_utc: int | None
    presence_state: str
    recorded_at_utc: int
    fields: tuple[StagedFieldEvidence, ...]
    findings: tuple[StagedFindingEvidence, ...]

    def normalized(self) -> NormalizedObservationEvidence:
        return NormalizedObservationEvidence(
            entity_kind=self.entity_kind,
            identity_state=self.identity_state,
            canonical_primary_id=self.canonical_primary_id,
            canonical_parent_rfc_no=self.canonical_parent_rfc_no,
            row_ordinal=self.row_ordinal,
            sheet_ordinal=self.sheet_ordinal,
            row_logical_sha256=self.row_logical_sha256,
            source_row_chronology_utc=self.source_row_chronology_utc,
            fields=tuple(field.normalized() for field in self.fields),
        )


@dataclass(frozen=True, slots=True)
class StagedRunEvidence:
    import_run_id: str
    source_family: str
    source_profile_id: str
    header_registry_id: str
    vocabulary_registry_id: str
    parser_profile_id: str
    candidate_chronology_kind: str
    candidate_chronology_value: int
    revision: int
    observations: tuple[StagedObservationEvidence, ...]
    global_findings: tuple[StagedFindingEvidence, ...]


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


def _require_persisted_uuid(value: object, *, label: str) -> str:
    try:
        return require_uuid4(str(value))
    except ValidationError as exc:
        raise IntegrityFailure(f"persisted {label} is not a canonical UUID4") from exc


def _validate_persisted_observation(source_family: str, observation: NormalizedObservationEvidence) -> None:
    try:
        _validate_sha256(observation.row_logical_sha256, "row_logical_sha256")
        _validate_identity(source_family, observation)
    except ValidationError as exc:
        raise IntegrityFailure("persisted staged observation violates normalized evidence contract") from exc


def _validate_persisted_field(source_family: str, field: NormalizedFieldEvidence) -> None:
    try:
        _validate_field(source_family, field)
    except ValidationError as exc:
        raise IntegrityFailure("persisted staged field violates normalized evidence contract") from exc


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
            "SELECT source_family,source_profile_id,header_registry_id,vocabulary_registry_id,parser_profile_id,"
            "run_state,revision FROM import_runs WHERE import_run_id=?",
            (import_run_id,),
        ).fetchone()
        if row is None:
            raise SomaError("IMPORT_RUN_NOT_FOUND", "import run does not exist")
        if str(row[5]) != "validating" or int(row[6]) != expected_revision:
            raise SomaError("IMPORT_RUN_STALE", "import run is no longer the expected validating run")
        source_family = str(row[0])
        expected = require_profile_versions(source_family)
        if (
            str(row[1]) != expected.source_profile_id
            or str(row[2]) != expected.header_registry_id
            or str(row[3]) != expected.vocabulary_registry_id
            or str(row[4]) != expected.parser_profile_id
        ):
            raise SomaError("IMPORT_SOURCE_PROFILE_MISMATCH", "import run profile registry versions are not accepted")
        return source_family, str(row[1])

    @classmethod
    def load_validating_evidence(
        cls,
        reader: Any,
        *,
        import_run_id: str,
        expected_run_revision: int,
    ) -> StagedRunEvidence:
        canonical_run_id = require_uuid4(import_run_id)
        if type(expected_run_revision) is not int or expected_run_revision < 1:
            raise ValidationError("expected_run_revision must be a positive integer")
        row = reader.execute(
            "SELECT source_family,source_profile_id,header_registry_id,vocabulary_registry_id,parser_profile_id,"
            "candidate_chronology_kind,candidate_chronology_value,run_state,revision "
            "FROM import_runs WHERE import_run_id=?",
            (canonical_run_id,),
        ).fetchone()
        if row is None:
            raise SomaError("IMPORT_RUN_NOT_FOUND", "import run does not exist")
        source_family = str(row[0])
        if str(row[7]) != "validating" or int(row[8]) != expected_run_revision:
            raise SomaError("IMPORT_RUN_STALE", "import run is no longer the expected validating evidence source")
        expected = require_profile_versions(source_family)
        profile_values = tuple(str(row[index]) for index in range(1, 5))
        if profile_values != (
            expected.source_profile_id,
            expected.header_registry_id,
            expected.vocabulary_registry_id,
            expected.parser_profile_id,
        ):
            raise SomaError("IMPORT_SOURCE_PROFILE_MISMATCH", "import run profile registry versions are not accepted")
        chronology_kind = str(row[5])
        chronology_value = int(row[6])
        if chronology_kind not in {"filesystem_mtime_ns", "embedded_filename_timestamp_utc"} or chronology_value < 0:
            raise IntegrityFailure("validating import run chronology authority is invalid")

        observation_rows = reader.execute(
            "SELECT source_observation_id,source_family,entity_kind,identity_state,canonical_primary_id,"
            "canonical_parent_rfc_no,row_ordinal,sheet_ordinal,row_logical_sha256,source_row_chronology_utc,"
            "presence_state,recorded_at_utc FROM source_observations WHERE import_run_id=? "
            "ORDER BY sheet_ordinal ASC,row_ordinal ASC,source_observation_id ASC",
            (canonical_run_id,),
        ).fetchall()
        observation_order: list[str] = []
        observation_base: dict[str, tuple[object, ...]] = {}
        seen_locators: set[tuple[int, int]] = set()
        for persisted in observation_rows:
            observation_id = _require_persisted_uuid(persisted[0], label="source_observation_id")
            if observation_id in observation_base:
                raise IntegrityFailure("validating import run repeats source observation identity")
            persisted_family = str(persisted[1])
            if persisted_family != source_family:
                raise IntegrityFailure("staged observation source family disagrees with parent import run")
            row_ordinal = int(persisted[6])
            sheet_ordinal = int(persisted[7])
            locator = (sheet_ordinal, row_ordinal)
            if locator in seen_locators:
                raise IntegrityFailure("validating import run repeats one physical worksheet row locator")
            seen_locators.add(locator)
            source_row_chronology = None if persisted[9] is None else int(persisted[9])
            if row_ordinal < 1 or sheet_ordinal < 1 or (
                source_row_chronology is not None and source_row_chronology < 0
            ):
                raise IntegrityFailure("staged observation physical or chronology provenance is invalid")
            normalized = NormalizedObservationEvidence(
                entity_kind=str(persisted[2]),
                identity_state=str(persisted[3]),
                canonical_primary_id=None if persisted[4] is None else str(persisted[4]),
                canonical_parent_rfc_no=None if persisted[5] is None else str(persisted[5]),
                row_ordinal=row_ordinal,
                sheet_ordinal=sheet_ordinal,
                row_logical_sha256=str(persisted[8]),
                source_row_chronology_utc=source_row_chronology,
            )
            _validate_persisted_observation(source_family, normalized)
            expected_presence = (
                "observed_valid_identity" if normalized.identity_state == "valid" else "observed_invalid_identity"
            )
            if str(persisted[10]) != expected_presence or int(persisted[11]) < 0:
                raise IntegrityFailure("staged observation presence or recorded-time authority is invalid")
            observation_order.append(observation_id)
            observation_base[observation_id] = tuple(persisted)

        fields_by_observation: dict[str, list[StagedFieldEvidence]] = {
            observation_id: [] for observation_id in observation_order
        }
        field_rows = reader.execute(
            "SELECT f.source_observation_field_id,f.source_observation_id,f.field_key,f.field_class,f.value_state,"
            "f.value_kind,f.source_text,f.normalized_text,f.integer_value,f.vocabulary_id,f.field_logical_sha256 "
            "FROM source_observation_fields f JOIN source_observations o "
            "ON o.source_observation_id=f.source_observation_id WHERE o.import_run_id=? "
            "ORDER BY o.sheet_ordinal ASC,o.row_ordinal ASC,o.source_observation_id ASC,f.field_key ASC",
            (canonical_run_id,),
        ).fetchall()
        for persisted in field_rows:
            field_id = _require_persisted_uuid(persisted[0], label="source_observation_field_id")
            observation_id = _require_persisted_uuid(persisted[1], label="field source_observation_id")
            if observation_id not in fields_by_observation:
                raise IntegrityFailure("staged field is not owned by the validating import run")
            field = StagedFieldEvidence(
                source_observation_field_id=field_id,
                field_key=str(persisted[2]),
                field_class=str(persisted[3]),
                value_state=str(persisted[4]),
                value_kind=str(persisted[5]),
                source_text=None if persisted[6] is None else str(persisted[6]),
                normalized_text=None if persisted[7] is None else str(persisted[7]),
                integer_value=None if persisted[8] is None else int(persisted[8]),
                vocabulary_id=None if persisted[9] is None else str(persisted[9]),
                field_logical_sha256=str(persisted[10]),
            )
            _validate_persisted_field(source_family, field.normalized())
            fields_by_observation[observation_id].append(field)
        if any(len(fields) > _MAX_FIELDS_PER_OBSERVATION for fields in fields_by_observation.values()):
            raise IntegrityFailure("staged observation exceeds the bounded semantic-field count")

        findings_by_observation: dict[str, list[StagedFindingEvidence]] = {
            observation_id: [] for observation_id in observation_order
        }
        global_findings: list[StagedFindingEvidence] = []
        finding_rows = reader.execute(
            "SELECT import_finding_id,source_observation_id,field_key,finding_code,severity,scope_kind,message_text,recorded_at_utc "
            "FROM import_findings WHERE import_run_id=? ORDER BY import_finding_id ASC",
            (canonical_run_id,),
        ).fetchall()
        for persisted in finding_rows:
            finding_id = _require_persisted_uuid(persisted[0], label="import_finding_id")
            observation_id = None if persisted[1] is None else _require_persisted_uuid(
                persisted[1], label="finding source_observation_id"
            )
            severity = str(persisted[4])
            scope_kind = str(persisted[5])
            message_text = str(persisted[6])
            recorded_at = int(persisted[7])
            if severity not in _FINDING_SEVERITIES or scope_kind not in _FINDING_SCOPES:
                raise IntegrityFailure("staged finding severity or scope is outside the closed LLD-04 vocabulary")
            if not message_text or "\x00" in message_text or recorded_at < 0:
                raise IntegrityFailure("staged finding message or recorded-time authority is invalid")
            field_key = None if persisted[2] is None else str(persisted[2])
            finding_code = str(persisted[3])
            if not finding_code or "\x00" in finding_code or (field_key is not None and "\x00" in field_key):
                raise IntegrityFailure("staged finding semantic identity is invalid")
            finding = StagedFindingEvidence(
                import_finding_id=finding_id,
                source_observation_id=observation_id,
                field_key=field_key,
                finding_code=finding_code,
                severity=severity,
                scope_kind=scope_kind,
                message_text=message_text,
                recorded_at_utc=recorded_at,
            )
            if observation_id is None:
                global_findings.append(finding)
            else:
                target = findings_by_observation.get(observation_id)
                if target is None:
                    raise IntegrityFailure("staged finding links an observation outside its import run")
                target.append(finding)

        observations: list[StagedObservationEvidence] = []
        for observation_id in observation_order:
            persisted = observation_base[observation_id]
            observations.append(
                StagedObservationEvidence(
                    source_observation_id=observation_id,
                    source_family=str(persisted[1]),
                    entity_kind=str(persisted[2]),
                    identity_state=str(persisted[3]),
                    canonical_primary_id=None if persisted[4] is None else str(persisted[4]),
                    canonical_parent_rfc_no=None if persisted[5] is None else str(persisted[5]),
                    row_ordinal=int(persisted[6]),
                    sheet_ordinal=int(persisted[7]),
                    row_logical_sha256=str(persisted[8]),
                    source_row_chronology_utc=None if persisted[9] is None else int(persisted[9]),
                    presence_state=str(persisted[10]),
                    recorded_at_utc=int(persisted[11]),
                    fields=tuple(fields_by_observation[observation_id]),
                    findings=tuple(findings_by_observation[observation_id]),
                )
            )
        return StagedRunEvidence(
            import_run_id=canonical_run_id,
            source_family=source_family,
            source_profile_id=profile_values[0],
            header_registry_id=profile_values[1],
            vocabulary_registry_id=profile_values[2],
            parser_profile_id=profile_values[3],
            candidate_chronology_kind=chronology_kind,
            candidate_chronology_value=chronology_value,
            revision=expected_run_revision,
            observations=tuple(observations),
            global_findings=tuple(global_findings),
        )

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
