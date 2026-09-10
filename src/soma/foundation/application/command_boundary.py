from __future__ import annotations

import hashlib
import re
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from soma.foundation.audit.writer import AuditEventInput, AuditWriter
from soma.foundation.errors import (
    IdempotencyConflict,
    IdempotencyResultUnavailable,
    IntegrityFailure,
    PersistenceFailure,
    ValidationError,
)
from soma.foundation.identifiers import require_uuid4, utc_epoch_seconds
from soma.foundation.persistence.connections import ConnectionFactory
from soma.foundation.persistence.uow import UnitOfWork
from soma.foundation.strict_json import (
    canonical_json_bytes_bounded,
    loads_canonical_json,
    sha256_canonical_json,
)

from .command_receipts import (
    CommandReceipt,
    CommandReceiptStore,
    CommittedCommandResult,
)

AuditEmission = AuditEventInput | tuple[AuditEventInput, ...]
ApplyMutation = Callable[[UnitOfWork], AuditEmission | None]
ResponseFactory = Callable[[UnitOfWork], Any]
PrepareMutation = Callable[[UnitOfWork], "PreparedMutation"]

_MAX_RESPONSE_JSON_BYTES = 524_288
_MAX_RESPONSE_DEPTH = 8
_MAX_RESPONSE_COLLECTION_ITEMS = 512
_DEFAULT_RESPONSE = object()


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
    response_schema: str = ""
    response_version: int = 1
    response: Any = field(default=_DEFAULT_RESPONSE, repr=False)
    response_factory: ResponseFactory | None = field(default=None, repr=False)
    after_audit: Callable[[UnitOfWork], None] | None = field(default=None, repr=False)

    def validate(self) -> None:
        if self.no_change:
            if self.apply is not None or self.after_audit is not None:
                raise ValidationError("NO_CHANGE command cannot contain a mutation callback")
            if self.result_type not in (None, "NO_CHANGE") or self.result_id is not None:
                raise ValidationError("NO_CHANGE result identity is invalid")
        elif self.apply is None:
            raise ValidationError("material command requires a mutation callback")
        if not isinstance(self.response_schema, str) or not self.response_schema:
            raise ValidationError("command response schema must be declared explicitly")
        if type(self.response_version) is not int or self.response_version <= 0:
            raise ValidationError("command response version must be a positive integer")
        if self.response_factory is not None and self.response is not _DEFAULT_RESPONSE:
            raise ValidationError("command response must use either a value or a response factory, not both")
        if self.response_factory is None and self.response is _DEFAULT_RESPONSE:
            raise ValidationError("command must declare an exact response value or same-UoW response factory")


@dataclass(frozen=True, slots=True)
class CommandExecutionResult:
    result_type: str | None
    result_id: str | None
    replayed: bool
    no_change: bool
    response_schema: str
    response_version: int
    response: Any


