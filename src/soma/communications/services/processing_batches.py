"""Authoritative ordinary batches; parsing belongs outside the writer UoW.

One inspection is a bounded batch. No parser handle, source item identity or
unmatched content is stored in job progress, receipts or diagnostic payloads.
"""
from __future__ import annotations

import hashlib
from dataclasses import dataclass, field

from soma.foundation.application.command_boundary import CommandBoundary, CommandEnvelope, PreparedMutation
from soma.foundation.audit.writer import AuditResultRef, AuditWriter
from soma.foundation.errors import IntegrityFailure, SomaError, ValidationError
from soma.foundation.identifiers import new_uuid4, utc_epoch_seconds
from soma.foundation.persistence.uow import ReadSnapshot
from soma.foundation.strict_json import canonical_json_bytes, loads_canonical_json, sha256_canonical_json

from soma.communications.audit_registry import audit_event, build_communications_audit_registry
from soma.communications.contracts.common import Chronology, integer
from soma.communications.contracts.jobs import CommunicationExecutionConfig, CommunicationJobCheckpoint, CommunicationJobCounters, CommunicationJobScope, bound_from_value
from soma.communications.contracts.matching import ALIASES
from soma.communications.contracts.message import TransientMessage
from soma.communications.contracts.proposal import CommunicationProposalContractRegistry
from soma.communications.contracts.source import ProviderCheckpoint
from soma.communications.domain.attachments import capture_attachments
from soma.communications.domain.communication import canonical_message_identity
from soma.communications.jobs.communications import JOB_TYPES
from soma.communications.repositories import communications, identity, links, proposals
from soma.communications.repositories.sources import one
from soma.communications.services.identity_review import CommunicationIdentityReviewService, cancellation_audit
from soma.communications.services.retention import reconcile_retention, record_transition, retention, has_protected_dependency
from soma.communications.services import historical_coverage
from soma.communications.services.scan_scope import readable_scope
from soma.communications.services.settings import CommunicationSettingsService
from soma.communications.settings import GRACE_KEY


def load(value):
    return loads_canonical_json(value, max_bytes=65536, max_depth=8, max_collection_items=512)


def provider_checkpoint(row):
    if row is None or row["checkpoint_kind"] is None:
        return None
    return ProviderCheckpoint(row["checkpoint_kind"], row["checkpoint_token"], row["provider_time_source_epoch_ms"])


@dataclass(frozen=True, slots=True)
class PreparedMessageBatch:
    envelope: CommandEnvelope
    message: TransientMessage = field(repr=False)
    attachments: tuple = field(repr=False)
    canonical_identity: object = field(repr=False)
    tokens: tuple[str, ...] = field(repr=False)
    candidate_fingerprint: str
    counter_revision: int
    folder_id: str
    forward_revision: int | None


