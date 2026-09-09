from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from typing import Any, Iterable

from soma.foundation.errors import SomaError, ValidationError
from soma.foundation.identifiers import require_uuid4
from soma.foundation.persistence.connections import ConnectionFactory
from soma.foundation.persistence.uow import ReadSnapshot
from soma.foundation.strict_json import canonical_json_bytes, sha256_canonical_json

_DEFAULT_LIMIT = 100
_MAX_LIMIT = 500
_SCOPE_PROFILE = "SOMA_RFC_ARCHIVE_SCOPE_V1"
_PREVIEW_QUERY_ID = "PreviewRfcArchive"
_PREVIEW_SORT_REGISTRY_ID = "RFC_ARCHIVE_SCOPE_ORDER_V1"
_PREVIEW_FILTER_SCHEMA = "SOMA_RFC_ARCHIVE_PREVIEW_FILTER_V1"
_OPERATION_QUERY_ID = "GetRfcArchiveOperation"
_OPERATION_SORT_REGISTRY_ID = "RFC_ARCHIVE_OPERATION_MEMBER_ORDER_V1"
_OPERATION_FILTER_SCHEMA = "SOMA_RFC_ARCHIVE_OPERATION_FILTER_V1"
_NULL_ORDER = "not_applicable"
_SCOPE_KINDS = frozenset({"exact_rfc", "reviewed_branch"})
_ARCHIVE_STATES = frozenset({"active", "archived"})
_SHA256_HEX_RE = re.compile(r"[0-9a-f]{64}\Z")


def _request_uuid(value: object, *, field: str) -> str:
    if not isinstance(value, str):
        raise ValidationError(f"{field} must be canonical UUIDv4")
    try:
        return require_uuid4(value)
    except ValidationError as exc:
        raise ValidationError(f"{field} must be canonical UUIDv4") from exc


def _stored_uuid(value: object, *, field: str) -> str:
    if not isinstance(value, str):
        raise SomaError("PERSISTENCE_FAILURE", f"stored {field} is not a UUID string")
    try:
        return require_uuid4(value)
    except ValidationError as exc:
        raise SomaError("PERSISTENCE_FAILURE", f"stored {field} is not canonical UUIDv4") from exc


def _validate_scope_kind(scope_kind: str) -> str:
    if scope_kind not in _SCOPE_KINDS:
        raise ValidationError("scope_kind must be exact_rfc or reviewed_branch")
    return scope_kind


def _validate_limit(limit: int) -> int:
    if type(limit) is not int or not 1 <= limit <= _MAX_LIMIT:
        raise ValidationError("RFC archive page size must be an integer from 1 through 500")
    return limit


@dataclass(frozen=True, slots=True)
class RfcArchiveScopeMember:
    rfc_id: str
    rfc_revision: int
    archive_state: str
    scope_ordinal: int

    @property
    def change_classification(self) -> str:
        return "would_change" if self.archive_state == "active" else "excluded_prearchived"

    def fingerprint_object(self) -> dict[str, object]:
        return {
            "rfc_id": self.rfc_id,
            "rfc_revision": self.rfc_revision,
            "archive_state": self.archive_state,
        }

    def to_response(self) -> dict[str, object]:
        return {
            "rfc_id": self.rfc_id,
            "rfc_revision": self.rfc_revision,
            "archive_state": self.archive_state,
            "change_classification": self.change_classification,
        }


@dataclass(frozen=True, slots=True)
class RfcArchiveScope:
    requested_rfc_id: str
    scope_kind: str
    members: tuple[RfcArchiveScopeMember, ...]
    scope_fingerprint: str

    @property
    def exact_member_count(self) -> int:
        return len(self.members)

    @property
    def would_change_count(self) -> int:
        return sum(member.archive_state == "active" for member in self.members)

    @property
    def excluded_prearchived_count(self) -> int:
        return self.exact_member_count - self.would_change_count


