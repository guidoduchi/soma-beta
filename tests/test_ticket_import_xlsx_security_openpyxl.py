from __future__ import annotations

from pathlib import Path

from openpyxl import Workbook

from soma.ticket_import.parsing.xlsx_security import preflight_xlsx


def test_standard_openpyxl_workbook_passes_security_preflight(tmp_path: Path) -> None:
    path = tmp_path / "standard-openpyxl.xlsx"
    workbook = Workbook()
    worksheet = workbook.active
    assert worksheet is not None
    worksheet.title = "Service Request"
    worksheet.append(["SRNo", "Problem Summary"])
    worksheet.append(["12345678", "Link is down"])
    workbook.save(path)
    workbook.close()

    result = preflight_xlsx(path)

    assert result.path == path
    assert result.entry_count > 0
    assert result.compressed_file_bytes == path.stat().st_size
    assert result.total_expanded_bytes > 0
