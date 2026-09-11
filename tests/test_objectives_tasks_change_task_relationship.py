from __future__ import annotations

import json

import pytest

from soma.foundation.errors import IdempotencyConflict, PersistenceFailure, SomaError, ValidationError
from soma.foundation.identifiers import new_uuid4
from soma.foundation.persistence.uow import ReadSnapshot
from soma.objectives_tasks import TaskPlanningService
from soma.objectives_tasks.services.task_relationships import TaskRelationshipService
from soma.tickets.device_references import DeviceReferenceService
from soma.tickets.rfcs import RfcService
from soma.tickets.service_requests import ServiceRequestService


_RELATIONSHIP_STORAGE = {
    "sr": ("task_sr_links", "service_request_id"),
    "rfc": ("task_rfc_links", "rfc_id"),
    "device": ("task_device_links", "device_reference_id"),
}


def _factory(initialized_database):
    database_path, factory_for_path = initialized_database
    return factory_for_path(database_path)


def _create_local(factory):
    return TaskPlanningService(factory).create_local_task(
        command_id=new_uuid4(), local_task_name="Relationship target"
    )


def _create_sr(factory) -> str:
    return ServiceRequestService(factory).create_manual_service_request(
        command_id=new_uuid4()
    ).service_request_id


def _create_rfc(factory, suffix: int) -> str:
    return RfcService(factory).create_or_adopt_identity(
        command_id=new_uuid4(),
        rfc_no=f"NC{suffix:014d}",
        creation_context="manual",
    ).rfc_id


def _create_device(factory, suffix: int) -> str:
    return DeviceReferenceService(factory).create(
        command_id=new_uuid4(), operational_name=f"NE-REL-{suffix}"
    ).device_reference_id


def _create_wfm(factory, suffix: int):
    return TaskPlanningService(factory).register_manual_wfm_task(
        command_id=new_uuid4(),
        task_no=f"TK{suffix:014d}",
        rfc_id=_create_rfc(factory, 8_000 + suffix),
    )


def _receipt_exists(factory, command_id: str) -> bool:
    with ReadSnapshot(factory) as snapshot:
        return snapshot.connection.execute(
            "SELECT 1 FROM command_receipts WHERE command_id=?", (command_id,)
        ).fetchone() is not None


def _task_revision(factory, task_id: str) -> int:
    with ReadSnapshot(factory) as snapshot:
        row = snapshot.connection.execute(
            "SELECT revision FROM tasks WHERE task_id=?", (task_id,)
        ).fetchone()
    assert row is not None
    return int(row[0])


def _relationship_rows(factory, task_id: str, kind: str, target_id: str):
    table, target_column = _RELATIONSHIP_STORAGE[kind]
    with ReadSnapshot(factory) as snapshot:
        return snapshot.connection.execute(
            f"SELECT link_id,active,opened_command_id,closed_command_id FROM {table} "
            f"WHERE task_id=? AND {target_column}=? ORDER BY rowid",
            (task_id, target_id),
        ).fetchall()


def _change(
    factory,
    *,
    task_id: str,
    task_revision: int,
    kind: str,
    target_id: str,
    action: str,
    reason: str | None = None,
    command_id: str | None = None,
):
    return TaskRelationshipService(factory).change_task_relationship(
        command_id=new_uuid4() if command_id is None else command_id,
        task_id=task_id,
        task_revision=task_revision,
        relationship_kind=kind,
        target_id=target_id,
        action=action,
        reason_category=reason,
    )


def test_local_task_links_sr_rfc_and_device_with_exact_audit(initialized_database) -> None:
    factory = _factory(initialized_database)
    task = _create_local(factory)
    targets = {
        "sr": _create_sr(factory),
        "rfc": _create_rfc(factory, 101),
        "device": _create_device(factory, 101),
    }

    for offset, kind in enumerate(("sr", "rfc", "device")):
        expected_revision = 1 + offset
        command_id = new_uuid4()
        result = _change(
            factory,
            command_id=command_id,
            task_id=task.task_id,
            task_revision=expected_revision,
            kind=kind,
            target_id=targets[kind],
            action="link",
        )
        assert result.outcome == "APPLIED"
        assert result.revision == expected_revision + 1
        assert len(result.result_refs) == 1
        relationship_id = result.result_refs[0].result_id
        assert result.result_refs[0].result_type == "task_relationship"
        assert tuple(_relationship_rows(factory, task.task_id, kind, targets[kind])[0]) == (
            relationship_id,
            1,
            command_id,
            None,
        )

        with ReadSnapshot(factory) as snapshot:
            audit = snapshot.connection.execute(
                "SELECT audit_event_id,action_type,payload_schema,payload_json "
                "FROM audit_events WHERE command_id=?",
                (command_id,),
            ).fetchone()
            assert audit is not None
            assert (str(audit[1]), str(audit[2])) == (
                "task.relationship_changed",
                "TaskRelationshipAuditV1",
            )
            assert json.loads(str(audit[3])) == {
                "action": "OPEN",
                "prior_related_id": None,
                "reason_category": None,
                "related_id": targets[kind],
                "relationship_id": relationship_id,
                "relationship_kind": kind,
                "resulting_revision": expected_revision + 1,
                "task_id": task.task_id,
            }
            assert snapshot.connection.execute(
                "SELECT result_type,result_id FROM audit_event_results WHERE audit_event_id=?",
                (str(audit[0]),),
            ).fetchone() == ("task_relationship", relationship_id)

    assert _task_revision(factory, task.task_id) == 4


