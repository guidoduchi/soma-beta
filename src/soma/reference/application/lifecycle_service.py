from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal

from soma.foundation.application.command_boundary import CommandBoundary, CommandEnvelope, PreparedMutation
from soma.foundation.audit.writer import AuditEventInput, AuditResultRef, AuditWriter
from soma.foundation.errors import SomaError, ValidationError
from soma.foundation.identifiers import new_uuid4, utc_epoch_seconds
from soma.foundation.persistence.connections import ConnectionFactory
from soma.foundation.persistence.uow import ReadSnapshot, UnitOfWork
from soma.reference.audit_registry import build_reference_audit_registry
from soma.reference.domain.dependencies import (
    DependencyBlocker,
    DependencyGuard,
    ReferenceDependencyRegistry,
    ReferenceTarget,
    ReferenceType,
)
from soma.reference.domain.validation import validate_reason_category
from soma.reference.results import ReferenceMutationResult, reference_mutation_result_from_execution

LifecycleOperation = Literal["archive", "reactivate"]


@dataclass(frozen=True, slots=True)
class PreviewBlocker:
    validator_id: str
    blocker_id: str
    reason_code: str


@dataclass(frozen=True, slots=True)
class LifecyclePreview:
    target_type: ReferenceType
    target_id: str
    operation: LifecycleOperation
    exact_blocker_count: int
    blockers: tuple[PreviewBlocker, ...]
    continuation: str | None
    would_be_eligible: bool


