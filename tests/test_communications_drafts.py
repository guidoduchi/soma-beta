from __future__ import annotations

import hashlib
import sqlite3

import pytest

from soma.communications.adapters.msg_publication import MsgDraftPublisher
from soma.communications.services.drafts import MsgDraftService
from soma.foundation.audit.writer import AuditWriter
from soma.foundation.errors import IdempotencyConflict, PersistenceFailure, SomaError, ValidationError
from soma.foundation.identifiers import new_uuid4
from soma.foundation.persistence.uow import ReadSnapshot
from soma.inventory.services.requests_rma import InventoryRequestsRmaService
from soma.objectives_tasks.queries.execution_review import TaskOutcomeReviewQueryService
from soma.objectives_tasks.queries.objectives import ObjectiveQueryService
from soma.objectives_tasks.services.objectives import ObjectiveService
from soma.objectives_tasks.services.task_execution import TaskExecutionService
from soma.objectives_tasks.services.task_review import TaskReviewService
from test_communications_identity_providers import providers
from test_communications_source_config import ReadOnlyAdapter, configure, request
from test_inventory_proposal_target_participant import _draft
from test_objectives_tasks_objectives import _create_single_task_objective


def spare_origin(factory):
    target_id, _ = _draft(factory)
    with ReadSnapshot(factory) as reader:
        command_id = reader.connection.execute("SELECT created_command_id FROM spare_requests WHERE spare_request_id=?", (target_id,)).fetchone()[0]
    return "LLD-07", "SPARE_REQUEST", target_id, command_id


def objective_origin(factory, outcome="completed"):
    task, objective = _create_single_task_objective(factory, name="MSG completion", start_utc=2700000000, end_utc=2700003600)
    execution = TaskExecutionService(factory)
    started = execution.start_task_execution(command_id=new_uuid4(), task_id=task.task_id, task_revision=task.revision,
        execution_revision=0, effective_start_utc=2700000100)
    ended = execution.end_task_execution(command_id=new_uuid4(), task_id=task.task_id, task_revision=started.revision,
        execution_revision=1, effective_end_utc=2700000200)
    args = dict(task_id=task.task_id, task_revision=ended.revision, execution_revision=2, outcome_revision=0,
                current_outcome_event_id=None, outcome=outcome, reason_category=None if outcome == "completed" else "INCOMPLETE_WORK")
    preview = TaskOutcomeReviewQueryService(factory).preview(**args)
    TaskReviewService(factory).review_task_outcome(command_id=new_uuid4(), **args, outcome_review_fingerprint=preview.outcome_review_fingerprint)
    review = ObjectiveQueryService(factory).workbench(objective.objective_id)["review"]["review_fingerprint"]
    command_id = new_uuid4()
    ObjectiveService(factory).review_objective(command_id=command_id, objective_id=objective.objective_id, review_fingerprint=review,
        reason_category=None if outcome == "completed" else "INCOMPLETE_WORK")
    return "LLD-05", "OBJECTIVE", objective.objective_id, command_id


def payload(origin, destination):
    domain, kind, target_id, origin_command_id = origin
    return dict(command_id=new_uuid4(), origin_domain=domain, origin_target_type=kind, origin_target_id=target_id,
        origin_command_id=origin_command_id, template_id="operator-selected-v1", template_version=1,
        subject="Authored canary subject", body_format="TEXT", body="Authored canary body\r\nCafé",
        recipients=[{"role": "CC", "address": "Cc@example.org", "display_name": None},
                    {"role": "TO", "address": "Case@example.org", "display_name": "Authored canary contact"},
                    {"role": "TO", "address": "second@example.org", "display_name": None}], destination_path=str(destination))


