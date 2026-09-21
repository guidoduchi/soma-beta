from __future__ import annotations

import re

import pytest

from soma.foundation.errors import SomaError
from soma.foundation.identifiers import new_uuid4
from soma.foundation.persistence.uow import UnitOfWork
from soma.tickets.queries.rfc_archive import (
    RfcArchiveQueryService,
    archive_operation_projection_fingerprint,
)
from soma.tickets.rfc_archive import RfcArchiveService


_SHA256_HEX_RE = re.compile(r"[0-9a-f]{64}\Z")


def _factory(initialized_database):
    database_path, factory_for_path = initialized_database
    return factory_for_path(database_path)


def _seed_branch(factory, *, child_count: int, serial_base: int) -> tuple[str, tuple[str, ...]]:
    root_id = new_uuid4()
    child_ids = tuple(new_uuid4() for _ in range(child_count))
    seed_command_id = new_uuid4()
    with UnitOfWork(factory) as uow:
        uow.connection.execute(
            "INSERT INTO command_receipts("
            "command_id,command_type,request_hash,target_type,target_id,committed_at_utc,result_type,result_id"
            ") VALUES (?, 'TEST_SEED_RFC_ARCHIVE_PROJECTION', ?, 'test_seed', NULL, 0, 'test_seed', ?)",
            (seed_command_id, "0" * 64, seed_command_id),
        )
        uow.connection.execute(
            "INSERT INTO rfcs(rfc_id,rfc_no,customer_org_id,local_archive_state,revision,created_at_utc,updated_at_utc) "
            "VALUES (?, ?, NULL, 'active', ?, 0, 0)",
            (root_id, f"NC{serial_base:014d}", child_count + 1),
        )
        for offset, child_id in enumerate(child_ids, start=1):
            uow.connection.execute(
                "INSERT INTO rfcs(rfc_id,rfc_no,customer_org_id,local_archive_state,revision,created_at_utc,updated_at_utc) "
                "VALUES (?, ?, NULL, 'active', 2, 0, 0)",
                (child_id, f"NC{serial_base + offset:014d}"),
            )
            uow.connection.execute(
                "INSERT INTO rfc_hierarchy_edges("
                "rfc_hierarchy_edge_id,parent_rfc_id,child_rfc_id,edge_state,opened_at_utc,opened_command_id"
                ") VALUES (?, ?, ?, 'active', 0, ?)",
                (new_uuid4(), root_id, child_id, seed_command_id),
            )
    return root_id, child_ids


def test_restore_replay_continuation_is_invalidated_by_later_projection_change(
    initialized_database,
) -> None:
    factory = _factory(initialized_database)
    root_id, child_ids = _seed_branch(factory, child_count=32, serial_base=5000)
    query = RfcArchiveQueryService(factory)
    service = RfcArchiveService(factory)

    preview = query.preview(rfc_id=root_id, scope_kind="reviewed_branch")
    archived = service.archive(
        command_id=new_uuid4(),
        rfc_id=root_id,
        scope_kind="reviewed_branch",
        reviewed_scope_fingerprint=preview.scope_fingerprint,
    )
    assert archived.rfc_archive_operation_id is not None
    operation_id = archived.rfc_archive_operation_id

    restore_command_id = new_uuid4()
    restored = service.restore_operation(
        command_id=restore_command_id,
        rfc_archive_operation_id=operation_id,
    )
    assert restored.exact_member_count == 33
    assert len(restored.members) == 32
    assert restored.continuation is not None
    assert _SHA256_HEX_RE.fullmatch(restored.projection_fingerprint) is not None

    full_after_restore = query.get(
        rfc_archive_operation_id=operation_id,
        limit=500,
    )
    assert full_after_restore.continuation is None
    assert len(full_after_restore.members) == 33
    assert full_after_restore.projection_fingerprint == restored.projection_fingerprint
    assert archive_operation_projection_fingerprint(
        rfc_archive_operation_id=operation_id,
        scope_kind=full_after_restore.scope_kind,
        scope_fingerprint=full_after_restore.scope_fingerprint,
        members=full_after_restore.members,
    ) == restored.projection_fingerprint

    later_member = child_ids[-1]
    later_preview = query.preview(rfc_id=later_member, scope_kind="exact_rfc")
    later_archive = service.archive(
        command_id=new_uuid4(),
        rfc_id=later_member,
        scope_kind="exact_rfc",
        reviewed_scope_fingerprint=later_preview.scope_fingerprint,
    )
    assert later_archive.rfc_archive_operation_id is not None
    assert later_archive.rfc_archive_operation_id != operation_id

    replay = service.restore_operation(
        command_id=restore_command_id,
        rfc_archive_operation_id=operation_id,
    )
    assert replay.to_response() == restored.to_response()
    assert replay.continuation is not None

    fresh_first_page = query.get(
        rfc_archive_operation_id=operation_id,
        limit=32,
    )
    assert fresh_first_page.projection_fingerprint != replay.projection_fingerprint
    assert fresh_first_page.continuation is not None

    with pytest.raises(SomaError) as exc_info:
        query.get(
            rfc_archive_operation_id=operation_id,
            cursor=replay.continuation,
            limit=32,
        )
    assert exc_info.value.code == "VALIDATION_FAILED"
    assert "filter fingerprint is stale" in exc_info.value.message

    fresh_second_page = query.get(
        rfc_archive_operation_id=operation_id,
        cursor=fresh_first_page.continuation,
        limit=32,
    )
    assert fresh_second_page.projection_fingerprint == fresh_first_page.projection_fingerprint
    assert len(fresh_second_page.members) == 1
    assert fresh_second_page.continuation is None
