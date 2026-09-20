from __future__ import annotations

import hashlib

from soma.foundation.application.command_boundary import CommandBoundary, CommandEnvelope, PreparedMutation
from soma.foundation.audit.writer import AuditEventInput, AuditResultRef, AuditWriter
from soma.foundation.errors import IntegrityFailure, SomaError, ValidationError
from soma.foundation.identifiers import new_uuid4, require_uuid4
from soma.foundation.persistence.connections import ConnectionFactory
from soma.foundation.persistence.uow import UnitOfWork

from ..audit_registry import build_inventory_audit_registry
from ..contracts.inventory import InventoryMutationResult, inventory_mutation_result_from_execution
from ..domain.needs import (
    normalize_optional_serial,
    normalize_optional_slot,
    normalize_part_code,
    validate_condition_token,
    validate_effective_at_utc,
    validate_planned_quantity,
    validate_reason_code,
)
from ..domain.units import (
    initial_disposition_for_condition,
    normalize_custody_text,
    normalize_location_kind,
    normalize_location_ref,
    normalize_spare_part_identity,
    validate_spare_condition,
    validate_spare_part_origin,
    validate_unit_effective_at_utc,
)
from ..repositories.needs import InventoryNeedsRepository
from ..repositories.units import InventoryUnitsRepository

_ORIGINS = frozenset(
    {"manual_fault_registration", "manual_component_registration", "reviewed_reconciliation"}
)
_LIFECYCLE_ACTIONS = frozenset({"resolve", "cancel", "reactivate", "history_remove"})


