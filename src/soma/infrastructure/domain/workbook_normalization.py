"""Versioned, allowlisted LLD-08 workbook replay representation."""

from __future__ import annotations

import hashlib
import re
import unicodedata2

from soma.foundation.errors import ValidationError
from soma.foundation.identifiers import require_uuid4
from soma.foundation.strict_json import canonical_json_bytes
from soma.infrastructure.contracts.infrastructure import validate_value
from soma.infrastructure.domain.relationships import normalize_ip
from soma.infrastructure.domain.workbooks import FORMAT_ID, HEADERS, WORKBOOK_VERSION
from soma.reference.domain.matching import trim_match_whitespace

NORMALIZED_ROW_VERSION = "INFRA_WORKBOOK_NORMALIZED_ROW_V1"
LOGICAL_VERSION = "INFRA_WORKBOOK_LOGICAL_V1"
_TEXT_KINDS = {
    "OperationalName": "network_element_name", "ManufacturerSerial": "manufacturer_serial",
    "ModelName": "model_name", "SiteName": "site_name", "SiteAddress": "site_address",
    "RoomName": "room_name", "RackName": "rack_name", "RackRow": "row_column_label",
    "RackColumn": "row_column_label", "CloudTypeName": "cloud_name",
    "CloudDeploymentName": "cloud_name", "ImportComment": "workbook_comment",
}
_IDENTITY_NAMES = frozenset(name for sheet in HEADERS.values() for name in sheet if name.startswith("Soma"))
_RACK_INTEGERS = frozenset({"RackHeightU", "RackUStart", "RackUSpan"})


def normalize_workbook_row(
    sheet: str, values: tuple[object, ...], *, same_installation: bool,
) -> tuple[dict, str]:
    if sheet not in ("Network Elements", "IP Addresses"):
        raise ValidationError("Unsupported Infrastructure workbook row sheet")
    headers = HEADERS[sheet]
    if len(values) > len(headers) and any(value is not None for value in values[len(headers):]):
        raise ValidationError("Workbook row exceeds its profile width")
    fields: dict[str, object] = {}
    for index, name in enumerate(headers):
        value = values[index] if index < len(values) else None
        if value == "":
            value = None
        if value is None:
            fields[name] = None
        elif name in _IDENTITY_NAMES:
            if not isinstance(value, str):
                raise ValidationError("Workbook identity must be text")
            fields[name] = require_uuid4(value) if same_installation else _foreign_provenance(value)
        elif name in _RACK_INTEGERS:
            if type(value) is not int or not 1 <= value <= 120:
                raise ValidationError("Workbook Rack value must be an exact bounded integer")
            fields[name] = value
        elif name == "Address":
            fields[name] = normalize_ip(value).canonical_text
        elif name == "Primary":
            if type(value) is not bool:
                raise ValidationError("Workbook Primary must be an explicit boolean")
            fields[name] = value
        elif name in _TEXT_KINDS:
            if not isinstance(value, str):
                raise ValidationError("Workbook descriptive value must be text")
            text = unicodedata2.normalize("NFC", trim_match_whitespace(value))
            fields[name] = validate_value(_TEXT_KINDS[name], text) if text else None
        else:
            raise ValidationError("Workbook row has an unrecognized field")
    if sheet == "IP Addresses" and fields["Address"] is None:
        raise ValidationError("Workbook IP row needs an address")
    row = {"version": NORMALIZED_ROW_VERSION, "sheet": sheet, "fields": fields}
    fingerprint = hashlib.sha256(canonical_json_bytes(row)).hexdigest()
    return row, fingerprint


def _foreign_provenance(value: str) -> str | None:
    value = unicodedata2.normalize("NFC", trim_match_whitespace(value))
    if not value:
        return None
    if len(value.encode("utf-8")) > 16_384 or "\x00" in value:
        raise ValidationError("Foreign workbook identity exceeds its cell bound")
    return value


def workbook_logical_fingerprint(
    *, mode: str, source_installation_scope_id: str, export_scope: dict,
    network_rows: list[str], ip_rows: list[str],
) -> str:
    """Hash semantic metadata and row multiset; row order is not identity."""
    from soma.infrastructure.domain.workbooks import MODES

    if mode not in MODES:
        raise ValidationError("Unsupported Infrastructure workbook mode")
    require_uuid4(source_installation_scope_id)
    scope = validate_value("INFRA_EXPORT_SCOPE_V1", export_scope)
    scope_field = {
        "all": None, "customer": "customer_org_id", "site": "site_id",
        "network_elements": "network_element_ids",
    }[scope["scope_kind"]]
    present = {key for key, value in scope.items() if key != "scope_kind" and value is not None}
    if present != ({scope_field} if scope_field is not None else set()):
        raise ValidationError("Workbook export scope fields disagree with scope_kind")
    if scope_field == "network_element_ids" and not scope[scope_field]:
        raise ValidationError("Workbook Network Element export scope is empty")
    if len(network_rows) > 100_000 or len(ip_rows) > 500_000:
        raise ValidationError("Workbook normalized row count exceeds its profile")
    if any(re.fullmatch(r"[0-9a-f]{64}", value) is None
           for value in network_rows + ip_rows):
        raise ValidationError("Workbook row fingerprint is invalid")
    content = {
        "version": LOGICAL_VERSION, "format_id": FORMAT_ID,
        "workbook_version": WORKBOOK_VERSION, "mode": mode,
        "source_installation_scope_id": source_installation_scope_id,
        "export_scope": scope,
        "network_elements": sorted(network_rows),
        "ip_addresses": sorted(ip_rows),
    }
    return hashlib.sha256(canonical_json_bytes(content)).hexdigest()
