from __future__ import annotations

from typing import Any, Iterator

from soma.foundation.errors import SomaError, ValidationError
from soma.foundation.identifiers import require_uuid4
from soma.foundation.persistence.uow import ReadSnapshot, UnitOfWork
from soma.foundation.strict_json import sha256_canonical_json
from soma.reference.domain.dependencies import (
    DependencyBlocker,
    DependencyGuard,
    DependencyPage,
    ReferenceTarget,
)

Reader = ReadSnapshot | UnitOfWork


class InventoryPhysicalConsequenceReader:
    @staticmethod
    def get_current(reader: Reader, physical_consequence_id: str) -> dict[str, object] | None:
        identity = require_uuid4(physical_consequence_id)
        row = reader.connection.execute(
            "SELECT c.physical_consequence_id,c.task_review_fingerprint,"
            "c.physical_disposition,c.installed_spare_part_unit_id,"
            "c.removed_device_part_unit_id,c.inbound_spare_part_unit_id,"
            "c.parent_dismantled_unit_id,c.revision,c.input_fingerprint,"
            "i.task_id,i.rma_id FROM physical_consequence_current c "
            "JOIN inventory_physical_consequences i "
            "ON i.physical_consequence_id=c.physical_consequence_id "
            "WHERE c.physical_consequence_id=?",
            (identity,),
        ).fetchone()
        if row is None:
            return None
        return {
            "physical_consequence_id": str(row[0]),
            "task_review_fingerprint": str(row[1]),
            "physical_disposition": str(row[2]),
            "installed_spare_part_unit_id": None if row[3] is None else str(row[3]),
            "removed_device_part_unit_id": None if row[4] is None else str(row[4]),
            "inbound_spare_part_unit_id": None if row[5] is None else str(row[5]),
            "parent_dismantled_unit_id": None if row[6] is None else str(row[6]),
            "revision": int(row[7]),
            "input_fingerprint": str(row[8]),
            "task_id": str(row[9]),
            "rma_id": None if row[10] is None else str(row[10]),
        }

    @classmethod
    def validate_current(
        cls,
        uow: UnitOfWork,
        physical_consequence_id: str,
        expected_fingerprint: str,
    ) -> str:
        try:
            current = cls.get_current(uow, physical_consequence_id)
        except Exception:
            return "INDETERMINATE"
        if current is None:
            return "INVALID"
        return (
            "VALID"
            if current["input_fingerprint"] == expected_fingerprint
            else "STALE"
        )


