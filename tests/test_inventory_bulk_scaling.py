from __future__ import annotations

import sqlite3

import pytest

from soma.foundation.errors import ValidationError
from soma.inventory.queries.previews import InventoryBulkPreviewQuery
from soma.inventory.repositories.fault_tags import InventoryFaultTagsRepository


def _uuid_for(ordinal: int) -> str:
    return f"{ordinal:08x}-0000-4000-8000-{ordinal:012x}"


def _warehouse_authority_database(count: int = 2_000) -> tuple[sqlite3.Connection, tuple[tuple[str, int], ...]]:
    connection = sqlite3.connect(":memory:")
    connection.execute(
        "CREATE TABLE fault_tag_membership_current("
        "fault_tag_membership_id TEXT PRIMARY KEY,"
        "fault_tag_id TEXT NOT NULL,"
        "rma_id TEXT NOT NULL,"
        "device_part_unit_id TEXT,"
        "spare_part_unit_id TEXT,"
        "state TEXT NOT NULL,"
        "active_submitted INTEGER NOT NULL,"
        "revision INTEGER NOT NULL,"
        "last_event_id TEXT NOT NULL"
        ")"
    )
    connection.execute(
        "CREATE TABLE fault_tag_memberships("
        "fault_tag_membership_id TEXT PRIMARY KEY,"
        "physical_consequence_id TEXT NOT NULL"
        ")"
    )
    connection.execute(
        "CREATE TABLE rma_return_obligation_current("
        "rma_id TEXT PRIMARY KEY,"
        "obligation_state TEXT NOT NULL,"
        "device_part_unit_id TEXT,"
        "spare_part_unit_id TEXT,"
        "physical_consequence_id TEXT NOT NULL,"
        "revision INTEGER NOT NULL,"
        "last_event_id TEXT"
        ")"
    )

    current_rows = []
    membership_rows = []
    obligation_rows = []
    targets: list[tuple[str, int]] = []
    for ordinal in range(1, count + 1):
        membership_id = _uuid_for(ordinal)
        fault_tag_id = _uuid_for(10_000 + ordinal)
        rma_id = _uuid_for(20_000 + ordinal)
        consequence_id = _uuid_for(30_000 + ordinal)
        event_id = _uuid_for(40_000 + ordinal)
        revision = 7
        targets.append((membership_id, revision))
        current_rows.append(
            (
                membership_id,
                fault_tag_id,
                rma_id,
                None,
                None,
                "submitted_awaiting_receipt",
                1,
                revision,
                event_id,
            )
        )
        membership_rows.append((membership_id, consequence_id))
        obligation_rows.append(
            (
                rma_id,
                "open",
                None,
                None,
                consequence_id,
                3,
                event_id,
            )
        )

    connection.executemany(
        "INSERT INTO fault_tag_membership_current VALUES (?,?,?,?,?,?,?,?,?)",
        current_rows,
    )
    connection.executemany(
        "INSERT INTO fault_tag_memberships VALUES (?,?)",
        membership_rows,
    )
    connection.executemany(
        "INSERT INTO rma_return_obligation_current VALUES (?,?,?,?,?,?,?)",
        obligation_rows,
    )
    connection.commit()
    return connection, tuple(targets)


def test_2000_target_bulk_preview_prefetches_authority_in_five_chunks() -> None:
    connection, targets = _warehouse_authority_database()
    statements: list[str] = []
    connection.set_trace_callback(statements.append)
    try:
        preview = InventoryBulkPreviewQuery.classify_bulk(
            connection,
            action_kind="warehouse_receipt",
            targets=targets,
        )
    finally:
        connection.set_trace_callback(None)
        connection.close()

    authority_selects = [
        statement
        for statement in statements
        if statement.lstrip().upper().startswith("SELECT ")
        and "FROM fault_tag_membership_current c" in statement
    ]
    assert len(authority_selects) == 5
    assert preview["compatible"] is True
    assert len(preview["targets"]) == 2_000
    assert len(preview["blockers"]) == 0


def test_writer_bulk_preflight_uses_same_bounded_authority_chunks() -> None:
    connection, targets = _warehouse_authority_database()
    statements: list[str] = []
    connection.set_trace_callback(statements.append)
    try:
        validated = InventoryFaultTagsRepository._require_warehouse_targets(
            connection,
            targets=targets,
            required_state="submitted_awaiting_receipt",
        )
    finally:
        connection.set_trace_callback(None)
        connection.close()

    authority_selects = [
        statement
        for statement in statements
        if statement.lstrip().upper().startswith("SELECT ")
        and "FROM fault_tag_membership_current c" in statement
    ]
    assert len(authority_selects) == 5
    assert len(validated) == 2_000


def test_inventory_bulk_preview_rejects_2001_targets_before_authority_reads() -> None:
    connection = sqlite3.connect(":memory:")
    targets = tuple((_uuid_for(index + 1), 1) for index in range(2_001))
    statements: list[str] = []
    connection.set_trace_callback(statements.append)
    try:
        with pytest.raises(ValidationError, match="target bound exceeded"):
            InventoryBulkPreviewQuery.classify_bulk(
                connection,
                action_kind="warehouse_receipt",
                targets=targets,
            )
    finally:
        connection.set_trace_callback(None)
        connection.close()
    assert not any(statement.lstrip().upper().startswith("SELECT ") for statement in statements)
