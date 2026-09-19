from __future__ import annotations

from typing import Any

from soma.foundation.errors import IntegrityFailure, SomaError
from soma.foundation.identifiers import new_uuid4, utc_epoch_seconds
from soma.foundation.strict_json import sha256_canonical_json


class InventoryRequestsRepository:
    @staticmethod
    def allocate_spare_request_tracking(
        connection: Any,
        command_id: str,
    ) -> tuple[int, str]:
        row = connection.execute(
            "SELECT next_sequence,revision FROM inventory_tracking_allocators "
            "WHERE allocator_kind='spare_request'"
        ).fetchone()
        if row is None:
            raise IntegrityFailure("Inventory Spare Request allocator is missing")
        sequence = int(row[0])
        revision = int(row[1])
        if sequence >= 100_000_000:
            raise SomaError("INV_INVALID_ID", "Spare Request tracking sequence is exhausted")
        updated = connection.execute(
            "UPDATE inventory_tracking_allocators SET next_sequence=?,revision=?,last_command_id=? "
            "WHERE allocator_kind='spare_request' AND next_sequence=? AND revision=?",
            (sequence + 1, revision + 1, command_id, sequence, revision),
        )
        if updated.rowcount != 1:
            raise SomaError("INV_STALE", "Spare Request allocator changed")
        return sequence, f"SPR-{sequence:08d}"

    @staticmethod
    def requester_authority(connection: Any, contact_id: str):
        return connection.execute(
            "SELECT c.contact_id,c.name,c.revision,c.lifecycle_state,"
            "a.contact_affiliation_id,a.customer_org_id "
            "FROM contacts c LEFT JOIN contact_affiliations a "
            "ON a.contact_id=c.contact_id AND a.is_current=1 "
            "WHERE c.contact_id=?",
            (contact_id,),
        ).fetchone()

    @classmethod
    def require_requester_authority(
        cls,
        connection: Any,
        *,
        contact_id: str,
        expected_revision: int,
        expected_name: str,
        expected_affiliation_id: str | None,
        expected_customer_org_id: str | None,
    ) -> None:
        row = cls.requester_authority(connection, contact_id)
        if row is None or str(row[3]) != "active":
            raise SomaError("REQUEST_SUBMISSION_INVALID", "Requester Contact is not active")
        if (
            int(row[2]) != expected_revision
            or str(row[1]) != expected_name
            or (None if row[4] is None else str(row[4])) != expected_affiliation_id
            or (None if row[5] is None else str(row[5])) != expected_customer_org_id
        ):
            raise SomaError(
                "INV_STALE",
                "Requester Contact/affiliation authority changed before commit",
            )

    @staticmethod
    def require_receiver_and_location(
        connection: Any,
        *,
        receiver_contact_id: str,
        dispatch_location_id: str,
    ) -> None:
        contact = connection.execute(
            "SELECT lifecycle_state FROM contacts WHERE contact_id=?",
            (receiver_contact_id,),
        ).fetchone()
        if contact is None or str(contact[0]) != "active":
            raise SomaError("REQUEST_SUBMISSION_INVALID", "Receiver Contact is not active")
        location = connection.execute(
            "SELECT lifecycle_state FROM dispatch_locations WHERE dispatch_location_id=?",
            (dispatch_location_id,),
        ).fetchone()
        if location is None or str(location[0]) != "active":
            raise SomaError("REQUEST_SUBMISSION_INVALID", "Dispatch Location is not active")

    @staticmethod
    def require_sr_need_allocations(
        connection: Any,
        *,
        service_request_id: str,
        allocations: tuple[tuple[str, int], ...],
    ) -> tuple[tuple[str, str, int], ...]:
        if connection.execute(
            "SELECT 1 FROM service_requests WHERE service_request_id=?",
            (service_request_id,),
        ).fetchone() is None:
            raise SomaError("INV_STALE", "Service Request no longer exists")
        rows: list[tuple[str, str, int]] = []
        for spare_need_id, quantity in allocations:
            row = connection.execute(
                "SELECT n.service_request_id,n.bom_key,p.lifecycle_state,p.revision "
                "FROM spare_needs n JOIN spare_need_current_projection p "
                "ON p.spare_need_id=n.spare_need_id WHERE n.spare_need_id=?",
                (spare_need_id,),
            ).fetchone()
            if row is None:
                raise SomaError("INV_STALE", "Selected Spare Need no longer exists")
            if str(row[0]) != service_request_id:
                raise SomaError("NEED_CROSS_SR", "Selected Spare Needs cross Service Requests")
            if str(row[2]) != "active":
                raise SomaError(
                    "REQUEST_SUBMISSION_INVALID",
                    "Selected Spare Need is not active",
                )
            rows.append((spare_need_id, str(row[1]), int(row[3])))
        return tuple(rows)

    @staticmethod
    def projection_fingerprint(
        *,
        spare_request_id: str,
        service_request_id: str,
        requester_context_sha256: str,
        allocations: tuple[tuple[str, int], ...],
        mode: str,
        receiver_contact_id: str,
        dispatch_location_id: str,
    ) -> str:
        return sha256_canonical_json(
            {
                "schema": "SOMA_SPARE_REQUEST_CURRENT_V1",
                "spare_request_id": spare_request_id,
                "service_request_id": service_request_id,
                "lifecycle_state": "draft",
                "requester_context_sha256": requester_context_sha256,
                "allocations": [
                    {"spare_need_id": need_id, "quantity": quantity}
                    for need_id, quantity in allocations
                ],
                "logistics": {
                    "mode": mode,
                    "receiver_contact_id": receiver_contact_id,
                    "dispatch_location_id": dispatch_location_id,
                },
            }
        )

    @classmethod
    def insert_draft(
        cls,
        connection: Any,
        *,
        spare_request_id: str,
        tracking_sequence: int,
        tracking_id: str,
        service_request_id: str,
        requester_contact_id: str,
        requester_context_json: str,
        creation_origin: str,
        allocations: tuple[tuple[str, int], ...],
        mode: str,
        receiver_contact_id: str,
        dispatch_location_id: str,
        command_id: str,
    ) -> tuple[str, tuple[str, ...], int]:
        now = utc_epoch_seconds()
        connection.execute(
            "INSERT INTO spare_requests("
            "spare_request_id,tracking_sequence,tracking_id,service_request_id,"
            "requester_contact_id,requester_context_json,creation_origin,created_at_utc,"
            "created_command_id"
            ") VALUES (?,?,?,?,?,?,?,?,?)",
            (
                spare_request_id,
                tracking_sequence,
                tracking_id,
                service_request_id,
                requester_contact_id,
                requester_context_json,
                creation_origin,
                now,
                command_id,
            ),
        )
        allocation_ids: list[str] = []
        for spare_need_id, quantity in allocations:
            allocation_id = new_uuid4()
            connection.execute(
                "INSERT INTO spare_request_need_allocations("
                "request_need_allocation_id,spare_request_id,spare_need_id,quantity,revision,"
                "active_draft,created_command_id,last_command_id"
                ") VALUES (?,?,?,?,1,1,?,?)",
                (
                    allocation_id,
                    spare_request_id,
                    spare_need_id,
                    quantity,
                    command_id,
                    command_id,
                ),
            )
            allocation_ids.append(allocation_id)
        connection.execute(
            "INSERT INTO spare_request_draft_logistics("
            "spare_request_id,mode,receiver_contact_id,dispatch_location_id,revision,last_command_id"
            ") VALUES (?,?,?,?,1,?)",
            (
                spare_request_id,
                mode,
                receiver_contact_id,
                dispatch_location_id,
                command_id,
            ),
        )
        event_id = new_uuid4()
        connection.execute(
            "INSERT INTO spare_request_lifecycle_events("
            "request_event_id,spare_request_id,event_kind,effective_at_utc,target_event_id,"
            "reason_code,evidence_kind,evidence_id,recorded_at_utc,command_id"
            ") VALUES (?,?,'created',NULL,NULL,NULL,NULL,NULL,?,?)",
            (event_id, spare_request_id, now, command_id),
        )
        requester_context_sha = sha256_canonical_json(
            __import__("json").loads(requester_context_json)
        )
        fingerprint = cls.projection_fingerprint(
            spare_request_id=spare_request_id,
            service_request_id=service_request_id,
            requester_context_sha256=requester_context_sha,
            allocations=allocations,
            mode=mode,
            receiver_contact_id=receiver_contact_id,
            dispatch_location_id=dispatch_location_id,
        )
        connection.execute(
            "INSERT INTO spare_request_current_projection("
            "spare_request_id,lifecycle_state,current_sr7,current_submission_snapshot_id,"
            "submitted_quantity,authorized_rma_count,response_warning_start_utc,revision,"
            "input_fingerprint,last_command_id"
            ") VALUES (?,'draft',NULL,NULL,0,0,NULL,1,?,?)",
            (spare_request_id, fingerprint, command_id),
        )
        return event_id, tuple(allocation_ids), 1

    @staticmethod
    def current_detail(connection: Any, spare_request_id: str):
        return connection.execute(
            "SELECT r.spare_request_id,r.tracking_id,r.service_request_id,"
            "r.requester_contact_id,r.requester_context_json,r.creation_origin,"
            "p.lifecycle_state,p.current_sr7,p.revision,p.input_fingerprint,"
            "l.mode,l.receiver_contact_id,l.dispatch_location_id,l.revision "
            "FROM spare_requests r JOIN spare_request_current_projection p "
            "ON p.spare_request_id=r.spare_request_id "
            "JOIN spare_request_draft_logistics l ON l.spare_request_id=r.spare_request_id "
            "WHERE r.spare_request_id=?",
            (spare_request_id,),
        ).fetchone()

    @staticmethod
    def active_draft_allocations(connection: Any, spare_request_id: str):
        return connection.execute(
            "SELECT a.request_need_allocation_id,a.spare_need_id,a.quantity,"
            "n.bom_code,n.bom_key,a.revision "
            "FROM spare_request_need_allocations a JOIN spare_needs n "
            "ON n.spare_need_id=a.spare_need_id "
            "WHERE a.spare_request_id=? AND a.active_draft=1 "
            "ORDER BY a.spare_need_id,a.request_need_allocation_id",
            (spare_request_id,),
        ).fetchall()

    @classmethod
    def replace_draft(
        cls,
        connection: Any,
        *,
        spare_request_id: str,
        base_revision: int,
        allocations: tuple[tuple[str, int], ...],
        mode: str,
        receiver_contact_id: str,
        dispatch_location_id: str,
        command_id: str,
    ) -> tuple[tuple[str, ...], int]:
        row = cls.current_detail(connection, spare_request_id)
        if row is None or int(row[8]) != base_revision:
            raise SomaError("INV_STALE", "Spare Request revision changed")
        if str(row[6]) != "draft" or row[7] is not None:
            raise SomaError("REQUEST_NOT_DRAFT", "Spare Request is not editable Draft authority")
        service_request_id = str(row[2])
        cls.require_receiver_and_location(
            connection,
            receiver_contact_id=receiver_contact_id,
            dispatch_location_id=dispatch_location_id,
        )
        cls.require_sr_need_allocations(
            connection,
            service_request_id=service_request_id,
            allocations=allocations,
        )
        connection.execute(
            "UPDATE spare_request_need_allocations "
            "SET active_draft=0,revision=revision+1,last_command_id=? "
            "WHERE spare_request_id=? AND active_draft=1",
            (command_id, spare_request_id),
        )
        allocation_ids: list[str] = []
        for spare_need_id, quantity in allocations:
            allocation_id = new_uuid4()
            connection.execute(
                "INSERT INTO spare_request_need_allocations("
                "request_need_allocation_id,spare_request_id,spare_need_id,quantity,revision,"
                "active_draft,created_command_id,last_command_id"
                ") VALUES (?,?,?,?,1,1,?,?)",
                (
                    allocation_id,
                    spare_request_id,
                    spare_need_id,
                    quantity,
                    command_id,
                    command_id,
                ),
            )
            allocation_ids.append(allocation_id)
        updated = connection.execute(
            "UPDATE spare_request_draft_logistics SET mode=?,receiver_contact_id=?,"
            "dispatch_location_id=?,revision=revision+1,last_command_id=? "
            "WHERE spare_request_id=?",
            (
                mode,
                receiver_contact_id,
                dispatch_location_id,
                command_id,
                spare_request_id,
            ),
        )
        if updated.rowcount != 1:
            raise IntegrityFailure("Spare Request draft logistics disappeared")
        requester_context_sha = sha256_canonical_json(
            __import__("json").loads(str(row[4]))
        )
        fingerprint = cls.projection_fingerprint(
            spare_request_id=spare_request_id,
            service_request_id=service_request_id,
            requester_context_sha256=requester_context_sha,
            allocations=allocations,
            mode=mode,
            receiver_contact_id=receiver_contact_id,
            dispatch_location_id=dispatch_location_id,
        )
        changed = connection.execute(
            "UPDATE spare_request_current_projection "
            "SET revision=revision+1,input_fingerprint=?,last_command_id=? "
            "WHERE spare_request_id=? AND revision=? AND lifecycle_state='draft' "
            "AND current_submission_snapshot_id IS NULL",
            (fingerprint, command_id, spare_request_id, base_revision),
        )
        if changed.rowcount != 1:
            raise SomaError("INV_STALE", "Spare Request changed during draft replacement")
        return tuple(allocation_ids), base_revision + 1

    @staticmethod
    def current_sr7(connection: Any, spare_request_id: str) -> str | None:
        row = connection.execute(
            "SELECT sr7 FROM spare_request_identifier_aliases "
            "WHERE spare_request_id=? AND alias_kind='current'",
            (spare_request_id,),
        ).fetchone()
        return None if row is None else str(row[0])

    @classmethod
    def assign_or_correct_sr7(
        cls,
        connection: Any,
        *,
        spare_request_id: str,
        base_revision: int,
        new_sr7: str,
        action: str,
        reason_code: str | None,
        command_id: str,
    ) -> tuple[str, str | None, int]:
        row = cls.current_detail(connection, spare_request_id)
        if row is None or int(row[8]) != base_revision:
            raise SomaError("INV_STALE", "Spare Request revision changed")
        if str(row[6]) in {"cancelled", "rejected"}:
            raise SomaError("INV_STALE", "Terminal Spare Request cannot change official identity")
        current = cls.current_sr7(connection, spare_request_id)
        if action == "assign":
            if current is not None:
                raise SomaError("INV_STALE", "Spare Request already has an official SR7")
        elif action == "correct":
            if current is None:
                raise SomaError("INV_STALE", "Spare Request has no current SR7 to correct")
        else:
            raise SomaError("INV_INVALID_ID", "Unknown Spare Request identifier action")
        conflict = connection.execute(
            "SELECT spare_request_id,alias_kind FROM spare_request_identifier_aliases WHERE sr7=?",
            (new_sr7,),
        ).fetchone()
        if conflict is not None:
            raise SomaError("SR7_CONFLICT", "SR7 is already current or former authority")
        now = utc_epoch_seconds()
        event_id = new_uuid4()
        connection.execute(
            "INSERT INTO spare_request_identifier_events("
            "identifier_event_id,spare_request_id,event_kind,prior_sr7,new_sr7,reason_code,"
            "recorded_at_utc,command_id"
            ") VALUES (?,?,?,?,?,?,?,?)",
            (
                event_id,
                spare_request_id,
                action,
                current,
                new_sr7,
                reason_code,
                now,
                command_id,
            ),
        )
        if current is not None:
            changed = connection.execute(
                "UPDATE spare_request_identifier_aliases SET alias_kind='former' "
                "WHERE spare_request_id=? AND alias_kind='current' AND sr7=?",
                (spare_request_id, current),
            )
            if changed.rowcount != 1:
                raise IntegrityFailure("Current SR7 alias disappeared during correction")
        connection.execute(
            "INSERT INTO spare_request_identifier_aliases("
            "alias_id,spare_request_id,sr7,alias_kind,source_identifier_event_id"
            ") VALUES (?,? ,?,'current',?)",
            (new_uuid4(), spare_request_id, new_sr7, event_id),
        )
        changed = connection.execute(
            "UPDATE spare_request_current_projection "
            "SET current_sr7=?,revision=revision+1,"
            "input_fingerprint=?,last_command_id=? "
            "WHERE spare_request_id=? AND revision=?",
            (
                new_sr7,
                sha256_canonical_json(
                    {
                        "schema": "SOMA_SPARE_REQUEST_IDENTITY_V1",
                        "spare_request_id": spare_request_id,
                        "current_sr7": new_sr7,
                        "prior_sr7": current,
                    }
                ),
                command_id,
                spare_request_id,
                base_revision,
            ),
        )
        if changed.rowcount != 1:
            raise SomaError("INV_STALE", "Spare Request changed during SR7 update")
        return event_id, current, base_revision + 1

    @classmethod
    def cancel_or_reject(
        cls,
        connection: Any,
        *,
        spare_request_id: str,
        base_revision: int,
        target_state: str,
        reason_code: str,
        command_id: str,
    ) -> tuple[str, int]:
        row = cls.current_detail(connection, spare_request_id)
        if row is None or int(row[8]) != base_revision:
            raise SomaError("INV_STALE", "Spare Request revision changed")
        current_state = str(row[6])
        if current_state in {"cancelled", "rejected"}:
            raise SomaError("INV_STALE", "Spare Request is already terminal")
        obligations = connection.execute(
            "SELECT COUNT(*) FROM rmas WHERE spare_request_id=?",
            (spare_request_id,),
        ).fetchone()
        if obligations is None:
            raise IntegrityFailure("RMA dependency count failed")
        if int(obligations[0]) != 0:
            raise SomaError(
                "REQUEST_SUBMISSION_INVALID",
                "Spare Request has accepted downstream RMA obligations",
            )
        event_id = new_uuid4()
        now = utc_epoch_seconds()
        connection.execute(
            "INSERT INTO spare_request_lifecycle_events("
            "request_event_id,spare_request_id,event_kind,effective_at_utc,target_event_id,"
            "reason_code,evidence_kind,evidence_id,recorded_at_utc,command_id"
            ") VALUES (?,?,?,?,NULL,?,NULL,NULL,?,?)",
            (
                event_id,
                spare_request_id,
                target_state,
                now,
                reason_code,
                now,
                command_id,
            ),
        )
        changed = connection.execute(
            "UPDATE spare_request_current_projection "
            "SET lifecycle_state=?,response_warning_start_utc=NULL,revision=revision+1,"
            "input_fingerprint=?,last_command_id=? "
            "WHERE spare_request_id=? AND revision=?",
            (
                target_state,
                sha256_canonical_json(
                    {
                        "schema": "SOMA_SPARE_REQUEST_TERMINAL_V1",
                        "spare_request_id": spare_request_id,
                        "state": target_state,
                        "reason_code": reason_code,
                    }
                ),
                command_id,
                spare_request_id,
                base_revision,
            ),
        )
        if changed.rowcount != 1:
            raise SomaError("INV_STALE", "Spare Request changed during terminal transition")
        return event_id, base_revision + 1


__all__ = ["InventoryRequestsRepository"]
