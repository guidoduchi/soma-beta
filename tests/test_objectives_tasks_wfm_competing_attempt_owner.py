from __future__ import annotations

import pytest

from soma.foundation.audit.writer import AuditWriter
from soma.foundation.errors import IntegrityFailure, SomaError
from soma.foundation.identifiers import new_uuid4
from soma.foundation.persistence.uow import ReadSnapshot, UnitOfWork
from soma.objectives_tasks.contracts.objectives_tasks import AcceptedTaskSchedule
from soma.objectives_tasks.queries.task_activity_review import WfmActivityRelationshipReviewQueryService
from soma.objectives_tasks.services.task_activity_review import (
    WfmActivityRelationshipReviewService,
    WfmActivityReviewCommandContext,
    WfmActivityReviewParticipant,
)
from soma.objectives_tasks.services.task_planning import TaskPlanningService
from soma.objectives_tasks.services.wfm_import import WfmImportReader
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


def _insert_outer_receipt(uow: UnitOfWork, *, command_id: str) -> str:
    proposal_id = new_uuid4()
    uow.connection.execute(
        "INSERT INTO command_receipts(command_id,command_type,request_hash,target_type,target_id,"
        "committed_at_utc,result_type,result_id) "
        "VALUES (?,'ResolveWfmCompetingAttemptReview',?,'reconciliation_proposal',?,0,NULL,NULL)",
        (command_id, "b" * 64, proposal_id),
    )
    return proposal_id


def _review_same_activity(factory, task_ids: tuple[str, ...]):
    query = WfmActivityRelationshipReviewQueryService(factory)
    preview = query.preview(seed_task_ids=task_ids, decision="same_activity")
    WfmActivityRelationshipReviewService(factory).review_wfm_activity_relationship(
        command_id=new_uuid4(),
        seed_tasks=tuple((seed.task_id, seed.task_revision) for seed in preview.seed_tasks),
        decision="same_activity",
        review_fingerprint=preview.review_fingerprint,
        reason_category="establish_reviewed_lineage",
    )


def _identity(factory, task_id: str) -> tuple[str, str, int]:
    with ReadSnapshot(factory) as snapshot:
        row = snapshot.connection.execute(
            "SELECT w.task_no,w.current_rfc_id,t.revision FROM wfm_task_identities w "
            "JOIN tasks t ON t.task_id=w.task_id WHERE w.task_id=?",
            (task_id,),
        ).fetchone()
        assert row is not None
        return str(row[0]), str(row[1]), int(row[2])


def test_activity_conflicts_binds_complete_hidden_set_and_deterministic_counterpart(initialized_database) -> None:
    factory = _factory(initialized_database)
    rfc_id = _create_rfc(factory, 901)
    starts = (2_100_000_000, 2_100_000_600, 2_100_001_200)
    registered = tuple(
        _register_wfm(factory, rfc_id=rfc_id, ordinal=901 + index, start_utc=start)
        for index, start in enumerate(starts)
    )
    task_ids = tuple(sorted(item.task_id for item in registered))
    _review_same_activity(factory, task_ids)
    subject_id = task_ids[0]
    subject_task_no, subject_rfc_id, _subject_revision = _identity(factory, subject_id)
    candidate = {"task_no": subject_task_no, "current_rfc_id": subject_rfc_id, "task_id": subject_id}
    interval = {"start_utc": 2_100_000_000, "end_utc": 2_100_003_600}

    with ReadSnapshot(factory) as snapshot:
        initial = WfmImportReader.activity_conflicts(snapshot.connection, candidate, interval, None)
    assert initial["classification"] == "SAME_REVIEWED_LINEAGE_OVERLAP"
    assert initial["exact_conflict_count"] == 2
    expected_suggestion = min(task_id for task_id in task_ids if task_id != subject_id)
    assert initial["suggested_counterpart_task_id"] == expected_suggestion
    assert initial["selected_counterpart"] is None

    with ReadSnapshot(factory) as snapshot:
        selected = WfmImportReader.activity_conflicts(
            snapshot.connection,
            candidate,
            interval,
            expected_suggestion,
        )
    assert selected["conflict_fingerprint"] == initial["conflict_fingerprint"]
    assert selected["selected_counterpart"]["task_id"] == expected_suggestion

    hidden_id = next(task_id for task_id in task_ids if task_id not in {subject_id, expected_suggestion})
    with ReadSnapshot(factory) as snapshot:
        row = snapshot.connection.execute(
            "SELECT t.revision,c.revision FROM tasks t JOIN task_plan_current c ON c.task_id=t.task_id "
            "WHERE t.task_id=?",
            (hidden_id,),
        ).fetchone()
        assert row is not None
        hidden_task_revision = int(row[0])
        hidden_plan_revision = int(row[1])
    moved = TaskPlanningService(factory).set_task_plan(
        command_id=new_uuid4(),
        task_id=hidden_id,
        task_revision=hidden_task_revision,
        current_plan_revision=hidden_plan_revision,
        schedule=AcceptedTaskSchedule(
            start_utc=2_100_020_000,
            end_utc=2_100_023_600,
            scheduling_timezone_iana="America/Guayaquil",
        ),
        reason_category="prove_complete_conflict_set_freshness",
    )
    assert moved.outcome == "APPLIED"

    with ReadSnapshot(factory) as snapshot:
        refreshed = WfmImportReader.activity_conflicts(
            snapshot.connection,
            candidate,
            interval,
            expected_suggestion,
        )
    assert refreshed["classification"] == "SAME_REVIEWED_LINEAGE_OVERLAP"
    assert refreshed["exact_conflict_count"] == 1
    assert refreshed["selected_counterpart"]["task_id"] == expected_suggestion
    assert refreshed["conflict_fingerprint"] != initial["conflict_fingerprint"]


