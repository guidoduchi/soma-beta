from __future__ import annotations

import re

from soma.foundation.audit.registry import AuditActionContract, AuditRegistry
from soma.foundation.errors import SomaError, ValidationError
from soma.foundation.identifiers import require_uuid4
from soma.foundation.strict_json import ObjectContract

_SHA256 = re.compile(r"[0-9a-f]{64}\Z")
_NEED_EVENTS = frozenset(
    {
        "CREATE",
        "CONTRIBUTOR_ADDED",
        "PLANNED_QUANTITY_CHANGED",
        "RESOLVE",
        "CANCEL",
        "REACTIVATE",
        "HISTORY_REMOVE",
        "LOCAL_SELECTION",
    }
)


def _uuid(value: object, field: str, *, nullable: bool = False) -> None:
    if value is None and nullable:
        return
    try:
        if not isinstance(value, str):
            raise ValidationError(f"{field} must be UUID text")
        require_uuid4(value)
    except ValidationError as exc:
        raise SomaError("AUDIT_PAYLOAD_INVALID", f"{field} is invalid") from exc


def _fingerprint(value: object, field: str, *, nullable: bool = False) -> None:
    if value is None and nullable:
        return
    if not isinstance(value, str) or _SHA256.fullmatch(value) is None:
        raise SomaError("AUDIT_PAYLOAD_INVALID", f"{field} is invalid")


def _positive(value: object, field: str, *, nullable: bool = False) -> None:
    if value is None and nullable:
        return
    if type(value) is not int or value <= 0:
        raise SomaError("AUDIT_PAYLOAD_INVALID", f"{field} is invalid")


def _reason(value: object) -> None:
    if value is None:
        return
    if not isinstance(value, str) or not value or len(value.encode("utf-8", errors="strict")) > 384:
        raise SomaError("AUDIT_PAYLOAD_INVALID", "reason_category is invalid")


def _validate_identity(payload: dict[str, object]) -> None:
    if payload.get("entity_type") != "device_part_unit":
        raise SomaError("AUDIT_PAYLOAD_INVALID", "Inventory identity entity type is invalid")
    _uuid(payload.get("entity_id"), "entity_id")
    if payload.get("tracking_id") is not None:
        raise SomaError("AUDIT_PAYLOAD_INVALID", "Device Part Unit cannot carry tracking identity")
    if payload.get("origin") not in {
        "manual_fault_registration",
        "manual_component_registration",
        "reviewed_reconciliation",
    }:
        raise SomaError("AUDIT_PAYLOAD_INVALID", "Inventory identity origin is invalid")
    _positive(payload.get("resulting_revision"), "resulting_revision")
    _fingerprint(payload.get("bom_fingerprint"), "bom_fingerprint")
    _fingerprint(payload.get("serial_fingerprint"), "serial_fingerprint", nullable=True)


def _validate_need(payload: dict[str, object]) -> None:
    _uuid(payload.get("spare_need_id"), "spare_need_id")
    _uuid(payload.get("service_request_id"), "service_request_id")
    if payload.get("event_kind") not in _NEED_EVENTS:
        raise SomaError("AUDIT_PAYLOAD_INVALID", "Spare Need event kind is invalid")
    _positive(payload.get("planned_quantity"), "planned_quantity", nullable=True)
    _uuid(payload.get("contributor_id"), "contributor_id", nullable=True)
    _positive(payload.get("resulting_revision"), "resulting_revision")
    _reason(payload.get("reason_category"))



_SPARE_UNIT_EVENTS = frozenset({
    "REGISTER",
    "RESERVE",
    "RELEASE",
    "REASSIGN",
    "LOCAL_SELECTION",
    "PROVENANCE_ATTACH",
})
_LSU = re.compile(r"LSU-[0-9]{8}\Z")


