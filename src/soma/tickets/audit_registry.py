from __future__ import annotations

from soma.foundation.audit.registry import AuditActionContract, AuditRegistry
from soma.foundation.strict_json import ObjectContract


def _payload(name: str, fields: set[str]) -> ObjectContract:
    return ObjectContract(
        name=name,
        version=1,
        required_fields=frozenset(fields),
        allowed_fields=frozenset(fields),
        max_depth=5,
        max_collection_items=64,
        max_utf8_bytes=16_384,
    )


def build_tickets_audit_registry() -> AuditRegistry:
    registry = AuditRegistry()
    definitions = [
        (
            "ticket.service_request.created",
            "ServiceRequestAuditV1",
            {"service_request_id", "resulting_revision", "identity_kind", "source_or_creation_class"},
        ),
        (
            "ticket.service_request.official_identity_attached",
            "ServiceRequestIdentityAuditV1",
            {"service_request_id", "prior_identity_kind", "official_sr_no_fingerprint", "resulting_revision", "review_context_id"},
        ),
        (
            "ticket.rfc.identity_created_or_adopted",
            "RfcIdentityAuditV1",
            {"rfc_id", "rfc_no", "creation_context", "customer_org_id", "resulting_revision"},
        ),
        (
            "ticket.rfc.customer_changed",
            "RfcCustomerAuditV1",
            {"rfc_id", "prior_customer_org_id", "new_customer_org_id", "resulting_revision", "reason_category", "review_fingerprint"},
        ),
        (
            "ticket.device_reference.created",
            "DeviceReferenceAuditV1",
            {"device_reference_id", "resulting_revision", "change_kind", "relationship_target_type", "relationship_target_id", "reason_category"},
        ),
        (
            "ticket.device_reference.corrected",
            "DeviceReferenceAuditV1",
            {"device_reference_id", "resulting_revision", "change_kind", "relationship_target_type", "relationship_target_id", "reason_category"},
        ),
    ]
    for action_type, payload_name, fields in definitions:
        registry.register(
            AuditActionContract(
                action_type=action_type,
                action_version=1,
                payload_schema=payload_name,
                payload_version=1,
                payload_contract=_payload(payload_name, fields),
            )
        )
    return registry
