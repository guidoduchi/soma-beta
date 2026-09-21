from __future__ import annotations

import pytest

from soma.foundation.errors import SomaError
from soma.foundation.identifiers import new_uuid4
from soma.foundation.persistence.uow import ReadSnapshot, UnitOfWork
from soma.inventory.queries.stock_needs import InventoryNeedsQueryService
from soma.inventory.services.needs_stock import InventoryNeedsStockService
from soma.objectives_tasks.services.task_planning import TaskPlanningService
from soma.reference.application.contact_service import ContactReferenceService
from soma.tickets.device_references import DeviceReferenceService
from soma.tickets.service_requests import ServiceRequestService


def _factory(initialized_database):
    database_path, factory_builder = initialized_database
    return factory_builder(database_path)


def _link_sr_device(factory, service_request_id: str, device_reference_id: str) -> None:
    command_id = new_uuid4()
    with UnitOfWork(factory) as uow:
        uow.connection.execute(
            "INSERT INTO command_receipts("
            "command_id,command_type,request_hash,target_type,target_id,committed_at_utc,"
            "result_type,result_id"
            ") VALUES (?,?,?,?,?,?,?,?)",
            (
                command_id,
                "TestLinkDeviceReference",
                "a" * 64,
                "service_request",
                service_request_id,
                1,
                None,
                None,
            ),
        )
        uow.connection.execute(
            "INSERT INTO sr_device_reference_links("
            "sr_device_reference_link_id,service_request_id,device_reference_id,link_state,"
            "opened_at_utc,closed_at_utc,opened_command_id,closed_command_id"
            ") VALUES (?,?,?,'active',1,NULL,?,NULL)",
            (new_uuid4(), service_request_id, device_reference_id, command_id),
        )


def _sr(factory, official: str):
    return ServiceRequestService(factory).create_manual_service_request(
        command_id=new_uuid4(),
        official_sr_no=official,
    )


def _device(factory, sr_id: str, label: str):
    device = DeviceReferenceService(factory).create(
        command_id=new_uuid4(),
        operational_name=label,
    )
    _link_sr_device(factory, sr_id, device.device_reference_id)
    return device


def _need_row(factory, sr_id: str, bom_key: str):
    with ReadSnapshot(factory) as snapshot:
        return snapshot.connection.execute(
            "SELECT n.spare_need_id,p.lifecycle_state,p.planned_quantity,"
            "p.contributor_count,p.revision "
            "FROM spare_need_active_keys k "
            "JOIN spare_needs n ON n.spare_need_id=k.spare_need_id "
            "JOIN spare_need_current_projection p ON p.spare_need_id=n.spare_need_id "
            "WHERE k.service_request_id=? AND k.bom_key=?",
            (sr_id, bom_key),
        ).fetchone()


def test_t001_sixty_faulty_same_sr_bom_aggregate_one_need(
    initialized_database,
) -> None:
    factory = _factory(initialized_database)
    sr = _sr(factory, "97000001")
    devices = [_device(factory, sr.service_request_id, f"NE-{i:02d}") for i in range(15)]
    service = InventoryNeedsStockService(factory)
    need_ids: set[str] = set()

    for ordinal in range(60):
        result = service.register_device_part_unit(
            command_id=new_uuid4(),
            service_request_id=sr.service_request_id,
            device_reference_id=devices[ordinal % 15].device_reference_id,
            bom_code="  ABC-123 / Main  ",
            manufacturer_serial=f"SER-{ordinal:04d}",
            condition_token="faulty",
        )
        need_ids.update(
            ref.result_id for ref in result.target_refs if ref.result_type == "spare_need"
        )

    assert len(need_ids) == 1
    with ReadSnapshot(factory) as snapshot:
        need_id = next(iter(need_ids))
        projection = snapshot.connection.execute(
            "SELECT lifecycle_state,planned_quantity,contributor_count,revision "
            "FROM spare_need_current_projection WHERE spare_need_id=?",
            (need_id,),
        ).fetchone()
        assert tuple(projection) == ("active", 1, 60, 60)
        assert snapshot.connection.execute(
            "SELECT COUNT(*) FROM spare_need_contributors "
            "WHERE spare_need_id=? AND active=1",
            (need_id,),
        ).fetchone()[0] == 60
        assert snapshot.connection.execute(
            "SELECT COUNT(*) FROM spare_needs "
            "WHERE service_request_id=?",
            (sr.service_request_id,),
        ).fetchone()[0] == 1
        assert snapshot.connection.execute(
            "SELECT COUNT(*) FROM device_part_units "
            "WHERE service_request_id=?",
            (sr.service_request_id,),
        ).fetchone()[0] == 60


