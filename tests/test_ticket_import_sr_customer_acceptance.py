from __future__ import annotations

import json

import pytest

from soma.foundation.errors import SomaError
from soma.foundation.identifiers import new_uuid4
from soma.foundation.persistence.uow import ReadSnapshot, UnitOfWork
from soma.reference.application.customer_service import CustomerReferenceService
from soma.ticket_import.commands.decide_proposal import ProposalDecisionService
from soma.tickets.import_mutations import ServiceRequestImportMutationService
from soma.tickets.service_requests import ServiceRequestService
from soma.tickets.sr_references import ServiceRequestReferenceService


def _factory(initialized_database):
    database_path, factory_for_path = initialized_database
    return factory_for_path(database_path)


class FakeClassificationParticipant:
    def __init__(self, *, fail: bool = False) -> None:
        self.fail = fail
        self.apply_calls: list[tuple[str, str | None, dict[str, object]]] = []

    def preview_customer_change(self, reader, sr_id: str, new_customer_org_id: str | None):
        return {"impact": "none", "service_request_id": sr_id, "customer_org_id": new_customer_org_id}

    def apply_customer_change(self, uow, sr_id: str, new_customer_org_id: str | None, command_context):
        assert uow.connection.in_transaction
        if self.fail:
            raise RuntimeError("injected LLD-06 failure")
        self.apply_calls.append((sr_id, new_customer_org_id, dict(command_context)))
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


def _set_manual_customer(factory, *, sr_id: str, base_revision: int, customer_org_id: str, participant):
    return ServiceRequestReferenceService(factory, participant).set_customer(
        command_id=new_uuid4(),
        service_request_id=sr_id,
        base_revision=base_revision,
        customer_org_id=customer_org_id,
        reason_category="manual_customer_review",
    )


def _customer_base_token(factory, sr_id: str, target_customer_org_id: str) -> str:
    with ReadSnapshot(factory) as snapshot:
        return ServiceRequestImportMutationService.customer_reconciliation_base_token(
            snapshot.connection,
            sr_id,
            target_customer_org_id,
        )


