from __future__ import annotations

import json

import pytest

from soma.foundation.errors import SomaError
from soma.foundation.identifiers import new_uuid4
from soma.foundation.persistence.uow import ReadSnapshot, UnitOfWork
from soma.reference.application.contact_service import ContactReferenceService
from soma.ticket_import.commands.decide_proposal import ProposalDecisionService
from soma.tickets.import_mutations import ServiceRequestImportMutationService
from soma.tickets.service_requests import ServiceRequestService


def _factory(initialized_database):
    database_path, factory_for_path = initialized_database
    return factory_for_path(database_path)


def _official_sr(factory, sr_no: str):
    return ServiceRequestService(factory).create_manual_service_request(
        command_id=new_uuid4(),
        official_sr_no=sr_no,
    )


def _contact(factory, name: str):
    return ContactReferenceService(factory).create_contact(
        command_id=new_uuid4(),
        name=name,
    )


def _source_base_token(factory, service_request_id: str) -> str:
    with ReadSnapshot(factory) as snapshot:
        return ServiceRequestImportMutationService.source_acceptance_base_token(
            snapshot.connection,
            service_request_id,
        )


def _contact_base_token(
    factory,
    *,
    service_request_id: str,
    reference_role: str,
    target_contact_id: str,
    source_observation_field_id: str,
) -> str:
    with ReadSnapshot(factory) as snapshot:
        return ServiceRequestImportMutationService.contact_reconciliation_base_token(
            snapshot.connection,
            service_request_id,
            reference_role,
            target_contact_id,
            source_observation_field_id,
        )


def _insert_run_observation_field(
    factory,
    *,
    sr_no: str,
    field_key: str,
    label: str,
    proposal_count: int = 1,
):
    run_id = new_uuid4()
    observation_id = new_uuid4()
    field_id = new_uuid4()
    with UnitOfWork(factory) as uow:
        uow.connection.execute(
            "INSERT INTO import_runs("
            "import_run_id,source_family,invocation_kind,source_profile_id,header_registry_id,vocabulary_registry_id,parser_profile_id,"
            "candidate_filename,candidate_file_size_bytes,candidate_stable_mtime_ns,candidate_chronology_kind,candidate_chronology_value,"
            "logical_fingerprint_sha256,run_state,started_at_utc,staged_at_utc,observed_row_count,valid_identity_count,"
            "proposal_count,pending_proposal_count,revision"
            ") VALUES (?, 'advanced_search_sr','manual','ADVANCED_SEARCH_SR_V1','ADVANCED_SEARCH_HEADERS_V1',"
            "'ADVANCED_SEARCH_VOCAB_V1','ADVANCED_SEARCH_PARSER_V1','Advanced Search(Service Request)20260910010000.xlsx',"
            "100,1,'embedded_filename_timestamp_utc',400,?,'waiting_review',0,1,1,1,?,?,1)",
            (run_id, "1" * 64, proposal_count, proposal_count),
        )
        uow.connection.execute(
            "INSERT INTO source_observations(source_observation_id,import_run_id,source_family,entity_kind,identity_state,"
            "canonical_primary_id,canonical_parent_rfc_no,row_ordinal,sheet_ordinal,row_logical_sha256,source_row_chronology_utc,"
            "presence_state,recorded_at_utc) VALUES (?,?,'advanced_search_sr','service_request','valid',?,NULL,1,1,?,400,"
            "'observed_valid_identity',1)",
            (observation_id, run_id, sr_no, "2" * 64),
        )
        uow.connection.execute(
            "INSERT INTO source_observation_fields(source_observation_field_id,source_observation_id,field_key,field_class,"
            "value_state,value_kind,source_text,normalized_text,integer_value,vocabulary_id,field_logical_sha256) "
            "VALUES (?,?,?,'active','usable','text',?,?,NULL,NULL,?)",
            (field_id, observation_id, field_key, label, label, "3" * 64),
        )
    return run_id, observation_id, field_id


