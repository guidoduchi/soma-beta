from __future__ import annotations

import json
import re
from importlib.resources import files

from soma.foundation.errors import ValidationError
from soma.foundation.identifiers import require_uuid4
from soma.foundation.jobs import JobTypeContract, StaleRecoveryDisposition
from soma.foundation.strict_json import canonical_json_bytes

from soma.communications.contracts.common import closed, integer
from soma.communications.contracts.jobs import CommunicationJobCheckpoint, CommunicationJobScope

_ACTIVE = frozenset({"queued", "running", "waiting_review", "retry_wait"})
_ERROR = re.compile(r"[A-Z][A-Z0-9_]{0,63}")
_REGISTRY = json.loads(files("soma.communications.contracts").joinpath("registry.json").read_text(encoding="utf-8"))
_JOBS = _REGISTRY["leaves"]["jobs/communication-jobs.json"]["jobs"]
JOB_TYPES = {
    "ORDINARY": "communications.processing.ordinary",
    "TARGETED_BACKFILL": "communications.processing.targeted_backfill",
    "DEEP_SCAN": "communications.processing.deep_scan",
    "IDENTITY_RECONCILIATION": "communications.identity_reconciliation",
    "ORPHAN_HOUSEKEEPING": "communications.orphan_housekeeping",
}


def _scope_for_kind(value, kind):
    scope = CommunicationJobScope.from_value(value)
    if scope.job_kind != kind:
        raise ValidationError("Communication job type disagrees with scope kind")
    return scope


def dedupe_key(value):
    scope = CommunicationJobScope.from_value(value)
    if scope.job_kind == "ORPHAN_HOUSEKEEPING":
        return "SOMA_COMM_HOUSEKEEPING_INSTALLATION_V1"
    if scope.job_kind != "TARGETED_BACKFILL":
        return scope.source_scope_id
    exact = scope.to_response()
    exact["folder_keys"] = sorted(exact["folder_keys"])
    exact["target_identity_ids"] = sorted(exact["target_identity_ids"])
    # Foundation hashes this exact semantic key and re-compares it on a hit.
    return canonical_json_bytes(exact).decode("utf-8")


def retry_at(job_kind: str, *, error_code: str, attempt_ordinal: int, now: int) -> int | None:
    integer(attempt_ordinal, minimum=1)
    integer(now)
    if not isinstance(error_code, str) or _ERROR.fullmatch(error_code) is None:
        raise ValidationError("Communication job error code is invalid")
    if not isinstance(job_kind, str) or job_kind not in JOB_TYPES:
        raise ValidationError("Communication job kind is invalid")
    policy = next(job["retry_policy"] for job in _JOBS if job["job_type"] == JOB_TYPES[job_kind])
    if error_code not in policy["retryable"] or attempt_ordinal >= policy["max_attempts"]:
        return None
    return integer(now + policy["backoff_seconds"][attempt_ordinal - 1])


def _contract(item):
    kind = next(kind for kind, job_type in JOB_TYPES.items() if job_type == item["job_type"])

    def payload(value):
        _scope_for_kind(value, kind)

    def checkpoint(value):
        parsed = CommunicationJobCheckpoint.from_value(value)
        if parsed.scope.job_kind != kind:
            raise ValidationError("Communication checkpoint belongs to another job kind")

    def failure(code, ordinal, now, requested_retry):
        expected = retry_at(kind, error_code=code, attempt_ordinal=ordinal, now=now)
        if requested_retry is not None and (type(requested_retry) is not int or requested_retry != expected):
            raise ValidationError("Communication retry disagrees with its registered policy")

    def cancellation(context, state):
        require_uuid4(closed(context, {"command_id"})["command_id"])
        if state not in _ACTIVE:
            raise ValidationError("Communication job state is not cancellable")

    def recover(value, committed, ordinal, now):
        original = _scope_for_kind(value, kind)
        integer(ordinal, minimum=1)
        integer(now)
        if committed is not None:
            parsed = CommunicationJobCheckpoint.from_value(committed)
            if parsed.scope != original:
                raise ValidationError("Communication recovery checkpoint changed its immutable scope")
        if ordinal >= item["retry_policy"]["max_attempts"]:
            return StaleRecoveryDisposition("failed", error_code="JOB_INTERRUPTED")
        # Recovery preserves the committed checkpoint. Handlers must revalidate
        # current source/configuration and claim before IO or another mutation.
        return StaleRecoveryDisposition("retry_wait", next_attempt_at_utc=now, error_code="JOB_INTERRUPTED")

    return JobTypeContract(item["job_type"], item["contract_version"], payload, checkpoint, dedupe_key,
                           _ACTIVE, failure, cancellation, recover)


COMMUNICATION_JOB_CONTRACTS = tuple(_contract(item) for item in _JOBS)
