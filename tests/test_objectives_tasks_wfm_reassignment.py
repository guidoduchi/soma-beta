from __future__ import annotations

import json

import pytest

from soma.foundation.errors import SomaError, ValidationError
from soma.foundation.identifiers import new_uuid4
from soma.foundation.persistence.uow import ReadSnapshot, UnitOfWork
from soma.objectives_tasks import AcceptedTaskSchedule, TaskPlanningService
from soma.tickets.rfcs import RfcService


def _factory(initialized_database):
    database_path, factory_for_path = initialized_database
    return factory_for_path(database_path)


def _create_rfc(factory, rfc_no: str) -> str:
    return RfcService(factory).create_or_adopt_identity(
        command_id=new_uuid4(),
        rfc_no=rfc_no,
        creation_context="provisional",
    ).rfc_id


def _register(factory, *, rfc_id: str, task_no: str, schedule: AcceptedTaskSchedule | None = None):
    command_id = new_uuid4()
    result = TaskPlanningService(factory).register_manual_wfm_task(
        command_id=command_id,
        task_no=task_no,
        rfc_id=rfc_id,
        schedule=schedule,
    )
    return command_id, result


def _receipt_exists(factory, command_id: str) -> bool:
    with ReadSnapshot(factory) as snapshot:
        return snapshot.connection.execute(
            "SELECT 1 FROM command_receipts WHERE command_id=?",
            (command_id,),
        ).fetchone() is not None


def _rfc_authority(factory, rfc_id: str) -> tuple[int, int]:
    with ReadSnapshot(factory) as snapshot:
        row = snapshot.connection.execute(
            "SELECT r.revision,COALESCE(p.revision,0) "
            "FROM rfcs r LEFT JOIN rfc_current_source_projection p ON p.rfc_id=r.rfc_id "
            "WHERE r.rfc_id=?",
            (rfc_id,),
        ).fetchone()
    assert row is not None
    return int(row[0]), int(row[1])


def _freshness(factory, *, current_rfc_id: str, new_rfc_id: str) -> dict[str, int]:
    current_rfc_revision, current_source_revision = _rfc_authority(factory, current_rfc_id)
    new_rfc_revision, new_source_revision = _rfc_authority(factory, new_rfc_id)
    return {
        "current_rfc_revision": current_rfc_revision,
        "current_rfc_source_projection_revision": current_source_revision,
        "new_rfc_revision": new_rfc_revision,
        "new_rfc_source_projection_revision": new_source_revision,
    }


def _reassign(
    factory,
    *,
    task_id: str,
    task_revision: int,
    assignment_revision: int,
    current_rfc_id: str,
    new_rfc_id: str,
    command_id: str | None = None,
    reason_category: str = "manual_correction",
    accept_high_risk: bool = False,
    freshness: dict[str, int] | None = None,
):
    bases = _freshness(factory, current_rfc_id=current_rfc_id, new_rfc_id=new_rfc_id) if freshness is None else freshness
    return TaskPlanningService(factory).reassign_wfm_parent(
        command_id=new_uuid4() if command_id is None else command_id,
        task_id=task_id,
        task_revision=task_revision,
        assignment_revision=assignment_revision,
        new_rfc_id=new_rfc_id,
        reason_category=reason_category,
        accept_high_risk=accept_high_risk,
        **bases,
    )


