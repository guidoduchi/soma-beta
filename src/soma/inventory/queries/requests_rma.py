from __future__ import annotations

from dataclasses import dataclass

from soma.foundation.errors import IntegrityFailure, SomaError, ValidationError
from soma.foundation.identifiers import require_uuid4
from soma.foundation.persistence.connections import ConnectionFactory
from soma.foundation.persistence.uow import ReadSnapshot
from soma.foundation.strict_json import loads_canonical_json, sha256_canonical_json

from ..repositories.requests import InventoryRequestsRepository

_REQUEST_QUERY_ID = "SpareRequestListQuery"
_REQUEST_SORT_ID = "INVENTORY_REQUEST_TRACKING_ID_ASC_V1"
_REQUEST_CURSOR_FIELDS = frozenset(
    {
        "version",
        "query_id",
        "sort_registry_id",
        "last_key_tuple",
        "filter_fingerprint",
        "null_order",
    }
)



def _transport_state(value: str) -> str:
    mapping = {
        "draft": "draft",
        "submitted_awaiting_response": "submitted",
        "acknowledged": "submitted",
        "partially_authorized": "authorizing",
        "authorized": "authorized",
        "cancelled": "terminal",
        "rejected": "terminal",
    }
    try:
        return mapping[value]
    except KeyError as exc:
        raise IntegrityFailure("Spare Request projection state is invalid") from exc


@dataclass(frozen=True, slots=True)
class SpareRequestDraftPayload:
    payload: dict[str, object]
    input_fingerprint: str


@dataclass(frozen=True, slots=True)
class SpareRequestPage:
    items: tuple[dict[str, object], ...]
    continuation: dict[str, object] | None
    exact_total: int


