from __future__ import annotations

from typing import Any, Iterable

from soma.foundation.errors import IntegrityFailure, SomaError, ValidationError
from soma.foundation.identifiers import require_uuid4
from soma.reference.domain.dependencies import (
    DependencyBlocker,
    DependencyGuard,
    DependencyPage,
    ReferenceTarget,
)

from ..repositories.projections import InventoryPhysicalConsequenceRepository


def _connection(reader: Any):
    connection = getattr(reader, "connection", None)
    if connection is not None and hasattr(connection, "execute"):
        return connection
    if hasattr(reader, "execute"):
        return reader
    raise ValidationError("Inventory provider requires a database read context")


def _table_exists(connection: Any, table: str) -> bool:
    row = connection.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?",
        (table,),
    ).fetchone()
    return row is not None


def _scope_values(scope: Any) -> tuple[str, str | None]:
    if isinstance(scope, dict):
        kind = scope.get("kind")
        customer_id = scope.get("customer_org_id")
    else:
        kind = getattr(scope, "kind", None)
        customer_id = getattr(scope, "customer_org_id", None)
    if kind not in {"all", "specific", "unassigned"}:
        raise ValidationError("CustomerScopeResolutionV1 kind is invalid")
    if kind == "specific":
        if not isinstance(customer_id, str):
            raise ValidationError("specific Customer scope requires customer_org_id")
        customer_id = require_uuid4(customer_id)
    elif customer_id is not None:
        raise ValidationError("non-specific Customer scope cannot carry customer_org_id")
    return str(kind), customer_id


def _window_values(window: Any) -> dict[str, object]:
    fields = (
        "timezone",
        "current_start_utc",
        "current_end_utc",
        "previous_start_utc",
        "previous_end_utc",
        "period_kind",
        "anchor_local_date",
        "window_fingerprint",
    )
    values = {
        field: window.get(field) if isinstance(window, dict) else getattr(window, field, None)
        for field in fields
    }
    if values["timezone"] != "America/Guayaquil":
        raise ValidationError("OverviewWindowV1 timezone is invalid")
    for start, end in (
        ("current_start_utc", "current_end_utc"),
        ("previous_start_utc", "previous_end_utc"),
    ):
        if (
            type(values[start]) is not int
            or type(values[end]) is not int
            or int(values[start]) < 0
            or int(values[end]) <= int(values[start])
        ):
            raise ValidationError("OverviewWindowV1 interval is invalid")
    fingerprint = values["window_fingerprint"]
    if (
        not isinstance(fingerprint, str)
        or len(fingerprint) != 64
        or any(ch not in "0123456789abcdef" for ch in fingerprint)
    ):
        raise ValidationError("OverviewWindowV1 fingerprint is invalid")
    return values


class InventoryPhysicalConsequenceReader:
    """Minimized accepted Inventory consequence context consumed by LLD-08."""

    @staticmethod
    def get_current(snapshot: Any, physical_consequence_id: str) -> dict[str, object] | None:
        identity = require_uuid4(physical_consequence_id)
        row = InventoryPhysicalConsequenceRepository.current(
            _connection(snapshot),
            identity,
        )
        if row is None:
            return None
        revision = int(row[10])
        fingerprint = str(row[11])
        if revision <= 0 or len(fingerprint) != 64:
            raise IntegrityFailure("Inventory physical consequence projection is corrupt")
        return {
            "physical_consequence_id": str(row[0]),
            "task_id": str(row[1]),
            "task_review_fingerprint": str(row[2]),
            "target_device_part_unit_id": None if row[3] is None else str(row[3]),
            "rma_id": None if row[4] is None else str(row[4]),
            "physical_disposition": str(row[5]),
            "installed_spare_part_unit_id": None if row[6] is None else str(row[6]),
            "removed_device_part_unit_id": None if row[7] is None else str(row[7]),
            "inbound_spare_part_unit_id": None if row[8] is None else str(row[8]),
            "parent_dismantled_unit_id": None if row[9] is None else str(row[9]),
            "revision": revision,
            "input_fingerprint": fingerprint,
            "last_event_id": str(row[12]),
        }

    @classmethod
    def validate_current(
        cls,
        uow: Any,
        physical_consequence_id: str,
        expected_fingerprint: str,
    ) -> str:
        if (
            not isinstance(expected_fingerprint, str)
            or len(expected_fingerprint) != 64
            or any(ch not in "0123456789abcdef" for ch in expected_fingerprint)
        ):
            return "INDETERMINATE"
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