def test_reassign_wfm_parent_low_risk_preserves_identity_and_audits_exact_event(initialized_database) -> None:
    factory = _factory(initialized_database)
    old_rfc = _create_rfc(factory, "NC00000000000101")
    new_rfc = _create_rfc(factory, "NC00000000000102")
    _, registered = _register(factory, rfc_id=old_rfc, task_no="TK00000000000101")
    command_id = new_uuid4()
    rfc_bases = _freshness(factory, current_rfc_id=old_rfc, new_rfc_id=new_rfc)

    with ReadSnapshot(factory) as snapshot:
        before_task = snapshot.connection.execute(
            "SELECT task_kind,creation_origin,created_command_id FROM tasks WHERE task_id=?",
            (registered.task_id,),
        ).fetchone()
        before_identity = snapshot.connection.execute(
            "SELECT task_no,created_command_id FROM wfm_task_identities WHERE task_id=?",
            (registered.task_id,),
        ).fetchone()

    result = _reassign(
        factory,
        command_id=command_id,
        task_id=registered.task_id,
        task_revision=1,
        assignment_revision=1,
        current_rfc_id=old_rfc,
        new_rfc_id=new_rfc,
        freshness=rfc_bases,
    )

    assert result.outcome == "APPLIED"
    assert result.revision == 2
    assert not result.replayed
    assert len(result.result_refs) == 1
    assignment_event_id = result.result_refs[0].result_id
    assert result.result_refs[0].result_type == "wfm_assignment"

    with ReadSnapshot(factory) as snapshot:
        task = snapshot.connection.execute(
            "SELECT task_kind,creation_origin,created_command_id,revision FROM tasks WHERE task_id=?",
            (registered.task_id,),
        ).fetchone()
        assert tuple(task[:3]) == tuple(before_task)
        assert int(task[3]) == 2
        identity = snapshot.connection.execute(
            "SELECT task_no,current_rfc_id,assignment_revision,created_command_id FROM wfm_task_identities WHERE task_id=?",
            (registered.task_id,),
        ).fetchone()
        assert (str(identity[0]), str(identity[3])) == (str(before_identity[0]), str(before_identity[1]))
        assert (str(identity[1]), int(identity[2])) == (new_rfc, 2)

        events = snapshot.connection.execute(
            "SELECT assignment_event_id,prior_rfc_id,new_rfc_id,reason_code,review_risk,command_id "
            "FROM wfm_rfc_assignment_events WHERE task_id=? ORDER BY recorded_at_utc,assignment_event_id",
            (registered.task_id,),
        ).fetchall()
        assert len(events) == 2
        reassignment = next(row for row in events if str(row[0]) == assignment_event_id)
        assert tuple(reassignment[1:]) == (
            old_rfc,
            new_rfc,
            "manual_correction",
            "low",
            command_id,
        )

        assert snapshot.connection.execute(
            "SELECT revision FROM rfcs WHERE rfc_id=?", (old_rfc,)
        ).fetchone()[0] == rfc_bases["current_rfc_revision"]
        assert snapshot.connection.execute(
            "SELECT revision FROM rfcs WHERE rfc_id=?", (new_rfc,)
        ).fetchone()[0] == rfc_bases["new_rfc_revision"]
        assert snapshot.connection.execute(
            "SELECT count(*) FROM rfc_current_source_projection WHERE rfc_id IN (?,?)",
            (old_rfc, new_rfc),
        ).fetchone()[0] == 0
        for table in (
            "task_plan_revisions",
            "wfm_source_projection_cache",
            "objective_membership_events",
            "task_execution_events",
            "task_retry_relations",
            "task_outcome_events",
        ):
            if table == "task_retry_relations":
                count = snapshot.connection.execute(
                    "SELECT count(*) FROM task_retry_relations WHERE predecessor_task_id=? OR successor_task_id=?",
                    (registered.task_id, registered.task_id),
                ).fetchone()[0]
            else:
                count = snapshot.connection.execute(
                    f"SELECT count(*) FROM {table} WHERE task_id=?", (registered.task_id,)
                ).fetchone()[0]
            assert count == 0

        audit = snapshot.connection.execute(
            "SELECT audit_event_id,action_type,reason_category,payload_json FROM audit_events WHERE command_id=?",
            (command_id,),
        ).fetchone()
        assert audit is not None
        assert str(audit[1]) == "task.wfm_parent_reassigned"
        assert str(audit[2]) == "manual_correction"
        assert json.loads(str(audit[3])) == {
            "action": "REASSIGN",
            "prior_related_id": old_rfc,
            "reason_category": "manual_correction",
            "related_id": new_rfc,
            "relationship_id": assignment_event_id,
            "relationship_kind": "wfm_parent",
            "resulting_revision": 2,
            "task_id": registered.task_id,
        }
        refs = snapshot.connection.execute(
            "SELECT result_type,result_id FROM audit_event_results WHERE audit_event_id=?",
            (str(audit[0]),),
        ).fetchall()
        assert [(str(row[0]), str(row[1])) for row in refs] == [("wfm_assignment", assignment_event_id)]


