import json
import sqlite3
from dataclasses import replace

import pytest

from soma.communications.contracts.common import Chronology, UNKNOWN_CHRONOLOGY
from soma.communications.contracts.message import ProviderMessageIdentity
from soma.communications.contracts.source import ProviderCheckpoint
from soma.communications.jobs.processing import CommunicationProcessingWorker
from soma.communications.services.processing import CommunicationProcessingService
from soma.communications.services.job_control import CommunicationJobControlService
from soma.foundation.errors import SomaError, JobClaimConflict
from soma.foundation.identifiers import new_uuid4
from test_communications_matching_run import identity
from test_communications_processing_batches import matched, scalar
from test_communications_processing_requests import setup_processing
from test_communications_processing_worker import Adapter
from test_communications_identity import message


def setup_history(database, values, *, kind="TARGETED_BACKFILL", targets=None, lower=None, upper=None, full=False):
    targets = targets or [identity("MW-00000001"), identity("MW-00000002")]
    path, factory, source, owners, starter, previews, proofs = setup_processing(database, targets)
    owners.lookup = lambda reader, token: (item for item in owners.values if item.normalized_value == token)
    owners.validate = lambda reader, item: "VALID" if item in owners.values else "INVALID"
    owners.validate_reassociation = lambda *args: "VALID"
    owners.validate_revision = lambda reader, kind, target, revision: "VALID" if any(
        (item.target_type, item.target_id, item.target_revision) == (kind, target, revision) for item in owners.values) else "INVALID"
    adapter = Adapter(factory, values)
    clock = [2_000_000_000]
    service = CommunicationProcessingService(factory, owners, starter._jobs, adapter=adapter, proof_provider=proofs)
    jobs = service._jobs
    jobs._clock = lambda: clock[0]
    # A pre-existing completed ordinary range must survive every historical path.
    with sqlite3.connect(path) as db:
        folder = db.execute("SELECT source_folder_id FROM communication_source_folders").fetchone()[0]
        db.execute("INSERT INTO communication_forward_coverage VALUES(?,?,?,'POSITION','ZZ',999001,'COMPLETE_TO_HIGH_WATER',7,100)", (source, folder, "test-1"))
    request = {"source_scope_id": source, "source_scope_revision": 1,
        "lower_bound": None if full else (lower or Chronology(True, 100, "OTHER_PROVIDER_TIME")).to_response(),
        "upper_bound": None if full else (upper or Chronology(True, 300, "OTHER_PROVIDER_TIME")).to_response()}
    if kind == "TARGETED_BACKFILL":
        request["target_identity_ids"] = [targets[0].target_id]
        preview = previews.preview_targeted_backfill(request)
        result = service.start_targeted_backfill({**request, "command_id": new_uuid4(), "preview_fingerprint": preview["preview_fingerprint"]})
    else:
        request["folder_keys"] = ["inbox"]
        preview = previews.preview_deep_scan(request)
        result = service.start_deep_scan({**request, "command_id": new_uuid4(), "preview_fingerprint": preview["preview_fingerprint"], "deliberate_action_proof": "approved-test-proof"})
    claim = jobs.claim_next(new_uuid4(), clock[0])
    assert claim.job_id == result["job_id"]
    worker = CommunicationProcessingWorker(factory, owners, jobs, adapter, clock=lambda: clock[0])
    return path, factory, owners, claim, jobs, clock, adapter, worker, proofs


def forward_unchanged(path):
    with sqlite3.connect(path) as db:
        assert db.execute("SELECT checkpoint_token,provider_time_source_epoch_ms,state,revision,updated_at_utc FROM communication_forward_coverage").fetchone() == ("ZZ", 999001, "COMPLETE_TO_HIGH_WATER", 7, 100)


@pytest.mark.parametrize("kind", ["TARGETED_BACKFILL", "DEEP_SCAN"])
def test_historical_processing_commits_separate_coverage_and_preserves_ordinary_checkpoint(communication_database, kind):
    path, _, _, claim, _, _, adapter, worker, proofs = setup_history(communication_database, [replace(matched(), subject="MW-00000001 MW-00000002")], kind=kind)
    result = worker.run(claim)
    assert result["retained"] == 1
    assert scalar(path, "SELECT count(*) FROM communication_links") == (1 if kind == "TARGETED_BACKFILL" else 2)
    forward_unchanged(path)
    with sqlite3.connect(path) as db:
        row = db.execute("SELECT lower_bound_json,upper_bound_json,state FROM communication_historical_coverage_segments").fetchone()
        assert json.loads(row[0])["utc_epoch_seconds"] == 100
        assert json.loads(row[1])["utc_epoch_seconds"] == 300
        assert row[2] == "BOUNDED_COMPLETE"
        checkpoint = json.loads(db.execute("SELECT checkpoint_json FROM durable_jobs WHERE job_id=?", (claim.job_id,)).fetchone()[0])
        assert len(checkpoint["coverage_segment_ids"]) == 1
    assert adapter.reads[0][0] is None and adapter.reads[0][1]["upper_bound"]["utc_epoch_seconds"] == 300
    assert proofs.calls == (1 if kind == "DEEP_SCAN" else 0)


