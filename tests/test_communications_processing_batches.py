import io
import json
import sqlite3
from dataclasses import replace

import pytest

from soma.communications.contracts.message import ProviderMessageIdentity, TransientAttachment
from soma.communications.contracts.source import ProviderCheckpoint
from soma.communications.services.processing_batches import CommunicationBatchService
from soma.foundation.errors import JobClaimConflict, SomaError
from soma.foundation.identifiers import new_uuid4
from soma.foundation.persistence.uow import UnitOfWork
from test_communications_identity import message
from test_communications_matching_run import identity, start


class Ordering:
    @staticmethod
    def compare_checkpoints(lower, upper):
        return "BEFORE" if lower.opaque_token < upper.opaque_token else "EQUAL" if lower == upper else "AFTER"


def setup(database, values=None):
    values = values or [identity("MW-00000001")]
    path, factory, owners, matching, claim = start(database, values)
    matching._jobs._clock = lambda: 2_000_000_000
    owners.validate = lambda reader, candidate: "VALID"
    owners.validate_reassociation = lambda reader, kind, target, revision: "VALID"
    matching.prepare_run(claim)
    service = CommunicationBatchService(factory, owners, matching, matching._jobs, Ordering(), clock=lambda: 2_000_000_000)
    return path, factory, owners, claim, service


def matched(**changes):
    return message(subject="MW-00000001", provider_identity=ProviderMessageIdentity("MAPI_RECORD_KEY", b"message-key"), **changes)


def scalar(path, sql, parameters=()):
    with sqlite3.connect(path) as db:
        return db.execute(sql, parameters).fetchone()[0]


def commit(service, claim, value):
    return service.commit_message(claim, service.prepare_message(claim, value))


def test_batch_retains_one_canonical_message_and_independent_links_with_atomic_progress(communication_database):
    first, second = identity("MW-00000001"), identity("MW-00000002")
    path, _, _, claim, service = setup(communication_database, [first, second])
    value = message(subject="MW-00000001 MW-00000002", provider_identity=ProviderMessageIdentity("MAPI_RECORD_KEY", b"key"))
    result = commit(service, claim, value)
    with sqlite3.connect(path) as db:
        assert db.execute("SELECT count(*) FROM communications").fetchone() == (1,)
        assert db.execute("SELECT count(*) FROM communication_links WHERE state='ACTIVE'").fetchone() == (2,)
        assert db.execute("SELECT count(*) FROM communication_link_events").fetchone() == (2,)
        assert db.execute("SELECT state FROM communication_retention").fetchone() == ("RETAINED",)
        assert db.execute("SELECT checkpoint_token,provider_time_source_epoch_ms,state FROM communication_forward_coverage").fetchone() == ("AA", 100001, "PARTIAL")
        state, checkpoint = db.execute("SELECT state,checkpoint_json FROM durable_jobs WHERE job_id=?", (claim.job_id,)).fetchone()
        assert state == "running" and json.loads(checkpoint)["counters"] == result["counters"]
        assert db.execute("SELECT count(*) FROM audit_events WHERE action_type='communications.processing.batch_committed'").fetchone() == (1,)
    assert result["counters"]["retained"] == result["counters"]["matched"] == 1
    assert result["counters"]["estimated_total"] is None


def test_unmatched_leaves_no_content_children_identity_search_or_diagnostic_evidence(communication_database):
    path, _, _, claim, service = setup(communication_database)
    value = message(subject="UNMATCHED_SECRET", body="PRIVATE_BODY", internet_message_id="PRIVATE_ID", provider_identity=ProviderMessageIdentity("MAPI_RECORD_KEY", b"PRIVATE_KEY"))
    result = commit(service, claim, value)
    assert result["communication_id"] is None and result["counters"]["skipped"] == 1
    with sqlite3.connect(path) as db:
        for table in ("communications", "communication_participants", "communication_attachments", "communication_proposals", "communication_search_fts"):
            assert db.execute(f"SELECT count(*) FROM {table}").fetchone() == (0,)
        for table in ("command_receipts", "command_receipt_results", "audit_events", "durable_jobs"):
            rows = str(db.execute(f"SELECT * FROM {table}").fetchall())
            assert all(secret not in rows for secret in ("UNMATCHED_SECRET", "PRIVATE_BODY", "PRIVATE_ID", "PRIVATE_KEY"))


