from __future__ import annotations

import json
from dataclasses import dataclass

import pytest

from soma.foundation.application.command_receipts import CommandReceipt, CommandReceiptStore
from soma.foundation.errors import SomaError
from soma.foundation.identifiers import new_uuid4
from soma.foundation.persistence.uow import ReadSnapshot, UnitOfWork
from soma.tickets.rfc_hierarchy import RfcHierarchyService
from soma.tickets.rfc_source_projection import RfcAcceptedFieldDelta, RfcSourceProjectionService
from soma.tickets.rfc_terminal_cascade import (
    RfcTerminalCascadeCaptureService,
    RfcTerminalCascadeRefreshService,
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
    fail_capture: bool = False

    def capture_applicable_wfms(self, uow, rfc_ids):
        if self.fail_capture:
            raise RuntimeError("injected Task participant failure")
        allowed = frozenset(rfc_ids)
        return tuple(member for member in self.members if member.owning_rfc_id in allowed)


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


def _terminal_standalone(factory, participant: _TaskParticipant):
    rfc = _new_rfc(factory, 20260909003001)
    capture = RfcTerminalCascadeCaptureService(participant)
    source = RfcSourceProjectionService(
        _AcceptingEvidenceProvider(),
        terminal_capture_participant=capture,
    )
    command_id = new_uuid4()
    with UnitOfWork(factory) as uow:
        _insert_outer_receipt(uow, command_id, rfc.rfc_id)
        applied = source.apply_accepted_field_deltas(
            uow,
            rfc_id=rfc.rfc_id,
            accepted_command_id=command_id,
            deltas=(_status("Closed", "terminal_closed", "refresh-evidence-1"),),
        )
        assert applied.pending_cascade_proposal_id is not None
        assert applied.lifecycle_projection.terminal_epoch_id is not None
        proposal_id = applied.pending_cascade_proposal_id
        epoch_id = applied.lifecycle_projection.terminal_epoch_id
    return rfc, source, proposal_id, epoch_id


def _proposal_row(factory, proposal_id: str):
    with ReadSnapshot(factory) as snapshot:
        return snapshot.connection.execute(
            "SELECT trigger_rfc_id,terminal_epoch_id,terminal_status_class,terminal_status_evidence_id,"
            "scope_kind,scope_fingerprint,proposal_state,revision,created_command_id,"
            "superseded_command_id FROM rfc_terminal_cascade_proposals "
            "WHERE rfc_terminal_cascade_proposal_id=?",
            (proposal_id,),
        ).fetchone()


def _receipt_row(factory, command_id: str):
    with ReadSnapshot(factory) as snapshot:
        return snapshot.connection.execute(
            "SELECT result_type,result_id FROM command_receipts WHERE command_id=?",
            (command_id,),
        ).fetchone()


def test_refresh_no_change_persists_exact_state_and_replays_without_owner_reads(
    initialized_database,
) -> None:
    factory = _factory(initialized_database)
    participant = _TaskParticipant()
    rfc, _source, proposal_id, epoch_id = _terminal_standalone(factory, participant)
    service = RfcTerminalCascadeRefreshService(factory, participant)
    command_id = new_uuid4()

    first = service.refresh(
        command_id=command_id,
        proposal_id=proposal_id,
        proposal_revision=1,
    )
    assert first.proposal_id == proposal_id
    assert first.trigger_rfc_id == rfc.rfc_id
    assert first.state == "pending"
    assert first.proposal_revision == 1
    assert first.terminal_epoch_id == epoch_id
    assert first.terminal_status_class == "terminal_closed"
    assert first.terminal_status_evidence_id == "refresh-evidence-1"
    assert first.captured_rfc_count == 1
    assert first.captured_wfm_count == 0
    assert first.no_change is True
    assert first.replayed is False
    assert _receipt_row(factory, command_id) == ("NO_CHANGE", None)

    later_child = _new_rfc(factory, 20260909003002)
    RfcHierarchyService(factory).add_subordinate(
        command_id=new_uuid4(),
        parent_rfc_id=rfc.rfc_id,
        child_rfc_id=later_child.rfc_id,
        base_revisions={rfc.rfc_id: 1, later_child.rfc_id: 1},
        reason_category="post_refresh_replay_drift",
    )

    participant.fail_capture = True
    replay = service.refresh(
        command_id=command_id,
        proposal_id=proposal_id,
        proposal_revision=1,
    )
    assert replay.to_response() == first.to_response()
    assert replay.no_change is True
    assert replay.replayed is True

    with ReadSnapshot(factory) as snapshot:
        assert snapshot.connection.execute(
            "SELECT COUNT(*) FROM audit_events WHERE command_id=?",
            (command_id,),
        ).fetchone()[0] == 0
        assert snapshot.connection.execute(
            "SELECT COUNT(*) FROM rfc_terminal_cascade_proposals WHERE terminal_epoch_id=?",
            (epoch_id,),
        ).fetchone()[0] == 1


def test_refresh_same_epoch_terminal_correction_replaces_pending_and_audits_exact_provenance(
    initialized_database,
) -> None:
    factory = _factory(initialized_database)
    participant = _TaskParticipant()
    rfc, source, old_proposal_id, epoch_id = _terminal_standalone(factory, participant)

    correction_command = new_uuid4()
    with UnitOfWork(factory) as uow:
        _insert_outer_receipt(uow, correction_command, rfc.rfc_id)
        correction = source.apply_accepted_field_deltas(
            uow,
            rfc_id=rfc.rfc_id,
            accepted_command_id=correction_command,
            deltas=(_status("Cancelled", "terminal_cancelled", "refresh-evidence-2"),),
        )
        assert correction.lifecycle_projection.terminal_epoch_id == epoch_id
        assert correction.pending_cascade_proposal_id is None

    refresh_command = new_uuid4()
    service = RfcTerminalCascadeRefreshService(factory, participant)
    refreshed = service.refresh(
        command_id=refresh_command,
        proposal_id=old_proposal_id,
        proposal_revision=1,
    )
    assert refreshed.proposal_id != old_proposal_id
    assert refreshed.state == "pending"
    assert refreshed.proposal_revision == 1
    assert refreshed.terminal_epoch_id == epoch_id
    assert refreshed.terminal_status_class == "terminal_cancelled"
    assert refreshed.terminal_status_evidence_id == "refresh-evidence-2"
    assert refreshed.no_change is False
    assert refreshed.replayed is False

    old_row = _proposal_row(factory, old_proposal_id)
    new_row = _proposal_row(factory, refreshed.proposal_id)
    assert old_row[6:8] == ("superseded", 2)
    assert old_row[9] == refresh_command
    assert new_row[1] == epoch_id
    assert new_row[2:4] == ("terminal_cancelled", "refresh-evidence-2")
    assert new_row[6:8] == ("pending", 1)
    assert new_row[8] == refresh_command
    assert _receipt_row(factory, refresh_command) == (
        "rfc_terminal_cascade_proposal",
        refreshed.proposal_id,
    )

    with ReadSnapshot(factory) as snapshot:
        rows = snapshot.connection.execute(
            "SELECT target_id,payload_schema,payload_json FROM audit_events "
            "WHERE command_id=? AND action_type='ticket.rfc.terminal_cascade_refreshed'",
            (refresh_command,),
        ).fetchall()
        assert len(rows) == 1
        target_id, payload_schema, payload_json = rows[0]
        assert target_id == old_proposal_id
        assert payload_schema == "RfcTerminalCascadeRefreshAuditV1"
        payload = json.loads(payload_json)
        assert payload == {
            "prior_proposal_id": old_proposal_id,
            "prior_proposal_revision": 1,
            "resulting_prior_proposal_revision": 2,
            "replacement_proposal_id": refreshed.proposal_id,
            "replacement_proposal_revision": 1,
            "terminal_epoch_id": epoch_id,
            "prior_terminal_status_class": "terminal_closed",
            "replacement_terminal_status_class": "terminal_cancelled",
            "prior_terminal_status_evidence_id": "refresh-evidence-1",
            "replacement_terminal_status_evidence_id": "refresh-evidence-2",
            "prior_scope_fingerprint": old_row[5],
            "replacement_scope_fingerprint": new_row[5],
            "state_transition": "pending_to_superseded_with_replacement_pending",
            "reason_category": None,
        }
        result_refs = snapshot.connection.execute(
            "SELECT result_type,result_id FROM audit_event_results "
            "WHERE audit_event_id=(SELECT audit_event_id FROM audit_events WHERE command_id=?)",
            (refresh_command,),
        ).fetchall()
        assert result_refs == [("rfc_terminal_cascade_proposal", refreshed.proposal_id)]

    later_child = _new_rfc(factory, 20260909003003)
    RfcHierarchyService(factory).add_subordinate(
        command_id=new_uuid4(),
        parent_rfc_id=rfc.rfc_id,
        child_rfc_id=later_child.rfc_id,
        base_revisions={rfc.rfc_id: 1, later_child.rfc_id: 1},
        reason_category="post_material_refresh_replay_drift",
    )
    participant.fail_capture = True
    replay = service.refresh(
        command_id=refresh_command,
        proposal_id=old_proposal_id,
        proposal_revision=1,
    )
    assert replay.to_response() == refreshed.to_response()
    assert replay.replayed is True
    assert replay.no_change is False
    with ReadSnapshot(factory) as snapshot:
        assert snapshot.connection.execute(
            "SELECT COUNT(*) FROM rfc_terminal_cascade_proposals WHERE terminal_epoch_id=?",
            (epoch_id,),
        ).fetchone()[0] == 2
        assert snapshot.connection.execute(
            "SELECT COUNT(*) FROM audit_events WHERE command_id=?",
            (refresh_command,),
        ).fetchone()[0] == 1


def test_refresh_scope_drift_replaces_with_exact_current_branch(initialized_database) -> None:
    factory = _factory(initialized_database)
    participant = _TaskParticipant()
    rfc, _source, old_proposal_id, epoch_id = _terminal_standalone(factory, participant)
    child = _new_rfc(factory, 20260909003004)
    RfcHierarchyService(factory).add_subordinate(
        command_id=new_uuid4(),
        parent_rfc_id=rfc.rfc_id,
        child_rfc_id=child.rfc_id,
        base_revisions={rfc.rfc_id: 1, child.rfc_id: 1},
        reason_category="refresh_scope_drift",
    )

    refreshed = RfcTerminalCascadeRefreshService(factory, participant).refresh(
        command_id=new_uuid4(),
        proposal_id=old_proposal_id,
        proposal_revision=1,
    )
    assert refreshed.proposal_id != old_proposal_id
    assert refreshed.terminal_epoch_id == epoch_id
    assert refreshed.scope_kind == "root_branch"
    assert refreshed.captured_rfc_count == 2
    assert refreshed.captured_wfm_count == 0

    with ReadSnapshot(factory) as snapshot:
        members = snapshot.connection.execute(
            "SELECT rfc_id,captured_role,ordinal FROM rfc_terminal_cascade_rfc_members "
            "WHERE rfc_terminal_cascade_proposal_id=? ORDER BY ordinal",
            (refreshed.proposal_id,),
        ).fetchall()
        assert members == [
            (rfc.rfc_id, "root", 0),
            (child.rfc_id, "subordinate", 1),
        ]


def test_refresh_stale_base_revision_writes_nothing(initialized_database) -> None:
    factory = _factory(initialized_database)
    participant = _TaskParticipant()
    _rfc, _source, proposal_id, _epoch_id = _terminal_standalone(factory, participant)
    command_id = new_uuid4()

    with pytest.raises(SomaError) as exc_info:
        RfcTerminalCascadeRefreshService(factory, participant).refresh(
            command_id=command_id,
            proposal_id=proposal_id,
            proposal_revision=2,
        )
    assert exc_info.value.code == "RFC_TERMINAL_CASCADE_STALE"
    assert _receipt_row(factory, command_id) is None
    assert _proposal_row(factory, proposal_id)[6:8] == ("pending", 1)


def test_refresh_task_participant_failure_rolls_back_before_receipt(initialized_database) -> None:
    factory = _factory(initialized_database)
    participant = _TaskParticipant()
    _rfc, _source, proposal_id, epoch_id = _terminal_standalone(factory, participant)
    participant.fail_capture = True
    command_id = new_uuid4()

    with pytest.raises(SomaError) as exc_info:
        RfcTerminalCascadeRefreshService(factory, participant).refresh(
            command_id=command_id,
            proposal_id=proposal_id,
            proposal_revision=1,
        )
    assert exc_info.value.code == "RFC_TERMINAL_CASCADE_PARTICIPANT_FAILED"
    assert _receipt_row(factory, command_id) is None
    assert _proposal_row(factory, proposal_id)[6:8] == ("pending", 1)
    with ReadSnapshot(factory) as snapshot:
        assert snapshot.connection.execute(
            "SELECT COUNT(*) FROM rfc_terminal_cascade_proposals WHERE terminal_epoch_id=?",
            (epoch_id,),
        ).fetchone()[0] == 1


def test_refresh_rejects_superseded_proposal_without_new_receipt(initialized_database) -> None:
    factory = _factory(initialized_database)
    participant = _TaskParticipant()
    rfc, source, old_proposal_id, _epoch_id = _terminal_standalone(factory, participant)
    correction_command = new_uuid4()
    with UnitOfWork(factory) as uow:
        _insert_outer_receipt(uow, correction_command, rfc.rfc_id)
        source.apply_accepted_field_deltas(
            uow,
            rfc_id=rfc.rfc_id,
            accepted_command_id=correction_command,
            deltas=(_status("Cancelled", "terminal_cancelled", "refresh-evidence-2"),),
        )
    RfcTerminalCascadeRefreshService(factory, participant).refresh(
        command_id=new_uuid4(),
        proposal_id=old_proposal_id,
        proposal_revision=1,
    )

    command_id = new_uuid4()
    with pytest.raises(SomaError) as exc_info:
        RfcTerminalCascadeRefreshService(factory, participant).refresh(
            command_id=command_id,
            proposal_id=old_proposal_id,
            proposal_revision=2,
        )
    assert exc_info.value.code == "RFC_TERMINAL_CASCADE_NOT_PENDING"
    assert _receipt_row(factory, command_id) is None
