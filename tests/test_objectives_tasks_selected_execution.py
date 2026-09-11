from __future__ import annotations

import json

import pytest

from soma.foundation.errors import IntegrityFailure, SomaError, ValidationError
from soma.foundation.identifiers import new_uuid4
from soma.foundation.persistence.uow import ReadSnapshot, UnitOfWork
from soma.objectives_tasks import AcceptedTaskSchedule, TaskPlanningService
from soma.objectives_tasks.services.task_execution import SelectedTaskExecutionStart, TaskExecutionService


TZ = "America/Guayaquil"


def _factory(initialized_database):
    database_path, factory_for_path = initialized_database
    return factory_for_path(database_path)


def _create_task(factory, *, ordinal: int):
    command_id = new_uuid4()
    result = TaskPlanningService(factory).create_local_task(
        command_id=command_id,
        local_task_name=f"Selected execution {ordinal}",
        schedule=AcceptedTaskSchedule(
            start_utc=1_960_000_000 + ordinal * 100,
            end_utc=1_960_003_600 + ordinal * 100,
            scheduling_timezone_iana=TZ,
        ),
    )
    with ReadSnapshot(factory) as snapshot:
        plan = snapshot.connection.execute(
            "SELECT pc.plan_revision_id,p.start_utc,p.end_utc "
            "FROM task_plan_current pc JOIN task_plan_revisions p ON p.plan_revision_id=pc.plan_revision_id "
            "WHERE pc.task_id=?",
            (result.task_id,),
        ).fetchone()
        assert plan is not None
        return command_id, result.task_id, str(plan[0]), int(plan[1]), int(plan[2])


def _seed_objective(factory, *, task_rows):
    objective_id = new_uuid4()
    first_command = task_rows[0][0]
    tracking_sequence = 97_500_000 + int(objective_id[-4:], 16) % 400_000
    start_utc = min(row[3] for row in task_rows)
    end_utc = max(row[4] for row in task_rows)
    with UnitOfWork(factory) as uow:
        uow.connection.execute(
            "INSERT INTO objectives(objective_id,tracking_sequence,tracking_id,creation_origin,"
            "superseded_by_objective_id,revision,created_at_utc,created_command_id) "
            "VALUES (?,?,?,'manual',NULL,1,1,?)",
            (objective_id, tracking_sequence, f"MW-{tracking_sequence:08d}", first_command),
        )
        for command_id, task_id, plan_id, _start, _end in task_rows:
            event_id = new_uuid4()
            uow.connection.execute(
                "INSERT INTO objective_membership_events(membership_event_id,task_id,event_kind,from_objective_id,"
                "to_objective_id,accepted_plan_revision_id,grouping_proposal_id,reason_code,recorded_at_utc,command_id) "
                "VALUES (?,?,'add',NULL,?,?,NULL,NULL,1,?)",
                (event_id, task_id, objective_id, plan_id, command_id),
            )
            uow.connection.execute(
                "INSERT INTO objective_task_membership_current(task_id,objective_id,accepted_plan_revision_id,"
                "membership_revision,last_event_id,last_command_id) VALUES (?,?,?,1,?,?)",
                (task_id, objective_id, plan_id, event_id, command_id),
            )
        uow.connection.execute(
            "INSERT INTO objective_envelope_projection(objective_id,start_utc,end_utc,member_count,"
            "membership_input_fingerprint,revision,last_command_id) VALUES (?,?,?,?,?,1,?)",
            (objective_id, start_utc, end_utc, len(task_rows), "a" * 64, first_command),
        )
        uow.connection.execute(
            "INSERT INTO objective_aggregate_projection(objective_id,execution_state,aggregate_outcome,"
            "actual_start_utc,actual_end_utc,attention_reason,included_task_count,excluded_task_count,"
            "aggregate_input_fingerprint,revision,last_command_id) "
            "VALUES (?,'planned',NULL,NULL,NULL,NULL,?,0,?,1,?)",
            (objective_id, len(task_rows), "b" * 64, first_command),
        )
    return objective_id


def _selection(*task_rows):
    return [SelectedTaskExecutionStart(row[1], 1, 0) for row in task_rows]


