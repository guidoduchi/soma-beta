from __future__ import annotations

from typing import Any

from soma.foundation.application.command_boundary import CommandBoundary, CommandEnvelope, PreparedMutation
from soma.foundation.audit.writer import AuditEventInput, AuditResultRef, AuditWriter
from soma.foundation.errors import IntegrityFailure, SomaError, ValidationError
from soma.foundation.identifiers import new_uuid4, require_uuid4, utc_epoch_seconds
from soma.foundation.persistence.connections import ConnectionFactory
from soma.foundation.persistence.uow import UnitOfWork

from ..audit_registry import build_objectives_tasks_audit_registry
from ..contracts.objectives_tasks import TaskMutationResult, task_mutation_result_from_execution
from ..repositories.tasks import TaskRepository, WfmTaskRepository
from .task_planning import validate_task_reason_category

_TERMINAL_WFM_SOURCE_CLASSES = frozenset({"complete", "plan_cancel"})
_PROTECTED_OBJECTIVE_STATES = frozenset(
    {"historical_structure", "in_progress", "awaiting_review", "reviewed", "superseded"}
)


def _require_revision(value: int, *, label: str, allow_zero: bool = False) -> int:
    if type(value) is not int or value < (0 if allow_zero else 1):
        qualifier = "nonnegative" if allow_zero else "positive"
        raise ValidationError(f"{label} must be a {qualifier} integer")
    return value


def _require_lock_kind(value: str) -> str:
    if value not in {"plan", "membership"}:
        raise ValidationError("lock_kind must be plan or membership")
    return value


def _require_lock_action(value: str) -> str:
    if value not in {"lock", "unlock"}:
        raise ValidationError("action must be lock or unlock")
    return value


