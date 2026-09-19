from __future__ import annotations

import re
from typing import Any

from soma.foundation.errors import IntegrityFailure, ValidationError
from soma.foundation.identifiers import require_uuid4
from soma.foundation.strict_json import sha256_canonical_json

from .execution_review import _load_execution_authority, _load_outcome_authority

_SHA256 = re.compile(r"[0-9a-f]{64}\Z")


def _connection(reader: Any) -> Any:
    connection = getattr(reader, "connection", None)
    if connection is not None:
        return connection
    if hasattr(reader, "execute"):
        return reader
    raise ValidationError("Task operational evidence reader requires Snapshot, UnitOfWork, or connection")


def _task_id(connection: Any, task_id: str) -> str:
    canonical = require_uuid4(task_id)
    if connection.execute(
        "SELECT 1 FROM tasks WHERE task_id=?",
        (canonical,),
    ).fetchone() is None:
        raise IntegrityFailure("Task operational evidence target does not exist")
    return canonical


class TaskOperationalEvidenceReader:
    """Read-only LLD-05 owner boundary consumed by Inventory/Overview."""

    @classmethod
    def task_execution(cls, reader: Any, task_id: str) -> dict[str, object]:
        connection = _connection(reader)
        canonical = _task_id(connection, task_id)
        authority = _load_execution_authority(connection, canonical)
        return {
            "execution_revision": authority.revision,
            "execution_state": authority.state,
            "actual_start_utc": authority.actual_start_utc,
            "actual_end_utc": authority.actual_end_utc,
            "effective_termination_utc": authority.effective_termination_utc,
            "termination_reason": authority.termination_reason,
            "last_event_id": authority.last_event_id,
        }

    @classmethod
    def task_outcome(
        cls,
        reader: Any,
        task_id: str,
    ) -> dict[str, object] | None:
        connection = _connection(reader)
        canonical = _task_id(connection, task_id)
        authority = _load_outcome_authority(connection, canonical)
        if authority.revision == 0:
            if any(
                value is not None
                for value in (
                    authority.event_id,
                    authority.accepted_outcome,
                    authority.reviewed_at_utc,
                    authority.last_command_id,
                )
            ):
                raise IntegrityFailure("Task outcome absence authority is inconsistent")
            return None
        if (
            authority.event_id is None
            or authority.accepted_outcome is None
            or authority.reviewed_at_utc is None
        ):
            raise IntegrityFailure("Task outcome positive authority is incomplete")
        return {
            "outcome_event_id": authority.event_id,
            "accepted_outcome": authority.accepted_outcome,
            "reviewed_at_utc": authority.reviewed_at_utc,
            "outcome_revision": authority.revision,
        }

    @classmethod
    def objective_context(
        cls,
        reader: Any,
        task_id: str,
    ) -> dict[str, object] | None:
        connection = _connection(reader)
        canonical = _task_id(connection, task_id)
        row = connection.execute(
            "SELECT m.objective_id,m.membership_revision,m.accepted_plan_revision_id,"
            "m.last_event_id,o.revision,e.revision,a.revision,a.aggregate_input_fingerprint,"
            "p.task_id,me.task_id,me.to_objective_id,me.accepted_plan_revision_id "
            "FROM objective_task_membership_current m "
            "JOIN objectives o ON o.objective_id=m.objective_id "
            "JOIN objective_envelope_projection e ON e.objective_id=m.objective_id "
            "JOIN objective_aggregate_projection a ON a.objective_id=m.objective_id "
            "JOIN task_plan_revisions p ON p.plan_revision_id=m.accepted_plan_revision_id "
            "JOIN objective_membership_events me ON me.membership_event_id=m.last_event_id "
            "WHERE m.task_id=?",
            (canonical,),
        ).fetchone()
        if row is None:
            orphan = connection.execute(
                "SELECT 1 FROM objective_task_membership_current WHERE task_id=?",
                (canonical,),
            ).fetchone()
            if orphan is not None:
                raise IntegrityFailure("Task Objective membership authority is incomplete")
            return None

        objective_id = str(row[0])
        membership_revision = row[1]
        accepted_plan_revision_id = str(row[2])
        membership_last_event_id = str(row[3])
        objective_revision = row[4]
        envelope_revision = row[5]
        aggregate_revision = row[6]
        aggregate_fingerprint = row[7]
        for label, value in (
            ("membership_revision", membership_revision),
            ("objective_revision", objective_revision),
            ("envelope_revision", envelope_revision),
            ("aggregate_revision", aggregate_revision),
        ):
            if type(value) is not int or value <= 0:
                raise IntegrityFailure(f"Task Objective {label} is invalid")
        for label, value in (
            ("objective_id", objective_id),
            ("accepted_plan_revision_id", accepted_plan_revision_id),
            ("membership_last_event_id", membership_last_event_id),
        ):
            try:
                require_uuid4(value)
            except ValidationError as exc:
                raise IntegrityFailure(f"Task Objective {label} is invalid") from exc
        if (
            not isinstance(aggregate_fingerprint, str)
            or _SHA256.fullmatch(aggregate_fingerprint) is None
        ):
            raise IntegrityFailure("Task Objective aggregate fingerprint is invalid")
        if str(row[8]) != canonical or str(row[9]) != canonical:
            raise IntegrityFailure("Task Objective membership points to another Task")
        if str(row[10]) != objective_id or str(row[11]) != accepted_plan_revision_id:
            raise IntegrityFailure("Task Objective membership disagrees with immutable event authority")
        return {
            "objective_id": objective_id,
            "membership_revision": int(membership_revision),
            "accepted_plan_revision_id": accepted_plan_revision_id,
            "membership_last_event_id": membership_last_event_id,
            "objective_revision": int(objective_revision),
            "envelope_revision": int(envelope_revision),
            "aggregate_revision": int(aggregate_revision),
            "aggregate_input_fingerprint": aggregate_fingerprint,
        }

    @classmethod
    def review_fingerprint(cls, reader: Any, task_id: str) -> str:
        connection = _connection(reader)
        canonical = _task_id(connection, task_id)
        return sha256_canonical_json(
            {
                "schema": "SOMA_TASK_OPERATIONAL_EVIDENCE_V1",
                "task_id": canonical,
                "execution": cls.task_execution(connection, canonical),
                "outcome": cls.task_outcome(connection, canonical),
                "objective_context": cls.objective_context(connection, canonical),
            }
        )


__all__ = ["TaskOperationalEvidenceReader"]
