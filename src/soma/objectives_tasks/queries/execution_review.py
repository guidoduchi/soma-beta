from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from soma.foundation.errors import IntegrityFailure, SomaError, ValidationError
from soma.foundation.identifiers import require_uuid4
from soma.foundation.persistence.connections import ConnectionFactory
from soma.foundation.persistence.uow import ReadSnapshot
from soma.foundation.strict_json import sha256_canonical_json

from ..repositories.tasks import TaskRepository
from ..services.task_execution import TaskExecutionService
from ..services.task_planning import validate_task_reason_category

_OUTCOMES = frozenset({"completed", "incomplete", "cancelled_without_execution"})


@dataclass(frozen=True, slots=True)
class TaskOutcomeReviewPreview:
    eligible: bool
    fingerprint: str
    current_outcome_revision: int
    current_outcome_event_id: str | None
    semantic_no_change: bool
    blockers: tuple[str, ...]

    def to_response(self) -> dict[str, object]:
        return {
            "eligible": self.eligible,
            "fingerprint": self.fingerprint,
            "current_outcome_revision": self.current_outcome_revision,
            "current_outcome_event_id": self.current_outcome_event_id,
            "semantic_no_change": self.semantic_no_change,
            "blockers": list(self.blockers),
        }


@dataclass(frozen=True, slots=True)
class _OutcomeAuthority:
    revision: int
    event_id: str | None
    accepted_outcome: str | None
    reason_category: str | None
    reviewed_at_utc: int | None
    last_command_id: str | None


