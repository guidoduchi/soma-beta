from __future__ import annotations

import json

import pytest

from soma.foundation.errors import SomaError
from soma.foundation.identifiers import new_uuid4, utc_epoch_seconds
from soma.foundation.persistence.uow import ReadSnapshot, UnitOfWork
from soma.inventory.domain.consequences import (
    ExtractedSparePartIntent,
    PhysicalConsequenceIntent,
)
from soma.inventory.domain.fault_tags import (
    FaultTagMembershipIntent,
    WarehouseMembershipTarget,
)
from soma.inventory.domain.logistics import LogisticsParticipants
from soma.inventory.domain.requests import SpareRequestAllocationIntent
from soma.inventory.domain.rmas import RmaAuthorizationIntent
from soma.inventory.services.consequences_logistics import (
    InventoryConsequencesLogisticsService,
)
from soma.inventory.services.corrections_bulk import InventoryCorrectionsBulkService
from soma.inventory.services.fault_tags import InventoryFaultTagService
from soma.inventory.services.needs_stock import InventoryNeedsStockService
from soma.inventory.services.requests_rma import InventoryRequestsRmaService
from soma.inventory.queries.fault_tags import FaultTagQueryService
from soma.inventory.queries.requests_rma import InventoryRequestsQueryService
from soma.inventory.queries.previews import (
    InventoryBulkPreviewTarget,
    InventoryPreviewsQueryService,
)
from soma.inventory.queries.task_context import TaskInventoryContextQueryService
from soma.objectives_tasks import AcceptedTaskSchedule, TaskPlanningService
from soma.objectives_tasks.queries.execution_review import (
    TaskOutcomeCorrectionQueryService,
    TaskOutcomeReviewQueryService,
)
from soma.objectives_tasks.queries.tasks import TaskOperationalEvidenceReader
from soma.objectives_tasks.services.task_execution import TaskExecutionService
from soma.objectives_tasks.services.task_review import TaskReviewService
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
    c10_base: int = 5000,
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
                c10=f"C{c10_base + ordinal:010d}",
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


def _rma_operational_context(factory, rma_id: str) -> tuple[str, str | None]:
    with ReadSnapshot(factory) as snapshot:
        row = snapshot.connection.execute(
            "SELECT r.service_request_id,l.current_target_device_part_unit_id "
            "FROM rmas m JOIN spare_requests r ON r.spare_request_id=m.spare_request_id "
            "JOIN rma_lifecycle_projection l ON l.rma_id=m.rma_id WHERE m.rma_id=?",
            (rma_id,),
        ).fetchone()
    assert row is not None
    return str(row[0]), None if row[1] is None else str(row[1])


def _reviewed_completed_task(factory, service_request_id: str):
    created = TaskPlanningService(factory).create_local_task(
        command_id=new_uuid4(),
        local_task_name="Inventory physical consequence",
        service_request_ids=(service_request_id,),
        schedule=AcceptedTaskSchedule(
            start_utc=1_700_700_000,
            end_utc=1_700_703_600,
            scheduling_timezone_iana="America/Guayaquil",
        ),
    )
    execution = TaskExecutionService(factory)
    started = execution.start_task_execution(
        command_id=new_uuid4(),
        task_id=created.task_id,
        task_revision=created.revision,
        execution_revision=0,
        effective_start_utc=1_700_700_100,
    )
    ended = execution.end_task_execution(
        command_id=new_uuid4(),
        task_id=created.task_id,
        task_revision=started.revision,
        execution_revision=1,
        effective_end_utc=1_700_700_200,
    )
    preview = TaskOutcomeReviewQueryService(factory).preview(
        task_id=created.task_id,
        task_revision=ended.revision,
        execution_revision=2,
        outcome_revision=0,
        current_outcome_event_id=None,
        outcome="completed",
        reason_category=None,
    )
    assert preview.eligible is True
    reviewed = TaskReviewService(factory).review_task_outcome(
        command_id=new_uuid4(),
        task_id=created.task_id,
        task_revision=ended.revision,
        execution_revision=2,
        outcome_revision=0,
        current_outcome_event_id=None,
        outcome="completed",
        reason_category=None,
        outcome_review_fingerprint=preview.outcome_review_fingerprint,
    )
    with ReadSnapshot(factory) as snapshot:
        fingerprint = TaskOperationalEvidenceReader.review_fingerprint(
            snapshot.connection,
            created.task_id,
        )
    return created.task_id, reviewed, fingerprint


def _receive_rma_unit(
    factory,
    *,
    receiver,
    location_id: str,
    rma_id: str,
    bom: str,
    serial: str,
) -> str:
    received = InventoryConsequencesLogisticsService(factory).record_rma_inbound_receipt(
        command_id=new_uuid4(),
        rma_id=rma_id,
        actual_bom_code=bom,
        manufacturer_serial=serial,
        condition_token="new",
        effective_at_utc=1_700_690_000,
        dispatch_location_id=location_id,
        receiver_contact_id=receiver.contact_id,
    )
    return next(
        ref.result_id
        for ref in received.target_refs
        if ref.result_type == "spare_part_unit"
    )


def test_t036_successful_replacement_installs_spare_removes_target_and_selects_removed_return(
    initialized_database,
) -> None:
    factory, receiver, location_id, rma_ids = _rma_ready(
        initialized_database,
        official_sr="97200003",
        suffix="T036",
        count=1,
        promised_bom="BOM-REPLACE",
    )
    rma_id = rma_ids[0]
    service_request_id, target_id = _rma_operational_context(factory, rma_id)
    assert target_id is not None
    inbound_id = _receive_rma_unit(
        factory,
        receiver=receiver,
        location_id=location_id,
        rma_id=rma_id,
        bom="BOM-REPLACE",
        serial="T036-INBOUND",
    )
    task_id, reviewed, fingerprint = _reviewed_completed_task(
        factory,
        service_request_id,
    )
    InventoryNeedsStockService(factory).reserve_spare_part_unit_for_task(
        command_id=new_uuid4(),
        task_id=task_id,
        spare_part_unit_id=inbound_id,
        unit_revision=2,
        task_revision=reviewed.revision,
    )

    result = InventoryConsequencesLogisticsService(
        factory
    ).accept_inventory_physical_consequence(
        command_id=new_uuid4(),
        task_id=task_id,
        task_review_fingerprint=fingerprint,
        target_device_part_unit_id=target_id,
        rma_id=rma_id,
        intent=PhysicalConsequenceIntent(
            physical_disposition="installed_used",
            installed_spare_part_unit_id=inbound_id,
            removed_device_part_unit_id=target_id,
            inbound_spare_part_unit_id=inbound_id,
            effective_at_utc=1_700_700_300,
        ),
    )
    consequence_id = next(
        ref.result_id
        for ref in result.target_refs
        if ref.result_type == "inventory_physical_consequence"
    )

    with ReadSnapshot(factory) as snapshot:
        assert snapshot.connection.execute(
            "SELECT physical_disposition,installed_spare_part_unit_id,"
            "removed_device_part_unit_id,revision FROM physical_consequence_current "
            "WHERE physical_consequence_id=?",
            (consequence_id,),
        ).fetchone() == ("installed_used", inbound_id, target_id, 1)
        assert snapshot.connection.execute(
            "SELECT disposition_token,active_task_allocation_id "
            "FROM spare_part_current_projection WHERE spare_part_unit_id=?",
            (inbound_id,),
        ).fetchone() == ("installed", None)
        assert snapshot.connection.execute(
            "SELECT condition_token FROM device_part_current_projection "
            "WHERE device_part_unit_id=?",
            (target_id,),
        ).fetchone()[0] == "removed"
        assert snapshot.connection.execute(
            "SELECT COUNT(*) FROM task_unit_allocation_current "
            "WHERE spare_part_unit_id=?",
            (inbound_id,),
        ).fetchone()[0] == 0
        obligation = snapshot.connection.execute(
            "SELECT obligation_state,device_part_unit_id,spare_part_unit_id,"
            "physical_consequence_id FROM rma_return_obligation_current WHERE rma_id=?",
            (rma_id,),
        ).fetchone()
        assert tuple(obligation) == ("open", target_id, None, consequence_id)


def test_t037_unused_replacement_returns_inbound_unit_without_installation(
    initialized_database,
) -> None:
    factory, receiver, location_id, rma_ids = _rma_ready(
        initialized_database,
        official_sr="97200004",
        suffix="T037",
        count=1,
        promised_bom="BOM-UNUSED",
    )
    rma_id = rma_ids[0]
    service_request_id, _target_id = _rma_operational_context(factory, rma_id)
    inbound_id = _receive_rma_unit(
        factory,
        receiver=receiver,
        location_id=location_id,
        rma_id=rma_id,
        bom="BOM-UNUSED",
        serial="T037-INBOUND",
    )
    task_id, _reviewed, fingerprint = _reviewed_completed_task(
        factory,
        service_request_id,
    )
    result = InventoryConsequencesLogisticsService(
        factory
    ).accept_inventory_physical_consequence(
        command_id=new_uuid4(),
        task_id=task_id,
        task_review_fingerprint=fingerprint,
        rma_id=rma_id,
        intent=PhysicalConsequenceIntent(
            physical_disposition="unused",
            inbound_spare_part_unit_id=inbound_id,
            effective_at_utc=1_700_710_000,
        ),
    )
    consequence_id = next(
        ref.result_id
        for ref in result.target_refs
        if ref.result_type == "inventory_physical_consequence"
    )
    with ReadSnapshot(factory) as snapshot:
        assert snapshot.connection.execute(
            "SELECT obligation_state,device_part_unit_id,spare_part_unit_id,"
            "physical_consequence_id FROM rma_return_obligation_current WHERE rma_id=?",
            (rma_id,),
        ).fetchone() == ("open", None, inbound_id, consequence_id)
        assert snapshot.connection.execute(
            "SELECT disposition_token FROM spare_part_current_projection "
            "WHERE spare_part_unit_id=?",
            (inbound_id,),
        ).fetchone()[0] == "available"
        assert snapshot.connection.execute(
            "SELECT COUNT(*) FROM spare_part_lifecycle_events "
            "WHERE spare_part_unit_id=? AND event_kind='installed'",
            (inbound_id,),
        ).fetchone()[0] == 0


