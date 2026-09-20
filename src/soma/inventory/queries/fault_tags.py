from __future__ import annotations

from soma.foundation.errors import SomaError, ValidationError
from soma.foundation.identifiers import require_uuid4
from soma.foundation.persistence.connections import ConnectionFactory
from soma.foundation.persistence.uow import ReadSnapshot


class InventoryFaultTagQueryService:
    def __init__(self, connection_factory: ConnectionFactory) -> None:
        self._factory = connection_factory

    def list_tags(
        self,
        *,
        state: str | None = None,
        archived: bool | None = None,
        after_id: str | None = None,
        limit: int = 100,
    ) -> dict[str, object]:
        if type(limit) is not int or not 1 <= limit <= 500:
            raise ValidationError("limit must be in 1..500")
        after = None if after_id is None else require_uuid4(after_id)
        clauses: list[str] = []
        params: list[object] = []
        if state is not None:
            clauses.append("p.state=?")
            params.append(state)
        if archived is not None:
            clauses.append("p.archived=?")
            params.append(1 if archived else 0)
        base_where = "" if not clauses else " WHERE " + " AND ".join(clauses)
        with ReadSnapshot(self._factory) as snapshot:
            total = int(snapshot.connection.execute(
                "SELECT COUNT(*) FROM fault_tags t JOIN fault_tag_current_projection p "
                "ON p.fault_tag_id=t.fault_tag_id" + base_where,
                tuple(params),
            ).fetchone()[0])
            if after is not None:
                clauses.append("t.fault_tag_id>?")
                params.append(after)
            where = "" if not clauses else " WHERE " + " AND ".join(clauses)
            rows = snapshot.connection.execute(
                "SELECT t.fault_tag_id,t.tracking_id,p.state,p.archived,"
                "p.submitted_member_count,p.awaiting_receipt_count,p.awaiting_final_count,"
                "p.accepted_count,p.rejected_count,p.revision "
                "FROM fault_tags t JOIN fault_tag_current_projection p "
                "ON p.fault_tag_id=t.fault_tag_id" + where
                + " ORDER BY t.fault_tag_id LIMIT ?",
                (*params, limit + 1),
            ).fetchall()
            page=rows[:limit]
            return {
                "items": [
                    {
                        "fault_tag_id": str(x[0]),
                        "tracking_handle": str(x[1]),
                        "state": str(x[2]),
                        "archived": bool(int(x[3])),
                        "submitted_member_count": int(x[4]),
                        "awaiting_receipt_count": int(x[5]),
                        "awaiting_final_count": int(x[6]),
                        "accepted_count": int(x[7]),
                        "rejected_count": int(x[8]),
                        "revision": int(x[9]),
                    }
                    for x in page
                ],
                "continuation": str(page[-1][0]) if len(rows)>limit and page else None,
                "exact_total": total,
            }

    def detail(self, fault_tag_id: str) -> dict[str, object]:
        identity=require_uuid4(fault_tag_id)
        with ReadSnapshot(self._factory) as snapshot:
            tag=snapshot.connection.execute(
                "SELECT t.fault_tag_id,t.tracking_id,t.draft_return_method,"
                "t.draft_pickup_dispatch_location_id,t.draft_pickup_contact_id,"
                "t.draft_pickup_instructions,t.draft_revision,p.state,p.archived,"
                "p.current_submission_snapshot_id,p.submitted_member_count,"
                "p.awaiting_receipt_count,p.awaiting_final_count,p.accepted_count,"
                "p.rejected_count,p.revision FROM fault_tags t "
                "JOIN fault_tag_current_projection p ON p.fault_tag_id=t.fault_tag_id "
                "WHERE t.fault_tag_id=?",
                (identity,),
            ).fetchone()
            if tag is None:
                raise SomaError("NOT_FOUND","Fault Tag does not exist")
            members=snapshot.connection.execute(
                "SELECT m.fault_tag_membership_id,m.rma_id,m.physical_consequence_id,"
                "m.device_part_unit_id,m.spare_part_unit_id,m.return_reason,"
                "c.state,c.active_submitted,c.revision FROM fault_tag_memberships m "
                "JOIN fault_tag_membership_current c "
                "ON c.fault_tag_membership_id=m.fault_tag_membership_id "
                "WHERE m.fault_tag_id=? ORDER BY m.rma_id,m.fault_tag_membership_id",
                (identity,),
            ).fetchall()
            snapshots=snapshot.connection.execute(
                "SELECT fault_tag_submission_snapshot_id,submission_event_id,tracking_id,"
                "return_method,pickup_dispatch_location_id,pickup_location_name_snapshot,"
                "pickup_location_address_snapshot,pickup_contact_id,"
                "pickup_contact_snapshot_json,pickup_instructions_snapshot,"
                "effective_submission_at_utc,recorded_at_utc,snapshot_hash "
                "FROM fault_tag_submission_snapshots WHERE fault_tag_id=? "
                "ORDER BY recorded_at_utc,fault_tag_submission_snapshot_id",
                (identity,),
            ).fetchall()
            lineage=snapshot.connection.execute(
                "SELECT fault_tag_lineage_id,relation_type,predecessor_fault_tag_id,"
                "successor_fault_tag_id,reason_code,recorded_at_utc "
                "FROM fault_tag_lineage WHERE predecessor_fault_tag_id=? "
                "OR successor_fault_tag_id=? ORDER BY recorded_at_utc,fault_tag_lineage_id",
                (identity,identity),
            ).fetchall()
            return {
                "fault_tag_id":str(tag[0]),"tracking_handle":str(tag[1]),
                "draft_return_method":str(tag[2]),
                "draft_pickup_dispatch_location_id":None if tag[3] is None else str(tag[3]),
                "draft_pickup_contact_id":None if tag[4] is None else str(tag[4]),
                "draft_pickup_instructions":None if tag[5] is None else str(tag[5]),
                "draft_revision":int(tag[6]),"state":str(tag[7]),
                "archived":bool(int(tag[8])),
                "current_submission_snapshot_id":None if tag[9] is None else str(tag[9]),
                "counts":{"submitted":int(tag[10]),"awaiting_receipt":int(tag[11]),
                    "awaiting_final":int(tag[12]),"accepted":int(tag[13]),"rejected":int(tag[14])},
                "revision":int(tag[15]),
                "members":[{"fault_tag_membership_id":str(x[0]),"rma_id":str(x[1]),
                    "physical_consequence_id":str(x[2]),
                    "device_part_unit_id":None if x[3] is None else str(x[3]),
                    "spare_part_unit_id":None if x[4] is None else str(x[4]),
                    "return_reason":str(x[5]),"state":str(x[6]),
                    "active_submitted":bool(int(x[7])),"revision":int(x[8])} for x in members],
                "submission_history":[{"snapshot_id":str(x[0]),"submission_event_id":str(x[1]),
                    "tracking_id":str(x[2]),"return_method":str(x[3]),
                    "pickup_dispatch_location_id":None if x[4] is None else str(x[4]),
                    "pickup_location_name_snapshot":None if x[5] is None else str(x[5]),
                    "pickup_location_address_snapshot":None if x[6] is None else str(x[6]),
                    "pickup_contact_id":None if x[7] is None else str(x[7]),
                    "pickup_contact_snapshot_json":None if x[8] is None else str(x[8]),
                    "pickup_instructions_snapshot":None if x[9] is None else str(x[9]),
                    "effective_submission_at_utc":None if x[10] is None else int(x[10]),
                    "recorded_at_utc":int(x[11]),"snapshot_hash":str(x[12])} for x in snapshots],
                "lineage":[{"lineage_id":str(x[0]),"relation_type":str(x[1]),
                    "predecessor_fault_tag_id":str(x[2]),"successor_fault_tag_id":str(x[3]),
                    "reason_code":str(x[4]),"recorded_at_utc":int(x[5])} for x in lineage],
            }

    def eligible_memberships(self, *, after_rma_id: str | None=None, limit:int=100)->dict[str,object]:
        if type(limit) is not int or not 1<=limit<=500:
            raise ValidationError("limit must be in 1..500")
        after=None if after_rma_id is None else require_uuid4(after_rma_id)
        params:list[object]=[]
        clause=""
        if after is not None:
            clause=" AND o.rma_id>?"
            params.append(after)
        with ReadSnapshot(self._factory) as snapshot:
            rows=snapshot.connection.execute(
                "SELECT o.rma_id,o.device_part_unit_id,o.spare_part_unit_id,"
                "o.physical_consequence_id,o.revision,a.c10 "
                "FROM rma_return_obligation_current o "
                "JOIN rma_identifier_aliases a ON a.rma_id=o.rma_id AND a.alias_kind='current' "
                "WHERE o.obligation_state='open' "
                "AND NOT EXISTS (SELECT 1 FROM fault_tag_membership_current c "
                "WHERE c.rma_id=o.rma_id AND c.active_submitted=1)"
                +clause+" ORDER BY o.rma_id LIMIT ?",
                (*params,limit+1),
            ).fetchall()
            page=rows[:limit]
            return {"items":[{"rma_id":str(x[0]),
                "device_part_unit_id":None if x[1] is None else str(x[1]),
                "spare_part_unit_id":None if x[2] is None else str(x[2]),
                "physical_consequence_id":str(x[3]),"revision":int(x[4]),
                "current_c10":str(x[5])} for x in page],
                "continuation":str(page[-1][0]) if len(rows)>limit and page else None}

    def warehouse_queue(self, *, after_membership_id:str|None=None, limit:int=100)->dict[str,object]:
        if type(limit) is not int or not 1<=limit<=500:
            raise ValidationError("limit must be in 1..500")
        after=None if after_membership_id is None else require_uuid4(after_membership_id)
        params:list[object]=[]
        clause=""
        if after is not None:
            clause=" AND c.fault_tag_membership_id>?"
            params.append(after)
        with ReadSnapshot(self._factory) as snapshot:
            rows=snapshot.connection.execute(
                "SELECT c.fault_tag_membership_id,c.fault_tag_id,c.rma_id,c.state,"
                "c.device_part_unit_id,c.spare_part_unit_id,c.revision "
                "FROM fault_tag_membership_current c WHERE c.active_submitted=1 "
                "AND c.state IN ('submitted_awaiting_receipt','warehouse_received')"
                +clause+" ORDER BY c.fault_tag_membership_id LIMIT ?",
                (*params,limit+1),
            ).fetchall()
            page=rows[:limit]
            return {"items":[{"fault_tag_membership_id":str(x[0]),"fault_tag_id":str(x[1]),
                "rma_id":str(x[2]),"state":str(x[3]),
                "device_part_unit_id":None if x[4] is None else str(x[4]),
                "spare_part_unit_id":None if x[5] is None else str(x[5]),
                "revision":int(x[6])} for x in page],
                "continuation":str(page[-1][0]) if len(rows)>limit and page else None}

    def lineage(self, fault_tag_id:str)->dict[str,object]:
        identity=require_uuid4(fault_tag_id)
        with ReadSnapshot(self._factory) as snapshot:
            rows=snapshot.connection.execute(
                "SELECT fault_tag_lineage_id,relation_type,predecessor_fault_tag_id,"
                "successor_fault_tag_id,reason_code,recorded_at_utc FROM fault_tag_lineage "
                "WHERE predecessor_fault_tag_id=? OR successor_fault_tag_id=? "
                "ORDER BY recorded_at_utc,fault_tag_lineage_id",
                (identity,identity),
            ).fetchall()
            return {"fault_tag_id":identity,"edges":[{"lineage_id":str(x[0]),
                "relation_type":str(x[1]),"predecessor_fault_tag_id":str(x[2]),
                "successor_fault_tag_id":str(x[3]),"reason_code":str(x[4]),
                "recorded_at_utc":int(x[5])} for x in rows]}


__all__=["InventoryFaultTagQueryService"]
