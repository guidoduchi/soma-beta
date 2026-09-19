from __future__ import annotations

import pytest

from soma.foundation.errors import SomaError
from soma.foundation.identifiers import new_uuid4, utc_epoch_seconds
from soma.foundation.persistence.uow import ReadSnapshot, UnitOfWork
from soma.inventory.domain.requests import SpareRequestAllocationIntent
from soma.inventory.services.needs_stock import InventoryNeedsStockService
from soma.inventory.services.requests_rma import InventoryRequestsRmaService
from soma.reference.application.contact_service import ContactReferenceService
from soma.tickets.device_references import DeviceReferenceService
from soma.tickets.service_requests import ServiceRequestService


def _factory(initialized_database):
    database_path, factory_builder = initialized_database
    return factory_builder(database_path)


def _sr(factory, official: str):
    return ServiceRequestService(factory).create_manual_service_request(
        command_id=new_uuid4(),
        official_sr_no=official,
    )


def _device(factory, sr_id: str, name: str):
    device = DeviceReferenceService(factory).create(
        command_id=new_uuid4(),
        operational_name=name,
    )
    command_id = new_uuid4()
    with UnitOfWork(factory) as uow:
        uow.connection.execute(
            "INSERT INTO command_receipts("
            "command_id,command_type,request_hash,target_type,target_id,committed_at_utc,"
            "result_type,result_id"
            ") VALUES (?,?,?,?,?,?,?,?)",
            (
                command_id,
                "TestLinkInventoryRequestDevice",
                "a" * 64,
                "service_request",
                sr_id,
                utc_epoch_seconds(),
                None,
                None,
            ),
        )
        uow.connection.execute(
            "INSERT INTO sr_device_reference_links("
            "sr_device_reference_link_id,service_request_id,device_reference_id,link_state,"
            "opened_at_utc,closed_at_utc,opened_command_id,closed_command_id"
            ") VALUES (?,?,?,'active',?,NULL,?,NULL)",
            (
                new_uuid4(),
                sr_id,
                device.device_reference_id,
                utc_epoch_seconds(),
                command_id,
            ),
        )
    return device


def _dispatch_location(factory, suffix: str) -> str:
    location_id = new_uuid4()
    now = utc_epoch_seconds()
    with UnitOfWork(factory) as uow:
        uow.connection.execute(
            "INSERT INTO dispatch_locations("
            "dispatch_location_id,name,name_match_key,address_mode,standalone_address_text,"
            "lifecycle_state,revision,created_at_utc,updated_at_utc"
            ") VALUES (?,?,?,'standalone',?,'active',1,?,?)",
            (
                location_id,
                f"Warehouse {suffix}",
                f"warehouse {suffix}".lower(),
                f"{suffix} test address",
                now,
                now,
            ),
        )
    return location_id


def _need(factory, *, sr_id: str, device_name: str, bom: str) -> str:
    device = _device(factory, sr_id, device_name)
    result = InventoryNeedsStockService(factory).register_device_part_unit(
        command_id=new_uuid4(),
        service_request_id=sr_id,
        device_reference_id=device.device_reference_id,
        bom_code=bom,
        condition_token="faulty",
    )
    return next(
        ref.result_id
        for ref in result.target_refs
        if ref.result_type == "spare_need"
    )


