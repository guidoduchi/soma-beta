from __future__ import annotations

from dataclasses import dataclass

from soma.foundation.application.command_boundary import CommandBoundary, CommandEnvelope, PreparedMutation
from soma.foundation.audit.writer import AuditEventInput, AuditResultRef, AuditWriter
from soma.foundation.errors import SomaError
from soma.foundation.identifiers import new_uuid4, utc_epoch_seconds
from soma.foundation.persistence.connections import ConnectionFactory
from soma.foundation.persistence.uow import ReadSnapshot, UnitOfWork

from .audit_registry import build_tickets_audit_registry
from .validation import validate_device_reference_name, validate_reason_category


@dataclass(frozen=True, slots=True)
class DeviceReferenceResult:
    device_reference_id: str
    operational_name: str
    revision: int
    replayed: bool
    no_change: bool


class DeviceReferenceService:
    def __init__(self, connection_factory: ConnectionFactory) -> None:
        self._factory = connection_factory
        self._boundary = CommandBoundary(
            connection_factory,
            AuditWriter(build_tickets_audit_registry()),
        )

    def _result(self, device_reference_id: str, *, replayed: bool, no_change: bool) -> DeviceReferenceResult:
        with ReadSnapshot(self._factory) as snapshot:
            row = snapshot.connection.execute(
                "SELECT operational_name,revision FROM device_references WHERE device_reference_id=?",
                (device_reference_id,),
            ).fetchone()
        if row is None:
            raise SomaError("NOT_FOUND", "Device Reference does not exist")
        return DeviceReferenceResult(
            device_reference_id=device_reference_id,
            operational_name=str(row[0]),
            revision=int(row[1]),
            replayed=replayed,
            no_change=no_change,
        )

    def create(
        self,
        *,
        command_id: str,
        operational_name: str,
        actor_kind: str = "local_user",
        actor_id: str | None = None,
    ) -> DeviceReferenceResult:
        stored_name = validate_device_reference_name(operational_name)
        envelope = CommandEnvelope(
            command_id=command_id,
            command_type="CreateDeviceReference",
            target_type="device_reference",
            target_id=None,
            semantic_payload={"operational_name": stored_name},
        )

        def prepare(uow: UnitOfWork) -> PreparedMutation:
            device_reference_id = new_uuid4()
            audit_event_id = new_uuid4()
            now = utc_epoch_seconds()

            def apply(inner: UnitOfWork) -> AuditEventInput:
                inner.connection.execute(
                    "INSERT INTO device_references(device_reference_id,operational_name,revision,created_at_utc,updated_at_utc) "
                    "VALUES (?, ?, 1, ?, ?)",
                    (device_reference_id, stored_name, now, now),
                )
                return AuditEventInput(
                    audit_event_id=audit_event_id,
                    action_type="ticket.device_reference.created",
                    action_version=1,
                    actor_kind=actor_kind,
                    actor_id=actor_id,
                    target_type="device_reference",
                    target_id=device_reference_id,
                    command_id=command_id,
                    payload_schema="DeviceReferenceAuditV1",
                    payload_version=1,
                    payload={
                        "device_reference_id": device_reference_id,
                        "resulting_revision": 1,
                        "change_kind": "created",
                        "relationship_target_type": None,
                        "relationship_target_id": None,
                        "reason_category": None,
                    },
                    resulting_event_refs=(AuditResultRef("device_reference", device_reference_id),),
                )

            return PreparedMutation(False, "device_reference", device_reference_id, apply)

        result = self._boundary.execute(envelope, prepare)
        assert result.result_id is not None
        return self._result(result.result_id, replayed=result.replayed, no_change=result.no_change)

    def correct_name(
        self,
        *,
        command_id: str,
        device_reference_id: str,
        base_revision: int,
        operational_name: str,
        reason_category: str,
        actor_kind: str = "local_user",
        actor_id: str | None = None,
    ) -> DeviceReferenceResult:
        stored_name = validate_device_reference_name(operational_name)
        reason = validate_reason_category(reason_category)
        envelope = CommandEnvelope(
            command_id=command_id,
            command_type="CorrectDeviceReferenceName",
            target_type="device_reference",
            target_id=device_reference_id,
            semantic_payload={"operational_name": stored_name, "reason_category": reason},
            base_revisions={"device_reference": base_revision},
        )

        def prepare(uow: UnitOfWork) -> PreparedMutation:
            row = uow.connection.execute(
                "SELECT operational_name,revision FROM device_references WHERE device_reference_id=?",
                (device_reference_id,),
            ).fetchone()
            if row is None:
                raise SomaError("NOT_FOUND", "Device Reference does not exist")
            if int(row[1]) != base_revision:
                raise SomaError("STALE_REVISION", "Device Reference revision changed")
            if str(row[0]) == stored_name:
                return PreparedMutation(True, None, None)
            audit_event_id = new_uuid4()
            now = utc_epoch_seconds()

            def apply(inner: UnitOfWork) -> AuditEventInput:
                inner.connection.execute(
                    "UPDATE device_references SET operational_name=?,revision=revision+1,updated_at_utc=? "
                    "WHERE device_reference_id=?",
                    (stored_name, now, device_reference_id),
                )
                return AuditEventInput(
                    audit_event_id=audit_event_id,
                    action_type="ticket.device_reference.corrected",
                    action_version=1,
                    actor_kind=actor_kind,
                    actor_id=actor_id,
                    target_type="device_reference",
                    target_id=device_reference_id,
                    reason_category=reason,
                    command_id=command_id,
                    payload_schema="DeviceReferenceAuditV1",
                    payload_version=1,
                    payload={
                        "device_reference_id": device_reference_id,
                        "resulting_revision": base_revision + 1,
                        "change_kind": "corrected",
                        "relationship_target_type": None,
                        "relationship_target_id": None,
                        "reason_category": reason,
                    },
                    resulting_event_refs=(AuditResultRef("device_reference", device_reference_id),),
                )

            return PreparedMutation(False, "device_reference", device_reference_id, apply)

        result = self._boundary.execute(envelope, prepare)
        return self._result(device_reference_id, replayed=result.replayed, no_change=result.no_change)
