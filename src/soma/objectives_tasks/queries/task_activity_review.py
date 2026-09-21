from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any

from soma.foundation.errors import IntegrityFailure, SomaError, ValidationError
from soma.foundation.identifiers import require_uuid4
from soma.foundation.persistence.connections import ConnectionFactory
from soma.foundation.persistence.uow import ReadSnapshot
from soma.foundation.strict_json import sha256_canonical_json

_DECISIONS = frozenset({"distinct_activity", "same_activity", "retry_lineage", "unresolved_source_error"})
_SOURCE_CLASSES = frozenset({"unknown", "active", "complete", "plan_cancel"})
_EXECUTION_STATES = frozenset({"not_started", "in_progress", "ended", "terminated"})
_OUTCOMES = frozenset({"completed", "incomplete", "cancelled_without_execution"})
_QUERY_ID = "WfmActivityRelationshipReviewPreview"
_SORT_REGISTRY_ID = "WFM_ACTIVITY_REVIEW_AFFECTED_TASK_ORDER_V1"
_CURSOR_FILTER_SCHEMA = "SOMA_WFM_ACTIVITY_REVIEW_CURSOR_FILTER_V1"
_FINGERPRINT_SCHEMA = "SOMA_WFM_ACTIVITY_RELATIONSHIP_REVIEW_V1"
_NULL_ORDER = "not_applicable"
_DEFAULT_LIMIT = 100
_MAX_LIMIT = 1000
_SQL_CHUNK = 200


def validate_activity_review_decision(value: object) -> str:
    if not isinstance(value, str) or value not in _DECISIONS:
        raise ValidationError(
            "decision must be distinct_activity, same_activity, retry_lineage, or unresolved_source_error"
        )
    return value


def _request_uuid(value: object, *, field: str) -> str:
    if not isinstance(value, str):
        raise ValidationError(f"{field} must be canonical UUIDv4 text")
    try:
        return require_uuid4(value)
    except ValidationError as exc:
        raise ValidationError(f"{field} must be canonical UUIDv4 text") from exc


def _stored_uuid(value: object, *, field: str) -> str:
    if not isinstance(value, str):
        raise IntegrityFailure(f"stored {field} is not UUID text")
    try:
        return require_uuid4(value)
    except ValidationError as exc:
        raise IntegrityFailure(f"stored {field} is not canonical UUIDv4") from exc


def _canonical_seed_ids(value: Sequence[str]) -> tuple[str, ...]:
    if isinstance(value, (str, bytes)) or not isinstance(value, Sequence):
        raise ValidationError("seed_task_ids must be a sequence of canonical UUIDv4 values")
    if not 2 <= len(value) <= 1000:
        raise ValidationError("seed_task_ids must contain from 2 through 1000 WFM Tasks")
    canonical = tuple(_request_uuid(item, field="seed_task_id") for item in value)
    if len(set(canonical)) != len(canonical):
        raise ValidationError("seed_task_ids must be unique")
    if canonical != tuple(sorted(canonical)):
        raise ValidationError("seed_task_ids must be canonical-sorted by task_id")
    return canonical


def _validate_limit(limit: int) -> int:
    if type(limit) is not int or not 1 <= limit <= _MAX_LIMIT:
        raise ValidationError("affected_limit must be an integer from 1 through 1000")
    return limit


def _is_canonical_task_no(value: object) -> bool:
    return (
        isinstance(value, str)
        and len(value) == 16
        and value[:2] == "TK"
        and all("0" <= character <= "9" for character in value[2:])
    )


@dataclass(frozen=True, slots=True)
class WfmActivitySeedTask:
    task_id: str
    task_revision: int

    def to_response(self) -> dict[str, object]:
        return {"task_id": self.task_id, "task_revision": self.task_revision}


