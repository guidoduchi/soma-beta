from __future__ import annotations

from soma.foundation.errors import IntegrityFailure, ValidationError
from soma.foundation.identifiers import require_uuid4
from soma.foundation.persistence.uow import ReadSnapshot

from soma.communications.contracts.common import integer, text
from soma.communications.contracts.queries import cursor_key, next_cursor

HEALTH_STATES = frozenset({"READY", "MISSING", "LOCKED", "CORRUPT", "UNSUPPORTED", "PARTIAL", "UNPROBED"})
QUERY = "ListCommunicationSourceScopes"


def list_sources_in_reader(reader, request: dict) -> dict:
    if not isinstance(request, dict) or set(request) - {"health_state", "cursor", "limit"}:
        raise ValidationError("Communication source query has unknown fields")
    health = request.get("health_state")
    if health is not None and (not isinstance(health, str) or health not in HEALTH_STATES):
        raise ValidationError("Communication source health filter is invalid")
    limit = integer(request.get("limit", 50), minimum=1, maximum=100)
    filters = {"health_state": health}
    key = cursor_key(request.get("cursor"), query=QUERY, filters=filters, null_order="none", key_length=2)
    conditions, values = [], []
    if health is not None:
        conditions.append("health_state=?")
        values.append(health)
    if key is not None:
        text(key[0], minimum=1, maximum=2048)
        require_uuid4(key[1])
        conditions.append("(display_name_folded,source_scope_id)>(?,?)")
        values.extend(key)
    where = " WHERE " + " AND ".join(conditions) if conditions else ""
    rows = reader.connection.execute(
        "SELECT source_scope_id,revision,display_name,health_state,processing_enabled,display_name_folded "
        "FROM communication_source_scopes" + where + " ORDER BY display_name_folded,source_scope_id LIMIT ?",
        (*values, limit + 1),
    ).fetchall()
    page = rows[:limit]
    folders: dict[str, list] = {row[0]: [] for row in page}
    if page:
        # One bounded read for the entire page. The maximum result is 100 * 64.
        placeholders = ",".join("?" for _ in page)
        for scope, folder_key, role, name in reader.connection.execute(
            "SELECT source_scope_id,provider_folder_key,role,display_name FROM communication_source_folders "
            f"WHERE source_scope_id IN ({placeholders}) AND enabled=1 ORDER BY source_scope_id,provider_folder_key",
            tuple(folders),
        ):
            selected = folders[scope]
            if len(selected) == 64:
                raise IntegrityFailure("Communication source exceeds the selected-folder bound")
            selected.append({"folder_key": folder_key, "role": role, "display_name": name})
    items = [{"source_scope_id": row[0], "revision": row[1], "display_name": row[2], "health_state": row[3],
              "processing_enabled": bool(row[4]), "selected_folders": folders[row[0]]} for row in page]
    continuation = None
    if len(rows) > limit:
        continuation = next_cursor(query=QUERY, filters=filters, null_order="none", key=(page[-1][5], page[-1][0]))
    return {"items": items, "next_cursor": continuation}


class SourceQueries:
    def __init__(self, connection_factory):
        self._factory = connection_factory

    def list_source_scopes(self, request: dict) -> dict:
        with ReadSnapshot(self._factory) as reader:
            return list_sources_in_reader(reader, request)
