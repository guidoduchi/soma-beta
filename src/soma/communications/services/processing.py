from __future__ import annotations

from collections.abc import Mapping

from soma.foundation.application.command_boundary import CommandBoundary, CommandEnvelope, PreparedMutation
from soma.foundation.audit.writer import AuditResultRef, AuditWriter
from soma.foundation.errors import IntegrityFailure, SomaError
from soma.foundation.identifiers import require_uuid4, utc_epoch_seconds
from soma.foundation.strict_json import canonical_json_bytes

from soma.communications.audit_registry import audit_event, build_communications_audit_registry
from soma.communications.contracts.common import closed, fingerprint, integer
from soma.communications.contracts.jobs import CommunicationExecutionConfig, CommunicationJobScope
from soma.communications.jobs.communications import JOB_TYPES, dedupe_key
from soma.communications.queries.previews import scan_request
from soma.communications.repositories.sources import one
from soma.communications.services.scan_scope import communication_settings, ordinary_scope, scan_preview_in_reader


def _proof_matches(value, *, target, revision, preview):
    names = {"action_code", "target", "base_revision", "preview_fingerprint"}
    if isinstance(value, Mapping):
        if set(value) != names:
            return False
        fields = dict(value)
    else:
        fields = {name: getattr(value, name, None) for name in names}
    actual_target = fields["target"]
    if not isinstance(actual_target, Mapping):
        actual_target = {name: getattr(actual_target, name, None) for name in ("target_type", "target_id")}
    return (fields["action_code"] == "COMMUNICATION_DEEP_SCAN" and actual_target == target
            and type(fields["base_revision"]) is int and fields["base_revision"] == revision
            and fields["preview_fingerprint"] == preview)


