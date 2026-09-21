from __future__ import annotations

import json

import pytest

from soma.foundation.errors import IntegrityFailure, SomaError, ValidationError
from soma.foundation.identifiers import new_uuid4
from soma.foundation.persistence.uow import ReadSnapshot, UnitOfWork
from soma.objectives_tasks import AcceptedTaskSchedule, TaskPlanningService
from soma.objectives_tasks.services.task_execution import TaskExecutionService


TZ = "America/Guayaquil"


def _factory(initialized_database):
    database_path, factory_for_path = initialized_database
    return factory_for_path(database_path)


def _create_task(factory, *, ordinal: int):
    creation_command = new_uuid4()
    created = TaskPlanningService(factory).create_local_task(
        command_id=creation_command,
        local_task_name=f"End execution {ordinal}",
        schedule=AcceptedTaskSchedule(
            start_utc=1_970_000_000 + ordinal * 100,
            end_utc=1_970_003_600 + ordinal * 100,
            scheduling_timezone_iana=TZ,
        ),
    )
    with ReadSnapshot(factory) as snapshot:
        plan = snapshot.connection.execute(
            "SELECT pc.plan_revision_id,p.start_utc,p.end_utc FROM task_plan_current pc "
            "JOIN task_plan_revisions p ON p.plan_revision_id=pc.plan_revision_id WHERE pc.task_id=?",
            (created.task_id,),
        ).fetchone()
        assert plan is not None
        return creation_command, created.task_id, str(plan[0]), int(plan[1]), int(plan[2])


def _seed_single_task_objective(factory, row):
    creation_command, task_id, plan_id, start_utc, end_utc = row
    objective_id = new_uuid4()
    event_id = new_uuid4()
    tracking_sequence = 96_500_000 + int(objective_id[-4:], 16) % 400_000
    with UnitOfWork(factory) as uow:
        uow.connection.execute(
            "INSERT INTO objectives(objective_id,tracking_sequence,tracking_id,creation_origin,"
            "superseded_by_objective_id,revision,created_at_utc,created_command_id) "
            "VALUES (?,?,?,'manual',NULL,1,1,?)",
            (objective_id, tracking_sequence, f"MW-{tracking_sequence:08d}", creation_command),
        )
        uow.connection.execute(
            "INSERT INTO objective_membership_events(membership_event_id,task_id,event_kind,from_objective_id,"
            "to_objective_id,accepted_plan_revision_id,grouping_proposal_id,reason_code,recorded_at_utc,command_id) "
            "VALUES (?,?,'add',NULL,?,?,NULL,NULL,1,?)",
            (event_id, task_id, objective_id, plan_id, creation_command),
        )
        uow.connection.execute(
            "INSERT INTO objective_task_membership_current(task_id,objective_id,accepted_plan_revision_id,"
            "membership_revision,last_event_id,last_command_id) VALUES (?,?,?,1,?,?)",
            (task_id, objective_id, plan_id, event_id, creation_command),
        )
        uow.connection.execute(
            "INSERT INTO objective_envelope_projection(objective_id,start_utc,end_utc,member_count,"
            "membership_input_fingerprint,revision,last_command_id) VALUES (?,?,?,?,?,1,?)",
            (objective_id, start_utc, end_utc, 1, "a" * 64, creation_command),
        )
        uow.connection.execute(
            "INSERT INTO objective_aggregate_projection(objective_id,execution_state,aggregate_outcome,"
            "actual_start_utc,actual_end_utc,attention_reason,included_task_count,excluded_task_count,"
            "aggregate_input_fingerprint,revision,last_command_id) "
            "VALUES (?,'planned',NULL,NULL,NULL,NULL,1,0,?,1,?)",
            (objective_id, "b" * 64, creation_command),
        )
    return objective_id


