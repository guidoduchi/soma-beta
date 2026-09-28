from __future__ import annotations

import base64
from typing import Any, Iterator

from soma.foundation.audit.writer import AuditEventInput, AuditResultRef, AuditWriter
from soma.foundation.errors import IntegrityFailure, SomaError, ValidationError
from soma.foundation.identifiers import new_uuid4, require_uuid4
from soma.foundation.persistence.uow import ReadSnapshot, UnitOfWork
from soma.foundation.strict_json import (
    ObjectContract,
    canonical_json_bytes,
    canonical_json_bytes_bounded,
    loads_canonical_json,
    sha256_canonical_json,
)
from soma.inventory.audit_registry import build_inventory_audit_registry
from soma.inventory.domain.proposals import (
    ParsedInventoryProposalTarget,
    parse_inventory_proposal_target,
    source_evidence_ref,
    validate_proposal_kind,
    validate_risk_tier,
)
from soma.inventory.repositories.fault_tags import InventoryFaultTagsRepository
from soma.inventory.repositories.requests import InventoryRequestsRepository
from soma.inventory.repositories.units import InventoryUnitsRepository
from soma.product_line_sla.report_sections import (
    ReportSectionDescriptor,
    ReportSectionRow,
)
from soma.reference.domain.dependencies import (
    DependencyBlocker,
    DependencyGuard,
    DependencyPage,
    ReferenceTarget,
)
from soma.tickets.service_request_sla_input import ServiceRequestSlaInputReader

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

    @classmethod
    def apply_retry_relationship_clone(
        cls,
        uow: UnitOfWork,
        preview: dict[str, object],
        new_task_id: str,
        command_context: dict[str, object],
    ) -> tuple[dict[str, str], ...]:
        successor = require_uuid4(new_task_id)
        if not isinstance(command_context, dict) or set(command_context) != {
            "command_id", "actor_kind", "actor_id"
        }:
            raise ValidationError("Inventory retry clone command_context is invalid")
        command_id_raw = command_context.get("command_id")
        actor_kind = command_context.get("actor_kind")
        actor_id = command_context.get("actor_id")
        if not isinstance(command_id_raw, str):
            raise ValidationError("Inventory retry clone command_id must be UUID text")
        command_id = require_uuid4(command_id_raw)
        if not isinstance(actor_kind, str) or not actor_kind:
            raise ValidationError("Inventory retry clone actor_kind is invalid")
        if actor_id is not None and not isinstance(actor_id, str):
            raise ValidationError("Inventory retry clone actor_id is invalid")
        if not isinstance(preview, dict) or preview.get("schema") != "SOMA_INVENTORY_RETRY_CLONE_PREVIEW_V1":
            raise SomaError("DEPENDENCY_INDETERMINATE", "Inventory retry clone preview is invalid")
        predecessor_raw = preview.get("predecessor_task_id")
        relationships = preview.get("relationships")
        fingerprint = preview.get("input_fingerprint")
        if not isinstance(predecessor_raw, str) or not isinstance(relationships, list):
            raise SomaError("DEPENDENCY_INDETERMINATE", "Inventory retry clone preview is incomplete")
        predecessor = require_uuid4(predecessor_raw)
        selected_ids: list[str] = []
        for item in relationships:
            if not isinstance(item, dict) or item.get("status") != "eligible":
                raise SomaError(
                    "DEPENDENCY_INDETERMINATE",
                    "Selected Inventory retry relationship is not currently eligible",
                )
            allocation_id = item.get("id")
            if not isinstance(allocation_id, str):
                raise SomaError("DEPENDENCY_INDETERMINATE", "Inventory retry allocation id is invalid")
            selected_ids.append(require_uuid4(allocation_id))
        recomputed = cls.preview_retry_relationship_clone(uow, predecessor, tuple(selected_ids))
        if (
            not isinstance(fingerprint, str)
            or recomputed.get("input_fingerprint") != fingerprint
            or recomputed.get("relationships") != relationships
        ):
            raise SomaError("INV_STALE", "Inventory retry clone preview changed")
        writer = AuditWriter(build_inventory_audit_registry())
        refs: list[dict[str, str]] = []
        for item in relationships:
            allocation_id = str(item["id"])
            event_id, unit_id, spare_need_id, allocation_revision, unit_revision = (
                InventoryUnitsRepository.reassign_task_allocation(
                    uow.connection,
                    allocation_id=allocation_id,
                    predecessor_task_id=predecessor,
                    new_task_id=successor,
                    expected_allocation_revision=int(item["revision"]),
                    command_id=command_id,
                )
            )
            unit = InventoryUnitsRepository.current_unit(uow.connection, unit_id)
            if unit is None:
                raise IntegrityFailure("Retry reassignment lost Spare Part Unit authority")
            writer.write(
                uow,
                AuditEventInput(
                    audit_event_id=new_uuid4(),
                    action_type="inventory.spare_unit.registered_or_reserved",
                    action_version=1,
                    actor_kind=actor_kind,
                    actor_id=actor_id,
                    target_type="spare_part_unit",
                    target_id=unit_id,
                    command_id=command_id,
                    reason_category="retry_clone",
                    payload_schema="SpareUnitAuditV1",
                    payload_version=1,
                    payload={
                        "spare_part_unit_id": unit_id,
                        "event_kind": "REASSIGN",
                        "local_tracking_id": None if unit[1] is None else str(unit[1]),
                        "task_id": successor,
                        "allocation_id": allocation_id,
                        "spare_need_id": spare_need_id,
                        "resulting_unit_revision": unit_revision,
                        "allocation_revision": allocation_revision,
                        "bom_fingerprint": None,
                        "reason_category": "retry_clone",
                    },
                    resulting_event_refs=(
                        AuditResultRef("task_unit_allocation_event", event_id),
                    ),
                ),
            )
            refs.append({"type": "task_unit_allocation_event", "id": event_id})
        return tuple(refs)


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
    _CURSOR_PREFIX = "SOMA_INVENTORY_DEPENDENCY_CURSOR_V1."
    _CURSOR_MAX_BYTES = 2048

    @staticmethod
    def _blocker_key(blocker: DependencyBlocker) -> tuple[str, str]:
        return blocker.blocker_id, blocker.reason_code

    @classmethod
    def _encode_cursor(
        cls,
        target: ReferenceTarget,
        blocker: DependencyBlocker,
    ) -> str:
        payload = {
            "schema": "SOMA_INVENTORY_DEPENDENCY_CURSOR_V1",
            "target_type": target.target_type,
            "target_id": target.target_id,
            "blocker_id": blocker.blocker_id,
            "reason_code": blocker.reason_code,
        }
        raw = canonical_json_bytes_bounded(
            payload,
            max_bytes=cls._CURSOR_MAX_BYTES,
            max_depth=2,
            max_collection_items=8,
        )
        token = base64.urlsafe_b64encode(raw).rstrip(b"=").decode("ascii")
        return cls._CURSOR_PREFIX + token

    @classmethod
    def _decode_cursor(
        cls,
        target: ReferenceTarget,
        cursor: str,
    ) -> tuple[str, str]:
        try:
            if not cursor.startswith(cls._CURSOR_PREFIX):
                raise ValueError("wrong cursor version")
            token = cursor[len(cls._CURSOR_PREFIX) :]
            if not token or len(token) > cls._CURSOR_MAX_BYTES * 2:
                raise ValueError("cursor length is invalid")
            encoded = token.encode("ascii")
            encoded += b"=" * ((4 - len(encoded) % 4) % 4)
            raw = base64.b64decode(encoded, altchars=b"-_", validate=True)
            if len(raw) > cls._CURSOR_MAX_BYTES:
                raise ValueError("cursor payload is oversized")
            payload = loads_canonical_json(
                raw.decode("utf-8", errors="strict"),
                max_bytes=cls._CURSOR_MAX_BYTES,
                max_depth=2,
                max_collection_items=8,
            )
            if not isinstance(payload, dict) or set(payload) != {
                "schema",
                "target_type",
                "target_id",
                "blocker_id",
                "reason_code",
            }:
                raise ValueError("cursor payload shape is invalid")
            if payload["schema"] != "SOMA_INVENTORY_DEPENDENCY_CURSOR_V1":
                raise ValueError("cursor schema is invalid")
            if (
                payload["target_type"] != target.target_type
                or payload["target_id"] != target.target_id
            ):
                raise ValueError("cursor target does not match")
            blocker_id = payload["blocker_id"]
            reason_code = payload["reason_code"]
            if (
                not isinstance(blocker_id, str)
                or not blocker_id
                or not isinstance(reason_code, str)
                or not reason_code
            ):
                raise ValueError("cursor ordering key is invalid")
            return blocker_id, reason_code
        except Exception as exc:
            raise ValidationError("Inventory dependency cursor is invalid") from exc

    @staticmethod
    def _source_queries(
        target: ReferenceTarget,
    ) -> tuple[tuple[str, tuple[object, ...]], ...]:
        target_id = target.target_id
        if target.target_type == "contact":
            return (
                (
                    "SELECT r.spare_request_id AS blocker_id,"
                    "'active_spare_request_requester' AS reason_code "
                    "FROM spare_requests r "
                    "JOIN spare_request_current_projection p "
                    "ON p.spare_request_id=r.spare_request_id "
                    "WHERE r.requester_contact_id=? "
                    "AND p.lifecycle_state NOT IN ('cancelled','rejected')",
                    (target_id,),
                ),
                (
                    "SELECT l.spare_request_id AS blocker_id,"
                    "'active_spare_request_receiver' AS reason_code "
                    "FROM spare_request_draft_logistics l "
                    "JOIN spare_request_current_projection p "
                    "ON p.spare_request_id=l.spare_request_id "
                    "WHERE l.receiver_contact_id=? AND p.lifecycle_state='draft'",
                    (target_id,),
                ),
                (
                    "SELECT t.fault_tag_id AS blocker_id,"
                    "'active_fault_tag_pickup_contact' AS reason_code "
                    "FROM fault_tags t "
                    "JOIN fault_tag_current_projection p "
                    "ON p.fault_tag_id=t.fault_tag_id "
                    "WHERE t.draft_pickup_contact_id=? AND p.state='draft'",
                    (target_id,),
                ),
            )
        if target.target_type == "dispatch_location":
            return (
                (
                    "SELECT l.spare_request_id AS blocker_id,"
                    "'active_spare_request_dispatch_location' AS reason_code "
                    "FROM spare_request_draft_logistics l "
                    "JOIN spare_request_current_projection p "
                    "ON p.spare_request_id=l.spare_request_id "
                    "WHERE l.dispatch_location_id=? AND p.lifecycle_state='draft'",
                    (target_id,),
                ),
                (
                    "SELECT t.fault_tag_id AS blocker_id,"
                    "'active_fault_tag_pickup_origin' AS reason_code "
                    "FROM fault_tags t "
                    "JOIN fault_tag_current_projection p "
                    "ON p.fault_tag_id=t.fault_tag_id "
                    "WHERE t.draft_pickup_dispatch_location_id=? AND p.state='draft'",
                    (target_id,),
                ),
            )
        if target.target_type == "customer_organization":
            # Inventory customer scope is derived through LLD-03 Service Request
            # authority. The empty source still proves the provider/schema query
            # path is available when guards are used only as an availability probe.
            return (
                (
                    "SELECT CAST(NULL AS TEXT) AS blocker_id,"
                    "CAST(NULL AS TEXT) AS reason_code WHERE 0",
                    (),
                ),
            )
        raise ValidationError(
            "reference target_type is outside Inventory dependency scope"
        )

    @classmethod
    def _source_query(
        cls,
        target: ReferenceTarget,
    ) -> tuple[str, tuple[object, ...]]:
        sources = cls._source_queries(target)
        # Blocker identity + reason is unique inside each source and reason codes
        # differ across sources, so UNION ALL preserves exact blocker semantics
        # without paying UNION's duplicate-elimination sort.
        return (
            " UNION ALL ".join(sql for sql, _params in sources),
            tuple(value for _sql, params in sources for value in params),
        )

    @classmethod
    def _first_blocker(
        cls,
        connection: Any,
        target: ReferenceTarget,
    ) -> DependencyBlocker | None:
        # A write-path guard needs existence, not the globally smallest blocker.
        # Probe each owner source independently so indexed target predicates can
        # stop at the first match instead of materializing/sorting a compound UNION.
        # Source order is fixed only to make the reported blocking reason stable.
        for source, params in cls._source_queries(target):
            row = connection.execute(source + " LIMIT 1", params).fetchone()
            if row is not None:
                return DependencyBlocker(str(row[0]), str(row[1]))
        return None

    @classmethod
    def _count_blockers(cls, connection: Any, target: ReferenceTarget) -> int:
        source, params = cls._source_query(target)
        row = connection.execute(
            "SELECT COUNT(*) FROM (" + source + ") blockers",
            params,
        ).fetchone()
        if row is None:
            raise IntegrityFailure("Inventory dependency count returned no row")
        count = int(row[0])
        if count < 0:
            raise IntegrityFailure("Inventory dependency count is invalid")
        return count

    @classmethod
    def _page_blockers(
        cls,
        connection: Any,
        target: ReferenceTarget,
        cursor: str | None,
        limit: int,
    ) -> DependencyPage:
        if type(limit) is not int or limit < 1 or limit > 200:
            raise ValidationError("Inventory dependency page limit must be in 1..200")
        source, params = cls._source_query(target)
        where = ""
        query_params: tuple[object, ...] = params
        if cursor is not None:
            blocker_id, reason_code = cls._decode_cursor(target, cursor)
            where = (
                " WHERE blocker_id>? OR "
                "(blocker_id=? AND reason_code>?)"
            )
            query_params = (*params, blocker_id, blocker_id, reason_code)
        rows = connection.execute(
            "SELECT blocker_id,reason_code FROM (" + source + ") blockers"
            + where
            + " ORDER BY blocker_id,reason_code LIMIT ?",
            (*query_params, limit + 1),
        ).fetchall()
        has_more = len(rows) > limit
        visible = rows[:limit]
        blockers = tuple(
            DependencyBlocker(str(row[0]), str(row[1]))
            for row in visible
        )
        continuation = (
            cls._encode_cursor(target, blockers[-1])
            if has_more and blockers
            else None
        )
        return DependencyPage(blockers, continuation)

    def guard_archive(self, uow: UnitOfWork, target: ReferenceTarget) -> DependencyGuard:
        try:
            blocker = self._first_blocker(uow.connection, target)
        except Exception:
            return DependencyGuard("INDETERMINATE", "inventory_dependency_unavailable")
        return (
            DependencyGuard("BLOCKED", blocker.reason_code)
            if blocker is not None
            else DependencyGuard("CLEAR")
        )

    def guard_reactivate(self, uow: UnitOfWork, target: ReferenceTarget) -> DependencyGuard:
        try:
            # A bounded probe proves the provider/schema is available. Inventory has no
            # reactivation blocker of its own in LLD-07.
            self._first_blocker(uow.connection, target)
        except Exception:
            return DependencyGuard("INDETERMINATE", "inventory_dependency_unavailable")
        return DependencyGuard("CLEAR")

    def count_archive_blockers(self, snapshot: ReadSnapshot, target: ReferenceTarget) -> int:
        return self._count_blockers(snapshot.connection, target)

    def list_archive_blockers(
        self,
        snapshot: ReadSnapshot,
        target: ReferenceTarget,
        cursor: str | None,
        limit: int,
    ) -> DependencyPage:
        return self._page_blockers(snapshot.connection, target, cursor, limit)

    def count_reactivation_blockers(self, snapshot: ReadSnapshot, target: ReferenceTarget) -> int:
        # Use a bounded probe so an unavailable Inventory authority fails closed rather
        # than being mistaken for an empty blocker set.
        self._first_blocker(snapshot.connection, target)
        return 0

    def list_reactivation_blockers(
        self,
        snapshot: ReadSnapshot,
        target: ReferenceTarget,
        cursor: str | None,
        limit: int,
    ) -> DependencyPage:
        if type(limit) is not int or limit < 1 or limit > 200:
            raise ValidationError("Inventory dependency page limit must be in 1..200")
        self._first_blocker(snapshot.connection, target)
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


