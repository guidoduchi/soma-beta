from __future__ import annotations

import pytest

from soma.foundation.errors import SomaError
from soma.foundation.identifiers import new_uuid4
from soma.foundation.persistence.uow import ReadSnapshot, UnitOfWork
from soma.reference.application.customer_service import CustomerReferenceService
from soma.ticket_import.providers.sr_customer_reconciliation import TicketImportSrCustomerReconciliationProvider
from soma.ticket_import.reconciliation.advanced_search_customer import (
    build_advanced_search_sr_customer_reconciliation_proposals,
)
from soma.tickets.service_request_import_reader import ServiceRequestImportReader
from soma.tickets.service_requests import ServiceRequestService
from soma.tickets.sr_references import ServiceRequestReferenceService


def _factory(initialized_database):
    database_path, factory_for_path = initialized_database
    return factory_for_path(database_path)


class _NoopClassificationParticipant:
    def preview_customer_change(self, reader, sr_id: str, new_customer_org_id: str | None):
        return {"impact": "none", "service_request_id": sr_id, "customer_org_id": new_customer_org_id}

    def apply_customer_change(self, uow, sr_id: str, new_customer_org_id: str | None, command_context):
        assert uow.connection.in_transaction
        return ()


def _customer(factory, *, name: str, account_code: str | None = None):
    return CustomerReferenceService(factory).create_customer_organization(
        command_id=new_uuid4(),
        name=name,
        account_code=account_code,
    )


def _official_sr(factory, sr_no: str):
    return ServiceRequestService(factory).create_manual_service_request(
        command_id=new_uuid4(),
        official_sr_no=sr_no,
    )


def _set_customer(factory, *, sr_id: str, base_revision: int, customer_org_id: str) -> None:
    ServiceRequestReferenceService(factory, _NoopClassificationParticipant()).set_customer(
        command_id=new_uuid4(),
        service_request_id=sr_id,
        base_revision=base_revision,
        customer_org_id=customer_org_id,
        reason_category="test_customer_context",
    )


def _seed_validating_run(factory) -> str:
    run_id = new_uuid4()
    with UnitOfWork(factory) as uow:
        uow.connection.execute(
            "INSERT INTO import_runs("
            "import_run_id,source_family,invocation_kind,source_profile_id,header_registry_id,vocabulary_registry_id,parser_profile_id,"
            "candidate_filename,candidate_file_size_bytes,candidate_stable_mtime_ns,candidate_chronology_kind,candidate_chronology_value,"
            "logical_fingerprint_sha256,run_state,started_at_utc,staged_at_utc,observed_row_count,valid_identity_count,"
            "proposal_count,pending_proposal_count,revision"
            ") VALUES (?, 'advanced_search_sr','manual','ADVANCED_SEARCH_SR_V1','ADVANCED_SEARCH_HEADERS_V1',"
            "'ADVANCED_SEARCH_VOCAB_V1','ADVANCED_SEARCH_PARSER_V1','Advanced Search(Service Request)20260908030000.xlsx',"
            "100,1,'embedded_filename_timestamp_utc',400,?,'validating',0,1,0,0,0,0,1)",
            (run_id, "1" * 64),
        )
    return run_id


