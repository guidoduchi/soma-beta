from __future__ import annotations

from soma.foundation.identifiers import new_uuid4
from soma.foundation.persistence.uow import ReadSnapshot, UnitOfWork
from soma.ticket_import.reconciliation.rfc_enhanced_identity import (
    build_rfc_enhanced_identity_proposals,
)
from soma.tickets.rfc_import_mutations import RfcImportMutationService


def _factory(initialized_database):
    database_path, factory_for_path = initialized_database
    return factory_for_path(database_path)


def _seed_run_and_observation(factory, rfc_no: str) -> tuple[str, str]:
    run_id = new_uuid4()
    observation_id = new_uuid4()
    field_id = new_uuid4()
    with UnitOfWork(factory) as uow:
        uow.connection.execute(
            "INSERT INTO import_runs("
            "import_run_id,source_family,invocation_kind,source_profile_id,header_registry_id,vocabulary_registry_id,parser_profile_id,"
            "candidate_filename,candidate_file_size_bytes,candidate_stable_mtime_ns,candidate_chronology_kind,candidate_chronology_value,"
            "logical_fingerprint_sha256,run_state,started_at_utc,staged_at_utc,observed_row_count,valid_identity_count,"
            "proposal_count,pending_proposal_count,revision"
            ") VALUES (?, 'rfc_enhanced','manual','RFC_ENHANCED_V1','RFC_HEADERS_V1','RFC_VOCAB_V1','RFC_PARSER_V1',"
            "'operator-rfc.xlsx',100,1,'filesystem_mtime_ns',200,?,'validating',0,1,0,0,0,0,1)",
            (run_id, "1" * 64),
        )
        uow.connection.execute(
            "INSERT INTO source_observations(source_observation_id,import_run_id,source_family,entity_kind,identity_state,"
            "canonical_primary_id,canonical_parent_rfc_no,row_ordinal,sheet_ordinal,row_logical_sha256,source_row_chronology_utc,"
            "presence_state,recorded_at_utc) VALUES (?,?,'rfc_enhanced','rfc','valid',?,NULL,1,1,?,100,"
            "'observed_valid_identity',1)",
            (observation_id, run_id, rfc_no, "a" * 64),
        )
        uow.connection.execute(
            "INSERT INTO source_observation_fields(source_observation_field_id,source_observation_id,field_key,field_class,"
            "value_state,value_kind,source_text,normalized_text,integer_value,vocabulary_id,field_logical_sha256) "
            "VALUES (?,?, 'summary','active','usable','text','Identity seed','Identity seed',NULL,NULL,?)",
            (field_id, observation_id, "b" * 64),
        )
    return run_id, observation_id


def test_missing_exact_rfc_builds_owner_bound_create_or_adopt_proposal(initialized_database) -> None:
    factory = _factory(initialized_database)
    rfc_no = "NC20260916000201"
    run_id, observation_id = _seed_run_and_observation(factory, rfc_no)

    with ReadSnapshot(factory) as snapshot:
        result = build_rfc_enhanced_identity_proposals(
            snapshot.connection,
            import_run_id=run_id,
            source_observation_id=observation_id,
        )
        expected_token = RfcImportMutationService.source_identity_base_token(snapshot.connection, rfc_no)

    assert result.scope_status == "unique"
    assert result.rfc_id is None
    assert len(result.proposals) == 1
    proposal = result.proposals[0]
    assert proposal.proposal_kind == "rfc_create_or_adopt"
    assert proposal.target_kind == "rfc"
    assert proposal.target_internal_id is None
    assert proposal.target_business_id == rfc_no
    assert proposal.risk_class == "medium"
    assert proposal.base_state_token_sha256 == expected_token
    assert len(proposal.proposal_fingerprint_sha256) == 64
    assert len(proposal.changes) == 1
    change = proposal.changes[0]
    assert change.field_key == "rfc_no"
    assert change.change_kind == "create"
    assert change.value_kind == "identity"
    assert change.before_text is None
    assert change.after_text == rfc_no
    assert change.source_observation_field_id is None


def test_existing_exact_rfc_suppresses_identity_mutation_proposal(initialized_database) -> None:
    factory = _factory(initialized_database)
    rfc_no = "NC20260916000202"
    rfc_id = new_uuid4()
    with UnitOfWork(factory) as uow:
        uow.connection.execute(
            "INSERT INTO rfcs(rfc_id,rfc_no,customer_org_id,local_archive_state,revision,created_at_utc,updated_at_utc) "
            "VALUES (?,?,NULL,'active',1,1,1)",
            (rfc_id, rfc_no),
        )
    run_id, observation_id = _seed_run_and_observation(factory, rfc_no)

    with ReadSnapshot(factory) as snapshot:
        result = build_rfc_enhanced_identity_proposals(
            snapshot.connection,
            import_run_id=run_id,
            source_observation_id=observation_id,
        )

    assert result.rfc_id == rfc_id
    assert result.proposals == ()
