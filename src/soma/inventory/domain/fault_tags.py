from __future__ import annotations

from dataclasses import dataclass

from soma.foundation.errors import ValidationError
from soma.foundation.identifiers import require_uuid4

from .logistics import normalize_optional_logistics_text
from .needs import validate_effective_at_utc, validate_reason_code

_MAX_MEMBERS = 5000


@dataclass(frozen=True, slots=True)
class FaultTagMembershipIntent:
    rma_id: str
    return_reason: str

    def validate(self) -> "FaultTagMembershipIntent":
        return FaultTagMembershipIntent(
            rma_id=require_uuid4(self.rma_id),
            return_reason=validate_reason_code(self.return_reason),
        )


def validate_fault_tag_memberships(
    values: tuple[FaultTagMembershipIntent, ...],
) -> tuple[FaultTagMembershipIntent, ...]:
    if not isinstance(values, tuple) or len(values) > _MAX_MEMBERS:
        raise ValidationError("Fault Tag memberships must be a tuple of at most 5000 selections")
    accepted = tuple(value.validate() for value in values)
    ids = [value.rma_id for value in accepted]
    if len(set(ids)) != len(ids):
        raise ValidationError("Fault Tag membership selections contain duplicate RMA identities")
    return tuple(sorted(accepted, key=lambda value: value.rma_id.encode("utf-8")))


@dataclass(frozen=True, slots=True)
class WarehouseMembershipTarget:
    fault_tag_membership_id: str
    revision: int

    def validate(self) -> "WarehouseMembershipTarget":
        identity = require_uuid4(self.fault_tag_membership_id)
        if type(self.revision) is not int or self.revision <= 0:
            raise ValidationError("warehouse membership revision must be positive")
        return WarehouseMembershipTarget(identity, self.revision)


def validate_warehouse_targets(
    values: tuple[WarehouseMembershipTarget, ...],
) -> tuple[WarehouseMembershipTarget, ...]:
    if not isinstance(values, tuple) or not values or len(values) > 2000:
        raise ValidationError("warehouse targets must contain 1..2000 memberships")
    accepted = tuple(value.validate() for value in values)
    ids = [value.fault_tag_membership_id for value in accepted]
    if len(set(ids)) != len(ids):
        raise ValidationError("warehouse targets contain duplicate memberships")
    return tuple(
        sorted(accepted, key=lambda value: value.fault_tag_membership_id.encode("utf-8"))
    )


def validate_return_method(value: str) -> str:
    if value not in {"pickup", "non_pickup"}:
        raise ValidationError("Fault Tag return method must be pickup or non_pickup")
    return value


def validate_pickup_context(
    *,
    return_method: str,
    dispatch_location_id: str | None,
    contact_id: str | None,
    instructions: str | None,
) -> tuple[str, str | None, str | None, str | None]:
    method = validate_return_method(return_method)
    location = None if dispatch_location_id is None else require_uuid4(dispatch_location_id)
    contact = None if contact_id is None else require_uuid4(contact_id)
    text = normalize_optional_logistics_text(
        instructions,
        field="pickup_instructions",
        max_graphemes=500,
        max_utf8_bytes=2000,
    )
    if method == "non_pickup":
        if location is not None or contact is not None:
            raise ValidationError("non_pickup Fault Tag cannot carry pickup origin/contact")
        return method, None, None, text
    return method, location, contact, text


def validate_fault_tag_effective_at(value: int | None) -> int | None:
    return validate_effective_at_utc(value)


__all__ = [
    "FaultTagMembershipIntent",
    "WarehouseMembershipTarget",
    "validate_fault_tag_effective_at",
    "validate_fault_tag_memberships",
    "validate_pickup_context",
    "validate_return_method",
    "validate_warehouse_targets",
]