def test_overlap_preserves_links_content_revisions_and_high_water_without_retention_count_inflation(communication_database):
    path, _, _, claim, service = setup(communication_database)
    first = commit(service, claim, matched())
    second = commit(service, claim, matched(provider_position=ProviderCheckpoint("POSITION", "BB", 100002)))
    third = commit(service, claim, matched())
    assert first["communication_id"] == second["communication_id"] == third["communication_id"]
    assert third["counters"]["retained"] == third["counters"]["matched"] == 1
    assert third["counters"]["unchanged"] == 2 and not third["checkpoint_advanced"]
    assert scalar(path, "SELECT checkpoint_token FROM communication_forward_coverage") == "BB"
    assert scalar(path, "SELECT count(*) FROM communication_links") == 1
    assert scalar(path, "SELECT content_revision FROM communications") == 1


@pytest.mark.parametrize("change", ["revision", "ambiguity", "terminal", "source", "claim"])
def test_stale_preparation_rolls_back_all_authoritative_work(communication_database, change):
    path, _, owners, claim, service = setup(communication_database)
    prepared = service.prepare_message(claim, matched())
    if change == "revision":
        owners.values = [replace(owners.values[0], target_revision=2)]
    elif change == "ambiguity":
        owners.values.append(identity("MW-00000001"))
    elif change == "terminal":
        owners.validate_reassociation = lambda *args: "INVALID"
    elif change == "source":
        with sqlite3.connect(path) as db:
            db.execute("UPDATE communication_source_scopes SET revision=revision+1")
    else:
        claim = replace(claim, run_id=new_uuid4())
    with pytest.raises((SomaError, JobClaimConflict)):
        service.commit_message(claim, prepared)
    for table in ("communications", "communication_links", "communication_proposals", "communication_forward_coverage"):
        assert scalar(path, f"SELECT count(*) FROM {table}") == 0
    assert scalar(path, "SELECT inspected FROM communication_job_counters") == 0


def test_audit_failure_rolls_back_content_fts_links_receipt_counters_and_checkpoint(communication_database, monkeypatch):
    path, _, _, claim, service = setup(communication_database)
    prepared = service.prepare_message(claim, matched())
    def fail(*args):
        raise RuntimeError("injected audit failure")
    monkeypatch.setattr(service._audit, "write", fail)
    with pytest.raises(RuntimeError):
        service.commit_message(claim, prepared)
    for table in ("communications", "communication_links", "communication_link_events", "communication_retention", "communication_forward_coverage", "communication_search_fts"):
        assert scalar(path, f"SELECT count(*) FROM {table}") == 0
    assert scalar(path, "SELECT count(*) FROM command_receipts WHERE command_id=?", (prepared.envelope.command_id,)) == 0
    assert scalar(path, "SELECT checkpoint_json FROM durable_jobs WHERE job_id=?", (claim.job_id,)) is None


def test_exact_receipt_replay_survives_cancelled_claim_source_change_and_consumed_stream(communication_database):
    path, factory, owners, claim, service = setup(communication_database)
    value = matched(attachments=(TransientAttachment(0, "file.txt", None, 3, io.BytesIO(b"abc")),))
    prepared = service.prepare_message(claim, value)
    result = service.commit_message(claim, prepared)
    from soma.communications.services.job_control import CommunicationJobControlService
    CommunicationJobControlService(factory, service._jobs).cancel_job({"command_id": new_uuid4(), "job_id": claim.job_id})
    with UnitOfWork(factory) as writer:
        writer.connection.execute("UPDATE communication_source_scopes SET revision=revision+1")
    owners.lookup = lambda *args: (_ for _ in ()).throw(AssertionError("replay consulted current owner"))
    assert service.commit_message(claim, prepared) == result
    assert scalar(path, "SELECT count(*) FROM communication_attachment_chunks") == 1
    assert scalar(path, "SELECT inspected FROM communication_job_counters") == 1


