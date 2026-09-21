from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

from soma.foundation.application.command_boundary import (
    CommandBoundary,
    CommandEnvelope,
    CommandExecutionResult,
    PreparedMutation,
)
from soma.foundation.audit.writer import AuditEventInput, AuditResultRef, AuditWriter
from soma.foundation.errors import IntegrityFailure, SomaError, ValidationError
from soma.foundation.identifiers import new_uuid4, require_uuid4, utc_epoch_seconds
from soma.foundation.persistence.connections import ConnectionFactory
from soma.foundation.persistence.uow import UnitOfWork

from .audit_registry import build_tickets_audit_registry
from .queries.rfc_archive import (
    RfcArchiveOperation,
    RfcArchiveQueryService,
    resolve_archive_scope_from_connection,
)

_SCOPE_KINDS = frozenset({"exact_rfc", "reviewed_branch"})
_SHA256_HEX_RE = re.compile(r"[0-9a-f]{64}\Z")
_COMMAND_OPERATION_PAGE_LIMIT = 32


@dataclass(frozen=True, slots=True)
class ArchiveRfcResult:
    outcome: str
    scope_kind: str
    scope_fingerprint: str
    exact_member_count: int
    changed_rfc_count: int
    excluded_prearchived_count: int
    rfc_archive_operation_id: str | None
    replayed: bool
    no_change: bool

    def to_response(self) -> dict[str, object]:
        return {
            "outcome": self.outcome,
            "scope_kind": self.scope_kind,
            "scope_fingerprint": self.scope_fingerprint,
            "exact_member_count": self.exact_member_count,
            "changed_rfc_count": self.changed_rfc_count,
            "excluded_prearchived_count": self.excluded_prearchived_count,
            "rfc_archive_operation_id": self.rfc_archive_operation_id,
        }


def _request_uuid(value: object, *, field: str) -> str:
    if not isinstance(value, str):
        raise ValidationError(f"{field} must be canonical UUIDv4")
    try:
        return require_uuid4(value)
    except ValidationError as exc:
        raise ValidationError(f"{field} must be canonical UUIDv4") from exc


def _scope_kind(value: object) -> str:
    if not isinstance(value, str) or value not in _SCOPE_KINDS:
        raise ValidationError("scope_kind must be exact_rfc or reviewed_branch")
    return value


def _scope_fingerprint(value: object) -> str:
    if not isinstance(value, str) or _SHA256_HEX_RE.fullmatch(value) is None:
        raise ValidationError("reviewed_scope_fingerprint must be lowercase SHA-256 hex")
    return value


def _archive_response(
    *,
    outcome: str,
    scope_kind: str,
    scope_fingerprint: str,
    exact_member_count: int,
    changed_rfc_count: int,
    excluded_prearchived_count: int,
    rfc_archive_operation_id: str | None,
) -> dict[str, object]:
    return {
        "outcome": outcome,
        "scope_kind": scope_kind,
        "scope_fingerprint": scope_fingerprint,
        "exact_member_count": exact_member_count,
        "changed_rfc_count": changed_rfc_count,
        "excluded_prearchived_count": excluded_prearchived_count,
        "rfc_archive_operation_id": rfc_archive_operation_id,
    }


