from __future__ import annotations

import json
from dataclasses import dataclass

from soma.foundation.errors import SomaError
from soma.foundation.identifiers import utc_epoch_seconds
from soma.foundation.persistence.uow import UnitOfWork

from .registry import AuditRegistry


@dataclass(frozen=True, slots=True)
class AuditResultRef:
    result_type: str
    result_id: str


@dataclass(frozen=True, slots=True)
class AuditEventInput:
    audit_event_id: str
    action_type: str
    action_version: int
    actor_kind: str
    target_type: str
    command_id: str
    payload_schema: str
    payload_version: int
    payload: dict[str, object]
    actor_id: str | None = None
    target_id: str | None = None
    reason_category: str | None = None
    correlation_id: str | None = None
    job_id: str | None = None
    import_run_id: str | None = None
    proposal_id: str | None = None
    batch_id: str | None = None
    resulting_event_refs: tuple[AuditResultRef, ...] = ()


class AuditWriter:
    def __init__(self, registry: AuditRegistry) -> None:
        self._registry = registry

    def write(self, uow: UnitOfWork, event: AuditEventInput) -> None:
        contract = self._registry.resolve(event.action_type, event.action_version)
        if contract.payload_schema != event.payload_schema or contract.payload_version != event.payload_version:
            raise SomaError("AUDIT_PAYLOAD_INVALID", "audit payload schema/version mismatch")
        if contract.allowed_reason_categories is not None:
            if event.reason_category not in contract.allowed_reason_categories:
                raise SomaError("AUDIT_PAYLOAD_INVALID", "audit reason category is not allowed")
        payload = contract.payload_contract.validate(event.payload)
        if contract.sensitivity_validator is not None:
            contract.sensitivity_validator(payload)
        try:
            payload_json = json.dumps(
                payload,
                ensure_ascii=False,
                allow_nan=False,
                separators=(",", ":"),
                sort_keys=True,
            )
        except (TypeError, ValueError) as exc:
            raise SomaError("AUDIT_PAYLOAD_INVALID", "audit payload cannot be serialized") from exc
        max_payload_bytes = contract.payload_contract.max_utf8_bytes
        if len(payload_json.encode("utf-8")) > max_payload_bytes:
            raise SomaError(
                "AUDIT_PAYLOAD_INVALID",
                f"audit payload exceeds its {max_payload_bytes}-byte action contract",
            )

        try:
            uow.connection.execute(
                "INSERT INTO audit_events("
                "audit_event_id, action_type, action_version, recorded_at_utc, actor_kind, actor_id, "
                "target_type, target_id, reason_category, command_id, correlation_id, job_id, import_run_id, "
                "proposal_id, batch_id, payload_schema, payload_version, payload_json"
                ") VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    event.audit_event_id,
                    event.action_type,
                    event.action_version,
                    utc_epoch_seconds(),
                    event.actor_kind,
                    event.actor_id,
                    event.target_type,
                    event.target_id,
                    event.reason_category,
                    event.command_id,
                    event.correlation_id,
                    event.job_id,
                    event.import_run_id,
                    event.proposal_id,
                    event.batch_id,
                    event.payload_schema,
                    event.payload_version,
                    payload_json,
                ),
            )
            for ordinal, ref in enumerate(
                sorted(event.resulting_event_refs, key=lambda value: (value.result_type, value.result_id))
            ):
                uow.connection.execute(
                    "INSERT INTO audit_event_results(audit_event_id, ordinal, result_type, result_id) "
                    "VALUES (?, ?, ?, ?)",
                    (event.audit_event_id, ordinal, ref.result_type, ref.result_id),
                )
        except SomaError:
            raise
        except BaseException as exc:
            text = str(exc).lower()
            if "unique" in text or "primary key" in text:
                raise SomaError("AUDIT_DUPLICATE_ID", "audit identity already exists") from exc
            raise SomaError("AUDIT_PERSISTENCE_FAILURE", "audit persistence failed") from exc