@pytest.mark.parametrize("kind", ["alias", "ambiguous", "terminal"])
def test_non_auto_safe_matches_create_independent_review_proposals_and_exact_holds(communication_database, kind):
    values = [identity("MW-00000001", "SPARE_REQUEST_ALIAS" if kind == "alias" else "OBJECTIVE_TRACKING")]
    if kind == "ambiguous":
        values.append(identity("MW-00000001"))
    path, _, owners, claim, service = setup(communication_database, values)
    if kind == "terminal":
        owners.validate_reassociation = lambda *args: "INVALID"
    result = commit(service, claim, matched())
    assert result["counters"]["proposed"] == len(values)
    assert scalar(path, "SELECT count(*) FROM communication_links") == 0
    assert scalar(path, "SELECT count(*) FROM communication_protection_holds WHERE state='ACTIVE'") == len(values)
    commit(service, claim, matched())
    assert scalar(path, "SELECT count(*) FROM communication_proposals") == len(values)


def test_changed_provider_content_creates_review_without_associating_new_identifiers(communication_database):
    path, _, _, claim, service = setup(communication_database, [identity("MW-00000001"), identity("MW-00000002")])
    original = commit(service, claim, matched())
    changed = replace(matched(), subject="MW-00000002", body="PRIVATE_CHANGED_BODY")
    result = commit(service, claim, changed)
    assert result["communication_id"] == original["communication_id"]
    assert result["counters"]["warnings"] == 1
    assert scalar(path, "SELECT count(*) FROM communication_links") == 1
    assert scalar(path, "SELECT count(*) FROM communication_identity_review_evidence") == 1
    assert scalar(path, "SELECT body_text FROM communications") == "body\ntext"
    assert commit(service, claim, changed)["counters"]["warnings"] == 1


def test_independently_distinct_fallback_creates_protected_collision_without_auto_links(communication_database):
    path, _, _, claim, service = setup(communication_database)
    transient = message(subject="MW-00000001")
    original = commit(service, claim, transient)
    collision = commit(service, claim, replace(transient, independently_distinct_source_item=True))
    assert collision["communication_id"] != original["communication_id"]
    assert scalar(path, "SELECT count(*) FROM communications WHERE identity_state='IDENTITY_COLLISION'") == 1
    assert scalar(path, "SELECT count(*) FROM communication_links") == 1
    assert scalar(path, "SELECT count(*) FROM communication_protection_holds WHERE state='ACTIVE'") == 3
    with pytest.raises(SomaError) as unresolved:
        commit(service, claim, transient)
    assert unresolved.value.code == "COMM_IDENTITY_COLLISION"
    assert scalar(path, "SELECT count(*) FROM communications") == 2
    assert scalar(path, "SELECT inspected FROM communication_job_counters") == 2


def test_later_stable_provider_collision_candidate_is_reused_without_consolidating_fallback_identity(communication_database):
    path, _, _, claim, service = setup(communication_database)
    original = commit(service, claim, message(subject="MW-00000001"))
    stable = commit(service, claim, matched())
    overlap = commit(service, claim, matched())
    assert original["communication_id"] != stable["communication_id"] == overlap["communication_id"]
    assert scalar(path, "SELECT count(*) FROM communications") == 2
    assert scalar(path, "SELECT count(*) FROM communication_links") == 1
    assert scalar(path, "SELECT identity_state FROM communications WHERE communication_id=?", (stable["communication_id"],)) == "IDENTITY_COLLISION"


