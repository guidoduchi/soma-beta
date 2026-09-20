from __future__ import annotations

from typing import Any

from soma.foundation.audit.writer import AuditEventInput, AuditResultRef, AuditWriter
from soma.foundation.errors import IntegrityFailure, SomaError, ValidationError
from soma.foundation.identifiers import new_uuid4, require_uuid4, utc_epoch_seconds
from soma.foundation.strict_json import canonical_json_bytes, sha256_canonical_json

from ..audit_registry import build_inventory_audit_registry
from ..domain.needs import validate_reason_code
from ..report_sections import InventoryReportSectionContributor
from ..repositories.fault_tags import InventoryFaultTagsRepository
from .corrections_bulk import InventoryCorrectionsBulkService


def _connection(reader: Any):
    if hasattr(reader, "execute"):
        return reader
    connection = getattr(reader, "connection", None)
    if connection is None or not hasattr(connection, "execute"):
        raise ValidationError("Inventory Task participant requires a database read context")
    return connection


class InventoryProposalTargetService:
    """Caller-UoW Inventory proposal participant for future LLD-09 orchestration."""

    def __init__(self) -> None:
        self._fault_tags = InventoryFaultTagsRepository()
        self._audit = AuditWriter(build_inventory_audit_registry())

    @staticmethod
    def _normalize_evidence_ref(evidence_ref: object) -> dict[str, str]:
        if (
            not isinstance(evidence_ref, dict)
            or set(evidence_ref) != {"evidence_kind", "evidence_id"}
            or not isinstance(evidence_ref["evidence_kind"], str)
            or not evidence_ref["evidence_kind"]
            or not isinstance(evidence_ref["evidence_id"], str)
            or not evidence_ref["evidence_id"]
        ):
            raise ValidationError("Inventory proposal evidence_ref is invalid")
        if (
            len(evidence_ref["evidence_kind"].encode("utf-8")) > 256
            or len(evidence_ref["evidence_id"].encode("utf-8")) > 1024
        ):
            raise ValidationError("Inventory proposal evidence_ref exceeds bounds")
        return {
            "evidence_kind": str(evidence_ref["evidence_kind"]),
            "evidence_id": str(evidence_ref["evidence_id"]),
        }

    @staticmethod
    def _normalize_targets(
        proposal_kind: str,
        target_refs: object,
        *,
        risk_tier: str,
        explicit_confirmation: bool,
    ) -> tuple[dict[str, object], ...]:
        if proposal_kind not in {
            "warehouse_received",
            "warehouse_final_decision",
        }:
            raise SomaError(
                "DEPENDENCY_INDETERMINATE",
                "Inventory proposal kind is not typed for Beta 1.0 acceptance",
            )
        if not isinstance(target_refs, tuple) or not target_refs or len(target_refs) > 2000:
            raise ValidationError(
                "Inventory proposal target_refs must contain 1..2000 targets"
            )
        normalized: list[dict[str, object]] = []
        seen: set[str] = set()
        for raw in target_refs:
            if not isinstance(raw, dict):
                raise ValidationError("Inventory proposal target must be an object")
            if set(raw) != {
                "target_kind",
                "target_id",
                "expected_revision",
                "proposed_action",
                "payload",
            }:
                raise ValidationError("Inventory proposal target shape is invalid")
            if raw["target_kind"] != "fault_tag_membership":
                raise SomaError(
                    "DEPENDENCY_INDETERMINATE",
                    "Beta 1.0 proposal target must be Fault Tag membership",
                )
            target_id = require_uuid4(str(raw["target_id"]))
            if target_id in seen:
                raise ValidationError("Inventory proposal target is duplicated")
            seen.add(target_id)
            revision = raw["expected_revision"]
            if type(revision) is not int or revision <= 0:
                raise ValidationError("Inventory proposal expected_revision is invalid")
            payload = raw["payload"]
            if not isinstance(payload, dict):
                raise ValidationError("Inventory proposal payload must be an object")
            target = {
                "inventory_proposal_target_id": target_id,
                "target_kind": "fault_tag_membership",
                "spare_request_id": None,
                "rma_id": None,
                "spare_part_unit_id": None,
                "fault_tag_id": None,
                "fault_tag_membership_id": target_id,
                "expected_revision": revision,
                "proposed_action": str(raw["proposed_action"]),
                "payload_json": canonical_json_bytes(payload).decode("utf-8"),
            }
            parsed = InventoryCorrectionsBulkService._parse_proposal_target(
                proposal_kind=proposal_kind,
                risk_tier=risk_tier,
                target=target,
                explicit_confirmation=explicit_confirmation,
            )
            normalized.append(
                {
                    "target_kind": "fault_tag_membership",
                    "target_id": target_id,
                    "expected_revision": revision,
                    "proposed_action": str(raw["proposed_action"]),
                    "payload": payload,
                    "owner": parsed,
                }
            )
        normalized.sort(key=lambda item: str(item["target_id"]).encode("utf-8"))
        return tuple(normalized)

    @classmethod
    def _authority(
        cls,
        reader: Any,
        *,
        proposal_kind: str,
        targets: tuple[dict[str, object], ...],
    ) -> tuple[dict[str, object], ...]:
        connection = _connection(reader)
        authority: list[dict[str, object]] = []
        for item in targets:
            owner = item["owner"]
            if not isinstance(owner, dict):
                raise IntegrityFailure("Inventory proposal owner mapping is invalid")
            expected_state = (
                "submitted_awaiting_receipt"
                if owner["owner_action"] == "warehouse_received"
                else "warehouse_received"
            )
            try:
                member, obligation = InventoryFaultTagsRepository._require_warehouse_member(
                    connection,
                    membership_id=str(owner["membership_id"]),
                    expected_revision=int(owner["expected_revision"]),
                    expected_state=expected_state,
                )
            except SomaError as exc:
                if exc.code in {
                    "INV_STALE",
                    "BULK_INCOMPATIBLE",
                    "WAREHOUSE_RECEIPT_REQUIRED",
                    "RETURN_SELECTION_INVALID",
                }:
                    raise SomaError(
                        "PROPOSAL_STALE",
                        "Inventory proposal owner state changed",
                    ) from exc
                raise
            authority.append(
                {
                    "target_id": str(item["target_id"]),
                    "membership_revision": int(member[9]),
                    "membership_state": str(member[7]),
                    "membership_last_event_id": None
                    if member[11] is None
                    else str(member[11]),
                    "rma_id": str(member[2]),
                    "return_obligation_state": str(obligation[0]),
                    "return_obligation_revision": int(obligation[4]),
                    "return_obligation_last_event_id": None
                    if obligation[5] is None
                    else str(obligation[5]),
                    "physical_consequence_id": str(member[3]),
                    "proposal_kind": proposal_kind,
                }
            )
        return tuple(authority)

    def preview(
        self,
        snapshot: Any,
        proposal_kind: str,
        target_refs: object,
        evidence_ref: object,
        *,
        risk_tier: str = "normal",
        explicit_confirmation: bool = False,
    ) -> dict[str, object]:
        if risk_tier not in {"normal", "high", "material_final"}:
            raise ValidationError("Inventory proposal risk_tier is invalid")
        if type(explicit_confirmation) is not bool:
            raise ValidationError("Inventory proposal explicit_confirmation is invalid")
        evidence = self._normalize_evidence_ref(evidence_ref)
        targets = self._normalize_targets(
            proposal_kind,
            target_refs,
            risk_tier=risk_tier,
            explicit_confirmation=explicit_confirmation,
        )
        authority = self._authority(
            snapshot,
            proposal_kind=proposal_kind,
            targets=targets,
        )
        base_material = {
            "schema": "SOMA_INVENTORY_PROPOSAL_BASE_V1",
            "proposal_kind": proposal_kind,
            "targets": [
                {
                    "target_id": str(item["target_id"]),
                    "expected_revision": int(item["expected_revision"]),
                    "owner_authority": current,
                }
                for item, current in zip(targets, authority)
            ],
        }
        base_token = sha256_canonical_json(base_material)
        semantic_targets = [
            {
                "target_kind": str(item["target_kind"]),
                "target_id": str(item["target_id"]),
                "expected_revision": int(item["expected_revision"]),
                "proposed_action": str(item["proposed_action"]),
                "payload": item["payload"],
            }
            for item in targets
        ]
        impact = {
            "schema": "SOMA_INVENTORY_PROPOSAL_IMPACT_V1",
            "status": "READY",
            "proposal_kind": proposal_kind,
            "risk_tier": risk_tier,
            "evidence_ref": evidence,
            "targets": semantic_targets,
            "base_token": base_token,
            "explicit_confirmation": explicit_confirmation,
        }
        return {
            **impact,
            "input_fingerprint": sha256_canonical_json(impact),
        }

    def base_token(
        self,
        snapshot: Any,
        proposal_kind: str,
        target_refs: object,
    ) -> str:
        risk_tier = (
            "material_final"
            if proposal_kind == "warehouse_final_decision"
            else "normal"
        )
        targets = self._normalize_targets(
            proposal_kind,
            target_refs,
            risk_tier=risk_tier,
            explicit_confirmation=(proposal_kind == "warehouse_final_decision"),
        )
        authority = self._authority(
            snapshot,
            proposal_kind=proposal_kind,
            targets=targets,
        )
        return sha256_canonical_json(
            {
                "schema": "SOMA_INVENTORY_PROPOSAL_BASE_V1",
                "proposal_kind": proposal_kind,
                "targets": [
                    {
                        "target_id": str(item["target_id"]),
                        "expected_revision": int(item["expected_revision"]),
                        "owner_authority": current,
                    }
                    for item, current in zip(targets, authority)
                ],
            }
        )

    def apply(
        self,
        uow: Any,
        accepted_proposal: object,
        command_context: object,
    ) -> tuple[dict[str, str], ...]:
        connection = _connection(uow)
        if not isinstance(accepted_proposal, dict):
            raise ValidationError("accepted_proposal must be an object")
        required = {
            "schema",
            "status",
            "proposal_kind",
            "risk_tier",
            "evidence_ref",
            "targets",
            "base_token",
            "explicit_confirmation",
            "input_fingerprint",
        }
        if set(accepted_proposal) != required:
            raise ValidationError("accepted_proposal shape is invalid")
        if (
            accepted_proposal["schema"] != "SOMA_INVENTORY_PROPOSAL_IMPACT_V1"
            or accepted_proposal["status"] != "READY"
        ):
            raise SomaError(
                "DEPENDENCY_INDETERMINATE",
                "accepted_proposal is not READY Inventory authority",
            )
        if (
            not isinstance(command_context, dict)
            or set(command_context) != {"command_id", "actor_kind", "actor_id"}
        ):
            raise ValidationError("Inventory proposal command_context shape is invalid")
        command_id = require_uuid4(str(command_context["command_id"]))
        actor_kind = command_context["actor_kind"]
        actor_id = command_context["actor_id"]
        if not isinstance(actor_kind, str) or not actor_kind:
            raise ValidationError("Inventory proposal actor_kind is invalid")
        if actor_id is not None and not isinstance(actor_id, str):
            raise ValidationError("Inventory proposal actor_id is invalid")
        if connection.execute(
            "SELECT 1 FROM command_receipts WHERE command_id=?",
            (command_id,),
        ).fetchone() is None:
            raise IntegrityFailure(
                "Inventory proposal participant requires caller-owned outer receipt"
            )

        proposal_kind = str(accepted_proposal["proposal_kind"])
        risk_tier = str(accepted_proposal["risk_tier"])
        explicit_confirmation = accepted_proposal["explicit_confirmation"]
        targets_raw = accepted_proposal["targets"]
        if not isinstance(targets_raw, list):
            raise ValidationError("accepted_proposal targets must be a list")
        targets = self._normalize_targets(
            proposal_kind,
            tuple(targets_raw),
            risk_tier=risk_tier,
            explicit_confirmation=bool(explicit_confirmation),
        )
        evidence = self._normalize_evidence_ref(accepted_proposal["evidence_ref"])
        current = self.preview(
            uow,
            proposal_kind,
            tuple(targets_raw),
            evidence,
            risk_tier=risk_tier,
            explicit_confirmation=bool(explicit_confirmation),
        )
        if (
            str(current["base_token"]) != str(accepted_proposal["base_token"])
            or str(current["input_fingerprint"])
            != str(accepted_proposal["input_fingerprint"])
        ):
            raise SomaError("PROPOSAL_STALE", "Inventory proposal preview changed")

        batch_id = new_uuid4()
        connection.execute(
            "INSERT INTO inventory_lifecycle_batches("
            "inventory_batch_id,batch_kind,target_count,recorded_at_utc,command_id"
            ") VALUES (?,'proposal_acceptance',?,?,?)",
            (batch_id, len(targets), utc_epoch_seconds(), command_id),
        )
        refs: list[dict[str, str]] = [
            {"type": "inventory_batch", "id": batch_id}
        ]
        for item in targets:
            owner = item["owner"]
            if not isinstance(owner, dict):
                raise IntegrityFailure("Inventory proposal owner mapping is invalid")
            membership_id = str(owner["membership_id"])
            expected_revision = int(owner["expected_revision"])
            if owner["owner_action"] == "warehouse_received":
                result = self._fault_tags.record_warehouse_receipt(
                    connection,
                    targets=((membership_id, expected_revision),),
                    effective_at_utc=owner["effective_at_utc"],
                    evidence_kind=evidence["evidence_kind"],
                    evidence_id=evidence["evidence_id"],
                    command_id=command_id,
                )
                audit_kind = "RECEIVED"
                confirmation = False
            else:
                result = self._fault_tags.record_warehouse_final_decision(
                    connection,
                    targets=((membership_id, expected_revision),),
                    decision=str(owner["decision"]),
                    reason_code=owner["reason_code"],
                    effective_at_utc=owner["effective_at_utc"],
                    evidence_kind=evidence["evidence_kind"],
                    evidence_id=evidence["evidence_id"],
                    command_id=command_id,
                )
                audit_kind = (
                    "ACCEPTED"
                    if owner["decision"] == "accepted"
                    else "REJECTED"
                )
                confirmation = True
            event = result["events"][0]
            refs.append(
                {
                    "type": "fault_tag_membership_event",
                    "id": str(event["membership_event_id"]),
                }
            )
            if owner["owner_action"] == "warehouse_final_decision":
                refs.append(
                    {
                        "type": "rma_return_obligation",
                        "id": str(event["rma_id"]),
                    }
                )
            self._audit.write(
                uow,
                AuditEventInput(
                    audit_event_id=new_uuid4(),
                    action_type="inventory.fault_tag.warehouse_state_changed",
                    action_version=1,
                    actor_kind=actor_kind,
                    actor_id=actor_id,
                    target_type="fault_tag_membership",
                    target_id=str(event["membership_id"]),
                    command_id=command_id,
                    reason_category=owner["reason_code"],
                    batch_id=batch_id,
                    payload_schema="WarehouseDecisionAuditV1",
                    payload_version=1,
                    payload={
                        "membership_id": str(event["membership_id"]),
                        "event_kind": audit_kind,
                        "rma_id": str(event["rma_id"]),
                        "return_obligation_id": str(event["rma_id"]),
                        "batch_id": batch_id,
                        "effective_at_utc": owner["effective_at_utc"],
                        "explicit_confirmation": confirmation,
                    },
                    resulting_event_refs=(
                        AuditResultRef(
                            "fault_tag_membership_event",
                            str(event["membership_event_id"]),
                        ),
                        AuditResultRef(
                            "rma_return_obligation",
                            str(event["rma_id"]),
                        ),
                    ),
                ),
            )
        return tuple(refs)


