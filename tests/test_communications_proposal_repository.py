from dataclasses import replace

import pytest

from soma.communications.contracts.proposal import CommunicationProposalContractRegistry
from soma.communications.repositories.proposals import insert_pending
from soma.communications.services.proposals import CommunicationProposalService
from soma.foundation.application.command_receipts import CommandReceipt, CommandReceiptStore
from soma.foundation.errors import IntegrityFailure, SomaError, ValidationError
from soma.foundation.identifiers import new_uuid4
from soma.foundation.persistence.uow import ReadSnapshot, UnitOfWork

from test_communications_housekeeping import seed


def payload(*, membership=None, effective=None):
    return CommunicationProposalContractRegistry().validate("COMM_INVENTORY_WAREHOUSE_RECEIPT_V1", 1, "FAULT_TAG", {
        "schema": "COMM_INVENTORY_WAREHOUSE_RECEIPT_V1", "membership_id": membership or new_uuid4(), "membership_revision": 1,
        "facts": {"schema": "INVENTORY_PROPOSAL_TARGET_V1", "effective_at_utc": effective},
    })


def receipt(writer, command):
    # Test harness for a caller-owned processing receipt. No new public command.
    CommandReceiptStore().insert(writer, CommandReceipt(command, "CommunicationProcessingBatch", "a" * 64,
        "job", new_uuid4(), 100, None, None))


def write(factory, comm, target, proposed, *, source_revision=1):
    with UnitOfWork(factory) as writer:
        command = new_uuid4()
        receipt(writer, command)
        return insert_pending(writer, comm, source_revision=source_revision, target_id=target, target_revision=1,
            payload=proposed, now=100, command_id=command)


@pytest.mark.parametrize("state", ["PENDING", "DEFERRED", "REJECTED"])
def test_reinspection_coalesces_exact_proposal_without_reopening_or_new_holds(communication_database, state):
    path, factory = communication_database
    comm, target, proposed = seed(path, pending=False), new_uuid4(), payload()
    first = write(factory, comm, target, proposed)
    assert first.created and first.creation_event_id and first.protection_hold_id
    service = CommunicationProposalService(factory, clock=lambda: 200)
    if state != "PENDING":
        with ReadSnapshot(factory) as reader:
            fingerprint = reader.connection.execute("SELECT proposal_fingerprint FROM communication_proposals WHERE communication_proposal_id=?", (first.proposal_id,)).fetchone()[0]
        service.decide_domain_proposal({"command_id": new_uuid4(), "proposal_id": first.proposal_id, "proposal_revision": 1,
            "proposal_fingerprint": fingerprint, "decision": "DEFER" if state == "DEFERRED" else "REJECT", "reason_code": "OPERATOR_REVIEWED"})
    again = write(factory, comm, target, proposed)
    assert again.proposal_id == first.proposal_id and not again.created and again.state == state
    assert again.creation_event_id is None and again.protection_hold_id is None
    assert again.revision == (1 if state == "PENDING" else 2)
    with ReadSnapshot(factory) as reader:
        assert reader.connection.execute("SELECT count(*) FROM communication_proposals").fetchone()[0] == 1
        assert reader.connection.execute("SELECT count(*) FROM communication_protection_holds").fetchone()[0] == 1
        assert reader.connection.execute("SELECT count(*) FROM communication_proposal_events").fetchone()[0] == (1 if state == "PENDING" else 2)


def test_different_item_memberships_have_independent_proposals_on_one_canonical_message(communication_database):
    path, factory = communication_database
    comm, target = seed(path, pending=False), new_uuid4()
    first, second = write(factory, comm, target, payload()), write(factory, comm, target, payload())
    assert first.proposal_id != second.proposal_id and first.protection_hold_id != second.protection_hold_id
    with ReadSnapshot(factory) as reader:
        assert reader.connection.execute("SELECT count(*) FROM communications").fetchone()[0] == 1
        assert reader.connection.execute("SELECT count(*) FROM communication_protection_holds WHERE state='ACTIVE'").fetchone()[0] == 2
        plan = reader.connection.execute("EXPLAIN QUERY PLAN SELECT protection_hold_id FROM communication_protection_holds "
            "WHERE communication_id=? AND hold_kind='PROPOSAL' AND owner_ref=? AND state='ACTIVE' LIMIT 2", (comm, first.proposal_id)).fetchall()
        assert any("SEARCH" in row[3] and "communication_id=? AND hold_kind=? AND owner_ref=?" in row[3] for row in plan)


