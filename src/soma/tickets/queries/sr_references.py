from __future__ import annotations

from typing import Any

from soma.foundation.errors import SomaError
from soma.foundation.persistence.connections import ConnectionFactory
from soma.foundation.persistence.uow import ReadSnapshot

from .service_requests import ServiceRequestQueryService


class ServiceRequestReferenceQueryService:
    """Read-only current LLD-03 Service Request reference context projection."""

    def __init__(self, connection_factory: ConnectionFactory) -> None:
        self._factory = connection_factory

    def get(self, *, service_request_id: str) -> dict[str, Any]:
        with ReadSnapshot(self._factory) as snapshot:
            row = snapshot.connection.execute(
                "SELECT revision FROM service_requests WHERE service_request_id=?",
                (service_request_id,),
            ).fetchone()
            if row is None:
                raise SomaError("NOT_FOUND", "Service Request does not exist")
            context, _warnings = ServiceRequestQueryService._reference_context(
                snapshot.connection,
                service_request_id,
                int(row[0]),
            )
            return context
