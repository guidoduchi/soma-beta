from __future__ import annotations

import sqlite3

import pytest

from soma.communications.queries.communications import CommunicationQueries
from soma.communications.services.housekeeping import HousekeepingService
from soma.foundation.errors import ValidationError
from soma.foundation.identifiers import new_uuid4

from test_communications_housekeeping import seed


def add_link(connection, comm, target, *, state="ACTIVE"):
    link = new_uuid4()
    connection.execute(
        "INSERT INTO communication_links(communication_link_id,communication_id,target_type,target_id,"
        "target_revision_at_link,matched_identity_kind,matched_identity_value,match_rule_id,match_rule_version,"
        "confidence_basis,direction,effective_chronology_known,effective_chronology_utc,origin,state,revision,"
        "created_at_utc,closed_at_utc,close_reason,effective_chronology_source_kind) "
        "VALUES (?,?,'OBJECTIVE',?,1,'MW_TRACKING_ID','MW-00000001','EXACT_IDENTIFIER',1,'EXACT_IDENTIFIER',"
        "'RECEIVED',0,NULL,'AUTO_SAFE',?,1,1,?,NULL,'UNKNOWN')",
        (link, comm, target, state, 2 if state == "CLOSED" else None),
    )
    return link


def test_detail_pages_arbitrary_sibling_links_and_preserves_total_key(communication_database):
    path, factory = communication_database
    comm = seed(path)
    target = new_uuid4()
    with sqlite3.connect(path) as connection:
        active = [add_link(connection, comm, new_uuid4()) for _ in range(127)]
        # Several historical links share the same target. The final UUID remains
        # essential to the total ordering when paging those rows.
        closed = [add_link(connection, comm, target, state="CLOSED") for _ in range(5)]
        plan = connection.execute(
            "EXPLAIN QUERY PLAN SELECT communication_link_id FROM communication_links "
            "WHERE communication_id=? AND state='ACTIVE' AND (target_type,target_id,communication_link_id)>(?,?,?) "
            "ORDER BY target_type,target_id,communication_link_id LIMIT 101",
            (comm, "OBJECTIVE", target, new_uuid4()),
        ).fetchall()
        assert any("idx_comm_link_comm_state_order" in row[3] for row in plan)
        assert all("TEMP B-TREE" not in row[3] for row in plan)
    queries = CommunicationQueries(factory)
    detail = queries.get_communication({"communication_id": comm})
    assert len(detail["active_links"]) == 100
    assert detail["body"] == "SecretBody"
    assert detail["participants"][0]["address"] == "SecretAddress@example.com"
    assert detail["attachments"][0]["filename"] == "SecretFilename"
    cursor = detail["active_links_next_cursor"]
    remainder = queries.list_communication_links({"communication_id": comm, "state": "ACTIVE", "cursor": cursor})
    assert len(remainder["items"]) == 27 and remainder["next_cursor"] is None
    assert {row["communication_link_id"] for row in detail["active_links"] + remainder["items"]} == set(active)
    found, cursor = [], None
    while True:
        page = queries.list_communication_links({"communication_id": comm, "state": "CLOSED", "limit": 2, "cursor": cursor})
        found.extend(row["communication_link_id"] for row in page["items"])
        cursor = page["next_cursor"]
        if cursor is None:
            break
        assert len(cursor["last_key_tuple"]) == 3
    assert found == sorted(closed)
    with pytest.raises(ValidationError):
        queries.list_communication_links({"communication_id": comm, "state": "CLOSED", "cursor": detail["active_links_next_cursor"]})
    with pytest.raises(ValidationError):
        queries.list_communication_links({"communication_id": new_uuid4(), "state": "ACTIVE", "cursor": detail["active_links_next_cursor"]})
    with sqlite3.connect(path) as connection:
        assert connection.execute("SELECT count(*) FROM command_receipts").fetchone()[0] == 0
        assert connection.execute("SELECT count(*) FROM audit_events").fetchone()[0] == 0


def test_lld09_a044_p004_p005_purged_detail_never_reconstructs_content(communication_database):
    path, factory = communication_database
    comm = seed(path)
    with sqlite3.connect(path) as connection:
        add_link(connection, comm, new_uuid4(), state="CLOSED")
    HousekeepingService(factory).purge_due(command_id=new_uuid4(), communication_id=comm, selected_revision=1, now_utc=220)
    detail = CommunicationQueries(factory).get_communication({"communication_id": comm})
    assert detail["content_state"] == detail["retention_state"] == "PURGED"
    assert detail["body"] is detail["subject"] is None
    assert detail["body_kind"] == "NONE"
    assert detail["participants"] == detail["attachments"] == detail["active_links"] == []
    assert detail["active_links_next_cursor"] is None
    assert detail["identity_state"] == "PROVIDER_STABLE"


