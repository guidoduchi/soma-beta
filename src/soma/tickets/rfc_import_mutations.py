from __future__ import annotations

import hmac
from dataclasses import dataclass
from typing import Any

from soma.foundation.audit.writer import AuditEventInput, AuditResultRef
from soma.foundation.errors import SomaError
from soma.foundation.identifiers import new_uuid4, require_uuid4, utc_epoch_seconds
from soma.foundation.persistence.uow import UnitOfWork
from soma.foundation.strict_json import sha256_canonical_json

from .rfc_import_reader import RfcImportReader
from .rfc_source_projection import (
    RfcAcceptedFieldDelta,
    RfcSourceEvidenceProvider,
    RfcSourceProjectionApplyResult,
    RfcSourceProjectionService,
    RfcTerminalCascadeCaptureParticipant,
)
from .validation import validate_official_sr_no, validate_rfc_no


@dataclass(frozen=True, slots=True)
class RfcCreateFromSourceMutation:
    rfc_no: str
    base_state_token: str
    accepted_command_id: str
    actor_kind: str = "local_user"
    actor_id: str | None = None


@dataclass(frozen=True, slots=True)
class RfcCreateFromSourceResult:
    rfc_id: str
    result_refs: tuple[tuple[str, str], ...]
    audit_events: tuple[AuditEventInput, ...]


@dataclass(frozen=True, slots=True)
class RfcSourceProjectionMutation:
    rfc_id: str
    base_state_token: str
    deltas: tuple[RfcAcceptedFieldDelta, ...]
    accepted_command_id: str
    review_fingerprint: str | None = None
    actor_kind: str = "local_user"
    actor_id: str | None = None


@dataclass(frozen=True, slots=True)
class RfcCustomerReviewMutation:
    rfc_id: str
    target_customer_org_id: str
    expected_prior_customer_org_id: str | None
    base_state_token: str
    accepted_command_id: str
    reason_category: str | None = None
    review_fingerprint: str | None = None
    actor_kind: str = "local_user"
    actor_id: str | None = None


@dataclass(frozen=True, slots=True)
class RfcCustomerReviewResult:
    rfc_id: str
    resulting_revision: int
    result_refs: tuple[tuple[str, str], ...]
    audit_events: tuple[AuditEventInput, ...]


@dataclass(frozen=True, slots=True)
class RfcSrLinkReviewContext:
    service_request_id: str
    requested_rfc_id: str
    governing_root_rfc_id: str
    subordinate_origin_rfc_id: str | None
    sr_revision: int
    rfc_revision: int
    duplicate_active: bool
    review_required: bool
    risk_class: str
    warnings: tuple[str, ...]
    base_state_token: str


@dataclass(frozen=True, slots=True)
class RfcSrLinkReviewMutation:
    service_request_id: str
    requested_rfc_id: str
    base_state_token: str
    accepted_command_id: str
    reason_category: str | None = None
    actor_kind: str = "local_user"
    actor_id: str | None = None


@dataclass(frozen=True, slots=True)
class RfcSrLinkReviewResult:
    relationship_id: str
    service_request_revision: int
    rfc_revision: int
    result_refs: tuple[tuple[str, str], ...]
    audit_events: tuple[AuditEventInput, ...]


@dataclass(frozen=True, slots=True)
class RfcImportMutationResult:
    result_refs: tuple[tuple[str, str], ...]
    projection_result: RfcSourceProjectionApplyResult
    audit_events: tuple[AuditEventInput, ...]


