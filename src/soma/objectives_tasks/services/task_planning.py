from __future__ import annotations

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
from ..repositories.tasks import (
    TaskNoStatus,
    TaskPlanRecord,
    TaskPlanRepository,
    TaskRecord,
    TaskRepository,
    WfmTaskRepository,
)

_TERMINAL_RFC_STATUS_CLASSES = frozenset({"terminal_closed", "terminal_cancelled"})


def validate_wfm_task_no(value: str) -> str:
    if (
        not isinstance(value, str)
        or len(value) != 16
        or value[:2] != "TK"
        or any(character < "0" or character > "9" for character in value[2:])
    ):
        raise SomaError("WFM_TASK_NO_INVALID", "WFM Task No must be exactly TK followed by fourteen ASCII digits")
    return value


class TaskPlanningService:
    """Initial LLD-05 planning authority for manual WFM identity registration."""

    def __init__(self, connection_factory: ConnectionFactory) -> None:
        self._factory = connection_factory
        self._tasks = TaskRepository()
        self._wfm = WfmTaskRepository()
        self._plans = TaskPlanRepository()
        self._boundary = CommandBoundary(
            connection_factory,
            AuditWriter(build_objectives_tasks_audit_registry()),
        )

    @staticmethod
    def _require_eligible_rfc(connection, rfc_id: str) -> None:
        row = connection.execute(
            "SELECT r.local_archive_state,COALESCE(p.status_class,'unknown') "
            "FROM rfcs r LEFT JOIN rfc_current_source_projection p ON p.rfc_id=r.rfc_id "
            "WHERE r.rfc_id=?",
            (rfc_id,),
        ).fetchone()
        if row is None:
            raise SomaError("WFM_RFC_NOT_ELIGIBLE", "owning RFC does not exist")
        archive_state, status_class = str(row[0]), str(row[1])
        if archive_state != "active" or status_class in _TERMINAL_RFC_STATUS_CLASSES:
            raise SomaError("WFM_RFC_NOT_ELIGIBLE", "owning RFC cannot own active nonterminal WFM work")

    def register_manual_wfm_task(
        self,
        *,
        command_id: str,
        task_no: str,
        rfc_id: str,
        schedule: AcceptedTaskSchedule | None = None,
        actor_kind: str = "local_user",
        actor_id: str | None = None,
    ) -> TaskMutationResult:
        canonical_task_no = validate_wfm_task_no(task_no)
        canonical_rfc_id = require_uuid4(rfc_id)
        if schedule is not None and not isinstance(schedule, AcceptedTaskSchedule):
            raise ValidationError("schedule must be AcceptedTaskSchedule or None")
        accepted_schedule = None if schedule is None else schedule.validate()
        envelope = CommandEnvelope(
            command_id=command_id,
            command_type="RegisterManualWfmTask",
            target_type="task",
            target_id=None,
            semantic_payload={
                "task_no": canonical_task_no,
                "rfc_id": canonical_rfc_id,
                "schedule": None if accepted_schedule is None else accepted_schedule.semantic_payload(),
            },
        )

        def prepare(uow: UnitOfWork) -> PreparedMutation:
            status = self._wfm.task_no_status(uow.connection, canonical_task_no)
            if status is TaskNoStatus.RETIRED:
                raise SomaError("WFM_TASK_NO_RETIRED", "WFM Task No is permanently retired and cannot be reused")
            if status is TaskNoStatus.ACTIVE:
                identity = self._wfm.get_by_task_no(uow.connection, canonical_task_no)
                if identity is None:
                    raise IntegrityFailure("ACTIVE WFM Task No has no current identity row")
                task = self._tasks.get(uow.connection, identity.task_id)
                if task is None or task.task_kind != "wfm":
                    raise IntegrityFailure("WFM identity does not resolve to a WFM Task")
                if identity.current_rfc_id != canonical_rfc_id:
                    raise SomaError(
                        "WFM_PARENT_STALE",
                        "WFM Task No already exists under a different RFC; use reviewed reassignment",
                    )
                return PreparedMutation(
                    True,
                    None,
                    None,
                    response_schema="TaskMutationResultV1",
                    response_version=1,
                    response={
                        "outcome": "NO_CHANGE",
                        "task_id": task.task_id,
                        "revision": task.revision,
                        "result_refs": [],
                    },
                )

            self._require_eligible_rfc(uow.connection, canonical_rfc_id)
            task_id = new_uuid4()
            assignment_event_id = new_uuid4()
            plan_revision_id = None if accepted_schedule is None else new_uuid4()
            audit_event_id = new_uuid4()
            now = utc_epoch_seconds()

            def apply(inner: UnitOfWork) -> AuditEventInput:
                self._tasks.insert(
                    inner,
                    TaskRecord(
                        task_id=task_id,
                        task_kind="wfm",
                        local_task_name=None,
                        creation_origin="wfm_manual",
                        revision=1,
                        created_at_utc=now,
                        created_command_id=command_id,
                    ),
                )
                self._wfm.insert_identity(
                    inner,
                    task_id=task_id,
                    task_no=canonical_task_no,
                    rfc_id=canonical_rfc_id,
                    created_command_id=command_id,
                )
                self._wfm.insert_initial_assignment(
                    inner,
                    assignment_event_id=assignment_event_id,
                    task_id=task_id,
                    rfc_id=canonical_rfc_id,
                    command_id=command_id,
                    recorded_at_utc=now,
                )
                if accepted_schedule is not None and plan_revision_id is not None:
                    self._plans.insert_initial(
                        inner,
                        TaskPlanRecord(
                            plan_revision_id=plan_revision_id,
                            task_id=task_id,
                            start_utc=accepted_schedule.start_utc,
                            end_utc=accepted_schedule.end_utc,
                            origin="manual",
                            scheduling_timezone_iana=accepted_schedule.scheduling_timezone_iana,
                            source_observation_id=None,
                            predecessor_plan_revision_id=None,
                            reason_code=None,
                            accepted_at_utc=now,
                            command_id=command_id,
                        ),
                    )
                return AuditEventInput(
                    audit_event_id=audit_event_id,
                    action_type="task.wfm_registered",
                    action_version=1,
                    actor_kind=actor_kind,
                    actor_id=actor_id,
                    target_type="task",
                    target_id=task_id,
                    command_id=command_id,
                    payload_schema="TaskAuditV1",
                    payload_version=1,
                    payload={
                        "task_id": task_id,
                        "task_kind": "wfm",
                        "creation_origin": "wfm_manual",
                        "resulting_revision": 1,
                        "task_plan_revision_id": plan_revision_id,
                        "reason_category": None,
                    },
                    resulting_event_refs=(
                        AuditResultRef("task", task_id),
                        AuditResultRef("wfm_assignment", assignment_event_id),
                    ),
                )

            result_refs = [
                {"type": "task", "id": task_id},
                {"type": "wfm_assignment", "id": assignment_event_id},
            ]
            if plan_revision_id is not None:
                result_refs.append({"type": "task_plan", "id": plan_revision_id})
            return PreparedMutation(
                False,
                "task",
                task_id,
                apply,
                response_schema="TaskMutationResultV1",
                response_version=1,
                response={
                    "outcome": "APPLIED",
                    "task_id": task_id,
                    "revision": 1,
                    "result_refs": result_refs,
                },
            )

        return task_mutation_result_from_execution(self._boundary.execute(envelope, prepare))
