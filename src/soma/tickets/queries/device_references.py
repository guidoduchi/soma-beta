from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol

from soma.foundation.errors import IntegrityFailure, SomaError, ValidationError
from soma.foundation.identifiers import require_uuid4
from soma.foundation.persistence.connections import ConnectionFactory
from soma.foundation.persistence.uow import ReadSnapshot
from soma.foundation.strict_json import sha256_canonical_json

_DEFAULT_LIMIT = 100
_MAX_LIMIT = 500
_NULL_ORDER = "not_applicable"
_LIST_QUERY_ID = "ListTicketDeviceReferences"
_LIST_SORT_ID = "TICKET_DEVICE_REFERENCE_ID_ASC_V1"
_LIST_FILTER_SCHEMA = "SOMA_TICKET_DEVICE_REFERENCE_FILTER_V1"
_BRANCH_QUERY_ID = "GetRfcDeviceContextForBranch"
_BRANCH_SORT_ID = "RFC_BRANCH_DEVICE_REFERENCE_ORDER_V1"
_BRANCH_FILTER_SCHEMA = "SOMA_RFC_BRANCH_DEVICE_REFERENCE_FILTER_V1"
_TARGETS = {
    "service_request": ("service_requests", "service_request_id", "sr_device_reference_links", "service_request_id"),
    "rfc": ("rfcs", "rfc_id", "rfc_device_reference_links", "rfc_id"),
}


class DeviceReferenceResolutionReader(Protocol):
    def resolution_for(self, reader: object, device_reference_id: str) -> object | None: ...


def _validate_limit(limit: int) -> int:
    if type(limit) is not int or not 1 <= limit <= _MAX_LIMIT:
        raise ValidationError("Device Reference page size must be an integer from 1 through 500")
    return limit


def _cursor_body(*, query_id: str, sort_id: str, filter_fingerprint: str, last_key: list[str]) -> dict[str, Any]:
    return {
        "version": 1,
        "query_id": query_id,
        "sort_registry_id": sort_id,
        "last_key_tuple": last_key,
        "filter_fingerprint": filter_fingerprint,
        "null_order": _NULL_ORDER,
    }


def _validate_cursor(
    cursor: Any,
    *,
    query_id: str,
    sort_id: str,
    filter_fingerprint: str,
    key_length: int,
) -> list[str] | None:
    if cursor is None:
        return None
    if not isinstance(cursor, dict) or set(cursor) != {
        "version",
        "query_id",
        "sort_registry_id",
        "last_key_tuple",
        "filter_fingerprint",
        "null_order",
    }:
        raise ValidationError("Device Reference cursor fields are invalid")
    if cursor["version"] != 1 or cursor["query_id"] != query_id:
        raise ValidationError("Device Reference cursor version/query is invalid")
    if cursor["sort_registry_id"] != sort_id or cursor["null_order"] != _NULL_ORDER:
        raise ValidationError("Device Reference cursor sort contract is invalid")
    if cursor["filter_fingerprint"] != filter_fingerprint:
        raise ValidationError("Device Reference cursor filter fingerprint is stale")
    key = cursor["last_key_tuple"]
    if (
        not isinstance(key, list)
        or len(key) != key_length
        or any(not isinstance(item, str) for item in key)
    ):
        raise ValidationError("Device Reference cursor key tuple is invalid")
    return key


def _resolution_network_element_id(value: object | None) -> str | None:
    if value is None:
        return None
    if isinstance(value, dict):
        if "network_element_id" not in value:
            raise IntegrityFailure("Device Reference resolution is missing Network Element identity")
        raw = value["network_element_id"]
    else:
        raw = getattr(value, "network_element_id", None)
    if not isinstance(raw, str):
        raise IntegrityFailure("Device Reference resolution has invalid Network Element identity")
    try:
        return require_uuid4(raw)
    except ValidationError as exc:
        raise IntegrityFailure("Device Reference resolution has invalid Network Element identity") from exc


@dataclass(frozen=True, slots=True)
class DeviceReferenceView:
    device_reference_id: str
    operational_name: str
    revision: int
    registered_network_element_id: str | None

    def to_response(self) -> dict[str, object]:
        return {
            "device_reference_id": self.device_reference_id,
            "operational_name": self.operational_name,
            "revision": self.revision,
            "registered_network_element_id": self.registered_network_element_id,
        }


