from __future__ import annotations

from soma.foundation.identifiers import new_uuid4
from soma.foundation.persistence.uow import UnitOfWork
from soma.ticket_import.queries.proposals import ProposalQueryService
from soma.tickets.service_request_import_reader import ServiceRequestImportReader
from soma.tickets.service_requests import ServiceRequestService


def _factory(initialized_database):
    database_path, factory_builder = initialized_database
    return factory_builder(database_path)


def test_proposal_review_uses_certified_sr_source_field_set_token(initialized_database) -> None:
    factory = _factory(initialized_database)
    sr_no = "87654322"
    sr = ServiceRequestService(factory).create_manual_service_request(
        command_id=new_uuid4(),
        official_sr_no=sr_no,
    )
    run_id = new_uuid4()
    observation_id = new_uuid4()
    field_id = new_uuid4()
    proposal_id = new_uuid4()

    with UnitOfWork(factory) as uow:
        uow.connection.execute(
            "INSERT INTO import_runs(import_run_id,source_family,invocation_kind,source_profile_id,header_registry_id,"
            "vocabulary_registry_id,parser_profile_id,candidate_filename,candidate_file_size_bytes,"
            "candidate_stable_mtime_ns,candidate_chronology_kind,candidate_chronology_value,"
            "logical_fingerprint_sha256,run_state,started_at_utc,staged_at_utc,observed_row_count,"
            "valid_identity_count,proposal_count,pending_proposal_count,revision) "
            "VALUES (?,'advanced_search_sr','manual','ADVANCED_SEARCH_SR_V1','ADVANCED_SEARCH_HEADERS_V1',"
            "'ADVANCED_SEARCH_VOCAB_V1','ADVANCED_SEARCH_PARSER_V1','source.xlsx',1,1,"
            "'embedded_filename_timestamp_utc',1,?,'staged',1,1,1,1,1,1,1)",
            (run_id, "a" * 64),
        )
        uow.connection.execute(
            "INSERT INTO source_observations(source_observation_id,import_run_id,source_family,entity_kind,"
            "identity_state,canonical_primary_id,canonical_parent_rfc_no,row_ordinal,sheet_ordinal,row_logical_sha256,"
            "source_row_chronology_utc,presence_state,recorded_at_utc) "
            "VALUES (?,?,'advanced_search_sr','service_request','valid',?,NULL,1,1,?,10,"
            "'observed_valid_identity',1)",
            (observation_id, run_id, sr_no, "b" * 64),
        )
        uow.connection.execute(
            "INSERT INTO source_observation_fields(source_observation_field_id,source_observation_id,field_key,"
            "field_class,value_state,value_kind,source_text,normalized_text,integer_value,vocabulary_id,"
            "field_logical_sha256) VALUES (?,?,'problem_summary','active','usable','text',"
            "'new source summary','new source summary',NULL,NULL,?)",
            (field_id, observation_id, "c" * 64),
        )
        base_token = ServiceRequestImportReader.source_field_set_base_token(
            uow.connection,
            sr.service_request_id,
            ("problem_summary",),
        )
        uow.connection.execute(
            "INSERT INTO reconciliation_proposals(reconciliation_proposal_id,import_run_id,evidence_mode,"
            "source_observation_id,prior_source_observation_id,proposal_kind,target_kind,target_internal_id,"
            "target_business_id,risk_class,base_state_token_sha256,proposal_fingerprint_sha256,proposal_state,"
            "created_at_utc,revision,decided_at_utc) VALUES (?,?,'observed_row',?,NULL,'sr_source_projection',"
            "'service_request',?,?,'low',?,?,'pending',1,1,NULL)",
            (proposal_id, run_id, observation_id, sr.service_request_id, sr_no, base_token, "d" * 64),
        )
        uow.connection.execute(
            "INSERT INTO reconciliation_proposal_changes(reconciliation_proposal_id,ordinal,field_key,change_kind,"
            "value_kind,before_text,after_text,before_integer,after_integer,source_observation_field_id) "
            "VALUES (?,0,'problem_summary','set','text',NULL,'new source summary',NULL,NULL,?)",
            (proposal_id, field_id),
        )

    review = ProposalQueryService(factory).get_review(proposal_id)
    assert review.stale is False
    assert review.allowed_dispositions == ("accept", "reject", "defer")
    assert review.proposal.base_state_token == base_token