def _validate_spare_unit(payload: dict[str, object]) -> None:
    _uuid(payload.get("spare_part_unit_id"), "spare_part_unit_id")
    if payload.get("event_kind") not in _SPARE_UNIT_EVENTS:
        raise SomaError("AUDIT_PAYLOAD_INVALID", "Spare Part Unit event kind is invalid")
    tracking_id = payload.get("local_tracking_id")
    if tracking_id is not None and (
        not isinstance(tracking_id, str) or _LSU.fullmatch(tracking_id) is None
    ):
        raise SomaError("AUDIT_PAYLOAD_INVALID", "local_tracking_id is invalid")
    _uuid(payload.get("task_id"), "task_id", nullable=True)
    _uuid(payload.get("allocation_id"), "allocation_id", nullable=True)
    _uuid(payload.get("spare_need_id"), "spare_need_id", nullable=True)
    _positive(payload.get("resulting_unit_revision"), "resulting_unit_revision")
    _positive(payload.get("allocation_revision"), "allocation_revision", nullable=True)
    _fingerprint(payload.get("bom_fingerprint"), "bom_fingerprint", nullable=True)
    _reason(payload.get("reason_category"))



_SPR = re.compile(r"SPR-[0-9]{8}\Z")
_SR7 = re.compile(r"SR[0-9]{7}\Z")
_SPARE_REQUEST_EVENTS = frozenset({"CREATE", "DRAFT_UPDATE", "TERMINAL"})


def _validate_spare_request(payload: dict[str, object]) -> None:
    _uuid(payload.get("spare_request_id"), "spare_request_id")
    _uuid(payload.get("requester_contact_id"), "requester_contact_id")
    tracking_id = payload.get("tracking_id")
    if not isinstance(tracking_id, str) or _SPR.fullmatch(tracking_id) is None:
        raise SomaError("AUDIT_PAYLOAD_INVALID", "tracking_id is invalid")
    if payload.get("event_kind") not in _SPARE_REQUEST_EVENTS:
        raise SomaError("AUDIT_PAYLOAD_INVALID", "Spare Request event kind is invalid")
    _positive(payload.get("allocation_count"), "allocation_count")
    _positive(payload.get("resulting_revision"), "resulting_revision")
    _fingerprint(payload.get("requester_context_fingerprint"), "requester_context_fingerprint")
    _reason(payload.get("reason_category"))


def _validate_spare_request_identity(payload: dict[str, object]) -> None:
    _uuid(payload.get("spare_request_id"), "spare_request_id")
    if payload.get("event_kind") not in {"ASSIGN", "CORRECT"}:
        raise SomaError("AUDIT_PAYLOAD_INVALID", "Spare Request identity event is invalid")
    current = payload.get("current_sr7")
    former = payload.get("former_sr7")
    if not isinstance(current, str) or _SR7.fullmatch(current) is None:
        raise SomaError("AUDIT_PAYLOAD_INVALID", "current_sr7 is invalid")
    if former is not None and (
        not isinstance(former, str) or _SR7.fullmatch(former) is None
    ):
        raise SomaError("AUDIT_PAYLOAD_INVALID", "former_sr7 is invalid")
    _positive(payload.get("resulting_revision"), "resulting_revision")
    _reason(payload.get("reason_category"))


def _validate_spare_request_submission(payload: dict[str, object]) -> None:
    _uuid(payload.get("spare_request_id"), "spare_request_id")
    _uuid(payload.get("submission_event_id"), "submission_event_id")
    _uuid(payload.get("submission_snapshot_id"), "submission_snapshot_id")
    if payload.get("event_kind") not in {"ACCEPT", "CORRECT_FALSE"}:
        raise SomaError("AUDIT_PAYLOAD_INVALID", "Spare Request submission event is invalid")
    _positive(payload.get("allocation_count"), "allocation_count")
    _fingerprint(payload.get("input_fingerprint"), "input_fingerprint")
    effective = payload.get("effective_at_utc")
    if effective is not None and (type(effective) is not int or effective < 0):
        raise SomaError("AUDIT_PAYLOAD_INVALID", "effective_at_utc is invalid")


