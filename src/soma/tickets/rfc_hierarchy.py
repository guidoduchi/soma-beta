from __future__ import annotations

from soma.foundation.application.command_boundary import CommandBoundary, CommandEnvelope, PreparedMutation
from soma.foundation.audit.writer import AuditEventInput, AuditResultRef, AuditWriter
from soma.foundation.errors import IntegrityFailure, SomaError, ValidationError
from soma.foundation.identifiers import new_uuid4, require_uuid4, utc_epoch_seconds
from soma.foundation.persistence.connections import ConnectionFactory
from soma.foundation.persistence.uow import UnitOfWork

from .audit_registry import build_tickets_audit_registry
from .queries.relationship_previews import RfcHierarchyPreviewEvaluator, RfcHistoryRiskProvider
from .queries.rfc_branches import RfcBranch, RfcBranchQueryService
from .validation import validate_optional_sha256, validate_reason_category


class RfcHierarchyService:
    def __init__(
        self,
        connection_factory: ConnectionFactory,
        history_risk_provider: RfcHistoryRiskProvider | None = None,
    ) -> None:
        self._branch_query = RfcBranchQueryService(connection_factory)
        self._preview_evaluator = RfcHierarchyPreviewEvaluator(history_risk_provider)
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
    def _validate_mutation_base_revisions(
        base_revisions: dict[str, int],
        *,
        maximum_participants: int,
    ) -> dict[str, int]:
        if not isinstance(base_revisions, dict) or not 1 <= len(base_revisions) <= maximum_participants:
            raise ValidationError("base_revisions must be a bounded closed RFC-id to revision map")
        normalized: dict[str, int] = {}
        for rfc_id, revision in base_revisions.items():
            canonical_id = require_uuid4(rfc_id)
            if canonical_id != rfc_id:
                raise ValidationError("RFC base revision keys must use canonical UUID identities")
            if type(revision) is not int or revision < 1:
                raise ValidationError("RFC base revisions must be positive integers")
            normalized[canonical_id] = revision
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

    def _branch_response_factory(self, root_rfc_id: str):
        def build_response(uow: UnitOfWork):
            return self._branch_query.get_from_connection(
                uow.connection,
                root_rfc_id=root_rfc_id,
                cursor=None,
                limit=100,
            ).to_response()

        return build_response

    @staticmethod
    def _raise_first_hierarchy_blocker(blockers: tuple[str, ...]) -> None:
        if not blockers:
            return
        code = blockers[0]
        messages = {
            "RFC_HIERARCHY_CYCLE": "proposed RFC hierarchy would create a self/cycle relation",
            "RFC_PARENT_CONFLICT": "RFC is already attached to the proposed parent",
            "RFC_HIERARCHY_DEPTH": "proposed RFC hierarchy would exceed two levels",
            "RFC_DIRECT_SR_LINK_ON_SUBORDINATE": "RFC with an active direct SR link cannot be subordinate",
            "RFC_CUSTOMER_MISMATCH": "known RFC Customers differ across the proposed hierarchy relation",
        }
        raise SomaError(code, messages.get(code, "RFC hierarchy mutation is blocked"))

    @staticmethod
    def _require_current_review(preview, supplied_review: str | None) -> None:
        authority = preview.history_authority
        if authority.status != "READY" or preview.review_fingerprint is None:
            raise SomaError(
                "TICKET_RELATIONSHIP_STALE",
                "RFC hierarchy history authority is indeterminate; refresh the hierarchy review",
            )
        if preview.review_required and supplied_review is None:
            raise SomaError(
                "RFC_REPARENT_REVIEW_REQUIRED",
                "protected RFC Task/WFM history requires an exact reviewed hierarchy correction",
            )
        if supplied_review is not None and supplied_review != preview.review_fingerprint:
            raise SomaError(
                "TICKET_RELATIONSHIP_STALE",
                "RFC hierarchy review authority changed since preview",
            )

    @staticmethod
    def _require_exact_preview_revisions(
        supplied: dict[str, int],
        current: dict[str, int],
    ) -> None:
        if supplied != current:
            raise SomaError(
                "TICKET_RELATIONSHIP_STALE",
                "RFC hierarchy participants or revisions changed since preview",
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
    ) -> RfcBranch:
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
                        response_schema="RfcBranchV1",
                        response_version=1,
                        response_factory=self._branch_response_factory(parent_rfc_id),
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
                response_schema="RfcBranchV1",
                response_version=1,
                response_factory=self._branch_response_factory(parent_rfc_id),
            )

        result = self._boundary.execute(envelope, prepare)
        if result.response_schema != "RfcBranchV1" or result.response_version != 1:
            raise IntegrityFailure("RFC hierarchy committed response contract is invalid")
        return RfcBranch.from_response(result.response)

    def reparent_subordinate(
        self,
        *,
        command_id: str,
        child_rfc_id: str,
        new_parent_rfc_id: str,
        base_revisions: dict[str, int],
        reason_category: str,
        review_fingerprint: str | None = None,
        actor_kind: str = "local_user",
        actor_id: str | None = None,
    ) -> RfcBranch:
        child_id = require_uuid4(child_rfc_id)
        new_parent_id = require_uuid4(new_parent_rfc_id)
        revisions = self._validate_mutation_base_revisions(base_revisions, maximum_participants=3)
        reason = validate_reason_category(reason_category)
        review = validate_optional_sha256(review_fingerprint, field="review_fingerprint")
        envelope = CommandEnvelope(
            command_id=command_id,
            command_type="ReparentRfc",
            target_type="rfc_hierarchy",
            target_id=child_id,
            semantic_payload={
                "child_rfc_id": child_id,
                "new_parent_rfc_id": new_parent_id,
                "reason_category": reason,
                "review_fingerprint": review,
            },
            base_revisions=revisions,
            authorizing_fingerprints={} if review is None else {"review": review},
        )

        def prepare(uow: UnitOfWork) -> PreparedMutation:
            preview = self._preview_evaluator.evaluate(
                uow,
                action="reparent",
                child_rfc_id=child_id,
                new_parent_rfc_id=new_parent_id,
            )
            self._require_exact_preview_revisions(revisions, preview.base_revisions)
            self._require_current_review(preview, review)
            self._raise_first_hierarchy_blocker(preview.blockers)

            old_parent_id = preview.old_parent_rfc_id
            old_edge_id = preview.old_edge_id
            new_edge_id = new_uuid4()
            audit_event_id = new_uuid4()
            now = utc_epoch_seconds()
            resulting_child_revision = preview.base_revisions[child_id] + 1

            def apply(inner: UnitOfWork) -> AuditEventInput:
                closed = inner.connection.execute(
                    "UPDATE rfc_hierarchy_edges SET edge_state='superseded',closed_at_utc=?,closed_command_id=? "
                    "WHERE rfc_hierarchy_edge_id=? AND parent_rfc_id=? AND child_rfc_id=? AND edge_state='active'",
                    (now, command_id, old_edge_id, old_parent_id, child_id),
                )
                if closed.rowcount != 1:
                    raise IntegrityFailure("reviewed RFC hierarchy edge disappeared before reparent")
                inner.connection.execute(
                    "INSERT INTO rfc_hierarchy_edges("
                    "rfc_hierarchy_edge_id,parent_rfc_id,child_rfc_id,edge_state,opened_at_utc,opened_command_id"
                    ") VALUES (?, ?, ?, 'active', ?, ?)",
                    (new_edge_id, new_parent_id, child_id, now, command_id),
                )
                updated = inner.connection.execute(
                    "UPDATE rfcs SET revision=revision+1,updated_at_utc=? WHERE rfc_id IN (?, ?, ?)",
                    (now, old_parent_id, child_id, new_parent_id),
                )
                if updated.rowcount != 3:
                    raise IntegrityFailure("reviewed RFC reparent participant set changed during mutation")
                return AuditEventInput(
                    audit_event_id=audit_event_id,
                    action_type="ticket.rfc.hierarchy_changed",
                    action_version=1,
                    actor_kind=actor_kind,
                    actor_id=actor_id,
                    target_type="rfc",
                    target_id=child_id,
                    reason_category=reason,
                    command_id=command_id,
                    payload_schema="RfcHierarchyAuditV1",
                    payload_version=1,
                    payload={
                        "rfc_id": child_id,
                        "relationship_id": new_edge_id,
                        "prior_parent_rfc_id": old_parent_id,
                        "new_parent_rfc_id": new_parent_id,
                        "resulting_revision": resulting_child_revision,
                        "reason_category": reason,
                        "review_fingerprint": review,
                    },
                    resulting_event_refs=(
                        AuditResultRef("rfc_hierarchy_edge", old_edge_id),
                        AuditResultRef("rfc_hierarchy_edge", new_edge_id),
                        AuditResultRef("rfc", old_parent_id),
                        AuditResultRef("rfc", new_parent_id),
                        AuditResultRef("rfc", child_id),
                    ),
                )

            return PreparedMutation(
                False,
                "rfc_hierarchy_edge",
                new_edge_id,
                apply,
                response_schema="RfcBranchV1",
                response_version=1,
                response_factory=self._branch_response_factory(new_parent_id),
            )

        result = self._boundary.execute(envelope, prepare)
        if result.response_schema != "RfcBranchV1" or result.response_version != 1 or result.no_change:
            raise IntegrityFailure("RFC reparent committed response contract is invalid")
        return RfcBranch.from_response(result.response)

    def detach_subordinate(
        self,
        *,
        command_id: str,
        child_rfc_id: str,
        base_revisions: dict[str, int],
        reason_category: str,
        review_fingerprint: str | None = None,
        actor_kind: str = "local_user",
        actor_id: str | None = None,
    ) -> RfcBranch:
        child_id = require_uuid4(child_rfc_id)
        revisions = self._validate_mutation_base_revisions(base_revisions, maximum_participants=2)
        reason = validate_reason_category(reason_category)
        review = validate_optional_sha256(review_fingerprint, field="review_fingerprint")
        envelope = CommandEnvelope(
            command_id=command_id,
            command_type="DetachRfc",
            target_type="rfc_hierarchy",
            target_id=child_id,
            semantic_payload={
                "child_rfc_id": child_id,
                "reason_category": reason,
                "review_fingerprint": review,
            },
            base_revisions=revisions,
            authorizing_fingerprints={} if review is None else {"review": review},
        )

        def prepare(uow: UnitOfWork) -> PreparedMutation:
            preview = self._preview_evaluator.evaluate(
                uow,
                action="detach",
                child_rfc_id=child_id,
                new_parent_rfc_id=None,
            )
            self._require_exact_preview_revisions(revisions, preview.base_revisions)
            self._require_current_review(preview, review)
            self._raise_first_hierarchy_blocker(preview.blockers)

            old_parent_id = preview.old_parent_rfc_id
            old_edge_id = preview.old_edge_id
            audit_event_id = new_uuid4()
            now = utc_epoch_seconds()
            resulting_child_revision = preview.base_revisions[child_id] + 1

            def apply(inner: UnitOfWork) -> AuditEventInput:
                closed = inner.connection.execute(
                    "UPDATE rfc_hierarchy_edges SET edge_state='superseded',closed_at_utc=?,closed_command_id=? "
                    "WHERE rfc_hierarchy_edge_id=? AND parent_rfc_id=? AND child_rfc_id=? AND edge_state='active'",
                    (now, command_id, old_edge_id, old_parent_id, child_id),
                )
                if closed.rowcount != 1:
                    raise IntegrityFailure("reviewed RFC hierarchy edge disappeared before detach")
                updated = inner.connection.execute(
                    "UPDATE rfcs SET revision=revision+1,updated_at_utc=? WHERE rfc_id IN (?, ?)",
                    (now, old_parent_id, child_id),
                )
                if updated.rowcount != 2:
                    raise IntegrityFailure("reviewed RFC detach participant set changed during mutation")
                return AuditEventInput(
                    audit_event_id=audit_event_id,
                    action_type="ticket.rfc.hierarchy_changed",
                    action_version=1,
                    actor_kind=actor_kind,
                    actor_id=actor_id,
                    target_type="rfc",
                    target_id=child_id,
                    reason_category=reason,
                    command_id=command_id,
                    payload_schema="RfcHierarchyAuditV1",
                    payload_version=1,
                    payload={
                        "rfc_id": child_id,
                        "relationship_id": old_edge_id,
                        "prior_parent_rfc_id": old_parent_id,
                        "new_parent_rfc_id": None,
                        "resulting_revision": resulting_child_revision,
                        "reason_category": reason,
                        "review_fingerprint": review,
                    },
                    resulting_event_refs=(
                        AuditResultRef("rfc_hierarchy_edge", old_edge_id),
                        AuditResultRef("rfc", old_parent_id),
                        AuditResultRef("rfc", child_id),
                    ),
                )

            return PreparedMutation(
                False,
                "rfc_hierarchy_edge",
                old_edge_id,
                apply,
                response_schema="RfcBranchV1",
                response_version=1,
                response_factory=self._branch_response_factory(child_id),
            )

        result = self._boundary.execute(envelope, prepare)
        if result.response_schema != "RfcBranchV1" or result.response_version != 1 or result.no_change:
            raise IntegrityFailure("RFC detach committed response contract is invalid")
        return RfcBranch.from_response(result.response)
