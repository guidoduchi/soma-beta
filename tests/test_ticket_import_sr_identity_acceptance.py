from __future__ import annotations

import pytest

from soma.foundation.errors import SomaError
from soma.foundation.identifiers import new_uuid4
from soma.foundation.persistence.uow import ReadSnapshot, UnitOfWork
from soma.ticket_import.commands.decide_proposal import ProposalDecisionService
from soma.tickets.import_mutations import ServiceRequestImportMutationService
from soma.tickets.service_requests import ServiceRequestService


def _factory(initialized_database):
    database_path, factory_for_path = initialized_database
    return factory_for_path(database_path)


def _seed_run(uow: UnitOfWork, run_id: str) -> None:
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


def _seed_observation(uow: UnitOfWork, *, run_id: str, observation_id: str, sr_no: str) -> None:
    uow.connection.execute(
        "INSERT INTO source_observations(source_observation_id,import_run_id,source_family,entity_kind,identity_state,"
        "canonical_primary_id,canonical_parent_rfc_no,row_ordinal,sheet_ordinal,row_logical_sha256,source_row_chronology_utc,"
        "presence_state,recorded_at_utc) VALUES (?,?,'advanced_search_sr','service_request','valid',?,NULL,1,1,?,100,"
        "'observed_valid_identity',1)",
        (observation_id, run_id, sr_no, "2" * 64),
    )


def _seed_create_proposal(
    factory,
    *,
    sr_no: str,
    observation_run_id: str | None = None,
    target_internal_id: str | None = None,
):
    proposal_run_id = new_uuid4()
    observation_run = proposal_run_id if observation_run_id is None else observation_run_id
    observation_id = new_uuid4()
    proposal_id = new_uuid4()
    fingerprint = "7" * 64
    with UnitOfWork(factory) as uow:
        if observation_run == proposal_run_id:
            _seed_run(uow, proposal_run_id)
        else:
            _seed_run(uow, proposal_run_id)
            _seed_run(uow, observation_run)
        _seed_observation(uow, run_id=observation_run, observation_id=observation_id, sr_no=sr_no)
        base_token = ServiceRequestImportMutationService.source_identity_base_token(uow.connection, sr_no)
        uow.connection.execute(
            "INSERT INTO reconciliation_proposals(reconciliation_proposal_id,import_run_id,evidence_mode,source_observation_id,"
            "prior_source_observation_id,proposal_kind,target_kind,target_internal_id,target_business_id,risk_class,"
            "base_state_token_sha256,proposal_fingerprint_sha256,proposal_state,created_at_utc,revision,decided_at_utc) "
            "VALUES (?,?,'observed_row',?,NULL,'sr_create_or_adopt','service_request',?,?,'medium',?,?,'pending',1,1,NULL)",
            (
                proposal_id,
                proposal_run_id,
                observation_id,
                target_internal_id,
                sr_no,
                base_token,
                fingerprint,
            ),
        )
    return {
        "proposal_run_id": proposal_run_id,
        "observation_run_id": observation_run,
        "observation_id": observation_id,
        "proposal_id": proposal_id,
        "fingerprint": fingerprint,
        "base_token": base_token,
    }


