from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from soma.foundation.errors import IntegrityFailure, SomaError, ValidationError
from soma.foundation.identifiers import require_uuid4
from soma.foundation.persistence.connections import ConnectionFactory
from soma.foundation.persistence.uow import ReadSnapshot
from soma.foundation.strict_json import sha256_canonical_json

from ..repositories.tasks import TaskRepository

_OUTCOMES = frozenset({"completed", "incomplete", "cancelled_without_execution"})
_BASE_EVENT_KINDS = frozenset(
    {"start", "end", "manual_cancel", "rfc_terminal_terminate", "source_terminal_consequence"}
)
_GOVERNED_TERMINAL_KINDS = frozenset({"rfc_terminal_terminate", "source_terminal_consequence"})
_MAX_REASON_UTF8_BYTES = 128


@dataclass(frozen=True, slots=True)
class TaskExecutionCorrectionPreview:
    eligible: bool
    correction_review_fingerprint: str
    execution_revision: int
    target_execution_event_id: str
    target_execution_revision: int
    target_event_kind: str
    target_effective_at_utc: int | None
    resulting_execution_state: str
    outcome_invalidation_required: bool
    current_outcome_revision: int
    current_outcome_event_id: str | None
    blockers: tuple[str, ...]

    def to_response(self) -> dict[str, object]:
        return {
            "eligible": self.eligible,
            "correction_review_fingerprint": self.correction_review_fingerprint,
            "execution_revision": self.execution_revision,
            "target_execution_event_id": self.target_execution_event_id,
            "target_execution_revision": self.target_execution_revision,
            "target_event_kind": self.target_event_kind,
            "target_effective_at_utc": self.target_effective_at_utc,
            "resulting_execution_state": self.resulting_execution_state,
            "outcome_invalidation_required": self.outcome_invalidation_required,
            "current_outcome_revision": self.current_outcome_revision,
            "current_outcome_event_id": self.current_outcome_event_id,
            "blockers": list(self.blockers),
        }


@dataclass(frozen=True, slots=True)
class TaskOutcomeReviewPreview:
    eligible: bool
    outcome_review_fingerprint: str
    current_outcome_revision: int
    current_outcome_event_id: str | None
    semantic_no_change: bool
    blockers: tuple[str, ...]

    @property
    def fingerprint(self) -> str:
        """Compatibility alias for the initial implementation slice."""
        return self.outcome_review_fingerprint

    def to_response(self) -> dict[str, object]:
        return {
            "eligible": self.eligible,
            "outcome_review_fingerprint": self.outcome_review_fingerprint,
            "current_outcome_revision": self.current_outcome_revision,
            "current_outcome_event_id": self.current_outcome_event_id,
            "semantic_no_change": self.semantic_no_change,
            "blockers": list(self.blockers),
        }


@dataclass(frozen=True, slots=True)
class TaskOutcomeCorrectionPreview:
    eligible: bool
    correction_review_fingerprint: str
    current_outcome_revision: int
    current_outcome_event_id: str
    semantic_no_change: bool
    blockers: tuple[str, ...]

    def to_response(self) -> dict[str, object]:
        return {
            "eligible": self.eligible,
            "correction_review_fingerprint": self.correction_review_fingerprint,
            "current_outcome_revision": self.current_outcome_revision,
            "current_outcome_event_id": self.current_outcome_event_id,
            "semantic_no_change": self.semantic_no_change,
            "blockers": list(self.blockers),
        }


@dataclass(frozen=True, slots=True)
class _ExecutionEvent:
    event_id: str
    revision: int
    event_kind: str
    original_effective_at_utc: int | None
    target_event_id: str | None
    correction_action: str | None
    reason_code: str | None
    recorded_at_utc: int
    command_id: str


@dataclass(frozen=True, slots=True)
class _ExecutionAuthority:
    revision: int
    state: str
    actual_start_utc: int | None
    actual_end_utc: int | None
    effective_termination_utc: int | None
    termination_reason: str | None
    last_event_id: str | None
    events: tuple[_ExecutionEvent, ...]


