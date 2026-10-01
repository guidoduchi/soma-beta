from __future__ import annotations

from soma.foundation.errors import IntegrityFailure, SomaError
from soma.foundation.identifiers import new_uuid4

from soma.communications.contracts.common import Chronology
from soma.communications.contracts.matching import validate_identity_confidence, validate_match_rule
from soma.communications.repositories.sources import one


def require_retained_message(reader, communication_id):
    message = one(reader, "SELECT communication_id,source_scope_id,direction,chronology_known,chronology_utc,chronology_source_kind,content_state,content_revision FROM communications WHERE communication_id=?", (communication_id,))
    if message is None:
        raise IntegrityFailure("Communication link lost its canonical message")
    if message["content_state"] != "RETAINED":
        raise SomaError("COMM_CONTENT_PURGED", "Communication content is unavailable")
    return message


def active_link(reader, communication_id, target_type, target_id):
    return one(reader, "SELECT communication_link_id,revision FROM communication_links WHERE communication_id=? AND target_type=? AND target_id=? AND state='ACTIVE'", (communication_id, target_type, target_id))


def create_link(uow, message, *, target_type, target_id, target_revision, match, origin, now, command_id, reason):
    validate_match_rule(match["match_rule_id"], match["match_rule_version"], match["confidence_basis"])
    validate_identity_confidence(match["matched_identity_kind"], match["confidence_basis"])
    if active_link(uow, message["communication_id"], target_type, target_id) is not None:
        raise SomaError("COMM_LINK_CONFLICT", "Communication already has an active link to this target")
    chronology = Chronology(bool(message["chronology_known"]), message["chronology_utc"], message["chronology_source_kind"])
    identity, event = new_uuid4(), new_uuid4()
    uow.connection.execute(
        "INSERT INTO communication_links(communication_link_id,communication_id,target_type,target_id,target_revision_at_link,"
        "matched_identity_kind,matched_identity_value,match_rule_id,match_rule_version,confidence_basis,direction,"
        "effective_chronology_known,effective_chronology_utc,effective_chronology_source_kind,origin,state,revision,created_at_utc) "
        "VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,'ACTIVE',1,?)",
        (identity, message["communication_id"], target_type, target_id, target_revision, match["matched_identity_kind"],
         match["matched_identity_value"], match["match_rule_id"], match["match_rule_version"], match["confidence_basis"],
         message["direction"], int(chronology.known), chronology.utc_epoch_seconds, chronology.source_kind, origin, now),
    )
    uow.connection.execute(
        "INSERT INTO communication_link_events(communication_link_event_id,communication_link_id,event_kind,prior_revision,new_revision,reason_code,recorded_at_utc,command_id) VALUES(?,?,'CREATED',NULL,1,?,?,?)",
        (event, identity, reason, now, command_id),
    )
    return identity, event


def close_link(uow, row, *, now, command_id, reason, event_kind="CLOSED"):
    event = new_uuid4()
    revision = row["revision"] + 1
    changed = uow.connection.execute(
        "UPDATE communication_links SET state='CLOSED',revision=?,closed_at_utc=?,close_reason=? "
        "WHERE communication_link_id=? AND revision=? AND state='ACTIVE'",
        (revision, now, reason, row["communication_link_id"], row["revision"]),
    )
    if changed.rowcount != 1:
        raise SomaError("COMM_STALE", "Communication link changed before closure")
    uow.connection.execute(
        "INSERT INTO communication_link_events(communication_link_event_id,communication_link_id,event_kind,prior_revision,new_revision,reason_code,recorded_at_utc,command_id) VALUES(?,?,?,?,?,?,?,?)",
        (event, row["communication_link_id"], event_kind, row["revision"], revision, reason, now, command_id),
    )
    return revision, event
