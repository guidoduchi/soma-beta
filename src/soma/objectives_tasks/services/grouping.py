from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from soma.foundation.application.command_boundary import CommandBoundary, CommandEnvelope, PreparedMutation
from soma.foundation.audit.writer import AuditEventInput, AuditResultRef, AuditWriter
from soma.foundation.errors import IntegrityFailure, SomaError, ValidationError
from soma.foundation.identifiers import new_uuid4, require_uuid4, utc_epoch_seconds
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
from ..repositories.objectives import ObjectiveProjectionRepository
from .objectives import ObjectiveService
from .task_planning import validate_task_reason_category


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
        self._objectives = ObjectiveProjectionRepository()
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
                    now = utc_epoch_seconds()
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


    @staticmethod
    def _proposal_response(
        proposal,
        *,
        state: str | None = None,
        revision: int | None = None,
        task_change_count: int,
        objective_change_count: int,
    ) -> dict[str, object]:
        return {
            "proposal_id": proposal.proposal_id,
            "revision": proposal.revision if revision is None else revision,
            "input_fingerprint": proposal.input_fingerprint,
            "state": proposal.state if state is None else state,
            "diff": {
                "proposal_kind": proposal.proposal_kind,
                "origin": proposal.origin,
                "risk_tier": proposal.risk_tier,
                "task_change_count": task_change_count,
                "objective_change_count": objective_change_count,
            },
        }

    @staticmethod
    def _persisted_changes(connection: Any, proposal_id: str):
        task_rows = RegroupProposalRepository.task_changes(connection, proposal_id)
        objective_rows = RegroupProposalRepository.objective_changes(connection, proposal_id)
        return task_rows, objective_rows

    @classmethod
    def _candidate_for_proposal(cls, connection: Any, proposal):
        candidates = cls._candidates(connection, origin=proposal.origin)
        matches = [
            candidate for candidate in candidates
            if candidate.input_fingerprint == proposal.input_fingerprint
            and candidate.proposal_kind == proposal.proposal_kind
        ]
        if len(matches) != 1:
            raise SomaError(
                "GROUPING_PROPOSAL_STALE",
                "current grouping authority no longer reproduces reviewed proposal",
            )
        return matches[0]

    @staticmethod
    def _assert_persisted_diff(candidate: RegroupCandidate, task_rows, objective_rows) -> None:
        persisted_tasks = [
            {
                "task_id": str(row[1]),
                "from_objective_id": None if row[2] is None else str(row[2]),
                "to_objective_id": None if row[3] is None else str(row[3]),
                "expected_task_revision": int(row[4]),
                "expected_current_plan_revision_id": str(row[5]),
                "expected_membership_revision": None if row[6] is None else int(row[6]),
                "change_kind": str(row[7]),
            }
            for row in task_rows
        ]
        expected_tasks = [item.value() for item in candidate.task_changes]
        persisted_objectives = [
            {
                "objective_id": None if row[1] is None else str(row[1]),
                "action": str(row[2]),
                "expected_objective_revision": None if row[3] is None else int(row[3]),
                "expected_envelope_revision": None if row[4] is None else int(row[4]),
            }
            for row in objective_rows
        ]
        expected_objectives = [item.value() for item in candidate.objective_changes]

        task_key = lambda item: (
            str(item["task_id"]),
            "" if item["from_objective_id"] is None else str(item["from_objective_id"]),
            "" if item["to_objective_id"] is None else str(item["to_objective_id"]),
            str(item["change_kind"]),
        )
        objective_key = lambda item: (
            "" if item["objective_id"] is None else str(item["objective_id"]),
            str(item["action"]),
        )
        if (
            sorted(persisted_tasks, key=task_key) != sorted(expected_tasks, key=task_key)
            or sorted(persisted_objectives, key=objective_key)
            != sorted(expected_objectives, key=objective_key)
        ):
            raise SomaError(
                "GROUPING_PROPOSAL_STALE",
                "persisted regroup diff disagrees with current material input",
            )

    @staticmethod
    def _rebuild_survivor_envelope(
        connection: Any,
        *,
        objective_id: str,
        expected_envelope_revision: int,
        command_id: str,
    ) -> int:
        rows = connection.execute(
            "SELECT m.task_id,m.accepted_plan_revision_id,p.start_utc,p.end_utc "
            "FROM objective_task_membership_current m "
            "JOIN task_plan_revisions p ON p.plan_revision_id=m.accepted_plan_revision_id "
            "WHERE m.objective_id=? ORDER BY m.task_id",
            (objective_id,),
        ).fetchall()
        if not rows:
            raise IntegrityFailure("accepted regroup would leave survivor Objective empty")
        material = [
            {
                "task_id": str(row[0]),
                "plan_revision_id": str(row[1]),
                "start_utc": int(row[2]),
                "end_utc": int(row[3]),
            }
            for row in rows
        ]
        from soma.foundation.strict_json import sha256_canonical_json
        fingerprint = sha256_canonical_json(
            {"schema": "OBJECTIVE_MEMBERSHIP_INPUT_V1", "members": material}
        )
        next_revision = expected_envelope_revision + 1
        changed = connection.execute(
            "UPDATE objective_envelope_projection SET start_utc=?,end_utc=?,member_count=?,"
            "membership_input_fingerprint=?,revision=?,last_command_id=? "
            "WHERE objective_id=? AND revision=?",
            (
                min(item["start_utc"] for item in material),
                max(item["end_utc"] for item in material),
                len(material),
                fingerprint,
                next_revision,
                command_id,
                objective_id,
                expected_envelope_revision,
            ),
        )
        if changed.rowcount != 1:
            raise SomaError("GROUPING_PROPOSAL_STALE", "survivor Objective envelope changed")
        return next_revision

    @staticmethod
    def _apply_membership_change(
        connection: Any,
        *,
        proposal_id: str,
        task_row,
        survivor_objective_id: str,
        command_id: str,
    ) -> str | None:
        task_id = str(task_row[1])
        from_objective = None if task_row[2] is None else str(task_row[2])
        expected_plan_id = str(task_row[5])
        expected_membership_revision = None if task_row[6] is None else int(task_row[6])
        kind = str(task_row[7])
        current = connection.execute(
            "SELECT objective_id,accepted_plan_revision_id,membership_revision,last_event_id "
            "FROM objective_task_membership_current WHERE task_id=?",
            (task_id,),
        ).fetchone()
        if kind == "unchanged_context":
            if (
                current is None
                or str(current[0]) != survivor_objective_id
                or str(current[1]) != expected_plan_id
                or int(current[2]) != expected_membership_revision
            ):
                raise SomaError("GROUPING_PROPOSAL_STALE", "unchanged regroup context drifted")
            return None
        event_id = new_uuid4()
        event_kind = "add" if current is None else "repin_plan" if kind == "repin" else "move"
        connection.execute(
            "INSERT INTO objective_membership_events("
            "membership_event_id,task_id,event_kind,from_objective_id,to_objective_id,"
            "accepted_plan_revision_id,grouping_proposal_id,reason_code,recorded_at_utc,command_id"
            ") VALUES (?,?,?,?,?,?,?,NULL,?,?)",
            (
                event_id,
                task_id,
                event_kind,
                from_objective,
                survivor_objective_id,
                expected_plan_id,
                proposal_id,
                utc_epoch_seconds(),
                command_id,
            ),
        )
        if current is None:
            if expected_membership_revision is not None or from_objective is not None:
                raise SomaError("GROUPING_PROPOSAL_STALE", "add regroup membership precondition drifted")
            connection.execute(
                "INSERT INTO objective_task_membership_current("
                "task_id,objective_id,accepted_plan_revision_id,membership_revision,last_event_id,last_command_id"
                ") VALUES (?,?,?,1,?,?)",
                (task_id, survivor_objective_id, expected_plan_id, event_id, command_id),
            )
        else:
            if (
                str(current[0]) != from_objective
                or int(current[2]) != expected_membership_revision
            ):
                raise SomaError("GROUPING_PROPOSAL_STALE", "regroup membership precondition drifted")
            changed = connection.execute(
                "UPDATE objective_task_membership_current SET objective_id=?,"
                "accepted_plan_revision_id=?,membership_revision=membership_revision+1,"
                "last_event_id=?,last_command_id=? WHERE task_id=? AND objective_id=? "
                "AND membership_revision=?",
                (
                    survivor_objective_id,
                    expected_plan_id,
                    event_id,
                    command_id,
                    task_id,
                    from_objective,
                    expected_membership_revision,
                ),
            )
            if changed.rowcount != 1:
                raise SomaError("GROUPING_PROPOSAL_STALE", "regroup membership changed")
        return event_id

    def accept_regroup_proposal(
        self,
        *,
        command_id: str,
        proposal_id: str,
        proposal_revision: int,
        input_fingerprint: str,
        accept_high_risk: bool = False,
        actor_kind: str = "local_user",
        actor_id: str | None = None,
    ) -> dict[str, object]:
        identity = require_uuid4(proposal_id)
        if type(proposal_revision) is not int or proposal_revision <= 0:
            raise ValidationError("proposal_revision must be positive")
        fingerprint = _fingerprint(input_fingerprint)
        if type(accept_high_risk) is not bool:
            raise ValidationError("accept_high_risk must be boolean")
        envelope = CommandEnvelope(
            command_id=command_id,
            command_type="AcceptRegroupProposal",
            target_type="grouping_proposal",
            target_id=identity,
            semantic_payload={"accept_high_risk": accept_high_risk},
            base_revisions={f"grouping_proposal:{identity}": proposal_revision},
            authorizing_fingerprints={"input_fingerprint": fingerprint},
        )

        def prepare(uow: UnitOfWork) -> PreparedMutation:
            proposal = RegroupProposalRepository.get(uow.connection, identity)
            if proposal is None:
                raise SomaError("GROUPING_PROPOSAL_NOT_FOUND", "grouping proposal does not exist")
            if (
                proposal.state != "pending"
                or proposal.revision != proposal_revision
                or proposal.input_fingerprint != fingerprint
            ):
                raise SomaError("GROUPING_PROPOSAL_STALE", "grouping proposal changed")
            if proposal.risk_tier == "high" and not accept_high_risk:
                raise SomaError(
                    "OBJECTIVE_IN_PROGRESS_RESTRUCTURE_LIMIT",
                    "high-risk in-progress regroup requires explicit acceptance",
                )
            candidate = self._candidate_for_proposal(uow.connection, proposal)
            task_rows, objective_rows = self._persisted_changes(uow.connection, identity)
            self._assert_persisted_diff(candidate, task_rows, objective_rows)

            new_objective = candidate.proposal_kind == "create"
            survivor_id = proposal.survivor_objective_id
            sequence = allocator_revision = None
            tracking_id = None
            if new_objective:
                sequence, allocator_revision = ObjectiveService._tracking_allocator(uow.connection)
                survivor_id = new_uuid4()
                tracking_id = f"MW-{sequence:08d}"
            if survivor_id is None:
                raise IntegrityFailure("regroup proposal lacks survivor Objective authority")
            membership_event_ids = [new_uuid4() for row in task_rows if str(row[7]) != "unchanged_context"]
            next_proposal_revision = proposal_revision + 1

            def apply(inner: UnitOfWork):
                nonlocal survivor_id
                if new_objective:
                    assert sequence is not None and allocator_revision is not None and tracking_id is not None
                    ObjectiveService._advance_tracking_allocator(
                        inner.connection,
                        sequence=sequence,
                        revision=allocator_revision,
                        command_id=command_id,
                    )
                    inner.connection.execute(
                        "INSERT INTO objectives("
                        "objective_id,tracking_sequence,tracking_id,creation_origin,"
                        "superseded_by_objective_id,revision,created_at_utc,created_command_id"
                        ") VALUES (?,?,?,'automatic_grouping',NULL,1,?,?)",
                        (survivor_id, sequence, tracking_id, utc_epoch_seconds(), command_id),
                    )
                    inner.connection.execute(
                        "INSERT INTO objective_archive_projection("
                        "objective_id,archived,revision,last_event_id) VALUES (?,0,1,NULL)",
                        (survivor_id,),
                    )

                actual_events: list[str] = []
                for row in task_rows:
                    event_id = self._apply_membership_change(
                        inner.connection,
                        proposal_id=identity,
                        task_row=row,
                        survivor_objective_id=survivor_id,
                        command_id=command_id,
                    )
                    if event_id is not None:
                        actual_events.append(event_id)
                if len(actual_events) != len(membership_event_ids):
                    raise IntegrityFailure("regroup membership event cardinality drifted")

                affected_objectives: list[str] = []
                for row in objective_rows:
                    objective_id = None if row[1] is None else str(row[1])
                    action = str(row[2])
                    if objective_id is None:
                        continue
                    expected_objective_revision = int(row[3])
                    if action == "supersede":
                        changed = inner.connection.execute(
                            "UPDATE objectives SET superseded_by_objective_id=?,revision=revision+1 "
                            "WHERE objective_id=? AND revision=? AND superseded_by_objective_id IS NULL",
                            (survivor_id, objective_id, expected_objective_revision),
                        )
                    elif objective_id == survivor_id:
                        changed = inner.connection.execute(
                            "UPDATE objectives SET revision=revision+1 "
                            "WHERE objective_id=? AND revision=? AND superseded_by_objective_id IS NULL",
                            (objective_id, expected_objective_revision),
                        )
                    else:
                        changed = None
                    if changed is not None and changed.rowcount != 1:
                        raise SomaError("GROUPING_PROPOSAL_STALE", "affected Objective revision changed")
                    affected_objectives.append(objective_id)

                # Superseded Objectives must stop participating in the current
                # non-overlap constraint before the survivor envelope expands.
                # This remains one atomic outer UoW, so any later failure rolls
                # these revision/supersession writes back together.
                expected_survivor_envelope_revision = None
                if new_objective:
                    member_rows = inner.connection.execute(
                        "SELECT m.task_id,m.accepted_plan_revision_id,p.start_utc,p.end_utc "
                        "FROM objective_task_membership_current m "
                        "JOIN task_plan_revisions p ON p.plan_revision_id=m.accepted_plan_revision_id "
                        "WHERE m.objective_id=? ORDER BY m.task_id",
                        (survivor_id,),
                    ).fetchall()
                    ObjectiveService._insert_envelope(
                        inner.connection,
                        objective_id=survivor_id,
                        members=tuple(
                            (str(row[0]), str(row[1]), int(row[2]), int(row[3]))
                            for row in member_rows
                        ),
                        command_id=command_id,
                    )
                else:
                    for row in objective_rows:
                        if row[1] is not None and str(row[1]) == survivor_id:
                            expected_survivor_envelope_revision = int(row[4])
                            break
                    if expected_survivor_envelope_revision is None:
                        raise IntegrityFailure("regroup survivor envelope revision is absent")
                    self._rebuild_survivor_envelope(
                        inner.connection,
                        objective_id=survivor_id,
                        expected_envelope_revision=expected_survivor_envelope_revision,
                        command_id=command_id,
                    )

                ObjectiveService._assert_no_overlap(inner.connection, survivor_id)
                self._objectives.rebuild_aggregate(
                    inner, objective_id=survivor_id, command_id=command_id
                )
                for objective_id in sorted(set(affected_objectives)):
                    if objective_id != survivor_id:
                        self._objectives.rebuild_aggregate(
                            inner, objective_id=objective_id, command_id=command_id
                        )
                actual_revision = RegroupProposalRepository.transition(
                    inner.connection,
                    proposal_id=identity,
                    expected_revision=proposal_revision,
                    expected_fingerprint=fingerprint,
                    new_state="accepted",
                    command_id=command_id,
                )
                apply.revision = actual_revision
                apply.membership_events = actual_events
                refs = [
                    AuditResultRef("grouping_proposal", identity),
                    AuditResultRef("objective", survivor_id),
                ]
                refs.extend(
                    AuditResultRef("objective_membership", event_id)
                    for event_id in actual_events
                )
                return AuditEventInput(
                    audit_event_id=new_uuid4(),
                    action_type="grouping.proposal_decided",
                    action_version=1,
                    actor_kind=actor_kind,
                    actor_id=actor_id,
                    target_type="grouping_proposal",
                    target_id=identity,
                    command_id=command_id,
                    payload_schema="GroupingAuditV1",
                    payload_version=1,
                    payload={
                        "proposal_id": identity,
                        "event_kind": "ACCEPTED",
                        "proposal_kind": proposal.proposal_kind,
                        "risk_tier": proposal.risk_tier,
                        "input_fingerprint": fingerprint,
                        "task_change_count": len(task_rows),
                        "objective_change_count": len(objective_rows),
                        "reason_category": None,
                    },
                    resulting_event_refs=tuple(refs),
                )

            apply.revision = next_proposal_revision
            apply.membership_events = []
            return PreparedMutation(
                False,
                "grouping_proposal",
                identity,
                apply,
                response_schema="GroupingProposalV1",
                response_factory=lambda _inner: self._proposal_response(
                    proposal,
                    state="accepted",
                    revision=apply.revision,
                    task_change_count=len(task_rows),
                    objective_change_count=len(objective_rows),
                ),
            )

        return self._boundary.execute(envelope, prepare).response

    def reject_regroup_proposal(
        self,
        *,
        command_id: str,
        proposal_id: str,
        proposal_revision: int,
        input_fingerprint: str,
        reason_category: str,
        actor_kind: str = "local_user",
        actor_id: str | None = None,
    ) -> dict[str, object]:
        identity = require_uuid4(proposal_id)
        if type(proposal_revision) is not int or proposal_revision <= 0:
            raise ValidationError("proposal_revision must be positive")
        fingerprint = _fingerprint(input_fingerprint)
        reason = validate_task_reason_category(reason_category)
        envelope = CommandEnvelope(
            command_id=command_id,
            command_type="RejectRegroupProposal",
            target_type="grouping_proposal",
            target_id=identity,
            semantic_payload={"reason_category": reason},
            base_revisions={f"grouping_proposal:{identity}": proposal_revision},
            authorizing_fingerprints={"input_fingerprint": fingerprint},
        )

        def prepare(uow: UnitOfWork) -> PreparedMutation:
            proposal = RegroupProposalRepository.get(uow.connection, identity)
            if proposal is None:
                raise SomaError("GROUPING_PROPOSAL_NOT_FOUND", "grouping proposal does not exist")
            if (
                proposal.state != "pending"
                or proposal.revision != proposal_revision
                or proposal.input_fingerprint != fingerprint
            ):
                raise SomaError("GROUPING_PROPOSAL_STALE", "grouping proposal changed")
            task_rows, objective_rows = self._persisted_changes(uow.connection, identity)
            rejection_id = new_uuid4()

            def apply(inner: UnitOfWork):
                actual_rejection_id, next_revision = RegroupProposalRepository.reject(
                    inner.connection,
                    proposal_id=identity,
                    expected_revision=proposal_revision,
                    expected_fingerprint=fingerprint,
                    reason_code=reason,
                    command_id=command_id,
                )
                apply.revision = next_revision
                apply.rejection_id = actual_rejection_id
                return AuditEventInput(
                    audit_event_id=new_uuid4(),
                    action_type="grouping.proposal_decided",
                    action_version=1,
                    actor_kind=actor_kind,
                    actor_id=actor_id,
                    target_type="grouping_proposal",
                    target_id=identity,
                    command_id=command_id,
                    reason_category=reason,
                    payload_schema="GroupingAuditV1",
                    payload_version=1,
                    payload={
                        "proposal_id": identity,
                        "event_kind": "REJECTED",
                        "proposal_kind": proposal.proposal_kind,
                        "risk_tier": proposal.risk_tier,
                        "input_fingerprint": fingerprint,
                        "task_change_count": len(task_rows),
                        "objective_change_count": len(objective_rows),
                        "reason_category": reason,
                    },
                    resulting_event_refs=(AuditResultRef("grouping_proposal", identity),),
                )

            apply.revision = proposal_revision + 1
            apply.rejection_id = rejection_id
            return PreparedMutation(
                False,
                "grouping_proposal",
                identity,
                apply,
                response_schema="GroupingProposalV1",
                response_factory=lambda _inner: self._proposal_response(
                    proposal,
                    state="rejected",
                    revision=apply.revision,
                    task_change_count=len(task_rows),
                    objective_change_count=len(objective_rows),
                ),
            )

        return self._boundary.execute(envelope, prepare).response

    def reconsider_regroup_inputs(
        self,
        *,
        command_id: str,
        proposal_id: str,
        rejection_event_id: str,
        input_fingerprint: str,
        reason_category: str,
        actor_kind: str = "local_user",
        actor_id: str | None = None,
    ) -> dict[str, object]:
        identity = require_uuid4(proposal_id)
        rejection_id = require_uuid4(rejection_event_id)
        fingerprint = _fingerprint(input_fingerprint)
        reason = validate_task_reason_category(reason_category)
        envelope = CommandEnvelope(
            command_id=command_id,
            command_type="ReconsiderRegroupInputs",
            target_type="grouping_proposal",
            target_id=identity,
            semantic_payload={
                "rejection_event_id": rejection_id,
                "input_fingerprint": fingerprint,
                "reason_category": reason,
            },
            authorizing_fingerprints={"input_fingerprint": fingerprint},
        )

        def prepare(uow: UnitOfWork) -> PreparedMutation:
            proposal = RegroupProposalRepository.get(uow.connection, identity)
            if proposal is None:
                raise SomaError("GROUPING_PROPOSAL_NOT_FOUND", "grouping proposal does not exist")
            if proposal.state != "rejected" or proposal.input_fingerprint != fingerprint:
                raise SomaError(
                    "GROUPING_EQUIVALENT_REJECTION",
                    "proposal does not own the exact rejected regroup input",
                )
            task_rows, objective_rows = self._persisted_changes(uow.connection, identity)

            def apply(inner: UnitOfWork):
                actual_id = RegroupProposalRepository.reconsider_rejection(
                    inner.connection,
                    proposal_id=identity,
                    rejection_event_id=rejection_id,
                    input_fingerprint=fingerprint,
                    reason_code=reason,
                    command_id=command_id,
                )
                apply.rejection_id = actual_id
                return AuditEventInput(
                    audit_event_id=new_uuid4(),
                    action_type="grouping.proposal_decided",
                    action_version=1,
                    actor_kind=actor_kind,
                    actor_id=actor_id,
                    target_type="grouping_proposal",
                    target_id=identity,
                    command_id=command_id,
                    reason_category=reason,
                    payload_schema="GroupingAuditV1",
                    payload_version=1,
                    payload={
                        "proposal_id": identity,
                        "event_kind": "RECONSIDERED",
                        "proposal_kind": proposal.proposal_kind,
                        "risk_tier": proposal.risk_tier,
                        "input_fingerprint": fingerprint,
                        "task_change_count": len(task_rows),
                        "objective_change_count": len(objective_rows),
                        "reason_category": reason,
                    },
                    resulting_event_refs=(AuditResultRef("grouping_proposal", identity),),
                )

            apply.rejection_id = rejection_id
            return PreparedMutation(
                False,
                "grouping_proposal",
                identity,
                apply,
                response_schema="GroupingProposalV1",
                response=self._proposal_response(
                    proposal,
                    state="rejected",
                    revision=proposal.revision,
                    task_change_count=len(task_rows),
                    objective_change_count=len(objective_rows),
                ),
            )

        return self._boundary.execute(envelope, prepare).response


__all__ = ["GroupingService"]
