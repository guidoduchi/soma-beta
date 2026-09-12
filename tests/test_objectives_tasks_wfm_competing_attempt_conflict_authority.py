from __future__ import annotations

import pytest

from soma.foundation.errors import SomaError
from soma.foundation.identifiers import new_uuid4
from soma.foundation.persistence.uow import ReadSnapshot, UnitOfWork
from soma.objectives_tasks.contracts.objectives_tasks import AcceptedTaskSchedule
from soma.objectives_tasks.queries.task_activity_review import WfmActivityRelationshipReviewQueryService
from soma.objectives_tasks.services.task_activity_review import WfmActivityRelationshipReviewService
from soma.objectives_tasks.services.task_execution import TaskExecutionService
from soma.objectives_tasks.services.task_planning import TaskPlanningService
from soma.objectives_tasks.services.wfm_import import (
    WfmImportBaseTarget,
    WfmImportMutationParticipant,
    WfmImportReader,
    WfmSourceProjectionAcceptanceMutation,
)
from soma.tickets.rfcs import RfcService


def _factory(initialized_database):
    database_path, factory_for_path = initialized_database
    return factory_for_path(database_path)


def _create_rfc(factory, ordinal: int) -> str:
    return RfcService(factory).create_or_adopt_identity(
        command_id=new_uuid4(),
        rfc_no=f"NC{ordinal:014d}",
        creation_context="provisional",
    ).rfc_id


def _register_wfm(factory, *, rfc_id: str, ordinal: int, start_utc: int | None = None):
    schedule = None
    if start_utc is not None:
        schedule = AcceptedTaskSchedule(
            start_utc=start_utc,
            end_utc=start_utc + 3_600,
            scheduling_timezone_iana="America/Guayaquil",
        )
    return TaskPlanningService(factory).register_manual_wfm_task(
        command_id=new_uuid4(),
        task_no=f"TK{ordinal:014d}",
        rfc_id=rfc_id,
        schedule=schedule,
    )


def _review_same_activity(factory, task_ids: tuple[str, str]) -> None:
    query = WfmActivityRelationshipReviewQueryService(factory)
    preview = query.preview(seed_task_ids=task_ids, decision="same_activity")
    WfmActivityRelationshipReviewService(factory).review_wfm_activity_relationship(
        command_id=new_uuid4(),
        seed_tasks=tuple((seed.task_id, seed.task_revision) for seed in preview.seed_tasks),
        decision="same_activity",
        review_fingerprint=preview.review_fingerprint,
        reason_category="establish_reviewed_lineage",
    )


def _current_identity(factory, task_id: str) -> tuple[str, str, int]:
    with ReadSnapshot(factory) as snapshot:
        row = snapshot.connection.execute(
            "SELECT w.task_no,w.current_rfc_id,t.revision FROM wfm_task_identities w "
            "JOIN tasks t ON t.task_id=w.task_id WHERE w.task_id=?",
            (task_id,),
        ).fetchone()
        assert row is not None
        return str(row[0]), str(row[1]), int(row[2])


def _insert_outer_receipt(uow: UnitOfWork, *, command_id: str) -> None:
    uow.connection.execute(
        "INSERT INTO command_receipts(command_id,command_type,request_hash,target_type,target_id,"
        "committed_at_utc,result_type,result_id) "
        "VALUES (?,'AcceptReconciliationProposal',?,'reconciliation_proposal',?,0,NULL,NULL)",
        (command_id, "c" * 64, new_uuid4()),
    )


def _apply_source_plan(
    factory,
    *,
    task_id: str,
    task_no: str,
    start_utc: int,
    end_utc: int,
) -> None:
    with ReadSnapshot(factory) as snapshot:
        base_token = WfmImportReader.source_acceptance_base_token(
            snapshot.connection,
            WfmImportBaseTarget("wfm_source_projection", task_no, task_id),
        )
    command_id = new_uuid4()
    with UnitOfWork(factory) as uow:
        _insert_outer_receipt(uow, command_id=command_id)
        result = WfmImportMutationParticipant.apply_wfm_source_projection(
            uow,
            WfmSourceProjectionAcceptanceMutation(
                task_id=task_id,
                task_no=task_no,
                expected_source_projection_revision=0,
                provider_status_token="Implementation",
                provider_lifecycle_class="active",
                source_plan_start_utc=start_utc,
                source_plan_end_utc=end_utc,
                accepted_source_observation_id=new_uuid4(),
                base_state_token=base_token,
                accepted_command_id=command_id,
            ),
        )
        assert result.source_projection_revision == 1


