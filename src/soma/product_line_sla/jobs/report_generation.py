from __future__ import annotations

from datetime import UTC, datetime, timedelta, timezone
from typing import Any

from soma.foundation.contracts.foundation import DurableJobClaim
from soma.foundation.errors import IntegrityFailure, SomaError, ValidationError
from soma.foundation.identifiers import new_uuid4
from soma.foundation.jobs import DurableJobCoordinator, JobTypeRegistry
from soma.foundation.persistence.connections import ConnectionFactory
from soma.foundation.persistence.uow import ReadSnapshot, UnitOfWork
from soma.foundation.strict_json import (
    canonical_json_bytes,
    loads_canonical_json,
    sha256_canonical_json,
)
from soma.tickets.service_request_sla_input import ServiceRequestSlaInputReader

from ..algorithms.cohort_state import CanonicalCohortCalculator, canonical_month_bounds
from ..algorithms.individual_sla import IndividualSlaCalculator
from ..artifacts.xlsx_report import SlaReportXlsxArtifact
from ..report_sections import ReportSectionContributorRegistry
from ..repositories.reports import ReportRepository
from ..services.report_worker import SlaReportWorkerService
from . import (
    PRODUCT_LINE_SLA_JOB_CONTRACTS,
    SLA_REPORT_JOB_CONTRACT_VERSION,
    SLA_REPORT_JOB_TYPE,
    validate_report_job_checkpoint,
    validate_report_job_payload,
)

_BATCH_SIZE = 500
_JOB_JSON_BYTES = 65_536


