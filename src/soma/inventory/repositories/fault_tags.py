from __future__ import annotations

from typing import Any

from soma.foundation.errors import IntegrityFailure, SomaError
from soma.foundation.identifiers import new_uuid4, utc_epoch_seconds
from soma.foundation.strict_json import sha256_canonical_json


class InventoryFaultTagsRepository:
    @staticmethod
    def allocate_fault_tag_tracking(
        connection: Any,
        command_id: str,
    ) -> tuple[int, str]:
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
        changed = connection.execute(
            "UPDATE inventory_tracking_allocators "
            "SET next_sequence=?,revision=?,last_command_id=? "
            "WHERE allocator_kind='fault_tag' AND next_sequence=? AND revision=?",
            (sequence + 1, revision + 1, command_id, sequence, revision),
        )
        if changed.rowcount != 1:
            raise SomaError("INV_STALE", "Fault Tag allocator changed")
        return sequence, f"FT-{sequence:08d}"

    @staticmethod
    def require_optional_draft_references(
        connection: Any,
        *,
        return_method: str,
        pickup_dispatch_location_id: str | None,
        pickup_contact_id: str | None,
    ) -> None:
        if return_method == "non_pickup":
            if pickup_dispatch_location_id is not None or pickup_contact_id is not None:
                raise SomaError(
                    "FAULT_TAG_PICKUP_ORIGIN_REQUIRED",
                    "Non-pickup Fault Tag cannot carry pickup-origin references",
                )
            return
        if pickup_dispatch_location_id is not None:
            location = connection.execute(
                "SELECT lifecycle_state FROM dispatch_locations WHERE dispatch_location_id=?",
                (pickup_dispatch_location_id,),
            ).fetchone()
            if location is None or str(location[0]) != "active":
                raise SomaError(
                    "FAULT_TAG_PICKUP_ORIGIN_REQUIRED",
                    "Fault Tag pickup-origin Dispatch Location is unavailable",
                )
        if pickup_contact_id is not None:
            contact = connection.execute(
                "SELECT lifecycle_state FROM contacts WHERE contact_id=?",
                (pickup_contact_id,),
            ).fetchone()
            if contact is None or str(contact[0]) != "active":
                raise SomaError(
                    "FAULT_TAG_PICKUP_ORIGIN_REQUIRED",
                    "Fault Tag pickup Contact is unavailable",
                )

    @staticmethod
    def obligation_authority(connection: Any, rma_id: str):
        return connection.execute(
            "SELECT o.obligation_state,o.device_part_unit_id,o.spare_part_unit_id,"
            "o.physical_consequence_id,o.revision,p.state "
            "FROM rma_return_obligation_current o "
            "JOIN rma_lifecycle_projection p ON p.rma_id=o.rma_id "
            "WHERE o.rma_id=?",
            (rma_id,),
        ).fetchone()

    @classmethod
    def require_membership_eligible(
        cls,
        connection: Any,
        *,
        rma_id: str,
        excluding_fault_tag_id: str | None = None,
    ) -> tuple[str, str | None, str | None, int]:
        row = cls.obligation_authority(connection, rma_id)
        if row is None or str(row[0]) != "open" or row[3] is None:
            raise SomaError(
                "RETURN_SELECTION_INVALID",
                "RMA has no current open return obligation selected by physical consequence",
            )
        device_part_unit_id = None if row[1] is None else str(row[1])
        spare_part_unit_id = None if row[2] is None else str(row[2])
        if (device_part_unit_id is None) == (spare_part_unit_id is None):
            raise IntegrityFailure("Open RMA return obligation has invalid typed unit authority")
        physical_consequence_id = str(row[3])
        params: list[object] = [rma_id]
        sql = (
            "SELECT fault_tag_id,fault_tag_membership_id "
            "FROM fault_tag_membership_current "
            "WHERE active_submitted=1 AND (rma_id=?"
        )
        if device_part_unit_id is not None:
            sql += " OR device_part_unit_id=?"
            params.append(device_part_unit_id)
        else:
            sql += " OR spare_part_unit_id=?"
            params.append(spare_part_unit_id)
        sql += ")"
        if excluding_fault_tag_id is not None:
            sql += " AND fault_tag_id<>?"
            params.append(excluding_fault_tag_id)
        conflict = connection.execute(sql, tuple(params)).fetchone()
        if conflict is not None:
            raise SomaError(
                "FAULT_TAG_MEMBERSHIP_CONFLICT",
                "RMA return obligation or selected unit is active in another submitted Fault Tag",
            )
        return (
            physical_consequence_id,
            device_part_unit_id,
            spare_part_unit_id,
            int(row[4]),
        )

    @staticmethod
    def membership_fingerprint(
        *,
        fault_tag_membership_id: str,
        rma_id: str,
        physical_consequence_id: str,
        device_part_unit_id: str | None,
        spare_part_unit_id: str | None,
        return_reason: str,
    ) -> str:
        return sha256_canonical_json(
            {
                "schema": "SOMA_FAULT_TAG_MEMBERSHIP_V1",
                "fault_tag_membership_id": fault_tag_membership_id,
                "rma_id": rma_id,
                "physical_consequence_id": physical_consequence_id,
                "device_part_unit_id": device_part_unit_id,
                "spare_part_unit_id": spare_part_unit_id,
                "return_reason": return_reason,
                "state": "draft",
                "active_submitted": 0,
            }
        )

    @staticmethod
    def projection_fingerprint(
        *,
        fault_tag_id: str,
        return_method: str,
        pickup_dispatch_location_id: str | None,
        pickup_contact_id: str | None,
        pickup_instructions: str | None,
        members: tuple[tuple[str, str, str, str | None, str | None, str], ...],
        archived: int = 0,
    ) -> str:
        return sha256_canonical_json(
            {
                "schema": "SOMA_FAULT_TAG_CURRENT_V1",
                "fault_tag_id": fault_tag_id,
                "state": "draft",
                "archived": archived,
                "current_submission_snapshot_id": None,
                "draft": {
                    "return_method": return_method,
                    "pickup_dispatch_location_id": pickup_dispatch_location_id,
                    "pickup_contact_id": pickup_contact_id,
                    "pickup_instructions": pickup_instructions,
                },
                "members": [
                    {
                        "fault_tag_membership_id": membership_id,
                        "rma_id": rma_id,
                        "physical_consequence_id": consequence_id,
                        "device_part_unit_id": device_id,
                        "spare_part_unit_id": spare_id,
                        "return_reason": reason,
                    }
                    for membership_id, rma_id, consequence_id, device_id, spare_id, reason
                    in members
                ],
            }
        )

    @classmethod
    def _insert_membership(
        cls,
        connection: Any,
        *,
        fault_tag_id: str,
        rma_id: str,
        return_reason: str,
        draft_revision: int,
        command_id: str,
        excluding_fault_tag_id: str | None,
    ) -> tuple[str, str, str | None, str | None, str]:
        (
            physical_consequence_id,
            device_part_unit_id,
            spare_part_unit_id,
            _obligation_revision,
        ) = cls.require_membership_eligible(
            connection,
            rma_id=rma_id,
            excluding_fault_tag_id=excluding_fault_tag_id,
        )
        membership_id = new_uuid4()
        now = utc_epoch_seconds()
        connection.execute(
            "INSERT INTO fault_tag_memberships("
            "fault_tag_membership_id,fault_tag_id,rma_id,physical_consequence_id,"
            "device_part_unit_id,spare_part_unit_id,return_reason,draft_revision,"
            "created_at_utc,created_command_id"
            ") VALUES (?,?,?,?,?,?,?,?,?,?)",
            (
                membership_id,
                fault_tag_id,
                rma_id,
                physical_consequence_id,
                device_part_unit_id,
                spare_part_unit_id,
                return_reason,
                draft_revision,
                now,
                command_id,
            ),
        )
        fingerprint = cls.membership_fingerprint(
            fault_tag_membership_id=membership_id,
            rma_id=rma_id,
            physical_consequence_id=physical_consequence_id,
            device_part_unit_id=device_part_unit_id,
            spare_part_unit_id=spare_part_unit_id,
            return_reason=return_reason,
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
                rma_id,
                device_part_unit_id,
                spare_part_unit_id,
                fingerprint,
                command_id,
            ),
        )
        return (
            membership_id,
            physical_consequence_id,
            device_part_unit_id,
            spare_part_unit_id,
            return_reason,
        )

    @classmethod
    def insert_draft(
        cls,
        connection: Any,
        *,
        fault_tag_id: str,
        tracking_sequence: int,
        tracking_id: str,
        return_method: str,
        pickup_dispatch_location_id: str | None,
        pickup_contact_id: str | None,
        pickup_instructions: str | None,
        memberships: tuple[tuple[str, str], ...],
        command_id: str,
    ) -> tuple[str, tuple[str, ...], int]:
        cls.require_optional_draft_references(
            connection,
            return_method=return_method,
            pickup_dispatch_location_id=pickup_dispatch_location_id,
            pickup_contact_id=pickup_contact_id,
        )
        now = utc_epoch_seconds()
        connection.execute(
            "INSERT INTO fault_tags("
            "fault_tag_id,tracking_sequence,tracking_id,creation_origin,draft_return_method,"
            "draft_pickup_dispatch_location_id,draft_pickup_contact_id,"
            "draft_pickup_instructions,draft_revision,created_at_utc,created_command_id"
            ") VALUES (?,?,?,'manual',?,?,?,?,1,?,?)",
            (
                fault_tag_id,
                tracking_sequence,
                tracking_id,
                return_method,
                pickup_dispatch_location_id,
                pickup_contact_id,
                pickup_instructions,
                now,
                command_id,
            ),
        )
        event_id = new_uuid4()
        connection.execute(
            "INSERT INTO fault_tag_lifecycle_events("
            "fault_tag_event_id,fault_tag_id,event_kind,effective_at_utc,target_event_id,"
            "reason_code,evidence_kind,evidence_id,recorded_at_utc,command_id"
            ") VALUES (?,?,'created',NULL,NULL,NULL,NULL,NULL,?,?)",
            (event_id, fault_tag_id, now, command_id),
        )
        member_rows: list[tuple[str, str, str, str | None, str | None, str]] = []
        for rma_id, reason in memberships:
            member_rows.append(
                (
                    *cls._insert_membership(
                        connection,
                        fault_tag_id=fault_tag_id,
                        rma_id=rma_id,
                        return_reason=reason,
                        draft_revision=1,
                        command_id=command_id,
                        excluding_fault_tag_id=fault_tag_id,
                    ),
                )
            )
        member_rows.sort(key=lambda item: item[0])
        # Re-read to avoid relying on caller ordering when canonicalizing current authority.
        current_members = cls.current_members(connection, fault_tag_id)
        fingerprint = cls.projection_fingerprint(
            fault_tag_id=fault_tag_id,
            return_method=return_method,
            pickup_dispatch_location_id=pickup_dispatch_location_id,
            pickup_contact_id=pickup_contact_id,
            pickup_instructions=pickup_instructions,
            members=tuple(
                (
                    str(row[0]),
                    str(row[1]),
                    str(row[2]),
                    None if row[3] is None else str(row[3]),
                    None if row[4] is None else str(row[4]),
                    str(row[5]),
                )
                for row in current_members
            ),
        )
        connection.execute(
            "INSERT INTO fault_tag_current_projection("
            "fault_tag_id,state,archived,current_submission_snapshot_id,"
            "submitted_member_count,awaiting_receipt_count,awaiting_final_count,"
            "accepted_count,rejected_count,revision,input_fingerprint,last_command_id"
            ") VALUES (?,'draft',0,NULL,0,0,0,0,0,1,?,?)",
            (fault_tag_id, fingerprint, command_id),
        )
        return event_id, tuple(str(row[0]) for row in current_members), 1

    @staticmethod
    def current_members(connection: Any, fault_tag_id: str):
        return connection.execute(
            "SELECT m.fault_tag_membership_id,m.rma_id,m.physical_consequence_id,"
            "m.device_part_unit_id,m.spare_part_unit_id,m.return_reason,"
            "c.state,c.active_submitted,c.revision "
            "FROM fault_tag_memberships m JOIN fault_tag_membership_current c "
            "ON c.fault_tag_membership_id=m.fault_tag_membership_id "
            "WHERE m.fault_tag_id=? ORDER BY m.rma_id,m.fault_tag_membership_id",
            (fault_tag_id,),
        ).fetchall()

    @staticmethod
    def current_tag(connection: Any, fault_tag_id: str):
        return connection.execute(
            "SELECT t.fault_tag_id,t.tracking_id,t.draft_return_method,"
            "t.draft_pickup_dispatch_location_id,t.draft_pickup_contact_id,"
            "t.draft_pickup_instructions,t.draft_revision,p.state,p.archived,"
            "p.current_submission_snapshot_id,p.revision,p.input_fingerprint "
            "FROM fault_tags t JOIN fault_tag_current_projection p "
            "ON p.fault_tag_id=t.fault_tag_id WHERE t.fault_tag_id=?",
            (fault_tag_id,),
        ).fetchone()

    @classmethod
    def replace_draft(
        cls,
        connection: Any,
        *,
        fault_tag_id: str,
        base_revision: int,
        return_method: str,
        pickup_dispatch_location_id: str | None,
        pickup_contact_id: str | None,
        pickup_instructions: str | None,
        memberships: tuple[tuple[str, str], ...],
        command_id: str,
    ) -> tuple[tuple[str, ...], int]:
        tag = cls.current_tag(connection, fault_tag_id)
        if tag is None or int(tag[10]) != base_revision:
            raise SomaError("INV_STALE", "Fault Tag revision changed")
        if str(tag[7]) != "draft" or tag[9] is not None:
            raise SomaError("FAULT_TAG_NOT_DRAFT", "Fault Tag is not editable Draft authority")
        cls.require_optional_draft_references(
            connection,
            return_method=return_method,
            pickup_dispatch_location_id=pickup_dispatch_location_id,
            pickup_contact_id=pickup_contact_id,
        )
        desired = {rma_id: reason for rma_id, reason in memberships}
        existing = {
            str(row[1]): row for row in cls.current_members(connection, fault_tag_id)
        }
        next_revision = base_revision + 1
        for rma_id, row in existing.items():
            membership_id = str(row[0])
            if rma_id not in desired:
                if str(row[6]) != "draft" or int(row[7]) != 0:
                    raise SomaError(
                        "FAULT_TAG_NOT_DRAFT",
                        "Submitted Fault Tag membership cannot be removed in place",
                    )
                protected = connection.execute(
                    "SELECT 1 FROM fault_tag_membership_events WHERE fault_tag_membership_id=? "
                    "UNION ALL SELECT 1 FROM fault_tag_membership_submission_snapshots "
                    "WHERE fault_tag_membership_id=? LIMIT 1",
                    (membership_id, membership_id),
                ).fetchone()
                if protected is not None:
                    raise SomaError(
                        "FAULT_TAG_NOT_DRAFT",
                        "Fault Tag membership already has protected history",
                    )
                connection.execute(
                    "DELETE FROM fault_tag_membership_current WHERE fault_tag_membership_id=?",
                    (membership_id,),
                )
                connection.execute(
                    "DELETE FROM fault_tag_memberships WHERE fault_tag_membership_id=?",
                    (membership_id,),
                )
                continue
            (
                physical_consequence_id,
                device_part_unit_id,
                spare_part_unit_id,
                _obligation_revision,
            ) = cls.require_membership_eligible(
                connection,
                rma_id=rma_id,
                excluding_fault_tag_id=fault_tag_id,
            )
            reason = desired[rma_id]
            connection.execute(
                "UPDATE fault_tag_memberships SET physical_consequence_id=?,"
                "device_part_unit_id=?,spare_part_unit_id=?,return_reason=?,draft_revision=? "
                "WHERE fault_tag_membership_id=?",
                (
                    physical_consequence_id,
                    device_part_unit_id,
                    spare_part_unit_id,
                    reason,
                    next_revision,
                    membership_id,
                ),
            )
            fingerprint = cls.membership_fingerprint(
                fault_tag_membership_id=membership_id,
                rma_id=rma_id,
                physical_consequence_id=physical_consequence_id,
                device_part_unit_id=device_part_unit_id,
                spare_part_unit_id=spare_part_unit_id,
                return_reason=reason,
            )
            connection.execute(
                "UPDATE fault_tag_membership_current SET device_part_unit_id=?,"
                "spare_part_unit_id=?,revision=revision+1,input_fingerprint=?,last_command_id=? "
                "WHERE fault_tag_membership_id=? AND state='draft' AND active_submitted=0",
                (
                    device_part_unit_id,
                    spare_part_unit_id,
                    fingerprint,
                    command_id,
                    membership_id,
                ),
            )
        for rma_id, reason in memberships:
            if rma_id in existing:
                continue
            cls._insert_membership(
                connection,
                fault_tag_id=fault_tag_id,
                rma_id=rma_id,
                return_reason=reason,
                draft_revision=next_revision,
                command_id=command_id,
                excluding_fault_tag_id=fault_tag_id,
            )
        connection.execute(
            "UPDATE fault_tags SET draft_return_method=?,"
            "draft_pickup_dispatch_location_id=?,draft_pickup_contact_id=?,"
            "draft_pickup_instructions=?,draft_revision=? WHERE fault_tag_id=?",
            (
                return_method,
                pickup_dispatch_location_id,
                pickup_contact_id,
                pickup_instructions,
                next_revision,
                fault_tag_id,
            ),
        )
        members = cls.current_members(connection, fault_tag_id)
        fingerprint = cls.projection_fingerprint(
            fault_tag_id=fault_tag_id,
            return_method=return_method,
            pickup_dispatch_location_id=pickup_dispatch_location_id,
            pickup_contact_id=pickup_contact_id,
            pickup_instructions=pickup_instructions,
            members=tuple(
                (
                    str(row[0]),
                    str(row[1]),
                    str(row[2]),
                    None if row[3] is None else str(row[3]),
                    None if row[4] is None else str(row[4]),
                    str(row[5]),
                )
                for row in members
            ),
        )
        changed = connection.execute(
            "UPDATE fault_tag_current_projection SET revision=?,input_fingerprint=?,"
            "last_command_id=? WHERE fault_tag_id=? AND revision=? AND state='draft' "
            "AND current_submission_snapshot_id IS NULL",
            (next_revision, fingerprint, command_id, fault_tag_id, base_revision),
        )
        if changed.rowcount != 1:
            raise SomaError("INV_STALE", "Fault Tag changed during draft replacement")
        return tuple(str(row[0]) for row in members), next_revision


__all__ = ["InventoryFaultTagsRepository"]
