from __future__ import annotations

import pytest

from soma.foundation.errors import SomaError
from soma.foundation.identifiers import new_uuid4
from soma.foundation.persistence.uow import ReadSnapshot, UnitOfWork
from soma.objectives_tasks import AcceptedTaskSchedule, TaskPlanningService
from soma.objectives_tasks.queries.execution_review import (
    TaskExecutionCorrectionQueryService,
    TaskOutcomeReviewQueryService,
)
from soma.objectives_tasks.services.task_execution import TaskExecutionService
from soma.objectives_tasks.services.task_review import TaskReviewService


TZ = "America/Guayaquil"


def _factory(initialized_database):
    database_path, factory_for_path = initialized_database
    return factory_for_path(database_path)


def _new_task(factory, *, name: str, ordinal: int):
    command_id = new_uuid4()
    created = TaskPlanningService(factory).create_local_task(
        command_id=command_id,
        local_task_name=name,
        schedule=AcceptedTaskSchedule(
            start_utc=2_010_000_000 + ordinal * 10_000,
            end_utc=2_010_003_600 + ordinal * 10_000,
            scheduling_timezone_iana=TZ,
        ),
    )
    return command_id, created


def _seed_objective(factory, *, creation_command: str, task_id: str, ordinal: int) -> str:
    objective_id = new_uuid4()
    membership_event_id = new_uuid4()
    with UnitOfWork(factory) as uow:
        plan_row = uow.connection.execute(
            "SELECT pc.plan_revision_id,p.start_utc,p.end_utc "
            "FROM task_plan_current pc JOIN task_plan_revisions p ON p.plan_revision_id=pc.plan_revision_id "
            "WHERE pc.task_id=?",
            (task_id,),
        ).fetchone()
        assert plan_row is not None
        plan_id, start_utc, end_utc = str(plan_row[0]), int(plan_row[1]), int(plan_row[2])
        tracking_sequence = 99_000_000 + ordinal
        uow.connection.execute(
            "INSERT INTO objectives(objective_id,tracking_sequence,tracking_id,creation_origin,"
            "superseded_by_objective_id,revision,created_at_utc,created_command_id) "
            "VALUES (?,?,?,'manual',NULL,1,1,?)",
            (objective_id, tracking_sequence, f"MW-{tracking_sequence:08d}", creation_command),
        )
        uow.connection.execute(
            "INSERT INTO objective_membership_events(membership_event_id,task_id,event_kind,from_objective_id,"
            "to_objective_id,accepted_plan_revision_id,grouping_proposal_id,reason_code,recorded_at_utc,command_id) "
            "VALUES (?,?,'add',NULL,?,?,NULL,NULL,1,?)",
            (membership_event_id, task_id, objective_id, plan_id, creation_command),
        )
        uow.connection.execute(
            "INSERT INTO objective_task_membership_current(task_id,objective_id,accepted_plan_revision_id,"
            "membership_revision,last_event_id,last_command_id) VALUES (?,?,?,1,?,?)",
            (task_id, objective_id, plan_id, membership_event_id, creation_command),
        )
        uow.connection.execute(
            "INSERT INTO objective_envelope_projection(objective_id,start_utc,end_utc,member_count,"
            "membership_input_fingerprint,revision,last_command_id) VALUES (?,?,?,?,?,1,?)",
            (objective_id, start_utc, end_utc, 1, "a" * 64, creation_command),
        )
        uow.connection.execute(
            "INSERT INTO objective_aggregate_projection(objective_id,execution_state,aggregate_outcome,"
            "actual_start_utc,actual_end_utc,attention_reason,included_task_count,excluded_task_count,"
            "aggregate_input_fingerprint,revision,last_command_id) "
            "VALUES (?,'planned',NULL,NULL,NULL,NULL,1,0,?,1,?)",
            (objective_id, "b" * 64, creation_command),
        )
    return objective_id


