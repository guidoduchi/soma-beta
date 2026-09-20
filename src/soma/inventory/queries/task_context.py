from __future__ import annotations

from typing import Any

from soma.foundation.errors import IntegrityFailure
from soma.foundation.identifiers import require_uuid4
from soma.foundation.persistence.connections import ConnectionFactory
from soma.foundation.persistence.uow import ReadSnapshot
from soma.objectives_tasks.queries.tasks import TaskOperationalEvidenceReader


class TaskInventoryContextQueryService:
    """Read-only LLD-07 projection of Inventory facts around one LLD-05 Task."""

    def __init__(self, connection_factory: ConnectionFactory) -> None:
        self._factory = connection_factory

    @staticmethod
    def _project(reader: Any, task_id: str) -> dict[str, object]:
        canonical = require_uuid4(task_id)
        execution = TaskOperationalEvidenceReader.task_execution(reader, canonical)
        outcome = TaskOperationalEvidenceReader.task_outcome(reader, canonical)
        objective = TaskOperationalEvidenceReader.objective_context(reader, canonical)
        operational_fingerprint = TaskOperationalEvidenceReader.review_fingerprint(
            reader,
            canonical,
        )

        active_allocations = reader.execute(
            "SELECT allocation_id,spare_part_unit_id,spare_need_id,revision,last_event_id "
            "FROM task_unit_allocation_current WHERE task_id=? "
            "ORDER BY allocation_id",
            (canonical,),
        ).fetchall()
        allocation_history = reader.execute(
            "SELECT allocation_event_id,allocation_id,spare_part_unit_id,spare_need_id,"
            "event_kind,prior_task_id,reason_code,effective_at_utc,target_event_id,recorded_at_utc "
            "FROM task_unit_allocation_events WHERE task_id=? "
            "ORDER BY recorded_at_utc,allocation_event_id",
            (canonical,),
        ).fetchall()

        consequence_rows = reader.execute(
            "SELECT c.physical_consequence_id,c.task_review_fingerprint,"
            "c.target_device_part_unit_id,c.rma_id,p.physical_disposition,"
            "p.installed_spare_part_unit_id,p.removed_device_part_unit_id,"
            "p.inbound_spare_part_unit_id,p.parent_dismantled_unit_id,p.revision,"
            "p.input_fingerprint,p.last_event_id "
            "FROM inventory_physical_consequences c "
            "JOIN physical_consequence_current p "
            "ON p.physical_consequence_id=c.physical_consequence_id "
            "WHERE c.task_id=? ORDER BY c.created_at_utc,c.physical_consequence_id",
            (canonical,),
        ).fetchall()

        consequences: list[dict[str, object]] = []
        for row in consequence_rows:
            consequence_id = require_uuid4(str(row[0]))
            stored_fingerprint = str(row[1])
            if len(stored_fingerprint) != 64:
                raise IntegrityFailure("Inventory physical consequence Task fingerprint is invalid")
            obligation = reader.execute(
                "SELECT rma_id,obligation_state,device_part_unit_id,spare_part_unit_id,revision,"
                "last_event_id FROM rma_return_obligation_current "
                "WHERE physical_consequence_id=? ORDER BY rma_id",
                (consequence_id,),
            ).fetchall()
            consequences.append(
                {
                    "physical_consequence_id": consequence_id,
                    "task_review_fingerprint": stored_fingerprint,
                    "requires_rereview": stored_fingerprint != operational_fingerprint,
                    "target_device_part_unit_id": None if row[2] is None else str(row[2]),
                    "rma_id": None if row[3] is None else str(row[3]),
                    "physical_disposition": str(row[4]),
                    "installed_spare_part_unit_id": None if row[5] is None else str(row[5]),
                    "removed_device_part_unit_id": None if row[6] is None else str(row[6]),
                    "inbound_spare_part_unit_id": None if row[7] is None else str(row[7]),
                    "parent_dismantled_unit_id": None if row[8] is None else str(row[8]),
                    "revision": int(row[9]),
                    "input_fingerprint": str(row[10]),
                    "last_event_id": str(row[11]),
                    "return_obligations": [
                        {
                            "rma_id": str(item[0]),
                            "obligation_state": str(item[1]),
                            "device_part_unit_id": None
                            if item[2] is None
                            else str(item[2]),
                            "spare_part_unit_id": None
                            if item[3] is None
                            else str(item[3]),
                            "revision": int(item[4]),
                            "last_event_id": None
                            if item[5] is None
                            else str(item[5]),
                        }
                        for item in obligation
                    ],
                }
            )

        need_ids = sorted(
            {
                str(row[2])
                for row in active_allocations
                if row[2] is not None
            }
            | {
                str(row[3])
                for row in allocation_history
                if row[3] is not None
            }
        )
        needs: list[dict[str, object]] = []
        for need_id in need_ids:
            row = reader.execute(
                "SELECT n.service_request_id,n.bom_code,p.lifecycle_state,"
                "p.planned_quantity,p.contributor_count,p.revision "
                "FROM spare_needs n JOIN spare_need_current_projection p "
                "ON p.spare_need_id=n.spare_need_id WHERE n.spare_need_id=?",
                (need_id,),
            ).fetchone()
            if row is None:
                raise IntegrityFailure("Task allocation references missing Spare Need")
            needs.append(
                {
                    "spare_need_id": need_id,
                    "service_request_id": str(row[0]),
                    "bom_code": str(row[1]),
                    "lifecycle_state": str(row[2]),
                    "planned_quantity": int(row[3]),
                    "contributor_count": int(row[4]),
                    "revision": int(row[5]),
                }
            )

        return {
            "task_id": canonical,
            "task_operational": {
                "execution": execution.to_payload(),
                "outcome": None if outcome is None else outcome.to_payload(),
                "objective_context": None
                if objective is None
                else objective.to_payload(),
                "review_fingerprint": operational_fingerprint,
            },
            "allocations": {
                "active": [
                    {
                        "allocation_id": str(row[0]),
                        "spare_part_unit_id": str(row[1]),
                        "spare_need_id": None if row[2] is None else str(row[2]),
                        "revision": int(row[3]),
                        "last_event_id": str(row[4]),
                    }
                    for row in active_allocations
                ],
                "history": [
                    {
                        "allocation_event_id": str(row[0]),
                        "allocation_id": str(row[1]),
                        "spare_part_unit_id": str(row[2]),
                        "spare_need_id": None if row[3] is None else str(row[3]),
                        "event_kind": str(row[4]),
                        "prior_task_id": None if row[5] is None else str(row[5]),
                        "reason_code": None if row[6] is None else str(row[6]),
                        "effective_at_utc": None if row[7] is None else int(row[7]),
                        "target_event_id": None if row[8] is None else str(row[8]),
                        "recorded_at_utc": int(row[9]),
                    }
                    for row in allocation_history
                ],
            },
            "needs": needs,
            "physical_consequences": consequences,
            "open_return_obligations": [
                obligation
                for consequence in consequences
                for obligation in consequence["return_obligations"]
                if obligation["obligation_state"] == "open"
            ],
        }

    def get(self, task_id: str) -> dict[str, object]:
        with ReadSnapshot(self._factory) as snapshot:
            return self._project(snapshot.connection, task_id)


__all__ = ["TaskInventoryContextQueryService"]