def test_end_task_execution_appends_end_without_fabricating_outcome_and_replays(initialized_database) -> None:
    factory = _factory(initialized_database)
    row = _create_task(factory, ordinal=1)
    service = TaskExecutionService(factory)
    accepted_start = 1_970_000_200
    service.start_task_execution(
        command_id=new_uuid4(), task_id=row[1], task_revision=1,
        execution_revision=0, effective_start_utc=accepted_start,
    )
    command_id = new_uuid4()
    accepted_end = accepted_start + 300
    ended = service.end_task_execution(
        command_id=command_id,
        task_id=row[1],
        task_revision=2,
        execution_revision=1,
        effective_end_utc=accepted_end,
    )
    assert ended.outcome == "APPLIED"
    assert ended.revision == 3
    assert not ended.replayed
    assert len(ended.result_refs) == 1
    event_id = ended.result_refs[0].result_id

    with ReadSnapshot(factory) as snapshot:
        assert tuple(snapshot.connection.execute(
            "SELECT event_kind,effective_at_utc,target_event_id,correction_action,reason_code,command_id "
            "FROM task_execution_events WHERE execution_event_id=?", (event_id,)
        ).fetchone()) == ("end", accepted_end, None, None, None, command_id)
        assert tuple(snapshot.connection.execute(
            "SELECT execution_state,actual_start_utc,actual_end_utc,effective_termination_utc,termination_reason,"
            "revision,last_event_id FROM task_execution_projection WHERE task_id=?", (row[1],)
        ).fetchone()) == ("ended", accepted_start, accepted_end, None, None, 2, event_id)
        assert snapshot.connection.execute(
            "SELECT revision FROM tasks WHERE task_id=?", (row[1],)
        ).fetchone()[0] == 3
        assert snapshot.connection.execute(
            "SELECT 1 FROM task_outcome_current WHERE task_id=?", (row[1],)
        ).fetchone() is None
        audit = snapshot.connection.execute(
            "SELECT payload_json FROM audit_events WHERE command_id=? AND action_type='task.execution_changed'",
            (command_id,),
        ).fetchone()
        assert audit is not None
        assert json.loads(str(audit[0])) == {
            "effective_at_utc": accepted_end,
            "event_kind": "end",
            "execution_event_id": event_id,
            "reason_category": None,
            "resulting_execution_revision": 2,
            "resulting_task_revision": 3,
            "target_event_id": None,
            "task_id": row[1],
        }

    with UnitOfWork(factory) as uow:
        uow.connection.execute("UPDATE tasks SET revision=revision+1 WHERE task_id=?", (row[1],))
    replay = service.end_task_execution(
        command_id=command_id,
        task_id=row[1],
        task_revision=2,
        execution_revision=1,
        effective_end_utc=accepted_end,
    )
    assert replay.replayed
    assert replay.revision == ended.revision
    assert replay.result_refs == ended.result_refs
    with ReadSnapshot(factory) as snapshot:
        assert snapshot.connection.execute(
            "SELECT count(*) FROM task_execution_events WHERE task_id=?", (row[1],)
        ).fetchone()[0] == 2


def test_end_task_execution_distinguishes_stale_not_started_and_terminal(initialized_database) -> None:
    factory = _factory(initialized_database)
    row = _create_task(factory, ordinal=2)
    service = TaskExecutionService(factory)

    stale_command = new_uuid4()
    with pytest.raises(SomaError) as stale:
        service.end_task_execution(
            command_id=stale_command, task_id=row[1], task_revision=1,
            execution_revision=1, effective_end_utc=1_970_000_500,
        )
    assert stale.value.code == "TASK_STALE"

    original_start_id = new_uuid4()
    correction_id = new_uuid4()
    with UnitOfWork(factory) as uow:
        uow.connection.execute(
            "INSERT INTO task_execution_events(execution_event_id,task_id,execution_revision,event_kind,effective_at_utc,target_event_id,"
            "correction_action,reason_code,recorded_at_utc,command_id) VALUES (?,?,1,'start',?,NULL,NULL,NULL,1,?)",
            (original_start_id, row[1], 1_970_000_300, row[0]),
        )
        uow.connection.execute(
            "INSERT INTO task_execution_events(execution_event_id,task_id,execution_revision,event_kind,effective_at_utc,target_event_id,"
            "correction_action,reason_code,recorded_at_utc,command_id) VALUES (?,?,2,'correction',NULL,?,'withdraw','test',2,?)",
            (correction_id, row[1], original_start_id, row[0]),
        )
        uow.connection.execute(
            "INSERT INTO task_execution_projection(task_id,execution_state,actual_start_utc,actual_end_utc,"
            "effective_termination_utc,termination_reason,revision,last_event_id) "
            "VALUES (?,'not_started',NULL,NULL,NULL,NULL,2,?)",
            (row[1], correction_id),
        )
        uow.connection.execute("UPDATE tasks SET revision=2 WHERE task_id=?", (row[1],))
    not_started_command = new_uuid4()
    with pytest.raises(SomaError) as not_started:
        service.end_task_execution(
            command_id=not_started_command, task_id=row[1], task_revision=2,
            execution_revision=2, effective_end_utc=1_970_000_500,
        )
    assert not_started.value.code == "TASK_EXECUTION_NOT_STARTED"

    # Re-start the corrected Task, then end it once and prove a second end is terminal.
    service.start_task_execution(
        command_id=new_uuid4(), task_id=row[1], task_revision=2,
        execution_revision=2, effective_start_utc=1_970_000_400,
    )
    service.end_task_execution(
        command_id=new_uuid4(), task_id=row[1], task_revision=3,
        execution_revision=3, effective_end_utc=1_970_000_500,
    )
    terminal_command = new_uuid4()
    with pytest.raises(SomaError) as terminal:
        service.end_task_execution(
            command_id=terminal_command, task_id=row[1], task_revision=4,
            execution_revision=4, effective_end_utc=1_970_000_600,
        )
    assert terminal.value.code == "TASK_EXECUTION_ALREADY_TERMINAL"

    with ReadSnapshot(factory) as snapshot:
        for command_id in (stale_command, not_started_command, terminal_command):
            assert snapshot.connection.execute(
                "SELECT 1 FROM command_receipts WHERE command_id=?", (command_id,)
            ).fetchone() is None


