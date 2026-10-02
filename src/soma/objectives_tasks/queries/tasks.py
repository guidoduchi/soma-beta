from __future__ import annotations

import re
from typing import Any

from soma.foundation.persistence.connections import ConnectionFactory
from soma.foundation.persistence.uow import ReadSnapshot

from soma.foundation.errors import IntegrityFailure, SomaError, ValidationError
from soma.foundation.identifiers import require_uuid4
from soma.foundation.strict_json import sha256_canonical_json

from ..contracts.objectives_tasks import TaskRelationshipListQueryV1, TaskAttentionListQueryV1, TaskRelationshipPageV1, TaskAttentionPageV1

from .execution_review import _load_execution_authority, _load_outcome_authority

_SHA256 = re.compile(r"[0-9a-f]{64}\Z")


def _connection(reader: Any) -> Any:
    connection = getattr(reader, "connection", None)
    if connection is not None:
        return connection
    if hasattr(reader, "execute"):
        return reader
    raise ValidationError("Task operational evidence reader requires Snapshot, UnitOfWork, or connection")


def _task_id(connection: Any, task_id: str) -> str:
    canonical = require_uuid4(task_id)
    if connection.execute(
        "SELECT 1 FROM tasks WHERE task_id=?",
        (canonical,),
    ).fetchone() is None:
        raise IntegrityFailure("Task operational evidence target does not exist")
    return canonical


