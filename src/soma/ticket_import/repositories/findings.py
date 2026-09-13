from __future__ import annotations

from dataclasses import dataclass

from soma.foundation.errors import SomaError, ValidationError
from soma.foundation.identifiers import new_uuid4, require_uuid4, utc_epoch_seconds
from soma.foundation.persistence.uow import UnitOfWork

from ..profiles.registry import require_profile_versions


_FINDING_SEVERITIES = frozenset({"info", "warning", "error", "high_risk"})
_FINDING_SCOPES = frozenset(
    {"workbook", "sheet", "row", "field", "identity", "chronology", "replay", "proposal", "population"}
)
_MAX_FINDING_MESSAGE_UTF8_BYTES = 2_048
_MAX_FIELD_KEY_UTF8_BYTES = 1_024
_OBSERVATION_LOOKUP_BATCH = 500

_COMMON_SOURCE_FINDING_CODES = frozenset(
    {
        "SOURCE_HEADER_COVERAGE_MISSING",
        "SOURCE_CONTROLLED_VALUE_UNKNOWN",
        "SOURCE_EQUIVALENT_DUPLICATE",
        "SOURCE_IDENTITY_CONFLICT",
    }
)
_RETAINABLE_SOURCE_FINDING_CODES_BY_FAMILY = {
    "advanced_search_sr": _COMMON_SOURCE_FINDING_CODES | frozenset({"SR_ID_INVALID"}),
    "rfc_enhanced": _COMMON_SOURCE_FINDING_CODES | frozenset({"RFC_ID_INVALID", "RFC_SOURCE_BRANCH_ARTIFACT"}),
    "wfm_service_provider": _COMMON_SOURCE_FINDING_CODES
    | frozenset(
        {
            "WFM_TASK_ID_INVALID",
            "WFM_PARENT_RFC_INVALID",
            "WFM_PLAN_INCOMPLETE",
            "WFM_PLAN_INVALID_INTERVAL",
        }
    ),
}


@dataclass(frozen=True, slots=True)
class NormalizedFindingEvidence:
    source_observation_id: str | None
    field_key: str | None
    finding_code: str
    severity: str
    scope_kind: str
    message_text: str


