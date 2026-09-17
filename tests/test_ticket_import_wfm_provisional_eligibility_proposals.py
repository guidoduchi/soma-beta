from __future__ import annotations

from soma.foundation.identifiers import new_uuid4
from soma.foundation.persistence.uow import ReadSnapshot, UnitOfWork
from soma.ticket_import.profiles import require_profile_versions
from soma.ticket_import.reconciliation.wfm_provisional_eligibility import build_wfm_service_provider_proposals
from soma.tickets.rfcs import RfcService


def _factory(initialized_database):
    database_path, factory_for_path = initialized_database
    return factory_for_path(database_path)


def _seed_observation(factory, *, task_no: str, rfc_no: str, fields: tuple[dict[str, object], ...]) -> tuple[str, str]:
    versions = require_profile_versions("wfm_service_provider")
    run_id = new_uuid4()
    observation_id = new_uuid4()
    with UnitOfWork(factory) as uow:
        uow.connection.execute(
            "INSERT INTO import_runs("
            "import_run_id,source_family,invocation_kind,source_profile_id,header_registry_id,vocabulary_registry_id,parser_profile_id,"
            "candidate_filename,candidate_file_size_bytes,candidate_stable_mtime_ns,candidate_chronology_kind,candidate_chronology_value,"
            "logical_fingerprint_sha256,run_state,started_at_utc,staged_at_utc,observed_row_count,valid_identity_count,"
            "proposal_count,pending_proposal_count,revision"
            ") VALUES (?,'wfm_service_provider','manual',?,?,?,?,"
            "'operator-wfm.xlsx',100,1,'embedded_filename_timestamp_utc',200,?,'validating',0,1,1,1,0,0,1)",
            (
                run_id,
                versions.source_profile_id,
                versions.header_registry_id,
                versions.vocabulary_registry_id,
                versions.parser_profile_id,
                "1" * 64,
            ),
        )
        uow.connection.execute(
            "INSERT INTO source_observations(source_observation_id,import_run_id,source_family,entity_kind,identity_state,"
            "canonical_primary_id,canonical_parent_rfc_no,row_ordinal,sheet_ordinal,row_logical_sha256,source_row_chronology_utc,"
            "presence_state,recorded_at_utc) VALUES (?,?,'wfm_service_provider','wfm','valid',?,?,1,1,?,200,"
            "'observed_valid_identity',1)",
            (observation_id, run_id, task_no, rfc_no, "2" * 64),
        )
        for ordinal, field in enumerate(fields):
            uow.connection.execute(
                "INSERT INTO source_observation_fields(source_observation_field_id,source_observation_id,field_key,field_class,"
                "value_state,value_kind,source_text,normalized_text,integer_value,vocabulary_id,field_logical_sha256) "
                "VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                (
                    new_uuid4(),
                    observation_id,
                    field["field_key"],
                    "active",
                    field["value_state"],
                    field["value_kind"],
                    field.get("source_text"),
                    field.get("normalized_text"),
                    None,
                    field.get("vocabulary_id"),
                    f"{ordinal + 3:064x}",
                ),
            )
    return run_id, observation_id


def _active_task_status() -> dict[str, object]:
    return {
        "field_key": "task_status",
        "value_state": "unknown",
        "value_kind": "controlled",
        "source_text": "Implementation",
        "vocabulary_id": "WFM_TASK_STATUS_V1",
    }


def _complete_task_status() -> dict[str, object]:
    return {
        "field_key": "task_status",
        "value_state": "usable",
        "value_kind": "controlled",
        "source_text": "Complete",
        "normalized_text": "Complete",
        "vocabulary_id": "WFM_TASK_STATUS_V1",
    }


def _implement_rfc_status() -> dict[str, object]:
    return {
        "field_key": "rfc_status",
        "value_state": "usable",
        "value_kind": "controlled",
        "source_text": "Implement",
        "normalized_text": "Implement",
        "vocabulary_id": "RFC_STATUS_V1",
    }


def test_missing_parent_emits_separate_provisional_identity_and_eligibility_reviews(initialized_database) -> None:
    factory = _factory(initialized_database)
    task_no = "TK00000000000711"
    rfc_no = "NC00000000000711"
    run_id, observation_id = _seed_observation(
        factory,
        task_no=task_no,
        rfc_no=rfc_no,
        fields=(_active_task_status(), _implement_rfc_status()),
    )
    with ReadSnapshot(factory) as snapshot:
        result = build_wfm_service_provider_proposals(
            snapshot.connection,
            import_run_id=run_id,
            source_observation_id=observation_id,
        )

    assert result.resolution_state == "parent_rfc_and_eligibility_review"
    assert [proposal.proposal_kind for proposal in result.proposals] == [
        "wfm_provisional_rfc",
        "wfm_provisional_eligibility",
    ]
    eligibility = result.proposals[1]
    assert eligibility.target_kind == "rfc"
    assert eligibility.target_internal_id is None
    assert eligibility.target_business_id == rfc_no
    assert eligibility.risk_class == "high"
    assert len(eligibility.changes) == 1
    change = eligibility.changes[0]
    assert (change.field_key, change.change_kind, change.value_kind, change.before_text, change.after_text) == (
        "status",
        "set",
        "controlled",
        None,
        "Implement",
    )
    assert change.source_observation_field_id is not None


def test_complete_wfm_never_promotes_missing_parent_rfc(initialized_database) -> None:
    factory = _factory(initialized_database)
    task_no = "TK00000000000712"
    rfc_no = "NC00000000000712"
    run_id, observation_id = _seed_observation(
        factory,
        task_no=task_no,
        rfc_no=rfc_no,
        fields=(_complete_task_status(), _implement_rfc_status()),
    )
    with ReadSnapshot(factory) as snapshot:
        result = build_wfm_service_provider_proposals(
            snapshot.connection,
            import_run_id=run_id,
            source_observation_id=observation_id,
        )

    assert [proposal.proposal_kind for proposal in result.proposals] == ["wfm_provisional_rfc"]


def test_accepted_enhanced_status_blocks_provisional_eligibility_proposal(initialized_database) -> None:
    factory = _factory(initialized_database)
    task_no = "TK00000000000713"
    rfc_no = "NC00000000000713"
    rfc = RfcService(factory).create_or_adopt_identity(
        command_id=new_uuid4(),
        rfc_no=rfc_no,
        creation_context="provisional",
    )
    with UnitOfWork(factory) as uow:
        uow.connection.execute(
            "INSERT INTO rfc_current_source_projection("
            "rfc_id,status_text,status_class,status_authority,status_evidence_id,terminal_epoch_id,revision"
            ") VALUES (?,'Implement','implement_eligible','enhanced_rfc',?,NULL,1)",
            (rfc.rfc_id, new_uuid4()),
        )
    run_id, observation_id = _seed_observation(
        factory,
        task_no=task_no,
        rfc_no=rfc_no,
        fields=(_active_task_status(), _implement_rfc_status()),
    )
    with ReadSnapshot(factory) as snapshot:
        result = build_wfm_service_provider_proposals(
            snapshot.connection,
            import_run_id=run_id,
            source_observation_id=observation_id,
        )

    assert result.resolution_state == "create_review"
    assert [proposal.proposal_kind for proposal in result.proposals] == ["wfm_create_or_adopt"]