class CommunicationBatchService:
    """Commit content, protection, audit, counters and coverage in one receipt."""

    def __init__(self, connection_factory, identities, matching, coordinator, adapter, *, clock=utc_epoch_seconds):
        self._factory, self._identities, self._matching = connection_factory, identities, matching
        self._jobs, self._adapter, self._clock = coordinator, adapter, clock
        self._audit = AuditWriter(build_communications_audit_registry())
        self._boundary = CommandBoundary(connection_factory, self._audit)
        self._review = CommunicationIdentityReviewService(connection_factory, clock=clock)
        self._settings = CommunicationSettingsService(connection_factory).settings
        self._contracts = CommunicationProposalContractRegistry()

    def progress(self, reader, claim):
        kinds = {JOB_TYPES[kind]: kind for kind in ("ORDINARY", "TARGETED_BACKFILL", "DEEP_SCAN")}
        if claim.job_type not in kinds or claim.contract_version != 1:
            raise ValidationError("Processing batch received another job type")
        committed = self._jobs.assert_claim_current(reader, claim)
        scope = CommunicationJobScope.from_value(load(claim.payload_json))
        owned = one(reader, "SELECT * FROM communication_job_scopes WHERE job_id=?", (claim.job_id,))
        if (owned is None or owned["job_kind"] != kinds[claim.job_type] or scope.job_kind != kinds[claim.job_type]
                or owned["scope_json"] != claim.payload_json or owned["source_scope_id"] != scope.source_scope_id
                or owned["config_revision"] != scope.config_revision):
            raise IntegrityFailure("Communication batch disagrees with its immutable owned scope")
        execution = CommunicationExecutionConfig.from_value(load(owned["execution_config_json"]))
        source, folders = readable_scope(reader, scope.source_scope_id, scope.config_revision)
        if (execution.adapter_family, execution.adapter_version) != (source["adapter_family"], source["adapter_version"]):
            raise SomaError("COMM_STALE", "Communication adapter configuration changed")
        available = {row["provider_folder_key"] for row in folders}
        if not set(scope.folder_keys).issubset(available) or (scope.job_kind != "DEEP_SCAN" and set(scope.folder_keys) != available):
            raise SomaError("COMM_STALE", "Communication selected folders changed")
        folders = [row for row in folders if row["provider_folder_key"] in scope.folder_keys]
        if scope.job_kind == "DEEP_SCAN" and owned["preview_fingerprint"] is None:
            raise IntegrityFailure("Deep Scan lost its immutable reviewed fingerprint")
        if scope.job_kind == "TARGETED_BACKFILL":
            selected = scope.target_identity_ids
            rows = reader.connection.execute("SELECT DISTINCT target_id,target_type,target_revision "
                "FROM communication_match_tokens WHERE job_id=? AND target_id IN (" + ",".join("?" for _ in selected) + ") LIMIT ?",
                (claim.job_id, *selected, len(selected) + 1)).fetchall()
            if len(rows) != len(selected) or {row[0] for row in rows} != set(selected):
                raise SomaError("COMM_TARGET_STALE", "Historical target reference changed or is ambiguous")
            for target, kind, revision in rows:
                if self._identities.validate_revision(reader, kind, target, revision) != "VALID":
                    raise SomaError("COMM_TARGET_STALE", "Historical target revision changed")
        row = one(reader, "SELECT * FROM communication_job_counters WHERE job_id=?", (claim.job_id,))
        if row is None:
            raise IntegrityFailure("Communication batch has no owned counters")
        counters = CommunicationJobCounters.from_value({key: row[key] for key in CommunicationJobCounters.__dataclass_fields__})
        checkpoint = None if committed is None else CommunicationJobCheckpoint.from_value(load(committed))
        if checkpoint is None:
            if counters != CommunicationJobCounters():
                raise IntegrityFailure("Communication counters have no committed checkpoint")
        elif checkpoint.scope != scope or checkpoint.counters != counters:
            raise IntegrityFailure("Communication counters disagree with committed progress")
        return scope, execution, source, folders, counters, row["revision"], checkpoint

    def _candidates(self, reader, job, tokens):
        digest = hashlib.sha256(b"SOMA_COMM_BATCH_CANDIDATES_V1\x00")
        for token in tokens:
            self._matching.require_current_candidates(reader, job, token)
            for candidate in self._matching.candidates(reader, job, token):
                if self._identities.validate(reader, candidate) != "VALID":
                    raise SomaError("COMM_TARGET_STALE", "Communication target identity changed")
                eligibility = self._identities.validate_reassociation(reader, candidate.target_type, candidate.target_id, candidate.target_revision)
                if eligibility not in {"VALID", "INVALID"}:
                    raise SomaError("COMM_TARGET_STALE", "Communication reassociation authority is unavailable")
                encoded = canonical_json_bytes([token, candidate.target_type, candidate.target_id, candidate.target_revision,
                    candidate.identity_kind, candidate.effective_from.to_response(), eligibility])
                digest.update(len(encoded).to_bytes(8, "big"))
                digest.update(encoded)
        return digest.hexdigest()

    def _require_range(self, scope, message):
        if (isinstance(scope.lower_bound, Chronology) and scope.lower_bound.known
                and message.chronology.known and message.chronology.utc_epoch_seconds < scope.lower_bound.utc_epoch_seconds):
            raise SomaError("COMM_STALE", "Communication inspection is outside its accepted lower bound")
        if scope.job_kind != "ORDINARY":
            if (isinstance(scope.upper_bound, Chronology) and scope.upper_bound.known and message.chronology.known
                    and message.chronology.utc_epoch_seconds > scope.upper_bound.utc_epoch_seconds):
                raise SomaError("COMM_STALE", "Communication inspection is outside its accepted upper bound")
            for bound, allowed in ((scope.lower_bound, {"BEFORE", "EQUAL"}), (scope.upper_bound, {"AFTER", "EQUAL"})):
                if isinstance(bound, ProviderCheckpoint) and self._adapter.compare_checkpoints(bound, message.provider_position) not in allowed:
                    raise SomaError("COMM_STALE", "Communication inspection crossed its provider range")

    @staticmethod
    def _unknown_range(scope, message):
        return scope.job_kind != "ORDINARY" and not message.chronology.known and any(
            isinstance(bound, Chronology) for bound in (scope.lower_bound, scope.upper_bound))

    def prepare_message(self, claim, message):
        if not isinstance(message, TransientMessage):
            raise ValidationError("Communication batch requires a typed transient message")
        # Capture streams and canonical evidence once, before the writer lock.
        with ReadSnapshot(self._factory) as reader:
            scope, _, _, folders, _, revision, _ = self.progress(reader, claim)
            folder = next((row for row in folders if row["provider_folder_key"] == message.folder.folder_key), None)
            if folder is None or folder["role"] != message.folder.role:
                raise SomaError("COMM_STALE", "Communication inspection crossed its selected folder")
            tokens = tuple(sorted({found.identity.normalized_value for found in self._matching.inspect(reader, claim.job_id, message)}))
            if scope.job_kind == "TARGETED_BACKFILL":
                tokens = tuple(token for token in tokens if any(candidate.target_id in scope.target_identity_ids
                    for candidate in self._matching.candidates(reader, claim.job_id, token)))
            candidates = self._candidates(reader, claim.job_id, tokens)
            forward = self._forward(reader, scope.source_scope_id, folder["source_folder_id"])
            if scope.job_kind != "ORDINARY" or provider_checkpoint(forward) is None:
                self._require_range(scope, message)
        captured = capture_attachments(message)
        canonical = canonical_message_identity(scope.source_scope_id, message, tuple(item.identity for item in captured))
        semantic = {"batch_sequence": revision, "folder_id": folder["source_folder_id"],
                    "checkpoint": message.provider_position.to_response(), "source_revision": scope.config_revision}
        # Unmatched canonical evidence never becomes durable receipt evidence.
        # A matched batch binds exact captured content and candidate authority.
        if tokens:
            semantic["preparation_fingerprint"] = sha256_canonical_json({"fallback": canonical.fallback_canonical_json,
                "provider": None if canonical.provider_bytes is None else canonical.provider_bytes.hex(),
                "provider_kind": canonical.provider_kind, "distinct": message.independently_distinct_source_item,
                "candidates": candidates})
        envelope = CommandEnvelope(new_uuid4(), "CommitCommunicationProcessingBatch", "communication_job", claim.job_id, semantic)
        return PreparedMessageBatch(envelope, message, captured, canonical, tokens, candidates, revision,
                                    folder["source_folder_id"], None if forward is None else forward["revision"])

    @staticmethod
    def _forward(reader, source_id, folder_id):
        return one(reader, "SELECT * FROM communication_forward_coverage WHERE source_scope_id=? AND source_folder_id=?", (source_id, folder_id))

    def _advance(self, prior, incoming, execution):
        if prior is not None and prior["adapter_version"] != execution.adapter_version:
            raise SomaError("COMM_STALE", "Communication checkpoint adapter changed")
        previous = provider_checkpoint(prior)
        if previous is None:
            return True
        order = self._adapter.compare_checkpoints(previous, incoming)
        if order not in {"BEFORE", "EQUAL", "AFTER"}:
            raise SomaError("COMM_STALE", "Communication checkpoint ordering is unavailable")
        return order == "BEFORE"

    def commit_message(self, claim, prepared):
        if not isinstance(prepared, PreparedMessageBatch) or prepared.envelope.target_id != claim.job_id:
            raise ValidationError("Communication batch preparation belongs to another job")
        envelope = prepared.envelope
        command = envelope.command_id
        completed = {}

        def prepare(writer):
            scope, execution, _, folders, counters, revision, checkpoint = self.progress(writer, claim)
            folder = next((row for row in folders if row["source_folder_id"] == prepared.folder_id), None)
            if (revision != prepared.counter_revision or folder is None
                    or folder["role"] != prepared.message.folder.role
                    or folder["provider_folder_key"] != prepared.message.folder.folder_key):
                raise SomaError("COMM_STALE", "Communication batch progress changed during preparation")
            forward = self._forward(writer, scope.source_scope_id, prepared.folder_id)
            if scope.job_kind == "ORDINARY" and (None if forward is None else forward["revision"]) != prepared.forward_revision:
                raise SomaError("COMM_STALE", "Communication forward coverage changed during preparation")
            if scope.job_kind != "ORDINARY" or provider_checkpoint(forward) is None:
                self._require_range(scope, prepared.message)
            if self._candidates(writer, claim.job_id, prepared.tokens) != prepared.candidate_fingerprint:
                raise SomaError("COMM_TARGET_STALE", "Communication target eligibility changed during preparation")
            advance = scope.job_kind == "ORDINARY" and self._advance(forward, prepared.message.provider_position, execution)
            now = integer(self._clock())
            grace = self._settings.get_in_reader(writer, GRACE_KEY).value

            def apply(inner):
                delta, communication_id = self._write_message(inner, claim, prepared, scope, now, grace)
                if advance:
                    position = prepared.message.provider_position
                    inner.connection.execute("INSERT INTO communication_forward_coverage VALUES(?,?,?,?,?,?,'PARTIAL',1,?) "
                        "ON CONFLICT(source_scope_id,source_folder_id) DO UPDATE SET checkpoint_kind=excluded.checkpoint_kind,"
                        "checkpoint_token=excluded.checkpoint_token,provider_time_source_epoch_ms=excluded.provider_time_source_epoch_ms,"
                        "state='PARTIAL',revision=communication_forward_coverage.revision+1,updated_at_utc=excluded.updated_at_utc",
                        (scope.source_scope_id, prepared.folder_id, execution.adapter_version, position.checkpoint_kind,
                         position.opaque_token, position.provider_time_source_epoch_ms, now))
                values = counters.to_response()
                for key, increment in delta.items():
                    values[key] = integer(values[key] + increment)
                current = CommunicationJobCounters.from_value(values)
                assignments = ",".join(key + "=?" for key in values)
                changed = inner.connection.execute("UPDATE communication_job_counters SET " + assignments + ",revision=revision+1,updated_at_utc=? WHERE job_id=? AND revision=?",
                    (*values.values(), now, claim.job_id, revision))
                if changed.rowcount != 1:
                    raise IntegrityFailure("Communication counters changed inside batch")
                # Job inspection progress includes committed overlap even when
                # the installation's forward high-water is already farther on.
                last = prepared.message.provider_position
                segments = ()
                if scope.job_kind != "ORDINARY":
                    previous = historical_coverage.segment(inner, claim, prepared.folder_id, checkpoint)
                    prior = historical_coverage.position(previous)
                    if prior is not None:
                        order = self._adapter.compare_checkpoints(prior, last)
                        if order not in {"BEFORE", "EQUAL", "AFTER"}:
                            raise SomaError("COMM_STALE", "Historical checkpoint ordering is unavailable")
                        if order == "AFTER":
                            last = prior
                    segments = historical_coverage.write(inner, claim, scope, prepared.folder_id, checkpoint, now=now,
                        lower=last if previous is None else bound_from_value(load(previous["lower_bound_json"])), upper=last,
                        state="UNKNOWN" if (previous is not None and previous["state"] == "UNKNOWN") or self._unknown_range(scope, prepared.message) else "PARTIAL")
                self._jobs.checkpoint_in_uow(inner, claim, CommunicationJobCheckpoint(scope, last, current, segments).to_response())
                completed.update(counters=current.to_response(), communication_id=communication_id, checkpoint_advanced=advance)
                refs = (AuditResultRef("communication_job", claim.job_id),)
                if communication_id is not None:
                    refs += (AuditResultRef("communication", communication_id),)
                return audit_event("communications.processing.batch_committed", command_id=command, actor_kind="job",
                    target_type="communication_job", target_id=claim.job_id,
                    payload={"batch_sequence": revision, "inspected": 1, "matched": delta["matched"], "retained": delta["retained"],
                             "proposed": delta["proposed"], "checkpoint_advanced": advance}, refs=refs)

            return PreparedMutation(False, "communication_job", claim.job_id, apply,
                response_schema="CommunicationBatchResultV1", response_factory=lambda inner: dict(completed))

        # Immutable replay is resolved before claim/current-state checks.
        return self._boundary.execute(envelope, prepare).response

    def _protect_collision_candidates(self, writer, scope, canonical, command, now, grace):
        # Both branches stream indexed digest candidate groups. Candidate count
        # has no business cap and no process-sized list or per-page sort is used.
        groups = [("fallback_version=? AND fallback_digest=?", (canonical.fallback_version, canonical.fallback_digest))]
        if canonical.provider_digest is not None:
            groups.append(("provider_identity_kind=? AND provider_identity_digest=?", (canonical.provider_kind, canonical.provider_digest)))
        for predicate, parameters in groups:
            for candidate, state in writer.connection.execute("SELECT communication_id,identity_state FROM communications WHERE source_scope_id=? AND " + predicate,
                    (scope.source_scope_id, *parameters)):
                exists = writer.connection.execute("SELECT state FROM communication_protection_holds WHERE communication_id=? "
                    "AND hold_kind='COLLISION_REVIEW' AND owner_ref=?", (candidate, candidate)).fetchone()
                if exists is not None:
                    if exists[0] != "ACTIVE":
                        raise SomaError("COMM_IDENTITY_COLLISION", "Previously reviewed identity requires a fresh governed reconciliation")
                    continue
                hold = new_uuid4()
                writer.connection.execute("INSERT INTO communication_protection_holds VALUES(?,?,'COLLISION_REVIEW',?,'ACTIVE',?,NULL)", (hold, candidate, candidate, now))
                transition = reconcile_retention(writer, candidate, dependency_event_id=hold, event_time=now, grace_minutes=grace, command_id=command)
                self._audit.write(writer, audit_event("communications.identity.review_required", command_id=command,
                    actor_kind="job", target_type="communication", target_id=candidate,
                    payload={"reason_code": "IDENTITY_COLLISION", "identity_state": state, "protection_hold_id": hold},
                    refs=(AuditResultRef("communication", candidate), AuditResultRef("communication_protection_hold", hold))))
                for event in cancellation_audit(transition, communication_id=candidate, command_id=command, actor_kind="job", actor_id=None):
                    self._audit.write(writer, event)

    def _write_message(self, writer, claim, prepared, scope, now, grace):
        command, message, canonical = prepared.envelope.command_id, prepared.message, prepared.canonical_identity
        delta = {"discovered": 1, "inspected": 1, "matched": 0, "retained": 0, "unchanged": 0, "proposed": 0, "skipped": 0, "warnings": 0}
        if self._unknown_range(scope, message):
            delta["skipped"] = delta["warnings"] = 1
            return delta, None
        resolved = identity.resolve_identity(writer, scope.source_scope_id, canonical,
            independently_distinct_source_item=message.independently_distinct_source_item)
        if resolved.disposition != "REUSE" and not prepared.tokens:
            delta["skipped"] = 1
            return delta, None
        if resolved.disposition == "COLLISION_REVIEW" and writer.connection.execute(
                "SELECT 1 FROM communications WHERE source_scope_id=? AND fallback_version=? AND fallback_digest=? "
                "AND identity_state='IDENTITY_COLLISION' LIMIT 1",
                (scope.source_scope_id, canonical.fallback_version, canonical.fallback_digest)).fetchone() is not None:
            # Existing unresolved fallback candidates cannot identify an overlap
            # item exactly. Preserve their committed review evidence and stop
            # this batch, rather than manufacturing more duplicate candidates
            # or treating provider position as canonical identity authority.
            raise SomaError("COMM_IDENTITY_COLLISION", "Message identity requires reviewed reconciliation")
        communication_id = resolved.communication_id or new_uuid4()
        created = resolved.disposition != "REUSE"
        reconstructed = False
        if created:
            state = "IDENTITY_COLLISION" if resolved.disposition == "COLLISION_REVIEW" else "PROVIDER_STABLE" if canonical.provider_digest else "FALLBACK"
            communications.insert_retained(writer, communication_id, scope.source_scope_id, message, canonical,
                prepared.attachments, identity_state=state, now=now)
            writer.connection.execute("INSERT INTO communication_retention VALUES(?,'RETAINED',NULL,NULL,NULL,1,?)", (communication_id, now))
            delta["retained"] = delta["matched"] = 1
            if state == "IDENTITY_COLLISION":
                delta["warnings"] = 1
                self._protect_collision_candidates(writer, scope, canonical, command, now, grace)
        else:
            current = one(writer, "SELECT * FROM communications WHERE communication_id=?", (communication_id,))
            # Purged content is never silently recreated by ordinary overlap.
            # Governed reconstruction will use the targeted reversal worker.
            if current["content_state"] != "RETAINED":
                if scope.job_kind == "ORDINARY" or not prepared.tokens:
                    delta["unchanged"] = 1
                    delta["warnings"] = 1
                    return delta, communication_id
                if current["fallback_version"] != canonical.fallback_version or current["fallback_digest"] != canonical.fallback_digest:
                    raise SomaError("COMM_IDENTITY_COLLISION", "Purged source evidence changed before reconstruction")
                communications.restore_retained(writer, communication_id, message, canonical, prepared.attachments, now=now)
                reconstructed = True
                delta["retained"] = 1
            if canonical.provider_digest is not None:
                observed = self._review.observe_provider_content_in_uow(writer, source_scope_id=scope.source_scope_id,
                    source_revision=scope.config_revision, communication_id=communication_id, identity=canonical,
                    command_id=command, now=now)
                for event in observed.audits:
                    self._audit.write(writer, event)
                if not observed.permits_matching:
                    delta["warnings"] = int(bool(observed.audits))
                    delta["unchanged"] = int(not observed.audits)
                    return delta, communication_id
        stored = links.require_retained_message(writer, communication_id)
        collision = (one(writer, "SELECT identity_state FROM communications WHERE communication_id=?", (communication_id,))["identity_state"] == "IDENTITY_COLLISION"
            or writer.connection.execute("SELECT 1 FROM communication_protection_holds WHERE communication_id=? "
                "AND hold_kind='COLLISION_REVIEW' AND owner_ref=? AND state='ACTIVE' LIMIT 1", (communication_id, communication_id)).fetchone() is not None)
        dependency = None
        for token in prepared.tokens:
            # Indexed existence probe: ambiguity has no business cardinality cap.
            targets = writer.connection.execute("SELECT DISTINCT target_type,target_id FROM communication_match_tokens "
                "WHERE job_id=? AND token=? LIMIT 2", (claim.job_id, token)).fetchall()
            ambiguous = len(targets) != 1
            for candidate in self._matching.candidates(writer, claim.job_id, token):
                if scope.job_kind == "TARGETED_BACKFILL" and candidate.target_id not in scope.target_identity_ids:
                    continue
                if links.active_link(writer, communication_id, candidate.target_type, candidate.target_id) is not None:
                    continue
                prior = writer.connection.execute("SELECT 1 FROM communication_links WHERE communication_id=? AND target_type=? AND target_id=? LIMIT 1",
                    (communication_id, candidate.target_type, candidate.target_id)).fetchone()
                reviewed = writer.connection.execute("SELECT 1 FROM communication_proposals WHERE communication_id=? AND target_type=? AND target_id=? "
                    "AND proposal_contract_id='COMM_LINK_V1' LIMIT 1", (communication_id, candidate.target_type, candidate.target_id)).fetchone()
                eligible = self._identities.validate_reassociation(writer, candidate.target_type, candidate.target_id, candidate.target_revision)
                alias = candidate.identity_kind in ALIASES
                match = {"schema": "COMM_LINK_V1", "matched_identity_kind": candidate.identity_kind,
                    "matched_identity_value": candidate.normalized_value,
                    "match_rule_id": "COMM_EXACT_ALIAS_V1" if alias else "COMM_EXACT_IDENTIFIER_V1", "match_rule_version": 1,
                    "confidence_basis": "EXACT_ALIAS" if alias else "EXACT_IDENTIFIER"}
                if not ambiguous and not alias and not collision and not prior and not reviewed and eligible == "VALID":
                    _, dependency = links.create_link(writer, stored, target_type=candidate.target_type, target_id=candidate.target_id,
                        target_revision=candidate.target_revision, match=match, origin="AUTO_SAFE", now=now, command_id=command, reason="EXACT_IDENTIFIER")
                else:
                    payload = self._contracts.validate("COMM_LINK_V1", 1, candidate.target_type, match)
                    written = proposals.insert_pending(writer, communication_id, source_revision=scope.config_revision,
                        target_id=candidate.target_id, target_revision=candidate.target_revision, payload=payload, now=now, command_id=command)
                    delta["proposed"] += int(written.created)
                    if written.created:
                        dependency = written.creation_event_id
        if reconstructed:
            if not has_protected_dependency(writer, communication_id):
                raise IntegrityFailure("Reconstructed content has no governed protection")
            transition = record_transition(writer, retention(writer, communication_id), to_state="RETAINED",
                reason_code="RECONSTRUCTED_FROM_SOURCE", dependency_event_id=dependency, event_time=now,
                command_id=command, orphan_since=None, due=None)
            self._audit.write(writer, audit_event("communications.content_reconstructed", command_id=command, actor_kind="job",
                target_type="communication", target_id=communication_id,
                payload={"source_scope_id": scope.source_scope_id, "content_revision": stored["content_revision"],
                    "restored_target_count": delta["proposed"] + writer.connection.execute("SELECT count(*) FROM communication_links WHERE communication_id=? AND state='ACTIVE'", (communication_id,)).fetchone()[0]},
                refs=(AuditResultRef("communication", communication_id), AuditResultRef("communication_retention_event", transition.event_id))))
        if dependency is not None:
            transition = reconcile_retention(writer, communication_id, dependency_event_id=dependency,
                event_time=now, grace_minutes=grace, command_id=command)
            for event in cancellation_audit(transition, communication_id=communication_id, command_id=command, actor_kind="job", actor_id=None):
                self._audit.write(writer, event)
            delta["matched"] = 1
        elif not created:
            delta["unchanged"] = 1
        return delta, communication_id

    def finish_folder(self, claim, folder_id, *, readable_complete):
        """Record adapter exhaustion, without inventing a position for emptiness."""
        if type(readable_complete) is not bool:
            raise ValidationError("Communication folder exhaustion requires exact readability")
        with ReadSnapshot(self._factory) as reader:
            scope, *_ = self.progress(reader, claim)
        if scope.job_kind != "ORDINARY":
            return self._finish_historical_folder(claim, folder_id, readable_complete=readable_complete)
        envelope = CommandEnvelope(new_uuid4(), "CompleteCommunicationFolderInspection", "communication_job", claim.job_id,
            {"folder_id": folder_id, "readable_complete": readable_complete})

        def prepare(writer):
            scope, _, source, folders, counters, revision, checkpoint = self.progress(writer, claim)
            if folder_id not in {row["source_folder_id"] for row in folders}:
                raise SomaError("COMM_STALE", "Communication completion crossed its selected folder")
            forward = self._forward(writer, scope.source_scope_id, folder_id)
            complete = readable_complete and source["health_state"] == "READY"
            state = "COMPLETE_TO_HIGH_WATER" if complete else "PARTIAL"
            unknown = not complete and (forward is None or forward["checkpoint_kind"] is None)
            if unknown:
                state = "UNKNOWN"
            if (complete and (forward is None or forward["checkpoint_kind"] is None)) or (forward is not None and forward["state"] == state):
                return PreparedMutation(True, None, None, response_schema="CommunicationJobCountersV1", response=counters.to_response())
            values = counters.to_response()
            if unknown:
                values["warnings"] = integer(values["warnings"] + 1)
            current = CommunicationJobCounters.from_value(values)

            def apply(inner):
                now = integer(self._clock())
                if forward is None:
                    inner.connection.execute("INSERT INTO communication_forward_coverage VALUES(?,?,?,NULL,NULL,NULL,'UNKNOWN',1,?)",
                        (scope.source_scope_id, folder_id, source["adapter_version"], now))
                else:
                    inner.connection.execute("UPDATE communication_forward_coverage SET state=?,revision=revision+1,updated_at_utc=? "
                        "WHERE source_scope_id=? AND source_folder_id=?", (state, now, scope.source_scope_id, folder_id))
                inner.connection.execute("UPDATE communication_job_counters SET warnings=?,revision=revision+1,updated_at_utc=? WHERE job_id=?",
                    (current.warnings, now, claim.job_id))
                self._jobs.checkpoint_in_uow(inner, claim, CommunicationJobCheckpoint(scope,
                    None if checkpoint is None else checkpoint.last_committed_provider_checkpoint, current, ()).to_response())
                return audit_event("communications.processing.batch_committed", command_id=envelope.command_id, actor_kind="job",
                    target_type="communication_job", target_id=claim.job_id,
                    payload={"batch_sequence": revision, "inspected": 0, "matched": 0, "retained": 0, "proposed": 0, "checkpoint_advanced": False},
                    refs=(AuditResultRef("communication_job", claim.job_id),))

            return PreparedMutation(False, "communication_job", claim.job_id, apply,
                response_schema="CommunicationJobCountersV1", response=current.to_response())

        return self._boundary.execute(envelope, prepare).response

    def _finish_historical_folder(self, claim, folder_id, *, readable_complete):
        envelope = CommandEnvelope(new_uuid4(), "CompleteCommunicationHistoricalFolder", "communication_job", claim.job_id,
            {"folder_id": folder_id, "readable_complete": readable_complete})

        def prepare(writer):
            scope, _, source, folders, counters, revision, checkpoint = self.progress(writer, claim)
            if folder_id not in {row["source_folder_id"] for row in folders}:
                raise SomaError("COMM_STALE", "Historical completion crossed its selected folder")
            previous = historical_coverage.segment(writer, claim, folder_id, checkpoint)
            complete = readable_complete and source["health_state"] == "READY" and (previous is None or previous["state"] != "UNKNOWN")
            lower = scope.lower_bound or (None if previous is None else bound_from_value(load(previous["lower_bound_json"])))
            upper = scope.upper_bound or (None if previous is None else bound_from_value(load(previous["upper_bound_json"])))
            state = "BOUNDED_COMPLETE" if complete and lower is not None and upper is not None else "PARTIAL" if lower is not None and upper is not None else "UNKNOWN"
            if previous is not None and previous["state"] == "UNKNOWN":
                state = "UNKNOWN"
            if previous is not None and previous["state"] == state and state == "BOUNDED_COMPLETE":
                return PreparedMutation(True, None, None, response_schema="CommunicationJobCountersV1", response=counters.to_response())
            values = counters.to_response()
            if state != "BOUNDED_COMPLETE":
                values["warnings"] += 1
            current = CommunicationJobCounters.from_value(values)

            def apply(inner):
                now = integer(self._clock())
                ids = historical_coverage.write(inner, claim, scope, folder_id, checkpoint, now=now, lower=lower, upper=upper, state=state)
                inner.connection.execute("UPDATE communication_job_counters SET warnings=?,revision=revision+1,updated_at_utc=? WHERE job_id=?", (current.warnings, now, claim.job_id))
                self._jobs.checkpoint_in_uow(inner, claim, CommunicationJobCheckpoint(scope,
                    None if checkpoint is None else checkpoint.last_committed_provider_checkpoint, current, ids).to_response())
                return audit_event("communications.processing.batch_committed", command_id=envelope.command_id, actor_kind="job",
                    target_type="communication_job", target_id=claim.job_id,
                    payload={"batch_sequence": revision, "inspected": 0, "matched": 0, "retained": 0, "proposed": 0, "checkpoint_advanced": False},
                    refs=(AuditResultRef("communication_job", claim.job_id),))
            return PreparedMutation(False, "communication_job", claim.job_id, apply, response_schema="CommunicationJobCountersV1", response=current.to_response())
        return self._boundary.execute(envelope, prepare).response
