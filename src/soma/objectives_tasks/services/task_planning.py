from __future__ import annotations

from collections.abc import Sequence

import regex

from soma.foundation.application.command_boundary import CommandBoundary, CommandEnvelope, PreparedMutation
from soma.foundation.audit.writer import AuditEventInput, AuditResultRef, AuditWriter
from soma.foundation.errors import IntegrityFailure, SomaError, ValidationError
from soma.foundation.identifiers import new_uuid4, require_uuid4, utc_epoch_seconds
from soma.foundation.persistence.connections import ConnectionFactory
from soma.foundation.persistence.uow import UnitOfWork
from soma.reference.domain.matching import trim_match_whitespace

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
    TaskRelationshipRecord,
    TaskRelationshipRepository,
    TaskRepository,
    WfmTaskRepository,
)

_TERMINAL_RFC_STATUS_CLASSES = frozenset({"terminal_closed", "terminal_cancelled"})
_LOCAL_TASK_NAME_MAX_GRAPHEMES = 240
_LOCAL_TASK_NAME_MAX_UTF8_BYTES = 1024
_LOCAL_TASK_INITIAL_RELATIONSHIP_MAX = 62
_RELATIONSHIP_EXISTENCE_CHUNK = 256
_TASK_REASON_CATEGORY_MAX_UTF8_BYTES = 128


def validate_local_task_name(value: str) -> str:
    if not isinstance(value, str):
        raise SomaError("TASK_NAME_REQUIRED", "Local Task name must be text")
    try:
        encoded = value.encode("utf-8", errors="strict")
    except UnicodeEncodeError as exc:
        raise SomaError("TASK_NAME_REQUIRED", "Local Task name must be valid Unicode") from exc
    if not encoded or len(encoded) > _LOCAL_TASK_NAME_MAX_UTF8_BYTES:
        raise SomaError("TASK_NAME_REQUIRED", "Local Task name is empty or exceeds its UTF-8 byte bound")
    if not trim_match_whitespace(value):
        raise SomaError("TASK_NAME_REQUIRED", "Local Task name cannot be blank")
    grapheme_count = 0
    for _ in regex.finditer(r"\X", value, flags=regex.VERSION1):
        grapheme_count += 1
        if grapheme_count > _LOCAL_TASK_NAME_MAX_GRAPHEMES:
            raise SomaError("TASK_NAME_REQUIRED", "Local Task name exceeds its grapheme bound")
    if grapheme_count == 0:
        raise SomaError("TASK_NAME_REQUIRED", "Local Task name cannot be empty")
    return value


def _canonical_relationship_ids(value: Sequence[str], *, field: str) -> tuple[str, ...]:
    if isinstance(value, (str, bytes)) or not isinstance(value, Sequence):
        raise ValidationError(f"{field} must be a sequence of UUIDs")
    canonical: list[str] = []
    seen: set[str] = set()
    for item in value:
        if not isinstance(item, str):
            raise ValidationError(f"{field} must contain UUID text")
        identity = require_uuid4(item)
        if identity in seen:
            raise ValidationError(f"{field} cannot contain duplicate identities")
        seen.add(identity)
        canonical.append(identity)
    canonical.sort()
    return tuple(canonical)


def validate_wfm_task_no(value: str) -> str:
    if (
        not isinstance(value, str)
        or len(value) != 16
        or value[:2] != "TK"
        or any(character < "0" or character > "9" for character in value[2:])
    ):
        raise SomaError("WFM_TASK_NO_INVALID", "WFM Task No must be exactly TK followed by fourteen ASCII digits")
    return value


def validate_task_reason_category(value: str) -> str:
    if not isinstance(value, str):
        raise ValidationError("reason_category must be text")
    try:
        encoded = value.encode("utf-8", errors="strict")
    except UnicodeEncodeError as exc:
        raise ValidationError("reason_category must be valid Unicode") from exc
    if (
        not encoded
        or len(encoded) > _TASK_REASON_CATEGORY_MAX_UTF8_BYTES
        or "\x00" in value
        or "\r" in value
        or "\n" in value
    ):
        raise ValidationError("reason_category violates its bounded one-line contract")
    return value


