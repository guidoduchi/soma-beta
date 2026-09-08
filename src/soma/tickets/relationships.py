from __future__ import annotations

import hmac
from dataclasses import dataclass
from typing import Any

from soma.foundation.application.command_boundary import CommandBoundary, CommandEnvelope, PreparedMutation
from soma.foundation.audit.writer import AuditEventInput, AuditResultRef, AuditWriter
from soma.foundation.errors import SomaError, ValidationError
from soma.foundation.identifiers import new_uuid4, utc_epoch_seconds
from soma.foundation.persistence.connections import ConnectionFactory
from soma.foundation.persistence.uow import ReadSnapshot, UnitOfWork
from soma.foundation.strict_json import sha256_canonical_json

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


@dataclass(frozen=True, slots=True)
class SrRfcLinkPreview:
    service_request_id: str
    requested_rfc_id: str
    governing_root_rfc_id: str
    subordinate_origin_rfc_id: str | None
    duplicate_active: bool
    sr_revision: int
    rfc_revision: int
    review_required: bool
    review_fingerprint: str
    sr_lifecycle: dict[str, Any]
    rfc_lifecycle: dict[str, Any]
    warnings: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class SrRfcRelationshipResult:
    relationship_id: str | None
    service_request_id: str
    root_rfc_id: str
    state: str
    sr_revision: int
    rfc_revision: int
    replayed: bool
    no_change: bool


