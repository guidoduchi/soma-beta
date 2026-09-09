from __future__ import annotations

import pytest

from soma.foundation.application.command_receipts import CommandReceipt, CommandReceiptStore
from soma.foundation.audit.writer import AuditWriter
from soma.foundation.errors import SomaError
from soma.foundation.identifiers import new_uuid4
from soma.foundation.persistence.uow import UnitOfWork
from soma.tickets.audit_registry import build_tickets_audit_registry
from soma.tickets.rfc_source_projection import (
    RfcAcceptedFieldDelta,
    RfcSourceProjectionService,
)
from soma.tickets.rfcs import RfcService


class _AcceptingEvidenceProvider:
    def validate_accepted_delta(self, uow, rfc_id, delta, evidence_id):
        return "VALID"

    def has_accepted_source_provenance(self, uow, rfc_id):
        return "YES"

    def source_freshness_token(self, uow, rfc_id):
        return "f" * 64


class _ExactTerminalCapture:
    def __init__(self) -> None:
        self.proposal_ids: list[str] = []

    def capture_pending(
        self,
        uow,
        *,
        trigger_rfc_id: str,
        terminal_epoch_id: str,
        terminal_status_class: str,
        terminal_status_evidence_id: str,
        accepted_command_id: str,
    ) -> str:
        projection = uow.connection.execute(
            "SELECT status_class,status_evidence_id,terminal_epoch_id FROM rfc_current_source_projection WHERE rfc_id=?",
            (trigger_rfc_id,),
        ).fetchone()
        assert projection is not None
        assert tuple(projection) == (
            terminal_status_class,
            terminal_status_evidence_id,
            terminal_epoch_id,
        )

        proposal_id = new_uuid4()
        revision_row = uow.connection.execute(
            "SELECT revision FROM rfcs WHERE rfc_id=?",
            (trigger_rfc_id,),
        ).fetchone()
        assert revision_row is not None
        uow.connection.execute(
            "INSERT INTO rfc_terminal_cascade_proposals("
            "rfc_terminal_cascade_proposal_id,trigger_rfc_id,terminal_epoch_id,terminal_status_class,"
            "terminal_status_evidence_id,scope_kind,scope_fingerprint,proposal_state,revision,created_at_utc,"
            "created_command_id,executed_at_utc,executed_command_id,superseded_at_utc,superseded_command_id"
            ") VALUES (?, ?, ?, ?, ?, 'root_branch', ?, 'pending', 1, 1, ?, NULL, NULL, NULL, NULL)",
            (
                proposal_id,
                trigger_rfc_id,
                terminal_epoch_id,
                terminal_status_class,
                terminal_status_evidence_id,
                "c" * 64,
                accepted_command_id,
            ),
        )
        uow.connection.execute(
            "INSERT INTO rfc_terminal_cascade_rfc_members("
            "rfc_terminal_cascade_proposal_id,rfc_id,captured_rfc_revision,captured_role,ordinal"
            ") VALUES (?, ?, ?, 'standalone', 0)",
            (proposal_id, trigger_rfc_id, int(revision_row[0])),
        )
        self.proposal_ids.append(proposal_id)
        return proposal_id


def _factory(initialized_database):
    database_path, factory_for_path = initialized_database
    return factory_for_path(database_path)


def _new_rfc(factory):
    return RfcService(factory).create_or_adopt_identity(
        command_id=new_uuid4(),
        rfc_no=f"NC{new_uuid4().replace('-', '')[:14].replace('a', '1').replace('b', '2').replace('c', '3').replace('d', '4').replace('e', '5').replace('f', '6')}",
        creation_context="manual",
    )


def _insert_outer_receipt(uow: UnitOfWork, command_id: str, rfc_id: str) -> None:
    CommandReceiptStore().insert(
        uow,
        CommandReceipt(
            command_id=command_id,
            command_type="AcceptReconciliationProposal",
            request_hash="0" * 64,
            target_type="reconciliation_proposal",
            target_id=rfc_id,
            committed_at_utc=1,
            result_type=None,
            result_id=None,
        ),
    )


