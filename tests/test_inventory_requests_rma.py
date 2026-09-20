from __future__ import annotations

import pytest

from soma.foundation.errors import SomaError
from soma.foundation.identifiers import new_uuid4, utc_epoch_seconds
from soma.foundation.persistence.uow import ReadSnapshot, UnitOfWork
from soma.inventory.domain.requests import SpareRequestAllocationIntent
from soma.inventory.queries.attention_history import InventoryAttentionQueryService
from soma.inventory.queries.requests_rma import InventoryRequestsQueryService
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

class _ValidIndexedSentEvidence:
    def __init__(self) -> None:
        self.calls: list[tuple[str, int, str, str]] = []

    def validate_indexed_sent_evidence(
        self,
        uow,
        *,
        spare_request_id: str,
        spare_request_revision: int,
        evidence_kind: str,
        evidence_id: str,
    ) -> str:
        assert uow.connection.in_transaction
        self.calls.append(
            (
                spare_request_id,
                spare_request_revision,
                evidence_kind,
                evidence_id,
            )
        )
        return "VALID"


def _request_fixture(initialized_database, *, official_sr: str, suffix: str):
    factory = _factory(initialized_database)
    sr = _sr(factory, official_sr)
    need = _need(
        factory,
        sr_id=sr.service_request_id,
        device_name=f"REQ-{suffix}",
        bom=f"BOM-{suffix}",
    )
    contacts = ContactReferenceService(factory)
    requester = contacts.create_contact(
        command_id=new_uuid4(),
        name=f"Requester {suffix}",
    )
    receiver = contacts.create_contact(
        command_id=new_uuid4(),
        name=f"Receiver {suffix}",
    )
    location_id = _dispatch_location(factory, suffix)
    service = InventoryRequestsRmaService(factory)
    created = service.create_spare_request_draft(
        command_id=new_uuid4(),
        service_request_id=sr.service_request_id,
        requester_contact_id=requester.contact_id,
        allocations=(SpareRequestAllocationIntent(need, 2),),
        mode="delivery",
        receiver_contact_id=receiver.contact_id,
        dispatch_location_id=location_id,
    )
    return (
        factory,
        sr,
        need,
        requester,
        receiver,
        location_id,
        service,
        created,
    )


def test_t016_msg_draft_payload_is_pure_and_never_starts_submission_chronology(
    initialized_database,
) -> None:
    (
        factory,
        _sr_result,
        _need_id,
        _requester,
        _receiver,
        _location_id,
        _service,
        created,
    ) = _request_fixture(
        initialized_database,
        official_sr="97100004",
        suffix="T016",
    )
    request_id = str(created["spare_request_id"])
    query = InventoryRequestsQueryService(factory)

    with ReadSnapshot(factory) as snapshot:
        before = (
            snapshot.connection.execute(
                "SELECT lifecycle_state,current_submission_snapshot_id,"
                "response_warning_start_utc,revision,input_fingerprint "
                "FROM spare_request_current_projection WHERE spare_request_id=?",
                (request_id,),
            ).fetchone(),
            snapshot.connection.execute(
                "SELECT COUNT(*) FROM spare_request_lifecycle_events "
                "WHERE spare_request_id=?",
                (request_id,),
            ).fetchone()[0],
            snapshot.connection.execute(
                "SELECT COUNT(*) FROM command_receipts"
            ).fetchone()[0],
            snapshot.connection.execute(
                "SELECT COUNT(*) FROM audit_events"
            ).fetchone()[0],
        )

    generated = query.spare_request_draft_payload(request_id)
    exported = query.spare_request_draft_payload(request_id)
    opened = query.spare_request_draft_payload(request_id)

    assert generated == exported == opened
    assert generated.payload["schema"] == "INVENTORY_SPARE_REQUEST_DRAFT_V1"
    assert generated.payload["temporary_tracking_id"] == created["local_handle"]
    assert generated.payload["request_revision"] == 1

    with ReadSnapshot(factory) as snapshot:
        after = (
            snapshot.connection.execute(
                "SELECT lifecycle_state,current_submission_snapshot_id,"
                "response_warning_start_utc,revision,input_fingerprint "
                "FROM spare_request_current_projection WHERE spare_request_id=?",
                (request_id,),
            ).fetchone(),
            snapshot.connection.execute(
                "SELECT COUNT(*) FROM spare_request_lifecycle_events "
                "WHERE spare_request_id=?",
                (request_id,),
            ).fetchone()[0],
            snapshot.connection.execute(
                "SELECT COUNT(*) FROM command_receipts"
            ).fetchone()[0],
            snapshot.connection.execute(
                "SELECT COUNT(*) FROM audit_events"
            ).fetchone()[0],
        )
    assert tuple(before[0]) == ("draft", None, None, 1, generated.payload["request_input_fingerprint"])
    assert after == before


