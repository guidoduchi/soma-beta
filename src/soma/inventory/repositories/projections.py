from __future__ import annotations

from typing import Any

from soma.foundation.errors import IntegrityFailure, SomaError
from soma.foundation.identifiers import new_uuid4, utc_epoch_seconds
from soma.foundation.strict_json import sha256_canonical_json

from ..domain.consequences import PhysicalConsequenceIntent
from .rmas import InventoryRmasRepository
from .units import InventoryUnitsRepository


class InventoryPhysicalConsequenceRepository:
    @staticmethod
    def current(connection: Any, physical_consequence_id: str):
        return connection.execute(
            "SELECT c.physical_consequence_id,c.task_id,c.task_review_fingerprint,"
            "c.target_device_part_unit_id,c.rma_id,p.physical_disposition,"
            "p.installed_spare_part_unit_id,p.removed_device_part_unit_id,"
            "p.inbound_spare_part_unit_id,p.parent_dismantled_unit_id,"
            "p.revision,p.input_fingerprint,p.last_event_id "
            "FROM inventory_physical_consequences c "
            "JOIN physical_consequence_current p "
            "ON p.physical_consequence_id=c.physical_consequence_id "
            "WHERE c.physical_consequence_id=?",
            (physical_consequence_id,),
        ).fetchone()

    @staticmethod
    def _require_device_part(connection: Any, device_part_unit_id: str) -> None:
        if connection.execute(
            "SELECT 1 FROM device_part_units WHERE device_part_unit_id=?",
            (device_part_unit_id,),
        ).fetchone() is None:
            raise SomaError("RETURN_SELECTION_INVALID", "Device Part Unit no longer exists")

    @staticmethod
    def _require_spare_part(connection: Any, spare_part_unit_id: str) -> None:
        if connection.execute(
            "SELECT 1 FROM spare_part_units WHERE spare_part_unit_id=?",
            (spare_part_unit_id,),
        ).fetchone() is None:
            raise SomaError("RETURN_SELECTION_INVALID", "Spare Part Unit no longer exists")

    @classmethod
    def require_context(
        cls,
        connection: Any,
        *,
        task_id: str,
        rma_id: str | None,
        target_device_part_unit_id: str | None,
        intent: PhysicalConsequenceIntent,
    ) -> None:
        if connection.execute(
            "SELECT 1 FROM tasks WHERE task_id=?",
            (task_id,),
        ).fetchone() is None:
            raise SomaError("TASK_REVIEW_STALE", "Task no longer exists")

        device_ids = {
            value
            for value in (
                target_device_part_unit_id,
                intent.removed_device_part_unit_id,
                intent.explicit_return_device_part_unit_id,
            )
            if value is not None
        }
        spare_ids = {
            value
            for value in (
                intent.installed_spare_part_unit_id,
                intent.inbound_spare_part_unit_id,
                intent.parent_dismantled_unit_id,
                intent.explicit_return_spare_part_unit_id,
            )
            if value is not None
        }
        for identity in device_ids:
            cls._require_device_part(connection, identity)
        for identity in spare_ids:
            cls._require_spare_part(connection, identity)

        for unit_id in spare_ids:
            allocation = connection.execute(
                "SELECT task_id FROM task_unit_allocation_current WHERE spare_part_unit_id=?",
                (unit_id,),
            ).fetchone()
            if allocation is not None and str(allocation[0]) != task_id:
                raise SomaError(
                    "RETURN_SELECTION_INVALID",
                    "Spare Part Unit is actively reserved to a different Task",
                )

        if rma_id is None:
            return

        rma = InventoryRmasRepository.current_rma(connection, rma_id)
        if rma is None:
            raise SomaError("INV_STALE", "RMA no longer exists")
        assigned_target = None if rma[6] is None else str(rma[6])
        direct_inbound = None if rma[7] is None else str(rma[7])
        if target_device_part_unit_id is not None and assigned_target != target_device_part_unit_id:
            raise SomaError(
                "RETURN_SELECTION_INVALID",
                "Physical consequence target does not match current RMA assignment",
            )
        if intent.removed_device_part_unit_id is not None and assigned_target is not None:
            if intent.removed_device_part_unit_id != assigned_target:
                raise SomaError(
                    "RETURN_SELECTION_INVALID",
                    "Removed Device Part Unit does not match current RMA target",
                )

        if intent.physical_disposition in {"unused", "inbound_faulty", "incompatible"}:
            if direct_inbound is None or intent.inbound_spare_part_unit_id != direct_inbound:
                raise SomaError(
                    "RETURN_SELECTION_INVALID",
                    "Inbound return consequence must use the RMA direct inbound unit",
                )
        if intent.physical_disposition == "dismantled":
            if direct_inbound is None or intent.parent_dismantled_unit_id != direct_inbound:
                raise SomaError(
                    "RETURN_SELECTION_INVALID",
                    "Dismantled return consequence must retain the direct inbound parent assembly",
                )
        if intent.physical_disposition == "installed_used":
            if direct_inbound is not None and intent.installed_spare_part_unit_id is not None:
                installed = connection.execute(
                    "SELECT origin_rma_id,parent_spare_part_unit_id "
                    "FROM spare_part_units WHERE spare_part_unit_id=?",
                    (intent.installed_spare_part_unit_id,),
                ).fetchone()
                if installed is None:
                    raise SomaError("RETURN_SELECTION_INVALID", "Installed unit no longer exists")
                origin_rma = None if installed[0] is None else str(installed[0])
                parent = None if installed[1] is None else str(installed[1])
                if (
                    intent.installed_spare_part_unit_id != direct_inbound
                    and not (origin_rma == rma_id and parent == direct_inbound)
                ):
                    raise SomaError(
                        "RETURN_SELECTION_INVALID",
                        "Installed unit is not the RMA direct inbound unit or its extracted child",
                    )

    @staticmethod
    def consequence_fingerprint(
        *,
        physical_consequence_id: str,
        task_review_fingerprint: str,
        intent: PhysicalConsequenceIntent,
    ) -> str:
        return sha256_canonical_json(
            {
                "schema": "SOMA_INVENTORY_PHYSICAL_CONSEQUENCE_V1",
                "physical_consequence_id": physical_consequence_id,
                "task_review_fingerprint": task_review_fingerprint,
                "physical_disposition": intent.physical_disposition,
                "installed_spare_part_unit_id": intent.installed_spare_part_unit_id,
                "removed_device_part_unit_id": intent.removed_device_part_unit_id,
                "inbound_spare_part_unit_id": intent.inbound_spare_part_unit_id,
                "parent_dismantled_unit_id": intent.parent_dismantled_unit_id,
            }
        )

    @staticmethod
    def _append_spare_unit_event(
        connection: Any,
        *,
        spare_part_unit_id: str,
        event_kind: str,
        condition_token: str,
        disposition_token: str,
        effective_at_utc: int | None,
        command_id: str,
    ) -> tuple[str, int]:
        unit = InventoryUnitsRepository.current_unit(connection, spare_part_unit_id)
        if unit is None:
            raise SomaError("RETURN_SELECTION_INVALID", "Spare Part Unit no longer exists")
        event_id = new_uuid4()
        now = utc_epoch_seconds()
        connection.execute(
            "INSERT INTO spare_part_lifecycle_events("
            "unit_event_id,spare_part_unit_id,event_kind,condition_token,disposition_token,"
            "location_kind,location_ref_id,custody_text,effective_at_utc,target_event_id,"
            "reason_code,evidence_kind,evidence_id,recorded_at_utc,command_id"
            ") VALUES (?,?,?,?,?,?,?,?,?,NULL,NULL,NULL,NULL,?,?)",
            (
                event_id,
                spare_part_unit_id,
                event_kind,
                condition_token,
                disposition_token,
                unit[10],
                unit[11],
                unit[12],
                effective_at_utc,
                now,
                command_id,
            ),
        )
        revision = int(unit[14]) + 1
        fingerprint = InventoryUnitsRepository.projection_fingerprint(
            spare_part_unit_id=spare_part_unit_id,
            condition_token=condition_token,
            disposition_token=disposition_token,
            location_kind=None if unit[10] is None else str(unit[10]),
            location_ref_id=None if unit[11] is None else str(unit[11]),
            custody_text=None if unit[12] is None else str(unit[12]),
            active_task_allocation_id=None,
        )
        updated = connection.execute(
            "UPDATE spare_part_current_projection SET condition_token=?,disposition_token=?,"
            "active_task_allocation_id=NULL,revision=?,input_fingerprint=?,last_command_id=? "
            "WHERE spare_part_unit_id=? AND revision=?",
            (
                condition_token,
                disposition_token,
                revision,
                fingerprint,
                command_id,
                spare_part_unit_id,
                int(unit[14]),
            ),
        )
        if updated.rowcount != 1:
            raise SomaError("INV_STALE", "Spare Part Unit changed during physical consequence")
        return event_id, revision

    @staticmethod
    def _close_owned_allocation(
        connection: Any,
        *,
        task_id: str,
        spare_part_unit_id: str,
        effective_at_utc: int | None,
        command_id: str,
    ) -> str | None:
        row = connection.execute(
            "SELECT allocation_id,spare_need_id,revision,last_event_id "
            "FROM task_unit_allocation_current WHERE spare_part_unit_id=?",
            (spare_part_unit_id,),
        ).fetchone()
        if row is None:
            return None
        allocation_id = str(row[0])
        owner = connection.execute(
            "SELECT task_id FROM task_unit_allocation_current WHERE allocation_id=?",
            (allocation_id,),
        ).fetchone()
        if owner is None or str(owner[0]) != task_id:
            raise SomaError("RETURN_SELECTION_INVALID", "Task allocation ownership changed")
        event_id = new_uuid4()
        connection.execute(
            "INSERT INTO task_unit_allocation_events("
            "allocation_event_id,allocation_id,task_id,spare_part_unit_id,spare_need_id,"
            "event_kind,prior_task_id,reason_code,effective_at_utc,target_event_id,"
            "recorded_at_utc,command_id"
            ") VALUES (?,?,?,?,?,'release',NULL,'physical_consequence_accepted',?,?,?,?)",
            (
                event_id,
                allocation_id,
                task_id,
                spare_part_unit_id,
                None if row[1] is None else str(row[1]),
                effective_at_utc,
                str(row[3]),
                utc_epoch_seconds(),
                command_id,
            ),
        )
        deleted = connection.execute(
            "DELETE FROM task_unit_allocation_current WHERE allocation_id=? AND revision=?",
            (allocation_id, int(row[2])),
        )
        if deleted.rowcount != 1:
            raise SomaError("INV_STALE", "Task allocation changed during physical consequence")
        return event_id

    @staticmethod
    def _append_device_removed(
        connection: Any,
        *,
        device_part_unit_id: str,
        effective_at_utc: int | None,
        command_id: str,
    ) -> tuple[str, int]:
        row = connection.execute(
            "SELECT condition_token,revision,last_event_id FROM device_part_current_projection "
            "WHERE device_part_unit_id=?",
            (device_part_unit_id,),
        ).fetchone()
        if row is None:
            raise SomaError("RETURN_SELECTION_INVALID", "Device Part Unit current projection is missing")
        event_id = new_uuid4()
        now = utc_epoch_seconds()
        connection.execute(
            "INSERT INTO device_part_lifecycle_events("
            "device_part_event_id,device_part_unit_id,event_kind,condition_token,effective_at_utc,"
            "target_event_id,reason_code,evidence_kind,evidence_id,recorded_at_utc,command_id"
            ") VALUES (?,?,'removed','removed',?,NULL,NULL,NULL,NULL,?,?)",
            (event_id, device_part_unit_id, effective_at_utc, now, command_id),
        )
        revision = int(row[1]) + 1
        fingerprint = sha256_canonical_json(
            {
                "schema": "SOMA_DEVICE_PART_CURRENT_V1",
                "device_part_unit_id": device_part_unit_id,
                "condition_token": "removed",
                "last_event_id": event_id,
            }
        )
        updated = connection.execute(
            "UPDATE device_part_current_projection SET condition_token='removed',revision=?,"
            "input_fingerprint=?,last_event_id=?,last_command_id=? "
            "WHERE device_part_unit_id=? AND revision=?",
            (
                revision,
                fingerprint,
                event_id,
                command_id,
                device_part_unit_id,
                int(row[1]),
            ),
        )
        if updated.rowcount != 1:
            raise SomaError("INV_STALE", "Device Part Unit changed during physical consequence")
        return event_id, revision

    @classmethod
    def _set_return_obligation(
        cls,
        connection: Any,
        *,
        rma_id: str,
        physical_consequence_id: str,
        return_candidate: tuple[str, str] | None,
        effective_at_utc: int | None,
        command_id: str,
    ) -> tuple[str | None, int, int]:
        current = connection.execute(
            "SELECT obligation_state,device_part_unit_id,spare_part_unit_id,"
            "physical_consequence_id,revision,last_event_id "
            "FROM rma_return_obligation_current WHERE rma_id=?",
            (rma_id,),
        ).fetchone()
        if current is None:
            raise IntegrityFailure("RMA return obligation projection is missing")
        if str(current[0]) == "closed_accepted":
            raise SomaError("RETURN_SELECTION_INVALID", "RMA return obligation is already closed")

        rma = InventoryRmasRepository.current_rma(connection, rma_id)
        if rma is None:
            raise SomaError("INV_STALE", "RMA no longer exists")
        obligation_revision = int(current[4]) + 1
        lifecycle_revision = int(rma[12]) + 1

        if return_candidate is None:
            updated = connection.execute(
                "UPDATE rma_return_obligation_current SET obligation_state='not_established',"
                "device_part_unit_id=NULL,spare_part_unit_id=NULL,physical_consequence_id=?,"
                "revision=?,last_event_id=NULL,last_command_id=? WHERE rma_id=? AND revision=?",
                (
                    physical_consequence_id,
                    obligation_revision,
                    command_id,
                    rma_id,
                    int(current[4]),
                ),
            )
            if updated.rowcount != 1:
                raise SomaError("INV_STALE", "RMA return obligation changed")
            state = "physical_consequence_pending"
            return_device = None
            return_spare = None
            selection_event_id = None
        else:
            kind, unit_id = return_candidate
            if kind == "device_part_unit":
                cls._require_device_part(connection, unit_id)
                return_device, return_spare = unit_id, None
            elif kind == "spare_part_unit":
                cls._require_spare_part(connection, unit_id)
                return_device, return_spare = None, unit_id
            else:
                raise IntegrityFailure("return candidate type is invalid")
            selection_event_id = new_uuid4()
            connection.execute(
                "INSERT INTO rma_return_selection_events("
                "return_selection_event_id,rma_id,physical_consequence_id,event_kind,"
                "device_part_unit_id,spare_part_unit_id,reason_code,effective_at_utc,"
                "target_event_id,recorded_at_utc,command_id"
                ") VALUES (?,?,?,'select',?,?,NULL,?,NULL,?,?)",
                (
                    selection_event_id,
                    rma_id,
                    physical_consequence_id,
                    return_device,
                    return_spare,
                    effective_at_utc,
                    utc_epoch_seconds(),
                    command_id,
                ),
            )
            updated = connection.execute(
                "UPDATE rma_return_obligation_current SET obligation_state='open',"
                "device_part_unit_id=?,spare_part_unit_id=?,physical_consequence_id=?,"
                "revision=?,last_event_id=?,last_command_id=? WHERE rma_id=? AND revision=?",
                (
                    return_device,
                    return_spare,
                    physical_consequence_id,
                    obligation_revision,
                    selection_event_id,
                    command_id,
                    rma_id,
                    int(current[4]),
                ),
            )
            if updated.rowcount != 1:
                raise SomaError("INV_STALE", "RMA return obligation changed")
            state = "return_open"

        lifecycle_fingerprint = InventoryRmasRepository.rma_lifecycle_fingerprint(
            rma_id=rma_id,
            current_c10=str(rma[4]),
            state=state,
            target_device_part_unit_id=None if rma[6] is None else str(rma[6]),
            direct_inbound_spare_part_unit_id=None if rma[7] is None else str(rma[7]),
            return_device_part_unit_id=return_device,
            return_spare_part_unit_id=return_spare,
            return_obligation_open=return_candidate is not None,
            active_fault_tag_membership_id=None if rma[11] is None else str(rma[11]),
        )
        updated_lifecycle = connection.execute(
            "UPDATE rma_lifecycle_projection SET state=?,return_device_part_unit_id=?,"
            "return_spare_part_unit_id=?,return_obligation_open=?,revision=?,input_fingerprint=?,"
            "last_command_id=? WHERE rma_id=? AND revision=?",
            (
                state,
                return_device,
                return_spare,
                1 if return_candidate is not None else 0,
                lifecycle_revision,
                lifecycle_fingerprint,
                command_id,
                rma_id,
                int(rma[12]),
            ),
        )
        if updated_lifecycle.rowcount != 1:
            raise SomaError("INV_STALE", "RMA lifecycle changed during return selection")

        connection.execute(
            "DELETE FROM inventory_attention_projection "
            "WHERE target_kind='rma' AND target_id=? AND attention_kind='return_obligation_open'",
            (rma_id,),
        )
        if return_candidate is not None:
            attention_id = new_uuid4()
            attention_fp = sha256_canonical_json(
                {
                    "schema": "SOMA_INVENTORY_ATTENTION_V1",
                    "target_kind": "rma",
                    "target_id": rma_id,
                    "attention_kind": "return_obligation_open",
                    "physical_consequence_id": physical_consequence_id,
                    "return_kind": return_candidate[0],
                    "return_unit_id": return_candidate[1],
                }
            )
            connection.execute(
                "INSERT INTO inventory_attention_projection("
                "attention_id,target_kind,target_id,attention_kind,severity,input_fingerprint,last_command_id"
                ") VALUES (?,'rma',?,'return_obligation_open','action_required',?,?)",
                (attention_id, rma_id, attention_fp, command_id),
            )
        return selection_event_id, obligation_revision, lifecycle_revision

    @classmethod
    def insert_extracted_children(
        cls,
        connection: Any,
        *,
        parent_spare_part_unit_id: str,
        rma_id: str,
        children: tuple[dict[str, object], ...],
        effective_at_utc: int | None,
        command_id: str,
    ) -> tuple[dict[str, object], ...]:
        parent = connection.execute(
            "SELECT origin_rma_id FROM spare_part_units WHERE spare_part_unit_id=?",
            (parent_spare_part_unit_id,),
        ).fetchone()
        if parent is None or parent[0] is None or str(parent[0]) != rma_id:
            raise SomaError(
                "RETURN_SELECTION_INVALID",
                "Dismantled parent does not carry the expected RMA provenance",
            )
        direct = connection.execute(
            "SELECT spare_part_unit_id FROM rma_direct_inbound_units WHERE rma_id=?",
            (rma_id,),
        ).fetchone()
        if direct is None or str(direct[0]) != parent_spare_part_unit_id:
            raise SomaError(
                "RETURN_SELECTION_INVALID",
                "Dismantled parent is not the RMA direct inbound assembly",
            )

        created: list[dict[str, object]] = []
        for child in children:
            spare_part_unit_id = new_uuid4()
            sequence, tracking_id = InventoryUnitsRepository.allocate_local_tracking_sequence(
                connection,
                command_id,
            )
            event_id, revision = InventoryUnitsRepository.insert_spare_part_unit(
                connection,
                spare_part_unit_id=spare_part_unit_id,
                local_tracking_sequence=sequence,
                local_tracking_id=tracking_id,
                bom_code=str(child["bom_code"]),
                bom_key=str(child["bom_key"]),
                manufacturer_serial=(
                    None
                    if child["manufacturer_serial"] is None
                    else str(child["manufacturer_serial"])
                ),
                serial_key=(
                    None if child["serial_key"] is None else str(child["serial_key"])
                ),
                creation_origin="extracted",
                origin_rma_id=rma_id,
                parent_spare_part_unit_id=parent_spare_part_unit_id,
                condition_token=str(child["condition_token"]),
                disposition_token=str(child["disposition_token"]),
                location_kind=None,
                location_ref_id=None,
                custody_text=None,
                effective_at_utc=effective_at_utc,
                command_id=command_id,
            )
            created.append(
                {
                    "spare_part_unit_id": spare_part_unit_id,
                    "local_tracking_id": tracking_id,
                    "event_id": event_id,
                    "revision": revision,
                    "bom_key": str(child["bom_key"]),
                }
            )
        return tuple(created)

    @classmethod
    def accept(
        cls,
        connection: Any,
        *,
        physical_consequence_id: str,
        task_id: str,
        task_review_fingerprint: str,
        target_device_part_unit_id: str | None,
        rma_id: str | None,
        intent: PhysicalConsequenceIntent,
        extracted_children: tuple[dict[str, object], ...] = (),
        command_id: str,
    ) -> dict[str, object]:
        cls.require_context(
            connection,
            task_id=task_id,
            rma_id=rma_id,
            target_device_part_unit_id=target_device_part_unit_id,
            intent=intent,
        )
        now = utc_epoch_seconds()
        connection.execute(
            "INSERT INTO inventory_physical_consequences("
            "physical_consequence_id,task_id,task_review_fingerprint,target_device_part_unit_id,"
            "rma_id,created_at_utc,created_command_id"
            ") VALUES (?,?,?,?,?,?,?)",
            (
                physical_consequence_id,
                task_id,
                task_review_fingerprint,
                target_device_part_unit_id,
                rma_id,
                now,
                command_id,
            ),
        )
        consequence_event_id = new_uuid4()
        connection.execute(
            "INSERT INTO physical_consequence_events("
            "consequence_event_id,physical_consequence_id,event_kind,physical_disposition,"
            "installed_spare_part_unit_id,removed_device_part_unit_id,inbound_spare_part_unit_id,"
            "parent_dismantled_unit_id,effective_at_utc,target_event_id,reason_code,"
            "recorded_at_utc,command_id"
            ") VALUES (?,?,'accept',?,?,?,?,?,?,NULL,NULL,?,?)",
            (
                consequence_event_id,
                physical_consequence_id,
                intent.physical_disposition,
                intent.installed_spare_part_unit_id,
                intent.removed_device_part_unit_id,
                intent.inbound_spare_part_unit_id,
                intent.parent_dismantled_unit_id,
                intent.effective_at_utc,
                now,
                command_id,
            ),
        )
        consequence_fp = cls.consequence_fingerprint(
            physical_consequence_id=physical_consequence_id,
            task_review_fingerprint=task_review_fingerprint,
            intent=intent,
        )
        connection.execute(
            "INSERT INTO physical_consequence_current("
            "physical_consequence_id,task_review_fingerprint,physical_disposition,"
            "installed_spare_part_unit_id,removed_device_part_unit_id,inbound_spare_part_unit_id,"
            "parent_dismantled_unit_id,revision,input_fingerprint,last_event_id,last_command_id"
            ") VALUES (?,?,?,?,?,?,?,1,?,?,?)",
            (
                physical_consequence_id,
                task_review_fingerprint,
                intent.physical_disposition,
                intent.installed_spare_part_unit_id,
                intent.removed_device_part_unit_id,
                intent.inbound_spare_part_unit_id,
                intent.parent_dismantled_unit_id,
                consequence_fp,
                consequence_event_id,
                command_id,
            ),
        )

        refs: list[tuple[str, str]] = [
            ("inventory_physical_consequence", physical_consequence_id),
            ("physical_consequence_event", consequence_event_id),
        ]
        if intent.installed_spare_part_unit_id is not None:
            allocation_event = cls._close_owned_allocation(
                connection,
                task_id=task_id,
                spare_part_unit_id=intent.installed_spare_part_unit_id,
                effective_at_utc=intent.effective_at_utc,
                command_id=command_id,
            )
            unit_event, _unit_revision = cls._append_spare_unit_event(
                connection,
                spare_part_unit_id=intent.installed_spare_part_unit_id,
                event_kind="installed",
                condition_token="used",
                disposition_token="installed",
                effective_at_utc=intent.effective_at_utc,
                command_id=command_id,
            )
            refs.append(("spare_part_unit_event", unit_event))
            if allocation_event is not None:
                refs.append(("task_unit_allocation_event", allocation_event))

        if intent.removed_device_part_unit_id is not None:
            device_event, _device_revision = cls._append_device_removed(
                connection,
                device_part_unit_id=intent.removed_device_part_unit_id,
                effective_at_utc=intent.effective_at_utc,
                command_id=command_id,
            )
            refs.append(("device_part_unit_event", device_event))

        if intent.physical_disposition in {"inbound_faulty", "incompatible"}:
            assert intent.inbound_spare_part_unit_id is not None
            condition = "faulty" if intent.physical_disposition == "inbound_faulty" else "incompatible"
            unit_event, _unit_revision = cls._append_spare_unit_event(
                connection,
                spare_part_unit_id=intent.inbound_spare_part_unit_id,
                event_kind="condition_changed",
                condition_token=condition,
                disposition_token="quarantined",
                effective_at_utc=intent.effective_at_utc,
                command_id=command_id,
            )
            refs.append(("spare_part_unit_event", unit_event))

        if intent.physical_disposition == "dismantled":
            assert intent.parent_dismantled_unit_id is not None
            parent = InventoryUnitsRepository.current_unit(
                connection,
                intent.parent_dismantled_unit_id,
            )
            if parent is None:
                raise SomaError("RETURN_SELECTION_INVALID", "Dismantled parent no longer exists")
            parent_event, _parent_revision = cls._append_spare_unit_event(
                connection,
                spare_part_unit_id=intent.parent_dismantled_unit_id,
                event_kind="dismantled",
                condition_token=str(parent[8]),
                disposition_token="dismantled",
                effective_at_utc=intent.effective_at_utc,
                command_id=command_id,
            )
            refs.append(("spare_part_unit_event", parent_event))

        extracted: tuple[dict[str, object], ...] = ()
        if extracted_children:
            if intent.physical_disposition != "dismantled":
                raise IntegrityFailure("extracted children reached non-dismantled consequence")
            if rma_id is None or intent.parent_dismantled_unit_id is None:
                raise SomaError(
                    "RETURN_SELECTION_INVALID",
                    "extracted children require RMA-backed dismantled parent",
                )
            extracted = cls.insert_extracted_children(
                connection,
                parent_spare_part_unit_id=intent.parent_dismantled_unit_id,
                rma_id=rma_id,
                children=extracted_children,
                effective_at_utc=intent.effective_at_utc,
                command_id=command_id,
            )
            for child in extracted:
                refs.extend(
                    (
                        ("spare_part_unit", str(child["spare_part_unit_id"])),
                        ("spare_part_unit_event", str(child["event_id"])),
                    )
                )

        selection_event_id: str | None = None
        obligation_revision: int | None = None
        rma_revision: int | None = None
        if rma_id is not None:
            selection_event_id, obligation_revision, rma_revision = cls._set_return_obligation(
                connection,
                rma_id=rma_id,
                physical_consequence_id=physical_consequence_id,
                return_candidate=intent.return_candidate(),
                effective_at_utc=intent.effective_at_utc,
                command_id=command_id,
            )
            refs.append(("rma_return_obligation", rma_id))
            if selection_event_id is not None:
                refs.append(("rma_return_selection_event", selection_event_id))

        return {
            "physical_consequence_id": physical_consequence_id,
            "consequence_event_id": consequence_event_id,
            "return_selection_event_id": selection_event_id,
            "obligation_revision": obligation_revision,
            "rma_revision": rma_revision,
            "refs": tuple(refs),
            "consequence_revision": 1,
            "extracted_units": extracted,
        }


__all__ = ["InventoryPhysicalConsequenceRepository"]
