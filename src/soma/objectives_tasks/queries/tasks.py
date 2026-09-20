from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from soma.foundation.errors import IntegrityFailure, ValidationError
from soma.foundation.identifiers import require_uuid4
from soma.foundation.strict_json import sha256_canonical_json

from .execution_review import _load_execution_authority, _load_outcome_authority

_SHA256_CHARS = frozenset("0123456789abcdef")


@dataclass(frozen=True, slots=True)
class TaskOperationalExecution:
    execution_revision: int
    execution_state: str
    actual_start_utc: int | None
    actual_end_utc: int | None
    effective_termination_utc: int | None
    termination_reason: str | None
    last_event_id: str | None

    def to_payload(self) -> dict[str, object]:
        return {
            "execution_revision": self.execution_revision,
            "execution_state": self.execution_state,
            "actual_start_utc": self.actual_start_utc,
            "actual_end_utc": self.actual_end_utc,
            "effective_termination_utc": self.effective_termination_utc,
            "termination_reason": self.termination_reason,
            "last_event_id": self.last_event_id,
        }


@dataclass(frozen=True, slots=True)
class TaskOperationalOutcome:
    outcome_event_id: str
    accepted_outcome: str
    reviewed_at_utc: int
    outcome_revision: int

    def to_payload(self) -> dict[str, object]:
        return {
            "outcome_event_id": self.outcome_event_id,
            "accepted_outcome": self.accepted_outcome,
            "reviewed_at_utc": self.reviewed_at_utc,
            "outcome_revision": self.outcome_revision,
        }


@dataclass(frozen=True, slots=True)
class TaskOperationalObjectiveContext:
    objective_id: str
    membership_revision: int
    accepted_plan_revision_id: str
    membership_last_event_id: str
    objective_revision: int
    envelope_revision: int
    aggregate_revision: int
    aggregate_input_fingerprint: str

    def to_payload(self) -> dict[str, object]:
        return {
            "objective_id": self.objective_id,
            "membership_revision": self.membership_revision,
            "accepted_plan_revision_id": self.accepted_plan_revision_id,
            "membership_last_event_id": self.membership_last_event_id,
            "objective_revision": self.objective_revision,
            "envelope_revision": self.envelope_revision,
            "aggregate_revision": self.aggregate_revision,
            "aggregate_input_fingerprint": self.aggregate_input_fingerprint,
        }


def _connection(reader: Any) -> Any:
    if hasattr(reader, "execute"):
        return reader
    connection = getattr(reader, "connection", None)
    if connection is None or not hasattr(connection, "execute"):
        raise ValidationError("Task operational reader requires a database read context")
    return connection


def _positive(value: object, *, field: str) -> int:
    if type(value) is not int or value <= 0:
        raise IntegrityFailure(f"{field} is invalid")
    return value


def _sha256(value: object, *, field: str) -> str:
    if (
        not isinstance(value, str)
        or len(value) != 64
        or any(character not in _SHA256_CHARS for character in value)
    ):
        raise IntegrityFailure(f"{field} is invalid")
    return value


