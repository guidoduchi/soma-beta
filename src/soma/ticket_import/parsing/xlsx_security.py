from __future__ import annotations

import os
import posixpath
import re
import zipfile
from dataclasses import dataclass
from pathlib import Path
from xml.etree import ElementTree

from soma.foundation.errors import SomaError


MAX_COMPRESSED_FILE_BYTES = 104_857_600
MAX_TOTAL_EXPANDED_BYTES = 536_870_912
MAX_SINGLE_PART_BYTES = 134_217_728
MAX_ZIP_ENTRIES = 4_096
MAX_EXPANSION_RATIO = 100

_REQUIRED_PARTS = frozenset({
    "[Content_Types].xml",
    "_rels/.rels",
    "xl/workbook.xml",
    "xl/_rels/workbook.xml.rels",
})
_XML_SUFFIXES = (".xml", ".rels")
_DRIVE_PREFIX = re.compile(r"^[A-Za-z]:")
_ACTIVE_NAME_MARKERS = (
    "xl/activex/",
    "xl/embeddings/",
    "xl/externallinks/",
    "xl/vbaproject.bin",
    "xl/vbadata.xml",
)
_FORBIDDEN_CONTENT_TYPE_MARKERS = (
    "macroenabled",
    "vnd.ms-office.vbaproject",
    "activex",
    "oleobject",
)


@dataclass(frozen=True, slots=True)
class XlsxPreflightResult:
    path: Path
    entry_count: int
    compressed_file_bytes: int
    total_expanded_bytes: int


def _unsafe(message: str) -> SomaError:
    return SomaError("XLSX_UNSAFE_CONTAINER", message)


def _resource(message: str) -> SomaError:
    return SomaError("XLSX_RESOURCE_LIMIT", message)


def _normalize_part_name(raw: str) -> str:
    if not raw or "\x00" in raw or "\\" in raw:
        raise _unsafe("ZIP part name violates the normalized OOXML namespace")
    if raw.startswith("/") or _DRIVE_PREFIX.match(raw) or ":" in raw:
        raise _unsafe("ZIP part name uses an absolute, drive or alternate-stream form")
    parts = raw.split("/")
    if any(part in {"", ".", ".."} for part in parts if part != ""):
        # A trailing slash is permitted only for a directory entry; callers strip it first.
        raise _unsafe("ZIP part name contains ambiguous or traversal components")
    normalized = posixpath.normpath(raw)
    if normalized == ".." or normalized.startswith("../") or normalized.startswith("/"):
        raise _unsafe("ZIP part escapes the OOXML namespace")
    return normalized


def _read_bounded(zf: zipfile.ZipFile, info: zipfile.ZipInfo) -> bytes:
    if info.file_size > MAX_SINGLE_PART_BYTES:
        raise _resource("OOXML part exceeds the single-part expanded-byte ceiling")
    with zf.open(info, "r") as stream:
        data = stream.read(MAX_SINGLE_PART_BYTES + 1)
    if len(data) > MAX_SINGLE_PART_BYTES or len(data) != info.file_size:
        raise _resource("OOXML part expansion exceeded its declared or allowed size")
    return data


def _reject_xml_declarations(data: bytes) -> None:
    upper = data.upper()
    if b"<!DOCTYPE" in upper or b"<!ENTITY" in upper:
        raise _unsafe("OOXML XML contains a forbidden DTD/entity declaration")


def _validate_content_types(data: bytes) -> None:
    _reject_xml_declarations(data)
    try:
        root = ElementTree.fromstring(data)
    except ElementTree.ParseError as exc:
        raise _unsafe("OOXML content-types manifest is malformed") from exc
    for element in root.iter():
        value = element.attrib.get("ContentType", "").lower()
        if any(marker in value for marker in _FORBIDDEN_CONTENT_TYPE_MARKERS):
            raise _unsafe("OOXML content type declares active or macro-enabled content")