class InventoryRequestsQueryService:
    def __init__(self, connection_factory: ConnectionFactory) -> None:
        self._factory = connection_factory
        self._repository = InventoryRequestsRepository()

    @staticmethod
    def _page_limit(value: int) -> int:
        if type(value) is not int or not 1 <= value <= 500:
            raise ValidationError("limit must be an integer from 1 through 500")
        return value

    @staticmethod
    def _decode_request_cursor(
        cursor: dict[str, object] | None,
        *,
        filter_fingerprint: str,
    ) -> tuple[str, str] | None:
        if cursor is None:
            return None
        if not isinstance(cursor, dict) or set(cursor) != _REQUEST_CURSOR_FIELDS:
            raise ValidationError("Spare Request cursor shape is invalid")
        if (
            cursor["version"] != 1
            or cursor["query_id"] != _REQUEST_QUERY_ID
            or cursor["sort_registry_id"] != _REQUEST_SORT_ID
            or cursor["filter_fingerprint"] != filter_fingerprint
            or cursor["null_order"] != "not_applicable"
        ):
            raise ValidationError("Spare Request cursor contract is invalid")
        key = cursor["last_key_tuple"]
        if (
            not isinstance(key, list)
            or len(key) != 2
            or not isinstance(key[0], str)
            or not isinstance(key[1], str)
        ):
            raise ValidationError("Spare Request cursor key is invalid")
        require_uuid4(key[1])
        return str(key[0]), str(key[1])

    def list_spare_requests(
        self,
        *,
        service_request_id: str | None = None,
        customer_org_id: str | None = None,
        lifecycle_state: str | None = None,
        response_warning_only: bool = False,
        as_of_utc: int | None = None,
        cursor: dict[str, object] | None = None,
        limit: int = 100,
    ) -> SpareRequestPage:
        page_limit = self._page_limit(limit)
        sr_id = None if service_request_id is None else require_uuid4(service_request_id)
        customer_id = None if customer_org_id is None else require_uuid4(customer_org_id)
        if lifecycle_state is not None and lifecycle_state not in {
            "draft",
            "submitted_awaiting_response",
            "acknowledged",
            "partially_authorized",
            "authorized",
            "cancelled",
            "rejected",
        }:
            raise ValidationError("Spare Request lifecycle_state is invalid")
        if type(response_warning_only) is not bool:
            raise ValidationError("response_warning_only must be boolean")
        if response_warning_only and (
            type(as_of_utc) is not int or as_of_utc < 0
        ):
            raise ValidationError(
                "response_warning_only requires nonnegative as_of_utc"
            )
        filter_fingerprint = sha256_canonical_json(
            {
                "schema": "SOMA_SPARE_REQUEST_LIST_FILTER_V1",
                "service_request_id": sr_id,
                "customer_org_id": customer_id,
                "lifecycle_state": lifecycle_state,
                "response_warning_only": response_warning_only,
                "as_of_utc": as_of_utc if response_warning_only else None,
            }
        )
        after = self._decode_request_cursor(
            cursor,
            filter_fingerprint=filter_fingerprint,
        )

        with ReadSnapshot(self._factory) as snapshot:
            clauses: list[str] = []
            params: list[object] = []
            if sr_id is not None:
                clauses.append("r.service_request_id=?")
                params.append(sr_id)
            if customer_id is not None:
                clauses.append(
                    "EXISTS(SELECT 1 FROM sr_customer_relationships scr "
                    "WHERE scr.service_request_id=r.service_request_id "
                    "AND scr.relationship_state='active' AND scr.customer_org_id=?)"
                )
                params.append(customer_id)
            if lifecycle_state is not None:
                clauses.append("p.lifecycle_state=?")
                params.append(lifecycle_state)
            if response_warning_only:
                clauses.append(
                    "p.lifecycle_state='submitted_awaiting_response' "
                    "AND p.response_warning_start_utc IS NOT NULL "
                    "AND p.response_warning_start_utc + 86400 <= ?"
                )
                params.append(as_of_utc)
            where = "" if not clauses else "WHERE " + " AND ".join(clauses)
            rows = snapshot.connection.execute(
                "SELECT r.spare_request_id,r.tracking_id,r.service_request_id,"
                "r.requester_contact_id,r.requester_context_json,p.lifecycle_state,"
                "p.current_sr7,p.submitted_quantity,p.authorized_rma_count,"
                "p.response_warning_start_utc,p.revision,p.input_fingerprint "
                "FROM spare_requests r JOIN spare_request_current_projection p "
                "ON p.spare_request_id=r.spare_request_id "
                f"{where} "
                "ORDER BY r.tracking_id,r.spare_request_id",
                tuple(params),
            ).fetchall()
            projected: list[tuple[tuple[str, str], dict[str, object]]] = []
            for row in rows:
                request_id = str(row[0])
                key = (str(row[1]), request_id)
                if after is not None and key <= after:
                    continue
                requester = loads_canonical_json(
                    str(row[4]),
                    max_bytes=4096,
                    max_depth=3,
                    max_collection_items=16,
                )
                if not isinstance(requester, dict):
                    raise IntegrityFailure(
                        "Persisted requester creation context is invalid"
                    )
                rma_count = int(
                    snapshot.connection.execute(
                        "SELECT COUNT(*) FROM rmas WHERE spare_request_id=?",
                        (request_id,),
                    ).fetchone()[0]
                )
                current_customer = snapshot.connection.execute(
                    "SELECT customer_org_id FROM sr_customer_relationships "
                    "WHERE service_request_id=? AND relationship_state='active'",
                    (str(row[2]),),
                ).fetchone()
                warning_start = None if row[9] is None else int(row[9])
                warning_age = (
                    None
                    if warning_start is None or as_of_utc is None
                    else max(0, as_of_utc - warning_start)
                )
                blockers: list[str] = []
                if str(row[5]) in {"cancelled", "rejected", "authorized"}:
                    blockers.append("request_terminal_or_complete")
                if rma_count:
                    blockers.append("accepted_rma_history_present")
                projected.append(
                    (
                        key,
                        {
                            "spare_request_id": request_id,
                            "local_handle": str(row[1]),
                            "official_sr7": None if row[6] is None else str(row[6]),
                            "service_request_id": str(row[2]),
                            "customer_org_id": None
                            if current_customer is None
                            else str(current_customer[0]),
                            "requester_contact_id": str(row[3]),
                            "requester": requester,
                            "lifecycle_state": str(row[5]),
                            "state": _transport_state(str(row[5])),
                            "submitted_quantity": int(row[7]),
                            "rma_count": rma_count,
                            "authorized_rma_count": int(row[8]),
                            "response_warning_start_utc": warning_start,
                            "response_warning_age_seconds": warning_age,
                            "revision": int(row[10]),
                            "input_fingerprint": str(row[11]),
                            "action_blockers": blockers,
                        },
                    )
                )
            total = len(projected)
            selected = projected[:page_limit]
            continuation = None
            if len(projected) > page_limit and selected:
                continuation = {
                    "version": 1,
                    "query_id": _REQUEST_QUERY_ID,
                    "sort_registry_id": _REQUEST_SORT_ID,
                    "last_key_tuple": list(selected[-1][0]),
                    "filter_fingerprint": filter_fingerprint,
                    "null_order": "not_applicable",
                }
            return SpareRequestPage(
                items=tuple(item for _key, item in selected),
                continuation=continuation,
                exact_total=total,
            )

    def get_spare_request(self, spare_request_id: str) -> dict[str, object]:
        request_id = require_uuid4(spare_request_id)
        with ReadSnapshot(self._factory) as snapshot:
            material = self._repository.draft_material(
                snapshot.connection,
                request_id,
            )
            requester = loads_canonical_json(
                str(material["requester_context_json"]),
                max_bytes=4096,
                max_depth=3,
                max_collection_items=16,
            )
            if not isinstance(requester, dict):
                raise IntegrityFailure("Persisted requester context is invalid")
            return {
                "spare_request_id": request_id,
                "local_handle": str(material["tracking_id"]),
                "official_sr7": material["current_sr7"],
                "requester": requester,
                "state": _transport_state(str(material["lifecycle_state"])),
                "revision": int(material["revision"]),
                "input_fingerprint": str(material["input_fingerprint"]),
                "draft": {
                    "allocations": [
                        {
                            "request_need_allocation_id": str(item["request_need_allocation_id"]),
                            "spare_need_id": str(item["spare_need_id"]),
                            "quantity": int(item["quantity"]),
                            "bom_code": str(item["bom_code"]),
                        }
                        for item in material["allocations"]
                    ],
                    "mode": str(material["mode"]),
                    "receiver_contact_id": str(material["receiver_contact_id"]),
                    "dispatch_location_id": str(material["dispatch_location_id"]),
                    "logistics_revision": int(material["logistics_revision"]),
                },
                "current_submission_snapshot_id": material[
                    "current_submission_snapshot_id"
                ],
                "submitted_quantity": int(material["submitted_quantity"]),
                "response_warning_start_utc": material["response_warning_start_utc"],
            }

    def spare_request_detail(self, spare_request_id: str) -> dict[str, object]:
        request_id = require_uuid4(spare_request_id)
        base = self.get_spare_request(request_id)
        with ReadSnapshot(self._factory) as snapshot:
            aliases = snapshot.connection.execute(
                "SELECT sr7,alias_kind,source_identifier_event_id "
                "FROM spare_request_identifier_aliases "
                "WHERE spare_request_id=? ORDER BY alias_kind,sr7",
                (request_id,),
            ).fetchall()
            snapshots = snapshot.connection.execute(
                "SELECT submission_snapshot_id,submission_event_id,temporary_tracking_id,"
                "mode,receiver_contact_id,dispatch_location_id,location_name_snapshot,"
                "location_address_snapshot,recipient_context_json,effective_submission_at_utc,"
                "recorded_at_utc,evidence_kind,evidence_id,snapshot_hash "
                "FROM spare_request_submission_snapshots "
                "WHERE spare_request_id=? ORDER BY recorded_at_utc,submission_snapshot_id",
                (request_id,),
            ).fetchall()
            rmas = snapshot.connection.execute(
                "SELECT r.rma_id,r.authorization_batch_id,r.response_ordinal,"
                "r.promised_bom_code,a.c10,l.state,l.current_target_device_part_unit_id,"
                "l.direct_inbound_spare_part_unit_id,l.return_device_part_unit_id,"
                "l.return_spare_part_unit_id,l.return_obligation_open,l.revision "
                "FROM rmas r "
                "JOIN rma_identifier_aliases a ON a.rma_id=r.rma_id "
                "AND a.alias_kind='current' "
                "JOIN rma_lifecycle_projection l ON l.rma_id=r.rma_id "
                "WHERE r.spare_request_id=? "
                "ORDER BY r.response_ordinal,r.rma_id",
                (request_id,),
            ).fetchall()
            logistics = snapshot.connection.execute(
                "SELECT e.logistics_event_id,e.event_kind,e.effective_at_utc,"
                "e.dispatch_location_id,e.location_name_snapshot,"
                "e.location_address_snapshot,e.receiver_contact_id,e.custody_text,"
                "e.observed_condition,e.reason_code,e.recorded_at_utc,p.rma_id "
                "FROM actual_logistics_events e "
                "LEFT JOIN logistics_rma_participants p "
                "ON p.logistics_event_id=e.logistics_event_id "
                "AND p.rma_id IN (SELECT rma_id FROM rmas WHERE spare_request_id=?) "
                "WHERE p.rma_id IS NOT NULL "
                "ORDER BY e.recorded_at_utc,e.logistics_event_id,p.rma_id",
                (request_id,),
            ).fetchall()
            attention = snapshot.connection.execute(
                "SELECT attention_id,target_kind,target_id,attention_kind,severity,"
                "input_fingerprint FROM inventory_attention_projection "
                "WHERE (target_kind='spare_request' AND target_id=?) "
                "OR (target_kind='rma' AND target_id IN "
                "(SELECT rma_id FROM rmas WHERE spare_request_id=?)) "
                "ORDER BY attention_kind,target_kind,target_id",
                (request_id, request_id),
            ).fetchall()
            proposals = snapshot.connection.execute(
                "SELECT DISTINCT p.inventory_proposal_id,p.proposal_kind,p.state,"
                "p.risk_tier,p.revision,p.input_fingerprint "
                "FROM inventory_proposals p JOIN inventory_proposal_targets t "
                "ON t.inventory_proposal_id=p.inventory_proposal_id "
                "WHERE t.spare_request_id=? "
                "OR t.rma_id IN (SELECT rma_id FROM rmas WHERE spare_request_id=?) "
                "ORDER BY p.created_at_utc,p.inventory_proposal_id",
                (request_id, request_id),
            ).fetchall()
            history = snapshot.connection.execute(
                "SELECT request_event_id,event_kind,effective_at_utc,target_event_id,"
                "reason_code,evidence_kind,evidence_id,recorded_at_utc "
                "FROM spare_request_lifecycle_events WHERE spare_request_id=? "
                "ORDER BY recorded_at_utc,request_event_id",
                (request_id,),
            ).fetchall()

        base["identifier_aliases"] = [
            {
                "sr7": str(row[0]),
                "alias_kind": str(row[1]),
                "source_identifier_event_id": str(row[2]),
            }
            for row in aliases
        ]
        base["submission_snapshots"] = [
            {
                "submission_snapshot_id": str(row[0]),
                "submission_event_id": str(row[1]),
                "temporary_tracking_id": str(row[2]),
                "mode": str(row[3]),
                "receiver_contact_id": str(row[4]),
                "dispatch_location_id": str(row[5]),
                "location_name_snapshot": str(row[6]),
                "location_address_snapshot": str(row[7]),
                "recipient_context": loads_canonical_json(
                    str(row[8]),
                    max_bytes=16_384,
                    max_depth=4,
                    max_collection_items=32,
                ),
                "effective_submission_at_utc": None
                if row[9] is None
                else int(row[9]),
                "recorded_at_utc": int(row[10]),
                "evidence_kind": None if row[11] is None else str(row[11]),
                "evidence_id": None if row[12] is None else str(row[12]),
                "snapshot_hash": str(row[13]),
                "historical": True,
            }
            for row in snapshots
        ]
        base["rmas"] = [
            {
                "rma_id": str(row[0]),
                "authorization_batch_id": str(row[1]),
                "response_ordinal": int(row[2]),
                "promised_bom_code": str(row[3]),
                "current_c10": str(row[4]),
                "state": str(row[5]),
                "current_target_device_part_unit_id": None
                if row[6] is None
                else str(row[6]),
                "direct_inbound_spare_part_unit_id": None
                if row[7] is None
                else str(row[7]),
                "return_device_part_unit_id": None
                if row[8] is None
                else str(row[8]),
                "return_spare_part_unit_id": None
                if row[9] is None
                else str(row[9]),
                "return_obligation_open": bool(row[10]),
                "revision": int(row[11]),
            }
            for row in rmas
        ]
        base["actual_logistics"] = [
            {
                "logistics_event_id": str(row[0]),
                "event_kind": str(row[1]),
                "effective_at_utc": None if row[2] is None else int(row[2]),
                "dispatch_location_id": None if row[3] is None else str(row[3]),
                "location_name_snapshot": None if row[4] is None else str(row[4]),
                "location_address_snapshot": None if row[5] is None else str(row[5]),
                "receiver_contact_id": None if row[6] is None else str(row[6]),
                "custody_text": None if row[7] is None else str(row[7]),
                "observed_condition": None if row[8] is None else str(row[8]),
                "reason_code": None if row[9] is None else str(row[9]),
                "recorded_at_utc": int(row[10]),
                "rma_id": str(row[11]),
            }
            for row in logistics
        ]
        base["attention"] = [
            {
                "attention_id": str(row[0]),
                "target_kind": str(row[1]),
                "target_id": str(row[2]),
                "attention_kind": str(row[3]),
                "severity": str(row[4]),
                "input_fingerprint": str(row[5]),
            }
            for row in attention
        ]
        base["proposals"] = [
            {
                "inventory_proposal_id": str(row[0]),
                "proposal_kind": str(row[1]),
                "state": str(row[2]),
                "risk_tier": str(row[3]),
                "revision": int(row[4]),
                "input_fingerprint": str(row[5]),
            }
            for row in proposals
        ]
        base["lifecycle_history"] = [
            {
                "request_event_id": str(row[0]),
                "event_kind": str(row[1]),
                "effective_at_utc": None if row[2] is None else int(row[2]),
                "target_event_id": None if row[3] is None else str(row[3]),
                "reason_code": None if row[4] is None else str(row[4]),
                "evidence_kind": None if row[5] is None else str(row[5]),
                "evidence_id": None if row[6] is None else str(row[6]),
                "recorded_at_utc": int(row[7]),
            }
            for row in history
        ]
        return base

    def get_rma(self, rma_id: str) -> dict[str, object]:
        identity = require_uuid4(rma_id)
        with ReadSnapshot(self._factory) as snapshot:
            row = snapshot.connection.execute(
                "SELECT r.rma_id,r.spare_request_id,r.authorization_batch_id,"
                "r.response_ordinal,r.promised_bom_code,r.promised_bom_key,"
                "l.state,l.current_target_device_part_unit_id,"
                "l.direct_inbound_spare_part_unit_id,l.return_device_part_unit_id,"
                "l.return_spare_part_unit_id,l.return_obligation_open,"
                "l.active_fault_tag_membership_id,l.revision,l.input_fingerprint "
                "FROM rmas r JOIN rma_lifecycle_projection l ON l.rma_id=r.rma_id "
                "WHERE r.rma_id=?",
                (identity,),
            ).fetchone()
            if row is None:
                raise ValidationError("RMA does not exist")
            aliases = snapshot.connection.execute(
                "SELECT c10,alias_kind,source_identifier_event_id "
                "FROM rma_identifier_aliases WHERE rma_id=? "
                "ORDER BY alias_kind,c10",
                (identity,),
            ).fetchall()
            assignments = snapshot.connection.execute(
                "SELECT assignment_event_id,prior_device_part_unit_id,"
                "new_device_part_unit_id,event_kind,reason_code,recorded_at_utc "
                "FROM rma_assignment_events WHERE rma_id=? "
                "ORDER BY recorded_at_utc,assignment_event_id",
                (identity,),
            ).fetchall()
            direct = snapshot.connection.execute(
                "SELECT d.direct_inbound_relationship_id,d.spare_part_unit_id,"
                "d.relationship_event_id,u.local_tracking_id,u.bom_code,"
                "u.manufacturer_serial,p.condition_token,p.disposition_token,p.revision "
                "FROM rma_direct_inbound_units d "
                "JOIN spare_part_units u ON u.spare_part_unit_id=d.spare_part_unit_id "
                "JOIN spare_part_current_projection p "
                "ON p.spare_part_unit_id=d.spare_part_unit_id "
                "WHERE d.rma_id=?",
                (identity,),
            ).fetchone()
            consequence = snapshot.connection.execute(
                "SELECT i.physical_consequence_id,i.task_id,i.task_review_fingerprint,"
                "i.target_device_part_unit_id,c.physical_disposition,"
                "c.installed_spare_part_unit_id,c.removed_device_part_unit_id,"
                "c.inbound_spare_part_unit_id,c.parent_dismantled_unit_id,"
                "c.revision,c.input_fingerprint,c.last_event_id "
                "FROM inventory_physical_consequences i "
                "JOIN physical_consequence_current c "
                "ON c.physical_consequence_id=i.physical_consequence_id "
                "WHERE i.rma_id=? "
                "ORDER BY i.created_at_utc DESC,i.physical_consequence_id DESC LIMIT 1",
                (identity,),
            ).fetchone()
            obligation = snapshot.connection.execute(
                "SELECT obligation_state,device_part_unit_id,spare_part_unit_id,"
                "physical_consequence_id,revision,last_event_id "
                "FROM rma_return_obligation_current WHERE rma_id=?",
                (identity,),
            ).fetchone()
            memberships = snapshot.connection.execute(
                "SELECT m.fault_tag_membership_id,m.fault_tag_id,"
                "t.tracking_id,c.state,c.active_submitted,c.revision,c.last_event_id "
                "FROM fault_tag_memberships m JOIN fault_tags t "
                "ON t.fault_tag_id=m.fault_tag_id "
                "JOIN fault_tag_membership_current c "
                "ON c.fault_tag_membership_id=m.fault_tag_membership_id "
                "WHERE m.rma_id=? "
                "ORDER BY t.tracking_sequence,m.fault_tag_membership_id",
                (identity,),
            ).fetchall()
            logistics = snapshot.connection.execute(
                "SELECT p.logistics_rma_participant_id,p.active,p.close_reason,"
                "e.logistics_event_id,e.event_kind,e.effective_at_utc,"
                "e.dispatch_location_id,e.location_name_snapshot,"
                "e.location_address_snapshot,e.receiver_contact_id,e.custody_text,"
                "e.observed_condition,e.reason_code,e.recorded_at_utc "
                "FROM logistics_rma_participants p JOIN actual_logistics_events e "
                "ON e.logistics_event_id=p.logistics_event_id "
                "WHERE p.rma_id=? "
                "ORDER BY e.recorded_at_utc,e.logistics_event_id,"
                "p.logistics_rma_participant_id",
                (identity,),
            ).fetchall()

        return {
            "rma_id": identity,
            "spare_request_id": str(row[1]),
            "authorization_batch_id": str(row[2]),
            "response_ordinal": int(row[3]),
            "promised_bom_code": str(row[4]),
            "promised_bom_key": str(row[5]),
            "state": str(row[6]),
            "current_target_device_part_unit_id": None
            if row[7] is None
            else str(row[7]),
            "direct_inbound_spare_part_unit_id": None
            if row[8] is None
            else str(row[8]),
            "return_device_part_unit_id": None
            if row[9] is None
            else str(row[9]),
            "return_spare_part_unit_id": None
            if row[10] is None
            else str(row[10]),
            "return_obligation_open": bool(row[11]),
            "active_fault_tag_membership_id": None
            if row[12] is None
            else str(row[12]),
            "revision": int(row[13]),
            "input_fingerprint": str(row[14]),
            "identifier_aliases": [
                {
                    "c10": str(item[0]),
                    "alias_kind": str(item[1]),
                    "source_identifier_event_id": str(item[2]),
                }
                for item in aliases
            ],
            "assignment_history": [
                {
                    "assignment_event_id": str(item[0]),
                    "prior_device_part_unit_id": None
                    if item[1] is None
                    else str(item[1]),
                    "new_device_part_unit_id": None
                    if item[2] is None
                    else str(item[2]),
                    "event_kind": str(item[3]),
                    "reason_code": None if item[4] is None else str(item[4]),
                    "recorded_at_utc": int(item[5]),
                }
                for item in assignments
            ],
            "direct_inbound_unit": None
            if direct is None
            else {
                "direct_inbound_relationship_id": str(direct[0]),
                "spare_part_unit_id": str(direct[1]),
                "relationship_event_id": str(direct[2]),
                "local_tracking_id": None if direct[3] is None else str(direct[3]),
                "bom_code": str(direct[4]),
                "manufacturer_serial": None if direct[5] is None else str(direct[5]),
                "condition_token": str(direct[6]),
                "disposition_token": str(direct[7]),
                "revision": int(direct[8]),
            },
            "physical_consequence": None
            if consequence is None
            else {
                "physical_consequence_id": str(consequence[0]),
                "task_id": str(consequence[1]),
                "task_review_fingerprint": str(consequence[2]),
                "target_device_part_unit_id": None
                if consequence[3] is None
                else str(consequence[3]),
                "physical_disposition": str(consequence[4]),
                "installed_spare_part_unit_id": None
                if consequence[5] is None
                else str(consequence[5]),
                "removed_device_part_unit_id": None
                if consequence[6] is None
                else str(consequence[6]),
                "inbound_spare_part_unit_id": None
                if consequence[7] is None
                else str(consequence[7]),
                "parent_dismantled_unit_id": None
                if consequence[8] is None
                else str(consequence[8]),
                "revision": int(consequence[9]),
                "input_fingerprint": str(consequence[10]),
                "last_event_id": str(consequence[11]),
            },
            "return_obligation": None
            if obligation is None
            else {
                "obligation_state": str(obligation[0]),
                "device_part_unit_id": None
                if obligation[1] is None
                else str(obligation[1]),
                "spare_part_unit_id": None
                if obligation[2] is None
                else str(obligation[2]),
                "physical_consequence_id": None
                if obligation[3] is None
                else str(obligation[3]),
                "revision": int(obligation[4]),
                "last_event_id": None
                if obligation[5] is None
                else str(obligation[5]),
            },
            "fault_tag_memberships": [
                {
                    "fault_tag_membership_id": str(item[0]),
                    "fault_tag_id": str(item[1]),
                    "tracking_id": str(item[2]),
                    "state": str(item[3]),
                    "active_submitted": bool(item[4]),
                    "revision": int(item[5]),
                    "last_event_id": str(item[6]),
                }
                for item in memberships
            ],
            "actual_logistics": [
                {
                    "logistics_rma_participant_id": str(item[0]),
                    "active": bool(item[1]),
                    "close_reason": None if item[2] is None else str(item[2]),
                    "logistics_event_id": str(item[3]),
                    "event_kind": str(item[4]),
                    "effective_at_utc": None
                    if item[5] is None
                    else int(item[5]),
                    "dispatch_location_id": None
                    if item[6] is None
                    else str(item[6]),
                    "location_name_snapshot": None
                    if item[7] is None
                    else str(item[7]),
                    "location_address_snapshot": None
                    if item[8] is None
                    else str(item[8]),
                    "receiver_contact_id": None
                    if item[9] is None
                    else str(item[9]),
                    "custody_text": None if item[10] is None else str(item[10]),
                    "observed_condition": None
                    if item[11] is None
                    else str(item[11]),
                    "reason_code": None if item[12] is None else str(item[12]),
                    "recorded_at_utc": int(item[13]),
                }
                for item in logistics
            ],
        }

    def spare_request_draft_payload(
        self,
        spare_request_id: str,
    ) -> SpareRequestDraftPayload:
        request_id = require_uuid4(spare_request_id)
        with ReadSnapshot(self._factory) as snapshot:
            material = self._repository.draft_material(
                snapshot.connection,
                request_id,
            )
            if str(material["lifecycle_state"]) != "draft":
                raise SomaError("REQUEST_NOT_DRAFT", "MSG draft payload requires current Draft state")
            reference = self._repository.submission_reference_context(
                snapshot.connection,
                receiver_contact_id=str(material["receiver_contact_id"]),
                dispatch_location_id=str(material["dispatch_location_id"]),
            )
            allocations = sorted(
                material["allocations"],
                key=lambda item: (
                    str(item["spare_need_id"]),
                    str(item["request_need_allocation_id"]),
                ),
            )
            payload: dict[str, object] = {
                "schema": "INVENTORY_SPARE_REQUEST_DRAFT_V1",
                "spare_request_id": request_id,
                "temporary_tracking_id": str(material["tracking_id"]),
                "service_request_id": str(material["service_request_id"]),
                "request_revision": int(material["revision"]),
                "request_input_fingerprint": str(material["input_fingerprint"]),
                "mode": str(material["mode"]),
                "receiver": {
                    "contact_id": str(reference["receiver_contact_id"]),
                    "display_name": str(reference["receiver_display_name_snapshot"]),
                    "contact_revision": int(
                        reference["receiver_contact_revision_at_submission"]
                    ),
                },
                "dispatch_location": {
                    "dispatch_location_id": str(reference["dispatch_location_id"]),
                    "name": str(reference["location_name_snapshot"]),
                    "address": str(reference["location_address_snapshot"]),
                    "revision": int(
                        reference["dispatch_location_revision_at_submission"]
                    ),
                },
                "allocations": [
                    {
                        "request_need_allocation_id": str(
                            item["request_need_allocation_id"]
                        ),
                        "spare_need_id": str(item["spare_need_id"]),
                        "quantity": int(item["quantity"]),
                        "requested_bom_code": str(item["bom_code"]),
                        "requested_bom_key": str(item["bom_key"]),
                    }
                    for item in allocations
                ],
            }
            return SpareRequestDraftPayload(
                payload=payload,
                input_fingerprint=sha256_canonical_json(payload),
            )


__all__ = ["InventoryRequestsQueryService", "SpareRequestDraftPayload", "SpareRequestPage"]
