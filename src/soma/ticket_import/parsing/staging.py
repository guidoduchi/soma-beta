from __future__ import annotations

from dataclasses import dataclass

from soma.foundation.errors import SomaError, ValidationError
from soma.foundation.persistence.uow import UnitOfWork
from soma.ticket_import.profiles.registry import require_profile_versions
from soma.ticket_import.repositories.findings import NormalizedFindingEvidence, SourceFindingRepository
from soma.ticket_import.repositories.observations import SourceObservationRepository, StagedObservationResult

from .advanced_search import AdvancedSearchParseResult, ParsedAdvancedSearchRow, ParsedFinding


_SOURCE_FAMILY = "advanced_search_sr"
_OBSERVATION_STAGE_BATCH = 2_000


@dataclass(frozen=True, slots=True)
class AdvancedSearchStagingBatchResult:
    start_index: int
    next_index: int
    complete: bool
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


def _validate_row_findings(row: ParsedAdvancedSearchRow) -> None:
    for finding in row.findings:
        if finding.sheet_ordinal is not None and finding.sheet_ordinal != row.observation.sheet_ordinal:
            raise SomaError("IMPORT_SOURCE_PROFILE_MISMATCH", "row finding sheet provenance disagrees with observation")
        if finding.row_ordinal is not None and finding.row_ordinal != row.observation.row_ordinal:
            raise SomaError("IMPORT_SOURCE_PROFILE_MISMATCH", "row finding row provenance disagrees with observation")
        SourceFindingRepository._validate_finding(_to_finding(finding, source_observation_id=None))


def stage_advanced_search_parse_batch(
    uow: UnitOfWork,
    *,
    import_run_id: str,
    expected_run_revision: int,
    parsed: AdvancedSearchParseResult,
    start_index: int,
    include_global_findings: bool = False,
) -> AdvancedSearchStagingBatchResult:
    """Stage one bounded parser batch while the import run remains unpublished.

    The durable-job caller owns the outer UnitOfWork and must advance its
    `last_committed_batch` checkpoint in that same UoW before commit. Recovery
    therefore resumes after the last committed batch instead of deleting and
    rebuilding already-staged technical evidence.
    """

    _require_exact_parser_profile(parsed)
    if type(start_index) is not int or start_index < 0 or start_index > len(parsed.rows):
        raise ValidationError("start_index must address the parsed Advanced Search row sequence")

    end_index = min(start_index + _OBSERVATION_STAGE_BATCH, len(parsed.rows))
    selected_rows = parsed.rows[start_index:end_index]
    seen_locators: set[tuple[int, int]] = set()
    for row in selected_rows:
        locator = (row.observation.sheet_ordinal, row.observation.row_ordinal)
        if locator in seen_locators:
            raise SomaError("IMPORT_SOURCE_PROFILE_MISMATCH", "staging batch repeats one physical worksheet row")
        seen_locators.add(locator)
        _validate_row_findings(row)
    if include_global_findings:
        for finding in parsed.global_findings:
            SourceFindingRepository._validate_finding(_to_finding(finding, source_observation_id=None))

    staged_rows: tuple[StagedObservationResult, ...] = ()
    if selected_rows:
        staged_rows = SourceObservationRepository.stage_observations(
            uow,
            import_run_id=import_run_id,
            expected_run_revision=expected_run_revision,
            observations=tuple(row.observation for row in selected_rows),
        )

    findings: list[NormalizedFindingEvidence] = []
    for row, staged in zip(selected_rows, staged_rows, strict=True):
        findings.extend(
            _to_finding(finding, source_observation_id=staged.source_observation_id)
            for finding in row.findings
        )
    if include_global_findings:
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
    return AdvancedSearchStagingBatchResult(
        start_index=start_index,
        next_index=end_index,
        complete=end_index == len(parsed.rows),
        observations=staged_rows,
        finding_ids=finding_ids,
    )
