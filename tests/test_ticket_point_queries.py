from __future__ import annotations

from soma.foundation.identifiers import new_uuid4
from soma.reference.application.customer_service import CustomerReferenceService
from soma.tickets.device_references import DeviceReferenceService
from soma.tickets.queries.rfcs import RfcQueryService
from soma.tickets.queries.service_requests import ServiceRequestQueryService
from soma.tickets.relationships import TicketDeviceReferenceRelationshipService
from soma.tickets.rfc_hierarchy import RfcHierarchyService
from soma.tickets.rfcs import RfcService
from soma.tickets.service_requests import ServiceRequestService


def _factory(initialized_database):
    database_path, factory_for_path = initialized_database
    return factory_for_path(database_path)


def _receipt_count(factory) -> int:
    connection = factory.open_authoritative(read_only=True, require_wal=True)
    try:
        return int(connection.execute("SELECT COUNT(*) FROM command_receipts").fetchone()[0])
    finally:
        connection.close()


def test_get_service_request_projects_identity_counts_and_stable_reference_token(initialized_database) -> None:
    factory = _factory(initialized_database)
    sr_service = ServiceRequestService(factory)
    device_service = DeviceReferenceService(factory)
    relationships = TicketDeviceReferenceRelationshipService(factory)
    queries = ServiceRequestQueryService(factory)

    sr = sr_service.create_manual_service_request(
        command_id=new_uuid4(),
        official_sr_no="87654321",
    )
    device = device_service.create(command_id=new_uuid4(), operational_name="edge-router-01")
    relationships.link(
        command_id=new_uuid4(),
        ticket_type="service_request",
        ticket_id=sr.service_request_id,
        device_reference_id=device.device_reference_id,
        target_base_revision=1,
    )

    before = _receipt_count(factory)
    detail = queries.get(service_request_id=sr.service_request_id)
    by_business_id = queries.get(business_identity="87654321")
    after = _receipt_count(factory)

    assert before == after
    assert detail == by_business_id
    assert detail.identity == {"official_sr_no": "87654321", "local_sr_no": None}
    assert detail.revision == 1
    assert detail.source_projection is None
    assert detail.linked_root_rfc_count == 0
    assert detail.device_reference_count == 1
    assert detail.warnings == ()
    assert detail.reference_context["service_request_id"] == sr.service_request_id
    assert detail.reference_context["customer"] is None
    assert detail.reference_context["contacts"] == {
        "customer_contact": None,
        "current_handler_reference": None,
    }
    assert len(detail.reference_context["review_fingerprint"]) == 64


def test_get_rfc_derives_roles_counts_customer_archive_and_unresolved_warning(initialized_database) -> None:
    factory = _factory(initialized_database)
    customer = CustomerReferenceService(factory).create_customer_organization(
        command_id=new_uuid4(),
        name="Point Query Customer",
    )
    rfc_service = RfcService(factory)
    hierarchy = RfcHierarchyService(factory)
    devices = DeviceReferenceService(factory)
    relationships = TicketDeviceReferenceRelationshipService(factory)
    queries = RfcQueryService(factory)

    root = rfc_service.create_or_adopt_identity(
        command_id=new_uuid4(),
        rfc_no="NC20260804002001",
        creation_context="manual",
        customer_org_id=customer.customer_org_id,
    )
    child = rfc_service.create_or_adopt_identity(
        command_id=new_uuid4(),
        rfc_no="NC20260804002002",
        creation_context="manual",
        customer_org_id=customer.customer_org_id,
    )
    hierarchy.add_subordinate(
        command_id=new_uuid4(),
        parent_rfc_id=root.rfc_id,
        child_rfc_id=child.rfc_id,
        base_revisions={root.rfc_id: 1, child.rfc_id: 1},
        reason_category="reviewed_hierarchy",
    )
    device = devices.create(command_id=new_uuid4(), operational_name="core-device-01")
    relationships.link(
        command_id=new_uuid4(),
        ticket_type="rfc",
        ticket_id=root.rfc_id,
        device_reference_id=device.device_reference_id,
        target_base_revision=2,
    )

    before = _receipt_count(factory)
    root_detail = queries.get(rfc_no="NC20260804002001")
    child_detail = queries.get(rfc_id=child.rfc_id)
    after = _receipt_count(factory)

    assert before == after
    assert root_detail.rfc_id == root.rfc_id
    assert root_detail.revision == 2
    assert root_detail.hierarchy_role == "root"
    assert root_detail.customer_org_id == customer.customer_org_id
    assert root_detail.local_archive_state == "active"
    assert root_detail.source_projection is None
    assert root_detail.direct_service_request_count == 0
    assert root_detail.device_reference_count == 1
    assert root_detail.subordinate_count == 1
    assert root_detail.warnings == ()

    assert child_detail.hierarchy_role == "subordinate"
    assert child_detail.subordinate_count == 0
    assert child_detail.direct_service_request_count == 0

    unresolved = rfc_service.create_or_adopt_identity(
        command_id=new_uuid4(),
        rfc_no="NC20260804002003",
        creation_context="manual",
    )
    unresolved_detail = queries.get(rfc_id=unresolved.rfc_id)
    assert unresolved_detail.hierarchy_role == "standalone"
    assert unresolved_detail.customer_org_id is None
    assert unresolved_detail.warnings == ("RFC_CUSTOMER_UNRESOLVED",)
