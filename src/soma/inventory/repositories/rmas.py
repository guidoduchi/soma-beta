from __future__ import annotations

from typing import Any

from soma.foundation.errors import IntegrityFailure, SomaError
from soma.foundation.identifiers import new_uuid4, utc_epoch_seconds
from soma.foundation.strict_json import sha256_canonical_json


class InventoryRmasRepository:
    @staticmethod
    def request_authorization_state(connection: Any, spare_request_id: str):
        return connection.execute(
            "SELECT r.service_request_id,r.creation_origin,p.lifecycle_state,p.current_sr7,"
            "p.current_submission_snapshot_id,p.submitted_quantity,p.authorized_rma_count,"
            "p.revision,p.input_fingerprint "
            "FROM spare_requests r JOIN spare_request_current_projection p "
            "ON p.spare_request_id=r.spare_request_id WHERE r.spare_request_id=?",
            (spare_request_id,),
        ).fetchone()

    @staticmethod
    def c10_owner(connection: Any, c10: str):
        return connection.execute(
            "SELECT rma_id,alias_kind FROM rma_identifier_aliases WHERE c10=?",
            (c10,),
        ).fetchone()

    @classmethod
    def require_batch_eligible(
        cls,
        connection: Any,
        *,
        spare_request_id: str,
        expected_request_revision: int,
        rows: tuple[tuple[str, str, str], ...],
    ):
        state = cls.request_authorization_state(connection, spare_request_id)
        if state is None or int(state[7]) != expected_request_revision:
            raise SomaError("INV_STALE", "Spare Request revision changed")
        if state[3] is None:
            raise SomaError("RMA_REQUIRES_SR7", "RMA authorization requires current SR7")
        if state[4] is None and str(state[1]) != "external_registration":
            raise SomaError(
                "REQUEST_SUBMISSION_INVALID",
                "RMA authorization requires accepted submission authority",
            )
        if str(state[2]) in {"cancelled", "rejected"}:
            raise SomaError("REQUEST_SUBMISSION_INVALID", "Terminal request cannot authorize RMA")
        for c10, _bom_code, _bom_key in rows:
            if cls.c10_owner(connection, c10) is not None:
                raise SomaError("C10_CONFLICT", "C10 is already current or former authority")
        return state

    @staticmethod
    def _eligible_target(
        connection: Any,
        *,
        spare_request_id: str,
        bom_key: str,
    ) -> str | None:
        row = connection.execute(
            "SELECT d.device_part_unit_id "
            "FROM spare_requests r JOIN device_part_units d "
            "ON d.service_request_id=r.service_request_id "
            "WHERE r.spare_request_id=? AND d.bom_key=? "
            "AND NOT EXISTS ("
            "SELECT 1 FROM rma_current_assignment a "
            "WHERE a.device_part_unit_id=d.device_part_unit_id"
            ") ORDER BY d.creation_sequence,d.device_part_unit_id LIMIT 1",
            (spare_request_id, bom_key),
        ).fetchone()
        return None if row is None else str(row[0])

    @staticmethod
    def _rma_projection_fingerprint(
        *,
        rma_id: str,
        state: str,
        target_device_part_unit_id: str | None,
        current_c10: str,
    ) -> str:
        return sha256_canonical_json(
            {
                "schema": "SOMA_RMA_LIFECYCLE_V1",
                "rma_id": rma_id,
                "state": state,
                "current_target_device_part_unit_id": target_device_part_unit_id,
                "direct_inbound_spare_part_unit_id": None,
                "return_device_part_unit_id": None,
                "return_spare_part_unit_id": None,
                "return_obligation_open": 0,
                "active_fault_tag_membership_id": None,
                "current_c10": current_c10,
            }
        )

    @classmethod
    def accept_authorization_batch(
        cls,
        connection: Any,
        *,
        spare_request_id: str,
        expected_request_revision: int,
        rows: tuple[tuple[str, str, str], ...],
        accepted_at_utc: int,
        evidence_kind: str | None,
        evidence_id: str | None,
        command_id: str,
    ) -> tuple[str, tuple[dict[str, object], ...], int, int]:
        request_state = cls.require_batch_eligible(
            connection,
            spare_request_id=spare_request_id,
            expected_request_revision=expected_request_revision,
            rows=rows,
        )
        batch_row = connection.execute(
            "SELECT COALESCE(MAX(batch_ordinal),0) FROM rma_authorization_batches "
            "WHERE spare_request_id=?",
            (spare_request_id,),
        ).fetchone()
        if batch_row is None:
            raise IntegrityFailure("RMA authorization batch ordinal query failed")
        batch_ordinal = int(batch_row[0]) + 1
        batch_id = new_uuid4()
        connection.execute(
            "INSERT INTO rma_authorization_batches("
            "authorization_batch_id,spare_request_id,batch_ordinal,accepted_at_utc,"
            "evidence_kind,evidence_id,command_id"
            ") VALUES (?,?,?,?,?,?,?)",
            (
                batch_id,
                spare_request_id,
                batch_ordinal,
                accepted_at_utc,
                evidence_kind,
                evidence_id,
                command_id,
            ),
        )
        now = utc_epoch_seconds()
        created: list[dict[str, object]] = []
        for response_ordinal, (c10, bom_code, bom_key) in enumerate(rows, start=1):
            rma_id = new_uuid4()
            connection.execute(
                "INSERT INTO rmas("
                "rma_id,spare_request_id,authorization_batch_id,response_ordinal,"
                "promised_bom_code,promised_bom_key,created_at_utc,created_command_id"
                ") VALUES (?,?,?,?,?,?,?,?)",
                (
                    rma_id,
                    spare_request_id,
                    batch_id,
                    response_ordinal,
                    bom_code,
                    bom_key,
                    now,
                    command_id,
                ),
            )
            identifier_event_id = new_uuid4()
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
                ") VALUES (?,? ,?,'current',?)",
                (new_uuid4(), rma_id, c10, identifier_event_id),
            )
            target_id = cls._eligible_target(
                connection,
                spare_request_id=spare_request_id,
                bom_key=bom_key,
            )
            assignment_id = None
            if target_id is not None:
                assignment_id = new_uuid4()
                connection.execute(
                    "INSERT INTO rma_assignment_events("
                    "assignment_event_id,rma_id,prior_device_part_unit_id,"
                    "new_device_part_unit_id,event_kind,reason_code,recorded_at_utc,command_id"
                    ") VALUES (?,?,NULL,?,'auto_assign',NULL,?,?)",
                    (assignment_id, rma_id, target_id, now, command_id),
                )
                connection.execute(
                    "INSERT INTO rma_current_assignment("
                    "rma_id,device_part_unit_id,assignment_event_id,revision,last_command_id"
                    ") VALUES (?,?,?,1,?)",
                    (rma_id, target_id, assignment_id, command_id),
                )
            fingerprint = cls._rma_projection_fingerprint(
                rma_id=rma_id,
                state="promised",
                target_device_part_unit_id=target_id,
                current_c10=c10,
            )
            connection.execute(
                "INSERT INTO rma_lifecycle_projection("
                "rma_id,state,current_target_device_part_unit_id,"
                "direct_inbound_spare_part_unit_id,return_device_part_unit_id,"
                "return_spare_part_unit_id,return_obligation_open,"
                "active_fault_tag_membership_id,revision,input_fingerprint,last_command_id"
                ") VALUES (?,'promised',?,NULL,NULL,NULL,0,NULL,1,?,?)",
                (rma_id, target_id, fingerprint, command_id),
            )
            created.append(
                {
                    "rma_id": rma_id,
                    "current_c10": c10,
                    "state": "promised",
                    "promised_bom": bom_code,
                    "direct_inbound_unit_id": None,
                    "target_device_part_unit_id": target_id,
                    "assignment_event_id": assignment_id,
                    "revision": 1,
                }
            )
        progress_event_id = new_uuid4()
        connection.execute(
            "INSERT INTO spare_request_lifecycle_events("
            "request_event_id,spare_request_id,event_kind,effective_at_utc,target_event_id,"
            "reason_code,evidence_kind,evidence_id,recorded_at_utc,command_id"
            ") VALUES (?,?,'authorization_progress',?,NULL,NULL,?,?,?,?)",
            (
                progress_event_id,
                spare_request_id,
                accepted_at_utc,
                evidence_kind,
                evidence_id,
                now,
                command_id,
            ),
        )
        total_authorized = int(request_state[6]) + len(created)
        submitted_quantity = int(request_state[5])
        next_state = (
            "partially_authorized"
            if submitted_quantity > 0 and total_authorized < submitted_quantity
            else "authorized"
        )
        resulting_revision = expected_request_revision + 1
        request_fingerprint = sha256_canonical_json(
            {
                "schema": "SOMA_SPARE_REQUEST_AUTHORIZATION_V1",
                "spare_request_id": spare_request_id,
                "current_sr7": str(request_state[3]),
                "current_submission_snapshot_id": (
                    None if request_state[4] is None else str(request_state[4])
                ),
                "submitted_quantity": submitted_quantity,
                "authorized_rma_count": total_authorized,
                "lifecycle_state": next_state,
                "authorization_batch_id": batch_id,
            }
        )
        changed = connection.execute(
            "UPDATE spare_request_current_projection "
            "SET lifecycle_state=?,authorized_rma_count=?,revision=?,input_fingerprint=?,"
            "last_command_id=? WHERE spare_request_id=? AND revision=?",
            (
                next_state,
                total_authorized,
                resulting_revision,
                request_fingerprint,
                command_id,
                spare_request_id,
                expected_request_revision,
            ),
        )
        if changed.rowcount != 1:
            raise SomaError("INV_STALE", "Spare Request changed during RMA authorization")
        remaining = max(submitted_quantity - total_authorized, 0)
        return batch_id, tuple(created), resulting_revision, remaining

    @staticmethod
    def current_rma(connection: Any, rma_id: str):
        return connection.execute(
            "SELECT r.rma_id,r.spare_request_id,r.promised_bom_code,r.promised_bom_key,"
            "req.service_request_id,a.c10,p.state,p.current_target_device_part_unit_id,"
            "p.direct_inbound_spare_part_unit_id,p.revision,p.input_fingerprint "
            "FROM rmas r JOIN spare_requests req ON req.spare_request_id=r.spare_request_id "
            "JOIN rma_identifier_aliases a ON a.rma_id=r.rma_id AND a.alias_kind='current' "
            "JOIN rma_lifecycle_projection p ON p.rma_id=r.rma_id WHERE r.rma_id=?",
            (rma_id,),
        ).fetchone()

    @classmethod
    def correct_c10(
        cls,
        connection: Any,
        *,
        rma_id: str,
        current_c10: str,
        new_c10: str,
        reason_code: str,
        command_id: str,
    ) -> tuple[str, int]:
        row = cls.current_rma(connection, rma_id)
        if row is None:
            raise SomaError("INV_STALE", "RMA no longer exists")
        if str(row[5]) != current_c10:
            raise SomaError("INV_STALE", "RMA current C10 changed")
        if cls.c10_owner(connection, new_c10) is not None:
            raise SomaError("C10_CONFLICT", "C10 is already current or former authority")
        now = utc_epoch_seconds()
        event_id = new_uuid4()
        connection.execute(
            "INSERT INTO rma_identifier_events("
            "identifier_event_id,rma_id,event_kind,prior_c10,new_c10,reason_code,"
            "recorded_at_utc,command_id"
            ") VALUES (?,?,'correct',?,?,?,?,?)",
            (event_id, rma_id, current_c10, new_c10, reason_code, now, command_id),
        )
        changed = connection.execute(
            "UPDATE rma_identifier_aliases SET alias_kind='former' "
            "WHERE rma_id=? AND c10=? AND alias_kind='current'",
            (rma_id, current_c10),
        )
        if changed.rowcount != 1:
            raise IntegrityFailure("RMA current C10 alias disappeared")
        connection.execute(
            "INSERT INTO rma_identifier_aliases("
            "alias_id,rma_id,c10,alias_kind,source_identifier_event_id"
            ") VALUES (?,? ,?,'current',?)",
            (new_uuid4(), rma_id, new_c10, event_id),
        )
        revision = int(row[9]) + 1
        fingerprint = cls._rma_projection_fingerprint(
            rma_id=rma_id,
            state=str(row[6]),
            target_device_part_unit_id=None if row[7] is None else str(row[7]),
            current_c10=new_c10,
        )
        updated = connection.execute(
            "UPDATE rma_lifecycle_projection SET revision=?,input_fingerprint=?,last_command_id=? "
            "WHERE rma_id=? AND revision=?",
            (revision, fingerprint, command_id, rma_id, int(row[9])),
        )
        if updated.rowcount != 1:
            raise SomaError("INV_STALE", "RMA changed during C10 correction")
        return event_id, revision

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
    ) -> tuple[str, int, int | None]:
        row = cls.current_rma(connection, rma_id)
        if row is None:
            raise SomaError("INV_STALE", "RMA no longer exists")
        current = connection.execute(
            "SELECT device_part_unit_id,revision FROM rma_current_assignment WHERE rma_id=?",
            (rma_id,),
        ).fetchone()
        if expected_assignment_revision is None:
            if current is not None:
                raise SomaError("INV_STALE", "RMA assignment appeared")
        else:
            if current is None or int(current[1]) != expected_assignment_revision:
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
                or str(target[0]) != str(row[4])
                or str(target[1]) != str(row[3])
            ):
                raise SomaError(
                    "RMA_TARGET_INCOMPATIBLE",
                    "RMA target must belong to the same SR and promised BOM",
                )
            owner = connection.execute(
                "SELECT rma_id FROM rma_current_assignment "
                "WHERE device_part_unit_id=? AND rma_id<>?",
                (new_target_device_part_unit_id, rma_id),
            ).fetchone()
            if owner is not None:
                raise SomaError(
                    "RMA_TARGET_INCOMPATIBLE",
                    "Device Part Unit is already assigned to another RMA",
                )
        now = utc_epoch_seconds()
        event_id = new_uuid4()
        if prior_target is None and new_target_device_part_unit_id is not None:
            event_kind = "manual_assign"
        elif prior_target is not None and new_target_device_part_unit_id is None:
            event_kind = "clear"
        else:
            event_kind = "reassign"
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
        assignment_revision: int | None
        if new_target_device_part_unit_id is None:
            if current is not None:
                deleted = connection.execute(
                    "DELETE FROM rma_current_assignment WHERE rma_id=? AND revision=?",
                    (rma_id, int(current[1])),
                )
                if deleted.rowcount != 1:
                    raise SomaError("INV_STALE", "RMA assignment changed during clear")
            assignment_revision = None
        elif current is None:
            connection.execute(
                "INSERT INTO rma_current_assignment("
                "rma_id,device_part_unit_id,assignment_event_id,revision,last_command_id"
                ") VALUES (?,?,?,1,?)",
                (rma_id, new_target_device_part_unit_id, event_id, command_id),
            )
            assignment_revision = 1
        else:
            assignment_revision = int(current[1]) + 1
            changed = connection.execute(
                "UPDATE rma_current_assignment SET device_part_unit_id=?,assignment_event_id=?,"
                "revision=?,last_command_id=? WHERE rma_id=? AND revision=?",
                (
                    new_target_device_part_unit_id,
                    event_id,
                    assignment_revision,
                    command_id,
                    rma_id,
                    int(current[1]),
                ),
            )
            if changed.rowcount != 1:
                raise SomaError("INV_STALE", "RMA assignment changed during reassignment")
        lifecycle_revision = int(row[9]) + 1
        fingerprint = cls._rma_projection_fingerprint(
            rma_id=rma_id,
            state=str(row[6]),
            target_device_part_unit_id=new_target_device_part_unit_id,
            current_c10=str(row[5]),
        )
        changed = connection.execute(
            "UPDATE rma_lifecycle_projection SET current_target_device_part_unit_id=?,"
            "revision=?,input_fingerprint=?,last_command_id=? WHERE rma_id=? AND revision=?",
            (
                new_target_device_part_unit_id,
                lifecycle_revision,
                fingerprint,
                command_id,
                rma_id,
                int(row[9]),
            ),
        )
        if changed.rowcount != 1:
            raise SomaError("INV_STALE", "RMA lifecycle changed during assignment")
        return event_id, lifecycle_revision, assignment_revision


__all__ = ["InventoryRmasRepository"]
