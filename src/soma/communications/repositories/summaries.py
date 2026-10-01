from __future__ import annotations

from soma.foundation.errors import IntegrityFailure, ValidationError
from soma.foundation.identifiers import new_uuid4, require_uuid4
from soma.foundation.strict_json import sha256_canonical_json

from soma.communications.contracts.common import Chronology, fingerprint, integer, text


def frozen_in_reader(reader, target_type, target_id, *, governing_event_id=None):
    if target_type not in {"SERVICE_REQUEST", "RFC"}:
        return None
    require_uuid4(target_id)
    condition, parameters = "target_type=? AND target_id=?", (target_type, target_id)
    if governing_event_id is not None:
        condition += " AND governing_event_id=?"
        parameters += (governing_event_id,)
    row = reader.connection.execute(
        "SELECT terminal_summary_id,governing_event_id,summary_revision,received_count,sent_count,unknown_count,"
        "last_interaction_known,last_interaction_utc,last_interaction_source_kind,last_direction,coverage_state,"
        "unlink_utc,summary_fingerprint FROM communication_terminal_summaries WHERE " + condition +
        " ORDER BY summary_revision DESC LIMIT 1", parameters,
    ).fetchone()
    if row is None:
        return None
    result = {"terminal_summary_id": row[0], "target_type": target_type, "target_id": target_id,
        "governing_event_id": row[1], "summary_revision": row[2], "received_count": row[3], "sent_count": row[4],
        "unknown_count": row[5], "last_interaction": Chronology(bool(row[6]), row[7], row[8]).to_response(),
        "last_direction": row[9], "coverage_state": row[10], "unlink_utc": row[11]}
    expected = sha256_canonical_json({"schema": "SOMA_COMM_FROZEN_SUMMARY_V1", **result})
    if fingerprint(row[12]) != expected:
        raise IntegrityFailure("Frozen Communication summary evidence is inconsistent")
    return {**result, "summary_fingerprint": row[12]}


def freeze_in_uow(uow, summary, governing_event_id, unlink_utc):
    """Called before unlink in the governing owner's outer writer transaction."""
    target_type, target_id = summary["target_type"], summary["target_id"]
    if target_type not in {"SERVICE_REQUEST", "RFC"}:
        raise ValidationError("Only governed SR/RFC terminal summaries can be frozen")
    require_uuid4(target_id)
    text(governing_event_id, minimum=1, maximum=512)
    integer(unlink_utc)
    previous = frozen_in_reader(uow, target_type, target_id, governing_event_id=governing_event_id)
    if previous is not None:
        return previous
    revision = uow.connection.execute(
        "SELECT coalesce(max(summary_revision),0)+1 FROM communication_terminal_summaries WHERE target_type=? AND target_id=?",
        (target_type, target_id),
    ).fetchone()[0]
    chronology = Chronology.from_value(summary["last_interaction"])
    result = {"terminal_summary_id": new_uuid4(), "target_type": target_type, "target_id": target_id,
        "governing_event_id": governing_event_id, "summary_revision": revision,
        "received_count": integer(summary["received_count"]), "sent_count": integer(summary["sent_count"]),
        "unknown_count": integer(summary["unknown_count"]), "last_interaction": chronology.to_response(),
        "last_direction": summary["last_direction"], "coverage_state": summary["coverage_state"], "unlink_utc": unlink_utc}
    result["summary_fingerprint"] = sha256_canonical_json({"schema": "SOMA_COMM_FROZEN_SUMMARY_V1", **result})
    uow.connection.execute(
        "INSERT INTO communication_terminal_summaries(terminal_summary_id,target_type,target_id,governing_event_id,"
        "received_count,sent_count,unknown_count,last_interaction_known,last_interaction_utc,last_direction,"
        "coverage_state,unlink_utc,summary_fingerprint,last_interaction_source_kind,summary_revision) "
        "VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)", (result["terminal_summary_id"], target_type, target_id, governing_event_id,
            result["received_count"], result["sent_count"], result["unknown_count"], int(chronology.known),
            chronology.utc_epoch_seconds, result["last_direction"], result["coverage_state"], unlink_utc,
            result["summary_fingerprint"], chronology.source_kind, revision),
    )
    return result