class TaskExplicitLockService:
    """Append-only explicit Task lock authority with fail-closed derived-lock guards."""

    def __init__(self, connection_factory: ConnectionFactory) -> None:
        self._tasks = TaskRepository()
        self._boundary = CommandBoundary(
            connection_factory,
            AuditWriter(build_objectives_tasks_audit_registry()),
        )

    @staticmethod
    def _load_projection(connection: Any, task_id: str) -> tuple[bool, bool, int, str | None] | None:
        row = connection.execute(
            "SELECT explicit_plan_lock,explicit_membership_lock,revision,last_event_id "
            "FROM task_lock_projection WHERE task_id=?",
            (task_id,),
        ).fetchone()
        if row is None:
            return None
        plan = int(row[0])
        membership = int(row[1])
        revision = int(row[2])
        last_event_id = None if row[3] is None else str(row[3])
        if plan not in {0, 1} or membership not in {0, 1} or revision <= 0:
            raise IntegrityFailure("Task lock projection is invalid")
        if last_event_id is None:
            if plan or membership:
                raise IntegrityFailure("Task lock projection asserts explicit lock without history")
        else:
            event = connection.execute(
                "SELECT 1 FROM task_lock_events WHERE lock_event_id=? AND task_id=?",
                (last_event_id, task_id),
            ).fetchone()
            if event is None:
                raise IntegrityFailure("Task lock projection is not bound to same-Task history")
        return bool(plan), bool(membership), revision, last_event_id

    @staticmethod
    def _has_execution_lock(connection: Any, task_id: str) -> bool:
        non_correction_count = int(
            connection.execute(
                "SELECT count(*) FROM task_execution_events WHERE task_id=? AND event_kind<>'correction'",
                (task_id,),
            ).fetchone()[0]
        )
        projection = connection.execute(
            "SELECT last_event_id FROM task_execution_projection WHERE task_id=?",
            (task_id,),
        ).fetchone()
        if projection is not None:
            last_event_id = str(projection[0])
            if connection.execute(
                "SELECT 1 FROM task_execution_events WHERE execution_event_id=? AND task_id=?",
                (last_event_id, task_id),
            ).fetchone() is None:
                raise IntegrityFailure("Task execution projection is not bound to same-Task history")
            if non_correction_count == 0:
                raise IntegrityFailure("Task execution projection exists without accepted execution history")
        elif non_correction_count:
            raise IntegrityFailure("Task execution history exists without current projection")
        return non_correction_count > 0

    @staticmethod
    def _has_source_terminal_lock(connection: Any, task_id: str, task_kind: str) -> bool:
        identity = WfmTaskRepository.get_identity(connection, task_id)
        if task_kind == "wfm" and identity is None:
            raise IntegrityFailure("WFM Task identity authority is missing")
        if task_kind != "wfm" and identity is not None:
            raise IntegrityFailure("Local Task unexpectedly has WFM identity authority")

        row = connection.execute(
            "SELECT provider_lifecycle_class,source_projection_revision "
            "FROM wfm_source_projection_cache WHERE task_id=?",
            (task_id,),
        ).fetchone()
        if row is None:
            return False
        if task_kind != "wfm":
            raise IntegrityFailure("Local Task unexpectedly has WFM source authority")
        lifecycle = str(row[0])
        source_revision = int(row[1])
        if lifecycle not in _TERMINAL_WFM_SOURCE_CLASSES:
            return False

        pending = connection.execute(
            "SELECT 1 FROM wfm_source_terminal_reviews "
            "WHERE task_id=? AND source_projection_revision=? AND state='pending' LIMIT 1",
            (task_id, source_revision),
        ).fetchone()
        if pending is not None:
            return True
        retained = connection.execute(
            "SELECT 1 FROM wfm_source_terminal_reviews "
            "WHERE task_id=? AND source_projection_revision=? AND state='retain_local_work' LIMIT 1",
            (task_id, source_revision),
        ).fetchone()
        return retained is None

    @staticmethod
    def _has_objective_lock(connection: Any, task_id: str) -> bool:
        membership = connection.execute(
            "SELECT objective_id,accepted_plan_revision_id,last_event_id FROM objective_task_membership_current "
            "WHERE task_id=?",
            (task_id,),
        ).fetchone()
        if membership is None:
            return False
        objective_id = str(membership[0])
        pinned_plan_id = str(membership[1])
        last_event_id = str(membership[2])
        event = connection.execute(
            "SELECT to_objective_id,accepted_plan_revision_id FROM objective_membership_events "
            "WHERE membership_event_id=? AND task_id=?",
            (last_event_id, task_id),
        ).fetchone()
        if event is None or str(event[0]) != objective_id or str(event[1]) != pinned_plan_id:
            raise IntegrityFailure("Objective membership projection is not bound to same-Task history")

        row = connection.execute(
            "SELECT o.creation_origin,o.superseded_by_objective_id,a.execution_state "
            "FROM objectives o LEFT JOIN objective_aggregate_projection a ON a.objective_id=o.objective_id "
            "WHERE o.objective_id=?",
            (objective_id,),
        ).fetchone()
        if row is None or row[0] is None or row[2] is None:
            raise IntegrityFailure("Current Objective protection authority is incomplete")
        creation_origin = str(row[0])
        superseded_by = None if row[1] is None else str(row[1])
        execution_state = str(row[2])
        return (
            creation_origin == "historical_provider_complete"
            or superseded_by is not None
            or execution_state in _PROTECTED_OBJECTIVE_STATES
        )

    @classmethod
    def _assert_unlock_effective(
        cls,
        connection: Any,
        *,
        task_id: str,
        task_kind: str,
        lock_kind: str,
    ) -> None:
        locked = (
            cls._has_execution_lock(connection, task_id)
            or cls._has_source_terminal_lock(connection, task_id, task_kind)
            or cls._has_objective_lock(connection, task_id)
        )
        if locked:
            code = "TASK_PLAN_LOCKED" if lock_kind == "plan" else "TASK_MEMBERSHIP_LOCKED"
            raise SomaError(code, f"Task {lock_kind} remains independently locked by accepted authority")

    def set_explicit_task_lock(
        self,
        *,
        command_id: str,
        task_id: str,
        task_revision: int,
        lock_projection_revision: int,
        lock_kind: str,
        action: str,
        reason_category: str,
        actor_kind: str = "local_user",
        actor_id: str | None = None,
    ) -> TaskMutationResult:
        canonical_task_id = require_uuid4(task_id)
        expected_task_revision = _require_revision(task_revision, label="task_revision")
        expected_lock_revision = _require_revision(
            lock_projection_revision,
            label="lock_projection_revision",
            allow_zero=True,
        )
        selected_kind = _require_lock_kind(lock_kind)
        selected_action = _require_lock_action(action)
        reason = validate_task_reason_category(reason_category)

        envelope = CommandEnvelope(
            command_id=command_id,
            command_type="SetExplicitTaskLock",
            target_type="task",
            target_id=canonical_task_id,
            semantic_payload={
                "lock_projection_revision": expected_lock_revision,
                "lock_kind": selected_kind,
                "action": selected_action,
                "reason_category": reason,
            },
            base_revisions={canonical_task_id: expected_task_revision},
        )

        def prepare(uow: UnitOfWork) -> PreparedMutation:
            task = self._tasks.get(uow.connection, canonical_task_id)
            if task is None:
                raise SomaError("TASK_NOT_FOUND", "Task does not exist")
            if task.revision != expected_task_revision:
                raise SomaError("TASK_STALE", "Task revision changed")

            projection = self._load_projection(uow.connection, canonical_task_id)
            if projection is None:
                if expected_lock_revision != 0:
                    raise SomaError("TASK_STALE", "Task lock projection is absent")
                explicit_plan = False
                explicit_membership = False
                current_lock_revision = 0
            else:
                explicit_plan, explicit_membership, current_lock_revision, _ = projection
                if expected_lock_revision != current_lock_revision:
                    raise SomaError("TASK_STALE", "Task lock projection revision changed")

            current_selected = explicit_plan if selected_kind == "plan" else explicit_membership
            desired_selected = selected_action == "lock"
            if current_selected == desired_selected:
                return PreparedMutation(
                    True,
                    None,
                    None,
                    response_schema="TaskMutationResultV1",
                    response_version=1,
                    response={
                        "outcome": "NO_CHANGE",
                        "task_id": canonical_task_id,
                        "revision": task.revision,
                        "result_refs": [],
                    },
                )

            if selected_action == "unlock":
                self._assert_unlock_effective(
                    uow.connection,
                    task_id=canonical_task_id,
                    task_kind=task.task_kind,
                    lock_kind=selected_kind,
                )

            lock_event_id = new_uuid4()
            audit_event_id = new_uuid4()
            resulting_task_revision = task.revision + 1
            resulting_lock_revision = current_lock_revision + 1
            now = utc_epoch_seconds()

            def apply(inner: UnitOfWork) -> AuditEventInput:
                inner.connection.execute(
                    "INSERT INTO task_lock_events(lock_event_id,task_id,lock_kind,action,reason_code,recorded_at_utc,command_id) "
                    "VALUES (?,?,?,?,?,?,?)",
                    (
                        lock_event_id,
                        canonical_task_id,
                        selected_kind,
                        selected_action,
                        reason,
                        now,
                        command_id,
                    ),
                )
                new_plan = desired_selected if selected_kind == "plan" else explicit_plan
                new_membership = desired_selected if selected_kind == "membership" else explicit_membership
                if projection is None:
                    inner.connection.execute(
                        "INSERT INTO task_lock_projection(task_id,explicit_plan_lock,explicit_membership_lock,revision,last_event_id) "
                        "VALUES (?,?,?,?,?)",
                        (
                            canonical_task_id,
                            int(new_plan),
                            int(new_membership),
                            1,
                            lock_event_id,
                        ),
                    )
                else:
                    updated = inner.connection.execute(
                        "UPDATE task_lock_projection SET explicit_plan_lock=?,explicit_membership_lock=?,"
                        "revision=revision+1,last_event_id=? WHERE task_id=? AND revision=?",
                        (
                            int(new_plan),
                            int(new_membership),
                            lock_event_id,
                            canonical_task_id,
                            current_lock_revision,
                        ),
                    )
                    if updated.rowcount != 1:
                        raise IntegrityFailure("Task lock projection changed during mutation")
                self._tasks.increment_revision(
                    inner,
                    task_id=canonical_task_id,
                    expected_revision=expected_task_revision,
                )
                return AuditEventInput(
                    audit_event_id=audit_event_id,
                    action_type="task.lock_changed",
                    action_version=1,
                    actor_kind=actor_kind,
                    actor_id=actor_id,
                    target_type="task",
                    target_id=canonical_task_id,
                    reason_category=reason,
                    command_id=command_id,
                    payload_schema="TaskLockAuditV1",
                    payload_version=1,
                    payload={
                        "task_id": canonical_task_id,
                        "lock_event_id": lock_event_id,
                        "lock_kind": selected_kind,
                        "action": selected_action,
                        "resulting_task_revision": resulting_task_revision,
                        "resulting_lock_revision": resulting_lock_revision,
                        "reason_category": reason,
                    },
                    resulting_event_refs=(AuditResultRef("task_lock_event", lock_event_id),),
                )

            return PreparedMutation(
                False,
                "task_lock_event",
                lock_event_id,
                apply,
                response_schema="TaskMutationResultV1",
                response_version=1,
                response={
                    "outcome": "APPLIED",
                    "task_id": canonical_task_id,
                    "revision": resulting_task_revision,
                    "result_refs": [{"type": "task_lock_event", "id": lock_event_id}],
                },
            )

        return task_mutation_result_from_execution(self._boundary.execute(envelope, prepare))
