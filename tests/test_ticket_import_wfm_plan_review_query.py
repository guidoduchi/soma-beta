from __future__ import annotations

import pytest

from soma.foundation.errors import SomaError
from soma.foundation.identifiers import new_uuid4
from soma.foundation.persistence.uow import ReadSnapshot, UnitOfWork
from soma.objectives_tasks import TaskPlanningService
from soma.objectives_tasks.services.wfm_import import (
    WfmImportBaseTarget,
    WfmImportMutationParticipant,
    WfmImportReader,
    WfmSourceProjectionAcceptanceMutation,
)
from soma.ticket_import.queries.wfm_plan import WfmPlanReviewQueryService
from soma.tickets.rfcs import RfcService


def _factory(initialized_database):
    database_path, factory_for_path = initialized_database
    return factory_for_path(database_path)


def _insert_outer_receipt(uow: UnitOfWork, *, command_id: str) -> None:
    uow.connection.execute(
        "INSERT INTO command_receipts(command_id,command_type,request_hash,target_type,target_id,"
        "committed_at_utc,result_type,result_id) "
        "VALUES (?,'AcceptReconciliationProposal',?,'reconciliation_proposal',?,0,NULL,NULL)",
        (command_id, "a" * 64, new_uuid4()),
    )


def _create_manual_wfm(factory, *, suffix: int):
    rfc_no = f"NC{suffix:014d}"
    rfc = RfcService(factory).create_or_adopt_identity(
        command_id=new_uuid4(),
        rfc_no=rfc_no,
        creation_context="provisional",
    )
    task_no = f"TK{suffix:014d}"
    task = TaskPlanningService(factory).register_manual_wfm_task(
        command_id=new_uuid4(),
        task_no=task_no,
        rfc_id=rfc.rfc_id,
    )
    return rfc.rfc_id, rfc_no, task_no, task


def _stage_wfm_observation(
    factory,
    *,
    observation_id: str,
    task_no: str,
    parent_rfc_no: str,
    chronology_utc: int,
) -> str:
    run_id = new_uuid4()
    with UnitOfWork(factory) as uow:
        uow.connection.execute(
            "INSERT INTO import_runs(import_run_id,source_family,invocation_kind,source_profile_id,header_registry_id,"
            "vocabulary_registry_id,parser_profile_id,candidate_filename,candidate_file_size_bytes,"
            "candidate_stable_mtime_ns,candidate_chronology_kind,candidate_chronology_value,"
            "logical_fingerprint_sha256,run_state,started_at_utc,staged_at_utc,observed_row_count,"
            "valid_identity_count,proposal_count,pending_proposal_count,revision) "
            "VALUES (?,'wfm_service_provider','manual','WFM_SERVICE_PROVIDER_V1','WFM_HEADERS_V1',"
            "'WFM_VOCAB_V1','WFM_PARSER_V1','wfm.xlsx',1,1,'filesystem_mtime_ns',1,?,'staged',1,1,1,1,1,1,1)",
            (run_id, "f" * 64),
        )
        uow.connection.execute(
            "INSERT INTO source_observations(source_observation_id,import_run_id,source_family,entity_kind,"
            "identity_state,canonical_primary_id,canonical_parent_rfc_no,row_ordinal,sheet_ordinal,row_logical_sha256,"
            "source_row_chronology_utc,presence_state,recorded_at_utc) "
            "VALUES (?,?,'wfm_service_provider','wfm','valid',?,?,1,1,?,?,'observed_valid_identity',1)",
            (observation_id, run_id, task_no, parent_rfc_no, "1" * 64, chronology_utc),
        )
    return run_id


def _apply_source_plan(
    factory,
    *,
    task_id: str,
    task_no: str,
    observation_id: str,
    start_utc: int,
    end_utc: int,
) -> None:
    with ReadSnapshot(factory) as snapshot:
        base_token = WfmImportReader.source_acceptance_base_token(
            snapshot.connection,
            WfmImportBaseTarget("wfm_source_projection", task_no, task_id),
        )
    command_id = new_uuid4()
    with UnitOfWork(factory) as uow:
        _insert_outer_receipt(uow, command_id=command_id)
        WfmImportMutationParticipant.apply_wfm_source_projection(
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
                accepted_command_id=command_id,
            ),
        )


