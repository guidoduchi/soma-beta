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


def _create_scheduled_task(factory, *, command_id: str | None = None, ordinal: int = 1):
    creation_command = command_id or new_uuid4()
    result = TaskPlanningService(factory).create_local_task(
        command_id=creation_command,
        local_task_name=f"Execution task {ordinal}",
        schedule=AcceptedTaskSchedule(
            start_utc=1_940_000_000 + ordinal * 10_000,
            end_utc=1_940_003_600 + ordinal * 10_000,
            scheduling_timezone_iana=TZ,
        ),
    )
    with ReadSnapshot(factory) as snapshot:
        plan_id = str(snapshot.connection.execute(
            "SELECT plan_revision_id FROM task_plan_current WHERE task_id=?",
            (result.task_id,),
        ).fetchone()[0])
        plan = tuple(snapshot.connection.execute(
            "SELECT start_utc,end_utc FROM task_plan_revisions WHERE plan_revision_id=?",
            (plan_id,),
        ).fetchone())
    return creation_command, result.task_id, plan_id, int(plan[0]), int(plan[1])


def _seed_objective(factory, *, task_id: str, plan_id: str, start_utc: int, end_utc: int, command_id: str):
    objective_id = new_uuid4()
    membership_event_id = new_uuid4()
    tracking_sequence = 98_700_000 + int(objective_id[-4:], 16) % 200_000
    tracking_id = f"MW-{tracking_sequence:08d}"
    with UnitOfWork(factory) as uow:
        uow.connection.execute(
            "INSERT INTO objectives(objective_id,tracking_sequence,tracking_id,creation_origin,"
            "superseded_by_objective_id,revision,created_at_utc,created_command_id) "
            "VALUES (?,?,?,'manual',NULL,1,1,?)",
            (objective_id, tracking_sequence, tracking_id, command_id),
        )
        uow.connection.execute(
            "INSERT INTO objective_membership_events(membership_event_id,task_id,event_kind,from_objective_id,"
            "to_objective_id,accepted_plan_revision_id,grouping_proposal_id,reason_code,recorded_at_utc,command_id) "
            "VALUES (?,?,'add',NULL,?,?,NULL,NULL,1,?)",
            (membership_event_id, task_id, objective_id, plan_id, command_id),
        )
        uow.connection.execute(
            "INSERT INTO objective_task_membership_current(task_id,objective_id,accepted_plan_revision_id,"
            "membership_revision,last_event_id,last_command_id) VALUES (?,?,?,1,?,?)",
            (task_id, objective_id, plan_id, membership_event_id, command_id),
        )
        uow.connection.execute(
            "INSERT INTO objective_envelope_projection(objective_id,start_utc,end_utc,member_count,"
            "membership_input_fingerprint,revision,last_command_id) VALUES (?,?,?,?,?,1,?)",
            (objective_id, start_utc, end_utc, 1, "a" * 64, command_id),
        )
        uow.connection.execute(
            "INSERT INTO objective_aggregate_projection(objective_id,execution_state,aggregate_outcome,"
            "actual_start_utc,actual_end_utc,attention_reason,included_task_count,excluded_task_count,"
            "aggregate_input_fingerprint,revision,last_command_id) "
            "VALUES (?,'planned',NULL,NULL,NULL,NULL,1,0,?,1,?)",
            (objective_id, "b" * 64, command_id),
        )
    return objective_id


def _counts(factory, command_id: str, task_id: str) -> tuple[int, int, int, int]:
    with ReadSnapshot(factory) as snapshot:
        return (
            int(snapshot.connection.execute(
                "SELECT count(*) FROM command_receipts WHERE command_id=?", (command_id,)
            ).fetchone()[0]),
            int(snapshot.connection.execute(
                "SELECT count(*) FROM command_receipt_results WHERE command_id=?", (command_id,)
            ).fetchone()[0]),
            int(snapshot.connection.execute(
                "SELECT count(*) FROM task_execution_events WHERE task_id=?", (task_id,)
            ).fetchone()[0]),
            int(snapshot.connection.execute(
                "SELECT count(*) FROM audit_events WHERE command_id=?", (command_id,)
            ).fetchone()[0]),
        )