def test_selected_start_is_one_atomic_batch_and_leaves_unselected_task_unchanged(initialized_database) -> None:
    factory = _factory(initialized_database)
    rows = [_create_task(factory, ordinal=index) for index in (1, 2, 3)]
    objective_id = _seed_objective(factory, task_rows=rows)
    selected = _selection(rows[1], rows[0])
    command_id = new_uuid4()
    accepted_start = 1_960_000_777

    result = TaskExecutionService(factory).start_selected_objective_tasks(
        command_id=command_id,
        objective_id=objective_id,
        objective_revision=1,
        objective_envelope_revision=1,
        selected_tasks=selected,
        effective_start_utc=accepted_start,
    )
    assert result.outcome == "APPLIED"
    assert result.objective_id == objective_id
    assert result.revision == 1
    assert not result.replayed
    assert len(result.result_refs) == 2

    canonical_selected = sorted((rows[0][1], rows[1][1]))
    with ReadSnapshot(factory) as snapshot:
        assert snapshot.connection.execute(
            "SELECT count(*) FROM command_receipts WHERE command_id=?", (command_id,)
        ).fetchone()[0] == 1
        assert snapshot.connection.execute(
            "SELECT count(*) FROM command_receipt_results WHERE command_id=?", (command_id,)
        ).fetchone()[0] == 1
        assert snapshot.connection.execute(
            "SELECT revision FROM objectives WHERE objective_id=?", (objective_id,)
        ).fetchone()[0] == 1
        assert snapshot.connection.execute(
            "SELECT revision FROM objective_envelope_projection WHERE objective_id=?", (objective_id,)
        ).fetchone()[0] == 1
        for task_id in canonical_selected:
            assert snapshot.connection.execute(
                "SELECT revision FROM tasks WHERE task_id=?", (task_id,)
            ).fetchone()[0] == 2
            projection = snapshot.connection.execute(
                "SELECT execution_state,actual_start_utc,revision FROM task_execution_projection WHERE task_id=?",
                (task_id,),
            ).fetchone()
            assert tuple(projection) == ("in_progress", accepted_start, 1)
        unselected_id = rows[2][1]
        assert snapshot.connection.execute(
            "SELECT revision FROM tasks WHERE task_id=?", (unselected_id,)
        ).fetchone()[0] == 1
        assert snapshot.connection.execute(
            "SELECT 1 FROM task_execution_projection WHERE task_id=?", (unselected_id,)
        ).fetchone() is None
        aggregate = snapshot.connection.execute(
            "SELECT execution_state,actual_start_utc,revision,aggregate_input_fingerprint,last_command_id "
            "FROM objective_aggregate_projection WHERE objective_id=?", (objective_id,)
        ).fetchone()
        assert aggregate[0] == "in_progress"
        assert aggregate[1] == accepted_start
        assert aggregate[2] == 2
        assert len(str(aggregate[3])) == 64 and str(aggregate[3]) != "b" * 64
        assert aggregate[4] == command_id

        audit = snapshot.connection.execute(
            "SELECT audit_event_id,payload_json FROM audit_events "
            "WHERE command_id=? AND action_type='task.execution_batch_started'",
            (command_id,),
        ).fetchone()
        assert audit is not None
        payload = json.loads(str(audit[1]))
        assert payload["objective_scope_id"] == objective_id
        assert payload["selected_task_ids"] == canonical_selected
        assert payload["task_execution_event_ids"] == [ref.result_id for ref in result.result_refs]
        assert list(payload["resulting_task_revisions"]) == canonical_selected
        assert payload["resulting_task_revisions"] == {
            task_id: {"execution_revision": 1, "task_revision": 2} for task_id in canonical_selected
        }
        assert payload["aggregate_input_fingerprint"] == aggregate[3]
        assert payload["resulting_objective_projection_revision"] == 2
        refs = snapshot.connection.execute(
            "SELECT result_type,result_id FROM audit_event_results WHERE audit_event_id=? ORDER BY ordinal",
            (str(audit[0]),),
        ).fetchall()
        assert {tuple(row) for row in refs} == {
            ("task_execution_event", ref.result_id) for ref in result.result_refs
        }