@pytest.mark.parametrize(
    ("disposition", "expected_condition"),
    (
        ("inbound_faulty", "faulty"),
        ("incompatible", "incompatible"),
    ),
)
def test_t038_faulty_or_incompatible_inbound_preserves_physical_state_and_return_selection(
    initialized_database,
    disposition: str,
    expected_condition: str,
) -> None:
    factory, receiver, location_id, rma_ids = _rma_ready(
        initialized_database,
        official_sr="97200005",
        suffix=f"T038-{expected_condition}",
        count=1,
        promised_bom="BOM-T038",
    )
    rma_id = rma_ids[0]
    service_request_id, _target_id = _rma_operational_context(factory, rma_id)
    inbound_id = _receive_rma_unit(
        factory,
        receiver=receiver,
        location_id=location_id,
        rma_id=rma_id,
        bom="BOM-T038",
        serial=f"T038-{expected_condition}",
    )
    task_id, _reviewed, fingerprint = _reviewed_completed_task(
        factory,
        service_request_id,
    )
    InventoryConsequencesLogisticsService(factory).accept_inventory_physical_consequence(
        command_id=new_uuid4(),
        task_id=task_id,
        task_review_fingerprint=fingerprint,
        rma_id=rma_id,
        intent=PhysicalConsequenceIntent(
            physical_disposition=disposition,
            inbound_spare_part_unit_id=inbound_id,
            effective_at_utc=1_700_720_000,
        ),
    )
    with ReadSnapshot(factory) as snapshot:
        assert snapshot.connection.execute(
            "SELECT condition_token,disposition_token FROM spare_part_current_projection "
            "WHERE spare_part_unit_id=?",
            (inbound_id,),
        ).fetchone() == (expected_condition, "quarantined")
        assert snapshot.connection.execute(
            "SELECT obligation_state,spare_part_unit_id "
            "FROM rma_return_obligation_current WHERE rma_id=?",
            (rma_id,),
        ).fetchone() == ("open", inbound_id)


def test_t033_t039_dismantled_parent_stays_direct_return_and_extracted_children_get_new_identities(
    initialized_database,
) -> None:
    factory, receiver, location_id, rma_ids = _rma_ready(
        initialized_database,
        official_sr="97200006",
        suffix="T033",
        count=1,
        promised_bom="ASSEMBLY-BOM",
    )
    rma_id = rma_ids[0]
    service_request_id, _target_id = _rma_operational_context(factory, rma_id)
    parent_id = _receive_rma_unit(
        factory,
        receiver=receiver,
        location_id=location_id,
        rma_id=rma_id,
        bom="ASSEMBLY-BOM",
        serial="PARENT-ASSEMBLY",
    )
    with ReadSnapshot(factory) as snapshot:
        original_logistics_count = snapshot.connection.execute(
            "SELECT COUNT(*) FROM actual_logistics_events"
        ).fetchone()[0]

    task_id, _reviewed, fingerprint = _reviewed_completed_task(
        factory,
        service_request_id,
    )
    result = InventoryConsequencesLogisticsService(
        factory
    ).accept_inventory_physical_consequence(
        command_id=new_uuid4(),
        task_id=task_id,
        task_review_fingerprint=fingerprint,
        rma_id=rma_id,
        intent=PhysicalConsequenceIntent(
            physical_disposition="dismantled",
            parent_dismantled_unit_id=parent_id,
            extracted_units=(
                ExtractedSparePartIntent(
                    bom_code="CHILD-A",
                    manufacturer_serial="CHILD-A-SERIAL",
                    condition_token="new",
                ),
                ExtractedSparePartIntent(
                    bom_code="CHILD-B",
                    manufacturer_serial="CHILD-B-SERIAL",
                    condition_token="used",
                ),
            ),
            effective_at_utc=1_700_730_000,
        ),
    )
    child_ids = [
        ref.result_id
        for ref in result.target_refs
        if ref.result_type == "spare_part_unit" and ref.result_id != parent_id
    ]
    assert len(child_ids) == 2

    with ReadSnapshot(factory) as snapshot:
        direct = snapshot.connection.execute(
            "SELECT spare_part_unit_id FROM rma_direct_inbound_units WHERE rma_id=?",
            (rma_id,),
        ).fetchone()
        assert str(direct[0]) == parent_id
        assert snapshot.connection.execute(
            "SELECT COUNT(*) FROM actual_logistics_events"
        ).fetchone()[0] == original_logistics_count
        assert snapshot.connection.execute(
            "SELECT disposition_token FROM spare_part_current_projection "
            "WHERE spare_part_unit_id=?",
            (parent_id,),
        ).fetchone()[0] == "dismantled"
        children = snapshot.connection.execute(
            "SELECT spare_part_unit_id,local_tracking_id,creation_origin,origin_rma_id,"
            "parent_spare_part_unit_id FROM spare_part_units "
            "WHERE parent_spare_part_unit_id=? ORDER BY local_tracking_id",
            (parent_id,),
        ).fetchall()
        assert len(children) == 2
        assert {str(row[0]) for row in children} == set(child_ids)
        assert {str(row[1]) for row in children} == {
            "LSU-00000001",
            "LSU-00000002",
        }
        assert all(
            tuple(row[2:]) == ("extracted", rma_id, parent_id)
            for row in children
        )
        assert snapshot.connection.execute(
            "SELECT obligation_state,spare_part_unit_id "
            "FROM rma_return_obligation_current WHERE rma_id=?",
            (rma_id,),
        ).fetchone() == ("open", parent_id)
        assert snapshot.connection.execute(
            "SELECT COUNT(*) FROM logistics_spare_unit_participants "
            "WHERE spare_part_unit_id IN (?,?)",
            tuple(child_ids),
        ).fetchone()[0] == 0


def test_t040_local_stock_replacement_records_physical_truth_without_fake_rma(
    initialized_database,
) -> None:
    factory = _factory(initialized_database)
    sr = ServiceRequestService(factory).create_manual_service_request(
        command_id=new_uuid4(),
        official_sr_no="97200007",
    )
    device = DeviceReferenceService(factory).create(
        command_id=new_uuid4(),
        operational_name="LOCAL-T040",
    )
    _link_sr_device(factory, sr.service_request_id, device.device_reference_id)
    inventory = InventoryNeedsStockService(factory)
    fault = inventory.register_device_part_unit(
        command_id=new_uuid4(),
        service_request_id=sr.service_request_id,
        device_reference_id=device.device_reference_id,
        bom_code="LOCAL-BOM",
        manufacturer_serial="FAULT-T040",
        condition_token="faulty",
    )
    target_id = next(
        ref.result_id
        for ref in fault.target_refs
        if ref.result_type == "device_part_unit"
    )
    local = inventory.register_spare_part_unit(
        command_id=new_uuid4(),
        origin="manual_local",
        bom_code="LOCAL-BOM",
        manufacturer_serial="LOCAL-SPARE-T040",
        condition_token="new",
    )
    unit_id = next(
        ref.result_id
        for ref in local.target_refs
        if ref.result_type == "spare_part_unit"
    )
    task_id, reviewed, fingerprint = _reviewed_completed_task(
        factory,
        sr.service_request_id,
    )
    inventory.reserve_spare_part_unit_for_task(
        command_id=new_uuid4(),
        task_id=task_id,
        spare_part_unit_id=unit_id,
        unit_revision=1,
        task_revision=reviewed.revision,
    )
    InventoryConsequencesLogisticsService(factory).accept_inventory_physical_consequence(
        command_id=new_uuid4(),
        task_id=task_id,
        task_review_fingerprint=fingerprint,
        target_device_part_unit_id=target_id,
        intent=PhysicalConsequenceIntent(
            physical_disposition="installed_used",
            installed_spare_part_unit_id=unit_id,
            removed_device_part_unit_id=target_id,
            effective_at_utc=1_700_740_000,
        ),
    )
    with ReadSnapshot(factory) as snapshot:
        assert snapshot.connection.execute(
            "SELECT disposition_token FROM spare_part_current_projection "
            "WHERE spare_part_unit_id=?",
            (unit_id,),
        ).fetchone()[0] == "installed"
        assert snapshot.connection.execute(
            "SELECT condition_token FROM device_part_current_projection "
            "WHERE device_part_unit_id=?",
            (target_id,),
        ).fetchone()[0] == "removed"
        assert snapshot.connection.execute(
            "SELECT COUNT(*) FROM rmas"
        ).fetchone()[0] == 0
        assert snapshot.connection.execute(
            "SELECT COUNT(*) FROM rma_return_selection_events"
        ).fetchone()[0] == 0


