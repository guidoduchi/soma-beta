from __future__ import annotations

import json

import pytest

from soma.foundation.errors import SomaError, ValidationError
from soma.foundation.identifiers import new_uuid4
from soma.foundation.persistence.uow import ReadSnapshot, UnitOfWork
from soma.objectives_tasks import AcceptedTaskSchedule, TaskPlanningService
from soma.tickets.rfcs import RfcService


TZ = "America/Guayaquil"


def _factory(initialized_database):
    database_path, factory_for_path = initialized_database
    return factory_for_path(database_path)


def _schedule(start: int, end: int) -> AcceptedTaskSchedule:
    return AcceptedTaskSchedule(start_utc=start, end_utc=end, scheduling_timezone_iana=TZ)


def _create_local(factory, *, name: str = "Plan target", schedule: AcceptedTaskSchedule | None = None):
    command_id = new_uuid4()
    result = TaskPlanningService(factory).create_local_task(
        command_id=command_id,
        local_task_name=name,
        schedule=schedule,
    )
    return command_id, result


def _receipt_exists(factory, command_id: str) -> bool:
    with ReadSnapshot(factory) as snapshot:
        return snapshot.connection.execute(
            "SELECT 1 FROM command_receipts WHERE command_id=?",
            (command_id,),
        ).fetchone() is not None


def _current_plan(factory, task_id: str):
    with ReadSnapshot(factory) as snapshot:
        row = snapshot.connection.execute(
            "SELECT c.plan_revision_id,c.revision,p.start_utc,p.end_utc,p.origin,p.scheduling_timezone_iana,"
            "p.source_observation_id,p.predecessor_plan_revision_id,p.reason_code,p.command_id "
            "FROM task_plan_current c JOIN task_plan_revisions p ON p.plan_revision_id=c.plan_revision_id "
            "WHERE c.task_id=? AND p.task_id=c.task_id",
            (task_id,),
        ).fetchone()
    return row


def _attach_planned_objective(
    factory,
    *,
    task_id: str,
    creation_command_id: str,
    attention_reason: str | None = None,
    creation_origin: str = "manual",
    execution_state: str = "planned",
    include_aggregate: bool = True,
) -> tuple[str, str]:
    with UnitOfWork(factory) as uow:
        plan_id = str(
            uow.connection.execute(
                "SELECT plan_revision_id FROM task_plan_current WHERE task_id=?",
                (task_id,),
            ).fetchone()[0]
        )
        plan = uow.connection.execute(
            "SELECT start_utc,end_utc FROM task_plan_revisions WHERE plan_revision_id=?",
            (plan_id,),
        ).fetchone()
        objective_id = new_uuid4()
        event_id = new_uuid4()
        uow.connection.execute(
            "INSERT INTO objectives(objective_id,tracking_sequence,tracking_id,creation_origin,"
            "superseded_by_objective_id,revision,created_at_utc,created_command_id) "
            "VALUES (?,?,?, ?,NULL,1,1,?)",
            (objective_id, 90_000_001, "MW-90000001", creation_origin, creation_command_id),
        )
        uow.connection.execute(
            "INSERT INTO objective_membership_events(membership_event_id,task_id,event_kind,from_objective_id,"
            "to_objective_id,accepted_plan_revision_id,grouping_proposal_id,reason_code,recorded_at_utc,command_id) "
            "VALUES (?,?,'add',NULL,?,?,NULL,NULL,1,?)",
            (event_id, task_id, objective_id, plan_id, creation_command_id),
        )
        uow.connection.execute(
            "INSERT INTO objective_task_membership_current(task_id,objective_id,accepted_plan_revision_id,"
            "membership_revision,last_event_id,last_command_id) VALUES (?,?,?,1,?,?)",
            (task_id, objective_id, plan_id, event_id, creation_command_id),
        )
        uow.connection.execute(
            "INSERT INTO objective_envelope_projection(objective_id,start_utc,end_utc,member_count,"
            "membership_input_fingerprint,revision,last_command_id) VALUES (?,?,?,?,?,1,?)",
            (objective_id, int(plan[0]), int(plan[1]), 1, "a" * 64, creation_command_id),
        )
        if include_aggregate:
            aggregate_outcome = "completed" if execution_state == "reviewed" else None
            uow.connection.execute(
                "INSERT INTO objective_aggregate_projection(objective_id,execution_state,aggregate_outcome,"
                "actual_start_utc,actual_end_utc,attention_reason,included_task_count,excluded_task_count,"
                "aggregate_input_fingerprint,revision,last_command_id) "
                "VALUES (?,?,?,NULL,NULL,?,1,0,?,1,?)",
                (
                    objective_id,
                    execution_state,
                    aggregate_outcome,
                    attention_reason,
                    "b" * 64,
                    creation_command_id,
                ),
            )
    return objective_id, plan_id


