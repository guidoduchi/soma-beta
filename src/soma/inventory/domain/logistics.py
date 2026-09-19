from __future__ import annotations

from dataclasses import dataclass

from soma.foundation.errors import ValidationError
from soma.foundation.identifiers import require_uuid4

from .units import (
    normalize_custody_text,
    normalize_location_kind,
    normalize_location_ref,
    normalize_spare_part_identity,
    validate_spare_condition,
    validate_unit_effective_at_utc,
)


_LOGISTICS_EVENT_KINDS = frozenset({
    "dispatch",
    "pickup",
    "delivery",
    "receipt",
    "custody_change",
    "location_change",
    "return_pickup",
    "warehouse_delivery",
})
_PARTICIPANT_KINDS = frozenset({"rma", "spare_part_unit", "device_part_unit"})


@dataclass(frozen=True, slots=True)
class LogisticsParticipantIntent:
    participant_kind: str
    participant_id: str

    def validate(self) -> "LogisticsParticipantIntent":
        if self.participant_kind not in _PARTICIPANT_KINDS:
            raise ValidationError("logistics participant kind is invalid")
        require_uuid4(self.participant_id)
        return self


def validate_logistics_event_kind(value: str) -> str:
    if value not in _LOGISTICS_EVENT_KINDS:
        raise ValidationError("actual logistics event kind is invalid")
    return value


def validate_logistics_participants(
    value: tuple[LogisticsParticipantIntent, ...],
) -> tuple[LogisticsParticipantIntent, ...]:
    if not isinstance(value, tuple) or not value:
        raise ValidationError("actual logistics event requires one-or-more participants")
    if len(value) > 2000:
        raise ValidationError("actual logistics participant hard limit exceeded")
    validated = tuple(item.validate() for item in value)
    identities = [(item.participant_kind, item.participant_id) for item in validated]
    if len(set(identities)) != len(identities):
        raise ValidationError("actual logistics participants contain duplicates")
    return validated


def normalize_optional_uuid(value: str | None, field: str) -> str | None:
    if value is None:
        return None
    try:
        return require_uuid4(value)
    except ValidationError as exc:
        raise ValidationError(f"{field} must be UUID text or null") from exc


def validate_receipt_identity(
    *,
    bom_code: str,
    manufacturer_serial: str | None,
    condition_token: str | None,
    effective_at_utc: int | None,
    location_kind: str | None,
    location_ref_id: str | None,
    custody_text: str | None,
) -> tuple[str, str, str | None, str | None, str, int | None, str | None, str | None, str | None]:
    stored_bom, bom_key, stored_serial, serial_key = normalize_spare_part_identity(
        bom_code, manufacturer_serial
    )
    condition = validate_spare_condition(condition_token)
    effective = validate_unit_effective_at_utc(effective_at_utc)
    return (
        stored_bom,
        bom_key,
        stored_serial,
        serial_key,
        condition,
        effective,
        normalize_location_kind(location_kind),
        normalize_location_ref(location_ref_id),
        normalize_custody_text(custody_text),
    )


__all__ = [
    "LogisticsParticipantIntent",
    "normalize_optional_uuid",
    "validate_logistics_event_kind",
    "validate_logistics_participants",
    "validate_receipt_identity",
]
