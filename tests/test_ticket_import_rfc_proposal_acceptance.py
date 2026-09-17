from __future__ import annotations

from soma.foundation.identifiers import new_uuid4
from soma.foundation.persistence.uow import ReadSnapshot, UnitOfWork
from soma.ticket_import.commands.decide_proposal import ProposalDecisionService
from soma.ticket_import.providers.rfc_source_evidence import TicketImportRfcSourceEvidenceProvider
from soma.tickets.rfc_import_mutations import RfcImportMutationService
from soma.tickets.rfcs import RfcService


def _factory(initialized_database):
    database_path, factory_for_path = initialized_database
    return factory_for_path(database_path)


def _seed_rfc_run(uow: UnitOfWork, *, run_id: str, pending: int = 1) -> None:
    uow.connection.execute(
        "INSERT INTO import_runs("
        "import_run_id,source_family,invocation_kind,source_profile_id,header_registry_id,vocabulary_registry_id,parser_profile_id,"
        "candidate_filename,candidate_file_size_bytes,candidate_stable_mtime_ns,candidate_chronology_kind,candidate_chronology_value,"
        "logical_fingerprint_sha256,run_state,started_at_utc,staged_at_utc,observed_row_count,valid_identity_count,"
        "proposal_count,pending_proposal_count,revision"
        ") VALUES (?, 'rfc_enhanced','manual','RFC_ENHANCED_V1','RFC_HEADERS_V1','RFC_VOCAB_V1','RFC_PARSER_V1',"
        "'operator-selected-rfc.xlsx',100,1,'filesystem_mtime_ns',200,?,'waiting_review',0,1,1,1,?,?,1)",
        (run_id, "1" * 64, pending, pending),
    )


def _seed_rfc_observation(
    uow: UnitOfWork,
    *,
    run_id: str,
    observation_id: str,
    rfc_no: str,
    chronology: int | None = 100,
) -> None:
    uow.connection.execute(
        "INSERT INTO source_observations(source_observation_id,import_run_id,source_family,entity_kind,identity_state,"
        "canonical_primary_id,canonical_parent_rfc_no,row_ordinal,sheet_ordinal,row_logical_sha256,source_row_chronology_utc,"
        "presence_state,recorded_at_utc) VALUES (?,?,'rfc_enhanced','rfc','valid',?,NULL,1,1,?,?,"
        "'observed_valid_identity',1)",
        (observation_id, run_id, rfc_no, "2" * 64, chronology),
    )


def _seed_identity_proposal(
    uow: UnitOfWork,
    *,
    run_id: str,
    observation_id: str,
    proposal_id: str,
    rfc_no: str,
    base_token: str,
    fingerprint: str,
) -> None:
    uow.connection.execute(
        "INSERT INTO reconciliation_proposals(reconciliation_proposal_id,import_run_id,evidence_mode,source_observation_id,"
        "prior_source_observation_id,proposal_kind,target_kind,target_internal_id,target_business_id,risk_class,"
        "base_state_token_sha256,proposal_fingerprint_sha256,proposal_state,created_at_utc,revision,decided_at_utc) "
        "VALUES (?,?,'observed_row',?,NULL,'rfc_create_or_adopt','rfc',NULL,?,'medium',?,?,'pending',1,1,NULL)",
        (proposal_id, run_id, observation_id, rfc_no, base_token, fingerprint),
    )
    uow.connection.execute(
        "INSERT INTO reconciliation_proposal_changes(reconciliation_proposal_id,ordinal,field_key,change_kind,value_kind,"
        "before_text,after_text,before_integer,after_integer,source_observation_field_id) "
        "VALUES (?,0,'rfc_no','create','identity',NULL,?,NULL,NULL,NULL)",
        (proposal_id, rfc_no),
    )


