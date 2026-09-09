from __future__ import annotations

from dataclasses import dataclass

from soma.foundation.application.command_boundary import CommandBoundary, CommandEnvelope, PreparedMutation
from soma.foundation.audit.writer import AuditEventInput, AuditResultRef, AuditWriter
from soma.foundation.errors import SomaError, ValidationError
from soma.foundation.identifiers import new_uuid4, utc_epoch_seconds
from soma.foundation.persistence.connections import ConnectionFactory
from soma.foundation.persistence.uow import ReadSnapshot, UnitOfWork

from .audit_registry import build_tickets_audit_registry
from .validation import validate_optional_sha256, validate_reason_category


@dataclass(frozen=True, slots=True)
class RfcHierarchyResult:
    rfc_hierarchy_edge_id: str
    parent_rfc_id: str
    child_rfc_id: str
    parent_revision: int
    child_revision: int
    replayed: bool
    no_change: bool
    warnings: tuple[str, ...]


class RfcHierarchyService:
    def __init__(self, connection_factory: ConnectionFactory) -> None:
        self._factory = connection_factory
        self._boundary = CommandBoundary(
            connection_factory,
            AuditWriter(build_tickets_audit_registry()),
        )

    @staticmethod
    def _validate_base_revisions(
        parent_rfc_id: str,
        child_rfc_id: str,
        base_revisions: dict[str, int],
    ) -> dict[str, int]:
        if not isinstance(base_revisions, dict):
            raise ValidationError("base_revisions must be a closed RFC-id to revision map")
        expected = {parent_rfc_id, child_rfc_id}
        if set(base_revisions) != expected:
            raise ValidationError("base_revisions must contain exactly parent_rfc_id and child_rfc_id")
        normalized: dict[str, int] = {}
        for rfc_id, revision in base_revisions.items():
            if not isinstance(revision, int) or isinstance(revision, bool) or revision < 1:
                raise ValidationError("RFC base revisions must be positive integers")
            normalized[rfc_id] = revision
        return normalized

    @staticmethod
    def _load_rfc(connection, rfc_id: str) -> tuple[str | None, int]:
        row = connection.execute(
            "SELECT customer_org_id,revision FROM rfcs WHERE rfc_id=?",
            (rfc_id,),
        ).fetchone()
        if row is None:
            raise SomaError("NOT_FOUND", "RFC does not exist")
        customer_org_id = None if row[0] is None else str(row[0])
        return customer_org_id, int(row[1])

    def _result(
        self,
        *,
        parent_rfc_id: str,
        child_rfc_id: str,
        fallback_edge_id: str | None,
        replayed: bool,
        no_change: bool,
    ) -> RfcHierarchyResult:
        with ReadSnapshot(self._factory) as snapshot:
            edge = snapshot.connection.execute(
                "SELECT rfc_hierarchy_edge_id FROM rfc_hierarchy_edges "
                "WHERE parent_rfc_id=? AND child_rfc_id=? AND edge_state='active'",
                (parent_rfc_id, child_rfc_id),
            ).fetchone()
            parent_customer, parent_revision = self._load_rfc(snapshot.connection, parent_rfc_id)
            child_customer, child_revision = self._load_rfc(snapshot.connection, child_rfc_id)
        if edge is None and fallback_edge_id is None:
            raise SomaError("PERSISTENCE_FAILURE", "RFC hierarchy mutation did not resolve an active edge")
        warnings: tuple[str, ...] = ()
        if parent_customer is None or child_customer is None:
            warnings = ("RFC_CUSTOMER_UNRESOLVED",)
        return RfcHierarchyResult(
            rfc_hierarchy_edge_id=str(edge[0]) if edge is not None else str(fallback_edge_id),
            parent_rfc_id=parent_rfc_id,
            child_rfc_id=child_rfc_id,
            parent_revision=parent_revision,
            child_revision=child_revision,
            replayed=replayed,
            no_change=no_change,
            warnings=warnings,
        )

    def add_subordinate(
        self,
        *,
        command_id: str,
        parent_rfc_id: str,
        child_rfc_id: str,
        base_revisions: dict[str, int],
        reason_category: str,
        review_fingerprint: str | None = None,
        actor_kind: str = "local_user",
        actor_id: str | None = None,
    ) -> RfcHierarchyResult:
        if parent_rfc_id == child_rfc_id:
            raise SomaError("RFC_HIERARCHY_CYCLE", "RFC cannot be its own parent")
        revisions = self._validate_base_revisions(parent_rfc_id, child_rfc_id, base_revisions)
        reason = validate_reason_category(reason_category)
        review = validate_optional_sha256(review_fingerprint, field="review_fingerprint")
        envelope = CommandEnvelope(
            command_id=command_id,
            command_type="AddRfcSubordinate",
            target_type="rfc_hierarchy",
            target_id=parent_rfc_id,
            semantic_payload={
                "parent_rfc_id": parent_rfc_id,
                "child_rfc_id": child_rfc_id,
                "reason_category": reason,
                "review_fingerprint": review,
            },
            base_revisions=revisions,
            authorizing_fingerprints={} if review is None else {"review": review},
        )

        def prepare(uow: UnitOfWork) -> PreparedMutation:
            parent_customer, parent_revision = self._load_rfc(uow.connection, parent_rfc_id)
            child_customer, child_revision = self._load_rfc(uow.connection, child_rfc_id)
            if parent_revision != revisions[parent_rfc_id] or child_revision != revisions[child_rfc_id]:
                raise SomaError("TICKET_RELATIONSHIP_STALE", "RFC hierarchy revision context changed")

            active_parent = uow.connection.execute(
                "SELECT rfc_hierarchy_edge_id,parent_rfc_id FROM rfc_hierarchy_edges "
                "WHERE child_rfc_id=? AND edge_state='active'",
                (child_rfc_id,),
            ).fetchone()
            if active_parent is not None:
                if str(active_parent[1]) == parent_rfc_id:
                    return PreparedMutation(
                        True,
                        None,
                        None,
                        response_schema="CommandExecutionResultV1",
                        response={"no_change": True, "result_id": None, "result_type": "NO_CHANGE"},
                    )
                raise SomaError("RFC_PARENT_CONFLICT", "RFC already has a different active parent")

            if uow.connection.execute(
                "SELECT 1 FROM rfc_hierarchy_edges WHERE child_rfc_id=? AND edge_state='active'",
                (parent_rfc_id,),
            ).fetchone() is not None:
                raise SomaError("RFC_HIERARCHY_DEPTH", "proposed parent is already subordinate")
            if uow.connection.execute(
                "SELECT 1 FROM rfc_hierarchy_edges WHERE parent_rfc_id=? AND edge_state='active'",
                (child_rfc_id,),
            ).fetchone() is not None:
                raise SomaError("RFC_HIERARCHY_DEPTH", "proposed child already owns subordinates")
            if uow.connection.execute(
                "SELECT 1 FROM sr_rfc_links WHERE rfc_id=? AND link_state='active'",
                (child_rfc_id,),
            ).fetchone() is not None:
                raise SomaError(
                    "RFC_DIRECT_SR_LINK_ON_SUBORDINATE",
                    "RFC with an active direct SR link cannot become subordinate",
                )
            if (
                parent_customer is not None
                and child_customer is not None
                and parent_customer != child_customer
            ):
                raise SomaError(
                    "RFC_CUSTOMER_MISMATCH",
                    "known parent and child RFC Customers differ",
                )

            edge_id = new_uuid4()
            audit_event_id = new_uuid4()
            now = utc_epoch_seconds()

            def apply(inner: UnitOfWork) -> AuditEventInput:
                inner.connection.execute(
                    "INSERT INTO rfc_hierarchy_edges("
                    "rfc_hierarchy_edge_id,parent_rfc_id,child_rfc_id,edge_state,opened_at_utc,opened_command_id"
                    ") VALUES (?, ?, ?, 'active', ?, ?)",
                    (edge_id, parent_rfc_id, child_rfc_id, now, command_id),
                )
                inner.connection.execute(
                    "UPDATE rfcs SET revision=revision+1,updated_at_utc=? WHERE rfc_id IN (?, ?)",
                    (now, parent_rfc_id, child_rfc_id),
                )
                return AuditEventInput(
                    audit_event_id=audit_event_id,
                    action_type="ticket.rfc.hierarchy_changed",
                    action_version=1,
                    actor_kind=actor_kind,
                    actor_id=actor_id,
                    target_type="rfc",
                    target_id=child_rfc_id,
                    reason_category=reason,
                    command_id=command_id,
                    payload_schema="RfcHierarchyAuditV1",
                    payload_version=1,
                    payload={
                        "rfc_id": child_rfc_id,
                        "relationship_id": edge_id,
                        "prior_parent_rfc_id": None,
                        "new_parent_rfc_id": parent_rfc_id,
                        "resulting_revision": child_revision + 1,
                        "reason_category": reason,
                        "review_fingerprint": review,
                    },
                    resulting_event_refs=(
                        AuditResultRef("rfc_hierarchy_edge", edge_id),
                        AuditResultRef("rfc", parent_rfc_id),
                        AuditResultRef("rfc", child_rfc_id),
                    ),
                )

            return PreparedMutation(
                False,
                "rfc_hierarchy_edge",
                edge_id,
                apply,
                response_schema="CommandExecutionResultV1",
                response={"no_change": False, "result_id": edge_id, "result_type": "rfc_hierarchy_edge"},
            )

        result = self._boundary.execute(envelope, prepare)
        return self._result(
            parent_rfc_id=parent_rfc_id,
            child_rfc_id=child_rfc_id,
            fallback_edge_id=result.result_id,
            replayed=result.replayed,
            no_change=result.no_change,
        )
