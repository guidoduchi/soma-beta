from __future__ import annotations

import json
from typing import Any

from soma.foundation.errors import IntegrityFailure, SomaError
from soma.foundation.identifiers import new_uuid4, utc_epoch_seconds
from soma.foundation.strict_json import canonical_json_bytes, sha256_canonical_json

from .rmas import InventoryRmasRepository
from .units import InventoryUnitsRepository


class InventoryLogisticsRepository:
    @staticmethod
    def reference_context(
        connection: Any,
        *,
        dispatch_location_id: str | None,
        receiver_contact_id: str | None,
    ) -> dict[str, object]:
        location_name: str | None = None
        location_address: str | None = None
        if dispatch_location_id is not None:
            row = connection.execute(
                "SELECT name,address_mode,standalone_address_text,lifecycle_state,revision "
                "FROM dispatch_locations WHERE dispatch_location_id=?",
                (dispatch_location_id,),
            ).fetchone()
            if row is None or str(row[3]) != "active":
                raise SomaError("INV_STALE", "Dispatch Location is not active")
            if str(row[1]) != "standalone" or row[2] is None:
                raise SomaError(
                    "DEPENDENCY_INDETERMINATE",
                    "Site-derived Dispatch Location address requires Infrastructure resolution",
                )
            location_name = str(row[0])
            location_address = str(row[2])

        receiver_snapshot: dict[str, object] | None = None
        if receiver_contact_id is not None:
            row = connection.execute(
                "SELECT name,lifecycle_state,revision FROM contacts WHERE contact_id=?",
                (receiver_contact_id,),
            ).fetchone()
            if row is None or str(row[1]) != "active":
                raise SomaError("INV_STALE", "Receiver Contact is not active")
            receiver_snapshot = {
                "schema": "LOGISTICS_RECEIVER_V1",
                "contact_id": receiver_contact_id,
                "display_name_snapshot": str(row[0]),
                "contact_revision": int(row[2]),
            }
        return {
            "dispatch_location_id": dispatch_location_id,
            "location_name_snapshot": location_name,
            "location_address_snapshot": location_address,
            "receiver_contact_id": receiver_contact_id,
            "receiver_snapshot": receiver_snapshot,
        }

    @classmethod
    def require_reference_context(
        cls,
        connection: Any,
        *,
        expected: dict[str, object],
    ) -> None:
        current = cls.reference_context(
            connection,
            dispatch_location_id=(
                None
                if expected["dispatch_location_id"] is None
                else str(expected["dispatch_location_id"])
            ),
            receiver_contact_id=(
                None
                if expected["receiver_contact_id"] is None
                else str(expected["receiver_contact_id"])
            ),
        )
        if current != expected:
            raise SomaError("INV_STALE", "Actual logistics reference context changed")

    @staticmethod
    def require_participants(
        connection: Any,
        *,
        rma_ids: tuple[str, ...],
        spare_part_unit_ids: tuple[str, ...],
        device_part_unit_ids: tuple[str, ...],
    ) -> None:
        for rma_id in rma_ids:
            if connection.execute(
                "SELECT 1 FROM rmas WHERE rma_id=?",
                (rma_id,),
            ).fetchone() is None:
                raise SomaError("INV_STALE", "RMA logistics participant no longer exists")
        for unit_id in spare_part_unit_ids:
            if connection.execute(
                "SELECT 1 FROM spare_part_units WHERE spare_part_unit_id=?",
                (unit_id,),
            ).fetchone() is None:
                raise SomaError("INV_STALE", "Spare Part logistics participant no longer exists")
        for unit_id in device_part_unit_ids:
            if connection.execute(
                "SELECT 1 FROM device_part_units WHERE device_part_unit_id=?",
                (unit_id,),
            ).fetchone() is None:
                raise SomaError("INV_STALE", "Device Part logistics participant no longer exists")

    @classmethod
    def insert_logistics_event(
        cls,
        connection: Any,
        *,
        event_kind: str,
        effective_at_utc: int | None,
        reference_context: dict[str, object],
        custody_text: str | None,
        observed_condition: str | None,
        rma_ids: tuple[str, ...],
        spare_part_unit_ids: tuple[str, ...],
        device_part_unit_ids: tuple[str, ...],
        evidence_kind: str | None,
        evidence_id: str | None,
        reason_code: str | None,
        target_event_id: str | None,
        command_id: str,
        logistics_event_id: str | None = None,
    ) -> tuple[str, tuple[tuple[str, str], ...]]:
        cls.require_reference_context(connection, expected=reference_context)
        cls.require_participants(
            connection,
            rma_ids=rma_ids,
            spare_part_unit_ids=spare_part_unit_ids,
            device_part_unit_ids=device_part_unit_ids,
        )
        event_id = new_uuid4() if logistics_event_id is None else logistics_event_id
        now = utc_epoch_seconds()
        receiver_snapshot = reference_context["receiver_snapshot"]
        connection.execute(
            "INSERT INTO actual_logistics_events("
            "logistics_event_id,event_kind,effective_at_utc,dispatch_location_id,"
            "location_name_snapshot,location_address_snapshot,receiver_contact_id,"
            "receiver_snapshot_json,custody_text,observed_condition,target_event_id,"
            "reason_code,evidence_kind,evidence_id,recorded_at_utc,command_id"
            ") VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (
                event_id,
                event_kind,
                effective_at_utc,
                reference_context["dispatch_location_id"],
                reference_context["location_name_snapshot"],
                reference_context["location_address_snapshot"],
                reference_context["receiver_contact_id"],
                (
                    None
                    if receiver_snapshot is None
                    else canonical_json_bytes(receiver_snapshot).decode("utf-8")
                ),
                custody_text,
                observed_condition,
                target_event_id,
                reason_code,
                evidence_kind,
                evidence_id,
                now,
                command_id,
            ),
        )
        refs: list[tuple[str, str]] = []
        for rma_id in rma_ids:
            participant_id = new_uuid4()
            connection.execute(
                "INSERT INTO logistics_rma_participants("
                "logistics_rma_participant_id,logistics_event_id,rma_id,active,"
                "opened_command_id,closed_command_id,close_reason"
                ") VALUES (?,?,?,1,?,NULL,NULL)",
                (participant_id, event_id, rma_id, command_id),
            )
            refs.append(("rma", participant_id))
        for unit_id in spare_part_unit_ids:
            participant_id = new_uuid4()
            connection.execute(
                "INSERT INTO logistics_spare_unit_participants("
                "logistics_spare_participant_id,logistics_event_id,spare_part_unit_id,"
                "active,opened_command_id,closed_command_id,close_reason"
                ") VALUES (?,?,?,1,?,NULL,NULL)",
                (participant_id, event_id, unit_id, command_id),
            )
            refs.append(("spare_part_unit", participant_id))
        for unit_id in device_part_unit_ids:
            participant_id = new_uuid4()
            connection.execute(
                "INSERT INTO logistics_device_part_participants("
                "logistics_device_participant_id,logistics_event_id,device_part_unit_id,"
                "active,opened_command_id,closed_command_id,close_reason"
                ") VALUES (?,?,?,1,?,NULL,NULL)",
                (participant_id, event_id, unit_id, command_id),
            )
            refs.append(("device_part_unit", participant_id))
        return event_id, tuple(refs)

    @classmethod
    def record_rma_inbound_receipt(
        cls,
        connection: Any,
        *,
        rma_id: str,
        spare_part_unit_id: str,
        actual_bom_code: str,
        actual_bom_key: str,
        manufacturer_serial: str | None,
        serial_key: str | None,
        condition_token: str,
        disposition_token: str,
        effective_at_utc: int | None,
        reference_context: dict[str, object],
        custody_text: str | None,
        evidence_kind: str | None,
        evidence_id: str | None,
        command_id: str,
    ) -> dict[str, object]:
        rma = InventoryRmasRepository.current_rma(connection, rma_id)
        if rma is None:
            raise SomaError("INV_STALE", "RMA no longer exists")
        if connection.execute(
            "SELECT 1 FROM rma_direct_inbound_units WHERE rma_id=?",
            (rma_id,),
        ).fetchone() is not None:
            raise SomaError("RMA_INBOUND_EXISTS", "RMA already has a direct inbound unit")

        cls.require_reference_context(connection, expected=reference_context)
        now = utc_epoch_seconds()
        connection.execute(
            "INSERT INTO spare_part_units("
            "spare_part_unit_id,local_tracking_sequence,local_tracking_id,bom_code,bom_key,"
            "manufacturer_serial,serial_key,creation_origin,origin_rma_id,"
            "parent_spare_part_unit_id,created_at_utc,created_command_id"
            ") VALUES (?,NULL,NULL,?,?,?,?, 'direct_rma_receipt',?,NULL,?,?)",
            (
                spare_part_unit_id,
                actual_bom_code,
                actual_bom_key,
                manufacturer_serial,
                serial_key,
                rma_id,
                now,
                command_id,
            ),
        )
        registered_event_id = new_uuid4()
        received_event_id = new_uuid4()
        location_ref_id = reference_context["dispatch_location_id"]
        location_kind = None if location_ref_id is None else "dispatch_location"
        connection.execute(
            "INSERT INTO spare_part_lifecycle_events("
            "unit_event_id,spare_part_unit_id,event_kind,condition_token,disposition_token,"
            "location_kind,location_ref_id,custody_text,effective_at_utc,target_event_id,"
            "reason_code,evidence_kind,evidence_id,recorded_at_utc,command_id"
            ") VALUES (?,?,'registered',?,?,?,?,?,?,NULL,NULL,NULL,NULL,?,?)",
            (
                registered_event_id,
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
        connection.execute(
            "INSERT INTO spare_part_lifecycle_events("
            "unit_event_id,spare_part_unit_id,event_kind,condition_token,disposition_token,"
            "location_kind,location_ref_id,custody_text,effective_at_utc,target_event_id,"
            "reason_code,evidence_kind,evidence_id,recorded_at_utc,command_id"
            ") VALUES (?,?,'received',?,?,?,?,?,?,NULL,NULL,?,?,?,?)",
            (
                received_event_id,
                spare_part_unit_id,
                condition_token,
                disposition_token,
                location_kind,
                location_ref_id,
                custody_text,
                effective_at_utc,
                evidence_kind,
                evidence_id,
                now,
                command_id,
            ),
        )
        unit_fingerprint = InventoryUnitsRepository.projection_fingerprint(
            spare_part_unit_id=spare_part_unit_id,
            condition_token=condition_token,
            disposition_token=disposition_token,
            location_kind=location_kind,
            location_ref_id=None if location_ref_id is None else str(location_ref_id),
            custody_text=custody_text,
            active_task_allocation_id=None,
        )
        connection.execute(
            "INSERT INTO spare_part_current_projection("
            "spare_part_unit_id,condition_token,disposition_token,location_kind,location_ref_id,"
            "custody_text,active_task_allocation_id,revision,input_fingerprint,last_command_id"
            ") VALUES (?,?,?,?,?,?,NULL,2,?,?)",
            (
                spare_part_unit_id,
                condition_token,
                disposition_token,
                location_kind,
                location_ref_id,
                custody_text,
                unit_fingerprint,
                command_id,
            ),
        )
        direct_relationship_id = new_uuid4()
        connection.execute(
            "INSERT INTO rma_direct_inbound_units("
            "direct_inbound_relationship_id,rma_id,spare_part_unit_id,"
            "relationship_event_id,opened_command_id"
            ") VALUES (?,?,?,?,?)",
            (
                direct_relationship_id,
                rma_id,
                spare_part_unit_id,
                received_event_id,
                command_id,
            ),
        )

        logistics_event_id, participant_refs = cls.insert_logistics_event(
            connection,
            event_kind="receipt",
            effective_at_utc=effective_at_utc,
            reference_context=reference_context,
            custody_text=custody_text,
            observed_condition=condition_token,
            rma_ids=(rma_id,),
            spare_part_unit_ids=(spare_part_unit_id,),
            device_part_unit_ids=(),
            evidence_kind=evidence_kind,
            evidence_id=evidence_id,
            reason_code=None,
            target_event_id=None,
            command_id=command_id,
        )

        rma_revision = int(rma[12]) + 1
        rma_fingerprint = InventoryRmasRepository.rma_lifecycle_fingerprint(
            rma_id=rma_id,
            current_c10=str(rma[4]),
            state="received",
            target_device_part_unit_id=None if rma[6] is None else str(rma[6]),
            direct_inbound_spare_part_unit_id=spare_part_unit_id,
            return_device_part_unit_id=None if rma[8] is None else str(rma[8]),
            return_spare_part_unit_id=None if rma[9] is None else str(rma[9]),
            return_obligation_open=bool(rma[10]),
            active_fault_tag_membership_id=None if rma[11] is None else str(rma[11]),
        )
        updated = connection.execute(
            "UPDATE rma_lifecycle_projection SET state='received',"
            "direct_inbound_spare_part_unit_id=?,revision=?,input_fingerprint=?,"
            "last_command_id=? WHERE rma_id=? AND revision=? "
            "AND direct_inbound_spare_part_unit_id IS NULL",
            (
                spare_part_unit_id,
                rma_revision,
                rma_fingerprint,
                command_id,
                rma_id,
                int(rma[12]),
            ),
        )
        if updated.rowcount != 1:
            raise SomaError("INV_STALE", "RMA lifecycle changed during inbound receipt")

        connection.execute(
            "DELETE FROM inventory_attention_projection "
            "WHERE target_kind='rma' AND target_id=? AND attention_kind='receipt_bom_mismatch'",
            (rma_id,),
        )
        if actual_bom_key != str(rma[3]):
            attention_id = new_uuid4()
            attention_fingerprint = sha256_canonical_json(
                {
                    "schema": "SOMA_INVENTORY_ATTENTION_V1",
                    "target_kind": "rma",
                    "target_id": rma_id,
                    "attention_kind": "receipt_bom_mismatch",
                    "promised_bom_key": str(rma[3]),
                    "actual_bom_key": actual_bom_key,
                }
            )
            connection.execute(
                "INSERT INTO inventory_attention_projection("
                "attention_id,target_kind,target_id,attention_kind,severity,"
                "input_fingerprint,last_command_id"
                ") VALUES (?,'rma',?,'receipt_bom_mismatch','warning',?,?)",
                (attention_id, rma_id, attention_fingerprint, command_id),
            )

        return {
            "spare_part_unit_id": spare_part_unit_id,
            "registered_event_id": registered_event_id,
            "received_event_id": received_event_id,
            "direct_relationship_id": direct_relationship_id,
            "logistics_event_id": logistics_event_id,
            "participant_refs": participant_refs,
            "rma_revision": rma_revision,
            "unit_revision": 2,
        }

    @staticmethod
    def locate_participant(connection: Any, participant_id: str):
        specs = (
            (
                "rma",
                "logistics_rma_participants",
                "logistics_rma_participant_id",
            ),
            (
                "spare_part_unit",
                "logistics_spare_unit_participants",
                "logistics_spare_participant_id",
            ),
            (
                "device_part_unit",
                "logistics_device_part_participants",
                "logistics_device_participant_id",
            ),
        )
        found: list[tuple[str, str, str, int]] = []
        for kind, table, id_column in specs:
            row = connection.execute(
                f"SELECT logistics_event_id,active FROM {table} WHERE {id_column}=?",
                (participant_id,),
            ).fetchone()
            if row is not None:
                found.append((kind, table, str(row[0]), int(row[1])))
        if len(found) > 1:
            raise IntegrityFailure("Logistics participant identity collides across types")
        return None if not found else found[0]

    @classmethod
    def close_participant(
        cls,
        connection: Any,
        *,
        participant_id: str,
        reason_code: str,
        command_id: str,
    ) -> tuple[str, str]:
        located = cls.locate_participant(connection, participant_id)
        if located is None or located[3] != 1:
            raise SomaError(
                "CORRECTION_TARGET_INVALID",
                "Logistics participant is not current-active",
            )
        kind, table, event_id, _active = located
        id_column = {
            "rma": "logistics_rma_participant_id",
            "spare_part_unit": "logistics_spare_participant_id",
            "device_part_unit": "logistics_device_participant_id",
        }[kind]
        updated = connection.execute(
            f"UPDATE {table} SET active=0,closed_command_id=?,close_reason=? "
            f"WHERE {id_column}=? AND active=1",
            (command_id, reason_code, participant_id),
        )
        if updated.rowcount != 1:
            raise SomaError("INV_STALE", "Logistics participant changed during correction")
        return kind, event_id


    @classmethod
    def correct_participant_relationship(
        cls,
        connection: Any,
        *,
        participant_id: str,
        replacement_kind: str | None,
        replacement_id: str | None,
        reason_code: str,
        command_id: str,
    ) -> tuple[str, str, str | None]:
        if (replacement_kind is None) != (replacement_id is None):
            raise SomaError(
                "CORRECTION_TARGET_INVALID",
                "Logistics participant replacement kind/id must both be null or both present",
            )
        if replacement_kind is not None and replacement_kind not in {
            "rma",
            "spare_part_unit",
            "device_part_unit",
        }:
            raise SomaError(
                "CORRECTION_TARGET_INVALID",
                "Logistics participant replacement kind is invalid",
            )

        located = cls.locate_participant(connection, participant_id)
        if located is None or located[3] != 1:
            raise SomaError(
                "CORRECTION_TARGET_INVALID",
                "Logistics participant is not current-active",
            )
        _old_kind, _table, event_id, _active = located

        if replacement_kind == "rma":
            assert replacement_id is not None
            cls.require_participants(
                connection,
                rma_ids=(replacement_id,),
                spare_part_unit_ids=(),
                device_part_unit_ids=(),
            )
            table = "logistics_rma_participants"
            id_column = "logistics_rma_participant_id"
            target_column = "rma_id"
        elif replacement_kind == "spare_part_unit":
            assert replacement_id is not None
            cls.require_participants(
                connection,
                rma_ids=(),
                spare_part_unit_ids=(replacement_id,),
                device_part_unit_ids=(),
            )
            table = "logistics_spare_unit_participants"
            id_column = "logistics_spare_participant_id"
            target_column = "spare_part_unit_id"
        elif replacement_kind == "device_part_unit":
            assert replacement_id is not None
            cls.require_participants(
                connection,
                rma_ids=(),
                spare_part_unit_ids=(),
                device_part_unit_ids=(replacement_id,),
            )
            table = "logistics_device_part_participants"
            id_column = "logistics_device_participant_id"
            target_column = "device_part_unit_id"
        else:
            table = id_column = target_column = ""

        if replacement_kind is not None:
            assert replacement_id is not None
            conflict = connection.execute(
                f"SELECT 1 FROM {table} WHERE logistics_event_id=? "
                f"AND {target_column}=? AND active=1 LIMIT 1",
                (event_id, replacement_id),
            ).fetchone()
            if conflict is not None:
                raise SomaError(
                    "CORRECTION_TARGET_INVALID",
                    "Replacement logistics participant is already active on the event",
                )

        cls.close_participant(
            connection,
            participant_id=participant_id,
            reason_code=reason_code,
            command_id=command_id,
        )

        replacement_participant_id: str | None = None
        if replacement_kind is not None:
            assert replacement_id is not None
            replacement_participant_id = new_uuid4()
            connection.execute(
                f"INSERT INTO {table}("
                f"{id_column},logistics_event_id,{target_column},active,"
                "opened_command_id,closed_command_id,close_reason"
                ") VALUES (?,?,?,1,?,NULL,NULL)",
                (
                    replacement_participant_id,
                    event_id,
                    replacement_id,
                    command_id,
                ),
            )
        return event_id, participant_id, replacement_participant_id


__all__ = ["InventoryLogisticsRepository"]
