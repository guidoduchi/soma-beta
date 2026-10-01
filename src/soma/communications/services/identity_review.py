from __future__ import annotations

from dataclasses import dataclass

from soma.foundation.application.command_boundary import CommandBoundary, CommandEnvelope, PreparedMutation
from soma.foundation.audit.writer import AuditEventInput, AuditResultRef, AuditWriter
from soma.foundation.errors import IntegrityFailure, SomaError, ValidationError
from soma.foundation.identifiers import new_uuid4, require_uuid4, utc_epoch_seconds
from soma.foundation.persistence.uow import ReadSnapshot, UnitOfWork
from soma.foundation.strict_json import sha256_canonical_json

from soma.communications.audit_registry import audit_event, build_communications_audit_registry
from soma.communications.contracts.common import closed, fingerprint, integer
from soma.communications.contracts.identity_review import IdentityReviewRequest
from soma.communications.domain.communication import CanonicalMessageIdentity
from soma.communications.repositories.identity import resolve_identity
from soma.communications.repositories.sources import one, scope
from soma.communications.services.retention import reconcile_retention, retention
from soma.communications.services.settings import CommunicationSettingsService
from soma.communications.settings import GRACE_KEY


def require_scope(reader, source_scope_id, revision):
    require_uuid4(source_scope_id)
    current = scope(reader, source_scope_id)
    if current is None or current["revision"] != revision:
        raise SomaError("COMM_STALE", "Communication source configuration changed")
    return current


def cancellation_audit(transition, *, communication_id, command_id, actor_kind, actor_id):
    if transition is None or transition.to_state != "RETAINED":
        return ()
    return (audit_event("communications.orphan_grace.cancelled", command_id=command_id,
        target_type="communication", target_id=communication_id, actor_kind=actor_kind, actor_id=actor_id,
        payload={"retention_revision": transition.new_revision, "reason_code": "PROTECTED_DEPENDENCY_RESTORED"},
        refs=(AuditResultRef("communication", communication_id), AuditResultRef("communication_retention_event", transition.event_id))),)


@dataclass(frozen=True, slots=True)
class ProviderContentObservation:
    disposition: str  # UNCHANGED, REVIEW_REQUIRED, ACKNOWLEDGED
    communication_id: str
    review_evidence_id: str | None = None
    protection_hold_id: str | None = None
    audits: tuple[AuditEventInput, ...] = ()

    @property
    def permits_matching(self):
        # A declined variant is not evidence for associating the retained body.
        return self.disposition == "UNCHANGED"


