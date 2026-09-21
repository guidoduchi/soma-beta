from __future__ import annotations

import re

from soma.foundation.application.command_boundary import (
    CommandBoundary,
    CommandEnvelope,
    PreparedMutation,
)
from soma.foundation.audit.writer import AuditEventInput, AuditResultRef, AuditWriter
from soma.foundation.errors import SomaError, ValidationError
from soma.foundation.identifiers import new_uuid4, require_uuid4, utc_epoch_seconds
from soma.foundation.jobs import DurableJobCoordinator, JobTypeRegistry
from soma.foundation.persistence.connections import ConnectionFactory
from soma.foundation.persistence.uow import UnitOfWork
from soma.foundation.strict_json import sha256_canonical_json

from ..algorithms.cohort_state import canonical_month_bounds
from ..audit_registry import build_product_line_sla_audit_registry
from ..jobs import (
    PRODUCT_LINE_SLA_JOB_CONTRACTS,
    SLA_REPORT_JOB_CONTRACT_VERSION,
    SLA_REPORT_JOB_TYPE,
)
from ..repositories.reports import ReportRepository

_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_PERIOD_TYPES = {"daily", "weekly", "monthly", "selected_range"}


class SlaReportOrchestrationService:
    """Public report request/cancellation owner; worker transitions live separately."""

    def __init__(self, connection_factory: ConnectionFactory) -> None:
        self._factory = connection_factory
        self._boundary = CommandBoundary(
            connection_factory,
            AuditWriter(build_product_line_sla_audit_registry()),
        )
        self._jobs = DurableJobCoordinator(
            connection_factory,
            JobTypeRegistry(PRODUCT_LINE_SLA_JOB_CONTRACTS),
        )

    @staticmethod
    def _scope_fingerprint(
        *,
        period_type: str,
        period_start_utc: int,
        period_end_utc: int,
        customer_org_id: str | None,
        as_of_utc: int,
    ) -> str:
        return sha256_canonical_json(
            {
                "schema": "SOMA_SLA_REPORT_SCOPE_V1",
                "period_type": period_type,
                "period_start_utc": period_start_utc,
                "period_end_utc": period_end_utc,
                "period_timezone": "America/Guayaquil",
                "scope_kind": "all_customers"
                if customer_org_id is None
                else "customer",
                "customer_org_id": customer_org_id,
                "as_of_utc": as_of_utc,
            }
        )

    @staticmethod
    def _attempt_response(connection, report_attempt_id: str) -> dict[str, object]:
        attempt = ReportRepository.get_attempt(connection, report_attempt_id)
        if attempt is None:
            raise SomaError("SLA_REPORT_ATTEMPT_STATE", "report attempt disappeared")
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

    def start_resolved(
        self,
        *,
        command_id: str,
        period_type: str,
        period_start_utc: int,
        period_end_utc: int,
        as_of_utc: int,
        customer_org_id: str | None,
        destination_request_token: str,
        actor_kind: str = "local_user",
        actor_id: str | None = None,
    ) -> dict[str, object]:
        require_uuid4(command_id)
        if period_type not in _PERIOD_TYPES:
            raise SomaError("SLA_REPORT_SCOPE_INVALID", "report period type is invalid")
        if (
            type(period_start_utc) is not int
            or type(period_end_utc) is not int
            or type(as_of_utc) is not int
            or period_start_utc < 0
            or period_end_utc <= period_start_utc
            or as_of_utc < period_start_utc
        ):
            raise SomaError("SLA_REPORT_SCOPE_INVALID", "report UTC period/as-of is invalid")
        customer_id = None if customer_org_id is None else require_uuid4(customer_org_id)
        if (
            not isinstance(destination_request_token, str)
            or _SHA256.fullmatch(destination_request_token) is None
        ):
            raise ValidationError("destination_request_token must be lowercase SHA-256")

        scope_fingerprint = self._scope_fingerprint(
            period_type=period_type,
            period_start_utc=period_start_utc,
            period_end_utc=period_end_utc,
            customer_org_id=customer_id,
            as_of_utc=as_of_utc,
        )
        envelope = CommandEnvelope(
            command_id=command_id,
            command_type="StartSlaReportGeneration",
            target_type="report_attempt",
            target_id=None,
            semantic_payload={
                "period_type": period_type,
                "period_start_utc": period_start_utc,
                "period_end_utc": period_end_utc,
                "period_timezone": "America/Guayaquil",
                "customer_org_id": customer_id,
                "as_of_utc": as_of_utc,
                "destination_request_token": destination_request_token,
            },
            authorizing_fingerprints={
                "scope": scope_fingerprint,
                "destination_request": destination_request_token,
            },
        )

        def prepare(uow: UnitOfWork) -> PreparedMutation:
            if customer_id is not None:
                row = uow.connection.execute(
                    "SELECT 1 FROM customer_organizations WHERE customer_org_id=?",
                    (customer_id,),
                ).fetchone()
                if row is None:
                    raise SomaError(
                        "SLA_REPORT_SCOPE_INVALID",
                        "report Customer Organization does not exist",
                    )

            report_attempt_id = new_uuid4()
            created_at = utc_epoch_seconds()

            def apply(inner: UnitOfWork):
                inner.connection.execute(
                    "INSERT INTO sla_report_attempts("
                    "report_attempt_id,period_type,period_start_utc,period_end_utc,period_timezone,"
                    "scope_kind,customer_org_id,as_of_utc,state,snapshot_hash,snapshot_member_count,"
                    "snapshot_cohort_count,snapshot_section_row_count,artifact_filename,artifact_sha256,"
                    "artifact_size_bytes,verified_at_utc,failure_code,created_at_utc,completed_at_utc,"
                    "revision,created_command_id,last_command_id"
                    ") VALUES (?,?,?,?,?,?,?,?,'staging',NULL,0,0,0,NULL,NULL,NULL,NULL,NULL,?,NULL,1,?,?)",
                    (
                        report_attempt_id,
                        period_type,
                        period_start_utc,
                        period_end_utc,
                        "America/Guayaquil",
                        "all_customers" if customer_id is None else "customer",
                        customer_id,
                        as_of_utc,
                        created_at,
                        command_id,
                        command_id,
                    ),
                )
                payload = {
                    "report_attempt_id": report_attempt_id,
                    "destination_request_token": destination_request_token,
                    "requested_by_command_id": command_id,
                }
                job_id = self._jobs.enqueue_or_coalesce(
                    inner,
                    SLA_REPORT_JOB_TYPE,
                    SLA_REPORT_JOB_CONTRACT_VERSION,
                    payload,
                    report_attempt_id,
                )
                inner.connection.execute(
                    "INSERT INTO sla_report_job_refs("
                    "report_attempt_id,job_id,destination_request_token,last_command_id"
                    ") VALUES (?,?,?,?)",
                    (
                        report_attempt_id,
                        job_id,
                        destination_request_token,
                        command_id,
                    ),
                )
                return AuditEventInput(
                    audit_event_id=new_uuid4(),
                    action_type="sla.report.started",
                    action_version=1,
                    actor_kind=actor_kind,
                    actor_id=actor_id,
                    target_type="report_attempt",
                    target_id=report_attempt_id,
                    command_id=command_id,
                    payload_schema="ReportAttemptAuditV1",
                    payload_version=1,
                    payload={
                        "report_attempt_id": report_attempt_id,
                        "event": "START",
                        "state_before": None,
                        "state_after": "staging",
                        "attempt_revision": 1,
                        "scope_fingerprint": scope_fingerprint,
                        "snapshot_hash": None,
                        "failure_code": None,
                    },
                    resulting_event_refs=(
                        AuditResultRef("report_attempt", report_attempt_id),
                    ),
                )

            return PreparedMutation(
                no_change=False,
                result_type="report_attempt",
                result_id=report_attempt_id,
                apply=apply,
                response_schema="ReportAttemptV1",
                response_factory=lambda inner: self._attempt_response(
                    inner.connection,
                    report_attempt_id,
                ),
            )

        return dict(self._boundary.execute(envelope, prepare).response)

    def cancel(
        self,
        *,
        command_id: str,
        report_attempt_id: str,
        expected_attempt_revision: int,
        actor_kind: str = "local_user",
        actor_id: str | None = None,
    ) -> dict[str, object]:
        """Cancel one nonterminal report and revoke its exact durable job atomically."""

        report_id = require_uuid4(report_attempt_id)
        if type(expected_attempt_revision) is not int or expected_attempt_revision <= 0:
            raise ValidationError("expected_attempt_revision must be a positive integer")
        envelope = CommandEnvelope(
            command_id=command_id,
            command_type="CancelSlaReportAttempt",
            target_type="report_attempt",
            target_id=report_id,
            semantic_payload={
                "report_attempt_id": report_id,
                "expected_attempt_revision": expected_attempt_revision,
            },
            base_revisions={"report_attempt": expected_attempt_revision},
        )

        def prepare(uow: UnitOfWork) -> PreparedMutation:
            attempt = ReportRepository.get_attempt(uow.connection, report_id)
            if attempt is None:
                raise SomaError(
                    "SLA_REPORT_ATTEMPT_STATE",
                    "report attempt does not exist",
                )
            if (
                attempt.state
                not in {"staging", "ready_to_generate", "generating", "verifying"}
                or attempt.revision != expected_attempt_revision
            ):
                raise SomaError(
                    "SLA_REPORT_ATTEMPT_STATE",
                    "report cancellation target is stale or terminal",
                )

            job_row = uow.connection.execute(
                "SELECT r.job_id,j.job_type,j.contract_version "
                "FROM sla_report_job_refs r "
                "JOIN durable_jobs j ON j.job_id=r.job_id "
                "WHERE r.report_attempt_id=?",
                (report_id,),
            ).fetchone()
            if job_row is None:
                raise SomaError(
                    "SLA_REPORT_CANCEL_UNSAFE",
                    "report attempt has no linked durable job",
                )
            job_id = require_uuid4(str(job_row[0]))
            if (
                str(job_row[1]) != SLA_REPORT_JOB_TYPE
                or int(job_row[2]) != SLA_REPORT_JOB_CONTRACT_VERSION
            ):
                raise SomaError(
                    "SLA_REPORT_CANCEL_UNSAFE",
                    "report attempt links an incompatible durable job",
                )

            prior_state = attempt.state
            scope_fingerprint = ReportRepository.scope_fingerprint(attempt)
            prior_snapshot_hash = attempt.snapshot_hash
            resulting_revision = expected_attempt_revision + 1
            completed_at = utc_epoch_seconds()

            def apply(inner: UnitOfWork):
                cancellation = self._jobs.cancel(
                    inner,
                    job_id,
                    SLA_REPORT_JOB_TYPE,
                    SLA_REPORT_JOB_CONTRACT_VERSION,
                    {
                        "report_attempt_id": report_id,
                        "command_id": command_id,
                    },
                )
                if (
                    cancellation.outcome == "TERMINAL_UNCHANGED"
                    and cancellation.prior_state == "completed"
                ):
                    raise SomaError(
                        "SLA_REPORT_CANCEL_UNSAFE",
                        "completed durable report job cannot be cancelled",
                    )

                # Only non-authoritative attempt-owned staging is removable.
                ReportRepository.cleanup_staging(inner.connection, report_id)
                updated = inner.connection.execute(
                    "UPDATE sla_report_attempts SET "
                    "state='cancelled',snapshot_hash=NULL,"
                    "snapshot_member_count=0,snapshot_cohort_count=0,"
                    "snapshot_section_row_count=0,artifact_filename=NULL,"
                    "artifact_sha256=NULL,artifact_size_bytes=NULL,"
                    "verified_at_utc=NULL,failure_code=NULL,completed_at_utc=?,"
                    "revision=?,last_command_id=? "
                    "WHERE report_attempt_id=? AND state=? AND revision=?",
                    (
                        completed_at,
                        resulting_revision,
                        command_id,
                        report_id,
                        prior_state,
                        expected_attempt_revision,
                    ),
                )
                if updated.rowcount != 1:
                    raise SomaError(
                        "SLA_REPORT_ATTEMPT_STATE",
                        "report cancellation lost authoritative revalidation",
                    )
                return AuditEventInput(
                    audit_event_id=new_uuid4(),
                    action_type="sla.report.cancelled_or_failed",
                    action_version=1,
                    actor_kind=actor_kind,
                    actor_id=actor_id,
                    target_type="report_attempt",
                    target_id=report_id,
                    command_id=command_id,
                    payload_schema="ReportAttemptAuditV1",
                    payload_version=1,
                    payload={
                        "report_attempt_id": report_id,
                        "event": "CANCELLED",
                        "state_before": prior_state,
                        "state_after": "cancelled",
                        "attempt_revision": resulting_revision,
                        "scope_fingerprint": scope_fingerprint,
                        "snapshot_hash": prior_snapshot_hash,
                        "failure_code": None,
                    },
                    resulting_event_refs=(
                        AuditResultRef("report_attempt", report_id),
                    ),
                )

            return PreparedMutation(
                no_change=False,
                result_type="report_attempt",
                result_id=report_id,
                apply=apply,
                response_schema="ReportAttemptV1",
                response_factory=lambda inner: self._attempt_response(
                    inner.connection,
                    report_id,
                ),
            )

        return dict(self._boundary.execute(envelope, prepare).response)

    def start_monthly(
        self,
        *,
        command_id: str,
        calendar_month: str,
        as_of_utc: int,
        customer_org_id: str | None,
        destination_request_token: str,
        actor_kind: str = "local_user",
        actor_id: str | None = None,
    ) -> dict[str, object]:
        start_utc, end_utc = canonical_month_bounds(calendar_month)
        return self.start_resolved(
            command_id=command_id,
            period_type="monthly",
            period_start_utc=start_utc,
            period_end_utc=end_utc,
            as_of_utc=as_of_utc,
            customer_org_id=customer_org_id,
            destination_request_token=destination_request_token,
            actor_kind=actor_kind,
            actor_id=actor_id,
        )


__all__ = ["SlaReportOrchestrationService"]
