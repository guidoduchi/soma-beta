from __future__ import annotations


def cursor_envelope(
    *,
    query_id: str,
    sort_id: str,
    last_key: list[object],
    filter_fingerprint: str,
) -> dict[str, object]:
    """Build the shared Product-Line/SLA CursorV1 envelope only.

    Query-specific validation, key typing, filter fingerprints and sort registries
    remain owned by each query module.
    """
    return {
        "version": 1,
        "query_id": query_id,
        "sort_registry_id": sort_id,
        "last_key_tuple": last_key,
        "filter_fingerprint": filter_fingerprint,
        "null_order": "none",
    }
