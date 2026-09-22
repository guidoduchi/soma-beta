from __future__ import annotations

import zipfile
from datetime import UTC, datetime, timedelta, timezone
from pathlib import Path

import pytest
from openpyxl import Workbook

from soma.foundation.errors import SomaError
from soma.ticket_import.parsing.advanced_search import parse_advanced_search
from soma.ticket_import.parsing.xlsx_security import preflight_xlsx
from soma.ticket_import.reconciliation.engine import field_logical_sha256, row_logical_sha256


def _write_workbook(
    path: Path,
    headers: list[object],
    rows: list[list[object]],
    *,
    second_matrix: bool = False,
) -> None:
    workbook = Workbook()
    worksheet = workbook.active
    worksheet.title = "Service Request"
    worksheet.append(headers)
    for row in rows:
        worksheet.append(row)
    if second_matrix:
        other = workbook.create_sheet("Other")
        other.append(["SRNo", "Problem Summary"])
        other.append(["87654321", "Other"])
    workbook.save(path)
    workbook.close()


def _parse(path: Path):
    return parse_advanced_search(path, preflight=preflight_xlsx(path))


def _field(parsed_row, key: str):
    return next(field for field in parsed_row.observation.fields if field.field_key == key)


def test_parses_registered_fields_and_reuses_exact_logical_hashes(tmp_path: Path) -> None:
    path = tmp_path / "advanced.xlsx"
    _write_workbook(
        path,
        [
            "  SRNo  ",
            "Problem Summary",
            "Customer Severity",
            "Status",
            "Report Date",
            "Suspension Duration",
            "Last Update",
            "Product",
            "Unregistered Thing",
        ],
        [[
            "12345678",
            "  Link is down  ",
            "  CRITICAL ",
            " closed ",
            "2026-09-13 10:00:00",
            "1.5",
            "2026-09-13T12:34:56.999999-05:00",
            "discard-me",
            "discard-me-too",
        ]],
    )

    result = _parse(path)

    assert result.source_family == "advanced_search_sr"
    assert result.source_profile_id == "ADVANCED_SEARCH_SR_V1"
    assert result.header_registry_id == "ADVANCED_SEARCH_HEADERS_V1"
    assert result.vocabulary_registry_id == "ADVANCED_SEARCH_VOCAB_V1"
    assert result.parser_profile_id == "ADVANCED_SEARCH_PARSER_V1"
    assert len(result.rows) == 1

    parsed = result.rows[0]
    assert parsed.observation.identity_state == "valid"
    assert parsed.observation.entity_kind == "service_request"
    assert parsed.observation.canonical_primary_id == "12345678"
    assert parsed.classification == "UNIQUE"

    keys = {field.field_key for field in parsed.observation.fields}
    assert "Product" not in keys
    assert "product" not in keys
    assert "Unregistered Thing" not in keys
    assert keys == {
        "problem_summary",
        "customer_severity",
        "status",
        "report_date",
        "suspension_duration",
        "last_update",
    }

    assert _field(parsed, "problem_summary").normalized_text == "Link is down"
    assert _field(parsed, "customer_severity").normalized_text == "Critical"
    assert _field(parsed, "status").normalized_text == "Closed"
    assert _field(parsed, "suspension_duration").integer_value == 129_600

    expected_report = int(
        datetime(2026, 9, 13, 10, 0, 0, tzinfo=timezone(timedelta(hours=-5))).timestamp()
    )
    expected_update = int(
        datetime(2026, 9, 13, 12, 34, 56, tzinfo=timezone(timedelta(hours=-5))).timestamp()
    )
    assert _field(parsed, "report_date").integer_value == expected_report
    assert _field(parsed, "last_update").integer_value == expected_update
    assert parsed.observation.source_row_chronology_utc == expected_update

    assert parsed.observation.row_logical_sha256 == row_logical_sha256(parsed.logical_row)
    logical_by_key = {field.field_key: field for field in parsed.logical_row.fields}
    for field in parsed.observation.fields:
        assert field.field_logical_sha256 == field_logical_sha256(logical_by_key[field.field_key])

    coverage = {finding.field_key for finding in result.global_findings}
    assert "customer_contact_label" in coverage
    assert "current_handler_label" in coverage
    assert "resolve_by" in coverage
    assert all(finding.finding_code == "SOURCE_HEADER_COVERAGE_MISSING" for finding in result.global_findings)
    assert all(finding.severity == "warning" for finding in result.global_findings)


