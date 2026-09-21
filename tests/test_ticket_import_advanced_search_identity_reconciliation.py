from __future__ import annotations

from soma.foundation.identifiers import new_uuid4
from soma.foundation.persistence.uow import ReadSnapshot, UnitOfWork
from soma.ticket_import.reconciliation.advanced_search_identity import (
    build_advanced_search_sr_identity_proposals,
)
from soma.tickets.service_request_import_reader import ServiceRequestImportReader
from soma.tickets.service_requests import ServiceRequestService


def _factory(initialized_database):
    database_path, factory_for_path = initialized_database
    return factory_for_path(database_path)


def _seed_validating_run(factory) -> str:
    run_id = new_uuid4()
    with UnitOfWork(factory) as uow:
        uow.connection.execute(
            "INSERT INTO import_runs("
            "import_run_id,source_family,invocation_kind,source_profile_id,header_registry_id,vocabulary_registry_id,parser_profile_id,"
            "candidate_filename,candidate_file_size_bytes,candidate_stable_mtime_ns,candidate_chronology_kind,candidate_chronology_value,"
            "logical_fingerprint_sha256,run_state,started_at_utc,staged_at_utc,observed_row_count,valid_identity_count,"
            "proposal_count,pending_proposal_count,revision"
            ") VALUES (?, 'advanced_search_sr','manual','ADVANCED_SEARCH_SR_V1','ADVANCED_SEARCH_HEADERS_V1',"
            "'ADVANCED_SEARCH_VOCAB_V1','ADVANCED_SEARCH_PARSER_V1','Advanced Search(Service Request)20260908010000.xlsx',"
            "100,1,'embedded_filename_timestamp_utc',200,?,'validating',0,1,0,0,0,0,1)",
            (run_id, "1" * 64),
        )
    return run_id


def _seed_observation(
    factory,
    *,
    run_id: str,
    sr_no: str,
    row_ordinal: int,
    row_hash: str,
    problem_summary: str | None = None,
) -> str:
    observation_id = new_uuid4()
    with UnitOfWork(factory) as uow:
        uow.connection.execute(
            "INSERT INTO source_observations(source_observation_id,import_run_id,source_family,entity_kind,identity_state,"
            "canonical_primary_id,canonical_parent_rfc_no,row_ordinal,sheet_ordinal,row_logical_sha256,source_row_chronology_utc,"
            "presence_state,recorded_at_utc) VALUES (?,?,'advanced_search_sr','service_request','valid',?,NULL,?,1,?,100,"
            "'observed_valid_identity',1)",
            (observation_id, run_id, sr_no, row_ordinal, row_hash),
        )
        if problem_summary is not None:
            uow.connection.execute(
                "INSERT INTO source_observation_fields(source_observation_field_id,source_observation_id,field_key,field_class,"
                "value_state,value_kind,source_text,normalized_text,integer_value,vocabulary_id,field_logical_sha256) "
                "VALUES (?,?,'problem_summary','active','usable','text',?,?,NULL,NULL,?)",
                (new_uuid4(), observation_id, problem_summary, problem_summary, "2" * 64),
            )
    return observation_id


def test_identity_builder_emits_exact_missing_sr_create_proposal(initialized_database) -> None:
    factory = _factory(initialized_database)
    run_id = _seed_validating_run(factory)
    observation_id = _seed_observation(
        factory,
        run_id=run_id,
        sr_no="44000010",
        row_ordinal=1,
        row_hash="a" * 64,
        problem_summary="Problem Alpha",
    )

    with ReadSnapshot(factory) as snapshot:
        first = build_advanced_search_sr_identity_proposals(
            snapshot.connection,
            import_run_id=run_id,
            source_observation_id=observation_id,
        )
        second = build_advanced_search_sr_identity_proposals(
            snapshot.connection,
            import_run_id=run_id,
            source_observation_id=observation_id,
        )
        expected_token = ServiceRequestImportReader.source_identity_base_token(
            snapshot.connection,
            "44000010",
        )

    assert first.scope_status == "unique"
    assert first.canonical_sr_no == "44000010"
    assert first.service_request_id is None
    assert len(first.proposals) == 1
    proposal = first.proposals[0]
    assert proposal.import_run_id == run_id
    assert proposal.evidence_mode == "observed_row"
    assert proposal.source_observation_id == observation_id
    assert proposal.proposal_kind == "sr_create_or_adopt"
    assert proposal.target_kind == "service_request"
    assert proposal.target_internal_id is None
    assert proposal.target_business_id == "44000010"
    assert proposal.risk_class == "medium"
    assert proposal.base_state_token_sha256 == expected_token
    assert len(proposal.changes) == 1
    change = proposal.changes[0]
    assert change.ordinal == 0
    assert change.field_key == "official_sr_no"
    assert change.change_kind == "create"
    assert change.value_kind == "identity"
    assert change.before_text is None
    assert change.after_text == "44000010"
    assert change.before_integer is None
    assert change.after_integer is None
    assert change.source_observation_field_id is None
    assert second.proposals[0].proposal_fingerprint_sha256 == proposal.proposal_fingerprint_sha256
    assert second.proposals[0].base_state_token_sha256 == proposal.base_state_token_sha256


def test_identity_builder_emits_no_create_for_existing_exact_sr(initialized_database) -> None:
    factory = _factory(initialized_database)
    existing = ServiceRequestService(factory).create_manual_service_request(
        command_id=new_uuid4(),
        official_sr_no="44000011",
    )
    run_id = _seed_validating_run(factory)
    observation_id = _seed_observation(
        factory,
        run_id=run_id,
        sr_no="44000011",
        row_ordinal=1,
        row_hash="b" * 64,
    )

    with ReadSnapshot(factory) as snapshot:
        result = build_advanced_search_sr_identity_proposals(
            snapshot.connection,
            import_run_id=run_id,
            source_observation_id=observation_id,
        )
    assert result.scope_status == "unique"
    assert result.service_request_id == existing.service_request_id
    assert result.proposals == ()


def test_identity_builder_blocks_conflicting_duplicate_sr_scope(initialized_database) -> None:
    factory = _factory(initialized_database)
    run_id = _seed_validating_run(factory)
    first_observation = _seed_observation(
        factory,
        run_id=run_id,
        sr_no="44000012",
        row_ordinal=1,
        row_hash="c" * 64,
    )
    _seed_observation(
        factory,
        run_id=run_id,
        sr_no="44000012",
        row_ordinal=2,
        row_hash="d" * 64,
    )

    with ReadSnapshot(factory) as snapshot:
        result = build_advanced_search_sr_identity_proposals(
            snapshot.connection,
            import_run_id=run_id,
            source_observation_id=first_observation,
        )
    assert result.scope_status == "conflict"
    assert result.proposals == ()


def test_identity_base_token_changes_when_official_sr_appears(initialized_database) -> None:
    factory = _factory(initialized_database)
    with ReadSnapshot(factory) as snapshot:
        before = ServiceRequestImportReader.source_identity_base_token(snapshot.connection, "44000013")

    created = ServiceRequestService(factory).create_manual_service_request(
        command_id=new_uuid4(),
        official_sr_no="44000013",
    )

    with ReadSnapshot(factory) as snapshot:
        after = ServiceRequestImportReader.source_identity_base_token(snapshot.connection, "44000013")
        resolved = ServiceRequestImportReader.get_by_official(snapshot.connection, "44000013")

    assert after != before
    assert resolved is not None
    assert resolved["service_request_id"] == created.service_request_id
