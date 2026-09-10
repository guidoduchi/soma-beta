from __future__ import annotations

import json

import pytest

from soma.foundation.errors import IdempotencyConflict, SomaError
from soma.foundation.identifiers import new_uuid4
from soma.foundation.persistence.uow import ReadSnapshot
from soma.objectives_tasks import AcceptedTaskSchedule, TaskPlanningService
from soma.objectives_tasks.repositories.tasks import TaskPlanRepository


def _factory(initialized_database):
    database_path, factory_for_path = initialized_database
    return factory_for_path(database_path)


def _result_refs(result) -> set[tuple[str, str]]:
    return {(ref.result_type, ref.result_id) for ref in result.result_refs}


def test_create_local_task_minimum_is_unscheduled_and_exactly_replayable(initialized_database) -> None:
    factory = _factory(initialized_database)
    service = TaskPlanningService(factory)
    command_id = new_uuid4()
    name = "  Replace aggregation switch optics  "

    applied = service.create_local_task(
        command_id=command_id,
        local_task_name=name,
    )

    assert applied.outcome == "APPLIED"
    assert applied.revision == 1
    assert not applied.replayed
    assert not applied.no_change
    assert _result_refs(applied) == {("task", applied.task_id)}

    with ReadSnapshot(factory) as snapshot:
        task = snapshot.connection.execute(
            "SELECT task_kind,local_task_name,creation_origin,revision,created_command_id "
            "FROM tasks WHERE task_id=?",
            (applied.task_id,),
        ).fetchone()
        assert tuple(task) == ("local", name, "manual", 1, command_id)
        assert snapshot.connection.execute(
            "SELECT 1 FROM wfm_task_identities WHERE task_id=?", (applied.task_id,)
        ).fetchone() is None
        assert snapshot.connection.execute(
            "SELECT 1 FROM task_plan_revisions WHERE task_id=?", (applied.task_id,)
        ).fetchone() is None
        assert snapshot.connection.execute(
            "SELECT 1 FROM task_plan_current WHERE task_id=?", (applied.task_id,)
        ).fetchone() is None
        assert snapshot.connection.execute(
            "SELECT 1 FROM objective_task_membership_current WHERE task_id=?", (applied.task_id,)
        ).fetchone() is None
        for table in ("task_sr_links", "task_rfc_links", "task_device_links"):
            assert snapshot.connection.execute(
                f"SELECT 1 FROM {table} WHERE task_id=?", (applied.task_id,)
            ).fetchone() is None

        audit = snapshot.connection.execute(
            "SELECT action_type,payload_schema,payload_version,payload_json FROM audit_events WHERE command_id=?",
            (command_id,),
        ).fetchone()
        assert tuple(audit[:3]) == ("task.created", "TaskAuditV1", 1)
        assert json.loads(str(audit[3])) == {
            "creation_origin": "manual",
            "reason_category": None,
            "resulting_revision": 1,
            "task_id": applied.task_id,
            "task_kind": "local",
            "task_plan_revision_id": None,
        }
        receipt = snapshot.connection.execute(
            "SELECT command_type,target_type,target_id,result_type,result_id FROM command_receipts WHERE command_id=?",
            (command_id,),
        ).fetchone()
        assert tuple(receipt) == ("CreateLocalTask", "task", None, "task", applied.task_id)

    replayed = service.create_local_task(
        command_id=command_id,
        local_task_name=name,
    )
    assert replayed.replayed
    assert replayed.outcome == applied.outcome
    assert replayed.task_id == applied.task_id
    assert replayed.revision == applied.revision
    assert replayed.result_refs == applied.result_refs

    with pytest.raises(IdempotencyConflict):
        service.create_local_task(
            command_id=command_id,
            local_task_name="Different semantic request",
        )


