from __future__ import annotations

import json

import pytest

from soma.foundation.errors import PersistenceFailure, SomaError, ValidationError
from soma.foundation.identifiers import new_uuid4
from soma.foundation.persistence.uow import ReadSnapshot, UnitOfWork
from soma.objectives_tasks import TaskPlanningService
from soma.objectives_tasks.services.task_explicit_lock import TaskExplicitLockService


def _factory(initialized_database):
    database_path, factory_for_path = initialized_database
    return factory_for_path(database_path)


def _create_local(factory):
    return TaskPlanningService(factory).create_local_task(
        command_id=new_uuid4(),
        local_task_name="Lock target",
    )


def _receipt_exists(factory, command_id: str) -> bool:
    with ReadSnapshot(factory) as snapshot:
        return snapshot.connection.execute(
            "SELECT 1 FROM command_receipts WHERE command_id=?", (command_id,)
        ).fetchone() is not None


def _created_command_id(factory, task_id: str) -> str:
    with ReadSnapshot(factory) as snapshot:
        row = snapshot.connection.execute(
            "SELECT created_command_id FROM tasks WHERE task_id=?", (task_id,)
        ).fetchone()
    assert row is not None
    return str(row[0])


def _lock_projection(factory, task_id: str):
    with ReadSnapshot(factory) as snapshot:
        return snapshot.connection.execute(
            "SELECT explicit_plan_lock,explicit_membership_lock,revision,last_event_id "
            "FROM task_lock_projection WHERE task_id=?",
            (task_id,),
        ).fetchone()


def _lock(factory, *, task_id: str, task_revision: int, lock_revision: int, kind: str, action: str):
    return TaskExplicitLockService(factory).set_explicit_task_lock(
        command_id=new_uuid4(),
        task_id=task_id,
        task_revision=task_revision,
        lock_projection_revision=lock_revision,
        lock_kind=kind,
        action=action,
        reason_category=f"operator_{action}_{kind}",
    )


def _seed_execution(factory, task_id: str) -> None:
    command_id = _created_command_id(factory, task_id)
    with UnitOfWork(factory) as uow:
        event_id = new_uuid4()
        uow.connection.execute(
            "INSERT INTO task_execution_events(execution_event_id,task_id,event_kind,effective_at_utc,target_event_id,"
            "correction_action,reason_code,recorded_at_utc,command_id) VALUES (?,?,'start',10,NULL,NULL,NULL,10,?)",
            (event_id, task_id, command_id),
        )
        uow.connection.execute(
            "INSERT INTO task_execution_projection(task_id,execution_state,actual_start_utc,actual_end_utc,"
            "effective_termination_utc,termination_reason,revision,last_event_id) VALUES (?,'in_progress',10,NULL,NULL,NULL,1,?)",
            (task_id, event_id),
        )


def test_first_plan_lock_creates_projection_event_and_exact_audit(initialized_database) -> None:
    factory = _factory(initialized_database)
    task = _create_local(factory)
    command_id = new_uuid4()
    result = TaskExplicitLockService(factory).set_explicit_task_lock(
        command_id=command_id,
        task_id=task.task_id,
        task_revision=1,
        lock_projection_revision=0,
        lock_kind="plan",
        action="lock",
        reason_category="operator_plan_lock",
    )

    assert result.outcome == "APPLIED"
    assert result.revision == 2
    assert len(result.result_refs) == 1
    event_id = result.result_refs[0].result_id
    assert result.result_refs[0].result_type == "task_lock_event"
    with ReadSnapshot(factory) as snapshot:
        assert snapshot.connection.execute(
            "SELECT revision FROM tasks WHERE task_id=?", (task.task_id,)
        ).fetchone() == (2,)
        assert snapshot.connection.execute(
            "SELECT explicit_plan_lock,explicit_membership_lock,revision,last_event_id "
            "FROM task_lock_projection WHERE task_id=?", (task.task_id,)
        ).fetchone() == (1, 0, 1, event_id)
        assert snapshot.connection.execute(
            "SELECT task_id,lock_kind,action,reason_code,command_id FROM task_lock_events WHERE lock_event_id=?",
            (event_id,),
        ).fetchone() == (task.task_id, "plan", "lock", "operator_plan_lock", command_id)
        audit = snapshot.connection.execute(
            "SELECT audit_event_id,action_type,payload_schema,payload_json FROM audit_events WHERE command_id=?",
            (command_id,),
        ).fetchone()
        assert audit is not None
        assert str(audit[1]) == "task.lock_changed"
        assert str(audit[2]) == "TaskLockAuditV1"
        assert json.loads(str(audit[3])) == {
            "action": "lock",
            "lock_event_id": event_id,
            "lock_kind": "plan",
            "reason_category": "operator_plan_lock",
            "resulting_lock_revision": 1,
            "resulting_task_revision": 2,
            "task_id": task.task_id,
        }
        assert snapshot.connection.execute(
            "SELECT result_type,result_id FROM audit_event_results WHERE audit_event_id=?",
            (str(audit[0]),),
        ).fetchone() == ("task_lock_event", event_id)


