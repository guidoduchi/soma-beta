from __future__ import annotations

import re

from soma.foundation.audit.registry import AuditActionContract, AuditRegistry
from soma.foundation.errors import SomaError, ValidationError
from soma.foundation.identifiers import require_uuid4
from soma.foundation.strict_json import ObjectContract

_SHA256 = re.compile(r"[0-9a-f]{64}\Z")


def _contract(name: str, fields: frozenset[str]) -> ObjectContract:
    return ObjectContract(
        name=name,
        version=1,
        required_fields=fields,
        allowed_fields=fields,
        max_depth=4,
        max_collection_items=32,
        max_utf8_bytes=16_384,
    )


def _uuid(value: object, field: str, *, nullable: bool = False) -> None:
    if value is None and nullable:
        return
    try:
        if not isinstance(value, str):
            raise ValidationError(f"{field} must be UUID text")
        require_uuid4(value)
    except ValidationError as exc:
        raise SomaError("AUDIT_PAYLOAD_INVALID", f"{field} is invalid") from exc


def _sha(value: object, field: str, *, nullable: bool = False) -> None:
    if value is None and nullable:
        return
    if not isinstance(value, str) or _SHA256.fullmatch(value) is None:
        raise SomaError("AUDIT_PAYLOAD_INVALID", f"{field} must be lowercase SHA-256")


def _positive(value: object, field: str, *, zero: bool = False) -> None:
    minimum = 0 if zero else 1
    if type(value) is not int or value < minimum:
        raise SomaError("AUDIT_PAYLOAD_INVALID", f"{field} is invalid")


_IDENTITY_FIELDS = frozenset(
    {
        "entity_type",
        "entity_id",
        "tracking_id",
        "origin",
        "resulting_revision",
        "bom_fingerprint",
        "serial_fingerprint",
    }
)
_NEED_FIELDS = frozenset(
    {
        "spare_need_id",
        "service_request_id",
        "event_kind",
        "planned_quantity",
        "contributor_id",
        "resulting_revision",
        "reason_category",
    }
)


def _validate_identity(payload: dict[str, object]) -> None:
    if payload.get("entity_type") not in {"device_part_unit", "spare_part_unit"}:
        raise SomaError("AUDIT_PAYLOAD_INVALID", "Inventory identity type is invalid")
    _uuid(payload.get("entity_id"), "entity_id")
    tracking = payload.get("tracking_id")
    if tracking is not None and (not isinstance(tracking, str) or not tracking):
        raise SomaError("AUDIT_PAYLOAD_INVALID", "Inventory tracking id is invalid")
    if payload.get("origin") not in {
        "manual_fault_registration",
        "manual_component_registration",
        "reviewed_reconciliation",
        "manual_local",
        "legacy",
        "direct_rma_inbound",
        "extracted",
    }:
        raise SomaError("AUDIT_PAYLOAD_INVALID", "Inventory identity origin is invalid")
    _positive(payload.get("resulting_revision"), "resulting_revision")
    _sha(payload.get("bom_fingerprint"), "bom_fingerprint")
    _sha(payload.get("serial_fingerprint"), "serial_fingerprint", nullable=True)


def _validate_need(payload: dict[str, object]) -> None:
    _uuid(payload.get("spare_need_id"), "spare_need_id")
    _uuid(payload.get("service_request_id"), "service_request_id")
    if payload.get("event_kind") not in {
        "CREATED",
        "CONTRIBUTOR_ADDED",
        "PLANNED_QUANTITY_CHANGED",
        "RESOLVED",
        "CANCELLED",
        "REACTIVATED",
        "HISTORY_REMOVED",
    }:
        raise SomaError("AUDIT_PAYLOAD_INVALID", "Spare Need event kind is invalid")
    planned = payload.get("planned_quantity")
    if planned is not None:
        _positive(planned, "planned_quantity")
    _uuid(payload.get("contributor_id"), "contributor_id", nullable=True)
    _positive(payload.get("resulting_revision"), "resulting_revision")
    reason = payload.get("reason_category")
    if reason is not None and (not isinstance(reason, str) or not reason):
        raise SomaError("AUDIT_PAYLOAD_INVALID", "Spare Need reason category is invalid")


def build_inventory_audit_registry() -> AuditRegistry:
    registry = AuditRegistry()
    for action, schema, fields, validator in (
        (
            "inventory.device_part.registered",
            "InventoryIdentityAuditV1",
            _IDENTITY_FIELDS,
            _validate_identity,
        ),
        (
            "inventory.spare_need.changed",
            "SpareNeedAuditV1",
            _NEED_FIELDS,
            _validate_need,
        ),
    ):
        registry.register(
            AuditActionContract(
                action_type=action,
                action_version=1,
                payload_schema=schema,
                payload_version=1,
                payload_contract=_contract(schema, fields),
                sensitivity_validator=validator,
            )
        )
    return registry


__all__ = ["build_inventory_audit_registry"]