class InventoryTaskDependencyProvider:
    @staticmethod
    def classify_task_hard_delete_dependency(reader: Reader, task_id: str) -> str:
        try:
            identity = require_uuid4(task_id)
            connection = reader.connection
            checks = (
                ("SELECT 1 FROM task_unit_allocation_events WHERE task_id=? LIMIT 1", (identity,)),
                ("SELECT 1 FROM task_unit_allocation_current WHERE task_id=? LIMIT 1", (identity,)),
                ("SELECT 1 FROM local_need_fulfillment_events WHERE task_id=? LIMIT 1", (identity,)),
                ("SELECT 1 FROM inventory_physical_consequences WHERE task_id=? LIMIT 1", (identity,)),
            )
            for sql, params in checks:
                if connection.execute(sql, params).fetchone() is not None:
                    return "BLOCKED"
            return "CLEAR"
        except Exception:
            return "INDETERMINATE"

    @staticmethod
    def preview_retry_relationship_clone(
        snapshot: ReadSnapshot,
        predecessor_task_id: str,
        selected_inventory_relationship_ids: tuple[str, ...],
    ) -> dict[str, object]:
        predecessor = require_uuid4(predecessor_task_id)
        selected = tuple(require_uuid4(value) for value in selected_inventory_relationship_ids)
        if len(set(selected)) != len(selected):
            raise ValidationError("selected Inventory retry relationships contain duplicates")
        rows: list[dict[str, object]] = []
        for allocation_id in selected:
            row = snapshot.connection.execute(
                "SELECT allocation_id,spare_part_unit_id,spare_need_id,revision "
                "FROM task_unit_allocation_current WHERE allocation_id=? AND task_id=?",
                (allocation_id, predecessor),
            ).fetchone()
            if row is None:
                rows.append({"id": allocation_id, "status": "missing_or_stale"})
                continue
            protected = snapshot.connection.execute(
                "SELECT 1 FROM inventory_physical_consequences WHERE task_id=? LIMIT 1",
                (predecessor,),
            ).fetchone() is not None
            rows.append(
                {
                    "id": allocation_id,
                    "status": "individual_review" if protected else "eligible",
                    "spare_part_unit_id": str(row[1]),
                    "spare_need_id": None if row[2] is None else str(row[2]),
                    "revision": int(row[3]),
                }
            )
        value = {
            "schema": "SOMA_INVENTORY_RETRY_CLONE_PREVIEW_V1",
            "predecessor_task_id": predecessor,
            "relationships": rows,
        }
        return {**value, "input_fingerprint": sha256_canonical_json(value)}

    @staticmethod
    def apply_retry_relationship_clone(
        uow: UnitOfWork,
        preview: dict[str, object],
        new_task_id: str,
    ) -> tuple[dict[str, str], ...]:
        # The accepted cross-packet contract intentionally omits a command-id parameter.
        # Creating Inventory planning evidence without the caller command identity would
        # make history unauditable, so mutation remains fail-closed until the caller
        # supplies command context in a later interface revision.
        require_uuid4(new_task_id)
        raise SomaError(
            "DEPENDENCY_INDETERMINATE",
            "Inventory retry relationship clone requires caller command context",
        )


class RfcInventoryDependencyProvider:
    @staticmethod
    def classify_hard_delete_dependency(reader: Reader, rfc_id: str) -> str:
        # LLD-07 stores no direct RFC-owned foreign key. Task/RFC dependencies remain
        # LLD-05 authority and SR/RFC relationship dependencies remain LLD-03 authority.
        try:
            require_uuid4(rfc_id)
            reader.connection.execute("SELECT 1").fetchone()
            return "CLEAR"
        except Exception:
            return "INDETERMINATE"


