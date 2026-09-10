from __future__ import annotations

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


def _validate_wfm_registered(payload: dict[str, object]) -> None:
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
        raise SomaError("AUDIT_PAYLOAD_INVALID", "WFM registration audit identity is invalid") from exc
    if payload.get("task_kind") != "wfm" or payload.get("creation_origin") != "wfm_manual":
        raise SomaError("AUDIT_PAYLOAD_INVALID", "WFM registration audit owner metadata is invalid")
    revision = payload.get("resulting_revision")
    if type(revision) is not int or revision != 1:
        raise SomaError("AUDIT_PAYLOAD_INVALID", "WFM registration audit revision must be one")
    if payload.get("reason_category") is not None:
        raise SomaError("AUDIT_PAYLOAD_INVALID", "WFM registration audit reason must be null")


def build_objectives_tasks_audit_registry() -> AuditRegistry:
    registry = AuditRegistry()
    registry.register(
        AuditActionContract(
            action_type="task.wfm_registered",
            action_version=1,
            payload_schema="TaskAuditV1",
            payload_version=1,
            payload_contract=ObjectContract(
                name="TaskAuditV1",
                version=1,
                required_fields=_TASK_AUDIT_FIELDS,
                allowed_fields=_TASK_AUDIT_FIELDS,
                max_depth=3,
                max_collection_items=16,
                max_utf8_bytes=16_384,
            ),
            sensitivity_validator=_validate_wfm_registered,
        )
    )
    return registry
