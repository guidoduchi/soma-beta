from __future__ import annotations

from soma.foundation.persistence.connections import ConnectionFactory
from soma.foundation.persistence.uow import ReadSnapshot

from ..algorithms.individual_sla import IndividualSlaCalculator, IndividualSlaResult


class IndividualSlaQueryService:
    def __init__(self, connection_factory: ConnectionFactory) -> None:
        self._factory = connection_factory

    def get_individual(self, *, service_request_id: str, as_of_utc: int) -> IndividualSlaResult:
        with ReadSnapshot(self._factory) as snapshot:
            return IndividualSlaCalculator.calculate(
                snapshot.connection,
                service_request_id,
                as_of_utc,
            )


__all__ = ["IndividualSlaQueryService"]
