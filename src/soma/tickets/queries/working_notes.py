from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from soma.foundation.errors import SomaError, ValidationError
from soma.foundation.identifiers import require_uuid4
from soma.foundation.persistence.connections import ConnectionFactory
from soma.foundation.persistence.uow import ReadSnapshot
from soma.foundation.strict_json import sha256_canonical_json

_DEFAULT_LIMIT = 100
_MAX_LIMIT = 500
_NULL_ORDER = "not_applicable"
_QUERY_ID = "ListWorkingNotes"
_SORT_ID = "WORKING_NOTE_CREATED_ID_ASC_V1"
_FILTER_SCHEMA = "SOMA_WORKING_NOTE_FILTER_V1"
_TARGETS = {
    "service_request": ("service_requests", "service_request_id", "sr_working_notes", "service_request_id"),
    "rfc": ("rfcs", "rfc_id", "rfc_working_notes", "rfc_id"),
}


def _validate_limit(limit: int) -> int:
    if type(limit) is not int or not 1 <= limit <= _MAX_LIMIT:
        raise ValidationError("Working Note page size must be an integer from 1 through 500")
    return limit


def _filter_fingerprint(ticket_type: str, ticket_id: str) -> str:
    return sha256_canonical_json(
        {
            "schema": _FILTER_SCHEMA,
            "ticket_type": ticket_type,
            "ticket_id": ticket_id,
        }
    )


def _cursor_body(ticket_type: str, ticket_id: str, created_at_utc: int, working_note_id: str) -> dict[str, Any]:
    return {
        "version": 1,
        "query_id": _QUERY_ID,
        "sort_registry_id": _SORT_ID,
        "last_key_tuple": [created_at_utc, working_note_id],
        "filter_fingerprint": _filter_fingerprint(ticket_type, ticket_id),
        "null_order": _NULL_ORDER,
    }


def _validate_cursor(cursor: Any, ticket_type: str, ticket_id: str) -> tuple[int, str] | None:
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
        raise ValidationError("Working Note cursor fields are invalid")
    if cursor["version"] != 1 or cursor["query_id"] != _QUERY_ID:
        raise ValidationError("Working Note cursor version/query is invalid")
    if cursor["sort_registry_id"] != _SORT_ID or cursor["null_order"] != _NULL_ORDER:
        raise ValidationError("Working Note cursor sort contract is invalid")
    if cursor["filter_fingerprint"] != _filter_fingerprint(ticket_type, ticket_id):
        raise ValidationError("Working Note cursor filter fingerprint is stale")
    key = cursor["last_key_tuple"]
    if (
        not isinstance(key, list)
        or len(key) != 2
        or type(key[0]) is not int
        or key[0] < 0
        or not isinstance(key[1], str)
    ):
        raise ValidationError("Working Note cursor key tuple is invalid")
    return key[0], require_uuid4(key[1])


@dataclass(frozen=True, slots=True)
class WorkingNoteView:
    working_note_id: str
    body_text: str
    revision: int
    created_at_utc: int
    updated_at_utc: int
    created_by_local_user_profile_id: str

    def to_response(self) -> dict[str, object]:
        return {
            "working_note_id": self.working_note_id,
            "body_text": self.body_text,
            "revision": self.revision,
            "created_at_utc": self.created_at_utc,
            "updated_at_utc": self.updated_at_utc,
            "created_by_local_user_profile_id": self.created_by_local_user_profile_id,
        }


@dataclass(frozen=True, slots=True)
class WorkingNotePage:
    items: tuple[WorkingNoteView, ...]
    continuation: dict[str, Any] | None

    def to_response(self) -> dict[str, object]:
        return {
            "items": [item.to_response() for item in self.items],
            "continuation": self.continuation,
        }


class WorkingNoteQueryService:
    """Exact current Working Note projection with creator identity preserved."""

    def __init__(self, connection_factory: ConnectionFactory) -> None:
        self._factory = connection_factory

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
            raise SomaError("NOT_FOUND", "Working Note owner ticket does not exist")

    def list_notes(
        self,
        *,
        ticket_type: str,
        ticket_id: str,
        cursor: dict[str, Any] | None = None,
        limit: int = _DEFAULT_LIMIT,
    ) -> WorkingNotePage:
        table, id_column, note_table, owner_column = self._target_spec(ticket_type)
        owner_id = require_uuid4(ticket_id)
        page_limit = _validate_limit(limit)
        after = _validate_cursor(cursor, ticket_type, owner_id)

        with ReadSnapshot(self._factory) as snapshot:
            connection = snapshot.connection
            self._require_target(connection, table, id_column, owner_id)
            sql = (
                f"SELECT working_note_id,body_text,revision,created_at_utc,updated_at_utc,created_by_local_user_profile_id "
                f"FROM {note_table} WHERE {owner_column}=? "
            )
            if after is None:
                rows = connection.execute(
                    sql + "ORDER BY created_at_utc ASC,working_note_id ASC LIMIT ?",
                    (owner_id, page_limit + 1),
                ).fetchall()
            else:
                created_at_utc, working_note_id = after
                rows = connection.execute(
                    sql
                    + "AND (created_at_utc>? OR (created_at_utc=? AND working_note_id>?)) "
                    "ORDER BY created_at_utc ASC,working_note_id ASC LIMIT ?",
                    (owner_id, created_at_utc, created_at_utc, working_note_id, page_limit + 1),
                ).fetchall()
            has_more = len(rows) > page_limit
            page_rows = rows[:page_limit]
            items = tuple(
                WorkingNoteView(
                    working_note_id=str(row[0]),
                    body_text=str(row[1]),
                    revision=int(row[2]),
                    created_at_utc=int(row[3]),
                    updated_at_utc=int(row[4]),
                    created_by_local_user_profile_id=str(row[5]),
                )
                for row in page_rows
            )
            continuation = None
            if has_more and page_rows:
                last = page_rows[-1]
                continuation = _cursor_body(
                    ticket_type,
                    owner_id,
                    int(last[3]),
                    str(last[0]),
                )
            return WorkingNotePage(items=items, continuation=continuation)
