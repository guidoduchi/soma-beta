from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass, field

import pytest

from soma.foundation.errors import SomaError
from soma.foundation.identifiers import new_uuid4
from soma.foundation.persistence.uow import ReadSnapshot, UnitOfWork
from soma.foundation.strict_json import canonical_json_bytes
from soma.tickets.queries.relationship_previews import (
    RfcHierarchyHistoryAuthority,
    RfcHierarchyPreviewQueryService,
    hierarchy_review_fingerprint,
)
from soma.tickets.queries.rfc_branches import RfcBranchQueryService
from soma.tickets.rfc_hierarchy import RfcHierarchyService
from soma.tickets.rfcs import RfcService


@dataclass
class _HistoryProvider:
    authority: object
    calls: list[tuple[object, str]] = field(default_factory=list)

    def hierarchy_history_authority(self, reader, rfc_id):
        self.calls.append((reader, rfc_id))
        assert reader.connection.in_transaction
        if isinstance(self.authority, Exception):
            raise self.authority
        return self.authority


def _ready(risk: str = "HIGH", count: int = 2, fingerprint: str = "a" * 64):
    return RfcHierarchyHistoryAuthority(
        status="READY",
        risk=risk,
        evidence_exact_count=count,
        provider_fingerprint=fingerprint,
        warning_code=None,
    )


def _indeterminate(warning: str = "TASK_HISTORY_UNAVAILABLE"):
    return RfcHierarchyHistoryAuthority(
        status="INDETERMINATE",
        risk=None,
        evidence_exact_count=None,
        provider_fingerprint=None,
        warning_code=warning,
    )


def _factory(initialized_database):
    database_path, factory_for_path = initialized_database
    return factory_for_path(database_path)


def _create_rfc(factory, serial: int):
    return RfcService(factory).create_or_adopt_identity(
        command_id=new_uuid4(),
        rfc_no=f"NC{serial:014d}",
        creation_context="manual",
    )


def _attach(factory, parent, child):
    return RfcHierarchyService(factory).add_subordinate(
        command_id=new_uuid4(),
        parent_rfc_id=parent.rfc_id,
        child_rfc_id=child.rfc_id,
        base_revisions={parent.rfc_id: parent.revision, child.rfc_id: child.revision},
        reason_category="manual_review",
    )


def _edge(factory, child_id: str):
    with ReadSnapshot(factory) as snapshot:
        return snapshot.connection.execute(
            "SELECT rfc_hierarchy_edge_id,parent_rfc_id,edge_state,opened_command_id,"
            "closed_command_id,closed_at_utc FROM rfc_hierarchy_edges "
            "WHERE child_rfc_id=? ORDER BY rowid",
            (child_id,),
        ).fetchall()


def _revisions(factory, *rfc_ids: str) -> dict[str, int]:
    with ReadSnapshot(factory) as snapshot:
        rows = snapshot.connection.execute(
            f"SELECT rfc_id,revision FROM rfcs WHERE rfc_id IN ({','.join('?' for _ in rfc_ids)})",
            tuple(rfc_ids),
        ).fetchall()
    return {str(row[0]): int(row[1]) for row in rows}


def _command_artifacts(factory, command_id: str) -> tuple[int, int, int]:
    with ReadSnapshot(factory) as snapshot:
        receipt = snapshot.connection.execute(
            "SELECT count(*) FROM command_receipts WHERE command_id=?",
            (command_id,),
        ).fetchone()[0]
        audit = snapshot.connection.execute(
            "SELECT count(*) FROM audit_events WHERE command_id=?",
            (command_id,),
        ).fetchone()[0]
        result = snapshot.connection.execute(
            "SELECT count(*) FROM command_receipt_results WHERE command_id=?",
            (command_id,),
        ).fetchone()[0]
    return int(receipt), int(audit), int(result)


