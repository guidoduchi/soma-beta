from __future__ import annotations

import os

import pytest

from soma.foundation.identifiers import new_uuid4
from soma.foundation.persistence.uow import ReadSnapshot
from soma.infrastructure.jobs.workbook_stage import InfrastructureWorkbookStageWorker
from soma.reference.application.customer_service import CustomerReferenceService
from test_infrastructure_workbook_stage_worker import (
    _Clock,
    _assembled,
    _stage_claim,
    _write,
)


pytestmark = pytest.mark.skipif(
    os.name != "nt",
    reason="LLD-08 workbook staging authority is Windows-path specific",
)


def test_stage_worker_recovers_checkpointed_rows_without_duplicate_generation(
    initialized_database,
    tmp_path,
    monkeypatch,
) -> None:
    factory, settings, service, data_instance_id = _assembled(
        initialized_database,
        tmp_path,
    )
    customer_id = CustomerReferenceService(factory).create_customer_organization(
        command_id=new_uuid4(),
        name="Recovery customer",
    ).customer_org_id
    site_id = service.execute(
        "CreateSite",
        command_id=new_uuid4(),
        payload={
            "customer_org_id": customer_id,
            "name": "Recovery Site",
            "address_text": "5 Stage Street",
        },
    ).response["target"]["id"]
    source = tmp_path / "recover.xlsx"
    before = _write(
        source,
        data_instance_id=data_instance_id,
        mode="round_trip",
        network_elements=(
            (
                None,
                "NE-RECOVER-01",
                "RECOVER-SERIAL",
                None,
                None,
                site_id,
                "Recovery Site",
                "5 Stage Street",
                None,
                None,
                None,
                None,
                None,
                None,
                None,
                None,
                None,
                None,
                None,
                None,
                None,
                None,
            ),
        ),
    )

    accepted, first_claim, base = _stage_claim(service)
    clock = _Clock(base + 1)
    worker = InfrastructureWorkbookStageWorker(
        factory,
        setting_service=settings,
        clock=clock,
    )
    real_build = worker._build_proposals
    failed_once = False

    def crash_before_proposals(*args, **kwargs):
        nonlocal failed_once
        if not failed_once:
            failed_once = True
            raise RuntimeError("injected staging interruption")
        return real_build(*args, **kwargs)

    monkeypatch.setattr(worker, "_build_proposals", crash_before_proposals)
    with pytest.raises(RuntimeError, match="injected staging interruption"):
        worker.run(first_claim)

    with ReadSnapshot(factory) as snapshot:
        assert snapshot.connection.execute(
            "SELECT state,attempt_count FROM durable_jobs WHERE job_id=?",
            (accepted.response["job_id"],),
        ).fetchone() == ("running", 1)
        run = snapshot.connection.execute(
            "SELECT workbook_run_id,state FROM infrastructure_workbook_runs"
        ).fetchone()
        assert run is not None and run[1] == "validating"
        run_id = str(run[0])
        assert snapshot.connection.execute(
            "SELECT count(*) FROM infrastructure_workbook_staging_rows "
            "WHERE workbook_run_id=?",
            (run_id,),
        ).fetchone() == (1,)
        assert snapshot.connection.execute(
            "SELECT count(*) FROM infrastructure_workbook_proposals "
            "WHERE workbook_run_id=?",
            (run_id,),
        ).fetchone() == (0,)

    clock.value = base + 2
    second_run_id = new_uuid4()
    recovery = worker._jobs.recover_stale_claims(second_run_id, clock.value)
    assert recovery.interrupted_count == 1
    assert recovery.retry_wait_count == 1
    second_claim = worker._jobs.claim_next(second_run_id, clock.value)
    assert second_claim is not None
    assert second_claim.attempt_ordinal == 2

    monkeypatch.setattr(worker, "_build_proposals", real_build)
    clock.value = base + 3
    result = worker.run(second_claim)

    assert source.read_bytes() == before
    assert result.published_run_ids == (run_id,)
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
            "SELECT state FROM infrastructure_workbook_runs WHERE workbook_run_id=?",
            (run_id,),
        ).fetchone() == ("staged",)
        assert snapshot.connection.execute(
            "SELECT count(*) FROM infrastructure_workbook_staging_rows "
            "WHERE workbook_run_id=?",
            (run_id,),
        ).fetchone() == (1,)
        assert snapshot.connection.execute(
            "SELECT count(*) FROM infrastructure_workbook_proposals "
            "WHERE workbook_run_id=?",
            (run_id,),
        ).fetchone() == (1,)


