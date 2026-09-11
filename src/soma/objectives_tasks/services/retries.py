from __future__ import annotations

from dataclasses import dataclass

from soma.foundation.application.command_boundary import CommandBoundary, CommandEnvelope, PreparedMutation
from soma.foundation.audit.registry import AuditActionContract, AuditRegistry
from soma.foundation.audit.writer import AuditEventInput, AuditResultRef, AuditWriter
from soma.foundation.errors import IntegrityFailure, SomaError, ValidationError
from soma.foundation.identifiers import new_uuid4, require_uuid4, utc_epoch_seconds
from soma.foundation.persistence.connections import ConnectionFactory
from soma.foundation.persistence.uow import UnitOfWork
from soma.foundation.strict_json import ObjectContract

from ..audit_registry import build_objectives_tasks_audit_registry
from ..contracts.objectives_tasks import TaskMutationResult, task_mutation_result_from_execution
from ..repositories.tasks import TaskRepository, WfmTaskRepository

_RETRY_AUDIT_FIELDS = frozenset(
    {
        "predecessor_task_id",
        "successor_task_id",
        "retry_relation_id",
        "successor_kind",
        "activity_lineage_id",
        "resulting_revisions",
        "reason_category",
    }
)


def _validate_optional_reason(value: object) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise ValidationError("reason_category must be text or null")
    try:
        encoded = value.encode("utf-8", errors="strict")
    except UnicodeEncodeError as exc:
        raise ValidationError("reason_category must be valid Unicode") from exc
    if not encoded or len(encoded) > 128 or "\x00" in value or "\r" in value or "\n" in value:
        raise ValidationError("reason_category violates its bounded one-line contract")
    return value


def _validate_retry_audit_payload(payload: dict[str, object]) -> None:
    predecessor_id = payload.get("predecessor_task_id")
    successor_id = payload.get("successor_task_id")
    relation_id = payload.get("retry_relation_id")
    try:
        for value in (predecessor_id, successor_id, relation_id):
            if not isinstance(value, str):
                raise ValidationError("retry audit identities must be UUID text")
            require_uuid4(value)
    except ValidationError as exc:
        raise SomaError("AUDIT_PAYLOAD_INVALID", "Task retry audit identity is invalid") from exc
    if predecessor_id == successor_id:
        raise SomaError("AUDIT_PAYLOAD_INVALID", "Task retry audit cannot self-link")
    if payload.get("successor_kind") != "wfm":
        raise SomaError("AUDIT_PAYLOAD_INVALID", "WFM retry-link audit successor kind is invalid")
    if payload.get("activity_lineage_id") is not None:
        raise SomaError("AUDIT_PAYLOAD_INVALID", "WFM retry-link audit cannot claim activity-lineage authority")
    revisions = payload.get("resulting_revisions")
    if not isinstance(revisions, dict) or set(revisions) != {predecessor_id, successor_id}:
        raise SomaError("AUDIT_PAYLOAD_INVALID", "WFM retry-link audit revision map is invalid")
    if any(type(revision) is not int or revision <= 0 for revision in revisions.values()):
        raise SomaError("AUDIT_PAYLOAD_INVALID", "WFM retry-link audit revisions must be positive integers")
    try:
        _validate_optional_reason(payload.get("reason_category"))
    except ValidationError as exc:
        raise SomaError("AUDIT_PAYLOAD_INVALID", "WFM retry-link audit reason is invalid") from exc


def _build_retry_audit_registry() -> AuditRegistry:
    registry = build_objectives_tasks_audit_registry()
    registry.register(
        AuditActionContract(
            action_type="task.retry_created_or_linked",
            action_version=1,
            payload_schema="TaskRetryAuditV1",
            payload_version=1,
            payload_contract=ObjectContract(
                name="TaskRetryAuditV1",
                version=1,
                required_fields=_RETRY_AUDIT_FIELDS,
                allowed_fields=_RETRY_AUDIT_FIELDS,
                max_depth=4,
                max_collection_items=9,
                max_utf8_bytes=16_384,
            ),
            sensitivity_validator=_validate_retry_audit_payload,
        )
    )
    return registry


@dataclass(frozen=True, slots=True)
class _WfmRetryAuthority:
    task_id: str
    task_revision: int
    task_no: str


@dataclass(frozen=True, slots=True)
class _RetryEdge:
    retry_relation_id: str
    predecessor_task_id: str
    successor_task_id: str