@dataclass(frozen=True, slots=True)
class _EffectiveEvidence:
    event_id: str
    revision: int
    event_kind: str
    original_effective_at_utc: int | None
    current_effective_at_utc: int | None
    withdrawn: bool


@dataclass(frozen=True, slots=True)
class _OutcomeAuthority:
    revision: int
    event_id: str | None
    accepted_outcome: str | None
    reason_category: str | None
    reviewed_at_utc: int | None
    last_command_id: str | None


def _stored_uuid(value: object, *, label: str) -> str:
    if not isinstance(value, str):
        raise IntegrityFailure(f"stored {label} is not UUID text")
    try:
        return require_uuid4(value)
    except ValidationError as exc:
        raise IntegrityFailure(f"stored {label} is not canonical UUIDv4") from exc


def _stored_optional_time(value: object, *, label: str) -> int | None:
    if value is None:
        return None
    if type(value) is not int or value < 0:
        raise IntegrityFailure(f"stored {label} is invalid")
    return value


def _normalize_reason(value: str | None, *, required: bool = False) -> str | None:
    if value is None:
        if required:
            raise ValidationError("reason_category is required")
        return None
    if not isinstance(value, str):
        raise ValidationError("reason_category must be text or null")
    try:
        encoded = value.encode("utf-8", errors="strict")
    except UnicodeEncodeError as exc:
        raise ValidationError("reason_category must be valid Unicode") from exc
    if (
        not encoded
        or len(encoded) > _MAX_REASON_UTF8_BYTES
        or "\x00" in value
        or "\r" in value
        or "\n" in value
    ):
        raise ValidationError("reason_category violates its bounded one-line contract")
    return value


def _require_positive_revision(value: int, *, label: str) -> int:
    if type(value) is not int or value <= 0:
        raise ValidationError(f"{label} must be a positive integer")
    return value


def _load_execution_authority(connection: Any, task_id: str) -> _ExecutionAuthority:
    projection = connection.execute(
        "SELECT revision,execution_state,actual_start_utc,actual_end_utc,effective_termination_utc,"
        "termination_reason,last_event_id FROM task_execution_projection WHERE task_id=?",
        (task_id,),
    ).fetchone()
    raw_rows = connection.execute(
        "SELECT execution_event_id,execution_revision,event_kind,effective_at_utc,target_event_id,"
        "correction_action,reason_code,recorded_at_utc,command_id "
        "FROM task_execution_events WHERE task_id=? ORDER BY execution_revision",
        (task_id,),
    ).fetchall()
    events: list[_ExecutionEvent] = []
    for expected_revision, row in enumerate(raw_rows, start=1):
        revision = row[1]
        if type(revision) is not int or revision != expected_revision:
            raise IntegrityFailure("Task execution history revision sequence is not contiguous")
        event_kind = str(row[2])
        if event_kind not in _BASE_EVENT_KINDS | {"correction"}:
            raise IntegrityFailure("Task execution history contains an invalid event kind")
        target_event_id = None if row[4] is None else _stored_uuid(
            row[4], label="Task execution correction target identity"
        )
        correction_action = None if row[5] is None else str(row[5])
        if event_kind == "correction":
            if target_event_id is None or correction_action not in {"replace_time", "withdraw"}:
                raise IntegrityFailure("Task execution correction history is malformed")
        elif target_event_id is not None or correction_action is not None:
            raise IntegrityFailure("Task execution base event carries correction metadata")
        recorded_at = row[7]
        if type(recorded_at) is not int or recorded_at < 0:
            raise IntegrityFailure("Task execution recorded_at_utc is invalid")
        events.append(
            _ExecutionEvent(
                event_id=_stored_uuid(row[0], label="Task execution event identity"),
                revision=revision,
                event_kind=event_kind,
                original_effective_at_utc=_stored_optional_time(
                    row[3], label="Task execution effective_at_utc"
                ),
                target_event_id=target_event_id,
                correction_action=correction_action,
                reason_code=None if row[6] is None else str(row[6]),
                recorded_at_utc=recorded_at,
                command_id=_stored_uuid(row[8], label="Task execution command identity"),
            )
        )

    if projection is None:
        if events:
            raise IntegrityFailure("Task execution history exists without current projection")
        return _ExecutionAuthority(0, "not_started", None, None, None, None, None, ())

    revision = projection[0]
    if type(revision) is not int or revision <= 0 or revision != len(events):
        raise IntegrityFailure("Task execution projection revision does not equal immutable event count")
    if not events:
        raise IntegrityFailure("Task execution projection exists without immutable history")
    state = str(projection[1])
    if state not in {"not_started", "in_progress", "ended", "terminated"}:
        raise IntegrityFailure("Task execution projection state is invalid")
    last_event_id = _stored_uuid(projection[6], label="Task execution projection last event")
    if last_event_id != events[-1].event_id:
        raise IntegrityFailure("Task execution projection does not reference the final immutable revision event")

    folded, _ = _fold_execution(events)
    actual_start = _stored_optional_time(projection[2], label="Task actual start")
    actual_end = _stored_optional_time(projection[3], label="Task actual end")
    termination = _stored_optional_time(projection[4], label="Task termination instant")
    termination_reason = None if projection[5] is None else str(projection[5])
    if (state, actual_start, actual_end, termination) != folded:
        raise IntegrityFailure("Task execution projection disagrees with folded immutable history")
    return _ExecutionAuthority(
        revision=revision,
        state=state,
        actual_start_utc=actual_start,
        actual_end_utc=actual_end,
        effective_termination_utc=termination,
        termination_reason=termination_reason,
        last_event_id=last_event_id,
        events=tuple(events),
    )


