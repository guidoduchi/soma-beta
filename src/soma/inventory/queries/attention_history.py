from __future__ import annotations

from dataclasses import dataclass

from soma.foundation.errors import ValidationError
from soma.foundation.identifiers import require_uuid4
from soma.foundation.persistence.connections import ConnectionFactory
from soma.foundation.persistence.uow import ReadSnapshot
from soma.foundation.strict_json import sha256_canonical_json

_RESPONSE_OVERDUE_SECONDS = 24 * 60 * 60
_HISTORY_QUERY_ID = "InventoryHistoryQuery"
_HISTORY_SORT_ID = "INVENTORY_HISTORY_TIME_AUTHORITY_ID_ASC_V1"
_HISTORY_CURSOR_FIELDS = frozenset(
    {
        "version",
        "query_id",
        "sort_registry_id",
        "last_key_tuple",
        "filter_fingerprint",
        "null_order",
    }
)


@dataclass(frozen=True, slots=True)
class SpareRequestResponseAttention:
    spare_request_id: str
    attention_kind: str
    severity: str
    warning_start_utc: int
    due_at_utc: int
    age_seconds: int


@dataclass(frozen=True, slots=True)
class InventoryHistoryPage:
    items: tuple[dict[str, object], ...]
    continuation: dict[str, object] | None
    exact_total: int


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


    @staticmethod
    def _decode_history_cursor(
        cursor: dict[str, object] | None,
        *,
        filter_fingerprint: str,
    ) -> tuple[int, str, str] | None:
        if cursor is None:
            return None
        if not isinstance(cursor, dict) or set(cursor) != _HISTORY_CURSOR_FIELDS:
            raise ValidationError("Inventory history cursor shape is invalid")
        if (
            cursor["version"] != 1
            or cursor["query_id"] != _HISTORY_QUERY_ID
            or cursor["sort_registry_id"] != _HISTORY_SORT_ID
            or cursor["filter_fingerprint"] != filter_fingerprint
            or cursor["null_order"] != "not_applicable"
        ):
            raise ValidationError("Inventory history cursor contract is invalid")
        key = cursor["last_key_tuple"]
        if (
            not isinstance(key, list)
            or len(key) != 3
            or type(key[0]) is not int
            or not isinstance(key[1], str)
            or not isinstance(key[2], str)
        ):
            raise ValidationError("Inventory history cursor key is invalid")
        return int(key[0]), str(key[1]), str(key[2])

    def history(
        self,
        *,
        target_kind: str,
        target_id: str,
        cursor: dict[str, object] | None = None,
        limit: int = 100,
    ) -> InventoryHistoryPage:
        if target_kind not in {
            "spare_need",
            "spare_request",
            "rma",
            "spare_part_unit",
            "device_part_unit",
            "fault_tag",
            "inventory_physical_consequence",
            "task",
        }:
            raise ValidationError("Inventory history target_kind is invalid")
        identity = require_uuid4(target_id)
        if type(limit) is not int or not 1 <= limit <= 500:
            raise ValidationError("Inventory history limit must be 1..500")
        fingerprint = sha256_canonical_json(
            {
                "schema": "SOMA_INVENTORY_HISTORY_FILTER_V1",
                "target_kind": target_kind,
                "target_id": identity,
            }
        )
        after = self._decode_history_cursor(
            cursor,
            filter_fingerprint=fingerprint,
        )
        entries: list[tuple[tuple[int, str, str], dict[str, object]]] = []

        def add(
            *,
            recorded_at_utc: int,
            authority: str,
            event_kind: str,
            event_id: str,
            details: dict[str, object],
        ) -> None:
            key = (recorded_at_utc, authority, event_id)
            entries.append(
                (
                    key,
                    {
                        "recorded_at_utc": recorded_at_utc,
                        "authority": authority,
                        "event_kind": event_kind,
                        "event_id": event_id,
                        "details": details,
                    },
                )
            )

        with ReadSnapshot(self._factory) as snapshot:
            connection = snapshot.connection
            exists_sql = {
                "spare_need": "SELECT 1 FROM spare_needs WHERE spare_need_id=?",
                "spare_request": "SELECT 1 FROM spare_requests WHERE spare_request_id=?",
                "rma": "SELECT 1 FROM rmas WHERE rma_id=?",
                "spare_part_unit": "SELECT 1 FROM spare_part_units WHERE spare_part_unit_id=?",
                "device_part_unit": "SELECT 1 FROM device_part_units WHERE device_part_unit_id=?",
                "fault_tag": "SELECT 1 FROM fault_tags WHERE fault_tag_id=?",
                "inventory_physical_consequence": (
                    "SELECT 1 FROM inventory_physical_consequences "
                    "WHERE physical_consequence_id=?"
                ),
                "task": "SELECT 1 FROM tasks WHERE task_id=?",
            }[target_kind]
            if connection.execute(exists_sql, (identity,)).fetchone() is None:
                raise ValidationError("Inventory history target does not exist")

            if target_kind == "spare_need":
                for row in connection.execute(
                    "SELECT need_event_id,event_kind,planned_quantity,reason_code,"
                    "effective_at_utc,recorded_at_utc,command_id "
                    "FROM spare_need_lifecycle_events WHERE spare_need_id=?",
                    (identity,),
                ).fetchall():
                    add(
                        recorded_at_utc=int(row[5]),
                        authority="spare_need_lifecycle",
                        event_kind=str(row[1]),
                        event_id=str(row[0]),
                        details={
                            "planned_quantity": None if row[2] is None else int(row[2]),
                            "reason_code": None if row[3] is None else str(row[3]),
                            "effective_at_utc": None if row[4] is None else int(row[4]),
                            "command_id": str(row[6]),
                        },
                    )
                for row in connection.execute(
                    "SELECT local_fulfillment_event_id,spare_part_unit_id,task_id,"
                    "event_kind,reason_code,recorded_at_utc,command_id "
                    "FROM local_need_fulfillment_events WHERE spare_need_id=?",
                    (identity,),
                ).fetchall():
                    add(
                        recorded_at_utc=int(row[5]),
                        authority="local_need_fulfillment",
                        event_kind=str(row[3]),
                        event_id=str(row[0]),
                        details={
                            "spare_part_unit_id": str(row[1]),
                            "task_id": None if row[2] is None else str(row[2]),
                            "reason_code": None if row[4] is None else str(row[4]),
                            "command_id": str(row[6]),
                        },
                    )

            elif target_kind == "spare_request":
                for row in connection.execute(
                    "SELECT request_event_id,event_kind,effective_at_utc,target_event_id,"
                    "reason_code,evidence_kind,evidence_id,recorded_at_utc,command_id "
                    "FROM spare_request_lifecycle_events WHERE spare_request_id=?",
                    (identity,),
                ).fetchall():
                    add(
                        recorded_at_utc=int(row[7]),
                        authority="spare_request_lifecycle",
                        event_kind=str(row[1]),
                        event_id=str(row[0]),
                        details={
                            "effective_at_utc": None if row[2] is None else int(row[2]),
                            "target_event_id": None if row[3] is None else str(row[3]),
                            "reason_code": None if row[4] is None else str(row[4]),
                            "evidence_kind": None if row[5] is None else str(row[5]),
                            "evidence_id": None if row[6] is None else str(row[6]),
                            "command_id": str(row[8]),
                        },
                    )
                for row in connection.execute(
                    "SELECT identifier_event_id,event_kind,prior_sr7,new_sr7,"
                    "reason_code,recorded_at_utc,command_id "
                    "FROM spare_request_identifier_events WHERE spare_request_id=?",
                    (identity,),
                ).fetchall():
                    add(
                        recorded_at_utc=int(row[5]),
                        authority="spare_request_identifier",
                        event_kind=str(row[1]),
                        event_id=str(row[0]),
                        details={
                            "prior_sr7": None if row[2] is None else str(row[2]),
                            "new_sr7": str(row[3]),
                            "reason_code": None if row[4] is None else str(row[4]),
                            "command_id": str(row[6]),
                        },
                    )

            elif target_kind == "rma":
                for row in connection.execute(
                    "SELECT identifier_event_id,event_kind,prior_c10,new_c10,"
                    "reason_code,recorded_at_utc,command_id "
                    "FROM rma_identifier_events WHERE rma_id=?",
                    (identity,),
                ).fetchall():
                    add(
                        recorded_at_utc=int(row[5]),
                        authority="rma_identifier",
                        event_kind=str(row[1]),
                        event_id=str(row[0]),
                        details={
                            "prior_c10": None if row[2] is None else str(row[2]),
                            "new_c10": str(row[3]),
                            "reason_code": None if row[4] is None else str(row[4]),
                            "command_id": str(row[6]),
                        },
                    )
                for row in connection.execute(
                    "SELECT assignment_event_id,event_kind,prior_device_part_unit_id,"
                    "new_device_part_unit_id,reason_code,recorded_at_utc,command_id "
                    "FROM rma_assignment_events WHERE rma_id=?",
                    (identity,),
                ).fetchall():
                    add(
                        recorded_at_utc=int(row[5]),
                        authority="rma_assignment",
                        event_kind=str(row[1]),
                        event_id=str(row[0]),
                        details={
                            "prior_device_part_unit_id": None
                            if row[2] is None
                            else str(row[2]),
                            "new_device_part_unit_id": None
                            if row[3] is None
                            else str(row[3]),
                            "reason_code": None if row[4] is None else str(row[4]),
                            "command_id": str(row[6]),
                        },
                    )
                for row in connection.execute(
                    "SELECT return_selection_event_id,event_kind,physical_consequence_id,"
                    "device_part_unit_id,spare_part_unit_id,reason_code,"
                    "effective_at_utc,target_event_id,recorded_at_utc,command_id "
                    "FROM rma_return_selection_events WHERE rma_id=?",
                    (identity,),
                ).fetchall():
                    add(
                        recorded_at_utc=int(row[8]),
                        authority="rma_return_selection",
                        event_kind=str(row[1]),
                        event_id=str(row[0]),
                        details={
                            "physical_consequence_id": str(row[2]),
                            "device_part_unit_id": None if row[3] is None else str(row[3]),
                            "spare_part_unit_id": None if row[4] is None else str(row[4]),
                            "reason_code": None if row[5] is None else str(row[5]),
                            "effective_at_utc": None if row[6] is None else int(row[6]),
                            "target_event_id": None if row[7] is None else str(row[7]),
                            "command_id": str(row[9]),
                        },
                    )
                for row in connection.execute(
                    "SELECT e.logistics_event_id,e.event_kind,e.effective_at_utc,"
                    "e.reason_code,e.recorded_at_utc,e.command_id,"
                    "p.logistics_rma_participant_id,p.active,p.close_reason "
                    "FROM logistics_rma_participants p "
                    "JOIN actual_logistics_events e "
                    "ON e.logistics_event_id=p.logistics_event_id "
                    "WHERE p.rma_id=?",
                    (identity,),
                ).fetchall():
                    add(
                        recorded_at_utc=int(row[4]),
                        authority="actual_logistics",
                        event_kind=str(row[1]),
                        event_id=str(row[0]),
                        details={
                            "effective_at_utc": None if row[2] is None else int(row[2]),
                            "reason_code": None if row[3] is None else str(row[3]),
                            "command_id": str(row[5]),
                            "participant_id": str(row[6]),
                            "active": bool(row[7]),
                            "close_reason": None if row[8] is None else str(row[8]),
                        },
                    )

            elif target_kind == "spare_part_unit":
                for row in connection.execute(
                    "SELECT unit_event_id,event_kind,condition_token,disposition_token,"
                    "effective_at_utc,target_event_id,reason_code,evidence_kind,evidence_id,"
                    "recorded_at_utc,command_id FROM spare_part_lifecycle_events "
                    "WHERE spare_part_unit_id=?",
                    (identity,),
                ).fetchall():
                    add(
                        recorded_at_utc=int(row[9]),
                        authority="spare_part_lifecycle",
                        event_kind=str(row[1]),
                        event_id=str(row[0]),
                        details={
                            "condition_token": None if row[2] is None else str(row[2]),
                            "disposition_token": None if row[3] is None else str(row[3]),
                            "effective_at_utc": None if row[4] is None else int(row[4]),
                            "target_event_id": None if row[5] is None else str(row[5]),
                            "reason_code": None if row[6] is None else str(row[6]),
                            "evidence_kind": None if row[7] is None else str(row[7]),
                            "evidence_id": None if row[8] is None else str(row[8]),
                            "command_id": str(row[10]),
                        },
                    )
                for row in connection.execute(
                    "SELECT allocation_event_id,event_kind,allocation_id,task_id,"
                    "spare_need_id,prior_task_id,reason_code,effective_at_utc,"
                    "target_event_id,recorded_at_utc,command_id "
                    "FROM task_unit_allocation_events WHERE spare_part_unit_id=?",
                    (identity,),
                ).fetchall():
                    add(
                        recorded_at_utc=int(row[9]),
                        authority="task_unit_allocation",
                        event_kind=str(row[1]),
                        event_id=str(row[0]),
                        details={
                            "allocation_id": str(row[2]),
                            "task_id": str(row[3]),
                            "spare_need_id": None if row[4] is None else str(row[4]),
                            "prior_task_id": None if row[5] is None else str(row[5]),
                            "reason_code": None if row[6] is None else str(row[6]),
                            "effective_at_utc": None if row[7] is None else int(row[7]),
                            "target_event_id": None if row[8] is None else str(row[8]),
                            "command_id": str(row[10]),
                        },
                    )

            elif target_kind == "device_part_unit":
                for row in connection.execute(
                    "SELECT device_part_event_id,event_kind,condition_token,"
                    "effective_at_utc,target_event_id,reason_code,evidence_kind,evidence_id,"
                    "recorded_at_utc,command_id FROM device_part_lifecycle_events "
                    "WHERE device_part_unit_id=?",
                    (identity,),
                ).fetchall():
                    add(
                        recorded_at_utc=int(row[8]),
                        authority="device_part_lifecycle",
                        event_kind=str(row[1]),
                        event_id=str(row[0]),
                        details={
                            "condition_token": None if row[2] is None else str(row[2]),
                            "effective_at_utc": None if row[3] is None else int(row[3]),
                            "target_event_id": None if row[4] is None else str(row[4]),
                            "reason_code": None if row[5] is None else str(row[5]),
                            "evidence_kind": None if row[6] is None else str(row[6]),
                            "evidence_id": None if row[7] is None else str(row[7]),
                            "command_id": str(row[9]),
                        },
                    )

            elif target_kind == "fault_tag":
                for row in connection.execute(
                    "SELECT fault_tag_event_id,event_kind,effective_at_utc,target_event_id,"
                    "reason_code,evidence_kind,evidence_id,recorded_at_utc,command_id "
                    "FROM fault_tag_lifecycle_events WHERE fault_tag_id=?",
                    (identity,),
                ).fetchall():
                    add(
                        recorded_at_utc=int(row[7]),
                        authority="fault_tag_lifecycle",
                        event_kind=str(row[1]),
                        event_id=str(row[0]),
                        details={
                            "effective_at_utc": None if row[2] is None else int(row[2]),
                            "target_event_id": None if row[3] is None else str(row[3]),
                            "reason_code": None if row[4] is None else str(row[4]),
                            "evidence_kind": None if row[5] is None else str(row[5]),
                            "evidence_id": None if row[6] is None else str(row[6]),
                            "command_id": str(row[8]),
                        },
                    )
                for row in connection.execute(
                    "SELECT e.membership_event_id,e.event_kind,e.effective_at_utc,"
                    "e.target_event_id,e.reason_code,e.evidence_kind,e.evidence_id,"
                    "e.recorded_at_utc,e.command_id,e.fault_tag_membership_id "
                    "FROM fault_tag_membership_events e "
                    "JOIN fault_tag_memberships m "
                    "ON m.fault_tag_membership_id=e.fault_tag_membership_id "
                    "WHERE m.fault_tag_id=?",
                    (identity,),
                ).fetchall():
                    add(
                        recorded_at_utc=int(row[7]),
                        authority="fault_tag_membership",
                        event_kind=str(row[1]),
                        event_id=str(row[0]),
                        details={
                            "fault_tag_membership_id": str(row[9]),
                            "effective_at_utc": None if row[2] is None else int(row[2]),
                            "target_event_id": None if row[3] is None else str(row[3]),
                            "reason_code": None if row[4] is None else str(row[4]),
                            "evidence_kind": None if row[5] is None else str(row[5]),
                            "evidence_id": None if row[6] is None else str(row[6]),
                            "command_id": str(row[8]),
                        },
                    )
                for row in connection.execute(
                    "SELECT fault_tag_lineage_id,relation_type,predecessor_fault_tag_id,"
                    "successor_fault_tag_id,reason_code,recorded_at_utc,command_id "
                    "FROM fault_tag_lineage WHERE predecessor_fault_tag_id=? "
                    "OR successor_fault_tag_id=?",
                    (identity, identity),
                ).fetchall():
                    add(
                        recorded_at_utc=int(row[5]),
                        authority="fault_tag_lineage",
                        event_kind=str(row[1]),
                        event_id=str(row[0]),
                        details={
                            "predecessor_fault_tag_id": str(row[2]),
                            "successor_fault_tag_id": str(row[3]),
                            "reason_code": str(row[4]),
                            "command_id": str(row[6]),
                        },
                    )

            elif target_kind == "inventory_physical_consequence":
                for row in connection.execute(
                    "SELECT consequence_event_id,event_kind,physical_disposition,"
                    "installed_spare_part_unit_id,removed_device_part_unit_id,"
                    "inbound_spare_part_unit_id,parent_dismantled_unit_id,"
                    "effective_at_utc,target_event_id,reason_code,recorded_at_utc,command_id "
                    "FROM physical_consequence_events WHERE physical_consequence_id=?",
                    (identity,),
                ).fetchall():
                    add(
                        recorded_at_utc=int(row[10]),
                        authority="physical_consequence",
                        event_kind=str(row[1]),
                        event_id=str(row[0]),
                        details={
                            "physical_disposition": str(row[2]),
                            "installed_spare_part_unit_id": None
                            if row[3] is None
                            else str(row[3]),
                            "removed_device_part_unit_id": None
                            if row[4] is None
                            else str(row[4]),
                            "inbound_spare_part_unit_id": None
                            if row[5] is None
                            else str(row[5]),
                            "parent_dismantled_unit_id": None
                            if row[6] is None
                            else str(row[6]),
                            "effective_at_utc": None if row[7] is None else int(row[7]),
                            "target_event_id": None if row[8] is None else str(row[8]),
                            "reason_code": None if row[9] is None else str(row[9]),
                            "command_id": str(row[11]),
                        },
                    )

            elif target_kind == "task":
                for row in connection.execute(
                    "SELECT allocation_event_id,event_kind,allocation_id,"
                    "spare_part_unit_id,spare_need_id,prior_task_id,reason_code,"
                    "effective_at_utc,target_event_id,recorded_at_utc,command_id "
                    "FROM task_unit_allocation_events WHERE task_id=?",
                    (identity,),
                ).fetchall():
                    add(
                        recorded_at_utc=int(row[9]),
                        authority="task_unit_allocation",
                        event_kind=str(row[1]),
                        event_id=str(row[0]),
                        details={
                            "allocation_id": str(row[2]),
                            "spare_part_unit_id": str(row[3]),
                            "spare_need_id": None if row[4] is None else str(row[4]),
                            "prior_task_id": None if row[5] is None else str(row[5]),
                            "reason_code": None if row[6] is None else str(row[6]),
                            "effective_at_utc": None if row[7] is None else int(row[7]),
                            "target_event_id": None if row[8] is None else str(row[8]),
                            "command_id": str(row[10]),
                        },
                    )
                for row in connection.execute(
                    "SELECT e.consequence_event_id,e.event_kind,e.physical_disposition,"
                    "e.recorded_at_utc,e.command_id,i.physical_consequence_id "
                    "FROM inventory_physical_consequences i "
                    "JOIN physical_consequence_events e "
                    "ON e.physical_consequence_id=i.physical_consequence_id "
                    "WHERE i.task_id=?",
                    (identity,),
                ).fetchall():
                    add(
                        recorded_at_utc=int(row[3]),
                        authority="physical_consequence",
                        event_kind=str(row[1]),
                        event_id=str(row[0]),
                        details={
                            "physical_consequence_id": str(row[5]),
                            "physical_disposition": str(row[2]),
                            "command_id": str(row[4]),
                        },
                    )

            audit_rows = connection.execute(
                "SELECT DISTINCT a.audit_event_id,a.action_type,a.recorded_at_utc,"
                "a.command_id,a.reason_category,a.target_type,a.target_id "
                "FROM audit_events a LEFT JOIN audit_event_results r "
                "ON r.audit_event_id=a.audit_event_id "
                "WHERE (a.target_type=? AND a.target_id=?) OR r.result_id=?",
                (target_kind, identity, identity),
            ).fetchall()
            for row in audit_rows:
                add(
                    recorded_at_utc=int(row[2]),
                    authority="application_audit",
                    event_kind=str(row[1]),
                    event_id=str(row[0]),
                    details={
                        "command_id": str(row[3]),
                        "reason_category": None if row[4] is None else str(row[4]),
                        "audit_target_type": str(row[5]),
                        "audit_target_id": None if row[6] is None else str(row[6]),
                    },
                )

            proposal_column = {
                "spare_request": "spare_request_id",
                "rma": "rma_id",
                "spare_part_unit": "spare_part_unit_id",
                "fault_tag": "fault_tag_id",
            }.get(target_kind)
            if proposal_column is not None:
                proposal_rows = connection.execute(
                    "SELECT DISTINCT p.inventory_proposal_id,p.proposal_kind,p.state,"
                    "p.evidence_kind,p.evidence_id,p.source_proposal_key,p.risk_tier,"
                    "p.created_at_utc,p.revision "
                    "FROM inventory_proposals p JOIN inventory_proposal_targets t "
                    "ON t.inventory_proposal_id=p.inventory_proposal_id "
                    f"WHERE t.{proposal_column}=?",
                    (identity,),
                ).fetchall()
                for row in proposal_rows:
                    add(
                        recorded_at_utc=int(row[7]),
                        authority="inventory_proposal",
                        event_kind=str(row[1]),
                        event_id=str(row[0]),
                        details={
                            "state": str(row[2]),
                            "evidence_kind": str(row[3]),
                            "evidence_id": str(row[4]),
                            "source_proposal_key": str(row[5]),
                            "risk_tier": str(row[6]),
                            "revision": int(row[8]),
                        },
                    )

        entries.sort(key=lambda item: item[0])
        if after is not None:
            entries = [item for item in entries if item[0] > after]
        total = len(entries)
        selected = entries[:limit]
        continuation = None
        if len(entries) > limit and selected:
            continuation = {
                "version": 1,
                "query_id": _HISTORY_QUERY_ID,
                "sort_registry_id": _HISTORY_SORT_ID,
                "last_key_tuple": list(selected[-1][0]),
                "filter_fingerprint": fingerprint,
                "null_order": "not_applicable",
            }
        return InventoryHistoryPage(
            items=tuple(item for _key, item in selected),
            continuation=continuation,
            exact_total=total,
        )


__all__ = [
    "InventoryAttentionQueryService",
    "InventoryHistoryPage",
    "SpareRequestResponseAttention",
]
