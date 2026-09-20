from __future__ import annotations

from dataclasses import dataclass

import regex

from soma.foundation.errors import ValidationError
from soma.foundation.identifiers import require_uuid4
from soma.reference.domain.matching import trim_match_whitespace

_LOGISTICS_EVENTS = frozenset(
    {
        "dispatch",
        "pickup",
        "delivery",
        "receipt",
        "custody_change",
        "location_change",
        "return_pickup",
        "warehouse_delivery",
        "correction",
    }
)
_MAX_PARTICIPANTS = 5000


@dataclass(frozen=True, slots=True)
class LogisticsParticipants:
    rma_ids: tuple[str, ...] = ()
    spare_part_unit_ids: tuple[str, ...] = ()
    device_part_unit_ids: tuple[str, ...] = ()

    def validate(self) -> "LogisticsParticipants":
        groups = (
            self.rma_ids,
            self.spare_part_unit_ids,
            self.device_part_unit_ids,
        )
        total = sum(len(group) for group in groups)
        if total <= 0:
            raise ValidationError("Actual logistics event requires at least one participant")
        if total > _MAX_PARTICIPANTS:
            raise ValidationError("Actual logistics participant hard limit exceeded")
        for field, group in zip(
            ("rma_ids", "spare_part_unit_ids", "device_part_unit_ids"),
            groups,
            strict=True,
        ):
            if not isinstance(group, tuple):
                raise ValidationError(f"{field} must be a tuple")
            if len(set(group)) != len(group):
                raise ValidationError(f"{field} contains duplicate identities")
            for identity in group:
                require_uuid4(identity)
        return self


def validate_logistics_event_kind(value: str) -> str:
    if value not in _LOGISTICS_EVENTS:
        raise ValidationError("actual logistics event kind is invalid")
    return value


def validate_logistics_time(value: int | None) -> int | None:
    if value is None:
        return None
    if type(value) is not int or value < 0:
        raise ValidationError("effective_at_utc must be a nonnegative integer or null")
    return value


def normalize_optional_logistics_text(
    value: str | None,
    *,
    field: str,
    max_graphemes: int = 240,
    max_utf8_bytes: int = 960,
) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise ValidationError(f"{field} must be text or null")
    stored = trim_match_whitespace(value)
    if not stored:
        return None
    if "\x00" in stored or "\r" in stored or "\n" in stored:
        raise ValidationError(f"{field} contains forbidden control/newline")
    if len(stored.encode("utf-8", errors="strict")) > max_utf8_bytes:
        raise ValidationError(f"{field} exceeds its UTF-8 byte bound")
    if len(regex.findall(r"\X", stored)) > max_graphemes:
        raise ValidationError(f"{field} exceeds its grapheme bound")
    return stored


__all__ = [
    "LogisticsParticipants",
    "normalize_optional_logistics_text",
    "validate_logistics_event_kind",
    "validate_logistics_time",
]
