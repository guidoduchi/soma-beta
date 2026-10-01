import json
import sqlite3

import pytest

from soma.communications.contracts.jobs import CommunicationJobScope
from soma.communications.jobs.communications import COMMUNICATION_JOB_CONTRACTS, JOB_TYPES, dedupe_key
from soma.communications.queries.jobs import JobQueries
from soma.foundation.errors import IntegrityFailure, ValidationError
from soma.foundation.identifiers import new_uuid4
from soma.foundation.jobs import DurableJobCoordinator, JobTypeRegistry
from soma.foundation.persistence.uow import UnitOfWork
from soma.foundation.queries.jobs import DURABLE_JOB_METADATA_V1
from soma.foundation.strict_json import canonical_json_bytes
from test_communications_processing_requests import setup_processing


def setup(database):
    path, factory, source, _, service, _, _ = setup_processing(database)
    clock = [1000]
    jobs = DurableJobCoordinator(factory, JobTypeRegistry(COMMUNICATION_JOB_CONTRACTS), clock=lambda: clock[0])
    service._jobs = jobs
    def enqueue():
        return service.start_processing({"command_id": new_uuid4(), "source_scope_id": source, "source_scope_revision": 1})["job_id"]
    return path, factory, source, clock, jobs, enqueue, JobQueries(factory)


def test_job_summary_uses_recorded_state_and_attempt_chronology(communication_database):
    _, _, source, clock, jobs, enqueue, query = setup(communication_database)
    identity = enqueue()
    row = query.list_jobs({})["items"][0]
    assert row["job_id"] == identity and row["source_scope_id"] == source and row["state"] == "queued"
    assert row["created_at_utc"] == row["updated_at_utc"] == 1000
    assert row["started_at_utc"] is None and row["ended_at_utc"] is None and row["percentage"] is None and row["phase"] is None
    clock[0] = 1005
    claim = jobs.claim_next(new_uuid4(), 1005)
    row = query.list_jobs({"state": "running"})["items"][0]
    assert row["started_at_utc"] == 1005 and row["ended_at_utc"] is None and row["attempt_count"] == 1
    clock[0] = 1010
    jobs.complete(claim)
    row = query.list_jobs({"state": "completed"})["items"][0]
    assert row["started_at_utc"] == 1005 and row["ended_at_utc"] == row["updated_at_utc"] == 1010
    assert row["percentage"] is None and row["cancellation_requested"] is False


def test_retry_and_cancellation_do_not_invent_job_end_time(communication_database):
    _, factory, _, clock, jobs, enqueue, query = setup(communication_database)
    identity = enqueue()
    clock[0] = 1005
    claim = jobs.claim_next(new_uuid4(), 1005)
    clock[0] = 1010
    jobs.fail(claim, "SOURCE_LOCKED", 1020)
    row = query.list_jobs({})["items"][0]
    assert row["state"] == "retry_wait" and row["diagnostic_code"] == "SOURCE_LOCKED" and row["next_attempt_at_utc"] == 1020
    assert row["started_at_utc"] == 1005 and row["ended_at_utc"] is None
    clock[0] = 1011
    with UnitOfWork(factory) as uow:
        jobs.cancel(uow, identity, JOB_TYPES["ORDINARY"], 1, {"command_id": new_uuid4()})
    row = query.list_jobs({})["items"][0]
    assert row["state"] == "cancelled" and row["cancellation_requested"] is True
    assert row["ended_at_utc"] is None and row["next_attempt_at_utc"] is None
    assert row["started_at_utc"] == 1005


def test_retries_preserve_first_start_and_terminal_attempt_end(communication_database):
    _, _, _, clock, jobs, enqueue, query = setup(communication_database)
    enqueue()
    first = jobs.claim_next(new_uuid4(), 1001)
    clock[0] = 1005
    jobs.fail(first, "SOURCE_LOCKED", 1015)
    clock[0] = 1035
    second = jobs.claim_next(new_uuid4(), 1035)
    clock[0] = 1040
    jobs.complete(second)
    row = query.list_jobs({})["items"][0]
    assert row["started_at_utc"] == 1001 and row["ended_at_utc"] == 1040 and row["attempt_count"] == 2