def test_t017_manual_submission_freezes_exact_snapshot_and_replays(
    initialized_database,
) -> None:
    (
        factory,
        _sr_result,
        need_id,
        _requester,
        receiver,
        location_id,
        service,
        created,
    ) = _request_fixture(
        initialized_database,
        official_sr="97100005",
        suffix="T017",
    )
    request_id = str(created["spare_request_id"])
    detail = InventoryRequestsQueryService(factory).get_spare_request(request_id)
    command_id = new_uuid4()

    submitted = service.accept_spare_request_submission(
        command_id=command_id,
        spare_request_id=request_id,
        base_revision=1,
        expected_draft_fingerprint=str(detail["input_fingerprint"]),
        effective_submission_at_utc=1_700_000_000,
    )
    assert submitted["state"] == "submitted"
    assert submitted["revision"] == 2

    replay = service.accept_spare_request_submission(
        command_id=command_id,
        spare_request_id=request_id,
        base_revision=1,
        expected_draft_fingerprint=str(detail["input_fingerprint"]),
        effective_submission_at_utc=1_700_000_000,
    )
    assert replay == submitted

    with ReadSnapshot(factory) as snapshot:
        projection = snapshot.connection.execute(
            "SELECT lifecycle_state,current_submission_snapshot_id,submitted_quantity,"
            "response_warning_start_utc,revision FROM spare_request_current_projection "
            "WHERE spare_request_id=?",
            (request_id,),
        ).fetchone()
        assert tuple(projection[0:1] + projection[2:]) == (
            "submitted_awaiting_response",
            2,
            1_700_000_000,
            2,
        )
        snapshot_id = str(projection[1])
        submission = snapshot.connection.execute(
            "SELECT temporary_tracking_id,mode,receiver_contact_id,dispatch_location_id,"
            "location_name_snapshot,location_address_snapshot,recipient_context_json,"
            "effective_submission_at_utc,evidence_kind,evidence_id,snapshot_hash "
            "FROM spare_request_submission_snapshots WHERE submission_snapshot_id=?",
            (snapshot_id,),
        ).fetchone()
        assert tuple(submission[:6]) == (
            created["local_handle"],
            "delivery",
            receiver.contact_id,
            location_id,
            "Warehouse T017",
            "T017 test address",
        )
        assert int(submission[7]) == 1_700_000_000
        assert submission[8] is None and submission[9] is None
        allocation = snapshot.connection.execute(
            "SELECT spare_need_id,quantity,requested_bom_code,requested_bom_key "
            "FROM spare_request_submission_allocations WHERE submission_snapshot_id=?",
            (snapshot_id,),
        ).fetchone()
        assert str(allocation[0]) == need_id
        assert int(allocation[1]) == 2
        original_snapshot_row = tuple(submission)
        original_allocation_row = tuple(allocation)

    ContactReferenceService(factory).update_contact_descriptive_data(
        command_id=new_uuid4(),
        contact_id=receiver.contact_id,
        base_revision=1,
        name="Receiver Changed After Submission",
    )
    InventoryNeedsStockService(factory).set_spare_need_planned_quantity(
        command_id=new_uuid4(),
        spare_need_id=need_id,
        base_revision=1,
        planned_quantity=9,
        reason_code="post-submission planning change",
    )

    with ReadSnapshot(factory) as snapshot:
        assert tuple(
            snapshot.connection.execute(
                "SELECT temporary_tracking_id,mode,receiver_contact_id,dispatch_location_id,"
                "location_name_snapshot,location_address_snapshot,recipient_context_json,"
                "effective_submission_at_utc,evidence_kind,evidence_id,snapshot_hash "
                "FROM spare_request_submission_snapshots WHERE submission_snapshot_id=?",
                (snapshot_id,),
            ).fetchone()
        ) == original_snapshot_row
        assert tuple(
            snapshot.connection.execute(
                "SELECT spare_need_id,quantity,requested_bom_code,requested_bom_key "
                "FROM spare_request_submission_allocations WHERE submission_snapshot_id=?",
                (snapshot_id,),
            ).fetchone()
        ) == original_allocation_row
        assert snapshot.connection.execute(
            "SELECT COUNT(*) FROM spare_request_submission_snapshots "
            "WHERE spare_request_id=?",
            (request_id,),
        ).fetchone()[0] == 1