def _archive_result_from_execution(result: CommandExecutionResult) -> ArchiveRfcResult:
    if (
        result.response_schema != "ArchiveRfcResultV1"
        or result.response_version != 1
        or not isinstance(result.response, dict)
        or set(result.response) != {
            "outcome",
            "scope_kind",
            "scope_fingerprint",
            "exact_member_count",
            "changed_rfc_count",
            "excluded_prearchived_count",
            "rfc_archive_operation_id",
        }
    ):
        raise IntegrityFailure("RFC archive committed response contract is invalid")

    response = result.response
    outcome = response["outcome"]
    scope_kind = response["scope_kind"]
    fingerprint = response["scope_fingerprint"]
    exact_count = response["exact_member_count"]
    changed_count = response["changed_rfc_count"]
    excluded_count = response["excluded_prearchived_count"]
    operation_id = response["rfc_archive_operation_id"]

    if outcome not in {"archived", "no_change"} or scope_kind not in _SCOPE_KINDS:
        raise IntegrityFailure("RFC archive committed response state is invalid")
    if not isinstance(fingerprint, str) or _SHA256_HEX_RE.fullmatch(fingerprint) is None:
        raise IntegrityFailure("RFC archive committed response fingerprint is invalid")
    if (
        type(exact_count) is not int
        or exact_count < 1
        or type(changed_count) is not int
        or changed_count < 0
        or type(excluded_count) is not int
        or excluded_count < 0
        or changed_count + excluded_count != exact_count
    ):
        raise IntegrityFailure("RFC archive committed response counts are invalid")

    canonical_operation_id: str | None
    if operation_id is None:
        canonical_operation_id = None
    else:
        try:
            canonical_operation_id = require_uuid4(operation_id)
        except ValidationError as exc:
            raise IntegrityFailure("RFC archive committed operation identity is invalid") from exc

    expected_no_change = outcome == "no_change"
    if expected_no_change != result.no_change:
        raise IntegrityFailure("RFC archive committed response outcome disagrees with receipt result")
    if expected_no_change:
        if changed_count != 0 or canonical_operation_id is not None:
            raise IntegrityFailure("RFC archive NO_CHANGE committed response is invalid")
    else:
        if changed_count <= 0 or canonical_operation_id is None:
            raise IntegrityFailure("RFC archive material committed response is invalid")
        if result.result_type != "rfc_archive_operation" or result.result_id != canonical_operation_id:
            raise IntegrityFailure("RFC archive material receipt result identity is invalid")

    return ArchiveRfcResult(
        outcome=outcome,
        scope_kind=scope_kind,
        scope_fingerprint=fingerprint,
        exact_member_count=exact_count,
        changed_rfc_count=changed_count,
        excluded_prearchived_count=excluded_count,
        rfc_archive_operation_id=canonical_operation_id,
        replayed=result.replayed,
        no_change=result.no_change,
    )


def _operation_from_execution(result: CommandExecutionResult) -> RfcArchiveOperation:
    if result.response_schema != "RfcArchiveOperationV1" or result.response_version != 1:
        raise IntegrityFailure("RFC archive restore committed response contract is invalid")
    try:
        operation = RfcArchiveOperation.from_response(result.response)
    except ValidationError as exc:
        raise IntegrityFailure("RFC archive restore committed response is invalid") from exc
    if result.no_change:
        if result.result_type != "NO_CHANGE" or result.result_id is not None:
            raise IntegrityFailure("RFC archive restore NO_CHANGE receipt is invalid")
    elif result.result_type != "rfc_archive_operation" or result.result_id != operation.rfc_archive_operation_id:
        raise IntegrityFailure("RFC archive restore receipt result identity is invalid")
    return operation


