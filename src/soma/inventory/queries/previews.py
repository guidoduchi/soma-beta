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
        if target_kind != "fault_tag":
            raise ValidationError(
                "This Inventory hard-delete preview currently supports fault_tag authority"
            )
        with ReadSnapshot(self._factory) as snapshot:
            return self._hard_delete_fault_tag_preview(snapshot.connection, target_id)


__all__ = [
    "InventoryBulkPreviewTarget",
    "InventoryPreviewsQueryService",
]
