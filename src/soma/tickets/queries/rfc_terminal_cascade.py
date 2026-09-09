from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Protocol

from soma.foundation.errors import SomaError, ValidationError
from soma.foundation.identifiers import require_uuid4
from soma.foundation.persistence.connections import ConnectionFactory
from soma.foundation.persistence.uow import ReadSnapshot
from soma.foundation.strict_json import sha256_canonical_json
from soma.tickets.rfc_terminal_cascade import (
    RfcTerminalCascadeRfcMember,
    RfcTerminalCascadeScope,
    RfcTerminalCascadeWfmMember,
    terminal_cascade_scope_fingerprint,
)
from soma.tickets.rfc_terminal_scope import (
    normalize_terminal_cascade_wfm_members,
    resolve_terminal_cascade_rfc_scope,
)

_DEFAULT_LIMIT = 100
_MAX_LIMIT = 500
_PENDING_QUERY_ID = "GetPendingRfcTerminalCascade"
_PENDING_SORT_REGISTRY_ID = "RFC_TERMINAL_CASCADE_MEMBER_ORDER_V1"
_PENDING_FILTER_SCHEMA = "SOMA_RFC_TERMINAL_CASCADE_MEMBER_FILTER_V1"
_PREVIEW_QUERY_ID = "PreviewRfcTerminalCascade"
_PREVIEW_SORT_REGISTRY_ID = "RFC_TERMINAL_CASCADE_IMPACT_ORDER_V1"
_PREVIEW_FILTER_SCHEMA = "SOMA_RFC_TERMINAL_CASCADE_PREVIEW_FILTER_V1"
_PREVIEW_PROFILE = "SOMA_RFC_TERMINAL_CASCADE_PREVIEW_V1"
_NULL_ORDER = "not_applicable"
_SHA256_HEX_RE = re.compile(r"[0-9a-f]{64}\Z")
_TASK_NO_RE = re.compile(r"TK[0-9]{14}\Z")
_WARNING_RE = re.compile(r"[A-Z][A-Z0-9_]{0,63}\Z")
_TERMINAL_CLASSES = frozenset({"terminal_closed", "terminal_cancelled"})
_STALE_REASON_ORDER = (
    "TERMINAL_EPOCH_CHANGED",
    "TERMINAL_EVIDENCE_CHANGED",
    "RFC_OR_WFM_SCOPE_CHANGED",
)
_DOMAIN_ORDINAL = {"TICKETS": 0, "TASKS_OBJECTIVES": 1, "COMMUNICATIONS": 2}


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


@dataclass(frozen=True, slots=True)
class RfcTerminalCascadeProposalSnapshot:
    proposal_id: str
    proposal_revision: int
    trigger_rfc_id: str
    terminal_epoch_id: str
    terminal_status_class: str
    terminal_status_evidence_id: str
    scope_kind: str
    scope_fingerprint: str
    rfc_members: tuple[RfcTerminalCascadeRfcMember, ...]
    wfm_members: tuple[RfcTerminalCascadeWfmMember, ...]


@dataclass(frozen=True, slots=True)
class RfcTerminalCascadeImpactItem:
    domain: str
    impact_kind: str
    entity_type: str
    entity_id: str
    current_state: str | None = None
    resulting_state: str | None = None
    current_count: int | None = None
    resulting_count: int | None = None
    attention_code: str | None = None

    def to_response(self) -> dict[str, Any]:
        return {
            "domain": self.domain,
            "impact_kind": self.impact_kind,
            "entity_type": self.entity_type,
            "entity_id": self.entity_id,
            "current_state": self.current_state,
            "resulting_state": self.resulting_state,
            "current_count": self.current_count,
            "resulting_count": self.resulting_count,
            "attention_code": self.attention_code,
        }


@dataclass(frozen=True, slots=True)
class RfcTerminalCascadeImpactProviderPage:
    domain: str
    status: str
    exact_count: int | None
    provider_fingerprint: str | None
    items: tuple[RfcTerminalCascadeImpactItem, ...] = ()
    continuation_key: tuple[str, str] | None = None
    warning_code: str | None = None


@dataclass(frozen=True, slots=True)
class RfcTerminalCascadePreview:
    proposal_id: str
    proposal_revision: int
    persisted_scope_fingerprint: str
    current_scope_fingerprint: str | None
    persisted_member_count: int
    current_member_count: int
    preview_fingerprint: str
    stale_reasons: tuple[str, ...]
    impacts: tuple[RfcTerminalCascadeImpactItem, ...]
    continuation: dict[str, Any] | None
    warnings: tuple[str, ...]
    execution_ready: bool

    def to_response(self) -> dict[str, Any]:
        return {
            "proposal_id": self.proposal_id,
            "proposal_revision": self.proposal_revision,
            "persisted_scope_fingerprint": self.persisted_scope_fingerprint,
            "current_scope_fingerprint": self.current_scope_fingerprint,
            "persisted_member_count": self.persisted_member_count,
            "current_member_count": self.current_member_count,
            "preview_fingerprint": self.preview_fingerprint,
            "stale_reasons": list(self.stale_reasons),
            "impacts": [item.to_response() for item in self.impacts],
            "continuation": self.continuation,
            "warnings": list(self.warnings),
            "execution_ready": self.execution_ready,
        }


