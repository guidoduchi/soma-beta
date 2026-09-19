from __future__ import annotations

import re

from soma.foundation.audit.registry import AuditActionContract, AuditRegistry
from soma.foundation.errors import SomaError, ValidationError
from soma.foundation.identifiers import require_uuid4
from soma.foundation.strict_json import ObjectContract

_SHA256 = re.compile(r"[0-9a-f]{64}\Z")
_NEED_EVENTS = frozenset(
    {
        "CREATE",
        "CONTRIBUTOR_ADDED",
        "PLANNED_QUANTITY_CHANGED",
        "RESOLVE",
        "CANCEL",
        "REACTIVATE",
        "HISTORY_REMOVE",
    }
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


def _fingerprint(value: object, field: str, *, nullable: bool = False) -> None:
    if value is None and nullable:
        return
    if not isinstance(value, str) or _SHA256.fullmatch(value) is None:
        raise SomaError("AUDIT_PAYLOAD_INVALID", f"{field} is invalid")


def _positive(value: object, field: str, *, nullable: bool = False) -> None:
    if value is None and nullable:
        return
    if type(value) is not int or value <= 0:
        raise SomaError("AUDIT_PAYLOAD_INVALID", f"{field} is invalid")


def _reason(value: object) -> None:
    if value is None:
        return
    if not isinstance(value, str) or not value or len(value.encode("utf-8", errors="strict")) > 384:
        raise SomaError("AUDIT_PAYLOAD_INVALID", "reason_category is invalid")


def _validate_identity(payload: dict[str, object]) -> None:
    if payload.get("entity_type") != "device_part_unit":
        raise SomaError("AUDIT_PAYLOAD_INVALID", "Inventory identity entity type is invalid")
    _uuid(payload.get("entity_id"), "entity_id")
    if payload.get("tracking_id") is not None:
        raise SomaError("AUDIT_PAYLOAD_INVALID", "Device Part Unit cannot carry tracking identity")
    if payload.get("origin") not in {
        "manual_fault_registration",
        "manual_component_registration",
        "reviewed_reconciliation",
    }:
        raise SomaError("AUDIT_PAYLOAD_INVALID", "Inventory identity origin is invalid")
    _positive(payload.get("resulting_revision"), "resulting_revision")
    _fingerprint(payload.get("bom_fingerprint"), "bom_fingerprint")
    _fingerprint(payload.get("serial_fingerprint"), "serial_fingerprint", nullable=True)


def _validate_need(payload: dict[str, object]) -> None:
    _uuid(payload.get("spare_need_id"), "spare_need_id")
    _uuid(payload.get("service_request_id"), "service_request_id")
    if payload.get("event_kind") not in _NEED_EVENTS:
        raise SomaError("AUDIT_PAYLOAD_INVALID", "Spare Need event kind is invalid")
    _positive(payload.get("planned_quantity"), "planned_quantity", nullable=True)
    _uuid(payload.get("contributor_id"), "contributor_id", nullable=True)
    _positive(payload.get("resulting_revision"), "resulting_revision")
    _reason(payload.get("reason_category"))



_SPARE_UNIT_EVENTS = frozenset({"REGISTER", "RESERVE", "RELEASE", "LOCAL_SELECTION"})
_LSU = re.compile(r"LSU-[0-9]{8}\Z")


def _validate_spare_unit(payload: dict[str, object]) -> None:
    _uuid(payload.get("spare_part_unit_id"), "spare_part_unit_id")
    if payload.get("event_kind") not in _SPARE_UNIT_EVENTS:
        raise SomaError("AUDIT_PAYLOAD_INVALID", "Spare Part Unit event kind is invalid")
    tracking_id = payload.get("local_tracking_id")
    if tracking_id is not None and (
        not isinstance(tracking_id, str) or _LSU.fullmatch(tracking_id) is None
    ):
        raise SomaError("AUDIT_PAYLOAD_INVALID", "local_tracking_id is invalid")
    _uuid(payload.get("task_id"), "task_id", nullable=True)
    _uuid(payload.get("allocation_id"), "allocation_id", nullable=True)
    _uuid(payload.get("spare_need_id"), "spare_need_id", nullable=True)
    _positive(payload.get("resulting_unit_revision"), "resulting_unit_revision")
    _positive(payload.get("allocation_revision"), "allocation_revision", nullable=True)
    _fingerprint(payload.get("bom_fingerprint"), "bom_fingerprint", nullable=True)
    _reason(payload.get("reason_category"))


def _contract(name: str, fields: frozenset[str]) -> ObjectContract:
    return ObjectContract(
        name=name,
        version=1,
        required_fields=fields,
        allowed_fields=fields,
        max_depth=3,
        max_collection_items=16,
        max_utf8_bytes=16_384,
    )


def build_inventory_audit_registry() -> AuditRegistry:
    registry = AuditRegistry()
    registry.register(
        AuditActionContract(
            action_type="inventory.device_part.registered",
            action_version=1,
            payload_schema="InventoryIdentityAuditV1",
            payload_version=1,
            payload_contract=_contract(
                "InventoryIdentityAuditV1",
                frozenset(
                    {
                        "entity_type",
                        "entity_id",
                        "tracking_id",
                        "origin",
                        "resulting_revision",
                        "bom_fingerprint",
                        "serial_fingerprint",
                    }
                ),
            ),
            sensitivity_validator=_validate_identity,
        )
    )
    registry.register(
        AuditActionContract(
            action_type="inventory.spare_need.changed",
            action_version=1,
            payload_schema="SpareNeedAuditV1",
            payload_version=1,
            payload_contract=_contract(
                "SpareNeedAuditV1",
                frozenset(
                    {
                        "spare_need_id",
                        "service_request_id",
                        "event_kind",
                        "planned_quantity",
                        "contributor_id",
                        "resulting_revision",
                        "reason_category",
                    }
                ),
            ),
            sensitivity_validator=_validate_need,
        )
    )
    registry.register(
        AuditActionContract(
            action_type="inventory.spare_unit.registered_or_reserved",
            action_version=1,
            payload_schema="SpareUnitAuditV1",
            payload_version=1,
            payload_contract=_contract(
                "SpareUnitAuditV1",
                frozenset(
                    {
                        "spare_part_unit_id",
                        "event_kind",
                        "local_tracking_id",
                        "task_id",
                        "allocation_id",
                        "spare_need_id",
                        "resulting_unit_revision",
                        "allocation_revision",
                        "bom_fingerprint",
                        "reason_category",
                    }
                ),
            ),
            sensitivity_validator=_validate_spare_unit,
        )
    )
    return registry


__all__ = ["build_inventory_audit_registry"]