def test_t002_same_bom_different_srs_never_cross_aggregate(
    initialized_database,
) -> None:
    factory = _factory(initialized_database)
    sr_a = _sr(factory, "97000002")
    sr_b = _sr(factory, "97000003")
    dev_a = _device(factory, sr_a.service_request_id, "NE-A")
    dev_b = _device(factory, sr_b.service_request_id, "NE-B")
    service = InventoryNeedsStockService(factory)

    a = service.register_device_part_unit(
        command_id=new_uuid4(),
        service_request_id=sr_a.service_request_id,
        device_reference_id=dev_a.device_reference_id,
        bom_code="BOM-X",
        condition_token="faulty",
    )
    b = service.register_device_part_unit(
        command_id=new_uuid4(),
        service_request_id=sr_b.service_request_id,
        device_reference_id=dev_b.device_reference_id,
        bom_code="BOM-X",
        condition_token="faulty",
    )
    need_a = next(ref.result_id for ref in a.target_refs if ref.result_type == "spare_need")
    need_b = next(ref.result_id for ref in b.target_refs if ref.result_type == "spare_need")
    assert need_a != need_b

    with ReadSnapshot(factory) as snapshot:
        rows = snapshot.connection.execute(
            "SELECT service_request_id,bom_key,spare_need_id "
            "FROM spare_need_active_keys ORDER BY service_request_id"
        ).fetchall()
        assert len(rows) == 2
        assert {str(row[0]) for row in rows} == {sr_a.service_request_id, sr_b.service_request_id}
        assert len({str(row[2]) for row in rows}) == 2


def test_t003_contributor_growth_never_overwrites_planned_quantity(
    initialized_database,
) -> None:
    factory = _factory(initialized_database)
    sr = _sr(factory, "97000004")
    dev_a = _device(factory, sr.service_request_id, "NE-C1")
    dev_b = _device(factory, sr.service_request_id, "NE-C2")
    service = InventoryNeedsStockService(factory)

    first = service.register_device_part_unit(
        command_id=new_uuid4(),
        service_request_id=sr.service_request_id,
        device_reference_id=dev_a.device_reference_id,
        bom_code="BOM-Q",
        condition_token="faulty",
    )
    need_id = next(ref.result_id for ref in first.target_refs if ref.result_type == "spare_need")
    changed = service.set_spare_need_planned_quantity(
        command_id=new_uuid4(),
        spare_need_id=need_id,
        base_revision=1,
        planned_quantity=7,
        reason_code="operator planning",
    )
    assert changed.outcome == "APPLIED"

    service.register_device_part_unit(
        command_id=new_uuid4(),
        service_request_id=sr.service_request_id,
        device_reference_id=dev_b.device_reference_id,
        bom_code="bom-q",
        condition_token="faulty",
    )

    with ReadSnapshot(factory) as snapshot:
        projection = snapshot.connection.execute(
            "SELECT planned_quantity,contributor_count,revision "
            "FROM spare_need_current_projection WHERE spare_need_id=?",
            (need_id,),
        ).fetchone()
        assert tuple(projection) == (7, 2, 3)


