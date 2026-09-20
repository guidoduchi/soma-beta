from __future__ import annotations

from typing import Any

from soma.foundation.errors import IntegrityFailure, SomaError
from soma.foundation.identifiers import new_uuid4, utc_epoch_seconds
from soma.foundation.strict_json import canonical_json_bytes, sha256_canonical_json

from ..domain.fault_tags import FaultTagMembershipIntent
from .rmas import InventoryRmasRepository


class InventoryFaultTagsRepository:
    @staticmethod
    def allocate_tracking(connection: Any, command_id: str) -> tuple[int, str]:
        row = connection.execute(
            "SELECT next_sequence,revision FROM inventory_tracking_allocators "
            "WHERE allocator_kind='fault_tag'"
        ).fetchone()
        if row is None:
            raise IntegrityFailure("Inventory Fault Tag allocator is missing")
        sequence = int(row[0])
        revision = int(row[1])
        if sequence >= 100_000_000:
            raise SomaError("INV_INVALID_ID", "Fault Tag tracking sequence is exhausted")
        updated = connection.execute(
            "UPDATE inventory_tracking_allocators SET next_sequence=?,revision=?,last_command_id=? "
            "WHERE allocator_kind='fault_tag' AND next_sequence=? AND revision=?",
            (sequence + 1, revision + 1, command_id, sequence, revision),
        )
        if updated.rowcount != 1:
            raise SomaError("INV_STALE", "Fault Tag allocator changed")
        return sequence, f"FT-{sequence:08d}"

    @staticmethod
    def current_tag(connection: Any, fault_tag_id: str):
        return connection.execute(
            "SELECT t.fault_tag_id,t.tracking_id,t.draft_return_method,"
            "t.draft_pickup_dispatch_location_id,t.draft_pickup_contact_id,"
            "t.draft_pickup_instructions,t.draft_revision,p.state,p.archived,"
            "p.current_submission_snapshot_id,p.submitted_member_count,"
            "p.awaiting_receipt_count,p.awaiting_final_count,p.accepted_count,"
            "p.rejected_count,p.revision,p.input_fingerprint "
            "FROM fault_tags t JOIN fault_tag_current_projection p "
            "ON p.fault_tag_id=t.fault_tag_id WHERE t.fault_tag_id=?",
            (fault_tag_id,),
        ).fetchone()

    @staticmethod
    def _typed_return(
        row: Any,
    ) -> tuple[str, str]:
        if row[1] is not None and row[2] is None:
            return "device_part_unit", str(row[1])
        if row[2] is not None and row[1] is None:
            return "spare_part_unit", str(row[2])
        raise IntegrityFailure("RMA return obligation has invalid typed unit state")

    @classmethod
    def membership_authority(cls, connection: Any, rma_id: str) -> dict[str, object]:
        row = connection.execute(
            "SELECT o.obligation_state,o.device_part_unit_id,o.spare_part_unit_id,"
            "o.physical_consequence_id,o.revision,r.current_c10,r.promised_bom_code,"
            "r.state,r.return_obligation_open "
            "FROM rma_return_obligation_current o "
            "JOIN (SELECT m.rma_id,a.c10 AS current_c10,m.promised_bom_code,"
            "l.state,l.return_obligation_open FROM rmas m "
            "JOIN rma_identifier_aliases a ON a.rma_id=m.rma_id AND a.alias_kind='current' "
            "JOIN rma_lifecycle_projection l ON l.rma_id=m.rma_id) r "
            "ON r.rma_id=o.rma_id WHERE o.rma_id=?",
            (rma_id,),
        ).fetchone()
        if row is None:
            raise SomaError("RETURN_SELECTION_INVALID", "RMA return obligation does not exist")
        if str(row[0]) != "open" or not bool(row[8]):
            raise SomaError("RETURN_SELECTION_INVALID", "RMA return obligation is not open")
        consequence_id = row[3]
        if consequence_id is None:
            raise IntegrityFailure("open RMA return obligation lacks physical consequence")
        consequence = connection.execute(
            "SELECT c.rma_id,p.physical_disposition,p.revision,p.input_fingerprint "
            "FROM inventory_physical_consequences c "
            "JOIN physical_consequence_current p "
            "ON p.physical_consequence_id=c.physical_consequence_id "
            "WHERE c.physical_consequence_id=?",
            (str(consequence_id),),
        ).fetchone()
        if consequence is None or consequence[0] is None or str(consequence[0]) != rma_id:
            raise SomaError(
                "RETURN_SELECTION_INVALID",
                "RMA return obligation is not backed by its current physical consequence",
            )
        unit_kind, unit_id = cls._typed_return(row)
        if unit_kind == "device_part_unit":
            unit = connection.execute(
                "SELECT bom_code,manufacturer_serial FROM device_part_units WHERE device_part_unit_id=?",
                (unit_id,),
            ).fetchone()
        else:
            unit = connection.execute(
                "SELECT bom_code,manufacturer_serial FROM spare_part_units WHERE spare_part_unit_id=?",
                (unit_id,),
            ).fetchone()
        if unit is None:
            raise IntegrityFailure("RMA return obligation points to missing physical unit")
        return {
            "rma_id": rma_id,
            "obligation_revision": int(row[4]),
            "physical_consequence_id": str(consequence_id),
            "physical_consequence_revision": int(consequence[2]),
            "physical_consequence_fingerprint": str(consequence[3]),
            "unit_kind": unit_kind,
            "unit_id": unit_id,
            "current_c10": str(row[5]),
            "promised_bom_code": str(row[6]),
            "rma_state": str(row[7]),
            "unit_bom_code": str(unit[0]),
            "unit_serial": None if unit[1] is None else str(unit[1]),
        }

    @classmethod
    def require_membership_available(
        cls,
        connection: Any,
        *,
        rma_id: str,
        allow_fault_tag_id: str | None = None,
    ) -> dict[str, object]:
        authority = cls.membership_authority(connection, rma_id)
        conflict = connection.execute(
            "SELECT fault_tag_membership_id,fault_tag_id FROM fault_tag_membership_current "
            "WHERE rma_id=? AND active_submitted=1",
            (rma_id,),
        ).fetchone()
        if conflict is not None and (
            allow_fault_tag_id is None or str(conflict[1]) != allow_fault_tag_id
        ):
            raise SomaError(
                "FAULT_TAG_MEMBERSHIP_CONFLICT",
                "RMA obligation already belongs to another active submitted Fault Tag",
            )
        unit_kind = str(authority["unit_kind"])
        unit_id = str(authority["unit_id"])
        if unit_kind == "device_part_unit":
            conflict = connection.execute(
                "SELECT fault_tag_id FROM fault_tag_membership_current "
                "WHERE device_part_unit_id=? AND active_submitted=1",
                (unit_id,),
            ).fetchone()
        else:
            conflict = connection.execute(
                "SELECT fault_tag_id FROM fault_tag_membership_current "
                "WHERE spare_part_unit_id=? AND active_submitted=1",
                (unit_id,),
            ).fetchone()
        if conflict is not None and (
            allow_fault_tag_id is None or str(conflict[0]) != allow_fault_tag_id
        ):
            raise SomaError(
                "FAULT_TAG_MEMBERSHIP_CONFLICT",
                "Return unit already belongs to another active submitted Fault Tag",
            )
        return authority

    @staticmethod
    def _member_payload(connection: Any, fault_tag_id: str) -> list[dict[str, object]]:
        rows = connection.execute(
            "SELECT m.fault_tag_membership_id,m.rma_id,m.physical_consequence_id,"
            "m.device_part_unit_id,m.spare_part_unit_id,m.return_reason,m.draft_revision,"
            "c.state,c.active_submitted,c.revision,c.input_fingerprint,c.last_event_id "
            "FROM fault_tag_memberships m JOIN fault_tag_membership_current c "
            "ON c.fault_tag_membership_id=m.fault_tag_membership_id "
            "WHERE m.fault_tag_id=? ORDER BY m.fault_tag_membership_id",
            (fault_tag_id,),
        ).fetchall()
        return [
            {
                "fault_tag_membership_id": str(row[0]),
                "rma_id": str(row[1]),
                "physical_consequence_id": str(row[2]),
                "device_part_unit_id": None if row[3] is None else str(row[3]),
                "spare_part_unit_id": None if row[4] is None else str(row[4]),
                "return_reason": str(row[5]),
                "draft_revision": int(row[6]),
                "state": str(row[7]),
                "active_submitted": bool(row[8]),
                "revision": int(row[9]),
                "input_fingerprint": str(row[10]),
                "last_event_id": None if row[11] is None else str(row[11]),
            }
            for row in rows
        ]

    @classmethod
    def tag_fingerprint(
        cls,
        connection: Any,
        *,
        fault_tag_id: str,
        state: str,
        archived: bool,
        current_submission_snapshot_id: str | None,
        submitted_member_count: int,
        awaiting_receipt_count: int,
        awaiting_final_count: int,
        accepted_count: int,
        rejected_count: int,
    ) -> str:
        tag = connection.execute(
            "SELECT tracking_id,draft_return_method,draft_pickup_dispatch_location_id,"
            "draft_pickup_contact_id,draft_pickup_instructions,draft_revision "
            "FROM fault_tags WHERE fault_tag_id=?",
            (fault_tag_id,),
        ).fetchone()
        if tag is None:
            raise IntegrityFailure("Fault Tag disappeared during projection rebuild")
        return sha256_canonical_json(
            {
                "schema": "SOMA_FAULT_TAG_CURRENT_V1",
                "fault_tag_id": fault_tag_id,
                "tracking_id": str(tag[0]),
                "draft": {
                    "return_method": str(tag[1]),
                    "pickup_dispatch_location_id": None if tag[2] is None else str(tag[2]),
                    "pickup_contact_id": None if tag[3] is None else str(tag[3]),
                    "pickup_instructions": None if tag[4] is None else str(tag[4]),
                    "revision": int(tag[5]),
                    "members": cls.current_members(connection, fault_tag_id),
                },
                "state": state,
                "archived": archived,
                "current_submission_snapshot_id": current_submission_snapshot_id,
                "submitted_member_count": submitted_member_count,
                "awaiting_receipt_count": awaiting_receipt_count,
                "awaiting_final_count": awaiting_final_count,
                "accepted_count": accepted_count,
                "rejected_count": rejected_count,
            }
        )

    @staticmethod
    def membership_fingerprint(
        *,
        membership_id: str,
        fault_tag_id: str,
        rma_id: str,
        device_part_unit_id: str | None,
        spare_part_unit_id: str | None,
        state: str,
        active_submitted: bool,
        revision: int,
        last_event_id: str | None,
    ) -> str:
        return sha256_canonical_json(
            {
                "schema": "SOMA_FAULT_TAG_MEMBERSHIP_CURRENT_V1",
                "fault_tag_membership_id": membership_id,
                "fault_tag_id": fault_tag_id,
                "rma_id": rma_id,
                "device_part_unit_id": device_part_unit_id,
                "spare_part_unit_id": spare_part_unit_id,
                "state": state,
                "active_submitted": active_submitted,
                "revision": revision,
                "last_event_id": last_event_id,
            }
        )

    @classmethod
    def create_draft(
        cls,
        connection: Any,
        *,
        fault_tag_id: str,
        return_method: str,
        pickup_dispatch_location_id: str | None,
        pickup_contact_id: str | None,
        pickup_instructions: str | None,
        memberships: tuple[FaultTagMembershipIntent, ...],
        command_id: str,
    ) -> dict[str, object]:
        authorities = [
            cls.require_membership_available(connection, rma_id=item.rma_id)
            for item in memberships
        ]
        sequence, tracking_id = cls.allocate_tracking(connection, command_id)
        now = utc_epoch_seconds()
        connection.execute(
            "INSERT INTO fault_tags("
            "fault_tag_id,tracking_sequence,tracking_id,creation_origin,draft_return_method,"
            "draft_pickup_dispatch_location_id,draft_pickup_contact_id,draft_pickup_instructions,"
            "draft_revision,created_at_utc,created_command_id"
            ") VALUES (?,?,?,'manual',?,?,?,?,1,?,?)",
            (
                fault_tag_id,
                sequence,
                tracking_id,
                return_method,
                pickup_dispatch_location_id,
                pickup_contact_id,
                pickup_instructions,
                now,
                command_id,
            ),
        )
        created_event_id = new_uuid4()
        connection.execute(
            "INSERT INTO fault_tag_lifecycle_events("
            "fault_tag_event_id,fault_tag_id,event_kind,effective_at_utc,target_event_id,"
            "reason_code,evidence_kind,evidence_id,recorded_at_utc,command_id"
            ") VALUES (?,?,'created',NULL,NULL,NULL,NULL,NULL,?,?)",
            (created_event_id, fault_tag_id, now, command_id),
        )
        member_ids: list[str] = []
        for item, authority in zip(memberships, authorities):
            membership_id = new_uuid4()
            device_id = (
                str(authority["unit_id"])
                if authority["unit_kind"] == "device_part_unit"
                else None
            )
            spare_id = (
                str(authority["unit_id"])
                if authority["unit_kind"] == "spare_part_unit"
                else None
            )
            connection.execute(
                "INSERT INTO fault_tag_memberships("
                "fault_tag_membership_id,fault_tag_id,rma_id,physical_consequence_id,"
                "device_part_unit_id,spare_part_unit_id,return_reason,draft_revision,"
                "created_at_utc,created_command_id"
                ") VALUES (?,?,?,?,?,?,?,1,?,?)",
                (
                    membership_id,
                    fault_tag_id,
                    item.rma_id,
                    str(authority["physical_consequence_id"]),
                    device_id,
                    spare_id,
                    item.return_reason,
                    now,
                    command_id,
                ),
            )
            fingerprint = cls.membership_fingerprint(
                membership_id=membership_id,
                fault_tag_id=fault_tag_id,
                rma_id=item.rma_id,
                device_part_unit_id=device_id,
                spare_part_unit_id=spare_id,
                state="draft",
                active_submitted=False,
                revision=1,
                last_event_id=None,
            )
            connection.execute(
                "INSERT INTO fault_tag_membership_current("
                "fault_tag_membership_id,fault_tag_id,rma_id,device_part_unit_id,"
                "spare_part_unit_id,state,active_submitted,revision,input_fingerprint,"
                "last_event_id,last_command_id"
                ") VALUES (?,?,?,?,?,'draft',0,1,?,NULL,?)",
                (
                    membership_id,
                    fault_tag_id,
                    item.rma_id,
                    device_id,
                    spare_id,
                    fingerprint,
                    command_id,
                ),
            )
            member_ids.append(membership_id)
        projection_fingerprint = cls.tag_fingerprint(
            connection,
            fault_tag_id=fault_tag_id,
            state="draft",
            archived=False,
            current_submission_snapshot_id=None,
            submitted_member_count=0,
            awaiting_receipt_count=0,
            awaiting_final_count=0,
            accepted_count=0,
            rejected_count=0,
        )
        connection.execute(
            "INSERT INTO fault_tag_current_projection("
            "fault_tag_id,state,archived,current_submission_snapshot_id,submitted_member_count,"
            "awaiting_receipt_count,awaiting_final_count,accepted_count,rejected_count,"
            "revision,input_fingerprint,last_command_id"
            ") VALUES (?,'draft',0,NULL,0,0,0,0,0,1,?,?)",
            (fault_tag_id, projection_fingerprint, command_id),
        )
        return {
            "fault_tag_id": fault_tag_id,
            "tracking_id": tracking_id,
            "created_event_id": created_event_id,
            "membership_ids": tuple(member_ids),
            "revision": 1,
            "input_fingerprint": projection_fingerprint,
        }

    @classmethod
    def current_members(
        cls,
        connection: Any,
        fault_tag_id: str,
    ) -> list[dict[str, object]]:
        return [
            member
            for member in cls._member_payload(connection, fault_tag_id)
            if member["state"] not in {"cancelled", "superseded"}
        ]

    @classmethod
    def update_draft(
        cls,
        connection: Any,
        *,
        fault_tag_id: str,
        expected_revision: int,
        expected_fingerprint: str,
        return_method: str,
        pickup_dispatch_location_id: str | None,
        pickup_contact_id: str | None,
        pickup_instructions: str | None,
        add_memberships: tuple[FaultTagMembershipIntent, ...],
        remove_membership_ids: tuple[str, ...],
        command_id: str,
    ) -> dict[str, object]:
        current = cls.require_exact_draft(
            connection,
            fault_tag_id=fault_tag_id,
            expected_revision=expected_revision,
            expected_fingerprint=expected_fingerprint,
        )
        all_members = cls._member_payload(connection, fault_tag_id)
        by_id = {str(item["fault_tag_membership_id"]): item for item in all_members}
        for membership_id in remove_membership_ids:
            member = by_id.get(membership_id)
            if member is None or member["state"] != "draft":
                raise SomaError(
                    "FAULT_TAG_NOT_DRAFT",
                    "Fault Tag membership is not removable Draft authority",
                )

        retained_rmas = {
            str(item["rma_id"])
            for item in all_members
            if item["state"] == "draft"
            and str(item["fault_tag_membership_id"]) not in remove_membership_ids
        }
        for item in add_memberships:
            if item.rma_id in retained_rmas:
                raise SomaError(
                    "FAULT_TAG_MEMBERSHIP_CONFLICT",
                    "Fault Tag already contains this RMA obligation",
                )
            cls.require_membership_available(
                connection,
                rma_id=item.rma_id,
                allow_fault_tag_id=fault_tag_id,
            )
            retained_rmas.add(item.rma_id)

        new_draft_revision = int(current[6]) + 1
        now = utc_epoch_seconds()
        updated_tag = connection.execute(
            "UPDATE fault_tags SET draft_return_method=?,"
            "draft_pickup_dispatch_location_id=?,draft_pickup_contact_id=?,"
            "draft_pickup_instructions=?,draft_revision=? "
            "WHERE fault_tag_id=? AND draft_revision=?",
            (
                return_method,
                pickup_dispatch_location_id,
                pickup_contact_id,
                pickup_instructions,
                new_draft_revision,
                fault_tag_id,
                int(current[6]),
            ),
        )
        if updated_tag.rowcount != 1:
            raise SomaError("INV_STALE", "Fault Tag draft revision changed")

        removed_event_ids: list[str] = []
        for membership_id in remove_membership_ids:
            member = by_id[membership_id]
            event_id = new_uuid4()
            connection.execute(
                "INSERT INTO fault_tag_membership_events("
                "membership_event_id,fault_tag_membership_id,event_kind,effective_at_utc,"
                "target_event_id,reason_code,evidence_kind,evidence_id,recorded_at_utc,command_id"
                ") VALUES (?,?,'cancelled',NULL,?,"
                "'draft_membership_removed',NULL,NULL,?,?)",
                (
                    event_id,
                    membership_id,
                    member["last_event_id"],
                    now,
                    command_id,
                ),
            )
            revision = int(member["revision"]) + 1
            fingerprint = cls.membership_fingerprint(
                membership_id=membership_id,
                fault_tag_id=fault_tag_id,
                rma_id=str(member["rma_id"]),
                device_part_unit_id=member["device_part_unit_id"],
                spare_part_unit_id=member["spare_part_unit_id"],
                state="cancelled",
                active_submitted=False,
                revision=revision,
                last_event_id=event_id,
            )
            changed = connection.execute(
                "UPDATE fault_tag_membership_current SET state='cancelled',"
                "active_submitted=0,revision=?,input_fingerprint=?,last_event_id=?,"
                "last_command_id=? WHERE fault_tag_membership_id=? AND revision=? "
                "AND state='draft'",
                (
                    revision,
                    fingerprint,
                    event_id,
                    command_id,
                    membership_id,
                    int(member["revision"]),
                ),
            )
            if changed.rowcount != 1:
                raise SomaError("INV_STALE", "Fault Tag draft membership changed")
            removed_event_ids.append(event_id)

        added_ids: list[str] = []
        for item in add_memberships:
            authority = cls.require_membership_available(
                connection,
                rma_id=item.rma_id,
                allow_fault_tag_id=fault_tag_id,
            )
            membership_id = new_uuid4()
            device_id = (
                str(authority["unit_id"])
                if authority["unit_kind"] == "device_part_unit"
                else None
            )
            spare_id = (
                str(authority["unit_id"])
                if authority["unit_kind"] == "spare_part_unit"
                else None
            )
            connection.execute(
                "INSERT INTO fault_tag_memberships("
                "fault_tag_membership_id,fault_tag_id,rma_id,physical_consequence_id,"
                "device_part_unit_id,spare_part_unit_id,return_reason,draft_revision,"
                "created_at_utc,created_command_id"
                ") VALUES (?,?,?,?,?,?,?,?,?,?)",
                (
                    membership_id,
                    fault_tag_id,
                    item.rma_id,
                    str(authority["physical_consequence_id"]),
                    device_id,
                    spare_id,
                    item.return_reason,
                    new_draft_revision,
                    now,
                    command_id,
                ),
            )
            fingerprint = cls.membership_fingerprint(
                membership_id=membership_id,
                fault_tag_id=fault_tag_id,
                rma_id=item.rma_id,
                device_part_unit_id=device_id,
                spare_part_unit_id=spare_id,
                state="draft",
                active_submitted=False,
                revision=1,
                last_event_id=None,
            )
            connection.execute(
                "INSERT INTO fault_tag_membership_current("
                "fault_tag_membership_id,fault_tag_id,rma_id,device_part_unit_id,"
                "spare_part_unit_id,state,active_submitted,revision,input_fingerprint,"
                "last_event_id,last_command_id"
                ") VALUES (?,?,?,?,?,'draft',0,1,?,NULL,?)",
                (
                    membership_id,
                    fault_tag_id,
                    item.rma_id,
                    device_id,
                    spare_id,
                    fingerprint,
                    command_id,
                ),
            )
            added_ids.append(membership_id)

        resulting_revision = int(current[15]) + 1
        tag_fp = cls.tag_fingerprint(
            connection,
            fault_tag_id=fault_tag_id,
            state="draft",
            archived=bool(current[8]),
            current_submission_snapshot_id=None,
            submitted_member_count=0,
            awaiting_receipt_count=0,
            awaiting_final_count=0,
            accepted_count=0,
            rejected_count=0,
        )
        changed_tag = connection.execute(
            "UPDATE fault_tag_current_projection SET revision=?,input_fingerprint=?,"
            "last_command_id=? WHERE fault_tag_id=? AND revision=? AND state='draft'",
            (
                resulting_revision,
                tag_fp,
                command_id,
                fault_tag_id,
                int(current[15]),
            ),
        )
        if changed_tag.rowcount != 1:
            raise SomaError("INV_STALE", "Fault Tag projection changed during draft update")
        return {
            "added_membership_ids": tuple(added_ids),
            "removed_event_ids": tuple(removed_event_ids),
            "revision": resulting_revision,
            "input_fingerprint": tag_fp,
        }

    @classmethod
    def correct_false_submission(
        cls,
        connection: Any,
        *,
        fault_tag_id: str,
        submission_event_id: str,
        reason_code: str,
        confirmed_no_real_send: bool,
        command_id: str,
    ) -> dict[str, object]:
        if confirmed_no_real_send is not True:
            raise SomaError(
                "CORRECTION_TARGET_INVALID",
                "False-submission correction requires explicit proof of no real send",
            )
        current = cls.current_tag(connection, fault_tag_id)
        if current is None:
            raise SomaError("INV_STALE", "Fault Tag no longer exists")
        if str(current[7]) not in {"submitted", "in_warehouse_review"}:
            raise SomaError(
                "CORRECTION_TARGET_INVALID",
                "Fault Tag has no current accepted submission to correct",
            )
        snapshot_id = current[9]
        if snapshot_id is None:
            raise IntegrityFailure("submitted Fault Tag lacks current snapshot")
        snapshot = connection.execute(
            "SELECT submission_event_id FROM fault_tag_submission_snapshots "
            "WHERE fault_tag_submission_snapshot_id=? AND fault_tag_id=?",
            (str(snapshot_id), fault_tag_id),
        ).fetchone()
        if snapshot is None or str(snapshot[0]) != submission_event_id:
            raise SomaError(
                "CORRECTION_TARGET_INVALID",
                "Fault Tag submission event is not current-effective",
            )
        submission = connection.execute(
            "SELECT evidence_kind FROM fault_tag_lifecycle_events "
            "WHERE fault_tag_event_id=? AND fault_tag_id=? AND event_kind='submission_accepted'",
            (submission_event_id, fault_tag_id),
        ).fetchone()
        if submission is None:
            raise SomaError("CORRECTION_TARGET_INVALID", "Submission event does not exist")
        if submission[0] is not None:
            raise SomaError(
                "CORRECTION_TARGET_INVALID",
                "Indexed sent evidence contradicts false-submission correction",
            )

        members = cls._member_payload(connection, fault_tag_id)
        submitted = [
            item for item in members if item["state"] in {"submitted_awaiting_receipt", "warehouse_received"}
        ]
        if len(submitted) != int(current[10]):
            raise IntegrityFailure("Fault Tag submitted-member count disagrees with member projection")
        if any(item["state"] != "submitted_awaiting_receipt" for item in submitted):
            raise SomaError(
                "CORRECTION_TARGET_INVALID",
                "Warehouse evidence contradicts false-submission correction",
            )
        for member in submitted:
            downstream = connection.execute(
                "SELECT 1 FROM fault_tag_membership_events "
                "WHERE fault_tag_membership_id=? AND event_kind IN "
                "('warehouse_received','warehouse_accepted','warehouse_rejected') LIMIT 1",
                (str(member["fault_tag_membership_id"]),),
            ).fetchone()
            if downstream is not None:
                raise SomaError(
                    "CORRECTION_TARGET_INVALID",
                    "Warehouse history contradicts false-submission correction",
                )

        now = utc_epoch_seconds()
        correction_event_id = new_uuid4()
        connection.execute(
            "INSERT INTO fault_tag_lifecycle_events("
            "fault_tag_event_id,fault_tag_id,event_kind,effective_at_utc,target_event_id,"
            "reason_code,evidence_kind,evidence_id,recorded_at_utc,command_id"
            ") VALUES (?,?,'submission_corrected_false',NULL,?,?,NULL,NULL,?,?)",
            (
                correction_event_id,
                fault_tag_id,
                submission_event_id,
                reason_code,
                now,
                command_id,
            ),
        )
        membership_correction_ids: list[str] = []
        for member in submitted:
            membership_id = str(member["fault_tag_membership_id"])
            correction_id = new_uuid4()
            connection.execute(
                "INSERT INTO fault_tag_membership_events("
                "membership_event_id,fault_tag_membership_id,event_kind,effective_at_utc,"
                "target_event_id,reason_code,evidence_kind,evidence_id,recorded_at_utc,command_id"
                ") VALUES (?,?,'correct',NULL,?,?,NULL,NULL,?,?)",
                (
                    correction_id,
                    membership_id,
                    member["last_event_id"],
                    reason_code,
                    now,
                    command_id,
                ),
            )
            revision = int(member["revision"]) + 1
            fingerprint = cls.membership_fingerprint(
                membership_id=membership_id,
                fault_tag_id=fault_tag_id,
                rma_id=str(member["rma_id"]),
                device_part_unit_id=member["device_part_unit_id"],
                spare_part_unit_id=member["spare_part_unit_id"],
                state="draft",
                active_submitted=False,
                revision=revision,
                last_event_id=correction_id,
            )
            changed = connection.execute(
                "UPDATE fault_tag_membership_current SET state='draft',active_submitted=0,"
                "revision=?,input_fingerprint=?,last_event_id=?,last_command_id=? "
                "WHERE fault_tag_membership_id=? AND revision=? "
                "AND state='submitted_awaiting_receipt'",
                (
                    revision,
                    fingerprint,
                    correction_id,
                    command_id,
                    membership_id,
                    int(member["revision"]),
                ),
            )
            if changed.rowcount != 1:
                raise SomaError("INV_STALE", "Fault Tag membership changed during correction")

            rma = InventoryRmasRepository.current_rma(connection, str(member["rma_id"]))
            if rma is None:
                raise SomaError("INV_STALE", "RMA disappeared during Fault Tag correction")
            if rma[11] is None or str(rma[11]) != membership_id:
                raise SomaError(
                    "CORRECTION_TARGET_INVALID",
                    "RMA active Fault Tag membership no longer matches correction target",
                )
            rma_revision = int(rma[12]) + 1
            rma_fp = InventoryRmasRepository.rma_lifecycle_fingerprint(
                rma_id=str(member["rma_id"]),
                current_c10=str(rma[4]),
                state="return_open",
                target_device_part_unit_id=None if rma[6] is None else str(rma[6]),
                direct_inbound_spare_part_unit_id=None if rma[7] is None else str(rma[7]),
                return_device_part_unit_id=None if rma[8] is None else str(rma[8]),
                return_spare_part_unit_id=None if rma[9] is None else str(rma[9]),
                return_obligation_open=True,
                active_fault_tag_membership_id=None,
            )
            updated_rma = connection.execute(
                "UPDATE rma_lifecycle_projection SET state='return_open',"
                "active_fault_tag_membership_id=NULL,revision=?,input_fingerprint=?,"
                "last_command_id=? WHERE rma_id=? AND revision=?",
                (
                    rma_revision,
                    rma_fp,
                    command_id,
                    str(member["rma_id"]),
                    int(rma[12]),
                ),
            )
            if updated_rma.rowcount != 1:
                raise SomaError("INV_STALE", "RMA lifecycle changed during Fault Tag correction")
            membership_correction_ids.append(correction_id)

        draft_revision = int(current[6]) + 1
        changed_draft = connection.execute(
            "UPDATE fault_tags SET draft_revision=? WHERE fault_tag_id=? AND draft_revision=?",
            (draft_revision, fault_tag_id, int(current[6])),
        )
        if changed_draft.rowcount != 1:
            raise SomaError("INV_STALE", "Fault Tag draft revision changed during correction")

        resulting_revision = int(current[15]) + 1
        tag_fp = cls.tag_fingerprint(
            connection,
            fault_tag_id=fault_tag_id,
            state="draft",
            archived=bool(current[8]),
            current_submission_snapshot_id=None,
            submitted_member_count=0,
            awaiting_receipt_count=0,
            awaiting_final_count=0,
            accepted_count=0,
            rejected_count=0,
        )
        changed_tag = connection.execute(
            "UPDATE fault_tag_current_projection SET state='draft',"
            "current_submission_snapshot_id=NULL,submitted_member_count=0,"
            "awaiting_receipt_count=0,awaiting_final_count=0,accepted_count=0,"
            "rejected_count=0,revision=?,input_fingerprint=?,last_command_id=? "
            "WHERE fault_tag_id=? AND revision=?",
            (
                resulting_revision,
                tag_fp,
                command_id,
                fault_tag_id,
                int(current[15]),
            ),
        )
        if changed_tag.rowcount != 1:
            raise SomaError("INV_STALE", "Fault Tag changed during false-submission correction")
        return {
            "correction_event_id": correction_event_id,
            "membership_correction_ids": tuple(membership_correction_ids),
            "revision": resulting_revision,
            "input_fingerprint": tag_fp,
        }

    @classmethod
    def response(cls, connection: Any, fault_tag_id: str) -> dict[str, object]:
        current = cls.current_tag(connection, fault_tag_id)
        if current is None:
            raise SomaError("INV_STALE", "Fault Tag no longer exists")
        state = str(current[7])
        transport_state = {
            "draft": "draft",
            "submitted": "submitted",
            "in_warehouse_review": "submitted",
            "terminal_completed": "terminal",
            "terminal_with_rejected": "terminal",
            "cancelled": "terminal",
            "superseded": "superseded",
        }[state]
        return {
            "fault_tag_id": fault_tag_id,
            "tracking_handle": str(current[1]),
            "state": transport_state,
            "revision": int(current[15]),
            "input_fingerprint": str(current[16]),
            "return_method": str(current[2]),
            "pickup_dispatch_location_id": None if current[3] is None else str(current[3]),
            "pickup_contact_id": None if current[4] is None else str(current[4]),
            "members": cls.current_members(connection, fault_tag_id),
        }

    @classmethod
    def require_exact_draft(
        cls,
        connection: Any,
        *,
        fault_tag_id: str,
        expected_revision: int,
        expected_fingerprint: str,
    ):
        current = cls.current_tag(connection, fault_tag_id)
        if current is None:
            raise SomaError("INV_STALE", "Fault Tag no longer exists")
        if str(current[7]) != "draft":
            raise SomaError("FAULT_TAG_NOT_DRAFT", "Fault Tag is not editable Draft")
        if int(current[15]) != expected_revision or str(current[16]) != expected_fingerprint:
            raise SomaError("INV_STALE", "Fault Tag Draft changed")
        return current

    @classmethod
    def _display_snapshot(
        cls,
        authority: dict[str, object],
    ) -> dict[str, object]:
        return {
            "schema": "FTT_MEMBERSHIP_DISPLAY_V1",
            "rma_id": str(authority["rma_id"]),
            "current_c10": str(authority["current_c10"]),
            "promised_bom_code": str(authority["promised_bom_code"]),
            "physical_consequence_id": str(authority["physical_consequence_id"]),
            "unit_kind": str(authority["unit_kind"]),
            "unit_id": str(authority["unit_id"]),
            "unit_bom_code": str(authority["unit_bom_code"]),
            "unit_serial": authority["unit_serial"],
        }

    @classmethod
    def accept_submission(
        cls,
        connection: Any,
        *,
        fault_tag_id: str,
        expected_revision: int,
        expected_fingerprint: str,
        pickup_context: dict[str, object],
        effective_submission_at_utc: int | None,
        evidence_kind: str | None,
        evidence_id: str | None,
        command_id: str,
        force_batch: bool = False,
    ) -> dict[str, object]:
        current = cls.require_exact_draft(
            connection,
            fault_tag_id=fault_tag_id,
            expected_revision=expected_revision,
            expected_fingerprint=expected_fingerprint,
        )
        members = cls.current_members(connection, fault_tag_id)
        if not members:
            raise SomaError("FAULT_TAG_NOT_DRAFT", "Fault Tag submission requires at least one member")
        if str(current[2]) == "pickup" and current[3] is None:
            raise SomaError(
                "FAULT_TAG_PICKUP_ORIGIN_REQUIRED",
                "Pickup Fault Tag requires one pickup-origin Dispatch Location",
            )

        authorities: list[dict[str, object]] = []
        for member in members:
            if member["state"] != "draft":
                raise SomaError("FAULT_TAG_NOT_DRAFT", "Fault Tag membership is not Draft")
            authority = cls.require_membership_available(
                connection,
                rma_id=str(member["rma_id"]),
                allow_fault_tag_id=fault_tag_id,
            )
            expected_device = member["device_part_unit_id"]
            expected_spare = member["spare_part_unit_id"]
            if (
                str(authority["physical_consequence_id"]) != member["physical_consequence_id"]
                or (
                    authority["unit_kind"] == "device_part_unit"
                    and str(authority["unit_id"]) != expected_device
                )
                or (
                    authority["unit_kind"] == "spare_part_unit"
                    and str(authority["unit_id"]) != expected_spare
                )
            ):
                raise SomaError(
                    "RETURN_SELECTION_INVALID",
                    "Fault Tag membership no longer matches current return obligation",
                )
            authorities.append(authority)

        now = utc_epoch_seconds()
        submission_event_id = new_uuid4()
        snapshot_id = new_uuid4()
        membership_snapshot_rows: list[tuple[str, dict[str, object], dict[str, object]]] = []
        for member, authority in zip(members, authorities):
            membership_snapshot_rows.append(
                (new_uuid4(), member, cls._display_snapshot(authority))
            )
        snapshot_object = {
            "schema": "SOMA_FAULT_TAG_SUBMISSION_SNAPSHOT_V1",
            "fault_tag_id": fault_tag_id,
            "tracking_id": str(current[1]),
            "return_method": str(current[2]),
            "pickup_context": pickup_context,
            "pickup_instructions": None if current[5] is None else str(current[5]),
            "effective_submission_at_utc": effective_submission_at_utc,
            "members": [
                {
                    "fault_tag_membership_id": str(member["fault_tag_membership_id"]),
                    "rma_id": str(member["rma_id"]),
                    "physical_consequence_id": str(member["physical_consequence_id"]),
                    "device_part_unit_id": member["device_part_unit_id"],
                    "spare_part_unit_id": member["spare_part_unit_id"],
                    "return_reason": str(member["return_reason"]),
                    "display": display,
                }
                for _snapshot_id, member, display in membership_snapshot_rows
            ],
        }
        snapshot_hash = sha256_canonical_json(snapshot_object)
        connection.execute(
            "INSERT INTO fault_tag_lifecycle_events("
            "fault_tag_event_id,fault_tag_id,event_kind,effective_at_utc,target_event_id,"
            "reason_code,evidence_kind,evidence_id,recorded_at_utc,command_id"
            ") VALUES (?,?,'submission_accepted',?,NULL,NULL,?,?,?,?)",
            (
                submission_event_id,
                fault_tag_id,
                effective_submission_at_utc,
                evidence_kind,
                evidence_id,
                now,
                command_id,
            ),
        )
        receiver_snapshot = pickup_context.get("receiver_snapshot")
        connection.execute(
            "INSERT INTO fault_tag_submission_snapshots("
            "fault_tag_submission_snapshot_id,fault_tag_id,submission_event_id,tracking_id,"
            "return_method,pickup_dispatch_location_id,pickup_location_name_snapshot,"
            "pickup_location_address_snapshot,pickup_contact_id,pickup_contact_snapshot_json,"
            "pickup_instructions_snapshot,recipient_context_json,effective_submission_at_utc,"
            "recorded_at_utc,snapshot_hash"
            ") VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (
                snapshot_id,
                fault_tag_id,
                submission_event_id,
                str(current[1]),
                str(current[2]),
                pickup_context["dispatch_location_id"],
                pickup_context["location_name_snapshot"],
                pickup_context["location_address_snapshot"],
                pickup_context["receiver_contact_id"],
                None
                if receiver_snapshot is None
                else canonical_json_bytes(receiver_snapshot).decode("utf-8"),
                None if current[5] is None else str(current[5]),
                None,
                effective_submission_at_utc,
                now,
                snapshot_hash,
            ),
        )

        submitted_events: list[str] = []
        membership_snapshot_ids: list[str] = []
        for membership_snapshot_id, member, display in membership_snapshot_rows:
            membership_id = str(member["fault_tag_membership_id"])
            connection.execute(
                "INSERT INTO fault_tag_membership_submission_snapshots("
                "membership_snapshot_id,fault_tag_submission_snapshot_id,"
                "fault_tag_membership_id,rma_id,device_part_unit_id,spare_part_unit_id,"
                "physical_consequence_id,return_reason,display_snapshot_json"
                ") VALUES (?,?,?,?,?,?,?,?,?)",
                (
                    membership_snapshot_id,
                    snapshot_id,
                    membership_id,
                    str(member["rma_id"]),
                    member["device_part_unit_id"],
                    member["spare_part_unit_id"],
                    str(member["physical_consequence_id"]),
                    str(member["return_reason"]),
                    canonical_json_bytes(display).decode("utf-8"),
                ),
            )
            membership_event_id = new_uuid4()
            connection.execute(
                "INSERT INTO fault_tag_membership_events("
                "membership_event_id,fault_tag_membership_id,event_kind,effective_at_utc,"
                "target_event_id,reason_code,evidence_kind,evidence_id,recorded_at_utc,command_id"
                ") VALUES (?,?,'submitted',?,NULL,NULL,?,?,?,?)",
                (
                    membership_event_id,
                    membership_id,
                    effective_submission_at_utc,
                    evidence_kind,
                    evidence_id,
                    now,
                    command_id,
                ),
            )
            new_revision = int(member["revision"]) + 1
            member_fingerprint = cls.membership_fingerprint(
                membership_id=membership_id,
                fault_tag_id=fault_tag_id,
                rma_id=str(member["rma_id"]),
                device_part_unit_id=member["device_part_unit_id"],
                spare_part_unit_id=member["spare_part_unit_id"],
                state="submitted_awaiting_receipt",
                active_submitted=True,
                revision=new_revision,
                last_event_id=membership_event_id,
            )
            updated = connection.execute(
                "UPDATE fault_tag_membership_current SET state='submitted_awaiting_receipt',"
                "active_submitted=1,revision=?,input_fingerprint=?,last_event_id=?,last_command_id=? "
                "WHERE fault_tag_membership_id=? AND revision=? AND state='draft'",
                (
                    new_revision,
                    member_fingerprint,
                    membership_event_id,
                    command_id,
                    membership_id,
                    int(member["revision"]),
                ),
            )
            if updated.rowcount != 1:
                raise SomaError("INV_STALE", "Fault Tag membership changed during submission")

            rma = InventoryRmasRepository.current_rma(connection, str(member["rma_id"]))
            if rma is None:
                raise SomaError("INV_STALE", "RMA disappeared during Fault Tag submission")
            rma_revision = int(rma[12]) + 1
            rma_fp = InventoryRmasRepository.rma_lifecycle_fingerprint(
                rma_id=str(member["rma_id"]),
                current_c10=str(rma[4]),
                state="fault_tagged",
                target_device_part_unit_id=None if rma[6] is None else str(rma[6]),
                direct_inbound_spare_part_unit_id=None if rma[7] is None else str(rma[7]),
                return_device_part_unit_id=None if rma[8] is None else str(rma[8]),
                return_spare_part_unit_id=None if rma[9] is None else str(rma[9]),
                return_obligation_open=bool(rma[10]),
                active_fault_tag_membership_id=membership_id,
            )
            updated_rma = connection.execute(
                "UPDATE rma_lifecycle_projection SET state='fault_tagged',"
                "active_fault_tag_membership_id=?,revision=?,input_fingerprint=?,last_command_id=? "
                "WHERE rma_id=? AND revision=?",
                (
                    membership_id,
                    rma_revision,
                    rma_fp,
                    command_id,
                    str(member["rma_id"]),
                    int(rma[12]),
                ),
            )
            if updated_rma.rowcount != 1:
                raise SomaError("INV_STALE", "RMA lifecycle changed during Fault Tag submission")
            submitted_events.append(membership_event_id)
            membership_snapshot_ids.append(membership_snapshot_id)

        tag_revision = int(current[15]) + 1
        tag_fp = cls.tag_fingerprint(
            connection,
            fault_tag_id=fault_tag_id,
            state="submitted",
            archived=bool(current[8]),
            current_submission_snapshot_id=snapshot_id,
            submitted_member_count=len(members),
            awaiting_receipt_count=len(members),
            awaiting_final_count=0,
            accepted_count=0,
            rejected_count=0,
        )
        updated_tag = connection.execute(
            "UPDATE fault_tag_current_projection SET state='submitted',"
            "current_submission_snapshot_id=?,submitted_member_count=?,"
            "awaiting_receipt_count=?,awaiting_final_count=0,accepted_count=0,"
            "rejected_count=0,revision=?,input_fingerprint=?,last_command_id=? "
            "WHERE fault_tag_id=? AND revision=? AND state='draft'",
            (
                snapshot_id,
                len(members),
                len(members),
                tag_revision,
                tag_fp,
                command_id,
                fault_tag_id,
                int(current[15]),
            ),
        )
        if updated_tag.rowcount != 1:
            raise SomaError("INV_STALE", "Fault Tag changed during submission")
        return {
            "submission_event_id": submission_event_id,
            "submission_snapshot_id": snapshot_id,
            "membership_snapshot_ids": tuple(membership_snapshot_ids),
            "membership_event_ids": tuple(submitted_events),
            "snapshot_hash": snapshot_hash,
            "revision": tag_revision,
        }


    @staticmethod
    def current_membership(connection: Any, membership_id: str):
        return connection.execute(
            "SELECT m.fault_tag_membership_id,m.fault_tag_id,m.rma_id,"
            "m.physical_consequence_id,m.device_part_unit_id,m.spare_part_unit_id,"
            "m.return_reason,c.state,c.active_submitted,c.revision,c.input_fingerprint,"
            "c.last_event_id FROM fault_tag_memberships m "
            "JOIN fault_tag_membership_current c "
            "ON c.fault_tag_membership_id=m.fault_tag_membership_id "
            "WHERE m.fault_tag_membership_id=?",
            (membership_id,),
        ).fetchone()

    @classmethod
    def _require_warehouse_member(
        cls,
        connection: Any,
        *,
        membership_id: str,
        expected_revision: int,
        expected_state: str,
    ):
        member = cls.current_membership(connection, membership_id)
        if member is None or int(member[9]) != expected_revision:
            raise SomaError("INV_STALE", "Fault Tag membership revision changed")
        if str(member[7]) != expected_state:
            if expected_state == "warehouse_received":
                raise SomaError(
                    "WAREHOUSE_RECEIPT_REQUIRED",
                    "Fault Tag membership has no current warehouse receipt",
                )
            raise SomaError(
                "BULK_INCOMPATIBLE",
                "Fault Tag membership is not eligible for this warehouse transition",
            )
        if not bool(member[8]):
            raise SomaError(
                "BULK_INCOMPATIBLE",
                "Fault Tag membership is no longer active-submitted",
            )
        obligation = connection.execute(
            "SELECT obligation_state,device_part_unit_id,spare_part_unit_id,"
            "physical_consequence_id,revision,last_event_id "
            "FROM rma_return_obligation_current WHERE rma_id=?",
            (str(member[2]),),
        ).fetchone()
        if obligation is None or str(obligation[0]) != "open":
            raise SomaError(
                "BULK_INCOMPATIBLE",
                "RMA return obligation is not open",
            )
        if (
            (None if obligation[1] is None else str(obligation[1]))
            != (None if member[4] is None else str(member[4]))
            or (None if obligation[2] is None else str(obligation[2]))
            != (None if member[5] is None else str(member[5]))
            or obligation[3] is None
            or str(obligation[3]) != str(member[3])
        ):
            raise SomaError(
                "RETURN_SELECTION_INVALID",
                "Fault Tag membership no longer matches the RMA return obligation",
            )
        return member, obligation

    @classmethod
    def _rebuild_tag_after_warehouse(
        cls,
        connection: Any,
        *,
        fault_tag_id: str,
        command_id: str,
    ) -> int:
        current = cls.current_tag(connection, fault_tag_id)
        if current is None:
            raise IntegrityFailure("Fault Tag disappeared during warehouse rebuild")
        if current[9] is None:
            raise IntegrityFailure("warehouse Fault Tag has no current submission snapshot")
        rows = connection.execute(
            "SELECT state,COUNT(*) FROM fault_tag_membership_current "
            "WHERE fault_tag_id=? GROUP BY state",
            (fault_tag_id,),
        ).fetchall()
        counts = {str(row[0]): int(row[1]) for row in rows}
        awaiting_receipt = counts.get("submitted_awaiting_receipt", 0)
        awaiting_final = counts.get("warehouse_received", 0)
        accepted = counts.get("accepted", 0)
        rejected = counts.get("rejected", 0)
        terminal_other = counts.get("cancelled", 0) + counts.get("superseded", 0)
        submitted_count = int(current[10])

        if awaiting_final > 0:
            state = "in_warehouse_review"
        elif awaiting_receipt > 0:
            state = "submitted"
        elif accepted + rejected + terminal_other >= submitted_count:
            state = "terminal_with_rejected" if rejected > 0 else "terminal_completed"
        else:
            raise IntegrityFailure("Fault Tag warehouse aggregate cannot be reduced")

        revision = int(current[15]) + 1
        fingerprint = cls.tag_fingerprint(
            connection,
            fault_tag_id=fault_tag_id,
            state=state,
            archived=bool(current[8]),
            current_submission_snapshot_id=str(current[9]),
            submitted_member_count=submitted_count,
            awaiting_receipt_count=awaiting_receipt,
            awaiting_final_count=awaiting_final,
            accepted_count=accepted,
            rejected_count=rejected,
        )
        updated = connection.execute(
            "UPDATE fault_tag_current_projection SET state=?,awaiting_receipt_count=?,"
            "awaiting_final_count=?,accepted_count=?,rejected_count=?,revision=?,"
            "input_fingerprint=?,last_command_id=? WHERE fault_tag_id=? AND revision=?",
            (
                state,
                awaiting_receipt,
                awaiting_final,
                accepted,
                rejected,
                revision,
                fingerprint,
                command_id,
                fault_tag_id,
                int(current[15]),
            ),
        )
        if updated.rowcount != 1:
            raise SomaError("INV_STALE", "Fault Tag changed during warehouse rebuild")
        return revision

    @staticmethod
    def _update_rma_warehouse_state(
        connection: Any,
        *,
        rma_id: str,
        state: str,
        active_membership_id: str | None,
        return_obligation_open: bool,
        command_id: str,
    ) -> int:
        rma = InventoryRmasRepository.current_rma(connection, rma_id)
        if rma is None:
            raise SomaError("INV_STALE", "RMA disappeared during warehouse transition")
        revision = int(rma[12]) + 1
        fingerprint = InventoryRmasRepository.rma_lifecycle_fingerprint(
            rma_id=rma_id,
            current_c10=str(rma[4]),
            state=state,
            target_device_part_unit_id=None if rma[6] is None else str(rma[6]),
            direct_inbound_spare_part_unit_id=None if rma[7] is None else str(rma[7]),
            return_device_part_unit_id=None if rma[8] is None else str(rma[8]),
            return_spare_part_unit_id=None if rma[9] is None else str(rma[9]),
            return_obligation_open=return_obligation_open,
            active_fault_tag_membership_id=active_membership_id,
        )
        updated = connection.execute(
            "UPDATE rma_lifecycle_projection SET state=?,return_obligation_open=?,"
            "active_fault_tag_membership_id=?,revision=?,input_fingerprint=?,"
            "last_command_id=? WHERE rma_id=? AND revision=?",
            (
                state,
                1 if return_obligation_open else 0,
                active_membership_id,
                revision,
                fingerprint,
                command_id,
                rma_id,
                int(rma[12]),
            ),
        )
        if updated.rowcount != 1:
            raise SomaError("INV_STALE", "RMA lifecycle changed during warehouse transition")
        return revision

    @classmethod
    def record_warehouse_receipt(
        cls,
        connection: Any,
        *,
        targets: tuple[tuple[str, int], ...],
        effective_at_utc: int | None,
        evidence_kind: str | None,
        evidence_id: str | None,
        command_id: str,
    ) -> dict[str, object]:
        preflight = [
            cls._require_warehouse_member(
                connection,
                membership_id=membership_id,
                expected_revision=revision,
                expected_state="submitted_awaiting_receipt",
            )
            for membership_id, revision in targets
        ]
        batch_id: str | None = None
        now = utc_epoch_seconds()
        if force_batch or len(targets) > 1:
            batch_id = new_uuid4()
            connection.execute(
                "INSERT INTO inventory_lifecycle_batches("
                "inventory_batch_id,batch_kind,target_count,recorded_at_utc,command_id"
                ") VALUES (?,'manual_bulk',?,?,?)",
                (batch_id, len(targets), now, command_id),
            )

        events: list[dict[str, object]] = []
        touched_tags: set[str] = set()
        for (membership_id, _expected_revision), (member, obligation) in zip(targets, preflight):
            event_id = new_uuid4()
            connection.execute(
                "INSERT INTO fault_tag_membership_events("
                "membership_event_id,fault_tag_membership_id,event_kind,effective_at_utc,"
                "target_event_id,reason_code,evidence_kind,evidence_id,recorded_at_utc,command_id"
                ") VALUES (?,?,'warehouse_received',?,?,NULL,?,?,?,?)",
                (
                    event_id,
                    membership_id,
                    effective_at_utc,
                    member[11],
                    evidence_kind,
                    evidence_id,
                    now,
                    command_id,
                ),
            )
            revision = int(member[9]) + 1
            fingerprint = cls.membership_fingerprint(
                membership_id=membership_id,
                fault_tag_id=str(member[1]),
                rma_id=str(member[2]),
                device_part_unit_id=None if member[4] is None else str(member[4]),
                spare_part_unit_id=None if member[5] is None else str(member[5]),
                state="warehouse_received",
                active_submitted=True,
                revision=revision,
                last_event_id=event_id,
            )
            updated = connection.execute(
                "UPDATE fault_tag_membership_current SET state='warehouse_received',"
                "revision=?,input_fingerprint=?,last_event_id=?,last_command_id=? "
                "WHERE fault_tag_membership_id=? AND revision=? "
                "AND state='submitted_awaiting_receipt' AND active_submitted=1",
                (
                    revision,
                    fingerprint,
                    event_id,
                    command_id,
                    membership_id,
                    int(member[9]),
                ),
            )
            if updated.rowcount != 1:
                raise SomaError("INV_STALE", "Fault Tag membership changed during warehouse receipt")
            rma_revision = cls._update_rma_warehouse_state(
                connection,
                rma_id=str(member[2]),
                state="warehouse_received",
                active_membership_id=membership_id,
                return_obligation_open=True,
                command_id=command_id,
            )
            connection.execute(
                "DELETE FROM inventory_attention_projection "
                "WHERE target_kind='rma' AND target_id=? "
                "AND attention_kind='warehouse_final_decision_pending'",
                (str(member[2]),),
            )
            attention_id = new_uuid4()
            attention_fp = sha256_canonical_json(
                {
                    "schema": "SOMA_INVENTORY_ATTENTION_V1",
                    "target_kind": "rma",
                    "target_id": str(member[2]),
                    "attention_kind": "warehouse_final_decision_pending",
                    "fault_tag_membership_id": membership_id,
                }
            )
            connection.execute(
                "INSERT INTO inventory_attention_projection("
                "attention_id,target_kind,target_id,attention_kind,severity,"
                "input_fingerprint,last_command_id"
                ") VALUES (?,'rma',?,'warehouse_final_decision_pending',"
                "'action_required',?,?)",
                (attention_id, str(member[2]), attention_fp, command_id),
            )
            touched_tags.add(str(member[1]))
            events.append(
                {
                    "membership_id": membership_id,
                    "membership_event_id": event_id,
                    "rma_id": str(member[2]),
                    "return_obligation_revision": int(obligation[4]),
                    "membership_revision": revision,
                    "rma_revision": rma_revision,
                }
            )

        tag_revisions = {
            tag_id: cls._rebuild_tag_after_warehouse(
                connection,
                fault_tag_id=tag_id,
                command_id=command_id,
            )
            for tag_id in sorted(touched_tags)
        }
        return {
            "batch_id": batch_id,
            "events": tuple(events),
            "tag_revisions": tag_revisions,
        }

    @classmethod
    def record_warehouse_final_decision(
        cls,
        connection: Any,
        *,
        targets: tuple[tuple[str, int], ...],
        decision: str,
        reason_code: str | None,
        effective_at_utc: int | None,
        evidence_kind: str | None,
        evidence_id: str | None,
        command_id: str,
        force_batch: bool = False,
    ) -> dict[str, object]:
        preflight = [
            cls._require_warehouse_member(
                connection,
                membership_id=membership_id,
                expected_revision=revision,
                expected_state="warehouse_received",
            )
            for membership_id, revision in targets
        ]
        batch_id: str | None = None
        now = utc_epoch_seconds()
        if force_batch or len(targets) > 1:
            batch_id = new_uuid4()
            connection.execute(
                "INSERT INTO inventory_lifecycle_batches("
                "inventory_batch_id,batch_kind,target_count,recorded_at_utc,command_id"
                ") VALUES (?,'manual_bulk',?,?,?)",
                (batch_id, len(targets), now, command_id),
            )

        events: list[dict[str, object]] = []
        touched_tags: set[str] = set()
        for (membership_id, _expected_revision), (member, obligation) in zip(targets, preflight):
            rma_id = str(member[2])
            membership_event_id = new_uuid4()
            event_kind = "warehouse_accepted" if decision == "accepted" else "warehouse_rejected"
            connection.execute(
                "INSERT INTO fault_tag_membership_events("
                "membership_event_id,fault_tag_membership_id,event_kind,effective_at_utc,"
                "target_event_id,reason_code,evidence_kind,evidence_id,recorded_at_utc,command_id"
                ") VALUES (?,?,?,?,?,?,?,?,?,?)",
                (
                    membership_event_id,
                    membership_id,
                    event_kind,
                    effective_at_utc,
                    member[11],
                    reason_code,
                    evidence_kind,
                    evidence_id,
                    now,
                    command_id,
                ),
            )
            membership_revision = int(member[9]) + 1
            member_state = "accepted" if decision == "accepted" else "rejected"
            member_fp = cls.membership_fingerprint(
                membership_id=membership_id,
                fault_tag_id=str(member[1]),
                rma_id=rma_id,
                device_part_unit_id=None if member[4] is None else str(member[4]),
                spare_part_unit_id=None if member[5] is None else str(member[5]),
                state=member_state,
                active_submitted=False,
                revision=membership_revision,
                last_event_id=membership_event_id,
            )
            updated_member = connection.execute(
                "UPDATE fault_tag_membership_current SET state=?,active_submitted=0,"
                "revision=?,input_fingerprint=?,last_event_id=?,last_command_id=? "
                "WHERE fault_tag_membership_id=? AND revision=? "
                "AND state='warehouse_received' AND active_submitted=1",
                (
                    member_state,
                    membership_revision,
                    member_fp,
                    membership_event_id,
                    command_id,
                    membership_id,
                    int(member[9]),
                ),
            )
            if updated_member.rowcount != 1:
                raise SomaError("INV_STALE", "Fault Tag membership changed during final decision")

            return_event_id = new_uuid4()
            obligation_revision = int(obligation[4]) + 1
            if decision == "accepted":
                connection.execute(
                    "INSERT INTO rma_return_selection_events("
                    "return_selection_event_id,rma_id,physical_consequence_id,event_kind,"
                    "device_part_unit_id,spare_part_unit_id,reason_code,effective_at_utc,"
                    "target_event_id,recorded_at_utc,command_id"
                    ") VALUES (?,?,?,'close',NULL,NULL,NULL,?,?,?,?)",
                    (
                        return_event_id,
                        rma_id,
                        str(member[3]),
                        effective_at_utc,
                        obligation[5],
                        now,
                        command_id,
                    ),
                )
                obligation_state = "closed_accepted"
                rma_state = "closed_accepted"
                obligation_open = False
            else:
                connection.execute(
                    "INSERT INTO rma_return_selection_events("
                    "return_selection_event_id,rma_id,physical_consequence_id,event_kind,"
                    "device_part_unit_id,spare_part_unit_id,reason_code,effective_at_utc,"
                    "target_event_id,recorded_at_utc,command_id"
                    ") VALUES (?,?,?,'reopen_after_rejection',?,?,?,?,?,?,?)",
                    (
                        return_event_id,
                        rma_id,
                        str(member[3]),
                        obligation[1],
                        obligation[2],
                        reason_code,
                        effective_at_utc,
                        obligation[5],
                        now,
                        command_id,
                    ),
                )
                obligation_state = "open"
                rma_state = "return_rejected"
                obligation_open = True

            updated_obligation = connection.execute(
                "UPDATE rma_return_obligation_current SET obligation_state=?,revision=?,"
                "last_event_id=?,last_command_id=? WHERE rma_id=? AND revision=?",
                (
                    obligation_state,
                    obligation_revision,
                    return_event_id,
                    command_id,
                    rma_id,
                    int(obligation[4]),
                ),
            )
            if updated_obligation.rowcount != 1:
                raise SomaError("INV_STALE", "RMA return obligation changed during final decision")
            rma_revision = cls._update_rma_warehouse_state(
                connection,
                rma_id=rma_id,
                state=rma_state,
                active_membership_id=None,
                return_obligation_open=obligation_open,
                command_id=command_id,
            )
            connection.execute(
                "DELETE FROM inventory_attention_projection "
                "WHERE target_kind='rma' AND target_id=? "
                "AND attention_kind='warehouse_final_decision_pending'",
                (rma_id,),
            )
            if decision == "accepted":
                connection.execute(
                    "DELETE FROM inventory_attention_projection "
                    "WHERE target_kind='rma' AND target_id=? "
                    "AND attention_kind IN "
                    "('return_obligation_open','warehouse_rejected_resend_required')",
                    (rma_id,),
                )
            else:
                connection.execute(
                    "DELETE FROM inventory_attention_projection "
                    "WHERE target_kind='rma' AND target_id=? "
                    "AND attention_kind='warehouse_rejected_resend_required'",
                    (rma_id,),
                )
                attention_id = new_uuid4()
                attention_fp = sha256_canonical_json(
                    {
                        "schema": "SOMA_INVENTORY_ATTENTION_V1",
                        "target_kind": "rma",
                        "target_id": rma_id,
                        "attention_kind": "warehouse_rejected_resend_required",
                        "fault_tag_membership_id": membership_id,
                    }
                )
                connection.execute(
                    "INSERT INTO inventory_attention_projection("
                    "attention_id,target_kind,target_id,attention_kind,severity,"
                    "input_fingerprint,last_command_id"
                    ") VALUES (?,'rma',?,'warehouse_rejected_resend_required',"
                    "'action_required',?,?)",
                    (attention_id, rma_id, attention_fp, command_id),
                )

            touched_tags.add(str(member[1]))
            events.append(
                {
                    "membership_id": membership_id,
                    "membership_event_id": membership_event_id,
                    "rma_id": rma_id,
                    "return_event_id": return_event_id,
                    "membership_revision": membership_revision,
                    "obligation_revision": obligation_revision,
                    "rma_revision": rma_revision,
                }
            )

        tag_revisions = {
            tag_id: cls._rebuild_tag_after_warehouse(
                connection,
                fault_tag_id=tag_id,
                command_id=command_id,
            )
            for tag_id in sorted(touched_tags)
        }
        return {
            "batch_id": batch_id,
            "events": tuple(events),
            "tag_revisions": tag_revisions,
        }


    @classmethod
    def lineage_authority(cls, connection: Any, fault_tag_id: str) -> dict[str, object]:
        current = cls.current_tag(connection, fault_tag_id)
        if current is None:
            raise SomaError("INV_STALE", "Fault Tag no longer exists")
        rows = connection.execute(
            "SELECT relation_type,predecessor_fault_tag_id,successor_fault_tag_id,"
            "fault_tag_lineage_id FROM fault_tag_lineage "
            "WHERE predecessor_fault_tag_id=? OR successor_fault_tag_id=? "
            "ORDER BY relation_type,predecessor_fault_tag_id,successor_fault_tag_id,"
            "fault_tag_lineage_id",
            (fault_tag_id, fault_tag_id),
        ).fetchall()
        authority = {
            "schema": "SOMA_FAULT_TAG_LINEAGE_AUTHORITY_V1",
            "fault_tag_id": fault_tag_id,
            "state": str(current[7]),
            "projection_revision": int(current[15]),
            "projection_fingerprint": str(current[16]),
            "lineage": [
                {
                    "relation_type": str(row[0]),
                    "predecessor_fault_tag_id": str(row[1]),
                    "successor_fault_tag_id": str(row[2]),
                    "fault_tag_lineage_id": str(row[3]),
                }
                for row in rows
            ],
        }
        return authority | {"fingerprint": sha256_canonical_json(authority)}

    @classmethod
    def _supersede_for_replacement(
        cls,
        connection: Any,
        *,
        predecessor_fault_tag_id: str,
        reason_code: str,
        command_id: str,
    ) -> int:
        current = cls.current_tag(connection, predecessor_fault_tag_id)
        if current is None:
            raise SomaError("INV_STALE", "Fault Tag no longer exists")
        if str(current[7]) not in {"submitted", "in_warehouse_review"}:
            raise SomaError(
                "REPLACEMENT_LINEAGE_CONFLICT",
                "Fault Tag is not an active submitted replacement predecessor",
            )
        if connection.execute(
            "SELECT 1 FROM fault_tag_lineage WHERE predecessor_fault_tag_id=? "
            "AND relation_type='corrects_replaces' LIMIT 1",
            (predecessor_fault_tag_id,),
        ).fetchone() is not None:
            raise SomaError(
                "REPLACEMENT_LINEAGE_CONFLICT",
                "Fault Tag already has a correction successor",
            )

        members = cls.current_members(connection, predecessor_fault_tag_id)
        if any(member["state"] in {"accepted", "rejected"} for member in members):
            raise SomaError(
                "REPLACEMENT_LINEAGE_CONFLICT",
                "Final warehouse history requires a later operational workflow, not submitted replacement",
            )
        now = utc_epoch_seconds()
        for member in members:
            if member["state"] not in {"submitted_awaiting_receipt", "warehouse_received"}:
                continue
            membership_id = str(member["fault_tag_membership_id"])
            event_id = new_uuid4()
            connection.execute(
                "INSERT INTO fault_tag_membership_events("
                "membership_event_id,fault_tag_membership_id,event_kind,effective_at_utc,"
                "target_event_id,reason_code,evidence_kind,evidence_id,recorded_at_utc,command_id"
                ") VALUES (?,?,'superseded',NULL,?,?,NULL,NULL,?,?)",
                (
                    event_id,
                    membership_id,
                    member["last_event_id"],
                    reason_code,
                    now,
                    command_id,
                ),
            )
            revision = int(member["revision"]) + 1
            fingerprint = cls.membership_fingerprint(
                membership_id=membership_id,
                fault_tag_id=predecessor_fault_tag_id,
                rma_id=str(member["rma_id"]),
                device_part_unit_id=member["device_part_unit_id"],
                spare_part_unit_id=member["spare_part_unit_id"],
                state="superseded",
                active_submitted=False,
                revision=revision,
                last_event_id=event_id,
            )
            updated = connection.execute(
                "UPDATE fault_tag_membership_current SET state='superseded',"
                "active_submitted=0,revision=?,input_fingerprint=?,last_event_id=?,"
                "last_command_id=? WHERE fault_tag_membership_id=? AND revision=?",
                (
                    revision,
                    fingerprint,
                    event_id,
                    command_id,
                    membership_id,
                    int(member["revision"]),
                ),
            )
            if updated.rowcount != 1:
                raise SomaError("INV_STALE", "Fault Tag membership changed during replacement")

            rma = InventoryRmasRepository.current_rma(connection, str(member["rma_id"]))
            if rma is None:
                raise SomaError("INV_STALE", "RMA disappeared during Fault Tag replacement")
            if rma[11] is not None and str(rma[11]) == membership_id:
                rma_revision = int(rma[12]) + 1
                rma_fp = InventoryRmasRepository.rma_lifecycle_fingerprint(
                    rma_id=str(member["rma_id"]),
                    current_c10=str(rma[4]),
                    state="return_open",
                    target_device_part_unit_id=None if rma[6] is None else str(rma[6]),
                    direct_inbound_spare_part_unit_id=None if rma[7] is None else str(rma[7]),
                    return_device_part_unit_id=None if rma[8] is None else str(rma[8]),
                    return_spare_part_unit_id=None if rma[9] is None else str(rma[9]),
                    return_obligation_open=True,
                    active_fault_tag_membership_id=None,
                )
                changed_rma = connection.execute(
                    "UPDATE rma_lifecycle_projection SET state='return_open',"
                    "active_fault_tag_membership_id=NULL,revision=?,input_fingerprint=?,"
                    "last_command_id=? WHERE rma_id=? AND revision=?",
                    (
                        rma_revision,
                        rma_fp,
                        command_id,
                        str(member["rma_id"]),
                        int(rma[12]),
                    ),
                )
                if changed_rma.rowcount != 1:
                    raise SomaError("INV_STALE", "RMA changed during Fault Tag replacement")
            connection.execute(
                "DELETE FROM inventory_attention_projection "
                "WHERE target_kind='rma' AND target_id=? "
                "AND attention_kind='warehouse_final_decision_pending'",
                (str(member["rma_id"]),),
            )

        target_event_id = None
        if current[9] is not None:
            row = connection.execute(
                "SELECT submission_event_id FROM fault_tag_submission_snapshots "
                "WHERE fault_tag_submission_snapshot_id=?",
                (str(current[9]),),
            ).fetchone()
            target_event_id = None if row is None else str(row[0])
        lifecycle_event_id = new_uuid4()
        connection.execute(
            "INSERT INTO fault_tag_lifecycle_events("
            "fault_tag_event_id,fault_tag_id,event_kind,effective_at_utc,target_event_id,"
            "reason_code,evidence_kind,evidence_id,recorded_at_utc,command_id"
            ") VALUES (?,?,'superseded',NULL,?,?,NULL,NULL,?,?)",
            (
                lifecycle_event_id,
                predecessor_fault_tag_id,
                target_event_id,
                reason_code,
                now,
                command_id,
            ),
        )
        revision = int(current[15]) + 1
        fingerprint = cls.tag_fingerprint(
            connection,
            fault_tag_id=predecessor_fault_tag_id,
            state="superseded",
            archived=bool(current[8]),
            current_submission_snapshot_id=None if current[9] is None else str(current[9]),
            submitted_member_count=int(current[10]),
            awaiting_receipt_count=0,
            awaiting_final_count=0,
            accepted_count=int(current[13]),
            rejected_count=int(current[14]),
        )
        updated_tag = connection.execute(
            "UPDATE fault_tag_current_projection SET state='superseded',"
            "awaiting_receipt_count=0,awaiting_final_count=0,revision=?,"
            "input_fingerprint=?,last_command_id=? WHERE fault_tag_id=? AND revision=?",
            (
                revision,
                fingerprint,
                command_id,
                predecessor_fault_tag_id,
                int(current[15]),
            ),
        )
        if updated_tag.rowcount != 1:
            raise SomaError("INV_STALE", "Fault Tag changed during replacement")
        return revision

    @classmethod
    def create_replacement(
        cls,
        connection: Any,
        *,
        predecessor_fault_tag_id: str,
        expected_predecessor_revision: int,
        expected_lineage_fingerprint: str,
        successor_fault_tag_id: str,
        return_method: str,
        pickup_dispatch_location_id: str | None,
        pickup_contact_id: str | None,
        pickup_instructions: str | None,
        memberships: tuple[FaultTagMembershipIntent, ...],
        reason_code: str,
        command_id: str,
    ) -> dict[str, object]:
        authority = cls.lineage_authority(connection, predecessor_fault_tag_id)
        if (
            int(authority["projection_revision"]) != expected_predecessor_revision
            or str(authority["fingerprint"]) != expected_lineage_fingerprint
        ):
            raise SomaError("INV_STALE", "Fault Tag replacement authority changed")
        predecessor_revision = cls._supersede_for_replacement(
            connection,
            predecessor_fault_tag_id=predecessor_fault_tag_id,
            reason_code=reason_code,
            command_id=command_id,
        )
        created = cls.create_draft(
            connection,
            fault_tag_id=successor_fault_tag_id,
            return_method=return_method,
            pickup_dispatch_location_id=pickup_dispatch_location_id,
            pickup_contact_id=pickup_contact_id,
            pickup_instructions=pickup_instructions,
            memberships=memberships,
            command_id=command_id,
        )
        lineage_id = new_uuid4()
        connection.execute(
            "INSERT INTO fault_tag_lineage("
            "fault_tag_lineage_id,relation_type,predecessor_fault_tag_id,"
            "successor_fault_tag_id,reason_code,recorded_at_utc,command_id"
            ") VALUES (?,'corrects_replaces',?,?,?,?,?)",
            (
                lineage_id,
                predecessor_fault_tag_id,
                successor_fault_tag_id,
                reason_code,
                utc_epoch_seconds(),
                command_id,
            ),
        )
        scope_fingerprint = sha256_canonical_json(
            {
                "schema": "SOMA_FAULT_TAG_LINEAGE_SCOPE_V1",
                "relation_type": "corrects_replaces",
                "predecessor_fault_tag_id": predecessor_fault_tag_id,
                "successor_fault_tag_id": successor_fault_tag_id,
                "rma_ids": [item.rma_id for item in memberships],
            }
        )
        return {
            **created,
            "lineage_id": lineage_id,
            "predecessor_revision": predecessor_revision,
            "membership_scope_fingerprint": scope_fingerprint,
        }

    @classmethod
    def create_resend(
        cls,
        connection: Any,
        *,
        predecessor_fault_tag_id: str,
        expected_lineage_fingerprint: str,
        successor_fault_tag_id: str,
        return_method: str,
        pickup_dispatch_location_id: str | None,
        pickup_contact_id: str | None,
        pickup_instructions: str | None,
        memberships: tuple[FaultTagMembershipIntent, ...],
        reason_code: str,
        command_id: str,
    ) -> dict[str, object]:
        authority = cls.lineage_authority(connection, predecessor_fault_tag_id)
        if str(authority["fingerprint"]) != expected_lineage_fingerprint:
            raise SomaError("INV_STALE", "Fault Tag resend authority changed")
        predecessor = cls.current_tag(connection, predecessor_fault_tag_id)
        if predecessor is None:
            raise SomaError("INV_STALE", "Fault Tag no longer exists")
        selected_rmas = {item.rma_id for item in memberships}
        if not selected_rmas:
            raise SomaError("RESEND_NOT_ELIGIBLE", "Resend requires at least one rejected obligation")

        rejected_rows = connection.execute(
            "SELECT c.rma_id FROM fault_tag_membership_current c "
            "WHERE c.fault_tag_id=? AND c.state='rejected'",
            (predecessor_fault_tag_id,),
        ).fetchall()
        rejected_rmas = {str(row[0]) for row in rejected_rows}
        if not selected_rmas.issubset(rejected_rmas):
            raise SomaError(
                "RESEND_NOT_ELIGIBLE",
                "Selected resend scope is not rejected predecessor membership",
            )
        existing_scope = {
            str(row[0])
            for row in connection.execute(
                "SELECT m.rma_id FROM fault_tag_lineage l "
                "JOIN fault_tag_memberships m ON m.fault_tag_id=l.successor_fault_tag_id "
                "WHERE l.predecessor_fault_tag_id=? AND l.relation_type='resend_of'",
                (predecessor_fault_tag_id,),
            ).fetchall()
        }
        if selected_rmas & existing_scope:
            raise SomaError(
                "RESEND_NOT_ELIGIBLE",
                "Selected rejected obligation already belongs to a resend attempt",
            )
        for item in memberships:
            cls.require_membership_available(connection, rma_id=item.rma_id)

        created = cls.create_draft(
            connection,
            fault_tag_id=successor_fault_tag_id,
            return_method=return_method,
            pickup_dispatch_location_id=pickup_dispatch_location_id,
            pickup_contact_id=pickup_contact_id,
            pickup_instructions=pickup_instructions,
            memberships=memberships,
            command_id=command_id,
        )
        lineage_id = new_uuid4()
        connection.execute(
            "INSERT INTO fault_tag_lineage("
            "fault_tag_lineage_id,relation_type,predecessor_fault_tag_id,"
            "successor_fault_tag_id,reason_code,recorded_at_utc,command_id"
            ") VALUES (?,'resend_of',?,?,?,?,?)",
            (
                lineage_id,
                predecessor_fault_tag_id,
                successor_fault_tag_id,
                reason_code,
                utc_epoch_seconds(),
                command_id,
            ),
        )
        scope_fingerprint = sha256_canonical_json(
            {
                "schema": "SOMA_FAULT_TAG_LINEAGE_SCOPE_V1",
                "relation_type": "resend_of",
                "predecessor_fault_tag_id": predecessor_fault_tag_id,
                "successor_fault_tag_id": successor_fault_tag_id,
                "rma_ids": sorted(selected_rmas),
            }
        )
        return {
            **created,
            "lineage_id": lineage_id,
            "predecessor_revision": int(predecessor[15]),
            "membership_scope_fingerprint": scope_fingerprint,
        }


__all__ = ["InventoryFaultTagsRepository"]
