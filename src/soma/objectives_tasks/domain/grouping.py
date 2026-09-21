from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable

from soma.foundation.strict_json import sha256_canonical_json


@dataclass(frozen=True, slots=True)
class GroupingTaskAuthority:
    task_id: str
    task_revision: int
    plan_revision_id: str
    plan_revision: int
    start_utc: int
    end_utc: int
    membership_objective_id: str | None
    membership_plan_revision_id: str | None
    membership_revision: int | None
    membership_locked: bool
    execution_state: str
    objective_id: str | None
    objective_revision: int | None
    objective_envelope_revision: int | None
    objective_execution_state: str | None

    def fingerprint_value(self) -> dict[str, object]:
        return {
            "task_id": self.task_id,
            "task_revision": self.task_revision,
            "plan_revision_id": self.plan_revision_id,
            "plan_revision": self.plan_revision,
            "interval": [self.start_utc, self.end_utc],
            "membership_objective_id": self.membership_objective_id,
            "membership_plan_revision_id": self.membership_plan_revision_id,
            "membership_revision": self.membership_revision,
            "membership_locked": self.membership_locked,
            "execution_state": self.execution_state,
            "objective_id": self.objective_id,
            "objective_revision": self.objective_revision,
            "objective_envelope_revision": self.objective_envelope_revision,
            "objective_execution_state": self.objective_execution_state,
        }


@dataclass(frozen=True, slots=True)
class GroupingObjectiveAuthority:
    objective_id: str
    tracking_sequence: int
    revision: int
    envelope_revision: int
    start_utc: int
    end_utc: int
    execution_state: str
    creation_origin: str

    def fingerprint_value(self) -> dict[str, object]:
        return {
            "objective_id": self.objective_id,
            "tracking_sequence": self.tracking_sequence,
            "revision": self.revision,
            "envelope_revision": self.envelope_revision,
            "interval": [self.start_utc, self.end_utc],
            "execution_state": self.execution_state,
            "creation_origin": self.creation_origin,
        }


@dataclass(frozen=True, slots=True)
class GroupingTaskChange:
    task_id: str
    from_objective_id: str | None
    to_objective_id: str | None
    expected_task_revision: int
    expected_current_plan_revision_id: str
    expected_membership_revision: int | None
    change_kind: str

    def value(self) -> dict[str, object]:
        return {
            "task_id": self.task_id,
            "from_objective_id": self.from_objective_id,
            "to_objective_id": self.to_objective_id,
            "expected_task_revision": self.expected_task_revision,
            "expected_current_plan_revision_id": self.expected_current_plan_revision_id,
            "expected_membership_revision": self.expected_membership_revision,
            "change_kind": self.change_kind,
        }


@dataclass(frozen=True, slots=True)
class GroupingObjectiveChange:
    objective_id: str | None
    action: str
    expected_objective_revision: int | None
    expected_envelope_revision: int | None

    def value(self) -> dict[str, object]:
        return {
            "objective_id": self.objective_id,
            "action": self.action,
            "expected_objective_revision": self.expected_objective_revision,
            "expected_envelope_revision": self.expected_envelope_revision,
        }


@dataclass(frozen=True, slots=True)
class RegroupCandidate:
    proposal_kind: str
    origin: str
    risk_tier: str
    survivor_objective_id: str | None
    task_changes: tuple[GroupingTaskChange, ...]
    objective_changes: tuple[GroupingObjectiveChange, ...]
    material_tasks: tuple[GroupingTaskAuthority, ...]
    material_objectives: tuple[GroupingObjectiveAuthority, ...]
    component_start_utc: int
    component_end_utc: int

    @property
    def input_fingerprint(self) -> str:
        return sha256_canonical_json(
            {
                "schema": "SOMA_REGROUP_INPUT_V1",
                "proposal_kind": self.proposal_kind,
                "origin": self.origin,
                "risk_tier": self.risk_tier,
                "survivor_objective_id": self.survivor_objective_id,
                "component": [self.component_start_utc, self.component_end_utc],
                "tasks": [item.fingerprint_value() for item in self.material_tasks],
                "objectives": [
                    item.fingerprint_value() for item in self.material_objectives
                ],
                "task_changes": [item.value() for item in self.task_changes],
                "objective_changes": [
                    item.value() for item in self.objective_changes
                ],
            }
        )


def strict_overlap_components(
    tasks: Iterable[GroupingTaskAuthority],
) -> tuple[tuple[GroupingTaskAuthority, ...], ...]:
    ordered = sorted(tasks, key=lambda item: (item.start_utc, item.end_utc, item.task_id))
    if not ordered:
        return ()
    components: list[list[GroupingTaskAuthority]] = []
    current = [ordered[0]]
    max_end = ordered[0].end_utc
    for item in ordered[1:]:
        if item.start_utc < max_end:
            current.append(item)
            max_end = max(max_end, item.end_utc)
        else:
            components.append(current)
            current = [item]
            max_end = item.end_utc
    components.append(current)
    return tuple(tuple(component) for component in components)


__all__ = [
    "GroupingObjectiveAuthority",
    "GroupingObjectiveChange",
    "GroupingTaskAuthority",
    "GroupingTaskChange",
    "RegroupCandidate",
    "strict_overlap_components",
]
