from __future__ import annotations

import json

import pytest

from soma.foundation.errors import SomaError
from soma.foundation.identifiers import new_uuid4
from soma.foundation.persistence.uow import ReadSnapshot, UnitOfWork
from soma.tickets.queries.rfc_archive import (
    RfcArchiveQueryService,
    RfcArchiveScope,
    RfcArchiveScopeMember,
    archive_scope_fingerprint,
)
from soma.tickets.rfc_archive import RfcArchiveService


def _factory(initialized_database):
    database_path, factory_for_path = initialized_database
    return factory_for_path(database_path)


def _seed_branch(factory, *, child_count: int, serial_base: int = 1) -> tuple[str, tuple[str, ...]]:
    root_id = new_uuid4()
    child_ids = tuple(new_uuid4() for _ in range(child_count))
    seed_command_id = new_uuid4()
    with UnitOfWork(factory) as uow:
        uow.connection.execute(
            "INSERT INTO command_receipts("
            "command_id,command_type,request_hash,target_type,target_id,committed_at_utc,result_type,result_id"
            ") VALUES (?, 'TEST_SEED_RFC_BRANCH', ?, 'test_seed', NULL, 0, 'test_seed', ?)",
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


def _audit_payload(snapshot, command_id: str) -> dict[str, object]:
    row = snapshot.connection.execute(
        "SELECT payload_json FROM audit_events WHERE command_id=?",
        (command_id,),
    ).fetchone()
    assert row is not None
    return json.loads(str(row[0]))


def test_archive_scope_fingerprint_matches_certified_golden_vectors() -> None:
    exact = RfcArchiveScope(
        requested_rfc_id="00000000-0000-4000-8000-000000000001",
        scope_kind="exact_rfc",
        members=(
            RfcArchiveScopeMember(
                rfc_id="00000000-0000-4000-8000-000000000001",
                rfc_revision=3,
                archive_state="active",
                scope_ordinal=0,
            ),
        ),
        scope_fingerprint="",
    )
    assert archive_scope_fingerprint(exact) == (
        "d419521b42adee4c607571b5e64eb5b004e51055f91c2c4548863959d2f8bedc"
    )

    branch = RfcArchiveScope(
        requested_rfc_id="00000000-0000-4000-8000-000000000010",
        scope_kind="reviewed_branch",
        members=(
            RfcArchiveScopeMember(
                rfc_id="00000000-0000-4000-8000-000000000010",
                rfc_revision=5,
                archive_state="active",
                scope_ordinal=0,
            ),
            RfcArchiveScopeMember(
                rfc_id="00000000-0000-4000-8000-000000000011",
                rfc_revision=2,
                archive_state="archived",
                scope_ordinal=1,
            ),
            RfcArchiveScopeMember(
                rfc_id="00000000-0000-4000-8000-000000000012",
                rfc_revision=7,
                archive_state="active",
                scope_ordinal=2,
            ),
        ),
        scope_fingerprint="",
    )
    assert archive_scope_fingerprint(branch) == (
        "041cb2c673287f42bb9cb968feb5ef403839ef3a815b1ff7a18846396e0543de"
    )


def test_archive_rejects_stale_complete_scope_before_receipt_or_mutation(initialized_database) -> None:
    factory = _factory(initialized_database)
    root_id, child_ids = _seed_branch(factory, child_count=1, serial_base=100)
    query = RfcArchiveQueryService(factory)
    preview = query.preview(rfc_id=root_id, scope_kind="reviewed_branch")

    with UnitOfWork(factory) as uow:
        uow.connection.execute(
            "UPDATE rfcs SET revision=revision+1 WHERE rfc_id=?",
            (child_ids[0],),
        )

    command_id = new_uuid4()
    with pytest.raises(SomaError) as exc_info:
        RfcArchiveService(factory).archive(
            command_id=command_id,
            rfc_id=root_id,
            scope_kind="reviewed_branch",
            reviewed_scope_fingerprint=preview.scope_fingerprint,
        )
    assert exc_info.value.code == "RFC_ARCHIVE_SCOPE_STALE"

    with ReadSnapshot(factory) as snapshot:
        assert snapshot.connection.execute(
            "SELECT count(*) FROM command_receipts WHERE command_id=?",
            (command_id,),
        ).fetchone()[0] == 0
        assert snapshot.connection.execute(
            "SELECT count(*) FROM rfc_archive_operations",
        ).fetchone()[0] == 0
        assert snapshot.connection.execute(
            "SELECT count(*) FROM rfc_archive_events",
        ).fetchone()[0] == 0
        assert snapshot.connection.execute(
            "SELECT count(*) FROM audit_events WHERE command_id=?",
            (command_id,),
        ).fetchone()[0] == 0


def test_archive_excludes_prearchived_members_and_replay_reads_no_owner_state(
    initialized_database,
    monkeypatch,
) -> None:
    factory = _factory(initialized_database)
    root_id, child_ids = _seed_branch(factory, child_count=1, serial_base=200)
    child_id = child_ids[0]
    query = RfcArchiveQueryService(factory)
    service = RfcArchiveService(factory)

    child_preview = query.preview(rfc_id=child_id, scope_kind="exact_rfc")
    child_archive = service.archive(
        command_id=new_uuid4(),
        rfc_id=child_id,
        scope_kind="exact_rfc",
        reviewed_scope_fingerprint=child_preview.scope_fingerprint,
    )
    assert child_archive.changed_rfc_count == 1

    preview = query.preview(rfc_id=root_id, scope_kind="reviewed_branch")
    assert preview.exact_member_count == 2
    assert preview.would_change_count == 1
    assert preview.excluded_prearchived_count == 1
    command_id = new_uuid4()
    result = service.archive(
        command_id=command_id,
        rfc_id=root_id,
        scope_kind="reviewed_branch",
        reviewed_scope_fingerprint=preview.scope_fingerprint,
    )
    original_response = result.to_response()
    assert result.outcome == "archived"
    assert result.changed_rfc_count == 1
    assert result.excluded_prearchived_count == 1
    assert result.rfc_archive_operation_id is not None

    operation = query.get(rfc_archive_operation_id=result.rfc_archive_operation_id)
    assert operation.exact_member_count == 1
    assert len(operation.members) == 1
    assert operation.members[0].rfc_id == root_id

    with ReadSnapshot(factory) as snapshot:
        assert snapshot.connection.execute(
            "SELECT count(*) FROM rfc_archive_operation_members "
            "WHERE rfc_archive_operation_id=? AND rfc_id=?",
            (result.rfc_archive_operation_id, child_id),
        ).fetchone()[0] == 0
        payload = _audit_payload(snapshot, command_id)
        assert payload["changed_rfc_count"] == 1
        assert payload["excluded_prearchived_count"] == 1
        assert "changed_rfc_ids" not in payload
        audit_id = snapshot.connection.execute(
            "SELECT audit_event_id FROM audit_events WHERE command_id=?",
            (command_id,),
        ).fetchone()[0]
        refs = snapshot.connection.execute(
            "SELECT result_type,result_id FROM audit_event_results WHERE audit_event_id=?",
            (audit_id,),
        ).fetchall()
        assert [tuple(row) for row in refs] == [
            ("rfc_archive_operation", result.rfc_archive_operation_id)
        ]

    service.restore_operation(
        command_id=new_uuid4(),
        rfc_archive_operation_id=result.rfc_archive_operation_id,
    )
    monkeypatch.setattr(
        "soma.tickets.rfc_archive.resolve_archive_scope_from_connection",
        lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("archive replay performed owner read")),
    )
    replay = service.archive(
        command_id=command_id,
        rfc_id=root_id,
        scope_kind="reviewed_branch",
        reviewed_scope_fingerprint=preview.scope_fingerprint,
    )
    assert replay.replayed is True
    assert replay.to_response() == original_response
    with ReadSnapshot(factory) as snapshot:
        assert snapshot.connection.execute(
            "SELECT count(*) FROM audit_events WHERE command_id=?",
            (command_id,),
        ).fetchone()[0] == 1


