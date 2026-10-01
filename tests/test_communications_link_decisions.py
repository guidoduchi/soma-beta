from __future__ import annotations

import sqlite3

import pytest

from soma.communications.contracts.proposal import CommunicationProposalContractRegistry
from soma.communications.domain.proposals import proposal_fingerprint, source_fingerprint
from soma.communications.repositories.sources import one
from soma.communications.services.proposal_evidence import CommunicationProposalEvidenceProvider
from soma.communications.services.proposals import CommunicationProposalService
from soma.foundation.errors import SomaError
from soma.foundation.identifiers import new_uuid4
from soma.foundation.persistence.uow import ReadSnapshot, UnitOfWork

from test_communications_housekeeping import seed
from test_communications_identity_providers import providers
from test_objectives_tasks_objectives import _create_single_task_objective


def link_proposal(path, factory, *, communication=None, target_id=None):
    start = 100 if communication is None else 300
    communication = communication or seed(path, pending=False)
    if target_id is None:
        _, target = _create_single_task_objective(factory, name="Reviewed communications target", start_utc=start, end_utc=start + 100)
        target_id = target.objective_id
    identity = new_uuid4()
    owners = providers()
    with UnitOfWork(factory) as uow:
        exported = next(item for item in owners.snapshot(uow) if item.target_id == target_id)
        uow.connection.execute("UPDATE communications SET chronology_known=1,chronology_utc=123,chronology_source_kind='RECEIVED_TIME' WHERE communication_id=?", (communication,))
        message = one(uow, "SELECT * FROM communications WHERE communication_id=?", (communication,))
        payload = CommunicationProposalContractRegistry().validate("COMM_LINK_V1", 1, exported.target_type, {
            "schema": "COMM_LINK_V1", "matched_identity_kind": exported.identity_kind,
            "matched_identity_value": exported.normalized_value, "match_rule_id": "COMM_EXACT_IDENTIFIER_V1",
            "match_rule_version": 1, "confidence_basis": "EXACT_IDENTIFIER"})
        source = source_fingerprint(message, 1)
        exact = proposal_fingerprint(source, exported.target_id, exported.target_revision, payload)
        uow.connection.execute("INSERT INTO communication_proposals(communication_proposal_id,communication_id,target_type,target_id,target_revision,proposal_contract_id,proposal_contract_version,payload_json,source_fingerprint,proposal_fingerprint,state,revision,created_at_utc) VALUES(?,?,?,?,?,'COMM_LINK_V1',1,?,?,?,'PENDING',1,1)",
                               (identity, communication, exported.target_type, exported.target_id, exported.target_revision, payload.canonical_json, source, exact))
        uow.connection.execute("INSERT INTO communication_protection_holds VALUES(?,?,'PROPOSAL',?,'ACTIVE',1,NULL)", (new_uuid4(), communication, identity))
    return communication, exported, {"command_id": new_uuid4(), "proposal_id": identity, "proposal_revision": 1,
        "target_revision": exported.target_revision, "proposal_fingerprint": exact, "decision": "ACCEPT", "reason_code": "REVIEWED_MATCH"}


def service(factory):
    identities = providers()
    return CommunicationProposalService(factory, identity_providers=identities,
        evidence_provider=CommunicationProposalEvidenceProvider(identities), clock=lambda: 500)


def correction(owner, link, target=None):
    value = {"link_id": link, "link_revision": 1, "action": "CLOSE" if target is None else "RETARGET",
        "new_target_type": None if target is None else target.target_type,
        "new_target_id": None if target is None else target.target_id,
        "new_target_revision": None if target is None else target.target_revision,
        "matched_identity_kind": None if target is None else target.identity_kind,
        "matched_identity_value": None if target is None else target.normalized_value,
        "reason_code": "REVIEWED_CORRECTION"}
    return {**value, "command_id": new_uuid4(), "preview_fingerprint": owner.preview_link_correction(value)}


def replacement(factory):
    _, target = _create_single_task_objective(factory, name="Replacement target", start_utc=500, end_utc=600)
    with UnitOfWork(factory) as uow:
        return next(item for item in providers().snapshot(uow) if item.target_id == target.objective_id)


def test_closing_sibling_links_keeps_content_and_starts_grace_only_for_final_dependency(communication_database):
    path, factory = communication_database
    comm, _, first = link_proposal(path, factory)
    _, _, second = link_proposal(path, factory, communication=comm)
    owner = service(factory)
    a, b = owner.decide_link(first), owner.decide_link(second)
    request = correction(owner, a["target_id"])
    result = owner.correct_link(request)
    assert result["new_revision"] == 2
    assert owner.correct_link(request) == result
    with sqlite3.connect(path) as connection:
        assert connection.execute("SELECT state,revision FROM communication_retention").fetchone() == ("RETAINED", 1)
        assert connection.execute("SELECT body_text FROM communications").fetchone()[0] == "SecretBody"
    owner.correct_link(correction(owner, b["target_id"]))
    with sqlite3.connect(path) as connection:
        assert connection.execute("SELECT state,orphan_since_utc,purge_due_utc FROM communication_retention").fetchone() == ("ORPHAN_PENDING_PURGE", 500, 500 + 10080 * 60)
        assert connection.execute("SELECT COUNT(*) FROM communication_links WHERE state='ACTIVE'").fetchone()[0] == 0