def _seed_observation(
    factory,
    *,
    run_id: str,
    sr_no: str,
    row_hash: str,
    account_code: str | None,
    customer_label: str | None,
) -> dict[str, str | None]:
    observation_id = new_uuid4()
    account_field_id = new_uuid4() if account_code is not None else None
    label_field_id = new_uuid4() if customer_label is not None else None
    with UnitOfWork(factory) as uow:
        uow.connection.execute(
            "INSERT INTO source_observations(source_observation_id,import_run_id,source_family,entity_kind,identity_state,"
            "canonical_primary_id,canonical_parent_rfc_no,row_ordinal,sheet_ordinal,row_logical_sha256,source_row_chronology_utc,"
            "presence_state,recorded_at_utc) VALUES (?,?,'advanced_search_sr','service_request','valid',?,NULL,1,1,?,100,"
            "'observed_valid_identity',1)",
            (observation_id, run_id, sr_no, row_hash),
        )
        if account_field_id is not None and account_code is not None:
            uow.connection.execute(
                "INSERT INTO source_observation_fields(source_observation_field_id,source_observation_id,field_key,field_class,"
                "value_state,value_kind,source_text,normalized_text,integer_value,vocabulary_id,field_logical_sha256) "
                "VALUES (?,?,'customer_account_code','active','usable','text',?,?,NULL,NULL,?)",
                (account_field_id, observation_id, account_code, account_code, "2" * 64),
            )
        if label_field_id is not None and customer_label is not None:
            uow.connection.execute(
                "INSERT INTO source_observation_fields(source_observation_field_id,source_observation_id,field_key,field_class,"
                "value_state,value_kind,source_text,normalized_text,integer_value,vocabulary_id,field_logical_sha256) "
                "VALUES (?,?,'customer_org_label','active','usable','text',?,?,NULL,NULL,?)",
                (label_field_id, observation_id, customer_label, customer_label, "3" * 64),
            )
    return {
        "observation_id": observation_id,
        "account_field_id": account_field_id,
        "label_field_id": label_field_id,
    }


def _build(factory, *, run_id: str, observation_id: str):
    with ReadSnapshot(factory) as snapshot:
        return build_advanced_search_sr_customer_reconciliation_proposals(
            snapshot.connection,
            import_run_id=run_id,
            source_observation_id=observation_id,
        )


def test_customer_builder_emits_exact_high_risk_account_code_proposal(initialized_database) -> None:
    factory = _factory(initialized_database)
    target = _customer(factory, name="Target Customer", account_code="ACC-200")
    sr = _official_sr(factory, "44000100")
    run_id = _seed_validating_run(factory)
    seeded = _seed_observation(
        factory,
        run_id=run_id,
        sr_no="44000100",
        row_hash="a" * 64,
        account_code="ACC-200",
        customer_label="Target Customer",
    )

    result = _build(factory, run_id=run_id, observation_id=str(seeded["observation_id"]))
    assert result.scope_status == "unique"
    assert result.resolution_state == "unique_candidate"
    assert result.matcher_explanation == "ACCOUNT_CODE_MATCH"
    assert result.service_request_id == sr.service_request_id
    assert len(result.proposals) == 1
    proposal = result.proposals[0]
    assert proposal.proposal_kind == "sr_customer_reconciliation"
    assert proposal.risk_class == "high"
    assert proposal.target_internal_id == sr.service_request_id
    assert proposal.target_business_id == "44000100"
    assert len(proposal.changes) == 1
    change = proposal.changes[0]
    assert change.ordinal == 0
    assert change.field_key == "customer_org_id"
    assert change.change_kind == "set"
    assert change.value_kind == "identity"
    assert change.before_text is None
    assert change.after_text == target.customer_org_id
    assert change.before_integer is None
    assert change.after_integer is None
    assert change.source_observation_field_id == seeded["account_field_id"]
    with ReadSnapshot(factory) as snapshot:
        expected = ServiceRequestImportReader.customer_reconciliation_base_token(
            snapshot.connection,
            sr.service_request_id,
            target.customer_org_id,
        )
    assert proposal.base_state_token_sha256 == expected


