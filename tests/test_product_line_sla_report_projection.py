from __future__ import annotations

from soma.product_line_sla.domain.reports import ReportAttemptRecord
from soma.product_line_sla.report_projection import report_attempt_response


def test_report_attempt_response_projection_is_exact() -> None:
    attempt = ReportAttemptRecord(
        report_attempt_id="11111111-1111-4111-8111-111111111111",
        period_type="daily",
        period_start_utc=10,
        period_end_utc=20,
        period_timezone="America/Guayaquil",
        scope_kind="all_customers",
        customer_org_id=None,
        as_of_utc=21,
        state="completed",
        snapshot_hash="a" * 64,
        snapshot_member_count=1,
        snapshot_cohort_count=2,
        snapshot_section_row_count=3,
        artifact_filename="sla.csv",
        artifact_sha256="b" * 64,
        artifact_size_bytes=123,
        verified_at_utc=22,
        failure_code=None,
        created_at_utc=9,
        completed_at_utc=23,
        revision=4,
        created_command_id="22222222-2222-4222-8222-222222222222",
        last_command_id="33333333-3333-4333-8333-333333333333",
    )
    assert report_attempt_response(attempt) == {
        "report_attempt_id": attempt.report_attempt_id,
        "period_type": "daily",
        "period_start_utc": 10,
        "period_end_utc": 20,
        "period_timezone": "America/Guayaquil",
        "scope_kind": "all_customers",
        "customer_org_id": None,
        "as_of_utc": 21,
        "state": "completed",
        "snapshot_hash": "a" * 64,
        "snapshot_member_count": 1,
        "snapshot_cohort_count": 2,
        "snapshot_section_row_count": 3,
        "artifact_filename": "sla.csv",
        "artifact_sha256": "b" * 64,
        "artifact_size_bytes": 123,
        "verified_at_utc": 22,
        "failure_code": None,
        "created_at_utc": 9,
        "completed_at_utc": 23,
        "revision": 4,
    }
