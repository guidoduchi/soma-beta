from __future__ import annotations

import pytest

from soma.foundation.errors import SomaError
from soma.foundation.identifiers import new_uuid4
from soma.foundation.persistence.uow import ReadSnapshot
from soma.inventory.services.consequences_logistics import InventoryConsequencesLogisticsService
from soma.inventory.services.needs_stock import InventoryNeedsStockService
from soma.inventory.domain.logistics import LogisticsParticipantIntent
from soma.objectives_tasks.queries.execution_review import TaskOutcomeCorrectionQueryService
from soma.objectives_tasks.queries.tasks import TaskOperationalEvidenceReader
from soma.objectives_tasks.services.task_review import TaskReviewService
from test_objectives_tasks_task_review import _ended_task, _first_review_preview


def _reviewed_task(factory):
    task_id, revision, _ = _ended_task(factory)
    preview = _first_review_preview(factory, task_id=task_id, task_revision=revision)
    reviewed = TaskReviewService(factory).review_task_outcome(
        command_id=new_uuid4(), task_id=task_id, task_revision=revision,
        execution_revision=2, outcome_revision=0, current_outcome_event_id=None,
        outcome="completed", reason_category=None,
        outcome_review_fingerprint=preview.outcome_review_fingerprint,
    )
    with ReadSnapshot(factory) as snapshot:
        fingerprint = TaskOperationalEvidenceReader.review_fingerprint(snapshot, task_id)
    return task_id, reviewed, fingerprint


def _correct_review(factory, task_id, reviewed):
    args = dict(task_id=task_id, task_revision=reviewed.revision,
                execution_revision=2, current_outcome_revision=1,
                current_outcome_event_id=reviewed.result_refs[0].result_id,
                replacement_outcome="incomplete", reason_category="work_incomplete")
    preview = TaskOutcomeCorrectionQueryService(factory).preview(**args)
    return TaskReviewService(factory).correct_task_outcome(
        command_id=new_uuid4(), **args,
        correction_review_fingerprint=preview.correction_review_fingerprint,
    )


def _factory(initialized_database):
    path, builder = initialized_database
    return builder(path)


def test_consequence_acceptance_replays_exact_result_after_upstream_review_change(initialized_database, monkeypatch):
    factory = _factory(initialized_database)
    task_id, reviewed, fingerprint = _reviewed_task(factory)
    service = InventoryConsequencesLogisticsService(factory)
    args = dict(command_id=new_uuid4(), task_id=task_id,
                task_review_fingerprint=fingerprint, physical_disposition="no_physical_change")
    accepted = service.accept_inventory_physical_consequence(**args)
    _correct_review(factory, task_id, reviewed)

    def forbidden(*args, **kwargs):
        pytest.fail("mutable Task authority read during committed replay")

    monkeypatch.setattr(service._task_evidence, "task_outcome", forbidden)
    monkeypatch.setattr(service._task_evidence, "review_fingerprint", forbidden)
    replay = service.accept_inventory_physical_consequence(**args)
    assert replay.replayed
    assert replay.target_refs == accepted.target_refs
    assert replay.revisions == accepted.revisions
    with pytest.raises(SomaError) as collision:
        service.accept_inventory_physical_consequence(**{**args, "effective_at_utc": 42})
    assert collision.value.code == "IDEMPOTENCY_CONFLICT"
    with ReadSnapshot(factory) as snapshot:
        assert snapshot.connection.execute("SELECT COUNT(*) FROM inventory_physical_consequences WHERE task_id=?", (task_id,)).fetchone()[0] == 1
        assert snapshot.connection.execute("SELECT COUNT(*) FROM audit_events WHERE command_id=?", (args["command_id"],)).fetchone()[0] == 1


