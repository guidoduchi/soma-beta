from __future__ import annotations

from soma.foundation.identifiers import new_uuid4
from soma.foundation.persistence.uow import ReadSnapshot
from soma.inventory.domain.rmas import RmaAuthorizationIntent
from soma.inventory.queries.requests_rma import InventoryRequestsRmaQueryService
from test_inventory_requests_rma import _factory, _prepare_submitted_request


def test_t031_authorized_rma_has_no_provisional_physical_unit_before_receipt(
    initialized_database,
) -> None:
    factory = _factory(initialized_database)
    _sr, _need, requests, request_id, request_revision = _prepare_submitted_request(
        factory,
        official_sr="97100131",
        request_quantity=1,
        target_count=1,
        bom="PRE-RECEIPT-131",
    )
    batch = requests.accept_rma_authorization_batch(
        command_id=new_uuid4(),
        spare_request_id=request_id,
        expected_request_revision=request_revision,
        rows=(RmaAuthorizationIntent("C0000000131", "PRE-RECEIPT-131"),),
        accepted_at_utc=4_131,
    )
    rma_id = str(batch["created_rmas"][0]["rma_id"])

    detail = InventoryRequestsRmaQueryService(factory).rma_detail(rma_id)
    assert detail["rma_id"] == rma_id
    assert detail["direct_inbound_spare_part_unit_id"] is None
    assert detail["state"] != "received"
    assert detail["actual_logistics"] == []
    assert detail["return_obligation"]["state"] == "not_established"
    assert detail["return_obligation"]["spare_part_unit_id"] is None

    with ReadSnapshot(factory) as snapshot:
        assert snapshot.connection.execute(
            "SELECT COUNT(*) FROM spare_part_units WHERE origin_rma_id=?",
            (rma_id,),
        ).fetchone()[0] == 0
        assert snapshot.connection.execute(
            "SELECT COUNT(*) FROM rma_direct_inbound_units WHERE rma_id=?",
            (rma_id,),
        ).fetchone()[0] == 0
        assert snapshot.connection.execute(
            "SELECT COUNT(*) FROM logistics_rma_participants WHERE rma_id=?",
            (rma_id,),
        ).fetchone()[0] == 0
