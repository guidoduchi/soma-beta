from __future__ import annotations

import sqlite3
import uuid

import pytest

from soma.foundation.errors import IntegrityFailure, JobClaimConflict, ValidationError
from soma.foundation.jobs import (
    DurableJobCoordinator,
    JobTypeContract,
    JobTypeRegistry,
    StaleRecoveryDisposition,
)
from soma.foundation.persistence.uow import UnitOfWork


def _uuid() -> str:
    return str(uuid.uuid4())


class Clock:
    def __init__(self, value: int = 100) -> None:
        self.value = value

    def __call__(self) -> int:
        return self.value


def _validate_payload(value) -> None:
    if not isinstance(value, dict) or set(value) != {"key", "value"}:
        raise ValidationError("test payload shape")
    if not isinstance(value["key"], str) or not value["key"]:
        raise ValidationError("test payload key")
    if not isinstance(value["value"], int):
        raise ValidationError("test payload value")


def _validate_checkpoint(value) -> None:
    if not isinstance(value, dict) or set(value) != {"n"} or not isinstance(value["n"], int):
        raise ValidationError("test checkpoint shape")


def _contract() -> JobTypeContract:
    return JobTypeContract(
        job_type="test.job",
        contract_version=1,
        validate_payload=_validate_payload,
        validate_checkpoint=_validate_checkpoint,
        derive_dedupe_key=lambda payload: payload["key"],
        coalesce_states=frozenset(
            {"queued", "running", "waiting_review", "retry_wait", "completed"}
        ),
        retryable_error=lambda error_code: error_code == "TRANSIENT_TEST",
        recover_stale=lambda payload, checkpoint, now: StaleRecoveryDisposition(
            state="retry_wait", next_attempt_at_utc=now + 10, error_code="JOB_INTERRUPTED"
        ),
    )


def _coordinator(initialized_database, *, clock: Clock | None = None):
    database_path, factory_builder = initialized_database
    factory = factory_builder(database_path)
    clock = clock or Clock()
    return database_path, factory, clock, DurableJobCoordinator(
        factory, JobTypeRegistry([_contract()]), clock=clock
    )


def _enqueue(coordinator: DurableJobCoordinator, factory, *, key="alpha", value=1) -> str:
    with UnitOfWork(factory) as uow:
        return coordinator.enqueue_or_coalesce(
            uow, "test.job", 1, {"key": key, "value": value}, key
        )


def _job_row(database_path, job_id: str):
    connection = sqlite3.connect(database_path)
    try:
        return connection.execute(
            "SELECT state,attempt_count,next_attempt_at_utc,claimed_run_id,claim_started_at_utc,payload_json,checkpoint_json,last_error_code,dedupe_sha256 FROM durable_jobs WHERE job_id=?",
            (job_id,),
        ).fetchone()
    finally:
        connection.close()


def test_enqueue_coalesces_by_registered_semantic_key_without_persisting_raw_key(
    initialized_database,
) -> None:
    database_path, factory, _clock, coordinator = _coordinator(initialized_database)
    first = _enqueue(coordinator, factory)
    with UnitOfWork(factory) as uow:
        second = coordinator.enqueue_or_coalesce(
            uow, "test.job", 1, {"key": "alpha", "value": 1}, "alpha"
        )
    assert second == first
    row = _job_row(database_path, first)
    assert row[0] == "queued"
    assert row[5] == '{"key":"alpha","value":1}'
    assert len(row[8]) == 64
    assert row[8] != "alpha"

    with UnitOfWork(factory) as uow:
        with pytest.raises(ValidationError):
            coordinator.enqueue_or_coalesce(
                uow, "test.job", 1, {"key": "alpha", "value": 1}, "wrong"
            )
        with pytest.raises(ValidationError):
            coordinator.enqueue_or_coalesce(
                uow, "test.job", 1, {"key": "x" * 65537, "value": 1}, "x" * 65537
            )