@dataclass(frozen=True, slots=True)
class WfmActivityAffectedTask:
    task_id: str
    task_revision: int
    lineage_revision: int
    activity_lineage_id: str | None
    last_decision: str | None

    def to_response(self) -> dict[str, object]:
        return {
            "task_id": self.task_id,
            "task_revision": self.task_revision,
            "lineage_revision": self.lineage_revision,
            "activity_lineage_id": self.activity_lineage_id,
            "last_decision": self.last_decision,
        }


@dataclass(frozen=True, slots=True)
class WfmCurrentLineage:
    activity_lineage_id: str
    exact_member_count: int

    def to_response(self) -> dict[str, object]:
        return {
            "activity_lineage_id": self.activity_lineage_id,
            "exact_member_count": self.exact_member_count,
        }


@dataclass(frozen=True, slots=True)
class _ActivityAuthority:
    task_id: str
    task_revision: int
    task_no: str
    current_rfc_id: str
    assignment_revision: int
    source_projection_revision: int
    provider_lifecycle_class: str | None
    source_plan_start_utc: int | None
    source_plan_end_utc: int | None
    operational_plan_revision: int
    operational_plan_revision_id: str | None
    operational_plan_start_utc: int | None
    operational_plan_end_utc: int | None
    execution_revision: int
    execution_state: str | None
    outcome_revision: int
    accepted_outcome: str | None
    lineage_revision: int
    activity_lineage_id: str | None
    last_lineage_event_id: str | None
    last_decision: str | None

    def fingerprint_object(self) -> dict[str, object]:
        return {
            "task_id": self.task_id,
            "task_revision": self.task_revision,
            "wfm_identity": {
                "task_no": self.task_no,
                "current_rfc_id": self.current_rfc_id,
                "assignment_revision": self.assignment_revision,
            },
            "source_projection": {
                "revision": self.source_projection_revision,
                "provider_lifecycle_class": self.provider_lifecycle_class,
                "source_plan_interval": None
                if self.source_plan_start_utc is None
                else [self.source_plan_start_utc, self.source_plan_end_utc],
            },
            "operational_plan": {
                "revision": self.operational_plan_revision,
                "plan_revision_id": self.operational_plan_revision_id,
                "interval": None
                if self.operational_plan_start_utc is None
                else [self.operational_plan_start_utc, self.operational_plan_end_utc],
            },
            "execution": {
                "revision": self.execution_revision,
                "state": self.execution_state,
            },
            "outcome": {
                "revision": self.outcome_revision,
                "accepted_outcome": self.accepted_outcome,
            },
            "lineage": {
                "revision": self.lineage_revision,
                "activity_lineage_id": self.activity_lineage_id,
                "last_event_id": self.last_lineage_event_id,
                "last_decision": self.last_decision,
            },
        }

    def to_preview_item(self) -> WfmActivityAffectedTask:
        return WfmActivityAffectedTask(
            task_id=self.task_id,
            task_revision=self.task_revision,
            lineage_revision=self.lineage_revision,
            activity_lineage_id=self.activity_lineage_id,
            last_decision=self.last_decision,
        )

    @property
    def locally_active(self) -> bool:
        if self.accepted_outcome is not None:
            return False
        return self.execution_state not in {"ended", "terminated"}

    @property
    def conflict_interval(self) -> tuple[int, int] | None:
        if self.operational_plan_start_utc is not None:
            assert self.operational_plan_end_utc is not None
            return self.operational_plan_start_utc, self.operational_plan_end_utc
        if self.source_plan_start_utc is not None:
            assert self.source_plan_end_utc is not None
            return self.source_plan_start_utc, self.source_plan_end_utc
        return None


@dataclass(frozen=True, slots=True)
class WfmActivityReviewEvaluation:
    decision: str
    review_fingerprint: str
    seed_tasks: tuple[WfmActivitySeedTask, ...]
    authorities: tuple[_ActivityAuthority, ...]
    current_lineages: tuple[WfmCurrentLineage, ...]
    retry_relation_id: str | None
    retry_relations: tuple[tuple[str, str, str], ...]
    semantic_no_change: bool
    projected_competing_attempt: bool

    @property
    def affected_task_count(self) -> int:
        return len(self.authorities)


