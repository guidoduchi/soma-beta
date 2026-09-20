from __future__ import annotations

from dataclasses import dataclass

from soma.foundation.errors import ValidationError
from soma.foundation.identifiers import require_uuid4
from soma.foundation.persistence.connections import ConnectionFactory
from soma.foundation.persistence.uow import ReadSnapshot
from soma.foundation.strict_json import sha256_canonical_json

from ..domain.needs import normalize_optional_serial, normalize_part_code
from ..repositories.units import InventoryUnitsRepository

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
_STOCK_QUERY_ID = "StockEligibilityQuery"
_STOCK_SORT_ID = "INVENTORY_STOCK_COMPAT_LSU_ID_ASC_V1"
_NEED_QUERY_ID = "InventoryNeedsQuery"
_NEED_SORT_ID = "INVENTORY_NEED_SR_BOM_ID_ASC_V1"


@dataclass(frozen=True, slots=True)
class DevicePartDuplicateCandidate:
    device_part_unit_id: str
    service_request_id: str
    device_reference_id: str
    creation_sequence: int
    bom_code: str
    manufacturer_serial: str | None


@dataclass(frozen=True, slots=True)
class SparePartDuplicateCandidate:
    spare_part_unit_id: str
    local_tracking_id: str | None
    bom_code: str
    manufacturer_serial: str | None
    condition_token: str
    disposition_token: str
    revision: int


@dataclass(frozen=True, slots=True)
class StockEligibilityItem:
    spare_part_unit_id: str
    local_tracking_id: str | None
    bom_code: str
    manufacturer_serial: str | None
    condition_token: str
    disposition_token: str
    location_kind: str | None
    location_ref_id: str | None
    custody_text: str | None
    active_task_allocation_id: str | None
    compatibility_classification: str
    availability_blockers: tuple[str, ...]

    @property
    def eligible(self) -> bool:
        return not self.availability_blockers


@dataclass(frozen=True, slots=True)
class StockEligibilityPage:
    items: tuple[StockEligibilityItem, ...]
    continuation: dict[str, object] | None
    exact_total: int


@dataclass(frozen=True, slots=True)
class InventoryNeedPage:
    items: tuple[dict[str, object], ...]
    continuation: dict[str, object] | None
    exact_total: int


def _limit(value: int) -> int:
    if type(value) is not int or not 1 <= value <= 500:
        raise ValidationError("limit must be an integer from 1 through 500")
    return value


def _stock_sort_key(
    compatibility: str,
    local_tracking_id: str | None,
    spare_part_unit_id: str,
) -> tuple[int, str, str]:
    rank = {
        "exact": 0,
        "candidate": 1,
        "incompatible": 2,
        "unknown": 3,
    }.get(compatibility)
    if rank is None:
        raise ValidationError("Stock compatibility class is invalid")
    return rank, "" if local_tracking_id is None else local_tracking_id, spare_part_unit_id


def _decode_cursor(
    cursor: dict[str, object] | None,
    *,
    filter_fingerprint: str,
) -> tuple[int, str, str] | None:
    if cursor is None:
        return None
    if not isinstance(cursor, dict) or set(cursor) != _CURSOR_FIELDS:
        raise ValidationError("Stock cursor shape is invalid")
    if (
        cursor["version"] != 1
        or cursor["query_id"] != _STOCK_QUERY_ID
        or cursor["sort_registry_id"] != _STOCK_SORT_ID
        or cursor["filter_fingerprint"] != filter_fingerprint
        or cursor["null_order"] != "empty_before_text"
    ):
        raise ValidationError("Stock cursor contract is invalid")
    key = cursor["last_key_tuple"]
    if (
        not isinstance(key, list)
        or len(key) != 3
        or type(key[0]) is not int
        or not isinstance(key[1], str)
        or not isinstance(key[2], str)
        or not 0 <= key[0] <= 3
    ):
        raise ValidationError("Stock cursor key is invalid")
    require_uuid4(key[2])
    return int(key[0]), str(key[1]), str(key[2])