class InventoryProposalTargetService:
    """Typed LLD-09 proposal participant over LLD-07 owner reducers.

    The caller owns the outer command receipt and transaction. This participant
    validates only the three Beta 1.0 owner actions and never persists message
    bodies or a second proposal authority.
    """

    _TARGET_FIELDS = frozenset(
        {
            "proposal_target_id",
            "target_kind",
            "target_id",
            "expected_revision",
            "proposed_action",
            "payload",
        }
    )
    _EVIDENCE_FIELDS = frozenset({"evidence_kind", "evidence_id", "risk_tier"})
    _ACCEPTED_FIELDS = frozenset(
        {
            "proposal_kind",
            "target_refs",
            "evidence_ref",
            "base_token",
            "preview_fingerprint",
            "explicit_confirmation",
        }
    )
    _COMMAND_FIELDS = frozenset({"command_id", "actor_kind", "actor_id"})

    @classmethod
    def _evidence(cls, evidence_ref: object) -> tuple[str, str, str]:
        if not isinstance(evidence_ref, dict) or set(evidence_ref) != cls._EVIDENCE_FIELDS:
            raise ValidationError("Inventory proposal evidence_ref is invalid")
        evidence_kind = evidence_ref.get("evidence_kind")
        evidence_id = evidence_ref.get("evidence_id")
        risk_tier = evidence_ref.get("risk_tier")
        if not isinstance(evidence_kind, str) or not isinstance(evidence_id, str):
            raise ValidationError("Inventory proposal evidence reference is invalid")
        source_evidence_ref(evidence_kind, evidence_id)
        return evidence_kind, evidence_id, validate_risk_tier(risk_tier)

    @classmethod
    def _targets(
        cls,
        *,
        proposal_kind: str,
        target_refs: object,
        risk_tier: str,
    ) -> tuple[ParsedInventoryProposalTarget, ...]:
        if not isinstance(target_refs, (tuple, list)) or not target_refs:
            raise ValidationError("Inventory proposal requires one or more targets")
        parsed: list[ParsedInventoryProposalTarget] = []
        for raw in target_refs:
            if not isinstance(raw, dict) or set(raw) != cls._TARGET_FIELDS:
                raise ValidationError("Inventory proposal target fields are invalid")
            target_id = raw.get("target_id")
            payload = raw.get("payload")
            if not isinstance(target_id, str) or not isinstance(payload, dict):
                raise ValidationError("Inventory proposal target is invalid")
            target_kind = raw.get("target_kind")
            parsed.append(
                parse_inventory_proposal_target(
                    proposal_target_id=raw.get("proposal_target_id"),
                    proposal_kind=proposal_kind,
                    risk_tier=risk_tier,
                    target_kind=target_kind,
                    spare_request_id=target_id if target_kind == "spare_request" else None,
                    membership_id=(
                        target_id if target_kind == "fault_tag_membership" else None
                    ),
                    expected_revision=raw.get("expected_revision"),
                    proposed_action=raw.get("proposed_action"),
                    payload_json=canonical_json_bytes(payload).decode("utf-8"),
                )
            )
        identities = tuple(item.proposal_target_id for item in parsed)
        if len(set(identities)) != len(identities):
            raise ValidationError("Inventory proposal target identities contain duplicates")
        return tuple(sorted(parsed, key=lambda item: item.proposal_target_id))

    @staticmethod
    def _target_state(reader: Reader, target: ParsedInventoryProposalTarget) -> dict[str, object]:
        if target.action == "spare_request_submission":
            assert target.spare_request_id is not None
            row = InventoryRequestsRepository.current_detail(
                reader.connection,
                target.spare_request_id,
            )
            if row is None:
                raise SomaError("PROPOSAL_STALE", "Spare Request target is missing")
            return {
                "proposal_target_id": target.proposal_target_id,
                "target_kind": "spare_request",
                "target_id": target.spare_request_id,
                "state": str(row[6]),
                "revision": int(row[8]),
                "input_fingerprint": str(row[9]),
            }
        assert target.membership_id is not None
        required_state = (
            "submitted_awaiting_receipt"
            if target.action == "warehouse_received"
            else "warehouse_received"
        )
        row, obligation = InventoryFaultTagsRepository._require_warehouse_target(
            reader.connection,
            membership_id=target.membership_id,
            expected_revision=target.expected_revision,
            required_state=required_state,
        )
        return {
            "proposal_target_id": target.proposal_target_id,
            "target_kind": "fault_tag_membership",
            "target_id": target.membership_id,
            "state": str(row[5]),
            "active_submitted": int(row[6]),
            "revision": int(row[7]),
            "last_event_id": None if row[8] is None else str(row[8]),
            "rma_id": str(row[2]),
            "physical_consequence_id": str(row[9]),
            "device_part_unit_id": None if row[3] is None else str(row[3]),
            "spare_part_unit_id": None if row[4] is None else str(row[4]),
            "obligation_state": str(obligation[0]),
            "obligation_revision": int(obligation[4]),
            "obligation_last_event_id": (
                None if obligation[5] is None else str(obligation[5])
            ),
        }

    @classmethod
    def base_token(
        cls,
        snapshot: Reader,
        proposal_kind: str,
        target_refs: object,
        evidence_ref: object | None = None,
    ) -> str:
        kind = validate_proposal_kind(proposal_kind)
        if evidence_ref is None:
            risk_tier = "material_final" if kind == "warehouse_final_decision" else "normal"
        else:
            _evidence_kind, _evidence_id, risk_tier = cls._evidence(evidence_ref)
        targets = cls._targets(
            proposal_kind=kind,
            target_refs=target_refs,
            risk_tier=risk_tier,
        )
        states = tuple(cls._target_state(snapshot, target) for target in targets)
        return sha256_canonical_json(
            {
                "schema": "SOMA_INVENTORY_PROPOSAL_BASE_V1",
                "proposal_kind": kind,
                "targets": states,
            }
        )

    @classmethod
    def preview(
        cls,
        snapshot: Reader,
        proposal_kind: str,
        target_refs: object,
        evidence_ref: object,
    ) -> dict[str, object]:
        try:
            kind = validate_proposal_kind(proposal_kind)
            evidence_kind, evidence_id, risk_tier = cls._evidence(evidence_ref)
            targets = cls._targets(
                proposal_kind=kind,
                target_refs=target_refs,
                risk_tier=risk_tier,
            )
            if kind == "spare_request_submission" and evidence_kind != "indexed_sent":
                raise ValidationError(
                    "Spare Request proposal requires indexed_sent evidence"
                )
            states = tuple(cls._target_state(snapshot, target) for target in targets)
            for target, state in zip(targets, states, strict=True):
                if target.action == "spare_request_submission" and (
                    state["state"] != "draft"
                    or state["revision"] != target.expected_revision
                    or state["input_fingerprint"] != target.expected_draft_fingerprint
                ):
                    raise SomaError(
                        "PROPOSAL_STALE",
                        "Spare Request draft authority changed",
                    )
            base_token = sha256_canonical_json(
                {
                    "schema": "SOMA_INVENTORY_PROPOSAL_BASE_V1",
                    "proposal_kind": kind,
                    "targets": states,
                }
            )
            impact = {
                "schema": "SOMA_INVENTORY_PROPOSAL_IMPACT_V1",
                "status": "READY",
                "proposal_kind": kind,
                "evidence_ref": {
                    "evidence_kind": evidence_kind,
                    "evidence_id": evidence_id,
                    "risk_tier": risk_tier,
                },
                "base_token": base_token,
                "target_count": len(targets),
                "targets": states,
                "requires_explicit_confirmation": kind == "warehouse_final_decision",
            }
            return {**impact, "input_fingerprint": sha256_canonical_json(impact)}
        except (SomaError, ValidationError, IntegrityFailure) as exc:
            return {
                "schema": "SOMA_INVENTORY_PROPOSAL_IMPACT_V1",
                "status": "INDETERMINATE",
                "reason_code": getattr(exc, "code", "VALIDATION_FAILED"),
            }

    @classmethod
    def apply(
        cls,
        uow: UnitOfWork,
        accepted_proposal: object,
        command_context: object,
    ) -> tuple[dict[str, str], ...]:
        if (
            not isinstance(accepted_proposal, dict)
            or set(accepted_proposal) != cls._ACCEPTED_FIELDS
        ):
            raise ValidationError("accepted Inventory proposal fields are invalid")
        if not isinstance(command_context, dict) or set(command_context) != cls._COMMAND_FIELDS:
            raise ValidationError("Inventory proposal command_context is invalid")
        command_id = require_uuid4(command_context.get("command_id"))
        actor_kind = command_context.get("actor_kind")
        actor_id = command_context.get("actor_id")
        if not isinstance(actor_kind, str) or not actor_kind:
            raise ValidationError("Inventory proposal actor_kind is invalid")
        if actor_id is not None and not isinstance(actor_id, str):
            raise ValidationError("Inventory proposal actor_id is invalid")
        if uow.connection.execute(
            "SELECT 1 FROM command_receipts WHERE command_id=?",
            (command_id,),
        ).fetchone() is None:
            raise SomaError(
                "DEPENDENCY_INDETERMINATE",
                "Inventory proposal participant requires the caller command receipt",
            )

        proposal_kind = accepted_proposal.get("proposal_kind")
        target_refs = accepted_proposal.get("target_refs")
        evidence_ref = accepted_proposal.get("evidence_ref")
        expected_base = accepted_proposal.get("base_token")
        expected_preview = accepted_proposal.get("preview_fingerprint")
        explicit_confirmation = accepted_proposal.get("explicit_confirmation")
        if not isinstance(expected_base, str) or not isinstance(expected_preview, str):
            raise ValidationError("accepted Inventory proposal fingerprints are invalid")
        impact = cls.preview(uow, proposal_kind, target_refs, evidence_ref)
        if impact.get("status") != "READY":
            raise SomaError("DEPENDENCY_INDETERMINATE", "Inventory proposal is indeterminate")
        if (
            impact.get("base_token") != expected_base
            or impact.get("input_fingerprint") != expected_preview
        ):
            raise SomaError("PROPOSAL_STALE", "Inventory proposal target authority changed")
        if impact["requires_explicit_confirmation"] and explicit_confirmation is not True:
            raise SomaError(
                "DEPENDENCY_INDETERMINATE",
                "Material warehouse final decision requires explicit confirmation",
            )

        kind = validate_proposal_kind(proposal_kind)
        evidence_kind, evidence_id, risk_tier = cls._evidence(evidence_ref)
        targets = cls._targets(
            proposal_kind=kind,
            target_refs=target_refs,
            risk_tier=risk_tier,
        )
        writer = AuditWriter(build_inventory_audit_registry())
        refs: list[dict[str, str]] = []
        if kind == "spare_request_submission":
            for target in targets:
                assert target.spare_request_id is not None
                assert target.expected_draft_fingerprint is not None
                event_id, snapshot_id, _revision, allocation_count, _snapshot_hash = (
                    InventoryRequestsRepository.accept_submission(
                        uow.connection,
                        spare_request_id=target.spare_request_id,
                        expected_fingerprint=target.expected_draft_fingerprint,
                        effective_submission_at_utc=target.effective_at_utc,
                        evidence_kind="indexed_sent",
                        evidence_id=evidence_id,
                        command_id=command_id,
                    )
                )
                writer.write(
                    uow,
                    AuditEventInput(
                        audit_event_id=new_uuid4(),
                        action_type="inventory.spare_request.submitted",
                        action_version=1,
                        actor_kind=actor_kind,
                        actor_id=actor_id,
                        target_type="spare_request",
                        target_id=target.spare_request_id,
                        command_id=command_id,
                        payload_schema="SpareRequestSubmissionAuditV1",
                        payload_version=1,
                        payload={
                            "spare_request_id": target.spare_request_id,
                            "submission_event_id": event_id,
                            "submission_snapshot_id": snapshot_id,
                            "event_kind": "ACCEPT",
                            "allocation_count": allocation_count,
                            "input_fingerprint": target.expected_draft_fingerprint,
                            "effective_at_utc": target.effective_at_utc,
                        },
                        resulting_event_refs=(
                            AuditResultRef("spare_request_submission_snapshot", snapshot_id),
                        ),
                    ),
                )
                refs.extend(
                    (
                        {"type": "spare_request_submission_event", "id": event_id},
                        {"type": "spare_request_submission_snapshot", "id": snapshot_id},
                    )
                )
            return tuple(refs)

        batch_id = new_uuid4() if len(targets) > 1 else None
        if batch_id is not None:
            InventoryFaultTagsRepository.insert_lifecycle_batch(
                uow.connection,
                batch_id=batch_id,
                batch_kind="proposal_acceptance",
                target_count=len(targets),
                command_id=command_id,
            )
            refs.append({"type": "inventory_lifecycle_batch", "id": batch_id})
        for target in targets:
            assert target.membership_id is not None
            if target.action == "warehouse_received":
                rows, _tag_revisions = InventoryFaultTagsRepository.record_warehouse_receipt(
                    uow.connection,
                    targets=((target.membership_id, target.expected_revision),),
                    effective_at_utc=target.effective_at_utc,
                    evidence_kind=evidence_kind,
                    evidence_id=evidence_id,
                    batch_id=None,
                    command_id=command_id,
                )
                event_kind = "RECEIVED"
            else:
                rows, _tag_revisions = (
                    InventoryFaultTagsRepository.record_warehouse_final_decision(
                        uow.connection,
                        targets=((target.membership_id, target.expected_revision),),
                        decision=str(target.decision),
                        reason_code=target.reason_code,
                        effective_at_utc=target.effective_at_utc,
                        evidence_kind=evidence_kind,
                        evidence_id=evidence_id,
                        batch_id=None,
                        command_id=command_id,
                    )
                )
                event_kind = "ACCEPTED" if target.decision == "accepted" else "REJECTED"
            row = rows[0]
            event_id = str(row["membership_event_id"])
            writer.write(
                uow,
                AuditEventInput(
                    audit_event_id=new_uuid4(),
                    action_type="inventory.fault_tag.warehouse_state_changed",
                    action_version=1,
                    actor_kind=actor_kind,
                    actor_id=actor_id,
                    target_type="fault_tag_membership",
                    target_id=target.membership_id,
                    command_id=command_id,
                    reason_category=target.reason_code,
                    payload_schema="WarehouseDecisionAuditV1",
                    payload_version=1,
                    payload={
                        "membership_id": target.membership_id,
                        "event_kind": event_kind,
                        "rma_id": str(row["rma_id"]),
                        "return_obligation_id": str(row["rma_id"]),
                        "batch_id": batch_id,
                        "effective_at_utc": target.effective_at_utc,
                        "explicit_confirmation": bool(explicit_confirmation),
                    },
                    resulting_event_refs=(
                        AuditResultRef("fault_tag_membership_event", event_id),
                    ),
                ),
            )
            refs.append({"type": "fault_tag_membership_event", "id": event_id})
        return tuple(refs)


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