def test_t018_indexed_sent_submission_requires_and_uses_typed_validator(
    initialized_database,
) -> None:
    (
        factory,
        _sr_result,
        _need_id,
        _requester,
        _receiver,
        _location_id,
        _service,
        created,
    ) = _request_fixture(
        initialized_database,
        official_sr="97100006",
        suffix="T018",
    )
    request_id = str(created["spare_request_id"])
    detail = InventoryRequestsQueryService(factory).get_spare_request(request_id)

    unavailable = InventoryRequestsRmaService(factory)
    with pytest.raises(SomaError) as excinfo:
        unavailable.accept_spare_request_submission(
            command_id=new_uuid4(),
            spare_request_id=request_id,
            base_revision=1,
            expected_draft_fingerprint=str(detail["input_fingerprint"]),
            effective_submission_at_utc=1_700_100_000,
            evidence_kind="indexed_sent",
            evidence_id="COMM-EVIDENCE-001",
        )
    assert excinfo.value.code == "DEPENDENCY_INDETERMINATE"

    with ReadSnapshot(factory) as snapshot:
        assert snapshot.connection.execute(
            "SELECT lifecycle_state FROM spare_request_current_projection "
            "WHERE spare_request_id=?",
            (request_id,),
        ).fetchone()[0] == "draft"
        assert snapshot.connection.execute(
            "SELECT COUNT(*) FROM spare_request_submission_snapshots "
            "WHERE spare_request_id=?",
            (request_id,),
        ).fetchone()[0] == 0

    validator = _ValidIndexedSentEvidence()
    service = InventoryRequestsRmaService(
        factory,
        submission_evidence_validator=validator,
    )
    submitted = service.accept_spare_request_submission(
        command_id=new_uuid4(),
        spare_request_id=request_id,
        base_revision=1,
        expected_draft_fingerprint=str(detail["input_fingerprint"]),
        effective_submission_at_utc=1_700_100_000,
        evidence_kind="indexed_sent",
        evidence_id="COMM-EVIDENCE-001",
    )
    assert submitted["state"] == "submitted"
    assert validator.calls == [
        (
            request_id,
            1,
            "indexed_sent",
            "COMM-EVIDENCE-001",
        )
    ]
    with ReadSnapshot(factory) as snapshot:
        evidence = snapshot.connection.execute(
            "SELECT evidence_kind,evidence_id FROM spare_request_submission_snapshots "
            "WHERE spare_request_id=?",
            (request_id,),
        ).fetchone()
        assert tuple(evidence) == ("indexed_sent", "COMM-EVIDENCE-001")


