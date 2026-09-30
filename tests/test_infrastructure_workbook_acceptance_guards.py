from __future__ import annotations

import pytest

from soma.foundation.errors import SomaError
from soma.foundation.identifiers import new_uuid4
from soma.foundation.persistence.uow import ReadSnapshot
from soma.infrastructure.services.core import InfrastructureService
from soma.infrastructure.services.workbook_acceptance import (
    PrimaryIpIntent,
    RackPlacementIntent,
    validate_containment_batch,
    validate_primary_ip_batch,
    validate_rack_placement_batch,
)
from soma.reference.application.customer_service import CustomerReferenceService


def _assembled(initialized_database):
    database_path, factory_builder = initialized_database
    factory = factory_builder(database_path)
    service = InfrastructureService(factory)
    customer_id = CustomerReferenceService(factory).create_customer_organization(
        command_id=new_uuid4(),
        name="Workbook acceptance guard customer",
    ).customer_org_id
    return factory, service, customer_id


def _command(service, command: str, **payload):
    return service.execute(
        command,
        command_id=new_uuid4(),
        payload=payload,
    ).response


def _site(service, customer_id: str, *, name: str):
    return _command(
        service,
        "CreateSite",
        customer_org_id=customer_id,
        name=name,
        address_text=f"{name} address",
    )["target"]["id"]


def _network_element(service, site_id: str, *, name: str):
    return _command(
        service,
        "CreateNetworkElement",
        new_element={
            "site_id": site_id,
            "operational_name": name,
        },
    )["target"]["id"]


def test_workbook_batch_rack_guard_detects_conflict_between_two_planned_moves(
    initialized_database,
) -> None:
    factory, service, customer_id = _assembled(initialized_database)
    site_id = _site(service, customer_id, name="Rack Guard Site")
    room_id = _command(service, "CreateRoom", site_id=site_id, name="Room")["target"]["id"]
    rack_id = _command(
        service,
        "CreateRack",
        room_id=room_id,
        name="Rack",
        height_u=42,
    )["target"]["id"]
    first = _network_element(service, site_id, name="NE-RACK-1")
    second = _network_element(service, site_id, name="NE-RACK-2")

    with ReadSnapshot(factory) as snapshot:
        with pytest.raises(SomaError) as error:
            validate_rack_placement_batch(
                snapshot,
                (
                    RackPlacementIntent(first, rack_id, 10, 4),
                    RackPlacementIntent(second, rack_id, 12, 2),
                ),
            )
    assert error.value.code == "RACK_U_OCCUPIED"


def test_workbook_batch_rack_guard_rejects_cross_site_target(
    initialized_database,
) -> None:
    factory, service, customer_id = _assembled(initialized_database)
    first_site = _site(service, customer_id, name="Rack Site A")
    second_site = _site(service, customer_id, name="Rack Site B")
    room_id = _command(service, "CreateRoom", site_id=first_site, name="Room A")["target"]["id"]
    rack_id = _command(
        service,
        "CreateRack",
        room_id=room_id,
        name="Rack A",
        height_u=42,
    )["target"]["id"]
    element = _network_element(service, second_site, name="NE-CROSS-SITE")

    with ReadSnapshot(factory) as snapshot:
        with pytest.raises(SomaError) as error:
            validate_rack_placement_batch(
                snapshot,
                (RackPlacementIntent(element, rack_id, 1, 1),),
            )
    assert error.value.code == "PLACEMENT_CROSS_SITE"


def test_workbook_batch_containment_guard_detects_cycle_only_created_by_batch(
    initialized_database,
) -> None:
    factory, service, customer_id = _assembled(initialized_database)
    site_id = _site(service, customer_id, name="Containment Guard Site")
    first = _network_element(service, site_id, name="NE-CYCLE-1")
    second = _network_element(service, site_id, name="NE-CYCLE-2")

    with ReadSnapshot(factory) as snapshot:
        with pytest.raises(SomaError) as error:
            validate_containment_batch(
                snapshot,
                {
                    first: second,
                    second: first,
                },
            )
    assert error.value.code == "CONTAINMENT_CYCLE"


def test_workbook_batch_primary_guard_rejects_two_selected_primaries() -> None:
    with pytest.raises(SomaError) as error:
        validate_primary_ip_batch(
            (
                PrimaryIpIntent("target", False, True),
                PrimaryIpIntent("target", False, True),
            )
        )
    assert error.value.code == "IP_PRIMARY_CONFLICT"


def test_workbook_batch_primary_guard_requires_replacement_when_unsetting_current() -> None:
    with pytest.raises(SomaError) as error:
        validate_primary_ip_batch(
            (
                PrimaryIpIntent("target", True, False),
                PrimaryIpIntent("target", False, None),
            )
        )
    assert error.value.code == "IP_PRIMARY_CONFLICT"

    validate_primary_ip_batch(
        (
            PrimaryIpIntent("target", True, False),
            PrimaryIpIntent("target", False, True),
        )
    )