def _seed_source_handler_projection(factory, *, service_request_id: str, sr_no: str, label: str):
    base_token = _source_base_token(factory, service_request_id)
    run_id, observation_id, field_id = _insert_run_observation_field(
        factory,
        sr_no=sr_no,
        field_key="current_handler_label",
        label=label,
    )
    proposal_id = new_uuid4()
    fingerprint = "4" * 64
    with UnitOfWork(factory) as uow:
        uow.connection.execute(
            "INSERT INTO reconciliation_proposals(reconciliation_proposal_id,import_run_id,evidence_mode,source_observation_id,"
            "prior_source_observation_id,proposal_kind,target_kind,target_internal_id,target_business_id,risk_class,"
            "base_state_token_sha256,proposal_fingerprint_sha256,proposal_state,created_at_utc,revision,decided_at_utc) "
            "VALUES (?,?,'observed_row',?,NULL,'sr_source_projection','service_request',?,?,'medium',?,?,'pending',1,1,NULL)",
            (proposal_id, run_id, observation_id, service_request_id, sr_no, base_token, fingerprint),
        )
        uow.connection.execute(
            "INSERT INTO reconciliation_proposal_changes(reconciliation_proposal_id,ordinal,field_key,change_kind,value_kind,"
            "before_text,after_text,before_integer,after_integer,source_observation_field_id) "
            "VALUES (?,0,'current_handler_label','set','text',NULL,?,NULL,NULL,?)",
            (proposal_id, label, field_id),
        )
    result = ProposalDecisionService(factory).accept(
        command_id=new_uuid4(),
        proposal_id=proposal_id,
        proposal_revision=1,
        proposal_fingerprint=fingerprint,
        base_state_token=base_token,
        reason_category="accepted_handler_source",
    )
    assert result.decision == "accepted"
    assert len(result.owner_result_refs) == 1
    owner_observation_id = result.owner_result_refs[0][1]
    return {
        "run_id": run_id,
        "source_observation_id": observation_id,
        "source_observation_field_id": field_id,
        "owner_observation_id": owner_observation_id,
    }


def _seed_contact_proposal(
    factory,
    *,
    service_request_id: str,
    sr_no: str,
    proposal_kind: str,
    reference_role: str,
    target_contact_id: str,
    label: str,
    prior_contact_id: str | None = None,
    support_field_id: str | None = None,
):
    source_field_key = (
        "customer_contact_label" if reference_role == "customer_contact" else "current_handler_label"
    )
    run_id, observation_id, current_field_id = _insert_run_observation_field(
        factory,
        sr_no=sr_no,
        field_key=source_field_key,
        label=label,
    )
    effective_support_id = current_field_id if support_field_id is None else support_field_id
    base_token = _contact_base_token(
        factory,
        service_request_id=service_request_id,
        reference_role=reference_role,
        target_contact_id=target_contact_id,
        source_observation_field_id=effective_support_id,
    )
    proposal_id = new_uuid4()
    fingerprint = "5" * 64
    with UnitOfWork(factory) as uow:
        uow.connection.execute(
            "INSERT INTO reconciliation_proposals(reconciliation_proposal_id,import_run_id,evidence_mode,source_observation_id,"
            "prior_source_observation_id,proposal_kind,target_kind,target_internal_id,target_business_id,risk_class,"
            "base_state_token_sha256,proposal_fingerprint_sha256,proposal_state,created_at_utc,revision,decided_at_utc) "
            "VALUES (?,?,'observed_row',?,NULL,?,'service_request',?,?,'high',?,?,'pending',1,1,NULL)",
            (
                proposal_id,
                run_id,
                observation_id,
                proposal_kind,
                service_request_id,
                sr_no,
                base_token,
                fingerprint,
            ),
        )
        uow.connection.execute(
            "INSERT INTO reconciliation_proposal_changes(reconciliation_proposal_id,ordinal,field_key,change_kind,value_kind,"
            "before_text,after_text,before_integer,after_integer,source_observation_field_id) "
            "VALUES (?,0,'contact_id','set','identity',?,?,NULL,NULL,?)",
            (proposal_id, prior_contact_id, target_contact_id, effective_support_id),
        )
    return {
        "run_id": run_id,
        "source_observation_id": observation_id,
        "current_source_field_id": current_field_id,
        "support_field_id": effective_support_id,
        "proposal_id": proposal_id,
        "fingerprint": fingerprint,
        "base_token": base_token,
    }