def _fold_execution(
    events: list[_ExecutionEvent] | tuple[_ExecutionEvent, ...],
) -> tuple[tuple[str, int | None, int | None, int | None], dict[str, _EffectiveEvidence]]:
    evidence: dict[str, _EffectiveEvidence] = {}
    ordered_base_ids: list[str] = []
    seen_event_ids: set[str] = set()
    for event in events:
        if event.event_id in seen_event_ids:
            raise IntegrityFailure("Task execution history contains duplicate event identity")
        seen_event_ids.add(event.event_id)
        if event.event_kind == "correction":
            assert event.target_event_id is not None
            target = evidence.get(event.target_event_id)
            if target is None:
                raise IntegrityFailure("Task execution correction targets missing or later evidence")
            if target.withdrawn:
                raise IntegrityFailure("Task execution correction targets non-current-effective evidence")
            if event.correction_action == "replace_time":
                if event.original_effective_at_utc is None:
                    raise IntegrityFailure("replace-time execution correction has no replacement instant")
                evidence[event.target_event_id] = _EffectiveEvidence(
                    event_id=target.event_id,
                    revision=target.revision,
                    event_kind=target.event_kind,
                    original_effective_at_utc=target.original_effective_at_utc,
                    current_effective_at_utc=event.original_effective_at_utc,
                    withdrawn=False,
                )
            elif event.correction_action == "withdraw":
                if event.original_effective_at_utc is not None:
                    raise IntegrityFailure("withdraw execution correction unexpectedly carries effective time")
                evidence[event.target_event_id] = _EffectiveEvidence(
                    event_id=target.event_id,
                    revision=target.revision,
                    event_kind=target.event_kind,
                    original_effective_at_utc=target.original_effective_at_utc,
                    current_effective_at_utc=target.current_effective_at_utc,
                    withdrawn=True,
                )
            else:
                raise IntegrityFailure("Task execution correction action is invalid")
            continue

        if event.event_kind in {"start", "end"} and event.original_effective_at_utc is None:
            raise IntegrityFailure("Task execution start/end evidence requires an effective instant")
        evidence[event.event_id] = _EffectiveEvidence(
            event_id=event.event_id,
            revision=event.revision,
            event_kind=event.event_kind,
            original_effective_at_utc=event.original_effective_at_utc,
            current_effective_at_utc=event.original_effective_at_utc,
            withdrawn=False,
        )
        ordered_base_ids.append(event.event_id)

    state = "not_started"
    actual_start: int | None = None
    actual_end: int | None = None
    termination: int | None = None
    for event_id in ordered_base_ids:
        item = evidence[event_id]
        if item.withdrawn:
            continue
        if item.event_kind == "start":
            if state != "not_started" or item.current_effective_at_utc is None:
                raise IntegrityFailure("Task execution history contains an invalid effective start")
            state = "in_progress"
            actual_start = item.current_effective_at_utc
            actual_end = None
            termination = None
        elif item.event_kind == "end":
            if state != "in_progress" or actual_start is None or item.current_effective_at_utc is None:
                raise IntegrityFailure("Task execution history contains an invalid effective end")
            if item.current_effective_at_utc < actual_start:
                raise IntegrityFailure("Task execution end precedes accepted start")
            state = "ended"
            actual_end = item.current_effective_at_utc
            termination = None
        else:
            if state == "terminated":
                raise IntegrityFailure("Task execution history contains multiple effective terminal consequences")
            state = "terminated"
            actual_end = None
            termination = item.current_effective_at_utc
    return (state, actual_start, actual_end, termination), evidence


