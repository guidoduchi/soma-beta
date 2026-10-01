"""Owned proposal writes in the processing caller's receipt and UnitOfWork.

The caller revalidates matching, owner targets/memberships and source facts.
This repository neither extracts lifecycle facts nor invokes owner commands.
The caller also reconciles retention and emits its required batch audit before
committing; this helper never commits or opens another command boundary.
"""
from __future__ import annotations

from dataclasses import dataclass

from soma.foundation.errors import IntegrityFailure, SomaError, ValidationError
from soma.foundation.identifiers import new_uuid4, require_uuid4

from soma.communications.contracts.common import integer
from soma.communications.contracts.proposal import CommunicationProposalContractRegistry, ValidatedProposalPayload
from soma.communications.domain.proposals import proposal_fingerprint, source_fingerprint
from soma.communications.repositories.sources import one


@dataclass(frozen=True, slots=True)
class ProposalWrite:
    proposal_id: str
    revision: int
    state: str
    created: bool
    creation_event_id: str | None = None
    protection_hold_id: str | None = None


def insert_pending(uow, communication_id, *, source_revision, target_id, target_revision,
                   payload: ValidatedProposalPayload, now, command_id) -> ProposalWrite:
    """Insert one reviewed proposal/hold/event, or reuse exact prior evidence.

    Reinspection cannot reopen a decided proposal or duplicate its active hold.
    A fingerprint hit still compares the complete stored facts. Source freshness
    and retained content are read in the caller's writer snapshot; operational
    owner eligibility remains the caller's declared provider responsibility.
    """
    require_uuid4(communication_id)
    require_uuid4(target_id)
    require_uuid4(command_id)
    integer(source_revision, minimum=1)
    integer(target_revision, minimum=1)
    integer(now)
    if not isinstance(payload, ValidatedProposalPayload):
        raise ValidationError("Communication proposal requires a registered typed payload")
    # A public dataclass constructor is not proof that validation occurred.
    registered = CommunicationProposalContractRegistry().validate(
        payload.contract_id, payload.contract_version, payload.target_type, payload.to_value())
    if registered != payload:
        raise ValidationError("Communication proposal payload differs from its registered contract")
    if one(uow, "SELECT 1 FROM command_receipts WHERE command_id=?", (command_id,)) is None:
        raise IntegrityFailure("Communication proposal creation requires the caller receipt")
    message = one(uow, "SELECT c.communication_id,c.source_scope_id,c.identity_state,c.provider_identity_digest,"
        "c.fallback_digest,c.fallback_version,c.content_revision,c.direction,c.chronology_known,c.chronology_utc,"
        "c.chronology_source_kind,c.content_state,s.revision AS source_revision "
        "FROM communications c JOIN communication_source_scopes s USING(source_scope_id) WHERE c.communication_id=?",
        (communication_id,))
    if message is None:
        raise IntegrityFailure("Communication proposal lost its canonical source")
    if message["source_revision"] != source_revision:
        raise SomaError("COMM_STALE", "Communication proposal source configuration changed")
    if message["content_state"] != "RETAINED":
        raise SomaError("COMM_CONTENT_PURGED", "Communication proposal source content is unavailable")
    if payload.contract_id == "COMM_INVENTORY_SUBMISSION_V1" and message["direction"] != "SENT":
        raise ValidationError("Communication submission proposal requires observed sent evidence")
    source = source_fingerprint(message, source_revision)
    exact = proposal_fingerprint(source, target_id, target_revision, payload)
    prior = one(uow, "SELECT * FROM communication_proposals WHERE communication_id=? AND target_type=? "
        "AND target_id=? AND proposal_contract_id=? AND proposal_fingerprint=?",
        (communication_id, payload.target_type, target_id, payload.contract_id, exact))
    if prior is not None:
        if (prior["target_revision"] != target_revision or prior["proposal_contract_version"] != payload.contract_version
                or prior["source_fingerprint"] != source or prior["payload_json"] != payload.canonical_json):
            raise IntegrityFailure("Communication proposal fingerprint conflicts with exact stored evidence")
        active_holds = uow.connection.execute("SELECT protection_hold_id FROM communication_protection_holds "
            "WHERE communication_id=? AND hold_kind='PROPOSAL' AND owner_ref=? AND state='ACTIVE' LIMIT 2",
            (communication_id, prior["communication_proposal_id"])).fetchall()
        if len(active_holds) != (1 if prior["state"] in {"PENDING", "DEFERRED"} else 0):
            raise IntegrityFailure("Communication proposal protection disagrees with its disposition")
        return ProposalWrite(prior["communication_proposal_id"], prior["revision"], prior["state"], False)
    identity, event, hold = new_uuid4(), new_uuid4(), new_uuid4()
    uow.connection.execute("INSERT INTO communication_proposals(communication_proposal_id,communication_id,"
        "target_type,target_id,target_revision,proposal_contract_id,proposal_contract_version,payload_json,"
        "source_fingerprint,proposal_fingerprint,state,revision,created_at_utc) VALUES(?,?,?,?,?,?,?,?,?,?,'PENDING',1,?)",
        (identity, communication_id, payload.target_type, target_id, target_revision, payload.contract_id,
         payload.contract_version, payload.canonical_json, source, exact, now))
    uow.connection.execute("INSERT INTO communication_protection_holds(protection_hold_id,communication_id,"
        "hold_kind,owner_ref,state,created_at_utc) VALUES(?,?,'PROPOSAL',?,'ACTIVE',?)", (hold, communication_id, identity, now))
    uow.connection.execute("INSERT INTO communication_proposal_events(communication_proposal_event_id,"
        "communication_proposal_id,from_state,to_state,reason_code,recorded_at_utc,command_id) "
        "VALUES(?,?,NULL,'PENDING','REVIEW_REQUIRED',?,?)", (event, identity, now, command_id))
    return ProposalWrite(identity, 1, "PENDING", True, event, hold)
