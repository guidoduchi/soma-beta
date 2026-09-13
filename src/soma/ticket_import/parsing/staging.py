from __future__ import annotations

from dataclasses import dataclass

from soma.foundation.errors import SomaError
from soma.foundation.persistence.uow import UnitOfWork
from soma.ticket_import.profiles.registry import require_profile_versions
from soma.ticket_import.repositories.findings import NormalizedFindingEvidence, SourceFindingRepository
from soma.ticket_import.repositories.observations import SourceObservationRepository, StagedObservationResult

from .advanced_search import AdvancedSearchParseResult, ParsedFinding


_SOURCE_FAMILY = "advanced_search_sr"
_OBSERVATION_STAGE_BATCH = 2_000


@dataclass(frozen=True, slots=True)
class AdvancedSearchStagingResult:
    observations: tuple[StagedObservationResult, ...]
    finding_ids: tuple[str, ...]


def _require_exact_parser_profile(parsed: AdvancedSearchParseResult) -> None:
    expected = require_profile_versions(_SOURCE_FAMILY)
    if parsed.source_family != _SOURCE_FAMILY or (
        parsed.source_profile_id,
        parsed.header_registry_id,
        parsed.vocabulary_registry_id,
        parsed.parser_profile_id,
    ) != (
        expected.source_profile_id,
        expected.header_registry_id,
        expected.vocabulary_registry_id,
        expected.parser_profile_id,
    ):
        raise SomaError("IMPORT_SOURCE_PROFILE_MISMATCH", "parsed Advanced Search evidence uses a stale profile registry")


def _to_finding(
    finding: ParsedFinding,
    *,
    source_observation_id: str | None,
) -> NormalizedFindingEvidence:
    return NormalizedFindingEvidence(
        source_observation_id=source_observation_id,
        field_key=finding.field_key,
        finding_code=finding.finding_code,
        severity=finding.severity,
        scope_kind=finding.scope_kind,
        message_text=finding.message_text,
    )


def stage_advanced_search_parse_result(
    uow: UnitOfWork,
    *,
    import_run_id: str,
    expected_run_revision: int,
    parsed: AdvancedSearchParseResult,
) -> AdvancedSearchStagingResult:
    """Replace unpublished technical staging with one complete parsed workbook result.

    The caller owns the outer UnitOfWork. Any raised exception must abort that UoW;
    publication/fingerprinting remains a later LLD-04 step.
    """

    _require_exact_parser_profile(parsed)

    seen_locators: set[tuple[int, int]] = set()
    for row in parsed.rows:
        locator = (row.observation.sheet_ordinal, row.observation.row_ordinal)
        if locator in seen_locators:
            raise SomaError("IMPORT_SOURCE_PROFILE_MISMATCH", "parsed result repeats one physical worksheet row")
        seen_locators.add(locator)
        for finding in row.findings:
            if finding.sheet_ordinal is not None and finding.sheet_ordinal != row.observation.sheet_ordinal:
                raise SomaError("IMPORT_SOURCE_PROFILE_MISMATCH", "row finding sheet provenance disagrees with observation")
            if finding.row_ordinal is not None and finding.row_ordinal != row.observation.row_ordinal:
                raise SomaError("IMPORT_SOURCE_PROFILE_MISMATCH", "row finding row provenance disagrees with observation")
            # Validate the durable finding vocabulary/bounds before replacing any
            # unpublished technical staging. Ownership is checked after IDs exist.
            SourceFindingRepository._validate_finding(_to_finding(finding, source_observation_id=None))
    for finding in parsed.global_findings:
        SourceFindingRepository._validate_finding(_to_finding(finding, source_observation_id=None))

    # Re-parsing an unpublished validating run replaces technical staging in the
    # same transaction. Published rows are protected by cleanup_unpublished().
    SourceObservationRepository.cleanup_unpublished(
        uow,
        import_run_id=import_run_id,
        expected_run_revision=expected_run_revision,
    )

    staged_rows: list[StagedObservationResult] = []
    observations = parsed.observations
    for start in range(0, len(observations), _OBSERVATION_STAGE_BATCH):
        staged_rows.extend(
            SourceObservationRepository.stage_observations(
                uow,
                import_run_id=import_run_id,
                expected_run_revision=expected_run_revision,
                observations=observations[start : start + _OBSERVATION_STAGE_BATCH],
            )
        )

    if len(staged_rows) != len(parsed.rows):
        raise RuntimeError("Advanced Search staging result count disagrees with parser output")

    findings: list[NormalizedFindingEvidence] = []
    for row, staged in zip(parsed.rows, staged_rows, strict=True):
        findings.extend(
            _to_finding(finding, source_observation_id=staged.source_observation_id)
            for finding in row.findings
        )
    findings.extend(
        _to_finding(finding, source_observation_id=None)
        for finding in parsed.global_findings
    )

    finding_ids = SourceFindingRepository.stage_findings(
        uow,
        import_run_id=import_run_id,
        expected_run_revision=expected_run_revision,
        findings=tuple(findings),
    )
    return AdvancedSearchStagingResult(tuple(staged_rows), finding_ids)
