from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from soma.foundation.application.command_boundary import CommandBoundary, CommandEnvelope, PreparedMutation
from soma.foundation.audit.writer import AuditEventInput, AuditResultRef, AuditWriter
from soma.foundation.errors import IntegrityFailure, SomaError, ValidationError
from soma.foundation.identifiers import new_uuid4
from soma.foundation.persistence.connections import ConnectionFactory
from soma.foundation.persistence.uow import UnitOfWork

from ..audit_registry import build_objectives_tasks_audit_registry
from ..domain.grouping import (
    GroupingObjectiveAuthority,
    GroupingObjectiveChange,
    GroupingTaskAuthority,
    GroupingTaskChange,
    RegroupCandidate,
    strict_overlap_components,
)
from ..repositories.grouping import RegroupProposalRepository


@dataclass(frozen=True, slots=True)
class _GroupingSnapshot:
    tasks: tuple[GroupingTaskAuthority, ...]
    objectives: dict[str, GroupingObjectiveAuthority]


def _fingerprint(value: str) -> str:
    if (
        not isinstance(value, str)
        or len(value) != 64
        or any(ch not in "0123456789abcdef" for ch in value)
    ):
        raise ValidationError("input_fingerprint must be lowercase SHA-256")
    return value


class GroupingService:
    def __init__(self, connection_factory: ConnectionFactory) -> None:
        self._boundary = CommandBoundary(
            connection_factory,
            AuditWriter(build_objectives_tasks_audit_registry()),
        )

    @staticmethod
    def _load_snapshot(connection: Any) -> _GroupingSnapshot:
        objective_rows = connection.execute(
            "SELECT o.objective_id,o.tracking_sequence,o.revision,e.revision,e.start_utc,"
            "e.end_utc,a.execution_state,o.creation_origin "
            "FROM objectives o JOIN objective_envelope_projection e "
            "ON e.objective_id=o.objective_id "
            "JOIN objective_aggregate_projection a ON a.objective_id=o.objective_id "
            "WHERE o.superseded_by_objective_id IS NULL "
            "ORDER BY o.tracking_sequence,o.objective_id"
        ).fetchall()
        objectives = {
            str(row[0]): GroupingObjectiveAuthority(
                objective_id=str(row[0]),
                tracking_sequence=int(row[1]),
                revision=int(row[2]),
                envelope_revision=int(row[3]),
                start_utc=int(row[4]),
                end_utc=int(row[5]),
                execution_state=str(row[6]),
                creation_origin=str(row[7]),
            )
            for row in objective_rows
        }
        rows = connection.execute(
            "SELECT t.task_id,t.revision,pc.plan_revision_id,pc.revision,p.start_utc,p.end_utc,"
            "m.objective_id,m.accepted_plan_revision_id,m.membership_revision,"
            "COALESCE(l.explicit_membership_lock,0),COALESCE(x.execution_state,'not_started'),"
            "oc.accepted_outcome "
            "FROM tasks t JOIN task_plan_current pc ON pc.task_id=t.task_id "
            "JOIN task_plan_revisions p ON p.plan_revision_id=pc.plan_revision_id "
            "LEFT JOIN objective_task_membership_current m ON m.task_id=t.task_id "
            "LEFT JOIN task_lock_projection l ON l.task_id=t.task_id "
            "LEFT JOIN task_execution_projection x ON x.task_id=t.task_id "
            "LEFT JOIN task_outcome_current oc ON oc.task_id=t.task_id "
            "ORDER BY p.start_utc,p.end_utc,t.task_id"
        ).fetchall()
        task_items: list[GroupingTaskAuthority] = []
        for row in rows:
            execution_state = str(row[10])
            if row[11] is not None or execution_state in {"ended", "terminated"}:
                continue
            objective_id = None if row[6] is None else str(row[6])
            objective = None if objective_id is None else objectives.get(objective_id)
            if objective_id is not None and objective is None:
                raise IntegrityFailure("Task membership points to missing current Objective")
            if objective is not None and objective.creation_origin == "historical_provider_complete":
                continue
            if objective is not None and objective.execution_state in {"reviewed", "superseded", "historical_structure"}:
                continue
            if int(row[9]) == 1:
                continue
            task_items.append(
                GroupingTaskAuthority(
                    task_id=str(row[0]),
                    task_revision=int(row[1]),
                    plan_revision_id=str(row[2]),
                    plan_revision=int(row[3]),
                    start_utc=int(row[4]),
                    end_utc=int(row[5]),
                    membership_objective_id=objective_id,
                    membership_plan_revision_id=None if row[7] is None else str(row[7]),
                    membership_revision=None if row[8] is None else int(row[8]),
                    membership_locked=bool(row[9]),
                    execution_state=execution_state,
                    objective_id=objective_id,
                    objective_revision=None if objective is None else objective.revision,
                    objective_envelope_revision=None if objective is None else objective.envelope_revision,
                    objective_execution_state=None if objective is None else objective.execution_state,
                )
            )
        return _GroupingSnapshot(tuple(task_items), objectives)

    @staticmethod
    def _split_objectives(
        components: tuple[tuple[GroupingTaskAuthority, ...], ...],
    ) -> set[str]:
        membership: dict[str, set[int]] = {}
        for index, component in enumerate(components):
            for task in component:
                if task.membership_objective_id is not None:
                    membership.setdefault(task.membership_objective_id, set()).add(index)
        return {
            objective_id for objective_id, indexes in membership.items()
            if len(indexes) > 1
        }

    @classmethod
    def _candidates(
        cls,
        connection: Any,
        *,
        origin: str,
    ) -> tuple[RegroupCandidate, ...]:
        snapshot = cls._load_snapshot(connection)
        components = strict_overlap_components(snapshot.tasks)
        split_objectives = cls._split_objectives(components)
        candidates: list[RegroupCandidate] = []
        for component in components:
            start = min(task.start_utc for task in component)
            end = max(task.end_utc for task in component)
            component_task_ids = {task.task_id for task in component}
            objective_ids = {
                task.membership_objective_id
                for task in component
                if task.membership_objective_id is not None
            }
            for objective in snapshot.objectives.values():
                if objective.start_utc < end and objective.end_utc > start:
                    objective_ids.add(objective.objective_id)
            objective_ids.discard(None)
            affected = tuple(
                sorted(
                    (
                        snapshot.objectives[objective_id]
                        for objective_id in objective_ids
                        if objective_id in snapshot.objectives
                    ),
                    key=lambda item: (item.tracking_sequence, item.objective_id),
                )
            )
            if any(item.objective_id in split_objectives for item in affected):
                continue
            if any(
                item.creation_origin == "historical_provider_complete"
                or item.execution_state in {"reviewed", "superseded", "historical_structure"}
                for item in affected
            ):
                continue

            if not affected:
                task_changes = tuple(
                    GroupingTaskChange(
                        task_id=task.task_id,
                        from_objective_id=None,
                        to_objective_id=None,
                        expected_task_revision=task.task_revision,
                        expected_current_plan_revision_id=task.plan_revision_id,
                        expected_membership_revision=None,
                        change_kind="add",
                    )
                    for task in sorted(component, key=lambda item: item.task_id)
                )
                objective_changes = (
                    GroupingObjectiveChange(None, "create", None, None),
                )
                proposal_kind = "create"
                survivor = None
                risk = "normal"
            elif len(affected) == 1:
                survivor_obj = affected[0]
                changes: list[GroupingTaskChange] = []
                high_risk = survivor_obj.execution_state == "in_progress"
                for task in sorted(component, key=lambda item: item.task_id):
                    if task.membership_objective_id is None:
                        change_kind = "add"
                    elif task.membership_objective_id == survivor_obj.objective_id:
                        if task.membership_plan_revision_id == task.plan_revision_id:
                            continue
                        change_kind = "repin"
                    else:
                        change_kind = "move"
                    if high_risk:
                        if (
                            change_kind not in {"add", "repin"}
                            or task.execution_state != "not_started"
                            or task.start_utc < survivor_obj.start_utc
                            or task.end_utc > survivor_obj.end_utc
                        ):
                            changes = []
                            break
                    changes.append(
                        GroupingTaskChange(
                            task_id=task.task_id,
                            from_objective_id=task.membership_objective_id,
                            to_objective_id=survivor_obj.objective_id,
                            expected_task_revision=task.task_revision,
                            expected_current_plan_revision_id=task.plan_revision_id,
                            expected_membership_revision=task.membership_revision,
                            change_kind=change_kind,
                        )
                    )
                if not changes:
                    continue
                task_changes = tuple(changes)
                objective_changes = (
                    GroupingObjectiveChange(
                        survivor_obj.objective_id,
                        "envelope_change",
                        survivor_obj.revision,
                        survivor_obj.envelope_revision,
                    ),
                )
                proposal_kind = (
                    "join"
                    if any(item.change_kind == "add" for item in task_changes)
                    else "repin"
                    if all(item.change_kind == "repin" for item in task_changes)
                    else "move"
                )
                survivor = survivor_obj.objective_id
                risk = "high" if high_risk else "normal"
            else:
                if any(item.execution_state != "planned" for item in affected):
                    continue
                survivor_obj = min(
                    affected, key=lambda item: (item.tracking_sequence, item.objective_id)
                )
                affected_ids = {item.objective_id for item in affected}
                all_members = [
                    task
                    for task in snapshot.tasks
                    if task.membership_objective_id in affected_ids
                ]
                if {
                    task.membership_objective_id for task in all_members
                    if task.membership_objective_id is not None
                } != affected_ids:
                    continue
                desired_tasks = {
                    task.task_id: task for task in (*component, *all_members)
                }
                changes = []
                for task in sorted(desired_tasks.values(), key=lambda item: item.task_id):
                    if task.membership_objective_id is None:
                        kind = "add"
                    elif task.membership_objective_id != survivor_obj.objective_id:
                        kind = "move"
                    elif task.membership_plan_revision_id != task.plan_revision_id:
                        kind = "repin"
                    else:
                        kind = "unchanged_context"
                    changes.append(
                        GroupingTaskChange(
                            task_id=task.task_id,
                            from_objective_id=task.membership_objective_id,
                            to_objective_id=survivor_obj.objective_id,
                            expected_task_revision=task.task_revision,
                            expected_current_plan_revision_id=task.plan_revision_id,
                            expected_membership_revision=task.membership_revision,
                            change_kind=kind,
                        )
                    )
                task_changes = tuple(changes)
                objective_changes = tuple(
                    GroupingObjectiveChange(
                        item.objective_id,
                        "retain" if item.objective_id == survivor_obj.objective_id else "supersede",
                        item.revision,
                        item.envelope_revision,
                    )
                    for item in affected
                )
                proposal_kind = "consolidate"
                survivor = survivor_obj.objective_id
                risk = "normal"

            material_task_ids = {item.task_id for item in task_changes}
            material_tasks = tuple(
                sorted(
                    (
                        task for task in snapshot.tasks
                        if task.task_id in material_task_ids
                    ),
                    key=lambda item: item.task_id,
                )
            )
            candidate = RegroupCandidate(
                proposal_kind=proposal_kind,
                origin=origin,
                risk_tier=risk,
                survivor_objective_id=survivor,
                task_changes=task_changes,
                objective_changes=objective_changes,
                material_tasks=material_tasks,
                material_objectives=affected,
                component_start_utc=start,
                component_end_utc=end,
            )
            candidates.append(candidate)
        candidates.sort(
            key=lambda item: (
                item.component_start_utc,
                item.component_end_utc,
                item.proposal_kind,
                item.input_fingerprint,
            )
        )
        return tuple(candidates)

    def recompute_grouping_proposals(
        self,
        *,
        command_id: str,
        origin: str = "manual_request",
        actor_kind: str = "local_user",
        actor_id: str | None = None,
    ) -> dict[str, object]:
        if origin not in {
            "task_created", "task_plan_changed", "source_plan_adopted",
            "manual_request", "retry_created", "objective_edit"
        }:
            raise ValidationError("grouping origin is invalid")
        envelope = CommandEnvelope(
            command_id=command_id,
            command_type="RecomputeGroupingProposals",
            target_type="grouping",
            target_id=None,
            semantic_payload={"origin": origin},
        )

        def prepare(uow: UnitOfWork) -> PreparedMutation:
            candidates = self._candidates(uow.connection, origin=origin)
            material = [
                candidate for candidate in candidates
                if RegroupProposalRepository.exact_pending_by_fingerprint(
                    uow.connection, candidate.input_fingerprint
                ) is None
                and not RegroupProposalRepository.rejection_suppressed(
                    uow.connection, candidate.input_fingerprint
                )
            ]
            if not material:
                return PreparedMutation(
                    True,
                    None,
                    None,
                    response_schema="GroupingProposalPageV1",
                    response_version=1,
                    response={"items": [], "continuation": None},
                )
            proposal_ids = [new_uuid4() for _ in material]
            first_id = proposal_ids[0]

            def apply(inner: UnitOfWork):
                audits: list[AuditEventInput] = []
                items: list[dict[str, object]] = []
                for proposal_id, candidate in zip(proposal_ids, material, strict=True):
                    # Insert with prebound proposal identity for replay-safe receipt/result.
                    now = __import__("time").time_ns() // 1_000_000_000
                    inner.connection.execute(
                        "INSERT INTO regroup_proposals("
                        "regroup_proposal_id,proposal_kind,origin,risk_tier,input_fingerprint,"
                        "state,survivor_objective_id,revision,created_at_utc,last_command_id"
                        ") VALUES (?,?,?,?,?,'pending',?,1,?,?)",
                        (
                            proposal_id,
                            candidate.proposal_kind,
                            candidate.origin,
                            candidate.risk_tier,
                            candidate.input_fingerprint,
                            candidate.survivor_objective_id,
                            now,
                            command_id,
                        ),
                    )
                    for change in candidate.task_changes:
                        inner.connection.execute(
                            "INSERT INTO regroup_proposal_task_changes("
                            "proposal_task_change_id,regroup_proposal_id,task_id,from_objective_id,"
                            "to_objective_id,expected_task_revision,expected_current_plan_revision_id,"
                            "expected_membership_revision,change_kind"
                            ") VALUES (?,?,?,?,?,?,?,?,?)",
                            (
                                new_uuid4(), proposal_id, change.task_id,
                                change.from_objective_id, change.to_objective_id,
                                change.expected_task_revision,
                                change.expected_current_plan_revision_id,
                                change.expected_membership_revision, change.change_kind,
                            ),
                        )
                    for change in candidate.objective_changes:
                        inner.connection.execute(
                            "INSERT INTO regroup_proposal_objective_changes("
                            "proposal_objective_change_id,regroup_proposal_id,objective_id,action,"
                            "expected_objective_revision,expected_envelope_revision"
                            ") VALUES (?,?,?,?,?,?)",
                            (
                                new_uuid4(), proposal_id, change.objective_id, change.action,
                                change.expected_objective_revision,
                                change.expected_envelope_revision,
                            ),
                        )
                    item = {
                        "proposal_id": proposal_id,
                        "revision": 1,
                        "input_fingerprint": candidate.input_fingerprint,
                        "state": "pending",
                        "diff": {
                            "proposal_kind": candidate.proposal_kind,
                            "risk_tier": candidate.risk_tier,
                            "task_change_count": len(candidate.task_changes),
                            "objective_change_count": len(candidate.objective_changes),
                        },
                    }
                    items.append(item)
                    audits.append(
                        AuditEventInput(
                            audit_event_id=new_uuid4(),
                            action_type="grouping.proposal_recomputed",
                            action_version=1,
                            actor_kind=actor_kind,
                            actor_id=actor_id,
                            target_type="grouping_proposal",
                            target_id=proposal_id,
                            command_id=command_id,
                            payload_schema="GroupingAuditV1",
                            payload_version=1,
                            payload={
                                "proposal_id": proposal_id,
                                "event_kind": "RECOMPUTED",
                                "proposal_kind": candidate.proposal_kind,
                                "risk_tier": candidate.risk_tier,
                                "input_fingerprint": candidate.input_fingerprint,
                                "task_change_count": len(candidate.task_changes),
                                "objective_change_count": len(candidate.objective_changes),
                                "reason_category": None,
                            },
                            resulting_event_refs=(
                                AuditResultRef("grouping_proposal", proposal_id),
                            ),
                        )
                    )
                apply.items = items
                return tuple(audits)

            apply.items = []
            return PreparedMutation(
                False,
                "grouping_proposal",
                first_id,
                apply,
                response_schema="GroupingProposalPageV1",
                response_factory=lambda _inner: {
                    "items": list(apply.items),
                    "continuation": None,
                },
            )

        return self._boundary.execute(envelope, prepare).response


__all__ = ["GroupingService"]
