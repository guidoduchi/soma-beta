from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

from soma.foundation.errors import SomaError, ValidationError
from soma.foundation.identifiers import require_uuid4
from soma.foundation.persistence.connections import ConnectionFactory
from soma.foundation.persistence.uow import ReadSnapshot
from soma.foundation.strict_json import sha256_canonical_json

_DEFAULT_LIMIT = 100
_MAX_LIMIT = 500
_QUERY_ID = "GetPendingRfcTerminalCascade"
_SORT_REGISTRY_ID = "RFC_TERMINAL_CASCADE_MEMBER_ORDER_V1"
_FILTER_SCHEMA = "SOMA_RFC_TERMINAL_CASCADE_MEMBER_FILTER_V1"
_NULL_ORDER = "not_applicable"
_SHA256_HEX_RE = re.compile(r"[0-9a-f]{64}\Z")


@dataclass(frozen=True, slots=True)
class RfcTerminalCascadeState:
    proposal_id: str
    trigger_rfc_id: str
    state: str
    proposal_revision: int
    terminal_epoch_id: str
    terminal_status_class: str
    terminal_status_evidence_id: str
    scope_kind: str
    scope_fingerprint: str
    captured_rfc_count: int
    captured_wfm_count: int

    def to_response(self) -> dict[str, Any]:
        return {
            "proposal_id": self.proposal_id,
            "trigger_rfc_id": self.trigger_rfc_id,
            "state": self.state,
            "proposal_revision": self.proposal_revision,
            "terminal_epoch_id": self.terminal_epoch_id,
            "terminal_status_class": self.terminal_status_class,
            "terminal_status_evidence_id": self.terminal_status_evidence_id,
            "scope_kind": self.scope_kind,
            "scope_fingerprint": self.scope_fingerprint,
            "captured_rfc_count": self.captured_rfc_count,
            "captured_wfm_count": self.captured_wfm_count,
        }


@dataclass(frozen=True, slots=True)
class RfcTerminalCascadeRfcCapturedMember:
    rfc_id: str
    captured_rfc_revision: int
    captured_role: str
    ordinal: int
    member_kind: str = "rfc"

    def to_response(self) -> dict[str, Any]:
        return {
            "member_kind": "rfc",
            "rfc_id": self.rfc_id,
            "captured_rfc_revision": self.captured_rfc_revision,
            "captured_role": self.captured_role,
            "ordinal": self.ordinal,
        }


@dataclass(frozen=True, slots=True)
class RfcTerminalCascadeWfmCapturedMember:
    task_id: str
    owning_rfc_id: str
    captured_task_revision: int
    captured_task_no: str
    ordinal: int
    member_kind: str = "wfm"

    def to_response(self) -> dict[str, Any]:
        return {
            "member_kind": "wfm",
            "task_id": self.task_id,
            "owning_rfc_id": self.owning_rfc_id,
            "captured_task_revision": self.captured_task_revision,
            "captured_task_no": self.captured_task_no,
            "ordinal": self.ordinal,
        }


RfcTerminalCascadeCapturedMember = RfcTerminalCascadeRfcCapturedMember | RfcTerminalCascadeWfmCapturedMember


@dataclass(frozen=True, slots=True)
class RfcTerminalCascadeDetail:
    state: RfcTerminalCascadeState
    members: tuple[RfcTerminalCascadeCapturedMember, ...]
    continuation: dict[str, Any] | None

    def to_response(self) -> dict[str, Any]:
        return {
            "state": self.state.to_response(),
            "members": [member.to_response() for member in self.members],
            "continuation": self.continuation,
        }


def _validate_uuid(value: object, *, field: str) -> str:
    if not isinstance(value, str):
        raise SomaError("PERSISTENCE_FAILURE", f"stored {field} is not a UUID string")
    try:
        return require_uuid4(value)
    except ValidationError as exc:
        raise SomaError("PERSISTENCE_FAILURE", f"stored {field} is not canonical UUIDv4") from exc


def _positive_int(value: object, *, field: str) -> int:
    if type(value) is not int or value <= 0:
        raise SomaError("PERSISTENCE_FAILURE", f"stored {field} must be a positive integer")
    return value


def _nonnegative_int(value: object, *, field: str) -> int:
    if type(value) is not int or value < 0:
        raise SomaError("PERSISTENCE_FAILURE", f"stored {field} must be a non-negative integer")
    return value


def _filter_fingerprint(
    *,
    rfc_id: str,
    proposal_id: str,
    proposal_revision: int,
    scope_fingerprint: str,
) -> str:
    return sha256_canonical_json(
        {
            "schema": _FILTER_SCHEMA,
            "rfc_id": rfc_id,
            "proposal_id": proposal_id,
            "proposal_revision": proposal_revision,
            "scope_fingerprint": scope_fingerprint,
        }
    )


