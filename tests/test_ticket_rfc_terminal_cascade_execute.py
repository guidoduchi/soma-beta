from __future__ import annotations

import json
from dataclasses import dataclass, field

import pytest

from soma.foundation.application.command_receipts import CommandReceipt, CommandReceiptStore
from soma.foundation.errors import SomaError
from soma.foundation.identifiers import new_uuid4
from soma.foundation.persistence.uow import ReadSnapshot, UnitOfWork
from soma.foundation.strict_json import sha256_canonical_json
from soma.objectives_tasks import AcceptedTaskSchedule, TaskPlanningService
from soma.objectives_tasks.domain.objectives import ObjectiveExistingTaskIntent
from soma.objectives_tasks.queries.grouping import ObjectiveGroupingQueryService
from soma.objectives_tasks.services.objectives import ObjectiveService
from soma.objectives_tasks.services.source_terminal import RfcTerminalTaskParticipant
from soma.objectives_tasks.services.wfm_import import (
    WfmImportBaseTarget,
    WfmImportMutationParticipant,
    WfmImportReader,
    WfmSourceProjectionAcceptanceMutation,
)
from soma.tickets.queries.rfc_terminal_cascade import (
    RfcTerminalCascadeImpactItem,
    RfcTerminalCascadeImpactProviderPage,
    RfcTerminalCascadePreviewService,
)
from soma.tickets.rfc_source_projection import RfcAcceptedFieldDelta, RfcSourceProjectionService
from soma.tickets.rfc_terminal_cascade import (
    RfcTerminalCascadeCaptureService,
    RfcTerminalCascadeWfmMember,
)
from soma.tickets.rfc_terminal_cascade_execute import RfcTerminalCascadeExecutionService
from soma.tickets.rfc_terminal_review import (
    RfcTerminalCascadeExecutionCommandContext,
    RfcTerminalCascadeParticipantApplyResult,
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
class _ExecutionParticipant:
    domain: str
    fingerprint: str
    impact_items: tuple[RfcTerminalCascadeImpactItem, ...] = ()
    scope_members: tuple[RfcTerminalCascadeWfmMember, ...] = ()
    revalidate_status: str = "READY"
    apply_result: RfcTerminalCascadeParticipantApplyResult | None = None
    fail_apply: bool = False
    revalidate_calls: int = 0
    apply_calls: int = 0
    receipt_seen: bool = False
    contexts: list[RfcTerminalCascadeExecutionCommandContext] = field(default_factory=list)

    def capture_applicable_wfms(self, uow, rfc_ids):
        allowed = frozenset(rfc_ids)
        return tuple(member for member in self.scope_members if member.owning_rfc_id in allowed)

    def snapshot_applicable_wfms(self, snapshot, rfc_ids):
        allowed = frozenset(rfc_ids)
        return tuple(member for member in self.scope_members if member.owning_rfc_id in allowed)

    def preview_terminal_cascade(self, snapshot, proposal_snapshot, after_key, limit):
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

    def revalidate_terminal_cascade(
        self,
        uow,
        proposal_snapshot,
        reviewed_exact_count,
        reviewed_provider_fingerprint,
    ):
        self.revalidate_calls += 1
        if self.revalidate_status != "READY":
            return self.revalidate_status
        if reviewed_exact_count != len(self.impact_items) or reviewed_provider_fingerprint != self.fingerprint:
            return "STALE"
        return "READY"

    def apply_terminal_cascade(self, uow, proposal_snapshot, command_context):
        self.apply_calls += 1
        receipt = uow.connection.execute(
            "SELECT target_type,target_id FROM command_receipts WHERE command_id=?",
            (command_context.command_id,),
        ).fetchone()
        self.receipt_seen = receipt == ("rfc_terminal_cascade_proposal", proposal_snapshot.proposal_id)
        if not self.receipt_seen:
            raise AssertionError("participant apply ran before the outer command receipt")
        if not isinstance(command_context, RfcTerminalCascadeExecutionCommandContext):
            raise AssertionError("participant did not receive the exact execution command context")
        if hasattr(command_context, "proof") or hasattr(command_context, "deliberate_action_proof"):
            raise AssertionError("participant command context leaked deliberate-action proof material")
        self.contexts.append(command_context)
        if self.fail_apply:
            raise RuntimeError("injected participant apply failure")
        if self.apply_result is None:
            raise AssertionError("participant apply result was not configured")
        return self.apply_result


@dataclass
class _ProofProvider:
    consumed: set[str] = field(default_factory=set)
    calls: list[tuple[str, str, int, str | None]] = field(default_factory=list)
    fail_all: bool = False

    def validate_and_consume(
        self,
        uow,
        proof,
        expected_action,
        target,
        base_revision,
        preview_fingerprint,
    ):
        if self.fail_all or not isinstance(proof, str) or proof in self.consumed:
            raise RuntimeError("proof unavailable")
        self.consumed.add(proof)
        self.calls.append((expected_action, target.target_id, base_revision, preview_fingerprint))
        return object()


def _factory(initialized_database):
    database_path, factory_for_path = initialized_database
    return factory_for_path(database_path)


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


def _status() -> RfcAcceptedFieldDelta:
    return RfcAcceptedFieldDelta(
        field_key="status",
        value_kind="controlled",
        value="Closed",
        evidence_id="execute-evidence-1",
        status_class="terminal_closed",
        status_authority="enhanced_rfc",
    )


def _task_member(rfc_id: str, ordinal: int) -> RfcTerminalCascadeWfmMember:
    return RfcTerminalCascadeWfmMember(
        task_id=new_uuid4(),
        owning_rfc_id=rfc_id,
        captured_task_revision=1,
        captured_task_no=f"TK{ordinal:014d}",
    )


def _task_impact(task_id: str) -> RfcTerminalCascadeImpactItem:
    return RfcTerminalCascadeImpactItem(
        domain="TASKS_OBJECTIVES",
        impact_kind="WFM_TERMINATION",
        entity_type="WFM_TASK",
        entity_id=task_id,
        current_state="not_started",
        resulting_state="terminated",
    )


def _communication_impact() -> RfcTerminalCascadeImpactItem:
    return RfcTerminalCascadeImpactItem(
        domain="COMMUNICATIONS",
        impact_kind="RFC_DIRECT_LINK_CLOSE",
        entity_type="COMMUNICATION_LINK",
        entity_id=new_uuid4(),
        current_state="active",
        resulting_state="closed",
    )


def _apply_result(domain: str, *, result_count: int, audit_count: int) -> RfcTerminalCascadeParticipantApplyResult:
    return RfcTerminalCascadeParticipantApplyResult(
        domain=domain,
        result_ref_count=result_count,
        audit_event_count=audit_count,
        result_fingerprint=sha256_canonical_json(
            {
                "schema": "SOMA_RFC_TERMINAL_CASCADE_PARTICIPANT_RESULT_V1",
                "domain": domain,
                "result_ref_count": result_count,
                "audit_event_count": audit_count,
            }
        ),
    )


def _terminal_case(initialized_database, *, task_count: int = 0, communication_count: int = 0):
    factory = _factory(initialized_database)
    rfc = RfcService(factory).create_or_adopt_identity(
        command_id=new_uuid4(),
        rfc_no="NC20260909004001",
        creation_context="manual",
    )

    task = _ExecutionParticipant(
        domain="TASKS_OBJECTIVES",
        fingerprint="c" * 64,
        apply_result=_apply_result("TASKS_OBJECTIVES", result_count=max(task_count, 1), audit_count=max(task_count // 2, 1)),
    )
    task.scope_members = tuple(_task_member(rfc.rfc_id, index + 1) for index in range(task_count))
    task.impact_items = tuple(_task_impact(member.task_id) for member in task.scope_members)

    communication = _ExecutionParticipant(
        domain="COMMUNICATIONS",
        fingerprint="d" * 64,
        impact_items=tuple(_communication_impact() for _ in range(communication_count)),
        apply_result=_apply_result(
            "COMMUNICATIONS",
            result_count=max(communication_count, 1),
            audit_count=max(communication_count // 2, 1),
        ),
    )

    capture = RfcTerminalCascadeCaptureService(task)
    source = RfcSourceProjectionService(
        _AcceptingEvidenceProvider(),
        terminal_capture_participant=capture,
    )
    source_command = new_uuid4()
    with UnitOfWork(factory) as uow:
        _insert_outer_receipt(uow, source_command, rfc.rfc_id)
        applied = source.apply_accepted_field_deltas(
            uow,
            rfc_id=rfc.rfc_id,
            accepted_command_id=source_command,
            deltas=(_status(),),
        )
        assert applied.pending_cascade_proposal_id is not None
        proposal_id = applied.pending_cascade_proposal_id

    preview_service = RfcTerminalCascadePreviewService(factory, task, communication)
    preview = preview_service.preview(proposal_id=proposal_id, limit=500)
    assert preview.execution_ready is True
    assert preview.execution_review is not None
    proof = _ProofProvider()
    execute = RfcTerminalCascadeExecutionService(factory, task, communication, proof)
    return factory, rfc, proposal_id, preview, task, communication, proof, execute


def _proposal_state(factory, proposal_id: str):
    with ReadSnapshot(factory) as snapshot:
        return snapshot.connection.execute(
            "SELECT proposal_state,revision,executed_command_id FROM rfc_terminal_cascade_proposals "
            "WHERE rfc_terminal_cascade_proposal_id=?",
            (proposal_id,),
        ).fetchone()


def _receipt_exists(factory, command_id: str) -> bool:
    with ReadSnapshot(factory) as snapshot:
        return snapshot.connection.execute(
            "SELECT 1 FROM command_receipts WHERE command_id=?",
            (command_id,),
        ).fetchone() is not None


def test_execute_large_provider_result_cardinality_keeps_ticket_audit_fixed_shape(initialized_database) -> None:
    factory, _rfc, proposal_id, preview, task, communication, proof, execute = _terminal_case(
        initialized_database,
        task_count=80,
        communication_count=20,
    )
    task.apply_result = _apply_result("TASKS_OBJECTIVES", result_count=500, audit_count=250)
    communication.apply_result = _apply_result("COMMUNICATIONS", result_count=300, audit_count=150)
    command_id = new_uuid4()
    actor_id = new_uuid4()

    result = execute.execute(
        command_id=command_id,
        proposal_id=proposal_id,
        proposal_revision=preview.proposal_revision,
        execution_review=preview.execution_review,
        deliberate_action_proof="proof-large",
        actor_id=actor_id,
    )
    assert result.state == "executed"
    assert result.proposal_revision == 2
    assert task.receipt_seen is True and communication.receipt_seen is True
    assert task.contexts == communication.contexts
    context = task.contexts[0]
    assert context.command_id == command_id
    assert context.actor_id == actor_id
    assert context.reviewed_preview_fingerprint == preview.preview_fingerprint
    assert len(proof.calls) == 1

    with ReadSnapshot(factory) as snapshot:
        audit_row = snapshot.connection.execute(
            "SELECT audit_event_id,payload_json FROM audit_events "
            "WHERE command_id=? AND action_type='ticket.rfc.terminal_cascade_executed'",
            (command_id,),
        ).fetchone()
        assert audit_row is not None
        audit_event_id, payload_json = audit_row
        payload = json.loads(payload_json)
        assert payload["task_objective_apply_result"]["result_ref_count"] == 500
        assert payload["communication_apply_result"]["result_ref_count"] == 300
        assert "task_participant_result_refs" not in payload
        assert "communication_participant_result_refs" not in payload
        assert payload["reviewed_preview_fingerprint"] == preview.preview_fingerprint
        refs = snapshot.connection.execute(
            "SELECT result_type,result_id FROM audit_event_results WHERE audit_event_id=? ORDER BY ordinal",
            (audit_event_id,),
        ).fetchall()
        assert refs == [("rfc_terminal_cascade_proposal", proposal_id)]

    before_calls = (task.revalidate_calls, task.apply_calls, communication.revalidate_calls, communication.apply_calls, len(proof.calls))
    proof.fail_all = True
    task.revalidate_status = "INDETERMINATE"
    replay = execute.execute(
        command_id=command_id,
        proposal_id=proposal_id,
        proposal_revision=preview.proposal_revision,
        execution_review=preview.execution_review,
        deliberate_action_proof="proof-large",
        actor_id=actor_id,
    )
    assert replay.to_response() == result.to_response()
    assert replay.replayed is True
    assert (task.revalidate_calls, task.apply_calls, communication.revalidate_calls, communication.apply_calls, len(proof.calls)) == before_calls


def test_execute_stale_provider_fails_before_proof_or_receipt(initialized_database) -> None:
    factory, _rfc, proposal_id, preview, task, communication, proof, execute = _terminal_case(initialized_database)
    task.fingerprint = "e" * 64
    command_id = new_uuid4()

    with pytest.raises(SomaError) as exc_info:
        execute.execute(
            command_id=command_id,
            proposal_id=proposal_id,
            proposal_revision=preview.proposal_revision,
            execution_review=preview.execution_review,
            deliberate_action_proof="proof-stale",
        )
    assert exc_info.value.code == "RFC_TERMINAL_CASCADE_STALE"
    assert len(proof.calls) == 0
    assert task.apply_calls == communication.apply_calls == 0
    assert _receipt_exists(factory, command_id) is False
    assert _proposal_state(factory, proposal_id) == ("pending", 1, None)


def test_execute_indeterminate_provider_fails_before_proof(initialized_database) -> None:
    factory, _rfc, proposal_id, preview, task, communication, proof, execute = _terminal_case(initialized_database)
    communication.revalidate_status = "INDETERMINATE"
    command_id = new_uuid4()

    with pytest.raises(SomaError) as exc_info:
        execute.execute(
            command_id=command_id,
            proposal_id=proposal_id,
            proposal_revision=preview.proposal_revision,
            execution_review=preview.execution_review,
            deliberate_action_proof="proof-indeterminate",
        )
    assert exc_info.value.code == "RFC_TERMINAL_CASCADE_PARTICIPANT_FAILED"
    assert len(proof.calls) == 0
    assert task.apply_calls == communication.apply_calls == 0
    assert _receipt_exists(factory, command_id) is False


def test_execute_invalid_proof_never_reaches_participant_apply(initialized_database) -> None:
    factory, _rfc, proposal_id, preview, task, communication, proof, execute = _terminal_case(initialized_database)
    proof.fail_all = True
    command_id = new_uuid4()

    with pytest.raises(SomaError) as exc_info:
        execute.execute(
            command_id=command_id,
            proposal_id=proposal_id,
            proposal_revision=preview.proposal_revision,
            execution_review=preview.execution_review,
            deliberate_action_proof="proof-invalid",
        )
    assert exc_info.value.code == "RFC_TERMINAL_CASCADE_CONFIRMATION_REQUIRED"
    assert task.revalidate_calls == communication.revalidate_calls == 1
    assert task.apply_calls == communication.apply_calls == 0
    assert _receipt_exists(factory, command_id) is False


def test_execute_participant_failure_rolls_back_receipt_but_proof_remains_consumed(initialized_database) -> None:
    factory, _rfc, proposal_id, preview, task, communication, proof, execute = _terminal_case(initialized_database)
    communication.fail_apply = True
    command_id = new_uuid4()

    with pytest.raises(SomaError) as exc_info:
        execute.execute(
            command_id=command_id,
            proposal_id=proposal_id,
            proposal_revision=preview.proposal_revision,
            execution_review=preview.execution_review,
            deliberate_action_proof="proof-once",
        )
    assert exc_info.value.code == "RFC_TERMINAL_CASCADE_PARTICIPANT_FAILED"
    assert task.receipt_seen is True and communication.receipt_seen is True
    assert _receipt_exists(factory, command_id) is False
    assert _proposal_state(factory, proposal_id) == ("pending", 1, None)
    assert "proof-once" in proof.consumed

    communication.fail_apply = False
    with pytest.raises(SomaError) as reused_info:
        execute.execute(
            command_id=command_id,
            proposal_id=proposal_id,
            proposal_revision=preview.proposal_revision,
            execution_review=preview.execution_review,
            deliberate_action_proof="proof-once",
        )
    assert reused_info.value.code == "RFC_TERMINAL_CASCADE_CONFIRMATION_REQUIRED"
    assert _receipt_exists(factory, command_id) is False

    success = execute.execute(
        command_id=command_id,
        proposal_id=proposal_id,
        proposal_revision=preview.proposal_revision,
        execution_review=preview.execution_review,
        deliberate_action_proof="proof-fresh",
    )
    assert success.state == "executed"
    assert _proposal_state(factory, proposal_id) == ("executed", 2, command_id)


def test_execute_rejects_wrong_domain_apply_summary_and_rolls_back(initialized_database) -> None:
    factory, _rfc, proposal_id, preview, task, communication, proof, execute = _terminal_case(initialized_database)
    task.apply_result = _apply_result("COMMUNICATIONS", result_count=1, audit_count=1)
    command_id = new_uuid4()

    with pytest.raises(SomaError) as exc_info:
        execute.execute(
            command_id=command_id,
            proposal_id=proposal_id,
            proposal_revision=preview.proposal_revision,
            execution_review=preview.execution_review,
            deliberate_action_proof="proof-wrong-domain",
        )
    assert exc_info.value.code == "RFC_TERMINAL_CASCADE_PARTICIPANT_FAILED"
    assert _receipt_exists(factory, command_id) is False
    assert _proposal_state(factory, proposal_id) == ("pending", 1, None)


def test_t020_real_task_participant_terminates_exact_wfm_scope_inside_rfc_outer_uow(
    initialized_database,
) -> None:
    factory = _factory(initialized_database)
    rfc = RfcService(factory).create_or_adopt_identity(
        command_id=new_uuid4(),
        rfc_no="NC00000000009020",
        creation_context="manual",
    )
    schedule = AcceptedTaskSchedule(
        start_utc=2_640_000_000,
        end_utc=2_640_003_600,
        scheduling_timezone_iana="America/Guayaquil",
    )
    task_no = "TK00000000009020"
    wfm = TaskPlanningService(factory).register_manual_wfm_task(
        command_id=new_uuid4(),
        task_no=task_no,
        rfc_id=rfc.rfc_id,
        schedule=schedule,
    )
    local = TaskPlanningService(factory).create_local_task(
        command_id=new_uuid4(),
        local_task_name="Unrelated local survivor",
        schedule=schedule,
    )

    def intent(task_id: str) -> ObjectiveExistingTaskIntent:
        with ReadSnapshot(factory) as snapshot:
            row = snapshot.connection.execute(
                "SELECT t.revision,pc.revision,pc.plan_revision_id "
                "FROM tasks t JOIN task_plan_current pc ON pc.task_id=t.task_id "
                "WHERE t.task_id=?",
                (task_id,),
            ).fetchone()
        assert row is not None
        return ObjectiveExistingTaskIntent(
            task_id=task_id,
            expected_task_revision=int(row[0]),
            expected_plan_revision=int(row[1]),
            expected_plan_revision_id=str(row[2]),
        )

    grouping = ObjectiveGroupingQueryService(factory)
    objective_intents = (intent(wfm.task_id), intent(local.task_id))
    creation = grouping.creation_preview(existing_tasks=objective_intents)
    assert creation["mode"] == "CREATE"
    objective = ObjectiveService(factory).create_objective_from_preview(
        command_id=new_uuid4(),
        preview_fingerprint=str(creation["fingerprint"]),
        existing_tasks=objective_intents,
    )

    with ReadSnapshot(factory) as snapshot:
        base_token = WfmImportReader.source_acceptance_base_token(
            snapshot.connection,
            WfmImportBaseTarget("wfm_source_projection", task_no, wfm.task_id),
        )
    source_command = new_uuid4()
    source_observation_id = new_uuid4()
    with UnitOfWork(factory) as uow:
        _insert_outer_receipt(uow, source_command, wfm.task_id)
        source_result = WfmImportMutationParticipant.apply_wfm_source_projection(
            uow,
            WfmSourceProjectionAcceptanceMutation(
                task_id=wfm.task_id,
                task_no=task_no,
                expected_source_projection_revision=0,
                provider_status_token="Implementation",
                provider_lifecycle_class="active",
                source_plan_start_utc=None,
                source_plan_end_utc=None,
                accepted_source_observation_id=source_observation_id,
                base_state_token=base_token,
                accepted_command_id=source_command,
            ),
        )
        assert source_result.source_projection_revision == 1

    with ReadSnapshot(factory) as snapshot:
        source_before = tuple(
            snapshot.connection.execute(
                "SELECT provider_status_token,provider_lifecycle_class,"
                "source_plan_start_utc,source_plan_end_utc,accepted_source_observation_id,"
                "source_projection_revision,source_base_token,last_command_id "
                "FROM wfm_source_projection_cache WHERE task_id=?",
                (wfm.task_id,),
            ).fetchone()
        )
        local_revision_before = int(
            snapshot.connection.execute(
                "SELECT revision FROM tasks WHERE task_id=?",
                (local.task_id,),
            ).fetchone()[0]
        )
        aggregate_before = tuple(
            snapshot.connection.execute(
                "SELECT execution_state,revision,aggregate_input_fingerprint "
                "FROM objective_aggregate_projection WHERE objective_id=?",
                (objective.objective_id,),
            ).fetchone()
        )

    task_participant = RfcTerminalTaskParticipant()
    capture = RfcTerminalCascadeCaptureService(task_participant)
    source = RfcSourceProjectionService(
        _AcceptingEvidenceProvider(),
        terminal_capture_participant=capture,
    )
    terminal_command = new_uuid4()
    with UnitOfWork(factory) as uow:
        _insert_outer_receipt(uow, terminal_command, rfc.rfc_id)
        applied = source.apply_accepted_field_deltas(
            uow,
            rfc_id=rfc.rfc_id,
            accepted_command_id=terminal_command,
            deltas=(_status(),),
        )
        assert applied.pending_cascade_proposal_id is not None
        proposal_id = applied.pending_cascade_proposal_id

    communication = _ExecutionParticipant(
        domain="COMMUNICATIONS",
        fingerprint=sha256_canonical_json(
            {"schema": "T020_EMPTY_COMMUNICATIONS_V1"}
        ),
        apply_result=_apply_result(
            "COMMUNICATIONS",
            result_count=0,
            audit_count=0,
        ),
    )
    preview = RfcTerminalCascadePreviewService(
        factory,
        task_participant,
        communication,
    ).preview(proposal_id=proposal_id, limit=500)
    assert preview.execution_ready is True
    assert preview.execution_review is not None

    task_impacts = [
        item for item in preview.impacts if item.domain == "TASKS_OBJECTIVES"
    ]
    assert any(
        item.impact_kind == "WFM_TERMINATION"
        and item.entity_id == wfm.task_id
        and item.current_state == "not_started"
        and item.resulting_state == "terminated"
        for item in task_impacts
    )
    objective_impact = next(
        item
        for item in task_impacts
        if item.impact_kind == "OBJECTIVE_EXECUTABLE_COUNT"
        and item.entity_id == objective.objective_id
    )
    assert objective_impact.current_count == 2
    assert objective_impact.resulting_count == 1
    assert objective_impact.attention_code is None

    with ReadSnapshot(factory) as snapshot:
        receipts_before = int(
            snapshot.connection.execute(
                "SELECT COUNT(*) FROM command_receipts"
            ).fetchone()[0]
        )

    proof = _ProofProvider()
    execute = RfcTerminalCascadeExecutionService(
        factory,
        task_participant,
        communication,
        proof,
    )
    execute_command = new_uuid4()
    result = execute.execute(
        command_id=execute_command,
        proposal_id=proposal_id,
        proposal_revision=preview.proposal_revision,
        execution_review=preview.execution_review,
        deliberate_action_proof="proof-real-t020",
    )
    assert result.state == "executed"

    with ReadSnapshot(factory) as snapshot:
        assert int(
            snapshot.connection.execute(
                "SELECT COUNT(*) FROM command_receipts"
            ).fetchone()[0]
        ) == receipts_before + 1

        wfm_execution = tuple(
            snapshot.connection.execute(
                "SELECT execution_state,actual_start_utc,actual_end_utc,"
                "effective_termination_utc,termination_reason,revision "
                "FROM task_execution_projection WHERE task_id=?",
                (wfm.task_id,),
            ).fetchone()
        )
        assert wfm_execution[0] == "terminated"
        assert wfm_execution[1] is None and wfm_execution[2] is None
        assert wfm_execution[3] is None
        assert wfm_execution[4] == "rfc_terminal_cascade"
        assert int(wfm_execution[5]) == 1

        assert snapshot.connection.execute(
            "SELECT 1 FROM task_execution_projection WHERE task_id=?",
            (local.task_id,),
        ).fetchone() is None
        assert int(
            snapshot.connection.execute(
                "SELECT revision FROM tasks WHERE task_id=?",
                (local.task_id,),
            ).fetchone()[0]
        ) == local_revision_before

        source_after = tuple(
            snapshot.connection.execute(
                "SELECT provider_status_token,provider_lifecycle_class,"
                "source_plan_start_utc,source_plan_end_utc,accepted_source_observation_id,"
                "source_projection_revision,source_base_token,last_command_id "
                "FROM wfm_source_projection_cache WHERE task_id=?",
                (wfm.task_id,),
            ).fetchone()
        )
        assert source_after == source_before

        aggregate_after = tuple(
            snapshot.connection.execute(
                "SELECT execution_state,revision,aggregate_input_fingerprint "
                "FROM objective_aggregate_projection WHERE objective_id=?",
                (objective.objective_id,),
            ).fetchone()
        )
        assert aggregate_after[0] == "planned"
        assert int(aggregate_after[1]) > int(aggregate_before[1])
        assert str(aggregate_after[2]) != str(aggregate_before[2])

        assert snapshot.connection.execute(
            "SELECT COUNT(*) FROM audit_events "
            "WHERE command_id=? AND action_type='task.rfc_terminal_cascade_applied'",
            (execute_command,),
        ).fetchone()[0] == 1
        assert snapshot.connection.execute(
            "SELECT executed_command_id FROM rfc_terminal_cascade_proposals "
            "WHERE rfc_terminal_cascade_proposal_id=?",
            (proposal_id,),
        ).fetchone()[0] == execute_command
