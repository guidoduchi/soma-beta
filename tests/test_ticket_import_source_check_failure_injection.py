from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

import soma.ticket_import.jobs.source_check as source_check_module
from soma.foundation.errors import PersistenceFailure
from soma.foundation.identifiers import new_uuid4
from soma.foundation.jobs import DurableJobCoordinator, JobTypeRegistry
from soma.foundation.persistence.uow import ReadSnapshot, UnitOfWork
from soma.ticket_import.jobs import (
    SOURCE_CHECK_JOB_TYPE,
    TICKET_IMPORT_JOB_CONTRACTS,
    derive_source_check_dedupe_key,
)
from soma.ticket_import.jobs.source_check import TicketImportSourceCheckWorker
from soma.ticket_import.profiles.registry import require_profile_versions
from soma.ticket_import.reconciliation.engine import LogicalRow, row_logical_sha256
from soma.ticket_import.repositories.observations import NormalizedObservationEvidence


class _Clock:
    def __init__(self, value: int = 100) -> None:
        self.value = value

    def __call__(self) -> int:
        return self.value


class _Preflight:
    content_sha256 = "c" * 64

    def close(self) -> None:
        return None


def _factory(initialized_database):
    database_path, factory_builder = initialized_database
    return factory_builder(database_path)


def _profiles() -> dict[str, str]:
    expected = require_profile_versions("advanced_search_sr")
    return {
        "source_profile_id": expected.source_profile_id,
        "header_registry_id": expected.header_registry_id,
        "vocabulary_registry_id": expected.vocabulary_registry_id,
        "parser_profile_id": expected.parser_profile_id,
    }


def _payload(profiles: dict[str, str]) -> dict[str, object]:
    return {
        "source_family": "advanced_search_sr",
        "invocation_kind": "manual",
        "profile_ids": profiles,
        "source_locator": {
            "kind": "manual_path",
            "selected_path": r"C:\Imports\candidate.xlsx",
        },
        "requested_by_command_id": new_uuid4(),
    }


def _candidate(profiles: dict[str, str]):
    return SimpleNamespace(
        source_family="advanced_search_sr",
        profile_id=profiles["source_profile_id"],
        path=Path("C:/Imports/candidate.xlsx"),
        filename="Advanced Search(Service Request)20260927120000.xlsx",
        stable_size_bytes=123,
        stable_mtime_ns=456,
        chronology_kind="embedded_filename_timestamp_utc",
        chronology_value=1_790_510_400,
        discovery_provenance="manual",
        preflight=_Preflight(),
    )


def _parsed(profiles: dict[str, str], count: int):
    rows = []
    for index in range(1, count + 1):
        sr_no = f"{index:08d}"
        logical = LogicalRow(
            identity_state="valid",
            entity_kind="service_request",
            canonical_primary_id=sr_no,
            canonical_parent_rfc_no=None,
        )
        rows.append(
            SimpleNamespace(
                observation=NormalizedObservationEvidence(
                    entity_kind="service_request",
                    identity_state="valid",
                    canonical_primary_id=sr_no,
                    canonical_parent_rfc_no=None,
                    row_ordinal=index,
                    sheet_ordinal=1,
                    row_logical_sha256=row_logical_sha256(logical),
                    source_row_chronology_utc=None,
                    fields=(),
                ),
                findings=(),
            )
        )
    return SimpleNamespace(
        source_family="advanced_search_sr",
        source_profile_id=profiles["source_profile_id"],
        header_registry_id=profiles["header_registry_id"],
        vocabulary_registry_id=profiles["vocabulary_registry_id"],
        parser_profile_id=profiles["parser_profile_id"],
        rows=tuple(rows),
        global_findings=(),
    )


def _coordinator(factory, clock: _Clock) -> DurableJobCoordinator:
    return DurableJobCoordinator(
        factory,
        JobTypeRegistry(TICKET_IMPORT_JOB_CONTRACTS),
        clock=clock,
    )


def _enqueue_and_claim(factory, clock: _Clock, profiles: dict[str, str]):
    coordinator = _coordinator(factory, clock)
    payload = _payload(profiles)
    with UnitOfWork(factory) as uow:
        job_id = coordinator.enqueue_or_coalesce(
            uow,
            SOURCE_CHECK_JOB_TYPE,
            1,
            payload,
            derive_source_check_dedupe_key(payload),
        )
    claim = coordinator.claim_next(new_uuid4(), clock.value)
    assert claim is not None
    assert claim.job_id == job_id
    return coordinator, payload, claim


def _worker(factory, coordinator: DurableJobCoordinator) -> TicketImportSourceCheckWorker:
    worker = TicketImportSourceCheckWorker(factory)
    worker._jobs = coordinator
    worker._publish._jobs = coordinator
    return worker


def _job_checkpoint(factory, job_id: str) -> dict[str, object] | None:
    with ReadSnapshot(factory) as snapshot:
        row = snapshot.connection.execute(
            "SELECT checkpoint_json FROM durable_jobs WHERE job_id=?",
            (job_id,),
        ).fetchone()
    assert row is not None
    return None if row[0] is None else json.loads(str(row[0]))


