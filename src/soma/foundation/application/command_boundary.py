from __future__ import annotations

import re
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from soma.foundation.audit.writer import AuditEventInput, AuditWriter
from soma.foundation.errors import IdempotencyConflict, PersistenceFailure, ValidationError
from soma.foundation.identifiers import require_uuid4, utc_epoch_seconds
from soma.foundation.persistence.connections import ConnectionFactory
from soma.foundation.persistence.uow import UnitOfWork
from soma.foundation.strict_json import sha256_canonical_json

AuditEmission = AuditEventInput | tuple[AuditEventInput, ...]
ApplyMutation = Callable[[UnitOfWork], AuditEmission | None]
PrepareMutation = Callable[[UnitOfWork], "PreparedMutation"]


@dataclass(frozen=True, slots=True)
class CommandEnvelope:
    command_id: str
    command_type: str
    target_type: str
    target_id: str | None
    semantic_payload: dict[str, object]
    base_revisions: dict[str, int] = field(default_factory=dict)
    authorizing_fingerprints: dict[str, str] = field(default_factory=dict)
    correlation_id: str | None = None

    def validate(self) -> None:
        require_uuid4(self.command_id)
        if not self.command_type or not self.target_type:
            raise ValidationError("command_type and target_type are required")
        for key, revision in self.base_revisions.items():
            if not key or type(revision) is not int or revision <= 0:
                raise ValidationError("base revisions must be positive integers")
        for key, value in self.authorizing_fingerprints.items():
            if not key or not isinstance(value, str) or re.fullmatch(r"[0-9a-f]{64}", value) is None:
                raise ValidationError("authorizing fingerprints must be SHA-256 hex strings")

    def request_hash(self) -> str:
        self.validate()
        return sha256_canonical_json(
            {
                "command_type": self.command_type,
                "target": {"type": self.target_type, "id": self.target_id},
                "semantic_payload": self.semantic_payload,
                "base_revisions": self.base_revisions,
                "authorizing_fingerprints": self.authorizing_fingerprints,
            }
        )


@dataclass(frozen=True, slots=True)
class PreparedMutation:
    no_change: bool
    result_type: str | None
    result_id: str | None
    apply: ApplyMutation | None = None

    def validate(self) -> None:
        if self.no_change:
            if self.apply is not None:
                raise ValidationError("NO_CHANGE command cannot contain a mutation callback")
            if self.result_type not in (None, "NO_CHANGE") or self.result_id is not None:
                raise ValidationError("NO_CHANGE result identity is invalid")
        elif self.apply is None:
            raise ValidationError("material command requires a mutation callback")


@dataclass(frozen=True, slots=True)
class CommandExecutionResult:
    result_type: str | None
    result_id: str | None
    replayed: bool
    no_change: bool


class CommandBoundary:
    def __init__(self, connection_factory: ConnectionFactory, audit_writer: AuditWriter) -> None:
        self._connection_factory = connection_factory
        self._audit_writer = audit_writer

    @staticmethod
    def _normalize_audit_emission(emission: AuditEmission | None, command_id: str) -> tuple[AuditEventInput, ...]:
        if emission is None:
            raise PersistenceFailure("material authoritative command did not produce required owner audit")
        events = (emission,) if isinstance(emission, AuditEventInput) else emission
        if not isinstance(events, tuple) or not events:
            raise PersistenceFailure("material authoritative command produced an invalid audit emission")
        seen_event_ids: set[str] = set()
        for event in events:
            if not isinstance(event, AuditEventInput):
                raise PersistenceFailure("material authoritative command produced an invalid audit event")
            if event.command_id != command_id:
                raise PersistenceFailure("audit event command_id does not match authoritative command")
            if event.audit_event_id in seen_event_ids:
                raise PersistenceFailure("authoritative command emitted duplicate audit event identities")
            seen_event_ids.add(event.audit_event_id)
        return events

    def execute(self, envelope: CommandEnvelope, prepare: PrepareMutation) -> CommandExecutionResult:
        request_hash = envelope.request_hash()
        with UnitOfWork(self._connection_factory) as uow:
            existing = uow.connection.execute(
                "SELECT command_type, request_hash, target_type, target_id, result_type, result_id "
                "FROM command_receipts WHERE command_id = ?",
                (envelope.command_id,),
            ).fetchone()
            if existing is not None:
                if (
                    str(existing[0]) != envelope.command_type
                    or str(existing[1]) != request_hash
                    or str(existing[2]) != envelope.target_type
                    or (existing[3] if existing[3] is None else str(existing[3])) != envelope.target_id
                ):
                    raise IdempotencyConflict()
                result_type = None if existing[4] is None else str(existing[4])
                result_id = None if existing[5] is None else str(existing[5])
                return CommandExecutionResult(
                    result_type=result_type,
                    result_id=result_id,
                    replayed=True,
                    no_change=result_type == "NO_CHANGE",
                )

            prepared = prepare(uow)
            prepared.validate()
            stored_result_type = "NO_CHANGE" if prepared.no_change else prepared.result_type
            uow.connection.execute(
                "INSERT INTO command_receipts("
                "command_id, command_type, request_hash, target_type, target_id, committed_at_utc, result_type, result_id"
                ") VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    envelope.command_id,
                    envelope.command_type,
                    request_hash,
                    envelope.target_type,
                    envelope.target_id,
                    utc_epoch_seconds(),
                    stored_result_type,
                    prepared.result_id,
                ),
            )

            if prepared.no_change:
                return CommandExecutionResult(
                    result_type="NO_CHANGE",
                    result_id=None,
                    replayed=False,
                    no_change=True,
                )

            assert prepared.apply is not None
            events = self._normalize_audit_emission(prepared.apply(uow), envelope.command_id)
            for event in events:
                self._audit_writer.write(uow, event)
            return CommandExecutionResult(
                result_type=prepared.result_type,
                result_id=prepared.result_id,
                replayed=False,
                no_change=False,
            )
