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
    original = _members(submitted)
    selected = original[0]
    sibling = original[1]

    receipt_command = new_uuid4()
    if bulk:
        preview = InventoryBulkPreviewQuery(factory).preview(
            action_kind="warehouse_receipt",
            targets=((selected.fault_tag_membership_id, selected.revision),),
        )
        receipt_args = dict(
            command_id=receipt_command,
            preview_fingerprint=preview["input_fingerprint"],
            action_kind="warehouse_receipt",
            memberships=(selected,),
            explicit_confirmation=False,
        )
        receipt_call = service.accept_inventory_bulk_action
    else:
        receipt_args = dict(command_id=receipt_command, memberships=(selected,))
        receipt_call = tags.record_warehouse_receipt

    receipt = receipt_call(**receipt_args)
    receipt_replay = receipt_call(**receipt_args)
    assert receipt_replay.replayed
    assert receipt_replay.target_refs == receipt.target_refs
    assert receipt_replay.revisions == receipt.revisions

    after_receipt = _current_members(factory, tag_id)
    by_id = {item.fault_tag_membership_id: item for item in after_receipt}
    assert _membership_state(factory, selected.fault_tag_membership_id)[0] == "warehouse_received"
    assert _membership_state(factory, sibling.fault_tag_membership_id)[0] == "submitted_awaiting_receipt"
    sibling_after_receipt = _membership_state(factory, sibling.fault_tag_membership_id)
    assert [_obligation_state(factory, rma_id)[0] for rma_id in rmas] == ["open", "open"]

    accepted_target = by_id[selected.fault_tag_membership_id]
    final_command = new_uuid4()
    if bulk:
        preview = InventoryBulkPreviewQuery(factory).preview(
            action_kind="warehouse_accept",
            targets=((accepted_target.fault_tag_membership_id, accepted_target.revision),),
        )
        final_args = dict(
            command_id=final_command,
            preview_fingerprint=preview["input_fingerprint"],
            action_kind="warehouse_accept",
            memberships=(accepted_target,),
            explicit_confirmation=True,
        )
        final_call = service.accept_inventory_bulk_action
    else:
        final_args = dict(
            command_id=final_command,
            memberships=(accepted_target,),
            decision="accepted",
            explicit_confirmation=True,
        )
        final_call = tags.record_warehouse_final_decision

    final = final_call(**final_args)
    final_replay = final_call(**final_args)
    assert final_replay.replayed
    assert final_replay.target_refs == final.target_refs
    assert final_replay.revisions == final.revisions

    selected_rma = _membership_rma(factory, selected.fault_tag_membership_id)
    sibling_rma = _membership_rma(factory, sibling.fault_tag_membership_id)
    assert {selected_rma, sibling_rma} == set(rmas)
    assert _obligation_state(factory, selected_rma)[0] == "closed_accepted"
    assert _obligation_state(factory, sibling_rma)[0] == "open"
    assert _membership_state(factory, sibling.fault_tag_membership_id) == sibling_after_receipt

    # Exact replay remains stable even after the selected member advanced further.
    late_receipt_replay = receipt_call(**receipt_args)
    assert late_receipt_replay.replayed
    assert late_receipt_replay.target_refs == receipt.target_refs
    assert late_receipt_replay.revisions == receipt.revisions

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
    tags, submitted, rmas = _submitted_tag(factory)
    members = _members(submitted)
    tags.record_warehouse_receipt(command_id=new_uuid4(), memberships=members)
    current = _current_members(factory, submitted["fault_tag_id"])
    with ReadSnapshot(factory) as snapshot:
        membership_before = tuple(
            tuple(row)
            for row in snapshot.connection.execute(
                "SELECT * FROM fault_tag_membership_current WHERE fault_tag_id=? "
                "ORDER BY fault_tag_membership_id",
                (submitted["fault_tag_id"],),
            ).fetchall()
        )
        obligations_before = tuple(
            tuple(row)
            for row in snapshot.connection.execute(
                "SELECT * FROM rma_return_obligation_current WHERE rma_id IN (?,?) "
                "ORDER BY rma_id",
                tuple(rmas),
            ).fetchall()
        )
        projection_before = tuple(
            snapshot.connection.execute(
                "SELECT * FROM fault_tag_current_projection WHERE fault_tag_id=?",
                (submitted["fault_tag_id"],),
            ).fetchone()
        )

    command = new_uuid4()
    with pytest.raises(SomaError) as rejected:
        tags.record_warehouse_final_decision(
            command_id=command,
            memberships=current,
            decision="accepted",
            explicit_confirmation=False,
            evidence_kind="indexed_logistics",
            evidence_id="opaque-message-id",
        )
    assert rejected.value.code == "WAREHOUSE_FINAL_CONFIRMATION_REQUIRED"
    with ReadSnapshot(factory) as snapshot:
        assert snapshot.connection.execute(
            "SELECT COUNT(*) FROM command_receipts WHERE command_id=?", (command,),
        ).fetchone()[0] == 0
        assert tuple(
            tuple(row)
            for row in snapshot.connection.execute(
                "SELECT * FROM fault_tag_membership_current WHERE fault_tag_id=? "
                "ORDER BY fault_tag_membership_id",
                (submitted["fault_tag_id"],),
            ).fetchall()
        ) == membership_before
        assert tuple(
            tuple(row)
            for row in snapshot.connection.execute(
                "SELECT * FROM rma_return_obligation_current WHERE rma_id IN (?,?) "
                "ORDER BY rma_id",
                tuple(rmas),
            ).fetchall()
        ) == obligations_before
        assert tuple(
            snapshot.connection.execute(
                "SELECT * FROM fault_tag_current_projection WHERE fault_tag_id=?",
                (submitted["fault_tag_id"],),
            ).fetchone()
        ) == projection_before