def test_reassign_wfm_parent_exact_replay_precedes_rfc_reads_and_same_parent_no_change(initialized_database) -> None:
    factory = _factory(initialized_database)
    old_rfc = _create_rfc(factory, "NC00000000000103")
    new_rfc = _create_rfc(factory, "NC00000000000104")
    _, registered = _register(factory, rfc_id=old_rfc, task_no="TK00000000000102")
    command_id = new_uuid4()
    original_bases = _freshness(factory, current_rfc_id=old_rfc, new_rfc_id=new_rfc)
    kwargs = dict(
        command_id=command_id,
        task_id=registered.task_id,
        task_revision=1,
        assignment_revision=1,
        current_rfc_id=old_rfc,
        new_rfc_id=new_rfc,
        reason_category="operator_review",
        accept_high_risk=False,
        freshness=original_bases,
    )
    applied = _reassign(factory, **kwargs)

    # Replay must not depend on mutable RFC authority after the original commit.
    with UnitOfWork(factory) as uow:
        uow.connection.execute("UPDATE rfcs SET revision=revision+1 WHERE rfc_id=?", (old_rfc,))
        uow.connection.execute("UPDATE rfcs SET revision=revision+1 WHERE rfc_id=?", (new_rfc,))
    replay = _reassign(factory, **kwargs)
    assert replay.replayed
    assert replay.outcome == applied.outcome
    assert replay.task_id == applied.task_id
    assert replay.revision == applied.revision
    assert replay.result_refs == applied.result_refs

    no_change_command = new_uuid4()
    no_change = _reassign(
        factory,
        command_id=no_change_command,
        task_id=registered.task_id,
        task_revision=2,
        assignment_revision=2,
        current_rfc_id=new_rfc,
        new_rfc_id=new_rfc,
        reason_category="confirm_parent",
    )
    assert no_change.no_change
    assert no_change.revision == 2
    assert no_change.result_refs == ()
    with ReadSnapshot(factory) as snapshot:
        assert snapshot.connection.execute(
            "SELECT count(*) FROM wfm_rfc_assignment_events WHERE task_id=?",
            (registered.task_id,),
        ).fetchone()[0] == 2
        assert snapshot.connection.execute(
            "SELECT count(*) FROM audit_events WHERE command_id=?",
            (no_change_command,),
        ).fetchone()[0] == 0
        assert snapshot.connection.execute(
            "SELECT result_type,result_id FROM command_receipts WHERE command_id=?",
            (no_change_command,),
        ).fetchone() == ("NO_CHANGE", None)


def test_reassign_wfm_parent_rejects_stale_task_and_assignment_before_receipt(initialized_database) -> None:
    factory = _factory(initialized_database)
    old_rfc = _create_rfc(factory, "NC00000000000105")
    new_rfc = _create_rfc(factory, "NC00000000000106")
    _, registered = _register(factory, rfc_id=old_rfc, task_no="TK00000000000103")
    bases = _freshness(factory, current_rfc_id=old_rfc, new_rfc_id=new_rfc)

    stale_task_command = new_uuid4()
    with pytest.raises(SomaError) as stale_task:
        _reassign(
            factory,
            command_id=stale_task_command,
            task_id=registered.task_id,
            task_revision=2,
            assignment_revision=1,
            current_rfc_id=old_rfc,
            new_rfc_id=new_rfc,
            freshness=bases,
        )
    assert stale_task.value.code == "TASK_STALE"
    assert not _receipt_exists(factory, stale_task_command)

    stale_assignment_command = new_uuid4()
    with pytest.raises(SomaError) as stale_assignment:
        _reassign(
            factory,
            command_id=stale_assignment_command,
            task_id=registered.task_id,
            task_revision=1,
            assignment_revision=2,
            current_rfc_id=old_rfc,
            new_rfc_id=new_rfc,
            freshness=bases,
        )
    assert stale_assignment.value.code == "WFM_PARENT_STALE"
    assert not _receipt_exists(factory, stale_assignment_command)


