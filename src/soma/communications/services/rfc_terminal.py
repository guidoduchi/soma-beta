from __future__ import annotations

import hashlib
from heapq import merge
from itertools import islice, zip_longest

from soma.foundation.audit.writer import AuditResultRef, AuditWriter
from soma.foundation.errors import IntegrityFailure, SomaError, ValidationError
from soma.foundation.identifiers import require_uuid4
from soma.foundation.persistence.uow import ReadSnapshot
from soma.foundation.strict_json import canonical_json_bytes
from soma.tickets.queries.rfc_terminal_cascade import (
    RfcTerminalCascadeImpactItem, RfcTerminalCascadeImpactProviderPage, RfcTerminalCascadeProposalSnapshot,
)
from soma.tickets.rfc_terminal_review import RfcTerminalCascadeExecutionCommandContext, RfcTerminalCascadeParticipantApplyResult

from soma.communications.audit_registry import audit_event, build_communications_audit_registry
from soma.communications.contracts.common import fingerprint, integer
from soma.communications.queries.summaries import live_summary_in_reader
from soma.communications.repositories import cascade, terminal_work
from soma.communications.repositories.links import close_link
from soma.communications.repositories.summaries import freeze_in_uow, frozen_in_reader
from soma.communications.services.dependencies import classify_target_dependency
from soma.communications.services.retention import dependency_fingerprint, reconcile_retention
from soma.communications.services.settings import CommunicationSettingsService
from soma.communications.settings import GRACE_KEY

_KINDS = ("ORPHAN_GRACE_EVALUATION", "RFC_DIRECT_LINK_CLOSE", "RFC_TERMINAL_SUMMARY_FREEZE")


