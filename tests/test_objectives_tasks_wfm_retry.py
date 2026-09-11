from __future__ import annotations

import pytest

from soma.foundation.errors import IntegrityFailure, SomaError, ValidationError
from soma.foundation.identifiers import new_uuid4
from soma.foundation.persistence.uow import ReadSnapshot, UnitOfWork
from soma.objectives_tasks.queries.task_activity_review import WfmActivityRelationshipReviewQueryService
from soma.objectives_tasks.services.retries import TaskRetryService
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


def _register_wfm(factory, *, rfc_id: str, ordinal: int) -> str:
    return TaskPlanningService(factory).register_manual_wfm_task(
        command_id=new_uuid4(),
        task_no=f"TK{ordinal:014d}",
        rfc_id=rfc_id,
    ).task_id


def _task_revision(factory, task_id: str) -> int:
    with ReadSnapshot(factory) as snapshot:
        row = snapshot.connection.execute(
            "SELECT revision FROM tasks WHERE task_id=?",
            (task_id,),
        ).fetchone()
        assert row is not None
        return int(row[0])


def test_wfm_retry_link_is_immutable_replayable_and_semantic_no_change(initialized_database) -> None:
    factory = _factory(initialized_database)
    rfc_id = _create_rfc(factory, 101)
    predecessor_id = _register_wfm(factory, rfc_id=rfc_id, ordinal=101)
    successor_id = _register_wfm(factory, rfc_id=rfc_id, ordinal=102)
    service = TaskRetryService(factory)

    command_id = new_uuid4()
    applied = service.link_wfm_retry_attempt(
        command_id=command_id,
        predecessor_wfm_task_id=predecessor_id,
        predecessor_task_revision=1,
        successor_wfm_task_id=successor_id,
        successor_task_revision=1,
        reason_category="provider_retry",
    )
    assert applied.outcome == "APPLIED"
    assert applied.task_id == predecessor_id
    assert applied.revision == 1
    assert not applied.replayed
    assert len(applied.result_refs) == 1
    assert applied.result_refs[0].result_type == "task_retry_relation"
    relation_id = applied.result_refs[0].result_id

    with ReadSnapshot(factory) as snapshot:
        edge = snapshot.connection.execute(
            "SELECT predecessor_task_id,successor_task_id FROM task_retry_relations WHERE retry_relation_id=?",
            (relation_id,),
        ).fetchone()
        assert tuple(edge) == (predecessor_id, successor_id)
        revisions = snapshot.connection.execute(
            "SELECT task_id,revision FROM tasks WHERE task_id IN (?,?) ORDER BY task_id",
            (predecessor_id, successor_id),
        ).fetchall()
        assert [(str(row[0]), int(row[1])) for row in revisions] == sorted(
            [(predecessor_id, 1), (successor_id, 1)]
        )
        assert snapshot.connection.execute(
            "SELECT count(*) FROM audit_events WHERE command_id=? AND action_type='task.retry_created_or_linked'",
            (command_id,),
        ).fetchone()[0] == 1

    # Exact replay is resolved before owner-state reads and remains independent of later state.
    with UnitOfWork(factory) as uow:
        uow.connection.execute(
            "UPDATE tasks SET revision=revision+1 WHERE task_id IN (?,?)",
            (predecessor_id, successor_id),
        )

    replayed = service.link_wfm_retry_attempt(
        command_id=command_id,
        predecessor_wfm_task_id=predecessor_id,
        predecessor_task_revision=1,
        successor_wfm_task_id=successor_id,
        successor_task_revision=1,
        reason_category="provider_retry",
    )
    assert replayed.replayed
    assert replayed.outcome == applied.outcome
    assert replayed.task_id == applied.task_id
    assert replayed.revision == applied.revision
    assert replayed.result_refs == applied.result_refs

    no_change_command = new_uuid4()
    no_change = service.link_wfm_retry_attempt(
        command_id=no_change_command,
        predecessor_wfm_task_id=predecessor_id,
        predecessor_task_revision=2,
        successor_wfm_task_id=successor_id,
        successor_task_revision=2,
        reason_category="confirm_existing_retry",
    )
    assert no_change.outcome == "NO_CHANGE"
    assert no_change.task_id == predecessor_id
    assert no_change.revision == 2
    assert no_change.result_refs == ()

    with ReadSnapshot(factory) as snapshot:
        assert snapshot.connection.execute(
            "SELECT count(*) FROM task_retry_relations WHERE predecessor_task_id=? AND successor_task_id=?",
            (predecessor_id, successor_id),
        ).fetchone()[0] == 1
        assert snapshot.connection.execute(
            "SELECT count(*) FROM audit_events WHERE command_id=?",
            (no_change_command,),
        ).fetchone()[0] == 0
        assert snapshot.connection.execute(
            "SELECT result_type FROM command_receipts WHERE command_id=?",
            (no_change_command,),
        ).fetchone()[0] == "NO_CHANGE"
        assert snapshot.connection.execute(
            "SELECT 1 FROM command_receipt_results WHERE command_id=?",
            (no_change_command,),
        ).fetchone() is not None