def test_end_before_current_start_is_rejected_before_receipt(initialized_database) -> None:
    factory = _factory(initialized_database)
    row = _create_task(factory, ordinal=3)
    service = TaskExecutionService(factory)
    accepted_start = 1_970_001_000
    service.start_task_execution(
        command_id=new_uuid4(), task_id=row[1], task_revision=1,
        execution_revision=0, effective_start_utc=accepted_start,
    )
    command_id = new_uuid4()
    with pytest.raises(ValidationError):
        service.end_task_execution(
            command_id=command_id, task_id=row[1], task_revision=2,
            execution_revision=1, effective_end_utc=accepted_start - 1,
        )
    with ReadSnapshot(factory) as snapshot:
        assert snapshot.connection.execute(
            "SELECT 1 FROM command_receipts WHERE command_id=?", (command_id,)
        ).fetchone() is None
        assert snapshot.connection.execute(
            "SELECT count(*) FROM task_execution_events WHERE task_id=?", (row[1],)
        ).fetchone()[0] == 1


def test_end_member_task_rebuilds_objective_to_awaiting_review_without_outcome(initialized_database) -> None:
    factory = _factory(initialized_database)
    row = _create_task(factory, ordinal=4)
    objective_id = _seed_single_task_objective(factory, row)
    service = TaskExecutionService(factory)
    accepted_start = 1_970_001_500
    service.start_task_execution(
        command_id=new_uuid4(), task_id=row[1], task_revision=1,
        execution_revision=0, effective_start_utc=accepted_start,
    )
    command_id = new_uuid4()
    accepted_end = accepted_start + 200
    service.end_task_execution(
        command_id=command_id, task_id=row[1], task_revision=2,
        execution_revision=1, effective_end_utc=accepted_end,
    )
    with ReadSnapshot(factory) as snapshot:
        aggregate = snapshot.connection.execute(
            "SELECT execution_state,aggregate_outcome,actual_start_utc,actual_end_utc,attention_reason,revision,last_command_id "
            "FROM objective_aggregate_projection WHERE objective_id=?", (objective_id,)
        ).fetchone()
        assert tuple(aggregate) == (
            "awaiting_review", None, accepted_start, accepted_end,
            "lost_last_executable", 3, command_id,
        )
        assert snapshot.connection.execute(
            "SELECT 1 FROM task_outcome_current WHERE task_id=?", (row[1],)
        ).fetchone() is None


def test_end_audit_failure_rolls_back_end_task_and_objective_aggregate(initialized_database, monkeypatch) -> None:
    factory = _factory(initialized_database)
    row = _create_task(factory, ordinal=5)
    objective_id = _seed_single_task_objective(factory, row)
    service = TaskExecutionService(factory)
    accepted_start = 1_970_002_000
    service.start_task_execution(
        command_id=new_uuid4(), task_id=row[1], task_revision=1,
        execution_revision=0, effective_start_utc=accepted_start,
    )
    with ReadSnapshot(factory) as snapshot:
        before_projection = tuple(snapshot.connection.execute(
            "SELECT execution_state,actual_start_utc,actual_end_utc,revision,last_event_id "
            "FROM task_execution_projection WHERE task_id=?", (row[1],)
        ).fetchone())
        before_aggregate = tuple(snapshot.connection.execute(
            "SELECT execution_state,actual_end_utc,attention_reason,revision,last_command_id "
            "FROM objective_aggregate_projection WHERE objective_id=?", (objective_id,)
        ).fetchone())

    def fail_audit(_uow, _event):
        raise IntegrityFailure("injected end audit failure")

    monkeypatch.setattr(service._boundary._audit_writer, "write", fail_audit)
    command_id = new_uuid4()
    with pytest.raises(IntegrityFailure):
        service.end_task_execution(
            command_id=command_id, task_id=row[1], task_revision=2,
            execution_revision=1, effective_end_utc=accepted_start + 100,
        )

    with ReadSnapshot(factory) as snapshot:
        assert snapshot.connection.execute(
            "SELECT revision FROM tasks WHERE task_id=?", (row[1],)
        ).fetchone()[0] == 2
        assert tuple(snapshot.connection.execute(
            "SELECT execution_state,actual_start_utc,actual_end_utc,revision,last_event_id "
            "FROM task_execution_projection WHERE task_id=?", (row[1],)
        ).fetchone()) == before_projection
        assert snapshot.connection.execute(
            "SELECT count(*) FROM task_execution_events WHERE task_id=?", (row[1],)
        ).fetchone()[0] == 1
        assert tuple(snapshot.connection.execute(
            "SELECT execution_state,actual_end_utc,attention_reason,revision,last_command_id "
            "FROM objective_aggregate_projection WHERE objective_id=?", (objective_id,)
        ).fetchone()) == before_aggregate
        assert snapshot.connection.execute(
            "SELECT 1 FROM command_receipts WHERE command_id=?", (command_id,)
        ).fetchone() is None
        assert snapshot.connection.execute(
            "SELECT 1 FROM command_receipt_results WHERE command_id=?", (command_id,)
        ).fetchone() is None
