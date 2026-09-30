from __future__ import annotations

import pytest

from soma.foundation.errors import IntegrityFailure
from soma.foundation.identifiers import new_uuid4
from soma.foundation.persistence.uow import ReadSnapshot, UnitOfWork
from soma.infrastructure.queries.core import InfrastructureQueries
from soma.infrastructure.services.core import InfrastructureService
from soma.infrastructure.services.participants import DeviceReferenceResolutionReader
from soma.inventory.services.participants import InventorySiteDependencyValidator
from soma.objectives_tasks.services.participants import TaskSiteDependencyValidator
from soma.objectives_tasks.services.task_planning import TaskPlanningService
from soma.objectives_tasks.services.task_relationships import TaskRelationshipService
from soma.reference.application.customer_service import CustomerReferenceService
from soma.tickets.device_references import DeviceReferenceService
from soma.tickets.infrastructure_participants import TicketSiteDependencyValidator
from soma.tickets.relationships import TicketDeviceReferenceRelationshipService
from soma.tickets.rfcs import RfcService
from soma.tickets.service_requests import ServiceRequestService


def _factory(initialized_database):
    path, factory_builder = initialized_database
    return factory_builder(path)


def _site_and_element(service, factory, *, suffix):
    customer = CustomerReferenceService(factory).create_customer_organization(
        command_id=new_uuid4(), name=f"Dependency customer {suffix}"
    ).customer_org_id
    site_id = service.execute(
        "CreateSite",
        command_id=new_uuid4(),
        payload={
            "customer_org_id": customer,
            "name": f"Site {suffix}",
            "address_text": f"{suffix} Main Street",
        },
    ).response["target"]["id"]
    network_element_id = service.execute(
        "CreateNetworkElement",
        command_id=new_uuid4(),
        payload={
            "new_element": {
                "site_id": site_id,
                "operational_name": f"Node {suffix}",
            }
        },
    ).response["target"]["id"]
    return site_id, network_element_id


def _record_resolution(factory, device_reference_id, network_element_id):
    command_id = new_uuid4()
    event_id = new_uuid4()
    with UnitOfWork(factory) as uow:
        uow.connection.execute(
            "INSERT INTO command_receipts("
            "command_id,command_type,request_hash,target_type,target_id,committed_at_utc,"
            "result_type,result_id) VALUES (?,?,?,?,?,?,?,?)",
            (
                command_id,
                "TestResolveDeviceReference",
                "0" * 64,
                "device_reference",
                device_reference_id,
                1,
                "device_reference",
                device_reference_id,
            ),
        )
        uow.connection.execute(
            "INSERT INTO device_reference_resolution_events("
            "resolution_event_id,device_reference_id,event_kind,prior_network_element_id,"
            "new_network_element_id,reason_code,recorded_at_utc,command_id"
            ") VALUES (?,?,'link',NULL,?,NULL,1,?)",
            (event_id, device_reference_id, network_element_id, command_id),
        )
        uow.connection.execute(
            "INSERT INTO device_reference_resolution_current("
            "device_reference_id,network_element_id,revision,last_event_id,last_command_id"
            ") VALUES (?,?,1,?,?)",
            (device_reference_id, network_element_id, event_id, command_id),
        )


def test_device_resolution_reader_pages_one_site_without_cross_site_scan(initialized_database):
    factory = _factory(initialized_database)
    service = InfrastructureService(factory)
    devices = DeviceReferenceService(factory)
    first_site, first_element = _site_and_element(service, factory, suffix="A")
    second_site, second_element = _site_and_element(service, factory, suffix="B")

    first_devices = [
        devices.create(command_id=new_uuid4(), operational_name=f"site-a-{ordinal}")
        for ordinal in range(2)
    ]
    foreign = devices.create(command_id=new_uuid4(), operational_name="site-b")
    for device in first_devices:
        _record_resolution(factory, device.device_reference_id, first_element)
    _record_resolution(factory, foreign.device_reference_id, second_element)

    reader = DeviceReferenceResolutionReader()
    with ReadSnapshot(factory) as snapshot:
        first = reader.list_for_site(snapshot, first_site, None, 1)
        assert len(first["items"]) == 1
        assert first["continuation"] is not None
        second = reader.list_for_site(snapshot, first_site, first["continuation"], 1)
        assert second["continuation"] is None
        pairs = [
            (item["network_element_id"], item["device_reference_id"])
            for item in first["items"] + second["items"]
        ]
        assert pairs == sorted(
            (first_element, device.device_reference_id) for device in first_devices
        )
        assert all(item["device_reference_id"] != foreign.device_reference_id for item in first["items"] + second["items"])
        resolved = reader.resolution_for(snapshot, first_devices[0].device_reference_id)
        assert resolved["network_element_id"] == first_element
        assert resolved["site_id"] == first_site


