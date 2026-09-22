from __future__ import annotations

import pytest

from soma.foundation.errors import SomaError, ValidationError
from soma.foundation.identifiers import new_uuid4
from soma.foundation.persistence.uow import ReadSnapshot
from soma.inventory.domain.requests import SpareRequestAllocationIntent
from soma.inventory.queries.requests_rma import InventoryRequestsRmaQueryService
from soma.inventory.services.participants import InventoryReferenceDependencyValidator
from soma.inventory.services.requests_rma import InventoryRequestsRmaService
from soma.reference.application.contact_service import ContactReferenceService
from soma.reference.application.customer_service import CustomerReferenceService
from soma.reference.application.lifecycle_service import ReferenceLifecycleService
from soma.reference.domain.dependencies import ReferenceDependencyRegistry, ReferenceTarget
from test_inventory_requests_rma import _dispatch_location, _factory, _need, _sr


def _create_request(
    factory,
    *,
    official_sr: str,
    requester_contact_id: str,
    receiver_contact_id: str,
    bom: str,
) -> tuple[InventoryRequestsRmaService, str]:
    sr = _sr(factory, official_sr)
    need = _need(
        factory,
        sr_id=sr.service_request_id,
        device_name=f"REQ-{official_sr}",
        bom=bom,
    )
    location_id = _dispatch_location(factory, official_sr[-3:])
    service = InventoryRequestsRmaService(factory)
    created = service.create_spare_request_draft(
        command_id=new_uuid4(),
        service_request_id=sr.service_request_id,
        requester_contact_id=requester_contact_id,
        allocations=(SpareRequestAllocationIntent(need, 1),),
        mode="delivery",
        receiver_contact_id=receiver_contact_id,
        dispatch_location_id=location_id,
    )
    return service, str(created["spare_request_id"])


def test_t067_requester_role_preserves_creation_context_and_shows_current_contact_separately(
    initialized_database,
) -> None:
    factory = _factory(initialized_database)
    customers = CustomerReferenceService(factory)
    customer_a = customers.create_customer_organization(
        command_id=new_uuid4(),
        name="Requester Customer A",
    )
    customer_b = customers.create_customer_organization(
        command_id=new_uuid4(),
        name="Requester Customer B",
    )
    contacts = ContactReferenceService(factory)
    requester = contacts.create_contact(
        command_id=new_uuid4(),
        name="Original Requester",
        initial_customer_org_id=customer_a.customer_org_id,
    )
    receiver = contacts.create_contact(
        command_id=new_uuid4(),
        name="Independent Receiver",
    )
    service, request_id = _create_request(
        factory,
        official_sr="97900067",
        requester_contact_id=requester.contact_id,
        receiver_contact_id=receiver.contact_id,
        bom="REQ-T067",
    )

    query = InventoryRequestsRmaQueryService(factory)
    before = query.request_detail(request_id)
    creation_before = before["requester"]["creation_context"]
    assert before["requester"]["contact_id"] == requester.contact_id
    assert before["draft_logistics"]["receiver_contact_id"] == receiver.contact_id
    assert requester.contact_id != receiver.contact_id
    assert creation_before["display_name_snapshot"] == "Original Requester"
    assert creation_before["contact_revision_at_creation"] == 1
    assert creation_before["customer_org_id_at_creation"] == customer_a.customer_org_id
    assert before["requester"]["current_context"] == {
        "display_name": "Original Requester",
        "lifecycle_state": "active",
        "revision": 1,
        "affiliation_id": creation_before["affiliation_id_at_creation"],
        "customer_org_id": customer_a.customer_org_id,
    }

    contacts.update_contact_descriptive_data(
        command_id=new_uuid4(),
        contact_id=requester.contact_id,
        base_revision=1,
        name="Current Requester Name",
    )
    contacts.change_contact_affiliation(
        command_id=new_uuid4(),
        contact_id=requester.contact_id,
        base_revision=2,
        new_customer_org_id=customer_b.customer_org_id,
        reason_category="role_changed",
    )

    changed = query.request_detail(request_id)
    assert changed["requester"]["creation_context"] == creation_before
    assert changed["requester"]["current_context"]["display_name"] == "Current Requester Name"
    assert changed["requester"]["current_context"]["lifecycle_state"] == "active"
    assert changed["requester"]["current_context"]["revision"] == 3
    assert (
        changed["requester"]["current_context"]["customer_org_id"]
        == customer_b.customer_org_id
    )
    assert (
        changed["requester"]["current_context"]["affiliation_id"]
        != creation_before["affiliation_id_at_creation"]
    )

    terminal = service.cancel_or_reject_spare_request(
        command_id=new_uuid4(),
        spare_request_id=request_id,
        base_revision=1,
        action="cancelled",
        reason_code="operator_cancelled",
    )
    assert terminal["state"] == "terminal"

    terminal_detail = query.request_detail(request_id)
    assert terminal_detail["lifecycle_state"] == "cancelled"
    assert terminal_detail["requester"]["contact_id"] == requester.contact_id
    assert terminal_detail["requester"]["creation_context"] == creation_before
    assert terminal_detail["requester"]["current_context"] == changed["requester"]["current_context"]