class TaskOperationalEvidenceReader:
    """Read-only LLD-05 owner boundary consumed by Inventory/Overview."""

    @classmethod
    def task_execution(cls, reader: Any, task_id: str) -> dict[str, object]:
        connection = _connection(reader)
        canonical = _task_id(connection, task_id)
        authority = _load_execution_authority(connection, canonical)
        return {
            "execution_revision": authority.revision,
            "execution_state": authority.state,
            "actual_start_utc": authority.actual_start_utc,
            "actual_end_utc": authority.actual_end_utc,
            "effective_termination_utc": authority.effective_termination_utc,
            "termination_reason": authority.termination_reason,
            "last_event_id": authority.last_event_id,
        }

    @classmethod
    def task_outcome(
        cls,
        reader: Any,
        task_id: str,
    ) -> dict[str, object] | None:
        connection = _connection(reader)
        canonical = _task_id(connection, task_id)
        authority = _load_outcome_authority(connection, canonical)
        if authority.revision == 0:
            if any(
                value is not None
                for value in (
                    authority.event_id,
                    authority.accepted_outcome,
                    authority.reviewed_at_utc,
                    authority.last_command_id,
                )
            ):
                raise IntegrityFailure("Task outcome absence authority is inconsistent")
            return None
        if (
            authority.event_id is None
            or authority.accepted_outcome is None
            or authority.reviewed_at_utc is None
        ):
            raise IntegrityFailure("Task outcome positive authority is incomplete")
        return {
            "outcome_event_id": authority.event_id,
            "accepted_outcome": authority.accepted_outcome,
            "reviewed_at_utc": authority.reviewed_at_utc,
            "outcome_revision": authority.revision,
        }

    @classmethod
    def objective_context(
        cls,
        reader: Any,
        task_id: str,
    ) -> dict[str, object] | None:
        connection = _connection(reader)
        canonical = _task_id(connection, task_id)
        row = connection.execute(
            "SELECT m.objective_id,m.membership_revision,m.accepted_plan_revision_id,"
            "m.last_event_id,o.revision,e.revision,a.revision,a.aggregate_input_fingerprint,"
            "p.task_id,me.task_id,me.to_objective_id,me.accepted_plan_revision_id "
            "FROM objective_task_membership_current m "
            "JOIN objectives o ON o.objective_id=m.objective_id "
            "JOIN objective_envelope_projection e ON e.objective_id=m.objective_id "
            "JOIN objective_aggregate_projection a ON a.objective_id=m.objective_id "
            "JOIN task_plan_revisions p ON p.plan_revision_id=m.accepted_plan_revision_id "
            "JOIN objective_membership_events me ON me.membership_event_id=m.last_event_id "
            "WHERE m.task_id=?",
            (canonical,),
        ).fetchone()
        if row is None:
            orphan = connection.execute(
                "SELECT 1 FROM objective_task_membership_current WHERE task_id=?",
                (canonical,),
            ).fetchone()
            if orphan is not None:
                raise IntegrityFailure("Task Objective membership authority is incomplete")
            return None

        objective_id = str(row[0])
        membership_revision = row[1]
        accepted_plan_revision_id = str(row[2])
        membership_last_event_id = str(row[3])
        objective_revision = row[4]
        envelope_revision = row[5]
        aggregate_revision = row[6]
        aggregate_fingerprint = row[7]
        for label, value in (
            ("membership_revision", membership_revision),
            ("objective_revision", objective_revision),
            ("envelope_revision", envelope_revision),
            ("aggregate_revision", aggregate_revision),
        ):
            if type(value) is not int or value <= 0:
                raise IntegrityFailure(f"Task Objective {label} is invalid")
        for label, value in (
            ("objective_id", objective_id),
            ("accepted_plan_revision_id", accepted_plan_revision_id),
            ("membership_last_event_id", membership_last_event_id),
        ):
            try:
                require_uuid4(value)
            except ValidationError as exc:
                raise IntegrityFailure(f"Task Objective {label} is invalid") from exc
        if (
            not isinstance(aggregate_fingerprint, str)
            or _SHA256.fullmatch(aggregate_fingerprint) is None
        ):
            raise IntegrityFailure("Task Objective aggregate fingerprint is invalid")
        if str(row[8]) != canonical or str(row[9]) != canonical:
            raise IntegrityFailure("Task Objective membership points to another Task")
        if str(row[10]) != objective_id or str(row[11]) != accepted_plan_revision_id:
            raise IntegrityFailure("Task Objective membership disagrees with immutable event authority")
        return {
            "objective_id": objective_id,
            "membership_revision": int(membership_revision),
            "accepted_plan_revision_id": accepted_plan_revision_id,
            "membership_last_event_id": membership_last_event_id,
            "objective_revision": int(objective_revision),
            "envelope_revision": int(envelope_revision),
            "aggregate_revision": int(aggregate_revision),
            "aggregate_input_fingerprint": aggregate_fingerprint,
        }

    @classmethod
    def review_fingerprint(cls, reader: Any, task_id: str) -> str:
        connection = _connection(reader)
        canonical = _task_id(connection, task_id)
        return sha256_canonical_json(
            {
                "schema": "SOMA_TASK_OPERATIONAL_EVIDENCE_V1",
                "task_id": canonical,
                "execution": cls.task_execution(connection, canonical),
                "outcome": cls.task_outcome(connection, canonical),
                "objective_context": cls.objective_context(connection, canonical),
            }
        )


_RELATIONSHIPS = (
    ("device", "task_device_links", "device_reference_id"),
    ("rfc", "task_rfc_links", "rfc_id"),
    ("sr", "task_sr_links", "service_request_id"),
)
_ATTENTION = (
    ("historical", "historical_proposals", "historical_proposal_id", "historical_objective_proposals", "0"),
    ("regroup", "regroup_proposals", "regroup_proposal_id", "regroup_proposals", "0"),
    ("source_terminal", "source_terminal_reviews", "source_terminal_review_id", "wfm_source_terminal_reviews", "created_at_utc"),
)
_CURSOR_FIELDS = {"version", "query_id", "sort_registry_id", "last_key_tuple", "filter_fingerprint", "null_order"}


def _require_task(connection, identity):
    if connection.execute("SELECT 1 FROM tasks WHERE task_id=?", (identity,)).fetchone() is None:
        raise SomaError("TASK_NOT_FOUND", "Task does not exist")


