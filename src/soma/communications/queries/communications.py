from __future__ import annotations

from soma.foundation.errors import IntegrityFailure, SomaError, ValidationError
from soma.foundation.identifiers import require_uuid4
from soma.foundation.persistence.uow import ReadSnapshot

from soma.communications.contracts.common import Chronology, DIRECTIONS, TARGET_TYPES, closed, integer, text
from soma.communications.contracts.queries import cursor_key, next_cursor

LINK_QUERY = "ListCommunicationLinks"
LIST_QUERY = "ListCommunications"
_LINK_COLUMNS = (
    "communication_link_id,target_type,target_id,target_revision_at_link,revision,origin,direction,"
    "effective_chronology_known,effective_chronology_utc,effective_chronology_source_kind,"
    "matched_identity_kind,matched_identity_value,confidence_basis,match_rule_id,match_rule_version,state"
)


def _link_summary(row):
    return {
        "communication_link_id": row[0], "target_type": row[1], "target_id": row[2],
        "target_revision_at_link": row[3], "revision": row[4], "origin": row[5], "direction": row[6],
        "effective_chronology": Chronology(bool(row[7]), row[8], row[9]).to_response(),
        "matched_identity_kind": row[10], "matched_identity_value": row[11], "confidence_basis": row[12],
        "match_rule_id": row[13], "match_rule_version": row[14], "state": row[15],
    }


def list_links_in_reader(reader, request: dict) -> dict:
    if not isinstance(request, dict) or "communication_id" not in request or set(request) - {"communication_id", "state", "cursor", "limit"}:
        raise ValidationError("Communication link query has missing or unknown fields")
    communication_id = require_uuid4(request["communication_id"])
    state = request.get("state")
    if state is not None and (not isinstance(state, str) or state not in {"ACTIVE", "CLOSED"}):
        raise ValidationError("Communication link state filter is invalid")
    limit = integer(request.get("limit", 50), minimum=1, maximum=100)
    filters = {"communication_id": communication_id, "state": state}
    key = cursor_key(request.get("cursor"), query=LINK_QUERY, filters=filters, null_order="none", key_length=3)
    conditions, values = ["communication_id=?"], [communication_id]
    if state is not None:
        conditions.append("state=?")
        values.append(state)
    if key is not None:
        if not isinstance(key[0], str) or key[0] not in TARGET_TYPES:
            raise ValidationError("Communication link cursor target type is invalid")
        require_uuid4(key[1])
        require_uuid4(key[2])
        conditions.append("(target_type,target_id,communication_link_id)>(?,?,?)")
        values.extend(key)
    rows = reader.connection.execute(
        "SELECT " + _LINK_COLUMNS + " FROM communication_links WHERE " + " AND ".join(conditions)
        + " ORDER BY target_type,target_id,communication_link_id LIMIT ?", (*values, limit + 1),
    ).fetchall()
    page = rows[:limit]
    continuation = None
    if len(rows) > limit:
        last = page[-1]
        continuation = next_cursor(query=LINK_QUERY, filters=filters, null_order="none", key=(last[1], last[2], last[0]))
    return {"items": [_link_summary(row) for row in page], "next_cursor": continuation}


def communication_detail_in_reader(reader, request: dict) -> dict:
    communication_id = require_uuid4(closed(request, {"communication_id"})["communication_id"])
    row = reader.connection.execute(
        "SELECT c.source_scope_id,c.identity_state,c.chronology_known,c.chronology_utc,c.chronology_source_kind,"
        "c.direction,c.content_state,c.subject,c.body_kind,c.body_text,r.state "
        "FROM communications c LEFT JOIN communication_retention r USING(communication_id) WHERE c.communication_id=?",
        (communication_id,),
    ).fetchone()
    if row is None:
        raise SomaError("COMM_STALE", "Communication is unavailable")
    if row[10] is None:
        raise IntegrityFailure("Communication has no retention authority")
    purged = row[6] == "PURGED"
    participants, attachments = [], []
    if not purged:
        for participant in reader.connection.execute(
            "SELECT role,ordinal,normalized_address,display_name,contact_id FROM communication_participants "
            "WHERE communication_id=? ORDER BY role,ordinal LIMIT 2001", (communication_id,),
        ):
            participants.append(dict(zip(("role", "ordinal", "address", "display_name", "contact_id"), participant)))
        if len(participants) > 2000:
            raise IntegrityFailure("Communication exceeds the participant bound")
        for attachment in reader.connection.execute(
            "SELECT communication_attachment_id,ordinal,filename,mime_type,size_bytes,sha256 "
            "FROM communication_attachments WHERE communication_id=? ORDER BY ordinal LIMIT 501", (communication_id,),
        ):
            attachments.append(dict(zip(("communication_attachment_id", "ordinal", "filename", "mime_type", "size_bytes", "sha256"), attachment)))
        if len(attachments) > 500:
            raise IntegrityFailure("Communication exceeds the attachment bound")
    links = list_links_in_reader(reader, {"communication_id": communication_id, "state": "ACTIVE", "limit": 100})
    proposal_count = reader.connection.execute(
        "SELECT count(*) FROM communication_proposals WHERE communication_id=?", (communication_id,),
    ).fetchone()[0]
    return {
        "communication_id": communication_id, "source_scope_id": row[0], "identity_state": row[1],
        "chronology": Chronology(bool(row[2]), row[3], row[4]).to_response(), "direction": row[5],
        "content_state": row[6], "subject": None if purged else row[7], "body_kind": "NONE" if purged else row[8],
        "body": None if purged else row[9], "participants": participants, "attachments": attachments,
        "active_links": links["items"], "active_links_next_cursor": links["next_cursor"],
        "proposal_count": proposal_count, "retention_state": row[10],
    }