def test_need_lifecycle_releases_and_restores_active_key(
    initialized_database,
) -> None:
    factory = _factory(initialized_database)
    sr = _sr(factory, "97000005")
    dev = _device(factory, sr.service_request_id, "NE-LIFE")
    service = InventoryNeedsStockService(factory)
    created = service.register_device_part_unit(
        command_id=new_uuid4(),
        service_request_id=sr.service_request_id,
        device_reference_id=dev.device_reference_id,
        bom_code="BOM-LIFE",
        condition_token="faulty",
    )
    need_id = next(ref.result_id for ref in created.target_refs if ref.result_type == "spare_need")

    resolved = service.change_spare_need_lifecycle(
        command_id=new_uuid4(),
        spare_need_id=need_id,
        base_revision=1,
        action="resolve",
        reason_code="reviewed resolution",
    )
    assert resolved.outcome == "APPLIED"
    with ReadSnapshot(factory) as snapshot:
        assert snapshot.connection.execute(
            "SELECT COUNT(*) FROM spare_need_active_keys WHERE spare_need_id=?",
            (need_id,),
        ).fetchone()[0] == 0

    reactivated = service.change_spare_need_lifecycle(
        command_id=new_uuid4(),
        spare_need_id=need_id,
        base_revision=2,
        action="reactivate",
        reason_code="demand reopened",
    )
    assert reactivated.outcome == "APPLIED"
    with ReadSnapshot(factory) as snapshot:
        projection = snapshot.connection.execute(
            "SELECT lifecycle_state,revision FROM spare_need_current_projection "
            "WHERE spare_need_id=?",
            (need_id,),
        ).fetchone()
        assert tuple(projection) == ("active", 3)
        assert snapshot.connection.execute(
            "SELECT COUNT(*) FROM spare_need_active_keys WHERE spare_need_id=?",
            (need_id,),
        ).fetchone()[0] == 1
        history = snapshot.connection.execute(
            "SELECT event_kind FROM spare_need_lifecycle_events "
            "WHERE spare_need_id=? ORDER BY recorded_at_utc,need_event_id",
            (need_id,),
        ).fetchall()
        assert {str(row[0]) for row in history} == {"created", "resolved", "reactivated"}


def test_t012_duplicate_candidate_never_silently_merges_identity(
    initialized_database,
) -> None:
    factory = _factory(initialized_database)
    sr = _sr(factory, "97000006")
    dev = _device(factory, sr.service_request_id, "NE-DUP")
    service = InventoryNeedsStockService(factory)
    query = InventoryNeedsQueryService(factory)

    first = service.register_device_part_unit(
        command_id=new_uuid4(),
        service_request_id=sr.service_request_id,
        device_reference_id=dev.device_reference_id,
        bom_code="BÓM-77",
        manufacturer_serial=" Serial  001 ",
        condition_token="normal",
    )
    first_id = next(ref.result_id for ref in first.target_refs if ref.result_type == "device_part_unit")
    candidates = query.preview_device_part_duplicates(
        bom_code="BÓM-77",
        manufacturer_serial="serial 001",
    )
    assert [item.device_part_unit_id for item in candidates] == [first_id]

    second = service.register_device_part_unit(
        command_id=new_uuid4(),
        service_request_id=sr.service_request_id,
        device_reference_id=dev.device_reference_id,
        bom_code="BÓM-77",
        manufacturer_serial="SERIAL 001",
        condition_token="normal",
    )
    second_id = next(ref.result_id for ref in second.target_refs if ref.result_type == "device_part_unit")
    assert second_id != first_id
    candidates_after = query.preview_device_part_duplicates(
        bom_code="bóm-77",
        manufacturer_serial="serial 001",
    )
    assert {item.device_part_unit_id for item in candidates_after} == {first_id, second_id}


def test_register_device_part_replay_returns_original_identity_without_duplicates(
    initialized_database,
) -> None:
    factory = _factory(initialized_database)
    sr = _sr(factory, "97000007")
    dev = _device(factory, sr.service_request_id, "NE-REPLAY")
    service = InventoryNeedsStockService(factory)
    command_id = new_uuid4()

    first = service.register_device_part_unit(
        command_id=command_id,
        service_request_id=sr.service_request_id,
        device_reference_id=dev.device_reference_id,
        bom_code="BOM-R",
        manufacturer_serial="SER-R",
        condition_token="faulty",
    )
    replay = service.register_device_part_unit(
        command_id=command_id,
        service_request_id=sr.service_request_id,
        device_reference_id=dev.device_reference_id,
        bom_code="BOM-R",
        manufacturer_serial="SER-R",
        condition_token="faulty",
    )
    assert replay.replayed is True
    assert replay.target_refs == first.target_refs
    assert replay.revisions == first.revisions

    with ReadSnapshot(factory) as snapshot:
        assert snapshot.connection.execute(
            "SELECT COUNT(*) FROM device_part_units WHERE service_request_id=?",
            (sr.service_request_id,),
        ).fetchone()[0] == 1
        assert snapshot.connection.execute(
            "SELECT COUNT(*) FROM spare_need_contributors",
        ).fetchone()[0] == 1
        assert snapshot.connection.execute(
            "SELECT COUNT(*) FROM audit_events WHERE command_id=?",
            (command_id,),
        ).fetchone()[0] == 2



