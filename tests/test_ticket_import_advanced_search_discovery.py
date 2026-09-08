from __future__ import annotations

import zipfile
from datetime import UTC, datetime
from pathlib import Path

import pytest

from soma.foundation.errors import SomaError
from soma.ticket_import.parsing import discovery
from soma.ticket_import.parsing.discovery import discover_advanced_search_automatic
from soma.ticket_import.parsing.xlsx_security import XlsxPreflightResult


_CONTENT_TYPES = b"""<?xml version="1.0" encoding="UTF-8"?>
<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">
  <Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>
  <Default Extension="xml" ContentType="application/xml"/>
  <Override PartName="/xl/workbook.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/>
  <Override PartName="/xl/worksheets/sheet1.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/>
</Types>
"""
_ROOT_RELS = b"""<?xml version="1.0" encoding="UTF-8"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
  <Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="xl/workbook.xml"/>
</Relationships>
"""
_WORKBOOK = b"""<?xml version="1.0" encoding="UTF-8"?>
<workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"
          xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">
  <sheets><sheet name="Sheet1" sheetId="1" r:id="rId1"/></sheets>
</workbook>
"""
_WORKBOOK_RELS = b"""<?xml version="1.0" encoding="UTF-8"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
  <Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" Target="worksheets/sheet1.xml"/>
</Relationships>
"""
_SHEET = b"""<?xml version="1.0" encoding="UTF-8"?>
<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"><sheetData/></worksheet>
"""


def _write_safe_xlsx(directory: Path, filename: str) -> Path:
    path = directory / filename
    with zipfile.ZipFile(path, "w", compression=zipfile.ZIP_STORED) as archive:
        archive.writestr("[Content_Types].xml", _CONTENT_TYPES)
        archive.writestr("_rels/.rels", _ROOT_RELS)
        archive.writestr("xl/workbook.xml", _WORKBOOK)
        archive.writestr("xl/_rels/workbook.xml.rels", _WORKBOOK_RELS)
        archive.writestr("xl/worksheets/sheet1.xml", _SHEET)
    return path


def _no_sleep(_: float) -> None:
    return None


def _assert_error(code: str, call) -> SomaError:
    with pytest.raises(SomaError) as excinfo:
        call()
    assert excinfo.value.code == code
    return excinfo.value


def test_exact_newest_advanced_search_file_is_selected_with_cst_chronology(tmp_path: Path) -> None:
    _write_safe_xlsx(tmp_path, "Advanced Search(Service Request)20260905153045.xlsx")
    newest = _write_safe_xlsx(tmp_path, "Advanced Search(Service Request)20260906153045.xlsx")
    _write_safe_xlsx(tmp_path, "advanced Search(Service Request)20260907153045.xlsx")
    _write_safe_xlsx(tmp_path, "Advanced Search(Service Request)20260907153045 (1).xlsx")

    result = discover_advanced_search_automatic(tmp_path, sleep_fn=_no_sleep)

    assert result.path == newest.resolve()
    assert result.filename == newest.name
    assert result.source_family == "advanced_search_sr"
    assert result.profile_id == "ADVANCED_SEARCH_SR_V1"
    assert result.chronology_kind == "embedded_filename_timestamp_utc"
    assert result.chronology_value == int(datetime(2026, 9, 6, 7, 30, 45, tzinfo=UTC).timestamp())
    assert result.discovery_provenance == "automatic"
    assert result.stable_size_bytes == newest.stat().st_size


def test_invalid_gregorian_filename_is_ineligible_not_normalized(tmp_path: Path) -> None:
    valid = _write_safe_xlsx(tmp_path, "Advanced Search(Service Request)20260906153045.xlsx")
    _write_safe_xlsx(tmp_path, "Advanced Search(Service Request)20260230153045.xlsx")

    result = discover_advanced_search_automatic(tmp_path, sleep_fn=_no_sleep)
    assert result.path == valid.resolve()


def test_nested_candidate_is_never_discovered(tmp_path: Path) -> None:
    nested = tmp_path / "nested"
    nested.mkdir()
    _write_safe_xlsx(nested, "Advanced Search(Service Request)20260907153045.xlsx")
    direct = _write_safe_xlsx(tmp_path, "Advanced Search(Service Request)20260906153045.xlsx")

    result = discover_advanced_search_automatic(tmp_path, sleep_fn=_no_sleep)
    assert result.path == direct.resolve()


