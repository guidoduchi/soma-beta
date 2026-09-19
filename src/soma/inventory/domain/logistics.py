from __future__ import annotations

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


__all__ = ["normalize_optional_uuid", "validate_receipt_identity"]
