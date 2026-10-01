import json
import sqlite3

import pytest

from soma.communications.queries.summaries import CommunicationSummaryProvider
from soma.communications.services.housekeeping import HousekeepingService
from soma.communications.services.terminal import ServiceRequestTerminalCommunicationParticipant
from soma.foundation.errors import IntegrityFailure, SomaError
from soma.foundation.identifiers import new_uuid4
from soma.foundation.persistence.uow import ReadSnapshot, UnitOfWork
from soma.tickets.import_mutations import ServiceRequestImportMutationService, ServiceRequestSourceProjectionMutation
from soma.tickets.sr_source_projection import AcceptedSrFieldDeltaSet, SrSourceProjectionService

from test_communications_housekeeping import seed
from test_communications_identity_providers import providers
from test_communications_queries import add_link
from test_sr_source_projection import FakeSrSourceEvidenceProvider, _delta, _insert_outer_receipt, _official_sr


def setup(database, monkeypatch, *, count=1):
    path, factory = database
    sr = _official_sr(factory, "10000111")
    owner = providers()
    participant = ServiceRequestTerminalCommunicationParticipant(factory, owner)
    source = SrSourceProjectionService(FakeSrSourceEvidenceProvider(), terminal_communication_participant=participant)
    clock = [1000]
    monkeypatch.setattr("soma.tickets.sr_source_projection.utc_epoch_seconds", lambda: clock[0])
    messages, links = [], []
    for _ in range(count):
        message = seed(path, pending=False)
        with sqlite3.connect(path) as db:
            db.execute("UPDATE communications SET chronology_known=1,chronology_utc=123,chronology_source_kind='RECEIVED_TIME' WHERE communication_id=?", (message,))
            link = add_link(db, message, sr.service_request_id)
            db.execute("UPDATE communication_links SET target_type='SERVICE_REQUEST',matched_identity_kind='SERVICE_REQUEST_OFFICIAL',"
                "matched_identity_value='10000111',match_rule_id='COMM_EXACT_IDENTIFIER_V1',effective_chronology_known=1,"
                "effective_chronology_utc=123,effective_chronology_source_kind='RECEIVED_TIME' WHERE communication_link_id=?", (link,))
        messages.append(message)
        links.append(link)
    return path, factory, sr.service_request_id, owner, participant, source, clock, messages, links


def accept(factory, service, sr, status, *, basis="source_chronology", chronology=10, actor=None):
    command, actor = new_uuid4(), actor or new_uuid4()
    context = {"command_id": command, "actor_kind": "local_user", "actor_id": actor}
    with UnitOfWork(factory) as writer:
        _insert_outer_receipt(writer, command)
        result = service.apply_accepted_field_deltas(writer, sr,
            AcceptedSrFieldDeltaSet(command, (_delta("status", status, chronology=chronology, precedence_basis=basis),)),
            command_context=context)
    return command, result, context


def test_sr_terminal_freezes_before_unlink_and_starts_grace_at_local_acceptance(communication_database, monkeypatch):
    path, factory, sr, owners, participant, source, _, messages, links = setup(communication_database, monkeypatch, count=2)
    with sqlite3.connect(path) as db:
        sibling = add_link(db, messages[1], new_uuid4())
    with ReadSnapshot(factory) as reader:
        preview = participant.preview_terminal_transition(reader, sr, 1)
    assert (preview["closed_link_count"], preview["orphaned_communication_count"]) == (2, 1)
    command, result, context = accept(factory, source, sr, "Closed", chronology=10)
    assert len(result.communication_result_refs) == 1
    provider = CommunicationSummaryProvider(owners)
    with ReadSnapshot(factory) as reader:
        frozen = provider.terminal_summary(reader, "SERVICE_REQUEST", sr)
        assert frozen["received_count"] == 2 and frozen["last_interaction"]["utc_epoch_seconds"] == 123
        assert frozen["unlink_utc"] == 1000
        event = owners.sr_status_event(reader, sr, 1, result.inserted_observation_ids[0])
        assert event == {"terminal": True, "current": True, "recorded_at_utc": 1000, "command_id": command, "reviewed_correction": False}
    with sqlite3.connect(path) as db:
        assert db.execute("SELECT state FROM communication_links WHERE communication_link_id=?", (sibling,)).fetchone()[0] == "ACTIVE"
        assert db.execute("SELECT state,orphan_since_utc,purge_due_utc FROM communication_retention WHERE communication_id=?", (messages[0],)).fetchone() == ("ORPHAN_PENDING_PURGE", 1000, 605800)
        assert db.execute("SELECT state,revision FROM communication_retention WHERE communication_id=?", (messages[1],)).fetchone() == ("RETAINED", 1)
        assert db.execute("SELECT count(*) FROM communication_link_events WHERE command_id=? AND event_kind='CLOSED'", (command,)).fetchone()[0] == 2
        audit = db.execute("SELECT actor_id,payload_json FROM audit_events WHERE action_type='communications.terminal_unlinked'").fetchone()
        assert audit[0] == context["actor_id"] and json.loads(audit[1])["closed_link_count"] == 2
        assert "Secret" not in audit[1]
        assert all(db.execute("SELECT state FROM communication_links WHERE communication_link_id=?", (link,)).fetchone()[0] == "CLOSED" for link in links)
        assert db.execute("SELECT count(*) FROM command_receipts WHERE command_id=?", (command,)).fetchone()[0] == 1


