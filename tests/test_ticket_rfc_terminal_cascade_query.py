from __future__ import annotations

from dataclasses import dataclass

import pytest

from soma.foundation.application.command_receipts import CommandReceipt, CommandReceiptStore
from soma.foundation.errors import SomaError, ValidationError
from soma.foundation.identifiers import new_uuid4, utc_epoch_seconds
from soma.foundation.persistence.uow import UnitOfWork
from soma.foundation.strict_json import sha256_canonical_json
from soma.tickets.queries.rfc_terminal_cascade import RfcTerminalCascadeQueryService
from soma.tickets.rfc_hierarchy import RfcHierarchyService
from soma.tickets.rfc_source_projection import RfcAcceptedFieldDelta, RfcSourceProjectionService
from soma.tickets.rfc_terminal_cascade import (
    RfcTerminalCascadeCaptureService,
    RfcTerminalCascadeWfmMember,
)
from soma.tickets.rfcs import RfcService


class _AcceptingEvidenceProvider:
    def validate_accepted_delta(self, uow, rfc_id, delta, evidence_id):
        return "VALID"

    def has_accepted_source_provenance(self, uow, rfc_id):
        return "YES"

    def source_freshness_token(self, uow, rfc_id):
        return "f" * 64


@dataclass
class _TaskParticipant:
    members: tuple[RfcTerminalCascadeWfmMember, ...] = ()

    def capture_applicable_wfms(self, uow, rfc_ids):
        return self.members


def _factory(initialized_database):
    database_path, factory_for_path = initialized_database
    return factory_for_path(database_path)


def _new_rfc(factory, sequence: int):
    return RfcService(factory).create_or_adopt_identity(
        command_id=new_uuid4(),
        rfc_no=f"NC{sequence:014d}",
        creation_context="manual",
    )


def _insert_outer_receipt(uow: UnitOfWork, command_id: str, target_id: str) -> None:
    CommandReceiptStore().insert(
        uow,
        CommandReceipt(
            command_id=command_id,
            command_type="AcceptReconciliationProposal",
            request_hash="0" * 64,
            target_type="reconciliation_proposal",
            target_id=target_id,
            committed_at_utc=1,
            result_type=None,
            result_id=None,
        ),
    )


def _status(value: str, status_class: str, evidence_id: str) -> RfcAcceptedFieldDelta:
    return RfcAcceptedFieldDelta(
        field_key="status",
        value_kind="controlled",
        value=value,
        evidence_id=evidence_id,
        status_class=status_class,
        status_authority="enhanced_rfc",
    )


def _terminal_root_with_members(factory):
    root = _new_rfc(factory, 20260909001001)
    child_a = _new_rfc(factory, 20260909001002)
    child_b = _new_rfc(factory, 20260909001003)
    children = sorted((child_a, child_b), key=lambda item: item.rfc_id)
    hierarchy = RfcHierarchyService(factory)
    root_revision = 1
    for child in reversed(children):
        hierarchy.add_subordinate(
            command_id=new_uuid4(),
            parent_rfc_id=root.rfc_id,
            child_rfc_id=child.rfc_id,
            base_revisions={root.rfc_id: root_revision, child.rfc_id: 1},
            reason_category="pending_query_setup",
        )
        root_revision += 1

    task_root = RfcTerminalCascadeWfmMember(
        task_id=new_uuid4(),
        owning_rfc_id=root.rfc_id,
        captured_task_revision=4,
        captured_task_no=f"TK{101:014d}",
    )
    task_child = RfcTerminalCascadeWfmMember(
        task_id=new_uuid4(),
        owning_rfc_id=children[1].rfc_id,
        captured_task_revision=6,
        captured_task_no=f"TK{102:014d}",
    )
    participant = _TaskParticipant((task_child, task_root))
    capture = RfcTerminalCascadeCaptureService(participant)
    source = RfcSourceProjectionService(
        _AcceptingEvidenceProvider(),
        terminal_capture_participant=capture,
    )
    command_id = new_uuid4()
    with UnitOfWork(factory) as uow:
        _insert_outer_receipt(uow, command_id, root.rfc_id)
        result = source.apply_accepted_field_deltas(
            uow,
            rfc_id=root.rfc_id,
            accepted_command_id=command_id,
            deltas=(_status("Closed", "terminal_closed", "pending-query-evidence"),),
        )
        proposal_id = result.pending_cascade_proposal_id
        epoch_id = result.lifecycle_projection.terminal_epoch_id
        assert proposal_id is not None and epoch_id is not None
    return root, children, hierarchy, capture, proposal_id, epoch_id, (task_root, task_child)


