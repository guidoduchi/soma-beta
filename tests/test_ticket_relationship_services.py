from __future__ import annotations

import json

import pytest

from soma.foundation.errors import SomaError
from soma.foundation.identifiers import new_uuid4
from soma.reference.application.customer_service import CustomerReferenceService
from soma.tickets.device_references import DeviceReferenceService
from soma.tickets.relationships import TicketDeviceReferenceRelationshipService
from soma.tickets.rfc_hierarchy import RfcHierarchyService
from soma.tickets.rfcs import RfcService
from soma.tickets.service_requests import ServiceRequestService


def _factory(initialized_database):
    database_path, factory_for_path = initialized_database
    return factory_for_path(database_path)


def _read(initialized_database):
    return _factory(initialized_database).open_authoritative(read_only=True, require_wal=True)


def test_add_subordinate_preserves_two_level_authority_and_idempotency(initialized_database) -> None:
    factory = _factory(initialized_database)
    customers = CustomerReferenceService(factory)
    customer = customers.create_customer_organization(command_id=new_uuid4(), name="Hierarchy Customer")
    rfcs = RfcService(factory)
    hierarchy = RfcHierarchyService(factory)
    root = rfcs.create_or_adopt_identity(
        command_id=new_uuid4(),
        rfc_no="NC20260804001001",
        creation_context="manual",
        customer_org_id=customer.customer_org_id,
    )
    child = rfcs.create_or_adopt_identity(
        command_id=new_uuid4(),
        rfc_no="NC20260804001002",
        creation_context="manual",
        customer_org_id=customer.customer_org_id,
    )

    applied = hierarchy.add_subordinate(
        command_id=new_uuid4(),
        parent_rfc_id=root.rfc_id,
        child_rfc_id=child.rfc_id,
        base_revisions={root.rfc_id: 1, child.rfc_id: 1},
        reason_category="reviewed_hierarchy",
    )
    assert applied.no_change is False
    assert applied.parent_revision == 2
    assert applied.child_revision == 2
    assert applied.warnings == ()

    no_change_command = new_uuid4()
    no_change = hierarchy.add_subordinate(
        command_id=no_change_command,
        parent_rfc_id=root.rfc_id,
        child_rfc_id=child.rfc_id,
        base_revisions={root.rfc_id: 2, child.rfc_id: 2},
        reason_category="reviewed_hierarchy",
    )
    assert no_change.no_change is True
    assert no_change.rfc_hierarchy_edge_id == applied.rfc_hierarchy_edge_id

    replay = hierarchy.add_subordinate(
        command_id=no_change_command,
        parent_rfc_id=root.rfc_id,
        child_rfc_id=child.rfc_id,
        base_revisions={root.rfc_id: 2, child.rfc_id: 2},
        reason_category="reviewed_hierarchy",
    )
    assert replay.replayed is True
    assert replay.no_change is True

    connection = _read(initialized_database)
    try:
        assert connection.execute(
            "SELECT count(*) FROM rfc_hierarchy_edges WHERE parent_rfc_id=? AND child_rfc_id=? AND edge_state='active'",
            (root.rfc_id, child.rfc_id),
        ).fetchone()[0] == 1
        assert connection.execute(
            "SELECT count(*) FROM audit_events WHERE action_type='ticket.rfc.hierarchy_changed'"
        ).fetchone()[0] == 1
        payload = connection.execute(
            "SELECT payload_json FROM audit_events WHERE action_type='ticket.rfc.hierarchy_changed'"
        ).fetchone()[0]
        assert json.loads(payload)["new_parent_rfc_id"] == root.rfc_id
    finally:
        connection.close()


