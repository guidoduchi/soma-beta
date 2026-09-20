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
            "c.state,c.active_submitted,c.revision,c.last_event_id "
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

    @staticmethod
    def _pickup_snapshot(
        connection: Any,
        *,
        return_method: str,
        pickup_dispatch_location_id: str | None,
        pickup_contact_id: str | None,
    ) -> tuple[str | None, str | None, str | None]:
        if return_method == "non_pickup":
            return None, None, None
        if pickup_dispatch_location_id is None:
            raise SomaError(
                "FAULT_TAG_PICKUP_ORIGIN_REQUIRED",
                "Pickup Fault Tag requires exactly one pickup-origin Dispatch Location",
            )
        location = connection.execute(
            "SELECT name,address_mode,standalone_address_text,lifecycle_state "
            "FROM dispatch_locations WHERE dispatch_location_id=?",
            (pickup_dispatch_location_id,),
        ).fetchone()
        if location is None or str(location[3]) != "active":
            raise SomaError(
                "FAULT_TAG_PICKUP_ORIGIN_REQUIRED",
                "Pickup-origin Dispatch Location is unavailable",
            )
        if location[2] is None:
            raise SomaError(
                "FAULT_TAG_PICKUP_ORIGIN_REQUIRED",
                "Pickup-origin address cannot be snapshotted",
            )
        contact_json = None
        if pickup_contact_id is not None:
            contact = connection.execute(
                "SELECT name,revision,lifecycle_state FROM contacts WHERE contact_id=?",
                (pickup_contact_id,),
            ).fetchone()
            if contact is None or str(contact[2]) != "active":
                raise SomaError(
                    "FAULT_TAG_PICKUP_ORIGIN_REQUIRED",
                    "Pickup Contact is unavailable",
                )
            contact_json = __import__("json").dumps(
                {
                    "contact_id": pickup_contact_id,
                    "contact_revision_at_submission": int(contact[1]),
                    "display_name_snapshot": str(contact[0]),
                },
                sort_keys=True,
                separators=(",", ":"),
                ensure_ascii=False,
            )
        return str(location[0]), str(location[2]), contact_json

    @staticmethod
    def latest_submission(connection: Any, fault_tag_id: str):
        return connection.execute(
            "SELECT s.fault_tag_submission_snapshot_id,s.submission_event_id,"
            "s.effective_submission_at_utc,s.recorded_at_utc,s.snapshot_hash "
            "FROM fault_tag_submission_snapshots s "
            "WHERE s.fault_tag_id=? AND NOT EXISTS ("
            "SELECT 1 FROM fault_tag_lifecycle_events c "
            "WHERE c.fault_tag_id=s.fault_tag_id "
            "AND c.event_kind='submission_corrected_false' "
            "AND c.target_event_id=s.submission_event_id"
            ") ORDER BY s.recorded_at_utc DESC,s.fault_tag_submission_snapshot_id DESC LIMIT 1",
            (fault_tag_id,),
        ).fetchone()

    @staticmethod
    def latest_lifecycle_kind(connection: Any, fault_tag_id: str) -> str | None:
        row = connection.execute(
            "SELECT event_kind FROM fault_tag_lifecycle_events WHERE fault_tag_id=? "
            "ORDER BY recorded_at_utc DESC,fault_tag_event_id DESC LIMIT 1",
            (fault_tag_id,),
        ).fetchone()
        return None if row is None else str(row[0])

    @staticmethod
    def _rma_c10(connection: Any, rma_id: str) -> str | None:
        row = connection.execute(
            "SELECT c10 FROM rma_identifier_aliases WHERE rma_id=? AND alias_kind='current'",
            (rma_id,),
        ).fetchone()
        return None if row is None else str(row[0])

    @staticmethod
    def _update_rma_fault_tag_projection(
        connection: Any,
        *,
        rma_id: str,
        membership_id: str | None,
        command_id: str,
    ) -> None:
        row = connection.execute(
            "SELECT state,current_target_device_part_unit_id,"
            "direct_inbound_spare_part_unit_id,return_device_part_unit_id,"
            "return_spare_part_unit_id,return_obligation_open,revision,input_fingerprint "
            "FROM rma_lifecycle_projection WHERE rma_id=?",
            (rma_id,),
        ).fetchone()
        if row is None:
            raise IntegrityFailure("Fault Tag membership points to missing RMA projection")
        next_state = "fault_tagged" if membership_id is not None else (
            "return_open" if int(row[5]) == 1 else str(row[0])
        )
        fingerprint = sha256_canonical_json(
            {
                "schema": "SOMA_RMA_LIFECYCLE_V1",
                "rma_id": rma_id,
                "state": next_state,
                "current_target_device_part_unit_id": (
                    None if row[1] is None else str(row[1])
                ),
                "direct_inbound_spare_part_unit_id": (
                    None if row[2] is None else str(row[2])
                ),
                "return_device_part_unit_id": (
                    None if row[3] is None else str(row[3])
                ),
                "return_spare_part_unit_id": (
                    None if row[4] is None else str(row[4])
                ),
                "return_obligation_open": int(row[5]),
                "active_fault_tag_membership_id": membership_id,
            }
        )
        changed = connection.execute(
            "UPDATE rma_lifecycle_projection SET state=?,active_fault_tag_membership_id=?,"
            "revision=revision+1,input_fingerprint=?,last_command_id=? "
            "WHERE rma_id=? AND revision=?",
            (
                next_state,
                membership_id,
                fingerprint,
                command_id,
                rma_id,
                int(row[6]),
            ),
        )
        if changed.rowcount != 1:
            raise SomaError("INV_STALE", "RMA changed during Fault Tag transition")

    @classmethod
    def accept_submission(
        cls,
        connection: Any,
        *,
        fault_tag_id: str,
        expected_fingerprint: str,
        effective_submission_at_utc: int | None,
        evidence_kind: str,
        evidence_id: str | None,
        command_id: str,
    ) -> tuple[str, str, int, int, str]:
        tag = cls.current_tag(connection, fault_tag_id)
        if tag is None:
            raise SomaError("INV_STALE", "Fault Tag no longer exists")
        if str(tag[7]) != "draft" or tag[9] is not None:
            raise SomaError("FAULT_TAG_NOT_DRAFT", "Fault Tag is not submission-ready Draft authority")
        if str(tag[11]) != expected_fingerprint:
            raise SomaError("INV_STALE", "Fault Tag draft fingerprint changed")
        members = cls.current_members(connection, fault_tag_id)
        if not members:
            raise SomaError("FAULT_TAG_NOT_DRAFT", "Fault Tag submission requires one-or-more members")
        location_name, location_address, contact_json = cls._pickup_snapshot(
            connection,
            return_method=str(tag[2]),
            pickup_dispatch_location_id=None if tag[3] is None else str(tag[3]),
            pickup_contact_id=None if tag[4] is None else str(tag[4]),
        )
        # Revalidate exact obligation/unit/consequence and submitted exclusivity.
        for member in members:
            (
                consequence_id,
                device_id,
                spare_id,
                _obligation_revision,
            ) = cls.require_membership_eligible(
                connection,
                rma_id=str(member[1]),
                excluding_fault_tag_id=fault_tag_id,
            )
            if (
                consequence_id != str(member[2])
                or device_id != (None if member[3] is None else str(member[3]))
                or spare_id != (None if member[4] is None else str(member[4]))
            ):
                raise SomaError(
                    "INV_STALE",
                    "Fault Tag membership no longer matches exact return obligation",
                )
        now = utc_epoch_seconds()
        event_id = new_uuid4()
        snapshot_id = new_uuid4()
        display_members: list[dict[str, object]] = []
        for member in members:
            display_members.append(
                {
                    "fault_tag_membership_id": str(member[0]),
                    "rma_id": str(member[1]),
                    "current_c10": cls._rma_c10(connection, str(member[1])),
                    "physical_consequence_id": str(member[2]),
                    "device_part_unit_id": None if member[3] is None else str(member[3]),
                    "spare_part_unit_id": None if member[4] is None else str(member[4]),
                    "return_reason": str(member[5]),
                }
            )
        snapshot_material = {
            "schema": "SOMA_FAULT_TAG_SUBMISSION_V1",
            "fault_tag_id": fault_tag_id,
            "submission_event_id": event_id,
            "tracking_id": str(tag[1]),
            "return_method": str(tag[2]),
            "pickup_dispatch_location_id": None if tag[3] is None else str(tag[3]),
            "pickup_location_name_snapshot": location_name,
            "pickup_location_address_snapshot": location_address,
            "pickup_contact_id": None if tag[4] is None else str(tag[4]),
            "pickup_contact_snapshot_json": (
                None if contact_json is None else __import__("json").loads(contact_json)
            ),
            "pickup_instructions_snapshot": None if tag[5] is None else str(tag[5]),
            "effective_submission_at_utc": effective_submission_at_utc,
            "evidence_kind": evidence_kind,
            "evidence_id": evidence_id,
            "members": display_members,
        }
        snapshot_hash = sha256_canonical_json(snapshot_material)
        connection.execute(
            "INSERT INTO fault_tag_lifecycle_events("
            "fault_tag_event_id,fault_tag_id,event_kind,effective_at_utc,target_event_id,"
            "reason_code,evidence_kind,evidence_id,recorded_at_utc,command_id"
            ") VALUES (?,?,'submission_accepted',?,NULL,NULL,?,?,?,?)",
            (
                event_id,
                fault_tag_id,
                effective_submission_at_utc,
                evidence_kind,
                evidence_id,
                now,
                command_id,
            ),
        )
        connection.execute(
            "INSERT INTO fault_tag_submission_snapshots("
            "fault_tag_submission_snapshot_id,fault_tag_id,submission_event_id,tracking_id,"
            "return_method,pickup_dispatch_location_id,pickup_location_name_snapshot,"
            "pickup_location_address_snapshot,pickup_contact_id,pickup_contact_snapshot_json,"
            "pickup_instructions_snapshot,recipient_context_json,effective_submission_at_utc,"
            "recorded_at_utc,snapshot_hash"
            ") VALUES (?,?,?,?,?,?,?,?,?,?,?,NULL,?,?,?)",
            (
                snapshot_id,
                fault_tag_id,
                event_id,
                str(tag[1]),
                str(tag[2]),
                None if tag[3] is None else str(tag[3]),
                location_name,
                location_address,
                None if tag[4] is None else str(tag[4]),
                contact_json,
                None if tag[5] is None else str(tag[5]),
                effective_submission_at_utc,
                now,
                snapshot_hash,
            ),
        )
        for member, display in zip(members, display_members):
            membership_id = str(member[0])
            membership_snapshot_id = new_uuid4()
            display_json = __import__("json").dumps(
                {
                    "schema": "FTT_MEMBERSHIP_DISPLAY_V1",
                    "rma_id": display["rma_id"],
                    "current_c10": display["current_c10"],
                    "device_part_unit_id": display["device_part_unit_id"],
                    "spare_part_unit_id": display["spare_part_unit_id"],
                    "return_reason": display["return_reason"],
                },
                sort_keys=True,
                separators=(",", ":"),
                ensure_ascii=False,
            )
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
                    str(member[1]),
                    None if member[3] is None else str(member[3]),
                    None if member[4] is None else str(member[4]),
                    str(member[2]),
                    str(member[5]),
                    display_json,
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
            membership_fingerprint = sha256_canonical_json(
                {
                    "schema": "SOMA_FAULT_TAG_MEMBERSHIP_CURRENT_V1",
                    "fault_tag_membership_id": membership_id,
                    "rma_id": str(member[1]),
                    "state": "submitted_awaiting_receipt",
                    "active_submitted": 1,
                    "device_part_unit_id": None if member[3] is None else str(member[3]),
                    "spare_part_unit_id": None if member[4] is None else str(member[4]),
                    "last_event_id": membership_event_id,
                }
            )
            changed = connection.execute(
                "UPDATE fault_tag_membership_current SET state='submitted_awaiting_receipt',"
                "active_submitted=1,revision=revision+1,input_fingerprint=?,last_event_id=?,"
                "last_command_id=? WHERE fault_tag_membership_id=? AND state='draft' "
                "AND active_submitted=0",
                (
                    membership_fingerprint,
                    membership_event_id,
                    command_id,
                    membership_id,
                ),
            )
            if changed.rowcount != 1:
                raise SomaError("INV_STALE", "Fault Tag membership changed during submission")
            cls._update_rma_fault_tag_projection(
                connection,
                rma_id=str(member[1]),
                membership_id=membership_id,
                command_id=command_id,
            )
        resulting_revision = int(tag[10]) + 1
        projection_fingerprint = sha256_canonical_json(
            {
                "schema": "SOMA_FAULT_TAG_CURRENT_V1",
                "fault_tag_id": fault_tag_id,
                "state": "submitted",
                "archived": int(tag[8]),
                "current_submission_snapshot_id": snapshot_id,
                "submitted_member_count": len(members),
                "awaiting_receipt_count": len(members),
                "awaiting_final_count": 0,
                "accepted_count": 0,
                "rejected_count": 0,
                "snapshot_hash": snapshot_hash,
            }
        )
        changed = connection.execute(
            "UPDATE fault_tag_current_projection SET state='submitted',"
            "current_submission_snapshot_id=?,submitted_member_count=?,"
            "awaiting_receipt_count=?,awaiting_final_count=0,accepted_count=0,"
            "rejected_count=0,revision=?,input_fingerprint=?,last_command_id=? "
            "WHERE fault_tag_id=? AND revision=? AND state='draft' "
            "AND current_submission_snapshot_id IS NULL",
            (
                snapshot_id,
                len(members),
                len(members),
                resulting_revision,
                projection_fingerprint,
                command_id,
                fault_tag_id,
                int(tag[10]),
            ),
        )
        if changed.rowcount != 1:
            raise SomaError("INV_STALE", "Fault Tag changed during submission")
        return event_id, snapshot_id, resulting_revision, len(members), snapshot_hash

    @classmethod
    def correct_false_submission(
        cls,
        connection: Any,
        *,
        fault_tag_id: str,
        submission_event_id: str,
        reason_code: str,
        command_id: str,
    ) -> tuple[str, str, int, int, str]:
        tag = cls.current_tag(connection, fault_tag_id)
        if tag is None:
            raise SomaError("INV_STALE", "Fault Tag no longer exists")
        current = cls.latest_submission(connection, fault_tag_id)
        if current is None or str(current[1]) != submission_event_id:
            raise SomaError(
                "CORRECTION_TARGET_INVALID",
                "Target is not current-effective Fault Tag submission",
            )
        source_event = connection.execute(
            "SELECT evidence_kind FROM fault_tag_lifecycle_events "
            "WHERE fault_tag_event_id=? AND fault_tag_id=? AND event_kind='submission_accepted'",
            (submission_event_id, fault_tag_id),
        ).fetchone()
        if source_event is None:
            raise IntegrityFailure("Fault Tag current submission event is missing")
        if source_event[0] == "indexed_sent":
            raise SomaError(
                "CORRECTION_TARGET_INVALID",
                "Indexed sent evidence contradicts false-submission correction",
            )
        members = cls.current_members(connection, fault_tag_id)
        for member in members:
            if str(member[6]) != "submitted_awaiting_receipt" or int(member[7]) != 1:
                raise SomaError(
                    "CORRECTION_TARGET_INVALID",
                    "Warehouse or later membership authority contradicts false submission",
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
        for member in members:
            membership_id = str(member[0])
            previous_event_id = None if member[9] is None else str(member[9])
            if previous_event_id is None:
                raise IntegrityFailure("Submitted Fault Tag membership lacks submitted event")
            event_id = new_uuid4()
            connection.execute(
                "INSERT INTO fault_tag_membership_events("
                "membership_event_id,fault_tag_membership_id,event_kind,effective_at_utc,"
                "target_event_id,reason_code,evidence_kind,evidence_id,recorded_at_utc,command_id"
                ") VALUES (?,?,'correct',NULL,?,?,NULL,NULL,?,?)",
                (
                    event_id,
                    membership_id,
                    previous_event_id,
                    reason_code,
                    now,
                    command_id,
                ),
            )
            fingerprint = cls.membership_fingerprint(
                fault_tag_membership_id=membership_id,
                rma_id=str(member[1]),
                physical_consequence_id=str(member[2]),
                device_part_unit_id=None if member[3] is None else str(member[3]),
                spare_part_unit_id=None if member[4] is None else str(member[4]),
                return_reason=str(member[5]),
            )
            changed = connection.execute(
                "UPDATE fault_tag_membership_current SET state='draft',active_submitted=0,"
                "revision=revision+1,input_fingerprint=?,last_event_id=?,last_command_id=? "
                "WHERE fault_tag_membership_id=? AND state='submitted_awaiting_receipt' "
                "AND active_submitted=1",
                (fingerprint, event_id, command_id, membership_id),
            )
            if changed.rowcount != 1:
                raise SomaError("INV_STALE", "Fault Tag membership changed during correction")
            cls._update_rma_fault_tag_projection(
                connection,
                rma_id=str(member[1]),
                membership_id=None,
                command_id=command_id,
            )
        draft_fingerprint = cls.projection_fingerprint(
            fault_tag_id=fault_tag_id,
            return_method=str(tag[2]),
            pickup_dispatch_location_id=None if tag[3] is None else str(tag[3]),
            pickup_contact_id=None if tag[4] is None else str(tag[4]),
            pickup_instructions=None if tag[5] is None else str(tag[5]),
            members=tuple(
                (
                    str(member[0]),
                    str(member[1]),
                    str(member[2]),
                    None if member[3] is None else str(member[3]),
                    None if member[4] is None else str(member[4]),
                    str(member[5]),
                )
                for member in members
            ),
            archived=int(tag[8]),
        )
        resulting_revision = int(tag[10]) + 1
        changed = connection.execute(
            "UPDATE fault_tag_current_projection SET state='draft',"
            "current_submission_snapshot_id=NULL,submitted_member_count=0,"
            "awaiting_receipt_count=0,awaiting_final_count=0,accepted_count=0,"
            "rejected_count=0,revision=?,input_fingerprint=?,last_command_id=? "
            "WHERE fault_tag_id=? AND revision=? AND current_submission_snapshot_id=?",
            (
                resulting_revision,
                draft_fingerprint,
                command_id,
                fault_tag_id,
                int(tag[10]),
                str(current[0]),
            ),
        )
        if changed.rowcount != 1:
            raise SomaError("INV_STALE", "Fault Tag changed during false-submission correction")
        return (
            correction_event_id,
            str(current[0]),
            resulting_revision,
            len(members),
            str(current[4]),
        )

    @staticmethod
    def warehouse_membership_authority(connection: Any, membership_id: str):
        return connection.execute(
            "SELECT c.fault_tag_membership_id,c.fault_tag_id,c.rma_id,"
            "c.device_part_unit_id,c.spare_part_unit_id,c.state,c.active_submitted,"
            "c.revision,c.last_event_id,m.physical_consequence_id "
            "FROM fault_tag_membership_current c JOIN fault_tag_memberships m "
            "ON m.fault_tag_membership_id=c.fault_tag_membership_id "
            "WHERE c.fault_tag_membership_id=?",
            (membership_id,),
        ).fetchone()

    @classmethod
    def _require_warehouse_target(
        cls,
        connection: Any,
        *,
        membership_id: str,
        expected_revision: int,
        required_state: str,
    ):
        row = cls.warehouse_membership_authority(connection, membership_id)
        if row is None or int(row[7]) != expected_revision:
            raise SomaError("INV_STALE", "Fault Tag membership revision changed")
        if str(row[5]) != required_state or int(row[6]) != 1:
            if required_state == "warehouse_received":
                raise SomaError(
                    "WAREHOUSE_RECEIPT_REQUIRED",
                    "Fault Tag membership is not awaiting final warehouse decision",
                )
            raise SomaError(
                "BULK_INCOMPATIBLE",
                "Fault Tag membership is not awaiting warehouse receipt",
            )
        obligation = connection.execute(
            "SELECT obligation_state,device_part_unit_id,spare_part_unit_id,"
            "physical_consequence_id,revision,last_event_id "
            "FROM rma_return_obligation_current WHERE rma_id=?",
            (str(row[2]),),
        ).fetchone()
        if obligation is None or str(obligation[0]) != "open":
            raise SomaError(
                "INV_STALE",
                "Fault Tag membership return obligation is no longer open",
            )
        if (
            (None if obligation[1] is None else str(obligation[1]))
            != (None if row[3] is None else str(row[3]))
            or (None if obligation[2] is None else str(obligation[2]))
            != (None if row[4] is None else str(row[4]))
            or (None if obligation[3] is None else str(obligation[3]))
            != str(row[9])
        ):
            raise SomaError(
                "INV_STALE",
                "Fault Tag membership no longer matches current return obligation",
            )
        return row, obligation

    @staticmethod
    def _membership_state_fingerprint(
        *,
        membership_id: str,
        rma_id: str,
        state: str,
        active_submitted: int,
        device_part_unit_id: str | None,
        spare_part_unit_id: str | None,
        last_event_id: str,
    ) -> str:
        return sha256_canonical_json(
            {
                "schema": "SOMA_FAULT_TAG_MEMBERSHIP_CURRENT_V1",
                "fault_tag_membership_id": membership_id,
                "rma_id": rma_id,
                "state": state,
                "active_submitted": active_submitted,
                "device_part_unit_id": device_part_unit_id,
                "spare_part_unit_id": spare_part_unit_id,
                "last_event_id": last_event_id,
            }
        )

    @classmethod
    def _rebuild_tag_projection(
        cls,
        connection: Any,
        *,
        fault_tag_id: str,
        command_id: str,
    ) -> int:
        tag = cls.current_tag(connection, fault_tag_id)
        if tag is None:
            raise IntegrityFailure("Fault Tag disappeared during projection rebuild")
        projection = connection.execute(
            "SELECT submitted_member_count,revision,current_submission_snapshot_id,archived "
            "FROM fault_tag_current_projection WHERE fault_tag_id=?",
            (fault_tag_id,),
        ).fetchone()
        if projection is None:
            raise IntegrityFailure("Fault Tag projection disappeared during rebuild")
        counts = {
            str(row[0]): int(row[1])
            for row in connection.execute(
                "SELECT state,COUNT(*) FROM fault_tag_membership_current "
                "WHERE fault_tag_id=? GROUP BY state",
                (fault_tag_id,),
            ).fetchall()
        }
        submitted_count = int(projection[0])
        awaiting_receipt = counts.get("submitted_awaiting_receipt", 0)
        awaiting_final = counts.get("warehouse_received", 0)
        accepted = counts.get("accepted", 0)
        rejected = counts.get("rejected", 0)
        terminal_count = accepted + rejected + counts.get("cancelled", 0) + counts.get("superseded", 0)
        if submitted_count > 0 and terminal_count >= submitted_count:
            state = "terminal_with_rejected" if rejected else "terminal_completed"
        elif awaiting_final > 0:
            state = "in_warehouse_review"
        else:
            state = "submitted"
        revision = int(projection[1]) + 1
        fingerprint = sha256_canonical_json(
            {
                "schema": "SOMA_FAULT_TAG_CURRENT_V1",
                "fault_tag_id": fault_tag_id,
                "state": state,
                "archived": int(projection[3]),
                "current_submission_snapshot_id": (
                    None if projection[2] is None else str(projection[2])
                ),
                "submitted_member_count": submitted_count,
                "awaiting_receipt_count": awaiting_receipt,
                "awaiting_final_count": awaiting_final,
                "accepted_count": accepted,
                "rejected_count": rejected,
            }
        )
        changed = connection.execute(
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
                int(projection[1]),
            ),
        )
        if changed.rowcount != 1:
            raise SomaError("INV_STALE", "Fault Tag changed during projection rebuild")
        return revision

    @staticmethod
    def _rebuild_rma_warehouse_state(
        connection: Any,
        *,
        rma_id: str,
        membership_id: str | None,
        state: str,
        obligation_open: int,
        command_id: str,
    ) -> int:
        row = connection.execute(
            "SELECT current_target_device_part_unit_id,direct_inbound_spare_part_unit_id,"
            "return_device_part_unit_id,return_spare_part_unit_id,revision "
            "FROM rma_lifecycle_projection WHERE rma_id=?",
            (rma_id,),
        ).fetchone()
        if row is None:
            raise IntegrityFailure("RMA projection disappeared during warehouse transition")
        revision = int(row[4]) + 1
        fingerprint = sha256_canonical_json(
            {
                "schema": "SOMA_RMA_LIFECYCLE_V1",
                "rma_id": rma_id,
                "state": state,
                "current_target_device_part_unit_id": None if row[0] is None else str(row[0]),
                "direct_inbound_spare_part_unit_id": None if row[1] is None else str(row[1]),
                "return_device_part_unit_id": None if row[2] is None else str(row[2]),
                "return_spare_part_unit_id": None if row[3] is None else str(row[3]),
                "return_obligation_open": obligation_open,
                "active_fault_tag_membership_id": membership_id,
            }
        )
        changed = connection.execute(
            "UPDATE rma_lifecycle_projection SET state=?,return_obligation_open=?,"
            "active_fault_tag_membership_id=?,revision=?,input_fingerprint=?,last_command_id=? "
            "WHERE rma_id=? AND revision=?",
            (
                state,
                obligation_open,
                membership_id,
                revision,
                fingerprint,
                command_id,
                rma_id,
                int(row[4]),
            ),
        )
        if changed.rowcount != 1:
            raise SomaError("INV_STALE", "RMA changed during warehouse transition")
        return revision

    @staticmethod
    def insert_lifecycle_batch(
        connection: Any,
        *,
        batch_id: str,
        target_count: int,
        command_id: str,
    ) -> None:
        connection.execute(
            "INSERT INTO inventory_lifecycle_batches("
            "inventory_batch_id,batch_kind,target_count,recorded_at_utc,command_id"
            ") VALUES (?,'manual_bulk',?,?,?)",
            (batch_id, target_count, utc_epoch_seconds(), command_id),
        )

    @classmethod
    def record_warehouse_receipt(
        cls,
        connection: Any,
        *,
        targets: tuple[tuple[str, int], ...],
        effective_at_utc: int | None,
        evidence_kind: str | None,
        evidence_id: str | None,
        batch_id: str | None,
        command_id: str,
    ) -> tuple[tuple[dict[str, object], ...], dict[str, int]]:
        preflight = [
            cls._require_warehouse_target(
                connection,
                membership_id=membership_id,
                expected_revision=revision,
                required_state="submitted_awaiting_receipt",
            )
            for membership_id, revision in targets
        ]
        if batch_id is not None:
            cls.insert_lifecycle_batch(
                connection,
                batch_id=batch_id,
                target_count=len(targets),
                command_id=command_id,
            )
        now = utc_epoch_seconds()
        results: list[dict[str, object]] = []
        affected_tags: set[str] = set()
        for (membership_id, expected_revision), (row, _obligation) in zip(targets, preflight):
            event_id = new_uuid4()
            connection.execute(
                "INSERT INTO fault_tag_membership_events("
                "membership_event_id,fault_tag_membership_id,event_kind,effective_at_utc,"
                "target_event_id,reason_code,evidence_kind,evidence_id,recorded_at_utc,command_id"
                ") VALUES (?,?,'warehouse_received',?,NULL,NULL,?,?,?,?)",
                (
                    event_id,
                    membership_id,
                    effective_at_utc,
                    evidence_kind,
                    evidence_id,
                    now,
                    command_id,
                ),
            )
            fingerprint = cls._membership_state_fingerprint(
                membership_id=membership_id,
                rma_id=str(row[2]),
                state="warehouse_received",
                active_submitted=1,
                device_part_unit_id=None if row[3] is None else str(row[3]),
                spare_part_unit_id=None if row[4] is None else str(row[4]),
                last_event_id=event_id,
            )
            changed = connection.execute(
                "UPDATE fault_tag_membership_current SET state='warehouse_received',"
                "revision=revision+1,input_fingerprint=?,last_event_id=?,last_command_id=? "
                "WHERE fault_tag_membership_id=? AND revision=? "
                "AND state='submitted_awaiting_receipt' AND active_submitted=1",
                (fingerprint, event_id, command_id, membership_id, expected_revision),
            )
            if changed.rowcount != 1:
                raise SomaError("INV_STALE", "Fault Tag membership changed during warehouse receipt")
            rma_revision = cls._rebuild_rma_warehouse_state(
                connection,
                rma_id=str(row[2]),
                membership_id=membership_id,
                state="warehouse_received",
                obligation_open=1,
                command_id=command_id,
            )
            affected_tags.add(str(row[1]))
            results.append(
                {
                    "membership_id": membership_id,
                    "membership_event_id": event_id,
                    "membership_revision": expected_revision + 1,
                    "fault_tag_id": str(row[1]),
                    "rma_id": str(row[2]),
                    "rma_revision": rma_revision,
                }
            )
        tag_revisions = {
            tag_id: cls._rebuild_tag_projection(
                connection,
                fault_tag_id=tag_id,
                command_id=command_id,
            )
            for tag_id in sorted(affected_tags)
        }
        return tuple(results), tag_revisions

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
        batch_id: str | None,
        command_id: str,
    ) -> tuple[tuple[dict[str, object], ...], dict[str, int]]:
        preflight = [
            cls._require_warehouse_target(
                connection,
                membership_id=membership_id,
                expected_revision=revision,
                required_state="warehouse_received",
            )
            for membership_id, revision in targets
        ]
        if batch_id is not None:
            cls.insert_lifecycle_batch(
                connection,
                batch_id=batch_id,
                target_count=len(targets),
                command_id=command_id,
            )
        now = utc_epoch_seconds()
        target_state = "accepted" if decision == "accepted" else "rejected"
        event_kind = "warehouse_accepted" if decision == "accepted" else "warehouse_rejected"
        results: list[dict[str, object]] = []
        affected_tags: set[str] = set()
        for (membership_id, expected_revision), (row, obligation) in zip(targets, preflight):
            event_id = new_uuid4()
            connection.execute(
                "INSERT INTO fault_tag_membership_events("
                "membership_event_id,fault_tag_membership_id,event_kind,effective_at_utc,"
                "target_event_id,reason_code,evidence_kind,evidence_id,recorded_at_utc,command_id"
                ") VALUES (?,?,?,?,NULL,?,?,?,?,?)",
                (
                    event_id,
                    membership_id,
                    event_kind,
                    effective_at_utc,
                    reason_code,
                    evidence_kind,
                    evidence_id,
                    now,
                    command_id,
                ),
            )
            fingerprint = cls._membership_state_fingerprint(
                membership_id=membership_id,
                rma_id=str(row[2]),
                state=target_state,
                active_submitted=0,
                device_part_unit_id=None if row[3] is None else str(row[3]),
                spare_part_unit_id=None if row[4] is None else str(row[4]),
                last_event_id=event_id,
            )
            changed = connection.execute(
                "UPDATE fault_tag_membership_current SET state=?,active_submitted=0,"
                "revision=revision+1,input_fingerprint=?,last_event_id=?,last_command_id=? "
                "WHERE fault_tag_membership_id=? AND revision=? AND state='warehouse_received' "
                "AND active_submitted=1",
                (
                    target_state,
                    fingerprint,
                    event_id,
                    command_id,
                    membership_id,
                    expected_revision,
                ),
            )
            if changed.rowcount != 1:
                raise SomaError("INV_STALE", "Fault Tag membership changed during final decision")
            return_event_id = None
            if decision == "accepted":
                if obligation[3] is None:
                    raise IntegrityFailure("Open return obligation lacks physical consequence")
                return_event_id = new_uuid4()
                connection.execute(
                    "INSERT INTO rma_return_selection_events("
                    "return_selection_event_id,rma_id,physical_consequence_id,event_kind,"
                    "device_part_unit_id,spare_part_unit_id,reason_code,effective_at_utc,"
                    "target_event_id,recorded_at_utc,command_id"
                    ") VALUES (?,?,?,'close',NULL,NULL,NULL,?,?,?,?)",
                    (
                        return_event_id,
                        str(row[2]),
                        str(obligation[3]),
                        effective_at_utc,
                        None if obligation[5] is None else str(obligation[5]),
                        now,
                        command_id,
                    ),
                )
                changed_obligation = connection.execute(
                    "UPDATE rma_return_obligation_current SET obligation_state='closed_accepted',"
                    "revision=revision+1,last_event_id=?,last_command_id=? "
                    "WHERE rma_id=? AND revision=? AND obligation_state='open'",
                    (
                        return_event_id,
                        command_id,
                        str(row[2]),
                        int(obligation[4]),
                    ),
                )
                if changed_obligation.rowcount != 1:
                    raise SomaError("INV_STALE", "Return obligation changed during acceptance")
                rma_revision = cls._rebuild_rma_warehouse_state(
                    connection,
                    rma_id=str(row[2]),
                    membership_id=None,
                    state="closed_accepted",
                    obligation_open=0,
                    command_id=command_id,
                )
            else:
                rma_revision = cls._rebuild_rma_warehouse_state(
                    connection,
                    rma_id=str(row[2]),
                    membership_id=None,
                    state="return_rejected",
                    obligation_open=1,
                    command_id=command_id,
                )
            affected_tags.add(str(row[1]))
            results.append(
                {
                    "membership_id": membership_id,
                    "membership_event_id": event_id,
                    "membership_revision": expected_revision + 1,
                    "fault_tag_id": str(row[1]),
                    "rma_id": str(row[2]),
                    "rma_revision": rma_revision,
                    "return_event_id": return_event_id,
                }
            )
        tag_revisions = {
            tag_id: cls._rebuild_tag_projection(
                connection,
                fault_tag_id=tag_id,
                command_id=command_id,
            )
            for tag_id in sorted(affected_tags)
        }
        return tuple(results), tag_revisions

    @staticmethod
    def has_submission_history(connection: Any, fault_tag_id: str) -> bool:
        return connection.execute(
            "SELECT 1 FROM fault_tag_submission_snapshots WHERE fault_tag_id=? LIMIT 1",
            (fault_tag_id,),
        ).fetchone() is not None

    @staticmethod
    def correction_successor(connection: Any, fault_tag_id: str) -> str | None:
        row = connection.execute(
            "SELECT successor_fault_tag_id FROM fault_tag_lineage "
            "WHERE predecessor_fault_tag_id=? AND relation_type='corrects_replaces'",
            (fault_tag_id,),
        ).fetchone()
        return None if row is None else str(row[0])

    @staticmethod
    def _lineage_scope_fingerprint(
        memberships: tuple[tuple[str, str], ...],
    ) -> str:
        return sha256_canonical_json(
            {
                "schema": "SOMA_FAULT_TAG_LINEAGE_SCOPE_V1",
                "memberships": [
                    {"rma_id": rma_id, "return_reason": reason}
                    for rma_id, reason in memberships
                ],
            }
        )

    @classmethod
    def require_resend_scope(
        cls,
        connection: Any,
        *,
        predecessor_fault_tag_id: str,
        memberships: tuple[tuple[str, str], ...],
    ) -> None:
        if not cls.has_submission_history(connection, predecessor_fault_tag_id):
            raise SomaError("RESEND_NOT_ELIGIBLE", "Fault Tag has no submitted history")
        for rma_id, _reason in memberships:
            rejected = connection.execute(
                "SELECT c.fault_tag_membership_id FROM fault_tag_membership_current c "
                "WHERE c.fault_tag_id=? AND c.rma_id=? AND c.state='rejected' "
                "AND c.active_submitted=0",
                (predecessor_fault_tag_id, rma_id),
            ).fetchone()
            if rejected is None:
                raise SomaError(
                    "RESEND_NOT_ELIGIBLE",
                    "Selected RMA is not a rejected predecessor membership",
                )
            obligation = cls.obligation_authority(connection, rma_id)
            if obligation is None or str(obligation[0]) != "open":
                raise SomaError(
                    "RESEND_NOT_ELIGIBLE",
                    "Selected rejected RMA obligation is not currently open",
                )
            conflict = connection.execute(
                "SELECT 1 FROM fault_tag_lineage l "
                "JOIN fault_tag_memberships m ON m.fault_tag_id=l.successor_fault_tag_id "
                "WHERE l.predecessor_fault_tag_id=? AND l.relation_type='resend_of' "
                "AND m.rma_id=? LIMIT 1",
                (predecessor_fault_tag_id, rma_id),
            ).fetchone()
            if conflict is not None:
                raise SomaError(
                    "RESEND_NOT_ELIGIBLE",
                    "Selected rejected obligation already has a resend successor",
                )

    @classmethod
    def supersede_for_replacement(
        cls,
        connection: Any,
        *,
        predecessor_fault_tag_id: str,
        reason_code: str,
        command_id: str,
    ) -> tuple[str, int]:
        tag = cls.current_tag(connection, predecessor_fault_tag_id)
        if tag is None:
            raise SomaError("INV_STALE", "Predecessor Fault Tag no longer exists")
        if not cls.has_submission_history(connection, predecessor_fault_tag_id):
            raise SomaError(
                "REPLACEMENT_LINEAGE_CONFLICT",
                "Fault Tag replacement requires submitted predecessor history",
            )
        if cls.correction_successor(connection, predecessor_fault_tag_id) is not None:
            raise SomaError(
                "REPLACEMENT_LINEAGE_CONFLICT",
                "Fault Tag already has a correction successor",
            )
        if str(tag[7]) == "superseded":
            raise SomaError(
                "REPLACEMENT_LINEAGE_CONFLICT",
                "Fault Tag predecessor is already superseded",
            )
        now = utc_epoch_seconds()
        tag_event_id = new_uuid4()
        connection.execute(
            "INSERT INTO fault_tag_lifecycle_events("
            "fault_tag_event_id,fault_tag_id,event_kind,effective_at_utc,target_event_id,"
            "reason_code,evidence_kind,evidence_id,recorded_at_utc,command_id"
            ") VALUES (?,?,'superseded',NULL,NULL,?,NULL,NULL,?,?)",
            (
                tag_event_id,
                predecessor_fault_tag_id,
                reason_code,
                now,
                command_id,
            ),
        )
        for member in cls.current_members(connection, predecessor_fault_tag_id):
            membership_id = str(member[0])
            state = str(member[6])
            active = int(member[7])
            if active != 1:
                continue
            previous_event = None if member[9] is None else str(member[9])
            membership_event_id = new_uuid4()
            connection.execute(
                "INSERT INTO fault_tag_membership_events("
                "membership_event_id,fault_tag_membership_id,event_kind,effective_at_utc,"
                "target_event_id,reason_code,evidence_kind,evidence_id,recorded_at_utc,command_id"
                ") VALUES (?,?,'superseded',NULL,?,?,NULL,NULL,?,?)",
                (
                    membership_event_id,
                    membership_id,
                    previous_event,
                    reason_code,
                    now,
                    command_id,
                ),
            )
            fingerprint = cls._membership_state_fingerprint(
                membership_id=membership_id,
                rma_id=str(member[1]),
                state="superseded",
                active_submitted=0,
                device_part_unit_id=None if member[3] is None else str(member[3]),
                spare_part_unit_id=None if member[4] is None else str(member[4]),
                last_event_id=membership_event_id,
            )
            changed = connection.execute(
                "UPDATE fault_tag_membership_current SET state='superseded',"
                "active_submitted=0,revision=revision+1,input_fingerprint=?,"
                "last_event_id=?,last_command_id=? "
                "WHERE fault_tag_membership_id=? AND revision=? AND active_submitted=1",
                (
                    fingerprint,
                    membership_event_id,
                    command_id,
                    membership_id,
                    int(member[8]),
                ),
            )
            if changed.rowcount != 1:
                raise SomaError(
                    "INV_STALE",
                    "Fault Tag membership changed during predecessor supersession",
                )
            cls._update_rma_fault_tag_projection(
                connection,
                rma_id=str(member[1]),
                membership_id=None,
                command_id=command_id,
            )
        projection = connection.execute(
            "SELECT revision,archived,current_submission_snapshot_id FROM fault_tag_current_projection "
            "WHERE fault_tag_id=?",
            (predecessor_fault_tag_id,),
        ).fetchone()
        if projection is None:
            raise IntegrityFailure("Fault Tag predecessor projection disappeared")
        revision = int(projection[0]) + 1
        fingerprint = sha256_canonical_json(
            {
                "schema": "SOMA_FAULT_TAG_CURRENT_V1",
                "fault_tag_id": predecessor_fault_tag_id,
                "state": "superseded",
                "archived": int(projection[1]),
                "current_submission_snapshot_id": (
                    None if projection[2] is None else str(projection[2])
                ),
            }
        )
        changed = connection.execute(
            "UPDATE fault_tag_current_projection SET state='superseded',"
            "awaiting_receipt_count=0,awaiting_final_count=0,revision=?,"
            "input_fingerprint=?,last_command_id=? WHERE fault_tag_id=? AND revision=?",
            (
                revision,
                fingerprint,
                command_id,
                predecessor_fault_tag_id,
                int(projection[0]),
            ),
        )
        if changed.rowcount != 1:
            raise SomaError("INV_STALE", "Fault Tag predecessor changed during supersession")
        return tag_event_id, revision

    @classmethod
    def create_lineage_successor(
        cls,
        connection: Any,
        *,
        successor_fault_tag_id: str,
        predecessor_fault_tag_id: str,
        relation_type: str,
        return_method: str,
        pickup_dispatch_location_id: str | None,
        pickup_contact_id: str | None,
        pickup_instructions: str | None,
        memberships: tuple[tuple[str, str], ...],
        reason_code: str,
        command_id: str,
    ) -> tuple[str, str, tuple[str, ...], int]:
        if successor_fault_tag_id == predecessor_fault_tag_id:
            raise SomaError("REPLACEMENT_LINEAGE_CONFLICT", "Fault Tag lineage cannot self-reference")
        if relation_type == "corrects_replaces":
            cls.supersede_for_replacement(
                connection,
                predecessor_fault_tag_id=predecessor_fault_tag_id,
                reason_code=reason_code,
                command_id=command_id,
            )
        elif relation_type == "resend_of":
            cls.require_resend_scope(
                connection,
                predecessor_fault_tag_id=predecessor_fault_tag_id,
                memberships=memberships,
            )
        else:
            raise IntegrityFailure("Unsupported Fault Tag lineage relation")
        sequence, tracking_id = cls.allocate_fault_tag_tracking(connection, command_id)
        _created_event_id, membership_ids, revision = cls.insert_draft(
            connection,
            fault_tag_id=successor_fault_tag_id,
            tracking_sequence=sequence,
            tracking_id=tracking_id,
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
            ") VALUES (?,?,?,?,?,?,?)",
            (
                lineage_id,
                relation_type,
                predecessor_fault_tag_id,
                successor_fault_tag_id,
                reason_code,
                utc_epoch_seconds(),
                command_id,
            ),
        )
        return lineage_id, tracking_id, membership_ids, revision

    @classmethod
    def set_archive_state(
        cls,
        connection: Any,
        *,
        fault_tag_id: str,
        base_revision: int,
        archived: bool,
        reason_code: str | None,
        command_id: str,
    ) -> tuple[str, int]:
        tag = cls.current_tag(connection, fault_tag_id)
        if tag is None or int(tag[10]) != base_revision:
            raise SomaError("INV_STALE", "Fault Tag revision changed")
        if bool(int(tag[8])) == archived:
            raise SomaError("INV_STALE", "Fault Tag archive state already matches requested state")
        event_kind = "archived" if archived else "restored"
        event_id = new_uuid4()
        now = utc_epoch_seconds()
        connection.execute(
            "INSERT INTO fault_tag_lifecycle_events("
            "fault_tag_event_id,fault_tag_id,event_kind,effective_at_utc,target_event_id,"
            "reason_code,evidence_kind,evidence_id,recorded_at_utc,command_id"
            ") VALUES (?,?,?,NULL,NULL,?,NULL,NULL,?,?)",
            (event_id, fault_tag_id, event_kind, reason_code, now, command_id),
        )
        revision = base_revision + 1
        fingerprint = sha256_canonical_json(
            {
                "schema": "SOMA_FAULT_TAG_ARCHIVE_V1",
                "fault_tag_id": fault_tag_id,
                "state": str(tag[7]),
                "archived": 1 if archived else 0,
                "current_submission_snapshot_id": None if tag[9] is None else str(tag[9]),
            }
        )
        changed = connection.execute(
            "UPDATE fault_tag_current_projection SET archived=?,revision=?,"
            "input_fingerprint=?,last_command_id=? WHERE fault_tag_id=? AND revision=?",
            (
                1 if archived else 0,
                revision,
                fingerprint,
                command_id,
                fault_tag_id,
                base_revision,
            ),
        )
        if changed.rowcount != 1:
            raise SomaError("INV_STALE", "Fault Tag changed during archive transition")
        return event_id, revision


__all__ = ["InventoryFaultTagsRepository"]
