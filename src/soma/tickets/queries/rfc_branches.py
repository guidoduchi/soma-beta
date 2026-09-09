from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from typing import Any

from soma.foundation.errors import SomaError, ValidationError
from soma.foundation.persistence.connections import ConnectionFactory
from soma.foundation.persistence.uow import ReadSnapshot
from soma.foundation.strict_json import canonical_json_bytes, sha256_canonical_json

from .rfcs import RfcDetail, RfcQueryService

_DEFAULT_LIMIT = 100
_MAX_LIMIT = 500
_BRANCH_SCHEMA = "SOMA_RFC_BRANCH_FINGERPRINT_V1"
_FILTER_SCHEMA = "SOMA_RFC_BRANCH_FILTER_V1"
_QUERY_ID = "GetRfcBranch"
_SORT_REGISTRY_ID = "RFC_BRANCH_CHILD_ID_ASC_V1"
_NULL_ORDER = "not_applicable"
_SHA256_HEX = re.compile(r"[0-9a-f]{64}")


def _detail_to_response(detail: RfcDetail) -> dict[str, Any]:
    return {
        "rfc_id": detail.rfc_id,
        "rfc_no": detail.rfc_no,
        "revision": detail.revision,
        "hierarchy_role": detail.hierarchy_role,
        "customer_org_id": detail.customer_org_id,
        "local_archive_state": detail.local_archive_state,
        "source_projection": detail.source_projection,
        "direct_service_request_count": detail.direct_service_request_count,
        "device_reference_count": detail.device_reference_count,
        "subordinate_count": detail.subordinate_count,
        "warnings": list(detail.warnings),
    }


def _detail_from_response(value: Any) -> RfcDetail:
    if not isinstance(value, dict):
        raise ValidationError("RfcDetailV1 response must be an object")
    expected = {
        "rfc_id",
        "rfc_no",
        "revision",
        "hierarchy_role",
        "customer_org_id",
        "local_archive_state",
        "source_projection",
        "direct_service_request_count",
        "device_reference_count",
        "subordinate_count",
        "warnings",
    }
    if set(value) != expected:
        raise ValidationError("RfcDetailV1 response fields are invalid")
    if not isinstance(value["rfc_id"], str) or not isinstance(value["rfc_no"], str):
        raise ValidationError("RfcDetailV1 identity fields are invalid")
    revision = value["revision"]
    if type(revision) is not int or revision < 1:
        raise ValidationError("RfcDetailV1 revision is invalid")
    if value["hierarchy_role"] not in {"standalone", "root", "subordinate"}:
        raise ValidationError("RfcDetailV1 hierarchy role is invalid")
    customer_org_id = value["customer_org_id"]
    if customer_org_id is not None and not isinstance(customer_org_id, str):
        raise ValidationError("RfcDetailV1 Customer identity is invalid")
    if value["local_archive_state"] not in {"active", "archived"}:
        raise ValidationError("RfcDetailV1 archive state is invalid")
    source_projection = value["source_projection"]
    if source_projection is not None and not isinstance(source_projection, dict):
        raise ValidationError("RfcDetailV1 source projection is invalid")
    counts: list[int] = []
    for key in ("direct_service_request_count", "device_reference_count", "subordinate_count"):
        count = value[key]
        if type(count) is not int or count < 0:
            raise ValidationError("RfcDetailV1 count is invalid")
        counts.append(count)
    warnings = value["warnings"]
    if not isinstance(warnings, list) or any(not isinstance(item, str) for item in warnings):
        raise ValidationError("RfcDetailV1 warnings are invalid")
    return RfcDetail(
        rfc_id=value["rfc_id"],
        rfc_no=value["rfc_no"],
        revision=revision,
        hierarchy_role=value["hierarchy_role"],
        customer_org_id=customer_org_id,
        local_archive_state=value["local_archive_state"],
        source_projection=source_projection,
        direct_service_request_count=counts[0],
        device_reference_count=counts[1],
        subordinate_count=counts[2],
        warnings=tuple(warnings),
    )


def _filter_fingerprint(root_rfc_id: str) -> str:
    return sha256_canonical_json(
        {
            "schema": _FILTER_SCHEMA,
            "root_rfc_id": root_rfc_id,
        }
    )


