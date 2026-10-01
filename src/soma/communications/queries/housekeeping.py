from __future__ import annotations

from soma.communications.contracts.common import integer
from soma.communications.contracts.queries import cursor_key, next_cursor
from soma.foundation.errors import IntegrityFailure, ValidationError
from soma.foundation.identifiers import require_uuid4
from soma.foundation.persistence.uow import ReadSnapshot

QUERY = "ListCommunicationHousekeeping"
STATES = ("ORPHAN_PENDING_PURGE", "PURGED")


def list_housekeeping_in_reader(reader, request):
    if not isinstance(request, dict) or set(request) - {"state", "due_before_utc", "cursor", "limit"}:
        raise ValidationError("Communication housekeeping query has unknown fields")
    filters = {name: request.get(name) for name in ("state", "due_before_utc")}
    if filters["state"] is not None and (not isinstance(filters["state"], str) or filters["state"] not in STATES):
        raise ValidationError("Communication housekeeping state is invalid")
    cutoff = filters["due_before_utc"]
    if cutoff is not None:
        integer(cutoff)
    limit = integer(request.get("limit", 50), minimum=1, maximum=100)
    key = cursor_key(request.get("cursor"), query=QUERY, filters=filters, null_order="due null last", key_length=3)
    if key is not None:
        integer(key[0], maximum=1)
        if key[1] is not None:
            integer(key[1])
        require_uuid4(key[2])
        if filters["state"] is not None and STATES[key[0]] != filters["state"]:
            raise ValidationError("Housekeeping cursor state disagrees with its filter")
    rows = []
    # Split null/non-null and the two states into bounded indexed ranges. This
    # preserves the complete ordering key without sorting the whole collection.
    for rank, state in enumerate(STATES):
        if (filters["state"] is not None and state != filters["state"]) or (key is not None and rank < key[0]):
            continue
        for null_due in (False, True):
            if null_due and cutoff is not None:
                continue
            if key is not None and rank == key[0] and key[1] is None and not null_due:
                continue
            conditions = ["r.state=?", "r.purge_due_utc IS NULL" if null_due else "r.purge_due_utc IS NOT NULL"]
            values = [state]
            if cutoff is not None:
                # 'before' is an exclusive observation filter. Due-purge's
                # separate authoritative eligibility remains due <= now.
                conditions.append("r.purge_due_utc<?")
                values.append(cutoff)
            if key is not None and rank == key[0]:
                if null_due and key[1] is None:
                    conditions.append("r.communication_id>?")
                    values.append(key[2])
                elif not null_due:
                    conditions.append("(r.purge_due_utc,r.communication_id)>(?,?)")
                    values.extend(key[1:])
            remaining = limit + 1 - len(rows)
            if remaining <= 0:
                break
            rows.extend(reader.connection.execute(
                "SELECT r.communication_id,r.state,r.purge_due_utc,e.reason_code,e.to_state "
                "FROM communication_retention r LEFT JOIN communication_retention_events e "
                "ON e.communication_id=r.communication_id AND e.resulting_retention_revision=r.revision WHERE " +
                " AND ".join(conditions) + " ORDER BY r.purge_due_utc,r.communication_id LIMIT ?", (*values, remaining),
            ).fetchall())
    page = rows[:limit]
    counts = {}
    if page:
        ids = [row[0] for row in page]
        placeholders = ",".join("?" for _ in ids)
        for table in ("communication_links", "communication_protection_holds"):
            for identity, count in reader.connection.execute(
                f"SELECT communication_id,COUNT(*) FROM {table} WHERE state='ACTIVE' "
                f"AND communication_id IN ({placeholders}) GROUP BY communication_id", ids,
            ):
                counts[identity] = counts.get(identity, 0) + count
    items = []
    for identity, state, due, reason, event_state in page:
        if reason is None or event_state != state:
            raise IntegrityFailure("Communication retention lacks its exact current transition evidence")
        items.append({"communication_id": identity, "state": state, "purge_due_utc": due,
                      "reason_code": reason, "protected_dependency_count": counts.get(identity, 0)})
    continuation = None
    if len(rows) > limit:
        last = page[-1]
        continuation = next_cursor(query=QUERY, filters=filters, null_order="due null last", key=(STATES.index(last[1]), last[2], last[0]))
    return {"items": items, "next_cursor": continuation}


class HousekeepingQueries:
    def __init__(self, connection_factory):
        self._factory = connection_factory

    def list_housekeeping(self, request):
        with ReadSnapshot(self._factory) as reader:
            return list_housekeeping_in_reader(reader, request)
