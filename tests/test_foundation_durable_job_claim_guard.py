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
        raise ValidationError("claim-guard payload shape")
    if not isinstance(value["key"], str) or not value["key"]:
        raise ValidationError("claim-guard payload key")
    if not isinstance(value["value"], int):
        raise ValidationError("claim-guard payload value")


def _validate_checkpoint(value) -> None:
    if not isinstance(value, dict) or set(value) != {"n"} or not isinstance(value["n"], int):
        raise ValidationError("claim-guard checkpoint shape")


def _contract() -> JobTypeContract:
    return JobTypeContract(
        job_type="test.claim_guard",
        contract_version=1,
        validate_payload=_validate_payload,
        validate_checkpoint=_validate_checkpoint,
        derive_dedupe_key=lambda payload: payload["key"],
        coalesce_states=frozenset(
            {"queued", "running", "waiting_review", "retry_wait", "completed"}
        ),
        validate_failure=lambda error_code, attempt_ordinal, now, retry_at: None,
        validate_cancellation=lambda context, state: (
            None
            if context == {"allow": True}
            else (_ for _ in ()).throw(ValidationError("claim-guard cancellation denied"))
        ),
        recover_stale=lambda payload, checkpoint, attempt_ordinal, now: StaleRecoveryDisposition(
            state="retry_wait",
            next_attempt_at_utc=now + 10,
            error_code="JOB_INTERRUPTED",
        ),
    )


def _coordinator(initialized_database):
    database_path, factory_builder = initialized_database
    factory = factory_builder(database_path)
    clock = Clock()
    coordinator = DurableJobCoordinator(
        factory,
        JobTypeRegistry([_contract()]),
        clock=clock,
    )
    return database_path, factory, clock, coordinator


def _enqueue(coordinator: DurableJobCoordinator, factory, *, key: str = "alpha") -> str:
    with UnitOfWork(factory) as uow:
        return coordinator.enqueue_or_coalesce(
            uow,
            "test.claim_guard",
            1,
            {"key": key, "value": 1},
            key,
        )


def _job_row(database_path, job_id: str):
    connection = sqlite3.connect(database_path)
    try:
        return connection.execute(
            "SELECT state,attempt_count,claimed_run_id,claim_started_at_utc,payload_json,"
            "checkpoint_json,dedupe_sha256,last_error_code FROM durable_jobs WHERE job_id=?",
            (job_id,),
        ).fetchone()
    finally:
        connection.close()


def _attempt_count(database_path, job_id: str) -> int:
    connection = sqlite3.connect(database_path)
    try:
        return int(
            connection.execute(
                "SELECT COUNT(*) FROM job_attempts WHERE job_id=?",
                (job_id,),
            ).fetchone()[0]
        )
    finally:
        connection.close()


def test_owner_guard_accepts_current_claim_after_checkpoint_advances(initialized_database) -> None:
    database_path, factory, clock, coordinator = _coordinator(initialized_database)
    job_id = _enqueue(coordinator, factory)
    claim = coordinator.claim_next(_uuid(), 101)
    assert claim is not None
    assert claim.checkpoint_json is None

    clock.value = 102
    coordinator.checkpoint(claim, {"n": 1})
    before = _job_row(database_path, job_id)
    assert before[0:2] == ("running", 1)
    assert before[5] == '{"n":1}'

    with UnitOfWork(factory) as uow:
        coordinator.assert_claim_current(uow, claim)

    assert _job_row(database_path, job_id) == before
    assert _attempt_count(database_path, job_id) == 0


def test_owner_guard_rejects_committed_cancellation_without_new_history(initialized_database) -> None:
    database_path, factory, clock, coordinator = _coordinator(initialized_database)
    job_id = _enqueue(coordinator, factory)
    claim = coordinator.claim_next(_uuid(), 101)
    assert claim is not None

    clock.value = 102
    with UnitOfWork(factory) as uow:
        result = coordinator.cancel(
            uow,
            job_id,
            "test.claim_guard",
            1,
            {"allow": True},
        )
    assert result.outcome == "CANCELLED"
    assert _attempt_count(database_path, job_id) == 1
    before = _job_row(database_path, job_id)

    with pytest.raises(JobClaimConflict):
        with UnitOfWork(factory) as uow:
            coordinator.assert_claim_current(uow, claim)

    assert _job_row(database_path, job_id) == before
    assert _attempt_count(database_path, job_id) == 1


def test_owner_guard_rejects_recovered_attempt_and_accepts_reclaim(initialized_database) -> None:
    database_path, factory, _clock, coordinator = _coordinator(initialized_database)
    job_id = _enqueue(coordinator, factory)
    stale_run = _uuid()
    stale_claim = coordinator.claim_next(stale_run, 101)
    assert stale_claim is not None

    current_run = _uuid()
    summary = coordinator.recover_stale_claims(current_run, 200)
    assert summary.interrupted_count == 1
    assert summary.retry_wait_count == 1
    assert _job_row(database_path, job_id)[0] == "retry_wait"

    current_claim = coordinator.claim_next(current_run, 210)
    assert current_claim is not None
    assert current_claim.attempt_ordinal == 2

    with pytest.raises(JobClaimConflict):
        with UnitOfWork(factory) as uow:
            coordinator.assert_claim_current(uow, stale_claim)

    with UnitOfWork(factory) as uow:
        coordinator.assert_claim_current(uow, current_claim)

    assert _job_row(database_path, job_id)[0:2] == ("running", 2)
    assert _attempt_count(database_path, job_id) == 1


def test_owner_guard_fails_closed_on_current_checkpoint_payload_or_dedupe_corruption(
    initialized_database,
) -> None:
    database_path, factory, _clock, coordinator = _coordinator(initialized_database)
    job_id = _enqueue(coordinator, factory)
    claim = coordinator.claim_next(_uuid(), 101)
    assert claim is not None

    with UnitOfWork(factory) as uow:
        uow.connection.execute(
            "UPDATE durable_jobs SET checkpoint_json=? WHERE job_id=?",
            ('{"bad":1}', job_id),
        )
    with pytest.raises(IntegrityFailure):
        with UnitOfWork(factory) as uow:
            coordinator.assert_claim_current(uow, claim)

    with UnitOfWork(factory) as uow:
        uow.connection.execute(
            "UPDATE durable_jobs SET checkpoint_json=? WHERE job_id=?",
            ('{"n":1}', job_id),
        )
    with UnitOfWork(factory) as uow:
        coordinator.assert_claim_current(uow, claim)

    with UnitOfWork(factory) as uow:
        uow.connection.execute(
            "UPDATE durable_jobs SET payload_json=? WHERE job_id=?",
            ('{"key":"beta","value":1}', job_id),
        )
    with pytest.raises(IntegrityFailure):
        with UnitOfWork(factory) as uow:
            coordinator.assert_claim_current(uow, claim)

    with UnitOfWork(factory) as uow:
        uow.connection.execute(
            "UPDATE durable_jobs SET payload_json=?,dedupe_sha256=? WHERE job_id=?",
            (claim.payload_json, "a" * 64, job_id),
        )
    with pytest.raises(IntegrityFailure):
        with UnitOfWork(factory) as uow:
            coordinator.assert_claim_current(uow, claim)

    assert _job_row(database_path, job_id)[0:2] == ("running", 1)
    assert _attempt_count(database_path, job_id) == 0