def _create_wfm(factory, *, task_no: str):
    rfc_id = RfcService(factory).create_or_adopt_identity(
        command_id=new_uuid4(),
        rfc_no="NC00000000009001",
        creation_context="provisional",
    ).rfc_id
    command_id = new_uuid4()
    result = TaskPlanningService(factory).register_manual_wfm_task(
        command_id=command_id,
        task_no=task_no,
        rfc_id=rfc_id,
    )
    return command_id, result


def _seed_terminal_wfm_source(factory, *, task_id: str, command_id: str) -> None:
    with UnitOfWork(factory) as uow:
        uow.connection.execute(
            "INSERT INTO wfm_source_projection_cache(task_id,provider_status_token,provider_lifecycle_class,"
            "source_plan_start_utc,source_plan_end_utc,accepted_source_observation_id,source_projection_revision,"
            "source_base_token,last_command_id) VALUES (?,'Complete','complete',NULL,NULL,NULL,1,?,?)",
            (task_id, "c" * 64, command_id),
        )


def _seed_retain_review(factory, *, task_id: str, command_id: str, created_at: int = 1) -> str:
    review_id = new_uuid4()
    with UnitOfWork(factory) as uow:
        uow.connection.execute(
            "INSERT INTO wfm_source_terminal_reviews(source_terminal_review_id,task_id,source_projection_revision,"
            "provider_lifecycle_class,input_fingerprint,state,local_consequence_event_id,revision,created_at_utc,"
            "decided_at_utc,last_command_id) VALUES (?,?,1,'complete',?,'pending',NULL,1,?,NULL,NULL)",
            (review_id, task_id, "d" * 64, created_at),
        )
        uow.connection.execute(
            "UPDATE wfm_source_terminal_reviews SET state='retain_local_work',revision=2,decided_at_utc=?,"
            "last_command_id=? WHERE source_terminal_review_id=?",
            (created_at, command_id, review_id),
        )
    return review_id


def test_set_task_plan_schedules_unscheduled_task_with_manual_only_provenance_and_exact_audit(initialized_database) -> None:
    factory = _factory(initialized_database)
    _, created = _create_local(factory)
    service = TaskPlanningService(factory)
    command_id = new_uuid4()
    schedule = _schedule(1_900_000_123, 1_900_003_789)

    result = service.set_task_plan(
        command_id=command_id,
        task_id=created.task_id,
        task_revision=1,
        current_plan_revision=0,
        schedule=schedule,
        reason_category="operator_schedule",
    )

    assert result.outcome == "APPLIED"
    assert result.revision == 2
    assert not result.replayed
    assert len(result.result_refs) == 1
    plan_id = result.result_refs[0].result_id
    assert result.result_refs[0].result_type == "task_plan"

    row = _current_plan(factory, created.task_id)
    assert row is not None
    assert tuple(row[:9]) == (
        plan_id,
        1,
        schedule.start_utc,
        schedule.end_utc,
        "manual",
        TZ,
        None,
        None,
        "operator_schedule",
    )
    assert str(row[9]) == command_id

    with ReadSnapshot(factory) as snapshot:
        assert snapshot.connection.execute(
            "SELECT revision FROM tasks WHERE task_id=?", (created.task_id,)
        ).fetchone() == (2,)
        audit = snapshot.connection.execute(
            "SELECT audit_event_id,action_type,reason_category,payload_json FROM audit_events WHERE command_id=?",
            (command_id,),
        ).fetchone()
        assert audit is not None
        assert str(audit[1]) == "task.plan_changed"
        assert str(audit[2]) == "operator_schedule"
        assert json.loads(str(audit[3])) == {
            "membership_plan_mismatch": False,
            "new_plan_revision_id": plan_id,
            "origin": "manual",
            "prior_plan_revision_id": None,
            "reason_category": "operator_schedule",
            "resulting_task_revision": 2,
            "task_id": created.task_id,
        }
        refs = snapshot.connection.execute(
            "SELECT result_type,result_id FROM audit_event_results WHERE audit_event_id=?",
            (str(audit[0]),),
        ).fetchall()
        assert [(str(item[0]), str(item[1])) for item in refs] == [("task_plan", plan_id)]