def test_t014_spare_request_draft_aggregates_same_sr_needs_and_freezes_requester_context(
    initialized_database,
) -> None:
    factory = _factory(initialized_database)
    sr = _sr(factory, "97100001")
    need_a = _need(
        factory,
        sr_id=sr.service_request_id,
        device_name="REQ-A",
        bom="REQ-BOM-A",
    )
    need_b = _need(
        factory,
        sr_id=sr.service_request_id,
        device_name="REQ-B",
        bom="REQ-BOM-B",
    )
    contacts = ContactReferenceService(factory)
    requester = contacts.create_contact(
        command_id=new_uuid4(),
        name="Original Requester",
    )
    receiver = contacts.create_contact(
        command_id=new_uuid4(),
        name="Different Receiver",
    )
    location_id = _dispatch_location(factory, "T014")
    service = InventoryRequestsRmaService(factory)

    result = service.create_spare_request_draft(
        command_id=new_uuid4(),
        service_request_id=sr.service_request_id,
        requester_contact_id=requester.contact_id,
        allocations=(
            SpareRequestAllocationIntent(need_a, 2),
            SpareRequestAllocationIntent(need_b, 3),
        ),
        mode="delivery",
        receiver_contact_id=receiver.contact_id,
        dispatch_location_id=location_id,
    )

    assert result["local_handle"] == "SPR-00000001"
    assert result["state"] == "draft"
    assert result["revision"] == 1
    assert result["requester"] == {
        "contact_id": requester.contact_id,
        "contact_revision_at_creation": 1,
        "affiliation_id_at_creation": None,
        "customer_org_id_at_creation": None,
        "display_name_snapshot": "Original Requester",
    }
    assert result["requester"]["contact_id"] != receiver.contact_id

    with ReadSnapshot(factory) as snapshot:
        request_id = str(result["spare_request_id"])
        allocations = snapshot.connection.execute(
            "SELECT spare_need_id,quantity,revision,active_draft "
            "FROM spare_request_need_allocations WHERE spare_request_id=? "
            "ORDER BY spare_need_id",
            (request_id,),
        ).fetchall()
        assert {
            (str(row[0]), int(row[1]), int(row[2]), int(row[3]))
            for row in allocations
        } == {
            (need_a, 2, 1, 1),
            (need_b, 3, 1, 1),
        }
        logistics = snapshot.connection.execute(
            "SELECT mode,receiver_contact_id,dispatch_location_id,revision "
            "FROM spare_request_draft_logistics WHERE spare_request_id=?",
            (request_id,),
        ).fetchone()
        assert tuple(logistics) == (
            "delivery",
            receiver.contact_id,
            location_id,
            1,
        )
        assert snapshot.connection.execute(
            "SELECT COUNT(*) FROM spare_request_submission_snapshots "
            "WHERE spare_request_id=?",
            (request_id,),
        ).fetchone()[0] == 0


def test_t015_cross_sr_spare_request_draft_fails_before_identity_allocation(
    initialized_database,
) -> None:
    factory = _factory(initialized_database)
    sr_a = _sr(factory, "97100002")
    sr_b = _sr(factory, "97100003")
    need_a = _need(
        factory,
        sr_id=sr_a.service_request_id,
        device_name="REQ-XA",
        bom="REQ-X",
    )
    need_b = _need(
        factory,
        sr_id=sr_b.service_request_id,
        device_name="REQ-XB",
        bom="REQ-X",
    )
    contact = ContactReferenceService(factory).create_contact(
        command_id=new_uuid4(),
        name="Cross SR Requester",
    )
    location_id = _dispatch_location(factory, "T015")
    service = InventoryRequestsRmaService(factory)

    with pytest.raises(SomaError) as excinfo:
        service.create_spare_request_draft(
            command_id=new_uuid4(),
            service_request_id=sr_a.service_request_id,
            requester_contact_id=contact.contact_id,
            allocations=(
                SpareRequestAllocationIntent(need_a, 1),
                SpareRequestAllocationIntent(need_b, 1),
            ),
            mode="self_pickup",
            receiver_contact_id=contact.contact_id,
            dispatch_location_id=location_id,
        )
    assert excinfo.value.code == "NEED_CROSS_SR"

    with ReadSnapshot(factory) as snapshot:
        assert snapshot.connection.execute(
            "SELECT COUNT(*) FROM spare_requests"
        ).fetchone()[0] == 0
        allocator = snapshot.connection.execute(
            "SELECT next_sequence,revision FROM inventory_tracking_allocators "
            "WHERE allocator_kind='spare_request'"
        ).fetchone()
        assert tuple(allocator) == (1, 1)