class CommunicationProcessingService:
    """Own the three start commands through one atomic enqueue implementation.

    The distinct public methods retain their declared command identities. Source
    parsing is exclusively worker work; requests and previews open no mail content.
    """

    def __init__(self, connection_factory, identities, coordinator, *, adapter=None, proof_provider=None, clock=utc_epoch_seconds):
        self._identities = identities
        self._jobs = coordinator
        self._adapter = adapter
        self._proof_provider = proof_provider
        self._clock = clock
        self._settings = communication_settings(connection_factory)
        self._boundary = CommandBoundary(connection_factory, AuditWriter(build_communications_audit_registry()))

    def start_processing(self, payload, *, actor_kind="local_user", actor_id=None):
        closed(payload, {"command_id", "source_scope_id", "source_scope_revision"})
        return self._start(payload, kind="ORDINARY", actor_kind=actor_kind, actor_id=actor_id)

    def start_targeted_backfill(self, payload, *, actor_kind="local_user", actor_id=None):
        closed(payload, {"command_id", "source_scope_id", "source_scope_revision", "target_identity_ids",
                         "lower_bound", "upper_bound", "preview_fingerprint"})
        return self._start(payload, kind="TARGETED_BACKFILL", actor_kind=actor_kind, actor_id=actor_id)

    def start_deep_scan(self, payload, *, actor_kind="local_user", actor_id=None):
        closed(payload, {"command_id", "source_scope_id", "source_scope_revision", "folder_keys",
                         "lower_bound", "upper_bound", "preview_fingerprint", "deliberate_action_proof"})
        return self._start(payload, kind="DEEP_SCAN", actor_kind=actor_kind, actor_id=actor_id)

    def request_scheduled_processing(self, payload):
        closed(payload, {"command_id", "source_scope_id", "source_scope_revision"})
        return self._start(payload, kind="ORDINARY", actor_kind="system", actor_id=None, automatic=True)

    def _start(self, payload, *, kind, actor_kind, actor_id, automatic=False):
        command = require_uuid4(payload["command_id"])
        identity = require_uuid4(payload["source_scope_id"])
        revision = integer(payload["source_scope_revision"], minimum=1)
        request = {key: value for key, value in payload.items() if key not in {"command_id", "deliberate_action_proof"}}
        token = None if kind == "ORDINARY" else fingerprint(request.pop("preview_fingerprint"))
        if kind != "ORDINARY":
            request = scan_request(request, kind=kind)
        semantic = request if token is None else {**request, "preview_fingerprint": token}
        command_type, action = {
            "ORDINARY": ("StartCommunicationProcessing", "communications.processing.requested"),
            "TARGETED_BACKFILL": ("StartTargetedBackfill", "communications.backfill.requested"),
            "DEEP_SCAN": ("StartDeepScan", "communications.deep_scan.requested"),
        }[kind]
        if automatic:
            command_type = "RequestScheduledCommunicationProcessing"
        envelope = CommandEnvelope(command, command_type, "communication_source_scope", identity, semantic,
                                   base_revisions={"source_scope": revision},
                                   authorizing_fingerprints={} if token is None else {"preview": token})

        def prepare(uow):
            if automatic:
                source = one(uow, "SELECT processing_enabled FROM communication_source_scopes WHERE source_scope_id=?", (identity,))
                if not self._settings.get_in_reader(uow, "communications.processing_enabled").value or source is None or not source["processing_enabled"]:
                    return PreparedMutation(True, None, None, response_schema="CommunicationScheduledRequestResultV1",
                        response={"job_id": None, "coalesced": False, "job_kind": "ORDINARY"})
            if kind == "ORDINARY":
                scope = ordinary_scope(uow, identity, revision, self._identities)
                preview = None
            else:
                preview = scan_preview_in_reader(uow, request, kind=kind, settings=self._settings,
                                                 identities=self._identities, adapter=self._adapter)
                if preview["preview_fingerprint"] != token:
                    raise SomaError("COMM_STALE", "Communication scan preview changed")
                scope = CommunicationJobScope.from_value(preview["scope"])
            source = one(uow, "SELECT adapter_family,adapter_version FROM communication_source_scopes WHERE source_scope_id=?", (identity,))
            execution = CommunicationExecutionConfig(source["adapter_family"], source["adapter_version"],
                self._settings.get_in_reader(uow, "communications.overlap_messages").value, 100)
            if kind == "DEEP_SCAN":
                target = {"target_type": "communication_source_scope", "target_id": identity}
                consume = getattr(self._proof_provider, "validate_and_consume", None)
                if not callable(consume):
                    raise SomaError("COMM_DEEP_SCAN_CONFIRMATION_REQUIRED", "Communication Deep Scan proof provider is unavailable")
                try:
                    validated = consume(uow, payload["deliberate_action_proof"], "COMMUNICATION_DEEP_SCAN", target, revision, token)
                except Exception:
                    raise SomaError("COMM_DEEP_SCAN_CONFIRMATION_REQUIRED", "Communication Deep Scan proof did not validate") from None
                if not _proof_matches(validated, target=target, revision=revision, preview=token):
                    raise SomaError("COMM_DEEP_SCAN_CONFIRMATION_REQUIRED", "Communication Deep Scan proof binding changed")
            state = {}

            def apply(inner):
                exact = scope.to_response()
                job_id = self._jobs.enqueue_or_coalesce(inner, JOB_TYPES[kind], 1, exact, dedupe_key(exact))
                existing = one(inner, "SELECT scope_json,preview_fingerprint FROM communication_job_scopes WHERE job_id=?", (job_id,))
                encoded = canonical_json_bytes(exact).decode("utf-8")
                coalesced = existing is not None
                if existing is not None:
                    if existing["scope_json"] != encoded or existing["preview_fingerprint"] != token:
                        raise SomaError("COMM_JOB_ACTIVE", "An active Communication job has a different immutable scope")
                else:
                    inner.connection.execute(
                        "INSERT INTO communication_job_scopes(job_id,job_kind,source_scope_id,scope_json,config_revision,created_at_utc,preview_fingerprint,execution_config_json) VALUES(?,?,?,?,?,?,?,?)",
                        (job_id, kind, identity, encoded, revision, self._clock(), token, canonical_json_bytes(execution.to_response()).decode("utf-8")))
                    inner.connection.execute(
                        "INSERT INTO communication_job_counters(job_id,discovered,inspected,matched,retained,unchanged,proposed,skipped,warnings,failures,estimated_total,revision,updated_at_utc) VALUES(?,0,0,0,0,0,0,0,0,0,NULL,1,?)",
                        (job_id, self._clock()))
                state.update(job_id=job_id, coalesced=coalesced, job_kind=kind)
                audit_payload = {"job_kind": kind, "source_scope_id": identity}
                if kind == "TARGETED_BACKFILL":
                    audit_payload.update(target_count=len(scope.target_identity_ids), confirmation_class=preview["confirmation_class"])
                elif kind == "DEEP_SCAN":
                    audit_payload = {"source_scope_id": identity, "folder_count": len(scope.folder_keys),
                                     "range_kind": "FULL_SCOPE" if scope.lower_bound is None and scope.upper_bound is None else "BOUNDED"}
                return audit_event(action, command_id=command, target_type="communication_job", target_id=job_id,
                                   payload=audit_payload, refs=(AuditResultRef("communication_job", job_id),),
                                   actor_kind=actor_kind, actor_id=actor_id)

            def response(inner):
                if not state:
                    raise IntegrityFailure("Communication job enqueue did not produce an identity")
                return dict(state)

            # A request audit is material evidence even when it coalesces with
            # prior work. It reports the request, never new processing results.
            return PreparedMutation(False, "communication_job_request", command, apply,
                                    response_schema="CommunicationJobQueuedV1", response_factory=response)

        return self._boundary.execute(envelope, prepare).response