class SlaReportGenerationWorker:
    def __init__(
        self,
        connection_factory: ConnectionFactory,
        section_registry: ReportSectionContributorRegistry | None = None,
        artifact: SlaReportXlsxArtifact | None = None,
    ) -> None:
        self._factory = connection_factory
        self._sections = section_registry or ReportSectionContributorRegistry()
        self._jobs = DurableJobCoordinator(
            connection_factory,
            JobTypeRegistry(PRODUCT_LINE_SLA_JOB_CONTRACTS),
        )
        self._worker = SlaReportWorkerService(
            connection_factory,
            self._sections,
        )
        self._artifact = artifact

    @staticmethod
    def _json_object(text: str, *, label: str) -> dict[str, Any]:
        value = loads_canonical_json(
            text,
            max_bytes=_JOB_JSON_BYTES,
            max_depth=8,
            max_collection_items=512,
        )
        if not isinstance(value, dict):
            raise IntegrityFailure(f"{label} must be a canonical JSON object")
        return value

    @classmethod
    def _payload(cls, claim: DurableJobClaim) -> dict[str, Any]:
        if (
            claim.job_type != SLA_REPORT_JOB_TYPE
            or claim.contract_version != SLA_REPORT_JOB_CONTRACT_VERSION
        ):
            raise ValidationError("claim is not SLA_REPORT_GENERATION_V1")
        payload = cls._json_object(claim.payload_json, label="report job payload")
        validate_report_job_payload(payload)
        return payload

    @classmethod
    def _existing_checkpoint(cls, claim: DurableJobClaim) -> dict[str, Any] | None:
        if claim.checkpoint_json is None:
            return None
        checkpoint = cls._json_object(
            claim.checkpoint_json,
            label="report job checkpoint",
        )
        validate_report_job_checkpoint(checkpoint)
        return checkpoint

    @staticmethod
    def _calendar_month(attempt) -> str:
        # Beta reporting/SLA month authority is America/Guayaquil. Modern mainland
        # Ecuador is UTC-05 and the exact canonical bounds are revalidated below.
        local_start = datetime.fromtimestamp(
            attempt.period_start_utc,
            UTC,
        ).astimezone(timezone(timedelta(hours=-5)))
        calendar_month = f"{local_start.year:04d}-{local_start.month:02d}"
        if canonical_month_bounds(calendar_month) != (
            attempt.period_start_utc,
            attempt.period_end_utc,
        ):
            raise ValidationError(
                "report snapshot conductor currently requires an exact canonical monthly period"
            )
        return calendar_month

    @staticmethod
    def _pending(
        *,
        kind: str,
        command_id: str,
        expected_revision: int,
        request_fingerprint: str,
        batch_ordinal: int | None = None,
        batch_payload_sha256: str | None = None,
        snapshot_hash: str | None = None,
        candidate_filename: str | None = None,
        completion_proof_fingerprint: str | None = None,
    ) -> dict[str, object]:
        return {
            "kind": kind,
            "command_id": command_id,
            "expected_attempt_revision": expected_revision,
            "request_fingerprint": request_fingerprint,
            "batch_ordinal": batch_ordinal,
            "batch_payload_sha256": batch_payload_sha256,
            "snapshot_hash": snapshot_hash,
            "candidate_filename": candidate_filename,
            "completion_proof_fingerprint": completion_proof_fingerprint,
        }

    @staticmethod
    def _member_row(
        *,
        result,
        member_ordinal: int,
        member_snapshot_id: str,
    ) -> dict[str, object]:
        return {
            "report_member_snapshot_id": member_snapshot_id,
            "member_ordinal": member_ordinal,
            "service_request_id": result.service_request_id,
            "customer_org_id": result.customer_org_id,
            "contract_id": result.contract_id,
            "contract_product_line_id": result.contract_product_line_id,
            "policy_revision_id": result.policy_revision_id,
            "classification_event_id": result.classification_event_id,
            "severity": result.severity,
            "report_date_utc": result.report_date_utc,
            "status_class": result.status_class,
            "endpoint_utc": result.endpoint_utc,
            "suspension_num": result.suspension_numerator_seconds,
            "suspension_den": result.suspension_denominator,
            "elapsed_num": result.effective_elapsed_numerator_seconds,
            "elapsed_den": result.effective_elapsed_denominator,
            "calculation_state": result.calculation_state,
            "sla_input_token": result.sla_input_token,
            "source_report_date_evidence_id": result.source_report_date_evidence_id,
            "source_status_evidence_id": result.source_status_evidence_id,
            "source_suspension_evidence_id": result.source_suspension_evidence_id,
            # REPORT_MEMBER_DISPLAY_V1 is intentionally not populated until its
            # exact allowlist is pinned. This is the minimizing fail-closed choice.
            "display_values_json": None,
        }

    @staticmethod
    def _tier_rows(result, member_snapshot_id: str) -> tuple[dict[str, object], ...]:
        return tuple(
            {
                "report_member_tier_result_id": new_uuid4(),
                "report_member_snapshot_id": member_snapshot_id,
                "policy_tier_id": tier.policy_tier_id,
                "individual_state": tier.individual_state,
                "inclusive_boundary_met": tier.inclusive_boundary_met,
            }
            for tier in result.tier_results
        )

    def _checkpoint_batch(
        self,
        claim: DurableJobClaim,
        *,
        checkpoint: dict[str, object],
        expected_revision: int,
        generation_token: str,
        batch_ordinal: int,
        member_rows: tuple[dict[str, object], ...] = (),
        tier_rows: tuple[dict[str, object], ...] = (),
        cohort_rows: tuple[dict[str, object], ...] = (),
        section_rows: tuple[dict[str, object], ...] = (),
    ) -> tuple[dict[str, object], int]:
        batch_hash = self._worker.batch_payload_hash(
            member_rows=member_rows,
            tier_rows=tier_rows,
            cohort_rows=cohort_rows,
            section_rows=section_rows,
        )
        command_id = new_uuid4()
        request_fingerprint = sha256_canonical_json(
            {
                "schema": "SOMA_REPORT_STAGE_BATCH_INTENT_V1",
                "report_attempt_id": self._payload(claim)["report_attempt_id"],
                "generation_token": generation_token,
                "batch_ordinal": batch_ordinal,
                "batch_payload_sha256": batch_hash,
                "expected_attempt_revision": expected_revision,
            }
        )
        pending = {
            **checkpoint,
            "attempt_revision": expected_revision,
            "next_batch_ordinal": batch_ordinal,
            "pending_command": self._pending(
                kind="stage_batch",
                command_id=command_id,
                expected_revision=expected_revision,
                request_fingerprint=request_fingerprint,
                batch_ordinal=batch_ordinal,
                batch_payload_sha256=batch_hash,
            ),
        }
        self._jobs.checkpoint(claim, pending)
        response = self._worker.stage_batch(
            command_id=command_id,
            report_attempt_id=str(self._payload(claim)["report_attempt_id"]),
            snapshot_generation_token=generation_token,
            batch_ordinal=batch_ordinal,
            batch_payload_sha256=batch_hash,
            expected_attempt_revision=expected_revision,
            member_rows=member_rows,
            tier_rows=tier_rows,
            cohort_rows=cohort_rows,
            section_rows=section_rows,
        )
        resulting_revision = int(response["resulting_attempt_revision"])
        committed = {
            **pending,
            "attempt_revision": resulting_revision,
            "next_batch_ordinal": batch_ordinal + 1,
            "pending_command": None,
        }
        self._jobs.checkpoint(claim, committed)
        return committed, resulting_revision

    def _current_checkpoint(self, claim: DurableJobClaim) -> dict[str, Any]:
        with UnitOfWork(self._factory) as uow:
            checkpoint_json = self._jobs.assert_claim_current(uow, claim)
        if checkpoint_json is None:
            raise IntegrityFailure("SLA report job has no persisted checkpoint")
        checkpoint = self._json_object(
            checkpoint_json,
            label="report job checkpoint",
        )
        validate_report_job_checkpoint(checkpoint)
        return checkpoint

    def snapshot_and_seal(self, claim: DurableJobClaim) -> str:
        payload = self._payload(claim)
        if self._existing_checkpoint(claim) is not None:
            raise IntegrityFailure(
                "interrupted report snapshot generation is not resumable from mutable live state"
            )
        report_attempt_id = str(payload["report_attempt_id"])
        generation_token = new_uuid4()
        checkpoint: dict[str, object] = {
            "phase": "snapshotting",
            "attempt_revision": 1,
            "snapshot_generation_token": generation_token,
            "next_batch_ordinal": 1,
            "pending_command": None,
            "candidate_filename": None,
            "published_artifact": None,
        }
        self._jobs.checkpoint(claim, checkpoint)

        with ReadSnapshot(self._factory) as domain_snapshot:
            attempt = ReportRepository.get_attempt(
                domain_snapshot.connection,
                report_attempt_id,
            )
            if attempt is None or attempt.state != "staging":
                raise IntegrityFailure("report snapshot owner is missing or no longer staging")
            if attempt.revision != 1:
                raise IntegrityFailure("fresh report snapshot attempt did not begin at revision 1")
            calendar_month = self._calendar_month(attempt)
            customer_scope = attempt.customer_org_id
            report_request = {
                "report_attempt_id": report_attempt_id,
                "period_type": attempt.period_type,
                "period_start_utc": attempt.period_start_utc,
                "period_end_utc": attempt.period_end_utc,
                "period_timezone": attempt.period_timezone,
                "scope_kind": attempt.scope_kind,
                "customer_org_id": attempt.customer_org_id,
                "as_of_utc": attempt.as_of_utc,
            }

            expected_revision = attempt.revision
            batch_ordinal = 1
            member_ordinal = 0
            cursor: str | None = None
            while True:
                page = ServiceRequestSlaInputReader.list_report_date_month(
                    domain_snapshot.connection,
                    attempt.period_start_utc,
                    attempt.period_end_utc,
                    customer_scope,
                    cursor,
                    _BATCH_SIZE,
                )
                member_rows: list[dict[str, object]] = []
                tier_rows: list[dict[str, object]] = []
                for sla_input in page.items:
                    result = IndividualSlaCalculator.calculate(
                        domain_snapshot.connection,
                        sla_input.service_request_id,
                        attempt.as_of_utc,
                    )
                    member_ordinal += 1
                    member_snapshot_id = new_uuid4()
                    member_rows.append(
                        self._member_row(
                            result=result,
                            member_ordinal=member_ordinal,
                            member_snapshot_id=member_snapshot_id,
                        )
                    )
                    tier_rows.extend(self._tier_rows(result, member_snapshot_id))
                if member_rows or tier_rows:
                    checkpoint, expected_revision = self._checkpoint_batch(
                        claim,
                        checkpoint=checkpoint,
                        expected_revision=expected_revision,
                        generation_token=generation_token,
                        batch_ordinal=batch_ordinal,
                        member_rows=tuple(member_rows),
                        tier_rows=tuple(tier_rows),
                    )
                    batch_ordinal += 1
                if page.next_cursor is None:
                    break
                cursor = page.next_cursor

            cohorts = CanonicalCohortCalculator.calculate_month(
                domain_snapshot.connection,
                calendar_month=calendar_month,
                as_of_utc=attempt.as_of_utc,
                customer_scope=customer_scope,
            ).cohorts
            cohort_rows = [
                {
                    "report_cohort_snapshot_id": new_uuid4(),
                    "cohort_ordinal": index,
                    "calendar_month": cohort.calendar_month,
                    "customer_org_id": cohort.customer_org_id,
                    "contract_id": cohort.contract_id,
                    "contract_product_line_id": cohort.contract_product_line_id,
                    "policy_revision_id": cohort.policy_revision_id,
                    "policy_tier_id": cohort.policy_tier_id,
                    "severity": cohort.severity,
                    "denominator": cohort.denominator,
                    "terminal_met_count": cohort.terminal_met_count,
                    "terminal_exceeded_count": cohort.terminal_exceeded_count,
                    "active_within_count": cohort.active_within_count,
                    "active_exceeded_count": cohort.active_exceeded_count,
                    "state": cohort.state,
                    "is_final": cohort.is_final,
                    "input_fingerprint": cohort.input_fingerprint,
                }
                for index, cohort in enumerate(cohorts, start=1)
            ]
            for start in range(0, len(cohort_rows), _BATCH_SIZE):
                chunk = tuple(cohort_rows[start : start + _BATCH_SIZE])
                checkpoint, expected_revision = self._checkpoint_batch(
                    claim,
                    checkpoint=checkpoint,
                    expected_revision=expected_revision,
                    generation_token=generation_token,
                    batch_ordinal=batch_ordinal,
                    cohort_rows=chunk,
                )
                batch_ordinal += 1

            emitted_sections = self._sections.emit_rows(
                snapshot=domain_snapshot.connection,
                report_kind=attempt.period_type,
                report_request=report_request,
                as_of_utc=attempt.as_of_utc,
            )
            section_rows = [
                {
                    "report_section_snapshot_id": new_uuid4(),
                    "section_kind": row["section_kind"],
                    "schema_name": row["schema_name"],
                    "schema_version": row["schema_version"],
                    "section_ordinal": row["section_ordinal"],
                    "row_ordinal": row["row_ordinal"],
                    "canonical_row_key": row["canonical_row_key"],
                    "payload_json": canonical_json_bytes(row["payload"]).decode("utf-8"),
                    "payload_sha256": row["payload_sha256"],
                }
                for row in emitted_sections
            ]
            for start in range(0, len(section_rows), _BATCH_SIZE):
                chunk = tuple(section_rows[start : start + _BATCH_SIZE])
                checkpoint, expected_revision = self._checkpoint_batch(
                    claim,
                    checkpoint=checkpoint,
                    expected_revision=expected_revision,
                    generation_token=generation_token,
                    batch_ordinal=batch_ordinal,
                    section_rows=chunk,
                )
                batch_ordinal += 1

            # The original domain snapshot intentionally cannot see staging rows.
            # A second read is safe here because the hash function touches only
            # attempt-owned staging and immutable request metadata.
            with ReadSnapshot(self._factory) as staged_snapshot:
                members, _tiers, cohorts_count, sections_count = ReportRepository.counts(
                    staged_snapshot.connection,
                    report_attempt_id,
                )
                snapshot_hash = ReportRepository.snapshot_hash(
                    staged_snapshot.connection,
                    report_attempt_id,
                )

            seal_command_id = new_uuid4()
            seal_fingerprint = sha256_canonical_json(
                {
                    "schema": "SOMA_REPORT_SEAL_INTENT_V1",
                    "report_attempt_id": report_attempt_id,
                    "generation_token": generation_token,
                    "expected_attempt_revision": expected_revision,
                    "member_count": members,
                    "cohort_count": cohorts_count,
                    "section_count": sections_count,
                    "snapshot_hash": snapshot_hash,
                }
            )
            pending_seal = {
                **checkpoint,
                "attempt_revision": expected_revision,
                "next_batch_ordinal": batch_ordinal,
                "pending_command": self._pending(
                    kind="seal",
                    command_id=seal_command_id,
                    expected_revision=expected_revision,
                    request_fingerprint=seal_fingerprint,
                    snapshot_hash=snapshot_hash,
                ),
            }
            self._jobs.checkpoint(claim, pending_seal)
            sealed = self._worker.seal(
                command_id=seal_command_id,
                report_attempt_id=report_attempt_id,
                snapshot_generation_token=generation_token,
                expected_attempt_revision=expected_revision,
                final_member_count=members,
                final_cohort_count=cohorts_count,
                final_section_row_count=sections_count,
                snapshot_hash=snapshot_hash,
            )
            sealed_checkpoint = {
                "phase": "sealed",
                "attempt_revision": int(sealed["resulting_attempt_revision"]),
                "snapshot_generation_token": generation_token,
                "next_batch_ordinal": None,
                "pending_command": None,
                "candidate_filename": None,
                "published_artifact": None,
            }
            self._jobs.checkpoint(claim, sealed_checkpoint)

        return report_attempt_id


    def artifact_and_complete(self, claim: DurableJobClaim) -> str:
        if self._artifact is None:
            raise ValidationError("SLA report artifact adapter is not configured")
        payload = self._payload(claim)
        report_attempt_id = str(payload["report_attempt_id"])
        destination_token = str(payload["destination_request_token"])
        checkpoint = self._current_checkpoint(claim)
        if checkpoint["phase"] != "sealed" or checkpoint["pending_command"] is not None:
            raise IntegrityFailure("normal artifact completion requires a sealed report checkpoint")

        with ReadSnapshot(self._factory) as snapshot:
            attempt = ReportRepository.get_attempt(snapshot.connection, report_attempt_id)
            if (
                attempt is None
                or attempt.state != "ready_to_generate"
                or attempt.snapshot_hash is None
                or attempt.revision != int(checkpoint["attempt_revision"])
            ):
                raise IntegrityFailure("sealed report attempt is not ready for artifact generation")
            snapshot_hash = attempt.snapshot_hash
            expected_revision = attempt.revision

        generating_command_id = new_uuid4()
        generating_fingerprint = sha256_canonical_json(
            {
                "schema": "SOMA_REPORT_GENERATING_INTENT_V1",
                "report_attempt_id": report_attempt_id,
                "expected_attempt_revision": expected_revision,
                "snapshot_hash": snapshot_hash,
            }
        )
        pending_generating = {
            **checkpoint,
            "pending_command": self._pending(
                kind="mark_generating",
                command_id=generating_command_id,
                expected_revision=expected_revision,
                request_fingerprint=generating_fingerprint,
                snapshot_hash=snapshot_hash,
            ),
        }
        self._jobs.checkpoint(claim, pending_generating)
        generating = self._worker.mark_generating(
            command_id=generating_command_id,
            report_attempt_id=report_attempt_id,
            expected_attempt_revision=expected_revision,
            snapshot_hash=snapshot_hash,
        )
        expected_revision = int(generating["resulting_attempt_revision"])
        writing_checkpoint = {
            **pending_generating,
            "phase": "writing",
            "attempt_revision": expected_revision,
            "pending_command": None,
        }
        self._jobs.checkpoint(claim, writing_checkpoint)

        candidate = self._artifact.write_candidate(
            report_attempt_id=report_attempt_id,
            snapshot_hash=snapshot_hash,
            destination_request_token=destination_token,
        )
        verifying_command_id = new_uuid4()
        verifying_fingerprint = sha256_canonical_json(
            {
                "schema": "SOMA_REPORT_VERIFYING_INTENT_V1",
                "report_attempt_id": report_attempt_id,
                "expected_attempt_revision": expected_revision,
                "snapshot_hash": snapshot_hash,
                "candidate_filename": candidate,
            }
        )
        pending_verifying = {
            **writing_checkpoint,
            "candidate_filename": candidate,
            "pending_command": self._pending(
                kind="mark_verifying",
                command_id=verifying_command_id,
                expected_revision=expected_revision,
                request_fingerprint=verifying_fingerprint,
                snapshot_hash=snapshot_hash,
                candidate_filename=candidate,
            ),
        }
        self._jobs.checkpoint(claim, pending_verifying)
        verifying = self._worker.mark_verifying(
            command_id=verifying_command_id,
            report_attempt_id=report_attempt_id,
            expected_attempt_revision=expected_revision,
            snapshot_hash=snapshot_hash,
            candidate_filename=candidate,
        )
        expected_revision = int(verifying["resulting_attempt_revision"])
        verifying_checkpoint = {
            **pending_verifying,
            "phase": "verifying",
            "attempt_revision": expected_revision,
            "pending_command": None,
        }
        self._jobs.checkpoint(claim, verifying_checkpoint)

        verification = self._artifact.verify_candidate(
            report_attempt_id=report_attempt_id,
            snapshot_hash=snapshot_hash,
            destination_request_token=destination_token,
            candidate_filename=candidate,
        )
        publishing_checkpoint = {
            **verifying_checkpoint,
            "phase": "publishing",
        }
        self._jobs.checkpoint(claim, publishing_checkpoint)
        proof = self._artifact.publish_verified(
            verification=verification,
            destination_request_token=destination_token,
        )

        completion_command_id = new_uuid4()
        proof_fingerprint = sha256_canonical_json(proof)
        published_artifact = {
            "candidate_filename": str(proof["candidate_filename"]),
            "final_filename": str(proof["artifact_filename"]),
            "artifact_sha256": str(proof["artifact_sha256"]),
            "artifact_size_bytes": int(proof["artifact_size_bytes"]),
            "verified_at_utc": int(proof["verified_at_utc"]),
            "snapshot_hash": snapshot_hash,
            "completion_command_id": completion_command_id,
        }
        completion_fingerprint = sha256_canonical_json(
            {
                "schema": "SOMA_REPORT_COMPLETE_INTENT_V1",
                "report_attempt_id": report_attempt_id,
                "expected_attempt_revision": expected_revision,
                "snapshot_hash": snapshot_hash,
                "completion_proof_fingerprint": proof_fingerprint,
            }
        )
        completing_checkpoint = {
            **publishing_checkpoint,
            "phase": "completing",
            "published_artifact": published_artifact,
            "pending_command": self._pending(
                kind="complete",
                command_id=completion_command_id,
                expected_revision=expected_revision,
                request_fingerprint=completion_fingerprint,
                snapshot_hash=snapshot_hash,
                completion_proof_fingerprint=proof_fingerprint,
            ),
        }
        self._jobs.checkpoint(claim, completing_checkpoint)
        completed = self._worker.complete(
            command_id=completion_command_id,
            report_attempt_id=report_attempt_id,
            expected_attempt_revision=expected_revision,
            snapshot_hash=snapshot_hash,
            artifact_completion=proof,
        )
        terminal_checkpoint = {
            **completing_checkpoint,
            "phase": "terminal",
            "attempt_revision": int(completed["revision"]),
            "pending_command": None,
        }
        self._jobs.checkpoint(claim, terminal_checkpoint)
        self._jobs.complete(claim)
        return report_attempt_id

    def _report_attempt(self, report_attempt_id: str):
        with ReadSnapshot(self._factory) as snapshot:
            attempt = ReportRepository.get_attempt(
                snapshot.connection,
                report_attempt_id,
            )
        if attempt is None:
            raise IntegrityFailure("SLA report durable job owner disappeared")
        return attempt

    def _checkpoint_terminal(
        self,
        claim: DurableJobClaim,
        checkpoint: dict[str, Any] | None,
        *,
        attempt_revision: int,
    ) -> None:
        terminal = {
            "phase": "terminal",
            "attempt_revision": attempt_revision,
            "snapshot_generation_token": (
                None
                if checkpoint is None
                else checkpoint["snapshot_generation_token"]
            ),
            "next_batch_ordinal": None,
            "pending_command": None,
            "candidate_filename": (
                None if checkpoint is None else checkpoint["candidate_filename"]
            ),
            "published_artifact": (
                None if checkpoint is None else checkpoint["published_artifact"]
            ),
        }
        self._jobs.checkpoint(claim, terminal)

    def _fail_interrupted_snapshot(
        self,
        claim: DurableJobClaim,
        checkpoint: dict[str, Any] | None,
        *,
        report_attempt_id: str,
        expected_revision: int,
    ) -> str:
        command_id = new_uuid4()
        generation_token = (
            new_uuid4()
            if checkpoint is None
            else str(checkpoint["snapshot_generation_token"])
        )
        failure_code = "SLA_REPORT_SNAPSHOT_INTERRUPTED"
        request_fingerprint = sha256_canonical_json(
            {
                "schema": "SOMA_REPORT_INTERRUPTED_SNAPSHOT_FAIL_V1",
                "report_attempt_id": report_attempt_id,
                "expected_attempt_revision": expected_revision,
                "failure_code": failure_code,
            }
        )
        recovery_checkpoint = {
            "phase": "snapshotting",
            "attempt_revision": expected_revision,
            "snapshot_generation_token": generation_token,
            "next_batch_ordinal": (
                1 if checkpoint is None else checkpoint["next_batch_ordinal"]
            ),
            "pending_command": self._pending(
                kind="fail",
                command_id=command_id,
                expected_revision=expected_revision,
                request_fingerprint=request_fingerprint,
            ),
            "candidate_filename": None,
            "published_artifact": None,
        }
        self._jobs.checkpoint(claim, recovery_checkpoint)
        failed = self._worker.fail(
            command_id=command_id,
            report_attempt_id=report_attempt_id,
            expected_attempt_revision=expected_revision,
            failure_code=failure_code,
        )
        self._checkpoint_terminal(
            claim,
            recovery_checkpoint,
            attempt_revision=int(failed["revision"]),
        )
        self._jobs.fail(claim, failure_code, None)
        return report_attempt_id

    def _resume_committed_seal(
        self,
        claim: DurableJobClaim,
        checkpoint: dict[str, Any],
        *,
        report_attempt_id: str,
    ) -> bool:
        pending = checkpoint["pending_command"]
        attempt = self._report_attempt(report_attempt_id)
        if (
            attempt.state != "ready_to_generate"
            or attempt.snapshot_hash is None
            or not isinstance(pending, dict)
            or pending.get("kind") != "seal"
            or pending.get("snapshot_hash") != attempt.snapshot_hash
        ):
            return False
        sealed_checkpoint = {
            **checkpoint,
            "phase": "sealed",
            "attempt_revision": attempt.revision,
            "next_batch_ordinal": None,
            "pending_command": None,
            "candidate_filename": None,
            "published_artifact": None,
        }
        self._jobs.checkpoint(claim, sealed_checkpoint)
        return True

    def _resume_published_completion(
        self,
        claim: DurableJobClaim,
        checkpoint: dict[str, Any],
        *,
        report_attempt_id: str,
    ) -> str:
        attempt = self._report_attempt(report_attempt_id)
        pending = checkpoint["pending_command"]
        published = checkpoint["published_artifact"]
        if (
            attempt.state != "verifying"
            or attempt.snapshot_hash is None
            or not isinstance(pending, dict)
            or pending.get("kind") != "complete"
            or not isinstance(published, dict)
            or pending.get("command_id") != published.get("completion_command_id")
            or pending.get("snapshot_hash") != attempt.snapshot_hash
            or published.get("snapshot_hash") != attempt.snapshot_hash
            or int(pending.get("expected_attempt_revision", -1)) != attempt.revision
        ):
            raise IntegrityFailure(
                "published report completion checkpoint disagrees with authoritative attempt"
            )
        proof = {
            "report_attempt_id": report_attempt_id,
            "snapshot_hash": attempt.snapshot_hash,
            "candidate_filename": str(published["candidate_filename"]),
            "artifact_filename": str(published["final_filename"]),
            "artifact_sha256": str(published["artifact_sha256"]),
            "artifact_size_bytes": int(published["artifact_size_bytes"]),
            "verified_at_utc": int(published["verified_at_utc"]),
        }
        if (
            pending.get("completion_proof_fingerprint")
            != sha256_canonical_json(proof)
        ):
            raise IntegrityFailure(
                "published report completion proof fingerprint changed"
            )
        completed = self._worker.complete(
            command_id=str(pending["command_id"]),
            report_attempt_id=report_attempt_id,
            expected_attempt_revision=attempt.revision,
            snapshot_hash=attempt.snapshot_hash,
            artifact_completion=proof,
        )
        self._checkpoint_terminal(
            claim,
            checkpoint,
            attempt_revision=int(completed["revision"]),
        )
        self._jobs.complete(claim)
        return report_attempt_id

    def _require_artifact(self) -> SlaReportXlsxArtifact:
        if self._artifact is None:
            raise ValidationError("SLA report artifact adapter is not configured")
        return self._artifact

    def _fail_artifact_recovery(
        self,
        claim: DurableJobClaim,
        checkpoint: dict[str, Any],
        *,
        report_attempt_id: str,
        failure_code: str,
    ) -> str:
        attempt = self._report_attempt(report_attempt_id)
        command_id = new_uuid4()
        fingerprint = sha256_canonical_json(
            {
                "schema": "SOMA_REPORT_ARTIFACT_RECOVERY_FAIL_V1",
                "report_attempt_id": report_attempt_id,
                "expected_attempt_revision": attempt.revision,
                "failure_code": failure_code,
            }
        )
        pending = {
            **checkpoint,
            "attempt_revision": attempt.revision,
            "pending_command": self._pending(
                kind="fail",
                command_id=command_id,
                expected_revision=attempt.revision,
                request_fingerprint=fingerprint,
            ),
        }
        self._jobs.checkpoint(claim, pending)
        failed = self._worker.fail(
            command_id=command_id,
            report_attempt_id=report_attempt_id,
            expected_attempt_revision=attempt.revision,
            failure_code=failure_code,
        )
        self._checkpoint_terminal(
            claim,
            pending,
            attempt_revision=int(failed["revision"]),
        )
        self._jobs.fail(claim, failure_code, None)
        return report_attempt_id

    def _resume_sealed_phase(
        self,
        claim: DurableJobClaim,
        checkpoint: dict[str, Any],
        *,
        report_attempt_id: str,
    ) -> str:
        attempt = self._report_attempt(report_attempt_id)
        pending = checkpoint["pending_command"]
        if pending is None:
            if attempt.state != "ready_to_generate":
                raise IntegrityFailure(
                    "sealed report checkpoint disagrees with authoritative attempt"
                )
            return self.artifact_and_complete(claim)
        if not isinstance(pending, dict) or pending.get("kind") != "mark_generating":
            raise IntegrityFailure("sealed report has unsupported pending worker command")
        if (
            attempt.state not in {"ready_to_generate", "generating"}
            or attempt.snapshot_hash is None
            or pending.get("snapshot_hash") != attempt.snapshot_hash
        ):
            raise IntegrityFailure("pending generating transition disagrees with report state")
        generating = self._worker.mark_generating(
            command_id=str(pending["command_id"]),
            report_attempt_id=report_attempt_id,
            expected_attempt_revision=int(pending["expected_attempt_revision"]),
            snapshot_hash=attempt.snapshot_hash,
        )
        writing = {
            **checkpoint,
            "phase": "writing",
            "attempt_revision": int(generating["resulting_attempt_revision"]),
            "pending_command": None,
        }
        self._jobs.checkpoint(claim, writing)
        return self._resume_writing_phase(
            claim,
            writing,
            report_attempt_id=report_attempt_id,
        )

    def _resume_writing_phase(
        self,
        claim: DurableJobClaim,
        checkpoint: dict[str, Any],
        *,
        report_attempt_id: str,
    ) -> str:
        artifact = self._require_artifact()
        payload = self._payload(claim)
        destination_token = str(payload["destination_request_token"])
        attempt = self._report_attempt(report_attempt_id)
        if attempt.snapshot_hash is None:
            raise IntegrityFailure("writing report lost sealed snapshot identity")
        snapshot_hash = attempt.snapshot_hash
        pending = checkpoint["pending_command"]

        if isinstance(pending, dict):
            if pending.get("kind") != "mark_verifying":
                raise IntegrityFailure("writing report has unsupported pending command")
            candidate = str(pending["candidate_filename"])
            if attempt.state == "generating":
                if not artifact.candidate_exists(
                    destination_request_token=destination_token,
                    candidate_filename=candidate,
                ):
                    artifact.recover_candidate(
                        report_attempt_id=report_attempt_id,
                        snapshot_hash=snapshot_hash,
                        destination_request_token=destination_token,
                        candidate_filename=candidate,
                    )
            elif attempt.state != "verifying":
                raise IntegrityFailure(
                    "pending verifying transition disagrees with report state"
                )
            verifying = self._worker.mark_verifying(
                command_id=str(pending["command_id"]),
                report_attempt_id=report_attempt_id,
                expected_attempt_revision=int(pending["expected_attempt_revision"]),
                snapshot_hash=str(pending["snapshot_hash"]),
                candidate_filename=candidate,
            )
        else:
            if attempt.state != "generating":
                raise IntegrityFailure(
                    "writing checkpoint disagrees with authoritative report state"
                )
            candidate = artifact.recover_candidate(
                report_attempt_id=report_attempt_id,
                snapshot_hash=snapshot_hash,
                destination_request_token=destination_token,
            )
            command_id = new_uuid4()
            request_fingerprint = sha256_canonical_json(
                {
                    "schema": "SOMA_REPORT_VERIFYING_RECOVERY_INTENT_V1",
                    "report_attempt_id": report_attempt_id,
                    "expected_attempt_revision": attempt.revision,
                    "snapshot_hash": snapshot_hash,
                    "candidate_filename": candidate,
                }
            )
            pending_checkpoint = {
                **checkpoint,
                "candidate_filename": candidate,
                "pending_command": self._pending(
                    kind="mark_verifying",
                    command_id=command_id,
                    expected_revision=attempt.revision,
                    request_fingerprint=request_fingerprint,
                    snapshot_hash=snapshot_hash,
                    candidate_filename=candidate,
                ),
            }
            self._jobs.checkpoint(claim, pending_checkpoint)
            verifying = self._worker.mark_verifying(
                command_id=command_id,
                report_attempt_id=report_attempt_id,
                expected_attempt_revision=attempt.revision,
                snapshot_hash=snapshot_hash,
                candidate_filename=candidate,
            )
            checkpoint = pending_checkpoint

        verifying_checkpoint = {
            **checkpoint,
            "phase": "verifying",
            "attempt_revision": int(verifying["resulting_attempt_revision"]),
            "candidate_filename": candidate,
            "pending_command": None,
        }
        self._jobs.checkpoint(claim, verifying_checkpoint)
        return self._resume_verifying_phase(
            claim,
            verifying_checkpoint,
            report_attempt_id=report_attempt_id,
        )

    def _publish_verified_recovery(
        self,
        claim: DurableJobClaim,
        checkpoint: dict[str, Any],
        *,
        report_attempt_id: str,
        verification: Any,
    ) -> str:
        artifact = self._require_artifact()
        destination_token = str(self._payload(claim)["destination_request_token"])
        attempt = self._report_attempt(report_attempt_id)
        if attempt.state != "verifying" or attempt.snapshot_hash is None:
            raise IntegrityFailure(
                "verified recovery result no longer matches report state"
            )
        snapshot_hash = attempt.snapshot_hash
        publishing_checkpoint = {
            **checkpoint,
            "phase": "publishing",
            "attempt_revision": attempt.revision,
            "candidate_filename": verification.candidate_filename,
            "pending_command": None,
        }
        self._jobs.checkpoint(claim, publishing_checkpoint)
        proof = artifact.publish_verified(
            verification=verification,
            destination_request_token=destination_token,
        )

        completion_command_id = new_uuid4()
        proof_fingerprint = sha256_canonical_json(proof)
        published_artifact = {
            "candidate_filename": str(proof["candidate_filename"]),
            "final_filename": str(proof["artifact_filename"]),
            "artifact_sha256": str(proof["artifact_sha256"]),
            "artifact_size_bytes": int(proof["artifact_size_bytes"]),
            "verified_at_utc": int(proof["verified_at_utc"]),
            "snapshot_hash": snapshot_hash,
            "completion_command_id": completion_command_id,
        }
        completion_fingerprint = sha256_canonical_json(
            {
                "schema": "SOMA_REPORT_COMPLETE_RECOVERY_INTENT_V1",
                "report_attempt_id": report_attempt_id,
                "expected_attempt_revision": attempt.revision,
                "snapshot_hash": snapshot_hash,
                "completion_proof_fingerprint": proof_fingerprint,
            }
        )
        completing_checkpoint = {
            **publishing_checkpoint,
            "phase": "completing",
            "published_artifact": published_artifact,
            "pending_command": self._pending(
                kind="complete",
                command_id=completion_command_id,
                expected_revision=attempt.revision,
                request_fingerprint=completion_fingerprint,
                snapshot_hash=snapshot_hash,
                completion_proof_fingerprint=proof_fingerprint,
            ),
        }
        self._jobs.checkpoint(claim, completing_checkpoint)
        completed = self._worker.complete(
            command_id=completion_command_id,
            report_attempt_id=report_attempt_id,
            expected_attempt_revision=attempt.revision,
            snapshot_hash=snapshot_hash,
            artifact_completion=proof,
        )
        self._checkpoint_terminal(
            claim,
            completing_checkpoint,
            attempt_revision=int(completed["revision"]),
        )
        self._jobs.complete(claim)
        return report_attempt_id

    def _resume_verifying_phase(
        self,
        claim: DurableJobClaim,
        checkpoint: dict[str, Any],
        *,
        report_attempt_id: str,
    ) -> str:
        artifact = self._require_artifact()
        payload = self._payload(claim)
        destination_token = str(payload["destination_request_token"])
        attempt = self._report_attempt(report_attempt_id)
        candidate = checkpoint["candidate_filename"]
        if (
            attempt.state != "verifying"
            or attempt.snapshot_hash is None
            or not isinstance(candidate, str)
            or attempt.artifact_filename != candidate
        ):
            raise IntegrityFailure(
                "verifying checkpoint disagrees with authoritative report candidate"
            )
        try:
            verification = artifact.verify_candidate(
                report_attempt_id=report_attempt_id,
                snapshot_hash=attempt.snapshot_hash,
                destination_request_token=destination_token,
                candidate_filename=candidate,
            )
        except SomaError:
            artifact.recover_candidate(
                report_attempt_id=report_attempt_id,
                snapshot_hash=attempt.snapshot_hash,
                destination_request_token=destination_token,
                candidate_filename=candidate,
            )
            verification = artifact.verify_candidate(
                report_attempt_id=report_attempt_id,
                snapshot_hash=attempt.snapshot_hash,
                destination_request_token=destination_token,
                candidate_filename=candidate,
            )
        return self._publish_verified_recovery(
            claim,
            checkpoint,
            report_attempt_id=report_attempt_id,
            verification=verification,
        )

    def _resume_publishing_phase(
        self,
        claim: DurableJobClaim,
        checkpoint: dict[str, Any],
        *,
        report_attempt_id: str,
    ) -> str:
        artifact = self._require_artifact()
        destination_token = str(self._payload(claim)["destination_request_token"])
        attempt = self._report_attempt(report_attempt_id)
        candidate = checkpoint["candidate_filename"]
        if (
            attempt.state != "verifying"
            or attempt.snapshot_hash is None
            or not isinstance(candidate, str)
            or attempt.artifact_filename != candidate
        ):
            raise IntegrityFailure(
                "publishing checkpoint disagrees with authoritative report candidate"
            )
        if isinstance(checkpoint["published_artifact"], dict):
            return self._resume_published_completion(
                claim,
                checkpoint,
                report_attempt_id=report_attempt_id,
            )
        if not artifact.candidate_exists(
            destination_request_token=destination_token,
            candidate_filename=candidate,
        ):
            return self._fail_artifact_recovery(
                claim,
                checkpoint,
                report_attempt_id=report_attempt_id,
                failure_code="SLA_REPORT_PUBLICATION_PROOF_LOST",
            )
        try:
            verification = artifact.verify_candidate(
                report_attempt_id=report_attempt_id,
                snapshot_hash=attempt.snapshot_hash,
                destination_request_token=destination_token,
                candidate_filename=candidate,
            )
        except SomaError:
            artifact.recover_candidate(
                report_attempt_id=report_attempt_id,
                snapshot_hash=attempt.snapshot_hash,
                destination_request_token=destination_token,
                candidate_filename=candidate,
            )
            verification = artifact.verify_candidate(
                report_attempt_id=report_attempt_id,
                snapshot_hash=attempt.snapshot_hash,
                destination_request_token=destination_token,
                candidate_filename=candidate,
            )
        return self._publish_verified_recovery(
            claim,
            checkpoint,
            report_attempt_id=report_attempt_id,
            verification=verification,
        )

    def run_to_completion(self, claim: DurableJobClaim) -> str:
        payload = self._payload(claim)
        report_attempt_id = str(payload["report_attempt_id"])
        checkpoint = self._existing_checkpoint(claim)
        attempt = self._report_attempt(report_attempt_id)

        # Domain authority wins over an interrupted technical checkpoint.
        if attempt.state == "completed":
            self._checkpoint_terminal(
                claim,
                checkpoint,
                attempt_revision=attempt.revision,
            )
            self._jobs.complete(claim)
            return report_attempt_id
        if attempt.state == "failed":
            if attempt.failure_code is None:
                raise IntegrityFailure("failed report attempt lacks failure code")
            self._checkpoint_terminal(
                claim,
                checkpoint,
                attempt_revision=attempt.revision,
            )
            self._jobs.fail(claim, "SLA_REPORT_DOMAIN_FAILED", None)
            return report_attempt_id
        if attempt.state == "cancelled":
            raise IntegrityFailure(
                "cancelled report unexpectedly retained an active durable claim"
            )

        if checkpoint is None:
            if claim.attempt_ordinal == 1:
                self.snapshot_and_seal(claim)
                return self.artifact_and_complete(claim)
            if attempt.state == "staging":
                return self._fail_interrupted_snapshot(
                    claim,
                    None,
                    report_attempt_id=report_attempt_id,
                    expected_revision=attempt.revision,
                )
            raise IntegrityFailure(
                "recovered report without checkpoint has incompatible domain state"
            )

        phase = str(checkpoint["phase"])
        if phase == "snapshotting":
            if self._resume_committed_seal(
                claim,
                checkpoint,
                report_attempt_id=report_attempt_id,
            ):
                return self.artifact_and_complete(claim)
            attempt = self._report_attempt(report_attempt_id)
            if attempt.state == "staging":
                return self._fail_interrupted_snapshot(
                    claim,
                    checkpoint,
                    report_attempt_id=report_attempt_id,
                    expected_revision=attempt.revision,
                )
            raise IntegrityFailure(
                "interrupted report snapshot checkpoint has incompatible domain state"
            )
        if phase == "sealed":
            return self._resume_sealed_phase(
                claim,
                checkpoint,
                report_attempt_id=report_attempt_id,
            )
        if phase == "writing":
            return self._resume_writing_phase(
                claim,
                checkpoint,
                report_attempt_id=report_attempt_id,
            )
        if phase == "verifying":
            return self._resume_verifying_phase(
                claim,
                checkpoint,
                report_attempt_id=report_attempt_id,
            )
        if phase == "publishing":
            return self._resume_publishing_phase(
                claim,
                checkpoint,
                report_attempt_id=report_attempt_id,
            )
        if phase == "completing":
            return self._resume_published_completion(
                claim,
                checkpoint,
                report_attempt_id=report_attempt_id,
            )
        if phase == "terminal":
            raise IntegrityFailure(
                "terminal report checkpoint disagrees with nonterminal domain state"
            )
        raise IntegrityFailure(
            f"report recovery for phase {phase!r} is not yet safely implemented"
        )



def run_snapshot(
    claim: DurableJobClaim,
    connection_factory: ConnectionFactory,
    section_registry: ReportSectionContributorRegistry | None = None,
) -> str:
    return SlaReportGenerationWorker(
        connection_factory,
        section_registry,
    ).snapshot_and_seal(claim)


def run_to_completion(
    claim: DurableJobClaim,
    connection_factory: ConnectionFactory,
    artifact: SlaReportXlsxArtifact,
    section_registry: ReportSectionContributorRegistry | None = None,
) -> str:
    return SlaReportGenerationWorker(
        connection_factory,
        section_registry,
        artifact,
    ).run_to_completion(claim)


__all__ = ["SlaReportGenerationWorker", "run_snapshot", "run_to_completion"]