def test_spare_request_draft_update_replaces_editable_intent_without_touching_requester(
    initialized_database,
) -> None:
    factory = _factory(initialized_database)
    sr = _sr(factory, "97100004")
    need_a = _need(factory, sr_id=sr.service_request_id, device_name="REQ-UP-A", bom="REQ-UP-A")
    need_b = _need(factory, sr_id=sr.service_request_id, device_name="REQ-UP-B", bom="REQ-UP-B")
    contacts = ContactReferenceService(factory)
    requester = contacts.create_contact(command_id=new_uuid4(), name="Draft Requester")
    receiver = contacts.create_contact(command_id=new_uuid4(), name="Draft Receiver")
    location_a = _dispatch_location(factory, "UP-A")
    location_b = _dispatch_location(factory, "UP-B")
    service = InventoryRequestsRmaService(factory)

    created = service.create_spare_request_draft(
        command_id=new_uuid4(),
        service_request_id=sr.service_request_id,
        requester_contact_id=requester.contact_id,
        allocations=(SpareRequestAllocationIntent(need_a, 1),),
        mode="delivery",
        receiver_contact_id=receiver.contact_id,
        dispatch_location_id=location_a,
    )
    request_id = str(created["spare_request_id"])
    updated = service.update_spare_request_draft(
        command_id=new_uuid4(),
        spare_request_id=request_id,
        base_revision=1,
        allocations=(SpareRequestAllocationIntent(need_b, 3),),
        mode="self_pickup",
        receiver_contact_id=receiver.contact_id,
        dispatch_location_id=location_b,
    )
    assert updated["revision"] == 2
    assert updated["requester"] == created["requester"]

    with ReadSnapshot(factory) as snapshot:
        active = snapshot.connection.execute(
            "SELECT spare_need_id,quantity FROM spare_request_need_allocations "
            "WHERE spare_request_id=? AND active_draft=1",
            (request_id,),
        ).fetchall()
        assert [(str(row[0]), int(row[1])) for row in active] == [(need_b, 3)]
        assert snapshot.connection.execute(
            "SELECT COUNT(*) FROM spare_request_need_allocations "
            "WHERE spare_request_id=? AND active_draft=0",
            (request_id,),
        ).fetchone()[0] == 1
        assert snapshot.connection.execute(
            "SELECT COUNT(*) FROM spare_request_submission_snapshots WHERE spare_request_id=?",
            (request_id,),
        ).fetchone()[0] == 0


def test_t021_t022_t023_sr7_assignment_correction_and_global_non_reuse(
    initialized_database,
) -> None:
    factory = _factory(initialized_database)
    sr = _sr(factory, "97100005")
    need = _need(factory, sr_id=sr.service_request_id, device_name="REQ-SR7", bom="REQ-SR7")
    contact = ContactReferenceService(factory).create_contact(
        command_id=new_uuid4(),
        name="SR7 Requester",
    )
    location_id = _dispatch_location(factory, "SR7")
    service = InventoryRequestsRmaService(factory)
    first = service.create_spare_request_draft(
        command_id=new_uuid4(),
        service_request_id=sr.service_request_id,
        requester_contact_id=contact.contact_id,
        allocations=(SpareRequestAllocationIntent(need, 1),),
        mode="delivery",
        receiver_contact_id=contact.contact_id,
        dispatch_location_id=location_id,
    )
    request_id = str(first["spare_request_id"])

    assigned = service.assign_or_correct_spare_request_official_id(
        command_id=new_uuid4(),
        spare_request_id=request_id,
        base_revision=1,
        sr7="SR0000001",
        action="assign",
    )
    assert assigned["official_sr7"] == "SR0000001"
    assert assigned["revision"] == 2

    corrected = service.assign_or_correct_spare_request_official_id(
        command_id=new_uuid4(),
        spare_request_id=request_id,
        base_revision=2,
        sr7="SR0000002",
        action="correct",
        reason_code="provider corrected identifier",
    )
    assert corrected["official_sr7"] == "SR0000002"
    assert corrected["revision"] == 3

    second = service.create_spare_request_draft(
        command_id=new_uuid4(),
        service_request_id=sr.service_request_id,
        requester_contact_id=contact.contact_id,
        allocations=(SpareRequestAllocationIntent(need, 1),),
        mode="delivery",
        receiver_contact_id=contact.contact_id,
        dispatch_location_id=location_id,
    )
    with pytest.raises(SomaError) as excinfo:
        service.assign_or_correct_spare_request_official_id(
            command_id=new_uuid4(),
            spare_request_id=str(second["spare_request_id"]),
            base_revision=1,
            sr7="SR0000001",
            action="assign",
        )
    assert excinfo.value.code == "SR7_CONFLICT"

    with ReadSnapshot(factory) as snapshot:
        aliases = snapshot.connection.execute(
            "SELECT sr7,alias_kind FROM spare_request_identifier_aliases "
            "WHERE spare_request_id=? ORDER BY sr7",
            (request_id,),
        ).fetchall()
        assert [tuple(row) for row in aliases] == [
            ("SR0000001", "former"),
            ("SR0000002", "current"),
        ]