def _attention_scope(kind):
    if kind == "regroup":
        return ("task_id=? AND EXISTS (SELECT 1 FROM regroup_proposals p "
                "WHERE p.regroup_proposal_id=regroup_proposal_task_changes.regroup_proposal_id AND p.state='pending')")
    return "task_id=? AND state='pending'"


def _attention_summary(connection, identity):
    result = {}
    for kind, label, column, table, order in _ATTENTION:
        if kind == "regroup":
            table = "regroup_proposal_task_changes"
        result[label + "_exact_pending_count"] = int(connection.execute(
            "SELECT COUNT(*) FROM " + table + " WHERE " + _attention_scope(kind), (identity,)
        ).fetchone()[0])
    # No warning_codes field: classification authority is not closed yet.
    return result


def _collection_cursor(query_id, identity, kind, cursor, relationship=False):
    sort = "TASK_RELATIONSHIP_KIND_TARGET_ASC_V1" if relationship else "TASK_ATTENTION_KIND_ORDER_ID_ASC_V1"
    base = {"version": 1, "query_id": query_id, "sort_registry_id": sort, "null_order": "not_applicable"}
    base["filter_fingerprint"] = sha256_canonical_json({**base, "task_id": identity, "kind": kind})
    if cursor is None:
        return base, None
    if not isinstance(cursor, dict) or set(cursor) != _CURSOR_FIELDS:
        raise ValidationError("Task collection cursor fields are invalid")
    if type(cursor["version"]) is not int or any(cursor.get(key) != value for key, value in base.items()):
        raise ValidationError("Task collection cursor identity is invalid")
    key = cursor["last_key_tuple"]
    if not isinstance(key, list) or len(key) != (2 if relationship else 3):
        raise ValidationError("Task collection cursor key is invalid")
    kinds = {item[0] for item in (_RELATIONSHIPS if relationship else _ATTENTION)}
    if not isinstance(key[0], str) or key[0] not in kinds or (kind is not None and key[0] != kind):
        raise ValidationError("Task collection cursor kind is invalid")
    require_uuid4(key[-1])
    if not relationship and (type(key[1]) is not int or key[1] < 0 or (key[0] != "source_terminal" and key[1] != 0)):
        raise ValidationError("Task attention cursor ordering value is invalid")
    return base, key


