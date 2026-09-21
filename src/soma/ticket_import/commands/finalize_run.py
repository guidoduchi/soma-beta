from __future__ import annotations

import hmac
import re
from dataclasses import dataclass

from soma.foundation.application.command_boundary import (
    CommandBoundary,
    CommandEnvelope,
    CommandExecutionResult,
    PreparedMutation,
)
from soma.foundation.audit.writer import AuditEventInput, AuditResultRef, AuditWriter
from soma.foundation.errors import IntegrityFailure, PersistenceFailure, SomaError, ValidationError
from soma.foundation.identifiers import new_uuid4, require_uuid4, utc_epoch_seconds
from soma.foundation.jobs import DurableJobCoordinator, JobTypeRegistry
from soma.foundation.persistence.connections import ConnectionFactory
from soma.foundation.persistence.uow import UnitOfWork

from ..audit_registry import build_ticket_import_audit_registry
from ..jobs import (
    SR_REAPPEARANCE_JOB_TYPE,
    TICKET_IMPORT_JOB_CONTRACTS,
    derive_reappearance_dedupe_key,
)
from ..repositories.proposals import ProposalRepository
from ..repositories.runs import ImportRunRepository, SourceCheckpointRepository, SourceCheckpointState


_HEX64_RE = re.compile(r"[0-9a-f]{64}\Z")
_CHRONOLOGY_KINDS = frozenset({"filesystem_mtime_ns", "embedded_filename_timestamp_utc"})
_SOURCE_FAMILIES = frozenset({"advanced_search_sr", "rfc_enhanced", "wfm_service_provider"})


@dataclass(frozen=True, slots=True)
class CheckpointAdvanceResult:
    import_run_id: str
    source_family: str
    run_state: str
    run_revision: int
    checkpoint_revision: int
    replayed: bool
    no_change: bool


@dataclass(frozen=True, slots=True)
class ImportRunFinalizeResult:
    import_run_id: str
    state: str
    revision: int
    checkpoint: dict[str, object]
    replayed: bool