def test_create_local_task_schedule_preserves_exact_operational_interval_without_objective(initialized_database) -> None:
    factory = _factory(initialized_database)
    service = TaskPlanningService(factory)
    command_id = new_uuid4()
    schedule = AcceptedTaskSchedule(
        start_utc=1_800_000_017,
        end_utc=1_800_003_599,
        scheduling_timezone_iana="America/Guayaquil",
    )

    result = service.create_local_task(
        command_id=command_id,
        local_task_name="Patch host firmware",
        schedule=schedule,
    )
    plan_refs = [ref.result_id for ref in result.result_refs if ref.result_type == "task_plan"]
    assert len(plan_refs) == 1
    plan_revision_id = plan_refs[0]

    with ReadSnapshot(factory) as snapshot:
        plan = snapshot.connection.execute(
            "SELECT p.start_utc,p.end_utc,p.origin,p.scheduling_timezone_iana,p.source_observation_id,"
            "p.predecessor_plan_revision_id,p.reason_code,p.command_id,c.revision,c.last_command_id "
            "FROM task_plan_revisions p JOIN task_plan_current c ON c.plan_revision_id=p.plan_revision_id "
            "WHERE p.plan_revision_id=? AND p.task_id=?",
            (plan_revision_id, result.task_id),
        ).fetchone()
        assert tuple(plan) == (
            1_800_000_017,
            1_800_003_599,
            "manual",
            "America/Guayaquil",
            None,
            None,
            None,
            command_id,
            1,
            command_id,
        )
        assert snapshot.connection.execute(
            "SELECT 1 FROM objective_task_membership_current WHERE task_id=?", (result.task_id,)
        ).fetchone() is None
        audit_payload = snapshot.connection.execute(
            "SELECT payload_json FROM audit_events WHERE command_id=? AND action_type='task.created'",
            (command_id,),
        ).fetchone()
        assert audit_payload is not None
        assert json.loads(str(audit_payload[0]))["task_plan_revision_id"] == plan_revision_id


def test_local_task_name_uses_unicode17_grapheme_and_utf8_bounds(initialized_database) -> None:
    factory = _factory(initialized_database)
    service = TaskPlanningService(factory)

    accepted_name = "e\u0301" * 240
    accepted = service.create_local_task(
        command_id=new_uuid4(),
        local_task_name=accepted_name,
    )
    with ReadSnapshot(factory) as snapshot:
        assert snapshot.connection.execute(
            "SELECT local_task_name FROM tasks WHERE task_id=?", (accepted.task_id,)
        ).fetchone()[0] == accepted_name

    rejected_commands: list[str] = []
    for name in (
        "\u2003\t  ",
        "e\u0301" * 241,
        ("e" + "\u0301" * 3) * 150,
    ):
        command_id = new_uuid4()
        rejected_commands.append(command_id)
        with pytest.raises(SomaError) as exc_info:
            service.create_local_task(command_id=command_id, local_task_name=name)
        assert exc_info.value.code == "TASK_NAME_REQUIRED"

    with ReadSnapshot(factory) as snapshot:
        for command_id in rejected_commands:
            assert snapshot.connection.execute(
                "SELECT 1 FROM command_receipts WHERE command_id=?", (command_id,)
            ).fetchone() is None


def test_create_local_task_rolls_back_receipt_task_and_plan_then_same_command_retries(
    initialized_database,
    monkeypatch,
) -> None:
    factory = _factory(initialized_database)
    service = TaskPlanningService(factory)
    command_id = new_uuid4()
    schedule = AcceptedTaskSchedule(
        start_utc=1_900_000_000,
        end_utc=1_900_003_600,
        scheduling_timezone_iana="America/Guayaquil",
    )
    original_insert = TaskPlanRepository.insert_initial

    def fail_after_task_insert(*_args, **_kwargs) -> None:
        raise RuntimeError("injected F001 plan failure")

    monkeypatch.setattr(TaskPlanRepository, "insert_initial", staticmethod(fail_after_task_insert))
    with pytest.raises(RuntimeError, match="injected F001 plan failure"):
        service.create_local_task(
            command_id=command_id,
            local_task_name="Rollback probe",
            schedule=schedule,
        )

    with ReadSnapshot(factory) as snapshot:
        assert snapshot.connection.execute(
            "SELECT 1 FROM command_receipts WHERE command_id=?", (command_id,)
        ).fetchone() is None
        assert snapshot.connection.execute(
            "SELECT 1 FROM tasks WHERE created_command_id=?", (command_id,)
        ).fetchone() is None
        assert snapshot.connection.execute(
            "SELECT 1 FROM task_plan_revisions WHERE command_id=?", (command_id,)
        ).fetchone() is None
        assert snapshot.connection.execute(
            "SELECT 1 FROM audit_events WHERE command_id=?", (command_id,)
        ).fetchone() is None

    monkeypatch.setattr(TaskPlanRepository, "insert_initial", staticmethod(original_insert))
    retried = service.create_local_task(
        command_id=command_id,
        local_task_name="Rollback probe",
        schedule=schedule,
    )
    assert retried.outcome == "APPLIED"
    assert not retried.replayed
