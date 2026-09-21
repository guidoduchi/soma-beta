from __future__ import annotations

import json

import pytest

from soma.foundation.errors import IdempotencyConflict, SomaError, ValidationError
from soma.foundation.identifiers import new_uuid4
from soma.foundation.persistence.uow import ReadSnapshot
from soma.objectives_tasks import AcceptedTaskSchedule, TaskPlanningService
from soma.objectives_tasks.repositories.tasks import TaskPlanRepository, TaskRelationshipRepository
from soma.tickets.device_references import DeviceReferenceService
from soma.tickets.rfcs import RfcService
from soma.tickets.service_requests import ServiceRequestService


def _factory(initialized_database):
    database_path, factory_for_path = initialized_database
    return factory_for_path(database_path)


def _result_refs(result) -> set[tuple[str, str]]:
    return {(ref.result_type, ref.result_id) for ref in result.result_refs}


def _create_sr(factory) -> str:
    return ServiceRequestService(factory).create_manual_service_request(command_id=new_uuid4()).service_request_id


def _create_rfc(factory, suffix: int = 1) -> str:
    return RfcService(factory).create_or_adopt_identity(
        command_id=new_uuid4(),
        rfc_no=f"NC{suffix:014d}",
        creation_context="manual",
    ).rfc_id


def _create_device(factory, suffix: int = 1) -> str:
    return DeviceReferenceService(factory).create(
        command_id=new_uuid4(),
        operational_name=f"NE-LAB-{suffix}",
    ).device_reference_id


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
            "SELECT payload_json,audit_event_id FROM audit_events WHERE command_id=? AND action_type='task.created'",
            (command_id,),
        ).fetchone()
        assert audit_payload is not None
        assert json.loads(str(audit_payload[0]))["task_plan_revision_id"] == plan_revision_id
        audit_refs = snapshot.connection.execute(
            "SELECT result_type,result_id FROM audit_event_results WHERE audit_event_id=?",
            (str(audit_payload[1]),),
        ).fetchall()
        assert {(str(row[0]), str(row[1])) for row in audit_refs} == {
            ("task", result.task_id),
            ("task_plan", plan_revision_id),
        }


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
        "\u0085\u2003\t  ",
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


def test_create_local_task_initial_relationships_are_task_owned_and_audit_retained(initialized_database) -> None:
    factory = _factory(initialized_database)
    service = TaskPlanningService(factory)
    sr_id = _create_sr(factory)
    rfc_id = _create_rfc(factory, 101)
    device_id = _create_device(factory, 101)
    command_id = new_uuid4()

    result = service.create_local_task(
        command_id=command_id,
        local_task_name="Replace controller",
        service_request_ids=[sr_id],
        rfc_ids=[rfc_id],
        device_reference_ids=[device_id],
    )

    with ReadSnapshot(factory) as snapshot:
        sr_link = snapshot.connection.execute(
            "SELECT link_id,service_request_id,active,opened_command_id,closed_command_id "
            "FROM task_sr_links WHERE task_id=?",
            (result.task_id,),
        ).fetchone()
        rfc_link = snapshot.connection.execute(
            "SELECT link_id,rfc_id,active,opened_command_id,closed_command_id "
            "FROM task_rfc_links WHERE task_id=?",
            (result.task_id,),
        ).fetchone()
        device_link = snapshot.connection.execute(
            "SELECT link_id,device_reference_id,active,opened_command_id,closed_command_id "
            "FROM task_device_links WHERE task_id=?",
            (result.task_id,),
        ).fetchone()
        assert tuple(sr_link[1:]) == (sr_id, 1, command_id, None)
        assert tuple(rfc_link[1:]) == (rfc_id, 1, command_id, None)
        assert tuple(device_link[1:]) == (device_id, 1, command_id, None)

        assert snapshot.connection.execute(
            "SELECT revision FROM service_requests WHERE service_request_id=?", (sr_id,)
        ).fetchone()[0] == 1
        assert snapshot.connection.execute(
            "SELECT revision FROM rfcs WHERE rfc_id=?", (rfc_id,)
        ).fetchone()[0] == 1
        assert snapshot.connection.execute(
            "SELECT revision FROM device_references WHERE device_reference_id=?", (device_id,)
        ).fetchone()[0] == 1

        audit_refs = snapshot.connection.execute(
            "SELECT r.result_type,r.result_id FROM audit_event_results r "
            "JOIN audit_events e ON e.audit_event_id=r.audit_event_id WHERE e.command_id=? "
            "ORDER BY r.result_type,r.result_id",
            (command_id,),
        ).fetchall()
        relationship_ids = {str(sr_link[0]), str(rfc_link[0]), str(device_link[0])}
        expected_refs = {
            ("task", result.task_id),
            *(("task_relationship", relationship_id) for relationship_id in relationship_ids),
        }
        assert _result_refs(result) == expected_refs
        assert {(str(row[0]), str(row[1])) for row in audit_refs} == expected_refs


