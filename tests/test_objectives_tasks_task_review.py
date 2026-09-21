from __future__ import annotations

import pytest

from soma.foundation.errors import SomaError
from soma.foundation.identifiers import new_uuid4
from soma.foundation.persistence.uow import ReadSnapshot, UnitOfWork
from soma.objectives_tasks import AcceptedTaskSchedule, TaskPlanningService
from soma.objectives_tasks.queries.execution_review import (
    TaskOutcomeCorrectionQueryService,
    TaskOutcomeReviewQueryService,
)
from soma.objectives_tasks.services.task_execution import TaskExecutionService
from soma.objectives_tasks.services.task_review import TaskReviewService


TZ = "America/Guayaquil"


def _factory(initialized_database):
    database_path, factory_for_path = initialized_database
    return factory_for_path(database_path)


def _ended_task(factory):
    created = TaskPlanningService(factory).create_local_task(
        command_id=new_uuid4(),
        local_task_name="Reviewed outcome",
        schedule=AcceptedTaskSchedule(
            start_utc=1_980_000_000,
            end_utc=1_980_003_600,
            scheduling_timezone_iana=TZ,
        ),
    )
    execution = TaskExecutionService(factory)
    started = execution.start_task_execution(
        command_id=new_uuid4(),
        task_id=created.task_id,
        task_revision=created.revision,
        execution_revision=0,
        effective_start_utc=1_980_000_100,
    )
    ended = execution.end_task_execution(
        command_id=new_uuid4(),
        task_id=created.task_id,
        task_revision=started.revision,
        execution_revision=1,
        effective_end_utc=1_980_000_200,
    )
    with ReadSnapshot(factory) as snapshot:
        end_event_id = str(
            snapshot.connection.execute(
                "SELECT execution_event_id FROM task_execution_events "
                "WHERE task_id=? AND execution_revision=2",
                (created.task_id,),
            ).fetchone()[0]
        )
    return created.task_id, ended.revision, end_event_id


def _first_review_preview(factory, *, task_id: str, task_revision: int):
    return TaskOutcomeReviewQueryService(factory).preview(
        task_id=task_id,
        task_revision=task_revision,
        execution_revision=2,
        outcome_revision=0,
        current_outcome_event_id=None,
        outcome="completed",
        reason_category=None,
    )


def test_review_task_outcome_applies_replays_and_exact_no_change(initialized_database) -> None:
    factory = _factory(initialized_database)
    task_id, task_revision, _end_event_id = _ended_task(factory)
    preview = _first_review_preview(factory, task_id=task_id, task_revision=task_revision)
    assert preview.eligible is True

    command_id = new_uuid4()
    service = TaskReviewService(factory)
    applied = service.review_task_outcome(
        command_id=command_id,
        task_id=task_id,
        task_revision=task_revision,
        execution_revision=2,
        outcome_revision=0,
        current_outcome_event_id=None,
        outcome="completed",
        reason_category=None,
        outcome_review_fingerprint=preview.outcome_review_fingerprint,
    )
    assert applied.outcome == "APPLIED"
    assert applied.revision == task_revision + 1
    assert applied.replayed is False
    assert len(applied.result_refs) == 1
    outcome_event_id = applied.result_refs[0].result_id

    replay = service.review_task_outcome(
        command_id=command_id,
        task_id=task_id,
        task_revision=task_revision,
        execution_revision=2,
        outcome_revision=0,
        current_outcome_event_id=None,
        outcome="completed",
        reason_category=None,
        outcome_review_fingerprint=preview.outcome_review_fingerprint,
    )
    assert replay.replayed is True
    assert replay.result_refs[0].result_id == outcome_event_id
    assert replay.revision == applied.revision

    with ReadSnapshot(factory) as snapshot:
        assert snapshot.connection.execute(
            "SELECT c.accepted_outcome,e.correction_of_event_id,c.revision "
            "FROM task_outcome_current c JOIN task_outcome_events e "
            "ON e.outcome_event_id=c.outcome_event_id WHERE c.task_id=?",
            (task_id,),
        ).fetchone() == ("completed", None, 1)
        assert snapshot.connection.execute(
            "SELECT count(*) FROM task_outcome_events WHERE task_id=?", (task_id,)
        ).fetchone()[0] == 1
        assert snapshot.connection.execute(
            "SELECT count(*) FROM audit_events WHERE command_id=? AND action_type='task.outcome_reviewed'",
            (command_id,),
        ).fetchone()[0] == 1

    no_change_preview = TaskOutcomeReviewQueryService(factory).preview(
        task_id=task_id,
        task_revision=applied.revision,
        execution_revision=2,
        outcome_revision=1,
        current_outcome_event_id=outcome_event_id,
        outcome="completed",
        reason_category=None,
    )
    assert no_change_preview.semantic_no_change is True
    no_change_command = new_uuid4()
    no_change = service.review_task_outcome(
        command_id=no_change_command,
        task_id=task_id,
        task_revision=applied.revision,
        execution_revision=2,
        outcome_revision=1,
        current_outcome_event_id=outcome_event_id,
        outcome="completed",
        reason_category=None,
        outcome_review_fingerprint=no_change_preview.outcome_review_fingerprint,
    )
    assert no_change.outcome == "NO_CHANGE"
    assert no_change.revision == applied.revision
    with ReadSnapshot(factory) as snapshot:
        assert snapshot.connection.execute(
            "SELECT count(*) FROM task_outcome_events WHERE task_id=?", (task_id,)
        ).fetchone()[0] == 1
        assert snapshot.connection.execute(
            "SELECT count(*) FROM audit_events WHERE command_id=?", (no_change_command,)
        ).fetchone()[0] == 0


