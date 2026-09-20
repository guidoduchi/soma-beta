from __future__ import annotations

from typing import Any

from soma.foundation.errors import ValidationError
from soma.foundation.identifiers import require_uuid4
from soma.foundation.persistence.connections import ConnectionFactory
from soma.foundation.persistence.uow import ReadSnapshot
from soma.foundation.strict_json import sha256_canonical_json

_HARD_DELETE_KINDS = frozenset(
    {"spare_need", "spare_request", "spare_part_unit", "fault_tag"}
)


class InventoryDestructivePreviewQuery:
    def __init__(self, connection_factory: ConnectionFactory) -> None:
        self._factory = connection_factory

    @staticmethod
    def _count(connection: Any, sql: str, params: tuple[object, ...]) -> int:
        row = connection.execute(sql, params).fetchone()
        return 0 if row is None else int(row[0])

    @classmethod
    def classify_hard_delete(
        cls,
        connection: Any,
        *,
        target_kind: str,
        target_id: str,
    ) -> dict[str, object]:
        if target_kind not in _HARD_DELETE_KINDS:
            raise ValidationError("unsupported Inventory hard-delete target kind")
        identity = require_uuid4(target_id)
        blockers: list[str] = []
        removable_rows: list[str] = []
        retained_related_ids: list[str] = []
        revision: int | None = None

        if target_kind == "spare_need":
            row = connection.execute(
                "SELECT n.creation_origin,n.service_request_id,p.lifecycle_state,"
                "p.contributor_count,p.revision FROM spare_needs n "
                "JOIN spare_need_current_projection p ON p.spare_need_id=n.spare_need_id "
                "WHERE n.spare_need_id=?",
                (identity,),
            ).fetchone()
            if row is None:
                blockers.append("missing_target")
            else:
                revision = int(row[4])
                retained_related_ids.append(str(row[1]))
                if str(row[0]) != "manual":
                    blockers.append("non_manual_origin")
                if str(row[2]) != "active":
                    blockers.append("lifecycle_history")
                if int(row[3]) != 0:
                    blockers.append("contributors")
                checks = (
                    ("contributors", "SELECT COUNT(*) FROM spare_need_contributors WHERE spare_need_id=?"),
                    ("request_allocations", "SELECT COUNT(*) FROM spare_request_need_allocations WHERE spare_need_id=?"),
                    ("local_fulfillment", "SELECT COUNT(*) FROM local_need_fulfillment_events WHERE spare_need_id=?"),
                    ("task_allocation_history", "SELECT COUNT(*) FROM task_unit_allocation_events WHERE spare_need_id=?"),
                )
                for label, sql in checks:
                    if cls._count(connection, sql, (identity,)):
                        blockers.append(label)
                event_count = cls._count(
                    connection,
                    "SELECT COUNT(*) FROM spare_need_lifecycle_events WHERE spare_need_id=?",
                    (identity,),
                )
                if event_count != 1:
                    blockers.append("protected_lifecycle_history")
                removable_rows = [
                    "inventory_attention_projection",
                    "spare_need_active_keys",
                    "spare_need_current_projection",
                    "spare_need_lifecycle_events",
                    "spare_needs",
                ]

        elif target_kind == "spare_request":
            row = connection.execute(
                "SELECT r.creation_origin,r.service_request_id,p.lifecycle_state,"
                "p.current_sr7,p.current_submission_snapshot_id,p.revision "
                "FROM spare_requests r JOIN spare_request_current_projection p "
                "ON p.spare_request_id=r.spare_request_id WHERE r.spare_request_id=?",
                (identity,),
            ).fetchone()
            if row is None:
                blockers.append("missing_target")
            else:
                revision = int(row[5])
                retained_related_ids.append(str(row[1]))
                if str(row[0]) != "soma_draft":
                    blockers.append("non_draft_origin")
                if str(row[2]) != "draft":
                    blockers.append("lifecycle_history")
                if row[3] is not None:
                    blockers.append("official_identifier_history")
                if row[4] is not None:
                    blockers.append("submission_history")
                checks = (
                    ("submission_history", "SELECT COUNT(*) FROM spare_request_submission_snapshots WHERE spare_request_id=?"),
                    ("identifier_history", "SELECT COUNT(*) FROM spare_request_identifier_events WHERE spare_request_id=?"),
                    ("rma_history", "SELECT COUNT(*) FROM rmas WHERE spare_request_id=?"),
                )
                for label, sql in checks:
                    if cls._count(connection, sql, (identity,)):
                        blockers.append(label)
                event_count = cls._count(
                    connection,
                    "SELECT COUNT(*) FROM spare_request_lifecycle_events WHERE spare_request_id=?",
                    (identity,),
                )
                if event_count != 1:
                    blockers.append("protected_lifecycle_history")
                retained_related_ids.extend(
                    str(r[0])
                    for r in connection.execute(
                        "SELECT spare_need_id FROM spare_request_need_allocations "
                        "WHERE spare_request_id=? ORDER BY spare_need_id",
                        (identity,),
                    ).fetchall()
                )
                removable_rows = [
                    "inventory_attention_projection",
                    "spare_request_draft_logistics",
                    "spare_request_need_allocations",
                    "spare_request_current_projection",
                    "spare_request_lifecycle_events",
                    "spare_requests",
                ]

        elif target_kind == "spare_part_unit":
            row = connection.execute(
                "SELECT u.creation_origin,u.origin_rma_id,u.parent_spare_part_unit_id,"
                "p.revision FROM spare_part_units u JOIN spare_part_current_projection p "
                "ON p.spare_part_unit_id=u.spare_part_unit_id WHERE u.spare_part_unit_id=?",
                (identity,),
            ).fetchone()
            if row is None:
                blockers.append("missing_target")
            else:
                revision = int(row[3])
                if str(row[0]) != "manual_local":
                    blockers.append("non_manual_origin")
                if row[1] is not None or row[2] is not None:
                    blockers.append("protected_provenance")
                checks = (
                    ("child_units", "SELECT COUNT(*) FROM spare_part_units WHERE parent_spare_part_unit_id=?"),
                    ("task_allocation_history", "SELECT COUNT(*) FROM task_unit_allocation_events WHERE spare_part_unit_id=?"),
                    ("local_fulfillment", "SELECT COUNT(*) FROM local_need_fulfillment_events WHERE spare_part_unit_id=?"),
                    ("direct_rma_receipt", "SELECT COUNT(*) FROM rma_direct_inbound_units WHERE spare_part_unit_id=?"),
                    ("logistics_history", "SELECT COUNT(*) FROM logistics_spare_unit_participants WHERE spare_part_unit_id=?"),
                    ("return_obligation", "SELECT COUNT(*) FROM rma_return_obligation_current WHERE spare_part_unit_id=?"),
                    ("fault_tag_membership", "SELECT COUNT(*) FROM fault_tag_memberships WHERE spare_part_unit_id=?"),
                    ("installed_consequence", "SELECT COUNT(*) FROM physical_consequence_current WHERE installed_spare_part_unit_id=? OR inbound_spare_part_unit_id=? OR parent_dismantled_unit_id=?"),
                )
                for label, sql in checks:
                    params = (identity, identity, identity) if label == "installed_consequence" else (identity,)
                    if cls._count(connection, sql, params):
                        blockers.append(label)
                event_count = cls._count(
                    connection,
                    "SELECT COUNT(*) FROM spare_part_lifecycle_events WHERE spare_part_unit_id=?",
                    (identity,),
                )
                if event_count != 1:
                    blockers.append("protected_lifecycle_history")
                removable_rows = [
                    "inventory_attention_projection",
                    "spare_part_current_projection",
                    "spare_part_lifecycle_events",
                    "spare_part_units",
                ]

        else:
            row = connection.execute(
                "SELECT t.creation_origin,p.state,p.revision,p.current_submission_snapshot_id "
                "FROM fault_tags t JOIN fault_tag_current_projection p "
                "ON p.fault_tag_id=t.fault_tag_id WHERE t.fault_tag_id=?",
                (identity,),
            ).fetchone()
            if row is None:
                blockers.append("missing_target")
            else:
                revision = int(row[2])
                if str(row[0]) != "manual" or str(row[1]) != "draft":
                    blockers.append("non_draft_or_lifecycle_history")
                if row[3] is not None:
                    blockers.append("submission_history")
                checks = (
                    ("submission_history", "SELECT COUNT(*) FROM fault_tag_submission_snapshots WHERE fault_tag_id=?"),
                    ("membership_history", "SELECT COUNT(*) FROM fault_tag_membership_events e JOIN fault_tag_memberships m ON m.fault_tag_membership_id=e.fault_tag_membership_id WHERE m.fault_tag_id=?"),
                    ("lineage_history", "SELECT COUNT(*) FROM fault_tag_lineage WHERE predecessor_fault_tag_id=? OR successor_fault_tag_id=?"),
                )
                for label, sql in checks:
                    params = (identity, identity) if label == "lineage_history" else (identity,)
                    if cls._count(connection, sql, params):
                        blockers.append(label)
                event_count = cls._count(
                    connection,
                    "SELECT COUNT(*) FROM fault_tag_lifecycle_events WHERE fault_tag_id=?",
                    (identity,),
                )
                if event_count != 1:
                    blockers.append("protected_lifecycle_history")
                retained_related_ids.extend(
                    str(r[0])
                    for r in connection.execute(
                        "SELECT rma_id FROM fault_tag_memberships WHERE fault_tag_id=? "
                        "ORDER BY rma_id",
                        (identity,),
                    ).fetchall()
                )
                removable_rows = [
                    "inventory_attention_projection",
                    "fault_tag_membership_current",
                    "fault_tag_memberships",
                    "fault_tag_current_projection",
                    "fault_tag_lifecycle_events",
                    "fault_tags",
                ]

        proposal_column = {
            "spare_request": "spare_request_id",
            "spare_part_unit": "spare_part_unit_id",
            "fault_tag": "fault_tag_id",
        }.get(target_kind)
        if proposal_column is not None and cls._count(
            connection,
            f"SELECT COUNT(*) FROM inventory_proposal_targets WHERE {proposal_column}=?",
            (identity,),
        ):
            blockers.append("proposal_history")

        normalized_blockers = sorted(set(blockers))
        retained = sorted(set(retained_related_ids))
        classification = "CLEAR" if not normalized_blockers else "BLOCKED"
        value = {
            "target_kind": target_kind,
            "target_id": identity,
            "classification": classification,
            "reviewed_revision": revision,
            "removable_rows": removable_rows if classification == "CLEAR" else [],
            "retained_related_ids": retained,
            "blockers": normalized_blockers,
        }
        return {
            **value,
            "input_fingerprint": sha256_canonical_json(
                {"schema": "SOMA_INVENTORY_HARD_DELETE_PREVIEW_V1", **value}
            ),
        }

    def preview_hard_delete(
        self,
        *,
        target_kind: str,
        target_id: str,
    ) -> dict[str, object]:
        with ReadSnapshot(self._factory) as snapshot:
            return self.classify_hard_delete(
                snapshot.connection,
                target_kind=target_kind,
                target_id=target_id,
            )


__all__ = ["InventoryDestructivePreviewQuery"]