def _cursor_body(root_rfc_id: str, last_child_rfc_id: str) -> dict[str, Any]:
    return {
        "version": 1,
        "query_id": _QUERY_ID,
        "sort_registry_id": _SORT_REGISTRY_ID,
        "last_key_tuple": [last_child_rfc_id],
        "filter_fingerprint": _filter_fingerprint(root_rfc_id),
        "null_order": _NULL_ORDER,
    }


def _validate_cursor(cursor: Any, root_rfc_id: str) -> str | None:
    if cursor is None:
        return None
    if not isinstance(cursor, dict):
        raise ValidationError("RFC branch cursor must be an object")
    expected = {
        "version",
        "query_id",
        "sort_registry_id",
        "last_key_tuple",
        "filter_fingerprint",
        "null_order",
    }
    if set(cursor) != expected:
        raise ValidationError("RFC branch cursor fields are invalid")
    if cursor["version"] != 1 or cursor["query_id"] != _QUERY_ID:
        raise ValidationError("RFC branch cursor version/query is invalid")
    if cursor["sort_registry_id"] != _SORT_REGISTRY_ID or cursor["null_order"] != _NULL_ORDER:
        raise ValidationError("RFC branch cursor sort contract is invalid")
    if cursor["filter_fingerprint"] != _filter_fingerprint(root_rfc_id):
        raise ValidationError("RFC branch cursor filter fingerprint is stale")
    key = cursor["last_key_tuple"]
    if not isinstance(key, list) or len(key) != 1 or not isinstance(key[0], str) or not key[0]:
        raise ValidationError("RFC branch cursor key tuple is invalid")
    return key[0]


@dataclass(frozen=True, slots=True)
class RfcBranch:
    root: RfcDetail
    subordinates: tuple[RfcDetail, ...]
    continuation: dict[str, Any] | None
    branch_fingerprint: str

    def to_response(self) -> dict[str, Any]:
        return {
            "root": _detail_to_response(self.root),
            "subordinates": [_detail_to_response(item) for item in self.subordinates],
            "continuation": self.continuation,
            "branch_fingerprint": self.branch_fingerprint,
        }

    @classmethod
    def from_response(cls, value: Any) -> "RfcBranch":
        if not isinstance(value, dict) or set(value) != {
            "root",
            "subordinates",
            "continuation",
            "branch_fingerprint",
        }:
            raise ValidationError("RfcBranchV1 response fields are invalid")
        root = _detail_from_response(value["root"])
        children = value["subordinates"]
        if not isinstance(children, list) or len(children) > _MAX_LIMIT:
            raise ValidationError("RfcBranchV1 subordinate page is invalid")
        parsed = tuple(_detail_from_response(item) for item in children)
        if tuple(item.rfc_id for item in parsed) != tuple(sorted(item.rfc_id for item in parsed)):
            raise ValidationError("RfcBranchV1 subordinate order is invalid")
        fingerprint = value["branch_fingerprint"]
        if not isinstance(fingerprint, str) or _SHA256_HEX.fullmatch(fingerprint) is None:
            raise ValidationError("RfcBranchV1 fingerprint is invalid")
        continuation = value["continuation"]
        if continuation is not None:
            last = _validate_cursor(continuation, root.rfc_id)
            if not parsed or last != parsed[-1].rfc_id:
                raise ValidationError("RfcBranchV1 continuation does not bind the last returned child")
        return cls(
            root=root,
            subordinates=parsed,
            continuation=continuation,
            branch_fingerprint=fingerprint,
        )