def test_existing_closed_link_requires_review_and_new_protection_cancels_grace(communication_database):
    path, _, _, claim, service = setup(communication_database)
    result = commit(service, claim, matched())
    with sqlite3.connect(path) as db:
        db.execute("UPDATE communication_links SET state='CLOSED',closed_at_utc=1000,close_reason='CORRECTION'")
        db.execute("UPDATE communication_retention SET state='ORPHAN_PENDING_PURGE',orphan_since_utc=1000,purge_due_utc=2000")
    commit(service, claim, matched())
    assert scalar(path, "SELECT count(*) FROM communication_links WHERE state='ACTIVE'") == 0
    assert scalar(path, "SELECT count(*) FROM communication_proposals") == 1
    assert scalar(path, "SELECT state FROM communication_retention") == "RETAINED"
    assert scalar(path, "SELECT count(*) FROM audit_events WHERE action_type='communications.orphan_grace.cancelled'") == 1


def test_unorderable_checkpoint_rejects_whole_batch_before_content_mutation(communication_database):
    path, _, _, claim, service = setup(communication_database)
    commit(service, claim, matched())
    prepared = service.prepare_message(claim, message(subject="MW-00000001", provider_position=ProviderCheckpoint("POSITION", "CC", 2)))
    service._adapter.compare_checkpoints = lambda *args: "INDETERMINATE"
    with pytest.raises(SomaError):
        service.commit_message(claim, prepared)
    assert scalar(path, "SELECT count(*) FROM communications") == 1
    assert scalar(path, "SELECT checkpoint_token FROM communication_forward_coverage") == "AA"
    assert scalar(path, "SELECT inspected FROM communication_job_counters") == 1


def test_rejected_link_evidence_is_not_auto_accepted_on_later_ordinary_overlap(communication_database):
    path, factory, owners, claim, service = setup(communication_database)
    owners.validate_reassociation = lambda *args: "INVALID"
    commit(service, claim, matched())
    with sqlite3.connect(path) as db:
        proposal, revision, target_revision, fingerprint = db.execute("SELECT communication_proposal_id,revision,target_revision,proposal_fingerprint FROM communication_proposals").fetchone()
    from soma.communications.services.proposals import CommunicationProposalService
    CommunicationProposalService(factory, clock=lambda: 2_000_000_000).decide_link({"command_id": new_uuid4(), "proposal_id": proposal,
        "proposal_revision": revision, "decision": "REJECT", "target_revision": target_revision,
        "proposal_fingerprint": fingerprint, "reason_code": "WRONG_TARGET"})
    owners.validate_reassociation = lambda *args: "VALID"
    result = commit(service, claim, matched())
    assert result["counters"]["proposed"] == 1
    assert scalar(path, "SELECT count(*) FROM communication_links") == 0
    assert scalar(path, "SELECT state FROM communication_proposals") == "REJECTED"
    assert scalar(path, "SELECT state FROM communication_retention") == "ORPHAN_PENDING_PURGE"
    assert scalar(path, "SELECT count(*) FROM communication_protection_holds WHERE state='ACTIVE'") == 0


