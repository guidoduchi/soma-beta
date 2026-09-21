from __future__ import annotations

from datetime import UTC, datetime

from openpyxl import Workbook

from soma.ticket_import.parsing.wfm import parse_wfm_service_provider
from soma.ticket_import.parsing.xlsx_security import preflight_xlsx


def _save(path, rows) -> None:
    workbook = Workbook()
    sheet = workbook.active
    for row in rows:
        sheet.append(row)
    workbook.save(path)


def test_wfm_parser_keeps_export_chronology_distinct_from_plan_facts(tmp_path) -> None:
    path = tmp_path / "Service Provider Plan Creation20260916120000.xlsx"
    _save(
        path,
        [
            [
                "RFC No.",
                "Task No.",
                "RFC Status",
                "Task Status",
                "Dispatch Progress",
                "Planned Start Time",
                "Planned End Time",
            ],
            [
                "NC12345678901234",
                "TK12345678901234",
                "Implement",
                "Working",
                "On site",
                "2026-09-18 08:00:00",
                "2026-09-18 10:00:00",
            ],
        ],
    )
    source_chronology = int(datetime(2026, 9, 16, 17, 0, tzinfo=UTC).timestamp())

    parsed = parse_wfm_service_provider(
        path,
        preflight=preflight_xlsx(path),
        source_chronology_utc=source_chronology,
    )
    row = parsed.rows[0]

    assert row.observation.entity_kind == "wfm"
    assert row.observation.identity_state == "valid"
    assert row.observation.canonical_primary_id == "TK12345678901234"
    assert row.observation.canonical_parent_rfc_no == "NC12345678901234"
    assert row.observation.source_row_chronology_utc == source_chronology
    start = next(field for field in row.observation.fields if field.field_key == "planned_start")
    end = next(field for field in row.observation.fields if field.field_key == "planned_end")
    assert start.integer_value == int(datetime(2026, 9, 18, 13, 0, tzinfo=UTC).timestamp())
    assert end.integer_value == int(datetime(2026, 9, 18, 15, 0, tzinfo=UTC).timestamp())
    assert "WFM_PLAN_INVALID_INTERVAL" not in {finding.finding_code for finding in row.findings}
    assert "WFM_PLAN_INCOMPLETE" not in {finding.finding_code for finding in row.findings}
    assert "SOURCE_CONTROLLED_VALUE_UNKNOWN" in {finding.finding_code for finding in row.findings}


def test_wfm_parser_invalid_identity_never_retains_partial_domain_identity(tmp_path) -> None:
    path = tmp_path / "wfm.xlsx"
    _save(
        path,
        [
            ["RFC No", "Task No"],
            ["NC12345678901234", "TK123"],
            ["NC123", "TK12345678901234"],
        ],
    )

    parsed = parse_wfm_service_provider(path, preflight=preflight_xlsx(path), source_chronology_utc=10)

    first, second = parsed.rows
    assert first.observation.entity_kind == "invalid_row"
    assert first.observation.canonical_primary_id is None
    assert first.observation.canonical_parent_rfc_no is None
    assert {finding.finding_code for finding in first.findings} == {"WFM_TASK_ID_INVALID"}
    assert second.observation.entity_kind == "invalid_row"
    assert second.observation.canonical_primary_id is None
    assert second.observation.canonical_parent_rfc_no is None
    assert {finding.finding_code for finding in second.findings} == {"WFM_PARENT_RFC_INVALID"}


def test_wfm_parser_plan_findings_are_scoped_without_destroying_identity(tmp_path) -> None:
    path = tmp_path / "plans.xlsx"
    _save(
        path,
        [
            ["RFC No", "Task No", "Planned Start Time", "Planned End Time"],
            ["NC11111111111111", "TK11111111111111", "2026-09-18 08:00:00", None],
            ["NC22222222222222", "TK22222222222222", "2026-09-18 10:00:00", "2026-09-18 09:00:00"],
            ["NC33333333333333", "TK33333333333333", None, None],
        ],
    )

    parsed = parse_wfm_service_provider(path, preflight=preflight_xlsx(path), source_chronology_utc=20)

    assert [row.observation.identity_state for row in parsed.rows] == ["valid", "valid", "valid"]
    assert {finding.finding_code for finding in parsed.rows[0].findings} == {"WFM_PLAN_INCOMPLETE"}
    assert {finding.finding_code for finding in parsed.rows[1].findings} == {"WFM_PLAN_INVALID_INTERVAL"}
    assert {finding.finding_code for finding in parsed.rows[2].findings} == set()


def test_wfm_parser_conflicts_same_task_no_even_when_owning_rfc_differs(tmp_path) -> None:
    path = tmp_path / "ownership-conflict.xlsx"
    _save(
        path,
        [
            ["RFC No", "Task No", "Task Name"],
            ["NC11111111111111", "TK99999999999999", "same task"],
            ["NC22222222222222", "TK99999999999999", "same task"],
            ["NC33333333333333", "TK33333333333333", "unrelated"],
        ],
    )

    parsed = parse_wfm_service_provider(path, preflight=preflight_xlsx(path), source_chronology_utc=30)

    conflicted = [row for row in parsed.rows if row.observation.canonical_primary_id == "TK99999999999999"]
    assert len(conflicted) == 2
    assert {row.classification for row in conflicted} == {"CONFLICT_MEMBER"}
    assert all(row.conflict_variant_count == 2 for row in conflicted)
    assert all("SOURCE_IDENTITY_CONFLICT" in {f.finding_code for f in row.findings} for row in conflicted)

    unrelated = next(row for row in parsed.rows if row.observation.canonical_primary_id == "TK33333333333333")
    assert unrelated.classification == "UNIQUE"


def test_wfm_parser_equivalent_duplicates_collapse_only_with_same_parent_and_content(tmp_path) -> None:
    path = tmp_path / "duplicates.xlsx"
    _save(
        path,
        [
            ["RFC No", "Task No", "Task Status", "Dispatch Progress"],
            ["NC11111111111111", "TK11111111111111", "Plan Cancel", None],
            ["NC11111111111111", "TK11111111111111", "Plan Cancel", None],
        ],
    )

    parsed = parse_wfm_service_provider(path, preflight=preflight_xlsx(path), source_chronology_utc=40)

    assert {row.classification for row in parsed.rows} == {"EQUIVALENT_DUPLICATE"}
    assert all(row.duplicate_count == 2 for row in parsed.rows)
    assert all("SOURCE_EQUIVALENT_DUPLICATE" in {f.finding_code for f in row.findings} for row in parsed.rows)