@dataclass(frozen=True, slots=True)
class WfmActivityRelationshipReviewPreview:
    decision: str
    review_fingerprint: str
    seed_tasks: tuple[WfmActivitySeedTask, ...]
    affected_task_count: int
    affected_tasks: tuple[WfmActivityAffectedTask, ...]
    affected_continuation: dict[str, object] | None
    current_lineages: tuple[WfmCurrentLineage, ...]
    retry_relation_id: str | None
    semantic_no_change: bool
    projected_competing_attempt: bool

    def to_response(self) -> dict[str, object]:
        return {
            "decision": self.decision,
            "review_fingerprint": self.review_fingerprint,
            "seed_tasks": [item.to_response() for item in self.seed_tasks],
            "affected_task_count": self.affected_task_count,
            "affected_tasks": [item.to_response() for item in self.affected_tasks],
            "affected_continuation": self.affected_continuation,
            "current_lineages": [item.to_response() for item in self.current_lineages],
            "retry_relation_id": self.retry_relation_id,
            "semantic_no_change": self.semantic_no_change,
            "projected_competing_attempt": self.projected_competing_attempt,
        }


def _load_seed_lineages(connection: Any, seed_ids: tuple[str, ...]) -> tuple[str, ...]:
    touched: set[str] = set()
    for offset in range(0, len(seed_ids), _SQL_CHUNK):
        chunk = seed_ids[offset : offset + _SQL_CHUNK]
        placeholders = ",".join("?" for _ in chunk)
        rows = connection.execute(
            f"SELECT task_id,activity_lineage_id FROM task_activity_lineage_current "
            f"WHERE task_id IN ({placeholders}) ORDER BY task_id",
            chunk,
        ).fetchall()
        for row in rows:
            _stored_uuid(row[0], field="activity-lineage Task identity")
            touched.add(_stored_uuid(row[1], field="activity lineage identity"))
    return tuple(sorted(touched))


def _expand_affected_ids(
    connection: Any,
    *,
    seed_ids: tuple[str, ...],
    touched_lineages: tuple[str, ...],
) -> tuple[str, ...]:
    affected = set(seed_ids)
    for offset in range(0, len(touched_lineages), _SQL_CHUNK):
        chunk = touched_lineages[offset : offset + _SQL_CHUNK]
        placeholders = ",".join("?" for _ in chunk)
        rows = connection.execute(
            f"SELECT task_id,activity_lineage_id FROM task_activity_lineage_current "
            f"WHERE activity_lineage_id IN ({placeholders}) ORDER BY activity_lineage_id,task_id",
            chunk,
        ).fetchall()
        for row in rows:
            task_id = _stored_uuid(row[0], field="activity-lineage member Task identity")
            lineage_id = _stored_uuid(row[1], field="activity lineage identity")
            if lineage_id not in touched_lineages:
                raise IntegrityFailure("activity lineage closure returned an unexpected lineage")
            affected.add(task_id)
    return tuple(sorted(affected))


