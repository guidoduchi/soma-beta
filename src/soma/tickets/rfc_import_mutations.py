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
from .validation import validate_rfc_no


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