def test_review_task_outcome_rejects_execution_drift_as_review_stale(initialized_database) -> None:
    factory = _factory(initialized_database)
    task_id, task_revision, end_event_id = _ended_task(factory)
    preview = _first_review_preview(factory, task_id=task_id, task_revision=task_revision)

    correction_command = new_uuid4()
    correction_event = new_uuid4()
    with UnitOfWork(factory) as uow:
        uow.connection.execute(
            "INSERT INTO command_receipts(command_id,command_type,request_hash,target_type,target_id,"
            "committed_at_utc,result_type,result_id) VALUES (?,'TestExecutionCorrection',?,'task',?,0,NULL,NULL)",
            (correction_command, "c" * 64, task_id),
        )
        uow.connection.execute(
            "INSERT INTO task_execution_events(execution_event_id,task_id,execution_revision,event_kind,"
            "effective_at_utc,target_event_id,correction_action,reason_code,recorded_at_utc,command_id) "
            "VALUES (?,?,3,'correction',?,?,'replace_time','test',30,?)",
            (correction_event, task_id, 1_980_000_250, end_event_id, correction_command),
        )
        uow.connection.execute(
            "UPDATE task_execution_projection SET actual_end_utc=?,revision=3,last_event_id=? "
            "WHERE task_id=? AND revision=2",
            (1_980_000_250, correction_event, task_id),
        )
        uow.connection.execute(
            "UPDATE tasks SET revision=revision+1 WHERE task_id=? AND revision=?",
            (task_id, task_revision),
        )

    attempted_command = new_uuid4()
    with pytest.raises(SomaError) as stale:
        TaskReviewService(factory).review_task_outcome(
            command_id=attempted_command,
            task_id=task_id,
            task_revision=task_revision,
            execution_revision=2,
            outcome_revision=0,
            current_outcome_event_id=None,
            outcome="completed",
            reason_category=None,
            outcome_review_fingerprint=preview.outcome_review_fingerprint,
        )
    assert stale.value.code == "TASK_REVIEW_STALE"
    with ReadSnapshot(factory) as snapshot:
        assert snapshot.connection.execute(
            "SELECT count(*) FROM command_receipts WHERE command_id=?", (attempted_command,)
        ).fetchone()[0] == 0
        assert snapshot.connection.execute(
            "SELECT count(*) FROM task_outcome_events WHERE task_id=?", (task_id,)
        ).fetchone()[0] == 0