def test_customer_builder_preserves_prior_customer_and_suppresses_already_current(initialized_database) -> None:
    factory = _factory(initialized_database)
    old_customer = _customer(factory, name="Old Customer", account_code="OLD-1")
    target = _customer(factory, name="Target Customer", account_code="NEW-1")
    sr = _official_sr(factory, "44000101")
    _set_customer(factory, sr_id=sr.service_request_id, base_revision=1, customer_org_id=old_customer.customer_org_id)
    run_id = _seed_validating_run(factory)
    seeded = _seed_observation(
        factory,
        run_id=run_id,
        sr_no="44000101",
        row_hash="b" * 64,
        account_code="NEW-1",
        customer_label="Target Customer",
    )
    result = _build(factory, run_id=run_id, observation_id=str(seeded["observation_id"]))
    assert result.proposals[0].changes[0].before_text == old_customer.customer_org_id

    sr2 = _official_sr(factory, "44000102")
    _set_customer(factory, sr_id=sr2.service_request_id, base_revision=1, customer_org_id=target.customer_org_id)
    run2 = _seed_validating_run(factory)
    seeded2 = _seed_observation(
        factory,
        run_id=run2,
        sr_no="44000102",
        row_hash="c" * 64,
        account_code="NEW-1",
        customer_label="Target Customer",
    )
    no_change = _build(factory, run_id=run2, observation_id=str(seeded2["observation_id"]))
    assert no_change.resolution_state == "already_current"
    assert no_change.proposals == ()


def test_customer_builder_never_uses_label_as_identity_authority(initialized_database) -> None:
    factory = _factory(initialized_database)
    _customer(factory, name="Label Only Customer")
    _official_sr(factory, "44000103")
    run_id = _seed_validating_run(factory)
    seeded = _seed_observation(
        factory,
        run_id=run_id,
        sr_no="44000103",
        row_hash="d" * 64,
        account_code=None,
        customer_label="Label Only Customer",
    )
    result = _build(factory, run_id=run_id, observation_id=str(seeded["observation_id"]))
    assert result.resolution_state == "account_code_unusable"
    assert result.proposals == ()

    _official_sr(factory, "44000104")
    run2 = _seed_validating_run(factory)
    seeded2 = _seed_observation(
        factory,
        run_id=run2,
        sr_no="44000104",
        row_hash="e" * 64,
        account_code="UNCLAIMED-1",
        customer_label="Label Only Customer",
    )
    fallback = _build(factory, run_id=run2, observation_id=str(seeded2["observation_id"]))
    assert fallback.matcher_explanation == "ACCOUNT_CODE_UNRESOLVED_NAME_CANDIDATE"
    assert fallback.proposals == ()


def test_customer_builder_keeps_shared_claim_and_name_conflict_ambiguous(initialized_database) -> None:
    factory = _factory(initialized_database)
    customer_service = CustomerReferenceService(factory)
    first = _customer(factory, name="Shared One", account_code="SHARED-1")
    second = _customer(factory, name="Shared Two")
    preview = customer_service.preview_account_code_review(
        raw_account_code="SHARED-1",
        proposed_action="CONFIRM_SHARED_CLAIM",
        target_customer_org_id=second.customer_org_id,
    )
    customer_service.confirm_customer_account_code_shared_claim(
        command_id=new_uuid4(),
        customer_org_id=second.customer_org_id,
        base_revision=1,
        account_code="SHARED-1",
        review_snapshot_hash=preview.review_snapshot_hash,
        reason_category="test_shared_claim",
    )
    assert first.customer_org_id != second.customer_org_id
    _official_sr(factory, "44000105")
    run_id = _seed_validating_run(factory)
    seeded = _seed_observation(
        factory,
        run_id=run_id,
        sr_no="44000105",
        row_hash="f" * 64,
        account_code="SHARED-1",
        customer_label=None,
    )
    ambiguous = _build(factory, run_id=run_id, observation_id=str(seeded["observation_id"]))
    assert ambiguous.resolution_state == "ambiguous"
    assert ambiguous.matcher_explanation == "ACCOUNT_CODE_MULTIPLE_CLAIMS"
    assert ambiguous.proposals == ()

    code_target = _customer(factory, name="Code Target", account_code="CODE-1")
    label_target = _customer(factory, name="Label Target")
    assert code_target.customer_org_id != label_target.customer_org_id
    _official_sr(factory, "44000106")
    run2 = _seed_validating_run(factory)
    seeded2 = _seed_observation(
        factory,
        run_id=run2,
        sr_no="44000106",
        row_hash="0" * 64,
        account_code="CODE-1",
        customer_label="Label Target",
    )
    conflict = _build(factory, run_id=run2, observation_id=str(seeded2["observation_id"]))
    assert conflict.resolution_state == "ambiguous"
    assert conflict.matcher_explanation == "ACCOUNT_CODE_NAME_CONFLICT"
    assert conflict.proposals == ()


