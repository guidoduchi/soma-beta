from __future__ import annotations

from soma.communications.repositories.sources import one

PROVIDER_KINDS = frozenset({"MAPI_RECORD_KEY", "PROVIDER_STABLE_OTHER"})
GENERIC_HOLD = "hold_kind='COLLISION_REVIEW' AND state='ACTIVE' AND NOT EXISTS(SELECT 1 FROM communication_identity_review_evidence e WHERE e.protection_hold_id=h.protection_hold_id)"


def candidate(reader, communication_id):
    return one(reader, "SELECT communication_id,source_scope_id,provider_identity_kind,provider_identity_digest,provider_identity_bytes,"
        "fallback_version,fallback_digest,fallback_canonical_json,identity_state,content_state,content_revision "
        "FROM communications WHERE communication_id=?", (communication_id,))


def aliases(reader, message):
    """Stream every donor alias plus an unaliased preferred provider key."""
    if message["provider_identity_digest"] is not None:
        present = reader.connection.execute("SELECT 1 FROM communication_identity_aliases WHERE communication_id=? "
            "AND alias_kind=? AND alias_digest=? AND normalization_version=1 AND alias_evidence_bytes=? LIMIT 1",
            (message["communication_id"], message["provider_identity_kind"], message["provider_identity_digest"], message["provider_identity_bytes"])).fetchone()
        if present is None:
            yield {"alias_kind": message["provider_identity_kind"], "alias_digest": message["provider_identity_digest"],
                   "normalization_version": 1, "alias_evidence_bytes": message["provider_identity_bytes"]}
    after = ""
    while True:
        cursor = reader.connection.execute("SELECT identity_alias_id,alias_kind,alias_digest,normalization_version,alias_evidence_bytes "
            "FROM communication_identity_aliases WHERE communication_id=? AND identity_alias_id>? ORDER BY identity_alias_id LIMIT 100",
            (message["communication_id"], after))
        rows = cursor.fetchall()
        if not rows:
            return
        names = tuple(field[0] for field in cursor.description)[1:]
        for row in rows:
            yield dict(zip(names, row[1:]))
        after = rows[-1][0]


def selected_alias(reader, communication_id, alias):
    return one(reader, "SELECT identity_alias_id,alias_evidence_bytes FROM communication_identity_aliases "
        "WHERE communication_id=? AND alias_kind=? AND alias_digest=? AND normalization_version=?",
        (communication_id, alias["alias_kind"], alias["alias_digest"], alias["normalization_version"]))


def assignment(reader, source_scope_id, alias):
    return one(reader, "SELECT a.communication_id,s.assignment_revision FROM communication_identity_alias_assignments s "
        "JOIN communication_identity_aliases a USING(identity_alias_id) WHERE s.source_scope_id=? "
        "AND s.provider_identity_kind=? AND s.provider_identity_digest=? AND a.alias_evidence_bytes=? "
        "ORDER BY s.assignment_revision DESC LIMIT 1",
        (source_scope_id, alias["alias_kind"], alias["alias_digest"], alias["alias_evidence_bytes"]))


def generic_holds(reader, communication_id):
    for row in reader.connection.execute("SELECT protection_hold_id,owner_ref,created_at_utc FROM communication_protection_holds h "
            "WHERE communication_id=? AND " + GENERIC_HOLD + " ORDER BY protection_hold_id", (communication_id,)):
        yield row


def active_links(reader, communication_id, *, after=None, limit=None):
    sql = "SELECT * FROM communication_links WHERE communication_id=? AND state='ACTIVE'"
    values = [communication_id]
    if after is not None:
        sql += " AND communication_link_id>?"
        values.append(after)
    sql += " ORDER BY communication_link_id"
    if limit is not None:
        sql += " LIMIT ?"
        values.append(limit)
    cursor = reader.connection.execute(sql, values)
    names = tuple(field[0] for field in cursor.description)
    for row in cursor:
        yield dict(zip(names, row))
