from __future__ import annotations

import pytest

from soma.foundation.errors import IntegrityFailure, SomaError, ValidationError
from soma.foundation.identifiers import new_uuid4
from soma.foundation.persistence.uow import ReadSnapshot, UnitOfWork
from soma.objectives_tasks.contracts.objectives_tasks import AcceptedTaskSchedule
from soma.objectives_tasks.queries.task_activity_review import WfmActivityRelationshipReviewQueryService
from soma.objectives_tasks.services.task_activity_review import WfmActivityRelationshipReviewService
from soma.objectives_tasks.services.task_planning import TaskPlanningService
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


def _register_wfm(factory, *, rfc_id: str, ordinal: int, start: int | None = None) -> str:
    schedule = None
    if start is not None:
        schedule = AcceptedTaskSchedule(
            start_utc=start,
            end_utc=start + 3_600,
            scheduling_timezone_iana="America/Guayaquil",
        )
    return TaskPlanningService(factory).register_manual_wfm_task(
        command_id=new_uuid4(),
        task_no=f"TK{ordinal:014d}",
        rfc_id=rfc_id,
        schedule=schedule,
    ).task_id


def _seed_pairs(preview) -> tuple[tuple[str, int], ...]:
    return tuple((seed.task_id, seed.task_revision) for seed in preview.seed_tasks)


def _insert_retry_edge(factory, predecessor_id: str, successor_id: str) -> str:
    relation_id = new_uuid4()
    command_id = new_uuid4()
    with UnitOfWork(factory) as uow:
        uow.connection.execute(
            "INSERT INTO command_receipts(command_id,command_type,request_hash,target_type,target_id,committed_at_utc,result_type,result_id) "
            "VALUES (?, 'LinkWfmRetryAttempt', ?, 'task', ?, 0, 'task_retry_relation', ?)",
            (command_id, "0" * 64, predecessor_id, relation_id),
        )
        uow.connection.execute(
            "INSERT INTO task_retry_relations(retry_relation_id,predecessor_task_id,successor_task_id,created_at_utc,command_id) "
            "VALUES (?,?,?,?,?)",
            (relation_id, predecessor_id, successor_id, 0, command_id),
        )
    return relation_id


def test_distinct_activity_review_is_atomic_replayable_and_semantic_no_change(initialized_database) -> None:
    factory = _factory(initialized_database)
    rfc_id = _create_rfc(factory, 1)
    task_ids = tuple(sorted((
        _register_wfm(factory, rfc_id=rfc_id, ordinal=1),
        _register_wfm(factory, rfc_id=rfc_id, ordinal=2),
    )))
    query = WfmActivityRelationshipReviewQueryService(factory)
    service = WfmActivityRelationshipReviewService(factory)

    preview = query.preview(seed_task_ids=task_ids, decision="distinct_activity")
    assert preview.affected_task_count == 2
    assert not preview.semantic_no_change
    assert not preview.projected_competing_attempt

    command_id = new_uuid4()
    applied = service.review_wfm_activity_relationship(
        command_id=command_id,
        seed_tasks=_seed_pairs(preview),
        decision="distinct_activity",
        review_fingerprint=preview.review_fingerprint,
        reason_category="operator_review",
    )
    assert applied.outcome == "APPLIED"
    assert applied.affected_task_count == 2
    assert not applied.replayed

    replayed = service.review_wfm_activity_relationship(
        command_id=command_id,
        seed_tasks=_seed_pairs(preview),
        decision="distinct_activity",
        review_fingerprint=preview.review_fingerprint,
        reason_category="operator_review",
    )
    assert replayed.replayed
    assert replayed.outcome == applied.outcome
    assert replayed.decision == applied.decision
    assert replayed.review_fingerprint == applied.review_fingerprint
    assert replayed.affected_task_count == applied.affected_task_count
    assert replayed.result_refs == applied.result_refs

    with ReadSnapshot(factory) as snapshot:
        rows = snapshot.connection.execute(
            "SELECT t.task_id,t.revision,c.activity_lineage_id,c.revision,e.reason_code "
            "FROM tasks t JOIN task_activity_lineage_current c ON c.task_id=t.task_id "
            "JOIN task_activity_lineage_events e ON e.lineage_event_id=c.last_event_id "
            "WHERE t.task_id IN (?,?) ORDER BY t.task_id",
            task_ids,
        ).fetchall()
        assert len(rows) == 2
        assert [int(row[1]) for row in rows] == [2, 2]
        assert [int(row[3]) for row in rows] == [1, 1]
        assert len({str(row[2]) for row in rows}) == 2
        assert [str(row[4]) for row in rows] == ["distinct_activity", "distinct_activity"]
        assert snapshot.connection.execute(
            "SELECT count(*) FROM audit_events WHERE command_id=? AND action_type='task.activity_relationship_reviewed'",
            (command_id,),
        ).fetchone()[0] == 2

    fresh = query.preview(seed_task_ids=task_ids, decision="distinct_activity")
    assert fresh.semantic_no_change
    no_change_command = new_uuid4()
    no_change = service.review_wfm_activity_relationship(
        command_id=no_change_command,
        seed_tasks=_seed_pairs(fresh),
        decision="distinct_activity",
        review_fingerprint=fresh.review_fingerprint,
        reason_category="confirm_existing_review",
    )
    assert no_change.outcome == "NO_CHANGE"
    assert no_change.result_refs == ()
    with ReadSnapshot(factory) as snapshot:
        assert snapshot.connection.execute(
            "SELECT count(*) FROM audit_events WHERE command_id=?", (no_change_command,)
        ).fetchone()[0] == 0
        assert snapshot.connection.execute(
            "SELECT result_type FROM command_receipts WHERE command_id=?", (no_change_command,)
        ).fetchone()[0] == "NO_CHANGE"


