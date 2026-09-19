from __future__ import annotations

from soma.foundation.identifiers import new_uuid4
from soma.foundation.persistence.uow import ReadSnapshot
from soma.inventory.services.fault_tags import InventoryFaultTagsService


def _factory(initialized_database):
    database_path, builder = initialized_database
    return builder(database_path)


def test_t042_fault_tag_draft_allocates_immutable_handle_and_allows_zero_members(
    initialized_database,
) -> None:
    factory = _factory(initialized_database)
    service = InventoryFaultTagsService(factory)

    created = service.create_fault_tag_draft(
        command_id=new_uuid4(),
        return_method="pickup",
    )
    assert created["state"] == "draft"
    assert created["revision"] == 1
    assert created["members"] == []
    assert created["tracking_handle"] == "FT-00000001"

    updated = service.update_fault_tag_draft(
        command_id=new_uuid4(),
        fault_tag_id=str(created["fault_tag_id"]),
        base_revision=1,
        return_method="non_pickup",
        memberships=(),
    )
    assert updated["fault_tag_id"] == created["fault_tag_id"]
    assert updated["tracking_handle"] == created["tracking_handle"]
    assert updated["state"] == "draft"
    assert updated["revision"] == 2
    assert updated["members"] == []

    second = service.create_fault_tag_draft(
        command_id=new_uuid4(),
        return_method="non_pickup",
    )
    assert second["tracking_handle"] == "FT-00000002"

    with ReadSnapshot(factory) as snapshot:
        allocator = snapshot.connection.execute(
            "SELECT next_sequence FROM inventory_tracking_allocators "
            "WHERE allocator_kind='fault_tag'"
        ).fetchone()
        assert int(allocator[0]) == 3
        tags = snapshot.connection.execute(
            "SELECT tracking_id,draft_revision FROM fault_tags ORDER BY tracking_sequence"
        ).fetchall()
        assert [tuple(row) for row in tags] == [
            ("FT-00000001", 2),
            ("FT-00000002", 1),
        ]
        assert snapshot.connection.execute(
            "SELECT COUNT(*) FROM fault_tag_submission_snapshots"
        ).fetchone()[0] == 0
        assert snapshot.connection.execute(
            "SELECT COUNT(*) FROM fault_tag_membership_events"
        ).fetchone()[0] == 0


def test_t043_pickup_fault_tag_submission_requires_pickup_origin(
    initialized_database,
) -> None:
    factory = _factory(initialized_database)
    service = InventoryFaultTagsService(factory)
    created = service.create_fault_tag_draft(
        command_id=new_uuid4(),
        return_method="pickup",
    )
    with ReadSnapshot(factory) as snapshot:
        fingerprint = str(
            snapshot.connection.execute(
                "SELECT input_fingerprint FROM fault_tag_current_projection "
                "WHERE fault_tag_id=?",
                (str(created["fault_tag_id"]),),
            ).fetchone()[0]
        )

    import pytest
    from soma.foundation.errors import SomaError

    with pytest.raises(SomaError) as excinfo:
        service.accept_fault_tag_submission(
            command_id=new_uuid4(),
            fault_tag_id=str(created["fault_tag_id"]),
            expected_fingerprint=fingerprint,
        )
    assert excinfo.value.code == "FAULT_TAG_PICKUP_ORIGIN_REQUIRED"
