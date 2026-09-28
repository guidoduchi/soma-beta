from __future__ import annotations

import sqlite3
from datetime import datetime
from zoneinfo import ZoneInfo

import pytest

from soma.foundation.errors import IntegrityFailure, SomaError
from soma.foundation.identifiers import new_uuid4
from soma.foundation.persistence.uow import ReadSnapshot, UnitOfWork
from soma.objectives_tasks import AcceptedTaskSchedule, TaskPlanningService
from soma.objectives_tasks.domain.objectives import (
    ObjectiveDraftLocalTaskIntent,
    ObjectiveExistingTaskIntent,
)
from soma.objectives_tasks.queries.execution_review import (
    TaskOutcomeCorrectionQueryService,
    TaskOutcomeReviewQueryService,
)
from soma.objectives_tasks.queries.grouping import ObjectiveGroupingQueryService
from soma.objectives_tasks.queries.hard_delete import ObjectiveHardDeleteQueryService
from soma.objectives_tasks.queries.objectives import ObjectiveQueryService
from soma.objectives_tasks.queries.reviews import OperationalReviewQueueQueryService
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



def _create_single_task_objective(
    factory,
    *,
    name: str,
    start_utc: int,
    end_utc: int,
):
    task = TaskPlanningService(factory).create_local_task(
        command_id=new_uuid4(),
        local_task_name=name,
        schedule=AcceptedTaskSchedule(
            start_utc=start_utc,
            end_utc=end_utc,
            scheduling_timezone_iana=TZ,
        ),
    )
    intent = _existing_intent(factory, task.task_id)
    preview = ObjectiveGroupingQueryService(factory).creation_preview(
        existing_tasks=(intent,),
    )
    assert preview["mode"] == "CREATE"
    objective = ObjectiveService(factory).create_objective_from_preview(
        command_id=new_uuid4(),
        preview_fingerprint=str(preview["fingerprint"]),
        existing_tasks=(intent,),
    )
    return task, objective