@pytest.mark.parametrize("origin_factory", [spare_origin, objective_origin])
def test_msg_local_flows_publish_immutable_provenance_without_sending(communication_database, tmp_path, origin_factory):
    path, factory = communication_database
    value = payload(origin_factory(factory), tmp_path / "operator.msg")
    result = MsgDraftService(factory, providers()).generate_msg_draft(value)
    artifact = (tmp_path / "operator.msg").read_bytes()
    assert hashlib.sha256(artifact).hexdigest() == result["artifact_sha256"]
    assert len(artifact) == result["artifact_size_bytes"]
    with sqlite3.connect(path) as db:
        assert db.execute("SELECT state,revision FROM communication_msg_drafts").fetchone() == ("EXPORTED", 1)
        assert db.execute("SELECT role,ordinal,address,display_name FROM communication_msg_draft_recipients ORDER BY role DESC,ordinal").fetchall() == [
            ("TO", 0, "Case@example.org", "Authored canary contact"), ("TO", 1, "second@example.org", None), ("CC", 2, "Cc@example.org", None)]
        for table in ("communications", "communication_links", "communication_historical_coverage_segments", "communication_forward_coverage"):
            assert db.execute(f"SELECT count(*) FROM {table}").fetchone()[0] == 0
        audit = db.execute("SELECT payload_json FROM audit_events WHERE command_id=?", (value["command_id"],)).fetchone()[0]
        assert all(canary not in audit for canary in ("canary", "example.org", str(tmp_path)))
        assert db.execute("SELECT count(*) FROM command_receipts WHERE command_id=?", (value["command_id"],)).fetchone()[0] == 1
        assert db.execute("SELECT count(*) FROM communication_msg_draft_exports").fetchone()[0] == 1
        if value["origin_domain"] == "LLD-07":
            assert db.execute("SELECT lifecycle_state,revision FROM spare_request_current_projection").fetchone() == ("draft", 1)


def test_exact_replay_precedes_owner_filesystem_and_writer_reads(communication_database, tmp_path):
    _, factory = communication_database
    value = payload(spare_origin(factory), tmp_path / "replay.msg")
    service = MsgDraftService(factory, providers())
    result = service.generate_msg_draft(value)
    (tmp_path / "replay.msg").unlink()
    service._owners = service._publisher = service._writer = object()
    assert service.generate_msg_draft(value) == result
    with pytest.raises(IdempotencyConflict):
        service.generate_msg_draft(value | {"body": "Changed"})
    assert not (tmp_path / "replay.msg").exists()


def test_later_observed_sent_message_has_new_canonical_identity_without_merging_draft(communication_database, tmp_path):
    from soma.communications.composition import build_communications_runtime
    from soma.communications.contracts.source import SourceFolder, SourceProbe
    from soma.communications.queries.previews import CommunicationPreviews
    from soma.communications.services.source_config import SourceConfigurationService
    from soma.communications.contracts.common import Chronology
    from test_communications_processing_worker import Adapter
    from test_communications_identity import message
    path, factory = communication_database
    origin = spare_origin(factory)
    value = payload(origin, tmp_path / 'distinct.msg')
    exported = MsgDraftService(factory, providers()).generate_msg_draft(value)
    with ReadSnapshot(factory) as reader:
        target = next(item for item in providers().snapshot(reader) if item.target_id == origin[2])
    adapter = Adapter(factory, [message(subject=target.normalized_value, chronology=Chronology(True, 100, 'SENT_TIME'),
        folder=SourceFolder('sent', 'SENT', 'Sent'))])
    adapter.probe_read_only = lambda *args: SourceProbe('READY', 'libpff', 'test-1', 'mailbox-A', (SourceFolder('sent', 'SENT', 'Sent'),))
    # Adapt the deterministic reader to the selected sent folder.
    adapter.enumerate = lambda *args: iter(adapter.values)
    configured, _ = configure(SourceConfigurationService(factory, adapter), CommunicationPreviews(factory, adapter),
        request() | {'selected_folder_keys': ['sent']})
    runtime = build_communications_runtime(factory, adapter, clock=lambda: 2_000_000_000)
    bounded = {'source_scope_id': configured['target_id'], 'source_scope_revision': 1, 'target_identity_ids': [target.target_id],
        'lower_bound': Chronology(True, 100, 'OTHER_PROVIDER_TIME').to_response(),
        'upper_bound': Chronology(True, 200, 'OTHER_PROVIDER_TIME').to_response()}
    preview = CommunicationPreviews(factory, adapter, providers()).preview_targeted_backfill(bounded)
    runtime.providers['processing'].start_targeted_backfill(bounded | {'command_id': new_uuid4(), 'preview_fingerprint': preview['preview_fingerprint']})
    assert runtime.dispatch(runtime.claim_next(new_uuid4(), 2_000_000_000))['retained'] == 1
    with sqlite3.connect(path) as db:
        communication, direction = db.execute('SELECT communication_id,direction FROM communications').fetchone()
        assert communication != exported['msg_draft_id'] and direction == 'SENT'
        assert db.execute('SELECT state FROM communication_msg_drafts').fetchone() == ('EXPORTED',)
        assert db.execute('SELECT lifecycle_state FROM spare_request_current_projection').fetchone() == ('draft',)


