from __future__ import annotations

from dataclasses import dataclass

from soma.foundation.errors import ValidationError
from soma.foundation.identifiers import require_uuid4
from soma.foundation.persistence.connections import ConnectionFactory
from soma.foundation.persistence.uow import ReadSnapshot

_RESPONSE_OVERDUE_SECONDS = 24 * 60 * 60


@dataclass(frozen=True, slots=True)
class SpareRequestResponseAttention:
    spare_request_id: str
    attention_kind: str
    severity: str
    warning_start_utc: int
    due_at_utc: int
    age_seconds: int


class InventoryAttentionQueryService:
    def __init__(self, connection_factory: ConnectionFactory) -> None:
        self._factory = connection_factory

    def spare_request_response_attention(
        self,
        *,
        spare_request_id: str,
        as_of_utc: int,
    ) -> SpareRequestResponseAttention | None:
        request_id = require_uuid4(spare_request_id)
        if type(as_of_utc) is not int or as_of_utc < 0:
            raise ValidationError("as_of_utc must be a nonnegative integer")
        with ReadSnapshot(self._factory) as snapshot:
            row = snapshot.connection.execute(
                "SELECT lifecycle_state,response_warning_start_utc "
                "FROM spare_request_current_projection WHERE spare_request_id=?",
                (request_id,),
            ).fetchone()
        if row is None:
            raise ValidationError("Spare Request does not exist")
        if str(row[0]) != "submitted_awaiting_response" or row[1] is None:
            return None
        warning_start = int(row[1])
        due = warning_start + _RESPONSE_OVERDUE_SECONDS
        if as_of_utc < due:
            return None
        return SpareRequestResponseAttention(
            spare_request_id=request_id,
            attention_kind="spare_request_response_overdue",
            severity="warning",
            warning_start_utc=warning_start,
            due_at_utc=due,
            age_seconds=as_of_utc - warning_start,
        )


    def list_items(
        self,
        *,
        attention_kind: str | None = None,
        severity: str | None = None,
        limit: int = 100,
    ) -> tuple[dict[str, object], ...]:
        next_actions = {
            "spare_request_response_overdue": "review_spare_request_response",
            "partial_rma_authorization": "review_rma_authorization",
            "rma_assignment_conflict": "review_rma_assignment",
            "receipt_bom_mismatch": "review_rma_receipt",
            "task_outcome_consequence_pending": "review_task_physical_consequence",
            "return_obligation_open": "create_or_update_fault_tag",
            "warehouse_final_decision_pending": "record_warehouse_final_decision",
            "warehouse_rejected_resend_required": "create_fault_tag_resend",
            "proposal_review_required": "review_inventory_proposal",
            "stock_conflict": "review_stock_conflict",
        }
        if type(limit) is not int or not 1 <= limit <= 500:
            raise ValidationError("Inventory attention limit must be 1..500")
        if attention_kind is not None and attention_kind not in next_actions:
            raise ValidationError("Inventory attention kind is invalid")
        if severity is not None and severity not in {
            "info",
            "warning",
            "action_required",
            "high",
        }:
            raise ValidationError("Inventory attention severity is invalid")

        with ReadSnapshot(self._factory) as snapshot:
            clauses: list[str] = []
            params: list[object] = []
            if attention_kind is not None:
                clauses.append("a.attention_kind=?")
                params.append(attention_kind)
            if severity is not None:
                clauses.append("a.severity=?")
                params.append(severity)
            where = "" if not clauses else "WHERE " + " AND ".join(clauses)
            rows = snapshot.connection.execute(
                "SELECT a.attention_id,a.target_kind,a.target_id,a.attention_kind,"
                "a.severity,a.input_fingerprint "
                "FROM inventory_attention_projection a "
                f"{where} "
                "ORDER BY a.attention_kind,a.severity,a.target_kind,a.target_id "
                "LIMIT ?",
                (*params, limit),
            ).fetchall()

            items: list[dict[str, object]] = []
            for row in rows:
                target_kind = str(row[1])
                target_id = str(row[2])
                kind = str(row[3])
                derived_context: dict[str, object] = {}
                if target_kind == "rma":
                    rma = snapshot.connection.execute(
                        "SELECT a.c10,l.state,l.return_obligation_open,"
                        "o.obligation_state,o.device_part_unit_id,o.spare_part_unit_id "
                        "FROM rmas r "
                        "JOIN rma_identifier_aliases a "
                        "ON a.rma_id=r.rma_id AND a.alias_kind='current' "
                        "JOIN rma_lifecycle_projection l ON l.rma_id=r.rma_id "
                        "LEFT JOIN rma_return_obligation_current o ON o.rma_id=r.rma_id "
                        "WHERE r.rma_id=?",
                        (target_id,),
                    ).fetchone()
                    if rma is not None:
                        derived_context.update(
                            {
                                "current_c10": str(rma[0]),
                                "rma_state": str(rma[1]),
                                "return_obligation_open": bool(rma[2]),
                                "obligation_state": None
                                if rma[3] is None
                                else str(rma[3]),
                                "return_device_part_unit_id": None
                                if rma[4] is None
                                else str(rma[4]),
                                "return_spare_part_unit_id": None
                                if rma[5] is None
                                else str(rma[5]),
                            }
                        )
                    rejected = snapshot.connection.execute(
                        "SELECT m.fault_tag_id,t.tracking_id,p.archived "
                        "FROM fault_tag_membership_current c "
                        "JOIN fault_tag_memberships m "
                        "ON m.fault_tag_membership_id=c.fault_tag_membership_id "
                        "JOIN fault_tags t ON t.fault_tag_id=m.fault_tag_id "
                        "JOIN fault_tag_current_projection p "
                        "ON p.fault_tag_id=m.fault_tag_id "
                        "WHERE c.rma_id=? AND c.state='rejected' "
                        "ORDER BY t.tracking_sequence DESC,m.fault_tag_membership_id DESC "
                        "LIMIT 1",
                        (target_id,),
                    ).fetchone()
                    if rejected is not None:
                        derived_context.update(
                            {
                                "rejected_fault_tag_id": str(rejected[0]),
                                "rejected_fault_tag_tracking_id": str(rejected[1]),
                                "rejected_fault_tag_archived": bool(rejected[2]),
                            }
                        )
                items.append(
                    {
                        "attention_id": str(row[0]),
                        "target_kind": target_kind,
                        "target_id": target_id,
                        "attention_kind": kind,
                        "severity": str(row[4]),
                        "input_fingerprint": str(row[5]),
                        "reason_or_blocker": kind,
                        "derived_context": derived_context,
                        "next_governed_action": next_actions[kind],
                    }
                )
            return tuple(items)


__all__ = ["InventoryAttentionQueryService", "SpareRequestResponseAttention"]
