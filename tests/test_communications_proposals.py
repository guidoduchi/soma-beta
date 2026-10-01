from __future__ import annotations

import sqlite3

import pytest

from soma.communications.services.proposals import CommunicationProposalService
from soma.foundation.errors import SomaError
from soma.foundation.identifiers import new_uuid4
from soma.foundation.strict_json import canonical_json_bytes

from test_communications_housekeeping import seed


def seed_proposal(path, comm, *, target=None):
    identity = new_uuid4()
    payload = {"schema": "COMM_INVENTORY_SUBMISSION_V1", "facts": {"schema": "INVENTORY_PROPOSAL_TARGET_V1",
               "expected_draft_fingerprint": "a" * 64, "effective_submission_at_utc": None}}
    with sqlite3.connect(path) as connection:
        connection.execute("UPDATE communication_retention SET state='RETAINED',orphan_since_utc=NULL,purge_due_utc=NULL WHERE communication_id=?", (comm,))
        connection.execute(
            "INSERT INTO communication_proposals(communication_proposal_id,communication_id,target_type,target_id,target_revision,"
            "proposal_contract_id,proposal_contract_version,payload_json,source_fingerprint,proposal_fingerprint,state,revision,created_at_utc) "
            "VALUES (?,?,'SPARE_REQUEST',?,1,'COMM_INVENTORY_SUBMISSION_V1',1,?,?,?,'PENDING',1,1)",
            (identity, comm, target or new_uuid4(), canonical_json_bytes(payload).decode(), "b" * 64, "c" * 64),
        )
        connection.execute("INSERT INTO communication_protection_holds VALUES (?,?, 'PROPOSAL',?,'ACTIVE',1,NULL)", (new_uuid4(), comm, identity))
    return identity


def request(identity, *, revision=1, decision="DEFER"):
    return {"command_id": new_uuid4(), "proposal_id": identity, "proposal_revision": revision,
            "decision": decision, "reason_code": "NEEDS_MORE_EVIDENCE" if decision == "DEFER" else "OPERATOR_REJECTED",
            "proposal_fingerprint": "c" * 64}


def test_lld09_a034_defer_and_reject_preserve_sibling_holds_and_exact_replay(communication_database):
    path, factory = communication_database
    comm = seed(path)
    first, sibling = seed_proposal(path, comm), seed_proposal(path, comm)
    service = CommunicationProposalService(factory, clock=lambda: 100)
    deferred = request(first)
    result = service.decide_domain_proposal(deferred)
    assert result["new_revision"] == 2
    assert service.decide_domain_proposal(request(first, revision=2))["status"] == "NO_CHANGE"
    service.decide_domain_proposal(request(first, revision=2, decision="REJECT"))
    assert service.decide_domain_proposal(deferred) == result
    with sqlite3.connect(path) as connection:
        assert connection.execute("SELECT state FROM communication_protection_holds WHERE owner_ref=?", (first,)).fetchone()[0] == "CLOSED"
        assert connection.execute("SELECT state FROM communication_protection_holds WHERE owner_ref=?", (sibling,)).fetchone()[0] == "ACTIVE"
        assert connection.execute("SELECT state FROM communication_retention WHERE communication_id=?", (comm,)).fetchone()[0] == "RETAINED"
        assert connection.execute("SELECT count(*) FROM communication_proposal_events").fetchone()[0] == 2
        assert connection.execute("SELECT count(*) FROM audit_events").fetchone()[0] == 2
    service.decide_domain_proposal(request(sibling, decision="REJECT"))
    with sqlite3.connect(path) as connection:
        assert connection.execute("SELECT state,purge_due_utc FROM communication_retention WHERE communication_id=?", (comm,)).fetchone() == ("ORPHAN_PENDING_PURGE", 100 + 10080 * 60)
        assert connection.execute("SELECT count(*) FROM spare_requests").fetchone()[0] == 0
    assert service.decide_domain_proposal(request(first, revision=3, decision="REJECT"))["status"] == "NO_CHANGE"


def test_lld09_f006_proposal_audit_failure_rolls_back_disposition_hold_and_grace(communication_database, monkeypatch):
    path, factory = communication_database
    comm = seed(path)
    identity = seed_proposal(path, comm)
    service = CommunicationProposalService(factory, clock=lambda: 100)
    value = request(identity, decision="REJECT")
    def fail(*args):
        raise RuntimeError("injected audit failure")
    monkeypatch.setattr(service._boundary._audit_writer, "write", fail)
    with pytest.raises(RuntimeError):
        service.decide_domain_proposal(value)
    with sqlite3.connect(path) as connection:
        assert connection.execute("SELECT state,revision FROM communication_proposals").fetchone() == ("PENDING", 1)
        assert connection.execute("SELECT state FROM communication_protection_holds").fetchone()[0] == "ACTIVE"
        assert connection.execute("SELECT state FROM communication_retention").fetchone()[0] == "RETAINED"
        assert connection.execute("SELECT count(*) FROM communication_proposal_events").fetchone()[0] == 0
        assert connection.execute("SELECT count(*) FROM command_receipts WHERE command_id=?", (value["command_id"],)).fetchone()[0] == 0
    stale = {**value, "proposal_revision": 2}
    with pytest.raises(SomaError) as raised:
        service.decide_domain_proposal(stale)
    assert raised.value.code == "COMM_PROPOSAL_STALE"
