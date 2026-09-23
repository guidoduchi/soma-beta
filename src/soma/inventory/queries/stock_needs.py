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

    @staticmethod
    def _stock_partition_rows(
        connection,
        *,
        requested_bom_key: str | None,
        compatibility_rank: int,
        after_tracking: str | None,
        after_unit_id: str | None,
        limit: int,
    ):
        if compatibility_rank == 0:
            if requested_bom_key is None:
                raise ValidationError("exact Stock partition requires a BOM key")
            index_name = "idx_inv_070_spare_part_units_stock_bom_order"
            predicate = "u.bom_key=?"
            params: tuple[object, ...] = (requested_bom_key,)
        elif compatibility_rank == 2:
            if requested_bom_key is None:
                raise ValidationError("incompatible Stock partition requires a BOM key")
            index_name = "idx_inv_069_spare_part_units_stock_order"
            predicate = "u.bom_key<>?"
            params = (requested_bom_key,)
        elif compatibility_rank == 3:
            if requested_bom_key is not None:
                raise ValidationError("unknown Stock partition cannot carry a BOM key")
            index_name = "idx_inv_069_spare_part_units_stock_order"
            predicate = "1=1"
            params = ()
        else:
            raise ValidationError("Stock compatibility partition is invalid")

        if (after_tracking is None) != (after_unit_id is None):
            raise ValidationError("Stock partition continuation key is incomplete")
        if after_tracking is not None and after_unit_id is not None:
            require_uuid4(after_unit_id)
            predicate += (
                " AND (COALESCE(u.local_tracking_id,''),u.spare_part_unit_id)>(?,?)"
            )
            params = (*params, after_tracking, after_unit_id)

        sql = (
            "SELECT u.spare_part_unit_id,u.local_tracking_id,u.bom_code,"
            "u.manufacturer_serial,p.condition_token,p.disposition_token,"
            "p.location_kind,p.location_ref_id,p.custody_text,"
            "p.active_task_allocation_id,? AS compatibility_rank,"
            "COALESCE(u.local_tracking_id,'') AS sort_tracking "
            "FROM spare_part_units u INDEXED BY "
            + index_name
            + " CROSS JOIN spare_part_current_projection p "
            "WHERE p.spare_part_unit_id=u.spare_part_unit_id AND "
            + predicate
            + " ORDER BY COALESCE(u.local_tracking_id,''),u.spare_part_unit_id LIMIT ?"
        )
        return connection.execute(
            sql,
            (compatibility_rank, *params, limit),
        ).fetchall()

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

            exact_total_row = snapshot.connection.execute(
                "SELECT COUNT(*) FROM spare_part_units u "
                "JOIN spare_part_current_projection p "
                "ON p.spare_part_unit_id=u.spare_part_unit_id"
            ).fetchone()
            exact_total = 0 if exact_total_row is None else int(exact_total_row[0])

            target_rows = page_limit + 1
            rows = []
            if requested_bom_key is None:
                if after_key is not None and after_key[0] != 3:
                    raise ValidationError("Stock cursor compatibility rank does not match filter")
                after_tracking = None if after_key is None else after_key[1]
                after_unit_id = None if after_key is None else after_key[2]
                rows = list(
                    self._stock_partition_rows(
                        snapshot.connection,
                        requested_bom_key=None,
                        compatibility_rank=3,
                        after_tracking=after_tracking,
                        after_unit_id=after_unit_id,
                        limit=target_rows,
                    )
                )
            else:
                if after_key is not None and after_key[0] not in {0, 2}:
                    raise ValidationError("Stock cursor compatibility rank does not match filter")
                if after_key is None or after_key[0] == 0:
                    exact_after_tracking = None if after_key is None else after_key[1]
                    exact_after_unit_id = None if after_key is None else after_key[2]
                    rows.extend(
                        self._stock_partition_rows(
                            snapshot.connection,
                            requested_bom_key=requested_bom_key,
                            compatibility_rank=0,
                            after_tracking=exact_after_tracking,
                            after_unit_id=exact_after_unit_id,
                            limit=target_rows,
                        )
                    )
                    remaining = target_rows - len(rows)
                    if remaining > 0:
                        rows.extend(
                            self._stock_partition_rows(
                                snapshot.connection,
                                requested_bom_key=requested_bom_key,
                                compatibility_rank=2,
                                after_tracking=None,
                                after_unit_id=None,
                                limit=remaining,
                            )
                        )
                else:
                    rows = list(
                        self._stock_partition_rows(
                            snapshot.connection,
                            requested_bom_key=requested_bom_key,
                            compatibility_rank=2,
                            after_tracking=after_key[1],
                            after_unit_id=after_key[2],
                            limit=target_rows,
                        )
                    )

            has_more = len(rows) > page_limit
            page_rows = rows[:page_limit]
            blocker_inputs = tuple(
                (
                    str(row[0]),
                    str(row[4]),
                    str(row[5]),
                    None if row[9] is None else str(row[9]),
                )
                for row in page_rows
            )
            blockers_by_unit = self._units.stock_blockers_for_units(
                snapshot.connection,
                blocker_inputs,
            )

            items: list[StockEligibilityItem] = []
            for row in page_rows:
                unit_id = str(row[0])
                compatibility_rank = int(row[10])
                compatibility = {
                    0: "exact",
                    2: "incompatible",
                    3: "unknown",
                }.get(compatibility_rank)
                if compatibility is None:
                    raise ValidationError("Stock compatibility class is invalid")
                items.append(
                    StockEligibilityItem(
                        spare_part_unit_id=unit_id,
                        local_tracking_id=None if row[1] is None else str(row[1]),
                        bom_code=str(row[2]),
                        manufacturer_serial=None if row[3] is None else str(row[3]),
                        condition_token=str(row[4]),
                        disposition_token=str(row[5]),
                        location_kind=None if row[6] is None else str(row[6]),
                        location_ref_id=None if row[7] is None else str(row[7]),
                        custody_text=None if row[8] is None else str(row[8]),
                        active_task_allocation_id=None
                        if row[9] is None
                        else str(row[9]),
                        compatibility_classification=compatibility,
                        availability_blockers=blockers_by_unit[unit_id],
                    )
                )

            next_cursor: dict[str, object] | None = None
            if has_more and page_rows:
                last = page_rows[-1]
                key = (int(last[10]), str(last[11]), str(last[0]))
                next_cursor = {
                    "version": 1,
                    "query_id": _STOCK_QUERY_ID,
                    "sort_registry_id": _STOCK_SORT_ID,
                    "last_key_tuple": [key[0], key[1], key[2]],
                    "filter_fingerprint": fingerprint,
                    "null_order": "empty_before_text",
                }

            return StockEligibilityPage(
                items=tuple(items),
                continuation=next_cursor,
                exact_total=exact_total,
            )


__all__ = [
    "DevicePartDuplicateCandidate",
    "InventoryNeedsQueryService",
    "SparePartDuplicateCandidate",
    "StockEligibilityItem",
    "StockEligibilityPage",
]
