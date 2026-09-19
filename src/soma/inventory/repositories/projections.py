from __future__ import annotations

from typing import Any

from soma.foundation.errors import IntegrityFailure, SomaError
from soma.foundation.identifiers import new_uuid4, utc_epoch_seconds
from soma.foundation.strict_json import sha256_canonical_json

from ..domain.consequences import ReturnSelection
from .rmas import InventoryRmasRepository
from .units import InventoryUnitsRepository


class InventoryProjectionsRepository:
    def __init__(self) -> None:
        self._rmas = InventoryRmasRepository()
        self._units = InventoryUnitsRepository()

    @staticmethod
    def require_no_current_task_consequence(connection: Any, task_id: str) -> None:
        if connection.execute(
            "SELECT 1 FROM inventory_physical_consequences c "
            "JOIN physical_consequence_current p "
            "ON p.physical_consequence_id=c.physical_consequence_id "
            "WHERE c.task_id=? LIMIT 1",
            (task_id,),
        ).fetchone() is not None:
            raise SomaError(
                "CORRECTION_TARGET_INVALID",
                "Task already has current accepted Inventory physical consequence",
            )

    @staticmethod
    def _device_current(connection: Any, device_part_unit_id: str):
        return connection.execute(
            "SELECT u.service_request_id,p.condition_token,p.revision,p.last_event_id "
            "FROM device_part_units u JOIN device_part_current_projection p "
            "ON p.device_part_unit_id=u.device_part_unit_id "
            "WHERE u.device_part_unit_id=?",
            (device_part_unit_id,),
        ).fetchone()

    def _validate_rma_consequence(
        self,
        connection: Any,
        *,
        rma_id: str,
        target_device_part_unit_id: str | None,
        disposition: str,
        installed_spare_part_unit_id: str | None,
        removed_device_part_unit_id: str | None,
        inbound_spare_part_unit_id: str | None,
        parent_dismantled_unit_id: str | None,
        selection: ReturnSelection | None,
    ):
        rma = self._rmas.current_rma(connection, rma_id)
        if rma is None:
            raise SomaError("INV_STALE", "RMA no longer exists")
        current_target = None if rma[7] is None else str(rma[7])
        direct_inbound = None if rma[8] is None else str(rma[8])
        if target_device_part_unit_id is not None and current_target != target_device_part_unit_id:
            raise SomaError(
                "RETURN_SELECTION_INVALID",
                "physical consequence target does not match current RMA assignment",
            )
        if disposition in {
            "installed_used",
            "unused",
            "inbound_faulty",
            "incompatible",
            "dismantled",
        } and direct_inbound is None:
            raise SomaError(
                "RETURN_SELECTION_INVALID",
                "RMA physical consequence requires accepted direct inbound unit",
            )
        if disposition == "installed_used" and installed_spare_part_unit_id != direct_inbound:
            raise SomaError(
                "RETURN_SELECTION_INVALID",
                "installed RMA spare must be the accepted direct inbound unit",
            )
        if disposition in {"unused", "inbound_faulty", "incompatible"} and (
            inbound_spare_part_unit_id != direct_inbound
        ):
            raise SomaError(
                "RETURN_SELECTION_INVALID",
                "return candidate must be the accepted direct inbound unit",
            )
        if disposition == "dismantled" and parent_dismantled_unit_id != direct_inbound:
            raise SomaError(
                "RETURN_SELECTION_INVALID",
                "dismantled return candidate must be the direct inbound parent unit",
            )
        if removed_device_part_unit_id is not None and current_target is not None and (
            removed_device_part_unit_id != current_target
        ):
            raise SomaError(
                "RETURN_SELECTION_INVALID",
                "removed Device Part does not match current RMA target",
            )
        obligation = connection.execute(
            "SELECT obligation_state,revision FROM rma_return_obligation_current WHERE rma_id=?",
            (rma_id,),
        ).fetchone()
        if obligation is None:
            raise IntegrityFailure("RMA is missing return-obligation projection")
        if str(obligation[0]) != "not_established":
            raise SomaError(
                "RETURN_SELECTION_INVALID",
                "RMA return obligation is already established",
            )
        if selection is None and disposition != "no_physical_change":
            raise SomaError("RETURN_SELECTION_INVALID", "RMA consequence lacks return selection")
        return rma, obligation

    @staticmethod
    def _require_spare_unit(connection: Any, unit_id: str):
        row = connection.execute(
            "SELECT condition_token,disposition_token,location_kind,location_ref_id,"
            "custody_text,active_task_allocation_id,revision "
            "FROM spare_part_current_projection WHERE spare_part_unit_id=?",
            (unit_id,),
        ).fetchone()
        if row is None:
            raise SomaError("RETURN_SELECTION_INVALID", "Spare Part Unit does not exist")
        return row

    @classmethod
    def _mark_device_removed(
        cls,
        connection: Any,
        *,
        device_part_unit_id: str,
        effective_at_utc: int | None,
        command_id: str,
    ) -> tuple[str, int]:
        current = cls._device_current(connection, device_part_unit_id)
        if current is None:
            raise SomaError("RETURN_SELECTION_INVALID", "Device Part Unit does not exist")
        event_id = new_uuid4()
        now = utc_epoch_seconds()
        connection.execute(
            "INSERT INTO device_part_lifecycle_events("
            "device_part_event_id,device_part_unit_id,event_kind,condition_token,effective_at_utc,"
            "target_event_id,reason_code,evidence_kind,evidence_id,recorded_at_utc,command_id"
            ") VALUES (?,?,'removed','removed',?,NULL,NULL,NULL,NULL,?,?)",
            (event_id, device_part_unit_id, effective_at_utc, now, command_id),
        )
        revision = int(current[2]) + 1
        fingerprint = sha256_canonical_json(
            {
                "schema": "SOMA_DEVICE_PART_CURRENT_V1",
                "device_part_unit_id": device_part_unit_id,
                "condition_token": "removed",
                "last_event_id": event_id,
            }
        )
        changed = connection.execute(
            "UPDATE device_part_current_projection SET condition_token='removed',revision=?,"
            "input_fingerprint=?,last_event_id=?,last_command_id=? "
            "WHERE device_part_unit_id=? AND revision=?",
            (
                revision,
                fingerprint,
                event_id,
                command_id,
                device_part_unit_id,
                int(current[2]),
            ),
        )
        if changed.rowcount != 1:
            raise SomaError("INV_STALE", "Device Part changed during consequence")
        return event_id, revision

    def _mark_spare_disposition(
        self,
        connection: Any,
        *,
        spare_part_unit_id: str,
        disposition_token: str,
        event_kind: str,
        task_id: str,
        effective_at_utc: int | None,
        command_id: str,
    ) -> tuple[str, int]:
        unit = self._require_spare_unit(connection, spare_part_unit_id)
        allocation_id = None if unit[5] is None else str(unit[5])
        if allocation_id is not None:
            allocation = connection.execute(
                "SELECT task_id,revision FROM task_unit_allocation_current WHERE allocation_id=?",
                (allocation_id,),
            ).fetchone()
            if allocation is None or str(allocation[0]) != task_id:
                raise SomaError(
                    "RETURN_SELECTION_INVALID",
                    "installed unit is reserved to a different Task",
                )
            self._units.release_reservation(
                connection,
                allocation_id=allocation_id,
                expected_allocation_revision=int(allocation[1]),
                reason_code="accepted_physical_consequence",
                command_id=command_id,
            )
            unit = self._require_spare_unit(connection, spare_part_unit_id)
        now = utc_epoch_seconds()
        event_id = new_uuid4()
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
                str(unit[0]),
                disposition_token,
                None if unit[2] is None else str(unit[2]),
                None if unit[3] is None else str(unit[3]),
                None if unit[4] is None else str(unit[4]),
                effective_at_utc,
                now,
                command_id,
            ),
        )
        revision = int(unit[6]) + 1
        fingerprint = self._units.projection_fingerprint(
            spare_part_unit_id=spare_part_unit_id,
            condition_token=str(unit[0]),
            disposition_token=disposition_token,
            location_kind=None if unit[2] is None else str(unit[2]),
            location_ref_id=None if unit[3] is None else str(unit[3]),
            custody_text=None if unit[4] is None else str(unit[4]),
            active_task_allocation_id=None,
        )
        changed = connection.execute(
            "UPDATE spare_part_current_projection SET disposition_token=?,"
            "active_task_allocation_id=NULL,revision=?,input_fingerprint=?,last_command_id=? "
            "WHERE spare_part_unit_id=? AND revision=?",
            (
                disposition_token,
                revision,
                fingerprint,
                command_id,
                spare_part_unit_id,
                int(unit[6]),
            ),
        )
        if changed.rowcount != 1:
            raise SomaError("INV_STALE", "Spare Part Unit changed during consequence")
        return event_id, revision

    def accept_physical_consequence(
        self,
        connection: Any,
        *,
        physical_consequence_id: str,
        task_id: str,
        task_review_fingerprint: str,
        target_device_part_unit_id: str | None,
        rma_id: str | None,
        disposition: str,
        installed_spare_part_unit_id: str | None,
        removed_device_part_unit_id: str | None,
        inbound_spare_part_unit_id: str | None,
        parent_dismantled_unit_id: str | None,
        effective_at_utc: int | None,
        selection: ReturnSelection | None,
        command_id: str,
    ) -> dict[str, object]:
        self.require_no_current_task_consequence(connection, task_id)
        rma = obligation = None
        if rma_id is not None:
            rma, obligation = self._validate_rma_consequence(
                connection,
                rma_id=rma_id,
                target_device_part_unit_id=target_device_part_unit_id,
                disposition=disposition,
                installed_spare_part_unit_id=installed_spare_part_unit_id,
                removed_device_part_unit_id=removed_device_part_unit_id,
                inbound_spare_part_unit_id=inbound_spare_part_unit_id,
                parent_dismantled_unit_id=parent_dismantled_unit_id,
                selection=selection,
            )
        for unit_id in (
            installed_spare_part_unit_id,
            inbound_spare_part_unit_id,
            parent_dismantled_unit_id,
        ):
            if unit_id is not None:
                self._require_spare_unit(connection, unit_id)
        if removed_device_part_unit_id is not None and self._device_current(
            connection, removed_device_part_unit_id
        ) is None:
            raise SomaError("RETURN_SELECTION_INVALID", "removed Device Part does not exist")

        now = utc_epoch_seconds()
        event_id = new_uuid4()
        connection.execute(
            "INSERT INTO inventory_physical_consequences("
            "physical_consequence_id,task_id,task_review_fingerprint,"
            "target_device_part_unit_id,rma_id,created_at_utc,created_command_id"
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
        connection.execute(
            "INSERT INTO physical_consequence_events("
            "consequence_event_id,physical_consequence_id,event_kind,physical_disposition,"
            "installed_spare_part_unit_id,removed_device_part_unit_id,"
            "inbound_spare_part_unit_id,parent_dismantled_unit_id,effective_at_utc,"
            "target_event_id,reason_code,recorded_at_utc,command_id"
            ") VALUES (?,?,'accept',?,?,?,?,?,?,NULL,NULL,?,?)",
            (
                event_id,
                physical_consequence_id,
                disposition,
                installed_spare_part_unit_id,
                removed_device_part_unit_id,
                inbound_spare_part_unit_id,
                parent_dismantled_unit_id,
                effective_at_utc,
                now,
                command_id,
            ),
        )

        unit_refs: list[tuple[str, str, int]] = []
        if installed_spare_part_unit_id is not None:
            install_event, unit_revision = self._mark_spare_disposition(
                connection,
                spare_part_unit_id=installed_spare_part_unit_id,
                disposition_token="installed",
                event_kind="installed",
                task_id=task_id,
                effective_at_utc=effective_at_utc,
                command_id=command_id,
            )
            unit_refs.append(("spare_part_unit", install_event, unit_revision))
        if removed_device_part_unit_id is not None:
            remove_event, device_revision = self._mark_device_removed(
                connection,
                device_part_unit_id=removed_device_part_unit_id,
                effective_at_utc=effective_at_utc,
                command_id=command_id,
            )
            unit_refs.append(("device_part_unit", remove_event, device_revision))
        if parent_dismantled_unit_id is not None:
            dismantle_event, unit_revision = self._mark_spare_disposition(
                connection,
                spare_part_unit_id=parent_dismantled_unit_id,
                disposition_token="dismantled",
                event_kind="dismantled",
                task_id=task_id,
                effective_at_utc=effective_at_utc,
                command_id=command_id,
            )
            unit_refs.append(("spare_part_unit", dismantle_event, unit_revision))

        current_fingerprint = sha256_canonical_json(
            {
                "schema": "SOMA_PHYSICAL_CONSEQUENCE_CURRENT_V1",
                "physical_consequence_id": physical_consequence_id,
                "task_review_fingerprint": task_review_fingerprint,
                "physical_disposition": disposition,
                "installed_spare_part_unit_id": installed_spare_part_unit_id,
                "removed_device_part_unit_id": removed_device_part_unit_id,
                "inbound_spare_part_unit_id": inbound_spare_part_unit_id,
                "parent_dismantled_unit_id": parent_dismantled_unit_id,
                "last_event_id": event_id,
            }
        )
        connection.execute(
            "INSERT INTO physical_consequence_current("
            "physical_consequence_id,task_review_fingerprint,physical_disposition,"
            "installed_spare_part_unit_id,removed_device_part_unit_id,"
            "inbound_spare_part_unit_id,parent_dismantled_unit_id,revision,"
            "input_fingerprint,last_event_id,last_command_id"
            ") VALUES (?,?,?,?,?,?,?,1,?,?,?)",
            (
                physical_consequence_id,
                task_review_fingerprint,
                disposition,
                installed_spare_part_unit_id,
                removed_device_part_unit_id,
                inbound_spare_part_unit_id,
                parent_dismantled_unit_id,
                current_fingerprint,
                event_id,
                command_id,
            ),
        )

        return_event_id = None
        obligation_revision = None
        if rma_id is not None and selection is not None:
            assert rma is not None and obligation is not None
            return_event_id = new_uuid4()
            device_return = selection.unit_id if selection.unit_kind == "device_part_unit" else None
            spare_return = selection.unit_id if selection.unit_kind == "spare_part_unit" else None
            connection.execute(
                "INSERT INTO rma_return_selection_events("
                "return_selection_event_id,rma_id,physical_consequence_id,event_kind,"
                "device_part_unit_id,spare_part_unit_id,reason_code,effective_at_utc,"
                "target_event_id,recorded_at_utc,command_id"
                ") VALUES (?,?,?,'select',?,?,NULL,?,NULL,?,?)",
                (
                    return_event_id,
                    rma_id,
                    physical_consequence_id,
                    device_return,
                    spare_return,
                    effective_at_utc,
                    now,
                    command_id,
                ),
            )
            obligation_revision = int(obligation[1]) + 1
            changed = connection.execute(
                "UPDATE rma_return_obligation_current SET obligation_state='open',"
                "device_part_unit_id=?,spare_part_unit_id=?,physical_consequence_id=?,"
                "revision=?,last_event_id=?,last_command_id=? "
                "WHERE rma_id=? AND obligation_state='not_established' AND revision=?",
                (
                    device_return,
                    spare_return,
                    physical_consequence_id,
                    obligation_revision,
                    return_event_id,
                    command_id,
                    rma_id,
                    int(obligation[1]),
                ),
            )
            if changed.rowcount != 1:
                raise SomaError("INV_STALE", "RMA return obligation changed during consequence")
            rma_revision = int(rma[9]) + 1
            rma_fingerprint = sha256_canonical_json(
                {
                    "schema": "SOMA_RMA_LIFECYCLE_V1",
                    "rma_id": rma_id,
                    "state": "return_open",
                    "current_target_device_part_unit_id": (
                        None if rma[7] is None else str(rma[7])
                    ),
                    "direct_inbound_spare_part_unit_id": (
                        None if rma[8] is None else str(rma[8])
                    ),
                    "return_device_part_unit_id": device_return,
                    "return_spare_part_unit_id": spare_return,
                    "return_obligation_open": 1,
                    "active_fault_tag_membership_id": None,
                    "current_c10": str(rma[5]),
                }
            )
            updated = connection.execute(
                "UPDATE rma_lifecycle_projection SET state='return_open',"
                "return_device_part_unit_id=?,return_spare_part_unit_id=?,"
                "return_obligation_open=1,revision=?,input_fingerprint=?,last_command_id=? "
                "WHERE rma_id=? AND revision=?",
                (
                    device_return,
                    spare_return,
                    rma_revision,
                    rma_fingerprint,
                    command_id,
                    rma_id,
                    int(rma[9]),
                ),
            )
            if updated.rowcount != 1:
                raise SomaError("INV_STALE", "RMA lifecycle changed during return selection")

        return {
            "consequence_event_id": event_id,
            "consequence_revision": 1,
            "return_selection_event_id": return_event_id,
            "obligation_revision": obligation_revision,
            "unit_refs": tuple(unit_refs),
        }


__all__ = ["InventoryProjectionsRepository"]
