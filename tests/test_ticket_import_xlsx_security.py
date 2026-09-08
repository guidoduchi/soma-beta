from __future__ import annotations

import stat
import zipfile
from pathlib import Path

import pytest

from soma.foundation.errors import SomaError
from soma.ticket_import.parsing import xlsx_security
from soma.ticket_import.parsing.xlsx_security import preflight_xlsx


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


def _write_xlsx(
    path: Path,
    *,
    content_types: bytes = _CONTENT_TYPES,
    root_rels: bytes = _ROOT_RELS,
    workbook: bytes = _WORKBOOK,
    workbook_rels: bytes = _WORKBOOK_RELS,
    sheet: bytes = _SHEET,
    extras: tuple[tuple[str | zipfile.ZipInfo, bytes, int], ...] = (),
) -> Path:
    with zipfile.ZipFile(path, "w", compression=zipfile.ZIP_STORED) as archive:
        archive.writestr("[Content_Types].xml", content_types)
        archive.writestr("_rels/.rels", root_rels)
        archive.writestr("xl/workbook.xml", workbook)
        archive.writestr("xl/_rels/workbook.xml.rels", workbook_rels)
        archive.writestr("xl/worksheets/sheet1.xml", sheet)
        for name, payload, compression in extras:
            archive.writestr(name, payload, compress_type=compression)
    return path


def _assert_code(path: Path, code: str) -> SomaError:
    with pytest.raises(SomaError) as excinfo:
        preflight_xlsx(path)
    assert excinfo.value.code == code
    return excinfo.value


def _set_zip_encrypted_flag(path: Path) -> None:
    data = bytearray(path.read_bytes())
    for signature, flag_offset in ((b"PK\x03\x04", 6), (b"PK\x01\x02", 8)):
        offset = 0
        found = False
        while True:
            index = data.find(signature, offset)
            if index < 0:
                break
            found = True
            flags_index = index + flag_offset
            flags = int.from_bytes(data[flags_index : flags_index + 2], "little") | 0x1
            data[flags_index : flags_index + 2] = flags.to_bytes(2, "little")
            offset = index + 4
        assert found
    path.write_bytes(data)


def test_valid_minimal_inert_xlsx_passes_preflight(tmp_path: Path) -> None:
    path = _write_xlsx(tmp_path / "safe.xlsx")
    result = preflight_xlsx(path)
    assert result.path == path
    assert result.entry_count == 5
    assert result.compressed_file_bytes == path.stat().st_size
    assert result.total_expanded_bytes > 0


@pytest.mark.parametrize(
    "malicious_name",
    (
        "../escape.xml",
        "/absolute.xml",
        "C:/drive.xml",
        "xl\\backslash.xml",
        "xl/CON/device.xml",
        "xl/stream:name.xml",
    ),
)
def test_unsafe_zip_part_names_are_rejected(tmp_path: Path, malicious_name: str) -> None:
    path = _write_xlsx(
        tmp_path / "unsafe-name.xlsx",
        extras=((malicious_name, b"<x/>", zipfile.ZIP_STORED),),
    )
    _assert_code(path, "XLSX_UNSAFE_CONTAINER")


def test_duplicate_normalized_zip_part_is_rejected(tmp_path: Path) -> None:
    path = _write_xlsx(
        tmp_path / "duplicate.xlsx",
        extras=(("xl/worksheets/./sheet1.xml", _SHEET, zipfile.ZIP_STORED),),
    )
    _assert_code(path, "XLSX_UNSAFE_CONTAINER")


def test_symbolic_link_zip_entry_is_rejected(tmp_path: Path) -> None:
    symlink = zipfile.ZipInfo("xl/evil-link.xml")
    symlink.create_system = 3
    symlink.external_attr = (stat.S_IFLNK | 0o777) << 16
    path = _write_xlsx(
        tmp_path / "symlink.xlsx",
        extras=((symlink, b"xl/workbook.xml", zipfile.ZIP_STORED),),
    )
    _assert_code(path, "XLSX_UNSAFE_CONTAINER")


def test_encrypted_zip_flag_is_rejected_before_semantic_read(tmp_path: Path) -> None:
    path = _write_xlsx(tmp_path / "encrypted.xlsx")
    _set_zip_encrypted_flag(path)
    _assert_code(path, "XLSX_UNSAFE_CONTAINER")