def test_missing_configuration_and_no_candidate_fail_truthfully(tmp_path: Path) -> None:
    _assert_error(
        "IMPORT_SOURCE_NOT_CONFIGURED",
        lambda: discover_advanced_search_automatic(None, sleep_fn=_no_sleep),
    )
    _assert_error(
        "IMPORT_SOURCE_UNAVAILABLE",
        lambda: discover_advanced_search_automatic(tmp_path, sleep_fn=_no_sleep),
    )


def test_relative_directory_is_not_accepted(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.chdir(tmp_path)
    _assert_error(
        "IMPORT_SOURCE_UNAVAILABLE",
        lambda: discover_advanced_search_automatic(Path("."), sleep_fn=_no_sleep),
    )


def test_unsafe_newest_candidate_never_falls_back_to_older_safe_file(tmp_path: Path) -> None:
    _write_safe_xlsx(tmp_path, "Advanced Search(Service Request)20260905153045.xlsx")
    newest = tmp_path / "Advanced Search(Service Request)20260906153045.xlsx"
    newest.write_bytes(b"not a safe XLSX")

    _assert_error(
        "XLSX_UNSAFE_CONTAINER",
        lambda: discover_advanced_search_automatic(tmp_path, sleep_fn=_no_sleep),
    )


def test_unstable_newest_candidate_never_falls_back(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    older = _write_safe_xlsx(tmp_path, "Advanced Search(Service Request)20260905153045.xlsx")
    newest = _write_safe_xlsx(tmp_path, "Advanced Search(Service Request)20260906153045.xlsx")
    real_probe = discovery._probe_stability

    def probe(path: Path, *, sleep_fn):
        if path == newest.resolve():
            raise SomaError("IMPORT_FILE_UNSTABLE", "injected active writer")
        return real_probe(path, sleep_fn=sleep_fn)

    monkeypatch.setattr(discovery, "_probe_stability", probe)
    _assert_error(
        "IMPORT_FILE_UNSTABLE",
        lambda: discover_advanced_search_automatic(tmp_path, sleep_fn=_no_sleep),
    )
    assert older.exists()


def test_unstable_older_candidate_does_not_override_selected_newest(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    older = _write_safe_xlsx(tmp_path, "Advanced Search(Service Request)20260905153045.xlsx")
    newest = _write_safe_xlsx(tmp_path, "Advanced Search(Service Request)20260906153045.xlsx")
    real_probe = discovery._probe_stability

    def probe(path: Path, *, sleep_fn):
        if path == older.resolve():
            raise SomaError("IMPORT_FILE_UNSTABLE", "injected old-file instability")
        return real_probe(path, sleep_fn=sleep_fn)

    monkeypatch.setattr(discovery, "_probe_stability", probe)
    result = discover_advanced_search_automatic(tmp_path, sleep_fn=_no_sleep)
    assert result.path == newest.resolve()


def test_writer_sharing_failure_never_counts_as_stable(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _write_safe_xlsx(tmp_path, "Advanced Search(Service Request)20260906153045.xlsx")
    monkeypatch.setattr(discovery, "_openable_without_writer", lambda path: False)

    _assert_error(
        "IMPORT_FILE_UNSTABLE",
        lambda: discover_advanced_search_automatic(tmp_path, sleep_fn=_no_sleep),
    )


def test_reparse_directory_is_rejected_before_enumeration(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(discovery, "_is_reparse_stat", lambda stat_result: True)
    _assert_error(
        "IMPORT_SOURCE_UNAVAILABLE",
        lambda: discover_advanced_search_automatic(tmp_path, sleep_fn=_no_sleep),
    )


def test_file_identity_swap_after_preflight_fails_closed(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    path = _write_safe_xlsx(tmp_path, "Advanced Search(Service Request)20260906153045.xlsx")
    stable = discovery._probe_stat(path.resolve())
    swapped = discovery._StableFile(
        stable.size_bytes,
        stable.mtime_ns,
        stable.device,
        stable.inode + 1,
    )
    monkeypatch.setattr(discovery, "_probe_stability", lambda path, sleep_fn: stable)
    monkeypatch.setattr(
        discovery,
        "preflight_xlsx",
        lambda selected: XlsxPreflightResult(selected, 5, selected.stat().st_size, 1),
    )
    monkeypatch.setattr(discovery, "_probe_stat", lambda selected: swapped)

    _assert_error(
        "IMPORT_FILE_UNSTABLE",
        lambda: discover_advanced_search_automatic(tmp_path, sleep_fn=_no_sleep),
    )