def _insert_plan_proposal(
    factory,
    *,
    run_id: str,
    observation_id: str,
    task_id: str,
    task_no: str,
    base_token: str,
    start_utc: int,
    end_utc: int,
) -> str:
    proposal_id = new_uuid4()
    with UnitOfWork(factory) as uow:
        uow.connection.execute(
            "INSERT INTO reconciliation_proposals(reconciliation_proposal_id,import_run_id,evidence_mode,"
            "source_observation_id,prior_source_observation_id,proposal_kind,target_kind,target_internal_id,"
            "target_business_id,risk_class,base_state_token_sha256,proposal_fingerprint_sha256,proposal_state,"
            "created_at_utc,revision,decided_at_utc) "
            "VALUES (?,?,'observed_row',?,NULL,'wfm_plan_reconciliation','task_plan',?,?,'high',?,?,"
            "'pending',1,1,NULL)",
            (proposal_id, run_id, observation_id, task_id, task_no, base_token, "2" * 64),
        )
        uow.connection.executemany(
            "INSERT INTO reconciliation_proposal_changes(reconciliation_proposal_id,ordinal,field_key,change_kind,"
            "value_kind,before_text,after_text,before_integer,after_integer,source_observation_field_id) "
            "VALUES (?,?,?,'set','instant',NULL,NULL,NULL,?,NULL)",
            (
                (proposal_id, 0, "plan_start_utc", start_utc),
                (proposal_id, 1, "plan_end_utc", end_utc),
            ),
        )
    return proposal_id


def test_wfm_plan_review_context_uses_owner_readers_and_keeps_regrouping_indeterminate(
    initialized_database,
) -> None:
    factory = _factory(initialized_database)
    _rfc_id, rfc_no, task_no, task = _create_manual_wfm(factory, suffix=901)
    observation_id = new_uuid4()
    source_start = 2_040_000_000
    source_end = source_start + 3_600
    source_chronology = source_start - 60
    run_id = _stage_wfm_observation(
        factory,
        observation_id=observation_id,
        task_no=task_no,
        parent_rfc_no=rfc_no,
        chronology_utc=source_chronology,
    )
    _apply_source_plan(
        factory,
        task_id=task.task_id,
        task_no=task_no,
        observation_id=observation_id,
        start_utc=source_start,
        end_utc=source_end,
    )
    with ReadSnapshot(factory) as snapshot:
        proposal_token = WfmImportReader.source_acceptance_base_token(
            snapshot.connection,
            WfmImportBaseTarget("wfm_plan_reconciliation", task_no, task.task_id),
        )
    proposal_id = _insert_plan_proposal(
        factory,
        run_id=run_id,
        observation_id=observation_id,
        task_id=task.task_id,
        task_no=task_no,
        base_token=proposal_token,
        start_utc=source_start,
        end_utc=source_end,
    )

    response = WfmPlanReviewQueryService(factory).get_context(proposal_id).to_response()

    assert response == {
        "proposal_id": proposal_id,
        "source_plan": {"start_utc": source_start, "end_utc": source_end},
        "operational_plan": None,
        "plan_diff": {
            "start": {"source_utc": source_start, "operational_utc": None, "changed": True},
            "end": {"source_utc": source_end, "operational_utc": None, "changed": True},
        },
        "source_chronology": source_chronology,
        "objective_regrouping_consequence": "INDETERMINATE",
        "base_state_token": proposal_token,
    }


def test_wfm_plan_review_context_rejects_missing_and_wrong_kind_proposals(initialized_database) -> None:
    factory = _factory(initialized_database)
    service = WfmPlanReviewQueryService(factory)

    with pytest.raises(SomaError) as missing:
        service.get_context(new_uuid4())
    assert missing.value.code == "IMPORT_PROPOSAL_NOT_FOUND"

    _rfc_id, rfc_no, task_no, task = _create_manual_wfm(factory, suffix=902)
    observation_id = new_uuid4()
    run_id = _stage_wfm_observation(
        factory,
        observation_id=observation_id,
        task_no=task_no,
        parent_rfc_no=rfc_no,
        chronology_utc=2_041_000_000,
    )
    proposal_id = new_uuid4()
    with UnitOfWork(factory) as uow:
        uow.connection.execute(
            "INSERT INTO reconciliation_proposals(reconciliation_proposal_id,import_run_id,evidence_mode,"
            "source_observation_id,prior_source_observation_id,proposal_kind,target_kind,target_internal_id,"
            "target_business_id,risk_class,base_state_token_sha256,proposal_fingerprint_sha256,proposal_state,"
            "created_at_utc,revision,decided_at_utc) "
            "VALUES (?,?,'observed_row',?,NULL,'wfm_source_projection','wfm',?,?,'medium',?,?,"
            "'pending',1,1,NULL)",
            (proposal_id, run_id, observation_id, task.task_id, task_no, "3" * 64, "4" * 64),
        )

    with pytest.raises(SomaError) as wrong_kind:
        service.get_context(proposal_id)
    assert wrong_kind.value.code == "IMPORT_PROPOSAL_KIND_INVALID"
