from __future__ import annotations

from soma.foundation.identifiers import new_uuid4
from soma.foundation.persistence.uow import UnitOfWork
from soma.objectives_tasks import TaskPlanningService
from soma.objectives_tasks.services.wfm_import import WfmImportBaseTarget, WfmImportReader
from soma.ticket_import.queries.proposals import ProposalQueryService
from soma.tickets.rfc_import_reader import RfcImportReader
from soma.tickets.rfcs import RfcService


def _factory(initialized_database):
    database_path, factory_builder = initialized_database
    return factory_builder(database_path)


def _seed_run(
    uow: UnitOfWork,
    *,
    run_id: str,
    source_family: str,
    source_profile_id: str,
    header_registry_id: str,
    vocabulary_registry_id: str,
    parser_profile_id: str,
) -> None:
    uow.connection.execute(
        "INSERT INTO import_runs(import_run_id,source_family,invocation_kind,source_profile_id,header_registry_id,"
        "vocabulary_registry_id,parser_profile_id,candidate_filename,candidate_file_size_bytes,"
        "candidate_stable_mtime_ns,candidate_chronology_kind,candidate_chronology_value,"
        "logical_fingerprint_sha256,run_state,started_at_utc,staged_at_utc,observed_row_count,"
        "valid_identity_count,proposal_count,pending_proposal_count,revision) "
        "VALUES (?,?, 'manual',?,?,?,?, 'source.xlsx',1,1,'filesystem_mtime_ns',1,?,"
        "'waiting_review',1,1,1,1,1,1,1)",
        (
            run_id,
            source_family,
            source_profile_id,
            header_registry_id,
            vocabulary_registry_id,
            parser_profile_id,
            "a" * 64,
        ),
    )


def test_get_proposal_review_exposes_fresh_rfc_owner_acceptance(initialized_database) -> None:
    factory = _factory(initialized_database)
    rfc = RfcService(factory).create_or_adopt_identity(
        command_id=new_uuid4(),
        rfc_no="NC00000000007001",
        creation_context="manual",
    )
    run_id = new_uuid4()
    observation_id = new_uuid4()
    field_id = new_uuid4()
    proposal_id = new_uuid4()

    with UnitOfWork(factory) as uow:
        _seed_run(
            uow,
            run_id=run_id,
            source_family="rfc_enhanced",
            source_profile_id="RFC_ENHANCED_V1",
            header_registry_id="RFC_HEADERS_V1",
            vocabulary_registry_id="RFC_VOCAB_V1",
            parser_profile_id="RFC_PARSER_V1",
        )
        uow.connection.execute(
            "INSERT INTO source_observations(source_observation_id,import_run_id,source_family,entity_kind,"
            "identity_state,canonical_primary_id,canonical_parent_rfc_no,row_ordinal,sheet_ordinal,row_logical_sha256,"
            "source_row_chronology_utc,presence_state,recorded_at_utc) "
            "VALUES (?,?,'rfc_enhanced','rfc','valid',?,NULL,1,1,?,10,'observed_valid_identity',1)",
            (observation_id, run_id, rfc.rfc_no, "b" * 64),
        )
        uow.connection.execute(
            "INSERT INTO source_observation_fields(source_observation_field_id,source_observation_id,field_key,"
            "field_class,value_state,value_kind,source_text,normalized_text,integer_value,vocabulary_id,"
            "field_logical_sha256) VALUES (?,?,'summary','active','usable','text','review summary',"
            "'review summary',NULL,NULL,?)",
            (field_id, observation_id, "c" * 64),
        )
        base_token = RfcImportReader().source_acceptance_base_token(uow.connection, rfc.rfc_id)
        uow.connection.execute(
            "INSERT INTO reconciliation_proposals(reconciliation_proposal_id,import_run_id,evidence_mode,"
            "source_observation_id,prior_source_observation_id,proposal_kind,target_kind,target_internal_id,"
            "target_business_id,risk_class,base_state_token_sha256,proposal_fingerprint_sha256,proposal_state,"
            "created_at_utc,revision,decided_at_utc) VALUES (?,?,'observed_row',?,NULL,'rfc_source_projection',"
            "'rfc',?,?,'medium',?,?,'pending',1,1,NULL)",
            (
                proposal_id,
                run_id,
                observation_id,
                rfc.rfc_id,
                rfc.rfc_no,
                base_token,
                "d" * 64,
            ),
        )
        uow.connection.execute(
            "INSERT INTO reconciliation_proposal_changes(reconciliation_proposal_id,ordinal,field_key,change_kind,"
            "value_kind,before_text,after_text,before_integer,after_integer,source_observation_field_id) "
            "VALUES (?,0,'summary','set','text',NULL,'review summary',NULL,NULL,?)",
            (proposal_id, field_id),
        )

    review = ProposalQueryService(factory).get_review(proposal_id)
    assert review.stale is False
    assert review.allowed_dispositions == ("accept", "reject", "defer")
    assert review.target_preview["owner"] == "LLD-03"
    assert review.target_preview["identity"]["rfc_id"] == rfc.rfc_id
    assert review.target_preview["current_source_projection"] is None
    assert review.proposal.base_state_token == base_token


