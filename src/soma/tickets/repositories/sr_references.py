from __future__ import annotations

from dataclasses import dataclass

from soma.foundation.errors import SomaError
from soma.foundation.persistence.uow import UnitOfWork


@dataclass(frozen=True, slots=True)
class SrCustomerRelationshipRecord:
    relationship_id: str
    service_request_id: str
    customer_org_id: str
    relationship_state: str
    origin_kind: str
    reconciliation_proposal_id: str | None
    opened_at_utc: int
    closed_at_utc: int | None
    opened_command_id: str
    closed_command_id: str | None
    reason_category: str | None


@dataclass(frozen=True, slots=True)
class SrContactRelationshipRecord:
    relationship_id: str
    service_request_id: str
    reference_role: str
    contact_id: str
    customer_org_context_id: str | None
    relationship_state: str
    origin_kind: str
    reconciliation_proposal_id: str | None
    supporting_source_observation_id: str | None
    opened_at_utc: int
    closed_at_utc: int | None
    opened_command_id: str
    closed_command_id: str | None
    reason_category: str | None


class ServiceRequestReferenceRepository:
    """Persistence authority for LLD-03 SR-to-reference relationship history only."""

    @staticmethod
    def current_customer(connection, service_request_id: str) -> SrCustomerRelationshipRecord | None:
        row = connection.execute(
            "SELECT sr_customer_relationship_id,service_request_id,customer_org_id,relationship_state,origin_kind,"
            "reconciliation_proposal_id,opened_at_utc,closed_at_utc,opened_command_id,closed_command_id,reason_category "
            "FROM sr_customer_relationships WHERE service_request_id=? AND relationship_state='active'",
            (service_request_id,),
        ).fetchone()
        if row is None:
            return None
        return SrCustomerRelationshipRecord(
            relationship_id=str(row[0]),
            service_request_id=str(row[1]),
            customer_org_id=str(row[2]),
            relationship_state=str(row[3]),
            origin_kind=str(row[4]),
            reconciliation_proposal_id=None if row[5] is None else str(row[5]),
            opened_at_utc=int(row[6]),
            closed_at_utc=None if row[7] is None else int(row[7]),
            opened_command_id=str(row[8]),
            closed_command_id=None if row[9] is None else str(row[9]),
            reason_category=None if row[10] is None else str(row[10]),
        )

    @staticmethod
    def current_contact(connection, service_request_id: str, reference_role: str) -> SrContactRelationshipRecord | None:
        row = connection.execute(
            "SELECT sr_contact_relationship_id,service_request_id,reference_role,contact_id,customer_org_context_id,"
            "relationship_state,origin_kind,reconciliation_proposal_id,supporting_sr_source_field_observation_id,"
            "opened_at_utc,closed_at_utc,opened_command_id,closed_command_id,reason_category "
            "FROM sr_contact_relationships WHERE service_request_id=? AND reference_role=? AND relationship_state='active'",
            (service_request_id, reference_role),
        ).fetchone()
        if row is None:
            return None
        return SrContactRelationshipRecord(
            relationship_id=str(row[0]),
            service_request_id=str(row[1]),
            reference_role=str(row[2]),
            contact_id=str(row[3]),
            customer_org_context_id=None if row[4] is None else str(row[4]),
            relationship_state=str(row[5]),
            origin_kind=str(row[6]),
            reconciliation_proposal_id=None if row[7] is None else str(row[7]),
            supporting_source_observation_id=None if row[8] is None else str(row[8]),
            opened_at_utc=int(row[9]),
            closed_at_utc=None if row[10] is None else int(row[10]),
            opened_command_id=str(row[11]),
            closed_command_id=None if row[12] is None else str(row[12]),
            reason_category=None if row[13] is None else str(row[13]),
        )

    @staticmethod
    def insert_customer(uow: UnitOfWork, row: SrCustomerRelationshipRecord) -> None:
        uow.connection.execute(
            "INSERT INTO sr_customer_relationships("
            "sr_customer_relationship_id,service_request_id,customer_org_id,relationship_state,origin_kind,"
            "reconciliation_proposal_id,opened_at_utc,closed_at_utc,opened_command_id,closed_command_id,reason_category"
            ") VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                row.relationship_id,
                row.service_request_id,
                row.customer_org_id,
                row.relationship_state,
                row.origin_kind,
                row.reconciliation_proposal_id,
                row.opened_at_utc,
                row.closed_at_utc,
                row.opened_command_id,
                row.closed_command_id,
                row.reason_category,
            ),
        )

    @staticmethod
    def supersede_customer(uow: UnitOfWork, relationship_id: str, *, closed_at_utc: int, command_id: str) -> None:
        cursor = uow.connection.execute(
            "UPDATE sr_customer_relationships SET relationship_state='superseded',closed_at_utc=?,closed_command_id=? "
            "WHERE sr_customer_relationship_id=? AND relationship_state='active'",
            (closed_at_utc, command_id, relationship_id),
        )
        if cursor.rowcount != 1:
            raise SomaError("SR_REFERENCE_STALE", "current Service Request Customer relationship changed")

    @staticmethod
    def insert_contact(uow: UnitOfWork, row: SrContactRelationshipRecord) -> None:
        uow.connection.execute(
            "INSERT INTO sr_contact_relationships("
            "sr_contact_relationship_id,service_request_id,reference_role,contact_id,customer_org_context_id,"
            "relationship_state,origin_kind,reconciliation_proposal_id,supporting_sr_source_field_observation_id,"
            "opened_at_utc,closed_at_utc,opened_command_id,closed_command_id,reason_category"
            ") VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                row.relationship_id,
                row.service_request_id,
                row.reference_role,
                row.contact_id,
                row.customer_org_context_id,
                row.relationship_state,
                row.origin_kind,
                row.reconciliation_proposal_id,
                row.supporting_source_observation_id,
                row.opened_at_utc,
                row.closed_at_utc,
                row.opened_command_id,
                row.closed_command_id,
                row.reason_category,
            ),
        )

    @staticmethod
    def supersede_contact(uow: UnitOfWork, relationship_id: str, *, closed_at_utc: int, command_id: str) -> None:
        cursor = uow.connection.execute(
            "UPDATE sr_contact_relationships SET relationship_state='superseded',closed_at_utc=?,closed_command_id=? "
            "WHERE sr_contact_relationship_id=? AND relationship_state='active'",
            (closed_at_utc, command_id, relationship_id),
        )
        if cursor.rowcount != 1:
            raise SomaError("SR_REFERENCE_STALE", "current Service Request Contact relationship changed")
