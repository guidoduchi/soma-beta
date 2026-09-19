from __future__ import annotations

from soma.foundation.identifiers import new_uuid4
from soma.foundation.persistence.uow import ReadSnapshot, UnitOfWork
from soma.ticket_import.commands.decide_proposal import ProposalDecisionService
from soma.ticket_import.profiles import require_profile_versions
from soma.tickets.rfc_import_mutations import RfcImportMutationService
from soma.tickets.rfc_import_reader import RfcImportReader
from soma.tickets.rfc_wfm_provisional import RfcWfmProvisionalEligibilityService


def _factory(initialized_database):
    database_path, factory_for_path = initialized_database
    return factory_for_path(database_path)


def _seed_two_review_run(factory, *, task_no: str, rfc_no: str) -> tuple[str, str, str]:
    versions = require_profile_versions("wfm_service_provider")
    run_id = new_uuid4()
    observation_id = new_uuid4()
    task_status_id = new_uuid4()
    rfc_status_id = new_uuid4()
    with UnitOfWork(factory) as uow:
        uow.connection.execute(
            "INSERT INTO import_runs("
            "import_run_id,source_family,invocation_kind,source_profile_id,header_registry_id,vocabulary_registry_id,parser_profile_id,"
            "candidate_filename,candidate_file_size_bytes,candidate_stable_mtime_ns,candidate_chronology_kind,candidate_chronology_value,"
            "logical_fingerprint_sha256,run_state,started_at_utc,staged_at_utc,observed_row_count,valid_identity_count,"
            "proposal_count,pending_proposal_count,revision"
            ") VALUES (?,'wfm_service_provider','manual',?,?,?,?,"
            "'operator-wfm.xlsx',100,1,'embedded_filename_timestamp_utc',200,?,'waiting_review',0,1,1,1,2,2,1)",
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
        uow.connection.execute(
            "INSERT INTO source_observation_fields(source_observation_field_id,source_observation_id,field_key,field_class,"
            "value_state,value_kind,source_text,normalized_text,integer_value,vocabulary_id,field_logical_sha256) "
            "VALUES (?,?,'task_status','active','unknown','controlled','Implementation',NULL,NULL,'WFM_TASK_STATUS_V1',?)",
            (task_status_id, observation_id, "3" * 64),
        )
        uow.connection.execute(
            "INSERT INTO source_observation_fields(source_observation_field_id,source_observation_id,field_key,field_class,"
            "value_state,value_kind,source_text,normalized_text,integer_value,vocabulary_id,field_logical_sha256) "
            "VALUES (?,?,'rfc_status','active','usable','controlled','Implement','Implement',NULL,'RFC_STATUS_V1',?)",
            (rfc_status_id, observation_id, "4" * 64),
        )
    return run_id, observation_id, rfc_status_id


def _insert_provisional_rfc_proposal(
    factory,
    *,
    run_id: str,
    observation_id: str,
    rfc_no: str,
    base_token: str,
    fingerprint: str,
) -> str:
    proposal_id = new_uuid4()
    with UnitOfWork(factory) as uow:
        uow.connection.execute(
            "INSERT INTO reconciliation_proposals(reconciliation_proposal_id,import_run_id,evidence_mode,source_observation_id,"
            "prior_source_observation_id,proposal_kind,target_kind,target_internal_id,target_business_id,risk_class,"
            "base_state_token_sha256,proposal_fingerprint_sha256,proposal_state,created_at_utc,revision,decided_at_utc) "
            "VALUES (?,?,'observed_row',?,NULL,'wfm_provisional_rfc','rfc',NULL,?,'high',?,?,'pending',1,1,NULL)",
            (proposal_id, run_id, observation_id, rfc_no, base_token, fingerprint),
        )
        uow.connection.execute(
            "INSERT INTO reconciliation_proposal_changes(reconciliation_proposal_id,ordinal,field_key,change_kind,value_kind,"
            "before_text,after_text,before_integer,after_integer,source_observation_field_id) "
            "VALUES (?,0,'rfc_no','create','identity',NULL,?,NULL,NULL,NULL)",
            (proposal_id, rfc_no),
        )
    return proposal_id


def _insert_provisional_eligibility_proposal(
    factory,
    *,
    run_id: str,
    observation_id: str,
    rfc_no: str,
    rfc_status_field_id: str,
    base_token: str,
    fingerprint: str,
) -> str:
    proposal_id = new_uuid4()
    with UnitOfWork(factory) as uow:
        uow.connection.execute(
            "INSERT INTO reconciliation_proposals(reconciliation_proposal_id,import_run_id,evidence_mode,source_observation_id,"
            "prior_source_observation_id,proposal_kind,target_kind,target_internal_id,target_business_id,risk_class,"
            "base_state_token_sha256,proposal_fingerprint_sha256,proposal_state,created_at_utc,revision,decided_at_utc) "
            "VALUES (?,?,'observed_row',?,NULL,'wfm_provisional_eligibility','rfc',NULL,?,'high',?,?,'pending',1,1,NULL)",
            (proposal_id, run_id, observation_id, rfc_no, base_token, fingerprint),
        )
        uow.connection.execute(
            "INSERT INTO reconciliation_proposal_changes(reconciliation_proposal_id,ordinal,field_key,change_kind,value_kind,"
            "before_text,after_text,before_integer,after_integer,source_observation_field_id) "
            "VALUES (?,0,'status','set','controlled',NULL,'Implement',NULL,NULL,?)",
            (proposal_id, rfc_status_field_id),
        )
    return proposal_id


def test_accept_provisional_rfc_then_original_eligibility_review_and_replay(initialized_database) -> None:
    factory = _factory(initialized_database)
    task_no = "TK00000000000721"
    rfc_no = "NC00000000000721"
    run_id, observation_id, rfc_status_field_id = _seed_two_review_run(
        factory,
        task_no=task_no,
        rfc_no=rfc_no,
    )
    with ReadSnapshot(factory) as snapshot:
        identity_base = RfcImportMutationService.source_identity_base_token(snapshot.connection, rfc_no)
        eligibility_base = RfcWfmProvisionalEligibilityService.base_state_token(snapshot.connection, rfc_no)

    rfc_fingerprint = "5" * 64
    eligibility_fingerprint = "6" * 64
    rfc_proposal_id = _insert_provisional_rfc_proposal(
        factory,
        run_id=run_id,
        observation_id=observation_id,
        rfc_no=rfc_no,
        base_token=identity_base,
        fingerprint=rfc_fingerprint,
    )
    eligibility_proposal_id = _insert_provisional_eligibility_proposal(
        factory,
        run_id=run_id,
        observation_id=observation_id,
        rfc_no=rfc_no,
        rfc_status_field_id=rfc_status_field_id,
        base_token=eligibility_base,
        fingerprint=eligibility_fingerprint,
    )

    service = ProposalDecisionService(factory)
    identity_result = service.accept(
        command_id=new_uuid4(),
        proposal_id=rfc_proposal_id,
        proposal_revision=1,
        proposal_fingerprint=rfc_fingerprint,
        base_state_token=identity_base,
    )
    assert identity_result.decision == "accepted"
    assert identity_result.replayed is False

    with ReadSnapshot(factory) as snapshot:
        identity = RfcImportReader().get_by_number(snapshot.connection, rfc_no)
        assert identity is not None
        rfc_id = identity["rfc_id"]
        assert RfcWfmProvisionalEligibilityService.base_state_token(snapshot.connection, rfc_no) == eligibility_base

    eligibility_command_id = new_uuid4()
    first = service.accept(
        command_id=eligibility_command_id,
        proposal_id=eligibility_proposal_id,
        proposal_revision=1,
        proposal_fingerprint=eligibility_fingerprint,
        base_state_token=eligibility_base,
    )
    assert first.decision == "accepted"
    assert first.replayed is False
    assert ("rfc_source_projection", rfc_id) in first.owner_result_refs

    replay = service.accept(
        command_id=eligibility_command_id,
        proposal_id=eligibility_proposal_id,
        proposal_revision=1,
        proposal_fingerprint=eligibility_fingerprint,
        base_state_token=eligibility_base,
    )
    assert replay.replayed is True
    assert replay.owner_result_refs == first.owner_result_refs

    with ReadSnapshot(factory) as snapshot:
        projection = RfcImportReader().current_source_projection(snapshot.connection, rfc_id)
        assert projection is not None
        assert projection["status_text"] == "Implement"
        assert projection["status_class"] == "implement_eligible"
        assert projection["status_authority"] == "wfm_provisional"
        assert projection["status_evidence_id"] == rfc_status_field_id
        run = snapshot.connection.execute(
            "SELECT pending_proposal_count,accepted_proposal_count,revision FROM import_runs WHERE import_run_id=?",
            (run_id,),
        ).fetchone()
        assert tuple(run) == (0, 2, 3)
        states = snapshot.connection.execute(
            "SELECT proposal_kind,proposal_state,revision FROM reconciliation_proposals WHERE import_run_id=? ORDER BY proposal_kind",
            (run_id,),
        ).fetchall()
        assert [(str(row[0]), str(row[1]), int(row[2])) for row in states] == [
            ("wfm_provisional_eligibility", "accepted", 2),
            ("wfm_provisional_rfc", "accepted", 2),
        ]
