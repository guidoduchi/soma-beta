import json
import sqlite3
from dataclasses import replace

import pytest

from soma.communications.queries.summaries import CommunicationSummaryProvider
from soma.communications.services.rfc_terminal import RfcTerminalCommunicationParticipant
from soma.foundation.errors import IntegrityFailure, SomaError, ValidationError
from soma.foundation.application.command_receipts import CommandReceipt, CommandReceiptStore
from soma.foundation.identifiers import new_uuid4
from soma.foundation.persistence.uow import ReadSnapshot, UnitOfWork
from soma.foundation.strict_json import sha256_canonical_json
from soma.tickets.queries.rfc_terminal_cascade import RfcTerminalCascadePreviewService
from soma.tickets.rfc_terminal_cascade_execute import RfcTerminalCascadeExecutionService
from soma.tickets.rfc_terminal_review import RfcTerminalCascadeExecutionCommandContext
from soma.tickets.rfc_terminal_cascade import RfcTerminalCascadeCaptureService
from soma.tickets.rfc_source_projection import RfcSourceProjectionService
from soma.tickets.rfc_hierarchy import RfcHierarchyService

from test_communications_housekeeping import seed
from test_communications_identity_providers import providers
from test_communications_queries import add_link
from test_ticket_rfc_terminal_cascade_execute import _terminal_case, _ExecutionParticipant, _apply_result, _ProofProvider, _AcceptingEvidenceProvider, _insert_outer_receipt, _status
from test_ticket_rfc_terminal_cascade_capture import _new_rfc


def setup(database, *, count=2):
    path, factory = database
    _, rfc, proposal_id, _, task, _, proof, _ = _terminal_case((path, lambda _: factory))
    owners = providers()
    participant = RfcTerminalCommunicationParticipant(factory, owners)
    preview = RfcTerminalCascadePreviewService(factory, task, participant)
    execute = RfcTerminalCascadeExecutionService(factory, task, participant, proof)
    messages, links = [], []
    for _ in range(count):
        message = seed(path, pending=False)
        with sqlite3.connect(path) as db:
            db.execute("UPDATE communications SET chronology_known=1,chronology_utc=123,chronology_source_kind='RECEIVED_TIME' WHERE communication_id=?", (message,))
            link = add_link(db, message, rfc.rfc_id)
            db.execute("UPDATE communication_links SET target_type='RFC',matched_identity_kind='RFC_OFFICIAL',matched_identity_value=?,"
                "match_rule_id='COMM_EXACT_IDENTIFIER_V1' WHERE communication_link_id=?", (rfc.rfc_no, link))
        messages.append(message)
        links.append(link)
    return path, factory, rfc, proposal_id, task, proof, owners, participant, preview, execute, messages, links


def snapshot(preview, reader, proposal_id):
    state = preview._load_pending_state_by_id(reader.connection, proposal_id=proposal_id)
    return preview._persisted_snapshot(reader.connection, state=state)


def run(execute, preview, proposal_id, *, command_id=None):
    reviewed = preview.preview(proposal_id=proposal_id)
    assert reviewed.execution_ready
    command = command_id or new_uuid4()
    return command, execute.execute(command_id=command, proposal_id=proposal_id,
        proposal_revision=reviewed.proposal_revision, execution_review=reviewed.execution_review,
        deliberate_action_proof="confirmed", actor_id=None), reviewed


def test_rfc_impact_pages_keep_total_key_and_snapshot_metadata(communication_database):
    path, factory, rfc, proposal_id, _, _, _, participant, preview, _, messages, _ = setup(communication_database, count=7)
    with sqlite3.connect(path) as db:
        add_link(db, messages[0], new_uuid4())
    with ReadSnapshot(factory) as reader:
        proposal = snapshot(preview, reader, proposal_id)
        rows, after, pairs = [], None, set()
        while True:
            page = participant.preview_terminal_cascade(reader, proposal, after, 3)
            assert page.status == "READY" and len(page.items) <= 3
            pairs.add((page.exact_count, page.provider_fingerprint))
            rows.extend(page.items)
            after = page.continuation_key
            if after is None:
                break
        assert len(rows) == 15 and len(pairs) == 1
        assert [(i.impact_kind, i.entity_id) for i in rows] == sorted((i.impact_kind, i.entity_id) for i in rows)
        sibling = next(i for i in rows if i.impact_kind == "ORPHAN_GRACE_EVALUATION" and i.entity_id == messages[0])
        assert (sibling.current_count, sibling.resulting_count, sibling.resulting_state) == (2, 1, "RETAINED")
        with pytest.raises(ValidationError):
            participant.preview_terminal_cascade(reader, proposal, ("RFC_DIRECT_LINK_CLOSE", "bad"), 3)
        with pytest.raises(ValidationError):
            participant.preview_terminal_cascade(reader, proposal, limit=501)
    with UnitOfWork(factory) as writer:
        assert participant.revalidate_terminal_cascade(writer, proposal, *next(iter(pairs))) == "READY"
    with sqlite3.connect(path) as db:
        assert db.execute("SELECT count(*) FROM communication_terminal_summaries").fetchone()[0] == 0