class TaskQueryService:
    def __init__(self, connection_factory: ConnectionFactory) -> None:
        self._factory = connection_factory

    @staticmethod
    def _limit(value: int) -> int:
        if type(value) is not int or not 1 <= value <= 500:
            raise ValidationError("Task query limit must be in 1..500")
        return value

    def list_tasks(
        self,
        *,
        kind: str | None = None,
        execution_state: str | None = None,
        review_state: str | None = None,
        objective_id: str | None = None,
        rfc_id: str | None = None,
        sr_id: str | None = None,
        historical: bool | None = None,
        operational_count_inclusion: bool | None = None,
        cursor: dict[str, object] | None = None,
        limit: int = 100,
    ) -> dict[str, object]:
        page_limit = self._limit(limit)
        if kind is not None and kind not in {"local", "wfm"}:
            raise ValidationError("Task kind filter is invalid")
        if execution_state is not None and execution_state not in {
            "not_started", "in_progress", "ended", "terminated"
        }:
            raise ValidationError("Task execution-state filter is invalid")
        if review_state is not None and review_state not in {
            "unreviewed", "awaiting_review", "reviewed"
        }:
            raise ValidationError("Task review-state filter is invalid")
        objective = None if objective_id is None else require_uuid4(objective_id)
        rfc = None if rfc_id is None else require_uuid4(rfc_id)
        sr = None if sr_id is None else require_uuid4(sr_id)

        clauses: list[str] = []
        params: list[object] = []
        if kind is not None:
            clauses.append("t.task_kind=?")
            params.append(kind)
        if execution_state is not None:
            clauses.append("COALESCE(e.execution_state,'not_started')=?")
            params.append(execution_state)
        if review_state is not None:
            if review_state == "reviewed":
                clauses.append("oc.task_id IS NOT NULL")
            elif review_state == "awaiting_review":
                clauses.append("oc.task_id IS NULL AND COALESCE(e.execution_state,'not_started') IN ('ended','terminated')")
            else:
                clauses.append("oc.task_id IS NULL AND COALESCE(e.execution_state,'not_started') NOT IN ('ended','terminated')")
        if objective is not None:
            clauses.append("m.objective_id=?")
            params.append(objective)
        if rfc is not None:
            clauses.append(
                "(w.current_rfc_id=? OR EXISTS (SELECT 1 FROM task_rfc_links tr "
                "WHERE tr.task_id=t.task_id AND tr.rfc_id=? AND tr.active=1))"
            )
            params.extend([rfc, rfc])
        if sr is not None:
            clauses.append(
                "(EXISTS (SELECT 1 FROM task_sr_links ts WHERE ts.task_id=t.task_id "
                "AND ts.service_request_id=? AND ts.active=1) OR "
                "EXISTS (SELECT 1 FROM wfm_task_identities wi "
                "LEFT JOIN rfc_hierarchy_edges he ON he.child_rfc_id=wi.current_rfc_id "
                "AND he.edge_state='active' "
                "JOIN sr_rfc_links sl ON sl.rfc_id=COALESCE(he.parent_rfc_id,wi.current_rfc_id) "
                "AND sl.link_state='active' "
                "WHERE wi.task_id=t.task_id AND sl.service_request_id=?))"
            )
            params.extend([sr, sr])
        if historical is not None:
            clauses.append("(t.creation_origin='historical_source')=?")
            params.append(1 if historical else 0)
        if operational_count_inclusion is not None:
            clauses.append("COALESCE(cnt.included,1)=?")
            params.append(1 if operational_count_inclusion else 0)

        base_where = "" if not clauses else " WHERE " + " AND ".join(clauses)
        cursor_clause = ""
        cursor_params: list[object] = []
        if cursor is not None:
            if not isinstance(cursor, dict) or set(cursor) != {"unscheduled", "start_utc", "task_id"}:
                raise ValidationError("Task cursor is invalid")
            unscheduled = cursor["unscheduled"]
            start = cursor["start_utc"]
            task_id = require_uuid4(str(cursor["task_id"]))
            if unscheduled not in {0, 1}:
                raise ValidationError("Task cursor discriminator is invalid")
            if unscheduled == 0:
                if type(start) is not int or start < 0:
                    raise ValidationError("Task cursor start is invalid")
                cursor_clause = (
                    " AND ((CASE WHEN p.start_utc IS NULL THEN 1 ELSE 0 END)>0 "
                    "OR (p.start_utc>? OR (p.start_utc=? AND t.task_id>?)))"
                )
                cursor_params.extend([start, start, task_id])
            else:
                if start is not None:
                    raise ValidationError("unscheduled Task cursor cannot carry start")
                cursor_clause = " AND p.start_utc IS NULL AND t.task_id>?"
                cursor_params.append(task_id)

        select_from = (
            " FROM tasks t "
            "LEFT JOIN wfm_task_identities w ON w.task_id=t.task_id "
            "LEFT JOIN task_plan_current pc ON pc.task_id=t.task_id "
            "LEFT JOIN task_plan_revisions p ON p.plan_revision_id=pc.plan_revision_id "
            "LEFT JOIN objective_task_membership_current m ON m.task_id=t.task_id "
            "LEFT JOIN objectives o ON o.objective_id=m.objective_id "
            "LEFT JOIN task_execution_projection e ON e.task_id=t.task_id "
            "LEFT JOIN task_outcome_current oc ON oc.task_id=t.task_id "
            "LEFT JOIN wfm_source_projection_cache sp ON sp.task_id=t.task_id "
            "LEFT JOIN task_operational_count_current cnt ON cnt.task_id=t.task_id "
        )
        with ReadSnapshot(self._factory) as snapshot:
            total = int(
                snapshot.connection.execute(
                    "SELECT COUNT(*)" + select_from + base_where,
                    tuple(params),
                ).fetchone()[0]
            )
            page_where = base_where
            if cursor_clause:
                page_where = (base_where if base_where else " WHERE 1=1") + cursor_clause
            rows = snapshot.connection.execute(
                "SELECT t.task_id,t.task_kind,t.local_task_name,t.creation_origin,t.revision,"
                "w.task_no,w.current_rfc_id,w.assignment_revision,"
                "pc.plan_revision_id,pc.revision,p.start_utc,p.end_utc,p.origin,"
                "m.objective_id,m.membership_revision,o.tracking_id,"
                "COALESCE(e.execution_state,'not_started'),e.actual_start_utc,e.actual_end_utc,"
                "oc.accepted_outcome,oc.reviewed_at_utc,"
                "sp.provider_status_token,sp.provider_lifecycle_class,sp.source_projection_revision,"
                "COALESCE(cnt.included,1),COALESCE(cnt.revision,0)"
                + select_from
                + page_where
                + " ORDER BY CASE WHEN p.start_utc IS NULL THEN 1 ELSE 0 END,"
                "p.start_utc,t.task_id LIMIT ?",
                (*params, *cursor_params, page_limit + 1),
            ).fetchall()
            page = rows[:page_limit]
            items = []
            for row in page:
                state = str(row[16])
                outcome = None if row[19] is None else str(row[19])
                review = (
                    "reviewed"
                    if outcome is not None
                    else ("awaiting_review" if state in {"ended", "terminated"} else "unreviewed")
                )
                items.append(
                    {
                        "task_id": str(row[0]),
                        "kind": str(row[1]),
                        "display_name": str(row[2]) if row[2] is not None else str(row[5]),
                        "creation_origin": str(row[3]),
                        "revision": int(row[4]),
                        "owning_rfc": None
                        if row[6] is None
                        else {
                            "rfc_id": str(row[6]),
                            "assignment_revision": int(row[7]),
                        },
                        "operational_plan": None
                        if row[8] is None
                        else {
                            "plan_revision_id": str(row[8]),
                            "revision": int(row[9]),
                            "start_utc": int(row[10]),
                            "end_utc": int(row[11]),
                            "origin": str(row[12]),
                        },
                        "membership": None
                        if row[13] is None
                        else {
                            "objective_id": str(row[13]),
                            "membership_revision": int(row[14]),
                            "objective_tracking_id": str(row[15]),
                        },
                        "execution_state": state,
                        "review_state": review,
                        "accepted_outcome": outcome,
                        "provider_source": None
                        if row[22] is None
                        else {
                            "status_token": None if row[21] is None else str(row[21]),
                            "lifecycle_class": str(row[22]),
                            "source_projection_revision": int(row[23]),
                        },
                        "operational_count_included": bool(row[24]),
                        "warnings": [],
                    }
                )
            continuation = None
            if len(rows) > page_limit and page:
                last = page[-1]
                continuation = {
                    "unscheduled": 1 if last[10] is None else 0,
                    "start_utc": None if last[10] is None else int(last[10]),
                    "task_id": str(last[0]),
                }
            return {"items": items, "continuation": continuation, "exact_total": total}

    def list_relationships(self, task_id: str, **decoded) -> TaskRelationshipPageV1:
        request = TaskRelationshipListQueryV1.from_value(decoded)
        identity = require_uuid4(task_id)
        base, key = _collection_cursor("TaskRelationshipList", identity, None, request.cursor, True)
        with ReadSnapshot(self._factory) as snapshot:
            connection = snapshot.connection
            _require_task(connection, identity)
            total = 0
            items = []
            for kind, table, column in _RELATIONSHIPS:
                total += int(connection.execute(
                    f"SELECT COUNT(*) FROM {table} WHERE task_id=? AND active=1", (identity,)
                ).fetchone()[0])
                if key is not None and kind < key[0]:
                    continue
                seek = f" AND {column}>?" if key is not None and kind == key[0] else ""
                params = (identity, key[1], request.limit + 1) if seek else (identity, request.limit + 1)
                rows = connection.execute(
                    f"SELECT link_id,{column} FROM {table} WHERE task_id=? AND active=1" + seek
                    + f" ORDER BY {column} LIMIT ?", params
                ).fetchall()
                items.extend({"kind": kind, "relationship_id": str(row[0]), "related_id": str(row[1])} for row in rows)
            page = items[:request.limit]
            continuation = None
            if len(items) > request.limit:
                last = page[-1]
                continuation = {**base, "last_key_tuple": [last["kind"], last["related_id"]]}
            return {"items": page, "continuation": continuation, "exact_total": total}

    def list_attention(self, task_id: str, **decoded) -> TaskAttentionPageV1:
        request = TaskAttentionListQueryV1.from_value(decoded)
        identity = require_uuid4(task_id)
        base, key = _collection_cursor("TaskAttentionList", identity, request.kind, request.cursor)
        with ReadSnapshot(self._factory) as snapshot:
            connection = snapshot.connection
            _require_task(connection, identity)
            total = 0
            candidates = []
            for kind, label, column, table, order in _ATTENTION:
                if request.kind is not None and kind != request.kind:
                    continue
                source_table = "regroup_proposal_task_changes" if kind == "regroup" else table
                scope = _attention_scope(kind)
                total += int(connection.execute(
                    "SELECT COUNT(*) FROM " + source_table + " WHERE " + scope, (identity,)
                ).fetchone()[0])
                if key is not None and kind < key[0]:
                    continue
                seek = ""
                params = [identity]
                if key is not None and kind == key[0]:
                    if kind == "source_terminal":
                        seek = f" AND (created_at_utc,{column})>(?,?)"
                        params.extend(key[1:])
                    else:
                        seek = f" AND {column}>?"
                        params.append(key[2])
                params.append(request.limit + 1)
                if kind == "regroup":
                    # One Task-indexed joined page; no per-item detail query or global pending set.
                    joined_seek = " AND c.regroup_proposal_id>?" if seek else ""
                    rows = connection.execute(
                        "SELECT p.regroup_proposal_id,p.revision,p.created_at_utc,p.input_fingerprint "
                        "FROM regroup_proposal_task_changes c JOIN regroup_proposals p "
                        "ON p.regroup_proposal_id=c.regroup_proposal_id "
                        "WHERE c.task_id=? AND p.state='pending'" + joined_seek
                        + " ORDER BY c.regroup_proposal_id LIMIT ?", tuple(params)
                    ).fetchall()
                    for row in rows:
                        candidates.append(([kind, 0, str(row[0])], {"kind": kind, "item_id": str(row[0]),
                            "revision": int(row[1]), "created_at_utc": int(row[2]), "input_fingerprint": str(row[3])}))
                else:
                    ordering = f"created_at_utc,{column}" if kind == "source_terminal" else column
                    rows = connection.execute(
                        f"SELECT {column},revision,created_at_utc,input_fingerprint FROM {table} WHERE "
                        + scope + seek + " ORDER BY " + ordering + " LIMIT ?", tuple(params)
                    ).fetchall()
                    for row in rows:
                        candidates.append(([kind, int(row[2]) if kind == "source_terminal" else 0, str(row[0])],
                            {"kind": kind, "item_id": str(row[0]), "revision": int(row[1]),
                             "created_at_utc": int(row[2]), "input_fingerprint": str(row[3])}))
            page = candidates[:request.limit]
            continuation = {**base, "last_key_tuple": page[-1][0]} if len(candidates) > request.limit else None
            return {"items": [item for key, item in page], "continuation": continuation, "exact_total": total}

    def workbench(self, task_id: str) -> dict[str, object]:
        identity = require_uuid4(task_id)
        with ReadSnapshot(self._factory) as snapshot:
            row = snapshot.connection.execute(
                "SELECT t.task_id,t.task_kind,t.local_task_name,t.creation_origin,t.revision,t.created_at_utc,"
                "w.task_no,w.current_rfc_id,w.assignment_revision "
                "FROM tasks t LEFT JOIN wfm_task_identities w ON w.task_id=t.task_id "
                "WHERE t.task_id=?",
                (identity,),
            ).fetchone()
            if row is None:
                raise SomaError("TASK_NOT_FOUND", "Task does not exist")
            current_plan = snapshot.connection.execute(
                "SELECT pc.plan_revision_id,pc.revision,p.start_utc,p.end_utc,p.origin,"
                "p.scheduling_timezone_iana,p.source_observation_id "
                "FROM task_plan_current pc JOIN task_plan_revisions p "
                "ON p.plan_revision_id=pc.plan_revision_id WHERE pc.task_id=?",
                (identity,),
            ).fetchone()
            plan_count = int(
                snapshot.connection.execute(
                    "SELECT COUNT(*) FROM task_plan_revisions WHERE task_id=?",
                    (identity,),
                ).fetchone()[0]
            )
            source = snapshot.connection.execute(
                "SELECT provider_status_token,provider_lifecycle_class,source_plan_start_utc,"
                "source_plan_end_utc,accepted_source_observation_id,source_projection_revision,"
                "source_base_token FROM wfm_source_projection_cache WHERE task_id=?",
                (identity,),
            ).fetchone()
            membership = TaskOperationalEvidenceReader.objective_context(snapshot, identity)
            pinned_plan = None
            if membership is not None:
                pinned_plan = snapshot.connection.execute(
                    "SELECT plan_revision_id,start_utc,end_utc,origin "
                    "FROM task_plan_revisions WHERE plan_revision_id=?",
                    (membership["accepted_plan_revision_id"],),
                ).fetchone()
            execution = TaskOperationalEvidenceReader.task_execution(snapshot, identity)
            outcome = TaskOperationalEvidenceReader.task_outcome(snapshot, identity)
            lock = snapshot.connection.execute(
                "SELECT explicit_plan_lock,explicit_membership_lock,revision,last_event_id "
                "FROM task_lock_projection WHERE task_id=?",
                (identity,),
            ).fetchone()
            retries = snapshot.connection.execute(
                "SELECT predecessor_task_id,successor_task_id,retry_relation_id "
                "FROM task_retry_relations WHERE predecessor_task_id=? OR successor_task_id=?",
                (identity, identity),
            ).fetchall()
            retry = {
                direction: next(({"retry_relation_id": str(edge[2]),
                    "predecessor_task_id": str(edge[0]), "successor_task_id": str(edge[1])}
                    for edge in retries if edge[index] == identity), None)
                for direction, index in (("predecessor", 1), ("successor", 0))
            }
            lineage = snapshot.connection.execute(
                "SELECT activity_lineage_id,revision,last_event_id "
                "FROM task_activity_lineage_current WHERE task_id=?",
                (identity,),
            ).fetchone()
            count = snapshot.connection.execute(
                "SELECT included,revision FROM task_operational_count_current WHERE task_id=?",
                (identity,),
            ).fetchone()
            relationship_counts = {kind: int(snapshot.connection.execute(
                f"SELECT COUNT(*) FROM {table} WHERE task_id=? AND active=1", (identity,)
            ).fetchone()[0]) for kind, table, column in _RELATIONSHIPS}
            relationship_summary = {"exact_total": sum(relationship_counts.values()), "counts_by_kind": relationship_counts}
            attention_summary = _attention_summary(snapshot.connection, identity)

            wfm_context = None
            if row[7] is not None:
                owning_rfc_id = str(row[7])
                rfc = snapshot.connection.execute(
                    "SELECT rfc_id,rfc_no,customer_org_id,revision FROM rfcs WHERE rfc_id=?",
                    (owning_rfc_id,),
                ).fetchone()
                parent = snapshot.connection.execute(
                    "SELECT parent_rfc_id FROM rfc_hierarchy_edges "
                    "WHERE child_rfc_id=? AND edge_state='active'",
                    (owning_rfc_id,),
                ).fetchone()
                root_id = owning_rfc_id if parent is None else str(parent[0])
                sr_rows = snapshot.connection.execute(
                    "SELECT service_request_id FROM sr_rfc_links "
                    "WHERE rfc_id=? AND link_state='active' ORDER BY service_request_id",
                    (root_id,),
                ).fetchall()
                wfm_context = {
                    "owning_rfc_id": owning_rfc_id,
                    "rfc_no": None if rfc is None else str(rfc[1]),
                    "role": "root_or_standalone" if parent is None else "subordinate",
                    "governing_root_rfc_id": root_id,
                    "service_request_ids": [str(item[0]) for item in sr_rows],
                    "customer_org_id": None if rfc is None or rfc[2] is None else str(rfc[2]),
                    "resolution_state": "resolved" if rfc is not None else "unresolved",
                }

            return {
                "task_id": identity,
                "kind": str(row[1]),
                "display_name": str(row[2]) if row[2] is not None else str(row[6]),
                "creation_origin": str(row[3]),
                "revision": int(row[4]),
                "created_at_utc": int(row[5]),
                "wfm_context": wfm_context,
                "provider_source_projection": None
                if source is None
                else {
                    "provider_status_token": None if source[0] is None else str(source[0]),
                    "provider_lifecycle_class": str(source[1]),
                    "source_plan": None
                    if source[2] is None
                    else {"start_utc": int(source[2]), "end_utc": int(source[3])},
                    "accepted_source_observation_id": None if source[4] is None else str(source[4]),
                    "source_projection_revision": int(source[5]),
                    "source_base_token": str(source[6]),
                },
                "operational_plan": None
                if current_plan is None
                else {
                    "plan_revision_id": str(current_plan[0]),
                    "revision": int(current_plan[1]),
                    "start_utc": int(current_plan[2]),
                    "end_utc": int(current_plan[3]),
                    "origin": str(current_plan[4]),
                    "scheduling_timezone_iana": str(current_plan[5]),
                    "source_observation_id": None if current_plan[6] is None else str(current_plan[6]),
                    "history_count": plan_count,
                },
                "objective_membership": membership,
                "membership_pinned_plan": None
                if pinned_plan is None
                else {
                    "plan_revision_id": str(pinned_plan[0]),
                    "start_utc": int(pinned_plan[1]),
                    "end_utc": int(pinned_plan[2]),
                    "origin": str(pinned_plan[3]),
                },
                "actual_execution": execution,
                "reviewed_outcome": outcome,
                "locks": {
                    "explicit_plan_lock": False if lock is None else bool(lock[0]),
                    "explicit_membership_lock": False if lock is None else bool(lock[1]),
                    "revision": 0 if lock is None else int(lock[2]),
                    "effective_plan_lock": (False if lock is None else bool(lock[0]))
                    or execution["execution_state"] != "not_started",
                    "effective_membership_lock": (False if lock is None else bool(lock[1]))
                    or execution["execution_state"] != "not_started",
                },
                "retry": retry,
                "activity_lineage": None
                if lineage is None
                else {
                    "activity_lineage_id": str(lineage[0]),
                    "revision": int(lineage[1]),
                    "last_event_id": str(lineage[2]),
                },
                "relationship_summary": relationship_summary,
                "operational_count": {
                    "included": True if count is None else bool(count[0]),
                    "revision": 0 if count is None else int(count[1]),
                },
                "attention_summary": attention_summary,
            }


__all__ = ["TaskOperationalEvidenceReader", "TaskQueryService"]
