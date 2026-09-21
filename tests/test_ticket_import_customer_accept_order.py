from __future__ import annotations

from dataclasses import dataclass

from soma.foundation.identifiers import new_uuid4
from soma.foundation.persistence.uow import ReadSnapshot, UnitOfWork
from soma.ticket_import.commands.decide_proposal import ProposalDecisionService
from soma.ticket_import.providers.sr_customer_reconciliation import ReviewedCustomerCandidate
from soma.tickets.import_mutations import ServiceRequestCustomerReviewResult
from soma.tickets.service_requests import ServiceRequestService


_BASE_TOKEN = "a" * 64
_PROPOSAL_FINGERPRINT = "b" * 64


class _OrderCheckingOwner:
    def __init__(self) -> None:
        self.observed_proposal_state: str | None = None
        self.observed_receipt = False

    def customer_reconciliation_base_token(self, reader, service_request_id: str, target_customer_org_id: str) -> str:
        return _BASE_TOKEN

    def set_customer_from_review(self, uow, mutation):
        row = uow.connection.execute(
            "SELECT proposal_state FROM reconciliation_proposals WHERE reconciliation_proposal_id=?",
            (mutation.reconciliation_proposal_id,),
        ).fetchone()
        self.observed_proposal_state = None if row is None else str(row[0])
        receipt = uow.connection.execute(
            "SELECT command_type,target_type,target_id FROM command_receipts WHERE command_id=?",
            (mutation.accepted_command_id,),
        ).fetchone()
        self.observed_receipt = receipt == (
            "AcceptReconciliationProposal",
            "reconciliation_proposal",
            mutation.reconciliation_proposal_id,
        )
        return ServiceRequestCustomerReviewResult(
            result_refs=(("service_request_customer_history", new_uuid4()),),
            audit_events=(),
            resulting_revision=2,
        )


@dataclass(frozen=True, slots=True)
class _CandidateProvider:
    customer_org_id: str
    source_observation_id: str

    def revalidate_reviewed_candidate(self, reader, **kwargs):
        return ReviewedCustomerCandidate(
            customer_org_id=self.customer_org_id,
            prior_customer_org_id=None,
            source_observation_id=self.source_observation_id,
            supporting_source_observation_field_id=new_uuid4(),
            matcher_explanation="TEST_EXACT",
        )


def test_customer_owner_runs_under_receipt_while_proposal_is_still_pending(initialized_database) -> None:
    database_path, factory_for_path = initialized_database
    factory = factory_for_path(database_path)
    sr = ServiceRequestService(factory).create_manual_service_request(
        command_id=new_uuid4(),
        official_sr_no="44556670",
    )
    run_id = new_uuid4()
    source_observation_id = new_uuid4()
    proposal_id = new_uuid4()
    target_customer_org_id = new_uuid4()

    with UnitOfWork(factory) as uow:
        uow.connection.execute(
            "INSERT INTO import_runs("
            "import_run_id,source_family,invocation_kind,source_profile_id,header_registry_id,vocabulary_registry_id,parser_profile_id,"
            "candidate_filename,candidate_file_size_bytes,candidate_stable_mtime_ns,candidate_chronology_kind,candidate_chronology_value,"
            "logical_fingerprint_sha256,run_state,started_at_utc,staged_at_utc,observed_row_count,valid_identity_count,"
            "proposal_count,pending_proposal_count,revision"
            ") VALUES (?, 'advanced_search_sr','manual','ADVANCED_SEARCH_SR_V1','ADVANCED_SEARCH_HEADERS_V1',"
            "'ADVANCED_SEARCH_VOCAB_V1','ADVANCED_SEARCH_PARSER_V1','Advanced Search(Service Request)20260908030000.xlsx',"
            "100,1,'embedded_filename_timestamp_utc',400,?,'waiting_review',0,1,1,1,1,1,1)",
            (run_id, "1" * 64),
        )
        uow.connection.execute(
            "INSERT INTO source_observations(source_observation_id,import_run_id,source_family,entity_kind,identity_state,"
            "canonical_primary_id,canonical_parent_rfc_no,row_ordinal,sheet_ordinal,row_logical_sha256,source_row_chronology_utc,"
            "presence_state,recorded_at_utc) VALUES (?,?,'advanced_search_sr','service_request','valid','44556670',NULL,1,1,?,100,"
            "'observed_valid_identity',1)",
            (source_observation_id, run_id, "2" * 64),
        )
        uow.connection.execute(
            "INSERT INTO reconciliation_proposals(reconciliation_proposal_id,import_run_id,evidence_mode,source_observation_id,"
            "prior_source_observation_id,proposal_kind,target_kind,target_internal_id,target_business_id,risk_class,"
            "base_state_token_sha256,proposal_fingerprint_sha256,proposal_state,created_at_utc,revision,decided_at_utc) "
            "VALUES (?,?,'observed_row',?,NULL,'sr_customer_reconciliation','service_request',?,'44556670','high',?,?,"
            "'pending',1,1,NULL)",
            (proposal_id, run_id, source_observation_id, sr.service_request_id, _BASE_TOKEN, _PROPOSAL_FINGERPRINT),
        )
        uow.connection.execute(
            "INSERT INTO reconciliation_proposal_changes(reconciliation_proposal_id,ordinal,field_key,change_kind,value_kind,"
            "before_text,after_text,before_integer,after_integer,source_observation_field_id) "
            "VALUES (?,0,'customer_org_id','set','identity',NULL,?,NULL,NULL,NULL)",
            (proposal_id, target_customer_org_id),
        )

    owner = _OrderCheckingOwner()
    service = ProposalDecisionService(factory, sr_import_mutation_service=owner)
    service._sr_customer_provider = _CandidateProvider(target_customer_org_id, source_observation_id)
    command_id = new_uuid4()

    result = service.accept(
        command_id=command_id,
        proposal_id=proposal_id,
        proposal_revision=1,
        proposal_fingerprint=_PROPOSAL_FINGERPRINT,
        base_state_token=_BASE_TOKEN,
        reason_category="reviewed_customer_reconciliation",
    )

    assert owner.observed_receipt is True
    assert owner.observed_proposal_state == "pending"
    assert result.decision == "accepted"
    with ReadSnapshot(factory) as snapshot:
        assert snapshot.connection.execute(
            "SELECT proposal_state,revision FROM reconciliation_proposals WHERE reconciliation_proposal_id=?",
            (proposal_id,),
        ).fetchone() == ("accepted", 2)