class RfcImportMutationService:
    """LLD-03 RFC import owner used inside LLD-04's already-open UnitOfWork."""

    def __init__(
        self,
        evidence_provider: RfcSourceEvidenceProvider,
        *,
        terminal_capture_participant: RfcTerminalCascadeCaptureParticipant | None = None,
    ) -> None:
        self._projection_service = RfcSourceProjectionService(
            evidence_provider,
            terminal_capture_participant=terminal_capture_participant,
        )

    @staticmethod
    def source_identity_base_token(reader: Any, rfc_no: str) -> str:
        canonical = validate_rfc_no(rfc_no)
        row = reader.execute(
            "SELECT rfc_id,customer_org_id,local_archive_state,revision FROM rfcs WHERE rfc_no=?",
            (canonical,),
        ).fetchone()
        target = None
        if row is not None:
            target = {
                "rfc_id": str(row[0]),
                "customer_org_id": None if row[1] is None else str(row[1]),
                "local_archive_state": str(row[2]),
                "revision": int(row[3]),
            }
        return sha256_canonical_json(
            {
                "schema": "RFC_SOURCE_IDENTITY_BASE_V1",
                "rfc_no": canonical,
                "target": target,
            }
        )

    def create_or_adopt_from_source(
        self,
        uow: UnitOfWork,
        mutation: RfcCreateFromSourceMutation,
    ) -> RfcCreateFromSourceResult:
        canonical = validate_rfc_no(mutation.rfc_no)
        current_token = self.source_identity_base_token(uow.connection, canonical)
        if not hmac.compare_digest(current_token, mutation.base_state_token):
            raise SomaError("IMPORT_PROPOSAL_STALE", "RFC identity base state changed")
        existing = uow.connection.execute(
            "SELECT rfc_id FROM rfcs WHERE rfc_no=?",
            (canonical,),
        ).fetchone()
        if existing is not None:
            raise SomaError(
                "IMPORT_PROPOSAL_STALE",
                "exact RFC identity already exists and no domain creation remains",
            )

        rfc_id = new_uuid4()
        audit_event_id = new_uuid4()
        now = utc_epoch_seconds()
        uow.connection.execute(
            "INSERT INTO rfcs(rfc_id,rfc_no,customer_org_id,local_archive_state,revision,created_at_utc,updated_at_utc) "
            "VALUES (?, ?, NULL, 'active', 1, ?, ?)",
            (rfc_id, canonical, now, now),
        )
        owner_audit = AuditEventInput(
            audit_event_id=audit_event_id,
            action_type="ticket.rfc.identity_created_or_adopted",
            action_version=1,
            actor_kind=mutation.actor_kind,
            actor_id=mutation.actor_id,
            target_type="rfc",
            target_id=rfc_id,
            command_id=mutation.accepted_command_id,
            payload_schema="RfcIdentityAuditV1",
            payload_version=1,
            payload={
                "rfc_id": rfc_id,
                "rfc_no": canonical,
                "creation_context": "accepted_source_adoption",
                "customer_org_id": None,
                "resulting_revision": 1,
            },
            resulting_event_refs=(AuditResultRef("rfc", rfc_id),),
        )
        refs = (("rfc", rfc_id),)
        return RfcCreateFromSourceResult(
            rfc_id=rfc_id,
            result_refs=refs,
            audit_events=(owner_audit,),
        )

    @staticmethod
    def source_acceptance_base_token(reader: Any, rfc_id: str) -> str:
        return RfcImportReader.source_acceptance_base_token(reader, rfc_id)

    def apply_accepted_source_projection(
        self,
        uow: UnitOfWork,
        mutation: RfcSourceProjectionMutation,
    ) -> RfcImportMutationResult:
        current_token = self.source_acceptance_base_token(uow.connection, mutation.rfc_id)
        if not hmac.compare_digest(current_token, mutation.base_state_token):
            raise SomaError("IMPORT_PROPOSAL_STALE", "RFC source projection base state changed")
        projection = self._projection_service.apply_accepted_field_deltas(
            uow,
            rfc_id=mutation.rfc_id,
            accepted_command_id=mutation.accepted_command_id,
            deltas=mutation.deltas,
            review_fingerprint=mutation.review_fingerprint,
            actor_kind=mutation.actor_kind,
            actor_id=mutation.actor_id,
        )
        return RfcImportMutationResult(
            result_refs=projection.result_refs,
            projection_result=projection,
            audit_events=projection.audit_events,
        )

    @staticmethod
    def customer_reconciliation_base_token(
        reader: Any,
        rfc_id: str,
        target_customer_org_id: str,
    ) -> str:
        canonical_rfc_id = require_uuid4(rfc_id)
        canonical_customer_id = require_uuid4(target_customer_org_id)
        row = reader.execute(
            "SELECT customer_org_id,local_archive_state,revision FROM rfcs WHERE rfc_id=?",
            (canonical_rfc_id,),
        ).fetchone()
        if row is None:
            raise SomaError("NOT_FOUND", "RFC does not exist")
        target = reader.execute(
            "SELECT lifecycle_state,revision FROM customer_organizations WHERE customer_org_id=?",
            (canonical_customer_id,),
        ).fetchone()
        if target is None:
            raise SomaError("NOT_FOUND", "Customer Organization does not exist")
        parent = reader.execute(
            "SELECT parent_rfc_id FROM rfc_hierarchy_edges WHERE child_rfc_id=? AND edge_state='active'",
            (canonical_rfc_id,),
        ).fetchone()
        root_id = canonical_rfc_id if parent is None else require_uuid4(str(parent[0]))
        branch_rows = reader.execute(
            "SELECT rfc_id,customer_org_id,revision FROM rfcs WHERE rfc_id=? OR rfc_id IN ("
            "SELECT child_rfc_id FROM rfc_hierarchy_edges WHERE parent_rfc_id=? AND edge_state='active'"
            ") ORDER BY rfc_id ASC",
            (root_id, root_id),
        ).fetchall()
        branch = [
            {
                "rfc_id": require_uuid4(str(branch_row[0])),
                "customer_org_id": None if branch_row[1] is None else require_uuid4(str(branch_row[1])),
                "revision": int(branch_row[2]),
            }
            for branch_row in branch_rows
        ]
        return sha256_canonical_json(
            {
                "schema": "RFC_CUSTOMER_RECONCILIATION_BASE_V1",
                "rfc_id": canonical_rfc_id,
                "current_customer_org_id": None if row[0] is None else require_uuid4(str(row[0])),
                "local_archive_state": str(row[1]),
                "rfc_revision": int(row[2]),
                "governing_root_rfc_id": root_id,
                "branch": branch,
                "target_customer": {
                    "customer_org_id": canonical_customer_id,
                    "lifecycle_state": str(target[0]),
                    "revision": int(target[1]),
                },
            }
        )

    def set_customer_from_review(
        self,
        uow: UnitOfWork,
        mutation: RfcCustomerReviewMutation,
    ) -> RfcCustomerReviewResult:
        canonical_rfc_id = require_uuid4(mutation.rfc_id)
        canonical_customer_id = require_uuid4(mutation.target_customer_org_id)
        current_token = self.customer_reconciliation_base_token(
            uow.connection,
            canonical_rfc_id,
            canonical_customer_id,
        )
        if not hmac.compare_digest(current_token, mutation.base_state_token):
            raise SomaError("IMPORT_PROPOSAL_STALE", "RFC Customer reconciliation base state changed")
        row = uow.connection.execute(
            "SELECT customer_org_id,revision FROM rfcs WHERE rfc_id=?",
            (canonical_rfc_id,),
        ).fetchone()
        if row is None:
            raise SomaError("IMPORT_PROPOSAL_STALE", "RFC target no longer exists")
        prior_customer = None if row[0] is None else require_uuid4(str(row[0]))
        expected_prior = (
            None
            if mutation.expected_prior_customer_org_id is None
            else require_uuid4(mutation.expected_prior_customer_org_id)
        )
        if prior_customer != expected_prior or prior_customer == canonical_customer_id:
            raise SomaError("IMPORT_PROPOSAL_STALE", "RFC Customer proposal no longer represents a material change")
        target = uow.connection.execute(
            "SELECT lifecycle_state FROM customer_organizations WHERE customer_org_id=?",
            (canonical_customer_id,),
        ).fetchone()
        if target is None or str(target[0]) != "active":
            raise SomaError("IMPORT_PROPOSAL_STALE", "reviewed Customer Organization is no longer active")

        parent = uow.connection.execute(
            "SELECT parent_rfc_id FROM rfc_hierarchy_edges WHERE child_rfc_id=? AND edge_state='active'",
            (canonical_rfc_id,),
        ).fetchone()
        root_id = canonical_rfc_id if parent is None else require_uuid4(str(parent[0]))
        branch_rows = uow.connection.execute(
            "SELECT rfc_id,customer_org_id FROM rfcs WHERE rfc_id=? OR rfc_id IN ("
            "SELECT child_rfc_id FROM rfc_hierarchy_edges WHERE parent_rfc_id=? AND edge_state='active'"
            ")",
            (root_id, root_id),
        ).fetchall()
        for branch_id, branch_customer in branch_rows:
            if require_uuid4(str(branch_id)) == canonical_rfc_id or branch_customer is None:
                continue
            if require_uuid4(str(branch_customer)) != canonical_customer_id:
                raise SomaError(
                    "RFC_CUSTOMER_MISMATCH",
                    "known RFC branch members resolve to a different Customer Organization",
                )

        current_revision = int(row[1])
        resulting_revision = current_revision + 1
        now = utc_epoch_seconds()
        audit_event_id = new_uuid4()
        uow.connection.execute(
            "UPDATE rfcs SET customer_org_id=?,revision=revision+1,updated_at_utc=? WHERE rfc_id=? AND revision=?",
            (canonical_customer_id, now, canonical_rfc_id, current_revision),
        )
        updated = uow.connection.execute("SELECT changes()").fetchone()
        if updated is None or int(updated[0]) != 1:
            raise SomaError("IMPORT_PROPOSAL_STALE", "RFC Customer authority changed during acceptance")
        owner_audit = AuditEventInput(
            audit_event_id=audit_event_id,
            action_type="ticket.rfc.customer_changed",
            action_version=1,
            actor_kind=mutation.actor_kind,
            actor_id=mutation.actor_id,
            target_type="rfc",
            target_id=canonical_rfc_id,
            reason_category=mutation.reason_category,
            command_id=mutation.accepted_command_id,
            payload_schema="RfcCustomerAuditV1",
            payload_version=1,
            payload={
                "rfc_id": canonical_rfc_id,
                "prior_customer_org_id": prior_customer,
                "new_customer_org_id": canonical_customer_id,
                "resulting_revision": resulting_revision,
                "reason_category": mutation.reason_category,
                "review_fingerprint": mutation.review_fingerprint,
            },
            resulting_event_refs=(AuditResultRef("rfc", canonical_rfc_id),),
        )
        return RfcCustomerReviewResult(
            rfc_id=canonical_rfc_id,
            resulting_revision=resulting_revision,
            result_refs=(("rfc", canonical_rfc_id),),
            audit_events=(owner_audit,),
        )

    @staticmethod
    def sr_link_candidate_context(
        reader: Any,
        service_request_id: str,
        requested_rfc_id: str,
    ) -> RfcSrLinkReviewContext:
        canonical_sr_id = require_uuid4(service_request_id)
        canonical_requested_rfc_id = require_uuid4(requested_rfc_id)
        sr_row = reader.execute(
            "SELECT official_sr_no,revision FROM service_requests WHERE service_request_id=?",
            (canonical_sr_id,),
        ).fetchone()
        if sr_row is None or sr_row[0] is None:
            raise SomaError("NOT_FOUND", "exact Service Request identity does not exist")
        official_sr_no = validate_official_sr_no(str(sr_row[0]))
        sr_revision = int(sr_row[1])

        requested_row = reader.execute(
            "SELECT rfc_no,revision FROM rfcs WHERE rfc_id=?",
            (canonical_requested_rfc_id,),
        ).fetchone()
        if requested_row is None:
            raise SomaError("NOT_FOUND", "RFC does not exist")
        requested_rfc_no = validate_rfc_no(str(requested_row[0]))
        requested_rfc_revision = int(requested_row[1])
        root_id = RfcImportReader.governing_root(reader, canonical_requested_rfc_id)
        subordinate_origin = None if root_id == canonical_requested_rfc_id else canonical_requested_rfc_id
        root_row = reader.execute(
            "SELECT rfc_no,customer_org_id,local_archive_state,revision FROM rfcs WHERE rfc_id=?",
            (root_id,),
        ).fetchone()
        if root_row is None:
            raise SomaError("NOT_FOUND", "governing RFC root does not exist")
        root_rfc_no = validate_rfc_no(str(root_row[0]))
        root_customer = None if root_row[1] is None else require_uuid4(str(root_row[1]))
        root_archive = str(root_row[2])
        root_revision = int(root_row[3])

        link_state = RfcImportReader.current_link_state(reader, canonical_sr_id, root_id)
        duplicate_active = link_state.get("state") == "ACTIVE"
        active_link_id = link_state.get("sr_rfc_link_id")

        sr_projection = reader.execute(
            "SELECT status_observation_id,revision FROM sr_current_source_projection WHERE service_request_id=?",
            (canonical_sr_id,),
        ).fetchone()
        sr_lifecycle: dict[str, object]
        sr_terminal = False
        if sr_projection is None or sr_projection[0] is None:
            sr_lifecycle = {
                "projection_revision": None if sr_projection is None else int(sr_projection[1]),
                "status_observation_id": None,
                "status": None,
            }
        else:
            status_observation_id = require_uuid4(str(sr_projection[0]))
            status_row = reader.execute(
                "SELECT value_state,text_value,source_observation_field_id FROM sr_source_field_observations "
                "WHERE sr_source_field_observation_id=? AND service_request_id=? AND field_key='status'",
                (status_observation_id, canonical_sr_id),
            ).fetchone()
            if status_row is None:
                raise SomaError("PERSISTENCE_FAILURE", "Service Request status projection is invalid")
            value_state = str(status_row[0])
            status = None if status_row[1] is None else str(status_row[1])
            sr_lifecycle = {
                "projection_revision": int(sr_projection[1]),
                "status_observation_id": status_observation_id,
                "value_state": value_state,
                "status": status,
                "source_observation_field_id": require_uuid4(str(status_row[2])),
            }
            sr_terminal = value_state == "usable" and status in {"Closed", "Resolved", "Cancelled"}

        rfc_projection = reader.execute(
            "SELECT status_class,status_authority,status_evidence_id,terminal_epoch_id,revision "
            "FROM rfc_current_source_projection WHERE rfc_id=?",
            (root_id,),
        ).fetchone()
        if rfc_projection is None:
            rfc_lifecycle = {
                "projection_revision": None,
                "status_class": "unknown",
                "status_authority": None,
                "status_evidence_id": None,
                "terminal_epoch_id": None,
                "local_archive_state": root_archive,
            }
            rfc_terminal = root_archive == "archived"
        else:
            status_class = str(rfc_projection[0])
            rfc_lifecycle = {
                "projection_revision": int(rfc_projection[4]),
                "status_class": status_class,
                "status_authority": None if rfc_projection[1] is None else str(rfc_projection[1]),
                "status_evidence_id": None if rfc_projection[2] is None else str(rfc_projection[2]),
                "terminal_epoch_id": None if rfc_projection[3] is None else str(rfc_projection[3]),
                "local_archive_state": root_archive,
            }
            rfc_terminal = status_class in {"terminal_closed", "terminal_cancelled"} or root_archive == "archived"

        sr_customer_row = reader.execute(
            "SELECT customer_org_id FROM sr_customer_relationships "
            "WHERE service_request_id=? AND relationship_state='active'",
            (canonical_sr_id,),
        ).fetchone()
        sr_customer = None if sr_customer_row is None else require_uuid4(str(sr_customer_row[0]))
        branch_rows = reader.execute(
            "SELECT rfc_id,customer_org_id,revision FROM rfcs WHERE rfc_id=? OR rfc_id IN ("
            "SELECT child_rfc_id FROM rfc_hierarchy_edges WHERE parent_rfc_id=? AND edge_state='active'"
            ") ORDER BY rfc_id ASC",
            (root_id, root_id),
        ).fetchall()
        branch = []
        known_customers = {value for value in (sr_customer, root_customer) if value is not None}
        unresolved_customer = sr_customer is None
        for branch_id, branch_customer, branch_revision in branch_rows:
            canonical_branch_id = require_uuid4(str(branch_id))
            canonical_branch_customer = None if branch_customer is None else require_uuid4(str(branch_customer))
            if canonical_branch_customer is None:
                unresolved_customer = True
            else:
                known_customers.add(canonical_branch_customer)
            branch.append(
                {
                    "rfc_id": canonical_branch_id,
                    "customer_org_id": canonical_branch_customer,
                    "revision": int(branch_revision),
                }
            )
        if len(known_customers) > 1:
            raise SomaError("RFC_CUSTOMER_MISMATCH", "Service Request and RFC branch resolve to different Customers")
        warnings = ("RFC_CUSTOMER_UNRESOLVED",) if unresolved_customer else ()

        review_required = False if duplicate_active else (sr_terminal or rfc_terminal)
        risk_class = "high" if review_required else "medium"
        token = sha256_canonical_json(
            {
                "schema": "RFC_SR_LINK_CANDIDATE_BASE_V1",
                "service_request": {
                    "service_request_id": canonical_sr_id,
                    "official_sr_no": official_sr_no,
                    "revision": sr_revision,
                    "lifecycle": sr_lifecycle,
                    "customer_org_id": sr_customer,
                },
                "requested_rfc": {
                    "rfc_id": canonical_requested_rfc_id,
                    "rfc_no": requested_rfc_no,
                    "revision": requested_rfc_revision,
                },
                "governing_root_rfc": {
                    "rfc_id": root_id,
                    "rfc_no": root_rfc_no,
                    "revision": root_revision,
                    "lifecycle": rfc_lifecycle,
                    "branch": branch,
                },
                "subordinate_origin_rfc_id": subordinate_origin,
                "duplicate_active": duplicate_active,
                "active_link_id": active_link_id,
            }
        )
        return RfcSrLinkReviewContext(
            service_request_id=canonical_sr_id,
            requested_rfc_id=canonical_requested_rfc_id,
            governing_root_rfc_id=root_id,
            subordinate_origin_rfc_id=subordinate_origin,
            sr_revision=sr_revision,
            rfc_revision=root_revision,
            duplicate_active=duplicate_active,
            review_required=review_required,
            risk_class=risk_class,
            warnings=warnings,
            base_state_token=token,
        )

    @staticmethod
    def sr_link_candidate_base_token(reader: Any, service_request_id: str, requested_rfc_id: str) -> str:
        return RfcImportMutationService.sr_link_candidate_context(
            reader,
            service_request_id,
            requested_rfc_id,
        ).base_state_token

    def link_sr_from_review(
        self,
        uow: UnitOfWork,
        mutation: RfcSrLinkReviewMutation,
    ) -> RfcSrLinkReviewResult:
        context = self.sr_link_candidate_context(
            uow.connection,
            mutation.service_request_id,
            mutation.requested_rfc_id,
        )
        if not hmac.compare_digest(context.base_state_token, mutation.base_state_token):
            raise SomaError("IMPORT_PROPOSAL_STALE", "RFC/SR relationship base state changed")
        if context.duplicate_active:
            raise SomaError("IMPORT_PROPOSAL_STALE", "reviewed RFC/SR relationship is already active")

        relationship_id = new_uuid4()
        audit_event_id = new_uuid4()
        now = utc_epoch_seconds()
        uow.connection.execute(
            "INSERT INTO sr_rfc_links(sr_rfc_link_id,service_request_id,rfc_id,link_state,opened_at_utc,opened_command_id) "
            "VALUES (?, ?, ?, 'active', ?, ?)",
            (
                relationship_id,
                context.service_request_id,
                context.governing_root_rfc_id,
                now,
                mutation.accepted_command_id,
            ),
        )
        sr_update = uow.connection.execute(
            "UPDATE service_requests SET revision=revision+1,updated_at_utc=? "
            "WHERE service_request_id=? AND revision=?",
            (now, context.service_request_id, context.sr_revision),
        )
        rfc_update = uow.connection.execute(
            "UPDATE rfcs SET revision=revision+1,updated_at_utc=? WHERE rfc_id=? AND revision=?",
            (now, context.governing_root_rfc_id, context.rfc_revision),
        )
        if sr_update.rowcount != 1 or rfc_update.rowcount != 1:
            raise SomaError("IMPORT_PROPOSAL_STALE", "Service Request or governing RFC changed during acceptance")

        owner_audit = AuditEventInput(
            audit_event_id=audit_event_id,
            action_type="ticket.sr_rfc_relationship.changed",
            action_version=1,
            actor_kind=mutation.actor_kind,
            actor_id=mutation.actor_id,
            target_type="service_request",
            target_id=context.service_request_id,
            reason_category=mutation.reason_category,
            command_id=mutation.accepted_command_id,
            payload_schema="TicketRelationshipAuditV1",
            payload_version=1,
            payload={
                "relationship_type": "service_request_rfc",
                "relationship_id": relationship_id,
                "left_id": context.service_request_id,
                "right_id": context.governing_root_rfc_id,
                "prior_state": None,
                "new_state": "active",
                "reason_category": mutation.reason_category,
                "subordinate_origin_rfc_id": context.subordinate_origin_rfc_id,
            },
            resulting_event_refs=(AuditResultRef("sr_rfc_relationship", relationship_id),),
        )
        return RfcSrLinkReviewResult(
            relationship_id=relationship_id,
            service_request_revision=context.sr_revision + 1,
            rfc_revision=context.rfc_revision + 1,
            result_refs=(("sr_rfc_relationship", relationship_id),),
            audit_events=(owner_audit,),
        )