def test_create_local_task_relationship_selection_is_canonical_for_replay(initialized_database) -> None:
    factory = _factory(initialized_database)
    service = TaskPlanningService(factory)
    first_sr = _create_sr(factory)
    second_sr = _create_sr(factory)
    command_id = new_uuid4()

    applied = service.create_local_task(
        command_id=command_id,
        local_task_name="Canonical relation order",
        service_request_ids=[second_sr, first_sr],
    )
    replayed = service.create_local_task(
        command_id=command_id,
        local_task_name="Canonical relation order",
        service_request_ids=[first_sr, second_sr],
    )
    assert replayed.replayed
    assert replayed.task_id == applied.task_id
    assert replayed.result_refs == applied.result_refs

    with ReadSnapshot(factory) as snapshot:
        rows = snapshot.connection.execute(
            "SELECT service_request_id FROM task_sr_links WHERE task_id=? ORDER BY service_request_id",
            (applied.task_id,),
        ).fetchall()
        assert [str(row[0]) for row in rows] == sorted([first_sr, second_sr])


def test_create_local_task_rejects_duplicate_missing_or_oversized_relationship_targets_without_receipt(
    initialized_database,
) -> None:
    factory = _factory(initialized_database)
    service = TaskPlanningService(factory)
    sr_id = _create_sr(factory)
    duplicate_command = new_uuid4()
    missing_command = new_uuid4()
    oversized_command = new_uuid4()

    with pytest.raises(ValidationError):
        service.create_local_task(
            command_id=duplicate_command,
            local_task_name="Duplicate relation",
            service_request_ids=[sr_id, sr_id],
        )
    with pytest.raises(ValidationError):
        service.create_local_task(
            command_id=missing_command,
            local_task_name="Missing relation",
            device_reference_ids=[new_uuid4()],
        )
    with pytest.raises(ValidationError):
        service.create_local_task(
            command_id=oversized_command,
            local_task_name="Too many initial relations",
            service_request_ids=[new_uuid4() for _ in range(63)],
        )

    with ReadSnapshot(factory) as snapshot:
        for command_id in (duplicate_command, missing_command, oversized_command):
            assert snapshot.connection.execute(
                "SELECT 1 FROM command_receipts WHERE command_id=?", (command_id,)
            ).fetchone() is None
            assert snapshot.connection.execute(
                "SELECT 1 FROM tasks WHERE created_command_id=?", (command_id,)
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


def test_create_local_task_relationship_failure_rolls_back_every_prior_creation_write(
    initialized_database,
    monkeypatch,
) -> None:
    factory = _factory(initialized_database)
    service = TaskPlanningService(factory)
    sr_id = _create_sr(factory)
    device_id = _create_device(factory, 202)
    command_id = new_uuid4()
    original_link = TaskRelationshipRepository.link
    calls = 0

    def fail_on_second_relationship(uow, row) -> None:
        nonlocal calls
        calls += 1
        if calls == 2:
            raise RuntimeError("injected F001 relationship failure")
        original_link(uow, row)

    monkeypatch.setattr(TaskRelationshipRepository, "link", staticmethod(fail_on_second_relationship))
    with pytest.raises(RuntimeError, match="injected F001 relationship failure"):
        service.create_local_task(
            command_id=command_id,
            local_task_name="Relationship rollback probe",
            service_request_ids=[sr_id],
            device_reference_ids=[device_id],
        )

    with ReadSnapshot(factory) as snapshot:
        assert snapshot.connection.execute(
            "SELECT 1 FROM command_receipts WHERE command_id=?", (command_id,)
        ).fetchone() is None
        assert snapshot.connection.execute(
            "SELECT 1 FROM tasks WHERE created_command_id=?", (command_id,)
        ).fetchone() is None
        assert snapshot.connection.execute(
            "SELECT 1 FROM task_sr_links WHERE opened_command_id=?", (command_id,)
        ).fetchone() is None
        assert snapshot.connection.execute(
            "SELECT 1 FROM task_device_links WHERE opened_command_id=?", (command_id,)
        ).fetchone() is None
        assert snapshot.connection.execute(
            "SELECT 1 FROM audit_events WHERE command_id=?", (command_id,)
        ).fetchone() is None

    monkeypatch.setattr(TaskRelationshipRepository, "link", staticmethod(original_link))
    retried = service.create_local_task(
        command_id=command_id,
        local_task_name="Relationship rollback probe",
        service_request_ids=[sr_id],
        device_reference_ids=[device_id],
    )
    assert retried.outcome == "APPLIED"
    assert not retried.replayed
