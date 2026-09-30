from __future__ import annotations

import sqlite3

import pytest

from soma.foundation.errors import SomaError
from soma.foundation.identifiers import new_uuid4
from soma.foundation.persistence.uow import UnitOfWork
from soma.foundation.persistence.uow import ReadSnapshot
from soma.infrastructure.services.core import InfrastructureService
from soma.infrastructure.services.sites import dependency_snapshot
from soma.infrastructure.repositories.workbooks import cleanup_terminal_staging
from soma.reference.application.customer_service import CustomerReferenceService


@pytest.fixture
def infra(initialized_database):
    path, factory_builder = initialized_database
    factory = factory_builder(path)
    service = InfrastructureService(factory)
    customer = CustomerReferenceService(factory).create_customer_organization(
        command_id=new_uuid4(), name="Infrastructure test customer").customer_org_id
    return service, factory, customer


def command(service, command_name, **payload):
    return service.execute(command_name, command_id=new_uuid4(), payload=payload).response


def site(service, customer):
    return command(service, "CreateSite", customer_org_id=customer,
                   name="Datacenter", address_text="1 Main Street")["target"]["id"]


def test_site_creation_replay_and_descriptive_history(infra):
    service, factory, customer = infra
    identity = new_uuid4()
    payload = dict(customer_org_id=customer, name="Datacenter", address_text="1 Main Street")
    first = service.execute("CreateSite", command_id=identity, payload=payload)
    second = service.execute("CreateSite", command_id=identity, payload=payload)
    assert second.replayed and first.response == second.response
    target = first.response["target"]["id"]
    changed = command(service, "UpdateSiteDescriptive", site_id=target, base_revision=1,
                      name="Renamed", address_text="2 Main Street", reason_code="correction")
    assert changed["revision"] == 2
    unchanged = command(service, "UpdateSiteDescriptive", site_id=target, base_revision=2,
                        name="Renamed", address_text="2 Main Street", reason_code="correction")
    assert unchanged["no_change"] and unchanged["revision"] == 2
    with ReadSnapshot(factory) as snapshot:
        assert snapshot.connection.execute("SELECT count(*) FROM sites").fetchone()[0] == 1
        assert snapshot.connection.execute("SELECT count(*) FROM site_lifecycle_events").fetchone()[0] == 2
        assert snapshot.connection.execute(
            "SELECT d.name,d.address_mode,d.standalone_address_text FROM dispatch_locations d "
            "JOIN site_dispatch_locations l USING(dispatch_location_id) WHERE l.site_id=?", (target,)
        ).fetchone() == ("Datacenter", "site_derived", None)


def test_site_participant_failure_rolls_back_receipt_and_domain(infra, monkeypatch):
    from soma.reference.application.dispatch_service import DispatchLocationService
    service, factory, customer = infra
    def broken(*args, **kwargs):
        raise RuntimeError("injected participant failure")
    monkeypatch.setattr(DispatchLocationService, "create_dedicated_for_site", broken)
    identity = new_uuid4()
    with pytest.raises(RuntimeError):
        service.execute("CreateSite", command_id=identity, payload=dict(
            customer_org_id=customer, name="No partial Site", address_text="1 Main Street"))
    with ReadSnapshot(factory) as snapshot:
        for table in ("sites", "site_dispatch_locations", "dispatch_locations", "site_lifecycle_events"):
            assert snapshot.connection.execute(f"SELECT count(*) FROM {table}").fetchone()[0] == 0
        assert snapshot.connection.execute("SELECT count(*) FROM command_receipts WHERE command_id=?", (identity,)).fetchone()[0] == 0


def test_site_archive_missing_dependency_fails_closed(infra):
    service, _, customer = infra
    target = site(service, customer)
    with pytest.raises(SomaError) as error:
        command(service, "ChangeSiteLifecycle", site_id=target, base_revision=1, target_state="archived")
    assert error.value.code == "DEPENDENCY_INDETERMINATE"