@dataclass(frozen=True, slots=True)
class RfcArchivePreview:
    scope_kind: str
    exact_member_count: int
    would_change_count: int
    excluded_prearchived_count: int
    items: tuple[RfcArchiveScopeMember, ...]
    continuation: dict[str, Any] | None
    scope_fingerprint: str

    def to_response(self) -> dict[str, object]:
        return {
            "scope_kind": self.scope_kind,
            "exact_member_count": self.exact_member_count,
            "would_change_count": self.would_change_count,
            "excluded_prearchived_count": self.excluded_prearchived_count,
            "items": [item.to_response() for item in self.items],
            "continuation": self.continuation,
            "scope_fingerprint": self.scope_fingerprint,
        }


@dataclass(frozen=True, slots=True)
class RfcArchiveOperationMember:
    rfc_id: str
    pre_archive_revision: int
    archived_revision: int
    ordinal: int
    current_archive_state: str
    latest_event_type: str
    latest_event_origin_archive_operation_id: str
    latest_event_resulting_rfc_revision: int
    restore_eligible: bool

    def to_response(self) -> dict[str, object]:
        return {
            "rfc_id": self.rfc_id,
            "pre_archive_revision": self.pre_archive_revision,
            "archived_revision": self.archived_revision,
            "ordinal": self.ordinal,
            "current_archive_state": self.current_archive_state,
            "latest_event_type": self.latest_event_type,
            "latest_event_origin_archive_operation_id": self.latest_event_origin_archive_operation_id,
            "latest_event_resulting_rfc_revision": self.latest_event_resulting_rfc_revision,
            "restore_eligible": self.restore_eligible,
        }

    @classmethod
    def from_response(cls, value: Any) -> "RfcArchiveOperationMember":
        if not isinstance(value, dict) or set(value) != {
            "rfc_id",
            "pre_archive_revision",
            "archived_revision",
            "ordinal",
            "current_archive_state",
            "latest_event_type",
            "latest_event_origin_archive_operation_id",
            "latest_event_resulting_rfc_revision",
            "restore_eligible",
        }:
            raise ValidationError("RfcArchiveOperationMember response fields are invalid")
        rfc_id = _request_uuid(value["rfc_id"], field="archive operation member rfc_id")
        origin_id = _request_uuid(
            value["latest_event_origin_archive_operation_id"],
            field="archive operation member latest event origin",
        )
        pre_revision = value["pre_archive_revision"]
        archived_revision = value["archived_revision"]
        ordinal = value["ordinal"]
        latest_revision = value["latest_event_resulting_rfc_revision"]
        if (
            type(pre_revision) is not int
            or pre_revision <= 0
            or type(archived_revision) is not int
            or archived_revision != pre_revision + 1
            or type(ordinal) is not int
            or ordinal < 0
            or value["current_archive_state"] not in _ARCHIVE_STATES
            or value["latest_event_type"] not in {"archived", "restored"}
            or type(latest_revision) is not int
            or latest_revision <= 1
            or type(value["restore_eligible"]) is not bool
        ):
            raise ValidationError("RfcArchiveOperationMember response authority is invalid")
        return cls(
            rfc_id=rfc_id,
            pre_archive_revision=pre_revision,
            archived_revision=archived_revision,
            ordinal=ordinal,
            current_archive_state=value["current_archive_state"],
            latest_event_type=value["latest_event_type"],
            latest_event_origin_archive_operation_id=origin_id,
            latest_event_resulting_rfc_revision=latest_revision,
            restore_eligible=value["restore_eligible"],
        )


