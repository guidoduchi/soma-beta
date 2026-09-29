from __future__ import annotations

from dataclasses import dataclass
from typing import Hashable

from soma.foundation.errors import SomaError
from soma.infrastructure.domain.relationships import CONTAINMENT_HARD_DEPTH


@dataclass(frozen=True, slots=True)
class RackPlacementIntent:
    network_element_id: str
    rack_id: str
    u_start: int
    u_span: int


@dataclass(frozen=True, slots=True)
class PrimaryIpIntent:
    target_key: Hashable
    current_is_primary: bool
    requested_primary: bool | None


def validate_rack_placement_batch(reader, intents: tuple[RackPlacementIntent, ...]) -> None:
    if not intents:
        return
    by_element: dict[str, RackPlacementIntent] = {}
    for intent in intents:
        if intent.network_element_id in by_element:
            raise SomaError(
                "WORKBOOK_RELATION_INVALID",
                "Workbook acceptance contains duplicate placement changes for one Network Element",
            )
        if intent.u_start < 1 or intent.u_span < 1:
            raise SomaError("WORKBOOK_RELATION_INVALID", "Workbook Rack interval is invalid")
        by_element[intent.network_element_id] = intent

    element_ids = tuple(sorted(by_element))
    placeholders = ",".join("?" for _ in element_ids)
    element_rows = reader.connection.execute(
        f"SELECT network_element_id,site_id,lifecycle_state FROM network_elements "
        f"WHERE network_element_id IN ({placeholders})",
        element_ids,
    ).fetchall()
    elements = {str(row[0]): (str(row[1]), str(row[2])) for row in element_rows}
    if set(elements) != set(element_ids) or any(state != "active" for _site, state in elements.values()):
        raise SomaError("WORKBOOK_STALE", "Workbook placement target is missing or archived")

    rack_ids = tuple(sorted({intent.rack_id for intent in intents}))
    rack_placeholders = ",".join("?" for _ in rack_ids)
    rack_rows = reader.connection.execute(
        f"""
        SELECT r.rack_id,r.height_u,r.lifecycle_state,rm.site_id,rm.lifecycle_state,s.lifecycle_state
        FROM racks r
        JOIN rooms rm ON rm.room_id=r.room_id
        JOIN sites s ON s.site_id=rm.site_id
        WHERE r.rack_id IN ({rack_placeholders})
        """,
        rack_ids,
    ).fetchall()
    racks = {
        str(row[0]): (
            int(row[1]),
            str(row[2]),
            str(row[3]),
            str(row[4]),
            str(row[5]),
        )
        for row in rack_rows
    }
    if set(racks) != set(rack_ids):
        raise SomaError("WORKBOOK_RELATION_INVALID", "Workbook Rack target does not exist")

    affected = set(rack_ids)
    current_rows = reader.connection.execute(
        f"SELECT network_element_id,rack_id FROM network_element_placement_current "
        f"WHERE network_element_id IN ({placeholders})",
        element_ids,
    ).fetchall()
    for _element_id, rack_id in current_rows:
        if rack_id is not None:
            affected.add(str(rack_id))

    occupancy: dict[str, list[tuple[int, int, str]]] = {rack_id: [] for rack_id in affected}
    if affected:
        affected_ids = tuple(sorted(affected))
        affected_placeholders = ",".join("?" for _ in affected_ids)
        rows = reader.connection.execute(
            f"""
            SELECT network_element_id,rack_id,u_start,u_span
            FROM network_element_placement_current
            WHERE rack_id IN ({affected_placeholders})
            ORDER BY rack_id,u_start,network_element_id
            """,
            affected_ids,
        ).fetchall()
        moving = set(by_element)
        for element_id, rack_id, u_start, u_span in rows:
            if str(element_id) in moving:
                continue
            occupancy[str(rack_id)].append(
                (int(u_start), int(u_start) + int(u_span), str(element_id))
            )

    for intent in sorted(intents, key=lambda item: item.network_element_id):
        rack = racks[intent.rack_id]
        height_u, rack_state, rack_site_id, room_state, site_state = rack
        if rack_state != "active" or room_state != "active" or site_state != "active":
            raise SomaError("WORKBOOK_RELATION_INVALID", "Workbook Rack target is archived")
        element_site_id = elements[intent.network_element_id][0]
        if rack_site_id != element_site_id:
            raise SomaError("PLACEMENT_CROSS_SITE", "Workbook Rack target belongs to another Site")
        end = intent.u_start + intent.u_span
        if end - 1 > height_u:
            raise SomaError("RACK_U_OUT_OF_RANGE", "Workbook Rack interval exceeds Rack height")
        for occupied_start, occupied_end, _occupant in occupancy.setdefault(intent.rack_id, []):
            if intent.u_start < occupied_end and end > occupied_start:
                raise SomaError("RACK_U_OCCUPIED", "Workbook Rack interval overlaps another placement")
        occupancy[intent.rack_id].append(
            (intent.u_start, end, intent.network_element_id)
        )


