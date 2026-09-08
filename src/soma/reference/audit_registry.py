from __future__ import annotations

from soma.foundation.audit.registry import AuditActionContract, AuditRegistry
from soma.foundation.strict_json import ObjectContract


def _payload(name: str, *, required: set[str], allowed: set[str]) -> ObjectContract:
    return ObjectContract(
        name=name,
        version=1,
        required_fields=frozenset(required),
        allowed_fields=frozenset(allowed),
        max_depth=5,
        max_collection_items=64,
        max_utf8_bytes=16_384,
    )


def build_reference_audit_registry() -> AuditRegistry:
    registry = AuditRegistry()
    definitions = [
        (
            "reference.customer_organization.created",
            "CustomerOrganizationAuditV1",
            {"customer_org_id", "new_revision", "account_code_claim_created", "reason_category"},
            set(),
        ),
        (
            "reference.customer_organization.descriptive_updated",
            "ReferenceDescriptiveAuditV1",
            {"target_type", "target_id", "prior_revision", "new_revision", "changed_fields", "lifecycle_event_id"},
            set(),
        ),
        (
            "reference.customer_account_code.set",
            "CustomerAccountCodeAuditV1",
            {"customer_org_id", "customer_org_identifier_id", "superseded_identifier_id", "prior_revision", "new_revision", "change_kind", "reason_category"},
            set(),
        ),
        (
            "reference.customer_account_code.shared_claim_confirmed",
            "CustomerAccountCodeReviewAuditV1",
            {"proposed_action", "review_snapshot_hash", "review_context_id", "from_customer_org_id", "to_customer_org_id", "changed_identifier_ids", "changed_customer_org_ids", "reason_category"},
            set(),
        ),
        (
            "reference.customer_account_code.reassigned",
            "CustomerAccountCodeReviewAuditV1",
            {"proposed_action", "review_snapshot_hash", "review_context_id", "from_customer_org_id", "to_customer_org_id", "changed_identifier_ids", "changed_customer_org_ids", "reason_category"},
            set(),
        ),
        (
            "reference.contact.created",
            "ContactAuditV1",
            {"contact_id", "new_revision", "initial_channel_id", "initial_affiliation_id"},
            set(),
        ),
        (
            "reference.contact.descriptive_updated",
            "ReferenceDescriptiveAuditV1",
            {"target_type", "target_id", "prior_revision", "new_revision", "changed_fields", "lifecycle_event_id"},
            set(),
        ),
        (
            "reference.contact_channel.added",
            "ContactChannelAuditV1",
            {"contact_id", "contact_channel_id", "channel_kind", "prior_channel_revision", "new_channel_revision", "prior_contact_revision", "new_contact_revision", "change_kind"},
            set(),
        ),
        (
            "reference.contact_channel.updated",
            "ContactChannelAuditV1",
            {"contact_id", "contact_channel_id", "channel_kind", "prior_channel_revision", "new_channel_revision", "prior_contact_revision", "new_contact_revision", "change_kind"},
            set(),
        ),
        (
            "reference.contact_channel.archived",
            "ContactChannelArchiveAuditV1",
            {"contact_id", "contact_channel_id", "prior_channel_revision", "new_channel_revision", "prior_contact_revision", "new_contact_revision", "reason_category"},
            set(),
        ),
        (
            "reference.contact_affiliation.changed",
            "ContactAffiliationAuditV1",
            {"contact_id", "prior_affiliation_id", "new_affiliation_id", "prior_customer_org_id", "new_customer_org_id", "prior_contact_revision", "new_contact_revision", "reason_category"},
            set(),
        ),
        (
            "reference.dispatch_location.created",
            "DispatchLocationAuditV1",
            {"dispatch_location_id", "address_mode", "new_revision", "lifecycle_event_id"},
            set(),
        ),
        (
            "reference.dispatch_location.descriptive_updated",
            "ReferenceDescriptiveAuditV1",
            {"target_type", "target_id", "prior_revision", "new_revision", "changed_fields", "lifecycle_event_id"},
            set(),
        ),
        (
            "reference.archived",
            "ReferenceLifecycleAuditV1",
            {"target_type", "target_id", "prior_state", "new_state", "prior_revision", "new_revision", "lifecycle_event_id", "reason_category"},
            set(),
        ),
        (
            "reference.reactivated",
            "ReferenceLifecycleAuditV1",
            {"target_type", "target_id", "prior_state", "new_state", "prior_revision", "new_revision", "lifecycle_event_id", "reason_category"},
            set(),
        ),
        (
            "setting.written",
            "SettingWriteAuditV1",
            {"setting_key", "contract_id", "contract_version", "prior_revision", "new_revision", "change_kind"},
            set(),
        ),
        (
            "local_user_profile.created",
            "LocalUserProfileAuditV1",
            {"local_user_profile_id", "metadata_revision"},
            set(),
        ),
        (
            "local_user_profile.display_name_updated",
            "LocalUserProfileDisplayNameAuditV1",
            {"local_user_profile_id", "prior_revision", "new_revision", "changed_field"},
            set(),
        ),
    ]
    for action_type, payload_name, required, optional in definitions:
        registry.register(
            AuditActionContract(
                action_type=action_type,
                action_version=1,
                payload_schema=payload_name,
                payload_version=1,
                payload_contract=_payload(
                    payload_name,
                    required=required,
                    allowed=required | optional,
                ),
            )
        )
    return registry