def _run_state(factory, run_id: str):
    with ReadSnapshot(factory) as snapshot:
        return snapshot.connection.execute(
            "SELECT run_state,revision,logical_fingerprint_sha256,staged_at_utc "
            "FROM import_runs WHERE import_run_id=?",
            (run_id,),
        ).fetchone()


def test_f001_stale_worker_before_discovery_recovers_retryably_without_import_authority(
    initialized_database,
) -> None:
    factory = _factory(initialized_database)
    profiles = _profiles()
    clock = _Clock()
    coordinator, _payload_value, claim = _enqueue_and_claim(factory, clock, profiles)

    recovery_run_id = new_uuid4()
    assert recovery_run_id != claim.run_id
    recovered = coordinator.recover_stale_claims(recovery_run_id, clock.value)
    assert recovered.examined_count == 1
    assert recovered.interrupted_count == 1
    assert recovered.retry_wait_count == 1
    assert recovered.failed_count == 0

    with ReadSnapshot(factory) as snapshot:
        job = snapshot.connection.execute(
            "SELECT state,attempt_count,next_attempt_at_utc,claimed_run_id,"
            "claim_started_at_utc,checkpoint_json,last_error_code "
            "FROM durable_jobs WHERE job_id=?",
            (claim.job_id,),
        ).fetchone()
        assert tuple(job) == (
            "retry_wait",
            1,
            clock.value + 5,
            None,
            None,
            None,
            "JOB_INTERRUPTED",
        )
        assert snapshot.connection.execute("SELECT COUNT(*) FROM import_runs").fetchone()[0] == 0
        assert snapshot.connection.execute("SELECT COUNT(*) FROM source_observations").fetchone()[0] == 0
        assert snapshot.connection.execute(
            "SELECT COUNT(*) FROM reconciliation_proposals"
        ).fetchone()[0] == 0
        assert snapshot.connection.execute(
            "SELECT COUNT(*) FROM import_source_checkpoints"
        ).fetchone()[0] == 0

    clock.value += 5
    retried = coordinator.claim_next(recovery_run_id, clock.value)
    assert retried is not None
    assert retried.job_id == claim.job_id
    assert retried.attempt_ordinal == 2
    assert retried.checkpoint_json is None


