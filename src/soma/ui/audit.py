"""Metadata-only recoverable-state evidence; draft content is never audit data."""
import json
from importlib.resources import files

from soma.foundation.audit.registry import AuditActionContract, AuditRegistry
from soma.foundation.audit.writer import AuditEventInput, AuditResultRef
from soma.foundation.identifiers import new_uuid4
from soma.foundation.strict_json import ObjectContract

_ACTIONS = json.loads(files('soma.ui').joinpath('registry.json').read_text(encoding='utf8'))['leaves']['audit/actions.json']['actions']


def build_ui_audit_registry():
    registry = AuditRegistry()
    for item in _ACTIONS:
        fields = frozenset(item['payload_fields'])
        registry.register(AuditActionContract(item['action_type'], 1, item['payload_schema'], 1,
            ObjectContract(item['payload_schema'], 1, fields, fields, max_utf8_bytes=4096)))
    return registry


def event(action, *, command_id, target_type, target_id, payload, owner_profile_id=None, actor_kind='local_user'):
    contract = next(item for item in _ACTIONS if item['action_type'] == action)
    return AuditEventInput(new_uuid4(), action, 1, actor_kind, target_type, command_id, contract['payload_schema'], 1,
        payload, actor_id=owner_profile_id, target_id=target_id,
        resulting_event_refs=(AuditResultRef(target_type, target_id),))
