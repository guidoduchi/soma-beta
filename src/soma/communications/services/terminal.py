from __future__ import annotations

import hashlib

from soma.foundation.audit.writer import AuditResultRef, AuditWriter
from soma.foundation.errors import IntegrityFailure, SomaError
from soma.foundation.identifiers import new_uuid4, require_uuid4
from soma.foundation.strict_json import canonical_json_bytes

from soma.communications.audit_registry import audit_event, build_communications_audit_registry
from soma.communications.contracts.common import closed, integer, text
from soma.communications.queries.summaries import live_summary_in_reader
from soma.communications.repositories.links import active_link, close_link
from soma.communications.repositories.sources import one
from soma.communications.repositories.summaries import freeze_in_uow, frozen_in_reader
from soma.communications.services.retention import dependency_fingerprint, reconcile_retention
from soma.communications.services.settings import CommunicationSettingsService
from soma.communications.settings import GRACE_KEY


def _context(uow, raw):
    context = closed(raw, {"command_id", "actor_kind", "actor_id"})
    require_uuid4(context["command_id"])
    text(context["actor_kind"], minimum=1, maximum=128)
    if context["actor_id"] is not None:
        require_uuid4(context["actor_id"])
    if not uow.connection.execute("SELECT 1 FROM command_receipts WHERE command_id=?", (context["command_id"],)).fetchone():
        raise IntegrityFailure("Terminal Communications consequences require the owning caller receipt")
    return context


def _links(reader, target_type, target_id, *, state="ACTIVE", terminal_command=None):
    """Stable keyset batches while caller updates the indexed state column."""
    after = ""
    while True:
        sql = "SELECT l.* FROM communication_links l WHERE l.target_type=? AND l.target_id=? AND l.state=? AND l.communication_link_id>?"
        parameters = (target_type, target_id, state, after)
        if terminal_command is not None:
            sql += " AND l.close_reason='SR_TERMINAL' AND EXISTS(SELECT 1 FROM communication_link_events e "
            sql += "WHERE e.communication_link_id=l.communication_link_id AND e.new_revision=l.revision AND e.event_kind='CLOSED' AND e.command_id=?)"
            parameters += (terminal_command,)
        cursor = reader.connection.execute(sql + " ORDER BY l.communication_link_id LIMIT 100", parameters)
        names = tuple(column[0] for column in cursor.description)
        rows = cursor.fetchall()
        if not rows:
            return
        after = rows[-1][0]
        for raw in rows:
            yield dict(zip(names, raw))