def _accept(factory, seeded, *, command_id: str | None = None):
    actual_command_id = new_uuid4() if command_id is None else command_id
    result = ProposalDecisionService(factory).accept(
        command_id=actual_command_id,
        proposal_id=seeded["proposal_id"],
        proposal_revision=1,
        proposal_fingerprint=seeded["fingerprint"],
        base_state_token=seeded["base_token"],
        reason_category="reviewed_contact_reconciliation",
    )
    return actual_command_id, result


def test_customer_contact_acceptance_preserves_history_and_exact_replay(initialized_database) -> None:
    factory = _factory(initialized_database)
    sr = _official_sr(factory, "44000001")
    target = _contact(factory, "Customer Contact Alpha")
    seeded = _seed_contact_proposal(
        factory,
        service_request_id=sr.service_request_id,
        sr_no="44000001",
        proposal_kind="sr_contact_reconciliation",
        reference_role="customer_contact",
        target_contact_id=target.contact_id,
        label="Customer Contact Alpha",
    )
    command_id = new_uuid4()
    service = ProposalDecisionService(factory)
    result = service.accept(
        command_id=command_id,
        proposal_id=seeded["proposal_id"],
        proposal_revision=1,
        proposal_fingerprint=seeded["fingerprint"],
        base_state_token=seeded["base_token"],
        reason_category="reviewed_customer_contact",
    )

    assert result.decision == "accepted"
    assert result.revision == 2
    assert result.replayed is False
    assert len(result.owner_result_refs) == 1
    assert result.owner_result_refs[0][0] == "service_request_contact_history"
    with ReadSnapshot(factory) as snapshot:
        relationship = snapshot.connection.execute(
            "SELECT reference_role,contact_id,customer_org_context_id,relationship_state,origin_kind,"
            "reconciliation_proposal_id,supporting_sr_source_field_observation_id,opened_command_id "
            "FROM sr_contact_relationships WHERE service_request_id=?",
            (sr.service_request_id,),
        ).fetchone()
        assert tuple(relationship) == (
            "customer_contact",
            target.contact_id,
            None,
            "active",
            "advanced_search_review",
            seeded["proposal_id"],
            None,
            command_id,
        )
        assert snapshot.connection.execute(
            "SELECT revision FROM service_requests WHERE service_request_id=?",
            (sr.service_request_id,),
        ).fetchone()[0] == 2
        assert snapshot.connection.execute(
            "SELECT proposal_state,revision FROM reconciliation_proposals WHERE reconciliation_proposal_id=?",
            (seeded["proposal_id"],),
        ).fetchone() == ("accepted", 2)
        assert snapshot.connection.execute(
            "SELECT pending_proposal_count,accepted_proposal_count,revision FROM import_runs WHERE import_run_id=?",
            (seeded["run_id"],),
        ).fetchone() == (0, 1, 2)
        audits = snapshot.connection.execute(
            "SELECT action_type,payload_json FROM audit_events WHERE command_id=? ORDER BY action_type",
            (command_id,),
        ).fetchall()
        assert [str(row[0]) for row in audits] == [
            "ticket.service_request.contact_reference_changed",
            "ticket_import.proposal_decided",
        ]
        payload = json.loads(str(audits[0][1]))
        assert payload["reference_role"] == "customer_contact"
        assert payload["new_reference_id"] == target.contact_id
        assert payload["source_observation_id"] == seeded["source_observation_id"]
        assert "Customer Contact Alpha" not in "\n".join(str(row[1]) for row in audits)

    replay = service.accept(
        command_id=command_id,
        proposal_id=seeded["proposal_id"],
        proposal_revision=1,
        proposal_fingerprint=seeded["fingerprint"],
        base_state_token=seeded["base_token"],
        reason_category="reviewed_customer_contact",
    )
    assert replay.replayed is True
    assert replay.owner_result_refs == result.owner_result_refs
    with ReadSnapshot(factory) as snapshot:
        assert snapshot.connection.execute(
            "SELECT COUNT(*) FROM sr_contact_relationships WHERE service_request_id=?",
            (sr.service_request_id,),
        ).fetchone()[0] == 1
        assert snapshot.connection.execute(
            "SELECT COUNT(*) FROM proposal_dispositions WHERE reconciliation_proposal_id=?",
            (seeded["proposal_id"],),
        ).fetchone()[0] == 1
        assert snapshot.connection.execute(
            "SELECT COUNT(*) FROM command_receipts WHERE command_id=?",
            (command_id,),
        ).fetchone()[0] == 1


