from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

from soma.foundation.errors import ValidationError
from soma.foundation.identifiers import require_uuid4

TARGET_TYPES = frozenset({"SERVICE_REQUEST", "SPARE_REQUEST", "RMA", "RFC", "WFM_TASK", "OBJECTIVE", "FAULT_TAG"})
DIRECTIONS = frozenset({"RECEIVED", "SENT", "UNKNOWN"})
MAX_INT64 = (1 << 63) - 1


def integer(value: Any, *, minimum: int = 0, maximum: int = MAX_INT64) -> int:
    if type(value) is not int or not minimum <= value <= maximum:
        raise ValidationError("Communication integer is outside its contract")
    return value


def text(value: Any, *, minimum: int = 0, maximum: int | None = None) -> str:
    if not isinstance(value, str) or (maximum is not None and len(value) > maximum) or len(value) < minimum:
        raise ValidationError("Communication text is outside its contract")
    try:
        value.encode("utf-8", errors="strict")
    except UnicodeError as exc:
        raise ValidationError("Communication text is not valid UTF-8") from exc
    if "\x00" in value:
        raise ValidationError("Communication text contains NUL")
    return value


def fingerprint(value: Any) -> str:
    if not isinstance(value, str) or re.fullmatch(r"[0-9a-f]{64}", value) is None:
        raise ValidationError("Communication fingerprint is invalid")
    return value


def closed(value: Any, fields: set[str]) -> dict:
    if not isinstance(value, dict) or set(value) != fields:
        raise ValidationError("Communication object has missing or unknown fields")
    return value


@dataclass(frozen=True, slots=True)
class Chronology:
    known: bool
    utc_epoch_seconds: int | None
    source_kind: str

    def __post_init__(self) -> None:
        if type(self.known) is not bool:
            raise ValidationError("Communication chronology requires an exact boolean")
        if self.known:
            integer(self.utc_epoch_seconds)
            if not isinstance(self.source_kind, str) or self.source_kind not in {"RECEIVED_TIME", "SENT_TIME", "OTHER_PROVIDER_TIME"}:
                raise ValidationError("Communication chronology source is invalid")
        elif self.utc_epoch_seconds is not None or self.source_kind != "UNKNOWN":
            raise ValidationError("Unknown chronology cannot contain an instant or inferred source")

    @classmethod
    def from_value(cls, value: Any) -> Chronology:
        return cls(**closed(value, {"known", "utc_epoch_seconds", "source_kind"}))

    def to_response(self) -> dict:
        return {"known": self.known, "utc_epoch_seconds": self.utc_epoch_seconds, "source_kind": self.source_kind}


UNKNOWN_CHRONOLOGY = Chronology(False, None, "UNKNOWN")


@dataclass(frozen=True, slots=True)
class TrackableIdentity:
    target_type: str
    target_id: str
    target_revision: int
    identity_kind: str
    normalized_value: str
    effective_from: Chronology

    def __post_init__(self) -> None:
        if not isinstance(self.target_type, str) or self.target_type not in TARGET_TYPES:
            raise ValidationError("Communication target type is invalid")
        require_uuid4(self.target_id)
        integer(self.target_revision, minimum=1)
        text(self.identity_kind, minimum=1, maximum=128)
        text(self.normalized_value, minimum=1, maximum=512)
        if not isinstance(self.effective_from, Chronology):
            raise ValidationError("Communication target requires independently supported chronology")

    @classmethod
    def from_value(cls, value) -> TrackableIdentity:
        item = dict(closed(value, {"target_type", "target_id", "target_revision", "identity_kind", "normalized_value", "effective_from"}))
        item["effective_from"] = Chronology.from_value(item["effective_from"])
        return cls(**item)
