import sqlite3

import pytest

from soma.communications.queries.housekeeping import HousekeepingQueries
from soma.communications.services.housekeeping import HousekeepingService
from soma.communications.services.retention import reconcile_retention
from soma.foundation.errors import IntegrityFailure, ValidationError
from soma.foundation.identifiers import new_uuid4
from soma.foundation.persistence.uow import UnitOfWork
from test_communications_housekeeping import seed


def transition(factory, comm, *, now=100, grace=1, hold=None, close=False):
    command = new_uuid4()
    with UnitOfWork(factory) as uow:
        uow.connection.execute("INSERT INTO command_receipts VALUES(?,'TestRetention',?,'communication',?,?,NULL,NULL)",
                               (command, "a" * 64, comm, now))
        if hold is not None:
            if close:
                uow.connection.execute("UPDATE communication_protection_holds SET state='CLOSED',closed_at_utc=? WHERE protection_hold_id=?", (now, hold))
            else:
                uow.connection.execute("INSERT INTO communication_protection_holds VALUES(?,?,'PROTECTED_EXPORT',?,'ACTIVE',?,NULL)",
                                       (hold, comm, new_uuid4(), now))
        return reconcile_retention(uow, comm, dependency_event_id=new_uuid4(), event_time=now,
                                   grace_minutes=grace, command_id=command)


def test_current_reason_uses_revision_even_when_state_and_seconds_repeat(communication_database):
    path, factory = communication_database
    comm = seed(path, pending=False)
    first = transition(factory, comm)
    hold = new_uuid4()
    transition(factory, comm, hold=hold)
    last = transition(factory, comm, hold=hold, close=True)
    with sqlite3.connect(path) as db:
        # A random UUID may sort before any earlier UUID. The query must ignore
        # that ordering and also ignore an earlier transition into the same state.
        assert db.execute("SELECT count(*) FROM communication_retention_events WHERE recorded_at_utc=100").fetchone()[0] == 3
        assert db.execute("SELECT resulting_retention_revision FROM communication_retention_events WHERE retention_event_id=?", (last.event_id,)).fetchone()[0] == 4
        assert first.event_id != last.event_id
    page = HousekeepingQueries(factory).list_housekeeping({})
    assert page["items"] == [{"communication_id": comm, "state": "ORPHAN_PENDING_PURGE", "purge_due_utc": 160,
                              "reason_code": "FINAL_PROTECTED_DEPENDENCY_REMOVED", "protected_dependency_count": 0}]
    assert page["next_cursor"] is None


def test_housekeeping_pages_all_state_due_uuid_keys_and_null_last(communication_database):
    path, factory = communication_database
    expected = []
    for i in range(7):
        comm = seed(path, pending=False)
        transition(factory, comm, grace=1 if i < 4 else 2)
        expected.append((0, 160 if i < 4 else 220, comm))
    for _ in range(2):
        comm = seed(path, pending=False)
        transition(factory, comm)
        HousekeepingService(factory).purge_due(command_id=new_uuid4(), communication_id=comm, selected_revision=2, now_utc=300)
        expected.append((1, 160, comm))
    # Nullable due chronology is part of the pinned purged-row schema. It cannot
    # be replaced with a made-up epoch for sorting or cursor continuation.
    with sqlite3.connect(path) as db:
        db.execute("UPDATE communication_retention SET purge_due_utc=NULL WHERE communication_id=?", (expected[-1][2],))
    expected[-1] = (1, None, expected[-1][2])
    expected.sort(key=lambda row: (row[0], row[1] is None, row[1] or 0, row[2]))
    query, cursor, actual = HousekeepingQueries(factory), None, []
    while True:
        page = query.list_housekeeping({"limit": 1, "cursor": cursor})
        actual.extend((0 if row["state"] == "ORPHAN_PENDING_PURGE" else 1, row["purge_due_utc"], row["communication_id"]) for row in page["items"])
        cursor = page["next_cursor"]
        if cursor is None:
            break
        assert len(cursor["last_key_tuple"]) == 3
    assert actual == expected and len(set(row[2] for row in actual)) == 9
    assert query.list_housekeeping({"due_before_utc": 160})["items"] == []
    assert len(query.list_housekeeping({"due_before_utc": 161})["items"]) == 5
    assert len(query.list_housekeeping({"state": "PURGED"})["items"]) == 2


def test_dependencies_are_observational_and_batched_without_reading_content(communication_database):
    path, factory = communication_database
    comm = seed(path, pending=False)
    transition(factory, comm)
    with sqlite3.connect(path) as db:
        db.execute("INSERT INTO communication_protection_holds VALUES(?,?,'PROTECTED_EXPORT',?,'ACTIVE',110,NULL)",
                   (new_uuid4(), comm, new_uuid4()))
    # A restored hold is visible before the authoritative due job reconciles it.
    item = HousekeepingQueries(factory).list_housekeeping({})["items"][0]
    assert item["protected_dependency_count"] == 1
    assert "Secret" not in str(item) and "ExternalSource" not in str(item)
    HousekeepingService(factory).purge_due(command_id=new_uuid4(), communication_id=comm, selected_revision=2, now_utc=300)
    assert HousekeepingQueries(factory).list_housekeeping({})["items"] == []


def test_housekeeping_missing_exact_event_fails_closed_and_cursor_binds_filters(communication_database):
    path, factory = communication_database
    query = HousekeepingQueries(factory)
    first = seed(path, pending=False)
    transition(factory, first)
    second = seed(path, pending=False)
    transition(factory, second)
    cursor = query.list_housekeeping({"limit": 1})["next_cursor"]
    with pytest.raises(ValidationError):
        query.list_housekeeping({"state": "PURGED", "cursor": cursor})
    with pytest.raises(ValidationError):
        query.list_housekeeping({"cursor": cursor | {"last_key_tuple": cursor["last_key_tuple"][:2]}})
    with sqlite3.connect(path) as db:
        db.execute("UPDATE communication_retention SET revision=revision+1 WHERE communication_id=?", (first,))
    with pytest.raises(IntegrityFailure):
        query.list_housekeeping({})


def test_retention_revision_event_identity_is_unique_and_immutable(communication_database):
    path, factory = communication_database
    comm = seed(path, pending=False)
    transition(factory, comm)
    with sqlite3.connect(path) as db:
        with pytest.raises(sqlite3.IntegrityError):
            db.execute("INSERT INTO communication_retention_events SELECT ?,communication_id,from_state,to_state,reason_code,dependency_fingerprint,recorded_at_utc,command_id,resulting_retention_revision FROM communication_retention_events", (new_uuid4(),))
        with pytest.raises(sqlite3.IntegrityError):
            db.execute("UPDATE communication_retention_events SET resulting_retention_revision=5")
        with pytest.raises(sqlite3.IntegrityError):
            db.execute("DELETE FROM communication_retention_events")
