from __future__ import annotations

from soma.foundation.identifiers import new_uuid4
from soma.foundation.persistence.uow import ReadSnapshot
from soma.foundation.strict_json import sha256_canonical_json
from soma.tickets.queries.rfc_branches import RfcBranchQueryService
from soma.tickets.rfc_hierarchy import RfcHierarchyService
from soma.tickets.rfcs import RfcService


class _Rows:
    def __init__(self, rows):
        self._rows = list(rows)

    def fetchone(self):
        return None if not self._rows else self._rows[0]

    def __iter__(self):
        return iter(self._rows)


class _GoldenFingerprintConnection:
    def execute(self, sql, params=()):
        if sql.startswith("SELECT rfc_id,revision,customer_org_id,local_archive_state FROM rfcs"):
            return _Rows(
                [
                    (
                        "00000000-0000-4000-8000-000000000001",
                        2,
                        None,
                        "active",
                    )
                ]
            )
        if sql.startswith("SELECT 1 FROM rfc_hierarchy_edges WHERE child_rfc_id"):
            return _Rows([])
        if sql.startswith("SELECT e.rfc_hierarchy_edge_id,c.rfc_id,c.revision"):
            return _Rows(
                [
                    (
                        "00000000-0000-4000-8000-000000000010",
                        "00000000-0000-4000-8000-000000000002",
                        3,
                        "00000000-0000-4000-8000-000000000100",
                        "active",
                    )
                ]
            )
        raise AssertionError(f"unexpected SQL in golden fingerprint fixture: {sql}")


def _factory(initialized_database):
    database_path, factory_for_path = initialized_database
    return factory_for_path(database_path)


def _create_rfc(factory, serial: int):
    return RfcService(factory).create_or_adopt_identity(
        command_id=new_uuid4(),
        rfc_no=f"NC{serial:014d}",
        creation_context="manual",
    )


def _add(
    service: RfcHierarchyService,
    *,
    command_id: str,
    parent_id: str,
    child_id: str,
    parent_revision: int,
    child_revision: int,
):
    return service.add_subordinate(
        command_id=command_id,
        parent_rfc_id=parent_id,
        child_rfc_id=child_id,
        base_revisions={parent_id: parent_revision, child_id: child_revision},
        reason_category="manual_review",
    )


def test_rfc_branch_fingerprint_matches_binding_golden_vector() -> None:
    fingerprint = RfcBranchQueryService.branch_fingerprint_from_connection(
        _GoldenFingerprintConnection(),
        "00000000-0000-4000-8000-000000000001",
    )
    assert fingerprint == "12de7e3643a0d3a49cfce579db40c54cc704e5d06b44e6455c277dd2d4da0ea5"


def test_rfc_branch_query_is_keyset_paged_with_page_independent_fingerprint(initialized_database) -> None:
    factory = _factory(initialized_database)
    root = _create_rfc(factory, 1)
    child_a = _create_rfc(factory, 2)
    child_b = _create_rfc(factory, 3)
    hierarchy = RfcHierarchyService(factory)

    _add(
        hierarchy,
        command_id=new_uuid4(),
        parent_id=root.rfc_id,
        child_id=child_a.rfc_id,
        parent_revision=1,
        child_revision=1,
    )
    _add(
        hierarchy,
        command_id=new_uuid4(),
        parent_id=root.rfc_id,
        child_id=child_b.rfc_id,
        parent_revision=2,
        child_revision=1,
    )

    query = RfcBranchQueryService(factory)
    first = query.get(root_rfc_id=root.rfc_id, limit=1)
    assert len(first.subordinates) == 1
    assert first.continuation is not None
    assert first.continuation == {
        "version": 1,
        "query_id": "GetRfcBranch",
        "sort_registry_id": "RFC_BRANCH_CHILD_ID_ASC_V1",
        "last_key_tuple": [first.subordinates[0].rfc_id],
        "filter_fingerprint": sha256_canonical_json(
            {"schema": "SOMA_RFC_BRANCH_FILTER_V1", "root_rfc_id": root.rfc_id}
        ),
        "null_order": "not_applicable",
    }

    second = query.get(
        root_rfc_id=root.rfc_id,
        cursor=first.continuation,
        limit=1,
    )
    expected_ids = sorted([child_a.rfc_id, child_b.rfc_id])
    assert [first.subordinates[0].rfc_id, second.subordinates[0].rfc_id] == expected_ids
    assert second.continuation is None
    assert first.branch_fingerprint == second.branch_fingerprint
    assert first.root.revision == second.root.revision == 3


