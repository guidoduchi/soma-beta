from __future__ import annotations

from typing import Any

from soma.foundation.errors import IntegrityFailure, ValidationError
from soma.foundation.strict_json import loads_canonical_json

JOB_JSON_MAX_BYTES = 65_536
JOB_JSON_MAX_DEPTH = 8
JOB_JSON_MAX_COLLECTION_ITEMS = 512


def load_persisted_job_object(text: str, *, label: str) -> dict[str, Any]:
    """Decode one persisted durable-job object under the shared bounded contract."""
    try:
        value = loads_canonical_json(
            text,
            max_bytes=JOB_JSON_MAX_BYTES,
            max_depth=JOB_JSON_MAX_DEPTH,
            max_collection_items=JOB_JSON_MAX_COLLECTION_ITEMS,
        )
    except ValidationError as exc:
        raise IntegrityFailure(f"persisted {label} is not canonical JSON") from exc
    if not isinstance(value, dict):
        raise IntegrityFailure(f"persisted {label} must be an object")
    return value


__all__ = [
    "JOB_JSON_MAX_BYTES",
    "JOB_JSON_MAX_COLLECTION_ITEMS",
    "JOB_JSON_MAX_DEPTH",
    "load_persisted_job_object",
]
