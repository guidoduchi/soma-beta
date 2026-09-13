from __future__ import annotations

from dataclasses import replace
from pathlib import Path

import pytest
from openpyxl import Workbook

from soma.foundation.errors import SomaError
from soma.foundation.identifiers import new_uuid4
from soma.foundation.persistence.uow import ReadSnapshot, UnitOfWork
from soma.ticket_import.parsing.advanced_search import parse_advanced_search
from soma.ticket_import.parsing.staging import stage_advanced_search_parse_result
from soma.ticket_import.parsing.xlsx_security import preflight_xlsx
from soma.ticket_import.repositories.observations import SourceObservationRepository


def _factory(initialized_database):
    database_path, factory_for_path = initialized_database
    return factory_for_path(database_path)


def _seed_validating_run(factory) -> str:
    run_id = new_uuid4()
    with UnitOfWork(factory) as uow:
        uow.connection.execute(
            "INSERT INTO import_runs("
            "import_run_id,source_family,invocation_kind,source_profile_id,header_registry_id,vocabulary_registry_id,parser_profile_id,"
            "candidate_filename,candidate_file_size_bytes,candidate_stable_mtime_ns,candidate_chronology_kind,candidate_chronology_value,"
            "run_state,started_at_utc,revision) VALUES (?,?,?,?,?,?,?,'fixture.xlsx',100,10,?,100,'validating',1,1)",
            (
                run_id,
                "advanced_search_sr",
                "automatic",
                "ADVANCED_SEARCH_SR_V1",
                "ADVANCED_SEARCH_HEADERS_V1",
                "ADVANCED_SEARCH_VOCAB_V1",
                "ADVANCED_SEARCH_PARSER_V1",
                "embedded_filename_timestamp_utc",
            ),
        )
    return run_id


def _write_workbook(path: Path, headers: list[object], rows: list[list[object]]) -> None:
    workbook = Workbook()
    worksheet = workbook.active
    worksheet.title = "Service Request"
    worksheet.append(headers)
    for row in rows:
        worksheet.append(row)
    workbook.save(path)
    workbook.close()


def _parse(path: Path):
    return parse_advanced_search(path, preflight=preflight_xlsx(path))


def test_parser_staging_persists_row_and_global_findings_without_publication(
    initialized_database,
    tmp_path: Path,
) -> None:
    factory = _factory(initialized_database)
    run_id = _seed_validating_run(factory)
    path = tmp_path / "findings.xlsx"
    _write_workbook(path, ["SRNo", "Status"], [["bad-id", "mystery status"]])
    parsed = _parse(path)

    with UnitOfWork(factory) as uow:
        staged = stage_advanced_search_parse_result(
            uow,
            import_run_id=run_id,
            expected_run_revision=1,
            parsed=parsed,
        )

    assert len(staged.observations) == 1
    assert len(staged.finding_ids) == len(parsed.rows[0].findings) + len(parsed.global_findings)

    with ReadSnapshot(factory) as snapshot:
        run = snapshot.connection.execute(
            "SELECT run_state,logical_fingerprint_sha256,observed_row_count,revision FROM import_runs WHERE import_run_id=?",
            (run_id,),
        ).fetchone()
        assert tuple(run) == ("validating", None, 0, 1)
        evidence = SourceObservationRepository.load_validating_evidence(
            snapshot.connection,
            import_run_id=run_id,
            expected_run_revision=1,
        )

    assert len(evidence.observations) == 1
    observation = evidence.observations[0]
    assert observation.identity_state == "invalid"
    assert observation.entity_kind == "invalid_row"
    assert observation.canonical_primary_id is None
    assert {finding.finding_code for finding in observation.findings} == {
        "SR_ID_INVALID",
        "SOURCE_CONTROLLED_VALUE_UNKNOWN",
    }
    assert evidence.global_findings
    assert {finding.finding_code for finding in evidence.global_findings} == {"SOURCE_HEADER_COVERAGE_MISSING"}
    assert all(finding.source_observation_id is None for finding in evidence.global_findings)