def _local_epoch(year: int, month: int, day: int, hour: int, minute: int = 0) -> int:
    return int(
        datetime(
            year,
            month,
            day,
            hour,
            minute,
            tzinfo=ZoneInfo(TZ),
        ).timestamp()
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


def test_t033_monthly_ordinal_is_derived_and_tracking_identity_never_changes(
    initialized_database,
) -> None:
    factory = _factory(initialized_database)
    queries = ObjectiveQueryService(factory)

    first_task, first = _create_single_task_objective(
        factory,
        name="Ordinal first",
        start_utc=_local_epoch(2026, 1, 10, 10),
        end_utc=_local_epoch(2026, 1, 10, 11),
    )
    second_task, second = _create_single_task_objective(
        factory,
        name="Ordinal second",
        start_utc=_local_epoch(2026, 1, 10, 12),
        end_utc=_local_epoch(2026, 1, 10, 13),
    )
    third_task, third = _create_single_task_objective(
        factory,
        name="Ordinal third",
        start_utc=_local_epoch(2026, 1, 10, 14),
        end_utc=_local_epoch(2026, 1, 10, 15),
    )
    _cross_task, cross = _create_single_task_objective(
        factory,
        name="Cross month",
        start_utc=_local_epoch(2026, 1, 31, 23, 30),
        end_utc=_local_epoch(2026, 2, 1, 0, 30),
    )

    first_before = queries.monthly_ordinal(first.objective_id, timezone_iana=TZ)
    second_before = queries.monthly_ordinal(second.objective_id, timezone_iana=TZ)
    third_before = queries.monthly_ordinal(third.objective_id, timezone_iana=TZ)
    cross_before = queries.monthly_ordinal(cross.objective_id, timezone_iana=TZ)
    assert (first_before["ordinal"], second_before["ordinal"], third_before["ordinal"]) == (1, 2, 3)
    assert first_before["basis"] == "planned_start"
    assert cross_before["year_month"] == "2026-01"
    assert cross_before["basis"] == "planned_start"

    first_tracking = queries.workbench(first.objective_id)["tracking_handle"]
    executor = TaskExecutionService(factory)
    first_started = executor.start_task_execution(
        command_id=new_uuid4(),
        task_id=first_task.task_id,
        task_revision=first_task.revision,
        execution_revision=0,
        effective_start_utc=_local_epoch(2026, 1, 10, 16),
    )
    assert first_started.outcome == "APPLIED"

    first_after = queries.monthly_ordinal(first.objective_id, timezone_iana=TZ)
    second_after = queries.monthly_ordinal(second.objective_id, timezone_iana=TZ)
    third_after = queries.monthly_ordinal(third.objective_id, timezone_iana=TZ)
    assert first_after["basis"] == "actual_start"
    assert first_after["ordinal"] == 3
    assert second_after["ordinal"] == 1
    assert third_after["ordinal"] == 2
    assert queries.workbench(first.objective_id)["tracking_handle"] == first_tracking

    second_started = executor.start_task_execution(
        command_id=new_uuid4(),
        task_id=second_task.task_id,
        task_revision=second_task.revision,
        execution_revision=0,
        effective_start_utc=_local_epoch(2026, 1, 10, 17),
    )
    third_started = executor.start_task_execution(
        command_id=new_uuid4(),
        task_id=third_task.task_id,
        task_revision=third_task.revision,
        execution_revision=0,
        effective_start_utc=_local_epoch(2026, 1, 10, 17),
    )
    assert second_started.outcome == third_started.outcome == "APPLIED"
    tied = sorted([second.objective_id, third.objective_id])
    tied_ordinals = {
        objective_id: queries.monthly_ordinal(objective_id, timezone_iana=TZ)["ordinal"]
        for objective_id in tied
    }
    assert [tied_ordinals[objective_id] for objective_id in tied] == [2, 3]


def test_t038_objective_archive_is_presentation_only_and_preserves_review_attention(
    initialized_database,
) -> None:
    factory = _factory(initialized_database)
    task, objective = _create_single_task_objective(
        factory,
        name="Archive presentation only",
        start_utc=2_720_000_000,
        end_utc=2_720_003_600,
    )
    executor = TaskExecutionService(factory)
    started = executor.start_task_execution(
        command_id=new_uuid4(),
        task_id=task.task_id,
        task_revision=task.revision,
        execution_revision=0,
        effective_start_utc=2_720_000_100,
    )
    ended = executor.end_task_execution(
        command_id=new_uuid4(),
        task_id=task.task_id,
        task_revision=started.revision,
        execution_revision=1,
        effective_end_utc=2_720_000_200,
    )
    assert ended.outcome == "APPLIED"

    queries = ObjectiveQueryService(factory)
    queue = OperationalReviewQueueQueryService(factory)
    before = queries.workbench(objective.objective_id)
    assert before["aggregate_state"]["execution_state"] == "awaiting_review"
    assert before["archive"]["archived"] is False
    tracking = before["tracking_handle"]

    with ReadSnapshot(factory) as snapshot:
        membership_before = tuple(
            snapshot.connection.execute(
                "SELECT task_id,objective_id,accepted_plan_revision_id,membership_revision "
                "FROM objective_task_membership_current WHERE objective_id=?",
                (objective.objective_id,),
            ).fetchone()
        )
        plan_before = tuple(
            snapshot.connection.execute(
                "SELECT plan_revision_id,revision FROM task_plan_current WHERE task_id=?",
                (task.task_id,),
            ).fetchone()
        )
        execution_before = tuple(
            snapshot.connection.execute(
                "SELECT execution_state,actual_start_utc,actual_end_utc,revision,last_event_id "
                "FROM task_execution_projection WHERE task_id=?",
                (task.task_id,),
            ).fetchone()
        )
        outcome_count_before = int(
            snapshot.connection.execute(
                "SELECT COUNT(*) FROM task_outcome_events WHERE task_id=?",
                (task.task_id,),
            ).fetchone()[0]
        )

    before_queue = queue.objective_review_queue(
        as_of_utc=2_720_000_300,
    )
    assert objective.objective_id in {
        str(item["objective_id"]) for item in before_queue["items"]
    }

    service = ObjectiveService(factory)
    archived = service.archive_objective(
        command_id=new_uuid4(),
        objective_id=objective.objective_id,
        objective_revision=int(before["revision"]),
        archive_revision=int(before["archive"]["revision"]),
        aggregate_revision=int(before["aggregate_state"]["revision"]),
        reason_category="presentation_archive",
    )
    assert archived.outcome == "APPLIED"

    archived_detail = queries.workbench(objective.objective_id)
    assert archived_detail["archive"]["archived"] is True
    assert archived_detail["tracking_handle"] == tracking
    assert queries.list_objectives(archived=False)["exact_total"] == 0
    archived_list = queries.list_objectives(archived=True)
    assert archived_list["exact_total"] == 1
    assert archived_list["items"][0]["objective_id"] == objective.objective_id

    archived_queue = queue.objective_review_queue(
        as_of_utc=2_720_000_300,
    )
    assert objective.objective_id in {
        str(item["objective_id"]) for item in archived_queue["items"]
    }

    with ReadSnapshot(factory) as snapshot:
        assert tuple(
            snapshot.connection.execute(
                "SELECT task_id,objective_id,accepted_plan_revision_id,membership_revision "
                "FROM objective_task_membership_current WHERE objective_id=?",
                (objective.objective_id,),
            ).fetchone()
        ) == membership_before
        assert tuple(
            snapshot.connection.execute(
                "SELECT plan_revision_id,revision FROM task_plan_current WHERE task_id=?",
                (task.task_id,),
            ).fetchone()
        ) == plan_before
        assert tuple(
            snapshot.connection.execute(
                "SELECT execution_state,actual_start_utc,actual_end_utc,revision,last_event_id "
                "FROM task_execution_projection WHERE task_id=?",
                (task.task_id,),
            ).fetchone()
        ) == execution_before
        assert int(
            snapshot.connection.execute(
                "SELECT COUNT(*) FROM task_outcome_events WHERE task_id=?",
                (task.task_id,),
            ).fetchone()[0]
        ) == outcome_count_before == 0

    restored = service.restore_objective(
        command_id=new_uuid4(),
        objective_id=objective.objective_id,
        objective_revision=int(archived_detail["revision"]),
        archive_revision=int(archived_detail["archive"]["revision"]),
        aggregate_revision=int(archived_detail["aggregate_state"]["revision"]),
    )
    assert restored.outcome == "APPLIED"
    restored_detail = queries.workbench(objective.objective_id)
    assert restored_detail["archive"]["archived"] is False
    assert restored_detail["tracking_handle"] == tracking


def test_t048_objective_is_valid_without_ticket_device_or_inventory_context(
    initialized_database,
) -> None:
    factory = _factory(initialized_database)
    task, objective = _create_single_task_objective(
        factory,
        name="Pure local scheduled work",
        start_utc=2_730_000_000,
        end_utc=2_730_003_600,
    )
    queries = ObjectiveQueryService(factory)
    detail = queries.workbench(objective.objective_id)
    assert detail["member_exact_count"] == 1
    assert detail["aggregate_state"]["execution_state"] == "planned"

    context = queries.context_by_task_relationships(
        objective.objective_id,
        limit=100,
    )
    assert context == {
        "items": [],
        "continuation": None,
        "exact_totals_by_context_type": {},
    }

    with ReadSnapshot(factory) as snapshot:
        assert snapshot.connection.execute(
            "SELECT COUNT(*) FROM task_sr_links WHERE task_id=?",
            (task.task_id,),
        ).fetchone()[0] == 0
        assert snapshot.connection.execute(
            "SELECT COUNT(*) FROM task_rfc_links WHERE task_id=?",
            (task.task_id,),
        ).fetchone()[0] == 0
        assert snapshot.connection.execute(
            "SELECT COUNT(*) FROM task_device_links WHERE task_id=?",
            (task.task_id,),
        ).fetchone()[0] == 0
        assert snapshot.connection.execute(
            "SELECT 1 FROM wfm_task_identities WHERE task_id=?",
            (task.task_id,),
        ).fetchone() is None
        assert snapshot.connection.execute(
            "SELECT COUNT(*) FROM physical_consequence_current pc "
            "JOIN inventory_physical_consequences c "
            "ON c.physical_consequence_id=pc.physical_consequence_id "
            "WHERE c.task_id=?",
            (task.task_id,),
        ).fetchone()[0] == 0


def test_t046_due_unreviewed_is_explicit_read_time_projection_only(
    initialized_database,
) -> None:
    factory = _factory(initialized_database)
    task, objective = _create_single_task_objective(
        factory,
        name="Clock-derived due review",
        start_utc=2_760_000_100,
        end_utc=2_760_000_300,
    )
    query = ObjectiveQueryService(factory)
    queue = OperationalReviewQueueQueryService(factory)

    with ReadSnapshot(factory) as snapshot:
        authority_before = {
            "aggregate": tuple(
                snapshot.connection.execute(
                    "SELECT execution_state,aggregate_outcome,actual_start_utc,actual_end_utc,"
                    "attention_reason,revision,last_command_id "
                    "FROM objective_aggregate_projection WHERE objective_id=?",
                    (objective.objective_id,),
                ).fetchone()
            ),
            "task_revision": int(snapshot.connection.execute(
                "SELECT revision FROM tasks WHERE task_id=?",
                (task.task_id,),
            ).fetchone()[0]),
            "receipts": int(snapshot.connection.execute(
                "SELECT COUNT(*) FROM command_receipts"
            ).fetchone()[0]),
            "audits": int(snapshot.connection.execute(
                "SELECT COUNT(*) FROM audit_events"
            ).fetchone()[0]),
            "outcomes": int(snapshot.connection.execute(
                "SELECT COUNT(*) FROM task_outcome_events WHERE task_id=?",
                (task.task_id,),
            ).fetchone()[0]),
            "execution": int(snapshot.connection.execute(
                "SELECT COUNT(*) FROM task_execution_events WHERE task_id=?",
                (task.task_id,),
            ).fetchone()[0]),
        }

    before = query.workbench(
        objective.objective_id,
        as_of_utc=2_760_000_300,
    )
    assert before["aggregate_state"]["execution_state"] == "planned"
    assert before["read_time_projection"] == {
        "as_of_utc": 2_760_000_300,
        "effective_review_state": "planned",
        "due_unreviewed": False,
        "reason_codes": [],
    }
    assert queue.objective_review_queue(
        as_of_utc=2_760_000_300,
        reason="due_unreviewed",
    )["exact_total"] == 0

    after = query.workbench(
        objective.objective_id,
        as_of_utc=2_760_000_301,
    )
    assert after["aggregate_state"]["execution_state"] == "planned"
    assert after["read_time_projection"] == {
        "as_of_utc": 2_760_000_301,
        "effective_review_state": "awaiting_review",
        "due_unreviewed": True,
        "reason_codes": ["due_unreviewed"],
    }
    listed = query.list_objectives(as_of_utc=2_760_000_301)
    listed_item = next(
        item for item in listed["items"]
        if item["objective_id"] == objective.objective_id
    )
    assert listed["as_of_utc"] == 2_760_000_301
    assert listed_item["aggregate_state"]["execution_state"] == "planned"
    assert listed_item["read_time_projection"]["due_unreviewed"] is True

    due_queue = queue.objective_review_queue(
        as_of_utc=2_760_000_301,
        reason="due_unreviewed",
    )
    assert due_queue["exact_total"] == 1
    assert due_queue["items"][0]["objective_id"] == objective.objective_id
    assert due_queue["items"][0]["read_time_projection"]["due_unreviewed"] is True

    with ReadSnapshot(factory) as snapshot:
        assert tuple(
            snapshot.connection.execute(
                "SELECT execution_state,aggregate_outcome,actual_start_utc,actual_end_utc,"
                "attention_reason,revision,last_command_id "
                "FROM objective_aggregate_projection WHERE objective_id=?",
                (objective.objective_id,),
            ).fetchone()
        ) == authority_before["aggregate"]
        assert int(snapshot.connection.execute(
            "SELECT revision FROM tasks WHERE task_id=?",
            (task.task_id,),
        ).fetchone()[0]) == authority_before["task_revision"]
        assert int(snapshot.connection.execute(
            "SELECT COUNT(*) FROM command_receipts"
        ).fetchone()[0]) == authority_before["receipts"]
        assert int(snapshot.connection.execute(
            "SELECT COUNT(*) FROM audit_events"
        ).fetchone()[0]) == authority_before["audits"]
        assert int(snapshot.connection.execute(
            "SELECT COUNT(*) FROM task_outcome_events WHERE task_id=?",
            (task.task_id,),
        ).fetchone()[0]) == authority_before["outcomes"] == 0
        assert int(snapshot.connection.execute(
            "SELECT COUNT(*) FROM task_execution_events WHERE task_id=?",
            (task.task_id,),
        ).fetchone()[0]) == authority_before["execution"] == 0


def test_lld05_f002_objective_creation_failure_before_first_membership_rolls_back_allocator_and_retries(
    initialized_database,
    monkeypatch,
) -> None:
    factory = _factory(initialized_database)
    task = TaskPlanningService(factory).create_local_task(
        command_id=new_uuid4(),
        local_task_name="F002 allocator rollback",
        schedule=AcceptedTaskSchedule(
            start_utc=2_320_000_000,
            end_utc=2_320_003_600,
            scheduling_timezone_iana=TZ,
        ),
    )
    intent = _existing_intent(factory, task.task_id)
    preview = ObjectiveGroupingQueryService(factory).creation_preview(
        existing_tasks=(intent,),
    )
    service = ObjectiveService(factory)
    command_id = new_uuid4()
    with ReadSnapshot(factory) as snapshot:
        allocator_before = tuple(
            snapshot.connection.execute(
                "SELECT next_sequence,revision,last_command_id "
                "FROM objective_tracking_allocator WHERE singleton_id=1"
            ).fetchone()
        )

    original = service._insert_membership

    def fail_before_first_membership(*_args, **_kwargs):
        raise IntegrityFailure("LLD05-F002 injected before first membership")

    monkeypatch.setattr(service, "_insert_membership", fail_before_first_membership)
    with pytest.raises(IntegrityFailure, match="LLD05-F002"):
        service.create_objective_from_preview(
            command_id=command_id,
            preview_fingerprint=str(preview["fingerprint"]),
            existing_tasks=(intent,),
        )

    with ReadSnapshot(factory) as snapshot:
        assert tuple(
            snapshot.connection.execute(
                "SELECT next_sequence,revision,last_command_id "
                "FROM objective_tracking_allocator WHERE singleton_id=1"
            ).fetchone()
        ) == allocator_before
        assert snapshot.connection.execute(
            "SELECT count(*) FROM objectives"
        ).fetchone()[0] == 0
        assert snapshot.connection.execute(
            "SELECT count(*) FROM objective_task_membership_current WHERE task_id=?",
            (task.task_id,),
        ).fetchone()[0] == 0
        assert snapshot.connection.execute(
            "SELECT count(*) FROM command_receipts WHERE command_id=?",
            (command_id,),
        ).fetchone()[0] == 0
        assert snapshot.connection.execute(
            "SELECT count(*) FROM audit_events WHERE command_id=?",
            (command_id,),
        ).fetchone()[0] == 0

    monkeypatch.setattr(service, "_insert_membership", original)
    retried = service.create_objective_from_preview(
        command_id=command_id,
        preview_fingerprint=str(preview["fingerprint"]),
        existing_tasks=(intent,),
    )
    with ReadSnapshot(factory) as snapshot:
        tracking = snapshot.connection.execute(
            "SELECT tracking_sequence FROM objectives WHERE objective_id=?",
            (retried.objective_id,),
        ).fetchone()
    assert tracking is not None and int(tracking[0]) == int(allocator_before[0])


def test_lld05_f003_second_membership_failure_rolls_back_first_membership_and_objective(
    initialized_database,
    monkeypatch,
) -> None:
    factory = _factory(initialized_database)
    first = TaskPlanningService(factory).create_local_task(
        command_id=new_uuid4(),
        local_task_name="F003 first",
        schedule=AcceptedTaskSchedule(
            start_utc=2_321_000_000,
            end_utc=2_321_003_600,
            scheduling_timezone_iana=TZ,
        ),
    )
    second = TaskPlanningService(factory).create_local_task(
        command_id=new_uuid4(),
        local_task_name="F003 second",
        schedule=AcceptedTaskSchedule(
            start_utc=2_321_001_800,
            end_utc=2_321_005_400,
            scheduling_timezone_iana=TZ,
        ),
    )
    intents = (
        _existing_intent(factory, first.task_id),
        _existing_intent(factory, second.task_id),
    )
    preview = ObjectiveGroupingQueryService(factory).creation_preview(
        existing_tasks=intents,
    )
    service = ObjectiveService(factory)
    command_id = new_uuid4()
    original = service._insert_membership
    calls = [0]

    def fail_on_second_membership(connection, **kwargs):
        calls[0] += 1
        if calls[0] == 2:
            raise IntegrityFailure("LLD05-F003 injected after first membership")
        return original(connection, **kwargs)

    monkeypatch.setattr(service, "_insert_membership", fail_on_second_membership)
    with pytest.raises(IntegrityFailure, match="LLD05-F003"):
        service.create_objective_from_preview(
            command_id=command_id,
            preview_fingerprint=str(preview["fingerprint"]),
            existing_tasks=intents,
        )
    assert calls == [2]
    with ReadSnapshot(factory) as snapshot:
        assert snapshot.connection.execute(
            "SELECT count(*) FROM objectives"
        ).fetchone()[0] == 0
        assert snapshot.connection.execute(
            "SELECT count(*) FROM objective_membership_events "
            "WHERE task_id IN (?,?)",
            (first.task_id, second.task_id),
        ).fetchone()[0] == 0
        assert snapshot.connection.execute(
            "SELECT count(*) FROM objective_task_membership_current "
            "WHERE task_id IN (?,?)",
            (first.task_id, second.task_id),
        ).fetchone()[0] == 0
        assert snapshot.connection.execute(
            "SELECT count(*) FROM command_receipts WHERE command_id=?",
            (command_id,),
        ).fetchone()[0] == 0

def test_lld05_f011_whole_objective_cancel_failure_after_first_member_rolls_back_all(
    initialized_database,
    monkeypatch,
) -> None:
    factory = _factory(initialized_database)
    planning = TaskPlanningService(factory)
    first = planning.create_local_task(
        command_id=new_uuid4(),
        local_task_name="F011 first member",
        schedule=AcceptedTaskSchedule(
            start_utc=2_325_000_000,
            end_utc=2_325_003_600,
            scheduling_timezone_iana=TZ,
        ),
    )
    second = planning.create_local_task(
        command_id=new_uuid4(),
        local_task_name="F011 second member",
        schedule=AcceptedTaskSchedule(
            start_utc=2_325_001_000,
            end_utc=2_325_004_000,
            scheduling_timezone_iana=TZ,
        ),
    )
    intents = (
        _existing_intent(factory, first.task_id),
        _existing_intent(factory, second.task_id),
    )
    preview = ObjectiveGroupingQueryService(factory).creation_preview(
        existing_tasks=intents,
    )
    service = ObjectiveService(factory)
    created = service.create_objective_from_preview(
        command_id=new_uuid4(),
        preview_fingerprint=str(preview["fingerprint"]),
        existing_tasks=intents,
    )
    detail = ObjectiveQueryService(factory).workbench(created.objective_id)
    aggregate_revision = int(detail["aggregate_state"]["revision"])
    with ReadSnapshot(factory) as snapshot:
        aggregate_before = tuple(
            snapshot.connection.execute(
                "SELECT execution_state,aggregate_outcome,revision,last_command_id "
                "FROM objective_aggregate_projection WHERE objective_id=?",
                (created.objective_id,),
            ).fetchone()
        )
        task_revisions_before = dict(
            snapshot.connection.execute(
                "SELECT task_id,revision FROM tasks WHERE task_id IN (?,?)",
                (first.task_id, second.task_id),
            ).fetchall()
        )

    original_increment = service._tasks.increment_revision
    calls = [0]

    def fail_after_first_member(inner, *, task_id, expected_revision):
        original_increment(
            inner,
            task_id=task_id,
            expected_revision=expected_revision,
        )
        calls[0] += 1
        if calls[0] == 1:
            raise IntegrityFailure(
                "LLD05-F011 injected after first Task cancellation/outcome"
            )

    monkeypatch.setattr(
        service._tasks,
        "increment_revision",
        fail_after_first_member,
    )
    command_id = new_uuid4()
    with pytest.raises(IntegrityFailure, match="LLD05-F011"):
        service.cancel_objective_before_execution(
            command_id=command_id,
            objective_id=created.objective_id,
            objective_revision=1,
            aggregate_revision=aggregate_revision,
            effective_cancel_utc=2_324_999_000,
            reason_category="f011_atomicity_cut",
        )
    assert calls == [1]

    with ReadSnapshot(factory) as snapshot:
        assert dict(
            snapshot.connection.execute(
                "SELECT task_id,revision FROM tasks WHERE task_id IN (?,?)",
                (first.task_id, second.task_id),
            ).fetchall()
        ) == task_revisions_before
        assert snapshot.connection.execute(
            "SELECT count(*) FROM task_execution_events WHERE command_id=?",
            (command_id,),
        ).fetchone()[0] == 0
        assert snapshot.connection.execute(
            "SELECT count(*) FROM task_outcome_events WHERE command_id=?",
            (command_id,),
        ).fetchone()[0] == 0
        assert snapshot.connection.execute(
            "SELECT count(*) FROM task_execution_projection "
            "WHERE task_id IN (?,?)",
            (first.task_id, second.task_id),
        ).fetchone()[0] == 0
        assert snapshot.connection.execute(
            "SELECT count(*) FROM task_outcome_current "
            "WHERE task_id IN (?,?)",
            (first.task_id, second.task_id),
        ).fetchone()[0] == 0
        assert tuple(
            snapshot.connection.execute(
                "SELECT execution_state,aggregate_outcome,revision,last_command_id "
                "FROM objective_aggregate_projection WHERE objective_id=?",
                (created.objective_id,),
            ).fetchone()
        ) == aggregate_before
        assert snapshot.connection.execute(
            "SELECT count(*) FROM objective_review_events WHERE command_id=?",
            (command_id,),
        ).fetchone()[0] == 0
        assert snapshot.connection.execute(
            "SELECT count(*) FROM command_receipts WHERE command_id=?",
            (command_id,),
        ).fetchone()[0] == 0
        assert snapshot.connection.execute(
            "SELECT count(*) FROM audit_events WHERE command_id=?",
            (command_id,),
        ).fetchone()[0] == 0

def test_lld05_f030_objective_delete_failure_after_projection_removal_rolls_back_all(
    initialized_database,
) -> None:
    factory = _factory(initialized_database)
    task = TaskPlanningService(factory).create_local_task(
        command_id=new_uuid4(),
        local_task_name="F030 retained Task",
        schedule=AcceptedTaskSchedule(
            start_utc=2_330_000_000,
            end_utc=2_330_003_600,
            scheduling_timezone_iana=TZ,
        ),
    )
    intent = _existing_intent(factory, task.task_id)
    preview = ObjectiveGroupingQueryService(factory).creation_preview(
        existing_tasks=(intent,),
    )
    created = ObjectiveService(factory).create_objective_from_preview(
        command_id=new_uuid4(),
        preview_fingerprint=str(preview["fingerprint"]),
        existing_tasks=(intent,),
    )
    delete_preview = ObjectiveHardDeleteQueryService(factory).preview(
        objective_id=created.objective_id,
        base_revision=1,
    )
    assert delete_preview.eligible is True

    with ReadSnapshot(factory) as snapshot:
        membership_before = tuple(
            snapshot.connection.execute(
                "SELECT task_id,objective_id,accepted_plan_revision_id,"
                "membership_revision,last_event_id,last_command_id "
                "FROM objective_task_membership_current WHERE task_id=?",
                (task.task_id,),
            ).fetchone()
        )
        envelope_before = tuple(
            snapshot.connection.execute(
                "SELECT start_utc,end_utc,member_count,revision,last_command_id "
                "FROM objective_envelope_projection WHERE objective_id=?",
                (created.objective_id,),
            ).fetchone()
        )
        aggregate_before = tuple(
            snapshot.connection.execute(
                "SELECT execution_state,aggregate_outcome,revision,last_command_id "
                "FROM objective_aggregate_projection WHERE objective_id=?",
                (created.objective_id,),
            ).fetchone()
        )

    with UnitOfWork(factory) as uow:
        uow.connection.execute(
            "CREATE TRIGGER test_lld05_f030_fail_objective_delete "
            "BEFORE DELETE ON objectives "
            "WHEN OLD.objective_id='" + created.objective_id + "' "
            "BEGIN SELECT RAISE(ABORT,'LLD05-F030 injected final Objective delete failure'); END"
        )

    command_id = new_uuid4()
    with pytest.raises((SomaError, sqlite3.IntegrityError)):
        ObjectiveHardDeleteService(factory).hard_delete(
            command_id=command_id,
            objective_id=created.objective_id,
            objective_revision=1,
            eligibility_fingerprint=delete_preview.eligibility_fingerprint,
        )

    with ReadSnapshot(factory) as snapshot:
        assert snapshot.connection.execute(
            "SELECT 1 FROM objectives WHERE objective_id=?",
            (created.objective_id,),
        ).fetchone() is not None
        assert tuple(
            snapshot.connection.execute(
                "SELECT task_id,objective_id,accepted_plan_revision_id,"
                "membership_revision,last_event_id,last_command_id "
                "FROM objective_task_membership_current WHERE task_id=?",
                (task.task_id,),
            ).fetchone()
        ) == membership_before
        assert tuple(
            snapshot.connection.execute(
                "SELECT start_utc,end_utc,member_count,revision,last_command_id "
                "FROM objective_envelope_projection WHERE objective_id=?",
                (created.objective_id,),
            ).fetchone()
        ) == envelope_before
        assert tuple(
            snapshot.connection.execute(
                "SELECT execution_state,aggregate_outcome,revision,last_command_id "
                "FROM objective_aggregate_projection WHERE objective_id=?",
                (created.objective_id,),
            ).fetchone()
        ) == aggregate_before
        assert snapshot.connection.execute(
            "SELECT COUNT(*) FROM command_receipts WHERE command_id=?",
            (command_id,),
        ).fetchone()[0] == 0
        assert snapshot.connection.execute(
            "SELECT COUNT(*) FROM audit_events WHERE command_id=?",
            (command_id,),
        ).fetchone()[0] == 0


def test_lld05_f031_objective_review_rejects_task_outcome_drift_after_preview(
    initialized_database,
) -> None:
    factory = _factory(initialized_database)
    task = TaskPlanningService(factory).create_local_task(
        command_id=new_uuid4(),
        local_task_name="F031 review drift",
        schedule=AcceptedTaskSchedule(
            start_utc=2_331_000_000,
            end_utc=2_331_003_600,
            scheduling_timezone_iana=TZ,
        ),
    )
    intent = _existing_intent(factory, task.task_id)
    creation = ObjectiveGroupingQueryService(factory).creation_preview(
        existing_tasks=(intent,),
    )
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
        effective_start_utc=2_331_000_100,
    )
    ended = execution.end_task_execution(
        command_id=new_uuid4(),
        task_id=task.task_id,
        task_revision=started.revision,
        execution_revision=1,
        effective_end_utc=2_331_000_200,
    )
    first_preview = TaskOutcomeReviewQueryService(factory).preview(
        task_id=task.task_id,
        task_revision=ended.revision,
        execution_revision=2,
        outcome_revision=0,
        current_outcome_event_id=None,
        outcome="completed",
        reason_category=None,
    )
    task_review = TaskReviewService(factory).review_task_outcome(
        command_id=new_uuid4(),
        task_id=task.task_id,
        task_revision=ended.revision,
        execution_revision=2,
        outcome_revision=0,
        current_outcome_event_id=None,
        outcome="completed",
        reason_category=None,
        outcome_review_fingerprint=first_preview.outcome_review_fingerprint,
    )
    outcome_event_id = task_review.result_refs[0].result_id

    detail = ObjectiveQueryService(factory).workbench(objective.objective_id)
    stale_review_fingerprint = str(detail["review"]["review_fingerprint"])

    correction_preview = TaskOutcomeCorrectionQueryService(factory).preview(
        task_id=task.task_id,
        task_revision=task_review.revision,
        execution_revision=2,
        current_outcome_revision=1,
        current_outcome_event_id=outcome_event_id,
        replacement_outcome="incomplete",
        reason_category="f031_outcome_drift",
    )
    TaskReviewService(factory).correct_task_outcome(
        command_id=new_uuid4(),
        task_id=task.task_id,
        task_revision=task_review.revision,
        execution_revision=2,
        current_outcome_revision=1,
        current_outcome_event_id=outcome_event_id,
        replacement_outcome="incomplete",
        reason_category="f031_outcome_drift",
        correction_review_fingerprint=correction_preview.correction_review_fingerprint,
    )

    command_id = new_uuid4()
    with pytest.raises(SomaError) as stale:
        ObjectiveService(factory).review_objective(
            command_id=command_id,
            objective_id=objective.objective_id,
            review_fingerprint=stale_review_fingerprint,
        )
    assert stale.value.code == "OBJECTIVE_REVIEW_STALE"

    with ReadSnapshot(factory) as snapshot:
        assert snapshot.connection.execute(
            "SELECT COUNT(*) FROM objective_review_events "
            "WHERE objective_id=? AND command_id=?",
            (objective.objective_id, command_id),
        ).fetchone()[0] == 0
        assert snapshot.connection.execute(
            "SELECT COUNT(*) FROM command_receipts WHERE command_id=?",
            (command_id,),
        ).fetchone()[0] == 0