class RfcInventoryDependencyProvider:
    """Exact read-only Inventory predicate for RFC hard-delete preview/commit."""

    @staticmethod
    def classify_hard_delete_dependency(reader: Any, rfc_id: str) -> str:
        try:
            identity = require_uuid4(rfc_id)
            connection = _connection(reader)
            if connection.execute(
                "SELECT 1 FROM rfcs WHERE rfc_id=?",
                (identity,),
            ).fetchone() is None:
                return "INDETERMINATE"
            task_rows = connection.execute(
                "SELECT DISTINCT task_id FROM task_rfc_links "
                "WHERE rfc_id=? ORDER BY task_id",
                (identity,),
            ).fetchall()
            task_ids = tuple(str(row[0]) for row in task_rows)
            if not task_ids:
                return "CLEAR"
            placeholders = ",".join("?" for _ in task_ids)
            checks = (
                (
                    "SELECT 1 FROM task_unit_allocation_events "
                    f"WHERE task_id IN ({placeholders}) LIMIT 1"
                ),
                (
                    "SELECT 1 FROM task_unit_allocation_current "
                    f"WHERE task_id IN ({placeholders}) LIMIT 1"
                ),
                (
                    "SELECT 1 FROM local_need_fulfillment_events "
                    f"WHERE task_id IN ({placeholders}) LIMIT 1"
                ),
                (
                    "SELECT 1 FROM inventory_physical_consequences "
                    f"WHERE task_id IN ({placeholders}) LIMIT 1"
                ),
            )
            for sql in checks:
                if connection.execute(sql, task_ids).fetchone() is not None:
                    return "BLOCKED"
            return "CLEAR"
        except Exception:
            return "INDETERMINATE"


class InventoryDevicePartReferenceReader:
    """Minimized Device Part context for Infrastructure regularization."""

    @staticmethod
    def get_reference_context(
        snapshot_or_uow: Any,
        device_part_unit_id: str,
    ) -> dict[str, object] | None:
        identity = require_uuid4(device_part_unit_id)
        connection = _connection(snapshot_or_uow)
        row = connection.execute(
            "SELECT d.device_part_unit_id,d.service_request_id,d.device_reference_id,"
            "d.creation_sequence,d.bom_code,d.manufacturer_serial,d.slot_label,"
            "d.creation_origin,d.created_at_utc,p.condition_token,p.revision,"
            "p.input_fingerprint,p.last_event_id "
            "FROM device_part_units d JOIN device_part_current_projection p "
            "ON p.device_part_unit_id=d.device_part_unit_id "
            "WHERE d.device_part_unit_id=?",
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
            "manufacturer_serial": None if row[5] is None else str(row[5]),
            "slot_label": None if row[6] is None else str(row[6]),
            "creation_origin": str(row[7]),
            "created_at_utc": int(row[8]),
            "condition_token": str(row[9]),
            "revision": int(row[10]),
            "input_fingerprint": str(row[11]),
            "last_event_id": str(row[12]),
        }