class InventoryNeedsQueryService:
    def __init__(self, connection_factory: ConnectionFactory) -> None:
        self._factory = connection_factory
        self._units = InventoryUnitsRepository()

    @staticmethod
    def _decode_need_cursor(
        cursor: dict[str, object] | None,
        *,
        filter_fingerprint: str,
    ) -> tuple[str, str, str] | None:
        if cursor is None:
            return None
        if not isinstance(cursor, dict) or set(cursor) != _CURSOR_FIELDS:
            raise ValidationError("Inventory Need cursor shape is invalid")
        if (
            cursor["version"] != 1
            or cursor["query_id"] != _NEED_QUERY_ID
            or cursor["sort_registry_id"] != _NEED_SORT_ID
            or cursor["filter_fingerprint"] != filter_fingerprint
            or cursor["null_order"] != "not_applicable"
        ):
            raise ValidationError("Inventory Need cursor contract is invalid")
        key = cursor["last_key_tuple"]
        if (
            not isinstance(key, list)
            or len(key) != 3
            or any(not isinstance(value, str) for value in key)
        ):
            raise ValidationError("Inventory Need cursor key is invalid")
        require_uuid4(key[0])
        require_uuid4(key[2])
        return str(key[0]), str(key[1]), str(key[2])

    def inventory_needs(
        self,
        *,
        service_request_id: str | None = None,
        customer_org_id: str | None = None,
        lifecycle_state: str | None = None,
        bom_code: str | None = None,
        cursor: dict[str, object] | None = None,
        limit: int = 100,
    ) -> InventoryNeedPage:
        page_limit = _limit(limit)
        sr_id = None if service_request_id is None else require_uuid4(service_request_id)
        customer_id = None if customer_org_id is None else require_uuid4(customer_org_id)
        if lifecycle_state is not None and lifecycle_state not in {
            "active",
            "resolved",
            "cancelled",
            "removed",
        }:
            raise ValidationError("Inventory Need lifecycle_state is invalid")
        normalized_bom: str | None = None
        bom_key: str | None = None
        if bom_code is not None:
            normalized_bom, bom_key = normalize_part_code(bom_code)
        fingerprint = sha256_canonical_json(
            {
                "schema": "SOMA_INVENTORY_NEEDS_FILTER_V1",
                "service_request_id": sr_id,
                "customer_org_id": customer_id,
                "lifecycle_state": lifecycle_state,
                "bom_code": normalized_bom,
                "bom_key": bom_key,
            }
        )
        after = self._decode_need_cursor(cursor, filter_fingerprint=fingerprint)

        with ReadSnapshot(self._factory) as snapshot:
            clauses: list[str] = []
            params: list[object] = []
            if sr_id is not None:
                clauses.append("n.service_request_id=?")
                params.append(sr_id)
            if customer_id is not None:
                clauses.append(
                    "EXISTS(SELECT 1 FROM sr_customer_relationships scr "
                    "WHERE scr.service_request_id=n.service_request_id "
                    "AND scr.relationship_state='active' AND scr.customer_org_id=?)"
                )
                params.append(customer_id)
            if lifecycle_state is not None:
                clauses.append("p.lifecycle_state=?")
                params.append(lifecycle_state)
            if bom_key is not None:
                clauses.append("n.bom_key=?")
                params.append(bom_key)
            where = "" if not clauses else "WHERE " + " AND ".join(clauses)
            rows = snapshot.connection.execute(
                "SELECT n.spare_need_id,n.service_request_id,n.bom_code,n.bom_key,"
                "n.description,p.lifecycle_state,p.planned_quantity,p.contributor_count,"
                "p.revision,p.input_fingerprint "
                "FROM spare_needs n JOIN spare_need_current_projection p "
                "ON p.spare_need_id=n.spare_need_id "
                f"{where} "
                "ORDER BY n.service_request_id,n.bom_key,n.spare_need_id",
                tuple(params),
            ).fetchall()

            projected: list[tuple[tuple[str, str, str], dict[str, object]]] = []
            for row in rows:
                need_id = str(row[0])
                key = (str(row[1]), str(row[3]), need_id)
                if after is not None and key <= after:
                    continue
                request_rows = snapshot.connection.execute(
                    "SELECT a.spare_request_id,a.quantity,a.active_draft,"
                    "p.lifecycle_state,p.current_sr7,p.revision "
                    "FROM spare_request_need_allocations a "
                    "JOIN spare_request_current_projection p "
                    "ON p.spare_request_id=a.spare_request_id "
                    "WHERE a.spare_need_id=? "
                    "ORDER BY a.spare_request_id",
                    (need_id,),
                ).fetchall()
                fulfillment_rows = snapshot.connection.execute(
                    "SELECT f.local_fulfillment_event_id,f.spare_part_unit_id,f.task_id,"
                    "f.event_kind,f.recorded_at_utc "
                    "FROM local_need_fulfillment_events f "
                    "WHERE f.spare_need_id=? "
                    "ORDER BY f.recorded_at_utc,f.local_fulfillment_event_id",
                    (need_id,),
                ).fetchall()
                history_rows = snapshot.connection.execute(
                    "SELECT need_event_id,event_kind,planned_quantity,reason_code,"
                    "effective_at_utc,recorded_at_utc "
                    "FROM spare_need_lifecycle_events WHERE spare_need_id=? "
                    "ORDER BY recorded_at_utc,need_event_id",
                    (need_id,),
                ).fetchall()
                request_quantity = sum(int(item[1]) for item in request_rows)
                current_local_selected = {
                    str(item[1])
                    for item in fulfillment_rows
                    if str(item[3]) == "selected"
                } - {
                    str(item[1])
                    for item in fulfillment_rows
                    if str(item[3]) in {"released", "superseded"}
                }
                blockers: list[str] = []
                if str(row[5]) != "active":
                    blockers.append("need_not_active")
                if any(
                    str(item[3]) not in {"cancelled", "rejected"}
                    for item in request_rows
                ):
                    blockers.append("nonterminal_request_dependency")
                projected.append(
                    (
                        key,
                        {
                            "spare_need_id": need_id,
                            "service_request_id": str(row[1]),
                            "bom_code": str(row[2]),
                            "description": None if row[4] is None else str(row[4]),
                            "lifecycle_state": str(row[5]),
                            "planned_quantity": int(row[6]),
                            "contributor_count": int(row[7]),
                            "revision": int(row[8]),
                            "input_fingerprint": str(row[9]),
                            "request_allocation_quantity": request_quantity,
                            "request_count": len(request_rows),
                            "local_selected_quantity": len(current_local_selected),
                            "request_histories": [
                                {
                                    "spare_request_id": str(item[0]),
                                    "quantity": int(item[1]),
                                    "active_draft": bool(item[2]),
                                    "lifecycle_state": str(item[3]),
                                    "current_sr7": None
                                    if item[4] is None
                                    else str(item[4]),
                                    "revision": int(item[5]),
                                }
                                for item in request_rows
                            ],
                            "local_fulfillment_history": [
                                {
                                    "local_fulfillment_event_id": str(item[0]),
                                    "spare_part_unit_id": str(item[1]),
                                    "task_id": None if item[2] is None else str(item[2]),
                                    "event_kind": str(item[3]),
                                    "recorded_at_utc": int(item[4]),
                                }
                                for item in fulfillment_rows
                            ],
                            "lifecycle_history": [
                                {
                                    "need_event_id": str(item[0]),
                                    "event_kind": str(item[1]),
                                    "planned_quantity": None
                                    if item[2] is None
                                    else int(item[2]),
                                    "reason_code": None
                                    if item[3] is None
                                    else str(item[3]),
                                    "effective_at_utc": None
                                    if item[4] is None
                                    else int(item[4]),
                                    "recorded_at_utc": int(item[5]),
                                }
                                for item in history_rows
                            ],
                            "action_blockers": blockers,
                        },
                    )
                )

            exact_total = len(projected)
            selected = projected[:page_limit]
            continuation = None
            if len(projected) > page_limit and selected:
                last_key = selected[-1][0]
                continuation = {
                    "version": 1,
                    "query_id": _NEED_QUERY_ID,
                    "sort_registry_id": _NEED_SORT_ID,
                    "last_key_tuple": list(last_key),
                    "filter_fingerprint": fingerprint,
                    "null_order": "not_applicable",
                }
            return InventoryNeedPage(
                items=tuple(item for _key, item in selected),
                continuation=continuation,
                exact_total=exact_total,
            )

    def preview_device_part_duplicates(
        self,
        *,
        bom_code: str,
        manufacturer_serial: str | None,
        limit: int = 100,
    ) -> tuple[DevicePartDuplicateCandidate, ...]:
        _stored_bom, bom_key = normalize_part_code(bom_code)
        _stored_serial, serial_key = normalize_optional_serial(manufacturer_serial)
        if serial_key is None:
            return ()
        page_limit = _limit(limit)
        with ReadSnapshot(self._factory) as snapshot:
            rows = snapshot.connection.execute(
                "SELECT device_part_unit_id,service_request_id,device_reference_id,creation_sequence,"
                "bom_code,manufacturer_serial FROM device_part_units "
                "WHERE bom_key=? AND serial_key=? "
                "ORDER BY creation_sequence,device_part_unit_id LIMIT ?",
                (bom_key, serial_key, page_limit),
            ).fetchall()
        return tuple(
            DevicePartDuplicateCandidate(
                device_part_unit_id=str(row[0]),
                service_request_id=str(row[1]),
                device_reference_id=str(row[2]),
                creation_sequence=int(row[3]),
                bom_code=str(row[4]),
                manufacturer_serial=None if row[5] is None else str(row[5]),
            )
            for row in rows
        )

    def preview_spare_part_duplicates(
        self,
        *,
        bom_code: str,
        manufacturer_serial: str | None,
        limit: int = 100,
    ) -> tuple[SparePartDuplicateCandidate, ...]:
        _stored_bom, bom_key = normalize_part_code(bom_code)
        _stored_serial, serial_key = normalize_optional_serial(manufacturer_serial)
        if serial_key is None:
            return ()
        page_limit = _limit(limit)
        with ReadSnapshot(self._factory) as snapshot:
            rows = self._units.duplicate_candidates(
                snapshot.connection,
                bom_key=bom_key,
                serial_key=serial_key,
                limit=page_limit,
            )
        return tuple(
            SparePartDuplicateCandidate(
                spare_part_unit_id=str(row[0]),
                local_tracking_id=None if row[1] is None else str(row[1]),
                bom_code=str(row[2]),
                manufacturer_serial=None if row[3] is None else str(row[3]),
                condition_token=str(row[4]),
                disposition_token=str(row[5]),
                revision=int(row[6]),
            )
            for row in rows
        )

    def stock_eligibility(
        self,
        *,
        bom_code: str | None = None,
        spare_need_id: str | None = None,
        cursor: dict[str, object] | None = None,
        limit: int = 100,
    ) -> StockEligibilityPage:
        page_limit = _limit(limit)
        if bom_code is not None and spare_need_id is not None:
            raise ValidationError("Stock query accepts bom_code or spare_need_id, not both")

        normalized_bom: str | None = None
        requested_bom_key: str | None = None
        need_id: str | None = None
        if bom_code is not None:
            normalized_bom, requested_bom_key = normalize_part_code(bom_code)
        elif spare_need_id is not None:
            need_id = require_uuid4(spare_need_id)

        with ReadSnapshot(self._factory) as snapshot:
            if need_id is not None:
                need = snapshot.connection.execute(
                    "SELECT n.bom_code,n.bom_key,p.lifecycle_state "
                    "FROM spare_needs n JOIN spare_need_current_projection p "
                    "ON p.spare_need_id=n.spare_need_id WHERE n.spare_need_id=?",
                    (need_id,),
                ).fetchone()
                if need is None:
                    raise ValidationError("Spare Need does not exist")
                if str(need[2]) != "active":
                    raise ValidationError("Spare Need is not active")
                normalized_bom = str(need[0])
                requested_bom_key = str(need[1])

            fingerprint = sha256_canonical_json(
                {
                    "schema": "SOMA_STOCK_ELIGIBILITY_FILTER_V1",
                    "bom_code": normalized_bom,
                    "bom_key": requested_bom_key,
                    "spare_need_id": need_id,
                }
            )
            after_key = _decode_cursor(
                cursor,
                filter_fingerprint=fingerprint,
            )

            rows = snapshot.connection.execute(
                "SELECT u.spare_part_unit_id,u.local_tracking_id,u.bom_code,u.bom_key,"
                "u.manufacturer_serial,p.condition_token,p.disposition_token,p.location_kind,"
                "p.location_ref_id,p.custody_text,p.active_task_allocation_id "
                "FROM spare_part_units u JOIN spare_part_current_projection p "
                "ON p.spare_part_unit_id=u.spare_part_unit_id "
                "ORDER BY COALESCE(u.local_tracking_id,''),u.spare_part_unit_id"
            ).fetchall()

            projected: list[tuple[tuple[int, str, str], StockEligibilityItem]] = []
            for row in rows:
                unit_bom_key = str(row[3])
                if requested_bom_key is None:
                    compatibility = "unknown"
                elif unit_bom_key == requested_bom_key:
                    compatibility = "exact"
                else:
                    compatibility = "incompatible"

                local_tracking = None if row[1] is None else str(row[1])
                unit_id = str(row[0])
                sort_key = _stock_sort_key(
                    compatibility,
                    local_tracking,
                    unit_id,
                )

                blockers = tuple(
                    self._units.stock_blockers(
                        snapshot.connection,
                        unit_id,
                    )
                )
                projected.append(
                    (
                        sort_key,
                        StockEligibilityItem(
                            spare_part_unit_id=unit_id,
                            local_tracking_id=local_tracking,
                            bom_code=str(row[2]),
                            manufacturer_serial=None if row[4] is None else str(row[4]),
                            condition_token=str(row[5]),
                            disposition_token=str(row[6]),
                            location_kind=None if row[7] is None else str(row[7]),
                            location_ref_id=None if row[8] is None else str(row[8]),
                            custody_text=None if row[9] is None else str(row[9]),
                            active_task_allocation_id=None
                            if row[10] is None
                            else str(row[10]),
                            compatibility_classification=compatibility,
                            availability_blockers=blockers,
                        ),
                    )
                )

            projected.sort(key=lambda item: item[0])
            exact_total = len(projected)
            remaining = (
                projected
                if after_key is None
                else [item for item in projected if item[0] > after_key]
            )
            selected = remaining[: page_limit + 1]
            has_more = len(selected) > page_limit
            page_rows = selected[:page_limit]
            next_cursor: dict[str, object] | None = None
            if has_more and page_rows:
                key = page_rows[-1][0]
                next_cursor = {
                    "version": 1,
                    "query_id": _STOCK_QUERY_ID,
                    "sort_registry_id": _STOCK_SORT_ID,
                    "last_key_tuple": [key[0], key[1], key[2]],
                    "filter_fingerprint": fingerprint,
                    "null_order": "empty_before_text",
                }
            return StockEligibilityPage(
                items=tuple(item for _key, item in page_rows),
                continuation=next_cursor,
                exact_total=exact_total,
            )


__all__ = [
    "InventoryNeedPage",
    "DevicePartDuplicateCandidate",
    "InventoryNeedsQueryService",
    "SparePartDuplicateCandidate",
    "StockEligibilityItem",
    "StockEligibilityPage",
]
