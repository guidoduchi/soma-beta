from __future__ import annotations

from soma.foundation.audit.writer import AuditResultRef, AuditWriter
from soma.foundation.errors import IntegrityFailure, SomaError, ValidationError
from soma.foundation.identifiers import require_uuid4, utc_epoch_seconds
from soma.foundation.strict_json import canonical_json_bytes_bounded

from soma.communications.audit_registry import audit_event, build_communications_audit_registry
from soma.communications.contracts.common import closed, integer, text
from soma.communications.contracts.proposal import CommunicationProposalContractRegistry
from soma.communications.domain.proposals import source_fingerprint
from soma.communications.repositories.sources import one, scope
from soma.communications.services.proposals import disposition_in_uow, reason_code, require_proposal
from soma.communications.services.settings import CommunicationSettingsService
from soma.communications.settings import GRACE_KEY


class CommunicationProposalDispositionParticipant:
    """Disposition under the owning caller's receipt, writer UoW and result.

    The caller validates owner evidence before performing its own mutation.
    Disposition then validates unchanged Communications authority without asking
    the already-mutated owner to still have its former revision.
    """

    def __init__(self, connection_factory, *, clock=utc_epoch_seconds):
        self._settings = CommunicationSettingsService(connection_factory).settings
        self._contracts = CommunicationProposalContractRegistry()
        self._writer = AuditWriter(build_communications_audit_registry())
        self._clock = clock

    def _record(self, uow, proposal_id, proposal_revision, *, accepted, reason, owner_refs, command_context):
        context = closed(command_context, {"command_id", "actor_kind", "actor_id"})
        command_id = require_uuid4(context["command_id"])
        text(context["actor_kind"], minimum=1, maximum=128)
        if context["actor_id"] is not None:
            text(context["actor_id"], minimum=1, maximum=128)
        if uow.connection.execute("SELECT 1 FROM command_receipts WHERE command_id=?", (command_id,)).fetchone() is None:
            raise IntegrityFailure("Communication disposition requires the owning caller receipt")
        row = require_proposal(uow, proposal_id, proposal_revision)
        if row["state"] not in {"PENDING", "DEFERRED"}:
            raise SomaError("COMM_PROPOSAL_STALE", "Communication proposal is no longer actionable")
        owner = self._contracts.owner_for(row["proposal_contract_id"], row["proposal_contract_version"])
        if owner == "LLD-09":
            raise ValidationError("Link proposal disposition belongs to the link-decision command")
        if accepted:
            message = one(uow, "SELECT communication_id,source_scope_id,identity_state,provider_identity_digest,fallback_digest,"
                          "fallback_version,content_revision,direction,chronology_known,chronology_utc,chronology_source_kind,content_state "
                          "FROM communications WHERE communication_id=?", (row["communication_id"],))
            source = None if message is None else scope(uow, message["source_scope_id"])
            if message is None or source is None:
                raise IntegrityFailure("Communication proposal lost its source authority")
            if message["content_state"] != "RETAINED" or source_fingerprint(message, source["revision"]) != row["source_fingerprint"]:
                raise SomaError("COMM_PROPOSAL_STALE", "Communication source authority changed")
        if not isinstance(owner_refs, (list, tuple)) or (accepted and not owner_refs):
            raise ValidationError("Accepted Communication proposal requires immutable owner result refs")
        refs = []
        for raw in owner_refs:
            item = closed(raw, {"type", "id"})
            refs.append({"type": text(item["type"], minimum=1, maximum=128), "id": require_uuid4(item["id"])})
        owner_json = canonical_json_bytes_bounded(refs, max_bytes=65_536, max_depth=4, max_collection_items=512).decode()
        now = integer(self._clock())
        grace = self._settings.get_in_reader(uow, GRACE_KEY).value
        _, result_refs, transition = disposition_in_uow(
            uow, row, to_state="ACCEPTED" if accepted else "REJECTED", reason=reason, command_id=command_id,
            now=now, grace_minutes=grace, owner_refs_json=owner_json if accepted else None,
        )
        actor = {"actor_kind": context["actor_kind"], "actor_id": context["actor_id"]}
        if accepted:
            event = audit_event("communications.proposal.owner_accepted", command_id=command_id,
                                target_type="communication_proposal", target_id=proposal_id,
                                payload={"proposal_contract_id": row["proposal_contract_id"], "owner_packet": owner, "owner_result_count": len(refs)},
                                refs=result_refs + tuple(AuditResultRef(item["type"], item["id"]) for item in refs), **actor)
        else:
            event = audit_event("communications.proposal.decided", command_id=command_id,
                                target_type="communication_proposal", target_id=proposal_id,
                                payload={"decision": "REJECT", "proposal_contract_id": row["proposal_contract_id"],
                                         "target_type": row["target_type"], "target_id": row["target_id"], "reason_code": reason}, refs=result_refs, **actor)
        self._writer.write(uow, event)
        if transition is not None and transition.to_state == "RETAINED":
            self._writer.write(uow, audit_event("communications.orphan_grace.cancelled", command_id=command_id,
                               target_type="communication", target_id=row["communication_id"],
                               payload={"retention_revision": transition.new_revision, "reason_code": "PROTECTED_DEPENDENCY_RESTORED"},
                               refs=(AuditResultRef("communication", row["communication_id"]), result_refs[-1]), **actor))
        return tuple({"type": ref.result_type, "id": ref.result_id} for ref in result_refs)

    def record_accepted(self, uow, proposal_id, proposal_revision, owner_result_refs, command_context):
        return self._record(uow, proposal_id, proposal_revision, accepted=True, reason="OWNER_ACCEPTED",
                            owner_refs=owner_result_refs, command_context=command_context)

    def record_rejected(self, uow, proposal_id, proposal_revision, reason_code_value, command_context):
        return self._record(uow, proposal_id, proposal_revision, accepted=False, reason=reason_code(reason_code_value),
                            owner_refs=(), command_context=command_context)
