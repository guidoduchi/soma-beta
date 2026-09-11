from __future__ import annotations

from collections.abc import Sequence
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
from ..contracts.objectives_tasks import (
    ObjectiveMutationResult,
    TaskMutationResult,
    objective_mutation_result_from_execution,
    task_mutation_result_from_execution,
)
from ..repositories.objectives import ObjectiveProjectionRepository
from ..repositories.tasks import TaskRepository

_CANONICAL_NOW = "canonical-now"
_MAX_SELECTED_TASKS = 100
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
_BATCH_START_AUDIT_FIELDS = frozenset(
    {
        "objective_scope_id",
        "selected_task_ids",
        "task_execution_event_ids",
        "resulting_task_revisions",
        "aggregate_input_fingerprint",
        "resulting_objective_projection_revision",
    }
)
_TERMINAL_EVENT_KINDS = frozenset({"manual_cancel", "rfc_terminal_terminate", "source_terminal_consequence"})


@dataclass(frozen=True, slots=True)
class SelectedTaskExecutionStart:
    task_id: str
    task_revision: int
    execution_revision: int


@dataclass(frozen=True, slots=True)
class _ExecutionAuthority:
    revision: int
    state: str
    actual_start_utc: int | None
    actual_end_utc: int | None
    effective_termination_utc: int | None
    last_event_id: str | None
    projection_exists: bool


@dataclass(frozen=True, slots=True)
class _SelectedStartAuthority:
    request: SelectedTaskExecutionStart
    execution: _ExecutionAuthority


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


