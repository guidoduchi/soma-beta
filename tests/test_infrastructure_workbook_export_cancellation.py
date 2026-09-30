from __future__ import annotations

import os

import pytest

from soma.foundation.errors import JobClaimConflict
from soma.foundation.identifiers import new_uuid4, utc_epoch_seconds
from soma.foundation.persistence.uow import ReadSnapshot, UnitOfWork
from soma.infrastructure.jobs import EXPORT_JOB_TYPE
from soma.infrastructure.jobs.infrastructure_workbooks import (
    InfrastructureWorkbookExportWorker,
)
from test_infrastructure_workbook_export_worker import _Clock, _claim_export, _service


pytestmark = pytest.mark.skipif(
    os.name != "nt",
    reason="LLD-08 workbook filesystem authority is Windows-path specific",
)


def test_export_cancellation_after_verification_removes_only_owned_unpublished_temp(
    initialized_database,
    tmp_path,
    monkeypatch,
) -> None:
    factory, service = _service(initialized_database)
    accepted = service.execute(
        "GenerateInfrastructureWorkbook",
        command_id=new_uuid4(),
        payload={
            "mode": "registration_template",
            "scope": {"scope_kind": "all"},
            "destination_directory": str(tmp_path),
        },
    )
    base = utc_epoch_seconds()
    claim = _claim_export(service, now=base)
    worker = InfrastructureWorkbookExportWorker(
        factory,
        clock=_Clock(base + 1),
    )
    real_publish = worker._publish_from_verified

    def cancel_then_publish(*args, **kwargs):
        with UnitOfWork(factory) as uow:
            result = worker._jobs.cancel(
                uow,
                claim.job_id,
                EXPORT_JOB_TYPE,
                1,
                {"command_id": new_uuid4()},
            )
        assert result.outcome == "CANCELLED"
        assert result.claim_revoked is True
        return real_publish(*args, **kwargs)

    monkeypatch.setattr(worker, "_publish_from_verified", cancel_then_publish)

    with pytest.raises(JobClaimConflict):
        worker.run(claim)

    assert not any(path.name.startswith(".soma-") for path in tmp_path.iterdir())
    assert not any(path.suffix.lower() == ".xlsx" for path in tmp_path.iterdir())
    with ReadSnapshot(factory) as snapshot:
        assert snapshot.connection.execute(
            "SELECT state FROM durable_jobs WHERE job_id=?",
            (accepted.response["job_id"],),
        ).fetchone() == ("cancelled",)
        assert snapshot.connection.execute(
            "SELECT outcome FROM job_attempts WHERE job_id=? AND ordinal=1",
            (accepted.response["job_id"],),
        ).fetchone() == ("cancelled",)
        assert snapshot.connection.execute(
            "SELECT count(*) FROM infrastructure_workbook_exports",
        ).fetchone() == (0,)