class InventoryReferenceDependencyValidator:
    """LLD-02 reference lifecycle validator over Inventory-owned dependencies."""

    validator_id = "inventory"

    @staticmethod
    def _validate_target(target: ReferenceTarget) -> ReferenceTarget:
        if not isinstance(target, ReferenceTarget):
            raise ValidationError("Inventory reference target is invalid")
        require_uuid4(target.target_id)
        return target

    @classmethod
    def _blockers(
        cls,
        reader: Any,
        target: ReferenceTarget,
    ) -> tuple[DependencyBlocker, ...]:
        target = cls._validate_target(target)
        connection = _connection(reader)
        blockers: list[DependencyBlocker] = []

        def add(prefix: str, identity: str, reason: str) -> None:
            blockers.append(
                DependencyBlocker(
                    blocker_id=f"{prefix}:{identity}",
                    reason_code=reason,
                )
            )

        if target.target_type == "contact":
            rows = connection.execute(
                "SELECT r.spare_request_id FROM spare_requests r "
                "JOIN spare_request_current_projection p "
                "ON p.spare_request_id=r.spare_request_id "
                "WHERE r.requester_contact_id=? "
                "AND p.lifecycle_state NOT IN ('authorized','cancelled','rejected') "
                "ORDER BY r.spare_request_id",
                (target.target_id,),
            ).fetchall()
            for row in rows:
                add("spare_request_requester", str(row[0]), "active_requester_contact")

            rows = connection.execute(
                "SELECT l.spare_request_id FROM spare_request_draft_logistics l "
                "JOIN spare_request_current_projection p "
                "ON p.spare_request_id=l.spare_request_id "
                "WHERE l.receiver_contact_id=? "
                "AND p.lifecycle_state NOT IN ('authorized','cancelled','rejected') "
                "ORDER BY l.spare_request_id",
                (target.target_id,),
            ).fetchall()
            for row in rows:
                add("spare_request_receiver", str(row[0]), "active_receiver_contact")

            rows = connection.execute(
                "SELECT t.fault_tag_id FROM fault_tags t "
                "JOIN fault_tag_current_projection p ON p.fault_tag_id=t.fault_tag_id "
                "WHERE t.draft_pickup_contact_id=? AND p.state='draft' "
                "ORDER BY t.fault_tag_id",
                (target.target_id,),
            ).fetchall()
            for row in rows:
                add("fault_tag_pickup", str(row[0]), "active_fault_tag_pickup_contact")

        elif target.target_type == "dispatch_location":
            rows = connection.execute(
                "SELECT l.spare_request_id FROM spare_request_draft_logistics l "
                "JOIN spare_request_current_projection p "
                "ON p.spare_request_id=l.spare_request_id "
                "WHERE l.dispatch_location_id=? "
                "AND p.lifecycle_state NOT IN ('authorized','cancelled','rejected') "
                "ORDER BY l.spare_request_id",
                (target.target_id,),
            ).fetchall()
            for row in rows:
                add(
                    "spare_request_dispatch",
                    str(row[0]),
                    "active_request_dispatch_location",
                )

            rows = connection.execute(
                "SELECT t.fault_tag_id FROM fault_tags t "
                "JOIN fault_tag_current_projection p ON p.fault_tag_id=t.fault_tag_id "
                "WHERE t.draft_pickup_dispatch_location_id=? AND p.state='draft' "
                "ORDER BY t.fault_tag_id",
                (target.target_id,),
            ).fetchall()
            for row in rows:
                add(
                    "fault_tag_pickup",
                    str(row[0]),
                    "active_fault_tag_dispatch_location",
                )

        elif target.target_type == "customer_organization":
            rows = connection.execute(
                "SELECT n.spare_need_id FROM spare_needs n "
                "JOIN spare_need_current_projection np ON np.spare_need_id=n.spare_need_id "
                "JOIN sr_customer_relationships c "
                "ON c.service_request_id=n.service_request_id "
                "AND c.relationship_state='active' "
                "WHERE c.customer_org_id=? AND np.lifecycle_state='active' "
                "ORDER BY n.spare_need_id",
                (target.target_id,),
            ).fetchall()
            for row in rows:
                add("spare_need", str(row[0]), "active_inventory_need")

            rows = connection.execute(
                "SELECT r.spare_request_id FROM spare_requests r "
                "JOIN spare_request_current_projection p "
                "ON p.spare_request_id=r.spare_request_id "
                "JOIN sr_customer_relationships c "
                "ON c.service_request_id=r.service_request_id "
                "AND c.relationship_state='active' "
                "WHERE c.customer_org_id=? "
                "AND p.lifecycle_state NOT IN ('authorized','cancelled','rejected') "
                "ORDER BY r.spare_request_id",
                (target.target_id,),
            ).fetchall()
            for row in rows:
                add("spare_request", str(row[0]), "active_inventory_request")

            rows = connection.execute(
                "SELECT o.rma_id FROM rma_return_obligation_current o "
                "JOIN rmas rm ON rm.rma_id=o.rma_id "
                "JOIN spare_requests r ON r.spare_request_id=rm.spare_request_id "
                "JOIN sr_customer_relationships c "
                "ON c.service_request_id=r.service_request_id "
                "AND c.relationship_state='active' "
                "WHERE c.customer_org_id=? AND o.obligation_state='open' "
                "ORDER BY o.rma_id",
                (target.target_id,),
            ).fetchall()
            for row in rows:
                add("rma_return", str(row[0]), "open_inventory_return_obligation")
        else:
            raise ValidationError("unsupported Inventory reference target type")

        blockers.sort(key=lambda item: (item.blocker_id, item.reason_code))
        deduped: list[DependencyBlocker] = []
        seen: set[tuple[str, str]] = set()
        for item in blockers:
            key = (item.blocker_id, item.reason_code)
            if key not in seen:
                seen.add(key)
                deduped.append(item)
        return tuple(deduped)

    def guard_archive(
        self,
        uow: Any,
        target: ReferenceTarget,
    ) -> DependencyGuard:
        try:
            blockers = self._blockers(uow, target)
        except Exception:
            return DependencyGuard("INDETERMINATE", "inventory_dependency_indeterminate")
        if blockers:
            return DependencyGuard("BLOCKED", blockers[0].reason_code)
        return DependencyGuard("CLEAR", None)

    def guard_reactivate(
        self,
        uow: Any,
        target: ReferenceTarget,
    ) -> DependencyGuard:
        try:
            self._validate_target(target)
            _connection(uow)
        except Exception:
            return DependencyGuard("INDETERMINATE", "inventory_dependency_indeterminate")
        return DependencyGuard("CLEAR", None)

    def count_archive_blockers(self, snapshot: Any, target: ReferenceTarget) -> int:
        return len(self._blockers(snapshot, target))

    def list_archive_blockers(
        self,
        snapshot: Any,
        target: ReferenceTarget,
        cursor: str | None,
        limit: int,
    ) -> DependencyPage:
        if type(limit) is not int or not 1 <= limit <= 500:
            raise ValidationError("Inventory dependency limit must be 1..500")
        blockers = list(self._blockers(snapshot, target))
        start = 0
        if cursor is not None:
            if not isinstance(cursor, str):
                raise ValidationError("Inventory dependency cursor is invalid")
            for index, blocker in enumerate(blockers):
                if blocker.blocker_id == cursor:
                    start = index + 1
                    break
            else:
                raise ValidationError("Inventory dependency cursor is stale")
        selected = blockers[start : start + limit]
        continuation = (
            selected[-1].blocker_id
            if start + len(selected) < len(blockers) and selected
            else None
        )
        return DependencyPage(tuple(selected), continuation)

    def count_reactivation_blockers(
        self,
        snapshot: Any,
        target: ReferenceTarget,
    ) -> int:
        self._validate_target(target)
        _connection(snapshot)
        return 0

    def list_reactivation_blockers(
        self,
        snapshot: Any,
        target: ReferenceTarget,
        cursor: str | None,
        limit: int,
    ) -> DependencyPage:
        if cursor is not None:
            raise ValidationError("reactivation dependency cursor must be null")
        if type(limit) is not int or not 1 <= limit <= 500:
            raise ValidationError("Inventory dependency limit must be 1..500")
        self._validate_target(target)
        _connection(snapshot)
        return DependencyPage((), None)


