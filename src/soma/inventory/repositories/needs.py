from __future__ import annotations

from dataclasses import dataclass

from soma.foundation.errors import SomaError
from soma.foundation.identifiers import new_uuid4
from soma.foundation.persistence.uow import UnitOfWork
from soma.foundation.strict_json import sha256_canonical_json


@dataclass(frozen=True, slots=True)
class NeedProjection:
    spare_need_id: str
    service_request_id: str
    bom_code: str
    bom_key: str
    lifecycle_state: str
    planned_quantity: int
    contributor_count: int
    revision: int


class InventoryNeedRepository:
    @staticmethod
    def allocate_creation_sequence(uow: UnitOfWork, command_id: str) -> int:
        row = uow.connection.execute(
            "SELECT next_sequence FROM inventory_tracking_allocators "
            "WHERE allocator_kind='device_part_creation'"
        ).fetchone()
        if row is None:
            raise SomaError("INV_INVALID_ID", "Device Part allocator is missing")
        value = int(row[0])
        if value >= 100_000_000:
            raise SomaError("INV_INVALID_ID", "Device Part creation sequence is exhausted")
        uow.connection.execute(
            "UPDATE inventory_tracking_allocators "
            "SET next_sequence=next_sequence+1,revision=revision+1,last_command_id=? "
            "WHERE allocator_kind='device_part_creation'",
            (command_id,),
        )
        return value

    @staticmethod
    def active_need_id(connection, service_request_id: str, bom_key: str) -> str | None:
        row = connection.execute(
            "SELECT spare_need_id FROM spare_need_active_keys "
            "WHERE service_request_id=? AND bom_key=?",
            (service_request_id, bom_key),
        ).fetchone()
        return None if row is None else str(row[0])

    @staticmethod
    def load_projection(connection, spare_need_id: str) -> NeedProjection | None:
        row = connection.execute(
            "SELECT n.spare_need_id,n.service_request_id,n.bom_code,n.bom_key,"
            "p.lifecycle_state,p.planned_quantity,p.contributor_count,p.revision "
            "FROM spare_needs n JOIN spare_need_current_projection p "
            "ON p.spare_need_id=n.spare_need_id WHERE n.spare_need_id=?",
            (spare_need_id,),
        ).fetchone()
        if row is None:
            return None
        return NeedProjection(
            spare_need_id=str(row[0]),
            service_request_id=str(row[1]),
            bom_code=str(row[2]),
            bom_key=str(row[3]),
            lifecycle_state=str(row[4]),
            planned_quantity=int(row[5]),
            contributor_count=int(row[6]),
            revision=int(row[7]),
        )

    @staticmethod
    def projection_fingerprint(
        connection,
        *,
        spare_need_id: str,
        lifecycle_state: str,
        planned_quantity: int,
    ) -> tuple[str, int]:
        rows = connection.execute(
            "SELECT device_part_unit_id FROM spare_need_contributors "
            "WHERE spare_need_id=? AND active=1 ORDER BY device_part_unit_id",
            (spare_need_id,),
        ).fetchall()
        contributors = [str(row[0]) for row in rows]
        return (
            sha256_canonical_json(
                {
                    "schema": "INVENTORY_SPARE_NEED_PROJECTION_V1",
                    "spare_need_id": spare_need_id,
                    "lifecycle_state": lifecycle_state,
                    "planned_quantity": planned_quantity,
                    "contributors": contributors,
                }
            ),
            len(contributors),
        )

    @classmethod
    def rebuild_projection(
        cls,
        uow: UnitOfWork,
        *,
        spare_need_id: str,
        lifecycle_state: str,
        planned_quantity: int,
        revision: int,
        command_id: str,
    ) -> None:
        fingerprint, count = cls.projection_fingerprint(
            uow.connection,
            spare_need_id=spare_need_id,
            lifecycle_state=lifecycle_state,
            planned_quantity=planned_quantity,
        )
        uow.connection.execute(
            "INSERT INTO spare_need_current_projection("
            "spare_need_id,lifecycle_state,planned_quantity,contributor_count,"
            "revision,input_fingerprint,last_command_id"
            ") VALUES (?,?,?,?,?,?,?) "
            "ON CONFLICT(spare_need_id) DO UPDATE SET "
            "lifecycle_state=excluded.lifecycle_state,"
            "planned_quantity=excluded.planned_quantity,"
            "contributor_count=excluded.contributor_count,"
            "revision=excluded.revision,"
            "input_fingerprint=excluded.input_fingerprint,"
            "last_command_id=excluded.last_command_id",
            (
                spare_need_id,
                lifecycle_state,
                planned_quantity,
                count,
                revision,
                fingerprint,
                command_id,
            ),
        )

    @staticmethod
    def contributor_for_unit(connection, device_part_unit_id: str) -> tuple[str, str] | None:
        row = connection.execute(
            "SELECT contributor_relationship_id,spare_need_id "
            "FROM spare_need_contributors WHERE device_part_unit_id=? AND active=1",
            (device_part_unit_id,),
        ).fetchone()
        return None if row is None else (str(row[0]), str(row[1]))


__all__ = ["InventoryNeedRepository", "NeedProjection"]
