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



_SPARE_UNIT_EVENTS = frozenset({"REGISTER", "RESERVE", "RELEASE", "LOCAL_SELECTION"})
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
    return registry


__all__ = ["build_inventory_audit_registry"]