class InventorySiteDependencyValidator:
    """Site archive guard using the LLD-08 Site↔Dispatch mapping once available."""

    @staticmethod
    def _dispatch_location(reader: Any, site_id: str) -> str | None:
        identity = require_uuid4(site_id)
        connection = _connection(reader)
        if not _table_exists(connection, "sites") or not _table_exists(
            connection,
            "site_dispatch_locations",
        ):
            raise SomaError(
                "DEPENDENCY_INDETERMINATE",
                "Infrastructure Site mapping authority is not available",
            )
        if connection.execute(
            "SELECT 1 FROM sites WHERE site_id=?",
            (identity,),
        ).fetchone() is None:
            raise SomaError("DEPENDENCY_INDETERMINATE", "Site does not exist")
        row = connection.execute(
            "SELECT dispatch_location_id FROM site_dispatch_locations WHERE site_id=?",
            (identity,),
        ).fetchone()
        if row is None:
            raise SomaError(
                "DEPENDENCY_INDETERMINATE",
                "Site lacks required dedicated Dispatch Location",
            )
        return str(row[0])

    @classmethod
    def _blockers(cls, reader: Any, site_id: str) -> tuple[DependencyBlocker, ...]:
        dispatch_id = cls._dispatch_location(reader, site_id)
        validator = InventoryReferenceDependencyValidator()
        return validator._blockers(
            reader,
            ReferenceTarget("dispatch_location", dispatch_id),
        )

    def guard_archive(self, uow: Any, site_id: str) -> str:
        try:
            return "BLOCKED" if self._blockers(uow, site_id) else "CLEAR"
        except Exception:
            return "INDETERMINATE"

    def count_blockers(self, snapshot: Any, site_id: str) -> int:
        return len(self._blockers(snapshot, site_id))

    def list_blockers(
        self,
        snapshot: Any,
        site_id: str,
        cursor: str | None,
        limit: int,
    ) -> dict[str, object]:
        if type(limit) is not int or not 1 <= limit <= 500:
            raise ValidationError("Inventory Site blocker limit must be 1..500")
        blockers = list(self._blockers(snapshot, site_id))
        start = 0
        if cursor is not None:
            if not isinstance(cursor, str):
                raise ValidationError("Inventory Site blocker cursor is invalid")
            for index, blocker in enumerate(blockers):
                if blocker.blocker_id == cursor:
                    start = index + 1
                    break
            else:
                raise ValidationError("Inventory Site blocker cursor is stale")
        selected = blockers[start : start + limit]
        return {
            "items": [
                {
                    "blocker_kind": "inventory_dispatch_dependency",
                    "blocker_id": item.blocker_id,
                    "reason_code": item.reason_code,
                }
                for item in selected
            ],
            "continuation": (
                selected[-1].blocker_id
                if start + len(selected) < len(blockers) and selected
                else None
            ),
        }