class RfcTerminalTaskPreviewParticipant(Protocol):
    def snapshot_applicable_wfms(
        self,
        snapshot: ReadSnapshot,
        rfc_ids: tuple[str, ...],
    ) -> tuple[RfcTerminalCascadeWfmMember, ...]: ...

    def preview_terminal_cascade(
        self,
        snapshot: ReadSnapshot,
        proposal_snapshot: RfcTerminalCascadeProposalSnapshot,
        after_key: tuple[str, str] | None,
        limit: int,
    ) -> RfcTerminalCascadeImpactProviderPage: ...


class RfcTerminalCommunicationPreviewParticipant(Protocol):
    def preview_terminal_cascade(
        self,
        snapshot: ReadSnapshot,
        proposal_snapshot: RfcTerminalCascadeProposalSnapshot,
        after_key: tuple[str, str] | None,
        limit: int,
    ) -> RfcTerminalCascadeImpactProviderPage: ...


def _validate_uuid(value: object, *, field: str) -> str:
    if not isinstance(value, str):
        raise SomaError("PERSISTENCE_FAILURE", f"stored {field} is not a UUID string")
    try:
        return require_uuid4(value)
    except ValidationError as exc:
        raise SomaError("PERSISTENCE_FAILURE", f"stored {field} is not canonical UUIDv4") from exc


def _request_uuid(value: object, *, field: str) -> str:
    if not isinstance(value, str):
        raise ValidationError(f"{field} must be canonical UUIDv4")
    try:
        return require_uuid4(value)
    except ValidationError as exc:
        raise ValidationError(f"{field} must be canonical UUIDv4") from exc


def _positive_int(value: object, *, field: str) -> int:
    if type(value) is not int or value <= 0:
        raise SomaError("PERSISTENCE_FAILURE", f"stored {field} must be a positive integer")
    return value


def _nonnegative_int(value: object, *, field: str) -> int:
    if type(value) is not int or value < 0:
        raise SomaError("PERSISTENCE_FAILURE", f"stored {field} must be a non-negative integer")
    return value


def _nonempty_text(value: object, *, field: str) -> str:
    if not isinstance(value, str) or not value:
        raise SomaError("PERSISTENCE_FAILURE", f"stored {field} must be non-empty text")
    return value


def _pending_filter_fingerprint(
    *,
    rfc_id: str,
    proposal_id: str,
    proposal_revision: int,
    scope_fingerprint: str,
) -> str:
    return sha256_canonical_json(
        {
            "schema": _PENDING_FILTER_SCHEMA,
            "rfc_id": rfc_id,
            "proposal_id": proposal_id,
            "proposal_revision": proposal_revision,
            "scope_fingerprint": scope_fingerprint,
        }
    )


def _pending_cursor_body(
    *,
    rfc_id: str,
    proposal_id: str,
    proposal_revision: int,
    scope_fingerprint: str,
    last_key: tuple[int, int, str],
) -> dict[str, Any]:
    return {
        "version": 1,
        "query_id": _PENDING_QUERY_ID,
        "sort_registry_id": _PENDING_SORT_REGISTRY_ID,
        "last_key_tuple": [last_key[0], last_key[1], last_key[2]],
        "filter_fingerprint": _pending_filter_fingerprint(
            rfc_id=rfc_id,
            proposal_id=proposal_id,
            proposal_revision=proposal_revision,
            scope_fingerprint=scope_fingerprint,
        ),
        "null_order": _NULL_ORDER,
    }