class RfcArchiveService:
    """LLD-03 owner for governed RFC archive and operation-scoped restore."""

    def __init__(self, connection_factory: ConnectionFactory) -> None:
        self._queries = RfcArchiveQueryService(connection_factory)
        self._boundary = CommandBoundary(
            connection_factory,
            AuditWriter(build_tickets_audit_registry()),
        )

    def _operation_response_factory(self, operation_id: str):
        def build_response(uow: UnitOfWork) -> dict[str, object]:
            return self._queries.get_from_connection(
                uow.connection,
                rfc_archive_operation_id=operation_id,
                cursor=None,
                limit=_COMMAND_OPERATION_PAGE_LIMIT,
            ).to_response()

        return build_response

    def archive(
        self,
        *,
        command_id: str,
        rfc_id: str,
        scope_kind: str,
        reviewed_scope_fingerprint: str,
        actor_kind: str = "local_user",
        actor_id: str | None = None,
    ) -> ArchiveRfcResult:
        canonical_rfc_id = _request_uuid(rfc_id, field="rfc_id")
        canonical_scope_kind = _scope_kind(scope_kind)
        reviewed_fingerprint = _scope_fingerprint(reviewed_scope_fingerprint)
        envelope = CommandEnvelope(
            command_id=command_id,
            command_type="ArchiveRfc",
            target_type="rfc",
            target_id=canonical_rfc_id,
            semantic_payload={"scope_kind": canonical_scope_kind},
            authorizing_fingerprints={"reviewed_scope_fingerprint": reviewed_fingerprint},
        )

        def prepare(uow: UnitOfWork) -> PreparedMutation:
            scope = resolve_archive_scope_from_connection(
                uow.connection,
                rfc_id=canonical_rfc_id,
                scope_kind=canonical_scope_kind,
            )
            if scope.scope_fingerprint != reviewed_fingerprint:
                raise SomaError(
                    "RFC_ARCHIVE_SCOPE_STALE",
                    "RFC archive reviewed scope changed before writer revalidation",
                )

            exact_count = scope.exact_member_count
            changed_count = scope.would_change_count
            excluded_count = scope.excluded_prearchived_count
            if changed_count == 0:
                return PreparedMutation(
                    True,
                    None,
                    None,
                    response_schema="ArchiveRfcResultV1",
                    response_version=1,
                    response=_archive_response(
                        outcome="no_change",
                        scope_kind=canonical_scope_kind,
                        scope_fingerprint=scope.scope_fingerprint,
                        exact_member_count=exact_count,
                        changed_rfc_count=0,
                        excluded_prearchived_count=excluded_count,
                        rfc_archive_operation_id=None,
                    ),
                )

            operation_id = new_uuid4()
            audit_event_id = new_uuid4()
            now = utc_epoch_seconds()
            response = _archive_response(
                outcome="archived",
                scope_kind=canonical_scope_kind,
                scope_fingerprint=scope.scope_fingerprint,
                exact_member_count=exact_count,
                changed_rfc_count=changed_count,
                excluded_prearchived_count=excluded_count,
                rfc_archive_operation_id=operation_id,
            )

            def apply(inner: UnitOfWork) -> AuditEventInput:
                inner.connection.execute(
                    "INSERT INTO rfc_archive_operations("
                    "rfc_archive_operation_id,requested_rfc_id,scope_kind,scope_fingerprint,created_at_utc,created_command_id"
                    ") VALUES (?, ?, ?, ?, ?, ?)",
                    (
                        operation_id,
                        canonical_rfc_id,
                        canonical_scope_kind,
                        scope.scope_fingerprint,
                        now,
                        command_id,
                    ),
                )
                applied_count = 0
                for member in scope.members:
                    if member.archive_state != "active":
                        continue
                    resulting_revision = member.rfc_revision + 1
                    updated = inner.connection.execute(
                        "UPDATE rfcs SET local_archive_state='archived',revision=revision+1,updated_at_utc=? "
                        "WHERE rfc_id=? AND revision=? AND local_archive_state='active'",
                        (now, member.rfc_id, member.rfc_revision),
                    )
                    if updated.rowcount != 1:
                        raise SomaError(
                            "RFC_ARCHIVE_SCOPE_STALE",
                            "RFC archive member changed before publication",
                        )
                    inner.connection.execute(
                        "INSERT INTO rfc_archive_operation_members("
                        "rfc_archive_operation_id,rfc_id,pre_archive_revision,archived_revision,ordinal"
                        ") VALUES (?, ?, ?, ?, ?)",
                        (
                            operation_id,
                            member.rfc_id,
                            member.rfc_revision,
                            resulting_revision,
                            member.scope_ordinal,
                        ),
                    )
                    inner.connection.execute(
                        "INSERT INTO rfc_archive_events("
                        "rfc_archive_event_id,rfc_id,event_type,origin_archive_operation_id,"
                        "resulting_rfc_revision,occurred_at_utc,command_id"
                        ") VALUES (?, ?, 'archived', ?, ?, ?, ?)",
                        (
                            new_uuid4(),
                            member.rfc_id,
                            operation_id,
                            resulting_revision,
                            now,
                            command_id,
                        ),
                    )
                    applied_count += 1
                if applied_count != changed_count:
                    raise SomaError(
                        "PERSISTENCE_FAILURE",
                        "RFC archive applied member count disagrees with reviewed scope",
                    )
                return AuditEventInput(
                    audit_event_id=audit_event_id,
                    action_type="ticket.rfc.archived",
                    action_version=1,
                    actor_kind=actor_kind,
                    actor_id=actor_id,
                    target_type="rfc_archive_operation",
                    target_id=operation_id,
                    reason_category=None,
                    command_id=command_id,
                    payload_schema="RfcArchiveAuditV1",
                    payload_version=1,
                    payload={
                        "rfc_archive_operation_id": operation_id,
                        "scope_kind": canonical_scope_kind,
                        "scope_fingerprint": scope.scope_fingerprint,
                        "changed_rfc_count": changed_count,
                        "excluded_prearchived_count": excluded_count,
                        "resulting_operation_state": "archived",
                        "reason_category": None,
                    },
                    resulting_event_refs=(
                        AuditResultRef("rfc_archive_operation", operation_id),
                    ),
                )

            return PreparedMutation(
                False,
                "rfc_archive_operation",
                operation_id,
                apply,
                response_schema="ArchiveRfcResultV1",
                response_version=1,
                response=response,
            )

        return _archive_result_from_execution(self._boundary.execute(envelope, prepare))

    def restore_operation(
        self,
        *,
        command_id: str,
        rfc_archive_operation_id: str,
        actor_kind: str = "local_user",
        actor_id: str | None = None,
    ) -> RfcArchiveOperation:
        operation_id = _request_uuid(
            rfc_archive_operation_id,
            field="rfc_archive_operation_id",
        )
        envelope = CommandEnvelope(
            command_id=command_id,
            command_type="RestoreRfcArchiveOperation",
            target_type="rfc_archive_operation",
            target_id=operation_id,
            semantic_payload={},
        )

        def prepare(uow: UnitOfWork) -> PreparedMutation:
            scope_kind, scope_fingerprint, members = (
                self._queries.load_complete_operation_members_from_connection(
                    uow.connection,
                    rfc_archive_operation_id=operation_id,
                )
            )
            eligible_count = sum(member.restore_eligible for member in members)
            response_factory = self._operation_response_factory(operation_id)
            if eligible_count == 0:
                return PreparedMutation(
                    True,
                    None,
                    None,
                    response_schema="RfcArchiveOperationV1",
                    response_version=1,
                    response_factory=response_factory,
                )

            audit_event_id = new_uuid4()
            now = utc_epoch_seconds()

            def apply(inner: UnitOfWork) -> AuditEventInput:
                restored_count = 0
                for member in members:
                    if not member.restore_eligible:
                        continue
                    row = inner.connection.execute(
                        "SELECT revision,local_archive_state FROM rfcs WHERE rfc_id=?",
                        (member.rfc_id,),
                    ).fetchone()
                    if row is None:
                        raise SomaError("PERSISTENCE_FAILURE", "RFC archive member disappeared")
                    current_revision = row[0]
                    current_state = str(row[1])
                    if type(current_revision) is not int or current_revision <= 0:
                        raise SomaError("PERSISTENCE_FAILURE", "RFC archive member revision is invalid")
                    if current_state != "archived":
                        raise SomaError(
                            "RFC_ARCHIVE_SCOPE_STALE",
                            "RFC archive restore eligibility changed before publication",
                        )
                    resulting_revision = current_revision + 1
                    updated = inner.connection.execute(
                        "UPDATE rfcs SET local_archive_state='active',revision=revision+1,updated_at_utc=? "
                        "WHERE rfc_id=? AND revision=? AND local_archive_state='archived'",
                        (now, member.rfc_id, current_revision),
                    )
                    if updated.rowcount != 1:
                        raise SomaError(
                            "RFC_ARCHIVE_SCOPE_STALE",
                            "RFC archive restore member changed before publication",
                        )
                    inner.connection.execute(
                        "INSERT INTO rfc_archive_events("
                        "rfc_archive_event_id,rfc_id,event_type,origin_archive_operation_id,"
                        "resulting_rfc_revision,occurred_at_utc,command_id"
                        ") VALUES (?, ?, 'restored', ?, ?, ?, ?)",
                        (
                            new_uuid4(),
                            member.rfc_id,
                            operation_id,
                            resulting_revision,
                            now,
                            command_id,
                        ),
                    )
                    restored_count += 1
                if restored_count != eligible_count:
                    raise SomaError(
                        "PERSISTENCE_FAILURE",
                        "RFC archive restore count disagrees with operation eligibility",
                    )
                return AuditEventInput(
                    audit_event_id=audit_event_id,
                    action_type="ticket.rfc.archive_restored",
                    action_version=1,
                    actor_kind=actor_kind,
                    actor_id=actor_id,
                    target_type="rfc_archive_operation",
                    target_id=operation_id,
                    reason_category=None,
                    command_id=command_id,
                    payload_schema="RfcArchiveAuditV1",
                    payload_version=1,
                    payload={
                        "rfc_archive_operation_id": operation_id,
                        "scope_kind": scope_kind,
                        "scope_fingerprint": scope_fingerprint,
                        "changed_rfc_count": eligible_count,
                        "excluded_prearchived_count": 0,
                        "resulting_operation_state": "restored",
                        "reason_category": None,
                    },
                    resulting_event_refs=(
                        AuditResultRef("rfc_archive_operation", operation_id),
                    ),
                )

            return PreparedMutation(
                False,
                "rfc_archive_operation",
                operation_id,
                apply,
                response_schema="RfcArchiveOperationV1",
                response_version=1,
                response_factory=response_factory,
            )

        return _operation_from_execution(self._boundary.execute(envelope, prepare))