class CommunicationReconstructionRequestParticipant:
    """Durable enqueue in reversal UoW; parsing starts only after its commit."""

    def __init__(self, connection_factory, identities, coordinator=None):
        from soma.foundation.jobs import DurableJobCoordinator, JobTypeRegistry
        from soma.communications.jobs.communications import COMMUNICATION_JOB_CONTRACTS
        from soma.communications.services.settings import CommunicationSettingsService
        self._identities = identities
        self._settings = CommunicationSettingsService(connection_factory).settings
        self._jobs = coordinator if coordinator is not None else DurableJobCoordinator(connection_factory, JobTypeRegistry(COMMUNICATION_JOB_CONTRACTS))
        self._audit = AuditWriter(build_communications_audit_registry())

    def request_in_uow(self, uow, message, target_type, target_id, target_revision, reversal_event_id, command_context):
        from soma.foundation.strict_json import sha256_canonical_json
        from soma.communications.contracts.common import Chronology
        from soma.communications.domain.summaries import identity_evidence
        from soma.communications.repositories import sources
        source = sources.scope(uow, message["source_scope_id"])
        if source is None or source["health_state"] not in {"READY", "PARTIAL"} or not message["chronology_known"]:
            # There is no authority for guessing a missing chronology/range or
            # opening a full store without its separate reviewed Deep Scan.
            return None
        if self._identities.validate_reassociation(uow, target_type, target_id, target_revision) != "VALID":
            raise SomaError("COMM_TARGET_STALE", "Reconstruction target is no longer eligible")
        folders = sources.enabled_folders(uow, source["source_scope_id"])
        if not folders or len(folders) > 64:
            raise IntegrityFailure("Reconstruction source has invalid selected folders")
        bound = Chronology(True, message["chronology_utc"], message["chronology_source_kind"])
        scope = CommunicationJobScope(source["source_scope_id"], tuple(row["provider_folder_key"] for row in folders),
            "TARGETED_BACKFILL", bound, bound, (target_id,), source["revision"])
        target_evidence = identity_evidence(self._identities.target_snapshot(uow, target_type, target_id))
        if not target_evidence[1]:
            raise SomaError("COMM_TARGET_STALE", "Reconstruction target has no exported identity evidence")
        token = sha256_canonical_json({"schema": "SOMA_COMM_REVERSAL_RECONSTRUCTION_V1", "scope": scope.to_response(),
            "target_type": target_type, "target_revision": target_revision, "target_evidence": target_evidence,
            "governing_event_id": reversal_event_id})
        execution = CommunicationExecutionConfig(source["adapter_family"], source["adapter_version"],
            self._settings.get_in_reader(uow, "communications.overlap_messages").value, 100)
        exact = scope.to_response()
        job_id = self._jobs.enqueue_or_coalesce(uow, JOB_TYPES["TARGETED_BACKFILL"], 1, exact, dedupe_key(exact))
        encoded = canonical_json_bytes(exact).decode("utf-8")
        existing = one(uow, "SELECT scope_json FROM communication_job_scopes WHERE job_id=?", (job_id,))
        if existing is not None and existing["scope_json"] != encoded:
            raise SomaError("COMM_JOB_ACTIVE", "Active reconstruction job changed its exact scope")
        if existing is None:
            now = utc_epoch_seconds()
            uow.connection.execute("INSERT INTO communication_job_scopes(job_id,job_kind,source_scope_id,scope_json,config_revision,created_at_utc,preview_fingerprint,execution_config_json) VALUES(?,?,?,?,?,?,?,?)",
                (job_id, "TARGETED_BACKFILL", source["source_scope_id"], encoded, source["revision"], now, token,
                    canonical_json_bytes(execution.to_response()).decode("utf-8")))
            uow.connection.execute("INSERT INTO communication_job_counters VALUES(?,0,0,0,0,0,0,0,0,0,NULL,1,?)", (job_id, now))
        self._audit.write(uow, audit_event("communications.backfill.requested", command_id=command_context["command_id"],
            actor_kind=command_context["actor_kind"], actor_id=command_context["actor_id"], target_type="communication_job", target_id=job_id,
            payload={"job_kind": "TARGETED_BACKFILL", "source_scope_id": source["source_scope_id"], "target_count": 1,
                "confirmation_class": "AUTO_BOUNDED"},
            refs=(AuditResultRef("communication_job", job_id), AuditResultRef("communication", message["communication_id"]))))
        return job_id
