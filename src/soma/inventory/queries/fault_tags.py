from __future__ import annotations

from soma.foundation.errors import IntegrityFailure, ValidationError
from soma.foundation.identifiers import require_uuid4
from soma.foundation.persistence.connections import ConnectionFactory
from soma.foundation.persistence.uow import ReadSnapshot
from soma.foundation.strict_json import sha256_canonical_json

from ..repositories.fault_tags import InventoryFaultTagsRepository

_CURSOR_FIELDS = frozenset(
    {
        "version",
        "query_id",
        "sort_registry_id",
        "last_key_tuple",
        "filter_fingerprint",
        "null_order",
    }
)
_FAULT_TAG_LIST_QUERY_ID = "FaultTagListQuery"
_FAULT_TAG_LIST_SORT_ID = "INVENTORY_FAULT_TAG_TRACKING_ASC_V1"
_ELIGIBLE_QUERY_ID = "EligibleFaultTagMembershipQuery"
_ELIGIBLE_SORT_ID = "INVENTORY_ELIGIBLE_RMA_C10_ASC_V1"
_WAREHOUSE_QUERY_ID = "WarehouseQueueQuery"
_WAREHOUSE_SORT_ID = "INVENTORY_WAREHOUSE_TRACKING_MEMBERSHIP_ASC_V1"