def _seed_customer_proposal(
    factory,
    *,
    sr_id: str,
    sr_no: str,
    target_customer_org_id: str,
    prior_customer_org_id: str | None,
    account_code: str | None,
    customer_label: str | None,
    base_token: str | None = None,
    support: str = "strongest",
):
    run_id = new_uuid4()
    observation_id = new_uuid4()
    proposal_id = new_uuid4()
    fingerprint = "8" * 64
    token = _customer_base_token(factory, sr_id, target_customer_org_id) if base_token is None else base_token
    account_field_id = new_uuid4() if account_code is not None else None
    label_field_id = new_uuid4() if customer_label is not None else None
    supporting_id = account_field_id if account_field_id is not None else label_field_id
    if support == "label":
        supporting_id = label_field_id
    assert supporting_id is not None

    with UnitOfWork(factory) as uow:
        uow.connection.execute(
            "INSERT INTO import_runs("
            "import_run_id,source_family,invocation_kind,source_profile_id,header_registry_id,vocabulary_registry_id,parser_profile_id,"
            "candidate_filename,candidate_file_size_bytes,candidate_stable_mtime_ns,candidate_chronology_kind,candidate_chronology_value,"
            "logical_fingerprint_sha256,run_state,started_at_utc,staged_at_utc,observed_row_count,valid_identity_count,"
            "proposal_count,pending_proposal_count,revision"
            ") VALUES (?, 'advanced_search_sr','manual','ADVANCED_SEARCH_SR_V1','ADVANCED_SEARCH_HEADERS_V1',"
            "'ADVANCED_SEARCH_VOCAB_V1','ADVANCED_SEARCH_PARSER_V1','Advanced Search(Service Request)20260908020000.xlsx',"
            "100,1,'embedded_filename_timestamp_utc',300,?,'waiting_review',0,1,1,1,1,1,1)",
            (run_id, "1" * 64),
        )
        uow.connection.execute(
            "INSERT INTO source_observations(source_observation_id,import_run_id,source_family,entity_kind,identity_state,"
            "canonical_primary_id,canonical_parent_rfc_no,row_ordinal,sheet_ordinal,row_logical_sha256,source_row_chronology_utc,"
            "presence_state,recorded_at_utc) VALUES (?,?,'advanced_search_sr','service_request','valid',?,NULL,1,1,?,100,"
            "'observed_valid_identity',1)",
            (observation_id, run_id, sr_no, "2" * 64),
        )
        if account_field_id is not None and account_code is not None:
            uow.connection.execute(
                "INSERT INTO source_observation_fields(source_observation_field_id,source_observation_id,field_key,field_class,"
                "value_state,value_kind,source_text,normalized_text,integer_value,vocabulary_id,field_logical_sha256) "
                "VALUES (?,?,'customer_account_code','active','usable','text',?,?,NULL,NULL,?)",
                (account_field_id, observation_id, account_code, account_code, "3" * 64),
            )
        if label_field_id is not None and customer_label is not None:
            uow.connection.execute(
                "INSERT INTO source_observation_fields(source_observation_field_id,source_observation_id,field_key,field_class,"
                "value_state,value_kind,source_text,normalized_text,integer_value,vocabulary_id,field_logical_sha256) "
                "VALUES (?,?,'customer_org_label','active','usable','text',?,?,NULL,NULL,?)",
                (label_field_id, observation_id, customer_label, customer_label, "4" * 64),
            )
        uow.connection.execute(
            "INSERT INTO reconciliation_proposals(reconciliation_proposal_id,import_run_id,evidence_mode,source_observation_id,"
            "prior_source_observation_id,proposal_kind,target_kind,target_internal_id,target_business_id,risk_class,"
            "base_state_token_sha256,proposal_fingerprint_sha256,proposal_state,created_at_utc,revision,decided_at_utc) "
            "VALUES (?,?,'observed_row',?,NULL,'sr_customer_reconciliation','service_request',?,?,'high',?,?,'pending',1,1,NULL)",
            (proposal_id, run_id, observation_id, sr_id, sr_no, token, fingerprint),
        )
        uow.connection.execute(
            "INSERT INTO reconciliation_proposal_changes(reconciliation_proposal_id,ordinal,field_key,change_kind,value_kind,"
            "before_text,after_text,before_integer,after_integer,source_observation_field_id) "
            "VALUES (?,0,'customer_org_id','set','identity',?,?,NULL,NULL,?)",
            (proposal_id, prior_customer_org_id, target_customer_org_id, supporting_id),
        )
    return {
        "run_id": run_id,
        "observation_id": observation_id,
        "proposal_id": proposal_id,
        "fingerprint": fingerprint,
        "base_token": token,
        "account_field_id": account_field_id,
        "label_field_id": label_field_id,
    }


