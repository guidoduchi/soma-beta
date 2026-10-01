import json
import sqlite3

import pytest

from soma.communications.contracts.jobs import CommunicationJobScope
from soma.communications.jobs.communications import COMMUNICATION_JOB_CONTRACTS, JOB_TYPES, dedupe_key
from soma.communications.jobs.housekeeping import CommunicationHousekeepingWorker
from soma.communications.services.housekeeping import HousekeepingService
from soma.communications.services.job_control import CommunicationJobControlService
from soma.foundation.errors import JobClaimConflict, SomaError
from soma.foundation.identifiers import new_uuid4
from soma.foundation.jobs import DurableJobCoordinator, JobTypeRegistry
from soma.foundation.persistence.uow import UnitOfWork
from soma.foundation.strict_json import canonical_json_bytes
from test_communications_housekeeping import seed, search_count


def setup(database):
    path, factory = database
    clock = [1000]
    jobs = DurableJobCoordinator(factory, JobTypeRegistry(COMMUNICATION_JOB_CONTRACTS), clock=lambda: clock[0])
    scope = CommunicationJobScope(None, (), "ORPHAN_HOUSEKEEPING", None, None, (), None).to_response()
    with UnitOfWork(factory) as writer:
        job = jobs.enqueue_or_coalesce(writer, JOB_TYPES["ORPHAN_HOUSEKEEPING"], 1, scope, dedupe_key(scope))
        writer.connection.execute("INSERT INTO communication_job_scopes VALUES(?,'ORPHAN_HOUSEKEEPING',NULL,?,NULL,1000,NULL,NULL)", (job, canonical_json_bytes(scope).decode()))
        writer.connection.execute("INSERT INTO communication_job_counters VALUES(?,0,0,0,0,0,0,0,0,0,NULL,1,1000)", (job,))
    service = HousekeepingService(factory)
    worker = CommunicationHousekeepingWorker(factory, service, jobs, clock=lambda: clock[0])
    return path, factory, clock, jobs, job, service, worker


def test_housekeeping_runs_while_fetching_disabled_and_atomically_records_each_candidate(communication_database):
    path, factory, _, jobs, job, _, worker = setup(communication_database)
    purged, protected, future = seed(path), seed(path), seed(path, due=2000)
    with sqlite3.connect(path) as db:
        db.execute("INSERT INTO communication_protection_holds VALUES(?,?,'PROTECTED_EXPORT',?,'ACTIVE',500,NULL)", (new_uuid4(), protected, new_uuid4()))
    result = worker.run(jobs.claim_next(new_uuid4(), 1000))
    assert result["inspected"] == result["discovered"] == 2 and result["estimated_total"] is None
    with sqlite3.connect(path) as db:
        assert dict(db.execute("SELECT communication_id,state FROM communication_retention")) == {purged: "PURGED", protected: "RETAINED", future: "ORPHAN_PENDING_PURGE"}
        state, checkpoint = db.execute("SELECT state,checkpoint_json FROM durable_jobs WHERE job_id=?", (job,)).fetchone()
        assert state == "completed" and json.loads(checkpoint)["counters"] == result
        assert db.execute("SELECT inspected,revision FROM communication_job_counters WHERE job_id=?", (job,)).fetchone() == (2, 3)
        assert db.execute("SELECT count(*) FROM communication_retention_events").fetchone() == (2,)
        assert search_count(db) == 2
        assert db.execute("SELECT count(*) FROM communication_forward_coverage").fetchone() == (0,)


