from __future__ import annotations

from soma.foundation.identifiers import new_uuid4
from soma.foundation.persistence.uow import ReadSnapshot, UnitOfWork
from soma.reference.application.customer_service import CustomerReferenceService
from soma.ticket_import.commands.decide_proposal import ProposalDecisionService
from soma.ticket_import.providers.rfc_source_evidence import TicketImportRfcSourceEvidenceProvider
from soma.tickets.rfc_import_mutations import RfcImportMutationService
from soma.tickets.rfcs import RfcService
from soma.tickets.service_requests import ServiceRequestService


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


def test_accept_rfc_identity_appends_source_projection_follow_on_and_replays(initialized_database) -> None:
    factory = _factory(initialized_database)
    run_id = new_uuid4()
    observation_id = new_uuid4()
    status_field_id = new_uuid4()
    proposal_id = new_uuid4()
    identity_command_id = new_uuid4()
    rfc_no = "NC00000000000011"
    owner = RfcImportMutationService(TicketImportRfcSourceEvidenceProvider())

    with UnitOfWork(factory) as uow:
        _seed_rfc_run(uow, run_id=run_id)
        _seed_rfc_observation(
            uow,
            run_id=run_id,
            observation_id=observation_id,
            rfc_no=rfc_no,
            chronology=100,
        )
        uow.connection.execute(
            "INSERT INTO source_observation_fields(source_observation_field_id,source_observation_id,field_key,field_class,"
            "value_state,value_kind,source_text,normalized_text,integer_value,vocabulary_id,field_logical_sha256) "
            "VALUES (?,?,'status','active','usable','controlled','Implement','Implement',NULL,'RFC_STATUS_V1',?)",
            (status_field_id, observation_id, "a" * 64),
        )
        base_token = owner.source_identity_base_token(uow.connection, rfc_no)
        _seed_identity_proposal(
            uow,
            run_id=run_id,
            observation_id=observation_id,
            proposal_id=proposal_id,
            rfc_no=rfc_no,
            base_token=base_token,
            fingerprint="b" * 64,
        )

    service = ProposalDecisionService(factory)
    first = service.accept(
        command_id=identity_command_id,
        proposal_id=proposal_id,
        proposal_revision=1,
        proposal_fingerprint="b" * 64,
        base_state_token=base_token,
    )
    assert first.decision == "accepted"
    assert first.replayed is False
    rfc_refs = [ref for ref in first.owner_result_refs if ref[0] == "rfc"]
    assert len(rfc_refs) == 1
    rfc_id = rfc_refs[0][1]

    replay = service.accept(
        command_id=identity_command_id,
        proposal_id=proposal_id,
        proposal_revision=1,
        proposal_fingerprint="b" * 64,
        base_state_token=base_token,
    )
    assert replay.replayed is True
    assert replay.owner_result_refs == first.owner_result_refs

    with ReadSnapshot(factory) as snapshot:
        follow_on = snapshot.connection.execute(
            "SELECT reconciliation_proposal_id,target_internal_id,target_business_id,risk_class,"
            "base_state_token_sha256,proposal_fingerprint_sha256,proposal_state,revision "
            "FROM reconciliation_proposals WHERE import_run_id=? AND proposal_kind='rfc_source_projection'",
            (run_id,),
        ).fetchone()
        assert follow_on is not None
        projection_proposal_id = str(follow_on[0])
        assert tuple(follow_on[1:4]) == (rfc_id, rfc_no, "medium")
        projection_base_token = str(follow_on[4])
        projection_fingerprint = str(follow_on[5])
        assert tuple(follow_on[6:]) == ("pending", 1)
        change = snapshot.connection.execute(
            "SELECT ordinal,field_key,change_kind,value_kind,before_text,after_text,before_integer,after_integer,"
            "source_observation_field_id FROM reconciliation_proposal_changes "
            "WHERE reconciliation_proposal_id=?",
            (projection_proposal_id,),
        ).fetchone()
        assert tuple(change) == (
            0,
            "status",
            "set",
            "controlled",
            None,
            "Implement",
            None,
            None,
            status_field_id,
        )
        run = snapshot.connection.execute(
            "SELECT proposal_count,pending_proposal_count,accepted_proposal_count,revision "
            "FROM import_runs WHERE import_run_id=?",
            (run_id,),
        ).fetchone()
        assert tuple(run) == (2, 1, 1, 3)

    projection_command_id = new_uuid4()
    projection = service.accept(
        command_id=projection_command_id,
        proposal_id=projection_proposal_id,
        proposal_revision=1,
        proposal_fingerprint=projection_fingerprint,
        base_state_token=projection_base_token,
    )
    assert projection.decision == "accepted"
    assert projection.replayed is False
    projection_replay = service.accept(
        command_id=projection_command_id,
        proposal_id=projection_proposal_id,
        proposal_revision=1,
        proposal_fingerprint=projection_fingerprint,
        base_state_token=projection_base_token,
    )
    assert projection_replay.replayed is True
    assert projection_replay.owner_result_refs == projection.owner_result_refs

    with ReadSnapshot(factory) as snapshot:
        current = snapshot.connection.execute(
            "SELECT status_text,status_class,status_authority,status_evidence_id,revision "
            "FROM rfc_current_source_projection WHERE rfc_id=?",
            (rfc_id,),
        ).fetchone()
        assert tuple(current) == (
            "Implement",
            "implement_eligible",
            "enhanced_rfc",
            status_field_id,
            1,
        )
        run = snapshot.connection.execute(
            "SELECT proposal_count,pending_proposal_count,accepted_proposal_count,revision "
            "FROM import_runs WHERE import_run_id=?",
            (run_id,),
        ).fetchone()
        assert tuple(run) == (2, 0, 2, 4)


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


