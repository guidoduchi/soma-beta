"""Pure canonical report materialization from already ordered snapshot rows.

The repository supplies sealed/staged rows from its existing read context. This
module cannot open a database, query live state, or own a transaction.
"""
from __future__ import annotations

import json
from collections.abc import Sequence

from soma.product_line_sla.domain.reports import ReportAttemptRecord


def build_report_snapshot(
    attempt: ReportAttemptRecord,
    *,
    member_rows: Sequence[Sequence[object]],
    tier_rows: Sequence[Sequence[object]],
    cohort_rows: Sequence[Sequence[object]],
    section_rows: Sequence[Sequence[object]],
) -> dict[str, object]:
    """Preserve the SOMA_REPORT_SNAPSHOT_V1 wire value and caller row order."""
    members: list[dict[str, object]] = []
    for row in member_rows:
        display = None if row[20] is None else json.loads(str(row[20]))
        members.append(
            {
                "member_ordinal": int(row[0]),
                "service_request_id": str(row[1]),
                "customer_org_id": None if row[2] is None else str(row[2]),
                "contract_id": None if row[3] is None else str(row[3]),
                "contract_product_line_id": None if row[4] is None else str(row[4]),
                "policy_revision_id": None if row[5] is None else str(row[5]),
                "classification_event_id": None if row[6] is None else str(row[6]),
                "severity": None if row[7] is None else str(row[7]),
                "report_date_utc": None if row[8] is None else int(row[8]),
                "status_class": str(row[9]),
                "endpoint_utc": None if row[10] is None else int(row[10]),
                "suspension_num": int(row[11]),
                "suspension_den": int(row[12]),
                "elapsed_num": None if row[13] is None else int(row[13]),
                "elapsed_den": None if row[14] is None else int(row[14]),
                "calculation_state": str(row[15]),
                "sla_input_token": str(row[16]),
                "source_report_date_evidence_id": None if row[17] is None else str(row[17]),
                "source_status_evidence_id": None if row[18] is None else str(row[18]),
                "source_suspension_evidence_id": None if row[19] is None else str(row[19]),
                "display_values": display,
            }
        )

    tiers = [
        {
            "service_request_id": str(row[0]),
            "policy_tier_id": str(row[1]),
            "individual_state": str(row[2]),
            "inclusive_boundary_met": bool(int(row[3])),
        }
        for row in tier_rows
    ]

    cohorts = [
        {
            "cohort_ordinal": int(row[0]),
            "calendar_month": str(row[1]),
            "customer_org_id": str(row[2]),
            "contract_id": str(row[3]),
            "contract_product_line_id": str(row[4]),
            "policy_revision_id": str(row[5]),
            "policy_tier_id": str(row[6]),
            "severity": str(row[7]),
            "denominator": int(row[8]),
            "terminal_met_count": int(row[9]),
            "terminal_exceeded_count": int(row[10]),
            "active_within_count": int(row[11]),
            "active_exceeded_count": int(row[12]),
            "state": str(row[13]),
            "is_final": bool(int(row[14])),
            "input_fingerprint": str(row[15]),
        }
        for row in cohort_rows
    ]

    sections = [
        {
            "section_kind": str(row[0]),
            "schema_name": str(row[1]),
            "schema_version": int(row[2]),
            "section_ordinal": int(row[3]),
            "row_ordinal": int(row[4]),
            "canonical_row_key": str(row[5]),
            "payload": json.loads(str(row[6])),
            "payload_sha256": str(row[7]),
        }
        for row in section_rows
    ]

    return {
        "schema": "SOMA_REPORT_SNAPSHOT_V1",
        "report_request": {
            "report_attempt_id": attempt.report_attempt_id,
            "period_type": attempt.period_type,
            "period_start_utc": attempt.period_start_utc,
            "period_end_utc": attempt.period_end_utc,
            "period_timezone": attempt.period_timezone,
            "scope_kind": attempt.scope_kind,
            "customer_org_id": attempt.customer_org_id,
            "as_of_utc": attempt.as_of_utc,
        },
        "members": members,
        "tiers": tiers,
        "cohorts": cohorts,
        "sections": sections,
    }


__all__ = ["build_report_snapshot"]
