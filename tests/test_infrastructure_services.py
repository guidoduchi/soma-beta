from __future__ import annotations

import sqlite3

import pytest

from soma.foundation.errors import SomaError
from soma.foundation.identifiers import new_uuid4
from soma.foundation.persistence.uow import ReadSnapshot
from soma.infrastructure.services.core import InfrastructureService
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


def test_new_migration_preserves_prefix(tmp_path, migration_directory, security_provider):
    from test_foundation_durable_job_migration import _runner, _stage_prefix
    prefix = tmp_path / "prefix"
    _stage_prefix(migration_directory, prefix, 13)
    database = tmp_path / "upgrade.db"
    assert _runner(database, prefix, security_provider).initialize_or_migrate() == 13
    with sqlite3.connect(database) as connection:
        before = connection.execute("SELECT * FROM schema_migrations ORDER BY sequence").fetchall()
        instance = connection.execute("SELECT * FROM instance_metadata").fetchall()
    assert _runner(database, migration_directory, security_provider).initialize_or_migrate() == 14
    with sqlite3.connect(database) as connection:
        assert connection.execute("SELECT * FROM schema_migrations WHERE sequence<=13 ORDER BY sequence").fetchall() == before
        assert connection.execute("SELECT * FROM instance_metadata").fetchall() == instance
        assert connection.execute("PRAGMA foreign_key_check").fetchall() == []
