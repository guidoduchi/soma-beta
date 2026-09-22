from __future__ import annotations

from ._cursor import cursor_envelope as _cursor

from dataclasses import asdict, dataclass

from soma.foundation.errors import SomaError, ValidationError
from soma.foundation.identifiers import require_uuid4
from soma.foundation.persistence.connections import ConnectionFactory
from soma.foundation.persistence.uow import ReadSnapshot
from soma.foundation.strict_json import sha256_canonical_json

from ..repositories.reports import ReportRepository

_CURSOR_FIELDS = {
    "version",
    "query_id",
    "sort_registry_id",
    "last_key_tuple",
    "filter_fingerprint",
    "null_order",
}
_STATES = {
    "staging",
    "ready_to_generate",
    "generating",
    "verifying",
    "completed",
    "failed",
    "cancelled",
}


@dataclass(frozen=True, slots=True)
class ReportPage:
    items: tuple[dict[str, object], ...]
    next_cursor: dict[str, object] | None
    exact_count: int


def _limit(value: int) -> int:
    if type(value) is not int or not 1 <= value <= 500:
        raise ValidationError("report page size must be an integer from 1 through 500")
    return value


def _cursor_key(
    value: dict[str, object] | None,
    *,
    query_id: str,
    sort_id: str,
    fingerprint: str,
    size: int,
) -> list[object] | None:
    if value is None:
        return None
    if not isinstance(value, dict) or set(value) != _CURSOR_FIELDS:
        raise ValidationError("report cursor fields are invalid")
    if (
        value["version"] != 1
        or value["query_id"] != query_id
        or value["sort_registry_id"] != sort_id
        or value["filter_fingerprint"] != fingerprint
        or value["null_order"] != "none"
    ):
        raise ValidationError("report cursor contract is invalid")
    key = value["last_key_tuple"]
    if not isinstance(key, list) or len(key) != size:
        raise ValidationError("report cursor key is invalid")
    return key


def _attempt_summary(attempt) -> dict[str, object]:
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


