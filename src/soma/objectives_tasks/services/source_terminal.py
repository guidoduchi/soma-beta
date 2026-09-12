from __future__ import annotations

import hmac
import re
from typing import Any

from soma.foundation.application.command_boundary import CommandBoundary, CommandEnvelope, PreparedMutation
from soma.foundation.audit.registry import AuditActionContract
from soma.foundation.audit.writer import AuditEventInput, AuditResultRef, AuditWriter
from soma.foundation.errors import IntegrityFailure, SomaError, ValidationError
from soma.foundation.identifiers import new_uuid4, require_uuid4, utc_epoch_seconds
from soma.foundation.persistence.connections import ConnectionFactory
from soma.foundation.persistence.uow import UnitOfWork
from soma.foundation.strict_json import ObjectContract

from ..audit_registry import build_objectives_tasks_audit_registry
from ..contracts.objectives_tasks import TaskMutationResult, task_mutation_result_from_execution
from ..repositories.objectives import ObjectiveProjectionRepository
from ..repositories.tasks import TaskRepository, WfmTaskRepository
from ..source_terminal_authority import (
    current_source_projection,
    get_source_terminal_review,
    source_terminal_review_fingerprint,
)
from .task_execution import TaskExecutionService
from .task_planning import validate_task_reason_category

_SHA256_RE = re.compile(r"[0-9a-f]{64}\Z")
_DECISIONS = frozenset({"retain_local_work", "terminate_local_work"})
_AUDIT_FIELDS = frozenset(
    {
        "task_id",
        "review_id",
        "source_projection_revision",
        "source_evidence_id",
        "review_fingerprint",
        "accepted_local_consequence",
        "execution_event_id",
        "reason_category",
    }
)


def _require_positive_revision(value: int, *, label: str) -> int:
    if type(value) is not int or value <= 0:
        raise ValidationError(f"{label} must be a positive integer")
    return value


def _require_sha256(value: object, *, label: str) -> str:
    if not isinstance(value, str) or _SHA256_RE.fullmatch(value) is None:
        raise ValidationError(f"{label} must be lowercase SHA-256 hex")
    return value


def _require_decision(value: object) -> str:
    if value not in _DECISIONS:
        raise ValidationError("decision must be retain_local_work or terminate_local_work")
    return str(value)


def _validate_source_terminal_audit(payload: dict[str, object]) -> None:
    try:
        task_id = payload.get("task_id")
        review_id = payload.get("review_id")
        source_evidence_id = payload.get("source_evidence_id")
        execution_event_id = payload.get("execution_event_id")
        for value in (task_id, review_id, source_evidence_id):
            if not isinstance(value, str):
                raise ValidationError("source-terminal audit identity must be UUID text")
            require_uuid4(value)
        if execution_event_id is not None:
            if not isinstance(execution_event_id, str):
                raise ValidationError("execution_event_id must be UUID text or null")
            require_uuid4(execution_event_id)
    except ValidationError as exc:
        raise SomaError("AUDIT_PAYLOAD_INVALID", "source-terminal audit identity is invalid") from exc

    revision = payload.get("source_projection_revision")
    if type(revision) is not int or revision <= 0:
        raise SomaError("AUDIT_PAYLOAD_INVALID", "source-terminal audit source revision is invalid")
    fingerprint = payload.get("review_fingerprint")
    if not isinstance(fingerprint, str) or _SHA256_RE.fullmatch(fingerprint) is None:
        raise SomaError("AUDIT_PAYLOAD_INVALID", "source-terminal audit fingerprint is invalid")
    decision = payload.get("accepted_local_consequence")
    if decision not in _DECISIONS:
        raise SomaError("AUDIT_PAYLOAD_INVALID", "source-terminal audit decision is invalid")
    if (decision == "retain_local_work") != (payload.get("execution_event_id") is None):
        raise SomaError("AUDIT_PAYLOAD_INVALID", "source-terminal audit consequence identity is inconsistent")
    try:
        validate_task_reason_category(payload.get("reason_category"))
    except ValidationError as exc:
        raise SomaError("AUDIT_PAYLOAD_INVALID", "source-terminal audit reason is invalid") from exc


def _build_source_terminal_audit_registry():
    registry = build_objectives_tasks_audit_registry()
    registry.register(
        AuditActionContract(
            action_type="task.source_terminal_consequence_resolved",
            action_version=1,
            payload_schema="TaskSourceTerminalAuditV1",
            payload_version=1,
            payload_contract=ObjectContract(
                name="TaskSourceTerminalAuditV1",
                version=1,
                required_fields=_AUDIT_FIELDS,
                allowed_fields=_AUDIT_FIELDS,
                max_depth=3,
                max_collection_items=16,
                max_utf8_bytes=16_384,
            ),
            sensitivity_validator=_validate_source_terminal_audit,
        )
    )
    return registry