def test_t041_task_outcome_correction_changes_operational_fingerprint_and_blocks_stale_consequence(
    initialized_database,
) -> None:
    factory = _factory(initialized_database)
    sr = ServiceRequestService(factory).create_manual_service_request(
        command_id=new_uuid4(),
        official_sr_no="97200008",
    )
    task_id, reviewed, original_fingerprint = _reviewed_completed_task(
        factory,
        sr.service_request_id,
    )
    with ReadSnapshot(factory) as snapshot:
        outcome_event_id = str(
            snapshot.connection.execute(
                "SELECT outcome_event_id FROM task_outcome_current WHERE task_id=?",
                (task_id,),
            ).fetchone()[0]
        )

    consequence = InventoryConsequencesLogisticsService(
        factory
    ).accept_inventory_physical_consequence(
        command_id=new_uuid4(),
        task_id=task_id,
        task_review_fingerprint=original_fingerprint,
        intent=PhysicalConsequenceIntent(
            physical_disposition="no_physical_change",
            effective_at_utc=1_700_750_000,
        ),
    )
    consequence_id = next(
        ref.result_id
        for ref in consequence.target_refs
        if ref.result_type == "inventory_physical_consequence"
    )

    preview = TaskOutcomeCorrectionQueryService(factory).preview(
        task_id=task_id,
        task_revision=reviewed.revision,
        execution_revision=2,
        current_outcome_revision=1,
        current_outcome_event_id=outcome_event_id,
        replacement_outcome="incomplete",
        reason_category="physical review changed",
    )
    corrected = TaskReviewService(factory).correct_task_outcome(
        command_id=new_uuid4(),
        task_id=task_id,
        task_revision=reviewed.revision,
        execution_revision=2,
        current_outcome_revision=1,
        current_outcome_event_id=outcome_event_id,
        replacement_outcome="incomplete",
        reason_category="physical review changed",
        correction_review_fingerprint=preview.correction_review_fingerprint,
    )
    assert corrected.outcome == "APPLIED"

    with ReadSnapshot(factory) as snapshot:
        current_fingerprint = TaskOperationalEvidenceReader.review_fingerprint(
            snapshot.connection,
            task_id,
        )
        stored = snapshot.connection.execute(
            "SELECT task_review_fingerprint FROM physical_consequence_current "
            "WHERE physical_consequence_id=?",
            (consequence_id,),
        ).fetchone()[0]
    assert current_fingerprint != original_fingerprint
    assert str(stored) == original_fingerprint
    task_context = TaskInventoryContextQueryService(factory).get(task_id)
    stale_consequence = next(
        item
        for item in task_context["physical_consequences"]
        if item["physical_consequence_id"] == consequence_id
    )
    assert stale_consequence["requires_rereview"] is True
    assert (
        task_context["task_operational"]["review_fingerprint"]
        == current_fingerprint
    )

    attempted_command = new_uuid4()
    with pytest.raises(SomaError) as stale:
        InventoryConsequencesLogisticsService(
            factory
        ).accept_inventory_physical_consequence(
            command_id=attempted_command,
            task_id=task_id,
            task_review_fingerprint=original_fingerprint,
            intent=PhysicalConsequenceIntent(
                physical_disposition="no_physical_change",
                effective_at_utc=1_700_750_100,
            ),
        )
    assert stale.value.code == "TASK_REVIEW_STALE"
    with ReadSnapshot(factory) as snapshot:
        assert snapshot.connection.execute(
            "SELECT COUNT(*) FROM command_receipts WHERE command_id=?",
            (attempted_command,),
        ).fetchone()[0] == 0
        assert snapshot.connection.execute(
            "SELECT COUNT(*) FROM inventory_physical_consequences WHERE task_id=?",
            (task_id,),
        ).fetchone()[0] == 1


def _open_return_obligation(
    initialized_database,
    *,
    official_sr: str,
    suffix: str,
    promised_bom: str,
    c10_base: int,
):
    factory, receiver, location_id, rma_ids = _rma_ready(
        initialized_database,
        official_sr=official_sr,
        suffix=suffix,
        count=1,
        promised_bom=promised_bom,
        c10_base=c10_base,
    )
    rma_id = rma_ids[0]
    service_request_id, _target_id = _rma_operational_context(factory, rma_id)
    inbound_id = _receive_rma_unit(
        factory,
        receiver=receiver,
        location_id=location_id,
        rma_id=rma_id,
        bom=promised_bom,
        serial=f"{suffix}-RETURN",
    )
    task_id, _reviewed, fingerprint = _reviewed_completed_task(
        factory,
        service_request_id,
    )
    consequence = InventoryConsequencesLogisticsService(
        factory
    ).accept_inventory_physical_consequence(
        command_id=new_uuid4(),
        task_id=task_id,
        task_review_fingerprint=fingerprint,
        rma_id=rma_id,
        intent=PhysicalConsequenceIntent(
            physical_disposition="unused",
            inbound_spare_part_unit_id=inbound_id,
            effective_at_utc=1_700_800_000,
        ),
    )
    consequence_id = next(
        ref.result_id
        for ref in consequence.target_refs
        if ref.result_type == "inventory_physical_consequence"
    )
    return factory, receiver, location_id, rma_id, inbound_id, consequence_id


def test_t042_fault_tag_draft_allocates_nonreusable_identity_and_allows_zero_members(
    initialized_database,
) -> None:
    factory = _factory(initialized_database)
    created = InventoryFaultTagService(factory).create_fault_tag_draft(
        command_id=new_uuid4(),
        return_method="non_pickup",
    )
    assert created["tracking_handle"] == "FT-00000001"
    assert created["state"] == "draft"
    assert created["revision"] == 1
    assert created["members"] == []

    with ReadSnapshot(factory) as snapshot:
        assert snapshot.connection.execute(
            "SELECT event_kind FROM fault_tag_lifecycle_events WHERE fault_tag_id=?",
            (created["fault_tag_id"],),
        ).fetchone()[0] == "created"
        assert snapshot.connection.execute(
            "SELECT state,submitted_member_count,revision FROM fault_tag_current_projection "
            "WHERE fault_tag_id=?",
            (created["fault_tag_id"],),
        ).fetchone() == ("draft", 0, 1)


def test_t043_pickup_fault_tag_without_origin_is_blocked_at_submission(
    initialized_database,
) -> None:
    factory, _receiver, _location_id, rma_id, _unit_id, _consequence_id = (
        _open_return_obligation(
            initialized_database,
            official_sr="97200009",
            suffix="T043",
            promised_bom="BOM-T043",
            c10_base=5100,
        )
    )
    service = InventoryFaultTagService(factory)
    draft = service.create_fault_tag_draft(
        command_id=new_uuid4(),
        return_method="pickup",
        memberships=(
            FaultTagMembershipIntent(
                rma_id=rma_id,
                return_reason="return unused replacement",
            ),
        ),
    )
    attempted = new_uuid4()
    with pytest.raises(SomaError) as missing_origin:
        service.accept_fault_tag_submission(
            command_id=attempted,
            fault_tag_id=str(draft["fault_tag_id"]),
            base_revision=int(draft["revision"]),
            expected_draft_fingerprint=str(draft["input_fingerprint"]),
            effective_submission_at_utc=1_700_810_000,
        )
    assert missing_origin.value.code == "FAULT_TAG_PICKUP_ORIGIN_REQUIRED"
    with ReadSnapshot(factory) as snapshot:
        assert snapshot.connection.execute(
            "SELECT COUNT(*) FROM command_receipts WHERE command_id=?",
            (attempted,),
        ).fetchone()[0] == 0
        assert snapshot.connection.execute(
            "SELECT state FROM fault_tag_current_projection WHERE fault_tag_id=?",
            (draft["fault_tag_id"],),
        ).fetchone()[0] == "draft"


def test_t044_fault_tag_draft_accepts_open_obligations_across_different_service_requests(
    initialized_database,
) -> None:
    first = _open_return_obligation(
        initialized_database,
        official_sr="97200010",
        suffix="T044-A",
        promised_bom="BOM-T044-A",
        c10_base=5200,
    )
    second = _open_return_obligation(
        initialized_database,
        official_sr="97200011",
        suffix="T044-B",
        promised_bom="BOM-T044-B",
        c10_base=5300,
    )
    factory = first[0]
    draft = InventoryFaultTagService(factory).create_fault_tag_draft(
        command_id=new_uuid4(),
        return_method="non_pickup",
        memberships=(
            FaultTagMembershipIntent(
                rma_id=first[3],
                return_reason="first independent obligation",
            ),
            FaultTagMembershipIntent(
                rma_id=second[3],
                return_reason="second independent obligation",
            ),
        ),
    )
    assert len(draft["members"]) == 2
    assert {item["rma_id"] for item in draft["members"]} == {first[3], second[3]}
    assert len({item["fault_tag_membership_id"] for item in draft["members"]}) == 2
    assert {item["physical_consequence_id"] for item in draft["members"]} == {
        first[5],
        second[5],
    }


def test_t045_second_submission_cannot_claim_already_active_rma_obligation(
    initialized_database,
) -> None:
    factory, _receiver, _location_id, rma_id, _unit_id, _consequence_id = (
        _open_return_obligation(
            initialized_database,
            official_sr="97200012",
            suffix="T045",
            promised_bom="BOM-T045",
            c10_base=5400,
        )
    )
    service = InventoryFaultTagService(factory)
    first = service.create_fault_tag_draft(
        command_id=new_uuid4(),
        return_method="non_pickup",
        memberships=(FaultTagMembershipIntent(rma_id, "first submission"),),
    )
    second = service.create_fault_tag_draft(
        command_id=new_uuid4(),
        return_method="non_pickup",
        memberships=(FaultTagMembershipIntent(rma_id, "competing submission"),),
    )
    service.accept_fault_tag_submission(
        command_id=new_uuid4(),
        fault_tag_id=str(first["fault_tag_id"]),
        base_revision=int(first["revision"]),
        expected_draft_fingerprint=str(first["input_fingerprint"]),
        effective_submission_at_utc=1_700_820_000,
    )

    attempted = new_uuid4()
    with pytest.raises(SomaError) as conflict:
        service.accept_fault_tag_submission(
            command_id=attempted,
            fault_tag_id=str(second["fault_tag_id"]),
            base_revision=int(second["revision"]),
            expected_draft_fingerprint=str(second["input_fingerprint"]),
            effective_submission_at_utc=1_700_820_100,
        )
    assert conflict.value.code == "FAULT_TAG_MEMBERSHIP_CONFLICT"
    with ReadSnapshot(factory) as snapshot:
        assert snapshot.connection.execute(
            "SELECT COUNT(*) FROM command_receipts WHERE command_id=?",
            (attempted,),
        ).fetchone()[0] == 0
        assert snapshot.connection.execute(
            "SELECT state FROM fault_tag_current_projection WHERE fault_tag_id=?",
            (second["fault_tag_id"],),
        ).fetchone()[0] == "draft"