def list_communications_in_reader(reader, request: dict) -> dict:
    allowed = {"source_scope_id", "target_type", "target_id", "direction", "content_state", "search", "cursor", "limit"}
    if not isinstance(request, dict) or set(request) - allowed:
        raise ValidationError("Communication list query has unknown fields")
    filters = {name: request.get(name) for name in ("source_scope_id", "target_type", "target_id", "direction", "content_state")}
    for name in ("source_scope_id", "target_id"):
        if filters[name] is not None:
            require_uuid4(filters[name])
    for name, values in (("target_type", TARGET_TYPES), ("direction", DIRECTIONS), ("content_state", {"RETAINED", "PURGED"})):
        value = filters[name]
        if value is not None and (not isinstance(value, str) or value not in values):
            raise ValidationError("Communication list enum filter is invalid")
    search = request.get("search")
    if search is not None:
        search = " ".join(text(search).split())
    filters["search"] = search or None
    limit = integer(request.get("limit", 50), minimum=1, maximum=100)
    key = cursor_key(request.get("cursor"), query=LIST_QUERY, filters=filters,
                     null_order="chronology null last", key_length=3)
    conditions, values = [], []
    exact_target = filters["target_type"] is not None and filters["target_id"] is not None
    if exact_target:
        # One active semantic pair is unique. The trigger-maintained canonical
        # ordering projection supports sparse target pages without scanning the
        # global chronology or sorting the complete target collection.
        source = "communication_links l INDEXED BY idx_comm_link_target_canonical_order JOIN communications c ON c.communication_id=l.communication_id"
        conditions.extend(["l.target_type=?", "l.target_id=?", "l.state='ACTIVE'"])
        values.extend([filters["target_type"], filters["target_id"]])
        order = ("l.canonical_chronology_known", "l.canonical_chronology_utc", "l.communication_id")
    else:
        source = "communications c"
        order = ("c.chronology_known", "c.chronology_utc", "c.communication_id")
        link_conditions, link_values = ["l.communication_id=c.communication_id", "l.state='ACTIVE'"], []
        for name in ("target_type", "target_id"):
            if filters[name] is not None:
                link_conditions.append("l." + name + "=?")
                link_values.append(filters[name])
        if link_values:
            conditions.append("EXISTS(SELECT 1 FROM communication_links l WHERE " + " AND ".join(link_conditions) + ")")
            values.extend(link_values)
    for name in ("source_scope_id", "direction", "content_state"):
        if filters[name] is not None:
            conditions.append("c." + name + "=?")
            values.append(filters[name])
    if search:
        literal = " AND ".join('"' + word.replace('"', '""') + '"' for word in search.split(" "))
        conditions.extend(["c.content_state='RETAINED'", "c.rowid IN (SELECT rowid FROM communication_search_fts WHERE communication_search_fts MATCH ?)"])
        values.append(literal)
    if key is not None:
        known = integer(key[0], maximum=1)
        require_uuid4(key[2])
        if known:
            integer(key[1])
            conditions.append(f"({order[0]}=0 OR ({order[0]}=1 AND ({order[1]},{order[2]})<(?,?)))")
            values.extend([key[1], key[2]])
        else:
            if key[1] is not None:
                raise ValidationError("Unknown communication cursor chronology requires a null instant")
            conditions.extend([order[0] + "=0", order[2] + "<?"])
            values.append(key[2])
    where = " WHERE " + " AND ".join(conditions) if conditions else ""
    rows = reader.connection.execute(
        "SELECT c.communication_id,c.source_scope_id,c.identity_state,c.chronology_known,c.chronology_utc,"
        "c.chronology_source_kind,c.direction,c.content_state,c.subject,r.state FROM " + source
        + " LEFT JOIN communication_retention r ON r.communication_id=c.communication_id" + where
        + " ORDER BY " + ",".join(column + " DESC" for column in order) + " LIMIT ?", (*values, limit + 1),
    ).fetchall()
    page = rows[:limit]
    if any(row[9] is None for row in page):
        raise IntegrityFailure("Communication has no retention authority")
    items = [{"communication_id": row[0], "source_scope_id": row[1], "identity_state": row[2],
              "chronology": Chronology(bool(row[3]), row[4], row[5]).to_response(), "direction": row[6],
              "content_state": row[7], "subject": None if row[7] == "PURGED" else row[8], "retention_state": row[9]} for row in page]
    continuation = None
    if len(rows) > limit:
        last = page[-1]
        continuation = next_cursor(query=LIST_QUERY, filters=filters, null_order="chronology null last", key=(last[3], last[4], last[0]))
    return {"items": items, "next_cursor": continuation}


class CommunicationQueries:
    def __init__(self, connection_factory):
        self._factory = connection_factory

    def get_communication(self, request: dict) -> dict:
        with ReadSnapshot(self._factory) as reader:
            return communication_detail_in_reader(reader, request)

    def list_communications(self, request: dict) -> dict:
        with ReadSnapshot(self._factory) as reader:
            return list_communications_in_reader(reader, request)

    def list_communication_links(self, request: dict) -> dict:
        with ReadSnapshot(self._factory) as reader:
            return list_links_in_reader(reader, request)