class CommandBoundary:
    def __init__(
        self,
        connection_factory: ConnectionFactory,
        audit_writer: AuditWriter,
        receipt_store: CommandReceiptStore | None = None,
    ) -> None:
        self._connection_factory = connection_factory
        self._audit_writer = audit_writer
        self._receipt_store = receipt_store or CommandReceiptStore()

    @staticmethod
    def _normalize_audit_emission(
        emission: AuditEmission | None,
        command_id: str,
    ) -> tuple[AuditEventInput, ...]:
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

    @staticmethod
    def _encode_response(response: Any) -> tuple[str, str, Any]:
        encoded = canonical_json_bytes_bounded(
            response,
            max_bytes=_MAX_RESPONSE_JSON_BYTES,
            max_depth=_MAX_RESPONSE_DEPTH,
            max_collection_items=_MAX_RESPONSE_COLLECTION_ITEMS,
        )
        text = encoded.decode("utf-8", errors="strict")
        normalized = loads_canonical_json(
            text,
            max_bytes=_MAX_RESPONSE_JSON_BYTES,
            max_depth=_MAX_RESPONSE_DEPTH,
            max_collection_items=_MAX_RESPONSE_COLLECTION_ITEMS,
        )
        return text, hashlib.sha256(encoded).hexdigest(), normalized

    @staticmethod
    def _decode_stored_response(result: CommittedCommandResult) -> Any:
        if (
            not result.response_schema
            or type(result.response_version) is not int
            or result.response_version <= 0
            or re.fullmatch(r"[0-9a-f]{64}", result.response_sha256) is None
        ):
            raise IntegrityFailure("committed command result metadata failed integrity validation")
        try:
            value = loads_canonical_json(
                result.response_json,
                max_bytes=_MAX_RESPONSE_JSON_BYTES,
                max_depth=_MAX_RESPONSE_DEPTH,
                max_collection_items=_MAX_RESPONSE_COLLECTION_ITEMS,
            )
            encoded = result.response_json.encode("utf-8", errors="strict")
        except (ValidationError, UnicodeError) as exc:
            raise IntegrityFailure("committed command result JSON failed integrity validation") from exc
        if hashlib.sha256(encoded).hexdigest() != result.response_sha256:
            raise IntegrityFailure("committed command result hash failed integrity validation")
        return value

    @staticmethod
    def _assert_replay_match(
        receipt: CommandReceipt,
        envelope: CommandEnvelope,
        request_hash: str,
    ) -> None:
        if (
            receipt.command_type != envelope.command_type
            or receipt.request_hash != request_hash
            or receipt.target_type != envelope.target_type
            or receipt.target_id != envelope.target_id
        ):
            raise IdempotencyConflict()

    def execute(
        self,
        envelope: CommandEnvelope,
        prepare: PrepareMutation,
    ) -> CommandExecutionResult:
        request_hash = envelope.request_hash()
        with UnitOfWork(self._connection_factory) as uow:
            existing = self._receipt_store.get(uow, envelope.command_id)
            if existing is not None:
                self._assert_replay_match(existing, envelope, request_hash)
                exact_result = self._receipt_store.get_exact_result(uow, envelope.command_id)
                if exact_result is None:
                    raise IdempotencyResultUnavailable()
                response = self._decode_stored_response(exact_result)
                return CommandExecutionResult(
                    result_type=existing.result_type,
                    result_id=existing.result_id,
                    replayed=True,
                    no_change=existing.result_type == "NO_CHANGE",
                    response_schema=exact_result.response_schema,
                    response_version=exact_result.response_version,
                    response=response,
                )

            prepared = prepare(uow)
            prepared.validate()
            stored_result_type = "NO_CHANGE" if prepared.no_change else prepared.result_type
            self._receipt_store.insert(
                uow,
                CommandReceipt(
                    command_id=envelope.command_id,
                    command_type=envelope.command_type,
                    request_hash=request_hash,
                    target_type=envelope.target_type,
                    target_id=envelope.target_id,
                    committed_at_utc=utc_epoch_seconds(),
                    result_type=stored_result_type,
                    result_id=prepared.result_id,
                ),
            )

            if not prepared.no_change:
                assert prepared.apply is not None
                events = self._normalize_audit_emission(prepared.apply(uow), envelope.command_id)
                for event in events:
                    self._audit_writer.write(uow, event)
                if prepared.after_audit is not None:
                    prepared.after_audit(uow)

            if prepared.response_factory is not None:
                semantic_response = prepared.response_factory(uow)
            elif prepared.response is _DEFAULT_RESPONSE:
                raise PersistenceFailure("validated command response snapshot unexpectedly disappeared")
            else:
                semantic_response = prepared.response

            response_json, response_sha256, normalized_response = self._encode_response(semantic_response)
            self._receipt_store.insert_exact_result(
                uow,
                CommittedCommandResult(
                    command_id=envelope.command_id,
                    response_schema=prepared.response_schema,
                    response_version=prepared.response_version,
                    response_json=response_json,
                    response_sha256=response_sha256,
                ),
            )
            return CommandExecutionResult(
                result_type=stored_result_type,
                result_id=prepared.result_id,
                replayed=False,
                no_change=prepared.no_change,
                response_schema=prepared.response_schema,
                response_version=prepared.response_version,
                response=normalized_response,
            )