def test_rfc_apply_exact_time_fingerprint_and_owner_replay(communication_database, monkeypatch):
    path, factory, rfc, proposal_id, task, proof, owners, _, preview, execute, messages, links = setup(communication_database)
    with sqlite3.connect(path) as db:
        sibling = add_link(db, messages[1], new_uuid4())
    clock = [1000]
    monkeypatch.setattr("soma.tickets._rfc_terminal_cascade_execution.utc_epoch_seconds", lambda: clock[0])
    original = task.apply_terminal_cascade
    def slow_task(*args):
        clock[0] = 1005
        return original(*args)
    monkeypatch.setattr(task, "apply_terminal_cascade", slow_task)
    command, result, reviewed = run(execute, preview, proposal_id)
    assert result.state == "executed" and task.contexts[0].accepted_execution_utc == 1000
    with ReadSnapshot(factory) as reader:
        frozen = CommunicationSummaryProvider(owners).terminal_summary(reader, "RFC", rfc.rfc_id)
        assert frozen["governing_event_id"] == proposal_id and frozen["unlink_utc"] == 1000 and frozen["received_count"] == 2
    with sqlite3.connect(path) as db:
        assert db.execute("SELECT executed_at_utc FROM rfc_terminal_cascade_proposals WHERE rfc_terminal_cascade_proposal_id=?", (proposal_id,)).fetchone()[0] == 1000
        assert db.execute("SELECT orphan_since_utc,purge_due_utc FROM communication_retention WHERE communication_id=?", (messages[0],)).fetchone() == (1000, 605800)
        assert db.execute("SELECT state FROM communication_retention WHERE communication_id=?", (messages[1],)).fetchone()[0] == "RETAINED"
        assert db.execute("SELECT state FROM communication_links WHERE communication_link_id=?", (sibling,)).fetchone()[0] == "ACTIVE"
        refs = [{"type": "communication_terminal_summary", "id": frozen["terminal_summary_id"]}]
        refs.extend({"type": "communication_link_event", "id": row[0]} for row in db.execute("SELECT communication_link_event_id FROM communication_link_events WHERE command_id=?", (command,)))
        refs.extend({"type": "communication_retention_event", "id": row[0]} for row in db.execute("SELECT retention_event_id FROM communication_retention_events WHERE command_id=?", (command,)))
        audits = sorted(row[0] for row in db.execute("SELECT audit_event_id FROM audit_events WHERE command_id=? AND action_type='communications.terminal_unlinked'", (command,)))
        owning = json.loads(db.execute("SELECT payload_json FROM audit_events WHERE command_id=? AND action_type='ticket.rfc.terminal_cascade_executed'", (command,)).fetchone()[0])
        actual = owning["communication_apply_result"]
        assert actual == {"domain": "COMMUNICATIONS", "result_ref_count": 4, "audit_event_count": 1,
            "result_fingerprint": sha256_canonical_json({"schema": "SOMA_RFC_TERMINAL_CASCADE_PARTICIPANT_RESULT_V1",
                "domain": "COMMUNICATIONS", "outer_command_id": command, "proposal_id": proposal_id,
                "result_refs": sorted(refs, key=lambda r: (r["type"], r["id"])), "audit_event_ids": audits})}
    replay = execute.execute(command_id=command, proposal_id=proposal_id, proposal_revision=reviewed.proposal_revision,
        execution_review=reviewed.execution_review, deliberate_action_proof="already-consumed")
    assert replay.replayed and replace(replay, replayed=False) == result and len(proof.calls) == 1


def test_rfc_stale_impact_rejected_before_confirmation(communication_database):
    path, _, _, proposal_id, _, proof, _, _, preview, execute, messages, _ = setup(communication_database)
    reviewed = preview.preview(proposal_id=proposal_id)
    with sqlite3.connect(path) as db:
        add_link(db, messages[0], new_uuid4())
    command = new_uuid4()
    with pytest.raises(SomaError) as failure:
        execute.execute(command_id=command, proposal_id=proposal_id, proposal_revision=1,
            execution_review=reviewed.execution_review, deliberate_action_proof="unused")
    assert failure.value.code == "RFC_TERMINAL_CASCADE_STALE" and proof.calls == []
    with sqlite3.connect(path) as db:
        assert db.execute("SELECT 1 FROM command_receipts WHERE command_id=?", (command,)).fetchone() is None


