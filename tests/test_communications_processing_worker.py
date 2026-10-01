import json
import sqlite3
from contextlib import contextmanager

import pytest

from soma.communications.contracts.source import SourceFolder, SourceProbe, ProviderCheckpoint
from soma.communications.jobs.processing import CommunicationProcessingWorker
from soma.communications.services.job_control import CommunicationJobControlService
from soma.foundation.errors import JobClaimConflict, SomaError
from soma.foundation.identifiers import new_uuid4
from test_communications_identity import message
from test_communications_processing_batches import Ordering, matched, scalar, setup


class Adapter(Ordering):
    def __init__(self, factory, values):
        self.factory, self.values = factory, values
        self.opened = 0
        self.closed = 0
        self.reads = []
        self.health = "READY"
        self.candidate = "mailbox-A"
        self.before_next = lambda ordinal: None
        self.after_probe = lambda: None

    def probe_read_only(self, location, profile):
        self.after_probe()
        return SourceProbe(self.health, "libpff", "test-1", self.candidate, (SourceFolder("inbox", "INBOX", "Inbox"),))

    @contextmanager
    def open_read_only(self, location, profile):
        self.opened += 1
        try:
            yield self
        finally:
            self.closed += 1

    def enumerate(self, handle, folder, checkpoint, overlap):
        assert handle is self and folder.folder_key == "inbox"
        self.reads.append((checkpoint, overlap))
        for ordinal, value in enumerate(self.values):
            self.before_next(ordinal)
            yield value


def worker_setup(database, values):
    path, factory, owners, claim, batches = setup(database)
    clock = [2_000_000_000]
    jobs = batches._jobs
    jobs._clock = lambda: clock[0]
    adapter = Adapter(factory, values)
    worker = CommunicationProcessingWorker(factory, owners, jobs, adapter, clock=lambda: clock[0])
    return path, factory, owners, claim, jobs, clock, adapter, worker


def test_worker_inspects_read_only_and_commits_only_matches_and_actual_exhaustion(communication_database):
    values = [matched(), message(subject="UNMATCHED_PRIVATE", provider_position=ProviderCheckpoint("POSITION", "BB", 100002))]
    path, _, _, claim, _, _, adapter, worker = worker_setup(communication_database, values)
    result = worker.run(claim)
    assert result["inspected"] == 2 and result["retained"] == 1 and result["skipped"] == 1
    assert adapter.opened == adapter.closed == 1
    assert adapter.reads[0][0] is None
    assert adapter.reads[0][1] == {"overlap_messages": 50, "lower_bound": {"known": True, "utc_epoch_seconds": 100, "source_kind": "OTHER_PROVIDER_TIME"}}
    assert scalar(path, "SELECT state FROM durable_jobs WHERE job_id=?", (claim.job_id,)) == "completed"
    assert scalar(path, "SELECT state FROM communication_forward_coverage") == "COMPLETE_TO_HIGH_WATER"
    assert scalar(path, "SELECT count(*) FROM communications") == 1
    checkpoint = json.loads(scalar(path, "SELECT checkpoint_json FROM durable_jobs WHERE job_id=?", (claim.job_id,)))
    assert checkpoint["last_committed_provider_checkpoint"]["opaque_token"] == "BB"
    assert checkpoint["counters"] == result


def test_worker_crash_recovery_reuses_committed_messages_and_resumes_recorded_provider_position(communication_database, monkeypatch):
    path, _, _, claim, jobs, clock, adapter, worker = worker_setup(communication_database, [matched()])
    class ProcessDeath(BaseException):
        pass
    original = worker._batches.commit_message
    def crash_after_commit(*args):
        original(*args)
        raise ProcessDeath()
    monkeypatch.setattr(worker._batches, "commit_message", crash_after_commit)
    with pytest.raises(ProcessDeath):
        worker.run(claim)
    assert scalar(path, "SELECT state FROM communication_forward_coverage") == "PARTIAL"
    clock[0] += 1000
    jobs.recover_stale_claims(new_uuid4(), clock[0])
    resumed = jobs.claim_next(new_uuid4(), clock[0])
    assert resumed.attempt_ordinal == 2
    monkeypatch.setattr(worker._batches, "commit_message", original)
    result = worker.run(resumed)
    assert adapter.reads[-1][0].opaque_token == "AA"
    assert result["retained"] == result["matched"] == 1 and result["unchanged"] == 1
    assert scalar(path, "SELECT count(*) FROM communications") == 1
    assert scalar(path, "SELECT count(*) FROM communication_links") == 1
    assert scalar(path, "SELECT state FROM durable_jobs WHERE job_id=?", (claim.job_id,)) == "completed"


def test_cancellation_between_batches_prevents_next_parse_and_preserves_last_commit(communication_database, monkeypatch):
    values = [matched(), message(subject="MW-00000001", provider_position=ProviderCheckpoint("POSITION", "BB", 2))]
    path, factory, _, claim, jobs, _, adapter, worker = worker_setup(communication_database, values)
    calls = []
    adapter.before_next = lambda ordinal: calls.append(ordinal)
    original = worker._batches.commit_message
    def cancel_after_commit(*args):
        result = original(*args)
        CommunicationJobControlService(factory, jobs).cancel_job({"command_id": new_uuid4(), "job_id": claim.job_id})
        return result
    monkeypatch.setattr(worker._batches, "commit_message", cancel_after_commit)
    with pytest.raises(JobClaimConflict):
        worker.run(claim)
    assert calls == [0] and adapter.closed == 1
    assert scalar(path, "SELECT state FROM durable_jobs WHERE job_id=?", (claim.job_id,)) == "cancelled"
    assert scalar(path, "SELECT checkpoint_token FROM communication_forward_coverage") == "AA"
    assert scalar(path, "SELECT inspected FROM communication_job_counters") == 1


