from __future__ import annotations

from soma.foundation.identifiers import new_uuid4
from soma.foundation.persistence.uow import ReadSnapshot, UnitOfWork
from soma.ticket_import.reconciliation.rfc_enhanced import (
    build_rfc_enhanced_source_projection_proposals,
)
from soma.tickets.rfc_import_reader import RfcImportReader


def _factory(initialized_database):
    database_path, factory_for_path = initialized_database
    return factory_for_path(database_path)


def _seed_rfc(factory, rfc_no: str) -> str:
    rfc_id = new_uuid4()
    with UnitOfWork(factory) as uow:
        uow.connection.execute(
            "INSERT INTO rfcs(rfc_id,rfc_no,customer_org_id,local_archive_state,revision,created_at_utc,updated_at_utc) "
            "VALUES (?,?,NULL,'active',1,1,1)",
            (rfc_id, rfc_no),
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


def _seed_observation(
    factory,
    *,
    run_id: str,
    rfc_no: str,
    row_hash: str,
    chronology: int | None,
    fields: tuple[tuple[str, str, str | None, int | None, str | None], ...],
) -> str:
    observation_id = new_uuid4()
    with UnitOfWork(factory) as uow:
        uow.connection.execute(
            "INSERT INTO source_observations(source_observation_id,import_run_id,source_family,entity_kind,identity_state,"
            "canonical_primary_id,canonical_parent_rfc_no,row_ordinal,sheet_ordinal,row_logical_sha256,source_row_chronology_utc,"
            "presence_state,recorded_at_utc) VALUES (?,?,'rfc_enhanced','rfc','valid',?,NULL,1,1,?,?,"
            "'observed_valid_identity',1)",
            (observation_id, run_id, rfc_no, row_hash, chronology),
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


def test_missing_rfc_remains_fail_closed_for_identity_owner(initialized_database) -> None:
    factory = _factory(initialized_database)
    run_id = _seed_validating_run(factory)
    observation_id = _seed_observation(
        factory,
        run_id=run_id,
        rfc_no="NC20260916000001",
        row_hash="a" * 64,
        chronology=100,
        fields=(("summary", "text", "Missing RFC", None, None),),
    )

    with ReadSnapshot(factory) as snapshot:
        result = build_rfc_enhanced_source_projection_proposals(
            snapshot.connection,
            import_run_id=run_id,
            source_observation_id=observation_id,
        )

    assert result.rfc_id is None
    assert result.identity_owner_required is True
    assert result.proposals == ()


def test_existing_rfc_builds_one_high_risk_projection_for_terminal_row(initialized_database) -> None:
    factory = _factory(initialized_database)
    rfc_no = "NC20260916000002"
    rfc_id = _seed_rfc(factory, rfc_no)
    run_id = _seed_validating_run(factory)
    observation_id = _seed_observation(
        factory,
        run_id=run_id,
        rfc_no=rfc_no,
        row_hash="b" * 64,
        chronology=200,
        fields=(
            ("summary", "text", "Terminal maintenance", None, None),
            ("status", "controlled", "Closed", None, "RFC_STATUS_V1"),
            ("last_update", "instant", None, 200, None),
        ),
    )

    with ReadSnapshot(factory) as snapshot:
        result = build_rfc_enhanced_source_projection_proposals(
            snapshot.connection,
            import_run_id=run_id,
            source_observation_id=observation_id,
        )
        expected_token = RfcImportReader.source_acceptance_base_token(snapshot.connection, rfc_id)

    assert result.identity_owner_required is False
    assert result.rfc_id == rfc_id
    assert len(result.proposals) == 1
    proposal = result.proposals[0]
    assert proposal.proposal_kind == "rfc_source_projection"
    assert proposal.target_kind == "rfc"
    assert proposal.target_internal_id == rfc_id
    assert proposal.target_business_id == rfc_no
    assert proposal.risk_class == "high"
    assert proposal.base_state_token_sha256 == expected_token
    assert [change.field_key for change in proposal.changes] == ["last_update", "status", "summary"]
    assert result.chronology_blocked_fields == ()
    assert result.chronology_review_fields == ()


def test_older_comparable_rfc_row_does_not_regress_current_projection(initialized_database) -> None:
    factory = _factory(initialized_database)
    rfc_no = "NC20260916000003"
    rfc_id = _seed_rfc(factory, rfc_no)
    with UnitOfWork(factory) as uow:
        uow.connection.execute(
            "INSERT INTO rfc_current_source_projection("
            "rfc_id,summary_text,summary_evidence_id,last_update_utc,last_update_evidence_id,revision"
            ") VALUES (?,?,?,?,?,1)",
            (rfc_id, "Current", "evidence-summary", 300, "evidence-last-update"),
        )
    run_id = _seed_validating_run(factory)
    observation_id = _seed_observation(
        factory,
        run_id=run_id,
        rfc_no=rfc_no,
        row_hash="c" * 64,
        chronology=200,
        fields=(
            ("summary", "text", "Older", None, None),
            ("last_update", "instant", None, 200, None),
        ),
    )

    with ReadSnapshot(factory) as snapshot:
        result = build_rfc_enhanced_source_projection_proposals(
            snapshot.connection,
            import_run_id=run_id,
            source_observation_id=observation_id,
        )

    assert result.proposals == ()
    assert result.chronology_blocked_fields == ("last_update", "summary")
    assert result.chronology_review_fields == ()


def test_missing_source_chronology_keeps_changed_field_reviewable(initialized_database) -> None:
    factory = _factory(initialized_database)
    rfc_no = "NC20260916000004"
    rfc_id = _seed_rfc(factory, rfc_no)
    with UnitOfWork(factory) as uow:
        uow.connection.execute(
            "INSERT INTO rfc_current_source_projection(rfc_id,summary_text,summary_evidence_id,revision) VALUES (?,?,?,1)",
            (rfc_id, "Current", "evidence-summary"),
        )
    run_id = _seed_validating_run(factory)
    observation_id = _seed_observation(
        factory,
        run_id=run_id,
        rfc_no=rfc_no,
        row_hash="d" * 64,
        chronology=None,
        fields=(("summary", "text", "Needs review", None, None),),
    )

    with ReadSnapshot(factory) as snapshot:
        result = build_rfc_enhanced_source_projection_proposals(
            snapshot.connection,
            import_run_id=run_id,
            source_observation_id=observation_id,
        )

    assert len(result.proposals) == 1
    assert result.proposals[0].risk_class == "medium"
    assert result.chronology_blocked_fields == ()
    assert result.chronology_review_fields == ("summary",)
