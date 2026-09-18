from __future__ import annotations

import hashlib
import re
from typing import Any

from soma.foundation.application.command_boundary import (
    CommandBoundary,
    CommandEnvelope,
    PreparedMutation,
)
from soma.foundation.application.command_receipts import (
    CommandReceipt,
    CommandReceiptStore,
    CommittedCommandResult,
)
from soma.foundation.audit.writer import AuditEventInput, AuditResultRef, AuditWriter
from soma.foundation.errors import (
    IdempotencyConflict,
    IdempotencyResultUnavailable,
    IntegrityFailure,
    SomaError,
    ValidationError,
)
from soma.foundation.identifiers import new_uuid4, require_uuid4, utc_epoch_seconds
from soma.foundation.persistence.connections import ConnectionFactory
from soma.foundation.persistence.uow import UnitOfWork
from soma.foundation.strict_json import (
    canonical_json_bytes_bounded,
    loads_canonical_json,
    sha256_canonical_json,
)

from ..audit_registry import build_product_line_sla_audit_registry
from ..jobs import (
    SLA_REPORT_JOB_CONTRACT_VERSION,
    SLA_REPORT_JOB_TYPE,
    validate_report_job_checkpoint,
)
from ..repositories.reports import ReportAttemptRecord, ReportRepository

_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_FAILURE = re.compile(r"^[A-Z][A-Z0-9_]{0,63}$")
_MEMBER_FIELDS = frozenset(
    {
        "report_member_snapshot_id",
        "member_ordinal",
        "service_request_id",
        "customer_org_id",
        "contract_id",
        "contract_product_line_id",
        "policy_revision_id",
        "classification_event_id",
        "severity",
        "report_date_utc",
        "status_class",
        "endpoint_utc",
        "suspension_num",
        "suspension_den",
        "elapsed_num",
        "elapsed_den",
        "calculation_state",
        "sla_input_token",
        "source_report_date_evidence_id",
        "source_status_evidence_id",
        "source_suspension_evidence_id",
        "display_values_json",
    }
)
_TIER_FIELDS = frozenset(
    {
        "report_member_tier_result_id",
        "report_member_snapshot_id",
        "policy_tier_id",
        "individual_state",
        "inclusive_boundary_met",
    }
)
_COHORT_FIELDS = frozenset(
    {
        "report_cohort_snapshot_id",
        "cohort_ordinal",
        "calendar_month",
        "customer_org_id",
        "contract_id",
        "contract_product_line_id",
        "policy_revision_id",
        "policy_tier_id",
        "severity",
        "denominator",
        "terminal_met_count",
        "terminal_exceeded_count",
        "active_within_count",
        "active_exceeded_count",
        "state",
        "is_final",
        "input_fingerprint",
    }
)
_SECTION_FIELDS = frozenset(
    {
        "report_section_snapshot_id",
        "section_kind",
        "schema_name",
        "schema_version",
        "section_ordinal",
        "row_ordinal",
        "canonical_row_key",
        "payload_json",
        "payload_sha256",
    }
)


def _require_sha(value: Any, label: str) -> str:
    if not isinstance(value, str) or _SHA256.fullmatch(value) is None:
        raise ValidationError(f"{label} must be lowercase SHA-256 hex")
    return value


def _positive(value: Any, label: str) -> int:
    if type(value) is not int or value < 1:
        raise ValidationError(f"{label} must be int>=1")
    return value


def _nonnegative(value: Any, label: str) -> int:
    if type(value) is not int or value < 0:
        raise ValidationError(f"{label} must be int>=0")
    return value


def _optional_uuid(value: Any, label: str) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise ValidationError(f"{label} must be UUID or null")
    return require_uuid4(value)


def _filename(value: Any, label: str) -> str:
    if (
        not isinstance(value, str)
        or not value
        or len(value.encode("utf-8")) > 4096
        or any(ch in value for ch in ("/", "\\", "\x00"))
        or value in {".", ".."}
    ):
        raise ValidationError(f"{label} must be a bounded filename-only identity")
    return value


def _attempt_response(attempt: ReportAttemptRecord) -> dict[str, object]:
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


def _transition_response(
    attempt: ReportAttemptRecord,
    *,
    candidate_filename: str | None = None,
) -> dict[str, object]:
    return {
        "outcome": "APPLIED",
        "report_attempt_id": attempt.report_attempt_id,
        "state": attempt.state,
        "resulting_attempt_revision": attempt.revision,
        "snapshot_hash": attempt.snapshot_hash,
        "snapshot_member_count": attempt.snapshot_member_count,
        "snapshot_cohort_count": attempt.snapshot_cohort_count,
        "snapshot_section_row_count": attempt.snapshot_section_row_count,
        "candidate_filename": candidate_filename,
    }


