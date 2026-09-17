from __future__ import annotations

from soma.foundation.identifiers import new_uuid4
from soma.foundation.persistence.uow import ReadSnapshot, UnitOfWork
from soma.ticket_import.reconciliation.rfc_enhanced_sr_link import (
    build_rfc_enhanced_sr_link_candidate_proposals,
    extract_sr_candidates,
)
from soma.tickets.service_requests import ServiceRequestService


def _factory(initialized_database):
    database_path, factory_for_path = initialized_database
    return factory_for_path(database_path)


def _official_sr(factory, sr_no: str):
    return ServiceRequestService(factory).create_manual_service_request(
        command_id=new_uuid4(),
        official_sr_no=sr_no,
    )


def _seed_rfc(factory, rfc_no: str, *, archive_state: str = "active") -> str:
    rfc_id = new_uuid4()
    with UnitOfWork(factory) as uow:
        uow.connection.execute(
            "INSERT INTO rfcs(rfc_id,rfc_no,customer_org_id,local_archive_state,revision,created_at_utc,updated_at_utc) "
            "VALUES (?,?,NULL,?,1,1,1)",
            (rfc_id, rfc_no, archive_state),
        )
    return rfc_id


def _seed_validating_run(factory) -> str:
    run_id = new_uuid4()
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
    return run_id


def _seed_summary(factory, *, run_id: str, rfc_no: str, summary: str) -> tuple[str, str]:
    observation_id = new_uuid4()
    field_id = new_uuid4()
    with UnitOfWork(factory) as uow:
        uow.connection.execute(
            "INSERT INTO source_observations(source_observation_id,import_run_id,source_family,entity_kind,identity_state,"
            "canonical_primary_id,canonical_parent_rfc_no,row_ordinal,sheet_ordinal,row_logical_sha256,source_row_chronology_utc,"
            "presence_state,recorded_at_utc) VALUES (?,?,'rfc_enhanced','rfc','valid',?,NULL,1,1,?,200,"
            "'observed_valid_identity',1)",
            (observation_id, run_id, rfc_no, "a" * 64),
        )
        uow.connection.execute(
            "INSERT INTO source_observation_fields(source_observation_field_id,source_observation_id,field_key,field_class,"
            "value_state,value_kind,source_text,normalized_text,integer_value,vocabulary_id,field_logical_sha256) "
            "VALUES (?,?,'summary','active','usable','text',?,?,NULL,NULL,?)",
            (field_id, observation_id, summary, summary, "b" * 64),
        )
    return observation_id, field_id


def _build(factory, *, run_id: str, observation_id: str):
    with ReadSnapshot(factory) as snapshot:
        return build_rfc_enhanced_sr_link_candidate_proposals(
            snapshot.connection,
            import_run_id=run_id,
            source_observation_id=observation_id,
        )


def test_candidate_parser_strong_weak_date_and_substring_rules() -> None:
    candidates = extract_sr_candidates(
        "SR12345678 and TT 87654321 plus 12345678 again; date 20260917; X55555555Y ignored; 55555555 valid"
    )
    assert [(item.official_sr_no, item.strength, item.mention_count) for item in candidates] == [
        ("12345678", "strong", 2),
        ("55555555", "weak", 1),
        ("87654321", "strong", 1),
    ]


def test_builder_emits_only_existing_exact_sr_matches(initialized_database) -> None:
    factory = _factory(initialized_database)
    sr = _official_sr(factory, "12345678")
    rfc_no = "NC20260917000011"
    rfc_id = _seed_rfc(factory, rfc_no)
    run_id = _seed_validating_run(factory)
    observation_id, summary_field_id = _seed_summary(
        factory,
        run_id=run_id,
        rfc_no=rfc_no,
        summary="Impact on SR12345678; possible SR99999999",
    )

    result = _build(factory, run_id=run_id, observation_id=observation_id)
    assert result.resolution_state == "existing_matches"
    assert [item.official_sr_no for item in result.candidates] == ["12345678", "99999999"]
    assert len(result.proposals) == 1
    proposal = result.proposals[0]
    assert proposal.proposal_kind == "sr_rfc_link_candidate"
    assert proposal.target_kind == "sr_rfc_relationship"
    assert proposal.target_internal_id == rfc_id
    assert proposal.target_business_id == rfc_no
    assert proposal.risk_class == "medium"
    assert len(proposal.changes) == 1
    change = proposal.changes[0]
    assert change.field_key == "service_request_id"
    assert change.change_kind == "candidate"
    assert change.value_kind == "identity"
    assert change.before_text is None
    assert change.after_text == sr.service_request_id
    assert change.source_observation_field_id == summary_field_id


def test_archived_governing_rfc_elevates_link_candidate_to_high_risk(initialized_database) -> None:
    factory = _factory(initialized_database)
    _official_sr(factory, "23456789")
    rfc_no = "NC20260917000012"
    _seed_rfc(factory, rfc_no, archive_state="archived")
    run_id = _seed_validating_run(factory)
    observation_id, _ = _seed_summary(
        factory,
        run_id=run_id,
        rfc_no=rfc_no,
        summary="TT 23456789",
    )

    result = _build(factory, run_id=run_id, observation_id=observation_id)
    assert len(result.proposals) == 1
    assert result.proposals[0].risk_class == "high"


def test_existing_active_link_is_not_reproposed(initialized_database) -> None:
    factory = _factory(initialized_database)
    sr = _official_sr(factory, "34567890")
    rfc_no = "NC20260917000013"
    rfc_id = _seed_rfc(factory, rfc_no)
    with UnitOfWork(factory) as uow:
        uow.connection.execute(
            "INSERT INTO sr_rfc_links(sr_rfc_link_id,service_request_id,rfc_id,link_state,opened_at_utc,opened_command_id) "
            "VALUES (?, ?, ?, 'active', 1, ?)",
            (new_uuid4(), sr.service_request_id, rfc_id, new_uuid4()),
        )
    run_id = _seed_validating_run(factory)
    observation_id, _ = _seed_summary(
        factory,
        run_id=run_id,
        rfc_no=rfc_no,
        summary="SR34567890",
    )

    result = _build(factory, run_id=run_id, observation_id=observation_id)
    assert result.resolution_state == "no_existing_unlinked_matches"
    assert result.proposals == ()