@dataclass(frozen=True, slots=True)
class RfcArchiveOperation:
    rfc_archive_operation_id: str
    scope_kind: str
    scope_fingerprint: str
    exact_member_count: int
    members: tuple[RfcArchiveOperationMember, ...]
    continuation: dict[str, Any] | None

    def to_response(self) -> dict[str, object]:
        return {
            "rfc_archive_operation_id": self.rfc_archive_operation_id,
            "scope_kind": self.scope_kind,
            "scope_fingerprint": self.scope_fingerprint,
            "exact_member_count": self.exact_member_count,
            "members": [member.to_response() for member in self.members],
            "continuation": self.continuation,
        }

    @classmethod
    def from_response(cls, value: Any) -> "RfcArchiveOperation":
        if not isinstance(value, dict) or set(value) != {
            "rfc_archive_operation_id",
            "scope_kind",
            "scope_fingerprint",
            "exact_member_count",
            "members",
            "continuation",
        }:
            raise ValidationError("RfcArchiveOperationV1 response fields are invalid")
        operation_id = _request_uuid(
            value["rfc_archive_operation_id"],
            field="rfc_archive_operation_id",
        )
        scope_kind = _validate_scope_kind(value["scope_kind"])
        fingerprint = value["scope_fingerprint"]
        count = value["exact_member_count"]
        members_raw = value["members"]
        if (
            not isinstance(fingerprint, str)
            or _SHA256_HEX_RE.fullmatch(fingerprint) is None
            or type(count) is not int
            or count < 0
            or not isinstance(members_raw, list)
            or len(members_raw) > _MAX_LIMIT
        ):
            raise ValidationError("RfcArchiveOperationV1 response authority is invalid")
        members = tuple(RfcArchiveOperationMember.from_response(item) for item in members_raw)
        ordered = tuple((item.ordinal, item.rfc_id) for item in members)
        if ordered != tuple(sorted(ordered)):
            raise ValidationError("RfcArchiveOperationV1 member order is invalid")
        continuation = value["continuation"]
        if continuation is not None:
            last = _validate_operation_cursor(continuation, operation_id)
            if not members or last != (members[-1].ordinal, members[-1].rfc_id):
                raise ValidationError("RfcArchiveOperationV1 continuation does not bind last member")
        return cls(
            rfc_archive_operation_id=operation_id,
            scope_kind=scope_kind,
            scope_fingerprint=fingerprint,
            exact_member_count=count,
            members=members,
            continuation=continuation,
        )


def _load_requested_rfc(connection: Any, rfc_id: str) -> tuple[str, int, str]:
    row = connection.execute(
        "SELECT rfc_id,revision,local_archive_state FROM rfcs WHERE rfc_id=?",
        (rfc_id,),
    ).fetchone()
    if row is None:
        raise SomaError("NOT_FOUND", "RFC does not exist")
    canonical_id = _stored_uuid(row[0], field="RFC identity")
    revision = row[1]
    archive_state = str(row[2])
    if type(revision) is not int or revision <= 0 or archive_state not in _ARCHIVE_STATES:
        raise SomaError("PERSISTENCE_FAILURE", "stored RFC archive authority is invalid")
    return canonical_id, revision, archive_state


def _require_parentless(connection: Any, rfc_id: str) -> None:
    if connection.execute(
        "SELECT 1 FROM rfc_hierarchy_edges WHERE child_rfc_id=? AND edge_state='active'",
        (rfc_id,),
    ).fetchone() is not None:
        raise SomaError("RFC_ARCHIVE_SCOPE_STALE", "reviewed RFC branch root is no longer parentless")


def _iter_scope_members(
    connection: Any,
    *,
    rfc_id: str,
    scope_kind: str,
) -> Iterable[RfcArchiveScopeMember]:
    root_id, root_revision, root_archive_state = _load_requested_rfc(connection, rfc_id)
    yield RfcArchiveScopeMember(root_id, root_revision, root_archive_state, 0)
    if scope_kind == "exact_rfc":
        return
    _require_parentless(connection, root_id)
    cursor = connection.execute(
        "SELECT c.rfc_id,c.revision,c.local_archive_state "
        "FROM rfc_hierarchy_edges e JOIN rfcs c ON c.rfc_id=e.child_rfc_id "
        "WHERE e.parent_rfc_id=? AND e.edge_state='active' ORDER BY c.rfc_id ASC",
        (root_id,),
    )
    ordinal = 1
    for row in cursor:
        child_id = _stored_uuid(row[0], field="RFC archive child identity")
        revision = row[1]
        archive_state = str(row[2])
        if type(revision) is not int or revision <= 0 or archive_state not in _ARCHIVE_STATES:
            raise SomaError("PERSISTENCE_FAILURE", "stored RFC archive child authority is invalid")
        yield RfcArchiveScopeMember(child_id, revision, archive_state, ordinal)
        ordinal += 1


