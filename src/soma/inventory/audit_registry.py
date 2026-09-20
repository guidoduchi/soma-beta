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


def _nonnegative(value: object, field: str) -> None:
    if type(value) is not int or value < 0:
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



_SPARE_UNIT_EVENTS = frozenset({"REGISTER", "RESERVE", "RELEASE", "SELECT"})


def _validate_spare_unit(payload: dict[str, object]) -> None:
    _uuid(payload.get("spare_part_unit_id"), "spare_part_unit_id")
    if payload.get("event_kind") not in _SPARE_UNIT_EVENTS:
        raise SomaError("AUDIT_PAYLOAD_INVALID", "Spare Part Unit event kind is invalid")
    _uuid(payload.get("task_id"), "task_id", nullable=True)
    _uuid(payload.get("allocation_id"), "allocation_id", nullable=True)
    _uuid(payload.get("spare_need_id"), "spare_need_id", nullable=True)
    _positive(payload.get("resulting_revision"), "resulting_revision")



_SPR = re.compile(r"SPR-[0-9]{8}\Z")


def _validate_spare_request_draft(payload: dict[str, object]) -> None:
    _uuid(payload.get("spare_request_id"), "spare_request_id")
    _uuid(payload.get("requester_contact_id"), "requester_contact_id")
    tracking_id = payload.get("tracking_id")
    if not isinstance(tracking_id, str) or _SPR.fullmatch(tracking_id) is None:
        raise SomaError("AUDIT_PAYLOAD_INVALID", "tracking_id is invalid")
    if payload.get("event_kind") not in {"CREATE", "DRAFT_UPDATE", "TERMINAL"}:
        raise SomaError("AUDIT_PAYLOAD_INVALID", "Spare Request draft event is invalid")
    _positive(payload.get("allocation_count"), "allocation_count")
    _positive(payload.get("resulting_revision"), "resulting_revision")
    _fingerprint(payload.get("requester_context_fingerprint"), "requester_context_fingerprint")
    _reason(payload.get("reason_category"))



_SUBMISSION_EVENTS = frozenset({"ACCEPT", "CORRECT_FALSE"})


def _validate_spare_request_submission(payload: dict[str, object]) -> None:
    _uuid(payload.get("spare_request_id"), "spare_request_id")
    _uuid(payload.get("submission_event_id"), "submission_event_id")
    _uuid(payload.get("submission_snapshot_id"), "submission_snapshot_id")
    if payload.get("event_kind") not in _SUBMISSION_EVENTS:
        raise SomaError("AUDIT_PAYLOAD_INVALID", "Spare Request submission event is invalid")
    _positive(payload.get("allocation_count"), "allocation_count")
    _fingerprint(payload.get("input_fingerprint"), "input_fingerprint")
    effective = payload.get("effective_at_utc")
    if effective is not None and (type(effective) is not int or effective < 0):
        raise SomaError("AUDIT_PAYLOAD_INVALID", "effective_at_utc is invalid")



_SR7_ID = re.compile(r"SR[0-9]{7}\Z")
_SR7_EVENTS = frozenset({"ASSIGN", "CORRECT"})


def _validate_spare_request_identity(payload: dict[str, object]) -> None:
    _uuid(payload.get("spare_request_id"), "spare_request_id")
    if payload.get("event_kind") not in _SR7_EVENTS:
        raise SomaError("AUDIT_PAYLOAD_INVALID", "Spare Request identity event is invalid")
    current_sr7 = payload.get("current_sr7")
    former_sr7 = payload.get("former_sr7")
    if not isinstance(current_sr7, str) or _SR7_ID.fullmatch(current_sr7) is None:
        raise SomaError("AUDIT_PAYLOAD_INVALID", "current_sr7 is invalid")
    if former_sr7 is not None and (
        not isinstance(former_sr7, str) or _SR7_ID.fullmatch(former_sr7) is None
    ):
        raise SomaError("AUDIT_PAYLOAD_INVALID", "former_sr7 is invalid")
    _positive(payload.get("resulting_revision"), "resulting_revision")
    _reason(payload.get("reason_category"))



_C10_ID = re.compile(r"C[0-9]{10}\Z")
_RMA_EVENTS = frozenset({"AUTHORIZE", "ASSIGN", "REASSIGN", "CLEAR", "C10_CORRECT"})


def _validate_rma(payload: dict[str, object]) -> None:
    _uuid(payload.get("spare_request_id"), "spare_request_id")
    _uuid(payload.get("authorization_batch_id"), "authorization_batch_id", nullable=True)
    _uuid(payload.get("rma_id"), "rma_id")
    if payload.get("event_kind") not in _RMA_EVENTS:
        raise SomaError("AUDIT_PAYLOAD_INVALID", "RMA event kind is invalid")
    current_c10 = payload.get("current_c10")
    if not isinstance(current_c10, str) or _C10_ID.fullmatch(current_c10) is None:
        raise SomaError("AUDIT_PAYLOAD_INVALID", "current_c10 is invalid")
    _uuid(
        payload.get("target_device_part_unit_id"),
        "target_device_part_unit_id",
        nullable=True,
    )
    _positive(payload.get("resulting_revision"), "resulting_revision")



_LOGISTICS_EVENTS = frozenset(
    {
        "dispatch",
        "pickup",
        "delivery",
        "receipt",
        "custody_change",
        "location_change",
        "return_pickup",
        "warehouse_delivery",
        "correction",
    }
)


