from __future__ import annotations

import json

import pytest

from soma.foundation.errors import PersistenceFailure, SomaError
from soma.foundation.identifiers import new_uuid4
from soma.foundation.persistence.uow import ReadSnapshot, UnitOfWork
from soma.objectives_tasks import AcceptedTaskSchedule, TaskPlanningService
from soma.objectives_tasks.queries.task_plan_correction import TaskPlanCorrectionQueryService
from soma.objectives_tasks.services.task_plan_correction import TaskPlanCorrectionService
from soma.tickets.rfcs import RfcService


TZ = "America/Guayaquil"


def _factory(initialized_database):
    database_path, factory_for_path = initialized_database
    return factory_for_path(database_path)


def _schedule(start: int, end: int) -> AcceptedTaskSchedule:
    return AcceptedTaskSchedule(start_utc=start, end_utc=end, scheduling_timezone_iana=TZ)


def _create_local(factory, schedule: AcceptedTaskSchedule):
    command_id = new_uuid4()
    result = TaskPlanningService(factory).create_local_task(
        command_id=command_id,
        local_task_name="Correction target",
        schedule=schedule,
    )
    return command_id, result


def _current_plan(factory, task_id: str):
    with ReadSnapshot(factory) as snapshot:
        return snapshot.connection.execute(
            "SELECT c.plan_revision_id,c.revision,p.start_utc,p.end_utc,p.origin,p.scheduling_timezone_iana,"
            "p.source_observation_id,p.predecessor_plan_revision_id,p.reason_code,p.command_id "
            "FROM task_plan_current c JOIN task_plan_revisions p ON p.plan_revision_id=c.plan_revision_id "
            "WHERE c.task_id=? AND p.task_id=c.task_id",
            (task_id,),
        ).fetchone()


def _preview(factory, task_id: str, replacement: AcceptedTaskSchedule):
    current = _current_plan(factory, task_id)
    assert current is not None
    with ReadSnapshot(factory) as snapshot:
        task_revision = int(snapshot.connection.execute(
            "SELECT revision FROM tasks WHERE task_id=?", (task_id,)
        ).fetchone()[0])
    preview = TaskPlanCorrectionQueryService(factory).preview(
        task_id=task_id,
        task_revision=task_revision,
        current_plan_revision=int(current[1]),
        current_plan_revision_id=str(current[0]),
        schedule=replacement,
    )
    return task_revision, current, preview


def _receipt_exists(factory, command_id: str) -> bool:
    with ReadSnapshot(factory) as snapshot:
        return snapshot.connection.execute(
            "SELECT 1 FROM command_receipts WHERE command_id=?", (command_id,)
        ).fetchone() is not None


def _add_plan_lock(factory, *, task_id: str, command_id: str) -> str:
    event_id = new_uuid4()
    with UnitOfWork(factory) as uow:
        uow.connection.execute(
            "INSERT INTO task_lock_events(lock_event_id,task_id,lock_kind,action,reason_code,recorded_at_utc,command_id) "
            "VALUES (?,?,'plan','lock','operator_lock',2,?)",
            (event_id, task_id, command_id),
        )
        uow.connection.execute(
            "INSERT INTO task_lock_projection(task_id,explicit_plan_lock,explicit_membership_lock,revision,last_event_id) "
            "VALUES (?,1,0,1,?)",
            (task_id, event_id),
        )
    return event_id


def _create_wfm_with_plan(factory, schedule: AcceptedTaskSchedule, task_no: str):
    rfc_id = RfcService(factory).create_or_adopt_identity(
        command_id=new_uuid4(),
        rfc_no="NC00000000009991",
        creation_context="provisional",
    ).rfc_id
    command_id = new_uuid4()
    result = TaskPlanningService(factory).register_manual_wfm_task(
        command_id=command_id,
        task_no=task_no,
        rfc_id=rfc_id,
        schedule=schedule,
    )
    return command_id, result


