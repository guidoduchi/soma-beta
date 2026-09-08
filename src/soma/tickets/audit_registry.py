from __future__ import annotations

from soma.foundation.audit.registry import AuditActionContract, AuditRegistry
from soma.foundation.strict_json import ObjectContract


def _payload(name: str, fields: set[str], *, max_utf8_bytes: int = 16_384) -> ObjectContract:
    return ObjectContract(
        name=name,
        version=1,
        required_fields=frozenset(fields),
        allowed_fields=frozenset(fields),
        max_depth=5,
        max_collection_items=64,
        max_utf8_bytes=max_utf8_bytes,
    )


def build_tickets_audit_registry() -> AuditRegistry:
    registry = AuditRegistry()
    definitions = [
        (
            "ticket.service_request.created",
            "ServiceRequestAuditV1",
            {"service_request_id", "resulting_revision", "identity_kind", "source_or_creation_class"},
            16_384,
        ),
        (
            "ticket.service_request.official_identity_attached",
            "ServiceRequestIdentityAuditV1",
            {"service_request_id", "prior_identity_kind", "official_sr_no_fingerprint", "resulting_revision", "review_context_id"},
            16_384,
        ),
        (
            "ticket.rfc.identity_created_or_adopted",
            "RfcIdentityAuditV1",
            {"rfc_id", "rfc_no", "creation_context", "customer_org_id", "resulting_revision"},
            16_384,
        ),
        (
            "ticket.rfc.customer_changed",
            "RfcCustomerAuditV1",
            {"rfc_id", "prior_customer_org_id", "new_customer_org_id", "resulting_revision", "reason_category", "review_fingerprint"},
            16_384,
        ),
        (
            "ticket.rfc.hierarchy_changed",
            "RfcHierarchyAuditV1",
            {"rfc_id", "relationship_id", "prior_parent_rfc_id", "new_parent_rfc_id", "resulting_revision", "reason_category", "review_fingerprint"},
            16_384,
        ),
        (
            "ticket.sr_rfc_relationship.changed",
            "TicketRelationshipAuditV1",
            {"relationship_type", "relationship_id", "left_id", "right_id", "prior_state", "new_state", "reason_category", "subordinate_origin_rfc_id"},
            16_384,
        ),
        (
            "ticket.device_reference.created",
            "DeviceReferenceAuditV1",
            {"device_reference_id", "resulting_revision", "change_kind", "relationship_target_type", "relationship_target_id", "reason_category"},
            16_384,
        ),
        (
            "ticket.device_reference.corrected",
            "DeviceReferenceAuditV1",
            {"device_reference_id", "resulting_revision", "change_kind", "relationship_target_type", "relationship_target_id", "reason_category"},
            16_384,
        ),
        (
            "ticket.device_reference.relationship_changed",
            "TicketRelationshipAuditV1",
            {"relationship_type", "relationship_id", "left_id", "right_id", "prior_state", "new_state", "reason_category", "subordinate_origin_rfc_id"},
            16_384,
        ),
        (
            "ticket.working_note.added",
            "WorkingNoteAuditV1",
            {"working_note_id", "owner_type", "owner_id", "resulting_revision", "created_by_local_user_profile_id", "change_kind", "reason_category", "bounded_prior_or_new_body_when_required_by_removal_or_edit_policy"},
            524_288,
        ),
        (
            "ticket.working_note.edited",
            "WorkingNoteAuditV1",
            {"working_note_id", "owner_type", "owner_id", "resulting_revision", "created_by_local_user_profile_id", "change_kind", "reason_category", "bounded_prior_or_new_body_when_required_by_removal_or_edit_policy"},
            524_288,
        ),
        (
            "ticket.working_note.removed",
            "WorkingNoteAuditV1",
            {"working_note_id", "owner_type", "owner_id", "resulting_revision", "created_by_local_user_profile_id", "change_kind", "reason_category", "bounded_prior_or_new_body_when_required_by_removal_or_edit_policy"},
            524_288,
        ),
    ]
    for action_type, payload_name, fields, max_utf8_bytes in definitions:
        registry.register(
            AuditActionContract(
                action_type=action_type,
                action_version=1,
                payload_schema=payload_name,
                payload_version=1,
                payload_contract=_payload(payload_name, fields, max_utf8_bytes=max_utf8_bytes),
            )
        )
    return registry
