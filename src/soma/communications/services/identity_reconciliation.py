from __future__ import annotations

import hashlib
from dataclasses import dataclass

from soma.foundation.application.command_boundary import CommandBoundary, CommandEnvelope, PreparedMutation
from soma.foundation.audit.writer import AuditResultRef, AuditWriter
from soma.foundation.errors import IntegrityFailure, SomaError, ValidationError
from soma.foundation.identifiers import new_uuid4, require_uuid4, utc_epoch_seconds
from soma.foundation.persistence.uow import ReadSnapshot
from soma.foundation.strict_json import canonical_json_bytes, loads_canonical_json

from soma.communications.audit_registry import audit_event, build_communications_audit_registry
from soma.communications.contracts.common import closed, fingerprint, integer
from soma.communications.contracts.identity_review import IdentityReviewRequest
from soma.communications.contracts.jobs import CommunicationExecutionConfig, CommunicationJobCheckpoint, CommunicationJobCounters, CommunicationJobScope
from soma.communications.domain.communication import require_fallback_evidence
from soma.communications.jobs.communications import JOB_TYPES, dedupe_key
from soma.communications.repositories import identity_review as repository
from soma.communications.repositories.links import close_link, create_link
from soma.communications.repositories.sources import one
from soma.communications.services.identity_review import cancellation_audit, require_scope
from soma.communications.services.retention import reconcile_retention, retention
from soma.communications.services.settings import CommunicationSettingsService
from soma.communications.settings import GRACE_KEY


def _feed(digest, value):
    if isinstance(value, dict):
        value = {key: {"binary_hex": item.hex()} if isinstance(item, bytes) else item for key, item in value.items()}
    encoded = canonical_json_bytes(value)
    digest.update(len(encoded).to_bytes(8, "big"))
    digest.update(encoded)


def _request(value):
    result = IdentityReviewRequest.from_value(value)
    if result.decision == "KEEP_RETAINED_CONTENT":
        raise ValidationError("Content acknowledgement uses the bounded content-review command")
    return result


def _load(value):
    return loads_canonical_json(value, max_bytes=65536, max_depth=8, max_collection_items=512)


@dataclass(frozen=True, slots=True)
class PairPreview:
    preview_fingerprint: str
    closed_link_count: int
    created_link_count: int
    attached_alias_count: int
    closed_hold_count: int

    def to_value(self):
        return {name: getattr(self, name) for name in self.__dataclass_fields__}


