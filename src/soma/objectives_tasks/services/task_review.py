from __future__ import annotations

import re

from soma.foundation.application.command_boundary import CommandBoundary, CommandEnvelope, PreparedMutation
from soma.foundation.audit.registry import AuditActionContract, AuditRegistry
from soma.foundation.audit.writer import AuditEventInput, AuditResultRef, AuditWriter
from soma.foundation.errors import SomaError, ValidationError
from soma.foundation.identifiers import new_uuid4, require_uuid4, utc_epoch_seconds
from soma.foundation.persistence.connections import ConnectionFactory
from soma.foundation.persistence.uow import UnitOfWork
from soma.foundation.strict_json import ObjectContract

from ..audit_registry import build_objectives_tasks_audit_registry
from ..contracts.objectives_tasks import TaskMutationResult, task_mutation_result_from_execution
from ..queries.execution_review import (
    TaskOutcomeCorrectionQueryService,
    TaskOutcomeReviewQueryService,
)
from ..repositories.objectives import ObjectiveProjectionRepository
from ..repositories.tasks import TaskRepository

_OUTCOMES = frozenset({"completed", "incomplete", "cancelled_without_execution"})
_SHA256_RE = re.compile(r"[0-9a-f]{64}\Z")
_MAX_REASON_UTF8_BYTES = 128
_OUTCOME_AUDIT_FIELDS = frozenset(
    {
        "task_id",
        "outcome_event_id",
        "accepted_outcome",
        "correction_of_event_id",
        "resulting_outcome_revision",
        "review_fingerprint",
        "reason_category",
    }
)


def _require_positive_revision(value: int, *, label: str) -> int:
    if type(value) is not int or value <= 0:
        raise ValidationError(f"{label} must be a positive integer")
    return value


def _require_nonnegative_revision(value: int, *, label: str) -> int:
    if type(value) is not int or value < 0:
        raise ValidationError(f"{label} must be a nonnegative integer")
    return value


def _normalize_reason(value: str | None) -> str | None:
    if value is None:
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


def _validate_fingerprint(value: str, *, label: str) -> str:
    if not isinstance(value, str) or _SHA256_RE.fullmatch(value) is None:
        raise ValidationError(f"{label} must be lowercase SHA-256 hex")
    return value


def _validate_outcome(value: str, *, label: str) -> str:
    if value not in _OUTCOMES:
        raise ValidationError(
            f"{label} must be completed, incomplete, or cancelled_without_execution"
        )
    return value


def _validate_outcome_audit(payload: dict[str, object]) -> None:
    try:
        task_id = payload.get("task_id")
        event_id = payload.get("outcome_event_id")
        correction_of = payload.get("correction_of_event_id")
        if not isinstance(task_id, str) or not isinstance(event_id, str):
            raise ValidationError("Task outcome audit identities must be UUID text")
        require_uuid4(task_id)
        require_uuid4(event_id)
        if correction_of is not None:
            if not isinstance(correction_of, str):
                raise ValidationError("Task outcome correction identity must be UUID text or null")
            require_uuid4(correction_of)
    except ValidationError as exc:
        raise SomaError("AUDIT_PAYLOAD_INVALID", "Task outcome audit identity is invalid") from exc

    if payload.get("accepted_outcome") not in _OUTCOMES:
        raise SomaError("AUDIT_PAYLOAD_INVALID", "Task outcome audit token is invalid")
    revision = payload.get("resulting_outcome_revision")
    if type(revision) is not int or revision <= 0:
        raise SomaError("AUDIT_PAYLOAD_INVALID", "Task outcome audit revision is invalid")
    fingerprint = payload.get("review_fingerprint")
    if not isinstance(fingerprint, str) or _SHA256_RE.fullmatch(fingerprint) is None:
        raise SomaError("AUDIT_PAYLOAD_INVALID", "Task outcome audit fingerprint is invalid")
    reason = payload.get("reason_category")
    if reason is not None:
        try:
            _normalize_reason(reason)
        except ValidationError as exc:
            raise SomaError("AUDIT_PAYLOAD_INVALID", "Task outcome audit reason is invalid") from exc


def _build_task_review_audit_registry() -> AuditRegistry:
    registry = build_objectives_tasks_audit_registry()
    registry.register(
        AuditActionContract(
            action_type="task.outcome_reviewed",
            action_version=1,
            payload_schema="TaskOutcomeAuditV1",
            payload_version=1,
            payload_contract=ObjectContract(
                name="TaskOutcomeAuditV1",
                version=1,
                required_fields=_OUTCOME_AUDIT_FIELDS,
                allowed_fields=_OUTCOME_AUDIT_FIELDS,
                max_depth=3,
                max_collection_items=8,
                max_utf8_bytes=16_384,
            ),
            sensitivity_validator=_validate_outcome_audit,
        )
    )
    return registry