def test_t046_fault_tag_submission_snapshots_survive_later_master_changes_and_replay(
    initialized_database,
) -> None:
    factory, receiver, location_id, rma_id, unit_id, consequence_id = (
        _open_return_obligation(
            initialized_database,
            official_sr="97200013",
            suffix="T046",
            promised_bom="BOM-T046",
            c10_base=5500,
        )
    )
    service = InventoryFaultTagService(factory)
    draft = service.create_fault_tag_draft(
        command_id=new_uuid4(),
        return_method="pickup",
        pickup_dispatch_location_id=location_id,
        pickup_contact_id=receiver.contact_id,
        pickup_instructions="collect from original dispatch point",
        memberships=(
            FaultTagMembershipIntent(
                rma_id=rma_id,
                return_reason="return for warehouse review",
            ),
        ),
    )
    command_id = new_uuid4()
    submitted = service.accept_fault_tag_submission(
        command_id=command_id,
        fault_tag_id=str(draft["fault_tag_id"]),
        base_revision=int(draft["revision"]),
        expected_draft_fingerprint=str(draft["input_fingerprint"]),
        effective_submission_at_utc=1_700_830_000,
    )
    replay = service.accept_fault_tag_submission(
        command_id=command_id,
        fault_tag_id=str(draft["fault_tag_id"]),
        base_revision=int(draft["revision"]),
        expected_draft_fingerprint=str(draft["input_fingerprint"]),
        effective_submission_at_utc=1_700_830_000,
    )
    assert replay == submitted

    with ReadSnapshot(factory) as snapshot:
        tag_snapshot = snapshot.connection.execute(
            "SELECT fault_tag_submission_snapshot_id,pickup_location_name_snapshot,"
            "pickup_location_address_snapshot,snapshot_hash "
            "FROM fault_tag_submission_snapshots WHERE fault_tag_id=?",
            (draft["fault_tag_id"],),
        ).fetchone()
        member_snapshot = snapshot.connection.execute(
            "SELECT display_snapshot_json FROM fault_tag_membership_submission_snapshots "
            "WHERE fault_tag_submission_snapshot_id=?",
            (str(tag_snapshot[0]),),
        ).fetchone()
        display_before = json.loads(str(member_snapshot[0]))
        tag_before = tuple(tag_snapshot)

    InventoryRequestsRmaService(factory).correct_rma_official_id(
        command_id=new_uuid4(),
        rma_id=rma_id,
        current_c10="C0000005500",
        new_c10="C0000005599",
        reason_code="provider corrected identifier",
    )
    with UnitOfWork(factory) as uow:
        uow.connection.execute(
            "UPDATE dispatch_locations SET name=?,standalone_address_text=?,revision=revision+1,"
            "updated_at_utc=? WHERE dispatch_location_id=?",
            (
                "Changed Pickup Name",
                "Changed pickup address",
                utc_epoch_seconds(),
                location_id,
            ),
        )

    with ReadSnapshot(factory) as snapshot:
        tag_after = snapshot.connection.execute(
            "SELECT fault_tag_submission_snapshot_id,pickup_location_name_snapshot,"
            "pickup_location_address_snapshot,snapshot_hash "
            "FROM fault_tag_submission_snapshots WHERE fault_tag_id=?",
            (draft["fault_tag_id"],),
        ).fetchone()
        display_after = json.loads(
            str(
                snapshot.connection.execute(
                    "SELECT display_snapshot_json FROM fault_tag_membership_submission_snapshots "
                    "WHERE fault_tag_submission_snapshot_id=?",
                    (str(tag_after[0]),),
                ).fetchone()[0]
            )
        )
        assert tuple(tag_after) == tag_before
        assert display_after == display_before
        assert display_after["current_c10"] == "C0000005500"
        assert display_after["unit_id"] == unit_id
        assert display_after["physical_consequence_id"] == consequence_id
        assert snapshot.connection.execute(
            "SELECT a.c10 FROM rma_identifier_aliases a "
            "WHERE a.rma_id=? AND a.alias_kind='current'",
            (rma_id,),
        ).fetchone()[0] == "C0000005599"
        assert snapshot.connection.execute(
            "SELECT name,standalone_address_text FROM dispatch_locations "
            "WHERE dispatch_location_id=?",
            (location_id,),
        ).fetchone() == ("Changed Pickup Name", "Changed pickup address")


def _submitted_fault_tag(
    factory,
    *,
    rma_id: str,
    return_method: str = "non_pickup",
    pickup_dispatch_location_id: str | None = None,
    pickup_contact_id: str | None = None,
):
    service = InventoryFaultTagService(factory)
    draft = service.create_fault_tag_draft(
        command_id=new_uuid4(),
        return_method=return_method,
        pickup_dispatch_location_id=pickup_dispatch_location_id,
        pickup_contact_id=pickup_contact_id,
        memberships=(
            FaultTagMembershipIntent(
                rma_id=rma_id,
                return_reason="return for warehouse review",
            ),
        ),
    )
    submitted = service.accept_fault_tag_submission(
        command_id=new_uuid4(),
        fault_tag_id=str(draft["fault_tag_id"]),
        base_revision=int(draft["revision"]),
        expected_draft_fingerprint=str(draft["input_fingerprint"]),
        effective_submission_at_utc=1_700_840_000,
    )
    with ReadSnapshot(factory) as snapshot:
        snapshot_row = snapshot.connection.execute(
            "SELECT submission_event_id,fault_tag_submission_snapshot_id "
            "FROM fault_tag_submission_snapshots WHERE fault_tag_id=? "
            "ORDER BY recorded_at_utc,fault_tag_submission_snapshot_id DESC LIMIT 1",
            (draft["fault_tag_id"],),
        ).fetchone()
    return draft, submitted, str(snapshot_row[0]), str(snapshot_row[1])


def test_t047_submitted_fault_tag_rejects_direct_draft_edit_or_membership_remove(
    initialized_database,
) -> None:
    factory, _receiver, _location_id, rma_id, _unit_id, _consequence_id = (
        _open_return_obligation(
            initialized_database,
            official_sr="97200014",
            suffix="T047",
            promised_bom="BOM-T047",
            c10_base=5600,
        )
    )
    draft, submitted, _event_id, _snapshot_id = _submitted_fault_tag(
        factory,
        rma_id=rma_id,
    )
    membership_id = str(submitted["members"][0]["fault_tag_membership_id"])
    attempted = new_uuid4()
    with pytest.raises(SomaError) as blocked:
        InventoryFaultTagService(factory).update_fault_tag_draft(
            command_id=attempted,
            fault_tag_id=str(draft["fault_tag_id"]),
            base_revision=int(submitted["revision"]),
            expected_draft_fingerprint=str(submitted["input_fingerprint"]),
            return_method="non_pickup",
            remove_membership_ids=(membership_id,),
        )
    assert blocked.value.code == "FAULT_TAG_NOT_DRAFT"
    with ReadSnapshot(factory) as snapshot:
        assert snapshot.connection.execute(
            "SELECT COUNT(*) FROM command_receipts WHERE command_id=?",
            (attempted,),
        ).fetchone()[0] == 0
        assert snapshot.connection.execute(
            "SELECT state,active_submitted FROM fault_tag_membership_current "
            "WHERE fault_tag_membership_id=?",
            (membership_id,),
        ).fetchone() == ("submitted_awaiting_receipt", 1)


def test_t048_false_fault_tag_submission_restores_same_tag_to_draft_preserving_s1(
    initialized_database,
) -> None:
    factory, _receiver, _location_id, rma_id, _unit_id, _consequence_id = (
        _open_return_obligation(
            initialized_database,
            official_sr="97200015",
            suffix="T048",
            promised_bom="BOM-T048",
            c10_base=5700,
        )
    )
    draft, submitted, submission_event_id, snapshot_id = _submitted_fault_tag(
        factory,
        rma_id=rma_id,
    )
    membership_id = str(submitted["members"][0]["fault_tag_membership_id"])
    corrected = InventoryFaultTagService(factory).correct_false_fault_tag_submission(
        command_id=new_uuid4(),
        fault_tag_id=str(draft["fault_tag_id"]),
        submission_event_id=submission_event_id,
        reason_code="submission was recorded but never externally sent",
        confirmed_no_real_send=True,
    )
    assert corrected["state"] == "draft"
    assert corrected["fault_tag_id"] == draft["fault_tag_id"]

    with ReadSnapshot(factory) as snapshot:
        tag = snapshot.connection.execute(
            "SELECT state,current_submission_snapshot_id,revision "
            "FROM fault_tag_current_projection WHERE fault_tag_id=?",
            (draft["fault_tag_id"],),
        ).fetchone()
        assert tuple(tag) == ("draft", None, 3)
        assert snapshot.connection.execute(
            "SELECT COUNT(*) FROM fault_tag_submission_snapshots "
            "WHERE fault_tag_submission_snapshot_id=?",
            (snapshot_id,),
        ).fetchone()[0] == 1
        assert snapshot.connection.execute(
            "SELECT event_kind,target_event_id FROM fault_tag_lifecycle_events "
            "WHERE fault_tag_id=? AND event_kind='submission_corrected_false'",
            (draft["fault_tag_id"],),
        ).fetchone() == ("submission_corrected_false", submission_event_id)
        assert snapshot.connection.execute(
            "SELECT state,active_submitted,revision FROM fault_tag_membership_current "
            "WHERE fault_tag_membership_id=?",
            (membership_id,),
        ).fetchone() == ("draft", 0, 3)
        assert snapshot.connection.execute(
            "SELECT COUNT(*) FROM fault_tag_membership_submission_snapshots "
            "WHERE fault_tag_membership_id=?",
            (membership_id,),
        ).fetchone()[0] == 1
        assert snapshot.connection.execute(
            "SELECT state,active_fault_tag_membership_id,return_obligation_open "
            "FROM rma_lifecycle_projection WHERE rma_id=?",
            (rma_id,),
        ).fetchone() == ("return_open", None, 1)