def test_accept_rfc_customer_reconciliation_revalidates_match_and_replays(initialized_database) -> None:
    factory = _factory(initialized_database)
    customer = CustomerReferenceService(factory).create_customer_organization(
        command_id=new_uuid4(),
        name="Reviewed RFC Customer",
        account_code="RFC-ACC-400",
    )
    rfc = RfcService(factory).create_or_adopt_identity(
        command_id=new_uuid4(),
        rfc_no="NC00000000000003",
        creation_context="manual",
    )
    run_id = new_uuid4()
    observation_id = new_uuid4()
    field_id = new_uuid4()
    proposal_id = new_uuid4()
    command_id = new_uuid4()
    owner = RfcImportMutationService(TicketImportRfcSourceEvidenceProvider())

    with UnitOfWork(factory) as uow:
        _seed_rfc_run(uow, run_id=run_id)
        _seed_rfc_observation(uow, run_id=run_id, observation_id=observation_id, rfc_no=rfc.rfc_no)
        uow.connection.execute(
            "INSERT INTO source_observation_fields(source_observation_field_id,source_observation_id,field_key,field_class,"
            "value_state,value_kind,source_text,normalized_text,integer_value,vocabulary_id,field_logical_sha256) "
            "VALUES (?,?,'customer_account_number','active','usable','text','RFC-ACC-400','RFC-ACC-400',NULL,NULL,?)",
            (field_id, observation_id, "6" * 64),
        )
        base_token = owner.customer_reconciliation_base_token(
            uow.connection,
            rfc.rfc_id,
            customer.customer_org_id,
        )
        uow.connection.execute(
            "INSERT INTO reconciliation_proposals(reconciliation_proposal_id,import_run_id,evidence_mode,source_observation_id,"
            "prior_source_observation_id,proposal_kind,target_kind,target_internal_id,target_business_id,risk_class,"
            "base_state_token_sha256,proposal_fingerprint_sha256,proposal_state,created_at_utc,revision,decided_at_utc) "
            "VALUES (?,?,'observed_row',?,NULL,'rfc_customer_reconciliation','rfc',?,?,'high',?,?,'pending',1,1,NULL)",
            (proposal_id, run_id, observation_id, rfc.rfc_id, rfc.rfc_no, base_token, "7" * 64),
        )
        uow.connection.execute(
            "INSERT INTO reconciliation_proposal_changes(reconciliation_proposal_id,ordinal,field_key,change_kind,value_kind,"
            "before_text,after_text,before_integer,after_integer,source_observation_field_id) "
            "VALUES (?,0,'customer_org_id','set','identity',NULL,?,NULL,NULL,?)",
            (proposal_id, customer.customer_org_id, field_id),
        )

    service = ProposalDecisionService(factory)
    result = service.accept(
        command_id=command_id,
        proposal_id=proposal_id,
        proposal_revision=1,
        proposal_fingerprint="7" * 64,
        base_state_token=base_token,
        reason_category="reviewed_import_customer",
    )
    assert result.decision == "accepted"
    assert result.replayed is False
    replay = service.accept(
        command_id=command_id,
        proposal_id=proposal_id,
        proposal_revision=1,
        proposal_fingerprint="7" * 64,
        base_state_token=base_token,
        reason_category="reviewed_import_customer",
    )
    assert replay.replayed is True
    assert replay.owner_result_refs == result.owner_result_refs

    with ReadSnapshot(factory) as snapshot:
        current = snapshot.connection.execute(
            "SELECT customer_org_id,revision FROM rfcs WHERE rfc_id=?",
            (rfc.rfc_id,),
        ).fetchone()
        assert tuple(current) == (customer.customer_org_id, 2)