def _validate_rma(payload: dict[str, object]) -> None:
    _uuid(payload.get("spare_request_id"), "spare_request_id")
    _uuid(payload.get("authorization_batch_id"), "authorization_batch_id", nullable=True)
    _uuid(payload.get("rma_id"), "rma_id")
    if payload.get("event_kind") not in {
        "AUTHORIZE", "ASSIGN", "REASSIGN", "CLEAR", "C10_CORRECT"
    }:
        raise SomaError("AUDIT_PAYLOAD_INVALID", "RMA audit event kind is invalid")
    c10 = payload.get("current_c10")
    if not isinstance(c10, str) or re.fullmatch(r"C[0-9]{10}", c10) is None:
        raise SomaError("AUDIT_PAYLOAD_INVALID", "current_c10 is invalid")
    _uuid(payload.get("target_device_part_unit_id"), "target_device_part_unit_id", nullable=True)
    _positive(payload.get("resulting_revision"), "resulting_revision")


def _validate_rma_receipt(payload: dict[str, object]) -> None:
    _uuid(payload.get("rma_id"), "rma_id")
    _uuid(payload.get("spare_part_unit_id"), "spare_part_unit_id")
    _uuid(payload.get("receipt_event_id"), "receipt_event_id")
    _uuid(payload.get("logistics_event_id"), "logistics_event_id")
    _fingerprint(payload.get("actual_bom_fingerprint"), "actual_bom_fingerprint")
    _fingerprint(payload.get("actual_serial_fingerprint"), "actual_serial_fingerprint", nullable=True)
    effective = payload.get("effective_at_utc")
    if effective is not None and (type(effective) is not int or effective < 0):
        raise SomaError("AUDIT_PAYLOAD_INVALID", "effective_at_utc is invalid")


def _validate_logistics(payload: dict[str, object]) -> None:
    _uuid(payload.get("logistics_event_id"), "logistics_event_id")
    event_kind = payload.get("event_kind")
    if event_kind not in {
        "dispatch",
        "pickup",
        "delivery",
        "receipt",
        "custody_change",
        "location_change",
        "return_pickup",
        "warehouse_delivery",
        "correction",
    }:
        raise SomaError("AUDIT_PAYLOAD_INVALID", "logistics event kind is invalid")
    effective = payload.get("effective_at_utc")
    if effective is not None and (type(effective) is not int or effective < 0):
        raise SomaError("AUDIT_PAYLOAD_INVALID", "effective_at_utc is invalid")
    _positive(payload.get("participant_count"), "participant_count")
    _uuid(
        payload.get("corrected_participant_id"),
        "corrected_participant_id",
        nullable=True,
    )
    _positive(payload.get("resulting_revision"), "resulting_revision")


def _validate_physical_consequence(payload: dict[str, object]) -> None:
    _uuid(payload.get("physical_consequence_id"), "physical_consequence_id")
    _uuid(payload.get("task_id"), "task_id")
    _fingerprint(payload.get("task_review_fingerprint"), "task_review_fingerprint")
    if payload.get("event_kind") not in {"ACCEPT", "CORRECT", "SUPERSEDE"}:
        raise SomaError("AUDIT_PAYLOAD_INVALID", "physical consequence event kind is invalid")
    if payload.get("disposition") not in {
        "installed_used",
        "unused",
        "inbound_faulty",
        "incompatible",
        "dismantled",
        "removed_only",
        "no_physical_change",
        "other_reviewed",
    }:
        raise SomaError("AUDIT_PAYLOAD_INVALID", "physical consequence disposition is invalid")
    _uuid(payload.get("return_obligation_id"), "return_obligation_id", nullable=True)
    _positive(payload.get("resulting_revision"), "resulting_revision")


