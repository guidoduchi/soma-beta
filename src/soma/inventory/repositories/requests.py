from __future__ import annotations

import json
from typing import Any

from soma.foundation.errors import IntegrityFailure, SomaError
from soma.foundation.identifiers import new_uuid4, utc_epoch_seconds
from soma.foundation.strict_json import canonical_json_bytes, sha256_canonical_json


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
    def submission_reference_context(
        connection: Any,
        *,
        receiver_contact_id: str,
        dispatch_location_id: str,
    ) -> dict[str, object]:
        contact = connection.execute(
            "SELECT c.contact_id,c.name,c.revision,c.lifecycle_state,"
            "a.contact_affiliation_id,a.customer_org_id "
            "FROM contacts c LEFT JOIN contact_affiliations a "
            "ON a.contact_id=c.contact_id AND a.is_current=1 "
            "WHERE c.contact_id=?",
            (receiver_contact_id,),
        ).fetchone()
        if contact is None or str(contact[3]) != "active":
            raise SomaError("REQUEST_SUBMISSION_INVALID", "Receiver Contact is not active")
        location = connection.execute(
            "SELECT dispatch_location_id,name,address_mode,standalone_address_text,"
            "lifecycle_state,revision FROM dispatch_locations WHERE dispatch_location_id=?",
            (dispatch_location_id,),
        ).fetchone()
        if location is None or str(location[4]) != "active":
            raise SomaError("REQUEST_SUBMISSION_INVALID", "Dispatch Location is not active")
        if str(location[2]) != "standalone" or location[3] is None:
            raise SomaError(
                "DEPENDENCY_INDETERMINATE",
                "Site-derived Dispatch Location address requires Infrastructure resolution",
            )
        return {
            "receiver_contact_id": str(contact[0]),
            "receiver_display_name_snapshot": str(contact[1]),
            "receiver_contact_revision_at_submission": int(contact[2]),
            "receiver_affiliation_id_at_submission": (
                None if contact[4] is None else str(contact[4])
            ),
            "receiver_customer_org_id_at_submission": (
                None if contact[5] is None else str(contact[5])
            ),
            "dispatch_location_id": str(location[0]),
            "location_name_snapshot": str(location[1]),
            "location_address_snapshot": str(location[3]),
            "dispatch_location_revision_at_submission": int(location[5]),
        }

    @classmethod
    def require_submission_reference_context(
        cls,
        connection: Any,
        *,
        expected: dict[str, object],
    ) -> None:
        current = cls.submission_reference_context(
            connection,
            receiver_contact_id=str(expected["receiver_contact_id"]),
            dispatch_location_id=str(expected["dispatch_location_id"]),
        )
        if current != expected:
            raise SomaError(
                "INV_STALE",
                "Receiver Contact or Dispatch Location changed before submission commit",
            )

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
    def draft_projection_fingerprint(
        *,
        spare_request_id: str,
        service_request_id: str,
        requester_context_sha256: str,
        allocations: tuple[tuple[str, int], ...],
        mode: str,
        receiver_contact_id: str,
        dispatch_location_id: str,
        current_sr7: str | None = None,
        lifecycle_state: str = "draft",
    ) -> str:
        return sha256_canonical_json(
            {
                "schema": "SOMA_SPARE_REQUEST_CURRENT_V1",
                "spare_request_id": spare_request_id,
                "service_request_id": service_request_id,
                "lifecycle_state": lifecycle_state,
                "current_sr7": current_sr7,
                "requester_context_sha256": requester_context_sha256,
                "allocations": [
                    {"spare_need_id": need_id, "quantity": quantity}
                    for need_id, quantity in sorted(allocations)
                ],
                "logistics": {
                    "mode": mode,
                    "receiver_contact_id": receiver_contact_id,
                    "dispatch_location_id": dispatch_location_id,
                },
            }
        )

    # Compatibility alias retained for the original draft-creation call site.
    projection_fingerprint = draft_projection_fingerprint

    @staticmethod
    def submitted_projection_fingerprint(
        *,
        spare_request_id: str,
        current_sr7: str | None,
        submission_snapshot_id: str,
        snapshot_hash: str,
        submitted_quantity: int,
        authorized_rma_count: int,
        response_warning_start_utc: int | None,
        lifecycle_state: str = "submitted_awaiting_response",
    ) -> str:
        return sha256_canonical_json(
            {
                "schema": "SOMA_SPARE_REQUEST_CURRENT_V1",
                "spare_request_id": spare_request_id,
                "lifecycle_state": lifecycle_state,
                "current_sr7": current_sr7,
                "current_submission_snapshot_id": submission_snapshot_id,
                "snapshot_hash": snapshot_hash,
                "submitted_quantity": submitted_quantity,
                "authorized_rma_count": authorized_rma_count,
                "response_warning_start_utc": response_warning_start_utc,
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
        requester_context_sha = sha256_canonical_json(json.loads(requester_context_json))
        fingerprint = cls.draft_projection_fingerprint(
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
            "l.mode,l.receiver_contact_id,l.dispatch_location_id,l.revision,"
            "p.current_submission_snapshot_id,p.submitted_quantity,"
            "p.authorized_rma_count,p.response_warning_start_utc "
            "FROM spare_requests r JOIN spare_request_current_projection p "
            "ON p.spare_request_id=r.spare_request_id "
            "JOIN spare_request_draft_logistics l ON l.spare_request_id=r.spare_request_id "
            "WHERE r.spare_request_id=?",
            (spare_request_id,),
        ).fetchone()

    @staticmethod
    def active_draft_allocations(connection: Any, spare_request_id: str):
        return connection.execute(
            "SELECT a.request_need_allocation_id,a.spare_need_id,a.quantity,a.revision,"
            "n.bom_code,n.bom_key,n.service_request_id,p.lifecycle_state "
            "FROM spare_request_need_allocations a "
            "JOIN spare_needs n ON n.spare_need_id=a.spare_need_id "
            "JOIN spare_need_current_projection p ON p.spare_need_id=a.spare_need_id "
            "WHERE a.spare_request_id=? AND a.active_draft=1 "
            "ORDER BY a.request_need_allocation_id",
            (spare_request_id,),
        ).fetchall()

    @classmethod
    def draft_material(cls, connection: Any, spare_request_id: str) -> dict[str, object]:
        row = cls.current_detail(connection, spare_request_id)
        if row is None:
            raise SomaError("INV_STALE", "Spare Request no longer exists")
        allocations = cls.active_draft_allocations(connection, spare_request_id)
        return {
            "spare_request_id": str(row[0]),
            "tracking_id": str(row[1]),
            "service_request_id": str(row[2]),
            "requester_contact_id": str(row[3]),
            "requester_context_json": str(row[4]),
            "creation_origin": str(row[5]),
            "lifecycle_state": str(row[6]),
            "current_sr7": None if row[7] is None else str(row[7]),
            "revision": int(row[8]),
            "input_fingerprint": str(row[9]),
            "mode": str(row[10]),
            "receiver_contact_id": str(row[11]),
            "dispatch_location_id": str(row[12]),
            "logistics_revision": int(row[13]),
            "current_submission_snapshot_id": (
                None if row[14] is None else str(row[14])
            ),
            "submitted_quantity": int(row[15]),
            "authorized_rma_count": int(row[16]),
            "response_warning_start_utc": (
                None if row[17] is None else int(row[17])
            ),
            "allocations": tuple(
                {
                    "request_need_allocation_id": str(item[0]),
                    "spare_need_id": str(item[1]),
                    "quantity": int(item[2]),
                    "revision": int(item[3]),
                    "bom_code": str(item[4]),
                    "bom_key": str(item[5]),
                    "service_request_id": str(item[6]),
                    "need_lifecycle_state": str(item[7]),
                }
                for item in allocations
            ),
        }

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
        material = cls.draft_material(connection, spare_request_id)
        if material["lifecycle_state"] != "draft":
            raise SomaError("REQUEST_NOT_DRAFT", "Spare Request is not editable Draft")
        if int(material["revision"]) != base_revision:
            raise SomaError("INV_STALE", "Spare Request revision changed")
        cls.require_sr_need_allocations(
            connection,
            service_request_id=str(material["service_request_id"]),
            allocations=allocations,
        )
        cls.require_receiver_and_location(
            connection,
            receiver_contact_id=receiver_contact_id,
            dispatch_location_id=dispatch_location_id,
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
        updated_logistics = connection.execute(
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
        if updated_logistics.rowcount != 1:
            raise IntegrityFailure("Spare Request draft logistics row is missing")
        requester_context_sha = sha256_canonical_json(
            json.loads(str(material["requester_context_json"]))
        )
        fingerprint = cls.draft_projection_fingerprint(
            spare_request_id=spare_request_id,
            service_request_id=str(material["service_request_id"]),
            requester_context_sha256=requester_context_sha,
            allocations=allocations,
            mode=mode,
            receiver_contact_id=receiver_contact_id,
            dispatch_location_id=dispatch_location_id,
        )
        resulting_revision = base_revision + 1
        updated = connection.execute(
            "UPDATE spare_request_current_projection SET revision=?,input_fingerprint=?,"
            "last_command_id=? WHERE spare_request_id=? AND lifecycle_state='draft' "
            "AND revision=?",
            (
                resulting_revision,
                fingerprint,
                command_id,
                spare_request_id,
                base_revision,
            ),
        )
        if updated.rowcount != 1:
            raise SomaError("INV_STALE", "Spare Request changed during Draft update")
        return tuple(allocation_ids), resulting_revision

    @staticmethod
    def _submission_snapshot_hash(
        *,
        spare_request_id: str,
        tracking_id: str,
        mode: str,
        receiver_contact_id: str,
        dispatch_location_id: str,
        location_name_snapshot: str,
        location_address_snapshot: str,
        recipient_context: dict[str, object],
        effective_submission_at_utc: int | None,
        evidence_kind: str | None,
        evidence_id: str | None,
        allocations: tuple[dict[str, object], ...],
    ) -> str:
        return sha256_canonical_json(
            {
                "schema": "SOMA_SPARE_REQUEST_SUBMISSION_SNAPSHOT_V1",
                "spare_request_id": spare_request_id,
                "temporary_tracking_id": tracking_id,
                "mode": mode,
                "receiver_contact_id": receiver_contact_id,
                "dispatch_location_id": dispatch_location_id,
                "location_name_snapshot": location_name_snapshot,
                "location_address_snapshot": location_address_snapshot,
                "recipient_context": recipient_context,
                "effective_submission_at_utc": effective_submission_at_utc,
                "evidence_kind": evidence_kind,
                "evidence_id": evidence_id,
                "allocations": [
                    {
                        "request_need_allocation_id": str(item["request_need_allocation_id"]),
                        "spare_need_id": str(item["spare_need_id"]),
                        "quantity": int(item["quantity"]),
                        "requested_bom_code": str(item["bom_code"]),
                        "requested_bom_key": str(item["bom_key"]),
                    }
                    for item in allocations
                ],
            }
        )

    @classmethod
    def accept_submission(
        cls,
        connection: Any,
        *,
        spare_request_id: str,
        base_revision: int,
        expected_draft_fingerprint: str,
        recipient_context: dict[str, object],
        effective_submission_at_utc: int | None,
        evidence_kind: str | None,
        evidence_id: str | None,
        command_id: str,
    ) -> tuple[str, str, tuple[str, ...], str, int, int]:
        material = cls.draft_material(connection, spare_request_id)
        if material["lifecycle_state"] != "draft":
            raise SomaError("REQUEST_NOT_DRAFT", "Spare Request is not editable Draft")
        if (
            int(material["revision"]) != base_revision
            or str(material["input_fingerprint"]) != expected_draft_fingerprint
        ):
            raise SomaError("INV_STALE", "Spare Request Draft changed before submission")
        allocations = tuple(material["allocations"])
        if not allocations:
            raise SomaError(
                "REQUEST_SUBMISSION_INVALID",
                "Spare Request submission requires at least one allocation",
            )
        for allocation in allocations:
            if str(allocation["service_request_id"]) != str(material["service_request_id"]):
                raise SomaError("NEED_CROSS_SR", "Spare Request allocation crosses Service Requests")
            if str(allocation["need_lifecycle_state"]) != "active":
                raise SomaError(
                    "REQUEST_SUBMISSION_INVALID",
                    "Spare Request allocation Need is not active",
                )
        cls.require_submission_reference_context(
            connection,
            expected=recipient_context,
        )
        now = utc_epoch_seconds()
        warning_start = (
            effective_submission_at_utc
            if effective_submission_at_utc is not None
            else now
        )
        submission_event_id = new_uuid4()
        snapshot_id = new_uuid4()
        recipient_context_payload = {
            "schema": "SUBMISSION_RECIPIENT_V1",
            "receiver_contact_id": str(recipient_context["receiver_contact_id"]),
            "receiver_contact_revision_at_submission": int(
                recipient_context["receiver_contact_revision_at_submission"]
            ),
            "receiver_affiliation_id_at_submission": recipient_context[
                "receiver_affiliation_id_at_submission"
            ],
            "receiver_customer_org_id_at_submission": recipient_context[
                "receiver_customer_org_id_at_submission"
            ],
            "receiver_display_name_snapshot": str(
                recipient_context["receiver_display_name_snapshot"]
            ),
        }
        snapshot_hash = cls._submission_snapshot_hash(
            spare_request_id=spare_request_id,
            tracking_id=str(material["tracking_id"]),
            mode=str(material["mode"]),
            receiver_contact_id=str(material["receiver_contact_id"]),
            dispatch_location_id=str(material["dispatch_location_id"]),
            location_name_snapshot=str(recipient_context["location_name_snapshot"]),
            location_address_snapshot=str(recipient_context["location_address_snapshot"]),
            recipient_context=recipient_context_payload,
            effective_submission_at_utc=effective_submission_at_utc,
            evidence_kind=evidence_kind,
            evidence_id=evidence_id,
            allocations=allocations,
        )
        connection.execute(
            "INSERT INTO spare_request_lifecycle_events("
            "request_event_id,spare_request_id,event_kind,effective_at_utc,target_event_id,"
            "reason_code,evidence_kind,evidence_id,recorded_at_utc,command_id"
            ") VALUES (?,?,'submission_accepted',?,NULL,NULL,?,?,?,?)",
            (
                submission_event_id,
                spare_request_id,
                effective_submission_at_utc,
                evidence_kind,
                evidence_id,
                now,
                command_id,
            ),
        )
        connection.execute(
            "INSERT INTO spare_request_submission_snapshots("
            "submission_snapshot_id,spare_request_id,submission_event_id,temporary_tracking_id,"
            "mode,receiver_contact_id,dispatch_location_id,location_name_snapshot,"
            "location_address_snapshot,recipient_context_json,effective_submission_at_utc,"
            "recorded_at_utc,evidence_kind,evidence_id,snapshot_hash"
            ") VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (
                snapshot_id,
                spare_request_id,
                submission_event_id,
                str(material["tracking_id"]),
                str(material["mode"]),
                str(material["receiver_contact_id"]),
                str(material["dispatch_location_id"]),
                str(recipient_context["location_name_snapshot"]),
                str(recipient_context["location_address_snapshot"]),
                canonical_json_bytes(recipient_context_payload).decode("utf-8"),
                effective_submission_at_utc,
                now,
                evidence_kind,
                evidence_id,
                snapshot_hash,
            ),
        )
        submission_allocation_ids: list[str] = []
        for allocation in allocations:
            submission_allocation_id = new_uuid4()
            connection.execute(
                "INSERT INTO spare_request_submission_allocations("
                "submission_allocation_id,submission_snapshot_id,request_need_allocation_id,"
                "spare_need_id,quantity,requested_bom_code,requested_bom_key"
                ") VALUES (?,?,?,?,?,?,?)",
                (
                    submission_allocation_id,
                    snapshot_id,
                    str(allocation["request_need_allocation_id"]),
                    str(allocation["spare_need_id"]),
                    int(allocation["quantity"]),
                    str(allocation["bom_code"]),
                    str(allocation["bom_key"]),
                ),
            )
            submission_allocation_ids.append(submission_allocation_id)
        submitted_quantity = sum(int(item["quantity"]) for item in allocations)
        resulting_revision = base_revision + 1
        projection_fingerprint = cls.submitted_projection_fingerprint(
            spare_request_id=spare_request_id,
            current_sr7=material["current_sr7"],
            submission_snapshot_id=snapshot_id,
            snapshot_hash=snapshot_hash,
            submitted_quantity=submitted_quantity,
            authorized_rma_count=int(material["authorized_rma_count"]),
            response_warning_start_utc=warning_start,
        )
        updated = connection.execute(
            "UPDATE spare_request_current_projection SET "
            "lifecycle_state='submitted_awaiting_response',"
            "current_submission_snapshot_id=?,submitted_quantity=?,"
            "response_warning_start_utc=?,revision=?,input_fingerprint=?,last_command_id=? "
            "WHERE spare_request_id=? AND lifecycle_state='draft' AND revision=? "
            "AND input_fingerprint=?",
            (
                snapshot_id,
                submitted_quantity,
                warning_start,
                resulting_revision,
                projection_fingerprint,
                command_id,
                spare_request_id,
                base_revision,
                expected_draft_fingerprint,
            ),
        )
        if updated.rowcount != 1:
            raise SomaError("INV_STALE", "Spare Request changed during submission")
        return (
            submission_event_id,
            snapshot_id,
            tuple(submission_allocation_ids),
            snapshot_hash,
            resulting_revision,
            warning_start,
        )

    @classmethod
    def current_submission(cls, connection: Any, spare_request_id: str):
        return connection.execute(
            "SELECT s.submission_snapshot_id,s.submission_event_id,s.evidence_kind,s.evidence_id,"
            "s.snapshot_hash,s.effective_submission_at_utc,p.revision,p.lifecycle_state,"
            "p.current_sr7,p.current_submission_snapshot_id "
            "FROM spare_request_current_projection p "
            "JOIN spare_request_submission_snapshots s "
            "ON s.submission_snapshot_id=p.current_submission_snapshot_id "
            "WHERE p.spare_request_id=?",
            (spare_request_id,),
        ).fetchone()

    @classmethod
    def correct_false_submission(
        cls,
        connection: Any,
        *,
        spare_request_id: str,
        base_revision: int,
        submission_event_id: str,
        reason_code: str,
        command_id: str,
    ) -> tuple[str, str, str, int | None, int, int]:
        material = cls.draft_material(connection, spare_request_id)
        current = cls.current_submission(connection, spare_request_id)
        if (
            current is None
            or str(material["lifecycle_state"]) != "submitted_awaiting_response"
            or int(material["revision"]) != base_revision
        ):
            raise SomaError(
                "CORRECTION_TARGET_INVALID",
                "Spare Request does not have the expected current submission",
            )
        if str(current[1]) != submission_event_id:
            raise SomaError(
                "CORRECTION_TARGET_INVALID",
                "False-submission correction does not target the current submission event",
            )
        if current[2] is not None or current[3] is not None:
            raise SomaError(
                "CORRECTION_TARGET_INVALID",
                "Indexed sent evidence contradicts a false-submission correction",
            )
        if current[8] is not None:
            raise SomaError(
                "CORRECTION_TARGET_INVALID",
                "Official response identity contradicts a false-submission correction",
            )
        if connection.execute(
            "SELECT 1 FROM rmas WHERE spare_request_id=? LIMIT 1",
            (spare_request_id,),
        ).fetchone() is not None:
            raise SomaError(
                "CORRECTION_TARGET_INVALID",
                "RMA authorization contradicts a false-submission correction",
            )
        correction_event_id = new_uuid4()
        now = utc_epoch_seconds()
        connection.execute(
            "INSERT INTO spare_request_lifecycle_events("
            "request_event_id,spare_request_id,event_kind,effective_at_utc,target_event_id,"
            "reason_code,evidence_kind,evidence_id,recorded_at_utc,command_id"
            ") VALUES (?,?,'submission_corrected_false',NULL,?,?,NULL,NULL,?,?)",
            (
                correction_event_id,
                spare_request_id,
                submission_event_id,
                reason_code,
                now,
                command_id,
            ),
        )
        allocations = tuple(
            (str(item["spare_need_id"]), int(item["quantity"]))
            for item in material["allocations"]
        )
        requester_context_sha = sha256_canonical_json(
            json.loads(str(material["requester_context_json"]))
        )
        draft_fingerprint = cls.draft_projection_fingerprint(
            spare_request_id=spare_request_id,
            service_request_id=str(material["service_request_id"]),
            requester_context_sha256=requester_context_sha,
            allocations=allocations,
            mode=str(material["mode"]),
            receiver_contact_id=str(material["receiver_contact_id"]),
            dispatch_location_id=str(material["dispatch_location_id"]),
        )
        resulting_revision = base_revision + 1
        updated = connection.execute(
            "UPDATE spare_request_current_projection SET lifecycle_state='draft',"
            "current_submission_snapshot_id=NULL,submitted_quantity=0,"
            "response_warning_start_utc=NULL,revision=?,input_fingerprint=?,last_command_id=? "
            "WHERE spare_request_id=? AND lifecycle_state='submitted_awaiting_response' "
            "AND revision=? AND current_submission_snapshot_id=?",
            (
                resulting_revision,
                draft_fingerprint,
                command_id,
                spare_request_id,
                base_revision,
                str(current[0]),
            ),
        )
        if updated.rowcount != 1:
            raise SomaError("INV_STALE", "Spare Request changed during false-submission correction")
        allocation_count = connection.execute(
            "SELECT COUNT(*) FROM spare_request_submission_allocations "
            "WHERE submission_snapshot_id=?",
            (str(current[0]),),
        ).fetchone()[0]
        return (
            correction_event_id,
            str(current[0]),
            str(current[4]),
            None if current[5] is None else int(current[5]),
            int(allocation_count),
            resulting_revision,
        )


    @staticmethod
    def sr7_alias_owner(connection: Any, sr7: str):
        return connection.execute(
            "SELECT spare_request_id,alias_kind,source_identifier_event_id "
            "FROM spare_request_identifier_aliases WHERE sr7=?",
            (sr7,),
        ).fetchone()

    @classmethod
    def assign_or_correct_sr7(
        cls,
        connection: Any,
        *,
        spare_request_id: str,
        base_revision: int,
        sr7: str,
        action: str,
        reason_code: str | None,
        command_id: str,
    ) -> tuple[str, str | None, str | None, int]:
        material = cls.draft_material(connection, spare_request_id)
        if int(material["revision"]) != base_revision:
            raise SomaError("INV_STALE", "Spare Request revision changed")
        current_sr7 = material["current_sr7"]
        if action == "assign":
            if current_sr7 is not None:
                raise SomaError("SR7_CONFLICT", "Spare Request already has a current SR7")
            if reason_code is not None:
                raise IntegrityFailure("SR7 assignment unexpectedly carries correction reason")
        elif action == "correct":
            if current_sr7 is None:
                raise SomaError("SR7_CONFLICT", "Spare Request has no current SR7 to correct")
            if reason_code is None:
                raise IntegrityFailure("SR7 correction reason is missing")
        else:
            raise IntegrityFailure("SR7 action escaped domain validation")

        alias = cls.sr7_alias_owner(connection, sr7)
        if alias is not None:
            raise SomaError("SR7_CONFLICT", "Official SR7 is already current or former history")

        identifier_event_id = new_uuid4()
        now = utc_epoch_seconds()
        connection.execute(
            "INSERT INTO spare_request_identifier_events("
            "identifier_event_id,spare_request_id,event_kind,prior_sr7,new_sr7,"
            "reason_code,recorded_at_utc,command_id"
            ") VALUES (?,?,?,?,?,?,?,?)",
            (
                identifier_event_id,
                spare_request_id,
                action,
                current_sr7,
                sr7,
                reason_code,
                now,
                command_id,
            ),
        )
        if current_sr7 is not None:
            updated_alias = connection.execute(
                "UPDATE spare_request_identifier_aliases SET alias_kind='former' "
                "WHERE spare_request_id=? AND sr7=? AND alias_kind='current'",
                (spare_request_id, current_sr7),
            )
            if updated_alias.rowcount != 1:
                raise IntegrityFailure("Current SR7 alias projection is inconsistent")
        alias_id = new_uuid4()
        connection.execute(
            "INSERT INTO spare_request_identifier_aliases("
            "alias_id,spare_request_id,sr7,alias_kind,source_identifier_event_id"
            ") VALUES (?,?,?,'current',?)",
            (
                alias_id,
                spare_request_id,
                sr7,
                identifier_event_id,
            ),
        )

        resulting_state = str(material["lifecycle_state"])
        warning_start = material["response_warning_start_utc"]
        acknowledgement_event_id: str | None = None
        if action == "assign" and resulting_state == "submitted_awaiting_response":
            acknowledgement_event_id = new_uuid4()
            connection.execute(
                "INSERT INTO spare_request_lifecycle_events("
                "request_event_id,spare_request_id,event_kind,effective_at_utc,target_event_id,"
                "reason_code,evidence_kind,evidence_id,recorded_at_utc,command_id"
                ") VALUES (?,?,'acknowledgement_accepted',NULL,NULL,NULL,NULL,NULL,?,?)",
                (
                    acknowledgement_event_id,
                    spare_request_id,
                    now,
                    command_id,
                ),
            )
            resulting_state = "acknowledged"
            warning_start = None

        if material["current_submission_snapshot_id"] is not None:
            snapshot = connection.execute(
                "SELECT snapshot_hash FROM spare_request_submission_snapshots "
                "WHERE submission_snapshot_id=?",
                (str(material["current_submission_snapshot_id"]),),
            ).fetchone()
            if snapshot is None:
                raise IntegrityFailure("Current Spare Request submission snapshot is missing")
            projection_fingerprint = cls.submitted_projection_fingerprint(
                spare_request_id=spare_request_id,
                current_sr7=sr7,
                submission_snapshot_id=str(material["current_submission_snapshot_id"]),
                snapshot_hash=str(snapshot[0]),
                submitted_quantity=int(material["submitted_quantity"]),
                authorized_rma_count=int(material["authorized_rma_count"]),
                response_warning_start_utc=(
                    None if warning_start is None else int(warning_start)
                ),
                lifecycle_state=resulting_state,
            )
        else:
            requester_context_sha = sha256_canonical_json(
                json.loads(str(material["requester_context_json"]))
            )
            allocations = tuple(
                (str(item["spare_need_id"]), int(item["quantity"]))
                for item in material["allocations"]
            )
            projection_fingerprint = cls.draft_projection_fingerprint(
                spare_request_id=spare_request_id,
                service_request_id=str(material["service_request_id"]),
                requester_context_sha256=requester_context_sha,
                allocations=allocations,
                mode=str(material["mode"]),
                receiver_contact_id=str(material["receiver_contact_id"]),
                dispatch_location_id=str(material["dispatch_location_id"]),
                current_sr7=sr7,
                lifecycle_state=resulting_state,
            )

        resulting_revision = base_revision + 1
        updated = connection.execute(
            "UPDATE spare_request_current_projection SET current_sr7=?,"
            "lifecycle_state=?,response_warning_start_utc=?,revision=?,"
            "input_fingerprint=?,last_command_id=? "
            "WHERE spare_request_id=? AND revision=? AND "
            "((current_sr7 IS NULL AND ? IS NULL) OR current_sr7=?)",
            (
                sr7,
                resulting_state,
                warning_start,
                resulting_revision,
                projection_fingerprint,
                command_id,
                spare_request_id,
                base_revision,
                current_sr7,
                current_sr7,
            ),
        )
        if updated.rowcount != 1:
            raise SomaError("INV_STALE", "Spare Request changed during SR7 update")
        return (
            identifier_event_id,
            alias_id,
            acknowledgement_event_id,
            resulting_revision,
        )


__all__ = ["InventoryRequestsRepository"]
