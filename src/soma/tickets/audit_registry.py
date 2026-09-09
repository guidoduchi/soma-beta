from __future__ import annotations

import re

from soma.foundation.audit.registry import AuditActionContract, AuditRegistry
from soma.foundation.errors import SomaError, ValidationError
from soma.foundation.identifiers import require_uuid4
from soma.foundation.strict_json import ObjectContract, canonical_json_bytes


_WORKING_NOTE_AUDIT_BODY_FIELD = "bounded_prior_or_new_body_when_required_by_removal_or_edit_policy"
_WORKING_NOTE_BODY_MAX_UTF8_BYTES = 65_536
_WORKING_NOTE_BODY_MAX_LINES = 512
_DEFAULT_AUDIT_MAX_UTF8_BYTES = 16_384
_WORKING_NOTE_EDIT_REMOVE_AUDIT_MAX_UTF8_BYTES = 524_288
_SHA256_HEX_RE = re.compile(r"[0-9a-f]{64}\Z")


def _payload(name: str, fields: set[str], *, max_utf8_bytes: int = _DEFAULT_AUDIT_MAX_UTF8_BYTES) -> ObjectContract:
    return ObjectContract(
        name=name,
        version=1,
        required_fields=frozenset(fields),
        allowed_fields=frozenset(fields),
        max_depth=5,
        max_collection_items=64,
        max_utf8_bytes=max_utf8_bytes,
    )


def _validate_working_note_edit_remove_audit(payload: dict[str, object]) -> None:
    body = payload.get(_WORKING_NOTE_AUDIT_BODY_FIELD)
    if not isinstance(body, str) or "\x00" in body:
        raise SomaError("AUDIT_PAYLOAD_INVALID", "Working Note audit body must be NUL-free text")
    try:
        body_bytes = body.encode("utf-8", errors="strict")
    except UnicodeEncodeError as exc:
        raise SomaError("AUDIT_PAYLOAD_INVALID", "Working Note audit body must be valid Unicode") from exc
    if len(body_bytes) > _WORKING_NOTE_BODY_MAX_UTF8_BYTES:
        raise SomaError("AUDIT_PAYLOAD_INVALID", "Working Note audit body exceeds its source body bound")
    if body.count("\n") + 1 > _WORKING_NOTE_BODY_MAX_LINES:
        raise SomaError("AUDIT_PAYLOAD_INVALID", "Working Note audit body exceeds its line bound")

    metadata_only = dict(payload)
    metadata_only[_WORKING_NOTE_AUDIT_BODY_FIELD] = None
    if len(canonical_json_bytes(metadata_only)) > _DEFAULT_AUDIT_MAX_UTF8_BYTES:
        raise SomaError("AUDIT_PAYLOAD_INVALID", "Working Note audit metadata exceeds the default audit bound")


def _validate_rfc_terminal_refresh_audit(payload: dict[str, object]) -> None:
    try:
        prior_id = require_uuid4(payload.get("prior_proposal_id"))
        replacement_id = require_uuid4(payload.get("replacement_proposal_id"))
    except ValidationError as exc:
        raise SomaError("AUDIT_PAYLOAD_INVALID", "RFC terminal refresh audit proposal identity is invalid") from exc
    if prior_id == replacement_id:
        raise SomaError("AUDIT_PAYLOAD_INVALID", "RFC terminal refresh audit replacement must use a new proposal identity")

    prior_revision = payload.get("prior_proposal_revision")
    resulting_prior_revision = payload.get("resulting_prior_proposal_revision")
    replacement_revision = payload.get("replacement_proposal_revision")
    if (
        type(prior_revision) is not int
        or prior_revision <= 0
        or type(resulting_prior_revision) is not int
        or resulting_prior_revision != prior_revision + 1
        or replacement_revision != 1
    ):
        raise SomaError("AUDIT_PAYLOAD_INVALID", "RFC terminal refresh audit revisions are invalid")

    if payload.get("state_transition") != "pending_to_superseded_with_replacement_pending":
        raise SomaError("AUDIT_PAYLOAD_INVALID", "RFC terminal refresh audit transition is invalid")
    epoch = payload.get("terminal_epoch_id")
    if not isinstance(epoch, str) or not epoch:
        raise SomaError("AUDIT_PAYLOAD_INVALID", "RFC terminal refresh audit epoch is invalid")
    if payload.get("prior_terminal_status_class") not in {"terminal_closed", "terminal_cancelled"}:
        raise SomaError("AUDIT_PAYLOAD_INVALID", "RFC terminal refresh prior status class is invalid")
    if payload.get("replacement_terminal_status_class") not in {"terminal_closed", "terminal_cancelled"}:
        raise SomaError("AUDIT_PAYLOAD_INVALID", "RFC terminal refresh replacement status class is invalid")
    for key in ("prior_terminal_status_evidence_id", "replacement_terminal_status_evidence_id"):
        value = payload.get(key)
        if not isinstance(value, str) or not value:
            raise SomaError("AUDIT_PAYLOAD_INVALID", "RFC terminal refresh audit evidence identity is invalid")
    for key in ("prior_scope_fingerprint", "replacement_scope_fingerprint"):
        value = payload.get(key)
        if not isinstance(value, str) or _SHA256_HEX_RE.fullmatch(value) is None:
            raise SomaError("AUDIT_PAYLOAD_INVALID", "RFC terminal refresh audit scope fingerprint is invalid")