def test_transient_source_failure_preserves_prior_batch_and_uses_registered_retry(communication_database):
    path, _, _, claim, jobs, clock, adapter, worker = worker_setup(communication_database, [matched(), matched()])
    def locked(ordinal):
        if ordinal == 1:
            raise SomaError("SOURCE_LOCKED", "PRIVATE_BODY private source path")
    adapter.before_next = locked
    with pytest.raises(SomaError) as failed:
        worker.run(claim)
    assert failed.value.code == "SOURCE_LOCKED" and "PRIVATE" not in str(failed.value)
    assert failed.value.__context__ is None and failed.value.__cause__ is None
    assert scalar(path, "SELECT state FROM communication_forward_coverage") == "PARTIAL"
    assert scalar(path, "SELECT next_attempt_at_utc FROM durable_jobs WHERE job_id=?", (claim.job_id,)) == clock[0] + 10
    assert scalar(path, "SELECT count(*) FROM communications") == 1
    assert adapter.closed == 1


@pytest.mark.parametrize("condition", ["no_targets", "other_mailbox", "reconfigured"])
def test_worker_preflight_fails_before_opening_source_content(communication_database, condition):
    path, _, owners, claim, _, _, adapter, worker = worker_setup(communication_database, [matched()])
    if condition == "no_targets":
        owners.values = []
    elif condition == "other_mailbox":
        adapter.candidate = "another-mailbox"
    else:
        def reconfigure():
            with sqlite3.connect(path) as db:
                db.execute("UPDATE communication_source_scopes SET revision=revision+1")
        adapter.after_probe = reconfigure
    with pytest.raises(SomaError):
        worker.run(claim)
    assert adapter.opened == 0
    assert scalar(path, "SELECT count(*) FROM communications") == 0
    assert scalar(path, "SELECT count(*) FROM communication_forward_coverage") == 0


def test_partial_adapter_never_claims_complete_coverage(communication_database):
    path, _, _, claim, _, _, adapter, worker = worker_setup(communication_database, [matched()])
    adapter.health = "PARTIAL"
    worker.run(claim)
    assert scalar(path, "SELECT state FROM communication_forward_coverage") == "PARTIAL"


def test_empty_source_has_no_invented_provider_position_or_content_audit(communication_database):
    path, _, _, claim, _, _, _, worker = worker_setup(communication_database, [])
    assert worker.run(claim)["inspected"] == 0
    assert scalar(path, "SELECT count(*) FROM communication_forward_coverage") == 0
    assert scalar(path, "SELECT count(*) FROM audit_events WHERE action_type='communications.processing.batch_committed'") == 0


def test_empty_partial_source_records_unknown_range_and_warning_without_inventing_a_position(communication_database):
    path, _, _, claim, _, _, adapter, worker = worker_setup(communication_database, [])
    adapter.health = "PARTIAL"
    result = worker.run(claim)
    assert result["warnings"] == 1 and result["inspected"] == 0
    with sqlite3.connect(path) as db:
        assert db.execute("SELECT state,checkpoint_kind,checkpoint_token FROM communication_forward_coverage").fetchone() == ("UNKNOWN", None, None)


def test_out_of_order_adapter_fails_without_advancing_past_last_committed_work(communication_database):
    values = [matched(provider_position=ProviderCheckpoint("POSITION", "BB", 2)), matched()]
    path, _, _, claim, _, _, _, worker = worker_setup(communication_database, values)
    with pytest.raises(SomaError):
        worker.run(claim)
    assert scalar(path, "SELECT checkpoint_token FROM communication_forward_coverage") == "BB"
    assert scalar(path, "SELECT state FROM communication_forward_coverage") == "PARTIAL"
    assert scalar(path, "SELECT inspected FROM communication_job_counters") == 1


def test_committed_forward_checkpoint_authorizes_overlap_before_the_initial_lower_bound(communication_database):
    from soma.communications.contracts.common import Chronology
    from soma.communications.contracts.message import ProviderMessageIdentity
    recent = matched(chronology=Chronology(True, 200, "RECEIVED_TIME"), provider_position=ProviderCheckpoint("POSITION", "BB", 200001))
    older = message(subject="MW-00000001", chronology=Chronology(True, 95, "RECEIVED_TIME"),
        provider_identity=ProviderMessageIdentity("MAPI_RECORD_KEY", b"older-item"))
    path, _, _, claim, _, _, adapter, worker = worker_setup(communication_database, [older, recent])
    worker._batches.commit_message(claim, worker._batches.prepare_message(claim, recent))
    result = worker.run(claim)
    assert adapter.reads[0][0].opaque_token == "BB"
    assert adapter.reads[0][1]["lower_bound"] is None
    assert result["retained"] == 2
    assert scalar(path, "SELECT checkpoint_token FROM communication_forward_coverage") == "BB"
    assert scalar(path, "SELECT count(*) FROM communication_links") == 2