def test_t005_history_remove_blocked_by_nonterminal_spare_request(
    initialized_database,
) -> None:
    factory = _factory(initialized_database)
    sr = _sr(factory, "97000008")
    dev = _device(factory, sr.service_request_id, "NE-T005")
    service = InventoryNeedsStockService(factory)
    created = service.register_device_part_unit(
        command_id=new_uuid4(),
        service_request_id=sr.service_request_id,
        device_reference_id=dev.device_reference_id,
        bom_code="BOM-T005",
        condition_token="faulty",
    )
    need_id = next(
        ref.result_id for ref in created.target_refs if ref.result_type == "spare_need"
    )
    contact = ContactReferenceService(factory).create_contact(
        command_id=new_uuid4(),
        name="T005 Requester",
    )

    setup_command = new_uuid4()
    request_id = new_uuid4()
    allocation_id = new_uuid4()
    with UnitOfWork(factory) as uow:
        uow.connection.execute(
            "INSERT INTO command_receipts("
            "command_id,command_type,request_hash,target_type,target_id,committed_at_utc,"
            "result_type,result_id"
            ") VALUES (?,?,?,?,?,?,?,?)",
            (
                setup_command,
                "TestCreateSpareRequestDependency",
                "b" * 64,
                "spare_request",
                request_id,
                1,
                None,
                None,
            ),
        )
        uow.connection.execute(
            "INSERT INTO spare_requests("
            "spare_request_id,tracking_sequence,tracking_id,service_request_id,"
            "requester_contact_id,requester_context_json,creation_origin,created_at_utc,"
            "created_command_id"
            ") VALUES (?,?,?,?,?,'{}','soma_draft',1,?)",
            (
                request_id,
                99999999,
                "SPR-99999999",
                sr.service_request_id,
                contact.contact_id,
                setup_command,
            ),
        )
        uow.connection.execute(
            "INSERT INTO spare_request_need_allocations("
            "request_need_allocation_id,spare_request_id,spare_need_id,quantity,revision,"
            "active_draft,created_command_id,last_command_id"
            ") VALUES (?,?,?,1,1,1,?,?)",
            (allocation_id, request_id, need_id, setup_command, setup_command),
        )
        uow.connection.execute(
            "INSERT INTO spare_request_current_projection("
            "spare_request_id,lifecycle_state,current_sr7,current_submission_snapshot_id,"
            "submitted_quantity,authorized_rma_count,response_warning_start_utc,revision,"
            "input_fingerprint,last_command_id"
            ") VALUES (?,'draft',NULL,NULL,0,0,NULL,1,?,?)",
            (request_id, "c" * 64, setup_command),
        )

    resolved = service.change_spare_need_lifecycle(
        command_id=new_uuid4(),
        spare_need_id=need_id,
        base_revision=1,
        action="resolve",
        reason_code="prepare history removal",
    )
    assert resolved.outcome == "APPLIED"

    command_id = new_uuid4()
    with pytest.raises(SomaError) as blocked:
        service.change_spare_need_lifecycle(
            command_id=command_id,
            spare_need_id=need_id,
            base_revision=2,
            action="history_remove",
            reason_code="operator requested removal",
        )
    assert blocked.value.code == "NEED_DELETE_BLOCKED"

    with ReadSnapshot(factory) as snapshot:
        projection = snapshot.connection.execute(
            "SELECT lifecycle_state,revision FROM spare_need_current_projection "
            "WHERE spare_need_id=?",
            (need_id,),
        ).fetchone()
        assert tuple(projection) == ("resolved", 2)
        assert snapshot.connection.execute(
            "SELECT COUNT(*) FROM spare_need_active_keys WHERE spare_need_id=?",
            (need_id,),
        ).fetchone()[0] == 0
        assert snapshot.connection.execute(
            "SELECT COUNT(*) FROM command_receipts WHERE command_id=?",
            (command_id,),
        ).fetchone()[0] == 0


