from __future__ import annotations

import pytest

from soma.foundation.errors import SomaError
from soma.foundation.identifiers import new_uuid4
from soma.foundation.persistence.uow import ReadSnapshot
from soma.inventory.domain.fault_tags import FaultTagMembershipIntent
from soma.inventory.domain.rmas import RmaAuthorizationIntent
from soma.inventory.services.consequences_logistics import InventoryConsequencesLogisticsService
from soma.inventory.services.fault_tags import InventoryFaultTagsService
from test_inventory_consequence_replay import _reviewed_task
from test_inventory_requests_rma import _prepare_submitted_request


def _factory(initialized_database):
    database_path, builder = initialized_database
    return builder(database_path)


def _eligible_return_rma(factory) -> str:
    _sr, _need, requests, request_id, revision = _prepare_submitted_request(
        factory,
        official_sr="97800430",
        request_quantity=1,
        target_count=1,
        bom="FT43-READY",
    )
    batch = requests.accept_rma_authorization_batch(
        command_id=new_uuid4(),
        spare_request_id=request_id,
        expected_request_revision=revision,
        rows=(RmaAuthorizationIntent("C0000000430", "FT43-READY"),),
        accepted_at_utc=4_300,
    )
    rma_id = str(batch["created_rmas"][0]["rma_id"])
    logistics = InventoryConsequencesLogisticsService(factory)
    received = logistics.record_rma_inbound_receipt(
        command_id=new_uuid4(),
        rma_id=rma_id,
        actual_bom_code="FT43-READY",
        condition_token="new",
    )
    unit_id = next(
        ref.result_id
        for ref in received.target_refs
        if ref.result_type == "spare_part_unit"
    )
    task_id, _reviewed, fingerprint = _reviewed_task(factory)
    logistics.accept_inventory_physical_consequence(
        command_id=new_uuid4(),
        task_id=task_id,
        task_review_fingerprint=fingerprint,
        physical_disposition="unused",
        rma_id=rma_id,
        inbound_spare_part_unit_id=unit_id,
    )
    return rma_id


def test_t042_fault_tag_draft_allocates_immutable_handle_and_allows_zero_members(
    initialized_database,
) -> None:
    factory = _factory(initialized_database)
    service = InventoryFaultTagsService(factory)

    created = service.create_fault_tag_draft(
        command_id=new_uuid4(),
        return_method="pickup",
    )
    assert created["state"] == "draft"
    assert created["revision"] == 1
    assert created["members"] == []
    assert created["tracking_handle"] == "FT-00000001"

    updated = service.update_fault_tag_draft(
        command_id=new_uuid4(),
        fault_tag_id=str(created["fault_tag_id"]),
        base_revision=1,
        return_method="non_pickup",
        memberships=(),
    )
    assert updated["fault_tag_id"] == created["fault_tag_id"]
    assert updated["tracking_handle"] == created["tracking_handle"]
    assert updated["state"] == "draft"
    assert updated["revision"] == 2
    assert updated["members"] == []

    second = service.create_fault_tag_draft(
        command_id=new_uuid4(),
        return_method="non_pickup",
    )
    assert second["tracking_handle"] == "FT-00000002"

    with ReadSnapshot(factory) as snapshot:
        allocator = snapshot.connection.execute(
            "SELECT next_sequence FROM inventory_tracking_allocators "
            "WHERE allocator_kind='fault_tag'"
        ).fetchone()
        assert int(allocator[0]) == 3
        tags = snapshot.connection.execute(
            "SELECT tracking_id,draft_revision FROM fault_tags ORDER BY tracking_sequence"
        ).fetchall()
        assert [tuple(row) for row in tags] == [
            ("FT-00000001", 2),
            ("FT-00000002", 1),
        ]
        assert snapshot.connection.execute(
            "SELECT COUNT(*) FROM fault_tag_submission_snapshots"
        ).fetchone()[0] == 0
        assert snapshot.connection.execute(
            "SELECT COUNT(*) FROM fault_tag_membership_events"
        ).fetchone()[0] == 0


def test_t043_pickup_fault_tag_submission_requires_pickup_origin(
    initialized_database,
) -> None:
    factory = _factory(initialized_database)
    service = InventoryFaultTagsService(factory)
    rma_id = _eligible_return_rma(factory)
    created = service.create_fault_tag_draft(
        command_id=new_uuid4(),
        return_method="pickup",
        memberships=(FaultTagMembershipIntent(rma_id, "pickup return"),),
    )
    tag_id = str(created["fault_tag_id"])
    assert len(created["members"]) == 1
    with ReadSnapshot(factory) as snapshot:
        fingerprint = str(
            snapshot.connection.execute(
                "SELECT input_fingerprint FROM fault_tag_current_projection "
                "WHERE fault_tag_id=?",
                (tag_id,),
            ).fetchone()[0]
        )

    command_id = new_uuid4()
    with pytest.raises(SomaError) as excinfo:
        service.accept_fault_tag_submission(
            command_id=command_id,
            fault_tag_id=tag_id,
            expected_fingerprint=fingerprint,
        )
    assert excinfo.value.code == "FAULT_TAG_PICKUP_ORIGIN_REQUIRED"

    with ReadSnapshot(factory) as snapshot:
        state = snapshot.connection.execute(
            "SELECT state,revision,current_submission_snapshot_id "
            "FROM fault_tag_current_projection WHERE fault_tag_id=?",
            (tag_id,),
        ).fetchone()
        assert tuple(state) == ("draft", 1, None)
        assert snapshot.connection.execute(
            "SELECT COUNT(*) FROM command_receipts WHERE command_id=?",
            (command_id,),
        ).fetchone()[0] == 0
        assert snapshot.connection.execute(
            "SELECT COUNT(*) FROM fault_tag_submission_snapshots "
            "WHERE fault_tag_id=?",
            (tag_id,),
        ).fetchone()[0] == 0