class ImportRunFinalizationService:
    def __init__(self, connection_factory: ConnectionFactory) -> None:
        self._factory = connection_factory
        self._runs = ImportRunRepository()
        self._proposals = ProposalRepository()
        self._checkpoints = SourceCheckpointRepository()
        self._jobs = DurableJobCoordinator(
            connection_factory,
            JobTypeRegistry(TICKET_IMPORT_JOB_CONTRACTS),
        )
        self._boundary = CommandBoundary(
            connection_factory,
            AuditWriter(build_ticket_import_audit_registry()),
        )

    @staticmethod
    def _checkpoint_summary(checkpoint: SourceCheckpointState) -> dict[str, object]:
        return {
            "source_family": checkpoint.source_family,
            "chronology_kind": checkpoint.chronology_kind,
            "chronology_value": checkpoint.chronology_value,
            "logical_fingerprint": checkpoint.logical_fingerprint,
            "import_run_id": checkpoint.accepted_import_run_id,
            "revision": checkpoint.revision,
        }

    def _checkpoint_response(self, uow: UnitOfWork, import_run_id: str) -> dict[str, object]:
        run = self._runs.get_checkpoint_transition_run(uow.connection, import_run_id)
        if run is None:
            raise PersistenceFailure("checkpoint advancement response run disappeared before commit")
        checkpoint = self._checkpoints.get(uow.connection, run.source_family)
        if checkpoint is None:
            raise PersistenceFailure("checkpoint advancement response checkpoint disappeared before commit")
        return {
            "import_run_id": import_run_id,
            "source_family": run.source_family,
            "run_state": run.run_state,
            "run_revision": run.revision,
            "checkpoint_revision": checkpoint.revision,
        }

    @classmethod
    def _finalize_result(cls, execution: CommandExecutionResult) -> ImportRunFinalizeResult:
        if execution.response_schema != "ImportRunFinalizeResultV1" or execution.response_version != 1:
            raise IntegrityFailure("import run finalization result schema/version is invalid")
        value = execution.response
        if not isinstance(value, dict) or set(value) != {"import_run_id", "state", "revision", "checkpoint"}:
            raise IntegrityFailure("import run finalization result shape is invalid")
        if value["state"] not in {"accepted", "rejected", "partially_accepted"}:
            raise IntegrityFailure("import run finalization result state is invalid")
        if type(value["revision"]) is not int or value["revision"] < 1:
            raise IntegrityFailure("import run finalization result revision is invalid")
        checkpoint = value["checkpoint"]
        if not isinstance(checkpoint, dict) or set(checkpoint) != {
            "source_family",
            "chronology_kind",
            "chronology_value",
            "logical_fingerprint",
            "import_run_id",
            "revision",
        }:
            raise IntegrityFailure("import run finalization checkpoint shape is invalid")
        if checkpoint["source_family"] not in _SOURCE_FAMILIES:
            raise IntegrityFailure("import run finalization checkpoint source family is invalid")
        if checkpoint["chronology_kind"] not in _CHRONOLOGY_KINDS:
            raise IntegrityFailure("import run finalization checkpoint chronology kind is invalid")
        if type(checkpoint["chronology_value"]) is not int or checkpoint["chronology_value"] < 0:
            raise IntegrityFailure("import run finalization checkpoint chronology value is invalid")
        logical_fingerprint = checkpoint["logical_fingerprint"]
        if not isinstance(logical_fingerprint, str) or _HEX64_RE.fullmatch(logical_fingerprint) is None:
            raise IntegrityFailure("import run finalization checkpoint fingerprint is invalid")
        if type(checkpoint["revision"]) is not int or checkpoint["revision"] < 1:
            raise IntegrityFailure("import run finalization checkpoint revision is invalid")
        checkpoint_run_id = require_uuid4(str(checkpoint["import_run_id"]))
        checkpoint_response = dict(checkpoint)
        checkpoint_response["import_run_id"] = checkpoint_run_id
        return ImportRunFinalizeResult(
            import_run_id=require_uuid4(str(value["import_run_id"])),
            state=str(value["state"]),
            revision=int(value["revision"]),
            checkpoint=checkpoint_response,
            replayed=execution.replayed,
        )

    def finalize_run(
        self,
        *,
        command_id: str,
        import_run_id: str,
        expected_run_revision: int,
        actor_kind: str = "local_user",
        actor_id: str | None = None,
    ) -> ImportRunFinalizeResult:
        canonical_run_id = require_uuid4(import_run_id)
        if type(expected_run_revision) is not int or expected_run_revision < 1:
            raise ValidationError("expected_run_revision must be a positive integer")
        envelope = CommandEnvelope(
            command_id=command_id,
            command_type="FinalizeImportRunReview",
            target_type="import_run",
            target_id=canonical_run_id,
            semantic_payload={"import_run_id": canonical_run_id},
            base_revisions={"import_run": expected_run_revision},
        )

        def response_factory(uow: UnitOfWork) -> dict[str, object]:
            row = uow.connection.execute(
                "SELECT source_family,run_state,revision FROM import_runs WHERE import_run_id=?",
                (canonical_run_id,),
            ).fetchone()
            if row is None:
                raise PersistenceFailure("finalized import run response authority disappeared")
            checkpoint = self._checkpoints.get(uow.connection, str(row[0]))
            if checkpoint is None:
                raise PersistenceFailure("finalized import run checkpoint response authority disappeared")
            return {
                "import_run_id": canonical_run_id,
                "state": str(row[1]),
                "revision": int(row[2]),
                "checkpoint": self._checkpoint_summary(checkpoint),
            }

        def prepare(uow: UnitOfWork) -> PreparedMutation:
            run = self._runs.get_checkpoint_transition_run(uow.connection, canonical_run_id)
            if run is None:
                raise SomaError("IMPORT_RUN_NOT_FOUND", "import run does not exist")
            if run.revision != expected_run_revision:
                raise SomaError("IMPORT_RUN_STALE", "import run revision changed")
            if run.run_state not in {"staged", "waiting_review", "recovery_required"}:
                raise SomaError("IMPORT_RUN_STALE", "import run is not review-finalizable")

            counters = self._runs.derive_publication_counters(uow.connection, canonical_run_id)
            stored = uow.connection.execute(
                "SELECT observed_row_count,valid_identity_count,invalid_row_count,warning_count,"
                "proposal_count,pending_proposal_count,accepted_proposal_count,rejected_proposal_count,"
                "deferred_proposal_count FROM import_runs WHERE import_run_id=?",
                (canonical_run_id,),
            ).fetchone()
            if stored is None or tuple(int(item) for item in stored) != (
                counters.observed_row_count,
                counters.valid_identity_count,
                counters.invalid_row_count,
                counters.warning_count,
                counters.proposal_count,
                counters.pending_proposal_count,
                counters.accepted_proposal_count,
                counters.rejected_proposal_count,
                counters.deferred_proposal_count,
            ):
                raise IntegrityFailure("import run stored counters disagree with exact evidence")
            if counters.pending_proposal_count != 0:
                raise SomaError("IMPORT_PENDING_PROPOSALS", "import run still has pending proposals")
            if counters.accepted_proposal_count == 0 and counters.proposal_count > 0:
                final_state = "rejected"
            elif counters.rejected_proposal_count or counters.deferred_proposal_count:
                final_state = "partially_accepted"
            else:
                final_state = "accepted"

            checkpoint = self._checkpoints.get(uow.connection, run.source_family)
            expected_checkpoint_revision = None if checkpoint is None else checkpoint.revision
            now = utc_epoch_seconds()
            audit_event_id = new_uuid4()

            if run.run_state == "recovery_required":
                if checkpoint is None:
                    raise SomaError(
                        "IMPORT_RECOVERY_REVIEW_STALE",
                        "recovery run no longer has a source checkpoint",
                    )
                decision_run = self._proposals.get_run(uow.connection, canonical_run_id)
                review_fingerprint = self._proposals.recovery_review_fingerprint(uow.connection, decision_run)
                review = uow.connection.execute(
                    "SELECT decision,reason_category,checkpoint_revision,review_fingerprint_sha256 "
                    "FROM import_recovery_reviews WHERE import_run_id=? ORDER BY review_ordinal DESC LIMIT 1",
                    (canonical_run_id,),
                ).fetchone()
                if (
                    review is None
                    or str(review[0]) != "authorized"
                    or str(review[3]) != review_fingerprint
                    or int(review[2]) != checkpoint.revision
                ):
                    raise SomaError(
                        "IMPORT_RECOVERY_AUTHORIZATION_REQUIRED",
                        "recovery finalization requires the latest exact authorization",
                    )
                recovery_event_id = new_uuid4()

                def apply(inner: UnitOfWork) -> AuditEventInput:
                    prior, checkpoint_revision, replaced = self._checkpoints.finalize_authorized_recovery(
                        inner,
                        run=run,
                        expected_checkpoint_revision=checkpoint.revision,
                        checked_at_utc=now,
                    )
                    changed = inner.connection.execute(
                        "UPDATE import_runs SET run_state=?,completed_at_utc=?,revision=revision+1 "
                        "WHERE import_run_id=? AND revision=? AND run_state='recovery_required' "
                        "AND pending_proposal_count=0",
                        (final_state, now, canonical_run_id, expected_run_revision),
                    )
                    if changed.rowcount != 1:
                        raise SomaError("IMPORT_RECOVERY_REVIEW_STALE", "recovery run changed before finalization")
                    inner.connection.execute(
                        "INSERT INTO import_recovery_events(import_recovery_event_id,source_family,import_run_id,"
                        "prior_checkpoint_run_id,recovery_reason_category,review_fingerprint_sha256,"
                        "occurred_at_utc,command_id) VALUES (?,?,?,?,?,?,?,?)",
                        (
                            recovery_event_id,
                            run.source_family,
                            canonical_run_id,
                            prior.accepted_import_run_id,
                            str(review[1]),
                            review_fingerprint,
                            now,
                            command_id,
                        ),
                    )
                    refs = [
                        AuditResultRef("import_run", canonical_run_id),
                        AuditResultRef("import_recovery_event", recovery_event_id),
                        AuditResultRef("import_source_checkpoint", run.source_family),
                    ]
                    if replaced and run.source_family == "advanced_search_sr":
                        payload = {
                            "import_run_id": canonical_run_id,
                            "source_family": "advanced_search_sr",
                            "published_run_revision": expected_run_revision + 1,
                            "requested_by_command_id": command_id,
                        }
                        job_id = self._jobs.enqueue_or_coalesce(
                            inner,
                            SR_REAPPEARANCE_JOB_TYPE,
                            1,
                            payload,
                            derive_reappearance_dedupe_key(payload),
                        )
                        refs.append(AuditResultRef("durable_job", job_id))
                    return AuditEventInput(
                        audit_event_id=audit_event_id,
                        action_type="ticket_import.run_finalized",
                        action_version=1,
                        actor_kind=actor_kind,
                        actor_id=actor_id,
                        target_type="import_run",
                        target_id=canonical_run_id,
                        command_id=command_id,
                        import_run_id=canonical_run_id,
                        payload_schema="ImportRunFinalizedAuditV1",
                        payload_version=1,
                        payload={
                            "import_run_id": canonical_run_id,
                            "final_state": final_state,
                            "revision": expected_run_revision + 1,
                            "checkpoint_revision": checkpoint_revision,
                            "accepted_count": counters.accepted_proposal_count,
                            "rejected_count": counters.rejected_proposal_count,
                            "deferred_count": counters.deferred_proposal_count,
                        },
                        resulting_event_refs=tuple(refs),
                    )

            else:

                def apply(inner: UnitOfWork) -> AuditEventInput:
                    checkpoint_revision = self._checkpoints.establish_or_advance_finalized(
                        inner,
                        run=run,
                        expected_checkpoint_revision=expected_checkpoint_revision,
                        checked_at_utc=now,
                    )
                    changed = inner.connection.execute(
                        "UPDATE import_runs SET run_state=?,completed_at_utc=?,revision=revision+1 "
                        "WHERE import_run_id=? AND revision=? AND run_state IN ('staged','waiting_review') "
                        "AND pending_proposal_count=0",
                        (final_state, now, canonical_run_id, expected_run_revision),
                    )
                    if changed.rowcount != 1:
                        raise SomaError("IMPORT_RUN_STALE", "import run changed before finalization")
                    return AuditEventInput(
                        audit_event_id=audit_event_id,
                        action_type="ticket_import.run_finalized",
                        action_version=1,
                        actor_kind=actor_kind,
                        actor_id=actor_id,
                        target_type="import_run",
                        target_id=canonical_run_id,
                        command_id=command_id,
                        import_run_id=canonical_run_id,
                        payload_schema="ImportRunFinalizedAuditV1",
                        payload_version=1,
                        payload={
                            "import_run_id": canonical_run_id,
                            "final_state": final_state,
                            "revision": expected_run_revision + 1,
                            "checkpoint_revision": checkpoint_revision,
                            "accepted_count": counters.accepted_proposal_count,
                            "rejected_count": counters.rejected_proposal_count,
                            "deferred_count": counters.deferred_proposal_count,
                        },
                        resulting_event_refs=(
                            AuditResultRef("import_run", canonical_run_id),
                            AuditResultRef("import_source_checkpoint", run.source_family),
                        ),
                    )

            return PreparedMutation(
                False,
                "import_run",
                canonical_run_id,
                apply,
                response_schema="ImportRunFinalizeResultV1",
                response_factory=response_factory,
            )

        return self._finalize_result(self._boundary.execute(envelope, prepare))

    @staticmethod
    def _result_from_execution(execution: CommandExecutionResult) -> CheckpointAdvanceResult:
        if execution.response_schema != "CheckpointAdvanceResultV1" or execution.response_version != 1:
            raise IntegrityFailure("checkpoint advancement result schema/version is invalid")
        response = execution.response
        if not isinstance(response, dict):
            raise IntegrityFailure("checkpoint advancement result payload is invalid")
        import_run_id = response.get("import_run_id")
        source_family = response.get("source_family")
        run_state = response.get("run_state")
        run_revision = response.get("run_revision")
        checkpoint_revision = response.get("checkpoint_revision")
        if (
            not isinstance(import_run_id, str)
            or not import_run_id
            or not isinstance(source_family, str)
            or not source_family
            or not isinstance(run_state, str)
            or not run_state
            or type(run_revision) is not int
            or run_revision <= 0
            or type(checkpoint_revision) is not int
            or checkpoint_revision <= 0
        ):
            raise IntegrityFailure("checkpoint advancement result fields are invalid")
        return CheckpointAdvanceResult(
            import_run_id=import_run_id,
            source_family=source_family,
            run_state=run_state,
            run_revision=run_revision,
            checkpoint_revision=checkpoint_revision,
            replayed=execution.replayed,
            no_change=execution.no_change,
        )

    def record_newer_identical_source_check(
        self,
        *,
        command_id: str,
        job_id: str,
        import_run_id: str,
        expected_run_revision: int,
        expected_checkpoint_revision: int,
        chronology_kind: str,
        chronology_value: int,
        logical_fingerprint: str,
        actor_kind: str = "system",
        actor_id: str | None = None,
    ) -> CheckpointAdvanceResult:
        require_uuid4(job_id)
        require_uuid4(import_run_id)
        if type(expected_run_revision) is not int or expected_run_revision <= 0:
            raise ValidationError("expected_run_revision must be a positive integer")
        if type(expected_checkpoint_revision) is not int or expected_checkpoint_revision <= 0:
            raise ValidationError("expected_checkpoint_revision must be a positive integer")
        if chronology_kind not in _CHRONOLOGY_KINDS:
            raise ValidationError("chronology_kind is not registered")
        if type(chronology_value) is not int or chronology_value < 0:
            raise ValidationError("chronology_value must be a non-negative integer")
        if not isinstance(logical_fingerprint, str) or _HEX64_RE.fullmatch(logical_fingerprint) is None:
            raise ValidationError("logical_fingerprint must be lowercase SHA-256 hex")

        envelope = CommandEnvelope(
            command_id=command_id,
            command_type="RecordNewerIdenticalSourceCheck",
            target_type="import_run",
            target_id=import_run_id,
            semantic_payload={
                "job_id": job_id,
                "chronology_kind": chronology_kind,
                "chronology_value": chronology_value,
                "logical_fingerprint": logical_fingerprint,
            },
            base_revisions={
                "import_run": expected_run_revision,
                "source_checkpoint": expected_checkpoint_revision,
            },
            authorizing_fingerprints={"logical_fingerprint": logical_fingerprint},
        )

        def response_factory(inner: UnitOfWork) -> dict[str, object]:
            return self._checkpoint_response(inner, import_run_id)

        def prepare(uow: UnitOfWork) -> PreparedMutation:
            run = self._runs.get_checkpoint_transition_run(uow.connection, import_run_id)
            if run is None:
                raise SomaError("IMPORT_RUN_STALE", "import run does not exist")
            checkpoint = self._checkpoints.get(uow.connection, run.source_family)
            if checkpoint is None:
                raise SomaError("IMPORT_CHECKPOINT_STALE", "source checkpoint does not exist")

            if run.revision != expected_run_revision:
                raise SomaError("IMPORT_RUN_STALE", "import run revision changed")
            if checkpoint.revision != expected_checkpoint_revision:
                raise SomaError("IMPORT_CHECKPOINT_STALE", "source checkpoint revision changed")
            if (
                run.chronology_kind != chronology_kind
                or run.chronology_value != chronology_value
                or not hmac.compare_digest(run.logical_fingerprint, logical_fingerprint)
            ):
                raise SomaError("IMPORT_RUN_STALE", "import run chronology or fingerprint changed")

            if run.run_state == "noop":
                if (
                    checkpoint.accepted_import_run_id == run.import_run_id
                    and checkpoint.source_profile_id == run.source_profile_id
                    and checkpoint.chronology_kind == run.chronology_kind
                    and checkpoint.chronology_value == run.chronology_value
                    and hmac.compare_digest(checkpoint.logical_fingerprint, run.logical_fingerprint)
                ):
                    return PreparedMutation(
                        True,
                        None,
                        None,
                        response_schema="CheckpointAdvanceResultV1",
                        response_factory=response_factory,
                    )
                raise SomaError("IMPORT_RUN_STALE", "noop run does not match the current source checkpoint")

            if run.run_state != "noop_pending_checkpoint":
                raise SomaError("IMPORT_RUN_STALE", "import run is not waiting for checkpoint advancement")
            if run.source_profile_id != checkpoint.source_profile_id:
                raise SomaError("IMPORT_CHECKPOINT_STALE", "source profile differs from current checkpoint")
            if run.chronology_kind != checkpoint.chronology_kind:
                raise SomaError("IMPORT_CHECKPOINT_STALE", "source chronology kind differs from current checkpoint")
            if run.chronology_value <= checkpoint.chronology_value:
                raise SomaError("IMPORT_CHECKPOINT_STALE", "newer-identical source chronology is not newer")
            if not hmac.compare_digest(run.logical_fingerprint, checkpoint.logical_fingerprint):
                raise SomaError("IMPORT_CHECKPOINT_STALE", "newer-identical source fingerprint differs from checkpoint")
            if run.proposal_count != 0 or run.pending_proposal_count != 0:
                raise SomaError("IMPORT_RUN_STALE", "newer-identical run unexpectedly contains proposals")
            if self._runs.has_published_row_authority(uow.connection, import_run_id):
                raise SomaError("IMPORT_RUN_STALE", "newer-identical run unexpectedly contains published row authority")

            now = utc_epoch_seconds()
            audit_event_id = new_uuid4()

            def apply(inner: UnitOfWork) -> AuditEventInput:
                self._checkpoints.advance_newer_identical(
                    inner,
                    checkpoint=checkpoint,
                    run=run,
                    expected_revision=expected_checkpoint_revision,
                    checked_at_utc=now,
                )
                self._runs.mark_noop(
                    inner,
                    import_run_id=import_run_id,
                    expected_revision=expected_run_revision,
                    completed_at_utc=now,
                )
                return AuditEventInput(
                    audit_event_id=audit_event_id,
                    action_type="ticket_import.checkpoint_advanced",
                    action_version=1,
                    actor_kind=actor_kind,
                    actor_id=actor_id,
                    target_type="import_source_family",
                    target_id=run.source_family,
                    command_id=command_id,
                    job_id=job_id,
                    import_run_id=import_run_id,
                    payload_schema="ImportCheckpointAuditV1",
                    payload_version=1,
                    payload={
                        "source_family": run.source_family,
                        "import_run_id": import_run_id,
                        "chronology_kind": run.chronology_kind,
                        "chronology_value": run.chronology_value,
                        "logical_fingerprint": run.logical_fingerprint,
                        "checkpoint_revision": expected_checkpoint_revision + 1,
                    },
                    resulting_event_refs=(
                        AuditResultRef("import_run", import_run_id),
                        AuditResultRef("import_source_checkpoint", run.source_family),
                    ),
                )

            return PreparedMutation(
                False,
                "import_run",
                import_run_id,
                apply,
                response_schema="CheckpointAdvanceResultV1",
                response_factory=response_factory,
            )

        return self._result_from_execution(self._boundary.execute(envelope, prepare))