def _load_authorities(connection: Any, task_ids: tuple[str, ...]) -> tuple[_ActivityAuthority, ...]:
    rows_by_id: dict[str, Any] = {}
    for offset in range(0, len(task_ids), _SQL_CHUNK):
        chunk = task_ids[offset : offset + _SQL_CHUNK]
        placeholders = ",".join("?" for _ in chunk)
        rows = connection.execute(
            "SELECT "
            "t.task_id,t.task_kind,t.revision,"
            "w.task_no,w.current_rfc_id,w.assignment_revision,"
            "s.source_projection_revision,s.provider_lifecycle_class,s.source_plan_start_utc,s.source_plan_end_utc,"
            "pc.revision,pc.plan_revision_id,pr.task_id,pr.start_utc,pr.end_utc,"
            "ep.revision,ep.execution_state,"
            "oc.revision,oc.accepted_outcome,"
            "lc.revision,lc.activity_lineage_id,lc.last_event_id,"
            "le.task_id,le.new_lineage_id,le.reason_code "
            "FROM tasks t "
            "LEFT JOIN wfm_task_identities w ON w.task_id=t.task_id "
            "LEFT JOIN wfm_source_projection_cache s ON s.task_id=t.task_id "
            "LEFT JOIN task_plan_current pc ON pc.task_id=t.task_id "
            "LEFT JOIN task_plan_revisions pr ON pr.plan_revision_id=pc.plan_revision_id "
            "LEFT JOIN task_execution_projection ep ON ep.task_id=t.task_id "
            "LEFT JOIN task_outcome_current oc ON oc.task_id=t.task_id "
            "LEFT JOIN task_activity_lineage_current lc ON lc.task_id=t.task_id "
            "LEFT JOIN task_activity_lineage_events le ON le.lineage_event_id=lc.last_event_id "
            f"WHERE t.task_id IN ({placeholders}) ORDER BY t.task_id",
            chunk,
        ).fetchall()
        for row in rows:
            task_id = _stored_uuid(row[0], field="Task identity")
            if task_id in rows_by_id:
                raise IntegrityFailure("activity review authority query returned duplicate Task identity")
            rows_by_id[task_id] = row

    if set(rows_by_id) != set(task_ids):
        raise SomaError("TASK_NOT_FOUND", "one or more reviewed Tasks do not exist")

    authorities: list[_ActivityAuthority] = []
    seen_task_nos: set[str] = set()
    for task_id in task_ids:
        row = rows_by_id[task_id]
        task_kind = str(row[1])
        task_revision = row[2]
        task_no = row[3]
        if task_kind != "wfm" or not _is_canonical_task_no(task_no) or row[4] is None or row[5] is None:
            raise SomaError("TASK_NOT_FOUND", "reviewed Task is not current WFM Task authority")
        assert isinstance(task_no, str)
        if task_no in seen_task_nos:
            raise IntegrityFailure("activity review scope contains duplicate canonical WFM Task No authority")
        seen_task_nos.add(task_no)
        if type(task_revision) is not int or task_revision <= 0:
            raise IntegrityFailure("stored Task revision is invalid")
        current_rfc_id = _stored_uuid(row[4], field="WFM owning RFC identity")
        assignment_revision = row[5]
        if type(assignment_revision) is not int or assignment_revision <= 0:
            raise IntegrityFailure("stored WFM assignment revision is invalid")

        source_revision = 0
        lifecycle: str | None = None
        source_start: int | None = None
        source_end: int | None = None
        if row[6] is not None:
            if type(row[6]) is not int or int(row[6]) <= 0:
                raise IntegrityFailure("stored WFM source projection revision is invalid")
            source_revision = int(row[6])
            lifecycle = str(row[7])
            if lifecycle not in _SOURCE_CLASSES:
                raise IntegrityFailure("stored WFM source lifecycle class is invalid")
            source_start = None if row[8] is None else int(row[8])
            source_end = None if row[9] is None else int(row[9])
            if (source_start is None) != (source_end is None) or (
                source_start is not None and (source_start < 0 or source_end is None or source_end <= source_start)
            ):
                raise IntegrityFailure("stored WFM source plan interval is invalid")
        elif any(row[index] is not None for index in (7, 8, 9)):
            raise IntegrityFailure("stored WFM source projection authority is incomplete")

        plan_revision = 0
        plan_revision_id: str | None = None
        plan_start: int | None = None
        plan_end: int | None = None
        if row[10] is not None:
            if type(row[10]) is not int or int(row[10]) <= 0 or row[11] is None or row[12] is None:
                raise IntegrityFailure("stored operational Task-plan pointer is invalid")
            plan_revision = int(row[10])
            plan_revision_id = _stored_uuid(row[11], field="Task plan revision identity")
            if _stored_uuid(row[12], field="Task plan owner identity") != task_id:
                raise IntegrityFailure("current Task plan points to another Task")
            plan_start, plan_end = int(row[13]), int(row[14])
            if plan_start < 0 or plan_end <= plan_start:
                raise IntegrityFailure("stored operational Task plan interval is invalid")
        elif any(row[index] is not None for index in (11, 12, 13, 14)):
            raise IntegrityFailure("stored operational Task-plan authority is incomplete")

        execution_revision = 0
        execution_state: str | None = None
        if row[15] is not None:
            if type(row[15]) is not int or int(row[15]) <= 0:
                raise IntegrityFailure("stored Task execution revision is invalid")
            execution_revision = int(row[15])
            execution_state = str(row[16])
            if execution_state not in _EXECUTION_STATES:
                raise IntegrityFailure("stored Task execution state is invalid")
        elif row[16] is not None:
            raise IntegrityFailure("stored Task execution authority is incomplete")

        outcome_revision = 0
        accepted_outcome: str | None = None
        if row[17] is not None:
            if type(row[17]) is not int or int(row[17]) <= 0:
                raise IntegrityFailure("stored Task outcome revision is invalid")
            outcome_revision = int(row[17])
            accepted_outcome = str(row[18])
            if accepted_outcome not in _OUTCOMES:
                raise IntegrityFailure("stored Task outcome is invalid")
        elif row[18] is not None:
            raise IntegrityFailure("stored Task outcome authority is incomplete")

        lineage_revision = 0
        lineage_id: str | None = None
        last_event_id: str | None = None
        last_decision: str | None = None
        if row[19] is not None:
            if type(row[19]) is not int or int(row[19]) <= 0:
                raise IntegrityFailure("stored activity-lineage revision is invalid")
            lineage_revision = int(row[19])
            lineage_id = _stored_uuid(row[20], field="activity lineage identity")
            last_event_id = _stored_uuid(row[21], field="activity lineage event identity")
            if row[22] is None or row[23] is None or row[24] is None:
                raise IntegrityFailure("current activity-lineage projection is not bound to immutable history")
            if _stored_uuid(row[22], field="activity lineage event Task identity") != task_id:
                raise IntegrityFailure("current activity-lineage event belongs to another Task")
            if _stored_uuid(row[23], field="activity lineage event new identity") != lineage_id:
                raise IntegrityFailure("current activity-lineage event does not match the current lineage")
            last_decision = str(row[24])
            if last_decision not in _DECISIONS:
                raise IntegrityFailure("stored activity-lineage decision is invalid")
        elif any(row[index] is not None for index in (20, 21, 22, 23, 24)):
            raise IntegrityFailure("stored activity-lineage current authority is incomplete")

        authorities.append(
            _ActivityAuthority(
                task_id=task_id,
                task_revision=int(task_revision),
                task_no=task_no,
                current_rfc_id=current_rfc_id,
                assignment_revision=int(assignment_revision),
                source_projection_revision=source_revision,
                provider_lifecycle_class=lifecycle,
                source_plan_start_utc=source_start,
                source_plan_end_utc=source_end,
                operational_plan_revision=plan_revision,
                operational_plan_revision_id=plan_revision_id,
                operational_plan_start_utc=plan_start,
                operational_plan_end_utc=plan_end,
                execution_revision=execution_revision,
                execution_state=execution_state,
                outcome_revision=outcome_revision,
                accepted_outcome=accepted_outcome,
                lineage_revision=lineage_revision,
                activity_lineage_id=lineage_id,
                last_lineage_event_id=last_event_id,
                last_decision=last_decision,
            )
        )
    return tuple(authorities)


