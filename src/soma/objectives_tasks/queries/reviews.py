from __future__ import annotations

from typing import Any

from soma.foundation.errors import IntegrityFailure, SomaError, ValidationError
from soma.foundation.identifiers import require_uuid4
from soma.foundation.persistence.connections import ConnectionFactory
from soma.foundation.persistence.uow import ReadSnapshot
from soma.foundation.strict_json import sha256_canonical_json

from ..repositories.tasks import TaskPlanRepository, TaskRepository, WfmTaskRepository
from ..source_terminal_authority import current_source_projection


def _limit(value: int) -> int:
    if type(value) is not int or not 1 <= value <= 500:
        raise ValidationError("limit must be an integer from 1 through 500")
    return value


class HistoricalObjectiveQueryService:
    def __init__(self, connection_factory: ConnectionFactory) -> None:
        self._factory = connection_factory

    @staticmethod
    def input_fingerprint(reader: Any, task_id: str) -> str:
        identity = require_uuid4(task_id)
        task = TaskRepository.get(reader, identity)
        wfm = WfmTaskRepository.get_identity(reader, identity)
        if task is None or task.task_kind != "wfm" or wfm is None:
            raise SomaError(
                "HISTORICAL_PROPOSAL_NOT_ELIGIBLE",
                "historical Objective proposal requires a current WFM Task",
            )
        source = current_source_projection(reader, identity)
        source_value = None
        if source is not None:
            source_value = {
                "revision": source.source_projection_revision,
                "provider_status_token": source.provider_status_token,
                "provider_lifecycle_class": source.provider_lifecycle_class,
                "start_utc": source.source_plan_start_utc,
                "end_utc": source.source_plan_end_utc,
                "accepted_source_observation_id": source.accepted_source_observation_id,
                "source_base_token": source.source_base_token,
            }
        pointer = TaskPlanRepository.current_pointer(reader, identity)
        plan_value = None
        if pointer is not None:
            plan = TaskPlanRepository.get_revision(reader, pointer.plan_revision_id)
            if plan is None or plan.task_id != identity:
                raise IntegrityFailure(
                    "historical proposal Task plan pointer is invalid"
                )
            plan_value = {
                "current_revision": pointer.revision,
                "plan_revision_id": plan.plan_revision_id,
                "start_utc": plan.start_utc,
                "end_utc": plan.end_utc,
                "origin": plan.origin,
                "source_observation_id": plan.source_observation_id,
            }
        membership = reader.execute(
            "SELECT objective_id,accepted_plan_revision_id,membership_revision,last_event_id "
            "FROM objective_task_membership_current WHERE task_id=?",
            (identity,),
        ).fetchone()
        lock = reader.execute(
            "SELECT explicit_plan_lock,explicit_membership_lock,revision,last_event_id "
            "FROM task_lock_projection WHERE task_id=?",
            (identity,),
        ).fetchone()
        execution_count = int(
            reader.execute(
                "SELECT count(*) FROM task_execution_events WHERE task_id=?",
                (identity,),
            ).fetchone()[0]
        )
        execution = reader.execute(
            "SELECT execution_state,actual_start_utc,actual_end_utc,"
            "effective_termination_utc,revision,last_event_id "
            "FROM task_execution_projection WHERE task_id=?",
            (identity,),
        ).fetchone()
        outcome_count = int(
            reader.execute(
                "SELECT count(*) FROM task_outcome_events WHERE task_id=?",
                (identity,),
            ).fetchone()[0]
        )
        outcome = reader.execute(
            "SELECT outcome_event_id,accepted_outcome,reviewed_at_utc,revision "
            "FROM task_outcome_current WHERE task_id=?",
            (identity,),
        ).fetchone()
        return sha256_canonical_json(
            {
                "schema": "SOMA_HISTORICAL_OBJECTIVE_PROPOSAL_INPUT_V1",
                "task": {
                    "task_id": task.task_id,
                    "task_revision": task.revision,
                    "creation_origin": task.creation_origin,
                },
                "wfm": {
                    "task_no": wfm.task_no,
                    "current_rfc_id": wfm.current_rfc_id,
                    "assignment_revision": wfm.assignment_revision,
                },
                "source": source_value,
                "operational_plan": plan_value,
                "membership": None
                if membership is None
                else {
                    "objective_id": str(membership[0]),
                    "accepted_plan_revision_id": str(membership[1]),
                    "membership_revision": int(membership[2]),
                    "last_event_id": str(membership[3]),
                },
                "explicit_lock": None
                if lock is None
                else {
                    "plan": bool(lock[0]),
                    "membership": bool(lock[1]),
                    "revision": int(lock[2]),
                    "last_event_id": None if lock[3] is None else str(lock[3]),
                },
                "execution": {
                    "event_count": execution_count,
                    "projection": None
                    if execution is None
                    else {
                        "state": str(execution[0]),
                        "actual_start_utc": execution[1],
                        "actual_end_utc": execution[2],
                        "effective_termination_utc": execution[3],
                        "revision": int(execution[4]),
                        "last_event_id": str(execution[5]),
                    },
                },
                "outcome": {
                    "event_count": outcome_count,
                    "current": None
                    if outcome is None
                    else {
                        "event_id": str(outcome[0]),
                        "accepted_outcome": str(outcome[1]),
                        "reviewed_at_utc": int(outcome[2]),
                        "revision": int(outcome[3]),
                    },
                },
            }
        )

    def list_historical_proposals(
        self,
        *,
        state: str | None = None,
        after_created_at_utc: int | None = None,
        after_proposal_id: str | None = None,
        limit: int = 100,
    ) -> dict[str, object]:
        page_limit = _limit(limit)
        if state is not None and state not in {
            "pending",
            "accepted",
            "rejected",
            "superseded",
        }:
            raise ValidationError("historical proposal state filter is invalid")
        after_id = (
            None
            if after_proposal_id is None
            else require_uuid4(after_proposal_id)
        )
        if (after_created_at_utc is None) != (after_id is None):
            raise ValidationError(
                "historical proposal continuation requires both key fields"
            )
        if after_created_at_utc is not None and (
            type(after_created_at_utc) is not int
            or after_created_at_utc < 0
        ):
            raise ValidationError(
                "historical proposal continuation timestamp is invalid"
            )
        clauses: list[str] = []
        params: list[object] = []
        if state is not None:
            clauses.append("p.state=?")
            params.append(state)
        with ReadSnapshot(self._factory) as snapshot:
            total_where = (
                "" if not clauses else " WHERE " + " AND ".join(clauses)
            )
            total = int(
                snapshot.connection.execute(
                    "SELECT count(*) FROM historical_objective_proposals p"
                    + total_where,
                    tuple(params),
                ).fetchone()[0]
            )
            page_clauses = list(clauses)
            page_params = list(params)
            if after_created_at_utc is not None and after_id is not None:
                page_clauses.append(
                    "(p.created_at_utc<? OR "
                    "(p.created_at_utc=? AND p.historical_proposal_id>?))"
                )
                page_params.extend(
                    [after_created_at_utc, after_created_at_utc, after_id]
                )
            where = (
                ""
                if not page_clauses
                else " WHERE " + " AND ".join(page_clauses)
            )
            rows = snapshot.connection.execute(
                "SELECT p.historical_proposal_id,p.task_id,w.task_no,"
                "p.expected_wfm_source_projection_revision,"
                "p.expected_source_plan_start_utc,p.expected_source_plan_end_utc,"
                "p.expected_source_observation_id,"
                "p.expected_matching_operational_plan_revision_id,"
                "p.input_fingerprint,p.state,p.revision,p.created_at_utc "
                "FROM historical_objective_proposals p "
                "JOIN wfm_task_identities w ON w.task_id=p.task_id"
                + where
                + " ORDER BY p.created_at_utc DESC,"
                "p.historical_proposal_id ASC LIMIT ?",
                (*page_params, page_limit + 1),
            ).fetchall()
            page = rows[:page_limit]
            items = [
                {
                    "proposal_id": str(row[0]),
                    "task_id": str(row[1]),
                    "task_no": str(row[2]),
                    "source_projection_revision": int(row[3]),
                    "source_plan": {
                        "start_utc": int(row[4]),
                        "end_utc": int(row[5]),
                    },
                    "source_evidence_id": str(row[6]),
                    "matching_operational_plan_revision_id": (
                        None if row[7] is None else str(row[7])
                    ),
                    "input_fingerprint": str(row[8]),
                    "state": str(row[9]),
                    "revision": int(row[10]),
                    "created_at_utc": int(row[11]),
                }
                for row in page
            ]
            continuation = None
            if len(rows) > page_limit and page:
                last = page[-1]
                continuation = {
                    "created_at_utc": int(last[11]),
                    "proposal_id": str(last[0]),
                }
            return {
                "items": items,
                "continuation": continuation,
                "exact_total": total,
            }


