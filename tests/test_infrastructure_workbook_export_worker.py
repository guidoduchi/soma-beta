from __future__ import annotations

import os

import pytest
from openpyxl import load_workbook

from soma.foundation.identifiers import new_uuid4, utc_epoch_seconds
from soma.foundation.persistence.uow import ReadSnapshot
from soma.infrastructure.jobs.infrastructure_workbooks import (
    InfrastructureWorkbookExportWorker,
    preflight_infrastructure_workbook,
    inspect_infrastructure_workbook,
)
from soma.infrastructure.services.core import InfrastructureService
from soma.reference.application.customer_service import CustomerReferenceService


pytestmark = pytest.mark.skipif(
    os.name != "nt",
    reason="LLD-08 workbook filesystem authority is Windows-path specific",
)


class _Clock:
    def __init__(self, value: int) -> None:
        self.value = value

    def __call__(self) -> int:
        return self.value


def _service(initialized_database):
    database_path, factory_builder = initialized_database
    factory = factory_builder(database_path)
    return factory, InfrastructureService(factory)


def _claim_export(service: InfrastructureService, *, now: int):
    claim = service.job_coordinator.claim_next(new_uuid4(), now)
    assert claim is not None
    assert claim.job_type == "INFRA_WORKBOOK_EXPORT_V1"
    return claim


def test_export_worker_publishes_verified_template_and_evidence(
    initialized_database,
    tmp_path,
) -> None:
    factory, service = _service(initialized_database)
    command_id = new_uuid4()
    accepted = service.execute(
        "GenerateInfrastructureWorkbook",
        command_id=command_id,
        payload={
            "mode": "registration_template",
            "scope": {"scope_kind": "all"},
            "destination_directory": str(tmp_path),
        },
    )
    base = utc_epoch_seconds()
    claim = _claim_export(service, now=base)
    clock = _Clock(base + 1)
    result = InfrastructureWorkbookExportWorker(factory, clock=clock).run(claim)

    final_path = tmp_path / result.final_filename
    assert final_path.is_file()
    assert not any(path.name.startswith(".soma-") for path in tmp_path.iterdir())

    captured = preflight_infrastructure_workbook(str(final_path))
    try:
        with ReadSnapshot(factory) as snapshot:
            data_instance_id = snapshot.connection.execute(
                "SELECT data_instance_id FROM instance_metadata"
            ).fetchone()[0]
        summary = inspect_infrastructure_workbook(
            captured,
            current_data_instance_id=str(data_instance_id),
        )
    finally:
        captured.close()
    assert summary.mode == "registration_template"
    assert summary.same_installation
    assert summary.network_element_rows == 0
    assert summary.ip_rows == 0

    with ReadSnapshot(factory) as snapshot:
        job = snapshot.connection.execute(
            "SELECT state,attempt_count,checkpoint_json FROM durable_jobs WHERE job_id=?",
            (accepted.response["job_id"],),
        ).fetchone()
        assert job[0:2] == ("completed", 1)
        assert '"phase":"evidence_recorded"' in job[2]
        evidence = snapshot.connection.execute(
            "SELECT export_id,mode,command_id,artifact_filename,artifact_size_bytes "
            "FROM infrastructure_workbook_exports"
        ).fetchone()
        assert evidence[0] == result.export_id
        assert evidence[1] == "registration_template"
        assert evidence[2] == command_id
        assert evidence[3] == result.final_filename
        assert evidence[4] == final_path.stat().st_size

    replay = service.execute(
        "GenerateInfrastructureWorkbook",
        command_id=command_id,
        payload={
            "mode": "registration_template",
            "scope": {"scope_kind": "all"},
            "destination_directory": str(tmp_path),
        },
    )
    assert replay.replayed
    assert replay.response == accepted.response