class SourceFindingRepository:
    """Persist unpublished source/parser findings for one validating import run."""

    @staticmethod
    def _require_validating_run(
        uow: UnitOfWork,
        *,
        import_run_id: str,
        expected_run_revision: int,
    ) -> tuple[str, str]:
        canonical_run_id = require_uuid4(import_run_id)
        if type(expected_run_revision) is not int or expected_run_revision < 1:
            raise ValidationError("expected_run_revision must be a positive integer")
        row = uow.connection.execute(
            "SELECT source_family,source_profile_id,header_registry_id,vocabulary_registry_id,parser_profile_id,"
            "run_state,revision FROM import_runs WHERE import_run_id=?",
            (canonical_run_id,),
        ).fetchone()
        if row is None:
            raise SomaError("IMPORT_RUN_NOT_FOUND", "import run does not exist")
        if str(row[5]) != "validating" or int(row[6]) != expected_run_revision:
            raise SomaError("IMPORT_RUN_STALE", "import run is no longer the expected validating run")
        source_family = str(row[0])
        expected = require_profile_versions(source_family)
        if tuple(str(row[index]) for index in range(1, 5)) != (
            expected.source_profile_id,
            expected.header_registry_id,
            expected.vocabulary_registry_id,
            expected.parser_profile_id,
        ):
            raise SomaError("IMPORT_SOURCE_PROFILE_MISMATCH", "import run profile registry versions are not accepted")
        return canonical_run_id, source_family

    @staticmethod
    def validate_finding(source_family: str, finding: NormalizedFindingEvidence) -> str | None:
        allowed_codes = _RETAINABLE_SOURCE_FINDING_CODES_BY_FAMILY.get(source_family)
        if allowed_codes is None:
            raise SomaError("IMPORT_SOURCE_FAMILY_INVALID", "source family is outside the closed LLD-04 registry")
        observation_id = None
        if finding.source_observation_id is not None:
            observation_id = require_uuid4(finding.source_observation_id)
        if finding.finding_code not in allowed_codes:
            raise SomaError(
                "IMPORT_SOURCE_PROFILE_MISMATCH",
                "finding code is outside the retainable catalogue for this source family",
            )
        if finding.severity not in _FINDING_SEVERITIES:
            raise ValidationError("finding severity is outside the closed LLD-04 vocabulary")
        if finding.scope_kind not in _FINDING_SCOPES:
            raise ValidationError("finding scope is outside the closed LLD-04 vocabulary")
        if not isinstance(finding.message_text, str) or not finding.message_text or "\x00" in finding.message_text:
            raise ValidationError("finding message must be nonempty NUL-free text")
        try:
            encoded = finding.message_text.encode("utf-8", errors="strict")
        except UnicodeEncodeError as exc:
            raise ValidationError("finding message must be valid Unicode text") from exc
        if len(encoded) > _MAX_FINDING_MESSAGE_UTF8_BYTES:
            raise ValidationError("finding message exceeds the LLD-04 UTF-8 byte ceiling")
        if finding.field_key is not None:
            if not isinstance(finding.field_key, str) or not finding.field_key or "\x00" in finding.field_key:
                raise ValidationError("finding field_key must be nonempty NUL-free text when supplied")
            try:
                encoded_field_key = finding.field_key.encode("utf-8", errors="strict")
            except UnicodeEncodeError as exc:
                raise ValidationError("finding field_key must be valid Unicode text") from exc
            if len(encoded_field_key) > _MAX_FIELD_KEY_UTF8_BYTES:
                raise ValidationError("finding field_key exceeds the bounded semantic-key ceiling")
        return observation_id

    @classmethod
    def stage_findings(
        cls,
        uow: UnitOfWork,
        *,
        import_run_id: str,
        expected_run_revision: int,
        findings: tuple[NormalizedFindingEvidence, ...],
    ) -> tuple[str, ...]:
        canonical_run_id, source_family = cls._require_validating_run(
            uow,
            import_run_id=import_run_id,
            expected_run_revision=expected_run_revision,
        )
        if not findings:
            return ()

        normalized_observation_ids: list[str | None] = []
        referenced_ids: set[str] = set()
        for finding in findings:
            observation_id = cls.validate_finding(source_family, finding)
            normalized_observation_ids.append(observation_id)
            if observation_id is not None:
                referenced_ids.add(observation_id)

        owned_ids: set[str] = set()
        ordered_references = sorted(referenced_ids)
        for start in range(0, len(ordered_references), _OBSERVATION_LOOKUP_BATCH):
            batch = ordered_references[start : start + _OBSERVATION_LOOKUP_BATCH]
            placeholders = ",".join("?" for _ in batch)
            rows = uow.connection.execute(
                "SELECT source_observation_id FROM source_observations WHERE import_run_id=? "
                f"AND source_observation_id IN ({placeholders})",
                (canonical_run_id, *batch),
            ).fetchall()
            owned_ids.update(str(row[0]) for row in rows)
        if owned_ids != referenced_ids:
            raise ValidationError("finding source observation must belong to the same validating import run")

        recorded_at = utc_epoch_seconds()
        finding_ids: list[str] = []
        for finding, observation_id in zip(findings, normalized_observation_ids, strict=True):
            finding_id = new_uuid4()
            uow.connection.execute(
                "INSERT INTO import_findings("
                "import_finding_id,import_run_id,source_observation_id,field_key,finding_code,severity,scope_kind,"
                "message_text,recorded_at_utc) VALUES (?,?,?,?,?,?,?,?,?)",
                (
                    finding_id,
                    canonical_run_id,
                    observation_id,
                    finding.field_key,
                    finding.finding_code,
                    finding.severity,
                    finding.scope_kind,
                    finding.message_text,
                    recorded_at,
                ),
            )
            finding_ids.append(finding_id)
        return tuple(finding_ids)
