from __future__ import annotations

import re

from soma.foundation.audit.registry import AuditActionContract, AuditRegistry
from soma.foundation.errors import SomaError, ValidationError
from soma.foundation.identifiers import require_uuid4
from soma.foundation.strict_json import ObjectContract


_TASK_AUDIT_FIELDS = frozenset(
    {
        "task_id",
        "task_kind",
        "creation_origin",
        "resulting_revision",
        "task_plan_revision_id",
        "reason_category",
    }
)
_HARD_DELETE_AUDIT_FIELDS = frozenset(
    {
        "target_type",
        "target_id",
        "reviewed_revision",
        "eligibility_fingerprint",
        "confirmation_context_id",
        "retained_related_ids",
        "result",
    }
)
_SHA256_RE = re.compile(r"[0-9a-f]{64}\Z")


def _validate_task_creation_payload(
    payload: dict[str, object],
    *,
    expected_kind: str,
    expected_origin: str,
) -> None:
    task_id = payload.get("task_id")
    plan_revision_id = payload.get("task_plan_revision_id")
    try:
        if not isinstance(task_id, str):
            raise ValidationError("task_id must be UUID text")
        require_uuid4(task_id)
        if plan_revision_id is not None:
            if not isinstance(plan_revision_id, str):
                raise ValidationError("task_plan_revision_id must be UUID text")
            require_uuid4(plan_revision_id)
    except ValidationError as exc:
        raise SomaError("AUDIT_PAYLOAD_INVALID", "Task creation audit identity is invalid") from exc
    if payload.get("task_kind") != expected_kind or payload.get("creation_origin") != expected_origin:
        raise SomaError("AUDIT_PAYLOAD_INVALID", "Task creation audit owner metadata is invalid")
    revision = payload.get("resulting_revision")
    if type(revision) is not int or revision != 1:
        raise SomaError("AUDIT_PAYLOAD_INVALID", "Task creation audit revision must be one")
    reason = payload.get("reason_category")
    if reason is not None and not isinstance(reason, str):
        raise SomaError("AUDIT_PAYLOAD_INVALID", "Task creation audit reason must be text or null")


def _validate_task_created(payload: dict[str, object]) -> None:
    _validate_task_creation_payload(payload, expected_kind="local", expected_origin="manual")


def _validate_wfm_registered(payload: dict[str, object]) -> None:
    _validate_task_creation_payload(payload, expected_kind="wfm", expected_origin="wfm_manual")
    if payload.get("reason_category") is not None:
        raise SomaError("AUDIT_PAYLOAD_INVALID", "WFM registration audit reason must be null")


def _validate_hard_delete(payload: dict[str, object]) -> None:
    if payload.get("target_type") != "task" or payload.get("result") != "deleted":
        raise SomaError("AUDIT_PAYLOAD_INVALID", "Task hard-delete audit target/result is invalid")
    target_id = payload.get("target_id")
    try:
        if not isinstance(target_id, str):
            raise ValidationError("target_id must be UUID text")
        require_uuid4(target_id)
    except ValidationError as exc:
        raise SomaError("AUDIT_PAYLOAD_INVALID", "Task hard-delete target identity is invalid") from exc
    revision = payload.get("reviewed_revision")
    if type(revision) is not int or revision <= 0:
        raise SomaError("AUDIT_PAYLOAD_INVALID", "Task hard-delete reviewed revision is invalid")
    fingerprint = payload.get("eligibility_fingerprint")
    if not isinstance(fingerprint, str) or _SHA256_RE.fullmatch(fingerprint) is None:
        raise SomaError("AUDIT_PAYLOAD_INVALID", "Task hard-delete eligibility fingerprint is invalid")
    confirmation = payload.get("confirmation_context_id")
    if confirmation is not None:
        if not isinstance(confirmation, str):
            raise SomaError("AUDIT_PAYLOAD_INVALID", "Task hard-delete confirmation context must be text or null")
        try:
            encoded = confirmation.encode("utf-8", errors="strict")
        except UnicodeEncodeError as exc:
            raise SomaError("AUDIT_PAYLOAD_INVALID", "Task hard-delete confirmation context is invalid Unicode") from exc
        if not encoded or len(encoded) > 1024 or "\x00" in confirmation or "\r" in confirmation or "\n" in confirmation:
            raise SomaError("AUDIT_PAYLOAD_INVALID", "Task hard-delete confirmation context violates its bound")
    retained = payload.get("retained_related_ids")
    if not isinstance(retained, list) or len(retained) > 32:
        raise SomaError("AUDIT_PAYLOAD_INVALID", "Task hard-delete retained-related list is invalid")
    seen: set[str] = set()
    for value in retained:
        try:
            if not isinstance(value, str):
                raise ValidationError("retained identity must be UUID text")
            require_uuid4(value)
        except ValidationError as exc:
            raise SomaError("AUDIT_PAYLOAD_INVALID", "Task hard-delete retained identity is invalid") from exc
        if value in seen:
            raise SomaError("AUDIT_PAYLOAD_INVALID", "Task hard-delete retained identities must be unique")
        seen.add(value)


def _contract(name: str, fields: frozenset[str], *, max_items: int = 32) -> ObjectContract:
    return ObjectContract(
        name=name,
        version=1,
        required_fields=fields,
        allowed_fields=fields,
        max_depth=4,
        max_collection_items=max_items,
        max_utf8_bytes=16_384,
    )


def build_objectives_tasks_audit_registry() -> AuditRegistry:
    registry = AuditRegistry()
    registry.register(
        AuditActionContract(
            action_type="task.created",
            action_version=1,
            payload_schema="TaskAuditV1",
            payload_version=1,
            payload_contract=_contract("TaskAuditV1", _TASK_AUDIT_FIELDS, max_items=16),
            sensitivity_validator=_validate_task_created,
        )
    )
    registry.register(
        AuditActionContract(
            action_type="task.wfm_registered",
            action_version=1,
            payload_schema="TaskAuditV1",
            payload_version=1,
            payload_contract=_contract("TaskAuditV1", _TASK_AUDIT_FIELDS, max_items=16),
            sensitivity_validator=_validate_wfm_registered,
        )
    )
    registry.register(
        AuditActionContract(
            action_type="task.hard_deleted",
            action_version=1,
            payload_schema="HardDeleteAuditV1",
            payload_version=1,
            payload_contract=_contract("HardDeleteAuditV1", _HARD_DELETE_AUDIT_FIELDS),
            sensitivity_validator=_validate_hard_delete,
        )
    )
    return registry
