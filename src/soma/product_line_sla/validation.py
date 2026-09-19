from __future__ import annotations

import regex

from soma.foundation.errors import ValidationError

_BOUNDS = {
    "product_line_name": (160, 640),
    "contract_name": (200, 800),
    "contract_reference": (120, 480),
    "policy_name": (160, 640),
    "reason_code": (96, 384),
}


def validate_bounded_text(value: str, *, field: str) -> str:
    if field not in _BOUNDS:
        raise ValidationError("unknown Product Line SLA text field")
    if not isinstance(value, str):
        raise ValidationError(f"{field} must be text")
    try:
        encoded = value.encode("utf-8", errors="strict")
    except UnicodeEncodeError as exc:
        raise ValidationError(f"{field} must be valid Unicode") from exc
    if not encoded or value != value.strip() or "\x00" in value:
        raise ValidationError(f"{field} must be nonblank bounded text")
    max_graphemes, max_bytes = _BOUNDS[field]
    if len(encoded) > max_bytes:
        raise ValidationError(f"{field} exceeds its UTF-8 byte bound")
    count = 0
    for _ in regex.finditer(r"\X", value, flags=regex.VERSION1):
        count += 1
        if count > max_graphemes:
            raise ValidationError(f"{field} exceeds its grapheme bound")
    if count == 0:
        raise ValidationError(f"{field} cannot be blank")
    return value


def validate_reason_code(value: str) -> str:
    result = validate_bounded_text(value, field="reason_code")
    if "\r" in result or "\n" in result:
        raise ValidationError("reason_code must be one line")
    return result


__all__ = ["validate_bounded_text", "validate_reason_code"]
