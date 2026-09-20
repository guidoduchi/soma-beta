from __future__ import annotations

from typing import Any

from soma.foundation.errors import IntegrityFailure, SomaError
from soma.foundation.identifiers import new_uuid4, utc_epoch_seconds
from soma.foundation.strict_json import sha256_canonical_json

from .requests import InventoryRequestsRepository


class InventoryRmasRepository:
    @staticmethod
    def c10_alias_owner(connection: Any, c10: str):
        return connection.execute(
            "SELECT rma_id,alias_kind,source_identifier_event_id "
            "FROM rma_identifier_aliases WHERE c10=?",
            (c10,),
        ).fetchone()

    @staticmethod
    def request_authority(connection: Any, spare_request_id: str):
        return connection.execute(
            "SELECT r.creation_origin,r.service_request_id,p.lifecycle_state,p.current_sr7,"
            "p.current_submission_snapshot_id,p.submitted_quantity,p.authorized_rma_count,"
            "p.revision,p.response_warning_start_utc "
            "FROM spare_requests r JOIN spare_request_current_projection p "
            "ON p.spare_request_id=r.spare_request_id WHERE r.spare_request_id=?",
            (spare_request_id,),
        ).fetchone()

    @classmethod
    def require_authorization_authority(
        cls,
        connection: Any,
        *,
        spare_request_id: str,
        expected_revision: int,
        batch_count: int,
    ):
        row = cls.request_authority(connection, spare_request_id)
        if row is None:
            raise SomaError("INV_STALE", "Spare Request no longer exists")
        if int(row[7]) != expected_revision:
            raise SomaError("INV_STALE", "Spare Request revision changed")
        if row[3] is None:
            raise SomaError("RMA_REQUIRES_SR7", "RMA authorization requires current official SR7")
        origin = str(row[0])
        if origin != "external_registration" and row[4] is None:
            raise SomaError(
                "REQUEST_SUBMISSION_INVALID",
                "RMA authorization requires accepted submission authority",
            )
        existing_count = connection.execute(
            "SELECT COUNT(*) FROM rmas WHERE spare_request_id=?",
            (spare_request_id,),
        ).fetchone()[0]
        submitted_quantity = int(row[5])
        if origin != "external_registration" and int(existing_count) + batch_count > submitted_quantity:
            raise SomaError(
                "REQUEST_SUBMISSION_INVALID",
                "RMA authorization exceeds submitted request quantity",
            )
        return row

    @staticmethod
    def next_batch_ordinal(connection: Any, spare_request_id: str) -> int:
        row = connection.execute(
            "SELECT COALESCE(MAX(batch_ordinal),0) FROM rma_authorization_batches "
            "WHERE spare_request_id=?",
            (spare_request_id,),
        ).fetchone()
        return int(row[0]) + 1

    @staticmethod
    def eligible_device_targets(
        connection: Any,
        *,
        service_request_id: str,
        promised_bom_key: str,
    ):
        return connection.execute(
            "SELECT d.device_part_unit_id,d.creation_sequence "
            "FROM device_part_units d "
            "LEFT JOIN rma_current_assignment a "
            "ON a.device_part_unit_id=d.device_part_unit_id "
            "WHERE d.service_request_id=? AND d.bom_key=? "
            "AND a.device_part_unit_id IS NULL "
            "ORDER BY d.creation_sequence,d.device_part_unit_id",
            (service_request_id, promised_bom_key),
        ).fetchall()

    @staticmethod
    def rma_lifecycle_fingerprint(
        *,
        rma_id: str,
        current_c10: str,
        state: str,
        target_device_part_unit_id: str | None,
        direct_inbound_spare_part_unit_id: str | None = None,
        return_device_part_unit_id: str | None = None,
        return_spare_part_unit_id: str | None = None,
        return_obligation_open: bool = False,
        active_fault_tag_membership_id: str | None = None,
    ) -> str:
        return sha256_canonical_json(
            {
                "schema": "SOMA_RMA_LIFECYCLE_V1",
                "rma_id": rma_id,
                "current_c10": current_c10,
                "state": state,
                "current_target_device_part_unit_id": target_device_part_unit_id,
                "direct_inbound_spare_part_unit_id": direct_inbound_spare_part_unit_id,
                "return_device_part_unit_id": return_device_part_unit_id,
                "return_spare_part_unit_id": return_spare_part_unit_id,
                "return_obligation_open": return_obligation_open,
                "active_fault_tag_membership_id": active_fault_tag_membership_id,
            }
        )

    @classmethod
    def insert_authorized_rma(
        cls,
        connection: Any,
        *,
        rma_id: str,
        spare_request_id: str,
        authorization_batch_id: str,
        response_ordinal: int,
        c10: str,
        promised_bom_code: str,
        promised_bom_key: str,
        service_request_id: str,
        command_id: str,
    ) -> tuple[str, str, str | None, str | None]:
        now = utc_epoch_seconds()
        connection.execute(
            "INSERT INTO rmas("
            "rma_id,spare_request_id,authorization_batch_id,response_ordinal,"
            "promised_bom_code,promised_bom_key,created_at_utc,created_command_id"
            ") VALUES (?,?,?,?,?,?,?,?)",
            (
                rma_id,
                spare_request_id,
                authorization_batch_id,
                response_ordinal,
                promised_bom_code,
                promised_bom_key,
                now,
                command_id,
            ),
        )
        identifier_event_id = new_uuid4()
        alias_id = new_uuid4()
        connection.execute(
            "INSERT INTO rma_identifier_events("
            "identifier_event_id,rma_id,event_kind,prior_c10,new_c10,reason_code,"
            "recorded_at_utc,command_id"
            ") VALUES (?,?,'assign',NULL,?,NULL,?,?)",
            (identifier_event_id, rma_id, c10, now, command_id),
        )
        connection.execute(
            "INSERT INTO rma_identifier_aliases("
            "alias_id,rma_id,c10,alias_kind,source_identifier_event_id"
            ") VALUES (?,?,?,'current',?)",
            (alias_id, rma_id, c10, identifier_event_id),
        )

        candidates = cls.eligible_device_targets(
            connection,
            service_request_id=service_request_id,
            promised_bom_key=promised_bom_key,
        )
        target_id: str | None = None
        assignment_event_id: str | None = None
        if candidates:
            target_id = str(candidates[0][0])
            assignment_event_id = new_uuid4()
            connection.execute(
                "INSERT INTO rma_assignment_events("
                "assignment_event_id,rma_id,prior_device_part_unit_id,new_device_part_unit_id,"
                "event_kind,reason_code,recorded_at_utc,command_id"
                ") VALUES (?,?,NULL,?,'auto_assign',NULL,?,?)",
                (assignment_event_id, rma_id, target_id, now, command_id),
            )
            connection.execute(
                "INSERT INTO rma_current_assignment("
                "rma_id,device_part_unit_id,assignment_event_id,revision,last_command_id"
                ") VALUES (?,?,?,1,?)",
                (rma_id, target_id, assignment_event_id, command_id),
            )

        lifecycle_fingerprint = cls.rma_lifecycle_fingerprint(
            rma_id=rma_id,
            current_c10=c10,
            state="promised",
            target_device_part_unit_id=target_id,
        )
        connection.execute(
            "INSERT INTO rma_lifecycle_projection("
            "rma_id,state,current_target_device_part_unit_id,direct_inbound_spare_part_unit_id,"
            "return_device_part_unit_id,return_spare_part_unit_id,return_obligation_open,"
            "active_fault_tag_membership_id,revision,input_fingerprint,last_command_id"
            ") VALUES (?,'promised',?,NULL,NULL,NULL,0,NULL,1,?,?)",
            (rma_id, target_id, lifecycle_fingerprint, command_id),
        )
        connection.execute(
            "INSERT INTO rma_return_obligation_current("
            "rma_id,obligation_state,device_part_unit_id,spare_part_unit_id,"
            "physical_consequence_id,revision,last_event_id,last_command_id"
            ") VALUES (?,'not_established',NULL,NULL,NULL,1,NULL,?)",
            (rma_id, command_id),
        )
        if target_id is None:
            attention_id = new_uuid4()
            attention_fingerprint = sha256_canonical_json(
                {
                    "schema": "SOMA_INVENTORY_ATTENTION_V1",
                    "target_kind": "rma",
                    "target_id": rma_id,
                    "attention_kind": "rma_assignment_conflict",
                    "promised_bom_key": promised_bom_key,
                }
            )
            connection.execute(
                "INSERT INTO inventory_attention_projection("
                "attention_id,target_kind,target_id,attention_kind,severity,"
                "input_fingerprint,last_command_id"
                ") VALUES (?,'rma',?,'rma_assignment_conflict','action_required',?,?)",
                (attention_id, rma_id, attention_fingerprint, command_id),
            )
        return identifier_event_id, alias_id, assignment_event_id, target_id

    @classmethod
    def accept_authorization_batch(
        cls,
        connection: Any,
        *,
        spare_request_id: str,
        expected_request_revision: int,
        rows: tuple[tuple[str, str, str], ...],
        accepted_at_utc: int | None,
        evidence_kind: str | None,
        evidence_id: str | None,
        command_id: str,
    ) -> tuple[str, tuple[dict[str, object], ...], int, int]:
        authority = cls.require_authorization_authority(
            connection,
            spare_request_id=spare_request_id,
            expected_revision=expected_request_revision,
            batch_count=len(rows),
        )
        for c10, _promised_bom_code, _promised_bom_key in rows:
            if cls.c10_alias_owner(connection, c10) is not None:
                raise SomaError("C10_CONFLICT", "C10 is already current or former history")

        batch_id = new_uuid4()
        batch_ordinal = cls.next_batch_ordinal(connection, spare_request_id)
        accepted_at = utc_epoch_seconds() if accepted_at_utc is None else accepted_at_utc
        connection.execute(
            "INSERT INTO rma_authorization_batches("
            "authorization_batch_id,spare_request_id,batch_ordinal,accepted_at_utc,"
            "evidence_kind,evidence_id,command_id"
            ") VALUES (?,?,?,?,?,?,?)",
            (
                batch_id,
                spare_request_id,
                batch_ordinal,
                accepted_at,
                evidence_kind,
                evidence_id,
                command_id,
            ),
        )
        created: list[dict[str, object]] = []
        service_request_id = str(authority[1])
        for response_ordinal, (c10, bom_code, bom_key) in enumerate(rows, start=1):
            rma_id = new_uuid4()
            (
                _identifier_event_id,
                _alias_id,
                assignment_event_id,
                target_id,
            ) = cls.insert_authorized_rma(
                connection,
                rma_id=rma_id,
                spare_request_id=spare_request_id,
                authorization_batch_id=batch_id,
                response_ordinal=response_ordinal,
                c10=c10,
                promised_bom_code=bom_code,
                promised_bom_key=bom_key,
                service_request_id=service_request_id,
                command_id=command_id,
            )
            created.append(
                {
                    "rma_id": rma_id,
                    "current_c10": c10,
                    "promised_bom": bom_code,
                    "target_device_part_unit_id": target_id,
                    "assignment_event_id": assignment_event_id,
                }
            )

        total_rmas = int(
            connection.execute(
                "SELECT COUNT(*) FROM rmas WHERE spare_request_id=?",
                (spare_request_id,),
            ).fetchone()[0]
        )
        origin = str(authority[0])
        submitted_quantity = int(authority[5])
        remaining = 0 if origin == "external_registration" else max(
            0,
            submitted_quantity - total_rmas,
        )
        resulting_state = "partially_authorized" if remaining > 0 else "authorized"
        lifecycle_event_id = new_uuid4()
        now = utc_epoch_seconds()
        connection.execute(
            "INSERT INTO spare_request_lifecycle_events("
            "request_event_id,spare_request_id,event_kind,effective_at_utc,target_event_id,"
            "reason_code,evidence_kind,evidence_id,recorded_at_utc,command_id"
            ") VALUES (?,?,'authorization_progress',?,NULL,NULL,?,?,?,?)",
            (
                lifecycle_event_id,
                spare_request_id,
                accepted_at,
                evidence_kind,
                evidence_id,
                now,
                command_id,
            ),
        )

        current_snapshot_id = None if authority[4] is None else str(authority[4])
        if current_snapshot_id is not None:
            snapshot = connection.execute(
                "SELECT snapshot_hash FROM spare_request_submission_snapshots "
                "WHERE submission_snapshot_id=?",
                (current_snapshot_id,),
            ).fetchone()
            if snapshot is None:
                raise IntegrityFailure("Spare Request current submission snapshot is missing")
            request_fingerprint = InventoryRequestsRepository.submitted_projection_fingerprint(
                spare_request_id=spare_request_id,
                current_sr7=str(authority[3]),
                submission_snapshot_id=current_snapshot_id,
                snapshot_hash=str(snapshot[0]),
                submitted_quantity=submitted_quantity,
                authorized_rma_count=total_rmas,
                response_warning_start_utc=None,
                lifecycle_state=resulting_state,
            )
        else:
            material = InventoryRequestsRepository.draft_material(
                connection,
                spare_request_id,
            )
            requester_context_sha = sha256_canonical_json(
                __import__("json").loads(str(material["requester_context_json"]))
            )
            allocation_pairs = tuple(
                (str(item["spare_need_id"]), int(item["quantity"]))
                for item in material["allocations"]
            )
            request_fingerprint = InventoryRequestsRepository.draft_projection_fingerprint(
                spare_request_id=spare_request_id,
                service_request_id=service_request_id,
                requester_context_sha256=requester_context_sha,
                allocations=allocation_pairs,
                mode=str(material["mode"]),
                receiver_contact_id=str(material["receiver_contact_id"]),
                dispatch_location_id=str(material["dispatch_location_id"]),
                current_sr7=str(authority[3]),
                lifecycle_state=resulting_state,
            )

        resulting_request_revision = expected_request_revision + 1
        updated = connection.execute(
            "UPDATE spare_request_current_projection SET lifecycle_state=?,"
            "authorized_rma_count=?,response_warning_start_utc=NULL,revision=?,"
            "input_fingerprint=?,last_command_id=? WHERE spare_request_id=? AND revision=?",
            (
                resulting_state,
                total_rmas,
                resulting_request_revision,
                request_fingerprint,
                command_id,
                spare_request_id,
                expected_request_revision,
            ),
        )
        if updated.rowcount != 1:
            raise SomaError("INV_STALE", "Spare Request changed during RMA authorization")

        connection.execute(
            "DELETE FROM inventory_attention_projection "
            "WHERE target_kind='spare_request' AND target_id=? "
            "AND attention_kind='partial_rma_authorization'",
            (spare_request_id,),
        )
        if remaining > 0:
            attention_id = new_uuid4()
            attention_fingerprint = sha256_canonical_json(
                {
                    "schema": "SOMA_INVENTORY_ATTENTION_V1",
                    "target_kind": "spare_request",
                    "target_id": spare_request_id,
                    "attention_kind": "partial_rma_authorization",
                    "submitted_quantity": submitted_quantity,
                    "authorized_rma_count": total_rmas,
                }
            )
            connection.execute(
                "INSERT INTO inventory_attention_projection("
                "attention_id,target_kind,target_id,attention_kind,severity,"
                "input_fingerprint,last_command_id"
                ") VALUES (?,'spare_request',?,'partial_rma_authorization','warning',?,?)",
                (attention_id, spare_request_id, attention_fingerprint, command_id),
            )
        return batch_id, tuple(created), remaining, resulting_request_revision

    @staticmethod
    def current_rma(connection: Any, rma_id: str):
        return connection.execute(
            "SELECT r.rma_id,r.spare_request_id,r.promised_bom_code,r.promised_bom_key,"
            "a.c10,l.state,l.current_target_device_part_unit_id,"
            "l.direct_inbound_spare_part_unit_id,l.return_device_part_unit_id,"
            "l.return_spare_part_unit_id,l.return_obligation_open,"
            "l.active_fault_tag_membership_id,l.revision,l.input_fingerprint "
            "FROM rmas r JOIN rma_identifier_aliases a "
            "ON a.rma_id=r.rma_id AND a.alias_kind='current' "
            "JOIN rma_lifecycle_projection l ON l.rma_id=r.rma_id "
            "WHERE r.rma_id=?",
            (rma_id,),
        ).fetchone()

    @classmethod
    def correct_c10(
        cls,
        connection: Any,
        *,
        rma_id: str,
        expected_current_c10: str,
        new_c10: str,
        reason_code: str,
        command_id: str,
    ) -> tuple[str, str, int]:
        row = cls.current_rma(connection, rma_id)
        if row is None:
            raise SomaError("INV_STALE", "RMA no longer exists")
        if str(row[4]) != expected_current_c10:
            raise SomaError("INV_STALE", "RMA current C10 changed")
        if cls.c10_alias_owner(connection, new_c10) is not None:
            raise SomaError("C10_CONFLICT", "C10 is already current or former history")
        now = utc_epoch_seconds()
        event_id = new_uuid4()
        alias_id = new_uuid4()
        connection.execute(
            "INSERT INTO rma_identifier_events("
            "identifier_event_id,rma_id,event_kind,prior_c10,new_c10,reason_code,"
            "recorded_at_utc,command_id"
            ") VALUES (?,?,'correct',?,?,?,?,?)",
            (
                event_id,
                rma_id,
                expected_current_c10,
                new_c10,
                reason_code,
                now,
                command_id,
            ),
        )
        updated_old = connection.execute(
            "UPDATE rma_identifier_aliases SET alias_kind='former' "
            "WHERE rma_id=? AND c10=? AND alias_kind='current'",
            (rma_id, expected_current_c10),
        )
        if updated_old.rowcount != 1:
            raise IntegrityFailure("RMA current C10 alias projection is inconsistent")
        connection.execute(
            "INSERT INTO rma_identifier_aliases("
            "alias_id,rma_id,c10,alias_kind,source_identifier_event_id"
            ") VALUES (?,?,?,'current',?)",
            (alias_id, rma_id, new_c10, event_id),
        )
        resulting_revision = int(row[12]) + 1
        fingerprint = cls.rma_lifecycle_fingerprint(
            rma_id=rma_id,
            current_c10=new_c10,
            state=str(row[5]),
            target_device_part_unit_id=None if row[6] is None else str(row[6]),
            direct_inbound_spare_part_unit_id=None if row[7] is None else str(row[7]),
            return_device_part_unit_id=None if row[8] is None else str(row[8]),
            return_spare_part_unit_id=None if row[9] is None else str(row[9]),
            return_obligation_open=bool(row[10]),
            active_fault_tag_membership_id=None if row[11] is None else str(row[11]),
        )
        updated = connection.execute(
            "UPDATE rma_lifecycle_projection SET revision=?,input_fingerprint=?,"
            "last_command_id=? WHERE rma_id=? AND revision=?",
            (
                resulting_revision,
                fingerprint,
                command_id,
                rma_id,
                int(row[12]),
            ),
        )
        if updated.rowcount != 1:
            raise SomaError("INV_STALE", "RMA lifecycle changed during C10 correction")
        return event_id, alias_id, resulting_revision

    @classmethod
    def set_target_assignment(
        cls,
        connection: Any,
        *,
        rma_id: str,
        expected_assignment_revision: int | None,
        new_target_device_part_unit_id: str | None,
        reason_code: str,
        command_id: str,
    ) -> tuple[str, str | None, int]:
        rma = cls.current_rma(connection, rma_id)
        if rma is None:
            raise SomaError("INV_STALE", "RMA no longer exists")
        request = connection.execute(
            "SELECT service_request_id FROM spare_requests WHERE spare_request_id=?",
            (str(rma[1]),),
        ).fetchone()
        if request is None:
            raise IntegrityFailure("RMA parent Spare Request is missing")
        current = connection.execute(
            "SELECT device_part_unit_id,assignment_event_id,revision "
            "FROM rma_current_assignment WHERE rma_id=?",
            (rma_id,),
        ).fetchone()
        if expected_assignment_revision is None:
            if current is not None:
                raise SomaError("INV_STALE", "RMA assignment was created")
        elif current is None or int(current[2]) != expected_assignment_revision:
            raise SomaError("INV_STALE", "RMA assignment revision changed")

        prior_target = None if current is None else str(current[0])
        if new_target_device_part_unit_id is not None:
            target = connection.execute(
                "SELECT service_request_id,bom_key FROM device_part_units "
                "WHERE device_part_unit_id=?",
                (new_target_device_part_unit_id,),
            ).fetchone()
            if (
                target is None
                or str(target[0]) != str(request[0])
                or str(target[1]) != str(rma[3])
            ):
                raise SomaError(
                    "RMA_TARGET_INCOMPATIBLE",
                    "RMA target is not compatible with request SR/BOM",
                )
            conflict = connection.execute(
                "SELECT rma_id FROM rma_current_assignment "
                "WHERE device_part_unit_id=? AND rma_id<>?",
                (new_target_device_part_unit_id, rma_id),
            ).fetchone()
            if conflict is not None:
                raise SomaError(
                    "RMA_TARGET_INCOMPATIBLE",
                    "RMA target is already assigned to another RMA",
                )
        if prior_target == new_target_device_part_unit_id:
            raise SomaError("INV_STALE", "RMA assignment is already the requested target")

        if prior_target is None:
            event_kind = "manual_assign" if new_target_device_part_unit_id is not None else "clear"
        elif new_target_device_part_unit_id is None:
            event_kind = "clear"
        else:
            event_kind = "reassign"
        event_id = new_uuid4()
        now = utc_epoch_seconds()
        connection.execute(
            "INSERT INTO rma_assignment_events("
            "assignment_event_id,rma_id,prior_device_part_unit_id,new_device_part_unit_id,"
            "event_kind,reason_code,recorded_at_utc,command_id"
            ") VALUES (?,?,?,?,?,?,?,?)",
            (
                event_id,
                rma_id,
                prior_target,
                new_target_device_part_unit_id,
                event_kind,
                reason_code,
                now,
                command_id,
            ),
        )
        if new_target_device_part_unit_id is None:
            if current is not None:
                connection.execute(
                    "DELETE FROM rma_current_assignment WHERE rma_id=?",
                    (rma_id,),
                )
            assignment_revision = 0 if expected_assignment_revision is None else expected_assignment_revision + 1
        elif current is None:
            assignment_revision = 1
            connection.execute(
                "INSERT INTO rma_current_assignment("
                "rma_id,device_part_unit_id,assignment_event_id,revision,last_command_id"
                ") VALUES (?,?,?,?,?)",
                (
                    rma_id,
                    new_target_device_part_unit_id,
                    event_id,
                    assignment_revision,
                    command_id,
                ),
            )
        else:
            assignment_revision = int(current[2]) + 1
            updated_assignment = connection.execute(
                "UPDATE rma_current_assignment SET device_part_unit_id=?,assignment_event_id=?,"
                "revision=?,last_command_id=? WHERE rma_id=? AND revision=?",
                (
                    new_target_device_part_unit_id,
                    event_id,
                    assignment_revision,
                    command_id,
                    rma_id,
                    int(current[2]),
                ),
            )
            if updated_assignment.rowcount != 1:
                raise SomaError("INV_STALE", "RMA assignment changed during update")

        lifecycle_revision = int(rma[12]) + 1
        fingerprint = cls.rma_lifecycle_fingerprint(
            rma_id=rma_id,
            current_c10=str(rma[4]),
            state=str(rma[5]),
            target_device_part_unit_id=new_target_device_part_unit_id,
            direct_inbound_spare_part_unit_id=None if rma[7] is None else str(rma[7]),
            return_device_part_unit_id=None if rma[8] is None else str(rma[8]),
            return_spare_part_unit_id=None if rma[9] is None else str(rma[9]),
            return_obligation_open=bool(rma[10]),
            active_fault_tag_membership_id=None if rma[11] is None else str(rma[11]),
        )
        updated_lifecycle = connection.execute(
            "UPDATE rma_lifecycle_projection SET current_target_device_part_unit_id=?,"
            "revision=?,input_fingerprint=?,last_command_id=? "
            "WHERE rma_id=? AND revision=?",
            (
                new_target_device_part_unit_id,
                lifecycle_revision,
                fingerprint,
                command_id,
                rma_id,
                int(rma[12]),
            ),
        )
        if updated_lifecycle.rowcount != 1:
            raise SomaError("INV_STALE", "RMA lifecycle changed during assignment update")

        connection.execute(
            "DELETE FROM inventory_attention_projection "
            "WHERE target_kind='rma' AND target_id=? "
            "AND attention_kind='rma_assignment_conflict'",
            (rma_id,),
        )
        if new_target_device_part_unit_id is None:
            attention_id = new_uuid4()
            attention_fingerprint = sha256_canonical_json(
                {
                    "schema": "SOMA_INVENTORY_ATTENTION_V1",
                    "target_kind": "rma",
                    "target_id": rma_id,
                    "attention_kind": "rma_assignment_conflict",
                    "promised_bom_key": str(rma[3]),
                }
            )
            connection.execute(
                "INSERT INTO inventory_attention_projection("
                "attention_id,target_kind,target_id,attention_kind,severity,"
                "input_fingerprint,last_command_id"
                ") VALUES (?,'rma',?,'rma_assignment_conflict','action_required',?,?)",
                (attention_id, rma_id, attention_fingerprint, command_id),
            )
        return event_id, new_target_device_part_unit_id, lifecycle_revision


__all__ = ["InventoryRmasRepository"]