class InventoryReferenceDependencyValidator:
    validator_id = "inventory"

    @staticmethod
    def _blockers(connection: Any, target: ReferenceTarget) -> tuple[DependencyBlocker, ...]:
        target_id = target.target_id
        blockers: list[DependencyBlocker] = []
        if target.target_type == "contact":
            rows = connection.execute(
                "SELECT r.spare_request_id FROM spare_requests r "
                "JOIN spare_request_current_projection p ON p.spare_request_id=r.spare_request_id "
                "WHERE r.requester_contact_id=? "
                "AND p.lifecycle_state NOT IN ('cancelled','rejected') "
                "ORDER BY r.spare_request_id",
                (target_id,),
            ).fetchall()
            blockers.extend(
                DependencyBlocker(str(row[0]), "active_spare_request_requester")
                for row in rows
            )
            rows = connection.execute(
                "SELECT l.spare_request_id FROM spare_request_draft_logistics l "
                "JOIN spare_request_current_projection p ON p.spare_request_id=l.spare_request_id "
                "WHERE l.receiver_contact_id=? AND p.lifecycle_state='draft' "
                "ORDER BY l.spare_request_id",
                (target_id,),
            ).fetchall()
            blockers.extend(
                DependencyBlocker(str(row[0]), "active_spare_request_receiver")
                for row in rows
            )
            rows = connection.execute(
                "SELECT t.fault_tag_id FROM fault_tags t "
                "JOIN fault_tag_current_projection p ON p.fault_tag_id=t.fault_tag_id "
                "WHERE t.draft_pickup_contact_id=? AND p.state='draft' "
                "ORDER BY t.fault_tag_id",
                (target_id,),
            ).fetchall()
            blockers.extend(
                DependencyBlocker(str(row[0]), "active_fault_tag_pickup_contact")
                for row in rows
            )
        elif target.target_type == "dispatch_location":
            rows = connection.execute(
                "SELECT l.spare_request_id FROM spare_request_draft_logistics l "
                "JOIN spare_request_current_projection p ON p.spare_request_id=l.spare_request_id "
                "WHERE l.dispatch_location_id=? AND p.lifecycle_state='draft' "
                "ORDER BY l.spare_request_id",
                (target_id,),
            ).fetchall()
            blockers.extend(
                DependencyBlocker(str(row[0]), "active_spare_request_dispatch_location")
                for row in rows
            )
            rows = connection.execute(
                "SELECT t.fault_tag_id FROM fault_tags t "
                "JOIN fault_tag_current_projection p ON p.fault_tag_id=t.fault_tag_id "
                "WHERE t.draft_pickup_dispatch_location_id=? AND p.state='draft' "
                "ORDER BY t.fault_tag_id",
                (target_id,),
            ).fetchall()
            blockers.extend(
                DependencyBlocker(str(row[0]), "active_fault_tag_pickup_origin")
                for row in rows
            )
        elif target.target_type == "customer_organization":
            # Inventory customer scope is derived through LLD-03 Service Request authority;
            # there is no direct mutable Inventory-owned Customer relationship.
            pass
        else:
            raise ValidationError("reference target_type is outside Inventory dependency scope")
        deduped = {
            (item.blocker_id, item.reason_code): item
            for item in blockers
        }
        return tuple(
            deduped[key]
            for key in sorted(deduped)
        )

    def guard_archive(self, uow: UnitOfWork, target: ReferenceTarget) -> DependencyGuard:
        try:
            blockers = self._blockers(uow.connection, target)
        except Exception:
            return DependencyGuard("INDETERMINATE", "inventory_dependency_unavailable")
        return (
            DependencyGuard("BLOCKED", blockers[0].reason_code)
            if blockers
            else DependencyGuard("CLEAR")
        )

    def guard_reactivate(self, uow: UnitOfWork, target: ReferenceTarget) -> DependencyGuard:
        try:
            self._blockers(uow.connection, target)
        except Exception:
            return DependencyGuard("INDETERMINATE", "inventory_dependency_unavailable")
        return DependencyGuard("CLEAR")

    def count_archive_blockers(self, snapshot: ReadSnapshot, target: ReferenceTarget) -> int:
        return len(self._blockers(snapshot.connection, target))

    def list_archive_blockers(
        self,
        snapshot: ReadSnapshot,
        target: ReferenceTarget,
        cursor: str | None,
        limit: int,
    ) -> DependencyPage:
        if type(limit) is not int or limit < 1 or limit > 200:
            raise ValidationError("Inventory dependency page limit must be in 1..200")
        blockers = self._blockers(snapshot.connection, target)
        start = 0
        if cursor is not None:
            matches = [
                index for index, item in enumerate(blockers)
                if item.blocker_id == cursor
            ]
            if len(matches) != 1:
                raise ValidationError("Inventory dependency cursor is invalid")
            start = matches[0] + 1
        page = blockers[start : start + limit]
        continuation = (
            page[-1].blocker_id
            if start + len(page) < len(blockers) and page
            else None
        )
        return DependencyPage(page, continuation)

    def count_reactivation_blockers(self, snapshot: ReadSnapshot, target: ReferenceTarget) -> int:
        self._blockers(snapshot.connection, target)
        return 0

    def list_reactivation_blockers(
        self,
        snapshot: ReadSnapshot,
        target: ReferenceTarget,
        cursor: str | None,
        limit: int,
    ) -> DependencyPage:
        self._blockers(snapshot.connection, target)
        if cursor is not None:
            raise ValidationError("Inventory reactivation blocker cursor is invalid")
        return DependencyPage((), None)