def _validate_member(row: dict[str, object]) -> None:
    if set(row) != _MEMBER_FIELDS:
        raise ValidationError("report member row shape is invalid")
    require_uuid4(str(row["report_member_snapshot_id"]))
    _positive(row["member_ordinal"], "member_ordinal")
    require_uuid4(str(row["service_request_id"]))
    for key in (
        "customer_org_id",
        "contract_id",
        "contract_product_line_id",
        "policy_revision_id",
        "classification_event_id",
        "source_report_date_evidence_id",
        "source_status_evidence_id",
        "source_suspension_evidence_id",
    ):
        _optional_uuid(row[key], key)
    if row["severity"] is not None and not isinstance(row["severity"], str):
        raise ValidationError("report member severity is invalid")
    for key in ("report_date_utc", "endpoint_utc"):
        if row[key] is not None:
            _nonnegative(row[key], key)
    _nonnegative(row["suspension_num"], "suspension_num")
    _positive(row["suspension_den"], "suspension_den")
    if row["elapsed_num"] is not None and type(row["elapsed_num"]) is not int:
        raise ValidationError("elapsed_num is invalid")
    if row["elapsed_den"] is not None:
        _positive(row["elapsed_den"], "elapsed_den")
    if row["status_class"] not in {"active", "resolved", "closed", "cancelled", "unknown"}:
        raise ValidationError("report member status_class is invalid")
    if not isinstance(row["calculation_state"], str) or not row["calculation_state"]:
        raise ValidationError("report member calculation_state is invalid")
    _require_sha(row["sla_input_token"], "sla_input_token")
    display = row["display_values_json"]
    if display is not None:
        if not isinstance(display, str):
            raise ValidationError("display_values_json must be canonical JSON text or null")
        loads_canonical_json(
            display,
            max_bytes=16_384,
            max_depth=4,
            max_collection_items=64,
        )


def _validate_tier(row: dict[str, object]) -> None:
    if set(row) != _TIER_FIELDS:
        raise ValidationError("report member tier row shape is invalid")
    for key in (
        "report_member_tier_result_id",
        "report_member_snapshot_id",
        "policy_tier_id",
    ):
        require_uuid4(str(row[key]))
    if row["individual_state"] not in {
        "active_within",
        "active_exceeded",
        "terminal_met",
        "terminal_exceeded",
    }:
        raise ValidationError("report member tier state is invalid")
    if type(row["inclusive_boundary_met"]) is not bool:
        raise ValidationError("report member tier boundary flag must be boolean")


def _validate_cohort(row: dict[str, object]) -> None:
    if set(row) != _COHORT_FIELDS:
        raise ValidationError("report cohort row shape is invalid")
    require_uuid4(str(row["report_cohort_snapshot_id"]))
    _positive(row["cohort_ordinal"], "cohort_ordinal")
    for key in (
        "customer_org_id",
        "contract_id",
        "contract_product_line_id",
        "policy_revision_id",
        "policy_tier_id",
    ):
        require_uuid4(str(row[key]))
    if not isinstance(row["calendar_month"], str) or len(row["calendar_month"]) != 7:
        raise ValidationError("report cohort calendar month is invalid")
    if not isinstance(row["severity"], str) or not row["severity"]:
        raise ValidationError("report cohort severity is invalid")
    counts = []
    for key in (
        "denominator",
        "terminal_met_count",
        "terminal_exceeded_count",
        "active_within_count",
        "active_exceeded_count",
    ):
        counts.append(_nonnegative(row[key], key))
    if sum(counts[1:]) != counts[0]:
        raise ValidationError("report cohort counts do not equal denominator")
    if row["state"] not in {
        "pending",
        "currently_met",
        "at_risk",
        "breached",
        "final_met",
    }:
        raise ValidationError("report cohort state is invalid")
    if type(row["is_final"]) is not bool:
        raise ValidationError("report cohort is_final must be boolean")
    _require_sha(row["input_fingerprint"], "input_fingerprint")


def _validate_section(row: dict[str, object]) -> None:
    if set(row) != _SECTION_FIELDS:
        raise ValidationError("report section row shape is invalid")
    require_uuid4(str(row["report_section_snapshot_id"]))
    for key in ("section_kind", "schema_name", "canonical_row_key"):
        if not isinstance(row[key], str) or not row[key]:
            raise ValidationError(f"report section {key} is invalid")
    _positive(row["schema_version"], "schema_version")
    _positive(row["section_ordinal"], "section_ordinal")
    _positive(row["row_ordinal"], "row_ordinal")
    if not isinstance(row["payload_json"], str):
        raise ValidationError("report section payload_json must be canonical JSON text")
    payload = loads_canonical_json(
        row["payload_json"],
        max_bytes=65_536,
        max_depth=8,
        max_collection_items=512,
    )
    expected = sha256_canonical_json(payload)
    if _require_sha(row["payload_sha256"], "payload_sha256") != expected:
        raise ValidationError("report section payload hash mismatch")