@pytest.mark.parametrize(
    ("side", "authority_kind"),
    (
        ("current", "rfc_revision"),
        ("current", "source_revision"),
        ("candidate", "rfc_revision"),
        ("candidate", "source_revision"),
    ),
)
def test_reassign_wfm_parent_binds_both_rfc_freshness_authorities(
    initialized_database, side: str, authority_kind: str
) -> None:
    factory = _factory(initialized_database)
    suffix = {
        ("current", "rfc_revision"): ("18", "19", "11"),
        ("current", "source_revision"): ("20", "21", "12"),
        ("candidate", "rfc_revision"): ("22", "23", "13"),
        ("candidate", "source_revision"): ("24", "25", "14"),
    }[(side, authority_kind)]
    old_rfc = _create_rfc(factory, f"NC000000000001{suffix[0]}")
    new_rfc = _create_rfc(factory, f"NC000000000001{suffix[1]}")
    _, registered = _register(factory, rfc_id=old_rfc, task_no=f"TK000000000001{suffix[2]}")
    captured = _freshness(factory, current_rfc_id=old_rfc, new_rfc_id=new_rfc)
    changed_rfc = old_rfc if side == "current" else new_rfc

    with UnitOfWork(factory) as uow:
        if authority_kind == "rfc_revision":
            uow.connection.execute("UPDATE rfcs SET revision=revision+1 WHERE rfc_id=?", (changed_rfc,))
        else:
            uow.connection.execute(
                "INSERT INTO rfc_current_source_projection(rfc_id,revision) VALUES (?,1)",
                (changed_rfc,),
            )

    command_id = new_uuid4()
    with pytest.raises(SomaError) as stale:
        _reassign(
            factory,
            command_id=command_id,
            task_id=registered.task_id,
            task_revision=1,
            assignment_revision=1,
            current_rfc_id=old_rfc,
            new_rfc_id=new_rfc,
            freshness=captured,
        )
    assert stale.value.code == "WFM_PARENT_STALE"
    assert not _receipt_exists(factory, command_id)
    with ReadSnapshot(factory) as snapshot:
        assert snapshot.connection.execute(
            "SELECT current_rfc_id,assignment_revision FROM wfm_task_identities WHERE task_id=?",
            (registered.task_id,),
        ).fetchone() == (old_rfc, 1)
        assert snapshot.connection.execute(
            "SELECT revision FROM tasks WHERE task_id=?", (registered.task_id,)
        ).fetchone() == (1,)


def test_reassign_wfm_parent_exact_but_archived_candidate_is_not_eligible(initialized_database) -> None:
    factory = _factory(initialized_database)
    old_rfc = _create_rfc(factory, "NC00000000000126")
    new_rfc = _create_rfc(factory, "NC00000000000127")
    _, registered = _register(factory, rfc_id=old_rfc, task_no="TK00000000000115")
    with UnitOfWork(factory) as uow:
        uow.connection.execute(
            "UPDATE rfcs SET local_archive_state='archived',revision=revision+1 WHERE rfc_id=?",
            (new_rfc,),
        )
    fresh = _freshness(factory, current_rfc_id=old_rfc, new_rfc_id=new_rfc)
    command_id = new_uuid4()
    with pytest.raises(SomaError) as blocked:
        _reassign(
            factory,
            command_id=command_id,
            task_id=registered.task_id,
            task_revision=1,
            assignment_revision=1,
            current_rfc_id=old_rfc,
            new_rfc_id=new_rfc,
            freshness=fresh,
        )
    assert blocked.value.code == "WFM_RFC_NOT_ELIGIBLE"
    assert not _receipt_exists(factory, command_id)