def test_add_subordinate_replay_returns_original_branch_without_owner_reads(
    initialized_database,
    monkeypatch,
) -> None:
    factory = _factory(initialized_database)
    root = _create_rfc(factory, 11)
    child = _create_rfc(factory, 12)
    later_child = _create_rfc(factory, 13)
    hierarchy = RfcHierarchyService(factory)
    command_id = new_uuid4()

    first = _add(
        hierarchy,
        command_id=command_id,
        parent_id=root.rfc_id,
        child_id=child.rfc_id,
        parent_revision=1,
        child_revision=1,
    )
    original = first.to_response()
    assert first.root.revision == 2
    assert first.root.subordinate_count == 1
    assert len(first.subordinates) == 1
    assert first.subordinates[0].rfc_id == child.rfc_id
    assert first.subordinates[0].revision == 2

    _add(
        hierarchy,
        command_id=new_uuid4(),
        parent_id=root.rfc_id,
        child_id=later_child.rfc_id,
        parent_revision=2,
        child_revision=1,
    )
    current = RfcBranchQueryService(factory).get(root_rfc_id=root.rfc_id)
    assert current.root.revision == 3
    assert len(current.subordinates) == 2
    assert current.branch_fingerprint != first.branch_fingerprint

    monkeypatch.setattr(
        hierarchy._branch_query,
        "get_from_connection",
        lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("replay performed owner read")),
    )
    replay = _add(
        hierarchy,
        command_id=command_id,
        parent_id=root.rfc_id,
        child_id=child.rfc_id,
        parent_revision=1,
        child_revision=1,
    )

    assert replay.to_response() == original
    assert replay.root.revision == 2
    assert len(replay.subordinates) == 1
    with ReadSnapshot(factory) as snapshot:
        assert snapshot.connection.execute(
            "SELECT count(*) FROM audit_events WHERE command_id=?",
            (command_id,),
        ).fetchone()[0] == 1
        row = snapshot.connection.execute(
            "SELECT response_schema,response_version FROM command_receipt_results WHERE command_id=?",
            (command_id,),
        ).fetchone()
        assert tuple(row) == ("RfcBranchV1", 1)


def test_add_subordinate_no_change_replay_preserves_original_branch_snapshot(
    initialized_database,
    monkeypatch,
) -> None:
    factory = _factory(initialized_database)
    root = _create_rfc(factory, 21)
    child = _create_rfc(factory, 22)
    later_child = _create_rfc(factory, 23)
    hierarchy = RfcHierarchyService(factory)

    _add(
        hierarchy,
        command_id=new_uuid4(),
        parent_id=root.rfc_id,
        child_id=child.rfc_id,
        parent_revision=1,
        child_revision=1,
    )
    no_change_command_id = new_uuid4()
    no_change = _add(
        hierarchy,
        command_id=no_change_command_id,
        parent_id=root.rfc_id,
        child_id=child.rfc_id,
        parent_revision=2,
        child_revision=2,
    )
    original = no_change.to_response()
    assert no_change.root.revision == 2
    assert len(no_change.subordinates) == 1

    _add(
        hierarchy,
        command_id=new_uuid4(),
        parent_id=root.rfc_id,
        child_id=later_child.rfc_id,
        parent_revision=2,
        child_revision=1,
    )

    monkeypatch.setattr(
        hierarchy._branch_query,
        "get_from_connection",
        lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("NO_CHANGE replay performed owner read")),
    )
    replay = _add(
        hierarchy,
        command_id=no_change_command_id,
        parent_id=root.rfc_id,
        child_id=child.rfc_id,
        parent_revision=2,
        child_revision=2,
    )
    assert replay.to_response() == original

    with ReadSnapshot(factory) as snapshot:
        assert snapshot.connection.execute(
            "SELECT count(*) FROM audit_events WHERE command_id=?",
            (no_change_command_id,),
        ).fetchone()[0] == 0
        receipt = snapshot.connection.execute(
            "SELECT result_type FROM command_receipts WHERE command_id=?",
            (no_change_command_id,),
        ).fetchone()
        assert receipt[0] == "NO_CHANGE"
        result = snapshot.connection.execute(
            "SELECT response_schema,response_version FROM command_receipt_results WHERE command_id=?",
            (no_change_command_id,),
        ).fetchone()
        assert tuple(result) == ("RfcBranchV1", 1)