class InventoryDevicePartReferenceReader:
    @staticmethod
    def get_reference_context(reader: Reader, device_part_unit_id: str) -> dict[str, object] | None:
        identity = require_uuid4(device_part_unit_id)
        row = reader.connection.execute(
            "SELECT device_part_unit_id,service_request_id,device_reference_id,"
            "creation_sequence,bom_code,bom_key,manufacturer_serial,serial_key,"
            "slot_label,creation_origin FROM device_part_units WHERE device_part_unit_id=?",
            (identity,),
        ).fetchone()
        if row is None:
            return None
        return {
            "device_part_unit_id": str(row[0]),
            "service_request_id": str(row[1]),
            "device_reference_id": str(row[2]),
            "creation_sequence": int(row[3]),
            "bom_code": str(row[4]),
            "bom_key": str(row[5]),
            "manufacturer_serial": None if row[6] is None else str(row[6]),
            "serial_key": None if row[7] is None else str(row[7]),
            "slot_label": None if row[8] is None else str(row[8]),
            "creation_origin": str(row[9]),
        }


class InventorySiteDependencyValidator:
    @staticmethod
    def _count(connection: Any, site_id: str) -> int:
        identity = require_uuid4(site_id)
        row = connection.execute(
            "SELECT COUNT(*) FROM spare_part_current_projection "
            "WHERE location_kind='site' AND location_ref_id=?",
            (identity,),
        ).fetchone()
        return 0 if row is None else int(row[0])

    def guard_archive(self, uow: UnitOfWork, site_id: str) -> str:
        try:
            return "BLOCKED" if self._count(uow.connection, site_id) else "CLEAR"
        except Exception:
            return "INDETERMINATE"

    def count_blockers(self, snapshot: ReadSnapshot, site_id: str) -> int:
        return self._count(snapshot.connection, site_id)

    def list_blockers(
        self,
        snapshot: ReadSnapshot,
        site_id: str,
        cursor: str | None,
        limit: int,
    ) -> dict[str, object]:
        identity = require_uuid4(site_id)
        if type(limit) is not int or limit < 1 or limit > 200:
            raise ValidationError("site dependency limit must be in 1..200")
        params: list[object] = [identity]
        sql = (
            "SELECT spare_part_unit_id FROM spare_part_current_projection "
            "WHERE location_kind='site' AND location_ref_id=?"
        )
        if cursor is not None:
            require_uuid4(cursor)
            sql += " AND spare_part_unit_id>?"
            params.append(cursor)
        sql += " ORDER BY spare_part_unit_id LIMIT ?"
        params.append(limit + 1)
        rows = snapshot.connection.execute(sql, tuple(params)).fetchall()
        page = rows[:limit]
        return {
            "blockers": [str(row[0]) for row in page],
            "continuation": (
                str(page[-1][0]) if len(rows) > limit and page else None
            ),
        }