def _load_retry_relations(
    connection: Any,
    affected_ids: tuple[str, ...],
) -> tuple[tuple[str, str, str], ...]:
    rows_by_id: dict[str, tuple[str, str, str]] = {}
    for offset in range(0, len(affected_ids), _SQL_CHUNK):
        chunk = affected_ids[offset : offset + _SQL_CHUNK]
        placeholders = ",".join("?" for _ in chunk)
        params = tuple(chunk) + tuple(chunk)
        rows = connection.execute(
            "SELECT retry_relation_id,predecessor_task_id,successor_task_id FROM task_retry_relations "
            f"WHERE predecessor_task_id IN ({placeholders}) OR successor_task_id IN ({placeholders}) "
            "ORDER BY predecessor_task_id,successor_task_id,retry_relation_id",
            params,
        ).fetchall()
        for row in rows:
            relation = (
                _stored_uuid(row[0], field="Task retry relation identity"),
                _stored_uuid(row[1], field="Task retry predecessor identity"),
                _stored_uuid(row[2], field="Task retry successor identity"),
            )
            previous = rows_by_id.get(relation[0])
            if previous is not None and previous != relation:
                raise IntegrityFailure("retry relation identity resolves to conflicting authority")
            rows_by_id[relation[0]] = relation
    return tuple(sorted(rows_by_id.values(), key=lambda item: (item[1], item[2], item[0])))