def test_set_task_plan_replaces_unlocked_plan_append_only_and_advances_both_revisions_once(initialized_database) -> None:
    factory = _factory(initialized_database)
    initial = _schedule(1_901_000_000, 1_901_003_600)
    _, created = _create_local(factory, schedule=initial)
    prior = _current_plan(factory, created.task_id)
    assert prior is not None
    prior_id = str(prior[0])
    replacement = _schedule(1_902_000_111, 1_902_007_777)

    result = TaskPlanningService(factory).set_task_plan(
        command_id=new_uuid4(),
        task_id=created.task_id,
        task_revision=1,
        current_plan_revision=1,
        schedule=replacement,
        reason_category="reschedule",
    )
    assert result.revision == 2
    new_id = result.result_refs[0].result_id

    current = _current_plan(factory, created.task_id)
    assert current is not None
    assert (str(current[0]), int(current[1]), int(current[2]), int(current[3])) == (
        new_id,
        2,
        replacement.start_utc,
        replacement.end_utc,
    )
    assert str(current[7]) == prior_id
    assert str(current[8]) == "reschedule"
    with ReadSnapshot(factory) as snapshot:
        histories = snapshot.connection.execute(
            "SELECT plan_revision_id,start_utc,end_utc,origin,source_observation_id,predecessor_plan_revision_id "
            "FROM task_plan_revisions WHERE task_id=? ORDER BY accepted_at_utc,plan_revision_id",
            (created.task_id,),
        ).fetchall()
        assert len(histories) == 2
        original = next(row for row in histories if str(row[0]) == prior_id)
        assert tuple(original[1:]) == (initial.start_utc, initial.end_utc, "manual", None, None)
        successor = next(row for row in histories if str(row[0]) == new_id)
        assert tuple(successor[1:]) == (
            replacement.start_utc,
            replacement.end_utc,
            "manual",
            None,
            prior_id,
        )
        assert snapshot.connection.execute(
            "SELECT revision FROM tasks WHERE task_id=?", (created.task_id,)
        ).fetchone() == (2,)


def test_set_task_plan_exact_same_schedule_is_semantic_no_change_before_lock_checks(initialized_database) -> None:
    factory = _factory(initialized_database)
    schedule = _schedule(1_903_000_000, 1_903_003_600)
    creation_command, created = _create_local(factory, schedule=schedule)
    with UnitOfWork(factory) as uow:
        lock_event_id = new_uuid4()
        uow.connection.execute(
            "INSERT INTO task_lock_events(lock_event_id,task_id,lock_kind,action,reason_code,recorded_at_utc,command_id) "
            "VALUES (?,?,'plan','lock','reviewed_lock',2,?)",
            (lock_event_id, created.task_id, creation_command),
        )
        uow.connection.execute(
            "INSERT INTO task_lock_projection(task_id,explicit_plan_lock,explicit_membership_lock,revision,last_event_id) "
            "VALUES (?,1,0,1,?)",
            (created.task_id, lock_event_id),
        )
    command_id = new_uuid4()

    result = TaskPlanningService(factory).set_task_plan(
        command_id=command_id,
        task_id=created.task_id,
        task_revision=1,
        current_plan_revision=1,
        schedule=schedule,
        reason_category="irrelevant_for_equal_plan",
    )
    assert result.no_change
    assert result.revision == 1
    assert result.result_refs == ()
    with ReadSnapshot(factory) as snapshot:
        assert snapshot.connection.execute(
            "SELECT count(*) FROM task_plan_revisions WHERE task_id=?", (created.task_id,)
        ).fetchone()[0] == 1
        assert snapshot.connection.execute(
            "SELECT revision FROM task_plan_current WHERE task_id=?", (created.task_id,)
        ).fetchone() == (1,)
        assert snapshot.connection.execute(
            "SELECT count(*) FROM audit_events WHERE command_id=?", (command_id,)
        ).fetchone()[0] == 0
        assert snapshot.connection.execute(
            "SELECT result_type,result_id FROM command_receipts WHERE command_id=?", (command_id,)
        ).fetchone() == ("NO_CHANGE", None)