def test_task_plan_correction_preview_is_deterministic_side_effect_free_and_binds_replacement(initialized_database) -> None:
    factory = _factory(initialized_database)
    original = _schedule(1_920_000_000, 1_920_003_600)
    _, task = _create_local(factory, original)
    first_replacement = _schedule(1_921_000_000, 1_921_003_600)
    second_replacement = _schedule(1_922_000_000, 1_922_003_600)

    task_revision, current, first = _preview(factory, task.task_id, first_replacement)
    _, _, repeated = _preview(factory, task.task_id, first_replacement)
    _, _, second = _preview(factory, task.task_id, second_replacement)

    assert task_revision == 1
    assert int(current[1]) == 1
    assert first.eligible and first.risk == "LOW"
    assert first.fingerprint == repeated.fingerprint
    assert first.fingerprint != second.fingerprint
    assert first.risk_reasons == ()
    assert first.blockers == ()
    with ReadSnapshot(factory) as snapshot:
        assert snapshot.connection.execute("SELECT count(*) FROM command_receipts").fetchone()[0] == 1
        assert snapshot.connection.execute(
            "SELECT count(*) FROM task_plan_revisions WHERE task_id=?", (task.task_id,)
        ).fetchone()[0] == 1


def test_low_risk_correction_is_append_only_and_emits_exact_correction_audit(initialized_database) -> None:
    factory = _factory(initialized_database)
    original = _schedule(1_923_000_000, 1_923_003_600)
    _, task = _create_local(factory, original)
    replacement = _schedule(1_924_000_111, 1_924_007_777)
    task_revision, current, preview = _preview(factory, task.task_id, replacement)
    prior_id = str(current[0])
    command_id = new_uuid4()

    result = TaskPlanCorrectionService(factory).correct_task_plan(
        command_id=command_id,
        task_id=task.task_id,
        task_revision=task_revision,
        current_plan_revision=int(current[1]),
        current_plan_revision_id=prior_id,
        schedule=replacement,
        reason_category="correct_erroneous_plan",
        correction_review_fingerprint=preview.fingerprint,
        accept_high_risk=False,
    )

    assert result.outcome == "APPLIED"
    assert result.revision == 2
    new_id = result.result_refs[0].result_id
    with ReadSnapshot(factory) as snapshot:
        plans = snapshot.connection.execute(
            "SELECT plan_revision_id,start_utc,end_utc,origin,source_observation_id,predecessor_plan_revision_id,reason_code "
            "FROM task_plan_revisions WHERE task_id=? ORDER BY plan_revision_id",
            (task.task_id,),
        ).fetchall()
        assert len(plans) == 2
        original_row = next(row for row in plans if str(row[0]) == prior_id)
        corrected_row = next(row for row in plans if str(row[0]) == new_id)
        assert tuple(original_row[1:]) == (original.start_utc, original.end_utc, "manual", None, None, None)
        assert tuple(corrected_row[1:]) == (
            replacement.start_utc,
            replacement.end_utc,
            "correction",
            None,
            prior_id,
            "correct_erroneous_plan",
        )
        assert snapshot.connection.execute(
            "SELECT plan_revision_id,revision FROM task_plan_current WHERE task_id=?", (task.task_id,)
        ).fetchone() == (new_id, 2)
        assert snapshot.connection.execute(
            "SELECT revision FROM tasks WHERE task_id=?", (task.task_id,)
        ).fetchone() == (2,)
        audit = snapshot.connection.execute(
            "SELECT audit_event_id,action_type,payload_schema,payload_json FROM audit_events WHERE command_id=?",
            (command_id,),
        ).fetchone()
        assert audit is not None
        assert str(audit[1]) == "task.plan_corrected"
        assert str(audit[2]) == "TaskPlanCorrectionAuditV1"
        payload = json.loads(str(audit[3]))
        assert payload == {
            "correction_review_fingerprint": preview.fingerprint,
            "membership_plan_mismatch": False,
            "new_plan_revision_id": new_id,
            "prior_plan_revision_id": prior_id,
            "reason_category": "correct_erroneous_plan",
            "resulting_task_revision": 2,
            "review_risk": "LOW",
            "task_id": task.task_id,
        }
        assert snapshot.connection.execute(
            "SELECT result_type,result_id FROM audit_event_results WHERE audit_event_id=?",
            (str(audit[0]),),
        ).fetchone() == ("task_plan", new_id)


