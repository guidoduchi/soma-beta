"""Canonical LLD-06 reports values; no persistence ownership."""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class ReportAttemptRecord:
    report_attempt_id: str
    period_type: str
    period_start_utc: int
    period_end_utc: int
    period_timezone: str
    scope_kind: str
    customer_org_id: str | None
    as_of_utc: int
    state: str
    snapshot_hash: str | None
    snapshot_member_count: int
    snapshot_cohort_count: int
    snapshot_section_row_count: int
    artifact_filename: str | None
    artifact_sha256: str | None
    artifact_size_bytes: int | None
    verified_at_utc: int | None
    failure_code: str | None
    created_at_utc: int
    completed_at_utc: int | None
    revision: int
    created_command_id: str
    last_command_id: str


__all__ = ["ReportAttemptRecord"]
