from __future__ import annotations

from dataclasses import dataclass

import pytest

from soma.foundation.application.command_receipts import CommandReceipt, CommandReceiptStore
from soma.foundation.errors import SomaError, ValidationError
from soma.foundation.identifiers import new_uuid4
from soma.foundation.persistence.uow import UnitOfWork
from soma.foundation.strict_json import sha256_canonical_json
from soma.tickets.queries import rfc_terminal_cascade as cascade_query
from soma.tickets.queries.rfc_terminal_cascade import (
    RfcTerminalCascadeImpactItem,
    RfcTerminalCascadeImpactProviderPage,
    RfcTerminalCascadePreviewService,
    RfcTerminalCascadeQueryService,
    terminal_cascade_preview_fingerprint,
)
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
class _PreviewParticipant:
    domain: str
    scope_members: tuple[RfcTerminalCascadeWfmMember, ...] = ()
    impact_items: tuple[RfcTerminalCascadeImpactItem, ...] = ()
    fingerprint: str = "c" * 64
    indeterminate_warning: str | None = None

    def capture_applicable_wfms(self, uow, rfc_ids):
        allowed = frozenset(rfc_ids)
        return tuple(member for member in self.scope_members if member.owning_rfc_id in allowed)

    def snapshot_applicable_wfms(self, snapshot, rfc_ids):
        allowed = frozenset(rfc_ids)
        return tuple(member for member in self.scope_members if member.owning_rfc_id in allowed)

    def preview_terminal_cascade(self, snapshot, proposal_snapshot, after_key, limit):
        if self.indeterminate_warning is not None:
            return RfcTerminalCascadeImpactProviderPage(
                domain=self.domain,
                status="INDETERMINATE",
                exact_count=None,
                provider_fingerprint=None,
                items=(),
                continuation_key=None,
                warning_code=self.indeterminate_warning,
            )
        ordered = tuple(sorted(self.impact_items, key=lambda item: (item.impact_kind, item.entity_id)))
        remaining = tuple(
            item for item in ordered if after_key is None or (item.impact_kind, item.entity_id) > after_key
        )
        page_items = remaining[:limit]
        continuation = None
        if len(remaining) > len(page_items):
            last = page_items[-1]
            continuation = (last.impact_kind, last.entity_id)
        return RfcTerminalCascadeImpactProviderPage(
            domain=self.domain,
            status="READY",
            exact_count=len(ordered),
            provider_fingerprint=self.fingerprint,
            items=page_items,
            continuation_key=continuation,
            warning_code=None,
        )


class _TruncatingParticipant(_PreviewParticipant):
    def preview_terminal_cascade(self, snapshot, proposal_snapshot, after_key, limit):
        ordered = tuple(sorted(self.impact_items, key=lambda item: (item.impact_kind, item.entity_id)))
        remaining = tuple(
            item for item in ordered if after_key is None or (item.impact_kind, item.entity_id) > after_key
        )
        page_items = remaining[:1]
        return RfcTerminalCascadeImpactProviderPage(
            domain=self.domain,
            status="READY",
            exact_count=len(ordered),
            provider_fingerprint=self.fingerprint,
            items=page_items,
            continuation_key=None,
            warning_code=None,
        )


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


def _task_termination(task_id: str, *, state: str = "not_started") -> RfcTerminalCascadeImpactItem:
    return RfcTerminalCascadeImpactItem(
        domain="TASKS_OBJECTIVES",
        impact_kind="WFM_TERMINATION",
        entity_type="WFM_TASK",
        entity_id=task_id,
        current_state=state,
        resulting_state="terminated",
    )


def _objective_impact(objective_id: str) -> RfcTerminalCascadeImpactItem:
    return RfcTerminalCascadeImpactItem(
        domain="TASKS_OBJECTIVES",
        impact_kind="OBJECTIVE_EXECUTABLE_COUNT",
        entity_type="OBJECTIVE",
        entity_id=objective_id,
        current_count=1,
        resulting_count=0,
        attention_code="LOST_LAST_EXECUTABLE",
    )


def _communication_freeze(rfc_id: str) -> RfcTerminalCascadeImpactItem:
    return RfcTerminalCascadeImpactItem(
        domain="COMMUNICATIONS",
        impact_kind="RFC_TERMINAL_SUMMARY_FREEZE",
        entity_type="RFC",
        entity_id=rfc_id,
        current_state="live",
        resulting_state="frozen",
    )


