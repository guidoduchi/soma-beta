from __future__ import annotations

import json

import pytest

from soma.foundation.errors import SomaError
from soma.foundation.identifiers import new_uuid4
from soma.foundation.persistence.uow import ReadSnapshot, UnitOfWork
from soma.objectives_tasks import AcceptedTaskSchedule, TaskPlanningService
from soma.objectives_tasks.services.task_execution import TaskExecutionService


TZ = "America/Guayaquil"


def _factory(initialized_database):
    database_path, factory_for_path = initialized_database
    return factory_for_path(database_path)


def _local_task(factory, *, name: str):
    return TaskPlanningService(factory).create_local_task(
        command_id=new_uuid4(),
        local_task_name=name,
        schedule=AcceptedTaskSchedule(
            start_utc=1_990_000_000,
            end_utc=1_990_003_600,
            scheduling_timezone_iana=TZ,
        ),
    )


def test_cancel_task_without_execution_is_atomic_and_replay_exact(initialized_database) -> None:
    factory = _factory(initialized_database)
    created = _local_task(factory, name="Cancel pristine")
    command_id = new_uuid4()
    service = TaskExecutionService(factory)

    applied = service.cancel_task_without_execution(
        command_id=command_id,
        task_id=created.task_id,
        task_revision=created.revision,
        execution_revision=0,
        outcome_revision=0,
        effective_cancel_utc=1_990_000_100,
        reason_category="operator_cancel",
    )
    assert applied.outcome == "APPLIED"
    assert applied.revision == created.revision + 1
    assert applied.replayed is False
    assert {ref.result_type for ref in applied.result_refs} == {
        "task_execution_event",
        "task_outcome_event",
    }

    replay = service.cancel_task_without_execution(
        command_id=command_id,
        task_id=created.task_id,
        task_revision=created.revision,
        execution_revision=0,
        outcome_revision=0,
        effective_cancel_utc=1_990_000_100,
        reason_category="operator_cancel",
    )
    assert replay.replayed is True
    assert replay.revision == applied.revision
    assert replay.result_refs == applied.result_refs

    with ReadSnapshot(factory) as snapshot:
        assert snapshot.connection.execute(
            "SELECT execution_state,actual_start_utc,actual_end_utc,effective_termination_utc,revision "
            "FROM task_execution_projection WHERE task_id=?",
            (created.task_id,),
        ).fetchone() == ("terminated", None, None, 1_990_000_100, 1)
        outcome = snapshot.connection.execute(
            "SELECT c.accepted_outcome,c.revision,e.correction_of_event_id "
            "FROM task_outcome_current c JOIN task_outcome_events e "
            "ON e.outcome_event_id=c.outcome_event_id WHERE c.task_id=?",
            (created.task_id,),
        ).fetchone()
        assert outcome == ("cancelled_without_execution", 1, None)
        assert snapshot.connection.execute(
            "SELECT count(*) FROM task_execution_events WHERE task_id=?", (created.task_id,)
        ).fetchone()[0] == 1
        assert snapshot.connection.execute(
            "SELECT count(*) FROM task_outcome_events WHERE task_id=?", (created.task_id,)
        ).fetchone()[0] == 1
        assert snapshot.connection.execute(
            "SELECT count(*) FROM audit_events WHERE command_id=?", (command_id,)
        ).fetchone()[0] == 2
        receipt = snapshot.connection.execute(
            "SELECT request_hash FROM command_receipts WHERE command_id=?", (command_id,)
        ).fetchone()
        outcome_audit = snapshot.connection.execute(
            "SELECT payload_json FROM audit_events WHERE command_id=? AND action_type='task.outcome_reviewed'",
            (command_id,),
        ).fetchone()
        assert receipt is not None and outcome_audit is not None
        payload = json.loads(str(outcome_audit[0]))
        assert payload["review_fingerprint"] == str(receipt[0])