def test_reassign_wfm_parent_high_risk_plan_requires_explicit_acceptance(initialized_database) -> None:
    factory = _factory(initialized_database)
    old_rfc = _create_rfc(factory, "NC00000000000107")
    new_rfc = _create_rfc(factory, "NC00000000000108")
    schedule = AcceptedTaskSchedule(
        start_utc=1_800_010_000,
        end_utc=1_800_013_600,
        scheduling_timezone_iana="America/Guayaquil",
    )
    _, registered = _register(
        factory,
        rfc_id=old_rfc,
        task_no="TK00000000000104",
        schedule=schedule,
    )
    bases = _freshness(factory, current_rfc_id=old_rfc, new_rfc_id=new_rfc)

    denied_command = new_uuid4()
    with pytest.raises(SomaError) as denied:
        _reassign(
            factory,
            command_id=denied_command,
            task_id=registered.task_id,
            task_revision=1,
            assignment_revision=1,
            current_rfc_id=old_rfc,
            new_rfc_id=new_rfc,
            reason_category="reviewed_move",
            freshness=bases,
        )
    assert denied.value.code == "WFM_PARENT_REVIEW_REQUIRED"
    assert not _receipt_exists(factory, denied_command)

    accepted = _reassign(
        factory,
        task_id=registered.task_id,
        task_revision=1,
        assignment_revision=1,
        current_rfc_id=old_rfc,
        new_rfc_id=new_rfc,
        reason_category="reviewed_move",
        accept_high_risk=True,
        freshness=bases,
    )
    assert accepted.revision == 2
    with ReadSnapshot(factory) as snapshot:
        event_id = accepted.result_refs[0].result_id
        event = snapshot.connection.execute(
            "SELECT review_risk,prior_rfc_id,new_rfc_id FROM wfm_rfc_assignment_events WHERE assignment_event_id=?",
            (event_id,),
        ).fetchone()
        assert tuple(event) == ("high", old_rfc, new_rfc)
        assert snapshot.connection.execute(
            "SELECT count(*) FROM task_plan_revisions WHERE task_id=?",
            (registered.task_id,),
        ).fetchone()[0] == 1


def test_reassign_wfm_parent_source_projection_is_high_risk(initialized_database) -> None:
    factory = _factory(initialized_database)
    old_rfc = _create_rfc(factory, "NC00000000000109")
    new_rfc = _create_rfc(factory, "NC00000000000110")
    registration_command, registered = _register(factory, rfc_id=old_rfc, task_no="TK00000000000105")
    with UnitOfWork(factory) as uow:
        uow.connection.execute(
            "INSERT INTO wfm_source_projection_cache(task_id,provider_status_token,provider_lifecycle_class,"
            "source_plan_start_utc,source_plan_end_utc,accepted_source_observation_id,source_projection_revision,"
            "source_base_token,last_command_id) VALUES (?,NULL,'active',NULL,NULL,NULL,1,?,?)",
            (registered.task_id, "a" * 64, registration_command),
        )

    command_id = new_uuid4()
    with pytest.raises(SomaError) as denied:
        _reassign(
            factory,
            command_id=command_id,
            task_id=registered.task_id,
            task_revision=1,
            assignment_revision=1,
            current_rfc_id=old_rfc,
            new_rfc_id=new_rfc,
            reason_category="source_conflict_review",
        )
    assert denied.value.code == "WFM_PARENT_REVIEW_REQUIRED"
    assert not _receipt_exists(factory, command_id)


