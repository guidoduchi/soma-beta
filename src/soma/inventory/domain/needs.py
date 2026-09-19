from __future__ import annotations

import regex

from soma.foundation.errors import ValidationError
from soma.reference.domain.matching import normalize_match_key, trim_match_whitespace

_CONDITIONS = frozenset({"unknown", "normal", "faulty", "removed", "installed", "quarantined"})


def _bounded_text(
    value: str,
    *,
    field: str,
    max_graphemes: int,
    max_utf8_bytes: int,
    blank_to_none: bool,
) -> str | None:
    if not isinstance(value, str):
        raise ValidationError(f"{field} must be text")
    stored = trim_match_whitespace(value)
    if not stored:
        if blank_to_none:
            return None
        raise ValidationError(f"{field} cannot be blank")
    encoded = stored.encode("utf-8", errors="strict")
    if len(encoded) > max_utf8_bytes:
        raise ValidationError(f"{field} exceeds its UTF-8 byte bound")
    if len(regex.findall(r"\X", stored)) > max_graphemes:
        raise ValidationError(f"{field} exceeds its grapheme bound")
    if "\x00" in stored or "\r" in stored or "\n" in stored:
        raise ValidationError(f"{field} contains a forbidden control/newline")
    return stored


def normalize_part_code(value: str) -> tuple[str, str]:
    stored = _bounded_text(
        value,
        field="bom_code",
        max_graphemes=160,
        max_utf8_bytes=640,
        blank_to_none=False,
    )
    assert stored is not None
    return stored, normalize_match_key(
        stored,
        raw_max_utf8_bytes=640,
        key_max_utf8_bytes=640,
    )


def normalize_optional_serial(value: str | None) -> tuple[str | None, str | None]:
    if value is None:
        return None, None
    stored = _bounded_text(
        value,
        field="manufacturer_serial",
        max_graphemes=200,
        max_utf8_bytes=800,
        blank_to_none=True,
    )
    if stored is None:
        return None, None
    return stored, normalize_match_key(
        stored,
        raw_max_utf8_bytes=800,
        key_max_utf8_bytes=800,
    )


def normalize_optional_slot(value: str | None) -> str | None:
    if value is None:
        return None
    return _bounded_text(
        value,
        field="slot_label",
        max_graphemes=120,
        max_utf8_bytes=480,
        blank_to_none=True,
    )


def validate_condition_token(value: str | None) -> str:
    if value is None:
        return "unknown"
    if value not in _CONDITIONS:
        raise ValidationError("condition_token is invalid")
    return value


def validate_effective_at_utc(value: int | None) -> int | None:
    if value is None:
        return None
    if type(value) is not int or value < 0:
        raise ValidationError("effective_at_utc must be a nonnegative integer or null")
    return value


def validate_planned_quantity(value: int) -> int:
    if type(value) is not int or not 1 <= value <= 1_000_000:
        raise ValidationError("planned_quantity must be a positive whole quantity <= 1000000")
    return value


def validate_reason_code(value: str) -> str:
    if not isinstance(value, str):
        raise ValidationError("reason_code must be text")
    stored = trim_match_whitespace(value)
    if not stored:
        raise ValidationError("reason_code cannot be blank")
    if len(stored.encode("utf-8", errors="strict")) > 384:
        raise ValidationError("reason_code exceeds its UTF-8 byte bound")
    if len(regex.findall(r"\X", stored)) > 96:
        raise ValidationError("reason_code exceeds its grapheme bound")
    if "\x00" in stored or "\r" in stored or "\n" in stored:
        raise ValidationError("reason_code contains a forbidden control/newline")
    return stored
