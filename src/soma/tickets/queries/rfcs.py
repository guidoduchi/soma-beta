from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from soma.foundation.errors import SomaError, ValidationError
from soma.foundation.persistence.connections import ConnectionFactory
from soma.foundation.persistence.uow import ReadSnapshot


@dataclass(frozen=True, slots=True)
class RfcDetail:
    rfc_id: str
    rfc_no: str
    revision: int
    hierarchy_role: str
    customer_org_id: str | None
    local_archive_state: str
    source_projection: dict[str, Any] | None
    direct_service_request_count: int
    device_reference_count: int
    subordinate_count: int
    warnings: tuple[str, ...]


class RfcQueryService:
    """Read-only LLD-03 point projection for RFCs."""

    def __init__(self, connection_factory: ConnectionFactory) -> None:
        self._factory = connection_factory

    @staticmethod
    def _lookup(connection, *, rfc_id: str | None, rfc_no: str | None):
        if (rfc_id is None) == (rfc_no is None):
            raise ValidationError("exactly one RFC lookup identity is required")
        if rfc_id is not None:
            return connection.execute(
                "SELECT rfc_id,rfc_no,customer_org_id,local_archive_state,revision FROM rfcs WHERE rfc_id=?",
                (rfc_id,),
            ).fetchone()
        assert rfc_no is not None
        return connection.execute(
            "SELECT rfc_id,rfc_no,customer_org_id,local_archive_state,revision FROM rfcs WHERE rfc_no=?",
            (rfc_no,),
        ).fetchone()

    @staticmethod
    def _source_projection(connection, rfc_id: str) -> dict[str, Any] | None:
        cursor = connection.execute(
            "SELECT * FROM rfc_current_source_projection WHERE rfc_id=?",
            (rfc_id,),
        )
        row = cursor.fetchone()
        if row is None:
            return None
        names = tuple(column[0] for column in cursor.description)
        projection = {name: value for name, value in zip(names, row, strict=True) if name != "rfc_id"}
        return projection

    def get(self, *, rfc_id: str | None = None, rfc_no: str | None = None) -> RfcDetail:
        with ReadSnapshot(self._factory) as snapshot:
            connection = snapshot.connection
            row = self._lookup(connection, rfc_id=rfc_id, rfc_no=rfc_no)
            if row is None:
                raise SomaError("NOT_FOUND", "RFC does not exist")
            resolved_rfc_id = str(row[0])
            parent = connection.execute(
                "SELECT parent_rfc_id FROM rfc_hierarchy_edges WHERE child_rfc_id=? AND edge_state='active'",
                (resolved_rfc_id,),
            ).fetchone()
            subordinate_count = int(
                connection.execute(
                    "SELECT COUNT(*) FROM rfc_hierarchy_edges WHERE parent_rfc_id=? AND edge_state='active'",
                    (resolved_rfc_id,),
                ).fetchone()[0]
            )
            if parent is not None and subordinate_count:
                raise SomaError("PERSISTENCE_FAILURE", "RFC hierarchy violates the two-level forest invariant")
            hierarchy_role = "subordinate" if parent is not None else ("root" if subordinate_count else "standalone")
            direct_service_request_count = int(
                connection.execute(
                    "SELECT COUNT(*) FROM sr_rfc_links WHERE rfc_id=? AND link_state='active'",
                    (resolved_rfc_id,),
                ).fetchone()[0]
            )
            device_reference_count = int(
                connection.execute(
                    "SELECT COUNT(*) FROM rfc_device_reference_links WHERE rfc_id=? AND link_state='active'",
                    (resolved_rfc_id,),
                ).fetchone()[0]
            )
            warnings: list[str] = []
            customer_org_id = None if row[2] is None else str(row[2])
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
            source_projection = self._source_projection(connection, resolved_rfc_id)
        return RfcDetail(
            rfc_id=resolved_rfc_id,
            rfc_no=str(row[1]),
            revision=int(row[4]),
            hierarchy_role=hierarchy_role,
            customer_org_id=customer_org_id,
            local_archive_state=str(row[3]),
            source_projection=source_projection,
            direct_service_request_count=direct_service_request_count,
            device_reference_count=device_reference_count,
            subordinate_count=subordinate_count,
            warnings=tuple(warnings),
        )
