from __future__ import annotations

from dataclasses import dataclass
import re

from soma.foundation.errors import ValidationError

from .needs import normalize_part_code

_C10 = re.compile(r"C[0-9]{10}\\Z")
_MAX_BATCH = 2000


def normalize_c10(value: str) -> str:
    if not isinstance(value, str):
        raise ValidationError("C10 must be text")
    normalized = value.strip()
    if _C10.fullmatch(normalized) is None:
        raise ValidationError("C10 must be exactly C followed by ten ASCII digits")
    return normalized


@dataclass(frozen=True, slots=True)
class RmaAuthorizationIntent:
    c10: str
    promised_bom_code: str

    def normalized(self) -> tuple[str, str, str]:
        c10 = normalize_c10(self.c10)
        stored_bom, bom_key = normalize_part_code(self.promised_bom_code)
        return c10, stored_bom, bom_key


def validate_authorization_intents(
    value: tuple[RmaAuthorizationIntent, ...],
) -> tuple[tuple[str, str, str], ...]:
    if not isinstance(value, tuple) or not value:
        raise ValidationError("RMA authorization requires one-or-more ordered rows")
    if len(value) > _MAX_BATCH:
        raise ValidationError("RMA authorization batch hard limit exceeded")
    normalized = tuple(item.normalized() for item in value)
    c10s = [item[0] for item in normalized]
    if len(set(c10s)) != len(c10s):
        raise ValidationError("RMA authorization batch contains duplicate C10 values")
    return normalized


__all__ = [
    "RmaAuthorizationIntent",
    "normalize_c10",
    "validate_authorization_intents",
]
