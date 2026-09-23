from __future__ import annotations

import pytest

from soma.foundation.errors import SomaError
from soma.foundation.identifiers import new_uuid4
from soma.foundation.persistence.uow import UnitOfWork
from soma.inventory.services.participants import InventoryReferenceDependencyValidator
from soma.reference.application.contact_service import ContactReferenceService
from soma.reference.application.dispatch_service import DispatchLocationService
from soma.reference.application.lifecycle_service import ReferenceLifecycleService
from soma.reference.domain.dependencies import ReferenceDependencyRegistry


def _factory(initialized_database):
    database_path, factory_for_path = initialized_database
    return factory_for_path(database_path)


def _seed_fault_tag_pickup_dependency(
    factory,
    *,
    contact_id: str | None = None,
    dispatch_location_id: str | None = None,
) -> str:
    command_id = new_uuid4()
    fault_tag_id = new_uuid4()
    with UnitOfWork(factory) as uow:
        uow.connection.execute(
            "INSERT INTO command_receipts("
            "command_id,command_type,request_hash,target_type,target_id,"
            "committed_at_utc,result_type,result_id"
            ") VALUES (?, 'SeedFaultTagDependency', ?, 'fault_tag', ?, 1, 'fault_tag', ?)",
            (command_id, "0" * 64, fault_tag_id, fault_tag_id),
        )
        uow.connection.execute(
            "INSERT INTO fault_tags("
            "fault_tag_id,tracking_sequence,tracking_id,creation_origin,"
            "draft_return_method,draft_pickup_dispatch_location_id,"
            "draft_pickup_contact_id,draft_pickup_instructions,draft_revision,"
            "created_at_utc,created_command_id"
            ") VALUES (?,1,'FT-00000001','manual','pickup',?,?,NULL,1,1,?)",
            (fault_tag_id, dispatch_location_id, contact_id, command_id),
        )
        uow.connection.execute(
            "INSERT INTO fault_tag_current_projection("
            "fault_tag_id,state,archived,current_submission_snapshot_id,"
            "submitted_member_count,awaiting_receipt_count,awaiting_final_count,"
            "accepted_count,rejected_count,revision,input_fingerprint,last_command_id"
            ") VALUES (?,'draft',0,NULL,0,0,0,0,0,1,?,?)",
            (fault_tag_id, "a" * 64, command_id),
        )
    return fault_tag_id


def _lifecycle(factory) -> ReferenceLifecycleService:
    registry = ReferenceDependencyRegistry()
    registry.register(InventoryReferenceDependencyValidator())
    registry.finalize(required_validator_ids=("inventory",))
    return ReferenceLifecycleService(factory, registry)


def test_inventory_contact_dependency_blocks_reference_archive_without_mutation(
    initialized_database,
) -> None:
    factory = _factory(initialized_database)
    contact = ContactReferenceService(factory).create_contact(
        command_id=new_uuid4(),
        name="Inventory Pickup Contact",
    )
    fault_tag_id = _seed_fault_tag_pickup_dependency(
        factory,
        contact_id=contact.contact_id,
    )
    service = _lifecycle(factory)

    preview = service.preview(
        operation="archive",
        target_type="contact",
        target_id=contact.contact_id,
        base_revision=1,
        limit=10,
    )
    assert preview.exact_blocker_count == 1
    assert preview.would_be_eligible is False
    assert [(b.blocker_id, b.reason_code) for b in preview.blockers] == [
        (fault_tag_id, "active_fault_tag_pickup_contact")
    ]

    archive_command = new_uuid4()
    with pytest.raises(SomaError) as raised:
        service.archive_reference(
            command_id=archive_command,
            target_type="contact",
            target_id=contact.contact_id,
            base_revision=1,
            reason_category="operator_archive",
        )
    assert raised.value.code == "ARCHIVE_BLOCKED"

    connection = factory.open_authoritative(read_only=True, require_wal=True)
    try:
        assert connection.execute(
            "SELECT lifecycle_state,revision FROM contacts WHERE contact_id=?",
            (contact.contact_id,),
        ).fetchone() == ("active", 1)
        assert connection.execute(
            "SELECT 1 FROM command_receipts WHERE command_id=?",
            (archive_command,),
        ).fetchone() is None
        assert connection.execute(
            "SELECT 1 FROM reference_lifecycle_events "
            "WHERE target_id=? AND event_type='archived'",
            (contact.contact_id,),
        ).fetchone() is None
    finally:
        connection.close()


def test_inventory_dispatch_logistics_dependency_blocks_reference_archive(
    initialized_database,
) -> None:
    factory = _factory(initialized_database)
    dispatch = DispatchLocationService(factory).create_standalone(
        command_id=new_uuid4(),
        name="Pickup Origin",
        address_text="Warehouse Road",
    )
    fault_tag_id = _seed_fault_tag_pickup_dependency(
        factory,
        dispatch_location_id=dispatch.dispatch_location_id,
    )
    service = _lifecycle(factory)

    preview = service.preview(
        operation="archive",
        target_type="dispatch_location",
        target_id=dispatch.dispatch_location_id,
        base_revision=1,
        limit=10,
    )
    assert preview.exact_blocker_count == 1
    assert [(b.blocker_id, b.reason_code) for b in preview.blockers] == [
        (fault_tag_id, "active_fault_tag_pickup_origin")
    ]

    with pytest.raises(SomaError) as raised:
        service.archive_reference(
            command_id=new_uuid4(),
            target_type="dispatch_location",
            target_id=dispatch.dispatch_location_id,
            base_revision=1,
            reason_category="operator_archive",
        )
    assert raised.value.code == "ARCHIVE_BLOCKED"