def _membership_state(factory, membership_id):
    with ReadSnapshot(factory) as snapshot:
        return tuple(
            snapshot.connection.execute(
                "SELECT state,active_submitted,revision,input_fingerprint,last_event_id,last_command_id "
                "FROM fault_tag_membership_current WHERE fault_tag_membership_id=?",
                (membership_id,),
            ).fetchone()
        )


def _membership_event(factory, event_id):
    with ReadSnapshot(factory) as snapshot:
        return tuple(
            snapshot.connection.execute(
                "SELECT event_kind,target_event_id,reason_code,evidence_kind,evidence_id,command_id "
                "FROM fault_tag_membership_events WHERE membership_event_id=?",
                (event_id,),
            ).fetchone()
        )


def _rma_state(factory, rma_id):
    with ReadSnapshot(factory) as snapshot:
        return tuple(
            snapshot.connection.execute(
                "SELECT state,return_obligation_open,active_fault_tag_membership_id,"
                "revision,input_fingerprint,last_command_id "
                "FROM rma_lifecycle_projection WHERE rma_id=?",
                (rma_id,),
            ).fetchone()
        )


def _membership_rma(factory, membership_id):
    with ReadSnapshot(factory) as snapshot:
        return str(
            snapshot.connection.execute(
                "SELECT rma_id FROM fault_tag_memberships WHERE fault_tag_membership_id=?",
                (membership_id,),
            ).fetchone()[0]
        )


def _obligation_state(factory, rma_id):
    with ReadSnapshot(factory) as snapshot:
        return tuple(
            snapshot.connection.execute(
                "SELECT obligation_state,revision,last_event_id,last_command_id "
                "FROM rma_return_obligation_current WHERE rma_id=?",
                (rma_id,),
            ).fetchone()
        )