def test_accept_customer_reconciliation_preserves_history_audits_and_replay(initialized_database) -> None:
    factory = _factory(initialized_database)
    old_customer = _customer(factory, name="Old Customer", account_code="OLD-001")
    target = _customer(factory, name="Target Customer", account_code="ACC-200")
    sr = _official_sr(factory, "33445560")
    participant = FakeClassificationParticipant()
    _set_manual_customer(
        factory,
        sr_id=sr.service_request_id,
        base_revision=1,
        customer_org_id=old_customer.customer_org_id,
        participant=participant,
    )
    participant.apply_calls.clear()
    seeded = _seed_customer_proposal(
        factory,
        sr_id=sr.service_request_id,
        sr_no="33445560",
        target_customer_org_id=target.customer_org_id,
        prior_customer_org_id=old_customer.customer_org_id,
        account_code="ACC-200",
        customer_label="Target Customer",
    )
    command_id = new_uuid4()
    service = ProposalDecisionService(factory, sr_customer_classification_participant=participant)

    result = service.accept(
        command_id=command_id,
        proposal_id=seeded["proposal_id"],
        proposal_revision=1,
        proposal_fingerprint=seeded["fingerprint"],
        base_state_token=seeded["base_token"],
        reason_category="reviewed_customer_reconciliation",
    )
    assert result.decision == "accepted"
    assert result.revision == 2
    assert result.replayed is False
    assert len(result.owner_result_refs) == 1
    assert result.owner_result_refs[0][0] == "service_request_customer_history"
    assert participant.apply_calls == [
        (
            sr.service_request_id,
            target.customer_org_id,
            participant.apply_calls[0][2],
        )
    ]
    assert participant.apply_calls[0][2]["resulting_revision"] == 3
    assert participant.apply_calls[0][2]["reconciliation_proposal_id"] == seeded["proposal_id"]

    with ReadSnapshot(factory) as snapshot:
        rows = snapshot.connection.execute(
            "SELECT customer_org_id,relationship_state,origin_kind,reconciliation_proposal_id,opened_command_id "
            "FROM sr_customer_relationships WHERE service_request_id=? ORDER BY opened_at_utc,sr_customer_relationship_id",
            (sr.service_request_id,),
        ).fetchall()
        assert len(rows) == 2
        assert str(rows[0][0]) == old_customer.customer_org_id
        assert str(rows[0][1]) == "superseded"
        active = next(row for row in rows if str(row[1]) == "active")
        assert tuple(str(active[index]) for index in (0, 2, 3, 4)) == (
            target.customer_org_id,
            "advanced_search_review",
            seeded["proposal_id"],
            command_id,
        )
        assert snapshot.connection.execute(
            "SELECT revision FROM service_requests WHERE service_request_id=?",
            (sr.service_request_id,),
        ).fetchone()[0] == 3
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
            "ticket.service_request.customer_changed",
            "ticket_import.proposal_decided",
        ]
        serialized = "\n".join(str(row[1]) for row in audits)
        assert "ACC-200" not in serialized
        assert "Target Customer" not in serialized
        ticket_payload = json.loads(str(audits[0][1]))
        assert ticket_payload["prior_reference_id"] == old_customer.customer_org_id
        assert ticket_payload["new_reference_id"] == target.customer_org_id
        assert ticket_payload["source_observation_id"] == seeded["observation_id"]

    replay = service.accept(
        command_id=command_id,
        proposal_id=seeded["proposal_id"],
        proposal_revision=1,
        proposal_fingerprint=seeded["fingerprint"],
        base_state_token=seeded["base_token"],
        reason_category="reviewed_customer_reconciliation",
    )
    assert replay.replayed is True
    assert replay.owner_result_refs == result.owner_result_refs
    assert len(participant.apply_calls) == 1
    with ReadSnapshot(factory) as snapshot:
        assert snapshot.connection.execute(
            "SELECT COUNT(*) FROM sr_customer_relationships WHERE service_request_id=?",
            (sr.service_request_id,),
        ).fetchone()[0] == 2
        assert snapshot.connection.execute(
            "SELECT COUNT(*) FROM audit_events WHERE command_id=?",
            (command_id,),
        ).fetchone()[0] == 2


def test_customer_generation_drift_makes_proposal_stale_before_receipt(initialized_database) -> None:
    factory = _factory(initialized_database)
    target = _customer(factory, name="Generation Target", account_code="GEN-1")
    sr = _official_sr(factory, "33445561")
    seeded = _seed_customer_proposal(
        factory,
        sr_id=sr.service_request_id,
        sr_no="33445561",
        target_customer_org_id=target.customer_org_id,
        prior_customer_org_id=None,
        account_code="GEN-1",
        customer_label="Generation Target",
    )
    _customer(factory, name="Unrelated New Customer", account_code="GEN-OTHER")
    command_id = new_uuid4()

    with pytest.raises(SomaError) as excinfo:
        ProposalDecisionService(factory, sr_customer_classification_participant=FakeClassificationParticipant()).accept(
            command_id=command_id,
            proposal_id=seeded["proposal_id"],
            proposal_revision=1,
            proposal_fingerprint=seeded["fingerprint"],
            base_state_token=seeded["base_token"],
        )
    assert excinfo.value.code == "IMPORT_PROPOSAL_STALE"
    with ReadSnapshot(factory) as snapshot:
        assert snapshot.connection.execute("SELECT 1 FROM command_receipts WHERE command_id=?", (command_id,)).fetchone() is None
        assert snapshot.connection.execute(
            "SELECT proposal_state FROM reconciliation_proposals WHERE reconciliation_proposal_id=?",
            (seeded["proposal_id"],),
        ).fetchone()[0] == "pending"


