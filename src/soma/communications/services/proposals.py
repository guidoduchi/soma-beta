from __future__ import annotations

import re

from soma.foundation.application.command_boundary import CommandBoundary, CommandEnvelope, PreparedMutation
from soma.foundation.audit.writer import AuditResultRef, AuditWriter
from soma.foundation.errors import IntegrityFailure, SomaError, ValidationError
from soma.foundation.identifiers import new_uuid4, require_uuid4, utc_epoch_seconds
from soma.foundation.strict_json import canonical_json_bytes, sha256_canonical_json
from soma.foundation.persistence.uow import ReadSnapshot

from soma.communications.audit_registry import audit_event, build_communications_audit_registry
from soma.communications.contracts.common import TARGET_TYPES, TrackableIdentity, UNKNOWN_CHRONOLOGY, closed, fingerprint, integer, text
from soma.communications.contracts.proposal import CommunicationProposalContractRegistry
from soma.communications.repositories.sources import one
from soma.communications.repositories.links import active_link, close_link, create_link, require_retained_message
from soma.communications.services.retention import dependency_fingerprint, reconcile_retention, retention
from soma.communications.services.settings import CommunicationSettingsService
from soma.communications.settings import GRACE_KEY

_REASON = re.compile(r"[A-Z][A-Z0-9_]{0,63}")


def reason_code(value):
    if not isinstance(value, str) or _REASON.fullmatch(value) is None:
        raise ValidationError("Communication decision requires a bounded stable reason code")
    return value


def proposal(reader, proposal_id):
    return one(reader, "SELECT * FROM communication_proposals WHERE communication_proposal_id=?", (require_uuid4(proposal_id),))


def require_proposal(reader, proposal_id, revision, expected_fingerprint=None):
    integer(revision, minimum=1)
    if expected_fingerprint is not None:
        fingerprint(expected_fingerprint)
    row = proposal(reader, proposal_id)
    if row is None or row["revision"] != revision or (expected_fingerprint is not None and row["proposal_fingerprint"] != expected_fingerprint):
        raise SomaError("COMM_PROPOSAL_STALE", "Communication proposal authority changed")
    return row


def disposition_in_uow(uow, row, *, to_state, reason, command_id, now, grace_minutes, owner_refs_json=None):
    event_id = new_uuid4()
    revision = row["revision"] + 1
    updated = uow.connection.execute(
        "UPDATE communication_proposals SET state=?,revision=?,decided_at_utc=?,decision_reason_code=? "
        "WHERE communication_proposal_id=? AND revision=? AND state=?",
        (to_state, revision, now, reason, row["communication_proposal_id"], row["revision"], row["state"]),
    )
    if updated.rowcount != 1:
        raise IntegrityFailure("Communication proposal changed during disposition")
    uow.connection.execute(
        "INSERT INTO communication_proposal_events(communication_proposal_event_id,communication_proposal_id,"
        "from_state,to_state,reason_code,owner_result_refs_json,recorded_at_utc,command_id) VALUES (?,?,?,?,?,?,?,?)",
        (event_id, row["communication_proposal_id"], row["state"], to_state, reason, owner_refs_json, now, command_id),
    )
    transition = None
    if to_state != "DEFERRED":
        holds = uow.connection.execute(
            "UPDATE communication_protection_holds SET state='CLOSED',closed_at_utc=? "
            "WHERE communication_id=? AND hold_kind='PROPOSAL' AND owner_ref=? AND state='ACTIVE'",
            (now, row["communication_id"], row["communication_proposal_id"]),
        )
        if holds.rowcount != 1:
            raise IntegrityFailure("Actionable Communication proposal has no exact active protection hold")
        transition = reconcile_retention(uow, row["communication_id"], dependency_event_id=event_id,
                                         event_time=now, grace_minutes=grace_minutes, command_id=command_id)
    refs = (AuditResultRef("communication_proposal", row["communication_proposal_id"]),
            AuditResultRef("communication_proposal_event", event_id))
    if transition is not None:
        refs += (AuditResultRef("communication_retention_event", transition.event_id),)
    return revision, refs, transition