def test_selected_start_request_order_is_nonsemantic_and_exact_replay_ignores_later_state(initialized_database) -> None:
    factory = _factory(initialized_database)
    rows = [_create_task(factory, ordinal=index) for index in (4, 5)]
    objective_id = _seed_objective(factory, task_rows=rows)
    service = TaskExecutionService(factory)
    command_id = new_uuid4()

    first = service.start_selected_objective_tasks(
        command_id=command_id,
        objective_id=objective_id,
        objective_revision=1,
        objective_envelope_revision=1,
        selected_tasks=_selection(rows[1], rows[0]),
        effective_start_utc=1_960_001_111,
    )
    with UnitOfWork(factory) as uow:
        uow.connection.execute("UPDATE tasks SET revision=revision+1 WHERE task_id=?", (rows[0][1],))

    replay = service.start_selected_objective_tasks(
        command_id=command_id,
        objective_id=objective_id,
        objective_revision=1,
        objective_envelope_revision=1,
        selected_tasks=_selection(rows[0], rows[1]),
        effective_start_utc=1_960_001_111,
    )
    assert replay.replayed
    assert replay.objective_id == first.objective_id
    assert replay.revision == first.revision
    assert replay.result_refs == first.result_refs


def test_selected_start_canonical_now_is_one_shared_instant_and_replay_stable(initialized_database) -> None:
    factory = _factory(initialized_database)
    rows = [_create_task(factory, ordinal=index) for index in (6, 7, 8)]
    objective_id = _seed_objective(factory, task_rows=rows)
    service = TaskExecutionService(factory)
    command_id = new_uuid4()

    first = service.start_selected_objective_tasks(
        command_id=command_id,
        objective_id=objective_id,
        objective_revision=1,
        objective_envelope_revision=1,
        selected_tasks=_selection(*rows),
        effective_start_utc="canonical-now",
    )
    with ReadSnapshot(factory) as snapshot:
        evidence = snapshot.connection.execute(
            "SELECT effective_at_utc,recorded_at_utc FROM task_execution_events WHERE command_id=?",
            (command_id,),
        ).fetchall()
        assert len(evidence) == 3
        assert len({tuple(row) for row in evidence}) == 1
        accepted_start, recorded_at = tuple(evidence[0])
        assert type(accepted_start) is int and accepted_start >= 0
        assert accepted_start == recorded_at

    replay = service.start_selected_objective_tasks(
        command_id=command_id,
        objective_id=objective_id,
        objective_revision=1,
        objective_envelope_revision=1,
        selected_tasks=_selection(*reversed(rows)),
        effective_start_utc="canonical-now",
    )
    assert replay.replayed
    assert replay.result_refs == first.result_refs
    with ReadSnapshot(factory) as snapshot:
        assert {tuple(row) for row in snapshot.connection.execute(
            "SELECT effective_at_utc,recorded_at_utc FROM task_execution_events WHERE command_id=?",
            (command_id,),
        ).fetchall()} == {(accepted_start, recorded_at)}


def test_selected_start_rejects_invalid_bounds_and_duplicates_before_receipt(initialized_database) -> None:
    factory = _factory(initialized_database)
    row = _create_task(factory, ordinal=9)
    objective_id = _seed_objective(factory, task_rows=[row])
    service = TaskExecutionService(factory)

    with pytest.raises(ValidationError):
        service.start_selected_objective_tasks(
            command_id=new_uuid4(), objective_id=objective_id, objective_revision=1,
            objective_envelope_revision=1, selected_tasks=[], effective_start_utc=1_960_002_000,
        )
    with pytest.raises(ValidationError):
        service.start_selected_objective_tasks(
            command_id=new_uuid4(), objective_id=objective_id, objective_revision=1,
            objective_envelope_revision=1,
            selected_tasks=[SelectedTaskExecutionStart(row[1], 1, 0)] * 2,
            effective_start_utc=1_960_002_000,
        )
    with pytest.raises(ValidationError):
        service.start_selected_objective_tasks(
            command_id=new_uuid4(), objective_id=objective_id, objective_revision=1,
            objective_envelope_revision=1,
            selected_tasks=[SelectedTaskExecutionStart(new_uuid4(), 1, 0) for _ in range(101)],
            effective_start_utc=1_960_002_000,
        )


