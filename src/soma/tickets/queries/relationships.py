from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from soma.foundation.errors import IntegrityFailure, SomaError, ValidationError
from soma.foundation.identifiers import require_uuid4
from soma.foundation.persistence.connections import ConnectionFactory
from soma.foundation.persistence.uow import ReadSnapshot
from soma.foundation.strict_json import sha256_canonical_json

_DEFAULT_LIMIT = 100
_MAX_LIMIT = 500
_NULL_ORDER = "not_applicable"
_BRANCH_QUERY_ID = "GetServiceRequestRfcBranches"
_BRANCH_SORT_ID = "SR_RFC_BRANCH_MEMBER_ORDER_V1"
_BRANCH_FILTER_SCHEMA = "SOMA_SR_RFC_BRANCH_FILTER_V1"
_CONTEXT_QUERY_ID = "GetEffectiveServiceRequestContextForRfc"
_CONTEXT_SORT_ID = "RFC_EFFECTIVE_SR_CONTEXT_ORDER_V1"
_CONTEXT_FILTER_SCHEMA = "SOMA_RFC_EFFECTIVE_SR_CONTEXT_FILTER_V1"


def _validate_limit(limit: int) -> int:
    if type(limit) is not int or not 1 <= limit <= _MAX_LIMIT:
        raise ValidationError("ticket relationship page size must be an integer from 1 through 500")
    return limit


def _cursor_body(*, query_id: str, sort_id: str, filter_fingerprint: str, last_key: list[object]) -> dict[str, Any]:
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
) -> list[object] | None:
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
        raise ValidationError("ticket relationship cursor fields are invalid")
    if cursor["version"] != 1 or cursor["query_id"] != query_id:
        raise ValidationError("ticket relationship cursor version/query is invalid")
    if cursor["sort_registry_id"] != sort_id or cursor["null_order"] != _NULL_ORDER:
        raise ValidationError("ticket relationship cursor sort contract is invalid")
    if cursor["filter_fingerprint"] != filter_fingerprint:
        raise ValidationError("ticket relationship cursor filter fingerprint is stale")
    key = cursor["last_key_tuple"]
    if not isinstance(key, list) or len(key) != key_length:
        raise ValidationError("ticket relationship cursor key tuple is invalid")
    return key


@dataclass(frozen=True, slots=True)
class ServiceRequestRfcBranchMember:
    direct_link_id: str
    root_rfc_id: str
    member_rfc_id: str
    role: str

    def to_response(self) -> dict[str, object]:
        return {
            "direct_link_id": self.direct_link_id,
            "root_rfc_id": self.root_rfc_id,
            "member_rfc_id": self.member_rfc_id,
            "role": self.role,
        }


@dataclass(frozen=True, slots=True)
class ServiceRequestRfcBranchPage:
    items: tuple[ServiceRequestRfcBranchMember, ...]
    continuation: dict[str, Any] | None

    def to_response(self) -> dict[str, object]:
        return {
            "items": [item.to_response() for item in self.items],
            "continuation": self.continuation,
        }


@dataclass(frozen=True, slots=True)
class EffectiveServiceRequestContextRow:
    sr_rfc_link_id: str
    service_request_id: str
    governing_root_rfc_id: str
    requested_rfc_id: str
    inherited_via_root: str | None

    def to_response(self) -> dict[str, object]:
        return {
            "sr_rfc_link_id": self.sr_rfc_link_id,
            "service_request_id": self.service_request_id,
            "governing_root_rfc_id": self.governing_root_rfc_id,
            "requested_rfc_id": self.requested_rfc_id,
            "inherited_via_root": self.inherited_via_root,
        }


@dataclass(frozen=True, slots=True)
class EffectiveServiceRequestContextPage:
    items: tuple[EffectiveServiceRequestContextRow, ...]
    continuation: dict[str, Any] | None

    def to_response(self) -> dict[str, object]:
        return {
            "items": [item.to_response() for item in self.items],
            "continuation": self.continuation,
        }