def test_spare_need_lifecycle_rejects_noncanonical_lateral_transition(
    initialized_database,
) -> None:
    factory = _factory(initialized_database)
    sr = _sr(factory, "97000018")
    dev = _device(factory, sr.service_request_id, "NE-NEED-LATERAL")
    service = InventoryNeedsStockService(factory)
    created = service.register_device_part_unit(
        command_id=new_uuid4(),
        service_request_id=sr.service_request_id,
        device_reference_id=dev.device_reference_id,
        bom_code="BOM-NEED-LATERAL",
        condition_token="faulty",
    )
    need_id = next(
        ref.result_id for ref in created.target_refs if ref.result_type == "spare_need"
    )
    service.change_spare_need_lifecycle(
        command_id=new_uuid4(),
        spare_need_id=need_id,
        base_revision=1,
        action="resolve",
        reason_code="resolved once",
    )

    command_id = new_uuid4()
    with pytest.raises(SomaError) as invalid:
        service.change_spare_need_lifecycle(
            command_id=command_id,
            spare_need_id=need_id,
            base_revision=2,
            action="cancel",
            reason_code="invalid lateral move",
        )
    assert invalid.value.code == "INV_STALE"

    with ReadSnapshot(factory) as snapshot:
        row = snapshot.connection.execute(
            "SELECT lifecycle_state,revision FROM spare_need_current_projection "
            "WHERE spare_need_id=?",
            (need_id,),
        ).fetchone()
        assert tuple(row) == ("resolved", 2)
        assert snapshot.connection.execute(
            "SELECT COUNT(*) FROM command_receipts WHERE command_id=?",
            (command_id,),
        ).fetchone()[0] == 0


def test_spare_need_history_remove_accepts_terminal_dependency_free_need(
    initialized_database,
) -> None:
    factory = _factory(initialized_database)
    sr = _sr(factory, "97000019")
    dev = _device(factory, sr.service_request_id, "NE-NEED-HISTORY")
    service = InventoryNeedsStockService(factory)
    created = service.register_device_part_unit(
        command_id=new_uuid4(),
        service_request_id=sr.service_request_id,
        device_reference_id=dev.device_reference_id,
        bom_code="BOM-NEED-HISTORY",
        condition_token="faulty",
    )
    need_id = next(
        ref.result_id for ref in created.target_refs if ref.result_type == "spare_need"
    )
    service.change_spare_need_lifecycle(
        command_id=new_uuid4(),
        spare_need_id=need_id,
        base_revision=1,
        action="cancel",
        reason_code="cancel demand",
    )
    removed = service.change_spare_need_lifecycle(
        command_id=new_uuid4(),
        spare_need_id=need_id,
        base_revision=2,
        action="history_remove",
        reason_code="remove terminal history",
    )
    assert removed.outcome == "APPLIED"

    with ReadSnapshot(factory) as snapshot:
        row = snapshot.connection.execute(
            "SELECT lifecycle_state,revision FROM spare_need_current_projection "
            "WHERE spare_need_id=?",
            (need_id,),
        ).fetchone()
        assert tuple(row) == ("removed", 3)
        events = snapshot.connection.execute(
            "SELECT event_kind FROM spare_need_lifecycle_events "
            "WHERE spare_need_id=? ORDER BY recorded_at_utc,need_event_id",
            (need_id,),
        ).fetchall()
        assert {str(row[0]) for row in events} == {
            "created",
            "cancelled",
            "history_removed",
        }
        assert snapshot.connection.execute(
            "SELECT COUNT(*) FROM spare_need_active_keys WHERE spare_need_id=?",
            (need_id,),
        ).fetchone()[0] == 0

def _spare_unit_projection(factory, spare_part_unit_id: str):
    with ReadSnapshot(factory) as snapshot:
        return snapshot.connection.execute(
            "SELECT u.local_tracking_id,u.bom_code,u.manufacturer_serial,"
            "p.condition_token,p.disposition_token,p.active_task_allocation_id,p.revision "
            "FROM spare_part_units u JOIN spare_part_current_projection p "
            "ON p.spare_part_unit_id=u.spare_part_unit_id "
            "WHERE u.spare_part_unit_id=?",
            (spare_part_unit_id,),
        ).fetchone()