def test_consequence_correction_replays_before_current_revision_check(initialized_database, monkeypatch):
    factory = _factory(initialized_database)
    task_id, reviewed, fingerprint = _reviewed_task(factory)
    service = InventoryConsequencesLogisticsService(factory)
    accepted = service.accept_inventory_physical_consequence(
        command_id=new_uuid4(), task_id=task_id,
        task_review_fingerprint=fingerprint, physical_disposition="no_physical_change",
    )
    identity = accepted.target_refs[0].result_id
    with ReadSnapshot(factory) as snapshot:
        event = snapshot.connection.execute("SELECT last_event_id FROM physical_consequence_current WHERE physical_consequence_id=?", (identity,)).fetchone()[0]
    args = dict(command_id=new_uuid4(), physical_consequence_id=identity,
                expected_revision=1, expected_event_id=event,
                task_review_fingerprint=fingerprint, physical_disposition="no_physical_change",
                effective_at_utc=42, reason_code="correct time")
    corrected = service.correct_inventory_physical_consequence(**args)
    _correct_review(factory, task_id, reviewed)
    monkeypatch.setattr(service._projections, "current_physical_consequence",
                        lambda *args: pytest.fail("current consequence read during replay"))
    replay = service.correct_inventory_physical_consequence(**args)
    assert replay.replayed
    assert replay.target_refs == corrected.target_refs
    assert replay.revisions == corrected.revisions


def test_new_consequence_rejects_changed_task_fingerprint_without_receipt(initialized_database):
    factory = _factory(initialized_database)
    task_id, reviewed, fingerprint = _reviewed_task(factory)
    _correct_review(factory, task_id, reviewed)
    command = new_uuid4()
    with pytest.raises(SomaError) as stale:
        InventoryConsequencesLogisticsService(factory).accept_inventory_physical_consequence(
            command_id=command, task_id=task_id,
            task_review_fingerprint=fingerprint, physical_disposition="no_physical_change",
        )
    assert stale.value.code == "TASK_REVIEW_STALE"
    with ReadSnapshot(factory) as snapshot:
        assert snapshot.connection.execute("SELECT COUNT(*) FROM command_receipts WHERE command_id=?", (command,)).fetchone()[0] == 0
        assert snapshot.connection.execute("SELECT COUNT(*) FROM inventory_physical_consequences WHERE task_id=?", (task_id,)).fetchone()[0] == 0


def test_consequence_failure_after_owner_write_rolls_back_everything(initialized_database, monkeypatch):
    factory = _factory(initialized_database)
    task_id, _, fingerprint = _reviewed_task(factory)
    service = InventoryConsequencesLogisticsService(factory)
    original = service._projections.accept_physical_consequence

    def fail_after_write(*args, **kwargs):
        original(*args, **kwargs)
        raise RuntimeError("injected after consequence write")

    monkeypatch.setattr(service._projections, "accept_physical_consequence", fail_after_write)
    command = new_uuid4()
    with pytest.raises(RuntimeError, match="injected"):
        service.accept_inventory_physical_consequence(
            command_id=command, task_id=task_id,
            task_review_fingerprint=fingerprint, physical_disposition="no_physical_change",
        )
    with ReadSnapshot(factory) as snapshot:
        assert snapshot.connection.execute("SELECT COUNT(*) FROM command_receipts WHERE command_id=?", (command,)).fetchone()[0] == 0
        assert snapshot.connection.execute("SELECT COUNT(*) FROM audit_events WHERE command_id=?", (command,)).fetchone()[0] == 0
        assert snapshot.connection.execute("SELECT COUNT(*) FROM inventory_physical_consequences WHERE task_id=?", (task_id,)).fetchone()[0] == 0


def test_logistics_replay_retains_generated_event_and_participant_ids(initialized_database, monkeypatch):
    factory = _factory(initialized_database)
    unit = InventoryNeedsStockService(factory).register_spare_part_unit(
        command_id=new_uuid4(), origin="manual_local", bom_code="REPLAY-BOM", condition_token="new",
    )
    unit_id = next(ref.result_id for ref in unit.target_refs if ref.result_type == "spare_part_unit")
    service = InventoryConsequencesLogisticsService(factory)
    args = dict(command_id=new_uuid4(), event_kind="dispatch",
                participants=(LogisticsParticipantIntent("spare_part_unit", unit_id),))
    applied = service.record_actual_logistics_event(**args)
    monkeypatch.setattr(service._repository, "require_participant_identity",
                        lambda *args, **kwargs: pytest.fail("participant read during replay"))
    replay = service.record_actual_logistics_event(**args)
    assert replay.replayed
    assert replay.target_refs == applied.target_refs
    assert replay.revisions == applied.revisions
    with pytest.raises(SomaError) as collision:
        service.record_actual_logistics_event(**{**args, "effective_at_utc": 42})
    assert collision.value.code == "IDEMPOTENCY_CONFLICT"