def test_t019_response_attention_flips_at_exact_twenty_four_hour_boundary(
    initialized_database,
) -> None:
    (
        factory,
        _sr_result,
        _need_id,
        _requester,
        _receiver,
        _location_id,
        service,
        created,
    ) = _request_fixture(
        initialized_database,
        official_sr="97100007",
        suffix="T019",
    )
    request_id = str(created["spare_request_id"])
    detail = InventoryRequestsQueryService(factory).get_spare_request(request_id)
    warning_start = 1_700_200_000
    service.accept_spare_request_submission(
        command_id=new_uuid4(),
        spare_request_id=request_id,
        base_revision=1,
        expected_draft_fingerprint=str(detail["input_fingerprint"]),
        effective_submission_at_utc=warning_start,
    )

    attention = InventoryAttentionQueryService(factory)
    assert attention.spare_request_response_attention(
        spare_request_id=request_id,
        as_of_utc=warning_start + 86_399,
    ) is None
    exact = attention.spare_request_response_attention(
        spare_request_id=request_id,
        as_of_utc=warning_start + 86_400,
    )
    assert exact is not None
    assert exact.attention_kind == "spare_request_response_overdue"
    assert exact.warning_start_utc == warning_start
    assert exact.due_at_utc == warning_start + 86_400
    assert exact.age_seconds == 86_400


def test_t020_false_submission_correction_preserves_snapshot_and_restores_draft(
    initialized_database,
) -> None:
    (
        factory,
        _sr_result,
        need_id,
        _requester,
        receiver,
        location_id,
        service,
        created,
    ) = _request_fixture(
        initialized_database,
        official_sr="97100008",
        suffix="T020",
    )
    request_id = str(created["spare_request_id"])
    query = InventoryRequestsQueryService(factory)
    detail = query.get_spare_request(request_id)
    service.accept_spare_request_submission(
        command_id=new_uuid4(),
        spare_request_id=request_id,
        base_revision=1,
        expected_draft_fingerprint=str(detail["input_fingerprint"]),
        effective_submission_at_utc=1_700_300_000,
    )

    with ReadSnapshot(factory) as snapshot:
        current = snapshot.connection.execute(
            "SELECT p.current_submission_snapshot_id,s.submission_event_id,s.snapshot_hash "
            "FROM spare_request_current_projection p "
            "JOIN spare_request_submission_snapshots s "
            "ON s.submission_snapshot_id=p.current_submission_snapshot_id "
            "WHERE p.spare_request_id=?",
            (request_id,),
        ).fetchone()
        snapshot_id = str(current[0])
        submission_event_id = str(current[1])
        snapshot_hash = str(current[2])

    corrected = service.correct_false_spare_request_submission(
        command_id=new_uuid4(),
        spare_request_id=request_id,
        base_revision=2,
        submission_event_id=submission_event_id,
        reason_code="operator confirmed message was never sent",
        confirmed_no_real_send=True,
    )
    assert corrected["state"] == "draft"
    assert corrected["revision"] == 3

    with ReadSnapshot(factory) as snapshot:
        projection = snapshot.connection.execute(
            "SELECT lifecycle_state,current_submission_snapshot_id,submitted_quantity,"
            "response_warning_start_utc,revision FROM spare_request_current_projection "
            "WHERE spare_request_id=?",
            (request_id,),
        ).fetchone()
        assert tuple(projection) == ("draft", None, 0, None, 3)
        preserved = snapshot.connection.execute(
            "SELECT snapshot_hash FROM spare_request_submission_snapshots "
            "WHERE submission_snapshot_id=?",
            (snapshot_id,),
        ).fetchone()
        assert str(preserved[0]) == snapshot_hash
        correction = snapshot.connection.execute(
            "SELECT target_event_id,reason_code FROM spare_request_lifecycle_events "
            "WHERE spare_request_id=? AND event_kind='submission_corrected_false'",
            (request_id,),
        ).fetchone()
        assert tuple(correction) == (
            submission_event_id,
            "operator confirmed message was never sent",
        )

    updated = service.update_spare_request_draft(
        command_id=new_uuid4(),
        spare_request_id=request_id,
        base_revision=3,
        allocations=(SpareRequestAllocationIntent(need_id, 4),),
        mode="self_pickup",
        receiver_contact_id=receiver.contact_id,
        dispatch_location_id=location_id,
    )
    assert updated["state"] == "draft"
    assert updated["revision"] == 4