def test_set_task_plan_rejects_stale_task_and_plan_presence_races_before_receipt(initialized_database) -> None:
    factory = _factory(initialized_database)
    service = TaskPlanningService(factory)
    schedule = _schedule(1_904_000_000, 1_904_003_600)
    _, unscheduled = _create_local(factory)

    stale_task = new_uuid4()
    with pytest.raises(SomaError) as task_error:
        service.set_task_plan(
            command_id=stale_task,
            task_id=unscheduled.task_id,
            task_revision=2,
            current_plan_revision=0,
            schedule=schedule,
        )
    assert task_error.value.code == "TASK_STALE"
    assert not _receipt_exists(factory, stale_task)

    expected_present = new_uuid4()
    with pytest.raises(SomaError) as absent_error:
        service.set_task_plan(
            command_id=expected_present,
            task_id=unscheduled.task_id,
            task_revision=1,
            current_plan_revision=1,
            schedule=schedule,
        )
    assert absent_error.value.code == "TASK_STALE"
    assert not _receipt_exists(factory, expected_present)

    _, scheduled = _create_local(factory, name="Already scheduled", schedule=schedule)
    expected_absent = new_uuid4()
    with pytest.raises(SomaError) as present_error:
        service.set_task_plan(
            command_id=expected_absent,
            task_id=scheduled.task_id,
            task_revision=1,
            current_plan_revision=0,
            schedule=_schedule(1_905_000_000, 1_905_003_600),
        )
    assert present_error.value.code == "TASK_STALE"
    assert not _receipt_exists(factory, expected_absent)


def test_set_task_plan_preflight_is_strict_and_writes_nothing(initialized_database) -> None:
    factory = _factory(initialized_database)
    _, created = _create_local(factory)
    service = TaskPlanningService(factory)
    schedule = _schedule(1_906_000_000, 1_906_003_600)
    cases = (
        {"task_revision": True, "current_plan_revision": 0, "schedule": schedule, "reason_category": None},
        {"task_revision": 1, "current_plan_revision": True, "schedule": schedule, "reason_category": None},
        {"task_revision": 1, "current_plan_revision": -1, "schedule": schedule, "reason_category": None},
        {"task_revision": 1, "current_plan_revision": 0, "schedule": object(), "reason_category": None},
        {"task_revision": 1, "current_plan_revision": 0, "schedule": schedule, "reason_category": ""},
        {"task_revision": 1, "current_plan_revision": 0, "schedule": schedule, "reason_category": "bad\nreason"},
    )
    for case in cases:
        command_id = new_uuid4()
        with pytest.raises(ValidationError):
            service.set_task_plan(command_id=command_id, task_id=created.task_id, **case)
        assert not _receipt_exists(factory, command_id)


def test_set_task_plan_is_blocked_by_explicit_plan_lock_and_execution_history(initialized_database) -> None:
    factory = _factory(initialized_database)
    schedule = _schedule(1_907_000_000, 1_907_003_600)

    creation_command, explicit = _create_local(factory, name="Explicit lock")
    with UnitOfWork(factory) as uow:
        event_id = new_uuid4()
        uow.connection.execute(
            "INSERT INTO task_lock_events(lock_event_id,task_id,lock_kind,action,reason_code,recorded_at_utc,command_id) "
            "VALUES (?,?,'plan','lock','operator_lock',2,?)",
            (event_id, explicit.task_id, creation_command),
        )
        uow.connection.execute(
            "INSERT INTO task_lock_projection(task_id,explicit_plan_lock,explicit_membership_lock,revision,last_event_id) "
            "VALUES (?,1,0,1,?)",
            (explicit.task_id, event_id),
        )
    command_id = new_uuid4()
    with pytest.raises(SomaError) as explicit_error:
        TaskPlanningService(factory).set_task_plan(
            command_id=command_id,
            task_id=explicit.task_id,
            task_revision=1,
            current_plan_revision=0,
            schedule=schedule,
        )
    assert explicit_error.value.code == "TASK_PLAN_LOCKED"
    assert not _receipt_exists(factory, command_id)

    execution_command, execution = _create_local(factory, name="Execution history")
    with UnitOfWork(factory) as uow:
        event_id = new_uuid4()
        uow.connection.execute(
            "INSERT INTO task_execution_events(execution_event_id,task_id,event_kind,effective_at_utc,target_event_id,"
            "correction_action,reason_code,recorded_at_utc,command_id) VALUES (?,?,'start',10,NULL,NULL,NULL,10,?)",
            (event_id, execution.task_id, execution_command),
        )
        uow.connection.execute(
            "INSERT INTO task_execution_projection(task_id,execution_state,actual_start_utc,actual_end_utc,"
            "effective_termination_utc,termination_reason,revision,last_event_id) "
            "VALUES (?,'in_progress',10,NULL,NULL,NULL,1,?)",
            (execution.task_id, event_id),
        )
    command_id = new_uuid4()
    with pytest.raises(SomaError) as history_error:
        TaskPlanningService(factory).set_task_plan(
            command_id=command_id,
            task_id=execution.task_id,
            task_revision=1,
            current_plan_revision=0,
            schedule=schedule,
        )
    assert history_error.value.code == "TASK_PLAN_LOCKED"
    assert not _receipt_exists(factory, command_id)