def test_rs003_false_corrected_fault_tag_can_resubmit_same_membership_without_erasing_s1(
    initialized_database,
) -> None:
    factory, _receiver, _location_id, rma_id, _unit_id, _consequence_id = (
        _open_return_obligation(
            initialized_database,
            official_sr="97200016",
            suffix="RS003",
            promised_bom="BOM-RS003",
            c10_base=5800,
        )
    )
    service = InventoryFaultTagService(factory)
    draft, _submitted, submission_event_id, first_snapshot_id = _submitted_fault_tag(
        factory,
        rma_id=rma_id,
    )
    corrected = service.correct_false_fault_tag_submission(
        command_id=new_uuid4(),
        fault_tag_id=str(draft["fault_tag_id"]),
        submission_event_id=submission_event_id,
        reason_code="first send did not occur",
        confirmed_no_real_send=True,
    )
    second = service.accept_fault_tag_submission(
        command_id=new_uuid4(),
        fault_tag_id=str(draft["fault_tag_id"]),
        base_revision=int(corrected["revision"]),
        expected_draft_fingerprint=str(corrected["input_fingerprint"]),
        effective_submission_at_utc=1_700_841_000,
    )
    assert second["state"] == "submitted"

    with ReadSnapshot(factory) as snapshot:
        snapshots = snapshot.connection.execute(
            "SELECT fault_tag_submission_snapshot_id FROM fault_tag_submission_snapshots "
            "WHERE fault_tag_id=? ORDER BY recorded_at_utc,fault_tag_submission_snapshot_id",
            (draft["fault_tag_id"],),
        ).fetchall()
        assert len(snapshots) == 2
        assert first_snapshot_id in {str(row[0]) for row in snapshots}
        member_id = str(second["members"][0]["fault_tag_membership_id"])
        assert snapshot.connection.execute(
            "SELECT COUNT(*) FROM fault_tag_membership_submission_snapshots "
            "WHERE fault_tag_membership_id=?",
            (member_id,),
        ).fetchone()[0] == 2
        current_snapshot = snapshot.connection.execute(
            "SELECT current_submission_snapshot_id FROM fault_tag_current_projection "
            "WHERE fault_tag_id=?",
            (draft["fault_tag_id"],),
        ).fetchone()[0]
        assert str(current_snapshot) != first_snapshot_id


def test_rs004_false_corrected_fault_tag_s2_freezes_only_changed_current_memberships(
    initialized_database,
) -> None:
    first = _open_return_obligation(
        initialized_database,
        official_sr="97200017",
        suffix="RS004-A",
        promised_bom="BOM-RS004-A",
        c10_base=5900,
    )
    second = _open_return_obligation(
        initialized_database,
        official_sr="97200018",
        suffix="RS004-B",
        promised_bom="BOM-RS004-B",
        c10_base=6000,
    )
    factory = first[0]
    service = InventoryFaultTagService(factory)
    draft, submitted, submission_event_id, first_snapshot_id = _submitted_fault_tag(
        factory,
        rma_id=first[3],
    )
    first_membership_id = str(submitted["members"][0]["fault_tag_membership_id"])
    corrected = service.correct_false_fault_tag_submission(
        command_id=new_uuid4(),
        fault_tag_id=str(draft["fault_tag_id"]),
        submission_event_id=submission_event_id,
        reason_code="first send did not occur",
        confirmed_no_real_send=True,
    )
    updated = service.update_fault_tag_draft(
        command_id=new_uuid4(),
        fault_tag_id=str(draft["fault_tag_id"]),
        base_revision=int(corrected["revision"]),
        expected_draft_fingerprint=str(corrected["input_fingerprint"]),
        return_method="non_pickup",
        remove_membership_ids=(first_membership_id,),
        add_memberships=(
            FaultTagMembershipIntent(
                rma_id=second[3],
                return_reason="replacement current draft membership",
            ),
        ),
    )
    assert {item["rma_id"] for item in updated["members"]} == {second[3]}
    second_submission = service.accept_fault_tag_submission(
        command_id=new_uuid4(),
        fault_tag_id=str(draft["fault_tag_id"]),
        base_revision=int(updated["revision"]),
        expected_draft_fingerprint=str(updated["input_fingerprint"]),
        effective_submission_at_utc=1_700_842_000,
    )
    assert second_submission["state"] == "submitted"

    with ReadSnapshot(factory) as snapshot:
        snapshots = snapshot.connection.execute(
            "SELECT fault_tag_submission_snapshot_id FROM fault_tag_submission_snapshots "
            "WHERE fault_tag_id=? ORDER BY recorded_at_utc,fault_tag_submission_snapshot_id",
            (draft["fault_tag_id"],),
        ).fetchall()
        assert len(snapshots) == 2
        second_snapshot_id = next(
            str(row[0]) for row in snapshots if str(row[0]) != first_snapshot_id
        )
        s1_rmas = {
            str(row[0])
            for row in snapshot.connection.execute(
                "SELECT rma_id FROM fault_tag_membership_submission_snapshots "
                "WHERE fault_tag_submission_snapshot_id=?",
                (first_snapshot_id,),
            ).fetchall()
        }
        s2_rmas = {
            str(row[0])
            for row in snapshot.connection.execute(
                "SELECT rma_id FROM fault_tag_membership_submission_snapshots "
                "WHERE fault_tag_submission_snapshot_id=?",
                (second_snapshot_id,),
            ).fetchall()
        }
        assert s1_rmas == {first[3]}
        assert s2_rmas == {second[3]}
        assert snapshot.connection.execute(
            "SELECT state FROM fault_tag_membership_current "
            "WHERE fault_tag_membership_id=?",
            (first_membership_id,),
        ).fetchone()[0] == "cancelled"


def _submitted_fault_tag_for_rmas(factory, rma_ids: tuple[str, ...]):
    service = InventoryFaultTagService(factory)
    draft = service.create_fault_tag_draft(
        command_id=new_uuid4(),
        return_method="non_pickup",
        memberships=tuple(
            FaultTagMembershipIntent(
                rma_id=rma_id,
                return_reason=f"return obligation {ordinal}",
            )
            for ordinal, rma_id in enumerate(rma_ids, start=1)
        ),
    )
    submitted = service.accept_fault_tag_submission(
        command_id=new_uuid4(),
        fault_tag_id=str(draft["fault_tag_id"]),
        base_revision=int(draft["revision"]),
        expected_draft_fingerprint=str(draft["input_fingerprint"]),
        effective_submission_at_utc=1_700_850_000,
    )
    return draft, submitted


def _warehouse_target(member: dict[str, object]) -> WarehouseMembershipTarget:
    return WarehouseMembershipTarget(
        fault_tag_membership_id=str(member["fault_tag_membership_id"]),
        revision=int(member["revision"]),
    )


def _current_warehouse_target(factory, membership_id: str) -> WarehouseMembershipTarget:
    with ReadSnapshot(factory) as snapshot:
        row = snapshot.connection.execute(
            "SELECT revision FROM fault_tag_membership_current "
            "WHERE fault_tag_membership_id=?",
            (membership_id,),
        ).fetchone()
    assert row is not None
    return WarehouseMembershipTarget(membership_id, int(row[0]))


def test_t050_warehouse_receipt_advances_only_selected_members_and_keeps_obligations_open(
    initialized_database,
) -> None:
    first = _open_return_obligation(
        initialized_database,
        official_sr="97200019",
        suffix="T050-A",
        promised_bom="BOM-T050-A",
        c10_base=6100,
    )
    second = _open_return_obligation(
        initialized_database,
        official_sr="97200020",
        suffix="T050-B",
        promised_bom="BOM-T050-B",
        c10_base=6200,
    )
    factory = first[0]
    draft, submitted = _submitted_fault_tag_for_rmas(
        factory,
        (first[3], second[3]),
    )
    members = {str(item["rma_id"]): item for item in submitted["members"]}
    service = InventoryFaultTagService(factory)
    receipt = service.record_warehouse_receipt(
        command_id=new_uuid4(),
        targets=(_warehouse_target(members[first[3]]),),
        effective_at_utc=1_700_851_000,
    )
    assert receipt.outcome == "APPLIED"

    with ReadSnapshot(factory) as snapshot:
        first_member = str(members[first[3]]["fault_tag_membership_id"])
        second_member = str(members[second[3]]["fault_tag_membership_id"])
        assert snapshot.connection.execute(
            "SELECT state,active_submitted FROM fault_tag_membership_current "
            "WHERE fault_tag_membership_id=?",
            (first_member,),
        ).fetchone() == ("warehouse_received", 1)
        assert snapshot.connection.execute(
            "SELECT state,active_submitted FROM fault_tag_membership_current "
            "WHERE fault_tag_membership_id=?",
            (second_member,),
        ).fetchone() == ("submitted_awaiting_receipt", 1)
        assert snapshot.connection.execute(
            "SELECT obligation_state FROM rma_return_obligation_current WHERE rma_id=?",
            (first[3],),
        ).fetchone()[0] == "open"
        assert snapshot.connection.execute(
            "SELECT obligation_state FROM rma_return_obligation_current WHERE rma_id=?",
            (second[3],),
        ).fetchone()[0] == "open"
        tag = snapshot.connection.execute(
            "SELECT state,awaiting_receipt_count,awaiting_final_count "
            "FROM fault_tag_current_projection WHERE fault_tag_id=?",
            (draft["fault_tag_id"],),
        ).fetchone()
        assert tuple(tag) == ("in_warehouse_review", 1, 1)