def test_job_pages_timestamp_uuid_ties_and_bind_all_filters(communication_database):
    _, _, source, clock, jobs, enqueue, query = setup(communication_database)
    ids = []
    for _ in range(6):
        ids.append(enqueue())
        jobs.complete(jobs.claim_next(new_uuid4(), 1000))
    clock[0] = 1001
    ids.append(enqueue())
    expected = [ids[-1], *sorted(ids[:-1], reverse=True)]
    cursor, actual = None, []
    while True:
        page = query.list_jobs({"source_scope_id": source, "limit": 1, "cursor": cursor})
        actual.extend(row["job_id"] for row in page["items"])
        cursor = page["next_cursor"]
        if cursor is None:
            break
        assert len(cursor["last_key_tuple"]) == 2
    assert actual == expected
    assert query.list_jobs({"state": "queued"})["items"][0]["job_id"] == ids[-1]
    assert len(query.list_jobs({"state": "completed", "job_kind": "ORDINARY"})["items"]) == 6
    assert query.list_jobs({"source_scope_id": new_uuid4()})["items"] == []
    cursor = query.list_jobs({"limit": 1})["next_cursor"]
    for value in ({"state": "queued", "cursor": cursor}, {"cursor": cursor | {"last_key_tuple": [1001]}}):
        with pytest.raises(ValidationError):
            query.list_jobs(value)


def test_global_housekeeping_job_joins_scope_and_recorded_counters(communication_database):
    path, factory = communication_database
    jobs = DurableJobCoordinator(factory, JobTypeRegistry(COMMUNICATION_JOB_CONTRACTS), clock=lambda: 100)
    scope = CommunicationJobScope(None, (), "ORPHAN_HOUSEKEEPING", None, None, (), None).to_response()
    with UnitOfWork(factory) as uow:
        identity = jobs.enqueue_or_coalesce(uow, JOB_TYPES["ORPHAN_HOUSEKEEPING"], 1, scope, dedupe_key(scope))
        uow.connection.execute("INSERT INTO communication_job_scopes VALUES(?,'ORPHAN_HOUSEKEEPING',NULL,?,NULL,100,NULL,NULL)",
                               (identity, canonical_json_bytes(scope).decode()))
        uow.connection.execute("INSERT INTO communication_job_counters VALUES(?,10,5,0,0,0,0,0,0,0,10,1,100)", (identity,))
    row = JobQueries(factory).list_jobs({"job_kind": "ORPHAN_HOUSEKEEPING"})["items"][0]
    assert row["source_scope_id"] is None and row["percentage"] == 50 and row["phase"] is None
    with sqlite3.connect(path) as db:
        db.execute("UPDATE communication_job_counters SET estimated_total=0")
    assert JobQueries(factory).list_jobs({})["items"][0]["percentage"] is None


def test_foundation_projection_is_read_only_and_excludes_private_job_material(communication_database):
    path, _, _, _, _, enqueue, query = setup(communication_database)
    identity = enqueue()
    with sqlite3.connect(path) as db:
        columns = {row[1] for row in db.execute(f"PRAGMA table_info({DURABLE_JOB_METADATA_V1})")}
        assert not columns & {"payload_json", "checkpoint_json", "claimed_run_id", "claim_started_at_utc", "dedupe_sha256"}
        with pytest.raises(sqlite3.OperationalError):
            db.execute(f"UPDATE {DURABLE_JOB_METADATA_V1} SET state='completed'")
        db.execute("UPDATE durable_jobs SET last_error_code='SecretCanary/private/path' WHERE job_id=?", (identity,))
    row = query.list_jobs({})["items"][0]
    assert row["diagnostic_code"] is None and "SecretCanary" not in json.dumps(row)


def test_job_query_detects_missing_counter_authority_and_rejects_unknown_fields(communication_database):
    path, _, _, _, _, enqueue, query = setup(communication_database)
    identity = enqueue()
    with pytest.raises(ValidationError):
        query.list_jobs({"payload": "mail body"})
    with pytest.raises(ValidationError):
        query.list_jobs({"state": "made_up"})
    with sqlite3.connect(path) as db:
        db.execute("DELETE FROM communication_job_counters WHERE job_id=?", (identity,))
    with pytest.raises(IntegrityFailure):
        query.list_jobs({})