def test_same_activity_may_commit_projected_competing_attempt(initialized_database) -> None:
    factory = _factory(initialized_database)
    rfc_id = _create_rfc(factory, 2)
    task_ids = tuple(sorted((
        _register_wfm(factory, rfc_id=rfc_id, ordinal=3, start=1_900_000_000),
        _register_wfm(factory, rfc_id=rfc_id, ordinal=4, start=1_900_001_800),
    )))
    query = WfmActivityRelationshipReviewQueryService(factory)
    service = WfmActivityRelationshipReviewService(factory)

    preview = query.preview(seed_task_ids=task_ids, decision="same_activity")
    assert preview.projected_competing_attempt
    result = service.review_wfm_activity_relationship(
        command_id=new_uuid4(),
        seed_tasks=_seed_pairs(preview),
        decision="same_activity",
        review_fingerprint=preview.review_fingerprint,
        reason_category="same_provider_activity",
    )
    assert result.outcome == "APPLIED"

    with ReadSnapshot(factory) as snapshot:
        rows = snapshot.connection.execute(
            "SELECT task_id,activity_lineage_id,revision FROM task_activity_lineage_current "
            "WHERE task_id IN (?,?) ORDER BY task_id",
            task_ids,
        ).fetchall()
        assert len(rows) == 2
        assert len({str(row[1]) for row in rows}) == 1
        assert [int(row[2]) for row in rows] == [1, 1]

    fresh = query.preview(seed_task_ids=task_ids, decision="same_activity")
    assert fresh.semantic_no_change
    assert fresh.projected_competing_attempt


def test_complete_lineage_closure_paging_and_stale_error_split(initialized_database) -> None:
    factory = _factory(initialized_database)
    rfc_id = _create_rfc(factory, 3)
    task_ids = tuple(sorted((
        _register_wfm(factory, rfc_id=rfc_id, ordinal=5),
        _register_wfm(factory, rfc_id=rfc_id, ordinal=6),
        _register_wfm(factory, rfc_id=rfc_id, ordinal=7),
    )))
    query = WfmActivityRelationshipReviewQueryService(factory)
    service = WfmActivityRelationshipReviewService(factory)

    shared = query.preview(seed_task_ids=task_ids, decision="same_activity")
    service.review_wfm_activity_relationship(
        command_id=new_uuid4(),
        seed_tasks=_seed_pairs(shared),
        decision="same_activity",
        review_fingerprint=shared.review_fingerprint,
        reason_category="establish_shared_lineage",
    )

    two_seeds = task_ids[:2]
    first_page = query.preview(
        seed_task_ids=two_seeds,
        decision="distinct_activity",
        affected_limit=1,
    )
    assert first_page.affected_task_count == 3
    assert len(first_page.affected_tasks) == 1
    assert first_page.affected_continuation is not None

    with UnitOfWork(factory) as uow:
        uow.connection.execute(
            "UPDATE tasks SET revision=revision+1 WHERE task_id=?",
            (task_ids[2],),
        )

    with pytest.raises(ValidationError):
        query.preview(
            seed_task_ids=two_seeds,
            decision="distinct_activity",
            affected_cursor=first_page.affected_continuation,
            affected_limit=1,
        )

    stale_fp_command = new_uuid4()
    with pytest.raises(SomaError) as stale_fp:
        service.review_wfm_activity_relationship(
            command_id=stale_fp_command,
            seed_tasks=_seed_pairs(first_page),
            decision="distinct_activity",
            review_fingerprint=first_page.review_fingerprint,
            reason_category="stale_closure",
        )
    assert stale_fp.value.code == "TASK_ACTIVITY_REVIEW_STALE"

    fresh = query.preview(seed_task_ids=two_seeds, decision="distinct_activity")
    with UnitOfWork(factory) as uow:
        uow.connection.execute(
            "UPDATE tasks SET revision=revision+1 WHERE task_id=?",
            (two_seeds[0],),
        )
    stale_seed_command = new_uuid4()
    with pytest.raises(SomaError) as stale_seed:
        service.review_wfm_activity_relationship(
            command_id=stale_seed_command,
            seed_tasks=_seed_pairs(fresh),
            decision="distinct_activity",
            review_fingerprint=fresh.review_fingerprint,
            reason_category="stale_seed",
        )
    assert stale_seed.value.code == "TASK_STALE"

    with ReadSnapshot(factory) as snapshot:
        for command_id in (stale_fp_command, stale_seed_command):
            assert snapshot.connection.execute(
                "SELECT 1 FROM command_receipts WHERE command_id=?", (command_id,)
            ).fetchone() is None