class TaskRetryService:
    """LLD-05 retry-edge authority; activity classification remains separately reviewed."""

    def __init__(self, connection_factory: ConnectionFactory) -> None:
        self._tasks = TaskRepository()
        self._wfm = WfmTaskRepository()
        self._boundary = CommandBoundary(
            connection_factory,
            AuditWriter(_build_retry_audit_registry()),
        )

    def _load_wfm_authority(
        self,
        uow: UnitOfWork,
        *,
        task_id: str,
        expected_revision: int,
    ) -> _WfmRetryAuthority:
        task = self._tasks.get(uow.connection, task_id)
        identity = self._wfm.get_identity(uow.connection, task_id)
        if task is None or task.task_kind != "wfm" or identity is None:
            raise SomaError("TASK_NOT_FOUND", "retry endpoint is not a current WFM Task")
        if task.revision != expected_revision:
            raise SomaError("TASK_STALE", "retry endpoint Task revision changed")
        task_no = identity.task_no
        if (
            not isinstance(task_no, str)
            or len(task_no) != 16
            or task_no[:2] != "TK"
            or any(character < "0" or character > "9" for character in task_no[2:])
        ):
            raise IntegrityFailure("stored WFM Task No authority is invalid")
        return _WfmRetryAuthority(
            task_id=task.task_id,
            task_revision=task.revision,
            task_no=task_no,
        )

    @staticmethod
    def _edge_from_row(row: object) -> _RetryEdge | None:
        if row is None:
            return None
        try:
            relation_id = require_uuid4(str(row[0]))
            predecessor_id = require_uuid4(str(row[1]))
            successor_id = require_uuid4(str(row[2]))
        except (IndexError, TypeError, ValidationError) as exc:
            raise IntegrityFailure("stored Task retry edge is invalid") from exc
        if predecessor_id == successor_id:
            raise IntegrityFailure("stored Task retry edge self-links")
        return _RetryEdge(relation_id, predecessor_id, successor_id)

    @classmethod
    def _edge_from_predecessor(cls, uow: UnitOfWork, task_id: str) -> _RetryEdge | None:
        row = uow.connection.execute(
            "SELECT retry_relation_id,predecessor_task_id,successor_task_id "
            "FROM task_retry_relations WHERE predecessor_task_id=?",
            (task_id,),
        ).fetchone()
        return cls._edge_from_row(row)

    @classmethod
    def _edge_from_successor(cls, uow: UnitOfWork, task_id: str) -> _RetryEdge | None:
        row = uow.connection.execute(
            "SELECT retry_relation_id,predecessor_task_id,successor_task_id "
            "FROM task_retry_relations WHERE successor_task_id=?",
            (task_id,),
        ).fetchone()
        return cls._edge_from_row(row)

    @classmethod
    def _assert_no_cycle(
        cls,
        uow: UnitOfWork,
        *,
        predecessor_task_id: str,
        successor_task_id: str,
    ) -> None:
        current = successor_task_id
        seen: set[str] = set()
        while True:
            if current == predecessor_task_id:
                raise SomaError("TASK_RETRY_CYCLE", "retry relation would create a cycle")
            if current in seen:
                raise IntegrityFailure("existing Task retry chain already contains a cycle")
            seen.add(current)
            edge = cls._edge_from_predecessor(uow, current)
            if edge is None:
                return
            if edge.predecessor_task_id != current:
                raise IntegrityFailure("stored retry successor traversal is inconsistent")
            current = edge.successor_task_id

    def link_wfm_retry_attempt(
        self,
        *,
        command_id: str,
        predecessor_wfm_task_id: str,
        predecessor_task_revision: int,
        successor_wfm_task_id: str,
        successor_task_revision: int,
        reason_category: str | None = None,
        actor_kind: str = "local_user",
        actor_id: str | None = None,
    ) -> TaskMutationResult:
        predecessor_id = require_uuid4(predecessor_wfm_task_id)
        successor_id = require_uuid4(successor_wfm_task_id)
        if predecessor_id == successor_id:
            raise ValidationError("WFM retry predecessor and successor must be distinct Tasks")
        if type(predecessor_task_revision) is not int or predecessor_task_revision <= 0:
            raise ValidationError("predecessor_task_revision must be a positive integer")
        if type(successor_task_revision) is not int or successor_task_revision <= 0:
            raise ValidationError("successor_task_revision must be a positive integer")
        reason = _validate_optional_reason(reason_category)

        envelope = CommandEnvelope(
            command_id=command_id,
            command_type="LinkWfmRetryAttempt",
            target_type="task",
            target_id=predecessor_id,
            semantic_payload={
                "successor_wfm_task_id": successor_id,
                "reason_category": reason,
            },
            base_revisions={
                predecessor_id: predecessor_task_revision,
                successor_id: successor_task_revision,
            },
        )

        def prepare(uow: UnitOfWork) -> PreparedMutation:
            predecessor = self._load_wfm_authority(
                uow,
                task_id=predecessor_id,
                expected_revision=predecessor_task_revision,
            )
            successor = self._load_wfm_authority(
                uow,
                task_id=successor_id,
                expected_revision=successor_task_revision,
            )
            if predecessor.task_no == successor.task_no:
                raise IntegrityFailure("distinct WFM Tasks unexpectedly share canonical Task No authority")

            outgoing = self._edge_from_predecessor(uow, predecessor_id)
            incoming = self._edge_from_successor(uow, successor_id)
            outgoing_exact = (
                outgoing is not None
                and outgoing.predecessor_task_id == predecessor_id
                and outgoing.successor_task_id == successor_id
            )
            incoming_exact = (
                incoming is not None
                and incoming.predecessor_task_id == predecessor_id
                and incoming.successor_task_id == successor_id
            )
            if outgoing_exact or incoming_exact:
                if not (outgoing_exact and incoming_exact and outgoing == incoming):
                    raise IntegrityFailure("exact retry edge is not bidirectionally resolvable by its unique endpoints")
                return PreparedMutation(
                    True,
                    None,
                    None,
                    response_schema="TaskMutationResultV1",
                    response_version=1,
                    response={
                        "outcome": "NO_CHANGE",
                        "task_id": predecessor_id,
                        "revision": predecessor.task_revision,
                        "result_refs": [],
                    },
                )
            if outgoing is not None or incoming is not None:
                raise SomaError(
                    "TASK_RETRY_ALREADY_EXISTS",
                    "retry predecessor already has a successor or successor already has a predecessor",
                )

            self._assert_no_cycle(
                uow,
                predecessor_task_id=predecessor_id,
                successor_task_id=successor_id,
            )
            retry_relation_id = new_uuid4()
            audit_event_id = new_uuid4()
            now = utc_epoch_seconds()

            def apply(inner: UnitOfWork) -> AuditEventInput:
                inner.connection.execute(
                    "INSERT INTO task_retry_relations("
                    "retry_relation_id,predecessor_task_id,successor_task_id,created_at_utc,command_id"
                    ") VALUES (?,?,?,?,?)",
                    (
                        retry_relation_id,
                        predecessor_id,
                        successor_id,
                        now,
                        command_id,
                    ),
                )
                return AuditEventInput(
                    audit_event_id=audit_event_id,
                    action_type="task.retry_created_or_linked",
                    action_version=1,
                    actor_kind=actor_kind,
                    actor_id=actor_id,
                    target_type="task",
                    target_id=predecessor_id,
                    reason_category=reason,
                    command_id=command_id,
                    payload_schema="TaskRetryAuditV1",
                    payload_version=1,
                    payload={
                        "predecessor_task_id": predecessor_id,
                        "successor_task_id": successor_id,
                        "retry_relation_id": retry_relation_id,
                        "successor_kind": "wfm",
                        "activity_lineage_id": None,
                        "resulting_revisions": {
                            predecessor_id: predecessor.task_revision,
                            successor_id: successor.task_revision,
                        },
                        "reason_category": reason,
                    },
                    resulting_event_refs=(
                        AuditResultRef("task_retry_relation", retry_relation_id),
                    ),
                )

            return PreparedMutation(
                False,
                "task_retry_relation",
                retry_relation_id,
                apply,
                response_schema="TaskMutationResultV1",
                response_version=1,
                response={
                    "outcome": "APPLIED",
                    "task_id": predecessor_id,
                    "revision": predecessor.task_revision,
                    "result_refs": [
                        {"type": "task_retry_relation", "id": retry_relation_id},
                    ],
                },
            )

        return task_mutation_result_from_execution(self._boundary.execute(envelope, prepare))