def test_wfm_device_link_and_unlink_are_legal_and_revisioned(initialized_database) -> None:
    factory = _factory(initialized_database)
    task = _create_wfm(factory, 201)
    device_id = _create_device(factory, 201)
    open_command_id = new_uuid4()
    linked = _change(
        factory,
        command_id=open_command_id,
        task_id=task.task_id,
        task_revision=1,
        kind="device",
        target_id=device_id,
        action="link",
    )
    assert linked.revision == 2
    relationship_id = linked.result_refs[0].result_id

    close_command_id = new_uuid4()
    unlinked = _change(
        factory,
        command_id=close_command_id,
        task_id=task.task_id,
        task_revision=2,
        kind="device",
        target_id=device_id,
        action="unlink",
        reason="device_context_removed",
    )
    assert unlinked.revision == 3
    assert unlinked.result_refs[0].result_id == relationship_id
    assert tuple(_relationship_rows(factory, task.task_id, "device", device_id)[0]) == (
        relationship_id,
        0,
        open_command_id,
        close_command_id,
    )
    assert _task_revision(factory, task.task_id) == 3


def test_wfm_direct_sr_and_rfc_relationships_are_rejected_before_receipt(initialized_database) -> None:
    factory = _factory(initialized_database)
    task = _create_wfm(factory, 202)
    targets = {"sr": _create_sr(factory), "rfc": _create_rfc(factory, 202)}

    for kind, target_id in targets.items():
        command_id = new_uuid4()
        with pytest.raises(SomaError) as exc_info:
            _change(
                factory,
                command_id=command_id,
                task_id=task.task_id,
                task_revision=1,
                kind=kind,
                target_id=target_id,
                action="link",
            )
        assert exc_info.value.code == "TASK_RELATIONSHIP_INVALID"
        assert not _receipt_exists(factory, command_id)
        assert _relationship_rows(factory, task.task_id, kind, target_id) == []
    assert _task_revision(factory, task.task_id) == 1


def test_missing_target_fails_before_no_change_or_receipt(initialized_database) -> None:
    factory = _factory(initialized_database)
    task = _create_local(factory)
    for kind in ("sr", "rfc", "device"):
        for action in ("link", "unlink"):
            command_id = new_uuid4()
            with pytest.raises(SomaError) as exc_info:
                _change(
                    factory,
                    command_id=command_id,
                    task_id=task.task_id,
                    task_revision=1,
                    kind=kind,
                    target_id=new_uuid4(),
                    action=action,
                    reason="missing_target" if action == "unlink" else None,
                )
            assert exc_info.value.code == "TASK_RELATIONSHIP_TARGET_NOT_FOUND"
            assert not _receipt_exists(factory, command_id)
    assert _task_revision(factory, task.task_id) == 1


def test_stale_task_revision_fails_before_receipt(initialized_database) -> None:
    factory = _factory(initialized_database)
    task = _create_local(factory)
    device_id = _create_device(factory, 203)
    command_id = new_uuid4()
    with pytest.raises(SomaError) as exc_info:
        _change(
            factory,
            command_id=command_id,
            task_id=task.task_id,
            task_revision=2,
            kind="device",
            target_id=device_id,
            action="link",
        )
    assert exc_info.value.code == "TASK_STALE"
    assert not _receipt_exists(factory, command_id)
    assert _relationship_rows(factory, task.task_id, "device", device_id) == []