def test_link_chronology_provenance_is_persisted_and_guarded(communication_database):
    path, factory = communication_database
    comm = seed(path)
    with sqlite3.connect(path) as connection:
        link = add_link(connection, comm, new_uuid4())
        with pytest.raises(sqlite3.IntegrityError):
            connection.execute("UPDATE communication_links SET effective_chronology_source_kind='SENT_TIME' WHERE communication_link_id=?", (link,))
        connection.execute("UPDATE communication_links SET effective_chronology_known=1,effective_chronology_utc=123,effective_chronology_source_kind='SENT_TIME' WHERE communication_link_id=?", (link,))
    page = CommunicationQueries(factory).list_communication_links({"communication_id": comm})
    assert page["items"][0]["effective_chronology"] == {"known": True, "utc_epoch_seconds": 123, "source_kind": "SENT_TIME"}


def test_list_pages_ties_known_and_unknown_without_duplicates(communication_database):
    path, factory = communication_database
    comms = [seed(path) for _ in range(7)]
    target = new_uuid4()
    with sqlite3.connect(path) as connection:
        for comm, instant in zip(comms, (200, 200, 100, 100, None, None, None)):
            if instant is not None:
                connection.execute("UPDATE communications SET chronology_known=1,chronology_utc=?,chronology_source_kind='RECEIVED_TIME' WHERE communication_id=?", (instant, comm))
            add_link(connection, comm, target)
            add_link(connection, comm, new_uuid4())
        expected = [row[0] for row in connection.execute("SELECT communication_id FROM communications ORDER BY chronology_known DESC,chronology_utc DESC,communication_id DESC")]
        plan = connection.execute(
            "EXPLAIN QUERY PLAN SELECT c.communication_id FROM communication_links l INDEXED BY idx_comm_link_target_canonical_order "
            "JOIN communications c ON c.communication_id=l.communication_id WHERE l.target_type='OBJECTIVE' AND l.target_id=? "
            "AND l.state='ACTIVE' ORDER BY l.canonical_chronology_known DESC,l.canonical_chronology_utc DESC,l.communication_id DESC LIMIT 3", (target,),
        ).fetchall()
        assert any("SEARCH l USING" in row[3] for row in plan)
        assert all("TEMP B-TREE" not in row[3] for row in plan)
    queries = CommunicationQueries(factory)
    for filters in ({}, {"target_type": "OBJECTIVE", "target_id": target}, {"target_type": "OBJECTIVE"}):
        found, cursor = [], None
        while True:
            page = queries.list_communications({**filters, "limit": 2, "cursor": cursor})
            found.extend(row["communication_id"] for row in page["items"])
            cursor = page["next_cursor"]
            if cursor is None:
                break
            assert len(cursor["last_key_tuple"]) == 3
        assert found == expected
    first = queries.list_communications({"limit": 2})
    with pytest.raises(ValidationError):
        queries.list_communications({"direction": "RECEIVED", "cursor": first["next_cursor"]})


def test_lld09_a044_literal_search_never_interprets_operators_or_returns_purged_content(communication_database):
    path, factory = communication_database
    retained, purged, other = seed(path), seed(path), seed(path)
    with sqlite3.connect(path) as connection:
        connection.execute("UPDATE communications SET subject='Résumé Alpha',body_text='Literal OR Beta' WHERE communication_id IN (?,?)", (retained, purged))
        connection.execute("UPDATE communications SET subject='Alpha',body_text='Beta' WHERE communication_id=?", (other,))
    HousekeepingService(factory).purge_due(command_id=new_uuid4(), communication_id=purged, selected_revision=1, now_utc=220)
    queries = CommunicationQueries(factory)
    assert [row["communication_id"] for row in queries.list_communications({"search": " resume\talpha "})["items"]] == [retained]
    assert [row["communication_id"] for row in queries.list_communications({"search": "Alpha OR Beta"})["items"]] == [retained]
    assert queries.list_communications({"search": '" OR "'})["items"] == []
    assert queries.list_communications({"search": "   "}) == queries.list_communications({})
    page = queries.list_communications({"search": "Alpha Beta", "limit": 1})
    cursor = page["next_cursor"]
    assert cursor is not None
    assert queries.list_communications({"search": " Alpha\tBeta ", "cursor": cursor})["items"]
    with pytest.raises(ValidationError):
        queries.list_communications({"search": "Beta", "cursor": cursor})
    assert len(queries.list_communications({"content_state": "PURGED"})["items"]) == 1
