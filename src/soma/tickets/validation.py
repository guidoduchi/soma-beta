from __future__ import annotations

import re

from soma.foundation.errors import SomaError, ValidationError

_OFFICIAL_SR_RE = re.compile(r"[0-9]{8}\Z")
_RFC_RE = re.compile(r"NC[0-9]{14}\Z")
_HEX64_RE = re.compile(r"[0-9a-f]{64}\Z")


def validate_official_sr_no(value: str) -> str:
    if not isinstance(value, str) or _OFFICIAL_SR_RE.fullmatch(value) is None:
        raise ValidationError("official_sr_no must be exactly eight ASCII decimal digits")
    return value


def validate_rfc_no(value: str) -> str:
    if not isinstance(value, str) or _RFC_RE.fullmatch(value) is None:
        raise SomaError("RFC_ID_INVALID", "RFC identity must be exactly NC followed by fourteen ASCII digits")
    return value


def validate_device_reference_name(value: str) -> str:
    if not isinstance(value, str):
        raise SomaError("DEVICE_REFERENCE_INVALID", "Device Reference operational_name must be a string")
    encoded = value.encode("utf-8", errors="strict")
    if not encoded or len(encoded) > 1024 or "\x00" in value or "\r" in value or "\n" in value:
        raise SomaError(
            "DEVICE_REFERENCE_INVALID",
            "Device Reference operational_name violates the one-line 1..1024 UTF-8 byte contract",
        )
    return value


def validate_working_note_body(value: str) -> str:
    if not isinstance(value, str):
        raise ValidationError("Working Note body must be a string")
    encoded = value.encode("utf-8", errors="strict")
    line_count = value.count("\n") + 1
    if not encoded or len(encoded) > 65_536 or line_count > 512 or "\x00" in value:
        raise ValidationError(
            "Working Note body violates the 1..65536 UTF-8 byte, 512-line, no-NUL contract"
        )
    return value


def validate_reason_category(value: str) -> str:
    if not isinstance(value, str):
        raise ValidationError("reason_category must be a string")
    encoded = value.encode("utf-8", errors="strict")
    if not encoded or len(encoded) > 128 or "\x00" in value or "\r" in value or "\n" in value:
        raise ValidationError("reason_category violates its bounded one-line contract")
    return value


def validate_review_context_id(value: str) -> str:
    if not isinstance(value, str):
        raise ValidationError("review context identity must be a string")
    encoded = value.encode("utf-8", errors="strict")
    if not encoded or len(encoded) > 1024 or "\x00" in value or "\r" in value or "\n" in value:
        raise ValidationError("review context identity violates its bounded one-line contract")
    return value


def validate_optional_sha256(value: str | None, *, field: str) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str) or _HEX64_RE.fullmatch(value) is None:
        raise ValidationError(f"{field} must be lowercase SHA-256 hex")
    return value
