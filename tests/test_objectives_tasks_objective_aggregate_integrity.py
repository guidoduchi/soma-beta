from __future__ import annotations

import pytest

from soma.foundation.errors import IntegrityFailure
from soma.foundation.identifiers import new_uuid4
from soma.foundation.persistence.uow import UnitOfWork
from soma.objectives_tasks import AcceptedTaskSchedule, TaskPlanningService
from soma.objectives_tasks.repositories.objectives import ObjectiveProjectionRepository
from soma.objectives_tasks.services.task_execution import TaskExecutionService


TZ = "America/Guayaquil"


def _factory(initialized_database):
    database_path, factory_for_path = initialized_database
    return factory_for_path(database_path)


def _seed_member_objective(factory, *, ordinal: int):
    creation_command = new_uuid4()
    created = TaskPlanningService(factory).create_local_task(
        command_id=creation_command,
        local_task_name=f"Aggregate integrity {ordinal}",
        schedule=AcceptedTaskSchedule(
            start_utc=1_950_000_000 + ordinal * 10_000,
            end_utc=1_950_003_600 + ordinal * 10_000,
            scheduling_timezone_iana=TZ,
        ),
    )
    objective_id = new_uuid4()
    membership_event_id = new_uuid4()
    with UnitOfWork(factory) as uow:
        plan_row = uow.connection.execute(
            "SELECT pc.plan_revision_id,p.start_utc,p.end_utc "
            "FROM task_plan_current pc JOIN task_plan_revisions p ON p.plan_revision_id=pc.plan_revision_id "
            "WHERE pc.task_id=?",
            (created.task_id,),
        ).fetchone()
        assert plan_row is not None
        plan_id, start_utc, end_utc = str(plan_row[0]), int(plan_row[1]), int(plan_row[2])
        tracking_sequence = 98_000_000 + ordinal
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
            (membership_event_id, created.task_id, objective_id, plan_id, creation_command),
        )
        uow.connection.execute(
            "INSERT INTO objective_task_membership_current(task_id,objective_id,accepted_plan_revision_id,"
            "membership_revision,last_event_id,last_command_id) VALUES (?,?,?,1,?,?)",
            (created.task_id, objective_id, plan_id, membership_event_id, creation_command),
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
    return creation_command, created.task_id, objective_id, start_utc


def test_aggregate_rebuild_rejects_hidden_execution_history_without_projection(initialized_database) -> None:
    factory = _factory(initialized_database)
    creation_command, task_id, objective_id, start_utc = _seed_member_objective(factory, ordinal=1)
    hidden_event_id = new_uuid4()
    with UnitOfWork(factory) as uow:
        uow.connection.execute(
            "INSERT INTO task_execution_events(execution_event_id,task_id,event_kind,effective_at_utc,target_event_id,"
            "correction_action,reason_code,recorded_at_utc,command_id) VALUES (?,?,'start',?,NULL,NULL,NULL,2,?)",
            (hidden_event_id, task_id, start_utc + 10, creation_command),
        )

    with pytest.raises(IntegrityFailure, match="events exist without current projection"):
        with UnitOfWork(factory) as uow:
            ObjectiveProjectionRepository.rebuild_aggregate(
                uow,
                objective_id=objective_id,
                command_id=creation_command,
            )


def test_aggregate_rebuild_rejects_projection_that_does_not_point_to_latest_event(initialized_database) -> None:
    factory = _factory(initialized_database)
    creation_command, task_id, objective_id, start_utc = _seed_member_objective(factory, ordinal=2)
    started = TaskExecutionService(factory).start_task_execution(
        command_id=new_uuid4(),
        task_id=task_id,
        task_revision=1,
        execution_revision=0,
        effective_start_utc=start_utc + 10,
    )
    assert started.revision == 2

    trailing_event_id = new_uuid4()
    with UnitOfWork(factory) as uow:
        uow.connection.execute(
            "INSERT INTO task_execution_events(execution_event_id,task_id,event_kind,effective_at_utc,target_event_id,"
            "correction_action,reason_code,recorded_at_utc,command_id) VALUES (?,?,'end',?,NULL,NULL,NULL,2147483647,?)",
            (trailing_event_id, task_id, start_utc + 20, creation_command),
        )

    with pytest.raises(IntegrityFailure, match="latest immutable history"):
        with UnitOfWork(factory) as uow:
            ObjectiveProjectionRepository.rebuild_aggregate(
                uow,
                objective_id=objective_id,
                command_id=creation_command,
            )