def _load_outcome_authority(connection: Any, task_id: str) -> _OutcomeAuthority:
    current = connection.execute(
        "SELECT outcome_event_id,accepted_outcome,reviewed_at_utc,revision,last_command_id "
        "FROM task_outcome_current WHERE task_id=?",
        (task_id,),
    ).fetchone()
    rows = connection.execute(
        "SELECT outcome_event_id,accepted_outcome,correction_of_event_id,reason_code,reviewed_at_utc,command_id "
        "FROM task_outcome_events WHERE task_id=?",
        (task_id,),
    ).fetchall()
    if current is None:
        if rows:
            raise IntegrityFailure("Task outcome history exists without current projection")
        return _OutcomeAuthority(0, None, None, None, None, None)
    if not rows:
        raise IntegrityFailure("Task outcome current projection exists without immutable history")

    revision = current[3]
    if type(revision) is not int or revision <= 0 or revision != len(rows):
        raise IntegrityFailure("Task outcome current revision does not equal immutable chain length")
    current_event_id = _stored_uuid(current[0], label="Task outcome current event identity")
    current_outcome = str(current[1])
    if current_outcome not in _OUTCOMES:
        raise IntegrityFailure("Task outcome current token is invalid")
    reviewed_at = current[2]
    if type(reviewed_at) is not int or reviewed_at < 0:
        raise IntegrityFailure("Task outcome current reviewed_at_utc is invalid")
    current_command_id = _stored_uuid(current[4], label="Task outcome current command identity")

    events: dict[str, tuple[str, str | None, str | None, int, str]] = {}
    child_of: dict[str, str] = {}
    genesis: list[str] = []
    for row in rows:
        event_id = _stored_uuid(row[0], label="Task outcome event identity")
        accepted_outcome = str(row[1])
        if accepted_outcome not in _OUTCOMES:
            raise IntegrityFailure("Task outcome history contains an invalid outcome token")
        predecessor = None if row[2] is None else _stored_uuid(
            row[2], label="Task outcome predecessor identity"
        )
        reason = None if row[3] is None else str(row[3])
        event_reviewed_at = row[4]
        if type(event_reviewed_at) is not int or event_reviewed_at < 0:
            raise IntegrityFailure("Task outcome history contains an invalid reviewed_at_utc")
        command_id = _stored_uuid(row[5], label="Task outcome command identity")
        if event_id in events:
            raise IntegrityFailure("Task outcome history contains duplicate event identity")
        events[event_id] = (accepted_outcome, predecessor, reason, event_reviewed_at, command_id)
        if predecessor is None:
            genesis.append(event_id)
        else:
            if predecessor in child_of:
                raise IntegrityFailure("Task outcome history branches from a prior event")
            child_of[predecessor] = event_id

    if len(genesis) != 1:
        raise IntegrityFailure("Task outcome history must contain exactly one genesis event")
    cursor = genesis[0]
    visited: set[str] = set()
    while True:
        if cursor in visited or cursor not in events:
            raise IntegrityFailure("Task outcome history correction chain is invalid")
        visited.add(cursor)
        next_event = child_of.get(cursor)
        if next_event is None:
            break
        cursor = next_event
    if len(visited) != len(events) or cursor != current_event_id:
        raise IntegrityFailure("Task outcome current event is not the unique immutable chain tip")

    current_event = events[current_event_id]
    if (
        current_event[0] != current_outcome
        or current_event[3] != reviewed_at
        or current_event[4] != current_command_id
    ):
        raise IntegrityFailure("Task outcome current projection disagrees with immutable chain tip")
    return _OutcomeAuthority(
        revision=revision,
        event_id=current_event_id,
        accepted_outcome=current_outcome,
        reason_category=current_event[2],
        reviewed_at_utc=reviewed_at,
        last_command_id=current_command_id,
    )