def _communication_orphan(communication_id: str) -> RfcTerminalCascadeImpactItem:
    return RfcTerminalCascadeImpactItem(
        domain="COMMUNICATIONS",
        impact_kind="ORPHAN_GRACE_EVALUATION",
        entity_type="COMMUNICATION",
        entity_id=communication_id,
        current_state="RETAINED",
        resulting_state="ORPHAN_PENDING_PURGE",
        current_count=1,
        resulting_count=0,
    )


def _terminal_standalone(factory, *, task_participant: _PreviewParticipant):
    rfc = _new_rfc(factory, 20260909002001)
    capture = RfcTerminalCascadeCaptureService(task_participant)
    source = RfcSourceProjectionService(
        _AcceptingEvidenceProvider(),
        terminal_capture_participant=capture,
    )
    command_id = new_uuid4()
    with UnitOfWork(factory) as uow:
        _insert_outer_receipt(uow, command_id, rfc.rfc_id)
        result = source.apply_accepted_field_deltas(
            uow,
            rfc_id=rfc.rfc_id,
            accepted_command_id=command_id,
            deltas=(_status("Closed", "terminal_closed", "preview-evidence-1"),),
        )
        assert result.pending_cascade_proposal_id is not None
        assert result.lifecycle_projection.terminal_epoch_id is not None
        proposal_id = result.pending_cascade_proposal_id
        epoch_id = result.lifecycle_projection.terminal_epoch_id
    return rfc, source, proposal_id, epoch_id


def _ready_preview(factory, task_participant, communication_participant):
    rfc, source, proposal_id, epoch_id = _terminal_standalone(
        factory,
        task_participant=task_participant,
    )
    preview = RfcTerminalCascadePreviewService(
        factory,
        task_participant,
        communication_participant,
    )
    return rfc, source, proposal_id, epoch_id, preview


def test_terminal_preview_golden_fingerprint_and_cursor_filter_vectors() -> None:
    task_meta = RfcTerminalCascadeImpactProviderPage(
        domain="TASKS_OBJECTIVES",
        status="READY",
        exact_count=2,
        provider_fingerprint="c" * 64,
    )
    communication_meta = RfcTerminalCascadeImpactProviderPage(
        domain="COMMUNICATIONS",
        status="READY",
        exact_count=1,
        provider_fingerprint="d" * 64,
    )
    preview_fingerprint = terminal_cascade_preview_fingerprint(
        proposal_id="00000000-0000-4000-8000-000000000050",
        proposal_revision=1,
        persisted_scope_fingerprint="a" * 64,
        current_scope_fingerprint="b" * 64,
        persisted_member_count=2,
        current_member_count=2,
        stale_reasons=(),
        task_page=task_meta,
        communication_page=communication_meta,
    )
    assert preview_fingerprint == "4f67cf4d794157362580f0eb5af5d2d6fd12d11241466c1da0107ee858a2debe"
    assert cascade_query._preview_filter_fingerprint(
        proposal_id="00000000-0000-4000-8000-000000000050",
        proposal_revision=1,
        preview_fingerprint=preview_fingerprint,
    ) == "44027d68c497b6916a8cae53e759fa1731716c03edd527ab97dd84a9b5f670c1"


def test_terminal_preview_pages_tickets_then_tasks_then_communications(initialized_database) -> None:
    factory = _factory(initialized_database)
    task = _PreviewParticipant(domain="TASKS_OBJECTIVES", fingerprint="c" * 64)
    communication = _PreviewParticipant(domain="COMMUNICATIONS", fingerprint="d" * 64)
    rfc, _source, proposal_id, _epoch_id, preview = _ready_preview(factory, task, communication)

    task.scope_members = (
        RfcTerminalCascadeWfmMember(
            task_id=new_uuid4(),
            owning_rfc_id=rfc.rfc_id,
            captured_task_revision=1,
            captured_task_no=f"TK{201:014d}",
        ),
    )
    # The scope member was added after proposal capture, so restore scope equality for this paging-only case.
    task.scope_members = ()
    task.impact_items = (
        _task_termination(new_uuid4()),
        _objective_impact(new_uuid4()),
    )
    communication.impact_items = (
        _communication_freeze(rfc.rfc_id),
        _communication_orphan(new_uuid4()),
    )

    page1 = preview.preview(proposal_id=proposal_id, limit=2)
    assert page1.execution_ready is True
    assert page1.stale_reasons == ()
    assert [item.domain for item in page1.impacts] == ["TICKETS", "TASKS_OBJECTIVES"]
    assert page1.continuation is not None
    assert page1.continuation["query_id"] == "PreviewRfcTerminalCascade"
    assert page1.continuation["sort_registry_id"] == "RFC_TERMINAL_CASCADE_IMPACT_ORDER_V1"

    page2 = preview.preview(proposal_id=proposal_id, cursor=page1.continuation, limit=2)
    assert [item.domain for item in page2.impacts] == ["TASKS_OBJECTIVES", "COMMUNICATIONS"]
    assert page2.continuation is not None

    page3 = preview.preview(proposal_id=proposal_id, cursor=page2.continuation, limit=2)
    assert [item.domain for item in page3.impacts] == ["COMMUNICATIONS"]
    assert page3.continuation is None
    assert page1.preview_fingerprint == page2.preview_fingerprint == page3.preview_fingerprint