def _start_and_end(factory, *, task_id: str, task_revision: int, base_time: int):
    service = TaskExecutionService(factory)
    started = service.start_task_execution(
        command_id=new_uuid4(),
        task_id=task_id,
        task_revision=task_revision,
        execution_revision=0,
        effective_start_utc=base_time + 100,
    )
    ended = service.end_task_execution(
        command_id=new_uuid4(),
        task_id=task_id,
        task_revision=started.revision,
        execution_revision=1,
        effective_end_utc=base_time + 200,
    )
    with ReadSnapshot(factory) as snapshot:
        rows = snapshot.connection.execute(
            "SELECT execution_event_id,execution_revision,event_kind FROM task_execution_events "
            "WHERE task_id=? ORDER BY execution_revision",
            (task_id,),
        ).fetchall()
    assert [(int(row[1]), str(row[2])) for row in rows] == [(1, "start"), (2, "end")]
    return ended, str(rows[0][0]), str(rows[1][0])


def _correction_preview(
    factory,
    *,
    task_id: str,
    task_revision: int,
    execution_revision: int,
    target_event_id: str,
    target_revision: int,
    action: str,
    replacement: int | None,
    reason: str,
):
    return TaskExecutionCorrectionQueryService(factory).preview(
        task_id=task_id,
        task_revision=task_revision,
        execution_revision=execution_revision,
        target_execution_event_id=target_event_id,
        target_execution_revision=target_revision,
        correction_action=action,
        replacement_effective_at_utc=replacement,
        reason_category=reason,
    )


def test_execution_correction_replace_time_applies_and_replays_exact(initialized_database) -> None:
    factory = _factory(initialized_database)
    _creation_command, created = _new_task(factory, name="Correct end", ordinal=1)
    base_time = 2_010_010_000
    ended, _start_id, end_id = _start_and_end(
        factory,
        task_id=created.task_id,
        task_revision=created.revision,
        base_time=base_time,
    )
    preview = _correction_preview(
        factory,
        task_id=created.task_id,
        task_revision=ended.revision,
        execution_revision=2,
        target_event_id=end_id,
        target_revision=2,
        action="replace_time",
        replacement=base_time + 250,
        reason="time_correction",
    )
    assert preview.eligible is True

    command_id = new_uuid4()
    service = TaskExecutionService(factory)
    applied = service.correct_task_execution_evidence(
        command_id=command_id,
        task_id=created.task_id,
        task_revision=ended.revision,
        execution_revision=2,
        target_execution_event_id=end_id,
        target_execution_revision=2,
        correction_action="replace_time",
        replacement_effective_at_utc=base_time + 250,
        reason_category="time_correction",
        correction_review_fingerprint=preview.correction_review_fingerprint,
        accept_outcome_invalidation=False,
    )
    assert applied.outcome == "APPLIED"
    assert applied.revision == ended.revision + 1
    assert applied.replayed is False
    correction_id = applied.result_refs[0].result_id

    replay = service.correct_task_execution_evidence(
        command_id=command_id,
        task_id=created.task_id,
        task_revision=ended.revision,
        execution_revision=2,
        target_execution_event_id=end_id,
        target_execution_revision=2,
        correction_action="replace_time",
        replacement_effective_at_utc=base_time + 250,
        reason_category="time_correction",
        correction_review_fingerprint=preview.correction_review_fingerprint,
        accept_outcome_invalidation=False,
    )
    assert replay.replayed is True
    assert replay.revision == applied.revision
    assert replay.result_refs == applied.result_refs

    with ReadSnapshot(factory) as snapshot:
        assert snapshot.connection.execute(
            "SELECT effective_at_utc FROM task_execution_events WHERE execution_event_id=?",
            (end_id,),
        ).fetchone() == (base_time + 200,)
        assert snapshot.connection.execute(
            "SELECT execution_revision,event_kind,effective_at_utc,target_event_id,correction_action "
            "FROM task_execution_events WHERE execution_event_id=?",
            (correction_id,),
        ).fetchone() == (3, "correction", base_time + 250, end_id, "replace_time")
        assert snapshot.connection.execute(
            "SELECT execution_state,actual_start_utc,actual_end_utc,revision,last_event_id "
            "FROM task_execution_projection WHERE task_id=?",
            (created.task_id,),
        ).fetchone() == ("ended", base_time + 100, base_time + 250, 3, correction_id)
        assert snapshot.connection.execute(
            "SELECT count(*) FROM task_execution_events WHERE task_id=?",
            (created.task_id,),
        ).fetchone()[0] == 3
        assert snapshot.connection.execute(
            "SELECT count(*) FROM audit_events WHERE command_id=? AND action_type='task.execution_changed'",
            (command_id,),
        ).fetchone()[0] == 1


