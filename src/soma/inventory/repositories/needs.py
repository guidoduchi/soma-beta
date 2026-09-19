from __future__ import annotations

from soma.foundation.errors import IntegrityFailure, SomaError
from soma.foundation.identifiers import new_uuid4, utc_epoch_seconds
from soma.foundation.strict_json import sha256_canonical_json


class InventoryNeedsRepository:
    @staticmethod
    def require_sr_device_context(connection, service_request_id: str, device_reference_id: str) -> None:
        if connection.execute(
            "SELECT 1 FROM service_requests WHERE service_request_id=?",
            (service_request_id,),
        ).fetchone() is None:
            raise SomaError("INV_STALE", "Service Request no longer exists")
        if connection.execute(
            "SELECT 1 FROM device_references WHERE device_reference_id=?",
            (device_reference_id,),
        ).fetchone() is None:
            raise SomaError("INV_STALE", "Device Reference no longer exists")
        if connection.execute(
            "SELECT 1 FROM sr_device_reference_links "
            "WHERE service_request_id=? AND device_reference_id=? AND link_state='active'",
            (service_request_id, device_reference_id),
        ).fetchone() is None:
            raise SomaError("INV_STALE", "Device Reference is not active in the Service Request context")

    @staticmethod
    def allocate_device_part_creation_sequence(connection, command_id: str) -> int:
        row = connection.execute(
            "SELECT next_sequence,revision FROM inventory_tracking_allocators "
            "WHERE allocator_kind='device_part_creation'"
        ).fetchone()
        if row is None:
            raise IntegrityFailure("Inventory Device Part allocator is missing")
        sequence = int(row[0])
        if sequence >= 100_000_000:
            raise SomaError("INV_INVALID_ID", "Device Part creation sequence is exhausted")
        updated = connection.execute(
            "UPDATE inventory_tracking_allocators SET next_sequence=?,revision=?,last_command_id=? "
            "WHERE allocator_kind='device_part_creation' AND next_sequence=? AND revision=?",
            (sequence + 1, int(row[1]) + 1, command_id, sequence, int(row[1])),
        )
        if updated.rowcount != 1:
            raise SomaError("INV_STALE", "Device Part allocator changed")
        return sequence

    @staticmethod
    def insert_device_part(
        connection,
        *,
        device_part_unit_id: str,
        service_request_id: str,
        device_reference_id: str,
        creation_sequence: int,
        bom_code: str,
        bom_key: str,
        manufacturer_serial: str | None,
        serial_key: str | None,
        slot_label: str | None,
        creation_origin: str,
        condition_token: str,
        effective_at_utc: int | None,
        command_id: str,
    ) -> tuple[str, int]:
        now = utc_epoch_seconds()
        connection.execute(
            "INSERT INTO device_part_units("
            "device_part_unit_id,service_request_id,device_reference_id,creation_sequence,"
            "bom_code,bom_key,manufacturer_serial,serial_key,slot_label,creation_origin,"
            "created_at_utc,created_command_id"
            ") VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
            (
                device_part_unit_id,
                service_request_id,
                device_reference_id,
                creation_sequence,
                bom_code,
                bom_key,
                manufacturer_serial,
                serial_key,
                slot_label,
                creation_origin,
                now,
                command_id,
            ),
        )
        registered_event = new_uuid4()
        connection.execute(
            "INSERT INTO device_part_lifecycle_events("
            "device_part_event_id,device_part_unit_id,event_kind,condition_token,effective_at_utc,"
            "target_event_id,reason_code,evidence_kind,evidence_id,recorded_at_utc,command_id"
            ") VALUES (?,?,'registered',?,?,?,?,?,?,?,?)",
            (
                registered_event,
                device_part_unit_id,
                condition_token if condition_token != "faulty" else "unknown",
                effective_at_utc,
                None,
                None,
                None,
                None,
                now,
                command_id,
            ),
        )
        last_event = registered_event
        projection_revision = 1
        if condition_token == "faulty":
            fault_event = new_uuid4()
            connection.execute(
                "INSERT INTO device_part_lifecycle_events("
                "device_part_event_id,device_part_unit_id,event_kind,condition_token,effective_at_utc,"
                "target_event_id,reason_code,evidence_kind,evidence_id,recorded_at_utc,command_id"
                ") VALUES (?,?,'fault_observed','faulty',?,?,?,?,?,?,?)",
                (
                    fault_event,
                    device_part_unit_id,
                    effective_at_utc,
                    None,
                    None,
                    None,
                    None,
                    now,
                    command_id,
                ),
            )
            last_event = fault_event
            projection_revision = 2
        fingerprint = sha256_canonical_json(
            {
                "schema": "SOMA_DEVICE_PART_CURRENT_V1",
                "device_part_unit_id": device_part_unit_id,
                "condition_token": condition_token,
                "last_event_id": last_event,
            }
        )
        connection.execute(
            "INSERT INTO device_part_current_projection("
            "device_part_unit_id,condition_token,revision,input_fingerprint,last_event_id,last_command_id"
            ") VALUES (?,?,?,?,?,?)",
            (
                device_part_unit_id,
                condition_token,
                projection_revision,
                fingerprint,
                last_event,
                command_id,
            ),
        )
        return last_event, projection_revision

    @staticmethod
    def active_need_for(connection, service_request_id: str, bom_key: str):
        return connection.execute(
            "SELECT k.spare_need_id,n.bom_code,n.bom_key,p.lifecycle_state,p.planned_quantity,"
            "p.contributor_count,p.revision "
            "FROM spare_need_active_keys k "
            "JOIN spare_needs n ON n.spare_need_id=k.spare_need_id "
            "JOIN spare_need_current_projection p ON p.spare_need_id=k.spare_need_id "
            "WHERE k.service_request_id=? AND k.bom_key=?",
            (service_request_id, bom_key),
        ).fetchone()

    @staticmethod
    def _active_contributors(connection, spare_need_id: str) -> list[str]:
        return [
            str(row[0])
            for row in connection.execute(
                "SELECT device_part_unit_id FROM spare_need_contributors "
                "WHERE spare_need_id=? AND active=1 ORDER BY device_part_unit_id",
                (spare_need_id,),
            ).fetchall()
        ]

    @classmethod
    def _need_fingerprint(
        cls,
        connection,
        *,
        spare_need_id: str,
        lifecycle_state: str,
        planned_quantity: int,
    ) -> str:
        contributors = cls._active_contributors(connection, spare_need_id)
        return sha256_canonical_json(
            {
                "schema": "SOMA_SPARE_NEED_CURRENT_V1",
                "spare_need_id": spare_need_id,
                "lifecycle_state": lifecycle_state,
                "planned_quantity": planned_quantity,
                "active_contributors": contributors,
            }
        )

    @classmethod
    def create_need_with_contributor(
        cls,
        connection,
        *,
        service_request_id: str,
        bom_code: str,
        bom_key: str,
        device_part_unit_id: str,
        command_id: str,
    ) -> tuple[str, str, str, int]:
        now = utc_epoch_seconds()
        spare_need_id = new_uuid4()
        need_event_id = new_uuid4()
        contributor_id = new_uuid4()
        connection.execute(
            "INSERT INTO spare_needs("
            "spare_need_id,service_request_id,bom_code,bom_key,description,planned_quantity,"
            "creation_origin,created_at_utc,created_command_id"
            ") VALUES (?,?,?,?,NULL,1,'system_aggregate',?,?)",
            (spare_need_id, service_request_id, bom_code, bom_key, now, command_id),
        )
        connection.execute(
            "INSERT INTO spare_need_lifecycle_events("
            "need_event_id,spare_need_id,event_kind,planned_quantity,reason_code,effective_at_utc,"
            "recorded_at_utc,command_id"
            ") VALUES (?,?,'created',1,NULL,NULL,?,?)",
            (need_event_id, spare_need_id, now, command_id),
        )
        connection.execute(
            "INSERT INTO spare_need_active_keys(service_request_id,bom_key,spare_need_id) VALUES (?,?,?)",
            (service_request_id, bom_key, spare_need_id),
        )
        connection.execute(
            "INSERT INTO spare_need_contributors("
            "contributor_relationship_id,spare_need_id,device_part_unit_id,active,opened_at_utc,"
            "opened_command_id,closed_at_utc,closed_command_id,close_reason"
            ") VALUES (?,?,?,1,?,?,NULL,NULL,NULL)",
            (contributor_id, spare_need_id, device_part_unit_id, now, command_id),
        )
        fingerprint = cls._need_fingerprint(
            connection,
            spare_need_id=spare_need_id,
            lifecycle_state="active",
            planned_quantity=1,
        )
        connection.execute(
            "INSERT INTO spare_need_current_projection("
            "spare_need_id,lifecycle_state,planned_quantity,contributor_count,revision,input_fingerprint,last_command_id"
            ") VALUES (?,'active',1,1,1,?,?)",
            (spare_need_id, fingerprint, command_id),
        )
        return spare_need_id, need_event_id, contributor_id, 1

    @classmethod
    def add_contributor(
        cls,
        connection,
        *,
        spare_need_id: str,
        service_request_id: str,
        bom_key: str,
        device_part_unit_id: str,
        command_id: str,
    ) -> tuple[str, int, int]:
        row = connection.execute(
            "SELECT n.service_request_id,n.bom_key,p.lifecycle_state,p.planned_quantity,p.revision "
            "FROM spare_needs n JOIN spare_need_current_projection p ON p.spare_need_id=n.spare_need_id "
            "WHERE n.spare_need_id=?",
            (spare_need_id,),
        ).fetchone()
        if row is None:
            raise SomaError("INV_STALE", "Spare Need disappeared")
        if str(row[0]) != service_request_id or str(row[1]) != bom_key:
            raise SomaError("NEED_CROSS_SR", "Need aggregation target does not match SR/BOM")
        if str(row[2]) != "active":
            raise SomaError("INV_STALE", "Spare Need is no longer active")
        other = connection.execute(
            "SELECT spare_need_id FROM spare_need_contributors "
            "WHERE device_part_unit_id=? AND active=1",
            (device_part_unit_id,),
        ).fetchone()
        if other is not None:
            if str(other[0]) == spare_need_id:
                raise IntegrityFailure("new Device Part unexpectedly already contributes to its Need")
            raise SomaError("NEED_CROSS_SR", "Device Part already contributes to another active Need")
        contributor_id = new_uuid4()
        now = utc_epoch_seconds()
        connection.execute(
            "INSERT INTO spare_need_contributors("
            "contributor_relationship_id,spare_need_id,device_part_unit_id,active,opened_at_utc,"
            "opened_command_id,closed_at_utc,closed_command_id,close_reason"
            ") VALUES (?,?,?,1,?,?,NULL,NULL,NULL)",
            (contributor_id, spare_need_id, device_part_unit_id, now, command_id),
        )
        planned = int(row[3])
        new_revision = int(row[4]) + 1
        contributors = len(cls._active_contributors(connection, spare_need_id))
        fingerprint = cls._need_fingerprint(
            connection,
            spare_need_id=spare_need_id,
            lifecycle_state="active",
            planned_quantity=planned,
        )
        connection.execute(
            "UPDATE spare_need_current_projection SET contributor_count=?,revision=?,"
            "input_fingerprint=?,last_command_id=? WHERE spare_need_id=?",
            (contributors, new_revision, fingerprint, command_id, spare_need_id),
        )
        return contributor_id, new_revision, planned

    @classmethod
    def change_planned_quantity(
        cls,
        connection,
        *,
        spare_need_id: str,
        base_revision: int,
        planned_quantity: int,
        reason_code: str,
        command_id: str,
    ) -> tuple[str, int]:
        row = connection.execute(
            "SELECT lifecycle_state,planned_quantity,revision FROM spare_need_current_projection "
            "WHERE spare_need_id=?",
            (spare_need_id,),
        ).fetchone()
        if row is None or int(row[2]) != base_revision:
            raise SomaError("INV_STALE", "Spare Need revision changed")
        if int(row[1]) == planned_quantity:
            raise IntegrityFailure("semantic NO_CHANGE must be handled before repository mutation")
        event_id = new_uuid4()
        now = utc_epoch_seconds()
        connection.execute(
            "INSERT INTO spare_need_lifecycle_events("
            "need_event_id,spare_need_id,event_kind,planned_quantity,reason_code,effective_at_utc,"
            "recorded_at_utc,command_id"
            ") VALUES (?,?,'planned_quantity_changed',?,?,NULL,?,?)",
            (event_id, spare_need_id, planned_quantity, reason_code, now, command_id),
        )
        revision = base_revision + 1
        fingerprint = cls._need_fingerprint(
            connection,
            spare_need_id=spare_need_id,
            lifecycle_state=str(row[0]),
            planned_quantity=planned_quantity,
        )
        connection.execute(
            "UPDATE spare_need_current_projection SET planned_quantity=?,revision=?,"
            "input_fingerprint=?,last_command_id=? WHERE spare_need_id=?",
            (planned_quantity, revision, fingerprint, command_id, spare_need_id),
        )
        return event_id, revision

    @staticmethod
    def request_dependency_states(connection, spare_need_id: str) -> list[str]:
        rows = connection.execute(
            "SELECT DISTINCT a.spare_request_id,p.lifecycle_state "
            "FROM spare_request_need_allocations a "
            "LEFT JOIN spare_request_current_projection p ON p.spare_request_id=a.spare_request_id "
            "WHERE a.spare_need_id=?",
            (spare_need_id,),
        ).fetchall()
        states: list[str] = []
        for row in rows:
            if row[1] is None:
                raise SomaError("DEPENDENCY_INDETERMINATE", "Spare Request state cannot be proven")
            states.append(str(row[1]))
        return states

    @classmethod
    def change_lifecycle(
        cls,
        connection,
        *,
        spare_need_id: str,
        base_revision: int,
        action: str,
        reason_code: str,
        command_id: str,
    ) -> tuple[str, int, str]:
        row = connection.execute(
            "SELECT n.service_request_id,n.bom_key,p.lifecycle_state,p.planned_quantity,p.revision "
            "FROM spare_needs n JOIN spare_need_current_projection p ON p.spare_need_id=n.spare_need_id "
            "WHERE n.spare_need_id=?",
            (spare_need_id,),
        ).fetchone()
        if row is None or int(row[4]) != base_revision:
            raise SomaError("INV_STALE", "Spare Need revision changed")
        service_request_id = str(row[0])
        bom_key = str(row[1])
        current_state = str(row[2])
        planned_quantity = int(row[3])
        target = {
            "resolve": "resolved",
            "cancel": "cancelled",
            "reactivate": "active",
            "history_remove": "removed",
        }[action]
        if current_state == target:
            raise IntegrityFailure("semantic NO_CHANGE must be handled before repository mutation")
        if action in {"resolve", "cancel", "history_remove"} and current_state != "active":
            raise SomaError("INV_STALE", "Need lifecycle action requires current active state")
        if action == "reactivate":
            if current_state not in {"resolved", "cancelled"}:
                raise SomaError("INV_STALE", "Only resolved or cancelled Needs may reactivate")
            conflict = connection.execute(
                "SELECT spare_need_id FROM spare_need_active_keys "
                "WHERE service_request_id=? AND bom_key=?",
                (service_request_id, bom_key),
            ).fetchone()
            if conflict is not None and str(conflict[0]) != spare_need_id:
                raise SomaError("INV_STALE", "Another active Need owns this SR/BOM key")
        if action == "history_remove":
            states = cls.request_dependency_states(connection, spare_need_id)
            if any(state not in {"cancelled", "rejected"} for state in states):
                raise SomaError("NEED_DELETE_BLOCKED", "Need has a nonterminal Spare Request dependency")

        now = utc_epoch_seconds()
        event_id = new_uuid4()
        event_kind = {
            "resolve": "resolved",
            "cancel": "cancelled",
            "reactivate": "reactivated",
            "history_remove": "history_removed",
        }[action]
        connection.execute(
            "INSERT INTO spare_need_lifecycle_events("
            "need_event_id,spare_need_id,event_kind,planned_quantity,reason_code,effective_at_utc,"
            "recorded_at_utc,command_id"
            ") VALUES (?,?,?,NULL,?,NULL,?,?)",
            (event_id, spare_need_id, event_kind, reason_code, now, command_id),
        )
        if current_state == "active" and target != "active":
            deleted = connection.execute(
                "DELETE FROM spare_need_active_keys WHERE service_request_id=? AND bom_key=? "
                "AND spare_need_id=?",
                (service_request_id, bom_key, spare_need_id),
            )
            if deleted.rowcount != 1:
                raise SomaError("INV_STALE", "Active Need key changed")
        elif current_state != "active" and target == "active":
            connection.execute(
                "INSERT INTO spare_need_active_keys(service_request_id,bom_key,spare_need_id) VALUES (?,?,?)",
                (service_request_id, bom_key, spare_need_id),
            )
        revision = base_revision + 1
        fingerprint = cls._need_fingerprint(
            connection,
            spare_need_id=spare_need_id,
            lifecycle_state=target,
            planned_quantity=planned_quantity,
        )
        connection.execute(
            "UPDATE spare_need_current_projection SET lifecycle_state=?,revision=?,"
            "input_fingerprint=?,last_command_id=? WHERE spare_need_id=?",
            (target, revision, fingerprint, command_id, spare_need_id),
        )
        return event_id, revision, target
