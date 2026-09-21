from __future__ import annotations

from soma.foundation.identifiers import require_uuid4
from soma.foundation.persistence.connections import ConnectionFactory
from soma.foundation.persistence.uow import ReadSnapshot


class TaskInventoryContextQuery:
    def __init__(self, connection_factory: ConnectionFactory) -> None:
        self._factory = connection_factory

    def get(self, task_id: str) -> dict[str, object]:
        identity = require_uuid4(task_id)
        with ReadSnapshot(self._factory) as snapshot:
            allocations = snapshot.connection.execute(
                "SELECT e.allocation_event_id,e.allocation_id,e.spare_part_unit_id,"
                "e.spare_need_id,e.event_kind,e.reason_code,e.recorded_at_utc "
                "FROM task_unit_allocation_events e WHERE e.task_id=? "
                "ORDER BY e.recorded_at_utc,e.allocation_event_id",
                (identity,),
            ).fetchall()
            consequences = snapshot.connection.execute(
                "SELECT i.physical_consequence_id,i.task_review_fingerprint,i.rma_id,"
                "c.physical_disposition,c.installed_spare_part_unit_id,"
                "c.removed_device_part_unit_id,c.inbound_spare_part_unit_id,"
                "c.parent_dismantled_unit_id,c.revision,c.input_fingerprint "
                "FROM inventory_physical_consequences i JOIN physical_consequence_current c "
                "ON c.physical_consequence_id=i.physical_consequence_id WHERE i.task_id=? "
                "ORDER BY i.physical_consequence_id",
                (identity,),
            ).fetchall()
            fulfillments = snapshot.connection.execute(
                "SELECT local_fulfillment_event_id,spare_need_id,spare_part_unit_id,"
                "event_kind,reason_code,recorded_at_utc FROM local_need_fulfillment_events "
                "WHERE task_id=? ORDER BY recorded_at_utc,local_fulfillment_event_id",
                (identity,),
            ).fetchall()
            obligation_rows = snapshot.connection.execute(
                "SELECT o.rma_id,o.obligation_state,o.device_part_unit_id,o.spare_part_unit_id,"
                "o.physical_consequence_id,o.revision FROM rma_return_obligation_current o "
                "JOIN inventory_physical_consequences i "
                "ON i.physical_consequence_id=o.physical_consequence_id "
                "WHERE i.task_id=? ORDER BY o.rma_id",
                (identity,),
            ).fetchall()
            return {
                "task_id": identity,
                "allocation_history": [
                    {
                        "allocation_event_id": str(x[0]),
                        "allocation_id": str(x[1]),
                        "spare_part_unit_id": str(x[2]),
                        "spare_need_id": None if x[3] is None else str(x[3]),
                        "event_kind": str(x[4]),
                        "reason_code": None if x[5] is None else str(x[5]),
                        "recorded_at_utc": int(x[6]),
                    }
                    for x in allocations
                ],
                "local_fulfillment_history": [
                    {
                        "event_id": str(x[0]),
                        "spare_need_id": str(x[1]),
                        "spare_part_unit_id": str(x[2]),
                        "event_kind": str(x[3]),
                        "reason_code": None if x[4] is None else str(x[4]),
                        "recorded_at_utc": int(x[5]),
                    }
                    for x in fulfillments
                ],
                "physical_consequences": [
                    {
                        "physical_consequence_id": str(x[0]),
                        "task_review_fingerprint": str(x[1]),
                        "rma_id": None if x[2] is None else str(x[2]),
                        "physical_disposition": str(x[3]),
                        "installed_spare_part_unit_id": None if x[4] is None else str(x[4]),
                        "removed_device_part_unit_id": None if x[5] is None else str(x[5]),
                        "inbound_spare_part_unit_id": None if x[6] is None else str(x[6]),
                        "parent_dismantled_unit_id": None if x[7] is None else str(x[7]),
                        "revision": int(x[8]),
                        "input_fingerprint": str(x[9]),
                    }
                    for x in consequences
                ],
                "return_obligations": [
                    {
                        "rma_id": str(x[0]),
                        "state": str(x[1]),
                        "device_part_unit_id": None if x[2] is None else str(x[2]),
                        "spare_part_unit_id": None if x[3] is None else str(x[3]),
                        "physical_consequence_id": str(x[4]),
                        "revision": int(x[5]),
                    }
                    for x in obligation_rows
                ],
            }


__all__ = ["TaskInventoryContextQuery"]
