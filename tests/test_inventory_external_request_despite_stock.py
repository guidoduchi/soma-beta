from __future__ import annotations

from soma.foundation.identifiers import new_uuid4
from soma.foundation.persistence.uow import ReadSnapshot
from soma.inventory.domain.requests import SpareRequestAllocationIntent
from soma.inventory.queries.stock_needs import InventoryNeedsQueryService
from soma.inventory.services.needs_stock import InventoryNeedsStockService
from soma.inventory.services.requests_rma import InventoryRequestsRmaService
from soma.reference.application.contact_service import ContactReferenceService
from test_inventory_requests_rma import _dispatch_location, _factory, _sr


def _unit_projection(factory, unit_id: str):
    with ReadSnapshot(factory) as snapshot:
        return tuple(
            snapshot.connection.execute(
                "SELECT condition_token,disposition_token,location_kind,location_ref_id,"
                "custody_text,active_task_allocation_id,revision,last_command_id "
                "FROM spare_part_current_projection WHERE spare_part_unit_id=?",
                (unit_id,),
            ).fetchone()
        )


def test_t008_external_request_remains_allowed_despite_compatible_stock(
    initialized_database,
) -> None:
    factory = _factory(initialized_database)
    sr = _sr(factory, "97100008")
    inventory = InventoryNeedsStockService(factory)

    need = inventory.create_spare_need_draft(
        command_id=new_uuid4(),
        service_request_id=sr.service_request_id,
        bom_code="EXT-REQ-008",
        planned_quantity=1,
    )
    need_id = next(
        ref.result_id
        for ref in need.target_refs
        if ref.result_type == "spare_need"
    )

    registered = inventory.register_spare_part_unit(
        command_id=new_uuid4(),
        origin="manual_local",
        bom_code="EXT-REQ-008",
        manufacturer_serial="LOCAL-STOCK-008",
        condition_token="new",
    )
    unit_id = next(
        ref.result_id
        for ref in registered.target_refs
        if ref.result_type == "spare_part_unit"
    )

    stock = InventoryNeedsQueryService(factory).stock_eligibility(
        spare_need_id=need_id,
    )
    candidate = next(item for item in stock.items if item.spare_part_unit_id == unit_id)
    assert candidate.compatibility_classification == "exact"
    assert candidate.availability_blockers == ()
    assert candidate.eligible is True
    before_unit = _unit_projection(factory, unit_id)

    contact = ContactReferenceService(factory).create_contact(
        command_id=new_uuid4(),
        name="External Request 008",
    )
    location_id = _dispatch_location(factory, "T008")
    request = InventoryRequestsRmaService(factory).create_spare_request_draft(
        command_id=new_uuid4(),
        service_request_id=sr.service_request_id,
        requester_contact_id=contact.contact_id,
        allocations=(SpareRequestAllocationIntent(need_id, 1),),
        mode="delivery",
        receiver_contact_id=contact.contact_id,
        dispatch_location_id=location_id,
    )
    request_id = str(request["spare_request_id"])
    assert request["state"] == "draft"

    after_unit = _unit_projection(factory, unit_id)
    assert after_unit == before_unit

    stock_after = InventoryNeedsQueryService(factory).stock_eligibility(
        spare_need_id=need_id,
    )
    after_candidate = next(
        item for item in stock_after.items if item.spare_part_unit_id == unit_id
    )
    assert after_candidate.compatibility_classification == "exact"
    assert after_candidate.availability_blockers == ()
    assert after_candidate.eligible is True

    with ReadSnapshot(factory) as snapshot:
        assert snapshot.connection.execute(
            "SELECT COUNT(*) FROM spare_request_need_allocations "
            "WHERE spare_request_id=? AND spare_need_id=? AND active_draft=1",
            (request_id, need_id),
        ).fetchone()[0] == 1
        assert snapshot.connection.execute(
            "SELECT COUNT(*) FROM task_unit_allocation_events "
            "WHERE spare_part_unit_id=?",
            (unit_id,),
        ).fetchone()[0] == 0
        assert snapshot.connection.execute(
            "SELECT COUNT(*) FROM task_unit_allocation_current "
            "WHERE spare_part_unit_id=?",
            (unit_id,),
        ).fetchone()[0] == 0
        assert snapshot.connection.execute(
            "SELECT COUNT(*) FROM local_need_fulfillment_events "
            "WHERE spare_part_unit_id=?",
            (unit_id,),
        ).fetchone()[0] == 0