def test_manual_warehouse_transition_needs_no_uploaded_evidence_t056(initialized_database):
    factory = _factory(initialized_database)
    tags, submitted, rmas = _submitted_tag(factory)
    first = _members(submitted)[0]

    receipt = tags.record_warehouse_receipt(
        command_id=new_uuid4(),
        memberships=(first,),
    )
    receipt_event_id = next(
        ref.result_id
        for ref in receipt.target_refs
        if ref.result_type == "fault_tag_membership_event"
    )
    receipt_event = _membership_event(factory, receipt_event_id)
    assert receipt_event[0] == "warehouse_received"
    assert receipt_event[3] is None
    assert receipt_event[4] is None

    current = _current_members(factory, submitted["fault_tag_id"])
    current_first = next(
        item for item in current
        if item.fault_tag_membership_id == first.fault_tag_membership_id
    )
    final = tags.record_warehouse_final_decision(
        command_id=new_uuid4(),
        memberships=(current_first,),
        decision="accepted",
        explicit_confirmation=True,
    )
    final_event_id = next(
        ref.result_id
        for ref in final.target_refs
        if ref.result_type == "fault_tag_membership_event"
    )
    final_event = _membership_event(factory, final_event_id)
    assert final_event[0] == "warehouse_accepted"
    assert final_event[3] is None
    assert final_event[4] is None
    first_rma = _membership_rma(factory, first.fault_tag_membership_id)
    assert _obligation_state(factory, first_rma)[0] == "closed_accepted"


def test_bulk_receipt_preflight_partitions_incompatible_target_t057(initialized_database):
    factory = _factory(initialized_database)
    tags, submitted, _ = _submitted_tag(factory)
    original = _members(submitted)

    tags.record_warehouse_receipt(
        command_id=new_uuid4(),
        memberships=(original[0],),
    )
    current = _current_members(factory, submitted["fault_tag_id"])
    preview = InventoryBulkPreviewQuery(factory).preview(
        action_kind="warehouse_receipt",
        targets=tuple(
            (item.fault_tag_membership_id, item.revision)
            for item in current
        ),
    )

    assert preview["compatible"] is False
    assert len(preview["targets"]) == 2
    statuses = {
        item["fault_tag_membership_id"]: (item["status"], item["blocker"])
        for item in preview["targets"]
    }
    assert statuses[original[0].fault_tag_membership_id] == (
        "incompatible",
        "BULK_INCOMPATIBLE",
    )
    assert statuses[original[1].fault_tag_membership_id] == ("eligible", None)
    assert preview["blockers"] == [
        {
            "fault_tag_membership_id": original[0].fault_tag_membership_id,
            "status": "incompatible",
            "code": "BULK_INCOMPATIBLE",
        }
    ]