def test_terminal_request_preserves_history_and_unblocks_nonterminal_semantics(
    initialized_database,
) -> None:
    factory = _factory(initialized_database)
    sr = _sr(factory, "97100006")
    need = _need(factory, sr_id=sr.service_request_id, device_name="REQ-TERM", bom="REQ-TERM")
    contact = ContactReferenceService(factory).create_contact(
        command_id=new_uuid4(),
        name="Terminal Requester",
    )
    location_id = _dispatch_location(factory, "TERM")
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
    terminal = service.cancel_or_reject_spare_request(
        command_id=new_uuid4(),
        spare_request_id=request_id,
        base_revision=1,
        action="cancelled",
        reason_code="request withdrawn",
    )
    assert terminal["state"] == "terminal"
    assert terminal["requester"] == created["requester"]
    assert terminal["revision"] == 2
    with ReadSnapshot(factory) as snapshot:
        assert snapshot.connection.execute(
            "SELECT lifecycle_state FROM spare_request_current_projection "
            "WHERE spare_request_id=?",
            (request_id,),
        ).fetchone()[0] == "cancelled"
        assert snapshot.connection.execute(
            "SELECT COUNT(*) FROM spare_request_lifecycle_events "
            "WHERE spare_request_id=? AND event_kind='cancelled'",
            (request_id,),
        ).fetchone()[0] == 1


def _request_projection(factory, request_id: str):
    with ReadSnapshot(factory) as snapshot:
        return snapshot.connection.execute(
            "SELECT lifecycle_state,current_submission_snapshot_id,submitted_quantity,"
            "response_warning_start_utc,revision,input_fingerprint "
            "FROM spare_request_current_projection WHERE spare_request_id=?",
            (request_id,),
        ).fetchone()


def test_t017_t019_submission_freezes_exact_snapshot_and_starts_warning_chronology(
    initialized_database,
) -> None:
    factory = _factory(initialized_database)
    sr = _sr(factory, "97100007")
    need = _need(factory, sr_id=sr.service_request_id, device_name="REQ-SUB", bom="REQ-SUB-BOM")
    contact = ContactReferenceService(factory).create_contact(
        command_id=new_uuid4(), name="Submission Receiver"
    )
    location_id = _dispatch_location(factory, "SUB")
    service = InventoryRequestsRmaService(factory)
    created = service.create_spare_request_draft(
        command_id=new_uuid4(),
        service_request_id=sr.service_request_id,
        requester_contact_id=contact.contact_id,
        allocations=(SpareRequestAllocationIntent(need, 2),),
        mode="delivery",
        receiver_contact_id=contact.contact_id,
        dispatch_location_id=location_id,
    )
    request_id = str(created["spare_request_id"])
    before = _request_projection(factory, request_id)
    submitted = service.accept_spare_request_submission(
        command_id=new_uuid4(),
        spare_request_id=request_id,
        expected_fingerprint=str(before[5]),
        effective_submission_at_utc=1_000,
    )
    assert submitted["state"] == "submitted"
    assert submitted["revision"] == 2

    with ReadSnapshot(factory) as snapshot:
        projection = snapshot.connection.execute(
            "SELECT lifecycle_state,current_submission_snapshot_id,submitted_quantity,"
            "response_warning_start_utc,revision "
            "FROM spare_request_current_projection WHERE spare_request_id=?",
            (request_id,),
        ).fetchone()
        assert tuple(projection[:1]) == ("submitted_awaiting_response",)
        assert projection[1] is not None
        assert tuple(projection[2:]) == (2, 1_000, 2)
        snapshot_id = str(projection[1])
        frozen = snapshot.connection.execute(
            "SELECT temporary_tracking_id,mode,receiver_contact_id,dispatch_location_id,"
            "location_name_snapshot,location_address_snapshot,effective_submission_at_utc "
            "FROM spare_request_submission_snapshots WHERE submission_snapshot_id=?",
            (snapshot_id,),
        ).fetchone()
        assert tuple(frozen[:4]) == (
            created["local_handle"],
            "delivery",
            contact.contact_id,
            location_id,
        )
        assert str(frozen[4]) == "Warehouse SUB"
        assert str(frozen[5]) == "SUB test address"
        assert int(frozen[6]) == 1_000
        allocation = snapshot.connection.execute(
            "SELECT spare_need_id,quantity,requested_bom_code "
            "FROM spare_request_submission_allocations WHERE submission_snapshot_id=?",
            (snapshot_id,),
        ).fetchone()
        assert (str(allocation[0]), int(allocation[1]), str(allocation[2])) == (
            need,
            2,
            "REQ-SUB-BOM",
        )

    with pytest.raises(SomaError) as excinfo:
        service.update_spare_request_draft(
            command_id=new_uuid4(),
            spare_request_id=request_id,
            base_revision=2,
            allocations=(SpareRequestAllocationIntent(need, 3),),
            mode="delivery",
            receiver_contact_id=contact.contact_id,
            dispatch_location_id=location_id,
        )
    assert excinfo.value.code == "REQUEST_NOT_DRAFT"