def test_hash_candidate_payload_disagreement_and_duplicate_candidates_fail_closed(
    initialized_database,
) -> None:
    database_path, factory, clock, coordinator = _coordinator(initialized_database)
    job_id = _enqueue(coordinator, factory)
    with UnitOfWork(factory) as uow:
        uow.connection.execute(
            "UPDATE durable_jobs SET payload_json=? WHERE job_id=?",
            ('{"key":"beta","value":1}', job_id),
        )
    with UnitOfWork(factory) as uow:
        with pytest.raises(IntegrityFailure):
            coordinator.enqueue_or_coalesce(
                uow, "test.job", 1, {"key": "alpha", "value": 1}, "alpha"
            )

    with UnitOfWork(factory) as uow:
        uow.connection.execute(
            "UPDATE durable_jobs SET payload_json=? WHERE job_id=?",
            ('{"key":"alpha","value":1}', job_id),
        )
    claim = coordinator.claim_next(_uuid(), 101)
    assert claim is not None
    clock.value = 102
    coordinator.complete(claim)
    completed = _job_row(database_path, job_id)
    with UnitOfWork(factory) as uow:
        uow.connection.execute(
            "INSERT INTO durable_jobs(job_id,job_type,contract_version,state,created_at_utc,updated_at_utc,attempt_count,payload_json,dedupe_sha256) VALUES (?,?,?,?,?,?,?,?,?)",
            (_uuid(), "test.job", 1, "queued", 103, 103, 0, '{"key":"alpha","value":1}', completed[8]),
        )
    with UnitOfWork(factory) as uow:
        with pytest.raises(IntegrityFailure):
            coordinator.enqueue_or_coalesce(
                uow, "test.job", 1, {"key": "alpha", "value": 1}, "alpha"
            )


def test_claim_repeated_checkpoint_and_complete_preserve_exact_attempt_history(
    initialized_database,
) -> None:
    database_path, factory, clock, coordinator = _coordinator(initialized_database)
    job_id = _enqueue(coordinator, factory)
    run_id = _uuid()
    claim = coordinator.claim_next(run_id, 101)
    assert claim is not None
    assert claim.job_id == job_id
    assert claim.attempt_ordinal == 1
    assert claim.checkpoint_json is None

    clock.value = 102
    coordinator.checkpoint(claim, {"n": 1})
    clock.value = 103
    coordinator.checkpoint(claim, {"n": 2})
    clock.value = 104
    coordinator.complete(claim)

    row = _job_row(database_path, job_id)
    assert row[:5] == ("completed", 1, None, None, None)
    assert row[6] == '{"n":2}'
    connection = sqlite3.connect(database_path)
    try:
        attempts = connection.execute(
            "SELECT ordinal,run_id,started_at_utc,finished_at_utc,outcome,error_code FROM job_attempts WHERE job_id=?",
            (job_id,),
        ).fetchall()
    finally:
        connection.close()
    assert attempts == [(1, run_id, 101, 104, "completed", None)]
    clock.value = 105
    with pytest.raises(JobClaimConflict):
        coordinator.complete(claim)


def test_retry_wait_due_time_and_full_claim_token_reject_stale_attempt(
    initialized_database,
) -> None:
    database_path, factory, clock, coordinator = _coordinator(initialized_database)
    job_id = _enqueue(coordinator, factory)
    first = coordinator.claim_next(_uuid(), 101)
    assert first is not None
    clock.value = 102
    coordinator.fail(first, "TRANSIENT_TEST", 110)
    assert _job_row(database_path, job_id)[:3] == ("retry_wait", 1, 110)
    assert coordinator.claim_next(_uuid(), 109) is None
    second = coordinator.claim_next(_uuid(), 110)
    assert second is not None
    assert second.attempt_ordinal == 2

    clock.value = 111
    with pytest.raises(JobClaimConflict):
        coordinator.checkpoint(first, {"n": 9})
    coordinator.checkpoint(second, {"n": 2})
    clock.value = 112
    coordinator.complete(second)
    connection = sqlite3.connect(database_path)
    try:
        assert connection.execute(
            "SELECT ordinal,outcome,error_code FROM job_attempts WHERE job_id=? ORDER BY ordinal",
            (job_id,),
        ).fetchall() == [
            (1, "failed", "TRANSIENT_TEST"),
            (2, "completed", None),
        ]
    finally:
        connection.close()