def _cursor_body(
    *,
    rfc_id: str,
    proposal_id: str,
    proposal_revision: int,
    scope_fingerprint: str,
    last_key: tuple[int, int, str],
) -> dict[str, Any]:
    return {
        "version": 1,
        "query_id": _QUERY_ID,
        "sort_registry_id": _SORT_REGISTRY_ID,
        "last_key_tuple": [last_key[0], last_key[1], last_key[2]],
        "filter_fingerprint": _filter_fingerprint(
            rfc_id=rfc_id,
            proposal_id=proposal_id,
            proposal_revision=proposal_revision,
            scope_fingerprint=scope_fingerprint,
        ),
        "null_order": _NULL_ORDER,
    }


def _validate_cursor(
    cursor: Any,
    *,
    rfc_id: str,
    proposal_id: str,
    proposal_revision: int,
    scope_fingerprint: str,
) -> tuple[int, int, str] | None:
    if cursor is None:
        return None
    if not isinstance(cursor, dict):
        raise ValidationError("pending RFC terminal cascade cursor must be an object")
    expected = {
        "version",
        "query_id",
        "sort_registry_id",
        "last_key_tuple",
        "filter_fingerprint",
        "null_order",
    }
    if set(cursor) != expected:
        raise ValidationError("pending RFC terminal cascade cursor fields are invalid")
    if cursor["version"] != 1 or cursor["query_id"] != _QUERY_ID:
        raise ValidationError("pending RFC terminal cascade cursor version/query is invalid")
    if cursor["sort_registry_id"] != _SORT_REGISTRY_ID or cursor["null_order"] != _NULL_ORDER:
        raise ValidationError("pending RFC terminal cascade cursor sort contract is invalid")
    expected_filter = _filter_fingerprint(
        rfc_id=rfc_id,
        proposal_id=proposal_id,
        proposal_revision=proposal_revision,
        scope_fingerprint=scope_fingerprint,
    )
    if cursor["filter_fingerprint"] != expected_filter:
        raise ValidationError("pending RFC terminal cascade cursor filter fingerprint is stale")
    key = cursor["last_key_tuple"]
    if not isinstance(key, list) or len(key) != 3:
        raise ValidationError("pending RFC terminal cascade cursor key tuple is invalid")
    kind_ordinal, ordinal, member_id = key
    if type(kind_ordinal) is not int or kind_ordinal not in {0, 1}:
        raise ValidationError("pending RFC terminal cascade cursor member kind is invalid")
    if type(ordinal) is not int or ordinal < 0:
        raise ValidationError("pending RFC terminal cascade cursor ordinal is invalid")
    if not isinstance(member_id, str):
        raise ValidationError("pending RFC terminal cascade cursor member identity is invalid")
    try:
        require_uuid4(member_id)
    except ValidationError as exc:
        raise ValidationError("pending RFC terminal cascade cursor member identity is invalid") from exc
    return kind_ordinal, ordinal, member_id