def _stream_scope_fingerprint(
    *,
    requested_rfc_id: str,
    scope_kind: str,
    members: Iterable[RfcArchiveScopeMember],
) -> tuple[str, int, int]:
    digest = hashlib.sha256()
    digest.update(b'{"members":[')
    first = True
    exact_count = 0
    changed_count = 0
    for member in members:
        if not first:
            digest.update(b",")
        first = False
        digest.update(canonical_json_bytes(member.fingerprint_object()))
        exact_count += 1
        changed_count += member.archive_state == "active"
    digest.update(b'],"requested_rfc_id":')
    digest.update(canonical_json_bytes(requested_rfc_id))
    digest.update(b',"schema":"SOMA_RFC_ARCHIVE_SCOPE_V1","scope_kind":')
    digest.update(canonical_json_bytes(scope_kind))
    digest.update(b"}")
    return digest.hexdigest(), exact_count, changed_count


def archive_scope_fingerprint(scope: RfcArchiveScope) -> str:
    return sha256_canonical_json(
        {
            "schema": _SCOPE_PROFILE,
            "requested_rfc_id": scope.requested_rfc_id,
            "scope_kind": scope.scope_kind,
            "members": [member.fingerprint_object() for member in scope.members],
        }
    )


def resolve_archive_scope_from_connection(
    connection: Any,
    *,
    rfc_id: str,
    scope_kind: str,
) -> RfcArchiveScope:
    canonical_rfc_id = _request_uuid(rfc_id, field="rfc_id")
    canonical_scope_kind = _validate_scope_kind(scope_kind)
    members = tuple(
        _iter_scope_members(
            connection,
            rfc_id=canonical_rfc_id,
            scope_kind=canonical_scope_kind,
        )
    )
    scope = RfcArchiveScope(
        requested_rfc_id=canonical_rfc_id,
        scope_kind=canonical_scope_kind,
        members=members,
        scope_fingerprint="",
    )
    return RfcArchiveScope(
        requested_rfc_id=scope.requested_rfc_id,
        scope_kind=scope.scope_kind,
        members=scope.members,
        scope_fingerprint=archive_scope_fingerprint(scope),
    )


def _preview_filter_fingerprint(*, rfc_id: str, scope_kind: str, scope_fingerprint: str) -> str:
    return sha256_canonical_json(
        {
            "schema": _PREVIEW_FILTER_SCHEMA,
            "rfc_id": rfc_id,
            "scope_kind": scope_kind,
            "scope_fingerprint": scope_fingerprint,
        }
    )


def _preview_cursor(
    *,
    rfc_id: str,
    scope_kind: str,
    scope_fingerprint: str,
    member: RfcArchiveScopeMember,
) -> dict[str, object]:
    return {
        "version": 1,
        "query_id": _PREVIEW_QUERY_ID,
        "sort_registry_id": _PREVIEW_SORT_REGISTRY_ID,
        "last_key_tuple": [member.scope_ordinal, member.rfc_id],
        "filter_fingerprint": _preview_filter_fingerprint(
            rfc_id=rfc_id,
            scope_kind=scope_kind,
            scope_fingerprint=scope_fingerprint,
        ),
        "null_order": _NULL_ORDER,
    }


