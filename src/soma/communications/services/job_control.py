from __future__ import annotations

from soma.foundation.application.command_boundary import CommandBoundary, CommandEnvelope, PreparedMutation
from soma.foundation.audit.writer import AuditResultRef, AuditWriter
from soma.foundation.errors import IntegrityFailure, ValidationError
from soma.foundation.identifiers import new_uuid4, require_uuid4
from soma.foundation.queries.jobs import DURABLE_JOB_METADATA_V1

from soma.communications.audit_registry import audit_event, build_communications_audit_registry
from soma.communications.contracts.common import closed
from soma.communications.jobs.communications import JOB_TYPES


class CommunicationJobControlService:
    """Cancel owned jobs at a committed batch boundary through Foundation."""

    def __init__(self, connection_factory, coordinator):
        self._jobs = coordinator
        self._boundary = CommandBoundary(connection_factory, AuditWriter(build_communications_audit_registry()))

    def cancel_job(self, payload, *, actor_kind="local_user", actor_id=None):
        closed(payload, {"command_id", "job_id"})
        command, job = require_uuid4(payload["command_id"]), require_uuid4(payload["job_id"])
        envelope = CommandEnvelope(command, "CancelCommunicationJob", "durable_job", job, {"job_id": job})

        def prepare(uow):
            row = uow.connection.execute(
                f"SELECT s.job_kind,j.job_type,j.contract_version,j.state FROM communication_job_scopes s "
                f"JOIN {DURABLE_JOB_METADATA_V1} j USING(job_id) WHERE s.job_id=?", (job,)).fetchone()
            if row is None:
                raise ValidationError("Communication job does not exist")
            kind, job_type, version, prior = row
            if kind not in JOB_TYPES or JOB_TYPES[kind] != job_type or version != 1:
                raise IntegrityFailure("Communication job scope disagrees with Foundation metadata")
            result = {"status": "NO_CHANGE", "job_id": job, "prior_state": prior,
                      "resulting_state": prior, "cancellation_event_id": None}
            if prior in {"completed", "failed", "cancelled"}:
                return PreparedMutation(True, None, None, response_schema="CommunicationJobCancellationResultV1", response=result)
            if prior not in {"queued", "running", "waiting_review", "retry_wait"}:
                raise IntegrityFailure("Communication job has an unknown state")
            event = new_uuid4()
            result.update(status="APPLIED", resulting_state="cancelled", cancellation_event_id=event)

            def apply(inner):
                cancelled = self._jobs.cancel(inner, job, job_type, version, {"command_id": command})
                if (cancelled.outcome != "CANCELLED" or cancelled.job_id != job
                        or cancelled.prior_state != prior or cancelled.resulting_state != "cancelled"):
                    raise IntegrityFailure("Communication cancellation changed within its writer transaction")
                # Foundation owns the transition clock; record its exact accepted time.
                now = inner.connection.execute(
                    f"SELECT updated_at_utc FROM {DURABLE_JOB_METADATA_V1} WHERE job_id=?", (job,)).fetchone()[0]
                inner.connection.execute("INSERT INTO communication_job_cancellation_events VALUES(?,?,?,?,?,?,?,?,?)",
                    (event, job, kind, prior, cancelled.resulting_state, int(cancelled.claim_revoked),
                     cancelled.cancelled_attempt_ordinal, now, command))
                return audit_event("communications.job.cancelled", command_id=command,
                    target_type="durable_job", target_id=job, actor_kind=actor_kind, actor_id=actor_id,
                    payload={"job_kind": kind, "prior_state": prior, "resulting_state": cancelled.resulting_state},
                    refs=(AuditResultRef("durable_job", job), AuditResultRef("communication_job_cancellation_event", event)))

            return PreparedMutation(False, "communication_job_cancellation_event", event, apply,
                response_schema="CommunicationJobCancellationResultV1", response=result)

        return self._boundary.execute(envelope, prepare).response