def test_start_task_execution_from_exact_absence_is_atomic_and_replayable(initialized_database) -> None:
    factory = _factory(initialized_database)
    _, task_id, _, _, _ = _create_scheduled_task(factory, ordinal=1)
    service = TaskExecutionService(factory)
    command_id = new_uuid4()
    effective_start = 1_940_000_123

    applied = service.start_task_execution(
        command_id=command_id,
        task_id=task_id,
        task_revision=1,
        execution_revision=0,
        effective_start_utc=effective_start,
    )
    assert applied.outcome == "APPLIED"
    assert applied.task_id == task_id
    assert applied.revision == 2
    assert not applied.replayed
    assert len(applied.result_refs) == 1
    assert applied.result_refs[0].result_type == "task_execution_event"
    event_id = applied.result_refs[0].result_id

    with ReadSnapshot(factory) as snapshot:
        assert tuple(snapshot.connection.execute(
            "SELECT event_kind,effective_at_utc,target_event_id,correction_action,reason_code,command_id "
            "FROM task_execution_events WHERE execution_event_id=?",
            (event_id,),
        ).fetchone()) == ("start", effective_start, None, None, None, command_id)
        assert tuple(snapshot.connection.execute(
            "SELECT execution_state,actual_start_utc,actual_end_utc,effective_termination_utc,termination_reason,revision,last_event_id "
            "FROM task_execution_projection WHERE task_id=?",
            (task_id,),
        ).fetchone()) == ("in_progress", effective_start, None, None, None, 1, event_id)
        assert snapshot.connection.execute(
            "SELECT revision FROM tasks WHERE task_id=?", (task_id,)
        ).fetchone()[0] == 2
        audit = snapshot.connection.execute(
            "SELECT payload_json,audit_event_id FROM audit_events WHERE command_id=? AND action_type='task.execution_changed'",
            (command_id,),
        ).fetchone()
        assert audit is not None
        assert json.loads(str(audit[0])) == {
            "effective_at_utc": effective_start,
            "event_kind": "start",
            "execution_event_id": event_id,
            "reason_category": None,
            "resulting_execution_revision": 1,
            "resulting_task_revision": 2,
            "target_event_id": None,
            "task_id": task_id,
        }
        assert snapshot.connection.execute(
            "SELECT result_type,result_id FROM audit_event_results WHERE audit_event_id=?",
            (str(audit[1]),),
        ).fetchone() == ("task_execution_event", event_id)

    # Exact replay must not consult later Task state.
    with UnitOfWork(factory) as uow:
        uow.connection.execute("UPDATE tasks SET revision=revision+1 WHERE task_id=?", (task_id,))

    replayed = service.start_task_execution(
        command_id=command_id,
        task_id=task_id,
        task_revision=1,
        execution_revision=0,
        effective_start_utc=effective_start,
    )
    assert replayed.replayed
    assert replayed.outcome == applied.outcome
    assert replayed.task_id == applied.task_id
    assert replayed.revision == applied.revision
    assert replayed.result_refs == applied.result_refs
    assert _counts(factory, command_id, task_id) == (1, 1, 1, 1)


def test_start_task_execution_canonical_now_resolves_once_and_replay_never_reresolves(initialized_database) -> None:
    factory = _factory(initialized_database)
    _, task_id, _, _, _ = _create_scheduled_task(factory, ordinal=2)
    service = TaskExecutionService(factory)
    command_id = new_uuid4()

    applied = service.start_task_execution(
        command_id=command_id,
        task_id=task_id,
        task_revision=1,
        execution_revision=0,
        effective_start_utc="canonical-now",
    )
    event_id = applied.result_refs[0].result_id
    with ReadSnapshot(factory) as snapshot:
        first = tuple(snapshot.connection.execute(
            "SELECT effective_at_utc,recorded_at_utc FROM task_execution_events WHERE execution_event_id=?",
            (event_id,),
        ).fetchone())
        assert type(first[0]) is int and first[0] >= 0
        assert first[0] == first[1]

    replayed = service.start_task_execution(
        command_id=command_id,
        task_id=task_id,
        task_revision=1,
        execution_revision=0,
        effective_start_utc="canonical-now",
    )
    assert replayed.replayed
    assert replayed.result_refs == applied.result_refs
    with ReadSnapshot(factory) as snapshot:
        assert tuple(snapshot.connection.execute(
            "SELECT effective_at_utc,recorded_at_utc FROM task_execution_events WHERE execution_event_id=?",
            (event_id,),
        ).fetchone()) == first


