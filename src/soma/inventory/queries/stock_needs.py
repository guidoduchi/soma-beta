from __future__ import annotations

from dataclasses import dataclass

from soma.foundation.persistence.connections import ConnectionFactory
from soma.foundation.persistence.uow import ReadSnapshot

from ..domain.needs import normalize_optional_serial, normalize_part_code


@dataclass(frozen=True, slots=True)
class DevicePartDuplicateCandidate:
    device_part_unit_id: str
    service_request_id: str
    device_reference_id: str
    creation_sequence: int
    bom_code: str
    manufacturer_serial: str | None


class InventoryNeedsQueryService:
    def __init__(self, connection_factory: ConnectionFactory) -> None:
        self._factory = connection_factory

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
        page_limit = max(1, min(int(limit), 500))
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
