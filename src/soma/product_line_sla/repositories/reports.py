from __future__ import annotations

from typing import Any

from soma.foundation.errors import IntegrityFailure
from soma.product_line_sla.algorithms.report_snapshot import build_report_snapshot
from soma.foundation.identifiers import require_uuid4
from soma.foundation.strict_json import canonical_json_bytes, sha256_canonical_json
from soma.product_line_sla.domain.reports import (
    ReportAttemptRecord,
)


_ATTEMPT_STATES = {
    "staging",
    "ready_to_generate",
    "generating",
    "verifying",
    "completed",
    "failed",
    "cancelled",
}


class ReportRepository:
    @staticmethod
    def get_attempt(reader: Any, report_attempt_id: str) -> ReportAttemptRecord | None:
        report_id = require_uuid4(report_attempt_id)
        row = reader.execute(
            "SELECT report_attempt_id,period_type,period_start_utc,period_end_utc,period_timezone,"
            "scope_kind,customer_org_id,as_of_utc,state,snapshot_hash,snapshot_member_count,"
            "snapshot_cohort_count,snapshot_section_row_count,artifact_filename,artifact_sha256,"
            "artifact_size_bytes,verified_at_utc,failure_code,created_at_utc,completed_at_utc,"
            "revision,created_command_id,last_command_id "
            "FROM sla_report_attempts WHERE report_attempt_id=?",
            (report_id,),
        ).fetchone()
        if row is None:
            return None
        state = str(row[8])
        if state not in _ATTEMPT_STATES:
            raise IntegrityFailure("persisted SLA report attempt has invalid state")
        timezone = str(row[4])
        if timezone != "America/Guayaquil":
            raise IntegrityFailure("persisted SLA report attempt has invalid timezone")
        revision = int(row[20])
        if revision < 1:
            raise IntegrityFailure("persisted SLA report attempt has invalid revision")
        return ReportAttemptRecord(
            report_attempt_id=require_uuid4(str(row[0])),
            period_type=str(row[1]),
            period_start_utc=int(row[2]),
            period_end_utc=int(row[3]),
            period_timezone=timezone,
            scope_kind=str(row[5]),
            customer_org_id=None if row[6] is None else require_uuid4(str(row[6])),
            as_of_utc=int(row[7]),
            state=state,
            snapshot_hash=None if row[9] is None else str(row[9]),
            snapshot_member_count=int(row[10]),
            snapshot_cohort_count=int(row[11]),
            snapshot_section_row_count=int(row[12]),
            artifact_filename=None if row[13] is None else str(row[13]),
            artifact_sha256=None if row[14] is None else str(row[14]),
            artifact_size_bytes=None if row[15] is None else int(row[15]),
            verified_at_utc=None if row[16] is None else int(row[16]),
            failure_code=None if row[17] is None else str(row[17]),
            created_at_utc=int(row[18]),
            completed_at_utc=None if row[19] is None else int(row[19]),
            revision=revision,
            created_command_id=require_uuid4(str(row[21])),
            last_command_id=require_uuid4(str(row[22])),
        )

    @staticmethod
    def scope_fingerprint(attempt: ReportAttemptRecord) -> str:
        return sha256_canonical_json(
            {
                "schema": "SOMA_SLA_REPORT_SCOPE_V1",
                "period_type": attempt.period_type,
                "period_start_utc": attempt.period_start_utc,
                "period_end_utc": attempt.period_end_utc,
                "period_timezone": attempt.period_timezone,
                "scope_kind": attempt.scope_kind,
                "customer_org_id": attempt.customer_org_id,
                "as_of_utc": attempt.as_of_utc,
            }
        )

    @staticmethod
    def job_identity(reader: Any, report_attempt_id: str) -> tuple[str, str, str | None]:
        row = reader.execute(
            "SELECT r.job_id,r.destination_request_token,j.checkpoint_json "
            "FROM sla_report_job_refs r JOIN durable_jobs j ON j.job_id=r.job_id "
            "WHERE r.report_attempt_id=?",
            (require_uuid4(report_attempt_id),),
        ).fetchone()
        if row is None:
            raise IntegrityFailure("SLA report attempt lacks its durable job reference")
        return require_uuid4(str(row[0])), str(row[1]), None if row[2] is None else str(row[2])

    @staticmethod
    def counts(reader: Any, report_attempt_id: str) -> tuple[int, int, int, int]:
        report_id = require_uuid4(report_attempt_id)
        member_count = int(
            reader.execute(
                "SELECT COUNT(*) FROM sla_report_member_snapshots WHERE report_attempt_id=?",
                (report_id,),
            ).fetchone()[0]
        )
        tier_count = int(
            reader.execute(
                "SELECT COUNT(*) FROM sla_report_member_tier_results WHERE report_attempt_id=?",
                (report_id,),
            ).fetchone()[0]
        )
        cohort_count = int(
            reader.execute(
                "SELECT COUNT(*) FROM sla_report_cohort_snapshots WHERE report_attempt_id=?",
                (report_id,),
            ).fetchone()[0]
        )
        section_count = int(
            reader.execute(
                "SELECT COUNT(*) FROM report_section_snapshots WHERE report_attempt_id=?",
                (report_id,),
            ).fetchone()[0]
        )
        return member_count, tier_count, cohort_count, section_count

    @classmethod
    def snapshot_semantic_value(
        cls,
        reader: Any,
        report_attempt_id: str,
    ) -> dict[str, object]:
        attempt = cls.get_attempt(reader, report_attempt_id)
        if attempt is None:
            raise IntegrityFailure("SLA report attempt disappeared during snapshot hashing")

        member_rows = reader.execute(
            "SELECT member_ordinal,service_request_id,customer_org_id,contract_id,"
            "contract_product_line_id,policy_revision_id,classification_event_id,severity,"
            "report_date_utc,status_class,endpoint_utc,suspension_num,suspension_den,"
            "elapsed_num,elapsed_den,calculation_state,sla_input_token,"
            "source_report_date_evidence_id,source_status_evidence_id,"
            "source_suspension_evidence_id,display_values_json "
            "FROM sla_report_member_snapshots WHERE report_attempt_id=? "
            "ORDER BY service_request_id",
            (attempt.report_attempt_id,),
        ).fetchall()

        tier_rows = reader.execute(
            "SELECT m.service_request_id,t.policy_tier_id,t.individual_state,t.inclusive_boundary_met "
            "FROM sla_report_member_tier_results t "
            "JOIN sla_report_member_snapshots m "
            "ON m.report_member_snapshot_id=t.report_member_snapshot_id "
            "WHERE t.report_attempt_id=? "
            "ORDER BY m.service_request_id,t.policy_tier_id",
            (attempt.report_attempt_id,),
        ).fetchall()

        cohort_rows = reader.execute(
            "SELECT cohort_ordinal,calendar_month,customer_org_id,contract_id,"
            "contract_product_line_id,policy_revision_id,policy_tier_id,severity,denominator,"
            "terminal_met_count,terminal_exceeded_count,active_within_count,active_exceeded_count,"
            "state,is_final,input_fingerprint "
            "FROM sla_report_cohort_snapshots WHERE report_attempt_id=? "
            "ORDER BY calendar_month,customer_org_id,contract_id,contract_product_line_id,severity,policy_tier_id",
            (attempt.report_attempt_id,),
        ).fetchall()

        section_rows = reader.execute(
            "SELECT section_kind,schema_name,schema_version,section_ordinal,row_ordinal,"
            "canonical_row_key,payload_json,payload_sha256 "
            "FROM report_section_snapshots WHERE report_attempt_id=? "
            "ORDER BY section_ordinal,row_ordinal,canonical_row_key",
            (attempt.report_attempt_id,),
        ).fetchall()

        return build_report_snapshot(
            attempt, member_rows=member_rows, tier_rows=tier_rows,
            cohort_rows=cohort_rows, section_rows=section_rows,
        )

    @classmethod
    def snapshot_hash(cls, reader: Any, report_attempt_id: str) -> str:
        return sha256_canonical_json(
            cls.snapshot_semantic_value(reader, report_attempt_id)
        )

    @classmethod
    def snapshot_canonical_bytes(cls, reader: Any, report_attempt_id: str) -> bytes:
        return canonical_json_bytes(
            cls.snapshot_semantic_value(reader, report_attempt_id)
        )

    @staticmethod
    def cleanup_staging(reader: Any, report_attempt_id: str) -> None:
        report_id = require_uuid4(report_attempt_id)
        reader.execute(
            "DELETE FROM sla_report_member_tier_results WHERE report_attempt_id=?",
            (report_id,),
        )
        reader.execute(
            "DELETE FROM sla_report_member_snapshots WHERE report_attempt_id=?",
            (report_id,),
        )
        reader.execute(
            "DELETE FROM sla_report_cohort_snapshots WHERE report_attempt_id=?",
            (report_id,),
        )
        reader.execute(
            "DELETE FROM report_section_snapshots WHERE report_attempt_id=?",
            (report_id,),
        )


__all__ = ["ReportAttemptRecord", "ReportRepository"]
