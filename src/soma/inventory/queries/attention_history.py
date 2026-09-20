from __future__ import annotations

from dataclasses import dataclass

from soma.foundation.errors import ValidationError
from soma.foundation.identifiers import require_uuid4
from soma.foundation.persistence.connections import ConnectionFactory
from soma.foundation.persistence.uow import ReadSnapshot

_RESPONSE_OVERDUE_SECONDS = 24 * 60 * 60


@dataclass(frozen=True, slots=True)
class SpareRequestResponseAttention:
    spare_request_id: str
    attention_kind: str
    severity: str
    warning_start_utc: int
    due_at_utc: int
    age_seconds: int


class InventoryAttentionQueryService:
    def __init__(self, connection_factory: ConnectionFactory) -> None:
        self._factory = connection_factory

    def spare_request_response_attention(
        self,
        *,
        spare_request_id: str,
        as_of_utc: int,
    ) -> SpareRequestResponseAttention | None:
        request_id = require_uuid4(spare_request_id)
        if type(as_of_utc) is not int or as_of_utc < 0:
            raise ValidationError("as_of_utc must be a nonnegative integer")
        with ReadSnapshot(self._factory) as snapshot:
            row = snapshot.connection.execute(
                "SELECT lifecycle_state,response_warning_start_utc "
                "FROM spare_request_current_projection WHERE spare_request_id=?",
                (request_id,),
            ).fetchone()
        if row is None:
            raise ValidationError("Spare Request does not exist")
        if str(row[0]) != "submitted_awaiting_response" or row[1] is None:
            return None
        warning_start = int(row[1])
        due = warning_start + _RESPONSE_OVERDUE_SECONDS
        if as_of_utc < due:
            return None
        return SpareRequestResponseAttention(
            spare_request_id=request_id,
            attention_kind="spare_request_response_overdue",
            severity="warning",
            warning_start_utc=warning_start,
            due_at_utc=due,
            age_seconds=as_of_utc - warning_start,
        )


__all__ = ["InventoryAttentionQueryService", "SpareRequestResponseAttention"]