def test_targeted_scope_does_not_retain_messages_matching_only_an_unselected_target(communication_database):
    path, _, _, claim, _, _, _, worker, _ = setup_history(communication_database, [message(subject="MW-00000002")])
    result = worker.run(claim)
    assert result["retained"] == 0 and result["skipped"] == 1
    with sqlite3.connect(path) as db:
        assert db.execute("SELECT count(*) FROM communications").fetchone() == (0,)


def test_removed_selected_target_stops_before_next_parse_even_when_next_message_would_not_match(communication_database):
    path, _, owners, claim, _, _, adapter, worker, _ = setup_history(communication_database, [matched(), message(subject="UNMATCHED")])
    original = worker._batches.commit_message
    def remove_after_commit(*args):
        result = original(*args)
        owners.values.pop(0)
        return result
    worker._batches.commit_message = remove_after_commit
    with pytest.raises(SomaError) as failed:
        worker.run(claim)
    assert failed.value.code == 'COMM_TARGET_STALE'
    assert scalar(path, "SELECT inspected FROM communication_job_counters") == 1
    assert scalar(path, "SELECT state FROM communication_historical_coverage_segments") == 'PARTIAL'


def test_historical_crash_recovery_uses_owned_segment_position_not_forward_high_water(communication_database, monkeypatch):
    later = replace(matched(), body="another retained body", provider_identity=ProviderMessageIdentity("MAPI_RECORD_KEY", b"second"), provider_position=ProviderCheckpoint("POSITION", "BB", 200001))
    path, _, _, claim, jobs, clock, adapter, worker, _ = setup_history(communication_database, [matched(), later])
    class ProcessDeath(BaseException):
        pass
    original = worker._batches.commit_message
    def stop(*args):
        original(*args)
        raise ProcessDeath()
    monkeypatch.setattr(worker._batches, "commit_message", stop)
    with pytest.raises(ProcessDeath):
        worker.run(claim)
    assert scalar(path, "SELECT state FROM communication_historical_coverage_segments") == "PARTIAL"
    clock[0] += 1000
    jobs.recover_stale_claims(new_uuid4(), clock[0])
    resumed = jobs.claim_next(new_uuid4(), clock[0])
    monkeypatch.setattr(worker._batches, "commit_message", original)
    result = worker.run(resumed)
    assert adapter.reads[-1][0].opaque_token == "AA"
    assert result["retained"] == 2 and result["unchanged"] == 1
    assert scalar(path, "SELECT count(*) FROM communication_historical_coverage_segments") == 1
    forward_unchanged(path)


@pytest.mark.parametrize("health,state", [("READY", "BOUNDED_COMPLETE"), ("PARTIAL", "PARTIAL")])
def test_empty_bounded_range_reports_actual_readability_without_inventing_a_position(communication_database, health, state):
    path, _, _, claim, _, _, adapter, worker, _ = setup_history(communication_database, [])
    adapter.health = health
    worker.run(claim)
    assert scalar(path, "SELECT state FROM communication_historical_coverage_segments") == state
    assert scalar(path, "SELECT inspected FROM communication_job_counters") == 0
    forward_unchanged(path)


def test_empty_full_deep_scan_keeps_unknown_bounds(communication_database):
    path, _, _, claim, _, _, _, worker, _ = setup_history(communication_database, [], kind="DEEP_SCAN", full=True)
    worker.run(claim)
    assert scalar(path, "SELECT state FROM communication_historical_coverage_segments") == "UNKNOWN"
    assert json.loads(scalar(path, "SELECT lower_bound_json FROM communication_historical_coverage_segments"))["known"] is False
    forward_unchanged(path)


def test_unknown_chronology_is_not_retained_or_claimed_inside_a_known_time_range(communication_database):
    path, _, _, claim, _, _, _, worker, _ = setup_history(communication_database, [matched(chronology=UNKNOWN_CHRONOLOGY)])
    result = worker.run(claim)
    assert result["warnings"] > 0 and result["skipped"] == 1
    assert scalar(path, "SELECT count(*) FROM communications") == 0
    assert scalar(path, "SELECT state FROM communication_historical_coverage_segments") == "UNKNOWN"


def test_historical_audit_failure_rolls_back_content_and_segment_and_progress(communication_database, monkeypatch):
    path, _, _, claim, _, _, _, worker, _ = setup_history(communication_database, [matched()])
    worker._matching.prepare_run(claim)
    prepared = worker._batches.prepare_message(claim, matched())
    def fail(*args):
        raise RuntimeError("audit failure")
    monkeypatch.setattr(worker._batches._audit, "write", fail)
    with pytest.raises(RuntimeError):
        worker._batches.commit_message(claim, prepared)
    assert scalar(path, "SELECT count(*) FROM communications") == 0
    assert scalar(path, "SELECT count(*) FROM communication_historical_coverage_segments") == 0
    assert scalar(path, "SELECT checkpoint_json FROM durable_jobs WHERE job_id=?", (claim.job_id,)) is None
    forward_unchanged(path)