class FaultTagQueryService:
    def __init__(self, connection_factory: ConnectionFactory) -> None:
        self._factory = connection_factory

    @staticmethod
    def _limit(value: int) -> int:
        if type(value) is not int or not 1 <= value <= 500:
            raise ValidationError("limit must be an integer from 1 through 500")
        return value

    @staticmethod
    def _decode_cursor(
        cursor: dict[str, object] | None,
        *,
        query_id: str,
        sort_id: str,
        filter_fingerprint: str,
        key_length: int,
    ) -> tuple[str, ...] | None:
        if cursor is None:
            return None
        if not isinstance(cursor, dict) or set(cursor) != _CURSOR_FIELDS:
            raise ValidationError("Fault Tag cursor shape is invalid")
        if (
            cursor["version"] != 1
            or cursor["query_id"] != query_id
            or cursor["sort_registry_id"] != sort_id
            or cursor["filter_fingerprint"] != filter_fingerprint
            or cursor["null_order"] != "not_applicable"
        ):
            raise ValidationError("Fault Tag cursor contract is invalid")
        key = cursor["last_key_tuple"]
        if (
            not isinstance(key, list)
            or len(key) != key_length
            or any(not isinstance(value, str) for value in key)
        ):
            raise ValidationError("Fault Tag cursor key is invalid")
        return tuple(str(value) for value in key)

    @staticmethod
    def _page(
        projected: list[tuple[tuple[str, ...], dict[str, object]]],
        *,
        after: tuple[str, ...] | None,
        limit: int,
        query_id: str,
        sort_id: str,
        filter_fingerprint: str,
    ) -> dict[str, object]:
        projected.sort(key=lambda item: item[0])
        if after is not None:
            projected = [item for item in projected if item[0] > after]
        total = len(projected)
        selected = projected[:limit]
        continuation = None
        if len(projected) > limit and selected:
            continuation = {
                "version": 1,
                "query_id": query_id,
                "sort_registry_id": sort_id,
                "last_key_tuple": list(selected[-1][0]),
                "filter_fingerprint": filter_fingerprint,
                "null_order": "not_applicable",
            }
        return {
            "items": [item for _key, item in selected],
            "continuation": continuation,
            "exact_total": total,
        }

    def list_fault_tags(
        self,
        *,
        state: str | None = None,
        archived: bool | None = None,
        attention_required: bool | None = None,
        service_request_id: str | None = None,
        official_sr7: str | None = None,
        current_c10: str | None = None,
        cursor: dict[str, object] | None = None,
        limit: int = 100,
    ) -> dict[str, object]:
        page_limit = self._limit(limit)
        if archived is not None and type(archived) is not bool:
            raise ValidationError("archived must be boolean or null")
        if attention_required is not None and type(attention_required) is not bool:
            raise ValidationError("attention_required must be boolean or null")
        sr_id = None if service_request_id is None else require_uuid4(service_request_id)
        filter_fingerprint = sha256_canonical_json(
            {
                "schema": "SOMA_FAULT_TAG_LIST_FILTER_V1",
                "state": state,
                "archived": archived,
                "attention_required": attention_required,
                "service_request_id": sr_id,
                "official_sr7": official_sr7,
                "current_c10": current_c10,
            }
        )
        after = self._decode_cursor(
            cursor,
            query_id=_FAULT_TAG_LIST_QUERY_ID,
            sort_id=_FAULT_TAG_LIST_SORT_ID,
            filter_fingerprint=filter_fingerprint,
            key_length=2,
        )
        projected: list[tuple[tuple[str, ...], dict[str, object]]] = []
        with ReadSnapshot(self._factory) as snapshot:
            rows = snapshot.connection.execute(
                "SELECT t.fault_tag_id,t.tracking_id,p.state,p.archived,"
                "p.submitted_member_count,p.awaiting_receipt_count,"
                "p.awaiting_final_count,p.accepted_count,p.rejected_count,"
                "p.revision,p.input_fingerprint "
                "FROM fault_tags t JOIN fault_tag_current_projection p "
                "ON p.fault_tag_id=t.fault_tag_id "
                "ORDER BY t.tracking_id,t.fault_tag_id"
            ).fetchall()
            for row in rows:
                tag_id = str(row[0])
                if state is not None and str(row[2]) != state:
                    continue
                if archived is not None and bool(row[3]) != archived:
                    continue
                context_rows = snapshot.connection.execute(
                    "SELECT DISTINCT rq.service_request_id,rq.spare_request_id,"
                    "rp.current_sr7,a.c10,m.rma_id "
                    "FROM fault_tag_memberships m "
                    "JOIN rmas r ON r.rma_id=m.rma_id "
                    "JOIN spare_requests rq ON rq.spare_request_id=r.spare_request_id "
                    "JOIN spare_request_current_projection rp "
                    "ON rp.spare_request_id=rq.spare_request_id "
                    "JOIN rma_identifier_aliases a "
                    "ON a.rma_id=r.rma_id AND a.alias_kind='current' "
                    "WHERE m.fault_tag_id=? "
                    "ORDER BY rq.service_request_id,rq.spare_request_id,m.rma_id",
                    (tag_id,),
                ).fetchall()
                sr_ids = sorted({str(item[0]) for item in context_rows})
                request_ids = sorted({str(item[1]) for item in context_rows})
                sr7s = sorted(
                    {str(item[2]) for item in context_rows if item[2] is not None}
                )
                c10s = sorted({str(item[3]) for item in context_rows})
                if sr_id is not None and sr_id not in sr_ids:
                    continue
                if official_sr7 is not None and official_sr7 not in sr7s:
                    continue
                if current_c10 is not None and current_c10 not in c10s:
                    continue
                attention_count = int(
                    snapshot.connection.execute(
                        "SELECT COUNT(*) FROM inventory_attention_projection a "
                        "WHERE (a.target_kind='fault_tag' AND a.target_id=?) "
                        "OR (a.target_kind='rma' AND a.target_id IN "
                        "(SELECT rma_id FROM fault_tag_memberships WHERE fault_tag_id=?))",
                        (tag_id, tag_id),
                    ).fetchone()[0]
                )
                if (
                    attention_required is not None
                    and (attention_count > 0) != attention_required
                ):
                    continue
                open_count = int(
                    snapshot.connection.execute(
                        "SELECT COUNT(*) FROM rma_return_obligation_current o "
                        "WHERE o.rma_id IN "
                        "(SELECT rma_id FROM fault_tag_memberships WHERE fault_tag_id=?) "
                        "AND o.obligation_state='open'",
                        (tag_id,),
                    ).fetchone()[0]
                )
                lineage = InventoryFaultTagsRepository.lineage_authority(
                    snapshot.connection,
                    tag_id,
                )
                blockers: list[str] = []
                if int(row[5]) > 0:
                    blockers.append("warehouse_receipt_pending")
                if int(row[6]) > 0:
                    blockers.append("warehouse_final_decision_pending")
                if int(row[8]) > 0 and open_count > 0:
                    blockers.append("rejected_return_action_required")
                projected.append(
                    (
                        (str(row[1]), tag_id),
                        {
                            "fault_tag_id": tag_id,
                            "tracking_id": str(row[1]),
                            "state": str(row[2]),
                            "archived": bool(row[3]),
                            "submitted_member_count": int(row[4]),
                            "awaiting_receipt_count": int(row[5]),
                            "awaiting_final_count": int(row[6]),
                            "accepted_count": int(row[7]),
                            "rejected_count": int(row[8]),
                            "open_obligation_count": open_count,
                            "attention_count": attention_count,
                            "service_request_ids": sr_ids,
                            "spare_request_ids": request_ids,
                            "current_sr7s": sr7s,
                            "current_c10s": c10s,
                            "service_request_diversity_count": len(sr_ids),
                            "spare_request_diversity_count": len(request_ids),
                            "has_correction_predecessor": any(
                                item["relation_type"] == "corrects_replaces"
                                and item["successor_fault_tag_id"] == tag_id
                                for item in lineage["lineage"]
                            ),
                            "has_correction_successor": any(
                                item["relation_type"] == "corrects_replaces"
                                and item["predecessor_fault_tag_id"] == tag_id
                                for item in lineage["lineage"]
                            ),
                            "has_resend_predecessor": any(
                                item["relation_type"] == "resend_of"
                                and item["successor_fault_tag_id"] == tag_id
                                for item in lineage["lineage"]
                            ),
                            "has_resend_successors": any(
                                item["relation_type"] == "resend_of"
                                and item["predecessor_fault_tag_id"] == tag_id
                                for item in lineage["lineage"]
                            ),
                            "action_blockers": blockers,
                            "revision": int(row[9]),
                            "input_fingerprint": str(row[10]),
                        },
                    )
                )
        return self._page(
            projected,
            after=after,
            limit=page_limit,
            query_id=_FAULT_TAG_LIST_QUERY_ID,
            sort_id=_FAULT_TAG_LIST_SORT_ID,
            filter_fingerprint=filter_fingerprint,
        )

    def eligible_memberships(
        self,
        *,
        service_request_id: str | None = None,
        spare_request_id: str | None = None,
        rma_id: str | None = None,
        bom_code: str | None = None,
        cursor: dict[str, object] | None = None,
        limit: int = 100,
    ) -> dict[str, object]:
        page_limit = self._limit(limit)
        sr_id = None if service_request_id is None else require_uuid4(service_request_id)
        request_id = None if spare_request_id is None else require_uuid4(spare_request_id)
        requested_rma = None if rma_id is None else require_uuid4(rma_id)
        filter_fingerprint = sha256_canonical_json(
            {
                "schema": "SOMA_ELIGIBLE_FAULT_TAG_MEMBERSHIP_FILTER_V1",
                "service_request_id": sr_id,
                "spare_request_id": request_id,
                "rma_id": requested_rma,
                "bom_code": bom_code,
            }
        )
        after = self._decode_cursor(
            cursor,
            query_id=_ELIGIBLE_QUERY_ID,
            sort_id=_ELIGIBLE_SORT_ID,
            filter_fingerprint=filter_fingerprint,
            key_length=2,
        )
        projected: list[tuple[tuple[str, ...], dict[str, object]]] = []
        with ReadSnapshot(self._factory) as snapshot:
            rows = snapshot.connection.execute(
                "SELECT o.rma_id,o.device_part_unit_id,o.spare_part_unit_id,"
                "o.physical_consequence_id,o.revision,a.c10,r.promised_bom_code,"
                "rq.spare_request_id,rq.service_request_id,l.state,"
                "c.task_review_fingerprint,c.revision,c.input_fingerprint "
                "FROM rma_return_obligation_current o "
                "JOIN rmas r ON r.rma_id=o.rma_id "
                "JOIN spare_requests rq ON rq.spare_request_id=r.spare_request_id "
                "JOIN rma_identifier_aliases a "
                "ON a.rma_id=r.rma_id AND a.alias_kind='current' "
                "JOIN rma_lifecycle_projection l ON l.rma_id=r.rma_id "
                "JOIN physical_consequence_current c "
                "ON c.physical_consequence_id=o.physical_consequence_id "
                "WHERE o.obligation_state='open' "
                "ORDER BY a.c10,o.rma_id"
            ).fetchall()
            for row in rows:
                current_rma = str(row[0])
                if requested_rma is not None and current_rma != requested_rma:
                    continue
                if request_id is not None and str(row[7]) != request_id:
                    continue
                if sr_id is not None and str(row[8]) != sr_id:
                    continue
                if bom_code is not None and str(row[6]) != bom_code:
                    continue
                if (row[1] is None) == (row[2] is None):
                    raise IntegrityFailure(
                        "Open return obligation has invalid typed unit authority"
                    )
                unit_kind = (
                    "device_part_unit" if row[1] is not None else "spare_part_unit"
                )
                unit_id = str(row[1] if row[1] is not None else row[2])
                if unit_kind == "device_part_unit":
                    unit = snapshot.connection.execute(
                        "SELECT bom_code,manufacturer_serial FROM device_part_units "
                        "WHERE device_part_unit_id=?",
                        (unit_id,),
                    ).fetchone()
                    conflict = snapshot.connection.execute(
                        "SELECT c.fault_tag_membership_id,c.fault_tag_id,c.state "
                        "FROM fault_tag_membership_current c "
                        "WHERE c.device_part_unit_id=? AND c.active_submitted=1",
                        (unit_id,),
                    ).fetchone()
                else:
                    unit = snapshot.connection.execute(
                        "SELECT bom_code,manufacturer_serial FROM spare_part_units "
                        "WHERE spare_part_unit_id=?",
                        (unit_id,),
                    ).fetchone()
                    conflict = snapshot.connection.execute(
                        "SELECT c.fault_tag_membership_id,c.fault_tag_id,c.state "
                        "FROM fault_tag_membership_current c "
                        "WHERE c.spare_part_unit_id=? AND c.active_submitted=1",
                        (unit_id,),
                    ).fetchone()
                if unit is None:
                    raise IntegrityFailure(
                        "Open return obligation points to missing physical unit"
                    )
                rma_conflict = snapshot.connection.execute(
                    "SELECT fault_tag_membership_id,fault_tag_id,state "
                    "FROM fault_tag_membership_current "
                    "WHERE rma_id=? AND active_submitted=1",
                    (current_rma,),
                ).fetchone()
                active_conflict = rma_conflict if rma_conflict is not None else conflict
                projected.append(
                    (
                        (str(row[5]), current_rma),
                        {
                            "rma_id": current_rma,
                            "current_c10": str(row[5]),
                            "spare_request_id": str(row[7]),
                            "service_request_id": str(row[8]),
                            "promised_bom_code": str(row[6]),
                            "rma_state": str(row[9]),
                            "obligation_revision": int(row[4]),
                            "physical_consequence_id": str(row[3]),
                            "task_review_fingerprint": str(row[10]),
                            "physical_consequence_revision": int(row[11]),
                            "physical_consequence_fingerprint": str(row[12]),
                            "return_unit": {
                                "kind": unit_kind,
                                "id": unit_id,
                                "bom_code": str(unit[0]),
                                "manufacturer_serial": None
                                if unit[1] is None
                                else str(unit[1]),
                            },
                            "eligible": active_conflict is None,
                            "conflict_reason": None
                            if active_conflict is None
                            else "active_submitted_fault_tag_membership",
                            "active_submitted_membership": None
                            if active_conflict is None
                            else {
                                "fault_tag_membership_id": str(active_conflict[0]),
                                "fault_tag_id": str(active_conflict[1]),
                                "state": str(active_conflict[2]),
                            },
                        },
                    )
                )
        return self._page(
            projected,
            after=after,
            limit=page_limit,
            query_id=_ELIGIBLE_QUERY_ID,
            sort_id=_ELIGIBLE_SORT_ID,
            filter_fingerprint=filter_fingerprint,
        )

    def warehouse_queue(
        self,
        *,
        queue_state: str,
        cursor: dict[str, object] | None = None,
        limit: int = 100,
    ) -> dict[str, object]:
        page_limit = self._limit(limit)
        state_map = {
            "awaiting_receipt": "submitted_awaiting_receipt",
            "awaiting_final": "warehouse_received",
            "rejected": "rejected",
        }
        if queue_state not in state_map:
            raise ValidationError("Warehouse queue state is invalid")
        membership_state = state_map[queue_state]
        filter_fingerprint = sha256_canonical_json(
            {
                "schema": "SOMA_WAREHOUSE_QUEUE_FILTER_V1",
                "queue_state": queue_state,
            }
        )
        after = self._decode_cursor(
            cursor,
            query_id=_WAREHOUSE_QUERY_ID,
            sort_id=_WAREHOUSE_SORT_ID,
            filter_fingerprint=filter_fingerprint,
            key_length=3,
        )
        projected: list[tuple[tuple[str, ...], dict[str, object]]] = []
        with ReadSnapshot(self._factory) as snapshot:
            rows = snapshot.connection.execute(
                "SELECT c.fault_tag_membership_id,c.fault_tag_id,c.rma_id,"
                "c.device_part_unit_id,c.spare_part_unit_id,c.state,c.revision,"
                "c.last_event_id,t.tracking_id,a.c10,rq.spare_request_id,"
                "rq.service_request_id,l.current_target_device_part_unit_id "
                "FROM fault_tag_membership_current c "
                "JOIN fault_tags t ON t.fault_tag_id=c.fault_tag_id "
                "JOIN rmas r ON r.rma_id=c.rma_id "
                "JOIN rma_identifier_aliases a "
                "ON a.rma_id=r.rma_id AND a.alias_kind='current' "
                "JOIN spare_requests rq ON rq.spare_request_id=r.spare_request_id "
                "JOIN rma_lifecycle_projection l ON l.rma_id=r.rma_id "
                "WHERE c.state=? "
                "ORDER BY t.tracking_id,c.fault_tag_id,c.fault_tag_membership_id",
                (membership_state,),
            ).fetchall()
            for row in rows:
                membership_id = str(row[0])
                chronology = snapshot.connection.execute(
                    "SELECT membership_event_id,event_kind,effective_at_utc,"
                    "reason_code,recorded_at_utc "
                    "FROM fault_tag_membership_events "
                    "WHERE fault_tag_membership_id=? "
                    "ORDER BY recorded_at_utc,membership_event_id",
                    (membership_id,),
                ).fetchall()
                proposals = snapshot.connection.execute(
                    "SELECT p.inventory_proposal_id,p.proposal_kind,p.state,p.risk_tier,"
                    "p.revision,p.input_fingerprint "
                    "FROM inventory_proposals p JOIN inventory_proposal_targets x "
                    "ON x.inventory_proposal_id=p.inventory_proposal_id "
                    "WHERE x.fault_tag_membership_id=? "
                    "ORDER BY p.created_at_utc,p.inventory_proposal_id",
                    (membership_id,),
                ).fetchall()
                actions = (
                    ["record_warehouse_receipt"]
                    if queue_state == "awaiting_receipt"
                    else ["record_warehouse_final_decision"]
                    if queue_state == "awaiting_final"
                    else ["create_fault_tag_resend"]
                )
                if proposals:
                    actions.append("review_inventory_proposal")
                projected.append(
                    (
                        (str(row[8]), str(row[1]), membership_id),
                        {
                            "fault_tag_membership_id": membership_id,
                            "fault_tag_id": str(row[1]),
                            "fault_tag_tracking_id": str(row[8]),
                            "rma_id": str(row[2]),
                            "current_c10": str(row[9]),
                            "return_unit": {
                                "kind": "device_part_unit"
                                if row[3] is not None
                                else "spare_part_unit",
                                "id": str(row[3] if row[3] is not None else row[4]),
                            },
                            "state": str(row[5]),
                            "revision": int(row[6]),
                            "last_event_id": str(row[7]),
                            "spare_request_id": str(row[10]),
                            "service_request_id": str(row[11]),
                            "target_device_part_unit_id": None
                            if row[12] is None
                            else str(row[12]),
                            "chronology": [
                                {
                                    "membership_event_id": str(item[0]),
                                    "event_kind": str(item[1]),
                                    "effective_at_utc": None
                                    if item[2] is None
                                    else int(item[2]),
                                    "reason_code": None
                                    if item[3] is None
                                    else str(item[3]),
                                    "recorded_at_utc": int(item[4]),
                                }
                                for item in chronology
                            ],
                            "proposals": [
                                {
                                    "inventory_proposal_id": str(item[0]),
                                    "proposal_kind": str(item[1]),
                                    "state": str(item[2]),
                                    "risk_tier": str(item[3]),
                                    "revision": int(item[4]),
                                    "input_fingerprint": str(item[5]),
                                }
                                for item in proposals
                            ],
                            "governed_actions": actions,
                        },
                    )
                )
        return self._page(
            projected,
            after=after,
            limit=page_limit,
            query_id=_WAREHOUSE_QUERY_ID,
            sort_id=_WAREHOUSE_SORT_ID,
            filter_fingerprint=filter_fingerprint,
        )

    def get_fault_tag(self, fault_tag_id: str) -> dict[str, object]:
        identity = require_uuid4(fault_tag_id)
        with ReadSnapshot(self._factory) as snapshot:
            return InventoryFaultTagsRepository.response(snapshot.connection, identity)

    def lineage(self, fault_tag_id: str) -> dict[str, object]:
        identity = require_uuid4(fault_tag_id)
        with ReadSnapshot(self._factory) as snapshot:
            authority = InventoryFaultTagsRepository.lineage_authority(
                snapshot.connection,
                identity,
            )
        return {
            "fault_tag_id": identity,
            "state": authority["state"],
            "projection_revision": authority["projection_revision"],
            "lineage_fingerprint": authority["fingerprint"],
            "correction_chain": [
                item
                for item in authority["lineage"]
                if item["relation_type"] == "corrects_replaces"
            ],
            "resend_edges": [
                item
                for item in authority["lineage"]
                if item["relation_type"] == "resend_of"
            ],
        }


__all__ = ["FaultTagQueryService"]