def test_terminal_preview_cursor_rejects_changed_provider_fingerprint(initialized_database) -> None:
    factory = _factory(initialized_database)
    task = _PreviewParticipant(
        domain="TASKS_OBJECTIVES",
        impact_items=(_objective_impact(new_uuid4()), _task_termination(new_uuid4())),
        fingerprint="c" * 64,
    )
    communication = _PreviewParticipant(
        domain="COMMUNICATIONS",
        impact_items=(_communication_orphan(new_uuid4()),),
        fingerprint="d" * 64,
    )
    _rfc, _source, proposal_id, _epoch_id, preview = _ready_preview(factory, task, communication)
    page1 = preview.preview(proposal_id=proposal_id, limit=1)
    assert page1.continuation is not None

    task.fingerprint = "e" * 64
    with pytest.raises(ValidationError, match="filter fingerprint is stale"):
        preview.preview(proposal_id=proposal_id, cursor=page1.continuation, limit=1)


def test_terminal_preview_marks_hierarchy_drift_stale(initialized_database) -> None:
    factory = _factory(initialized_database)
    task = _PreviewParticipant(domain="TASKS_OBJECTIVES")
    communication = _PreviewParticipant(domain="COMMUNICATIONS", fingerprint="d" * 64)
    rfc, _source, proposal_id, _epoch_id, preview = _ready_preview(factory, task, communication)

    child = _new_rfc(factory, 20260909002002)
    RfcHierarchyService(factory).add_subordinate(
        command_id=new_uuid4(),
        parent_rfc_id=rfc.rfc_id,
        child_rfc_id=child.rfc_id,
        base_revisions={rfc.rfc_id: 1, child.rfc_id: 1},
        reason_category="preview_hierarchy_drift",
    )

    result = preview.preview(proposal_id=proposal_id)
    assert result.execution_ready is False
    assert result.current_member_count == 2
    assert "RFC_OR_WFM_SCOPE_CHANGED" in result.stale_reasons


def test_terminal_preview_marks_wfm_drift_stale(initialized_database) -> None:
    factory = _factory(initialized_database)
    task = _PreviewParticipant(domain="TASKS_OBJECTIVES")
    communication = _PreviewParticipant(domain="COMMUNICATIONS", fingerprint="d" * 64)
    rfc, _source, proposal_id, _epoch_id, preview = _ready_preview(factory, task, communication)

    task.scope_members = (
        RfcTerminalCascadeWfmMember(
            task_id=new_uuid4(),
            owning_rfc_id=rfc.rfc_id,
            captured_task_revision=1,
            captured_task_no=f"TK{202:014d}",
        ),
    )
    result = preview.preview(proposal_id=proposal_id)
    assert result.execution_ready is False
    assert result.current_member_count == 2
    assert result.stale_reasons == ("RFC_OR_WFM_SCOPE_CHANGED",)