class TaskOutcomeReviewQueryService:
    """Pure exact review authority for one proposed Task outcome review."""

    def __init__(self, connection_factory: ConnectionFactory) -> None:
        self._factory = connection_factory

    @staticmethod
    def _require_inputs(
        *,
        task_id: str,
        task_revision: int,
        execution_revision: int,
        outcome_revision: int,
        current_outcome_event_id: str | None,
        outcome: str,
        reason_category: str | None,
    ) -> tuple[str, str | None, str | None]:
        canonical_task_id = require_uuid4(task_id)
        if type(task_revision) is not int or task_revision <= 0:
            raise ValidationError("task_revision must be a positive integer")
        if type(execution_revision) is not int or execution_revision <= 0:
            raise ValidationError("execution_revision must be a positive integer")
        if type(outcome_revision) is not int or outcome_revision < 0:
            raise ValidationError("outcome_revision must be a nonnegative integer")
        canonical_event_id: str | None = None
        if outcome_revision == 0:
            if current_outcome_event_id is not None:
                raise ValidationError("current_outcome_event_id must be null when outcome_revision is zero")
        else:
            if not isinstance(current_outcome_event_id, str):
                raise ValidationError("current_outcome_event_id is required for positive outcome_revision")
            canonical_event_id = require_uuid4(current_outcome_event_id)
        if outcome not in _OUTCOMES:
            raise ValidationError("outcome must be completed, incomplete, or cancelled_without_execution")
        normalized_reason = None if reason_category is None else validate_task_reason_category(reason_category)
        return canonical_task_id, canonical_event_id, normalized_reason

    @staticmethod
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
        current_event_id = require_uuid4(str(current[0]))
        current_outcome = str(current[1])
        if current_outcome not in _OUTCOMES:
            raise IntegrityFailure("Task outcome current token is invalid")
        reviewed_at = current[2]
        if type(reviewed_at) is not int or reviewed_at < 0:
            raise IntegrityFailure("Task outcome current reviewed_at_utc is invalid")
        current_command_id = require_uuid4(str(current[4]))

        events: dict[str, tuple[str, str | None, str | None, int, str]] = {}
        child_of: dict[str, str] = {}
        genesis: list[str] = []
        for row in rows:
            event_id = require_uuid4(str(row[0]))
            accepted_outcome = str(row[1])
            if accepted_outcome not in _OUTCOMES:
                raise IntegrityFailure("Task outcome history contains an invalid outcome token")
            predecessor = None if row[2] is None else require_uuid4(str(row[2]))
            reason = None if row[3] is None else str(row[3])
            event_reviewed_at = row[4]
            if type(event_reviewed_at) is not int or event_reviewed_at < 0:
                raise IntegrityFailure("Task outcome history contains an invalid reviewed_at_utc")
            command_id = require_uuid4(str(row[5]))
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
        visited: list[str] = []
        while True:
            if cursor in visited or cursor not in events:
                raise IntegrityFailure("Task outcome history correction chain is invalid")
            visited.append(cursor)
            next_event = child_of.get(cursor)
            if next_event is None:
                break
            cursor = next_event
        if len(visited) != len(events) or cursor != current_event_id:
            raise IntegrityFailure("Task outcome current event is not the unique immutable chain tip")

        current_event = events.get(current_event_id)
        if current_event is None:
            raise IntegrityFailure("Task outcome current event is missing from immutable history")
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

    @staticmethod
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
        canonical_task_id, canonical_event_id, normalized_reason = cls._require_inputs(
            task_id=task_id,
            task_revision=task_revision,
            execution_revision=execution_revision,
            outcome_revision=outcome_revision,
            current_outcome_event_id=current_outcome_event_id,
            outcome=outcome,
            reason_category=reason_category,
        )
        task = TaskRepository.get(connection, canonical_task_id)
        if task is None:
            raise SomaError("TASK_NOT_FOUND", "Task does not exist in current authority")
        if task.revision != task_revision:
            raise SomaError("TASK_STALE", "Task revision changed since outcome review preview input")

        execution = TaskExecutionService._execution_authority(connection, canonical_task_id)
        if execution.revision != execution_revision:
            raise SomaError("TASK_STALE", "Task execution revision changed since outcome review preview input")
        outcome_authority = cls._load_outcome_authority(connection, canonical_task_id)
        if outcome_authority.revision != outcome_revision or outcome_authority.event_id != canonical_event_id:
            raise SomaError("TASK_STALE", "Task outcome authority changed since outcome review preview input")

        requested_valid = cls._outcome_is_valid(
            outcome,
            execution_state=execution.state,
            actual_start_utc=execution.actual_start_utc,
            actual_end_utc=execution.actual_end_utc,
        )
        blockers: list[str] = []
        if not requested_valid:
            blockers.append("OUTCOME_INCOMPATIBLE_WITH_EXECUTION")
        if outcome == "incomplete" and execution.state == "ended" and normalized_reason is None:
            blockers.append("OUTCOME_REASON_REQUIRED")

        current_valid = False
        if outcome_authority.accepted_outcome is not None:
            current_valid = cls._outcome_is_valid(
                outcome_authority.accepted_outcome,
                execution_state=execution.state,
                actual_start_utc=execution.actual_start_utc,
                actual_end_utc=execution.actual_end_utc,
            )
            if not (
                current_valid
                and outcome_authority.accepted_outcome == outcome
                and outcome_authority.reason_category == normalized_reason
            ):
                blockers.append("OUTCOME_CORRECTION_REQUIRED")

        semantic_no_change = bool(
            outcome_authority.accepted_outcome is not None
            and current_valid
            and outcome_authority.accepted_outcome == outcome
            and outcome_authority.reason_category == normalized_reason
            and not blockers
        )
        authority = {
            "schema": "SOMA_TASK_OUTCOME_REVIEW_V1",
            "task": {
                "task_id": canonical_task_id,
                "revision": task.revision,
            },
            "execution": {
                "revision": execution.revision,
                "state": execution.state,
                "actual_start_utc": execution.actual_start_utc,
                "actual_end_utc": execution.actual_end_utc,
                "effective_termination_utc": execution.effective_termination_utc,
                "last_event_id": execution.last_event_id,
            },
            "current_outcome": None
            if outcome_authority.revision == 0
            else {
                "revision": outcome_authority.revision,
                "event_id": outcome_authority.event_id,
                "accepted_outcome": outcome_authority.accepted_outcome,
                "reason_category": outcome_authority.reason_category,
                "reviewed_at_utc": outcome_authority.reviewed_at_utc,
            },
            "request": {
                "outcome": outcome,
                "reason_category": normalized_reason,
            },
        }
        return TaskOutcomeReviewPreview(
            eligible=not blockers,
            fingerprint=sha256_canonical_json(authority),
            current_outcome_revision=outcome_authority.revision,
            current_outcome_event_id=outcome_authority.event_id,
            semantic_no_change=semantic_no_change,
            blockers=tuple(blockers),
        )

    def preview(
        self,
        *,
        task_id: str,
        task_revision: int,
        execution_revision: int,
        outcome_revision: int,
        current_outcome_event_id: str | None,
        outcome: str,
        reason_category: str | None,
    ) -> TaskOutcomeReviewPreview:
        with ReadSnapshot(self._factory) as snapshot:
            return self.evaluate_connection(
                snapshot.connection,
                task_id=task_id,
                task_revision=task_revision,
                execution_revision=execution_revision,
                outcome_revision=outcome_revision,
                current_outcome_event_id=current_outcome_event_id,
                outcome=outcome,
                reason_category=reason_category,
            )