class TaskPlanningService:
    """LLD-05 Task identity, initial planning, and WFM parent authority."""

    def __init__(self, connection_factory: ConnectionFactory) -> None:
        self._factory = connection_factory
        self._tasks = TaskRepository()
        self._wfm = WfmTaskRepository()
        self._plans = TaskPlanRepository()
        self._relationships = TaskRelationshipRepository()
        self._boundary = CommandBoundary(
            connection_factory,
            AuditWriter(build_objectives_tasks_audit_registry()),
        )

    @staticmethod
    def _require_existing_relationship_targets(
        connection,
        *,
        identities: tuple[str, ...],
        table: str,
        id_column: str,
        field: str,
    ) -> None:
        if not identities:
            return
        missing = set(identities)
        for offset in range(0, len(identities), _RELATIONSHIP_EXISTENCE_CHUNK):
            chunk = identities[offset : offset + _RELATIONSHIP_EXISTENCE_CHUNK]
            placeholders = ",".join("?" for _ in chunk)
            rows = connection.execute(
                f"SELECT {id_column} FROM {table} WHERE {id_column} IN ({placeholders})",
                chunk,
            ).fetchall()
            missing.difference_update(str(row[0]) for row in rows)
        if missing:
            raise ValidationError(f"{field} contains an identity that does not exist")

    @classmethod
    def _revalidate_local_relationship_targets(
        cls,
        connection,
        *,
        service_request_ids: tuple[str, ...],
        rfc_ids: tuple[str, ...],
        device_reference_ids: tuple[str, ...],
    ) -> None:
        cls._require_existing_relationship_targets(
            connection,
            identities=service_request_ids,
            table="service_requests",
            id_column="service_request_id",
            field="service_request_ids",
        )
        cls._require_existing_relationship_targets(
            connection,
            identities=rfc_ids,
            table="rfcs",
            id_column="rfc_id",
            field="rfc_ids",
        )
        cls._require_existing_relationship_targets(
            connection,
            identities=device_reference_ids,
            table="device_references",
            id_column="device_reference_id",
            field="device_reference_ids",
        )

    @staticmethod
    def _initial_relationship_rows(
        *,
        task_id: str,
        command_id: str,
        service_request_ids: tuple[str, ...],
        rfc_ids: tuple[str, ...],
        device_reference_ids: tuple[str, ...],
    ) -> tuple[TaskRelationshipRecord, ...]:
        rows: list[TaskRelationshipRecord] = []
        for kind, identities in (
            ("sr", service_request_ids),
            ("rfc", rfc_ids),
            ("device", device_reference_ids),
        ):
            for related_id in identities:
                rows.append(
                    TaskRelationshipRecord(
                        relationship_id=new_uuid4(),
                        task_id=task_id,
                        relationship_kind=kind,
                        related_id=related_id,
                        opened_command_id=command_id,
                    )
                )
        return tuple(rows)

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

    @staticmethod
    def _history_exists(connection, sql: str, task_id: str, *, twice: bool = False) -> bool:
        params = (task_id, task_id) if twice else (task_id,)
        return connection.execute(sql, params).fetchone() is not None

    @classmethod
    def _classify_wfm_parent_history_risk(cls, connection, task_id: str) -> str:
        plan_history = cls._history_exists(
            connection,
            "SELECT 1 FROM task_plan_revisions WHERE task_id=? LIMIT 1",
            task_id,
        )
        plan_current = cls._history_exists(
            connection,
            "SELECT 1 FROM task_plan_current WHERE task_id=? LIMIT 1",
            task_id,
        )
        plan_current_bound = cls._history_exists(
            connection,
            "SELECT 1 FROM task_plan_current c JOIN task_plan_revisions p "
            "ON p.plan_revision_id=c.plan_revision_id AND p.task_id=c.task_id "
            "WHERE c.task_id=? LIMIT 1",
            task_id,
        )

        objective_history = cls._history_exists(
            connection,
            "SELECT 1 FROM objective_membership_events WHERE task_id=? LIMIT 1",
            task_id,
        )
        objective_current = cls._history_exists(
            connection,
            "SELECT 1 FROM objective_task_membership_current WHERE task_id=? LIMIT 1",
            task_id,
        )
        objective_current_bound = cls._history_exists(
            connection,
            "SELECT 1 FROM objective_task_membership_current c JOIN objective_membership_events e "
            "ON e.membership_event_id=c.last_event_id AND e.task_id=c.task_id "
            "AND e.accepted_plan_revision_id=c.accepted_plan_revision_id AND e.to_objective_id=c.objective_id "
            "WHERE c.task_id=? LIMIT 1",
            task_id,
        )

        execution_history = cls._history_exists(
            connection,
            "SELECT 1 FROM task_execution_events WHERE task_id=? LIMIT 1",
            task_id,
        )
        execution_current = cls._history_exists(
            connection,
            "SELECT 1 FROM task_execution_projection WHERE task_id=? LIMIT 1",
            task_id,
        )
        execution_current_bound = cls._history_exists(
            connection,
            "SELECT 1 FROM task_execution_projection c JOIN task_execution_events e "
            "ON e.execution_event_id=c.last_event_id AND e.task_id=c.task_id "
            "WHERE c.task_id=? LIMIT 1",
            task_id,
        )

        outcome_history = cls._history_exists(
            connection,
            "SELECT 1 FROM task_outcome_events WHERE task_id=? LIMIT 1",
            task_id,
        )
        outcome_current = cls._history_exists(
            connection,
            "SELECT 1 FROM task_outcome_current WHERE task_id=? LIMIT 1",
            task_id,
        )
        outcome_current_bound = cls._history_exists(
            connection,
            "SELECT 1 FROM task_outcome_current c JOIN task_outcome_events e "
            "ON e.outcome_event_id=c.outcome_event_id AND e.task_id=c.task_id "
            "AND e.accepted_outcome=c.accepted_outcome WHERE c.task_id=? LIMIT 1",
            task_id,
        )

        if (
            (plan_current and not plan_current_bound)
            or (objective_current and not objective_current_bound)
            or (execution_current and not execution_current_bound)
            or (outcome_current and not outcome_current_bound)
        ):
            raise SomaError(
                "WFM_PARENT_STALE",
                "WFM Task history projections cannot be reconciled to their owned history",
            )

        source_history = cls._history_exists(
            connection,
            "SELECT 1 FROM wfm_source_projection_cache WHERE task_id=? LIMIT 1",
            task_id,
        )
        retry_history = cls._history_exists(
            connection,
            "SELECT 1 FROM task_retry_relations WHERE predecessor_task_id=? OR successor_task_id=? LIMIT 1",
            task_id,
            twice=True,
        )
        return (
            "high"
            if any(
                (
                    plan_history,
                    source_history,
                    objective_history,
                    execution_history,
                    retry_history,
                    outcome_history,
                )
            )
            else "low"
        )

    def create_local_task(
        self,
        *,
        command_id: str,
        local_task_name: str,
        schedule: AcceptedTaskSchedule | None = None,
        service_request_ids: Sequence[str] = (),
        rfc_ids: Sequence[str] = (),
        device_reference_ids: Sequence[str] = (),
        actor_kind: str = "local_user",
        actor_id: str | None = None,
    ) -> TaskMutationResult:
        stored_name = validate_local_task_name(local_task_name)
        if schedule is not None and not isinstance(schedule, AcceptedTaskSchedule):
            raise ValidationError("schedule must be AcceptedTaskSchedule or None")
        accepted_schedule = None if schedule is None else schedule.validate()
        canonical_sr_ids = _canonical_relationship_ids(service_request_ids, field="service_request_ids")
        canonical_rfc_ids = _canonical_relationship_ids(rfc_ids, field="rfc_ids")
        canonical_device_ids = _canonical_relationship_ids(device_reference_ids, field="device_reference_ids")
        relationship_count = len(canonical_sr_ids) + len(canonical_rfc_ids) + len(canonical_device_ids)
        if relationship_count > _LOCAL_TASK_INITIAL_RELATIONSHIP_MAX:
            raise ValidationError(
                f"CreateLocalTask accepts at most {_LOCAL_TASK_INITIAL_RELATIONSHIP_MAX} initial relationships"
            )
        envelope = CommandEnvelope(
            command_id=command_id,
            command_type="CreateLocalTask",
            target_type="task",
            target_id=None,
            semantic_payload={
                "local_task_name": stored_name,
                "schedule": None if accepted_schedule is None else accepted_schedule.semantic_payload(),
                "relationships": {
                    "service_request_ids": list(canonical_sr_ids),
                    "rfc_ids": list(canonical_rfc_ids),
                    "device_reference_ids": list(canonical_device_ids),
                },
            },
        )

        def prepare(uow: UnitOfWork) -> PreparedMutation:
            self._revalidate_local_relationship_targets(
                uow.connection,
                service_request_ids=canonical_sr_ids,
                rfc_ids=canonical_rfc_ids,
                device_reference_ids=canonical_device_ids,
            )
            task_id = new_uuid4()
            plan_revision_id = None if accepted_schedule is None else new_uuid4()
            relationship_rows = self._initial_relationship_rows(
                task_id=task_id,
                command_id=command_id,
                service_request_ids=canonical_sr_ids,
                rfc_ids=canonical_rfc_ids,
                device_reference_ids=canonical_device_ids,
            )
            audit_event_id = new_uuid4()
            now = utc_epoch_seconds()

            def apply(inner: UnitOfWork) -> AuditEventInput:
                self._tasks.insert(
                    inner,
                    TaskRecord(
                        task_id=task_id,
                        task_kind="local",
                        local_task_name=stored_name,
                        creation_origin="manual",
                        revision=1,
                        created_at_utc=now,
                        created_command_id=command_id,
                    ),
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
                for relationship in relationship_rows:
                    self._relationships.link(inner, relationship)
                audit_refs = [AuditResultRef("task", task_id)]
                if plan_revision_id is not None:
                    audit_refs.append(AuditResultRef("task_plan", plan_revision_id))
                audit_refs.extend(
                    AuditResultRef("task_relationship", relationship.relationship_id)
                    for relationship in relationship_rows
                )
                return AuditEventInput(
                    audit_event_id=audit_event_id,
                    action_type="task.created",
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
                        "task_kind": "local",
                        "creation_origin": "manual",
                        "resulting_revision": 1,
                        "task_plan_revision_id": plan_revision_id,
                        "reason_category": None,
                    },
                    resulting_event_refs=tuple(audit_refs),
                )

            result_refs = [{"type": "task", "id": task_id}]
            if plan_revision_id is not None:
                result_refs.append({"type": "task_plan", "id": plan_revision_id})
            result_refs.extend(
                {"type": "task_relationship", "id": relationship.relationship_id}
                for relationship in relationship_rows
            )
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

    def reassign_wfm_parent(
        self,
        *,
        command_id: str,
        task_id: str,
        task_revision: int,
        assignment_revision: int,
        new_rfc_id: str,
        reason_category: str,
        accept_high_risk: bool,
        actor_kind: str = "local_user",
        actor_id: str | None = None,
    ) -> TaskMutationResult:
        canonical_task_id = require_uuid4(task_id)
        canonical_new_rfc_id = require_uuid4(new_rfc_id)
        if type(task_revision) is not int or task_revision <= 0:
            raise ValidationError("task_revision must be a positive integer")
        if type(assignment_revision) is not int or assignment_revision <= 0:
            raise ValidationError("assignment_revision must be a positive integer")
        reason = validate_task_reason_category(reason_category)
        if type(accept_high_risk) is not bool:
            raise ValidationError("accept_high_risk must be a boolean")

        envelope = CommandEnvelope(
            command_id=command_id,
            command_type="ReassignWfmParent",
            target_type="task",
            target_id=canonical_task_id,
            semantic_payload={
                "new_rfc_id": canonical_new_rfc_id,
                "reason_category": reason,
                "accept_high_risk": accept_high_risk,
            },
            base_revisions={
                canonical_task_id: task_revision,
                f"wfm_assignment:{canonical_task_id}": assignment_revision,
            },
        )

        def prepare(uow: UnitOfWork) -> PreparedMutation:
            task = self._tasks.get(uow.connection, canonical_task_id)
            identity = self._wfm.get_identity(uow.connection, canonical_task_id)
            if task is None or task.task_kind != "wfm" or identity is None:
                raise SomaError("TASK_NOT_FOUND", "WFM Task does not exist in current authority")
            if task.revision != task_revision:
                raise SomaError("TASK_STALE", "Task revision changed before WFM parent reassignment")
            if identity.assignment_revision != assignment_revision:
                raise SomaError("WFM_PARENT_STALE", "WFM assignment revision changed before reassignment")
            if identity.current_rfc_id == canonical_new_rfc_id:
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

            review_risk = self._classify_wfm_parent_history_risk(uow.connection, canonical_task_id)
            if review_risk == "high" and not accept_high_risk:
                raise SomaError(
                    "WFM_PARENT_REVIEW_REQUIRED",
                    "protected Task history requires explicit high-risk WFM parent reassignment acceptance",
                )
            self._require_eligible_rfc(uow.connection, canonical_new_rfc_id)

            prior_rfc_id = identity.current_rfc_id
            assignment_event_id = new_uuid4()
            audit_event_id = new_uuid4()
            now = utc_epoch_seconds()
            resulting_revision = task.revision + 1

            def apply(inner: UnitOfWork) -> AuditEventInput:
                self._wfm.reassign_rfc(
                    inner,
                    assignment_event_id=assignment_event_id,
                    task_id=canonical_task_id,
                    prior_rfc_id=prior_rfc_id,
                    new_rfc_id=canonical_new_rfc_id,
                    expected_assignment_revision=assignment_revision,
                    reason_code=reason,
                    review_risk=review_risk,
                    command_id=command_id,
                    recorded_at_utc=now,
                )
                self._tasks.increment_revision(
                    inner,
                    task_id=canonical_task_id,
                    expected_revision=task_revision,
                )
                return AuditEventInput(
                    audit_event_id=audit_event_id,
                    action_type="task.wfm_parent_reassigned",
                    action_version=1,
                    actor_kind=actor_kind,
                    actor_id=actor_id,
                    target_type="task",
                    target_id=canonical_task_id,
                    reason_category=reason,
                    command_id=command_id,
                    payload_schema="TaskRelationshipAuditV1",
                    payload_version=1,
                    payload={
                        "task_id": canonical_task_id,
                        "relationship_kind": "wfm_parent",
                        "action": "REASSIGN",
                        "relationship_id": assignment_event_id,
                        "related_id": canonical_new_rfc_id,
                        "prior_related_id": prior_rfc_id,
                        "resulting_revision": resulting_revision,
                        "reason_category": reason,
                    },
                    resulting_event_refs=(AuditResultRef("wfm_assignment", assignment_event_id),),
                )

            return PreparedMutation(
                False,
                "wfm_assignment",
                assignment_event_id,
                apply,
                response_schema="TaskMutationResultV1",
                response_version=1,
                response={
                    "outcome": "APPLIED",
                    "task_id": canonical_task_id,
                    "revision": resulting_revision,
                    "result_refs": [{"type": "wfm_assignment", "id": assignment_event_id}],
                },
            )

        return task_mutation_result_from_execution(self._boundary.execute(envelope, prepare))
