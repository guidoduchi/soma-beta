from __future__ import annotations

from typing import Any

from soma.foundation.errors import IntegrityFailure, SomaError, ValidationError
from soma.foundation.identifiers import new_uuid4, require_uuid4, utc_epoch_seconds
from soma.foundation.strict_json import sha256_canonical_json


def _connection(reader: Any):
    if hasattr(reader, "execute"):
        return reader
    connection = getattr(reader, "connection", None)
    if connection is None or not hasattr(connection, "execute"):
        raise ValidationError("Inventory Task participant requires a database read context")
    return connection


class InventoryTaskDependencyProvider:
    """LLD-07 participant consumed by LLD-05 hard-delete and retry flows."""

    @staticmethod
    def classify_task_hard_delete_dependency(reader: Any, task_id: str) -> str:
        connection = _connection(reader)
        identity = require_uuid4(task_id)
        task = connection.execute(
            "SELECT 1 FROM tasks WHERE task_id=?",
            (identity,),
        ).fetchone()
        if task is None:
            return "INDETERMINATE"
        if connection.execute(
            "SELECT 1 FROM inventory_physical_consequences WHERE task_id=? LIMIT 1",
            (identity,),
        ).fetchone() is not None:
            return "BLOCKED"
        if connection.execute(
            "SELECT 1 FROM task_unit_allocation_events WHERE task_id=? LIMIT 1",
            (identity,),
        ).fetchone() is not None:
            return "BLOCKED"
        if connection.execute(
            "SELECT 1 FROM task_unit_allocation_current WHERE task_id=? LIMIT 1",
            (identity,),
        ).fetchone() is not None:
            return "BLOCKED"
        if connection.execute(
            "SELECT 1 FROM local_need_fulfillment_events WHERE task_id=? LIMIT 1",
            (identity,),
        ).fetchone() is not None:
            return "BLOCKED"
        return "CLEAR"

    @staticmethod
    def preview_retry_relationship_clone(
        snapshot: Any,
        predecessor_task_id: str,
        selected_inventory_relationship_ids: tuple[str, ...],
    ) -> dict[str, object]:
        connection = _connection(snapshot)
        predecessor = require_uuid4(predecessor_task_id)
        if (
            not isinstance(selected_inventory_relationship_ids, tuple)
            or len(selected_inventory_relationship_ids) > 2000
        ):
            raise ValidationError(
                "selected_inventory_relationship_ids must be a tuple of at most 2000 allocation UUIDs"
            )
        selected = tuple(
            sorted(
                (require_uuid4(value) for value in selected_inventory_relationship_ids),
                key=lambda value: value.encode("utf-8"),
            )
        )
        if len(set(selected)) != len(selected):
            raise ValidationError("retry Inventory selection contains duplicate allocations")
        if connection.execute(
            "SELECT 1 FROM tasks WHERE task_id=?",
            (predecessor,),
        ).fetchone() is None:
            return {
                "status": "INDETERMINATE",
                "predecessor_task_id": predecessor,
                "relationships": [],
                "fingerprint": sha256_canonical_json(
                    {
                        "schema": "SOMA_INVENTORY_RETRY_CLONE_PREVIEW_V1",
                        "predecessor_task_id": predecessor,
                        "status": "INDETERMINATE",
                        "relationships": [],
                    }
                ),
            }
        if connection.execute(
            "SELECT 1 FROM inventory_physical_consequences WHERE task_id=? LIMIT 1",
            (predecessor,),
        ).fetchone() is not None:
            status = "BLOCKED"
            relationships: list[dict[str, object]] = []
        else:
            status = "READY"
            relationships = []
            for allocation_id in selected:
                row = connection.execute(
                    "SELECT c.task_id,c.spare_part_unit_id,c.spare_need_id,c.revision,"
                    "c.last_event_id,p.disposition_token,p.active_task_allocation_id "
                    "FROM task_unit_allocation_current c "
                    "JOIN spare_part_current_projection p "
                    "ON p.spare_part_unit_id=c.spare_part_unit_id "
                    "WHERE c.allocation_id=?",
                    (allocation_id,),
                ).fetchone()
                if row is None:
                    status = "INDETERMINATE"
                    relationships.append(
                        {
                            "allocation_id": allocation_id,
                            "classification": "missing",
                        }
                    )
                    continue
                if (
                    str(row[0]) != predecessor
                    or str(row[5]) != "reserved"
                    or row[6] is None
                    or str(row[6]) != allocation_id
                ):
                    status = "BLOCKED"
                    relationships.append(
                        {
                            "allocation_id": allocation_id,
                            "classification": "incompatible",
                        }
                    )
                    continue
                relationships.append(
                    {
                        "allocation_id": allocation_id,
                        "classification": "eligible",
                        "allocation_revision": int(row[3]),
                        "spare_part_unit_id": str(row[1]),
                        "spare_need_id": None if row[2] is None else str(row[2]),
                        "last_event_id": str(row[4]),
                    }
                )
        material = {
            "schema": "SOMA_INVENTORY_RETRY_CLONE_PREVIEW_V1",
            "predecessor_task_id": predecessor,
            "status": status,
            "relationships": relationships,
        }
        return {
            "status": status,
            "predecessor_task_id": predecessor,
            "relationships": relationships,
            "fingerprint": sha256_canonical_json(material),
        }

    @staticmethod
    def apply_retry_relationship_clone(
        uow: Any,
        preview: dict[str, object],
        new_task_id: str,
        command_context: dict[str, object],
    ) -> tuple[dict[str, str], ...]:
        connection = _connection(uow)
        successor = require_uuid4(new_task_id)
        if not isinstance(preview, dict) or preview.get("status") != "READY":
            raise SomaError(
                "DEPENDENCY_INDETERMINATE",
                "Inventory retry clone preview is not READY",
            )
        predecessor = require_uuid4(str(preview.get("predecessor_task_id")))
        relationships = preview.get("relationships")
        fingerprint = preview.get("fingerprint")
        if (
            not isinstance(relationships, list)
            or not isinstance(fingerprint, str)
            or len(fingerprint) != 64
        ):
            raise SomaError(
                "DEPENDENCY_INDETERMINATE",
                "Inventory retry clone preview shape is invalid",
            )
        if (
            not isinstance(command_context, dict)
            or set(command_context) != {"command_id", "actor_kind", "actor_id"}
        ):
            raise ValidationError("Inventory retry command context shape is invalid")
        command_id = require_uuid4(str(command_context["command_id"]))
        actor_kind = command_context["actor_kind"]
        actor_id = command_context["actor_id"]
        if not isinstance(actor_kind, str) or not actor_kind:
            raise ValidationError("Inventory retry actor_kind is invalid")
        if actor_id is not None and not isinstance(actor_id, str):
            raise ValidationError("Inventory retry actor_id is invalid")

        if connection.execute(
            "SELECT 1 FROM command_receipts WHERE command_id=?",
            (command_id,),
        ).fetchone() is None:
            raise IntegrityFailure(
                "Inventory retry participant requires caller-owned outer command receipt"
            )
        if connection.execute(
            "SELECT 1 FROM tasks WHERE task_id=?",
            (successor,),
        ).fetchone() is None:
            raise SomaError("TASK_STALE", "Retry successor Task no longer exists")

        selected = tuple(
            str(item["allocation_id"])
            for item in relationships
            if isinstance(item, dict) and item.get("classification") == "eligible"
        )
        current_preview = InventoryTaskDependencyProvider.preview_retry_relationship_clone(
            uow,
            predecessor,
            selected,
        )
        if (
            current_preview["status"] != "READY"
            or current_preview["fingerprint"] != fingerprint
        ):
            raise SomaError("INV_STALE", "Inventory retry clone authority changed")

        now = utc_epoch_seconds()
        refs: list[dict[str, str]] = []
        for item in current_preview["relationships"]:
            allocation_id = str(item["allocation_id"])
            prior_revision = int(item["allocation_revision"])
            event_id = new_uuid4()
            connection.execute(
                "INSERT INTO task_unit_allocation_events("
                "allocation_event_id,allocation_id,task_id,spare_part_unit_id,spare_need_id,"
                "event_kind,prior_task_id,reason_code,effective_at_utc,target_event_id,"
                "recorded_at_utc,command_id"
                ") VALUES (?,?,?,?,?,'reassign',?,'task_retry_clone',NULL,?,?,?)",
                (
                    event_id,
                    allocation_id,
                    successor,
                    str(item["spare_part_unit_id"]),
                    item["spare_need_id"],
                    predecessor,
                    str(item["last_event_id"]),
                    now,
                    command_id,
                ),
            )
            changed = connection.execute(
                "UPDATE task_unit_allocation_current SET task_id=?,revision=?,"
                "last_event_id=?,last_command_id=? WHERE allocation_id=? "
                "AND task_id=? AND revision=?",
                (
                    successor,
                    prior_revision + 1,
                    event_id,
                    command_id,
                    allocation_id,
                    predecessor,
                    prior_revision,
                ),
            )
            if changed.rowcount != 1:
                raise SomaError("INV_STALE", "Inventory retry allocation changed")
            refs.extend(
                (
                    {"type": "task_unit_allocation", "id": allocation_id},
                    {"type": "task_unit_allocation_event", "id": event_id},
                )
            )
        return tuple(refs)


__all__ = ["InventoryTaskDependencyProvider"]