def test_start_task_execution_rejects_stale_started_and_invalid_requests_before_receipt(initialized_database) -> None:
    factory = _factory(initialized_database)
    _, task_id, _, _, _ = _create_scheduled_task(factory, ordinal=3)
    service = TaskExecutionService(factory)

    for invalid in (-1, "now", True):
        with pytest.raises(ValidationError):
            service.start_task_execution(
                command_id=new_uuid4(),
                task_id=task_id,
                task_revision=1,
                execution_revision=0,
                effective_start_utc=invalid,
            )

    stale_task_command = new_uuid4()
    with pytest.raises(SomaError) as stale_task:
        service.start_task_execution(
            command_id=stale_task_command,
            task_id=task_id,
            task_revision=2,
            execution_revision=0,
            effective_start_utc=1_940_000_456,
        )
    assert stale_task.value.code == "TASK_STALE"

    service.start_task_execution(
        command_id=new_uuid4(),
        task_id=task_id,
        task_revision=1,
        execution_revision=0,
        effective_start_utc=1_940_000_456,
    )

    stale_execution_command = new_uuid4()
    with pytest.raises(SomaError) as stale_execution:
        service.start_task_execution(
            command_id=stale_execution_command,
            task_id=task_id,
            task_revision=2,
            execution_revision=0,
            effective_start_utc=1_940_000_500,
        )
    assert stale_execution.value.code == "TASK_STALE"

    already_started_command = new_uuid4()
    with pytest.raises(SomaError) as already_started:
        service.start_task_execution(
            command_id=already_started_command,
            task_id=task_id,
            task_revision=2,
            execution_revision=1,
            effective_start_utc=1_940_000_500,
        )
    assert already_started.value.code == "TASK_EXECUTION_ALREADY_STARTED"

    with ReadSnapshot(factory) as snapshot:
        for command_id in (stale_task_command, stale_execution_command, already_started_command):
            assert snapshot.connection.execute(
                "SELECT 1 FROM command_receipts WHERE command_id=?", (command_id,)
            ).fetchone() is None
        assert snapshot.connection.execute(
            "SELECT count(*) FROM task_execution_events WHERE task_id=?", (task_id,)
        ).fetchone()[0] == 1


def test_start_after_corrected_to_not_started_uses_positive_execution_revision(initialized_database) -> None:
    factory = _factory(initialized_database)
    creation_command, task_id, _, _, _ = _create_scheduled_task(factory, ordinal=4)
    original_start_id = new_uuid4()
    correction_id = new_uuid4()
    with UnitOfWork(factory) as uow:
        uow.connection.execute(
            "INSERT INTO task_execution_events(execution_event_id,task_id,event_kind,effective_at_utc,target_event_id,"
            "correction_action,reason_code,recorded_at_utc,command_id) VALUES (?,?,'start',?,NULL,NULL,NULL,1,?)",
            (original_start_id, task_id, 1_940_040_100, creation_command),
        )
        uow.connection.execute(
            "INSERT INTO task_execution_events(execution_event_id,task_id,event_kind,effective_at_utc,target_event_id,"
            "correction_action,reason_code,recorded_at_utc,command_id) VALUES (?,?,'correction',NULL,?,'withdraw','test',2,?)",
            (correction_id, task_id, original_start_id, creation_command),
        )
        uow.connection.execute(
            "INSERT INTO task_execution_projection(task_id,execution_state,actual_start_utc,actual_end_utc,"
            "effective_termination_utc,termination_reason,revision,last_event_id) "
            "VALUES (?,'not_started',NULL,NULL,NULL,NULL,2,?)",
            (task_id, correction_id),
        )
        uow.connection.execute("UPDATE tasks SET revision=2 WHERE task_id=?", (task_id,))

    result = TaskExecutionService(factory).start_task_execution(
        command_id=new_uuid4(),
        task_id=task_id,
        task_revision=2,
        execution_revision=2,
        effective_start_utc=1_940_040_200,
    )
    assert result.revision == 3
    with ReadSnapshot(factory) as snapshot:
        projection = snapshot.connection.execute(
            "SELECT execution_state,actual_start_utc,revision,last_event_id FROM task_execution_projection WHERE task_id=?",
            (task_id,),
        ).fetchone()
        assert tuple(projection[:3]) == ("in_progress", 1_940_040_200, 3)
        assert str(projection[3]) == result.result_refs[0].result_id
        assert snapshot.connection.execute(
            "SELECT count(*) FROM task_execution_events WHERE task_id=?", (task_id,)
        ).fetchone()[0] == 3
        assert snapshot.connection.execute(
            "SELECT revision FROM tasks WHERE task_id=?", (task_id,)
        ).fetchone()[0] == 3