def _seed_minimal_proposal(
    factory,
    *,
    run_id: str,
    observation_id: str,
    sr_id: str,
    sr_no: str,
    risk_class: str,
) -> str:
    proposal_id = new_uuid4()
    with UnitOfWork(factory) as uow:
        uow.connection.execute(
            "INSERT INTO reconciliation_proposals(reconciliation_proposal_id,import_run_id,evidence_mode,source_observation_id,"
            "prior_source_observation_id,proposal_kind,target_kind,target_internal_id,target_business_id,risk_class,"
            "base_state_token_sha256,proposal_fingerprint_sha256,proposal_state,created_at_utc,revision,decided_at_utc) "
            "VALUES (?,?,'observed_row',?,NULL,'sr_customer_reconciliation','service_request',?,?,?,? ,?,'pending',1,1,NULL)",
            (proposal_id, run_id, observation_id, sr_id, sr_no, risk_class, "4" * 64, "5" * 64),
        )
    return proposal_id


def test_customer_acceptance_provider_rejects_label_only_and_low_risk_evidence(initialized_database) -> None:
    factory = _factory(initialized_database)
    label_target = _customer(factory, name="Label Authority")
    sr = _official_sr(factory, "44000107")
    run_id = _seed_validating_run(factory)
    label_source = _seed_observation(
        factory,
        run_id=run_id,
        sr_no="44000107",
        row_hash="6" * 64,
        account_code=None,
        customer_label="Label Authority",
    )
    label_proposal = _seed_minimal_proposal(
        factory,
        run_id=run_id,
        observation_id=str(label_source["observation_id"]),
        sr_id=sr.service_request_id,
        sr_no="44000107",
        risk_class="high",
    )
    provider = TicketImportSrCustomerReconciliationProvider()
    with ReadSnapshot(factory) as snapshot, pytest.raises(SomaError) as excinfo:
        provider.revalidate_reviewed_candidate(
            snapshot.connection,
            proposal_id=label_proposal,
            expected_import_run_id=run_id,
            source_observation_id=str(label_source["observation_id"]),
            service_request_id=sr.service_request_id,
            canonical_sr_no="44000107",
            field_key="customer_org_id",
            change_kind="set",
            value_kind="identity",
            before_text=None,
            after_text=label_target.customer_org_id,
            before_integer=None,
            after_integer=None,
            source_observation_field_id=str(label_source["label_field_id"]),
        )
    assert excinfo.value.code == "IMPORT_PROPOSAL_STALE"

    code_target = _customer(factory, name="Code Authority", account_code="CODE-AUTH")
    sr2 = _official_sr(factory, "44000108")
    run2 = _seed_validating_run(factory)
    code_source = _seed_observation(
        factory,
        run_id=run2,
        sr_no="44000108",
        row_hash="7" * 64,
        account_code="CODE-AUTH",
        customer_label="Code Authority",
    )
    low_risk_proposal = _seed_minimal_proposal(
        factory,
        run_id=run2,
        observation_id=str(code_source["observation_id"]),
        sr_id=sr2.service_request_id,
        sr_no="44000108",
        risk_class="medium",
    )
    with ReadSnapshot(factory) as snapshot, pytest.raises(SomaError) as excinfo2:
        provider.revalidate_reviewed_candidate(
            snapshot.connection,
            proposal_id=low_risk_proposal,
            expected_import_run_id=run2,
            source_observation_id=str(code_source["observation_id"]),
            service_request_id=sr2.service_request_id,
            canonical_sr_no="44000108",
            field_key="customer_org_id",
            change_kind="set",
            value_kind="identity",
            before_text=None,
            after_text=code_target.customer_org_id,
            before_integer=None,
            after_integer=None,
            source_observation_field_id=str(code_source["account_field_id"]),
        )
    assert excinfo2.value.code == "IMPORT_PROPOSAL_STALE"