class CommunicationProposalService:
    def __init__(self, connection_factory, *, identity_providers=None, evidence_provider=None, clock=utc_epoch_seconds):
        self._factory = connection_factory
        self._clock = clock
        self._identities = identity_providers
        self._evidence = evidence_provider
        self._settings = CommunicationSettingsService(connection_factory).settings
        self._contracts = CommunicationProposalContractRegistry()
        self._boundary = CommandBoundary(connection_factory, AuditWriter(build_communications_audit_registry()))

    def decide_link(self, request, *, actor_kind="local_user", actor_id=None):
        value = closed(request, {"command_id", "proposal_id", "proposal_revision", "decision", "target_revision", "proposal_fingerprint", "reason_code"})
        command, identity = require_uuid4(value["command_id"]), require_uuid4(value["proposal_id"])
        revision = integer(value["proposal_revision"], minimum=1)
        target_revision = integer(value["target_revision"], minimum=1)
        expected, reason = fingerprint(value["proposal_fingerprint"]), reason_code(value["reason_code"])
        decision = value["decision"]
        if not isinstance(decision, str) or decision not in {"ACCEPT", "REJECT"}:
            raise ValidationError("Communication link decision is invalid")
        envelope = CommandEnvelope(command, "DecideCommunicationLink", "communication_proposal", identity,
            {"decision": decision, "target_revision": target_revision, "reason_code": reason},
            base_revisions={"proposal": revision}, authorizing_fingerprints={"proposal": expected})

        def prepare(uow):
            row = require_proposal(uow, identity, revision, expected)
            if not self._contracts.is_link_contract(row["proposal_contract_id"], row["proposal_contract_version"]):
                raise ValidationError("Domain proposals require their owning command")
            if row["target_revision"] != target_revision:
                raise SomaError("COMM_TARGET_STALE", "Communication proposal target revision changed")
            if decision == "REJECT" and row["state"] == "REJECTED" and row["decision_reason_code"] == reason:
                return PreparedMutation(True, None, None, response_schema="CommunicationMutationResultV1",
                    response={"status": "NO_CHANGE", "target_id": identity, "new_revision": revision, "result_refs": []})
            if row["state"] not in {"PENDING", "DEFERRED"}:
                raise SomaError("COMM_PROPOSAL_STALE", "Communication link proposal is no longer actionable")
            message = match = None
            if decision == "ACCEPT":
                message = require_retained_message(uow, row["communication_id"])
                if self._evidence is None or self._identities is None:
                    raise SomaError("COMM_TARGET_STALE", "Communication identity evidence provider is unavailable")
                evidence = self._evidence.get_for_owner_command(uow, identity, revision, expected)
                if not isinstance(evidence, dict):
                    raise SomaError("COMM_PROPOSAL_STALE", "Communication link evidence changed or is unavailable")
                match = evidence["payload"]
                current = TrackableIdentity(row["target_type"], row["target_id"], target_revision,
                    match["matched_identity_kind"], match["matched_identity_value"], UNKNOWN_CHRONOLOGY)
                if (self._identities.validate(uow, current) != "VALID" or
                    self._identities.validate_reassociation(uow, current.target_type, current.target_id, target_revision) != "VALID"):
                    raise SomaError("COMM_TARGET_STALE", "Communication target identity or reassociation eligibility changed")
                if active_link(uow, row["communication_id"], current.target_type, current.target_id) is not None:
                    raise SomaError("COMM_LINK_CONFLICT", "Communication already has an active link to this target")
            grace = self._settings.get_in_reader(uow, GRACE_KEY).value
            now = integer(self._clock())
            completed = []

            def apply(inner):
                link_refs = ()
                if decision == "ACCEPT":
                    link, event = create_link(inner, message, target_type=row["target_type"], target_id=row["target_id"],
                        target_revision=target_revision, match=match, origin="REVIEWED", now=now, command_id=command, reason=reason)
                    link_refs = (AuditResultRef("communication_link", link), AuditResultRef("communication_link_event", event))
                proposal_revision, refs, transition = disposition_in_uow(inner, row,
                    to_state="ACCEPTED" if decision == "ACCEPT" else "REJECTED", reason=reason, command_id=command,
                    now=now, grace_minutes=grace,
                    owner_refs_json=None if not link_refs else canonical_json_bytes([{"type": ref.result_type, "id": ref.result_id} for ref in link_refs]).decode("utf-8"))
                refs = link_refs + refs
                result_target = link_refs[0].result_id if link_refs else identity
                completed.append({"status": "APPLIED", "target_id": result_target,
                    "new_revision": 1 if link_refs else proposal_revision,
                    "result_refs": [{"type": ref.result_type, "id": ref.result_id} for ref in refs]})
                events = (audit_event("communications.link.decided", command_id=command,
                    target_type="communication_link" if link_refs else "communication_proposal", target_id=result_target,
                    payload={"decision": decision, "target_type": row["target_type"], "target_id": row["target_id"], "reason_code": reason},
                    refs=refs, actor_kind=actor_kind, actor_id=actor_id),)
                if transition is not None and transition.to_state == "RETAINED":
                    events += (audit_event("communications.orphan_grace.cancelled", command_id=command, target_type="communication", target_id=row["communication_id"],
                        payload={"retention_revision": transition.new_revision, "reason_code": "PROTECTED_DEPENDENCY_RESTORED"},
                        refs=(AuditResultRef("communication", row["communication_id"]), AuditResultRef("communication_retention_event", transition.event_id)),
                        actor_kind=actor_kind, actor_id=actor_id),)
                return events

            return PreparedMutation(False, "communication_proposal", identity, apply,
                response_schema="CommunicationMutationResultV1", response_factory=lambda inner: completed[0])

        return self._boundary.execute(envelope, prepare).response

    @staticmethod
    def _correction_request(request):
        value = dict(closed(request, {"link_id", "link_revision", "action", "new_target_type", "new_target_id", "new_target_revision",
                                    "matched_identity_kind", "matched_identity_value", "reason_code"}))
        require_uuid4(value["link_id"])
        integer(value["link_revision"], minimum=1)
        reason_code(value["reason_code"])
        target_fields = ("new_target_type", "new_target_id", "new_target_revision", "matched_identity_kind", "matched_identity_value")
        if value["action"] == "CLOSE":
            if any(value[name] is not None for name in target_fields):
                raise ValidationError("Closing a Communication link has no replacement target fields")
        elif value["action"] == "RETARGET":
            if not isinstance(value["new_target_type"], str) or value["new_target_type"] not in TARGET_TYPES:
                raise ValidationError("Communication correction target type is invalid")
            require_uuid4(value["new_target_id"])
            integer(value["new_target_revision"], minimum=1)
            text(value["matched_identity_kind"], minimum=1, maximum=128)
            text(value["matched_identity_value"], minimum=1, maximum=512)
        else:
            raise ValidationError("Communication link correction action is invalid")
        return value

    def _correction_authority(self, reader, request):
        row = one(reader, "SELECT * FROM communication_links WHERE communication_link_id=?", (request["link_id"],))
        if row is None or row["revision"] != request["link_revision"] or row["state"] != "ACTIVE":
            raise SomaError("COMM_STALE", "Communication correction link changed")
        message = require_retained_message(reader, row["communication_id"])
        retained = retention(reader, row["communication_id"])
        if self._identities is None:
            raise SomaError("COMM_TARGET_STALE", "Communication correction identity provider is unavailable")
        old_revision = self._identities.current_revision(reader, row["target_type"], row["target_id"])
        new_revision = None
        if request["action"] == "RETARGET":
            target = TrackableIdentity(request["new_target_type"], request["new_target_id"], request["new_target_revision"],
                                      request["matched_identity_kind"], request["matched_identity_value"], UNKNOWN_CHRONOLOGY)
            new_revision = self._identities.current_revision(reader, target.target_type, target.target_id)
            if (new_revision != target.target_revision or self._identities.validate(reader, target) != "VALID" or
                self._identities.validate_reassociation(reader, target.target_type, target.target_id, target.target_revision) != "VALID"):
                raise SomaError("COMM_TARGET_STALE", "Communication replacement target changed or is ineligible")
            other = active_link(reader, row["communication_id"], target.target_type, target.target_id)
            if other is not None and other["communication_link_id"] != row["communication_link_id"]:
                raise SomaError("COMM_LINK_CONFLICT", "Communication replacement would duplicate a sibling link")
        token = sha256_canonical_json({"schema": "SOMA_COMM_LINK_CORRECTION_PREVIEW_V1", "request": request,
            "link": row, "message": message, "retention": retained,
            "old_target_current_revision": old_revision, "new_target_current_revision": new_revision,
            "dependency_fingerprint": dependency_fingerprint(reader, row["communication_id"])})
        return token, row, message

    def preview_link_correction(self, request):
        """Pure preflight helper; it grants no correction or lifecycle authority."""
        value = self._correction_request(request)
        with ReadSnapshot(self._factory) as reader:
            return self._correction_authority(reader, value)[0]

    def correct_link(self, request, *, actor_kind="local_user", actor_id=None):
        closed(request, {"command_id", "preview_fingerprint", "link_id", "link_revision", "action", "new_target_type",
                         "new_target_id", "new_target_revision", "matched_identity_kind", "matched_identity_value", "reason_code"})
        command = require_uuid4(request["command_id"])
        expected = fingerprint(request["preview_fingerprint"])
        value = self._correction_request({key: item for key, item in request.items() if key not in {"command_id", "preview_fingerprint"}})
        envelope = CommandEnvelope(command, "CorrectCommunicationLink", "communication_link", value["link_id"], value,
                                   base_revisions={"link": value["link_revision"]}, authorizing_fingerprints={"preview": expected})

        def prepare(uow):
            current, row, message = self._correction_authority(uow, value)
            if current != expected:
                raise SomaError("COMM_STALE", "Communication link correction preview changed")
            grace = self._settings.get_in_reader(uow, GRACE_KEY).value
            now = integer(self._clock())
            completed = []

            def apply(inner):
                revision, event = close_link(inner, row, now=now, command_id=command, reason=value["reason_code"], event_kind="CORRECTED")
                refs = (AuditResultRef("communication_link", row["communication_link_id"]), AuditResultRef("communication_link_event", event))
                if value["action"] == "RETARGET":
                    preserved = {**message, "direction": row["direction"], "chronology_known": row["effective_chronology_known"],
                                 "chronology_utc": row["effective_chronology_utc"], "chronology_source_kind": row["effective_chronology_source_kind"]}
                    match = {"matched_identity_kind": value["matched_identity_kind"], "matched_identity_value": value["matched_identity_value"],
                             "match_rule_id": "COMM_REVIEWED_MANUAL_V1", "match_rule_version": 1, "confidence_basis": "REVIEWED_MANUAL"}
                    link, link_event = create_link(inner, preserved, target_type=value["new_target_type"], target_id=value["new_target_id"],
                        target_revision=value["new_target_revision"], match=match, origin="MANUAL", now=now, command_id=command, reason=value["reason_code"])
                    refs += (AuditResultRef("communication_link", link), AuditResultRef("communication_link_event", link_event))
                transition = reconcile_retention(inner, row["communication_id"], dependency_event_id=event, event_time=now, grace_minutes=grace, command_id=command)
                if transition is not None:
                    refs += (AuditResultRef("communication_retention_event", transition.event_id),)
                completed.append({"status": "APPLIED", "target_id": row["communication_link_id"], "new_revision": revision,
                    "result_refs": [{"type": ref.result_type, "id": ref.result_id} for ref in refs]})
                events = (audit_event("communications.link.corrected", command_id=command, target_type="communication_link", target_id=row["communication_link_id"],
                    payload={"action": value["action"], "old_target_type": row["target_type"], "old_target_id": row["target_id"],
                             "new_target_type": value["new_target_type"], "new_target_id": value["new_target_id"], "reason_code": value["reason_code"]},
                    refs=refs, actor_kind=actor_kind, actor_id=actor_id),)
                if transition is not None and transition.to_state == "RETAINED":
                    events += (audit_event("communications.orphan_grace.cancelled", command_id=command, target_type="communication", target_id=row["communication_id"],
                        payload={"retention_revision": transition.new_revision, "reason_code": "PROTECTED_DEPENDENCY_RESTORED"},
                        refs=(AuditResultRef("communication", row["communication_id"]), AuditResultRef("communication_retention_event", transition.event_id)),
                        actor_kind=actor_kind, actor_id=actor_id),)
                return events

            return PreparedMutation(False, "communication_link", value["link_id"], apply,
                response_schema="CommunicationMutationResultV1", response_factory=lambda inner: completed[0])

        return self._boundary.execute(envelope, prepare).response

    def decide_domain_proposal(self, request: dict, *, actor_kind="local_user", actor_id=None) -> dict:
        value = closed(request, {"command_id", "proposal_id", "proposal_revision", "decision", "proposal_fingerprint", "reason_code"})
        command_id, identity = require_uuid4(value["command_id"]), require_uuid4(value["proposal_id"])
        revision = integer(value["proposal_revision"], minimum=1)
        expected = fingerprint(value["proposal_fingerprint"])
        reason = reason_code(value["reason_code"])
        decision = value["decision"]
        if not isinstance(decision, str) or decision not in {"REJECT", "DEFER"}:
            raise ValidationError("Communication domain proposal decision is invalid")
        envelope = CommandEnvelope(command_id, "DecideCommunicationDomainProposal", "communication_proposal", identity,
                                   {"decision": decision, "reason_code": reason}, base_revisions={"proposal": revision},
                                   authorizing_fingerprints={"proposal": expected})

        def prepare(uow):
            row = require_proposal(uow, identity, revision, expected)
            if self._contracts.is_link_contract(row["proposal_contract_id"], row["proposal_contract_version"]):
                raise ValidationError("Link proposals require the link-decision owner")
            final = "REJECTED" if decision == "REJECT" else "DEFERRED"
            if row["state"] == final and row["decision_reason_code"] == reason:
                return PreparedMutation(True, None, None, response_schema="CommunicationMutationResultV1",
                                        response={"status": "NO_CHANGE", "target_id": identity, "new_revision": revision, "result_refs": []})
            if row["state"] not in {"PENDING", "DEFERRED"} or (row["state"] == "DEFERRED" and final == "DEFERRED"):
                raise SomaError("COMM_PROPOSAL_STALE", "Communication proposal cannot take this decision")
            grace = self._settings.get_in_reader(uow, GRACE_KEY).value
            now = integer(self._clock())
            completed = []

            def apply(inner):
                updated_revision, refs, transition = disposition_in_uow(
                    inner, row, to_state=final, reason=reason, command_id=command_id, now=now, grace_minutes=grace,
                )
                completed.append((updated_revision, refs))
                events = (audit_event("communications.proposal.decided", command_id=command_id,
                                      actor_kind=actor_kind, actor_id=actor_id,
                                      target_type="communication_proposal", target_id=identity,
                                      payload={"decision": decision, "proposal_contract_id": row["proposal_contract_id"],
                                               "target_type": row["target_type"], "target_id": row["target_id"], "reason_code": reason}, refs=refs),)
                if transition is not None and transition.to_state == "RETAINED":
                    events += (audit_event("communications.orphan_grace.cancelled", command_id=command_id,
                                           actor_kind=actor_kind, actor_id=actor_id,
                                           target_type="communication", target_id=row["communication_id"],
                                           payload={"retention_revision": transition.new_revision, "reason_code": "PROTECTED_DEPENDENCY_RESTORED"}, refs=refs[-1:]),)
                return events

            def response(inner):
                updated_revision, refs = completed[0]
                return {"status": "APPLIED", "target_id": identity, "new_revision": updated_revision,
                        "result_refs": [{"type": ref.result_type, "id": ref.result_id} for ref in refs]}

            return PreparedMutation(False, "communication_proposal", identity, apply,
                                    response_schema="CommunicationMutationResultV1", response_factory=response)

        return self._boundary.execute(envelope, prepare).response
