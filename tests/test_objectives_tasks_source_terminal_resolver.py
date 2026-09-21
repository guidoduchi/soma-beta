from __future__ import annotations

import json

import pytest

from soma.foundation.errors import SomaError
from soma.foundation.identifiers import new_uuid4
from soma.foundation.persistence.uow import ReadSnapshot, UnitOfWork
from soma.objectives_tasks import AcceptedTaskSchedule, TaskPlanningService
from soma.objectives_tasks.services.source_terminal import WfmSourceTerminalService
from soma.objectives_tasks.services.task_execution import TaskExecutionService
from soma.objectives_tasks.services.task_explicit_lock import TaskExplicitLockService
from soma.objectives_tasks.source_terminal_authority import (
    WfmSourceProjectionMutation,
    WfmSourceProjectionParticipant,
)
from soma.tickets.rfcs import RfcService

TZ = "America/Guayaquil"


def _factory(initialized_database):
    database_path, factory_for_path = initialized_database
    return factory_for_path(database_path)


def _create_rfc(factory, suffix: int) -> str:
    return RfcService(factory).create_or_adopt_identity(
        command_id=new_uuid4(),
        rfc_no=f"NC{suffix:014d}",
        creation_context="provisional",
    ).rfc_id


def _register_wfm(factory, *, suffix: int):
    return TaskPlanningService(factory).register_manual_wfm_task(
        command_id=new_uuid4(),
        task_no=f"TK{suffix:014d}",
        rfc_id=_create_rfc(factory, suffix),
        schedule=AcceptedTaskSchedule(
            start_utc=2_040_000_000 + suffix * 10_000,
            end_utc=2_040_003_600 + suffix * 10_000,
            scheduling_timezone_iana=TZ,
        ),
    )


def _insert_outer_receipt(uow: UnitOfWork, *, command_id: str) -> None:
    uow.connection.execute(
        "INSERT INTO command_receipts(command_id,command_type,request_hash,target_type,target_id,"
        "committed_at_utc,result_type,result_id) "
        "VALUES (?,'AcceptReconciliationProposal',?,'reconciliation_proposal',?,0,NULL,NULL)",
        (command_id, "a" * 64, new_uuid4()),
    )


def _apply_terminal_source(factory, *, task_id: str, expected_revision: int = 0, lifecycle: str = "complete"):
    command_id = new_uuid4()
    observation_id = new_uuid4()
    with UnitOfWork(factory) as uow:
        _insert_outer_receipt(uow, command_id=command_id)
        result = WfmSourceProjectionParticipant.apply_wfm_source_projection(
            uow,
            WfmSourceProjectionMutation(
                task_id=task_id,
                expected_source_projection_revision=expected_revision,
                provider_status_token="Complete" if lifecycle == "complete" else "Plan Cancel",
                provider_lifecycle_class=lifecycle,
                source_plan_start_utc=2_040_100_000,
                source_plan_end_utc=2_040_103_600,
                accepted_source_observation_id=observation_id,
                source_base_token=("b" if expected_revision == 0 else "c") * 64,
            ),
            command_id=command_id,
        )
    assert result.source_terminal_review_id is not None
    assert result.source_terminal_review_fingerprint is not None
    return result, observation_id


def _resolve(service, *, command_id: str, task_id: str, source_result, decision: str):
    return service.resolve_wfm_source_terminal_consequence(
        command_id=command_id,
        source_terminal_review_id=source_result.source_terminal_review_id,
        task_id=task_id,
        source_projection_revision=source_result.source_projection_revision,
        input_fingerprint=source_result.source_terminal_review_fingerprint,
        decision=decision,
        reason_category="provider_terminal_review",
    )