def test_same_origin_content_reuses_draft_and_export_with_new_receipt(communication_database, tmp_path):
    path, factory = communication_database
    service = MsgDraftService(factory, providers())
    value = payload(spare_origin(factory), tmp_path / "first.msg")
    first = service.generate_msg_draft(value)
    assert service.generate_msg_draft(value | {"command_id": new_uuid4()}) == first
    assert service.generate_msg_draft(value | {"command_id": new_uuid4(), "destination_path": str(tmp_path / "second.msg")}) == first
    different = service.generate_msg_draft(value | {"command_id": new_uuid4(), "template_version": 2})
    assert different["msg_draft_id"] != first["msg_draft_id"]
    with sqlite3.connect(path) as db:
        assert db.execute("SELECT count(*) FROM communication_msg_drafts").fetchone()[0] == 2
        assert db.execute("SELECT count(*) FROM communication_msg_draft_exports").fetchone()[0] == 3
        assert db.execute("SELECT count(*) FROM audit_events WHERE action_type='communications.msg_draft.exported'").fetchone()[0] == 3


def test_db_failure_keeps_artifact_and_retry_reconciles_hash(communication_database, tmp_path, monkeypatch):
    path, factory = communication_database
    service = MsgDraftService(factory, providers())
    value = payload(spare_origin(factory), tmp_path / "recover.msg")
    original = AuditWriter.write
    def fail(*args, **kwargs):
        raise PersistenceFailure("injected audit failure")
    monkeypatch.setattr(AuditWriter, "write", fail)
    with pytest.raises(PersistenceFailure):
        service.generate_msg_draft(value)
    artifact = (tmp_path / "recover.msg").read_bytes()
    before = (tmp_path / "recover.msg").stat().st_mtime_ns
    with sqlite3.connect(path) as db:
        for table in ("communication_msg_drafts", "communication_msg_draft_recipients", "communication_msg_draft_exports"):
            assert db.execute(f"SELECT count(*) FROM {table}").fetchone()[0] == 0
        assert db.execute("SELECT count(*) FROM command_receipts WHERE command_id=?", (value["command_id"],)).fetchone()[0] == 0
    monkeypatch.setattr(AuditWriter, "write", original)
    result = service.generate_msg_draft(value)
    assert result["artifact_sha256"] == hashlib.sha256(artifact).hexdigest()
    assert (tmp_path / "recover.msg").stat().st_mtime_ns == before


def test_publication_failure_is_sanitized_and_does_not_record_provenance(communication_database, tmp_path, monkeypatch):
    path, factory = communication_database
    value = payload(spare_origin(factory), tmp_path / "fail.msg")
    import soma.communications.adapters.msg_publication as module
    def fail(*args):
        raise OSError("private path and content canary")
    monkeypatch.setattr(module.os, "replace", fail)
    with pytest.raises(SomaError) as failure:
        MsgDraftService(factory, providers()).generate_msg_draft(value)
    assert failure.value.code == "COMM_MSG_BUILD_FAILED" and failure.value.__context__ is None
    assert "canary" not in str(failure.value)
    assert not list(tmp_path.glob(".soma-msg-*")) and not (tmp_path / "fail.msg").exists()
    with sqlite3.connect(path) as db:
        assert db.execute("SELECT count(*) FROM communication_msg_drafts").fetchone()[0] == 0