def test_t068_active_requester_blocks_contact_archive_until_request_terminal(
    initialized_database,
) -> None:
    factory = _factory(initialized_database)
    contacts = ContactReferenceService(factory)
    requester = contacts.create_contact(
        command_id=new_uuid4(),
        name="Archive Protected Requester",
    )
    receiver = contacts.create_contact(
        command_id=new_uuid4(),
        name="Archive Independent Receiver",
    )
    service, request_id = _create_request(
        factory,
        official_sr="97900068",
        requester_contact_id=requester.contact_id,
        receiver_contact_id=receiver.contact_id,
        bom="REQ-T068",
    )

    registry = ReferenceDependencyRegistry()
    registry.register(InventoryReferenceDependencyValidator())
    registry.finalize(required_validator_ids=("inventory",))
    lifecycle = ReferenceLifecycleService(factory, registry)

    blocked_preview = lifecycle.preview(
        operation="archive",
        target_type="contact",
        target_id=requester.contact_id,
        base_revision=1,
        limit=50,
    )
    assert blocked_preview.revision == 1
    assert blocked_preview.would_be_eligible is False
    assert blocked_preview.exact_blocker_count == 1
    assert len(blocked_preview.blockers) == 1
    assert blocked_preview.blockers[0].validator_id == "inventory"
    assert blocked_preview.blockers[0].blocker_id == request_id
    assert blocked_preview.blockers[0].reason_code == "active_spare_request_requester"

    blocked_command = new_uuid4()
    with pytest.raises(SomaError) as blocked:
        lifecycle.archive_reference(
            command_id=blocked_command,
            target_type="contact",
            target_id=requester.contact_id,
            base_revision=1,
            reason_category="operator_archive",
        )
    assert blocked.value.code == "ARCHIVE_BLOCKED"

    service.cancel_or_reject_spare_request(
        command_id=new_uuid4(),
        spare_request_id=request_id,
        base_revision=1,
        action="cancelled",
        reason_code="operator_cancelled",
    )

    clear_preview = lifecycle.preview(
        operation="archive",
        target_type="contact",
        target_id=requester.contact_id,
        base_revision=1,
        limit=50,
    )
    assert clear_preview.revision == 1
    assert clear_preview.would_be_eligible is True
    assert clear_preview.exact_blocker_count == 0
    assert clear_preview.blockers == ()

    archived = lifecycle.archive_reference(
        command_id=new_uuid4(),
        target_type="contact",
        target_id=requester.contact_id,
        base_revision=1,
        reason_category="operator_archive",
    )
    assert archived.outcome == "APPLIED"
    assert archived.revision == 2

    detail = InventoryRequestsRmaQueryService(factory).request_detail(request_id)
    assert detail["lifecycle_state"] == "cancelled"
    assert detail["requester"]["contact_id"] == requester.contact_id
    assert detail["requester"]["creation_context"]["display_name_snapshot"] == (
        "Archive Protected Requester"
    )
    assert detail["requester"]["creation_context"]["contact_revision_at_creation"] == 1
    assert detail["requester"]["current_context"] == {
        "display_name": "Archive Protected Requester",
        "lifecycle_state": "archived",
        "revision": 2,
        "affiliation_id": None,
        "customer_org_id": None,
    }


def test_inventory_dependency_cursor_preserves_multi_role_blockers(
    initialized_database,
) -> None:
    factory = _factory(initialized_database)
    contact = ContactReferenceService(factory).create_contact(
        command_id=new_uuid4(),
        name="Requester And Receiver",
    )
    _, request_id = _create_request(
        factory,
        official_sr="97909999",
        requester_contact_id=contact.contact_id,
        receiver_contact_id=contact.contact_id,
        bom="REQ-CURSOR",
    )
    validator = InventoryReferenceDependencyValidator()
    target = ReferenceTarget("contact", contact.contact_id)

    with ReadSnapshot(factory) as snapshot:
        assert validator.count_archive_blockers(snapshot, target) == 2
        first = validator.list_archive_blockers(snapshot, target, None, 1)
        assert len(first.blockers) == 1
        assert first.continuation is not None

        second = validator.list_archive_blockers(
            snapshot,
            target,
            first.continuation,
            1,
        )
        assert len(second.blockers) == 1
        assert second.continuation is None
        assert {first.blockers[0].reason_code, second.blockers[0].reason_code} == {
            "active_spare_request_requester",
            "active_spare_request_receiver",
        }
        assert first.blockers[0].blocker_id == request_id
        assert second.blockers[0].blocker_id == request_id

        with pytest.raises(ValidationError, match="cursor is invalid"):
            validator.list_archive_blockers(
                snapshot,
                target,
                first.continuation[:-1] + ("A" if first.continuation[-1] != "A" else "B"),
                1,
            )


def test_inventory_dependency_guard_count_and_page_are_set_based(
    initialized_database,
) -> None:
    factory = _factory(initialized_database)
    contact = ContactReferenceService(factory).create_contact(
        command_id=new_uuid4(),
        name="Set Based Dependency Contact",
    )
    _create_request(
        factory,
        official_sr="97909998",
        requester_contact_id=contact.contact_id,
        receiver_contact_id=contact.contact_id,
        bom="REQ-SET-BASED",
    )
    validator = InventoryReferenceDependencyValidator()
    target = ReferenceTarget("contact", contact.contact_id)

    statements: list[str] = []
    with ReadSnapshot(factory) as snapshot:
        snapshot.connection.set_trace_callback(statements.append)
        assert validator.count_archive_blockers(snapshot, target) == 2
        page = validator.list_archive_blockers(snapshot, target, None, 1)
        assert len(page.blockers) == 1
        assert page.continuation is not None

    selects = [
        statement
        for statement in statements
        if statement.lstrip().upper().startswith("SELECT")
    ]
    assert len(selects) == 2
    assert "COUNT(*) FROM (" in selects[0]
    assert "ORDER BY blocker_id,reason_code LIMIT 2" in selects[1]