def test_execution_correction_rejects_preview_drift_before_receipt(initialized_database) -> None:
    factory = _factory(initialized_database)
    _creation_command, created = _new_task(factory, name="Stale correction", ordinal=2)
    base_time = 2_010_020_000
    ended, _start_id, end_id = _start_and_end(
        factory,
        task_id=created.task_id,
        task_revision=created.revision,
        base_time=base_time,
    )
    stale_preview = _correction_preview(
        factory,
        task_id=created.task_id,
        task_revision=ended.revision,
        execution_revision=2,
        target_event_id=end_id,
        target_revision=2,
        action="replace_time",
        replacement=base_time + 260,
        reason="stale_preview",
    )
    winning_preview = _correction_preview(
        factory,
        task_id=created.task_id,
        task_revision=ended.revision,
        execution_revision=2,
        target_event_id=end_id,
        target_revision=2,
        action="replace_time",
        replacement=base_time + 240,
        reason="winning_preview",
    )
    TaskExecutionService(factory).correct_task_execution_evidence(
        command_id=new_uuid4(),
        task_id=created.task_id,
        task_revision=ended.revision,
        execution_revision=2,
        target_execution_event_id=end_id,
        target_execution_revision=2,
        correction_action="replace_time",
        replacement_effective_at_utc=base_time + 240,
        reason_category="winning_preview",
        correction_review_fingerprint=winning_preview.correction_review_fingerprint,
        accept_outcome_invalidation=False,
    )

    attempted_command = new_uuid4()
    with pytest.raises(SomaError) as stale:
        TaskExecutionService(factory).correct_task_execution_evidence(
            command_id=attempted_command,
            task_id=created.task_id,
            task_revision=ended.revision,
            execution_revision=2,
            target_execution_event_id=end_id,
            target_execution_revision=2,
            correction_action="replace_time",
            replacement_effective_at_utc=base_time + 260,
            reason_category="stale_preview",
            correction_review_fingerprint=stale_preview.correction_review_fingerprint,
            accept_outcome_invalidation=False,
        )
    assert stale.value.code == "TASK_REVIEW_STALE"
    with ReadSnapshot(factory) as snapshot:
        assert snapshot.connection.execute(
            "SELECT count(*) FROM command_receipts WHERE command_id=?",
            (attempted_command,),
        ).fetchone()[0] == 0
        assert snapshot.connection.execute(
            "SELECT count(*) FROM task_execution_events WHERE task_id=?",
            (created.task_id,),
        ).fetchone()[0] == 3