def test_t051_warehouse_acceptance_closes_exact_obligation_and_leaves_sibling_unchanged(
    initialized_database,
) -> None:
    first = _open_return_obligation(
        initialized_database,
        official_sr="97200021",
        suffix="T051-A",
        promised_bom="BOM-T051-A",
        c10_base=6300,
    )
    second = _open_return_obligation(
        initialized_database,
        official_sr="97200022",
        suffix="T051-B",
        promised_bom="BOM-T051-B",
        c10_base=6400,
    )
    factory = first[0]
    _draft, submitted = _submitted_fault_tag_for_rmas(
        factory,
        (first[3], second[3]),
    )
    members = {str(item["rma_id"]): item for item in submitted["members"]}
    service = InventoryFaultTagService(factory)
    first_id = str(members[first[3]]["fault_tag_membership_id"])
    service.record_warehouse_receipt(
        command_id=new_uuid4(),
        targets=(_warehouse_target(members[first[3]]),),
        effective_at_utc=1_700_852_000,
    )
    final = service.record_warehouse_final_decision(
        command_id=new_uuid4(),
        targets=(_current_warehouse_target(factory, first_id),),
        decision="accepted",
        explicit_confirmation=True,
        effective_at_utc=1_700_852_100,
    )
    assert final.outcome == "APPLIED"

    with ReadSnapshot(factory) as snapshot:
        assert snapshot.connection.execute(
            "SELECT state,active_submitted FROM fault_tag_membership_current "
            "WHERE fault_tag_membership_id=?",
            (first_id,),
        ).fetchone() == ("accepted", 0)
        assert snapshot.connection.execute(
            "SELECT obligation_state FROM rma_return_obligation_current WHERE rma_id=?",
            (first[3],),
        ).fetchone()[0] == "closed_accepted"
        assert snapshot.connection.execute(
            "SELECT state,return_obligation_open,active_fault_tag_membership_id "
            "FROM rma_lifecycle_projection WHERE rma_id=?",
            (first[3],),
        ).fetchone() == ("closed_accepted", 0, None)
        assert snapshot.connection.execute(
            "SELECT obligation_state FROM rma_return_obligation_current WHERE rma_id=?",
            (second[3],),
        ).fetchone()[0] == "open"
        assert snapshot.connection.execute(
            "SELECT state FROM fault_tag_membership_current "
            "WHERE fault_tag_membership_id=?",
            (str(members[second[3]]["fault_tag_membership_id"]),),
        ).fetchone()[0] == "submitted_awaiting_receipt"


def test_t052_warehouse_rejection_preserves_open_obligation_and_surfaces_resend_attention(
    initialized_database,
) -> None:
    factory, _receiver, _location_id, rma_id, _unit_id, _consequence_id = (
        _open_return_obligation(
            initialized_database,
            official_sr="97200023",
            suffix="T052",
            promised_bom="BOM-T052",
            c10_base=6500,
        )
    )
    _draft, submitted = _submitted_fault_tag_for_rmas(factory, (rma_id,))
    member = submitted["members"][0]
    membership_id = str(member["fault_tag_membership_id"])
    service = InventoryFaultTagService(factory)
    service.record_warehouse_receipt(
        command_id=new_uuid4(),
        targets=(_warehouse_target(member),),
        effective_at_utc=1_700_853_000,
    )
    service.record_warehouse_final_decision(
        command_id=new_uuid4(),
        targets=(_current_warehouse_target(factory, membership_id),),
        decision="rejected",
        explicit_confirmation=True,
        reason_code="warehouse rejected returned unit",
        effective_at_utc=1_700_853_100,
    )

    with ReadSnapshot(factory) as snapshot:
        assert snapshot.connection.execute(
            "SELECT state,active_submitted FROM fault_tag_membership_current "
            "WHERE fault_tag_membership_id=?",
            (membership_id,),
        ).fetchone() == ("rejected", 0)
        obligation = snapshot.connection.execute(
            "SELECT obligation_state,revision FROM rma_return_obligation_current "
            "WHERE rma_id=?",
            (rma_id,),
        ).fetchone()
        assert obligation[0] == "open"
        assert int(obligation[1]) >= 3
        assert snapshot.connection.execute(
            "SELECT state,return_obligation_open,active_fault_tag_membership_id "
            "FROM rma_lifecycle_projection WHERE rma_id=?",
            (rma_id,),
        ).fetchone() == ("return_rejected", 1, None)
        assert snapshot.connection.execute(
            "SELECT COUNT(*) FROM inventory_attention_projection "
            "WHERE target_kind='rma' AND target_id=? "
            "AND attention_kind='warehouse_rejected_resend_required'",
            (rma_id,),
        ).fetchone()[0] == 1


def test_t054_mixed_final_decisions_reduce_tag_terminal_with_rejected(
    initialized_database,
) -> None:
    first = _open_return_obligation(
        initialized_database,
        official_sr="97200024",
        suffix="T054-A",
        promised_bom="BOM-T054-A",
        c10_base=6600,
    )
    second = _open_return_obligation(
        initialized_database,
        official_sr="97200025",
        suffix="T054-B",
        promised_bom="BOM-T054-B",
        c10_base=6700,
    )
    factory = first[0]
    draft, submitted = _submitted_fault_tag_for_rmas(
        factory,
        (first[3], second[3]),
    )
    members = {str(item["rma_id"]): item for item in submitted["members"]}
    service = InventoryFaultTagService(factory)
    service.record_warehouse_receipt(
        command_id=new_uuid4(),
        targets=tuple(_warehouse_target(item) for item in submitted["members"]),
        effective_at_utc=1_700_854_000,
    )
    service.record_warehouse_final_decision(
        command_id=new_uuid4(),
        targets=(
            _current_warehouse_target(
                factory,
                str(members[first[3]]["fault_tag_membership_id"]),
            ),
        ),
        decision="accepted",
        explicit_confirmation=True,
        effective_at_utc=1_700_854_100,
    )
    service.record_warehouse_final_decision(
        command_id=new_uuid4(),
        targets=(
            _current_warehouse_target(
                factory,
                str(members[second[3]]["fault_tag_membership_id"]),
            ),
        ),
        decision="rejected",
        explicit_confirmation=True,
        reason_code="warehouse rejected second unit",
        effective_at_utc=1_700_854_200,
    )

    with ReadSnapshot(factory) as snapshot:
        tag = snapshot.connection.execute(
            "SELECT state,awaiting_receipt_count,awaiting_final_count,"
            "accepted_count,rejected_count FROM fault_tag_current_projection "
            "WHERE fault_tag_id=?",
            (draft["fault_tag_id"],),
        ).fetchone()
        assert tuple(tag) == ("terminal_with_rejected", 0, 0, 1, 1)
        assert snapshot.connection.execute(
            "SELECT obligation_state FROM rma_return_obligation_current WHERE rma_id=?",
            (first[3],),
        ).fetchone()[0] == "closed_accepted"
        assert snapshot.connection.execute(
            "SELECT obligation_state FROM rma_return_obligation_current WHERE rma_id=?",
            (second[3],),
        ).fetchone()[0] == "open"


def test_t055_warehouse_final_proposal_without_explicit_confirmation_cannot_mutate_inventory(
    initialized_database,
) -> None:
    factory, _receiver, _location_id, rma_id, _unit_id, _consequence_id = (
        _open_return_obligation(
            initialized_database,
            official_sr="97200026",
            suffix="T055",
            promised_bom="BOM-T055",
            c10_base=6800,
        )
    )
    _draft, submitted = _submitted_fault_tag_for_rmas(factory, (rma_id,))
    member = submitted["members"][0]
    membership_id = str(member["fault_tag_membership_id"])
    service = InventoryFaultTagService(factory)
    service.record_warehouse_receipt(
        command_id=new_uuid4(),
        targets=(_warehouse_target(member),),
        effective_at_utc=1_700_855_000,
    )
    attempted = new_uuid4()
    target = _current_warehouse_target(factory, membership_id)
    with pytest.raises(SomaError) as confirmation:
        service.record_warehouse_final_decision(
            command_id=attempted,
            targets=(target,),
            decision="accepted",
            explicit_confirmation=False,
            effective_at_utc=1_700_855_100,
        )
    assert confirmation.value.code == "WAREHOUSE_FINAL_CONFIRMATION_REQUIRED"

    with ReadSnapshot(factory) as snapshot:
        assert snapshot.connection.execute(
            "SELECT COUNT(*) FROM command_receipts WHERE command_id=?",
            (attempted,),
        ).fetchone()[0] == 0
        assert snapshot.connection.execute(
            "SELECT state,revision FROM fault_tag_membership_current "
            "WHERE fault_tag_membership_id=?",
            (membership_id,),
        ).fetchone() == ("warehouse_received", target.revision)
        assert snapshot.connection.execute(
            "SELECT obligation_state FROM rma_return_obligation_current WHERE rma_id=?",
            (rma_id,),
        ).fetchone()[0] == "open"


def test_t056_manual_warehouse_receipt_and_final_decision_require_no_uploaded_evidence(
    initialized_database,
) -> None:
    factory, _receiver, _location_id, rma_id, _unit_id, _consequence_id = (
        _open_return_obligation(
            initialized_database,
            official_sr="97200027",
            suffix="T056",
            promised_bom="BOM-T056",
            c10_base=6900,
        )
    )
    _draft, submitted = _submitted_fault_tag_for_rmas(factory, (rma_id,))
    member = submitted["members"][0]
    membership_id = str(member["fault_tag_membership_id"])
    service = InventoryFaultTagService(factory)
    received = service.record_warehouse_receipt(
        command_id=new_uuid4(),
        targets=(_warehouse_target(member),),
        effective_at_utc=None,
        evidence_kind=None,
        evidence_id=None,
    )
    assert received.outcome == "APPLIED"
    accepted = service.record_warehouse_final_decision(
        command_id=new_uuid4(),
        targets=(_current_warehouse_target(factory, membership_id),),
        decision="accepted",
        explicit_confirmation=True,
        effective_at_utc=None,
        evidence_kind=None,
        evidence_id=None,
    )
    assert accepted.outcome == "APPLIED"
    with ReadSnapshot(factory) as snapshot:
        assert snapshot.connection.execute(
            "SELECT obligation_state FROM rma_return_obligation_current WHERE rma_id=?",
            (rma_id,),
        ).fetchone()[0] == "closed_accepted"


