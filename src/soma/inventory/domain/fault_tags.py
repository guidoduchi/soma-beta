from __future__ import annotations

from dataclasses import dataclass

from soma.foundation.errors import ValidationError
from soma.foundation.identifiers import require_uuid4
from soma.reference.domain.matching import trim_match_whitespace

_RETURN_METHODS = frozenset({"pickup", "non_pickup"})
_MAX_MEMBERS = 2000


def validate_return_method(value: str) -> str:
    if value not in _RETURN_METHODS:
        raise ValidationError("Fault Tag return method is invalid")
    return value


def normalize_optional_uuid(value: str | None, field: str) -> str | None:
    if value is None:
        return None
    try:
        return require_uuid4(value)
    except ValidationError as exc:
        raise ValidationError(f"{field} must be UUID text or null") from exc


def normalize_optional_instructions(value: str | None) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise ValidationError("pickup_instructions must be text or null")
    stored = trim_match_whitespace(value)
    if not stored:
        return None
    if "\x00" in stored or "\r" in stored or "\n" in stored:
        raise ValidationError("pickup_instructions contains forbidden control/newline")
    if len(stored.encode("utf-8", errors="strict")) > 1024:
        raise ValidationError("pickup_instructions exceeds UTF-8 byte bound")
    return stored


def normalize_return_reason(value: str) -> str:
    if not isinstance(value, str):
        raise ValidationError("return_reason must be text")
    stored = trim_match_whitespace(value)
    if not stored:
        raise ValidationError("return_reason is required")
    if "\x00" in stored or "\r" in stored or "\n" in stored:
        raise ValidationError("return_reason contains forbidden control/newline")
    if len(stored.encode("utf-8", errors="strict")) > 384:
        raise ValidationError("return_reason exceeds UTF-8 byte bound")
    return stored


@dataclass(frozen=True, slots=True)
class FaultTagMembershipIntent:
    rma_id: str
    return_reason: str

    def normalized(self) -> tuple[str, str]:
        return require_uuid4(self.rma_id), normalize_return_reason(self.return_reason)


def validate_memberships(
    value: tuple[FaultTagMembershipIntent, ...],
) -> tuple[tuple[str, str], ...]:
    if not isinstance(value, tuple):
        raise ValidationError("Fault Tag memberships must be a tuple")
    if len(value) > _MAX_MEMBERS:
        raise ValidationError("Fault Tag membership hard limit exceeded")
    normalized = tuple(item.normalized() for item in value)
    rmas = [item[0] for item in normalized]
    if len(set(rmas)) != len(rmas):
        raise ValidationError("Fault Tag memberships contain duplicate RMA obligations")
    return tuple(sorted(normalized, key=lambda item: item[0]))


__all__ = [
    "FaultTagMembershipIntent",
    "normalize_optional_instructions",
    "normalize_optional_uuid",
    "normalize_return_reason",
    "validate_memberships",
    "validate_return_method",
]
