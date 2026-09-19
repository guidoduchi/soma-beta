from __future__ import annotations

import regex

from soma.foundation.errors import ValidationError
from soma.reference.domain.matching import trim_match_whitespace

from .needs import normalize_optional_serial, normalize_part_code, validate_effective_at_utc

_SPARE_CONDITIONS = frozenset({"new", "used", "faulty", "incompatible", "unknown"})
_REGISTER_ORIGINS = frozenset({"manual_local", "legacy", "reviewed_reconciliation"})
_AVAILABLE_CONDITIONS = frozenset({"new", "used"})


def validate_spare_part_origin(value: str) -> str:
    if value not in _REGISTER_ORIGINS:
        raise ValidationError("Spare Part Unit origin is invalid for this command")
    return value


def validate_spare_condition(value: str | None) -> str:
    if value is None:
        return "unknown"
    if value not in _SPARE_CONDITIONS:
        raise ValidationError("Spare Part Unit condition_token is invalid")
    return value


def initial_disposition_for_condition(condition_token: str) -> str:
    if condition_token in _AVAILABLE_CONDITIONS:
        return "available"
    return "unavailable"


def validate_unit_effective_at_utc(value: int | None) -> int | None:
    return validate_effective_at_utc(value)


def _optional_text(
    value: str | None,
    *,
    field: str,
    max_graphemes: int,
    max_utf8_bytes: int,
) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise ValidationError(f"{field} must be text or null")
    stored = trim_match_whitespace(value)
    if not stored:
        return None
    if "\x00" in stored or "\r" in stored or "\n" in stored:
        raise ValidationError(f"{field} contains a forbidden control/newline")
    if len(stored.encode("utf-8", errors="strict")) > max_utf8_bytes:
        raise ValidationError(f"{field} exceeds its UTF-8 byte bound")
    if len(regex.findall(r"\X", stored)) > max_graphemes:
        raise ValidationError(f"{field} exceeds its grapheme bound")
    return stored


def normalize_location_kind(value: str | None) -> str | None:
    return _optional_text(
        value,
        field="location_kind",
        max_graphemes=80,
        max_utf8_bytes=320,
    )


def normalize_location_ref(value: str | None) -> str | None:
    return _optional_text(
        value,
        field="location_ref_id",
        max_graphemes=160,
        max_utf8_bytes=640,
    )


def normalize_custody_text(value: str | None) -> str | None:
    return _optional_text(
        value,
        field="custody_text",
        max_graphemes=160,
        max_utf8_bytes=640,
    )


def normalize_spare_part_identity(
    bom_code: str,
    manufacturer_serial: str | None,
) -> tuple[str, str, str | None, str | None]:
    stored_bom, bom_key = normalize_part_code(bom_code)
    stored_serial, serial_key = normalize_optional_serial(manufacturer_serial)
    return stored_bom, bom_key, stored_serial, serial_key


__all__ = [
    "initial_disposition_for_condition",
    "normalize_custody_text",
    "normalize_location_kind",
    "normalize_location_ref",
    "normalize_spare_part_identity",
    "validate_spare_condition",
    "validate_spare_part_origin",
    "validate_unit_effective_at_utc",
]
