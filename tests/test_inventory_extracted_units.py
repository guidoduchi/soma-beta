from __future__ import annotations

from soma.foundation.identifiers import new_uuid4
from soma.foundation.persistence.uow import ReadSnapshot
from soma.inventory.domain.rmas import RmaAuthorizationIntent
from soma.inventory.services.consequences_logistics import InventoryConsequencesLogisticsService
from soma.inventory.services.needs_stock import InventoryNeedsStockService
from test_inventory_consequence_replay import _reviewed_task
from test_inventory_requests_rma import _factory, _prepare_submitted_request


def test_t033_extracted_units_keep_parent_as_only_direct_inbound_and_logistics_unit(
    initialized_database,
) -> None:
    factory = _factory(initialized_database)
    _sr, _need, requests, request_id, request_revision = _prepare_submitted_request(
        factory,
        official_sr="97100333",
        request_quantity=1,
        target_count=1,
        bom="ASSEMBLY-033",
    )
    batch = requests.accept_rma_authorization_batch(
        command_id=new_uuid4(),
        spare_request_id=request_id,
        expected_request_revision=request_revision,
        rows=(RmaAuthorizationIntent("C0000000333", "ASSEMBLY-033"),),
        accepted_at_utc=3_330,
    )
    rma_id = str(batch["created_rmas"][0]["rma_id"])
    logistics = InventoryConsequencesLogisticsService(factory)
    receipt = logistics.record_rma_inbound_receipt(
        command_id=new_uuid4(),
        rma_id=rma_id,
        actual_bom_code="ASSEMBLY-033",
        manufacturer_serial="PARENT-033",
        condition_token="used",
        effective_at_utc=3_331,
    )
    parent_id = next(
        ref.result_id
        for ref in receipt.target_refs
        if ref.result_type == "spare_part_unit"
    )

    task_id, _reviewed, fingerprint = _reviewed_task(factory)
    logistics.accept_inventory_physical_consequence(
        command_id=new_uuid4(),
        task_id=task_id,
        task_review_fingerprint=fingerprint,
        physical_disposition="dismantled",
        rma_id=rma_id,
        parent_dismantled_unit_id=parent_id,
        effective_at_utc=3_332,
    )

    stock = InventoryNeedsStockService(factory)
    children = []
    for index in range(2):
        created = stock.register_spare_part_unit(
            command_id=new_uuid4(),
            origin="extracted",
            bom_code=f"ASSEMBLY-033-CHILD-{index}",
            manufacturer_serial=f"CHILD-033-{index}",
            condition_token="used",
            origin_rma_id=rma_id,
            parent_spare_part_unit_id=parent_id,
            effective_at_utc=3_333 + index,
        )
        children.append(
            next(
                ref.result_id
                for ref in created.target_refs
                if ref.result_type == "spare_part_unit"
            )
        )

    with ReadSnapshot(factory) as snapshot:
        parent = snapshot.connection.execute(
            "SELECT local_tracking_id,creation_origin,origin_rma_id,parent_spare_part_unit_id "
            "FROM spare_part_units WHERE spare_part_unit_id=?",
            (parent_id,),
        ).fetchone()
        child_rows = snapshot.connection.execute(
            "SELECT spare_part_unit_id,local_tracking_id,creation_origin,origin_rma_id,"
            "parent_spare_part_unit_id FROM spare_part_units "
            "WHERE parent_spare_part_unit_id=? ORDER BY local_tracking_sequence",
            (parent_id,),
        ).fetchall()
        direct = snapshot.connection.execute(
            "SELECT spare_part_unit_id FROM rma_direct_inbound_units WHERE rma_id=?",
            (rma_id,),
        ).fetchall()
        parent_logistics = snapshot.connection.execute(
            "SELECT COUNT(*) FROM logistics_spare_unit_participants "
            "WHERE spare_part_unit_id=?",
            (parent_id,),
        ).fetchone()[0]
        child_logistics = snapshot.connection.execute(
            "SELECT COUNT(*) FROM logistics_spare_unit_participants "
            "WHERE spare_part_unit_id IN (?,?)",
            tuple(children),
        ).fetchone()[0]

    assert tuple(parent) == (None, "direct_rma_receipt", rma_id, None)
    assert [str(row[0]) for row in child_rows] == children
    assert [str(row[1]) for row in child_rows] == ["LSU-00000001", "LSU-00000002"]
    assert all(str(row[2]) == "extracted" for row in child_rows)
    assert all(str(row[3]) == rma_id for row in child_rows)
    assert all(str(row[4]) == parent_id for row in child_rows)
    assert [str(row[0]) for row in direct] == [parent_id]
    assert parent_logistics >= 1
    assert child_logistics == 0