def test_site_customer_correction_reuses_guard_snapshot(infra):
    service, factory, customer = infra
    target = site(service, customer)
    other_customer = CustomerReferenceService(factory).create_customer_organization(
        command_id=new_uuid4(), name="Other customer").customer_org_id

    class Guard:
        calls = 0

        def guard_archive(self, reader, site_id):
            self.calls += 1
            return "CLEAR"

    guards = [Guard(), Guard(), Guard()]
    service.site_dependencies = tuple(guards)
    with ReadSnapshot(factory) as snapshot:
        current = snapshot.connection.execute("SELECT * FROM sites WHERE site_id=?", (target,))
        row = dict(zip((column[0] for column in current.description), current.fetchone()))
        preview, _, _ = dependency_snapshot(service, snapshot, target, row)
    for guard in guards:
        guard.calls = 0
    response = command(service, "CorrectSiteCustomerOwnership", site_id=target,
                       base_revision=1, new_customer_org_id=other_customer,
                       reason_code="correction", dependency_preview_fingerprint=preview)
    assert response["revision"] == 2
    assert [guard.calls for guard in guards] == [1, 1, 1]
    with ReadSnapshot(factory) as snapshot:
        current = snapshot.connection.execute("SELECT * FROM sites WHERE site_id=?", (target,))
        row = dict(zip((column[0] for column in current.description), current.fetchone()))
        archive_preview, _, _ = dependency_snapshot(service, snapshot, target, row)
    for guard in guards:
        guard.calls = 0
    archived = command(service, "ChangeSiteLifecycle", site_id=target, base_revision=2,
                       target_state="archived", blocker_preview_fingerprint=archive_preview)
    assert archived["revision"] == 3
    assert [guard.calls for guard in guards] == [1, 1, 1]


def test_room_rack_lifecycle_and_stale_revision(infra):
    service, _, customer = infra
    target = site(service, customer)
    room = command(service, "CreateRoom", site_id=target, name="Room")["target"]["id"]
    rack = command(service, "CreateRack", room_id=room, name="Rack", height_u=42)["target"]["id"]
    with pytest.raises(SomaError):
        command(service, "ChangeRoomLifecycle", room_id=room, base_revision=1, target_state="archived")
    command(service, "ChangeRackLifecycle", rack_id=rack, base_revision=1, target_state="archived")
    command(service, "ChangeRoomLifecycle", room_id=room, base_revision=1, target_state="archived")
    with pytest.raises(SomaError):
        command(service, "ChangeRackLifecycle", rack_id=rack, base_revision=2, target_state="active")
    with pytest.raises(SomaError) as error:
        command(service, "UpdateRack", rack_id=rack, base_revision=1, name="stale",
                height_u=42, reason_code="correction")
    assert error.value.code == "INFRA_STALE"


def test_forward_infrastructure_migrations_preserve_prefix(tmp_path, migration_directory, security_provider):
    from test_foundation_durable_job_migration import _runner, _stage_prefix
    prefix = tmp_path / "prefix"
    _stage_prefix(migration_directory, prefix, 13)
    database = tmp_path / "upgrade.db"
    assert _runner(database, prefix, security_provider).initialize_or_migrate() == 13
    with sqlite3.connect(database) as connection:
        before = connection.execute("SELECT * FROM schema_migrations ORDER BY sequence").fetchall()
        instance = connection.execute("SELECT * FROM instance_metadata").fetchall()
    assert _runner(database, migration_directory, security_provider).initialize_or_migrate() == 15
    with sqlite3.connect(database) as connection:
        assert connection.execute("SELECT * FROM schema_migrations WHERE sequence<=13 ORDER BY sequence").fetchall() == before
        assert connection.execute("SELECT * FROM instance_metadata").fetchall() == instance
        assert connection.execute("PRAGMA foreign_key_check").fetchall() == []
        assert "candidate_ids_json" in {
            row[1] for row in connection.execute("PRAGMA table_info(infrastructure_workbook_proposals)")
        }