def test_set_task_plan_terminal_wfm_source_requires_current_exact_retain_resolution(initialized_database) -> None:
    factory = _factory(initialized_database)
    registration_command, wfm = _create_wfm(factory, task_no="TK00000000900001")
    _seed_terminal_wfm_source(factory, task_id=wfm.task_id, command_id=registration_command)
    schedule = _schedule(1_908_000_000, 1_908_003_600)

    unresolved_command = new_uuid4()
    with pytest.raises(SomaError) as unresolved:
        TaskPlanningService(factory).set_task_plan(
            command_id=unresolved_command,
            task_id=wfm.task_id,
            task_revision=1,
            current_plan_revision=0,
            schedule=schedule,
        )
    assert unresolved.value.code == "TASK_PLAN_LOCKED"
    assert not _receipt_exists(factory, unresolved_command)

    _seed_retain_review(factory, task_id=wfm.task_id, command_id=registration_command, created_at=1)
    applied = TaskPlanningService(factory).set_task_plan(
        command_id=new_uuid4(),
        task_id=wfm.task_id,
        task_revision=1,
        current_plan_revision=0,
        schedule=schedule,
    )
    assert applied.outcome == "APPLIED"
    assert applied.revision == 2


def test_set_task_plan_newer_pending_terminal_review_defeats_older_retain(initialized_database) -> None:
    factory = _factory(initialized_database)
    registration_command, wfm = _create_wfm(factory, task_no="TK00000000900002")
    _seed_terminal_wfm_source(factory, task_id=wfm.task_id, command_id=registration_command)
    _seed_retain_review(factory, task_id=wfm.task_id, command_id=registration_command, created_at=1)
    with UnitOfWork(factory) as uow:
        uow.connection.execute(
            "INSERT INTO wfm_source_terminal_reviews(source_terminal_review_id,task_id,source_projection_revision,"
            "provider_lifecycle_class,input_fingerprint,state,local_consequence_event_id,revision,created_at_utc,"
            "decided_at_utc,last_command_id) VALUES (?,?,1,'complete',?,'pending',NULL,1,2,NULL,NULL)",
            (new_uuid4(), wfm.task_id, "e" * 64),
        )

    command_id = new_uuid4()
    with pytest.raises(SomaError) as stale_review:
        TaskPlanningService(factory).set_task_plan(
            command_id=command_id,
            task_id=wfm.task_id,
            task_revision=1,
            current_plan_revision=0,
            schedule=_schedule(1_909_000_000, 1_909_003_600),
        )
    assert stale_review.value.code == "TASK_PLAN_LOCKED"
    assert not _receipt_exists(factory, command_id)


