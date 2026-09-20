from __future__ import annotations

from soma.foundation.identifiers import new_uuid4
from soma.foundation.persistence.uow import ReadSnapshot
from soma.objectives_tasks import AcceptedTaskSchedule, TaskPlanningService
from soma.objectives_tasks.domain.objectives import (
    ObjectiveDraftLocalTaskIntent,
    ObjectiveExistingTaskIntent,
)
from soma.objectives_tasks.queries.objectives import ObjectiveQueryService
from soma.objectives_tasks.services.objectives import ObjectiveService


TZ = "America/Guayaquil"


def _factory(initialized_database):
    path, builder = initialized_database
    return builder(path)


def _existing_intent(factory, task_id: str) -> ObjectiveExistingTaskIntent:
    with ReadSnapshot(factory) as snapshot:
        row = snapshot.connection.execute(
            "SELECT t.revision,pc.revision,pc.plan_revision_id "
            "FROM tasks t JOIN task_plan_current pc ON pc.task_id=t.task_id "
            "WHERE t.task_id=?",
            (task_id,),
        ).fetchone()
    assert row is not None
    return ObjectiveExistingTaskIntent(
        task_id=task_id,
        expected_task_revision=int(row[0]),
        expected_plan_revision=int(row[1]),
        expected_plan_revision_id=str(row[2]),
    )


def test_objective_creation_preview_commit_replay_and_overlap(initialized_database) -> None:
    factory = _factory(initialized_database)
    task = TaskPlanningService(factory).create_local_task(
        command_id=new_uuid4(),
        local_task_name="Objective member",
        schedule=AcceptedTaskSchedule(
            start_utc=2_100_000_000,
            end_utc=2_100_003_600,
            scheduling_timezone_iana=TZ,
        ),
    )
    intent = _existing_intent(factory, task.task_id)
    queries = ObjectiveQueryService(factory)
    preview = queries.creation_preview(existing_tasks=(intent,))
    assert preview["mode"] == "CREATE"

    service = ObjectiveService(factory)
    command_id = new_uuid4()
    created = service.create_objective_from_preview(
        command_id=command_id,
        preview_fingerprint=str(preview["fingerprint"]),
        existing_tasks=(intent,),
    )
    assert created.outcome == "APPLIED"
    assert created.revision == 1
    replayed = service.create_objective_from_preview(
        command_id=command_id,
        preview_fingerprint=str(preview["fingerprint"]),
        existing_tasks=(intent,),
    )
    assert replayed.objective_id == created.objective_id
    assert replayed.replayed is True

    detail = queries.workbench(created.objective_id)
    assert detail["tracking_handle"] == "MW-00000001"
    assert detail["member_exact_count"] == 1
    assert detail["aggregate_state"]["execution_state"] == "planned"
    listed = queries.list_objectives()
    assert listed["exact_total"] == 1
    assert listed["items"][0]["objective_id"] == created.objective_id

    overlap_task = TaskPlanningService(factory).create_local_task(
        command_id=new_uuid4(),
        local_task_name="Overlapping member",
        schedule=AcceptedTaskSchedule(
            start_utc=2_100_001_000,
            end_utc=2_100_004_000,
            scheduling_timezone_iana=TZ,
        ),
    )
    overlap = queries.creation_preview(
        existing_tasks=(_existing_intent(factory, overlap_task.task_id),)
    )
    assert overlap["mode"] == "REGROUP_REQUIRED"
    assert overlap["overlap_neighbors"][0]["objective_id"] == created.objective_id


def test_objective_creation_can_atomically_create_draft_local_task(initialized_database) -> None:
    factory = _factory(initialized_database)
    draft = ObjectiveDraftLocalTaskIntent(
        local_task_name="Draft task inside Objective",
        schedule=AcceptedTaskSchedule(
            start_utc=2_200_000_000,
            end_utc=2_200_003_600,
            scheduling_timezone_iana=TZ,
        ),
    )
    queries = ObjectiveQueryService(factory)
    preview = queries.creation_preview(draft_tasks=(draft,))
    service = ObjectiveService(factory)
    result = service.create_objective_from_preview(
        command_id=new_uuid4(),
        preview_fingerprint=str(preview["fingerprint"]),
        draft_tasks=(draft,),
    )
    task_ref = next(ref for ref in result.result_refs if ref.result_type == "task")
    with ReadSnapshot(factory) as snapshot:
        task = snapshot.connection.execute(
            "SELECT creation_origin,revision FROM tasks WHERE task_id=?",
            (task_ref.result_id,),
        ).fetchone()
        plan = snapshot.connection.execute(
            "SELECT p.origin FROM task_plan_current c "
            "JOIN task_plan_revisions p ON p.plan_revision_id=c.plan_revision_id "
            "WHERE c.task_id=?",
            (task_ref.result_id,),
        ).fetchone()
        member = snapshot.connection.execute(
            "SELECT objective_id FROM objective_task_membership_current WHERE task_id=?",
            (task_ref.result_id,),
        ).fetchone()
    assert tuple(task) == ("manual", 1)
    assert str(plan[0]) == "objective_initialization"
    assert str(member[0]) == result.objective_id