def _summary(value: str, evidence_id: str) -> RfcAcceptedFieldDelta:
    return RfcAcceptedFieldDelta(
        field_key="summary",
        value_kind="text",
        value=value,
        evidence_id=evidence_id,
    )


def _status(
    value: str,
    status_class: str,
    evidence_id: str,
    *,
    authority: str = "enhanced_rfc",
) -> RfcAcceptedFieldDelta:
    return RfcAcceptedFieldDelta(
        field_key="status",
        value_kind="controlled",
        value=value,
        evidence_id=evidence_id,
        status_class=status_class,
        status_authority=authority,
    )


def _read_one(factory, sql: str, params=()):
    connection = factory.open_authoritative(read_only=True, require_wal=True)
    try:
        return connection.execute(sql, params).fetchone()
    finally:
        connection.close()


def test_nonterminal_source_projection_commits_exact_projection_and_registered_audit(initialized_database) -> None:
    factory = _factory(initialized_database)
    rfc = _new_rfc(factory)
    service = RfcSourceProjectionService(_AcceptingEvidenceProvider())
    command_id = new_uuid4()

    with UnitOfWork(factory) as uow:
        _insert_outer_receipt(uow, command_id, rfc.rfc_id)
        result = service.apply_accepted_field_deltas(
            uow,
            rfc_id=rfc.rfc_id,
            accepted_command_id=command_id,
            deltas=(
                _status("Implement", "implement_eligible", "status-evidence-1"),
                _summary("Planned maintenance", "summary-evidence-1"),
            ),
        )
        assert result.no_change is False
        assert result.changed_field_keys == ("summary", "status")
        assert result.source_evidence_ids == ("summary-evidence-1", "status-evidence-1")
        assert result.pending_cascade_proposal_id is None
        assert result.lifecycle_projection.accepted_source_state["summary_text"] == "Planned maintenance"
        assert result.lifecycle_projection.accepted_source_state["status_class"] == "implement_eligible"
        assert result.lifecycle_projection.terminal_epoch_id is None
        assert len(result.audit_events) == 1
        AuditWriter(build_tickets_audit_registry()).write(uow, result.audit_events[0])

    projection = _read_one(
        factory,
        "SELECT summary_text,summary_evidence_id,status_text,status_class,status_authority,status_evidence_id,"
        "terminal_epoch_id,revision FROM rfc_current_source_projection WHERE rfc_id=?",
        (rfc.rfc_id,),
    )
    assert tuple(projection) == (
        "Planned maintenance",
        "summary-evidence-1",
        "Implement",
        "implement_eligible",
        "enhanced_rfc",
        "status-evidence-1",
        None,
        1,
    )
    assert _read_one(
        factory,
        "SELECT action_type FROM audit_events WHERE command_id=? AND action_type='ticket.rfc.source_projection_applied'",
        (command_id,),
    )[0] == "ticket.rfc.source_projection_applied"


def test_equal_value_and_wfm_provisional_status_preserve_enhanced_authority(initialized_database) -> None:
    factory = _factory(initialized_database)
    rfc = _new_rfc(factory)
    service = RfcSourceProjectionService(_AcceptingEvidenceProvider())

    first_command = new_uuid4()
    with UnitOfWork(factory) as uow:
        _insert_outer_receipt(uow, first_command, rfc.rfc_id)
        first = service.apply_accepted_field_deltas(
            uow,
            rfc_id=rfc.rfc_id,
            accepted_command_id=first_command,
            deltas=(
                _summary("Stable summary", "summary-evidence-original"),
                _status("Implement", "implement_eligible", "status-evidence-enhanced"),
            ),
        )
        assert first.no_change is False

    second_command = new_uuid4()
    with UnitOfWork(factory) as uow:
        _insert_outer_receipt(uow, second_command, rfc.rfc_id)
        second = service.apply_accepted_field_deltas(
            uow,
            rfc_id=rfc.rfc_id,
            accepted_command_id=second_command,
            deltas=(
                _summary("Stable summary", "summary-evidence-newer"),
                _status(
                    "Cancelled",
                    "terminal_cancelled",
                    "status-evidence-wfm",
                    authority="wfm_provisional",
                ),
            ),
        )
        assert second.no_change is True
        assert second.changed_field_keys == ()
        assert second.audit_events == ()

    projection = _read_one(
        factory,
        "SELECT summary_evidence_id,status_text,status_class,status_authority,status_evidence_id,revision "
        "FROM rfc_current_source_projection WHERE rfc_id=?",
        (rfc.rfc_id,),
    )
    assert tuple(projection) == (
        "summary-evidence-original",
        "Implement",
        "implement_eligible",
        "enhanced_rfc",
        "status-evidence-enhanced",
        1,
    )


