from __future__ import annotations

import base64
from dataclasses import dataclass
from typing import Any, Literal

from soma.foundation.application.command_boundary import CommandBoundary, CommandEnvelope, PreparedMutation
from soma.foundation.audit.writer import AuditEventInput, AuditResultRef, AuditWriter
from soma.foundation.errors import SomaError, ValidationError
from soma.foundation.identifiers import new_uuid4, utc_epoch_seconds
from soma.foundation.persistence.connections import ConnectionFactory
from soma.foundation.persistence.uow import ReadSnapshot, UnitOfWork
from soma.foundation.strict_json import canonical_json_bytes_bounded, loads_canonical_json
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
    revision: int
    exact_blocker_count: int
    blockers: tuple[PreviewBlocker, ...]
    continuation: str | None
    would_be_eligible: bool


class ReferenceLifecycleService:
    _PREVIEW_CURSOR_PREFIX = "SOMA_REFERENCE_PREVIEW_CURSOR_V1."
    _PREVIEW_CURSOR_MAX_BYTES = 8192
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
        if dependency_registry is None:
            raise ValidationError("reference dependency registry is required")
        dependency_registry.require_finalized()
        self._factory = connection_factory
        self._dependencies = dependency_registry
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

    @classmethod
    def _encode_preview_cursor(
        cls,
        *,
        target: ReferenceTarget,
        operation: LifecycleOperation,
        validator_id: str,
        inner_cursor: str | None,
    ) -> str:
        payload = {
            "schema": "SOMA_REFERENCE_PREVIEW_CURSOR_V1",
            "target_type": target.target_type,
            "target_id": target.target_id,
            "operation": operation,
            "validator_id": validator_id,
            "inner_cursor": inner_cursor,
        }
        raw = canonical_json_bytes_bounded(
            payload,
            max_bytes=cls._PREVIEW_CURSOR_MAX_BYTES,
            max_depth=2,
            max_collection_items=8,
        )
        token = base64.urlsafe_b64encode(raw).rstrip(b"=").decode("ascii")
        return cls._PREVIEW_CURSOR_PREFIX + token

    @classmethod
    def _decode_preview_cursor(
        cls,
        cursor: str,
        *,
        target: ReferenceTarget,
        operation: LifecycleOperation,
        validator_ids: tuple[str, ...],
    ) -> tuple[int, str | None]:
        try:
            if not cursor.startswith(cls._PREVIEW_CURSOR_PREFIX):
                raise ValueError("wrong preview cursor version")
            token = cursor[len(cls._PREVIEW_CURSOR_PREFIX) :]
            if not token or len(token) > cls._PREVIEW_CURSOR_MAX_BYTES * 2:
                raise ValueError("preview cursor length is invalid")
            encoded = token.encode("ascii")
            encoded += b"=" * ((4 - len(encoded) % 4) % 4)
            raw = base64.b64decode(encoded, altchars=b"-_", validate=True)
            if len(raw) > cls._PREVIEW_CURSOR_MAX_BYTES:
                raise ValueError("preview cursor payload is oversized")
            payload = loads_canonical_json(
                raw.decode("utf-8", errors="strict"),
                max_bytes=cls._PREVIEW_CURSOR_MAX_BYTES,
                max_depth=2,
                max_collection_items=8,
            )
            if not isinstance(payload, dict) or set(payload) != {
                "schema",
                "target_type",
                "target_id",
                "operation",
                "validator_id",
                "inner_cursor",
            }:
                raise ValueError("preview cursor payload shape is invalid")
            if payload["schema"] != "SOMA_REFERENCE_PREVIEW_CURSOR_V1":
                raise ValueError("preview cursor schema is invalid")
            if (
                payload["target_type"] != target.target_type
                or payload["target_id"] != target.target_id
                or payload["operation"] != operation
            ):
                raise ValueError("preview cursor filter does not match")
            validator_id = payload["validator_id"]
            inner_cursor = payload["inner_cursor"]
            if not isinstance(validator_id, str):
                raise ValueError("preview cursor validator is invalid")
            if inner_cursor is not None and not isinstance(inner_cursor, str):
                raise ValueError("preview inner cursor is invalid")
            matches = [
                index
                for index, current in enumerate(validator_ids)
                if current == validator_id
            ]
            if len(matches) != 1:
                raise ValueError("preview cursor validator is unavailable")
            return matches[0], inner_cursor
        except Exception as exc:
            raise ValidationError("reference lifecycle preview cursor is invalid") from exc

    def preview(
        self,
        *,
        operation: LifecycleOperation,
        target_type: ReferenceType,
        target_id: str,
        base_revision: int,
        after: str | None = None,
        limit: int = 50,
    ) -> LifecyclePreview:
        if operation not in ("archive", "reactivate"):
            raise ValidationError("unsupported lifecycle preview operation")
        if type(base_revision) is not int or base_revision < 1:
            raise ValidationError("reference preview base_revision must be a positive integer")
        if type(limit) is not int or limit < 1 or limit > 200:
            raise SomaError("FIELD_BOUND_EXCEEDED", "preview limit must be in 1..200")
        target = ReferenceTarget(target_type, target_id)
        validators = self._dependencies.ordered()
        validator_ids = tuple(validator.validator_id for validator in validators)

        with ReadSnapshot(self._factory) as snapshot:
            state, revision = self._load(snapshot.connection, target)
            if revision != base_revision:
                raise SomaError("STALE_REVISION", "reference revision changed")
            if operation == "archive" and state != "active":
                raise SomaError("REFERENCE_ARCHIVED", "reference is already archived")
            if operation == "reactivate" and state != "archived":
                raise SomaError(
                    "VALIDATION_FAILED",
                    "reference must be archived before reactivation",
                )

            counts: list[int] = []
            for validator in validators:
                try:
                    count = (
                        validator.count_archive_blockers(snapshot, target)
                        if operation == "archive"
                        else validator.count_reactivation_blockers(snapshot, target)
                    )
                    if type(count) is not int or count < 0:
                        raise ValueError("invalid blocker count")
                    counts.append(count)
                except SomaError:
                    raise
                except Exception as exc:
                    raise SomaError(
                        "DEPENDENCY_VALIDATION_FAILED",
                        f"dependency validator {validator.validator_id} preview failed closed",
                    ) from exc

            total = sum(counts)
            start_index = 0
            inner_cursor: str | None = None
            if after is not None:
                start_index, inner_cursor = self._decode_preview_cursor(
                    after,
                    target=target,
                    operation=operation,
                    validator_ids=validator_ids,
                )

            page_items: list[PreviewBlocker] = []
            continuation: str | None = None
            index = start_index
            current_inner = inner_cursor

            while index < len(validators) and len(page_items) < limit:
                validator = validators[index]
                count = counts[index]
                if count == 0:
                    if current_inner is not None:
                        raise SomaError(
                            "VALIDATION_FAILED",
                            "reference lifecycle preview cursor is stale",
                        )
                    index += 1
                    continue

                remaining = limit - len(page_items)
                try:
                    page = (
                        validator.list_archive_blockers(
                            snapshot,
                            target,
                            current_inner,
                            remaining,
                        )
                        if operation == "archive"
                        else validator.list_reactivation_blockers(
                            snapshot,
                            target,
                            current_inner,
                            remaining,
                        )
                    )
                except SomaError:
                    raise
                except Exception as exc:
                    raise SomaError(
                        "DEPENDENCY_VALIDATION_FAILED",
                        f"dependency validator {validator.validator_id} preview failed closed",
                    ) from exc

                if len(page.blockers) > remaining:
                    raise SomaError(
                        "DEPENDENCY_VALIDATION_FAILED",
                        "dependency validator exceeded requested page size",
                    )
                if not page.blockers:
                    raise SomaError(
                        "DEPENDENCY_VALIDATION_FAILED",
                        "dependency validator count/list disagreement",
                    )
                if page.continuation is not None and len(page.blockers) < remaining:
                    raise SomaError(
                        "DEPENDENCY_VALIDATION_FAILED",
                        "dependency validator returned a short page with continuation",
                    )

                page_items.extend(
                    PreviewBlocker(
                        validator.validator_id,
                        blocker.blocker_id,
                        blocker.reason_code,
                    )
                    for blocker in page.blockers
                )

                if page.continuation is not None:
                    if len(page_items) != limit:
                        raise SomaError(
                            "DEPENDENCY_VALIDATION_FAILED",
                            "dependency validator continuation did not fill requested page",
                        )
                    continuation = self._encode_preview_cursor(
                        target=target,
                        operation=operation,
                        validator_id=validator.validator_id,
                        inner_cursor=page.continuation,
                    )
                    break

                index += 1
                current_inner = None
                if len(page_items) == limit:
                    next_index = next(
                        (
                            candidate
                            for candidate in range(index, len(validators))
                            if counts[candidate] > 0
                        ),
                        None,
                    )
                    if next_index is not None:
                        continuation = self._encode_preview_cursor(
                            target=target,
                            operation=operation,
                            validator_id=validators[next_index].validator_id,
                            inner_cursor=None,
                        )
                    break

        return LifecyclePreview(
            target_type,
            target_id,
            operation,
            revision,
            total,
            tuple(page_items),
            continuation,
            total == 0,
        )