def _outcome_is_valid(
    outcome: str,
    *,
    execution_state: str,
    actual_start_utc: int | None,
    actual_end_utc: int | None,
) -> bool:
    if outcome == "completed":
        return execution_state == "ended" and actual_start_utc is not None and actual_end_utc is not None
    if outcome == "incomplete":
        return execution_state in {"ended", "terminated"} and actual_start_utc is not None
    return execution_state == "terminated" and actual_start_utc is None


def _execution_object(authority: _ExecutionAuthority) -> dict[str, object]:
    return {
        "revision": authority.revision,
        "state": authority.state,
        "actual_start_utc": authority.actual_start_utc,
        "actual_end_utc": authority.actual_end_utc,
        "effective_termination_utc": authority.effective_termination_utc,
        "last_event_id": authority.last_event_id,
    }


def _outcome_object(authority: _OutcomeAuthority) -> dict[str, object] | None:
    if authority.revision == 0:
        return None
    return {
        "revision": authority.revision,
        "event_id": authority.event_id,
        "accepted_outcome": authority.accepted_outcome,
        "reason_category": authority.reason_category,
        "reviewed_at_utc": authority.reviewed_at_utc,
    }


class TaskExecutionCorrectionQueryService:
    """Pure exact review authority for one proposed Task execution correction."""

    def __init__(self, connection_factory: ConnectionFactory) -> None:
        self._factory = connection_factory

    @classmethod
    def evaluate_connection(
        cls,
        connection: Any,
        *,
        task_id: str,
        task_revision: int,
        execution_revision: int,
        target_execution_event_id: str,
        target_execution_revision: int,
        correction_action: str,
        replacement_effective_at_utc: int | None,
        reason_category: str,
    ) -> TaskExecutionCorrectionPreview:
        canonical_task_id = require_uuid4(task_id)
        expected_task_revision = _require_positive_revision(task_revision, label="task_revision")
        expected_execution_revision = _require_positive_revision(
            execution_revision, label="execution_revision"
        )
        canonical_target_id = require_uuid4(target_execution_event_id)
        expected_target_revision = _require_positive_revision(
            target_execution_revision, label="target_execution_revision"
        )
        if correction_action not in {"replace_time", "withdraw"}:
            raise ValidationError("correction_action must be replace_time or withdraw")
        if correction_action == "replace_time":
            if type(replacement_effective_at_utc) is not int or replacement_effective_at_utc < 0:
                raise ValidationError(
                    "replacement_effective_at_utc must be a nonnegative UTC whole second for replace_time"
                )
        elif replacement_effective_at_utc is not None:
            raise ValidationError("replacement_effective_at_utc must be null for withdraw")
        normalized_reason = _normalize_reason(reason_category, required=True)
        assert normalized_reason is not None

        task = TaskRepository.get(connection, canonical_task_id)
        if task is None:
            raise SomaError("TASK_NOT_FOUND", "Task does not exist in current authority")
        if task.revision != expected_task_revision:
            raise SomaError("TASK_STALE", "Task revision changed since execution correction preview input")
        execution = _load_execution_authority(connection, canonical_task_id)
        if execution.revision != expected_execution_revision:
            raise SomaError("TASK_STALE", "Task execution revision changed since correction preview input")
        if execution.revision == 0:
            raise SomaError("TASK_STALE", "Task execution history is absent")

        target = next(
            (
                event
                for event in execution.events
                if event.event_id == canonical_target_id
                and event.revision == expected_target_revision
                and event.event_kind in _BASE_EVENT_KINDS
            ),
            None,
        )
        if target is None:
            raise SomaError("TASK_STALE", "Task execution correction target changed")
        _, current_evidence = _fold_execution(execution.events)
        effective_target = current_evidence.get(canonical_target_id)
        if effective_target is None:
            raise IntegrityFailure("Task execution correction target disappeared from folded evidence")

        outcome = _load_outcome_authority(connection, canonical_task_id)
        blockers: list[str] = []
        if effective_target.withdrawn:
            blockers.append("TARGET_NOT_CURRENT_EFFECTIVE")
        if (
            correction_action == "withdraw"
            and target.event_kind in _GOVERNED_TERMINAL_KINDS
        ):
            blockers.append("GOVERNED_TERMINAL_WITHDRAW_FORBIDDEN")

        synthetic = _ExecutionEvent(
            event_id="00000000-0000-4000-8000-000000000000",
            revision=execution.revision + 1,
            event_kind="correction",
            original_effective_at_utc=replacement_effective_at_utc,
            target_event_id=canonical_target_id,
            correction_action=correction_action,
            reason_code=normalized_reason,
            recorded_at_utc=0,
            command_id="00000000-0000-4000-8000-000000000001",
        )
        resulting_fold: tuple[str, int | None, int | None, int | None] | None = None
        if not effective_target.withdrawn and not (
            correction_action == "withdraw" and target.event_kind in _GOVERNED_TERMINAL_KINDS
        ):
            try:
                resulting_fold, _ = _fold_execution((*execution.events, synthetic))
            except IntegrityFailure:
                blockers.append("INVALID_CORRECTED_CHRONOLOGY")

        current_outcome_valid = bool(
            outcome.accepted_outcome is not None
            and _outcome_is_valid(
                outcome.accepted_outcome,
                execution_state=execution.state,
                actual_start_utc=execution.actual_start_utc,
                actual_end_utc=execution.actual_end_utc,
            )
        )
        outcome_invalidation_required = False
        if current_outcome_valid and resulting_fold is not None and outcome.accepted_outcome is not None:
            outcome_invalidation_required = not _outcome_is_valid(
                outcome.accepted_outcome,
                execution_state=resulting_fold[0],
                actual_start_utc=resulting_fold[1],
                actual_end_utc=resulting_fold[2],
            )

        resulting_execution = None
        if resulting_fold is not None:
            resulting_execution = {
                "state": resulting_fold[0],
                "actual_start_utc": resulting_fold[1],
                "actual_end_utc": resulting_fold[2],
                "effective_termination_utc": resulting_fold[3],
            }
        fingerprint_object = {
            "schema": "SOMA_TASK_EXECUTION_CORRECTION_REVIEW_V1",
            "task": {"task_id": canonical_task_id, "revision": task.revision},
            "execution": _execution_object(execution),
            "target": {
                "execution_event_id": target.event_id,
                "execution_revision": target.revision,
                "event_kind": target.event_kind,
                "original_effective_at_utc": target.original_effective_at_utc,
                "current_effective_at_utc": effective_target.current_effective_at_utc,
                "withdrawn": effective_target.withdrawn,
            },
            "request": {
                "correction_action": correction_action,
                "replacement_effective_at_utc": replacement_effective_at_utc,
                "reason_category": normalized_reason,
            },
            "current_outcome": _outcome_object(outcome),
            "resulting_execution": resulting_execution,
            "outcome_invalidation_required": outcome_invalidation_required,
        }
        resulting_state = execution.state if resulting_fold is None else resulting_fold[0]
        return TaskExecutionCorrectionPreview(
            eligible=not blockers,
            correction_review_fingerprint=sha256_canonical_json(fingerprint_object),
            execution_revision=execution.revision,
            target_execution_event_id=target.event_id,
            target_execution_revision=target.revision,
            target_event_kind=target.event_kind,
            target_effective_at_utc=effective_target.current_effective_at_utc,
            resulting_execution_state=resulting_state,
            outcome_invalidation_required=outcome_invalidation_required,
            current_outcome_revision=outcome.revision,
            current_outcome_event_id=outcome.event_id,
            blockers=tuple(blockers),
        )

    def preview(self, **kwargs: object) -> TaskExecutionCorrectionPreview:
        with ReadSnapshot(self._factory) as snapshot:
            return self.evaluate_connection(snapshot.connection, **kwargs)