class SlaReportWorkerService:
    def __init__(self, connection_factory: ConnectionFactory) -> None:
        self._factory = connection_factory
        self._receipts = CommandReceiptStore()
        self._boundary = CommandBoundary(
            connection_factory,
            AuditWriter(build_product_line_sla_audit_registry()),
        )

    @staticmethod
    def batch_payload_hash(
        *,
        member_rows: tuple[dict[str, object], ...],
        tier_rows: tuple[dict[str, object], ...],
        cohort_rows: tuple[dict[str, object], ...],
        section_rows: tuple[dict[str, object], ...],
    ) -> str:
        return sha256_canonical_json(
            {
                "schema": "SOMA_REPORT_SNAPSHOT_BATCH_V1",
                "member_rows": list(member_rows),
                "tier_rows": list(tier_rows),
                "cohort_rows": list(cohort_rows),
                "section_rows": list(section_rows),
            }
        )

    @staticmethod
    def _validate_batch(
        *,
        member_rows: tuple[dict[str, object], ...],
        tier_rows: tuple[dict[str, object], ...],
        cohort_rows: tuple[dict[str, object], ...],
        section_rows: tuple[dict[str, object], ...],
    ) -> None:
        if not (member_rows or tier_rows or cohort_rows or section_rows):
            raise ValidationError("report snapshot batch must contain at least one row")
        if len(member_rows) > 2000:
            raise ValidationError("report member batch exceeds hard limit")
        for row in member_rows:
            _validate_member(row)
        for row in tier_rows:
            _validate_tier(row)
        for row in cohort_rows:
            _validate_cohort(row)
        for row in section_rows:
            _validate_section(row)
        if tuple(
            (int(row["member_ordinal"]), str(row["service_request_id"]))
            for row in member_rows
        ) != tuple(
            sorted(
                (int(row["member_ordinal"]), str(row["service_request_id"]))
                for row in member_rows
            )
        ):
            raise ValidationError("report member rows are not canonically ordered")
        if tuple(
            (int(row["cohort_ordinal"]), str(row["report_cohort_snapshot_id"]))
            for row in cohort_rows
        ) != tuple(
            sorted(
                (int(row["cohort_ordinal"]), str(row["report_cohort_snapshot_id"]))
                for row in cohort_rows
            )
        ):
            raise ValidationError("report cohort rows are not canonically ordered")
        if tuple(
            (
                int(row["section_ordinal"]),
                int(row["row_ordinal"]),
                str(row["canonical_row_key"]),
            )
            for row in section_rows
        ) != tuple(
            sorted(
                (
                    int(row["section_ordinal"]),
                    int(row["row_ordinal"]),
                    str(row["canonical_row_key"]),
                )
                for row in section_rows
            )
        ):
            raise ValidationError("report section rows are not canonically ordered")

    @staticmethod
    def _require_generation(
        connection,
        *,
        report_attempt_id: str,
        snapshot_generation_token: str,
    ) -> str:
        row = connection.execute(
            "SELECT r.job_id,j.job_type,j.contract_version,j.state,j.checkpoint_json "
            "FROM sla_report_job_refs r JOIN durable_jobs j ON j.job_id=r.job_id "
            "WHERE r.report_attempt_id=?",
            (report_attempt_id,),
        ).fetchone()
        if row is None:
            raise IntegrityFailure("report attempt lacks linked durable job")
        if str(row[1]) != SLA_REPORT_JOB_TYPE or int(row[2]) != SLA_REPORT_JOB_CONTRACT_VERSION:
            raise IntegrityFailure("report attempt links the wrong durable job contract")
        if str(row[3]) != "running":
            raise SomaError("SLA_REPORT_ATTEMPT_STATE", "report job is not currently running")
        if row[4] is None:
            raise SomaError("SLA_REPORT_ATTEMPT_STATE", "report job lacks snapshot checkpoint")
        checkpoint = loads_canonical_json(
            str(row[4]),
            max_bytes=65_536,
            max_depth=8,
            max_collection_items=512,
        )
        validate_report_job_checkpoint(checkpoint)
        if (
            checkpoint["phase"] != "snapshotting"
            or checkpoint["snapshot_generation_token"] != snapshot_generation_token
        ):
            raise SomaError("SLA_REPORT_SNAPSHOT_MISMATCH", "snapshot generation token is stale")
        return require_uuid4(str(row[0]))

    @staticmethod
    def _decode_receipt_result(exact: CommittedCommandResult) -> dict[str, object]:
        if exact.response_schema != "ReportSnapshotBatchResultV1" or exact.response_version != 1:
            raise IntegrityFailure("report batch replay result schema is invalid")
        response = loads_canonical_json(
            exact.response_json,
            max_bytes=65_536,
            max_depth=4,
            max_collection_items=64,
        )
        encoded = exact.response_json.encode("utf-8", errors="strict")
        if hashlib.sha256(encoded).hexdigest() != exact.response_sha256:
            raise IntegrityFailure("report batch replay result hash is invalid")
        if not isinstance(response, dict):
            raise IntegrityFailure("report batch replay response is invalid")
        return response

    def stage_batch(
        self,
        *,
        command_id: str,
        report_attempt_id: str,
        snapshot_generation_token: str,
        batch_ordinal: int,
        batch_payload_sha256: str,
        expected_attempt_revision: int,
        member_rows: tuple[dict[str, object], ...] = (),
        tier_rows: tuple[dict[str, object], ...] = (),
        cohort_rows: tuple[dict[str, object], ...] = (),
        section_rows: tuple[dict[str, object], ...] = (),
    ) -> dict[str, object]:
        command = require_uuid4(command_id)
        report_id = require_uuid4(report_attempt_id)
        if (
            not isinstance(snapshot_generation_token, str)
            or not snapshot_generation_token
            or len(snapshot_generation_token.encode("utf-8")) > 256
        ):
            raise ValidationError("snapshot_generation_token is invalid")
        _positive(batch_ordinal, "batch_ordinal")
        _positive(expected_attempt_revision, "expected_attempt_revision")
        supplied_hash = _require_sha(batch_payload_sha256, "batch_payload_sha256")
        self._validate_batch(
            member_rows=member_rows,
            tier_rows=tier_rows,
            cohort_rows=cohort_rows,
            section_rows=section_rows,
        )
        computed_hash = self.batch_payload_hash(
            member_rows=member_rows,
            tier_rows=tier_rows,
            cohort_rows=cohort_rows,
            section_rows=section_rows,
        )
        if supplied_hash != computed_hash:
            raise ValidationError("report batch payload hash mismatch")

        envelope = CommandEnvelope(
            command_id=command,
            command_type="StageReportSnapshotBatch",
            target_type="report_attempt",
            target_id=report_id,
            semantic_payload={
                "report_attempt_id": report_id,
                "snapshot_generation_token": snapshot_generation_token,
                "batch_ordinal": batch_ordinal,
                "batch_payload_sha256": supplied_hash,
                "expected_attempt_revision": expected_attempt_revision,
                "member_rows": list(member_rows),
                "tier_rows": list(tier_rows),
                "cohort_rows": list(cohort_rows),
                "section_rows": list(section_rows),
            },
            base_revisions={"report_attempt": expected_attempt_revision},
            authorizing_fingerprints={"batch_payload": supplied_hash},
        )
        request_hash = envelope.request_hash()

        with UnitOfWork(self._factory) as uow:
            existing = self._receipts.get(uow, command)
            if existing is not None:
                if (
                    existing.command_type != envelope.command_type
                    or existing.request_hash != request_hash
                    or existing.target_type != envelope.target_type
                    or existing.target_id != envelope.target_id
                ):
                    raise IdempotencyConflict()
                exact = self._receipts.get_exact_result(uow, command)
                if exact is None:
                    raise IdempotencyResultUnavailable()
                return self._decode_receipt_result(exact)

            attempt = ReportRepository.get_attempt(uow.connection, report_id)
            if attempt is None:
                raise SomaError("SLA_REPORT_ATTEMPT_STATE", "report attempt does not exist")
            if attempt.state != "staging" or attempt.revision != expected_attempt_revision:
                raise SomaError("SLA_STALE", "report staging revision/state changed")
            self._require_generation(
                uow.connection,
                report_attempt_id=report_id,
                snapshot_generation_token=snapshot_generation_token,
            )

            self._receipts.insert(
                uow,
                CommandReceipt(
                    command_id=command,
                    command_type=envelope.command_type,
                    request_hash=request_hash,
                    target_type=envelope.target_type,
                    target_id=envelope.target_id,
                    committed_at_utc=utc_epoch_seconds(),
                    result_type="report_snapshot_batch",
                    result_id=report_id,
                ),
            )

            uow.connection.executemany(
                "INSERT INTO sla_report_member_snapshots("
                "report_member_snapshot_id,report_attempt_id,member_ordinal,service_request_id,"
                "customer_org_id,contract_id,contract_product_line_id,policy_revision_id,"
                "classification_event_id,severity,report_date_utc,status_class,endpoint_utc,"
                "suspension_num,suspension_den,elapsed_num,elapsed_den,calculation_state,"
                "sla_input_token,source_report_date_evidence_id,source_status_evidence_id,"
                "source_suspension_evidence_id,display_values_json"
                ") VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                [
                    (
                        row["report_member_snapshot_id"],
                        report_id,
                        row["member_ordinal"],
                        row["service_request_id"],
                        row["customer_org_id"],
                        row["contract_id"],
                        row["contract_product_line_id"],
                        row["policy_revision_id"],
                        row["classification_event_id"],
                        row["severity"],
                        row["report_date_utc"],
                        row["status_class"],
                        row["endpoint_utc"],
                        row["suspension_num"],
                        row["suspension_den"],
                        row["elapsed_num"],
                        row["elapsed_den"],
                        row["calculation_state"],
                        row["sla_input_token"],
                        row["source_report_date_evidence_id"],
                        row["source_status_evidence_id"],
                        row["source_suspension_evidence_id"],
                        row["display_values_json"],
                    )
                    for row in member_rows
                ],
            )
            uow.connection.executemany(
                "INSERT INTO sla_report_member_tier_results("
                "report_member_tier_result_id,report_attempt_id,report_member_snapshot_id,"
                "policy_tier_id,individual_state,inclusive_boundary_met"
                ") VALUES (?,?,?,?,?,?)",
                [
                    (
                        row["report_member_tier_result_id"],
                        report_id,
                        row["report_member_snapshot_id"],
                        row["policy_tier_id"],
                        row["individual_state"],
                        1 if row["inclusive_boundary_met"] else 0,
                    )
                    for row in tier_rows
                ],
            )
            uow.connection.executemany(
                "INSERT INTO sla_report_cohort_snapshots("
                "report_cohort_snapshot_id,report_attempt_id,cohort_ordinal,calendar_month,"
                "customer_org_id,contract_id,contract_product_line_id,policy_revision_id,"
                "policy_tier_id,severity,denominator,terminal_met_count,terminal_exceeded_count,"
                "active_within_count,active_exceeded_count,state,is_final,input_fingerprint"
                ") VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                [
                    (
                        row["report_cohort_snapshot_id"],
                        report_id,
                        row["cohort_ordinal"],
                        row["calendar_month"],
                        row["customer_org_id"],
                        row["contract_id"],
                        row["contract_product_line_id"],
                        row["policy_revision_id"],
                        row["policy_tier_id"],
                        row["severity"],
                        row["denominator"],
                        row["terminal_met_count"],
                        row["terminal_exceeded_count"],
                        row["active_within_count"],
                        row["active_exceeded_count"],
                        row["state"],
                        1 if row["is_final"] else 0,
                        row["input_fingerprint"],
                    )
                    for row in cohort_rows
                ],
            )
            uow.connection.executemany(
                "INSERT INTO report_section_snapshots("
                "report_section_snapshot_id,report_attempt_id,section_kind,schema_name,"
                "schema_version,section_ordinal,row_ordinal,canonical_row_key,payload_json,payload_sha256"
                ") VALUES (?,?,?,?,?,?,?,?,?,?)",
                [
                    (
                        row["report_section_snapshot_id"],
                        report_id,
                        row["section_kind"],
                        row["schema_name"],
                        row["schema_version"],
                        row["section_ordinal"],
                        row["row_ordinal"],
                        row["canonical_row_key"],
                        row["payload_json"],
                        row["payload_sha256"],
                    )
                    for row in section_rows
                ],
            )
            resulting_revision = expected_attempt_revision + 1
            uow.connection.execute(
                "UPDATE sla_report_attempts SET "
                "snapshot_member_count=snapshot_member_count+?,"
                "snapshot_cohort_count=snapshot_cohort_count+?,"
                "snapshot_section_row_count=snapshot_section_row_count+?,"
                "revision=?,last_command_id=? "
                "WHERE report_attempt_id=? AND state='staging' AND revision=?",
                (
                    len(member_rows),
                    len(cohort_rows),
                    len(section_rows),
                    resulting_revision,
                    command,
                    report_id,
                    expected_attempt_revision,
                ),
            )
            attempt_after = ReportRepository.get_attempt(uow.connection, report_id)
            if attempt_after is None or attempt_after.revision != resulting_revision:
                raise IntegrityFailure("report staging update lost authoritative revalidation")
            response = {
                "outcome": "APPLIED",
                "report_attempt_id": report_id,
                "batch_ordinal": batch_ordinal,
                "batch_payload_sha256": supplied_hash,
                "resulting_attempt_revision": resulting_revision,
                "snapshot_member_count": attempt_after.snapshot_member_count,
                "snapshot_cohort_count": attempt_after.snapshot_cohort_count,
                "snapshot_section_row_count": attempt_after.snapshot_section_row_count,
            }
            encoded = canonical_json_bytes_bounded(
                response,
                max_bytes=65_536,
                max_depth=4,
                max_collection_items=64,
            )
            self._receipts.insert_exact_result(
                uow,
                CommittedCommandResult(
                    command_id=command,
                    response_schema="ReportSnapshotBatchResultV1",
                    response_version=1,
                    response_json=encoded.decode("utf-8"),
                    response_sha256=hashlib.sha256(encoded).hexdigest(),
                ),
            )
            return response

    def _transition(
        self,
        *,
        command_id: str,
        command_type: str,
        report_attempt_id: str,
        expected_attempt_revision: int,
        expected_state: str,
        resulting_state: str,
        snapshot_hash: str,
        candidate_filename: str | None = None,
        event: str,
        actor_kind: str = "system",
        actor_id: str | None = None,
    ) -> dict[str, object]:
        report_id = require_uuid4(report_attempt_id)
        _positive(expected_attempt_revision, "expected_attempt_revision")
        sealed_hash = _require_sha(snapshot_hash, "snapshot_hash")
        candidate = (
            None
            if candidate_filename is None
            else _filename(candidate_filename, "candidate_filename")
        )
        semantic: dict[str, object] = {
            "report_attempt_id": report_id,
            "expected_attempt_revision": expected_attempt_revision,
            "snapshot_hash": sealed_hash,
        }
        if candidate is not None:
            semantic["candidate_filename"] = candidate
        envelope = CommandEnvelope(
            command_id=command_id,
            command_type=command_type,
            target_type="report_attempt",
            target_id=report_id,
            semantic_payload=semantic,
            base_revisions={"report_attempt": expected_attempt_revision},
            authorizing_fingerprints={"snapshot": sealed_hash},
        )

        def prepare(uow: UnitOfWork) -> PreparedMutation:
            attempt = ReportRepository.get_attempt(uow.connection, report_id)
            if attempt is None:
                raise SomaError("SLA_REPORT_ATTEMPT_STATE", "report attempt does not exist")
            if (
                attempt.state != expected_state
                or attempt.revision != expected_attempt_revision
                or attempt.snapshot_hash != sealed_hash
            ):
                raise SomaError("SLA_REPORT_ATTEMPT_STATE", "report transition state is stale")
            if expected_state != "ready_to_generate" and attempt.snapshot_hash is None:
                raise IntegrityFailure("report transition lacks sealed snapshot")
            resulting_revision = expected_attempt_revision + 1
            scope_fingerprint = ReportRepository.scope_fingerprint(attempt)

            def apply(inner: UnitOfWork):
                if resulting_state == "verifying":
                    inner.connection.execute(
                        "UPDATE sla_report_attempts SET state='verifying',artifact_filename=?,"
                        "revision=?,last_command_id=? WHERE report_attempt_id=? AND state=? AND revision=?",
                        (
                            candidate,
                            resulting_revision,
                            command_id,
                            report_id,
                            expected_state,
                            expected_attempt_revision,
                        ),
                    )
                else:
                    inner.connection.execute(
                        "UPDATE sla_report_attempts SET state=?,revision=?,last_command_id=? "
                        "WHERE report_attempt_id=? AND state=? AND revision=?",
                        (
                            resulting_state,
                            resulting_revision,
                            command_id,
                            report_id,
                            expected_state,
                            expected_attempt_revision,
                        ),
                    )
                return AuditEventInput(
                    audit_event_id=new_uuid4(),
                    action_type="sla.report.progressed",
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
                        "event": event,
                        "state_before": expected_state,
                        "state_after": resulting_state,
                        "attempt_revision": resulting_revision,
                        "scope_fingerprint": scope_fingerprint,
                        "snapshot_hash": sealed_hash,
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
                response_schema="ReportAttemptTransitionResultV1",
                response_factory=lambda inner: _transition_response(
                    ReportRepository.get_attempt(inner.connection, report_id)
                    or (_ for _ in ()).throw(IntegrityFailure("report transition lost attempt")),
                    candidate_filename=candidate,
                ),
            )

        return dict(self._boundary.execute(envelope, prepare).response)

    def seal(
        self,
        *,
        command_id: str,
        report_attempt_id: str,
        snapshot_generation_token: str,
        expected_attempt_revision: int,
        final_member_count: int,
        final_cohort_count: int,
        final_section_row_count: int,
        snapshot_hash: str,
    ) -> dict[str, object]:
        report_id = require_uuid4(report_attempt_id)
        _positive(expected_attempt_revision, "expected_attempt_revision")
        for value, label in (
            (final_member_count, "final_member_count"),
            (final_cohort_count, "final_cohort_count"),
            (final_section_row_count, "final_section_row_count"),
        ):
            _nonnegative(value, label)
        sealed_hash = _require_sha(snapshot_hash, "snapshot_hash")
        envelope = CommandEnvelope(
            command_id=command_id,
            command_type="SealReportSnapshot",
            target_type="report_attempt",
            target_id=report_id,
            semantic_payload={
                "report_attempt_id": report_id,
                "snapshot_generation_token": snapshot_generation_token,
                "expected_attempt_revision": expected_attempt_revision,
                "final_member_count": final_member_count,
                "final_cohort_count": final_cohort_count,
                "final_section_row_count": final_section_row_count,
                "snapshot_hash": sealed_hash,
            },
            base_revisions={"report_attempt": expected_attempt_revision},
            authorizing_fingerprints={"snapshot": sealed_hash},
        )

        def prepare(uow: UnitOfWork) -> PreparedMutation:
            attempt = ReportRepository.get_attempt(uow.connection, report_id)
            if attempt is None:
                raise SomaError("SLA_REPORT_ATTEMPT_STATE", "report attempt does not exist")
            if attempt.state != "staging" or attempt.revision != expected_attempt_revision:
                raise SomaError("SLA_STALE", "report seal state/revision changed")
            self._require_generation(
                uow.connection,
                report_attempt_id=report_id,
                snapshot_generation_token=snapshot_generation_token,
            )
            members, _tiers, cohorts, sections = ReportRepository.counts(
                uow.connection,
                report_id,
            )
            if (members, cohorts, sections) != (
                final_member_count,
                final_cohort_count,
                final_section_row_count,
            ):
                raise SomaError("SLA_REPORT_SNAPSHOT_MISMATCH", "report staged counts differ")
            recomputed = ReportRepository.snapshot_hash(uow.connection, report_id)
            if recomputed != sealed_hash:
                raise SomaError("SLA_REPORT_SNAPSHOT_MISMATCH", "report snapshot hash differs")
            resulting_revision = expected_attempt_revision + 1
            scope_fingerprint = ReportRepository.scope_fingerprint(attempt)

            def apply(inner: UnitOfWork):
                inner.connection.execute(
                    "UPDATE sla_report_attempts SET state='ready_to_generate',snapshot_hash=?,"
                    "snapshot_member_count=?,snapshot_cohort_count=?,snapshot_section_row_count=?,"
                    "revision=?,last_command_id=? WHERE report_attempt_id=? AND state='staging' AND revision=?",
                    (
                        sealed_hash,
                        final_member_count,
                        final_cohort_count,
                        final_section_row_count,
                        resulting_revision,
                        command_id,
                        report_id,
                        expected_attempt_revision,
                    ),
                )
                return AuditEventInput(
                    audit_event_id=new_uuid4(),
                    action_type="sla.report.progressed",
                    action_version=1,
                    actor_kind="system",
                    target_type="report_attempt",
                    target_id=report_id,
                    command_id=command_id,
                    payload_schema="ReportAttemptAuditV1",
                    payload_version=1,
                    payload={
                        "report_attempt_id": report_id,
                        "event": "SEAL",
                        "state_before": "staging",
                        "state_after": "ready_to_generate",
                        "attempt_revision": resulting_revision,
                        "scope_fingerprint": scope_fingerprint,
                        "snapshot_hash": sealed_hash,
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
                response_schema="ReportAttemptTransitionResultV1",
                response_factory=lambda inner: _transition_response(
                    ReportRepository.get_attempt(inner.connection, report_id)
                    or (_ for _ in ()).throw(IntegrityFailure("sealed report disappeared"))
                ),
            )

        return dict(self._boundary.execute(envelope, prepare).response)

    def mark_generating(
        self,
        *,
        command_id: str,
        report_attempt_id: str,
        expected_attempt_revision: int,
        snapshot_hash: str,
    ) -> dict[str, object]:
        return self._transition(
            command_id=command_id,
            command_type="MarkReportGenerating",
            report_attempt_id=report_attempt_id,
            expected_attempt_revision=expected_attempt_revision,
            expected_state="ready_to_generate",
            resulting_state="generating",
            snapshot_hash=snapshot_hash,
            event="GENERATING",
        )

    def mark_verifying(
        self,
        *,
        command_id: str,
        report_attempt_id: str,
        expected_attempt_revision: int,
        snapshot_hash: str,
        candidate_filename: str,
    ) -> dict[str, object]:
        return self._transition(
            command_id=command_id,
            command_type="MarkReportVerifying",
            report_attempt_id=report_attempt_id,
            expected_attempt_revision=expected_attempt_revision,
            expected_state="generating",
            resulting_state="verifying",
            snapshot_hash=snapshot_hash,
            candidate_filename=candidate_filename,
            event="VERIFYING",
        )

    def complete(
        self,
        *,
        command_id: str,
        report_attempt_id: str,
        expected_attempt_revision: int,
        snapshot_hash: str,
        artifact_completion: dict[str, object],
    ) -> dict[str, object]:
        report_id = require_uuid4(report_attempt_id)
        _positive(expected_attempt_revision, "expected_attempt_revision")
        sealed_hash = _require_sha(snapshot_hash, "snapshot_hash")
        expected_fields = {
            "report_attempt_id",
            "snapshot_hash",
            "candidate_filename",
            "artifact_filename",
            "artifact_sha256",
            "artifact_size_bytes",
            "verified_at_utc",
        }
        if not isinstance(artifact_completion, dict) or set(artifact_completion) != expected_fields:
            raise ValidationError("artifact completion proof shape is invalid")
        if require_uuid4(str(artifact_completion["report_attempt_id"])) != report_id:
            raise ValidationError("artifact completion report identity differs")
        if _require_sha(artifact_completion["snapshot_hash"], "artifact snapshot_hash") != sealed_hash:
            raise ValidationError("artifact completion snapshot differs")
        candidate = _filename(artifact_completion["candidate_filename"], "candidate_filename")
        final_filename = _filename(artifact_completion["artifact_filename"], "artifact_filename")
        artifact_sha = _require_sha(artifact_completion["artifact_sha256"], "artifact_sha256")
        artifact_size = _positive(artifact_completion["artifact_size_bytes"], "artifact_size_bytes")
        verified_at = _nonnegative(artifact_completion["verified_at_utc"], "verified_at_utc")

        envelope = CommandEnvelope(
            command_id=command_id,
            command_type="CompleteSlaReport",
            target_type="report_attempt",
            target_id=report_id,
            semantic_payload={
                "report_attempt_id": report_id,
                "expected_attempt_revision": expected_attempt_revision,
                "snapshot_hash": sealed_hash,
                "artifact_completion": dict(artifact_completion),
            },
            base_revisions={"report_attempt": expected_attempt_revision},
            authorizing_fingerprints={
                "snapshot": sealed_hash,
                "artifact": artifact_sha,
            },
        )

        def prepare(uow: UnitOfWork) -> PreparedMutation:
            attempt = ReportRepository.get_attempt(uow.connection, report_id)
            if attempt is None:
                raise SomaError("SLA_REPORT_ATTEMPT_STATE", "report attempt does not exist")
            if (
                attempt.state != "verifying"
                or attempt.revision != expected_attempt_revision
                or attempt.snapshot_hash != sealed_hash
                or attempt.artifact_filename != candidate
                or attempt.artifact_sha256 is not None
                or attempt.artifact_size_bytes is not None
                or attempt.verified_at_utc is not None
            ):
                raise SomaError("SLA_REPORT_ATTEMPT_STATE", "report completion state is stale")
            members, _tiers, cohorts, sections = ReportRepository.counts(
                uow.connection,
                report_id,
            )
            if (members, cohorts, sections) != (
                attempt.snapshot_member_count,
                attempt.snapshot_cohort_count,
                attempt.snapshot_section_row_count,
            ):
                raise SomaError("SLA_REPORT_SNAPSHOT_MISMATCH", "sealed report counts changed")
            if ReportRepository.snapshot_hash(uow.connection, report_id) != sealed_hash:
                raise SomaError("SLA_REPORT_SNAPSHOT_MISMATCH", "sealed report snapshot changed")
            resulting_revision = expected_attempt_revision + 1
            completed_at = utc_epoch_seconds()

            def apply(inner: UnitOfWork):
                inner.connection.execute(
                    "UPDATE sla_report_attempts SET state='completed',artifact_filename=?,"
                    "artifact_sha256=?,artifact_size_bytes=?,verified_at_utc=?,completed_at_utc=?,"
                    "revision=?,last_command_id=? WHERE report_attempt_id=? AND state='verifying' AND revision=?",
                    (
                        final_filename,
                        artifact_sha,
                        artifact_size,
                        verified_at,
                        completed_at,
                        resulting_revision,
                        command_id,
                        report_id,
                        expected_attempt_revision,
                    ),
                )
                return AuditEventInput(
                    audit_event_id=new_uuid4(),
                    action_type="sla.report.completed",
                    action_version=1,
                    actor_kind="system",
                    target_type="report_attempt",
                    target_id=report_id,
                    command_id=command_id,
                    payload_schema="CompletedReportAuditV1",
                    payload_version=1,
                    payload={
                        "report_attempt_id": report_id,
                        "snapshot_hash": sealed_hash,
                        "artifact_filename": final_filename,
                        "artifact_sha256": artifact_sha,
                        "artifact_size_bytes": artifact_size,
                        "verified_at_utc": verified_at,
                        "completed_at_utc": completed_at,
                        "member_count": members,
                        "cohort_count": cohorts,
                        "section_count": sections,
                    },
                    resulting_event_refs=(
                        AuditResultRef("artifact", artifact_sha),
                        AuditResultRef("completed_report_evidence", report_id),
                    ),
                )

            return PreparedMutation(
                no_change=False,
                result_type="completed_report_evidence",
                result_id=report_id,
                apply=apply,
                response_schema="ReportAttemptV1",
                response_factory=lambda inner: _attempt_response(
                    ReportRepository.get_attempt(inner.connection, report_id)
                    or (_ for _ in ()).throw(IntegrityFailure("completed report disappeared"))
                ),
            )

        return dict(self._boundary.execute(envelope, prepare).response)

    def fail(
        self,
        *,
        command_id: str,
        report_attempt_id: str,
        expected_attempt_revision: int,
        failure_code: str,
    ) -> dict[str, object]:
        report_id = require_uuid4(report_attempt_id)
        _positive(expected_attempt_revision, "expected_attempt_revision")
        if not isinstance(failure_code, str) or _FAILURE.fullmatch(failure_code) is None:
            raise ValidationError("report failure_code is invalid")
        envelope = CommandEnvelope(
            command_id=command_id,
            command_type="FailSlaReportAttempt",
            target_type="report_attempt",
            target_id=report_id,
            semantic_payload={
                "report_attempt_id": report_id,
                "expected_attempt_revision": expected_attempt_revision,
                "failure_code": failure_code,
            },
            base_revisions={"report_attempt": expected_attempt_revision},
        )

        def prepare(uow: UnitOfWork) -> PreparedMutation:
            attempt = ReportRepository.get_attempt(uow.connection, report_id)
            if attempt is None:
                raise SomaError("SLA_REPORT_ATTEMPT_STATE", "report attempt does not exist")
            if attempt.state not in {
                "staging",
                "ready_to_generate",
                "generating",
                "verifying",
            } or attempt.revision != expected_attempt_revision:
                raise SomaError("SLA_REPORT_ATTEMPT_STATE", "report failure target is stale/terminal")
            prior_state = attempt.state
            scope_fingerprint = ReportRepository.scope_fingerprint(attempt)
            resulting_revision = expected_attempt_revision + 1
            completed_at = utc_epoch_seconds()

            def apply(inner: UnitOfWork):
                ReportRepository.cleanup_staging(inner.connection, report_id)
                inner.connection.execute(
                    "UPDATE sla_report_attempts SET state='failed',snapshot_hash=NULL,"
                    "snapshot_member_count=0,snapshot_cohort_count=0,snapshot_section_row_count=0,"
                    "artifact_filename=NULL,artifact_sha256=NULL,artifact_size_bytes=NULL,"
                    "verified_at_utc=NULL,failure_code=?,completed_at_utc=?,revision=?,last_command_id=? "
                    "WHERE report_attempt_id=? AND revision=?",
                    (
                        failure_code,
                        completed_at,
                        resulting_revision,
                        command_id,
                        report_id,
                        expected_attempt_revision,
                    ),
                )
                return AuditEventInput(
                    audit_event_id=new_uuid4(),
                    action_type="sla.report.cancelled_or_failed",
                    action_version=1,
                    actor_kind="system",
                    target_type="report_attempt",
                    target_id=report_id,
                    command_id=command_id,
                    payload_schema="ReportAttemptAuditV1",
                    payload_version=1,
                    payload={
                        "report_attempt_id": report_id,
                        "event": "FAILED",
                        "state_before": prior_state,
                        "state_after": "failed",
                        "attempt_revision": resulting_revision,
                        "scope_fingerprint": scope_fingerprint,
                        "snapshot_hash": attempt.snapshot_hash,
                        "failure_code": failure_code,
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
                response_factory=lambda inner: _attempt_response(
                    ReportRepository.get_attempt(inner.connection, report_id)
                    or (_ for _ in ()).throw(IntegrityFailure("failed report disappeared"))
                ),
            )

        return dict(self._boundary.execute(envelope, prepare).response)


__all__ = ["SlaReportWorkerService"]