def test_reject_workbook_run_records_terminal_row_decisions_and_replays(infra):
    service, factory, _ = infra
    run_id = new_uuid4()
    staging_id = new_uuid4()
    proposal_id = new_uuid4()
    other_proposal_id = new_uuid4()
    digest = "a" * 64
    with UnitOfWork(factory) as uow:
        uow.connection.execute(
            "INSERT INTO infrastructure_workbook_runs "
            "(workbook_run_id,source_filename,file_sha256,logical_fingerprint,"
            "workbook_version,workbook_mode,source_installation_scope_id,"
            "installation_relation,state,captured_at_utc,revision,network_element_row_count) "
            "VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
            (run_id, "input.xlsx", digest, digest, "1", "discovery", "instance",
             "same_installation", "reviewed", 1, 1, 1),
        )
        uow.connection.execute(
            "INSERT INTO infrastructure_workbook_staging_rows "
            "(staging_row_id,workbook_run_id,sheet_kind,row_ordinal,row_fingerprint,"
            "normalized_row_json,validation_state,warning_codes_json) "
            "VALUES (?,?,?,?,?,?,?,?)",
            (staging_id, run_id, "network_elements", 2, digest, "{}", "valid", "[]"),
        )
        uow.connection.execute(
            "INSERT INTO infrastructure_workbook_proposals "
            "(proposal_id,workbook_run_id,staging_row_id,action,state,input_fingerprint,"
            "impact_json,created_at_utc,revision) VALUES (?,?,?,?,?,?,?,?,?)",
            (proposal_id, run_id, staging_id, "unchanged", "pending", digest, "{}", 1, 1),
        )
        uow.connection.execute(
            "INSERT INTO infrastructure_workbook_proposals "
            "(proposal_id,workbook_run_id,staging_row_id,action,state,input_fingerprint,"
            "impact_json,created_at_utc,revision) VALUES (?,?,?,?,?,?,?,?,?)",
            (other_proposal_id, run_id, staging_id, "skip_invalid", "pending", digest, "{}", 1, 1),
        )

    with UnitOfWork(factory) as uow:
        with pytest.raises(SomaError) as error:
            cleanup_terminal_staging(uow, run_id)
        assert error.value.code == "WORKBOOK_STALE"

    command_id = new_uuid4()
    payload = {"run_id": run_id, "run_revision": 1, "reason_code": "operator_rejected"}
    actor_id = new_uuid4()
    first = service.execute("RejectInfrastructureWorkbookRun", command_id=command_id,
                            payload=payload, actor_id=actor_id)
    replay = service.execute("RejectInfrastructureWorkbookRun", command_id=command_id, payload=payload)
    assert first.response == {"command_id": command_id, "run_id": run_id, "state": "rejected", "revision": 2}
    assert replay.replayed and replay.response == first.response
    with ReadSnapshot(factory) as snapshot:
        assert snapshot.connection.execute(
            "SELECT state,revision FROM infrastructure_workbook_runs WHERE workbook_run_id=?", (run_id,)
        ).fetchone() == ("rejected", 2)
        assert snapshot.connection.execute(
            "SELECT state FROM infrastructure_workbook_proposals WHERE proposal_id=?", (proposal_id,)
        ).fetchone() == ("rejected",)
        assert snapshot.connection.execute(
            "SELECT disposition FROM infrastructure_workbook_row_decisions WHERE workbook_run_id=?", (run_id,)
        ).fetchone() == ("rejected",)
        assert snapshot.connection.execute(
            "SELECT count(*) FROM infrastructure_workbook_row_decisions WHERE workbook_run_id=?", (run_id,)
        ).fetchone() == (1,)
        assert snapshot.connection.execute(
            "SELECT count(*) FROM infrastructure_workbook_proposals "
            "WHERE workbook_run_id=? AND state='rejected'", (run_id,)
        ).fetchone() == (2,)
        assert snapshot.connection.execute(
            "SELECT actor_id FROM audit_events WHERE command_id=?", (command_id,)
        ).fetchone() == (actor_id,)
    with UnitOfWork(factory) as uow:
        assert cleanup_terminal_staging(uow, run_id, limit=1) == 1
    with ReadSnapshot(factory) as snapshot:
        assert snapshot.connection.execute(
            "SELECT count(*) FROM infrastructure_workbook_staging_rows WHERE workbook_run_id=?", (run_id,)
        ).fetchone() == (0,)
        assert snapshot.connection.execute(
            "SELECT count(*) FROM infrastructure_workbook_proposals WHERE workbook_run_id=?", (run_id,)
        ).fetchone() == (0,)
        assert snapshot.connection.execute(
            "SELECT count(*) FROM infrastructure_workbook_row_decisions WHERE workbook_run_id=?", (run_id,)
        ).fetchone() == (1,)
    after_cleanup = service.execute("RejectInfrastructureWorkbookRun", command_id=command_id, payload=payload)
    assert after_cleanup.replayed and after_cleanup.response == first.response


