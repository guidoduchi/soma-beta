from __future__ import annotations

import regex as regex_module

from soma.foundation.errors import ValidationError
from soma.reference.domain.matching import normalize_match_key, trim_match_whitespace

_CONDITION_TOKENS = {"unknown", "normal", "faulty", "removed", "installed", "quarantined"}


def _bounded_text(
    value: str,
    *,
    field: str,
    max_graphemes: int,
    max_utf8_bytes: int,
    blank_allowed: bool,
) -> str:
    if not isinstance(value, str):
        raise ValidationError(f"{field} must be text")
    stored = trim_match_whitespace(value)
    if not stored and not blank_allowed:
        raise ValidationError(f"{field} cannot be blank")
    if "\x00" in stored or "\r" in stored or "\n" in stored:
        raise ValidationError(f"{field} must be one line")
    if len(stored.encode("utf-8", errors="strict")) > max_utf8_bytes:
        raise ValidationError(f"{field} exceeds its UTF-8 bound")
    if len(regex_module.findall(r"\X", stored)) > max_graphemes:
        raise ValidationError(f"{field} exceeds its grapheme bound")
    return stored


def normalize_part_code(value: str) -> tuple[str, str]:
    stored = _bounded_text(
        value,
        field="bom_code",
        max_graphemes=160,
        max_utf8_bytes=640,
        blank_allowed=False,
    )
    return stored, normalize_match_key(
        stored,
        raw_max_utf8_bytes=640,
        key_max_utf8_bytes=2048,
    )


def normalize_serial(value: str | None) -> tuple[str | None, str | None]:
    if value is None:
        return None, None
    stored = _bounded_text(
        value,
        field="manufacturer_serial",
        max_graphemes=200,
        max_utf8_bytes=800,
        blank_allowed=True,
    )
    if not stored:
        return None, None
    return stored, normalize_match_key(
        stored,
        raw_max_utf8_bytes=800,
        key_max_utf8_bytes=2048,
    )


def normalize_slot_label(value: str | None) -> str | None:
    if value is None:
        return None
    stored = _bounded_text(
        value,
        field="slot_label",
        max_graphemes=120,
        max_utf8_bytes=480,
        blank_allowed=True,
    )
    return stored or None


def validate_condition(value: str | None) -> str:
    if value is None:
        return "unknown"
    if value not in _CONDITION_TOKENS:
        raise ValidationError("condition_token is invalid")
    return value


def validate_positive_quantity(value: int) -> int:
    if type(value) is not int or not 1 <= value <= 1_000_000:
        raise ValidationError("Inventory quantity must be an integer between 1 and 1000000")
    return value


def validate_reason(value: str) -> str:
    return _bounded_text(
        value,
        field="reason_code",
        max_graphemes=96,
        max_utf8_bytes=384,
        blank_allowed=False,
    )


def validate_effective_at(value: int | None) -> int | None:
    if value is not None and (type(value) is not int or value < 0):
        raise ValidationError("effective_at_utc must be a non-negative integer or null")
    return value


__all__ = [
    "normalize_part_code",
    "normalize_serial",
    "normalize_slot_label",
    "validate_condition",
    "validate_effective_at",
    "validate_positive_quantity",
    "validate_reason",
]