def test_t018_objective_outcome_matrix_is_derived_from_member_task_facts(
    initialized_database,
) -> None:
    factory = _factory(initialized_database)
    planning = TaskPlanningService(factory)
    execution = TaskExecutionService(factory)
    reviews = TaskReviewService(factory)

    def create_pair(label: str, base_utc: int):
        tasks = tuple(
            planning.create_local_task(
                command_id=new_uuid4(),
                local_task_name=f"{label} member {index}",
                schedule=AcceptedTaskSchedule(
                    start_utc=base_utc,
                    end_utc=base_utc + 3_600,
                    scheduling_timezone_iana=TZ,
                ),
            )
            for index in (1, 2)
        )
        intents = tuple(_existing_intent(factory, task.task_id) for task in tasks)
        preview = ObjectiveGroupingQueryService(factory).creation_preview(
            existing_tasks=intents,
        )
        assert preview["mode"] == "CREATE"
        objective = ObjectiveService(factory).create_objective_from_preview(
            command_id=new_uuid4(),
            preview_fingerprint=str(preview["fingerprint"]),
            existing_tasks=intents,
        )
        return tasks, objective

    def review_terminal(task, *, outcome: str, start_utc: int):
        started = execution.start_task_execution(
            command_id=new_uuid4(),
            task_id=task.task_id,
            task_revision=task.revision,
            execution_revision=0,
            effective_start_utc=start_utc,
        )
        ended = execution.end_task_execution(
            command_id=new_uuid4(),
            task_id=task.task_id,
            task_revision=started.revision,
            execution_revision=1,
            effective_end_utc=start_utc + 100,
        )
        reason = "work_incomplete" if outcome == "incomplete" else None
        preview = TaskOutcomeReviewQueryService(factory).preview(
            task_id=task.task_id,
            task_revision=ended.revision,
            execution_revision=2,
            outcome_revision=0,
            current_outcome_event_id=None,
            outcome=outcome,
            reason_category=reason,
        )
        assert preview.eligible is True
        return reviews.review_task_outcome(
            command_id=new_uuid4(),
            task_id=task.task_id,
            task_revision=ended.revision,
            execution_revision=2,
            outcome_revision=0,
            current_outcome_event_id=None,
            outcome=outcome,
            reason_category=reason,
            outcome_review_fingerprint=preview.outcome_review_fingerprint,
        )

    def cancel_pristine(task, *, cancel_utc: int):
        return execution.cancel_task_without_execution(
            command_id=new_uuid4(),
            task_id=task.task_id,
            task_revision=task.revision,
            execution_revision=0,
            outcome_revision=0,
            effective_cancel_utc=cancel_utc,
            reason_category="operator_cancel",
        )

    def aggregate(objective_id: str):
        with ReadSnapshot(factory) as snapshot:
            return tuple(
                snapshot.connection.execute(
                    "SELECT execution_state,aggregate_outcome,attention_reason "
                    "FROM objective_aggregate_projection WHERE objective_id=?",
                    (objective_id,),
                ).fetchone()
            )

    completed_cancelled, objective_a = create_pair(
        "T018 completed cancelled",
        2_780_000_000,
    )
    review_terminal(
        completed_cancelled[0],
        outcome="completed",
        start_utc=2_780_000_100,
    )
    cancel_pristine(
        completed_cancelled[1],
        cancel_utc=2_779_999_900,
    )
    assert aggregate(objective_a.objective_id) == (
        "awaiting_review",
        "mixed",
        "mixed_outcomes",
    )

    completed_incomplete, objective_b = create_pair(
        "T018 completed incomplete",
        2_780_100_000,
    )
    review_terminal(
        completed_incomplete[0],
        outcome="completed",
        start_utc=2_780_100_100,
    )
    review_terminal(
        completed_incomplete[1],
        outcome="incomplete",
        start_utc=2_780_100_200,
    )
    assert aggregate(objective_b.objective_id) == (
        "awaiting_review",
        "mixed",
        "mixed_outcomes",
    )

    all_completed, objective_c = create_pair(
        "T018 all completed",
        2_780_200_000,
    )
    review_terminal(
        all_completed[0],
        outcome="completed",
        start_utc=2_780_200_100,
    )
    review_terminal(
        all_completed[1],
        outcome="completed",
        start_utc=2_780_200_200,
    )
    assert aggregate(objective_c.objective_id) == (
        "awaiting_review",
        "completed",
        None,
    )

    all_cancelled, objective_d = create_pair(
        "T018 all cancelled",
        2_780_300_000,
    )
    cancel_pristine(
        all_cancelled[0],
        cancel_utc=2_780_299_900,
    )
    cancel_pristine(
        all_cancelled[1],
        cancel_utc=2_780_299_901,
    )
    assert aggregate(objective_d.objective_id) == (
        "awaiting_review",
        "cancelled",
        None,
    )

    with ReadSnapshot(factory) as snapshot:
        assert snapshot.connection.execute(
            "SELECT COUNT(*) FROM objective_review_events "
            "WHERE objective_id IN (?,?,?,?)",
            (
                objective_a.objective_id,
                objective_b.objective_id,
                objective_c.objective_id,
                objective_d.objective_id,
            ),
        ).fetchone()[0] == 0

