from __future__ import annotations

import pytest

from soma.foundation.audit.writer import AuditWriter
from soma.foundation.errors import IntegrityFailure, SomaError, ValidationError
from soma.foundation.identifiers import new_uuid4
from soma.foundation.persistence.uow import ReadSnapshot, UnitOfWork
from soma.objectives_tasks.contracts.objectives_tasks import AcceptedTaskSchedule
from soma.objectives_tasks.queries.task_activity_review import WfmActivityRelationshipReviewQueryService
from soma.objectives_tasks.services.task_activity_review import WfmActivityRelationshipReviewService
from soma.objectives_tasks.services.task_planning import TaskPlanningService
from soma.objectives_tasks.services.wfm_import import (
    WfmImportBaseTarget,
    WfmImportMutationParticipant,
    WfmImportReader,
    WfmSourceProjectionAcceptanceMutation,
)
from soma.ticket_import.commands.decide_proposal import ProposalDecisionService
from soma.ticket_import.commands.review_competing_attempt import WfmCompetingAttemptReviewService
from soma.tickets.rfcs import RfcService


def _factory(initialized_database):
    database_path, factory_for_path = initialized_database
    return factory_for_path(database_path)


def _create_rfc(factory, suffix: int) -> tuple[str, str]:
    rfc_no = f"NC{suffix:014d}"
    result = RfcService(factory).create_or_adopt_identity(
        command_id=new_uuid4(),
        rfc_no=rfc_no,
        creation_context="provisional",
    )
    return result.rfc_id, rfc_no


def _register_wfm(
    factory,
    *,
    rfc_id: str,
    task_no: str,
    start_utc: int,
):
    return TaskPlanningService(factory).register_manual_wfm_task(
        command_id=new_uuid4(),
        task_no=task_no,
        rfc_id=rfc_id,
        schedule=AcceptedTaskSchedule(
            start_utc=start_utc,
            end_utc=start_utc + 3_600,
            scheduling_timezone_iana="America/Guayaquil",
        ),
    )


def _review_same_activity(factory, task_ids: tuple[str, str]) -> str:
    canonical_task_ids = tuple(sorted(task_ids))
    query = WfmActivityRelationshipReviewQueryService(factory)
    preview = query.preview(seed_task_ids=canonical_task_ids, decision="same_activity")
    result = WfmActivityRelationshipReviewService(factory).review_wfm_activity_relationship(
        command_id=new_uuid4(),
        seed_tasks=tuple((seed.task_id, seed.task_revision) for seed in preview.seed_tasks),
        decision="same_activity",
        review_fingerprint=preview.review_fingerprint,
        reason_category="establish_competing_attempt_lineage",
    )
    assert result.outcome == "APPLIED"
    with ReadSnapshot(factory) as snapshot:
        rows = snapshot.connection.execute(
            "SELECT task_id,activity_lineage_id FROM task_activity_lineage_current "
            "WHERE task_id IN (?,?) ORDER BY task_id",
            canonical_task_ids,
        ).fetchall()
    assert len(rows) == 2
    lineage_ids = {str(row[1]) for row in rows}
    assert len(lineage_ids) == 1
    return lineage_ids.pop()


