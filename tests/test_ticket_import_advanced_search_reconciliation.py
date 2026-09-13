from __future__ import annotations

from soma.foundation.identifiers import new_uuid4
from soma.foundation.persistence.uow import ReadSnapshot, UnitOfWork
from soma.ticket_import.reconciliation.advanced_search import (
    build_advanced_search_sr_source_projection_proposals,
)
from soma.tickets.import_mutations import ServiceRequestImportMutationService
from soma.tickets.service_requests import ServiceRequestService


def _factory(initialized_database):
    database_path, factory_for_path = initialized_database
    return factory_for_path(database_path)


def _official_sr(factory, sr_no: str):
    return ServiceRequestService(factory).create_manual_service_request(
        command_id=new_uuid4(),
        official_sr_no=sr_no,
    )


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
    chronology: int = 100,
    fields: tuple[tuple[str, str, str | None, int | None, str | None], ...] = (),
) -> str:
    observation_id = new_uuid4()
    with UnitOfWork(factory) as uow:
        uow.connection.execute(
            "INSERT INTO source_observations(source_observation_id,import_run_id,source_family,entity_kind,identity_state,"
            "canonical_primary_id,canonical_parent_rfc_no,row_ordinal,sheet_ordinal,row_logical_sha256,source_row_chronology_utc,"
            "presence_state,recorded_at_utc) VALUES (?,?,'advanced_search_sr','service_request','valid',?,NULL,?,1,?,?,"
            "'observed_valid_identity',1)",
            (observation_id, run_id, sr_no, row_ordinal, row_hash, chronology),
        )
        for index, (field_key, value_kind, text_value, integer_value, vocabulary_id) in enumerate(fields, start=1):
            field_id = new_uuid4()
            source_text = text_value if text_value is not None else str(integer_value)
            uow.connection.execute(
                "INSERT INTO source_observation_fields(source_observation_field_id,source_observation_id,field_key,field_class,"
                "value_state,value_kind,source_text,normalized_text,integer_value,vocabulary_id,field_logical_sha256) "
                "VALUES (?,?,?,'active','usable',?,?,?,?,?,?)",
                (
                    field_id,
                    observation_id,
                    field_key,
                    value_kind,
                    source_text,
                    text_value,
                    integer_value,
                    vocabulary_id,
                    f"{index:x}" * 64,
                ),
            )
    return observation_id


def test_builder_splits_terminal_entry_from_ordinary_change_and_scopes_tokens(initialized_database) -> None:
    factory = _factory(initialized_database)
    sr = _official_sr(factory, "44000001")
    run_id = _seed_validating_run(factory)
    observation_id = _seed_observation(
        factory,
        run_id=run_id,
        sr_no="44000001",
        row_ordinal=1,
        row_hash="a" * 64,
        fields=(
            ("problem_summary", "text", "Problem Alpha", None, None),
            ("status", "controlled", "Closed", None, "ADVANCED_SEARCH_STATUS_V1"),
        ),
    )

    with ReadSnapshot(factory) as snapshot:
        result = build_advanced_search_sr_source_projection_proposals(
            snapshot.connection,
            import_run_id=run_id,
            source_observation_id=observation_id,
        )
        assert result.scope_status == "unique"
        assert result.service_request_id == sr.service_request_id
        assert len(result.proposals) == 2
        by_risk = {proposal.risk_class: proposal for proposal in result.proposals}
        assert set(by_risk) == {"medium", "high"}
        medium = by_risk["medium"]
        high = by_risk["high"]
        assert medium.proposal_kind == "sr_source_projection"
        assert high.proposal_kind == "sr_source_projection"
        assert [change.field_key for change in medium.changes] == ["problem_summary"]
        assert [change.field_key for change in high.changes] == ["status"]
        assert medium.base_state_token_sha256 == ServiceRequestImportMutationService.source_field_set_base_token(
            snapshot.connection,
            sr.service_request_id,
            ("problem_summary",),
        )
        assert high.base_state_token_sha256 == ServiceRequestImportMutationService.source_field_set_base_token(
            snapshot.connection,
            sr.service_request_id,
            ("status",),
        )
        assert medium.base_state_token_sha256 != high.base_state_token_sha256


def test_builder_blocks_conflicting_duplicate_sr_scope(initialized_database) -> None:
    factory = _factory(initialized_database)
    _official_sr(factory, "44000002")
    run_id = _seed_validating_run(factory)
    first = _seed_observation(
        factory,
        run_id=run_id,
        sr_no="44000002",
        row_ordinal=1,
        row_hash="b" * 64,
        fields=(("problem_summary", "text", "Problem A", None, None),),
    )
    _seed_observation(
        factory,
        run_id=run_id,
        sr_no="44000002",
        row_ordinal=2,
        row_hash="c" * 64,
        fields=(("problem_summary", "text", "Problem B", None, None),),
    )

    with ReadSnapshot(factory) as snapshot:
        result = build_advanced_search_sr_source_projection_proposals(
            snapshot.connection,
            import_run_id=run_id,
            source_observation_id=first,
        )
    assert result.scope_status == "conflict"
    assert result.proposals == ()


def test_builder_emits_no_projection_for_missing_official_sr(initialized_database) -> None:
    factory = _factory(initialized_database)
    run_id = _seed_validating_run(factory)
    observation_id = _seed_observation(
        factory,
        run_id=run_id,
        sr_no="44000003",
        row_ordinal=1,
        row_hash="d" * 64,
        fields=(("problem_summary", "text", "Problem Alpha", None, None),),
    )

    with ReadSnapshot(factory) as snapshot:
        result = build_advanced_search_sr_source_projection_proposals(
            snapshot.connection,
            import_run_id=run_id,
            source_observation_id=observation_id,
        )
    assert result.scope_status == "unique"
    assert result.service_request_id is None
    assert result.proposals == ()


def test_field_set_token_ignores_umbrella_sr_revision(initialized_database) -> None:
    factory = _factory(initialized_database)
    sr = _official_sr(factory, "44000004")
    with ReadSnapshot(factory) as snapshot:
        before = ServiceRequestImportMutationService.source_field_set_base_token(
            snapshot.connection,
            sr.service_request_id,
            ("problem_summary",),
        )
    with UnitOfWork(factory) as uow:
        uow.connection.execute(
            "UPDATE service_requests SET revision=revision+1,updated_at_utc=updated_at_utc+1 WHERE service_request_id=?",
            (sr.service_request_id,),
        )
    with ReadSnapshot(factory) as snapshot:
        after = ServiceRequestImportMutationService.source_field_set_base_token(
            snapshot.connection,
            sr.service_request_id,
            ("problem_summary",),
        )
    assert after == before