def test_account_code_name_conflict_and_weaker_pointer_fail_closed(initialized_database) -> None:
    factory = _factory(initialized_database)
    target = _customer(factory, name="Code Target", account_code="CODE-77")
    _other = _customer(factory, name="Conflicting Label")
    sr = _official_sr(factory, "33445562")
    seeded = _seed_customer_proposal(
        factory,
        sr_id=sr.service_request_id,
        sr_no="33445562",
        target_customer_org_id=target.customer_org_id,
        prior_customer_org_id=None,
        account_code="CODE-77",
        customer_label="Conflicting Label",
    )
    command_id = new_uuid4()
    service = ProposalDecisionService(factory, sr_customer_classification_participant=FakeClassificationParticipant())
    with pytest.raises(SomaError) as excinfo:
        service.accept(
            command_id=command_id,
            proposal_id=seeded["proposal_id"],
            proposal_revision=1,
            proposal_fingerprint=seeded["fingerprint"],
            base_state_token=seeded["base_token"],
        )
    assert excinfo.value.code == "IMPORT_PROPOSAL_STALE"

    target2 = _customer(factory, name="Strong Pointer Target", account_code="CODE-88")
    sr2 = _official_sr(factory, "33445563")
    seeded2 = _seed_customer_proposal(
        factory,
        sr_id=sr2.service_request_id,
        sr_no="33445563",
        target_customer_org_id=target2.customer_org_id,
        prior_customer_org_id=None,
        account_code="CODE-88",
        customer_label="Strong Pointer Target",
        support="label",
    )
    command2 = new_uuid4()
    with pytest.raises(SomaError) as excinfo2:
        service.accept(
            command_id=command2,
            proposal_id=seeded2["proposal_id"],
            proposal_revision=1,
            proposal_fingerprint=seeded2["fingerprint"],
            base_state_token=seeded2["base_token"],
        )
    assert excinfo2.value.code == "IMPORT_PROPOSAL_STALE"
    with ReadSnapshot(factory) as snapshot:
        assert snapshot.connection.execute("SELECT 1 FROM command_receipts WHERE command_id IN (?,?) LIMIT 1", (command_id, command2)).fetchone() is None


