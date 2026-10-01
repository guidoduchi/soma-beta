from __future__ import annotations

import sqlite3

import pytest

from soma.communications.services.proposal_disposition import CommunicationProposalDispositionParticipant
from soma.communications.services.proposal_evidence import CommunicationProposalEvidenceProvider
from soma.foundation.errors import SomaError
from soma.foundation.identifiers import new_uuid4
from soma.foundation.persistence.uow import UnitOfWork
from soma.inventory.services.participants import InventoryProposalTargetService
from soma.inventory.services.requests_rma import InventoryRequestsRmaService
from soma.inventory.services.fault_tags import InventoryFaultTagsService
from soma.communications.contracts.proposal import CommunicationProposalContractRegistry
from soma.communications.domain.proposals import source_fingerprint, proposal_fingerprint
from soma.communications.repositories.sources import one

from test_communications_identity_providers import providers
from test_communications_proposal_evidence import prepare
from test_communications_housekeeping import seed
from test_inventory_warehouse_replay import _submitted_tag, _members


def setup(communication_database):
    path, factory = communication_database
    comm, identity, exact = prepare(path, factory)
    provider = CommunicationProposalEvidenceProvider(providers(), InventoryProposalTargetService())
    disposition = CommunicationProposalDispositionParticipant(factory, clock=lambda: 100)
    service = InventoryRequestsRmaService(factory, communication_evidence_provider=provider,
                                         communication_disposition_participant=disposition)
    with UnitOfWork(factory) as uow:
        evidence = provider.get_for_owner_command(uow, identity, 1, exact)
    request = {"command_id": new_uuid4(), "spare_request_id": evidence["target_id"],
               "expected_fingerprint": evidence["payload"]["facts"]["expected_draft_fingerprint"],
               "effective_submission_at_utc": None, "evidence_kind": "indexed_sent", "evidence_id": comm,
               "communication_proposal": {"proposal_id": identity, "proposal_revision": 1, "proposal_fingerprint": exact}}
    return path, service, disposition, identity, request


def test_lld09_a033_owner_acceptance_disposition_and_exact_result_share_one_receipt(communication_database):
    path, service, _, identity, request = setup(communication_database)
    result = service.accept_spare_request_submission(**request)
    with sqlite3.connect(path) as connection:
        assert connection.execute("SELECT state,revision FROM communication_proposals WHERE communication_proposal_id=?", (identity,)).fetchone() == ("ACCEPTED", 2)
        assert connection.execute("SELECT state FROM communication_protection_holds WHERE owner_ref=?", (identity,)).fetchone()[0] == "CLOSED"
        assert connection.execute("SELECT lifecycle_state,revision FROM spare_request_current_projection WHERE spare_request_id=?", (request["spare_request_id"],)).fetchone() == ("submitted_awaiting_response", 2)
        assert connection.execute("SELECT count(*) FROM command_receipts WHERE command_id=?", (request["command_id"],)).fetchone()[0] == 1
        assert connection.execute("SELECT count(*) FROM command_receipt_results WHERE command_id=?", (request["command_id"],)).fetchone()[0] == 1
        assert {row[0] for row in connection.execute("SELECT action_type FROM audit_events WHERE command_id=?", (request["command_id"],))} == {"inventory.spare_request.submitted", "communications.proposal.owner_accepted"}
    service._communications._evidence = None
    service._communications._disposition = None
    assert service.accept_spare_request_submission(**request) == result


@pytest.mark.parametrize("failed_writer", ["owner", "disposition"])
def test_lld09_f006_each_required_audit_failure_rolls_back_both_owners(communication_database, monkeypatch, failed_writer):
    path, service, disposition, identity, request = setup(communication_database)
    writer = service._boundary._audit_writer if failed_writer == "owner" else disposition._writer
    def fail(*args):
        raise RuntimeError("injected required audit failure")
    monkeypatch.setattr(writer, "write", fail)
    with pytest.raises(RuntimeError):
        service.accept_spare_request_submission(**request)
    with sqlite3.connect(path) as connection:
        assert connection.execute("SELECT state,revision FROM communication_proposals WHERE communication_proposal_id=?", (identity,)).fetchone() == ("PENDING", 1)
        assert connection.execute("SELECT state FROM communication_protection_holds WHERE owner_ref=?", (identity,)).fetchone()[0] == "ACTIVE"
        assert connection.execute("SELECT lifecycle_state,revision FROM spare_request_current_projection WHERE spare_request_id=?", (request["spare_request_id"],)).fetchone() == ("draft", 1)
        assert connection.execute("SELECT state FROM communication_retention").fetchone()[0] == "RETAINED"
        for table in ("command_receipts", "command_receipt_results", "audit_events", "communication_proposal_events", "communication_retention_events"):
            assert connection.execute("SELECT count(*) FROM " + table + " WHERE command_id=?", (request["command_id"],)).fetchone()[0] == 0


