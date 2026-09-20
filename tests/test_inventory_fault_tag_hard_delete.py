from __future__ import annotations

import pytest
import sqlite3

from soma.foundation.errors import SomaError
from soma.foundation.identifiers import new_uuid4
from soma.foundation.persistence.uow import ReadSnapshot, UnitOfWork
from soma.inventory.queries.previews import InventoryDestructivePreviewQuery
from soma.inventory.services.fault_tags import InventoryFaultTagsService
from soma.inventory.services.hard_delete import InventoryHardDeleteService
from test_inventory_warehouse_replay import _factory, _submitted_tag
from test_inventory_request_creation_replay import _creation
from soma.inventory.services.requests_rma import InventoryRequestsRmaService
from soma.inventory.services.needs_stock import InventoryNeedsStockService


def _delete_arguments(preview):
    return dict(command_id=new_uuid4(), target_kind="fault_tag", target_id=preview["target_id"],
                expected_revision=preview["reviewed_revision"],
                preview_fingerprint=preview["input_fingerprint"], deliberate_confirmation=True)


def test_untouched_fault_tag_delete_retains_allocator_and_replays_t060(initialized_database):
    factory = _factory(initialized_database)
    tags = InventoryFaultTagsService(factory)
    created = tags.create_fault_tag_draft(command_id=new_uuid4(), return_method="non_pickup")
    preview = InventoryDestructivePreviewQuery(factory).preview_hard_delete(
        target_kind="fault_tag", target_id=created["fault_tag_id"],
    )
    assert preview["classification"] == "CLEAR"
    args = _delete_arguments(preview)
    owner = InventoryHardDeleteService(factory)
    result = owner.hard_delete_untouched_inventory_draft(**args)
    replay = owner.hard_delete_untouched_inventory_draft(**args)
    assert replay.replayed and replay.target_refs == result.target_refs
    with ReadSnapshot(factory) as snapshot:
        assert snapshot.connection.execute(
            "SELECT COUNT(*) FROM fault_tags WHERE fault_tag_id=?", (created["fault_tag_id"],),
        ).fetchone()[0] == 0
        assert snapshot.connection.execute(
            "SELECT COUNT(*) FROM audit_events WHERE target_id=?", (created["fault_tag_id"],),
        ).fetchone()[0] == 2
    next_tag = tags.create_fault_tag_draft(command_id=new_uuid4(), return_method="non_pickup")
    assert created["tracking_handle"] == "FT-00000001"
    assert next_tag["tracking_handle"] == "FT-00000002"


def test_submitted_fault_tag_history_blocks_hard_delete_t061(initialized_database):
    factory = _factory(initialized_database)
    _, submitted, _ = _submitted_tag(factory)
    query = InventoryDestructivePreviewQuery(factory)
    preview = query.preview_hard_delete(target_kind="fault_tag", target_id=submitted["fault_tag_id"])
    assert preview["classification"] == "BLOCKED"
    assert "submission_history" in preview["blockers"]
    args = _delete_arguments(preview)
    with pytest.raises(SomaError) as blocked:
        InventoryHardDeleteService(factory).hard_delete_untouched_inventory_draft(**args)
    assert blocked.value.code == "HARD_DELETE_BLOCKED"
    with ReadSnapshot(factory) as snapshot:
        assert snapshot.connection.execute(
            "SELECT COUNT(*) FROM command_receipts WHERE command_id=?", (args["command_id"],),
        ).fetchone()[0] == 0
        assert snapshot.connection.execute(
            "SELECT COUNT(*) FROM fault_tag_submission_snapshots WHERE fault_tag_id=?",
            (submitted["fault_tag_id"],),
        ).fetchone()[0] == 1


@pytest.mark.parametrize("kind", ["spare_request", "spare_part_unit"])
def test_other_untouched_draft_creation_facts_are_deletable(initialized_database, kind):
    factory = _factory(initialized_database)
    if kind == "spare_request":
        created = InventoryRequestsRmaService(factory).create_spare_request_draft(**_creation(factory))
        identity = created["spare_request_id"]
    else:
        created = InventoryNeedsStockService(factory).register_spare_part_unit(
            command_id=new_uuid4(), origin="manual_local", bom_code="UNTOUCHED", condition_token="new",
        )
        identity = next(ref.result_id for ref in created.target_refs if ref.result_type == kind)
    preview = InventoryDestructivePreviewQuery(factory).preview_hard_delete(target_kind=kind, target_id=identity)
    assert preview["classification"] == "CLEAR"
    args = {**_delete_arguments(preview), "target_kind": kind}
    owner = InventoryHardDeleteService(factory)
    owner.hard_delete_untouched_inventory_draft(**args)
    assert owner.hard_delete_untouched_inventory_draft(**args).replayed


def test_initial_fact_cannot_be_deleted_without_matching_pending_command(initialized_database):
    factory = _factory(initialized_database)
    tag = InventoryFaultTagsService(factory).create_fault_tag_draft(
        command_id=new_uuid4(), return_method="non_pickup",
    )
    with pytest.raises(sqlite3.IntegrityError, match="IMMUTABLE"):
        with UnitOfWork(factory) as uow:
            uow.connection.execute("DELETE FROM fault_tag_current_projection WHERE fault_tag_id=?", (tag["fault_tag_id"],))
            uow.connection.execute("DELETE FROM fault_tag_lifecycle_events WHERE fault_tag_id=?", (tag["fault_tag_id"],))
    with ReadSnapshot(factory) as snapshot:
        assert snapshot.connection.execute("SELECT COUNT(*) FROM fault_tag_current_projection WHERE fault_tag_id=?", (tag["fault_tag_id"],)).fetchone()[0] == 1
