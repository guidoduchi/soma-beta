from __future__ import annotations

from collections.abc import Iterable, Sequence
from datetime import datetime, timezone
import hashlib
import posixpath
import tempfile
from typing import BinaryIO
import zipfile
from xml.etree import ElementTree

from openpyxl import Workbook, load_workbook
from openpyxl.cell import WriteOnlyCell

from soma.foundation.errors import ValidationError
from soma.foundation.identifiers import require_uuid4
from soma.foundation.strict_json import canonical_json_bytes, loads_strict
from soma.infrastructure.contracts.infrastructure import validate_value
from soma.infrastructure.domain.workbooks import (
    FORMAT_ID, HEADERS, METADATA_KEYS, MODES, SHEET_ORDER, WORKBOOK_VERSION,
)

_GENERATED_PARTS = frozenset({
    "docProps/app.xml", "docProps/core.xml", "xl/theme/theme1.xml",
    "xl/worksheets/sheet1.xml", "xl/worksheets/sheet2.xml",
    "xl/worksheets/sheet3.xml", "xl/styles.xml", "_rels/.rels",
    "xl/workbook.xml", "xl/_rels/workbook.xml.rels", "[Content_Types].xml",
})


def _cell(sheet, value):
    if value is not None and type(value) not in (str, int, bool):
        raise ValidationError("Workbook cells must be text, exact integers or booleans")
    if isinstance(value, str):
        try:
            encoded = value.encode("utf-8", errors="strict")
        except UnicodeError as exc:
            raise ValidationError("Workbook cell text is not valid UTF-8") from exc
        if len(encoded) > 16_384 or "\x00" in value:
            raise ValidationError("Workbook cell text violates the profile bound")
    cell = WriteOnlyCell(sheet, value=value)
    if isinstance(value, str):
        # openpyxl otherwise treats leading '=' as an executable formula.
        cell.data_type = "s"
    return cell


def _verify_cell(cell) -> None:
    if cell.data_type == "f":
        raise ValidationError("Workbook contains a formula")
    value = cell.value
    if value is not None and type(value) not in (str, int, bool):
        raise ValidationError("Workbook contains an unsupported cell value")
    if isinstance(value, str):
        try:
            encoded = value.encode("utf-8", errors="strict")
        except UnicodeError as exc:
            raise ValidationError("Workbook cell text is not valid UTF-8") from exc
        if len(encoded) > 16_384 or "\x00" in value:
            raise ValidationError("Workbook cell text violates the profile bound")


def _append_rows(sheet, rows: Iterable[Sequence[object]], *, maximum: int) -> int:
    count = 0
    width = len(HEADERS[sheet.title])
    for row in rows:
        count += 1
        if count > maximum:
            raise ValidationError("Infrastructure workbook row count exceeds its profile")
        if not isinstance(row, (tuple, list)) or len(row) != width:
            raise ValidationError("Infrastructure workbook row does not match its header")
        if sheet.title == "Network Elements":
            for index in (0, 3, 5, 8, 10, 17, 20):
                if row[index] is not None:
                    require_uuid4(row[index])
            for index in (12, 15, 16):
                value = row[index]
                if value is not None and (type(value) is not int or not 1 <= value <= 120):
                    raise ValidationError("Rack values must be exact integers in 1..120")
        else:
            for index in (0, 1):
                if row[index] is not None:
                    require_uuid4(row[index])
            if not isinstance(row[3], str) or not row[3]:
                raise ValidationError("Exported IP address must be text")
            if type(row[4]) is not bool:
                raise ValidationError("Exported IP primary value must be TRUE or FALSE")
        sheet.append([_cell(sheet, value) for value in row])
    return count


