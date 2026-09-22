from __future__ import annotations

import zipfile
from datetime import UTC, datetime

import pytest
from openpyxl import Workbook

from soma.foundation.errors import SomaError

from soma.ticket_import.parsing.rfc import parse_rfc_enhanced
from soma.ticket_import.parsing.xlsx_security import preflight_xlsx


def _save(path, rows) -> None:
    workbook = Workbook()
    sheet = workbook.active
    for row in rows:
        sheet.append(row)
    workbook.save(path)


def test_rfc_parser_separates_exact_identity_branch_artifact_and_invalid_row(tmp_path) -> None:
    path = tmp_path / "Enhanced Excel Data Export.xlsx"
    _save(
        path,
        [
            ["Task ID", "Status", "Summary", "Last Update Time"],
            ["NC12345678901234", "Implement", "first", "2026-09-16 10:30:00"],
            ["NC12345678901234-branch", "Closed", "artifact", "2026-09-16 11:00:00"],
            ["NC123", "Cancelled", "invalid", "2026-09-16 12:00:00"],
        ],
    )

    parsed = parse_rfc_enhanced(path, preflight=preflight_xlsx(path))

    assert parsed.source_family == "rfc_enhanced"
    assert parsed.source_profile_id == "RFC_ENHANCED_V1"
    assert parsed.header_registry_id == "RFC_HEADERS_V1"
    assert parsed.vocabulary_registry_id == "RFC_VOCAB_V1"
    assert parsed.parser_profile_id == "RFC_PARSER_V1"

    exact, artifact, invalid = parsed.rows
    assert exact.observation.entity_kind == "rfc"
    assert exact.observation.identity_state == "valid"
    assert exact.observation.canonical_primary_id == "NC12345678901234"
    assert exact.observation.source_row_chronology_utc == int(
        datetime(2026, 9, 16, 15, 30, tzinfo=UTC).timestamp()
    )

    assert artifact.observation.entity_kind == "invalid_row"
    assert artifact.observation.canonical_primary_id is None
    assert [finding.finding_code for finding in artifact.findings] == ["RFC_SOURCE_BRANCH_ARTIFACT"]

    assert invalid.observation.entity_kind == "invalid_row"
    assert invalid.observation.canonical_primary_id is None
    assert [finding.finding_code for finding in invalid.findings] == ["RFC_ID_INVALID"]


def test_rfc_parser_preserves_unknown_status_as_warning_only_source_evidence(tmp_path) -> None:
    path = tmp_path / "operator-selected.xlsx"
    _save(path, [["Task ID", "Status"], ["NC12345678901234", "Mystery State"]])

    parsed = parse_rfc_enhanced(path, preflight=preflight_xlsx(path))
    row = parsed.rows[0]
    status = next(field for field in row.observation.fields if field.field_key == "status")

    assert status.value_state == "unknown"
    assert status.vocabulary_id == "RFC_STATUS_V1"
    assert status.normalized_text is None
    assert row.observation.source_row_chronology_utc is None
    assert [finding.finding_code for finding in row.findings] == ["SOURCE_CONTROLLED_VALUE_UNKNOWN"]
    assert any(
        finding.finding_code == "SOURCE_HEADER_COVERAGE_MISSING" and finding.field_key == "last_update"
        for finding in parsed.global_findings
    )


def test_rfc_parser_classifies_equivalent_duplicates_and_content_conflicts_per_identity(tmp_path) -> None:
    path = tmp_path / "duplicates.xlsx"
    _save(
        path,
        [
            ["Task ID", "Summary", "Status"],
            ["NC11111111111111", "same", "Implement"],
            ["NC11111111111111", "same", "Implement"],
            ["NC22222222222222", "variant-a", "Implement"],
            ["NC22222222222222", "variant-b", "Implement"],
            ["NC33333333333333", "unrelated", "Closed"],
        ],
    )

    parsed = parse_rfc_enhanced(path, preflight=preflight_xlsx(path))
    by_id: dict[str, list] = {}
    for row in parsed.rows:
        assert row.observation.canonical_primary_id is not None
        by_id.setdefault(row.observation.canonical_primary_id, []).append(row)

    equivalent = by_id["NC11111111111111"]
    assert {row.classification for row in equivalent} == {"EQUIVALENT_DUPLICATE"}
    assert all(row.duplicate_count == 2 for row in equivalent)
    assert all("SOURCE_EQUIVALENT_DUPLICATE" in {f.finding_code for f in row.findings} for row in equivalent)

    conflicting = by_id["NC22222222222222"]
    assert {row.classification for row in conflicting} == {"CONFLICT_MEMBER"}
    assert all(row.conflict_variant_count == 2 for row in conflicting)
    assert all("SOURCE_IDENTITY_CONFLICT" in {f.finding_code for f in row.findings} for row in conflicting)

    unrelated = by_id["NC33333333333333"][0]
    assert unrelated.classification == "UNIQUE"
    assert "SOURCE_IDENTITY_CONFLICT" not in {f.finding_code for f in unrelated.findings}


def test_rfc_parser_consumes_exact_preflighted_bytes_after_path_replacement(tmp_path) -> None:
    path = tmp_path / "stale-rfc.xlsx"
    _save(
        path,
        [
            ["Task ID", "Summary"],
            ["NC12345678901234", "Original safe RFC"],
        ],
    )
    preflight = preflight_xlsx(path)

    with zipfile.ZipFile(path, "a") as archive:
        archive.writestr("xl/embeddings/audit-marker.bin", b"harmless audit marker")

    with pytest.raises(SomaError) as fresh:
        preflight_xlsx(path)
    assert fresh.value.code == "XLSX_UNSAFE_CONTAINER"

    parsed = parse_rfc_enhanced(path, preflight=preflight)
    assert len(parsed.rows) == 1
    assert parsed.rows[0].observation.canonical_primary_id == "NC12345678901234"