def test_stage_worker_restarts_on_source_generation_change_without_mixing_rows(
    initialized_database,
    tmp_path,
    monkeypatch,
) -> None:
    factory, settings, service, data_instance_id = _assembled(
        initialized_database,
        tmp_path,
    )
    customer_id = CustomerReferenceService(factory).create_customer_organization(
        command_id=new_uuid4(),
        name="Generation customer",
    ).customer_org_id
    site_id = service.execute(
        "CreateSite",
        command_id=new_uuid4(),
        payload={
            "customer_org_id": customer_id,
            "name": "Generation Site",
            "address_text": "6 Stage Street",
        },
    ).response["target"]["id"]
    source = tmp_path / "generation.xlsx"
    _write(
        source,
        data_instance_id=data_instance_id,
        mode="round_trip",
        network_elements=(
            (
                None,
                "NE-GENERATION-OLD",
                "OLD-SERIAL",
                None,
                None,
                site_id,
                "Generation Site",
                "6 Stage Street",
                None,
                None,
                None,
                None,
                None,
                None,
                None,
                None,
                None,
                None,
                None,
                None,
                None,
                None,
            ),
        ),
    )

    accepted, first_claim, base = _stage_claim(service)
    clock = _Clock(base + 1)
    worker = InfrastructureWorkbookStageWorker(
        factory,
        setting_service=settings,
        clock=clock,
    )
    real_build = worker._build_proposals
    failed_once = False

    def crash_before_proposals(*args, **kwargs):
        nonlocal failed_once
        if not failed_once:
            failed_once = True
            raise RuntimeError("injected generation-change interruption")
        return real_build(*args, **kwargs)

    monkeypatch.setattr(worker, "_build_proposals", crash_before_proposals)
    with pytest.raises(RuntimeError, match="generation-change interruption"):
        worker.run(first_claim)

    with ReadSnapshot(factory) as snapshot:
        old_run = snapshot.connection.execute(
            "SELECT workbook_run_id,state FROM infrastructure_workbook_runs"
        ).fetchone()
        assert old_run is not None and old_run[1] == "validating"
        old_run_id = str(old_run[0])
        old_row = snapshot.connection.execute(
            "SELECT normalized_row_json FROM infrastructure_workbook_staging_rows "
            "WHERE workbook_run_id=?",
            (old_run_id,),
        ).fetchone()
        assert old_row is not None and "NE-GENERATION-OLD" in old_row[0]

    _write(
        source,
        data_instance_id=data_instance_id,
        mode="round_trip",
        network_elements=(
            (
                None,
                "NE-GENERATION-NEW-WITH-DIFFERENT-LENGTH",
                "NEW-SERIAL-WITH-DIFFERENT-LENGTH",
                None,
                None,
                site_id,
                "Generation Site",
                "6 Stage Street",
                None,
                None,
                None,
                None,
                None,
                None,
                None,
                None,
                None,
                None,
                None,
                None,
                None,
                None,
            ),
        ),
    )

    clock.value = base + 2
    recovery_run = new_uuid4()
    recovery = worker._jobs.recover_stale_claims(recovery_run, clock.value)
    assert recovery.interrupted_count == 1
    second_claim = worker._jobs.claim_next(recovery_run, clock.value)
    assert second_claim is not None and second_claim.attempt_ordinal == 2

    monkeypatch.setattr(worker, "_build_proposals", real_build)
    clock.value = base + 3
    result = worker.run(second_claim)
    assert len(result.published_run_ids) == 1
    new_run_id = result.published_run_ids[0]
    assert new_run_id != old_run_id

    with ReadSnapshot(factory) as snapshot:
        runs = snapshot.connection.execute(
            "SELECT workbook_run_id,state FROM infrastructure_workbook_runs "
            "ORDER BY workbook_run_id"
        ).fetchall()
        assert set(runs) == {
            (old_run_id, "failed"),
            (new_run_id, "staged"),
        }
        assert snapshot.connection.execute(
            "SELECT count(*) FROM infrastructure_workbook_staging_rows "
            "WHERE workbook_run_id=?",
            (old_run_id,),
        ).fetchone() == (0,)
        new_rows = snapshot.connection.execute(
            "SELECT normalized_row_json FROM infrastructure_workbook_staging_rows "
            "WHERE workbook_run_id=?",
            (new_run_id,),
        ).fetchall()
        assert len(new_rows) == 1
        assert "NE-GENERATION-NEW-WITH-DIFFERENT-LENGTH" in new_rows[0][0]
        assert "NE-GENERATION-OLD" not in new_rows[0][0]
        assert snapshot.connection.execute(
            "SELECT state,attempt_count FROM durable_jobs WHERE job_id=?",
            (accepted.response["job_id"],),
        ).fetchone() == ("completed", 2)