def _validate_batch_start_audit(payload: dict[str, object]) -> None:
    objective_id = payload.get("objective_scope_id")
    task_ids = payload.get("selected_task_ids")
    event_ids = payload.get("task_execution_event_ids")
    revisions = payload.get("resulting_task_revisions")
    fingerprint = payload.get("aggregate_input_fingerprint")
    aggregate_revision = payload.get("resulting_objective_projection_revision")
    try:
        if not isinstance(objective_id, str):
            raise ValidationError("Objective identity must be UUID text")
        require_uuid4(objective_id)
    except ValidationError as exc:
        raise SomaError("AUDIT_PAYLOAD_INVALID", "selected-Task start Objective identity is invalid") from exc
    if not isinstance(task_ids, list) or not (1 <= len(task_ids) <= _MAX_SELECTED_TASKS):
        raise SomaError("AUDIT_PAYLOAD_INVALID", "selected-Task start Task list is invalid")
    canonical_task_ids: list[str] = []
    try:
        for value in task_ids:
            if not isinstance(value, str):
                raise ValidationError("Task identity must be UUID text")
            canonical_task_ids.append(require_uuid4(value))
    except ValidationError as exc:
        raise SomaError("AUDIT_PAYLOAD_INVALID", "selected-Task start Task identity is invalid") from exc
    if canonical_task_ids != sorted(canonical_task_ids) or len(set(canonical_task_ids)) != len(canonical_task_ids):
        raise SomaError("AUDIT_PAYLOAD_INVALID", "selected-Task start Task identities are not canonical and unique")
    if not isinstance(event_ids, list) or len(event_ids) != len(canonical_task_ids):
        raise SomaError("AUDIT_PAYLOAD_INVALID", "selected-Task start event list is misaligned")
    canonical_event_ids: list[str] = []
    try:
        for value in event_ids:
            if not isinstance(value, str):
                raise ValidationError("execution event identity must be UUID text")
            canonical_event_ids.append(require_uuid4(value))
    except ValidationError as exc:
        raise SomaError("AUDIT_PAYLOAD_INVALID", "selected-Task start event identity is invalid") from exc
    if len(set(canonical_event_ids)) != len(canonical_event_ids):
        raise SomaError("AUDIT_PAYLOAD_INVALID", "selected-Task start event identities contain duplicates")
    if not isinstance(revisions, dict) or set(revisions) != set(canonical_task_ids):
        raise SomaError("AUDIT_PAYLOAD_INVALID", "selected-Task resulting revisions are not exact")
    for task_id in canonical_task_ids:
        value = revisions.get(task_id)
        if not isinstance(value, dict) or set(value) != {"task_revision", "execution_revision"}:
            raise SomaError("AUDIT_PAYLOAD_INVALID", "selected-Task resulting revision entry has wrong shape")
        task_revision = value.get("task_revision")
        execution_revision = value.get("execution_revision")
        if type(task_revision) is not int or task_revision < 2:
            raise SomaError("AUDIT_PAYLOAD_INVALID", "selected-Task resulting Task revision is invalid")
        if type(execution_revision) is not int or execution_revision < 1:
            raise SomaError("AUDIT_PAYLOAD_INVALID", "selected-Task resulting execution revision is invalid")
    if (
        not isinstance(fingerprint, str)
        or len(fingerprint) != 64
        or any(character not in "0123456789abcdef" for character in fingerprint)
    ):
        raise SomaError("AUDIT_PAYLOAD_INVALID", "selected-Task aggregate fingerprint is invalid")
    if type(aggregate_revision) is not int or aggregate_revision < 1:
        raise SomaError("AUDIT_PAYLOAD_INVALID", "selected-Task aggregate revision is invalid")


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
    registry.register(
        AuditActionContract(
            action_type="task.execution_batch_started",
            action_version=1,
            payload_schema="SelectedTaskStartAuditV1",
            payload_version=1,
            payload_contract=ObjectContract(
                name="SelectedTaskStartAuditV1",
                version=1,
                required_fields=_BATCH_START_AUDIT_FIELDS,
                allowed_fields=_BATCH_START_AUDIT_FIELDS,
                max_depth=3,
                max_collection_items=512,
                max_utf8_bytes=65_536,
            ),
            sensitivity_validator=_validate_batch_start_audit,
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
    """LLD-05 Task execution owner."""

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

    @staticmethod
    def _validate_objective_scope(
        connection: Any,
        *,
        objective_id: str,
        objective_revision: int,
        envelope_revision: int,
    ) -> None:
        row = connection.execute(
            "SELECT revision,superseded_by_objective_id FROM objectives WHERE objective_id=?",
            (objective_id,),
        ).fetchone()
        if row is None:
            raise SomaError("OBJECTIVE_NOT_FOUND", "Objective does not exist")
        stored_revision = row[0]
        if type(stored_revision) is not int or stored_revision <= 0:
            raise IntegrityFailure("Objective revision is invalid")
        if stored_revision != objective_revision or row[1] is not None:
            raise SomaError("OBJECTIVE_STALE", "Objective revision/currentness changed")
        envelope = connection.execute(
            "SELECT revision FROM objective_envelope_projection WHERE objective_id=?",
            (objective_id,),
        ).fetchone()
        if envelope is None:
            raise IntegrityFailure("current Objective is missing envelope projection")
        stored_envelope_revision = envelope[0]
        if type(stored_envelope_revision) is not int or stored_envelope_revision <= 0:
            raise IntegrityFailure("Objective envelope revision is invalid")
        if stored_envelope_revision != envelope_revision:
            raise SomaError("OBJECTIVE_STALE", "Objective envelope revision changed")

    @staticmethod
    def _insert_or_advance_start_projection(
        inner: UnitOfWork,
        *,
        task_id: str,
        authority: _ExecutionAuthority,
        event_id: str,
        accepted_start: int,
    ) -> None:
        if not authority.projection_exists:
            inner.connection.execute(
                "INSERT INTO task_execution_projection(task_id,execution_state,actual_start_utc,actual_end_utc,"
                "effective_termination_utc,termination_reason,revision,last_event_id) "
                "VALUES (?,'in_progress',?,NULL,NULL,NULL,1,?)",
                (task_id, accepted_start, event_id),
            )
            return
        updated = inner.connection.execute(
            "UPDATE task_execution_projection SET execution_state='in_progress',actual_start_utc=?,actual_end_utc=NULL,"
            "effective_termination_utc=NULL,termination_reason=NULL,revision=revision+1,last_event_id=? "
            "WHERE task_id=? AND revision=?",
            (accepted_start, event_id, task_id, authority.revision),
        )
        if updated.rowcount != 1:
            raise IntegrityFailure("Task execution projection changed during guarded start")

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
                self._insert_or_advance_start_projection(
                    inner,
                    task_id=canonical_task_id,
                    authority=authority,
                    event_id=event_id,
                    accepted_start=accepted_start,
                )
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

    def start_selected_objective_tasks(
        self,
        *,
        command_id: str,
        objective_id: str,
        objective_revision: int,
        objective_envelope_revision: int,
        selected_tasks: Sequence[SelectedTaskExecutionStart],
        effective_start_utc: int | str,
        actor_kind: str = "local_user",
        actor_id: str | None = None,
    ) -> ObjectiveMutationResult:
        canonical_objective_id = require_uuid4(objective_id)
        expected_objective_revision = _require_revision(objective_revision, label="objective_revision")
        expected_envelope_revision = _require_revision(
            objective_envelope_revision,
            label="objective_envelope_revision",
        )
        if not isinstance(selected_tasks, Sequence) or isinstance(selected_tasks, (str, bytes)):
            raise ValidationError("selected_tasks must be a bounded sequence")
        if not (1 <= len(selected_tasks) <= _MAX_SELECTED_TASKS):
            raise ValidationError("selected_tasks must contain between 1 and 100 Tasks")
        canonical_requests: list[SelectedTaskExecutionStart] = []
        for entry in selected_tasks:
            if not isinstance(entry, SelectedTaskExecutionStart):
                raise ValidationError("selected_tasks entries must be SelectedTaskExecutionStart values")
            canonical_requests.append(
                SelectedTaskExecutionStart(
                    task_id=require_uuid4(entry.task_id),
                    task_revision=_require_revision(entry.task_revision, label="selected task_revision"),
                    execution_revision=_require_revision(
                        entry.execution_revision,
                        label="selected execution_revision",
                        allow_zero=True,
                    ),
                )
            )
        canonical_requests.sort(key=lambda value: value.task_id)
        if len({entry.task_id for entry in canonical_requests}) != len(canonical_requests):
            raise ValidationError("selected_tasks cannot contain duplicate task_id")
        effective_request = _validate_effective_start(effective_start_utc)
        semantic_selected = [
            {
                "task_id": entry.task_id,
                "task_revision": entry.task_revision,
                "execution_revision": entry.execution_revision,
            }
            for entry in canonical_requests
        ]
        envelope = CommandEnvelope(
            command_id=command_id,
            command_type="StartSelectedObjectiveTasks",
            target_type="objective",
            target_id=canonical_objective_id,
            semantic_payload={
                "objective_envelope_revision": expected_envelope_revision,
                "selected_tasks": semantic_selected,
                "effective_start_utc": effective_request,
            },
            base_revisions={canonical_objective_id: expected_objective_revision},
        )

        def prepare(uow: UnitOfWork) -> PreparedMutation:
            self._validate_objective_scope(
                uow.connection,
                objective_id=canonical_objective_id,
                objective_revision=expected_objective_revision,
                envelope_revision=expected_envelope_revision,
            )
            selected_authorities: list[_SelectedStartAuthority] = []
            for request in canonical_requests:
                membership = self._objectives.current_membership_for_task(uow.connection, request.task_id)
                if membership is None or membership.objective_id != canonical_objective_id:
                    raise SomaError("TASK_STALE", "selected Task is no longer a current member of this Objective")
                task = self._tasks.get(uow.connection, request.task_id)
                if task is None or task.revision != request.task_revision:
                    raise SomaError("TASK_STALE", "selected Task revision changed")
                authority = self._execution_authority(uow.connection, request.task_id)
                if authority.revision != request.execution_revision:
                    raise SomaError("TASK_STALE", "selected Task execution revision changed")
                if authority.state == "in_progress":
                    raise SomaError(
                        "TASK_EXECUTION_ALREADY_STARTED",
                        "selected Task already has current accepted start evidence",
                    )
                if authority.state in {"ended", "terminated"} or self._has_terminal_outcome(
                    uow.connection, request.task_id
                ):
                    raise SomaError(
                        "TASK_EXECUTION_ALREADY_TERMINAL",
                        "selected Task execution/outcome is already terminal",
                    )
                if authority.state != "not_started":
                    raise IntegrityFailure("selected Task execution authority has unsupported start state")
                selected_authorities.append(_SelectedStartAuthority(request, authority))

            recorded_at = utc_epoch_seconds()
            accepted_start = recorded_at if effective_request == _CANONICAL_NOW else int(effective_request)
            event_ids = [new_uuid4() for _ in selected_authorities]
            audit_event_id = new_uuid4()
            primary_event_id = event_ids[0]
            response_refs = [
                {"type": "task_execution_event", "id": event_id}
                for event_id in event_ids
            ]

            def apply(inner: UnitOfWork) -> AuditEventInput:
                resulting_revisions: dict[str, dict[str, int]] = {}
                for selected, event_id in zip(selected_authorities, event_ids, strict=True):
                    request = selected.request
                    authority = selected.execution
                    inner.connection.execute(
                        "INSERT INTO task_execution_events(execution_event_id,task_id,event_kind,effective_at_utc,target_event_id,"
                        "correction_action,reason_code,recorded_at_utc,command_id) VALUES (?,?,'start',?,NULL,NULL,NULL,?,?)",
                        (event_id, request.task_id, accepted_start, recorded_at, command_id),
                    )
                    self._insert_or_advance_start_projection(
                        inner,
                        task_id=request.task_id,
                        authority=authority,
                        event_id=event_id,
                        accepted_start=accepted_start,
                    )
                    self._tasks.increment_revision(
                        inner,
                        task_id=request.task_id,
                        expected_revision=request.task_revision,
                    )
                    resulting_revisions[request.task_id] = {
                        "task_revision": request.task_revision + 1,
                        "execution_revision": authority.revision + 1,
                    }
                aggregate = self._objectives.rebuild_aggregate(
                    inner,
                    objective_id=canonical_objective_id,
                    command_id=command_id,
                )
                return AuditEventInput(
                    audit_event_id=audit_event_id,
                    action_type="task.execution_batch_started",
                    action_version=1,
                    actor_kind=actor_kind,
                    actor_id=actor_id,
                    target_type="objective",
                    target_id=canonical_objective_id,
                    reason_category=None,
                    command_id=command_id,
                    payload_schema="SelectedTaskStartAuditV1",
                    payload_version=1,
                    payload={
                        "objective_scope_id": canonical_objective_id,
                        "selected_task_ids": [selected.request.task_id for selected in selected_authorities],
                        "task_execution_event_ids": event_ids,
                        "resulting_task_revisions": resulting_revisions,
                        "aggregate_input_fingerprint": aggregate.aggregate_input_fingerprint,
                        "resulting_objective_projection_revision": aggregate.revision,
                    },
                    resulting_event_refs=tuple(
                        AuditResultRef("task_execution_event", event_id) for event_id in event_ids
                    ),
                )

            return PreparedMutation(
                False,
                "task_execution_event",
                primary_event_id,
                apply,
                response_schema="ObjectiveMutationResultV1",
                response_version=1,
                response={
                    "outcome": "APPLIED",
                    "objective_id": canonical_objective_id,
                    "revision": expected_objective_revision,
                    "result_refs": response_refs,
                },
            )

        result = objective_mutation_result_from_execution(self._boundary.execute(envelope, prepare))
        if any(ref.result_type != "task_execution_event" for ref in result.result_refs):
            raise IntegrityFailure("selected-Task start result contains unsupported result ref type")
        if len(result.result_refs) != len(canonical_requests):
            raise IntegrityFailure("selected-Task start result count does not match selected Task count")
        return result