@pytest.mark.parametrize(
    "active_name",
    (
        "xl/vbaProject.bin",
        "xl/activeX/activeX1.xml",
        "xl/embeddings/oleObject1.bin",
    ),
)
def test_active_or_embedded_parts_are_rejected(tmp_path: Path, active_name: str) -> None:
    path = _write_xlsx(
        tmp_path / "active.xlsx",
        extras=((active_name, b"active", zipfile.ZIP_STORED),),
    )
    _assert_code(path, "XLSX_UNSAFE_CONTAINER")


def test_macro_content_type_cannot_hide_behind_xlsx_extension(tmp_path: Path) -> None:
    macro_types = _CONTENT_TYPES.replace(
        b"application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml",
        b"application/vnd.ms-excel.sheet.macroEnabled.main+xml",
    )
    path = _write_xlsx(tmp_path / "renamed-macro.xlsx", content_types=macro_types)
    _assert_code(path, "XLSX_UNSAFE_CONTAINER")


def test_external_relationship_is_rejected_without_fetching(tmp_path: Path) -> None:
    external_rels = b"""<?xml version="1.0" encoding="UTF-8"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
  <Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" Target="worksheets/sheet1.xml"/>
  <Relationship Id="rId2" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/externalLink" Target="https://example.invalid/book.xlsx" TargetMode="External"/>
</Relationships>
"""
    path = _write_xlsx(tmp_path / "external.xlsx", workbook_rels=external_rels)
    _assert_code(path, "XLSX_UNSAFE_CONTAINER")


def test_uri_scheme_is_rejected_even_if_target_mode_is_omitted(tmp_path: Path) -> None:
    malicious_rels = b"""<?xml version="1.0" encoding="UTF-8"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
  <Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" Target="https://example.invalid/sheet.xml"/>
</Relationships>
"""
    path = _write_xlsx(tmp_path / "scheme.xlsx", workbook_rels=malicious_rels)
    _assert_code(path, "XLSX_UNSAFE_CONTAINER")


def test_missing_relationship_target_is_rejected(tmp_path: Path) -> None:
    missing_target_rels = _WORKBOOK_RELS.replace(b"worksheets/sheet1.xml", b"worksheets/missing.xml")
    path = _write_xlsx(tmp_path / "missing-target.xlsx", workbook_rels=missing_target_rels)
    _assert_code(path, "XLSX_UNSAFE_CONTAINER")


def test_package_must_designate_supported_workbook_root(tmp_path: Path) -> None:
    wrong_root_rels = _ROOT_RELS.replace(b"xl/workbook.xml", b"xl/worksheets/sheet1.xml")
    path = _write_xlsx(tmp_path / "wrong-root.xlsx", root_rels=wrong_root_rels)
    _assert_code(path, "XLSX_UNSAFE_CONTAINER")


def test_content_types_must_designate_standard_xlsx_workbook(tmp_path: Path) -> None:
    unsupported_types = _CONTENT_TYPES.replace(
        b"application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml",
        b"application/xml",
    )
    path = _write_xlsx(tmp_path / "wrong-content-type.xlsx", content_types=unsupported_types)
    _assert_code(path, "XLSX_UNSAFE_CONTAINER")


@pytest.mark.parametrize("declaration", (b"<!DOCTYPE workbook>", b"<!ENTITY x 'boom'>"))
def test_dtd_and_entity_declarations_are_rejected_before_xml_parse(tmp_path: Path, declaration: bytes) -> None:
    workbook = declaration + _WORKBOOK
    path = _write_xlsx(tmp_path / "xml-declaration.xlsx", workbook=workbook)
    error = _assert_code(path, "XLSX_UNSAFE_CONTAINER")
    assert "boom" not in str(error)


def test_expansion_ratio_limit_is_enforced_before_part_materialization(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(xlsx_security, "MAX_EXPANSION_RATIO", 2)
    path = _write_xlsx(
        tmp_path / "ratio.xlsx",
        extras=(("xl/worksheets/compressed.xml", b"A" * 4096, zipfile.ZIP_DEFLATED),),
    )
    _assert_code(path, "XLSX_RESOURCE_LIMIT")


def test_entry_count_limit_is_enforced(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(xlsx_security, "MAX_ZIP_ENTRIES", 4)
    path = _write_xlsx(tmp_path / "entries.xlsx")
    _assert_code(path, "XLSX_RESOURCE_LIMIT")


def test_bad_zip_is_mapped_to_closed_container_error(tmp_path: Path) -> None:
    path = tmp_path / "not-a-zip.xlsx"
    path.write_bytes(b"not a zip and no source data should leak")
    error = _assert_code(path, "XLSX_UNSAFE_CONTAINER")
    assert "source data" not in str(error)
