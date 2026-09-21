from __future__ import annotations

from email.errors import HeaderParseError
from email.headerregistry import Address

from soma.foundation.errors import ValidationError

from .matching import normalize_match_key, trim_match_whitespace


def validate_single_line_text(value: str, *, field: str, max_utf8_bytes: int) -> str:
    if not isinstance(value, str):
        raise ValidationError(f"{field} must be a string")
    encoded = value.encode("utf-8", errors="strict")
    if not encoded:
        raise ValidationError(f"{field} cannot be empty")
    if len(encoded) > max_utf8_bytes:
        raise ValidationError(f"{field} exceeds its UTF-8 byte bound")
    if "\x00" in value or "\r" in value or "\n" in value:
        raise ValidationError(f"{field} contains a forbidden control/newline")
    return value


def validate_display_name(value: str) -> str:
    # The accepted profile contract owns display_name; bounds.json retains a stale
    # username label, so this uses its intended one-line 512-byte bound without
    # creating any username/login field.
    return validate_single_line_text(value, field="display_name", max_utf8_bytes=512)


def validate_customer_name(value: str) -> tuple[str, str]:
    stored = validate_single_line_text(value, field="customer_organization.name", max_utf8_bytes=1024)
    return stored, normalize_match_key(stored, raw_max_utf8_bytes=1024)


def validate_account_code(value: str) -> tuple[str, str]:
    stored = validate_single_line_text(value, field="customer_account_code", max_utf8_bytes=512)
    return stored, normalize_match_key(stored, raw_max_utf8_bytes=512)


def validate_contact_name(value: str) -> tuple[str, str]:
    stored = validate_single_line_text(value, field="contact.name", max_utf8_bytes=1024)
    return stored, normalize_match_key(stored, raw_max_utf8_bytes=1024)


def _contains_c0_c1_control(value: str) -> bool:
    for character in value:
        codepoint = ord(character)
        if codepoint <= 0x1F or 0x7F <= codepoint <= 0x9F:
            return True
    return False


def validate_email_channel(value: str) -> tuple[str, str]:
    if not isinstance(value, str):
        raise ValidationError("email channel must be a string")
    if len(value.encode("utf-8", errors="strict")) > 2048:
        raise ValidationError("email channel exceeds its UTF-8 byte bound")
    stored = trim_match_whitespace(value)
    if not stored:
        raise ValidationError("email channel cannot be empty")
    if "\x00" in stored or "\r" in stored or "\n" in stored or _contains_c0_c1_control(stored):
        raise ValidationError("email channel contains a forbidden control character")
    try:
        parsed = Address(addr_spec=stored)
    except (ValueError, HeaderParseError) as exc:
        raise ValidationError("email channel is not one complete addr-spec") from exc
    # Address accepts one addr-spec by construction. Preserve the operator's trimmed
    # spelling for storage; parsed output is syntax proof only.
    if not parsed.addr_spec:
        raise ValidationError("email channel is invalid")
    return stored, normalize_match_key(stored, raw_max_utf8_bytes=2048)


def validate_dispatch_name(value: str) -> tuple[str, str]:
    stored = validate_single_line_text(value, field="dispatch_location.name", max_utf8_bytes=1024)
    return stored, normalize_match_key(stored, raw_max_utf8_bytes=1024)


def validate_standalone_address(value: str) -> str:
    if not isinstance(value, str):
        raise ValidationError("dispatch address must be a string")
    normalized = value.replace("\r\n", "\n").replace("\r", "\n")
    if "\x00" in normalized:
        raise ValidationError("dispatch address contains NUL")
    encoded = normalized.encode("utf-8", errors="strict")
    if not encoded or len(encoded) > 8192:
        raise ValidationError("dispatch address is empty or exceeds its UTF-8 byte bound")
    if normalized.count("\n") + 1 > 32:
        raise ValidationError("dispatch address exceeds 32 lines")
    return normalized


def validate_reason_category(value: str | None) -> str | None:
    if value is None:
        return None
    return validate_single_line_text(value, field="reason_category", max_utf8_bytes=128)
