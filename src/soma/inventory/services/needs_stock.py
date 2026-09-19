from __future__ import annotations

import hashlib

from soma.foundation.application.command_boundary import CommandBoundary, CommandEnvelope, PreparedMutation
from soma.foundation.audit.writer import AuditEventInput, AuditResultRef, AuditWriter
from soma.foundation.errors import IntegrityFailure, SomaError, ValidationError
from soma.foundation.identifiers import new_uuid4, require_uuid4, utc_epoch_seconds
from soma.foundation.persistence.connections import ConnectionFactory
from soma.foundation.persistence.uow import ReadSnapshot, UnitOfWork
from soma.foundation.strict_json import sha256_canonical_json

from ..audit_registry import build_inventory_audit_registry
from ..contracts.inventory import InventoryMutationResult, inventory_result_from_execution
from ..domain.validation import (
    normalize_part_code,
    normalize_serial,
    normalize_slot_label,
    validate_condition,
    validate_effective_at,
    validate_positive_quantity,
    validate_reason,
)
from ..repositories.needs import InventoryNeedRepository


def _ref(ref_type: str, ref_id: str) -> dict[str, str]:
    return {"type": ref_type, "id": ref_id}


def _revision_key(ref_type: str, ref_id: str) -> str:
    return f"{ref_type}:{ref_id}"


