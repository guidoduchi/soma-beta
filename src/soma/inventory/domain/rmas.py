from __future__ import annotations

from dataclasses import dataclass
import re

from soma.foundation.errors import ValidationError
from soma.reference.domain.matching import trim_match_whitespace

from .needs import normalize_part_code

_C10 = re.compile(r"C[0-9]{10}\Z")
_MAX_BATCH = 10_000


@dataclass(frozen=True, slots=True)
class RmaAuthorizationIntent:
    c10: str
    promised_bom_code: str

    def validate(self) -> tuple[str, str, str]:
        return (
            validate_c10(self.c10),
            *normalize_part_code(self.promised_bom_code),
        )


def validate_c10(value: str) -> str:
    if not isinstance(value, str):
        raise ValidationError("C10 must be text")
    canonical = value.strip()
    if _C10.fullmatch(canonical) is None:
        raise ValidationError("C10 must be C followed by exactly ten ASCII digits")
    return canonical


def validate_rma_authorization_batch(
    value: tuple[RmaAuthorizationIntent, ...],
) -> tuple[tuple[str, str, str], ...]:
    if not isinstance(value, tuple) or not value:
        raise ValidationError("RMA authorization batch requires one-or-more rows")
    if len(value) > _MAX_BATCH:
        raise ValidationError("RMA authorization batch exceeds the 10000-row hard limit")
    normalized = tuple(item.validate() for item in value)
    c10s = [item[0] for item in normalized]
    if len(set(c10s)) != len(c10s):
        raise ValidationError("RMA authorization batch contains duplicate C10 values")
    return normalized


def validate_authorization_time(value: int | None) -> int | None:
    if value is None:
        return None
    if type(value) is not int or value < 0:
        raise ValidationError("accepted_at_utc must be a nonnegative integer or null")
    return value


def validate_optional_evidence(
    evidence_kind: str | None,
    evidence_id: str | None,
) -> tuple[str | None, str | None]:
    if evidence_kind is None and evidence_id is None:
        return None, None
    if evidence_kind is None or evidence_id is None:
        raise ValidationError("RMA evidence kind/id must both be present or both absent")
    if not isinstance(evidence_kind, str) or not isinstance(evidence_id, str):
        raise ValidationError("RMA evidence kind/id must be text")
    kind = trim_match_whitespace(evidence_kind)
    identity = trim_match_whitespace(evidence_id)
    if not kind or not identity:
        raise ValidationError("RMA evidence kind/id cannot be blank")
    if len(kind.encode("utf-8")) > 512 or len(identity.encode("utf-8")) > 512:
        raise ValidationError("RMA evidence kind/id exceeds its UTF-8 bound")
    if any(token in kind or token in identity for token in ("\x00", "\r", "\n")):
        raise ValidationError("RMA evidence kind/id contains forbidden control/newline")
    return kind, identity


__all__ = [
    "RmaAuthorizationIntent",
    "validate_authorization_time",
    "validate_c10",
    "validate_optional_evidence",
    "validate_rma_authorization_batch",
]