def test_correct_task_outcome_appends_linear_tip_and_rejects_stale_preview(initialized_database) -> None:
    factory = _factory(initialized_database)
    task_id, task_revision, _end_event_id = _ended_task(factory)
    first_preview = _first_review_preview(factory, task_id=task_id, task_revision=task_revision)
    review = TaskReviewService(factory).review_task_outcome(
        command_id=new_uuid4(),
        task_id=task_id,
        task_revision=task_revision,
        execution_revision=2,
        outcome_revision=0,
        current_outcome_event_id=None,
        outcome="completed",
        reason_category=None,
        outcome_review_fingerprint=first_preview.outcome_review_fingerprint,
    )
    genesis_id = review.result_refs[0].result_id

    correction_preview = TaskOutcomeCorrectionQueryService(factory).preview(
        task_id=task_id,
        task_revision=review.revision,
        execution_revision=2,
        current_outcome_revision=1,
        current_outcome_event_id=genesis_id,
        replacement_outcome="incomplete",
        reason_category="work_incomplete",
    )
    service = TaskReviewService(factory)
    corrected = service.correct_task_outcome(
        command_id=new_uuid4(),
        task_id=task_id,
        task_revision=review.revision,
        execution_revision=2,
        current_outcome_revision=1,
        current_outcome_event_id=genesis_id,
        replacement_outcome="incomplete",
        reason_category="work_incomplete",
        correction_review_fingerprint=correction_preview.correction_review_fingerprint,
    )
    assert corrected.outcome == "APPLIED"
    assert corrected.revision == review.revision + 1
    correction_id = corrected.result_refs[0].result_id

    with ReadSnapshot(factory) as snapshot:
        assert snapshot.connection.execute(
            "SELECT accepted_outcome,correction_of_event_id FROM task_outcome_events "
            "WHERE outcome_event_id=?",
            (correction_id,),
        ).fetchone() == ("incomplete", genesis_id)
        assert snapshot.connection.execute(
            "SELECT outcome_event_id,accepted_outcome,revision FROM task_outcome_current WHERE task_id=?",
            (task_id,),
        ).fetchone() == (correction_id, "incomplete", 2)
        assert snapshot.connection.execute(
            "SELECT count(*) FROM task_outcome_events WHERE task_id=?", (task_id,)
        ).fetchone()[0] == 2

    stale_command = new_uuid4()
    with pytest.raises(SomaError) as stale:
        service.correct_task_outcome(
            command_id=stale_command,
            task_id=task_id,
            task_revision=review.revision,
            execution_revision=2,
            current_outcome_revision=1,
            current_outcome_event_id=genesis_id,
            replacement_outcome="incomplete",
            reason_category="work_incomplete",
            correction_review_fingerprint=correction_preview.correction_review_fingerprint,
        )
    assert stale.value.code == "TASK_REVIEW_STALE"
    with ReadSnapshot(factory) as snapshot:
        assert snapshot.connection.execute(
            "SELECT count(*) FROM task_outcome_events WHERE task_id=?", (task_id,)
        ).fetchone()[0] == 2
        assert snapshot.connection.execute(
            "SELECT count(*) FROM command_receipts WHERE command_id=?", (stale_command,)
        ).fetchone()[0] == 0

    no_change_preview = TaskOutcomeCorrectionQueryService(factory).preview(
        task_id=task_id,
        task_revision=corrected.revision,
        execution_revision=2,
        current_outcome_revision=2,
        current_outcome_event_id=correction_id,
        replacement_outcome="incomplete",
        reason_category="work_incomplete",
    )
    assert no_change_preview.semantic_no_change is True
    no_change_command = new_uuid4()
    no_change = service.correct_task_outcome(
        command_id=no_change_command,
        task_id=task_id,
        task_revision=corrected.revision,
        execution_revision=2,
        current_outcome_revision=2,
        current_outcome_event_id=correction_id,
        replacement_outcome="incomplete",
        reason_category="work_incomplete",
        correction_review_fingerprint=no_change_preview.correction_review_fingerprint,
    )
    assert no_change.outcome == "NO_CHANGE"
    assert no_change.revision == corrected.revision
    with ReadSnapshot(factory) as snapshot:
        assert snapshot.connection.execute(
            "SELECT count(*) FROM task_outcome_events WHERE task_id=?", (task_id,)
        ).fetchone()[0] == 2
        assert snapshot.connection.execute(
            "SELECT count(*) FROM audit_events WHERE command_id=?", (no_change_command,)
        ).fetchone()[0] == 0


def test_review_task_outcome_rejects_ineligible_preview_before_receipt(initialized_database) -> None:
    factory = _factory(initialized_database)
    created = TaskPlanningService(factory).create_local_task(
        command_id=new_uuid4(),
        local_task_name="No outcome yet",
        schedule=AcceptedTaskSchedule(
            start_utc=1_981_000_000,
            end_utc=1_981_003_600,
            scheduling_timezone_iana=TZ,
        ),
    )
    started = TaskExecutionService(factory).start_task_execution(
        command_id=new_uuid4(),
        task_id=created.task_id,
        task_revision=created.revision,
        execution_revision=0,
        effective_start_utc=1_981_000_100,
    )
    preview = TaskOutcomeReviewQueryService(factory).preview(
        task_id=created.task_id,
        task_revision=started.revision,
        execution_revision=1,
        outcome_revision=0,
        current_outcome_event_id=None,
        outcome="completed",
        reason_category=None,
    )
    assert preview.eligible is False

    attempted_command = new_uuid4()
    with pytest.raises(SomaError) as invalid:
        TaskReviewService(factory).review_task_outcome(
            command_id=attempted_command,
            task_id=created.task_id,
            task_revision=started.revision,
            execution_revision=1,
            outcome_revision=0,
            current_outcome_event_id=None,
            outcome="completed",
            reason_category=None,
            outcome_review_fingerprint=preview.outcome_review_fingerprint,
        )
    assert invalid.value.code == "TASK_OUTCOME_INVALID_FOR_EXECUTION"
    with ReadSnapshot(factory) as snapshot:
        assert snapshot.connection.execute(
            "SELECT count(*) FROM command_receipts WHERE command_id=?", (attempted_command,)
        ).fetchone()[0] == 0
