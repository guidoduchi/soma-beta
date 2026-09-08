from __future__ import annotations

import os
import posixpath
import re
import stat as stat_module
import zipfile
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import unquote, urlsplit
from xml.etree import ElementTree

from soma.foundation.errors import SomaError


MAX_COMPRESSED_FILE_BYTES = 104_857_600
MAX_TOTAL_EXPANDED_BYTES = 536_870_912
MAX_SINGLE_PART_BYTES = 134_217_728
MAX_ZIP_ENTRIES = 4_096
MAX_EXPANSION_RATIO = 100

_REQUIRED_PARTS = frozenset(
    {
        "[Content_Types].xml",
        "_rels/.rels",
        "xl/workbook.xml",
        "xl/_rels/workbook.xml.rels",
    }
)
_XML_SUFFIXES = (".xml", ".rels")
_DRIVE_PREFIX = re.compile(r"^[A-Za-z]:")
_WINDOWS_DEVICE_NAMES = frozenset(
    {"CON", "PRN", "AUX", "NUL", "CLOCK$"}
    | {f"COM{index}" for index in range(1, 10)}
    | {f"LPT{index}" for index in range(1, 10)}
)
_ACTIVE_NAME_MARKERS = (
    "activex/",
    "customui/",
    "embeddings/",
    "vbaproject.bin",
    "vbadata.xml",
)
_FORBIDDEN_CONTENT_TYPE_MARKERS = (
    "macroenabled",
    "vnd.ms-office.vbaproject",
    "activex",
    "oleobject",
)
_FORBIDDEN_RELATIONSHIP_TYPE_MARKERS = (
    "externallink",
    "attachedtemplate",
    "oleobject",
    "activex",
    "/package",
    "/connections",
    "/querytable",
)
_SUPPORTED_WORKBOOK_CONTENT_TYPE = (
    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"
)
_ALLOWED_COMPRESSION = frozenset({zipfile.ZIP_STORED, zipfile.ZIP_DEFLATED})


@dataclass(frozen=True, slots=True)
class XlsxPreflightResult:
    path: Path
    entry_count: int
    compressed_file_bytes: int
    total_expanded_bytes: int


@dataclass(frozen=True, slots=True)
class _Relationship:
    relationship_type: str
    target_part: str


def _unsafe(message: str) -> SomaError:
    return SomaError("XLSX_UNSAFE_CONTAINER", message)


def _resource(message: str) -> SomaError:
    return SomaError("XLSX_RESOURCE_LIMIT", message)


def _validate_part_segment(segment: str) -> None:
    if not segment or segment == ".":
        return
    if segment == "..":
        raise _unsafe("ZIP part name contains parent traversal")
    if segment[-1:] in {" ", "."}:
        raise _unsafe("ZIP part name contains a Windows-ambiguous segment")
    if any(ord(character) < 32 for character in segment):
        raise _unsafe("ZIP part name contains a control character")
    device_base = segment.split(".", 1)[0].upper()
    if device_base in _WINDOWS_DEVICE_NAMES:
        raise _unsafe("ZIP part name contains a Windows device-like segment")


def _normalize_part_name(raw: str) -> str:
    if not raw or "\x00" in raw or "\\" in raw:
        raise _unsafe("ZIP part name violates the normalized OOXML namespace")
    if raw.startswith("/") or _DRIVE_PREFIX.match(raw) or ":" in raw:
        raise _unsafe("ZIP part name uses an absolute, drive or alternate-stream form")
    for segment in raw.split("/"):
        _validate_part_segment(segment)
    normalized = posixpath.normpath(raw)
    if normalized in {"", ".", ".."} or normalized.startswith("../") or normalized.startswith("/"):
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


def _parse_xml(data: bytes, *, label: str) -> ElementTree.Element:
    _reject_xml_declarations(data)
    try:
        return ElementTree.fromstring(data)
    except ElementTree.ParseError as exc:
        raise _unsafe(f"OOXML {label} is malformed") from exc


def _validate_content_types(data: bytes) -> None:
    root = _parse_xml(data, label="content-types manifest")
    workbook_declared = False
    for element in root.iter():
        local_name = element.tag.rsplit("}", 1)[-1]
        content_type = element.attrib.get("ContentType", "").lower()
        if any(marker in content_type for marker in _FORBIDDEN_CONTENT_TYPE_MARKERS):
            raise _unsafe("OOXML content type declares active or macro-enabled content")
        if local_name == "Override":
            part_name = element.attrib.get("PartName", "")
            if part_name == "/xl/workbook.xml" and content_type == _SUPPORTED_WORKBOOK_CONTENT_TYPE:
                workbook_declared = True
    if not workbook_declared:
        raise _unsafe("OOXML content types do not declare a supported XLSX workbook")


def _relationship_base_directory(relationship_part_name: str) -> str:
    if relationship_part_name == "_rels/.rels":
        return ""
    marker = "/_rels/"
    if marker not in relationship_part_name or not relationship_part_name.endswith(".rels"):
        raise _unsafe("OOXML relationship part name is not structurally valid")
    prefix, relation_name = relationship_part_name.rsplit(marker, 1)
    source_name = relation_name[:-5]
    if not source_name:
        raise _unsafe("OOXML relationship part has no source part")
    return posixpath.dirname(posixpath.join(prefix, source_name))