def test_accept_rfc_sr_link_candidate_links_existing_exact_sr(initialized_database) -> None:
    factory = _factory(initialized_database)
    sr = ServiceRequestService(factory).create_manual_service_request(
        command_id=new_uuid4(),
        official_sr_no="78901234",
    )
    rfc = RfcService(factory).create_or_adopt_identity(
        command_id=new_uuid4(),
        rfc_no="NC00000000000004",
        creation_context="manual",
    )
    run_id = new_uuid4()
    observation_id = new_uuid4()
    field_id = new_uuid4()
    proposal_id = new_uuid4()
    command_id = new_uuid4()
    owner = RfcImportMutationService(TicketImportRfcSourceEvidenceProvider())

    with UnitOfWork(factory) as uow:
        _seed_rfc_run(uow, run_id=run_id)
        _seed_rfc_observation(uow, run_id=run_id, observation_id=observation_id, rfc_no=rfc.rfc_no)
        uow.connection.execute(
            "INSERT INTO source_observation_fields(source_observation_field_id,source_observation_id,field_key,field_class,"
            "value_state,value_kind,source_text,normalized_text,integer_value,vocabulary_id,field_logical_sha256) "
            "VALUES (?,?,'summary','active','usable','text','Impact to SR78901234','Impact to SR78901234',NULL,NULL,?)",
            (field_id, observation_id, "8" * 64),
        )
        context = owner.sr_link_candidate_context(uow.connection, sr.service_request_id, rfc.rfc_id)
        uow.connection.execute(
            "INSERT INTO reconciliation_proposals(reconciliation_proposal_id,import_run_id,evidence_mode,source_observation_id,"
            "prior_source_observation_id,proposal_kind,target_kind,target_internal_id,target_business_id,risk_class,"
            "base_state_token_sha256,proposal_fingerprint_sha256,proposal_state,created_at_utc,revision,decided_at_utc) "
            "VALUES (?,?,'observed_row',?,NULL,'sr_rfc_link_candidate','sr_rfc_relationship',?,?,?, ?,?,'pending',1,1,NULL)",
            (
                proposal_id,
                run_id,
                observation_id,
                rfc.rfc_id,
                rfc.rfc_no,
                context.risk_class,
                context.base_state_token,
                "9" * 64,
            ),
        )
        uow.connection.execute(
            "INSERT INTO reconciliation_proposal_changes(reconciliation_proposal_id,ordinal,field_key,change_kind,value_kind,"
            "before_text,after_text,before_integer,after_integer,source_observation_field_id) "
            "VALUES (?,0,'service_request_id','candidate','identity',NULL,?,NULL,NULL,?)",
            (proposal_id, sr.service_request_id, field_id),
        )

    result = ProposalDecisionService(factory).accept(
        command_id=command_id,
        proposal_id=proposal_id,
        proposal_revision=1,
        proposal_fingerprint="9" * 64,
        base_state_token=context.base_state_token,
        reason_category="reviewed_import_link",
    )
    assert result.decision == "accepted"
    assert result.replayed is False
    assert len(result.owner_result_refs) == 1
    assert result.owner_result_refs[0][0] == "sr_rfc_relationship"

    with ReadSnapshot(factory) as snapshot:
        link = snapshot.connection.execute(
            "SELECT service_request_id,rfc_id,link_state FROM sr_rfc_links WHERE service_request_id=? AND rfc_id=?",
            (sr.service_request_id, rfc.rfc_id),
        ).fetchone()
        assert tuple(link) == (sr.service_request_id, rfc.rfc_id, "active")
        sr_revision = snapshot.connection.execute(
            "SELECT revision FROM service_requests WHERE service_request_id=?",
            (sr.service_request_id,),
        ).fetchone()[0]
        rfc_revision = snapshot.connection.execute(
            "SELECT revision FROM rfcs WHERE rfc_id=?",
            (rfc.rfc_id,),
        ).fetchone()[0]
        assert int(sr_revision) == 2
        assert int(rfc_revision) == 2