def write_profile_workbook(
    stream: BinaryIO,
    *,
    mode: str,
    scope: dict,
    data_instance_id: str,
    generated_at_utc: int,
    network_elements: Iterable[Sequence[object]] = (),
    ip_addresses: Iterable[Sequence[object]] = (),
) -> tuple[int, int]:
    """Write a bounded profile workbook to a caller-owned unpublished stream."""
    if mode not in MODES:
        raise ValidationError("Unsupported Infrastructure workbook mode")
    require_uuid4(data_instance_id)
    if type(generated_at_utc) is not int or generated_at_utc < 0:
        raise ValidationError("Workbook generation timestamp must be a UTC epoch second")
    validated_scope = validate_value("INFRA_EXPORT_SCOPE_V1", scope)
    scope_field = {
        "all": None,
        "customer": "customer_org_id",
        "site": "site_id",
        "network_elements": "network_element_ids",
    }[validated_scope["scope_kind"]]
    present = {key for key, value in validated_scope.items()
               if key != "scope_kind" and value is not None}
    if present != ({scope_field} if scope_field is not None else set()):
        raise ValidationError("Workbook export scope fields disagree with scope_kind")
    if scope_field == "network_element_ids" and not validated_scope[scope_field]:
        raise ValidationError("Network Element export scope cannot be empty")
    try:
        generated_at_text = datetime.fromtimestamp(
            generated_at_utc, timezone.utc
        ).strftime("%Y-%m-%dT%H:%M:%SZ")
    except (OverflowError, OSError, ValueError) as exc:
        raise ValidationError("Workbook generation timestamp is out of range") from exc
    metadata = (
        FORMAT_ID, WORKBOOK_VERSION, mode, data_instance_id,
        generated_at_text,
        canonical_json_bytes(validated_scope).decode("utf-8"),
    )
    workbook = Workbook(write_only=True)
    sheets = {name: workbook.create_sheet(name) for name in SHEET_ORDER}
    for name, sheet in sheets.items():
        sheet.append([_cell(sheet, value) for value in HEADERS[name]])
    metadata_sheet = sheets["Metadata"]
    for key, value in zip(METADATA_KEYS, metadata):
        metadata_sheet.append([_cell(metadata_sheet, key), _cell(metadata_sheet, value)])
    network_count = _append_rows(
        sheets["Network Elements"], network_elements, maximum=100_000,
    )
    ip_count = _append_rows(sheets["IP Addresses"], ip_addresses, maximum=500_000)
    if mode == "registration_template" and (network_count or ip_count):
        raise ValidationError("Registration template must contain only headers")
    workbook.save(stream)
    return network_count, ip_count