def test_retarget_preserves_original_link_chronology_and_canonical_content(communication_database):
    path, factory = communication_database
    comm, _, proposal = link_proposal(path, factory)
    owner = service(factory)
    original = owner.decide_link(proposal)["target_id"]
    target = replacement(factory)
    with sqlite3.connect(path) as connection:
        connection.execute("UPDATE communications SET chronology_utc=999,chronology_source_kind='SENT_TIME' WHERE communication_id=?", (comm,))
    request = correction(owner, original, target)
    result = owner.correct_link(request)
    owner._identities = None
    assert owner.correct_link(request) == result
    with sqlite3.connect(path) as connection:
        active = connection.execute("SELECT communication_link_id,target_id,effective_chronology_utc,effective_chronology_source_kind,origin,match_rule_id FROM communication_links WHERE state='ACTIVE'").fetchone()
        assert active[0] != original
        assert active[1:] == (target.target_id, 123, "RECEIVED_TIME", "MANUAL", "COMM_REVIEWED_MANUAL_V1")
        assert connection.execute("SELECT state,revision FROM communication_links WHERE communication_link_id=?", (original,)).fetchone() == ("CLOSED", 2)
        assert connection.execute("SELECT chronology_utc,body_text FROM communications").fetchone() == (999, "SecretBody")
        assert connection.execute("SELECT state,revision FROM communication_retention").fetchone() == ("RETAINED", 1)


def test_correction_rejects_stale_dependency_preview_and_duplicate_sibling(communication_database):
    path, factory = communication_database
    comm, _, proposal = link_proposal(path, factory)
    owner = service(factory)
    original = owner.decide_link(proposal)["target_id"]
    request = correction(owner, original)
    _, sibling, second = link_proposal(path, factory, communication=comm)
    owner.decide_link(second)
    with pytest.raises(SomaError) as raised:
        owner.correct_link(request)
    assert raised.value.code == "COMM_STALE"
    with pytest.raises(SomaError) as raised:
        correction(owner, original, sibling)
    assert raised.value.code == "COMM_LINK_CONFLICT"
    with sqlite3.connect(path) as connection:
        assert connection.execute("SELECT state,revision FROM communication_links WHERE communication_link_id=?", (original,)).fetchone() == ("ACTIVE", 1)
        assert connection.execute("SELECT 1 FROM command_receipts WHERE command_id=?", (request["command_id"],)).fetchone() is None


def test_close_binds_current_old_owner_revision_but_does_not_require_historical_revision_to_remain_current(communication_database):
    from soma.inventory.services.requests_rma import InventoryRequestsRmaService
    from test_inventory_proposal_target_participant import _draft
    path, factory = communication_database
    target_id, _ = _draft(factory)
    _, target, payload = link_proposal(path, factory, target_id=target_id)
    owner = service(factory)
    original = owner.decide_link(payload)["target_id"]
    stale = correction(owner, original)
    InventoryRequestsRmaService(factory).assign_or_correct_spare_request_official_id(
        command_id=new_uuid4(), spare_request_id=target_id, base_revision=target.target_revision,
        sr7='SR0000001', action='assign')
    with pytest.raises(SomaError) as raised:
        owner.correct_link(stale)
    assert raised.value.code == "COMM_STALE"
    fresh = correction(owner, original)
    owner.correct_link(fresh)
    with ReadSnapshot(factory) as reader:
        assert providers().current_revision(reader, target.target_type, target.target_id) == target.target_revision + 1
    with sqlite3.connect(path) as connection:
        assert connection.execute("SELECT state FROM communication_links WHERE communication_link_id=?", (original,)).fetchone()[0] == "CLOSED"


@pytest.mark.parametrize("retarget", [False, True])
def test_correction_audit_failure_rolls_back_old_link_replacement_retention_and_receipt(communication_database, monkeypatch, retarget):
    path, factory = communication_database
    _, _, proposal = link_proposal(path, factory)
    owner = service(factory)
    original = owner.decide_link(proposal)["target_id"]
    request = correction(owner, original, replacement(factory) if retarget else None)
    def fail(*args):
        raise RuntimeError("injected correction audit failure")
    monkeypatch.setattr(owner._boundary._audit_writer, "write", fail)
    with pytest.raises(RuntimeError):
        owner.correct_link(request)
    with sqlite3.connect(path) as connection:
        assert connection.execute("SELECT state,revision FROM communication_links").fetchall() == [("ACTIVE", 1)]
        assert connection.execute("SELECT COUNT(*) FROM communication_link_events").fetchone()[0] == 1
        assert connection.execute("SELECT state,revision FROM communication_retention").fetchone() == ("RETAINED", 1)
        assert connection.execute("SELECT 1 FROM command_receipts WHERE command_id=?", (request["command_id"],)).fetchone() is None