class RfcTerminalCommunicationParticipant:
    def __init__(self, connection_factory, identity_providers):
        self._identities = identity_providers
        self._settings = CommunicationSettingsService(connection_factory).settings
        self._audit = AuditWriter(build_communications_audit_registry())

    @staticmethod
    def classify_hard_delete_dependency(reader, rfc_id):
        return classify_target_dependency(reader, "RFC", rfc_id)

    def _authority(self, reader, proposal):
        if not isinstance(proposal, RfcTerminalCascadeProposalSnapshot) or not proposal.rfc_members:
            raise ValidationError("Communication cascade requires the exact owner proposal snapshot")
        require_uuid4(proposal.proposal_id)
        integer(proposal.proposal_revision, minimum=1)
        fingerprint(proposal.scope_fingerprint)
        # The owner exports trigger first, then UUID-sorted children. Merge the
        # two immutable streams without copying an unbounded scope into a map.
        expected = merge(proposal.rfc_members[:1], islice(proposal.rfc_members, 1, None), key=lambda item: item.rfc_id)
        for member, actual in zip_longest(expected, cascade.members(reader, proposal)):
            if (member is None or actual is None or (member.rfc_id, member.captured_rfc_revision, member.captured_role) != tuple(actual)
                    or self._identities.validate_revision(reader, "RFC", member.rfc_id, member.captured_rfc_revision) != "VALID"):
                raise SomaError("COMM_TARGET_STALE", "Communication cascade owner membership changed")

    def _metadata(self, reader, proposal):
        key = (proposal.proposal_id, proposal.proposal_revision, proposal.scope_fingerprint)
        # This bounded pair belongs to the passed read snapshot, never to the
        # provider or process. Writer revalidation always recomputes authority.
        cached = getattr(reader, "_communication_cascade_metadata", None) if isinstance(reader, ReadSnapshot) else None
        if cached is not None and cached[0] == key:
            return cached[1]
        self._authority(reader, proposal)
        grace = self._settings.get_in_reader(reader, GRACE_KEY)
        digest = hashlib.sha256(b"SOMA_COMM_RFC_TERMINAL_IMPACT_V1\x00")
        digest.update(canonical_json_bytes([*key, proposal.terminal_epoch_id, proposal.terminal_status_class,
            proposal.terminal_status_evidence_id, grace.revision, grace.value]))
        count = 0
        for rfc_id, revision, role in cascade.members(reader, proposal):
            summary = live_summary_in_reader(reader, self._identities, "RFC", rfc_id)
            encoded = canonical_json_bytes(["SUMMARY", rfc_id, revision, role, summary])
            digest.update(len(encoded).to_bytes(8, "big"))
            digest.update(encoded)
            count += 1
        for row in cascade.scoped_links(reader, proposal):
            encoded = canonical_json_bytes(["LINK", row])
            digest.update(len(encoded).to_bytes(8, "big"))
            digest.update(encoded)
            count += 1
        for row in cascade.affected_messages(reader, proposal):
            if row[2] != "RETAINED" or row[3] != "RETAINED":
                raise IntegrityFailure("Communication cascade has inconsistent protected retention evidence")
            encoded = canonical_json_bytes(["ORPHAN", list(row), dependency_fingerprint(reader, row[0])])
            digest.update(len(encoded).to_bytes(8, "big"))
            digest.update(encoded)
            count += 1
        result = count, digest.hexdigest()
        if isinstance(reader, ReadSnapshot):
            reader._communication_cascade_metadata = key, result
        return result

    def preview_terminal_cascade(self, snapshot, proposal_snapshot, after_key=None, limit=500):
        integer(limit, minimum=1, maximum=500)
        if after_key is not None:
            if not isinstance(after_key, tuple) or len(after_key) != 2 or after_key[0] not in _KINDS:
                raise ValidationError("Communication cascade continuation is invalid")
            require_uuid4(after_key[1])
        try:
            count, token = self._metadata(snapshot, proposal_snapshot)
        except (SomaError, IntegrityFailure):
            return RfcTerminalCascadeImpactProviderPage("COMMUNICATIONS", "INDETERMINATE", None, None,
                warning_code="COMM_TERMINAL_IMPACT_INDETERMINATE")
        items = []
        for kind in _KINDS:
            if after_key is not None and kind < after_key[0]:
                continue
            after = after_key[1] if after_key is not None and kind == after_key[0] else ""
            remaining = limit + 1 - len(items)
            if kind == "ORPHAN_GRACE_EVALUATION":
                values = (RfcTerminalCascadeImpactItem("COMMUNICATIONS", kind, "COMMUNICATION", row[0],
                    current_state="RETAINED", resulting_state="RETAINED" if row[5] + row[6] - row[7] else "ORPHAN_PENDING_PURGE",
                    current_count=row[5] + row[6], resulting_count=row[5] + row[6] - row[7])
                    for row in cascade.affected_messages(snapshot, proposal_snapshot, after=after, limit=remaining))
            elif kind == "RFC_DIRECT_LINK_CLOSE":
                values = (RfcTerminalCascadeImpactItem("COMMUNICATIONS", kind, "COMMUNICATION_LINK", row["communication_link_id"],
                    current_state="active", resulting_state="closed")
                    for row in cascade.scoped_links(snapshot, proposal_snapshot, after=after, limit=remaining))
            else:
                values = (RfcTerminalCascadeImpactItem("COMMUNICATIONS", kind, "RFC", row[0], current_state="live", resulting_state="frozen")
                    for row in snapshot.connection.execute(
                        f"SELECT rfc_id FROM {cascade.MEMBERS} WHERE proposal_id=? AND proposal_revision=? AND rfc_id>? ORDER BY rfc_id LIMIT ?",
                        (proposal_snapshot.proposal_id, proposal_snapshot.proposal_revision, after, remaining)))
            items.extend(values)
            if len(items) > limit:
                break
        continuation = (items[limit - 1].impact_kind, items[limit - 1].entity_id) if len(items) > limit else None
        return RfcTerminalCascadeImpactProviderPage("COMMUNICATIONS", "READY", count, token, tuple(items[:limit]), continuation)

    def revalidate_terminal_cascade(self, uow, proposal_snapshot, reviewed_exact_count, reviewed_provider_fingerprint):
        integer(reviewed_exact_count)
        fingerprint(reviewed_provider_fingerprint)
        uow._communication_cascade_revalidation = None
        try:
            current = self._metadata(uow, proposal_snapshot)
        except (SomaError, IntegrityFailure):
            return "INDETERMINATE"
        if current != (reviewed_exact_count, reviewed_provider_fingerprint):
            return "STALE"
        uow._communication_cascade_revalidation = (proposal_snapshot.proposal_id, proposal_snapshot.proposal_revision,
            proposal_snapshot.scope_fingerprint, current)
        return "READY"

    def apply_terminal_cascade(self, uow, proposal_snapshot, command_context):
        from soma.communications.services.terminal import _context, _links
        if not isinstance(command_context, RfcTerminalCascadeExecutionCommandContext):
            raise ValidationError("Communication cascade requires the owning execution context")
        now = integer(command_context.accepted_execution_utc)
        context = _context(uow, {"command_id": command_context.command_id,
            "actor_kind": command_context.actor_kind, "actor_id": command_context.actor_id})
        receipt = uow.connection.execute("SELECT command_type,target_type,target_id FROM command_receipts WHERE command_id=?",
            (context["command_id"],)).fetchone()
        if receipt != ("ExecuteRfcTerminalCascade", "rfc_terminal_cascade_proposal", proposal_snapshot.proposal_id):
            raise IntegrityFailure("Communication cascade requires the exact owning execution receipt")
        sealed = getattr(uow, "_communication_cascade_revalidation", None)
        expected = (proposal_snapshot.proposal_id, proposal_snapshot.proposal_revision, proposal_snapshot.scope_fingerprint)
        if sealed is None or sealed[:3] != expected or self._metadata(uow, proposal_snapshot) != sealed[3]:
            raise SomaError("COMM_TARGET_STALE", "Communication cascade apply lost current reviewed authority")
        # One successful application per caller UoW. Eligible command replay is
        # the owner's receipt path, not a second execution of this participant.
        uow._communication_cascade_revalidation = None
        terminal_work.begin(uow)
        command = context["command_id"]
        grace = self._settings.get_in_reader(uow, GRACE_KEY).value
        # Freeze every scope member before closing any shared canonical message.
        for rfc_id, _, _ in cascade.members(uow, proposal_snapshot):
            if frozen_in_reader(uow, "RFC", rfc_id, governing_event_id=proposal_snapshot.proposal_id) is not None:
                raise IntegrityFailure("Pending cascade already has accepted Communication consequences")
            summary = live_summary_in_reader(uow, self._identities, "RFC", rfc_id)
            frozen = freeze_in_uow(uow, summary, proposal_snapshot.proposal_id, now)
            terminal_work.record(uow, "communication_terminal_summary", frozen["terminal_summary_id"], target_id=rfc_id)
        for rfc_id, _ in terminal_work.targets(uow):
            # The published membership was validated and these targets were
            # frozen above. Per-target keysets use the owned composite index;
            # do not repeatedly sort the entire cascade for each writer batch.
            for row in _links(uow, "RFC", rfc_id):
                _, event_id = close_link(uow, row, now=now, command_id=command, reason="RFC_TERMINAL_CASCADE")
                terminal_work.closed(uow, event_id, row["target_id"], row["communication_id"])
        # Evaluate each affected message exactly once after all scoped RFC links
        # close. External siblings and holds still participate in retention.
        for communication_id, dependency_event_id in terminal_work.messages(uow):
            transition = reconcile_retention(uow, communication_id, dependency_event_id=dependency_event_id,
                event_time=now, grace_minutes=grace, command_id=command)
            if transition is not None:
                if transition.to_state != "ORPHAN_PENDING_PURGE":
                    raise IntegrityFailure("Communication cascade produced an unexpected retention transition")
                terminal_work.record(uow, "communication_retention_event", transition.event_id, communication_id=communication_id)
        for rfc_id, summary_id in terminal_work.targets(uow):
            closed_count, orphan_count = terminal_work.target_counts(uow, rfc_id)
            event = audit_event("communications.terminal_unlinked", command_id=command,
                actor_kind=context["actor_kind"], actor_id=context["actor_id"],
                target_type="communication_terminal_summary", target_id=summary_id,
                payload={"target_type": "RFC", "target_id": rfc_id, "governing_event_id": proposal_snapshot.proposal_id,
                    "closed_link_count": closed_count, "orphaned_communication_count": orphan_count},
                refs=(AuditResultRef("communication_terminal_summary", summary_id),))
            self._audit.write(uow, event)
            terminal_work.record(uow, terminal_work.AUDIT_KIND, event.audit_event_id, target_id=rfc_id)
        result_count, audit_count, token = terminal_work.finish(uow, command, proposal_snapshot.proposal_id)
        return RfcTerminalCascadeParticipantApplyResult("COMMUNICATIONS", result_count, audit_count, token)