def test_reject_workbook_run_stale_terminal_evidence_fails_closed(infra):
    service, factory, _ = infra
    run_id = new_uuid4()
    staging_id = new_uuid4()
    digest = "b" * 64
    with UnitOfWork(factory) as uow:
        uow.connection.execute(
            "INSERT INTO infrastructure_workbook_runs "
            "(workbook_run_id,source_filename,file_sha256,logical_fingerprint,"
            "workbook_version,workbook_mode,source_installation_scope_id,"
            "installation_relation,state,captured_at_utc,network_element_row_count) "
            "VALUES (?,?,?,?,?,?,?,?,?,?,?)",
            (run_id, "input.xlsx", digest, digest, "1", "discovery", "instance",
             "same_installation", "staged", 1, 1),
        )
        uow.connection.execute(
            "INSERT INTO infrastructure_workbook_staging_rows "
            "(staging_row_id,workbook_run_id,sheet_kind,row_ordinal,row_fingerprint,"
            "normalized_row_json,validation_state,warning_codes_json) "
            "VALUES (?,?,?,?,?,?,?,?)",
            (staging_id, run_id, "network_elements", 2, digest, "{}", "valid", "[]"),
        )
        uow.connection.execute(
            "INSERT INTO infrastructure_workbook_row_decisions "
            "(row_decision_id,workbook_run_id,sheet_kind,row_ordinal,row_fingerprint,"
            "disposition,warning_codes_json,result_refs_json,recorded_at_utc) "
            "VALUES (?,?,?,?,?,?,?,?,?)",
            (new_uuid4(), run_id, "network_elements", 2, digest, "failed", "[]", "[]", 1),
        )
    payload = {"run_id": run_id, "run_revision": 1, "reason_code": "operator_rejected"}
    command_id = new_uuid4()
    with pytest.raises(SomaError) as error:
        service.execute("RejectInfrastructureWorkbookRun", command_id=command_id, payload=payload)
    assert error.value.code == "WORKBOOK_STALE"
    with ReadSnapshot(factory) as snapshot:
        assert snapshot.connection.execute(
            "SELECT state,revision,last_command_id FROM infrastructure_workbook_runs WHERE workbook_run_id=?",
            (run_id,),
        ).fetchone() == ("staged", 1, None)
        assert snapshot.connection.execute(
            "SELECT count(*) FROM command_receipts WHERE command_id=?", (command_id,)
        ).fetchone() == (0,)
    with pytest.raises(SomaError) as error:
        service.execute("RejectInfrastructureWorkbookRun", command_id=new_uuid4(),
                        payload={**payload, "run_revision": 2})
    assert error.value.code == "INFRA_STALE"


def test_reject_workbook_audit_failure_rolls_back_run_and_receipt(infra, monkeypatch):
    service, factory, _ = infra
    run_id = new_uuid4()
    digest = "d" * 64
    with UnitOfWork(factory) as uow:
        uow.connection.execute(
            "INSERT INTO infrastructure_workbook_runs "
            "(workbook_run_id,source_filename,file_sha256,logical_fingerprint,"
            "workbook_version,workbook_mode,source_installation_scope_id,"
            "installation_relation,state,captured_at_utc) VALUES (?,?,?,?,?,?,?,?,?,?)",
            (run_id, "input.xlsx", digest, digest, "1", "discovery", "instance",
             "same_installation", "staged", 1),
        )
    def fail_audit(*args, **kwargs):
        raise RuntimeError("injected audit failure")
    monkeypatch.setattr(service.boundary._audit_writer, "write", fail_audit)
    command_id = new_uuid4()
    with pytest.raises(RuntimeError, match="injected audit failure"):
        service.execute("RejectInfrastructureWorkbookRun", command_id=command_id,
                        payload={"run_id": run_id, "run_revision": 1,
                                 "reason_code": "operator_rejected"})
    with ReadSnapshot(factory) as snapshot:
        assert snapshot.connection.execute(
            "SELECT state,revision,last_command_id FROM infrastructure_workbook_runs WHERE workbook_run_id=?",
            (run_id,),
        ).fetchone() == ("staged", 1, None)
        assert snapshot.connection.execute(
            "SELECT count(*) FROM command_receipts WHERE command_id=?", (command_id,)
        ).fetchone() == (0,)