def test_terminal_preview_same_epoch_terminal_correction_is_stale(initialized_database) -> None:
    factory = _factory(initialized_database)
    task = _PreviewParticipant(domain="TASKS_OBJECTIVES")
    communication = _PreviewParticipant(domain="COMMUNICATIONS", fingerprint="d" * 64)
    _rfc, source, proposal_id, epoch_id, preview = _ready_preview(factory, task, communication)

    pending = RfcTerminalCascadeQueryService(factory).get(rfc_id=_rfc.rfc_id)
    assert pending.state.terminal_epoch_id == epoch_id
    command_id = new_uuid4()
    with UnitOfWork(factory) as uow:
        _insert_outer_receipt(uow, command_id, _rfc.rfc_id)
        result = source.apply_accepted_field_deltas(
            uow,
            rfc_id=_rfc.rfc_id,
            accepted_command_id=command_id,
            deltas=(_status("Cancelled", "terminal_cancelled", "preview-evidence-2"),),
        )
        assert result.lifecycle_projection.terminal_epoch_id == epoch_id
        assert result.pending_cascade_proposal_id is None

    result = preview.preview(proposal_id=proposal_id)
    assert result.execution_ready is False
    assert result.current_scope_fingerprint is not None
    assert result.stale_reasons == (
        "TERMINAL_EVIDENCE_CHANGED",
        "RFC_OR_WFM_SCOPE_CHANGED",
    )


def test_terminal_preview_indeterminate_provider_returns_no_partial_impacts(initialized_database) -> None:
    factory = _factory(initialized_database)
    task = _PreviewParticipant(
        domain="TASKS_OBJECTIVES",
        indeterminate_warning="TASK_PREVIEW_INDETERMINATE",
    )
    communication = _PreviewParticipant(
        domain="COMMUNICATIONS",
        impact_items=(_communication_orphan(new_uuid4()),),
        fingerprint="d" * 64,
    )
    _rfc, _source, proposal_id, _epoch_id, preview = _ready_preview(factory, task, communication)

    result = preview.preview(proposal_id=proposal_id)
    assert result.execution_ready is False
    assert result.impacts == ()
    assert result.continuation is None
    assert result.warnings == ("TASK_PREVIEW_INDETERMINATE",)


def test_terminal_preview_rejects_truncated_first_provider_page(initialized_database) -> None:
    factory = _factory(initialized_database)
    task = _TruncatingParticipant(
        domain="TASKS_OBJECTIVES",
        impact_items=(_objective_impact(new_uuid4()), _task_termination(new_uuid4())),
        fingerprint="c" * 64,
    )
    communication = _PreviewParticipant(domain="COMMUNICATIONS", fingerprint="d" * 64)
    _rfc, _source, proposal_id, _epoch_id, preview = _ready_preview(factory, task, communication)

    with pytest.raises(SomaError) as exc_info:
        preview.preview(proposal_id=proposal_id)
    assert exc_info.value.code == "RFC_TERMINAL_CASCADE_PARTICIPANT_FAILED"


def test_terminal_preview_never_opens_writer_uow(initialized_database, monkeypatch) -> None:
    factory = _factory(initialized_database)
    task = _PreviewParticipant(domain="TASKS_OBJECTIVES")
    communication = _PreviewParticipant(domain="COMMUNICATIONS", fingerprint="d" * 64)
    rfc, _source, proposal_id, _epoch_id, preview = _ready_preview(factory, task, communication)
    before = RfcTerminalCascadeQueryService(factory).get(rfc_id=rfc.rfc_id).to_response()

    def _forbid_writer(self):
        raise AssertionError("preview attempted to open a writer UnitOfWork")

    monkeypatch.setattr(UnitOfWork, "__enter__", _forbid_writer)
    result = preview.preview(proposal_id=proposal_id)
    assert result.execution_ready is True

    after = RfcTerminalCascadeQueryService(factory).get(rfc_id=rfc.rfc_id).to_response()
    assert after == before


def test_preview_fingerprint_binds_provider_authority_even_when_scope_is_unchanged(initialized_database) -> None:
    factory = _factory(initialized_database)
    task = _PreviewParticipant(domain="TASKS_OBJECTIVES", fingerprint="c" * 64)
    communication = _PreviewParticipant(domain="COMMUNICATIONS", fingerprint="d" * 64)
    _rfc, _source, proposal_id, _epoch_id, preview = _ready_preview(factory, task, communication)

    first = preview.preview(proposal_id=proposal_id)
    task.fingerprint = sha256_canonical_json({"provider": "task", "revision": 2})
    second = preview.preview(proposal_id=proposal_id)
    assert first.persisted_scope_fingerprint == second.persisted_scope_fingerprint
    assert first.current_scope_fingerprint == second.current_scope_fingerprint
    assert first.preview_fingerprint != second.preview_fingerprint