def test_rfc_audit_failure_rolls_back_cascade_and_all_consequences(communication_database, monkeypatch):
    path, _, _, proposal_id, _, _, _, participant, preview, execute, messages, links = setup(communication_database)
    monkeypatch.setattr(participant._audit, "write", lambda *args: (_ for _ in ()).throw(RuntimeError("injected")))
    command = new_uuid4()
    with pytest.raises(SomaError) as failure:
        run(execute, preview, proposal_id, command_id=command)
    assert failure.value.code == "RFC_TERMINAL_CASCADE_PARTICIPANT_FAILED"
    with sqlite3.connect(path) as db:
        assert db.execute("SELECT proposal_state,revision FROM rfc_terminal_cascade_proposals WHERE rfc_terminal_cascade_proposal_id=?", (proposal_id,)).fetchone() == ("pending", 1)
        assert db.execute("SELECT count(*) FROM communication_terminal_summaries").fetchone()[0] == 0
        assert db.execute("SELECT count(*) FROM communication_link_events WHERE command_id=?", (command,)).fetchone()[0] == 0
        assert all(db.execute("SELECT state,revision FROM communication_links WHERE communication_link_id=?", (link,)).fetchone() == ("ACTIVE", 1) for link in links)
        assert all(db.execute("SELECT state,revision FROM communication_retention WHERE communication_id=?", (message,)).fetchone() == ("RETAINED", 1) for message in messages)
        assert db.execute("SELECT 1 FROM command_receipts WHERE command_id=?", (command,)).fetchone() is None


def test_rfc_large_apply_uses_indexed_batches_and_bounded_owner_summary(communication_database):
    path, _, rfc, proposal_id, _, _, _, _, preview, execute, messages, _ = setup(communication_database, count=131)
    command, _, _ = run(execute, preview, proposal_id)
    with sqlite3.connect(path) as db:
        assert db.execute("SELECT count(*) FROM communication_links WHERE target_type='RFC' AND target_id=? AND state='CLOSED'", (rfc.rfc_id,)).fetchone()[0] == 131
        assert db.execute("SELECT count(*) FROM communication_retention_events WHERE command_id=?", (command,)).fetchone()[0] == 131
        result = json.loads(db.execute("SELECT payload_json FROM audit_events WHERE action_type='ticket.rfc.terminal_cascade_executed' AND command_id=?", (command,)).fetchone()[0])["communication_apply_result"]
        assert result["result_ref_count"] == 263 and result["audit_event_count"] == 1
        plan = db.execute("EXPLAIN QUERY PLAN SELECT communication_link_id FROM communication_links WHERE target_type='RFC' AND target_id=? AND state='ACTIVE' AND communication_link_id>? ORDER BY communication_link_id LIMIT 100", (rfc.rfc_id, "")).fetchall()
        assert any("idx_comm_link_target_event_order" in row[3] for row in plan)
        assert not any("TEMP B-TREE" in row[3] for row in plan)