def test_material_changes_preserve_other_dimension_and_advance_both_revisions_once(initialized_database) -> None:
    factory = _factory(initialized_database)
    task = _create_local(factory)
    first = _lock(factory, task_id=task.task_id, task_revision=1, lock_revision=0, kind="plan", action="lock")
    second = _lock(factory, task_id=task.task_id, task_revision=2, lock_revision=1, kind="membership", action="lock")
    third = _lock(factory, task_id=task.task_id, task_revision=3, lock_revision=2, kind="plan", action="unlock")

    assert (first.revision, second.revision, third.revision) == (2, 3, 4)
    projection = _lock_projection(factory, task.task_id)
    assert projection is not None
    assert tuple(projection[:3]) == (0, 1, 3)
    with ReadSnapshot(factory) as snapshot:
        assert snapshot.connection.execute(
            "SELECT revision FROM tasks WHERE task_id=?", (task.task_id,)
        ).fetchone() == (4,)
        rows = snapshot.connection.execute(
            "SELECT lock_kind,action FROM task_lock_events WHERE task_id=?",
            (task.task_id,),
        ).fetchall()
        assert sorted((str(row[0]), str(row[1])) for row in rows) == [
            ("membership", "lock"),
            ("plan", "lock"),
            ("plan", "unlock"),
        ]


def test_same_explicit_state_is_no_change_after_exact_freshness(initialized_database) -> None:
    factory = _factory(initialized_database)
    task = _create_local(factory)
    _lock(factory, task_id=task.task_id, task_revision=1, lock_revision=0, kind="plan", action="lock")
    command_id = new_uuid4()
    result = TaskExplicitLockService(factory).set_explicit_task_lock(
        command_id=command_id,
        task_id=task.task_id,
        task_revision=2,
        lock_projection_revision=1,
        lock_kind="plan",
        action="lock",
        reason_category="same_state",
    )
    assert result.no_change
    assert result.revision == 2
    assert result.result_refs == ()
    with ReadSnapshot(factory) as snapshot:
        assert snapshot.connection.execute(
            "SELECT count(*) FROM task_lock_events WHERE task_id=?", (task.task_id,)
        ).fetchone()[0] == 1
        assert snapshot.connection.execute(
            "SELECT count(*) FROM audit_events WHERE command_id=?", (command_id,)
        ).fetchone()[0] == 0


def test_exact_replay_returns_original_result_without_duplicate_lock_history(initialized_database) -> None:
    factory = _factory(initialized_database)
    task = _create_local(factory)
    command_id = new_uuid4()
    kwargs = dict(
        command_id=command_id,
        task_id=task.task_id,
        task_revision=1,
        lock_projection_revision=0,
        lock_kind="membership",
        action="lock",
        reason_category="replay_lock",
    )
    service = TaskExplicitLockService(factory)
    first = service.set_explicit_task_lock(**kwargs)
    replay = service.set_explicit_task_lock(**kwargs)
    assert replay.replayed
    assert replay.outcome == first.outcome
    assert replay.revision == first.revision
    assert replay.result_refs == first.result_refs
    with ReadSnapshot(factory) as snapshot:
        assert snapshot.connection.execute(
            "SELECT count(*) FROM task_lock_events WHERE task_id=?", (task.task_id,)
        ).fetchone()[0] == 1


def test_stale_task_and_projection_presence_fail_before_receipt(initialized_database) -> None:
    factory = _factory(initialized_database)
    task = _create_local(factory)
    service = TaskExplicitLockService(factory)

    stale_task = new_uuid4()
    with pytest.raises(SomaError) as task_error:
        service.set_explicit_task_lock(
            command_id=stale_task,
            task_id=task.task_id,
            task_revision=2,
            lock_projection_revision=0,
            lock_kind="plan",
            action="lock",
            reason_category="stale_task",
        )
    assert task_error.value.code == "TASK_STALE"
    assert not _receipt_exists(factory, stale_task)

    absent_but_expected = new_uuid4()
    with pytest.raises(SomaError) as absent_error:
        service.set_explicit_task_lock(
            command_id=absent_but_expected,
            task_id=task.task_id,
            task_revision=1,
            lock_projection_revision=1,
            lock_kind="plan",
            action="lock",
            reason_category="stale_projection",
        )
    assert absent_error.value.code == "TASK_STALE"
    assert not _receipt_exists(factory, absent_but_expected)

    _lock(factory, task_id=task.task_id, task_revision=1, lock_revision=0, kind="plan", action="lock")
    present_but_expected_absent = new_uuid4()
    with pytest.raises(SomaError) as present_error:
        service.set_explicit_task_lock(
            command_id=present_but_expected_absent,
            task_id=task.task_id,
            task_revision=2,
            lock_projection_revision=0,
            lock_kind="membership",
            action="lock",
            reason_category="stale_absence",
        )
    assert present_error.value.code == "TASK_STALE"
    assert not _receipt_exists(factory, present_but_expected_absent)