def test_accept_missing_sr_identity_creates_exact_official_sr_with_two_required_audits_and_replays(initialized_database) -> None:
    factory = _factory(initialized_database)
    seeded = _seed_create_proposal(factory, sr_no="33445566")
    command_id = new_uuid4()
    service = ProposalDecisionService(factory)

    result = service.accept(
        command_id=command_id,
        proposal_id=seeded["proposal_id"],
        proposal_revision=1,
        proposal_fingerprint=seeded["fingerprint"],
        base_state_token=seeded["base_token"],
        reason_category="reviewed_source_identity",
    )
    assert result.decision == "accepted"
    assert result.revision == 2
    assert result.replayed is False
    assert len(result.owner_result_refs) == 1
    assert result.owner_result_refs[0][0] == "service_request"
    service_request_id = result.owner_result_refs[0][1]

    with ReadSnapshot(factory) as snapshot:
        row = snapshot.connection.execute(
            "SELECT official_sr_no,local_sr_no,revision FROM service_requests WHERE service_request_id=?",
            (service_request_id,),
        ).fetchone()
        assert tuple(row) == ("33445566", None, 1)
        actions = snapshot.connection.execute(
            "SELECT action_type,payload_json FROM audit_events WHERE command_id=? ORDER BY action_type",
            (command_id,),
        ).fetchall()
        assert [str(row[0]) for row in actions] == [
            "ticket.service_request.created",
            "ticket_import.proposal_decided",
        ]
        assert "accepted_source" in str(actions[0][1])
        assert "33445566" not in str(actions[0][1])
        assert "33445566" not in str(actions[1][1])
        assert snapshot.connection.execute(
            "SELECT COUNT(*) FROM command_receipts WHERE command_id=?",
            (command_id,),
        ).fetchone()[0] == 1
        run = snapshot.connection.execute(
            "SELECT pending_proposal_count,accepted_proposal_count,revision FROM import_runs WHERE import_run_id=?",
            (seeded["proposal_run_id"],),
        ).fetchone()
        assert tuple(run) == (0, 1, 2)

    replay = service.accept(
        command_id=command_id,
        proposal_id=seeded["proposal_id"],
        proposal_revision=1,
        proposal_fingerprint=seeded["fingerprint"],
        base_state_token=seeded["base_token"],
        reason_category="reviewed_source_identity",
    )
    assert replay.replayed is True
    assert replay.owner_result_refs == result.owner_result_refs
    with ReadSnapshot(factory) as snapshot:
        assert snapshot.connection.execute(
            "SELECT COUNT(*) FROM service_requests WHERE official_sr_no='33445566'"
        ).fetchone()[0] == 1
        assert snapshot.connection.execute(
            "SELECT COUNT(*) FROM audit_events WHERE command_id=?",
            (command_id,),
        ).fetchone()[0] == 2


def test_sr_identity_creation_race_becomes_stale_without_accept_receipt(initialized_database) -> None:
    factory = _factory(initialized_database)
    seeded = _seed_create_proposal(factory, sr_no="33445567")
    existing = ServiceRequestService(factory).create_manual_service_request(
        command_id=new_uuid4(),
        official_sr_no="33445567",
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
        rows = snapshot.connection.execute(
            "SELECT service_request_id FROM service_requests WHERE official_sr_no='33445567'"
        ).fetchall()
        assert [str(row[0]) for row in rows] == [existing.service_request_id]
        assert snapshot.connection.execute(
            "SELECT 1 FROM command_receipts WHERE command_id=?",
            (command_id,),
        ).fetchone() is None
        assert snapshot.connection.execute(
            "SELECT proposal_state FROM reconciliation_proposals WHERE reconciliation_proposal_id=?",
            (seeded["proposal_id"],),
        ).fetchone()[0] == "pending"


def test_sr_identity_accept_rejects_cross_run_observation_before_receipt(initialized_database) -> None:
    factory = _factory(initialized_database)
    foreign_run = new_uuid4()
    seeded = _seed_create_proposal(factory, sr_no="33445568", observation_run_id=foreign_run)
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
            "SELECT 1 FROM service_requests WHERE official_sr_no='33445568'"
        ).fetchone() is None


def test_pending_exact_existing_adoption_cannot_fabricate_owner_mutation(initialized_database) -> None:
    factory = _factory(initialized_database)
    existing = ServiceRequestService(factory).create_manual_service_request(
        command_id=new_uuid4(),
        official_sr_no="33445569",
    )
    seeded = _seed_create_proposal(
        factory,
        sr_no="33445569",
        target_internal_id=existing.service_request_id,
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
        row = snapshot.connection.execute(
            "SELECT local_sr_no,revision FROM service_requests WHERE service_request_id=?",
            (existing.service_request_id,),
        ).fetchone()
        assert tuple(row) == (None, 1)
        assert snapshot.connection.execute(
            "SELECT 1 FROM command_receipts WHERE command_id=?",
            (command_id,),
        ).fetchone() is None
        assert snapshot.connection.execute(
            "SELECT COUNT(*) FROM audit_events WHERE command_id=?",
            (command_id,),
        ).fetchone()[0] == 0
