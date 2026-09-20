from __future__ import annotations

import pytest

from soma.foundation.errors import SomaError
from soma.foundation.identifiers import new_uuid4
from soma.foundation.persistence.uow import ReadSnapshot
from soma.inventory.domain.fault_tags import FaultTagMembershipIntent, WarehouseMembershipIntent
from soma.inventory.domain.rmas import RmaAuthorizationIntent
from soma.inventory.queries.previews import InventoryBulkPreviewQuery
from soma.inventory.services.consequences_logistics import InventoryConsequencesLogisticsService
from soma.inventory.services.corrections_bulk import InventoryCorrectionsBulkService
from soma.inventory.services.fault_tags import InventoryFaultTagsService
from test_inventory_consequence_replay import _factory, _reviewed_task
from test_inventory_requests_rma import _prepare_submitted_request


def _submitted_tag(factory):
    _, _, requests, request_id, revision = _prepare_submitted_request(
        factory, official_sr="97800001", request_quantity=2, target_count=2, bom="REPLAY-ASSEMBLY",
    )
    batch = requests.accept_rma_authorization_batch(
        command_id=new_uuid4(), spare_request_id=request_id, expected_request_revision=revision,
        rows=(RmaAuthorizationIntent("C0000000081", "REPLAY-ASSEMBLY"),
              RmaAuthorizationIntent("C0000000082", "REPLAY-ASSEMBLY")),
        accepted_at_utc=2100,
    )
    logistics = InventoryConsequencesLogisticsService(factory)
    rma_ids = []
    for item in batch["created_rmas"]:
        rma_id = item["rma_id"]
        rma_ids.append(rma_id)
        received = logistics.record_rma_inbound_receipt(
            command_id=new_uuid4(), rma_id=rma_id, actual_bom_code="REPLAY-ASSEMBLY", condition_token="new",
        )
        unit_id = next(ref.result_id for ref in received.target_refs if ref.result_type == "spare_part_unit")
        task_id, _, fingerprint = _reviewed_task(factory)
        logistics.accept_inventory_physical_consequence(
            command_id=new_uuid4(), task_id=task_id, task_review_fingerprint=fingerprint,
            physical_disposition="unused", rma_id=rma_id, inbound_spare_part_unit_id=unit_id,
        )
    tags = InventoryFaultTagsService(factory)
    tag = tags.create_fault_tag_draft(
        command_id=new_uuid4(), return_method="non_pickup",
        memberships=tuple(FaultTagMembershipIntent(identity, "unused return") for identity in rma_ids),
    )
    tag_id = tag["fault_tag_id"]
    with ReadSnapshot(factory) as snapshot:
        fingerprint = snapshot.connection.execute(
            "SELECT input_fingerprint FROM fault_tag_current_projection WHERE fault_tag_id=?", (tag_id,),
        ).fetchone()[0]
    submitted = tags.accept_fault_tag_submission(
        command_id=new_uuid4(), fault_tag_id=tag_id, expected_fingerprint=fingerprint,
    )
    return tags, submitted, rma_ids


def _members(tag):
    return tuple(WarehouseMembershipIntent(row["fault_tag_membership_id"], row["revision"]) for row in tag["members"])


def _current_members(factory, tag_id):
    with ReadSnapshot(factory) as snapshot:
        return _members(InventoryFaultTagsService._response(snapshot.connection, tag_id))


