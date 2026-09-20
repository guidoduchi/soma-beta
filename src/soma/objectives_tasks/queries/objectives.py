from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any

from soma.foundation.errors import IntegrityFailure, SomaError, ValidationError
from soma.foundation.identifiers import require_uuid4
from soma.foundation.persistence.connections import ConnectionFactory
from soma.foundation.persistence.uow import ReadSnapshot
from soma.foundation.strict_json import sha256_canonical_json

from ..domain.objectives import ObjectiveDraftLocalTaskIntent, ObjectiveExistingTaskIntent
from ..repositories.objectives import ObjectiveProjectionRepository


_MAX_PREVIEW_MEMBERS = 99


def _limit(value: int) -> int:
    if type(value) is not int or not 1 <= value <= 500:
        raise ValidationError("limit must be an integer from 1 through 500")
    return value


@dataclass(frozen=True, slots=True)
class ObjectiveHardDeletePreview:
    status: str
    objective_id: str
    objective_revision: int
    eligibility_fingerprint: str
    blockers: tuple[str, ...]
    member_task_ids: tuple[str, ...]
    membership_event_ids: tuple[str, ...]
    created_command_id: str
    tracking_id: str

    @property
    def eligible(self) -> bool:
        return self.status == "ELIGIBLE"

    def to_response(self) -> dict[str, object]:
        return {
            "eligible": self.eligible,
            "fingerprint": self.eligibility_fingerprint,
            "blockers": list(self.blockers),
        }