def test_terminal_entry_without_capture_rolls_back_projection_and_outer_receipt(initialized_database) -> None:
    factory = _factory(initialized_database)
    rfc = _new_rfc(factory)
    service = RfcSourceProjectionService(_AcceptingEvidenceProvider())
    command_id = new_uuid4()

    with pytest.raises(SomaError) as exc:
        with UnitOfWork(factory) as uow:
            _insert_outer_receipt(uow, command_id, rfc.rfc_id)
            service.apply_accepted_field_deltas(
                uow,
                rfc_id=rfc.rfc_id,
                accepted_command_id=command_id,
                deltas=(_status("Closed", "terminal_closed", "terminal-evidence-1"),),
            )
    assert exc.value.code == "RFC_TERMINAL_CASCADE_PARTICIPANT_FAILED"
    assert _read_one(
        factory,
        "SELECT 1 FROM rfc_current_source_projection WHERE rfc_id=?",
        (rfc.rfc_id,),
    ) is None
    assert _read_one(
        factory,
        "SELECT 1 FROM command_receipts WHERE command_id=?",
        (command_id,),
    ) is None


def test_terminal_repeat_and_correction_preserve_one_epoch_and_one_proposal(initialized_database) -> None:
    factory = _factory(initialized_database)
    rfc = _new_rfc(factory)
    capture = _ExactTerminalCapture()
    service = RfcSourceProjectionService(
        _AcceptingEvidenceProvider(),
        terminal_capture_participant=capture,
    )

    first_command = new_uuid4()
    with UnitOfWork(factory) as uow:
        _insert_outer_receipt(uow, first_command, rfc.rfc_id)
        first = service.apply_accepted_field_deltas(
            uow,
            rfc_id=rfc.rfc_id,
            accepted_command_id=first_command,
            deltas=(_status("Closed", "terminal_closed", "terminal-evidence-1"),),
        )
        first_epoch = first.lifecycle_projection.terminal_epoch_id
        first_proposal = first.pending_cascade_proposal_id
        assert first_epoch is not None
        assert first_proposal is not None

    repeat_command = new_uuid4()
    with UnitOfWork(factory) as uow:
        _insert_outer_receipt(uow, repeat_command, rfc.rfc_id)
        repeat = service.apply_accepted_field_deltas(
            uow,
            rfc_id=rfc.rfc_id,
            accepted_command_id=repeat_command,
            deltas=(_status("Closed", "terminal_closed", "terminal-evidence-newer"),),
        )
        assert repeat.no_change is True
        assert repeat.lifecycle_projection.terminal_epoch_id == first_epoch

    correction_command = new_uuid4()
    with UnitOfWork(factory) as uow:
        _insert_outer_receipt(uow, correction_command, rfc.rfc_id)
        corrected = service.apply_accepted_field_deltas(
            uow,
            rfc_id=rfc.rfc_id,
            accepted_command_id=correction_command,
            deltas=(_status("Cancelled", "terminal_cancelled", "terminal-evidence-2"),),
            review_fingerprint="a" * 64,
        )
        assert corrected.no_change is False
        assert corrected.lifecycle_projection.terminal_epoch_id == first_epoch
        assert corrected.pending_cascade_proposal_id is None

    assert len(capture.proposal_ids) == 1
    count = _read_one(
        factory,
        "SELECT COUNT(*) FROM rfc_terminal_cascade_proposals WHERE trigger_rfc_id=?",
        (rfc.rfc_id,),
    )[0]
    assert count == 1
    projection = _read_one(
        factory,
        "SELECT status_text,status_class,status_evidence_id,terminal_epoch_id,revision "
        "FROM rfc_current_source_projection WHERE rfc_id=?",
        (rfc.rfc_id,),
    )
    assert tuple(projection) == (
        "Cancelled",
        "terminal_cancelled",
        "terminal-evidence-2",
        first_epoch,
        2,
    )
    proposal = _read_one(
        factory,
        "SELECT rfc_terminal_cascade_proposal_id,proposal_state,revision FROM rfc_terminal_cascade_proposals "
        "WHERE trigger_rfc_id=?",
        (rfc.rfc_id,),
    )
    assert tuple(proposal) == (first_proposal, "pending", 1)