def test_t049_material_fault_tag_replacement_allocates_new_identity_and_linear_correction_edge(
    initialized_database,
) -> None:
    factory, _receiver, _location_id, rma_id, _unit_id, _consequence_id = (
        _open_return_obligation(
            initialized_database,
            official_sr="97200028",
            suffix="T049",
            promised_bom="BOM-T049",
            c10_base=7000,
        )
    )
    draft, submitted = _submitted_fault_tag_for_rmas(factory, (rma_id,))
    predecessor_id = str(draft["fault_tag_id"])
    predecessor_member_id = str(submitted["members"][0]["fault_tag_membership_id"])
    lineage = FaultTagQueryService(factory).lineage(predecessor_id)

    replacement = InventoryFaultTagService(factory).create_fault_tag_replacement(
        command_id=new_uuid4(),
        predecessor_fault_tag_id=predecessor_id,
        expected_predecessor_revision=int(lineage["projection_revision"]),
        expected_lineage_fingerprint=str(lineage["lineage_fingerprint"]),
        return_method="non_pickup",
        memberships=(
            FaultTagMembershipIntent(
                rma_id=rma_id,
                return_reason="corrected submitted return membership",
            ),
        ),
        reason_code="submitted membership required material correction",
    )
    successor_id = str(replacement["fault_tag_id"])
    assert successor_id != predecessor_id
    assert replacement["tracking_handle"] != draft["tracking_handle"]
    assert replacement["state"] == "draft"
    assert str(replacement["members"][0]["fault_tag_membership_id"]) != predecessor_member_id

    with ReadSnapshot(factory) as snapshot:
        assert snapshot.connection.execute(
            "SELECT state FROM fault_tag_current_projection WHERE fault_tag_id=?",
            (predecessor_id,),
        ).fetchone()[0] == "superseded"
        assert snapshot.connection.execute(
            "SELECT state,active_submitted FROM fault_tag_membership_current "
            "WHERE fault_tag_membership_id=?",
            (predecessor_member_id,),
        ).fetchone() == ("superseded", 0)
        edge = snapshot.connection.execute(
            "SELECT relation_type,predecessor_fault_tag_id,successor_fault_tag_id "
            "FROM fault_tag_lineage WHERE predecessor_fault_tag_id=? "
            "AND relation_type='corrects_replaces'",
            (predecessor_id,),
        ).fetchone()
        assert tuple(edge) == ("corrects_replaces", predecessor_id, successor_id)
        assert snapshot.connection.execute(
            "SELECT COUNT(*) FROM fault_tag_submission_snapshots WHERE fault_tag_id=?",
            (predecessor_id,),
        ).fetchone()[0] == 1
        assert snapshot.connection.execute(
            "SELECT state,active_fault_tag_membership_id,return_obligation_open "
            "FROM rma_lifecycle_projection WHERE rma_id=?",
            (rma_id,),
        ).fetchone() == ("return_open", None, 1)

    fresh = FaultTagQueryService(factory).lineage(predecessor_id)
    attempted = new_uuid4()
    with pytest.raises(SomaError) as branch:
        InventoryFaultTagService(factory).create_fault_tag_replacement(
            command_id=attempted,
            predecessor_fault_tag_id=predecessor_id,
            expected_predecessor_revision=int(fresh["projection_revision"]),
            expected_lineage_fingerprint=str(fresh["lineage_fingerprint"]),
            return_method="non_pickup",
            memberships=(
                FaultTagMembershipIntent(
                    rma_id=rma_id,
                    return_reason="invalid second correction branch",
                ),
            ),
            reason_code="would branch correction lineage",
        )
    assert branch.value.code == "REPLACEMENT_LINEAGE_CONFLICT"
    with ReadSnapshot(factory) as snapshot:
        assert snapshot.connection.execute(
            "SELECT COUNT(*) FROM command_receipts WHERE command_id=?",
            (attempted,),
        ).fetchone()[0] == 0


def test_t053_rejected_obligation_resend_creates_new_history_and_disallows_overlapping_scope(
    initialized_database,
) -> None:
    factory, _receiver, _location_id, rma_id, _unit_id, _consequence_id = (
        _open_return_obligation(
            initialized_database,
            official_sr="97200029",
            suffix="T053",
            promised_bom="BOM-T053",
            c10_base=7100,
        )
    )
    draft, submitted = _submitted_fault_tag_for_rmas(factory, (rma_id,))
    predecessor_id = str(draft["fault_tag_id"])
    member = submitted["members"][0]
    membership_id = str(member["fault_tag_membership_id"])
    service = InventoryFaultTagService(factory)
    service.record_warehouse_receipt(
        command_id=new_uuid4(),
        targets=(_warehouse_target(member),),
        effective_at_utc=1_700_856_000,
    )
    service.record_warehouse_final_decision(
        command_id=new_uuid4(),
        targets=(_current_warehouse_target(factory, membership_id),),
        decision="rejected",
        explicit_confirmation=True,
        reason_code="warehouse rejected original attempt",
        effective_at_utc=1_700_856_100,
    )
    predecessor_before = FaultTagQueryService(factory).get_fault_tag(predecessor_id)
    lineage = FaultTagQueryService(factory).lineage(predecessor_id)

    resend = service.create_fault_tag_resend(
        command_id=new_uuid4(),
        predecessor_fault_tag_id=predecessor_id,
        expected_lineage_fingerprint=str(lineage["lineage_fingerprint"]),
        return_method="non_pickup",
        memberships=(
            FaultTagMembershipIntent(
                rma_id=rma_id,
                return_reason="resend rejected return",
            ),
        ),
        reason_code="warehouse rejected prior return attempt",
    )
    resend_id = str(resend["fault_tag_id"])
    assert resend_id != predecessor_id
    assert resend["state"] == "draft"

    predecessor_after = FaultTagQueryService(factory).get_fault_tag(predecessor_id)
    assert predecessor_after == predecessor_before
    with ReadSnapshot(factory) as snapshot:
        edge = snapshot.connection.execute(
            "SELECT relation_type,predecessor_fault_tag_id,successor_fault_tag_id "
            "FROM fault_tag_lineage WHERE successor_fault_tag_id=?",
            (resend_id,),
        ).fetchone()
        assert tuple(edge) == ("resend_of", predecessor_id, resend_id)
        assert snapshot.connection.execute(
            "SELECT state FROM fault_tag_membership_current "
            "WHERE fault_tag_membership_id=?",
            (membership_id,),
        ).fetchone()[0] == "rejected"
        assert snapshot.connection.execute(
            "SELECT obligation_state FROM rma_return_obligation_current WHERE rma_id=?",
            (rma_id,),
        ).fetchone()[0] == "open"

    fresh = FaultTagQueryService(factory).lineage(predecessor_id)
    attempted = new_uuid4()
    with pytest.raises(SomaError) as overlap:
        service.create_fault_tag_resend(
            command_id=attempted,
            predecessor_fault_tag_id=predecessor_id,
            expected_lineage_fingerprint=str(fresh["lineage_fingerprint"]),
            return_method="non_pickup",
            memberships=(
                FaultTagMembershipIntent(
                    rma_id=rma_id,
                    return_reason="overlapping resend scope",
                ),
            ),
            reason_code="second resend would overlap unresolved scope",
        )
    assert overlap.value.code == "RESEND_NOT_ELIGIBLE"
    with ReadSnapshot(factory) as snapshot:
        assert snapshot.connection.execute(
            "SELECT COUNT(*) FROM command_receipts WHERE command_id=?",
            (attempted,),
        ).fetchone()[0] == 0


def test_t057_bulk_preview_partitions_incompatible_target_without_silent_skip(
    initialized_database,
) -> None:
    first = _open_return_obligation(
        initialized_database,
        official_sr="97200028",
        suffix="T057-A",
        promised_bom="BOM-T057-A",
        c10_base=7000,
    )
    second = _open_return_obligation(
        initialized_database,
        official_sr="97200029",
        suffix="T057-B",
        promised_bom="BOM-T057-B",
        c10_base=7100,
    )
    factory = first[0]
    _draft, submitted = _submitted_fault_tag_for_rmas(
        factory,
        (first[3], second[3]),
    )
    members = {str(item["rma_id"]): item for item in submitted["members"]}
    service = InventoryFaultTagService(factory)
    first_member_id = str(members[first[3]]["fault_tag_membership_id"])
    service.record_warehouse_receipt(
        command_id=new_uuid4(),
        targets=(_warehouse_target(members[first[3]]),),
        effective_at_utc=1_700_860_000,
    )
    first_current = _current_warehouse_target(factory, first_member_id)
    second_target = _warehouse_target(members[second[3]])

    preview = InventoryPreviewsQueryService(factory).preview_bulk_action(
        action_kind="warehouse_receipt",
        targets=(
            InventoryBulkPreviewTarget(
                first_current.fault_tag_membership_id,
                first_current.revision,
            ),
            InventoryBulkPreviewTarget(
                second_target.fault_tag_membership_id,
                second_target.revision,
            ),
        ),
    )
    partition = {
        str(item["fault_tag_membership_id"]): item
        for item in preview["partitions"]
    }
    assert preview["selected_count"] == 2
    assert preview["eligible_count"] == 1
    assert partition[first_member_id]["classification"] == "incompatible"
    assert partition[first_member_id]["reason"] == "requires_submitted_awaiting_receipt"
    assert (
        partition[second_target.fault_tag_membership_id]["classification"]
        == "eligible"
    )
    assert preview["eligible_targets"] == [
        {
            "fault_tag_membership_id": second_target.fault_tag_membership_id,
            "expected_revision": second_target.revision,
        }
    ]


