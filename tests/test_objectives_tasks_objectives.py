from __future__ import annotations

import pytest

from soma.foundation.errors import SomaError
from soma.foundation.identifiers import new_uuid4
from soma.foundation.persistence.uow import ReadSnapshot
from soma.objectives_tasks import AcceptedTaskSchedule, TaskPlanningService
from soma.objectives_tasks.domain.objectives import (
    ObjectiveDraftLocalTaskIntent,
    ObjectiveExistingTaskIntent,
)
from soma.objectives_tasks.queries.execution_review import TaskOutcomeReviewQueryService
from soma.objectives_tasks.queries.grouping import ObjectiveGroupingQueryService
from soma.objectives_tasks.queries.hard_delete import ObjectiveHardDeleteQueryService
from soma.objectives_tasks.queries.objectives import ObjectiveQueryService
from soma.objectives_tasks.services.hard_delete import ObjectiveHardDeleteService
from soma.objectives_tasks.services.objectives import ObjectiveService
from soma.objectives_tasks.services.task_execution import TaskExecutionService
from soma.objectives_tasks.services.task_review import TaskReviewService


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
    grouping = ObjectiveGroupingQueryService(factory)
    queries = ObjectiveQueryService(factory)
    preview = grouping.creation_preview(existing_tasks=(intent,))
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
    overlap = grouping.creation_preview(
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
    grouping = ObjectiveGroupingQueryService(factory)
    queries = ObjectiveQueryService(factory)
    preview = grouping.creation_preview(draft_tasks=(draft,))
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


def test_objective_cancel_before_execution_is_atomic_and_reviewed(initialized_database) -> None:
    factory = _factory(initialized_database)
    planning = TaskPlanningService(factory)
    first = planning.create_local_task(
        command_id=new_uuid4(),
        local_task_name="Cancel member one",
        schedule=AcceptedTaskSchedule(
            start_utc=2_300_000_000,
            end_utc=2_300_003_600,
            scheduling_timezone_iana=TZ,
        ),
    )
    second = planning.create_local_task(
        command_id=new_uuid4(),
        local_task_name="Cancel member two",
        schedule=AcceptedTaskSchedule(
            start_utc=2_300_001_000,
            end_utc=2_300_004_000,
            scheduling_timezone_iana=TZ,
        ),
    )
    intents = (
        _existing_intent(factory, first.task_id),
        _existing_intent(factory, second.task_id),
    )
    grouping = ObjectiveGroupingQueryService(factory)
    queries = ObjectiveQueryService(factory)
    preview = grouping.creation_preview(existing_tasks=intents)
    service = ObjectiveService(factory)
    created = service.create_objective_from_preview(
        command_id=new_uuid4(),
        preview_fingerprint=str(preview["fingerprint"]),
        existing_tasks=intents,
    )
    detail = queries.workbench(created.objective_id)
    aggregate_revision = int(detail["aggregate_state"]["revision"])
    command_id = new_uuid4()
    cancelled = service.cancel_objective_before_execution(
        command_id=command_id,
        objective_id=created.objective_id,
        objective_revision=1,
        aggregate_revision=aggregate_revision,
        effective_cancel_utc=2_299_999_000,
        reason_category="window cancelled",
    )
    assert cancelled.outcome == "APPLIED"
    replayed = service.cancel_objective_before_execution(
        command_id=command_id,
        objective_id=created.objective_id,
        objective_revision=1,
        aggregate_revision=aggregate_revision,
        effective_cancel_utc=2_299_999_000,
        reason_category="window cancelled",
    )
    assert replayed.replayed is True

    with ReadSnapshot(factory) as snapshot:
        execution = snapshot.connection.execute(
            "SELECT task_id,execution_state,actual_start_utc,effective_termination_utc "
            "FROM task_execution_projection WHERE task_id IN (?,?) ORDER BY task_id",
            (first.task_id, second.task_id),
        ).fetchall()
        outcomes = snapshot.connection.execute(
            "SELECT task_id,accepted_outcome,revision FROM task_outcome_current "
            "WHERE task_id IN (?,?) ORDER BY task_id",
            (first.task_id, second.task_id),
        ).fetchall()
        review = snapshot.connection.execute(
            "SELECT derived_outcome FROM objective_review_events WHERE objective_id=?",
            (created.objective_id,),
        ).fetchone()
        aggregate = snapshot.connection.execute(
            "SELECT execution_state,aggregate_outcome FROM objective_aggregate_projection "
            "WHERE objective_id=?",
            (created.objective_id,),
        ).fetchone()
    assert all(str(row[1]) == "terminated" and row[2] is None for row in execution)
    assert all(int(row[3]) == 2_299_999_000 for row in execution)
    assert all(str(row[1]) == "cancelled_without_execution" and int(row[2]) == 1 for row in outcomes)
    assert str(review[0]) == "cancelled"
    assert tuple(aggregate) == ("reviewed", "cancelled")


def test_objective_cancel_fails_atomically_after_any_member_start(initialized_database) -> None:
    factory = _factory(initialized_database)
    planning = TaskPlanningService(factory)
    first = planning.create_local_task(
        command_id=new_uuid4(),
        local_task_name="Started member",
        schedule=AcceptedTaskSchedule(
            start_utc=2_310_000_000,
            end_utc=2_310_003_600,
            scheduling_timezone_iana=TZ,
        ),
    )
    second = planning.create_local_task(
        command_id=new_uuid4(),
        local_task_name="Unstarted member",
        schedule=AcceptedTaskSchedule(
            start_utc=2_310_001_000,
            end_utc=2_310_004_000,
            scheduling_timezone_iana=TZ,
        ),
    )
    intents = (
        _existing_intent(factory, first.task_id),
        _existing_intent(factory, second.task_id),
    )
    grouping = ObjectiveGroupingQueryService(factory)
    queries = ObjectiveQueryService(factory)
    preview = grouping.creation_preview(existing_tasks=intents)
    service = ObjectiveService(factory)
    created = service.create_objective_from_preview(
        command_id=new_uuid4(),
        preview_fingerprint=str(preview["fingerprint"]),
        existing_tasks=intents,
    )
    TaskExecutionService(factory).start_task_execution(
        command_id=new_uuid4(),
        task_id=first.task_id,
        task_revision=1,
        execution_revision=0,
        effective_start_utc=2_310_000_100,
    )
    detail = queries.workbench(created.objective_id)
    with pytest.raises(SomaError) as excinfo:
        service.cancel_objective_before_execution(
            command_id=new_uuid4(),
            objective_id=created.objective_id,
            objective_revision=1,
            aggregate_revision=int(detail["aggregate_state"]["revision"]),
            effective_cancel_utc=2_310_000_200,
            reason_category="cannot cancel started work",
        )
    assert excinfo.value.code == "OBJECTIVE_CANCEL_AFTER_EXECUTION"
    with ReadSnapshot(factory) as snapshot:
        assert snapshot.connection.execute(
            "SELECT 1 FROM task_outcome_current WHERE task_id=?",
            (second.task_id,),
        ).fetchone() is None


def test_objective_hard_delete_retains_tasks_and_removes_only_baseline_membership(initialized_database) -> None:
    factory = _factory(initialized_database)
    planning = TaskPlanningService(factory)
    task = planning.create_local_task(
        command_id=new_uuid4(),
        local_task_name="Retained after Objective delete",
        schedule=AcceptedTaskSchedule(
            start_utc=2_320_000_000,
            end_utc=2_320_003_600,
            scheduling_timezone_iana=TZ,
        ),
    )
    intent = _existing_intent(factory, task.task_id)
    grouping = ObjectiveGroupingQueryService(factory)
    queries = ObjectiveQueryService(factory)
    preview = grouping.creation_preview(existing_tasks=(intent,))
    service = ObjectiveService(factory)
    created = service.create_objective_from_preview(
        command_id=new_uuid4(),
        preview_fingerprint=str(preview["fingerprint"]),
        existing_tasks=(intent,),
    )
    delete_queries = ObjectiveHardDeleteQueryService(factory)
    delete_preview = delete_queries.preview(
        objective_id=created.objective_id,
        base_revision=1,
    )
    assert delete_preview.eligible is True
    result = ObjectiveHardDeleteService(factory).hard_delete(
        command_id=new_uuid4(),
        objective_id=created.objective_id,
        objective_revision=1,
        eligibility_fingerprint=delete_preview.eligibility_fingerprint,
    )
    assert result.outcome == "APPLIED"
    with ReadSnapshot(factory) as snapshot:
        assert snapshot.connection.execute(
            "SELECT 1 FROM objectives WHERE objective_id=?",
            (created.objective_id,),
        ).fetchone() is None
        assert snapshot.connection.execute(
            "SELECT 1 FROM objective_task_membership_current WHERE task_id=?",
            (task.task_id,),
        ).fetchone() is None
        assert snapshot.connection.execute(
            "SELECT 1 FROM objective_membership_events WHERE task_id=?",
            (task.task_id,),
        ).fetchone() is None
        assert snapshot.connection.execute(
            "SELECT revision FROM tasks WHERE task_id=?",
            (task.task_id,),
        ).fetchone()[0] == 1
        assert snapshot.connection.execute(
            "SELECT 1 FROM task_plan_current WHERE task_id=?",
            (task.task_id,),
        ).fetchone() is not None


def test_t026_reviewed_at_is_never_execution_time_and_queries_keep_them_separate(
    initialized_database,
    monkeypatch,
) -> None:
    import soma.objectives_tasks.services.objectives as objective_service_module
    import soma.objectives_tasks.services.task_review as task_review_module

    factory = _factory(initialized_database)
    planning = TaskPlanningService(factory)
    task = planning.create_local_task(
        command_id=new_uuid4(),
        local_task_name="Review timestamp separation",
        schedule=AcceptedTaskSchedule(
            start_utc=2_700_000_000,
            end_utc=2_700_003_600,
            scheduling_timezone_iana=TZ,
        ),
    )
    intent = _existing_intent(factory, task.task_id)
    grouping = ObjectiveGroupingQueryService(factory)
    creation = grouping.creation_preview(existing_tasks=(intent,))
    objective = ObjectiveService(factory).create_objective_from_preview(
        command_id=new_uuid4(),
        preview_fingerprint=str(creation["fingerprint"]),
        existing_tasks=(intent,),
    )

    execution = TaskExecutionService(factory)
    started = execution.start_task_execution(
        command_id=new_uuid4(),
        task_id=task.task_id,
        task_revision=task.revision,
        execution_revision=0,
        effective_start_utc=2_700_000_100,
    )
    ended = execution.end_task_execution(
        command_id=new_uuid4(),
        task_id=task.task_id,
        task_revision=started.revision,
        execution_revision=1,
        effective_end_utc=2_700_000_200,
    )

    task_reviewed_at = 2_700_010_000
    monkeypatch.setattr(
        task_review_module,
        "utc_epoch_seconds",
        lambda: task_reviewed_at,
    )
    preview = TaskOutcomeReviewQueryService(factory).preview(
        task_id=task.task_id,
        task_revision=ended.revision,
        execution_revision=2,
        outcome_revision=0,
        current_outcome_event_id=None,
        outcome="completed",
        reason_category=None,
    )
    reviewed = TaskReviewService(factory).review_task_outcome(
        command_id=new_uuid4(),
        task_id=task.task_id,
        task_revision=ended.revision,
        execution_revision=2,
        outcome_revision=0,
        current_outcome_event_id=None,
        outcome="completed",
        reason_category=None,
        outcome_review_fingerprint=preview.outcome_review_fingerprint,
    )
    assert reviewed.outcome == "APPLIED"

    query = ObjectiveQueryService(factory)
    before_objective_review = query.workbench(objective.objective_id)
    assert before_objective_review["aggregate_state"]["actual_start_utc"] == 2_700_000_100
    assert before_objective_review["aggregate_state"]["actual_end_utc"] == 2_700_000_200
    assert before_objective_review["review"]["latest"] is None

    objective_reviewed_at = 2_700_020_000
    monkeypatch.setattr(
        objective_service_module,
        "utc_epoch_seconds",
        lambda: objective_reviewed_at,
    )
    objective_review = ObjectiveService(factory).review_objective(
        command_id=new_uuid4(),
        objective_id=objective.objective_id,
        review_fingerprint=str(
            before_objective_review["review"]["review_fingerprint"]
        ),
    )
    assert objective_review.outcome == "APPLIED"

    with ReadSnapshot(factory) as snapshot:
        execution_row = snapshot.connection.execute(
            "SELECT actual_start_utc,actual_end_utc,effective_termination_utc "
            "FROM task_execution_projection WHERE task_id=?",
            (task.task_id,),
        ).fetchone()
        outcome_row = snapshot.connection.execute(
            "SELECT reviewed_at_utc FROM task_outcome_current WHERE task_id=?",
            (task.task_id,),
        ).fetchone()
        objective_review_row = snapshot.connection.execute(
            "SELECT reviewed_at_utc FROM objective_review_events WHERE objective_id=?",
            (objective.objective_id,),
        ).fetchone()
    assert tuple(execution_row) == (2_700_000_100, 2_700_000_200, None)
    assert int(outcome_row[0]) == task_reviewed_at
    assert int(objective_review_row[0]) == objective_reviewed_at
    assert task_reviewed_at != 2_700_000_200
    assert objective_reviewed_at not in {2_700_000_100, 2_700_000_200}

    detail = query.workbench(objective.objective_id)
    assert detail["aggregate_state"]["actual_start_utc"] == 2_700_000_100
    assert detail["aggregate_state"]["actual_end_utc"] == 2_700_000_200
    assert detail["review"]["latest"]["reviewed_at_utc"] == objective_reviewed_at
    assert detail["review"]["latest"]["derived_outcome"] == "completed"