def _validate_rma_receipt(payload: dict[str, object]) -> None:
    _uuid(payload.get("rma_id"), "rma_id")
    _uuid(payload.get("spare_part_unit_id"), "spare_part_unit_id")
    _uuid(payload.get("receipt_event_id"), "receipt_event_id")
    _uuid(payload.get("logistics_event_id"), "logistics_event_id")
    _fingerprint(payload.get("actual_bom_fingerprint"), "actual_bom_fingerprint")
    _fingerprint(
        payload.get("actual_serial_fingerprint"),
        "actual_serial_fingerprint",
        nullable=True,
    )
    effective = payload.get("effective_at_utc")
    if effective is not None and (type(effective) is not int or effective < 0):
        raise SomaError("AUDIT_PAYLOAD_INVALID", "effective_at_utc is invalid")



_PHYSICAL_CONSEQUENCE_EVENTS = frozenset({"ACCEPT", "CORRECT", "SUPERSEDE"})
_PHYSICAL_DISPOSITIONS = frozenset(
    {
        "installed_used",
        "unused",
        "inbound_faulty",
        "incompatible",
        "dismantled",
        "removed_only",
        "no_physical_change",
        "other_reviewed",
    }
)


def _validate_physical_consequence(payload: dict[str, object]) -> None:
    _uuid(payload.get("physical_consequence_id"), "physical_consequence_id")
    _uuid(payload.get("task_id"), "task_id")
    _fingerprint(payload.get("task_review_fingerprint"), "task_review_fingerprint")
    if payload.get("event_kind") not in _PHYSICAL_CONSEQUENCE_EVENTS:
        raise SomaError("AUDIT_PAYLOAD_INVALID", "physical consequence event is invalid")
    if payload.get("disposition") not in _PHYSICAL_DISPOSITIONS:
        raise SomaError("AUDIT_PAYLOAD_INVALID", "physical consequence disposition is invalid")
    _uuid(
        payload.get("return_obligation_id"),
        "return_obligation_id",
        nullable=True,
    )
    _positive(payload.get("resulting_revision"), "resulting_revision")



def _validate_logistics(payload: dict[str, object]) -> None:
    _uuid(payload.get("logistics_event_id"), "logistics_event_id")
    if payload.get("event_kind") not in _LOGISTICS_EVENTS:
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


_FT = re.compile(r"FT-[0-9]{8}\Z")


def _validate_fault_tag(payload: dict[str, object]) -> None:
    _uuid(payload.get("fault_tag_id"), "fault_tag_id")
    tracking = payload.get("tracking_id")
    if not isinstance(tracking, str) or _FT.fullmatch(tracking) is None:
        raise SomaError("AUDIT_PAYLOAD_INVALID", "Fault Tag tracking_id is invalid")
    if payload.get("event_kind") not in {"CREATE", "DRAFT_UPDATE", "ARCHIVE", "RESTORE"}:
        raise SomaError("AUDIT_PAYLOAD_INVALID", "Fault Tag event kind is invalid")
    _nonnegative(payload.get("member_count"), "member_count")
    _positive(payload.get("resulting_revision"), "resulting_revision")
    _reason(payload.get("reason_category"))


def _validate_fault_tag_submission(payload: dict[str, object]) -> None:
    _uuid(payload.get("fault_tag_id"), "fault_tag_id")
    _uuid(payload.get("submission_event_id"), "submission_event_id")
    _uuid(payload.get("submission_snapshot_id"), "submission_snapshot_id")
    if payload.get("event_kind") not in {"ACCEPT", "CORRECT_FALSE"}:
        raise SomaError("AUDIT_PAYLOAD_INVALID", "Fault Tag submission event is invalid")
    _positive(payload.get("membership_count"), "membership_count")
    _fingerprint(payload.get("input_fingerprint"), "input_fingerprint")
    effective = payload.get("effective_at_utc")
    if effective is not None and (type(effective) is not int or effective < 0):
        raise SomaError("AUDIT_PAYLOAD_INVALID", "effective_at_utc is invalid")


def _validate_warehouse_decision(payload: dict[str, object]) -> None:
    _uuid(payload.get("membership_id"), "membership_id")
    if payload.get("event_kind") not in {"RECEIVED", "ACCEPTED", "REJECTED"}:
        raise SomaError("AUDIT_PAYLOAD_INVALID", "warehouse event kind is invalid")
    _uuid(payload.get("rma_id"), "rma_id")
    _uuid(payload.get("return_obligation_id"), "return_obligation_id")
    _uuid(payload.get("batch_id"), "batch_id", nullable=True)
    effective = payload.get("effective_at_utc")
    if effective is not None and (type(effective) is not int or effective < 0):
        raise SomaError("AUDIT_PAYLOAD_INVALID", "effective_at_utc is invalid")
    if type(payload.get("explicit_confirmation")) is not bool:
        raise SomaError("AUDIT_PAYLOAD_INVALID", "explicit_confirmation is invalid")


def _validate_fault_tag_lineage(payload: dict[str, object]) -> None:
    _uuid(payload.get("predecessor_fault_tag_id"), "predecessor_fault_tag_id")
    _uuid(payload.get("successor_fault_tag_id"), "successor_fault_tag_id")
    if payload.get("lineage_kind") not in {"CORRECTS_REPLACES", "RESEND_OF"}:
        raise SomaError("AUDIT_PAYLOAD_INVALID", "Fault Tag lineage kind is invalid")
    _fingerprint(payload.get("membership_scope_fingerprint"), "membership_scope_fingerprint")
    _reason(payload.get("reason_category"))
    _positive(payload.get("resulting_revision"), "resulting_revision")


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
                        "task_id",
                        "allocation_id",
                        "spare_need_id",
                        "resulting_revision",
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
            sensitivity_validator=_validate_spare_request_draft,
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
    return registry


__all__ = ["build_inventory_audit_registry"]
