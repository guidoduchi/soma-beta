from __future__ import annotations

import json

import pytest

from soma.foundation.errors import IntegrityFailure, SomaError
from soma.foundation.identifiers import new_uuid4
from soma.foundation.persistence.uow import ReadSnapshot, UnitOfWork
from soma.objectives_tasks import AcceptedTaskSchedule, TaskPlanningService, TaskNoStatus, WfmTaskRepository
from soma.tickets.rfcs import RfcService


def _factory(initialized_database):
    database_path, factory_for_path = initialized_database
    return factory_for_path(database_path)


def _create_rfc(factory, rfc_no: str) -> str:
    result = RfcService(factory).create_or_adopt_identity(
        command_id=new_uuid4(),
        rfc_no=rfc_no,
        creation_context="provisional",
    )
    return result.rfc_id


def _insert_hard_delete_receipt(uow: UnitOfWork, *, command_id: str, task_id: str) -> None:
    uow.connection.execute(
        "INSERT INTO command_receipts(command_id,command_type,request_hash,target_type,target_id,committed_at_utc,result_type,result_id) "
        "VALUES (?, 'HardDeleteTask', ?, 'task', ?, 0, NULL, NULL)",
        (command_id, "0" * 64, task_id),
    )


def test_register_manual_wfm_task_persists_identity_assignment_audit_and_exact_replay(initialized_database) -> None:
    factory = _factory(initialized_database)
    rfc_id = _create_rfc(factory, "NC00000000000001")
    service = TaskPlanningService(factory)
    command_id = new_uuid4()
    task_no = "TK00000000000001"

    applied = service.register_manual_wfm_task(
        command_id=command_id,
        task_no=task_no,
        rfc_id=rfc_id,
    )

    assert applied.outcome == "APPLIED"
    assert applied.task_no == task_no
    assert applied.rfc_id == rfc_id
    assert applied.task_revision == 1
    assert applied.assignment_revision == 1
    assert applied.plan_revision_id is None
    assert not applied.replayed
    assert not applied.no_change

    with ReadSnapshot(factory) as snapshot:
        task = snapshot.connection.execute(
            "SELECT task_kind,local_task_name,creation_origin,revision,created_command_id FROM tasks WHERE task_id=?",
            (applied.task_id,),
        ).fetchone()
        assert tuple(task) == ("wfm", None, "wfm_manual", 1, command_id)

        identity = snapshot.connection.execute(
            "SELECT task_no,current_rfc_id,assignment_revision,created_command_id FROM wfm_task_identities WHERE task_id=?",
            (applied.task_id,),
        ).fetchone()
        assert tuple(identity) == (task_no, rfc_id, 1, command_id)

        assignment = snapshot.connection.execute(
            "SELECT prior_rfc_id,new_rfc_id,reason_code,review_risk,command_id FROM wfm_rfc_assignment_events WHERE task_id=?",
            (applied.task_id,),
        ).fetchone()
        assert tuple(assignment) == (None, rfc_id, "manual_registration", "low", command_id)

        audit = snapshot.connection.execute(
            "SELECT action_type,payload_json FROM audit_events WHERE command_id=?",
            (command_id,),
        ).fetchone()
        assert audit is not None and str(audit[0]) == "task.wfm_registered"
        payload = json.loads(str(audit[1]))
        assert payload == {
            "creation_origin": "wfm_manual",
            "reason_category": None,
            "resulting_revision": 1,
            "task_id": applied.task_id,
            "task_kind": "wfm",
            "task_plan_revision_id": None,
        }

        refs = snapshot.connection.execute(
            "SELECT r.result_type,r.result_id FROM audit_event_results r "
            "JOIN audit_events e ON e.audit_event_id=r.audit_event_id "
            "WHERE e.command_id=? ORDER BY r.result_type,r.result_id",
            (command_id,),
        ).fetchall()
        assert [(str(row[0]), str(row[1])) for row in refs] == [
            ("task", applied.task_id),
            ("wfm_assignment", str(assignment[4]) if False else str(snapshot.connection.execute(
                "SELECT assignment_event_id FROM wfm_rfc_assignment_events WHERE task_id=?", (applied.task_id,)
            ).fetchone()[0])),
        ]

        receipt = snapshot.connection.execute(
            "SELECT command_type,target_type,target_id,result_type,result_id FROM command_receipts WHERE command_id=?",
            (command_id,),
        ).fetchone()
        assert tuple(receipt) == ("RegisterManualWfmTask", "task", None, "task", applied.task_id)

        exact = snapshot.connection.execute(
            "SELECT response_schema,response_version FROM command_receipt_results WHERE command_id=?",
            (command_id,),
        ).fetchone()
        assert tuple(exact) == ("TaskMutationResultV1", 1)

    replayed = service.register_manual_wfm_task(
        command_id=command_id,
        task_no=task_no,
        rfc_id=rfc_id,
    )
    assert replayed.replayed
    assert replayed == type(replayed)(
        outcome="APPLIED",
        task_id=applied.task_id,
        task_no=task_no,
        rfc_id=rfc_id,
        task_revision=1,
        assignment_revision=1,
        plan_revision_id=None,
        replayed=True,
    )

    no_change_command = new_uuid4()
    adopted = service.register_manual_wfm_task(
        command_id=no_change_command,
        task_no=task_no,
        rfc_id=rfc_id,
    )
    assert adopted.no_change
    assert adopted.outcome == "NO_CHANGE"
    assert adopted.task_id == applied.task_id
    assert not adopted.replayed

    with ReadSnapshot(factory) as snapshot:
        assert snapshot.connection.execute(
            "SELECT count(*) FROM audit_events WHERE command_id=?", (no_change_command,)
        ).fetchone()[0] == 0
        assert snapshot.connection.execute(
            "SELECT result_type FROM command_receipts WHERE command_id=?", (no_change_command,)
        ).fetchone()[0] == "NO_CHANGE"
        assert snapshot.connection.execute(
            "SELECT count(*) FROM wfm_rfc_assignment_events WHERE task_id=?", (applied.task_id,)
        ).fetchone()[0] == 1


