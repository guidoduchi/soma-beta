from __future__ import annotations

from soma.foundation.identifiers import new_uuid4
from soma.foundation.persistence.uow import ReadSnapshot, UnitOfWork
from soma.reference.application.customer_service import CustomerReferenceService
from soma.ticket_import.reconciliation.rfc_enhanced_customer import (
    build_rfc_enhanced_customer_reconciliation_proposals,
)
from soma.tickets.rfc_import_mutations import RfcImportMutationService


def _factory(initialized_database):
    database_path, factory_for_path = initialized_database
    return factory_for_path(database_path)


def _customer(factory, *, name: str, account_code: str | None = None):
    return CustomerReferenceService(factory).create_customer_organization(
        command_id=new_uuid4(),
        name=name,
        account_code=account_code,
    )


def _seed_rfc(factory, rfc_no: str, *, customer_org_id: str | None = None) -> str:
    rfc_id = new_uuid4()
    with UnitOfWork(factory) as uow:
        uow.connection.execute(
            "INSERT INTO rfcs(rfc_id,rfc_no,customer_org_id,local_archive_state,revision,created_at_utc,updated_at_utc) "
            "VALUES (?,?,?,'active',1,1,1)",
            (rfc_id, rfc_no, customer_org_id),
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
    account_code: str | None,
    customer_name: str | None,
) -> tuple[str, str | None]:
    observation_id = new_uuid4()
    account_field_id = new_uuid4() if account_code is not None else None
    with UnitOfWork(factory) as uow:
        uow.connection.execute(
            "INSERT INTO source_observations(source_observation_id,import_run_id,source_family,entity_kind,identity_state,"
            "canonical_primary_id,canonical_parent_rfc_no,row_ordinal,sheet_ordinal,row_logical_sha256,source_row_chronology_utc,"
            "presence_state,recorded_at_utc) VALUES (?,?,'rfc_enhanced','rfc','valid',?,NULL,1,1,?,200,"
            "'observed_valid_identity',1)",
            (observation_id, run_id, rfc_no, "a" * 64),
        )
        if account_code is not None:
            uow.connection.execute(
                "INSERT INTO source_observation_fields(source_observation_field_id,source_observation_id,field_key,field_class,"
                "value_state,value_kind,source_text,normalized_text,integer_value,vocabulary_id,field_logical_sha256) "
                "VALUES (?,?,'customer_account_number','active','usable','text',?,?,NULL,NULL,?)",
                (account_field_id, observation_id, account_code, account_code, "b" * 64),
            )
        if customer_name is not None:
            uow.connection.execute(
                "INSERT INTO source_observation_fields(source_observation_field_id,source_observation_id,field_key,field_class,"
                "value_state,value_kind,source_text,normalized_text,integer_value,vocabulary_id,field_logical_sha256) "
                "VALUES (?,?,'customer_account_name','active','usable','text',?,?,NULL,NULL,?)",
                (new_uuid4(), observation_id, customer_name, customer_name, "c" * 64),
            )
    return observation_id, account_field_id


def _build(factory, *, run_id: str, observation_id: str):
    with ReadSnapshot(factory) as snapshot:
        return build_rfc_enhanced_customer_reconciliation_proposals(
            snapshot.connection,
            import_run_id=run_id,
            source_observation_id=observation_id,
        )


def test_existing_rfc_builds_exact_high_risk_customer_proposal(initialized_database) -> None:
    factory = _factory(initialized_database)
    target = _customer(factory, name="Target Customer", account_code="RFC-ACC-200")
    rfc_no = "NC20260917000001"
    rfc_id = _seed_rfc(factory, rfc_no)
    run_id = _seed_validating_run(factory)
    observation_id, account_field_id = _seed_observation(
        factory,
        run_id=run_id,
        rfc_no=rfc_no,
        account_code="RFC-ACC-200",
        customer_name="Target Customer",
    )

    result = _build(factory, run_id=run_id, observation_id=observation_id)
    assert result.resolution_state == "unique_candidate"
    assert result.matcher_explanation == "ACCOUNT_CODE_MATCH"
    assert result.rfc_id == rfc_id
    assert len(result.proposals) == 1
    proposal = result.proposals[0]
    assert proposal.proposal_kind == "rfc_customer_reconciliation"
    assert proposal.risk_class == "high"
    assert proposal.target_internal_id == rfc_id
    assert proposal.target_business_id == rfc_no
    assert len(proposal.changes) == 1
    change = proposal.changes[0]
    assert change.ordinal == 0
    assert change.field_key == "customer_org_id"
    assert change.change_kind == "set"
    assert change.value_kind == "identity"
    assert change.before_text is None
    assert change.after_text == target.customer_org_id
    assert change.source_observation_field_id == account_field_id
    with ReadSnapshot(factory) as snapshot:
        expected = RfcImportMutationService.customer_reconciliation_base_token(
            snapshot.connection,
            rfc_id,
            target.customer_org_id,
        )
    assert proposal.base_state_token_sha256 == expected


def test_customer_builder_never_uses_name_as_identity_authority(initialized_database) -> None:
    factory = _factory(initialized_database)
    _customer(factory, name="Name Only Customer")
    rfc_no = "NC20260917000002"
    _seed_rfc(factory, rfc_no)
    run_id = _seed_validating_run(factory)
    observation_id, _ = _seed_observation(
        factory,
        run_id=run_id,
        rfc_no=rfc_no,
        account_code=None,
        customer_name="Name Only Customer",
    )

    result = _build(factory, run_id=run_id, observation_id=observation_id)
    assert result.resolution_state == "account_code_unusable"
    assert result.proposals == ()


def test_missing_rfc_defers_customer_until_identity_exists(initialized_database) -> None:
    factory = _factory(initialized_database)
    _customer(factory, name="Deferred Customer", account_code="RFC-ACC-202")
    run_id = _seed_validating_run(factory)
    observation_id, _ = _seed_observation(
        factory,
        run_id=run_id,
        rfc_no="NC20260917000003",
        account_code="RFC-ACC-202",
        customer_name="Deferred Customer",
    )

    result = _build(factory, run_id=run_id, observation_id=observation_id)
    assert result.rfc_id is None
    assert result.resolution_state == "rfc_identity_pending"
    assert result.proposals == ()