def test_owner_command_rejects_changed_facts_before_receipt_or_mutation(communication_database):
    path, service, _, identity, request = setup(communication_database)
    request["effective_submission_at_utc"] = 123
    with pytest.raises(SomaError) as raised:
        service.accept_spare_request_submission(**request)
    assert raised.value.code == "COMM_PROPOSAL_STALE"
    with sqlite3.connect(path) as connection:
        assert connection.execute("SELECT state,revision FROM communication_proposals WHERE communication_proposal_id=?", (identity,)).fetchone() == ("PENDING", 1)
        assert connection.execute("SELECT count(*) FROM command_receipts WHERE command_id=?", (request["command_id"],)).fetchone()[0] == 0


def warehouse_proposal(path, factory, *, tag_id, tag_revision, member, contract_id, facts):
    comm, identity = seed(path, pending=False), new_uuid4()
    with UnitOfWork(factory) as uow:
        message = one(uow, "SELECT * FROM communications WHERE communication_id=?", (comm,))
        payload = CommunicationProposalContractRegistry().validate(contract_id, 1, "FAULT_TAG", {
            "schema": contract_id, "membership_id": member.fault_tag_membership_id, "membership_revision": member.revision, "facts": facts,
        })
        source = source_fingerprint(message, 1)
        exact = proposal_fingerprint(source, tag_id, tag_revision, payload)
        uow.connection.execute(
            "INSERT INTO communication_proposals(communication_proposal_id,communication_id,target_type,target_id,target_revision,"
            "proposal_contract_id,proposal_contract_version,payload_json,source_fingerprint,proposal_fingerprint,state,revision,created_at_utc) "
            "VALUES (?,?,'FAULT_TAG',?,?,?,1,?,?,?,'PENDING',1,1)",
            (identity, comm, tag_id, tag_revision, contract_id, payload.canonical_json, source, exact),
        )
        uow.connection.execute("INSERT INTO communication_protection_holds VALUES (?,?, 'PROPOSAL',?,'ACTIVE',1,NULL)", (new_uuid4(), comm, identity))
    return comm, {"proposal_id": identity, "proposal_revision": 1, "proposal_fingerprint": exact}


def test_warehouse_proposals_preserve_parent_membership_binding_and_final_confirmation(communication_database):
    path, factory = communication_database
    _, tag, _ = _submitted_tag(factory)
    provider = CommunicationProposalEvidenceProvider(providers(), InventoryProposalTargetService())
    disposition = CommunicationProposalDispositionParticipant(factory, clock=lambda: 100)
    service = InventoryFaultTagsService(factory, communication_evidence_provider=provider, communication_disposition_participant=disposition)
    selected, sibling = _members(tag)
    comm, reference = warehouse_proposal(path, factory, tag_id=tag["fault_tag_id"], tag_revision=tag["revision"], member=selected,
        contract_id="COMM_INVENTORY_WAREHOUSE_RECEIPT_V1", facts={"schema": "INVENTORY_PROPOSAL_TARGET_V1", "effective_at_utc": None})
    receipt_request = {"command_id": new_uuid4(), "memberships": (selected,), "evidence_kind": "indexed_received", "evidence_id": comm,
                       "communication_proposal": reference}
    service.record_warehouse_receipt(**receipt_request)
    with UnitOfWork(factory) as uow:
        current = InventoryFaultTagsService._response(uow.connection, tag["fault_tag_id"])
    selected = next(member for member in _members(current) if member.fault_tag_membership_id == selected.fault_tag_membership_id)
    comm, final_ref = warehouse_proposal(path, factory, tag_id=tag["fault_tag_id"], tag_revision=current["revision"], member=selected,
        contract_id="COMM_INVENTORY_WAREHOUSE_DECISION_V1", facts={"schema": "INVENTORY_PROPOSAL_TARGET_V1", "effective_at_utc": None,
                                                                  "decision": "accepted", "reason_code": None})
    final_request = {"command_id": new_uuid4(), "memberships": (selected,), "decision": "accepted", "explicit_confirmation": False,
                     "evidence_kind": "indexed_received", "evidence_id": comm, "communication_proposal": final_ref}
    with pytest.raises(SomaError) as raised:
        service.record_warehouse_final_decision(**final_request)
    assert raised.value.code == "WAREHOUSE_FINAL_CONFIRMATION_REQUIRED"
    final_request["explicit_confirmation"] = True
    result = service.record_warehouse_final_decision(**final_request)
    replay = service.record_warehouse_final_decision(**final_request)
    assert replay.replayed is True
    assert (replay.outcome, replay.target_refs, replay.revisions) == (result.outcome, result.target_refs, result.revisions)
    with sqlite3.connect(path) as connection:
        assert connection.execute("SELECT state FROM communication_proposals WHERE communication_proposal_id=?", (final_ref["proposal_id"],)).fetchone()[0] == "ACCEPTED"
        assert connection.execute("SELECT state FROM fault_tag_membership_current WHERE fault_tag_membership_id=?", (sibling.fault_tag_membership_id,)).fetchone()[0] == "submitted_awaiting_receipt"