def test_housekeeping_audit_rollback_and_registered_retry_preserve_content_and_progress(communication_database, monkeypatch):
    path, _, clock, jobs, job, service, worker = setup(communication_database)
    comm = seed(path)
    original = service._boundary._audit_writer.write
    def fail(*args):
        raise SomaError("PERSISTENCE_BUSY", "private path or source body must never escape")
    monkeypatch.setattr(service._boundary._audit_writer, "write", fail)
    claim = jobs.claim_next(new_uuid4(), 1000)
    with pytest.raises(SomaError) as failure:
        worker.run(claim)
    assert failure.value.code == "PERSISTENCE_BUSY" and "private" not in str(failure.value)
    with sqlite3.connect(path) as db:
        assert db.execute("SELECT state,checkpoint_json,next_attempt_at_utc FROM durable_jobs WHERE job_id=?", (job,)).fetchone() == ("retry_wait", None, 1060)
        assert db.execute("SELECT state,revision FROM communication_retention WHERE communication_id=?", (comm,)).fetchone() == ("ORPHAN_PENDING_PURGE", 1)
        assert db.execute("SELECT inspected,revision FROM communication_job_counters WHERE job_id=?", (job,)).fetchone() == (0, 1)
        assert search_count(db) == 1
    monkeypatch.setattr(service._boundary._audit_writer, "write", original)
    clock[0] = 1060
    assert worker.run(jobs.claim_next(new_uuid4(), 1060))["inspected"] == 1


def test_housekeeping_crash_after_committed_candidate_resumes_without_double_count(communication_database, monkeypatch):
    path, _, clock, jobs, job, service, worker = setup(communication_database)
    seed(path)
    seed(path)
    original = service.purge_due_claim
    class SimulatedProcessDeath(BaseException):
        pass
    def crash(*args, **kwargs):
        original(*args, **kwargs)
        raise SimulatedProcessDeath()
    monkeypatch.setattr(service, "purge_due_claim", crash)
    first = jobs.claim_next(new_uuid4(), 1000)
    with pytest.raises(SimulatedProcessDeath):
        worker.run(first)
    with sqlite3.connect(path) as db:
        assert db.execute("SELECT inspected FROM communication_job_counters WHERE job_id=?", (job,)).fetchone() == (1,)
        assert db.execute("SELECT count(*) FROM communications WHERE content_state='PURGED'").fetchone() == (1,)
    monkeypatch.setattr(service, "purge_due_claim", original)
    clock[0] = 2000
    jobs.recover_stale_claims(new_uuid4(), 2000)
    second = jobs.claim_next(new_uuid4(), 2000)
    assert second.attempt_ordinal == 2
    assert worker.run(second)["inspected"] == 2
    with sqlite3.connect(path) as db:
        assert db.execute("SELECT count(*) FROM communication_retention_events").fetchone() == (2,)
        assert db.execute("SELECT state FROM durable_jobs WHERE job_id=?", (job,)).fetchone() == ("completed",)


def test_housekeeping_cancellation_between_candidates_preserves_committed_work(communication_database, monkeypatch):
    path, factory, _, jobs, job, service, worker = setup(communication_database)
    seed(path)
    seed(path)
    cancel = CommunicationJobControlService(factory, jobs)
    original = service.purge_due_claim
    def cancel_after_commit(*args, **kwargs):
        result = original(*args, **kwargs)
        cancel.cancel_job({"command_id": new_uuid4(), "job_id": job})
        return result
    monkeypatch.setattr(service, "purge_due_claim", cancel_after_commit)
    with pytest.raises(JobClaimConflict):
        worker.run(jobs.claim_next(new_uuid4(), 1000))
    with sqlite3.connect(path) as db:
        assert db.execute("SELECT state FROM durable_jobs WHERE job_id=?", (job,)).fetchone() == ("cancelled",)
        assert db.execute("SELECT inspected FROM communication_job_counters WHERE job_id=?", (job,)).fetchone() == (1,)
        assert db.execute("SELECT count(*) FROM communications WHERE content_state='PURGED'").fetchone() == (1,)
        assert db.execute("SELECT count(*) FROM communications WHERE content_state='RETAINED'").fetchone() == (1,)


def test_empty_housekeeping_finishes_without_fabricated_content_audit(communication_database):
    path, _, _, jobs, job, _, worker = setup(communication_database)
    assert worker.run(jobs.claim_next(new_uuid4(), 1000))["inspected"] == 0
    with sqlite3.connect(path) as db:
        assert db.execute("SELECT count(*) FROM audit_events").fetchone() == (0,)
        assert db.execute("SELECT state,checkpoint_json FROM durable_jobs WHERE job_id=?", (job,)).fetchone() == ("completed", None)