def _seed_single_objective(factory, task_id: str) -> str:
    objective_id = new_uuid4()
    tracking_sequence = 96_000_000 + int(objective_id[-5:], 16) % 3_000_000
    with UnitOfWork(factory) as uow:
        task = uow.connection.execute(
            "SELECT created_command_id FROM tasks WHERE task_id=?",
            (task_id,),
        ).fetchone()
        plan = uow.connection.execute(
            "SELECT c.plan_revision_id,p.start_utc,p.end_utc FROM task_plan_current c "
            "JOIN task_plan_revisions p ON p.plan_revision_id=c.plan_revision_id WHERE c.task_id=?",
            (task_id,),
        ).fetchone()
        assert task is not None and plan is not None
        command_id = str(task[0])
        plan_id, start_utc, end_utc = str(plan[0]), int(plan[1]), int(plan[2])
        membership_event_id = new_uuid4()
        uow.connection.execute(
            "INSERT INTO objectives(objective_id,tracking_sequence,tracking_id,creation_origin,"
            "superseded_by_objective_id,revision,created_at_utc,created_command_id) "
            "VALUES (?,?,?,'manual',NULL,1,1,?)",
            (objective_id, tracking_sequence, f"MW-{tracking_sequence:08d}", command_id),
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
            (objective_id, start_utc, end_utc, 1, "d" * 64, command_id),
        )
        uow.connection.execute(
            "INSERT INTO objective_aggregate_projection(objective_id,execution_state,aggregate_outcome,"
            "actual_start_utc,actual_end_utc,attention_reason,included_task_count,excluded_task_count,"
            "aggregate_input_fingerprint,revision,last_command_id) "
            "VALUES (?,'planned',NULL,NULL,NULL,NULL,1,0,?,1,?)",
            (objective_id, "e" * 64, command_id),
        )
    return objective_id


def test_retain_local_work_changes_only_review_and_exact_replay_survives_later_source_drift(initialized_database) -> None:
    factory = _factory(initialized_database)
    task = _register_wfm(factory, suffix=201)
    source, _ = _apply_terminal_source(factory, task_id=task.task_id)
    service = WfmSourceTerminalService(factory)
    command_id = new_uuid4()

    applied = _resolve(
        service,
        command_id=command_id,
        task_id=task.task_id,
        source_result=source,
        decision="retain_local_work",
    )
    assert applied.outcome == "APPLIED"
    assert applied.revision == task.revision
    assert not applied.replayed
    assert {(ref.result_type, ref.result_id) for ref in applied.result_refs} == {
        ("wfm_source_terminal_review", source.source_terminal_review_id)
    }

    with ReadSnapshot(factory) as snapshot:
        review = snapshot.connection.execute(
            "SELECT state,revision,local_consequence_event_id,decided_at_utc,last_command_id "
            "FROM wfm_source_terminal_reviews WHERE source_terminal_review_id=?",
            (source.source_terminal_review_id,),
        ).fetchone()
        assert review[0] == "retain_local_work"
        assert review[1] == 2
        assert review[2] is None
        assert type(review[3]) is int
        assert review[4] == command_id
        assert snapshot.connection.execute(
            "SELECT revision FROM tasks WHERE task_id=?", (task.task_id,)
        ).fetchone()[0] == task.revision
        assert snapshot.connection.execute(
            "SELECT count(*) FROM task_execution_events WHERE task_id=?", (task.task_id,)
        ).fetchone()[0] == 0
        audit = snapshot.connection.execute(
            "SELECT payload_json FROM audit_events WHERE command_id=? AND action_type='task.source_terminal_consequence_resolved'",
            (command_id,),
        ).fetchone()
        assert audit is not None
        payload = json.loads(str(audit[0]))
        assert payload["accepted_local_consequence"] == "retain_local_work"
        assert payload["execution_event_id"] is None

    _apply_terminal_source(factory, task_id=task.task_id, expected_revision=1, lifecycle="plan_cancel")
    replayed = _resolve(
        service,
        command_id=command_id,
        task_id=task.task_id,
        source_result=source,
        decision="retain_local_work",
    )
    assert replayed.replayed
    assert replayed.revision == applied.revision
    assert replayed.result_refs == applied.result_refs