class TaskReviewService:
    """LLD-05 reviewed Task outcome owner."""

    def __init__(self, connection_factory: ConnectionFactory) -> None:
        self._tasks = TaskRepository()
        self._objectives = ObjectiveProjectionRepository()
        self._outcome_reviews = TaskOutcomeReviewQueryService(connection_factory)
        self._outcome_corrections = TaskOutcomeCorrectionQueryService(connection_factory)
        self._boundary = CommandBoundary(
            connection_factory,
            AuditWriter(_build_task_review_audit_registry()),
        )

    @staticmethod
    def _rebuild_objective_if_member(
        uow: UnitOfWork,
        *,
        task_id: str,
        command_id: str,
    ) -> None:
        membership = ObjectiveProjectionRepository.current_membership_for_task(
            uow.connection, task_id
        )
        if membership is not None:
            ObjectiveProjectionRepository.rebuild_aggregate(
                uow,
                objective_id=membership.objective_id,
                command_id=command_id,
            )

    def review_task_outcome(
        self,
        *,
        command_id: str,
        task_id: str,
        task_revision: int,
        execution_revision: int,
        outcome_revision: int,
        current_outcome_event_id: str | None,
        outcome: str,
        reason_category: str | None,
        outcome_review_fingerprint: str,
        actor_kind: str = "local_user",
        actor_id: str | None = None,
    ) -> TaskMutationResult:
        canonical_task_id = require_uuid4(task_id)
        expected_task_revision = _require_positive_revision(task_revision, label="task_revision")
        expected_execution_revision = _require_positive_revision(
            execution_revision, label="execution_revision"
        )
        expected_outcome_revision = _require_nonnegative_revision(
            outcome_revision, label="outcome_revision"
        )
        if expected_outcome_revision == 0:
            if current_outcome_event_id is not None:
                raise ValidationError(
                    "current_outcome_event_id must be null when outcome_revision is zero"
                )
            canonical_current_event_id = None
        else:
            if not isinstance(current_outcome_event_id, str):
                raise ValidationError(
                    "current_outcome_event_id is required for positive outcome_revision"
                )
            canonical_current_event_id = require_uuid4(current_outcome_event_id)
        requested_outcome = _validate_outcome(outcome, label="outcome")
        normalized_reason = _normalize_reason(reason_category)
        fingerprint = _validate_fingerprint(
            outcome_review_fingerprint, label="outcome_review_fingerprint"
        )

        envelope = CommandEnvelope(
            command_id=command_id,
            command_type="ReviewTaskOutcome",
            target_type="task",
            target_id=canonical_task_id,
            semantic_payload={
                "execution_revision": expected_execution_revision,
                "outcome_revision": expected_outcome_revision,
                "current_outcome_event_id": canonical_current_event_id,
                "outcome": requested_outcome,
                "reason_category": normalized_reason,
            },
            base_revisions={canonical_task_id: expected_task_revision},
            authorizing_fingerprints={"outcome_review_fingerprint": fingerprint},
        )

        def prepare(uow: UnitOfWork) -> PreparedMutation:
            try:
                preview = self._outcome_reviews.evaluate_connection(
                    uow.connection,
                    task_id=canonical_task_id,
                    task_revision=expected_task_revision,
                    execution_revision=expected_execution_revision,
                    outcome_revision=expected_outcome_revision,
                    current_outcome_event_id=canonical_current_event_id,
                    outcome=requested_outcome,
                    reason_category=normalized_reason,
                )
            except SomaError as exc:
                if exc.code == "TASK_STALE":
                    raise SomaError(
                        "TASK_REVIEW_STALE",
                        "Task outcome review authority changed after preview",
                    ) from exc
                raise

            if preview.outcome_review_fingerprint != fingerprint:
                raise SomaError(
                    "TASK_REVIEW_STALE",
                    "Task outcome review fingerprint changed after preview",
                )
            if "CURRENT_OUTCOME_REQUIRES_CORRECTION" in preview.blockers:
                raise SomaError(
                    "TASK_REVIEW_STALE",
                    "Current reviewed outcome requires CorrectTaskOutcome",
                )
            if preview.blockers:
                raise SomaError(
                    "TASK_OUTCOME_INVALID_FOR_EXECUTION",
                    "Requested Task outcome is not eligible under current execution authority",
                )

            task = self._tasks.get(uow.connection, canonical_task_id)
            if task is None or task.revision != expected_task_revision:
                raise SomaError(
                    "TASK_REVIEW_STALE",
                    "Task outcome review authority changed during writer revalidation",
                )
            if preview.semantic_no_change:
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
            if expected_outcome_revision != 0 or preview.current_outcome_revision != 0:
                raise SomaError(
                    "TASK_REVIEW_STALE",
                    "First Task outcome review no longer targets exact outcome absence",
                )

            outcome_event_id = new_uuid4()
            audit_event_id = new_uuid4()
            reviewed_at = utc_epoch_seconds()
            resulting_task_revision = task.revision + 1

            def apply(inner: UnitOfWork) -> AuditEventInput:
                inner.connection.execute(
                    "INSERT INTO task_outcome_events(outcome_event_id,task_id,accepted_outcome,"
                    "correction_of_event_id,reason_code,reviewed_at_utc,command_id) "
                    "VALUES (?,?,?,NULL,?,?,?)",
                    (
                        outcome_event_id,
                        canonical_task_id,
                        requested_outcome,
                        normalized_reason,
                        reviewed_at,
                        command_id,
                    ),
                )
                inner.connection.execute(
                    "INSERT INTO task_outcome_current(task_id,outcome_event_id,accepted_outcome,"
                    "reviewed_at_utc,revision,last_command_id) VALUES (?,?,?,?,1,?)",
                    (
                        canonical_task_id,
                        outcome_event_id,
                        requested_outcome,
                        reviewed_at,
                        command_id,
                    ),
                )
                self._tasks.increment_revision(
                    inner,
                    task_id=canonical_task_id,
                    expected_revision=expected_task_revision,
                )
                self._rebuild_objective_if_member(
                    inner,
                    task_id=canonical_task_id,
                    command_id=command_id,
                )
                return AuditEventInput(
                    audit_event_id=audit_event_id,
                    action_type="task.outcome_reviewed",
                    action_version=1,
                    actor_kind=actor_kind,
                    actor_id=actor_id,
                    target_type="task",
                    target_id=canonical_task_id,
                    reason_category=normalized_reason,
                    command_id=command_id,
                    payload_schema="TaskOutcomeAuditV1",
                    payload_version=1,
                    payload={
                        "task_id": canonical_task_id,
                        "outcome_event_id": outcome_event_id,
                        "accepted_outcome": requested_outcome,
                        "correction_of_event_id": None,
                        "resulting_outcome_revision": 1,
                        "review_fingerprint": fingerprint,
                        "reason_category": normalized_reason,
                    },
                    resulting_event_refs=(
                        AuditResultRef("task_outcome_event", outcome_event_id),
                    ),
                )

            return PreparedMutation(
                False,
                "task_outcome_event",
                outcome_event_id,
                apply,
                response_schema="TaskMutationResultV1",
                response_version=1,
                response={
                    "outcome": "APPLIED",
                    "task_id": canonical_task_id,
                    "revision": resulting_task_revision,
                    "result_refs": [
                        {"type": "task_outcome_event", "id": outcome_event_id}
                    ],
                },
            )

        return task_mutation_result_from_execution(self._boundary.execute(envelope, prepare))

    def correct_task_outcome(
        self,
        *,
        command_id: str,
        task_id: str,
        task_revision: int,
        execution_revision: int,
        current_outcome_revision: int,
        current_outcome_event_id: str,
        replacement_outcome: str,
        reason_category: str | None,
        correction_review_fingerprint: str,
        actor_kind: str = "local_user",
        actor_id: str | None = None,
    ) -> TaskMutationResult:
        canonical_task_id = require_uuid4(task_id)
        expected_task_revision = _require_positive_revision(task_revision, label="task_revision")
        expected_execution_revision = _require_positive_revision(
            execution_revision, label="execution_revision"
        )
        expected_outcome_revision = _require_positive_revision(
            current_outcome_revision, label="current_outcome_revision"
        )
        canonical_current_event_id = require_uuid4(current_outcome_event_id)
        requested_outcome = _validate_outcome(
            replacement_outcome, label="replacement_outcome"
        )
        normalized_reason = _normalize_reason(reason_category)
        fingerprint = _validate_fingerprint(
            correction_review_fingerprint, label="correction_review_fingerprint"
        )

        envelope = CommandEnvelope(
            command_id=command_id,
            command_type="CorrectTaskOutcome",
            target_type="task",
            target_id=canonical_task_id,
            semantic_payload={
                "execution_revision": expected_execution_revision,
                "current_outcome_revision": expected_outcome_revision,
                "current_outcome_event_id": canonical_current_event_id,
                "replacement_outcome": requested_outcome,
                "reason_category": normalized_reason,
            },
            base_revisions={canonical_task_id: expected_task_revision},
            authorizing_fingerprints={"correction_review_fingerprint": fingerprint},
        )

        def prepare(uow: UnitOfWork) -> PreparedMutation:
            try:
                preview = self._outcome_corrections.evaluate_connection(
                    uow.connection,
                    task_id=canonical_task_id,
                    task_revision=expected_task_revision,
                    execution_revision=expected_execution_revision,
                    current_outcome_revision=expected_outcome_revision,
                    current_outcome_event_id=canonical_current_event_id,
                    replacement_outcome=requested_outcome,
                    reason_category=normalized_reason,
                )
            except SomaError as exc:
                if exc.code == "TASK_STALE":
                    raise SomaError(
                        "TASK_REVIEW_STALE",
                        "Task outcome correction authority changed after preview",
                    ) from exc
                raise

            if preview.correction_review_fingerprint != fingerprint:
                raise SomaError(
                    "TASK_REVIEW_STALE",
                    "Task outcome correction fingerprint changed after preview",
                )
            if preview.blockers:
                raise SomaError(
                    "TASK_OUTCOME_INVALID_FOR_EXECUTION",
                    "Replacement Task outcome is not eligible under current execution authority",
                )

            task = self._tasks.get(uow.connection, canonical_task_id)
            if task is None or task.revision != expected_task_revision:
                raise SomaError(
                    "TASK_REVIEW_STALE",
                    "Task outcome correction authority changed during writer revalidation",
                )
            if preview.semantic_no_change:
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

            outcome_event_id = new_uuid4()
            audit_event_id = new_uuid4()
            reviewed_at = utc_epoch_seconds()
            resulting_task_revision = task.revision + 1
            resulting_outcome_revision = expected_outcome_revision + 1

            def apply(inner: UnitOfWork) -> AuditEventInput:
                inner.connection.execute(
                    "INSERT INTO task_outcome_events(outcome_event_id,task_id,accepted_outcome,"
                    "correction_of_event_id,reason_code,reviewed_at_utc,command_id) "
                    "VALUES (?,?,?,?,?,?,?)",
                    (
                        outcome_event_id,
                        canonical_task_id,
                        requested_outcome,
                        canonical_current_event_id,
                        normalized_reason,
                        reviewed_at,
                        command_id,
                    ),
                )
                updated = inner.connection.execute(
                    "UPDATE task_outcome_current SET outcome_event_id=?,accepted_outcome=?,"
                    "reviewed_at_utc=?,revision=revision+1,last_command_id=? "
                    "WHERE task_id=? AND revision=? AND outcome_event_id=?",
                    (
                        outcome_event_id,
                        requested_outcome,
                        reviewed_at,
                        command_id,
                        canonical_task_id,
                        expected_outcome_revision,
                        canonical_current_event_id,
                    ),
                )
                if updated.rowcount != 1:
                    raise SomaError(
                        "TASK_REVIEW_STALE",
                        "Task outcome current tip changed during guarded correction",
                    )
                self._tasks.increment_revision(
                    inner,
                    task_id=canonical_task_id,
                    expected_revision=expected_task_revision,
                )
                self._rebuild_objective_if_member(
                    inner,
                    task_id=canonical_task_id,
                    command_id=command_id,
                )
                return AuditEventInput(
                    audit_event_id=audit_event_id,
                    action_type="task.outcome_reviewed",
                    action_version=1,
                    actor_kind=actor_kind,
                    actor_id=actor_id,
                    target_type="task",
                    target_id=canonical_task_id,
                    reason_category=normalized_reason,
                    command_id=command_id,
                    payload_schema="TaskOutcomeAuditV1",
                    payload_version=1,
                    payload={
                        "task_id": canonical_task_id,
                        "outcome_event_id": outcome_event_id,
                        "accepted_outcome": requested_outcome,
                        "correction_of_event_id": canonical_current_event_id,
                        "resulting_outcome_revision": resulting_outcome_revision,
                        "review_fingerprint": fingerprint,
                        "reason_category": normalized_reason,
                    },
                    resulting_event_refs=(
                        AuditResultRef("task_outcome_event", outcome_event_id),
                    ),
                )

            return PreparedMutation(
                False,
                "task_outcome_event",
                outcome_event_id,
                apply,
                response_schema="TaskMutationResultV1",
                response_version=1,
                response={
                    "outcome": "APPLIED",
                    "task_id": canonical_task_id,
                    "revision": resulting_task_revision,
                    "result_refs": [
                        {"type": "task_outcome_event", "id": outcome_event_id}
                    ],
                },
            )

        return task_mutation_result_from_execution(self._boundary.execute(envelope, prepare))