def test_reassign_wfm_parent_rejects_missing_candidate_and_local_task(initialized_database) -> None:
    factory = _factory(initialized_database)
    old_rfc = _create_rfc(factory, "NC00000000000111")
    _, registered = _register(factory, rfc_id=old_rfc, task_no="TK00000000000106")
    service = TaskPlanningService(factory)
    current_revision, current_source_revision = _rfc_authority(factory, old_rfc)

    missing_command = new_uuid4()
    with pytest.raises(SomaError) as missing:
        service.reassign_wfm_parent(
            command_id=missing_command,
            task_id=registered.task_id,
            task_revision=1,
            assignment_revision=1,
            current_rfc_revision=current_revision,
            current_rfc_source_projection_revision=current_source_revision,
            new_rfc_id=new_uuid4(),
            new_rfc_revision=1,
            new_rfc_source_projection_revision=0,
            reason_category="manual_correction",
            accept_high_risk=False,
        )
    assert missing.value.code == "WFM_RFC_NOT_ELIGIBLE"
    assert not _receipt_exists(factory, missing_command)

    local = service.create_local_task(command_id=new_uuid4(), local_task_name="Local only")
    local_command = new_uuid4()
    with pytest.raises(SomaError) as local_error:
        service.reassign_wfm_parent(
            command_id=local_command,
            task_id=local.task_id,
            task_revision=1,
            assignment_revision=1,
            current_rfc_revision=current_revision,
            current_rfc_source_projection_revision=current_source_revision,
            new_rfc_id=old_rfc,
            new_rfc_revision=current_revision,
            new_rfc_source_projection_revision=current_source_revision,
            reason_category="manual_correction",
            accept_high_risk=False,
        )
    assert local_error.value.code == "TASK_NOT_FOUND"
    assert not _receipt_exists(factory, local_command)


def test_reassign_wfm_parent_preflight_is_strict_and_writes_nothing(initialized_database) -> None:
    factory = _factory(initialized_database)
    old_rfc = _create_rfc(factory, "NC00000000000112")
    new_rfc = _create_rfc(factory, "NC00000000000113")
    _, registered = _register(factory, rfc_id=old_rfc, task_no="TK00000000000107")
    valid = {
        "task_revision": 1,
        "assignment_revision": 1,
        "reason_category": "x",
        "accept_high_risk": False,
        **_freshness(factory, current_rfc_id=old_rfc, new_rfc_id=new_rfc),
    }
    cases = (
        {"task_revision": True},
        {"assignment_revision": 0},
        {"current_rfc_revision": 0},
        {"current_rfc_source_projection_revision": -1},
        {"new_rfc_revision": True},
        {"new_rfc_source_projection_revision": -1},
        {"reason_category": ""},
        {"reason_category": "x\nunsafe"},
        {"accept_high_risk": 1},
    )
    for override in cases:
        command_id = new_uuid4()
        with pytest.raises(ValidationError):
            TaskPlanningService(factory).reassign_wfm_parent(
                command_id=command_id,
                task_id=registered.task_id,
                new_rfc_id=new_rfc,
                **(valid | override),
            )
        assert not _receipt_exists(factory, command_id)


def test_reassign_wfm_parent_rolls_back_identity_revision_event_and_receipt_on_audit_failure(
    initialized_database, monkeypatch
) -> None:
    factory = _factory(initialized_database)
    old_rfc = _create_rfc(factory, "NC00000000000114")
    new_rfc = _create_rfc(factory, "NC00000000000115")
    _, registered = _register(factory, rfc_id=old_rfc, task_no="TK00000000000108")
    service = TaskPlanningService(factory)
    command_id = new_uuid4()
    bases = _freshness(factory, current_rfc_id=old_rfc, new_rfc_id=new_rfc)

    def fail_audit(*_args, **_kwargs):
        raise SomaError("AUDIT_PERSISTENCE_FAILURE", "injected reassignment audit failure")

    monkeypatch.setattr(service._boundary._audit_writer, "write", fail_audit)
    with pytest.raises(SomaError) as failure:
        service.reassign_wfm_parent(
            command_id=command_id,
            task_id=registered.task_id,
            task_revision=1,
            assignment_revision=1,
            new_rfc_id=new_rfc,
            reason_category="manual_correction",
            accept_high_risk=False,
            **bases,
        )
    assert failure.value.code == "AUDIT_PERSISTENCE_FAILURE"

    with ReadSnapshot(factory) as snapshot:
        assert snapshot.connection.execute(
            "SELECT revision FROM tasks WHERE task_id=?", (registered.task_id,)
        ).fetchone() == (1,)
        assert snapshot.connection.execute(
            "SELECT current_rfc_id,assignment_revision FROM wfm_task_identities WHERE task_id=?",
            (registered.task_id,),
        ).fetchone() == (old_rfc, 1)
        assert snapshot.connection.execute(
            "SELECT count(*) FROM wfm_rfc_assignment_events WHERE task_id=?",
            (registered.task_id,),
        ).fetchone()[0] == 1
        assert snapshot.connection.execute(
            "SELECT 1 FROM command_receipts WHERE command_id=?", (command_id,)
        ).fetchone() is None


