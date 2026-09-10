from __future__ import annotations

import re

from soma.foundation.application.command_boundary import CommandBoundary, CommandEnvelope, PreparedMutation
from soma.foundation.audit.writer import AuditEventInput, AuditResultRef, AuditWriter
from soma.foundation.errors import IntegrityFailure, SomaError, ValidationError
from soma.foundation.identifiers import new_uuid4, require_uuid4, utc_epoch_seconds
from soma.foundation.persistence.connections import ConnectionFactory
from soma.foundation.persistence.uow import UnitOfWork

from ..audit_registry import build_objectives_tasks_audit_registry
from ..contracts.objectives_tasks import (
    AcceptedTaskSchedule,
    TaskMutationResult,
    task_mutation_result_from_execution,
)
from ..queries.task_plan_correction import TaskPlanCorrectionQueryService
from ..repositories.tasks import TaskPlanRecord, TaskPlanRepository, TaskRepository
from .task_planning import validate_task_reason_category

_SHA256_RE = re.compile(r"[0-9a-f]{64}\Z")
_PROTECTED_OBJECTIVE_PLAN_STATES = frozenset(
    {"historical_structure", "in_progress", "awaiting_review", "reviewed", "superseded"}
)


def _validate_correction_fingerprint(value: str) -> str:
    if not isinstance(value, str) or _SHA256_RE.fullmatch(value) is None:
        raise ValidationError("correction_review_fingerprint must be lowercase SHA-256 hex")
    return value


