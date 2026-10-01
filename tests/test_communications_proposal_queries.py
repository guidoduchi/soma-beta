from __future__ import annotations

import sqlite3

import pytest

from soma.communications.contracts.proposal import CommunicationProposalContractRegistry
from soma.communications.domain.proposals import proposal_fingerprint
from soma.communications.queries.proposals import ProposalQueries, list_proposals_in_reader
from soma.foundation.errors import ValidationError
from soma.foundation.identifiers import new_uuid4
from soma.foundation.persistence.uow import ReadSnapshot

from test_communications_proposal_evidence import prepare


def test_proposal_pages_keep_complete_tied_order_and_never_read_message_body(communication_database):
    path, factory = communication_database
    _, proposal_id, _ = prepare(path, factory)
    registry = CommunicationProposalContractRegistry()
    with sqlite3.connect(path) as connection:
        cursor = connection.execute("SELECT * FROM communication_proposals WHERE communication_proposal_id=?", (proposal_id,))
        row = dict(zip((item[0] for item in cursor.description), cursor.fetchone()))
        import json
        payload = registry.validate(row["proposal_contract_id"], row["proposal_contract_version"], row["target_type"], json.loads(row["payload_json"]))
        for _ in range(105):
            identity, target = new_uuid4(), new_uuid4()
            clone = {**row, "communication_proposal_id": identity, "target_id": target,
                     "proposal_fingerprint": proposal_fingerprint(row["source_fingerprint"], target, 1, payload)}
            connection.execute("INSERT INTO communication_proposals(" + ",".join(clone) + ") VALUES(" + ",".join("?" for _ in clone) + ")", tuple(clone.values()))
        expected = [value[0] for value in connection.execute("SELECT communication_proposal_id FROM communication_proposals ORDER BY created_at_utc DESC,communication_proposal_id DESC")]
    queries = ProposalQueries(factory)
    seen, cursor = [], None
    while True:
        page = queries.list_proposals({"limit": 17, "cursor": cursor, "state": "PENDING"})
        seen.extend(item["proposal_id"] for item in page["items"])
        assert all("body" not in item and len(item["payload"]) == 2 for item in page["items"])
        cursor = page["next_cursor"]
        if cursor is None:
            break
    assert seen == expected
    with ReadSnapshot(factory) as reader:
        statements = []
        reader.connection.set_trace_callback(statements.append)
        list_proposals_in_reader(reader, {"limit": 2}, registry)
        assert not any("body_text" in sql or "SELECT * FROM communications" in sql for sql in statements)
        plan = reader.connection.execute("EXPLAIN QUERY PLAN SELECT communication_proposal_id FROM communication_proposals WHERE state='PENDING' ORDER BY created_at_utc DESC,communication_proposal_id DESC LIMIT 100").fetchall()
        assert not any("TEMP B-TREE" in str(item) for item in plan)
        assert any("idx_comm_proposal_state_created" in str(item) for item in plan)


def test_proposal_cursor_binds_filters_and_full_typed_order_key(communication_database):
    path, factory = communication_database
    _, identity, _ = prepare(path, factory)
    with sqlite3.connect(path) as connection:
        # A second disposition of the same immutable evidence is not a second
        # operational target; use another existing proposal row for this paging
        # shape test, with a distinct contract-bound target fingerprint.
        row = connection.execute("SELECT communication_id,target_type,target_id,target_revision,proposal_contract_id,proposal_contract_version,payload_json,source_fingerprint,proposal_fingerprint FROM communication_proposals WHERE communication_proposal_id=?", (identity,)).fetchone()
        import json
        payload = CommunicationProposalContractRegistry().validate(row[4], row[5], row[1], json.loads(row[6]))
        target = new_uuid4()
        connection.execute("INSERT INTO communication_proposals(communication_proposal_id,communication_id,target_type,target_id,target_revision,proposal_contract_id,proposal_contract_version,payload_json,source_fingerprint,proposal_fingerprint,state,revision,created_at_utc) VALUES(?,?,?,?,?,?,?,?,?,?,'PENDING',1,1)",
                           (new_uuid4(), row[0], row[1], target, row[3], row[4], row[5], row[6], row[7], proposal_fingerprint(row[7], target, row[3], payload)))
    query = ProposalQueries(factory)
    page = query.list_proposals({"limit": 1, "state": "PENDING"})
    cursor = page["next_cursor"]
    assert cursor is not None
    with pytest.raises(ValidationError):
        query.list_proposals({"state": "ACCEPTED", "cursor": cursor})
    with pytest.raises(ValidationError):
        query.list_proposals({"state": "PENDING", "cursor": {**cursor, "last_key_tuple": [cursor["last_key_tuple"][0]]}})
    with pytest.raises(ValidationError):
        query.list_proposals({"state": "PENDING", "cursor": {**cursor, "last_key_tuple": [True, cursor["last_key_tuple"][1]]}})
    with pytest.raises(ValidationError):
        query.list_proposals({"state": "UNKNOWN"})
