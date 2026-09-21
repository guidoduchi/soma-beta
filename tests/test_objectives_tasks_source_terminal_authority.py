from __future__ import annotations

from soma.foundation.identifiers import new_uuid4
from soma.foundation.persistence.uow import ReadSnapshot, UnitOfWork
from soma.objectives_tasks import AcceptedTaskSchedule, TaskPlanningService
from soma.objectives_tasks.services.task_explicit_lock import TaskExplicitLockService
from soma.objectives_tasks.source_terminal_authority import (
    WfmSourceProjectionMutation,
    WfmSourceProjectionParticipant,
    source_terminal_review_fingerprint,
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


def _register_wfm(factory, *, suffix: int, scheduled: bool):
    schedule = (
        AcceptedTaskSchedule(
            start_utc=2_020_000_000 + suffix * 10_000,
            end_utc=2_020_003_600 + suffix * 10_000,
            scheduling_timezone_iana=TZ,
        )
        if scheduled
        else None
    )
    return TaskPlanningService(factory).register_manual_wfm_task(
        command_id=new_uuid4(),
        task_no=f"TK{suffix:014d}",
        rfc_id=_create_rfc(factory, suffix),
        schedule=schedule,
    )


def _insert_outer_receipt(uow: UnitOfWork, *, command_id: str, target_id: str) -> None:
    uow.connection.execute(
        "INSERT INTO command_receipts(command_id,command_type,request_hash,target_type,target_id,"
        "committed_at_utc,result_type,result_id) "
        "VALUES (?,'AcceptReconciliationProposal',?,'reconciliation_proposal',?,0,NULL,NULL)",
        (command_id, "a" * 64, target_id),
    )


def _apply_source(
    factory,
    *,
    task_id: str,
    expected_revision: int,
    lifecycle: str,
    observation_id: str | None,
    command_id: str,
    status_token: str = "Complete",
):
    with UnitOfWork(factory) as uow:
        _insert_outer_receipt(uow, command_id=command_id, target_id=new_uuid4())
        result = WfmSourceProjectionParticipant.apply_wfm_source_projection(
            uow,
            WfmSourceProjectionMutation(
                task_id=task_id,
                expected_source_projection_revision=expected_revision,
                provider_status_token=status_token,
                provider_lifecycle_class=lifecycle,
                source_plan_start_utc=2_020_100_000,
                source_plan_end_utc=2_020_103_600,
                accepted_source_observation_id=observation_id,
                source_base_token=("b" if expected_revision == 0 else "c") * 64,
            ),
            command_id=command_id,
        )
    return result


def test_terminal_source_without_local_work_does_not_fabricate_review(initialized_database) -> None:
    factory = _factory(initialized_database)
    task = _register_wfm(factory, suffix=101, scheduled=False)
    command_id = new_uuid4()
    observation_id = new_uuid4()

    result = _apply_source(
        factory,
        task_id=task.task_id,
        expected_revision=0,
        lifecycle="complete",
        observation_id=observation_id,
        command_id=command_id,
    )

    assert result.source_projection_revision == 1
    assert result.source_terminal_review_id is None
    assert result.source_terminal_review_fingerprint is None
    assert result.result_refs == ()
    with ReadSnapshot(factory) as snapshot:
        projection = snapshot.connection.execute(
            "SELECT provider_lifecycle_class,accepted_source_observation_id,source_projection_revision,"
            "last_command_id FROM wfm_source_projection_cache WHERE task_id=?",
            (task.task_id,),
        ).fetchone()
        assert tuple(projection) == ("complete", observation_id, 1, command_id)
        assert snapshot.connection.execute(
            "SELECT count(*) FROM wfm_source_terminal_reviews WHERE task_id=?",
            (task.task_id,),
        ).fetchone()[0] == 0
        assert snapshot.connection.execute(
            "SELECT count(*) FROM command_receipts WHERE command_id=?",
            (command_id,),
        ).fetchone()[0] == 1


def test_terminal_source_with_operational_plan_creates_exact_pending_review_in_outer_uow(
    initialized_database,
) -> None:
    factory = _factory(initialized_database)
    task = _register_wfm(factory, suffix=102, scheduled=True)
    before_task_revision = task.revision
    command_id = new_uuid4()
    observation_id = new_uuid4()

    result = _apply_source(
        factory,
        task_id=task.task_id,
        expected_revision=0,
        lifecycle="complete",
        observation_id=observation_id,
        command_id=command_id,
    )

    assert result.source_projection_revision == 1
    assert result.source_terminal_review_id is not None
    assert result.source_terminal_review_fingerprint is not None
    assert result.result_refs == (
        ("wfm_source_terminal_review", result.source_terminal_review_id),
    )
    with ReadSnapshot(factory) as snapshot:
        assert source_terminal_review_fingerprint(snapshot.connection, task.task_id) == result.source_terminal_review_fingerprint
        review = snapshot.connection.execute(
            "SELECT source_projection_revision,provider_lifecycle_class,input_fingerprint,state,revision,"
            "local_consequence_event_id,decided_at_utc,last_command_id "
            "FROM wfm_source_terminal_reviews WHERE source_terminal_review_id=?",
            (result.source_terminal_review_id,),
        ).fetchone()
        assert tuple(review) == (
            1,
            "complete",
            result.source_terminal_review_fingerprint,
            "pending",
            1,
            None,
            None,
            command_id,
        )
        assert snapshot.connection.execute(
            "SELECT revision FROM tasks WHERE task_id=?",
            (task.task_id,),
        ).fetchone()[0] == before_task_revision
        assert snapshot.connection.execute(
            "SELECT count(*) FROM command_receipts WHERE command_id=?",
            (command_id,),
        ).fetchone()[0] == 1
        assert snapshot.connection.execute(
            "SELECT count(*) FROM audit_events WHERE command_id=?",
            (command_id,),
        ).fetchone()[0] == 0


def test_new_terminal_source_projection_supersedes_old_pending_review_and_preserves_history(
    initialized_database,
) -> None:
    factory = _factory(initialized_database)
    task = _register_wfm(factory, suffix=103, scheduled=True)
    first_command = new_uuid4()
    first = _apply_source(
        factory,
        task_id=task.task_id,
        expected_revision=0,
        lifecycle="complete",
        observation_id=new_uuid4(),
        command_id=first_command,
    )
    assert first.source_terminal_review_id is not None

    second_command = new_uuid4()
    second = _apply_source(
        factory,
        task_id=task.task_id,
        expected_revision=1,
        lifecycle="plan_cancel",
        observation_id=new_uuid4(),
        command_id=second_command,
        status_token="Plan Cancel",
    )
    assert second.source_terminal_review_id is not None
    assert second.source_terminal_review_id != first.source_terminal_review_id
    assert second.source_projection_revision == 2

    with ReadSnapshot(factory) as snapshot:
        old = snapshot.connection.execute(
            "SELECT source_projection_revision,provider_lifecycle_class,input_fingerprint,state,revision,"
            "local_consequence_event_id,last_command_id FROM wfm_source_terminal_reviews "
            "WHERE source_terminal_review_id=?",
            (first.source_terminal_review_id,),
        ).fetchone()
        assert tuple(old[:5]) == (
            1,
            "complete",
            first.source_terminal_review_fingerprint,
            "superseded",
            2,
        )
        assert old[5] is None
        assert old[6] == second_command

        current = snapshot.connection.execute(
            "SELECT source_projection_revision,provider_lifecycle_class,input_fingerprint,state,revision "
            "FROM wfm_source_terminal_reviews WHERE source_terminal_review_id=?",
            (second.source_terminal_review_id,),
        ).fetchone()
        assert tuple(current) == (
            2,
            "plan_cancel",
            second.source_terminal_review_fingerprint,
            "pending",
            1,
        )
        assert snapshot.connection.execute(
            "SELECT count(*) FROM wfm_source_terminal_reviews WHERE task_id=? AND state='pending'",
            (task.task_id,),
        ).fetchone()[0] == 1


def test_review_fingerprint_changes_when_explicit_local_lock_authority_changes(initialized_database) -> None:
    factory = _factory(initialized_database)
    task = _register_wfm(factory, suffix=104, scheduled=True)
    result = _apply_source(
        factory,
        task_id=task.task_id,
        expected_revision=0,
        lifecycle="complete",
        observation_id=new_uuid4(),
        command_id=new_uuid4(),
    )
    assert result.source_terminal_review_fingerprint is not None

    locked = TaskExplicitLockService(factory).set_explicit_task_lock(
        command_id=new_uuid4(),
        task_id=task.task_id,
        task_revision=task.revision,
        lock_projection_revision=0,
        lock_kind="membership",
        action="lock",
        reason_category="protect_terminal_review_context",
    )
    assert locked.outcome == "APPLIED"

    with ReadSnapshot(factory) as snapshot:
        refreshed = source_terminal_review_fingerprint(snapshot.connection, task.task_id)
        assert refreshed != result.source_terminal_review_fingerprint
        pending = snapshot.connection.execute(
            "SELECT input_fingerprint,state FROM wfm_source_terminal_reviews "
            "WHERE source_terminal_review_id=?",
            (result.source_terminal_review_id,),
        ).fetchone()
        assert tuple(pending) == (result.source_terminal_review_fingerprint, "pending")


def test_participant_requires_caller_owned_receipt_and_rolls_back_with_outer_uow(initialized_database) -> None:
    factory = _factory(initialized_database)
    task = _register_wfm(factory, suffix=105, scheduled=True)
    command_id = new_uuid4()

    try:
        with UnitOfWork(factory) as uow:
            _insert_outer_receipt(uow, command_id=command_id, target_id=new_uuid4())
            result = WfmSourceProjectionParticipant.apply_wfm_source_projection(
                uow,
                WfmSourceProjectionMutation(
                    task_id=task.task_id,
                    expected_source_projection_revision=0,
                    provider_status_token="Complete",
                    provider_lifecycle_class="complete",
                    source_plan_start_utc=None,
                    source_plan_end_utc=None,
                    accepted_source_observation_id=new_uuid4(),
                    source_base_token="d" * 64,
                ),
                command_id=command_id,
            )
            assert result.source_terminal_review_id is not None
            raise RuntimeError("inject outer failure")
    except RuntimeError as exc:
        assert str(exc) == "inject outer failure"

    with ReadSnapshot(factory) as snapshot:
        assert snapshot.connection.execute(
            "SELECT count(*) FROM command_receipts WHERE command_id=?",
            (command_id,),
        ).fetchone()[0] == 0
        assert snapshot.connection.execute(
            "SELECT count(*) FROM wfm_source_projection_cache WHERE task_id=?",
            (task.task_id,),
        ).fetchone()[0] == 0
        assert snapshot.connection.execute(
            "SELECT count(*) FROM wfm_source_terminal_reviews WHERE task_id=?",
            (task.task_id,),
        ).fetchone()[0] == 0