def test_export_worker_recovers_link_published_before_database_commit(
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
    first_claim = _claim_export(service, now=base)
    clock = _Clock(base + 1)
    worker = InfrastructureWorkbookExportWorker(factory, clock=clock)
    real_evidence = worker._evidence

    def fail_after_link(*args, **kwargs):
        raise RuntimeError("injected post-publication database failure")

    monkeypatch.setattr(worker, "_evidence", fail_after_link)
    with pytest.raises(RuntimeError, match="post-publication database failure"):
        worker.run(first_claim)

    paths = list(tmp_path.iterdir())
    temp_paths = [path for path in paths if path.name.startswith(".soma-")]
    final_paths = [path for path in paths if path.suffix.lower() == ".xlsx"]
    assert len(temp_paths) == len(final_paths) == 1
    assert os.path.samefile(temp_paths[0], final_paths[0])

    with ReadSnapshot(factory) as snapshot:
        row = snapshot.connection.execute(
            "SELECT state,checkpoint_json FROM durable_jobs WHERE job_id=?",
            (accepted.response["job_id"],),
        ).fetchone()
        assert row[0] == "running"
        assert '"phase":"verified"' in row[1]
        assert snapshot.connection.execute(
            "SELECT count(*) FROM infrastructure_workbook_exports"
        ).fetchone() == (0,)

    clock.value = base + 2
    new_run_id = new_uuid4()
    recovery = worker._jobs.recover_stale_claims(new_run_id, clock.value)
    assert recovery.interrupted_count == 1
    assert recovery.retry_wait_count == 1
    second_claim = worker._jobs.claim_next(new_run_id, clock.value)
    assert second_claim is not None
    assert second_claim.attempt_ordinal == 2
    assert second_claim.checkpoint_json is not None
    assert '"phase":"verified"' in second_claim.checkpoint_json

    monkeypatch.setattr(worker, "_evidence", real_evidence)
    clock.value = base + 3
    result = worker.run(second_claim)

    assert (tmp_path / result.final_filename).is_file()
    assert not any(path.name.startswith(".soma-") for path in tmp_path.iterdir())
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
            "SELECT count(*) FROM infrastructure_workbook_exports"
        ).fetchone() == (1,)



def test_export_worker_discovery_streams_current_infrastructure_rows(
    initialized_database,
    tmp_path,
) -> None:
    factory, service = _service(initialized_database)
    customer_id = CustomerReferenceService(factory).create_customer_organization(
        command_id=new_uuid4(),
        name="Workbook export customer",
    ).customer_org_id
    site_id = service.execute(
        "CreateSite",
        command_id=new_uuid4(),
        payload={
            "customer_org_id": customer_id,
            "name": "Export Site",
            "address_text": "1 Export Street",
        },
    ).response["target"]["id"]
    network_element_id = service.execute(
        "CreateNetworkElement",
        command_id=new_uuid4(),
        payload={
            "new_element": {
                "site_id": site_id,
                "operational_name": "NE-EXPORT-01",
                "manufacturer_serial": "SERIAL-01",
            },
        },
    ).response["target"]["id"]
    ip_response = service.execute(
        "AddNetworkElementIp",
        command_id=new_uuid4(),
        payload={
            "network_element_id": network_element_id,
            "address": "192.0.2.10",
            "make_primary": True,
        },
    ).response
    ip_id = ip_response["target"]["id"]

    accepted = service.execute(
        "GenerateInfrastructureWorkbook",
        command_id=new_uuid4(),
        payload={
            "mode": "discovery",
            "scope": {"scope_kind": "site", "site_id": site_id},
            "destination_directory": str(tmp_path),
        },
    )
    base = utc_epoch_seconds()
    claim = _claim_export(service, now=base)
    result = InfrastructureWorkbookExportWorker(
        factory,
        clock=_Clock(base + 1),
    ).run(claim)

    workbook = load_workbook(
        tmp_path / result.final_filename,
        read_only=True,
        data_only=False,
        keep_links=False,
    )
    try:
        network_rows = list(workbook["Network Elements"].values)
        ip_rows = list(workbook["IP Addresses"].values)
    finally:
        workbook.close()

    assert len(network_rows) == 2
    assert network_rows[1][0] == network_element_id
    assert network_rows[1][1] == "NE-EXPORT-01"
    assert network_rows[1][2] == "SERIAL-01"
    assert network_rows[1][5] == site_id
    assert network_rows[1][6] == "Export Site"
    assert network_rows[1][10] is None
    assert len(ip_rows) == 2
    assert ip_rows[1] == (
        ip_id,
        network_element_id,
        "NE-EXPORT-01",
        "192.0.2.10",
        True,
    )

    with ReadSnapshot(factory) as snapshot:
        assert snapshot.connection.execute(
            "SELECT state FROM durable_jobs WHERE job_id=?",
            (accepted.response["job_id"],),
        ).fetchone() == ("completed",)
        assert snapshot.connection.execute(
            "SELECT mode,filter_scope_json FROM infrastructure_workbook_exports"
        ).fetchone() == (
            "discovery",
            '{"site_id":"' + site_id + '","scope_kind":"site"}',
        )