def test_one_stale_or_nonmember_selected_task_rolls_back_entire_preflight(initialized_database) -> None:
    factory = _factory(initialized_database)
    rows = [_create_task(factory, ordinal=index) for index in (10, 11)]
    outsider = _create_task(factory, ordinal=12)
    objective_id = _seed_objective(factory, task_rows=rows)
    service = TaskExecutionService(factory)

    stale_command = new_uuid4()
    with pytest.raises(SomaError) as stale:
        service.start_selected_objective_tasks(
            command_id=stale_command,
            objective_id=objective_id,
            objective_revision=1,
            objective_envelope_revision=1,
            selected_tasks=[
                SelectedTaskExecutionStart(rows[0][1], 1, 0),
                SelectedTaskExecutionStart(rows[1][1], 2, 0),
            ],
            effective_start_utc=1_960_003_000,
        )
    assert stale.value.code == "TASK_STALE"

    nonmember_command = new_uuid4()
    with pytest.raises(SomaError) as nonmember:
        service.start_selected_objective_tasks(
            command_id=nonmember_command,
            objective_id=objective_id,
            objective_revision=1,
            objective_envelope_revision=1,
            selected_tasks=[
                SelectedTaskExecutionStart(rows[0][1], 1, 0),
                SelectedTaskExecutionStart(outsider[1], 1, 0),
            ],
            effective_start_utc=1_960_003_000,
        )
    assert nonmember.value.code == "TASK_STALE"

    with ReadSnapshot(factory) as snapshot:
        for command_id in (stale_command, nonmember_command):
            assert snapshot.connection.execute(
                "SELECT 1 FROM command_receipts WHERE command_id=?", (command_id,)
            ).fetchone() is None
        for row in rows:
            assert snapshot.connection.execute(
                "SELECT revision FROM tasks WHERE task_id=?", (row[1],)
            ).fetchone()[0] == 1
            assert snapshot.connection.execute(
                "SELECT 1 FROM task_execution_projection WHERE task_id=?", (row[1],)
            ).fetchone() is None


def test_already_started_selected_member_prevents_other_selected_mutation(initialized_database) -> None:
    factory = _factory(initialized_database)
    rows = [_create_task(factory, ordinal=index) for index in (13, 14)]
    objective_id = _seed_objective(factory, task_rows=rows)
    service = TaskExecutionService(factory)
    service.start_task_execution(
        command_id=new_uuid4(), task_id=rows[1][1], task_revision=1,
        execution_revision=0, effective_start_utc=1_960_004_000,
    )
    command_id = new_uuid4()
    with pytest.raises(SomaError) as started:
        service.start_selected_objective_tasks(
            command_id=command_id,
            objective_id=objective_id,
            objective_revision=1,
            objective_envelope_revision=1,
            selected_tasks=[
                SelectedTaskExecutionStart(rows[0][1], 1, 0),
                SelectedTaskExecutionStart(rows[1][1], 2, 1),
            ],
            effective_start_utc=1_960_004_100,
        )
    assert started.value.code == "TASK_EXECUTION_ALREADY_STARTED"
    with ReadSnapshot(factory) as snapshot:
        assert snapshot.connection.execute(
            "SELECT revision FROM tasks WHERE task_id=?", (rows[0][1],)
        ).fetchone()[0] == 1
        assert snapshot.connection.execute(
            "SELECT 1 FROM task_execution_projection WHERE task_id=?", (rows[0][1],)
        ).fetchone() is None
        assert snapshot.connection.execute(
            "SELECT 1 FROM command_receipts WHERE command_id=?", (command_id,)
        ).fetchone() is None


