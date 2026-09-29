from __future__ import annotations

import os

import pytest

from soma.foundation.identifiers import new_uuid4, utc_epoch_seconds
from soma.foundation.persistence.uow import ReadSnapshot
from soma.infrastructure.jobs.infrastructure_workbooks import write_profile_workbook
from soma.infrastructure.jobs.workbook_stage import InfrastructureWorkbookStageWorker
from soma.infrastructure.services.core import InfrastructureService
from soma.infrastructure.settings import (
    IMPORT_DIRECTORY_KEY,
    build_import_directory_setting_registry,
)
from soma.reference.application.customer_service import CustomerReferenceService
from soma.reference.application.settings_service import SettingService


pytestmark = pytest.mark.skipif(
    os.name != "nt",
    reason="LLD-08 workbook staging authority is Windows-path specific",
)


class _Clock:
    def __init__(self, value: int) -> None:
        self.value = value

    def __call__(self) -> int:
        return self.value


def _assembled(initialized_database, import_directory):
    database_path, factory_builder = initialized_database
    factory = factory_builder(database_path)
    settings = SettingService(
        factory,
        build_import_directory_setting_registry(str(import_directory.parent)),
    )
    saved = settings.write(
        command_id=new_uuid4(),
        setting_key=IMPORT_DIRECTORY_KEY,
        base_revision=None,
        value={"path": str(import_directory)},
    )
    assert saved.revision == 1
    service = InfrastructureService(factory, setting_service=settings)
    with ReadSnapshot(factory) as snapshot:
        data_instance_id = str(
            snapshot.connection.execute(
                "SELECT data_instance_id FROM instance_metadata"
            ).fetchone()[0]
        )
    return factory, settings, service, data_instance_id


def _stage_claim(service: InfrastructureService, *, now: int):
    accepted = service.execute(
        "StageInfrastructureWorkbookCheck",
        command_id=new_uuid4(),
        payload={"setting_revision": 1},
    )
    claim = service.job_coordinator.claim_next(new_uuid4(), now)
    assert claim is not None
    assert claim.job_id == accepted.response["job_id"]
    assert claim.job_type == "INFRA_WORKBOOK_STAGE_V1"
    return accepted, claim


def _write(
    path,
    *,
    data_instance_id: str,
    mode: str,
    network_elements=(),
    ip_addresses=(),
) -> bytes:
    with path.open("wb") as stream:
        write_profile_workbook(
            stream,
            mode=mode,
            scope={"scope_kind": "all"},
            data_instance_id=data_instance_id,
            generated_at_utc=utc_epoch_seconds(),
            network_elements=network_elements,
            ip_addresses=ip_addresses,
        )
    return path.read_bytes()


def test_stage_worker_publishes_header_only_candidate_without_mutating_source(
    initialized_database,
    tmp_path,
) -> None:
    factory, settings, service, data_instance_id = _assembled(
        initialized_database,
        tmp_path,
    )
    source = tmp_path / "template.xlsx"
    before = _write(
        source,
        data_instance_id=data_instance_id,
        mode="registration_template",
    )

    base = utc_epoch_seconds()
    accepted, claim = _stage_claim(service, now=base)
    result = InfrastructureWorkbookStageWorker(
        factory,
        setting_service=settings,
        clock=_Clock(base + 1),
    ).run(claim)

    assert source.read_bytes() == before
    assert len(result.published_run_ids) == 1
    with ReadSnapshot(factory) as snapshot:
        assert snapshot.connection.execute(
            "SELECT state,attempt_count FROM durable_jobs WHERE job_id=?",
            (accepted.response["job_id"],),
        ).fetchone() == ("completed", 1)
        run = snapshot.connection.execute(
            "SELECT state,revision,workbook_mode,installation_relation,"
            "network_element_row_count,ip_row_count FROM infrastructure_workbook_runs"
        ).fetchone()
        assert run == (
            "staged",
            2,
            "registration_template",
            "same_installation",
            0,
            0,
        )
        assert snapshot.connection.execute(
            "SELECT count(*) FROM infrastructure_workbook_staging_rows"
        ).fetchone() == (0,)
        assert snapshot.connection.execute(
            "SELECT count(*) FROM infrastructure_workbook_proposals"
        ).fetchone() == (0,)