def _seed_published_wfm_source(
    factory,
    *,
    task_id: str,
    task_no: str,
    rfc_no: str,
    start_utc: int,
    end_utc: int,
) -> dict[str, str | int]:
    run_id = new_uuid4()
    observation_id = new_uuid4()
    start_field_id = new_uuid4()
    end_field_id = new_uuid4()
    with UnitOfWork(factory) as uow:
        uow.connection.execute(
            "INSERT INTO import_runs("
            "import_run_id,source_family,invocation_kind,source_profile_id,header_registry_id,vocabulary_registry_id,parser_profile_id,"
            "candidate_filename,candidate_file_size_bytes,candidate_stable_mtime_ns,candidate_chronology_kind,candidate_chronology_value,"
            "logical_fingerprint_sha256,run_state,started_at_utc,staged_at_utc,observed_row_count,valid_identity_count,"
            "proposal_count,pending_proposal_count,revision"
            ") VALUES (?,'wfm_service_provider','manual','WFM_SERVICE_PROVIDER_V1','WFM_HEADERS_V1','WFM_VOCAB_V1',"
            "'WFM_PARSER_V1','WFM Service Provider.xlsx',100,1,'embedded_filename_timestamp_utc',200,?,"
            "'waiting_review',0,1,1,1,1,1,1)",
            (run_id, "1" * 64),
        )
        uow.connection.execute(
            "INSERT INTO source_observations(source_observation_id,import_run_id,source_family,entity_kind,identity_state,"
            "canonical_primary_id,canonical_parent_rfc_no,row_ordinal,sheet_ordinal,row_logical_sha256,source_row_chronology_utc,"
            "presence_state,recorded_at_utc) VALUES (?,?,'wfm_service_provider','wfm','valid',?,?,1,1,?,200,"
            "'observed_valid_identity',1)",
            (observation_id, run_id, task_no, rfc_no, "2" * 64),
        )
        uow.connection.execute(
            "INSERT INTO source_observation_fields(source_observation_field_id,source_observation_id,field_key,field_class,"
            "value_state,value_kind,source_text,normalized_text,integer_value,vocabulary_id,field_logical_sha256) "
            "VALUES (?,?,'planned_start','active','usable','instant',?,NULL,?,NULL,?)",
            (start_field_id, observation_id, str(start_utc), start_utc, "3" * 64),
        )
        uow.connection.execute(
            "INSERT INTO source_observation_fields(source_observation_field_id,source_observation_id,field_key,field_class,"
            "value_state,value_kind,source_text,normalized_text,integer_value,vocabulary_id,field_logical_sha256) "
            "VALUES (?,?,'planned_end','active','usable','instant',?,NULL,?,NULL,?)",
            (end_field_id, observation_id, str(end_utc), end_utc, "4" * 64),
        )

    with ReadSnapshot(factory) as snapshot:
        base_token = WfmImportReader.source_acceptance_base_token(
            snapshot.connection,
            WfmImportBaseTarget("wfm_source_projection", task_no, task_id),
        )
    source_command_id = new_uuid4()
    with UnitOfWork(factory) as uow:
        uow.connection.execute(
            "INSERT INTO command_receipts(command_id,command_type,request_hash,target_type,target_id,"
            "committed_at_utc,result_type,result_id) "
            "VALUES (?,'AcceptReconciliationProposal',?,'reconciliation_proposal',?,0,NULL,NULL)",
            (source_command_id, "5" * 64, new_uuid4()),
        )
        result = WfmImportMutationParticipant.apply_wfm_source_projection(
            uow,
            WfmSourceProjectionAcceptanceMutation(
                task_id=task_id,
                task_no=task_no,
                expected_source_projection_revision=0,
                provider_status_token="Implementation",
                provider_lifecycle_class="active",
                source_plan_start_utc=start_utc,
                source_plan_end_utc=end_utc,
                accepted_source_observation_id=observation_id,
                base_state_token=base_token,
                accepted_command_id=source_command_id,
            ),
        )
        assert result.source_projection_revision == 1
        assert result.audit_events == ()
    return {
        "run_id": run_id,
        "observation_id": observation_id,
        "start_field_id": start_field_id,
        "end_field_id": end_field_id,
        "source_command_id": source_command_id,
    }