class RfcTerminalCascadeQueryService:
    """Read-only persisted terminal-cascade proposal/member evidence."""

    def __init__(self, connection_factory: ConnectionFactory) -> None:
        self._factory = connection_factory

    @staticmethod
    def _validate_limit(limit: int) -> int:
        if type(limit) is not int or not 1 <= limit <= _MAX_LIMIT:
            raise ValidationError("terminal cascade page size must be an integer from 1 through 500")
        return limit

    @staticmethod
    def _load_pending(connection, *, rfc_id: str):
        try:
            canonical_rfc_id = require_uuid4(rfc_id)
        except ValidationError as exc:
            raise ValidationError("rfc_id must be canonical UUIDv4") from exc
        if connection.execute("SELECT 1 FROM rfcs WHERE rfc_id=?", (canonical_rfc_id,)).fetchone() is None:
            raise SomaError("NOT_FOUND", "RFC does not exist")
        row = connection.execute(
            "SELECT p.rfc_terminal_cascade_proposal_id,p.trigger_rfc_id,p.proposal_state,p.revision,"
            "p.terminal_epoch_id,p.terminal_status_class,p.terminal_status_evidence_id,p.scope_kind,p.scope_fingerprint,"
            "(SELECT COUNT(*) FROM rfc_terminal_cascade_rfc_members rm "
            " WHERE rm.rfc_terminal_cascade_proposal_id=p.rfc_terminal_cascade_proposal_id),"
            "(SELECT COUNT(*) FROM rfc_terminal_cascade_wfm_members wm "
            " WHERE wm.rfc_terminal_cascade_proposal_id=p.rfc_terminal_cascade_proposal_id) "
            "FROM rfc_terminal_cascade_proposals p "
            "WHERE p.trigger_rfc_id=? AND p.proposal_state='pending'",
            (canonical_rfc_id,),
        ).fetchone()
        if row is None:
            raise SomaError(
                "RFC_TERMINAL_CASCADE_NOT_PENDING",
                "RFC has no current pending terminal cascade proposal",
            )
        return canonical_rfc_id, row

    @staticmethod
    def _state_from_row(row: Any) -> RfcTerminalCascadeState:
        proposal_id = _validate_uuid(row[0], field="terminal cascade proposal identity")
        trigger_rfc_id = _validate_uuid(row[1], field="terminal cascade trigger RFC identity")
        if row[2] != "pending":
            raise SomaError("PERSISTENCE_FAILURE", "pending terminal cascade query resolved non-pending state")
        proposal_revision = _positive_int(row[3], field="terminal cascade proposal revision")
        terminal_epoch_id = _validate_uuid(row[4], field="terminal epoch identity")
        terminal_status_class = str(row[5])
        if terminal_status_class not in {"terminal_closed", "terminal_cancelled"}:
            raise SomaError("PERSISTENCE_FAILURE", "stored terminal cascade status class is invalid")
        if not isinstance(row[6], str) or not row[6]:
            raise SomaError("PERSISTENCE_FAILURE", "stored terminal cascade evidence identity is invalid")
        terminal_status_evidence_id = str(row[6])
        scope_kind = str(row[7])
        if scope_kind not in {"exact_rfc", "root_branch"}:
            raise SomaError("PERSISTENCE_FAILURE", "stored terminal cascade scope kind is invalid")
        scope_fingerprint = str(row[8])
        if _SHA256_HEX_RE.fullmatch(scope_fingerprint) is None:
            raise SomaError("PERSISTENCE_FAILURE", "stored terminal cascade scope fingerprint is invalid")
        captured_rfc_count = _nonnegative_int(row[9], field="captured RFC count")
        captured_wfm_count = _nonnegative_int(row[10], field="captured WFM count")
        if captured_rfc_count < 1:
            raise SomaError("PERSISTENCE_FAILURE", "pending terminal cascade omitted RFC membership")
        return RfcTerminalCascadeState(
            proposal_id=proposal_id,
            trigger_rfc_id=trigger_rfc_id,
            state="pending",
            proposal_revision=proposal_revision,
            terminal_epoch_id=terminal_epoch_id,
            terminal_status_class=terminal_status_class,
            terminal_status_evidence_id=terminal_status_evidence_id,
            scope_kind=scope_kind,
            scope_fingerprint=scope_fingerprint,
            captured_rfc_count=captured_rfc_count,
            captured_wfm_count=captured_wfm_count,
        )

    @staticmethod
    def _member_rows(
        connection,
        *,
        proposal_id: str,
        after_key: tuple[int, int, str] | None,
        limit: int,
    ):
        params: list[object] = [proposal_id, proposal_id]
        predicate = ""
        if after_key is not None:
            kind_ordinal, ordinal, member_id = after_key
            predicate = (
                " WHERE (member_kind_ordinal>? OR "
                "(member_kind_ordinal=? AND ordinal>?) OR "
                "(member_kind_ordinal=? AND ordinal=? AND member_id>?))"
            )
            params.extend([kind_ordinal, kind_ordinal, ordinal, kind_ordinal, ordinal, member_id])
        params.append(limit + 1)
        return connection.execute(
            "SELECT member_kind_ordinal,ordinal,member_id,member_kind,rfc_id,captured_rfc_revision,captured_role,"
            "task_id,owning_rfc_id,captured_task_revision,captured_task_no FROM ("
            "SELECT 0 AS member_kind_ordinal,ordinal,rfc_id AS member_id,'rfc' AS member_kind,"
            "rfc_id,captured_rfc_revision,captured_role,NULL AS task_id,NULL AS owning_rfc_id,"
            "NULL AS captured_task_revision,NULL AS captured_task_no "
            "FROM rfc_terminal_cascade_rfc_members WHERE rfc_terminal_cascade_proposal_id=? "
            "UNION ALL "
            "SELECT 1 AS member_kind_ordinal,ordinal,task_id AS member_id,'wfm' AS member_kind,"
            "NULL AS rfc_id,NULL AS captured_rfc_revision,NULL AS captured_role,task_id,owning_rfc_id,"
            "captured_task_revision,captured_task_no "
            "FROM rfc_terminal_cascade_wfm_members WHERE rfc_terminal_cascade_proposal_id=?"
            ")"
            + predicate
            + " ORDER BY member_kind_ordinal ASC,ordinal ASC,member_id ASC LIMIT ?",
            params,
        ).fetchall()

    @staticmethod
    def _member_from_row(row: Any) -> RfcTerminalCascadeCapturedMember:
        kind_ordinal = _nonnegative_int(row[0], field="cascade member kind ordinal")
        ordinal = _nonnegative_int(row[1], field="cascade member ordinal")
        member_id = _validate_uuid(row[2], field="cascade member identity")
        member_kind = str(row[3])
        if kind_ordinal == 0 and member_kind == "rfc":
            rfc_id = _validate_uuid(row[4], field="captured RFC identity")
            if rfc_id != member_id:
                raise SomaError("PERSISTENCE_FAILURE", "captured RFC member identity disagrees with sort identity")
            revision = _positive_int(row[5], field="captured RFC revision")
            role = str(row[6])
            if role not in {"root", "subordinate", "standalone"}:
                raise SomaError("PERSISTENCE_FAILURE", "captured RFC role is invalid")
            if any(value is not None for value in row[7:11]):
                raise SomaError("PERSISTENCE_FAILURE", "captured RFC row contains WFM fields")
            return RfcTerminalCascadeRfcCapturedMember(
                rfc_id=rfc_id,
                captured_rfc_revision=revision,
                captured_role=role,
                ordinal=ordinal,
            )
        if kind_ordinal == 1 and member_kind == "wfm":
            if any(value is not None for value in row[4:7]):
                raise SomaError("PERSISTENCE_FAILURE", "captured WFM row contains RFC fields")
            task_id = _validate_uuid(row[7], field="captured WFM Task identity")
            if task_id != member_id:
                raise SomaError("PERSISTENCE_FAILURE", "captured WFM identity disagrees with sort identity")
            owning_rfc_id = _validate_uuid(row[8], field="captured WFM owning RFC identity")
            task_revision = _positive_int(row[9], field="captured WFM Task revision")
            task_no = str(row[10])
            if re.fullmatch(r"TK[0-9]{14}", task_no) is None:
                raise SomaError("PERSISTENCE_FAILURE", "captured WFM Task No. is invalid")
            return RfcTerminalCascadeWfmCapturedMember(
                task_id=task_id,
                owning_rfc_id=owning_rfc_id,
                captured_task_revision=task_revision,
                captured_task_no=task_no,
                ordinal=ordinal,
            )
        raise SomaError("PERSISTENCE_FAILURE", "captured terminal cascade member discriminator is invalid")

    def get_from_connection(
        self,
        connection,
        *,
        rfc_id: str,
        cursor: dict[str, Any] | None = None,
        limit: int = _DEFAULT_LIMIT,
    ) -> RfcTerminalCascadeDetail:
        limit = self._validate_limit(limit)
        canonical_rfc_id, proposal_row = self._load_pending(connection, rfc_id=rfc_id)
        state = self._state_from_row(proposal_row)
        if state.trigger_rfc_id != canonical_rfc_id:
            raise SomaError("PERSISTENCE_FAILURE", "pending proposal trigger RFC disagrees with lookup RFC")
        after_key = _validate_cursor(
            cursor,
            rfc_id=canonical_rfc_id,
            proposal_id=state.proposal_id,
            proposal_revision=state.proposal_revision,
            scope_fingerprint=state.scope_fingerprint,
        )
        rows = self._member_rows(
            connection,
            proposal_id=state.proposal_id,
            after_key=after_key,
            limit=limit,
        )
        has_more = len(rows) > limit
        page_rows = rows[:limit]
        members = tuple(self._member_from_row(row) for row in page_rows)
        continuation = None
        if has_more:
            last = page_rows[-1]
            last_key = (
                int(last[0]),
                int(last[1]),
                str(last[2]),
            )
            continuation = _cursor_body(
                rfc_id=canonical_rfc_id,
                proposal_id=state.proposal_id,
                proposal_revision=state.proposal_revision,
                scope_fingerprint=state.scope_fingerprint,
                last_key=last_key,
            )
        return RfcTerminalCascadeDetail(
            state=state,
            members=members,
            continuation=continuation,
        )

    def get(
        self,
        *,
        rfc_id: str,
        cursor: dict[str, Any] | None = None,
        limit: int = _DEFAULT_LIMIT,
    ) -> RfcTerminalCascadeDetail:
        with ReadSnapshot(self._factory) as snapshot:
            return self.get_from_connection(
                snapshot.connection,
                rfc_id=rfc_id,
                cursor=cursor,
                limit=limit,
            )
