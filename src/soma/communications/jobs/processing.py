"""Read-only ordinary inspection with atomic, bounded authoritative batches."""
from soma.foundation.errors import IntegrityFailure, SomaError, ValidationError
from soma.foundation.identifiers import utc_epoch_seconds
from soma.foundation.persistence.uow import ReadSnapshot, UnitOfWork

from soma.communications.contracts.message import TransientMessage
from soma.communications.contracts.source import SourceFolder, SourceProbe
from soma.communications.jobs.communications import JOB_TYPES
from soma.communications.jobs.execution import run_with_failure_policy
from soma.communications.services.matching import CommunicationMatchingService
from soma.communications.services.processing_batches import CommunicationBatchService, provider_checkpoint
from soma.communications.services import historical_coverage
from soma.communications.services.scan_scope import validate_range


class CommunicationProcessingWorker:
    def __init__(self, connection_factory, identities, coordinator, adapter, *, clock=utc_epoch_seconds):
        self._factory, self._jobs, self._adapter, self._clock = connection_factory, coordinator, adapter, clock
        self._identities = identities
        self._matching = CommunicationMatchingService(connection_factory, identities, coordinator)
        self._batches = CommunicationBatchService(connection_factory, identities, self._matching, coordinator, adapter, clock=clock)

    def run(self, claim):
        kinds = {JOB_TYPES[kind]: kind for kind in ("ORDINARY", "TARGETED_BACKFILL", "DEEP_SCAN")}
        if claim.job_type not in kinds or claim.contract_version != 1:
            raise ValidationError("Communication processing worker received another job type")
        return run_with_failure_policy(claim, self._jobs, job_kind=kinds[claim.job_type], clock=self._clock,
            execute=lambda: self._execute(claim), safe_message="Communication source inspection could not be completed.")

    def _execute(self, claim):
        # Owner identity preparation/gating always precedes opening mail content.
        self._matching.prepare_run(claim)
        with ReadSnapshot(self._factory) as snapshot:
            scope, execution, source, folders, _, _, _ = self._batches.progress(snapshot, claim)
            if next(iter(self._identities.snapshot(snapshot)), None) is None:
                raise SomaError("COMM_NO_TRACKABLE_TARGETS", "No accepted operational identities are available")
            if scope.job_kind != "ORDINARY":
                validate_range(scope.lower_bound, scope.upper_bound, adapter=self._adapter, allow_open=scope.job_kind == "DEEP_SCAN")
        probe = self._adapter.probe_read_only(source["current_location"], None)
        if not isinstance(probe, SourceProbe):
            raise IntegrityFailure("Communication adapter returned an invalid source probe")
        if probe.health == "LOCKED":
            raise SomaError("SOURCE_LOCKED", "Communication source is locked")
        if probe.health not in {"READY", "PARTIAL"}:
            raise SomaError("COMM_SOURCE_UNSUPPORTED", "Communication source is unavailable")
        if (probe.adapter_family, probe.adapter_version) != (execution.adapter_family, execution.adapter_version):
            raise SomaError("COMM_STALE", "Communication source adapter changed")
        if source["scope_identity_kind"] == "PROVIDER_ACCOUNT" and probe.scope_identity_candidate != source["scope_identity_value"]:
            raise SomaError("COMM_SOURCE_SCOPE_CONFLICT", "Communication source identity changed")
        selected = {row["provider_folder_key"]: row["role"] for row in folders}
        available = {folder.folder_key: folder.role for folder in probe.folders if folder.folder_key in selected}
        if available != selected:
            raise SomaError("COMM_STALE", "Communication source folder evidence changed")
        # Revalidate after the slow read-only probe, before opening any content.
        with ReadSnapshot(self._factory) as snapshot:
            self._batches.progress(snapshot, claim)
            for folder in folders:
                forward = self._batches._forward(snapshot, scope.source_scope_id, folder["source_folder_id"])
                if forward is not None and forward["adapter_version"] != execution.adapter_version:
                    raise SomaError("COMM_STALE", "Communication source checkpoint adapter changed")
                if scope.job_kind == "ORDINARY" and provider_checkpoint(forward) is None and scope.lower_bound is None:
                    raise SomaError("COMM_COVERAGE_BOUNDARY_UNKNOWN", "Communication source requires an accepted historical bound")
        with self._adapter.open_read_only(source["current_location"], None) as handle:
            for folder in folders:
                with ReadSnapshot(self._factory) as snapshot:
                    *_, committed = self._batches.progress(snapshot, claim)
                    forward = self._batches._forward(snapshot, scope.source_scope_id, folder["source_folder_id"])
                    if forward is not None and forward["adapter_version"] != execution.adapter_version:
                        raise SomaError("COMM_STALE", "Communication source checkpoint adapter changed")
                    history = None if scope.job_kind == "ORDINARY" else historical_coverage.segment(snapshot, claim, folder["source_folder_id"], committed)
                    if history is not None and history["state"] == "BOUNDED_COMPLETE":
                        continue
                    checkpoint = provider_checkpoint(forward) if scope.job_kind == "ORDINARY" else historical_coverage.position(history)
                folder_scope = SourceFolder(folder["provider_folder_key"], folder["role"], folder["display_name"])
                # This process-local policy carries only the accepted bound and
                # captured overlap; it grants no identity or chronology authority.
                overlap = {"overlap_messages": execution.overlap_messages,
                           "lower_bound": None if checkpoint is not None or scope.lower_bound is None else scope.lower_bound.to_response()}
                if scope.job_kind != "ORDINARY":
                    overlap.update(lower_bound=None if scope.lower_bound is None else scope.lower_bound.to_response(),
                        upper_bound=None if scope.upper_bound is None else scope.upper_bound.to_response())
                values = iter(self._adapter.enumerate(handle, folder_scope, checkpoint, overlap))
                previous = None
                while True:
                    # Cancellation/freshness check also precedes the next parse.
                    with ReadSnapshot(self._factory) as snapshot:
                        self._batches.progress(snapshot, claim)
                    try:
                        transient = next(values)
                    except StopIteration:
                        break
                    if not isinstance(transient, TransientMessage) or transient.folder.folder_key != folder_scope.folder_key or transient.folder.role != folder_scope.role:
                        raise IntegrityFailure("Communication adapter crossed its selected folder")
                    if previous is not None and self._adapter.compare_checkpoints(previous, transient.provider_position) not in {"BEFORE", "EQUAL"}:
                        raise SomaError("COMM_STALE", "Communication source enumeration is not ordered")
                    previous = transient.provider_position
                    prepared = self._batches.prepare_message(claim, transient)
                    self._batches.commit_message(claim, prepared)
                    # Release parser streams and captured content before parsing
                    # another potentially large message/attachment collection.
                    del prepared, transient
                self._batches.finish_folder(claim, folder["source_folder_id"], readable_complete=probe.health == "READY")
        with UnitOfWork(self._factory) as writer:
            _, _, _, _, counters, _, _ = self._batches.progress(writer, claim)
            self._jobs.complete_in_uow(writer, claim)
            return counters.to_response()
