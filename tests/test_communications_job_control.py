import json
import sqlite3

import pytest

from soma.communications.contracts.jobs import CommunicationJobCheckpoint, CommunicationJobCounters, CommunicationJobScope
from soma.communications.jobs.communications import JOB_TYPES, dedupe_key
from soma.communications.services.job_control import CommunicationJobControlService
from soma.foundation.errors import JobClaimConflict, ValidationError
from soma.foundation.identifiers import new_uuid4
from soma.foundation.persistence.uow import UnitOfWork
from soma.foundation.strict_json import canonical_json_bytes
from test_communications_job_queries import setup


def test_cancel_queued_exact_replay_no_change_and_immutable_evidence(communication_database):
    path, factory, _, clock, jobs, enqueue, query = setup(communication_database)
    job = enqueue()
    service = CommunicationJobControlService(factory, jobs)
    request = {"command_id": new_uuid4(), "job_id": job}
    clock[0] = 1005
    applied = service.cancel_job(request)
    assert applied == {"status": "APPLIED", "job_id": job, "prior_state": "queued", "resulting_state": "cancelled",
                       "cancellation_event_id": applied["cancellation_event_id"]}
    assert service.cancel_job(request) == applied
    assert service.cancel_job({**request, "command_id": new_uuid4()}) == {
        **applied, "status": "NO_CHANGE", "prior_state": "cancelled", "cancellation_event_id": None}
    with sqlite3.connect(path) as db:
        assert db.execute("SELECT prior_state,claim_revoked,cancelled_attempt_ordinal,recorded_at_utc,command_id FROM communication_job_cancellation_events").fetchall() == [("queued", 0, None, 1005, request["command_id"])]
        assert db.execute("SELECT count(*) FROM audit_events WHERE action_type='communications.job.cancelled'").fetchone() == (1,)
        assert db.execute("SELECT count(*) FROM command_receipts WHERE command_type='CancelCommunicationJob'").fetchone() == (2,)
        assert db.execute("SELECT count(*) FROM job_attempts WHERE job_id=?", (job,)).fetchone() == (0,)
        for sql in ("UPDATE communication_job_cancellation_events SET recorded_at_utc=1006", "DELETE FROM communication_job_cancellation_events"):
            with pytest.raises(sqlite3.IntegrityError):
                db.execute(sql)
    row = query.list_jobs({})["items"][0]
    assert row["cancellation_requested"] and row["ended_at_utc"] is None


def test_running_cancel_revokes_claim_and_preserves_committed_checkpoint_counters(communication_database):
    path, factory, source, clock, jobs, enqueue, query = setup(communication_database)
    job = enqueue()
    claim = jobs.claim_next(new_uuid4(), 1000)
    scope = CommunicationJobScope.from_value(json.loads(claim.payload_json))
    checkpoint = CommunicationJobCheckpoint(scope, None, CommunicationJobCounters(inspected=7, unchanged=7), ())
    with UnitOfWork(factory) as writer:
        jobs.checkpoint_in_uow(writer, claim, checkpoint.to_response())
        writer.connection.execute("UPDATE communication_job_counters SET inspected=7,unchanged=7,revision=2 WHERE job_id=?", (job,))
    # Changed source availability and revision cannot strand a running job.
    with sqlite3.connect(path) as db:
        db.execute("UPDATE communication_source_scopes SET revision=revision+1,health_state='MISSING',processing_enabled=0 WHERE source_scope_id=?", (source,))
        prior_checkpoint = db.execute("SELECT checkpoint_json FROM durable_jobs WHERE job_id=?", (job,)).fetchone()[0]
    clock[0] = 1010
    result = CommunicationJobControlService(factory, jobs).cancel_job({"command_id": new_uuid4(), "job_id": job})
    assert result["prior_state"] == "running"
    with pytest.raises(JobClaimConflict):
        jobs.complete(claim)
    with sqlite3.connect(path) as db:
        assert db.execute("SELECT state,checkpoint_json,claimed_run_id,claim_started_at_utc FROM durable_jobs WHERE job_id=?", (job,)).fetchone() == ("cancelled", prior_checkpoint, None, None)
        assert db.execute("SELECT inspected,unchanged,revision FROM communication_job_counters WHERE job_id=?", (job,)).fetchone() == (7, 7, 2)
        assert db.execute("SELECT claim_revoked,cancelled_attempt_ordinal FROM communication_job_cancellation_events").fetchone() == (1, 1)
        assert db.execute("SELECT outcome,finished_at_utc FROM job_attempts WHERE job_id=?", (job,)).fetchone() == ("cancelled", 1010)
    assert query.list_jobs({})["items"][0]["ended_at_utc"] == 1010