class InventoryCommunicationIdentityProvider:
    """Accepted Inventory operational identities for Communications matching."""

    @staticmethod
    def _chronology(epoch_seconds: int | None) -> dict[str, object]:
        if epoch_seconds is None:
            return {
                "known": False,
                "utc_epoch_ms": None,
                "source_kind": "UNKNOWN",
            }
        return {
            "known": True,
            "utc_epoch_ms": int(epoch_seconds) * 1000,
            "source_kind": "OTHER_PROVIDER_TIME",
        }

    @classmethod
    def snapshot_trackable_inventory(
        cls,
        reader: Any,
    ) -> tuple[dict[str, object], ...]:
        connection = _connection(reader)
        result: list[dict[str, object]] = []

        requests = connection.execute(
            "SELECT r.spare_request_id,r.tracking_id,r.created_at_utc,p.revision "
            "FROM spare_requests r JOIN spare_request_current_projection p "
            "ON p.spare_request_id=r.spare_request_id "
            "ORDER BY r.spare_request_id"
        ).fetchall()
        for row in requests:
            request_id = str(row[0])
            revision = int(row[3])
            result.append(
                {
                    "target_type": "SPARE_REQUEST",
                    "target_id": request_id,
                    "target_revision": revision,
                    "identity_kind": "SPR_LOCAL_HANDLE",
                    "normalized_value": str(row[1]).upper(),
                    "effective_from": cls._chronology(int(row[2])),
                }
            )
            aliases = connection.execute(
                "SELECT a.sr7,e.recorded_at_utc "
                "FROM spare_request_identifier_aliases a "
                "JOIN spare_request_identifier_events e "
                "ON e.identifier_event_id=a.source_identifier_event_id "
                "WHERE a.spare_request_id=? ORDER BY a.sr7",
                (request_id,),
            ).fetchall()
            for alias in aliases:
                result.append(
                    {
                        "target_type": "SPARE_REQUEST",
                        "target_id": request_id,
                        "target_revision": revision,
                        "identity_kind": "SPARE_REQUEST_SR7",
                        "normalized_value": str(alias[0]).upper(),
                        "effective_from": cls._chronology(int(alias[1])),
                    }
                )

        rmas = connection.execute(
            "SELECT r.rma_id,r.created_at_utc,p.revision "
            "FROM rmas r JOIN rma_lifecycle_projection p ON p.rma_id=r.rma_id "
            "ORDER BY r.rma_id"
        ).fetchall()
        for row in rmas:
            rma_id = str(row[0])
            revision = int(row[2])
            aliases = connection.execute(
                "SELECT a.c10,e.recorded_at_utc "
                "FROM rma_identifier_aliases a "
                "JOIN rma_identifier_events e "
                "ON e.identifier_event_id=a.source_identifier_event_id "
                "WHERE a.rma_id=? ORDER BY a.c10",
                (rma_id,),
            ).fetchall()
            for alias in aliases:
                result.append(
                    {
                        "target_type": "RMA",
                        "target_id": rma_id,
                        "target_revision": revision,
                        "identity_kind": "RMA_C10",
                        "normalized_value": str(alias[0]).upper(),
                        "effective_from": cls._chronology(int(alias[1])),
                    }
                )

        tags = connection.execute(
            "SELECT t.fault_tag_id,t.tracking_id,t.created_at_utc,p.revision "
            "FROM fault_tags t JOIN fault_tag_current_projection p "
            "ON p.fault_tag_id=t.fault_tag_id ORDER BY t.fault_tag_id"
        ).fetchall()
        for row in tags:
            result.append(
                {
                    "target_type": "FAULT_TAG",
                    "target_id": str(row[0]),
                    "target_revision": int(row[3]),
                    "identity_kind": "FAULT_TAG_TRACKING",
                    "normalized_value": str(row[1]).upper(),
                    "effective_from": cls._chronology(int(row[2])),
                }
            )

        result.sort(
            key=lambda item: (
                str(item["target_type"]),
                str(item["target_id"]),
                str(item["identity_kind"]),
                str(item["normalized_value"]),
            )
        )
        return tuple(result)

    @classmethod
    def validate_trackable_target(
        cls,
        uow: Any,
        target_type: str,
        target_id: str,
        target_revision: int,
        matched_identity: Any,
    ) -> str:
        if target_type not in {"SPARE_REQUEST", "RMA", "FAULT_TAG"}:
            return "INVALID"
        if type(target_revision) is not int or target_revision <= 0:
            return "INVALID"
        try:
            identity = require_uuid4(target_id)
            if not isinstance(matched_identity, dict):
                return "INVALID"
            candidates = cls.snapshot_trackable_inventory(uow)
        except Exception:
            return "INDETERMINATE"
        for candidate in candidates:
            if (
                candidate["target_type"] == target_type
                and candidate["target_id"] == identity
                and candidate["target_revision"] == target_revision
                and candidate["identity_kind"] == matched_identity.get("identity_kind")
                and candidate["normalized_value"]
                == matched_identity.get("normalized_value")
            ):
                return "VALID"
        return "INVALID"


