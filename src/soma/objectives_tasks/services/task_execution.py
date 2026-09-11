from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from soma.foundation.application.command_boundary import CommandBoundary, CommandEnvelope, PreparedMutation
from soma.foundation.audit.registry import AuditActionContract, AuditRegistry
from soma.foundation.audit.writer import AuditEventInput, AuditResultRef, AuditWriter
from soma.foundation.errors import IntegrityFailure, SomaError, ValidationError
from soma.foundation.identifiers import new_uuid4, require_uuid4, utc_epoch_seconds
from soma.foundation.persistence.connections import ConnectionFactory
from soma.foundation.persistence.uow import UnitOfWork
from soma.foundation.strict_json import ObjectContract

from ..audit_registry import build_objectives_tasks_audit_registry
from ..contracts.objectives_tasks import TaskMutationResult, task_mutation_result_from_execution
from ..repositories.objectives import ObjectiveProjectionRepository
from ..repositories.tasks import TaskRepository

_CANONICAL_NOW = "canonical-now"
_EXECUTION_AUDIT_FIELDS = frozenset(
    {
        "task_id",
        "execution_event_id",
        "event_kind",
        "effective_at_utc",
        "target_event_id",
        "resulting_task_revision",
        "resulting_execution_revision",
        "reason_category",
    }
)
_TERMINAL_EVENT_KINDS = frozenset({"manual_cancel", "rfc_terminal_terminate", "source_terminal_consequence"})


@dataclass(frozen=True, slots=True)
class _ExecutionAuthority:
    revision: int
    state: str
    actual_start_utc: int | None
    actual_end_utc: int | None
    effective_termination_utc: int | None
    last_event_id: str | None
    projection_exists: bool


@dataclass(slots=True)
class _Evidence:
    event_id: str
    event_kind: str
    effective_at_utc: int | None
    withdrawn: bool = False


def _require_revision(value: int, *, label: str, allow_zero: bool = False) -> int:
    minimum = 0 if allow_zero else 1
    if type(value) is not int or value < minimum:
        qualifier = "nonnegative" if allow_zero else "positive"
        raise ValidationError(f"{label} must be a {qualifier} integer")
    return value


def _validate_effective_start(value: object) -> int | str:
    if type(value) is int:
        if value < 0:
            raise ValidationError("effective_start_utc must be a nonnegative UTC whole second")
        return value
    if value == _CANONICAL_NOW:
        return _CANONICAL_NOW
    raise ValidationError("effective_start_utc must be a nonnegative UTC whole second or exact canonical-now token")


def _validate_execution_audit(payload: dict[str, object]) -> None:
    task_id = payload.get("task_id")
    event_id = payload.get("execution_event_id")
    try:
        if not isinstance(task_id, str) or not isinstance(event_id, str):
            raise ValidationError("execution audit identities must be UUID text")
        require_uuid4(task_id)
        require_uuid4(event_id)
    except ValidationError as exc:
        raise SomaError("AUDIT_PAYLOAD_INVALID", "Task execution audit identity is invalid") from exc
    if payload.get("event_kind") != "start":
        raise SomaError("AUDIT_PAYLOAD_INVALID", "StartTaskExecution audit event kind is invalid")
    effective_at = payload.get("effective_at_utc")
    if type(effective_at) is not int or effective_at < 0:
        raise SomaError("AUDIT_PAYLOAD_INVALID", "Task execution audit effective time is invalid")
    if payload.get("target_event_id") is not None or payload.get("reason_category") is not None:
        raise SomaError("AUDIT_PAYLOAD_INVALID", "StartTaskExecution audit cannot claim correction/reason authority")
    task_revision = payload.get("resulting_task_revision")
    execution_revision = payload.get("resulting_execution_revision")
    if type(task_revision) is not int or task_revision <= 1:
        raise SomaError("AUDIT_PAYLOAD_INVALID", "Task execution audit Task revision is invalid")
    if type(execution_revision) is not int or execution_revision <= 0:
        raise SomaError("AUDIT_PAYLOAD_INVALID", "Task execution audit execution revision is invalid")