def test_t058_bulk_commit_aborts_all_targets_when_one_changes_after_preview(
    initialized_database,
) -> None:
    first = _open_return_obligation(
        initialized_database,
        official_sr="97200030",
        suffix="T058-A",
        promised_bom="BOM-T058-A",
        c10_base=7200,
    )
    second = _open_return_obligation(
        initialized_database,
        official_sr="97200031",
        suffix="T058-B",
        promised_bom="BOM-T058-B",
        c10_base=7300,
    )
    factory = first[0]
    _draft, submitted = _submitted_fault_tag_for_rmas(
        factory,
        (first[3], second[3]),
    )
    members = tuple(submitted["members"])
    targets = tuple(_warehouse_target(item) for item in members)
    preview_targets = tuple(
        InventoryBulkPreviewTarget(item.fault_tag_membership_id, item.revision)
        for item in targets
    )
    preview = InventoryPreviewsQueryService(factory).preview_bulk_action(
        action_kind="warehouse_receipt",
        targets=preview_targets,
        effective_at_utc=1_700_861_000,
    )
    assert preview["eligible_count"] == 2

    InventoryFaultTagService(factory).record_warehouse_receipt(
        command_id=new_uuid4(),
        targets=(targets[0],),
        effective_at_utc=1_700_861_050,
    )
    second_id = targets[1].fault_tag_membership_id
    attempted = new_uuid4()
    with pytest.raises(SomaError) as stale:
        InventoryCorrectionsBulkService(factory).accept_inventory_bulk_action(
            command_id=attempted,
            action_kind="warehouse_receipt",
            targets=targets,
            preview_fingerprint=str(preview["input_fingerprint"]),
            effective_at_utc=1_700_861_000,
        )
    assert stale.value.code in {"INV_STALE", "BULK_INCOMPATIBLE"}

    with ReadSnapshot(factory) as snapshot:
        assert snapshot.connection.execute(
            "SELECT state,revision FROM fault_tag_membership_current "
            "WHERE fault_tag_membership_id=?",
            (second_id,),
        ).fetchone() == ("submitted_awaiting_receipt", targets[1].revision)
        assert snapshot.connection.execute(
            "SELECT COUNT(*) FROM inventory_lifecycle_batches "
            "WHERE command_id=?",
            (attempted,),
        ).fetchone()[0] == 0
        assert snapshot.connection.execute(
            "SELECT COUNT(*) FROM command_receipts WHERE command_id=?",
            (attempted,),
        ).fetchone()[0] == 0


def test_t059_successful_bulk_batch_keeps_members_independently_addressable_afterward(
    initialized_database,
) -> None:
    first = _open_return_obligation(
        initialized_database,
        official_sr="97200032",
        suffix="T059-A",
        promised_bom="BOM-T059-A",
        c10_base=7400,
    )
    second = _open_return_obligation(
        initialized_database,
        official_sr="97200033",
        suffix="T059-B",
        promised_bom="BOM-T059-B",
        c10_base=7500,
    )
    factory = first[0]
    _draft, submitted = _submitted_fault_tag_for_rmas(
        factory,
        (first[3], second[3]),
    )
    targets = tuple(_warehouse_target(item) for item in submitted["members"])
    preview = InventoryPreviewsQueryService(factory).preview_bulk_action(
        action_kind="warehouse_receipt",
        targets=tuple(
            InventoryBulkPreviewTarget(item.fault_tag_membership_id, item.revision)
            for item in targets
        ),
        effective_at_utc=1_700_862_000,
    )
    bulk = InventoryCorrectionsBulkService(factory).accept_inventory_bulk_action(
        command_id=new_uuid4(),
        action_kind="warehouse_receipt",
        targets=targets,
        preview_fingerprint=str(preview["input_fingerprint"]),
        effective_at_utc=1_700_862_000,
    )
    batch_ids = [
        ref.result_id for ref in bulk.target_refs if ref.result_type == "inventory_batch"
    ]
    assert len(batch_ids) == 1
    batch_id = batch_ids[0]
    member_ids = [item.fault_tag_membership_id for item in targets]

    with ReadSnapshot(factory) as snapshot:
        before = {
            str(row[0]): (str(row[1]), int(row[2]), str(row[3]))
            for row in snapshot.connection.execute(
                "SELECT fault_tag_membership_id,state,revision,last_event_id "
                "FROM fault_tag_membership_current "
                "WHERE fault_tag_membership_id IN (?,?)",
                tuple(member_ids),
            ).fetchall()
        }
        assert all(value[0] == "warehouse_received" for value in before.values())
        assert snapshot.connection.execute(
            "SELECT target_count FROM inventory_lifecycle_batches "
            "WHERE inventory_batch_id=?",
            (batch_id,),
        ).fetchone()[0] == 2

    first_target = _current_warehouse_target(factory, member_ids[0])
    InventoryFaultTagService(factory).record_warehouse_final_decision(
        command_id=new_uuid4(),
        targets=(first_target,),
        decision="accepted",
        explicit_confirmation=True,
        effective_at_utc=1_700_862_100,
    )

    with ReadSnapshot(factory) as snapshot:
        first_after = snapshot.connection.execute(
            "SELECT state,revision FROM fault_tag_membership_current "
            "WHERE fault_tag_membership_id=?",
            (member_ids[0],),
        ).fetchone()
        second_after = snapshot.connection.execute(
            "SELECT state,revision,last_event_id FROM fault_tag_membership_current "
            "WHERE fault_tag_membership_id=?",
            (member_ids[1],),
        ).fetchone()
        assert first_after[0] == "accepted"
        assert tuple(second_after) == before[member_ids[1]]
        assert snapshot.connection.execute(
            "SELECT target_count FROM inventory_lifecycle_batches "
            "WHERE inventory_batch_id=?",
            (batch_id,),
        ).fetchone()[0] == 2


def test_t060_untouched_fault_tag_hard_delete_removes_only_draft_rows_and_never_reuses_ft(
    initialized_database,
) -> None:
    factory, _receiver, _location_id, rma_id, unit_id, _consequence_id = (
        _open_return_obligation(
            initialized_database,
            official_sr="97200034",
            suffix="T060",
            promised_bom="BOM-T060",
            c10_base=7600,
        )
    )
    fault_tags = InventoryFaultTagService(factory)
    draft = fault_tags.create_fault_tag_draft(
        command_id=new_uuid4(),
        return_method="non_pickup",
        memberships=(
            FaultTagMembershipIntent(
                rma_id=rma_id,
                return_reason="untouched draft only",
            ),
        ),
    )
    preview = InventoryPreviewsQueryService(factory).preview_hard_delete(
        target_kind="fault_tag",
        target_id=str(draft["fault_tag_id"]),
    )
    assert preview["classification"] == "CLEAR"
    assert preview["reviewed_revision"] == 1
    deleted = InventoryCorrectionsBulkService(factory).hard_delete_untouched_fault_tag(
        command_id=new_uuid4(),
        fault_tag_id=str(draft["fault_tag_id"]),
        reviewed_revision=int(preview["reviewed_revision"]),
        eligibility_fingerprint=str(preview["eligibility_fingerprint"]),
        deliberate_confirmation=True,
    )
    assert deleted.outcome == "APPLIED"
    assert any(
        ref.result_type == "hard_delete_evidence"
        for ref in deleted.target_refs
    )

    with ReadSnapshot(factory) as snapshot:
        assert snapshot.connection.execute(
            "SELECT COUNT(*) FROM fault_tags WHERE fault_tag_id=?",
            (draft["fault_tag_id"],),
        ).fetchone()[0] == 0
        assert snapshot.connection.execute(
            "SELECT COUNT(*) FROM fault_tag_memberships WHERE fault_tag_id=?",
            (draft["fault_tag_id"],),
        ).fetchone()[0] == 0
        assert snapshot.connection.execute(
            "SELECT COUNT(*) FROM rmas WHERE rma_id=?",
            (rma_id,),
        ).fetchone()[0] == 1
        assert snapshot.connection.execute(
            "SELECT COUNT(*) FROM spare_part_units WHERE spare_part_unit_id=?",
            (unit_id,),
        ).fetchone()[0] == 1
        allocator = snapshot.connection.execute(
            "SELECT next_sequence FROM inventory_tracking_allocators "
            "WHERE allocator_kind='fault_tag'",
        ).fetchone()
        assert int(allocator[0]) == 2

    next_tag = fault_tags.create_fault_tag_draft(
        command_id=new_uuid4(),
        return_method="non_pickup",
    )
    assert next_tag["tracking_handle"] == "FT-00000002"


def test_t061_fault_tag_with_protected_submission_history_cannot_be_hard_deleted(
    initialized_database,
) -> None:
    factory, _receiver, _location_id, rma_id, _unit_id, _consequence_id = (
        _open_return_obligation(
            initialized_database,
            official_sr="97200035",
            suffix="T061",
            promised_bom="BOM-T061",
            c10_base=7700,
        )
    )
    draft, submitted, _event_id, snapshot_id = _submitted_fault_tag(
        factory,
        rma_id=rma_id,
    )
    preview = InventoryPreviewsQueryService(factory).preview_hard_delete(
        target_kind="fault_tag",
        target_id=str(draft["fault_tag_id"]),
    )
    assert preview["classification"] == "BLOCKED"
    assert "submission_history" in preview["reasons"]
    attempted = new_uuid4()
    with pytest.raises(SomaError) as blocked:
        InventoryCorrectionsBulkService(factory).hard_delete_untouched_fault_tag(
            command_id=attempted,
            fault_tag_id=str(draft["fault_tag_id"]),
            reviewed_revision=int(submitted["revision"]),
            eligibility_fingerprint=str(preview["eligibility_fingerprint"]),
            deliberate_confirmation=True,
        )
    assert blocked.value.code == "HARD_DELETE_BLOCKED"

    with ReadSnapshot(factory) as snapshot:
        assert snapshot.connection.execute(
            "SELECT COUNT(*) FROM command_receipts WHERE command_id=?",
            (attempted,),
        ).fetchone()[0] == 0
        assert snapshot.connection.execute(
            "SELECT COUNT(*) FROM fault_tags WHERE fault_tag_id=?",
            (draft["fault_tag_id"],),
        ).fetchone()[0] == 1
        assert snapshot.connection.execute(
            "SELECT COUNT(*) FROM fault_tag_submission_snapshots "
            "WHERE fault_tag_submission_snapshot_id=?",
            (snapshot_id,),
        ).fetchone()[0] == 1