def test_ticket_and_task_site_validators_page_current_links_and_feed_infrastructure_query(initialized_database):
    factory = _factory(initialized_database)
    resolution_reader = DeviceReferenceResolutionReader()
    ticket_validator = TicketSiteDependencyValidator(resolution_reader)
    task_validator = TaskSiteDependencyValidator(resolution_reader)
    service = InfrastructureService(
        factory,
        site_dependencies=(
            ticket_validator,
            task_validator,
            InventorySiteDependencyValidator(),
        ),
    )
    site_id, network_element_id = _site_and_element(service, factory, suffix="C")
    devices = DeviceReferenceService(factory)
    device = devices.create(command_id=new_uuid4(), operational_name="shared-device")
    _record_resolution(factory, device.device_reference_id, network_element_id)

    ticket_links = TicketDeviceReferenceRelationshipService(factory)
    sr = ServiceRequestService(factory).create_manual_service_request(command_id=new_uuid4())
    rfc = RfcService(factory).create_or_adopt_identity(
        command_id=new_uuid4(),
        rfc_no="NC20260929000001",
        creation_context="manual",
    )
    ticket_links.link(
        command_id=new_uuid4(),
        ticket_type="service_request",
        ticket_id=sr.service_request_id,
        device_reference_id=device.device_reference_id,
        target_base_revision=sr.revision,
    )
    ticket_links.link(
        command_id=new_uuid4(),
        ticket_type="rfc",
        ticket_id=rfc.rfc_id,
        device_reference_id=device.device_reference_id,
        target_base_revision=rfc.revision,
    )

    task = TaskPlanningService(factory).create_local_task(
        command_id=new_uuid4(),
        local_task_name="Site-linked Task",
        device_reference_ids=(device.device_reference_id,),
    )

    with ReadSnapshot(factory) as snapshot:
        assert ticket_validator.count_blockers(snapshot, site_id) == 2
        first = ticket_validator.list_blockers(snapshot, site_id, None, 1)
        assert len(first["blockers"]) == 1
        assert first["continuation"] == first["blockers"][0]
        second = ticket_validator.list_blockers(
            snapshot, site_id, first["continuation"], 1
        )
        assert len(second["blockers"]) == 1
        assert second["continuation"] is None
        assert first["blockers"][0] < second["blockers"][0]
        assert task_validator.count_blockers(snapshot, site_id) == 1
        task_page = task_validator.list_blockers(snapshot, site_id, None, 1)
        assert len(task_page["blockers"]) == 1
        assert ":task:" in task_page["blockers"][0]

    result = InfrastructureQueries(service).execute(
        "SiteArchiveBlockerQuery", {"site_id": site_id, "limit": 10}
    )
    assert result["indeterminate"] is False
    assert result["exact_count"] == 4
    assert [item["provider_order"] for item in result["items"]] == [0, 1, 1, 2]
    assert [item["blocker_kind"] for item in result["items"]] == [
        "network_element",
        "ticket",
        "ticket",
        "task",
    ]

    TaskRelationshipService(factory).change_task_relationship(
        command_id=new_uuid4(),
        task_id=task.task_id,
        task_revision=task.revision,
        relationship_kind="device",
        target_id=device.device_reference_id,
        action="unlink",
        reason_category="reviewed_unlink",
    )
    with ReadSnapshot(factory) as snapshot:
        assert task_validator.count_blockers(snapshot, site_id) == 0
        assert task_validator.list_blockers(snapshot, site_id, None, 10) == {
            "blockers": [],
            "continuation": None,
        }


def test_site_dependency_validators_fail_closed_on_malformed_resolution_provider(initialized_database):
    factory = _factory(initialized_database)
    site_id = new_uuid4()

    class MalformedResolutionProvider:
        @staticmethod
        def resolution_for(reader, device_reference_id):
            del reader, device_reference_id
            return None

        @staticmethod
        def list_for_site(reader, requested_site_id, cursor, limit):
            del reader, requested_site_id, cursor, limit
            return {
                "items": [
                    {
                        "network_element_id": "not-a-uuid",
                        "device_reference_id": new_uuid4(),
                    }
                ],
                "continuation": None,
            }

    ticket = TicketSiteDependencyValidator(MalformedResolutionProvider())
    task = TaskSiteDependencyValidator(MalformedResolutionProvider())
    with UnitOfWork(factory) as uow:
        assert ticket.guard_archive(uow, site_id) == "INDETERMINATE"
        assert task.guard_archive(uow, site_id) == "INDETERMINATE"

    with ReadSnapshot(factory) as snapshot:
        with pytest.raises(Exception):
            ticket.count_blockers(snapshot, site_id)
        with pytest.raises(Exception):
            task.count_blockers(snapshot, site_id)


def test_site_dependency_validators_reject_nonadvancing_provider_pages(initialized_database):
    factory = _factory(initialized_database)
    site_id = new_uuid4()
    network_element_id = new_uuid4()
    device_reference_id = new_uuid4()

    class NonAdvancingResolutionProvider:
        @staticmethod
        def resolution_for(reader, requested_device_reference_id):
            del reader, requested_device_reference_id
            return None

        @staticmethod
        def list_for_site(reader, requested_site_id, cursor, limit):
            del reader, requested_site_id, limit
            pair = [network_element_id, device_reference_id]
            return {
                "items": [
                    {
                        "network_element_id": pair[0],
                        "device_reference_id": pair[1],
                    }
                ],
                "continuation": pair if cursor is None else cursor,
            }

    validator = TicketSiteDependencyValidator(NonAdvancingResolutionProvider())
    with ReadSnapshot(factory) as snapshot:
        with pytest.raises(IntegrityFailure):
            validator.count_blockers(snapshot, site_id)
