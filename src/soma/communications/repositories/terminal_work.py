"""Connection-local ID bookkeeping for an unbounded atomic cascade.

Only immutable IDs enter these temporary tables. Authoritative evidence stays
in its normal relational tables; this workspace is dropped before returning.
"""
from __future__ import annotations

import hashlib

from soma.foundation.strict_json import canonical_json_bytes

RESULTS = "temp.communication_terminal_work_results"
MESSAGES = "temp.communication_terminal_work_messages"
AUDIT_KIND = "_AUDIT"


def begin(uow):
    uow.connection.execute(f"CREATE TEMP TABLE {RESULTS}(kind TEXT NOT NULL,id TEXT NOT NULL,target_id TEXT,communication_id TEXT,PRIMARY KEY(kind,id)) WITHOUT ROWID")
    uow.connection.execute("CREATE INDEX temp.comm_terminal_work_target ON communication_terminal_work_results(kind,target_id,communication_id)")
    uow.connection.execute("CREATE INDEX temp.comm_terminal_work_message ON communication_terminal_work_results(kind,communication_id,target_id)")
    uow.connection.execute(f"CREATE TEMP TABLE {MESSAGES}(communication_id TEXT PRIMARY KEY,dependency_event_id TEXT NOT NULL) WITHOUT ROWID")


def record(uow, kind, identity, *, target_id=None, communication_id=None):
    uow.connection.execute(f"INSERT INTO {RESULTS} VALUES(?,?,?,?)", (kind, identity, target_id, communication_id))


def closed(uow, event_id, target_id, communication_id):
    record(uow, "communication_link_event", event_id, target_id=target_id, communication_id=communication_id)
    uow.connection.execute(f"INSERT OR IGNORE INTO {MESSAGES} VALUES(?,?)", (communication_id, event_id))


def targets(uow):
    return uow.connection.execute(f"SELECT target_id,id FROM {RESULTS} WHERE kind='communication_terminal_summary' ORDER BY target_id")


def messages(uow):
    return uow.connection.execute(f"SELECT communication_id,dependency_event_id FROM {MESSAGES} ORDER BY communication_id")


def target_counts(uow, target_id):
    return uow.connection.execute(
        f"SELECT count(*),coalesce(sum(EXISTS(SELECT 1 FROM {RESULTS} r "
        "WHERE r.kind='communication_retention_event' AND r.communication_id=l.communication_id)),0) "
        f"FROM {RESULTS} l WHERE l.kind='communication_link_event' AND l.target_id=?", (target_id,),
    ).fetchone()


def finish(uow, command_id, proposal_id):
    """Stream the exact canonical object, including its complete sorted arrays."""
    result_count, audit_count = uow.connection.execute(
        f"SELECT coalesce(sum(kind!=?),0),coalesce(sum(kind=?),0) FROM {RESULTS}", (AUDIT_KIND, AUDIT_KIND),
    ).fetchone()
    fields = {
        "schema": "SOMA_RFC_TERMINAL_CASCADE_PARTICIPANT_RESULT_V1",
        "domain": "COMMUNICATIONS", "outer_command_id": command_id, "proposal_id": proposal_id,
        "result_refs": None, "audit_event_ids": None,
    }
    digest = hashlib.sha256()
    digest.update(b"{")
    for ordinal, key in enumerate(sorted(fields)):
        digest.update((b"," if ordinal else b"") + canonical_json_bytes(key) + b":")
        if key in {"result_refs", "audit_event_ids"}:
            digest.update(b"[")
            if key == "result_refs":
                rows = uow.connection.execute(f"SELECT kind,id FROM {RESULTS} WHERE kind!=? ORDER BY kind,id", (AUDIT_KIND,))
                values = ({"type": kind, "id": identity} for kind, identity in rows)
            else:
                rows = uow.connection.execute(f"SELECT id FROM {RESULTS} WHERE kind=? ORDER BY id", (AUDIT_KIND,))
                values = (row[0] for row in rows)
            for index, value in enumerate(values):
                digest.update((b"," if index else b"") + canonical_json_bytes(value))
            digest.update(b"]")
        else:
            digest.update(canonical_json_bytes(fields[key]))
    digest.update(b"}")
    uow.connection.execute(f"DROP TABLE {MESSAGES}")
    uow.connection.execute(f"DROP TABLE {RESULTS}")
    return result_count, audit_count, digest.hexdigest()