def _direct_retry_relation_id(
    seed_ids: tuple[str, ...],
    retry_relations: tuple[tuple[str, str, str], ...],
) -> str | None:
    if len(seed_ids) != 2:
        return None
    seed_set = set(seed_ids)
    matches = [relation for relation in retry_relations if {relation[1], relation[2]} == seed_set]
    if len(matches) > 1:
        raise IntegrityFailure("reviewed Task pair has more than one immutable direct retry relation")
    return None if not matches else matches[0][0]


def _lineage_memberships(authorities: tuple[_ActivityAuthority, ...]) -> tuple[dict[str, object], ...]:
    members: dict[str, list[str]] = {}
    for authority in authorities:
        if authority.activity_lineage_id is not None:
            members.setdefault(authority.activity_lineage_id, []).append(authority.task_id)
    return tuple(
        {
            "activity_lineage_id": lineage_id,
            "task_ids": sorted(task_ids),
        }
        for lineage_id, task_ids in sorted(members.items())
    )


def _current_lineage_summaries(authorities: tuple[_ActivityAuthority, ...]) -> tuple[WfmCurrentLineage, ...]:
    return tuple(
        WfmCurrentLineage(
            activity_lineage_id=str(item["activity_lineage_id"]),
            exact_member_count=len(item["task_ids"]),
        )
        for item in _lineage_memberships(authorities)
    )


def _semantic_no_change(
    *,
    decision: str,
    authorities: tuple[_ActivityAuthority, ...],
) -> bool:
    memberships = _lineage_memberships(authorities)
    member_count = {
        str(item["activity_lineage_id"]): len(item["task_ids"])
        for item in memberships
    }
    if decision == "distinct_activity":
        return all(
            authority.activity_lineage_id is not None
            and member_count.get(authority.activity_lineage_id) == 1
            and authority.last_decision == decision
            for authority in authorities
        )
    lineages = {authority.activity_lineage_id for authority in authorities}
    return (
        None not in lineages
        and len(lineages) == 1
        and all(authority.last_decision == decision for authority in authorities)
    )


def _projected_competing_attempt(
    *,
    decision: str,
    authorities: tuple[_ActivityAuthority, ...],
) -> bool:
    if decision == "distinct_activity":
        return False
    intervals: list[tuple[int, int, str]] = []
    for authority in authorities:
        if not authority.locally_active:
            continue
        interval = authority.conflict_interval
        if interval is None:
            continue
        intervals.append((interval[0], interval[1], authority.task_id))
    if len(intervals) < 2:
        return False
    intervals.sort(key=lambda item: (item[0], item[1], item[2]))
    max_end = intervals[0][1]
    for start, end, _ in intervals[1:]:
        if start < max_end:
            return True
        max_end = max(max_end, end)
    return False