@pytest.mark.parametrize("state", ["completed", "failed", "retry_wait", "waiting_review"])
def test_terminal_no_change_and_other_active_states(communication_database, state):
    path, factory, _, clock, jobs, enqueue, _ = setup(communication_database)
    job = enqueue()
    if state in {"completed", "failed", "retry_wait"}:
        claim = jobs.claim_next(new_uuid4(), 1000)
        clock[0] = 1005
        if state == "completed":
            jobs.complete(claim)
        else:
            jobs.fail(claim, "SOURCE_LOCKED", 1015 if state == "retry_wait" else None)
    else:
        with sqlite3.connect(path) as db:
            db.execute("UPDATE durable_jobs SET state='waiting_review' WHERE job_id=?", (job,))
    result = CommunicationJobControlService(factory, jobs).cancel_job({"command_id": new_uuid4(), "job_id": job})
    terminal = state in {"completed", "failed"}
    assert result["status"] == ("NO_CHANGE" if terminal else "APPLIED")
    assert result["prior_state"] == state and result["resulting_state"] == (state if terminal else "cancelled")
    with sqlite3.connect(path) as db:
        assert db.execute("SELECT count(*) FROM communication_job_cancellation_events").fetchone() == (int(not terminal),)
        assert db.execute("SELECT count(*) FROM audit_events WHERE action_type='communications.job.cancelled'").fetchone() == (int(not terminal),)
        assert db.execute("SELECT next_attempt_at_utc FROM durable_jobs WHERE job_id=?", (job,)).fetchone() == (None,)


def test_cancel_audit_failure_rolls_back_claim_attempt_event_and_receipt(communication_database, monkeypatch):
    path, factory, _, clock, jobs, enqueue, _ = setup(communication_database)
    job = enqueue()
    claim = jobs.claim_next(new_uuid4(), 1000)
    clock[0] = 1010
    service = CommunicationJobControlService(factory, jobs)
    request = {"command_id": new_uuid4(), "job_id": job}
    original = service._boundary._audit_writer.write
    def fail(*args):
        raise RuntimeError("injected cancellation audit failure")
    monkeypatch.setattr(service._boundary._audit_writer, "write", fail)
    with pytest.raises(RuntimeError):
        service.cancel_job(request)
    with sqlite3.connect(path) as db:
        assert db.execute("SELECT state,claimed_run_id FROM durable_jobs WHERE job_id=?", (job,)).fetchone() == ("running", claim.run_id)
        assert db.execute("SELECT count(*) FROM job_attempts WHERE job_id=?", (job,)).fetchone() == (0,)
        assert db.execute("SELECT count(*) FROM communication_job_cancellation_events").fetchone() == (0,)
        assert db.execute("SELECT count(*) FROM command_receipts WHERE command_id=?", (request["command_id"],)).fetchone() == (0,)
    monkeypatch.setattr(service._boundary._audit_writer, "write", original)
    assert service.cancel_job(request)["status"] == "APPLIED"


def test_global_housekeeping_cancellation_and_strict_request_ownership(communication_database):
    path, factory, _, _, jobs, _, _ = setup(communication_database)
    scope = CommunicationJobScope(None, (), "ORPHAN_HOUSEKEEPING", None, None, (), None).to_response()
    with UnitOfWork(factory) as writer:
        job = jobs.enqueue_or_coalesce(writer, JOB_TYPES["ORPHAN_HOUSEKEEPING"], 1, scope, dedupe_key(scope))
        writer.connection.execute("INSERT INTO communication_job_scopes VALUES(?,'ORPHAN_HOUSEKEEPING',NULL,?,NULL,1000,NULL,NULL)", (job, canonical_json_bytes(scope).decode()))
        unowned_scope = CommunicationJobScope(new_uuid4(), (), "ORDINARY", None, None, (), 1).to_response()
        unowned = jobs.enqueue_or_coalesce(writer, JOB_TYPES["ORDINARY"], 1, unowned_scope, dedupe_key(unowned_scope))
    service = CommunicationJobControlService(factory, jobs)
    for payload in ({"command_id": new_uuid4(), "job_id": unowned}, {"command_id": new_uuid4(), "job_id": new_uuid4()},
                    {"command_id": new_uuid4(), "job_id": job, "unsafe_payload": "private"}, {"command_id": new_uuid4(), "job_id": True}):
        with pytest.raises(ValidationError):
            service.cancel_job(payload)
    assert service.cancel_job({"command_id": new_uuid4(), "job_id": job})["status"] == "APPLIED"
    with sqlite3.connect(path) as db:
        assert db.execute("SELECT state FROM durable_jobs WHERE job_id=?", (unowned,)).fetchone() == ("queued",)
        assert db.execute("SELECT job_kind FROM communication_job_cancellation_events").fetchone() == ("ORPHAN_HOUSEKEEPING",)