def test_batch_accepts_positive_corrected_to_not_started_execution_revision(initialized_database) -> None:
    factory = _factory(initialized_database)
    row = _create_task(factory, ordinal=15)
    objective_id = _seed_objective(factory, task_rows=[row])
    original_start_id = new_uuid4()
    correction_id = new_uuid4()
    with UnitOfWork(factory) as uow:
        uow.connection.execute(
            "INSERT INTO task_execution_events(execution_event_id,task_id,event_kind,effective_at_utc,target_event_id,"
            "correction_action,reason_code,recorded_at_utc,command_id) VALUES (?,?,'start',?,NULL,NULL,NULL,1,?)",
            (original_start_id, row[1], 1_960_005_000, row[0]),
        )
        uow.connection.execute(
            "INSERT INTO task_execution_events(execution_event_id,task_id,event_kind,effective_at_utc,target_event_id,"
            "correction_action,reason_code,recorded_at_utc,command_id) VALUES (?,?,'correction',NULL,?,'withdraw','test',2,?)",
            (correction_id, row[1], original_start_id, row[0]),
        )
        uow.connection.execute(
            "INSERT INTO task_execution_projection(task_id,execution_state,actual_start_utc,actual_end_utc,"
            "effective_termination_utc,termination_reason,revision,last_event_id) "
            "VALUES (?,'not_started',NULL,NULL,NULL,NULL,2,?)",
            (row[1], correction_id),
        )
        uow.connection.execute("UPDATE tasks SET revision=2 WHERE task_id=?", (row[1],))

    result = TaskExecutionService(factory).start_selected_objective_tasks(
        command_id=new_uuid4(), objective_id=objective_id, objective_revision=1,
        objective_envelope_revision=1,
        selected_tasks=[SelectedTaskExecutionStart(row[1], 2, 2)],
        effective_start_utc=1_960_005_100,
    )
    assert result.outcome == "APPLIED"
    with ReadSnapshot(factory) as snapshot:
        assert tuple(snapshot.connection.execute(
            "SELECT execution_state,actual_start_utc,revision FROM task_execution_projection WHERE task_id=?",
            (row[1],),
        ).fetchone()) == ("in_progress", 1_960_005_100, 3)
        assert snapshot.connection.execute(
            "SELECT revision FROM tasks WHERE task_id=?", (row[1],)
        ).fetchone()[0] == 3


def test_batch_audit_failure_rolls_back_all_selected_writes_and_aggregate(initialized_database, monkeypatch) -> None:
    factory = _factory(initialized_database)
    rows = [_create_task(factory, ordinal=index) for index in (16, 17, 18)]
    objective_id = _seed_objective(factory, task_rows=rows)
    service = TaskExecutionService(factory)
    command_id = new_uuid4()
    with ReadSnapshot(factory) as snapshot:
        before_aggregate = tuple(snapshot.connection.execute(
            "SELECT execution_state,aggregate_input_fingerprint,revision,last_command_id "
            "FROM objective_aggregate_projection WHERE objective_id=?", (objective_id,)
        ).fetchone())

    def fail_audit(_uow, _event):
        raise IntegrityFailure("injected selected-start audit failure")

    monkeypatch.setattr(service._boundary._audit_writer, "write", fail_audit)
    with pytest.raises(IntegrityFailure):
        service.start_selected_objective_tasks(
            command_id=command_id,
            objective_id=objective_id,
            objective_revision=1,
            objective_envelope_revision=1,
            selected_tasks=_selection(*rows),
            effective_start_utc=1_960_006_000,
        )

    with ReadSnapshot(factory) as snapshot:
        assert snapshot.connection.execute(
            "SELECT 1 FROM command_receipts WHERE command_id=?", (command_id,)
        ).fetchone() is None
        assert snapshot.connection.execute(
            "SELECT 1 FROM command_receipt_results WHERE command_id=?", (command_id,)
        ).fetchone() is None
        assert snapshot.connection.execute(
            "SELECT 1 FROM audit_events WHERE command_id=?", (command_id,)
        ).fetchone() is None
        for row in rows:
            assert snapshot.connection.execute(
                "SELECT revision FROM tasks WHERE task_id=?", (row[1],)
            ).fetchone()[0] == 1
            assert snapshot.connection.execute(
                "SELECT count(*) FROM task_execution_events WHERE task_id=?", (row[1],)
            ).fetchone()[0] == 0
            assert snapshot.connection.execute(
                "SELECT 1 FROM task_execution_projection WHERE task_id=?", (row[1],)
            ).fetchone() is None
        assert tuple(snapshot.connection.execute(
            "SELECT execution_state,aggregate_input_fingerprint,revision,last_command_id "
            "FROM objective_aggregate_projection WHERE objective_id=?", (objective_id,)
        ).fetchone()) == before_aggregate
