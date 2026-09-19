from __future__ import annotations

from dataclasses import dataclass

from soma.foundation.errors import ValidationError
from soma.foundation.identifiers import require_uuid4

_DISPOSITIONS = frozenset(
    {
        "installed_used",
        "unused",
        "inbound_faulty",
        "incompatible",
        "dismantled",
        "removed_only",
        "no_physical_change",
        "other_reviewed",
    }
)


@dataclass(frozen=True, slots=True)
class ReturnSelection:
    unit_kind: str
    unit_id: str


def optional_uuid(value: str | None, field: str) -> str | None:
    if value is None:
        return None
    try:
        return require_uuid4(value)
    except ValidationError as exc:
        raise ValidationError(f"{field} must be UUID text or null") from exc


def validate_disposition(value: str) -> str:
    if value not in _DISPOSITIONS:
        raise ValidationError("physical disposition is invalid")
    return value


def validate_effective_at_utc(value: int | None) -> int | None:
    if value is not None and (type(value) is not int or value < 0):
        raise ValidationError("effective_at_utc must be non-negative or null")
    return value


def validate_consequence_shape(
    *,
    disposition: str,
    installed_spare_part_unit_id: str | None,
    removed_device_part_unit_id: str | None,
    inbound_spare_part_unit_id: str | None,
    parent_dismantled_unit_id: str | None,
) -> ReturnSelection | None:
    installed = optional_uuid(installed_spare_part_unit_id, "installed_spare_part_unit_id")
    removed = optional_uuid(removed_device_part_unit_id, "removed_device_part_unit_id")
    inbound = optional_uuid(inbound_spare_part_unit_id, "inbound_spare_part_unit_id")
    parent = optional_uuid(parent_dismantled_unit_id, "parent_dismantled_unit_id")
    if disposition == "installed_used":
        if installed is None or removed is None or inbound is not None or parent is not None:
            raise ValidationError(
                "installed_used requires installed spare + removed Device Part only"
            )
        return ReturnSelection("device_part_unit", removed)
    if disposition in {"unused", "inbound_faulty", "incompatible"}:
        if inbound is None or any(x is not None for x in (installed, removed, parent)):
            raise ValidationError(
                f"{disposition} requires exactly the inbound Spare Part Unit"
            )
        return ReturnSelection("spare_part_unit", inbound)
    if disposition == "dismantled":
        if parent is None or any(x is not None for x in (installed, removed, inbound)):
            raise ValidationError("dismantled requires exactly the parent dismantled unit")
        return ReturnSelection("spare_part_unit", parent)
    if disposition == "removed_only":
        if removed is None or any(x is not None for x in (installed, inbound, parent)):
            raise ValidationError("removed_only requires exactly the removed Device Part")
        return ReturnSelection("device_part_unit", removed)
    if disposition == "no_physical_change":
        if any(x is not None for x in (installed, removed, inbound, parent)):
            raise ValidationError("no_physical_change cannot carry physical unit identities")
        return None
    if disposition == "other_reviewed":
        candidates = [
            ReturnSelection("device_part_unit", removed) if removed is not None else None,
            ReturnSelection("spare_part_unit", inbound) if inbound is not None else None,
            ReturnSelection("spare_part_unit", parent) if parent is not None else None,
        ]
        selected = [item for item in candidates if item is not None]
        if installed is not None or len(selected) != 1:
            raise ValidationError(
                "other_reviewed requires exactly one explicit reviewed return unit"
            )
        return selected[0]
    raise ValidationError("physical disposition is invalid")


__all__ = [
    "ReturnSelection",
    "optional_uuid",
    "validate_consequence_shape",
    "validate_disposition",
    "validate_effective_at_utc",
]