class InventoryOverviewProjectionProvider:
    """Read-only LLD-07 constituent projection for the shared Overview snapshot."""

    @staticmethod
    def _scope_clause(
        alias: str,
        scope_kind: str,
        customer_id: str | None,
    ) -> tuple[str, tuple[object, ...]]:
        if scope_kind == "all":
            return "", ()
        if scope_kind == "specific":
            return (
                " AND EXISTS(SELECT 1 FROM sr_customer_relationships sc "
                f"WHERE sc.service_request_id={alias}.service_request_id "
                "AND sc.relationship_state='active' AND sc.customer_org_id=?)",
                (customer_id,),
            )
        return (
            " AND NOT EXISTS(SELECT 1 FROM sr_customer_relationships sc "
            f"WHERE sc.service_request_id={alias}.service_request_id "
            "AND sc.relationship_state='active')",
            (),
        )

    @classmethod
    def _request_scope_predicate(
        cls,
        scope_kind: str,
        customer_id: str | None,
    ) -> tuple[str, tuple[object, ...]]:
        return cls._scope_clause("r", scope_kind, customer_id)

    @classmethod
    def _rma_scope_predicate(
        cls,
        scope_kind: str,
        customer_id: str | None,
    ) -> tuple[str, tuple[object, ...]]:
        if scope_kind == "all":
            return "", ()
        comparator = (
            "EXISTS(SELECT 1 FROM sr_customer_relationships sc "
            "WHERE sc.service_request_id=rq.service_request_id "
            "AND sc.relationship_state='active' AND sc.customer_org_id=?)"
            if scope_kind == "specific"
            else
            "NOT EXISTS(SELECT 1 FROM sr_customer_relationships sc "
            "WHERE sc.service_request_id=rq.service_request_id "
            "AND sc.relationship_state='active')"
        )
        return f" AND {comparator}", (() if customer_id is None else (customer_id,))

    @classmethod
    def project_overview(
        cls,
        snapshot: Any,
        window: Any,
        customer_scope: Any,
    ) -> dict[str, object]:
        connection = _connection(snapshot)
        resolved_window = _window_values(window)
        scope_kind, customer_id = _scope_values(customer_scope)
        request_scope, request_params = cls._request_scope_predicate(
            scope_kind,
            customer_id,
        )
        rma_scope, rma_params = cls._rma_scope_predicate(
            scope_kind,
            customer_id,
        )
        need_scope, need_params = cls._scope_clause("n", scope_kind, customer_id)

        open_need_count = int(
            connection.execute(
                "SELECT COUNT(*) FROM spare_needs n "
                "JOIN spare_need_current_projection p ON p.spare_need_id=n.spare_need_id "
                "WHERE p.lifecycle_state='active'" + need_scope,
                need_params,
            ).fetchone()[0]
        )
        active_request_count = int(
            connection.execute(
                "SELECT COUNT(*) FROM spare_requests r "
                "JOIN spare_request_current_projection p "
                "ON p.spare_request_id=r.spare_request_id "
                "WHERE p.lifecycle_state NOT IN ('authorized','cancelled','rejected')"
                + request_scope,
                request_params,
            ).fetchone()[0]
        )
        open_rma_count = int(
            connection.execute(
                "SELECT COUNT(*) FROM rma_return_obligation_current o "
                "JOIN rmas rm ON rm.rma_id=o.rma_id "
                "JOIN spare_requests rq ON rq.spare_request_id=rm.spare_request_id "
                "WHERE o.obligation_state='open'" + rma_scope,
                rma_params,
            ).fetchone()[0]
        )
        fault_tag_action_count = int(
            connection.execute(
                "SELECT COUNT(DISTINCT t.fault_tag_id) FROM fault_tags t "
                "JOIN fault_tag_current_projection p ON p.fault_tag_id=t.fault_tag_id "
                "WHERE (p.awaiting_receipt_count>0 OR p.awaiting_final_count>0 "
                "OR p.rejected_count>0) "
                "AND EXISTS(SELECT 1 FROM fault_tag_memberships m "
                "JOIN rmas rm ON rm.rma_id=m.rma_id "
                "JOIN spare_requests rq ON rq.spare_request_id=rm.spare_request_id "
                "WHERE m.fault_tag_id=t.fault_tag_id"
                + (
                    ""
                    if scope_kind == "all"
                    else (
                        " AND EXISTS(SELECT 1 FROM sr_customer_relationships sc "
                        "WHERE sc.service_request_id=rq.service_request_id "
                        "AND sc.relationship_state='active' AND sc.customer_org_id=?)"
                        if scope_kind == "specific"
                        else
                        " AND NOT EXISTS(SELECT 1 FROM sr_customer_relationships sc "
                        "WHERE sc.service_request_id=rq.service_request_id "
                        "AND sc.relationship_state='active')"
                    )
                )
                + ")",
                (() if scope_kind != "specific" else (customer_id,)),
            ).fetchone()[0]
        )
        mixed_partial_present = (
            connection.execute(
                "SELECT 1 FROM spare_requests r "
                "JOIN spare_request_current_projection p "
                "ON p.spare_request_id=r.spare_request_id "
                "WHERE p.lifecycle_state='partially_authorized'"
                + request_scope
                + " LIMIT 1",
                request_params,
            ).fetchone()
            is not None
        )

        attention_rows = connection.execute(
            "SELECT a.attention_id,a.target_kind,a.target_id,a.attention_kind,"
            "a.severity,c.committed_at_utc "
            "FROM inventory_attention_projection a "
            "JOIN command_receipts c ON c.command_id=a.last_command_id "
            "ORDER BY c.committed_at_utc,a.attention_kind,a.target_kind,a.target_id"
        ).fetchall()
        scoped_attention: list[dict[str, object]] = []
        for row in attention_rows:
            target_kind = str(row[1])
            target_id = str(row[2])
            if not cls._target_in_scope(
                connection,
                target_kind,
                target_id,
                scope_kind,
                customer_id,
            ):
                continue
            severity_map = {
                "high": "critical",
                "action_required": "high",
                "warning": "medium",
                "info": "info",
            }
            attention_kind = str(row[3])
            scoped_attention.append(
                {
                    "attention_class": (
                        "action_required"
                        if str(row[4]) in {"high", "action_required"}
                        else "review_required"
                    ),
                    "owner_severity": severity_map.get(str(row[4]), "low"),
                    "domain": "inventory",
                    "condition_code": attention_kind,
                    "target_type": target_kind,
                    "target_id": target_id,
                    "label": attention_kind.replace("_", " "),
                    "reason": attention_kind,
                    "due_at_utc": None,
                    "created_at_utc": int(row[5]),
                    "navigation_target": {
                        "workspace": "inventory",
                        "target_type": target_kind,
                        "target_id": target_id,
                    },
                    "coverage": {"state": "complete", "detail_code": None},
                }
            )

        current_start = int(resolved_window["current_start_utc"])
        current_end = int(resolved_window["current_end_utc"])
        previous_start = int(resolved_window["previous_start_utc"])
        previous_end = int(resolved_window["previous_end_utc"])
        action_current = sum(
            1
            for item in scoped_attention
            if current_start <= int(item["created_at_utc"]) < current_end
        )
        action_previous = sum(
            1
            for item in scoped_attention
            if previous_start <= int(item["created_at_utc"]) < previous_end
        )

        activity = cls._recent_activity(
            connection,
            scope_kind,
            customer_id,
            current_start,
            current_end,
        )
        timeline = cls._timeline(
            connection,
            scope_kind,
            customer_id,
            current_start,
            current_end,
        )

        return {
            "card": {
                "title": "Inventory",
                "action_required_count": {
                    "current": action_current,
                    "previous": action_previous,
                },
                "open_need_count": open_need_count,
                "active_request_count": active_request_count,
                "open_rma_count": open_rma_count,
                "fault_tag_action_count": fault_tag_action_count,
                "mixed_partial_present": bool(mixed_partial_present),
            },
            "attention": tuple(scoped_attention[:100]),
            "timeline": tuple(timeline[:200]),
            "activity": tuple(activity[:100]),
            "metadata": {
                "provider_id": "inventory",
                "contract_version": 1,
                "coverage": {"state": "complete", "detail_code": None},
                "freshness": {
                    "state": "live_snapshot",
                    "source_as_of_utc": None,
                },
                "projection_revision": (
                    f"{open_need_count}:{active_request_count}:"
                    f"{open_rma_count}:{fault_tag_action_count}:"
                    f"{len(scoped_attention)}"
                ),
                "warnings": [],
            },
        }

    @classmethod
    def _target_in_scope(
        cls,
        connection: Any,
        target_kind: str,
        target_id: str,
        scope_kind: str,
        customer_id: str | None,
    ) -> bool:
        if scope_kind == "all":
            return True
        if target_kind == "spare_request":
            row = connection.execute(
                "SELECT service_request_id FROM spare_requests WHERE spare_request_id=?",
                (target_id,),
            ).fetchone()
        elif target_kind == "rma":
            row = connection.execute(
                "SELECT rq.service_request_id FROM rmas rm JOIN spare_requests rq "
                "ON rq.spare_request_id=rm.spare_request_id WHERE rm.rma_id=?",
                (target_id,),
            ).fetchone()
        elif target_kind == "fault_tag":
            rows = connection.execute(
                "SELECT DISTINCT rq.service_request_id FROM fault_tag_memberships m "
                "JOIN rmas rm ON rm.rma_id=m.rma_id "
                "JOIN spare_requests rq ON rq.spare_request_id=rm.spare_request_id "
                "WHERE m.fault_tag_id=?",
                (target_id,),
            ).fetchall()
            if not rows:
                return scope_kind == "unassigned"
            return any(
                cls._sr_in_scope(
                    connection,
                    str(item[0]),
                    scope_kind,
                    customer_id,
                )
                for item in rows
            )
        else:
            return False
        if row is None:
            return False
        return cls._sr_in_scope(
            connection,
            str(row[0]),
            scope_kind,
            customer_id,
        )

    @staticmethod
    def _sr_in_scope(
        connection: Any,
        sr_id: str,
        scope_kind: str,
        customer_id: str | None,
    ) -> bool:
        row = connection.execute(
            "SELECT customer_org_id FROM sr_customer_relationships "
            "WHERE service_request_id=? AND relationship_state='active'",
            (sr_id,),
        ).fetchone()
        if scope_kind == "specific":
            return row is not None and str(row[0]) == customer_id
        return row is None

    @classmethod
    def _recent_activity(
        cls,
        connection: Any,
        scope_kind: str,
        customer_id: str | None,
        start_utc: int,
        end_utc: int,
    ) -> list[dict[str, object]]:
        rows = connection.execute(
            "SELECT e.request_event_id,e.spare_request_id,e.event_kind,e.recorded_at_utc "
            "FROM spare_request_lifecycle_events e "
            "WHERE e.recorded_at_utc>=? AND e.recorded_at_utc<? "
            "ORDER BY e.recorded_at_utc DESC,e.request_event_id DESC LIMIT 200",
            (start_utc, end_utc),
        ).fetchall()
        items: list[dict[str, object]] = []
        for row in rows:
            if not cls._target_in_scope(
                connection,
                "spare_request",
                str(row[1]),
                scope_kind,
                customer_id,
            ):
                continue
            items.append(
                {
                    "recorded_at_utc": int(row[3]),
                    "domain": "inventory",
                    "activity_code": f"spare_request_{row[2]}",
                    "target_id": str(row[1]),
                    "label": str(row[2]).replace("_", " "),
                    "navigation_target": {
                        "workspace": "inventory",
                        "target_type": "spare_request",
                        "target_id": str(row[1]),
                    },
                }
            )
        return items

    @classmethod
    def _timeline(
        cls,
        connection: Any,
        scope_kind: str,
        customer_id: str | None,
        start_utc: int,
        end_utc: int,
    ) -> list[dict[str, object]]:
        rows = connection.execute(
            "SELECT e.logistics_event_id,e.event_kind,e.effective_at_utc,"
            "e.recorded_at_utc,p.rma_id "
            "FROM actual_logistics_events e JOIN logistics_rma_participants p "
            "ON p.logistics_event_id=e.logistics_event_id "
            "WHERE e.recorded_at_utc>=? AND e.recorded_at_utc<? "
            "ORDER BY COALESCE(e.effective_at_utc,e.recorded_at_utc),"
            "e.logistics_event_id,p.rma_id LIMIT 400",
            (start_utc, end_utc),
        ).fetchall()
        items: list[dict[str, object]] = []
        for row in rows:
            rma_id = str(row[4])
            if not cls._target_in_scope(
                connection,
                "rma",
                rma_id,
                scope_kind,
                customer_id,
            ):
                continue
            items.append(
                {
                    "kind": "inventory_milestone",
                    "effective_start_utc": None
                    if row[2] is None
                    else int(row[2]),
                    "effective_end_utc": None,
                    "chronology_known": row[2] is not None,
                    "domain": "inventory",
                    "target_type": "rma",
                    "target_id": rma_id,
                    "label": str(row[1]).replace("_", " "),
                    "state_label": str(row[1]),
                    "navigation_target": {
                        "workspace": "inventory",
                        "target_type": "rma",
                        "target_id": rma_id,
                    },
                    "objective_timezone": None,
                }
            )
        items.sort(
            key=lambda item: (
                0 if item["chronology_known"] else 1,
                int(item["effective_start_utc"])
                if item["effective_start_utc"] is not None
                else 2**63 - 1,
                str(item["target_type"]),
                str(item["target_id"]),
                str(item["state_label"]),
            )
        )
        return items

    @classmethod
    def iter_communication_targets(
        cls,
        snapshot: Any,
        window: Any,
        customer_scope: Any,
    ) -> tuple[dict[str, str], ...]:
        _window_values(window)
        scope_kind, customer_id = _scope_values(customer_scope)
        connection = _connection(snapshot)
        refs: set[tuple[str, str]] = set()

        for row in connection.execute(
            "SELECT spare_request_id FROM spare_requests ORDER BY spare_request_id"
        ).fetchall():
            identity = str(row[0])
            if cls._target_in_scope(
                connection,
                "spare_request",
                identity,
                scope_kind,
                customer_id,
            ):
                refs.add(("SPARE_REQUEST", identity))

        for row in connection.execute(
            "SELECT rma_id FROM rmas ORDER BY rma_id"
        ).fetchall():
            identity = str(row[0])
            if cls._target_in_scope(
                connection,
                "rma",
                identity,
                scope_kind,
                customer_id,
            ):
                refs.add(("RMA", identity))

        for row in connection.execute(
            "SELECT fault_tag_id FROM fault_tags ORDER BY fault_tag_id"
        ).fetchall():
            identity = str(row[0])
            if cls._target_in_scope(
                connection,
                "fault_tag",
                identity,
                scope_kind,
                customer_id,
            ):
                refs.add(("FAULT_TAG", identity))

        return tuple(
            {
                "target_type": target_type,
                "target_id": target_id,
            }
            for target_type, target_id in sorted(refs)
        )


__all__ = [
    "InventoryCommunicationIdentityProvider",
    "InventoryDevicePartReferenceReader",
    "InventoryOverviewProjectionProvider",
    "InventoryPhysicalConsequenceReader",
    "InventoryReferenceDependencyValidator",
    "InventorySiteDependencyValidator",
    "RfcInventoryDependencyProvider",
]