def _build_execution_audit_registry() -> AuditRegistry:
    registry = build_objectives_tasks_audit_registry()
    registry.register(
        AuditActionContract(
            action_type="task.execution_changed",
            action_version=1,
            payload_schema="TaskExecutionAuditV1",
            payload_version=1,
            payload_contract=ObjectContract(
                name="TaskExecutionAuditV1",
                version=1,
                required_fields=_EXECUTION_AUDIT_FIELDS,
                allowed_fields=_EXECUTION_AUDIT_FIELDS,
                max_depth=3,
                max_collection_items=8,
                max_utf8_bytes=16_384,
            ),
            sensitivity_validator=_validate_execution_audit,
        )
    )
    return registry


def _stored_uuid(value: object, *, label: str) -> str:
    if not isinstance(value, str):
        raise IntegrityFailure(f"stored {label} is not UUID text")
    try:
        return require_uuid4(value)
    except ValidationError as exc:
        raise IntegrityFailure(f"stored {label} is not canonical UUIDv4") from exc


def _stored_time(value: object, *, label: str, required: bool) -> int | None:
    if value is None and not required:
        return None
    if type(value) is not int or value < 0:
        raise IntegrityFailure(f"stored {label} is invalid")
    return value


def _fold_execution_history(rows: list[Any]) -> tuple[str, int | None, int | None, int | None]:
    evidence: dict[str, _Evidence] = {}
    ordered_base_ids: list[str] = []
    seen_event_ids: set[str] = set()
    for row in rows:
        event_id = _stored_uuid(row[0], label="Task execution event identity")
        if event_id in seen_event_ids:
            raise IntegrityFailure("Task execution history contains duplicate event identity")
        seen_event_ids.add(event_id)
        event_kind = str(row[1])
        effective_at = _stored_time(row[2], label="Task execution effective time", required=False)
        target_id = None if row[3] is None else _stored_uuid(row[3], label="Task execution correction target")
        correction_action = None if row[4] is None else str(row[4])
        if event_kind == "correction":
            if target_id is None or correction_action not in {"replace_time", "withdraw"}:
                raise IntegrityFailure("Task execution correction history is malformed")
            target = evidence.get(target_id)
            if target is None:
                raise IntegrityFailure("Task execution correction targets missing or later evidence")
            if correction_action == "replace_time":
                if effective_at is None:
                    raise IntegrityFailure("replace-time execution correction has no replacement instant")
                target.effective_at_utc = effective_at
                target.withdrawn = False
            else:
                if effective_at is not None:
                    raise IntegrityFailure("withdraw execution correction unexpectedly carries effective time")
                target.withdrawn = True
            continue
        if event_kind not in {"start", "end", *_TERMINAL_EVENT_KINDS}:
            raise IntegrityFailure("Task execution history has unknown event kind")
        if target_id is not None or correction_action is not None:
            raise IntegrityFailure("non-correction execution event carries correction metadata")
        if event_kind in {"start", "end"} and effective_at is None:
            raise IntegrityFailure("start/end execution evidence requires an effective instant")
        evidence[event_id] = _Evidence(event_id, event_kind, effective_at)
        ordered_base_ids.append(event_id)

    state = "not_started"
    actual_start: int | None = None
    actual_end: int | None = None
    termination: int | None = None
    for event_id in ordered_base_ids:
        item = evidence[event_id]
        if item.withdrawn:
            continue
        if item.event_kind == "start":
            if state != "not_started" or item.effective_at_utc is None:
                raise IntegrityFailure("Task execution history contains an invalid effective start")
            state = "in_progress"
            actual_start = item.effective_at_utc
            actual_end = None
            termination = None
        elif item.event_kind == "end":
            if state != "in_progress" or actual_start is None or item.effective_at_utc is None:
                raise IntegrityFailure("Task execution history contains an invalid effective end")
            if item.effective_at_utc < actual_start:
                raise IntegrityFailure("Task execution end precedes accepted start")
            state = "ended"
            actual_end = item.effective_at_utc
            termination = None
        else:
            if state == "terminated":
                raise IntegrityFailure("Task execution history contains multiple effective terminal consequences")
            state = "terminated"
            actual_end = None
            termination = item.effective_at_utc
    return state, actual_start, actual_end, termination