class CommunicationIdentityReconciliationService:
    """Reviewed two-candidate groups; collections stream, consequences commit atomically.

    Source parsing is unnecessary. The immutable accepted request survives claim
    recovery without adding secrets/content to Foundation's closed job payload.
    """

    def __init__(self, connection_factory, identities, coordinator, *, clock=utc_epoch_seconds):
        self._factory, self._identities, self._jobs, self._clock = connection_factory, identities, coordinator, clock
        self._settings = CommunicationSettingsService(connection_factory).settings
        self._boundary = CommandBoundary(connection_factory, AuditWriter(build_communications_audit_registry()))

    def _candidates(self, reader, request):
        require_scope(reader, request.source_scope_id, request.source_scope_revision)
        retained = repository.candidate(reader, request.retained_communication_id)
        other = repository.candidate(reader, request.other_communication_id)
        for message, revision in ((retained, request.retained_content_revision), (other, request.other_content_revision)):
            if message is None or message["source_scope_id"] != request.source_scope_id or message["content_revision"] != revision:
                raise SomaError("COMM_STALE", "Communication identity candidate changed")
        if request.decision != "KEEP_SEPARATE":
            if retained["content_state"] != "RETAINED" or other["content_state"] != "RETAINED":
                raise SomaError("COMM_CONTENT_PURGED", "Identity transfer requires both retained snapshots")
            if (retained["fallback_canonical_json"] is None or other["fallback_canonical_json"] is None
                    or retained["fallback_version"] != other["fallback_version"]
                    or retained["fallback_canonical_json"] != other["fallback_canonical_json"]):
                raise SomaError("COMM_IDENTITY_COLLISION", "Identity transfer requires identical complete evidence")
            try:
                require_fallback_evidence(request.source_scope_id, retained["fallback_version"], retained["fallback_canonical_json"])
            except ValidationError:
                raise SomaError("COMM_IDENTITY_COLLISION", "Identity transfer requires complete supported canonical evidence") from None
        return retained, other

    def _alias_effect(self, reader, request, alias):
        existing = repository.selected_alias(reader, request.retained_communication_id, alias)
        donor_alias = repository.selected_alias(reader, request.other_communication_id, alias)
        for row in (existing, donor_alias):
            if row is not None and row["alias_evidence_bytes"] != alias["alias_evidence_bytes"]:
                raise SomaError("COMM_IDENTITY_COLLISION", "Alias digest has conflicting exact evidence")
        if alias["alias_kind"] not in repository.PROVIDER_KINDS:
            return existing, None, existing is None
        if alias["normalization_version"] != 1 or not alias["alias_evidence_bytes"]:
            raise SomaError("COMM_IDENTITY_COLLISION", "Provider alias has no exact versioned evidence")
        current = repository.assignment(reader, request.source_scope_id, alias)
        pair = (request.retained_communication_id, request.other_communication_id)
        if current is not None:
            if current["communication_id"] not in pair:
                raise SomaError("COMM_IDENTITY_COLLISION", "Provider key is governed outside this reviewed pair")
        else:
            outside = reader.connection.execute(
                "SELECT EXISTS(SELECT 1 FROM communication_identity_aliases a JOIN communications c USING(communication_id) "
                "WHERE c.source_scope_id=? AND a.alias_kind=? AND a.alias_digest=? AND a.normalization_version=1 AND a.alias_evidence_bytes=? "
                "AND a.communication_id NOT IN (?,?)) OR EXISTS(SELECT 1 FROM communications WHERE source_scope_id=? "
                "AND provider_identity_kind=? AND provider_identity_digest=? AND provider_identity_bytes=? AND communication_id NOT IN (?,?))",
                (request.source_scope_id, alias["alias_kind"], alias["alias_digest"], alias["alias_evidence_bytes"], *pair) * 2).fetchone()[0]
            if outside:
                raise SomaError("COMM_IDENTITY_COLLISION", "Exact provider key has an unreviewed outside candidate")
        return existing, current, existing is None or current is None or current["communication_id"] != request.retained_communication_id

    def _target_revision(self, reader, row):
        revision = self._identities.current_revision(reader, row["target_type"], row["target_id"])
        if revision is None or self._identities.validate_reassociation(reader, row["target_type"], row["target_id"], revision) != "VALID":
            raise SomaError("COMM_TARGET_STALE", "Reconciliation link target is no longer eligible")
        return revision

    @staticmethod
    def _remaining_dependency(reader, communication_id, *, remove_links):
        # Generic collision holds are the only holds in this reviewed closure
        # scope. Seal the retention effect after their removal, so a new content
        # variant/proposal/export cannot silently change the reviewed impact.
        return bool(reader.connection.execute(
            "SELECT (?=0 AND EXISTS(SELECT 1 FROM communication_links WHERE communication_id=? AND state='ACTIVE')) "
            "OR EXISTS(SELECT 1 FROM communication_protection_holds h WHERE communication_id=? AND state='ACTIVE' AND NOT (" + repository.GENERIC_HOLD + ")) "
            "OR EXISTS(SELECT 1 FROM communication_proposals WHERE communication_id=? AND state IN ('PENDING','DEFERRED'))",
            (int(remove_links), communication_id, communication_id, communication_id)).fetchone()[0])

    def _preview(self, reader, request):
        retained, other = self._candidates(reader, request)
        digest = hashlib.sha256(b"SOMA_COMM_PAIR_IDENTITY_REVIEW_V1\x00")
        _feed(digest, request.to_value())
        closed_links = created_links = attached_aliases = closed_holds = 0
        grace = self._settings.get_in_reader(reader, GRACE_KEY)
        _feed(digest, {"grace_revision": grace.revision, "grace_minutes": grace.value})
        for message in (retained, other):
            _feed(digest, message)
            _feed(digest, retention(reader, message["communication_id"]))
            remove_links = request.decision == "CONSOLIDATE_LINKS_AND_ALIASES" and message is other
            _feed(digest, {"other_protected": self._remaining_dependency(reader, message["communication_id"], remove_links=remove_links)})
            for hold in repository.generic_holds(reader, message["communication_id"]):
                _feed(digest, ["GENERIC_HOLD", *hold])
                closed_holds += 1
        provider_count = 0
        if request.decision != "KEEP_SEPARATE":
            for alias in repository.aliases(reader, other):
                existing, current, changed = self._alias_effect(reader, request, alias)
                _feed(digest, {"alias": {key: item.hex() if isinstance(item, bytes) else item for key, item in alias.items()},
                    "selected": None if existing is None else {"id": existing["identity_alias_id"], "bytes": None if existing["alias_evidence_bytes"] is None else existing["alias_evidence_bytes"].hex()},
                    "assignment": current})
                attached_aliases += int(changed)
                provider_count += int(alias["alias_kind"] in repository.PROVIDER_KINDS)
            if request.decision == "ATTACH_PROVIDER_IDENTITY" and not provider_count:
                raise SomaError("COMM_IDENTITY_COLLISION", "Provider identity attachment needs stronger exact evidence")
        if request.decision == "CONSOLIDATE_LINKS_AND_ALIASES":
            for row in repository.active_links(reader, other["communication_id"]):
                revision = self._target_revision(reader, row)
                existing = one(reader, "SELECT * FROM communication_links WHERE communication_id=? AND target_type=? AND target_id=? AND state='ACTIVE'",
                    (retained["communication_id"], row["target_type"], row["target_id"]))
                _feed(digest, {"link": row, "owner_revision": revision, "selected_active": existing})
                closed_links += 1
                created_links += int(existing is None)
        return PairPreview(digest.hexdigest(), closed_links, created_links, attached_aliases, closed_holds), retained, other, grace.value

    def preview(self, value):
        request = _request(value)
        with ReadSnapshot(self._factory) as reader:
            return self._preview(reader, request)[0].to_value()

    def enqueue(self, value, *, actor_kind="local_user", actor_id=None):
        closed(value, set(IdentityReviewRequest.__dataclass_fields__) | {"command_id", "preview_fingerprint"})
        command = require_uuid4(value["command_id"])
        expected = fingerprint(value["preview_fingerprint"])
        request = _request({key: value[key] for key in IdentityReviewRequest.__dataclass_fields__})
        envelope = CommandEnvelope(command, "RequestCommunicationIdentityReconciliation", "communication_source_scope", request.source_scope_id,
            request.to_value(), base_revisions={"source": request.source_scope_revision, "retained_content": request.retained_content_revision,
                "other_content": request.other_content_revision}, authorizing_fingerprints={"preview": expected})

        def prepare(uow):
            if self._preview(uow, request)[0].preview_fingerprint != expected:
                raise SomaError("COMM_STALE", "Communication reconciliation preview changed")
            source = require_scope(uow, request.source_scope_id, request.source_scope_revision)
            scope = CommunicationJobScope(request.source_scope_id, (), "IDENTITY_RECONCILIATION", None, None, (), request.source_scope_revision)
            execution = CommunicationExecutionConfig(source["adapter_family"], source["adapter_version"], 0, 100)
            result = {}

            def apply(inner):
                payload = scope.to_response()
                job_id = self._jobs.enqueue_or_coalesce(inner, JOB_TYPES[scope.job_kind], 1, payload, dedupe_key(payload))
                encoded = canonical_json_bytes(request.to_value()).decode("utf-8")
                existing = one(inner, "SELECT request_json,preview_fingerprint FROM communication_identity_review_requests WHERE job_id=?", (job_id,))
                if existing is not None and (existing["request_json"] != encoded or existing["preview_fingerprint"] != expected):
                    raise SomaError("COMM_JOB_ACTIVE", "Active reconciliation has a different reviewed candidate group")
                now = integer(self._clock())
                if existing is None:
                    inner.connection.execute("INSERT INTO communication_identity_review_requests VALUES(?,?,?,?,?)", (job_id, command, new_uuid4(), encoded, expected))
                    inner.connection.execute("INSERT INTO communication_job_scopes VALUES(?,?,?,?,?,?,?,?)",
                        (job_id, scope.job_kind, scope.source_scope_id, canonical_json_bytes(payload).decode("utf-8"), scope.config_revision, now, expected,
                         canonical_json_bytes(execution.to_response()).decode("utf-8")))
                    inner.connection.execute("INSERT INTO communication_job_counters VALUES(?,0,0,0,0,0,0,0,0,0,2,1,?)", (job_id, now))
                result.update(job_id=job_id, coalesced=existing is not None, job_kind=scope.job_kind)
                return audit_event("communications.processing.requested", command_id=command,
                    target_type="communication_job", target_id=job_id, actor_kind=actor_kind, actor_id=actor_id,
                    payload={"job_kind": scope.job_kind, "source_scope_id": scope.source_scope_id}, refs=(AuditResultRef("communication_job", job_id),))

            return PreparedMutation(False, "communication_job_request", command, apply, response_schema="CommunicationJobQueuedV1", response_factory=lambda inner: dict(result))

        return self._boundary.execute(envelope, prepare).response

    @staticmethod
    def _reference(uow, event, kind, identity):
        uow.connection.execute("INSERT OR IGNORE INTO communication_identity_review_results VALUES(?,?,?)", (event, kind, identity))

    def _attach(self, uow, request, alias, *, event, now):
        existing, current, changed = self._alias_effect(uow, request, alias)
        if not changed:
            return 0
        alias_id = existing["identity_alias_id"] if existing else new_uuid4()
        if existing is None:
            uow.connection.execute("INSERT INTO communication_identity_aliases VALUES(?,?,?,?,?,?,?)",
                (alias_id, request.retained_communication_id, alias["alias_kind"], alias["alias_digest"], alias["normalization_version"], now, alias["alias_evidence_bytes"]))
        if alias["alias_kind"] in repository.PROVIDER_KINDS and (current is None or current["communication_id"] != request.retained_communication_id):
            revision = uow.connection.execute("SELECT COALESCE(MAX(assignment_revision),0)+1 FROM communication_identity_alias_assignments WHERE source_scope_id=?", (request.source_scope_id,)).fetchone()[0]
            uow.connection.execute("INSERT INTO communication_identity_alias_assignments VALUES(?,?,?,?,?,?,?)",
                (new_uuid4(), request.source_scope_id, alias["alias_kind"], alias["alias_digest"], alias_id, event, revision))
        self._reference(uow, event, "communication_identity_alias", alias_id)
        return 1

    def _apply_pair(self, uow, request, preview, other, *, command, now, grace):
        event = new_uuid4()
        uow.connection.execute("INSERT INTO communication_identity_review_events VALUES(?,?,?,?,?,?,?,?,NULL,?,?,?,?,?,?,?)",
            (event, request.source_scope_id, request.source_scope_revision, request.decision, request.retained_communication_id, request.retained_content_revision,
             request.other_communication_id, request.other_content_revision, preview.preview_fingerprint, preview.closed_link_count,
             preview.created_link_count, preview.attached_alias_count, preview.closed_hold_count, now, command))
        attached = closed_links = created_links = closed_holds = 0
        if request.decision != "KEEP_SEPARATE":
            for alias in repository.aliases(uow, other):
                attached += self._attach(uow, request, alias, event=event, now=now)
        if request.decision == "CONSOLIDATE_LINKS_AND_ALIASES":
            after = None
            while rows := tuple(repository.active_links(uow, other["communication_id"], after=after, limit=100)):
                for row in rows:
                    existing = uow.connection.execute("SELECT 1 FROM communication_links WHERE communication_id=? AND target_type=? AND target_id=? AND state='ACTIVE'",
                        (request.retained_communication_id, row["target_type"], row["target_id"])).fetchone()
                    if existing is None:
                        message = {"communication_id": request.retained_communication_id, "direction": row["direction"],
                            "chronology_known": row["effective_chronology_known"], "chronology_utc": row["effective_chronology_utc"],
                            "chronology_source_kind": row["effective_chronology_source_kind"]}
                        _, created = create_link(uow, message, target_type=row["target_type"], target_id=row["target_id"],
                            target_revision=self._target_revision(uow, row), origin="REVIEWED", now=now, command_id=command, reason="REVIEWED_IDENTITY_CONSOLIDATION",
                            match={"matched_identity_kind": row["matched_identity_kind"], "matched_identity_value": row["matched_identity_value"],
                                   "match_rule_id": "COMM_REVIEWED_MANUAL_V1", "match_rule_version": 1, "confidence_basis": "REVIEWED_MANUAL"})
                        created_links += 1
                        self._reference(uow, event, "communication_link_event", created)
                    _, closed_event = close_link(uow, row, now=now, command_id=command, reason="REVIEWED_IDENTITY_CONSOLIDATION", event_kind="CORRECTED")
                    closed_links += 1
                    self._reference(uow, event, "communication_link_event", closed_event)
                after = rows[-1]["communication_link_id"]
        for communication_id in (request.retained_communication_id, request.other_communication_id):
            uow.connection.execute("INSERT INTO communication_identity_review_results SELECT ?, 'communication_protection_hold',h.protection_hold_id "
                "FROM communication_protection_holds h WHERE communication_id=? AND " + repository.GENERIC_HOLD, (event, communication_id))
            closed_holds += uow.connection.execute("UPDATE communication_protection_holds AS h SET state='CLOSED',closed_at_utc=? "
                "WHERE communication_id=? AND " + repository.GENERIC_HOLD, (now, communication_id)).rowcount
        if (attached, closed_links, created_links, closed_holds) != (preview.attached_alias_count, preview.closed_link_count, preview.created_link_count, preview.closed_hold_count):
            raise IntegrityFailure("Reviewed reconciliation consequences disagree with the sealed preview")
        audits = []
        for communication_id in (request.retained_communication_id, request.other_communication_id):
            transition = reconcile_retention(uow, communication_id, dependency_event_id=event, event_time=now, grace_minutes=grace, command_id=command)
            if transition is not None:
                self._reference(uow, event, "communication_retention_event", transition.event_id)
            audits.extend(cancellation_audit(transition, communication_id=communication_id, command_id=command, actor_kind="job", actor_id=None))
        audits.append(audit_event("communications.identity.decided", command_id=command, target_type="communication_identity_review_event", target_id=event,
            actor_kind="job", payload={"decision": request.decision, "source_scope_id": request.source_scope_id, "candidate_count": 2,
                "closed_link_count": closed_links, "created_link_count": created_links, "attached_alias_count": attached, "closed_hold_count": closed_holds},
            refs=(AuditResultRef("communication_identity_review_event", event), AuditResultRef("communication", request.retained_communication_id), AuditResultRef("communication", request.other_communication_id))))
        return event, tuple(audits)

    def execute_claim(self, claim):
        if claim.job_type != JOB_TYPES["IDENTITY_RECONCILIATION"] or claim.contract_version != 1:
            raise ValidationError("Reconciliation worker received another job type")
        with ReadSnapshot(self._factory) as reader:
            reviewed = one(reader, "SELECT * FROM communication_identity_review_requests WHERE job_id=?", (claim.job_id,))
        if reviewed is None:
            raise IntegrityFailure("Reconciliation job has no immutable reviewed request")
        request = _request(_load(reviewed["request_json"]))
        command = reviewed["execution_command_id"]
        envelope = CommandEnvelope(command, "ApplyCommunicationIdentityReconciliation", "communication_job", claim.job_id,
            {"job_id": claim.job_id, "request": request.to_value()},
            base_revisions={"source": request.source_scope_revision, "retained_content": request.retained_content_revision, "other_content": request.other_content_revision},
            authorizing_fingerprints={"preview": reviewed["preview_fingerprint"]})

        def prepare(uow):
            self._jobs.assert_claim_current(uow, claim)
            scope = CommunicationJobScope.from_value(_load(claim.payload_json))
            expected_scope = CommunicationJobScope(request.source_scope_id, (), "IDENTITY_RECONCILIATION", None, None, (), request.source_scope_revision)
            if scope != expected_scope:
                raise IntegrityFailure("Reconciliation job changed its reviewed scope")
            owned = one(uow, "SELECT scope_json,preview_fingerprint FROM communication_job_scopes WHERE job_id=?", (claim.job_id,))
            if owned is None or owned["scope_json"] != claim.payload_json or owned["preview_fingerprint"] != reviewed["preview_fingerprint"]:
                raise IntegrityFailure("Reconciliation job lost its immutable owned scope")
            preview, _, other, grace = self._preview(uow, request)
            if preview.preview_fingerprint != reviewed["preview_fingerprint"]:
                raise SomaError("COMM_STALE", "Reviewed reconciliation scope changed before execution")
            result = {}

            def apply(inner):
                event, audits = self._apply_pair(inner, request, preview, other, command=command, now=integer(self._clock()), grace=grace)
                counters = CommunicationJobCounters(discovered=2, inspected=2, estimated_total=2)
                self._jobs.checkpoint_in_uow(inner, claim, CommunicationJobCheckpoint(scope, None, counters, ()).to_response())
                changed = inner.connection.execute("UPDATE communication_job_counters SET discovered=2,inspected=2,revision=revision+1,updated_at_utc=? WHERE job_id=?", (integer(self._clock()), claim.job_id))
                if changed.rowcount != 1:
                    raise IntegrityFailure("Reconciliation job has no owned counters")
                result.update(status="APPLIED", identity_review_event_id=event)
                return audits

            return PreparedMutation(False, "communication_identity_review_execution", command, apply,
                response_schema="CommunicationIdentityReviewResultV1", response_factory=lambda inner: dict(result),
                after_audit=lambda inner: self._jobs.complete_in_uow(inner, claim))

        return self._boundary.execute(envelope, prepare).response