def test_execution_correction_invalidated_outcome_requires_ack_and_remains_historical(initialized_database) -> None:
    factory = _factory(initialized_database)
    creation_command, created = _new_task(factory, name="Invalidate completed", ordinal=3)
    objective_id = _seed_objective(
        factory,
        creation_command=creation_command,
        task_id=created.task_id,
        ordinal=3,
    )
    base_time = 2_010_030_000
    ended, _start_id, end_id = _start_and_end(
        factory,
        task_id=created.task_id,
        task_revision=created.revision,
        base_time=base_time,
    )
    review_preview = TaskOutcomeReviewQueryService(factory).preview(
        task_id=created.task_id,
        task_revision=ended.revision,
        execution_revision=2,
        outcome_revision=0,
        current_outcome_event_id=None,
        outcome="completed",
        reason_category=None,
    )
    reviewed = TaskReviewService(factory).review_task_outcome(
        command_id=new_uuid4(),
        task_id=created.task_id,
        task_revision=ended.revision,
        execution_revision=2,
        outcome_revision=0,
        current_outcome_event_id=None,
        outcome="completed",
        reason_category=None,
        outcome_review_fingerprint=review_preview.outcome_review_fingerprint,
    )
    outcome_event_id = reviewed.result_refs[0].result_id
    correction_preview = _correction_preview(
        factory,
        task_id=created.task_id,
        task_revision=reviewed.revision,
        execution_revision=2,
        target_event_id=end_id,
        target_revision=2,
        action="withdraw",
        replacement=None,
        reason="false_end",
    )
    assert correction_preview.outcome_invalidation_required is True

    rejected_command = new_uuid4()
    with pytest.raises(SomaError) as rejected:
        TaskExecutionService(factory).correct_task_execution_evidence(
            command_id=rejected_command,
            task_id=created.task_id,
            task_revision=reviewed.revision,
            execution_revision=2,
            target_execution_event_id=end_id,
            target_execution_revision=2,
            correction_action="withdraw",
            replacement_effective_at_utc=None,
            reason_category="false_end",
            correction_review_fingerprint=correction_preview.correction_review_fingerprint,
            accept_outcome_invalidation=False,
        )
    assert rejected.value.code == "TASK_OUTCOME_INVALID_FOR_EXECUTION"

    accepted = TaskExecutionService(factory).correct_task_execution_evidence(
        command_id=new_uuid4(),
        task_id=created.task_id,
        task_revision=reviewed.revision,
        execution_revision=2,
        target_execution_event_id=end_id,
        target_execution_revision=2,
        correction_action="withdraw",
        replacement_effective_at_utc=None,
        reason_category="false_end",
        correction_review_fingerprint=correction_preview.correction_review_fingerprint,
        accept_outcome_invalidation=True,
    )
    assert accepted.outcome == "APPLIED"
    assert accepted.revision == reviewed.revision + 1

    with ReadSnapshot(factory) as snapshot:
        assert snapshot.connection.execute(
            "SELECT execution_state,actual_start_utc,actual_end_utc,revision "
            "FROM task_execution_projection WHERE task_id=?",
            (created.task_id,),
        ).fetchone() == ("in_progress", base_time + 100, None, 3)
        assert snapshot.connection.execute(
            "SELECT outcome_event_id,accepted_outcome,revision FROM task_outcome_current WHERE task_id=?",
            (created.task_id,),
        ).fetchone() == (outcome_event_id, "completed", 1)
        assert snapshot.connection.execute(
            "SELECT count(*) FROM task_outcome_events WHERE task_id=?",
            (created.task_id,),
        ).fetchone()[0] == 1
        aggregate = snapshot.connection.execute(
            "SELECT execution_state,aggregate_outcome,actual_start_utc,actual_end_utc "
            "FROM objective_aggregate_projection WHERE objective_id=?",
            (objective_id,),
        ).fetchone()
        assert aggregate == ("in_progress", None, base_time + 100, None)
        assert snapshot.connection.execute(
            "SELECT count(*) FROM command_receipts WHERE command_id=?",
            (rejected_command,),
        ).fetchone()[0] == 0


def test_execution_correction_rejects_already_withdrawn_target_as_review_stale(initialized_database) -> None:
    factory = _factory(initialized_database)
    _creation_command, created = _new_task(factory, name="Withdraw once", ordinal=4)
    base_time = 2_010_040_000
    execution = TaskExecutionService(factory)
    started = execution.start_task_execution(
        command_id=new_uuid4(),
        task_id=created.task_id,
        task_revision=created.revision,
        execution_revision=0,
        effective_start_utc=base_time + 100,
    )
    with ReadSnapshot(factory) as snapshot:
        start_id = str(
            snapshot.connection.execute(
                "SELECT execution_event_id FROM task_execution_events WHERE task_id=? AND execution_revision=1",
                (created.task_id,),
            ).fetchone()[0]
        )
    first_preview = _correction_preview(
        factory,
        task_id=created.task_id,
        task_revision=started.revision,
        execution_revision=1,
        target_event_id=start_id,
        target_revision=1,
        action="withdraw",
        replacement=None,
        reason="false_start",
    )
    first = execution.correct_task_execution_evidence(
        command_id=new_uuid4(),
        task_id=created.task_id,
        task_revision=started.revision,
        execution_revision=1,
        target_execution_event_id=start_id,
        target_execution_revision=1,
        correction_action="withdraw",
        replacement_effective_at_utc=None,
        reason_category="false_start",
        correction_review_fingerprint=first_preview.correction_review_fingerprint,
        accept_outcome_invalidation=False,
    )
    second_preview = _correction_preview(
        factory,
        task_id=created.task_id,
        task_revision=first.revision,
        execution_revision=2,
        target_event_id=start_id,
        target_revision=1,
        action="withdraw",
        replacement=None,
        reason="false_start_again",
    )
    assert second_preview.blockers == ("TARGET_NOT_CURRENT_EFFECTIVE",)

    attempted_command = new_uuid4()
    with pytest.raises(SomaError) as stale:
        execution.correct_task_execution_evidence(
            command_id=attempted_command,
            task_id=created.task_id,
            task_revision=first.revision,
            execution_revision=2,
            target_execution_event_id=start_id,
            target_execution_revision=1,
            correction_action="withdraw",
            replacement_effective_at_utc=None,
            reason_category="false_start_again",
            correction_review_fingerprint=second_preview.correction_review_fingerprint,
            accept_outcome_invalidation=False,
        )
    assert stale.value.code == "TASK_REVIEW_STALE"
    with ReadSnapshot(factory) as snapshot:
        assert snapshot.connection.execute(
            "SELECT count(*) FROM command_receipts WHERE command_id=?",
            (attempted_command,),
        ).fetchone()[0] == 0