class TaskOutcomeReviewQueryService:
    """Pure exact review authority for one proposed Task outcome review."""

    def __init__(self, connection_factory: ConnectionFactory) -> None:
        self._factory = connection_factory

    @classmethod
    def evaluate_connection(
        cls,
        connection: Any,
        *,
        task_id: str,
        task_revision: int,
        execution_revision: int,
        outcome_revision: int,
        current_outcome_event_id: str | None,
        outcome: str,
        reason_category: str | None,
    ) -> TaskOutcomeReviewPreview:
        canonical_task_id = require_uuid4(task_id)
        expected_task_revision = _require_positive_revision(task_revision, label="task_revision")
        expected_execution_revision = _require_positive_revision(
            execution_revision, label="execution_revision"
        )
        if type(outcome_revision) is not int or outcome_revision < 0:
            raise ValidationError("outcome_revision must be a nonnegative integer")
        if outcome_revision == 0:
            if current_outcome_event_id is not None:
                raise ValidationError("current_outcome_event_id must be null when outcome_revision is zero")
            canonical_event_id = None
        else:
            if not isinstance(current_outcome_event_id, str):
                raise ValidationError("current_outcome_event_id is required for positive outcome_revision")
            canonical_event_id = require_uuid4(current_outcome_event_id)
        if outcome not in _OUTCOMES:
            raise ValidationError("outcome must be completed, incomplete, or cancelled_without_execution")
        normalized_reason = _normalize_reason(reason_category)

        task = TaskRepository.get(connection, canonical_task_id)
        if task is None:
            raise SomaError("TASK_NOT_FOUND", "Task does not exist in current authority")
        if task.revision != expected_task_revision:
            raise SomaError("TASK_STALE", "Task revision changed since outcome review preview input")
        execution = _load_execution_authority(connection, canonical_task_id)
        if execution.revision != expected_execution_revision:
            raise SomaError("TASK_STALE", "Task execution revision changed since outcome review preview input")
        outcome_authority = _load_outcome_authority(connection, canonical_task_id)
        if outcome_authority.revision != outcome_revision or outcome_authority.event_id != canonical_event_id:
            raise SomaError("TASK_STALE", "Task outcome authority changed since outcome review preview input")

        blockers: list[str] = []
        if execution.state not in {"ended", "terminated"}:
            blockers.append("EXECUTION_NOT_TERMINAL")
        requested_valid = _outcome_is_valid(
            outcome,
            execution_state=execution.state,
            actual_start_utc=execution.actual_start_utc,
            actual_end_utc=execution.actual_end_utc,
        )
        if not requested_valid or (
            outcome == "incomplete" and execution.state == "ended" and normalized_reason is None
        ):
            blockers.append("OUTCOME_INVALID_FOR_EXECUTION")

        current_valid = bool(
            outcome_authority.accepted_outcome is not None
            and _outcome_is_valid(
                outcome_authority.accepted_outcome,
                execution_state=execution.state,
                actual_start_utc=execution.actual_start_utc,
                actual_end_utc=execution.actual_end_utc,
            )
        )
        exact_same = bool(
            current_valid
            and outcome_authority.accepted_outcome == outcome
            and outcome_authority.reason_category == normalized_reason
        )
        if outcome_authority.accepted_outcome is not None and not exact_same:
            blockers.append("CURRENT_OUTCOME_REQUIRES_CORRECTION")
        semantic_no_change = bool(exact_same and not blockers)

        authority = {
            "schema": "SOMA_TASK_OUTCOME_REVIEW_V1",
            "task": {"task_id": canonical_task_id, "revision": task.revision},
            "execution": _execution_object(execution),
            "current_outcome": _outcome_object(outcome_authority),
            "request": {"outcome": outcome, "reason_category": normalized_reason},
        }
        return TaskOutcomeReviewPreview(
            eligible=not blockers,
            outcome_review_fingerprint=sha256_canonical_json(authority),
            current_outcome_revision=outcome_authority.revision,
            current_outcome_event_id=outcome_authority.event_id,
            semantic_no_change=semantic_no_change,
            blockers=tuple(blockers),
        )

    def preview(self, **kwargs: object) -> TaskOutcomeReviewPreview:
        with ReadSnapshot(self._factory) as snapshot:
            return self.evaluate_connection(snapshot.connection, **kwargs)


