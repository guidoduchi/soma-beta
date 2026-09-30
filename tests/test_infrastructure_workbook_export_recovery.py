from __future__ import annotations

import os

import pytest

from soma.foundation.identifiers import new_uuid4, utc_epoch_seconds
from soma.foundation.persistence.uow import ReadSnapshot
from soma.infrastructure.jobs.infrastructure_workbooks import (
    InfrastructureWorkbookExportWorker,
    inspect_infrastructure_workbook,
    preflight_infrastructure_workbook,
)
from test_infrastructure_workbook_export_worker import _Clock, _claim_export, _service


pytestmark = pytest.mark.skipif(
    os.name != "nt",
    reason="LLD-08 workbook filesystem authority is Windows-path specific",
)


def _enqueue_template(service, directory):
    return service.execute(
        "GenerateInfrastructureWorkbook",
        command_id=new_uuid4(),
        payload={
            "mode": "registration_template",
            "scope": {"scope_kind": "all"},
            "destination_directory": str(directory),
        },
    )


def _assert_final_template(factory, path):
    captured = preflight_infrastructure_workbook(str(path))
    try:
        with ReadSnapshot(factory) as snapshot:
            data_instance_id = str(
                snapshot.connection.execute(
                    "SELECT data_instance_id FROM instance_metadata"
                ).fetchone()[0]
            )
        summary = inspect_infrastructure_workbook(
            captured,
            current_data_instance_id=data_instance_id,
        )
    finally:
        captured.close()
    assert summary.mode == "registration_template"
    assert summary.same_installation


def test_export_recovery_restarts_uncheckpointed_temp_from_fresh_generation(
    initialized_database,
    tmp_path,
    monkeypatch,
) -> None:
    factory, service = _service(initialized_database)
    accepted = _enqueue_template(service, tmp_path)
    base = utc_epoch_seconds()
    first_claim = _claim_export(service, now=base)
    clock = _Clock(base + 1)
    worker = InfrastructureWorkbookExportWorker(factory, clock=clock)
    real_checkpoint = worker._jobs.checkpoint

    def fail_before_verifying_checkpoint(claim, checkpoint):
        if checkpoint["phase"] == "verifying":
            raise RuntimeError("injected pre-verification checkpoint failure")
        return real_checkpoint(claim, checkpoint)

    monkeypatch.setattr(worker._jobs, "checkpoint", fail_before_verifying_checkpoint)
    with pytest.raises(RuntimeError, match="pre-verification checkpoint failure"):
        worker.run(first_claim)

    temps = [path for path in tmp_path.iterdir() if path.name.startswith(".soma-")]
    assert len(temps) == 1
    temp = temps[0]
    with ReadSnapshot(factory) as snapshot:
        row = snapshot.connection.execute(
            "SELECT state,checkpoint_json FROM durable_jobs WHERE job_id=?",
            (accepted.response["job_id"],),
        ).fetchone()
        assert row[0] == "running"
        assert '"phase":"writing"' in row[1]

    temp.write_bytes(b"tampered stale temp")
    monkeypatch.setattr(worker._jobs, "checkpoint", real_checkpoint)
    clock.value = base + 2
    recovery_run = new_uuid4()
    recovery = worker._jobs.recover_stale_claims(recovery_run, clock.value)
    assert recovery.interrupted_count == 1
    second_claim = worker._jobs.claim_next(recovery_run, clock.value)
    assert second_claim is not None and second_claim.attempt_ordinal == 2

    clock.value = base + 3
    result = worker.run(second_claim)
    final = tmp_path / result.final_filename
    assert final.is_file()
    assert not any(path.name.startswith(".soma-") for path in tmp_path.iterdir())
    _assert_final_template(factory, final)

    with ReadSnapshot(factory) as snapshot:
        assert snapshot.connection.execute(
            "SELECT state,attempt_count FROM durable_jobs WHERE job_id=?",
            (accepted.response["job_id"],),
        ).fetchone() == ("completed", 2)
        assert snapshot.connection.execute(
            "SELECT count(*) FROM infrastructure_workbook_exports",
        ).fetchone() == (1,)


def test_export_recovery_discards_tampered_verified_temp_and_regenerates(
    initialized_database,
    tmp_path,
    monkeypatch,
) -> None:
    factory, service = _service(initialized_database)
    accepted = _enqueue_template(service, tmp_path)
    base = utc_epoch_seconds()
    first_claim = _claim_export(service, now=base)
    clock = _Clock(base + 1)
    worker = InfrastructureWorkbookExportWorker(factory, clock=clock)
    real_publish = worker._publish_from_verified

    def crash_before_publication(*args, **kwargs):
        raise RuntimeError("injected verified-temp interruption")

    monkeypatch.setattr(worker, "_publish_from_verified", crash_before_publication)
    with pytest.raises(RuntimeError, match="verified-temp interruption"):
        worker.run(first_claim)

    temps = [path for path in tmp_path.iterdir() if path.name.startswith(".soma-")]
    assert len(temps) == 1
    temp = temps[0]
    assert not any(path.suffix.lower() == ".xlsx" for path in tmp_path.iterdir())
    with ReadSnapshot(factory) as snapshot:
        row = snapshot.connection.execute(
            "SELECT state,checkpoint_json FROM durable_jobs WHERE job_id=?",
            (accepted.response["job_id"],),
        ).fetchone()
        assert row[0] == "running"
        assert '"phase":"verified"' in row[1]

    temp.write_bytes(b"tampered verified temp")
    clock.value = base + 2
    recovery_run = new_uuid4()
    recovery = worker._jobs.recover_stale_claims(recovery_run, clock.value)
    assert recovery.interrupted_count == 1
    second_claim = worker._jobs.claim_next(recovery_run, clock.value)
    assert second_claim is not None and second_claim.attempt_ordinal == 2
    assert second_claim.checkpoint_json is not None
    assert '"phase":"verified"' in second_claim.checkpoint_json

    monkeypatch.setattr(worker, "_publish_from_verified", real_publish)
    clock.value = base + 3
    result = worker.run(second_claim)
    final = tmp_path / result.final_filename
    assert final.is_file()
    assert not any(path.name.startswith(".soma-") for path in tmp_path.iterdir())
    _assert_final_template(factory, final)

    with ReadSnapshot(factory) as snapshot:
        assert snapshot.connection.execute(
            "SELECT state,attempt_count FROM durable_jobs WHERE job_id=?",
            (accepted.response["job_id"],),
        ).fetchone() == ("completed", 2)
        assert snapshot.connection.execute(
            "SELECT ordinal,outcome,error_code FROM job_attempts "
            "WHERE job_id=? ORDER BY ordinal",
            (accepted.response["job_id"],),
        ).fetchall() == [
            (1, "interrupted", "JOB_INTERRUPTED"),
            (2, "completed", None),
        ]
        assert snapshot.connection.execute(
            "SELECT count(*) FROM infrastructure_workbook_exports",
        ).fetchone() == (1,)
