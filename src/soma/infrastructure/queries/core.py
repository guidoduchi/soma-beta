from soma.foundation.errors import SomaError, ValidationError
from soma.foundation.persistence.uow import ReadSnapshot
from soma.infrastructure.contracts.infrastructure import REGISTRY, validate_value
from soma.infrastructure.repositories.core import fingerprint, rows

QUERIES = {spec["name"]: spec for spec in REGISTRY["queries"]}


def cursor_key(query, p, width):
    cursor = p.get("cursor")
    if cursor is None:
        return None
    expected = {"version", "query_id", "sort_registry_id", "last_key_tuple", "filter_fingerprint", "null_order"}
    filters = {key: value for key, value in p.items() if key not in ("cursor", "limit")}
    if (not isinstance(cursor, dict) or set(cursor) != expected or cursor["version"] != 1
        or cursor["query_id"] != query or cursor["sort_registry_id"] != query + "_ORDER_V1"
        or cursor["filter_fingerprint"] != fingerprint(filters)
        or cursor["null_order"] != QUERIES[query].get("pagination", {}).get("null_order", "NOT_APPLICABLE")
        or not isinstance(cursor["last_key_tuple"], list) or len(cursor["last_key_tuple"]) != width
        or any(type(item) not in (str, int) for item in cursor["last_key_tuple"])):
        raise SomaError("CURSOR_INVALID", "Infrastructure cursor does not match this query and filter")
    return cursor["last_key_tuple"]


def make_cursor(query, p, keys):
    return dict(version=1, query_id=query, sort_registry_id=query + "_ORDER_V1",
                last_key_tuple=list(keys), filter_fingerprint=fingerprint(
                    {key: value for key, value in p.items() if key not in ("cursor", "limit")}),
                null_order=QUERIES[query].get("pagination", {}).get("null_order", "NOT_APPLICABLE"))


def page(reader, query, p, sql, params, keys, directions=None):
    directions = directions or ["ASC"] * len(keys)
    last = cursor_key(query, p, len(keys))
    values = list(params)
    where = ""
    if last:
        clauses = []
        for i, (key, direction) in enumerate(zip(keys, directions)):
            clauses.append("(" + " AND ".join([*(previous + "=?" for previous in keys[:i]),
                                                key + ("<?" if direction == "DESC" else ">?")]) + ")")
            values.extend(last[:i + 1])
        where = " WHERE " + " OR ".join(clauses)
    limit = p.get("limit", 100)
    result = rows(reader, "SELECT * FROM (" + sql + ")" + where + " ORDER BY " +
                  ",".join(key + " " + direction for key, direction in zip(keys, directions)) + " LIMIT ?",
                  (*values, limit + 1))
    continuation = make_cursor(query, p, [result[limit - 1][key] for key in keys]) if len(result) > limit else None
    return result[:limit], continuation


class InfrastructureQueries:
    def __init__(self, service):
        self.service = service

    def execute(self, query, payload):
        if query not in QUERIES:
            raise ValidationError("Unknown Infrastructure query")
        p = validate_value(QUERIES[query]["input_type"], payload)
        from . import details, explorer, candidates, history, workbooks
        with ReadSnapshot(self.service.factory) as snapshot:
            for owner in (details, explorer, candidates, history, workbooks):
                if query in owner.QUERY_NAMES:
                    return owner.execute(self.service, snapshot, query, p)
        raise ValidationError("Infrastructure query has no installed owner")