def test_t020_false_submission_correction_preserves_snapshot_and_restores_draft(
    initialized_database,
) -> None:
    factory = _factory(initialized_database)
    sr = _sr(factory, "97100008")
    need = _need(factory, sr_id=sr.service_request_id, device_name="REQ-FALSE", bom="REQ-FALSE")
    contact = ContactReferenceService(factory).create_contact(
        command_id=new_uuid4(), name="False Submission"
    )
    location_id = _dispatch_location(factory, "FALSE")
    service = InventoryRequestsRmaService(factory)
    created = service.create_spare_request_draft(
        command_id=new_uuid4(),
        service_request_id=sr.service_request_id,
        requester_contact_id=contact.contact_id,
        allocations=(SpareRequestAllocationIntent(need, 1),),
        mode="self_pickup",
        receiver_contact_id=contact.contact_id,
        dispatch_location_id=location_id,
    )
    request_id = str(created["spare_request_id"])
    before = _request_projection(factory, request_id)
    service.accept_spare_request_submission(
        command_id=new_uuid4(),
        spare_request_id=request_id,
        expected_fingerprint=str(before[5]),
        evidence_kind="indexed_sent",
        evidence_id="indexed-message-1",
    )
    with ReadSnapshot(factory) as snapshot:
        submission = snapshot.connection.execute(
            "SELECT submission_event_id,submission_snapshot_id "
            "FROM spare_request_submission_snapshots WHERE spare_request_id=?",
            (request_id,),
        ).fetchone()
        event_id = str(submission[0])
        snapshot_id = str(submission[1])

    corrected = service.correct_false_spare_request_submission(
        command_id=new_uuid4(),
        spare_request_id=request_id,
        submission_event_id=event_id,
        reason_code="confirmed message was never sent",
    )
    assert corrected["state"] == "draft"
    assert corrected["revision"] == 3

    with ReadSnapshot(factory) as snapshot:
        projection = snapshot.connection.execute(
            "SELECT lifecycle_state,current_submission_snapshot_id,submitted_quantity,"
            "response_warning_start_utc FROM spare_request_current_projection "
            "WHERE spare_request_id=?",
            (request_id,),
        ).fetchone()
        assert tuple(projection) == ("draft", None, 0, None)
        assert snapshot.connection.execute(
            "SELECT COUNT(*) FROM spare_request_submission_snapshots "
            "WHERE submission_snapshot_id=?",
            (snapshot_id,),
        ).fetchone()[0] == 1
        assert snapshot.connection.execute(
            "SELECT COUNT(*) FROM spare_request_lifecycle_events "
            "WHERE spare_request_id=? AND event_kind='submission_corrected_false' "
            "AND target_event_id=?",
            (request_id, event_id),
        ).fetchone()[0] == 1

    updated = service.update_spare_request_draft(
        command_id=new_uuid4(),
        spare_request_id=request_id,
        base_revision=3,
        allocations=(SpareRequestAllocationIntent(need, 2),),
        mode="delivery",
        receiver_contact_id=contact.contact_id,
        dispatch_location_id=location_id,
    )
    assert updated["revision"] == 4
