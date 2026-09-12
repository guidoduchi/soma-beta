from __future__ import annotations

import pytest

from soma.foundation.errors import SomaError
from soma.foundation.identifiers import new_uuid4
from soma.foundation.persistence.uow import ReadSnapshot, UnitOfWork
from soma.objectives_tasks import AcceptedTaskSchedule, TaskPlanningService
from soma.objectives_tasks.queries.execution_review import TaskExecutionCorrectionQueryService
from soma.objectives_tasks.services.task_execution import TaskExecutionService


TZ = "America/Guayaquil"


def _factory(initialized_database):
    database_path, factory_for_path = initialized_database
    return factory_for_path(database_path)


def _task(factory, *, name: str, start_utc: int):
    return TaskPlanningService(factory).create_local_task(
        command_id=new_uuid4(),
        local_task_name=name,
        schedule=AcceptedTaskSchedule(
            start_utc=start_utc,
            end_utc=start_utc + 3_600,
            scheduling_timezone_iana=TZ,
        ),
    )


def test_execution_correction_command_blocks_governed_terminal_withdraw_before_receipt(
    initialized_database,
) -> None:
    factory = _factory(initialized_database)
    created = _task(factory, name="Governed terminal mutation", start_utc=2_011_000_000)
    event_id = new_uuid4()
    seed_command = new_uuid4()
    with UnitOfWork(factory) as uow:
        uow.connection.execute(
            "INSERT INTO command_receipts(command_id,command_type,request_hash,target_type,target_id,"
            "committed_at_utc,result_type,result_id) VALUES (?,'TestTerminalSeed',?,'task',?,0,NULL,NULL)",
            (seed_command, "b" * 64, created.task_id),
        )
        uow.connection.execute(
            "INSERT INTO task_execution_events(execution_event_id,task_id,execution_revision,event_kind,"
            "effective_at_utc,target_event_id,correction_action,reason_code,recorded_at_utc,command_id) "
            "VALUES (?,?,1,'rfc_terminal_terminate',?,NULL,NULL,'rfc_terminal',20,?)",
            (event_id, created.task_id, 2_011_000_050, seed_command),
        )
        uow.connection.execute(
            "INSERT INTO task_execution_projection(task_id,execution_state,actual_start_utc,actual_end_utc,"
            "effective_termination_utc,termination_reason,revision,last_event_id) "
            "VALUES (?,'terminated',NULL,NULL,?,'rfc_terminal',1,?)",
            (created.task_id, 2_011_000_050, event_id),
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
    assert preview.blockers == ("GOVERNED_TERMINAL_WITHDRAW_FORBIDDEN",)

    attempted_command = new_uuid4()
    with pytest.raises(SomaError) as blocked:
        TaskExecutionService(factory).correct_task_execution_evidence(
            command_id=attempted_command,
            task_id=created.task_id,
            task_revision=created.revision,
            execution_revision=1,
            target_execution_event_id=event_id,
            target_execution_revision=1,
            correction_action="withdraw",
            replacement_effective_at_utc=None,
            reason_category="generic_withdraw",
            correction_review_fingerprint=preview.correction_review_fingerprint,
            accept_outcome_invalidation=False,
        )
    assert blocked.value.code == "TASK_OUTCOME_INVALID_FOR_EXECUTION"
    with ReadSnapshot(factory) as snapshot:
        assert snapshot.connection.execute(
            "SELECT count(*) FROM command_receipts WHERE command_id=?",
            (attempted_command,),
        ).fetchone()[0] == 0
        assert snapshot.connection.execute(
            "SELECT execution_state,revision,last_event_id FROM task_execution_projection WHERE task_id=?",
            (created.task_id,),
        ).fetchone() == ("terminated", 1, event_id)


def test_execution_correction_command_blocks_invalid_corrected_chronology_before_receipt(
    initialized_database,
) -> None:
    factory = _factory(initialized_database)
    created = _task(factory, name="Invalid corrected chronology", start_utc=2_011_010_000)
    execution = TaskExecutionService(factory)
    started = execution.start_task_execution(
        command_id=new_uuid4(),
        task_id=created.task_id,
        task_revision=created.revision,
        execution_revision=0,
        effective_start_utc=2_011_010_100,
    )
    ended = execution.end_task_execution(
        command_id=new_uuid4(),
        task_id=created.task_id,
        task_revision=started.revision,
        execution_revision=1,
        effective_end_utc=2_011_010_200,
    )
    with ReadSnapshot(factory) as snapshot:
        start_id = str(
            snapshot.connection.execute(
                "SELECT execution_event_id FROM task_execution_events "
                "WHERE task_id=? AND execution_revision=1",
                (created.task_id,),
            ).fetchone()[0]
        )

    preview = TaskExecutionCorrectionQueryService(factory).preview(
        task_id=created.task_id,
        task_revision=ended.revision,
        execution_revision=2,
        target_execution_event_id=start_id,
        target_execution_revision=1,
        correction_action="replace_time",
        replacement_effective_at_utc=2_011_010_300,
        reason_category="bad_time",
    )
    assert preview.blockers == ("INVALID_CORRECTED_CHRONOLOGY",)

    attempted_command = new_uuid4()
    with pytest.raises(SomaError) as blocked:
        execution.correct_task_execution_evidence(
            command_id=attempted_command,
            task_id=created.task_id,
            task_revision=ended.revision,
            execution_revision=2,
            target_execution_event_id=start_id,
            target_execution_revision=1,
            correction_action="replace_time",
            replacement_effective_at_utc=2_011_010_300,
            reason_category="bad_time",
            correction_review_fingerprint=preview.correction_review_fingerprint,
            accept_outcome_invalidation=False,
        )
    assert blocked.value.code == "TASK_OUTCOME_INVALID_FOR_EXECUTION"
    with ReadSnapshot(factory) as snapshot:
        assert snapshot.connection.execute(
            "SELECT count(*) FROM command_receipts WHERE command_id=?",
            (attempted_command,),
        ).fetchone()[0] == 0
        assert snapshot.connection.execute(
            "SELECT count(*) FROM task_execution_events WHERE task_id=?",
            (created.task_id,),
        ).fetchone()[0] == 2
