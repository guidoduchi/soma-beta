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
                    "members": cls._member_payload(connection, fault_tag_id),
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
            "members": cls._member_payload(connection, fault_tag_id),
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
    ) -> dict[str, object]:
        current = cls.require_exact_draft(
            connection,
            fault_tag_id=fault_tag_id,
            expected_revision=expected_revision,
            expected_fingerprint=expected_fingerprint,
        )
        members = cls._member_payload(connection, fault_tag_id)
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


__all__ = ["InventoryFaultTagsRepository"]