def test_register_manual_wfm_task_with_schedule_persists_manual_operational_plan(initialized_database) -> None:
    factory = _factory(initialized_database)
    rfc_id = _create_rfc(factory, "NC00000000000002")
    service = TaskPlanningService(factory)
    command_id = new_uuid4()
    schedule = AcceptedTaskSchedule(
        start_utc=1_800_000_000,
        end_utc=1_800_003_600,
        scheduling_timezone_iana="America/Guayaquil",
    )

    result = service.register_manual_wfm_task(
        command_id=command_id,
        task_no="TK00000000000002",
        rfc_id=rfc_id,
        schedule=schedule,
    )
    assert result.plan_revision_id is not None

    with ReadSnapshot(factory) as snapshot:
        plan = snapshot.connection.execute(
            "SELECT p.start_utc,p.end_utc,p.origin,p.scheduling_timezone_iana,p.source_observation_id,"
            "p.predecessor_plan_revision_id,p.reason_code,p.command_id,c.revision,c.last_command_id "
            "FROM task_plan_revisions p JOIN task_plan_current c ON c.plan_revision_id=p.plan_revision_id "
            "WHERE p.plan_revision_id=? AND p.task_id=?",
            (result.plan_revision_id, result.task_id),
        ).fetchone()
        assert tuple(plan) == (
            schedule.start_utc,
            schedule.end_utc,
            "manual",
            "America/Guayaquil",
            None,
            None,
            None,
            command_id,
            1,
            command_id,
        )

        audit_payload = snapshot.connection.execute(
            "SELECT payload_json FROM audit_events WHERE command_id=? AND action_type='task.wfm_registered'",
            (command_id,),
        ).fetchone()
        assert audit_payload is not None
        assert json.loads(str(audit_payload[0]))["task_plan_revision_id"] == result.plan_revision_id

        ref_types = snapshot.connection.execute(
            "SELECT r.result_type FROM audit_event_results r JOIN audit_events e ON e.audit_event_id=r.audit_event_id "
            "WHERE e.command_id=? ORDER BY r.result_type",
            (command_id,),
        ).fetchall()
        assert [str(row[0]) for row in ref_types] == ["task", "wfm_assignment"]


def test_register_manual_wfm_task_rejects_different_parent_and_missing_rfc_before_receipt(initialized_database) -> None:
    factory = _factory(initialized_database)
    first_rfc_id = _create_rfc(factory, "NC00000000000003")
    second_rfc_id = _create_rfc(factory, "NC00000000000004")
    service = TaskPlanningService(factory)
    task_no = "TK00000000000003"

    service.register_manual_wfm_task(
        command_id=new_uuid4(),
        task_no=task_no,
        rfc_id=first_rfc_id,
    )

    parent_change_command = new_uuid4()
    with pytest.raises(SomaError) as parent_error:
        service.register_manual_wfm_task(
            command_id=parent_change_command,
            task_no=task_no,
            rfc_id=second_rfc_id,
        )
    assert parent_error.value.code == "WFM_PARENT_STALE"

    missing_rfc_command = new_uuid4()
    with pytest.raises(SomaError) as missing_error:
        service.register_manual_wfm_task(
            command_id=missing_rfc_command,
            task_no="TK00000000000004",
            rfc_id=new_uuid4(),
        )
    assert missing_error.value.code == "WFM_RFC_NOT_ELIGIBLE"

    invalid_command = new_uuid4()
    with pytest.raises(SomaError) as invalid_error:
        service.register_manual_wfm_task(
            command_id=invalid_command,
            task_no="TK123",
            rfc_id=first_rfc_id,
        )
    assert invalid_error.value.code == "WFM_TASK_NO_INVALID"

    with ReadSnapshot(factory) as snapshot:
        for command_id in (parent_change_command, missing_rfc_command, invalid_command):
            assert snapshot.connection.execute(
                "SELECT 1 FROM command_receipts WHERE command_id=?", (command_id,)
            ).fetchone() is None