def test_reviewed_sr_reversal_restores_same_links_cancels_grace_and_refreezes_sequence(communication_database, monkeypatch):
    path, factory, sr, owners, _, source, clock, messages, links = setup(communication_database, monkeypatch)
    _, first, _ = accept(factory, source, sr, "Closed")
    _, repeated, _ = accept(factory, source, sr, "Closed", chronology=20)
    assert repeated.no_change and repeated.communication_result_refs == ()
    _, corrected_terminal, _ = accept(factory, source, sr, "Resolved", basis="reviewed_correction", chronology=20)
    assert corrected_terminal.communication_result_refs == ()
    # Reclassification within terminal state does not remove the original
    # governed closure relation used by the subsequent reviewed reversal.
    clock[0] = 1100
    command, reversal, _ = accept(factory, source, sr, "In Progress", basis="reviewed_correction", chronology=30)
    assert reversal.communication_result_refs == first.communication_result_refs
    with sqlite3.connect(path) as db:
        assert db.execute("SELECT state,revision,effective_chronology_utc FROM communication_links WHERE communication_link_id=?", (links[0],)).fetchone() == ("ACTIVE", 3, 123)
        assert db.execute("SELECT state,purge_due_utc,revision FROM communication_retention WHERE communication_id=?", (messages[0],)).fetchone() == ("RETAINED", None, 3)
        assert db.execute("SELECT count(*) FROM communication_link_events WHERE command_id=? AND event_kind='RESTORED'", (command,)).fetchone()[0] == 1
        assert db.execute("SELECT count(*) FROM audit_events WHERE command_id=? AND action_type='communications.orphan_grace.cancelled'", (command,)).fetchone()[0] == 1
    accept(factory, source, sr, "Cancelled", chronology=40)
    with ReadSnapshot(factory) as reader:
        latest = CommunicationSummaryProvider(owners).terminal_summary(reader, "SERVICE_REQUEST", sr)
        assert latest["summary_revision"] == 2 and latest["received_count"] == 1


def test_terminal_audit_failure_rolls_back_owner_projection_receipt_and_all_communication_changes(communication_database, monkeypatch):
    path, factory, sr, _, participant, source, _, _, links = setup(communication_database, monkeypatch)
    monkeypatch.setattr(participant._audit, "write", lambda *args: (_ for _ in ()).throw(RuntimeError("injected terminal audit failure")))
    with pytest.raises(RuntimeError):
        accept(factory, source, sr, "Closed")
    with sqlite3.connect(path) as db:
        assert db.execute("SELECT count(*) FROM sr_source_field_observations WHERE service_request_id=?", (sr,)).fetchone()[0] == 0
        assert db.execute("SELECT count(*) FROM sr_current_source_projection WHERE service_request_id=?", (sr,)).fetchone()[0] == 0
        assert db.execute("SELECT state,revision FROM communication_links WHERE communication_link_id=?", (links[0],)).fetchone() == ("ACTIVE", 1)
        assert db.execute("SELECT count(*) FROM communication_terminal_summaries").fetchone()[0] == 0
        assert db.execute("SELECT count(*) FROM command_receipts WHERE command_type='AcceptImportProposal'").fetchone()[0] == 0