def test_before_state_mismatch_after_staged_acceptance_rolls_everything_back(initialized_database) -> None:
    factory = _factory(initialized_database)
    actual = _customer(factory, name="Actual Prior", account_code="PRIOR-A")
    wrong = _customer(factory, name="Wrong Prior", account_code="PRIOR-B")
    target = _customer(factory, name="Next Customer", account_code="NEXT-1")
    sr = _official_sr(factory, "33445564")
    participant = FakeClassificationParticipant()
    _set_manual_customer(factory, sr_id=sr.service_request_id, base_revision=1, customer_org_id=actual.customer_org_id, participant=participant)
    seeded = _seed_customer_proposal(
        factory,
        sr_id=sr.service_request_id,
        sr_no="33445564",
        target_customer_org_id=target.customer_org_id,
        prior_customer_org_id=wrong.customer_org_id,
        account_code="NEXT-1",
        customer_label="Next Customer",
    )
    command_id = new_uuid4()
    with pytest.raises(SomaError) as excinfo:
        ProposalDecisionService(factory, sr_customer_classification_participant=participant).accept(
            command_id=command_id,
            proposal_id=seeded["proposal_id"],
            proposal_revision=1,
            proposal_fingerprint=seeded["fingerprint"],
            base_state_token=seeded["base_token"],
        )
    assert excinfo.value.code == "IMPORT_PROPOSAL_STALE"
    with ReadSnapshot(factory) as snapshot:
        assert snapshot.connection.execute("SELECT 1 FROM command_receipts WHERE command_id=?", (command_id,)).fetchone() is None
        assert snapshot.connection.execute(
            "SELECT proposal_state,revision FROM reconciliation_proposals WHERE reconciliation_proposal_id=?",
            (seeded["proposal_id"],),
        ).fetchone() == ("pending", 1)
        active = snapshot.connection.execute(
            "SELECT customer_org_id FROM sr_customer_relationships WHERE service_request_id=? AND relationship_state='active'",
            (sr.service_request_id,),
        ).fetchone()
        assert str(active[0]) == actual.customer_org_id
        assert snapshot.connection.execute(
            "SELECT revision FROM service_requests WHERE service_request_id=?",
            (sr.service_request_id,),
        ).fetchone()[0] == 2
        assert snapshot.connection.execute(
            "SELECT COUNT(*) FROM proposal_dispositions WHERE reconciliation_proposal_id=?",
            (seeded["proposal_id"],),
        ).fetchone()[0] == 0


def test_lld06_failure_after_staged_acceptance_rolls_back_receipt_domain_and_import_state(initialized_database) -> None:
    factory = _factory(initialized_database)
    target = _customer(factory, name="Rollback Target", account_code="RB-1")
    sr = _official_sr(factory, "33445565")
    seeded = _seed_customer_proposal(
        factory,
        sr_id=sr.service_request_id,
        sr_no="33445565",
        target_customer_org_id=target.customer_org_id,
        prior_customer_org_id=None,
        account_code="RB-1",
        customer_label="Rollback Target",
    )
    command_id = new_uuid4()
    service = ProposalDecisionService(
        factory,
        sr_customer_classification_participant=FakeClassificationParticipant(fail=True),
    )
    with pytest.raises(SomaError) as excinfo:
        service.accept(
            command_id=command_id,
            proposal_id=seeded["proposal_id"],
            proposal_revision=1,
            proposal_fingerprint=seeded["fingerprint"],
            base_state_token=seeded["base_token"],
            reason_category="classification_failure",
        )
    assert excinfo.value.code == "SR_CUSTOMER_CLASSIFICATION_PARTICIPANT_FAILED"
    with ReadSnapshot(factory) as snapshot:
        assert snapshot.connection.execute("SELECT 1 FROM command_receipts WHERE command_id=?", (command_id,)).fetchone() is None
        assert snapshot.connection.execute(
            "SELECT proposal_state,revision FROM reconciliation_proposals WHERE reconciliation_proposal_id=?",
            (seeded["proposal_id"],),
        ).fetchone() == ("pending", 1)
        assert snapshot.connection.execute(
            "SELECT COUNT(*) FROM proposal_dispositions WHERE reconciliation_proposal_id=?",
            (seeded["proposal_id"],),
        ).fetchone()[0] == 0
        assert snapshot.connection.execute(
            "SELECT COUNT(*) FROM sr_customer_relationships WHERE service_request_id=?",
            (sr.service_request_id,),
        ).fetchone()[0] == 0
        assert snapshot.connection.execute(
            "SELECT revision FROM service_requests WHERE service_request_id=?",
            (sr.service_request_id,),
        ).fetchone()[0] == 1
        assert snapshot.connection.execute(
            "SELECT pending_proposal_count,accepted_proposal_count,revision FROM import_runs WHERE import_run_id=?",
            (seeded["run_id"],),
        ).fetchone() == (1, 0, 1)
        assert snapshot.connection.execute("SELECT COUNT(*) FROM audit_events WHERE command_id=?", (command_id,)).fetchone()[0] == 0
