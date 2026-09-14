from __future__ import annotations

import pytest

from soma.foundation.errors import SomaError
from soma.foundation.identifiers import new_uuid4
from soma.foundation.persistence.uow import ReadSnapshot, UnitOfWork
from soma.reference.application.contact_service import ContactReferenceService
from soma.reference.application.customer_service import CustomerReferenceService
from soma.ticket_import.commands.decide_proposal import ProposalDecisionService
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


def test_customer_contact_acceptance_rejects_non_high_risk_before_receipt(initialized_database) -> None:
    factory = _factory(initialized_database)
    customer = CustomerReferenceService(factory).create_customer_organization(
        command_id=new_uuid4(),
        name="Risk Customer",
    )
    contact = ContactReferenceService(factory).create_contact(
        command_id=new_uuid4(),
        name="Risk Contact",
        initial_customer_org_id=customer.customer_org_id,
    )
    sr = ServiceRequestService(factory).create_manual_service_request(
        command_id=new_uuid4(),
        official_sr_no="44000220",
    )
    ServiceRequestReferenceService(factory, _NoopClassificationParticipant()).set_customer(
        command_id=new_uuid4(),
        service_request_id=sr.service_request_id,
        base_revision=1,
        customer_org_id=customer.customer_org_id,
        reason_category="risk_scope",
    )

    run_id = new_uuid4()
    observation_id = new_uuid4()
    field_id = new_uuid4()
    proposal_id = new_uuid4()
    fingerprint = "5" * 64
    with UnitOfWork(factory) as uow:
        uow.connection.execute(
            "INSERT INTO import_runs("
            "import_run_id,source_family,invocation_kind,source_profile_id,header_registry_id,vocabulary_registry_id,parser_profile_id,"
            "candidate_filename,candidate_file_size_bytes,candidate_stable_mtime_ns,candidate_chronology_kind,candidate_chronology_value,"
            "logical_fingerprint_sha256,run_state,started_at_utc,staged_at_utc,observed_row_count,valid_identity_count,"
            "proposal_count,pending_proposal_count,revision"
            ") VALUES (?, 'advanced_search_sr','manual','ADVANCED_SEARCH_SR_V1','ADVANCED_SEARCH_HEADERS_V1',"
            "'ADVANCED_SEARCH_VOCAB_V1','ADVANCED_SEARCH_PARSER_V1','Advanced Search(Service Request)20260913020000.xlsx',"
            "100,1,'embedded_filename_timestamp_utc',400,?,'waiting_review',0,1,1,1,1,1,1)",
            (run_id, "1" * 64),
        )
        uow.connection.execute(
            "INSERT INTO source_observations(source_observation_id,import_run_id,source_family,entity_kind,identity_state,"
            "canonical_primary_id,canonical_parent_rfc_no,row_ordinal,sheet_ordinal,row_logical_sha256,source_row_chronology_utc,"
            "presence_state,recorded_at_utc) VALUES (?,?,'advanced_search_sr','service_request','valid','44000220',NULL,1,1,?,400,"
            "'observed_valid_identity',1)",
            (observation_id, run_id, "2" * 64),
        )
        uow.connection.execute(
            "INSERT INTO source_observation_fields(source_observation_field_id,source_observation_id,field_key,field_class,"
            "value_state,value_kind,source_text,normalized_text,integer_value,vocabulary_id,field_logical_sha256) "
            "VALUES (?,?,'customer_contact_label','active','usable','text','Risk Contact','Risk Contact',NULL,NULL,?)",
            (field_id, observation_id, "3" * 64),
        )

    with ReadSnapshot(factory) as snapshot:
        base_token = ServiceRequestImportReader.contact_reconciliation_base_token(
            snapshot.connection,
            sr.service_request_id,
            "customer_contact",
            contact.contact_id,
            field_id,
        )

    with UnitOfWork(factory) as uow:
        uow.connection.execute(
            "INSERT INTO reconciliation_proposals(reconciliation_proposal_id,import_run_id,evidence_mode,source_observation_id,"
            "prior_source_observation_id,proposal_kind,target_kind,target_internal_id,target_business_id,risk_class,"
            "base_state_token_sha256,proposal_fingerprint_sha256,proposal_state,created_at_utc,revision,decided_at_utc) "
            "VALUES (?,?,'observed_row',?,NULL,'sr_contact_reconciliation','service_request',?,'44000220','medium',?,?,"
            "'pending',1,1,NULL)",
            (proposal_id, run_id, observation_id, sr.service_request_id, base_token, fingerprint),
        )
        uow.connection.execute(
            "INSERT INTO reconciliation_proposal_changes(reconciliation_proposal_id,ordinal,field_key,change_kind,value_kind,"
            "before_text,after_text,before_integer,after_integer,source_observation_field_id) "
            "VALUES (?,0,'contact_id','set','identity',NULL,?,NULL,NULL,?)",
            (proposal_id, contact.contact_id, field_id),
        )

    command_id = new_uuid4()
    with pytest.raises(SomaError) as excinfo:
        ProposalDecisionService(factory).accept(
            command_id=command_id,
            proposal_id=proposal_id,
            proposal_revision=1,
            proposal_fingerprint=fingerprint,
            base_state_token=base_token,
            reason_category="must_remain_high_risk",
        )
    assert excinfo.value.code == "IMPORT_PROPOSAL_STALE"

    with ReadSnapshot(factory) as snapshot:
        assert snapshot.connection.execute(
            "SELECT COUNT(*) FROM command_receipts WHERE command_id=?",
            (command_id,),
        ).fetchone()[0] == 0
        assert snapshot.connection.execute(
            "SELECT proposal_state,revision FROM reconciliation_proposals WHERE reconciliation_proposal_id=?",
            (proposal_id,),
        ).fetchone() == ("pending", 1)
        assert snapshot.connection.execute(
            "SELECT pending_proposal_count,accepted_proposal_count,revision FROM import_runs WHERE import_run_id=?",
            (run_id,),
        ).fetchone() == (1, 0, 1)