def test_set_task_plan_preserves_objective_pin_and_envelope_and_surfaces_mismatch(initialized_database) -> None:
    factory = _factory(initialized_database)
    original = _schedule(1_910_000_000, 1_910_003_600)
    creation_command, task = _create_local(factory, schedule=original)
    objective_id, pinned_plan_id = _attach_planned_objective(
        factory,
        task_id=task.task_id,
        creation_command_id=creation_command,
    )
    with ReadSnapshot(factory) as snapshot:
        before_envelope = tuple(snapshot.connection.execute(
            "SELECT start_utc,end_utc,member_count,membership_input_fingerprint,revision,last_command_id "
            "FROM objective_envelope_projection WHERE objective_id=?",
            (objective_id,),
        ).fetchone())

    command_id = new_uuid4()
    result = TaskPlanningService(factory).set_task_plan(
        command_id=command_id,
        task_id=task.task_id,
        task_revision=1,
        current_plan_revision=1,
        schedule=_schedule(1_911_000_000, 1_911_007_200),
        reason_category="reviewed_reschedule",
    )
    assert result.revision == 2
    new_plan_id = result.result_refs[0].result_id

    with ReadSnapshot(factory) as snapshot:
        membership = snapshot.connection.execute(
            "SELECT objective_id,accepted_plan_revision_id,membership_revision,last_event_id,last_command_id "
            "FROM objective_task_membership_current WHERE task_id=?",
            (task.task_id,),
        ).fetchone()
        assert str(membership[0]) == objective_id
        assert str(membership[1]) == pinned_plan_id
        assert int(membership[2]) == 1
        assert tuple(snapshot.connection.execute(
            "SELECT start_utc,end_utc,member_count,membership_input_fingerprint,revision,last_command_id "
            "FROM objective_envelope_projection WHERE objective_id=?",
            (objective_id,),
        ).fetchone()) == before_envelope
        aggregate = snapshot.connection.execute(
            "SELECT execution_state,attention_reason,revision,last_command_id FROM objective_aggregate_projection "
            "WHERE objective_id=?",
            (objective_id,),
        ).fetchone()
        assert tuple(aggregate) == ("planned", "plan_membership_mismatch", 2, command_id)
        assert snapshot.connection.execute(
            "SELECT plan_revision_id,revision FROM task_plan_current WHERE task_id=?", (task.task_id,)
        ).fetchone() == (new_plan_id, 2)
        audit = snapshot.connection.execute(
            "SELECT payload_json FROM audit_events WHERE command_id=?", (command_id,)
        ).fetchone()
        assert json.loads(str(audit[0]))["membership_plan_mismatch"] is True


def test_set_task_plan_preserves_higher_objective_attention_reason_without_projection_churn(initialized_database) -> None:
    factory = _factory(initialized_database)
    original = _schedule(1_912_000_000, 1_912_003_600)
    creation_command, task = _create_local(factory, schedule=original)
    objective_id, pinned_plan_id = _attach_planned_objective(
        factory,
        task_id=task.task_id,
        creation_command_id=creation_command,
        attention_reason="source_terminal_conflict",
    )

    result = TaskPlanningService(factory).set_task_plan(
        command_id=new_uuid4(),
        task_id=task.task_id,
        task_revision=1,
        current_plan_revision=1,
        schedule=_schedule(1_913_000_000, 1_913_003_600),
    )
    assert result.outcome == "APPLIED"
    with ReadSnapshot(factory) as snapshot:
        assert snapshot.connection.execute(
            "SELECT accepted_plan_revision_id FROM objective_task_membership_current WHERE task_id=?",
            (task.task_id,),
        ).fetchone() == (pinned_plan_id,)
        assert snapshot.connection.execute(
            "SELECT attention_reason,revision,last_command_id FROM objective_aggregate_projection WHERE objective_id=?",
            (objective_id,),
        ).fetchone() == ("source_terminal_conflict", 1, creation_command)
        audit = snapshot.connection.execute(
            "SELECT payload_json FROM audit_events WHERE command_id=(SELECT command_id FROM task_plan_revisions "
            "WHERE plan_revision_id=?)",
            (result.result_refs[0].result_id,),
        ).fetchone()
        assert json.loads(str(audit[0]))["membership_plan_mismatch"] is True