def test_cancelled_historical_run_keeps_last_partial_segment(communication_database, monkeypatch):
    path, factory, _, claim, jobs, _, adapter, worker, _ = setup_history(communication_database, [matched(), matched()])
    original = worker._batches.commit_message
    def cancel(*args):
        result = original(*args)
        CommunicationJobControlService(factory, jobs).cancel_job({"command_id": new_uuid4(), "job_id": claim.job_id})
        return result
    monkeypatch.setattr(worker._batches, "commit_message", cancel)
    with pytest.raises(JobClaimConflict):
        worker.run(claim)
    assert scalar(path, "SELECT state FROM communication_historical_coverage_segments") == "PARTIAL"
    assert scalar(path, "SELECT inspected FROM communication_job_counters") == 1
    assert adapter.closed == 1
    forward_unchanged(path)


@pytest.mark.parametrize("bound", [99, 301])
def test_historical_adapter_cannot_commit_content_outside_reviewed_chronology_range(communication_database, bound):
    path, _, _, claim, _, _, _, worker, _ = setup_history(communication_database, [matched(chronology=Chronology(True, bound, "RECEIVED_TIME"))])
    with pytest.raises(SomaError):
        worker.run(claim)
    assert scalar(path, "SELECT count(*) FROM communications") == 0
    assert scalar(path, "SELECT count(*) FROM communication_historical_coverage_segments") == 0
    forward_unchanged(path)


def purge_seed(path, factory, claim, worker):
    from soma.communications.services.housekeeping import HousekeepingService
    worker._matching.prepare_run(claim)
    original = worker._batches.commit_message(claim, worker._batches.prepare_message(claim, matched()))
    communication = original["communication_id"]
    with sqlite3.connect(path) as db:
        db.execute("UPDATE communication_links SET state='CLOSED',closed_at_utc=1000,close_reason='SR_TERMINAL'")
        db.execute("UPDATE communication_retention SET state='ORPHAN_PENDING_PURGE',orphan_since_utc=1000,purge_due_utc=2000")
    HousekeepingService(factory).purge_due(command_id=new_uuid4(), communication_id=communication,
        selected_revision=1, now_utc=3000)
    assert scalar(path, "SELECT content_state FROM communications") == "PURGED"
    return communication


def test_historical_reconstruction_restores_same_canonical_id_revision_children_search_and_governed_protection(communication_database):
    path, factory, _, claim, _, _, _, worker, _ = setup_history(communication_database, [matched()])
    communication = purge_seed(path, factory, claim, worker)
    purged_revision = scalar(path, "SELECT content_revision FROM communications")
    result = worker.run(claim)
    assert scalar(path, "SELECT communication_id FROM communications") == communication
    assert scalar(path, "SELECT count(*) FROM communications") == 1
    assert scalar(path, "SELECT content_revision FROM communications") == purged_revision + 1
    assert scalar(path, "SELECT content_state FROM communications") == "RETAINED"
    assert scalar(path, "SELECT state FROM communication_retention") == "RETAINED"
    assert scalar(path, "SELECT count(*) FROM communication_protection_holds WHERE state='ACTIVE'") == 1
    assert scalar(path, "SELECT count(*) FROM communication_proposals WHERE state='PENDING'") == 1
    assert scalar(path, "SELECT count(*) FROM audit_events WHERE action_type='communications.content_reconstructed'") == 1
    assert scalar(path, "SELECT count(*) FROM communication_search_fts") == 1
    assert result["proposed"] == 1
    forward_unchanged(path)


@pytest.mark.parametrize("failure", ["changed_content", "audit"])
def test_reconstruction_failure_keeps_purged_state_and_prior_historical_progress(communication_database, monkeypatch, failure):
    path, factory, _, claim, _, _, _, worker, _ = setup_history(communication_database, [matched()])
    purge_seed(path, factory, claim, worker)
    prepared = worker._batches.prepare_message(claim, matched(body="changed") if failure == "changed_content" else matched())
    if failure == "audit":
        original = worker._batches._audit.write
        def fail(uow, event):
            if event.action_type == "communications.content_reconstructed":
                raise RuntimeError("reconstruction audit failure")
            return original(uow, event)
        monkeypatch.setattr(worker._batches._audit, "write", fail)
    with pytest.raises(SomaError if failure == "changed_content" else RuntimeError):
        worker._batches.commit_message(claim, prepared)
    assert scalar(path, "SELECT content_state FROM communications") == "PURGED"
    assert scalar(path, "SELECT state FROM communication_retention") == "PURGED"
    assert scalar(path, "SELECT count(*) FROM communication_proposals") == 0
    assert scalar(path, "SELECT inspected FROM communication_job_counters") == 1
    assert scalar(path, "SELECT count(*) FROM communication_search_fts") == 0
    forward_unchanged(path)