def test_cancellation_is_same_uow_atomic_and_revokes_running_claim(initialized_database) -> None:
    database_path, factory, clock, coordinator = _coordinator(initialized_database)
    job_id = _enqueue(coordinator, factory)
    claim = coordinator.claim_next(_uuid(), 101)
    assert claim is not None
    clock.value = 102
    with pytest.raises(RuntimeError):
        with UnitOfWork(factory) as uow:
            result = coordinator.cancel(uow, job_id, "test.job", 1, object())
            assert result.claim_revoked is True
            raise RuntimeError("owning domain rejected cancellation")
    assert _job_row(database_path, job_id)[0] == "running"
    connection = sqlite3.connect(database_path)
    try:
        assert connection.execute(
            "SELECT COUNT(*) FROM job_attempts WHERE job_id=?", (job_id,)
        ).fetchone()[0] == 0
    finally:
        connection.close()

    clock.value = 103
    with UnitOfWork(factory) as uow:
        result = coordinator.cancel(uow, job_id, "test.job", 1, object())
    assert result.outcome == "CANCELLED"
    assert result.cancelled_attempt_ordinal == 1
    assert _job_row(database_path, job_id)[0] == "cancelled"
    clock.value = 104
    with pytest.raises(JobClaimConflict):
        coordinator.complete(claim)
    with UnitOfWork(factory) as uow:
        assert coordinator.cancel(uow, job_id, "test.job", 1, object()).outcome == "ALREADY_CANCELLED"


def test_unknown_contract_due_job_is_failed_safe_without_execution(initialized_database) -> None:
    database_path, factory, _clock, coordinator = _coordinator(initialized_database)
    job_id = _uuid()
    with UnitOfWork(factory) as uow:
        uow.connection.execute(
            "INSERT INTO durable_jobs(job_id,job_type,contract_version,state,created_at_utc,updated_at_utc,attempt_count,payload_json,dedupe_sha256) VALUES (?,?,?,?,?,?,?,?,?)",
            (job_id, "unknown.job", 1, "queued", 100, 100, 0, '{}', "a" * 64),
        )
    assert coordinator.claim_next(_uuid(), 101) is None
    row = _job_row(database_path, job_id)
    assert row[0] == "failed"
    assert row[7] == "JOB_CONTRACT_UNAVAILABLE"


def test_startup_recovery_terminalizes_legacy_null_jobs_and_is_idempotent(initialized_database) -> None:
    database_path, factory, _clock, coordinator = _coordinator(initialized_database)
    queued_id = _uuid()
    running_id = _uuid()
    stale_run = _uuid()
    with UnitOfWork(factory) as uow:
        uow.connection.execute(
            "INSERT INTO durable_jobs(job_id,job_type,contract_version,state,created_at_utc,updated_at_utc,attempt_count,payload_json) VALUES (?,?,?,?,?,?,?,?)",
            (queued_id, "legacy.job", 1, "queued", 50, 50, 0, '{}'),
        )
        uow.connection.execute(
            "INSERT INTO durable_jobs(job_id,job_type,contract_version,state,created_at_utc,updated_at_utc,attempt_count,claimed_run_id,claim_started_at_utc,payload_json) VALUES (?,?,?,?,?,?,?,?,?,?)",
            (running_id, "legacy.job", 1, "running", 50, 60, 1, stale_run, 60, '{}'),
        )
    summary = coordinator.recover_stale_claims(_uuid(), 100)
    assert summary.examined_count == 2
    assert summary.failed_count == 2
    assert summary.interrupted_count == 1
    assert _job_row(database_path, queued_id)[0] == "failed"
    assert _job_row(database_path, running_id)[0] == "failed"
    connection = sqlite3.connect(database_path)
    try:
        assert connection.execute(
            "SELECT ordinal,run_id,outcome,error_code FROM job_attempts WHERE job_id=?",
            (running_id,),
        ).fetchall() == [
            (1, stale_run, "interrupted", "LEGACY_JOB_DEDUPE_UNAVAILABLE")
        ]
    finally:
        connection.close()
    again = coordinator.recover_stale_claims(_uuid(), 101)
    assert again.examined_count == 0
    assert again.interrupted_count == 0


