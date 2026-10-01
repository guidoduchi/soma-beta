from __future__ import annotations

from soma.foundation.errors import ValidationError
from soma.foundation.identifiers import utc_epoch_seconds

from soma.communications.jobs.communications import JOB_TYPES
from soma.communications.jobs.execution import run_with_failure_policy

_SAFE_MESSAGE = "Communication identity reconciliation could not be completed."


class CommunicationIdentityReconciliationWorker:
    """Foundation owns attempts/recovery; the service owns atomic candidate work."""

    def __init__(self, service, coordinator, *, clock=utc_epoch_seconds):
        self._service, self._jobs, self._clock = service, coordinator, clock

    def run(self, claim):
        if claim.job_type != JOB_TYPES["IDENTITY_RECONCILIATION"] or claim.contract_version != 1:
            raise ValidationError("Reconciliation worker received another job type")
        return run_with_failure_policy(claim, self._jobs, job_kind="IDENTITY_RECONCILIATION", clock=self._clock,
            execute=lambda: self._service.execute_claim(claim), safe_message=_SAFE_MESSAGE)