def validate_containment_batch(
    reader,
    intents: dict[str, str | None],
) -> None:
    if not intents:
        return
    if any(child == parent for child, parent in intents.items() if parent is not None):
        raise SomaError("CONTAINMENT_SELF", "Workbook containment cannot self-parent")

    cache: dict[str, str | None] = {}

    def parent_of(identity: str) -> str | None:
        if identity in intents:
            return intents[identity]
        if identity in cache:
            return cache[identity]
        row = reader.connection.execute(
            "SELECT lifecycle_state FROM network_elements WHERE network_element_id=?",
            (identity,),
        ).fetchone()
        if row is None or str(row[0]) != "active":
            raise SomaError(
                "WORKBOOK_RELATION_INVALID",
                "Workbook containment target is missing or archived",
            )
        current = reader.connection.execute(
            "SELECT parent_network_element_id FROM network_element_containment_current "
            "WHERE child_network_element_id=?",
            (identity,),
        ).fetchone()
        value = None if current is None else str(current[0])
        cache[identity] = value
        return value

    for child in sorted(intents):
        child_row = reader.connection.execute(
            "SELECT lifecycle_state FROM network_elements WHERE network_element_id=?",
            (child,),
        ).fetchone()
        if child_row is None or str(child_row[0]) != "active":
            raise SomaError("WORKBOOK_STALE", "Workbook containment child is missing or archived")
        visited: set[str] = set()
        current: str | None = child
        while current is not None:
            if current in visited:
                raise SomaError("CONTAINMENT_CYCLE", "Workbook containment batch creates a cycle")
            if len(visited) >= CONTAINMENT_HARD_DEPTH:
                raise SomaError(
                    "DEPENDENCY_INDETERMINATE",
                    "Workbook containment batch exceeds the ancestry depth bound",
                )
            visited.add(current)
            current = parent_of(current)


def validate_primary_ip_batch(intents: tuple[PrimaryIpIntent, ...]) -> None:
    grouped: dict[Hashable, list[PrimaryIpIntent]] = {}
    for intent in intents:
        grouped.setdefault(intent.target_key, []).append(intent)
    for target_key, group in grouped.items():
        requested_true = sum(intent.requested_primary is True for intent in group)
        if requested_true > 1:
            raise SomaError(
                "IP_PRIMARY_CONFLICT",
                "Workbook acceptance selects multiple primary IPs for one Network Element",
            )
        explicitly_unset_current = any(
            intent.current_is_primary and intent.requested_primary is False
            for intent in group
        )
        if explicitly_unset_current and requested_true == 0:
            raise SomaError(
                "IP_PRIMARY_CONFLICT",
                "Workbook cannot leave an existing Network Element without an explicit replacement primary",
            )


__all__ = [
    "PrimaryIpIntent",
    "RackPlacementIntent",
    "validate_containment_batch",
    "validate_primary_ip_batch",
    "validate_rack_placement_batch",
]