def _validate_preview_cursor(
    cursor: Any,
    *,
    rfc_id: str,
    scope_kind: str,
    scope_fingerprint: str,
) -> tuple[int, str] | None:
    if cursor is None:
        return None
    if not isinstance(cursor, dict):
        raise ValidationError("RFC archive preview cursor must be an object")
    expected = {
        "version",
        "query_id",
        "sort_registry_id",
        "last_key_tuple",
        "filter_fingerprint",
        "null_order",
    }
    if set(cursor) != expected:
        raise ValidationError("RFC archive preview cursor fields are invalid")
    if cursor["version"] != 1 or cursor["query_id"] != _PREVIEW_QUERY_ID:
        raise ValidationError("RFC archive preview cursor version/query is invalid")
    if cursor["sort_registry_id"] != _PREVIEW_SORT_REGISTRY_ID or cursor["null_order"] != _NULL_ORDER:
        raise ValidationError("RFC archive preview cursor sort contract is invalid")
    expected_filter = _preview_filter_fingerprint(
        rfc_id=rfc_id,
        scope_kind=scope_kind,
        scope_fingerprint=scope_fingerprint,
    )
    if cursor["filter_fingerprint"] != expected_filter:
        raise ValidationError("RFC archive preview cursor filter fingerprint is stale")
    key = cursor["last_key_tuple"]
    if not isinstance(key, list) or len(key) != 2:
        raise ValidationError("RFC archive preview cursor key tuple is invalid")
    ordinal, member_id = key
    if type(ordinal) is not int or ordinal < 0:
        raise ValidationError("RFC archive preview cursor ordinal is invalid")
    canonical_member_id = _request_uuid(member_id, field="RFC archive preview cursor member identity")
    return ordinal, canonical_member_id


def _operation_filter_fingerprint(operation_id: str) -> str:
    return sha256_canonical_json(
        {
            "schema": _OPERATION_FILTER_SCHEMA,
            "rfc_archive_operation_id": operation_id,
        }
    )


def _operation_cursor(operation_id: str, member: RfcArchiveOperationMember) -> dict[str, object]:
    return {
        "version": 1,
        "query_id": _OPERATION_QUERY_ID,
        "sort_registry_id": _OPERATION_SORT_REGISTRY_ID,
        "last_key_tuple": [member.ordinal, member.rfc_id],
        "filter_fingerprint": _operation_filter_fingerprint(operation_id),
        "null_order": _NULL_ORDER,
    }


def _validate_operation_cursor(cursor: Any, operation_id: str) -> tuple[int, str] | None:
    if cursor is None:
        return None
    if not isinstance(cursor, dict):
        raise ValidationError("RFC archive operation cursor must be an object")
    expected = {
        "version",
        "query_id",
        "sort_registry_id",
        "last_key_tuple",
        "filter_fingerprint",
        "null_order",
    }
    if set(cursor) != expected:
        raise ValidationError("RFC archive operation cursor fields are invalid")
    if cursor["version"] != 1 or cursor["query_id"] != _OPERATION_QUERY_ID:
        raise ValidationError("RFC archive operation cursor version/query is invalid")
    if cursor["sort_registry_id"] != _OPERATION_SORT_REGISTRY_ID or cursor["null_order"] != _NULL_ORDER:
        raise ValidationError("RFC archive operation cursor sort contract is invalid")
    if cursor["filter_fingerprint"] != _operation_filter_fingerprint(operation_id):
        raise ValidationError("RFC archive operation cursor filter fingerprint is stale")
    key = cursor["last_key_tuple"]
    if not isinstance(key, list) or len(key) != 2:
        raise ValidationError("RFC archive operation cursor key tuple is invalid")
    ordinal, member_id = key
    if type(ordinal) is not int or ordinal < 0:
        raise ValidationError("RFC archive operation cursor ordinal is invalid")
    return ordinal, _request_uuid(member_id, field="RFC archive operation cursor member identity")


