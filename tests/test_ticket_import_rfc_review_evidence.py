from __future__ import annotations

import pytest

from soma.foundation.errors import SomaError
from soma.foundation.identifiers import new_uuid4
from soma.foundation.persistence.uow import UnitOfWork
from soma.reference.application.customer_service import CustomerReferenceService
from soma.ticket_import.providers.rfc_review_evidence import TicketImportRfcReviewEvidenceProvider
from soma.tickets.service_requests import ServiceRequestService


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


def _seed_published_field(
    factory,
    *,
    rfc_no: str,
    field_key: str,
    value: str,
) -> tuple[str, str, str]:
    run_id = new_uuid4()
    observation_id = new_uuid4()
    field_id = new_uuid4()
    with UnitOfWork(factory) as uow:
        uow.connection.execute(
            "INSERT INTO import_runs("
            "import_run_id,source_family,invocation_kind,source_profile_id,header_registry_id,vocabulary_registry_id,parser_profile_id,"
            "candidate_filename,candidate_file_size_bytes,candidate_stable_mtime_ns,candidate_chronology_kind,candidate_chronology_value,"
            "logical_fingerprint_sha256,run_state,started_at_utc,staged_at_utc,published_at_utc,observed_row_count,valid_identity_count,"
            "proposal_count,pending_proposal_count,revision"
            ") VALUES (?, 'rfc_enhanced','manual','RFC_ENHANCED_V1','RFC_HEADERS_V1','RFC_VOCAB_V1','RFC_PARSER_V1',"
            "'operator-rfc.xlsx',100,1,'filesystem_mtime_ns',200,?,'waiting_review',0,1,2,1,1,0,0,1)",
            (run_id, "1" * 64),
        )
        uow.connection.execute(
            "INSERT INTO source_observations(source_observation_id,import_run_id,source_family,entity_kind,identity_state,"
            "canonical_primary_id,canonical_parent_rfc_no,row_ordinal,sheet_ordinal,row_logical_sha256,source_row_chronology_utc,"
            "presence_state,recorded_at_utc) VALUES (?,?,'rfc_enhanced','rfc','valid',?,NULL,1,1,?,200,"
            "'observed_valid_identity',1)",
            (observation_id, run_id, rfc_no, "a" * 64),
        )
        uow.connection.execute(
            "INSERT INTO source_observation_fields(source_observation_field_id,source_observation_id,field_key,field_class,"
            "value_state,value_kind,source_text,normalized_text,integer_value,vocabulary_id,field_logical_sha256) "
            "VALUES (?, ?, ?, 'active','usable','text',?,?,NULL,NULL,?)",
            (field_id, observation_id, field_key, value, value, "b" * 64),
        )
    return run_id, observation_id, field_id


def test_customer_review_evidence_revalidates_exact_account_match(initialized_database) -> None:
    factory = _factory(initialized_database)
    customer = CustomerReferenceService(factory).create_customer_organization(
        command_id=new_uuid4(),
        name="Target Customer",
        account_code="RFC-ACC-300",
    )
    rfc_no = "NC20260917000031"
    rfc_id = _seed_rfc(factory, rfc_no)
    run_id, observation_id, field_id = _seed_published_field(
        factory,
        rfc_no=rfc_no,
        field_key="customer_account_number",
        value="RFC-ACC-300",
    )
    provider = TicketImportRfcReviewEvidenceProvider()
    with UnitOfWork(factory) as uow:
        candidate = provider.revalidate_customer_candidate(
            uow.connection,
            expected_import_run_id=run_id,
            expected_source_observation_id=observation_id,
            rfc_id=rfc_id,
            rfc_no=rfc_no,
            source_observation_field_id=field_id,
            expected_customer_org_id=customer.customer_org_id,
        )
    assert candidate.customer_org_id == customer.customer_org_id
    assert candidate.account_code == "RFC-ACC-300"
    assert candidate.current_customer_org_id is None


def test_customer_review_evidence_fails_when_account_match_becomes_ambiguous(initialized_database) -> None:
    factory = _factory(initialized_database)
    customer_service = CustomerReferenceService(factory)
    first = customer_service.create_customer_organization(
        command_id=new_uuid4(),
        name="First",
        account_code="RFC-SHARED-1",
    )
    second = customer_service.create_customer_organization(
        command_id=new_uuid4(),
        name="Second",
    )
    rfc_no = "NC20260917000032"
    rfc_id = _seed_rfc(factory, rfc_no)
    run_id, observation_id, field_id = _seed_published_field(
        factory,
        rfc_no=rfc_no,
        field_key="customer_account_number",
        value="RFC-SHARED-1",
    )
    preview = customer_service.preview_account_code_review(
        raw_account_code="RFC-SHARED-1",
        proposed_action="CONFIRM_SHARED_CLAIM",
        target_customer_org_id=second.customer_org_id,
    )
    customer_service.confirm_customer_account_code_shared_claim(
        command_id=new_uuid4(),
        customer_org_id=second.customer_org_id,
        base_revision=1,
        account_code="RFC-SHARED-1",
        review_snapshot_hash=preview.review_snapshot_hash,
        reason_category="test_shared_claim",
    )
    provider = TicketImportRfcReviewEvidenceProvider()
    with pytest.raises(SomaError) as exc_info:
        with UnitOfWork(factory) as uow:
            provider.revalidate_customer_candidate(
                uow.connection,
                expected_import_run_id=run_id,
                expected_source_observation_id=observation_id,
                rfc_id=rfc_id,
                rfc_no=rfc_no,
                source_observation_field_id=field_id,
                expected_customer_org_id=first.customer_org_id,
            )
    assert exc_info.value.code == "IMPORT_PROPOSAL_STALE"


def test_sr_link_review_evidence_revalidates_summary_candidate(initialized_database) -> None:
    factory = _factory(initialized_database)
    sr = ServiceRequestService(factory).create_manual_service_request(
        command_id=new_uuid4(),
        official_sr_no="67890123",
    )
    rfc_no = "NC20260917000033"
    rfc_id = _seed_rfc(factory, rfc_no)
    run_id, observation_id, field_id = _seed_published_field(
        factory,
        rfc_no=rfc_no,
        field_key="summary",
        value="Maintenance for TT 67890123; date 20260917",
    )
    provider = TicketImportRfcReviewEvidenceProvider()
    with UnitOfWork(factory) as uow:
        candidate = provider.revalidate_sr_link_candidate(
            uow.connection,
            expected_import_run_id=run_id,
            expected_source_observation_id=observation_id,
            requested_rfc_id=rfc_id,
            rfc_no=rfc_no,
            source_observation_field_id=field_id,
            service_request_id=sr.service_request_id,
        )
    assert candidate.service_request_id == sr.service_request_id
    assert candidate.official_sr_no == "67890123"
