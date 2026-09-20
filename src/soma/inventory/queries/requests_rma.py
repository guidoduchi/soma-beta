from __future__ import annotations

from typing import Any

from soma.foundation.errors import SomaError, ValidationError
from soma.foundation.identifiers import require_uuid4
from soma.foundation.persistence.connections import ConnectionFactory
from soma.foundation.persistence.uow import ReadSnapshot
from soma.foundation.strict_json import loads_canonical_json


def _limit(value: int) -> int:
    if type(value) is not int or not 1 <= value <= 500:
        raise ValidationError("limit must be an integer from 1 through 500")
    return value


class InventoryRequestsRmaQueryService:
    def __init__(self, connection_factory: ConnectionFactory) -> None:
        self._factory = connection_factory

    def list_requests(
        self,
        *,
        service_request_id: str | None = None,
        lifecycle_state: str | None = None,
        response_warning_only: bool = False,
        after_id: str | None = None,
        limit: int = 100,
    ) -> dict[str, object]:
        page_limit = _limit(limit)
        sr_id = None if service_request_id is None else require_uuid4(service_request_id)
        after = None if after_id is None else require_uuid4(after_id)
        params: list[object] = []
        clauses: list[str] = []
        if sr_id is not None:
            clauses.append("r.service_request_id=?")
            params.append(sr_id)
        if lifecycle_state is not None:
            clauses.append("p.lifecycle_state=?")
            params.append(lifecycle_state)
        if response_warning_only:
            clauses.append("p.response_warning_start_utc IS NOT NULL")
        where = "" if not clauses else " WHERE " + " AND ".join(clauses)
        with ReadSnapshot(self._factory) as snapshot:
            total = int(snapshot.connection.execute(
                "SELECT COUNT(*) FROM spare_requests r "
                "JOIN spare_request_current_projection p "
                "ON p.spare_request_id=r.spare_request_id" + where,
                tuple(params),
            ).fetchone()[0])
            page_clauses = list(clauses)
            page_params = list(params)
            if after is not None:
                page_clauses.append("r.spare_request_id>?")
                page_params.append(after)
            page_where = "" if not page_clauses else " WHERE " + " AND ".join(page_clauses)
            rows = snapshot.connection.execute(
                "SELECT r.spare_request_id,r.tracking_id,r.service_request_id,"
                "r.requester_contact_id,r.requester_context_json,p.lifecycle_state,"
                "p.current_sr7,p.submitted_quantity,p.authorized_rma_count,"
                "p.response_warning_start_utc,p.revision "
                "FROM spare_requests r JOIN spare_request_current_projection p "
                "ON p.spare_request_id=r.spare_request_id"
                + page_where
                + " ORDER BY r.spare_request_id LIMIT ?",
                (*page_params, page_limit + 1),
            ).fetchall()
            page = rows[:page_limit]
            items = [
                {
                    "spare_request_id": str(row[0]),
                    "local_handle": str(row[1]),
                    "service_request_id": str(row[2]),
                    "requester_contact_id": str(row[3]),
                    "requester_context": loads_canonical_json(
                        str(row[4]), max_bytes=4096, max_depth=4, max_collection_items=32
                    ),
                    "lifecycle_state": str(row[5]),
                    "official_sr7": None if row[6] is None else str(row[6]),
                    "submitted_quantity": int(row[7]),
                    "authorized_rma_count": int(row[8]),
                    "response_warning_start_utc": None if row[9] is None else int(row[9]),
                    "revision": int(row[10]),
                }
                for row in page
            ]
            return {
                "items": items,
                "continuation": str(page[-1][0]) if len(rows) > page_limit and page else None,
                "exact_total": total,
            }

    def request_detail(self, request_id: str) -> dict[str, object]:
        identity = require_uuid4(request_id)
        with ReadSnapshot(self._factory) as snapshot:
            row = snapshot.connection.execute(
                "SELECT r.spare_request_id,r.tracking_id,r.service_request_id,"
                "r.requester_contact_id,r.requester_context_json,r.creation_origin,"
                "p.lifecycle_state,p.current_sr7,p.current_submission_snapshot_id,"
                "p.submitted_quantity,p.authorized_rma_count,p.response_warning_start_utc,"
                "p.revision,l.mode,l.receiver_contact_id,l.dispatch_location_id,l.revision "
                "FROM spare_requests r JOIN spare_request_current_projection p "
                "ON p.spare_request_id=r.spare_request_id "
                "JOIN spare_request_draft_logistics l ON l.spare_request_id=r.spare_request_id "
                "WHERE r.spare_request_id=?",
                (identity,),
            ).fetchone()
            if row is None:
                raise SomaError("NOT_FOUND", "Spare Request does not exist")
            allocations = snapshot.connection.execute(
                "SELECT a.request_need_allocation_id,a.spare_need_id,a.quantity,a.revision,"
                "a.active_draft,n.bom_code FROM spare_request_need_allocations a "
                "JOIN spare_needs n ON n.spare_need_id=a.spare_need_id "
                "WHERE a.spare_request_id=? ORDER BY a.spare_need_id,a.request_need_allocation_id",
                (identity,),
            ).fetchall()
            submissions = snapshot.connection.execute(
                "SELECT submission_snapshot_id,submission_event_id,temporary_tracking_id,"
                "mode,receiver_contact_id,dispatch_location_id,location_name_snapshot,"
                "location_address_snapshot,recipient_context_json,effective_submission_at_utc,"
                "recorded_at_utc,evidence_kind,evidence_id,snapshot_hash "
                "FROM spare_request_submission_snapshots WHERE spare_request_id=? "
                "ORDER BY recorded_at_utc,submission_snapshot_id",
                (identity,),
            ).fetchall()
            aliases = snapshot.connection.execute(
                "SELECT sr7,alias_kind FROM spare_request_identifier_aliases "
                "WHERE spare_request_id=? ORDER BY alias_kind,sr7",
                (identity,),
            ).fetchall()
            rmas = snapshot.connection.execute(
                "SELECT r.rma_id,r.authorization_batch_id,r.response_ordinal,"
                "r.promised_bom_code,a.c10,p.state,p.current_target_device_part_unit_id,"
                "p.direct_inbound_spare_part_unit_id,p.return_obligation_open,p.revision "
                "FROM rmas r JOIN rma_identifier_aliases a "
                "ON a.rma_id=r.rma_id AND a.alias_kind='current' "
                "JOIN rma_lifecycle_projection p ON p.rma_id=r.rma_id "
                "WHERE r.spare_request_id=? "
                "ORDER BY r.authorization_batch_id,r.response_ordinal,r.rma_id",
                (identity,),
            ).fetchall()
            history = snapshot.connection.execute(
                "SELECT request_event_id,event_kind,effective_at_utc,target_event_id,"
                "reason_code,evidence_kind,evidence_id,recorded_at_utc "
                "FROM spare_request_lifecycle_events WHERE spare_request_id=? "
                "ORDER BY recorded_at_utc,request_event_id",
                (identity,),
            ).fetchall()
            return {
                "spare_request_id": str(row[0]),
                "local_handle": str(row[1]),
                "service_request_id": str(row[2]),
                "requester": {
                    "contact_id": str(row[3]),
                    "creation_context": loads_canonical_json(
                        str(row[4]), max_bytes=4096, max_depth=4, max_collection_items=32
                    ),
                },
                "creation_origin": str(row[5]),
                "lifecycle_state": str(row[6]),
                "official_sr7": None if row[7] is None else str(row[7]),
                "current_submission_snapshot_id": None if row[8] is None else str(row[8]),
                "submitted_quantity": int(row[9]),
                "authorized_rma_count": int(row[10]),
                "response_warning_start_utc": None if row[11] is None else int(row[11]),
                "revision": int(row[12]),
                "draft_logistics": {
                    "mode": str(row[13]),
                    "receiver_contact_id": str(row[14]),
                    "dispatch_location_id": str(row[15]),
                    "revision": int(row[16]),
                },
                "allocations": [
                    {
                        "request_need_allocation_id": str(item[0]),
                        "spare_need_id": str(item[1]),
                        "quantity": int(item[2]),
                        "revision": int(item[3]),
                        "active_draft": bool(int(item[4])),
                        "bom_code": str(item[5]),
                    }
                    for item in allocations
                ],
                "submission_history": [
                    {
                        "submission_snapshot_id": str(item[0]),
                        "submission_event_id": str(item[1]),
                        "temporary_tracking_id": str(item[2]),
                        "mode": str(item[3]),
                        "receiver_contact_id": str(item[4]),
                        "dispatch_location_id": str(item[5]),
                        "location_name_snapshot": str(item[6]),
                        "location_address_snapshot": str(item[7]),
                        "recipient_context": loads_canonical_json(
                            str(item[8]), max_bytes=4096, max_depth=4, max_collection_items=32
                        ),
                        "effective_submission_at_utc": None if item[9] is None else int(item[9]),
                        "recorded_at_utc": int(item[10]),
                        "evidence_kind": None if item[11] is None else str(item[11]),
                        "evidence_id": None if item[12] is None else str(item[12]),
                        "snapshot_hash": str(item[13]),
                    }
                    for item in submissions
                ],
                "sr7_aliases": [
                    {"sr7": str(item[0]), "alias_kind": str(item[1])}
                    for item in aliases
                ],
                "rmas": [
                    {
                        "rma_id": str(item[0]),
                        "authorization_batch_id": str(item[1]),
                        "response_ordinal": int(item[2]),
                        "promised_bom_code": str(item[3]),
                        "current_c10": str(item[4]),
                        "state": str(item[5]),
                        "target_device_part_unit_id": None if item[6] is None else str(item[6]),
                        "direct_inbound_spare_part_unit_id": None if item[7] is None else str(item[7]),
                        "return_obligation_open": bool(int(item[8])),
                        "revision": int(item[9]),
                    }
                    for item in rmas
                ],
                "history": [
                    {
                        "event_id": str(item[0]),
                        "event_kind": str(item[1]),
                        "effective_at_utc": None if item[2] is None else int(item[2]),
                        "target_event_id": None if item[3] is None else str(item[3]),
                        "reason_code": None if item[4] is None else str(item[4]),
                        "evidence_kind": None if item[5] is None else str(item[5]),
                        "evidence_id": None if item[6] is None else str(item[6]),
                        "recorded_at_utc": int(item[7]),
                    }
                    for item in history
                ],
            }

    def rma_detail(self, rma_id: str) -> dict[str, object]:
        identity = require_uuid4(rma_id)
        with ReadSnapshot(self._factory) as snapshot:
            row = snapshot.connection.execute(
                "SELECT r.rma_id,r.spare_request_id,r.promised_bom_code,r.promised_bom_key,"
                "p.state,p.current_target_device_part_unit_id,"
                "p.direct_inbound_spare_part_unit_id,p.return_device_part_unit_id,"
                "p.return_spare_part_unit_id,p.return_obligation_open,"
                "p.active_fault_tag_membership_id,p.revision "
                "FROM rmas r JOIN rma_lifecycle_projection p ON p.rma_id=r.rma_id "
                "WHERE r.rma_id=?",
                (identity,),
            ).fetchone()
            if row is None:
                raise SomaError("NOT_FOUND", "RMA does not exist")
            aliases = snapshot.connection.execute(
                "SELECT c10,alias_kind FROM rma_identifier_aliases WHERE rma_id=? "
                "ORDER BY alias_kind,c10",
                (identity,),
            ).fetchall()
            assignments = snapshot.connection.execute(
                "SELECT assignment_event_id,prior_device_part_unit_id,new_device_part_unit_id,"
                "event_kind,reason_code,recorded_at_utc FROM rma_assignment_events "
                "WHERE rma_id=? ORDER BY recorded_at_utc,assignment_event_id",
                (identity,),
            ).fetchall()
            obligation = snapshot.connection.execute(
                "SELECT obligation_state,device_part_unit_id,spare_part_unit_id,"
                "physical_consequence_id,revision,last_event_id "
                "FROM rma_return_obligation_current WHERE rma_id=?",
                (identity,),
            ).fetchone()
            membership = snapshot.connection.execute(
                "SELECT c.fault_tag_membership_id,c.fault_tag_id,c.state,c.active_submitted,"
                "c.revision FROM fault_tag_membership_current c WHERE c.rma_id=? "
                "ORDER BY c.revision DESC,c.fault_tag_membership_id",
                (identity,),
            ).fetchall()
            logistics = snapshot.connection.execute(
                "SELECT e.logistics_event_id,e.event_kind,e.effective_at_utc,"
                "e.dispatch_location_id,e.custody_text,e.observed_condition,e.recorded_at_utc "
                "FROM actual_logistics_events e JOIN logistics_rma_participants p "
                "ON p.logistics_event_id=e.logistics_event_id "
                "WHERE p.rma_id=? ORDER BY e.recorded_at_utc,e.logistics_event_id",
                (identity,),
            ).fetchall()
            return {
                "rma_id": str(row[0]),
                "spare_request_id": str(row[1]),
                "promised_bom_code": str(row[2]),
                "promised_bom_key": str(row[3]),
                "state": str(row[4]),
                "target_device_part_unit_id": None if row[5] is None else str(row[5]),
                "direct_inbound_spare_part_unit_id": None if row[6] is None else str(row[6]),
                "return_device_part_unit_id": None if row[7] is None else str(row[7]),
                "return_spare_part_unit_id": None if row[8] is None else str(row[8]),
                "return_obligation_open": bool(int(row[9])),
                "active_fault_tag_membership_id": None if row[10] is None else str(row[10]),
                "revision": int(row[11]),
                "c10_aliases": [{"c10": str(x[0]), "alias_kind": str(x[1])} for x in aliases],
                "assignment_history": [
                    {
                        "assignment_event_id": str(x[0]),
                        "prior_device_part_unit_id": None if x[1] is None else str(x[1]),
                        "new_device_part_unit_id": None if x[2] is None else str(x[2]),
                        "event_kind": str(x[3]),
                        "reason_code": None if x[4] is None else str(x[4]),
                        "recorded_at_utc": int(x[5]),
                    }
                    for x in assignments
                ],
                "return_obligation": None if obligation is None else {
                    "state": str(obligation[0]),
                    "device_part_unit_id": None if obligation[1] is None else str(obligation[1]),
                    "spare_part_unit_id": None if obligation[2] is None else str(obligation[2]),
                    "physical_consequence_id": None if obligation[3] is None else str(obligation[3]),
                    "revision": int(obligation[4]),
                    "last_event_id": None if obligation[5] is None else str(obligation[5]),
                },
                "fault_tag_memberships": [
                    {
                        "fault_tag_membership_id": str(x[0]),
                        "fault_tag_id": str(x[1]),
                        "state": str(x[2]),
                        "active_submitted": bool(int(x[3])),
                        "revision": int(x[4]),
                    }
                    for x in membership
                ],
                "actual_logistics": [
                    {
                        "logistics_event_id": str(x[0]),
                        "event_kind": str(x[1]),
                        "effective_at_utc": None if x[2] is None else int(x[2]),
                        "dispatch_location_id": None if x[3] is None else str(x[3]),
                        "custody_text": None if x[4] is None else str(x[4]),
                        "observed_condition": None if x[5] is None else str(x[5]),
                        "recorded_at_utc": int(x[6]),
                    }
                    for x in logistics
                ],
            }


__all__ = ["InventoryRequestsRmaQueryService"]