def test_terminal_reversal_requires_review_then_supersedes_only_pending_proposal(initialized_database) -> None:
    factory = _factory(initialized_database)
    rfc = _new_rfc(factory)
    capture = _ExactTerminalCapture()
    service = RfcSourceProjectionService(
        _AcceptingEvidenceProvider(),
        terminal_capture_participant=capture,
    )

    terminal_command = new_uuid4()
    with UnitOfWork(factory) as uow:
        _insert_outer_receipt(uow, terminal_command, rfc.rfc_id)
        terminal = service.apply_accepted_field_deltas(
            uow,
            rfc_id=rfc.rfc_id,
            accepted_command_id=terminal_command,
            deltas=(_status("Closed", "terminal_closed", "terminal-evidence-1"),),
        )
        epoch = terminal.lifecycle_projection.terminal_epoch_id
        proposal_id = terminal.pending_cascade_proposal_id
        assert epoch is not None and proposal_id is not None

    rejected_command = new_uuid4()
    with pytest.raises(SomaError) as exc:
        with UnitOfWork(factory) as uow:
            _insert_outer_receipt(uow, rejected_command, rfc.rfc_id)
            service.apply_accepted_field_deltas(
                uow,
                rfc_id=rfc.rfc_id,
                accepted_command_id=rejected_command,
                deltas=(_status("Implement", "implement_eligible", "nonterminal-evidence-1"),),
            )
    assert exc.value.code == "RFC_STATUS_REVERSAL_REVIEW_REQUIRED"
    assert _read_one(factory, "SELECT 1 FROM command_receipts WHERE command_id=?", (rejected_command,)) is None
    still_terminal = _read_one(
        factory,
        "SELECT status_class,terminal_epoch_id,revision FROM rfc_current_source_projection WHERE rfc_id=?",
        (rfc.rfc_id,),
    )
    assert tuple(still_terminal) == ("terminal_closed", epoch, 1)

    reversal_command = new_uuid4()
    with UnitOfWork(factory) as uow:
        _insert_outer_receipt(uow, reversal_command, rfc.rfc_id)
        reversed_result = service.apply_accepted_field_deltas(
            uow,
            rfc_id=rfc.rfc_id,
            accepted_command_id=reversal_command,
            deltas=(_status("Implement", "implement_eligible", "nonterminal-evidence-2"),),
            review_fingerprint="b" * 64,
        )
        assert reversed_result.lifecycle_projection.terminal_epoch_id is None
        assert reversed_result.lifecycle_projection.accepted_source_state["status_class"] == "implement_eligible"
        AuditWriter(build_tickets_audit_registry()).write(uow, reversed_result.audit_events[0])

    projection = _read_one(
        factory,
        "SELECT status_text,status_class,status_evidence_id,terminal_epoch_id,revision "
        "FROM rfc_current_source_projection WHERE rfc_id=?",
        (rfc.rfc_id,),
    )
    assert tuple(projection) == (
        "Implement",
        "implement_eligible",
        "nonterminal-evidence-2",
        None,
        2,
    )
    proposal = _read_one(
        factory,
        "SELECT proposal_state,revision,superseded_command_id FROM rfc_terminal_cascade_proposals "
        "WHERE rfc_terminal_cascade_proposal_id=?",
        (proposal_id,),
    )
    assert tuple(proposal) == ("superseded", 2, reversal_command)
