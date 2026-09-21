from __future__ import annotations

from soma.foundation.identifiers import new_uuid4
from soma.foundation.persistence.uow import ReadSnapshot
from soma.inventory.domain.requests import SpareRequestAllocationIntent
from soma.inventory.services.requests_rma import InventoryRequestsRmaService
from soma.reference.application.contact_service import ContactReferenceService
from test_inventory_requests_rma import (
    _dispatch_location,
    _factory,
    _need,
    _request_projection,
    _sr,
)


def test_t016_msg_generate_export_open_is_not_spare_request_submission_authority(
    initialized_database,
    tmp_path,
) -> None:
    factory = _factory(initialized_database)
    sr = _sr(factory, "97100016")
    need = _need(
        factory,
        sr_id=sr.service_request_id,
        device_name="REQ-MSG-T016",
        bom="REQ-MSG-T016",
    )
    contact = ContactReferenceService(factory).create_contact(
        command_id=new_uuid4(),
        name="MSG Boundary Receiver",
    )
    location_id = _dispatch_location(factory, "T016")
    service = InventoryRequestsRmaService(factory)

    created = service.create_spare_request_draft(
        command_id=new_uuid4(),
        service_request_id=sr.service_request_id,
        requester_contact_id=contact.contact_id,
        allocations=(SpareRequestAllocationIntent(need, 1),),
        mode="delivery",
        receiver_contact_id=contact.contact_id,
        dispatch_location_id=location_id,
    )
    request_id = str(created["spare_request_id"])
    before = tuple(_request_projection(factory, request_id))
    assert before[0] == "draft"
    assert before[1] is None
    assert before[2] == 0
    assert before[3] is None

    with ReadSnapshot(factory) as snapshot:
        receipt_count_before = int(
            snapshot.connection.execute(
                "SELECT COUNT(*) FROM command_receipts"
            ).fetchone()[0]
        )
        audit_count_before = int(
            snapshot.connection.execute(
                "SELECT COUNT(*) FROM audit_events"
            ).fetchone()[0]
        )
        assert snapshot.connection.execute(
            "SELECT COUNT(*) FROM spare_request_submission_snapshots "
            "WHERE spare_request_id=?",
            (request_id,),
        ).fetchone()[0] == 0
        assert snapshot.connection.execute(
            "SELECT COUNT(*) FROM spare_request_lifecycle_events "
            "WHERE spare_request_id=? AND event_kind='submission_accepted'",
            (request_id,),
        ).fetchone()[0] == 0

    # LLD-09 owns actual OXMSG/CFB generation and verification. For the LLD-07
    # boundary acceptance the artifact is intentionally opaque: generating bytes,
    # exporting them to a .msg path and opening that file must have no Inventory
    # authority unless AcceptSpareRequestSubmission is explicitly invoked.
    generated_msg_bytes = (
        b"SOMA-T016-OPAQUE-MSG-BOUNDARY\n"
        + request_id.encode("ascii")
        + b"\nNOT-SENT\n"
    )
    exported_path = tmp_path / f"SOMA-{request_id}.msg"
    exported_path.write_bytes(generated_msg_bytes)
    opened_bytes = exported_path.read_bytes()
    assert opened_bytes == generated_msg_bytes
    assert exported_path.suffix == ".msg"

    after_artifact = tuple(_request_projection(factory, request_id))
    assert after_artifact == before
    with ReadSnapshot(factory) as snapshot:
        assert snapshot.connection.execute(
            "SELECT COUNT(*) FROM command_receipts"
        ).fetchone()[0] == receipt_count_before
        assert snapshot.connection.execute(
            "SELECT COUNT(*) FROM audit_events"
        ).fetchone()[0] == audit_count_before
        assert snapshot.connection.execute(
            "SELECT COUNT(*) FROM spare_request_submission_snapshots "
            "WHERE spare_request_id=?",
            (request_id,),
        ).fetchone()[0] == 0
        assert snapshot.connection.execute(
            "SELECT COUNT(*) FROM spare_request_lifecycle_events "
            "WHERE spare_request_id=? AND event_kind='submission_accepted'",
            (request_id,),
        ).fetchone()[0] == 0

    # Submission chronology begins only at the explicit owner command.
    accepted = service.accept_spare_request_submission(
        command_id=new_uuid4(),
        spare_request_id=request_id,
        expected_fingerprint=str(before[5]),
        effective_submission_at_utc=4_000,
    )
    assert accepted["state"] == "submitted"
    after_submission = tuple(_request_projection(factory, request_id))
    assert after_submission[0] == "submitted_awaiting_response"
    assert after_submission[1] is not None
    assert after_submission[2] == 1
    assert after_submission[3] == 4_000