def test_batch_consumes_production_objective_identity_owner_and_rejects_real_revision_drift(communication_database):
    from test_communications_identity_providers import providers
    from test_objectives_tasks_objectives import _create_single_task_objective
    from test_communications_processing_requests import setup_processing
    from soma.communications.services.processing import CommunicationProcessingService
    from soma.communications.services.matching import CommunicationMatchingService
    from soma.foundation.persistence.uow import ReadSnapshot
    path, factory, source, _, starter, _, _ = setup_processing(communication_database)
    _, objective = _create_single_task_objective(factory, name="Owner-bound matching", start_utc=100, end_utc=200)
    owners = providers()
    with ReadSnapshot(factory) as reader:
        target = next(item for item in owners.snapshot(reader) if item.target_id == objective.objective_id)
    jobs = starter._jobs
    jobs._clock = lambda: 2_000_000_000
    starter = CommunicationProcessingService(factory, owners, jobs)
    starter.start_processing({"command_id": new_uuid4(), "source_scope_id": source, "source_scope_revision": 1})
    claim = jobs.claim_next(new_uuid4(), 2_000_000_000)
    matching = CommunicationMatchingService(factory, owners, jobs)
    matching.prepare_run(claim)
    service = CommunicationBatchService(factory, owners, matching, jobs, Ordering(), clock=lambda: 2_000_000_000)
    commit(service, claim, message(subject=target.normalized_value, chronology=target.effective_from))
    assert scalar(path, "SELECT target_id FROM communication_links") == objective.objective_id
    prepared = service.prepare_message(claim, message(subject=target.normalized_value, body="different message", chronology=target.effective_from))
    _, replacement = _create_single_task_objective(factory, name="Replacement owner", start_utc=300, end_utc=400)
    with sqlite3.connect(path) as db:
        # Inject the guarded supersession shape, rather than an illegal edit to
        # immutable Objective identity. The real owner export must then stale.
        db.execute("UPDATE objectives SET revision=revision+1,superseded_by_objective_id=? WHERE objective_id=?",
            (replacement.objective_id, objective.objective_id))
    with pytest.raises(SomaError) as stale:
        service.commit_message(claim, prepared)
    assert stale.value.code == "COMM_TARGET_STALE"
    assert scalar(path, "SELECT count(*) FROM communications") == 1


def test_large_ambiguous_target_set_streams_independent_protection_without_audit_or_response_limit_changes(communication_database):
    values = [identity("MW-00000001") for _ in range(131)]
    path, _, owners, claim, service = setup(communication_database, values)
    lookups = []
    original = owners.lookup
    def counted(reader, token):
        lookups.append(token)
        return original(reader, token)
    owners.lookup = counted
    result = commit(service, claim, matched(body="MW-00000001 MW-00000001 MW-00000001"))
    assert result["counters"]["proposed"] == 131
    assert lookups == ["MW-00000001", "MW-00000001"]
    assert scalar(path, "SELECT count(*) FROM communication_proposals") == 131
    assert scalar(path, "SELECT count(*) FROM communication_protection_holds WHERE state='ACTIVE'") == 131
    with sqlite3.connect(path) as db:
        commands = db.execute("SELECT DISTINCT command_id FROM communication_proposal_events").fetchall()
        assert len(commands) == 1
        assert db.execute("SELECT count(*) FROM command_receipts WHERE command_id=?", commands[0]).fetchone() == (1,)
        plan = db.execute("EXPLAIN QUERY PLAN SELECT DISTINCT target_type,target_id FROM communication_match_tokens WHERE job_id=? AND token=? LIMIT 2",
            (claim.job_id, "MW-00000001")).fetchall()
        assert any("SEARCH" in row[3] for row in plan)
        assert not any("TEMP B-TREE" in row[3] for row in plan)


def test_attachment_capture_is_outside_writer_and_commit_never_reopens_changed_stream(communication_database):
    from soma.foundation.persistence.uow import _active_uow
    class GuardedStream(io.BytesIO):
        def read(self, size):
            assert not _active_uow.get(), "parser bytes were read under a writer lock"
            return super().read(size)
    path, _, _, claim, service = setup(communication_database)
    stream = GuardedStream(b"abc")
    prepared = service.prepare_message(claim, matched(attachments=(TransientAttachment(0, "item.bin", None, 3, stream),)))
    stream.seek(0)
    stream.write(b"xyz")
    service.commit_message(claim, prepared)
    with sqlite3.connect(path) as db:
        assert db.execute("SELECT content FROM communication_attachment_chunks").fetchone() == (b"abc",)


def test_adapter_message_outside_accepted_lower_bound_cannot_enter_authoritative_batch(communication_database):
    from soma.communications.contracts.common import Chronology
    path, _, _, claim, service = setup(communication_database)
    with pytest.raises(SomaError) as outside:
        service.prepare_message(claim, matched(chronology=Chronology(True, 99, "RECEIVED_TIME")))
    assert outside.value.code == "COMM_STALE"
    assert scalar(path, "SELECT count(*) FROM communications") == 0
