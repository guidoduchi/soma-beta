from __future__ import annotations

import pytest

from soma.foundation.errors import SomaError
from soma.foundation.identifiers import new_uuid4
from soma.foundation.persistence.uow import ReadSnapshot, UnitOfWork
from soma.objectives_tasks import AcceptedTaskSchedule, TaskPlanningService
from soma.objectives_tasks.queries.execution_review import (
    TaskExecutionCorrectionQueryService,
    TaskOutcomeCorrectionQueryService,
)
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
            start_utc=1_970_000_000,
            end_utc=1_970_003_600,
            scheduling_timezone_iana=TZ,
        ),
    )


def _ended_task(factory):
    created = _local_task(factory, name="Execution review")
    execution = TaskExecutionService(factory)
    started = execution.start_task_execution(
        command_id=new_uuid4(),
        task_id=created.task_id,
        task_revision=created.revision,
        execution_revision=0,
        effective_start_utc=1_970_000_100,
    )
    ended = execution.end_task_execution(
        command_id=new_uuid4(),
        task_id=created.task_id,
        task_revision=started.revision,
        execution_revision=1,
        effective_end_utc=1_970_000_200,
    )
    with ReadSnapshot(factory) as snapshot:
        rows = snapshot.connection.execute(
            "SELECT execution_event_id,execution_revision,event_kind "
            "FROM task_execution_events WHERE task_id=? ORDER BY execution_revision",
            (created.task_id,),
        ).fetchall()
    assert len(rows) == 2
    return created.task_id, ended.revision, str(rows[0][0]), str(rows[1][0])


def _seed_completed_outcome(factory, *, task_id: str) -> str:
    event_id = new_uuid4()
    command_id = new_uuid4()
    with UnitOfWork(factory) as uow:
        uow.connection.execute(
            "INSERT INTO command_receipts(command_id,command_type,request_hash,target_type,target_id,"
            "committed_at_utc,result_type,result_id) VALUES (?,'TestOutcomeSeed',?,'task',?,0,NULL,NULL)",
            (command_id, "a" * 64, task_id),
        )
        uow.connection.execute(
            "INSERT INTO task_outcome_events(outcome_event_id,task_id,accepted_outcome,correction_of_event_id,"
            "reason_code,reviewed_at_utc,command_id) VALUES (?,?,'completed',NULL,NULL,10,?)",
            (event_id, task_id, command_id),
        )
        uow.connection.execute(
            "INSERT INTO task_outcome_current(task_id,outcome_event_id,accepted_outcome,reviewed_at_utc,revision,"
            "last_command_id) VALUES (?,?,'completed',10,1,?)",
            (task_id, event_id, command_id),
        )
    return event_id


def test_execution_correction_preview_replaces_end_without_mutation(initialized_database) -> None:
    factory = _factory(initialized_database)
    task_id, task_revision, _start_id, end_id = _ended_task(factory)
    with ReadSnapshot(factory) as snapshot:
        before_receipts = int(snapshot.connection.execute("SELECT count(*) FROM command_receipts").fetchone()[0])
        before_events = int(
            snapshot.connection.execute(
                "SELECT count(*) FROM task_execution_events WHERE task_id=?", (task_id,)
            ).fetchone()[0]
        )

    preview = TaskExecutionCorrectionQueryService(factory).preview(
        task_id=task_id,
        task_revision=task_revision,
        execution_revision=2,
        target_execution_event_id=end_id,
        target_execution_revision=2,
        correction_action="replace_time",
        replacement_effective_at_utc=1_970_000_250,
        reason_category="time_correction",
    )

    assert preview.eligible is True
    assert preview.execution_revision == 2
    assert preview.target_execution_event_id == end_id
    assert preview.target_execution_revision == 2
    assert preview.target_event_kind == "end"
    assert preview.target_effective_at_utc == 1_970_000_200
    assert preview.resulting_execution_state == "ended"
    assert preview.outcome_invalidation_required is False
    assert preview.blockers == ()
    assert len(preview.correction_review_fingerprint) == 64
    with ReadSnapshot(factory) as snapshot:
        assert int(snapshot.connection.execute("SELECT count(*) FROM command_receipts").fetchone()[0]) == before_receipts
        assert int(
            snapshot.connection.execute(
                "SELECT count(*) FROM task_execution_events WHERE task_id=?", (task_id,)
            ).fetchone()[0]
        ) == before_events


def test_execution_correction_preview_flags_outcome_invalidation(initialized_database) -> None:
    factory = _factory(initialized_database)
    task_id, task_revision, _start_id, end_id = _ended_task(factory)
    outcome_id = _seed_completed_outcome(factory, task_id=task_id)

    preview = TaskExecutionCorrectionQueryService(factory).preview(
        task_id=task_id,
        task_revision=task_revision,
        execution_revision=2,
        target_execution_event_id=end_id,
        target_execution_revision=2,
        correction_action="withdraw",
        replacement_effective_at_utc=None,
        reason_category="remove_false_end",
    )

    assert preview.eligible is True
    assert preview.resulting_execution_state == "in_progress"
    assert preview.outcome_invalidation_required is True
    assert preview.current_outcome_revision == 1
    assert preview.current_outcome_event_id == outcome_id


