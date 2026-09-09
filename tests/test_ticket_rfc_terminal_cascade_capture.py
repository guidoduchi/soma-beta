from __future__ import annotations

from dataclasses import dataclass

import pytest

from soma.foundation.application.command_receipts import CommandReceipt, CommandReceiptStore
from soma.foundation.errors import SomaError
from soma.foundation.identifiers import new_uuid4
from soma.foundation.persistence.uow import UnitOfWork
from soma.foundation.strict_json import canonical_json_bytes
from soma.tickets.rfc_hierarchy import RfcHierarchyService
from soma.tickets.rfc_source_projection import RfcAcceptedFieldDelta, RfcSourceProjectionService
from soma.tickets.rfc_terminal_cascade import (
    RfcTerminalCascadeCaptureService,
    RfcTerminalCascadeRfcMember,
    RfcTerminalCascadeWfmMember,
    terminal_cascade_scope_fingerprint,
    terminal_cascade_scope_payload,
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

    def __post_init__(self) -> None:
        self.calls: list[tuple[str, ...]] = []

    def capture_applicable_wfms(self, uow, rfc_ids):
        self.calls.append(tuple(rfc_ids))
        return self.members


class _ExplodingTaskParticipant:
    def capture_applicable_wfms(self, uow, rfc_ids):
        raise RuntimeError("provider failure")


def _factory(initialized_database):
    database_path, factory_for_path = initialized_database
    return factory_for_path(database_path)


def _read(factory, sql: str, params=()):
    connection = factory.open_authoritative(read_only=True, require_wal=True)
    try:
        return connection.execute(sql, params).fetchall()
    finally:
        connection.close()


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


def test_terminal_cascade_scope_fingerprint_matches_design_golden_vectors() -> None:
    exact_rfc_members = (
        RfcTerminalCascadeRfcMember(
            rfc_id="00000000-0000-4000-8000-000000000002",
            captured_rfc_revision=2,
            captured_role="subordinate",
        ),
    )
    exact_payload = terminal_cascade_scope_payload(
        trigger_rfc_id="00000000-0000-4000-8000-000000000002",
        terminal_epoch_id="00000000-0000-4000-8000-000000000020",
        terminal_status_class="terminal_closed",
        terminal_status_evidence_id="evidence-terminal-001",
        scope_kind="exact_rfc",
        rfc_members=exact_rfc_members,
        wfm_members=(),
    )
    assert len(canonical_json_bytes(exact_payload)) == 452
    assert terminal_cascade_scope_fingerprint(
        trigger_rfc_id="00000000-0000-4000-8000-000000000002",
        terminal_epoch_id="00000000-0000-4000-8000-000000000020",
        terminal_status_class="terminal_closed",
        terminal_status_evidence_id="evidence-terminal-001",
        scope_kind="exact_rfc",
        rfc_members=exact_rfc_members,
        wfm_members=(),
    ) == "b2e7005ebe389fa18cfa0f978f21dab4507d9b44ece6b33fb8a19d9a563c849d"

    branch_rfc_members = (
        RfcTerminalCascadeRfcMember(
            rfc_id="00000000-0000-4000-8000-000000000001",
            captured_rfc_revision=5,
            captured_role="root",
        ),
        RfcTerminalCascadeRfcMember(
            rfc_id="00000000-0000-4000-8000-000000000002",
            captured_rfc_revision=3,
            captured_role="subordinate",
        ),
        RfcTerminalCascadeRfcMember(
            rfc_id="00000000-0000-4000-8000-000000000003",
            captured_rfc_revision=4,
            captured_role="subordinate",
        ),
    )
    branch_wfm_members = (
        RfcTerminalCascadeWfmMember(
            task_id="00000000-0000-4000-8000-000000000101",
            owning_rfc_id="00000000-0000-4000-8000-000000000001",
            captured_task_revision=7,
            captured_task_no="TK20260909000001",
        ),
        RfcTerminalCascadeWfmMember(
            task_id="00000000-0000-4000-8000-000000000102",
            owning_rfc_id="00000000-0000-4000-8000-000000000003",
            captured_task_revision=2,
            captured_task_no="TK20260909000002",
        ),
    )
    branch_payload = terminal_cascade_scope_payload(
        trigger_rfc_id="00000000-0000-4000-8000-000000000001",
        terminal_epoch_id="00000000-0000-4000-8000-000000000021",
        terminal_status_class="terminal_cancelled",
        terminal_status_evidence_id="evidence-terminal-002",
        scope_kind="root_branch",
        rfc_members=branch_rfc_members,
        wfm_members=branch_wfm_members,
    )
    assert len(canonical_json_bytes(branch_payload)) == 1003
    assert terminal_cascade_scope_fingerprint(
        trigger_rfc_id="00000000-0000-4000-8000-000000000001",
        terminal_epoch_id="00000000-0000-4000-8000-000000000021",
        terminal_status_class="terminal_cancelled",
        terminal_status_evidence_id="evidence-terminal-002",
        scope_kind="root_branch",
        rfc_members=branch_rfc_members,
        wfm_members=branch_wfm_members,
    ) == "92c926573a48d3036d92f56bac40801e73d79e102980a8d2156502c5e94f866c"


def test_root_terminal_capture_persists_exact_ordered_branch_and_wfms(initialized_database) -> None:
    factory = _factory(initialized_database)
    root = _new_rfc(factory, 20260909000001)
    child_a = _new_rfc(factory, 20260909000002)
    child_b = _new_rfc(factory, 20260909000003)
    children = sorted((child_a, child_b), key=lambda item: item.rfc_id)

    hierarchy = RfcHierarchyService(factory)
    root_revision = 1
    for child in reversed(children):
        hierarchy.add_subordinate(
            command_id=new_uuid4(),
            parent_rfc_id=root.rfc_id,
            child_rfc_id=child.rfc_id,
            base_revisions={root.rfc_id: root_revision, child.rfc_id: 1},
            reason_category="terminal_scope_setup",
        )
        root_revision += 1
    assert root_revision == 3

    task_root = RfcTerminalCascadeWfmMember(
        task_id=new_uuid4(),
        owning_rfc_id=root.rfc_id,
        captured_task_revision=7,
        captured_task_no=f"TK{1:014d}",
    )
    task_child = RfcTerminalCascadeWfmMember(
        task_id=new_uuid4(),
        owning_rfc_id=children[1].rfc_id,
        captured_task_revision=2,
        captured_task_no=f"TK{2:014d}",
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
        applied = source.apply_accepted_field_deltas(
            uow,
            rfc_id=root.rfc_id,
            accepted_command_id=command_id,
            deltas=(_status("Closed", "terminal_closed", "root-terminal-evidence"),),
        )
        proposal_id = applied.pending_cascade_proposal_id
        epoch_id = applied.lifecycle_projection.terminal_epoch_id
        assert proposal_id is not None and epoch_id is not None

    expected_rfc_ids = (root.rfc_id, *(child.rfc_id for child in children))
    assert participant.calls == [expected_rfc_ids]
    proposal = _read(
        factory,
        "SELECT trigger_rfc_id,terminal_epoch_id,terminal_status_class,terminal_status_evidence_id,"
        "scope_kind,scope_fingerprint,proposal_state,revision,created_command_id "
        "FROM rfc_terminal_cascade_proposals WHERE rfc_terminal_cascade_proposal_id=?",
        (proposal_id,),
    )[0]
    assert proposal[0] == root.rfc_id
    assert proposal[1] == epoch_id
    assert proposal[2] == "terminal_closed"
    assert proposal[3] == "root-terminal-evidence"
    assert proposal[4] == "root_branch"
    assert proposal[6:] == ("pending", 1, command_id)

    rfc_rows = _read(
        factory,
        "SELECT rfc_id,captured_rfc_revision,captured_role,ordinal "
        "FROM rfc_terminal_cascade_rfc_members WHERE rfc_terminal_cascade_proposal_id=? ORDER BY ordinal",
        (proposal_id,),
    )
    assert [(row[0], row[1], row[2], row[3]) for row in rfc_rows] == [
        (root.rfc_id, 3, "root", 0),
        (children[0].rfc_id, 2, "subordinate", 1),
        (children[1].rfc_id, 2, "subordinate", 2),
    ]

    expected_wfms = sorted((task_child, task_root), key=lambda item: (item.owning_rfc_id, item.task_id))
    wfm_rows = _read(
        factory,
        "SELECT task_id,owning_rfc_id,captured_task_revision,captured_task_no,ordinal "
        "FROM rfc_terminal_cascade_wfm_members WHERE rfc_terminal_cascade_proposal_id=? ORDER BY ordinal",
        (proposal_id,),
    )
    assert [(row[0], row[1], row[2], row[3], row[4]) for row in wfm_rows] == [
        (item.task_id, item.owning_rfc_id, item.captured_task_revision, item.captured_task_no, ordinal)
        for ordinal, item in enumerate(expected_wfms)
    ]

    persisted_rfc_members = tuple(
        RfcTerminalCascadeRfcMember(
            rfc_id=str(row[0]),
            captured_rfc_revision=int(row[1]),
            captured_role=str(row[2]),
        )
        for row in rfc_rows
    )
    persisted_wfm_members = tuple(
        RfcTerminalCascadeWfmMember(
            task_id=str(row[0]),
            owning_rfc_id=str(row[1]),
            captured_task_revision=int(row[2]),
            captured_task_no=str(row[3]),
        )
        for row in wfm_rows
    )
    assert proposal[5] == terminal_cascade_scope_fingerprint(
        trigger_rfc_id=root.rfc_id,
        terminal_epoch_id=epoch_id,
        terminal_status_class="terminal_closed",
        terminal_status_evidence_id="root-terminal-evidence",
        scope_kind="root_branch",
        rfc_members=persisted_rfc_members,
        wfm_members=persisted_wfm_members,
    )


def test_subordinate_terminal_capture_is_exact_rfc_scope(initialized_database) -> None:
    factory = _factory(initialized_database)
    root = _new_rfc(factory, 20260909000011)
    child = _new_rfc(factory, 20260909000012)
    RfcHierarchyService(factory).add_subordinate(
        command_id=new_uuid4(),
        parent_rfc_id=root.rfc_id,
        child_rfc_id=child.rfc_id,
        base_revisions={root.rfc_id: 1, child.rfc_id: 1},
        reason_category="terminal_scope_setup",
    )
    task = RfcTerminalCascadeWfmMember(
        task_id=new_uuid4(),
        owning_rfc_id=child.rfc_id,
        captured_task_revision=4,
        captured_task_no=f"TK{11:014d}",
    )
    participant = _TaskParticipant((task,))
    capture = RfcTerminalCascadeCaptureService(participant)
    source = RfcSourceProjectionService(
        _AcceptingEvidenceProvider(),
        terminal_capture_participant=capture,
    )
    command_id = new_uuid4()

    with UnitOfWork(factory) as uow:
        _insert_outer_receipt(uow, command_id, child.rfc_id)
        applied = source.apply_accepted_field_deltas(
            uow,
            rfc_id=child.rfc_id,
            accepted_command_id=command_id,
            deltas=(_status("Cancelled", "terminal_cancelled", "child-terminal-evidence"),),
        )
        proposal_id = applied.pending_cascade_proposal_id
        assert proposal_id is not None

    assert participant.calls == [(child.rfc_id,)]
    proposal = _read(
        factory,
        "SELECT scope_kind FROM rfc_terminal_cascade_proposals WHERE rfc_terminal_cascade_proposal_id=?",
        (proposal_id,),
    )[0]
    assert proposal[0] == "exact_rfc"
    members = _read(
        factory,
        "SELECT rfc_id,captured_rfc_revision,captured_role,ordinal FROM rfc_terminal_cascade_rfc_members "
        "WHERE rfc_terminal_cascade_proposal_id=? ORDER BY ordinal",
        (proposal_id,),
    )
    assert [tuple(row) for row in members] == [(child.rfc_id, 2, "subordinate", 0)]


def test_invalid_task_participant_rolls_back_terminal_projection_and_outer_receipt(initialized_database) -> None:
    factory = _factory(initialized_database)
    rfc = _new_rfc(factory, 20260909000021)
    invalid_member = RfcTerminalCascadeWfmMember(
        task_id=new_uuid4(),
        owning_rfc_id=new_uuid4(),
        captured_task_revision=1,
        captured_task_no=f"TK{21:014d}",
    )
    capture = RfcTerminalCascadeCaptureService(_TaskParticipant((invalid_member,)))
    source = RfcSourceProjectionService(
        _AcceptingEvidenceProvider(),
        terminal_capture_participant=capture,
    )
    command_id = new_uuid4()

    with pytest.raises(SomaError) as exc:
        with UnitOfWork(factory) as uow:
            _insert_outer_receipt(uow, command_id, rfc.rfc_id)
            source.apply_accepted_field_deltas(
                uow,
                rfc_id=rfc.rfc_id,
                accepted_command_id=command_id,
                deltas=(_status("Closed", "terminal_closed", "invalid-participant-evidence"),),
            )
    assert exc.value.code == "RFC_TERMINAL_CASCADE_PARTICIPANT_FAILED"
    assert _read(
        factory,
        "SELECT 1 FROM command_receipts WHERE command_id=?",
        (command_id,),
    ) == []
    assert _read(
        factory,
        "SELECT 1 FROM rfc_current_source_projection WHERE rfc_id=?",
        (rfc.rfc_id,),
    ) == []
    assert _read(
        factory,
        "SELECT 1 FROM rfc_terminal_cascade_proposals WHERE trigger_rfc_id=?",
        (rfc.rfc_id,),
    ) == []


def test_task_participant_exception_rolls_back_terminal_capture(initialized_database) -> None:
    factory = _factory(initialized_database)
    rfc = _new_rfc(factory, 20260909000031)
    capture = RfcTerminalCascadeCaptureService(_ExplodingTaskParticipant())
    source = RfcSourceProjectionService(
        _AcceptingEvidenceProvider(),
        terminal_capture_participant=capture,
    )
    command_id = new_uuid4()

    with pytest.raises(SomaError) as exc:
        with UnitOfWork(factory) as uow:
            _insert_outer_receipt(uow, command_id, rfc.rfc_id)
            source.apply_accepted_field_deltas(
                uow,
                rfc_id=rfc.rfc_id,
                accepted_command_id=command_id,
                deltas=(_status("Closed", "terminal_closed", "participant-exception-evidence"),),
            )
    assert exc.value.code == "RFC_TERMINAL_CASCADE_PARTICIPANT_FAILED"
    assert _read(factory, "SELECT 1 FROM command_receipts WHERE command_id=?", (command_id,)) == []
    assert _read(factory, "SELECT 1 FROM rfc_terminal_cascade_proposals WHERE trigger_rfc_id=?", (rfc.rfc_id,)) == []


def test_terminal_correction_preserves_proposal_history_but_changes_current_scope_fingerprint(initialized_database) -> None:
    factory = _factory(initialized_database)
    rfc = _new_rfc(factory, 20260909000041)
    participant = _TaskParticipant()
    capture = RfcTerminalCascadeCaptureService(participant)
    source = RfcSourceProjectionService(
        _AcceptingEvidenceProvider(),
        terminal_capture_participant=capture,
    )

    first_command = new_uuid4()
    with UnitOfWork(factory) as uow:
        _insert_outer_receipt(uow, first_command, rfc.rfc_id)
        first = source.apply_accepted_field_deltas(
            uow,
            rfc_id=rfc.rfc_id,
            accepted_command_id=first_command,
            deltas=(_status("Closed", "terminal_closed", "terminal-evidence-old"),),
        )
        proposal_id = first.pending_cascade_proposal_id
        epoch_id = first.lifecycle_projection.terminal_epoch_id
        assert proposal_id is not None and epoch_id is not None

    original = _read(
        factory,
        "SELECT terminal_status_class,terminal_status_evidence_id,scope_fingerprint,proposal_state,revision "
        "FROM rfc_terminal_cascade_proposals WHERE rfc_terminal_cascade_proposal_id=?",
        (proposal_id,),
    )[0]

    correction_command = new_uuid4()
    with UnitOfWork(factory) as uow:
        _insert_outer_receipt(uow, correction_command, rfc.rfc_id)
        corrected = source.apply_accepted_field_deltas(
            uow,
            rfc_id=rfc.rfc_id,
            accepted_command_id=correction_command,
            deltas=(_status("Cancelled", "terminal_cancelled", "terminal-evidence-new"),),
            review_fingerprint="a" * 64,
        )
        assert corrected.lifecycle_projection.terminal_epoch_id == epoch_id
        current_scope = capture.capture_scope(
            uow,
            trigger_rfc_id=rfc.rfc_id,
            terminal_epoch_id=epoch_id,
            terminal_status_class="terminal_cancelled",
            terminal_status_evidence_id="terminal-evidence-new",
        )

    after = _read(
        factory,
        "SELECT terminal_status_class,terminal_status_evidence_id,scope_fingerprint,proposal_state,revision "
        "FROM rfc_terminal_cascade_proposals WHERE rfc_terminal_cascade_proposal_id=?",
        (proposal_id,),
    )[0]
    assert tuple(after) == tuple(original)
    assert tuple(after[:2]) == ("terminal_closed", "terminal-evidence-old")
    assert tuple(after[3:]) == ("pending", 1)
    assert current_scope.scope_fingerprint != str(after[2])