def test_caller_failure_rolls_back_proposal_hold_event_and_receipt_together(communication_database):
    path, factory = communication_database
    comm, command = seed(path, pending=False), new_uuid4()
    with pytest.raises(RuntimeError), UnitOfWork(factory) as writer:
        receipt(writer, command)
        insert_pending(writer, comm, source_revision=1, target_id=new_uuid4(), target_revision=1,
            payload=payload(), now=100, command_id=command)
        raise RuntimeError("injected required batch audit failure")
    with ReadSnapshot(factory) as reader:
        for table in ("communication_proposals", "communication_protection_holds", "communication_proposal_events"):
            assert reader.connection.execute("SELECT count(*) FROM " + table).fetchone()[0] == 0
        assert reader.connection.execute("SELECT count(*) FROM command_receipts WHERE command_id=?", (command,)).fetchone()[0] == 0


def test_source_revision_is_revalidated_and_missing_receipt_is_not_a_new_boundary(communication_database):
    path, factory = communication_database
    comm, target, proposed = seed(path, pending=False), new_uuid4(), payload()
    with pytest.raises(IntegrityFailure), UnitOfWork(factory) as writer:
        insert_pending(writer, comm, source_revision=1, target_id=target, target_revision=1,
            payload=proposed, now=100, command_id=new_uuid4())
    with UnitOfWork(factory) as writer:
        writer.connection.execute("UPDATE communication_source_scopes SET revision=2 WHERE source_scope_id=(SELECT source_scope_id FROM communications WHERE communication_id=?)", (comm,))
    with pytest.raises(SomaError) as raised:
        write(factory, comm, target, proposed)
    assert raised.value.code == "COMM_STALE"
    assert write(factory, comm, target, proposed, source_revision=2).created


def test_digest_collision_does_not_reuse_different_exact_facts(communication_database, monkeypatch):
    import soma.communications.repositories.proposals as repository
    path, factory = communication_database
    comm, target, member = seed(path, pending=False), new_uuid4(), new_uuid4()
    monkeypatch.setattr(repository, "proposal_fingerprint", lambda *args: "e" * 64)
    write(factory, comm, target, payload(membership=member))
    with pytest.raises(IntegrityFailure):
        write(factory, comm, target, payload(membership=member, effective=123))
    with ReadSnapshot(factory) as reader:
        assert reader.connection.execute("SELECT count(*) FROM communication_proposals").fetchone()[0] == 1


def test_typed_dataclass_cannot_bypass_release_validation(communication_database):
    path, factory = communication_database
    comm, target = seed(path, pending=False), new_uuid4()
    valid = payload()
    for forged in (replace(valid, owner_packet="LLD-03"), replace(valid, canonical_json="{}")):
        with pytest.raises(ValidationError):
            write(factory, comm, target, forged)


@pytest.mark.parametrize("direction", ["RECEIVED", "UNKNOWN"])
def test_submission_creation_requires_observed_sent_direction(communication_database, direction):
    path, factory = communication_database
    comm = seed(path, pending=False)
    with UnitOfWork(factory) as writer:
        writer.connection.execute("UPDATE communications SET direction=? WHERE communication_id=?", (direction, comm))
    proposed = CommunicationProposalContractRegistry().validate("COMM_INVENTORY_SUBMISSION_V1", 1, "SPARE_REQUEST", {
        "schema": "COMM_INVENTORY_SUBMISSION_V1", "facts": {"schema": "INVENTORY_PROPOSAL_TARGET_V1",
        "expected_draft_fingerprint": "a" * 64, "effective_submission_at_utc": None}})
    with pytest.raises(ValidationError):
        write(factory, comm, new_uuid4(), proposed)