def test_hierarchy_allows_more_than_twenty_children_and_warns_on_unknown_customer(initialized_database) -> None:
    factory = _factory(initialized_database)
    rfcs = RfcService(factory)
    hierarchy = RfcHierarchyService(factory)
    root = rfcs.create_or_adopt_identity(
        command_id=new_uuid4(),
        rfc_no="NC20260804002000",
        creation_context="manual",
    )
    root_revision = 1
    for offset in range(1, 22):
        child = rfcs.create_or_adopt_identity(
            command_id=new_uuid4(),
            rfc_no=f"NC{20260804002000 + offset:014d}",
            creation_context="manual",
        )
        result = hierarchy.add_subordinate(
            command_id=new_uuid4(),
            parent_rfc_id=root.rfc_id,
            child_rfc_id=child.rfc_id,
            base_revisions={root.rfc_id: root_revision, child.rfc_id: 1},
            reason_category="reviewed_hierarchy",
        )
        root_revision += 1
        assert result.parent_revision == root_revision
        assert result.warnings == ("RFC_CUSTOMER_UNRESOLVED",)

    connection = _read(initialized_database)
    try:
        assert connection.execute(
            "SELECT count(*) FROM rfc_hierarchy_edges WHERE parent_rfc_id=? AND edge_state='active'",
            (root.rfc_id,),
        ).fetchone()[0] == 21
    finally:
        connection.close()


def test_hierarchy_rejects_known_customer_mismatch_without_edge_mutation(initialized_database) -> None:
    factory = _factory(initialized_database)
    customers = CustomerReferenceService(factory)
    customer_a = customers.create_customer_organization(command_id=new_uuid4(), name="Customer A")
    customer_b = customers.create_customer_organization(command_id=new_uuid4(), name="Customer B")
    rfcs = RfcService(factory)
    hierarchy = RfcHierarchyService(factory)
    root = rfcs.create_or_adopt_identity(
        command_id=new_uuid4(),
        rfc_no="NC20260804003001",
        creation_context="manual",
        customer_org_id=customer_a.customer_org_id,
    )
    child = rfcs.create_or_adopt_identity(
        command_id=new_uuid4(),
        rfc_no="NC20260804003002",
        creation_context="manual",
        customer_org_id=customer_b.customer_org_id,
    )

    with pytest.raises(SomaError) as mismatch:
        hierarchy.add_subordinate(
            command_id=new_uuid4(),
            parent_rfc_id=root.rfc_id,
            child_rfc_id=child.rfc_id,
            base_revisions={root.rfc_id: 1, child.rfc_id: 1},
            reason_category="reviewed_hierarchy",
        )
    assert mismatch.value.code == "RFC_CUSTOMER_MISMATCH"

    connection = _read(initialized_database)
    try:
        assert connection.execute("SELECT count(*) FROM rfc_hierarchy_edges").fetchone()[0] == 0
        assert connection.execute(
            "SELECT revision FROM rfcs WHERE rfc_id=?", (root.rfc_id,)
        ).fetchone()[0] == 1
        assert connection.execute(
            "SELECT revision FROM rfcs WHERE rfc_id=?", (child.rfc_id,)
        ).fetchone()[0] == 1
    finally:
        connection.close()