def test_execution_correction_preview_blocks_governed_terminal_withdraw(initialized_database) -> None:
    factory = _factory(initialized_database)
    created = _local_task(factory, name="Governed terminal")
    event_id = new_uuid4()
    command_id = new_uuid4()
    with UnitOfWork(factory) as uow:
        uow.connection.execute(
            "INSERT INTO command_receipts(command_id,command_type,request_hash,target_type,target_id,"
            "committed_at_utc,result_type,result_id) VALUES (?,'TestTerminalSeed',?,'task',?,0,NULL,NULL)",
            (command_id, "b" * 64, created.task_id),
        )
        uow.connection.execute(
            "INSERT INTO task_execution_events(execution_event_id,task_id,execution_revision,event_kind,"
            "effective_at_utc,target_event_id,correction_action,reason_code,recorded_at_utc,command_id) "
            "VALUES (?,?,1,'rfc_terminal_terminate',?,NULL,NULL,'rfc_terminal',20,?)",
            (event_id, created.task_id, 1_970_000_050, command_id),
        )
        uow.connection.execute(
            "INSERT INTO task_execution_projection(task_id,execution_state,actual_start_utc,actual_end_utc,"
            "effective_termination_utc,termination_reason,revision,last_event_id) "
            "VALUES (?,'terminated',NULL,NULL,?,'rfc_terminal',1,?)",
            (created.task_id, 1_970_000_050, event_id),
        )

    preview = TaskExecutionCorrectionQueryService(factory).preview(
        task_id=created.task_id,
        task_revision=created.revision,
        execution_revision=1,
        target_execution_event_id=event_id,
        target_execution_revision=1,
        correction_action="withdraw",
        replacement_effective_at_utc=None,
        reason_category="generic_withdraw",
    )

    assert preview.eligible is False
    assert preview.blockers == ("GOVERNED_TERMINAL_WITHDRAW_FORBIDDEN",)


def test_execution_correction_preview_blocks_invalid_corrected_chronology(initialized_database) -> None:
    factory = _factory(initialized_database)
    task_id, task_revision, start_id, _end_id = _ended_task(factory)

    preview = TaskExecutionCorrectionQueryService(factory).preview(
        task_id=task_id,
        task_revision=task_revision,
        execution_revision=2,
        target_execution_event_id=start_id,
        target_execution_revision=1,
        correction_action="replace_time",
        replacement_effective_at_utc=1_970_000_300,
        reason_category="bad_time",
    )

    assert preview.eligible is False
    assert preview.blockers == ("INVALID_CORRECTED_CHRONOLOGY",)
    assert preview.resulting_execution_state == "ended"


def test_outcome_correction_preview_binds_current_tip_and_precise_no_change(initialized_database) -> None:
    factory = _factory(initialized_database)
    task_id, task_revision, _start_id, _end_id = _ended_task(factory)
    outcome_id = _seed_completed_outcome(factory, task_id=task_id)
    service = TaskOutcomeCorrectionQueryService(factory)

    same = service.preview(
        task_id=task_id,
        task_revision=task_revision,
        execution_revision=2,
        current_outcome_revision=1,
        current_outcome_event_id=outcome_id,
        replacement_outcome="completed",
        reason_category=None,
    )
    assert same.eligible is True
    assert same.semantic_no_change is True
    assert same.blockers == ()

    changed = service.preview(
        task_id=task_id,
        task_revision=task_revision,
        execution_revision=2,
        current_outcome_revision=1,
        current_outcome_event_id=outcome_id,
        replacement_outcome="incomplete",
        reason_category="work_incomplete",
    )
    assert changed.eligible is True
    assert changed.semantic_no_change is False
    assert changed.current_outcome_event_id == outcome_id
    assert len(changed.correction_review_fingerprint) == 64

    invalid = service.preview(
        task_id=task_id,
        task_revision=task_revision,
        execution_revision=2,
        current_outcome_revision=1,
        current_outcome_event_id=outcome_id,
        replacement_outcome="cancelled_without_execution",
        reason_category="wrong_outcome",
    )
    assert invalid.eligible is False
    assert invalid.blockers == ("OUTCOME_INVALID_FOR_EXECUTION",)

    with pytest.raises(SomaError) as stale:
        service.preview(
            task_id=task_id,
            task_revision=task_revision,
            execution_revision=2,
            current_outcome_revision=2,
            current_outcome_event_id=outcome_id,
            replacement_outcome="completed",
            reason_category=None,
        )
    assert stale.value.code == "TASK_STALE"