def test_sr_import_owner_passes_actor_and_bounded_summary_reference_in_same_uow(communication_database, monkeypatch):
    path, factory, sr, _, participant, _, _, _, _ = setup(communication_database, monkeypatch)
    mutation_owner = ServiceRequestImportMutationService(FakeSrSourceEvidenceProvider(), terminal_communication_participant=participant)
    command, actor = new_uuid4(), new_uuid4()
    with UnitOfWork(factory) as writer:
        _insert_outer_receipt(writer, command)
        token = mutation_owner.source_field_set_base_token(writer.connection, sr, ("status",))
        result = mutation_owner.apply_accepted_source_projection(writer, ServiceRequestSourceProjectionMutation(sr, token,
            AcceptedSrFieldDeltaSet(command, (_delta("status", "Closed", chronology=10),)), actor_kind="local_user", actor_id=actor))
    assert len(result.result_refs) == 2
    assert result.result_refs[-1][0] == "communication_terminal_summary"
    with sqlite3.connect(path) as db:
        assert db.execute("SELECT actor_id FROM audit_events WHERE action_type='communications.terminal_unlinked'").fetchone()[0] == actor


def test_large_sr_unlink_keeps_bounded_handoff_and_does_not_skip_mutating_index_rows(communication_database, monkeypatch):
    path, factory, sr, _, _, source, _, _, _ = setup(communication_database, monkeypatch, count=131)
    command, result, _ = accept(factory, source, sr, "Closed")
    assert len(result.communication_result_refs) == 1
    with sqlite3.connect(path) as db:
        assert db.execute("SELECT count(*) FROM communication_links WHERE target_type='SERVICE_REQUEST' AND target_id=? AND state='CLOSED'", (sr,)).fetchone()[0] == 131
        assert db.execute("SELECT count(*) FROM communication_retention WHERE state='ORPHAN_PENDING_PURGE'").fetchone()[0] == 131
        assert db.execute("SELECT count(*) FROM audit_event_results r JOIN audit_events a USING(audit_event_id) WHERE a.command_id=?", (command,)).fetchone()[0] == 1


@pytest.mark.parametrize("unavailable", [False, True])
def test_post_purge_reversal_preserves_summary_and_enqueues_only_provable_exact_scope(communication_database, monkeypatch, unavailable):
    path, factory, sr, owners, _, source, clock, messages, _ = setup(communication_database, monkeypatch)
    accept(factory, source, sr, "Closed")
    HousekeepingService(factory).purge_due(command_id=new_uuid4(), communication_id=messages[0], selected_revision=2, now_utc=605800)
    with sqlite3.connect(path) as db:
        scope = db.execute("SELECT source_scope_id FROM communications WHERE communication_id=?", (messages[0],)).fetchone()[0]
        db.execute("INSERT INTO communication_source_folders VALUES(?,?,'inbox','Inbox','INBOX',1,1)", (new_uuid4(), scope))
        if unavailable:
            db.execute("UPDATE communication_source_scopes SET health_state='MISSING' WHERE source_scope_id=?", (scope,))
    clock[0] = 606000
    command, _, _ = accept(factory, source, sr, "In Progress", basis="reviewed_correction", chronology=20)
    with sqlite3.connect(path) as db:
        assert db.execute("SELECT content_state,body_text FROM communications WHERE communication_id=?", (messages[0],)).fetchone() == ("PURGED", None)
        assert db.execute("SELECT count(*) FROM communication_links WHERE state='ACTIVE'").fetchone()[0] == 0
        jobs = db.execute("SELECT scope_json FROM communication_job_scopes").fetchall()
        assert len(jobs) == (0 if unavailable else 1)
        if jobs:
            scope = json.loads(jobs[0][0])
            assert scope["target_identity_ids"] == [sr] and scope["job_kind"] == "TARGETED_BACKFILL"
            assert scope["lower_bound"] == scope["upper_bound"] == {"known": True, "utc_epoch_seconds": 123, "source_kind": "RECEIVED_TIME"}
            assert db.execute("SELECT state FROM durable_jobs").fetchone()[0] == "queued"
        assert db.execute("SELECT count(*) FROM audit_events WHERE command_id=? AND action_type='communications.terminal_links.restored'", (command,)).fetchone()[0] == 1
    with ReadSnapshot(factory) as reader:
        result = CommunicationSummaryProvider(owners).entity_summary(reader, "SERVICE_REQUEST", sr)
        assert result["received_count"] == 1 and result["coverage_state"] == "UNKNOWN" and result["body_navigation_available"] is False


