from __future__ import annotations

import hashlib
import re
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from soma.foundation.contracts.foundation import (
    DurableJobCancellationResult,
    DurableJobClaim,
    DurableJobRecoverySummary,
    RestoreJobReconciliation,
)
from soma.foundation.errors import IntegrityFailure, JobClaimConflict, SomaError, ValidationError
from soma.foundation.identifiers import new_uuid4, require_uuid4, utc_epoch_seconds
from soma.foundation.persistence.connections import ConnectionFactory
from soma.foundation.persistence.uow import UnitOfWork
from soma.foundation.strict_json import canonical_json_bytes_bounded, loads_canonical_json


_ALLOWED_STATES = frozenset(
    {"queued", "running", "waiting_review", "retry_wait", "completed", "failed", "cancelled"}
)
_NONTERMINAL_STATES = frozenset({"queued", "running", "waiting_review", "retry_wait"})
_COALESCIBLE_STATES = frozenset({*_NONTERMINAL_STATES, "completed"})
_RECOVERY_STATES = frozenset({"queued", "retry_wait", "waiting_review", "failed"})
_ERROR_CODE = re.compile(r"^[A-Z][A-Z0-9_]{0,63}$")
_MAX_JOB_TYPE_BYTES = 256
_MAX_DEDUPE_KEY_BYTES = 65536
_MAX_JOB_JSON_BYTES = 65536
_MAX_JSON_DEPTH = 8
_MAX_COLLECTION_ITEMS = 512


@dataclass(frozen=True, slots=True)
class StaleRecoveryDisposition:
    state: str
    next_attempt_at_utc: int | None = None
    error_code: str | None = None


@dataclass(frozen=True, slots=True)
class JobTypeContract:
    job_type: str
    contract_version: int
    validate_payload: Callable[[Any], None]
    validate_checkpoint: Callable[[Any], None]
    derive_dedupe_key: Callable[[Any], str]
    coalesce_states: frozenset[str]
    retryable_error: Callable[[str], bool]
    recover_stale: Callable[[Any, Any | None, int], StaleRecoveryDisposition]


class JobTypeRegistry:
    def __init__(self, contracts: tuple[JobTypeContract, ...] | list[JobTypeContract] = ()) -> None:
        self._contracts: dict[tuple[str, int], JobTypeContract] = {}
        for contract in contracts:
            self.register(contract)

    def register(self, contract: JobTypeContract) -> None:
        _validate_job_type(contract.job_type)
        if not isinstance(contract.contract_version, int) or isinstance(contract.contract_version, bool):
            raise ValidationError("durable job contract_version must be int>=1")
        if contract.contract_version < 1:
            raise ValidationError("durable job contract_version must be int>=1")
        states = frozenset(contract.coalesce_states)
        if not states or not states.issubset(_COALESCIBLE_STATES):
            raise ValidationError(
                "durable job coalesce_states must be a nonempty active/completed state set"
            )
        key = (contract.job_type, contract.contract_version)
        if key in self._contracts:
            raise ValidationError("duplicate durable job type/version registration")
        self._contracts[key] = JobTypeContract(
            job_type=contract.job_type,
            contract_version=contract.contract_version,
            validate_payload=contract.validate_payload,
            validate_checkpoint=contract.validate_checkpoint,
            derive_dedupe_key=contract.derive_dedupe_key,
            coalesce_states=states,
            retryable_error=contract.retryable_error,
            recover_stale=contract.recover_stale,
        )

    def get(self, job_type: str, contract_version: int) -> JobTypeContract | None:
        return self._contracts.get((job_type, contract_version))

    def require(self, job_type: str, contract_version: int) -> JobTypeContract:
        contract = self.get(job_type, contract_version)
        if contract is None:
            raise ValidationError("unknown durable job type/version")
        return contract