def _review_fingerprint(
    *,
    decision: str,
    seed_tasks: tuple[WfmActivitySeedTask, ...],
    authorities: tuple[_ActivityAuthority, ...],
    retry_relations: tuple[tuple[str, str, str], ...],
) -> str:
    return sha256_canonical_json(
        {
            "schema": _FINGERPRINT_SCHEMA,
            "decision": decision,
            "seed_tasks": [item.to_response() for item in seed_tasks],
            "affected_tasks": [authority.fingerprint_object() for authority in authorities],
            "touched_lineage_membership": list(_lineage_memberships(authorities)),
            "retry_relations": [
                {
                    "retry_relation_id": relation_id,
                    "predecessor_task_id": predecessor_id,
                    "successor_task_id": successor_id,
                }
                for relation_id, predecessor_id, successor_id in retry_relations
            ],
        }
    )


def _cursor_filter_fingerprint(
    *,
    seed_task_ids: tuple[str, ...],
    decision: str,
    review_fingerprint: str,
) -> str:
    return sha256_canonical_json(
        {
            "schema": _CURSOR_FILTER_SCHEMA,
            "seed_task_ids": list(seed_task_ids),
            "decision": decision,
            "review_fingerprint": review_fingerprint,
        }
    )


def _cursor(
    *,
    seed_task_ids: tuple[str, ...],
    decision: str,
    review_fingerprint: str,
    last_task_id: str,
) -> dict[str, object]:
    return {
        "version": 1,
        "query_id": _QUERY_ID,
        "sort_registry_id": _SORT_REGISTRY_ID,
        "last_key_tuple": [last_task_id],
        "filter_fingerprint": _cursor_filter_fingerprint(
            seed_task_ids=seed_task_ids,
            decision=decision,
            review_fingerprint=review_fingerprint,
        ),
        "null_order": _NULL_ORDER,
    }


def _validate_cursor(
    cursor: Any,
    *,
    seed_task_ids: tuple[str, ...],
    decision: str,
    review_fingerprint: str,
) -> str | None:
    if cursor is None:
        return None
    if not isinstance(cursor, dict):
        raise ValidationError("affected_cursor must be a CursorV1 object")
    expected = {
        "version",
        "query_id",
        "sort_registry_id",
        "last_key_tuple",
        "filter_fingerprint",
        "null_order",
    }
    if set(cursor) != expected:
        raise ValidationError("affected_cursor fields are invalid")
    if cursor["version"] != 1 or cursor["query_id"] != _QUERY_ID:
        raise ValidationError("affected_cursor version/query owner is invalid")
    if cursor["sort_registry_id"] != _SORT_REGISTRY_ID or cursor["null_order"] != _NULL_ORDER:
        raise ValidationError("affected_cursor sort contract is invalid")
    expected_filter = _cursor_filter_fingerprint(
        seed_task_ids=seed_task_ids,
        decision=decision,
        review_fingerprint=review_fingerprint,
    )
    if cursor["filter_fingerprint"] != expected_filter:
        raise ValidationError("affected_cursor scope or review fingerprint is stale")
    key = cursor["last_key_tuple"]
    if not isinstance(key, list) or len(key) != 1:
        raise ValidationError("affected_cursor key tuple is invalid")
    return _request_uuid(key[0], field="affected_cursor last Task identity")