class OperationalReviewQueueQueryService:
    def __init__(self, connection_factory: ConnectionFactory) -> None:
        self._factory = connection_factory

    def objective_review_queue(
        self,
        *,
        as_of_utc: int,
        reason: str | None = None,
        after_objective_id: str | None = None,
        limit: int = 100,
    ) -> dict[str, object]:
        if type(as_of_utc) is not int or as_of_utc < 0:
            raise ValidationError("as_of_utc must be non-negative")
        page_limit = _limit(limit)
        after = None if after_objective_id is None else require_uuid4(after_objective_id)
        with ReadSnapshot(self._factory) as snapshot:
            ids = [
                str(row[0])
                for row in snapshot.connection.execute(
                    "SELECT objective_id FROM objectives "
                    "WHERE superseded_by_objective_id IS NULL ORDER BY objective_id"
                ).fetchall()
            ]
            items: list[dict[str, object]] = []
            for objective_id in ids:
                aggregate = ObjectiveProjectionRepository.aggregate(
                    snapshot.connection, objective_id
                )
                if aggregate is None:
                    raise IntegrityFailure("Objective review queue lacks aggregate authority")
                obj = snapshot.connection.execute(
                    "SELECT revision FROM objectives WHERE objective_id=?",
                    (objective_id,),
                ).fetchone()
                members = ObjectiveProjectionRepository._load_members(
                    snapshot.connection, objective_id
                )
                fingerprint = ObjectiveProjectionRepository._review_fingerprint(
                    objective_id=objective_id,
                    objective_revision=int(obj[0]),
                    superseded_by=None,
                    members=members,
                )
                latest = snapshot.connection.execute(
                    "SELECT review_fingerprint FROM objective_review_events "
                    "WHERE objective_id=? ORDER BY reviewed_at_utc DESC,"
                    "objective_review_event_id DESC LIMIT 1",
                    (objective_id,),
                ).fetchone()
                queue_reason = None
                if aggregate.execution_state == "awaiting_review":
                    queue_reason = (
                        "mixed_outcomes"
                        if aggregate.attention_reason == "mixed_outcomes"
                        else (
                            "lost_last_executable"
                            if aggregate.attention_reason == "lost_last_executable"
                            else "due_unreviewed"
                        )
                    )
                elif latest is not None and str(latest[0]) != fingerprint:
                    queue_reason = "corrected_after_review"
                if queue_reason is None or (reason is not None and queue_reason != reason):
                    continue
                items.append(
                    {
                        "objective_id": objective_id,
                        "reason_code": queue_reason,
                        "aggregate_revision": aggregate.revision,
                        "review_fingerprint": fingerprint,
                        "aggregate_state": aggregate.execution_state,
                    }
                )
            if after is not None:
                items = [item for item in items if str(item["objective_id"]) > after]
            total = len(items)
            page = items[:page_limit]
            return {
                "items": page,
                "continuation": (
                    str(page[-1]["objective_id"])
                    if len(items) > page_limit and page
                    else None
                ),
                "exact_total": total,
            }

    def source_terminal_review_queue(
        self,
        *,
        state: str = "pending",
        after_created_at_utc: int | None = None,
        after_review_id: str | None = None,
        limit: int = 100,
    ) -> dict[str, object]:
        if state != "pending":
            raise ValidationError("source-terminal queue currently exposes pending review authority")
        page_limit = _limit(limit)
        if (after_created_at_utc is None) != (after_review_id is None):
            raise ValidationError("source-terminal cursor requires both fields")
        params: list[object] = [state]
        clause = ""
        if after_created_at_utc is not None:
            if type(after_created_at_utc) is not int or after_created_at_utc < 0:
                raise ValidationError("source-terminal cursor timestamp is invalid")
            review_id = require_uuid4(str(after_review_id))
            clause = " AND (r.created_at_utc>? OR (r.created_at_utc=? AND r.source_terminal_review_id>?))"
            params.extend([after_created_at_utc, after_created_at_utc, review_id])
        with ReadSnapshot(self._factory) as snapshot:
            total = int(
                snapshot.connection.execute(
                    "SELECT COUNT(*) FROM wfm_source_terminal_reviews WHERE state=?",
                    (state,),
                ).fetchone()[0]
            )
            rows = snapshot.connection.execute(
                "SELECT r.source_terminal_review_id,r.task_id,w.task_no,"
                "r.provider_lifecycle_class,r.source_projection_revision,r.input_fingerprint,"
                "r.revision,r.created_at_utc,sp.provider_status_token,"
                "sp.accepted_source_observation_id,m.objective_id,e.execution_state "
                "FROM wfm_source_terminal_reviews r "
                "JOIN wfm_task_identities w ON w.task_id=r.task_id "
                "JOIN wfm_source_projection_cache sp ON sp.task_id=r.task_id "
                "LEFT JOIN objective_task_membership_current m ON m.task_id=r.task_id "
                "LEFT JOIN task_execution_projection e ON e.task_id=r.task_id "
                "WHERE r.state=?"
                + clause
                + " ORDER BY r.created_at_utc,r.source_terminal_review_id LIMIT ?",
                (*params, page_limit + 1),
            ).fetchall()
            page = rows[:page_limit]
            items = []
            for row in page:
                objective_id = None if row[10] is None else str(row[10])
                surviving = None
                if objective_id is not None:
                    surviving = int(
                        snapshot.connection.execute(
                            "SELECT COUNT(*) FROM objective_task_membership_current m "
                            "LEFT JOIN task_execution_projection e ON e.task_id=m.task_id "
                            "WHERE m.objective_id=? AND m.task_id<>? "
                            "AND COALESCE(e.execution_state,'not_started') NOT IN ('ended','terminated')",
                            (objective_id, str(row[1])),
                        ).fetchone()[0]
                    )
                items.append(
                    {
                        "source_terminal_review_id": str(row[0]),
                        "task_id": str(row[1]),
                        "task_no": str(row[2]),
                        "provider_lifecycle_class": str(row[3]),
                        "source_projection_revision": int(row[4]),
                        "input_fingerprint": str(row[5]),
                        "review_revision": int(row[6]),
                        "created_at_utc": int(row[7]),
                        "provider_status_token": None if row[8] is None else str(row[8]),
                        "source_evidence_id": None if row[9] is None else str(row[9]),
                        "local_context": {
                            "objective_id": objective_id,
                            "execution_state": "not_started" if row[11] is None else str(row[11]),
                        },
                        "impact_summary": {
                            "surviving_executable_count": surviving,
                        },
                    }
                )
            continuation = None
            if len(rows) > page_limit and page:
                continuation = {
                    "created_at_utc": int(page[-1][7]),
                    "review_id": str(page[-1][0]),
                }
            return {"items": items, "continuation": continuation, "exact_total": total}


__all__ = ["HistoricalObjectiveQueryService", "OperationalReviewQueueQueryService"]
