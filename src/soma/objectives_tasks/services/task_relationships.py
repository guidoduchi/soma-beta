from __future__ import annotations

from typing import Any

from soma.foundation.application.command_boundary import CommandBoundary, CommandEnvelope, PreparedMutation
from soma.foundation.audit.registry import AuditActionContract
from soma.foundation.audit.writer import AuditEventInput, AuditResultRef, AuditWriter
from soma.foundation.errors import IntegrityFailure, SomaError, ValidationError
from soma.foundation.identifiers import new_uuid4, require_uuid4
from soma.foundation.persistence.connections import ConnectionFactory
from soma.foundation.persistence.uow import UnitOfWork
from soma.foundation.strict_json import ObjectContract

from ..audit_registry import build_objectives_tasks_audit_registry
from ..contracts.objectives_tasks import TaskMutationResult, task_mutation_result_from_execution
from ..repositories.tasks import TaskRelationshipRecord, TaskRelationshipRepository, TaskRepository
from .task_planning import validate_task_reason_category

_RELATIONSHIP_TARGETS = {
    "sr": ("task_sr_links", "service_request_id", "service_requests", "service_request_id"),
    "rfc": ("task_rfc_links", "rfc_id", "rfcs", "rfc_id"),
    "device": ("task_device_links", "device_reference_id", "device_references", "device_reference_id"),
}
_RELATIONSHIP_AUDIT_FIELDS = frozenset(
    {
        "task_id",
        "relationship_kind",
        "action",
        "relationship_id",
        "related_id",
        "prior_related_id",
        "resulting_revision",
        "reason_category",
    }
)


def _require_positive_revision(value: int) -> int:
    if type(value) is not int or value <= 0:
        raise ValidationError("task_revision must be a positive integer")
    return value


def _require_relationship_kind(value: str) -> str:
    if value not in _RELATIONSHIP_TARGETS:
        raise ValidationError("relationship_kind must be sr, rfc, or device")
    return value


def _require_action(value: str) -> str:
    if value not in {"link", "unlink"}:
        raise ValidationError("action must be link or unlink")
    return value


def _validate_relationship_audit(payload: dict[str, object]) -> None:
    try:
        for field in ("task_id", "relationship_id", "related_id"):
            value = payload.get(field)
            if not isinstance(value, str):
                raise ValidationError(f"{field} must be UUID text")
            require_uuid4(value)
    except ValidationError as exc:
        raise SomaError("AUDIT_PAYLOAD_INVALID", "Task relationship audit identity is invalid") from exc

    if payload.get("relationship_kind") not in _RELATIONSHIP_TARGETS:
        raise SomaError("AUDIT_PAYLOAD_INVALID", "Task relationship audit kind is invalid")
    action = payload.get("action")
    if action not in {"OPEN", "CLOSE"}:
        raise SomaError("AUDIT_PAYLOAD_INVALID", "Task relationship audit action is invalid")
    if payload.get("prior_related_id") is not None:
        raise SomaError("AUDIT_PAYLOAD_INVALID", "Direct Task relationship prior target must be null")
    revision = payload.get("resulting_revision")
    if type(revision) is not int or revision <= 1:
        raise SomaError("AUDIT_PAYLOAD_INVALID", "Task relationship audit revision is invalid")
    reason = payload.get("reason_category")
    if action == "OPEN":
        if reason is not None:
            raise SomaError("AUDIT_PAYLOAD_INVALID", "Task relationship OPEN reason must be null")
    else:
        if not isinstance(reason, str):
            raise SomaError("AUDIT_PAYLOAD_INVALID", "Task relationship CLOSE reason must be text")
        try:
            encoded = reason.encode("utf-8", errors="strict")
        except UnicodeEncodeError as exc:
            raise SomaError("AUDIT_PAYLOAD_INVALID", "Task relationship CLOSE reason is invalid Unicode") from exc
        if not encoded or len(encoded) > 128 or "\x00" in reason or "\r" in reason or "\n" in reason:
            raise SomaError("AUDIT_PAYLOAD_INVALID", "Task relationship CLOSE reason violates its bound")


def _build_relationship_audit_registry():
    registry = build_objectives_tasks_audit_registry()
    registry.register(
        AuditActionContract(
            action_type="task.relationship_changed",
            action_version=1,
            payload_schema="TaskRelationshipAuditV1",
            payload_version=1,
            payload_contract=ObjectContract(
                name="TaskRelationshipAuditV1",
                version=1,
                required_fields=_RELATIONSHIP_AUDIT_FIELDS,
                allowed_fields=_RELATIONSHIP_AUDIT_FIELDS,
                max_depth=4,
                max_collection_items=16,
                max_utf8_bytes=16_384,
            ),
            sensitivity_validator=_validate_relationship_audit,
        )
    )
    return registry