class WfmActivityRelationshipReviewQueryService:
    """Pure, fingerprint-bound review authority for WFM activity relationships."""

    def __init__(self, connection_factory: ConnectionFactory) -> None:
        self._factory = connection_factory

    @classmethod
    def evaluate_connection(
        cls,
        connection: Any,
        *,
        seed_task_ids: Sequence[str],
        decision: str,
    ) -> WfmActivityReviewEvaluation:
        canonical_seed_ids = _canonical_seed_ids(seed_task_ids)
        canonical_decision = validate_activity_review_decision(decision)
        touched_lineages = _load_seed_lineages(connection, canonical_seed_ids)
        affected_ids = _expand_affected_ids(
            connection,
            seed_ids=canonical_seed_ids,
            touched_lineages=touched_lineages,
        )
        authorities = _load_authorities(connection, affected_ids)
        authority_by_id = {authority.task_id: authority for authority in authorities}
        seed_tasks = tuple(
            WfmActivitySeedTask(task_id=task_id, task_revision=authority_by_id[task_id].task_revision)
            for task_id in canonical_seed_ids
        )
        retry_relations = _load_retry_relations(connection, affected_ids)
        retry_relation_id = _direct_retry_relation_id(canonical_seed_ids, retry_relations)
        if canonical_decision == "retry_lineage":
            if len(canonical_seed_ids) != 2 or retry_relation_id is None:
                raise SomaError(
                    "TASK_ACTIVITY_LINEAGE_CONFLICT",
                    "retry_lineage requires exactly two Tasks with one existing immutable direct retry edge",
                )
        fingerprint = _review_fingerprint(
            decision=canonical_decision,
            seed_tasks=seed_tasks,
            authorities=authorities,
            retry_relations=retry_relations,
        )
        return WfmActivityReviewEvaluation(
            decision=canonical_decision,
            review_fingerprint=fingerprint,
            seed_tasks=seed_tasks,
            authorities=authorities,
            current_lineages=_current_lineage_summaries(authorities),
            retry_relation_id=retry_relation_id,
            retry_relations=retry_relations,
            semantic_no_change=_semantic_no_change(
                decision=canonical_decision,
                authorities=authorities,
            ),
            projected_competing_attempt=_projected_competing_attempt(
                decision=canonical_decision,
                authorities=authorities,
            ),
        )

    @staticmethod
    def _page(
        evaluation: WfmActivityReviewEvaluation,
        *,
        seed_task_ids: tuple[str, ...],
        affected_cursor: Any,
        affected_limit: int,
    ) -> WfmActivityRelationshipReviewPreview:
        limit = _validate_limit(affected_limit)
        after = _validate_cursor(
            affected_cursor,
            seed_task_ids=seed_task_ids,
            decision=evaluation.decision,
            review_fingerprint=evaluation.review_fingerprint,
        )
        ordered = tuple(authority.to_preview_item() for authority in evaluation.authorities)
        start_index = 0
        if after is not None:
            ids = [item.task_id for item in ordered]
            try:
                start_index = ids.index(after) + 1
            except ValueError as exc:
                raise ValidationError("affected_cursor no longer names a reviewed affected Task") from exc
        page = ordered[start_index : start_index + limit]
        has_more = start_index + len(page) < len(ordered)
        continuation = None
        if has_more:
            if not page:
                raise IntegrityFailure("activity-review paging produced an empty nonterminal page")
            continuation = _cursor(
                seed_task_ids=seed_task_ids,
                decision=evaluation.decision,
                review_fingerprint=evaluation.review_fingerprint,
                last_task_id=page[-1].task_id,
            )
        return WfmActivityRelationshipReviewPreview(
            decision=evaluation.decision,
            review_fingerprint=evaluation.review_fingerprint,
            seed_tasks=evaluation.seed_tasks,
            affected_task_count=evaluation.affected_task_count,
            affected_tasks=page,
            affected_continuation=continuation,
            current_lineages=evaluation.current_lineages,
            retry_relation_id=evaluation.retry_relation_id,
            semantic_no_change=evaluation.semantic_no_change,
            projected_competing_attempt=evaluation.projected_competing_attempt,
        )

    def preview(
        self,
        *,
        seed_task_ids: Sequence[str],
        decision: str,
        affected_cursor: Any = None,
        affected_limit: int = _DEFAULT_LIMIT,
    ) -> WfmActivityRelationshipReviewPreview:
        canonical_seed_ids = _canonical_seed_ids(seed_task_ids)
        canonical_decision = validate_activity_review_decision(decision)
        with ReadSnapshot(self._factory) as snapshot:
            evaluation = self.evaluate_connection(
                snapshot.connection,
                seed_task_ids=canonical_seed_ids,
                decision=canonical_decision,
            )
            return self._page(
                evaluation,
                seed_task_ids=canonical_seed_ids,
                affected_cursor=affected_cursor,
                affected_limit=affected_limit,
            )
