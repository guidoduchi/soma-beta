"""Shared registered retry policy and diagnostic minimization for mail jobs."""
from soma.foundation.errors import JobClaimConflict, SomaError

from soma.communications.jobs.communications import _REGISTRY, retry_at

_SAFE_CODES = frozenset(item["code"] for item in _REGISTRY["leaves"]["errors.json"]["errors"]) | frozenset({
    "SOURCE_LOCKED", "IO_TRANSIENT", "PERSISTENCE_BUSY", "INTEGRITY_FAILURE", "PERSISTENCE_FAILURE"})


def run_with_failure_policy(claim, coordinator, *, job_kind, clock, execute, safe_message):
    try:
        return execute()
    except JobClaimConflict:
        raise
    except Exception as exc:
        code = exc.code if isinstance(exc, SomaError) and exc.code in _SAFE_CODES else "COMM_DIAGNOSTIC_REDACTED"
    # Leave the exception handler before recording/raising safe failure. ``from
    # None`` alone suppresses display but retains the unsafe exception object in
    # __context__, which diagnostic callers must never be able to inspect.
    try:
        retry = retry_at(job_kind, error_code=code, attempt_ordinal=claim.attempt_ordinal, now=clock())
        coordinator.fail(claim, code, retry)
    except JobClaimConflict:
        raise
    except Exception:
        code = "COMM_DIAGNOSTIC_REDACTED"
    raise SomaError(code, safe_message)