def test_t011_manual_local_unit_allocates_lsu_and_preserves_duplicate_candidates(
    initialized_database,
) -> None:
    factory = _factory(initialized_database)
    service = InventoryNeedsStockService(factory)
    query = InventoryNeedsQueryService(factory)

    first = service.register_spare_part_unit(
        command_id=new_uuid4(),
        origin="manual_local",
        bom_code="  LOCAL-BOM-1 ",
        condition_token="new",
    )
    first_id = next(
        ref.result_id
        for ref in first.target_refs
        if ref.result_type == "spare_part_unit"
    )
    first_projection = _spare_unit_projection(factory, first_id)
    assert tuple(first_projection) == (
        "LSU-00000001",
        "LOCAL-BOM-1",
        None,
        "new",
        "available",
        None,
        1,
    )

    second = service.register_spare_part_unit(
        command_id=new_uuid4(),
        origin="manual_local",
        bom_code="Local-Bom-1",
        manufacturer_serial=" Serial-77 ",
        condition_token="used",
    )
    second_id = next(
        ref.result_id
        for ref in second.target_refs
        if ref.result_type == "spare_part_unit"
    )
    third = service.register_spare_part_unit(
        command_id=new_uuid4(),
        origin="manual_local",
        bom_code="LOCAL-BOM-1",
        manufacturer_serial="serial-77",
        condition_token="used",
    )
    third_id = next(
        ref.result_id
        for ref in third.target_refs
        if ref.result_type == "spare_part_unit"
    )
    assert second_id != third_id
    candidates = query.preview_spare_part_duplicates(
        bom_code=" local-bom-1 ",
        manufacturer_serial="SERIAL-77",
    )
    assert {item.spare_part_unit_id for item in candidates} == {
        second_id,
        third_id,
    }
    assert {item.local_tracking_id for item in candidates} == {
        "LSU-00000002",
        "LSU-00000003",
    }


def test_t007_stock_query_recommends_without_reserving(
    initialized_database,
) -> None:
    factory = _factory(initialized_database)
    sr = _sr(factory, "97000009")
    device = _device(factory, sr.service_request_id, "NE-STOCK")
    service = InventoryNeedsStockService(factory)
    query = InventoryNeedsQueryService(factory)

    need_result = service.register_device_part_unit(
        command_id=new_uuid4(),
        service_request_id=sr.service_request_id,
        device_reference_id=device.device_reference_id,
        bom_code="BOM-STOCK",
        condition_token="faulty",
    )
    need_id = next(
        ref.result_id for ref in need_result.target_refs if ref.result_type == "spare_need"
    )
    stock_result = service.register_spare_part_unit(
        command_id=new_uuid4(),
        origin="manual_local",
        bom_code="bom-stock",
        manufacturer_serial="SPARE-1",
        condition_token="new",
    )
    unit_id = next(
        ref.result_id
        for ref in stock_result.target_refs
        if ref.result_type == "spare_part_unit"
    )

    page = query.stock_eligibility(spare_need_id=need_id)
    exact = [
        item
        for item in page.items
        if item.spare_part_unit_id == unit_id
    ]
    assert len(exact) == 1
    assert exact[0].compatibility_classification == "exact"
    assert exact[0].eligible is True
    assert exact[0].availability_blockers == ()

    with ReadSnapshot(factory) as snapshot:
        assert snapshot.connection.execute(
            "SELECT COUNT(*) FROM task_unit_allocation_current"
        ).fetchone()[0] == 0
        projection = snapshot.connection.execute(
            "SELECT disposition_token,active_task_allocation_id,revision "
            "FROM spare_part_current_projection WHERE spare_part_unit_id=?",
            (unit_id,),
        ).fetchone()
        assert tuple(projection) == ("available", None, 1)