class DurableJobCoordinator:
    def __init__(
        self,
        connection_factory: ConnectionFactory,
        registry: JobTypeRegistry,
        *,
        clock: Callable[[], int] = utc_epoch_seconds,
    ) -> None:
        self._factory = connection_factory
        self._registry = registry
        self._clock = clock

    def enqueue_or_coalesce(
        self,
        uow: UnitOfWork,
        job_type: str,
        contract_version: int,
        payload: Any,
        dedupe_key: str,
    ) -> str:
        contract = self._registry.require(job_type, contract_version)
        payload_json = self._canonical_payload(contract, payload, persisted=False)
        semantic_key = self._derive_dedupe_key(contract, payload, persisted=False)
        _validate_dedupe_key(dedupe_key)
        if semantic_key != dedupe_key:
            raise ValidationError("durable job dedupe_key disagrees with registered payload contract")
        dedupe_sha256 = _dedupe_sha256(job_type, contract_version, dedupe_key)
        states = tuple(sorted(contract.coalesce_states))
        placeholders = ",".join("?" for _ in states)
        rows = uow.connection.execute(
            f"""
            SELECT job_id,payload_json,dedupe_sha256
            FROM durable_jobs
            WHERE job_type=?
              AND contract_version=?
              AND dedupe_sha256=?
              AND state IN ({placeholders})
            ORDER BY job_id
            LIMIT 2
            """,
            (job_type, contract_version, dedupe_sha256, *states),
        ).fetchall()
        if len(rows) > 1:
            raise IntegrityFailure("multiple durable jobs match one semantic coalescing identity")
        if rows:
            job_id, persisted_payload_json, persisted_hash = rows[0]
            if str(persisted_hash) != dedupe_sha256:
                raise IntegrityFailure("durable job dedupe identity changed during indexed lookup")
            persisted_payload = self._load_registered_payload(contract, str(persisted_payload_json))
            persisted_key = self._derive_dedupe_key(contract, persisted_payload, persisted=True)
            if persisted_key != dedupe_key:
                raise IntegrityFailure("durable job dedupe hash collision or payload/key disagreement")
            _require_uuid_persisted(str(job_id), "durable job_id")
            return str(job_id)

        now = self._now()
        job_id = new_uuid4()
        try:
            uow.connection.execute(
                """
                INSERT INTO durable_jobs(
                    job_id,job_type,contract_version,state,
                    created_at_utc,updated_at_utc,attempt_count,next_attempt_at_utc,
                    claimed_run_id,claim_started_at_utc,payload_json,checkpoint_json,
                    last_error_code,dedupe_sha256
                ) VALUES (?,?,?,'queued',?,?,0,NULL,NULL,NULL,?,NULL,NULL,?)
                """,
                (job_id, job_type, contract_version, now, now, payload_json, dedupe_sha256),
            )
        except Exception as exc:
            raise IntegrityFailure("durable job enqueue violated persistence invariants") from exc
        return job_id

    def claim_next(self, run_id: str, now: int) -> DurableJobClaim | None:
        require_uuid4(run_id)
        _validate_time(now, "now")
        with UnitOfWork(self._factory) as uow:
            row = uow.connection.execute(
                """
                SELECT job_id,job_type,contract_version,state,created_at_utc,attempt_count,
                       next_attempt_at_utc,payload_json,checkpoint_json,dedupe_sha256
                FROM durable_jobs
                WHERE state='queued'
                   OR (state='retry_wait' AND next_attempt_at_utc IS NOT NULL AND next_attempt_at_utc<=?)
                ORDER BY
                    CASE WHEN next_attempt_at_utc IS NULL THEN 0 ELSE 1 END,
                    next_attempt_at_utc,
                    created_at_utc,
                    job_id
                LIMIT 1
                """,
                (now,),
            ).fetchone()
            if row is None:
                return None
            (
                job_id,
                job_type,
                contract_version,
                state,
                created_at_utc,
                attempt_count,
                next_attempt_at_utc,
                payload_json,
                checkpoint_json,
                dedupe_sha256,
            ) = row
            if state == "retry_wait" and (
                next_attempt_at_utc is None or int(next_attempt_at_utc) > now
            ):
                raise IntegrityFailure("durable retry_wait job was selected before it became due")
            contract = self._registry.get(str(job_type), int(contract_version))
            if contract is None:
                self._fail_unclaimable(uow, str(job_id), now, "JOB_CONTRACT_UNAVAILABLE")
                return None
            if dedupe_sha256 is None or not _is_sha256(str(dedupe_sha256)):
                raise IntegrityFailure("claimable durable job lacks valid migration-8 dedupe identity")
            payload = self._load_registered_payload(contract, str(payload_json))
            expected_key = self._derive_dedupe_key(contract, payload, persisted=True)
            expected_hash = _dedupe_sha256(str(job_type), int(contract_version), expected_key)
            if expected_hash != str(dedupe_sha256):
                raise IntegrityFailure("claimable durable job payload disagrees with dedupe identity")
            canonical_checkpoint = self._validate_persisted_checkpoint(contract, checkpoint_json)
            _require_uuid_persisted(str(job_id), "durable job_id")
            if not isinstance(attempt_count, int) or int(attempt_count) < 0:
                raise IntegrityFailure("durable job attempt_count is invalid")
            attempt_ordinal = int(attempt_count) + 1
            if now < int(created_at_utc):
                raise IntegrityFailure("durable job claim timestamp precedes creation")
            uow.connection.execute(
                """
                UPDATE durable_jobs
                SET state='running',
                    claimed_run_id=?,
                    claim_started_at_utc=?,
                    attempt_count=?,
                    next_attempt_at_utc=NULL,
                    updated_at_utc=?
                WHERE job_id=? AND state=?
                  AND attempt_count=?
                  AND claimed_run_id IS NULL
                  AND claim_started_at_utc IS NULL
                """,
                (
                    run_id,
                    now,
                    attempt_ordinal,
                    now,
                    str(job_id),
                    str(state),
                    int(attempt_count),
                ),
            )
            if _changes(uow.connection) != 1:
                raise IntegrityFailure("durable job claim lost authoritative revalidation")
            return DurableJobClaim(
                job_id=str(job_id),
                job_type=str(job_type),
                contract_version=int(contract_version),
                run_id=run_id,
                attempt_ordinal=attempt_ordinal,
                claim_started_at_utc=now,
                dedupe_sha256=str(dedupe_sha256),
                payload_json=str(payload_json),
                checkpoint_json=canonical_checkpoint,
            )

    def checkpoint(self, claim: DurableJobClaim, checkpoint: Any) -> None:
        contract = self._require_claim_contract(claim)
        checkpoint_json = self._canonical_checkpoint(contract, checkpoint, persisted=False)
        now = self._now()
        with UnitOfWork(self._factory) as uow:
            row = self._verify_claim(uow, claim)
            self._require_nonregressing_now(now, int(row[1]), claim)
            uow.connection.execute(
                "UPDATE durable_jobs SET checkpoint_json=?,updated_at_utc=? WHERE job_id=?",
                (checkpoint_json, now, claim.job_id),
            )

    def complete(self, claim: DurableJobClaim) -> None:
        self._require_claim_contract(claim)
        now = self._now()
        with UnitOfWork(self._factory) as uow:
            row = self._verify_claim(uow, claim)
            self._require_nonregressing_now(now, int(row[1]), claim)
            self._require_attempt_absent(uow, claim.job_id, claim.attempt_ordinal)
            self._insert_attempt(
                uow,
                job_id=claim.job_id,
                ordinal=claim.attempt_ordinal,
                run_id=claim.run_id,
                started_at_utc=claim.claim_started_at_utc,
                finished_at_utc=now,
                outcome="completed",
                error_code=None,
            )
            uow.connection.execute(
                """
                UPDATE durable_jobs
                SET state='completed',claimed_run_id=NULL,claim_started_at_utc=NULL,
                    next_attempt_at_utc=NULL,last_error_code=NULL,updated_at_utc=?
                WHERE job_id=?
                """,
                (now, claim.job_id),
            )

    def fail(self, claim: DurableJobClaim, error_code: str, retry_at: int | None) -> None:
        contract = self._require_claim_contract(claim)
        _validate_error_code(error_code)
        now = self._now()
        if retry_at is not None:
            _validate_time(retry_at, "retry_at")
            if retry_at < now:
                raise ValidationError("durable job retry_at must not precede failure time")
            try:
                retryable = bool(contract.retryable_error(error_code))
            except Exception as exc:
                raise ValidationError("durable job retry policy rejected error classification") from exc
            if not retryable:
                raise ValidationError("durable job contract does not permit retry for error_code")
        with UnitOfWork(self._factory) as uow:
            row = self._verify_claim(uow, claim)
            self._require_nonregressing_now(now, int(row[1]), claim)
            self._require_attempt_absent(uow, claim.job_id, claim.attempt_ordinal)
            self._insert_attempt(
                uow,
                job_id=claim.job_id,
                ordinal=claim.attempt_ordinal,
                run_id=claim.run_id,
                started_at_utc=claim.claim_started_at_utc,
                finished_at_utc=now,
                outcome="failed",
                error_code=error_code,
            )
            state = "retry_wait" if retry_at is not None else "failed"
            uow.connection.execute(
                """
                UPDATE durable_jobs
                SET state=?,claimed_run_id=NULL,claim_started_at_utc=NULL,
                    next_attempt_at_utc=?,last_error_code=?,updated_at_utc=?
                WHERE job_id=?
                """,
                (state, retry_at, error_code, now, claim.job_id),
            )

    def cancel(
        self,
        uow: UnitOfWork,
        job_id: str,
        expected_job_type: str,
        expected_contract_version: int,
        command_context: Any,
    ) -> DurableJobCancellationResult:
        del command_context
        require_uuid4(job_id)
        contract = self._registry.require(expected_job_type, expected_contract_version)
        row = uow.connection.execute(
            """
            SELECT job_type,contract_version,state,attempt_count,claimed_run_id,
                   claim_started_at_utc,created_at_utc,updated_at_utc
            FROM durable_jobs WHERE job_id=?
            """,
            (job_id,),
        ).fetchone()
        if row is None:
            raise ValidationError("durable job does not exist")
        (
            job_type,
            contract_version,
            state,
            attempt_count,
            claimed_run_id,
            claim_started_at_utc,
            created_at_utc,
            updated_at_utc,
        ) = row
        if str(job_type) != contract.job_type or int(contract_version) != contract.contract_version:
            raise IntegrityFailure("durable job identity disagrees with cancellation expectation")
        prior_state = str(state)
        if prior_state == "cancelled":
            return DurableJobCancellationResult(
                outcome="ALREADY_CANCELLED",
                job_id=job_id,
                prior_state="cancelled",
                resulting_state="cancelled",
                claim_revoked=False,
            )
        if prior_state in {"completed", "failed"}:
            return DurableJobCancellationResult(
                outcome="TERMINAL_UNCHANGED",
                job_id=job_id,
                prior_state=prior_state,  # type: ignore[arg-type]
                resulting_state=prior_state,  # type: ignore[arg-type]
                claim_revoked=False,
            )
        if prior_state not in _NONTERMINAL_STATES:
            raise IntegrityFailure("durable job has unknown persisted state")
        now = self._now()
        if now < int(created_at_utc) or now < int(updated_at_utc):
            raise IntegrityFailure("durable job cancellation clock regressed")
        cancelled_ordinal: int | None = None
        claim_revoked = prior_state == "running"
        if claim_revoked:
            if (
                not isinstance(attempt_count, int)
                or int(attempt_count) < 1
                or claimed_run_id is None
                or claim_started_at_utc is None
            ):
                raise IntegrityFailure("running durable job has incomplete claim evidence")
            cancelled_ordinal = int(attempt_count)
            self._require_attempt_absent(uow, job_id, cancelled_ordinal)
            self._insert_attempt(
                uow,
                job_id=job_id,
                ordinal=cancelled_ordinal,
                run_id=str(claimed_run_id),
                started_at_utc=int(claim_started_at_utc),
                finished_at_utc=now,
                outcome="cancelled",
                error_code=None,
            )
        uow.connection.execute(
            """
            UPDATE durable_jobs
            SET state='cancelled',claimed_run_id=NULL,claim_started_at_utc=NULL,
                next_attempt_at_utc=NULL,updated_at_utc=?
            WHERE job_id=?
            """,
            (now, job_id),
        )
        return DurableJobCancellationResult(
            outcome="CANCELLED",
            job_id=job_id,
            prior_state=prior_state,  # type: ignore[arg-type]
            resulting_state="cancelled",
            claim_revoked=claim_revoked,
            cancelled_attempt_ordinal=cancelled_ordinal,
        )

    def recover_stale_claims(self, current_run_id: str, now: int) -> DurableJobRecoverySummary:
        require_uuid4(current_run_id)
        _validate_time(now, "now")
        counts = {
            "examined_count": 0,
            "interrupted_count": 0,
            "queued_count": 0,
            "retry_wait_count": 0,
            "waiting_review_count": 0,
            "failed_count": 0,
            "skipped_count": 0,
        }

        for job_id in self._list_job_ids(
            """
            SELECT job_id FROM durable_jobs
            WHERE dedupe_sha256 IS NULL
              AND state IN ('queued','running','waiting_review','retry_wait')
            ORDER BY job_id
            """
        ):
            counts["examined_count"] += 1
            with UnitOfWork(self._factory) as uow:
                row = uow.connection.execute(
                    """
                    SELECT state,attempt_count,claimed_run_id,claim_started_at_utc
                    FROM durable_jobs
                    WHERE job_id=? AND dedupe_sha256 IS NULL
                    """,
                    (job_id,),
                ).fetchone()
                if row is None or str(row[0]) not in _NONTERMINAL_STATES:
                    counts["skipped_count"] += 1
                    continue
                if str(row[0]) == "running":
                    ordinal = int(row[1])
                    run_id = row[2]
                    started = row[3]
                    if ordinal < 1 or run_id is None or started is None:
                        raise IntegrityFailure("legacy running job has incomplete claim evidence")
                    inserted = self._insert_interrupted_if_absent(
                        uow,
                        job_id,
                        ordinal,
                        str(run_id),
                        int(started),
                        now,
                        "LEGACY_JOB_DEDUPE_UNAVAILABLE",
                    )
                    counts["interrupted_count"] += int(inserted)
                uow.connection.execute(
                    """
                    UPDATE durable_jobs
                    SET state='failed',claimed_run_id=NULL,claim_started_at_utc=NULL,
                        next_attempt_at_utc=NULL,last_error_code='LEGACY_JOB_DEDUPE_UNAVAILABLE',
                        updated_at_utc=CASE WHEN updated_at_utc>? THEN updated_at_utc ELSE ? END
                    WHERE job_id=? AND dedupe_sha256 IS NULL
                      AND state IN ('queued','running','waiting_review','retry_wait')
                    """,
                    (now, now, job_id),
                )
                if _changes(uow.connection) != 1:
                    raise IntegrityFailure("legacy durable job recovery lost revalidation")
                counts["failed_count"] += 1

        for job_id in self._list_job_ids(
            """
            SELECT job_id FROM durable_jobs
            WHERE state='running'
              AND dedupe_sha256 IS NOT NULL
              AND claimed_run_id<>?
            ORDER BY job_id
            """,
            (current_run_id,),
        ):
            counts["examined_count"] += 1
            with UnitOfWork(self._factory) as uow:
                row = uow.connection.execute(
                    """
                    SELECT job_type,contract_version,state,attempt_count,claimed_run_id,
                           claim_started_at_utc,payload_json,checkpoint_json,dedupe_sha256
                    FROM durable_jobs WHERE job_id=?
                    """,
                    (job_id,),
                ).fetchone()
                if (
                    row is None
                    or str(row[2]) != "running"
                    or row[4] is None
                    or str(row[4]) == current_run_id
                ):
                    counts["skipped_count"] += 1
                    continue
                (
                    job_type,
                    contract_version,
                    _state,
                    attempt_count,
                    stale_run_id,
                    claim_started_at_utc,
                    payload_json,
                    checkpoint_json,
                    dedupe_sha256,
                ) = row
                ordinal = int(attempt_count)
                if ordinal < 1 or claim_started_at_utc is None:
                    raise IntegrityFailure("stale durable job has incomplete claim evidence")
                inserted = self._insert_interrupted_if_absent(
                    uow,
                    job_id,
                    ordinal,
                    str(stale_run_id),
                    int(claim_started_at_utc),
                    now,
                    "JOB_INTERRUPTED",
                )
                counts["interrupted_count"] += int(inserted)
                contract = self._registry.get(str(job_type), int(contract_version))
                if contract is None:
                    uow.connection.execute(
                        """
                        UPDATE durable_jobs
                        SET state='failed',claimed_run_id=NULL,claim_started_at_utc=NULL,
                            next_attempt_at_utc=NULL,last_error_code='JOB_CONTRACT_UNAVAILABLE',
                            updated_at_utc=CASE WHEN updated_at_utc>? THEN updated_at_utc ELSE ? END
                        WHERE job_id=? AND state='running' AND claimed_run_id=?
                          AND attempt_count=? AND claim_started_at_utc=?
                        """,
                        (
                            now,
                            now,
                            job_id,
                            str(stale_run_id),
                            ordinal,
                            int(claim_started_at_utc),
                        ),
                    )
                    if _changes(uow.connection) != 1:
                        raise IntegrityFailure("unknown-contract stale recovery lost revalidation")
                    counts["failed_count"] += 1
                    continue
                if dedupe_sha256 is None or not _is_sha256(str(dedupe_sha256)):
                    raise IntegrityFailure("stale durable job has invalid dedupe identity")
                payload = self._load_registered_payload(contract, str(payload_json))
                checkpoint = self._load_registered_checkpoint(contract, checkpoint_json)
                key = self._derive_dedupe_key(contract, payload, persisted=True)
                if _dedupe_sha256(str(job_type), int(contract_version), key) != str(dedupe_sha256):
                    raise IntegrityFailure("stale durable job payload disagrees with dedupe identity")
                try:
                    disposition = contract.recover_stale(payload, checkpoint, now)
                except Exception as exc:
                    raise IntegrityFailure("registered durable job crash policy failed") from exc
                self._validate_recovery_disposition(disposition, now)
                error_code = disposition.error_code or "JOB_INTERRUPTED"
                _validate_error_code(error_code)
                uow.connection.execute(
                    """
                    UPDATE durable_jobs
                    SET state=?,claimed_run_id=NULL,claim_started_at_utc=NULL,
                        next_attempt_at_utc=?,last_error_code=?,
                        updated_at_utc=CASE WHEN updated_at_utc>? THEN updated_at_utc ELSE ? END
                    WHERE job_id=? AND state='running' AND claimed_run_id=?
                      AND attempt_count=? AND claim_started_at_utc=?
                    """,
                    (
                        disposition.state,
                        disposition.next_attempt_at_utc,
                        error_code,
                        now,
                        now,
                        job_id,
                        str(stale_run_id),
                        ordinal,
                        int(claim_started_at_utc),
                    ),
                )
                if _changes(uow.connection) != 1:
                    raise IntegrityFailure("stale durable job recovery lost revalidation")
                counts[f"{disposition.state}_count"] += 1

        return DurableJobRecoverySummary(**counts)

    def reconcile_restored_jobs(
        self,
        uow: UnitOfWork,
        restore_context: Any,
    ) -> RestoreJobReconciliation:
        if restore_context is None:
            raise ValidationError("restore_context is required")
        rows = uow.connection.execute(
            """
            SELECT job_id,state,attempt_count,claimed_run_id,claim_started_at_utc,updated_at_utc
            FROM durable_jobs
            WHERE state IN ('queued','running','waiting_review','retry_wait')
            ORDER BY job_id
            """
        ).fetchall()
        interrupted = 0
        now = self._now()
        for row in rows:
            job_id, state, attempt_count, claimed_run_id, claim_started_at_utc, updated_at_utc = row
            if str(state) == "running":
                if (
                    not isinstance(attempt_count, int)
                    or int(attempt_count) < 1
                    or claimed_run_id is None
                    or claim_started_at_utc is None
                ):
                    raise IntegrityFailure("restored running job has incomplete claim evidence")
                inserted = self._insert_interrupted_if_absent(
                    uow,
                    str(job_id),
                    int(attempt_count),
                    str(claimed_run_id),
                    int(claim_started_at_utc),
                    max(now, int(updated_at_utc)),
                    "RESTORE_SNAPSHOT_JOB_INVALIDATED",
                )
                interrupted += int(inserted)
            uow.connection.execute(
                """
                UPDATE durable_jobs
                SET state='cancelled',claimed_run_id=NULL,claim_started_at_utc=NULL,
                    next_attempt_at_utc=NULL,last_error_code='RESTORE_SNAPSHOT_JOB_INVALIDATED',
                    updated_at_utc=CASE WHEN updated_at_utc>? THEN updated_at_utc ELSE ? END
                WHERE job_id=? AND state IN ('queued','running','waiting_review','retry_wait')
                """,
                (now, now, str(job_id)),
            )
            if _changes(uow.connection) != 1:
                raise IntegrityFailure("restore durable job reconciliation lost revalidation")
        terminal_count = int(
            uow.connection.execute(
                "SELECT COUNT(*) FROM durable_jobs WHERE state IN ('completed','failed','cancelled')"
            ).fetchone()[0]
        )
        return RestoreJobReconciliation(
            examined_nonterminal_count=len(rows),
            cancelled_count=len(rows),
            interrupted_attempt_count=interrupted,
            unchanged_terminal_count=terminal_count - len(rows),
        )

    def _require_claim_contract(self, claim: DurableJobClaim) -> JobTypeContract:
        require_uuid4(claim.job_id)
        require_uuid4(claim.run_id)
        if claim.attempt_ordinal < 1:
            raise ValidationError("durable job claim attempt_ordinal must be >=1")
        _validate_time(claim.claim_started_at_utc, "claim_started_at_utc")
        if not _is_sha256(claim.dedupe_sha256):
            raise ValidationError("durable job claim dedupe_sha256 is invalid")
        return self._registry.require(claim.job_type, claim.contract_version)

    def _verify_claim(self, uow: UnitOfWork, claim: DurableJobClaim) -> tuple[Any, ...]:
        row = uow.connection.execute(
            """
            SELECT attempt_count,updated_at_utc,dedupe_sha256,payload_json,checkpoint_json
            FROM durable_jobs
            WHERE job_id=? AND job_type=? AND contract_version=? AND state='running'
              AND claimed_run_id=? AND attempt_count=? AND claim_started_at_utc=?
            """,
            (
                claim.job_id,
                claim.job_type,
                claim.contract_version,
                claim.run_id,
                claim.attempt_ordinal,
                claim.claim_started_at_utc,
            ),
        ).fetchone()
        if row is None:
            raise JobClaimConflict()
        if str(row[2]) != claim.dedupe_sha256 or str(row[3]) != claim.payload_json:
            raise IntegrityFailure("durable job claim identity payload changed")
        contract = self._registry.require(claim.job_type, claim.contract_version)
        self._validate_persisted_checkpoint(contract, row[4])
        return row

    def _canonical_payload(self, contract: JobTypeContract, payload: Any, *, persisted: bool) -> str:
        try:
            contract.validate_payload(payload)
            encoded = canonical_json_bytes_bounded(
                payload,
                max_bytes=_MAX_JOB_JSON_BYTES,
                max_depth=_MAX_JSON_DEPTH,
                max_collection_items=_MAX_COLLECTION_ITEMS,
            )
        except SomaError:
            raise
        except Exception as exc:
            error = IntegrityFailure if persisted else ValidationError
            raise error("durable job payload violates registered contract") from exc
        return encoded.decode("utf-8")

    def _canonical_checkpoint(
        self, contract: JobTypeContract, checkpoint: Any, *, persisted: bool
    ) -> str:
        try:
            contract.validate_checkpoint(checkpoint)
            encoded = canonical_json_bytes_bounded(
                checkpoint,
                max_bytes=_MAX_JOB_JSON_BYTES,
                max_depth=_MAX_JSON_DEPTH,
                max_collection_items=_MAX_COLLECTION_ITEMS,
            )
        except SomaError:
            raise
        except Exception as exc:
            error = IntegrityFailure if persisted else ValidationError
            raise error("durable job checkpoint violates registered contract") from exc
        return encoded.decode("utf-8")

    def _load_registered_payload(self, contract: JobTypeContract, payload_json: str) -> Any:
        try:
            payload = loads_canonical_json(
                payload_json,
                max_bytes=_MAX_JOB_JSON_BYTES,
                max_depth=_MAX_JSON_DEPTH,
                max_collection_items=_MAX_COLLECTION_ITEMS,
            )
            canonical = self._canonical_payload(contract, payload, persisted=True)
        except Exception as exc:
            if isinstance(exc, IntegrityFailure):
                raise
            raise IntegrityFailure(
                "persisted durable job payload is not exact canonical contract data"
            ) from exc
        if canonical != payload_json:
            raise IntegrityFailure("persisted durable job payload is noncanonical")
        return payload

    def _load_registered_checkpoint(
        self, contract: JobTypeContract, checkpoint_json: Any
    ) -> Any | None:
        if checkpoint_json is None:
            return None
        text = str(checkpoint_json)
        try:
            checkpoint = loads_canonical_json(
                text,
                max_bytes=_MAX_JOB_JSON_BYTES,
                max_depth=_MAX_JSON_DEPTH,
                max_collection_items=_MAX_COLLECTION_ITEMS,
            )
            canonical = self._canonical_checkpoint(contract, checkpoint, persisted=True)
        except Exception as exc:
            if isinstance(exc, IntegrityFailure):
                raise
            raise IntegrityFailure("persisted durable job checkpoint is invalid") from exc
        if canonical != text:
            raise IntegrityFailure("persisted durable job checkpoint is noncanonical")
        return checkpoint

    def _validate_persisted_checkpoint(
        self, contract: JobTypeContract, checkpoint_json: Any
    ) -> str | None:
        if checkpoint_json is None:
            return None
        self._load_registered_checkpoint(contract, checkpoint_json)
        return str(checkpoint_json)

    def _derive_dedupe_key(
        self, contract: JobTypeContract, payload: Any, *, persisted: bool
    ) -> str:
        try:
            key = contract.derive_dedupe_key(payload)
            _validate_dedupe_key(key)
        except SomaError as exc:
            if persisted:
                raise IntegrityFailure(
                    "persisted durable job cannot reproduce semantic dedupe key"
                ) from exc
            raise
        except Exception as exc:
            error = IntegrityFailure if persisted else ValidationError
            raise error("durable job semantic dedupe key derivation failed") from exc
        return key

    def _fail_unclaimable(
        self,
        uow: UnitOfWork,
        job_id: str,
        now: int,
        error_code: str,
    ) -> None:
        _validate_error_code(error_code)
        uow.connection.execute(
            """
            UPDATE durable_jobs
            SET state='failed',claimed_run_id=NULL,claim_started_at_utc=NULL,
                next_attempt_at_utc=NULL,last_error_code=?,
                updated_at_utc=CASE WHEN updated_at_utc>? THEN updated_at_utc ELSE ? END
            WHERE job_id=? AND state IN ('queued','retry_wait')
            """,
            (error_code, now, now, job_id),
        )
        if _changes(uow.connection) != 1:
            raise IntegrityFailure("unclaimable durable job disposition lost revalidation")

    def _list_job_ids(self, sql: str, params: tuple[Any, ...] = ()) -> list[str]:
        connection = self._factory.open_authoritative(read_only=True)
        try:
            return [str(row[0]) for row in connection.execute(sql, params).fetchall()]
        finally:
            connection.close()

    def _require_attempt_absent(self, uow: UnitOfWork, job_id: str, ordinal: int) -> None:
        if uow.connection.execute(
            "SELECT 1 FROM job_attempts WHERE job_id=? AND ordinal=?",
            (job_id, ordinal),
        ).fetchone() is not None:
            raise IntegrityFailure("durable job attempt ordinal already has terminal history")

    def _insert_attempt(
        self,
        uow: UnitOfWork,
        *,
        job_id: str,
        ordinal: int,
        run_id: str,
        started_at_utc: int,
        finished_at_utc: int,
        outcome: str,
        error_code: str | None,
    ) -> None:
        if finished_at_utc < started_at_utc:
            raise IntegrityFailure("durable job attempt finish precedes claim start")
        if error_code is not None:
            _validate_error_code(error_code)
        uow.connection.execute(
            """
            INSERT INTO job_attempts(
                attempt_id,job_id,ordinal,run_id,started_at_utc,finished_at_utc,outcome,error_code
            ) VALUES (?,?,?,?,?,?,?,?)
            """,
            (
                new_uuid4(),
                job_id,
                ordinal,
                run_id,
                started_at_utc,
                finished_at_utc,
                outcome,
                error_code,
            ),
        )

    def _insert_interrupted_if_absent(
        self,
        uow: UnitOfWork,
        job_id: str,
        ordinal: int,
        run_id: str,
        started_at_utc: int,
        finished_at_utc: int,
        error_code: str,
    ) -> bool:
        existing = uow.connection.execute(
            """
            SELECT run_id,started_at_utc,outcome,error_code
            FROM job_attempts WHERE job_id=? AND ordinal=?
            """,
            (job_id, ordinal),
        ).fetchone()
        if existing is not None:
            if (
                str(existing[0]) == run_id
                and int(existing[1]) == started_at_utc
                and str(existing[2]) == "interrupted"
                and str(existing[3]) == error_code
            ):
                return False
            raise IntegrityFailure("durable job recovery found conflicting attempt history")
        self._insert_attempt(
            uow,
            job_id=job_id,
            ordinal=ordinal,
            run_id=run_id,
            started_at_utc=started_at_utc,
            finished_at_utc=max(finished_at_utc, started_at_utc),
            outcome="interrupted",
            error_code=error_code,
        )
        return True

    @staticmethod
    def _validate_recovery_disposition(
        disposition: StaleRecoveryDisposition, now: int
    ) -> None:
        if disposition.state not in _RECOVERY_STATES:
            raise IntegrityFailure("registered durable job crash policy returned invalid state")
        if disposition.state == "retry_wait":
            if disposition.next_attempt_at_utc is None:
                raise IntegrityFailure("retry_wait recovery requires next_attempt_at_utc")
            _validate_time(disposition.next_attempt_at_utc, "next_attempt_at_utc")
            if disposition.next_attempt_at_utc < now:
                raise IntegrityFailure("recovery retry time precedes recovery time")
        elif disposition.next_attempt_at_utc is not None:
            raise IntegrityFailure("non-retry recovery state cannot carry next_attempt_at_utc")

    @staticmethod
    def _require_nonregressing_now(
        now: int, updated_at_utc: int, claim: DurableJobClaim
    ) -> None:
        if now < updated_at_utc or now < claim.claim_started_at_utc:
            raise IntegrityFailure("durable job coordinator clock regressed")

    def _now(self) -> int:
        value = self._clock()
        _validate_time(value, "server time")
        return value