class ServiceRequestRfcQueryService:
    """Read-only LLD-03 SR/RFC relationship projections with exact root provenance."""

    def __init__(self, connection_factory: ConnectionFactory) -> None:
        self._factory = connection_factory

    @staticmethod
    def _require_service_request(connection, service_request_id: str) -> None:
        if connection.execute(
            "SELECT 1 FROM service_requests WHERE service_request_id=?",
            (service_request_id,),
        ).fetchone() is None:
            raise SomaError("NOT_FOUND", "Service Request does not exist")

    @staticmethod
    def _governing_root(connection, rfc_id: str) -> str:
        if connection.execute("SELECT 1 FROM rfcs WHERE rfc_id=?", (rfc_id,)).fetchone() is None:
            raise SomaError("NOT_FOUND", "RFC does not exist")
        parent = connection.execute(
            "SELECT parent_rfc_id FROM rfc_hierarchy_edges WHERE child_rfc_id=? AND edge_state='active'",
            (rfc_id,),
        ).fetchone()
        if parent is None:
            return rfc_id
        root_id = str(parent[0])
        if connection.execute(
            "SELECT 1 FROM rfc_hierarchy_edges WHERE child_rfc_id=? AND edge_state='active'",
            (root_id,),
        ).fetchone() is not None:
            raise IntegrityFailure("RFC hierarchy exceeds the accepted two-level invariant")
        return root_id

    @staticmethod
    def _require_direct_roots(connection, service_request_id: str) -> None:
        if connection.execute(
            "SELECT 1 FROM sr_rfc_links l JOIN rfc_hierarchy_edges e ON e.child_rfc_id=l.rfc_id "
            "AND e.edge_state='active' WHERE l.service_request_id=? AND l.link_state='active' LIMIT 1",
            (service_request_id,),
        ).fetchone() is not None:
            raise IntegrityFailure("active Service Request RFC link targets a subordinate RFC")

    def list_branches(
        self,
        *,
        service_request_id: str,
        cursor: dict[str, Any] | None = None,
        limit: int = _DEFAULT_LIMIT,
    ) -> ServiceRequestRfcBranchPage:
        sr_id = require_uuid4(service_request_id)
        page_limit = _validate_limit(limit)
        filter_fingerprint = sha256_canonical_json(
            {"schema": _BRANCH_FILTER_SCHEMA, "service_request_id": sr_id}
        )
        key = _validate_cursor(
            cursor,
            query_id=_BRANCH_QUERY_ID,
            sort_id=_BRANCH_SORT_ID,
            filter_fingerprint=filter_fingerprint,
            key_length=3,
        )
        after_root: str | None = None
        after_role: int | None = None
        after_member: str | None = None
        if key is not None:
            if (
                not isinstance(key[0], str)
                or type(key[1]) is not int
                or key[1] not in {0, 1}
                or not isinstance(key[2], str)
            ):
                raise ValidationError("Service Request RFC branch cursor key is invalid")
            after_root = require_uuid4(key[0])
            after_role = key[1]
            after_member = require_uuid4(key[2])

        with ReadSnapshot(self._factory) as snapshot:
            connection = snapshot.connection
            self._require_service_request(connection, sr_id)
            self._require_direct_roots(connection, sr_id)
            base_sql = (
                "WITH members AS ("
                "SELECT l.sr_rfc_link_id AS direct_link_id,l.rfc_id AS root_rfc_id,0 AS role_ordinal,"
                "l.rfc_id AS member_rfc_id,'root' AS role "
                "FROM sr_rfc_links l WHERE l.service_request_id=? AND l.link_state='active' "
                "UNION ALL "
                "SELECT l.sr_rfc_link_id,l.rfc_id,1,e.child_rfc_id,'subordinate' "
                "FROM sr_rfc_links l JOIN rfc_hierarchy_edges e ON e.parent_rfc_id=l.rfc_id AND e.edge_state='active' "
                "WHERE l.service_request_id=? AND l.link_state='active'"
                ") SELECT direct_link_id,root_rfc_id,role_ordinal,member_rfc_id,role FROM members "
            )
            if after_root is None:
                rows = connection.execute(
                    base_sql + "ORDER BY root_rfc_id ASC,role_ordinal ASC,member_rfc_id ASC LIMIT ?",
                    (sr_id, sr_id, page_limit + 1),
                ).fetchall()
            else:
                assert after_role is not None and after_member is not None
                rows = connection.execute(
                    base_sql
                    + "WHERE root_rfc_id>? OR (root_rfc_id=? AND role_ordinal>?) "
                    "OR (root_rfc_id=? AND role_ordinal=? AND member_rfc_id>?) "
                    "ORDER BY root_rfc_id ASC,role_ordinal ASC,member_rfc_id ASC LIMIT ?",
                    (
                        sr_id,
                        sr_id,
                        after_root,
                        after_root,
                        after_role,
                        after_root,
                        after_role,
                        after_member,
                        page_limit + 1,
                    ),
                ).fetchall()

            has_more = len(rows) > page_limit
            page_rows = rows[:page_limit]
            items = tuple(
                ServiceRequestRfcBranchMember(
                    direct_link_id=str(row[0]),
                    root_rfc_id=str(row[1]),
                    member_rfc_id=str(row[3]),
                    role=str(row[4]),
                )
                for row in page_rows
            )
            continuation = None
            if has_more and page_rows:
                last = page_rows[-1]
                continuation = _cursor_body(
                    query_id=_BRANCH_QUERY_ID,
                    sort_id=_BRANCH_SORT_ID,
                    filter_fingerprint=filter_fingerprint,
                    last_key=[str(last[1]), int(last[2]), str(last[3])],
                )
            return ServiceRequestRfcBranchPage(items=items, continuation=continuation)

    def effective_context_for_rfc(
        self,
        *,
        rfc_id: str,
        cursor: dict[str, Any] | None = None,
        limit: int = _DEFAULT_LIMIT,
    ) -> EffectiveServiceRequestContextPage:
        requested_id = require_uuid4(rfc_id)
        page_limit = _validate_limit(limit)
        filter_fingerprint = sha256_canonical_json(
            {"schema": _CONTEXT_FILTER_SCHEMA, "rfc_id": requested_id}
        )
        key = _validate_cursor(
            cursor,
            query_id=_CONTEXT_QUERY_ID,
            sort_id=_CONTEXT_SORT_ID,
            filter_fingerprint=filter_fingerprint,
            key_length=1,
        )
        after_sr: str | None = None
        if key is not None:
            if not isinstance(key[0], str):
                raise ValidationError("effective Service Request context cursor key is invalid")
            after_sr = require_uuid4(key[0])

        with ReadSnapshot(self._factory) as snapshot:
            connection = snapshot.connection
            root_id = self._governing_root(connection, requested_id)
            inherited = root_id if root_id != requested_id else None
            if after_sr is None:
                rows = connection.execute(
                    "SELECT sr_rfc_link_id,service_request_id FROM sr_rfc_links "
                    "WHERE rfc_id=? AND link_state='active' ORDER BY service_request_id ASC LIMIT ?",
                    (root_id, page_limit + 1),
                ).fetchall()
            else:
                rows = connection.execute(
                    "SELECT sr_rfc_link_id,service_request_id FROM sr_rfc_links "
                    "WHERE rfc_id=? AND link_state='active' AND service_request_id>? "
                    "ORDER BY service_request_id ASC LIMIT ?",
                    (root_id, after_sr, page_limit + 1),
                ).fetchall()
            has_more = len(rows) > page_limit
            page_rows = rows[:page_limit]
            items = tuple(
                EffectiveServiceRequestContextRow(
                    sr_rfc_link_id=str(row[0]),
                    service_request_id=str(row[1]),
                    governing_root_rfc_id=root_id,
                    requested_rfc_id=requested_id,
                    inherited_via_root=inherited,
                )
                for row in page_rows
            )
            continuation = None
            if has_more and page_rows:
                continuation = _cursor_body(
                    query_id=_CONTEXT_QUERY_ID,
                    sort_id=_CONTEXT_SORT_ID,
                    filter_fingerprint=filter_fingerprint,
                    last_key=[str(page_rows[-1][1])],
                )
            return EffectiveServiceRequestContextPage(items=items, continuation=continuation)