class ServiceRequestRfcRelationshipService:
    """Authoritative LLD-03 direct SR-to-governing-root RFC relationship service."""

    def __init__(self, connection_factory: ConnectionFactory) -> None:
        self._factory = connection_factory
        self._boundary = CommandBoundary(
            connection_factory,
            AuditWriter(build_tickets_audit_registry()),
        )

    @staticmethod
    def _load_sr(connection, service_request_id: str) -> tuple[int, str | None]:
        row = connection.execute(
            "SELECT revision,official_sr_no FROM service_requests WHERE service_request_id=?",
            (service_request_id,),
        ).fetchone()
        if row is None:
            raise SomaError("NOT_FOUND", "Service Request does not exist")
        return int(row[0]), None if row[1] is None else str(row[1])

    @staticmethod
    def _load_root(connection, rfc_id: str) -> tuple[int, str | None, str]:
        row = connection.execute(
            "SELECT revision,customer_org_id,local_archive_state FROM rfcs WHERE rfc_id=?",
            (rfc_id,),
        ).fetchone()
        if row is None:
            raise SomaError("NOT_FOUND", "RFC does not exist")
        parent = connection.execute(
            "SELECT parent_rfc_id FROM rfc_hierarchy_edges WHERE child_rfc_id=? AND edge_state='active'",
            (rfc_id,),
        ).fetchone()
        if parent is not None:
            raise SomaError(
                "RFC_DIRECT_SR_LINK_ON_SUBORDINATE",
                "direct Service Request relationship must target the governing root RFC",
            )
        return int(row[0]), None if row[1] is None else str(row[1]), str(row[2])

    @staticmethod
    def _validate_subordinate_origin(connection, root_rfc_id: str, subordinate_origin_rfc_id: str | None) -> None:
        if subordinate_origin_rfc_id is None:
            return
        row = connection.execute(
            "SELECT parent_rfc_id FROM rfc_hierarchy_edges WHERE child_rfc_id=? AND edge_state='active'",
            (subordinate_origin_rfc_id,),
        ).fetchone()
        if row is None or str(row[0]) != root_rfc_id:
            raise SomaError(
                "TICKET_RELATIONSHIP_STALE",
                "subordinate-origin provenance no longer belongs to the reviewed governing root",
            )

    @staticmethod
    def _sr_lifecycle(connection, service_request_id: str) -> tuple[dict[str, Any], bool]:
        projection = connection.execute(
            "SELECT status_observation_id,revision FROM sr_current_source_projection WHERE service_request_id=?",
            (service_request_id,),
        ).fetchone()
        if projection is None or projection[0] is None:
            return {"projection_revision": None if projection is None else int(projection[1]), "status_observation_id": None, "status": None}, False
        observation_id = str(projection[0])
        observation = connection.execute(
            "SELECT value_state,text_value,source_observation_field_id FROM sr_source_field_observations "
            "WHERE sr_source_field_observation_id=? AND service_request_id=? AND field_key='status'",
            (observation_id, service_request_id),
        ).fetchone()
        if observation is None:
            raise SomaError("PERSISTENCE_FAILURE", "Service Request status projection is invalid")
        status = None if observation[1] is None else str(observation[1])
        state = {
            "projection_revision": int(projection[1]),
            "status_observation_id": observation_id,
            "value_state": str(observation[0]),
            "status": status,
            "source_observation_field_id": str(observation[2]),
        }
        return state, str(observation[0]) == "usable" and status in {"Closed", "Resolved", "Cancelled"}

    @staticmethod
    def _rfc_lifecycle(connection, rfc_id: str, local_archive_state: str) -> tuple[dict[str, Any], bool]:
        row = connection.execute(
            "SELECT status_class,status_authority,status_evidence_id,terminal_epoch_id,revision "
            "FROM rfc_current_source_projection WHERE rfc_id=?",
            (rfc_id,),
        ).fetchone()
        if row is None:
            state = {
                "projection_revision": None,
                "status_class": "unknown",
                "status_authority": None,
                "status_evidence_id": None,
                "terminal_epoch_id": None,
                "local_archive_state": local_archive_state,
            }
            return state, local_archive_state == "archived"
        status_class = str(row[0])
        state = {
            "projection_revision": int(row[4]),
            "status_class": status_class,
            "status_authority": None if row[1] is None else str(row[1]),
            "status_evidence_id": None if row[2] is None else str(row[2]),
            "terminal_epoch_id": None if row[3] is None else str(row[3]),
            "local_archive_state": local_archive_state,
        }
        return state, status_class in {"terminal_closed", "terminal_cancelled"} or local_archive_state == "archived"

    @staticmethod
    def _customer_warnings(connection, service_request_id: str, root_rfc_id: str, root_customer_org_id: str | None) -> tuple[str, ...]:
        sr_customer_row = connection.execute(
            "SELECT customer_org_id FROM sr_customer_relationships "
            "WHERE service_request_id=? AND relationship_state='active'",
            (service_request_id,),
        ).fetchone()
        sr_customer = None if sr_customer_row is None else str(sr_customer_row[0])
        branch_rows = connection.execute(
            "SELECT rfc_id,customer_org_id FROM rfcs WHERE rfc_id=? OR rfc_id IN ("
            "SELECT child_rfc_id FROM rfc_hierarchy_edges WHERE parent_rfc_id=? AND edge_state='active'"
            ") ORDER BY rfc_id",
            (root_rfc_id, root_rfc_id),
        ).fetchall()
        branch_customers = [None if row[1] is None else str(row[1]) for row in branch_rows]
        known = {value for value in [sr_customer, root_customer_org_id, *branch_customers] if value is not None}
        if len(known) > 1:
            raise SomaError("RFC_CUSTOMER_MISMATCH", "Service Request and RFC branch resolve to different Customers")
        warnings: list[str] = []
        if sr_customer is None or any(value is None for value in branch_customers):
            warnings.append("RFC_CUSTOMER_UNRESOLVED")
        return tuple(warnings)

    def _preview_with_reader(
        self,
        connection,
        *,
        service_request_id: str,
        rfc_id: str,
        subordinate_origin_rfc_id: str | None,
    ) -> SrRfcLinkPreview:
        sr_revision, _official = self._load_sr(connection, service_request_id)
        rfc_revision, root_customer_org_id, local_archive_state = self._load_root(connection, rfc_id)
        self._validate_subordinate_origin(connection, rfc_id, subordinate_origin_rfc_id)
        duplicate = connection.execute(
            "SELECT 1 FROM sr_rfc_links WHERE service_request_id=? AND rfc_id=? AND link_state='active'",
            (service_request_id, rfc_id),
        ).fetchone() is not None
        sr_lifecycle, sr_review = self._sr_lifecycle(connection, service_request_id)
        rfc_lifecycle, rfc_review = self._rfc_lifecycle(connection, rfc_id, local_archive_state)
        warnings = self._customer_warnings(connection, service_request_id, rfc_id, root_customer_org_id)
        review_required = False if duplicate else (sr_review or rfc_review)
        fingerprint = sha256_canonical_json(
            {
                "schema": "SR_RFC_LINK_REVIEW_V1",
                "service_request_id": service_request_id,
                "governing_root_rfc_id": rfc_id,
                "subordinate_origin_rfc_id": subordinate_origin_rfc_id,
                "sr_revision": sr_revision,
                "rfc_revision": rfc_revision,
                "duplicate_active": duplicate,
                "sr_lifecycle": sr_lifecycle,
                "rfc_lifecycle": rfc_lifecycle,
            }
        )
        return SrRfcLinkPreview(
            service_request_id=service_request_id,
            requested_rfc_id=rfc_id,
            governing_root_rfc_id=rfc_id,
            subordinate_origin_rfc_id=subordinate_origin_rfc_id,
            duplicate_active=duplicate,
            sr_revision=sr_revision,
            rfc_revision=rfc_revision,
            review_required=review_required,
            review_fingerprint=fingerprint,
            sr_lifecycle=sr_lifecycle,
            rfc_lifecycle=rfc_lifecycle,
            warnings=warnings,
        )

    def preview_link(
        self,
        *,
        service_request_id: str,
        rfc_id: str,
        subordinate_origin_rfc_id: str | None = None,
    ) -> SrRfcLinkPreview:
        with ReadSnapshot(self._factory) as snapshot:
            return self._preview_with_reader(
                snapshot.connection,
                service_request_id=service_request_id,
                rfc_id=rfc_id,
                subordinate_origin_rfc_id=subordinate_origin_rfc_id,
            )

    def _result(
        self,
        *,
        service_request_id: str,
        root_rfc_id: str,
        fallback_relationship_id: str | None,
        replayed: bool,
        no_change: bool,
    ) -> SrRfcRelationshipResult:
        with ReadSnapshot(self._factory) as snapshot:
            sr_revision, _ = self._load_sr(snapshot.connection, service_request_id)
            rfc_revision, _, _ = self._load_root(snapshot.connection, root_rfc_id)
            active = snapshot.connection.execute(
                "SELECT sr_rfc_link_id FROM sr_rfc_links WHERE service_request_id=? AND rfc_id=? AND link_state='active'",
                (service_request_id, root_rfc_id),
            ).fetchone()
            if active is not None:
                relationship_id = str(active[0])
                state = "active"
            elif fallback_relationship_id is not None:
                row = snapshot.connection.execute(
                    "SELECT link_state FROM sr_rfc_links WHERE sr_rfc_link_id=?",
                    (fallback_relationship_id,),
                ).fetchone()
                relationship_id = fallback_relationship_id
                state = "absent" if row is None else str(row[0])
            else:
                relationship_id = None
                state = "absent"
        return SrRfcRelationshipResult(
            relationship_id=relationship_id,
            service_request_id=service_request_id,
            root_rfc_id=root_rfc_id,
            state=state,
            sr_revision=sr_revision,
            rfc_revision=rfc_revision,
            replayed=replayed,
            no_change=no_change,
        )

    def link(
        self,
        *,
        command_id: str,
        service_request_id: str,
        rfc_id: str,
        sr_base_revision: int,
        rfc_base_revision: int,
        subordinate_origin_rfc_id: str | None = None,
        review_fingerprint: str | None = None,
        actor_kind: str = "local_user",
        actor_id: str | None = None,
    ) -> SrRfcRelationshipResult:
        envelope = CommandEnvelope(
            command_id=command_id,
            command_type="LinkServiceRequestToRfc",
            target_type="service_request",
            target_id=service_request_id,
            semantic_payload={
                "rfc_id": rfc_id,
                "subordinate_origin_rfc_id": subordinate_origin_rfc_id,
                "review_fingerprint": review_fingerprint,
            },
            base_revisions={"service_request": sr_base_revision, "rfc": rfc_base_revision},
        )

        def prepare(uow: UnitOfWork) -> PreparedMutation:
            preview = self._preview_with_reader(
                uow.connection,
                service_request_id=service_request_id,
                rfc_id=rfc_id,
                subordinate_origin_rfc_id=subordinate_origin_rfc_id,
            )
            if preview.sr_revision != sr_base_revision or preview.rfc_revision != rfc_base_revision:
                raise SomaError("TICKET_RELATIONSHIP_STALE", "Service Request or RFC revision changed")
            if preview.duplicate_active:
                return PreparedMutation(True, None, None)
            if review_fingerprint is not None and not hmac.compare_digest(review_fingerprint, preview.review_fingerprint):
                raise SomaError("TICKET_RELATIONSHIP_STALE", "relationship review fingerprint is stale")
            if preview.review_required and (
                review_fingerprint is None or not hmac.compare_digest(review_fingerprint, preview.review_fingerprint)
            ):
                raise SomaError("TICKET_RELATIONSHIP_STALE", "fresh terminal/historical relationship review is required")

            relationship_id = new_uuid4()
            audit_event_id = new_uuid4()
            now = utc_epoch_seconds()

            def apply(inner: UnitOfWork) -> AuditEventInput:
                inner.connection.execute(
                    "INSERT INTO sr_rfc_links(sr_rfc_link_id,service_request_id,rfc_id,link_state,opened_at_utc,opened_command_id) "
                    "VALUES (?, ?, ?, 'active', ?, ?)",
                    (relationship_id, service_request_id, rfc_id, now, command_id),
                )
                sr_update = inner.connection.execute(
                    "UPDATE service_requests SET revision=revision+1,updated_at_utc=? WHERE service_request_id=? AND revision=?",
                    (now, service_request_id, sr_base_revision),
                )
                rfc_update = inner.connection.execute(
                    "UPDATE rfcs SET revision=revision+1,updated_at_utc=? WHERE rfc_id=? AND revision=?",
                    (now, rfc_id, rfc_base_revision),
                )
                if sr_update.rowcount != 1 or rfc_update.rowcount != 1:
                    raise SomaError("TICKET_RELATIONSHIP_STALE", "Service Request or RFC revision changed")
                return AuditEventInput(
                    audit_event_id=audit_event_id,
                    action_type="ticket.sr_rfc_relationship.changed",
                    action_version=1,
                    actor_kind=actor_kind,
                    actor_id=actor_id,
                    target_type="service_request",
                    target_id=service_request_id,
                    command_id=command_id,
                    payload_schema="TicketRelationshipAuditV1",
                    payload_version=1,
                    payload={
                        "relationship_type": "service_request_rfc",
                        "relationship_id": relationship_id,
                        "left_id": service_request_id,
                        "right_id": rfc_id,
                        "prior_state": None,
                        "new_state": "active",
                        "reason_category": None,
                        "subordinate_origin_rfc_id": subordinate_origin_rfc_id,
                    },
                    resulting_event_refs=(AuditResultRef("sr_rfc_relationship", relationship_id),),
                )

            return PreparedMutation(False, "sr_rfc_relationship", relationship_id, apply)

        result = self._boundary.execute(envelope, prepare)
        return self._result(
            service_request_id=service_request_id,
            root_rfc_id=rfc_id,
            fallback_relationship_id=result.result_id,
            replayed=result.replayed,
            no_change=result.no_change,
        )

    def unlink(
        self,
        *,
        command_id: str,
        service_request_id: str,
        root_rfc_id: str,
        sr_base_revision: int,
        rfc_base_revision: int,
        reason_category: str,
        actor_kind: str = "local_user",
        actor_id: str | None = None,
    ) -> SrRfcRelationshipResult:
        reason = validate_reason_category(reason_category)
        envelope = CommandEnvelope(
            command_id=command_id,
            command_type="UnlinkServiceRequestFromRfc",
            target_type="service_request",
            target_id=service_request_id,
            semantic_payload={"root_rfc_id": root_rfc_id, "reason_category": reason},
            base_revisions={"service_request": sr_base_revision, "rfc": rfc_base_revision},
        )

        def prepare(uow: UnitOfWork) -> PreparedMutation:
            sr_revision, _ = self._load_sr(uow.connection, service_request_id)
            rfc_revision, _, _ = self._load_root(uow.connection, root_rfc_id)
            if sr_revision != sr_base_revision or rfc_revision != rfc_base_revision:
                raise SomaError("TICKET_RELATIONSHIP_STALE", "Service Request or RFC revision changed")
            active = uow.connection.execute(
                "SELECT sr_rfc_link_id FROM sr_rfc_links WHERE service_request_id=? AND rfc_id=? AND link_state='active'",
                (service_request_id, root_rfc_id),
            ).fetchone()
            if active is None:
                return PreparedMutation(True, None, None)

            relationship_id = str(active[0])
            audit_event_id = new_uuid4()
            now = utc_epoch_seconds()

            def apply(inner: UnitOfWork) -> AuditEventInput:
                link_update = inner.connection.execute(
                    "UPDATE sr_rfc_links SET link_state='unlinked',closed_at_utc=?,closed_command_id=? "
                    "WHERE sr_rfc_link_id=? AND link_state='active'",
                    (now, command_id, relationship_id),
                )
                sr_update = inner.connection.execute(
                    "UPDATE service_requests SET revision=revision+1,updated_at_utc=? WHERE service_request_id=? AND revision=?",
                    (now, service_request_id, sr_base_revision),
                )
                rfc_update = inner.connection.execute(
                    "UPDATE rfcs SET revision=revision+1,updated_at_utc=? WHERE rfc_id=? AND revision=?",
                    (now, root_rfc_id, rfc_base_revision),
                )
                if link_update.rowcount != 1 or sr_update.rowcount != 1 or rfc_update.rowcount != 1:
                    raise SomaError("TICKET_RELATIONSHIP_STALE", "relationship or ticket revision changed")
                return AuditEventInput(
                    audit_event_id=audit_event_id,
                    action_type="ticket.sr_rfc_relationship.changed",
                    action_version=1,
                    actor_kind=actor_kind,
                    actor_id=actor_id,
                    target_type="service_request",
                    target_id=service_request_id,
                    reason_category=reason,
                    command_id=command_id,
                    payload_schema="TicketRelationshipAuditV1",
                    payload_version=1,
                    payload={
                        "relationship_type": "service_request_rfc",
                        "relationship_id": relationship_id,
                        "left_id": service_request_id,
                        "right_id": root_rfc_id,
                        "prior_state": "active",
                        "new_state": "unlinked",
                        "reason_category": reason,
                        "subordinate_origin_rfc_id": None,
                    },
                    resulting_event_refs=(AuditResultRef("sr_rfc_relationship", relationship_id),),
                )

            return PreparedMutation(False, "sr_rfc_relationship", relationship_id, apply)

        result = self._boundary.execute(envelope, prepare)
        return self._result(
            service_request_id=service_request_id,
            root_rfc_id=root_rfc_id,
            fallback_relationship_id=result.result_id,
            replayed=result.replayed,
            no_change=result.no_change,
        )