def test_false_submission_correction_rejects_indexed_sent_evidence(
    initialized_database,
) -> None:
    (
        factory,
        _sr_result,
        _need_id,
        _requester,
        _receiver,
        _location_id,
        _service,
        created,
    ) = _request_fixture(
        initialized_database,
        official_sr="97100009",
        suffix="T020-EVIDENCE",
    )
    request_id = str(created["spare_request_id"])
    detail = InventoryRequestsQueryService(factory).get_spare_request(request_id)
    validator = _ValidIndexedSentEvidence()
    service = InventoryRequestsRmaService(
        factory,
        submission_evidence_validator=validator,
    )
    service.accept_spare_request_submission(
        command_id=new_uuid4(),
        spare_request_id=request_id,
        base_revision=1,
        expected_draft_fingerprint=str(detail["input_fingerprint"]),
        evidence_kind="indexed_sent",
        evidence_id="COMM-EVIDENCE-REAL",
    )
    with ReadSnapshot(factory) as snapshot:
        event_id = snapshot.connection.execute(
            "SELECT submission_event_id FROM spare_request_submission_snapshots "
            "WHERE spare_request_id=?",
            (request_id,),
        ).fetchone()[0]

    with pytest.raises(SomaError) as excinfo:
        service.correct_false_spare_request_submission(
            command_id=new_uuid4(),
            spare_request_id=request_id,
            base_revision=2,
            submission_event_id=str(event_id),
            reason_code="incorrect operator claim",
            confirmed_no_real_send=True,
        )
    assert excinfo.value.code == "CORRECTION_TARGET_INVALID"
    with ReadSnapshot(factory) as snapshot:
        assert snapshot.connection.execute(
            "SELECT lifecycle_state FROM spare_request_current_projection "
            "WHERE spare_request_id=?",
            (request_id,),
        ).fetchone()[0] == "submitted_awaiting_response"

def test_t021_t022_sr7_assignment_and_correction_preserve_request_and_submission_history(
    initialized_database,
) -> None:
    (
        factory,
        _sr_result,
        _need_id,
        _requester,
        _receiver,
        _location_id,
        service,
        created,
    ) = _request_fixture(
        initialized_database,
        official_sr="97100010",
        suffix="T021",
    )
    request_id = str(created["spare_request_id"])
    detail = InventoryRequestsQueryService(factory).get_spare_request(request_id)
    service.accept_spare_request_submission(
        command_id=new_uuid4(),
        spare_request_id=request_id,
        base_revision=1,
        expected_draft_fingerprint=str(detail["input_fingerprint"]),
        effective_submission_at_utc=1_700_400_000,
    )
    with ReadSnapshot(factory) as snapshot:
        original_snapshot_id = snapshot.connection.execute(
            "SELECT current_submission_snapshot_id "
            "FROM spare_request_current_projection WHERE spare_request_id=?",
            (request_id,),
        ).fetchone()[0]
        original_snapshot_hash = snapshot.connection.execute(
            "SELECT snapshot_hash FROM spare_request_submission_snapshots "
            "WHERE submission_snapshot_id=?",
            (original_snapshot_id,),
        ).fetchone()[0]

    assigned = service.assign_or_correct_spare_request_official_id(
        command_id=new_uuid4(),
        spare_request_id=request_id,
        base_revision=2,
        sr7="SR0000123",
        action="assign",
    )
    assert assigned["spare_request_id"] == request_id
    assert assigned["official_sr7"] == "SR0000123"
    assert assigned["state"] == "submitted"
    assert assigned["revision"] == 3

    assert InventoryAttentionQueryService(factory).spare_request_response_attention(
        spare_request_id=request_id,
        as_of_utc=1_700_400_000 + 200_000,
    ) is None

    corrected = service.assign_or_correct_spare_request_official_id(
        command_id=new_uuid4(),
        spare_request_id=request_id,
        base_revision=3,
        sr7="SR7654321",
        action="correct",
        reason_code="provider corrected official request identifier",
    )
    assert corrected["spare_request_id"] == request_id
    assert corrected["official_sr7"] == "SR7654321"
    assert corrected["revision"] == 4

    with ReadSnapshot(factory) as snapshot:
        aliases = snapshot.connection.execute(
            "SELECT sr7,alias_kind FROM spare_request_identifier_aliases "
            "WHERE spare_request_id=? ORDER BY sr7",
            (request_id,),
        ).fetchall()
        assert {(str(row[0]), str(row[1])) for row in aliases} == {
            ("SR0000123", "former"),
            ("SR7654321", "current"),
        }
        events = snapshot.connection.execute(
            "SELECT event_kind,prior_sr7,new_sr7 FROM spare_request_identifier_events "
            "WHERE spare_request_id=? ORDER BY recorded_at_utc,identifier_event_id",
            (request_id,),
        ).fetchall()
        assert {(str(row[0]), row[1], str(row[2])) for row in events} == {
            ("assign", None, "SR0000123"),
            ("correct", "SR0000123", "SR7654321"),
        }
        assert snapshot.connection.execute(
            "SELECT COUNT(*) FROM spare_request_lifecycle_events "
            "WHERE spare_request_id=? AND event_kind='acknowledgement_accepted'",
            (request_id,),
        ).fetchone()[0] == 1
        projection = snapshot.connection.execute(
            "SELECT lifecycle_state,current_sr7,current_submission_snapshot_id,"
            "response_warning_start_utc,revision "
            "FROM spare_request_current_projection WHERE spare_request_id=?",
            (request_id,),
        ).fetchone()
        assert tuple(projection) == (
            "acknowledged",
            "SR7654321",
            original_snapshot_id,
            None,
            4,
        )
        assert snapshot.connection.execute(
            "SELECT snapshot_hash FROM spare_request_submission_snapshots "
            "WHERE submission_snapshot_id=?",
            (original_snapshot_id,),
        ).fetchone()[0] == original_snapshot_hash