class InventoryNeedsStockService:
    def __init__(self, connection_factory: ConnectionFactory) -> None:
        self._factory = connection_factory
        self._repository = InventoryNeedsRepository()
        self._units = InventoryUnitsRepository()
        self._boundary = CommandBoundary(
            connection_factory,
            AuditWriter(build_inventory_audit_registry()),
        )

    @staticmethod
    def _fingerprint(value: str | None) -> str | None:
        if value is None:
            return None
        return hashlib.sha256(value.encode("utf-8", errors="strict")).hexdigest()

    @staticmethod
    def _response(
        refs: list[tuple[str, str]],
        revisions: dict[str, int],
        *,
        outcome: str = "APPLIED",
    ) -> dict[str, object]:
        return {
            "outcome": outcome,
            "target_refs": [{"type": kind, "id": identity} for kind, identity in refs],
            "revisions": dict(revisions),
        }

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
        creation_origin: str = "manual_fault_registration",
        actor_kind: str = "local_user",
        actor_id: str | None = None,
    ) -> InventoryMutationResult:
        require_uuid4(service_request_id)
        require_uuid4(device_reference_id)
        stored_bom, bom_key = normalize_part_code(bom_code)
        stored_serial, serial_key = normalize_optional_serial(manufacturer_serial)
        slot = normalize_optional_slot(slot_label)
        condition = validate_condition_token(condition_token)
        effective = validate_effective_at_utc(effective_at_utc)
        if creation_origin not in _ORIGINS:
            raise ValidationError("creation_origin is invalid")
        envelope = CommandEnvelope(
            command_id=command_id,
            command_type="RegisterDevicePartUnit",
            target_type="device_part_unit",
            target_id=None,
            semantic_payload={
                "service_request_id": service_request_id,
                "device_reference_id": device_reference_id,
                "bom_code": stored_bom,
                "bom_key": bom_key,
                "manufacturer_serial": stored_serial,
                "serial_key": serial_key,
                "slot_label": slot,
                "condition_token": condition,
                "effective_at_utc": effective,
                "creation_origin": creation_origin,
            },
        )

        def prepare(uow: UnitOfWork) -> PreparedMutation:
            self._repository.require_sr_device_context(
                uow.connection,
                service_request_id,
                device_reference_id,
            )
            device_part_unit_id = new_uuid4()

            def apply(inner: UnitOfWork):
                self._repository.require_sr_device_context(
                    inner.connection,
                    service_request_id,
                    device_reference_id,
                )
                sequence = self._repository.allocate_device_part_creation_sequence(
                    inner.connection,
                    command_id,
                )
                _last_event_id, unit_revision = self._repository.insert_device_part(
                    inner.connection,
                    device_part_unit_id=device_part_unit_id,
                    service_request_id=service_request_id,
                    device_reference_id=device_reference_id,
                    creation_sequence=sequence,
                    bom_code=stored_bom,
                    bom_key=bom_key,
                    manufacturer_serial=stored_serial,
                    serial_key=serial_key,
                    slot_label=slot,
                    creation_origin=creation_origin,
                    condition_token=condition,
                    effective_at_utc=effective,
                    command_id=command_id,
                )
                refs: list[tuple[str, str]] = [("device_part_unit", device_part_unit_id)]
                revisions: dict[str, int] = {
                    f"device_part_unit:{device_part_unit_id}": unit_revision
                }
                audits: list[AuditEventInput] = []
                need_ref: str | None = None

                if condition == "faulty":
                    active = self._repository.active_need_for(
                        inner.connection,
                        service_request_id,
                        bom_key,
                    )
                    if active is None:
                        (
                            spare_need_id,
                            need_event_id,
                            contributor_id,
                            need_revision,
                        ) = self._repository.create_need_with_contributor(
                            inner.connection,
                            service_request_id=service_request_id,
                            bom_code=stored_bom,
                            bom_key=bom_key,
                            device_part_unit_id=device_part_unit_id,
                            command_id=command_id,
                        )
                        event_kind = "CREATE"
                        planned_quantity = 1
                        refs.extend(
                            [
                                ("spare_need", spare_need_id),
                                ("spare_need_contributor", contributor_id),
                                ("spare_need_event", need_event_id),
                            ]
                        )
                    else:
                        spare_need_id = str(active[0])
                        contributor_id, need_revision, planned_quantity = (
                            self._repository.add_contributor(
                                inner.connection,
                                spare_need_id=spare_need_id,
                                service_request_id=service_request_id,
                                bom_key=bom_key,
                                device_part_unit_id=device_part_unit_id,
                                command_id=command_id,
                            )
                        )
                        event_kind = "CONTRIBUTOR_ADDED"
                        refs.extend(
                            [
                                ("spare_need", spare_need_id),
                                ("spare_need_contributor", contributor_id),
                            ]
                        )
                    need_ref = spare_need_id
                    revisions[f"spare_need:{spare_need_id}"] = need_revision
                    audits.append(
                        AuditEventInput(
                            audit_event_id=new_uuid4(),
                            action_type="inventory.spare_need.changed",
                            action_version=1,
                            actor_kind=actor_kind,
                            actor_id=actor_id,
                            target_type="spare_need",
                            target_id=spare_need_id,
                            command_id=command_id,
                            payload_schema="SpareNeedAuditV1",
                            payload_version=1,
                            payload={
                                "spare_need_id": spare_need_id,
                                "service_request_id": service_request_id,
                                "event_kind": event_kind,
                                "planned_quantity": planned_quantity,
                                "contributor_id": contributor_id,
                                "resulting_revision": need_revision,
                                "reason_category": None,
                            },
                            resulting_event_refs=(
                                AuditResultRef("spare_need", spare_need_id),
                                AuditResultRef("spare_need_contributor", contributor_id),
                            ),
                        )
                    )

                identity_refs = [AuditResultRef("device_part_unit", device_part_unit_id)]
                if need_ref is not None:
                    identity_refs.append(AuditResultRef("spare_need", need_ref))
                audits.insert(
                    0,
                    AuditEventInput(
                        audit_event_id=new_uuid4(),
                        action_type="inventory.device_part.registered",
                        action_version=1,
                        actor_kind=actor_kind,
                        actor_id=actor_id,
                        target_type="device_part_unit",
                        target_id=device_part_unit_id,
                        command_id=command_id,
                        payload_schema="InventoryIdentityAuditV1",
                        payload_version=1,
                        payload={
                            "entity_type": "device_part_unit",
                            "entity_id": device_part_unit_id,
                            "tracking_id": None,
                            "origin": creation_origin,
                            "resulting_revision": unit_revision,
                            "bom_fingerprint": self._fingerprint(bom_key),
                            "serial_fingerprint": self._fingerprint(serial_key),
                        },
                        resulting_event_refs=tuple(identity_refs),
                    ),
                )

                apply.refs = refs
                apply.revisions = revisions
                return tuple(audits)

            apply.refs = [("device_part_unit", device_part_unit_id)]
            apply.revisions = {f"device_part_unit:{device_part_unit_id}": 1}
            return PreparedMutation(
                no_change=False,
                result_type="device_part_unit",
                result_id=device_part_unit_id,
                apply=apply,
                response_schema="InventoryMutationResultV1",
                response_factory=lambda _inner: self._response(apply.refs, apply.revisions),
            )

        return inventory_mutation_result_from_execution(
            self._boundary.execute(envelope, prepare)
        )

    def set_spare_need_planned_quantity(
        self,
        *,
        command_id: str,
        spare_need_id: str,
        base_revision: int,
        planned_quantity: int,
        reason_code: str,
        actor_kind: str = "local_user",
        actor_id: str | None = None,
    ) -> InventoryMutationResult:
        require_uuid4(spare_need_id)
        if type(base_revision) is not int or base_revision <= 0:
            raise ValidationError("base_revision must be positive")
        quantity = validate_planned_quantity(planned_quantity)
        reason = validate_reason_code(reason_code)
        envelope = CommandEnvelope(
            command_id=command_id,
            command_type="SetSpareNeedPlannedQuantity",
            target_type="spare_need",
            target_id=spare_need_id,
            semantic_payload={
                "planned_quantity": quantity,
                "reason_code": reason,
            },
            base_revisions={"spare_need": base_revision},
        )

        def prepare(uow: UnitOfWork) -> PreparedMutation:
            row = uow.connection.execute(
                "SELECT n.service_request_id,p.planned_quantity,p.revision "
                "FROM spare_needs n JOIN spare_need_current_projection p "
                "ON p.spare_need_id=n.spare_need_id WHERE n.spare_need_id=?",
                (spare_need_id,),
            ).fetchone()
            if row is None or int(row[2]) != base_revision:
                raise SomaError("INV_STALE", "Spare Need revision changed")
            service_request_id = str(row[0])
            if int(row[1]) == quantity:
                return PreparedMutation(
                    no_change=True,
                    result_type=None,
                    result_id=None,
                    response_schema="InventoryMutationResultV1",
                    response=self._response([], {}, outcome="NO_CHANGE"),
                )

            def apply(inner: UnitOfWork):
                event_id, revision = self._repository.change_planned_quantity(
                    inner.connection,
                    spare_need_id=spare_need_id,
                    base_revision=base_revision,
                    planned_quantity=quantity,
                    reason_code=reason,
                    command_id=command_id,
                )
                apply.event_id = event_id
                apply.revision = revision
                return AuditEventInput(
                    audit_event_id=new_uuid4(),
                    action_type="inventory.spare_need.changed",
                    action_version=1,
                    actor_kind=actor_kind,
                    actor_id=actor_id,
                    target_type="spare_need",
                    target_id=spare_need_id,
                    command_id=command_id,
                    reason_category=reason,
                    payload_schema="SpareNeedAuditV1",
                    payload_version=1,
                    payload={
                        "spare_need_id": spare_need_id,
                        "service_request_id": service_request_id,
                        "event_kind": "PLANNED_QUANTITY_CHANGED",
                        "planned_quantity": quantity,
                        "contributor_id": None,
                        "resulting_revision": revision,
                        "reason_category": reason,
                    },
                    resulting_event_refs=(
                        AuditResultRef("spare_need", spare_need_id),
                        AuditResultRef("spare_need_event", event_id),
                    ),
                )

            apply.event_id = ""
            apply.revision = base_revision + 1
            return PreparedMutation(
                no_change=False,
                result_type="spare_need",
                result_id=spare_need_id,
                apply=apply,
                response_schema="InventoryMutationResultV1",
                response_factory=lambda _inner: self._response(
                    [
                        ("spare_need", spare_need_id),
                        ("spare_need_event", apply.event_id),
                    ],
                    {f"spare_need:{spare_need_id}": apply.revision},
                ),
            )

        return inventory_mutation_result_from_execution(
            self._boundary.execute(envelope, prepare)
        )

    def change_spare_need_lifecycle(
        self,
        *,
        command_id: str,
        spare_need_id: str,
        base_revision: int,
        action: str,
        reason_code: str,
        actor_kind: str = "local_user",
        actor_id: str | None = None,
    ) -> InventoryMutationResult:
        require_uuid4(spare_need_id)
        if type(base_revision) is not int or base_revision <= 0:
            raise ValidationError("base_revision must be positive")
        if action not in _LIFECYCLE_ACTIONS:
            raise ValidationError("Need lifecycle action is invalid")
        reason = validate_reason_code(reason_code)
        target_state = {
            "resolve": "resolved",
            "cancel": "cancelled",
            "reactivate": "active",
            "history_remove": "removed",
        }[action]
        envelope = CommandEnvelope(
            command_id=command_id,
            command_type="ChangeSpareNeedLifecycle",
            target_type="spare_need",
            target_id=spare_need_id,
            semantic_payload={"action": action, "reason_code": reason},
            base_revisions={"spare_need": base_revision},
        )

        def prepare(uow: UnitOfWork) -> PreparedMutation:
            row = uow.connection.execute(
                "SELECT n.service_request_id,p.lifecycle_state,p.revision "
                "FROM spare_needs n JOIN spare_need_current_projection p "
                "ON p.spare_need_id=n.spare_need_id WHERE n.spare_need_id=?",
                (spare_need_id,),
            ).fetchone()
            if row is None or int(row[2]) != base_revision:
                raise SomaError("INV_STALE", "Spare Need revision changed")
            service_request_id = str(row[0])
            if str(row[1]) == target_state:
                return PreparedMutation(
                    no_change=True,
                    result_type=None,
                    result_id=None,
                    response_schema="InventoryMutationResultV1",
                    response=self._response([], {}, outcome="NO_CHANGE"),
                )

            def apply(inner: UnitOfWork):
                event_id, revision, resulting_state = self._repository.change_lifecycle(
                    inner.connection,
                    spare_need_id=spare_need_id,
                    base_revision=base_revision,
                    action=action,
                    reason_code=reason,
                    command_id=command_id,
                )
                apply.event_id = event_id
                apply.revision = revision
                apply.state = resulting_state
                return AuditEventInput(
                    audit_event_id=new_uuid4(),
                    action_type="inventory.spare_need.changed",
                    action_version=1,
                    actor_kind=actor_kind,
                    actor_id=actor_id,
                    target_type="spare_need",
                    target_id=spare_need_id,
                    command_id=command_id,
                    reason_category=reason,
                    payload_schema="SpareNeedAuditV1",
                    payload_version=1,
                    payload={
                        "spare_need_id": spare_need_id,
                        "service_request_id": service_request_id,
                        "event_kind": {
                            "resolve": "RESOLVE",
                            "cancel": "CANCEL",
                            "reactivate": "REACTIVATE",
                            "history_remove": "HISTORY_REMOVE",
                        }[action],
                        "planned_quantity": None,
                        "contributor_id": None,
                        "resulting_revision": revision,
                        "reason_category": reason,
                    },
                    resulting_event_refs=(
                        AuditResultRef("spare_need", spare_need_id),
                        AuditResultRef("spare_need_event", event_id),
                    ),
                )

            apply.event_id = ""
            apply.revision = base_revision + 1
            apply.state = target_state
            return PreparedMutation(
                no_change=False,
                result_type="spare_need",
                result_id=spare_need_id,
                apply=apply,
                response_schema="InventoryMutationResultV1",
                response_factory=lambda _inner: self._response(
                    [
                        ("spare_need", spare_need_id),
                        ("spare_need_event", apply.event_id),
                    ],
                    {f"spare_need:{spare_need_id}": apply.revision},
                ),
            )

        return inventory_mutation_result_from_execution(
            self._boundary.execute(envelope, prepare)
        )

    def register_spare_part_unit(
        self,
        *,
        command_id: str,
        origin: str,
        bom_code: str,
        manufacturer_serial: str | None = None,
        condition_token: str | None = None,
        location_kind: str | None = None,
        location_ref_id: str | None = None,
        custody_text: str | None = None,
        origin_rma_id: str | None = None,
        effective_at_utc: int | None = None,
        actor_kind: str = "local_user",
        actor_id: str | None = None,
    ) -> InventoryMutationResult:
        creation_origin = validate_spare_part_origin(origin)
        stored_bom, bom_key, stored_serial, serial_key = normalize_spare_part_identity(
            bom_code,
            manufacturer_serial,
        )
        condition = validate_spare_condition(condition_token)
        disposition = initial_disposition_for_condition(condition)
        location_type = normalize_location_kind(location_kind)
        location_ref = normalize_location_ref(location_ref_id)
        custody = normalize_custody_text(custody_text)
        effective = validate_unit_effective_at_utc(effective_at_utc)
        provenance = None if origin_rma_id is None else require_uuid4(origin_rma_id)

        envelope = CommandEnvelope(
            command_id=command_id,
            command_type="RegisterSparePartUnit",
            target_type="spare_part_unit",
            target_id=None,
            semantic_payload={
                "origin": creation_origin,
                "bom_code": stored_bom,
                "bom_key": bom_key,
                "manufacturer_serial": stored_serial,
                "serial_key": serial_key,
                "condition_token": condition,
                "location_kind": location_type,
                "location_ref_id": location_ref,
                "custody_text": custody,
                "origin_rma_id": provenance,
                "effective_at_utc": effective,
            },
        )

        def prepare(uow: UnitOfWork) -> PreparedMutation:
            self._units.require_optional_rma_provenance(
                uow.connection,
                origin_rma_id=provenance,
                creation_origin=creation_origin,
            )
            spare_part_unit_id = new_uuid4()

            def apply(inner: UnitOfWork):
                self._units.require_optional_rma_provenance(
                    inner.connection,
                    origin_rma_id=provenance,
                    creation_origin=creation_origin,
                )
                sequence, tracking_id = self._units.allocate_local_tracking_sequence(
                    inner.connection,
                    command_id,
                )
                event_id, revision = self._units.insert_spare_part_unit(
                    inner.connection,
                    spare_part_unit_id=spare_part_unit_id,
                    local_tracking_sequence=sequence,
                    local_tracking_id=tracking_id,
                    bom_code=stored_bom,
                    bom_key=bom_key,
                    manufacturer_serial=stored_serial,
                    serial_key=serial_key,
                    creation_origin=creation_origin,
                    origin_rma_id=provenance,
                    parent_spare_part_unit_id=None,
                    condition_token=condition,
                    disposition_token=disposition,
                    location_kind=location_type,
                    location_ref_id=location_ref,
                    custody_text=custody,
                    effective_at_utc=effective,
                    command_id=command_id,
                )
                apply.event_id = event_id
                apply.tracking_id = tracking_id
                apply.revision = revision
                return AuditEventInput(
                    audit_event_id=new_uuid4(),
                    action_type="inventory.spare_unit.registered_or_reserved",
                    action_version=1,
                    actor_kind=actor_kind,
                    actor_id=actor_id,
                    target_type="spare_part_unit",
                    target_id=spare_part_unit_id,
                    command_id=command_id,
                    payload_schema="SpareUnitAuditV1",
                    payload_version=1,
                    payload={
                        "spare_part_unit_id": spare_part_unit_id,
                        "event_kind": "REGISTER",
                        "task_id": None,
                        "allocation_id": None,
                        "spare_need_id": None,
                        "resulting_revision": revision,
                    },
                    resulting_event_refs=(
                        AuditResultRef("spare_part_unit", spare_part_unit_id),
                    ),
                )

            apply.event_id = ""
            apply.tracking_id = ""
            apply.revision = 1
            return PreparedMutation(
                no_change=False,
                result_type="spare_part_unit",
                result_id=spare_part_unit_id,
                apply=apply,
                response_schema="InventoryMutationResultV1",
                response_factory=lambda _inner: self._response(
                    [
                        ("spare_part_unit", spare_part_unit_id),
                        ("spare_part_unit_event", apply.event_id),
                    ],
                    {f"spare_part_unit:{spare_part_unit_id}": apply.revision},
                ),
            )

        return inventory_mutation_result_from_execution(
            self._boundary.execute(envelope, prepare)
        )

    def reserve_spare_part_unit_for_task(
        self,
        *,
        command_id: str,
        task_id: str,
        spare_part_unit_id: str,
        unit_revision: int,
        task_revision: int,
        spare_need_id: str | None = None,
        effective_at_utc: int | None = None,
        actor_kind: str = "local_user",
        actor_id: str | None = None,
    ) -> InventoryMutationResult:
        require_uuid4(task_id)
        require_uuid4(spare_part_unit_id)
        need_id = None if spare_need_id is None else require_uuid4(spare_need_id)
        if type(unit_revision) is not int or unit_revision <= 0:
            raise ValidationError("unit_revision must be positive")
        if type(task_revision) is not int or task_revision <= 0:
            raise ValidationError("task_revision must be positive")
        effective = validate_unit_effective_at_utc(effective_at_utc)

        envelope = CommandEnvelope(
            command_id=command_id,
            command_type="ReserveSparePartUnitForTask",
            target_type="spare_part_unit",
            target_id=spare_part_unit_id,
            semantic_payload={
                "task_id": task_id,
                "spare_part_unit_id": spare_part_unit_id,
                "spare_need_id": need_id,
                "effective_at_utc": effective,
            },
            base_revisions={
                "spare_part_unit": unit_revision,
                "task": task_revision,
            },
        )

        def prepare(uow: UnitOfWork) -> PreparedMutation:
            unit = self._units.current_unit(uow.connection, spare_part_unit_id)
            if unit is None or int(unit[14]) != unit_revision:
                raise SomaError("INV_STALE", "Spare Part Unit revision changed")
            self._units.require_task_revision(uow.connection, task_id, task_revision)
            if uow.connection.execute(
                "SELECT 1 FROM task_unit_allocation_current WHERE spare_part_unit_id=?",
                (spare_part_unit_id,),
            ).fetchone() is not None:
                raise SomaError("UNIT_ALREADY_RESERVED", "Spare Part Unit is already reserved")
            blockers = self._units.stock_blockers(uow.connection, spare_part_unit_id)
            if blockers:
                raise SomaError(
                    "STOCK_NOT_ELIGIBLE",
                    "Spare Part Unit is not Stock eligible: " + ",".join(blockers),
                )
            if need_id is not None:
                need = self._units.require_active_need(
                    uow.connection,
                    spare_need_id=need_id,
                )
                if str(need[1]) != str(unit[3]):
                    raise SomaError(
                        "STOCK_NOT_ELIGIBLE",
                        "Spare Part Unit BOM does not match selected Spare Need",
                    )

            allocation_id = new_uuid4()

            def apply(inner: UnitOfWork):
                event_id, allocation_revision, resulting_unit_revision = (
                    self._units.reserve_for_task(
                        inner.connection,
                        allocation_id=allocation_id,
                        task_id=task_id,
                        spare_part_unit_id=spare_part_unit_id,
                        spare_need_id=need_id,
                        expected_unit_revision=unit_revision,
                        expected_task_revision=task_revision,
                        command_id=command_id,
                        effective_at_utc=effective,
                    )
                )
                current = self._units.current_unit(inner.connection, spare_part_unit_id)
                if current is None:
                    raise IntegrityFailure("reserved Spare Part Unit disappeared")
                apply.event_id = event_id
                apply.allocation_revision = allocation_revision
                apply.unit_revision = resulting_unit_revision
                return AuditEventInput(
                    audit_event_id=new_uuid4(),
                    action_type="inventory.spare_unit.registered_or_reserved",
                    action_version=1,
                    actor_kind=actor_kind,
                    actor_id=actor_id,
                    target_type="spare_part_unit",
                    target_id=spare_part_unit_id,
                    command_id=command_id,
                    payload_schema="SpareUnitAuditV1",
                    payload_version=1,
                    payload={
                        "spare_part_unit_id": spare_part_unit_id,
                        "event_kind": "RESERVE",
                        "task_id": task_id,
                        "allocation_id": allocation_id,
                        "spare_need_id": need_id,
                        "resulting_revision": resulting_unit_revision,
                    },
                    resulting_event_refs=(
                        AuditResultRef("spare_part_unit", spare_part_unit_id),
                        AuditResultRef("task_unit_allocation", allocation_id),
                    ),
                )

            apply.event_id = ""
            apply.allocation_revision = 1
            apply.unit_revision = unit_revision + 1
            return PreparedMutation(
                no_change=False,
                result_type="task_unit_allocation",
                result_id=allocation_id,
                apply=apply,
                response_schema="InventoryMutationResultV1",
                response_factory=lambda _inner: self._response(
                    [
                        ("spare_part_unit", spare_part_unit_id),
                        ("task_unit_allocation", allocation_id),
                        ("task_unit_allocation_event", apply.event_id),
                    ],
                    {
                        f"spare_part_unit:{spare_part_unit_id}": apply.unit_revision,
                        f"task_unit_allocation:{allocation_id}": apply.allocation_revision,
                    },
                ),
            )

        return inventory_mutation_result_from_execution(
            self._boundary.execute(envelope, prepare)
        )

    def release_spare_part_unit_reservation(
        self,
        *,
        command_id: str,
        allocation_id: str,
        base_revision: int,
        reason_code: str,
        actor_kind: str = "local_user",
        actor_id: str | None = None,
    ) -> InventoryMutationResult:
        require_uuid4(allocation_id)
        if type(base_revision) is not int or base_revision <= 0:
            raise ValidationError("base_revision must be positive")
        reason = validate_reason_code(reason_code)
        envelope = CommandEnvelope(
            command_id=command_id,
            command_type="ReleaseSparePartUnitReservation",
            target_type="task_unit_allocation",
            target_id=allocation_id,
            semantic_payload={"reason_code": reason},
            base_revisions={"task_unit_allocation": base_revision},
        )

        def prepare(uow: UnitOfWork) -> PreparedMutation:
            current = uow.connection.execute(
                "SELECT task_id,spare_part_unit_id,spare_need_id,revision "
                "FROM task_unit_allocation_current WHERE allocation_id=?",
                (allocation_id,),
            ).fetchone()
            if current is None:
                latest = self._units.latest_allocation_event(uow.connection, allocation_id)
                if latest is not None and str(latest[0]) == "release":
                    return PreparedMutation(
                        no_change=True,
                        result_type=None,
                        result_id=None,
                        response_schema="InventoryMutationResultV1",
                        response=self._response([], {}, outcome="NO_CHANGE"),
                    )
                raise SomaError(
                    "CORRECTION_TARGET_INVALID",
                    "Task reservation is not active",
                )
            if int(current[3]) != base_revision:
                raise SomaError("INV_STALE", "Task reservation revision changed")
            unit_id = str(current[1])
            unit = self._units.current_unit(uow.connection, unit_id)
            if unit is None:
                raise IntegrityFailure("Task reservation points to missing Spare Part Unit")

            def apply(inner: UnitOfWork):
                event_id, released_unit_id, resulting_unit_revision = (
                    self._units.release_reservation(
                        inner.connection,
                        allocation_id=allocation_id,
                        expected_allocation_revision=base_revision,
                        reason_code=reason,
                        command_id=command_id,
                    )
                )
                after = self._units.current_unit(inner.connection, released_unit_id)
                if after is None:
                    raise IntegrityFailure("released Spare Part Unit disappeared")
                apply.event_id = event_id
                apply.unit_id = released_unit_id
                apply.unit_revision = resulting_unit_revision
                return AuditEventInput(
                    audit_event_id=new_uuid4(),
                    action_type="inventory.spare_unit.registered_or_reserved",
                    action_version=1,
                    actor_kind=actor_kind,
                    actor_id=actor_id,
                    target_type="spare_part_unit",
                    target_id=released_unit_id,
                    command_id=command_id,
                    reason_category=reason,
                    payload_schema="SpareUnitAuditV1",
                    payload_version=1,
                    payload={
                        "spare_part_unit_id": released_unit_id,
                        "event_kind": "RELEASE",
                        "task_id": str(current[0]),
                        "allocation_id": allocation_id,
                        "spare_need_id": None if current[2] is None else str(current[2]),
                        "resulting_revision": resulting_unit_revision,
                    },
                    resulting_event_refs=(
                        AuditResultRef("spare_part_unit", released_unit_id),
                        AuditResultRef("task_unit_allocation", allocation_id),
                    ),
                )

            apply.event_id = ""
            apply.unit_id = unit_id
            apply.unit_revision = int(unit[14]) + 1
            return PreparedMutation(
                no_change=False,
                result_type="task_unit_allocation",
                result_id=allocation_id,
                apply=apply,
                response_schema="InventoryMutationResultV1",
                response_factory=lambda _inner: self._response(
                    [
                        ("task_unit_allocation", allocation_id),
                        ("spare_part_unit", apply.unit_id),
                        ("task_unit_allocation_event", apply.event_id),
                    ],
                    {f"spare_part_unit:{apply.unit_id}": apply.unit_revision},
                ),
            )

        return inventory_mutation_result_from_execution(
            self._boundary.execute(envelope, prepare)
        )

    def record_local_need_fulfillment_selection(
        self,
        *,
        command_id: str,
        spare_need_id: str,
        spare_part_unit_id: str,
        need_revision: int,
        unit_revision: int,
        task_id: str | None = None,
        task_revision: int | None = None,
        actor_kind: str = "local_user",
        actor_id: str | None = None,
    ) -> InventoryMutationResult:
        require_uuid4(spare_need_id)
        require_uuid4(spare_part_unit_id)
        task = None if task_id is None else require_uuid4(task_id)
        if type(need_revision) is not int or need_revision <= 0:
            raise ValidationError("need_revision must be positive")
        if type(unit_revision) is not int or unit_revision <= 0:
            raise ValidationError("unit_revision must be positive")
        if task is None:
            if task_revision is not None:
                raise ValidationError("task_revision requires task_id")
        elif type(task_revision) is not int or task_revision <= 0:
            raise ValidationError("task_revision must be positive when task_id is supplied")

        envelope = CommandEnvelope(
            command_id=command_id,
            command_type="RecordLocalNeedFulfillmentSelection",
            target_type="spare_need",
            target_id=spare_need_id,
            semantic_payload={
                "spare_part_unit_id": spare_part_unit_id,
                "task_id": task,
            },
            base_revisions={
                "spare_need": need_revision,
                "spare_part_unit": unit_revision,
                **({} if task is None else {"task": int(task_revision)}),
            },
        )

        def prepare(uow: UnitOfWork) -> PreparedMutation:
            need = self._units.require_active_need(
                uow.connection,
                spare_need_id=spare_need_id,
                expected_revision=need_revision,
            )
            unit = self._units.current_unit(uow.connection, spare_part_unit_id)
            if unit is None or int(unit[14]) != unit_revision:
                raise SomaError("INV_STALE", "Spare Part Unit revision changed")
            if str(need[1]) != str(unit[3]):
                raise SomaError(
                    "STOCK_NOT_ELIGIBLE",
                    "Spare Part Unit BOM does not match selected Spare Need",
                )
            blockers = self._units.stock_blockers(uow.connection, spare_part_unit_id)
            if blockers:
                raise SomaError(
                    "STOCK_NOT_ELIGIBLE",
                    "Spare Part Unit is not Stock eligible: " + ",".join(blockers),
                )
            if task is not None:
                assert task_revision is not None
                self._units.require_task_revision(
                    uow.connection,
                    task,
                    task_revision,
                )
            allocation_id = None if task is None else new_uuid4()

            def apply(inner: UnitOfWork):
                fulfillment_event_id = self._units.record_local_fulfillment(
                    inner.connection,
                    spare_need_id=spare_need_id,
                    spare_part_unit_id=spare_part_unit_id,
                    task_id=task,
                    reason_code=None,
                    command_id=command_id,
                )
                allocation_event_id: str | None = None
                allocation_revision: int | None = None
                resulting_unit_revision = unit_revision
                if task is not None and allocation_id is not None:
                    assert task_revision is not None
                    (
                        allocation_event_id,
                        allocation_revision,
                        resulting_unit_revision,
                    ) = self._units.reserve_for_task(
                        inner.connection,
                        allocation_id=allocation_id,
                        task_id=task,
                        spare_part_unit_id=spare_part_unit_id,
                        spare_need_id=spare_need_id,
                        expected_unit_revision=unit_revision,
                        expected_task_revision=task_revision,
                        command_id=command_id,
                    )
                after = self._units.current_unit(inner.connection, spare_part_unit_id)
                if after is None:
                    raise IntegrityFailure("selected Spare Part Unit disappeared")
                apply.fulfillment_event_id = fulfillment_event_id
                apply.allocation_event_id = allocation_event_id
                apply.allocation_revision = allocation_revision
                apply.unit_revision = resulting_unit_revision

                need_audit = AuditEventInput(
                    audit_event_id=new_uuid4(),
                    action_type="inventory.spare_need.changed",
                    action_version=1,
                    actor_kind=actor_kind,
                    actor_id=actor_id,
                    target_type="spare_need",
                    target_id=spare_need_id,
                    command_id=command_id,
                    payload_schema="SpareNeedAuditV1",
                    payload_version=1,
                    payload={
                        "spare_need_id": spare_need_id,
                        "service_request_id": str(need[0]),
                        "event_kind": "LOCAL_SELECTION",
                        "planned_quantity": None,
                        "contributor_id": None,
                        "resulting_revision": need_revision,
                        "reason_category": None,
                    },
                    resulting_event_refs=(
                        AuditResultRef("spare_need", spare_need_id),
                        AuditResultRef(
                            "local_need_fulfillment",
                            fulfillment_event_id,
                        ),
                    ),
                )
                unit_refs = [
                    AuditResultRef("spare_part_unit", spare_part_unit_id),
                ]
                if allocation_id is not None:
                    unit_refs.append(
                        AuditResultRef("task_unit_allocation", allocation_id)
                    )
                unit_audit = AuditEventInput(
                    audit_event_id=new_uuid4(),
                    action_type="inventory.spare_unit.registered_or_reserved",
                    action_version=1,
                    actor_kind=actor_kind,
                    actor_id=actor_id,
                    target_type="spare_part_unit",
                    target_id=spare_part_unit_id,
                    command_id=command_id,
                    payload_schema="SpareUnitAuditV1",
                    payload_version=1,
                    payload={
                        "spare_part_unit_id": spare_part_unit_id,
                        "event_kind": "SELECT" if task is None else "RESERVE",
                        "task_id": task,
                        "allocation_id": allocation_id,
                        "spare_need_id": spare_need_id,
                        "resulting_revision": resulting_unit_revision,
                    },
                    resulting_event_refs=tuple(unit_refs),
                )
                return (need_audit, unit_audit)

            apply.fulfillment_event_id = ""
            apply.allocation_event_id = None
            apply.allocation_revision = None
            apply.unit_revision = unit_revision if task is None else unit_revision + 1
            return PreparedMutation(
                no_change=False,
                result_type="spare_need",
                result_id=spare_need_id,
                apply=apply,
                response_schema="InventoryMutationResultV1",
                response_factory=lambda _inner: self._response(
                    [
                        ("spare_need", spare_need_id),
                        ("spare_part_unit", spare_part_unit_id),
                        ("local_need_fulfillment", apply.fulfillment_event_id),
                    ]
                    + (
                        []
                        if allocation_id is None
                        else [("task_unit_allocation", allocation_id)]
                    )
                    + (
                        []
                        if apply.allocation_event_id is None
                        else [
                            (
                                "task_unit_allocation_event",
                                apply.allocation_event_id,
                            )
                        ]
                    ),
                    {
                        f"spare_need:{spare_need_id}": need_revision,
                        f"spare_part_unit:{spare_part_unit_id}": apply.unit_revision,
                        **(
                            {}
                            if allocation_id is None or apply.allocation_revision is None
                            else {
                                f"task_unit_allocation:{allocation_id}": apply.allocation_revision
                            }
                        ),
                    },
                ),
            )

        return inventory_mutation_result_from_execution(
            self._boundary.execute(envelope, prepare)
        )