def test_already_active_link_and_absent_unlink_are_no_change(initialized_database) -> None:
    factory = _factory(initialized_database)
    task = _create_local(factory)
    sr_id = _create_sr(factory)
    device_id = _create_device(factory, 204)
    first = _change(
        factory,
        task_id=task.task_id,
        task_revision=1,
        kind="sr",
        target_id=sr_id,
        action="link",
    )

    same_command = new_uuid4()
    same = _change(
        factory,
        command_id=same_command,
        task_id=task.task_id,
        task_revision=2,
        kind="sr",
        target_id=sr_id,
        action="link",
    )
    assert same.no_change and same.revision == 2 and same.result_refs == ()
    assert not _receipt_exists(factory, same_command)
    assert first.result_refs[0].result_id == _relationship_rows(
        factory, task.task_id, "sr", sr_id
    )[0][0]

    absent_command = new_uuid4()
    absent = _change(
        factory,
        command_id=absent_command,
        task_id=task.task_id,
        task_revision=2,
        kind="device",
        target_id=device_id,
        action="unlink",
        reason="nothing_to_remove",
    )
    assert absent.no_change and absent.revision == 2 and absent.result_refs == ()
    assert not _receipt_exists(factory, absent_command)
    assert _task_revision(factory, task.task_id) == 2


def test_unlink_closes_same_row_and_relink_allocates_new_identity(initialized_database) -> None:
    factory = _factory(initialized_database)
    task = _create_local(factory)
    rfc_id = _create_rfc(factory, 205)
    service = TaskRelationshipService(factory)
    open_command = new_uuid4()
    opened = service.change_task_relationship(
        command_id=open_command,
        task_id=task.task_id,
        task_revision=1,
        relationship_kind="rfc",
        target_id=rfc_id,
        action="link",
    )
    first_id = opened.result_refs[0].result_id

    close_command = new_uuid4()
    closed = service.change_task_relationship(
        command_id=close_command,
        task_id=task.task_id,
        task_revision=2,
        relationship_kind="rfc",
        target_id=rfc_id,
        action="unlink",
        reason_category="relationship_no_longer_applies",
    )
    assert closed.result_refs[0].result_id == first_id
    assert tuple(_relationship_rows(factory, task.task_id, "rfc", rfc_id)[0]) == (
        first_id,
        0,
        open_command,
        close_command,
    )

    reopened = service.change_task_relationship(
        command_id=new_uuid4(),
        task_id=task.task_id,
        task_revision=3,
        relationship_kind="rfc",
        target_id=rfc_id,
        action="link",
    )
    second_id = reopened.result_refs[0].result_id
    assert second_id != first_id
    rows = _relationship_rows(factory, task.task_id, "rfc", rfc_id)
    assert len(rows) == 2
    assert tuple(rows[0]) == (first_id, 0, open_command, close_command)
    assert str(rows[1][0]) == second_id and int(rows[1][1]) == 1 and rows[1][3] is None
    assert _task_revision(factory, task.task_id) == 4


def test_target_metadata_revision_is_not_relationship_freshness_authority(initialized_database) -> None:
    factory = _factory(initialized_database)
    task = _create_local(factory)
    device_id = _create_device(factory, 206)
    corrected = DeviceReferenceService(factory).correct_name(
        command_id=new_uuid4(),
        device_reference_id=device_id,
        base_revision=1,
        operational_name="NE-REL-206-CORRECTED",
        reason_category="name_correction",
    )
    assert corrected.revision == 2
    linked = _change(
        factory,
        task_id=task.task_id,
        task_revision=1,
        kind="device",
        target_id=device_id,
        action="link",
    )
    assert linked.outcome == "APPLIED" and linked.revision == 2


def test_exact_replay_after_later_close_does_not_reopen(initialized_database) -> None:
    factory = _factory(initialized_database)
    task = _create_local(factory)
    device_id = _create_device(factory, 207)
    service = TaskRelationshipService(factory)
    open_command = new_uuid4()
    open_kwargs = dict(
        command_id=open_command,
        task_id=task.task_id,
        task_revision=1,
        relationship_kind="device",
        target_id=device_id,
        action="link",
    )
    opened = service.change_task_relationship(**open_kwargs)
    relationship_id = opened.result_refs[0].result_id
    service.change_task_relationship(
        command_id=new_uuid4(),
        task_id=task.task_id,
        task_revision=2,
        relationship_kind="device",
        target_id=device_id,
        action="unlink",
        reason_category="later_close",
    )

    replay = service.change_task_relationship(**open_kwargs)
    assert replay.replayed
    assert replay.outcome == opened.outcome
    assert replay.revision == opened.revision == 2
    assert replay.result_refs == opened.result_refs
    rows = _relationship_rows(factory, task.task_id, "device", device_id)
    assert len(rows) == 1 and str(rows[0][0]) == relationship_id and int(rows[0][1]) == 0
    assert _task_revision(factory, task.task_id) == 3