_FT = re.compile(r"FT-[0-9]{8}\Z")


def _validate_fault_tag(payload: dict[str, object]) -> None:
    _uuid(payload.get("fault_tag_id"), "fault_tag_id")
    tracking_id = payload.get("tracking_id")
    if not isinstance(tracking_id, str) or _FT.fullmatch(tracking_id) is None:
        raise SomaError("AUDIT_PAYLOAD_INVALID", "Fault Tag tracking_id is invalid")
    if payload.get("event_kind") not in {"CREATE", "DRAFT_UPDATE", "ARCHIVE", "RESTORE"}:
        raise SomaError("AUDIT_PAYLOAD_INVALID", "Fault Tag event kind is invalid")
    member_count = payload.get("member_count")
    if type(member_count) is not int or member_count < 0:
        raise SomaError("AUDIT_PAYLOAD_INVALID", "Fault Tag member_count is invalid")
    _positive(payload.get("resulting_revision"), "resulting_revision")
    _reason(payload.get("reason_category"))


def _validate_fault_tag_submission(payload: dict[str, object]) -> None:
    _uuid(payload.get("fault_tag_id"), "fault_tag_id")
    _uuid(payload.get("submission_event_id"), "submission_event_id")
    _uuid(payload.get("submission_snapshot_id"), "submission_snapshot_id")
    if payload.get("event_kind") not in {"ACCEPT", "CORRECT_FALSE"}:
        raise SomaError("AUDIT_PAYLOAD_INVALID", "Fault Tag submission event kind is invalid")
    count = payload.get("membership_count")
    if type(count) is not int or count < 0:
        raise SomaError("AUDIT_PAYLOAD_INVALID", "Fault Tag membership_count is invalid")
    _fingerprint(payload.get("input_fingerprint"), "input_fingerprint")
    effective = payload.get("effective_at_utc")
    if effective is not None and (type(effective) is not int or effective < 0):
        raise SomaError("AUDIT_PAYLOAD_INVALID", "Fault Tag effective_at_utc is invalid")


def _validate_warehouse_decision(payload: dict[str, object]) -> None:
    _uuid(payload.get("membership_id"), "membership_id")
    if payload.get("event_kind") not in {"RECEIVED", "ACCEPTED", "REJECTED"}:
        raise SomaError("AUDIT_PAYLOAD_INVALID", "warehouse event_kind is invalid")
    _uuid(payload.get("rma_id"), "rma_id")
    _uuid(payload.get("return_obligation_id"), "return_obligation_id")
    _uuid(payload.get("batch_id"), "batch_id", nullable=True)
    effective = payload.get("effective_at_utc")
    if effective is not None and (type(effective) is not int or effective < 0):
        raise SomaError("AUDIT_PAYLOAD_INVALID", "warehouse effective_at_utc is invalid")
    if payload.get("explicit_confirmation") is not True:
        raise SomaError("AUDIT_PAYLOAD_INVALID", "warehouse explicit confirmation is invalid")


def _validate_fault_tag_lineage(payload: dict[str, object]) -> None:
    _uuid(payload.get("predecessor_fault_tag_id"), "predecessor_fault_tag_id")
    _uuid(payload.get("successor_fault_tag_id"), "successor_fault_tag_id")
    if payload.get("lineage_kind") not in {"CORRECTS_REPLACES", "RESEND_OF"}:
        raise SomaError("AUDIT_PAYLOAD_INVALID", "Fault Tag lineage kind is invalid")
    _fingerprint(
        payload.get("membership_scope_fingerprint"),
        "membership_scope_fingerprint",
    )
    _reason(payload.get("reason_category"))
    _positive(payload.get("resulting_revision"), "resulting_revision")