def test_reviewed_links_share_canonical_content_and_preserve_chronology_provenance(communication_database):
    path, factory = communication_database
    comm, target, first = link_proposal(path, factory)
    _, other, second = link_proposal(path, factory, communication=comm)
    owner = service(factory)
    a, b = owner.decide_link(first), owner.decide_link(second)
    assert a["target_id"] != b["target_id"]
    owner._identities = owner._evidence = None
    assert owner.decide_link(first) == a
    with sqlite3.connect(path) as connection:
        assert connection.execute("SELECT COUNT(*) FROM communications").fetchone()[0] == 1
        assert connection.execute("SELECT COUNT(*) FROM communication_links WHERE state='ACTIVE'").fetchone()[0] == 2
        assert connection.execute("SELECT effective_chronology_utc,effective_chronology_source_kind FROM communication_links").fetchall() == [(123, "RECEIVED_TIME")] * 2
        assert connection.execute("SELECT state FROM communication_retention WHERE communication_id=?", (comm,)).fetchone()[0] == "RETAINED"
        assert connection.execute("SELECT COUNT(*) FROM communication_protection_holds WHERE state='ACTIVE'").fetchone()[0] == 0
        assert connection.execute("SELECT state FROM communication_proposals").fetchall() == [("ACCEPTED",)] * 2
        assert connection.execute("SELECT body_text FROM communications").fetchone()[0] == "SecretBody"
        assert "Secret" not in str(connection.execute("SELECT payload_json FROM audit_events WHERE action_type='communications.link.decided'").fetchall())


def test_stale_source_cannot_be_accepted_but_exact_rejection_releases_final_hold_and_starts_elapsed_grace(communication_database):
    path, factory = communication_database
    comm, _, payload = link_proposal(path, factory)
    owner = service(factory)
    with sqlite3.connect(path) as connection:
        connection.execute("UPDATE communications SET content_revision=2 WHERE communication_id=?", (comm,))
    with pytest.raises(SomaError) as raised:
        owner.decide_link(payload)
    assert raised.value.code == "COMM_PROPOSAL_STALE"
    rejected = {**payload, "decision": "REJECT", "reason_code": "REJECTED_STALE_MATCH"}
    owner._identities = owner._evidence = None
    result = owner.decide_link(rejected)
    assert result["new_revision"] == 2
    assert owner.decide_link(rejected) == result
    with sqlite3.connect(path) as connection:
        assert connection.execute("SELECT COUNT(*) FROM communication_links").fetchone()[0] == 0
        assert connection.execute("SELECT state,orphan_since_utc,purge_due_utc FROM communication_retention").fetchone() == ("ORPHAN_PENDING_PURGE", 500, 500 + 10080 * 60)
        assert connection.execute("SELECT content_state,body_text FROM communications").fetchone() == ("RETAINED", "SecretBody")


@pytest.mark.parametrize("decision", ["ACCEPT", "REJECT"])
def test_link_decision_audit_failure_rolls_back_link_disposition_hold_retention_and_receipt(communication_database, monkeypatch, decision):
    path, factory = communication_database
    comm, _, payload = link_proposal(path, factory)
    payload["decision"] = decision
    owner = service(factory)
    def fail(*args):
        raise RuntimeError("injected link audit failure")
    monkeypatch.setattr(owner._boundary._audit_writer, "write", fail)
    with pytest.raises(RuntimeError):
        owner.decide_link(payload)
    with sqlite3.connect(path) as connection:
        assert connection.execute("SELECT state,revision FROM communication_proposals").fetchone() == ("PENDING", 1)
        assert connection.execute("SELECT state FROM communication_protection_holds").fetchone()[0] == "ACTIVE"
        assert connection.execute("SELECT COUNT(*) FROM communication_links").fetchone()[0] == 0
        assert connection.execute("SELECT COUNT(*) FROM communication_link_events").fetchone()[0] == 0
        assert connection.execute("SELECT COUNT(*) FROM communication_proposal_events").fetchone()[0] == 0
        assert connection.execute("SELECT state,revision FROM communication_retention").fetchone() == ("RETAINED", 1)
        assert connection.execute("SELECT 1 FROM command_receipts WHERE command_id=?", (payload["command_id"],)).fetchone() is None