def test_terminal_execution_removes_counterpart_and_stales_selected_conflict(initialized_database) -> None:
    factory = _factory(initialized_database)
    rfc_id = _create_rfc(factory, 951)
    first = _register_wfm(factory, rfc_id=rfc_id, ordinal=951, start_utc=2_150_000_000)
    second = _register_wfm(factory, rfc_id=rfc_id, ordinal=952, start_utc=2_150_000_600)
    task_ids = tuple(sorted((first.task_id, second.task_id)))
    _review_same_activity(factory, task_ids)

    subject_id = task_ids[0]
    counterpart_id = task_ids[1]
    task_no, current_rfc_id, _subject_revision = _current_identity(factory, subject_id)
    candidate = {"task_no": task_no, "current_rfc_id": current_rfc_id, "task_id": subject_id}
    interval = {"start_utc": 2_150_000_000, "end_utc": 2_150_004_200}
    with ReadSnapshot(factory) as snapshot:
        before = WfmImportReader.activity_conflicts(
            snapshot.connection,
            candidate,
            interval,
            counterpart_id,
        )
    assert before["classification"] == "SAME_REVIEWED_LINEAGE_OVERLAP"
    assert before["exact_conflict_count"] == 1
    assert before["selected_counterpart"]["task_id"] == counterpart_id

    _counterpart_no, _counterpart_rfc, task_revision = _current_identity(factory, counterpart_id)
    execution = TaskExecutionService(factory)
    started = execution.start_task_execution(
        command_id=new_uuid4(),
        task_id=counterpart_id,
        task_revision=task_revision,
        execution_revision=0,
        effective_start_utc=2_150_000_700,
    )
    assert started.outcome == "APPLIED"
    ended = execution.end_task_execution(
        command_id=new_uuid4(),
        task_id=counterpart_id,
        task_revision=started.revision,
        execution_revision=1,
        effective_end_utc=2_150_000_800,
    )
    assert ended.outcome == "APPLIED"

    with ReadSnapshot(factory) as snapshot:
        after = WfmImportReader.activity_conflicts(snapshot.connection, candidate, interval, None)
        with pytest.raises(SomaError) as caught:
            WfmImportReader.activity_conflicts(
                snapshot.connection,
                candidate,
                interval,
                counterpart_id,
            )
    assert after["classification"] == "CLEAR"
    assert after["exact_conflict_count"] == 0
    assert after["conflict_fingerprint"] != before["conflict_fingerprint"]
    assert caught.value.code == "TASK_STALE"


def test_source_plan_fallback_yields_to_current_operational_plan(initialized_database) -> None:
    factory = _factory(initialized_database)
    rfc_id = _create_rfc(factory, 960)
    first = _register_wfm(factory, rfc_id=rfc_id, ordinal=961)
    second = _register_wfm(factory, rfc_id=rfc_id, ordinal=962)
    task_ids = tuple(sorted((first.task_id, second.task_id)))
    _review_same_activity(factory, task_ids)

    subject_id = task_ids[0]
    counterpart_id = task_ids[1]
    subject_no, subject_rfc_id, _subject_revision = _current_identity(factory, subject_id)
    counterpart_no, _counterpart_rfc_id, counterpart_revision = _current_identity(factory, counterpart_id)
    source_start = 2_160_000_000
    source_end = 2_160_003_600
    _apply_source_plan(
        factory,
        task_id=subject_id,
        task_no=subject_no,
        start_utc=source_start,
        end_utc=source_end,
    )
    _apply_source_plan(
        factory,
        task_id=counterpart_id,
        task_no=counterpart_no,
        start_utc=source_start + 600,
        end_utc=source_end + 600,
    )

    candidate = {"task_no": subject_no, "current_rfc_id": subject_rfc_id, "task_id": subject_id}
    interval = {"start_utc": source_start, "end_utc": source_end}
    with ReadSnapshot(factory) as snapshot:
        source_conflict = WfmImportReader.activity_conflicts(
            snapshot.connection,
            candidate,
            interval,
            counterpart_id,
        )
    assert source_conflict["classification"] == "SAME_REVIEWED_LINEAGE_OVERLAP"
    assert source_conflict["selected_counterpart"]["task_id"] == counterpart_id

    moved = TaskPlanningService(factory).set_task_plan(
        command_id=new_uuid4(),
        task_id=counterpart_id,
        task_revision=counterpart_revision,
        current_plan_revision=0,
        schedule=AcceptedTaskSchedule(
            start_utc=2_160_020_000,
            end_utc=2_160_023_600,
            scheduling_timezone_iana="America/Guayaquil",
        ),
        reason_category="prove_operational_plan_precedence",
    )
    assert moved.outcome == "APPLIED"

    with ReadSnapshot(factory) as snapshot:
        operational_clear = WfmImportReader.activity_conflicts(
            snapshot.connection,
            candidate,
            interval,
            None,
        )
    assert operational_clear["classification"] == "CLEAR"
    assert operational_clear["exact_conflict_count"] == 0
    assert operational_clear["conflict_fingerprint"] != source_conflict["conflict_fingerprint"]