@dataclass(frozen=True, slots=True)
class DeviceReferencePage:
    items: tuple[DeviceReferenceView, ...]
    continuation: dict[str, Any] | None

    def to_response(self) -> dict[str, object]:
        return {
            "items": [item.to_response() for item in self.items],
            "continuation": self.continuation,
        }


@dataclass(frozen=True, slots=True)
class RfcBranchDeviceReferenceRow:
    owning_rfc_id: str
    role: str
    device_reference: DeviceReferenceView

    def to_response(self) -> dict[str, object]:
        value = self.device_reference.to_response()
        value.update({"owning_rfc_id": self.owning_rfc_id, "role": self.role})
        return value


@dataclass(frozen=True, slots=True)
class RfcBranchDeviceReferencePage:
    items: tuple[RfcBranchDeviceReferenceRow, ...]
    continuation: dict[str, Any] | None

    def to_response(self) -> dict[str, object]:
        return {
            "items": [item.to_response() for item in self.items],
            "continuation": self.continuation,
        }


class TicketDeviceReferenceQueryService:
    """Read-only LLD-03 Device Reference projections; Infrastructure resolution remains optional metadata."""

    def __init__(
        self,
        connection_factory: ConnectionFactory,
        resolution_reader: DeviceReferenceResolutionReader | None = None,
    ) -> None:
        self._factory = connection_factory
        self._resolution_reader = resolution_reader

    @staticmethod
    def _target_spec(ticket_type: str) -> tuple[str, str, str, str]:
        try:
            return _TARGETS[ticket_type]
        except KeyError as exc:
            raise ValidationError("ticket_type must be service_request or rfc") from exc

    @staticmethod
    def _require_target(connection, table: str, id_column: str, ticket_id: str) -> None:
        if connection.execute(
            f"SELECT 1 FROM {table} WHERE {id_column}=?",
            (ticket_id,),
        ).fetchone() is None:
            raise SomaError("NOT_FOUND", "Ticket does not exist")

    @staticmethod
    def _require_root(connection, root_rfc_id: str) -> None:
        if connection.execute("SELECT 1 FROM rfcs WHERE rfc_id=?", (root_rfc_id,)).fetchone() is None:
            raise SomaError("NOT_FOUND", "RFC does not exist")
        if connection.execute(
            "SELECT 1 FROM rfc_hierarchy_edges WHERE child_rfc_id=? AND edge_state='active'",
            (root_rfc_id,),
        ).fetchone() is not None:
            raise ValidationError("RFC branch root must be parentless")

    def _view(self, snapshot: ReadSnapshot, row: object) -> DeviceReferenceView:
        device_reference_id = str(row[0])
        resolved_id = None
        if self._resolution_reader is not None:
            try:
                resolved_id = _resolution_network_element_id(
                    self._resolution_reader.resolution_for(snapshot, device_reference_id)
                )
            except (IntegrityFailure, SomaError, ValidationError):
                raise
            except Exception as exc:
                raise IntegrityFailure("Device Reference resolution provider failed") from exc
        return DeviceReferenceView(
            device_reference_id=device_reference_id,
            operational_name=str(row[1]),
            revision=int(row[2]),
            registered_network_element_id=resolved_id,
        )

    def list_for_ticket(
        self,
        *,
        ticket_type: str,
        ticket_id: str,
        cursor: dict[str, Any] | None = None,
        limit: int = _DEFAULT_LIMIT,
    ) -> DeviceReferencePage:
        table, id_column, link_table, owner_column = self._target_spec(ticket_type)
        target_id = require_uuid4(ticket_id)
        page_limit = _validate_limit(limit)
        filter_fingerprint = sha256_canonical_json(
            {"schema": _LIST_FILTER_SCHEMA, "ticket_type": ticket_type, "ticket_id": target_id}
        )
        key = _validate_cursor(
            cursor,
            query_id=_LIST_QUERY_ID,
            sort_id=_LIST_SORT_ID,
            filter_fingerprint=filter_fingerprint,
            key_length=1,
        )
        after_device: str | None = None
        if key is not None:
            after_device = require_uuid4(key[0])

        with ReadSnapshot(self._factory) as snapshot:
            connection = snapshot.connection
            self._require_target(connection, table, id_column, target_id)
            sql = (
                f"SELECT d.device_reference_id,d.operational_name,d.revision FROM {link_table} l "
                f"JOIN device_references d ON d.device_reference_id=l.device_reference_id "
                f"WHERE l.{owner_column}=? AND l.link_state='active' "
            )
            if after_device is None:
                rows = connection.execute(
                    sql + "ORDER BY d.device_reference_id ASC LIMIT ?",
                    (target_id, page_limit + 1),
                ).fetchall()
            else:
                rows = connection.execute(
                    sql + "AND d.device_reference_id>? ORDER BY d.device_reference_id ASC LIMIT ?",
                    (target_id, after_device, page_limit + 1),
                ).fetchall()
            has_more = len(rows) > page_limit
            page_rows = rows[:page_limit]
            items = tuple(self._view(snapshot, row) for row in page_rows)
            continuation = None
            if has_more and page_rows:
                continuation = _cursor_body(
                    query_id=_LIST_QUERY_ID,
                    sort_id=_LIST_SORT_ID,
                    filter_fingerprint=filter_fingerprint,
                    last_key=[str(page_rows[-1][0])],
                )
            return DeviceReferencePage(items=items, continuation=continuation)

    def branch_context(
        self,
        *,
        root_rfc_id: str,
        cursor: dict[str, Any] | None = None,
        limit: int = _DEFAULT_LIMIT,
    ) -> RfcBranchDeviceReferencePage:
        root_id = require_uuid4(root_rfc_id)
        page_limit = _validate_limit(limit)
        filter_fingerprint = sha256_canonical_json(
            {"schema": _BRANCH_FILTER_SCHEMA, "root_rfc_id": root_id}
        )
        key = _validate_cursor(
            cursor,
            query_id=_BRANCH_QUERY_ID,
            sort_id=_BRANCH_SORT_ID,
            filter_fingerprint=filter_fingerprint,
            key_length=2,
        )
        after_owner: str | None = None
        after_device: str | None = None
        if key is not None:
            after_owner = require_uuid4(key[0])
            after_device = require_uuid4(key[1])

        with ReadSnapshot(self._factory) as snapshot:
            connection = snapshot.connection
            self._require_root(connection, root_id)
            base_sql = (
                "WITH owners AS ("
                "SELECT ? AS owning_rfc_id,'root' AS role "
                "UNION ALL "
                "SELECT child_rfc_id,'subordinate' FROM rfc_hierarchy_edges "
                "WHERE parent_rfc_id=? AND edge_state='active'"
                ") SELECT o.owning_rfc_id,o.role,d.device_reference_id,d.operational_name,d.revision "
                "FROM owners o JOIN rfc_device_reference_links l ON l.rfc_id=o.owning_rfc_id AND l.link_state='active' "
                "JOIN device_references d ON d.device_reference_id=l.device_reference_id "
            )
            if after_owner is None:
                rows = connection.execute(
                    base_sql + "ORDER BY o.owning_rfc_id ASC,d.device_reference_id ASC LIMIT ?",
                    (root_id, root_id, page_limit + 1),
                ).fetchall()
            else:
                assert after_device is not None
                rows = connection.execute(
                    base_sql
                    + "WHERE o.owning_rfc_id>? OR (o.owning_rfc_id=? AND d.device_reference_id>?) "
                    "ORDER BY o.owning_rfc_id ASC,d.device_reference_id ASC LIMIT ?",
                    (root_id, root_id, after_owner, after_owner, after_device, page_limit + 1),
                ).fetchall()
            has_more = len(rows) > page_limit
            page_rows = rows[:page_limit]
            items = tuple(
                RfcBranchDeviceReferenceRow(
                    owning_rfc_id=str(row[0]),
                    role=str(row[1]),
                    device_reference=self._view(snapshot, (row[2], row[3], row[4])),
                )
                for row in page_rows
            )
            continuation = None
            if has_more and page_rows:
                continuation = _cursor_body(
                    query_id=_BRANCH_QUERY_ID,
                    sort_id=_BRANCH_SORT_ID,
                    filter_fingerprint=filter_fingerprint,
                    last_key=[str(page_rows[-1][0]), str(page_rows[-1][2])],
                )
            return RfcBranchDeviceReferencePage(items=items, continuation=continuation)