@pytest.mark.parametrize("bulk", [False, True], ids=["warehouse-commands", "reviewed-bulk"])
def test_warehouse_receipt_and_final_batches_replay_exactly_t050_t051(initialized_database, bulk):
    factory = _factory(initialized_database)
    tags, submitted, rmas = _submitted_tag(factory)
    tag_id = submitted["fault_tag_id"]
    service = InventoryCorrectionsBulkService(factory) if bulk else tags
    original_receipt = None
    for action in ("warehouse_receipt", "warehouse_accept"):
        members = _current_members(factory, tag_id)
        command = new_uuid4()
        if bulk:
            preview = InventoryBulkPreviewQuery(factory).preview(
                action_kind=action, targets=tuple((item.fault_tag_membership_id, item.revision) for item in members),
            )
            args = dict(command_id=command, preview_fingerprint=preview["input_fingerprint"],
                        action_kind=action, memberships=members,
                        explicit_confirmation=action == "warehouse_accept")
            call = service.accept_inventory_bulk_action
        elif action == "warehouse_receipt":
            args = dict(command_id=command, memberships=members)
            call = tags.record_warehouse_receipt
        else:
            args = dict(command_id=command, memberships=members, decision="accepted", explicit_confirmation=True)
            call = tags.record_warehouse_final_decision
        applied = call(**args)
        replay = call(**args)
        assert replay.replayed
        assert replay.target_refs == applied.target_refs
        assert replay.revisions == applied.revisions
        if action == "warehouse_receipt":
            original_receipt = (call, args, applied)
        with ReadSnapshot(factory) as snapshot:
            states = [snapshot.connection.execute(
                "SELECT obligation_state FROM rma_return_obligation_current WHERE rma_id=?", (identity,),
            ).fetchone()[0] for identity in rmas]
        assert states == (["open", "open"] if action == "warehouse_receipt" else ["closed_accepted", "closed_accepted"])
    # Replay the earlier receipt after the entire warehouse lifecycle advanced.
    call, args, applied = original_receipt
    replay = call(**args)
    assert replay.replayed and replay.target_refs == applied.target_refs
    assert replay.revisions == applied.revisions


def test_bulk_drift_aborts_complete_selected_scope_t058(initialized_database):
    factory = _factory(initialized_database)
    tags, submitted, _ = _submitted_tag(factory)
    members = _members(submitted)
    preview = InventoryBulkPreviewQuery(factory).preview(
        action_kind="warehouse_receipt", targets=tuple((x.fault_tag_membership_id, x.revision) for x in members),
    )
    tags.record_warehouse_receipt(command_id=new_uuid4(), memberships=members[:1])
    command = new_uuid4()
    with pytest.raises(SomaError) as stale:
        InventoryCorrectionsBulkService(factory).accept_inventory_bulk_action(
            command_id=command, preview_fingerprint=preview["input_fingerprint"],
            action_kind="warehouse_receipt", memberships=members,
        )
    assert stale.value.code == "INV_STALE"
    with ReadSnapshot(factory) as snapshot:
        current = InventoryFaultTagsService._response(snapshot.connection, submitted["fault_tag_id"])
        assert {x["state"] for x in current["members"]} == {"warehouse_received", "submitted_awaiting_receipt"}
        assert snapshot.connection.execute("SELECT COUNT(*) FROM command_receipts WHERE command_id=?", (command,)).fetchone()[0] == 0
        assert snapshot.connection.execute("SELECT COUNT(*) FROM audit_events WHERE command_id=?", (command,)).fetchone()[0] == 0


def test_warehouse_final_decision_requires_explicit_confirmation_t055(initialized_database):
    factory = _factory(initialized_database)
    tags, submitted, _ = _submitted_tag(factory)
    members = _members(submitted)
    tags.record_warehouse_receipt(command_id=new_uuid4(), memberships=members)
    command = new_uuid4()
    with pytest.raises(SomaError) as rejected:
        tags.record_warehouse_final_decision(
            command_id=command, memberships=_current_members(factory, submitted["fault_tag_id"]),
            decision="accepted", explicit_confirmation=False,
            evidence_kind="indexed_logistics", evidence_id="opaque-message-id",
        )
    assert rejected.value.code == "WAREHOUSE_FINAL_CONFIRMATION_REQUIRED"
    with ReadSnapshot(factory) as snapshot:
        assert snapshot.connection.execute("SELECT COUNT(*) FROM command_receipts WHERE command_id=?", (command,)).fetchone()[0] == 0
