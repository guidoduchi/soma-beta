from __future__ import annotations

from soma.foundation.audit.registry import AuditActionContract, AuditRegistry
from soma.foundation.strict_json import ObjectContract


def build_ticket_import_audit_registry() -> AuditRegistry:
    registry = AuditRegistry()
    fields = frozenset(
        {
            "proposal_id",
            "proposal_kind",
            "decision",
            "proposal_revision",
            "reason_category",
            "owner_result_refs",
        }
    )
    registry.register(
        AuditActionContract(
            action_type="ticket_import.proposal_decided",
            action_version=1,
            payload_schema="ImportProposalDecisionAuditV1",
            payload_version=1,
            payload_contract=ObjectContract(
                name="ImportProposalDecisionAuditV1",
                version=1,
                required_fields=fields,
                allowed_fields=fields,
                max_depth=4,
                max_collection_items=32,
                max_utf8_bytes=16_384,
            ),
        )
    )
    return registry
