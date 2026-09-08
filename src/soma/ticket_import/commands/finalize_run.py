from __future__ import annotations

import hmac
import re
from dataclasses import dataclass

from soma.foundation.application.command_boundary import CommandBoundary, CommandEnvelope, PreparedMutation
from soma.foundation.audit.writer import AuditEventInput, AuditResultRef, AuditWriter
from soma.foundation.errors import SomaError, ValidationError
from soma.foundation.identifiers import new_uuid4, require_uuid4, utc_epoch_seconds
from soma.foundation.persistence.connections import ConnectionFactory
from soma.foundation.persistence.uow import ReadSnapshot, UnitOfWork

from ..audit_registry import build_ticket_import_audit_registry
from ..repositories.runs import ImportRunRepository, SourceCheckpointRepository


_HEX64_RE = re.compile(r"[0-9a-f]{64}\Z")
_CHRONOLOGY_KINDS = frozenset({"filesystem_mtime_ns", "embedded_filename_timestamp_utc"})


@dataclass(frozen=True, slots=True)
class CheckpointAdvanceResult:
    import_run_id: str
    source_family: str
    run_state: str
    run_revision: int
    checkpoint_revision: int
    replayed: bool
    no_change: bool


class ImportRunFinalizationService:
    def __init__(self, connection_factory: ConnectionFactory) -> None:
        self._factory = connection_factory
        self._runs = ImportRunRepository()
        self._checkpoints = SourceCheckpointRepository()
        self._boundary = CommandBoundary(
            connection_factory,
            AuditWriter(build_ticket_import_audit_registry()),
        )

    def _result(self, import_run_id: str, *, replayed: bool, no_change: bool) -> CheckpointAdvanceResult:
        with ReadSnapshot(self._factory) as snapshot:
            run = self._runs.get_checkpoint_transition_run(snapshot.connection, import_run_id)
            if run is None:
                raise SomaError("IMPORT_RUN_STALE", "import run no longer exists")
            checkpoint = self._checkpoints.get(snapshot.connection, run.source_family)
            if checkpoint is None:
                raise SomaError("IMPORT_CHECKPOINT_STALE", "source checkpoint no longer exists")
        return CheckpointAdvanceResult(
            import_run_id=import_run_id,
            source_family=run.source_family,
            run_state=run.run_state,
            run_revision=run.revision,
            checkpoint_revision=checkpoint.revision,
            replayed=replayed,
            no_change=no_change,
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
                    return PreparedMutation(True, None, None)
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

            return PreparedMutation(False, "import_run", import_run_id, apply)

        execution = self._boundary.execute(envelope, prepare)
        return self._result(
            import_run_id,
            replayed=execution.replayed,
            no_change=execution.no_change,
        )