def test_start_member_task_rebuilds_only_material_objective_aggregate(initialized_database) -> None:
    factory = _factory(initialized_database)
    creation_command, task_id, plan_id, start_utc, end_utc = _create_scheduled_task(factory, ordinal=5)
    objective_id = _seed_objective(
        factory,
        task_id=task_id,
        plan_id=plan_id,
        start_utc=start_utc,
        end_utc=end_utc,
        command_id=creation_command,
    )
    with ReadSnapshot(factory) as snapshot:
        before_membership = tuple(snapshot.connection.execute(
            "SELECT objective_id,accepted_plan_revision_id,membership_revision,last_event_id,last_command_id "
            "FROM objective_task_membership_current WHERE task_id=?", (task_id,)
        ).fetchone())
        before_envelope = tuple(snapshot.connection.execute(
            "SELECT start_utc,end_utc,member_count,membership_input_fingerprint,revision,last_command_id "
            "FROM objective_envelope_projection WHERE objective_id=?", (objective_id,)
        ).fetchone())
        before_objective = tuple(snapshot.connection.execute(
            "SELECT tracking_id,revision,superseded_by_objective_id FROM objectives WHERE objective_id=?",
            (objective_id,),
        ).fetchone())

    command_id = new_uuid4()
    effective_start = start_utc + 17
    result = TaskExecutionService(factory).start_task_execution(
        command_id=command_id,
        task_id=task_id,
        task_revision=1,
        execution_revision=0,
        effective_start_utc=effective_start,
    )
    assert result.revision == 2

    with ReadSnapshot(factory) as snapshot:
        assert tuple(snapshot.connection.execute(
            "SELECT objective_id,accepted_plan_revision_id,membership_revision,last_event_id,last_command_id "
            "FROM objective_task_membership_current WHERE task_id=?", (task_id,)
        ).fetchone()) == before_membership
        assert tuple(snapshot.connection.execute(
            "SELECT start_utc,end_utc,member_count,membership_input_fingerprint,revision,last_command_id "
            "FROM objective_envelope_projection WHERE objective_id=?", (objective_id,)
        ).fetchone()) == before_envelope
        assert tuple(snapshot.connection.execute(
            "SELECT tracking_id,revision,superseded_by_objective_id FROM objectives WHERE objective_id=?",
            (objective_id,),
        ).fetchone()) == before_objective
        aggregate = snapshot.connection.execute(
            "SELECT execution_state,aggregate_outcome,actual_start_utc,actual_end_utc,attention_reason,"
            "included_task_count,excluded_task_count,aggregate_input_fingerprint,revision,last_command_id "
            "FROM objective_aggregate_projection WHERE objective_id=?",
            (objective_id,),
        ).fetchone()
        assert tuple(aggregate[:7]) == ("in_progress", None, effective_start, None, None, 1, 0)
        assert len(str(aggregate[7])) == 64 and str(aggregate[7]) != "b" * 64
        assert tuple(aggregate[8:]) == (2, command_id)


def test_execution_audit_failure_rolls_back_task_execution_and_objective_rebuild(initialized_database, monkeypatch) -> None:
    factory = _factory(initialized_database)
    creation_command, task_id, plan_id, start_utc, end_utc = _create_scheduled_task(factory, ordinal=6)
    objective_id = _seed_objective(
        factory,
        task_id=task_id,
        plan_id=plan_id,
        start_utc=start_utc,
        end_utc=end_utc,
        command_id=creation_command,
    )
    service = TaskExecutionService(factory)
    command_id = new_uuid4()

    with ReadSnapshot(factory) as snapshot:
        before_aggregate = tuple(snapshot.connection.execute(
            "SELECT execution_state,aggregate_outcome,actual_start_utc,actual_end_utc,attention_reason,"
            "included_task_count,excluded_task_count,aggregate_input_fingerprint,revision,last_command_id "
            "FROM objective_aggregate_projection WHERE objective_id=?", (objective_id,)
        ).fetchone())

    def fail_audit(_uow, _event):
        raise IntegrityFailure("injected execution audit failure")

    monkeypatch.setattr(service._boundary._audit_writer, "write", fail_audit)
    with pytest.raises(IntegrityFailure):
        service.start_task_execution(
            command_id=command_id,
            task_id=task_id,
            task_revision=1,
            execution_revision=0,
            effective_start_utc=start_utc + 20,
        )

    with ReadSnapshot(factory) as snapshot:
        assert snapshot.connection.execute(
            "SELECT revision FROM tasks WHERE task_id=?", (task_id,)
        ).fetchone()[0] == 1
        assert snapshot.connection.execute(
            "SELECT 1 FROM task_execution_projection WHERE task_id=?", (task_id,)
        ).fetchone() is None
        assert snapshot.connection.execute(
            "SELECT count(*) FROM task_execution_events WHERE task_id=?", (task_id,)
        ).fetchone()[0] == 0
        assert tuple(snapshot.connection.execute(
            "SELECT execution_state,aggregate_outcome,actual_start_utc,actual_end_utc,attention_reason,"
            "included_task_count,excluded_task_count,aggregate_input_fingerprint,revision,last_command_id "
            "FROM objective_aggregate_projection WHERE objective_id=?", (objective_id,)
        ).fetchone()) == before_aggregate
        assert snapshot.connection.execute(
            "SELECT 1 FROM command_receipts WHERE command_id=?", (command_id,)
        ).fetchone() is None
        assert snapshot.connection.execute(
            "SELECT 1 FROM command_receipt_results WHERE command_id=?", (command_id,)
        ).fetchone() is None
        assert snapshot.connection.execute(
            "SELECT 1 FROM audit_events WHERE command_id=?", (command_id,)
        ).fetchone() is None