def test_preflight_is_strict_and_writes_nothing(initialized_database) -> None:
    factory = _factory(initialized_database)
    task = _create_local(factory)
    service = TaskExplicitLockService(factory)
    cases = (
        dict(task_revision=True, lock_projection_revision=0, lock_kind="plan", action="lock", reason_category="x"),
        dict(task_revision=1, lock_projection_revision=True, lock_kind="plan", action="lock", reason_category="x"),
        dict(task_revision=1, lock_projection_revision=-1, lock_kind="plan", action="lock", reason_category="x"),
        dict(task_revision=1, lock_projection_revision=0, lock_kind="other", action="lock", reason_category="x"),
        dict(task_revision=1, lock_projection_revision=0, lock_kind="plan", action="toggle", reason_category="x"),
        dict(task_revision=1, lock_projection_revision=0, lock_kind="plan", action="lock", reason_category=""),
        dict(task_revision=1, lock_projection_revision=0, lock_kind="plan", action="lock", reason_category="bad\nreason"),
    )
    for case in cases:
        command_id = new_uuid4()
        with pytest.raises(ValidationError):
            service.set_explicit_task_lock(command_id=command_id, task_id=task.task_id, **case)
        assert not _receipt_exists(factory, command_id)


def test_material_unlock_is_blocked_by_accepted_execution_without_misleading_history(initialized_database) -> None:
    factory = _factory(initialized_database)
    task = _create_local(factory)
    _lock(factory, task_id=task.task_id, task_revision=1, lock_revision=0, kind="plan", action="lock")
    _seed_execution(factory, task.task_id)
    command_id = new_uuid4()
    with pytest.raises(SomaError) as blocked:
        TaskExplicitLockService(factory).set_explicit_task_lock(
            command_id=command_id,
            task_id=task.task_id,
            task_revision=2,
            lock_projection_revision=1,
            lock_kind="plan",
            action="unlock",
            reason_category="ineffective_unlock",
        )
    assert blocked.value.code == "TASK_PLAN_LOCKED"
    assert not _receipt_exists(factory, command_id)
    with ReadSnapshot(factory) as snapshot:
        assert snapshot.connection.execute(
            "SELECT explicit_plan_lock,revision FROM task_lock_projection WHERE task_id=?", (task.task_id,)
        ).fetchone() == (1, 1)
        assert snapshot.connection.execute(
            "SELECT count(*) FROM task_lock_events WHERE task_id=?", (task.task_id,)
        ).fetchone()[0] == 1


def test_explicitly_false_unlock_is_no_change_even_when_execution_derives_effective_lock(initialized_database) -> None:
    factory = _factory(initialized_database)
    task = _create_local(factory)
    _seed_execution(factory, task.task_id)
    command_id = new_uuid4()
    result = TaskExplicitLockService(factory).set_explicit_task_lock(
        command_id=command_id,
        task_id=task.task_id,
        task_revision=1,
        lock_projection_revision=0,
        lock_kind="plan",
        action="unlock",
        reason_category="already_explicitly_unlocked",
    )
    assert result.no_change
    assert _lock_projection(factory, task.task_id) is None


def test_audit_failure_rolls_back_event_projection_task_revision_and_receipt(initialized_database, monkeypatch) -> None:
    factory = _factory(initialized_database)
    task = _create_local(factory)
    service = TaskExplicitLockService(factory)
    command_id = new_uuid4()

    def fail_write(*_args, **_kwargs):
        raise PersistenceFailure("injected audit failure")

    monkeypatch.setattr(service._boundary._audit_writer, "write", fail_write)
    with pytest.raises(PersistenceFailure):
        service.set_explicit_task_lock(
            command_id=command_id,
            task_id=task.task_id,
            task_revision=1,
            lock_projection_revision=0,
            lock_kind="membership",
            action="lock",
            reason_category="rollback_test",
        )
    assert not _receipt_exists(factory, command_id)
    with ReadSnapshot(factory) as snapshot:
        assert snapshot.connection.execute(
            "SELECT revision FROM tasks WHERE task_id=?", (task.task_id,)
        ).fetchone() == (1,)
        assert snapshot.connection.execute(
            "SELECT count(*) FROM task_lock_events WHERE task_id=?", (task.task_id,)
        ).fetchone()[0] == 0
        assert snapshot.connection.execute(
            "SELECT count(*) FROM task_lock_projection WHERE task_id=?", (task.task_id,)
        ).fetchone()[0] == 0