def _validate_pending_cursor(
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
    if cursor["version"] != 1 or cursor["query_id"] != _PENDING_QUERY_ID:
        raise ValidationError("pending RFC terminal cascade cursor version/query is invalid")
    if cursor["sort_registry_id"] != _PENDING_SORT_REGISTRY_ID or cursor["null_order"] != _NULL_ORDER:
        raise ValidationError("pending RFC terminal cascade cursor sort contract is invalid")
    expected_filter = _pending_filter_fingerprint(
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
    _request_uuid(member_id, field="pending RFC terminal cascade cursor member identity")
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
    def _load_pending(connection: Any, *, rfc_id: str):
        canonical_rfc_id = _request_uuid(rfc_id, field="rfc_id")
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
        terminal_epoch_id = _nonempty_text(row[4], field="terminal epoch identity")
        terminal_status_class = str(row[5])
        if terminal_status_class not in _TERMINAL_CLASSES:
            raise SomaError("PERSISTENCE_FAILURE", "stored terminal cascade status class is invalid")
        terminal_status_evidence_id = _nonempty_text(row[6], field="terminal cascade evidence identity")
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
        connection: Any,
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
            if _TASK_NO_RE.fullmatch(task_no) is None:
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
        connection: Any,
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
        after_key = _validate_pending_cursor(
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
            continuation = _pending_cursor_body(
                rfc_id=canonical_rfc_id,
                proposal_id=state.proposal_id,
                proposal_revision=state.proposal_revision,
                scope_fingerprint=state.scope_fingerprint,
                last_key=(int(last[0]), int(last[1]), str(last[2])),
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


def _impact_key(item: RfcTerminalCascadeImpactItem) -> tuple[str, str]:
    return item.impact_kind, item.entity_id


def _global_impact_key(item: RfcTerminalCascadeImpactItem) -> tuple[int, str, str]:
    return _DOMAIN_ORDINAL[item.domain], item.impact_kind, item.entity_id


def _validate_nullable_count(value: object, *, field: str) -> int | None:
    if value is None:
        return None
    if type(value) is not int or value < 0:
        raise SomaError("RFC_TERMINAL_CASCADE_PARTICIPANT_FAILED", f"{field} must be a non-negative integer or null")
    return value


def _validate_impact_item(
    item: object,
    *,
    expected_domain: str,
) -> RfcTerminalCascadeImpactItem:
    if not isinstance(item, RfcTerminalCascadeImpactItem):
        raise SomaError("RFC_TERMINAL_CASCADE_PARTICIPANT_FAILED", "terminal cascade impact participant returned wrong item type")
    if item.domain != expected_domain:
        raise SomaError("RFC_TERMINAL_CASCADE_PARTICIPANT_FAILED", "terminal cascade impact item belongs to the wrong domain")
    _request_uuid(item.entity_id, field="terminal cascade impact entity_id")
    current_count = _validate_nullable_count(item.current_count, field="terminal cascade current_count")
    resulting_count = _validate_nullable_count(item.resulting_count, field="terminal cascade resulting_count")

    if item.impact_kind == "RFC_TERMINAL_SCOPE_MEMBER":
        valid = (
            expected_domain == "TICKETS"
            and item.entity_type == "RFC"
            and item.current_state in {"root", "subordinate", "standalone"}
            and item.resulting_state == "included"
            and current_count is None
            and resulting_count is None
            and item.attention_code is None
        )
    elif item.impact_kind == "WFM_TERMINATION":
        valid = (
            expected_domain == "TASKS_OBJECTIVES"
            and item.entity_type == "WFM_TASK"
            and item.current_state in {"not_started", "in_progress"}
            and item.resulting_state == "terminated"
            and current_count is None
            and resulting_count is None
            and item.attention_code is None
        )
    elif item.impact_kind == "OBJECTIVE_EXECUTABLE_COUNT":
        valid = (
            expected_domain == "TASKS_OBJECTIVES"
            and item.entity_type == "OBJECTIVE"
            and item.current_state is None
            and item.resulting_state is None
            and current_count is not None
            and resulting_count is not None
            and item.attention_code in {None, "LOST_LAST_EXECUTABLE"}
            and (
                item.attention_code != "LOST_LAST_EXECUTABLE"
                or (current_count > 0 and resulting_count == 0)
            )
        )
    elif item.impact_kind == "RFC_TERMINAL_SUMMARY_FREEZE":
        valid = (
            expected_domain == "COMMUNICATIONS"
            and item.entity_type == "RFC"
            and item.current_state == "live"
            and item.resulting_state == "frozen"
            and current_count is None
            and resulting_count is None
            and item.attention_code is None
        )
    elif item.impact_kind == "RFC_DIRECT_LINK_CLOSE":
        valid = (
            expected_domain == "COMMUNICATIONS"
            and item.entity_type == "COMMUNICATION_LINK"
            and item.current_state == "active"
            and item.resulting_state == "closed"
            and current_count is None
            and resulting_count is None
            and item.attention_code is None
        )
    elif item.impact_kind == "ORPHAN_GRACE_EVALUATION":
        valid = (
            expected_domain == "COMMUNICATIONS"
            and item.entity_type == "COMMUNICATION"
            and item.current_state == "RETAINED"
            and item.resulting_state in {"RETAINED", "ORPHAN_PENDING_PURGE"}
            and current_count is not None
            and resulting_count is not None
            and item.attention_code is None
        )
    else:
        valid = False
    if not valid:
        raise SomaError("RFC_TERMINAL_CASCADE_PARTICIPANT_FAILED", "terminal cascade impact item violates its closed contract")
    return item


def _validate_provider_page(
    page: object,
    *,
    expected_domain: str,
    after_key: tuple[str, str] | None,
    limit: int,
) -> RfcTerminalCascadeImpactProviderPage:
    if not isinstance(page, RfcTerminalCascadeImpactProviderPage):
        raise SomaError("RFC_TERMINAL_CASCADE_PARTICIPANT_FAILED", "terminal cascade preview participant returned wrong page type")
    if page.domain != expected_domain or page.status not in {"READY", "INDETERMINATE"}:
        raise SomaError("RFC_TERMINAL_CASCADE_PARTICIPANT_FAILED", "terminal cascade preview participant page identity/state is invalid")
    if len(page.items) > limit:
        raise SomaError("RFC_TERMINAL_CASCADE_PARTICIPANT_FAILED", "terminal cascade preview participant exceeded requested page bound")
    if page.status == "INDETERMINATE":
        if (
            page.exact_count is not None
            or page.provider_fingerprint is not None
            or page.items
            or page.continuation_key is not None
            or not isinstance(page.warning_code, str)
            or _WARNING_RE.fullmatch(page.warning_code) is None
        ):
            raise SomaError("RFC_TERMINAL_CASCADE_PARTICIPANT_FAILED", "indeterminate terminal cascade participant page is malformed")
        return page

    if type(page.exact_count) is not int or page.exact_count < 0:
        raise SomaError("RFC_TERMINAL_CASCADE_PARTICIPANT_FAILED", "ready terminal cascade participant requires exact_count")
    if not isinstance(page.provider_fingerprint, str) or _SHA256_HEX_RE.fullmatch(page.provider_fingerprint) is None:
        raise SomaError("RFC_TERMINAL_CASCADE_PARTICIPANT_FAILED", "ready terminal cascade participant requires exact fingerprint")
    if page.warning_code is not None:
        raise SomaError("RFC_TERMINAL_CASCADE_PARTICIPANT_FAILED", "ready terminal cascade participant cannot carry warning_code")
    items = tuple(_validate_impact_item(item, expected_domain=expected_domain) for item in page.items)
    keys = tuple(_impact_key(item) for item in items)
    if keys != tuple(sorted(keys)) or len(set(keys)) != len(keys):
        raise SomaError("RFC_TERMINAL_CASCADE_PARTICIPANT_FAILED", "terminal cascade participant impact order is invalid")
    if after_key is not None and any(key <= after_key for key in keys):
        raise SomaError("RFC_TERMINAL_CASCADE_PARTICIPANT_FAILED", "terminal cascade participant page did not advance its keyset")
    if page.exact_count == 0 and (items or page.continuation_key is not None):
        raise SomaError("RFC_TERMINAL_CASCADE_PARTICIPANT_FAILED", "empty terminal cascade participant set returned page evidence")
    if page.exact_count > 0 and after_key is None and not items:
        raise SomaError("RFC_TERMINAL_CASCADE_PARTICIPANT_FAILED", "non-empty terminal cascade participant set returned an empty first page")
    if page.continuation_key is not None:
        if (
            not isinstance(page.continuation_key, tuple)
            or len(page.continuation_key) != 2
            or not isinstance(page.continuation_key[0], str)
            or not isinstance(page.continuation_key[1], str)
            or not items
            or page.continuation_key != keys[-1]
        ):
            raise SomaError("RFC_TERMINAL_CASCADE_PARTICIPANT_FAILED", "terminal cascade participant continuation key is invalid")
        _request_uuid(page.continuation_key[1], field="terminal cascade participant continuation entity_id")
    return RfcTerminalCascadeImpactProviderPage(
        domain=page.domain,
        status=page.status,
        exact_count=page.exact_count,
        provider_fingerprint=page.provider_fingerprint,
        items=items,
        continuation_key=page.continuation_key,
        warning_code=None,
    )


def terminal_cascade_preview_payload(
    *,
    proposal_id: str,
    proposal_revision: int,
    persisted_scope_fingerprint: str,
    current_scope_fingerprint: str | None,
    persisted_member_count: int,
    current_member_count: int,
    stale_reasons: tuple[str, ...],
    task_page: RfcTerminalCascadeImpactProviderPage,
    communication_page: RfcTerminalCascadeImpactProviderPage,
) -> dict[str, Any]:
    def summary(page: RfcTerminalCascadeImpactProviderPage) -> dict[str, Any]:
        return {
            "status": page.status,
            "exact_count": page.exact_count,
            "provider_fingerprint": page.provider_fingerprint,
        }

    return {
        "schema": _PREVIEW_PROFILE,
        "proposal_id": proposal_id,
        "proposal_revision": proposal_revision,
        "persisted_scope_fingerprint": persisted_scope_fingerprint,
        "current_scope_fingerprint": current_scope_fingerprint,
        "persisted_member_count": persisted_member_count,
        "current_member_count": current_member_count,
        "stale_reasons": list(stale_reasons),
        "task_objective_preview": summary(task_page),
        "communication_preview": summary(communication_page),
    }


def terminal_cascade_preview_fingerprint(**kwargs: Any) -> str:
    return sha256_canonical_json(terminal_cascade_preview_payload(**kwargs))


def _preview_filter_fingerprint(
    *,
    proposal_id: str,
    proposal_revision: int,
    preview_fingerprint: str,
) -> str:
    return sha256_canonical_json(
        {
            "schema": _PREVIEW_FILTER_SCHEMA,
            "proposal_id": proposal_id,
            "proposal_revision": proposal_revision,
            "preview_fingerprint": preview_fingerprint,
        }
    )


def _preview_cursor_body(
    *,
    proposal_id: str,
    proposal_revision: int,
    preview_fingerprint: str,
    last_key: tuple[int, str, str],
) -> dict[str, Any]:
    return {
        "version": 1,
        "query_id": _PREVIEW_QUERY_ID,
        "sort_registry_id": _PREVIEW_SORT_REGISTRY_ID,
        "last_key_tuple": [last_key[0], last_key[1], last_key[2]],
        "filter_fingerprint": _preview_filter_fingerprint(
            proposal_id=proposal_id,
            proposal_revision=proposal_revision,
            preview_fingerprint=preview_fingerprint,
        ),
        "null_order": _NULL_ORDER,
    }


def _validate_preview_cursor(
    cursor: Any,
    *,
    proposal_id: str,
    proposal_revision: int,
    preview_fingerprint: str,
) -> tuple[int, str, str] | None:
    if cursor is None:
        return None
    if not isinstance(cursor, dict):
        raise ValidationError("terminal cascade preview cursor must be an object")
    expected = {
        "version",
        "query_id",
        "sort_registry_id",
        "last_key_tuple",
        "filter_fingerprint",
        "null_order",
    }
    if set(cursor) != expected:
        raise ValidationError("terminal cascade preview cursor fields are invalid")
    if cursor["version"] != 1 or cursor["query_id"] != _PREVIEW_QUERY_ID:
        raise ValidationError("terminal cascade preview cursor version/query is invalid")
    if cursor["sort_registry_id"] != _PREVIEW_SORT_REGISTRY_ID or cursor["null_order"] != _NULL_ORDER:
        raise ValidationError("terminal cascade preview cursor sort contract is invalid")
    if cursor["filter_fingerprint"] != _preview_filter_fingerprint(
        proposal_id=proposal_id,
        proposal_revision=proposal_revision,
        preview_fingerprint=preview_fingerprint,
    ):
        raise ValidationError("terminal cascade preview cursor filter fingerprint is stale")
    key = cursor["last_key_tuple"]
    if not isinstance(key, list) or len(key) != 3:
        raise ValidationError("terminal cascade preview cursor key tuple is invalid")
    domain_ordinal, impact_kind, entity_id = key
    if type(domain_ordinal) is not int or domain_ordinal not in {0, 1, 2}:
        raise ValidationError("terminal cascade preview cursor domain is invalid")
    if not isinstance(impact_kind, str) or not impact_kind:
        raise ValidationError("terminal cascade preview cursor impact kind is invalid")
    _request_uuid(entity_id, field="terminal cascade preview cursor entity_id")
    return domain_ordinal, impact_kind, entity_id


class RfcTerminalCascadePreviewService:
    """Read-only cross-domain terminal-cascade preview over one stable snapshot."""

    def __init__(
        self,
        connection_factory: ConnectionFactory,
        task_participant: RfcTerminalTaskPreviewParticipant,
        communication_participant: RfcTerminalCommunicationPreviewParticipant,
    ) -> None:
        self._factory = connection_factory
        self._task_participant = task_participant
        self._communication_participant = communication_participant

    @staticmethod
    def _validate_limit(limit: int) -> int:
        if type(limit) is not int or not 1 <= limit <= _MAX_LIMIT:
            raise ValidationError("terminal cascade preview page size must be an integer from 1 through 500")
        return limit

    @staticmethod
    def _load_pending_state_by_id(connection: Any, *, proposal_id: str) -> RfcTerminalCascadeState:
        canonical_id = _request_uuid(proposal_id, field="proposal_id")
        row = connection.execute(
            "SELECT p.rfc_terminal_cascade_proposal_id,p.trigger_rfc_id,p.proposal_state,p.revision,"
            "p.terminal_epoch_id,p.terminal_status_class,p.terminal_status_evidence_id,p.scope_kind,p.scope_fingerprint,"
            "(SELECT COUNT(*) FROM rfc_terminal_cascade_rfc_members rm WHERE rm.rfc_terminal_cascade_proposal_id=p.rfc_terminal_cascade_proposal_id),"
            "(SELECT COUNT(*) FROM rfc_terminal_cascade_wfm_members wm WHERE wm.rfc_terminal_cascade_proposal_id=p.rfc_terminal_cascade_proposal_id) "
            "FROM rfc_terminal_cascade_proposals p WHERE p.rfc_terminal_cascade_proposal_id=?",
            (canonical_id,),
        ).fetchone()
        if row is None:
            raise SomaError("NOT_FOUND", "RFC terminal cascade proposal does not exist")
        if row[2] != "pending":
            raise SomaError("RFC_TERMINAL_CASCADE_NOT_PENDING", "RFC terminal cascade proposal is not pending")
        return RfcTerminalCascadeQueryService._state_from_row(row)

    @staticmethod
    def _persisted_snapshot(
        connection: Any,
        *,
        state: RfcTerminalCascadeState,
    ) -> RfcTerminalCascadeProposalSnapshot:
        rfc_rows = connection.execute(
            "SELECT rfc_id,captured_rfc_revision,captured_role,ordinal "
            "FROM rfc_terminal_cascade_rfc_members WHERE rfc_terminal_cascade_proposal_id=? "
            "ORDER BY ordinal ASC,rfc_id ASC",
            (state.proposal_id,),
        ).fetchall()
        if len(rfc_rows) != state.captured_rfc_count or not rfc_rows:
            raise SomaError("PERSISTENCE_FAILURE", "terminal cascade proposal RFC count disagrees with immutable membership")
        rfc_members: list[RfcTerminalCascadeRfcMember] = []
        for expected_ordinal, row in enumerate(rfc_rows):
            rfc_id = _validate_uuid(row[0], field="captured RFC identity")
            revision = _positive_int(row[1], field="captured RFC revision")
            role = str(row[2])
            ordinal = _nonnegative_int(row[3], field="captured RFC ordinal")
            if ordinal != expected_ordinal or role not in {"root", "subordinate", "standalone"}:
                raise SomaError("PERSISTENCE_FAILURE", "terminal cascade RFC membership order/role is invalid")
            rfc_members.append(RfcTerminalCascadeRfcMember(rfc_id, revision, role))

        if state.scope_kind == "exact_rfc":
            if len(rfc_members) != 1 or rfc_members[0].rfc_id != state.trigger_rfc_id or rfc_members[0].captured_role != "subordinate":
                raise SomaError("PERSISTENCE_FAILURE", "exact terminal cascade RFC scope is invalid")
        else:
            first = rfc_members[0]
            if first.rfc_id != state.trigger_rfc_id or first.captured_role not in {"root", "standalone"}:
                raise SomaError("PERSISTENCE_FAILURE", "root-branch terminal cascade trigger membership is invalid")
            if first.captured_role == "standalone" and len(rfc_members) != 1:
                raise SomaError("PERSISTENCE_FAILURE", "standalone terminal cascade scope contains subordinate members")
            if first.captured_role == "root":
                children = rfc_members[1:]
                if any(member.captured_role != "subordinate" for member in children):
                    raise SomaError("PERSISTENCE_FAILURE", "root terminal cascade child role is invalid")
                if tuple(member.rfc_id for member in children) != tuple(sorted(member.rfc_id for member in children)):
                    raise SomaError("PERSISTENCE_FAILURE", "root terminal cascade child ordering is invalid")

        wfm_rows = connection.execute(
            "SELECT task_id,owning_rfc_id,captured_task_revision,captured_task_no,ordinal "
            "FROM rfc_terminal_cascade_wfm_members WHERE rfc_terminal_cascade_proposal_id=? "
            "ORDER BY ordinal ASC,task_id ASC",
            (state.proposal_id,),
        ).fetchall()
        if len(wfm_rows) != state.captured_wfm_count:
            raise SomaError("PERSISTENCE_FAILURE", "terminal cascade proposal WFM count disagrees with immutable membership")
        raw_wfms: list[RfcTerminalCascadeWfmMember] = []
        for expected_ordinal, row in enumerate(wfm_rows):
            task_id = _validate_uuid(row[0], field="captured WFM Task identity")
            owning_rfc_id = _validate_uuid(row[1], field="captured WFM owning RFC identity")
            revision = _positive_int(row[2], field="captured WFM Task revision")
            task_no = str(row[3])
            ordinal = _nonnegative_int(row[4], field="captured WFM ordinal")
            if ordinal != expected_ordinal or _TASK_NO_RE.fullmatch(task_no) is None:
                raise SomaError("PERSISTENCE_FAILURE", "terminal cascade WFM membership order/identity is invalid")
            raw_wfms.append(RfcTerminalCascadeWfmMember(task_id, owning_rfc_id, revision, task_no))
        rfc_ids = tuple(member.rfc_id for member in rfc_members)
        normalized_wfms = normalize_terminal_cascade_wfm_members(tuple(raw_wfms), rfc_ids=rfc_ids)
        if tuple(raw_wfms) != normalized_wfms:
            raise SomaError("PERSISTENCE_FAILURE", "persisted terminal cascade WFM ordering is non-canonical")

        recomputed = terminal_cascade_scope_fingerprint(
            trigger_rfc_id=state.trigger_rfc_id,
            terminal_epoch_id=state.terminal_epoch_id,
            terminal_status_class=state.terminal_status_class,
            terminal_status_evidence_id=state.terminal_status_evidence_id,
            scope_kind=state.scope_kind,
            rfc_members=tuple(rfc_members),
            wfm_members=normalized_wfms,
        )
        if recomputed != state.scope_fingerprint:
            raise SomaError("PERSISTENCE_FAILURE", "persisted terminal cascade scope fingerprint disagrees with immutable members")
        return RfcTerminalCascadeProposalSnapshot(
            proposal_id=state.proposal_id,
            proposal_revision=state.proposal_revision,
            trigger_rfc_id=state.trigger_rfc_id,
            terminal_epoch_id=state.terminal_epoch_id,
            terminal_status_class=state.terminal_status_class,
            terminal_status_evidence_id=state.terminal_status_evidence_id,
            scope_kind=state.scope_kind,
            scope_fingerprint=state.scope_fingerprint,
            rfc_members=tuple(rfc_members),
            wfm_members=normalized_wfms,
        )

    def _current_scope(
        self,
        snapshot: ReadSnapshot,
        *,
        proposal: RfcTerminalCascadeProposalSnapshot,
    ) -> tuple[RfcTerminalCascadeScope | None, bool]:
        row = snapshot.connection.execute(
            "SELECT status_class,status_evidence_id,terminal_epoch_id FROM rfc_current_source_projection WHERE rfc_id=?",
            (proposal.trigger_rfc_id,),
        ).fetchone()
        if (
            row is None
            or row[2] is None
            or str(row[2]) != proposal.terminal_epoch_id
            or str(row[0]) not in _TERMINAL_CLASSES
        ):
            return None, False
        current_class = str(row[0])
        current_evidence = _nonempty_text(row[1], field="current RFC terminal evidence identity")
        evidence_changed = (
            current_class != proposal.terminal_status_class
            or current_evidence != proposal.terminal_status_evidence_id
        )
        scope_kind, rfc_members = resolve_terminal_cascade_rfc_scope(
            snapshot.connection,
            trigger_rfc_id=proposal.trigger_rfc_id,
        )
        rfc_ids = tuple(member.rfc_id for member in rfc_members)
        try:
            raw_wfms = self._task_participant.snapshot_applicable_wfms(snapshot, rfc_ids)
        except SomaError:
            raise
        except BaseException as exc:
            raise SomaError(
                "RFC_TERMINAL_CASCADE_PARTICIPANT_FAILED",
                "Task participant failed while selecting current terminal WFM scope",
            ) from exc
        wfm_members = normalize_terminal_cascade_wfm_members(raw_wfms, rfc_ids=rfc_ids)
        fingerprint = terminal_cascade_scope_fingerprint(
            trigger_rfc_id=proposal.trigger_rfc_id,
            terminal_epoch_id=proposal.terminal_epoch_id,
            terminal_status_class=current_class,
            terminal_status_evidence_id=current_evidence,
            scope_kind=scope_kind,
            rfc_members=rfc_members,
            wfm_members=wfm_members,
        )
        return (
            RfcTerminalCascadeScope(
                trigger_rfc_id=proposal.trigger_rfc_id,
                terminal_epoch_id=proposal.terminal_epoch_id,
                terminal_status_class=current_class,
                terminal_status_evidence_id=current_evidence,
                scope_kind=scope_kind,
                rfc_members=rfc_members,
                wfm_members=wfm_members,
                scope_fingerprint=fingerprint,
            ),
            evidence_changed,
        )

    @staticmethod
    def _ticket_impacts(scope: RfcTerminalCascadeScope | None) -> tuple[RfcTerminalCascadeImpactItem, ...]:
        if scope is None:
            return ()
        items = tuple(
            RfcTerminalCascadeImpactItem(
                domain="TICKETS",
                impact_kind="RFC_TERMINAL_SCOPE_MEMBER",
                entity_type="RFC",
                entity_id=member.rfc_id,
                current_state=member.captured_role,
                resulting_state="included",
            )
            for member in scope.rfc_members
        )
        return tuple(sorted(items, key=_impact_key))

    @staticmethod
    def _provider_call(
        participant: Any,
        snapshot: ReadSnapshot,
        proposal: RfcTerminalCascadeProposalSnapshot,
        *,
        expected_domain: str,
        after_key: tuple[str, str] | None,
        limit: int,
    ) -> RfcTerminalCascadeImpactProviderPage:
        try:
            raw = participant.preview_terminal_cascade(snapshot, proposal, after_key, limit)
        except SomaError:
            raise
        except BaseException as exc:
            raise SomaError(
                "RFC_TERMINAL_CASCADE_PARTICIPANT_FAILED",
                f"{expected_domain} terminal cascade preview participant failed",
            ) from exc
        return _validate_provider_page(
            raw,
            expected_domain=expected_domain,
            after_key=after_key,
            limit=limit,
        )

    def _provider_meta(
        self,
        snapshot: ReadSnapshot,
        proposal: RfcTerminalCascadeProposalSnapshot,
    ) -> tuple[RfcTerminalCascadeImpactProviderPage, RfcTerminalCascadeImpactProviderPage]:
        task = self._provider_call(
            self._task_participant,
            snapshot,
            proposal,
            expected_domain="TASKS_OBJECTIVES",
            after_key=None,
            limit=1,
        )
        communication = self._provider_call(
            self._communication_participant,
            snapshot,
            proposal,
            expected_domain="COMMUNICATIONS",
            after_key=None,
            limit=1,
        )
        return task, communication

    @staticmethod
    def _same_provider_authority(
        page: RfcTerminalCascadeImpactProviderPage,
        meta: RfcTerminalCascadeImpactProviderPage,
    ) -> None:
        if (
            page.status != meta.status
            or page.exact_count != meta.exact_count
            or page.provider_fingerprint != meta.provider_fingerprint
        ):
            raise SomaError(
                "RFC_TERMINAL_CASCADE_PARTICIPANT_FAILED",
                "terminal cascade participant authority changed inside one read snapshot",
            )

    def _page_impacts(
        self,
        snapshot: ReadSnapshot,
        *,
        proposal: RfcTerminalCascadeProposalSnapshot,
        ticket_items: tuple[RfcTerminalCascadeImpactItem, ...],
        task_meta: RfcTerminalCascadeImpactProviderPage,
        communication_meta: RfcTerminalCascadeImpactProviderPage,
        after_key: tuple[int, str, str] | None,
        limit: int,
    ) -> tuple[tuple[RfcTerminalCascadeImpactItem, ...], bool]:
        result: list[RfcTerminalCascadeImpactItem] = []
        remaining = limit
        cursor_domain = -1 if after_key is None else after_key[0]

        if cursor_domain <= 0 and remaining:
            local_after = None if after_key is None or cursor_domain < 0 else (after_key[1], after_key[2])
            candidates = tuple(
                item
                for item in ticket_items
                if local_after is None or _impact_key(item) > local_after
            )
            take = candidates[:remaining]
            result.extend(take)
            remaining -= len(take)
            if len(candidates) > len(take):
                return tuple(result), True
            if remaining == 0:
                return tuple(result), bool((task_meta.exact_count or 0) or (communication_meta.exact_count or 0))

        if cursor_domain <= 1 and remaining:
            task_after = (after_key[1], after_key[2]) if after_key is not None and cursor_domain == 1 else None
            task_page = self._provider_call(
                self._task_participant,
                snapshot,
                proposal,
                expected_domain="TASKS_OBJECTIVES",
                after_key=task_after,
                limit=remaining,
            )
            self._same_provider_authority(task_page, task_meta)
            result.extend(task_page.items)
            remaining -= len(task_page.items)
            if task_page.continuation_key is not None:
                return tuple(result), True
            if remaining == 0:
                return tuple(result), bool(communication_meta.exact_count or 0)

        if cursor_domain <= 2 and remaining:
            communication_after = (
                (after_key[1], after_key[2])
                if after_key is not None and cursor_domain == 2
                else None
            )
            communication_page = self._provider_call(
                self._communication_participant,
                snapshot,
                proposal,
                expected_domain="COMMUNICATIONS",
                after_key=communication_after,
                limit=remaining,
            )
            self._same_provider_authority(communication_page, communication_meta)
            result.extend(communication_page.items)
            if communication_page.continuation_key is not None:
                return tuple(result), True

        keys = tuple(_global_impact_key(item) for item in result)
        if keys != tuple(sorted(keys)) or len(set(keys)) != len(keys):
            raise SomaError("PERSISTENCE_FAILURE", "composed terminal cascade impact order is invalid")
        return tuple(result), False

    def preview(
        self,
        *,
        proposal_id: str,
        cursor: dict[str, Any] | None = None,
        limit: int = _DEFAULT_LIMIT,
    ) -> RfcTerminalCascadePreview:
        limit = self._validate_limit(limit)
        with ReadSnapshot(self._factory) as snapshot:
            state = self._load_pending_state_by_id(snapshot.connection, proposal_id=proposal_id)
            proposal = self._persisted_snapshot(snapshot.connection, state=state)
            current_scope, evidence_changed = self._current_scope(snapshot, proposal=proposal)

            stale: set[str] = set()
            if current_scope is None:
                stale.add("TERMINAL_EPOCH_CHANGED")
                current_scope_fingerprint = None
                current_member_count = 0
            else:
                current_scope_fingerprint = current_scope.scope_fingerprint
                current_member_count = len(current_scope.rfc_members) + len(current_scope.wfm_members)
                if evidence_changed:
                    stale.add("TERMINAL_EVIDENCE_CHANGED")
                if current_scope.scope_fingerprint != proposal.scope_fingerprint:
                    stale.add("RFC_OR_WFM_SCOPE_CHANGED")
            stale_reasons = tuple(reason for reason in _STALE_REASON_ORDER if reason in stale)
            persisted_member_count = len(proposal.rfc_members) + len(proposal.wfm_members)

            task_meta, communication_meta = self._provider_meta(snapshot, proposal)
            preview_fingerprint = terminal_cascade_preview_fingerprint(
                proposal_id=proposal.proposal_id,
                proposal_revision=proposal.proposal_revision,
                persisted_scope_fingerprint=proposal.scope_fingerprint,
                current_scope_fingerprint=current_scope_fingerprint,
                persisted_member_count=persisted_member_count,
                current_member_count=current_member_count,
                stale_reasons=stale_reasons,
                task_page=task_meta,
                communication_page=communication_meta,
            )
            after_key = _validate_preview_cursor(
                cursor,
                proposal_id=proposal.proposal_id,
                proposal_revision=proposal.proposal_revision,
                preview_fingerprint=preview_fingerprint,
            )
            warnings = tuple(
                code
                for code in (task_meta.warning_code, communication_meta.warning_code)
                if code is not None
            )
            indeterminate = task_meta.status == "INDETERMINATE" or communication_meta.status == "INDETERMINATE"
            execution_ready = not stale_reasons and not indeterminate
            if indeterminate:
                return RfcTerminalCascadePreview(
                    proposal_id=proposal.proposal_id,
                    proposal_revision=proposal.proposal_revision,
                    persisted_scope_fingerprint=proposal.scope_fingerprint,
                    current_scope_fingerprint=current_scope_fingerprint,
                    persisted_member_count=persisted_member_count,
                    current_member_count=current_member_count,
                    preview_fingerprint=preview_fingerprint,
                    stale_reasons=stale_reasons,
                    impacts=(),
                    continuation=None,
                    warnings=warnings,
                    execution_ready=False,
                )

            ticket_items = self._ticket_impacts(current_scope)
            impacts, has_more = self._page_impacts(
                snapshot,
                proposal=proposal,
                ticket_items=ticket_items,
                task_meta=task_meta,
                communication_meta=communication_meta,
                after_key=after_key,
                limit=limit,
            )
            continuation = None
            if has_more and impacts:
                continuation = _preview_cursor_body(
                    proposal_id=proposal.proposal_id,
                    proposal_revision=proposal.proposal_revision,
                    preview_fingerprint=preview_fingerprint,
                    last_key=_global_impact_key(impacts[-1]),
                )
            return RfcTerminalCascadePreview(
                proposal_id=proposal.proposal_id,
                proposal_revision=proposal.proposal_revision,
                persisted_scope_fingerprint=proposal.scope_fingerprint,
                current_scope_fingerprint=current_scope_fingerprint,
                persisted_member_count=persisted_member_count,
                current_member_count=current_member_count,
                preview_fingerprint=preview_fingerprint,
                stale_reasons=stale_reasons,
                impacts=impacts,
                continuation=continuation,
                warnings=warnings,
                execution_ready=execution_ready,
            )