def _seed_review_scope(factory, *, suffix: int = 960) -> dict[str, object]:
    rfc_id, rfc_no = _create_rfc(factory, suffix)
    subject_no = f"TK{suffix:014d}"
    counterpart_no = f"TK{suffix + 1:014d}"
    subject_start = 2_200_000_000 + suffix * 10_000
    counterpart_start = subject_start + 600
    subject = _register_wfm(
        factory,
        rfc_id=rfc_id,
        task_no=subject_no,
        start_utc=subject_start,
    )
    counterpart = _register_wfm(
        factory,
        rfc_id=rfc_id,
        task_no=counterpart_no,
        start_utc=counterpart_start,
    )
    evidence = _seed_published_wfm_source(
        factory,
        task_id=subject.task_id,
        task_no=subject_no,
        rfc_no=rfc_no,
        start_utc=subject_start,
        end_utc=subject_start + 3_600,
    )
    lineage_id = _review_same_activity(factory, (subject.task_id, counterpart.task_id))

    with ReadSnapshot(factory) as snapshot:
        conflict = WfmImportReader.activity_conflicts(
            snapshot.connection,
            {"task_no": subject_no, "current_rfc_id": rfc_id, "task_id": subject.task_id},
            {"start_utc": subject_start, "end_utc": subject_start + 3_600},
            counterpart.task_id,
        )
    assert conflict["classification"] == "SAME_REVIEWED_LINEAGE_OVERLAP"
    assert conflict["activity_lineage_id"] == lineage_id
    assert conflict["selected_counterpart"]["task_id"] == counterpart.task_id
    base_token = str(conflict["conflict_fingerprint"])
    proposal_id = new_uuid4()
    proposal_fingerprint = "7" * 64
    with UnitOfWork(factory) as uow:
        uow.connection.execute(
            "INSERT INTO reconciliation_proposals(reconciliation_proposal_id,import_run_id,evidence_mode,source_observation_id,"
            "prior_source_observation_id,proposal_kind,target_kind,target_internal_id,target_business_id,risk_class,"
            "base_state_token_sha256,proposal_fingerprint_sha256,proposal_state,created_at_utc,revision,decided_at_utc) "
            "VALUES (?,?,'observed_row',?,NULL,'wfm_competing_attempt_review','activity_lineage',?,?,'high',?,?,'pending',1,1,NULL)",
            (
                proposal_id,
                evidence["run_id"],
                evidence["observation_id"],
                lineage_id,
                subject_no,
                base_token,
                proposal_fingerprint,
            ),
        )
        uow.connection.execute(
            "INSERT INTO reconciliation_proposal_changes(reconciliation_proposal_id,ordinal,field_key,change_kind,value_kind,"
            "before_text,after_text,before_integer,after_integer,source_observation_field_id) "
            "VALUES (?,0,'competing_attempt_counterpart','conflict','identity',NULL,?,NULL,NULL,NULL)",
            (proposal_id, counterpart.task_id),
        )
    return {
        "rfc_id": rfc_id,
        "rfc_no": rfc_no,
        "subject_id": subject.task_id,
        "subject_no": subject_no,
        "counterpart_id": counterpart.task_id,
        "counterpart_no": counterpart_no,
        "subject_start": subject_start,
        "lineage_id": lineage_id,
        "proposal_id": proposal_id,
        "proposal_fingerprint": proposal_fingerprint,
        "base_token": base_token,
        **evidence,
    }


def _activity_preview(factory, scope: dict[str, object], decision: str):
    seed_task_ids = tuple(sorted((str(scope["subject_id"]), str(scope["counterpart_id"]))))
    return WfmActivityRelationshipReviewQueryService(factory).preview(
        seed_task_ids=seed_task_ids,
        decision=decision,
    )


def _resolve(service, scope: dict[str, object], *, command_id: str, decision: str, fingerprint: str, reason: str):
    return service.resolve(
        command_id=command_id,
        proposal_id=str(scope["proposal_id"]),
        proposal_revision=1,
        proposal_fingerprint=str(scope["proposal_fingerprint"]),
        base_state_token=str(scope["base_token"]),
        decision=decision,
        activity_review_fingerprint=fingerprint,
        reason_category=reason,
    )