def test_archive_all_prearchived_is_exact_no_change_and_replays_without_reads(
    initialized_database,
    monkeypatch,
) -> None:
    factory = _factory(initialized_database)
    root_id, _ = _seed_branch(factory, child_count=0, serial_base=300)
    query = RfcArchiveQueryService(factory)
    service = RfcArchiveService(factory)

    first_preview = query.preview(rfc_id=root_id, scope_kind="exact_rfc")
    service.archive(
        command_id=new_uuid4(),
        rfc_id=root_id,
        scope_kind="exact_rfc",
        reviewed_scope_fingerprint=first_preview.scope_fingerprint,
    )
    no_change_preview = query.preview(rfc_id=root_id, scope_kind="exact_rfc")
    command_id = new_uuid4()
    result = service.archive(
        command_id=command_id,
        rfc_id=root_id,
        scope_kind="exact_rfc",
        reviewed_scope_fingerprint=no_change_preview.scope_fingerprint,
    )
    original = result.to_response()
    assert result.no_change is True
    assert result.outcome == "no_change"
    assert result.changed_rfc_count == 0
    assert result.excluded_prearchived_count == 1
    assert result.rfc_archive_operation_id is None

    with ReadSnapshot(factory) as snapshot:
        assert snapshot.connection.execute(
            "SELECT count(*) FROM rfc_archive_operations WHERE created_command_id=?",
            (command_id,),
        ).fetchone()[0] == 0
        assert snapshot.connection.execute(
            "SELECT count(*) FROM rfc_archive_events WHERE command_id=?",
            (command_id,),
        ).fetchone()[0] == 0
        assert snapshot.connection.execute(
            "SELECT count(*) FROM audit_events WHERE command_id=?",
            (command_id,),
        ).fetchone()[0] == 0
        assert snapshot.connection.execute(
            "SELECT result_type FROM command_receipts WHERE command_id=?",
            (command_id,),
        ).fetchone()[0] == "NO_CHANGE"
        assert tuple(
            snapshot.connection.execute(
                "SELECT response_schema,response_version FROM command_receipt_results WHERE command_id=?",
                (command_id,),
            ).fetchone()
        ) == ("ArchiveRfcResultV1", 1)

    monkeypatch.setattr(
        "soma.tickets.rfc_archive.resolve_archive_scope_from_connection",
        lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("NO_CHANGE replay performed owner read")),
    )
    replay = service.archive(
        command_id=command_id,
        rfc_id=root_id,
        scope_kind="exact_rfc",
        reviewed_scope_fingerprint=no_change_preview.scope_fingerprint,
    )
    assert replay.replayed is True
    assert replay.to_response() == original


