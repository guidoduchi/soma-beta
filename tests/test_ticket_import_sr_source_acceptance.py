from __future__ import annotations

import pytest

from soma.foundation.errors import SomaError
from soma.foundation.identifiers import new_uuid4
from soma.foundation.persistence.uow import ReadSnapshot, UnitOfWork
from soma.ticket_import.commands.decide_proposal import ProposalDecisionService
from soma.tickets.import_mutations import (
    ServiceRequestImportMutationService,
    ServiceRequestSourceProjectionMutation,
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


def _base_token(factory, service_request_id: str) -> str:
    with ReadSnapshot(factory) as snapshot:
        return ServiceRequestImportMutationService.source_acceptance_base_token(
            snapshot.connection,
            service_request_id,
        )


def _seed_source_projection_proposal(
    factory,
    *,
    target_service_request_id: str,
    target_sr_no: str,
    source_sr_no: str | None = None,
    field_key: str = "problem_summary",
    field_value: str = "Problem Alpha",
    chronology: int = 100,
    base_state_token: str | None = None,
):
    run_id = new_uuid4()
    observation_id = new_uuid4()
    field_id = new_uuid4()
    proposal_id = new_uuid4()
    fingerprint = "7" * 64
    token = _base_token(factory, target_service_request_id) if base_state_token is None else base_state_token
    canonical_sr_no = target_sr_no if source_sr_no is None else source_sr_no
    with UnitOfWork(factory) as uow:
        uow.connection.execute(
            "INSERT INTO import_runs("
            "import_run_id,source_family,invocation_kind,source_profile_id,header_registry_id,vocabulary_registry_id,parser_profile_id,"
            "candidate_filename,candidate_file_size_bytes,candidate_stable_mtime_ns,candidate_chronology_kind,candidate_chronology_value,"
            "logical_fingerprint_sha256,run_state,started_at_utc,staged_at_utc,observed_row_count,valid_identity_count,"
            "proposal_count,pending_proposal_count,revision"
            ") VALUES (?, 'advanced_search_sr','manual','ADVANCED_SEARCH_SR_V1','ADVANCED_SEARCH_HEADERS_V1',"
            "'ADVANCED_SEARCH_VOCAB_V1','ADVANCED_SEARCH_PARSER_V1','Advanced Search(Service Request)20260908010000.xlsx',"
            "100,1,'embedded_filename_timestamp_utc',200,?,'waiting_review',0,1,1,1,1,1,1)",
            (run_id, "1" * 64),
        )
        uow.connection.execute(
            "INSERT INTO source_observations(source_observation_id,import_run_id,source_family,entity_kind,identity_state,"
            "canonical_primary_id,canonical_parent_rfc_no,row_ordinal,sheet_ordinal,row_logical_sha256,source_row_chronology_utc,"
            "presence_state,recorded_at_utc) VALUES (?,?,'advanced_search_sr','service_request','valid',?,NULL,1,1,?,?,"
            "'observed_valid_identity',1)",
            (observation_id, run_id, canonical_sr_no, "2" * 64, chronology),
        )
        uow.connection.execute(
            "INSERT INTO source_observation_fields(source_observation_field_id,source_observation_id,field_key,field_class,"
            "value_state,value_kind,source_text,normalized_text,integer_value,vocabulary_id,field_logical_sha256) "
            "VALUES (?,?,?,'active','usable','text',?,?,NULL,NULL,?)",
            (field_id, observation_id, field_key, field_value, field_value, "3" * 64),
        )
        uow.connection.execute(
            "INSERT INTO reconciliation_proposals(reconciliation_proposal_id,import_run_id,evidence_mode,source_observation_id,"
            "prior_source_observation_id,proposal_kind,target_kind,target_internal_id,target_business_id,risk_class,"
            "base_state_token_sha256,proposal_fingerprint_sha256,proposal_state,created_at_utc,revision,decided_at_utc) "
            "VALUES (?,?,'observed_row',?,NULL,'sr_source_projection','service_request',?,?,'medium',?,?,'pending',1,1,NULL)",
            (proposal_id, run_id, observation_id, target_service_request_id, target_sr_no, token, fingerprint),
        )
        uow.connection.execute(
            "INSERT INTO reconciliation_proposal_changes(reconciliation_proposal_id,ordinal,field_key,change_kind,value_kind,"
            "before_text,after_text,before_integer,after_integer,source_observation_field_id) "
            "VALUES (?,0,?,'set','text',NULL,?,NULL,NULL,?)",
            (proposal_id, field_key, field_value, field_id),
        )
    return {
        "run_id": run_id,
        "observation_id": observation_id,
        "field_id": field_id,
        "proposal_id": proposal_id,
        "fingerprint": fingerprint,
        "base_token": token,
    }


def test_accept_sr_source_projection_is_one_uow_and_replay_is_exact(initialized_database) -> None:
    factory = _factory(initialized_database)
    sr = _official_sr(factory, "22334455")
    seeded = _seed_source_projection_proposal(
        factory,
        target_service_request_id=sr.service_request_id,
        target_sr_no="22334455",
    )
    command_id = new_uuid4()
    service = ProposalDecisionService(factory)

    result = service.accept(
        command_id=command_id,
        proposal_id=seeded["proposal_id"],
        proposal_revision=1,
        proposal_fingerprint=seeded["fingerprint"],
        base_state_token=seeded["base_token"],
        reason_category="reviewed_source_projection",
    )
    assert result.decision == "accepted"
    assert result.revision == 2
    assert result.replayed is False
    assert len(result.owner_result_refs) == 1
    assert result.owner_result_refs[0][0] == "sr_source_field_observation"
    owner_observation_id = result.owner_result_refs[0][1]

    with ReadSnapshot(factory) as snapshot:
        projection = snapshot.connection.execute(
            "SELECT problem_summary_observation_id,revision FROM sr_current_source_projection WHERE service_request_id=?",
            (sr.service_request_id,),
        ).fetchone()
        assert tuple(projection) == (owner_observation_id, 1)
        owner_row = snapshot.connection.execute(
            "SELECT source_observation_field_id,accepted_command_id,text_value,source_chronology_utc "
            "FROM sr_source_field_observations WHERE sr_source_field_observation_id=?",
            (owner_observation_id,),
        ).fetchone()
        assert tuple(owner_row) == (seeded["field_id"], command_id, "Problem Alpha", 100)
        proposal = snapshot.connection.execute(
            "SELECT proposal_state,revision FROM reconciliation_proposals WHERE reconciliation_proposal_id=?",
            (seeded["proposal_id"],),
        ).fetchone()
        assert tuple(proposal) == ("accepted", 2)
        run = snapshot.connection.execute(
            "SELECT run_state,pending_proposal_count,accepted_proposal_count,revision FROM import_runs WHERE import_run_id=?",
            (seeded["run_id"],),
        ).fetchone()
        assert tuple(run) == ("waiting_review", 0, 1, 2)
        disposition = snapshot.connection.execute(
            "SELECT decision,proposal_revision,command_id FROM proposal_dispositions WHERE reconciliation_proposal_id=?",
            (seeded["proposal_id"],),
        ).fetchone()
        assert tuple(disposition) == ("accepted", 1, command_id)
        audit = snapshot.connection.execute(
            "SELECT payload_json FROM audit_events WHERE command_id=? AND action_type='ticket_import.proposal_decided'",
            (command_id,),
        ).fetchone()
        assert audit is not None
        assert "Problem Alpha" not in str(audit[0])
        assert snapshot.connection.execute(
            "SELECT COUNT(*) FROM command_receipts WHERE command_id=?",
            (command_id,),
        ).fetchone()[0] == 1

    replay = service.accept(
        command_id=command_id,
        proposal_id=seeded["proposal_id"],
        proposal_revision=1,
        proposal_fingerprint=seeded["fingerprint"],
        base_state_token=seeded["base_token"],
        reason_category="reviewed_source_projection",
    )
    assert replay.replayed is True
    assert replay.decision == "accepted"
    assert replay.revision == 2
    assert replay.owner_result_refs == result.owner_result_refs
    with ReadSnapshot(factory) as snapshot:
        assert snapshot.connection.execute(
            "SELECT COUNT(*) FROM sr_source_field_observations WHERE service_request_id=?",
            (sr.service_request_id,),
        ).fetchone()[0] == 1
        assert snapshot.connection.execute(
            "SELECT COUNT(*) FROM proposal_dispositions WHERE reconciliation_proposal_id=?",
            (seeded["proposal_id"],),
        ).fetchone()[0] == 1


def test_accept_stale_owner_base_fails_before_receipt_and_leaves_proposal_pending(initialized_database) -> None:
    factory = _factory(initialized_database)
    sr = _official_sr(factory, "22334456")
    seeded = _seed_source_projection_proposal(
        factory,
        target_service_request_id=sr.service_request_id,
        target_sr_no="22334456",
    )
    with UnitOfWork(factory) as uow:
        uow.connection.execute(
            "UPDATE service_requests SET revision=revision+1,updated_at_utc=updated_at_utc+1 WHERE service_request_id=?",
            (sr.service_request_id,),
        )
    command_id = new_uuid4()

    with pytest.raises(SomaError) as excinfo:
        ProposalDecisionService(factory).accept(
            command_id=command_id,
            proposal_id=seeded["proposal_id"],
            proposal_revision=1,
            proposal_fingerprint=seeded["fingerprint"],
            base_state_token=seeded["base_token"],
        )
    assert excinfo.value.code == "IMPORT_PROPOSAL_STALE"
    with ReadSnapshot(factory) as snapshot:
        assert snapshot.connection.execute(
            "SELECT 1 FROM command_receipts WHERE command_id=?",
            (command_id,),
        ).fetchone() is None
        assert snapshot.connection.execute(
            "SELECT proposal_state FROM reconciliation_proposals WHERE reconciliation_proposal_id=?",
            (seeded["proposal_id"],),
        ).fetchone()[0] == "pending"
        assert snapshot.connection.execute(
            "SELECT COUNT(*) FROM proposal_dispositions WHERE reconciliation_proposal_id=?",
            (seeded["proposal_id"],),
        ).fetchone()[0] == 0
        assert snapshot.connection.execute(
            "SELECT COUNT(*) FROM sr_source_field_observations WHERE service_request_id=?",
            (sr.service_request_id,),
        ).fetchone()[0] == 0
        run = snapshot.connection.execute(
            "SELECT pending_proposal_count,accepted_proposal_count,revision FROM import_runs WHERE import_run_id=?",
            (seeded["run_id"],),
        ).fetchone()
        assert tuple(run) == (1, 0, 1)


def test_accept_rejects_cross_sr_source_field_substitution_without_receipt(initialized_database) -> None:
    factory = _factory(initialized_database)
    target = _official_sr(factory, "22334457")
    _other = _official_sr(factory, "22334458")
    seeded = _seed_source_projection_proposal(
        factory,
        target_service_request_id=target.service_request_id,
        target_sr_no="22334457",
        source_sr_no="22334458",
    )
    command_id = new_uuid4()

    with pytest.raises(SomaError) as excinfo:
        ProposalDecisionService(factory).accept(
            command_id=command_id,
            proposal_id=seeded["proposal_id"],
            proposal_revision=1,
            proposal_fingerprint=seeded["fingerprint"],
            base_state_token=seeded["base_token"],
        )
    assert excinfo.value.code == "IMPORT_PROPOSAL_STALE"
    with ReadSnapshot(factory) as snapshot:
        assert snapshot.connection.execute(
            "SELECT 1 FROM command_receipts WHERE command_id=?",
            (command_id,),
        ).fetchone() is None
        assert snapshot.connection.execute(
            "SELECT proposal_state FROM reconciliation_proposals WHERE reconciliation_proposal_id=?",
            (seeded["proposal_id"],),
        ).fetchone()[0] == "pending"
        assert snapshot.connection.execute(
            "SELECT COUNT(*) FROM proposal_dispositions WHERE reconciliation_proposal_id=?",
            (seeded["proposal_id"],),
        ).fetchone()[0] == 0


class _FailAfterReceiptOwner:
    @staticmethod
    def source_acceptance_base_token(reader, service_request_id: str) -> str:
        return ServiceRequestImportMutationService.source_acceptance_base_token(reader, service_request_id)

    @staticmethod
    def apply_accepted_source_projection(uow: UnitOfWork, mutation: ServiceRequestSourceProjectionMutation):
        assert uow.connection.execute(
            "SELECT 1 FROM command_receipts WHERE command_id=?",
            (mutation.accepted_delta_set.accepted_command_id,),
        ).fetchone() is not None
        raise SomaError("INJECTED_OWNER_FAILURE", "failure after outer receipt insertion")


def test_owner_failure_after_receipt_rolls_back_entire_cross_packet_acceptance(initialized_database) -> None:
    factory = _factory(initialized_database)
    sr = _official_sr(factory, "22334459")
    seeded = _seed_source_projection_proposal(
        factory,
        target_service_request_id=sr.service_request_id,
        target_sr_no="22334459",
    )
    command_id = new_uuid4()
    service = ProposalDecisionService(factory, sr_import_mutation_service=_FailAfterReceiptOwner())

    with pytest.raises(SomaError) as excinfo:
        service.accept(
            command_id=command_id,
            proposal_id=seeded["proposal_id"],
            proposal_revision=1,
            proposal_fingerprint=seeded["fingerprint"],
            base_state_token=seeded["base_token"],
            reason_category="failure_injection",
        )
    assert excinfo.value.code == "INJECTED_OWNER_FAILURE"
    with ReadSnapshot(factory) as snapshot:
        assert snapshot.connection.execute(
            "SELECT 1 FROM command_receipts WHERE command_id=?",
            (command_id,),
        ).fetchone() is None
        assert snapshot.connection.execute(
            "SELECT proposal_state,revision FROM reconciliation_proposals WHERE reconciliation_proposal_id=?",
            (seeded["proposal_id"],),
        ).fetchone() == ("pending", 1)
        assert snapshot.connection.execute(
            "SELECT COUNT(*) FROM proposal_dispositions WHERE reconciliation_proposal_id=?",
            (seeded["proposal_id"],),
        ).fetchone()[0] == 0
        assert snapshot.connection.execute(
            "SELECT COUNT(*) FROM audit_events WHERE command_id=?",
            (command_id,),
        ).fetchone()[0] == 0
        assert snapshot.connection.execute(
            "SELECT COUNT(*) FROM sr_source_field_observations WHERE service_request_id=?",
            (sr.service_request_id,),
        ).fetchone()[0] == 0
        run = snapshot.connection.execute(
            "SELECT pending_proposal_count,accepted_proposal_count,revision FROM import_runs WHERE import_run_id=?",
            (seeded["run_id"],),
        ).fetchone()
        assert tuple(run) == (1, 0, 1)