class TaskPlanCorrectionService:
    """Preview-bound, history-preserving correction of an existing Task plan."""

    def __init__(self, connection_factory: ConnectionFactory) -> None:
        self._tasks = TaskRepository()
        self._plans = TaskPlanRepository()
        self._reviews = TaskPlanCorrectionQueryService(connection_factory)
        self._boundary = CommandBoundary(
            connection_factory,
            AuditWriter(build_objectives_tasks_audit_registry()),
        )

    @staticmethod
    def _surface_mutable_objective_mismatch(
        uow: UnitOfWork,
        *,
        task_id: str,
        command_id: str,
    ) -> bool:
        row = uow.connection.execute(
            "SELECT m.objective_id,o.creation_origin,o.superseded_by_objective_id,"
            "a.execution_state,a.attention_reason,a.revision "
            "FROM objective_task_membership_current m "
            "LEFT JOIN objectives o ON o.objective_id=m.objective_id "
            "LEFT JOIN objective_aggregate_projection a ON a.objective_id=m.objective_id "
            "WHERE m.task_id=?",
            (task_id,),
        ).fetchone()
        if row is None:
            return False
        if row[1] is None or row[3] is None or row[5] is None:
            raise SomaError("TASK_PLAN_LOCKED", "current Objective authority cannot be reconciled safely")
        objective_id = str(row[0])
        creation_origin = str(row[1])
        superseded_by = None if row[2] is None else str(row[2])
        execution_state = str(row[3])
        attention_reason = None if row[4] is None else str(row[4])
        aggregate_revision = int(row[5])
        protected = (
            superseded_by is not None
            or creation_origin == "historical_provider_complete"
            or execution_state in _PROTECTED_OBJECTIVE_PLAN_STATES
        )
        if protected or attention_reason is not None:
            return True
        updated = uow.connection.execute(
            "UPDATE objective_aggregate_projection "
            "SET attention_reason='plan_membership_mismatch',revision=revision+1,last_command_id=? "
            "WHERE objective_id=? AND revision=? AND attention_reason IS NULL",
            (command_id, objective_id, aggregate_revision),
        )
        if updated.rowcount != 1:
            raise IntegrityFailure("Objective aggregate authority changed during corrected-plan mismatch projection")
        return True

    def correct_task_plan(
        self,
        *,
        command_id: str,
        task_id: str,
        task_revision: int,
        current_plan_revision: int,
        current_plan_revision_id: str,
        schedule: AcceptedTaskSchedule,
        reason_category: str,
        correction_review_fingerprint: str,
        accept_high_risk: bool,
        actor_kind: str = "local_user",
        actor_id: str | None = None,
    ) -> TaskMutationResult:
        canonical_task_id = require_uuid4(task_id)
        canonical_plan_id = require_uuid4(current_plan_revision_id)
        if type(task_revision) is not int or task_revision <= 0:
            raise ValidationError("task_revision must be a positive integer")
        if type(current_plan_revision) is not int or current_plan_revision <= 0:
            raise ValidationError("current_plan_revision must be a positive integer")
        if not isinstance(schedule, AcceptedTaskSchedule):
            raise ValidationError("schedule must be AcceptedTaskSchedule")
        accepted_schedule = schedule.validate()
        reason = validate_task_reason_category(reason_category)
        fingerprint = _validate_correction_fingerprint(correction_review_fingerprint)
        if type(accept_high_risk) is not bool:
            raise ValidationError("accept_high_risk must be a boolean")

        envelope = CommandEnvelope(
            command_id=command_id,
            command_type="CorrectTaskPlan",
            target_type="task",
            target_id=canonical_task_id,
            semantic_payload={
                "current_plan_revision": current_plan_revision,
                "current_plan_revision_id": canonical_plan_id,
                "schedule": accepted_schedule.semantic_payload(),
                "reason_category": reason,
                "accept_high_risk": accept_high_risk,
            },
            base_revisions={canonical_task_id: task_revision},
            authorizing_fingerprints={"correction_review_fingerprint": fingerprint},
        )

        def prepare(uow: UnitOfWork) -> PreparedMutation:
            preview = self._reviews.evaluate_connection(
                uow.connection,
                task_id=canonical_task_id,
                task_revision=task_revision,
                current_plan_revision=current_plan_revision,
                current_plan_revision_id=canonical_plan_id,
                schedule=accepted_schedule,
            )
            if preview.fingerprint != fingerprint:
                raise SomaError("TASK_STALE", "Task plan correction authority changed since preview")
            if preview.blockers:
                raise SomaError("TASK_PLAN_LOCKED", "Task plan correction has a non-overridable current blocker")

            task = self._tasks.get(uow.connection, canonical_task_id)
            pointer = self._plans.current_pointer(uow.connection, canonical_task_id)
            prior_plan = self._plans.get_revision(uow.connection, canonical_plan_id)
            if (
                task is None
                or task.revision != task_revision
                or pointer is None
                or pointer.revision != current_plan_revision
                or pointer.plan_revision_id != canonical_plan_id
                or prior_plan is None
                or prior_plan.task_id != canonical_task_id
            ):
                raise SomaError("TASK_STALE", "Task plan correction freshness changed during writer revalidation")

            if (
                prior_plan.start_utc == accepted_schedule.start_utc
                and prior_plan.end_utc == accepted_schedule.end_utc
                and prior_plan.scheduling_timezone_iana == accepted_schedule.scheduling_timezone_iana
            ):
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

            if preview.risk == "HIGH" and not accept_high_risk:
                raise SomaError(
                    "TASK_PLAN_LOCKED",
                    "Task plan correction requires explicit high-risk review acceptance",
                )

            plan_revision_id = new_uuid4()
            audit_event_id = new_uuid4()
            now = utc_epoch_seconds()
            resulting_revision = task.revision + 1
            plan_row = TaskPlanRecord(
                plan_revision_id=plan_revision_id,
                task_id=canonical_task_id,
                start_utc=accepted_schedule.start_utc,
                end_utc=accepted_schedule.end_utc,
                origin="correction",
                scheduling_timezone_iana=accepted_schedule.scheduling_timezone_iana,
                source_observation_id=None,
                predecessor_plan_revision_id=canonical_plan_id,
                reason_code=reason,
                accepted_at_utc=now,
                command_id=command_id,
            )

            def apply(inner: UnitOfWork) -> AuditEventInput:
                self._plans.append_and_set_current(
                    inner,
                    plan_row,
                    expected_current_revision=current_plan_revision,
                )
                self._tasks.increment_revision(
                    inner,
                    task_id=canonical_task_id,
                    expected_revision=task_revision,
                )
                membership_plan_mismatch = self._surface_mutable_objective_mismatch(
                    inner,
                    task_id=canonical_task_id,
                    command_id=command_id,
                )
                return AuditEventInput(
                    audit_event_id=audit_event_id,
                    action_type="task.plan_corrected",
                    action_version=1,
                    actor_kind=actor_kind,
                    actor_id=actor_id,
                    target_type="task",
                    target_id=canonical_task_id,
                    reason_category=reason,
                    command_id=command_id,
                    payload_schema="TaskPlanCorrectionAuditV1",
                    payload_version=1,
                    payload={
                        "task_id": canonical_task_id,
                        "prior_plan_revision_id": canonical_plan_id,
                        "new_plan_revision_id": plan_revision_id,
                        "resulting_task_revision": resulting_revision,
                        "reason_category": reason,
                        "membership_plan_mismatch": membership_plan_mismatch,
                        "review_risk": preview.risk,
                        "correction_review_fingerprint": fingerprint,
                    },
                    resulting_event_refs=(AuditResultRef("task_plan", plan_revision_id),),
                )

            return PreparedMutation(
                False,
                "task_plan",
                plan_revision_id,
                apply,
                response_schema="TaskMutationResultV1",
                response_version=1,
                response={
                    "outcome": "APPLIED",
                    "task_id": canonical_task_id,
                    "revision": resulting_revision,
                    "result_refs": [{"type": "task_plan", "id": plan_revision_id}],
                },
            )

        return task_mutation_result_from_execution(self._boundary.execute(envelope, prepare))
