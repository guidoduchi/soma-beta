from __future__ import annotations

from dataclasses import dataclass

from soma.foundation.errors import ValidationError
from soma.foundation.identifiers import require_uuid4

_REQUEST_ORIGINS = frozenset({"soma_draft", "external_registration"})
_LOGISTICS_MODES = frozenset({"delivery", "self_pickup"})
_MAX_ALLOCATIONS = 2000
_MAX_QUANTITY = 1_000_000


@dataclass(frozen=True, slots=True)
class SpareRequestAllocationIntent:
    spare_need_id: str
    quantity: int

    def validate(self) -> "SpareRequestAllocationIntent":
        require_uuid4(self.spare_need_id)
        if type(self.quantity) is not int or not 1 <= self.quantity <= _MAX_QUANTITY:
            raise ValidationError(
                "Spare Request allocation quantity must be a positive whole number <=1000000"
            )
        return self


def validate_request_origin(value: str) -> str:
    if value not in _REQUEST_ORIGINS:
        raise ValidationError("Spare Request creation origin is invalid")
    return value


def validate_logistics_mode(value: str) -> str:
    if value not in _LOGISTICS_MODES:
        raise ValidationError("Spare Request logistics mode is invalid")
    return value


def validate_allocation_intents(
    value: tuple[SpareRequestAllocationIntent, ...],
) -> tuple[SpareRequestAllocationIntent, ...]:
    if not isinstance(value, tuple) or not value:
        raise ValidationError("Spare Request requires one-or-more Need allocations")
    if len(value) > _MAX_ALLOCATIONS:
        raise ValidationError("Spare Request allocation hard limit exceeded")
    validated = tuple(item.validate() for item in value)
    ids = [item.spare_need_id for item in validated]
    if len(set(ids)) != len(ids):
        raise ValidationError("Spare Request cannot repeat a Need in one draft")
    return validated


__all__ = [
    "SpareRequestAllocationIntent",
    "validate_allocation_intents",
    "validate_logistics_mode",
    "validate_request_origin",
]