def test_hierarchy_review_fingerprint_matches_certified_golden_vector() -> None:
    authority = {
        "schema": "SOMA_RFC_HIERARCHY_REVIEW_V1",
        "action": "reparent",
        "child_rfc_id": "00000000-0000-4000-8000-000000000002",
        "old_parent_rfc_id": "00000000-0000-4000-8000-000000000001",
        "new_parent_rfc_id": "00000000-0000-4000-8000-000000000003",
        "old_edge_id": "00000000-0000-4000-8000-000000000010",
        "old_branch_fingerprint": "12de7e3643a0d3a49cfce579db40c54cc704e5d06b44e6455c277dd2d4da0ea5",
        "new_branch_fingerprint": "a" * 64,
        "history_risk": "HIGH",
        "history_evidence_exact_count": 2,
        "history_provider_fingerprint": "b" * 64,
        "blockers": [],
        "warnings": [],
    }
    assert len(canonical_json_bytes(authority)) == 651
    assert hierarchy_review_fingerprint(
        action="reparent",
        child_rfc_id=authority["child_rfc_id"],
        old_parent_rfc_id=authority["old_parent_rfc_id"],
        new_parent_rfc_id=authority["new_parent_rfc_id"],
        old_edge_id=authority["old_edge_id"],
        old_branch_fingerprint=authority["old_branch_fingerprint"],
        new_branch_fingerprint=authority["new_branch_fingerprint"],
        history_risk="HIGH",
        history_evidence_exact_count=2,
        history_provider_fingerprint="b" * 64,
        blockers=(),
        warnings=(),
    ) == "4a56f5220d8cf52271f4c7ae81ee024f99707910bc5a920dcd7244f8e5850360"


def test_preview_uses_one_stable_snapshot_and_server_resolves_authority(initialized_database) -> None:
    factory = _factory(initialized_database)
    old_parent = _create_rfc(factory, 1)
    child = _create_rfc(factory, 2)
    new_parent = _create_rfc(factory, 3)
    _attach(factory, old_parent, child)
    provider = _HistoryProvider(_ready())

    preview = RfcHierarchyPreviewQueryService(factory, provider).preview(
        action="reparent",
        child_rfc_id=child.rfc_id,
        new_parent_rfc_id=new_parent.rfc_id,
    )

    assert len(provider.calls) == 1
    assert isinstance(provider.calls[0][0], ReadSnapshot)
    assert provider.calls[0][1] == child.rfc_id
    assert preview.old_parent_rfc_id == old_parent.rfc_id
    assert preview.old_edge_id == _edge(factory, child.rfc_id)[0][0]
    assert preview.base_revisions == {
        old_parent.rfc_id: 2,
        child.rfc_id: 2,
        new_parent.rfc_id: 1,
    }
    assert preview.history_authority == _ready()
    assert preview.review_required
    assert preview.review_fingerprint is not None
    assert preview.new_branch_fingerprint == RfcBranchQueryService(factory).get(
        root_rfc_id=new_parent.rfc_id
    ).branch_fingerprint
    assert preview.warnings == ("RFC_CUSTOMER_UNRESOLVED",)
    assert preview.blockers == ()