class ReferenceLifecycleService:
    _TABLES: dict[str, tuple[str, str]] = {
        "customer_organization": ("customer_organizations", "customer_org_id"),
        "contact": ("contacts", "contact_id"),
        "dispatch_location": ("dispatch_locations", "dispatch_location_id"),
    }

    def __init__(
        self,
        connection_factory: ConnectionFactory,
        dependency_registry: ReferenceDependencyRegistry | None = None,
    ) -> None:
        self._factory = connection_factory
        self._dependencies = dependency_registry or ReferenceDependencyRegistry()
        self._boundary = CommandBoundary(
            connection_factory,
            AuditWriter(build_reference_audit_registry()),
        )

    @classmethod
    def _table(cls, target_type: str) -> tuple[str, str]:
        result = cls._TABLES.get(target_type)
        if result is None:
            raise ValidationError("reference target_type is outside the closed LLD-02 enum")
        return result

    @classmethod
    def _load(cls, connection: Any, target: ReferenceTarget) -> tuple[str, int]:
        table, id_column = cls._table(target.target_type)
        row = connection.execute(
            f"SELECT lifecycle_state,revision FROM {table} WHERE {id_column}=?",
            (target.target_id,),
        ).fetchone()
        if row is None:
            raise SomaError("NOT_FOUND", "reference target does not exist")
        return str(row[0]), int(row[1])

    @staticmethod
    def _reason(value: str | None) -> str:
        result = validate_reason_category(value)
        if result is None:
            raise SomaError("VALIDATION_FAILED", "reason_category is required")
        return result

    def _guard(self, uow: UnitOfWork, target: ReferenceTarget, operation: LifecycleOperation) -> None:
        for validator in self._dependencies.ordered():
            try:
                guard: DependencyGuard = (
                    validator.guard_archive(uow, target)
                    if operation == "archive"
                    else validator.guard_reactivate(uow, target)
                )
            except SomaError:
                raise
            except Exception as exc:
                raise SomaError(
                    "DEPENDENCY_VALIDATION_FAILED",
                    f"dependency validator {validator.validator_id} failed closed",
                ) from exc
            if guard.state == "BLOCKED":
                code = "ARCHIVE_BLOCKED" if operation == "archive" else "REACTIVATION_BLOCKED"
                raise SomaError(code, guard.reason_code or f"{operation} blocked")
            if guard.state != "CLEAR":
                raise SomaError(
                    "DEPENDENCY_VALIDATION_FAILED",
                    guard.reason_code or f"{operation} dependency state is indeterminate",
                )

    def archive_reference(
        self,
        *,
        command_id: str,
        target_type: ReferenceType,
        target_id: str,
        base_revision: int,
        reason_category: str | None,
        actor_kind: str = "local_user",
        actor_id: str | None = None,
    ) -> ReferenceMutationResult:
        self._table(target_type)
        reason = self._reason(reason_category)
        target = ReferenceTarget(target_type, target_id)
        envelope = CommandEnvelope(
            command_id=command_id,
            command_type="ArchiveReference",
            target_type=target_type,
            target_id=target_id,
            semantic_payload={"reason_category": reason},
            base_revisions={target_type: base_revision},
        )

        def prepare(uow: UnitOfWork) -> PreparedMutation:
            state, revision = self._load(uow.connection, target)
            if revision != base_revision:
                raise SomaError("STALE_REVISION", "reference revision changed")
            if state != "active":
                raise SomaError("REFERENCE_ARCHIVED", "reference is already archived")
            self._guard(uow, target, "archive")
            lifecycle_event_id = new_uuid4()
            audit_event_id = new_uuid4()
            now = utc_epoch_seconds()
            table, id_column = self._table(target_type)

            def apply(inner: UnitOfWork) -> AuditEventInput:
                inner.connection.execute(
                    f"UPDATE {table} SET lifecycle_state='archived',revision=revision+1,updated_at_utc=? "
                    f"WHERE {id_column}=?",
                    (now, target_id),
                )
                inner.connection.execute(
                    "INSERT INTO reference_lifecycle_events(reference_lifecycle_event_id,target_type,target_id,event_type,"
                    "occurred_at_utc,command_id,reason_category) VALUES (?, ?, ?, 'archived', ?, ?, ?)",
                    (lifecycle_event_id, target_type, target_id, now, command_id, reason),
                )
                return AuditEventInput(
                    audit_event_id=audit_event_id,
                    action_type="reference.archived",
                    action_version=1,
                    actor_kind=actor_kind,
                    actor_id=actor_id,
                    target_type=target_type,
                    target_id=target_id,
                    reason_category=reason,
                    command_id=command_id,
                    payload_schema="ReferenceLifecycleAuditV1",
                    payload_version=1,
                    payload={
                        "target_type": target_type,
                        "target_id": target_id,
                        "prior_state": "active",
                        "new_state": "archived",
                        "prior_revision": base_revision,
                        "new_revision": base_revision + 1,
                        "lifecycle_event_id": lifecycle_event_id,
                        "reason_category": reason,
                    },
                    resulting_event_refs=(
                        AuditResultRef(target_type, target_id),
                        AuditResultRef("reference_lifecycle_event", lifecycle_event_id),
                    ),
                )

            return PreparedMutation(
                False,
                target_type,
                target_id,
                apply,
                response_schema="ReferenceMutationResultV1",
                response_version=1,
                response={"outcome": "APPLIED", "target_id": target_id, "revision": base_revision + 1},
            )

        return reference_mutation_result_from_execution(self._boundary.execute(envelope, prepare))

    def reactivate_reference(
        self,
        *,
        command_id: str,
        target_type: ReferenceType,
        target_id: str,
        base_revision: int,
        reason_category: str | None,
        actor_kind: str = "local_user",
        actor_id: str | None = None,
    ) -> ReferenceMutationResult:
        self._table(target_type)
        reason = self._reason(reason_category)
        target = ReferenceTarget(target_type, target_id)
        envelope = CommandEnvelope(
            command_id=command_id,
            command_type="ReactivateReference",
            target_type=target_type,
            target_id=target_id,
            semantic_payload={"reason_category": reason},
            base_revisions={target_type: base_revision},
        )

        def prepare(uow: UnitOfWork) -> PreparedMutation:
            state, revision = self._load(uow.connection, target)
            if revision != base_revision:
                raise SomaError("STALE_REVISION", "reference revision changed")
            if state != "archived":
                raise SomaError("VALIDATION_FAILED", "reference must be archived before reactivation")
            self._guard(uow, target, "reactivate")
            lifecycle_event_id = new_uuid4()
            audit_event_id = new_uuid4()
            now = utc_epoch_seconds()
            table, id_column = self._table(target_type)

            def apply(inner: UnitOfWork) -> AuditEventInput:
                inner.connection.execute(
                    f"UPDATE {table} SET lifecycle_state='active',revision=revision+1,updated_at_utc=? "
                    f"WHERE {id_column}=?",
                    (now, target_id),
                )
                inner.connection.execute(
                    "INSERT INTO reference_lifecycle_events(reference_lifecycle_event_id,target_type,target_id,event_type,"
                    "occurred_at_utc,command_id,reason_category) VALUES (?, ?, ?, 'reactivated', ?, ?, ?)",
                    (lifecycle_event_id, target_type, target_id, now, command_id, reason),
                )
                return AuditEventInput(
                    audit_event_id=audit_event_id,
                    action_type="reference.reactivated",
                    action_version=1,
                    actor_kind=actor_kind,
                    actor_id=actor_id,
                    target_type=target_type,
                    target_id=target_id,
                    reason_category=reason,
                    command_id=command_id,
                    payload_schema="ReferenceLifecycleAuditV1",
                    payload_version=1,
                    payload={
                        "target_type": target_type,
                        "target_id": target_id,
                        "prior_state": "archived",
                        "new_state": "active",
                        "prior_revision": base_revision,
                        "new_revision": base_revision + 1,
                        "lifecycle_event_id": lifecycle_event_id,
                        "reason_category": reason,
                    },
                    resulting_event_refs=(
                        AuditResultRef(target_type, target_id),
                        AuditResultRef("reference_lifecycle_event", lifecycle_event_id),
                    ),
                )

            return PreparedMutation(
                False,
                target_type,
                target_id,
                apply,
                response_schema="ReferenceMutationResultV1",
                response_version=1,
                response={"outcome": "APPLIED", "target_id": target_id, "revision": base_revision + 1},
            )

        return reference_mutation_result_from_execution(self._boundary.execute(envelope, prepare))

    def preview(
        self,
        *,
        operation: LifecycleOperation,
        target_type: ReferenceType,
        target_id: str,
        after: str | None = None,
        limit: int = 50,
    ) -> LifecyclePreview:
        if operation not in ("archive", "reactivate"):
            raise ValidationError("unsupported lifecycle preview operation")
        if type(limit) is not int or limit < 1 or limit > 200:
            raise SomaError("FIELD_BOUND_EXCEEDED", "preview limit must be in 1..200")
        target = ReferenceTarget(target_type, target_id)
        validators = self._dependencies.ordered()
        with ReadSnapshot(self._factory) as snapshot:
            state, _ = self._load(snapshot.connection, target)
            if operation == "archive" and state != "active":
                raise SomaError("REFERENCE_ARCHIVED", "reference is already archived")
            if operation == "reactivate" and state != "archived":
                raise SomaError("VALIDATION_FAILED", "reference must be archived before reactivation")

            total = 0
            all_blockers: list[PreviewBlocker] = []
            for validator in validators:
                try:
                    count = (
                        validator.count_archive_blockers(snapshot, target)
                        if operation == "archive"
                        else validator.count_reactivation_blockers(snapshot, target)
                    )
                    if type(count) is not int or count < 0:
                        raise ValueError("invalid blocker count")
                    total += count
                    cursor: str | None = None
                    remaining_for_validator = count
                    while remaining_for_validator > 0:
                        page_limit = min(200, remaining_for_validator)
                        page = (
                            validator.list_archive_blockers(snapshot, target, cursor, page_limit)
                            if operation == "archive"
                            else validator.list_reactivation_blockers(snapshot, target, cursor, page_limit)
                        )
                        if not page.blockers:
                            raise ValueError("validator count/list disagreement")
                        for blocker in page.blockers:
                            all_blockers.append(
                                PreviewBlocker(
                                    validator.validator_id,
                                    blocker.blocker_id,
                                    blocker.reason_code,
                                )
                            )
                        remaining_for_validator -= len(page.blockers)
                        if remaining_for_validator > 0 and page.continuation is None:
                            raise ValueError("validator pagination ended before exact count")
                        cursor = page.continuation
                except SomaError:
                    raise
                except Exception as exc:
                    raise SomaError(
                        "DEPENDENCY_VALIDATION_FAILED",
                        f"dependency validator {validator.validator_id} preview failed closed",
                    ) from exc

        all_blockers.sort(key=lambda item: (item.validator_id, item.blocker_id, item.reason_code))
        if len(all_blockers) != total:
            raise SomaError("DEPENDENCY_VALIDATION_FAILED", "dependency blocker count/list mismatch")
        start = 0
        if after is not None:
            tokens = [f"{item.validator_id}\x1f{item.blocker_id}\x1f{item.reason_code}" for item in all_blockers]
            start = next((index + 1 for index, token in enumerate(tokens) if token == after), -1)
            if start < 0:
                raise SomaError("VALIDATION_FAILED", "preview continuation is invalid or stale")
        page_items = tuple(all_blockers[start : start + limit])
        continuation = None
        if start + limit < len(all_blockers) and page_items:
            last = page_items[-1]
            continuation = f"{last.validator_id}\x1f{last.blocker_id}\x1f{last.reason_code}"
        return LifecyclePreview(
            target_type,
            target_id,
            operation,
            total,
            page_items,
            continuation,
            total == 0,
        )