def test_competing_attempt_resolution_applies_atomically_and_replays_before_owner_reads(
    initialized_database,
    monkeypatch,
) -> None:
    factory = _factory(initialized_database)
    scope = _seed_review_scope(factory, suffix=960)
    preview = _activity_preview(factory, scope, "distinct_activity")
    assert not preview.semantic_no_change
    command_id = new_uuid4()
    service = WfmCompetingAttemptReviewService(factory)

    result = _resolve(
        service,
        scope,
        command_id=command_id,
        decision="distinct_activity",
        fingerprint=preview.review_fingerprint,
        reason="x" * 128,
    )
    assert result.decision == "accepted"
    assert result.revision == 2
    assert result.replayed is False
    assert any(kind == "task_activity_lineage_event" for kind, _ in result.owner_result_refs)

    with ReadSnapshot(factory) as snapshot:
        proposal = snapshot.connection.execute(
            "SELECT proposal_state,revision FROM reconciliation_proposals WHERE reconciliation_proposal_id=?",
            (scope["proposal_id"],),
        ).fetchone()
        run = snapshot.connection.execute(
            "SELECT run_state,pending_proposal_count,accepted_proposal_count,revision FROM import_runs WHERE import_run_id=?",
            (scope["run_id"],),
        ).fetchone()
        assert tuple(proposal) == ("accepted", 2)
        assert tuple(run) == ("waiting_review", 0, 1, 2)
        assert snapshot.connection.execute(
            "SELECT count(*) FROM command_receipts WHERE command_id=?", (command_id,)
        ).fetchone()[0] == 1
        assert snapshot.connection.execute(
            "SELECT count(*) FROM proposal_dispositions WHERE reconciliation_proposal_id=?",
            (scope["proposal_id"],),
        ).fetchone()[0] == 1
        assert snapshot.connection.execute(
            "SELECT count(*) FROM audit_events WHERE command_id=? AND action_type='ticket_import.proposal_decided'",
            (command_id,),
        ).fetchone()[0] == 1
        assert snapshot.connection.execute(
            "SELECT count(*) FROM audit_events WHERE command_id=? AND action_type='task.activity_relationship_reviewed'",
            (command_id,),
        ).fetchone()[0] == 2
        lineages = snapshot.connection.execute(
            "SELECT count(DISTINCT activity_lineage_id) FROM task_activity_lineage_current WHERE task_id IN (?,?)",
            (scope["subject_id"], scope["counterpart_id"]),
        ).fetchone()[0]
        assert lineages == 2

    def explode(*args, **kwargs):
        raise AssertionError("replay performed forbidden current-state read")

    monkeypatch.setattr(service._evidence, "load_exact", explode)
    monkeypatch.setattr(service._wfm_reader, "activity_conflicts", explode)
    replay = _resolve(
        service,
        scope,
        command_id=command_id,
        decision="distinct_activity",
        fingerprint=preview.review_fingerprint,
        reason="x" * 128,
    )
    assert replay.replayed is True
    assert replay.decision == result.decision
    assert replay.revision == result.revision
    assert replay.owner_result_refs == result.owner_result_refs


def test_competing_attempt_resolution_accepts_semantic_no_change_without_duplicate_lineage_history(
    initialized_database,
) -> None:
    factory = _factory(initialized_database)
    scope = _seed_review_scope(factory, suffix=970)
    preview = _activity_preview(factory, scope, "same_activity")
    assert preview.semantic_no_change
    with ReadSnapshot(factory) as snapshot:
        before_events = snapshot.connection.execute(
            "SELECT count(*) FROM task_activity_lineage_events"
        ).fetchone()[0]
    command_id = new_uuid4()
    result = _resolve(
        WfmCompetingAttemptReviewService(factory),
        scope,
        command_id=command_id,
        decision="same_activity",
        fingerprint=preview.review_fingerprint,
        reason="confirm_current_lineage",
    )
    assert result.decision == "accepted"
    assert result.owner_result_refs == ()

    with ReadSnapshot(factory) as snapshot:
        after_events = snapshot.connection.execute(
            "SELECT count(*) FROM task_activity_lineage_events"
        ).fetchone()[0]
        assert after_events == before_events
        assert snapshot.connection.execute(
            "SELECT count(*) FROM audit_events WHERE command_id=? AND action_type='task.activity_relationship_reviewed'",
            (command_id,),
        ).fetchone()[0] == 0
        assert snapshot.connection.execute(
            "SELECT count(*) FROM audit_events WHERE command_id=? AND action_type='ticket_import.proposal_decided'",
            (command_id,),
        ).fetchone()[0] == 1


