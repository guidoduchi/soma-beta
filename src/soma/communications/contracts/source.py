from __future__ import annotations

import re
from dataclasses import dataclass

from soma.foundation.errors import ValidationError
from .common import MAX_INT64, closed, integer, text


@dataclass(frozen=True, slots=True)
class SourceFolder:
    folder_key: str
    role: str
    display_name: str

    def __post_init__(self) -> None:
        text(self.folder_key, minimum=1, maximum=512)
        text(self.display_name, maximum=512)
        if not isinstance(self.role, str) or self.role not in {"INBOX", "SENT", "OTHER"}:
            raise ValidationError("Communication folder role is invalid")

    @classmethod
    def from_value(cls, value) -> SourceFolder:
        return cls(**closed(value, {"folder_key", "role", "display_name"}))

    def to_response(self) -> dict:
        return {"folder_key": self.folder_key, "role": self.role, "display_name": self.display_name}


@dataclass(frozen=True, slots=True)
class SourceProbe:
    health: str
    adapter_family: str
    adapter_version: str
    scope_identity_candidate: str | None
    folders: tuple[SourceFolder, ...]

    def __post_init__(self) -> None:
        if not isinstance(self.health, str) or self.health not in {"READY", "MISSING", "LOCKED", "CORRUPT", "UNSUPPORTED", "PARTIAL"}:
            raise ValidationError("Communication source health is invalid")
        text(self.adapter_family, minimum=1)
        text(self.adapter_version, minimum=1)
        if self.scope_identity_candidate is not None:
            text(self.scope_identity_candidate, minimum=1)
        if not isinstance(self.folders, tuple) or any(not isinstance(x, SourceFolder) for x in self.folders):
            raise ValidationError("Communication folders require typed immutable values")
        if len({x.folder_key for x in self.folders}) != len(self.folders):
            raise ValidationError("Communication probe has duplicate folder keys")

    def to_response(self) -> dict:
        return {"health": self.health, "adapter_family": self.adapter_family, "adapter_version": self.adapter_version,
                "scope_identity_candidate": self.scope_identity_candidate, "folders": [x.to_response() for x in self.folders]}


@dataclass(frozen=True, slots=True)
class ProviderCheckpoint:
    checkpoint_kind: str
    opaque_token: str
    provider_time_source_epoch_ms: int | None

    def __post_init__(self) -> None:
        if not isinstance(self.checkpoint_kind, str) or self.checkpoint_kind not in {"POSITION", "TIME", "COMPOSITE"}:
            raise ValidationError("Communication provider checkpoint kind is invalid")
        if not isinstance(self.opaque_token, str) or len(self.opaque_token) > 4096 or re.fullmatch(r"[A-Za-z0-9_-]*", self.opaque_token) is None:
            raise ValidationError("Communication checkpoint token is invalid")
        if self.provider_time_source_epoch_ms is not None:
            integer(self.provider_time_source_epoch_ms, minimum=-MAX_INT64 - 1)

    @classmethod
    def from_value(cls, value) -> ProviderCheckpoint:
        return cls(**closed(value, {"checkpoint_kind", "opaque_token", "provider_time_source_epoch_ms"}))

    def to_response(self) -> dict:
        return {"checkpoint_kind": self.checkpoint_kind, "opaque_token": self.opaque_token,
                "provider_time_source_epoch_ms": self.provider_time_source_epoch_ms}
