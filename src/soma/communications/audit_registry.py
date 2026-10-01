from __future__ import annotations

import json
from importlib.resources import files

from soma.foundation.audit.registry import AuditActionContract, AuditRegistry
from soma.foundation.audit.writer import AuditEventInput, AuditResultRef
from soma.foundation.identifiers import new_uuid4
from soma.foundation.strict_json import ObjectContract

_ACTIONS = json.loads(files("soma.communications.contracts").joinpath("registry.json").read_text(encoding="utf-8"))["leaves"]["audit/actions.json"]["actions"]


def build_communications_audit_registry() -> AuditRegistry:
    registry = AuditRegistry()
    for item in _ACTIONS:
        fields = frozenset(x.split(":", 1)[0] for x in item["payload_fields"])
        registry.register(AuditActionContract(
            item["action_type"], item["action_version"], item["payload_schema"], item["payload_version"],
            ObjectContract(item["payload_schema"], 1, fields, fields, max_utf8_bytes=4096),
        ))
    return registry


def audit_event(action: str, *, command_id: str, target_type: str, target_id: str,
                payload: dict, refs: tuple[AuditResultRef, ...] = (), actor_kind: str = "local_user", actor_id: str | None = None) -> AuditEventInput:
    item = next(x for x in _ACTIONS if x["action_type"] == action)
    return AuditEventInput(new_uuid4(), action, 1, actor_kind, target_type, command_id,
                           item["payload_schema"], 1, payload, actor_id=actor_id, target_id=target_id,
                           resulting_event_refs=refs)
