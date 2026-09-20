from __future__ import annotations

from soma.foundation.identifiers import new_uuid4, utc_epoch_seconds
from soma.foundation.persistence.uow import ReadSnapshot, UnitOfWork
from soma.inventory.domain.logistics import LogisticsParticipants
from soma.inventory.domain.requests import SpareRequestAllocationIntent
from soma.inventory.domain.rmas import RmaAuthorizationIntent
from soma.inventory.services.consequences_logistics import (
    InventoryConsequencesLogisticsService,
)
from soma.inventory.services.needs_stock import InventoryNeedsStockService
from soma.inventory.services.requests_rma import InventoryRequestsRmaService
from soma.inventory.queries.requests_rma import InventoryRequestsQueryService
from soma.reference.application.contact_service import ContactReferenceService
from soma.tickets.device_references import DeviceReferenceService
from soma.tickets.service_requests import ServiceRequestService


def _factory(initialized_database):
    database_path, factory_builder = initialized_database
    return factory_builder(database_path)


def _link_sr_device(factory, service_request_id: str, device_reference_id: str) -> None:
    command_id = new_uuid4()
    now = utc_epoch_seconds()
    with UnitOfWork(factory) as uow:
        uow.connection.execute(
            "INSERT INTO command_receipts("
            "command_id,command_type,request_hash,target_type,target_id,committed_at_utc,"
            "result_type,result_id"
            ") VALUES (?,?,?,?,?,?,?,?)",
            (
                command_id,
                "TestLinkInventoryLogisticsDevice",
                "a" * 64,
                "service_request",
                service_request_id,
                now,
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
                service_request_id,
                device_reference_id,
                now,
                command_id,
            ),
        )


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
                f"Receipt Warehouse {suffix}",
                f"receipt warehouse {suffix}".lower(),
                f"{suffix} receipt address",
                now,
                now,
            ),
        )
    return location_id


def _rma_ready(
    initialized_database,
    *,
    official_sr: str,
    suffix: str,
    count: int,
    promised_bom: str,
):
    factory = _factory(initialized_database)
    sr = ServiceRequestService(factory).create_manual_service_request(
        command_id=new_uuid4(),
        official_sr_no=official_sr,
    )
    device = DeviceReferenceService(factory).create(
        command_id=new_uuid4(),
        operational_name=f"LOG-{suffix}",
    )
    _link_sr_device(factory, sr.service_request_id, device.device_reference_id)
    inventory = InventoryNeedsStockService(factory)
    need_id: str | None = None
    for ordinal in range(count):
        registered = inventory.register_device_part_unit(
            command_id=new_uuid4(),
            service_request_id=sr.service_request_id,
            device_reference_id=device.device_reference_id,
            bom_code=promised_bom,
            manufacturer_serial=f"{suffix}-FAULT-{ordinal:03d}",
            condition_token="faulty",
        )
        if need_id is None:
            need_id = next(
                ref.result_id
                for ref in registered.target_refs
                if ref.result_type == "spare_need"
            )
    assert need_id is not None

    contacts = ContactReferenceService(factory)
    requester = contacts.create_contact(
        command_id=new_uuid4(),
        name=f"Receipt Requester {suffix}",
    )
    receiver = contacts.create_contact(
        command_id=new_uuid4(),
        name=f"Receipt Receiver {suffix}",
    )
    location_id = _dispatch_location(factory, suffix)
    requests = InventoryRequestsRmaService(factory)
    created = requests.create_spare_request_draft(
        command_id=new_uuid4(),
        service_request_id=sr.service_request_id,
        requester_contact_id=requester.contact_id,
        allocations=(SpareRequestAllocationIntent(need_id, count),),
        mode="delivery",
        receiver_contact_id=receiver.contact_id,
        dispatch_location_id=location_id,
    )
    request_id = str(created["spare_request_id"])
    detail = InventoryRequestsQueryService(factory).get_spare_request(request_id)
    requests.accept_spare_request_submission(
        command_id=new_uuid4(),
        spare_request_id=request_id,
        base_revision=1,
        expected_draft_fingerprint=str(detail["input_fingerprint"]),
        effective_submission_at_utc=1_700_600_000,
    )
    requests.assign_or_correct_spare_request_official_id(
        command_id=new_uuid4(),
        spare_request_id=request_id,
        base_revision=2,
        sr7=f"SR{int(official_sr[-7:]):07d}",
        action="assign",
    )
    batch = requests.accept_rma_authorization_batch(
        command_id=new_uuid4(),
        spare_request_id=request_id,
        expected_request_revision=3,
        rows=tuple(
            RmaAuthorizationIntent(
                c10=f"C{5000 + ordinal:010d}",
                promised_bom_code=promised_bom,
            )
            for ordinal in range(count)
        ),
        accepted_at_utc=1_700_600_100,
    )
    return (
        factory,
        receiver,
        location_id,
        tuple(str(item["rma_id"]) for item in batch["created_rmas"]),
    )


