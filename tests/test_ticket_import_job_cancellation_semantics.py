from __future__ import annotations

import uuid

import pytest

from soma.foundation.errors import ValidationError
from soma.foundation.jobs import DurableJobCoordinator, JobTypeRegistry
from soma.foundation.persistence.uow import UnitOfWork
from soma.ticket_import.jobs import (
    SOURCE_CHECK_JOB_TYPE,
    TICKET_IMPORT_JOB_CONTRACTS,
    derive_source_check_dedupe_key,
)


def _uuid() -> str:
    return str(uuid.uuid4())


class Clock:
    def __init__(self, value: int = 100) -> None:
        self.value = value

    def __call__(self) -> int:
        return self.value


def _payload() -> dict[str, object]:
    return {
        "source_family": "advanced_search_sr",
        "invocation_kind": "automatic",
        "profile_ids": {
            "source_profile_id": "ADVANCED_SEARCH_SR_V1",
            "header_registry_id": "ADVANCED_SEARCH_HEADERS_V1",
            "vocabulary_registry_id": "ADVANCED_SEARCH_VOCABULARIES_V1",
            "parser_profile_id": "ADVANCED_SEARCH_PARSER_V1",
        },
        "source_locator": {
            "kind": "setting_revision",
            "setting_key": "advanced_search_import_directory",
            "setting_revision": 1,
        },
        "requested_by_command_id": _uuid(),
    }


def _coordinator(initialized_database):
    database_path, factory_builder = initialized_database
    factory = factory_builder(database_path)
    clock = Clock()
    coordinator = DurableJobCoordinator(
        factory,
        JobTypeRegistry(TICKET_IMPORT_JOB_CONTRACTS),
        clock=clock,
    )
    return factory, clock, coordinator


def _enqueue(factory, coordinator: DurableJobCoordinator) -> str:
    payload = _payload()
    dedupe_key = derive_source_check_dedupe_key(payload)
    with UnitOfWork(factory) as uow:
        return coordinator.enqueue_or_coalesce(
            uow,
            SOURCE_CHECK_JOB_TYPE,
            1,
            payload,
            dedupe_key,
        )


def test_nonterminal_ticket_import_cancel_transition_is_rejected(initialized_database) -> None:
    factory, _clock, coordinator = _coordinator(initialized_database)
    job_id = _enqueue(factory, coordinator)

    with UnitOfWork(factory) as uow:
        with pytest.raises(ValidationError):
            coordinator.cancel(
                uow,
                job_id,
                SOURCE_CHECK_JOB_TYPE,
                1,
                {"command": "cancel_import"},
            )


def test_completed_ticket_import_cancel_is_foundation_terminal_noop(initialized_database) -> None:
    factory, clock, coordinator = _coordinator(initialized_database)
    job_id = _enqueue(factory, coordinator)
    claim = coordinator.claim_next(_uuid(), 101)
    assert claim is not None and claim.job_id == job_id
    clock.value = 102
    coordinator.complete(claim)

    with UnitOfWork(factory) as uow:
        result = coordinator.cancel(
            uow,
            job_id,
            SOURCE_CHECK_JOB_TYPE,
            1,
            {"command": "cancel_import"},
        )

    assert result.outcome == "TERMINAL_UNCHANGED"
    assert result.prior_state == "completed"
    assert result.resulting_state == "completed"
    assert result.claim_revoked is False


def test_failed_ticket_import_cancel_is_foundation_terminal_noop(initialized_database) -> None:
    factory, clock, coordinator = _coordinator(initialized_database)
    job_id = _enqueue(factory, coordinator)
    claim = coordinator.claim_next(_uuid(), 101)
    assert claim is not None and claim.job_id == job_id
    clock.value = 102
    coordinator.fail(claim, "XLSX_UNSAFE_CONTAINER", None)

    with UnitOfWork(factory) as uow:
        result = coordinator.cancel(
            uow,
            job_id,
            SOURCE_CHECK_JOB_TYPE,
            1,
            {"command": "cancel_import"},
        )

    assert result.outcome == "TERMINAL_UNCHANGED"
    assert result.prior_state == "failed"
    assert result.resulting_state == "failed"
    assert result.claim_revoked is False