def test_correction_replay_returns_exact_original_result_without_duplicate_history(initialized_database) -> None:
    factory = _factory(initialized_database)
    _, task = _create_local(factory, _schedule(1_925_000_000, 1_925_003_600))
    replacement = _schedule(1_926_000_000, 1_926_003_600)
    task_revision, current, preview = _preview(factory, task.task_id, replacement)
    command_id = new_uuid4()
    kwargs = dict(
        command_id=command_id,
        task_id=task.task_id,
        task_revision=task_revision,
        current_plan_revision=int(current[1]),
        current_plan_revision_id=str(current[0]),
        schedule=replacement,
        reason_category="correct_plan",
        correction_review_fingerprint=preview.fingerprint,
        accept_high_risk=False,
    )
    service = TaskPlanCorrectionService(factory)
    first = service.correct_task_plan(**kwargs)
    replay = service.correct_task_plan(**kwargs)

    assert replay.replayed
    assert replay.outcome == first.outcome
    assert replay.revision == first.revision
    assert replay.result_refs == first.result_refs
    with ReadSnapshot(factory) as snapshot:
        assert snapshot.connection.execute(
            "SELECT count(*) FROM task_plan_revisions WHERE task_id=?", (task.task_id,)
        ).fetchone()[0] == 2
        assert snapshot.connection.execute(
            "SELECT count(*) FROM audit_events WHERE command_id=?", (command_id,)
        ).fetchone()[0] == 1


def test_explicit_plan_lock_makes_preview_high_and_reviewed_correction_preserves_lock(initialized_database) -> None:
    factory = _factory(initialized_database)
    creation_command, task = _create_local(factory, _schedule(1_927_000_000, 1_927_003_600))
    lock_event_id = _add_plan_lock(factory, task_id=task.task_id, command_id=creation_command)
    replacement = _schedule(1_928_000_000, 1_928_003_600)
    task_revision, current, preview = _preview(factory, task.task_id, replacement)
    assert preview.risk == "HIGH"
    assert "EXPLICIT_PLAN_LOCK" in preview.risk_reasons

    blocked_command = new_uuid4()
    with pytest.raises(SomaError) as blocked:
        TaskPlanCorrectionService(factory).correct_task_plan(
            command_id=blocked_command,
            task_id=task.task_id,
            task_revision=task_revision,
            current_plan_revision=int(current[1]),
            current_plan_revision_id=str(current[0]),
            schedule=replacement,
            reason_category="reviewed_lock_override",
            correction_review_fingerprint=preview.fingerprint,
            accept_high_risk=False,
        )
    assert blocked.value.code == "TASK_PLAN_LOCKED"
    assert not _receipt_exists(factory, blocked_command)

    applied = TaskPlanCorrectionService(factory).correct_task_plan(
        command_id=new_uuid4(),
        task_id=task.task_id,
        task_revision=task_revision,
        current_plan_revision=int(current[1]),
        current_plan_revision_id=str(current[0]),
        schedule=replacement,
        reason_category="reviewed_lock_override",
        correction_review_fingerprint=preview.fingerprint,
        accept_high_risk=True,
    )
    assert applied.outcome == "APPLIED"
    with ReadSnapshot(factory) as snapshot:
        assert snapshot.connection.execute(
            "SELECT explicit_plan_lock,revision,last_event_id FROM task_lock_projection WHERE task_id=?",
            (task.task_id,),
        ).fetchone() == (1, 1, lock_event_id)
        assert snapshot.connection.execute(
            "SELECT count(*) FROM task_lock_events WHERE task_id=?", (task.task_id,)
        ).fetchone()[0] == 1


