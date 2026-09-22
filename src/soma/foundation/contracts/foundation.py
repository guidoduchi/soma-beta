from __future__ import annotations

from dataclasses import dataclass
from typing import Literal


DurableJobState = Literal[
    "queued",
    "running",
    "waiting_review",
    "retry_wait",
    "completed",
    "failed",
    "cancelled",
]


@dataclass(frozen=True, slots=True)
class DurableJobClaim:
    job_id: str
    job_type: str
    contract_version: int
    run_id: str
    attempt_ordinal: int
    claim_started_at_utc: int
    dedupe_sha256: str
    payload_json: str
    checkpoint_json: str | None


@dataclass(frozen=True, slots=True)
class DurableJobRecoverySummary:
    examined_count: int = 0
    interrupted_count: int = 0
    queued_count: int = 0
    retry_wait_count: int = 0
    waiting_review_count: int = 0
    failed_count: int = 0
    skipped_count: int = 0


@dataclass(frozen=True, slots=True)
class RestoreJobReconciliation:
    examined_nonterminal_count: int
    cancelled_count: int
    interrupted_attempt_count: int
    unchanged_terminal_count: int


@dataclass(frozen=True, slots=True)
class DurableJobCancellationResult:
    outcome: Literal["CANCELLED", "ALREADY_CANCELLED", "TERMINAL_UNCHANGED"]
    job_id: str
    prior_state: DurableJobState
    resulting_state: Literal["cancelled", "completed", "failed"]
    claim_revoked: bool
    cancelled_attempt_ordinal: int | None = None



@dataclass(frozen=True, slots=True)
class RuntimeHealth:
    protocol_version: str
    run_id: str
    data_instance_id: str
    host_state: Literal["LISTENING_NOT_READY", "READY", "QUIESCING"]
    app_version: str
    migration_sequence: int
    migration_id: str | None
    integrity_state: str
    started_at_utc: int


@dataclass(frozen=True, slots=True)
class ShutdownResult:
    shutdown_state: Literal["QUIESCING", "ALREADY_QUIESCING", "STOPPED"]
    run_id: str
    data_instance_id: str
