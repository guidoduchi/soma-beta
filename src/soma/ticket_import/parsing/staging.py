from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from soma.foundation.errors import SomaError, ValidationError
from soma.foundation.persistence.uow import UnitOfWork
from soma.ticket_import.profiles.registry import require_profile_versions
from soma.ticket_import.repositories.findings import NormalizedFindingEvidence, SourceFindingRepository
from soma.ticket_import.repositories.observations import SourceObservationRepository, StagedObservationResult

from .advanced_search import AdvancedSearchParseResult, ParsedFinding
from .rfc import RfcParseResult
from .wfm import WfmParseResult


_OBSERVATION_STAGE_BATCH = 2_000


@dataclass(frozen=True, slots=True)
class ImportStagingBatchResult:
    start_index: int
    next_index: int
    complete: bool
    observations: tuple[StagedObservationResult, ...]
    finding_ids: tuple[str, ...]


# Compatibility name retained for already-certified Advanced Search callers/tests.
AdvancedSearchStagingBatchResult = ImportStagingBatchResult


def _require_exact_parser_profile(parsed: Any, *, source_family: str) -> None:
    expected = require_profile_versions(source_family)
    if getattr(parsed, "source_family", None) != source_family or (
        getattr(parsed, "source_profile_id", None),
        getattr(parsed, "header_registry_id", None),
        getattr(parsed, "vocabulary_registry_id", None),
        getattr(parsed, "parser_profile_id", None),
    ) != (
        expected.source_profile_id,
        expected.header_registry_id,
        expected.vocabulary_registry_id,
        expected.parser_profile_id,
    ):
        raise SomaError("IMPORT_SOURCE_PROFILE_MISMATCH", "parsed evidence uses a stale source profile registry")


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


def _validate_row_findings(row: Any, *, source_family: str) -> None:
    for finding in row.findings:
        if finding.sheet_ordinal is not None and finding.sheet_ordinal != row.observation.sheet_ordinal:
            raise SomaError("IMPORT_SOURCE_PROFILE_MISMATCH", "row finding sheet provenance disagrees with observation")
        if finding.row_ordinal is not None and finding.row_ordinal != row.observation.row_ordinal:
            raise SomaError("IMPORT_SOURCE_PROFILE_MISMATCH", "row finding row provenance disagrees with observation")
        SourceFindingRepository.validate_finding(
            source_family,
            _to_finding(finding, source_observation_id=None),
        )


def stage_import_parse_batch(
    uow: UnitOfWork,
    *,
    import_run_id: str,
    expected_run_revision: int,
    source_family: str,
    parsed: Any,
    start_index: int,
    include_global_findings: bool = False,
) -> ImportStagingBatchResult:
    """Stage one bounded immutable parser batch for any registered LLD-04 source family."""

    _require_exact_parser_profile(parsed, source_family=source_family)
    rows = parsed.rows
    if type(start_index) is not int or start_index < 0 or start_index > len(rows):
        raise ValidationError("start_index must address the parsed source row sequence")
    if include_global_findings and start_index != 0:
        raise ValidationError("workbook-level findings may be staged only with the first parser batch")

    end_index = min(start_index + _OBSERVATION_STAGE_BATCH, len(rows))
    selected_rows = rows[start_index:end_index]
    seen_locators: set[tuple[int, int]] = set()
    for row in selected_rows:
        locator = (row.observation.sheet_ordinal, row.observation.row_ordinal)
        if locator in seen_locators:
            raise SomaError("IMPORT_SOURCE_PROFILE_MISMATCH", "staging batch repeats one physical worksheet row")
        seen_locators.add(locator)
        _validate_row_findings(row, source_family=source_family)
    if include_global_findings:
        for finding in parsed.global_findings:
            SourceFindingRepository.validate_finding(
                source_family,
                _to_finding(finding, source_observation_id=None),
            )

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
    return ImportStagingBatchResult(
        start_index=start_index,
        next_index=end_index,
        complete=end_index == len(rows),
        observations=staged_rows,
        finding_ids=finding_ids,
    )


def stage_advanced_search_parse_batch(
    uow: UnitOfWork,
    *,
    import_run_id: str,
    expected_run_revision: int,
    parsed: AdvancedSearchParseResult,
    start_index: int,
    include_global_findings: bool = False,
) -> ImportStagingBatchResult:
    return stage_import_parse_batch(
        uow,
        import_run_id=import_run_id,
        expected_run_revision=expected_run_revision,
        source_family="advanced_search_sr",
        parsed=parsed,
        start_index=start_index,
        include_global_findings=include_global_findings,
    )


def stage_rfc_parse_batch(
    uow: UnitOfWork,
    *,
    import_run_id: str,
    expected_run_revision: int,
    parsed: RfcParseResult,
    start_index: int,
    include_global_findings: bool = False,
) -> ImportStagingBatchResult:
    return stage_import_parse_batch(
        uow,
        import_run_id=import_run_id,
        expected_run_revision=expected_run_revision,
        source_family="rfc_enhanced",
        parsed=parsed,
        start_index=start_index,
        include_global_findings=include_global_findings,
    )


def stage_wfm_parse_batch(
    uow: UnitOfWork,
    *,
    import_run_id: str,
    expected_run_revision: int,
    parsed: WfmParseResult,
    start_index: int,
    include_global_findings: bool = False,
) -> ImportStagingBatchResult:
    return stage_import_parse_batch(
        uow,
        import_run_id=import_run_id,
        expected_run_revision=expected_run_revision,
        source_family="wfm_service_provider",
        parsed=parsed,
        start_index=start_index,
        include_global_findings=include_global_findings,
    )


__all__ = [
    "AdvancedSearchStagingBatchResult",
    "ImportStagingBatchResult",
    "stage_advanced_search_parse_batch",
    "stage_import_parse_batch",
    "stage_rfc_parse_batch",
    "stage_wfm_parse_batch",
]
