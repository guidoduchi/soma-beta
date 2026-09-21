from __future__ import annotations

import json

from soma.foundation.identifiers import new_uuid4
from soma.foundation.persistence.uow import ReadSnapshot, UnitOfWork
from soma.inventory.domain.requests import SpareRequestAllocationIntent
from soma.inventory.services.corrections_bulk import InventoryCorrectionsBulkService
from soma.inventory.services.requests_rma import InventoryRequestsRmaService
from soma.reference.application.contact_service import ContactReferenceService
from test_inventory_requests_rma import (
    _dispatch_location,
    _factory,
    _need,
    _request_projection,
    _sr,
)


def test_t018_indexed_sent_proposal_acceptance_uses_normal_submission_authority(
    initialized_database,
) -> None:
    factory = _factory(initialized_database)
    sr = _sr(factory, "97100118")
    need = _need(
        factory,
        sr_id=sr.service_request_id,
        device_name="REQ-PROPOSAL-118",
        bom="REQ-PROPOSAL-118",
    )
    contact = ContactReferenceService(factory).create_contact(
        command_id=new_uuid4(),
        name="Proposal Submission Contact",
    )
    location_id = _dispatch_location(factory, "T018")
    requests = InventoryRequestsRmaService(factory)
    created = requests.create_spare_request_draft(
        command_id=new_uuid4(),
        service_request_id=sr.service_request_id,
        requester_contact_id=contact.contact_id,
        allocations=(SpareRequestAllocationIntent(need, 2),),
        mode="delivery",
        receiver_contact_id=contact.contact_id,
        dispatch_location_id=location_id,
    )
    request_id = str(created["spare_request_id"])
    projection = _request_projection(factory, request_id)
    assert tuple(projection[:5]) == ("draft", None, 0, None, 1)
    draft_fingerprint = str(projection[5])

    proposal_id = new_uuid4()
    proposal_target_id = new_uuid4()
    proposal_fingerprint = "b" * 64
    evidence_id = "indexed-sent-t018"
    payload_json = json.dumps(
        {
            "schema": "INVENTORY_PROPOSAL_TARGET_V1",
            "expected_draft_fingerprint": draft_fingerprint,
            "effective_submission_at_utc": 4_118,
        },
        sort_keys=True,
        separators=(",", ":"),
    )
    with UnitOfWork(factory) as uow:
        uow.connection.execute(
            "INSERT INTO inventory_proposals("
            "inventory_proposal_id,proposal_kind,evidence_kind,evidence_id,"
            "source_proposal_key,state,input_fingerprint,risk_tier,created_at_utc,"
            "revision,last_command_id"
            ") VALUES (?,?,?,?,?,'pending',?,'normal',1,1,NULL)",
            (
                proposal_id,
                "spare_request_submission",
                "indexed_sent",
                evidence_id,
                "t018-indexed-send",
                proposal_fingerprint,
            ),
        )
        uow.connection.execute(
            "INSERT INTO inventory_proposal_targets("
            "inventory_proposal_target_id,inventory_proposal_id,target_kind,"
            "spare_request_id,rma_id,spare_part_unit_id,fault_tag_id,"
            "fault_tag_membership_id,expected_revision,proposed_action,payload_json"
            ") VALUES (?,?,'spare_request',?,NULL,NULL,NULL,NULL,1,?,?)",
            (
                proposal_target_id,
                proposal_id,
                request_id,
                "spare_request_submission",
                payload_json,
            ),
        )

    with ReadSnapshot(factory) as snapshot:
        assert snapshot.connection.execute(
            "SELECT COUNT(*) FROM spare_request_submission_snapshots "
            "WHERE spare_request_id=?",
            (request_id,),
        ).fetchone()[0] == 0
        assert tuple(
            snapshot.connection.execute(
                "SELECT state,revision FROM inventory_proposals "
                "WHERE inventory_proposal_id=?",
                (proposal_id,),
            ).fetchone()
        ) == ("pending", 1)

    command_id = new_uuid4()
    service = InventoryCorrectionsBulkService(factory)
    accepted = service.accept_inventory_proposal(
        command_id=command_id,
        proposal_id=proposal_id,
        expected_revision=1,
        input_fingerprint=proposal_fingerprint,
    )
    assert accepted.outcome == "APPLIED"
    assert accepted.replayed is False
    assert {
        (ref.result_type, ref.result_id)
        for ref in accepted.target_refs
    } == {
        ("inventory_proposal", proposal_id),
        ("spare_request", request_id),
    }
    assert accepted.revisions == {
        proposal_id: 2,
        f"spare_request:{request_id}": 2,
    }

    replay = service.accept_inventory_proposal(
        command_id=command_id,
        proposal_id=proposal_id,
        expected_revision=1,
        input_fingerprint=proposal_fingerprint,
    )
    assert replay.replayed is True
    assert replay.target_refs == accepted.target_refs
    assert replay.revisions == accepted.revisions

    with ReadSnapshot(factory) as snapshot:
        request_projection = snapshot.connection.execute(
            "SELECT lifecycle_state,current_submission_snapshot_id,"
            "submitted_quantity,response_warning_start_utc,revision "
            "FROM spare_request_current_projection WHERE spare_request_id=?",
            (request_id,),
        ).fetchone()
        assert str(request_projection[0]) == "submitted_awaiting_response"
        assert request_projection[1] is not None
        assert tuple(request_projection[2:]) == (2, 4_118, 2)
        snapshot_id = str(request_projection[1])

        submission = snapshot.connection.execute(
            "SELECT submission_event_id,effective_submission_at_utc "
            "FROM spare_request_submission_snapshots "
            "WHERE submission_snapshot_id=?",
            (snapshot_id,),
        ).fetchone()
        assert int(submission[1]) == 4_118
        event_id = str(submission[0])
        event = snapshot.connection.execute(
            "SELECT event_kind,evidence_kind,evidence_id "
            "FROM spare_request_lifecycle_events WHERE request_event_id=?",
            (event_id,),
        ).fetchone()
        assert tuple(event) == (
            "submission_accepted",
            "indexed_sent",
            evidence_id,
        )

        allocation = snapshot.connection.execute(
            "SELECT spare_need_id,quantity,requested_bom_code "
            "FROM spare_request_submission_allocations "
            "WHERE submission_snapshot_id=?",
            (snapshot_id,),
        ).fetchone()
        assert (str(allocation[0]), int(allocation[1]), str(allocation[2])) == (
            need,
            2,
            "REQ-PROPOSAL-118",
        )

        assert tuple(
            snapshot.connection.execute(
                "SELECT state,revision,last_command_id FROM inventory_proposals "
                "WHERE inventory_proposal_id=?",
                (proposal_id,),
            ).fetchone()
        ) == ("accepted", 2, command_id)
        assert [
            str(row[0])
            for row in snapshot.connection.execute(
                "SELECT action_type FROM audit_events "
                "WHERE command_id=? ORDER BY action_type",
                (command_id,),
            ).fetchall()
        ] == [
            "inventory.proposal.decided",
            "inventory.spare_request.submitted",
        ]
        assert snapshot.connection.execute(
            "SELECT COUNT(*) FROM command_receipts WHERE command_id=? "
            "AND command_type='AcceptInventoryProposal'",
            (command_id,),
        ).fetchone()[0] == 1
        assert snapshot.connection.execute(
            "SELECT COUNT(*) FROM command_receipts "
            "WHERE command_type='AcceptSpareRequestSubmission' "
            "AND committed_at_utc=(SELECT committed_at_utc FROM command_receipts "
            "WHERE command_id=?)",
            (command_id,),
        ).fetchone()[0] == 0
        assert snapshot.connection.execute(
            "SELECT COUNT(*) FROM spare_request_submission_snapshots "
            "WHERE spare_request_id=?",
            (request_id,),
        ).fetchone()[0] == 1
