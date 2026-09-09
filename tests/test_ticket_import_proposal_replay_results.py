from __future__ import annotations

import json

from soma.foundation.identifiers import new_uuid4
from soma.foundation.persistence.uow import UnitOfWork
from soma.ticket_import.commands.decide_proposal import ProposalDecisionService
from soma.ticket_import.repositories.proposals import ProposalRepository


def _factory(initialized_database):
    database_path, factory_for_path = initialized_database
    return factory_for_path(database_path)


def _seed_pending_proposal(factory) -> tuple[str, str]:
    run_id = new_uuid4()
    observation_id = new_uuid4()
    proposal_id = new_uuid4()
    proposal_fingerprint = "5" * 64
    with UnitOfWork(factory) as uow:
        uow.connection.execute(
            "INSERT INTO import_runs("
            "import_run_id,source_family,invocation_kind,source_profile_id,header_registry_id,vocabulary_registry_id,parser_profile_id,"
            "candidate_filename,candidate_file_size_bytes,candidate_stable_mtime_ns,candidate_chronology_kind,candidate_chronology_value,"
            "logical_fingerprint_sha256,run_state,started_at_utc,staged_at_utc,proposal_count,pending_proposal_count,revision"
            ") VALUES (?, 'advanced_search_sr','manual','ADVANCED_SEARCH_SR_V1','ADVANCED_SEARCH_HEADERS_V1','ADVANCED_SEARCH_VOCAB_V1',"
            "'ADVANCED_SEARCH_PARSER_V1','Advanced Search(Service Request)20260908010000.xlsx',100,1,"
            "'embedded_filename_timestamp_utc',200,?,'waiting_review',0,1,1,1,1)",
            (run_id, "1" * 64),
        )
        uow.connection.execute(
            "INSERT INTO source_observations(source_observation_id,import_run_id,source_family,entity_kind,identity_state,"
            "canonical_primary_id,canonical_parent_rfc_no,row_ordinal,sheet_ordinal,row_logical_sha256,source_row_chronology_utc,"
            "presence_state,recorded_at_utc) VALUES (?,?,'advanced_search_sr','service_request','valid','12345678',NULL,1,1,?,100,"
            "'observed_valid_identity',1)",
            (observation_id, run_id, "2" * 64),
        )
        uow.connection.execute(
            "INSERT INTO reconciliation_proposals(reconciliation_proposal_id,import_run_id,evidence_mode,source_observation_id,"
            "prior_source_observation_id,proposal_kind,target_kind,target_internal_id,target_business_id,risk_class,"
            "base_state_token_sha256,proposal_fingerprint_sha256,proposal_state,created_at_utc,revision,decided_at_utc) "
            "VALUES (?,?,'observed_row',?,NULL,'sr_source_projection','service_request',NULL,'12345678','medium',?,?,'pending',1,1,NULL)",
            (proposal_id, run_id, observation_id, "4" * 64, proposal_fingerprint),
        )
    return proposal_id, proposal_fingerprint


def test_reject_replay_uses_exact_committed_result_without_owner_reads(initialized_database, monkeypatch) -> None:
    factory = _factory(initialized_database)
    proposal_id, proposal_fingerprint = _seed_pending_proposal(factory)
    service = ProposalDecisionService(factory)
    command_id = new_uuid4()

    first = service.reject(
        command_id=command_id,
        proposal_id=proposal_id,
        proposal_revision=1,
        proposal_fingerprint=proposal_fingerprint,
        reason_category="exact_replay_test",
    )
    assert first.replayed is False
    assert first.decision == "rejected"
    assert first.revision == 2
    assert first.owner_result_refs == ()

    def forbidden_owner_read(*_args, **_kwargs):
        raise AssertionError("proposal owner state must not be read during committed replay")

    monkeypatch.setattr(ProposalRepository, "get", staticmethod(forbidden_owner_read))
    replay = service.reject(
        command_id=command_id,
        proposal_id=proposal_id,
        proposal_revision=1,
        proposal_fingerprint=proposal_fingerprint,
        reason_category="exact_replay_test",
    )
    assert replay.replayed is True
    assert replay.decision == "rejected"
    assert replay.revision == 2
    assert replay.owner_result_refs == ()

    connection = factory.open_authoritative(read_only=True, require_wal=True)
    try:
        stored = connection.execute(
            "SELECT response_schema,response_version,response_json FROM command_receipt_results WHERE command_id=?",
            (command_id,),
        ).fetchone()
        assert tuple(stored[:2]) == ("ProposalDecisionResultV1", 1)
        assert json.loads(str(stored[2])) == {
            "decision": "rejected",
            "owner_result_refs": [],
            "proposal_id": proposal_id,
            "revision": 2,
        }
        assert connection.execute(
            "SELECT COUNT(*) FROM proposal_dispositions WHERE reconciliation_proposal_id=?",
            (proposal_id,),
        ).fetchone()[0] == 1
        assert connection.execute(
            "SELECT COUNT(*) FROM audit_events WHERE command_id=?",
            (command_id,),
        ).fetchone()[0] == 1
    finally:
        connection.close()
