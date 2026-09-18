from __future__ import annotations

import re
from typing import Any

from soma.foundation.errors import ValidationError
from soma.foundation.identifiers import require_uuid4
from soma.foundation.jobs import JobTypeContract, StaleRecoveryDisposition

SLA_REPORT_JOB_TYPE = "SLA_REPORT_GENERATION_V1"
SLA_REPORT_JOB_CONTRACT_VERSION = 1

_ACTIVE_STATES = frozenset({"queued", "running", "waiting_review", "retry_wait"})
_PHASES = frozenset(
    {
        "snapshotting",
        "sealed",
        "writing",
        "verifying",
        "publishing",
        "completing",
        "terminal",
    }
)
_PENDING_KINDS = frozenset(
    {
        "stage_batch",
        "seal",
        "mark_generating",
        "mark_verifying",
        "complete",
        "fail",
        "cancel",
    }
)
_RETRYABLE = frozenset(
    {
        "JOB_INTERRUPTED",
        "PERSISTENCE_BUSY",
        "SLA_REPORT_FILESYSTEM_TRANSIENT",
        "SLA_REPORT_VERIFY_TRANSIENT",
    }
)
_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_FAILURE = re.compile(r"^[A-Z][A-Z0-9_]{0,63}$")


def _dict(value: Any, keys: frozenset[str], label: str) -> dict[str, Any]:
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


def _sha(value: Any, label: str) -> str:
    if not isinstance(value, str) or _SHA256.fullmatch(value) is None:
        raise ValidationError(f"{label} must be lowercase SHA-256 hex")
    return value


def _positive(value: Any, label: str) -> int:
    if type(value) is not int or value < 1:
        raise ValidationError(f"{label} must be int>=1")
    return value


def _filename(value: Any, label: str) -> str:
    if (
        not isinstance(value, str)
        or not value
        or len(value.encode("utf-8")) > 4096
        or any(ch in value for ch in ("/", "\\", "\x00"))
        or value in {".", ".."}
    ):
        raise ValidationError(f"{label} must be a bounded filename-only identity")
    return value


def validate_report_job_payload(value: Any) -> None:
    payload = _dict(
        value,
        frozenset(
            {
                "report_attempt_id",
                "destination_request_token",
                "requested_by_command_id",
            }
        ),
        "SLA report job payload",
    )
    _uuid(payload["report_attempt_id"], "report_attempt_id")
    _sha(payload["destination_request_token"], "destination_request_token")
    _uuid(payload["requested_by_command_id"], "requested_by_command_id")


def _validate_pending(value: Any) -> None:
    if value is None:
        return
    pending = _dict(
        value,
        frozenset(
            {
                "kind",
                "command_id",
                "expected_attempt_revision",
                "request_fingerprint",
                "batch_ordinal",
                "batch_payload_sha256",
                "snapshot_hash",
                "candidate_filename",
                "completion_proof_fingerprint",
            }
        ),
        "SLA report pending command",
    )
    kind = pending["kind"]
    if kind not in _PENDING_KINDS:
        raise ValidationError("SLA report pending command kind is invalid")
    _uuid(pending["command_id"], "pending command_id")
    _positive(pending["expected_attempt_revision"], "pending expected_attempt_revision")
    _sha(pending["request_fingerprint"], "pending request_fingerprint")

    batch_ordinal = pending["batch_ordinal"]
    batch_hash = pending["batch_payload_sha256"]
    if kind == "stage_batch":
        _positive(batch_ordinal, "pending batch_ordinal")
        _sha(batch_hash, "pending batch_payload_sha256")
    elif batch_ordinal is not None or batch_hash is not None:
        raise ValidationError("non-stage pending command cannot carry batch identity")

    snapshot_hash = pending["snapshot_hash"]
    if kind in {"seal", "mark_generating", "mark_verifying", "complete"}:
        _sha(snapshot_hash, "pending snapshot_hash")
    elif snapshot_hash is not None:
        raise ValidationError("pending command carries an unexpected snapshot hash")

    candidate = pending["candidate_filename"]
    if kind == "mark_verifying":
        _filename(candidate, "pending candidate_filename")
    elif candidate is not None:
        raise ValidationError("pending command carries an unexpected candidate filename")

    proof = pending["completion_proof_fingerprint"]
    if kind == "complete":
        _sha(proof, "pending completion_proof_fingerprint")
    elif proof is not None:
        raise ValidationError("pending command carries an unexpected completion proof")


def _validate_published_artifact(value: Any) -> None:
    if value is None:
        return
    artifact = _dict(
        value,
        frozenset(
            {
                "candidate_filename",
                "final_filename",
                "artifact_sha256",
                "artifact_size_bytes",
                "verified_at_utc",
                "snapshot_hash",
                "completion_command_id",
            }
        ),
        "SLA report published artifact checkpoint",
    )
    _filename(artifact["candidate_filename"], "candidate_filename")
    _filename(artifact["final_filename"], "final_filename")
    _sha(artifact["artifact_sha256"], "artifact_sha256")
    _positive(artifact["artifact_size_bytes"], "artifact_size_bytes")
    if type(artifact["verified_at_utc"]) is not int or artifact["verified_at_utc"] < 0:
        raise ValidationError("verified_at_utc must be a nonnegative UTC epoch second")
    _sha(artifact["snapshot_hash"], "snapshot_hash")
    _uuid(artifact["completion_command_id"], "completion_command_id")