def test_device_reference_links_are_history_preserving_and_do_not_replace_identity(initialized_database) -> None:
    factory = _factory(initialized_database)
    srs = ServiceRequestService(factory)
    rfcs = RfcService(factory)
    devices = DeviceReferenceService(factory)
    relationships = TicketDeviceReferenceRelationshipService(factory)

    sr = srs.create_manual_service_request(command_id=new_uuid4())
    rfc = rfcs.create_or_adopt_identity(
        command_id=new_uuid4(),
        rfc_no="NC20260804004001",
        creation_context="manual",
    )
    device = devices.create(command_id=new_uuid4(), operational_name="device-before-regularization")

    sr_link = relationships.link(
        command_id=new_uuid4(),
        ticket_type="service_request",
        ticket_id=sr.service_request_id,
        device_reference_id=device.device_reference_id,
        target_base_revision=1,
    )
    assert sr_link.state == "active"
    assert sr_link.target_revision == 1

    duplicate = relationships.link(
        command_id=new_uuid4(),
        ticket_type="service_request",
        ticket_id=sr.service_request_id,
        device_reference_id=device.device_reference_id,
        target_base_revision=1,
    )
    assert duplicate.no_change is True
    assert duplicate.relationship_id == sr_link.relationship_id

    rfc_link = relationships.link(
        command_id=new_uuid4(),
        ticket_type="rfc",
        ticket_id=rfc.rfc_id,
        device_reference_id=device.device_reference_id,
        target_base_revision=1,
    )
    assert rfc_link.state == "active"
    assert rfc_link.target_revision == 1

    unlink_command = new_uuid4()
    unlinked = relationships.unlink(
        command_id=unlink_command,
        ticket_type="service_request",
        ticket_id=sr.service_request_id,
        device_reference_id=device.device_reference_id,
        target_base_revision=1,
        reason_category="operator_unlink",
    )
    assert unlinked.relationship_id == sr_link.relationship_id
    assert unlinked.state == "unlinked"
    assert unlinked.target_revision == 1

    replay = relationships.unlink(
        command_id=unlink_command,
        ticket_type="service_request",
        ticket_id=sr.service_request_id,
        device_reference_id=device.device_reference_id,
        target_base_revision=1,
        reason_category="operator_unlink",
    )
    assert replay.replayed is True
    assert replay.state == "unlinked"

    absent = relationships.unlink(
        command_id=new_uuid4(),
        ticket_type="service_request",
        ticket_id=sr.service_request_id,
        device_reference_id=device.device_reference_id,
        target_base_revision=1,
        reason_category="operator_unlink",
    )
    assert absent.no_change is True
    assert absent.state == "absent"

    connection = _read(initialized_database)
    try:
        assert connection.execute(
            "SELECT link_state FROM sr_device_reference_links WHERE sr_device_reference_link_id=?",
            (sr_link.relationship_id,),
        ).fetchone()[0] == "unlinked"
        assert connection.execute(
            "SELECT link_state FROM rfc_device_reference_links WHERE rfc_device_reference_link_id=?",
            (rfc_link.relationship_id,),
        ).fetchone()[0] == "active"
        assert connection.execute(
            "SELECT revision FROM device_references WHERE device_reference_id=?",
            (device.device_reference_id,),
        ).fetchone()[0] == 1
        assert connection.execute(
            "SELECT revision FROM service_requests WHERE service_request_id=?",
            (sr.service_request_id,),
        ).fetchone()[0] == 1
        assert connection.execute(
            "SELECT revision FROM rfcs WHERE rfc_id=?",
            (rfc.rfc_id,),
        ).fetchone()[0] == 1
        payloads = [
            str(row[0])
            for row in connection.execute(
                "SELECT payload_json FROM audit_events WHERE action_type='ticket.device_reference.relationship_changed'"
            ).fetchall()
        ]
        assert len(payloads) == 3
        assert all("device-before-regularization" not in payload for payload in payloads)
    finally:
        connection.close()


def test_device_reference_link_stales_on_ticket_revision_change(initialized_database) -> None:
    factory = _factory(initialized_database)
    srs = ServiceRequestService(factory)
    devices = DeviceReferenceService(factory)
    relationships = TicketDeviceReferenceRelationshipService(factory)
    sr = srs.create_manual_service_request(command_id=new_uuid4())
    device = devices.create(command_id=new_uuid4(), operational_name="stale-target")
    srs.attach_official_identity(
        command_id=new_uuid4(),
        service_request_id=sr.service_request_id,
        base_revision=1,
        official_sr_no="11223344",
        review_context_id="review-stale-device-link",
    )

    with pytest.raises(SomaError) as stale:
        relationships.link(
            command_id=new_uuid4(),
            ticket_type="service_request",
            ticket_id=sr.service_request_id,
            device_reference_id=device.device_reference_id,
            target_base_revision=1,
        )
    assert stale.value.code == "TICKET_RELATIONSHIP_STALE"
