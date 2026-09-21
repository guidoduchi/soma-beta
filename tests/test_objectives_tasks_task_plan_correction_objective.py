from __future__ import annotations

import json

from soma.foundation.identifiers import new_uuid4
from soma.foundation.persistence.uow import ReadSnapshot, UnitOfWork
from soma.objectives_tasks import AcceptedTaskSchedule, TaskPlanningService
from soma.objectives_tasks.queries.task_plan_correction import TaskPlanCorrectionQueryService
from soma.objectives_tasks.services.task_plan_correction import TaskPlanCorrectionService


TZ = "America/Guayaquil"


def _factory(initialized_database):
    database_path, factory_for_path = initialized_database
    return factory_for_path(database_path)


def _schedule(start: int, end: int) -> AcceptedTaskSchedule:
    return AcceptedTaskSchedule(start_utc=start, end_utc=end, scheduling_timezone_iana=TZ)


def test_in_progress_objective_makes_correction_high_and_frozen_even_when_target_task_has_no_execution(initialized_database) -> None:
    factory = _factory(initialized_database)
    creation_command = new_uuid4()
    original = _schedule(1_935_000_000, 1_935_003_600)
    task = TaskPlanningService(factory).create_local_task(
        command_id=creation_command,
        local_task_name="Objective-protected correction target",
        schedule=original,
    )
    with ReadSnapshot(factory) as snapshot:
        plan_id, plan_revision = snapshot.connection.execute(
            "SELECT plan_revision_id,revision FROM task_plan_current WHERE task_id=?",
            (task.task_id,),
        ).fetchone()

    objective_id = new_uuid4()
    membership_event_id = new_uuid4()
    tracking_sequence = 98_999_991
    tracking_id = f"MW-{tracking_sequence:08d}"
    with UnitOfWork(factory) as uow:
        uow.connection.execute(
            "INSERT INTO objectives(objective_id,tracking_sequence,tracking_id,creation_origin,"
            "superseded_by_objective_id,revision,created_at_utc,created_command_id) "
            "VALUES (?,?,?,'manual',NULL,1,1,?)",
            (objective_id, tracking_sequence, tracking_id, creation_command),
        )
        uow.connection.execute(
            "INSERT INTO objective_membership_events(membership_event_id,task_id,event_kind,from_objective_id,"
            "to_objective_id,accepted_plan_revision_id,grouping_proposal_id,reason_code,recorded_at_utc,command_id) "
            "VALUES (?,?,'add',NULL,?,?,NULL,NULL,1,?)",
            (membership_event_id, task.task_id, objective_id, str(plan_id), creation_command),
        )
        uow.connection.execute(
            "INSERT INTO objective_task_membership_current(task_id,objective_id,accepted_plan_revision_id,"
            "membership_revision,last_event_id,last_command_id) VALUES (?,?,?,1,?,?)",
            (task.task_id, objective_id, str(plan_id), membership_event_id, creation_command),
        )
        uow.connection.execute(
            "INSERT INTO objective_envelope_projection(objective_id,start_utc,end_utc,member_count,"
            "membership_input_fingerprint,revision,last_command_id) VALUES (?,?,?,?,?,1,?)",
            (objective_id, original.start_utc, original.end_utc, 1, "a" * 64, creation_command),
        )
        uow.connection.execute(
            "INSERT INTO objective_aggregate_projection(objective_id,execution_state,aggregate_outcome,"
            "actual_start_utc,actual_end_utc,attention_reason,included_task_count,excluded_task_count,"
            "aggregate_input_fingerprint,revision,last_command_id) "
            "VALUES (?,'in_progress',NULL,?,NULL,NULL,1,0,?,2,?)",
            (objective_id, original.start_utc + 10, "b" * 64, creation_command),
        )

    replacement = _schedule(1_936_000_000, 1_936_003_600)
    preview = TaskPlanCorrectionQueryService(factory).preview(
        task_id=task.task_id,
        task_revision=1,
        current_plan_revision=int(plan_revision),
        current_plan_revision_id=str(plan_id),
        schedule=replacement,
    )
    assert preview.eligible
    assert preview.risk == "HIGH"
    assert preview.risk_reasons == ("PROTECTED_OBJECTIVE_HISTORY",)

    with ReadSnapshot(factory) as snapshot:
        before_membership = tuple(snapshot.connection.execute(
            "SELECT objective_id,accepted_plan_revision_id,membership_revision,last_event_id,last_command_id "
            "FROM objective_task_membership_current WHERE task_id=?",
            (task.task_id,),
        ).fetchone())
        before_envelope = tuple(snapshot.connection.execute(
            "SELECT start_utc,end_utc,member_count,membership_input_fingerprint,revision,last_command_id "
            "FROM objective_envelope_projection WHERE objective_id=?",
            (objective_id,),
        ).fetchone())
        before_aggregate = tuple(snapshot.connection.execute(
            "SELECT execution_state,aggregate_outcome,actual_start_utc,actual_end_utc,attention_reason,"
            "included_task_count,excluded_task_count,aggregate_input_fingerprint,revision,last_command_id "
            "FROM objective_aggregate_projection WHERE objective_id=?",
            (objective_id,),
        ).fetchone())
        assert snapshot.connection.execute(
            "SELECT count(*) FROM task_execution_events WHERE task_id=?", (task.task_id,)
        ).fetchone()[0] == 0

    command_id = new_uuid4()
    result = TaskPlanCorrectionService(factory).correct_task_plan(
        command_id=command_id,
        task_id=task.task_id,
        task_revision=1,
        current_plan_revision=int(plan_revision),
        current_plan_revision_id=str(plan_id),
        schedule=replacement,
        reason_category="reviewed_started_objective_correction",
        correction_review_fingerprint=preview.fingerprint,
        accept_high_risk=True,
    )
    assert result.outcome == "APPLIED"

    with ReadSnapshot(factory) as snapshot:
        assert tuple(snapshot.connection.execute(
            "SELECT objective_id,accepted_plan_revision_id,membership_revision,last_event_id,last_command_id "
            "FROM objective_task_membership_current WHERE task_id=?",
            (task.task_id,),
        ).fetchone()) == before_membership
        assert tuple(snapshot.connection.execute(
            "SELECT start_utc,end_utc,member_count,membership_input_fingerprint,revision,last_command_id "
            "FROM objective_envelope_projection WHERE objective_id=?",
            (objective_id,),
        ).fetchone()) == before_envelope
        assert tuple(snapshot.connection.execute(
            "SELECT execution_state,aggregate_outcome,actual_start_utc,actual_end_utc,attention_reason,"
            "included_task_count,excluded_task_count,aggregate_input_fingerprint,revision,last_command_id "
            "FROM objective_aggregate_projection WHERE objective_id=?",
            (objective_id,),
        ).fetchone()) == before_aggregate
        audit_payload = json.loads(str(snapshot.connection.execute(
            "SELECT payload_json FROM audit_events WHERE command_id=?", (command_id,)
        ).fetchone()[0]))
        assert audit_payload["review_risk"] == "HIGH"
        assert audit_payload["membership_plan_mismatch"] is True