def test_reject_workbook_incomplete_staging_fails_before_receipt(infra):
    service, factory, _ = infra
    run_id = new_uuid4()
    digest = "e" * 64
    with UnitOfWork(factory) as uow:
        uow.connection.execute(
            "INSERT INTO infrastructure_workbook_runs "
            "(workbook_run_id,source_filename,file_sha256,logical_fingerprint,"
            "workbook_version,workbook_mode,source_installation_scope_id,"
            "installation_relation,state,captured_at_utc,network_element_row_count) "
            "VALUES (?,?,?,?,?,?,?,?,?,?,?)",
            (run_id, "input.xlsx", digest, digest, "1", "discovery", "instance",
             "same_installation", "staged", 1, 1),
        )
    command_id = new_uuid4()
    with pytest.raises(SomaError) as error:
        service.execute("RejectInfrastructureWorkbookRun", command_id=command_id,
                        payload={"run_id": run_id, "run_revision": 1,
                                 "reason_code": "operator_rejected"})
    assert error.value.code == "WORKBOOK_STALE"
    with ReadSnapshot(factory) as snapshot:
        assert snapshot.connection.execute(
            "SELECT count(*) FROM command_receipts WHERE command_id=?", (command_id,)
        ).fetchone() == (0,)


def test_terminal_staging_cleanup_requires_durable_row_decision(infra):
    _, factory, _ = infra
    run_id = new_uuid4()
    digest = "f" * 64
    with UnitOfWork(factory) as uow:
        uow.connection.execute(
            "INSERT INTO infrastructure_workbook_runs "
            "(workbook_run_id,source_filename,file_sha256,logical_fingerprint,"
            "workbook_version,workbook_mode,source_installation_scope_id,"
            "installation_relation,state,captured_at_utc,network_element_row_count) "
            "VALUES (?,?,?,?,?,?,?,?,?,?,?)",
            (run_id, "input.xlsx", digest, digest, "1", "discovery", "instance",
             "same_installation", "failed", 1, 1),
        )
        uow.connection.execute(
            "INSERT INTO infrastructure_workbook_staging_rows "
            "(staging_row_id,workbook_run_id,sheet_kind,row_ordinal,row_fingerprint,"
            "normalized_row_json,validation_state,warning_codes_json) VALUES (?,?,?,?,?,?,?,?)",
            (new_uuid4(), run_id, "network_elements", 2, digest, "{}", "invalid", "[]"),
        )
    with pytest.raises(sqlite3.IntegrityError):
        with UnitOfWork(factory) as uow:
            cleanup_terminal_staging(uow, run_id)
    with ReadSnapshot(factory) as snapshot:
        assert snapshot.connection.execute(
            "SELECT count(*) FROM infrastructure_workbook_staging_rows WHERE workbook_run_id=?", (run_id,)
        ).fetchone() == (1,)



def test_generate_workbook_enqueues_atomically_and_replays(infra):
    service, factory, _ = infra
    command_id = new_uuid4()
    payload = {
        "mode": "registration_template",
        "scope": {"scope_kind": "all"},
        "destination_directory": r"D:\Exports",
    }

    first = service.execute(
        "GenerateInfrastructureWorkbook",
        command_id=command_id,
        payload=payload,
    )
    replay = service.execute(
        "GenerateInfrastructureWorkbook",
        command_id=command_id,
        payload=payload,
    )

    assert first.response_schema == "INFRA_JOB_ACCEPTED_V1"
    assert first.response["command_id"] == command_id
    assert first.response["job_type"] == "INFRA_WORKBOOK_EXPORT_V1"
    assert first.response["state"] == "queued"
    assert replay.replayed and replay.response == first.response
    with ReadSnapshot(factory) as snapshot:
        assert snapshot.connection.execute(
            "SELECT count(*) FROM durable_jobs WHERE job_id=?",
            (first.response["job_id"],),
        ).fetchone() == (1,)
        assert snapshot.connection.execute(
            "SELECT count(*) FROM command_receipts WHERE command_id=?",
            (command_id,),
        ).fetchone() == (1,)
        assert snapshot.connection.execute(
            "SELECT action_type FROM audit_events WHERE command_id=?",
            (command_id,),
        ).fetchone() == ("infrastructure.workbook.export_request",)


