from __future__ import annotations

from soma.foundation.identifiers import new_uuid4
from soma.foundation.persistence.uow import ReadSnapshot, UnitOfWork
from soma.objectives_tasks import AcceptedTaskSchedule, TaskPlanningService
from soma.objectives_tasks.queries.execution_review import TaskOutcomeReviewQueryService
from soma.objectives_tasks.queries.tasks import TaskOperationalEvidenceReader
from soma.objectives_tasks.services.task_execution import TaskExecutionService
from soma.objectives_tasks.services.task_review import TaskReviewService


TZ = "America/Guayaquil"


def _factory(initialized_database):
    database_path, builder = initialized_database
    return builder(database_path)


def _scheduled_task(factory):
    return TaskPlanningService(factory).create_local_task(
        command_id=new_uuid4(),
        local_task_name="Operational evidence",
        schedule=AcceptedTaskSchedule(
            start_utc=1_990_000_000,
            end_utc=1_990_003_600,
            scheduling_timezone_iana=TZ,
        ),
    )


def test_task_operational_evidence_exact_absence_and_writer_reader_match(
    initialized_database,
) -> None:
    factory = _factory(initialized_database)
    created = _scheduled_task(factory)
    reader = TaskOperationalEvidenceReader()

    with ReadSnapshot(factory) as snapshot:
        execution = reader.task_execution(snapshot, created.task_id)
        outcome = reader.task_outcome(snapshot, created.task_id)
        objective = reader.objective_context(snapshot, created.task_id)
        stable_fingerprint = reader.review_fingerprint(snapshot, created.task_id)

    assert execution == {
        "execution_revision": 0,
        "execution_state": "not_started",
        "actual_start_utc": None,
        "actual_end_utc": None,
        "effective_termination_utc": None,
        "termination_reason": None,
        "last_event_id": None,
    }
    assert outcome is None
    assert objective is None

    with UnitOfWork(factory) as uow:
        assert reader.review_fingerprint(uow, created.task_id) == stable_fingerprint


def test_task_operational_fingerprint_changes_with_execution_and_reviewed_outcome(
    initialized_database,
) -> None:
    factory = _factory(initialized_database)
    created = _scheduled_task(factory)
    reader = TaskOperationalEvidenceReader()
    with ReadSnapshot(factory) as snapshot:
        initial = reader.review_fingerprint(snapshot, created.task_id)

    execution = TaskExecutionService(factory)
    started = execution.start_task_execution(
        command_id=new_uuid4(),
        task_id=created.task_id,
        task_revision=created.revision,
        execution_revision=0,
        effective_start_utc=1_990_000_100,
    )
    ended = execution.end_task_execution(
        command_id=new_uuid4(),
        task_id=created.task_id,
        task_revision=started.revision,
        execution_revision=1,
        effective_end_utc=1_990_000_200,
    )
    with ReadSnapshot(factory) as snapshot:
        after_execution = reader.review_fingerprint(snapshot, created.task_id)
        execution_object = reader.task_execution(snapshot, created.task_id)
    assert after_execution != initial
    assert execution_object["execution_revision"] == 2
    assert execution_object["execution_state"] == "ended"

    preview = TaskOutcomeReviewQueryService(factory).preview(
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
        outcome_review_fingerprint=preview.outcome_review_fingerprint,
    )
    with ReadSnapshot(factory) as snapshot:
        after_outcome = reader.review_fingerprint(snapshot, created.task_id)
        outcome = reader.task_outcome(snapshot, created.task_id)
    assert after_outcome != after_execution
    assert outcome is not None
    assert outcome["accepted_outcome"] == "completed"
    assert outcome["outcome_revision"] == 1
    assert outcome["outcome_event_id"] == reviewed.result_refs[0].result_id


def test_task_operational_fingerprint_changes_with_objective_context(
    initialized_database,
) -> None:
    factory = _factory(initialized_database)
    created = _scheduled_task(factory)
    reader = TaskOperationalEvidenceReader()
    with ReadSnapshot(factory) as snapshot:
        before = reader.review_fingerprint(snapshot, created.task_id)
        plan_id = str(
            snapshot.connection.execute(
                "SELECT plan_revision_id FROM task_plan_current WHERE task_id=?",
                (created.task_id,),
            ).fetchone()[0]
        )

    command_id = new_uuid4()
    objective_id = new_uuid4()
    membership_event_id = new_uuid4()
    with UnitOfWork(factory) as uow:
        uow.connection.execute(
            "INSERT INTO command_receipts("
            "command_id,command_type,request_hash,target_type,target_id,committed_at_utc,"
            "result_type,result_id"
            ") VALUES (?,'TestOperationalEvidenceObjective',?,'objective',?,1,NULL,NULL)",
            (command_id, "a" * 64, objective_id),
        )
        uow.connection.execute(
            "INSERT INTO objectives("
            "objective_id,tracking_sequence,tracking_id,creation_origin,"
            "superseded_by_objective_id,revision,created_at_utc,created_command_id"
            ") VALUES (?,99000001,'MW-99000001','manual',NULL,1,1,?)",
            (objective_id, command_id),
        )
        uow.connection.execute(
            "INSERT INTO objective_membership_events("
            "membership_event_id,task_id,event_kind,from_objective_id,to_objective_id,"
            "accepted_plan_revision_id,grouping_proposal_id,reason_code,recorded_at_utc,command_id"
            ") VALUES (?,?,'add',NULL,?,?,NULL,NULL,1,?)",
            (membership_event_id, created.task_id, objective_id, plan_id, command_id),
        )
        uow.connection.execute(
            "INSERT INTO objective_task_membership_current("
            "task_id,objective_id,accepted_plan_revision_id,membership_revision,last_event_id,last_command_id"
            ") VALUES (?,?,?,1,?,?)",
            (created.task_id, objective_id, plan_id, membership_event_id, command_id),
        )
        uow.connection.execute(
            "INSERT INTO objective_envelope_projection("
            "objective_id,start_utc,end_utc,member_count,membership_input_fingerprint,revision,last_command_id"
            ") VALUES (?,1990000000,1990003600,1,?,1,?)",
            (objective_id, "b" * 64, command_id),
        )
        uow.connection.execute(
            "INSERT INTO objective_aggregate_projection("
            "objective_id,execution_state,aggregate_outcome,actual_start_utc,actual_end_utc,"
            "attention_reason,included_task_count,excluded_task_count,aggregate_input_fingerprint,"
            "revision,last_command_id"
            ") VALUES (?,'planned',NULL,NULL,NULL,NULL,1,0,?,1,?)",
            (objective_id, "c" * 64, command_id),
        )

    with ReadSnapshot(factory) as snapshot:
        after = reader.review_fingerprint(snapshot, created.task_id)
        context = reader.objective_context(snapshot, created.task_id)
    assert after != before
    assert context is not None
    assert context["objective_id"] == objective_id
    assert context["membership_revision"] == 1
    assert context["accepted_plan_revision_id"] == plan_id
