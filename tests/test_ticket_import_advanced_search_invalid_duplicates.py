from __future__ import annotations

from pathlib import Path

from openpyxl import Workbook

from soma.ticket_import.parsing.advanced_search import parse_advanced_search
from soma.ticket_import.parsing.xlsx_security import preflight_xlsx


def test_identical_invalid_sr_rows_remain_independent_invalid_evidence(tmp_path: Path) -> None:
    path = tmp_path / "invalid-duplicates.xlsx"
    workbook = Workbook()
    worksheet = workbook.active
    assert worksheet is not None
    worksheet.title = "Service Request"
    worksheet.append(["SRNo", "Problem Summary"])
    worksheet.append(["SR 12345678", "same malformed row"])
    worksheet.append(["SR 12345678", "same malformed row"])
    workbook.save(path)
    workbook.close()

    parsed = parse_advanced_search(path, preflight=preflight_xlsx(path))

    assert len(parsed.rows) == 2
    assert all(row.observation.identity_state == "invalid" for row in parsed.rows)
    assert all(row.observation.entity_kind == "invalid_row" for row in parsed.rows)
    assert all(row.observation.canonical_primary_id is None for row in parsed.rows)
    assert all(row.classification == "UNIQUE" for row in parsed.rows)
    assert all(row.duplicate_count == 1 for row in parsed.rows)
    assert all(row.conflict_variant_count == 1 for row in parsed.rows)
    assert all(
        not any(
            finding.finding_code in {"SOURCE_EQUIVALENT_DUPLICATE", "SOURCE_IDENTITY_CONFLICT"}
            for finding in row.findings
        )
        for row in parsed.rows
    )