class WfmSourceTerminalService:
    """Resolve reviewed WFM terminal source evidence into an explicit local consequence."""

    def __init__(self, connection_factory: ConnectionFactory) -> None:
        self._tasks = TaskRepository()
        self._objectives = ObjectiveProjectionRepository()
        self._boundary = CommandBoundary(
            connection_factory,
            AuditWriter(_build_source_terminal_audit_registry()),
        )

    @staticmethod
    def _require_current_review(
        connection: Any,
        *,
        review_id: str,
        task_id: str,
        source_projection_revision: int,
        input_fingerprint: str,
    ):
        review = get_source_terminal_review(connection, review_id)
        if review is None:
            raise SomaError("WFM_SOURCE_TERMINAL_STALE", "WFM source-terminal review is missing")
        if (
            review.task_id != task_id
            or review.source_projection_revision != source_projection_revision
            or review.input_fingerprint != input_fingerprint
            or review.state != "pending"
            or review.revision != 1
            or review.local_consequence_event_id is not None
            or review.decided_at_utc is not None
        ):
            raise SomaError("WFM_SOURCE_TERMINAL_STALE", "WFM source-terminal review changed after review")
        return review

    @staticmethod
    def _advance_termination_projection(
        uow: UnitOfWork,
        *,
        task_id: str,
        authority: Any,
        execution_event_id: str,
        reason: str,
    ) -> None:
        if authority.revision == 0:
            uow.connection.execute(
                "INSERT INTO task_execution_projection(task_id,execution_state,actual_start_utc,actual_end_utc,"
                "effective_termination_utc,termination_reason,revision,last_event_id) "
                "VALUES (?,'terminated',NULL,NULL,NULL,?,1,?)",
                (task_id, reason, execution_event_id),
            )
            return
        updated = uow.connection.execute(
            "UPDATE task_execution_projection SET execution_state='terminated',actual_end_utc=NULL,"
            "effective_termination_utc=NULL,termination_reason=?,revision=revision+1,last_event_id=? "
            "WHERE task_id=? AND revision=?",
            (reason, execution_event_id, task_id, authority.revision),
        )
        if updated.rowcount != 1:
            raise IntegrityFailure("Task execution projection changed during source-terminal consequence")

    def resolve_wfm_source_terminal_consequence(
        self,
        *,
        command_id: str,
        source_terminal_review_id: str,
        task_id: str,
        source_projection_revision: int,
        input_fingerprint: str,
        decision: str,
        reason_category: str,
        actor_kind: str = "local_user",
        actor_id: str | None = None,
    ) -> TaskMutationResult:
        canonical_review_id = require_uuid4(source_terminal_review_id)
        canonical_task_id = require_uuid4(task_id)
        expected_source_revision = _require_positive_revision(
            source_projection_revision,
            label="source_projection_revision",
        )
        reviewed_fingerprint = _require_sha256(input_fingerprint, label="input_fingerprint")
        accepted_decision = _require_decision(decision)
        reason = validate_task_reason_category(reason_category)

        envelope = CommandEnvelope(
            command_id=command_id,
            command_type="ResolveWfmSourceTerminalConsequence",
            target_type="task",
            target_id=canonical_task_id,
            semantic_payload={
                "source_terminal_review_id": canonical_review_id,
                "source_projection_revision": expected_source_revision,
                "input_fingerprint": reviewed_fingerprint,
                "decision": accepted_decision,
                "reason_category": reason,
            },
        )

        def prepare(uow: UnitOfWork) -> PreparedMutation:
            task = self._tasks.get(uow.connection, canonical_task_id)
            if task is None:
                raise SomaError("TASK_NOT_FOUND", "Task does not exist")
            if task.task_kind != "wfm" or WfmTaskRepository.get_identity(uow.connection, canonical_task_id) is None:
                raise IntegrityFailure("source-terminal review target lacks canonical WFM identity")

            review = self._require_current_review(
                uow.connection,
                review_id=canonical_review_id,
                task_id=canonical_task_id,
                source_projection_revision=expected_source_revision,
                input_fingerprint=reviewed_fingerprint,
            )
            source = current_source_projection(uow.connection, canonical_task_id)
            if (
                source is None
                or source.provider_lifecycle_class not in {"complete", "plan_cancel"}
                or source.source_projection_revision != expected_source_revision
                or source.provider_lifecycle_class != review.provider_lifecycle_class
                or source.accepted_source_observation_id is None
            ):
                raise SomaError("WFM_SOURCE_TERMINAL_STALE", "accepted WFM terminal source authority changed")

            current_fingerprint = source_terminal_review_fingerprint(uow.connection, canonical_task_id)
            if (
                not hmac.compare_digest(review.input_fingerprint, reviewed_fingerprint)
                or not hmac.compare_digest(current_fingerprint, reviewed_fingerprint)
            ):
                raise SomaError("WFM_SOURCE_TERMINAL_STALE", "WFM source-terminal review authority changed")

            execution = TaskExecutionService._execution_authority(uow.connection, canonical_task_id)
            if accepted_decision == "terminate_local_work" and execution.state in {"ended", "terminated"}:
                raise SomaError("TASK_EXECUTION_ALREADY_TERMINAL", "Task execution is already terminal")

            now = utc_epoch_seconds()
            audit_event_id = new_uuid4()
            execution_event_id = new_uuid4() if accepted_decision == "terminate_local_work" else None
            resulting_task_revision = task.revision + (1 if execution_event_id is not None else 0)
            resulting_execution_revision = execution.revision + (1 if execution_event_id is not None else 0)
            result_refs = [{"type": "wfm_source_terminal_review", "id": canonical_review_id}]
            if execution_event_id is not None:
                result_refs.append({"type": "task_execution_event", "id": execution_event_id})

            def apply(inner: UnitOfWork) -> AuditEventInput:
                if execution_event_id is not None:
                    inner.connection.execute(
                        "INSERT INTO task_execution_events(execution_event_id,task_id,execution_revision,event_kind,"
                        "effective_at_utc,target_event_id,correction_action,reason_code,recorded_at_utc,command_id) "
                        "VALUES (?,?,?,'source_terminal_consequence',NULL,NULL,NULL,?,?,?)",
                        (
                            execution_event_id,
                            canonical_task_id,
                            resulting_execution_revision,
                            reason,
                            now,
                            command_id,
                        ),
                    )
                    self._advance_termination_projection(
                        inner,
                        task_id=canonical_task_id,
                        authority=execution,
                        execution_event_id=execution_event_id,
                        reason=reason,
                    )
                    self._tasks.increment_revision(
                        inner,
                        task_id=canonical_task_id,
                        expected_revision=task.revision,
                    )

                updated = inner.connection.execute(
                    "UPDATE wfm_source_terminal_reviews SET state=?,local_consequence_event_id=?,"
                    "revision=revision+1,decided_at_utc=?,last_command_id=? "
                    "WHERE source_terminal_review_id=? AND task_id=? AND state='pending' AND revision=?",
                    (
                        accepted_decision,
                        execution_event_id,
                        now,
                        command_id,
                        canonical_review_id,
                        canonical_task_id,
                        review.revision,
                    ),
                )
                if updated.rowcount != 1:
                    raise SomaError("WFM_SOURCE_TERMINAL_STALE", "WFM source-terminal review changed during decision")

                if execution_event_id is not None:
                    membership = self._objectives.current_membership_for_task(
                        inner.connection,
                        canonical_task_id,
                    )
                    if membership is not None:
                        self._objectives.rebuild_aggregate(
                            inner,
                            objective_id=membership.objective_id,
                            command_id=command_id,
                        )

                refs = [AuditResultRef("wfm_source_terminal_review", canonical_review_id)]
                if execution_event_id is not None:
                    refs.append(AuditResultRef("task_execution_event", execution_event_id))
                return AuditEventInput(
                    audit_event_id=audit_event_id,
                    action_type="task.source_terminal_consequence_resolved",
                    action_version=1,
                    actor_kind=actor_kind,
                    actor_id=actor_id,
                    target_type="task",
                    target_id=canonical_task_id,
                    reason_category=reason,
                    command_id=command_id,
                    payload_schema="TaskSourceTerminalAuditV1",
                    payload_version=1,
                    payload={
                        "task_id": canonical_task_id,
                        "review_id": canonical_review_id,
                        "source_projection_revision": expected_source_revision,
                        "source_evidence_id": source.accepted_source_observation_id,
                        "review_fingerprint": reviewed_fingerprint,
                        "accepted_local_consequence": accepted_decision,
                        "execution_event_id": execution_event_id,
                        "reason_category": reason,
                    },
                    resulting_event_refs=tuple(refs),
                )

            return PreparedMutation(
                False,
                "wfm_source_terminal_review",
                canonical_review_id,
                apply,
                response_schema="TaskMutationResultV1",
                response_version=1,
                response={
                    "outcome": "APPLIED",
                    "task_id": canonical_task_id,
                    "revision": resulting_task_revision,
                    "result_refs": result_refs,
                },
            )

        return task_mutation_result_from_execution(self._boundary.execute(envelope, prepare))
