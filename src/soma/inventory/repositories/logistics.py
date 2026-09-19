from __future__ import annotations

from typing import Any

from soma.foundation.errors import IntegrityFailure, SomaError
from soma.foundation.identifiers import new_uuid4, utc_epoch_seconds
from soma.foundation.strict_json import sha256_canonical_json

from .rmas import InventoryRmasRepository
from .units import InventoryUnitsRepository


class InventoryLogisticsRepository:
    def __init__(self) -> None:
        self._rmas = InventoryRmasRepository()
        self._units = InventoryUnitsRepository()

    @staticmethod
    def _reference_exists(connection: Any, table: str, column: str, identity: str) -> bool:
        row = connection.execute(
            f"SELECT 1 FROM {table} WHERE {column}=?",
            (identity,),
        ).fetchone()
        return row is not None

    def require_receipt_eligible(self, connection: Any, rma_id: str):
        row = self._rmas.current_rma(connection, rma_id)
        if row is None:
            raise SomaError("INV_STALE", "RMA no longer exists")
        if connection.execute(
            "SELECT 1 FROM rma_direct_inbound_units WHERE rma_id=?",
            (rma_id,),
        ).fetchone() is not None or row[8] is not None:
            raise SomaError("RMA_INBOUND_EXISTS", "RMA already has direct inbound physical unit")
        return row

    @staticmethod
    def _snapshot_reference_context(
        connection: Any,
        *,
        dispatch_location_id: str | None,
        receiver_contact_id: str | None,
    ) -> tuple[str | None, str | None, str | None]:
        location_name = None
        location_address = None
        if dispatch_location_id is not None:
            row = connection.execute(
                "SELECT name,address_mode,standalone_address_text,lifecycle_state "
                "FROM dispatch_locations WHERE dispatch_location_id=?",
                (dispatch_location_id,),
            ).fetchone()
            if row is None or str(row[3]) != "active":
                raise SomaError("INV_STALE", "Receipt Dispatch Location is unavailable")
            location_name = str(row[0])
            if row[2] is not None:
                location_address = str(row[2])
            elif str(row[1]) == "site_derived":
                raise SomaError(
                    "DEPENDENCY_INDETERMINATE",
                    "Site-derived receipt location address cannot be snapshotted",
                )
        receiver_json = None
        if receiver_contact_id is not None:
            row = connection.execute(
                "SELECT name,revision,lifecycle_state FROM contacts WHERE contact_id=?",
                (receiver_contact_id,),
            ).fetchone()
            if row is None or str(row[2]) != "active":
                raise SomaError("INV_STALE", "Receipt receiver Contact is unavailable")
            receiver_json = __import__("json").dumps(
                {
                    "contact_id": receiver_contact_id,
                    "contact_revision_at_event": int(row[1]),
                    "display_name_snapshot": str(row[0]),
                },
                sort_keys=True,
                separators=(",", ":"),
                ensure_ascii=False,
            )
        return location_name, location_address, receiver_json

    def record_rma_inbound_receipt(
        self,
        connection: Any,
        *,
        rma_id: str,
        spare_part_unit_id: str,
        bom_code: str,
        bom_key: str,
        manufacturer_serial: str | None,
        serial_key: str | None,
        condition_token: str,
        disposition_token: str,
        effective_at_utc: int | None,
        dispatch_location_id: str | None,
        receiver_contact_id: str | None,
        location_kind: str | None,
        location_ref_id: str | None,
        custody_text: str | None,
        evidence_kind: str | None,
        evidence_id: str | None,
        command_id: str,
    ) -> tuple[str, str, str, int, int]:
        rma = self.require_receipt_eligible(connection, rma_id)
        if dispatch_location_id is not None and not self._reference_exists(
            connection, "dispatch_locations", "dispatch_location_id", dispatch_location_id
        ):
            raise SomaError("INV_STALE", "Receipt Dispatch Location no longer exists")
        if receiver_contact_id is not None and not self._reference_exists(
            connection, "contacts", "contact_id", receiver_contact_id
        ):
            raise SomaError("INV_STALE", "Receipt receiver Contact no longer exists")
        location_name, location_address, receiver_json = self._snapshot_reference_context(
            connection,
            dispatch_location_id=dispatch_location_id,
            receiver_contact_id=receiver_contact_id,
        )
        unit_event_id, unit_revision = self._units.insert_spare_part_unit(
            connection,
            spare_part_unit_id=spare_part_unit_id,
            local_tracking_sequence=None,
            local_tracking_id=None,
            bom_code=bom_code,
            bom_key=bom_key,
            manufacturer_serial=manufacturer_serial,
            serial_key=serial_key,
            creation_origin="direct_rma_receipt",
            origin_rma_id=rma_id,
            condition_token=condition_token,
            disposition_token=disposition_token,
            location_kind=location_kind,
            location_ref_id=location_ref_id,
            custody_text=custody_text,
            effective_at_utc=effective_at_utc,
            command_id=command_id,
        )
        now = utc_epoch_seconds()
        receipt_unit_event_id = new_uuid4()
        connection.execute(
            "INSERT INTO spare_part_lifecycle_events("
            "unit_event_id,spare_part_unit_id,event_kind,condition_token,disposition_token,"
            "location_kind,location_ref_id,custody_text,effective_at_utc,target_event_id,"
            "reason_code,evidence_kind,evidence_id,recorded_at_utc,command_id"
            ") VALUES (?,?,'received',?,?,?,?,?,?,NULL,NULL,?,?,?,?)",
            (
                receipt_unit_event_id,
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
        logistics_event_id = new_uuid4()
        connection.execute(
            "INSERT INTO actual_logistics_events("
            "logistics_event_id,event_kind,effective_at_utc,dispatch_location_id,"
            "location_name_snapshot,location_address_snapshot,receiver_contact_id,"
            "receiver_snapshot_json,custody_text,observed_condition,target_event_id,"
            "reason_code,evidence_kind,evidence_id,recorded_at_utc,command_id"
            ") VALUES (?,'receipt',?,?,?,?,?,?,?,?,NULL,NULL,?,?,?,?)",
            (
                logistics_event_id,
                effective_at_utc,
                dispatch_location_id,
                location_name,
                location_address,
                receiver_contact_id,
                receiver_json,
                custody_text,
                condition_token,
                evidence_kind,
                evidence_id,
                now,
                command_id,
            ),
        )
        connection.execute(
            "INSERT INTO logistics_rma_participants("
            "logistics_rma_participant_id,logistics_event_id,rma_id,active,"
            "opened_command_id,closed_command_id,close_reason"
            ") VALUES (?,?,?,1,?,NULL,NULL)",
            (new_uuid4(), logistics_event_id, rma_id, command_id),
        )
        connection.execute(
            "INSERT INTO logistics_spare_unit_participants("
            "logistics_spare_participant_id,logistics_event_id,spare_part_unit_id,active,"
            "opened_command_id,closed_command_id,close_reason"
            ") VALUES (?,?,?,1,?,NULL,NULL)",
            (new_uuid4(), logistics_event_id, spare_part_unit_id, command_id),
        )
        relationship_id = new_uuid4()
        connection.execute(
            "INSERT INTO rma_direct_inbound_units("
            "direct_inbound_relationship_id,rma_id,spare_part_unit_id,relationship_event_id,"
            "opened_command_id"
            ") VALUES (?,?,?,?,?)",
            (
                relationship_id,
                rma_id,
                spare_part_unit_id,
                logistics_event_id,
                command_id,
            ),
        )
        lifecycle_revision = int(rma[9]) + 1
        fingerprint = sha256_canonical_json(
            {
                "schema": "SOMA_RMA_LIFECYCLE_V1",
                "rma_id": rma_id,
                "state": "received",
                "current_target_device_part_unit_id": (
                    None if rma[7] is None else str(rma[7])
                ),
                "direct_inbound_spare_part_unit_id": spare_part_unit_id,
                "return_device_part_unit_id": None,
                "return_spare_part_unit_id": None,
                "return_obligation_open": 0,
                "active_fault_tag_membership_id": None,
                "current_c10": str(rma[5]),
            }
        )
        changed = connection.execute(
            "UPDATE rma_lifecycle_projection SET state='received',"
            "direct_inbound_spare_part_unit_id=?,revision=?,input_fingerprint=?,"
            "last_command_id=? WHERE rma_id=? AND revision=? "
            "AND direct_inbound_spare_part_unit_id IS NULL",
            (
                spare_part_unit_id,
                lifecycle_revision,
                fingerprint,
                command_id,
                rma_id,
                int(rma[9]),
            ),
        )
        if changed.rowcount != 1:
            raise SomaError("INV_STALE", "RMA changed during inbound receipt")
        return (
            spare_part_unit_id,
            logistics_event_id,
            receipt_unit_event_id,
            unit_revision,
            lifecycle_revision,
        )

    @staticmethod
    def _participant_table(kind: str) -> tuple[str, str, str]:
        mapping = {
            "rma": ("logistics_rma_participants", "logistics_rma_participant_id", "rma_id"),
            "spare_part_unit": (
                "logistics_spare_unit_participants",
                "logistics_spare_participant_id",
                "spare_part_unit_id",
            ),
            "device_part_unit": (
                "logistics_device_part_participants",
                "logistics_device_participant_id",
                "device_part_unit_id",
            ),
        }
        try:
            return mapping[kind]
        except KeyError as exc:
            raise SomaError("CORRECTION_TARGET_INVALID", "Unknown logistics participant kind") from exc

    @staticmethod
    def _entity_table(kind: str) -> tuple[str, str]:
        mapping = {
            "rma": ("rmas", "rma_id"),
            "spare_part_unit": ("spare_part_units", "spare_part_unit_id"),
            "device_part_unit": ("device_part_units", "device_part_unit_id"),
        }
        try:
            return mapping[kind]
        except KeyError as exc:
            raise SomaError("CORRECTION_TARGET_INVALID", "Unknown logistics participant kind") from exc

    @classmethod
    def require_participant_identity(
        cls,
        connection: Any,
        *,
        participant_kind: str,
        participant_id: str,
    ) -> None:
        table, column = cls._entity_table(participant_kind)
        if connection.execute(
            f"SELECT 1 FROM {table} WHERE {column}=?",
            (participant_id,),
        ).fetchone() is None:
            raise SomaError("INV_STALE", "Logistics participant no longer exists")

    @classmethod
    def record_actual_logistics_event(
        cls,
        connection: Any,
        *,
        event_kind: str,
        effective_at_utc: int | None,
        dispatch_location_id: str | None,
        receiver_contact_id: str | None,
        custody_text: str | None,
        observed_condition: str | None,
        participants: tuple[tuple[str, str], ...],
        evidence_kind: str | None,
        evidence_id: str | None,
        command_id: str,
    ) -> tuple[str, tuple[tuple[str, str], ...]]:
        if not participants:
            raise SomaError("CORRECTION_TARGET_INVALID", "Logistics event has no participants")
        for kind, identity in participants:
            cls.require_participant_identity(
                connection,
                participant_kind=kind,
                participant_id=identity,
            )
        location_name, location_address, receiver_json = cls._snapshot_reference_context(
            connection,
            dispatch_location_id=dispatch_location_id,
            receiver_contact_id=receiver_contact_id,
        )
        now = utc_epoch_seconds()
        event_id = new_uuid4()
        connection.execute(
            "INSERT INTO actual_logistics_events("
            "logistics_event_id,event_kind,effective_at_utc,dispatch_location_id,"
            "location_name_snapshot,location_address_snapshot,receiver_contact_id,"
            "receiver_snapshot_json,custody_text,observed_condition,target_event_id,"
            "reason_code,evidence_kind,evidence_id,recorded_at_utc,command_id"
            ") VALUES (?,?,?,?,?,?,?,?,?,?,NULL,NULL,?,?,?,?)",
            (
                event_id,
                event_kind,
                effective_at_utc,
                dispatch_location_id,
                location_name,
                location_address,
                receiver_contact_id,
                receiver_json,
                custody_text,
                observed_condition,
                evidence_kind,
                evidence_id,
                now,
                command_id,
            ),
        )
        inserted: list[tuple[str, str]] = []
        for kind, identity in participants:
            table, pk, fk = cls._participant_table(kind)
            participant_id = new_uuid4()
            connection.execute(
                f"INSERT INTO {table}("
                f"{pk},logistics_event_id,{fk},active,opened_command_id,"
                "closed_command_id,close_reason"
                ") VALUES (?,?,?,1,?,NULL,NULL)",
                (participant_id, event_id, identity, command_id),
            )
            inserted.append((kind, participant_id))
        return event_id, tuple(inserted)

    @classmethod
    def locate_participant(cls, connection: Any, participant_id: str):
        matches: list[tuple[str, str, str, str]] = []
        for kind in ("rma", "spare_part_unit", "device_part_unit"):
            table, pk, fk = cls._participant_table(kind)
            row = connection.execute(
                f"SELECT logistics_event_id,{fk},active FROM {table} WHERE {pk}=?",
                (participant_id,),
            ).fetchone()
            if row is not None:
                matches.append((kind, str(row[0]), str(row[1]), str(row[2])))
        if len(matches) != 1:
            raise SomaError(
                "CORRECTION_TARGET_INVALID",
                "Logistics participant identity is missing or ambiguous",
            )
        return matches[0]

    @classmethod
    def correct_logistics_participant(
        cls,
        connection: Any,
        *,
        participant_id: str,
        replacement_kind: str | None,
        replacement_id: str | None,
        reason_code: str,
        command_id: str,
    ) -> tuple[str, str, str | None]:
        kind, event_id, _target_id, active = cls.locate_participant(connection, participant_id)
        if active != "1":
            raise SomaError("CORRECTION_TARGET_INVALID", "Logistics participant is not active")
        table, pk, _fk = cls._participant_table(kind)
        changed = connection.execute(
            f"UPDATE {table} SET active=0,closed_command_id=?,close_reason=? "
            f"WHERE {pk}=? AND active=1",
            (command_id, reason_code, participant_id),
        )
        if changed.rowcount != 1:
            raise SomaError("INV_STALE", "Logistics participant changed during correction")
        replacement_participant_id = None
        if replacement_kind is not None or replacement_id is not None:
            if replacement_kind is None or replacement_id is None:
                raise SomaError(
                    "CORRECTION_TARGET_INVALID",
                    "Replacement logistics participant is incomplete",
                )
            cls.require_participant_identity(
                connection,
                participant_kind=replacement_kind,
                participant_id=replacement_id,
            )
            rtable, rpk, rfk = cls._participant_table(replacement_kind)
            replacement_participant_id = new_uuid4()
            connection.execute(
                f"INSERT INTO {rtable}("
                f"{rpk},logistics_event_id,{rfk},active,opened_command_id,"
                "closed_command_id,close_reason"
                ") VALUES (?,?,?,1,?,NULL,NULL)",
                (replacement_participant_id, event_id, replacement_id, command_id),
            )
        return event_id, kind, replacement_participant_id


__all__ = ["InventoryLogisticsRepository"]