def test_large_archive_and_restore_are_cardinality_safe_and_provenance_scoped(
    initialized_database,
    monkeypatch,
) -> None:
    factory = _factory(initialized_database)
    root_id, child_ids = _seed_branch(factory, child_count=64, serial_base=1000)
    query = RfcArchiveQueryService(factory)
    service = RfcArchiveService(factory)

    preview = query.preview(rfc_id=root_id, scope_kind="reviewed_branch")
    assert preview.exact_member_count == 65
    assert preview.would_change_count == 65
    archive_command_id = new_uuid4()
    archived = service.archive(
        command_id=archive_command_id,
        rfc_id=root_id,
        scope_kind="reviewed_branch",
        reviewed_scope_fingerprint=preview.scope_fingerprint,
    )
    assert archived.changed_rfc_count == 65
    assert archived.excluded_prearchived_count == 0
    assert archived.rfc_archive_operation_id is not None
    operation_id = archived.rfc_archive_operation_id

    with ReadSnapshot(factory) as snapshot:
        assert snapshot.connection.execute(
            "SELECT count(*) FROM rfc_archive_operation_members WHERE rfc_archive_operation_id=?",
            (operation_id,),
        ).fetchone()[0] == 65
        assert snapshot.connection.execute(
            "SELECT count(*) FROM rfc_archive_events WHERE command_id=? AND event_type='archived'",
            (archive_command_id,),
        ).fetchone()[0] == 65
        archive_payload = _audit_payload(snapshot, archive_command_id)
        assert archive_payload["changed_rfc_count"] == 65
        assert "changed_rfc_ids" not in archive_payload
        archive_audit_id = snapshot.connection.execute(
            "SELECT audit_event_id FROM audit_events WHERE command_id=?",
            (archive_command_id,),
        ).fetchone()[0]
        assert snapshot.connection.execute(
            "SELECT count(*) FROM audit_event_results WHERE audit_event_id=?",
            (archive_audit_id,),
        ).fetchone()[0] == 1

    restore_command_id = new_uuid4()
    restored = service.restore_operation(
        command_id=restore_command_id,
        rfc_archive_operation_id=operation_id,
    )
    stored_restore_response = restored.to_response()
    assert restored.exact_member_count == 65
    assert len(restored.members) == 32
    assert restored.continuation is not None
    assert all(member.restore_eligible is False for member in restored.members)

    with ReadSnapshot(factory) as snapshot:
        assert snapshot.connection.execute(
            "SELECT count(*) FROM rfcs WHERE local_archive_state='active'",
        ).fetchone()[0] == 65
        assert snapshot.connection.execute(
            "SELECT count(*) FROM rfc_archive_events WHERE command_id=? AND event_type='restored'",
            (restore_command_id,),
        ).fetchone()[0] == 65
        restore_payload = _audit_payload(snapshot, restore_command_id)
        assert restore_payload["changed_rfc_count"] == 65
        restore_audit_id = snapshot.connection.execute(
            "SELECT audit_event_id FROM audit_events WHERE command_id=?",
            (restore_command_id,),
        ).fetchone()[0]
        refs = snapshot.connection.execute(
            "SELECT result_type,result_id FROM audit_event_results WHERE audit_event_id=?",
            (restore_audit_id,),
        ).fetchall()
        assert [tuple(row) for row in refs] == [("rfc_archive_operation", operation_id)]
        stored = snapshot.connection.execute(
            "SELECT response_schema,response_version FROM command_receipt_results WHERE command_id=?",
            (restore_command_id,),
        ).fetchone()
        assert tuple(stored) == ("RfcArchiveOperationV1", 1)

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

    second_restore_command_id = new_uuid4()
    second_restore = service.restore_operation(
        command_id=second_restore_command_id,
        rfc_archive_operation_id=operation_id,
    )
    assert second_restore.members
    with ReadSnapshot(factory) as snapshot:
        assert snapshot.connection.execute(
            "SELECT local_archive_state FROM rfcs WHERE rfc_id=?",
            (later_member,),
        ).fetchone()[0] == "archived"
        assert snapshot.connection.execute(
            "SELECT result_type FROM command_receipts WHERE command_id=?",
            (second_restore_command_id,),
        ).fetchone()[0] == "NO_CHANGE"
        assert snapshot.connection.execute(
            "SELECT count(*) FROM rfc_archive_events WHERE command_id=?",
            (second_restore_command_id,),
        ).fetchone()[0] == 0
        assert snapshot.connection.execute(
            "SELECT count(*) FROM audit_events WHERE command_id=?",
            (second_restore_command_id,),
        ).fetchone()[0] == 0

    monkeypatch.setattr(
        service._queries,
        "load_complete_operation_members_from_connection",
        lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("restore replay performed owner read")),
    )
    replay = service.restore_operation(
        command_id=restore_command_id,
        rfc_archive_operation_id=operation_id,
    )
    assert replay.to_response() == stored_restore_response
    with ReadSnapshot(factory) as snapshot:
        assert snapshot.connection.execute(
            "SELECT count(*) FROM audit_events WHERE command_id=?",
            (restore_command_id,),
        ).fetchone()[0] == 1