class InventoryTaskDependencyProvider:
    """LLD-07 participant consumed by LLD-05 hard-delete and retry flows."""

    @staticmethod
    def classify_task_hard_delete_dependency(reader: Any, task_id: str) -> str:
        connection = _connection(reader)
        identity = require_uuid4(task_id)
        task = connection.execute(
            "SELECT 1 FROM tasks WHERE task_id=?",
            (identity,),
        ).fetchone()
        if task is None:
            return "INDETERMINATE"
        if connection.execute(
            "SELECT 1 FROM inventory_physical_consequences WHERE task_id=? LIMIT 1",
            (identity,),
        ).fetchone() is not None:
            return "BLOCKED"
        if connection.execute(
            "SELECT 1 FROM task_unit_allocation_events WHERE task_id=? LIMIT 1",
            (identity,),
        ).fetchone() is not None:
            return "BLOCKED"
        if connection.execute(
            "SELECT 1 FROM task_unit_allocation_current WHERE task_id=? LIMIT 1",
            (identity,),
        ).fetchone() is not None:
            return "BLOCKED"
        if connection.execute(
            "SELECT 1 FROM local_need_fulfillment_events WHERE task_id=? LIMIT 1",
            (identity,),
        ).fetchone() is not None:
            return "BLOCKED"
        return "CLEAR"

    @staticmethod
    def preview_retry_relationship_clone(
        snapshot: Any,
        predecessor_task_id: str,
        selected_inventory_relationship_ids: tuple[str, ...],
    ) -> dict[str, object]:
        connection = _connection(snapshot)
        predecessor = require_uuid4(predecessor_task_id)
        if (
            not isinstance(selected_inventory_relationship_ids, tuple)
            or len(selected_inventory_relationship_ids) > 2000
        ):
            raise ValidationError(
                "selected_inventory_relationship_ids must be a tuple of at most 2000 allocation UUIDs"
            )
        selected = tuple(
            sorted(
                (require_uuid4(value) for value in selected_inventory_relationship_ids),
                key=lambda value: value.encode("utf-8"),
            )
        )
        if len(set(selected)) != len(selected):
            raise ValidationError("retry Inventory selection contains duplicate allocations")
        if connection.execute(
            "SELECT 1 FROM tasks WHERE task_id=?",
            (predecessor,),
        ).fetchone() is None:
            return {
                "status": "INDETERMINATE",
                "predecessor_task_id": predecessor,
                "relationships": [],
                "fingerprint": sha256_canonical_json(
                    {
                        "schema": "SOMA_INVENTORY_RETRY_CLONE_PREVIEW_V1",
                        "predecessor_task_id": predecessor,
                        "status": "INDETERMINATE",
                        "relationships": [],
                    }
                ),
            }
        if connection.execute(
            "SELECT 1 FROM inventory_physical_consequences WHERE task_id=? LIMIT 1",
            (predecessor,),
        ).fetchone() is not None:
            status = "BLOCKED"
            relationships: list[dict[str, object]] = []
        else:
            status = "READY"
            relationships = []
            for allocation_id in selected:
                row = connection.execute(
                    "SELECT c.task_id,c.spare_part_unit_id,c.spare_need_id,c.revision,"
                    "c.last_event_id,p.disposition_token,p.active_task_allocation_id "
                    "FROM task_unit_allocation_current c "
                    "JOIN spare_part_current_projection p "
                    "ON p.spare_part_unit_id=c.spare_part_unit_id "
                    "WHERE c.allocation_id=?",
                    (allocation_id,),
                ).fetchone()
                if row is None:
                    status = "INDETERMINATE"
                    relationships.append(
                        {
                            "allocation_id": allocation_id,
                            "classification": "missing",
                        }
                    )
                    continue
                if (
                    str(row[0]) != predecessor
                    or str(row[5]) != "reserved"
                    or row[6] is None
                    or str(row[6]) != allocation_id
                ):
                    status = "BLOCKED"
                    relationships.append(
                        {
                            "allocation_id": allocation_id,
                            "classification": "incompatible",
                        }
                    )
                    continue
                relationships.append(
                    {
                        "allocation_id": allocation_id,
                        "classification": "eligible",
                        "allocation_revision": int(row[3]),
                        "spare_part_unit_id": str(row[1]),
                        "spare_need_id": None if row[2] is None else str(row[2]),
                        "last_event_id": str(row[4]),
                    }
                )
        material = {
            "schema": "SOMA_INVENTORY_RETRY_CLONE_PREVIEW_V1",
            "predecessor_task_id": predecessor,
            "status": status,
            "relationships": relationships,
        }
        return {
            "status": status,
            "predecessor_task_id": predecessor,
            "relationships": relationships,
            "fingerprint": sha256_canonical_json(material),
        }

    @staticmethod
    def apply_retry_relationship_clone(
        uow: Any,
        preview: dict[str, object],
        new_task_id: str,
        command_context: dict[str, object],
    ) -> tuple[dict[str, str], ...]:
        connection = _connection(uow)
        successor = require_uuid4(new_task_id)
        if not isinstance(preview, dict) or preview.get("status") != "READY":
            raise SomaError(
                "DEPENDENCY_INDETERMINATE",
                "Inventory retry clone preview is not READY",
            )
        predecessor = require_uuid4(str(preview.get("predecessor_task_id")))
        relationships = preview.get("relationships")
        fingerprint = preview.get("fingerprint")
        if (
            not isinstance(relationships, list)
            or not isinstance(fingerprint, str)
            or len(fingerprint) != 64
        ):
            raise SomaError(
                "DEPENDENCY_INDETERMINATE",
                "Inventory retry clone preview shape is invalid",
            )
        if (
            not isinstance(command_context, dict)
            or set(command_context) != {"command_id", "actor_kind", "actor_id"}
        ):
            raise ValidationError("Inventory retry command context shape is invalid")
        command_id = require_uuid4(str(command_context["command_id"]))
        actor_kind = command_context["actor_kind"]
        actor_id = command_context["actor_id"]
        if not isinstance(actor_kind, str) or not actor_kind:
            raise ValidationError("Inventory retry actor_kind is invalid")
        if actor_id is not None and not isinstance(actor_id, str):
            raise ValidationError("Inventory retry actor_id is invalid")

        if connection.execute(
            "SELECT 1 FROM command_receipts WHERE command_id=?",
            (command_id,),
        ).fetchone() is None:
            raise IntegrityFailure(
                "Inventory retry participant requires caller-owned outer command receipt"
            )
        if connection.execute(
            "SELECT 1 FROM tasks WHERE task_id=?",
            (successor,),
        ).fetchone() is None:
            raise SomaError("TASK_STALE", "Retry successor Task no longer exists")

        selected = tuple(
            str(item["allocation_id"])
            for item in relationships
            if isinstance(item, dict) and item.get("classification") == "eligible"
        )
        current_preview = InventoryTaskDependencyProvider.preview_retry_relationship_clone(
            uow,
            predecessor,
            selected,
        )
        if (
            current_preview["status"] != "READY"
            or current_preview["fingerprint"] != fingerprint
        ):
            raise SomaError("INV_STALE", "Inventory retry clone authority changed")

        now = utc_epoch_seconds()
        refs: list[dict[str, str]] = []
        for item in current_preview["relationships"]:
            allocation_id = str(item["allocation_id"])
            prior_revision = int(item["allocation_revision"])
            event_id = new_uuid4()
            connection.execute(
                "INSERT INTO task_unit_allocation_events("
                "allocation_event_id,allocation_id,task_id,spare_part_unit_id,spare_need_id,"
                "event_kind,prior_task_id,reason_code,effective_at_utc,target_event_id,"
                "recorded_at_utc,command_id"
                ") VALUES (?,?,?,?,?,'reassign',?,'task_retry_clone',NULL,?,?,?)",
                (
                    event_id,
                    allocation_id,
                    successor,
                    str(item["spare_part_unit_id"]),
                    item["spare_need_id"],
                    predecessor,
                    str(item["last_event_id"]),
                    now,
                    command_id,
                ),
            )
            changed = connection.execute(
                "UPDATE task_unit_allocation_current SET task_id=?,revision=?,"
                "last_event_id=?,last_command_id=? WHERE allocation_id=? "
                "AND task_id=? AND revision=?",
                (
                    successor,
                    prior_revision + 1,
                    event_id,
                    command_id,
                    allocation_id,
                    predecessor,
                    prior_revision,
                ),
            )
            if changed.rowcount != 1:
                raise SomaError("INV_STALE", "Inventory retry allocation changed")
            refs.extend(
                (
                    {"type": "task_unit_allocation", "id": allocation_id},
                    {"type": "task_unit_allocation_event", "id": event_id},
                )
            )
        return tuple(refs)


__all__ = ["InventoryTaskDependencyProvider"]