def _validate_inventory_proposal(payload: dict[str, object]) -> None:
    _uuid(payload.get("proposal_id"), "proposal_id")
    if payload.get("decision") not in {"ACCEPT", "REJECT"}:
        raise SomaError("AUDIT_PAYLOAD_INVALID", "proposal decision is invalid")
    _fingerprint(payload.get("input_fingerprint"), "input_fingerprint")
    accepted = payload.get("accepted_target_count")
    rejected = payload.get("deferred_or_rejected_count")
    if type(accepted) is not int or accepted < 0:
        raise SomaError("AUDIT_PAYLOAD_INVALID", "accepted_target_count is invalid")
    if type(rejected) is not int or rejected < 0:
        raise SomaError("AUDIT_PAYLOAD_INVALID", "deferred_or_rejected_count is invalid")
    source_ref = payload.get("source_evidence_ref")
    if (
        not isinstance(source_ref, str)
        or not source_ref
        or len(source_ref.encode("utf-8", errors="strict")) > 768
        or "\x00" in source_ref
        or "\r" in source_ref
        or "\n" in source_ref
    ):
        raise SomaError("AUDIT_PAYLOAD_INVALID", "source_evidence_ref is invalid")
    _reason(payload.get("reason_category"))

def _validate_inventory_hard_delete(payload: dict[str, object]) -> None:
    if payload.get("target_type") not in {
        "spare_need", "spare_request", "spare_part_unit", "fault_tag"
    }:
        raise SomaError("AUDIT_PAYLOAD_INVALID", "hard-delete target_type is invalid")
    _uuid(payload.get("target_id"), "target_id")
    _positive(payload.get("reviewed_revision"), "reviewed_revision")
    _fingerprint(payload.get("eligibility_fingerprint"), "eligibility_fingerprint")
    related = payload.get("retained_related_ids")
    if not isinstance(related, list) or len(related) > 256:
        raise SomaError("AUDIT_PAYLOAD_INVALID", "retained_related_ids is invalid")
    for identity in related:
        _uuid(identity, "retained_related_id")
    if payload.get("result") != "DELETED":
        raise SomaError("AUDIT_PAYLOAD_INVALID", "hard-delete result is invalid")


def _validate_inventory_bulk(payload: dict[str, object]) -> None:
    _uuid(payload.get("batch_id"), "batch_id")
    if payload.get("action_kind") not in {
        "warehouse_receipt", "warehouse_accept", "warehouse_reject"
    }:
        raise SomaError("AUDIT_PAYLOAD_INVALID", "bulk action_kind is invalid")
    _fingerprint(payload.get("input_fingerprint"), "input_fingerprint")
    target_count = payload.get("target_count")
    if type(target_count) is not int or not 1 <= target_count <= 200:
        raise SomaError("AUDIT_PAYLOAD_INVALID", "bulk target_count is invalid")
    refs = payload.get("result_refs")
    if not isinstance(refs, list) or len(refs) != target_count:
        raise SomaError("AUDIT_PAYLOAD_INVALID", "bulk result_refs are invalid")
    for ref in refs:
        if (
            not isinstance(ref, dict)
            or set(ref) != {"type", "id"}
            or ref.get("type") != "fault_tag_membership_event"
        ):
            raise SomaError("AUDIT_PAYLOAD_INVALID", "bulk result ref is invalid")
        _uuid(ref.get("id"), "bulk_result_id")
    if payload.get("result") != "APPLIED":
        raise SomaError("AUDIT_PAYLOAD_INVALID", "bulk result is invalid")


_CORRECTION_KINDS = frozenset(
    {
        "false_spare_request_submission",
        "rma_identifier_alias",
        "logistics_participant_relationship",
        "spare_part_rma_provenance",
        "false_fault_tag_submission",
        "physical_consequence",
    }
)