def _validate_terminal_apply_result(
    value: object,
    *,
    field: str,
    expected_domain: str,
) -> None:
    if not isinstance(value, dict) or set(value) != {
        "domain",
        "result_ref_count",
        "audit_event_count",
        "result_fingerprint",
    }:
        raise SomaError("AUDIT_PAYLOAD_INVALID", f"{field} must be a fixed-shape participant apply summary")
    if value.get("domain") != expected_domain:
        raise SomaError("AUDIT_PAYLOAD_INVALID", f"{field} belongs to the wrong participant domain")
    for count_field in ("result_ref_count", "audit_event_count"):
        count = value.get(count_field)
        if type(count) is not int or count < 0:
            raise SomaError("AUDIT_PAYLOAD_INVALID", f"{field}.{count_field} must be a non-negative integer")
    fingerprint = value.get("result_fingerprint")
    if not isinstance(fingerprint, str) or _SHA256_HEX_RE.fullmatch(fingerprint) is None:
        raise SomaError("AUDIT_PAYLOAD_INVALID", f"{field}.result_fingerprint must be lowercase SHA-256")


def _validate_rfc_terminal_execute_audit(payload: dict[str, object]) -> None:
    try:
        require_uuid4(payload.get("proposal_id"))
    except ValidationError as exc:
        raise SomaError("AUDIT_PAYLOAD_INVALID", "RFC terminal execute audit proposal identity is invalid") from exc
    proposal_revision = payload.get("proposal_revision")
    if type(proposal_revision) is not int or proposal_revision <= 0:
        raise SomaError("AUDIT_PAYLOAD_INVALID", "RFC terminal execute audit proposal revision is invalid")
    epoch = payload.get("terminal_epoch_id")
    if not isinstance(epoch, str) or not epoch:
        raise SomaError("AUDIT_PAYLOAD_INVALID", "RFC terminal execute audit epoch is invalid")
    for key in ("scope_fingerprint", "reviewed_preview_fingerprint"):
        value = payload.get(key)
        if not isinstance(value, str) or _SHA256_HEX_RE.fullmatch(value) is None:
            raise SomaError("AUDIT_PAYLOAD_INVALID", "RFC terminal execute audit fingerprint is invalid")
    if payload.get("state_transition") != "pending_to_executed":
        raise SomaError("AUDIT_PAYLOAD_INVALID", "RFC terminal execute audit transition is invalid")
    _validate_terminal_apply_result(
        payload.get("task_objective_apply_result"),
        field="task_objective_apply_result",
        expected_domain="TASKS_OBJECTIVES",
    )
    _validate_terminal_apply_result(
        payload.get("communication_apply_result"),
        field="communication_apply_result",
        expected_domain="COMMUNICATIONS",
    )


def _validate_rfc_archive_audit(payload: dict[str, object]) -> None:
    try:
        require_uuid4(payload.get("rfc_archive_operation_id"))
    except ValidationError as exc:
        raise SomaError("AUDIT_PAYLOAD_INVALID", "RFC archive audit operation identity is invalid") from exc
    if payload.get("scope_kind") not in {"exact_rfc", "reviewed_branch"}:
        raise SomaError("AUDIT_PAYLOAD_INVALID", "RFC archive audit scope kind is invalid")
    fingerprint = payload.get("scope_fingerprint")
    if not isinstance(fingerprint, str) or _SHA256_HEX_RE.fullmatch(fingerprint) is None:
        raise SomaError("AUDIT_PAYLOAD_INVALID", "RFC archive audit scope fingerprint is invalid")
    changed_count = payload.get("changed_rfc_count")
    excluded_count = payload.get("excluded_prearchived_count")
    if type(changed_count) is not int or changed_count <= 0:
        raise SomaError("AUDIT_PAYLOAD_INVALID", "RFC archive audit changed count must be positive")
    if type(excluded_count) is not int or excluded_count < 0:
        raise SomaError("AUDIT_PAYLOAD_INVALID", "RFC archive audit excluded count must be non-negative")
    if payload.get("resulting_operation_state") not in {"archived", "restored"}:
        raise SomaError("AUDIT_PAYLOAD_INVALID", "RFC archive audit resulting state is invalid")
    reason = payload.get("reason_category")
    if reason is not None and (not isinstance(reason, str) or not reason):
        raise SomaError("AUDIT_PAYLOAD_INVALID", "RFC archive audit reason category is invalid")


