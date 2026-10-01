from __future__ import annotations

from dataclasses import dataclass, fields

from soma.foundation.errors import ValidationError
from soma.foundation.identifiers import require_uuid4
from soma.foundation.strict_json import canonical_json_bytes_bounded

from .common import Chronology, closed, integer, text
from .source import ProviderCheckpoint

JOB_KINDS = frozenset({"ORDINARY", "TARGETED_BACKFILL", "DEEP_SCAN", "IDENTITY_RECONCILIATION", "ORPHAN_HOUSEKEEPING"})


@dataclass(frozen=True, slots=True)
class CommunicationExecutionConfig:
    adapter_family: str
    adapter_version: str
    overlap_messages: int
    batch_messages: int

    def __post_init__(self):
        text(self.adapter_family, minimum=1)
        text(self.adapter_version, minimum=1)
        integer(self.overlap_messages, maximum=500)
        integer(self.batch_messages, minimum=1, maximum=500)
        validate_job_json(self.to_response())

    @classmethod
    def from_value(cls, value):
        return cls(**closed(value, {field.name for field in fields(cls)}))

    def to_response(self):
        return {field.name: getattr(self, field.name) for field in fields(self)}


def validate_job_json(value: dict) -> dict:
    # The Foundation envelope budget applies unchanged to owner payloads.
    canonical_json_bytes_bounded(value, max_bytes=65_536, max_depth=8, max_collection_items=512)
    return value


def bound_from_value(value) -> Chronology | ProviderCheckpoint | None:
    if value is None:
        return None
    if isinstance(value, dict) and "known" in value:
        return Chronology.from_value(value)
    return ProviderCheckpoint.from_value(value)


@dataclass(frozen=True, slots=True)
class CommunicationJobScope:
    source_scope_id: str | None
    folder_keys: tuple[str, ...]
    job_kind: str
    lower_bound: Chronology | ProviderCheckpoint | None
    upper_bound: Chronology | ProviderCheckpoint | None
    target_identity_ids: tuple[str, ...]
    config_revision: int | None

    def __post_init__(self):
        if not isinstance(self.job_kind, str) or self.job_kind not in JOB_KINDS:
            raise ValidationError("Communication job kind is invalid")
        if not isinstance(self.folder_keys, tuple) or not isinstance(self.target_identity_ids, tuple):
            raise ValidationError("Communication job collections require immutable tuples")
        for key in self.folder_keys:
            text(key, minimum=1, maximum=512)
        for identity in self.target_identity_ids:
            text(identity, minimum=1)
        if len(self.folder_keys) > 64 or len(set(self.folder_keys)) != len(self.folder_keys):
            raise ValidationError("Communication job folders exceed the bound or are duplicated")
        if len(set(self.target_identity_ids)) != len(self.target_identity_ids):
            raise ValidationError("Communication job identities are duplicated")
        for bound in (self.lower_bound, self.upper_bound):
            if bound is not None and not isinstance(bound, (Chronology, ProviderCheckpoint)):
                raise ValidationError("Communication job range requires typed bounds")
        if self.job_kind == "ORPHAN_HOUSEKEEPING":
            if (self.source_scope_id is not None or self.config_revision is not None or self.folder_keys
                    or self.target_identity_ids or self.lower_bound is not None or self.upper_bound is not None):
                raise ValidationError("Housekeeping requires the exact installation-wide scope")
        else:
            require_uuid4(self.source_scope_id)
            integer(self.config_revision, minimum=1)
        validate_job_json(self.to_response())

    @classmethod
    def from_value(cls, value):
        item = dict(closed(value, {field.name for field in fields(cls)}))
        for name in ("folder_keys", "target_identity_ids"):
            if not isinstance(item[name], list):
                raise ValidationError("Communication job scope requires JSON arrays")
            item[name] = tuple(item[name])
        for name in ("lower_bound", "upper_bound"):
            item[name] = bound_from_value(item[name])
        return cls(**item)

    def to_response(self):
        return {"source_scope_id": self.source_scope_id, "folder_keys": list(self.folder_keys), "job_kind": self.job_kind,
                "lower_bound": None if self.lower_bound is None else self.lower_bound.to_response(),
                "upper_bound": None if self.upper_bound is None else self.upper_bound.to_response(),
                "target_identity_ids": list(self.target_identity_ids), "config_revision": self.config_revision}


@dataclass(frozen=True, slots=True)
class CommunicationJobCounters:
    discovered: int = 0
    inspected: int = 0
    matched: int = 0
    retained: int = 0
    unchanged: int = 0
    proposed: int = 0
    skipped: int = 0
    warnings: int = 0
    failures: int = 0
    estimated_total: int | None = None

    def __post_init__(self):
        for field in fields(self):
            value = getattr(self, field.name)
            if field.name != "estimated_total" or value is not None:
                integer(value)

    @classmethod
    def from_value(cls, value):
        return cls(**closed(value, {field.name for field in fields(cls)}))

    def to_response(self):
        return {field.name: getattr(self, field.name) for field in fields(self)}

    @property
    def percentage(self):
        if self.estimated_total is None or self.estimated_total == 0:
            return None
        return min(100.0, self.inspected * 100.0 / self.estimated_total)


@dataclass(frozen=True, slots=True)
class CommunicationJobCheckpoint:
    scope: CommunicationJobScope
    last_committed_provider_checkpoint: ProviderCheckpoint | None
    counters: CommunicationJobCounters
    coverage_segment_ids: tuple[str, ...]

    def __post_init__(self):
        if not isinstance(self.scope, CommunicationJobScope) or not isinstance(self.counters, CommunicationJobCounters):
            raise ValidationError("Communication checkpoint requires typed scope and counters")
        if self.last_committed_provider_checkpoint is not None and not isinstance(self.last_committed_provider_checkpoint, ProviderCheckpoint):
            raise ValidationError("Communication checkpoint requires typed provider position")
        if not isinstance(self.coverage_segment_ids, tuple):
            raise ValidationError("Communication checkpoint segments require an immutable tuple")
        for segment in self.coverage_segment_ids:
            require_uuid4(segment)
        if len(set(self.coverage_segment_ids)) != len(self.coverage_segment_ids):
            raise ValidationError("Communication checkpoint segments are duplicated")
        if self.scope.job_kind == "ORPHAN_HOUSEKEEPING" and (self.last_committed_provider_checkpoint is not None or self.coverage_segment_ids):
            raise ValidationError("Housekeeping has no provider position or mail coverage")
        validate_job_json(self.to_response())

    @classmethod
    def from_value(cls, value):
        item = closed(value, {field.name for field in fields(cls)})
        segments = item["coverage_segment_ids"]
        if not isinstance(segments, list):
            raise ValidationError("Communication checkpoint requires a segment array")
        provider = item["last_committed_provider_checkpoint"]
        return cls(CommunicationJobScope.from_value(item["scope"]),
                   None if provider is None else ProviderCheckpoint.from_value(provider),
                   CommunicationJobCounters.from_value(item["counters"]), tuple(segments))

    def to_response(self):
        return {"scope": self.scope.to_response(),
                "last_committed_provider_checkpoint": None if self.last_committed_provider_checkpoint is None else self.last_committed_provider_checkpoint.to_response(),
                "counters": self.counters.to_response(), "coverage_segment_ids": list(self.coverage_segment_ids)}