def test_duration_decimal_days_uses_half_even_whole_seconds(tmp_path: Path) -> None:
    path = tmp_path / "duration.xlsx"
    _write_workbook(
        path,
        ["SRNo", "Suspension Duration"],
        [
            ["12345678", "0.00015625"],
            ["87654321", "0.00046875"],
            ["11223344", 1.25],
        ],
    )

    result = _parse(path)

    assert _field(result.rows[0], "suspension_duration").integer_value == 14
    assert _field(result.rows[1], "suspension_duration").integer_value == 40
    assert _field(result.rows[2], "suspension_duration").integer_value == 108_000


def test_present_blank_duration_is_zero_but_missing_header_creates_no_field(tmp_path: Path) -> None:
    with_duration = tmp_path / "blank-duration.xlsx"
    _write_workbook(with_duration, ["SRNo", "Suspension Duration"], [["12345678", None]])
    parsed = _parse(with_duration)
    duration = _field(parsed.rows[0], "suspension_duration")
    assert duration.value_state == "usable"
    assert duration.integer_value == 0
    assert duration.source_text == ""

    without_duration = tmp_path / "missing-duration.xlsx"
    _write_workbook(without_duration, ["SRNo", "Problem Summary"], [["12345678", "x"]])
    parsed_missing = _parse(without_duration)
    assert "suspension_duration" not in {
        field.field_key for field in parsed_missing.rows[0].observation.fields
    }
    assert any(
        finding.finding_code == "SOURCE_HEADER_COVERAGE_MISSING"
        and finding.field_key == "suspension_duration"
        for finding in parsed_missing.global_findings
    )


@pytest.mark.parametrize("value", ["-1", "1e3", "1,5", "1 day", "Infinity"])
def test_malformed_duration_never_clamps_or_acquires_authority(tmp_path: Path, value: object) -> None:
    path = tmp_path / "bad-duration.xlsx"
    _write_workbook(path, ["SRNo", "Suspension Duration"], [["12345678", value]])

    parsed = _parse(path)
    duration = _field(parsed.rows[0], "suspension_duration")
    assert duration.value_state == "malformed"
    assert duration.integer_value is None


def test_invalid_identity_and_unknown_controlled_values_are_evidence_only(tmp_path: Path) -> None:
    path = tmp_path / "invalid.xlsx"
    _write_workbook(
        path,
        ["SRNo", "Customer Severity", "Status"],
        [["SR 12345678", "Emergency", "Almost Closed"]],
    )

    parsed = _parse(path).rows[0]

    assert parsed.observation.identity_state == "invalid"
    assert parsed.observation.entity_kind == "invalid_row"
    assert parsed.observation.canonical_primary_id is None
    assert _field(parsed, "customer_severity").value_state == "unknown"
    assert _field(parsed, "status").value_state == "unknown"
    assert [finding.finding_code for finding in parsed.findings].count("SR_ID_INVALID") == 1
    assert [finding.finding_code for finding in parsed.findings].count(
        "SOURCE_CONTROLLED_VALUE_UNKNOWN"
    ) == 2


def test_header_normalization_is_unicode_whitespace_and_casefold_governed(tmp_path: Path) -> None:
    path = tmp_path / "headers.xlsx"
    _write_workbook(
        path,
        ["\u3000srno\u3000", "CUSTOMER\u00a0\u00a0SEVERITY", "problem   summary"],
        [["12345678", "major", "hello"]],
    )

    parsed = _parse(path).rows[0]
    assert parsed.observation.canonical_primary_id == "12345678"
    assert _field(parsed, "customer_severity").normalized_text == "Major"
    assert _field(parsed, "problem_summary").normalized_text == "hello"


def test_duplicate_semantic_header_blocks_workbook(tmp_path: Path) -> None:
    path = tmp_path / "duplicate-header.xlsx"
    _write_workbook(path, ["SRNo", " srno "], [["12345678", "12345678"]])

    with pytest.raises(SomaError) as raised:
        _parse(path)
    assert raised.value.code == "SOURCE_DUPLICATE_SEMANTIC_HEADER"


def test_semantic_formula_blocks_workbook_but_discarded_product_formula_does_not(tmp_path: Path) -> None:
    bad = tmp_path / "formula.xlsx"
    _write_workbook(bad, ["SRNo", "Problem Summary"], [["12345678", "=1+1"]])
    with pytest.raises(SomaError) as raised:
        _parse(bad)
    assert raised.value.code == "SOURCE_FORMULA_IN_SEMANTIC_FIELD"

    discarded = tmp_path / "discarded-formula.xlsx"
    _write_workbook(discarded, ["SRNo", "Product"], [["12345678", "=1+1"]])
    parsed = _parse(discarded)
    assert parsed.rows[0].observation.canonical_primary_id == "12345678"
    assert parsed.rows[0].observation.fields == ()


