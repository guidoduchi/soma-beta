from __future__ import annotations

import sqlite3
import uuid

from soma.foundation.errors import ValidationError
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
    if value != {"key": "terminal"}:
        raise ValidationError("terminal test payload")


def _validate_checkpoint(value) -> None:
    if value != {"n": 1}:
        raise ValidationError("terminal test checkpoint")


def _validate_failure(error_code: str, attempt_ordinal: int, now: int, retry_at: int | None) -> None:
    if retry_at is not None:
        raise ValidationError("terminal test does not retry")


def _validate_cancellation(command_context, state: str) -> None:
    if command_context != {"allow": True}:
        raise ValidationError("terminal test cancellation denied")


def _contract() -> JobTypeContract:
    return JobTypeContract(
        job_type="terminal.test",
        contract_version=1,
        validate_payload=_validate_payload,
        validate_checkpoint=_validate_checkpoint,
        derive_dedupe_key=lambda payload: payload["key"],
        coalesce_states=frozenset(
            {"queued", "running", "waiting_review", "retry_wait", "completed"}
        ),
        validate_failure=_validate_failure,
        validate_cancellation=_validate_cancellation,
        recover_stale=lambda payload, checkpoint, ordinal, now: StaleRecoveryDisposition(
            state="failed", error_code="JOB_INTERRUPTED"
        ),
    )


def _coordinator(initialized_database):
    database_path, factory_builder = initialized_database
    factory = factory_builder(database_path)
    clock = Clock()
    coordinator = DurableJobCoordinator(factory, JobTypeRegistry([_contract()]), clock=clock)
    return database_path, factory, clock, coordinator


def _enqueue(coordinator: DurableJobCoordinator, factory) -> str:
    with UnitOfWork(factory) as uow:
        return coordinator.enqueue_or_coalesce(
            uow,
            "terminal.test",
            1,
            {"key": "terminal"},
            "terminal",
        )


def test_terminal_cancellation_replay_precedes_packet_authorization(initialized_database) -> None:
    database_path, factory, clock, coordinator = _coordinator(initialized_database)

    cancelled_id = _enqueue(coordinator, factory)
    with UnitOfWork(factory) as uow:
        first = coordinator.cancel(
            uow,
            cancelled_id,
            "terminal.test",
            1,
            {"allow": True},
        )
    assert first.outcome == "CANCELLED"

    with UnitOfWork(factory) as uow:
        replay = coordinator.cancel(
            uow,
            cancelled_id,
            "terminal.test",
            1,
            {"allow": False},
        )
    assert replay.outcome == "ALREADY_CANCELLED"

    completed_id = _enqueue(coordinator, factory)
    claim = coordinator.claim_next(_uuid(), 101)
    assert claim is not None
    assert claim.job_id == completed_id
    clock.value = 102
    coordinator.complete(claim)

    with UnitOfWork(factory) as uow:
        terminal = coordinator.cancel(
            uow,
            completed_id,
            "terminal.test",
            1,
            {"allow": False},
        )
    assert terminal.outcome == "TERMINAL_UNCHANGED"
    assert terminal.resulting_state == "completed"

    connection = sqlite3.connect(database_path)
    try:
        assert connection.execute(
            "SELECT state FROM durable_jobs WHERE job_id=?",
            (cancelled_id,),
        ).fetchone() == ("cancelled",)
        assert connection.execute(
            "SELECT state FROM durable_jobs WHERE job_id=?",
            (completed_id,),
        ).fetchone() == ("completed",)
        assert connection.execute(
            "SELECT COUNT(*) FROM job_attempts WHERE job_id=?",
            (cancelled_id,),
        ).fetchone()[0] == 0
        assert connection.execute(
            "SELECT ordinal,outcome FROM job_attempts WHERE job_id=?",
            (completed_id,),
        ).fetchall() == [(1, "completed")]
    finally:
        connection.close()
