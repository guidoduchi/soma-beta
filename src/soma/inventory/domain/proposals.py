from __future__ import annotations

import re

from soma.foundation.errors import ValidationError
from soma.foundation.identifiers import require_uuid4
from soma.reference.domain.matching import trim_match_whitespace

_PROPOSAL_KINDS = frozenset(
    {
        "spare_request_submission",
        "official_sr7",
        "rma_authorization",
        "dispatch",
        "receipt",
        "fault_tag_submission",
        "warehouse_received",
        "warehouse_final_decision",
    }
)
_TARGET_KINDS = frozenset(
    {"spare_request", "rma", "spare_part_unit", "fault_tag", "fault_tag_membership"}
)
_RISK_TIERS = frozenset({"normal", "high", "material_final"})
_SHA256 = re.compile(r"[0-9a-f]{64}\Z")


def validate_positive_revision(value: int, field: str = "revision") -> int:
    if type(value) is not int or value <= 0:
        raise ValidationError(f"{field} must be a positive integer")
    return value


def validate_fingerprint(value: str, field: str = "input_fingerprint") -> str:
    if not isinstance(value, str) or _SHA256.fullmatch(value) is None:
        raise ValidationError(f"{field} must be lowercase SHA-256 hex")
    return value


def validate_proposal_kind(value: str) -> str:
    if value not in _PROPOSAL_KINDS:
        raise ValidationError("Inventory proposal kind is invalid")
    return value


def validate_target_kind(value: str) -> str:
    if value not in _TARGET_KINDS:
        raise ValidationError("Inventory proposal target kind is invalid")
    return value


def validate_risk_tier(value: str) -> str:
    if value not in _RISK_TIERS:
        raise ValidationError("Inventory proposal risk tier is invalid")
    return value


def validate_proposal_id(value: str) -> str:
    return require_uuid4(value)


def normalize_reason_category(value: str) -> str:
    if not isinstance(value, str):
        raise ValidationError("reason_category must be text")
    normalized = trim_match_whitespace(value)
    if not normalized:
        raise ValidationError("reason_category is required")
    if "\x00" in normalized or "\r" in normalized or "\n" in normalized:
        raise ValidationError("reason_category contains forbidden control/newline")
    if len(normalized.encode("utf-8", errors="strict")) > 384:
        raise ValidationError("reason_category exceeds UTF-8 byte bound")
    return normalized


def source_evidence_ref(evidence_kind: str, evidence_id: str) -> str:
    if not isinstance(evidence_kind, str) or not evidence_kind:
        raise ValidationError("proposal evidence_kind is invalid")
    if not isinstance(evidence_id, str) or not evidence_id:
        raise ValidationError("proposal evidence_id is invalid")
    value = f"{evidence_kind}:{evidence_id}"
    if (
        len(value.encode("utf-8", errors="strict")) > 768
        or "\x00" in value
        or "\r" in value
        or "\n" in value
    ):
        raise ValidationError("proposal source evidence reference is invalid")
    return value


__all__ = [
    "normalize_reason_category",
    "source_evidence_ref",
    "validate_fingerprint",
    "validate_positive_revision",
    "validate_proposal_id",
    "validate_proposal_kind",
    "validate_risk_tier",
    "validate_target_kind",
]