class ObjectiveQueryService:
    def __init__(self, connection_factory: ConnectionFactory) -> None:
        self._factory = connection_factory

    @staticmethod
    def _require_relationship_targets(connection: Any, draft: ObjectiveDraftLocalTaskIntent) -> None:
        for values, table, column, field in (
            (draft.service_request_ids, "service_requests", "service_request_id", "service_request_ids"),
            (draft.rfc_ids, "rfcs", "rfc_id", "rfc_ids"),
            (draft.device_reference_ids, "device_references", "device_reference_id", "device_reference_ids"),
        ):
            if not values:
                continue
            placeholders = ",".join("?" for _ in values)
            rows = connection.execute(
                f"SELECT {column} FROM {table} WHERE {column} IN ({placeholders})",
                values,
            ).fetchall()
            if {str(row[0]) for row in rows} != set(values):
                raise SomaError("TASK_STALE", f"{field} contains a missing relationship target")

    @classmethod
    def evaluate_creation(
        cls,
        connection: Any,
        *,
        existing_tasks: Sequence[ObjectiveExistingTaskIntent] = (),
        draft_tasks: Sequence[ObjectiveDraftLocalTaskIntent] = (),
    ) -> dict[str, object]:
        if isinstance(existing_tasks, (str, bytes)) or isinstance(draft_tasks, (str, bytes)):
            raise ValidationError("Objective preview inputs must be sequences")
        existing = tuple(item.validate() for item in existing_tasks)
        drafts = tuple(item.validate() for item in draft_tasks)
        if not existing and not drafts:
            raise SomaError("OBJECTIVE_EMPTY", "Objective requires at least one Task")
        if len(existing) + len(drafts) > _MAX_PREVIEW_MEMBERS:
            raise SomaError(
                "GROUPING_INDETERMINATE",
                "Objective creation exceeds the bounded interactive preview scope",
            )
        if len({item.task_id for item in existing}) != len(existing):
            raise ValidationError("Objective preview contains duplicate existing Tasks")

        prospective: list[dict[str, object]] = []
        current_memberships: list[dict[str, object]] = []
        for item in sorted(existing, key=lambda value: value.task_id):
            row = connection.execute(
                "SELECT t.revision,pc.revision,pc.plan_revision_id,p.start_utc,p.end_utc,"
                "COALESCE(l.revision,0),COALESCE(l.explicit_membership_lock,0),"
                "m.objective_id,m.membership_revision "
                "FROM tasks t "
                "LEFT JOIN task_plan_current pc ON pc.task_id=t.task_id "
                "LEFT JOIN task_plan_revisions p ON p.plan_revision_id=pc.plan_revision_id "
                "LEFT JOIN task_lock_projection l ON l.task_id=t.task_id "
                "LEFT JOIN objective_task_membership_current m ON m.task_id=t.task_id "
                "WHERE t.task_id=?",
                (item.task_id,),
            ).fetchone()
            if row is None:
                raise SomaError("TASK_NOT_FOUND", "Objective member Task does not exist")
            if (
                int(row[0]) != item.expected_task_revision
                or row[1] is None
                or int(row[1]) != item.expected_plan_revision
                or row[2] is None
                or str(row[2]) != item.expected_plan_revision_id
            ):
                raise SomaError("TASK_STALE", "Objective member Task or current plan changed")
            if row[3] is None or row[4] is None or int(row[4]) <= int(row[3]):
                raise SomaError("TASK_PLAN_INCOMPLETE", "Objective member lacks a complete accepted plan")
            if int(row[6]) == 1:
                raise SomaError("GROUPING_INDETERMINATE", "Objective member has an explicit membership lock")
            current_objective_id = None if row[7] is None else str(row[7])
            current_membership_revision = None if row[8] is None else int(row[8])
            if current_objective_id is not None:
                current_memberships.append(
                    {
                        "task_id": item.task_id,
                        "objective_id": current_objective_id,
                        "membership_revision": current_membership_revision,
                    }
                )
            prospective.append(
                {
                    "kind": "existing",
                    "task_id": item.task_id,
                    "task_revision": item.expected_task_revision,
                    "plan_revision": item.expected_plan_revision,
                    "plan_revision_id": item.expected_plan_revision_id,
                    "start_utc": int(row[3]),
                    "end_utc": int(row[4]),
                    "lock_revision": int(row[5]),
                    "current_objective_id": current_objective_id,
                    "current_membership_revision": current_membership_revision,
                }
            )

        for ordinal, draft in enumerate(drafts, start=1):
            cls._require_relationship_targets(connection, draft)
            prospective.append(
                {
                    "kind": "draft_local",
                    "draft_ordinal": ordinal,
                    "definition": draft.semantic_value(),
                    "start_utc": draft.schedule.start_utc,
                    "end_utc": draft.schedule.end_utc,
                }
            )

        prospective.sort(
            key=lambda item: (
                0 if item["kind"] == "existing" else 1,
                str(item.get("task_id", "")),
                int(item.get("draft_ordinal", 0)),
            )
        )
        start_utc = min(int(item["start_utc"]) for item in prospective)
        end_utc = max(int(item["end_utc"]) for item in prospective)

        overlap_rows = connection.execute(
            "SELECT e.objective_id,e.start_utc,e.end_utc,e.revision,o.revision "
            "FROM objective_envelope_projection e "
            "JOIN objectives o ON o.objective_id=e.objective_id "
            "WHERE o.superseded_by_objective_id IS NULL "
            "AND e.start_utc<? AND e.end_utc>? "
            "ORDER BY e.start_utc,e.objective_id",
            (end_utc, start_utc),
        ).fetchall()
        overlaps = [
            {
                "objective_id": str(row[0]),
                "start_utc": int(row[1]),
                "end_utc": int(row[2]),
                "envelope_revision": int(row[3]),
                "objective_revision": int(row[4]),
            }
            for row in overlap_rows
        ]
        mode = "REGROUP_REQUIRED" if overlaps or current_memberships else "CREATE"
        material = {
            "schema": "OBJECTIVE_CREATION_PREVIEW_V1",
            "prospective_members": prospective,
            "derived_envelope": {"start_utc": start_utc, "end_utc": end_utc},
            "current_memberships": sorted(
                current_memberships, key=lambda item: str(item["task_id"])
            ),
            "overlap_neighbors": overlaps,
        }
        return {
            "mode": mode,
            "fingerprint": sha256_canonical_json(material),
            "prospective_members": prospective,
            "derived_envelope": {"start_utc": start_utc, "end_utc": end_utc},
            "current_memberships": material["current_memberships"],
            "overlap_neighbors": overlaps,
        }

    def creation_preview(
        self,
        *,
        existing_tasks: Sequence[ObjectiveExistingTaskIntent] = (),
        draft_tasks: Sequence[ObjectiveDraftLocalTaskIntent] = (),
    ) -> dict[str, object]:
        with ReadSnapshot(self._factory) as snapshot:
            return self.evaluate_creation(
                snapshot.connection,
                existing_tasks=existing_tasks,
                draft_tasks=draft_tasks,
            )

    def list_objectives(
        self,
        *,
        execution_state: str | None = None,
        archived: bool | None = None,
        after_start_utc: int | None = None,
        after_objective_id: str | None = None,
        limit: int = 100,
    ) -> dict[str, object]:
        page_limit = _limit(limit)
        if after_start_utc is not None and (type(after_start_utc) is not int or after_start_utc < 0):
            raise ValidationError("after_start_utc is invalid")
        after_id = None if after_objective_id is None else require_uuid4(after_objective_id)
        if (after_start_utc is None) != (after_id is None):
            raise ValidationError("Objective continuation requires both key fields")
        params: list[object] = []
        clauses = ["o.superseded_by_objective_id IS NULL"]
        if execution_state is not None:
            clauses.append("a.execution_state=?")
            params.append(execution_state)
        if archived is not None:
            clauses.append("COALESCE(ar.archived,0)=?")
            params.append(1 if archived else 0)
        where = " WHERE " + " AND ".join(clauses)
        with ReadSnapshot(self._factory) as snapshot:
            total = int(
                snapshot.connection.execute(
                    "SELECT COUNT(*) FROM objectives o "
                    "JOIN objective_envelope_projection e ON e.objective_id=o.objective_id "
                    "JOIN objective_aggregate_projection a ON a.objective_id=o.objective_id "
                    "LEFT JOIN objective_archive_projection ar ON ar.objective_id=o.objective_id"
                    + where,
                    tuple(params),
                ).fetchone()[0]
            )
            page_clauses = list(clauses)
            page_params = list(params)
            if after_start_utc is not None and after_id is not None:
                page_clauses.append(
                    "(COALESCE(a.actual_start_utc,e.start_utc)>? OR "
                    "(COALESCE(a.actual_start_utc,e.start_utc)=? AND o.objective_id>?))"
                )
                page_params.extend([after_start_utc, after_start_utc, after_id])
            page_where = " WHERE " + " AND ".join(page_clauses)
            rows = snapshot.connection.execute(
                "SELECT o.objective_id,o.tracking_id,o.creation_origin,o.revision,"
                "e.start_utc,e.end_utc,e.member_count,e.revision,"
                "a.execution_state,a.aggregate_outcome,a.actual_start_utc,a.actual_end_utc,"
                "a.attention_reason,a.included_task_count,a.excluded_task_count,a.revision,"
                "COALESCE(ar.archived,0),COALESCE(ar.revision,0),"
                "COALESCE(a.actual_start_utc,e.start_utc) AS effective_start "
                "FROM objectives o "
                "JOIN objective_envelope_projection e ON e.objective_id=o.objective_id "
                "JOIN objective_aggregate_projection a ON a.objective_id=o.objective_id "
                "LEFT JOIN objective_archive_projection ar ON ar.objective_id=o.objective_id"
                + page_where
                + " ORDER BY effective_start,o.objective_id LIMIT ?",
                (*page_params, page_limit + 1),
            ).fetchall()
            page = rows[:page_limit]
            items = [
                {
                    "objective_id": str(row[0]),
                    "tracking_handle": str(row[1]),
                    "creation_origin": str(row[2]),
                    "revision": int(row[3]),
                    "derived_envelope": {
                        "start_utc": int(row[4]),
                        "end_utc": int(row[5]),
                        "member_count": int(row[6]),
                        "revision": int(row[7]),
                    },
                    "aggregate_state": {
                        "execution_state": str(row[8]),
                        "aggregate_outcome": None if row[9] is None else str(row[9]),
                        "actual_start_utc": None if row[10] is None else int(row[10]),
                        "actual_end_utc": None if row[11] is None else int(row[11]),
                        "attention_reason": None if row[12] is None else str(row[12]),
                        "included_task_count": int(row[13]),
                        "excluded_task_count": int(row[14]),
                        "revision": int(row[15]),
                    },
                    "archived": bool(row[16]),
                    "archive_revision": int(row[17]),
                }
                for row in page
            ]
            continuation = None
            if len(rows) > page_limit and page:
                last = page[-1]
                continuation = {
                    "effective_start_utc": int(last[18]),
                    "objective_id": str(last[0]),
                }
            return {"items": items, "continuation": continuation, "exact_total": total}

    def workbench(
        self,
        objective_id: str,
        *,
        member_after_task_id: str | None = None,
        member_limit: int = 100,
    ) -> dict[str, object]:
        identity = require_uuid4(objective_id)
        after = None if member_after_task_id is None else require_uuid4(member_after_task_id)
        page_limit = _limit(member_limit)
        with ReadSnapshot(self._factory) as snapshot:
            objective = snapshot.connection.execute(
                "SELECT objective_id,tracking_id,creation_origin,superseded_by_objective_id,"
                "revision,created_at_utc FROM objectives WHERE objective_id=?",
                (identity,),
            ).fetchone()
            if objective is None:
                raise SomaError("OBJECTIVE_NOT_FOUND", "Objective does not exist")
            envelope = snapshot.connection.execute(
                "SELECT start_utc,end_utc,member_count,membership_input_fingerprint,revision "
                "FROM objective_envelope_projection WHERE objective_id=?",
                (identity,),
            ).fetchone()
            aggregate = ObjectiveProjectionRepository.aggregate(snapshot.connection, identity)
            archive = snapshot.connection.execute(
                "SELECT archived,revision,last_event_id FROM objective_archive_projection "
                "WHERE objective_id=?",
                (identity,),
            ).fetchone()
            total = int(
                snapshot.connection.execute(
                    "SELECT COUNT(*) FROM objective_task_membership_current WHERE objective_id=?",
                    (identity,),
                ).fetchone()[0]
            )
            params: list[object] = [identity]
            clause = ""
            if after is not None:
                clause = " AND m.task_id>?"
                params.append(after)
            rows = snapshot.connection.execute(
                "SELECT m.task_id,m.accepted_plan_revision_id,m.membership_revision,"
                "p.start_utc,p.end_utc,pc.plan_revision_id,pc.revision,t.task_kind,"
                "t.local_task_name,w.task_no "
                "FROM objective_task_membership_current m "
                "JOIN task_plan_revisions p ON p.plan_revision_id=m.accepted_plan_revision_id "
                "JOIN task_plan_current pc ON pc.task_id=m.task_id "
                "JOIN tasks t ON t.task_id=m.task_id "
                "LEFT JOIN wfm_task_identities w ON w.task_id=m.task_id "
                "WHERE m.objective_id=?"
                + clause
                + " ORDER BY m.task_id LIMIT ?",
                (*params, page_limit + 1),
            ).fetchall()
            page = rows[:page_limit]
            membership = [
                {
                    "task_id": str(row[0]),
                    "accepted_plan_revision_id": str(row[1]),
                    "membership_revision": int(row[2]),
                    "accepted_plan": {"start_utc": int(row[3]), "end_utc": int(row[4])},
                    "current_plan_revision_id": str(row[5]),
                    "current_plan_revision": int(row[6]),
                    "plan_membership_mismatch": str(row[1]) != str(row[5]),
                    "task_kind": str(row[7]),
                    "display_name": str(row[8]) if row[8] is not None else str(row[9]),
                }
                for row in page
            ]
            members = ObjectiveProjectionRepository._load_members(snapshot.connection, identity)
            review_fingerprint = ObjectiveProjectionRepository._review_fingerprint(
                objective_id=identity,
                objective_revision=int(objective[4]),
                superseded_by=None if objective[3] is None else str(objective[3]),
                members=members,
            )
            current_review = ObjectiveProjectionRepository._current_review(
                snapshot.connection, identity, review_fingerprint
            )
            latest_review = snapshot.connection.execute(
                "SELECT objective_review_event_id,review_fingerprint,derived_outcome,"
                "reviewed_at_utc,reason_code FROM objective_review_events "
                "WHERE objective_id=? ORDER BY reviewed_at_utc DESC,objective_review_event_id DESC LIMIT 1",
                (identity,),
            ).fetchone()
            return {
                "objective_id": identity,
                "tracking_handle": str(objective[1]),
                "creation_origin": str(objective[2]),
                "superseded_by_objective_id": None if objective[3] is None else str(objective[3]),
                "revision": int(objective[4]),
                "created_at_utc": int(objective[5]),
                "membership": membership,
                "member_exact_count": total,
                "member_continuation": str(page[-1][0]) if len(rows) > page_limit and page else None,
                "derived_envelope": None
                if envelope is None
                else {
                    "start_utc": int(envelope[0]),
                    "end_utc": int(envelope[1]),
                    "member_count": int(envelope[2]),
                    "membership_input_fingerprint": str(envelope[3]),
                    "revision": int(envelope[4]),
                },
                "aggregate_state": None
                if aggregate is None
                else {
                    "execution_state": aggregate.execution_state,
                    "aggregate_outcome": aggregate.aggregate_outcome,
                    "actual_start_utc": aggregate.actual_start_utc,
                    "actual_end_utc": aggregate.actual_end_utc,
                    "attention_reason": aggregate.attention_reason,
                    "included_task_count": aggregate.included_task_count,
                    "excluded_task_count": aggregate.excluded_task_count,
                    "revision": aggregate.revision,
                    "aggregate_input_fingerprint": aggregate.aggregate_input_fingerprint,
                },
                "archive": {
                    "archived": False if archive is None else bool(archive[0]),
                    "revision": 0 if archive is None else int(archive[1]),
                    "last_event_id": None if archive is None or archive[2] is None else str(archive[2]),
                },
                "review": {
                    "review_fingerprint": review_fingerprint,
                    "current": current_review,
                    "latest": None
                    if latest_review is None
                    else {
                        "objective_review_event_id": str(latest_review[0]),
                        "review_fingerprint": str(latest_review[1]),
                        "derived_outcome": str(latest_review[2]),
                        "reviewed_at_utc": int(latest_review[3]),
                        "reason_code": None if latest_review[4] is None else str(latest_review[4]),
                        "stale": str(latest_review[1]) != review_fingerprint,
                    },
                },
            }


    @staticmethod
    def evaluate_hard_delete(
        connection: Any,
        objective_id: str,
    ) -> ObjectiveHardDeletePreview:
        identity = require_uuid4(objective_id)
        row = connection.execute(
            "SELECT objective_id,tracking_id,creation_origin,superseded_by_objective_id,"
            "revision,created_command_id FROM objectives WHERE objective_id=?",
            (identity,),
        ).fetchone()
        if row is None:
            raise SomaError("OBJECTIVE_NOT_FOUND", "Objective does not exist")

        tracking_id = str(row[1])
        creation_origin = str(row[2])
        superseded_by = None if row[3] is None else str(row[3])
        revision = int(row[4])
        created_command_id = str(row[5])
        blockers: list[str] = []

        def block(code: str, condition: bool) -> None:
            if condition:
                blockers.append(code)

        block("OBJECTIVE_CREATION_NOT_MANUAL", creation_origin != "manual")
        block("OBJECTIVE_SUPERSEDED", superseded_by is not None)
        block("OBJECTIVE_REVISION_NOT_INITIAL", revision != 1)

        receipt = connection.execute(
            "SELECT command_type,target_type,target_id FROM command_receipts WHERE command_id=?",
            (created_command_id,),
        ).fetchone()
        block(
            "OBJECTIVE_CREATION_RECEIPT_INVALID",
            receipt is None
            or str(receipt[0]) != "CreateObjectiveFromPreview"
            or str(receipt[1]) != "objective"
            or (receipt[2] is not None and str(receipt[2]) != identity),
        )

        objective_audits = connection.execute(
            "SELECT action_type,command_id FROM audit_events "
            "WHERE target_type='objective' AND target_id=? ORDER BY audit_event_id",
            (identity,),
        ).fetchall()
        block(
            "OBJECTIVE_AUDIT_HISTORY_PRESENT",
            len(objective_audits) != 1
            or str(objective_audits[0][0]) != "objective.created"
            or str(objective_audits[0][1]) != created_command_id,
        )

        archive = connection.execute(
            "SELECT archived,revision,last_event_id FROM objective_archive_projection "
            "WHERE objective_id=?",
            (identity,),
        ).fetchone()
        block(
            "OBJECTIVE_ARCHIVE_HISTORY_PRESENT",
            archive is None
            or int(archive[0]) != 0
            or int(archive[1]) != 1
            or archive[2] is not None
            or connection.execute(
                "SELECT 1 FROM objective_archive_events WHERE objective_id=? LIMIT 1",
                (identity,),
            ).fetchone()
            is not None,
        )
        block(
            "OBJECTIVE_REVIEW_HISTORY_PRESENT",
            connection.execute(
                "SELECT 1 FROM objective_review_events WHERE objective_id=? LIMIT 1",
                (identity,),
            ).fetchone()
            is not None,
        )

        envelope = connection.execute(
            "SELECT start_utc,end_utc,member_count,membership_input_fingerprint,revision "
            "FROM objective_envelope_projection WHERE objective_id=?",
            (identity,),
        ).fetchone()
        aggregate = connection.execute(
            "SELECT execution_state,aggregate_outcome,actual_start_utc,actual_end_utc,"
            "attention_reason,revision FROM objective_aggregate_projection WHERE objective_id=?",
            (identity,),
        ).fetchone()
        block(
            "OBJECTIVE_PROJECTION_HISTORY_PRESENT",
            envelope is None
            or aggregate is None
            or int(envelope[4]) != 1
            or int(aggregate[5]) != 1
            or str(aggregate[0]) != "planned"
            or aggregate[1] is not None
            or aggregate[2] is not None
            or aggregate[3] is not None
            or aggregate[4] is not None,
        )

        members = connection.execute(
            "SELECT task_id,accepted_plan_revision_id,membership_revision,last_event_id,last_command_id "
            "FROM objective_task_membership_current WHERE objective_id=? ORDER BY task_id",
            (identity,),
        ).fetchall()
        block("OBJECTIVE_EMPTY", not members)
        if envelope is not None:
            block("OBJECTIVE_MEMBER_COUNT_CHANGED", int(envelope[2]) != len(members))

        member_task_ids = tuple(str(member[0]) for member in members)
        current_event_ids = tuple(str(member[3]) for member in members)
        event_rows = connection.execute(
            "SELECT membership_event_id,task_id,event_kind,from_objective_id,to_objective_id,"
            "accepted_plan_revision_id,grouping_proposal_id,command_id "
            "FROM objective_membership_events "
            "WHERE from_objective_id=? OR to_objective_id=? "
            "ORDER BY task_id,membership_event_id",
            (identity, identity),
        ).fetchall()

        baseline_event_ids: list[str] = []
        baseline_by_task: dict[str, tuple[str, str]] = {}
        invalid_membership_history = False
        for event in event_rows:
            event_id = str(event[0])
            task_id = str(event[1])
            if (
                str(event[2]) != "add"
                or event[3] is not None
                or event[4] is None
                or str(event[4]) != identity
                or event[6] is not None
                or str(event[7]) != created_command_id
                or task_id in baseline_by_task
            ):
                invalid_membership_history = True
                continue
            baseline_by_task[task_id] = (event_id, str(event[5]))
            baseline_event_ids.append(event_id)

        if len(event_rows) != len(members):
            invalid_membership_history = True
        for member in members:
            task_id = str(member[0])
            baseline = baseline_by_task.get(task_id)
            if (
                baseline is None
                or int(member[2]) != 1
                or str(member[3]) != baseline[0]
                or str(member[1]) != baseline[1]
                or str(member[4]) != created_command_id
            ):
                invalid_membership_history = True
                break
        block("OBJECTIVE_MEMBERSHIP_HISTORY_PRESENT", invalid_membership_history)

        if member_task_ids:
            placeholders = ",".join("?" for _ in member_task_ids)
            protected = connection.execute(
                "SELECT 1 FROM task_execution_events WHERE task_id IN (" + placeholders + ") LIMIT 1",
                member_task_ids,
            ).fetchone()
            if protected is None:
                protected = connection.execute(
                    "SELECT 1 FROM task_outcome_events WHERE task_id IN (" + placeholders + ") LIMIT 1",
                    member_task_ids,
                ).fetchone()
            block("OBJECTIVE_MEMBER_EXECUTION_OR_OUTCOME_HISTORY_PRESENT", protected is not None)

        block(
            "OBJECTIVE_REGROUP_HISTORY_PRESENT",
            connection.execute(
                "SELECT 1 FROM regroup_proposal_objective_changes WHERE objective_id=? LIMIT 1",
                (identity,),
            ).fetchone()
            is not None
            or connection.execute(
                "SELECT 1 FROM regroup_proposal_task_changes "
                "WHERE from_objective_id=? OR to_objective_id=? LIMIT 1",
                (identity, identity),
            ).fetchone()
            is not None,
        )

        blocker_tuple = tuple(sorted(set(blockers)))
        status = "ELIGIBLE" if not blocker_tuple else "BLOCKED"
        fingerprint = sha256_canonical_json(
            {
                "schema": "SOMA_OBJECTIVE_HARD_DELETE_ELIGIBILITY_V1",
                "objective": {
                    "objective_id": identity,
                    "tracking_id": tracking_id,
                    "creation_origin": creation_origin,
                    "superseded_by_objective_id": superseded_by,
                    "revision": revision,
                    "created_command_id": created_command_id,
                },
                "members": [
                    {
                        "task_id": str(member[0]),
                        "accepted_plan_revision_id": str(member[1]),
                        "membership_revision": int(member[2]),
                        "last_event_id": str(member[3]),
                        "last_command_id": str(member[4]),
                    }
                    for member in members
                ],
                "membership_event_ids": sorted(baseline_event_ids),
                "envelope": None
                if envelope is None
                else {
                    "start_utc": int(envelope[0]),
                    "end_utc": int(envelope[1]),
                    "member_count": int(envelope[2]),
                    "membership_input_fingerprint": str(envelope[3]),
                    "revision": int(envelope[4]),
                },
                "aggregate": None
                if aggregate is None
                else {
                    "execution_state": str(aggregate[0]),
                    "aggregate_outcome": None if aggregate[1] is None else str(aggregate[1]),
                    "actual_start_utc": None if aggregate[2] is None else int(aggregate[2]),
                    "actual_end_utc": None if aggregate[3] is None else int(aggregate[3]),
                    "attention_reason": None if aggregate[4] is None else str(aggregate[4]),
                    "revision": int(aggregate[5]),
                },
                "status": status,
                "blockers": list(blocker_tuple),
            }
        )
        return ObjectiveHardDeletePreview(
            status=status,
            objective_id=identity,
            objective_revision=revision,
            eligibility_fingerprint=fingerprint,
            blockers=blocker_tuple,
            member_task_ids=member_task_ids,
            membership_event_ids=tuple(sorted(baseline_event_ids)),
            created_command_id=created_command_id,
            tracking_id=tracking_id,
        )

    def hard_delete_preview(
        self,
        *,
        objective_id: str,
        base_revision: int,
    ) -> ObjectiveHardDeletePreview:
        identity = require_uuid4(objective_id)
        if type(base_revision) is not int or base_revision <= 0:
            raise ValidationError("base_revision must be positive")
        with ReadSnapshot(self._factory) as snapshot:
            preview = self.evaluate_hard_delete(snapshot.connection, identity)
            if preview.objective_revision != base_revision:
                raise SomaError(
                    "HARD_DELETE_BLOCKED",
                    "Objective revision changed; refresh before hard-delete preview",
                )
            return preview


__all__ = ["ObjectiveHardDeletePreview", "ObjectiveQueryService"]