def test_missing_outer_context_and_stale_status_event_fail_closed(communication_database, monkeypatch):
    path, factory, sr, _, participant, source, _, _, _ = setup(communication_database, monkeypatch)
    command = new_uuid4()
    with pytest.raises(IntegrityFailure), UnitOfWork(factory) as writer:
        _insert_outer_receipt(writer, command)
        source.apply_accepted_field_deltas(writer, sr, AcceptedSrFieldDeltaSet(command, (_delta("status", "Closed", chronology=10),)))
    with pytest.raises(SomaError) as raised, UnitOfWork(factory) as writer:
        _insert_outer_receipt(writer, command)
        participant.apply_terminal_transition(writer, sr, 1, new_uuid4(), {"command_id": command, "actor_kind": "local_user", "actor_id": None})
    assert raised.value.code == "COMM_TARGET_STALE"


def test_post_purge_reconstruction_enqueue_rolls_back_with_reversal_audit_failure(communication_database, monkeypatch):
    path, factory, sr, _, participant, source, clock, messages, _ = setup(communication_database, monkeypatch)
    accept(factory, source, sr, "Closed")
    HousekeepingService(factory).purge_due(command_id=new_uuid4(), communication_id=messages[0], selected_revision=2, now_utc=605800)
    with sqlite3.connect(path) as db:
        scope = db.execute("SELECT source_scope_id FROM communications WHERE communication_id=?", (messages[0],)).fetchone()[0]
        db.execute("INSERT INTO communication_source_folders VALUES(?,?,'inbox','Inbox','INBOX',1,1)", (new_uuid4(), scope))
    clock[0] = 606000
    monkeypatch.setattr(participant._audit, "write", lambda *args: (_ for _ in ()).throw(RuntimeError("injected reversal audit failure")))
    with pytest.raises(RuntimeError):
        accept(factory, source, sr, "In Progress", basis="reviewed_correction", chronology=20)
    with sqlite3.connect(path) as db:
        assert db.execute("SELECT count(*) FROM communication_job_scopes").fetchone()[0] == 0
        assert db.execute("SELECT count(*) FROM durable_jobs").fetchone()[0] == 0
        assert db.execute("SELECT count(*) FROM audit_events WHERE action_type='communications.backfill.requested'").fetchone()[0] == 0
        assert db.execute("SELECT o.text_value FROM sr_current_source_projection p JOIN sr_source_field_observations o "
            "ON o.sr_source_field_observation_id=p.status_observation_id WHERE p.service_request_id=?", (sr,)).fetchone()[0] == "Closed"


def test_unknown_purged_message_chronology_cannot_authorize_implicit_full_scan(communication_database, monkeypatch):
    path, factory, sr, owners, _, source, clock, messages, _ = setup(communication_database, monkeypatch)
    with sqlite3.connect(path) as db:
        db.execute("UPDATE communications SET chronology_known=0,chronology_utc=NULL,chronology_source_kind='UNKNOWN'")
        scope = db.execute("SELECT source_scope_id FROM communications WHERE communication_id=?", (messages[0],)).fetchone()[0]
        db.execute("INSERT INTO communication_source_folders VALUES(?,?,'inbox','Inbox','INBOX',1,1)", (new_uuid4(), scope))
    accept(factory, source, sr, "Closed")
    HousekeepingService(factory).purge_due(command_id=new_uuid4(), communication_id=messages[0], selected_revision=2, now_utc=605800)
    clock[0] = 606000
    accept(factory, source, sr, "In Progress", basis="reviewed_correction", chronology=20)
    with ReadSnapshot(factory) as reader:
        summary = CommunicationSummaryProvider(owners).entity_summary(reader, "SERVICE_REQUEST", sr)
        assert summary["last_interaction"]["known"] is False and summary["coverage_state"] == "UNKNOWN"
        assert "COMM_RECONSTRUCTION_REQUIRED" in summary["warnings"]
        assert reader.connection.execute("SELECT count(*) FROM durable_jobs").fetchone()[0] == 0