def test_terminate_local_work_appends_governed_event_preserves_start_and_rebuilds_objective(initialized_database) -> None:
    factory = _factory(initialized_database)
    task = _register_wfm(factory, suffix=202)
    objective_id = _seed_single_objective(factory, task.task_id)
    accepted_start = 2_040_250_000
    started = TaskExecutionService(factory).start_task_execution(
        command_id=new_uuid4(),
        task_id=task.task_id,
        task_revision=task.revision,
        execution_revision=0,
        effective_start_utc=accepted_start,
    )
    assert started.revision == task.revision + 1
    source, observation_id = _apply_terminal_source(factory, task_id=task.task_id)
    command_id = new_uuid4()

    result = _resolve(
        WfmSourceTerminalService(factory),
        command_id=command_id,
        task_id=task.task_id,
        source_result=source,
        decision="terminate_local_work",
    )
    assert result.revision == started.revision + 1
    refs = {(ref.result_type, ref.result_id) for ref in result.result_refs}
    event_ids = [identity for kind, identity in refs if kind == "task_execution_event"]
    assert len(event_ids) == 1
    event_id = event_ids[0]

    with ReadSnapshot(factory) as snapshot:
        event = snapshot.connection.execute(
            "SELECT execution_revision,event_kind,effective_at_utc,target_event_id,correction_action,reason_code,command_id "
            "FROM task_execution_events WHERE execution_event_id=?",
            (event_id,),
        ).fetchone()
        assert tuple(event) == (
            2,
            "source_terminal_consequence",
            None,
            None,
            None,
            "provider_terminal_review",
            command_id,
        )
        projection = snapshot.connection.execute(
            "SELECT execution_state,actual_start_utc,actual_end_utc,effective_termination_utc,termination_reason,revision,last_event_id "
            "FROM task_execution_projection WHERE task_id=?",
            (task.task_id,),
        ).fetchone()
        assert tuple(projection) == (
            "terminated",
            accepted_start,
            None,
            None,
            "provider_terminal_review",
            2,
            event_id,
        )
        assert snapshot.connection.execute(
            "SELECT count(*) FROM task_outcome_events WHERE task_id=?", (task.task_id,)
        ).fetchone()[0] == 0
        review = snapshot.connection.execute(
            "SELECT state,local_consequence_event_id,revision,last_command_id FROM wfm_source_terminal_reviews "
            "WHERE source_terminal_review_id=?",
            (source.source_terminal_review_id,),
        ).fetchone()
        assert tuple(review) == ("terminate_local_work", event_id, 2, command_id)
        aggregate = snapshot.connection.execute(
            "SELECT execution_state,attention_reason,actual_start_utc,aggregate_outcome,revision,last_command_id "
            "FROM objective_aggregate_projection WHERE objective_id=?",
            (objective_id,),
        ).fetchone()
        assert aggregate[0] == "awaiting_review"
        assert aggregate[1] == "lost_last_executable"
        assert aggregate[2] == accepted_start
        assert aggregate[3] is None
        assert aggregate[4] >= 3
        assert aggregate[5] == command_id
        audit = snapshot.connection.execute(
            "SELECT payload_json FROM audit_events WHERE command_id=? AND action_type='task.source_terminal_consequence_resolved'",
            (command_id,),
        ).fetchone()
        payload = json.loads(str(audit[0]))
        assert payload["source_evidence_id"] == observation_id
        assert payload["review_fingerprint"] == source.source_terminal_review_fingerprint
        assert payload["accepted_local_consequence"] == "terminate_local_work"
        assert payload["execution_event_id"] == event_id


def test_local_authority_drift_stales_review_before_receipt(initialized_database) -> None:
    factory = _factory(initialized_database)
    task = _register_wfm(factory, suffix=203)
    source, _ = _apply_terminal_source(factory, task_id=task.task_id)
    TaskExplicitLockService(factory).set_explicit_task_lock(
        command_id=new_uuid4(),
        task_id=task.task_id,
        task_revision=task.revision,
        lock_projection_revision=0,
        lock_kind="plan",
        action="lock",
        reason_category="operator_lock",
    )
    command_id = new_uuid4()

    with pytest.raises(SomaError) as stale:
        _resolve(
            WfmSourceTerminalService(factory),
            command_id=command_id,
            task_id=task.task_id,
            source_result=source,
            decision="terminate_local_work",
        )
    assert stale.value.code == "WFM_SOURCE_TERMINAL_STALE"
    with ReadSnapshot(factory) as snapshot:
        assert snapshot.connection.execute(
            "SELECT 1 FROM command_receipts WHERE command_id=?", (command_id,)
        ).fetchone() is None
        review = snapshot.connection.execute(
            "SELECT state,revision FROM wfm_source_terminal_reviews WHERE source_terminal_review_id=?",
            (source.source_terminal_review_id,),
        ).fetchone()
        assert tuple(review) == ("pending", 1)
        assert snapshot.connection.execute(
            "SELECT count(*) FROM task_execution_events WHERE task_id=?", (task.task_id,)
        ).fetchone()[0] == 0