def test_accept_rfc_create_uses_exact_published_identity_and_replays_without_owner_reads(initialized_database) -> None:
    factory = _factory(initialized_database)
    run_id = new_uuid4()
    observation_id = new_uuid4()
    proposal_id = new_uuid4()
    command_id = new_uuid4()
    rfc_no = "NC00000000000001"
    owner = RfcImportMutationService(TicketImportRfcSourceEvidenceProvider())
    with UnitOfWork(factory) as uow:
        _seed_rfc_run(uow, run_id=run_id)
        _seed_rfc_observation(uow, run_id=run_id, observation_id=observation_id, rfc_no=rfc_no)
        base_token = owner.source_identity_base_token(uow.connection, rfc_no)
        _seed_identity_proposal(
            uow,
            run_id=run_id,
            observation_id=observation_id,
            proposal_id=proposal_id,
            rfc_no=rfc_no,
            base_token=base_token,
            fingerprint="3" * 64,
        )

    service = ProposalDecisionService(factory)
    first = service.accept(
        command_id=command_id,
        proposal_id=proposal_id,
        proposal_revision=1,
        proposal_fingerprint="3" * 64,
        base_state_token=base_token,
    )
    assert first.decision == "accepted"
    assert first.replayed is False
    assert len(first.owner_result_refs) == 1
    assert first.owner_result_refs[0][0] == "rfc"

    replay = service.accept(
        command_id=command_id,
        proposal_id=proposal_id,
        proposal_revision=1,
        proposal_fingerprint="3" * 64,
        base_state_token=base_token,
    )
    assert replay.replayed is True
    assert replay.owner_result_refs == first.owner_result_refs

    with ReadSnapshot(factory) as snapshot:
        rfc = snapshot.connection.execute("SELECT rfc_id,rfc_no FROM rfcs WHERE rfc_no=?", (rfc_no,)).fetchone()
        assert rfc is not None
        assert str(rfc[0]) == first.owner_result_refs[0][1]
        assert str(rfc[1]) == rfc_no
        proposal = snapshot.connection.execute(
            "SELECT proposal_state,revision FROM reconciliation_proposals WHERE reconciliation_proposal_id=?",
            (proposal_id,),
        ).fetchone()
        assert tuple(proposal) == ("accepted", 2)
        assert snapshot.connection.execute(
            "SELECT COUNT(*) FROM proposal_dispositions WHERE reconciliation_proposal_id=?",
            (proposal_id,),
        ).fetchone()[0] == 1


def test_accept_rfc_source_projection_applies_exact_published_field(initialized_database) -> None:
    factory = _factory(initialized_database)
    rfc = RfcService(factory).create_or_adopt_identity(
        command_id=new_uuid4(),
        rfc_no="NC00000000000002",
        creation_context="manual",
    )
    run_id = new_uuid4()
    observation_id = new_uuid4()
    field_id = new_uuid4()
    proposal_id = new_uuid4()
    command_id = new_uuid4()
    provider = TicketImportRfcSourceEvidenceProvider()
    owner = RfcImportMutationService(provider)

    with UnitOfWork(factory) as uow:
        _seed_rfc_run(uow, run_id=run_id)
        _seed_rfc_observation(
            uow,
            run_id=run_id,
            observation_id=observation_id,
            rfc_no=rfc.rfc_no,
            chronology=100,
        )
        uow.connection.execute(
            "INSERT INTO source_observation_fields(source_observation_field_id,source_observation_id,field_key,field_class,"
            "value_state,value_kind,source_text,normalized_text,integer_value,vocabulary_id,field_logical_sha256) "
            "VALUES (?,?,'summary','active','usable','text','RFC Alpha','RFC Alpha',NULL,NULL,?)",
            (field_id, observation_id, "4" * 64),
        )
        base_token = owner.source_acceptance_base_token(uow.connection, rfc.rfc_id)
        uow.connection.execute(
            "INSERT INTO reconciliation_proposals(reconciliation_proposal_id,import_run_id,evidence_mode,source_observation_id,"
            "prior_source_observation_id,proposal_kind,target_kind,target_internal_id,target_business_id,risk_class,"
            "base_state_token_sha256,proposal_fingerprint_sha256,proposal_state,created_at_utc,revision,decided_at_utc) "
            "VALUES (?,?,'observed_row',?,NULL,'rfc_source_projection','rfc',?,?, 'medium',?,?,'pending',1,1,NULL)",
            (proposal_id, run_id, observation_id, rfc.rfc_id, rfc.rfc_no, base_token, "5" * 64),
        )
        uow.connection.execute(
            "INSERT INTO reconciliation_proposal_changes(reconciliation_proposal_id,ordinal,field_key,change_kind,value_kind,"
            "before_text,after_text,before_integer,after_integer,source_observation_field_id) "
            "VALUES (?,0,'summary','set','text',NULL,'RFC Alpha',NULL,NULL,?)",
            (proposal_id, field_id),
        )

    result = ProposalDecisionService(factory).accept(
        command_id=command_id,
        proposal_id=proposal_id,
        proposal_revision=1,
        proposal_fingerprint="5" * 64,
        base_state_token=base_token,
    )
    assert result.decision == "accepted"
    assert result.replayed is False

    with ReadSnapshot(factory) as snapshot:
        projection = snapshot.connection.execute(
            "SELECT summary_text,summary_evidence_id,revision FROM rfc_current_source_projection WHERE rfc_id=?",
            (rfc.rfc_id,),
        ).fetchone()
        assert tuple(projection) == ("RFC Alpha", field_id, 1)
        run = snapshot.connection.execute(
            "SELECT pending_proposal_count,accepted_proposal_count,revision FROM import_runs WHERE import_run_id=?",
            (run_id,),
        ).fetchone()
        assert tuple(run) == (0, 1, 2)