class TaskExecutionService:
    """LLD-05 Task execution owner. This slice implements StartTaskExecution."""

    def __init__(self, connection_factory: ConnectionFactory) -> None:
        self._tasks = TaskRepository()
        self._objectives = ObjectiveProjectionRepository()
        self._boundary = CommandBoundary(
            connection_factory,
            AuditWriter(_build_execution_audit_registry()),
        )

    @staticmethod
    def _execution_authority(connection: Any, task_id: str) -> _ExecutionAuthority:
        projection = connection.execute(
            "SELECT revision,execution_state,actual_start_utc,actual_end_utc,effective_termination_utc,last_event_id "
            "FROM task_execution_projection WHERE task_id=?",
            (task_id,),
        ).fetchone()
        rows = connection.execute(
            "SELECT execution_event_id,event_kind,effective_at_utc,target_event_id,correction_action "
            "FROM task_execution_events WHERE task_id=? ORDER BY recorded_at_utc,execution_event_id",
            (task_id,),
        ).fetchall()
        if projection is None:
            if rows:
                raise IntegrityFailure("Task execution history exists without current projection")
            return _ExecutionAuthority(0, "not_started", None, None, None, None, False)
        if not rows:
            raise IntegrityFailure("Task execution projection exists without history")
        revision = projection[0]
        if type(revision) is not int or revision <= 0:
            raise IntegrityFailure("Task execution projection revision is invalid")
        state = str(projection[1])
        actual_start = _stored_time(projection[2], label="Task actual start", required=False)
        actual_end = _stored_time(projection[3], label="Task actual end", required=False)
        termination = _stored_time(projection[4], label="Task termination instant", required=False)
        last_event_id = _stored_uuid(projection[5], label="Task execution projection last event")
        if last_event_id != _stored_uuid(rows[-1][0], label="Task execution final event identity"):
            raise IntegrityFailure("Task execution projection does not reference the latest immutable event")
        folded = _fold_execution_history(rows)
        if (state, actual_start, actual_end, termination) != folded:
            raise IntegrityFailure("Task execution projection disagrees with folded immutable history")
        return _ExecutionAuthority(
            revision=revision,
            state=state,
            actual_start_utc=actual_start,
            actual_end_utc=actual_end,
            effective_termination_utc=termination,
            last_event_id=last_event_id,
            projection_exists=True,
        )

    @staticmethod
    def _has_terminal_outcome(connection: Any, task_id: str) -> bool:
        row = connection.execute(
            "SELECT outcome_event_id,accepted_outcome,revision FROM task_outcome_current WHERE task_id=?",
            (task_id,),
        ).fetchone()
        if row is None:
            return False
        _stored_uuid(row[0], label="Task current outcome event identity")
        if str(row[1]) not in {"completed", "incomplete", "cancelled_without_execution"}:
            raise IntegrityFailure("Task current outcome token is invalid")
        if type(row[2]) is not int or row[2] <= 0:
            raise IntegrityFailure("Task current outcome revision is invalid")
        return True

    def start_task_execution(
        self,
        *,
        command_id: str,
        task_id: str,
        task_revision: int,
        execution_revision: int,
        effective_start_utc: int | str,
        actor_kind: str = "local_user",
        actor_id: str | None = None,
    ) -> TaskMutationResult:
        canonical_task_id = require_uuid4(task_id)
        expected_task_revision = _require_revision(task_revision, label="task_revision")
        expected_execution_revision = _require_revision(
            execution_revision,
            label="execution_revision",
            allow_zero=True,
        )
        effective_request = _validate_effective_start(effective_start_utc)

        envelope = CommandEnvelope(
            command_id=command_id,
            command_type="StartTaskExecution",
            target_type="task",
            target_id=canonical_task_id,
            semantic_payload={
                "execution_revision": expected_execution_revision,
                "effective_start_utc": effective_request,
            },
            base_revisions={canonical_task_id: expected_task_revision},
        )

        def prepare(uow: UnitOfWork) -> PreparedMutation:
            task = self._tasks.get(uow.connection, canonical_task_id)
            if task is None:
                raise SomaError("TASK_NOT_FOUND", "Task does not exist")
            if task.revision != expected_task_revision:
                raise SomaError("TASK_STALE", "Task revision changed")
            authority = self._execution_authority(uow.connection, canonical_task_id)
            if authority.revision != expected_execution_revision:
                raise SomaError("TASK_STALE", "Task execution revision changed")
            if authority.state == "in_progress":
                raise SomaError("TASK_EXECUTION_ALREADY_STARTED", "Task already has current accepted start evidence")
            if authority.state in {"ended", "terminated"} or self._has_terminal_outcome(
                uow.connection, canonical_task_id
            ):
                raise SomaError("TASK_EXECUTION_ALREADY_TERMINAL", "Task execution/outcome is already terminal")
            if authority.state != "not_started":
                raise IntegrityFailure("Task execution authority has unsupported start state")

            recorded_at = utc_epoch_seconds()
            accepted_start = recorded_at if effective_request == _CANONICAL_NOW else int(effective_request)
            event_id = new_uuid4()
            audit_event_id = new_uuid4()
            resulting_task_revision = task.revision + 1
            resulting_execution_revision = authority.revision + 1

            def apply(inner: UnitOfWork) -> AuditEventInput:
                inner.connection.execute(
                    "INSERT INTO task_execution_events(execution_event_id,task_id,event_kind,effective_at_utc,target_event_id,"
                    "correction_action,reason_code,recorded_at_utc,command_id) VALUES (?,?,'start',?,NULL,NULL,NULL,?,?)",
                    (event_id, canonical_task_id, accepted_start, recorded_at, command_id),
                )
                if not authority.projection_exists:
                    inner.connection.execute(
                        "INSERT INTO task_execution_projection(task_id,execution_state,actual_start_utc,actual_end_utc,"
                        "effective_termination_utc,termination_reason,revision,last_event_id) "
                        "VALUES (?,'in_progress',?,NULL,NULL,NULL,1,?)",
                        (canonical_task_id, accepted_start, event_id),
                    )
                else:
                    updated = inner.connection.execute(
                        "UPDATE task_execution_projection SET execution_state='in_progress',actual_start_utc=?,actual_end_utc=NULL,"
                        "effective_termination_utc=NULL,termination_reason=NULL,revision=revision+1,last_event_id=? "
                        "WHERE task_id=? AND revision=?",
                        (accepted_start, event_id, canonical_task_id, authority.revision),
                    )
                    if updated.rowcount != 1:
                        raise IntegrityFailure("Task execution projection changed during guarded start")
                self._tasks.increment_revision(
                    inner,
                    task_id=canonical_task_id,
                    expected_revision=expected_task_revision,
                )
                membership = self._objectives.current_membership_for_task(inner.connection, canonical_task_id)
                if membership is not None:
                    self._objectives.rebuild_aggregate(
                        inner,
                        objective_id=membership.objective_id,
                        command_id=command_id,
                    )
                return AuditEventInput(
                    audit_event_id=audit_event_id,
                    action_type="task.execution_changed",
                    action_version=1,
                    actor_kind=actor_kind,
                    actor_id=actor_id,
                    target_type="task",
                    target_id=canonical_task_id,
                    reason_category=None,
                    command_id=command_id,
                    payload_schema="TaskExecutionAuditV1",
                    payload_version=1,
                    payload={
                        "task_id": canonical_task_id,
                        "execution_event_id": event_id,
                        "event_kind": "start",
                        "effective_at_utc": accepted_start,
                        "target_event_id": None,
                        "resulting_task_revision": resulting_task_revision,
                        "resulting_execution_revision": resulting_execution_revision,
                        "reason_category": None,
                    },
                    resulting_event_refs=(AuditResultRef("task_execution_event", event_id),),
                )

            return PreparedMutation(
                False,
                "task_execution_event",
                event_id,
                apply,
                response_schema="TaskMutationResultV1",
                response_version=1,
                response={
                    "outcome": "APPLIED",
                    "task_id": canonical_task_id,
                    "revision": resulting_task_revision,
                    "result_refs": [{"type": "task_execution_event", "id": event_id}],
                },
            )

        return task_mutation_result_from_execution(self._boundary.execute(envelope, prepare))