def test_exact_excel_datetime_and_text_offset_normalize_to_same_instant(tmp_path: Path) -> None:
    path = tmp_path / "dates.xlsx"
    excel_value = datetime(2026, 9, 13, 10, 0, 0)
    _write_workbook(
        path,
        ["SRNo", "Report Date"],
        [
            ["12345678", excel_value],
            ["87654321", "2026-09-13T15:00:00Z"],
        ],
    )

    parsed = _parse(path)
    expected = int(datetime(2026, 9, 13, 15, 0, 0, tzinfo=UTC).timestamp())
    assert _field(parsed.rows[0], "report_date").integer_value == expected
    assert _field(parsed.rows[1], "report_date").integer_value == expected


def test_lowercase_z_and_pre_epoch_timestamps_are_malformed_without_fallback(tmp_path: Path) -> None:
    path = tmp_path / "bad-dates.xlsx"
    _write_workbook(
        path,
        ["SRNo", "Report Date", "Last Update"],
        [
            ["12345678", "2026-09-13T15:00:00z", "1969-12-31T23:59:59Z"],
        ],
    )

    parsed = _parse(path).rows[0]
    assert _field(parsed, "report_date").value_state == "malformed"
    assert _field(parsed, "last_update").value_state == "malformed"
    assert parsed.observation.source_row_chronology_utc is None


def test_equivalent_duplicates_and_conflicts_are_deterministic_classifications(tmp_path: Path) -> None:
    duplicate_path = tmp_path / "duplicates.xlsx"
    _write_workbook(
        duplicate_path,
        ["SRNo", "Problem Summary"],
        [["12345678", "same"], ["12345678", "same"]],
    )
    duplicates = _parse(duplicate_path).rows
    assert {row.classification for row in duplicates} == {"EQUIVALENT_DUPLICATE"}
    assert {row.duplicate_count for row in duplicates} == {2}
    assert all(
        any(finding.finding_code == "SOURCE_EQUIVALENT_DUPLICATE" for finding in row.findings)
        for row in duplicates
    )

    conflict_path = tmp_path / "conflicts.xlsx"
    _write_workbook(
        conflict_path,
        ["SRNo", "Problem Summary"],
        [["12345678", "one"], ["12345678", "two"], ["87654321", "safe"]],
    )
    conflicts = _parse(conflict_path).rows
    affected = [row for row in conflicts if row.observation.canonical_primary_id == "12345678"]
    unrelated = [row for row in conflicts if row.observation.canonical_primary_id == "87654321"]
    assert {row.classification for row in affected} == {"CONFLICT_MEMBER"}
    assert {row.conflict_variant_count for row in affected} == {2}
    assert unrelated[0].classification == "UNIQUE"
    assert all(
        any(finding.finding_code == "SOURCE_IDENTITY_CONFLICT" for finding in row.findings)
        for row in affected
    )


def test_multiple_matrices_are_rejected(tmp_path: Path) -> None:
    path = tmp_path / "ambiguous.xlsx"
    _write_workbook(
        path,
        ["SRNo", "Problem Summary"],
        [["12345678", "one"]],
        second_matrix=True,
    )

    with pytest.raises(SomaError) as raised:
        _parse(path)
    assert raised.value.code == "SOURCE_MATRIX_AMBIGUOUS"


def test_parser_requires_preflight_for_the_exact_same_path(tmp_path: Path) -> None:
    first = tmp_path / "first.xlsx"
    second = tmp_path / "second.xlsx"
    _write_workbook(first, ["SRNo"], [["12345678"]])
    _write_workbook(second, ["SRNo"], [["87654321"]])

    preflight = preflight_xlsx(first)
    with pytest.raises(SomaError) as raised:
        parse_advanced_search(second, preflight=preflight)
    assert raised.value.code == "IMPORT_SOURCE_PROFILE_MISMATCH"
    with pytest.raises(SomaError) as closed:
        preflight.semantic_stream()
    assert closed.value.code == "IMPORT_SOURCE_UNAVAILABLE"


def test_advanced_search_parser_consumes_exact_preflighted_bytes_after_path_replacement(
    tmp_path: Path,
) -> None:
    path = tmp_path / "stale-preflight.xlsx"
    _write_workbook(
        path,
        ["SRNo", "Problem Summary"],
        [["12345678", "Original safe workbook"]],
    )
    preflight = preflight_xlsx(path)

    with zipfile.ZipFile(path, "a") as archive:
        archive.writestr("xl/embeddings/audit-marker.bin", b"harmless audit marker")

    with pytest.raises(SomaError) as fresh:
        preflight_xlsx(path)
    assert fresh.value.code == "XLSX_UNSAFE_CONTAINER"

    parsed = parse_advanced_search(path, preflight=preflight)
    assert len(parsed.rows) == 1
    assert parsed.rows[0].observation.canonical_primary_id == "12345678"
    assert _field(parsed.rows[0], "problem_summary").normalized_text == "Original safe workbook"