def build_tickets_audit_registry() -> AuditRegistry:
    registry = AuditRegistry()
    definitions = [
        (
            "ticket.service_request.created",
            "ServiceRequestAuditV1",
            {"service_request_id", "resulting_revision", "identity_kind", "source_or_creation_class"},
            _DEFAULT_AUDIT_MAX_UTF8_BYTES,
            None,
        ),
        (
            "ticket.service_request.official_identity_attached",
            "ServiceRequestIdentityAuditV1",
            {"service_request_id", "prior_identity_kind", "official_sr_no_fingerprint", "resulting_revision", "review_context_id"},
            _DEFAULT_AUDIT_MAX_UTF8_BYTES,
            None,
        ),
        (
            "ticket.service_request.customer_changed",
            "ServiceRequestReferenceAuditV1",
            {"service_request_id", "reference_role", "prior_reference_id", "new_reference_id", "customer_org_context_id", "source_observation_id", "resulting_revision", "reason_category", "review_fingerprint"},
            _DEFAULT_AUDIT_MAX_UTF8_BYTES,
            None,
        ),
        (
            "ticket.service_request.contact_reference_changed",
            "ServiceRequestReferenceAuditV1",
            {"service_request_id", "reference_role", "prior_reference_id", "new_reference_id", "customer_org_context_id", "source_observation_id", "resulting_revision", "reason_category", "review_fingerprint"},
            _DEFAULT_AUDIT_MAX_UTF8_BYTES,
            None,
        ),
        (
            "ticket.rfc.identity_created_or_adopted",
            "RfcIdentityAuditV1",
            {"rfc_id", "rfc_no", "creation_context", "customer_org_id", "resulting_revision"},
            _DEFAULT_AUDIT_MAX_UTF8_BYTES,
            None,
        ),
        (
            "ticket.rfc.customer_changed",
            "RfcCustomerAuditV1",
            {"rfc_id", "prior_customer_org_id", "new_customer_org_id", "resulting_revision", "reason_category", "review_fingerprint"},
            _DEFAULT_AUDIT_MAX_UTF8_BYTES,
            None,
        ),
        (
            "ticket.rfc.hierarchy_changed",
            "RfcHierarchyAuditV1",
            {"rfc_id", "relationship_id", "prior_parent_rfc_id", "new_parent_rfc_id", "resulting_revision", "reason_category", "review_fingerprint"},
            _DEFAULT_AUDIT_MAX_UTF8_BYTES,
            None,
        ),
        (
            "ticket.sr_rfc_relationship.changed",
            "TicketRelationshipAuditV1",
            {"relationship_type", "relationship_id", "left_id", "right_id", "prior_state", "new_state", "reason_category", "subordinate_origin_rfc_id"},
            _DEFAULT_AUDIT_MAX_UTF8_BYTES,
            None,
        ),
        (
            "ticket.device_reference.created",
            "DeviceReferenceAuditV1",
            {"device_reference_id", "resulting_revision", "change_kind", "relationship_target_type", "relationship_target_id", "reason_category"},
            _DEFAULT_AUDIT_MAX_UTF8_BYTES,
            None,
        ),
        (
            "ticket.device_reference.corrected",
            "DeviceReferenceAuditV1",
            {"device_reference_id", "resulting_revision", "change_kind", "relationship_target_type", "relationship_target_id", "reason_category"},
            _DEFAULT_AUDIT_MAX_UTF8_BYTES,
            None,
        ),
        (
            "ticket.device_reference.relationship_changed",
            "TicketRelationshipAuditV1",
            {"relationship_type", "relationship_id", "left_id", "right_id", "prior_state", "new_state", "reason_category", "subordinate_origin_rfc_id"},
            _DEFAULT_AUDIT_MAX_UTF8_BYTES,
            None,
        ),
        (
            "ticket.rfc.source_projection_applied",
            "RfcSourceProjectionAuditV1",
            {"rfc_id", "prior_projection_revision", "resulting_projection_revision", "changed_field_keys", "source_evidence_ids", "status_class_before", "status_class_after", "terminal_epoch_id", "pending_cascade_proposal_id", "review_fingerprint"},
            _DEFAULT_AUDIT_MAX_UTF8_BYTES,
            None,
        ),
        (
            "ticket.rfc.archived",
            "RfcArchiveAuditV1",
            {"rfc_archive_operation_id", "scope_kind", "scope_fingerprint", "changed_rfc_count", "excluded_prearchived_count", "resulting_operation_state", "reason_category"},
            _DEFAULT_AUDIT_MAX_UTF8_BYTES,
            _validate_rfc_archive_audit,
        ),
        (
            "ticket.rfc.archive_restored",
            "RfcArchiveAuditV1",
            {"rfc_archive_operation_id", "scope_kind", "scope_fingerprint", "changed_rfc_count", "excluded_prearchived_count", "resulting_operation_state", "reason_category"},
            _DEFAULT_AUDIT_MAX_UTF8_BYTES,
            _validate_rfc_archive_audit,
        ),
        (
            "ticket.rfc.terminal_cascade_refreshed",
            "RfcTerminalCascadeRefreshAuditV1",
            {"prior_proposal_id", "prior_proposal_revision", "resulting_prior_proposal_revision", "replacement_proposal_id", "replacement_proposal_revision", "terminal_epoch_id", "prior_terminal_status_class", "replacement_terminal_status_class", "prior_terminal_status_evidence_id", "replacement_terminal_status_evidence_id", "prior_scope_fingerprint", "replacement_scope_fingerprint", "state_transition", "reason_category"},
            _DEFAULT_AUDIT_MAX_UTF8_BYTES,
            _validate_rfc_terminal_refresh_audit,
        ),
        (
            "ticket.rfc.terminal_cascade_executed",
            "RfcTerminalCascadeAuditV1",
            {"proposal_id", "proposal_revision", "terminal_epoch_id", "scope_fingerprint", "reviewed_preview_fingerprint", "state_transition", "task_objective_apply_result", "communication_apply_result", "reason_category"},
            _DEFAULT_AUDIT_MAX_UTF8_BYTES,
            _validate_rfc_terminal_execute_audit,
        ),
        (
            "ticket.rfc.hard_deleted",
            "RfcHardDeleteAuditV1",
            {"rfc_id", "rfc_no", "reviewed_revision", "eligibility_fingerprint", "confirmation_context_id", "result"},
            _DEFAULT_AUDIT_MAX_UTF8_BYTES,
            None,
        ),
        (
            "ticket.working_note.added",
            "WorkingNoteAuditV1",
            {"working_note_id", "owner_type", "owner_id", "resulting_revision", "created_by_local_user_profile_id", "change_kind", "reason_category", _WORKING_NOTE_AUDIT_BODY_FIELD},
            _DEFAULT_AUDIT_MAX_UTF8_BYTES,
            None,
        ),
        (
            "ticket.working_note.edited",
            "WorkingNoteAuditV1",
            {"working_note_id", "owner_type", "owner_id", "resulting_revision", "created_by_local_user_profile_id", "change_kind", "reason_category", _WORKING_NOTE_AUDIT_BODY_FIELD},
            _WORKING_NOTE_EDIT_REMOVE_AUDIT_MAX_UTF8_BYTES,
            _validate_working_note_edit_remove_audit,
        ),
        (
            "ticket.working_note.removed",
            "WorkingNoteAuditV1",
            {"working_note_id", "owner_type", "owner_id", "resulting_revision", "created_by_local_user_profile_id", "change_kind", "reason_category", _WORKING_NOTE_AUDIT_BODY_FIELD},
            _WORKING_NOTE_EDIT_REMOVE_AUDIT_MAX_UTF8_BYTES,
            _validate_working_note_edit_remove_audit,
        ),
    ]
    for action_type, payload_name, fields, max_utf8_bytes, sensitivity_validator in definitions:
        registry.register(
            AuditActionContract(
                action_type=action_type,
                action_version=1,
                payload_schema=payload_name,
                payload_version=1,
                payload_contract=_payload(payload_name, fields, max_utf8_bytes=max_utf8_bytes),
                sensitivity_validator=sensitivity_validator,
            )
        )
    return registry