def test_activity_conflicts_requires_reviewed_lineage_and_uses_strict_overlap(initialized_database) -> None:
    factory = _factory(initialized_database)
    rfc_id = _create_rfc(factory, 910)
    absent = {
        "task_no": "TK00000000009910",
        "current_rfc_id": rfc_id,
        "task_id": None,
    }
    with ReadSnapshot(factory) as snapshot:
        no_identity = WfmImportReader.activity_conflicts(
            snapshot.connection,
            absent,
            {"start_utc": 2_110_000_000, "end_utc": 2_110_003_600},
            None,
        )
    assert no_identity["classification"] == "NO_REVIEWED_LINEAGE"
    assert no_identity["subject_task_id"] is None

    first = _register_wfm(factory, rfc_id=rfc_id, ordinal=911, start_utc=2_110_000_000)
    second = _register_wfm(factory, rfc_id=rfc_id, ordinal=912, start_utc=2_110_003_600)
    task_ids = tuple(sorted((first.task_id, second.task_id)))
    subject_id = task_ids[0]
    task_no, current_rfc_id, _revision = _identity(factory, subject_id)
    candidate = {"task_no": task_no, "current_rfc_id": current_rfc_id, "task_id": subject_id}
    with ReadSnapshot(factory) as snapshot:
        before_review = WfmImportReader.activity_conflicts(
            snapshot.connection,
            candidate,
            {"start_utc": 2_110_000_000, "end_utc": 2_110_003_600},
            None,
        )
    assert before_review["classification"] == "NO_REVIEWED_LINEAGE"

    _review_same_activity(factory, task_ids)
    second_id = next(task_id for task_id in task_ids if task_id != subject_id)
    with ReadSnapshot(factory) as snapshot:
        row = snapshot.connection.execute(
            "SELECT p.start_utc,p.end_utc FROM task_plan_current c JOIN task_plan_revisions p "
            "ON p.plan_revision_id=c.plan_revision_id WHERE c.task_id=?",
            (second_id,),
        ).fetchone()
        assert row is not None
        second_start = int(row[0])
        second_end = int(row[1])
        touching = WfmImportReader.activity_conflicts(
            snapshot.connection,
            candidate,
            {"start_utc": second_end, "end_utc": second_end + 3_600},
            None,
        )
    assert second_start < second_end
    assert touching["classification"] == "CLEAR"
    assert touching["exact_conflict_count"] == 0


def test_activity_review_participant_applies_and_accepts_semantic_no_change(initialized_database) -> None:
    factory = _factory(initialized_database)
    rfc_id = _create_rfc(factory, 920)
    task_ids = tuple(sorted((
        _register_wfm(factory, rfc_id=rfc_id, ordinal=921, start_utc=2_120_000_000).task_id,
        _register_wfm(factory, rfc_id=rfc_id, ordinal=922, start_utc=2_120_001_000).task_id,
    )))
    query = WfmActivityRelationshipReviewQueryService(factory)
    preview = query.preview(seed_task_ids=task_ids, decision="same_activity")
    seed_pairs = tuple((seed.task_id, seed.task_revision) for seed in preview.seed_tasks)
    command_id = new_uuid4()
    with UnitOfWork(factory) as uow:
        _insert_outer_receipt(uow, command_id=command_id)
        applied = WfmActivityReviewParticipant.apply_reviewed_activity_relationship(
            uow,
            seed_tasks=seed_pairs,
            decision="same_activity",
            review_fingerprint=preview.review_fingerprint,
            reason_category="review_competing_attempt",
            command_context=WfmActivityReviewCommandContext(command_id=command_id),
        )
    assert applied.outcome == "APPLIED"
    assert applied.affected_task_count == 2
    assert applied.result_refs[0][0] == "task_activity_lineage_event"

    with ReadSnapshot(factory) as snapshot:
        assert snapshot.connection.execute(
            "SELECT count(*) FROM audit_events WHERE command_id=? AND action_type='task.activity_relationship_reviewed'",
            (command_id,),
        ).fetchone()[0] == 2
        assert snapshot.connection.execute(
            "SELECT count(DISTINCT activity_lineage_id) FROM task_activity_lineage_current "
            "WHERE task_id IN (?,?)",
            task_ids,
        ).fetchone()[0] == 1

    fresh = query.preview(seed_task_ids=task_ids, decision="same_activity")
    assert fresh.semantic_no_change
    fresh_pairs = tuple((seed.task_id, seed.task_revision) for seed in fresh.seed_tasks)
    no_change_command = new_uuid4()
    with UnitOfWork(factory) as uow:
        _insert_outer_receipt(uow, command_id=no_change_command)
        no_change = WfmActivityReviewParticipant.apply_reviewed_activity_relationship(
            uow,
            seed_tasks=fresh_pairs,
            decision="same_activity",
            review_fingerprint=fresh.review_fingerprint,
            reason_category="confirm_competing_attempt",
            command_context=WfmActivityReviewCommandContext(command_id=no_change_command),
        )
    assert no_change.outcome == "NO_CHANGE"
    assert no_change.result_refs == ()
    with ReadSnapshot(factory) as snapshot:
        assert snapshot.connection.execute(
            "SELECT count(*) FROM audit_events WHERE command_id=?",
            (no_change_command,),
        ).fetchone()[0] == 0