class InventoryReportSectionContributor:
    """Minimized Inventory facts for the exact LLD-06 report Snapshot scope."""

    _CONTRACT = ObjectContract(
        name="InventoryReportSectionV1",
        version=1,
        required_fields=frozenset(
            {
                "service_request_id",
                "as_of_utc",
                "spare_need_count",
                "active_spare_need_count",
                "spare_request_count",
                "open_rma_count",
                "fault_tag_count",
                "open_return_obligation_count",
                "attention_count",
            }
        ),
        allowed_fields=frozenset(
            {
                "service_request_id",
                "as_of_utc",
                "spare_need_count",
                "active_spare_need_count",
                "spare_request_count",
                "open_rma_count",
                "fault_tag_count",
                "open_return_obligation_count",
                "attention_count",
            }
        ),
        max_depth=2,
        max_collection_items=16,
        max_utf8_bytes=4096,
    )

    @classmethod
    def section_descriptor(cls) -> ReportSectionDescriptor:
        return ReportSectionDescriptor(
            section_kind="inventory_summary",
            schema_name=cls._CONTRACT.name,
            schema_version=cls._CONTRACT.version,
            ordinal=700,
            payload_contract=cls._CONTRACT,
        )

    @staticmethod
    def _count(connection: Any, sql: str, params: tuple[object, ...]) -> int:
        row = connection.execute(sql, params).fetchone()
        return 0 if row is None else int(row[0])

    @classmethod
    def _row(cls, connection: Any, service_request_id: str, as_of_utc: int) -> ReportSectionRow:
        sr_id = require_uuid4(service_request_id)
        rma_scope = (
            "SELECT m.rma_id FROM rmas m JOIN spare_requests q "
            "ON q.spare_request_id=m.spare_request_id WHERE q.service_request_id=?"
        )
        fault_tag_scope = (
            "SELECT DISTINCT fm.fault_tag_id FROM fault_tag_memberships fm "
            "WHERE fm.rma_id IN (" + rma_scope + ")"
        )
        attention_count = cls._count(
            connection,
            "SELECT COUNT(*) FROM inventory_attention_projection a WHERE "
            "(a.target_kind='spare_need' AND a.target_id IN "
            "(SELECT spare_need_id FROM spare_needs WHERE service_request_id=?)) OR "
            "(a.target_kind='spare_request' AND a.target_id IN "
            "(SELECT spare_request_id FROM spare_requests WHERE service_request_id=?)) OR "
            "(a.target_kind='rma' AND a.target_id IN (" + rma_scope + ")) OR "
            "(a.target_kind='fault_tag' AND a.target_id IN (" + fault_tag_scope + "))",
            (sr_id, sr_id, sr_id, sr_id),
        )
        payload = {
            "service_request_id": sr_id,
            "as_of_utc": as_of_utc,
            "spare_need_count": cls._count(
                connection,
                "SELECT COUNT(*) FROM spare_needs WHERE service_request_id=?",
                (sr_id,),
            ),
            "active_spare_need_count": cls._count(
                connection,
                "SELECT COUNT(*) FROM spare_needs n JOIN spare_need_current_projection p "
                "ON p.spare_need_id=n.spare_need_id "
                "WHERE n.service_request_id=? AND p.lifecycle_state='active'",
                (sr_id,),
            ),
            "spare_request_count": cls._count(
                connection,
                "SELECT COUNT(*) FROM spare_requests WHERE service_request_id=?",
                (sr_id,),
            ),
            "open_rma_count": cls._count(
                connection,
                "SELECT COUNT(*) FROM rma_lifecycle_projection p WHERE p.rma_id IN ("
                + rma_scope
                + ") AND p.state<>'closed_accepted'",
                (sr_id,),
            ),
            "fault_tag_count": cls._count(
                connection,
                "SELECT COUNT(*) FROM fault_tags t WHERE t.fault_tag_id IN ("
                + fault_tag_scope
                + ")",
                (sr_id,),
            ),
            "open_return_obligation_count": cls._count(
                connection,
                "SELECT COUNT(*) FROM rma_return_obligation_current o WHERE o.rma_id IN ("
                + rma_scope
                + ") AND o.obligation_state='open'",
                (sr_id,),
            ),
            "attention_count": attention_count,
        }
        return ReportSectionRow(canonical_row_key=sr_id, payload=payload)

    @classmethod
    def stream_snapshot_rows(
        cls,
        snapshot: Any,
        report_request: dict[str, object],
        as_of_utc: int,
    ) -> tuple[ReportSectionRow, ...]:
        if type(as_of_utc) is not int or as_of_utc < 0:
            raise ValidationError("Inventory report as_of_utc is invalid")
        period_start = report_request.get("period_start_utc")
        period_end = report_request.get("period_end_utc")
        customer_id = report_request.get("customer_org_id")
        if type(period_start) is not int or type(period_end) is not int:
            raise ValidationError("Inventory report period bounds are invalid")
        if customer_id is not None and not isinstance(customer_id, str):
            raise ValidationError("Inventory report customer scope is invalid")

        rows: list[ReportSectionRow] = []
        cursor: str | None = None
        while True:
            page = ServiceRequestSlaInputReader.list_report_date_month(
                snapshot,
                period_start,
                period_end,
                customer_id,
                cursor,
                500,
            )
            rows.extend(
                cls._row(snapshot, item.service_request_id, as_of_utc)
                for item in page.items
            )
            if page.next_cursor is None:
                break
            cursor = page.next_cursor
        return tuple(rows)


# Normative module-map service name; the explicit Inventory name avoids ambiguity at
# composition roots that also import the LLD-06 protocol.
ReportSectionContributor = InventoryReportSectionContributor


__all__ = [
    "InventoryCommunicationIdentityProvider",
    "InventoryDevicePartReferenceReader",
    "InventoryOverviewProjectionProvider",
    "InventoryPhysicalConsequenceReader",
    "InventoryProposalTargetService",
    "InventoryReportSectionContributor",
    "InventoryReferenceDependencyValidator",
    "InventorySiteDependencyValidator",
    "InventoryTaskDependencyProvider",
    "ReportSectionContributor",
    "RfcInventoryDependencyProvider",
]
