"""Host-invoked trigger evaluation; Foundation owns timers, claims and executors."""
from soma.foundation.errors import IntegrityFailure, SomaError
from soma.foundation.identifiers import new_uuid4
from soma.foundation.persistence.uow import ReadSnapshot, UnitOfWork
from soma.foundation.strict_json import canonical_json_bytes
from soma.communications.contracts.common import integer
from soma.communications.contracts.jobs import CommunicationJobScope
from soma.communications.jobs.communications import JOB_TYPES, dedupe_key


class CommunicationSchedule:
    def __init__(self, runtime):
        self._runtime = runtime

    def enqueue_housekeeping(self, now):
        scope = CommunicationJobScope(None, (), "ORPHAN_HOUSEKEEPING", None, None, (), None).to_response()
        encoded = canonical_json_bytes(scope).decode("utf-8")
        with UnitOfWork(self._runtime.connection_factory) as writer:
            job = self._runtime.coordinator.enqueue_or_coalesce(writer, JOB_TYPES["ORPHAN_HOUSEKEEPING"], 1, scope, dedupe_key(scope))
            row = writer.connection.execute("SELECT scope_json FROM communication_job_scopes WHERE job_id=?", (job,)).fetchone()
            if row is not None:
                if row[0] != encoded:
                    raise IntegrityFailure("Housekeeping trigger changed its immutable installation scope")
                return job
            writer.connection.execute("INSERT INTO communication_job_scopes VALUES(?,'ORPHAN_HOUSEKEEPING',NULL,?,NULL,?,NULL,NULL)", (job, encoded, now))
            writer.connection.execute("INSERT INTO communication_job_counters VALUES(?,0,0,0,0,0,0,0,0,0,NULL,1,?)", (job, now))
            return job

    def tick(self, now):
        integer(now)
        housekeeping = self.enqueue_housekeeping(now)
        after = ""
        requested = skipped = 0
        while True:
            with ReadSnapshot(self._runtime.connection_factory) as reader:
                values, _ = self._runtime.providers["settings"]._schedule(reader)
                if not values[0].value:
                    break
                interval = values[1].value * 60
                rows = reader.connection.execute("SELECT s.source_scope_id,s.revision,"
                    "(SELECT j.created_at_utc FROM communication_job_scopes j WHERE j.source_scope_id=s.source_scope_id "
                    "AND j.job_kind='ORDINARY' ORDER BY j.created_at_utc DESC,j.job_id DESC LIMIT 1) "
                    "FROM communication_source_scopes s WHERE s.processing_enabled=1 AND s.source_scope_id>? "
                    "ORDER BY s.source_scope_id LIMIT 64", (after,)).fetchall()
            if not rows:
                break
            after = rows[-1][0]
            for source, revision, last in rows:
                if last is not None and now < last + interval:
                    continue
                try:
                    result = self._runtime.providers["processing"].request_scheduled_processing({"command_id": new_uuid4(),
                        "source_scope_id": source, "source_scope_revision": revision})
                    requested += int(result["job_id"] is not None)
                except SomaError as exc:
                    if exc.code not in {"COMM_NO_TRACKABLE_TARGETS", "COMM_COVERAGE_BOUNDARY_UNKNOWN", "COMM_SOURCE_NOT_FOUND",
                            "COMM_SOURCE_LOCKED", "COMM_SOURCE_UNSUPPORTED", "COMM_STALE", "COMM_JOB_ACTIVE"}:
                        raise
                    skipped += 1
        return {"housekeeping_job_id": housekeeping, "ordinary_requests": requested, "skipped_sources": skipped}