def test_wfm_retry_rejects_endpoint_reuse_and_cycles_before_receipt(initialized_database) -> None:
    factory = _factory(initialized_database)
    rfc_id = _create_rfc(factory, 102)
    task_ids = [
        _register_wfm(factory, rfc_id=rfc_id, ordinal=ordinal)
        for ordinal in range(103, 107)
    ]
    a, b, c, d = task_ids
    service = TaskRetryService(factory)

    service.link_wfm_retry_attempt(
        command_id=new_uuid4(),
        predecessor_wfm_task_id=a,
        predecessor_task_revision=1,
        successor_wfm_task_id=b,
        successor_task_revision=1,
    )

    outgoing_conflict_command = new_uuid4()
    with pytest.raises(SomaError) as outgoing_conflict:
        service.link_wfm_retry_attempt(
            command_id=outgoing_conflict_command,
            predecessor_wfm_task_id=a,
            predecessor_task_revision=1,
            successor_wfm_task_id=c,
            successor_task_revision=1,
        )
    assert outgoing_conflict.value.code == "TASK_RETRY_ALREADY_EXISTS"

    incoming_conflict_command = new_uuid4()
    with pytest.raises(SomaError) as incoming_conflict:
        service.link_wfm_retry_attempt(
            command_id=incoming_conflict_command,
            predecessor_wfm_task_id=d,
            predecessor_task_revision=1,
            successor_wfm_task_id=b,
            successor_task_revision=1,
        )
    assert incoming_conflict.value.code == "TASK_RETRY_ALREADY_EXISTS"

    service.link_wfm_retry_attempt(
        command_id=new_uuid4(),
        predecessor_wfm_task_id=b,
        predecessor_task_revision=1,
        successor_wfm_task_id=c,
        successor_task_revision=1,
    )

    cycle_command = new_uuid4()
    with pytest.raises(SomaError) as cycle:
        service.link_wfm_retry_attempt(
            command_id=cycle_command,
            predecessor_wfm_task_id=c,
            predecessor_task_revision=1,
            successor_wfm_task_id=a,
            successor_task_revision=1,
        )
    assert cycle.value.code == "TASK_RETRY_CYCLE"

    with ReadSnapshot(factory) as snapshot:
        for command_id in (outgoing_conflict_command, incoming_conflict_command, cycle_command):
            assert snapshot.connection.execute(
                "SELECT 1 FROM command_receipts WHERE command_id=?",
                (command_id,),
            ).fetchone() is None
        assert snapshot.connection.execute(
            "SELECT count(*) FROM task_retry_relations",
        ).fetchone()[0] == 2


def test_wfm_retry_fails_closed_on_stale_or_invalid_request(initialized_database) -> None:
    factory = _factory(initialized_database)
    rfc_id = _create_rfc(factory, 103)
    predecessor_id = _register_wfm(factory, rfc_id=rfc_id, ordinal=107)
    successor_id = _register_wfm(factory, rfc_id=rfc_id, ordinal=108)
    service = TaskRetryService(factory)

    with pytest.raises(ValidationError):
        service.link_wfm_retry_attempt(
            command_id=new_uuid4(),
            predecessor_wfm_task_id=predecessor_id,
            predecessor_task_revision=1,
            successor_wfm_task_id=predecessor_id,
            successor_task_revision=1,
        )

    with pytest.raises(ValidationError):
        service.link_wfm_retry_attempt(
            command_id=new_uuid4(),
            predecessor_wfm_task_id=predecessor_id,
            predecessor_task_revision=1,
            successor_wfm_task_id=successor_id,
            successor_task_revision=1,
            reason_category="bad\nreason",
        )

    with UnitOfWork(factory) as uow:
        uow.connection.execute(
            "UPDATE tasks SET revision=revision+1 WHERE task_id=?",
            (successor_id,),
        )

    stale_command = new_uuid4()
    with pytest.raises(SomaError) as stale:
        service.link_wfm_retry_attempt(
            command_id=stale_command,
            predecessor_wfm_task_id=predecessor_id,
            predecessor_task_revision=1,
            successor_wfm_task_id=successor_id,
            successor_task_revision=1,
        )
    assert stale.value.code == "TASK_STALE"

    with ReadSnapshot(factory) as snapshot:
        assert snapshot.connection.execute(
            "SELECT count(*) FROM task_retry_relations",
        ).fetchone()[0] == 0
        assert snapshot.connection.execute(
            "SELECT 1 FROM command_receipts WHERE command_id=?",
            (stale_command,),
        ).fetchone() is None


