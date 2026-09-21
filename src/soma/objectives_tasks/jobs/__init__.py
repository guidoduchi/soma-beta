from __future__ import annotations

import re
from typing import Any

from soma.foundation.errors import ValidationError
from soma.foundation.identifiers import require_uuid4
from soma.foundation.jobs import JobTypeContract, StaleRecoveryDisposition

GROUPING_RECOMPUTE_JOB_TYPE = "OBJECTIVE_GROUPING_RECOMPUTE_V1"
GROUPING_RECOMPUTE_JOB_CONTRACT_VERSION = 1

GROUPING_ORIGINS = frozenset(
    {
        "task_created",
        "task_plan_changed",
        "source_plan_adopted",
        "manual_request",
        "retry_created",
        "objective_edit",
    }
)
_ACTIVE_STATES = frozenset({"queued", "running", "waiting_review", "retry_wait"})
_PHASES = frozenset({"queued", "scanning", "publishing"})
_RETRYABLE = frozenset({"JOB_INTERRUPTED", "PERSISTENCE_BUSY", "JOB_CLAIM_CONFLICT"})
_RETRY_DELAY_BY_ATTEMPT = {1: 5, 2: 30, 3: 120}
_FAILURE = re.compile(r"^[A-Z][A-Z0-9_]{0,63}$")


def _exact_dict(value: Any, keys: frozenset[str], label: str) -> dict[str, Any]:
    if not isinstance(value, dict) or set(value) != keys:
        raise ValidationError(f"{label} must contain exactly the registered fields")
    return value


def _uuid(value: Any, label: str) -> str:
    if not isinstance(value, str):
        raise ValidationError(f"{label} must be canonical UUIDv4 text")
    try:
        return require_uuid4(value)
    except ValidationError as exc:
        raise ValidationError(f"{label} must be canonical UUIDv4 text") from exc


def validate_grouping_recompute_payload(value: Any) -> None:
    payload = _exact_dict(
        value,
        frozenset({"origin", "requested_by_command_id"}),
        "grouping recompute job payload",
    )
    if payload["origin"] not in GROUPING_ORIGINS:
        raise ValidationError("grouping recompute job origin is invalid")
    _uuid(payload["requested_by_command_id"], "requested_by_command_id")


def validate_grouping_recompute_checkpoint(value: Any) -> None:
    checkpoint = _exact_dict(
        value,
        frozenset({"phase", "published_proposal_count"}),
        "grouping recompute checkpoint",
    )
    if checkpoint["phase"] not in _PHASES:
        raise ValidationError("grouping recompute checkpoint phase is invalid")
    count = checkpoint["published_proposal_count"]
    if type(count) is not int or count < 0:
        raise ValidationError("published_proposal_count must be int>=0")


def derive_grouping_recompute_dedupe_key(payload: Any) -> str:
    validate_grouping_recompute_payload(payload)
    return f"{GROUPING_RECOMPUTE_JOB_TYPE}:{payload['origin']}"


def _validate_grouping_recompute_failure(
    error_code: str,
    attempt_ordinal: int,
    now: int,
    retry_at: int | None,
) -> None:
    if not isinstance(error_code, str) or _FAILURE.fullmatch(error_code) is None:
        raise ValidationError("grouping durable failure code is invalid")
    if type(attempt_ordinal) is not int or attempt_ordinal < 1:
        raise ValidationError("grouping durable attempt_ordinal must be int>=1")
    if type(now) is not int or now < 0:
        raise ValidationError("grouping durable failure time is invalid")
    delay = _RETRY_DELAY_BY_ATTEMPT.get(attempt_ordinal)
    if error_code in _RETRYABLE and delay is not None:
        if retry_at != now + delay:
            raise ValidationError("retryable grouping failure uses wrong retry_at")
        return
    if retry_at is not None:
        raise ValidationError("terminal grouping failure requires retry_at=null")


def _validate_grouping_recompute_cancellation(command_context: Any, _state: str) -> None:
    context = _exact_dict(
        command_context,
        frozenset({"command_id"}),
        "grouping recompute cancellation context",
    )
    _uuid(context["command_id"], "grouping cancellation command_id")


def _recover_grouping_recompute_stale(
    payload: Any,
    checkpoint: Any | None,
    attempt_ordinal: int,
    now: int,
) -> StaleRecoveryDisposition:
    validate_grouping_recompute_payload(payload)
    if checkpoint is not None:
        validate_grouping_recompute_checkpoint(checkpoint)
    if type(attempt_ordinal) is not int or attempt_ordinal < 1:
        raise ValidationError("grouping recovery attempt_ordinal must be int>=1")
    if type(now) is not int or now < 0:
        raise ValidationError("grouping recovery time is invalid")
    if attempt_ordinal <= 3:
        return StaleRecoveryDisposition(
            state="retry_wait",
            next_attempt_at_utc=now,
            error_code="JOB_INTERRUPTED",
        )
    return StaleRecoveryDisposition(
        state="failed",
        error_code="JOB_INTERRUPTED",
    )


GROUPING_RECOMPUTE_JOB_CONTRACT = JobTypeContract(
    job_type=GROUPING_RECOMPUTE_JOB_TYPE,
    contract_version=GROUPING_RECOMPUTE_JOB_CONTRACT_VERSION,
    validate_payload=validate_grouping_recompute_payload,
    validate_checkpoint=validate_grouping_recompute_checkpoint,
    derive_dedupe_key=derive_grouping_recompute_dedupe_key,
    coalesce_states=_ACTIVE_STATES,
    validate_failure=_validate_grouping_recompute_failure,
    validate_cancellation=_validate_grouping_recompute_cancellation,
    recover_stale=_recover_grouping_recompute_stale,
)

OBJECTIVES_TASKS_JOB_CONTRACTS = (GROUPING_RECOMPUTE_JOB_CONTRACT,)

__all__ = [
    "GROUPING_ORIGINS",
    "GROUPING_RECOMPUTE_JOB_CONTRACT",
    "GROUPING_RECOMPUTE_JOB_CONTRACT_VERSION",
    "GROUPING_RECOMPUTE_JOB_TYPE",
    "OBJECTIVES_TASKS_JOB_CONTRACTS",
    "derive_grouping_recompute_dedupe_key",
    "validate_grouping_recompute_checkpoint",
    "validate_grouping_recompute_payload",
]