def validate_report_job_checkpoint(value: Any) -> None:
    checkpoint = _dict(
        value,
        frozenset(
            {
                "phase",
                "attempt_revision",
                "snapshot_generation_token",
                "next_batch_ordinal",
                "pending_command",
                "candidate_filename",
                "published_artifact",
            }
        ),
        "SLA report checkpoint",
    )
    if checkpoint["phase"] not in _PHASES:
        raise ValidationError("SLA report checkpoint phase is invalid")
    _positive(checkpoint["attempt_revision"], "attempt_revision")

    token = checkpoint["snapshot_generation_token"]
    if token is not None:
        if (
            not isinstance(token, str)
            or not token
            or len(token.encode("utf-8")) > 256
        ):
            raise ValidationError("snapshot_generation_token is invalid")
    if checkpoint["phase"] == "snapshotting" and token is None:
        raise ValidationError("snapshotting checkpoint requires generation token")

    next_batch = checkpoint["next_batch_ordinal"]
    if next_batch is not None:
        _positive(next_batch, "next_batch_ordinal")

    candidate = checkpoint["candidate_filename"]
    if candidate is not None:
        _filename(candidate, "candidate_filename")
    if checkpoint["phase"] == "verifying" and candidate is None:
        raise ValidationError("verifying checkpoint requires candidate filename")

    _validate_pending(checkpoint["pending_command"])
    _validate_published_artifact(checkpoint["published_artifact"])


def derive_report_job_dedupe_key(payload: Any) -> str:
    validate_report_job_payload(payload)
    return str(payload["report_attempt_id"])


def _validate_report_failure(
    error_code: str,
    attempt_ordinal: int,
    now: int,
    retry_at: int | None,
) -> None:
    if not isinstance(error_code, str) or _FAILURE.fullmatch(error_code) is None:
        raise ValidationError("SLA report durable failure code is invalid")
    _positive(attempt_ordinal, "attempt_ordinal")
    if type(now) is not int or now < 0:
        raise ValidationError("failure time is invalid")
    if error_code in _RETRYABLE and attempt_ordinal <= 3:
        if type(retry_at) is not int or retry_at < now:
            raise ValidationError("retryable SLA report failure requires retry_at>=now")
    elif retry_at is not None:
        raise ValidationError("terminal SLA report failure requires retry_at=null")


def _validate_report_cancellation(command_context: Any, _state: str) -> None:
    context = _dict(
        command_context,
        frozenset({"report_attempt_id", "command_id"}),
        "SLA report cancellation context",
    )
    _uuid(context["report_attempt_id"], "report cancellation report_attempt_id")
    _uuid(context["command_id"], "report cancellation command_id")


def _recover_report_stale(
    _payload: Any,
    checkpoint: Any | None,
    attempt_ordinal: int,
    now: int,
) -> StaleRecoveryDisposition:
    _positive(attempt_ordinal, "attempt_ordinal")
    if type(now) is not int or now < 0:
        raise ValidationError("recovery time is invalid")
    if checkpoint is not None:
        validate_report_job_checkpoint(checkpoint)

    # Foundation cannot safely terminalize this job by itself because LLD-06 owns
    # report-attempt state and staging cleanup. Every stale report claim therefore
    # receives one reconciliation claim. A snapshotting reconciliation is cleanup
    # only; it never resumes mutable live-domain reads.
    return StaleRecoveryDisposition(
        state="retry_wait",
        next_attempt_at_utc=now,
        error_code="JOB_INTERRUPTED",
    )


SLA_REPORT_JOB_CONTRACT = JobTypeContract(
    job_type=SLA_REPORT_JOB_TYPE,
    contract_version=SLA_REPORT_JOB_CONTRACT_VERSION,
    validate_payload=validate_report_job_payload,
    validate_checkpoint=validate_report_job_checkpoint,
    derive_dedupe_key=derive_report_job_dedupe_key,
    coalesce_states=_ACTIVE_STATES,
    validate_failure=_validate_report_failure,
    validate_cancellation=_validate_report_cancellation,
    recover_stale=_recover_report_stale,
)

PRODUCT_LINE_SLA_JOB_CONTRACTS = (SLA_REPORT_JOB_CONTRACT,)

__all__ = [
    "PRODUCT_LINE_SLA_JOB_CONTRACTS",
    "SLA_REPORT_JOB_CONTRACT",
    "SLA_REPORT_JOB_CONTRACT_VERSION",
    "SLA_REPORT_JOB_TYPE",
    "derive_report_job_dedupe_key",
    "validate_report_job_checkpoint",
    "validate_report_job_payload",
]