def test_reparent_preserves_old_edge_history_and_replays_exact_result(
    initialized_database,
    monkeypatch,
) -> None:
    factory = _factory(initialized_database)
    old_parent = _create_rfc(factory, 11)
    child = _create_rfc(factory, 12)
    new_parent = _create_rfc(factory, 13)
    _attach(factory, old_parent, child)
    provider = _HistoryProvider(_ready())
    preview = RfcHierarchyPreviewQueryService(factory, provider).preview(
        action="reparent", child_rfc_id=child.rfc_id, new_parent_rfc_id=new_parent.rfc_id
    )
    command_id = new_uuid4()
    service = RfcHierarchyService(factory, provider)

    result = service.reparent_subordinate(
        command_id=command_id,
        child_rfc_id=child.rfc_id,
        new_parent_rfc_id=new_parent.rfc_id,
        base_revisions=preview.base_revisions,
        reason_category="reviewed_correction",
        review_fingerprint=preview.review_fingerprint,
    )
    original = result.to_response()

    assert result.root.rfc_id == new_parent.rfc_id
    assert result.root.revision == 2
    assert result.root.subordinate_count == 1
    assert len(result.subordinates) == 1
    assert result.subordinates[0].rfc_id == child.rfc_id
    assert result.subordinates[0].revision == 3
    assert isinstance(provider.calls[-1][0], UnitOfWork)
    assert provider.calls[-1][1] == child.rfc_id
    rows = _edge(factory, child.rfc_id)
    assert len(rows) == 2
    old_row = next(row for row in rows if row[0] == preview.old_edge_id)
    new_row = next(row for row in rows if row[2] == "active")
    assert old_row[1] == old_parent.rfc_id
    assert old_row[2] == "superseded"
    assert old_row[4] == command_id and old_row[5] is not None
    assert new_row[0] != preview.old_edge_id
    assert new_row[1] == new_parent.rfc_id
    assert new_row[3] == command_id
    assert new_row[4] is None and new_row[5] is None
    assert _revisions(factory, old_parent.rfc_id, child.rfc_id, new_parent.rfc_id) == {
        old_parent.rfc_id: 3,
        child.rfc_id: 3,
        new_parent.rfc_id: 2,
    }
    with ReadSnapshot(factory) as snapshot:
        audit = snapshot.connection.execute(
            "SELECT payload_json FROM audit_events WHERE command_id=?",
            (command_id,),
        ).fetchone()
        assert json.loads(audit[0]) == {
            "rfc_id": child.rfc_id,
            "relationship_id": new_row[0],
            "prior_parent_rfc_id": old_parent.rfc_id,
            "new_parent_rfc_id": new_parent.rfc_id,
            "resulting_revision": 3,
            "reason_category": "reviewed_correction",
            "review_fingerprint": preview.review_fingerprint,
        }
        assert snapshot.connection.execute(
            "SELECT response_schema,response_version FROM command_receipt_results WHERE command_id=?",
            (command_id,),
        ).fetchone() == ("RfcBranchV1", 1)

    provider.authority = RuntimeError("replay must not call history provider")
    calls_before = len(provider.calls)
    monkeypatch.setattr(
        service._branch_query,
        "get_from_connection",
        lambda *args, **kwargs: pytest.fail("replay must not read current branch state"),
    )
    replay = service.reparent_subordinate(
        command_id=command_id,
        child_rfc_id=child.rfc_id,
        new_parent_rfc_id=new_parent.rfc_id,
        base_revisions=preview.base_revisions,
        reason_category="reviewed_correction",
        review_fingerprint=preview.review_fingerprint,
    )
    assert replay.to_response() == original
    assert len(provider.calls) == calls_before
    assert _command_artifacts(factory, command_id) == (1, 1, 1)


@pytest.mark.parametrize("action", ["reparent", "detach"])
@pytest.mark.parametrize("change", ["provider_fingerprint", "exact_count"])
def test_same_hierarchy_and_same_high_risk_with_changed_history_stales_review(
    initialized_database,
    action,
    change,
) -> None:
    factory = _factory(initialized_database)
    old_parent = _create_rfc(factory, 21)
    child = _create_rfc(factory, 22)
    new_parent = _create_rfc(factory, 23)
    _attach(factory, old_parent, child)
    provider = _HistoryProvider(_ready("HIGH", 2, "a" * 64))
    query = RfcHierarchyPreviewQueryService(factory, provider)
    preview = query.preview(
        action=action,
        child_rfc_id=child.rfc_id,
        new_parent_rfc_id=new_parent.rfc_id if action == "reparent" else None,
    )
    before_branch = RfcBranchQueryService(factory).get(root_rfc_id=old_parent.rfc_id).branch_fingerprint
    before_revisions = _revisions(factory, old_parent.rfc_id, child.rfc_id, new_parent.rfc_id)
    old_edge_id = preview.old_edge_id
    provider.authority = (
        _ready("HIGH", 2, "b" * 64)
        if change == "provider_fingerprint"
        else _ready("HIGH", 3, "a" * 64)
    )
    command_id = new_uuid4()
    service = RfcHierarchyService(factory, provider)

    with pytest.raises(SomaError, match="TICKET_RELATIONSHIP_STALE") as error:
        if action == "reparent":
            service.reparent_subordinate(
                command_id=command_id,
                child_rfc_id=child.rfc_id,
                new_parent_rfc_id=new_parent.rfc_id,
                base_revisions=preview.base_revisions,
                reason_category="reviewed_correction",
                review_fingerprint=preview.review_fingerprint,
            )
        else:
            service.detach_subordinate(
                command_id=command_id,
                child_rfc_id=child.rfc_id,
                base_revisions=preview.base_revisions,
                reason_category="reviewed_correction",
                review_fingerprint=preview.review_fingerprint,
            )
    assert error.value.code == "TICKET_RELATIONSHIP_STALE"
    assert RfcBranchQueryService(factory).get(root_rfc_id=old_parent.rfc_id).branch_fingerprint == before_branch
    assert _revisions(factory, old_parent.rfc_id, child.rfc_id, new_parent.rfc_id) == before_revisions
    rows = _edge(factory, child.rfc_id)
    assert len(rows) == 1
    assert rows[0][0] == old_edge_id and rows[0][2] == "active"
    assert rows[0][4] is None and rows[0][5] is None
    assert _command_artifacts(factory, command_id) == (0, 0, 0)


