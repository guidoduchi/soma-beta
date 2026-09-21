from __future__ import annotations

import pytest

from soma.foundation.application.command_receipts import CommandReceipt, CommandReceiptStore
from soma.foundation.errors import SomaError
from soma.foundation.identifiers import new_uuid4
from soma.foundation.persistence.uow import UnitOfWork
from soma.tickets.rfc_source_projection import RfcAcceptedFieldDelta, RfcSourceProjectionService
from soma.tickets.rfcs import RfcService


class _AcceptingEvidenceProvider:
    def validate_accepted_delta(self, uow, rfc_id, delta, evidence_id):
        return "VALID"

    def has_accepted_source_provenance(self, uow, rfc_id):
        return "YES"

    def source_freshness_token(self, uow, rfc_id):
        return "f" * 64


class _FailAfterProposalInsert:
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
                "d" * 64,
                accepted_command_id,
            ),
        )
        raise RuntimeError("injected terminal capture failure before membership")


class _ProposalWithoutTriggerMembership:
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
        proposal_id = new_uuid4()
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
                "e" * 64,
                accepted_command_id,
            ),
        )
        return proposal_id


def _factory(initialized_database):
    database_path, factory_for_path = initialized_database
    return factory_for_path(database_path)


def _new_rfc(factory):
    suffix = new_uuid4().replace("-", "")[:14]
    for source, replacement in zip("abcdef", "123456", strict=True):
        suffix = suffix.replace(source, replacement)
    return RfcService(factory).create_or_adopt_identity(
        command_id=new_uuid4(),
        rfc_no=f"NC{suffix}",
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


def _terminal_delta(evidence_id: str) -> RfcAcceptedFieldDelta:
    return RfcAcceptedFieldDelta(
        field_key="status",
        value_kind="controlled",
        value="Closed",
        evidence_id=evidence_id,
        status_class="terminal_closed",
        status_authority="enhanced_rfc",
    )


def _read_one(factory, sql: str, params=()):
    connection = factory.open_authoritative(read_only=True, require_wal=True)
    try:
        return connection.execute(sql, params).fetchone()
    finally:
        connection.close()


def _assert_no_terminal_acceptance_survived(factory, rfc_id: str, command_id: str) -> None:
    assert _read_one(
        factory,
        "SELECT 1 FROM rfc_current_source_projection WHERE rfc_id=?",
        (rfc_id,),
    ) is None
    assert _read_one(
        factory,
        "SELECT 1 FROM rfc_terminal_cascade_proposals WHERE trigger_rfc_id=?",
        (rfc_id,),
    ) is None
    assert _read_one(
        factory,
        "SELECT 1 FROM command_receipts WHERE command_id=?",
        (command_id,),
    ) is None


def test_partial_terminal_capture_rolls_back_projection_proposal_and_outer_receipt(initialized_database) -> None:
    factory = _factory(initialized_database)
    rfc = _new_rfc(factory)
    service = RfcSourceProjectionService(
        _AcceptingEvidenceProvider(),
        terminal_capture_participant=_FailAfterProposalInsert(),
    )
    command_id = new_uuid4()

    with pytest.raises(RuntimeError, match="injected terminal capture failure"):
        with UnitOfWork(factory) as uow:
            _insert_outer_receipt(uow, command_id, rfc.rfc_id)
            service.apply_accepted_field_deltas(
                uow,
                rfc_id=rfc.rfc_id,
                accepted_command_id=command_id,
                deltas=(_terminal_delta("terminal-evidence-fi002"),),
            )

    _assert_no_terminal_acceptance_survived(factory, rfc.rfc_id, command_id)


def test_capture_that_omits_triggering_rfc_membership_is_rejected_and_rolled_back(initialized_database) -> None:
    factory = _factory(initialized_database)
    rfc = _new_rfc(factory)
    service = RfcSourceProjectionService(
        _AcceptingEvidenceProvider(),
        terminal_capture_participant=_ProposalWithoutTriggerMembership(),
    )
    command_id = new_uuid4()

    with pytest.raises(SomaError) as exc:
        with UnitOfWork(factory) as uow:
            _insert_outer_receipt(uow, command_id, rfc.rfc_id)
            service.apply_accepted_field_deltas(
                uow,
                rfc_id=rfc.rfc_id,
                accepted_command_id=command_id,
                deltas=(_terminal_delta("terminal-evidence-membership"),),
            )
    assert exc.value.code == "RFC_TERMINAL_CASCADE_PARTICIPANT_FAILED"
    _assert_no_terminal_acceptance_survived(factory, rfc.rfc_id, command_id)
