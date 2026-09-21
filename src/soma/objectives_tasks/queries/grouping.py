from __future__ import annotations

from collections.abc import Sequence
from typing import Any

from soma.foundation.errors import SomaError, ValidationError
from soma.foundation.identifiers import require_uuid4
from soma.foundation.persistence.connections import ConnectionFactory
from soma.foundation.persistence.uow import ReadSnapshot
from soma.foundation.strict_json import sha256_canonical_json

from ..repositories.grouping import RegroupProposalRepository

from ..domain.objectives import ObjectiveDraftLocalTaskIntent, ObjectiveExistingTaskIntent


_MAX_PREVIEW_MEMBERS = 99


class ObjectiveGroupingQueryService:
    def __init__(self, connection_factory: ConnectionFactory) -> None:
        self._factory = connection_factory

    @staticmethod
    def _explanatory_partitions(connection: Any, task_ids: Sequence[str]) -> dict[str, object]:
        customer_sources: dict[str | None, set[str]] = {}
        rfc_sources: dict[str, set[str]] = {}
        lineage_sources: dict[str, set[str]] = {}

        def add_customer(customer_org_id: str | None, task_id: str) -> None:
            customer_sources.setdefault(customer_org_id, set()).add(task_id)

        def add_rfc(rfc_id: str, task_id: str) -> None:
            rfc_sources.setdefault(rfc_id, set()).add(task_id)

        for task_id in sorted(set(task_ids)):
            for row in connection.execute(
                "SELECT service_request_id FROM task_sr_links "
                "WHERE task_id=? AND active=1 ORDER BY service_request_id",
                (task_id,),
            ).fetchall():
                sr_id = str(row[0])
                customer = connection.execute(
                    "SELECT customer_org_id FROM sr_customer_relationships "
                    "WHERE service_request_id=? AND relationship_state='active'",
                    (sr_id,),
                ).fetchone()
                add_customer(None if customer is None else str(customer[0]), task_id)

            for row in connection.execute(
                "SELECT rfc_id FROM task_rfc_links "
                "WHERE task_id=? AND active=1 ORDER BY rfc_id",
                (task_id,),
            ).fetchall():
                rfc_id = str(row[0])
                add_rfc(rfc_id, task_id)
                customer = connection.execute(
                    "SELECT customer_org_id FROM rfcs WHERE rfc_id=?",
                    (rfc_id,),
                ).fetchone()
                add_customer(
                    None if customer is None or customer[0] is None else str(customer[0]),
                    task_id,
                )

            wfm = connection.execute(
                "SELECT current_rfc_id FROM wfm_task_identities WHERE task_id=?",
                (task_id,),
            ).fetchone()
            if wfm is not None:
                owning = str(wfm[0])
                add_rfc(owning, task_id)
                parent = connection.execute(
                    "SELECT parent_rfc_id FROM rfc_hierarchy_edges "
                    "WHERE child_rfc_id=? AND edge_state='active'",
                    (owning,),
                ).fetchone()
                root = owning if parent is None else str(parent[0])
                add_rfc(root, task_id)
                customer = connection.execute(
                    "SELECT customer_org_id FROM rfcs WHERE rfc_id=?",
                    (root,),
                ).fetchone()
                add_customer(
                    None if customer is None or customer[0] is None else str(customer[0]),
                    task_id,
                )
                lineage = connection.execute(
                    "SELECT activity_lineage_id FROM task_activity_lineage_current WHERE task_id=?",
                    (task_id,),
                ).fetchone()
                if lineage is not None and lineage[0] is not None:
                    lineage_sources.setdefault(str(lineage[0]), set()).add(task_id)

        resolved_customers = sorted(key for key in customer_sources if key is not None)
        return {
            "customer_org_ids": resolved_customers,
            "unresolved_customer_task_ids": sorted(customer_sources.get(None, set())),
            "rfc_ids": sorted(rfc_sources),
            "activity_lineage_ids": sorted(lineage_sources),
            "multi_customer": len(resolved_customers) > 1,
            "customer_sources": [
                {
                    "customer_org_id": customer_org_id,
                    "source_task_ids": sorted(customer_sources[customer_org_id]),
                }
                for customer_org_id in sorted(
                    customer_sources,
                    key=lambda value: "" if value is None else value,
                )
            ],
        }

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


    def grouping_eligibility(
        self,
        task_id: str,
        *,
        as_of_utc: int,
    ) -> dict[str, object]:
        identity = require_uuid4(task_id)
        if type(as_of_utc) is not int or as_of_utc < 0:
            raise ValidationError("as_of_utc must be non-negative")
        with ReadSnapshot(self._factory) as snapshot:
            row = snapshot.connection.execute(
                "SELECT t.task_kind,t.creation_origin,t.revision,"
                "pc.revision,pc.plan_revision_id,p.start_utc,p.end_utc,"
                "m.objective_id,m.membership_revision,m.accepted_plan_revision_id,"
                "COALESCE(l.revision,0),COALESCE(l.explicit_plan_lock,0),"
                "COALESCE(l.explicit_membership_lock,0),"
                "COALESCE(e.execution_state,'not_started'),"
                "oc.accepted_outcome,sp.provider_lifecycle_class,sp.source_projection_revision,"
                "alc.activity_lineage_id "
                "FROM tasks t "
                "LEFT JOIN task_plan_current pc ON pc.task_id=t.task_id "
                "LEFT JOIN task_plan_revisions p ON p.plan_revision_id=pc.plan_revision_id "
                "LEFT JOIN objective_task_membership_current m ON m.task_id=t.task_id "
                "LEFT JOIN task_lock_projection l ON l.task_id=t.task_id "
                "LEFT JOIN task_execution_projection e ON e.task_id=t.task_id "
                "LEFT JOIN task_outcome_current oc ON oc.task_id=t.task_id "
                "LEFT JOIN wfm_source_projection_cache sp ON sp.task_id=t.task_id "
                "LEFT JOIN task_activity_lineage_current alc ON alc.task_id=t.task_id "
                "WHERE t.task_id=?",
                (identity,),
            ).fetchone()
            if row is None:
                raise SomaError("TASK_NOT_FOUND", "Task does not exist")
            if row[4] is None:
                classification = "unscheduled"
                eligible = False
            elif row[14] == "cancelled_without_execution":
                classification = "cancelled"
                eligible = False
            elif row[13] in {"ended", "terminated"} or row[14] is not None:
                classification = "terminal_history"
                eligible = False
            elif int(row[11]) == 1 or int(row[12]) == 1 or row[13] == "in_progress":
                classification = "started_or_protected"
                eligible = False
            elif row[7] is not None and str(row[9]) != str(row[4]):
                classification = "plan_membership_mismatch"
                eligible = False
            elif row[17] is not None and int(
                snapshot.connection.execute(
                    "SELECT COUNT(*) FROM task_activity_lineage_current "
                    "WHERE activity_lineage_id=?",
                    (str(row[17]),),
                ).fetchone()[0]
            ) > 1:
                classification = "competing_attempt"
                eligible = False
            elif row[15] == "complete" and int(row[5]) < as_of_utc:
                classification = "historical_candidate"
                eligible = False
            else:
                classification = "ordinary_future"
                eligible = int(row[5]) >= as_of_utc
            return {
                "task_id": identity,
                "eligible": eligible,
                "classification": classification,
                "current_plan": None
                if row[4] is None
                else {
                    "revision": int(row[3]),
                    "plan_revision_id": str(row[4]),
                    "start_utc": int(row[5]),
                    "end_utc": int(row[6]),
                },
                "membership": None
                if row[7] is None
                else {
                    "objective_id": str(row[7]),
                    "revision": int(row[8]),
                    "accepted_plan_revision_id": str(row[9]),
                },
                "lock_revision": int(row[10]),
                "source_projection_revision": None if row[16] is None else int(row[16]),
            }

    def overlap_neighbors(
        self,
        *,
        start_utc: int,
        end_utc: int,
        exclude_objective_ids: Sequence[str] = (),
    ) -> dict[str, object]:
        if type(start_utc) is not int or start_utc < 0:
            raise ValidationError("start_utc is invalid")
        if type(end_utc) is not int or end_utc <= start_utc:
            raise ValidationError("end_utc must be greater than start_utc")
        excluded = tuple(sorted({require_uuid4(value) for value in exclude_objective_ids}))
        params: list[object] = [end_utc, start_utc]
        clause = ""
        if excluded:
            placeholders = ",".join("?" for _ in excluded)
            clause = f" AND e.objective_id NOT IN ({placeholders})"
            params.extend(excluded)
        with ReadSnapshot(self._factory) as snapshot:
            rows = snapshot.connection.execute(
                "SELECT e.objective_id,e.start_utc,e.end_utc,e.member_count,e.revision,o.revision "
                "FROM objective_envelope_projection e "
                "JOIN objectives o ON o.objective_id=e.objective_id "
                "WHERE o.superseded_by_objective_id IS NULL "
                "AND e.start_utc<? AND e.end_utc>?"
                + clause
                + " ORDER BY e.start_utc,e.objective_id",
                tuple(params),
            ).fetchall()
            return {
                "items": [
                    {
                        "objective_id": str(row[0]),
                        "start_utc": int(row[1]),
                        "end_utc": int(row[2]),
                        "member_count": int(row[3]),
                        "envelope_revision": int(row[4]),
                        "objective_revision": int(row[5]),
                    }
                    for row in rows
                ],
                "exact_total": len(rows),
            }


    def list_proposals(
        self,
        *,
        state: str | None = None,
        risk: str | None = None,
        origin: str | None = None,
        after_created_at_utc: int | None = None,
        after_proposal_id: str | None = None,
        limit: int = 100,
    ) -> dict[str, object]:
        if type(limit) is not int or not 1 <= limit <= 500:
            raise ValidationError("grouping proposal limit must be in 1..500")
        params: list[object] = []
        clauses: list[str] = []
        if state is not None:
            clauses.append("state=?")
            params.append(state)
        if risk is not None:
            clauses.append("risk_tier=?")
            params.append(risk)
        if origin is not None:
            clauses.append("origin=?")
            params.append(origin)
        if (after_created_at_utc is None) != (after_proposal_id is None):
            raise ValidationError("grouping continuation requires both key fields")
        if after_created_at_utc is not None:
            if type(after_created_at_utc) is not int or after_created_at_utc < 0:
                raise ValidationError("grouping continuation timestamp is invalid")
            from soma.foundation.identifiers import require_uuid4
            after_id = require_uuid4(str(after_proposal_id))
            clauses.append("(created_at_utc>? OR (created_at_utc=? AND regroup_proposal_id>?))")
            params.extend([after_created_at_utc, after_created_at_utc, after_id])
        where = "" if not clauses else " WHERE " + " AND ".join(clauses)
        with ReadSnapshot(self._factory) as snapshot:
            rows = snapshot.connection.execute(
                "SELECT p.regroup_proposal_id,p.proposal_kind,p.origin,p.risk_tier,"
                "p.input_fingerprint,p.state,p.revision,p.created_at_utc,"
                "(SELECT COUNT(*) FROM regroup_proposal_task_changes t "
                " WHERE t.regroup_proposal_id=p.regroup_proposal_id),"
                "(SELECT COUNT(*) FROM regroup_proposal_objective_changes o "
                " WHERE o.regroup_proposal_id=p.regroup_proposal_id) "
                "FROM regroup_proposals p" + where +
                " ORDER BY p.created_at_utc,p.regroup_proposal_id LIMIT ?",
                (*params, limit + 1),
            ).fetchall()
            page = rows[:limit]
            items = [
                {
                    "proposal_id": str(row[0]),
                    "revision": int(row[6]),
                    "input_fingerprint": str(row[4]),
                    "state": str(row[5]),
                    "diff": {
                        "proposal_kind": str(row[1]),
                        "origin": str(row[2]),
                        "risk_tier": str(row[3]),
                        "task_change_count": int(row[8]),
                        "objective_change_count": int(row[9]),
                    },
                    "created_at_utc": int(row[7]),
                }
                for row in page
            ]
            continuation = None
            if len(rows) > limit and page:
                continuation = {
                    "created_at_utc": int(page[-1][7]),
                    "proposal_id": str(page[-1][0]),
                }
            return {"items": items, "continuation": continuation}

    def proposal_detail(
        self,
        proposal_id: str,
        *,
        task_after_id: str | None = None,
        task_limit: int = 100,
        objective_after_id: str | None = None,
        objective_limit: int = 100,
    ) -> dict[str, object]:
        from soma.foundation.identifiers import require_uuid4
        identity = require_uuid4(proposal_id)
        if type(task_limit) is not int or not 1 <= task_limit <= 500:
            raise ValidationError("task change limit must be in 1..500")
        if type(objective_limit) is not int or not 1 <= objective_limit <= 500:
            raise ValidationError("objective change limit must be in 1..500")
        with ReadSnapshot(self._factory) as snapshot:
            proposal = RegroupProposalRepository.get(snapshot.connection, identity)
            if proposal is None:
                raise SomaError("GROUPING_PROPOSAL_NOT_FOUND", "grouping proposal does not exist")
            task_rows = RegroupProposalRepository.task_changes(snapshot.connection, identity)
            objective_rows = RegroupProposalRepository.objective_changes(snapshot.connection, identity)
            if task_after_id is not None:
                after = require_uuid4(task_after_id)
                task_rows = [row for row in task_rows if str(row[1]) > after]
            if objective_after_id is not None:
                after = require_uuid4(objective_after_id)
                objective_rows = [
                    row for row in objective_rows
                    if row[1] is not None and str(row[1]) > after
                ]
            task_page = task_rows[: task_limit + 1]
            objective_page = objective_rows[: objective_limit + 1]
            stale = False
            for row in task_rows:
                current = snapshot.connection.execute(
                    "SELECT t.revision,pc.plan_revision_id,m.objective_id,m.membership_revision "
                    "FROM tasks t JOIN task_plan_current pc ON pc.task_id=t.task_id "
                    "LEFT JOIN objective_task_membership_current m ON m.task_id=t.task_id "
                    "WHERE t.task_id=?",
                    (str(row[1]),),
                ).fetchone()
                if current is None or int(current[0]) != int(row[4]) or str(current[1]) != str(row[5]):
                    stale = True
                    break
                expected_objective = None if row[2] is None else str(row[2])
                current_objective = None if current[2] is None else str(current[2])
                expected_membership_revision = None if row[6] is None else int(row[6])
                current_membership_revision = None if current[3] is None else int(current[3])
                if (
                    current_objective != expected_objective
                    or current_membership_revision != expected_membership_revision
                ):
                    stale = True
                    break

            if not stale:
                for row in objective_rows:
                    if row[1] is None:
                        continue
                    current = snapshot.connection.execute(
                        "SELECT o.revision,e.revision FROM objectives o "
                        "JOIN objective_envelope_projection e ON e.objective_id=o.objective_id "
                        "WHERE o.objective_id=? AND o.superseded_by_objective_id IS NULL",
                        (str(row[1]),),
                    ).fetchone()
                    if (
                        current is None
                        or row[3] is None
                        or row[4] is None
                        or int(current[0]) != int(row[3])
                        or int(current[1]) != int(row[4])
                    ):
                        stale = True
                        break

            current_candidate = None
            if not stale:
                from ..services.grouping import GroupingService

                current_candidate = next(
                    (
                        candidate
                        for candidate in GroupingService._candidates(
                            snapshot.connection,
                            origin=proposal.origin,
                        )
                        if candidate.input_fingerprint == proposal.input_fingerprint
                    ),
                    None,
                )
                stale = current_candidate is None

            context_task_ids = {str(row[1]) for row in task_rows}
            for row in objective_rows:
                if row[1] is None:
                    continue
                for member in snapshot.connection.execute(
                    "SELECT task_id FROM objective_task_membership_current "
                    "WHERE objective_id=? ORDER BY task_id",
                    (str(row[1]),),
                ).fetchall():
                    context_task_ids.add(str(member[0]))
            explanatory_partitions = self._explanatory_partitions(
                snapshot.connection,
                tuple(sorted(context_task_ids)),
            )

            return {
                "proposal_id": identity,
                "proposal_kind": proposal.proposal_kind,
                "origin": proposal.origin,
                "risk_tier": proposal.risk_tier,
                "revision": proposal.revision,
                "input_fingerprint": proposal.input_fingerprint,
                "state": proposal.state,
                "survivor_objective_id": proposal.survivor_objective_id,
                "stale": stale,
                "equivalent_rejection_suppressed": RegroupProposalRepository.rejection_suppressed(
                    snapshot.connection, proposal.input_fingerprint
                ),
                "component_envelope": None
                if current_candidate is None
                else {
                    "start_utc": current_candidate.component_start_utc,
                    "end_utc": current_candidate.component_end_utc,
                },
                "explanatory_partitions": explanatory_partitions,
                "task_changes": [
                    {
                        "proposal_task_change_id": str(row[0]),
                        "task_id": str(row[1]),
                        "from_objective_id": None if row[2] is None else str(row[2]),
                        "to_objective_id": None if row[3] is None else str(row[3]),
                        "expected_task_revision": int(row[4]),
                        "expected_current_plan_revision_id": str(row[5]),
                        "expected_membership_revision": None if row[6] is None else int(row[6]),
                        "change_kind": str(row[7]),
                    }
                    for row in task_page[:task_limit]
                ],
                "task_change_exact_count": len(task_rows),
                "task_change_continuation": (
                    str(task_page[task_limit - 1][1])
                    if len(task_page) > task_limit and task_limit > 0 else None
                ),
                "objective_changes": [
                    {
                        "proposal_objective_change_id": str(row[0]),
                        "objective_id": None if row[1] is None else str(row[1]),
                        "action": str(row[2]),
                        "expected_objective_revision": None if row[3] is None else int(row[3]),
                        "expected_envelope_revision": None if row[4] is None else int(row[4]),
                    }
                    for row in objective_page[:objective_limit]
                ],
                "objective_change_exact_count": len(objective_rows),
                "objective_change_continuation": (
                    str(objective_page[objective_limit - 1][1])
                    if len(objective_page) > objective_limit and objective_page[objective_limit - 1][1] is not None
                    else None
                ),
            }



__all__ = ["ObjectiveGroupingQueryService"]
