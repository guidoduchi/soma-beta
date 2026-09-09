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
_TASK_TERMINAL_RESULT_TYPES = frozenset({"task", "objective"})
_COMMUNICATION_TERMINAL_RESULT_TYPES = frozenset({"communication_link"})


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


def _validate_terminal_result_refs(
    value: object,
    *,
    field: str,
    allowed_types: frozenset[str],
) -> None:
    if not isinstance(value, list):
        raise SomaError("AUDIT_PAYLOAD_INVALID", f"{field} must be a bounded result-reference list")
    seen: set[tuple[str, str]] = set()
    for item in value:
        if not isinstance(item, dict) or set(item) != {"result_type", "result_id"}:
            raise SomaError("AUDIT_PAYLOAD_INVALID", f"{field} contains a malformed result reference")
        result_type = item.get("result_type")
        if result_type not in allowed_types:
            raise SomaError("AUDIT_PAYLOAD_INVALID", f"{field} contains an unauthorized result type")
        try:
            result_id = require_uuid4(item.get("result_id"))
        except ValidationError as exc:
            raise SomaError("AUDIT_PAYLOAD_INVALID", f"{field} contains an invalid result identity") from exc
        key = (str(result_type), result_id)
        if key in seen:
            raise SomaError("AUDIT_PAYLOAD_INVALID", f"{field} contains duplicate result references")
        seen.add(key)


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
    _validate_terminal_result_refs(
        payload.get("task_participant_result_refs"),
        field="task_participant_result_refs",
        allowed_types=_TASK_TERMINAL_RESULT_TYPES,
    )
    _validate_terminal_result_refs(
        payload.get("communication_participant_result_refs"),
        field="communication_participant_result_refs",
        allowed_types=_COMMUNICATION_TERMINAL_RESULT_TYPES,
    )


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
            {"rfc_archive_operation_id", "scope_kind", "scope_fingerprint", "changed_rfc_ids", "excluded_prearchived_count", "resulting_operation_state", "reason_category"},
            _DEFAULT_AUDIT_MAX_UTF8_BYTES,
            None,
        ),
        (
            "ticket.rfc.archive_restored",
            "RfcArchiveAuditV1",
            {"rfc_archive_operation_id", "scope_kind", "scope_fingerprint", "changed_rfc_ids", "excluded_prearchived_count", "resulting_operation_state", "reason_category"},
            _DEFAULT_AUDIT_MAX_UTF8_BYTES,
            None,
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
            {"proposal_id", "proposal_revision", "terminal_epoch_id", "scope_fingerprint", "reviewed_preview_fingerprint", "state_transition", "task_participant_result_refs", "communication_participant_result_refs", "reason_category"},
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