def test_command_id_collision_different_payload_is_rejected_before_state_reads(initialized_database) -> None:
    factory = _factory(initialized_database)
    task = _create_local(factory)
    device_id = _create_device(factory, 208)
    command_id = new_uuid4()
    service = TaskRelationshipService(factory)
    opened = service.change_task_relationship(
        command_id=command_id,
        task_id=task.task_id,
        task_revision=1,
        relationship_kind="device",
        target_id=device_id,
        action="link",
    )
    with pytest.raises(IdempotencyConflict):
        service.change_task_relationship(
            command_id=command_id,
            task_id=task.task_id,
            task_revision=1,
            relationship_kind="device",
            target_id=device_id,
            action="unlink",
            reason_category="different_payload",
        )
    rows = _relationship_rows(factory, task.task_id, "device", device_id)
    assert len(rows) == 1 and str(rows[0][0]) == opened.result_refs[0].result_id
    assert int(rows[0][1]) == 1 and _task_revision(factory, task.task_id) == 2


def test_preflight_is_strict_and_writes_nothing(initialized_database) -> None:
    factory = _factory(initialized_database)
    task = _create_local(factory)
    device_id = _create_device(factory, 209)
    service = TaskRelationshipService(factory)
    cases = (
        dict(task_revision=True, relationship_kind="device", target_id=device_id, action="link", reason_category=None),
        dict(task_revision=1, relationship_kind="other", target_id=device_id, action="link", reason_category=None),
        dict(task_revision=1, relationship_kind="device", target_id="not-a-uuid", action="link", reason_category=None),
        dict(task_revision=1, relationship_kind="device", target_id=device_id, action="toggle", reason_category=None),
        dict(task_revision=1, relationship_kind="device", target_id=device_id, action="unlink", reason_category=None),
        dict(task_revision=1, relationship_kind="device", target_id=device_id, action="link", reason_category="ignored"),
        dict(task_revision=1, relationship_kind="device", target_id=device_id, action="unlink", reason_category=""),
        dict(task_revision=1, relationship_kind="device", target_id=device_id, action="unlink", reason_category="bad\nreason"),
        dict(task_revision=1, relationship_kind="device", target_id=device_id, action="unlink", reason_category="é" * 65),
    )
    for case in cases:
        command_id = new_uuid4()
        with pytest.raises(ValidationError):
            service.change_task_relationship(command_id=command_id, task_id=task.task_id, **case)
        assert not _receipt_exists(factory, command_id)
    assert _task_revision(factory, task.task_id) == 1
    assert _relationship_rows(factory, task.task_id, "device", device_id) == []


def test_audit_failure_rolls_back_link_task_revision_and_receipt(initialized_database, monkeypatch) -> None:
    factory = _factory(initialized_database)
    task = _create_local(factory)
    device_id = _create_device(factory, 210)
    service = TaskRelationshipService(factory)
    command_id = new_uuid4()

    def fail_write(*_args, **_kwargs):
        raise PersistenceFailure("injected relationship audit failure")

    monkeypatch.setattr(service._boundary._audit_writer, "write", fail_write)
    with pytest.raises(PersistenceFailure):
        service.change_task_relationship(
            command_id=command_id,
            task_id=task.task_id,
            task_revision=1,
            relationship_kind="device",
            target_id=device_id,
            action="link",
        )
    assert not _receipt_exists(factory, command_id)
    assert _task_revision(factory, task.task_id) == 1
    assert _relationship_rows(factory, task.task_id, "device", device_id) == []


def test_audit_failure_rolls_back_unlink_and_keeps_active_row(initialized_database, monkeypatch) -> None:
    factory = _factory(initialized_database)
    task = _create_local(factory)
    sr_id = _create_sr(factory)
    opened = _change(
        factory,
        task_id=task.task_id,
        task_revision=1,
        kind="sr",
        target_id=sr_id,
        action="link",
    )
    relationship_id = opened.result_refs[0].result_id
    service = TaskRelationshipService(factory)
    command_id = new_uuid4()

    def fail_write(*_args, **_kwargs):
        raise PersistenceFailure("injected relationship audit failure")

    monkeypatch.setattr(service._boundary._audit_writer, "write", fail_write)
    with pytest.raises(PersistenceFailure):
        service.change_task_relationship(
            command_id=command_id,
            task_id=task.task_id,
            task_revision=2,
            relationship_kind="sr",
            target_id=sr_id,
            action="unlink",
            reason_category="rollback_close",
        )
    assert not _receipt_exists(factory, command_id)
    rows = _relationship_rows(factory, task.task_id, "sr", sr_id)
    assert len(rows) == 1 and str(rows[0][0]) == relationship_id
    assert int(rows[0][1]) == 1 and rows[0][3] is None
    assert _task_revision(factory, task.task_id) == 2
