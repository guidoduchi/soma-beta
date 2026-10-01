from soma.foundation.errors import ValidationError
from soma.foundation.identifiers import new_uuid4, utc_epoch_seconds
from soma.foundation.persistence.uow import UnitOfWork

from soma.communications.contracts.common import integer
from soma.communications.jobs.communications import JOB_TYPES
from soma.communications.jobs.execution import run_with_failure_policy


class CommunicationHousekeepingWorker:
    """Reselect current due rows; each candidate/checkpoint is an atomic command."""

    def __init__(self, connection_factory, service, coordinator, *, clock=utc_epoch_seconds):
        self._factory, self._service, self._jobs, self._clock = connection_factory, service, coordinator, clock

    def run(self, claim):
        if claim.job_type != JOB_TYPES["ORPHAN_HOUSEKEEPING"] or claim.contract_version != 1:
            raise ValidationError("Housekeeping worker received another job type")
        return run_with_failure_policy(claim, self._jobs, job_kind="ORPHAN_HOUSEKEEPING", clock=self._clock,
            execute=lambda: self._execute(claim), safe_message="Communication housekeeping could not be completed.")

    def _execute(self, claim):
        # Finish the finite set currently due; later due rows belong to a later
        # scheduled run. Recovery deliberately reselects current due authority.
        cutoff = integer(self._clock())
        while True:
            with UnitOfWork(self._factory) as writer:
                _, counters, _ = self._service._claim_progress(writer, claim, self._jobs)
                due = writer.connection.execute("SELECT communication_id,revision FROM communication_retention "
                    "WHERE state='ORPHAN_PENDING_PURGE' AND purge_due_utc<=? ORDER BY purge_due_utc,communication_id LIMIT 1",
                    (cutoff,)).fetchone()
                if due is None:
                    # Revalidate the empty due set and claim inside completion,
                    # so cancellation cannot be overwritten by stale success.
                    self._jobs.complete_in_uow(writer, claim)
                    return counters.to_response()
            self._service.purge_due_claim(claim, self._jobs, command_id=new_uuid4(), communication_id=due[0],
                selected_revision=due[1], now_utc=integer(self._clock()))