def test_rfc_shared_scope_freezes_all_members_before_closing_and_deduplicates_orphan(communication_database):
    path, factory = communication_database
    root, child, outside = (_new_rfc(factory, 20260909009000 + n) for n in range(3))
    RfcHierarchyService(factory).add_subordinate(command_id=new_uuid4(), parent_rfc_id=root.rfc_id,
        child_rfc_id=child.rfc_id, base_revisions={root.rfc_id: 1, child.rfc_id: 1}, reason_category="terminal_scope_setup")
    task = _ExecutionParticipant("TASKS_OBJECTIVES", "c" * 64, apply_result=_apply_result("TASKS_OBJECTIVES", result_count=0, audit_count=0))
    source = RfcSourceProjectionService(_AcceptingEvidenceProvider(), terminal_capture_participant=RfcTerminalCascadeCaptureService(task))
    command = new_uuid4()
    with UnitOfWork(factory) as writer:
        _insert_outer_receipt(writer, command, root.rfc_id)
        proposal_id = source.apply_accepted_field_deltas(writer, rfc_id=root.rfc_id,
            accepted_command_id=command, deltas=(_status(),)).pending_cascade_proposal_id
    shared, protected = seed(path, pending=False), seed(path, pending=False)
    with sqlite3.connect(path) as db:
        for message in (shared, protected):
            for rfc in (root, child):
                link = add_link(db, message, rfc.rfc_id)
                db.execute("UPDATE communication_links SET target_type='RFC',matched_identity_kind='RFC_OFFICIAL',matched_identity_value=?,match_rule_id='COMM_EXACT_IDENTIFIER_V1' WHERE communication_link_id=?", (rfc.rfc_no, link))
        other = add_link(db, protected, outside.rfc_id)
        db.execute("UPDATE communication_links SET target_type='RFC',matched_identity_kind='RFC_OFFICIAL',matched_identity_value=? WHERE communication_link_id=?", (outside.rfc_no, other))
    participant = RfcTerminalCommunicationParticipant(factory, providers())
    preview = RfcTerminalCascadePreviewService(factory, task, participant)
    execute = RfcTerminalCascadeExecutionService(factory, task, participant, _ProofProvider())
    reviewed = preview.preview(proposal_id=proposal_id)
    assert reviewed.execution_review.communication_exact_count == 8  # two freezes, four closes, two distinct messages
    command, _, _ = run(execute, preview, proposal_id)
    with ReadSnapshot(factory) as reader:
        for rfc in (root, child):
            frozen = CommunicationSummaryProvider(providers()).terminal_summary(reader, "RFC", rfc.rfc_id)
            assert frozen["received_count"] == 2 and frozen["governing_event_id"] == proposal_id
        assert participant.classify_hard_delete_dependency(reader, child.rfc_id) == "BLOCKED"
    with sqlite3.connect(path) as db:
        assert db.execute("SELECT state FROM communication_links WHERE communication_link_id=?", (other,)).fetchone()[0] == "ACTIVE"
        assert db.execute("SELECT count(*) FROM communication_retention_events WHERE command_id=?", (command,)).fetchone()[0] == 1
        assert db.execute("SELECT state FROM communication_retention WHERE communication_id=?", (protected,)).fetchone()[0] == "RETAINED"
        result = json.loads(db.execute("SELECT payload_json FROM audit_events WHERE action_type='ticket.rfc.terminal_cascade_executed' AND command_id=?", (command,)).fetchone()[0])["communication_apply_result"]
        assert result["result_ref_count"] == 7 and result["audit_event_count"] == 2


def test_rfc_apply_requires_same_writer_revalidation_receipt_and_accepted_time(communication_database):
    _, factory, _, proposal_id, _, _, _, participant, preview, _, _, _ = setup(communication_database, count=0)
    with ReadSnapshot(factory) as reader:
        proposal = snapshot(preview, reader, proposal_id)
    context = RfcTerminalCascadeExecutionCommandContext(new_uuid4(), "local_user", None, "a" * 64, 1000)
    with pytest.raises(IntegrityFailure), UnitOfWork(factory) as writer:
        participant.apply_terminal_cascade(writer, proposal, context)
    with pytest.raises(ValidationError), UnitOfWork(factory) as writer:
        participant.apply_terminal_cascade(writer, proposal, replace(context, accepted_execution_utc=None))
    with pytest.raises(SomaError) as failure, UnitOfWork(factory) as writer:
        CommandReceiptStore().insert(writer, CommandReceipt(context.command_id, "ExecuteRfcTerminalCascade", "0" * 64,
            "rfc_terminal_cascade_proposal", proposal_id, 1000, None, None))
        participant.apply_terminal_cascade(writer, proposal, context)
    assert failure.value.code == "COMM_TARGET_STALE"
    for invalid in (True, -1, 2**63, "1000"):
        with pytest.raises(ValidationError):
            replace(context, accepted_execution_utc=invalid)


def test_rfc_failure_rolls_back_durable_proof_consumption_in_caller_uow(communication_database, monkeypatch):
    path, factory, _, proposal_id, task, _, _, participant, preview, _, _, _ = setup(communication_database)
    with sqlite3.connect(path) as db:
        # The future LLD-12 provider is represented by test-owned durable
        # evidence, rather than a Python set that cannot roll back with SQLite.
        db.execute("CREATE TABLE test_proof_consumptions(proof TEXT PRIMARY KEY)")
    class DurableProof:
        def validate_and_consume(self, uow, proof, *args):
            uow.connection.execute("INSERT INTO test_proof_consumptions VALUES(?)", (proof,))
            return object()
    execute = RfcTerminalCascadeExecutionService(factory, task, participant, DurableProof())
    original = participant._audit.write
    monkeypatch.setattr(participant._audit, "write", lambda *args: (_ for _ in ()).throw(RuntimeError("injected")))
    with pytest.raises(SomaError):
        run(execute, preview, proposal_id)
    with sqlite3.connect(path) as db:
        assert db.execute("SELECT count(*) FROM test_proof_consumptions").fetchone()[0] == 0
    monkeypatch.setattr(participant._audit, "write", original)
    run(execute, preview, proposal_id)
    with sqlite3.connect(path) as db:
        assert db.execute("SELECT count(*) FROM test_proof_consumptions").fetchone()[0] == 1