class CommunicationIdentityReviewService:
    """Owned review SPI plus the bounded single-snapshot acknowledgement.

    Detection participates in the processing caller's receipt/UoW and returns
    its required audit emissions. It never opens a nested command or commits.
    Pairwise reconciliation is a separate durable-work path.
    """

    def __init__(self, connection_factory, *, clock=utc_epoch_seconds):
        self._factory = connection_factory
        self._clock = clock
        self._settings = CommunicationSettingsService(connection_factory).settings
        self._boundary = CommandBoundary(connection_factory, AuditWriter(build_communications_audit_registry()))

    def observe_provider_content_in_uow(self, uow, *, source_scope_id, source_revision, communication_id,
            identity: CanonicalMessageIdentity, command_id, now, actor_kind="job", actor_id=None):
        require_uuid4(command_id)
        require_uuid4(communication_id)
        integer(source_revision, minimum=1)
        integer(now)
        if not isinstance(uow, UnitOfWork) or uow.connection.execute(
                "SELECT 1 FROM command_receipts WHERE command_id=?", (command_id,)).fetchone() is None:
            raise IntegrityFailure("Communication conflict detection requires the caller's writer receipt")
        require_scope(uow, source_scope_id, source_revision)
        if not isinstance(identity, CanonicalMessageIdentity) or identity.provider_digest is None:
            raise ValidationError("Provider-content review requires captured stable identity evidence")
        resolved = resolve_identity(uow, source_scope_id, identity)
        if resolved.disposition != "REUSE" or resolved.communication_id != communication_id:
            raise SomaError("COMM_STALE", "Exact canonical provider identity changed")
        message = one(uow, "SELECT content_state,content_revision,identity_state,fallback_canonical_json FROM communications WHERE communication_id=?", (communication_id,))
        if message["content_state"] != "RETAINED":
            raise SomaError("COMM_CONTENT_PURGED", "Provider content requires governed reconstruction")
        if message["fallback_canonical_json"] is None:
            raise IntegrityFailure("Retained Communication has no exact content identity evidence")
        if message["fallback_canonical_json"] == identity.fallback_canonical_json:
            return ProviderContentObservation("UNCHANGED", communication_id)
        # Narrow by indexed digests, then compare exact provider bytes, complete
        # canonical objects and the unchanged retained snapshot. An acknowledged
        # donor can be recognized through a subsequently reviewed provider alias.
        exact_sql = (
            "SELECT e.review_evidence_id,e.protection_hold_id,e.decision_event_id FROM communication_identity_review_evidence e "
            "JOIN communications c ON c.communication_id=e.communication_id "
            "JOIN communication_protection_holds h ON h.protection_hold_id=e.protection_hold_id "
            "WHERE e.source_scope_id=? AND e.provider_identity_kind=? AND e.provider_identity_digest=? "
            "AND e.fallback_digest=? AND e.provider_identity_bytes=? AND e.fallback_canonical_json=? "
            "AND c.content_state='RETAINED' AND c.content_revision=e.retained_content_revision AND c.fallback_canonical_json=? "
        )
        exact_values = (source_scope_id, identity.provider_kind, identity.provider_digest, identity.fallback_digest,
                       identity.provider_bytes, identity.fallback_canonical_json, message["fallback_canonical_json"])
        existing = one(uow, exact_sql + "AND e.decision_event_id IS NOT NULL ORDER BY e.review_evidence_id LIMIT 1", exact_values)
        if existing is None:
            existing = one(uow, exact_sql + "AND e.communication_id=? AND h.state='ACTIVE' ORDER BY e.review_evidence_id LIMIT 1",
                           (*exact_values, communication_id))
        if existing is not None:
            return ProviderContentObservation("ACKNOWLEDGED" if existing["decision_event_id"] else "REVIEW_REQUIRED",
                communication_id, existing["review_evidence_id"], existing["protection_hold_id"])
        evidence_id, hold_id = new_uuid4(), new_uuid4()
        uow.connection.execute("INSERT INTO communication_protection_holds VALUES(?,?,'COLLISION_REVIEW',?,'ACTIVE',?,NULL)",
            (hold_id, communication_id, evidence_id, now))
        uow.connection.execute(
            "INSERT INTO communication_identity_review_evidence(review_evidence_id,communication_id,source_scope_id,source_revision,"
            "protection_hold_id,provider_identity_kind,provider_identity_digest,provider_identity_bytes,fallback_digest,"
            "fallback_canonical_json,retained_content_revision,created_at_utc) VALUES(?,?,?,?,?,?,?,?,?,?,?,?)",
            (evidence_id, communication_id, source_scope_id, source_revision, hold_id, identity.provider_kind,
             identity.provider_digest, identity.provider_bytes, identity.fallback_digest, identity.fallback_canonical_json,
             message["content_revision"], now))
        grace = self._settings.get_in_reader(uow, GRACE_KEY).value
        transition = reconcile_retention(uow, communication_id, dependency_event_id=hold_id,
            event_time=now, grace_minutes=grace, command_id=command_id)
        refs = (AuditResultRef("communication", communication_id), AuditResultRef("communication_protection_hold", hold_id))
        if transition is not None:
            refs += (AuditResultRef("communication_retention_event", transition.event_id),)
        audits = (audit_event("communications.identity.review_required", command_id=command_id,
            target_type="communication", target_id=communication_id, actor_kind=actor_kind, actor_id=actor_id,
            payload={"reason_code": "PROVIDER_CONTENT_CONFLICT", "identity_state": message["identity_state"], "protection_hold_id": hold_id}, refs=refs),)
        audits += cancellation_audit(transition, communication_id=communication_id, command_id=command_id,
            actor_kind=actor_kind, actor_id=actor_id)
        return ProviderContentObservation("REVIEW_REQUIRED", communication_id, evidence_id, hold_id, audits)

    def _content_preview(self, reader, request):
        require_scope(reader, request.source_scope_id, request.source_scope_revision)
        evidence = one(reader, "SELECT * FROM communication_identity_review_evidence WHERE review_evidence_id=?", (request.review_evidence_id,))
        message = one(reader, "SELECT content_state,content_revision FROM communications WHERE communication_id=?", (request.retained_communication_id,))
        if (evidence is None or message is None or evidence["communication_id"] != request.retained_communication_id
                or evidence["source_scope_id"] != request.source_scope_id
                or evidence["retained_content_revision"] != request.retained_content_revision
                or message["content_revision"] != request.retained_content_revision):
            raise SomaError("COMM_STALE", "Communication review snapshot changed")
        if message["content_state"] != "RETAINED" or evidence["fallback_canonical_json"] is None:
            raise SomaError("COMM_CONTENT_PURGED", "Communication review content is unavailable")
        hold = one(reader, "SELECT * FROM communication_protection_holds WHERE protection_hold_id=?", (evidence["protection_hold_id"],))
        if (hold is None or hold["communication_id"] != request.retained_communication_id
                or hold["hold_kind"] != "COLLISION_REVIEW" or hold["owner_ref"] != evidence["review_evidence_id"]
                or (evidence["decision_event_id"] is None and hold["state"] != "ACTIVE")):
            raise IntegrityFailure("Communication conflict has no governed active review hold")
        grace = self._settings.get_in_reader(reader, GRACE_KEY)
        # Only this hold can close. The complete retention impact is whether
        # another protected dependency remains, not the identity of every
        # sibling link/hold/proposal. Each branch is an indexed existence probe.
        other_protected = bool(reader.connection.execute(
            "SELECT EXISTS(SELECT 1 FROM communication_links WHERE communication_id=? AND state='ACTIVE') "
            "OR EXISTS(SELECT 1 FROM communication_protection_holds WHERE communication_id=? AND state='ACTIVE' AND protection_hold_id!=?) "
            "OR EXISTS(SELECT 1 FROM communication_proposals WHERE communication_id=? AND state IN ('PENDING','DEFERRED'))",
            (request.retained_communication_id, request.retained_communication_id,
             evidence["protection_hold_id"], request.retained_communication_id)).fetchone()[0])
        # Binary provider evidence is encoded solely into the internal digest;
        # previews, receipts, audits and diagnostics never expose it or content.
        token_evidence = {**evidence, "provider_identity_bytes": evidence["provider_identity_bytes"].hex()}
        token = sha256_canonical_json({"schema": "SOMA_COMM_IDENTITY_CONTENT_REVIEW_V1", "request": request.to_value(),
            "evidence": token_evidence, "hold": hold, "retention": retention(reader, request.retained_communication_id),
            "other_protected_dependency": other_protected,
            "grace": {"revision": grace.revision, "value": grace.value}})
        return evidence, token, grace.value

    @staticmethod
    def _content_request(value):
        request = IdentityReviewRequest.from_value(value)
        if request.decision != "KEEP_RETAINED_CONTENT":
            raise ValidationError("Content acknowledgement requires KEEP_RETAINED_CONTENT")
        return request

    def preview_keep_retained_content(self, value):
        request = self._content_request(value)
        with ReadSnapshot(self._factory) as reader:
            _, token, _ = self._content_preview(reader, request)
            return token

    def keep_retained_content(self, value, *, actor_kind="local_user", actor_id=None):
        closed(value, set(IdentityReviewRequest.__dataclass_fields__) | {"command_id", "preview_fingerprint"})
        command = require_uuid4(value["command_id"])
        expected = fingerprint(value["preview_fingerprint"])
        request = self._content_request({key: value[key] for key in IdentityReviewRequest.__dataclass_fields__})
        envelope = CommandEnvelope(command, "DecideCommunicationIdentity", "communication", request.retained_communication_id,
            request.to_value(), base_revisions={"source_scope": request.source_scope_revision, "content": request.retained_content_revision},
            authorizing_fingerprints={"preview": expected})

        def prepare(uow):
            evidence, token, grace = self._content_preview(uow, request)
            if token != expected:
                raise SomaError("COMM_STALE", "Communication identity preview changed")
            event = evidence["decision_event_id"]
            if event is not None:
                return PreparedMutation(True, None, None, response_schema="CommunicationIdentityReviewResultV1",
                    response={"status": "NO_CHANGE", "identity_review_event_id": event})
            event = new_uuid4()
            now = integer(self._clock())

            def apply(inner):
                changed = inner.connection.execute("UPDATE communication_protection_holds SET state='CLOSED',closed_at_utc=? "
                    "WHERE protection_hold_id=? AND state='ACTIVE'", (now, evidence["protection_hold_id"]))
                if changed.rowcount != 1:
                    raise IntegrityFailure("Communication conflict hold changed during acknowledgement")
                inner.connection.execute("INSERT INTO communication_identity_review_events VALUES(?,?,?,?,?, ?,NULL,NULL,?,?,0,0,0,1,?,?)",
                    (event, request.source_scope_id, request.source_scope_revision, request.decision, request.retained_communication_id,
                     request.retained_content_revision, request.review_evidence_id, expected, now, command))
                inner.connection.execute("UPDATE communication_identity_review_evidence SET decision_event_id=? WHERE review_evidence_id=?",
                    (event, request.review_evidence_id))
                transition = reconcile_retention(inner, request.retained_communication_id, dependency_event_id=event,
                    event_time=now, grace_minutes=grace, command_id=command)
                inner.connection.execute("INSERT INTO communication_identity_review_results VALUES(?, 'communication_protection_hold',?)",
                    (event, evidence["protection_hold_id"]))
                if transition is not None:
                    inner.connection.execute("INSERT INTO communication_identity_review_results VALUES(?, 'communication_retention_event',?)", (event, transition.event_id))
                return audit_event("communications.identity.decided", command_id=command, target_type="communication_identity_review_event", target_id=event,
                    actor_kind=actor_kind, actor_id=actor_id,
                    payload={"decision": request.decision, "source_scope_id": request.source_scope_id, "candidate_count": 1,
                             "closed_link_count": 0, "created_link_count": 0, "attached_alias_count": 0, "closed_hold_count": 1},
                    refs=(AuditResultRef("communication", request.retained_communication_id), AuditResultRef("communication_identity_review_event", event)))

            return PreparedMutation(False, "communication_identity_review_event", event, apply,
                response_schema="CommunicationIdentityReviewResultV1", response={"status": "APPLIED", "identity_review_event_id": event})

        return self._boundary.execute(envelope, prepare).response