def _validate_inventory_correction(payload: dict[str, object]) -> None:
    if payload.get("correction_kind") not in _CORRECTION_KINDS:
        raise SomaError("AUDIT_PAYLOAD_INVALID", "correction_kind is invalid")
    _uuid(payload.get("target_id"), "target_id")
    _uuid(payload.get("target_event_id"), "target_event_id", nullable=True)
    _reason(payload.get("reason_category"))
    if payload.get("result_kind") not in {"inventory_event", "inventory_relationship"}:
        raise SomaError("AUDIT_PAYLOAD_INVALID", "correction result_kind is invalid")
    _uuid(payload.get("result_id"), "result_id")

def _contract(name: str, fields: frozenset[str]) -> ObjectContract:
    return ObjectContract(
        name=name,
        version=1,
        required_fields=fields,
        allowed_fields=fields,
        max_depth=3,
        max_collection_items=16,
        max_utf8_bytes=16_384,
    )


def build_inventory_audit_registry() -> AuditRegistry:
    registry = AuditRegistry()
    registry.register(
        AuditActionContract(
            action_type="inventory.device_part.registered",
            action_version=1,
            payload_schema="InventoryIdentityAuditV1",
            payload_version=1,
            payload_contract=_contract(
                "InventoryIdentityAuditV1",
                frozenset(
                    {
                        "entity_type",
                        "entity_id",
                        "tracking_id",
                        "origin",
                        "resulting_revision",
                        "bom_fingerprint",
                        "serial_fingerprint",
                    }
                ),
            ),
            sensitivity_validator=_validate_identity,
        )
    )
    registry.register(
        AuditActionContract(
            action_type="inventory.spare_need.changed",
            action_version=1,
            payload_schema="SpareNeedAuditV1",
            payload_version=1,
            payload_contract=_contract(
                "SpareNeedAuditV1",
                frozenset(
                    {
                        "spare_need_id",
                        "service_request_id",
                        "event_kind",
                        "planned_quantity",
                        "contributor_id",
                        "resulting_revision",
                        "reason_category",
                    }
                ),
            ),
            sensitivity_validator=_validate_need,
        )
    )
    registry.register(
        AuditActionContract(
            action_type="inventory.spare_unit.registered_or_reserved",
            action_version=1,
            payload_schema="SpareUnitAuditV1",
            payload_version=1,
            payload_contract=_contract(
                "SpareUnitAuditV1",
                frozenset(
                    {
                        "spare_part_unit_id",
                        "event_kind",
                        "local_tracking_id",
                        "task_id",
                        "allocation_id",
                        "spare_need_id",
                        "resulting_unit_revision",
                        "allocation_revision",
                        "bom_fingerprint",
                        "reason_category",
                    }
                ),
            ),
            sensitivity_validator=_validate_spare_unit,
        )
    )
    registry.register(
        AuditActionContract(
            action_type="inventory.spare_request.draft_changed",
            action_version=1,
            payload_schema="SpareRequestAuditV1",
            payload_version=1,
            payload_contract=_contract(
                "SpareRequestAuditV1",
                frozenset(
                    {
                        "spare_request_id",
                        "tracking_id",
                        "event_kind",
                        "requester_contact_id",
                        "requester_context_fingerprint",
                        "resulting_revision",
                        "allocation_count",
                        "reason_category",
                    }
                ),
            ),
            sensitivity_validator=_validate_spare_request,
        )
    )
    registry.register(
        AuditActionContract(
            action_type="inventory.spare_request.submitted",
            action_version=1,
            payload_schema="SpareRequestSubmissionAuditV1",
            payload_version=1,
            payload_contract=_contract(
                "SpareRequestSubmissionAuditV1",
                frozenset(
                    {
                        "spare_request_id",
                        "submission_event_id",
                        "submission_snapshot_id",
                        "event_kind",
                        "allocation_count",
                        "input_fingerprint",
                        "effective_at_utc",
                    }
                ),
            ),
            sensitivity_validator=_validate_spare_request_submission,
        )
    )
    registry.register(
        AuditActionContract(
            action_type="inventory.spare_request.official_id_changed",
            action_version=1,
            payload_schema="SpareRequestIdentityAuditV1",
            payload_version=1,
            payload_contract=_contract(
                "SpareRequestIdentityAuditV1",
                frozenset(
                    {
                        "spare_request_id",
                        "event_kind",
                        "current_sr7",
                        "former_sr7",
                        "resulting_revision",
                        "reason_category",
                    }
                ),
            ),
            sensitivity_validator=_validate_spare_request_identity,
        )
    )
    registry.register(
        AuditActionContract(
            action_type="inventory.rma.authorized_or_assigned",
            action_version=1,
            payload_schema="RmaAuditV1",
            payload_version=1,
            payload_contract=_contract(
                "RmaAuditV1",
                frozenset(
                    {
                        "spare_request_id",
                        "authorization_batch_id",
                        "rma_id",
                        "event_kind",
                        "current_c10",
                        "target_device_part_unit_id",
                        "resulting_revision",
                    }
                ),
            ),
            sensitivity_validator=_validate_rma,
        )
    )
    registry.register(
        AuditActionContract(
            action_type="inventory.rma.inbound_received",
            action_version=1,
            payload_schema="RmaReceiptAuditV1",
            payload_version=1,
            payload_contract=_contract(
                "RmaReceiptAuditV1",
                frozenset(
                    {
                        "rma_id",
                        "spare_part_unit_id",
                        "receipt_event_id",
                        "logistics_event_id",
                        "actual_bom_fingerprint",
                        "actual_serial_fingerprint",
                        "effective_at_utc",
                    }
                ),
            ),
            sensitivity_validator=_validate_rma_receipt,
        )
    )
    registry.register(
        AuditActionContract(
            action_type="inventory.logistics.recorded_or_corrected",
            action_version=1,
            payload_schema="LogisticsAuditV1",
            payload_version=1,
            payload_contract=_contract(
                "LogisticsAuditV1",
                frozenset(
                    {
                        "logistics_event_id",
                        "event_kind",
                        "effective_at_utc",
                        "participant_count",
                        "corrected_participant_id",
                        "resulting_revision",
                    }
                ),
            ),
            sensitivity_validator=_validate_logistics,
        )
    )
    registry.register(
        AuditActionContract(
            action_type="inventory.task_physical_consequence.accepted_or_corrected",
            action_version=1,
            payload_schema="PhysicalConsequenceAuditV1",
            payload_version=1,
            payload_contract=_contract(
                "PhysicalConsequenceAuditV1",
                frozenset(
                    {
                        "physical_consequence_id",
                        "task_id",
                        "task_review_fingerprint",
                        "event_kind",
                        "disposition",
                        "return_obligation_id",
                        "resulting_revision",
                    }
                ),
            ),
            sensitivity_validator=_validate_physical_consequence,
        )
    )
    registry.register(
        AuditActionContract(
            action_type="inventory.fault_tag.draft_changed",
            action_version=1,
            payload_schema="FaultTagAuditV1",
            payload_version=1,
            payload_contract=_contract(
                "FaultTagAuditV1",
                frozenset(
                    {
                        "fault_tag_id",
                        "tracking_id",
                        "event_kind",
                        "member_count",
                        "resulting_revision",
                        "reason_category",
                    }
                ),
            ),
            sensitivity_validator=_validate_fault_tag,
        )
    )
    registry.register(
        AuditActionContract(
            action_type="inventory.fault_tag.submitted",
            action_version=1,
            payload_schema="FaultTagSubmissionAuditV1",
            payload_version=1,
            payload_contract=_contract(
                "FaultTagSubmissionAuditV1",
                frozenset(
                    {
                        "fault_tag_id",
                        "submission_event_id",
                        "submission_snapshot_id",
                        "event_kind",
                        "membership_count",
                        "input_fingerprint",
                        "effective_at_utc",
                    }
                ),
            ),
            sensitivity_validator=_validate_fault_tag_submission,
        )
    )
    registry.register(
        AuditActionContract(
            action_type="inventory.fault_tag.warehouse_state_changed",
            action_version=1,
            payload_schema="WarehouseDecisionAuditV1",
            payload_version=1,
            payload_contract=_contract(
                "WarehouseDecisionAuditV1",
                frozenset(
                    {
                        "membership_id",
                        "event_kind",
                        "rma_id",
                        "return_obligation_id",
                        "batch_id",
                        "effective_at_utc",
                        "explicit_confirmation",
                    }
                ),
            ),
            sensitivity_validator=_validate_warehouse_decision,
        )
    )
    registry.register(
        AuditActionContract(
            action_type="inventory.fault_tag.replacement_or_resend_created",
            action_version=1,
            payload_schema="FaultTagLineageAuditV1",
            payload_version=1,
            payload_contract=_contract(
                "FaultTagLineageAuditV1",
                frozenset(
                    {
                        "predecessor_fault_tag_id",
                        "successor_fault_tag_id",
                        "lineage_kind",
                        "membership_scope_fingerprint",
                        "reason_category",
                        "resulting_revision",
                    }
                ),
            ),
            sensitivity_validator=_validate_fault_tag_lineage,
        )
    )
    registry.register(
        AuditActionContract(
            action_type="inventory.proposal.decided",
            action_version=1,
            payload_schema="InventoryProposalAuditV1",
            payload_version=1,
            payload_contract=_contract(
                "InventoryProposalAuditV1",
                frozenset(
                    {
                        "proposal_id",
                        "decision",
                        "input_fingerprint",
                        "accepted_target_count",
                        "deferred_or_rejected_count",
                        "source_evidence_ref",
                        "reason_category",
                    }
                ),
            ),
            sensitivity_validator=_validate_inventory_proposal,
        )
    )
    registry.register(
        AuditActionContract(
            action_type="inventory.untouched_draft.hard_deleted",
            action_version=1,
            payload_schema="InventoryHardDeleteAuditV1",
            payload_version=1,
            payload_contract=_contract(
                "InventoryHardDeleteAuditV1",
                frozenset(
                    {
                        "target_type",
                        "target_id",
                        "reviewed_revision",
                        "eligibility_fingerprint",
                        "retained_related_ids",
                        "result",
                    }
                ),
            ),
            sensitivity_validator=_validate_inventory_hard_delete,
        )
    )
    registry.register(
        AuditActionContract(
            action_type="inventory.bulk.accepted",
            action_version=1,
            payload_schema="InventoryBulkAuditV1",
            payload_version=1,
            payload_contract=ObjectContract(
                name="InventoryBulkAuditV1",
                version=1,
                required_fields=frozenset(
                    {
                        "batch_id",
                        "action_kind",
                        "input_fingerprint",
                        "target_count",
                        "result_refs",
                        "result",
                    }
                ),
                allowed_fields=frozenset(
                    {
                        "batch_id",
                        "action_kind",
                        "input_fingerprint",
                        "target_count",
                        "result_refs",
                        "result",
                    }
                ),
                max_depth=4,
                max_collection_items=700,
                max_utf8_bytes=131_072,
            ),
            sensitivity_validator=_validate_inventory_bulk,
        )
    )
    registry.register(
        AuditActionContract(
            action_type="inventory.evidence.corrected",
            action_version=1,
            payload_schema="InventoryCorrectionAuditV1",
            payload_version=1,
            payload_contract=_contract(
                "InventoryCorrectionAuditV1",
                frozenset(
                    {
                        "correction_kind",
                        "target_id",
                        "target_event_id",
                        "reason_category",
                        "result_kind",
                        "result_id",
                    }
                ),
            ),
            sensitivity_validator=_validate_inventory_correction,
        )
    )
    return registry


__all__ = ["build_inventory_audit_registry"]