class TaskRelationshipService:
    """LLD-05 direct Task relationship owner with append-only link history."""

    def __init__(self, connection_factory: ConnectionFactory) -> None:
        self._tasks = TaskRepository()
        self._relationships = TaskRelationshipRepository()
        self._boundary = CommandBoundary(
            connection_factory,
            AuditWriter(_build_relationship_audit_registry()),
        )

    @staticmethod
    def _require_target_exists(connection: Any, relationship_kind: str, target_id: str) -> None:
        _link_table, _link_target_column, target_table, target_id_column = _RELATIONSHIP_TARGETS[relationship_kind]
        row = connection.execute(
            f"SELECT 1 FROM {target_table} WHERE {target_id_column}=?",
            (target_id,),
        ).fetchone()
        if row is None:
            raise SomaError("TASK_RELATIONSHIP_TARGET_NOT_FOUND", "Task relationship target does not exist")

    @staticmethod
    def _active_relationship(connection: Any, *, task_id: str, relationship_kind: str, target_id: str) -> str | None:
        link_table, link_target_column, _target_table, _target_id_column = _RELATIONSHIP_TARGETS[relationship_kind]
        rows = connection.execute(
            f"SELECT link_id FROM {link_table} WHERE task_id=? AND {link_target_column}=? AND active=1 LIMIT 2",
            (task_id, target_id),
        ).fetchall()
        if len(rows) > 1:
            raise IntegrityFailure("Task relationship active-pair authority is not unique")
        return None if not rows else str(rows[0][0])

    @staticmethod
    def _close_relationship(
        uow: UnitOfWork,
        *,
        relationship_id: str,
        task_id: str,
        relationship_kind: str,
        target_id: str,
        command_id: str,
    ) -> None:
        link_table, link_target_column, _target_table, _target_id_column = _RELATIONSHIP_TARGETS[relationship_kind]
        updated = uow.connection.execute(
            f"UPDATE {link_table} SET active=0,closed_command_id=? "
            f"WHERE link_id=? AND task_id=? AND {link_target_column}=? AND active=1 AND closed_command_id IS NULL",
            (command_id, relationship_id, task_id, target_id),
        )
        if updated.rowcount != 1:
            raise IntegrityFailure("Task relationship changed during guarded close")

    def change_task_relationship(
        self,
        *,
        command_id: str,
        task_id: str,
        task_revision: int,
        relationship_kind: str,
        target_id: str,
        action: str,
        reason_category: str | None = None,
        actor_kind: str = "local_user",
        actor_id: str | None = None,
    ) -> TaskMutationResult:
        canonical_task_id = require_uuid4(task_id)
        expected_task_revision = _require_positive_revision(task_revision)
        selected_kind = _require_relationship_kind(relationship_kind)
        canonical_target_id = require_uuid4(target_id)
        selected_action = _require_action(action)
        if selected_action == "unlink":
            if reason_category is None:
                raise ValidationError("reason_category is required for unlink")
            reason = validate_task_reason_category(reason_category)
        else:
            if reason_category is not None:
                raise ValidationError("reason_category must be absent for link")
            reason = None

        envelope = CommandEnvelope(
            command_id=command_id,
            command_type="ChangeTaskRelationship",
            target_type="task",
            target_id=canonical_task_id,
            semantic_payload={
                "relationship_kind": selected_kind,
                "target_id": canonical_target_id,
                "action": selected_action,
                "reason_category": reason,
            },
            base_revisions={canonical_task_id: expected_task_revision},
        )

        def prepare(uow: UnitOfWork) -> PreparedMutation:
            task = self._tasks.get(uow.connection, canonical_task_id)
            if task is None:
                raise SomaError("TASK_NOT_FOUND", "Task does not exist")
            if task.revision != expected_task_revision:
                raise SomaError("TASK_STALE", "Task revision changed")
            if task.task_kind not in {"local", "wfm"}:
                raise IntegrityFailure("Task kind authority is invalid")

            self._require_target_exists(uow.connection, selected_kind, canonical_target_id)
            if task.task_kind == "wfm" and selected_kind in {"sr", "rfc"}:
                raise SomaError(
                    "TASK_RELATIONSHIP_INVALID",
                    "WFM SR/RFC context derives through the owning RFC",
                )

            active_relationship_id = self._active_relationship(
                uow.connection,
                task_id=canonical_task_id,
                relationship_kind=selected_kind,
                target_id=canonical_target_id,
            )
            wants_link = selected_action == "link"
            if (wants_link and active_relationship_id is not None) or (
                not wants_link and active_relationship_id is None
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

            relationship_id = new_uuid4() if wants_link else active_relationship_id
            if relationship_id is None:
                raise IntegrityFailure("Material unlink lost its active relationship identity")
            audit_event_id = new_uuid4()
            resulting_revision = task.revision + 1
            audit_action = "OPEN" if wants_link else "CLOSE"

            def apply(inner: UnitOfWork) -> AuditEventInput:
                if wants_link:
                    self._relationships.link(
                        inner,
                        TaskRelationshipRecord(
                            relationship_id=relationship_id,
                            task_id=canonical_task_id,
                            relationship_kind=selected_kind,
                            related_id=canonical_target_id,
                            opened_command_id=command_id,
                        ),
                    )
                else:
                    self._close_relationship(
                        inner,
                        relationship_id=relationship_id,
                        task_id=canonical_task_id,
                        relationship_kind=selected_kind,
                        target_id=canonical_target_id,
                        command_id=command_id,
                    )

                self._tasks.increment_revision(
                    inner,
                    task_id=canonical_task_id,
                    expected_revision=expected_task_revision,
                )
                return AuditEventInput(
                    audit_event_id=audit_event_id,
                    action_type="task.relationship_changed",
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
                        "relationship_kind": selected_kind,
                        "action": audit_action,
                        "relationship_id": relationship_id,
                        "related_id": canonical_target_id,
                        "prior_related_id": None,
                        "resulting_revision": resulting_revision,
                        "reason_category": reason,
                    },
                    resulting_event_refs=(AuditResultRef("task_relationship", relationship_id),),
                )

            return PreparedMutation(
                False,
                "task_relationship",
                relationship_id,
                apply,
                response_schema="TaskMutationResultV1",
                response_version=1,
                response={
                    "outcome": "APPLIED",
                    "task_id": canonical_task_id,
                    "revision": resulting_revision,
                    "result_refs": [{"type": "task_relationship", "id": relationship_id}],
                },
            )

        return task_mutation_result_from_execution(self._boundary.execute(envelope, prepare))