def test_competing_attempt_conflict_drift_fails_before_receipt_and_leaves_proposal_pending(
    initialized_database,
) -> None:
    factory = _factory(initialized_database)
    scope = _seed_review_scope(factory, suffix=980)
    preview = _activity_preview(factory, scope, "distinct_activity")
    with ReadSnapshot(factory) as snapshot:
        row = snapshot.connection.execute(
            "SELECT t.revision,c.revision FROM tasks t JOIN task_plan_current c ON c.task_id=t.task_id WHERE t.task_id=?",
            (scope["counterpart_id"],),
        ).fetchone()
        assert row is not None
        task_revision, plan_revision = int(row[0]), int(row[1])
    moved = TaskPlanningService(factory).set_task_plan(
        command_id=new_uuid4(),
        task_id=str(scope["counterpart_id"]),
        task_revision=task_revision,
        current_plan_revision=plan_revision,
        schedule=AcceptedTaskSchedule(
            start_utc=int(scope["subject_start"]) + 20_000,
            end_utc=int(scope["subject_start"]) + 23_600,
            scheduling_timezone_iana="America/Guayaquil",
        ),
        reason_category="invalidate_competing_attempt_review",
    )
    assert moved.outcome == "APPLIED"
    command_id = new_uuid4()
    with pytest.raises(SomaError) as caught:
        _resolve(
            WfmCompetingAttemptReviewService(factory),
            scope,
            command_id=command_id,
            decision="distinct_activity",
            fingerprint=preview.review_fingerprint,
            reason="stale_conflict",
        )
    assert caught.value.code == "IMPORT_PROPOSAL_STALE"
    with ReadSnapshot(factory) as snapshot:
        assert snapshot.connection.execute(
            "SELECT 1 FROM command_receipts WHERE command_id=?", (command_id,)
        ).fetchone() is None
        proposal = snapshot.connection.execute(
            "SELECT proposal_state,revision FROM reconciliation_proposals WHERE reconciliation_proposal_id=?",
            (scope["proposal_id"],),
        ).fetchone()
        run = snapshot.connection.execute(
            "SELECT pending_proposal_count,accepted_proposal_count,revision FROM import_runs WHERE import_run_id=?",
            (scope["run_id"],),
        ).fetchone()
        assert tuple(proposal) == ("pending", 1)
        assert tuple(run) == (1, 0, 1)


def test_competing_attempt_participant_stale_failure_rolls_back_outer_receipt_and_disposition(
    initialized_database,
) -> None:
    factory = _factory(initialized_database)
    scope = _seed_review_scope(factory, suffix=990)
    preview = _activity_preview(factory, scope, "distinct_activity")

    class StaleParticipant:
        @staticmethod
        def apply_reviewed_activity_relationship(*args, **kwargs):
            raise SomaError("TASK_ACTIVITY_REVIEW_STALE", "injected participant staleness")

    command_id = new_uuid4()
    with pytest.raises(SomaError) as caught:
        _resolve(
            WfmCompetingAttemptReviewService(factory, activity_participant=StaleParticipant),
            scope,
            command_id=command_id,
            decision="distinct_activity",
            fingerprint=preview.review_fingerprint,
            reason="participant_stale",
        )
    assert caught.value.code == "IMPORT_PROPOSAL_STALE"
    with ReadSnapshot(factory) as snapshot:
        assert snapshot.connection.execute(
            "SELECT 1 FROM command_receipts WHERE command_id=?", (command_id,)
        ).fetchone() is None
        assert snapshot.connection.execute(
            "SELECT count(*) FROM proposal_dispositions WHERE reconciliation_proposal_id=?",
            (scope["proposal_id"],),
        ).fetchone()[0] == 0
        assert snapshot.connection.execute(
            "SELECT proposal_state FROM reconciliation_proposals WHERE reconciliation_proposal_id=?",
            (scope["proposal_id"],),
        ).fetchone()[0] == "pending"