class TaskOperationalEvidenceReader:
    """LLD-05 read-only accepted operational evidence provider for cross-packet consumers."""

    @staticmethod
    def _require_task(connection: Any, task_id: str) -> str:
        canonical = require_uuid4(task_id)
        row = connection.execute(
            "SELECT 1 FROM tasks WHERE task_id=?",
            (canonical,),
        ).fetchone()
        if row is None:
            raise ValidationError("Task does not exist")
        return canonical

    @classmethod
    def task_execution(cls, reader: Any, task_id: str) -> TaskOperationalExecution:
        connection = _connection(reader)
        canonical = cls._require_task(connection, task_id)
        authority = _load_execution_authority(connection, canonical)
        return TaskOperationalExecution(
            execution_revision=authority.revision,
            execution_state=authority.state,
            actual_start_utc=authority.actual_start_utc,
            actual_end_utc=authority.actual_end_utc,
            effective_termination_utc=authority.effective_termination_utc,
            termination_reason=authority.termination_reason,
            last_event_id=authority.last_event_id,
        )

    @classmethod
    def task_outcome(
        cls,
        reader: Any,
        task_id: str,
    ) -> TaskOperationalOutcome | None:
        connection = _connection(reader)
        canonical = cls._require_task(connection, task_id)
        authority = _load_outcome_authority(connection, canonical)
        if authority.revision == 0:
            if (
                authority.event_id is not None
                or authority.accepted_outcome is not None
                or authority.reviewed_at_utc is not None
            ):
                raise IntegrityFailure("empty Task outcome authority is contradictory")
            return None
        if (
            authority.event_id is None
            or authority.accepted_outcome is None
            or authority.reviewed_at_utc is None
        ):
            raise IntegrityFailure("positive Task outcome authority is incomplete")
        return TaskOperationalOutcome(
            outcome_event_id=authority.event_id,
            accepted_outcome=authority.accepted_outcome,
            reviewed_at_utc=authority.reviewed_at_utc,
            outcome_revision=authority.revision,
        )

    @classmethod
    def objective_context(
        cls,
        reader: Any,
        task_id: str,
    ) -> TaskOperationalObjectiveContext | None:
        connection = _connection(reader)
        canonical = cls._require_task(connection, task_id)
        row = connection.execute(
            "SELECT m.objective_id,m.membership_revision,m.accepted_plan_revision_id,"
            "m.last_event_id,o.revision,e.revision,a.revision,a.aggregate_input_fingerprint "
            "FROM objective_task_membership_current m "
            "JOIN objectives o ON o.objective_id=m.objective_id "
            "LEFT JOIN objective_envelope_projection e ON e.objective_id=m.objective_id "
            "LEFT JOIN objective_aggregate_projection a ON a.objective_id=m.objective_id "
            "WHERE m.task_id=?",
            (canonical,),
        ).fetchone()
        if row is None:
            return None
        if row[5] is None or row[6] is None or row[7] is None:
            raise IntegrityFailure("current Task Objective membership lacks required Objective projections")

        objective_id = require_uuid4(str(row[0]))
        membership_revision = _positive(row[1], field="Task Objective membership revision")
        plan_revision_id = require_uuid4(str(row[2]))
        membership_event_id = require_uuid4(str(row[3]))
        objective_revision = _positive(row[4], field="Objective revision")
        envelope_revision = _positive(row[5], field="Objective envelope revision")
        aggregate_revision = _positive(row[6], field="Objective aggregate revision")
        aggregate_fingerprint = _sha256(
            row[7],
            field="Objective aggregate input fingerprint",
        )

        event = connection.execute(
            "SELECT task_id,to_objective_id,accepted_plan_revision_id "
            "FROM objective_membership_events WHERE membership_event_id=?",
            (membership_event_id,),
        ).fetchone()
        if event is None:
            raise IntegrityFailure("Task Objective membership points to missing immutable event")
        if (
            str(event[0]) != canonical
            or event[1] is None
            or str(event[1]) != objective_id
            or str(event[2]) != plan_revision_id
        ):
            raise IntegrityFailure("Task Objective membership disagrees with immutable event")

        plan = connection.execute(
            "SELECT task_id FROM task_plan_revisions WHERE plan_revision_id=?",
            (plan_revision_id,),
        ).fetchone()
        if plan is None or str(plan[0]) != canonical:
            raise IntegrityFailure("Task Objective membership references a plan owned by another Task")

        return TaskOperationalObjectiveContext(
            objective_id=objective_id,
            membership_revision=membership_revision,
            accepted_plan_revision_id=plan_revision_id,
            membership_last_event_id=membership_event_id,
            objective_revision=objective_revision,
            envelope_revision=envelope_revision,
            aggregate_revision=aggregate_revision,
            aggregate_input_fingerprint=aggregate_fingerprint,
        )

    @classmethod
    def review_fingerprint(cls, reader: Any, task_id: str) -> str:
        connection = _connection(reader)
        canonical = cls._require_task(connection, task_id)
        execution = cls.task_execution(connection, canonical)
        outcome = cls.task_outcome(connection, canonical)
        objective = cls.objective_context(connection, canonical)
        return sha256_canonical_json(
            {
                "schema": "SOMA_TASK_OPERATIONAL_EVIDENCE_V1",
                "task_id": canonical,
                "execution": execution.to_payload(),
                "outcome": None if outcome is None else outcome.to_payload(),
                "objective_context": None if objective is None else objective.to_payload(),
            }
        )


__all__ = [
    "TaskOperationalEvidenceReader",
    "TaskOperationalExecution",
    "TaskOperationalObjectiveContext",
    "TaskOperationalOutcome",
]
