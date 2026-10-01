"""Bounded job-owned historical progress; ordinary high-water is untouched."""
from soma.foundation.errors import IntegrityFailure
from soma.foundation.identifiers import new_uuid4
from soma.foundation.strict_json import canonical_json_bytes

from soma.communications.contracts.common import UNKNOWN_CHRONOLOGY
from soma.communications.contracts.jobs import bound_from_value
from soma.communications.repositories.sources import one


def segment(reader, claim, folder_id, checkpoint):
    ids = () if checkpoint is None else checkpoint.coverage_segment_ids
    if len(ids) > 64:
        raise IntegrityFailure("Historical progress exceeds its selected-folder bound")
    if not ids:
        return None
    rows = reader.connection.execute(
        "SELECT * FROM communication_historical_coverage_segments WHERE coverage_segment_id IN ("
        + ",".join("?" for _ in ids) + ") AND source_folder_id=?", (*ids, folder_id)).fetchall()
    if len(rows) > 1:
        raise IntegrityFailure("Historical job has duplicated folder progress")
    if not rows:
        return None
    row = one(reader, "SELECT * FROM communication_historical_coverage_segments WHERE coverage_segment_id=?", (rows[0][0],))
    if row["job_id"] != claim.job_id:
        raise IntegrityFailure("Historical checkpoint crossed its owning job")
    return row


def position(row):
    if row is None or row["state"] == "BOUNDED_COMPLETE":
        return None
    from soma.communications.services.processing_batches import load
    from soma.communications.contracts.source import ProviderCheckpoint
    bound = bound_from_value(load(row["upper_bound_json"]))
    return bound if isinstance(bound, ProviderCheckpoint) else None


def write(reader, claim, scope, folder_id, checkpoint, *, now, lower, upper, state):
    previous = segment(reader, claim, folder_id, checkpoint)
    ids = () if checkpoint is None else checkpoint.coverage_segment_ids
    encode = lambda value: canonical_json_bytes((value or UNKNOWN_CHRONOLOGY).to_response()).decode("utf-8")
    if previous is None:
        identity = new_uuid4()
        reader.connection.execute("INSERT INTO communication_historical_coverage_segments VALUES(?,?,?,?,?,?,?,?)",
            (identity, scope.source_scope_id, folder_id, encode(lower), encode(upper), state, claim.job_id, now))
        ids += (identity,)
    else:
        reader.connection.execute("UPDATE communication_historical_coverage_segments SET lower_bound_json=?,upper_bound_json=?,state=?,recorded_at_utc=? WHERE coverage_segment_id=?",
            (encode(lower), encode(upper), state, now, previous["coverage_segment_id"]))
    return ids
