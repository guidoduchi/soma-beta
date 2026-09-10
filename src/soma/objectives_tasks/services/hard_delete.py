from __future__ import annotations

import re

from soma.foundation.application.command_boundary import CommandBoundary, CommandEnvelope, PreparedMutation
from soma.foundation.audit.writer import AuditEventInput, AuditResultRef, AuditWriter
from soma.foundation.errors import IntegrityFailure, SomaError, ValidationError
from soma.foundation.identifiers import new_uuid4, require_uuid4, utc_epoch_seconds
from soma.foundation.persistence.connections import ConnectionFactory
from soma.foundation.persistence.uow import UnitOfWork

from ..audit_registry import build_objectives_tasks_audit_registry
from ..contracts.objectives_tasks import TaskMutationResult, task_mutation_result_from_execution
from ..queries.hard_delete import InventoryTaskDependencyProvider, TaskHardDeletePreview, TaskHardDeleteQueryService
from ..repositories.tasks import WfmTaskRepository

_SHA256_RE = re.compile(r"[0-9a-f]{64}\Z")


def _validate_confirmation_context(value: str | None) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise ValidationError("confirmation_context_id must be text or null")
    try:
        encoded = value.encode("utf-8", errors="strict")
    except UnicodeEncodeError as exc:
        raise ValidationError("confirmation_context_id must be valid Unicode") from exc
    if not encoded or len(encoded) > 1024 or "\x00" in value or "\r" in value or "\n" in value:
        raise ValidationError("confirmation_context_id violates its bounded one-line contract")
    return value


def _validate_fingerprint(value: str) -> str:
    if not isinstance(value, str) or _SHA256_RE.fullmatch(value) is None:
        raise ValidationError("eligibility_fingerprint must be lowercase SHA-256 hex")
    return value


