from __future__ import annotations

from typing import Any

from soma.foundation.errors import ValidationError
from soma.foundation.strict_json import sha256_canonical_json

_CURSOR_FIELDS = {
    "version",
    "query_id",
    "sort_registry_id",
    "last_key_tuple",
    "filter_fingerprint",
    "null_order",
}


def filter_fingerprint(payload: dict[str, object]) -> str:
    return sha256_canonical_json(payload)


def encode_cursor(
    *,
    query_id: str,
    sort_registry_id: str,
    last_key_tuple: tuple[object, ...],
    filter_payload: dict[str, object],
    null_order: str = "not_applicable",
) -> dict[str, Any]:
    return {
        "version": 1,
        "query_id": query_id,
        "sort_registry_id": sort_registry_id,
        "last_key_tuple": list(last_key_tuple),
        "filter_fingerprint": filter_fingerprint(filter_payload),
        "null_order": null_order,
    }


def decode_cursor(
    cursor: object,
    *,
    query_id: str,
    sort_registry_id: str,
    filter_payload: dict[str, object],
    key_length: int,
    null_order: str = "not_applicable",
) -> tuple[object, ...] | None:
    if cursor is None:
        return None
    if not isinstance(cursor, dict) or set(cursor) != _CURSOR_FIELDS:
        raise ValidationError("Reference cursor fields are invalid")
    if (
        cursor["version"] != 1
        or cursor["query_id"] != query_id
        or cursor["sort_registry_id"] != sort_registry_id
        or cursor["null_order"] != null_order
    ):
        raise ValidationError("Reference cursor contract is invalid")
    if cursor["filter_fingerprint"] != filter_fingerprint(filter_payload):
        raise ValidationError("Reference cursor filter fingerprint is stale")
    key = cursor["last_key_tuple"]
    if not isinstance(key, list) or len(key) != key_length:
        raise ValidationError("Reference cursor key tuple is invalid")
    return tuple(key)