def test_t032_receipt_creates_one_direct_unit_from_actual_facts_without_rewriting_promise(
    initialized_database,
) -> None:
    factory, receiver, location_id, rma_ids = _rma_ready(
        initialized_database,
        official_sr="97200001",
        suffix="T032",
        count=1,
        promised_bom="PROMISED-BOM",
    )
    rma_id = rma_ids[0]
    service = InventoryConsequencesLogisticsService(factory)
    command_id = new_uuid4()

    result = service.record_rma_inbound_receipt(
        command_id=command_id,
        rma_id=rma_id,
        actual_bom_code="ACTUAL-BOM",
        manufacturer_serial="ACTUAL-SERIAL-001",
        condition_token="new",
        effective_at_utc=1_700_600_200,
        dispatch_location_id=location_id,
        receiver_contact_id=receiver.contact_id,
        custody_text="received by local operations",
    )
    unit_id = next(
        ref.result_id
        for ref in result.target_refs
        if ref.result_type == "spare_part_unit"
    )
    logistics_event_id = next(
        ref.result_id
        for ref in result.target_refs
        if ref.result_type == "logistics_event"
    )

    replay = service.record_rma_inbound_receipt(
        command_id=command_id,
        rma_id=rma_id,
        actual_bom_code="ACTUAL-BOM",
        manufacturer_serial="ACTUAL-SERIAL-001",
        condition_token="new",
        effective_at_utc=1_700_600_200,
        dispatch_location_id=location_id,
        receiver_contact_id=receiver.contact_id,
        custody_text="received by local operations",
    )
    assert replay.replayed is True
    assert replay.target_refs == result.target_refs

    with ReadSnapshot(factory) as snapshot:
        promised = snapshot.connection.execute(
            "SELECT promised_bom_code FROM rmas WHERE rma_id=?",
            (rma_id,),
        ).fetchone()
        assert str(promised[0]) == "PROMISED-BOM"

        unit = snapshot.connection.execute(
            "SELECT local_tracking_id,bom_code,manufacturer_serial,creation_origin,origin_rma_id "
            "FROM spare_part_units WHERE spare_part_unit_id=?",
            (unit_id,),
        ).fetchone()
        assert tuple(unit) == (
            None,
            "ACTUAL-BOM",
            "ACTUAL-SERIAL-001",
            "direct_rma_receipt",
            rma_id,
        )
        assert snapshot.connection.execute(
            "SELECT COUNT(*) FROM spare_part_units WHERE origin_rma_id=?",
            (rma_id,),
        ).fetchone()[0] == 1
        direct = snapshot.connection.execute(
            "SELECT spare_part_unit_id,relationship_event_id "
            "FROM rma_direct_inbound_units WHERE rma_id=?",
            (rma_id,),
        ).fetchone()
        assert str(direct[0]) == unit_id
        assert snapshot.connection.execute(
            "SELECT event_kind FROM spare_part_lifecycle_events "
            "WHERE unit_event_id=?",
            (str(direct[1]),),
        ).fetchone()[0] == "received"

        logistics = snapshot.connection.execute(
            "SELECT event_kind,effective_at_utc FROM actual_logistics_events "
            "WHERE logistics_event_id=?",
            (logistics_event_id,),
        ).fetchone()
        assert tuple(logistics) == ("receipt", 1_700_600_200)
        assert snapshot.connection.execute(
            "SELECT COUNT(*) FROM logistics_rma_participants "
            "WHERE logistics_event_id=? AND rma_id=? AND active=1",
            (logistics_event_id, rma_id),
        ).fetchone()[0] == 1
        assert snapshot.connection.execute(
            "SELECT COUNT(*) FROM logistics_spare_unit_participants "
            "WHERE logistics_event_id=? AND spare_part_unit_id=? AND active=1",
            (logistics_event_id, unit_id),
        ).fetchone()[0] == 1

        lifecycle = snapshot.connection.execute(
            "SELECT state,direct_inbound_spare_part_unit_id,revision "
            "FROM rma_lifecycle_projection WHERE rma_id=?",
            (rma_id,),
        ).fetchone()
        assert tuple(lifecycle) == ("received", unit_id, 2)
        attention = snapshot.connection.execute(
            "SELECT attention_kind FROM inventory_attention_projection "
            "WHERE target_kind='rma' AND target_id=? "
            "AND attention_kind='receipt_bom_mismatch'",
            (rma_id,),
        ).fetchone()
        assert attention is not None


