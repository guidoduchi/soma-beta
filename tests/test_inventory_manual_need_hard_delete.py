from __future__ import annotations

from soma.foundation.identifiers import new_uuid4
from soma.foundation.persistence.uow import ReadSnapshot
from soma.inventory.api.routes_inventory import resolve_route
from soma.inventory.queries.previews import InventoryDestructivePreviewQuery
from soma.inventory.services.hard_delete import InventoryHardDeleteService
from soma.inventory.services.needs_stock import InventoryNeedsStockService
from test_inventory_needs_stock import _factory, _sr


def _allocator_snapshot(factory):
    with ReadSnapshot(factory) as snapshot:
        return [
            tuple(row)
            for row in snapshot.connection.execute(
                "SELECT allocator_kind,next_sequence,revision,last_command_id "
                "FROM inventory_tracking_allocators ORDER BY allocator_kind"
            ).fetchall()
        ]


def test_t006_untouched_manual_need_hard_delete_preserves_audit_and_allocator_history(
    initialized_database,
) -> None:
    factory = _factory(initialized_database)
    sr = _sr(factory, "97100006")
    before_allocators = _allocator_snapshot(factory)

    route = resolve_route("POST", "/api/v1/inventory/needs")
    assert route is not None
    assert route.spec.handler == "CreateSpareNeedDraft"

    service = InventoryNeedsStockService(factory)
    create_command = new_uuid4()
    created = service.create_spare_need_draft(
        command_id=create_command,
        service_request_id=sr.service_request_id,
        bom_code="  MANUAL-NEED-006  ",
        planned_quantity=3,
    )
    need_id = next(
        ref.result_id
        for ref in created.target_refs
        if ref.result_type == "spare_need"
    )
    assert created.outcome == "APPLIED"
    assert created.replayed is False
    assert created.revisions == {f"spare_need:{need_id}": 1}

    replay = service.create_spare_need_draft(
        command_id=create_command,
        service_request_id=sr.service_request_id,
        bom_code="  MANUAL-NEED-006  ",
        planned_quantity=3,
    )
    assert replay.replayed is True
    assert replay.target_refs == created.target_refs
    assert replay.revisions == created.revisions

    with ReadSnapshot(factory) as snapshot:
        root = snapshot.connection.execute(
            "SELECT service_request_id,bom_code,creation_origin,created_command_id "
            "FROM spare_needs WHERE spare_need_id=?",
            (need_id,),
        ).fetchone()
        assert tuple(root) == (
            sr.service_request_id,
            "MANUAL-NEED-006",
            "manual",
            create_command,
        )
        projection = snapshot.connection.execute(
            "SELECT lifecycle_state,planned_quantity,contributor_count,revision,last_command_id "
            "FROM spare_need_current_projection WHERE spare_need_id=?",
            (need_id,),
        ).fetchone()
        assert tuple(projection) == ("active", 3, 0, 1, create_command)
        assert snapshot.connection.execute(
            "SELECT COUNT(*) FROM spare_need_contributors WHERE spare_need_id=?",
            (need_id,),
        ).fetchone()[0] == 0
        event = snapshot.connection.execute(
            "SELECT event_kind,planned_quantity,command_id "
            "FROM spare_need_lifecycle_events WHERE spare_need_id=?",
            (need_id,),
        ).fetchone()
        assert tuple(event) == ("created", 3, create_command)
        assert snapshot.connection.execute(
            "SELECT COUNT(*) FROM audit_events "
            "WHERE command_id=? AND action_type='inventory.spare_need.changed'",
            (create_command,),
        ).fetchone()[0] == 1
    assert _allocator_snapshot(factory) == before_allocators

    preview = InventoryDestructivePreviewQuery(factory).preview_hard_delete(
        target_kind="spare_need",
        target_id=need_id,
    )
    assert preview["classification"] == "CLEAR"
    assert preview["reviewed_revision"] == 1
    assert preview["blockers"] == []
    assert preview["retained_related_ids"] == [sr.service_request_id]

    delete_command = new_uuid4()
    owner = InventoryHardDeleteService(factory)
    deleted = owner.hard_delete_untouched_inventory_draft(
        command_id=delete_command,
        target_kind="spare_need",
        target_id=need_id,
        expected_revision=1,
        preview_fingerprint=str(preview["input_fingerprint"]),
        deliberate_confirmation=True,
    )
    assert deleted.outcome == "APPLIED"
    assert deleted.replayed is False
    assert deleted.revisions == {}

    delete_replay = owner.hard_delete_untouched_inventory_draft(
        command_id=delete_command,
        target_kind="spare_need",
        target_id=need_id,
        expected_revision=1,
        preview_fingerprint=str(preview["input_fingerprint"]),
        deliberate_confirmation=True,
    )
    assert delete_replay.replayed is True
    assert delete_replay.target_refs == deleted.target_refs

    with ReadSnapshot(factory) as snapshot:
        for table in (
            "spare_needs",
            "spare_need_current_projection",
            "spare_need_active_keys",
            "spare_need_lifecycle_events",
        ):
            assert snapshot.connection.execute(
                f"SELECT COUNT(*) FROM {table} WHERE spare_need_id=?",
                (need_id,),
            ).fetchone()[0] == 0
        assert snapshot.connection.execute(
            "SELECT COUNT(*) FROM command_receipts WHERE command_id IN (?,?)",
            (create_command, delete_command),
        ).fetchone()[0] == 2
        assert snapshot.connection.execute(
            "SELECT COUNT(*) FROM audit_events "
            "WHERE command_id=? AND action_type='inventory.spare_need.changed'",
            (create_command,),
        ).fetchone()[0] == 1
        assert snapshot.connection.execute(
            "SELECT COUNT(*) FROM audit_events "
            "WHERE command_id=? AND action_type='inventory.untouched_draft.hard_deleted'",
            (delete_command,),
        ).fetchone()[0] == 1

    assert _allocator_snapshot(factory) == before_allocators