def _resolve_relationship_target(relationship_part_name: str, target: str) -> str:
    if not target:
        raise _unsafe("OOXML relationship target is empty")
    parsed = urlsplit(target)
    if parsed.scheme or parsed.netloc or parsed.query or parsed.fragment:
        raise _unsafe("OOXML relationship target references an external or non-part URI")
    decoded = unquote(parsed.path)
    if not decoded or decoded.startswith("/") or "\\" in decoded or _DRIVE_PREFIX.match(decoded):
        raise _unsafe("OOXML relationship target uses an unsafe path form")
    base_directory = _relationship_base_directory(relationship_part_name)
    resolved = posixpath.normpath(posixpath.join(base_directory, decoded))
    if resolved == ".." or resolved.startswith("../") or resolved.startswith("/"):
        raise _unsafe("OOXML relationship target escapes the package namespace")
    return _normalize_part_name(resolved)


def _validate_relationships(
    data: bytes,
    *,
    relationship_part_name: str,
    known_parts: frozenset[str],
) -> tuple[_Relationship, ...]:
    root = _parse_xml(data, label="relationship part")
    relationships: list[_Relationship] = []
    for relation in root.iter():
        if relation.tag.rsplit("}", 1)[-1] != "Relationship":
            continue
        target_mode = relation.attrib.get("TargetMode", "")
        target = relation.attrib.get("Target", "")
        relationship_type = relation.attrib.get("Type", "")
        lowered_type = relationship_type.lower()
        if target_mode.lower() == "external":
            raise _unsafe("OOXML relationship requires an external resource")
        if any(marker in lowered_type for marker in _FORBIDDEN_RELATIONSHIP_TYPE_MARKERS):
            raise _unsafe("OOXML relationship declares unsupported active/external content")
        target_part = _resolve_relationship_target(relationship_part_name, target)
        if target_part not in known_parts:
            raise _unsafe("OOXML relationship targets a missing package part")
        relationships.append(_Relationship(relationship_type, target_part))
    return tuple(relationships)


def _validate_required_relationship_graph(
    relationship_sets: dict[str, tuple[_Relationship, ...]],
) -> None:
    root_office_documents = tuple(
        relation
        for relation in relationship_sets.get("_rels/.rels", ())
        if relation.relationship_type.lower().endswith("/officedocument")
    )
    if len(root_office_documents) != 1 or root_office_documents[0].target_part != "xl/workbook.xml":
        raise _unsafe("OOXML package does not designate exactly one supported workbook root")

    workbook_worksheets = tuple(
        relation
        for relation in relationship_sets.get("xl/_rels/workbook.xml.rels", ())
        if relation.relationship_type.lower().endswith("/worksheet")
    )
    if not workbook_worksheets:
        raise _unsafe("OOXML workbook has no supported worksheet relationship")
    if any(not relation.target_part.startswith("xl/worksheets/") for relation in workbook_worksheets):
        raise _unsafe("OOXML worksheet relationship resolves outside the supported worksheet namespace")


def _is_symlink_entry(info: zipfile.ZipInfo) -> bool:
    unix_mode = (info.external_attr >> 16) & 0xFFFF
    return stat_module.S_IFMT(unix_mode) == stat_module.S_IFLNK


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
                # ZipInfo.filename is normalized to forward slashes on Windows. Security
                # validation must inspect the original decoded central-directory name first.
                raw = info.orig_filename
                if info.is_dir():
                    raw = raw.rstrip("/")
                    if not raw:
                        continue
                name = _normalize_part_name(raw)
                if name in normalized:
                    raise _unsafe("XLSX contains duplicate normalized ZIP part names")
                normalized[name] = info
                if _is_symlink_entry(info):
                    raise _unsafe("XLSX contains a symbolic-link ZIP entry")
                if info.flag_bits & 0x1:
                    raise _unsafe("encrypted/password-protected XLSX archives are unsupported")
                if info.compress_type not in _ALLOWED_COMPRESSION:
                    raise _unsafe("XLSX uses an unsupported ZIP compression method")
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
                if any(marker in lowered for marker in _ACTIVE_NAME_MARKERS):
                    raise _unsafe("XLSX contains unsupported active or embedded package content")

            missing = _REQUIRED_PARTS.difference(normalized)
            if missing:
                raise _unsafe("XLSX is missing required workbook/content-type relationship parts")

            known_parts = frozenset(normalized)
            relationship_sets: dict[str, tuple[_Relationship, ...]] = {}
            for name, info in normalized.items():
                lowered = name.lower()
                if lowered.endswith(_XML_SUFFIXES):
                    data = _read_bounded(zf, info)
                    _reject_xml_declarations(data)
                    if name == "[Content_Types].xml":
                        _validate_content_types(data)
                    if lowered.endswith(".rels"):
                        relationship_sets[name] = _validate_relationships(
                            data,
                            relationship_part_name=name,
                            known_parts=known_parts,
                        )

            _validate_required_relationship_graph(relationship_sets)
            return XlsxPreflightResult(
                path=candidate,
                entry_count=len(infos),
                compressed_file_bytes=stat_result.st_size,
                total_expanded_bytes=total_expanded,
            )
    except (zipfile.BadZipFile, zipfile.LargeZipFile) as exc:
        raise _unsafe("selected workbook is not a supported ZIP-based OOXML container") from exc