def test_retry_lineage_consumes_existing_edge_without_mutating_it(initialized_database) -> None:
    factory = _factory(initialized_database)
    rfc_id = _create_rfc(factory, 4)
    task_ids = tuple(sorted((
        _register_wfm(factory, rfc_id=rfc_id, ordinal=8),
        _register_wfm(factory, rfc_id=rfc_id, ordinal=9),
    )))
    query = WfmActivityRelationshipReviewQueryService(factory)
    service = WfmActivityRelationshipReviewService(factory)

    with pytest.raises(SomaError) as missing:
        query.preview(seed_task_ids=task_ids, decision="retry_lineage")
    assert missing.value.code == "TASK_ACTIVITY_LINEAGE_CONFLICT"

    relation_id = _insert_retry_edge(factory, task_ids[0], task_ids[1])
    preview = query.preview(seed_task_ids=task_ids, decision="retry_lineage")
    assert preview.retry_relation_id == relation_id
    result = service.review_wfm_activity_relationship(
        command_id=new_uuid4(),
        seed_tasks=_seed_pairs(preview),
        decision="retry_lineage",
        review_fingerprint=preview.review_fingerprint,
        reason_category="reviewed_retry_attempt",
    )
    assert result.outcome == "APPLIED"

    with ReadSnapshot(factory) as snapshot:
        retry = snapshot.connection.execute(
            "SELECT predecessor_task_id,successor_task_id FROM task_retry_relations WHERE retry_relation_id=?",
            (relation_id,),
        ).fetchone()
        assert tuple(retry) == (task_ids[0], task_ids[1])
        lineage_count = snapshot.connection.execute(
            "SELECT count(DISTINCT activity_lineage_id) FROM task_activity_lineage_current "
            "WHERE task_id IN (?,?)",
            task_ids,
        ).fetchone()[0]
        assert lineage_count == 1


def test_multi_task_audit_failure_rolls_back_receipt_domain_and_first_audit(initialized_database, monkeypatch) -> None:
    factory = _factory(initialized_database)
    rfc_id = _create_rfc(factory, 5)
    task_ids = tuple(sorted((
        _register_wfm(factory, rfc_id=rfc_id, ordinal=10),
        _register_wfm(factory, rfc_id=rfc_id, ordinal=11),
    )))
    query = WfmActivityRelationshipReviewQueryService(factory)
    service = WfmActivityRelationshipReviewService(factory)
    preview = query.preview(seed_task_ids=task_ids, decision="same_activity")
    command_id = new_uuid4()

    original_write = service._boundary._audit_writer.write
    writes = 0

    def fail_second_audit(uow, event):
        nonlocal writes
        writes += 1
        if writes == 2:
            raise IntegrityFailure("injected second activity-review audit failure")
        return original_write(uow, event)

    monkeypatch.setattr(service._boundary._audit_writer, "write", fail_second_audit)

    with pytest.raises(IntegrityFailure):
        service.review_wfm_activity_relationship(
            command_id=command_id,
            seed_tasks=_seed_pairs(preview),
            decision="same_activity",
            review_fingerprint=preview.review_fingerprint,
            reason_category="failure_injection",
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
            "SELECT count(*) FROM task_activity_lineages WHERE created_command_id=?", (command_id,)
        ).fetchone()[0] == 0
        assert snapshot.connection.execute(
            "SELECT count(*) FROM task_activity_lineage_events WHERE command_id=?", (command_id,)
        ).fetchone()[0] == 0
        assert snapshot.connection.execute(
            "SELECT count(*) FROM task_activity_lineage_current WHERE task_id IN (?,?)", task_ids
        ).fetchone()[0] == 0
        assert snapshot.connection.execute(
            "SELECT count(*) FROM audit_events WHERE command_id=?", (command_id,)
        ).fetchone()[0] == 0
        assert snapshot.connection.execute(
            "SELECT 1 FROM command_receipts WHERE command_id=?", (command_id,)
        ).fetchone() is None
        assert snapshot.connection.execute(
            "SELECT 1 FROM command_receipt_results WHERE command_id=?", (command_id,)
        ).fetchone() is None