class RfcBranchQueryService:
    """Exact LLD-03 branch projection usable from a ReadSnapshot or an existing UoW."""

    def __init__(self, connection_factory: ConnectionFactory) -> None:
        self._factory = connection_factory
        self._rfc_query = RfcQueryService(connection_factory)

    @staticmethod
    def _validate_limit(limit: int) -> int:
        if type(limit) is not int or not 1 <= limit <= _MAX_LIMIT:
            raise ValidationError("RFC branch page size must be an integer from 1 through 500")
        return limit

    @staticmethod
    def _root_authority(connection, root_rfc_id: str):
        row = connection.execute(
            "SELECT rfc_id,revision,customer_org_id,local_archive_state FROM rfcs WHERE rfc_id=?",
            (root_rfc_id,),
        ).fetchone()
        if row is None:
            raise SomaError("NOT_FOUND", "RFC does not exist")
        if connection.execute(
            "SELECT 1 FROM rfc_hierarchy_edges WHERE child_rfc_id=? AND edge_state='active'",
            (root_rfc_id,),
        ).fetchone() is not None:
            raise ValidationError("RFC branch root must be parentless")
        return row

    @classmethod
    def branch_fingerprint_from_connection(cls, connection, root_rfc_id: str) -> str:
        root = cls._root_authority(connection, root_rfc_id)
        root_customer = None if root[2] is None else str(root[2])
        root_object = {
            "rfc_id": str(root[0]),
            "revision": int(root[1]),
            "customer_org_id": root_customer,
            "local_archive_state": str(root[3]),
        }
        digest = hashlib.sha256()
        digest.update(b'{"root":')
        digest.update(canonical_json_bytes(root_object))
        digest.update(b',"schema":"SOMA_RFC_BRANCH_FINGERPRINT_V1","subordinates":[')
        cursor = connection.execute(
            "SELECT e.rfc_hierarchy_edge_id,c.rfc_id,c.revision,c.customer_org_id,c.local_archive_state "
            "FROM rfc_hierarchy_edges e JOIN rfcs c ON c.rfc_id=e.child_rfc_id "
            "WHERE e.parent_rfc_id=? AND e.edge_state='active' ORDER BY c.rfc_id ASC",
            (root_rfc_id,),
        )
        first = True
        for row in cursor:
            child_customer = None if row[3] is None else str(row[3])
            if root_customer is not None and child_customer is not None and root_customer != child_customer:
                raise SomaError("PERSISTENCE_FAILURE", "RFC branch contains a known Customer mismatch")
            if not first:
                digest.update(b",")
            first = False
            digest.update(
                canonical_json_bytes(
                    {
                        "rfc_hierarchy_edge_id": str(row[0]),
                        "rfc_id": str(row[1]),
                        "revision": int(row[2]),
                        "customer_org_id": child_customer,
                        "local_archive_state": str(row[4]),
                    }
                )
            )
        digest.update(b"]}")
        return digest.hexdigest()

    def get_from_connection(
        self,
        connection,
        *,
        root_rfc_id: str,
        cursor: dict[str, Any] | None = None,
        limit: int = _DEFAULT_LIMIT,
    ) -> RfcBranch:
        limit = self._validate_limit(limit)
        after_child_id = _validate_cursor(cursor, root_rfc_id)
        self._root_authority(connection, root_rfc_id)
        fingerprint = self.branch_fingerprint_from_connection(connection, root_rfc_id)
        if after_child_id is None:
            child_rows = connection.execute(
                "SELECT child_rfc_id FROM rfc_hierarchy_edges "
                "WHERE parent_rfc_id=? AND edge_state='active' "
                "ORDER BY child_rfc_id ASC LIMIT ?",
                (root_rfc_id, limit + 1),
            ).fetchall()
        else:
            child_rows = connection.execute(
                "SELECT child_rfc_id FROM rfc_hierarchy_edges "
                "WHERE parent_rfc_id=? AND edge_state='active' AND child_rfc_id>? "
                "ORDER BY child_rfc_id ASC LIMIT ?",
                (root_rfc_id, after_child_id, limit + 1),
            ).fetchall()
        has_more = len(child_rows) > limit
        page_ids = tuple(str(row[0]) for row in child_rows[:limit])
        root = self._rfc_query.get_from_connection(connection, rfc_id=root_rfc_id)
        if root.hierarchy_role == "subordinate":
            raise SomaError("PERSISTENCE_FAILURE", "RFC branch root became subordinate during projection")
        subordinates = self._rfc_query.get_subordinates_from_connection(connection, page_ids)
        continuation = _cursor_body(root_rfc_id, page_ids[-1]) if has_more and page_ids else None
        return RfcBranch(
            root=root,
            subordinates=subordinates,
            continuation=continuation,
            branch_fingerprint=fingerprint,
        )

    def get(
        self,
        *,
        root_rfc_id: str,
        cursor: dict[str, Any] | None = None,
        limit: int = _DEFAULT_LIMIT,
    ) -> RfcBranch:
        with ReadSnapshot(self._factory) as snapshot:
            return self.get_from_connection(
                snapshot.connection,
                root_rfc_id=root_rfc_id,
                cursor=cursor,
                limit=limit,
            )
