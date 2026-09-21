from __future__ import annotations

from soma.foundation.errors import IntegrityFailure, SomaError
from soma.foundation.identifiers import new_uuid4, utc_epoch_seconds
from soma.foundation.strict_json import sha256_canonical_json


class InventoryUnitsRepository:
    @staticmethod
    def allocate_local_tracking_sequence(connection, command_id: str) -> tuple[int, str]:
        row = connection.execute(
            "SELECT next_sequence,revision FROM inventory_tracking_allocators "
            "WHERE allocator_kind='local_spare_unit'"
        ).fetchone()
        if row is None:
            raise IntegrityFailure("Inventory local Spare Part allocator is missing")
        sequence = int(row[0])
        revision = int(row[1])
        if sequence >= 100_000_000:
            raise SomaError("INV_INVALID_ID", "Local Spare Part Unit sequence is exhausted")
        updated = connection.execute(
            "UPDATE inventory_tracking_allocators SET next_sequence=?,revision=?,last_command_id=? "
            "WHERE allocator_kind='local_spare_unit' AND next_sequence=? AND revision=?",
            (sequence + 1, revision + 1, command_id, sequence, revision),
        )
        if updated.rowcount != 1:
            raise SomaError("INV_STALE", "Local Spare Part Unit allocator changed")
        return sequence, f"LSU-{sequence:08d}"

    @staticmethod
    def require_registration_provenance(
        connection,
        *,
        origin_rma_id: str | None,
        creation_origin: str,
        parent_spare_part_unit_id: str | None,
    ) -> None:
        if creation_origin == "extracted":
            if origin_rma_id is None or parent_spare_part_unit_id is None:
                raise SomaError(
                    "INV_INVALID_ID",
                    "Extracted Spare Part Unit requires parent and RMA provenance",
                )
            parent = connection.execute(
                "SELECT origin_rma_id FROM spare_part_units WHERE spare_part_unit_id=?",
                (parent_spare_part_unit_id,),
            ).fetchone()
            if (
                parent is None
                or parent[0] is None
                or str(parent[0]) != origin_rma_id
            ):
                raise SomaError(
                    "INV_INVALID_ID",
                    "Extracted parent does not own the supplied RMA provenance",
                )
            direct = connection.execute(
                "SELECT spare_part_unit_id FROM rma_direct_inbound_units WHERE rma_id=?",
                (origin_rma_id,),
            ).fetchone()
            if direct is None or str(direct[0]) != parent_spare_part_unit_id:
                raise SomaError(
                    "INV_INVALID_ID",
                    "Extracted parent is not the RMA direct inbound unit",
                )
            return

        if parent_spare_part_unit_id is not None:
            raise SomaError(
                "INV_INVALID_ID",
                "Only extracted Spare Part Units may name a parent",
            )
        if origin_rma_id is None:
            return
        if creation_origin != "reviewed_reconciliation":
            raise SomaError(
                "INV_INVALID_ID",
                "RMA provenance is accepted here only through reviewed reconciliation",
            )
        if connection.execute(
            "SELECT 1 FROM rmas WHERE rma_id=?",
            (origin_rma_id,),
        ).fetchone() is None:
            raise SomaError("INV_STALE", "RMA provenance no longer exists")
        if connection.execute(
            "SELECT 1 FROM rma_direct_inbound_units WHERE rma_id=?",
            (origin_rma_id,),
        ).fetchone() is not None:
            raise SomaError(
                "STOCK_NOT_ELIGIBLE",
                "RMA already owns a direct inbound physical unit",
            )

    @classmethod
    def require_optional_rma_provenance(
        cls,
        connection,
        *,
        origin_rma_id: str | None,
        creation_origin: str,
    ) -> None:
        cls.require_registration_provenance(
            connection,
            origin_rma_id=origin_rma_id,
            creation_origin=creation_origin,
            parent_spare_part_unit_id=None,
        )

    @staticmethod
    def projection_fingerprint(
        *,
        spare_part_unit_id: str,
        condition_token: str,
        disposition_token: str,
        location_kind: str | None,
        location_ref_id: str | None,
        custody_text: str | None,
        active_task_allocation_id: str | None,
    ) -> str:
        return sha256_canonical_json(
            {
                "schema": "SOMA_SPARE_PART_CURRENT_V1",
                "spare_part_unit_id": spare_part_unit_id,
                "condition_token": condition_token,
                "disposition_token": disposition_token,
                "location_kind": location_kind,
                "location_ref_id": location_ref_id,
                "custody_text": custody_text,
                "active_task_allocation_id": active_task_allocation_id,
            }
        )

    @classmethod
    def insert_spare_part_unit(
        cls,
        connection,
        *,
        spare_part_unit_id: str,
        local_tracking_sequence: int | None,
        local_tracking_id: str | None,
        bom_code: str,
        bom_key: str,
        manufacturer_serial: str | None,
        serial_key: str | None,
        creation_origin: str,
        origin_rma_id: str | None,
        parent_spare_part_unit_id: str | None,
        condition_token: str,
        disposition_token: str,
        location_kind: str | None,
        location_ref_id: str | None,
        custody_text: str | None,
        effective_at_utc: int | None,
        command_id: str,
    ) -> tuple[str, int]:
        now = utc_epoch_seconds()
        connection.execute(
            "INSERT INTO spare_part_units("
            "spare_part_unit_id,local_tracking_sequence,local_tracking_id,bom_code,bom_key,"
            "manufacturer_serial,serial_key,creation_origin,origin_rma_id,"
            "parent_spare_part_unit_id,created_at_utc,created_command_id"
            ") VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
            (
                spare_part_unit_id,
                local_tracking_sequence,
                local_tracking_id,
                bom_code,
                bom_key,
                manufacturer_serial,
                serial_key,
                creation_origin,
                origin_rma_id,
                parent_spare_part_unit_id,
                now,
                command_id,
            ),
        )
        event_id = new_uuid4()
        connection.execute(
            "INSERT INTO spare_part_lifecycle_events("
            "unit_event_id,spare_part_unit_id,event_kind,condition_token,disposition_token,"
            "location_kind,location_ref_id,custody_text,effective_at_utc,target_event_id,"
            "reason_code,evidence_kind,evidence_id,recorded_at_utc,command_id"
            ") VALUES (?,?,'registered',?,?,?,?,?,?,NULL,NULL,NULL,NULL,?,?)",
            (
                event_id,
                spare_part_unit_id,
                condition_token,
                disposition_token,
                location_kind,
                location_ref_id,
                custody_text,
                effective_at_utc,
                now,
                command_id,
            ),
        )
        fingerprint = cls.projection_fingerprint(
            spare_part_unit_id=spare_part_unit_id,
            condition_token=condition_token,
            disposition_token=disposition_token,
            location_kind=location_kind,
            location_ref_id=location_ref_id,
            custody_text=custody_text,
            active_task_allocation_id=None,
        )
        connection.execute(
            "INSERT INTO spare_part_current_projection("
            "spare_part_unit_id,condition_token,disposition_token,location_kind,location_ref_id,"
            "custody_text,active_task_allocation_id,revision,input_fingerprint,last_command_id"
            ") VALUES (?,?,?,?,?,?,NULL,1,?,?)",
            (
                spare_part_unit_id,
                condition_token,
                disposition_token,
                location_kind,
                location_ref_id,
                custody_text,
                fingerprint,
                command_id,
            ),
        )
        return event_id, 1

    @staticmethod
    def duplicate_candidates(
        connection,
        *,
        bom_key: str,
        serial_key: str | None,
        limit: int = 50,
    ):
        if serial_key is None:
            return connection.execute(
                "SELECT u.spare_part_unit_id,u.local_tracking_id,u.bom_code,u.manufacturer_serial,"
                "p.condition_token,p.disposition_token,p.revision "
                "FROM spare_part_units u JOIN spare_part_current_projection p "
                "ON p.spare_part_unit_id=u.spare_part_unit_id "
                "WHERE u.bom_key=? ORDER BY u.spare_part_unit_id LIMIT ?",
                (bom_key, limit),
            ).fetchall()
        return connection.execute(
            "SELECT u.spare_part_unit_id,u.local_tracking_id,u.bom_code,u.manufacturer_serial,"
            "p.condition_token,p.disposition_token,p.revision "
            "FROM spare_part_units u JOIN spare_part_current_projection p "
            "ON p.spare_part_unit_id=u.spare_part_unit_id "
            "WHERE u.bom_key=? AND u.serial_key=? "
            "ORDER BY u.spare_part_unit_id LIMIT ?",
            (bom_key, serial_key, limit),
        ).fetchall()

    @staticmethod
    def current_unit(connection, spare_part_unit_id: str):
        return connection.execute(
            "SELECT u.spare_part_unit_id,u.local_tracking_id,u.bom_code,u.bom_key,"
            "u.manufacturer_serial,u.serial_key,u.creation_origin,u.origin_rma_id,"
            "p.condition_token,p.disposition_token,p.location_kind,p.location_ref_id,"
            "p.custody_text,p.active_task_allocation_id,p.revision,p.input_fingerprint "
            "FROM spare_part_units u JOIN spare_part_current_projection p "
            "ON p.spare_part_unit_id=u.spare_part_unit_id "
            "WHERE u.spare_part_unit_id=?",
            (spare_part_unit_id,),
        ).fetchone()

    @classmethod
    def attach_origin_rma(
        cls,
        connection,
        *,
        spare_part_unit_id: str,
        origin_rma_id: str,
        expected_revision: int,
        reason_code: str,
        command_id: str,
    ) -> tuple[str, int]:
        unit = cls.current_unit(connection, spare_part_unit_id)
        if unit is None or int(unit[14]) != expected_revision:
            raise SomaError("INV_STALE", "Spare Part Unit revision changed")
        if unit[7] is not None:
            raise SomaError(
                "CORRECTION_TARGET_INVALID",
                "Spare Part Unit already has RMA provenance",
            )
        if connection.execute(
            "SELECT 1 FROM rmas WHERE rma_id=?",
            (origin_rma_id,),
        ).fetchone() is None:
            raise SomaError("INV_STALE", "RMA provenance no longer exists")

        now = utc_epoch_seconds()
        event_id = new_uuid4()
        connection.execute(
            "INSERT INTO spare_part_lifecycle_events("
            "unit_event_id,spare_part_unit_id,event_kind,condition_token,disposition_token,"
            "location_kind,location_ref_id,custody_text,effective_at_utc,target_event_id,"
            "reason_code,evidence_kind,evidence_id,recorded_at_utc,command_id"
            ") VALUES (?,?,'correction',?,?,?,?,?,NULL,NULL,?,'rma_provenance',?,?,?)",
            (
                event_id,
                spare_part_unit_id,
                str(unit[8]),
                str(unit[9]),
                None if unit[10] is None else str(unit[10]),
                None if unit[11] is None else str(unit[11]),
                None if unit[12] is None else str(unit[12]),
                reason_code,
                origin_rma_id,
                now,
                command_id,
            ),
        )
        changed_root = connection.execute(
            "UPDATE spare_part_units SET origin_rma_id=? "
            "WHERE spare_part_unit_id=? AND origin_rma_id IS NULL",
            (origin_rma_id, spare_part_unit_id),
        )
        if changed_root.rowcount != 1:
            raise SomaError("INV_STALE", "Spare Part Unit provenance changed")

        revision = expected_revision + 1
        changed_projection = connection.execute(
            "UPDATE spare_part_current_projection SET revision=?,last_command_id=? "
            "WHERE spare_part_unit_id=? AND revision=?",
            (revision, command_id, spare_part_unit_id, expected_revision),
        )
        if changed_projection.rowcount != 1:
            raise SomaError("INV_STALE", "Spare Part Unit projection changed")
        return event_id, revision

    @staticmethod
    def stock_blockers(connection, spare_part_unit_id: str) -> list[str]:
        row = connection.execute(
            "SELECT condition_token,disposition_token,active_task_allocation_id "
            "FROM spare_part_current_projection WHERE spare_part_unit_id=?",
            (spare_part_unit_id,),
        ).fetchone()
        if row is None:
            return ["missing"]
        condition = str(row[0])
        disposition = str(row[1])
        blockers: list[str] = []
        if condition not in {"new", "used"}:
            blockers.append(f"condition:{condition}")
        if disposition != "available":
            blockers.append(f"disposition:{disposition}")
        if row[2] is not None:
            blockers.append("active_task_allocation")
        if connection.execute(
            "SELECT 1 FROM task_unit_allocation_current WHERE spare_part_unit_id=?",
            (spare_part_unit_id,),
        ).fetchone() is not None and "active_task_allocation" not in blockers:
            blockers.append("active_task_allocation")
        if connection.execute(
            "SELECT 1 FROM rma_return_obligation_current "
            "WHERE spare_part_unit_id=? AND obligation_state='open'",
            (spare_part_unit_id,),
        ).fetchone() is not None:
            blockers.append("open_return_obligation")
        if connection.execute(
            "SELECT 1 FROM physical_consequence_current "
            "WHERE installed_spare_part_unit_id=? LIMIT 1",
            (spare_part_unit_id,),
        ).fetchone() is not None:
            blockers.append("installed_physical_consequence")
        return blockers

    @staticmethod
    def require_task_revision(connection, task_id: str, expected_revision: int) -> None:
        row = connection.execute(
            "SELECT revision FROM tasks WHERE task_id=?",
            (task_id,),
        ).fetchone()
        if row is None:
            raise SomaError("INV_STALE", "Task no longer exists")
        if int(row[0]) != expected_revision:
            raise SomaError("INV_STALE", "Task revision changed")

    @staticmethod
    def require_active_need(
        connection,
        *,
        spare_need_id: str,
        expected_revision: int | None = None,
    ):
        row = connection.execute(
            "SELECT n.service_request_id,n.bom_key,p.lifecycle_state,p.revision "
            "FROM spare_needs n JOIN spare_need_current_projection p "
            "ON p.spare_need_id=n.spare_need_id WHERE n.spare_need_id=?",
            (spare_need_id,),
        ).fetchone()
        if row is None:
            raise SomaError("INV_STALE", "Spare Need no longer exists")
        if expected_revision is not None and int(row[3]) != expected_revision:
            raise SomaError("INV_STALE", "Spare Need revision changed")
        if str(row[2]) != "active":
            raise SomaError("STOCK_NOT_ELIGIBLE", "Spare Need is not active")
        return row

    @classmethod
    def reserve_for_task(
        cls,
        connection,
        *,
        allocation_id: str,
        task_id: str,
        spare_part_unit_id: str,
        spare_need_id: str | None,
        expected_unit_revision: int,
        expected_task_revision: int,
        command_id: str,
        effective_at_utc: int | None = None,
    ) -> tuple[str, int, int]:
        cls.require_task_revision(connection, task_id, expected_task_revision)
        unit = cls.current_unit(connection, spare_part_unit_id)
        if unit is None:
            raise SomaError("INV_STALE", "Spare Part Unit no longer exists")
        if int(unit[14]) != expected_unit_revision:
            raise SomaError("INV_STALE", "Spare Part Unit revision changed")
        if connection.execute(
            "SELECT 1 FROM task_unit_allocation_current WHERE spare_part_unit_id=?",
            (spare_part_unit_id,),
        ).fetchone() is not None:
            raise SomaError("UNIT_ALREADY_RESERVED", "Spare Part Unit is already reserved")
        blockers = cls.stock_blockers(connection, spare_part_unit_id)
        if blockers:
            raise SomaError(
                "STOCK_NOT_ELIGIBLE",
                "Spare Part Unit is not Stock eligible: " + ",".join(blockers),
            )
        if spare_need_id is not None:
            need = cls.require_active_need(connection, spare_need_id=spare_need_id)
            if str(need[1]) != str(unit[3]):
                raise SomaError(
                    "STOCK_NOT_ELIGIBLE",
                    "Spare Part Unit BOM does not match selected Spare Need",
                )
            task_sr_rows = connection.execute(
                "SELECT service_request_id FROM task_sr_links "
                "WHERE task_id=? AND active=1 ORDER BY service_request_id",
                (task_id,),
            ).fetchall()
            if task_sr_rows and str(need[0]) not in {str(row[0]) for row in task_sr_rows}:
                raise SomaError("NEED_CROSS_SR", "Task and Spare Need Service Request context differ")

        now = utc_epoch_seconds()
        event_id = new_uuid4()
        connection.execute(
            "INSERT INTO task_unit_allocation_events("
            "allocation_event_id,allocation_id,task_id,spare_part_unit_id,spare_need_id,"
            "event_kind,prior_task_id,reason_code,effective_at_utc,target_event_id,"
            "recorded_at_utc,command_id"
            ") VALUES (?,?,?,?,?,'reserve',NULL,NULL,?,NULL,?,?)",
            (
                event_id,
                allocation_id,
                task_id,
                spare_part_unit_id,
                spare_need_id,
                effective_at_utc,
                now,
                command_id,
            ),
        )
        connection.execute(
            "INSERT INTO task_unit_allocation_current("
            "allocation_id,task_id,spare_part_unit_id,spare_need_id,revision,last_event_id,last_command_id"
            ") VALUES (?,?,?,?,1,?,?)",
            (
                allocation_id,
                task_id,
                spare_part_unit_id,
                spare_need_id,
                event_id,
                command_id,
            ),
        )
        unit_revision = expected_unit_revision + 1
        fingerprint = cls.projection_fingerprint(
            spare_part_unit_id=spare_part_unit_id,
            condition_token=str(unit[8]),
            disposition_token="reserved",
            location_kind=None if unit[10] is None else str(unit[10]),
            location_ref_id=None if unit[11] is None else str(unit[11]),
            custody_text=None if unit[12] is None else str(unit[12]),
            active_task_allocation_id=allocation_id,
        )
        updated = connection.execute(
            "UPDATE spare_part_current_projection SET disposition_token='reserved',"
            "active_task_allocation_id=?,revision=?,input_fingerprint=?,last_command_id=? "
            "WHERE spare_part_unit_id=? AND revision=? AND active_task_allocation_id IS NULL",
            (
                allocation_id,
                unit_revision,
                fingerprint,
                command_id,
                spare_part_unit_id,
                expected_unit_revision,
            ),
        )
        if updated.rowcount != 1:
            raise SomaError("INV_STALE", "Spare Part Unit projection changed during reservation")
        return event_id, 1, unit_revision

    @classmethod
    def release_reservation(
        cls,
        connection,
        *,
        allocation_id: str,
        expected_allocation_revision: int,
        reason_code: str,
        command_id: str,
    ) -> tuple[str, str, int]:
        current = connection.execute(
            "SELECT task_id,spare_part_unit_id,spare_need_id,revision,last_event_id "
            "FROM task_unit_allocation_current WHERE allocation_id=?",
            (allocation_id,),
        ).fetchone()
        if current is None:
            raise SomaError("CORRECTION_TARGET_INVALID", "Task reservation is not active")
        if int(current[3]) != expected_allocation_revision:
            raise SomaError("INV_STALE", "Task reservation revision changed")
        unit_id = str(current[1])
        if connection.execute(
            "SELECT 1 FROM physical_consequence_current "
            "WHERE installed_spare_part_unit_id=? LIMIT 1",
            (unit_id,),
        ).fetchone() is not None:
            raise SomaError(
                "CORRECTION_TARGET_INVALID",
                "Task reservation is protected by accepted physical consequence",
            )
        unit = cls.current_unit(connection, unit_id)
        if unit is None:
            raise IntegrityFailure("Task reservation points to missing Spare Part Unit")
        if unit[13] != allocation_id:
            raise IntegrityFailure("Spare Part Unit projection disagrees with current reservation")

        now = utc_epoch_seconds()
        event_id = new_uuid4()
        connection.execute(
            "INSERT INTO task_unit_allocation_events("
            "allocation_event_id,allocation_id,task_id,spare_part_unit_id,spare_need_id,"
            "event_kind,prior_task_id,reason_code,effective_at_utc,target_event_id,"
            "recorded_at_utc,command_id"
            ") VALUES (?,?,?,?,?,'release',NULL,?,NULL,?, ?,?)",
            (
                event_id,
                allocation_id,
                str(current[0]),
                unit_id,
                None if current[2] is None else str(current[2]),
                reason_code,
                str(current[4]),
                now,
                command_id,
            ),
        )
        deleted = connection.execute(
            "DELETE FROM task_unit_allocation_current WHERE allocation_id=? AND revision=?",
            (allocation_id, expected_allocation_revision),
        )
        if deleted.rowcount != 1:
            raise SomaError("INV_STALE", "Task reservation changed during release")

        condition = str(unit[8])
        disposition = "available" if condition in {"new", "used"} else "unavailable"
        unit_revision = int(unit[14]) + 1
        fingerprint = cls.projection_fingerprint(
            spare_part_unit_id=unit_id,
            condition_token=condition,
            disposition_token=disposition,
            location_kind=None if unit[10] is None else str(unit[10]),
            location_ref_id=None if unit[11] is None else str(unit[11]),
            custody_text=None if unit[12] is None else str(unit[12]),
            active_task_allocation_id=None,
        )
        updated = connection.execute(
            "UPDATE spare_part_current_projection SET disposition_token=?,"
            "active_task_allocation_id=NULL,revision=?,input_fingerprint=?,last_command_id=? "
            "WHERE spare_part_unit_id=? AND revision=? AND active_task_allocation_id=?",
            (
                disposition,
                unit_revision,
                fingerprint,
                command_id,
                unit_id,
                int(unit[14]),
                allocation_id,
            ),
        )
        if updated.rowcount != 1:
            raise SomaError("INV_STALE", "Spare Part Unit projection changed during release")
        return event_id, unit_id, unit_revision


    @classmethod
    def reassign_task_allocation(
        cls,
        connection,
        *,
        allocation_id: str,
        predecessor_task_id: str,
        new_task_id: str,
        expected_allocation_revision: int,
        command_id: str,
    ) -> tuple[str, str, str | None, int, int]:
        current = connection.execute(
            "SELECT task_id,spare_part_unit_id,spare_need_id,revision,last_event_id "
            "FROM task_unit_allocation_current WHERE allocation_id=?",
            (allocation_id,),
        ).fetchone()
        if current is None:
            raise SomaError("INV_STALE", "Selected retry allocation is no longer current")
        if str(current[0]) != predecessor_task_id or int(current[3]) != expected_allocation_revision:
            raise SomaError("INV_STALE", "Selected retry allocation changed")
        if connection.execute(
            "SELECT 1 FROM tasks WHERE task_id=?",
            (new_task_id,),
        ).fetchone() is None:
            raise SomaError("INV_STALE", "Retry successor Task is missing")
        if connection.execute(
            "SELECT 1 FROM inventory_physical_consequences WHERE task_id=? LIMIT 1",
            (predecessor_task_id,),
        ).fetchone() is not None:
            raise SomaError(
                "CORRECTION_TARGET_INVALID",
                "Inventory allocation is protected by predecessor physical-consequence history",
            )
        unit_id = str(current[1])
        unit = cls.current_unit(connection, unit_id)
        if unit is None:
            raise IntegrityFailure("Retry allocation points to missing Spare Part Unit")
        if unit[13] is None or str(unit[13]) != allocation_id:
            raise IntegrityFailure("Spare Part Unit projection disagrees with retry allocation")
        now = utc_epoch_seconds()
        event_id = new_uuid4()
        connection.execute(
            "INSERT INTO task_unit_allocation_events("
            "allocation_event_id,allocation_id,task_id,spare_part_unit_id,spare_need_id,"
            "event_kind,prior_task_id,reason_code,effective_at_utc,target_event_id,"
            "recorded_at_utc,command_id"
            ") VALUES (?,?,?,?,?,'reassign',?,'retry_clone',NULL,?,?,?)",
            (
                event_id,
                allocation_id,
                new_task_id,
                unit_id,
                None if current[2] is None else str(current[2]),
                predecessor_task_id,
                str(current[4]),
                now,
                command_id,
            ),
        )
        next_revision = expected_allocation_revision + 1
        changed = connection.execute(
            "UPDATE task_unit_allocation_current SET task_id=?,revision=?,last_event_id=?,"
            "last_command_id=? WHERE allocation_id=? AND task_id=? AND revision=? AND last_event_id=?",
            (
                new_task_id,
                next_revision,
                event_id,
                command_id,
                allocation_id,
                predecessor_task_id,
                expected_allocation_revision,
                str(current[4]),
            ),
        )
        if changed.rowcount != 1:
            raise SomaError("INV_STALE", "Retry allocation changed during reassignment")
        return (
            event_id,
            unit_id,
            None if current[2] is None else str(current[2]),
            next_revision,
            int(unit[14]),
        )

    @staticmethod
    def latest_allocation_event(connection, allocation_id: str):
        return connection.execute(
            "SELECT event_kind,allocation_event_id,spare_part_unit_id "
            "FROM task_unit_allocation_events WHERE allocation_id=? "
            "ORDER BY recorded_at_utc DESC,allocation_event_id DESC LIMIT 1",
            (allocation_id,),
        ).fetchone()

    @staticmethod
    def record_local_fulfillment(
        connection,
        *,
        fulfillment_event_id: str,
        spare_need_id: str,
        spare_part_unit_id: str,
        task_id: str | None,
        reason_code: str | None,
        command_id: str,
    ) -> str:
        event_id = fulfillment_event_id
        connection.execute(
            "INSERT INTO local_need_fulfillment_events("
            "local_fulfillment_event_id,spare_need_id,spare_part_unit_id,task_id,quantity,"
            "event_kind,reason_code,recorded_at_utc,command_id"
            ") VALUES (?,?,?,?,1,'selected',?,?,?)",
            (
                event_id,
                spare_need_id,
                spare_part_unit_id,
                task_id,
                reason_code,
                utc_epoch_seconds(),
                command_id,
            ),
        )
        return event_id


__all__ = ["InventoryUnitsRepository"]