def _operation_member_from_row(row: Any, operation_id: str) -> RfcArchiveOperationMember:
    rfc_id = _stored_uuid(row[0], field="RFC archive operation member identity")
    pre_revision = row[1]
    archived_revision = row[2]
    ordinal = row[3]
    current_state = str(row[4])
    latest_event_type = str(row[5])
    latest_origin = _stored_uuid(row[6], field="RFC archive latest event origin operation")
    latest_revision = row[7]
    if (
        type(pre_revision) is not int
        or pre_revision <= 0
        or type(archived_revision) is not int
        or archived_revision != pre_revision + 1
        or type(ordinal) is not int
        or ordinal < 0
        or current_state not in _ARCHIVE_STATES
        or latest_event_type not in {"archived", "restored"}
        or type(latest_revision) is not int
        or latest_revision <= 1
    ):
        raise SomaError("PERSISTENCE_FAILURE", "stored RFC archive operation member authority is invalid")
    eligible = (
        current_state == "archived"
        and latest_event_type == "archived"
        and latest_origin == operation_id
    )
    return RfcArchiveOperationMember(
        rfc_id=rfc_id,
        pre_archive_revision=pre_revision,
        archived_revision=archived_revision,
        ordinal=ordinal,
        current_archive_state=current_state,
        latest_event_type=latest_event_type,
        latest_event_origin_archive_operation_id=latest_origin,
        latest_event_resulting_rfc_revision=latest_revision,
        restore_eligible=eligible,
    )