def test_wfm_retry_link_preserves_existing_activity_lineage_authority(initialized_database) -> None:
    factory = _factory(initialized_database)
    rfc_id = _create_rfc(factory, 104)
    task_ids = tuple(sorted((
        _register_wfm(factory, rfc_id=rfc_id, ordinal=109),
        _register_wfm(factory, rfc_id=rfc_id, ordinal=110),
    )))
    activity_query = WfmActivityRelationshipReviewQueryService(factory)
    activity_service = WfmActivityRelationshipReviewService(factory)

    preview = activity_query.preview(seed_task_ids=task_ids, decision="same_activity")
    activity_service.review_wfm_activity_relationship(
        command_id=new_uuid4(),
        seed_tasks=tuple((seed.task_id, seed.task_revision) for seed in preview.seed_tasks),
        decision="same_activity",
        review_fingerprint=preview.review_fingerprint,
        reason_category="establish_shared_activity",
    )

    with ReadSnapshot(factory) as snapshot:
        before_current = [
            tuple(row)
            for row in snapshot.connection.execute(
                "SELECT task_id,activity_lineage_id,revision,last_event_id FROM task_activity_lineage_current "
                "WHERE task_id IN (?,?) ORDER BY task_id",
                task_ids,
            ).fetchall()
        ]
        before_events = snapshot.connection.execute(
            "SELECT count(*) FROM task_activity_lineage_events",
        ).fetchone()[0]

    revisions = tuple(_task_revision(factory, task_id) for task_id in task_ids)
    assert revisions == (2, 2)
    command_id = new_uuid4()
    result = TaskRetryService(factory).link_wfm_retry_attempt(
        command_id=command_id,
        predecessor_wfm_task_id=task_ids[0],
        predecessor_task_revision=revisions[0],
        successor_wfm_task_id=task_ids[1],
        successor_task_revision=revisions[1],
        reason_category="retry_edge_only",
    )
    assert result.outcome == "APPLIED"

    with ReadSnapshot(factory) as snapshot:
        after_current = [
            tuple(row)
            for row in snapshot.connection.execute(
                "SELECT task_id,activity_lineage_id,revision,last_event_id FROM task_activity_lineage_current "
                "WHERE task_id IN (?,?) ORDER BY task_id",
                task_ids,
            ).fetchall()
        ]
        after_events = snapshot.connection.execute(
            "SELECT count(*) FROM task_activity_lineage_events",
        ).fetchone()[0]
        assert after_current == before_current
        assert after_events == before_events
        assert snapshot.connection.execute(
            "SELECT revision FROM tasks WHERE task_id=?",
            (task_ids[0],),
        ).fetchone()[0] == revisions[0]
        assert snapshot.connection.execute(
            "SELECT revision FROM tasks WHERE task_id=?",
            (task_ids[1],),
        ).fetchone()[0] == revisions[1]


def test_wfm_retry_audit_failure_rolls_back_receipt_edge_audit_and_replay(initialized_database, monkeypatch) -> None:
    factory = _factory(initialized_database)
    rfc_id = _create_rfc(factory, 105)
    predecessor_id = _register_wfm(factory, rfc_id=rfc_id, ordinal=111)
    successor_id = _register_wfm(factory, rfc_id=rfc_id, ordinal=112)
    service = TaskRetryService(factory)
    command_id = new_uuid4()

    def fail_audit(_uow, _event):
        raise IntegrityFailure("injected retry audit failure")

    monkeypatch.setattr(service._boundary._audit_writer, "write", fail_audit)

    with pytest.raises(IntegrityFailure):
        service.link_wfm_retry_attempt(
            command_id=command_id,
            predecessor_wfm_task_id=predecessor_id,
            predecessor_task_revision=1,
            successor_wfm_task_id=successor_id,
            successor_task_revision=1,
            reason_category="failure_injection",
        )

    with ReadSnapshot(factory) as snapshot:
        assert snapshot.connection.execute(
            "SELECT count(*) FROM task_retry_relations WHERE predecessor_task_id=? OR successor_task_id=?",
            (predecessor_id, successor_id),
        ).fetchone()[0] == 0
        assert snapshot.connection.execute(
            "SELECT count(*) FROM audit_events WHERE command_id=?",
            (command_id,),
        ).fetchone()[0] == 0
        assert snapshot.connection.execute(
            "SELECT 1 FROM command_receipts WHERE command_id=?",
            (command_id,),
        ).fetchone() is None
        assert snapshot.connection.execute(
            "SELECT 1 FROM command_receipt_results WHERE command_id=?",
            (command_id,),
        ).fetchone() is None