def test_cancel_accepts_positive_corrected_not_started_authority(initialized_database) -> None:
    factory = _factory(initialized_database)
    created = _local_task(factory, name="Cancel corrected not started")
    execution = TaskExecutionService(factory)
    started = execution.start_task_execution(
        command_id=new_uuid4(),
        task_id=created.task_id,
        task_revision=created.revision,
        execution_revision=0,
        effective_start_utc=1_990_000_100,
    )
    with ReadSnapshot(factory) as snapshot:
        start_event_id = str(
            snapshot.connection.execute(
                "SELECT execution_event_id FROM task_execution_events WHERE task_id=? AND execution_revision=1",
                (created.task_id,),
            ).fetchone()[0]
        )

    correction_command = new_uuid4()
    correction_event = new_uuid4()
    with UnitOfWork(factory) as uow:
        uow.connection.execute(
            "INSERT INTO command_receipts(command_id,command_type,request_hash,target_type,target_id,"
            "committed_at_utc,result_type,result_id) VALUES (?,'TestWithdrawStart',?,'task',?,0,NULL,NULL)",
            (correction_command, "d" * 64, created.task_id),
        )
        uow.connection.execute(
            "INSERT INTO task_execution_events(execution_event_id,task_id,execution_revision,event_kind,"
            "effective_at_utc,target_event_id,correction_action,reason_code,recorded_at_utc,command_id) "
            "VALUES (?,?,2,'correction',NULL,?,'withdraw','false_start',20,?)",
            (correction_event, created.task_id, start_event_id, correction_command),
        )
        uow.connection.execute(
            "UPDATE task_execution_projection SET execution_state='not_started',actual_start_utc=NULL,"
            "actual_end_utc=NULL,effective_termination_utc=NULL,termination_reason=NULL,revision=2,last_event_id=? "
            "WHERE task_id=? AND revision=1",
            (correction_event, created.task_id),
        )
        uow.connection.execute(
            "UPDATE tasks SET revision=revision+1 WHERE task_id=? AND revision=?",
            (created.task_id, started.revision),
        )

    applied = execution.cancel_task_without_execution(
        command_id=new_uuid4(),
        task_id=created.task_id,
        task_revision=started.revision + 1,
        execution_revision=2,
        outcome_revision=0,
        effective_cancel_utc=1_990_000_300,
        reason_category="operator_cancel",
    )
    assert applied.outcome == "APPLIED"
    with ReadSnapshot(factory) as snapshot:
        assert snapshot.connection.execute(
            "SELECT execution_state,revision FROM task_execution_projection WHERE task_id=?",
            (created.task_id,),
        ).fetchone() == ("terminated", 3)
        assert snapshot.connection.execute(
            "SELECT execution_revision,event_kind FROM task_execution_events "
            "WHERE task_id=? ORDER BY execution_revision DESC LIMIT 1",
            (created.task_id,),
        ).fetchone() == (3, "manual_cancel")


def test_cancel_after_concurrent_start_returns_domain_specific_conflict(initialized_database) -> None:
    factory = _factory(initialized_database)
    created = _local_task(factory, name="Concurrent start")
    execution = TaskExecutionService(factory)
    execution.start_task_execution(
        command_id=new_uuid4(),
        task_id=created.task_id,
        task_revision=created.revision,
        execution_revision=0,
        effective_start_utc=1_990_000_100,
    )

    attempted_command = new_uuid4()
    with pytest.raises(SomaError) as conflict:
        execution.cancel_task_without_execution(
            command_id=attempted_command,
            task_id=created.task_id,
            task_revision=created.revision,
            execution_revision=0,
            outcome_revision=0,
            effective_cancel_utc=1_990_000_200,
            reason_category="operator_cancel",
        )
    assert conflict.value.code == "TASK_CANCEL_AFTER_START"
    with ReadSnapshot(factory) as snapshot:
        assert snapshot.connection.execute(
            "SELECT count(*) FROM command_receipts WHERE command_id=?", (attempted_command,)
        ).fetchone()[0] == 0
        assert snapshot.connection.execute(
            "SELECT count(*) FROM task_outcome_events WHERE task_id=?", (created.task_id,)
        ).fetchone()[0] == 0
        assert snapshot.connection.execute(
            "SELECT execution_state,revision FROM task_execution_projection WHERE task_id=?",
            (created.task_id,),
        ).fetchone() == ("in_progress", 1)


def test_cancel_rejects_existing_outcome_history_before_receipt(initialized_database) -> None:
    factory = _factory(initialized_database)
    created = _local_task(factory, name="Existing outcome")
    seed_command = new_uuid4()
    outcome_event_id = new_uuid4()
    with UnitOfWork(factory) as uow:
        uow.connection.execute(
            "INSERT INTO command_receipts(command_id,command_type,request_hash,target_type,target_id,"
            "committed_at_utc,result_type,result_id) VALUES (?,'TestOutcomeSeed',?,'task',?,0,NULL,NULL)",
            (seed_command, "e" * 64, created.task_id),
        )
        uow.connection.execute(
            "INSERT INTO task_outcome_events(outcome_event_id,task_id,accepted_outcome,correction_of_event_id,"
            "reason_code,reviewed_at_utc,command_id) VALUES (?,?,'cancelled_without_execution',NULL,'seed',10,?)",
            (outcome_event_id, created.task_id, seed_command),
        )
        uow.connection.execute(
            "INSERT INTO task_outcome_current(task_id,outcome_event_id,accepted_outcome,reviewed_at_utc,revision,last_command_id) "
            "VALUES (?,?,'cancelled_without_execution',10,1,?)",
            (created.task_id, outcome_event_id, seed_command),
        )

    attempted_command = new_uuid4()
    with pytest.raises(SomaError) as terminal:
        TaskExecutionService(factory).cancel_task_without_execution(
            command_id=attempted_command,
            task_id=created.task_id,
            task_revision=created.revision,
            execution_revision=0,
            outcome_revision=0,
            effective_cancel_utc=1_990_000_200,
            reason_category="operator_cancel",
        )
    assert terminal.value.code == "TASK_EXECUTION_ALREADY_TERMINAL"
    with ReadSnapshot(factory) as snapshot:
        assert snapshot.connection.execute(
            "SELECT count(*) FROM command_receipts WHERE command_id=?", (attempted_command,)
        ).fetchone()[0] == 0
        assert snapshot.connection.execute(
            "SELECT count(*) FROM task_execution_events WHERE task_id=?", (created.task_id,)
        ).fetchone()[0] == 0
