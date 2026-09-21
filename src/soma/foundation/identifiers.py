from __future__ import annotations

import time
import uuid

from .errors import ValidationError


def new_uuid4() -> str:
    return str(uuid.uuid4())


def require_uuid4(value: str) -> str:
    try:
        parsed = uuid.UUID(value)
    except (ValueError, TypeError, AttributeError) as exc:
        raise ValidationError("expected canonical lowercase UUIDv4") from exc
    if parsed.version != 4 or str(parsed) != value or value.lower() != value:
        raise ValidationError("expected canonical lowercase UUIDv4")
    return value


def utc_epoch_seconds() -> int:
    return time.time_ns() // 1_000_000_000


def monotonic_ns() -> int:
    return time.monotonic_ns()