def test_t023_current_and_former_sr7_aliases_are_globally_non_reusable(
    initialized_database,
) -> None:
    (
        factory,
        _sr_a,
        _need_a,
        _requester_a,
        _receiver_a,
        _location_a,
        service_a,
        created_a,
    ) = _request_fixture(
        initialized_database,
        official_sr="97100011",
        suffix="T023-A",
    )
    (
        _factory_b,
        _sr_b,
        _need_b,
        _requester_b,
        _receiver_b,
        _location_b,
        service_b,
        created_b,
    ) = _request_fixture(
        initialized_database,
        official_sr="97100012",
        suffix="T023-B",
    )
    request_a = str(created_a["spare_request_id"])
    request_b = str(created_b["spare_request_id"])

    service_a.assign_or_correct_spare_request_official_id(
        command_id=new_uuid4(),
        spare_request_id=request_a,
        base_revision=1,
        sr7="SR1234567",
        action="assign",
    )
    with pytest.raises(SomaError) as current_conflict:
        service_b.assign_or_correct_spare_request_official_id(
            command_id=new_uuid4(),
            spare_request_id=request_b,
            base_revision=1,
            sr7="SR1234567",
            action="assign",
        )
    assert current_conflict.value.code == "SR7_CONFLICT"

    service_a.assign_or_correct_spare_request_official_id(
        command_id=new_uuid4(),
        spare_request_id=request_a,
        base_revision=2,
        sr7="SR2345678",
        action="correct",
        reason_code="provider correction",
    )
    with pytest.raises(SomaError) as former_conflict:
        service_b.assign_or_correct_spare_request_official_id(
            command_id=new_uuid4(),
            spare_request_id=request_b,
            base_revision=1,
            sr7="SR1234567",
            action="assign",
        )
    assert former_conflict.value.code == "SR7_CONFLICT"

    with ReadSnapshot(factory) as snapshot:
        assert snapshot.connection.execute(
            "SELECT COUNT(*) FROM spare_request_identifier_aliases WHERE sr7='SR1234567'"
        ).fetchone()[0] == 1
        assert snapshot.connection.execute(
            "SELECT COUNT(*) FROM spare_request_identifier_aliases "
            "WHERE spare_request_id=?",
            (request_b,),
        ).fetchone()[0] == 0