def verify_profile_workbook(
    stream: BinaryIO,
    *,
    mode: str,
    data_instance_id: str,
    expected_scope: dict,
    expected_generated_at_utc: int,
    expected_network_rows: int,
    expected_ip_rows: int,
) -> tuple[str, int]:
    """Verify one captured unpublished workbook and return its SHA-256 and size."""
    if mode not in MODES:
        raise ValidationError("Unsupported Infrastructure workbook mode")
    require_uuid4(data_instance_id)
    validated_scope = validate_value("INFRA_EXPORT_SCOPE_V1", expected_scope)
    if type(expected_generated_at_utc) is not int or expected_generated_at_utc < 0:
        raise ValidationError("Expected workbook generation time is invalid")
    try:
        expected_time = datetime.fromtimestamp(
            expected_generated_at_utc, timezone.utc,
        ).strftime("%Y-%m-%dT%H:%M:%SZ")
    except (OverflowError, OSError, ValueError) as exc:
        raise ValidationError("Expected workbook generation time is out of range") from exc
    if any(type(value) is not int or value < 0 for value in
           (expected_network_rows, expected_ip_rows)):
        raise ValidationError("Expected workbook row counts must be nonnegative integers")
    digest = hashlib.sha256()
    size = 0
    with tempfile.SpooledTemporaryFile(max_size=8_388_608) as captured:
        stream.seek(0)
        while chunk := stream.read(1_048_576):
            size += len(chunk)
            if size > 268_435_456:
                raise ValidationError("Workbook exceeds the compressed file bound")
            digest.update(chunk)
            captured.write(chunk)
        if size == 0:
            raise ValidationError("Workbook is empty")
        captured.seek(0)
        try:
            with zipfile.ZipFile(captured) as archive:
                infos = archive.infolist()
                if len(infos) > 20_000 or sum(info.file_size for info in infos) > 1_073_741_824:
                    raise ValidationError("Workbook archive exceeds its resource bounds")
                seen = set()
                for info in infos:
                    name = info.filename
                    parts = name.split("/")
                    key = name.casefold()
                    if (not name or name.startswith("/") or ":" in name or "\\" in name or "\x00" in name
                            or any(part in ("", ".", "..") for part in parts[:-1])
                            or key in seen or posixpath.normpath(name) != name):
                        raise ValidationError("Workbook archive has an unsafe or duplicate part")
                    seen.add(key)
                    lower = name.lower()
                    if any(marker in lower for marker in (
                        "vbaproject", "activex/", "embeddings/", "externallinks/",
                        "oleobject", "customui/",
                    )):
                        raise ValidationError("Workbook contains active or external content")
                    if lower.endswith(".rels") or name == "[Content_Types].xml":
                        if info.file_size > 1_048_576:
                            raise ValidationError("Workbook relationship metadata is too large")
                        raw = archive.read(info)
                        try:
                            root = ElementTree.fromstring(raw)
                        except ElementTree.ParseError as exc:
                            raise ValidationError("Workbook relationship metadata is malformed") from exc
                        for node in root.iter():
                            attributes = {key.rsplit("}", 1)[-1].lower(): value.lower()
                                          for key, value in node.attrib.items()}
                            if attributes.get("targetmode") == "external":
                                raise ValidationError("Workbook contains an external relationship")
                            if any("macroenabled" in value or "vba" in value
                                   for value in attributes.values()):
                                raise ValidationError("Workbook contains macro-enabled content")
                if {info.filename for info in infos} != _GENERATED_PARTS:
                    raise ValidationError("Workbook archive parts differ from generated profile")
            captured.seek(0)
            workbook = load_workbook(captured, read_only=True, data_only=False, keep_links=False)
            try:
                if workbook.sheetnames != list(SHEET_ORDER):
                    raise ValidationError("Workbook sheet order differs from the profile")
                for name in SHEET_ORDER:
                    sheet = workbook[name]
                    if sheet.sheet_state != "visible":
                        raise ValidationError("Workbook has a hidden authoritative sheet")
                    iterator = sheet.iter_rows()
                    header = tuple(cell.value for cell in next(iterator, ()))
                    if header != HEADERS[name]:
                        raise ValidationError("Workbook header differs from the profile")
                    if name == "Metadata":
                        metadata = []
                        for row in iterator:
                            if len(row) != len(HEADERS[name]):
                                raise ValidationError("Workbook metadata row width differs from the profile")
                            for cell in row:
                                _verify_cell(cell)
                            metadata.append(tuple(cell.value for cell in row))
                            if len(metadata) > 128:
                                raise ValidationError("Workbook metadata exceeds its row bound")
                        if tuple(key for key, _ in metadata) != METADATA_KEYS:
                            raise ValidationError("Workbook metadata keys differ from the profile")
                        values = dict(metadata)
                        if (values["FormatId"] != FORMAT_ID
                                or values["WorkbookVersion"] != WORKBOOK_VERSION
                                or values["Mode"] != mode
                                or values["SourceInstallationScopeId"] != data_instance_id):
                            raise ValidationError("Workbook metadata differs from the expected profile")
                        try:
                            export_scope = loads_strict(values["ExportScopeJson"], max_bytes=65_536)
                            parsed_scope = validate_value("INFRA_EXPORT_SCOPE_V1", export_scope)
                        except (TypeError, ValueError) as exc:
                            raise ValidationError("Workbook metadata values are malformed") from exc
                        if (parsed_scope != validated_scope
                                or values["GeneratedAtUtc"] != expected_time):
                            raise ValidationError("Workbook metadata differs from generation inputs")
                        continue
                    count = 0
                    maximum = 100_000 if name == "Network Elements" else 500_000
                    for row in iterator:
                        count += 1
                        if count > maximum:
                            raise ValidationError("Workbook row count exceeds its profile")
                        if len(row) > len(HEADERS[name]):
                            raise ValidationError("Workbook row width exceeds its header")
                        for cell in row:
                            _verify_cell(cell)
                    expected = expected_network_rows if name == "Network Elements" else expected_ip_rows
                    if count != expected:
                        raise ValidationError("Workbook row count differs from verified generation")
            finally:
                workbook.close()
        except (zipfile.BadZipFile, zipfile.LargeZipFile, KeyError,
                ElementTree.ParseError, OSError, EOFError) as exc:
            raise ValidationError("Workbook is not a valid profile XLSX archive") from exc
    return digest.hexdigest(), size