def test_conflict_findings_bind_each_physical_row_to_its_exact_observation(
    initialized_database,
    tmp_path: Path,
) -> None:
    factory = _factory(initialized_database)
    run_id = _seed_validating_run(factory)
    path = tmp_path / "conflicts.xlsx"
    _write_workbook(
        path,
        ["SRNo", "Problem Summary"],
        [["12345678", "one"], ["12345678", "two"], ["87654321", "safe"]],
    )
    parsed = _parse(path)

    with UnitOfWork(factory) as uow:
        staged = stage_advanced_search_parse_result(
            uow,
            import_run_id=run_id,
            expected_run_revision=1,
            parsed=parsed,
        )

    assert len(staged.observations) == 3
    with ReadSnapshot(factory) as snapshot:
        evidence = SourceObservationRepository.load_validating_evidence(
            snapshot.connection,
            import_run_id=run_id,
            expected_run_revision=1,
        )

    by_sr = {observation.canonical_primary_id: [] for observation in evidence.observations}
    for observation in evidence.observations:
        by_sr[observation.canonical_primary_id].append(observation)
    affected = by_sr["12345678"]
    assert len(affected) == 2
    assert all(
        {finding.finding_code for finding in observation.findings} == {"SOURCE_IDENTITY_CONFLICT"}
        for observation in affected
    )
    assert by_sr["87654321"][0].findings == ()
    assert {observation.source_observation_id for observation in affected} == {
        staged.observations[0].source_observation_id,
        staged.observations[1].source_observation_id,
    }


def test_reparse_replaces_only_unpublished_technical_staging(
    initialized_database,
    tmp_path: Path,
) -> None:
    factory = _factory(initialized_database)
    run_id = _seed_validating_run(factory)
    first = tmp_path / "first.xlsx"
    second = tmp_path / "second.xlsx"
    _write_workbook(first, ["SRNo", "Problem Summary"], [["12345678", "first"]])
    _write_workbook(second, ["SRNo", "Problem Summary"], [["87654321", "second"]])

    with UnitOfWork(factory) as uow:
        first_staged = stage_advanced_search_parse_result(
            uow,
            import_run_id=run_id,
            expected_run_revision=1,
            parsed=_parse(first),
        )
    with UnitOfWork(factory) as uow:
        second_staged = stage_advanced_search_parse_result(
            uow,
            import_run_id=run_id,
            expected_run_revision=1,
            parsed=_parse(second),
        )

    assert first_staged.observations[0].source_observation_id != second_staged.observations[0].source_observation_id
    with ReadSnapshot(factory) as snapshot:
        rows = snapshot.connection.execute(
            "SELECT source_observation_id,canonical_primary_id FROM source_observations WHERE import_run_id=?",
            (run_id,),
        ).fetchall()
        assert [tuple(row) for row in rows] == [
            (second_staged.observations[0].source_observation_id, "87654321")
        ]


def test_invalid_finding_code_fails_before_existing_staging_is_replaced(
    initialized_database,
    tmp_path: Path,
) -> None:
    factory = _factory(initialized_database)
    run_id = _seed_validating_run(factory)
    first = tmp_path / "first.xlsx"
    bad = tmp_path / "bad.xlsx"
    _write_workbook(first, ["SRNo", "Problem Summary"], [["12345678", "first"]])
    _write_workbook(bad, ["SRNo", "Status"], [["87654321", "unknown status"]])

    with UnitOfWork(factory) as uow:
        first_staged = stage_advanced_search_parse_result(
            uow,
            import_run_id=run_id,
            expected_run_revision=1,
            parsed=_parse(first),
        )

    parsed = _parse(bad)
    row = parsed.rows[0]
    assert row.findings and row.findings[0].finding_code == "SOURCE_CONTROLLED_VALUE_UNKNOWN"
    poisoned_finding = replace(row.findings[0], finding_code="NOT_IN_LLD04_CATALOGUE")
    poisoned_row = replace(row, findings=(poisoned_finding, *row.findings[1:]))
    poisoned = replace(parsed, rows=(poisoned_row, *parsed.rows[1:]))

    with pytest.raises(SomaError) as raised:
        with UnitOfWork(factory) as uow:
            stage_advanced_search_parse_result(
                uow,
                import_run_id=run_id,
                expected_run_revision=1,
                parsed=poisoned,
            )
    assert raised.value.code == "IMPORT_SOURCE_PROFILE_MISMATCH"

    with ReadSnapshot(factory) as snapshot:
        rows = snapshot.connection.execute(
            "SELECT source_observation_id,canonical_primary_id FROM source_observations WHERE import_run_id=?",
            (run_id,),
        ).fetchall()
        assert [tuple(row) for row in rows] == [
            (first_staged.observations[0].source_observation_id, "12345678")
        ]