def test_t034_t035_shared_logistics_event_has_independently_correctable_participants(
    initialized_database,
) -> None:
    factory, receiver, location_id, rma_ids = _rma_ready(
        initialized_database,
        official_sr="97200002",
        suffix="T034",
        count=3,
        promised_bom="BOM-SHARED-LOGISTICS",
    )
    service = InventoryConsequencesLogisticsService(factory)
    unit_ids: list[str] = []
    for ordinal, rma_id in enumerate(rma_ids):
        received = service.record_rma_inbound_receipt(
            command_id=new_uuid4(),
            rma_id=rma_id,
            actual_bom_code="BOM-SHARED-LOGISTICS",
            manufacturer_serial=f"SHARED-{ordinal}",
            condition_token="new",
            effective_at_utc=1_700_610_000 + ordinal,
            dispatch_location_id=location_id,
            receiver_contact_id=receiver.contact_id,
        )
        unit_ids.append(
            next(
                ref.result_id
                for ref in received.target_refs
                if ref.result_type == "spare_part_unit"
            )
        )

    shared = service.record_actual_logistics_event(
        command_id=new_uuid4(),
        event_kind="dispatch",
        participants=LogisticsParticipants(
            rma_ids=tuple(rma_ids),
            spare_part_unit_ids=tuple(unit_ids),
        ),
        effective_at_utc=1_700_620_000,
        dispatch_location_id=location_id,
        receiver_contact_id=receiver.contact_id,
        custody_text="shared return dispatch",
    )
    event_id = next(
        ref.result_id
        for ref in shared.target_refs
        if ref.result_type == "logistics_event"
    )

    with ReadSnapshot(factory) as snapshot:
        assert snapshot.connection.execute(
            "SELECT COUNT(*) FROM actual_logistics_events WHERE logistics_event_id=?",
            (event_id,),
        ).fetchone()[0] == 1
        assert snapshot.connection.execute(
            "SELECT COUNT(*) FROM logistics_rma_participants "
            "WHERE logistics_event_id=? AND active=1",
            (event_id,),
        ).fetchone()[0] == 3
        assert snapshot.connection.execute(
            "SELECT COUNT(*) FROM logistics_spare_unit_participants "
            "WHERE logistics_event_id=? AND active=1",
            (event_id,),
        ).fetchone()[0] == 3
        selected = snapshot.connection.execute(
            "SELECT logistics_spare_participant_id FROM logistics_spare_unit_participants "
            "WHERE logistics_event_id=? ORDER BY logistics_spare_participant_id LIMIT 1",
            (event_id,),
        ).fetchone()[0]

    corrected = service.correct_logistics_participant(
        command_id=new_uuid4(),
        participant_id=str(selected),
        reason_code="participant was included in error",
    )
    assert corrected.outcome == "APPLIED"

    with ReadSnapshot(factory) as snapshot:
        event = snapshot.connection.execute(
            "SELECT event_kind,effective_at_utc,custody_text "
            "FROM actual_logistics_events WHERE logistics_event_id=?",
            (event_id,),
        ).fetchone()
        assert tuple(event) == (
            "dispatch",
            1_700_620_000,
            "shared return dispatch",
        )
        corrected_row = snapshot.connection.execute(
            "SELECT active,close_reason FROM logistics_spare_unit_participants "
            "WHERE logistics_spare_participant_id=?",
            (str(selected),),
        ).fetchone()
        assert tuple(corrected_row) == (0, "participant was included in error")
        assert snapshot.connection.execute(
            "SELECT COUNT(*) FROM logistics_spare_unit_participants "
            "WHERE logistics_event_id=? AND active=1",
            (event_id,),
        ).fetchone()[0] == 2
        assert snapshot.connection.execute(
            "SELECT COUNT(*) FROM logistics_rma_participants "
            "WHERE logistics_event_id=? AND active=1",
            (event_id,),
        ).fetchone()[0] == 3
        assert snapshot.connection.execute(
            "SELECT COUNT(*) FROM actual_logistics_events WHERE logistics_event_id=?",
            (event_id,),
        ).fetchone()[0] == 1