def test_pending_cascade_query_pages_persisted_rfc_then_wfm_members(initialized_database) -> None:
    factory = _factory(initialized_database)
    root, children, _hierarchy, _capture, proposal_id, epoch_id, tasks = _terminal_root_with_members(factory)
    query = RfcTerminalCascadeQueryService(factory)

    page1 = query.get(rfc_id=root.rfc_id, limit=2)
    assert page1.state.proposal_id == proposal_id
    assert page1.state.trigger_rfc_id == root.rfc_id
    assert page1.state.state == "pending"
    assert page1.state.proposal_revision == 1
    assert page1.state.terminal_epoch_id == epoch_id
    assert page1.state.terminal_status_class == "terminal_closed"
    assert page1.state.terminal_status_evidence_id == "pending-query-evidence"
    assert page1.state.scope_kind == "root_branch"
    assert page1.state.captured_rfc_count == 3
    assert page1.state.captured_wfm_count == 2
    assert [member.member_kind for member in page1.members] == ["rfc", "rfc"]
    assert [member.rfc_id for member in page1.members] == [root.rfc_id, children[0].rfc_id]
    assert page1.continuation is not None
    assert page1.continuation["query_id"] == "GetPendingRfcTerminalCascade"
    assert page1.continuation["sort_registry_id"] == "RFC_TERMINAL_CASCADE_MEMBER_ORDER_V1"
    assert page1.continuation["last_key_tuple"] == [0, 1, children[0].rfc_id]
    assert page1.continuation["null_order"] == "not_applicable"
    expected_filter = sha256_canonical_json(
        {
            "schema": "SOMA_RFC_TERMINAL_CASCADE_MEMBER_FILTER_V1",
            "rfc_id": root.rfc_id,
            "proposal_id": proposal_id,
            "proposal_revision": 1,
            "scope_fingerprint": page1.state.scope_fingerprint,
        }
    )
    assert page1.continuation["filter_fingerprint"] == expected_filter

    page2 = query.get(rfc_id=root.rfc_id, cursor=page1.continuation, limit=2)
    assert [member.member_kind for member in page2.members] == ["rfc", "wfm"]
    assert page2.members[0].rfc_id == children[1].rfc_id
    expected_tasks = sorted(tasks, key=lambda item: (item.owning_rfc_id, item.task_id))
    assert page2.members[1].task_id == expected_tasks[0].task_id
    assert page2.continuation is not None
    assert page2.continuation["last_key_tuple"] == [1, 0, expected_tasks[0].task_id]

    page3 = query.get(rfc_id=root.rfc_id, cursor=page2.continuation, limit=2)
    assert len(page3.members) == 1
    assert page3.members[0].member_kind == "wfm"
    assert page3.members[0].task_id == expected_tasks[1].task_id
    assert page3.continuation is None

    response = page1.to_response()
    assert set(response) == {"state", "members", "continuation"}
    assert response["state"]["scope_fingerprint"] == page1.state.scope_fingerprint
    assert response["members"][0]["member_kind"] == "rfc"


def test_pending_query_reads_immutable_capture_even_after_live_hierarchy_drift(initialized_database) -> None:
    factory = _factory(initialized_database)
    root, children, hierarchy, _capture, proposal_id, _epoch_id, _tasks = _terminal_root_with_members(factory)
    query = RfcTerminalCascadeQueryService(factory)
    before = query.get(rfc_id=root.rfc_id, limit=500)
    captured_ids_before = [
        member.rfc_id for member in before.members if member.member_kind == "rfc"
    ]

    later_child = _new_rfc(factory, 20260909001004)
    hierarchy.add_subordinate(
        command_id=new_uuid4(),
        parent_rfc_id=root.rfc_id,
        child_rfc_id=later_child.rfc_id,
        base_revisions={root.rfc_id: 3, later_child.rfc_id: 1},
        reason_category="post_capture_hierarchy_drift",
    )

    after = query.get(rfc_id=root.rfc_id, limit=500)
    assert after.state.proposal_id == proposal_id
    assert after.state.scope_fingerprint == before.state.scope_fingerprint
    assert after.state.captured_rfc_count == 3
    captured_ids_after = [
        member.rfc_id for member in after.members if member.member_kind == "rfc"
    ]
    assert captured_ids_after == captured_ids_before == [root.rfc_id, children[0].rfc_id, children[1].rfc_id]
    assert later_child.rfc_id not in captured_ids_after


def test_pending_cursor_is_rejected_after_proposal_replacement(initialized_database) -> None:
    factory = _factory(initialized_database)
    root, _children, _hierarchy, capture, old_proposal_id, epoch_id, _tasks = _terminal_root_with_members(factory)
    query = RfcTerminalCascadeQueryService(factory)
    old_page = query.get(rfc_id=root.rfc_id, limit=1)
    assert old_page.continuation is not None

    refresh_command = new_uuid4()
    with UnitOfWork(factory) as uow:
        _insert_outer_receipt(uow, refresh_command, old_proposal_id)
        updated = uow.connection.execute(
            "UPDATE rfc_terminal_cascade_proposals SET proposal_state='superseded',revision=revision+1,"
            "superseded_at_utc=?,superseded_command_id=? "
            "WHERE rfc_terminal_cascade_proposal_id=? AND proposal_state='pending' AND revision=1",
            (utc_epoch_seconds(), refresh_command, old_proposal_id),
        )
        assert updated.rowcount == 1
        new_proposal_id = capture.capture_pending(
            uow,
            trigger_rfc_id=root.rfc_id,
            terminal_epoch_id=epoch_id,
            terminal_status_class="terminal_closed",
            terminal_status_evidence_id="pending-query-evidence",
            accepted_command_id=refresh_command,
        )
        assert new_proposal_id != old_proposal_id

    current = query.get(rfc_id=root.rfc_id, limit=1)
    assert current.state.proposal_id == new_proposal_id
    with pytest.raises(ValidationError, match="filter fingerprint is stale"):
        query.get(rfc_id=root.rfc_id, cursor=old_page.continuation, limit=1)


def test_pending_query_distinguishes_missing_rfc_from_no_pending_proposal(initialized_database) -> None:
    factory = _factory(initialized_database)
    query = RfcTerminalCascadeQueryService(factory)
    rfc = _new_rfc(factory, 20260909001011)

    with pytest.raises(SomaError) as not_pending:
        query.get(rfc_id=rfc.rfc_id)
    assert not_pending.value.code == "RFC_TERMINAL_CASCADE_NOT_PENDING"

    with pytest.raises(SomaError) as missing:
        query.get(rfc_id=new_uuid4())
    assert missing.value.code == "NOT_FOUND"
