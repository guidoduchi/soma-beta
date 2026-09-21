from __future__ import annotations

import pytest

from soma.foundation.errors import IntegrityFailure, SomaError
from soma.foundation.identifiers import new_uuid4
from soma.foundation.persistence.uow import ReadSnapshot, UnitOfWork
from soma.objectives_tasks import AcceptedTaskSchedule, TaskPlanningService
from soma.objectives_tasks.queries.execution_review import TaskOutcomeReviewQueryService
from soma.objectives_tasks.services.task_execution import TaskExecutionService


TZ = "America/Guayaquil"


def _factory(initialized_database):
    database_path, factory_for_path = initialized_database
    return factory_for_path(database_path)


def _ended_task(factory):
    created = TaskPlanningService(factory).create_local_task(
        command_id=new_uuid4(),
        local_task_name="Outcome preview",
        schedule=AcceptedTaskSchedule(
            start_utc=1_960_000_000,
            end_utc=1_960_003_600,
            scheduling_timezone_iana=TZ,
        ),
    )
    execution = TaskExecutionService(factory)
    started = execution.start_task_execution(
        command_id=new_uuid4(),
        task_id=created.task_id,
        task_revision=created.revision,
        execution_revision=0,
        effective_start_utc=1_960_000_100,
    )
    ended = execution.end_task_execution(
        command_id=new_uuid4(),
        task_id=created.task_id,
        task_revision=started.revision,
        execution_revision=1,
        effective_end_utc=1_960_000_200,
    )
    return created.task_id, ended.revision


def test_outcome_review_preview_is_pure_and_eligible_for_first_completed_review(initialized_database) -> None:
    factory = _factory(initialized_database)
    task_id, task_revision = _ended_task(factory)
    with ReadSnapshot(factory) as snapshot:
        before_receipts = int(snapshot.connection.execute("SELECT count(*) FROM command_receipts").fetchone()[0])
        before_audit = int(snapshot.connection.execute("SELECT count(*) FROM audit_events").fetchone()[0])

    preview = TaskOutcomeReviewQueryService(factory).preview(
        task_id=task_id,
        task_revision=task_revision,
        execution_revision=2,
        outcome_revision=0,
        current_outcome_event_id=None,
        outcome="completed",
        reason_category=None,
    )

    assert preview.eligible is True
    assert preview.current_outcome_revision == 0
    assert preview.current_outcome_event_id is None
    assert preview.semantic_no_change is False
    assert preview.blockers == ()
    assert len(preview.fingerprint) == 64
    with ReadSnapshot(factory) as snapshot:
        assert int(snapshot.connection.execute("SELECT count(*) FROM command_receipts").fetchone()[0]) == before_receipts
        assert int(snapshot.connection.execute("SELECT count(*) FROM audit_events").fetchone()[0]) == before_audit
        assert snapshot.connection.execute(
            "SELECT count(*) FROM task_outcome_events WHERE task_id=?", (task_id,)
        ).fetchone()[0] == 0


def test_outcome_review_preview_reconciles_linear_current_chain_and_precise_no_change(initialized_database) -> None:
    factory = _factory(initialized_database)
    task_id, task_revision = _ended_task(factory)
    event_id = new_uuid4()
    command_id = new_uuid4()
    with UnitOfWork(factory) as uow:
        uow.connection.execute(
            "INSERT INTO command_receipts(command_id,command_type,request_hash,target_type,target_id,committed_at_utc,result_type,result_id) "
            "VALUES (?,'TestOutcomeSeed',?,'task',?,0,NULL,NULL)",
            (command_id, "0" * 64, task_id),
        )
        uow.connection.execute(
            "INSERT INTO task_outcome_events(outcome_event_id,task_id,accepted_outcome,correction_of_event_id,reason_code,"
            "reviewed_at_utc,command_id) VALUES (?,?,'completed',NULL,NULL,10,?)",
            (event_id, task_id, command_id),
        )
        uow.connection.execute(
            "INSERT INTO task_outcome_current(task_id,outcome_event_id,accepted_outcome,reviewed_at_utc,revision,last_command_id) "
            "VALUES (?,?,'completed',10,1,?)",
            (task_id, event_id, command_id),
        )

    preview = TaskOutcomeReviewQueryService(factory).preview(
        task_id=task_id,
        task_revision=task_revision,
        execution_revision=2,
        outcome_revision=1,
        current_outcome_event_id=event_id,
        outcome="completed",
        reason_category=None,
    )
    assert preview.eligible is True
    assert preview.semantic_no_change is True
    assert preview.blockers == ()

    with pytest.raises(SomaError) as stale:
        TaskOutcomeReviewQueryService(factory).preview(
            task_id=task_id,
            task_revision=task_revision,
            execution_revision=2,
            outcome_revision=0,
            current_outcome_event_id=None,
            outcome="completed",
            reason_category=None,
        )
    assert stale.value.code == "TASK_STALE"


def test_outcome_review_preview_fails_closed_on_noncurrent_outcome_history(initialized_database) -> None:
    factory = _factory(initialized_database)
    task_id, task_revision = _ended_task(factory)
    genesis_id = new_uuid4()
    trailing_id = new_uuid4()
    command_id = new_uuid4()
    with UnitOfWork(factory) as uow:
        uow.connection.execute(
            "INSERT INTO command_receipts(command_id,command_type,request_hash,target_type,target_id,committed_at_utc,result_type,result_id) "
            "VALUES (?,'TestOutcomeSeed',?,'task',?,0,NULL,NULL)",
            (command_id, "1" * 64, task_id),
        )
        uow.connection.execute(
            "INSERT INTO task_outcome_events VALUES (?,?,'completed',NULL,NULL,10,?)",
            (genesis_id, task_id, command_id),
        )
        uow.connection.execute(
            "INSERT INTO task_outcome_current VALUES (?,?,'completed',10,1,?)",
            (task_id, genesis_id, command_id),
        )
        uow.connection.execute(
            "INSERT INTO task_outcome_events VALUES (?,?,'incomplete',?,'manual_review',11,?)",
            (trailing_id, task_id, genesis_id, command_id),
        )

    with pytest.raises(IntegrityFailure, match="revision does not equal immutable chain length"):
        TaskOutcomeReviewQueryService(factory).preview(
            task_id=task_id,
            task_revision=task_revision,
            execution_revision=2,
            outcome_revision=1,
            current_outcome_event_id=genesis_id,
            outcome="completed",
            reason_category=None,
        )
