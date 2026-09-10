from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from soma.foundation.errors import SomaError, ValidationError
from soma.foundation.identifiers import require_uuid4
from soma.foundation.persistence.connections import ConnectionFactory
from soma.foundation.persistence.uow import ReadSnapshot
from soma.foundation.strict_json import sha256_canonical_json

from ..contracts.objectives_tasks import AcceptedTaskSchedule
from ..repositories.tasks import TaskPlanRepository, TaskRepository, WfmTaskRepository

_TERMINAL_WFM_SOURCE_CLASSES = frozenset({"complete", "plan_cancel"})
_PROTECTED_OBJECTIVE_PLAN_STATES = frozenset({"historical_structure", "reviewed", "superseded"})


@dataclass(frozen=True, slots=True)
class TaskPlanCorrectionPreview:
    eligible: bool
    risk: str
    fingerprint: str
    risk_reasons: tuple[str, ...]
    blockers: tuple[str, ...]

    def to_response(self) -> dict[str, object]:
        return {
            "eligible": self.eligible,
            "risk": self.risk,
            "fingerprint": self.fingerprint,
            "risk_reasons": list(self.risk_reasons),
            "blockers": list(self.blockers),
        }


class TaskPlanCorrectionQueryService:
    """Pure exact review authority for one proposed Task-plan correction."""

    def __init__(self, connection_factory: ConnectionFactory) -> None:
        self._factory = connection_factory

    @staticmethod
    def _require_fresh_inputs(
        *,
        task_id: str,
        task_revision: int,
        current_plan_revision: int,
        current_plan_revision_id: str,
        schedule: AcceptedTaskSchedule,
    ) -> tuple[str, str, AcceptedTaskSchedule]:
        canonical_task_id = require_uuid4(task_id)
        canonical_plan_id = require_uuid4(current_plan_revision_id)
        if type(task_revision) is not int or task_revision <= 0:
            raise ValidationError("task_revision must be a positive integer")
        if type(current_plan_revision) is not int or current_plan_revision <= 0:
            raise ValidationError("current_plan_revision must be a positive integer")
        if not isinstance(schedule, AcceptedTaskSchedule):
            raise ValidationError("schedule must be AcceptedTaskSchedule")
        return canonical_task_id, canonical_plan_id, schedule.validate()

    @staticmethod
    def _load_execution_authority(connection: Any, task_id: str) -> tuple[dict[str, object] | None, int]:
        counts = connection.execute(
            "SELECT count(*),sum(CASE WHEN event_kind<>'correction' THEN 1 ELSE 0 END) "
            "FROM task_execution_events WHERE task_id=?",
            (task_id,),
        ).fetchone()
        if counts is None:
            raise SomaError("TASK_PLAN_LOCKED", "Task execution authority cannot be established")
        total_count = int(counts[0])
        non_correction_count = int(counts[1] or 0)
        row = connection.execute(
            "SELECT execution_state,actual_start_utc,actual_end_utc,effective_termination_utc,termination_reason,revision,last_event_id "
            "FROM task_execution_projection WHERE task_id=?",
            (task_id,),
        ).fetchone()
        if row is None:
            if total_count != 0:
                raise SomaError("TASK_PLAN_LOCKED", "Task execution history has no current projection")
            return None, non_correction_count
        if total_count == 0:
            raise SomaError("TASK_PLAN_LOCKED", "Task execution projection has no owned history")
        last_event_id = str(row[6])
        event = connection.execute(
            "SELECT event_kind,effective_at_utc,target_event_id,correction_action,reason_code,recorded_at_utc,command_id "
            "FROM task_execution_events WHERE execution_event_id=? AND task_id=?",
            (last_event_id, task_id),
        ).fetchone()
        if event is None:
            raise SomaError("TASK_PLAN_LOCKED", "Task execution projection is not bound to same-Task history")
        return {
            "execution_state": str(row[0]),
            "actual_start_utc": None if row[1] is None else int(row[1]),
            "actual_end_utc": None if row[2] is None else int(row[2]),
            "effective_termination_utc": None if row[3] is None else int(row[3]),
            "termination_reason": None if row[4] is None else str(row[4]),
            "revision": int(row[5]),
            "last_event_id": last_event_id,
            "last_event": {
                "event_kind": str(event[0]),
                "effective_at_utc": None if event[1] is None else int(event[1]),
                "target_event_id": None if event[2] is None else str(event[2]),
                "correction_action": None if event[3] is None else str(event[3]),
                "reason_code": None if event[4] is None else str(event[4]),
                "recorded_at_utc": int(event[5]),
                "command_id": str(event[6]),
            },
            "event_count": total_count,
            "non_correction_event_count": non_correction_count,
        }, non_correction_count

    @staticmethod
    def _load_outcome_authority(connection: Any, task_id: str) -> dict[str, object] | None:
        row = connection.execute(
            "SELECT outcome_event_id,accepted_outcome,reviewed_at_utc,revision,last_command_id "
            "FROM task_outcome_current WHERE task_id=?",
            (task_id,),
        ).fetchone()
        history_count = int(
            connection.execute(
                "SELECT count(*) FROM task_outcome_events WHERE task_id=?",
                (task_id,),
            ).fetchone()[0]
        )
        if row is None:
            if history_count != 0:
                raise SomaError("TASK_PLAN_LOCKED", "Task outcome history has no current authority")
            return None
        event_id = str(row[0])
        event = connection.execute(
            "SELECT accepted_outcome,correction_of_event_id,reason_code,reviewed_at_utc,command_id "
            "FROM task_outcome_events WHERE outcome_event_id=? AND task_id=?",
            (event_id, task_id),
        ).fetchone()
        if event is None or str(event[0]) != str(row[1]) or int(event[3]) != int(row[2]):
            raise SomaError("TASK_PLAN_LOCKED", "Task outcome projection is not bound to same-Task history")
        return {
            "outcome_event_id": event_id,
            "accepted_outcome": str(row[1]),
            "reviewed_at_utc": int(row[2]),
            "revision": int(row[3]),
            "last_command_id": str(row[4]),
            "event": {
                "correction_of_event_id": None if event[1] is None else str(event[1]),
                "reason_code": None if event[2] is None else str(event[2]),
                "command_id": str(event[4]),
            },
            "history_count": history_count,
        }

    @staticmethod
    def _load_lock_authority(connection: Any, task_id: str) -> dict[str, object] | None:
        row = connection.execute(
            "SELECT explicit_plan_lock,explicit_membership_lock,revision,last_event_id "
            "FROM task_lock_projection WHERE task_id=?",
            (task_id,),
        ).fetchone()
        if row is None:
            return None
        last_event_id = None if row[3] is None else str(row[3])
        event_authority: dict[str, object] | None = None
        if last_event_id is not None:
            event = connection.execute(
                "SELECT lock_kind,action,reason_code,recorded_at_utc,command_id "
                "FROM task_lock_events WHERE lock_event_id=? AND task_id=?",
                (last_event_id, task_id),
            ).fetchone()
            if event is None:
                raise SomaError("TASK_PLAN_LOCKED", "Task lock projection is not bound to same-Task history")
            event_authority = {
                "lock_kind": str(event[0]),
                "action": str(event[1]),
                "reason_code": str(event[2]),
                "recorded_at_utc": int(event[3]),
                "command_id": str(event[4]),
            }
        elif int(row[0]) != 0 or int(row[1]) != 0:
            raise SomaError("TASK_PLAN_LOCKED", "Task lock projection asserts a lock without history")
        return {
            "explicit_plan_lock": bool(int(row[0])),
            "explicit_membership_lock": bool(int(row[1])),
            "revision": int(row[2]),
            "last_event_id": last_event_id,
            "last_event": event_authority,
        }

    @staticmethod
    def _load_wfm_source_authority(connection: Any, task_id: str, task_kind: str) -> tuple[dict[str, object] | None, bool]:
        identity = WfmTaskRepository.get_identity(connection, task_id)
        if task_kind == "wfm" and identity is None:
            raise SomaError("TASK_PLAN_LOCKED", "WFM Task identity authority is missing")
        if task_kind != "wfm" and identity is not None:
            raise SomaError("TASK_PLAN_LOCKED", "Local Task unexpectedly has WFM identity authority")
        row = connection.execute(
            "SELECT provider_status_token,provider_lifecycle_class,source_plan_start_utc,source_plan_end_utc,"
            "accepted_source_observation_id,source_projection_revision,source_base_token,last_command_id "
            "FROM wfm_source_projection_cache WHERE task_id=?",
            (task_id,),
        ).fetchone()
        if row is None:
            return None, False
        if task_kind != "wfm":
            raise SomaError("TASK_PLAN_LOCKED", "Local Task unexpectedly has WFM source authority")
        source_revision = int(row[5])
        reviews = connection.execute(
            "SELECT source_terminal_review_id,provider_lifecycle_class,input_fingerprint,state,local_consequence_event_id,"
            "revision,created_at_utc,decided_at_utc,last_command_id "
            "FROM wfm_source_terminal_reviews WHERE task_id=? AND source_projection_revision=? "
            "ORDER BY source_terminal_review_id",
            (task_id, source_revision),
        ).fetchall()
        review_vector = [
            {
                "review_id": str(review[0]),
                "provider_lifecycle_class": str(review[1]),
                "input_fingerprint": str(review[2]),
                "state": str(review[3]),
                "local_consequence_event_id": None if review[4] is None else str(review[4]),
                "revision": int(review[5]),
                "created_at_utc": int(review[6]),
                "decided_at_utc": None if review[7] is None else int(review[7]),
                "last_command_id": None if review[8] is None else str(review[8]),
            }
            for review in reviews
        ]
        pending = any(item["state"] == "pending" for item in review_vector)
        return {
            "provider_status_token": None if row[0] is None else str(row[0]),
            "provider_lifecycle_class": str(row[1]),
            "source_plan_start_utc": None if row[2] is None else int(row[2]),
            "source_plan_end_utc": None if row[3] is None else int(row[3]),
            "accepted_source_observation_id": None if row[4] is None else str(row[4]),
            "source_projection_revision": source_revision,
            "source_base_token": str(row[6]),
            "last_command_id": str(row[7]),
            "terminal_review_vector": review_vector,
        }, pending

    @staticmethod
    def _load_objective_authority(connection: Any, task_id: str) -> tuple[dict[str, object] | None, bool]:
        row = connection.execute(
            "SELECT m.objective_id,m.accepted_plan_revision_id,m.membership_revision,m.last_event_id,m.last_command_id,"
            "o.revision,o.creation_origin,o.superseded_by_objective_id,"
            "e.start_utc,e.end_utc,e.member_count,e.membership_input_fingerprint,e.revision,e.last_command_id,"
            "a.execution_state,a.aggregate_outcome,a.attention_reason,a.included_task_count,a.excluded_task_count,"
            "a.aggregate_input_fingerprint,a.revision,a.last_command_id "
            "FROM objective_task_membership_current m "
            "LEFT JOIN objectives o ON o.objective_id=m.objective_id "
            "LEFT JOIN objective_envelope_projection e ON e.objective_id=m.objective_id "
            "LEFT JOIN objective_aggregate_projection a ON a.objective_id=m.objective_id "
            "WHERE m.task_id=?",
            (task_id,),
        ).fetchone()
        if row is None:
            return None, False
        if any(row[index] is None for index in (5, 6, 8, 9, 10, 11, 12, 13, 14, 17, 18, 19, 20, 21)):
            raise SomaError("TASK_PLAN_LOCKED", "current Objective authority is incomplete")
        objective_id = str(row[0])
        pinned_plan_id = str(row[1])
        last_event_id = str(row[3])
        event = connection.execute(
            "SELECT event_kind,from_objective_id,to_objective_id,accepted_plan_revision_id,grouping_proposal_id,reason_code,recorded_at_utc,command_id "
            "FROM objective_membership_events WHERE membership_event_id=? AND task_id=?",
            (last_event_id, task_id),
        ).fetchone()
        if (
            event is None
            or str(event[2]) != objective_id
            or str(event[3]) != pinned_plan_id
        ):
            raise SomaError("TASK_PLAN_LOCKED", "current Objective membership is not bound to same-Task history")
        execution_state = str(row[14])
        protected = (
            row[7] is not None
            or str(row[6]) == "historical_provider_complete"
            or execution_state in _PROTECTED_OBJECTIVE_PLAN_STATES
        )
        return {
            "membership": {
                "objective_id": objective_id,
                "accepted_plan_revision_id": pinned_plan_id,
                "membership_revision": int(row[2]),
                "last_event_id": last_event_id,
                "last_command_id": str(row[4]),
                "event": {
                    "event_kind": str(event[0]),
                    "from_objective_id": None if event[1] is None else str(event[1]),
                    "grouping_proposal_id": None if event[4] is None else str(event[4]),
                    "reason_code": None if event[5] is None else str(event[5]),
                    "recorded_at_utc": int(event[6]),
                    "command_id": str(event[7]),
                },
            },
            "objective": {
                "revision": int(row[5]),
                "creation_origin": str(row[6]),
                "superseded_by_objective_id": None if row[7] is None else str(row[7]),
            },
            "envelope": {
                "start_utc": int(row[8]),
                "end_utc": int(row[9]),
                "member_count": int(row[10]),
                "membership_input_fingerprint": str(row[11]),
                "revision": int(row[12]),
                "last_command_id": str(row[13]),
            },
            "aggregate": {
                "execution_state": execution_state,
                "aggregate_outcome": None if row[15] is None else str(row[15]),
                "attention_reason": None if row[16] is None else str(row[16]),
                "included_task_count": int(row[17]),
                "excluded_task_count": int(row[18]),
                "aggregate_input_fingerprint": str(row[19]),
                "revision": int(row[20]),
                "last_command_id": str(row[21]),
            },
        }, protected

    @classmethod
    def evaluate_connection(
        cls,
        connection: Any,
        *,
        task_id: str,
        task_revision: int,
        current_plan_revision: int,
        current_plan_revision_id: str,
        schedule: AcceptedTaskSchedule,
    ) -> TaskPlanCorrectionPreview:
        canonical_task_id, canonical_plan_id, accepted_schedule = cls._require_fresh_inputs(
            task_id=task_id,
            task_revision=task_revision,
            current_plan_revision=current_plan_revision,
            current_plan_revision_id=current_plan_revision_id,
            schedule=schedule,
        )
        task = TaskRepository.get(connection, canonical_task_id)
        if task is None:
            raise SomaError("TASK_NOT_FOUND", "Task does not exist in current authority")
        if task.revision != task_revision:
            raise SomaError("TASK_STALE", "Task revision changed since correction preview input")
        pointer = TaskPlanRepository.current_pointer(connection, canonical_task_id)
        if (
            pointer is None
            or pointer.revision != current_plan_revision
            or pointer.plan_revision_id != canonical_plan_id
        ):
            raise SomaError("TASK_STALE", "Task current-plan authority changed since correction preview input")
        current_plan = TaskPlanRepository.get_revision(connection, canonical_plan_id)
        if current_plan is None or current_plan.task_id != canonical_task_id:
            raise SomaError("TASK_STALE", "Task current-plan pointer does not resolve to owned immutable history")

        lock_authority = cls._load_lock_authority(connection, canonical_task_id)
        execution_authority, non_correction_execution_count = cls._load_execution_authority(
            connection, canonical_task_id
        )
        outcome_authority = cls._load_outcome_authority(connection, canonical_task_id)
        source_authority, pending_source_terminal_review = cls._load_wfm_source_authority(
            connection, canonical_task_id, task.task_kind
        )
        objective_authority, protected_objective = cls._load_objective_authority(
            connection, canonical_task_id
        )

        risk_reasons: list[str] = []
        if lock_authority is not None and bool(lock_authority["explicit_plan_lock"]):
            risk_reasons.append("EXPLICIT_PLAN_LOCK")
        if non_correction_execution_count > 0:
            risk_reasons.append("EXECUTION_HISTORY")
        if outcome_authority is not None:
            risk_reasons.append("TASK_OUTCOME")
        if (
            source_authority is not None
            and source_authority["provider_lifecycle_class"] in _TERMINAL_WFM_SOURCE_CLASSES
        ):
            risk_reasons.append("TERMINAL_WFM_SOURCE")
        if protected_objective:
            risk_reasons.append("PROTECTED_OBJECTIVE_HISTORY")
        blockers = ["SOURCE_TERMINAL_REVIEW_PENDING"] if pending_source_terminal_review else []
        risk = "HIGH" if risk_reasons else "LOW"

        authority = {
            "schema": "SOMA_TASK_PLAN_CORRECTION_REVIEW_V1",
            "task": {
                "task_id": canonical_task_id,
                "task_kind": task.task_kind,
                "revision": task.revision,
            },
            "current_plan": {
                "pointer_revision": pointer.revision,
                "plan_revision_id": current_plan.plan_revision_id,
                "start_utc": current_plan.start_utc,
                "end_utc": current_plan.end_utc,
                "origin": current_plan.origin,
                "scheduling_timezone_iana": current_plan.scheduling_timezone_iana,
                "source_observation_id": current_plan.source_observation_id,
                "predecessor_plan_revision_id": current_plan.predecessor_plan_revision_id,
            },
            "replacement": accepted_schedule.semantic_payload(),
            "lock": lock_authority,
            "execution": execution_authority,
            "outcome": outcome_authority,
            "wfm_source": source_authority,
            "objective": objective_authority,
        }
        return TaskPlanCorrectionPreview(
            eligible=not blockers,
            risk=risk,
            fingerprint=sha256_canonical_json(authority),
            risk_reasons=tuple(risk_reasons),
            blockers=tuple(blockers),
        )

    def preview(
        self,
        *,
        task_id: str,
        task_revision: int,
        current_plan_revision: int,
        current_plan_revision_id: str,
        schedule: AcceptedTaskSchedule,
    ) -> TaskPlanCorrectionPreview:
        with ReadSnapshot(self._factory) as snapshot:
            return self.evaluate_connection(
                snapshot.connection,
                task_id=task_id,
                task_revision=task_revision,
                current_plan_revision=current_plan_revision,
                current_plan_revision_id=current_plan_revision_id,
                schedule=schedule,
            )