class RfcArchiveQueryService:
    def __init__(self, connection_factory: ConnectionFactory) -> None:
        self._factory = connection_factory

    def preview_from_connection(
        self,
        connection: Any,
        *,
        rfc_id: str,
        scope_kind: str,
        cursor: dict[str, Any] | None = None,
        limit: int = _DEFAULT_LIMIT,
    ) -> RfcArchivePreview:
        limit = _validate_limit(limit)
        canonical_rfc_id = _request_uuid(rfc_id, field="rfc_id")
        canonical_scope_kind = _validate_scope_kind(scope_kind)
        fingerprint, exact_count, changed_count = _stream_scope_fingerprint(
            requested_rfc_id=canonical_rfc_id,
            scope_kind=canonical_scope_kind,
            members=_iter_scope_members(
                connection,
                rfc_id=canonical_rfc_id,
                scope_kind=canonical_scope_kind,
            ),
        )
        after = _validate_preview_cursor(
            cursor,
            rfc_id=canonical_rfc_id,
            scope_kind=canonical_scope_kind,
            scope_fingerprint=fingerprint,
        )
        page_buffer: list[RfcArchiveScopeMember] = []
        after_found = after is None
        for member in _iter_scope_members(
            connection,
            rfc_id=canonical_rfc_id,
            scope_kind=canonical_scope_kind,
        ):
            if not after_found:
                if (member.scope_ordinal, member.rfc_id) == after:
                    after_found = True
                continue
            if len(page_buffer) < limit + 1:
                page_buffer.append(member)
            else:
                break
        if not after_found:
            raise ValidationError("RFC archive preview cursor no longer names a scope member")
        has_more = len(page_buffer) > limit
        page = tuple(page_buffer[:limit])
        continuation = (
            _preview_cursor(
                rfc_id=canonical_rfc_id,
                scope_kind=canonical_scope_kind,
                scope_fingerprint=fingerprint,
                member=page[-1],
            )
            if has_more and page
            else None
        )
        return RfcArchivePreview(
            scope_kind=canonical_scope_kind,
            exact_member_count=exact_count,
            would_change_count=changed_count,
            excluded_prearchived_count=exact_count - changed_count,
            items=page,
            continuation=continuation,
            scope_fingerprint=fingerprint,
        )

    def preview(
        self,
        *,
        rfc_id: str,
        scope_kind: str,
        cursor: dict[str, Any] | None = None,
        limit: int = _DEFAULT_LIMIT,
    ) -> RfcArchivePreview:
        with ReadSnapshot(self._factory) as snapshot:
            return self.preview_from_connection(
                snapshot.connection,
                rfc_id=rfc_id,
                scope_kind=scope_kind,
                cursor=cursor,
                limit=limit,
            )

    @staticmethod
    def _operation_header(connection: Any, operation_id: str) -> tuple[str, str]:
        row = connection.execute(
            "SELECT scope_kind,scope_fingerprint FROM rfc_archive_operations "
            "WHERE rfc_archive_operation_id=?",
            (operation_id,),
        ).fetchone()
        if row is None:
            raise SomaError("RFC_ARCHIVE_OPERATION_NOT_FOUND", "RFC archive operation does not exist")
        scope_kind = str(row[0])
        fingerprint = str(row[1])
        if scope_kind not in _SCOPE_KINDS or _SHA256_HEX_RE.fullmatch(fingerprint) is None:
            raise SomaError("PERSISTENCE_FAILURE", "stored RFC archive operation authority is invalid")
        return scope_kind, fingerprint

    @staticmethod
    def _operation_member_query(
        connection: Any,
        *,
        operation_id: str,
        after: tuple[int, str] | None,
        limit: int | None,
    ):
        predicate = ""
        params: list[object] = [operation_id]
        if after is not None:
            predicate = " AND (m.ordinal>? OR (m.ordinal=? AND m.rfc_id>?))"
            params.extend([after[0], after[0], after[1]])
        sql = (
            "SELECT m.rfc_id,m.pre_archive_revision,m.archived_revision,m.ordinal,r.local_archive_state,"
            "e.event_type,e.origin_archive_operation_id,e.resulting_rfc_revision "
            "FROM rfc_archive_operation_members m "
            "JOIN rfcs r ON r.rfc_id=m.rfc_id "
            "JOIN rfc_archive_events e ON e.rfc_id=m.rfc_id "
            "AND e.resulting_rfc_revision=("
            "SELECT MAX(e2.resulting_rfc_revision) FROM rfc_archive_events e2 WHERE e2.rfc_id=m.rfc_id"
            ") "
            "WHERE m.rfc_archive_operation_id=?"
            f"{predicate} ORDER BY m.ordinal ASC,m.rfc_id ASC"
        )
        if limit is not None:
            sql += " LIMIT ?"
            params.append(limit)
        return connection.execute(sql, tuple(params))

    def get_from_connection(
        self,
        connection: Any,
        *,
        rfc_archive_operation_id: str,
        cursor: dict[str, Any] | None = None,
        limit: int = _DEFAULT_LIMIT,
    ) -> RfcArchiveOperation:
        limit = _validate_limit(limit)
        operation_id = _request_uuid(
            rfc_archive_operation_id,
            field="rfc_archive_operation_id",
        )
        scope_kind, fingerprint = self._operation_header(connection, operation_id)
        after = _validate_operation_cursor(cursor, operation_id)
        exact_count = int(
            connection.execute(
                "SELECT COUNT(*) FROM rfc_archive_operation_members WHERE rfc_archive_operation_id=?",
                (operation_id,),
            ).fetchone()[0]
        )
        rows = self._operation_member_query(
            connection,
            operation_id=operation_id,
            after=after,
            limit=limit + 1,
        ).fetchall()
        parsed = tuple(_operation_member_from_row(row, operation_id) for row in rows[:limit])
        continuation = _operation_cursor(operation_id, parsed[-1]) if len(rows) > limit and parsed else None
        return RfcArchiveOperation(
            rfc_archive_operation_id=operation_id,
            scope_kind=scope_kind,
            scope_fingerprint=fingerprint,
            exact_member_count=exact_count,
            members=parsed,
            continuation=continuation,
        )

    def get(
        self,
        *,
        rfc_archive_operation_id: str,
        cursor: dict[str, Any] | None = None,
        limit: int = _DEFAULT_LIMIT,
    ) -> RfcArchiveOperation:
        with ReadSnapshot(self._factory) as snapshot:
            return self.get_from_connection(
                snapshot.connection,
                rfc_archive_operation_id=rfc_archive_operation_id,
                cursor=cursor,
                limit=limit,
            )

    def load_complete_operation_members_from_connection(
        self,
        connection: Any,
        *,
        rfc_archive_operation_id: str,
    ) -> tuple[str, str, tuple[RfcArchiveOperationMember, ...]]:
        operation_id = _request_uuid(
            rfc_archive_operation_id,
            field="rfc_archive_operation_id",
        )
        scope_kind, fingerprint = self._operation_header(connection, operation_id)
        rows = self._operation_member_query(
            connection,
            operation_id=operation_id,
            after=None,
            limit=None,
        )
        members = tuple(_operation_member_from_row(row, operation_id) for row in rows)
        return scope_kind, fingerprint, members
