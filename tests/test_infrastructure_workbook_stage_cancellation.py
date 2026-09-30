from __future__ import annotations

import os

import pytest

from soma.foundation.errors import JobClaimConflict
from soma.foundation.identifiers import new_uuid4
from soma.foundation.persistence.uow import ReadSnapshot, UnitOfWork
from soma.infrastructure.jobs import STAGE_JOB_TYPE
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


def test_stage_worker_cancellation_cleans_only_unpublished_validating_run(
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
        name="Cancellation customer",
    ).customer_org_id
    site_id = service.execute(
        "CreateSite",
        command_id=new_uuid4(),
        payload={
            "customer_org_id": customer_id,
            "name": "Cancellation Site",
            "address_text": "4 Stage Street",
        },
    ).response["target"]["id"]
    source = tmp_path / "cancel-me.xlsx"
    before = _write(
        source,
        data_instance_id=data_instance_id,
        mode="round_trip",
        network_elements=(
            (
                None,
                "NE-CANCEL-01",
                "CANCEL-SERIAL",
                None,
                None,
                site_id,
                "Cancellation Site",
                "4 Stage Street",
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

    accepted, claim, base = _stage_claim(service)
    clock = _Clock(base + 1)
    worker = InfrastructureWorkbookStageWorker(
        factory,
        setting_service=settings,
        clock=clock,
    )
    real_build = worker._build_proposals

    def cancel_after_proposals(*args, **kwargs):
        real_build(*args, **kwargs)
        with UnitOfWork(factory) as uow:
            result = worker._jobs.cancel(
                uow,
                claim.job_id,
                STAGE_JOB_TYPE,
                1,
                {"command_id": new_uuid4()},
            )
        assert result.outcome == "CANCELLED"
        assert result.claim_revoked is True

    monkeypatch.setattr(worker, "_build_proposals", cancel_after_proposals)

    with pytest.raises(JobClaimConflict):
        worker.run(claim)

    assert source.read_bytes() == before
    with ReadSnapshot(factory) as snapshot:
        assert snapshot.connection.execute(
            "SELECT state FROM durable_jobs WHERE job_id=?",
            (accepted.response["job_id"],),
        ).fetchone() == ("cancelled",)
        assert snapshot.connection.execute(
            "SELECT outcome FROM job_attempts WHERE job_id=? AND ordinal=1",
            (accepted.response["job_id"],),
        ).fetchone() == ("cancelled",)
        run = snapshot.connection.execute(
            "SELECT workbook_run_id,state,published_at_utc "
            "FROM infrastructure_workbook_runs"
        ).fetchone()
        assert run is not None
        assert run[1:] == ("failed", None)
        run_id = str(run[0])
        assert snapshot.connection.execute(
            "SELECT count(*) FROM infrastructure_workbook_staging_rows "
            "WHERE workbook_run_id=?",
            (run_id,),
        ).fetchone() == (0,)
        assert snapshot.connection.execute(
            "SELECT count(*) FROM infrastructure_workbook_proposals "
            "WHERE workbook_run_id=?",
            (run_id,),
        ).fetchone() == (0,)
        decision = snapshot.connection.execute(
            "SELECT disposition,warning_codes_json "
            "FROM infrastructure_workbook_row_decisions WHERE workbook_run_id=?",
            (run_id,),
        ).fetchone()
        assert decision == ("failed", '["WORKBOOK_STAGE_CANCELLED"]')