def test_different_review_or_request_fingerprint_fails_before_receipt(initialized_database) -> None:
    factory = _factory(initialized_database)
    task = _register_wfm(factory, suffix=204)
    source, _ = _apply_terminal_source(factory, task_id=task.task_id)
    service = WfmSourceTerminalService(factory)

    command_id = new_uuid4()
    with pytest.raises(SomaError) as stale:
        service.resolve_wfm_source_terminal_consequence(
            command_id=command_id,
            source_terminal_review_id=new_uuid4(),
            task_id=task.task_id,
            source_projection_revision=source.source_projection_revision,
            input_fingerprint=source.source_terminal_review_fingerprint,
            decision="retain_local_work",
            reason_category="provider_terminal_review",
        )
    assert stale.value.code == "WFM_SOURCE_TERMINAL_STALE"

    fingerprint_command = new_uuid4()
    with pytest.raises(SomaError) as fingerprint_stale:
        service.resolve_wfm_source_terminal_consequence(
            command_id=fingerprint_command,
            source_terminal_review_id=source.source_terminal_review_id,
            task_id=task.task_id,
            source_projection_revision=source.source_projection_revision,
            input_fingerprint="0" * 64,
            decision="retain_local_work",
            reason_category="provider_terminal_review",
        )
    assert fingerprint_stale.value.code == "WFM_SOURCE_TERMINAL_STALE"
    with ReadSnapshot(factory) as snapshot:
        for candidate in (command_id, fingerprint_command):
            assert snapshot.connection.execute(
                "SELECT 1 FROM command_receipts WHERE command_id=?", (candidate,)
            ).fetchone() is None


def test_audit_failure_rolls_back_receipt_review_execution_and_task_revision(initialized_database, monkeypatch) -> None:
    factory = _factory(initialized_database)
    task = _register_wfm(factory, suffix=205)
    source, _ = _apply_terminal_source(factory, task_id=task.task_id)
    service = WfmSourceTerminalService(factory)
    command_id = new_uuid4()

    def fail_audit(*_args, **_kwargs):
        raise RuntimeError("injected source-terminal audit failure")

    monkeypatch.setattr(service._boundary._audit_writer, "write", fail_audit)
    with pytest.raises(RuntimeError, match="injected source-terminal audit failure"):
        _resolve(
            service,
            command_id=command_id,
            task_id=task.task_id,
            source_result=source,
            decision="terminate_local_work",
        )

    with ReadSnapshot(factory) as snapshot:
        assert snapshot.connection.execute(
            "SELECT 1 FROM command_receipts WHERE command_id=?", (command_id,)
        ).fetchone() is None
        assert snapshot.connection.execute(
            "SELECT 1 FROM command_receipt_results WHERE command_id=?", (command_id,)
        ).fetchone() is None
        assert snapshot.connection.execute(
            "SELECT count(*) FROM audit_events WHERE command_id=?", (command_id,)
        ).fetchone()[0] == 0
        assert snapshot.connection.execute(
            "SELECT count(*) FROM task_execution_events WHERE command_id=?", (command_id,)
        ).fetchone()[0] == 0
        assert snapshot.connection.execute(
            "SELECT revision FROM tasks WHERE task_id=?", (task.task_id,)
        ).fetchone()[0] == task.revision
        assert snapshot.connection.execute(
            "SELECT 1 FROM task_execution_projection WHERE task_id=?", (task.task_id,)
        ).fetchone() is None
        review = snapshot.connection.execute(
            "SELECT state,revision,local_consequence_event_id,decided_at_utc,last_command_id "
            "FROM wfm_source_terminal_reviews WHERE source_terminal_review_id=?",
            (source.source_terminal_review_id,),
        ).fetchone()
        assert tuple(review[:4]) == ("pending", 1, None, None)
        assert review[4] is not None