def test_high_risk_requires_exact_review_before_any_mutation(initialized_database) -> None:
    factory = _factory(initialized_database)
    old_parent = _create_rfc(factory, 31)
    child = _create_rfc(factory, 32)
    new_parent = _create_rfc(factory, 33)
    _attach(factory, old_parent, child)
    provider = _HistoryProvider(_ready("HIGH", 1, "c" * 64))
    preview = RfcHierarchyPreviewQueryService(factory, provider).preview(
        action="reparent", child_rfc_id=child.rfc_id, new_parent_rfc_id=new_parent.rfc_id
    )
    command_id = new_uuid4()

    with pytest.raises(SomaError, match="RFC_REPARENT_REVIEW_REQUIRED") as error:
        RfcHierarchyService(factory, provider).reparent_subordinate(
            command_id=command_id,
            child_rfc_id=child.rfc_id,
            new_parent_rfc_id=new_parent.rfc_id,
            base_revisions=preview.base_revisions,
            reason_category="reviewed_correction",
            review_fingerprint=None,
        )
    assert error.value.code == "RFC_REPARENT_REVIEW_REQUIRED"
    assert _command_artifacts(factory, command_id) == (0, 0, 0)
    assert len(_edge(factory, child.rfc_id)) == 1


def test_detach_low_risk_allows_null_review_and_recomputes_roles(initialized_database) -> None:
    factory = _factory(initialized_database)
    old_parent = _create_rfc(factory, 41)
    child = _create_rfc(factory, 42)
    _attach(factory, old_parent, child)
    provider = _HistoryProvider(_ready("LOW", 0, "d" * 64))
    preview = RfcHierarchyPreviewQueryService(factory, provider).preview(
        action="detach", child_rfc_id=child.rfc_id
    )
    assert not preview.review_required
    assert preview.review_fingerprint is not None
    assert preview.new_parent_rfc_id is None and preview.new_branch_fingerprint is None
    command_id = new_uuid4()

    result = RfcHierarchyService(factory, provider).detach_subordinate(
        command_id=command_id,
        child_rfc_id=child.rfc_id,
        base_revisions=preview.base_revisions,
        reason_category="manual_review",
        review_fingerprint=None,
    )

    assert result.root.rfc_id == child.rfc_id
    assert result.root.hierarchy_role == "standalone"
    assert result.root.revision == 3
    assert result.root.subordinate_count == 0
    assert result.subordinates == ()
    rows = _edge(factory, child.rfc_id)
    assert len(rows) == 1
    assert rows[0][0] == preview.old_edge_id
    assert rows[0][2] == "superseded"
    assert rows[0][4] == command_id and rows[0][5] is not None
    assert _revisions(factory, old_parent.rfc_id, child.rfc_id) == {
        old_parent.rfc_id: 3,
        child.rfc_id: 3,
    }
    with ReadSnapshot(factory) as snapshot:
        payload = json.loads(
            snapshot.connection.execute(
                "SELECT payload_json FROM audit_events WHERE command_id=?",
                (command_id,),
            ).fetchone()[0]
        )
    assert payload["prior_parent_rfc_id"] == old_parent.rfc_id
    assert payload["new_parent_rfc_id"] is None
    assert payload["relationship_id"] == preview.old_edge_id
    assert payload["review_fingerprint"] is None


