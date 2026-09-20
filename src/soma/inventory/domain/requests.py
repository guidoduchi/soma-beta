from __future__ import annotations

from dataclasses import dataclass

from soma.foundation.errors import ValidationError
from soma.foundation.identifiers import require_uuid4
from soma.reference.domain.matching import trim_match_whitespace

_REQUEST_ORIGINS = frozenset({"soma_draft", "external_registration"})
_LOGISTICS_MODES = frozenset({"delivery", "self_pickup"})
_MAX_ALLOCATIONS = 2000
_MAX_QUANTITY = 1_000_000
_MAX_EVIDENCE_TEXT_BYTES = 512


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
    "validate_positive_revision",
    "validate_request_origin",
    "validate_submission_evidence",
    "validate_submission_time",
]

def validate_positive_revision(value: int, *, field: str) -> int:
    if type(value) is not int or value <= 0:
        raise ValidationError(f"{field} must be a positive integer")
    return value


def validate_submission_time(value: int | None) -> int | None:
    if value is None:
        return None
    if type(value) is not int or value < 0:
        raise ValidationError("effective_submission_at_utc must be a nonnegative integer or null")
    return value


def validate_submission_evidence(
    evidence_kind: str | None,
    evidence_id: str | None,
) -> tuple[str | None, str | None]:
    if evidence_kind is None and evidence_id is None:
        return None, None
    if evidence_kind is None or evidence_id is None:
        raise ValidationError("submission evidence_kind and evidence_id must both be present or both absent")
    if not isinstance(evidence_kind, str) or not isinstance(evidence_id, str):
        raise ValidationError("submission evidence values must be text")
    kind = trim_match_whitespace(evidence_kind)
    identity = trim_match_whitespace(evidence_id)
    if not kind or not identity:
        raise ValidationError("submission evidence values cannot be blank")
    if (
        len(kind.encode("utf-8", errors="strict")) > _MAX_EVIDENCE_TEXT_BYTES
        or len(identity.encode("utf-8", errors="strict")) > _MAX_EVIDENCE_TEXT_BYTES
    ):
        raise ValidationError("submission evidence value exceeds its UTF-8 byte bound")
    if any(token in kind or token in identity for token in ("\x00", "\r", "\n")):
        raise ValidationError("submission evidence value contains a forbidden control/newline")
    return kind, identity

