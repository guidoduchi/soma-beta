from __future__ import annotations

from soma.foundation.identifiers import new_uuid4
from soma.foundation.persistence.uow import ReadSnapshot
from soma.inventory.queries.task_context import TaskInventoryContextQuery
from soma.inventory.services.consequences_logistics import (
    InventoryConsequencesLogisticsService,
)
from soma.inventory.services.needs_stock import InventoryNeedsStockService
from soma.inventory.services.participants import InventoryTaskDependencyProvider
from soma.objectives_tasks import AcceptedTaskSchedule, TaskPlanningService
from soma.objectives_tasks.queries.grouping import ObjectiveGroupingQueryService
from soma.objectives_tasks.queries.hard_delete import TaskHardDeleteQueryService
from soma.objectives_tasks.services.objectives import ObjectiveService
from soma.objectives_tasks.services.retries import TaskRetryService
from test_inventory_consequence_replay import _reviewed_task
from test_objectives_tasks_objectives import _existing_intent


TZ = "America/Guayaquil"


def _factory(initialized_database):
    path, builder = initialized_database
    return builder(path)


def _register_unit(factory, bom: str) -> tuple[str, int]:
    result = InventoryNeedsStockService(factory).register_spare_part_unit(
        command_id=new_uuid4(),
        origin="manual_local",
        bom_code=bom,
        condition_token="new",
    )
    unit_id = next(
        ref.result_id
        for ref in result.target_refs
        if ref.result_type == "spare_part_unit"
    )
    return unit_id, result.revisions[f"spare_part_unit:{unit_id}"]


def test_t063_task_hard_delete_uses_real_inventory_consequence_provider(
    initialized_database,
) -> None:
    factory = _factory(initialized_database)
    task_id, reviewed, fingerprint = _reviewed_task(factory)
    InventoryConsequencesLogisticsService(factory).accept_inventory_physical_consequence(
        command_id=new_uuid4(),
        task_id=task_id,
        task_review_fingerprint=fingerprint,
        physical_disposition="no_physical_change",
    )

    preview = TaskHardDeleteQueryService(
        factory,
        InventoryTaskDependencyProvider(),
    ).preview(
        task_id=task_id,
        base_revision=reviewed.revision,
    )

    assert preview.inventory_status == "BLOCKED"
    assert "TASK_INVENTORY_DEPENDENCY_PRESENT" in {
        blocker.code for blocker in preview.blockers
    }


def test_t064_retry_reassigns_only_selected_planning_relation(
    initialized_database,
) -> None:
    factory = _factory(initialized_database)
    planning = TaskPlanningService(factory)
    predecessor = planning.create_local_task(
        command_id=new_uuid4(),
        local_task_name="Inventory retry predecessor",
    )
    unit_id, unit_revision = _register_unit(factory, "RETRY-BOM")

    reserved = InventoryNeedsStockService(factory).reserve_spare_part_unit_for_task(
        command_id=new_uuid4(),
        task_id=predecessor.task_id,
        spare_part_unit_id=unit_id,
        unit_revision=unit_revision,
        task_revision=predecessor.revision,
    )
    allocation_id = next(
        ref.result_id
        for ref in reserved.target_refs
        if ref.result_type == "task_unit_allocation"
    )

    retry = TaskRetryService(factory).create_local_task_retry(
        command_id=new_uuid4(),
        predecessor_task_id=predecessor.task_id,
        predecessor_task_revision=predecessor.revision,
        schedule=AcceptedTaskSchedule(
            start_utc=2_600_000_000,
            end_utc=2_600_003_600,
            scheduling_timezone_iana=TZ,
        ),
        selected_inventory_relationship_ids=(allocation_id,),
    )

    with ReadSnapshot(factory) as snapshot:
        current = snapshot.connection.execute(
            "SELECT task_id,spare_part_unit_id,revision "
            "FROM task_unit_allocation_current WHERE allocation_id=?",
            (allocation_id,),
        ).fetchone()
        assert (str(current[0]), str(current[1])) == (retry.task_id, unit_id)
        assert int(current[2]) == 2

        events = snapshot.connection.execute(
            "SELECT allocation_event_id,event_kind,task_id,prior_task_id,target_event_id "
            "FROM task_unit_allocation_events WHERE allocation_id=?",
            (allocation_id,),
        ).fetchall()
        assert len(events) == 2
        by_kind = {str(row[1]): row for row in events}
        assert set(by_kind) == {"reserve", "reassign"}
        reserve = by_kind["reserve"]
        reassign = by_kind["reassign"]
        assert str(reserve[2]) == predecessor.task_id
        assert reserve[3] is None and reserve[4] is None
        assert str(reassign[2]) == retry.task_id
        assert str(reassign[3]) == predecessor.task_id
        assert str(reassign[4]) == str(reserve[0])

        assert snapshot.connection.execute(
            "SELECT COUNT(*) FROM inventory_physical_consequences "
            "WHERE task_id IN (?,?)",
            (predecessor.task_id, retry.task_id),
        ).fetchone()[0] == 0
        assert snapshot.connection.execute(
            "SELECT COUNT(*) FROM fault_tag_memberships"
        ).fetchone()[0] == 0


def test_t065_objective_inventory_context_derives_only_through_member_task(
    initialized_database,
) -> None:
    factory = _factory(initialized_database)
    planning = TaskPlanningService(factory)
    task = planning.create_local_task(
        command_id=new_uuid4(),
        local_task_name="Objective Inventory member",
        schedule=AcceptedTaskSchedule(
            start_utc=2_700_000_000,
            end_utc=2_700_003_600,
            scheduling_timezone_iana=TZ,
        ),
    )
    unit_id, unit_revision = _register_unit(factory, "OBJECTIVE-BOM")
    reserved = InventoryNeedsStockService(factory).reserve_spare_part_unit_for_task(
        command_id=new_uuid4(),
        task_id=task.task_id,
        spare_part_unit_id=unit_id,
        unit_revision=unit_revision,
        task_revision=task.revision,
    )
    allocation_id = next(
        ref.result_id
        for ref in reserved.target_refs
        if ref.result_type == "task_unit_allocation"
    )

    intent = _existing_intent(factory, task.task_id)
    preview = ObjectiveGroupingQueryService(factory).creation_preview(
        existing_tasks=(intent,)
    )
    objective = ObjectiveService(factory).create_objective_from_preview(
        command_id=new_uuid4(),
        preview_fingerprint=str(preview["fingerprint"]),
        existing_tasks=(intent,),
    )

    with ReadSnapshot(factory) as snapshot:
        membership = snapshot.connection.execute(
            "SELECT task_id FROM objective_task_membership_current "
            "WHERE objective_id=?",
            (objective.objective_id,),
        ).fetchall()
        assert [str(row[0]) for row in membership] == [task.task_id]

        for table in (
            "task_unit_allocation_current",
            "task_unit_allocation_events",
            "inventory_physical_consequences",
            "physical_consequence_current",
        ):
            columns = {
                str(row[1])
                for row in snapshot.connection.execute(
                    f"PRAGMA table_info({table})"
                ).fetchall()
            }
            assert "objective_id" not in columns

    context = TaskInventoryContextQuery(factory).get(task.task_id)
    assert any(
        item["allocation_id"] == allocation_id
        and item["spare_part_unit_id"] == unit_id
        for item in context["allocation_history"]
    )