def test_t009_t010_task_reservation_is_exclusive_planning_only_and_releaseable(
    initialized_database,
) -> None:
    factory = _factory(initialized_database)
    sr = _sr(factory, "97000010")
    task_a = TaskPlanningService(factory).create_local_task(
        command_id=new_uuid4(),
        local_task_name="Install local spare",
        service_request_ids=(sr.service_request_id,),
    )
    task_b = TaskPlanningService(factory).create_local_task(
        command_id=new_uuid4(),
        local_task_name="Competing local spare",
        service_request_ids=(sr.service_request_id,),
    )
    service = InventoryNeedsStockService(factory)
    created = service.register_spare_part_unit(
        command_id=new_uuid4(),
        origin="manual_local",
        bom_code="BOM-ALLOC",
        condition_token="new",
    )
    unit_id = next(
        ref.result_id
        for ref in created.target_refs
        if ref.result_type == "spare_part_unit"
    )

    reserved = service.reserve_spare_part_unit_for_task(
        command_id=new_uuid4(),
        task_id=task_a.task_id,
        spare_part_unit_id=unit_id,
        unit_revision=1,
        task_revision=task_a.revision,
    )
    allocation_id = next(
        ref.result_id
        for ref in reserved.target_refs
        if ref.result_type == "task_unit_allocation"
    )
    assert _spare_unit_projection(factory, unit_id)[4:] == (
        "reserved",
        allocation_id,
        2,
    )

    with pytest.raises(SomaError) as excinfo:
        service.reserve_spare_part_unit_for_task(
            command_id=new_uuid4(),
            task_id=task_b.task_id,
            spare_part_unit_id=unit_id,
            unit_revision=2,
            task_revision=task_b.revision,
        )
    assert excinfo.value.code == "UNIT_ALREADY_RESERVED"

    with ReadSnapshot(factory) as snapshot:
        assert snapshot.connection.execute(
            "SELECT COUNT(*) FROM task_unit_allocation_current "
            "WHERE spare_part_unit_id=?",
            (unit_id,),
        ).fetchone()[0] == 1
        assert snapshot.connection.execute(
            "SELECT COUNT(*) FROM physical_consequence_current "
            "WHERE installed_spare_part_unit_id=?",
            (unit_id,),
        ).fetchone()[0] == 0
        execution = snapshot.connection.execute(
            "SELECT execution_state FROM task_execution_projection WHERE task_id=?",
            (task_a.task_id,),
        ).fetchone()
        assert execution is None or str(execution[0]) == "not_started"

    released = service.release_spare_part_unit_reservation(
        command_id=new_uuid4(),
        allocation_id=allocation_id,
        base_revision=1,
        reason_code="planning changed",
    )
    assert released.outcome == "APPLIED"
    assert _spare_unit_projection(factory, unit_id)[4:] == (
        "available",
        None,
        3,
    )


def test_t004_local_selection_preserves_active_need_and_optional_reservation(
    initialized_database,
) -> None:
    factory = _factory(initialized_database)
    sr = _sr(factory, "97000011")
    device = _device(factory, sr.service_request_id, "NE-LOCAL-SEL")
    service = InventoryNeedsStockService(factory)

    fault = service.register_device_part_unit(
        command_id=new_uuid4(),
        service_request_id=sr.service_request_id,
        device_reference_id=device.device_reference_id,
        bom_code="BOM-LOCAL-SEL",
        condition_token="faulty",
    )
    need_id = next(
        ref.result_id for ref in fault.target_refs if ref.result_type == "spare_need"
    )
    spare = service.register_spare_part_unit(
        command_id=new_uuid4(),
        origin="manual_local",
        bom_code="BOM-LOCAL-SEL",
        condition_token="new",
    )
    unit_id = next(
        ref.result_id
        for ref in spare.target_refs
        if ref.result_type == "spare_part_unit"
    )
    task = TaskPlanningService(factory).create_local_task(
        command_id=new_uuid4(),
        local_task_name="Local selection planning",
        service_request_ids=(sr.service_request_id,),
    )

    selected = service.record_local_need_fulfillment_selection(
        command_id=new_uuid4(),
        spare_need_id=need_id,
        spare_part_unit_id=unit_id,
        need_revision=1,
        unit_revision=1,
        task_id=task.task_id,
        task_revision=task.revision,
    )
    assert selected.outcome == "APPLIED"

    with ReadSnapshot(factory) as snapshot:
        need = snapshot.connection.execute(
            "SELECT lifecycle_state,planned_quantity,revision "
            "FROM spare_need_current_projection WHERE spare_need_id=?",
            (need_id,),
        ).fetchone()
        assert tuple(need) == ("active", 1, 1)
        assert snapshot.connection.execute(
            "SELECT COUNT(*) FROM spare_need_active_keys WHERE spare_need_id=?",
            (need_id,),
        ).fetchone()[0] == 1
        assert snapshot.connection.execute(
            "SELECT COUNT(*) FROM local_need_fulfillment_events "
            "WHERE spare_need_id=? AND event_kind='selected'",
            (need_id,),
        ).fetchone()[0] == 1
        assert snapshot.connection.execute(
            "SELECT COUNT(*) FROM task_unit_allocation_current "
            "WHERE task_id=? AND spare_part_unit_id=?",
            (task.task_id, unit_id),
        ).fetchone()[0] == 1
        assert snapshot.connection.execute(
            "SELECT COUNT(*) FROM physical_consequence_current "
            "WHERE installed_spare_part_unit_id=?",
            (unit_id,),
        ).fetchone()[0] == 0