class InventoryNeedsStockService:
    def __init__(self, connection_factory: ConnectionFactory) -> None:
        self._factory = connection_factory
        self._boundary = CommandBoundary(
            connection_factory,
            AuditWriter(build_inventory_audit_registry()),
        )

    def preview_device_part_duplicates(
        self,
        *,
        service_request_id: str,
        bom_code: str,
        manufacturer_serial: str | None = None,
    ) -> tuple[str, ...]:
        sr_id = require_uuid4(service_request_id)
        _stored_bom, bom_key = normalize_part_code(bom_code)
        _stored_serial, serial_key = normalize_serial(manufacturer_serial)
        with ReadSnapshot(self._factory) as snapshot:
            if serial_key is None:
                rows = snapshot.connection.execute(
                    "SELECT device_part_unit_id FROM device_part_units "
                    "WHERE service_request_id=? AND bom_key=? "
                    "ORDER BY creation_sequence,device_part_unit_id LIMIT 500",
                    (sr_id, bom_key),
                ).fetchall()
            else:
                rows = snapshot.connection.execute(
                    "SELECT device_part_unit_id FROM device_part_units "
                    "WHERE service_request_id=? AND bom_key=? AND serial_key=? "
                    "ORDER BY creation_sequence,device_part_unit_id LIMIT 500",
                    (sr_id, bom_key, serial_key),
                ).fetchall()
        return tuple(str(row[0]) for row in rows)

    def register_device_part_unit(
        self,
        *,
        command_id: str,
        service_request_id: str,
        device_reference_id: str,
        bom_code: str,
        manufacturer_serial: str | None = None,
        slot_label: str | None = None,
        condition_token: str | None = None,
        effective_at_utc: int | None = None,
        actor_kind: str = "local_user",
        actor_id: str | None = None,
    ) -> InventoryMutationResult:
        sr_id = require_uuid4(service_request_id)
        device_id = require_uuid4(device_reference_id)
        stored_bom, bom_key = normalize_part_code(bom_code)
        stored_serial, serial_key = normalize_serial(manufacturer_serial)
        slot = normalize_slot_label(slot_label)
        condition = validate_condition(condition_token)
        effective = validate_effective_at(effective_at_utc)
        origin = (
            "manual_fault_registration"
            if condition == "faulty"
            else "manual_component_registration"
        )
        envelope = CommandEnvelope(
            command_id=command_id,
            command_type="RegisterDevicePartUnit",
            target_type="device_part_unit",
            target_id=None,
            semantic_payload={
                "service_request_id": sr_id,
                "device_reference_id": device_id,
                "bom_code": stored_bom,
                "bom_key": bom_key,
                "manufacturer_serial": stored_serial,
                "serial_key": serial_key,
                "slot_label": slot,
                "condition_token": condition,
                "effective_at_utc": effective,
                "creation_origin": origin,
            },
        )

        def prepare(uow: UnitOfWork) -> PreparedMutation:
            if uow.connection.execute(
                "SELECT 1 FROM service_requests WHERE service_request_id=?",
                (sr_id,),
            ).fetchone() is None:
                raise SomaError("INV_STALE", "Service Request no longer exists")
            if uow.connection.execute(
                "SELECT 1 FROM sr_device_reference_links "
                "WHERE service_request_id=? AND device_reference_id=? AND link_state='active'",
                (sr_id, device_id),
            ).fetchone() is None:
                raise SomaError(
                    "NEED_CROSS_SR",
                    "Device Reference is not active in the selected Service Request",
                )

            creation_sequence_row = uow.connection.execute(
                "SELECT next_sequence FROM inventory_tracking_allocators "
                "WHERE allocator_kind='device_part_creation'"
            ).fetchone()
            if creation_sequence_row is None or int(creation_sequence_row[0]) >= 100_000_000:
                raise SomaError("INV_INVALID_ID", "Device Part creation sequence is exhausted")
            creation_sequence = int(creation_sequence_row[0])

            unit_id = new_uuid4()
            registered_event_id = new_uuid4()
            fault_event_id = new_uuid4() if condition == "faulty" else None
            contributor_id = new_uuid4()
            now = utc_epoch_seconds()

            active_need_id = InventoryNeedRepository.active_need_id(
                uow.connection,
                sr_id,
                bom_key,
            )
            creating_need = active_need_id is None
            need_id = new_uuid4() if creating_need else active_need_id
            assert need_id is not None
            existing_need = (
                None
                if creating_need
                else InventoryNeedRepository.load_projection(uow.connection, need_id)
            )
            if existing_need is not None and (
                existing_need.service_request_id != sr_id or existing_need.bom_key != bom_key
            ):
                raise SomaError("NEED_CROSS_SR", "Active Need key points at incompatible demand")
            need_revision = 1 if existing_need is None else existing_need.revision + 1
            need_planned_quantity = 1 if existing_need is None else existing_need.planned_quantity
            need_created_event_id = new_uuid4() if creating_need else None

            response = {
                "outcome": "APPLIED",
                "target_refs": [
                    _ref("device_part_unit", unit_id),
                    _ref("spare_need", need_id),
                    _ref("spare_need_contributor", contributor_id),
                ],
                "revisions": {
                    _revision_key("device_part_unit", unit_id): 1,
                    _revision_key("spare_need", need_id): need_revision,
                },
            }

            def apply(inner: UnitOfWork):
                allocated = InventoryNeedRepository.allocate_creation_sequence(inner, command_id)
                if allocated != creation_sequence:
                    raise IntegrityFailure("Inventory allocator changed inside one writer UnitOfWork")
                inner.connection.execute(
                    "INSERT INTO device_part_units("
                    "device_part_unit_id,service_request_id,device_reference_id,creation_sequence,"
                    "bom_code,bom_key,manufacturer_serial,serial_key,slot_label,creation_origin,"
                    "created_at_utc,created_command_id"
                    ") VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
                    (
                        unit_id,
                        sr_id,
                        device_id,
                        creation_sequence,
                        stored_bom,
                        bom_key,
                        stored_serial,
                        serial_key,
                        slot,
                        origin,
                        now,
                        command_id,
                    ),
                )
                inner.connection.execute(
                    "INSERT INTO device_part_lifecycle_events("
                    "device_part_event_id,device_part_unit_id,event_kind,condition_token,"
                    "effective_at_utc,target_event_id,reason_code,evidence_kind,evidence_id,"
                    "recorded_at_utc,command_id"
                    ") VALUES (?,?, 'registered', ?, ?, NULL, NULL, NULL, NULL, ?, ?)",
                    (
                        registered_event_id,
                        unit_id,
                        "unknown" if fault_event_id is not None else condition,
                        effective,
                        now,
                        command_id,
                    ),
                )
                last_event_id = registered_event_id
                if fault_event_id is not None:
                    inner.connection.execute(
                        "INSERT INTO device_part_lifecycle_events("
                        "device_part_event_id,device_part_unit_id,event_kind,condition_token,"
                        "effective_at_utc,target_event_id,reason_code,evidence_kind,evidence_id,"
                        "recorded_at_utc,command_id"
                        ") VALUES (?,?, 'fault_observed', 'faulty', ?, NULL, NULL, NULL, NULL, ?, ?)",
                        (fault_event_id, unit_id, effective, now, command_id),
                    )
                    last_event_id = fault_event_id
                device_fingerprint = sha256_canonical_json(
                    {
                        "schema": "INVENTORY_DEVICE_PART_PROJECTION_V1",
                        "device_part_unit_id": unit_id,
                        "condition_token": condition,
                        "last_event_id": last_event_id,
                    }
                )
                inner.connection.execute(
                    "INSERT INTO device_part_current_projection("
                    "device_part_unit_id,condition_token,revision,input_fingerprint,last_event_id,last_command_id"
                    ") VALUES (?,?,1,?,?,?)",
                    (unit_id, condition, device_fingerprint, last_event_id, command_id),
                )

                if creating_need:
                    assert need_created_event_id is not None
                    inner.connection.execute(
                        "INSERT INTO spare_needs("
                        "spare_need_id,service_request_id,bom_code,bom_key,description,planned_quantity,"
                        "creation_origin,created_at_utc,created_command_id"
                        ") VALUES (?,?,?,?,NULL,1,'system_aggregate',?,?)",
                        (need_id, sr_id, stored_bom, bom_key, now, command_id),
                    )
                    inner.connection.execute(
                        "INSERT INTO spare_need_lifecycle_events("
                        "need_event_id,spare_need_id,event_kind,planned_quantity,reason_code,"
                        "effective_at_utc,recorded_at_utc,command_id"
                        ") VALUES (?,?, 'created',1,NULL,?,?,?)",
                        (need_created_event_id, need_id, effective, now, command_id),
                    )
                    inner.connection.execute(
                        "INSERT INTO spare_need_active_keys(service_request_id,bom_key,spare_need_id) "
                        "VALUES (?,?,?)",
                        (sr_id, bom_key, need_id),
                    )

                inner.connection.execute(
                    "INSERT INTO spare_need_contributors("
                    "contributor_relationship_id,spare_need_id,device_part_unit_id,active,"
                    "opened_at_utc,opened_command_id,closed_at_utc,closed_command_id,close_reason"
                    ") VALUES (?,?,?,1,?,?,NULL,NULL,NULL)",
                    (contributor_id, need_id, unit_id, now, command_id),
                )
                InventoryNeedRepository.rebuild_projection(
                    inner,
                    spare_need_id=need_id,
                    lifecycle_state="active",
                    planned_quantity=need_planned_quantity,
                    revision=need_revision,
                    command_id=command_id,
                )

                bom_fingerprint = hashlib.sha256(bom_key.encode("utf-8")).hexdigest()
                serial_fingerprint = (
                    None
                    if serial_key is None
                    else hashlib.sha256(serial_key.encode("utf-8")).hexdigest()
                )
                identity_audit = AuditEventInput(
                    audit_event_id=new_uuid4(),
                    action_type="inventory.device_part.registered",
                    action_version=1,
                    actor_kind=actor_kind,
                    actor_id=actor_id,
                    target_type="device_part_unit",
                    target_id=unit_id,
                    command_id=command_id,
                    payload_schema="InventoryIdentityAuditV1",
                    payload_version=1,
                    payload={
                        "entity_type": "device_part_unit",
                        "entity_id": unit_id,
                        "tracking_id": None,
                        "origin": origin,
                        "resulting_revision": 1,
                        "bom_fingerprint": bom_fingerprint,
                        "serial_fingerprint": serial_fingerprint,
                    },
                    resulting_event_refs=(
                        AuditResultRef("device_part_unit", unit_id),
                        AuditResultRef("spare_need", need_id),
                    ),
                )
                need_audit = AuditEventInput(
                    audit_event_id=new_uuid4(),
                    action_type="inventory.spare_need.changed",
                    action_version=1,
                    actor_kind=actor_kind,
                    actor_id=actor_id,
                    target_type="spare_need",
                    target_id=need_id,
                    command_id=command_id,
                    payload_schema="SpareNeedAuditV1",
                    payload_version=1,
                    payload={
                        "spare_need_id": need_id,
                        "service_request_id": sr_id,
                        "event_kind": "CREATED" if creating_need else "CONTRIBUTOR_ADDED",
                        "planned_quantity": need_planned_quantity,
                        "contributor_id": contributor_id,
                        "resulting_revision": need_revision,
                        "reason_category": None,
                    },
                    resulting_event_refs=(
                        AuditResultRef("spare_need", need_id),
                        AuditResultRef("spare_need_contributor", contributor_id),
                    ),
                )
                return (identity_audit, need_audit)

            return PreparedMutation(
                False,
                "device_part_unit",
                unit_id,
                apply,
                response_schema="InventoryMutationResultV1",
                response=response,
            )

        return inventory_result_from_execution(self._boundary.execute(envelope, prepare))

    def set_spare_need_planned_quantity(
        self,
        *,
        command_id: str,
        spare_need_id: str,
        base_revision: int,
        planned_quantity: int,
        reason: str,
        actor_kind: str = "local_user",
        actor_id: str | None = None,
    ) -> InventoryMutationResult:
        need_id = require_uuid4(spare_need_id)
        quantity = validate_positive_quantity(planned_quantity)
        reason_code = validate_reason(reason)
        envelope = CommandEnvelope(
            command_id=command_id,
            command_type="SetSpareNeedPlannedQuantity",
            target_type="spare_need",
            target_id=need_id,
            semantic_payload={
                "planned_quantity": quantity,
                "reason": reason_code,
            },
            base_revisions={"spare_need": base_revision},
        )

        def prepare(uow: UnitOfWork) -> PreparedMutation:
            current = InventoryNeedRepository.load_projection(uow.connection, need_id)
            if current is None or current.revision != base_revision:
                raise SomaError("INV_STALE", "Spare Need revision changed")
            response = {
                "outcome": "NO_CHANGE" if current.planned_quantity == quantity else "APPLIED",
                "target_refs": [_ref("spare_need", need_id)],
                "revisions": {
                    _revision_key("spare_need", need_id): (
                        current.revision
                        if current.planned_quantity == quantity
                        else current.revision + 1
                    )
                },
            }
            if current.planned_quantity == quantity:
                return PreparedMutation(
                    True,
                    None,
                    None,
                    response_schema="InventoryMutationResultV1",
                    response=response,
                )
            event_id = new_uuid4()
            now = utc_epoch_seconds()
            next_revision = current.revision + 1

            def apply(inner: UnitOfWork):
                inner.connection.execute(
                    "INSERT INTO spare_need_lifecycle_events("
                    "need_event_id,spare_need_id,event_kind,planned_quantity,reason_code,"
                    "effective_at_utc,recorded_at_utc,command_id"
                    ") VALUES (?,?, 'planned_quantity_changed',?,?,NULL,?,?)",
                    (event_id, need_id, quantity, reason_code, now, command_id),
                )
                InventoryNeedRepository.rebuild_projection(
                    inner,
                    spare_need_id=need_id,
                    lifecycle_state=current.lifecycle_state,
                    planned_quantity=quantity,
                    revision=next_revision,
                    command_id=command_id,
                )
                return AuditEventInput(
                    audit_event_id=new_uuid4(),
                    action_type="inventory.spare_need.changed",
                    action_version=1,
                    actor_kind=actor_kind,
                    actor_id=actor_id,
                    target_type="spare_need",
                    target_id=need_id,
                    reason_category=reason_code,
                    command_id=command_id,
                    payload_schema="SpareNeedAuditV1",
                    payload_version=1,
                    payload={
                        "spare_need_id": need_id,
                        "service_request_id": current.service_request_id,
                        "event_kind": "PLANNED_QUANTITY_CHANGED",
                        "planned_quantity": quantity,
                        "contributor_id": None,
                        "resulting_revision": next_revision,
                        "reason_category": reason_code,
                    },
                    resulting_event_refs=(AuditResultRef("spare_need", need_id),),
                )

            return PreparedMutation(
                False,
                "spare_need",
                need_id,
                apply,
                response_schema="InventoryMutationResultV1",
                response=response,
            )

        return inventory_result_from_execution(self._boundary.execute(envelope, prepare))

    def change_spare_need_lifecycle(
        self,
        *,
        command_id: str,
        spare_need_id: str,
        base_revision: int,
        action: str,
        reason: str,
        actor_kind: str = "local_user",
        actor_id: str | None = None,
    ) -> InventoryMutationResult:
        need_id = require_uuid4(spare_need_id)
        reason_code = validate_reason(reason)
        mapping = {
            "resolve": ("resolved", "resolved", "RESOLVED"),
            "cancel": ("cancelled", "cancelled", "CANCELLED"),
            "reactivate": ("active", "reactivated", "REACTIVATED"),
            "history_remove": ("removed", "history_removed", "HISTORY_REMOVED"),
        }
        if action not in mapping:
            raise ValidationError("Spare Need lifecycle action is invalid")
        target_state, event_kind, audit_kind = mapping[action]
        envelope = CommandEnvelope(
            command_id=command_id,
            command_type="ChangeSpareNeedLifecycle",
            target_type="spare_need",
            target_id=need_id,
            semantic_payload={"action": action, "reason": reason_code},
            base_revisions={"spare_need": base_revision},
        )

        def prepare(uow: UnitOfWork) -> PreparedMutation:
            current = InventoryNeedRepository.load_projection(uow.connection, need_id)
            if current is None or current.revision != base_revision:
                raise SomaError("INV_STALE", "Spare Need revision changed")
            allowed = {
                "active": {"resolve", "cancel"},
                "resolved": {"reactivate", "history_remove"},
                "cancelled": {"reactivate", "history_remove"},
                "removed": set(),
            }
            if action not in allowed.get(current.lifecycle_state, set()):
                raise SomaError(
                    "INV_STALE",
                    "Spare Need lifecycle action is incompatible with current state",
                )
            if action == "reactivate":
                competing = InventoryNeedRepository.active_need_id(
                    uow.connection,
                    current.service_request_id,
                    current.bom_key,
                )
                if competing is not None and competing != need_id:
                    raise SomaError("INV_STALE", "Another active Need owns the SR+BOM key")
            if action == "history_remove":
                row = uow.connection.execute(
                    "SELECT 1 FROM spare_request_need_allocations a "
                    "JOIN spare_request_current_projection p ON p.spare_request_id=a.spare_request_id "
                    "WHERE a.spare_need_id=? "
                    "AND p.lifecycle_state NOT IN ('cancelled','rejected') LIMIT 1",
                    (need_id,),
                ).fetchone()
                if row is not None:
                    raise SomaError(
                        "NEED_DELETE_BLOCKED",
                        "Spare Need has a nonterminal Spare Request dependency",
                    )
            event_id = new_uuid4()
            now = utc_epoch_seconds()
            next_revision = current.revision + 1
            response = {
                "outcome": "APPLIED",
                "target_refs": [_ref("spare_need", need_id)],
                "revisions": {_revision_key("spare_need", need_id): next_revision},
            }

            def apply(inner: UnitOfWork):
                if target_state == "active":
                    inner.connection.execute(
                        "INSERT INTO spare_need_active_keys(service_request_id,bom_key,spare_need_id) "
                        "VALUES (?,?,?)",
                        (current.service_request_id, current.bom_key, need_id),
                    )
                elif current.lifecycle_state == "active":
                    inner.connection.execute(
                        "DELETE FROM spare_need_active_keys WHERE spare_need_id=?",
                        (need_id,),
                    )
                inner.connection.execute(
                    "INSERT INTO spare_need_lifecycle_events("
                    "need_event_id,spare_need_id,event_kind,planned_quantity,reason_code,"
                    "effective_at_utc,recorded_at_utc,command_id"
                    ") VALUES (?,?,?,?,?,NULL,?,?)",
                    (
                        event_id,
                        need_id,
                        event_kind,
                        current.planned_quantity,
                        reason_code,
                        now,
                        command_id,
                    ),
                )
                InventoryNeedRepository.rebuild_projection(
                    inner,
                    spare_need_id=need_id,
                    lifecycle_state=target_state,
                    planned_quantity=current.planned_quantity,
                    revision=next_revision,
                    command_id=command_id,
                )
                return AuditEventInput(
                    audit_event_id=new_uuid4(),
                    action_type="inventory.spare_need.changed",
                    action_version=1,
                    actor_kind=actor_kind,
                    actor_id=actor_id,
                    target_type="spare_need",
                    target_id=need_id,
                    reason_category=reason_code,
                    command_id=command_id,
                    payload_schema="SpareNeedAuditV1",
                    payload_version=1,
                    payload={
                        "spare_need_id": need_id,
                        "service_request_id": current.service_request_id,
                        "event_kind": audit_kind,
                        "planned_quantity": current.planned_quantity,
                        "contributor_id": None,
                        "resulting_revision": next_revision,
                        "reason_category": reason_code,
                    },
                    resulting_event_refs=(AuditResultRef("spare_need", need_id),),
                )

            return PreparedMutation(
                False,
                "spare_need",
                need_id,
                apply,
                response_schema="InventoryMutationResultV1",
                response=response,
            )

        return inventory_result_from_execution(self._boundary.execute(envelope, prepare))


__all__ = ["InventoryNeedsStockService"]
