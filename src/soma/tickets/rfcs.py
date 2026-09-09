from __future__ import annotations

from dataclasses import asdict, dataclass

from soma.foundation.application.command_boundary import (
    CommandBoundary,
    CommandEnvelope,
    CommandExecutionResult,
    PreparedMutation,
)
from soma.foundation.audit.writer import AuditEventInput, AuditResultRef, AuditWriter
from soma.foundation.errors import IntegrityFailure, SomaError, ValidationError
from soma.foundation.identifiers import new_uuid4, utc_epoch_seconds
from soma.foundation.persistence.connections import ConnectionFactory
from soma.foundation.persistence.uow import UnitOfWork

from .audit_registry import build_tickets_audit_registry
from .queries.rfcs import RfcQueryService
from .results import TicketMutationResult, ticket_mutation_result_from_execution
from .validation import validate_optional_sha256, validate_reason_category, validate_rfc_no

_CREATION_CONTEXTS = frozenset({"manual", "provisional", "accepted_source_adoption"})


@dataclass(frozen=True, slots=True)
class RfcIdentityResult:
    rfc_id: str
    rfc_no: str
    customer_org_id: str | None
    revision: int
    created_by_command: bool
    replayed: bool
    no_change: bool


class RfcService:
    def __init__(self, connection_factory: ConnectionFactory) -> None:
        self._factory = connection_factory
        self._queries = RfcQueryService(connection_factory)
        self._boundary = CommandBoundary(
            connection_factory,
            AuditWriter(build_tickets_audit_registry()),
        )

    @staticmethod
    def _validate_creation_context(value: str) -> str:
        if value not in _CREATION_CONTEXTS:
            raise ValidationError("creation_context must be manual, provisional, or accepted_source_adoption")
        return value

    @staticmethod
    def _require_active_customer(connection, customer_org_id: str) -> None:
        row = connection.execute(
            "SELECT lifecycle_state FROM customer_organizations WHERE customer_org_id=?",
            (customer_org_id,),
        ).fetchone()
        if row is None:
            raise SomaError("NOT_FOUND", "Customer Organization does not exist")
        if str(row[0]) != "active":
            raise SomaError("CUSTOMER_ORG_INACTIVE", "Customer Organization is archived")

    @staticmethod
    def _identity_result(result: CommandExecutionResult) -> RfcIdentityResult:
        if (
            result.response_schema != "RfcDetailV1"
            or result.response_version != 1
            or not isinstance(result.response, dict)
        ):
            raise IntegrityFailure("RFC identity replay result has the wrong response contract")
        rfc_id = result.response.get("rfc_id")
        rfc_no = result.response.get("rfc_no")
        customer_org_id = result.response.get("customer_org_id")
        revision = result.response.get("revision")
        if not isinstance(rfc_id, str) or not isinstance(rfc_no, str):
            raise IntegrityFailure("RFC identity replay result has invalid identity")
        if customer_org_id is not None and not isinstance(customer_org_id, str):
            raise IntegrityFailure("RFC identity replay result has invalid Customer identity")
        if type(revision) is not int or revision <= 0:
            raise IntegrityFailure("RFC identity replay result has invalid revision")
        return RfcIdentityResult(
            rfc_id=rfc_id,
            rfc_no=rfc_no,
            customer_org_id=customer_org_id,
            revision=revision,
            created_by_command=not result.no_change,
            replayed=result.replayed,
            no_change=result.no_change,
        )

    def create_or_adopt_identity(
        self,
        *,
        command_id: str,
        rfc_no: str,
        creation_context: str,
        customer_org_id: str | None = None,
        actor_kind: str = "local_user",
        actor_id: str | None = None,
    ) -> RfcIdentityResult:
        canonical_no = validate_rfc_no(rfc_no)
        context = self._validate_creation_context(creation_context)
        envelope = CommandEnvelope(
            command_id=command_id,
            command_type="CreateOrAdoptRfcIdentity",
            target_type="rfc",
            target_id=None,
            semantic_payload={
                "rfc_no": canonical_no,
                "creation_context": context,
                "customer_org_id": customer_org_id,
            },
        )

        def prepare(uow: UnitOfWork) -> PreparedMutation:
            existing = uow.connection.execute(
                "SELECT rfc_id FROM rfcs WHERE rfc_no=?",
                (canonical_no,),
            ).fetchone()
            if existing is not None:
                existing_id = str(existing[0])
                return PreparedMutation(
                    True,
                    None,
                    None,
                    response_schema="RfcDetailV1",
                    response_version=1,
                    response_factory=lambda inner: asdict(
                        self._queries.get_from_connection(inner.connection, rfc_id=existing_id)
                    ),
                )
            if customer_org_id is not None:
                self._require_active_customer(uow.connection, customer_org_id)
            rfc_id = new_uuid4()
            audit_event_id = new_uuid4()
            now = utc_epoch_seconds()

            def apply(inner: UnitOfWork) -> AuditEventInput:
                inner.connection.execute(
                    "INSERT INTO rfcs(rfc_id,rfc_no,customer_org_id,local_archive_state,revision,created_at_utc,updated_at_utc) "
                    "VALUES (?, ?, ?, 'active', 1, ?, ?)",
                    (rfc_id, canonical_no, customer_org_id, now, now),
                )
                return AuditEventInput(
                    audit_event_id=audit_event_id,
                    action_type="ticket.rfc.identity_created_or_adopted",
                    action_version=1,
                    actor_kind=actor_kind,
                    actor_id=actor_id,
                    target_type="rfc",
                    target_id=rfc_id,
                    command_id=command_id,
                    payload_schema="RfcIdentityAuditV1",
                    payload_version=1,
                    payload={
                        "rfc_id": rfc_id,
                        "rfc_no": canonical_no,
                        "creation_context": context,
                        "customer_org_id": customer_org_id,
                        "resulting_revision": 1,
                    },
                    resulting_event_refs=(AuditResultRef("rfc", rfc_id),),
                )

            return PreparedMutation(
                False,
                "rfc",
                rfc_id,
                apply,
                response_schema="RfcDetailV1",
                response_version=1,
                response_factory=lambda inner: asdict(
                    self._queries.get_from_connection(inner.connection, rfc_id=rfc_id)
                ),
            )

        return self._identity_result(self._boundary.execute(envelope, prepare))

    def set_customer(
        self,
        *,
        command_id: str,
        rfc_id: str,
        base_revision: int,
        customer_org_id: str | None,
        reason_category: str,
        review_fingerprint: str | None = None,
        actor_kind: str = "local_user",
        actor_id: str | None = None,
    ) -> TicketMutationResult:
        reason = validate_reason_category(reason_category)
        fingerprint = validate_optional_sha256(review_fingerprint, field="review_fingerprint")
        envelope = CommandEnvelope(
            command_id=command_id,
            command_type="SetRfcCustomer",
            target_type="rfc",
            target_id=rfc_id,
            semantic_payload={
                "customer_org_id": customer_org_id,
                "reason_category": reason,
                "review_fingerprint": fingerprint,
            },
            base_revisions={"rfc": base_revision},
            authorizing_fingerprints={} if fingerprint is None else {"review": fingerprint},
        )

        def prepare(uow: UnitOfWork) -> PreparedMutation:
            row = uow.connection.execute(
                "SELECT customer_org_id,revision FROM rfcs WHERE rfc_id=?",
                (rfc_id,),
            ).fetchone()
            if row is None:
                raise SomaError("NOT_FOUND", "RFC does not exist")
            current_revision = int(row[1])
            if current_revision != base_revision:
                raise SomaError("STALE_REVISION", "RFC revision changed")
            if customer_org_id is not None:
                self._require_active_customer(uow.connection, customer_org_id)
            prior_customer = None if row[0] is None else str(row[0])
            if prior_customer == customer_org_id:
                return PreparedMutation(
                    True,
                    None,
                    None,
                    response_schema="TicketMutationResultV1",
                    response_version=1,
                    response={"outcome": "NO_CHANGE", "target_id": rfc_id, "revision": current_revision},
                )

            parent = uow.connection.execute(
                "SELECT parent_rfc_id FROM rfc_hierarchy_edges WHERE child_rfc_id=? AND edge_state='active'",
                (rfc_id,),
            ).fetchone()
            root_id = rfc_id if parent is None else str(parent[0])
            branch_rows = uow.connection.execute(
                "SELECT rfc_id,customer_org_id FROM rfcs WHERE rfc_id=? OR rfc_id IN ("
                "SELECT child_rfc_id FROM rfc_hierarchy_edges WHERE parent_rfc_id=? AND edge_state='active'"
                ")",
                (root_id, root_id),
            ).fetchall()
            for branch_id, branch_customer in branch_rows:
                if str(branch_id) == rfc_id or branch_customer is None:
                    continue
                if customer_org_id is None or str(branch_customer) != customer_org_id:
                    raise SomaError(
                        "RFC_CUSTOMER_MISMATCH",
                        "known RFC branch members resolve to a different Customer Organization",
                    )

            audit_event_id = new_uuid4()
            now = utc_epoch_seconds()

            def apply(inner: UnitOfWork) -> AuditEventInput:
                inner.connection.execute(
                    "UPDATE rfcs SET customer_org_id=?,revision=revision+1,updated_at_utc=? WHERE rfc_id=?",
                    (customer_org_id, now, rfc_id),
                )
                return AuditEventInput(
                    audit_event_id=audit_event_id,
                    action_type="ticket.rfc.customer_changed",
                    action_version=1,
                    actor_kind=actor_kind,
                    actor_id=actor_id,
                    target_type="rfc",
                    target_id=rfc_id,
                    reason_category=reason,
                    command_id=command_id,
                    payload_schema="RfcCustomerAuditV1",
                    payload_version=1,
                    payload={
                        "rfc_id": rfc_id,
                        "prior_customer_org_id": prior_customer,
                        "new_customer_org_id": customer_org_id,
                        "resulting_revision": base_revision + 1,
                        "reason_category": reason,
                        "review_fingerprint": fingerprint,
                    },
                    resulting_event_refs=(AuditResultRef("rfc", rfc_id),),
                )

            return PreparedMutation(
                False,
                "rfc",
                rfc_id,
                apply,
                response_schema="TicketMutationResultV1",
                response_version=1,
                response={"outcome": "APPLIED", "target_id": rfc_id, "revision": base_revision + 1},
            )

        return ticket_mutation_result_from_execution(self._boundary.execute(envelope, prepare))
