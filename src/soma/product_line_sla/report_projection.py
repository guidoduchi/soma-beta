from __future__ import annotations

from .domain.reports import ReportAttemptRecord


def report_attempt_response(attempt: ReportAttemptRecord) -> dict[str, object]:
    """Project one immutable report-attempt record into its public response shape."""
    return {
        "report_attempt_id": attempt.report_attempt_id,
        "period_type": attempt.period_type,
        "period_start_utc": attempt.period_start_utc,
        "period_end_utc": attempt.period_end_utc,
        "period_timezone": attempt.period_timezone,
        "scope_kind": attempt.scope_kind,
        "customer_org_id": attempt.customer_org_id,
        "as_of_utc": attempt.as_of_utc,
        "state": attempt.state,
        "snapshot_hash": attempt.snapshot_hash,
        "snapshot_member_count": attempt.snapshot_member_count,
        "snapshot_cohort_count": attempt.snapshot_cohort_count,
        "snapshot_section_row_count": attempt.snapshot_section_row_count,
        "artifact_filename": attempt.artifact_filename,
        "artifact_sha256": attempt.artifact_sha256,
        "artifact_size_bytes": attempt.artifact_size_bytes,
        "verified_at_utc": attempt.verified_at_utc,
        "failure_code": attempt.failure_code,
        "created_at_utc": attempt.created_at_utc,
        "completed_at_utc": attempt.completed_at_utc,
        "revision": attempt.revision,
    }


__all__ = ["report_attempt_response"]
