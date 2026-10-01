from __future__ import annotations

from soma.communications.contracts.common import integer
from soma.communications.contracts.jobs import CommunicationJobCounters, JOB_KINDS
from soma.communications.contracts.queries import cursor_key, next_cursor
from soma.communications.jobs.communications import JOB_TYPES
from soma.foundation.errors import IntegrityFailure, ValidationError
from soma.foundation.identifiers import require_uuid4
from soma.foundation.persistence.uow import ReadSnapshot
from soma.foundation.queries.jobs import DURABLE_JOB_METADATA_V1

QUERY = "ListCommunicationJobs"
STATES = frozenset({"queued", "running", "waiting_review", "retry_wait", "completed", "failed", "cancelled"})
COUNTERS = tuple(CommunicationJobCounters().to_response())


def list_jobs_in_reader(reader, request):
    if not isinstance(request, dict) or set(request) - {"source_scope_id", "job_kind", "state", "cursor", "limit"}:
        raise ValidationError("Communication jobs query has unknown fields")
    filters = {name: request.get(name) for name in ("source_scope_id", "job_kind", "state")}
    if filters["source_scope_id"] is not None:
        require_uuid4(filters["source_scope_id"])
    for name, allowed in (("job_kind", JOB_KINDS), ("state", STATES)):
        if filters[name] is not None and (not isinstance(filters[name], str) or filters[name] not in allowed):
            raise ValidationError("Communication jobs query filter is invalid")
    limit = integer(request.get("limit", 50), minimum=1, maximum=100)
    key = cursor_key(request.get("cursor"), query=QUERY, filters=filters, null_order="none", key_length=2)
    conditions, values = [], []
    for name, column in (("source_scope_id", "s.source_scope_id"), ("job_kind", "s.job_kind"), ("state", "j.state")):
        if filters[name] is not None:
            conditions.append(f"{column}=?")
            values.append(filters[name])
    if key is not None:
        integer(key[0])
        require_uuid4(key[1])
        conditions.append("(j.created_at_utc,j.job_id)<(?,?)")
        values.extend(key)
    where = " WHERE " + " AND ".join(conditions) if conditions else ""
    # Page first. Attempt evidence and counters are read only for this bounded
    # set; no payload/checkpoint/claim identifiers enter the consumer projection.
    rows = reader.connection.execute(
        "WITH page AS MATERIALIZED (SELECT s.job_id,s.source_scope_id,s.job_kind,j.state,j.created_at_utc "
        f"FROM communication_job_scopes s JOIN {DURABLE_JOB_METADATA_V1} j ON j.job_id=s.job_id" + where +
        " ORDER BY j.created_at_utc DESC,j.job_id DESC LIMIT ?) "
        "SELECT p.job_id,p.source_scope_id,p.job_kind,j.job_type,j.contract_version,p.state,p.created_at_utc,j.updated_at_utc,"
        "j.started_at_utc,j.ended_at_utc,j.attempt_count,j.next_attempt_at_utc,j.cancellation_requested,j.diagnostic_code," +
        ",".join(f"c.{name}" for name in COUNTERS) +
        f" FROM page p JOIN {DURABLE_JOB_METADATA_V1} j ON j.job_id=p.job_id "
        "LEFT JOIN communication_job_counters c ON c.job_id=p.job_id ORDER BY p.created_at_utc DESC,p.job_id DESC",
        (*values, limit + 1),
    ).fetchall()
    items = []
    for row in rows[:limit]:
        if row[3] != JOB_TYPES[row[2]] or row[4] != 1:
            raise IntegrityFailure("Communication job scope disagrees with its registered Foundation type")
        if row[14] is None:
            raise IntegrityFailure("Communication job lacks its recorded counters")
        try:
            counters = CommunicationJobCounters.from_value(dict(zip(COUNTERS, row[14:], strict=True)))
        except ValidationError:
            raise IntegrityFailure("Communication job counters violate their contract") from None
        items.append({"job_id": row[0], "source_scope_id": row[1], "job_kind": row[2], "state": row[5],
            "phase": None, "counters": counters.to_response(), "percentage": counters.percentage,
            "created_at_utc": row[6], "updated_at_utc": row[7], "started_at_utc": row[8], "ended_at_utc": row[9],
            "attempt_count": row[10], "next_attempt_at_utc": row[11], "cancellation_requested": bool(row[12]), "diagnostic_code": row[13]})
    continuation = None
    if len(rows) > limit:
        last = rows[limit - 1]
        continuation = next_cursor(query=QUERY, filters=filters, null_order="none", key=(last[6], last[0]))
    return {"items": items, "next_cursor": continuation}


class JobQueries:
    def __init__(self, connection_factory):
        self._factory = connection_factory

    def list_jobs(self, request):
        with ReadSnapshot(self._factory) as reader:
            return list_jobs_in_reader(reader, request)
