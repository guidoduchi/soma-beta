from __future__ import annotations

from dataclasses import dataclass

from soma.foundation.application.command_boundary import CommandBoundary, CommandEnvelope, PreparedMutation
from soma.foundation.audit.writer import AuditEventInput, AuditResultRef, AuditWriter
from soma.foundation.errors import SomaError, ValidationError
from soma.foundation.identifiers import new_uuid4, utc_epoch_seconds
from soma.foundation.persistence.connections import ConnectionFactory
from soma.foundation.persistence.uow import ReadSnapshot, UnitOfWork

from .audit_registry import build_tickets_audit_registry
from .validation import validate_reason_category


_TICKET_TARGETS = {
    "service_request": ("service_requests", "service_request_id", "sr_device_reference_links", "sr_device_reference_link_id"),
    "rfc": ("rfcs", "rfc_id", "rfc_device_reference_links", "rfc_device_reference_link_id"),
}


@dataclass(frozen=True, slots=True)
class TicketDeviceReferenceRelationshipResult:
    relationship_id: str | None
    ticket_type: str
    ticket_id: str
    device_reference_id: str
    state: str
    target_revision: int
    replayed: bool
    no_change: bool


class TicketDeviceReferenceRelationshipService:
    def __init__(self, connection_factory: ConnectionFactory) -> None:
        self._factory = connection_factory
        self._boundary = CommandBoundary(
            connection_factory,
            AuditWriter(build_tickets_audit_registry()),
        )

    @staticmethod
    def _target_spec(ticket_type: str) -> tuple[str, str, str, str]:
        try:
            return _TICKET_TARGETS[ticket_type]
        except KeyError as exc:
            raise ValidationError("ticket_type must be service_request or rfc") from exc

    @staticmethod
    def _optional_reason(value: str | None) -> str | None:
        if value is None:
            return None
        return validate_reason_category(value)

    @staticmethod
    def _load_target_revision(connection, table: str, id_column: str, ticket_id: str) -> int:
        row = connection.execute(
            f"SELECT revision FROM {table} WHERE {id_column}=?",
            (ticket_id,),
        ).fetchone()
        if row is None:
            raise SomaError("NOT_FOUND", "Ticket does not exist")
        return int(row[0])

    @staticmethod
    def _require_device_reference(connection, device_reference_id: str) -> None:
        row = connection.execute(
            "SELECT 1 FROM device_references WHERE device_reference_id=?",
            (device_reference_id,),
        ).fetchone()
        if row is None:
            raise SomaError("NOT_FOUND", "Device Reference does not exist")

    def _result(
        self,
        *,
        ticket_type: str,
        ticket_id: str,
        device_reference_id: str,
        fallback_relationship_id: str | None,
        replayed: bool,
        no_change: bool,
    ) -> TicketDeviceReferenceRelationshipResult:
        target_table, target_id_column, link_table, link_id_column = self._target_spec(ticket_type)
        owner_column = "service_request_id" if ticket_type == "service_request" else "rfc_id"
        with ReadSnapshot(self._factory) as snapshot:
            revision = self._load_target_revision(
                snapshot.connection,
                target_table,
                target_id_column,
                ticket_id,
            )
            active = snapshot.connection.execute(
                f"SELECT {link_id_column} FROM {link_table} "
                f"WHERE {owner_column}=? AND device_reference_id=? AND link_state='active'",
                (ticket_id, device_reference_id),
            ).fetchone()
            if active is not None:
                relationship_id = str(active[0])
                state = "active"
            elif fallback_relationship_id is not None:
                closed = snapshot.connection.execute(
                    f"SELECT link_state FROM {link_table} WHERE {link_id_column}=?",
                    (fallback_relationship_id,),
                ).fetchone()
                relationship_id = fallback_relationship_id
                state = "absent" if closed is None else str(closed[0])
            else:
                relationship_id = None
                state = "absent"
        return TicketDeviceReferenceRelationshipResult(
            relationship_id=relationship_id,
            ticket_type=ticket_type,
            ticket_id=ticket_id,
            device_reference_id=device_reference_id,
            state=state,
            target_revision=revision,
            replayed=replayed,
            no_change=no_change,
        )

    def link(
        self,
        *,
        command_id: str,
        ticket_type: str,
        ticket_id: str,
        device_reference_id: str,
        target_base_revision: int,
        reason_category: str | None = None,
        actor_kind: str = "local_user",
        actor_id: str | None = None,
    ) -> TicketDeviceReferenceRelationshipResult:
        target_table, target_id_column, link_table, link_id_column = self._target_spec(ticket_type)
        owner_column = "service_request_id" if ticket_type == "service_request" else "rfc_id"
        reason = self._optional_reason(reason_category)
        envelope = CommandEnvelope(
            command_id=command_id,
            command_type="LinkDeviceReference",
            target_type=ticket_type,
            target_id=ticket_id,
            semantic_payload={
                "ticket_type": ticket_type,
                "ticket_id": ticket_id,
                "device_reference_id": device_reference_id,
                "reason_category": reason,
            },
            base_revisions={ticket_type: target_base_revision},
        )

        def prepare(uow: UnitOfWork) -> PreparedMutation:
            revision = self._load_target_revision(uow.connection, target_table, target_id_column, ticket_id)
            if revision != target_base_revision:
                raise SomaError("TICKET_RELATIONSHIP_STALE", "Ticket revision changed")
            self._require_device_reference(uow.connection, device_reference_id)
            existing = uow.connection.execute(
                f"SELECT {link_id_column} FROM {link_table} "
                f"WHERE {owner_column}=? AND device_reference_id=? AND link_state='active'",
                (ticket_id, device_reference_id),
            ).fetchone()
            if existing is not None:
                return PreparedMutation(True, None, None)

            relationship_id = new_uuid4()
            audit_event_id = new_uuid4()
            now = utc_epoch_seconds()
            relationship_type = f"{ticket_type}_device_reference"

            def apply(inner: UnitOfWork) -> AuditEventInput:
                inner.connection.execute(
                    f"INSERT INTO {link_table}("
                    f"{link_id_column},{owner_column},device_reference_id,link_state,opened_at_utc,opened_command_id"
                    ") VALUES (?, ?, ?, 'active', ?, ?)",
                    (relationship_id, ticket_id, device_reference_id, now, command_id),
                )
                return AuditEventInput(
                    audit_event_id=audit_event_id,
                    action_type="ticket.device_reference.relationship_changed",
                    action_version=1,
                    actor_kind=actor_kind,
                    actor_id=actor_id,
                    target_type="device_reference",
                    target_id=device_reference_id,
                    reason_category=reason,
                    command_id=command_id,
                    payload_schema="TicketRelationshipAuditV1",
                    payload_version=1,
                    payload={
                        "relationship_type": relationship_type,
                        "relationship_id": relationship_id,
                        "left_id": ticket_id,
                        "right_id": device_reference_id,
                        "prior_state": None,
                        "new_state": "active",
                        "reason_category": reason,
                        "subordinate_origin_rfc_id": None,
                    },
                    resulting_event_refs=(
                        AuditResultRef("ticket_device_reference_relationship", relationship_id),
                    ),
                )

            return PreparedMutation(
                False,
                "ticket_device_reference_relationship",
                relationship_id,
                apply,
            )

        result = self._boundary.execute(envelope, prepare)
        return self._result(
            ticket_type=ticket_type,
            ticket_id=ticket_id,
            device_reference_id=device_reference_id,
            fallback_relationship_id=result.result_id,
            replayed=result.replayed,
            no_change=result.no_change,
        )

    def unlink(
        self,
        *,
        command_id: str,
        ticket_type: str,
        ticket_id: str,
        device_reference_id: str,
        target_base_revision: int,
        reason_category: str | None = None,
        actor_kind: str = "local_user",
        actor_id: str | None = None,
    ) -> TicketDeviceReferenceRelationshipResult:
        target_table, target_id_column, link_table, link_id_column = self._target_spec(ticket_type)
        owner_column = "service_request_id" if ticket_type == "service_request" else "rfc_id"
        reason = self._optional_reason(reason_category)
        envelope = CommandEnvelope(
            command_id=command_id,
            command_type="UnlinkDeviceReference",
            target_type=ticket_type,
            target_id=ticket_id,
            semantic_payload={
                "ticket_type": ticket_type,
                "ticket_id": ticket_id,
                "device_reference_id": device_reference_id,
                "reason_category": reason,
            },
            base_revisions={ticket_type: target_base_revision},
        )

        def prepare(uow: UnitOfWork) -> PreparedMutation:
            revision = self._load_target_revision(uow.connection, target_table, target_id_column, ticket_id)
            if revision != target_base_revision:
                raise SomaError("TICKET_RELATIONSHIP_STALE", "Ticket revision changed")
            self._require_device_reference(uow.connection, device_reference_id)
            existing = uow.connection.execute(
                f"SELECT {link_id_column} FROM {link_table} "
                f"WHERE {owner_column}=? AND device_reference_id=? AND link_state='active'",
                (ticket_id, device_reference_id),
            ).fetchone()
            if existing is None:
                return PreparedMutation(True, None, None)

            relationship_id = str(existing[0])
            audit_event_id = new_uuid4()
            now = utc_epoch_seconds()
            relationship_type = f"{ticket_type}_device_reference"

            def apply(inner: UnitOfWork) -> AuditEventInput:
                inner.connection.execute(
                    f"UPDATE {link_table} SET link_state='unlinked',closed_at_utc=?,closed_command_id=? "
                    f"WHERE {link_id_column}=? AND link_state='active'",
                    (now, command_id, relationship_id),
                )
                return AuditEventInput(
                    audit_event_id=audit_event_id,
                    action_type="ticket.device_reference.relationship_changed",
                    action_version=1,
                    actor_kind=actor_kind,
                    actor_id=actor_id,
                    target_type="device_reference",
                    target_id=device_reference_id,
                    reason_category=reason,
                    command_id=command_id,
                    payload_schema="TicketRelationshipAuditV1",
                    payload_version=1,
                    payload={
                        "relationship_type": relationship_type,
                        "relationship_id": relationship_id,
                        "left_id": ticket_id,
                        "right_id": device_reference_id,
                        "prior_state": "active",
                        "new_state": "unlinked",
                        "reason_category": reason,
                        "subordinate_origin_rfc_id": None,
                    },
                    resulting_event_refs=(
                        AuditResultRef("ticket_device_reference_relationship", relationship_id),
                    ),
                )

            return PreparedMutation(
                False,
                "ticket_device_reference_relationship",
                relationship_id,
                apply,
            )

        result = self._boundary.execute(envelope, prepare)
        return self._result(
            ticket_type=ticket_type,
            ticket_id=ticket_id,
            device_reference_id=device_reference_id,
            fallback_relationship_id=result.result_id,
            replayed=result.replayed,
            no_change=result.no_change,
        )
