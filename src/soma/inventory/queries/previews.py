from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from soma.foundation.errors import ValidationError
from soma.foundation.identifiers import require_uuid4
from soma.foundation.persistence.connections import ConnectionFactory
from soma.foundation.persistence.uow import ReadSnapshot
from soma.foundation.strict_json import sha256_canonical_json

from ..domain.needs import validate_reason_code
from ..repositories.fault_tags import InventoryFaultTagsRepository


@dataclass(frozen=True, slots=True)
class InventoryBulkPreviewTarget:
    fault_tag_membership_id: str
    expected_revision: int | None

    def validate(self) -> "InventoryBulkPreviewTarget":
        identity = require_uuid4(self.fault_tag_membership_id)
        revision = self.expected_revision
        if revision is not None and (type(revision) is not int or revision <= 0):
            raise ValidationError("bulk expected_revision must be positive or null")
        return InventoryBulkPreviewTarget(identity, revision)


class InventoryPreviewsQueryService:
    def __init__(self, connection_factory: ConnectionFactory) -> None:
        self._factory = connection_factory

    @staticmethod
    def _bulk_preview(
        connection: Any,
        *,
        action_kind: str,
        targets: tuple[InventoryBulkPreviewTarget, ...],
        effective_at_utc: int | None,
        reason_code: str | None,
        explicit_confirmation: bool,
    ) -> dict[str, object]:
        if action_kind not in {"warehouse_receipt", "warehouse_accept", "warehouse_reject"}:
            raise ValidationError("Inventory bulk action kind is invalid")
        if not isinstance(targets, tuple) or not targets or len(targets) > 2000:
            raise ValidationError("Inventory bulk preview requires 1..2000 targets")
        accepted = tuple(target.validate() for target in targets)
        ids = [target.fault_tag_membership_id for target in accepted]
        if len(set(ids)) != len(ids):
            raise ValidationError("Inventory bulk preview contains duplicate targets")
        if effective_at_utc is not None and (
            type(effective_at_utc) is not int or effective_at_utc < 0
        ):
            raise ValidationError("effective_at_utc must be nonnegative or null")
        if type(explicit_confirmation) is not bool:
            raise ValidationError("explicit_confirmation must be boolean")
        if action_kind == "warehouse_reject":
            if reason_code is None:
                raise ValidationError("warehouse_reject bulk preview requires reason_code")
            reason = validate_reason_code(reason_code)
        else:
            if reason_code is not None:
                raise ValidationError("reason_code is accepted only for warehouse_reject")
            reason = None

        expected_state = (
            "submitted_awaiting_receipt"
            if action_kind == "warehouse_receipt"
            else "warehouse_received"
        )
        partitions: list[dict[str, object]] = []
        for target in sorted(
            accepted,
            key=lambda item: item.fault_tag_membership_id.encode("utf-8"),
        ):
            identity = target.fault_tag_membership_id
            expected_revision = target.expected_revision
            if expected_revision is None:
                partitions.append(
                    {
                        "fault_tag_membership_id": identity,
                        "expected_revision": None,
                        "classification": "missing_input",
                        "reason": "expected_revision_required",
                        "observed_revision": None,
                        "observed_state": None,
                        "rma_id": None,
                    }
                )
                continue
            member = InventoryFaultTagsRepository.current_membership(connection, identity)
            if member is None:
                partitions.append(
                    {
                        "fault_tag_membership_id": identity,
                        "expected_revision": expected_revision,
                        "classification": "stale",
                        "reason": "membership_missing",
                        "observed_revision": None,
                        "observed_state": None,
                        "rma_id": None,
                    }
                )
                continue
            observed_revision = int(member[9])
            observed_state = str(member[7])
            rma_id = str(member[2])
            if observed_revision != expected_revision:
                classification = "stale"
                reason_text = "revision_changed"
            elif observed_state != expected_state or not bool(member[8]):
                classification = "incompatible"
                reason_text = f"requires_{expected_state}"
            else:
                obligation = connection.execute(
                    "SELECT obligation_state,device_part_unit_id,spare_part_unit_id,"
                    "physical_consequence_id FROM rma_return_obligation_current WHERE rma_id=?",
                    (rma_id,),
                ).fetchone()
                if obligation is None or str(obligation[0]) != "open":
                    classification = "incompatible"
                    reason_text = "return_obligation_not_open"
                elif (
                    (None if obligation[1] is None else str(obligation[1]))
                    != (None if member[4] is None else str(member[4]))
                    or (None if obligation[2] is None else str(obligation[2]))
                    != (None if member[5] is None else str(member[5]))
                    or obligation[3] is None
                    or str(obligation[3]) != str(member[3])
                ):
                    classification = "incompatible"
                    reason_text = "return_obligation_relationship_changed"
                elif action_kind in {"warehouse_accept", "warehouse_reject"} and not explicit_confirmation:
                    classification = "individual_review"
                    reason_text = "explicit_confirmation_required"
                else:
                    classification = "eligible"
                    reason_text = None
            partitions.append(
                {
                    "fault_tag_membership_id": identity,
                    "expected_revision": expected_revision,
                    "classification": classification,
                    "reason": reason_text,
                    "observed_revision": observed_revision,
                    "observed_state": observed_state,
                    "rma_id": rma_id,
                }
            )

        eligible = [
            {
                "fault_tag_membership_id": str(item["fault_tag_membership_id"]),
                "expected_revision": int(item["expected_revision"]),
            }
            for item in partitions
            if item["classification"] == "eligible"
        ]
        material = {
            "schema": "SOMA_INVENTORY_BULK_PREVIEW_V1",
            "action_kind": action_kind,
            "context": {
                "effective_at_utc": effective_at_utc,
                "reason_code": reason,
                "explicit_confirmation": explicit_confirmation,
            },
            "partitions": partitions,
        }
        return {
            "action_kind": action_kind,
            "partitions": partitions,
            "eligible_targets": eligible,
            "eligible_count": len(eligible),
            "selected_count": len(partitions),
            "input_fingerprint": sha256_canonical_json(material),
            "material_dependency_summary": {
                "expected_state": expected_state,
                "all_selected_eligible": len(eligible) == len(partitions),
                "explicit_confirmation": explicit_confirmation,
            },
        }

    def preview_bulk_action(
        self,
        *,
        action_kind: str,
        targets: tuple[InventoryBulkPreviewTarget, ...],
        effective_at_utc: int | None = None,
        reason_code: str | None = None,
        explicit_confirmation: bool = False,
    ) -> dict[str, object]:
        with ReadSnapshot(self._factory) as snapshot:
            return self._bulk_preview(
                snapshot.connection,
                action_kind=action_kind,
                targets=targets,
                effective_at_utc=effective_at_utc,
                reason_code=reason_code,
                explicit_confirmation=explicit_confirmation,
            )

    @staticmethod
    def _hard_delete_missing(
        *,
        target_kind: str,
        target_id: str,
    ) -> dict[str, object]:
        material = {
            "schema": "SOMA_INVENTORY_HARD_DELETE_PREVIEW_V1",
            "target_kind": target_kind,
            "target_id": target_id,
            "classification": "INDETERMINATE",
            "reasons": ["target_missing"],
        }
        return {
            "target_kind": target_kind,
            "target_id": target_id,
            "classification": "INDETERMINATE",
            "reasons": ["target_missing"],
            "reviewed_revision": None,
            "removable_rows": [],
            "retained_related_ids": [],
            "eligibility_fingerprint": sha256_canonical_json(material),
        }

    @staticmethod
    def _hard_delete_result(
        *,
        target_kind: str,
        target_id: str,
        reviewed_revision: int,
        reasons: list[str],
        removable_rows: list[dict[str, object]],
        retained_related_ids: list[str],
        material: dict[str, object],
    ) -> dict[str, object]:
        classification = "CLEAR" if not reasons else "BLOCKED"
        material = dict(material) | {
            "schema": "SOMA_INVENTORY_HARD_DELETE_PREVIEW_V1",
            "target_kind": target_kind,
            "target_id": target_id,
            "classification": classification,
            "reasons": list(reasons),
            "reviewed_revision": reviewed_revision,
            "retained_related_ids": list(retained_related_ids),
        }
        return {
            "target_kind": target_kind,
            "target_id": target_id,
            "classification": classification,
            "reasons": list(reasons),
            "reviewed_revision": reviewed_revision,
            "removable_rows": removable_rows if classification == "CLEAR" else [],
            "retained_related_ids": list(retained_related_ids),
            "eligibility_fingerprint": sha256_canonical_json(material),
        }

    @classmethod
    def _hard_delete_spare_need_preview(
        cls,
        connection: Any,
        spare_need_id: str,
    ) -> dict[str, object]:
        identity = require_uuid4(spare_need_id)
        row = connection.execute(
            "SELECT n.service_request_id,n.creation_origin,p.lifecycle_state,"
            "p.planned_quantity,p.contributor_count,p.revision,p.input_fingerprint "
            "FROM spare_needs n JOIN spare_need_current_projection p "
            "ON p.spare_need_id=n.spare_need_id WHERE n.spare_need_id=?",
            (identity,),
        ).fetchone()
        if row is None:
            return cls._hard_delete_missing(
                target_kind="spare_need",
                target_id=identity,
            )
        reasons: list[str] = []
        if str(row[1]) != "manual":
            reasons.append("creation_origin_not_manual")
        if str(row[2]) != "active" or int(row[5]) != 1:
            reasons.append("need_not_creation_only")
        if int(row[4]) != 0:
            reasons.append("contributors_present")
        lifecycle = connection.execute(
            "SELECT need_event_id,event_kind FROM spare_need_lifecycle_events "
            "WHERE spare_need_id=? ORDER BY recorded_at_utc,need_event_id",
            (identity,),
        ).fetchall()
        if len(lifecycle) != 1 or str(lifecycle[0][1]) != "created":
            reasons.append("need_lifecycle_history")
        dependencies = {
            "contributors": int(connection.execute(
                "SELECT COUNT(*) FROM spare_need_contributors WHERE spare_need_id=?",
                (identity,),
            ).fetchone()[0]),
            "request_allocations": int(connection.execute(
                "SELECT COUNT(*) FROM spare_request_need_allocations WHERE spare_need_id=?",
                (identity,),
            ).fetchone()[0]),
            "task_allocations": int(connection.execute(
                "SELECT COUNT(*) FROM task_unit_allocation_events WHERE spare_need_id=?",
                (identity,),
            ).fetchone()[0]),
            "local_fulfillment": int(connection.execute(
                "SELECT COUNT(*) FROM local_need_fulfillment_events WHERE spare_need_id=?",
                (identity,),
            ).fetchone()[0]),
        }
        for key, count in dependencies.items():
            if count:
                reasons.append(f"{key}_history")
        retained = [str(row[0])]
        removable = [
            {"table": "spare_need_active_keys", "ids": [identity]},
            {"table": "spare_need_current_projection", "ids": [identity]},
            {
                "table": "spare_need_lifecycle_events",
                "ids": [str(item[0]) for item in lifecycle],
            },
            {"table": "spare_needs", "ids": [identity]},
        ]
        return cls._hard_delete_result(
            target_kind="spare_need",
            target_id=identity,
            reviewed_revision=int(row[5]),
            reasons=reasons,
            removable_rows=removable,
            retained_related_ids=retained,
            material={
                "creation_origin": str(row[1]),
                "state": str(row[2]),
                "planned_quantity": int(row[3]),
                "projection_fingerprint": str(row[6]),
                "lifecycle_event_ids": [str(item[0]) for item in lifecycle],
                "dependencies": dependencies,
            },
        )

    @classmethod
    def _hard_delete_spare_request_preview(
        cls,
        connection: Any,
        spare_request_id: str,
    ) -> dict[str, object]:
        identity = require_uuid4(spare_request_id)
        row = connection.execute(
            "SELECT r.service_request_id,r.requester_contact_id,r.creation_origin,"
            "p.lifecycle_state,p.current_sr7,p.current_submission_snapshot_id,"
            "p.submitted_quantity,p.authorized_rma_count,p.revision,p.input_fingerprint "
            "FROM spare_requests r JOIN spare_request_current_projection p "
            "ON p.spare_request_id=r.spare_request_id WHERE r.spare_request_id=?",
            (identity,),
        ).fetchone()
        if row is None:
            return cls._hard_delete_missing(
                target_kind="spare_request",
                target_id=identity,
            )
        reasons: list[str] = []
        if str(row[2]) != "soma_draft":
            reasons.append("creation_origin_not_soma_draft")
        if (
            str(row[3]) != "draft"
            or row[4] is not None
            or row[5] is not None
            or int(row[6]) != 0
            or int(row[7]) != 0
            or int(row[8]) != 1
        ):
            reasons.append("request_not_creation_only_draft")
        lifecycle = connection.execute(
            "SELECT request_event_id,event_kind FROM spare_request_lifecycle_events "
            "WHERE spare_request_id=? ORDER BY recorded_at_utc,request_event_id",
            (identity,),
        ).fetchall()
        if len(lifecycle) != 1 or str(lifecycle[0][1]) != "created":
            reasons.append("request_lifecycle_history")
        dependencies = {
            "identifier_events": int(connection.execute(
                "SELECT COUNT(*) FROM spare_request_identifier_events WHERE spare_request_id=?",
                (identity,),
            ).fetchone()[0]),
            "identifier_aliases": int(connection.execute(
                "SELECT COUNT(*) FROM spare_request_identifier_aliases WHERE spare_request_id=?",
                (identity,),
            ).fetchone()[0]),
            "submission_snapshots": int(connection.execute(
                "SELECT COUNT(*) FROM spare_request_submission_snapshots WHERE spare_request_id=?",
                (identity,),
            ).fetchone()[0]),
            "rma_batches": int(connection.execute(
                "SELECT COUNT(*) FROM rma_authorization_batches WHERE spare_request_id=?",
                (identity,),
            ).fetchone()[0]),
            "rmas": int(connection.execute(
                "SELECT COUNT(*) FROM rmas WHERE spare_request_id=?",
                (identity,),
            ).fetchone()[0]),
            "proposals": int(connection.execute(
                "SELECT COUNT(*) FROM inventory_proposal_targets WHERE spare_request_id=?",
                (identity,),
            ).fetchone()[0]),
        }
        for key, count in dependencies.items():
            if count:
                reasons.append(f"{key}_history")
        allocation_rows = connection.execute(
            "SELECT request_need_allocation_id,spare_need_id,revision,active_draft "
            "FROM spare_request_need_allocations WHERE spare_request_id=? "
            "ORDER BY request_need_allocation_id",
            (identity,),
        ).fetchall()
        logistics = connection.execute(
            "SELECT revision,receiver_contact_id,dispatch_location_id "
            "FROM spare_request_draft_logistics WHERE spare_request_id=?",
            (identity,),
        ).fetchone()
        if any(int(item[2]) != 1 or int(item[3]) != 1 for item in allocation_rows):
            reasons.append("draft_allocation_history")
        if logistics is None or int(logistics[0]) != 1:
            reasons.append("draft_logistics_history")
        retained = sorted(
            {
                str(row[0]),
                str(row[1]),
                *[str(item[1]) for item in allocation_rows],
                *(
                    []
                    if logistics is None
                    else [str(logistics[1]), str(logistics[2])]
                ),
            }
        )
        allocation_ids = [str(item[0]) for item in allocation_rows]
        removable = [
            {
                "table": "spare_request_need_allocations",
                "ids": allocation_ids,
            },
            {"table": "spare_request_draft_logistics", "ids": [identity]},
            {"table": "spare_request_current_projection", "ids": [identity]},
            {
                "table": "spare_request_lifecycle_events",
                "ids": [str(item[0]) for item in lifecycle],
            },
            {"table": "spare_requests", "ids": [identity]},
        ]
        return cls._hard_delete_result(
            target_kind="spare_request",
            target_id=identity,
            reviewed_revision=int(row[8]),
            reasons=reasons,
            removable_rows=removable,
            retained_related_ids=retained,
            material={
                "creation_origin": str(row[2]),
                "state": str(row[3]),
                "projection_fingerprint": str(row[9]),
                "lifecycle_event_ids": [str(item[0]) for item in lifecycle],
                "allocation_rows": [
                    {
                        "id": str(item[0]),
                        "need_id": str(item[1]),
                        "revision": int(item[2]),
                        "active_draft": bool(item[3]),
                    }
                    for item in allocation_rows
                ],
                "draft_logistics_revision": (
                    None if logistics is None else int(logistics[0])
                ),
                "dependencies": dependencies,
            },
        )

    @classmethod
    def _hard_delete_spare_part_unit_preview(
        cls,
        connection: Any,
        spare_part_unit_id: str,
    ) -> dict[str, object]:
        identity = require_uuid4(spare_part_unit_id)
        row = connection.execute(
            "SELECT u.local_tracking_id,u.creation_origin,u.origin_rma_id,"
            "u.parent_spare_part_unit_id,p.condition_token,p.disposition_token,"
            "p.active_task_allocation_id,p.revision,p.input_fingerprint "
            "FROM spare_part_units u JOIN spare_part_current_projection p "
            "ON p.spare_part_unit_id=u.spare_part_unit_id WHERE u.spare_part_unit_id=?",
            (identity,),
        ).fetchone()
        if row is None:
            return cls._hard_delete_missing(
                target_kind="spare_part_unit",
                target_id=identity,
            )
        reasons: list[str] = []
        if str(row[1]) != "manual_local" or row[2] is not None or row[3] is not None:
            reasons.append("unit_not_manual_local_root")
        if int(row[7]) != 1 or row[6] is not None:
            reasons.append("unit_not_creation_only")
        lifecycle = connection.execute(
            "SELECT unit_event_id,event_kind FROM spare_part_lifecycle_events "
            "WHERE spare_part_unit_id=? ORDER BY recorded_at_utc,unit_event_id",
            (identity,),
        ).fetchall()
        if len(lifecycle) != 1 or str(lifecycle[0][1]) != "registered":
            reasons.append("unit_lifecycle_history")
        dependency_sql = {
            "direct_rma": (
                "SELECT COUNT(*) FROM rma_direct_inbound_units WHERE spare_part_unit_id=?"
            ),
            "task_allocations": (
                "SELECT COUNT(*) FROM task_unit_allocation_events WHERE spare_part_unit_id=?"
            ),
            "local_fulfillment": (
                "SELECT COUNT(*) FROM local_need_fulfillment_events WHERE spare_part_unit_id=?"
            ),
            "physical_consequences": (
                "SELECT COUNT(*) FROM physical_consequence_events "
                "WHERE installed_spare_part_unit_id=? OR inbound_spare_part_unit_id=? "
                "OR parent_dismantled_unit_id=?"
            ),
            "return_selection": (
                "SELECT COUNT(*) FROM rma_return_selection_events WHERE spare_part_unit_id=?"
            ),
            "return_obligation": (
                "SELECT COUNT(*) FROM rma_return_obligation_current WHERE spare_part_unit_id=?"
            ),
            "logistics": (
                "SELECT COUNT(*) FROM logistics_spare_unit_participants WHERE spare_part_unit_id=?"
            ),
            "fault_tags": (
                "SELECT COUNT(*) FROM fault_tag_memberships WHERE spare_part_unit_id=?"
            ),
            "children": (
                "SELECT COUNT(*) FROM spare_part_units WHERE parent_spare_part_unit_id=?"
            ),
            "proposals": (
                "SELECT COUNT(*) FROM inventory_proposal_targets WHERE spare_part_unit_id=?"
            ),
        }
        dependencies: dict[str, int] = {}
        for key, sql in dependency_sql.items():
            params = (identity, identity, identity) if key == "physical_consequences" else (identity,)
            dependencies[key] = int(connection.execute(sql, params).fetchone()[0])
            if dependencies[key]:
                reasons.append(f"{key}_history")
        removable = [
            {"table": "spare_part_current_projection", "ids": [identity]},
            {
                "table": "spare_part_lifecycle_events",
                "ids": [str(item[0]) for item in lifecycle],
            },
            {"table": "spare_part_units", "ids": [identity]},
        ]
        return cls._hard_delete_result(
            target_kind="spare_part_unit",
            target_id=identity,
            reviewed_revision=int(row[7]),
            reasons=reasons,
            removable_rows=removable,
            retained_related_ids=[],
            material={
                "tracking_id": None if row[0] is None else str(row[0]),
                "creation_origin": str(row[1]),
                "condition": str(row[4]),
                "disposition": str(row[5]),
                "projection_fingerprint": str(row[8]),
                "lifecycle_event_ids": [str(item[0]) for item in lifecycle],
                "dependencies": dependencies,
            },
        )

    @staticmethod
    def _hard_delete_fault_tag_preview(
        connection: Any,
        fault_tag_id: str,
    ) -> dict[str, object]:
        identity = require_uuid4(fault_tag_id)
        current = InventoryFaultTagsRepository.current_tag(connection, identity)
        if current is None:
            return {
                "target_kind": "fault_tag",
                "target_id": identity,
                "classification": "INDETERMINATE",
                "reasons": ["target_missing"],
                "reviewed_revision": None,
                "removable_rows": [],
                "retained_related_ids": [],
                "eligibility_fingerprint": sha256_canonical_json(
                    {
                        "schema": "SOMA_INVENTORY_HARD_DELETE_PREVIEW_V1",
                        "target_kind": "fault_tag",
                        "target_id": identity,
                        "classification": "INDETERMINATE",
                        "reasons": ["target_missing"],
                    }
                ),
            }

        reasons: list[str] = []
        if str(current[7]) != "draft":
            reasons.append(f"state:{current[7]}")
        if current[9] is not None:
            reasons.append("current_submission_snapshot")
        if int(current[10]) != 0 or int(current[11]) != 0 or int(current[12]) != 0:
            reasons.append("submitted_or_warehouse_counts")
        if int(current[13]) != 0 or int(current[14]) != 0:
            reasons.append("final_warehouse_counts")

        snapshots = int(
            connection.execute(
                "SELECT COUNT(*) FROM fault_tag_submission_snapshots WHERE fault_tag_id=?",
                (identity,),
            ).fetchone()[0]
        )
        if snapshots:
            reasons.append("submission_history")
        lineage = int(
            connection.execute(
                "SELECT COUNT(*) FROM fault_tag_lineage "
                "WHERE predecessor_fault_tag_id=? OR successor_fault_tag_id=?",
                (identity, identity),
            ).fetchone()[0]
        )
        if lineage:
            reasons.append("lineage_history")
        proposal_targets = int(
            connection.execute(
                "SELECT COUNT(*) FROM inventory_proposal_targets p "
                "WHERE p.fault_tag_id=? OR p.fault_tag_membership_id IN "
                "(SELECT fault_tag_membership_id FROM fault_tag_memberships "
                "WHERE fault_tag_id=?)",
                (identity, identity),
            ).fetchone()[0]
        )
        if proposal_targets:
            reasons.append("proposal_history")
        member_events = int(
            connection.execute(
                "SELECT COUNT(*) FROM fault_tag_membership_events e "
                "JOIN fault_tag_memberships m "
                "ON m.fault_tag_membership_id=e.fault_tag_membership_id "
                "WHERE m.fault_tag_id=?",
                (identity,),
            ).fetchone()[0]
        )
        if member_events:
            reasons.append("membership_lifecycle_history")
        lifecycle_events = connection.execute(
            "SELECT fault_tag_event_id,event_kind FROM fault_tag_lifecycle_events "
            "WHERE fault_tag_id=? ORDER BY recorded_at_utc,fault_tag_event_id",
            (identity,),
        ).fetchall()
        if len(lifecycle_events) != 1 or str(lifecycle_events[0][1]) != "created":
            reasons.append("fault_tag_lifecycle_history")

        members = InventoryFaultTagsRepository._member_payload(connection, identity)
        if any(item["state"] != "draft" or bool(item["active_submitted"]) for item in members):
            reasons.append("non_draft_membership")

        classification = "CLEAR" if not reasons else "BLOCKED"
        member_ids = sorted(str(item["fault_tag_membership_id"]) for item in members)
        retained_related_ids = sorted(
            {
                str(item["rma_id"])
                for item in members
            }
            | {
                str(item["device_part_unit_id"])
                for item in members
                if item["device_part_unit_id"] is not None
            }
            | {
                str(item["spare_part_unit_id"])
                for item in members
                if item["spare_part_unit_id"] is not None
            }
        )
        removable_rows = (
            [
                {"table": "fault_tag_membership_current", "ids": member_ids},
                {"table": "fault_tag_memberships", "ids": member_ids},
                {
                    "table": "fault_tag_current_projection",
                    "ids": [identity],
                },
                {
                    "table": "fault_tag_lifecycle_events",
                    "ids": [str(row[0]) for row in lifecycle_events],
                },
                {"table": "fault_tags", "ids": [identity]},
            ]
            if classification == "CLEAR"
            else []
        )
        material = {
            "schema": "SOMA_INVENTORY_HARD_DELETE_PREVIEW_V1",
            "target_kind": "fault_tag",
            "target_id": identity,
            "classification": classification,
            "reasons": reasons,
            "reviewed_revision": int(current[15]),
            "tracking_id": str(current[1]),
            "draft_revision": int(current[6]),
            "member_ids": member_ids,
            "member_revisions": [
                {
                    "id": str(item["fault_tag_membership_id"]),
                    "revision": int(item["revision"]),
                    "fingerprint": str(item["input_fingerprint"]),
                }
                for item in members
            ],
            "lifecycle_event_ids": [str(row[0]) for row in lifecycle_events],
            "retained_related_ids": retained_related_ids,
        }
        return {
            "target_kind": "fault_tag",
            "target_id": identity,
            "classification": classification,
            "reasons": reasons,
            "reviewed_revision": int(current[15]),
            "removable_rows": removable_rows,
            "retained_related_ids": retained_related_ids,
            "eligibility_fingerprint": sha256_canonical_json(material),
        }

    def preview_hard_delete(
        self,
        *,
        target_kind: str,
        target_id: str,
    ) -> dict[str, object]:
        handlers = {
            "spare_need": self._hard_delete_spare_need_preview,
            "spare_request": self._hard_delete_spare_request_preview,
            "spare_part_unit": self._hard_delete_spare_part_unit_preview,
            "fault_tag": self._hard_delete_fault_tag_preview,
        }
        try:
            handler = handlers[target_kind]
        except KeyError as exc:
            raise ValidationError("Inventory hard-delete target kind is invalid") from exc
        with ReadSnapshot(self._factory) as snapshot:
            return handler(snapshot.connection, target_id)


__all__ = [
    "InventoryBulkPreviewTarget",
    "InventoryPreviewsQueryService",
]