def test_current_handler_contact_accepts_equal_later_import_without_redundant_source_observation(
    initialized_database,
) -> None:
    factory = _factory(initialized_database)
    sr = _official_sr(factory, "44000002")
    prior = _seed_source_handler_projection(
        factory,
        service_request_id=sr.service_request_id,
        sr_no="44000002",
        label="Handler Alpha",
    )
    target = _contact(factory, "Handler Alpha")
    seeded = _seed_contact_proposal(
        factory,
        service_request_id=sr.service_request_id,
        sr_no="44000002",
        proposal_kind="sr_current_handler_reconciliation",
        reference_role="current_handler_reference",
        target_contact_id=target.contact_id,
        label="Handler Alpha",
        support_field_id=prior["source_observation_field_id"],
    )
    assert seeded["current_source_field_id"] != seeded["support_field_id"]

    command_id, result = _accept(factory, seeded)
    assert result.decision == "accepted"
    assert result.replayed is False
    with ReadSnapshot(factory) as snapshot:
        projection = snapshot.connection.execute(
            "SELECT current_handler_observation_id FROM sr_current_source_projection WHERE service_request_id=?",
            (sr.service_request_id,),
        ).fetchone()
        assert projection[0] == prior["owner_observation_id"]
        assert snapshot.connection.execute(
            "SELECT COUNT(*) FROM sr_source_field_observations WHERE service_request_id=? "
            "AND field_key='current_handler_label'",
            (sr.service_request_id,),
        ).fetchone()[0] == 1
        relationship = snapshot.connection.execute(
            "SELECT reference_role,contact_id,origin_kind,reconciliation_proposal_id,"
            "supporting_sr_source_field_observation_id,opened_command_id "
            "FROM sr_contact_relationships WHERE service_request_id=? AND reference_role='current_handler_reference'",
            (sr.service_request_id,),
        ).fetchone()
        assert tuple(relationship) == (
            "current_handler_reference",
            target.contact_id,
            "advanced_search_review",
            seeded["proposal_id"],
            prior["owner_observation_id"],
            command_id,
        )


def test_new_same_name_contact_after_review_makes_candidate_stale_without_receipt(initialized_database) -> None:
    factory = _factory(initialized_database)
    sr = _official_sr(factory, "44000003")
    target = _contact(factory, "Ambiguity Candidate")
    seeded = _seed_contact_proposal(
        factory,
        service_request_id=sr.service_request_id,
        sr_no="44000003",
        proposal_kind="sr_contact_reconciliation",
        reference_role="customer_contact",
        target_contact_id=target.contact_id,
        label="Ambiguity Candidate",
    )
    _contact(factory, "Ambiguity Candidate")
    command_id = new_uuid4()

    with pytest.raises(SomaError) as excinfo:
        ProposalDecisionService(factory).accept(
            command_id=command_id,
            proposal_id=seeded["proposal_id"],
            proposal_revision=1,
            proposal_fingerprint=seeded["fingerprint"],
            base_state_token=seeded["base_token"],
            reason_category="reviewed_customer_contact",
        )
    assert excinfo.value.code == "IMPORT_PROPOSAL_STALE"
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
            "SELECT COUNT(*) FROM sr_contact_relationships WHERE service_request_id=?",
            (sr.service_request_id,),
        ).fetchone()[0] == 0


