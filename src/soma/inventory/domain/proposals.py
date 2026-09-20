from __future__ import annotations

import re
from dataclasses import dataclass

from soma.foundation.errors import ValidationError
from soma.foundation.identifiers import require_uuid4
from soma.foundation.strict_json import loads_canonical_json
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


@dataclass(frozen=True, slots=True)
class ParsedInventoryProposalTarget:
    proposal_target_id: str
    membership_id: str
    expected_revision: int
    action: str
    effective_at_utc: int | None
    decision: str | None
    reason_code: str | None


def _effective_at(value: object) -> int | None:
    if value is None:
        return None
    if type(value) is not int or value < 0:
        raise ValidationError("proposal effective_at_utc must be non-negative integer or null")
    return value


def parse_inventory_proposal_target(
    *,
    proposal_target_id: str,
    proposal_kind: str,
    risk_tier: str,
    target_kind: str,
    membership_id: str | None,
    expected_revision: int,
    proposed_action: str,
    payload_json: str,
) -> ParsedInventoryProposalTarget:
    target_row_id = require_uuid4(proposal_target_id)
    revision = validate_positive_revision(expected_revision, "expected_revision")
    if target_kind != "fault_tag_membership" or membership_id is None:
        raise ValidationError("proposal target is not mapped to a supported Inventory owner")
    membership = require_uuid4(membership_id)
    payload = loads_canonical_json(
        payload_json,
        max_bytes=4096,
        max_depth=2,
        max_collection_items=8,
    )
    if not isinstance(payload, dict) or payload.get("schema") != "INVENTORY_PROPOSAL_TARGET_V1":
        raise ValidationError("proposal target payload schema is invalid")

    if proposal_kind == "warehouse_received":
        if proposed_action != "warehouse_received" or risk_tier not in {"normal", "high"}:
            raise ValidationError("warehouse receipt proposal mapping is invalid")
        if set(payload) != {"schema", "effective_at_utc"}:
            raise ValidationError("warehouse receipt proposal payload has unknown or missing fields")
        return ParsedInventoryProposalTarget(
            proposal_target_id=target_row_id,
            membership_id=membership,
            expected_revision=revision,
            action="warehouse_received",
            effective_at_utc=_effective_at(payload["effective_at_utc"]),
            decision=None,
            reason_code=None,
        )

    if proposal_kind == "warehouse_final_decision":
        if proposed_action != "warehouse_final_decision" or risk_tier != "material_final":
            raise ValidationError("warehouse final-decision proposal mapping is invalid")
        if set(payload) != {"schema", "decision", "reason_code", "effective_at_utc"}:
            raise ValidationError("warehouse final-decision payload has unknown or missing fields")
        decision = payload["decision"]
        if decision not in {"accepted", "rejected"}:
            raise ValidationError("warehouse final-decision proposal decision is invalid")
        reason_raw = payload["reason_code"]
        if reason_raw is None:
            reason = None
        elif isinstance(reason_raw, str):
            reason = normalize_reason_category(reason_raw)
            if reason != reason_raw:
                raise ValidationError("proposal reason_code must already be normalized")
        else:
            raise ValidationError("proposal reason_code must be text or null")
        if decision == "rejected" and reason is None:
            raise ValidationError("warehouse rejection proposal requires reason_code")
        return ParsedInventoryProposalTarget(
            proposal_target_id=target_row_id,
            membership_id=membership,
            expected_revision=revision,
            action="warehouse_final_decision",
            effective_at_utc=_effective_at(payload["effective_at_utc"]),
            decision=str(decision),
            reason_code=reason,
        )

    raise ValidationError("proposal kind has no accepted Inventory owner mapping in v1")


__all__ = [
    "ParsedInventoryProposalTarget",
    "normalize_reason_category",
    "parse_inventory_proposal_target",
    "source_evidence_ref",
    "validate_fingerprint",
    "validate_positive_revision",
    "validate_proposal_id",
    "validate_proposal_kind",
    "validate_risk_tier",
    "validate_target_kind",
]