def test_stale_prior_run_recovery_records_interruption_before_retry(initialized_database) -> None:
    database_path, factory, _clock, coordinator = _coordinator(initialized_database)
    job_id = _enqueue(coordinator, factory)
    stale_run = _uuid()
    claim = coordinator.claim_next(stale_run, 101)
    assert claim is not None
    current_run = _uuid()
    summary = coordinator.recover_stale_claims(current_run, 200)
    assert summary.examined_count == 1
    assert summary.interrupted_count == 1
    assert summary.retry_wait_count == 1
    assert _job_row(database_path, job_id)[:3] == ("retry_wait", 1, 210)
    assert coordinator.claim_next(current_run, 209) is None
    next_claim = coordinator.claim_next(current_run, 210)
    assert next_claim is not None
    assert next_claim.attempt_ordinal == 2
    connection = sqlite3.connect(database_path)
    try:
        assert connection.execute(
            "SELECT ordinal,run_id,outcome,error_code FROM job_attempts WHERE job_id=?",
            (job_id,),
        ).fetchall() == [(1, stale_run, "interrupted", "JOB_INTERRUPTED")]
    finally:
        connection.close()


def test_restore_reconciliation_cancels_all_nonterminal_jobs_without_touching_completed(
    initialized_database,
) -> None:
    database_path, factory, clock, coordinator = _coordinator(initialized_database)
    queued_id = _enqueue(coordinator, factory, key="queued")
    running_id = _enqueue(coordinator, factory, key="running")
    completed_id = _enqueue(coordinator, factory, key="completed")
    running_claim = coordinator.claim_next(_uuid(), 101)
    assert running_claim is not None
    # The deterministic claim order uses creation time/job id, so classify by actual claimed identity.
    if running_claim.job_id != running_id:
        queued_id, running_id = running_id, running_claim.job_id
    second = coordinator.claim_next(_uuid(), 102)
    assert second is not None
    clock.value = 103
    coordinator.complete(second)
    completed_id = second.job_id

    clock.value = 200
    with UnitOfWork(factory) as uow:
        result = coordinator.reconcile_restored_jobs(uow, {"restore": "verified"})
    assert result.examined_nonterminal_count == 2
    assert result.cancelled_count == 2
    assert result.interrupted_attempt_count == 1
    assert result.unchanged_terminal_count == 1
    assert _job_row(database_path, completed_id)[0] == "completed"
    nonterminal_ids = {
        row[0]
        for row in sqlite3.connect(database_path).execute(
            "SELECT job_id FROM durable_jobs WHERE job_id<>?", (completed_id,)
        ).fetchall()
    }
    assert len(nonterminal_ids) == 2
    assert all(_job_row(database_path, job_id)[0] == "cancelled" for job_id in nonterminal_ids)
    connection = sqlite3.connect(database_path)
    try:
        assert connection.execute(
            "SELECT ordinal,outcome,error_code FROM job_attempts WHERE job_id=?",
            (running_claim.job_id,),
        ).fetchall() == [
            (1, "interrupted", "RESTORE_SNAPSHOT_JOB_INVALIDATED")
        ]
    finally:
        connection.close()
