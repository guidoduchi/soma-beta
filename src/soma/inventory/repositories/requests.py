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


__all__ = ["InventoryRequestsRepository"]