def test_pending_terminal_wfm_review_is_non_overridable_even_with_high_risk_acceptance(initialized_database) -> None:
    factory = _factory(initialized_database)
    registration_command, task = _create_wfm_with_plan(
        factory,
        _schedule(1_929_000_000, 1_929_003_600),
        "TK00000000999991",
    )
    with UnitOfWork(factory) as uow:
        uow.connection.execute(
            "INSERT INTO wfm_source_projection_cache(task_id,provider_status_token,provider_lifecycle_class,"
            "source_plan_start_utc,source_plan_end_utc,accepted_source_observation_id,source_projection_revision,"
            "source_base_token,last_command_id) VALUES (?,'Complete','complete',NULL,NULL,NULL,1,?,?)",
            (task.task_id, "c" * 64, registration_command),
        )
        uow.connection.execute(
            "INSERT INTO wfm_source_terminal_reviews(source_terminal_review_id,task_id,source_projection_revision,"
            "provider_lifecycle_class,input_fingerprint,state,local_consequence_event_id,revision,created_at_utc,"
            "decided_at_utc,last_command_id) VALUES (?,?,1,'complete',?,'pending',NULL,1,2,NULL,NULL)",
            (new_uuid4(), task.task_id, "d" * 64),
        )
    replacement = _schedule(1_930_000_000, 1_930_003_600)
    task_revision, current, preview = _preview(factory, task.task_id, replacement)
    assert not preview.eligible
    assert preview.risk == "HIGH"
    assert preview.blockers == ("SOURCE_TERMINAL_REVIEW_PENDING",)

    command_id = new_uuid4()
    with pytest.raises(SomaError) as blocked:
        TaskPlanCorrectionService(factory).correct_task_plan(
            command_id=command_id,
            task_id=task.task_id,
            task_revision=task_revision,
            current_plan_revision=int(current[1]),
            current_plan_revision_id=str(current[0]),
            schedule=replacement,
            reason_category="must_not_cross_pending_review",
            correction_review_fingerprint=preview.fingerprint,
            accept_high_risk=True,
        )
    assert blocked.value.code == "TASK_PLAN_LOCKED"
    assert not _receipt_exists(factory, command_id)


def test_stale_review_fingerprint_fails_before_receipt_when_authority_changes(initialized_database) -> None:
    factory = _factory(initialized_database)
    creation_command, task = _create_local(factory, _schedule(1_931_000_000, 1_931_003_600))
    replacement = _schedule(1_932_000_000, 1_932_003_600)
    task_revision, current, preview = _preview(factory, task.task_id, replacement)
    _add_plan_lock(factory, task_id=task.task_id, command_id=creation_command)

    command_id = new_uuid4()
    with pytest.raises(SomaError) as stale:
        TaskPlanCorrectionService(factory).correct_task_plan(
            command_id=command_id,
            task_id=task.task_id,
            task_revision=task_revision,
            current_plan_revision=int(current[1]),
            current_plan_revision_id=str(current[0]),
            schedule=replacement,
            reason_category="stale_review",
            correction_review_fingerprint=preview.fingerprint,
            accept_high_risk=True,
        )
    assert stale.value.code == "TASK_STALE"
    assert not _receipt_exists(factory, command_id)


def test_audit_failure_rolls_back_plan_pointer_task_revision_and_receipt(initialized_database, monkeypatch) -> None:
    factory = _factory(initialized_database)
    _, task = _create_local(factory, _schedule(1_933_000_000, 1_933_003_600))
    replacement = _schedule(1_934_000_000, 1_934_003_600)
    task_revision, current, preview = _preview(factory, task.task_id, replacement)
    prior_id = str(current[0])
    service = TaskPlanCorrectionService(factory)
    command_id = new_uuid4()

    def fail_write(*_args, **_kwargs):
        raise PersistenceFailure("injected audit failure")

    monkeypatch.setattr(service._boundary._audit_writer, "write", fail_write)
    with pytest.raises(PersistenceFailure):
        service.correct_task_plan(
            command_id=command_id,
            task_id=task.task_id,
            task_revision=task_revision,
            current_plan_revision=int(current[1]),
            current_plan_revision_id=prior_id,
            schedule=replacement,
            reason_category="rollback_proof",
            correction_review_fingerprint=preview.fingerprint,
            accept_high_risk=False,
        )

    assert not _receipt_exists(factory, command_id)
    with ReadSnapshot(factory) as snapshot:
        assert snapshot.connection.execute(
            "SELECT plan_revision_id,revision FROM task_plan_current WHERE task_id=?", (task.task_id,)
        ).fetchone() == (prior_id, 1)
        assert snapshot.connection.execute(
            "SELECT revision FROM tasks WHERE task_id=?", (task.task_id,)
        ).fetchone() == (1,)
        assert snapshot.connection.execute(
            "SELECT count(*) FROM task_plan_revisions WHERE task_id=?", (task.task_id,)
        ).fetchone()[0] == 1
        assert snapshot.connection.execute(
            "SELECT count(*) FROM audit_events WHERE command_id=?", (command_id,)
        ).fetchone()[0] == 0