class InventoryCommunicationIdentityProvider:
    @staticmethod
    def snapshot_trackable_inventory(reader: Reader) -> Iterator[dict[str, object]]:
        connection = reader.connection
        for row in connection.execute(
            "SELECT r.spare_request_id,r.tracking_id,p.current_sr7,p.revision "
            "FROM spare_requests r JOIN spare_request_current_projection p "
            "ON p.spare_request_id=r.spare_request_id ORDER BY r.spare_request_id"
        ):
            yield {
                "target_type": "spare_request",
                "target_id": str(row[0]),
                "target_revision": int(row[3]),
                "identities": tuple(
                    item for item in (str(row[1]), None if row[2] is None else str(row[2]))
                    if item is not None
                ),
            }
        for row in connection.execute(
            "SELECT r.rma_id,a.c10,p.revision FROM rmas r "
            "JOIN rma_identifier_aliases a ON a.rma_id=r.rma_id AND a.alias_kind='current' "
            "JOIN rma_lifecycle_projection p ON p.rma_id=r.rma_id ORDER BY r.rma_id"
        ):
            yield {
                "target_type": "rma",
                "target_id": str(row[0]),
                "target_revision": int(row[2]),
                "identities": (str(row[1]),),
            }
        for row in connection.execute(
            "SELECT t.fault_tag_id,t.tracking_id,p.revision FROM fault_tags t "
            "JOIN fault_tag_current_projection p ON p.fault_tag_id=t.fault_tag_id "
            "ORDER BY t.fault_tag_id"
        ):
            yield {
                "target_type": "fault_tag",
                "target_id": str(row[0]),
                "target_revision": int(row[2]),
                "identities": (str(row[1]),),
            }

    @staticmethod
    def validate_trackable_target(
        uow: UnitOfWork,
        target_type: str,
        target_id: str,
        target_revision: int,
        matched_identity: str,
    ) -> str:
        try:
            identity = require_uuid4(target_id)
            if target_type == "spare_request":
                row = uow.connection.execute(
                    "SELECT r.tracking_id,p.current_sr7,p.revision FROM spare_requests r "
                    "JOIN spare_request_current_projection p ON p.spare_request_id=r.spare_request_id "
                    "WHERE r.spare_request_id=?",
                    (identity,),
                ).fetchone()
                if row is None:
                    return "INVALID"
                identities = {str(row[0])}
                if row[1] is not None:
                    identities.add(str(row[1]))
                revision = int(row[2])
            elif target_type == "rma":
                row = uow.connection.execute(
                    "SELECT a.c10,p.revision FROM rma_identifier_aliases a "
                    "JOIN rma_lifecycle_projection p ON p.rma_id=a.rma_id "
                    "WHERE a.rma_id=? AND a.alias_kind='current'",
                    (identity,),
                ).fetchone()
                if row is None:
                    return "INVALID"
                identities = {str(row[0])}
                revision = int(row[1])
            elif target_type == "fault_tag":
                row = uow.connection.execute(
                    "SELECT t.tracking_id,p.revision FROM fault_tags t "
                    "JOIN fault_tag_current_projection p ON p.fault_tag_id=t.fault_tag_id "
                    "WHERE t.fault_tag_id=?",
                    (identity,),
                ).fetchone()
                if row is None:
                    return "INVALID"
                identities = {str(row[0])}
                revision = int(row[1])
            else:
                return "INVALID"
            if revision != target_revision:
                return "INVALID"
            return "VALID" if matched_identity in identities else "INVALID"
        except Exception:
            return "INDETERMINATE"


class InventoryOverviewProjectionProvider:
    @staticmethod
    def project_overview(
        snapshot: ReadSnapshot,
        window: object,
        customer_scope: object,
    ) -> dict[str, object]:
        connection = snapshot.connection
        def count(sql: str) -> int:
            row = connection.execute(sql).fetchone()
            return 0 if row is None else int(row[0])
        return {
            "spare_need_active_count": count(
                "SELECT COUNT(*) FROM spare_need_current_projection WHERE lifecycle_state='active'"
            ),
            "spare_request_open_count": count(
                "SELECT COUNT(*) FROM spare_request_current_projection "
                "WHERE lifecycle_state NOT IN ('cancelled','rejected')"
            ),
            "rma_open_count": count(
                "SELECT COUNT(*) FROM rma_lifecycle_projection "
                "WHERE state NOT IN ('closed_accepted')"
            ),
            "fault_tag_open_count": count(
                "SELECT COUNT(*) FROM fault_tag_current_projection "
                "WHERE state NOT IN ('terminal_completed','cancelled','superseded')"
            ),
            "attention_count": count(
                "SELECT COUNT(*) FROM inventory_attention_projection"
            ),
        }

    @staticmethod
    def iter_communication_targets(
        snapshot: ReadSnapshot,
        window: object,
        customer_scope: object,
    ) -> Iterator[dict[str, object]]:
        yield from InventoryCommunicationIdentityProvider.snapshot_trackable_inventory(
            snapshot
        )


__all__ = [
    "InventoryCommunicationIdentityProvider",
    "InventoryDevicePartReferenceReader",
    "InventoryOverviewProjectionProvider",
    "InventoryPhysicalConsequenceReader",
    "InventoryReferenceDependencyValidator",
    "InventorySiteDependencyValidator",
    "InventoryTaskDependencyProvider",
    "RfcInventoryDependencyProvider",
]
