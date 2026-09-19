from __future__ import annotations

from dataclasses import dataclass
import re

from soma.foundation.errors import ValidationError
from soma.foundation.identifiers import require_uuid4

_REQUEST_ORIGINS = frozenset({"soma_draft", "external_registration"})
_LOGISTICS_MODES = frozenset({"delivery", "self_pickup"})
_MAX_ALLOCATIONS = 2000
_MAX_QUANTITY = 1_000_000
_SR7 = re.compile(r"SR[0-9]{7}\Z")


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


def normalize_sr7(value: str) -> str:
    if not isinstance(value, str):
        raise ValidationError("SR7 must be text")
    normalized = value.strip()
    if _SR7.fullmatch(normalized) is None:
        raise ValidationError("SR7 must be exactly SR followed by seven ASCII digits")
    return normalized


def validate_positive_revision(value: int, field: str = "revision") -> int:
    if type(value) is not int or value <= 0:
        raise ValidationError(f"{field} must be a positive integer")
    return value


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
    "normalize_sr7",
    "validate_positive_revision",
    "validate_allocation_intents",
    "validate_logistics_mode",
    "validate_request_origin",
]