class TaskHardDeleteService:
    """Delete only an exact reviewed draft Task while retaining immutable deletion evidence."""

    def __init__(
        self,
        connection_factory: ConnectionFactory,
        inventory_dependency_provider: InventoryTaskDependencyProvider,
    ) -> None:
        self._queries = TaskHardDeleteQueryService(connection_factory, inventory_dependency_provider)
        self._boundary = CommandBoundary(
            connection_factory,
            AuditWriter(build_objectives_tasks_audit_registry()),
        )

    @staticmethod
    def _require_deletable_preview(preview: TaskHardDeletePreview) -> None:
        if preview.status == "INDETERMINATE":
            raise SomaError("HARD_DELETE_INDETERMINATE", "Task hard-delete authority is incomplete")
        if preview.status != "ELIGIBLE":
            raise SomaError("HARD_DELETE_BLOCKED", "Task hard deletion is blocked by current evidence")

    @staticmethod
    def _delete_exact_rows(inner: UnitOfWork, preview: TaskHardDeletePreview) -> None:
        task_id = preview.task_id
        draft = preview.draft_rows
        if draft.plan_revision_id is not None:
            current = inner.connection.execute(
                "DELETE FROM task_plan_current WHERE task_id=? AND plan_revision_id=?",
                (task_id, draft.plan_revision_id),
            )
            if current.rowcount != 1:
                raise IntegrityFailure("Task hard-delete current plan changed after revalidation")
            plan = inner.connection.execute(
                "DELETE FROM task_plan_revisions WHERE task_id=? AND plan_revision_id=?",
                (task_id, draft.plan_revision_id),
            )
            if plan.rowcount != 1:
                raise IntegrityFailure("Task hard-delete plan revision changed after revalidation")

        if draft.lock_projection_present:
            lock = inner.connection.execute(
                "DELETE FROM task_lock_projection WHERE task_id=?",
                (task_id,),
            )
            if lock.rowcount != 1:
                raise IntegrityFailure("Task hard-delete draft lock projection changed after revalidation")

        for table, id_column, row_ids in (
            ("task_sr_links", "link_id", draft.sr_link_ids),
            ("task_rfc_links", "link_id", draft.rfc_link_ids),
            ("task_device_links", "link_id", draft.device_link_ids),
        ):
            for row_id in row_ids:
                deleted = inner.connection.execute(
                    f"DELETE FROM {table} WHERE task_id=? AND {id_column}=?",
                    (task_id, row_id),
                )
                if deleted.rowcount != 1:
                    raise IntegrityFailure("Task hard-delete draft relationship changed after revalidation")

        if preview.task_kind == "wfm":
            if preview.task_no is None or draft.wfm_assignment_event_id is None:
                raise IntegrityFailure("eligible WFM hard-delete preview lost its identity authority")
            assignment = inner.connection.execute(
                "DELETE FROM wfm_rfc_assignment_events WHERE task_id=? AND assignment_event_id=?",
                (task_id, draft.wfm_assignment_event_id),
            )
            if assignment.rowcount != 1:
                raise IntegrityFailure("WFM hard-delete baseline assignment changed after revalidation")
            identity = inner.connection.execute(
                "DELETE FROM wfm_task_identities WHERE task_id=? AND task_no=?",
                (task_id, preview.task_no),
            )
            if identity.rowcount != 1:
                raise IntegrityFailure("WFM hard-delete identity changed after revalidation")

        task = inner.connection.execute(
            "DELETE FROM tasks WHERE task_id=? AND revision=?",
            (task_id, preview.task_revision),
        )
        if task.rowcount != 1:
            raise IntegrityFailure("Task disappeared before its reviewed deletion")

    def hard_delete(
        self,
        *,
        command_id: str,
        task_id: str,
        base_revision: int,
        eligibility_fingerprint: str,
        confirmation_context_id: str | None,
        actor_kind: str = "local_user",
        actor_id: str | None = None,
    ) -> TaskMutationResult:
        canonical_task_id = require_uuid4(task_id)
        if type(base_revision) is not int or base_revision <= 0:
            raise ValidationError("base_revision must be a positive integer")
        fingerprint = _validate_fingerprint(eligibility_fingerprint)
        confirmation = _validate_confirmation_context(confirmation_context_id)
        envelope = CommandEnvelope(
            command_id=command_id,
            command_type="HardDeleteTask",
            target_type="task",
            target_id=canonical_task_id,
            semantic_payload={"confirmation_context_id": confirmation},
            base_revisions={"task": base_revision},
            authorizing_fingerprints={"eligibility_fingerprint": fingerprint},
        )

        def prepare(uow: UnitOfWork) -> PreparedMutation:
            task = self._queries.load_task(uow, canonical_task_id)
            if task.revision != base_revision:
                raise SomaError("TASK_STALE", "Task revision changed since hard-delete preview")
            preview = self._queries.evaluate(uow, task=task)
            self._require_deletable_preview(preview)
            if preview.eligibility_fingerprint != fingerprint:
                raise SomaError("TASK_STALE", "Task hard-delete eligibility changed since preview")

            evidence_id = new_uuid4()
            retirement_id = new_uuid4() if preview.task_kind == "wfm" else None
            retired_at_utc = utc_epoch_seconds()

            def apply(inner: UnitOfWork) -> AuditEventInput:
                retained_related_ids: list[str] = []
                if preview.task_kind == "wfm":
                    if preview.task_no is None or retirement_id is None:
                        raise IntegrityFailure("eligible WFM hard-delete preview lacks retirement identity")
                    WfmTaskRepository.retire_task_no(
                        inner,
                        retirement_id=retirement_id,
                        task_no=preview.task_no,
                        task_id=preview.task_id,
                        retired_at_utc=retired_at_utc,
                        hard_delete_command_id=command_id,
                    )
                    retained_related_ids.append(retirement_id)
                return AuditEventInput(
                    audit_event_id=evidence_id,
                    action_type="task.hard_deleted",
                    action_version=1,
                    actor_kind=actor_kind,
                    actor_id=actor_id,
                    target_type="task",
                    target_id=preview.task_id,
                    command_id=command_id,
                    payload_schema="HardDeleteAuditV1",
                    payload_version=1,
                    payload={
                        "target_type": "task",
                        "target_id": preview.task_id,
                        "reviewed_revision": preview.task_revision,
                        "eligibility_fingerprint": fingerprint,
                        "confirmation_context_id": confirmation,
                        "retained_related_ids": retained_related_ids,
                        "result": "deleted",
                    },
                    resulting_event_refs=(AuditResultRef("hard_delete_evidence", evidence_id),),
                )

            def delete_after_audit(inner: UnitOfWork) -> None:
                self._delete_exact_rows(inner, preview)

            return PreparedMutation(
                False,
                "hard_delete_evidence",
                evidence_id,
                apply,
                response_schema="TaskMutationResultV1",
                response_version=1,
                response={
                    "outcome": "APPLIED",
                    "task_id": preview.task_id,
                    "revision": preview.task_revision,
                    "result_refs": [{"type": "hard_delete_evidence", "id": evidence_id}],
                },
                after_audit=delete_after_audit,
            )

        return task_mutation_result_from_execution(self._boundary.execute(envelope, prepare))