def test_retired_wfm_task_no_is_permanent_nonreuse_authority(initialized_database) -> None:
    factory = _factory(initialized_database)
    rfc_id = _create_rfc(factory, "NC00000000000005")
    service = TaskPlanningService(factory)
    task_no = "TK00000000000005"
    registered = service.register_manual_wfm_task(
        command_id=new_uuid4(),
        task_no=task_no,
        rfc_id=rfc_id,
    )

    hard_delete_command = new_uuid4()
    retirement_id = new_uuid4()
    with UnitOfWork(factory) as uow:
        _insert_hard_delete_receipt(
            uow,
            command_id=hard_delete_command,
            task_id=registered.task_id,
        )
        WfmTaskRepository.retire_task_no(
            uow,
            retirement_id=retirement_id,
            task_no=task_no,
            task_id=registered.task_id,
            retired_at_utc=1,
            hard_delete_command_id=hard_delete_command,
        )
        uow.connection.execute(
            "DELETE FROM wfm_rfc_assignment_events WHERE task_id=?", (registered.task_id,)
        )
        uow.connection.execute(
            "DELETE FROM wfm_task_identities WHERE task_id=?", (registered.task_id,)
        )
        uow.connection.execute("DELETE FROM tasks WHERE task_id=?", (registered.task_id,))

    with ReadSnapshot(factory) as snapshot:
        assert WfmTaskRepository.task_no_status(snapshot.connection, task_no) is TaskNoStatus.RETIRED
        retirement = snapshot.connection.execute(
            "SELECT retired_task_id,hard_delete_command_id FROM wfm_task_no_retirements WHERE task_no=?",
            (task_no,),
        ).fetchone()
        assert tuple(retirement) == (registered.task_id, hard_delete_command)

    rejected_command = new_uuid4()
    with pytest.raises(SomaError) as exc_info:
        service.register_manual_wfm_task(
            command_id=rejected_command,
            task_no=task_no,
            rfc_id=rfc_id,
        )
    assert exc_info.value.code == "WFM_TASK_NO_RETIRED"

    with ReadSnapshot(factory) as snapshot:
        assert snapshot.connection.execute(
            "SELECT 1 FROM command_receipts WHERE command_id=?", (rejected_command,)
        ).fetchone() is None
        assert snapshot.connection.execute(
            "SELECT 1 FROM wfm_task_identities WHERE task_no=?", (task_no,)
        ).fetchone() is None


def test_task_no_status_fails_closed_on_active_retired_collision_and_rolls_back(initialized_database) -> None:
    factory = _factory(initialized_database)
    rfc_id = _create_rfc(factory, "NC00000000000006")
    service = TaskPlanningService(factory)
    task_no = "TK00000000000006"
    registered = service.register_manual_wfm_task(
        command_id=new_uuid4(),
        task_no=task_no,
        rfc_id=rfc_id,
    )
    hard_delete_command = new_uuid4()

    with pytest.raises(IntegrityFailure):
        with UnitOfWork(factory) as uow:
            _insert_hard_delete_receipt(
                uow,
                command_id=hard_delete_command,
                task_id=registered.task_id,
            )
            WfmTaskRepository.retire_task_no(
                uow,
                retirement_id=new_uuid4(),
                task_no=task_no,
                task_id=registered.task_id,
                retired_at_utc=1,
                hard_delete_command_id=hard_delete_command,
            )
            WfmTaskRepository.task_no_status(uow.connection, task_no)

    with ReadSnapshot(factory) as snapshot:
        assert WfmTaskRepository.task_no_status(snapshot.connection, task_no) is TaskNoStatus.ACTIVE
        assert snapshot.connection.execute(
            "SELECT 1 FROM wfm_task_no_retirements WHERE task_no=?", (task_no,)
        ).fetchone() is None
        assert snapshot.connection.execute(
            "SELECT 1 FROM command_receipts WHERE command_id=?", (hard_delete_command,)
        ).fetchone() is None