def test_set_task_plan_blocks_historical_objective_and_fails_closed_when_aggregate_missing(initialized_database) -> None:
    factory = _factory(initialized_database)
    schedule = _schedule(1_914_000_000, 1_914_003_600)

    creation_command, historical = _create_local(factory, name="Historical member", schedule=schedule)
    _attach_planned_objective(
        factory,
        task_id=historical.task_id,
        creation_command_id=creation_command,
        creation_origin="historical_provider_complete",
        execution_state="historical_structure",
    )
    command_id = new_uuid4()
    with pytest.raises(SomaError) as protected:
        TaskPlanningService(factory).set_task_plan(
            command_id=command_id,
            task_id=historical.task_id,
            task_revision=1,
            current_plan_revision=1,
            schedule=_schedule(1_915_000_000, 1_915_003_600),
        )
    assert protected.value.code == "TASK_PLAN_LOCKED"
    assert not _receipt_exists(factory, command_id)

    creation_command, indeterminate = _create_local(factory, name="Missing aggregate", schedule=schedule)
    _attach_planned_objective(
        factory,
        task_id=indeterminate.task_id,
        creation_command_id=creation_command,
        include_aggregate=False,
    )
    command_id = new_uuid4()
    with pytest.raises(SomaError) as missing:
        TaskPlanningService(factory).set_task_plan(
            command_id=command_id,
            task_id=indeterminate.task_id,
            task_revision=1,
            current_plan_revision=1,
            schedule=_schedule(1_916_000_000, 1_916_003_600),
        )
    assert missing.value.code == "TASK_PLAN_LOCKED"
    assert not _receipt_exists(factory, command_id)


def test_set_task_plan_audit_failure_rolls_back_plan_pointer_task_revision_and_receipt(initialized_database, monkeypatch) -> None:
    factory = _factory(initialized_database)
    initial = _schedule(1_917_000_000, 1_917_003_600)
    _, task = _create_local(factory, schedule=initial)
    service = TaskPlanningService(factory)
    command_id = new_uuid4()

    def fail_audit(*_args, **_kwargs):
        raise SomaError("AUDIT_PERSISTENCE_FAILURE", "injected Task plan audit failure")

    monkeypatch.setattr(service._boundary._audit_writer, "write", fail_audit)
    with pytest.raises(SomaError) as failure:
        service.set_task_plan(
            command_id=command_id,
            task_id=task.task_id,
            task_revision=1,
            current_plan_revision=1,
            schedule=_schedule(1_918_000_000, 1_918_003_600),
            reason_category="rollback_probe",
        )
    assert failure.value.code == "AUDIT_PERSISTENCE_FAILURE"

    current = _current_plan(factory, task.task_id)
    assert current is not None
    assert (int(current[1]), int(current[2]), int(current[3])) == (1, initial.start_utc, initial.end_utc)
    with ReadSnapshot(factory) as snapshot:
        assert snapshot.connection.execute(
            "SELECT count(*) FROM task_plan_revisions WHERE task_id=?", (task.task_id,)
        ).fetchone()[0] == 1
        assert snapshot.connection.execute(
            "SELECT revision FROM tasks WHERE task_id=?", (task.task_id,)
        ).fetchone() == (1,)
        assert snapshot.connection.execute(
            "SELECT 1 FROM command_receipts WHERE command_id=?", (command_id,)
        ).fetchone() is None


def test_set_task_plan_exact_replay_returns_original_result_before_newer_plan_reads(initialized_database) -> None:
    factory = _factory(initialized_database)
    _, task = _create_local(factory)
    service = TaskPlanningService(factory)
    first_command = new_uuid4()
    first_schedule = _schedule(1_919_000_000, 1_919_003_600)
    first_kwargs = dict(
        command_id=first_command,
        task_id=task.task_id,
        task_revision=1,
        current_plan_revision=0,
        schedule=first_schedule,
        reason_category="first_plan",
    )
    first = service.set_task_plan(**first_kwargs)
    assert first.revision == 2

    second = service.set_task_plan(
        command_id=new_uuid4(),
        task_id=task.task_id,
        task_revision=2,
        current_plan_revision=1,
        schedule=_schedule(1_920_000_000, 1_920_003_600),
        reason_category="newer_plan",
    )
    assert second.revision == 3

    replay = service.set_task_plan(**first_kwargs)
    assert replay.replayed
    assert replay.outcome == first.outcome
    assert replay.task_id == first.task_id
    assert replay.revision == first.revision
    assert replay.result_refs == first.result_refs
    current = _current_plan(factory, task.task_id)
    assert current is not None
    assert str(current[0]) == second.result_refs[0].result_id
    assert int(current[1]) == 2