def test_reassign_wfm_parent_fails_closed_on_cross_task_current_plan_corruption(initialized_database) -> None:
    factory = _factory(initialized_database)
    old_rfc = _create_rfc(factory, "NC00000000000116")
    new_rfc = _create_rfc(factory, "NC00000000000117")
    schedule_a = AcceptedTaskSchedule(1_810_000_000, 1_810_003_600, "America/Guayaquil")
    schedule_b = AcceptedTaskSchedule(1_820_000_000, 1_820_003_600, "America/Guayaquil")
    _, target = _register(factory, rfc_id=old_rfc, task_no="TK00000000000109", schedule=schedule_a)
    _, donor = _register(factory, rfc_id=old_rfc, task_no="TK00000000000110", schedule=schedule_b)

    # Simulate out-of-band/legacy corruption beyond the normal DB backstops, then restore the exact guards.
    with UnitOfWork(factory) as uow:
        donor_plan = str(
            uow.connection.execute(
                "SELECT plan_revision_id FROM task_plan_current WHERE task_id=?", (donor.task_id,)
            ).fetchone()[0]
        )
        uow.connection.execute("DROP TRIGGER task_plan_current_delete_guard")
        uow.connection.execute("DROP TRIGGER task_plan_current_update_guard")
        uow.connection.execute("DELETE FROM task_plan_current WHERE task_id=?", (donor.task_id,))
        uow.connection.execute(
            "UPDATE task_plan_current SET plan_revision_id=?,revision=revision+1 WHERE task_id=?",
            (donor_plan, target.task_id),
        )
        uow.connection.execute(
            "CREATE TRIGGER task_plan_current_update_guard BEFORE UPDATE ON task_plan_current BEGIN "
            "SELECT CASE WHEN NEW.task_id<>OLD.task_id OR NEW.revision<>OLD.revision+1 "
            "OR NEW.plan_revision_id=OLD.plan_revision_id OR NOT EXISTS "
            "(SELECT 1 FROM task_plan_revisions WHERE plan_revision_id=NEW.plan_revision_id AND task_id=NEW.task_id) "
            "THEN RAISE(ABORT,'TASK_PLAN_CURRENT_INVALID') END; END"
        )
        uow.connection.execute(
            "CREATE TRIGGER task_plan_current_delete_guard BEFORE DELETE ON task_plan_current BEGIN "
            "SELECT CASE WHEN NOT EXISTS (SELECT 1 FROM command_receipts WHERE command_type='HardDeleteTask' "
            "AND target_type='task' AND target_id=OLD.task_id) THEN RAISE(ABORT,'TASK_PLAN_CURRENT_PROTECTED') END; END"
        )

    command_id = new_uuid4()
    with pytest.raises(SomaError) as stale:
        _reassign(
            factory,
            command_id=command_id,
            task_id=target.task_id,
            task_revision=1,
            assignment_revision=1,
            current_rfc_id=old_rfc,
            new_rfc_id=new_rfc,
            reason_category="corrupt_projection_review",
            accept_high_risk=True,
        )
    assert stale.value.code == "WFM_PARENT_STALE"
    assert not _receipt_exists(factory, command_id)