def _validate_job_type(value: str) -> None:
    if not isinstance(value, str) or not value:
        raise ValidationError("durable job_type must be a nonempty string")
    if len(value.encode("utf-8")) > _MAX_JOB_TYPE_BYTES:
        raise ValidationError("durable job_type exceeds bound")


def _validate_dedupe_key(value: str) -> None:
    if not isinstance(value, str) or not value:
        raise ValidationError("durable job dedupe_key must be a nonempty string")
    try:
        size = len(value.encode("utf-8"))
    except UnicodeEncodeError as exc:
        raise ValidationError("durable job dedupe_key must be valid UTF-8") from exc
    if size > _MAX_DEDUPE_KEY_BYTES:
        raise ValidationError("durable job dedupe_key exceeds bound")


def _validate_error_code(value: str) -> None:
    if not isinstance(value, str) or _ERROR_CODE.fullmatch(value) is None:
        raise ValidationError("durable job error_code must be stable uppercase token <=64 chars")


def _validate_time(value: int, name: str) -> None:
    if not isinstance(value, int) or isinstance(value, bool) or value < 0:
        raise ValidationError(f"{name} must be a nonnegative whole-second UTC epoch")


def _dedupe_sha256(job_type: str, contract_version: int, dedupe_key: str) -> str:
    payload = {
        "schema": "SOMA_DURABLE_JOB_DEDUPE_V1",
        "job_type": job_type,
        "contract_version": contract_version,
        "dedupe_key": dedupe_key,
    }
    encoded = canonical_json_bytes_bounded(
        payload,
        max_bytes=_MAX_DEDUPE_KEY_BYTES + 1024,
        max_depth=4,
        max_collection_items=16,
    )
    return hashlib.sha256(encoded).hexdigest()


def _is_sha256(value: str) -> bool:
    return len(value) == 64 and all(ch in "0123456789abcdef" for ch in value)


def _require_uuid_persisted(value: str, label: str) -> None:
    try:
        require_uuid4(value)
    except ValidationError as exc:
        raise IntegrityFailure(f"persisted {label} is not canonical UUIDv4") from exc


def _changes(connection: Any) -> int:
    row = connection.execute("SELECT changes()").fetchone()
    if row is None:
        raise IntegrityFailure("SQLite did not report durable job mutation count")
    return int(row[0])