def test_execution_correction_rolls_back_all_state_when_audit_fails(
    initialized_database,
    monkeypatch,
) -> None:
    factory = _factory(initialized_database)
    creation_command, created = _new_task(factory, name="Rollback correction", ordinal=5)
    objective_id = _seed_objective(
        factory,
        creation_command=creation_command,
        task_id=created.task_id,
        ordinal=5,
    )
    base_time = 2_010_050_000
    ended, _start_id, end_id = _start_and_end(
        factory,
        task_id=created.task_id,
        task_revision=created.revision,
        base_time=base_time,
    )
    preview = _correction_preview(
        factory,
        task_id=created.task_id,
        task_revision=ended.revision,
        execution_revision=2,
        target_event_id=end_id,
        target_revision=2,
        action="replace_time",
        replacement=base_time + 250,
        reason="rollback_probe",
    )
    with ReadSnapshot(factory) as snapshot:
        before_aggregate = snapshot.connection.execute(
            "SELECT execution_state,actual_start_utc,actual_end_utc,aggregate_input_fingerprint,revision,last_command_id "
            "FROM objective_aggregate_projection WHERE objective_id=?",
            (objective_id,),
        ).fetchone()
        before_task_revision = snapshot.connection.execute(
            "SELECT revision FROM tasks WHERE task_id=?",
            (created.task_id,),
        ).fetchone()[0]

    service = TaskExecutionService(factory)

    def fail_audit(*_args, **_kwargs):
        raise RuntimeError("injected correction audit failure")

    monkeypatch.setattr(service._boundary._audit_writer, "write", fail_audit)
    attempted_command = new_uuid4()
    with pytest.raises(RuntimeError, match="injected correction audit failure"):
        service.correct_task_execution_evidence(
            command_id=attempted_command,
            task_id=created.task_id,
            task_revision=ended.revision,
            execution_revision=2,
            target_execution_event_id=end_id,
            target_execution_revision=2,
            correction_action="replace_time",
            replacement_effective_at_utc=base_time + 250,
            reason_category="rollback_probe",
            correction_review_fingerprint=preview.correction_review_fingerprint,
            accept_outcome_invalidation=False,
        )

    with ReadSnapshot(factory) as snapshot:
        assert snapshot.connection.execute(
            "SELECT count(*) FROM command_receipts WHERE command_id=?",
            (attempted_command,),
        ).fetchone()[0] == 0
        assert snapshot.connection.execute(
            "SELECT count(*) FROM task_execution_events WHERE task_id=?",
            (created.task_id,),
        ).fetchone()[0] == 2
        assert snapshot.connection.execute(
            "SELECT execution_state,actual_start_utc,actual_end_utc,revision,last_event_id "
            "FROM task_execution_projection WHERE task_id=?",
            (created.task_id,),
        ).fetchone() == ("ended", base_time + 100, base_time + 200, 2, end_id)
        assert snapshot.connection.execute(
            "SELECT revision FROM tasks WHERE task_id=?",
            (created.task_id,),
        ).fetchone()[0] == before_task_revision
        assert snapshot.connection.execute(
            "SELECT execution_state,actual_start_utc,actual_end_utc,aggregate_input_fingerprint,revision,last_command_id "
            "FROM objective_aggregate_projection WHERE objective_id=?",
            (objective_id,),
        ).fetchone() == before_aggregate
