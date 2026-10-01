from __future__ import annotations

from typing import Any

from soma.foundation.errors import ValidationError
from soma.foundation.strict_json import sha256_canonical_json

from .common import closed


def cursor_key(cursor: Any, *, query: str, filters: dict, null_order: str, key_length: int) -> tuple | None:
    if cursor is None:
        return None
    value = closed(cursor, {"version", "query_id", "sort_registry_id", "last_key_tuple", "filter_fingerprint", "null_order"})
    if (type(value["version"]) is not int or value["version"] != 1
            or value["query_id"] != query or value["sort_registry_id"] != query + "_ORDER_V1"
            or value["null_order"] != null_order
            or value["filter_fingerprint"] != sha256_canonical_json(filters)):
        raise ValidationError("Communication cursor does not match the query contract and filters")
    key = value["last_key_tuple"]
    if not isinstance(key, list) or len(key) != key_length:
        raise ValidationError("Communication cursor ordering key is incomplete")
    return tuple(key)


def next_cursor(*, query: str, filters: dict, null_order: str, key: tuple) -> dict:
    return {"version": 1, "query_id": query, "sort_registry_id": query + "_ORDER_V1",
            "last_key_tuple": list(key), "filter_fingerprint": sha256_canonical_json(filters), "null_order": null_order}