class TaskOutcomeCorrectionQueryService:
    """Pure exact review authority for one proposed Task outcome correction."""

    def __init__(self, connection_factory: ConnectionFactory) -> None:
        self._factory = connection_factory

    @classmethod
    def evaluate_connection(
        cls,
        connection: Any,
        *,
        task_id: str,
        task_revision: int,
        execution_revision: int,
        current_outcome_revision: int,
        current_outcome_event_id: str,
        replacement_outcome: str,
        reason_category: str | None,
    ) -> TaskOutcomeCorrectionPreview:
        canonical_task_id = require_uuid4(task_id)
        expected_task_revision = _require_positive_revision(task_revision, label="task_revision")
        expected_execution_revision = _require_positive_revision(
            execution_revision, label="execution_revision"
        )
        expected_outcome_revision = _require_positive_revision(
            current_outcome_revision, label="current_outcome_revision"
        )
        canonical_event_id = require_uuid4(current_outcome_event_id)
        if replacement_outcome not in _OUTCOMES:
            raise ValidationError(
                "replacement_outcome must be completed, incomplete, or cancelled_without_execution"
            )
        normalized_reason = _normalize_reason(reason_category)

        task = TaskRepository.get(connection, canonical_task_id)
        if task is None:
            raise SomaError("TASK_NOT_FOUND", "Task does not exist in current authority")
        if task.revision != expected_task_revision:
            raise SomaError("TASK_STALE", "Task revision changed since outcome correction preview input")
        execution = _load_execution_authority(connection, canonical_task_id)
        if execution.revision != expected_execution_revision:
            raise SomaError("TASK_STALE", "Task execution revision changed since outcome correction preview input")
        outcome = _load_outcome_authority(connection, canonical_task_id)
        if outcome.revision != expected_outcome_revision or outcome.event_id != canonical_event_id:
            raise SomaError("TASK_STALE", "Task current outcome changed since correction preview input")
        if outcome.event_id is None or outcome.accepted_outcome is None:
            raise IntegrityFailure("positive Task outcome authority is unexpectedly absent")

        blockers: list[str] = []
        replacement_valid = _outcome_is_valid(
            replacement_outcome,
            execution_state=execution.state,
            actual_start_utc=execution.actual_start_utc,
            actual_end_utc=execution.actual_end_utc,
        )
        if not replacement_valid or (
            replacement_outcome == "incomplete"
            and execution.state == "ended"
            and normalized_reason is None
        ):
            blockers.append("OUTCOME_INVALID_FOR_EXECUTION")

        semantic_no_change = bool(
            replacement_valid
            and outcome.accepted_outcome == replacement_outcome
            and outcome.reason_category == normalized_reason
            and not blockers
        )
        authority = {
            "schema": "SOMA_TASK_OUTCOME_CORRECTION_REVIEW_V1",
            "task": {"task_id": canonical_task_id, "revision": task.revision},
            "execution": _execution_object(execution),
            "current_outcome": _outcome_object(outcome),
            "request": {
                "replacement_outcome": replacement_outcome,
                "reason_category": normalized_reason,
            },
        }
        return TaskOutcomeCorrectionPreview(
            eligible=not blockers,
            correction_review_fingerprint=sha256_canonical_json(authority),
            current_outcome_revision=outcome.revision,
            current_outcome_event_id=outcome.event_id,
            semantic_no_change=semantic_no_change,
            blockers=tuple(blockers),
        )

    def preview(self, **kwargs: object) -> TaskOutcomeCorrectionPreview:
        with ReadSnapshot(self._factory) as snapshot:
            return self.evaluate_connection(snapshot.connection, **kwargs)