def test_activity_review_participant_stale_seed_rolls_back_outer_receipt(initialized_database) -> None:
    factory = _factory(initialized_database)
    rfc_id = _create_rfc(factory, 930)
    task_ids = tuple(sorted((
        _register_wfm(factory, rfc_id=rfc_id, ordinal=931).task_id,
        _register_wfm(factory, rfc_id=rfc_id, ordinal=932).task_id,
    )))
    query = WfmActivityRelationshipReviewQueryService(factory)
    preview = query.preview(seed_task_ids=task_ids, decision="same_activity")
    seed_pairs = tuple((seed.task_id, seed.task_revision) for seed in preview.seed_tasks)
    with UnitOfWork(factory) as uow:
        uow.connection.execute(
            "UPDATE tasks SET revision=revision+1 WHERE task_id=?",
            (task_ids[0],),
        )

    command_id = new_uuid4()
    with pytest.raises(SomaError) as caught:
        with UnitOfWork(factory) as uow:
            _insert_outer_receipt(uow, command_id=command_id)
            WfmActivityReviewParticipant.apply_reviewed_activity_relationship(
                uow,
                seed_tasks=seed_pairs,
                decision="same_activity",
                review_fingerprint=preview.review_fingerprint,
                reason_category="stale_competing_attempt",
                command_context=WfmActivityReviewCommandContext(command_id=command_id),
            )
    assert caught.value.code == "TASK_STALE"
    with ReadSnapshot(factory) as snapshot:
        assert snapshot.connection.execute(
            "SELECT 1 FROM command_receipts WHERE command_id=?",
            (command_id,),
        ).fetchone() is None


def test_activity_review_participant_audit_failure_rolls_back_everything(initialized_database, monkeypatch) -> None:
    factory = _factory(initialized_database)
    rfc_id = _create_rfc(factory, 940)
    task_ids = tuple(sorted((
        _register_wfm(factory, rfc_id=rfc_id, ordinal=941).task_id,
        _register_wfm(factory, rfc_id=rfc_id, ordinal=942).task_id,
    )))
    query = WfmActivityRelationshipReviewQueryService(factory)
    preview = query.preview(seed_task_ids=task_ids, decision="same_activity")
    seed_pairs = tuple((seed.task_id, seed.task_revision) for seed in preview.seed_tasks)
    command_id = new_uuid4()

    original_write = AuditWriter.write
    writes = 0

    def fail_second_write(self, uow, event):
        nonlocal writes
        writes += 1
        if writes == 2:
            raise IntegrityFailure("injected participant audit failure")
        return original_write(self, uow, event)

    monkeypatch.setattr(AuditWriter, "write", fail_second_write)
    with pytest.raises(IntegrityFailure):
        with UnitOfWork(factory) as uow:
            _insert_outer_receipt(uow, command_id=command_id)
            WfmActivityReviewParticipant.apply_reviewed_activity_relationship(
                uow,
                seed_tasks=seed_pairs,
                decision="same_activity",
                review_fingerprint=preview.review_fingerprint,
                reason_category="audit_failure_injection",
                command_context=WfmActivityReviewCommandContext(command_id=command_id),
            )

    with ReadSnapshot(factory) as snapshot:
        revisions = snapshot.connection.execute(
            "SELECT task_id,revision FROM tasks WHERE task_id IN (?,?) ORDER BY task_id",
            task_ids,
        ).fetchall()
        assert [(str(row[0]), int(row[1])) for row in revisions] == [
            (task_ids[0], 1),
            (task_ids[1], 1),
        ]
        assert snapshot.connection.execute(
            "SELECT count(*) FROM task_activity_lineage_events WHERE command_id=?",
            (command_id,),
        ).fetchone()[0] == 0
        assert snapshot.connection.execute(
            "SELECT count(*) FROM task_activity_lineage_current WHERE task_id IN (?,?)",
            task_ids,
        ).fetchone()[0] == 0
        assert snapshot.connection.execute(
            "SELECT count(*) FROM audit_events WHERE command_id=?",
            (command_id,),
        ).fetchone()[0] == 0
        assert snapshot.connection.execute(
            "SELECT 1 FROM command_receipts WHERE command_id=?",
            (command_id,),
        ).fetchone() is None
