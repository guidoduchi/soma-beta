from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

from soma.foundation.errors import ValidationError
from soma.foundation.identifiers import require_uuid4

_SHA256_HEX_RE = re.compile(r"[0-9a-f]{64}\Z")
_PARTICIPANT_DOMAINS = frozenset({"TASKS_OBJECTIVES", "COMMUNICATIONS"})


def _require_sha256(value: object, *, field: str) -> str:
    if not isinstance(value, str) or _SHA256_HEX_RE.fullmatch(value) is None:
        raise ValidationError(f"{field} must be lowercase SHA-256")
    return value


@dataclass(frozen=True, slots=True)
class RfcTerminalCascadeExecutionReview:
    """Bounded reviewed authority carried from READY preview into execution."""

    preview_fingerprint: str
    task_objective_exact_count: int
    task_objective_provider_fingerprint: str
    communication_exact_count: int
    communication_provider_fingerprint: str

    def __post_init__(self) -> None:
        _require_sha256(
            self.preview_fingerprint,
            field="terminal cascade execution review preview fingerprint",
        )
        if type(self.task_objective_exact_count) is not int or self.task_objective_exact_count < 0:
            raise ValidationError("terminal cascade execution review Task/Objective count must be a non-negative integer")
        _require_sha256(
            self.task_objective_provider_fingerprint,
            field="terminal cascade execution review Task/Objective fingerprint",
        )
        if type(self.communication_exact_count) is not int or self.communication_exact_count < 0:
            raise ValidationError("terminal cascade execution review Communication count must be a non-negative integer")
        _require_sha256(
            self.communication_provider_fingerprint,
            field="terminal cascade execution review Communication fingerprint",
        )

    def to_response(self) -> dict[str, Any]:
        return {
            "preview_fingerprint": self.preview_fingerprint,
            "task_objective_exact_count": self.task_objective_exact_count,
            "task_objective_provider_fingerprint": self.task_objective_provider_fingerprint,
            "communication_exact_count": self.communication_exact_count,
            "communication_provider_fingerprint": self.communication_provider_fingerprint,
        }


@dataclass(frozen=True, slots=True)
class RfcTerminalCascadeExecutionCommandContext:
    """Non-secret outer command provenance passed to cross-domain apply participants."""

    command_id: str
    actor_kind: str
    actor_id: str | None
    reviewed_preview_fingerprint: str

    def __post_init__(self) -> None:
        try:
            require_uuid4(self.command_id)
        except ValidationError as exc:
            raise ValidationError("terminal cascade execution command context command_id must be canonical UUIDv4") from exc
        if not isinstance(self.actor_kind, str) or not self.actor_kind or len(self.actor_kind.encode("utf-8")) > 128:
            raise ValidationError("terminal cascade execution command context actor_kind is invalid")
        if self.actor_id is not None:
            try:
                require_uuid4(self.actor_id)
            except ValidationError as exc:
                raise ValidationError("terminal cascade execution command context actor_id must be canonical UUIDv4 or null") from exc
        _require_sha256(
            self.reviewed_preview_fingerprint,
            field="terminal cascade execution command context preview fingerprint",
        )


@dataclass(frozen=True, slots=True)
class RfcTerminalCascadeParticipantApplyResult:
    """Bounded post-apply correlation summary; complete result history stays provider-owned."""

    domain: str
    result_ref_count: int
    audit_event_count: int
    result_fingerprint: str

    def __post_init__(self) -> None:
        if self.domain not in _PARTICIPANT_DOMAINS:
            raise ValidationError("terminal cascade participant apply result domain is invalid")
        if type(self.result_ref_count) is not int or self.result_ref_count < 0:
            raise ValidationError("terminal cascade participant result_ref_count must be a non-negative integer")
        if type(self.audit_event_count) is not int or self.audit_event_count < 0:
            raise ValidationError("terminal cascade participant audit_event_count must be a non-negative integer")
        _require_sha256(
            self.result_fingerprint,
            field="terminal cascade participant result fingerprint",
        )

    def to_payload(self) -> dict[str, object]:
        return {
            "domain": self.domain,
            "result_ref_count": self.result_ref_count,
            "audit_event_count": self.audit_event_count,
            "result_fingerprint": self.result_fingerprint,
        }