def test_f002_failure_after_validating_creation_retains_only_unpublished_run_checkpoint(
    initialized_database,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    factory = _factory(initialized_database)
    profiles = _profiles()
    clock = _Clock()
    coordinator, _payload_value, claim = _enqueue_and_claim(factory, clock, profiles)
    worker = _worker(factory, coordinator)
    candidate = _candidate(profiles)

    monkeypatch.setattr(worker, "_discover", lambda _payload: candidate)

    def fail_before_first_row(_claim, _checkpoint, _candidate):
        raise PersistenceFailure("injected failure before first staged row")

    monkeypatch.setattr(worker, "_stage", fail_before_first_row)
    with pytest.raises(PersistenceFailure, match="before first staged row"):
        worker.run(claim)

    checkpoint = _job_checkpoint(factory, claim.job_id)
    assert checkpoint is not None
    assert checkpoint["phase"] == "validating"
    run_id = str(checkpoint["import_run_id"])
    assert tuple(_run_state(factory, run_id)) == ("validating", 1, None, None)

    with ReadSnapshot(factory) as snapshot:
        assert snapshot.connection.execute(
            "SELECT COUNT(*) FROM source_observations WHERE import_run_id=?",
            (run_id,),
        ).fetchone()[0] == 0
        assert snapshot.connection.execute(
            "SELECT COUNT(*) FROM reconciliation_proposals WHERE import_run_id=?",
            (run_id,),
        ).fetchone()[0] == 0
        assert snapshot.connection.execute(
            "SELECT COUNT(*) FROM import_source_checkpoints"
        ).fetchone()[0] == 0

    coordinator.fail(claim, "PERSISTENCE_BUSY", clock.value + 5)
    clock.value += 5
    retried = coordinator.claim_next(new_uuid4(), clock.value)
    assert retried is not None
    assert json.loads(str(retried.checkpoint_json)) == checkpoint


def test_f003_mid_batch_failure_cannot_advance_cursor_past_rolled_back_rows(
    initialized_database,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    factory = _factory(initialized_database)
    profiles = _profiles()
    parsed = _parsed(profiles, 2_001)
    candidate = _candidate(profiles)
    clock = _Clock()
    coordinator, payload, claim = _enqueue_and_claim(factory, clock, profiles)
    worker = _worker(factory, coordinator)

    _run_id, validating = worker._start_run(
        claim,
        payload,
        profiles,
        candidate,
    )
    real_stage = source_check_module.stage_import_parse_batch
    calls = 0

    def fail_second_batch(*args, **kwargs):
        nonlocal calls
        calls += 1
        result = real_stage(*args, **kwargs)
        if calls == 2:
            raise PersistenceFailure("injected failure after second batch writes")
        return result

    monkeypatch.setattr(source_check_module, "parse_advanced_search", lambda *_args, **_kwargs: parsed)
    monkeypatch.setattr(source_check_module, "stage_import_parse_batch", fail_second_batch)

    with pytest.raises(PersistenceFailure, match="after second batch writes"):
        worker._stage(claim, validating, candidate)

    checkpoint = _job_checkpoint(factory, claim.job_id)
    assert checkpoint is not None
    assert checkpoint["phase"] == "staging"
    assert checkpoint["last_committed_batch"]["next_index"] == 2_000
    run_id = str(checkpoint["import_run_id"])
    assert tuple(_run_state(factory, run_id)) == ("validating", 1, None, None)

    with ReadSnapshot(factory) as snapshot:
        assert snapshot.connection.execute(
            "SELECT COUNT(*) FROM source_observations WHERE import_run_id=?",
            (run_id,),
        ).fetchone()[0] == 2_000
        assert snapshot.connection.execute(
            "SELECT COUNT(*) FROM reconciliation_proposals WHERE import_run_id=?",
            (run_id,),
        ).fetchone()[0] == 0
        assert snapshot.connection.execute(
            "SELECT COUNT(*) FROM import_source_checkpoints"
        ).fetchone()[0] == 0

    coordinator.fail(claim, "PERSISTENCE_BUSY", clock.value + 5)
    clock.value += 5
    retried = coordinator.claim_next(new_uuid4(), clock.value)
    assert retried is not None
    retry_checkpoint = json.loads(str(retried.checkpoint_json))

    monkeypatch.setattr(source_check_module, "stage_import_parse_batch", real_stage)
    resumed = worker._stage(retried, retry_checkpoint, candidate)
    assert resumed["phase"] == "staging"
    assert resumed["last_committed_batch"]["next_index"] == 2_001

    publishing, fingerprint = worker._publishing_checkpoint(retried, resumed)
    assert publishing["phase"] == "publishing"
    assert publishing["last_committed_batch"]["next_index"] == 2_001
    assert publishing["last_committed_batch"]["logical_fingerprint_sha256"] == fingerprint
    assert len(fingerprint) == 64

    with ReadSnapshot(factory) as snapshot:
        assert snapshot.connection.execute(
            "SELECT COUNT(*) FROM source_observations WHERE import_run_id=?",
            (run_id,),
        ).fetchone()[0] == 2_001


def test_f004_failure_after_eof_before_publish_is_restart_safe(
    initialized_database,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    factory = _factory(initialized_database)
    profiles = _profiles()
    parsed = _parsed(profiles, 1)
    candidate = _candidate(profiles)
    clock = _Clock()
    coordinator, _payload_value, claim = _enqueue_and_claim(factory, clock, profiles)
    worker = _worker(factory, coordinator)

    monkeypatch.setattr(worker, "_discover", lambda _payload: candidate)
    monkeypatch.setattr(source_check_module, "parse_advanced_search", lambda *_args, **_kwargs: parsed)

    def fail_before_publish(*_args, **_kwargs):
        raise PersistenceFailure("injected failure after EOF before publication")

    monkeypatch.setattr(worker, "_publish_run", fail_before_publish)
    with pytest.raises(PersistenceFailure, match="after EOF before publication"):
        worker.run(claim)

    checkpoint = _job_checkpoint(factory, claim.job_id)
    assert checkpoint is not None
    assert checkpoint["phase"] == "publishing"
    run_id = str(checkpoint["import_run_id"])
    fingerprint = str(checkpoint["last_committed_batch"]["logical_fingerprint_sha256"])
    assert len(fingerprint) == 64
    assert tuple(_run_state(factory, run_id)) == ("validating", 1, None, None)

    with ReadSnapshot(factory) as snapshot:
        assert snapshot.connection.execute(
            "SELECT COUNT(*) FROM source_observations WHERE import_run_id=?",
            (run_id,),
        ).fetchone()[0] == 1
        assert snapshot.connection.execute(
            "SELECT COUNT(*) FROM reconciliation_proposals WHERE import_run_id=?",
            (run_id,),
        ).fetchone()[0] == 0
        assert snapshot.connection.execute(
            "SELECT COUNT(*) FROM import_source_checkpoints"
        ).fetchone()[0] == 0

    coordinator.fail(claim, "PERSISTENCE_BUSY", clock.value + 5)
    clock.value += 5
    retried = coordinator.claim_next(new_uuid4(), clock.value)
    assert retried is not None
    assert json.loads(str(retried.checkpoint_json)) == checkpoint

    restarted = _worker(factory, coordinator)
    monkeypatch.setattr(restarted, "_discover", lambda _payload: _candidate(profiles))
    restarted.run(retried)

    run = _run_state(factory, run_id)
    assert run is not None
    assert str(run[0]) in {"staged", "waiting_review", "recovery_required", "noop_pending_checkpoint", "noop"}
    assert int(run[1]) >= 2
    assert str(run[2]) == fingerprint
    assert run[3] is not None

    with ReadSnapshot(factory) as snapshot:
        job = snapshot.connection.execute(
            "SELECT state,attempt_count FROM durable_jobs WHERE job_id=?",
            (claim.job_id,),
        ).fetchone()
        assert tuple(job) == ("completed", 2)