def test_later_false_receipt_correction_isolated_from_successful_bulk_t059(
    initialized_database,
):
    factory = _factory(initialized_database)
    _tags, submitted, rmas = _submitted_tag(factory)
    members = _members(submitted)
    preview = InventoryBulkPreviewQuery(factory).preview(
        action_kind="warehouse_receipt",
        targets=tuple(
            (item.fault_tag_membership_id, item.revision)
            for item in members
        ),
    )
    bulk_command = new_uuid4()
    bulk = InventoryCorrectionsBulkService(factory).accept_inventory_bulk_action(
        command_id=bulk_command,
        preview_fingerprint=preview["input_fingerprint"],
        action_kind="warehouse_receipt",
        memberships=members,
    )
    batch_id = next(
        ref.result_id
        for ref in bulk.target_refs
        if ref.result_type == "inventory_batch"
    )

    current = _current_members(factory, submitted["fault_tag_id"])
    corrected = current[0]
    sibling = current[1]
    corrected_before = _membership_state(
        factory, corrected.fault_tag_membership_id
    )
    sibling_before = _membership_state(factory, sibling.fault_tag_membership_id)
    corrected_rma = _membership_rma(factory, corrected.fault_tag_membership_id)
    sibling_rma = _membership_rma(factory, sibling.fault_tag_membership_id)
    sibling_rma_before = _rma_state(factory, sibling_rma)
    corrected_obligation_before = _obligation_state(factory, corrected_rma)
    target_event_id = str(corrected_before[4])
    sibling_event_id = str(sibling_before[4])
    sibling_event_before = _membership_event(factory, sibling_event_id)
    original_receipt_before = _membership_event(factory, target_event_id)

    with ReadSnapshot(factory) as snapshot:
        batch_before = tuple(
            snapshot.connection.execute(
                "SELECT inventory_batch_id,batch_kind,target_count,recorded_at_utc,command_id "
                "FROM inventory_lifecycle_batches WHERE inventory_batch_id=?",
                (batch_id,),
            ).fetchone()
        )

    correction_command = new_uuid4()
    service = InventoryCorrectionsBulkService(factory)
    corrected_result = service.correct_inventory_evidence(
        command_id=correction_command,
        correction_kind="false_warehouse_receipt",
        target_id=corrected.fault_tag_membership_id,
        target_event_id=target_event_id,
        expected_revision=corrected.revision,
        reason_code="false receipt",
    )
    replay = service.correct_inventory_evidence(
        command_id=correction_command,
        correction_kind="false_warehouse_receipt",
        target_id=corrected.fault_tag_membership_id,
        target_event_id=target_event_id,
        expected_revision=corrected.revision,
        reason_code="false receipt",
    )
    assert replay.replayed
    assert replay.target_refs == corrected_result.target_refs
    assert replay.revisions == corrected_result.revisions

    corrected_after = _membership_state(
        factory, corrected.fault_tag_membership_id
    )
    sibling_after = _membership_state(factory, sibling.fault_tag_membership_id)
    assert corrected_after[0] == "submitted_awaiting_receipt"
    assert corrected_after[1] == 1
    assert corrected_after[2] == corrected.revision + 1
    assert corrected_after[4] != target_event_id
    assert sibling_after == sibling_before
    assert _membership_event(factory, sibling_event_id) == sibling_event_before
    assert _membership_event(factory, target_event_id) == original_receipt_before

    correction_event = _membership_event(factory, str(corrected_after[4]))
    assert correction_event[0] == "correct"
    assert correction_event[1] == target_event_id
    assert correction_event[2] == "false receipt"
    assert correction_event[3] is None
    assert correction_event[4] is None
    assert correction_event[5] == correction_command

    corrected_rma_after = _rma_state(factory, corrected_rma)
    assert corrected_rma_after[0] == "fault_tagged"
    assert corrected_rma_after[1] == 1
    assert corrected_rma_after[2] == corrected.fault_tag_membership_id
    assert _obligation_state(factory, corrected_rma) == corrected_obligation_before
    assert _rma_state(factory, sibling_rma) == sibling_rma_before

    with ReadSnapshot(factory) as snapshot:
        batch_after = tuple(
            snapshot.connection.execute(
                "SELECT inventory_batch_id,batch_kind,target_count,recorded_at_utc,command_id "
                "FROM inventory_lifecycle_batches WHERE inventory_batch_id=?",
                (batch_id,),
            ).fetchone()
        )
        aggregate = tuple(
            snapshot.connection.execute(
                "SELECT state,awaiting_receipt_count,awaiting_final_count,"
                "accepted_count,rejected_count "
                "FROM fault_tag_current_projection WHERE fault_tag_id=?",
                (submitted["fault_tag_id"],),
            ).fetchone()
        )
        assert snapshot.connection.execute(
            "SELECT COUNT(*) FROM fault_tag_membership_events "
            "WHERE fault_tag_membership_id=? AND event_kind='warehouse_received'",
            (corrected.fault_tag_membership_id,),
        ).fetchone()[0] == 1

    assert batch_after == batch_before
    assert aggregate == ("in_warehouse_review", 1, 1, 0, 0)