def test_current_handler_import_label_must_equal_accepted_support_evidence(initialized_database) -> None:
    factory = _factory(initialized_database)
    sr = _official_sr(factory, "44000004")
    prior = _seed_source_handler_projection(
        factory,
        service_request_id=sr.service_request_id,
        sr_no="44000004",
        label="Accepted Handler",
    )
    target = _contact(factory, "Different Current Handler")
    seeded = _seed_contact_proposal(
        factory,
        service_request_id=sr.service_request_id,
        sr_no="44000004",
        proposal_kind="sr_current_handler_reconciliation",
        reference_role="current_handler_reference",
        target_contact_id=target.contact_id,
        label="Different Current Handler",
        support_field_id=prior["source_observation_field_id"],
    )
    command_id = new_uuid4()

    with pytest.raises(SomaError) as excinfo:
        ProposalDecisionService(factory).accept(
            command_id=command_id,
            proposal_id=seeded["proposal_id"],
            proposal_revision=1,
            proposal_fingerprint=seeded["fingerprint"],
            base_state_token=seeded["base_token"],
            reason_category="reviewed_current_handler",
        )
    assert excinfo.value.code == "IMPORT_PROPOSAL_STALE"
    with ReadSnapshot(factory) as snapshot:
        assert snapshot.connection.execute(
            "SELECT 1 FROM command_receipts WHERE command_id=?",
            (command_id,),
        ).fetchone() is None
        assert snapshot.connection.execute(
            "SELECT COUNT(*) FROM sr_contact_relationships WHERE service_request_id=?",
            (sr.service_request_id,),
        ).fetchone()[0] == 0


class _FailAfterReceiptContactOwner:
    @staticmethod
    def contact_reconciliation_base_token(
        reader,
        service_request_id: str,
        reference_role: str,
        target_contact_id: str,
        source_observation_field_id: str,
    ) -> str:
        return ServiceRequestImportMutationService.contact_reconciliation_base_token(
            reader,
            service_request_id,
            reference_role,
            target_contact_id,
            source_observation_field_id,
        )

    @staticmethod
    def set_customer_contact_from_review(uow: UnitOfWork, mutation):
        assert uow.connection.execute(
            "SELECT 1 FROM command_receipts WHERE command_id=?",
            (mutation.accepted_command_id,),
        ).fetchone() is not None
        uow.connection.execute(
            "UPDATE service_requests SET revision=revision+1 WHERE service_request_id=?",
            (mutation.service_request_id,),
        )
        raise SomaError("INJECTED_OWNER_FAILURE", "failure after Contact owner write")

    @staticmethod
    def set_current_handler_contact_reference_from_review(uow: UnitOfWork, mutation):
        return _FailAfterReceiptContactOwner.set_customer_contact_from_review(uow, mutation)


def test_contact_owner_failure_after_receipt_rolls_back_entire_acceptance(initialized_database) -> None:
    factory = _factory(initialized_database)
    sr = _official_sr(factory, "44000005")
    target = _contact(factory, "Rollback Contact")
    seeded = _seed_contact_proposal(
        factory,
        service_request_id=sr.service_request_id,
        sr_no="44000005",
        proposal_kind="sr_contact_reconciliation",
        reference_role="customer_contact",
        target_contact_id=target.contact_id,
        label="Rollback Contact",
    )
    command_id = new_uuid4()
    service = ProposalDecisionService(
        factory,
        sr_import_mutation_service=_FailAfterReceiptContactOwner(),
    )

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
            "SELECT revision FROM service_requests WHERE service_request_id=?",
            (sr.service_request_id,),
        ).fetchone()[0] == 1
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
            "SELECT COUNT(*) FROM sr_contact_relationships WHERE service_request_id=?",
            (sr.service_request_id,),
        ).fetchone()[0] == 0