def test_lld05_f032_preview_then_concurrent_start_returns_cancel_after_execution(
    initialized_database,
) -> None:
    factory = _factory(initialized_database)
    planning = TaskPlanningService(factory)
    first = planning.create_local_task(
        command_id=new_uuid4(),
        local_task_name="F032 preview member A",
        schedule=AcceptedTaskSchedule(
            start_utc=2_311_000_000,
            end_utc=2_311_003_600,
            scheduling_timezone_iana=TZ,
        ),
    )
    second = planning.create_local_task(
        command_id=new_uuid4(),
        local_task_name="F032 preview member B",
        schedule=AcceptedTaskSchedule(
            start_utc=2_311_001_000,
            end_utc=2_311_004_000,
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
    cancel_preview = queries.workbench(created.objective_id)
    preview_aggregate_revision = int(cancel_preview["aggregate_state"]["revision"])

    started = TaskExecutionService(factory).start_task_execution(
        command_id=new_uuid4(),
        task_id=first.task_id,
        task_revision=1,
        execution_revision=0,
        effective_start_utc=2_311_000_100,
    )
    assert started.outcome == "APPLIED"

    cancel_command = new_uuid4()
    with pytest.raises(SomaError) as excinfo:
        service.cancel_objective_before_execution(
            command_id=cancel_command,
            objective_id=created.objective_id,
            objective_revision=1,
            aggregate_revision=preview_aggregate_revision,
            effective_cancel_utc=2_311_000_200,
            reason_category="f032_concurrent_start",
        )
    assert excinfo.value.code == "OBJECTIVE_CANCEL_AFTER_EXECUTION"

    with ReadSnapshot(factory) as snapshot:
        assert snapshot.connection.execute(
            "SELECT execution_state,actual_start_utc FROM task_execution_projection "
            "WHERE task_id=?",
            (first.task_id,),
        ).fetchone() == ("in_progress", 2_311_000_100)
        assert snapshot.connection.execute(
            "SELECT 1 FROM task_outcome_current WHERE task_id=?",
            (second.task_id,),
        ).fetchone() is None
        assert snapshot.connection.execute(
            "SELECT 1 FROM command_receipts WHERE command_id=?",
            (cancel_command,),
        ).fetchone() is None

def test_t003_tracking_allocator_exhaustion_is_atomic_and_nonreusing(
    initialized_database,
) -> None:
    factory = _factory(initialized_database)
    with UnitOfWork(factory) as uow:
        uow.connection.execute(
            "UPDATE objective_tracking_allocator "
            "SET next_sequence=99999999,last_command_id=NULL "
            "WHERE singleton_id=1"
        )

    first_task = TaskPlanningService(factory).create_local_task(
        command_id=new_uuid4(),
        local_task_name="Last allocatable Objective",
        schedule=AcceptedTaskSchedule(
            start_utc=2_891_000_000,
            end_utc=2_891_003_600,
            scheduling_timezone_iana=TZ,
        ),
    )
    first_intent = _existing_intent(factory, first_task.task_id)
    first_preview = ObjectiveGroupingQueryService(factory).creation_preview(
        existing_tasks=(first_intent,),
    )
    assert first_preview["mode"] == "CREATE"
    first = ObjectiveService(factory).create_objective_from_preview(
        command_id=new_uuid4(),
        preview_fingerprint=str(first_preview["fingerprint"]),
        existing_tasks=(first_intent,),
    )
    with ReadSnapshot(factory) as snapshot:
        row = snapshot.connection.execute(
            "SELECT tracking_sequence,tracking_id FROM objectives WHERE objective_id=?",
            (first.objective_id,),
        ).fetchone()
        assert tuple(row) == (99_999_999, "MW-99999999")
        allocator = snapshot.connection.execute(
            "SELECT next_sequence FROM objective_tracking_allocator WHERE singleton_id=1"
        ).fetchone()
        assert allocator == (100_000_000,)

    second_task = TaskPlanningService(factory).create_local_task(
        command_id=new_uuid4(),
        local_task_name="Exhausted Objective attempt",
        schedule=AcceptedTaskSchedule(
            start_utc=2_892_000_000,
            end_utc=2_892_003_600,
            scheduling_timezone_iana=TZ,
        ),
    )
    second_intent = _existing_intent(factory, second_task.task_id)
    second_preview = ObjectiveGroupingQueryService(factory).creation_preview(
        existing_tasks=(second_intent,),
    )
    assert second_preview["mode"] == "CREATE"
    command_id = new_uuid4()
    with pytest.raises(SomaError) as caught:
        ObjectiveService(factory).create_objective_from_preview(
            command_id=command_id,
            preview_fingerprint=str(second_preview["fingerprint"]),
            existing_tasks=(second_intent,),
        )
    assert caught.value.code == "OBJECTIVE_TRACKING_ID_EXHAUSTED"

    with ReadSnapshot(factory) as snapshot:
        assert snapshot.connection.execute(
            "SELECT next_sequence FROM objective_tracking_allocator WHERE singleton_id=1"
        ).fetchone() == (100_000_000,)
        assert snapshot.connection.execute(
            "SELECT COUNT(*) FROM objectives"
        ).fetchone()[0] == 1
        assert snapshot.connection.execute(
            "SELECT 1 FROM objective_task_membership_current WHERE task_id=?",
            (second_task.task_id,),
        ).fetchone() is None
        assert snapshot.connection.execute(
            "SELECT 1 FROM command_receipts WHERE command_id=?",
            (command_id,),
        ).fetchone() is None
        assert snapshot.connection.execute(
            "SELECT 1 FROM audit_events WHERE command_id=?",
            (command_id,),
        ).fetchone() is None