def _validate_relationships(data: bytes) -> None:
    _reject_xml_declarations(data)
    try:
        root = ElementTree.fromstring(data)
    except ElementTree.ParseError as exc:
        raise _unsafe("OOXML relationship part is malformed") from exc
    for relation in root.iter():
        if relation.tag.rsplit("}", 1)[-1] != "Relationship":
            continue
        target_mode = relation.attrib.get("TargetMode", "")
        target = relation.attrib.get("Target", "")
        rel_type = relation.attrib.get("Type", "").lower()
        if target_mode.lower() == "external":
            raise _unsafe("OOXML relationship requires an external resource")
        if any(marker in rel_type for marker in ("externallink", "attachedtemplate", "oleobject", "activex")):
            raise _unsafe("OOXML relationship declares unsupported active/external content")
        if target and (target.startswith("/") or "\\" in target or _DRIVE_PREFIX.match(target)):
            raise _unsafe("OOXML relationship target uses an unsafe path form")


def preflight_xlsx(path: str | os.PathLike[str]) -> XlsxPreflightResult:
    """Validate the XLSX ZIP/OOXML security boundary without extracting it.

    This function intentionally performs no workbook semantic parsing. A semantic reader may
    only receive a file after this preflight succeeds.
    """

    candidate = Path(path)
    try:
        stat_result = candidate.stat()
    except OSError as exc:
        raise SomaError("IMPORT_SOURCE_UNAVAILABLE", "selected workbook cannot be safely inspected") from exc
    if not candidate.is_file() or stat_result.st_size <= 0:
        raise _unsafe("selected workbook is not a nonempty regular ZIP-based XLSX file")
    if stat_result.st_size > MAX_COMPRESSED_FILE_BYTES:
        raise _resource("XLSX compressed file exceeds the configured ceiling")

    try:
        with zipfile.ZipFile(candidate, "r") as zf:
            infos = zf.infolist()
            if len(infos) > MAX_ZIP_ENTRIES:
                raise _resource("XLSX ZIP entry count exceeds the configured ceiling")

            normalized: dict[str, zipfile.ZipInfo] = {}
            total_expanded = 0
            for info in infos:
                raw = info.filename
                if info.is_dir():
                    raw = raw.rstrip("/")
                    if not raw:
                        continue
                name = _normalize_part_name(raw)
                if name in normalized:
                    raise _unsafe("XLSX contains duplicate normalized ZIP part names")
                normalized[name] = info
                if info.flag_bits & 0x1:
                    raise _unsafe("encrypted/password-protected XLSX archives are unsupported")
                if info.file_size < 0 or info.compress_size < 0:
                    raise _unsafe("XLSX ZIP metadata contains invalid part sizes")
                if info.file_size > MAX_SINGLE_PART_BYTES:
                    raise _resource("XLSX part exceeds the single-part expanded-byte ceiling")
                total_expanded += info.file_size
                if total_expanded > MAX_TOTAL_EXPANDED_BYTES:
                    raise _resource("XLSX expanded content exceeds the configured ceiling")
                if info.file_size:
                    if info.compress_size == 0 or info.file_size > info.compress_size * MAX_EXPANSION_RATIO:
                        raise _resource("XLSX part exceeds the expansion-ratio ceiling")
                lowered = name.lower()
                if any(marker in lowered for marker in _ACTIVE_NAME_MARKERS) or lowered.endswith(".bin"):
                    raise _unsafe("XLSX contains unsupported active or embedded package content")

            missing = _REQUIRED_PARTS.difference(normalized)
            if missing:
                raise _unsafe("XLSX is missing required workbook/content-type relationship parts")

            for name, info in normalized.items():
                lowered = name.lower()
                if lowered.endswith(_XML_SUFFIXES):
                    data = _read_bounded(zf, info)
                    _reject_xml_declarations(data)
                    if name == "[Content_Types].xml":
                        _validate_content_types(data)
                    if lowered.endswith(".rels"):
                        _validate_relationships(data)

            return XlsxPreflightResult(
                path=candidate,
                entry_count=len(infos),
                compressed_file_bytes=stat_result.st_size,
                total_expanded_bytes=total_expanded,
            )
    except (zipfile.BadZipFile, zipfile.LargeZipFile) as exc:
        raise _unsafe("selected workbook is not a supported ZIP-based OOXML container") from exc
