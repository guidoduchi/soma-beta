from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from soma.foundation.errors import SomaError
from soma.foundation.persistence.connections import ConnectionFactory
from soma.foundation.persistence.uow import ReadSnapshot


_RFC_SOURCE_STATE_COLUMNS: tuple[str, ...] = (
    "summary_text",
    "summary_evidence_id",
    "external_created_at_utc",
    "external_created_evidence_id",
    "creator_text",
    "creator_evidence_id",
    "customer_account_number_text",
    "customer_account_number_evidence_id",
    "customer_account_name_text",
    "customer_account_name_evidence_id",
    "severity_text",
    "severity_evidence_id",
    "status_text",
    "status_class",
    "status_authority",
    "status_evidence_id",
    "owner_external_id_text",
    "owner_external_id_evidence_id",
    "owner_name_text",
    "owner_name_evidence_id",
    "l1_handler_name_text",
    "l1_handler_name_evidence_id",
    "l2_handler_name_text",
    "l2_handler_name_evidence_id",
    "last_update_utc",
    "last_update_evidence_id",
    "revision",
)


@dataclass(frozen=True, slots=True)
class RfcLifecycleProjection:
    rfc_id: str
    accepted_source_state: dict[str, Any]
    local_archive_state: str
    terminal_epoch_id: str | None
    warnings: tuple[str, ...]


class RfcLifecycleQueryService:
    """Read-only LLD-03 RFC lifecycle/source current projection."""

    def __init__(self, connection_factory: ConnectionFactory) -> None:
        self._factory = connection_factory

    @staticmethod
    def _empty_source_state() -> dict[str, Any]:
        state = {column: None for column in _RFC_SOURCE_STATE_COLUMNS}
        state["status_class"] = "unknown"
        return state

    @classmethod
    def get_from_connection(cls, connection: Any, *, rfc_id: str) -> RfcLifecycleProjection:
        rfc = connection.execute(
            "SELECT customer_org_id,local_archive_state FROM rfcs WHERE rfc_id=?",
            (rfc_id,),
        ).fetchone()
        if rfc is None:
            raise SomaError("NOT_FOUND", "RFC does not exist")

        selected = ",".join((*_RFC_SOURCE_STATE_COLUMNS[:-1], "terminal_epoch_id", "revision"))
        projection = connection.execute(
            f"SELECT {selected} FROM rfc_current_source_projection WHERE rfc_id=?",
            (rfc_id,),
        ).fetchone()
        if projection is None:
            accepted_source_state = cls._empty_source_state()
            terminal_epoch_id = None
        else:
            source_values = projection[:-2] + (projection[-1],)
            accepted_source_state = {
                column: value
                for column, value in zip(_RFC_SOURCE_STATE_COLUMNS, source_values, strict=True)
            }
            terminal_epoch_id = None if projection[-2] is None else str(projection[-2])

        warnings: list[str] = []
        customer_org_id = None if rfc[0] is None else str(rfc[0])
        if customer_org_id is None:
            warnings.append("RFC_CUSTOMER_UNRESOLVED")
        else:
            customer = connection.execute(
                "SELECT lifecycle_state FROM customer_organizations WHERE customer_org_id=?",
                (customer_org_id,),
            ).fetchone()
            if customer is None:
                raise SomaError("PERSISTENCE_FAILURE", "RFC Customer reference does not resolve")
            if str(customer[0]) != "active":
                warnings.append("RFC_CUSTOMER_REFERENCE_ARCHIVED")

        return RfcLifecycleProjection(
            rfc_id=rfc_id,
            accepted_source_state=accepted_source_state,
            local_archive_state=str(rfc[1]),
            terminal_epoch_id=terminal_epoch_id,
            warnings=tuple(warnings),
        )

    def get(self, *, rfc_id: str) -> RfcLifecycleProjection:
        with ReadSnapshot(self._factory) as snapshot:
            return self.get_from_connection(snapshot.connection, rfc_id=rfc_id)