def test_generate_workbook_scope_revalidation_fails_before_receipt(infra):
    service, factory, _ = infra
    command_id = new_uuid4()
    with pytest.raises(SomaError) as error:
        service.execute(
            "GenerateInfrastructureWorkbook",
            command_id=command_id,
            payload={
                "mode": "discovery",
                "scope": {"scope_kind": "site", "site_id": new_uuid4()},
                "destination_directory": r"D:\Exports",
            },
        )
    assert error.value.code == "INFRA_STALE"
    with ReadSnapshot(factory) as snapshot:
        assert snapshot.connection.execute(
            "SELECT count(*) FROM command_receipts WHERE command_id=?",
            (command_id,),
        ).fetchone() == (0,)
        assert snapshot.connection.execute(
            "SELECT count(*) FROM durable_jobs WHERE job_type='INFRA_WORKBOOK_EXPORT_V1'",
        ).fetchone() == (0,)


def test_stage_workbook_requires_persisted_setting_and_coalesces_by_revision(initialized_database):
    from soma.infrastructure.settings import (
        IMPORT_DIRECTORY_KEY,
        build_import_directory_setting_registry,
    )
    from soma.reference.application.settings_service import SettingService

    path, factory_builder = initialized_database
    factory = factory_builder(path)
    settings = SettingService(
        factory,
        build_import_directory_setting_registry(r"D:\SOMA"),
    )
    service = InfrastructureService(factory, setting_service=settings)

    missing_command = new_uuid4()
    with pytest.raises(SomaError) as error:
        service.execute(
            "StageInfrastructureWorkbookCheck",
            command_id=missing_command,
            payload={"setting_revision": 1},
        )
    assert error.value.code == "INFRA_STALE"

    settings.write(
        command_id=new_uuid4(),
        setting_key=IMPORT_DIRECTORY_KEY,
        base_revision=None,
        value={"path": r"D:\Imports"},
    )
    first_command = new_uuid4()
    second_command = new_uuid4()
    first = service.execute(
        "StageInfrastructureWorkbookCheck",
        command_id=first_command,
        payload={"setting_revision": 1},
    )
    second = service.execute(
        "StageInfrastructureWorkbookCheck",
        command_id=second_command,
        payload={"setting_revision": 1},
    )
    assert first.response["job_type"] == "INFRA_WORKBOOK_STAGE_V1"
    assert first.response["state"] == "queued"
    assert second.response["job_id"] == first.response["job_id"]
    assert second.response["command_id"] == second_command
    with ReadSnapshot(factory) as snapshot:
        assert snapshot.connection.execute(
            "SELECT count(*) FROM durable_jobs WHERE job_type='INFRA_WORKBOOK_STAGE_V1'",
        ).fetchone() == (1,)
        assert snapshot.connection.execute(
            "SELECT count(*) FROM command_receipts WHERE command_id IN (?,?)",
            (first_command, second_command),
        ).fetchone() == (2,)


def test_workbook_enqueue_audit_failure_rolls_back_job_and_receipt(infra, monkeypatch):
    service, factory, _ = infra
    command_id = new_uuid4()

    def fail_audit(*args, **kwargs):
        raise RuntimeError("injected workbook enqueue audit failure")

    monkeypatch.setattr(service.boundary._audit_writer, "write", fail_audit)
    with pytest.raises(RuntimeError, match="injected workbook enqueue audit failure"):
        service.execute(
            "GenerateInfrastructureWorkbook",
            command_id=command_id,
            payload={
                "mode": "round_trip",
                "scope": {"scope_kind": "all"},
                "destination_directory": r"D:\Exports",
            },
        )
    with ReadSnapshot(factory) as snapshot:
        assert snapshot.connection.execute(
            "SELECT count(*) FROM command_receipts WHERE command_id=?",
            (command_id,),
        ).fetchone() == (0,)
        assert snapshot.connection.execute(
            "SELECT count(*) FROM durable_jobs WHERE job_type='INFRA_WORKBOOK_EXPORT_V1'",
        ).fetchone() == (0,)