def test_get_proposal_review_exposes_fresh_wfm_owner_acceptance(initialized_database) -> None:
    factory = _factory(initialized_database)
    rfc = RfcService(factory).create_or_adopt_identity(
        command_id=new_uuid4(),
        rfc_no="NC00000000007002",
        creation_context="manual",
    )
    task_no = "TK00000000007002"
    task = TaskPlanningService(factory).register_manual_wfm_task(
        command_id=new_uuid4(),
        task_no=task_no,
        rfc_id=rfc.rfc_id,
    )
    run_id = new_uuid4()
    observation_id = new_uuid4()
    field_id = new_uuid4()
    proposal_id = new_uuid4()

    with UnitOfWork(factory) as uow:
        _seed_run(
            uow,
            run_id=run_id,
            source_family="wfm_service_provider",
            source_profile_id="WFM_SERVICE_PROVIDER_V1",
            header_registry_id="WFM_HEADERS_V1",
            vocabulary_registry_id="WFM_VOCAB_V1",
            parser_profile_id="WFM_PARSER_V1",
        )
        uow.connection.execute(
            "INSERT INTO source_observations(source_observation_id,import_run_id,source_family,entity_kind,"
            "identity_state,canonical_primary_id,canonical_parent_rfc_no,row_ordinal,sheet_ordinal,row_logical_sha256,"
            "source_row_chronology_utc,presence_state,recorded_at_utc) "
            "VALUES (?,?,'wfm_service_provider','wfm','valid',?,?,1,1,?,10,'observed_valid_identity',1)",
            (observation_id, run_id, task_no, rfc.rfc_no, "e" * 64),
        )
        uow.connection.execute(
            "INSERT INTO source_observation_fields(source_observation_field_id,source_observation_id,field_key,"
            "field_class,value_state,value_kind,source_text,normalized_text,integer_value,vocabulary_id,"
            "field_logical_sha256) VALUES (?,?,'task_status','active','unknown','controlled','Implementation',"
            "NULL,NULL,'WFM_TASK_STATUS_V1',?)",
            (field_id, observation_id, "f" * 64),
        )
        base_token = WfmImportReader.source_acceptance_base_token(
            uow.connection,
            WfmImportBaseTarget("wfm_source_projection", task_no, task.task_id),
        )
        uow.connection.execute(
            "INSERT INTO reconciliation_proposals(reconciliation_proposal_id,import_run_id,evidence_mode,"
            "source_observation_id,prior_source_observation_id,proposal_kind,target_kind,target_internal_id,"
            "target_business_id,risk_class,base_state_token_sha256,proposal_fingerprint_sha256,proposal_state,"
            "created_at_utc,revision,decided_at_utc) VALUES (?,?,'observed_row',?,NULL,'wfm_source_projection',"
            "'wfm',?,?,'medium',?,?,'pending',1,1,NULL)",
            (
                proposal_id,
                run_id,
                observation_id,
                task.task_id,
                task_no,
                base_token,
                "1" * 64,
            ),
        )
        uow.connection.execute(
            "INSERT INTO reconciliation_proposal_changes(reconciliation_proposal_id,ordinal,field_key,change_kind,"
            "value_kind,before_text,after_text,before_integer,after_integer,source_observation_field_id) "
            "VALUES (?,0,'task_status','set','controlled',NULL,'Implementation',NULL,NULL,?)",
            (proposal_id, field_id),
        )

    review = ProposalQueryService(factory).get_review(proposal_id)
    assert review.stale is False
    assert review.allowed_dispositions == ("accept", "reject", "defer")
    assert review.target_preview["owner"] == "LLD-05"
    assert review.target_preview["identity"]["task_id"] == task.task_id
    assert review.target_preview["current_source_projection"] is None
    assert review.proposal.base_state_token == base_token