def test_competing_attempt_final_orchestration_audit_failure_rolls_back_owner_mutation(
    initialized_database,
    monkeypatch,
) -> None:
    factory = _factory(initialized_database)
    scope = _seed_review_scope(factory, suffix=1000)
    preview = _activity_preview(factory, scope, "distinct_activity")
    with ReadSnapshot(factory) as snapshot:
        before_tasks = snapshot.connection.execute(
            "SELECT task_id,revision FROM tasks WHERE task_id IN (?,?) ORDER BY task_id",
            (scope["subject_id"], scope["counterpart_id"]),
        ).fetchall()
        before_lineage = snapshot.connection.execute(
            "SELECT task_id,activity_lineage_id,revision,last_event_id FROM task_activity_lineage_current "
            "WHERE task_id IN (?,?) ORDER BY task_id",
            (scope["subject_id"], scope["counterpart_id"]),
        ).fetchall()

    original_write = AuditWriter.write

    def fail_orchestration(self, uow, event):
        if event.action_type == "ticket_import.proposal_decided":
            raise IntegrityFailure("injected final orchestration audit failure")
        return original_write(self, uow, event)

    monkeypatch.setattr(AuditWriter, "write", fail_orchestration)
    command_id = new_uuid4()
    with pytest.raises(IntegrityFailure):
        _resolve(
            WfmCompetingAttemptReviewService(factory),
            scope,
            command_id=command_id,
            decision="distinct_activity",
            fingerprint=preview.review_fingerprint,
            reason="audit_failure",
        )

    with ReadSnapshot(factory) as snapshot:
        assert snapshot.connection.execute(
            "SELECT task_id,revision FROM tasks WHERE task_id IN (?,?) ORDER BY task_id",
            (scope["subject_id"], scope["counterpart_id"]),
        ).fetchall() == before_tasks
        assert snapshot.connection.execute(
            "SELECT task_id,activity_lineage_id,revision,last_event_id FROM task_activity_lineage_current "
            "WHERE task_id IN (?,?) ORDER BY task_id",
            (scope["subject_id"], scope["counterpart_id"]),
        ).fetchall() == before_lineage
        assert snapshot.connection.execute(
            "SELECT count(*) FROM audit_events WHERE command_id=?", (command_id,)
        ).fetchone()[0] == 0
        assert snapshot.connection.execute(
            "SELECT 1 FROM command_receipts WHERE command_id=?", (command_id,)
        ).fetchone() is None
        assert snapshot.connection.execute(
            "SELECT proposal_state FROM reconciliation_proposals WHERE reconciliation_proposal_id=?",
            (scope["proposal_id"],),
        ).fetchone()[0] == "pending"


def test_competing_attempt_source_identity_conflict_blocks_before_receipt(initialized_database) -> None:
    factory = _factory(initialized_database)
    scope = _seed_review_scope(factory, suffix=1010)
    preview = _activity_preview(factory, scope, "distinct_activity")
    with UnitOfWork(factory) as uow:
        uow.connection.execute(
            "INSERT INTO import_findings(import_finding_id,import_run_id,source_observation_id,field_key,finding_code,"
            "severity,scope_kind,message_text,recorded_at_utc) VALUES (?,?,?,NULL,'SOURCE_IDENTITY_CONFLICT',"
            "'high_risk','identity','injected source identity conflict',1)",
            (new_uuid4(), scope["run_id"], scope["observation_id"]),
        )
    command_id = new_uuid4()
    with pytest.raises(SomaError) as caught:
        _resolve(
            WfmCompetingAttemptReviewService(factory),
            scope,
            command_id=command_id,
            decision="distinct_activity",
            fingerprint=preview.review_fingerprint,
            reason="blocked_source_identity",
        )
    assert caught.value.code == "IMPORT_PROPOSAL_BLOCKED"
    with ReadSnapshot(factory) as snapshot:
        assert snapshot.connection.execute(
            "SELECT 1 FROM command_receipts WHERE command_id=?", (command_id,)
        ).fetchone() is None
        assert snapshot.connection.execute(
            "SELECT proposal_state FROM reconciliation_proposals WHERE reconciliation_proposal_id=?",
            (scope["proposal_id"],),
        ).fetchone()[0] == "pending"


def test_generic_accept_blocks_competing_attempt_kind_and_reason_contract_is_exact(initialized_database) -> None:
    factory = _factory(initialized_database)
    scope = _seed_review_scope(factory, suffix=1020)
    generic_command = new_uuid4()
    with pytest.raises(SomaError) as caught:
        ProposalDecisionService(factory).accept(
            command_id=generic_command,
            proposal_id=str(scope["proposal_id"]),
            proposal_revision=1,
            proposal_fingerprint=str(scope["proposal_fingerprint"]),
            base_state_token=str(scope["base_token"]),
            reason_category="must_use_dedicated_review",
        )
    assert caught.value.code == "IMPORT_PROPOSAL_BLOCKED"
    with ReadSnapshot(factory) as snapshot:
        assert snapshot.connection.execute(
            "SELECT 1 FROM command_receipts WHERE command_id=?", (generic_command,)
        ).fetchone() is None

    service = WfmCompetingAttemptReviewService(factory)
    with pytest.raises(ValidationError):
        service.resolve(
            command_id=new_uuid4(),
            proposal_id=new_uuid4(),
            proposal_revision=1,
            proposal_fingerprint="a" * 64,
            base_state_token="b" * 64,
            decision="same_activity",
            activity_review_fingerprint="c" * 64,
            reason_category="y" * 129,
        )