class ProductLineSlaReportQueryService:
    def __init__(self, connection_factory: ConnectionFactory) -> None:
        self._factory = connection_factory

    def list_attempts(
        self,
        *,
        state: str | None = None,
        period_type: str | None = None,
        customer_org_id: str | None = None,
        created_from_utc: int | None = None,
        created_to_utc: int | None = None,
        cursor: dict[str, object] | None = None,
        limit: int = 100,
    ) -> ReportPage:
        if state is not None and state not in _STATES:
            raise ValidationError("report state filter is invalid")
        if period_type is not None and period_type not in {"daily", "weekly", "monthly", "selected_range"}:
            raise ValidationError("report period filter is invalid")
        customer_id = None if customer_org_id is None else require_uuid4(customer_org_id)
        for value, label in ((created_from_utc, "created_from_utc"), (created_to_utc, "created_to_utc")):
            if value is not None and (type(value) is not int or value < 0):
                raise ValidationError(f"{label} must be a nonnegative UTC epoch second")
        if created_from_utc is not None and created_to_utc is not None and created_to_utc < created_from_utc:
            raise ValidationError("report created time filter is reversed")
        page_limit = _limit(limit)
        fingerprint = sha256_canonical_json(
            {
                "schema": "SOMA_REPORT_ATTEMPT_LIST_FILTER_V1",
                "state": state,
                "period_type": period_type,
                "customer_org_id": customer_id,
                "created_from_utc": created_from_utc,
                "created_to_utc": created_to_utc,
            }
        )
        key = _cursor_key(
            cursor,
            query_id="ListReportAttempts",
            sort_id="SLA_REPORT_ATTEMPT_DESC_V1",
            fingerprint=fingerprint,
            size=2,
        )
        clauses: list[str] = []
        params: list[object] = []
        if state is not None:
            clauses.append("state=?")
            params.append(state)
        if period_type is not None:
            clauses.append("period_type=?")
            params.append(period_type)
        if customer_id is not None:
            clauses.append("customer_org_id=?")
            params.append(customer_id)
        if created_from_utc is not None:
            clauses.append("created_at_utc>=?")
            params.append(created_from_utc)
        if created_to_utc is not None:
            clauses.append("created_at_utc<=?")
            params.append(created_to_utc)
        where = "" if not clauses else " WHERE " + " AND ".join(clauses)
        with ReadSnapshot(self._factory) as snapshot:
            ids = snapshot.connection.execute(
                f"SELECT report_attempt_id FROM sla_report_attempts{where} "
                "ORDER BY created_at_utc DESC,report_attempt_id DESC",
                tuple(params),
            ).fetchall()
            values = [
                _attempt_summary(
                    ReportRepository.get_attempt(snapshot.connection, str(row[0]))
                    or (_ for _ in ()).throw(SomaError("SLA_REPORT_ATTEMPT_STATE", "report attempt disappeared"))
                )
                for row in ids
            ]
        exact_count = len(values)
        if key is not None:
            if type(key[0]) is not int or not isinstance(key[1], str):
                raise ValidationError("report attempt cursor key is invalid")
            cursor_tuple = (int(key[0]), str(key[1]))
            values = [
                item
                for item in values
                if (int(item["created_at_utc"]), str(item["report_attempt_id"])) < cursor_tuple
            ]
        selected = values[: page_limit + 1]
        page = selected[:page_limit]
        next_cursor = None
        if len(selected) > page_limit and page:
            last = page[-1]
            next_cursor = _cursor(
                query_id="ListReportAttempts",
                sort_id="SLA_REPORT_ATTEMPT_DESC_V1",
                last_key=[int(last["created_at_utc"]), str(last["report_attempt_id"])],
                filter_fingerprint=fingerprint,
            )
        return ReportPage(tuple(page), next_cursor, exact_count)

    def get_attempt(self, *, report_attempt_id: str) -> dict[str, object]:
        report_id = require_uuid4(report_attempt_id)
        with ReadSnapshot(self._factory) as snapshot:
            attempt = ReportRepository.get_attempt(snapshot.connection, report_id)
            if attempt is None:
                raise SomaError("SLA_CATALOG_NOT_FOUND", "report attempt does not exist")
            result = _attempt_summary(attempt)
            sections = snapshot.connection.execute(
                "SELECT section_kind,schema_name,schema_version,section_ordinal,COUNT(*) "
                "FROM report_section_snapshots WHERE report_attempt_id=? "
                "GROUP BY section_kind,schema_name,schema_version,section_ordinal "
                "ORDER BY section_ordinal,section_kind",
                (report_id,),
            ).fetchall()
            result["section_summaries"] = tuple(
                {
                    "section_kind": str(row[0]),
                    "schema_name": str(row[1]),
                    "schema_version": int(row[2]),
                    "section_ordinal": int(row[3]),
                    "row_count": int(row[4]),
                }
                for row in sections
            )
            return result

    def list_members(
        self,
        *,
        report_attempt_id: str,
        cursor: dict[str, object] | None = None,
        limit: int = 100,
        allow_in_progress_diagnostic: bool = False,
    ) -> ReportPage:
        report_id = require_uuid4(report_attempt_id)
        if type(allow_in_progress_diagnostic) is not bool:
            raise ValidationError("diagnostic review flag must be bool")
        page_limit = _limit(limit)
        fingerprint = sha256_canonical_json(
            {
                "schema": "SOMA_REPORT_MEMBER_LIST_FILTER_V1",
                "report_attempt_id": report_id,
                "diagnostic": allow_in_progress_diagnostic,
            }
        )
        key = _cursor_key(
            cursor,
            query_id="ListReportMemberSnapshots",
            sort_id="SLA_REPORT_MEMBER_ORDINAL_ASC_V1",
            fingerprint=fingerprint,
            size=1,
        )
        with ReadSnapshot(self._factory) as snapshot:
            attempt = ReportRepository.get_attempt(snapshot.connection, report_id)
            if attempt is None:
                raise SomaError("SLA_CATALOG_NOT_FOUND", "report attempt does not exist")
            if attempt.state != "completed" and not allow_in_progress_diagnostic:
                raise SomaError("SLA_REPORT_ATTEMPT_STATE", "report member evidence is not completed")
            rows = snapshot.connection.execute(
                "SELECT report_member_snapshot_id,member_ordinal,service_request_id,customer_org_id,contract_id,"
                "contract_product_line_id,policy_revision_id,classification_event_id,severity,report_date_utc,"
                "status_class,endpoint_utc,suspension_num,suspension_den,elapsed_num,elapsed_den,"
                "calculation_state,sla_input_token,source_report_date_evidence_id,source_status_evidence_id,"
                "source_suspension_evidence_id,display_values_json "
                "FROM sla_report_member_snapshots WHERE report_attempt_id=? ORDER BY member_ordinal",
                (report_id,),
            ).fetchall()
            values: list[dict[str, object]] = []
            for row in rows:
                member_id = str(row[0])
                tiers = snapshot.connection.execute(
                    "SELECT policy_tier_id,individual_state,inclusive_boundary_met "
                    "FROM sla_report_member_tier_results WHERE report_attempt_id=? AND report_member_snapshot_id=? "
                    "ORDER BY policy_tier_id",
                    (report_id, member_id),
                ).fetchall()
                values.append(
                    {
                        "report_member_snapshot_id": member_id,
                        "member_ordinal": int(row[1]),
                        "service_request_id": str(row[2]),
                        "customer_org_id": None if row[3] is None else str(row[3]),
                        "contract_id": None if row[4] is None else str(row[4]),
                        "contract_product_line_id": None if row[5] is None else str(row[5]),
                        "policy_revision_id": None if row[6] is None else str(row[6]),
                        "classification_event_id": None if row[7] is None else str(row[7]),
                        "severity": None if row[8] is None else str(row[8]),
                        "report_date_utc": None if row[9] is None else int(row[9]),
                        "status_class": str(row[10]),
                        "endpoint_utc": None if row[11] is None else int(row[11]),
                        "suspension_num": int(row[12]),
                        "suspension_den": int(row[13]),
                        "elapsed_num": None if row[14] is None else int(row[14]),
                        "elapsed_den": None if row[15] is None else int(row[15]),
                        "calculation_state": str(row[16]),
                        "sla_input_token": str(row[17]),
                        "source_report_date_evidence_id": None if row[18] is None else str(row[18]),
                        "source_status_evidence_id": None if row[19] is None else str(row[19]),
                        "source_suspension_evidence_id": None if row[20] is None else str(row[20]),
                        "display_values_json": None if row[21] is None else str(row[21]),
                        "tier_results": tuple(
                            {
                                "policy_tier_id": str(tier[0]),
                                "individual_state": str(tier[1]),
                                "inclusive_boundary_met": bool(int(tier[2])),
                            }
                            for tier in tiers
                        ),
                    }
                )
        exact_count = len(values)
        if key is not None:
            if type(key[0]) is not int:
                raise ValidationError("report member cursor key is invalid")
            values = [item for item in values if int(item["member_ordinal"]) > int(key[0])]
        selected = values[: page_limit + 1]
        page = selected[:page_limit]
        next_cursor = None
        if len(selected) > page_limit and page:
            next_cursor = _cursor(
                query_id="ListReportMemberSnapshots",
                sort_id="SLA_REPORT_MEMBER_ORDINAL_ASC_V1",
                last_key=[int(page[-1]["member_ordinal"])],
                filter_fingerprint=fingerprint,
            )
        return ReportPage(tuple(page), next_cursor, exact_count)

    def list_cohorts(
        self,
        *,
        report_attempt_id: str,
        cursor: dict[str, object] | None = None,
        limit: int = 100,
    ) -> ReportPage:
        report_id = require_uuid4(report_attempt_id)
        page_limit = _limit(limit)
        fingerprint = sha256_canonical_json(
            {"schema": "SOMA_REPORT_COHORT_LIST_FILTER_V1", "report_attempt_id": report_id}
        )
        key = _cursor_key(
            cursor,
            query_id="ListReportCohortSnapshots",
            sort_id="SLA_REPORT_COHORT_ORDINAL_ASC_V1",
            fingerprint=fingerprint,
            size=1,
        )
        with ReadSnapshot(self._factory) as snapshot:
            if ReportRepository.get_attempt(snapshot.connection, report_id) is None:
                raise SomaError("SLA_CATALOG_NOT_FOUND", "report attempt does not exist")
            rows = snapshot.connection.execute(
                "SELECT report_cohort_snapshot_id,cohort_ordinal,calendar_month,customer_org_id,contract_id,"
                "contract_product_line_id,policy_revision_id,policy_tier_id,severity,denominator,"
                "terminal_met_count,terminal_exceeded_count,active_within_count,active_exceeded_count,"
                "state,is_final,input_fingerprint FROM sla_report_cohort_snapshots "
                "WHERE report_attempt_id=? ORDER BY cohort_ordinal",
                (report_id,),
            ).fetchall()
        values = [
            {
                "report_cohort_snapshot_id": str(row[0]),
                "cohort_ordinal": int(row[1]),
                "calendar_month": str(row[2]),
                "customer_org_id": str(row[3]),
                "contract_id": str(row[4]),
                "contract_product_line_id": str(row[5]),
                "policy_revision_id": str(row[6]),
                "policy_tier_id": str(row[7]),
                "severity": str(row[8]),
                "denominator": int(row[9]),
                "terminal_met_count": int(row[10]),
                "terminal_exceeded_count": int(row[11]),
                "active_within_count": int(row[12]),
                "active_exceeded_count": int(row[13]),
                "state": str(row[14]),
                "is_final": bool(int(row[15])),
                "input_fingerprint": str(row[16]),
            }
            for row in rows
        ]
        exact_count = len(values)
        if key is not None:
            if type(key[0]) is not int:
                raise ValidationError("report cohort cursor key is invalid")
            values = [item for item in values if int(item["cohort_ordinal"]) > int(key[0])]
        selected = values[: page_limit + 1]
        page = selected[:page_limit]
        next_cursor = None
        if len(selected) > page_limit and page:
            next_cursor = _cursor(
                query_id="ListReportCohortSnapshots",
                sort_id="SLA_REPORT_COHORT_ORDINAL_ASC_V1",
                last_key=[int(page[-1]["cohort_ordinal"])],
                filter_fingerprint=fingerprint,
            )
        return ReportPage(tuple(page), next_cursor, exact_count)

    def read_sealed_snapshot_for_artifact(
        self,
        *,
        report_attempt_id: str,
        snapshot_hash: str,
    ) -> dict[str, object]:
        report_id = require_uuid4(report_attempt_id)
        if not isinstance(snapshot_hash, str) or len(snapshot_hash) != 64:
            raise ValidationError("snapshot_hash must be lowercase SHA-256")
        with ReadSnapshot(self._factory) as snapshot:
            attempt = ReportRepository.get_attempt(snapshot.connection, report_id)
            if attempt is None:
                raise SomaError("SLA_CATALOG_NOT_FOUND", "report attempt does not exist")
            if attempt.state not in {"ready_to_generate", "generating", "verifying", "completed"}:
                raise SomaError("SLA_REPORT_ATTEMPT_STATE", "report snapshot is not sealed/readable")
            if attempt.snapshot_hash != snapshot_hash:
                raise SomaError("SLA_REPORT_SNAPSHOT_MISMATCH", "report snapshot hash differs")
            semantic = ReportRepository.snapshot_semantic_value(snapshot.connection, report_id)
            if sha256_canonical_json(semantic) != snapshot_hash:
                raise SomaError("SLA_REPORT_SNAPSHOT_MISMATCH", "persisted report snapshot changed")
            return semantic

    # Exact normative internal-query name used by the artifact writer contract.
    read_sealed_report_snapshot_for_artifact = read_sealed_snapshot_for_artifact


__all__ = ["ProductLineSlaReportQueryService", "ReportPage"]
