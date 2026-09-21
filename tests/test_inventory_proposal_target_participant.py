from __future__ import annotations

from soma.foundation.identifiers import new_uuid4
from soma.foundation.persistence.uow import ReadSnapshot, UnitOfWork
from soma.inventory.domain.requests import SpareRequestAllocationIntent
from soma.inventory.repositories.requests import InventoryRequestsRepository
from soma.inventory.services.participants import InventoryProposalTargetService
from soma.inventory.services.requests_rma import InventoryRequestsRmaService
from soma.reference.application.contact_service import ContactReferenceService
from test_inventory_requests_rma import _dispatch_location, _factory, _need, _sr


def _draft(factory) -> tuple[str, str]:
    sr = _sr(factory, "97100122")
    need_id = _need(
        factory,
        sr_id=sr.service_request_id,
        device_name="PROPOSAL-PARTICIPANT",
        bom="PROPOSAL-PARTICIPANT",
    )
    contact = ContactReferenceService(factory).create_contact(
        command_id=new_uuid4(),
        name="Proposal Participant Contact",
    )
    created = InventoryRequestsRmaService(factory).create_spare_request_draft(
        command_id=new_uuid4(),
        service_request_id=sr.service_request_id,
        requester_contact_id=contact.contact_id,
        allocations=(SpareRequestAllocationIntent(need_id, 1),),
        mode="delivery",
        receiver_contact_id=contact.contact_id,
        dispatch_location_id=_dispatch_location(factory, "PARTICIPANT"),
    )
    request_id = str(created["spare_request_id"])
    with ReadSnapshot(factory) as snapshot:
        row = InventoryRequestsRepository.current_detail(snapshot.connection, request_id)
        assert row is not None
        return request_id, str(row[9])


def _proposal(request_id: str, fingerprint: str) -> tuple[dict[str, object], dict[str, object]]:
    target = {
        "proposal_target_id": new_uuid4(),
        "target_kind": "spare_request",
        "target_id": request_id,
        "expected_revision": 1,
        "proposed_action": "spare_request_submission",
        "payload": {
            "schema": "INVENTORY_PROPOSAL_TARGET_V1",
            "expected_draft_fingerprint": fingerprint,
            "effective_submission_at_utc": 9_122,
        },
    }
    evidence = {
        "evidence_kind": "indexed_sent",
        "evidence_id": "participant-indexed-send",
        "risk_tier": "normal",
    }
    return target, evidence


def test_proposal_participant_applies_in_callers_uow_without_nested_receipt(
    initialized_database,
) -> None:
    factory = _factory(initialized_database)
    request_id, draft_fingerprint = _draft(factory)
    target, evidence = _proposal(request_id, draft_fingerprint)

    with ReadSnapshot(factory) as snapshot:
        before_receipts = int(
            snapshot.connection.execute("SELECT COUNT(*) FROM command_receipts").fetchone()[0]
        )
        preview = InventoryProposalTargetService.preview(
            snapshot,
            "spare_request_submission",
            (target,),
            evidence,
        )
    assert preview["status"] == "READY"
    assert preview["target_count"] == 1
    assert preview["requires_explicit_confirmation"] is False

    command_id = new_uuid4()
    with UnitOfWork(factory) as uow:
        uow.connection.execute(
            "INSERT INTO command_receipts(command_id,command_type,request_hash,"
            "target_type,target_id,committed_at_utc,result_type,result_id) "
            "VALUES (?,'AcceptCommunicationProposal',?,'communication_proposal',NULL,"
            "9122,NULL,NULL)",
            (command_id, "d" * 64),
        )
        refs = InventoryProposalTargetService.apply(
            uow,
            {
                "proposal_kind": "spare_request_submission",
                "target_refs": (target,),
                "evidence_ref": evidence,
                "base_token": preview["base_token"],
                "preview_fingerprint": preview["input_fingerprint"],
                "explicit_confirmation": False,
            },
            {
                "command_id": command_id,
                "actor_kind": "local_user",
                "actor_id": None,
            },
        )

    assert {ref["type"] for ref in refs} == {
        "spare_request_submission_event",
        "spare_request_submission_snapshot",
    }
    with ReadSnapshot(factory) as snapshot:
        assert int(
            snapshot.connection.execute("SELECT COUNT(*) FROM command_receipts").fetchone()[0]
        ) == before_receipts + 1
        state = snapshot.connection.execute(
            "SELECT lifecycle_state,revision FROM spare_request_current_projection "
            "WHERE spare_request_id=?",
            (request_id,),
        ).fetchone()
        assert tuple(state) == ("submitted_awaiting_response", 2)
        event = snapshot.connection.execute(
            "SELECT evidence_kind,evidence_id,command_id FROM spare_request_lifecycle_events "
            "WHERE spare_request_id=? AND event_kind='submission_accepted'",
            (request_id,),
        ).fetchone()
        assert tuple(event) == (
            "indexed_sent",
            "participant-indexed-send",
            command_id,
        )
        assert int(
            snapshot.connection.execute(
                "SELECT COUNT(*) FROM audit_events WHERE target_type='spare_request' "
                "AND target_id=? AND command_id=?",
                (request_id, command_id),
            ).fetchone()[0]
        ) == 1


def test_proposal_participant_fails_closed_for_non_authoritative_message_evidence(
    initialized_database,
) -> None:
    factory = _factory(initialized_database)
    request_id, draft_fingerprint = _draft(factory)
    target, evidence = _proposal(request_id, draft_fingerprint)
    evidence["evidence_kind"] = "message_body"

    with ReadSnapshot(factory) as snapshot:
        preview = InventoryProposalTargetService.preview(
            snapshot,
            "spare_request_submission",
            (target,),
            evidence,
        )
    assert preview == {
        "schema": "SOMA_INVENTORY_PROPOSAL_IMPACT_V1",
        "status": "INDETERMINATE",
        "reason_code": "VALIDATION_FAILED",
    }