def test_indeterminate_history_authority_cannot_authorize_reparent(initialized_database) -> None:
    factory = _factory(initialized_database)
    old_parent = _create_rfc(factory, 51)
    child = _create_rfc(factory, 52)
    new_parent = _create_rfc(factory, 53)
    _attach(factory, old_parent, child)
    provider = _HistoryProvider(_indeterminate())
    preview = RfcHierarchyPreviewQueryService(factory, provider).preview(
        action="reparent", child_rfc_id=child.rfc_id, new_parent_rfc_id=new_parent.rfc_id
    )
    assert preview.history_authority.status == "INDETERMINATE"
    assert preview.review_fingerprint is None
    assert not preview.review_required
    command_id = new_uuid4()

    with pytest.raises(SomaError, match="TICKET_RELATIONSHIP_STALE"):
        RfcHierarchyService(factory, provider).reparent_subordinate(
            command_id=command_id,
            child_rfc_id=child.rfc_id,
            new_parent_rfc_id=new_parent.rfc_id,
            base_revisions=preview.base_revisions,
            reason_category="reviewed_correction",
            review_fingerprint=None,
        )
    assert _command_artifacts(factory, command_id) == (0, 0, 0)
    assert _edge(factory, child.rfc_id)[0][2] == "active"


def test_missing_history_provider_is_indeterminate_and_writer_fails_closed(initialized_database) -> None:
    factory = _factory(initialized_database)
    old_parent = _create_rfc(factory, 61)
    child = _create_rfc(factory, 62)
    new_parent = _create_rfc(factory, 63)
    _attach(factory, old_parent, child)
    preview = RfcHierarchyPreviewQueryService(factory).preview(
        action="reparent", child_rfc_id=child.rfc_id, new_parent_rfc_id=new_parent.rfc_id
    )
    assert preview.history_authority == RfcHierarchyHistoryAuthority(
        "INDETERMINATE", None, None, None, "RFC_HISTORY_RISK_PROVIDER_UNAVAILABLE"
    )
    assert preview.review_fingerprint is None
    command_id = new_uuid4()
    with pytest.raises(SomaError, match="TICKET_RELATIONSHIP_STALE"):
        RfcHierarchyService(factory).reparent_subordinate(
            command_id=command_id,
            child_rfc_id=child.rfc_id,
            new_parent_rfc_id=new_parent.rfc_id,
            base_revisions=preview.base_revisions,
            reason_category="manual_review",
        )
    assert _command_artifacts(factory, command_id) == (0, 0, 0)


def test_reparent_insert_failure_rolls_back_closed_edge_receipt_audit_and_revisions(
    initialized_database,
) -> None:
    factory = _factory(initialized_database)
    old_parent = _create_rfc(factory, 71)
    child = _create_rfc(factory, 72)
    new_parent = _create_rfc(factory, 73)
    _attach(factory, old_parent, child)
    provider = _HistoryProvider(_ready("HIGH", 1, "e" * 64))
    preview = RfcHierarchyPreviewQueryService(factory, provider).preview(
        action="reparent", child_rfc_id=child.rfc_id, new_parent_rfc_id=new_parent.rfc_id
    )
    before_revisions = _revisions(factory, old_parent.rfc_id, child.rfc_id, new_parent.rfc_id)
    with UnitOfWork(factory) as uow:
        uow.connection.execute(
            "CREATE TRIGGER test_reparent_insert_failure BEFORE INSERT ON rfc_hierarchy_edges "
            f"WHEN NEW.parent_rfc_id='{new_parent.rfc_id}' "
            "BEGIN SELECT RAISE(ABORT,'injected reparent insert failure'); END"
        )
    command_id = new_uuid4()

    with pytest.raises(sqlite3.IntegrityError, match="injected reparent insert failure"):
        RfcHierarchyService(factory, provider).reparent_subordinate(
            command_id=command_id,
            child_rfc_id=child.rfc_id,
            new_parent_rfc_id=new_parent.rfc_id,
            base_revisions=preview.base_revisions,
            reason_category="reviewed_correction",
            review_fingerprint=preview.review_fingerprint,
        )

    assert _command_artifacts(factory, command_id) == (0, 0, 0)
    assert _revisions(factory, old_parent.rfc_id, child.rfc_id, new_parent.rfc_id) == before_revisions
    rows = _edge(factory, child.rfc_id)
    assert len(rows) == 1
    assert rows[0][0] == preview.old_edge_id
    assert rows[0][2] == "active"
    assert rows[0][4] is None and rows[0][5] is None