def test_changed_owner_during_publication_rolls_back_db_and_leaves_operator_artifact(communication_database, tmp_path):
    path, factory = communication_database
    origin = spare_origin(factory)
    class ChangeOwner(MsgDraftPublisher):
        def publish(self, path, artifact):
            super().publish(path, artifact)
            InventoryRequestsRmaService(factory).assign_or_correct_spare_request_official_id(
                command_id=new_uuid4(), spare_request_id=origin[2], base_revision=1, sr7="SR0000789", action="assign")
    value = payload(origin, tmp_path / "stale.msg")
    with pytest.raises(SomaError) as failure:
        MsgDraftService(factory, providers(), publisher=ChangeOwner()).generate_msg_draft(value)
    assert failure.value.code == "COMM_STALE" and (tmp_path / "stale.msg").exists()
    with sqlite3.connect(path) as db:
        assert db.execute("SELECT count(*) FROM communication_msg_drafts").fetchone()[0] == 0
    # Fresh recovery preserves the explicit authored snapshot; it does not mutate
    # the new owner state or treat the exported file as submission evidence.
    MsgDraftService(factory, providers()).generate_msg_draft(value)


def test_origin_must_be_matching_committed_owner_command_and_current_flow(communication_database, tmp_path):
    _, factory = communication_database
    service = MsgDraftService(factory, providers())
    value = payload(spare_origin(factory), tmp_path / "ineligible.msg")
    with pytest.raises(SomaError, match="origin"):
        service.generate_msg_draft(value | {"origin_command_id": new_uuid4()})
    with pytest.raises(SomaError, match="origin"):
        service.generate_msg_draft(payload(objective_origin(factory, "incomplete"), tmp_path / "incomplete.msg"))
    with pytest.raises(ValidationError):
        service.generate_msg_draft(value | {"origin_domain": "LLD-03", "origin_target_type": "SERVICE_REQUEST"})
    assert not list(tmp_path.glob("*.msg"))


def test_protected_source_and_nonlocal_paths_fail_before_writer(communication_database, tmp_path):
    _, factory = communication_database
    from soma.communications.queries.previews import CommunicationPreviews
    from soma.communications.services.source_config import SourceConfigurationService
    adapter = ReadOnlyAdapter()
    protected = tmp_path / "configured.msg"
    protected.write_bytes(b"source canary")
    configure(SourceConfigurationService(factory, adapter), CommunicationPreviews(factory, adapter), request(location=str(protected)))
    service = MsgDraftService(factory, providers(), writer=object())
    value = payload(spare_origin(factory), protected)
    for location in (str(protected), str(tmp_path / "source.pst"), "relative.msg", r"\\server\share\file.msg"):
        with pytest.raises(ValidationError):
            service.generate_msg_draft(value | {"destination_path": location})
    assert protected.read_bytes() == b"source canary"


def test_draft_snapshot_recipient_and_export_history_are_guarded(communication_database, tmp_path):
    path, factory = communication_database
    value = payload(spare_origin(factory), tmp_path / "immutable.msg")
    MsgDraftService(factory, providers()).generate_msg_draft(value)
    with sqlite3.connect(path) as db:
        for sql in ("UPDATE communication_msg_drafts SET subject_snapshot='replaced'",
                    "UPDATE communication_msg_draft_recipients SET address='other@example.org'",
                    "DELETE FROM communication_msg_draft_recipients", "DELETE FROM communication_msg_draft_exports"):
            with pytest.raises(sqlite3.IntegrityError):
                db.execute(sql)