def test_stage_worker_exact_round_trip_rows_are_unchanged(
    initialized_database,
    tmp_path,
) -> None:
    factory, settings, service, data_instance_id = _assembled(
        initialized_database,
        tmp_path,
    )
    customer_id = CustomerReferenceService(factory).create_customer_organization(
        command_id=new_uuid4(),
        name="Stage customer",
    ).customer_org_id
    site_id = service.execute(
        "CreateSite",
        command_id=new_uuid4(),
        payload={
            "customer_org_id": customer_id,
            "name": "Stage Site",
            "address_text": "1 Stage Street",
        },
    ).response["target"]["id"]
    ne_id = service.execute(
        "CreateNetworkElement",
        command_id=new_uuid4(),
        payload={
            "new_element": {
                "site_id": site_id,
                "operational_name": "NE-STAGE-01",
                "manufacturer_serial": "SERIAL-STAGE",
            }
        },
    ).response["target"]["id"]
    ip_id = service.execute(
        "AddNetworkElementIp",
        command_id=new_uuid4(),
        payload={
            "network_element_id": ne_id,
            "address": "198.51.100.10",
            "make_primary": True,
        },
    ).response["target"]["id"]

    network_row = (
        ne_id,
        "NE-STAGE-01",
        "SERIAL-STAGE",
        None,
        None,
        site_id,
        "Stage Site",
        "1 Stage Street",
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
    )
    ip_row = (ip_id, ne_id, "NE-STAGE-01", "198.51.100.10", True)
    source = tmp_path / "round-trip.xlsx"
    before = _write(
        source,
        data_instance_id=data_instance_id,
        mode="round_trip",
        network_elements=(network_row,),
        ip_addresses=(ip_row,),
    )

    base = utc_epoch_seconds()
    _accepted, claim = _stage_claim(service, now=base)
    result = InfrastructureWorkbookStageWorker(
        factory,
        setting_service=settings,
        clock=_Clock(base + 1),
    ).run(claim)

    assert source.read_bytes() == before
    assert len(result.published_run_ids) == 1
    with ReadSnapshot(factory) as snapshot:
        assert snapshot.connection.execute(
            "SELECT state,network_element_row_count,ip_row_count,warning_count "
            "FROM infrastructure_workbook_runs"
        ).fetchone() == ("staged", 1, 1, 0)
        proposals = snapshot.connection.execute(
            "SELECT s.sheet_kind,p.action,p.target_network_element_id,"
            "p.expected_target_revision,p.state "
            "FROM infrastructure_workbook_proposals p "
            "JOIN infrastructure_workbook_staging_rows s USING(staging_row_id) "
            "ORDER BY s.sheet_kind"
        ).fetchall()
        assert proposals == [
            ("ip_addresses", "unchanged", ne_id, 1, "pending"),
            ("network_elements", "unchanged", ne_id, 1, "pending"),
        ]


def test_foreign_installation_ids_never_direct_target_current_network_element(
    initialized_database,
    tmp_path,
) -> None:
    factory, settings, service, _data_instance_id = _assembled(
        initialized_database,
        tmp_path,
    )
    customer_id = CustomerReferenceService(factory).create_customer_organization(
        command_id=new_uuid4(),
        name="Foreign candidate customer",
    ).customer_org_id
    site_id = service.execute(
        "CreateSite",
        command_id=new_uuid4(),
        payload={
            "customer_org_id": customer_id,
            "name": "Foreign Candidate Site",
            "address_text": "2 Stage Street",
        },
    ).response["target"]["id"]
    ne_id = service.execute(
        "CreateNetworkElement",
        command_id=new_uuid4(),
        payload={
            "new_element": {
                "site_id": site_id,
                "operational_name": "NE-FOREIGN-01",
                "manufacturer_serial": "FOREIGN-SERIAL",
            }
        },
    ).response["target"]["id"]

    source = tmp_path / "foreign.xlsx"
    _write(
        source,
        data_instance_id=new_uuid4(),
        mode="round_trip",
        network_elements=(
            (
                ne_id,
                "NE-FOREIGN-01",
                "FOREIGN-SERIAL",
                None,
                None,
                site_id,
                "Foreign Candidate Site",
                "2 Stage Street",
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

    base = utc_epoch_seconds()
    _accepted, claim = _stage_claim(service, now=base)
    InfrastructureWorkbookStageWorker(
        factory,
        setting_service=settings,
        clock=_Clock(base + 1),
    ).run(claim)

    with ReadSnapshot(factory) as snapshot:
        row = snapshot.connection.execute(
            "SELECT p.action,p.target_network_element_id,p.candidate_ids_json,"
            "r.installation_relation "
            "FROM infrastructure_workbook_proposals p "
            "JOIN infrastructure_workbook_runs r USING(workbook_run_id)"
        ).fetchone()
        assert row[0] == "ambiguous"
        assert row[1] is None
        assert ne_id in row[2]
        assert row[3] == "foreign_installation"
