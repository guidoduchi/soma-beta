from soma.foundation.audit.registry import AuditActionContract, AuditRegistry
from soma.foundation.strict_json import ObjectContract
from soma.infrastructure.contracts.infrastructure import REGISTRY


def build_infrastructure_audit_registry() -> AuditRegistry:
    registry = AuditRegistry()
    spec = REGISTRY["audit"]
    required = frozenset(spec["payload_contract"]["required"])
    allowed = required | frozenset(spec["payload_contract"]["optional"])
    for action, _target in spec["actions"]:
        registry.register(AuditActionContract(
            action, 1, "INFRA_AUDIT_PAYLOAD_V1", 1,
            ObjectContract(name="INFRA_AUDIT_PAYLOAD_V1", version=1,
                           required_fields=required, allowed_fields=allowed,
                           max_utf8_bytes=16384),
        ))
    return registry