class ServiceRequestTerminalCommunicationParticipant:
    def __init__(self, connection_factory, identity_providers, *, reconstruction_request_participant=None):
        from soma.communications.services.processing import CommunicationReconstructionRequestParticipant
        self._identities = identity_providers
        self._settings = CommunicationSettingsService(connection_factory).settings
        self._audit = AuditWriter(build_communications_audit_registry())
        self._reconstruction = (reconstruction_request_participant if reconstruction_request_participant is not None
                                else CommunicationReconstructionRequestParticipant(connection_factory, identity_providers))

    def preview_terminal_transition(self, snapshot, sr_id, sr_revision):
        require_uuid4(sr_id)
        integer(sr_revision, minimum=1)
        valid = self._identities.validate_revision(snapshot, "SERVICE_REQUEST", sr_id, sr_revision)
        if valid != "VALID":
            return "INDETERMINATE"
        summary = live_summary_in_reader(snapshot, self._identities, "SERVICE_REQUEST", sr_id)
        digest = hashlib.sha256(b"SOMA_COMM_SR_TERMINAL_IMPACT_V1\x00")
        grace = self._settings.get_in_reader(snapshot, GRACE_KEY)
        digest.update(canonical_json_bytes([sr_id, sr_revision, summary, grace.revision, grace.value]))
        closed_count = orphan_count = 0
        for row in _links(snapshot, "SERVICE_REQUEST", sr_id):
            communication = row["communication_id"]
            retained = one(snapshot, "SELECT state,revision FROM communication_retention WHERE communication_id=?", (communication,))
            if retained is None:
                raise IntegrityFailure("Terminal Communication lost its retention evidence")
            protected = snapshot.connection.execute(
                "SELECT EXISTS(SELECT 1 FROM communication_links WHERE communication_id=? AND state='ACTIVE' "
                "AND (target_type!='SERVICE_REQUEST' OR target_id!=?)) "
                "OR EXISTS(SELECT 1 FROM communication_protection_holds WHERE communication_id=? AND state='ACTIVE') "
                "OR EXISTS(SELECT 1 FROM communication_proposals WHERE communication_id=? AND state IN ('PENDING','DEFERRED'))",
                (communication, sr_id, communication, communication),
            ).fetchone()[0]
            encoded = canonical_json_bytes([row, retained, dependency_fingerprint(snapshot, communication)])
            digest.update(len(encoded).to_bytes(8, "big"))
            digest.update(encoded)
            closed_count += 1
            orphan_count += int(not protected and retained["state"] == "RETAINED")
        return {"target_type": "SERVICE_REQUEST", "target_id": sr_id, "target_revision": sr_revision,
            "summary": summary, "closed_link_count": closed_count, "orphaned_communication_count": orphan_count,
            "impact_fingerprint": digest.hexdigest()}

    def _status_event(self, uow, sr_id, sr_revision, event_id, context, *, terminal):
        event = self._identities.sr_status_event(uow, sr_id, sr_revision, event_id)
        if (event is None or not event["current"] or event["terminal"] is not terminal
                or event["command_id"] != context["command_id"] or (not terminal and not event["reviewed_correction"])):
            raise SomaError("COMM_TARGET_STALE", "SR governing status evidence is unavailable or changed")
        return event

    def apply_terminal_transition(self, uow, sr_id, sr_revision, terminal_event_id, command_context):
        context = _context(uow, command_context)
        event = self._status_event(uow, sr_id, sr_revision, terminal_event_id, context, terminal=True)
        existing = frozen_in_reader(uow, "SERVICE_REQUEST", sr_id, governing_event_id=terminal_event_id)
        if existing is not None:
            return ({"type": "communication_terminal_summary", "id": existing["terminal_summary_id"]},)
        impact = self.preview_terminal_transition(uow, sr_id, sr_revision)
        if impact == "INDETERMINATE":
            raise SomaError("DEPENDENCY_INDETERMINATE", "SR terminal Communication impact is unavailable")
        now, command = event["recorded_at_utc"], context["command_id"]
        frozen = freeze_in_uow(uow, impact["summary"], terminal_event_id, now)
        grace = self._settings.get_in_reader(uow, GRACE_KEY).value
        closed_count = orphan_count = 0
        for row in _links(uow, "SERVICE_REQUEST", sr_id):
            _, link_event = close_link(uow, row, now=now, command_id=command, reason="SR_TERMINAL")
            transition = reconcile_retention(uow, row["communication_id"], dependency_event_id=link_event,
                event_time=now, grace_minutes=grace, command_id=command)
            closed_count += 1
            orphan_count += int(transition is not None and transition.to_state == "ORPHAN_PENDING_PURGE")
        if (closed_count, orphan_count) != (impact["closed_link_count"], impact["orphaned_communication_count"]):
            raise IntegrityFailure("SR terminal Communication consequence counts changed inside the writer")
        self._audit.write(uow, audit_event("communications.terminal_unlinked", command_id=command,
            actor_kind=context["actor_kind"], actor_id=context["actor_id"], target_type="communication_terminal_summary",
            target_id=frozen["terminal_summary_id"], payload={"target_type": "SERVICE_REQUEST", "target_id": sr_id,
                "governing_event_id": terminal_event_id, "closed_link_count": closed_count, "orphaned_communication_count": orphan_count},
            refs=(AuditResultRef("communication_terminal_summary", frozen["terminal_summary_id"]),)))
        return ({"type": "communication_terminal_summary", "id": frozen["terminal_summary_id"]},)
    def apply_terminal_reversal(self, uow, sr_id, sr_revision, reversal_event_id, command_context):
        context = _context(uow, command_context)
        event = self._status_event(uow, sr_id, sr_revision, reversal_event_id, context, terminal=False)
        if self._identities.validate_reassociation(uow, "SERVICE_REQUEST", sr_id, sr_revision) != "VALID":
            raise SomaError("COMM_TARGET_STALE", "SR is not eligible for governed reassociation")
        frozen = frozen_in_reader(uow, "SERVICE_REQUEST", sr_id)
        if frozen is None:
            return ()
        prior = self._identities.sr_status_event(uow, sr_id, sr_revision, frozen["governing_event_id"])
        if prior is None or not prior["terminal"]:
            raise IntegrityFailure("SR frozen summary lost its accepted governing evidence")
        now, command = event["recorded_at_utc"], context["command_id"]
        actor = {"actor_kind": context["actor_kind"], "actor_id": context["actor_id"]}
        grace = self._settings.get_in_reader(uow, GRACE_KEY).value
        restored = cancelled = reconstruction = 0
        for row in _links(uow, "SERVICE_REQUEST", sr_id, state="CLOSED", terminal_command=prior["command_id"]):
            if active_link(uow, row["communication_id"], "SERVICE_REQUEST", sr_id) is not None:
                continue
            message = one(uow, "SELECT communication_id,source_scope_id,content_state,chronology_known,chronology_utc,chronology_source_kind "
                "FROM communications WHERE communication_id=?", (row["communication_id"],))
            if message is None:
                raise IntegrityFailure("SR reversal lost minimized canonical evidence")
            if message["content_state"] == "PURGED":
                reconstruction += 1
                self._reconstruction.request_in_uow(uow, message, "SERVICE_REQUEST", sr_id, sr_revision, reversal_event_id, context)
                continue
            link_event, revision = new_uuid4(), row["revision"] + 1
            updated = uow.connection.execute("UPDATE communication_links SET state='ACTIVE',revision=?,closed_at_utc=NULL,close_reason=NULL "
                "WHERE communication_link_id=? AND revision=? AND state='CLOSED'", (revision, row["communication_link_id"], row["revision"]))
            if updated.rowcount != 1:
                raise SomaError("COMM_STALE", "SR reversal link evidence changed")
            uow.connection.execute("INSERT INTO communication_link_events VALUES(?,?,'RESTORED',?,?, 'SR_REVIEWED_REVERSAL',?,?)",
                (link_event, row["communication_link_id"], row["revision"], revision, now, command))
            transition = reconcile_retention(uow, row["communication_id"], dependency_event_id=link_event,
                event_time=now, grace_minutes=grace, command_id=command)
            restored += 1
            if transition is not None and transition.to_state == "RETAINED":
                cancelled += 1
                self._audit.write(uow, audit_event("communications.orphan_grace.cancelled", command_id=command, **actor,
                    target_type="communication", target_id=row["communication_id"],
                    payload={"retention_revision": transition.new_revision, "reason_code": "PROTECTED_DEPENDENCY_RESTORED"},
                    refs=(AuditResultRef("communication", row["communication_id"]), AuditResultRef("communication_retention_event", transition.event_id))))
        if restored or reconstruction:
            self._audit.write(uow, audit_event("communications.terminal_links.restored", command_id=command, **actor,
                target_type="communication_terminal_summary", target_id=frozen["terminal_summary_id"],
                payload={"target_type": "SERVICE_REQUEST", "target_id": sr_id, "governing_event_id": reversal_event_id,
                    "restored_link_count": restored, "cancelled_grace_count": cancelled, "reconstruction_required_count": reconstruction},
                refs=(AuditResultRef("communication_terminal_summary", frozen["terminal_summary_id"]),)))
        return ({"type": "communication_terminal_summary", "id": frozen["terminal_summary_id"]},)


# Both terminal provider surfaces remain at the packet's declared application
# module. The RFC helper owns its separate bounded cascade implementation.
from soma.communications.services.rfc_terminal import RfcTerminalCommunicationParticipant
