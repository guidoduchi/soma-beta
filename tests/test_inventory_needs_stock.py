from __future__ import annotations

from soma.foundation.identifiers import new_uuid4
from soma.foundation.persistence.uow import ReadSnapshot
from soma.inventory.services.needs_stock import InventoryNeedsStockService
from soma.tickets.device_references import DeviceReferenceService
from soma.tickets.relationships import TicketDeviceReferenceRelationshipService
from soma.tickets.service_requests import ServiceRequestService


def _factory(initialized_database):
    database_path, factory_builder = initialized_database
    return factory_builder(database_path)


def _sr_and_devices(factory, *, official: str, count: int):
    sr = ServiceRequestService(factory).create_manual_service_request(
        command_id=new_uuid4(),
        official_sr_no=official,
    )
    device_service = DeviceReferenceService(factory)
    links = TicketDeviceReferenceRelationshipService(factory)
    devices = []
    for index in range(count):
        device = device_service.create(
            command_id=new_uuid4(),
            operational_name=f"{official}-device-{index:02d}",
        )
        links.link(
            command_id=new_uuid4(),
            ticket_type="service_request",
            ticket_id=sr.service_request_id,
            device_reference_id=device.device_reference_id,
            target_base_revision=sr.revision,
        )
        devices.append(device.device_reference_id)
    return sr.service_request_id, tuple(devices)


def _ref_id(result, ref_type: str) -> str:
    matches = [ref.id for ref in result.target_refs if ref.type == ref_type]
    assert len(matches) == 1
    return matches[0]


def test_same_sr_bom_aggregates_sixty_contributors_without_changing_planned_quantity_t001_t003(
    initialized_database,
) -> None:
    factory = _factory(initialized_database)
    sr_id, devices = _sr_and_devices(factory, official="98100001", count=15)
    service = InventoryNeedsStockService(factory)

    need_ids = []
    for ordinal in range(60):
        result = service.register_device_part_unit(
            command_id=new_uuid4(),
            service_request_id=sr_id,
            device_reference_id=devices[ordinal % len(devices)],
            bom_code="Board / Main-A",
            manufacturer_serial=f"SER-{ordinal:03d}",
            condition_token="faulty",
            effective_at_utc=1_000 + ordinal,
        )
        assert result.outcome == "APPLIED"
        need_ids.append(_ref_id(result, "spare_need"))

    assert len(set(need_ids)) == 1
    need_id = need_ids[0]

    with ReadSnapshot(factory) as snapshot:
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
            "SELECT COUNT(*) FROM spare_needs WHERE service_request_id=?",
            (sr_id,),
        ).fetchone()[0] == 1

    changed = service.set_spare_need_planned_quantity(
        command_id=new_uuid4(),
        spare_need_id=need_id,
        base_revision=60,
        planned_quantity=7,
        reason="reviewed_demand_quantity",
    )
    assert changed.outcome == "APPLIED"
    with ReadSnapshot(factory) as snapshot:
        projection = snapshot.connection.execute(
            "SELECT planned_quantity,contributor_count,revision "
            "FROM spare_need_current_projection WHERE spare_need_id=?",
            (need_id,),
        ).fetchone()
        assert tuple(projection) == (7, 60, 61)


def test_same_bom_on_two_service_requests_never_cross_aggregates_t002(
    initialized_database,
) -> None:
    factory = _factory(initialized_database)
    sr_a, devices_a = _sr_and_devices(factory, official="98100002", count=1)
    sr_b, devices_b = _sr_and_devices(factory, official="98100003", count=1)
    service = InventoryNeedsStockService(factory)

    first = service.register_device_part_unit(
        command_id=new_uuid4(),
        service_request_id=sr_a,
        device_reference_id=devices_a[0],
        bom_code="SAME-BOM",
        condition_token="faulty",
    )
    second = service.register_device_part_unit(
        command_id=new_uuid4(),
        service_request_id=sr_b,
        device_reference_id=devices_b[0],
        bom_code="same-bom",
        condition_token="faulty",
    )
    need_a = _ref_id(first, "spare_need")
    need_b = _ref_id(second, "spare_need")
    assert need_a != need_b

    with ReadSnapshot(factory) as snapshot:
        rows = snapshot.connection.execute(
            "SELECT service_request_id,spare_need_id FROM spare_need_active_keys "
            "ORDER BY service_request_id"
        ).fetchall()
        assert {tuple(row) for row in rows} == {(sr_a, need_a), (sr_b, need_b)}


def test_register_device_part_replays_exact_identity_and_duplicate_is_not_merged(
    initialized_database,
) -> None:
    factory = _factory(initialized_database)
    sr_id, devices = _sr_and_devices(factory, official="98100004", count=1)
    service = InventoryNeedsStockService(factory)
    command_id = new_uuid4()

    first = service.register_device_part_unit(
        command_id=command_id,
        service_request_id=sr_id,
        device_reference_id=devices[0],
        bom_code="Dup-BOM",
        manufacturer_serial="SERIAL-ONE",
        condition_token="faulty",
    )
    replay = service.register_device_part_unit(
        command_id=command_id,
        service_request_id=sr_id,
        device_reference_id=devices[0],
        bom_code="Dup-BOM",
        manufacturer_serial="SERIAL-ONE",
        condition_token="faulty",
    )
    assert replay.replayed is True
    assert replay.target_refs == first.target_refs

    duplicate_candidates = service.preview_device_part_duplicates(
        service_request_id=sr_id,
        bom_code="dup-bom",
        manufacturer_serial="serial-one",
    )
    assert duplicate_candidates == (_ref_id(first, "device_part_unit"),)

    second = service.register_device_part_unit(
        command_id=new_uuid4(),
        service_request_id=sr_id,
        device_reference_id=devices[0],
        bom_code="dup-bom",
        manufacturer_serial="serial-one",
        condition_token="faulty",
    )
    assert _ref_id(second, "device_part_unit") != _ref_id(first, "device_part_unit")

    with ReadSnapshot(factory) as snapshot:
        assert snapshot.connection.execute(
            "SELECT COUNT(*) FROM device_part_units WHERE service_request_id=?",
            (sr_id,),
        ).fetchone()[0] == 2


def test_need_lifecycle_releases_and_restores_active_sr_bom_key(
    initialized_database,
) -> None:
    factory = _factory(initialized_database)
    sr_id, devices = _sr_and_devices(factory, official="98100005", count=1)
    service = InventoryNeedsStockService(factory)
    registered = service.register_device_part_unit(
        command_id=new_uuid4(),
        service_request_id=sr_id,
        device_reference_id=devices[0],
        bom_code="Lifecycle-BOM",
        condition_token="faulty",
    )
    need_id = _ref_id(registered, "spare_need")

    resolved = service.change_spare_need_lifecycle(
        command_id=new_uuid4(),
        spare_need_id=need_id,
        base_revision=1,
        action="resolve",
        reason="demand_temporarily_resolved",
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
        reason="demand_returned",
    )
    assert reactivated.outcome == "APPLIED"

    with ReadSnapshot(factory) as snapshot:
        row = snapshot.connection.execute(
            "SELECT lifecycle_state,planned_quantity,contributor_count,revision "
            "FROM spare_need_current_projection WHERE spare_need_id=?",
            (need_id,),
        ).fetchone()
        assert tuple(row) == ("active", 1, 1, 3)
        active = snapshot.connection.execute(
            "SELECT service_request_id,bom_key FROM spare_need_active_keys "
            "WHERE spare_need_id=?",
            (need_id,),
        ).fetchone()
        assert active is not None
        assert str(active[0]) == sr_id
