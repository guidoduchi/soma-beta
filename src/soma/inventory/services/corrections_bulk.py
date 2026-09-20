from __future__ import annotations

from soma.foundation.application.command_boundary import (
    CommandBoundary,
    CommandEnvelope,
    PreparedMutation,
)
from soma.foundation.audit.writer import AuditEventInput, AuditResultRef, AuditWriter
from soma.foundation.errors import IntegrityFailure, SomaError
from soma.foundation.identifiers import new_uuid4
from soma.foundation.persistence.connections import ConnectionFactory
from soma.foundation.persistence.uow import UnitOfWork

from ..audit_registry import build_inventory_audit_registry
from ..contracts.inventory import (
    InventoryMutationResult,
    inventory_mutation_result_from_execution,
)
from ..domain.proposals import (
    normalize_reason_category,
    source_evidence_ref,
    validate_fingerprint,
    validate_positive_revision,
    validate_proposal_id,
)


class InventoryCorrectionsBulkService:
    """Proposal decisions and bulk/correction orchestration owned by LLD-07."""

    def __init__(self, connection_factory: ConnectionFactory) -> None:
        self._boundary = CommandBoundary(
            connection_factory,
            AuditWriter(build_inventory_audit_registry()),
        )

    def reject_inventory_proposal(
        self,
        *,
        command_id: str,
        proposal_id: str,
        expected_revision: int,
        input_fingerprint: str,
        reason_category: str,
        actor_kind: str = "local_user",
        actor_id: str | None = None,
    ) -> InventoryMutationResult:
        identity = validate_proposal_id(proposal_id)
        revision = validate_positive_revision(expected_revision, "expected_revision")
        fingerprint = validate_fingerprint(input_fingerprint)
        reason = normalize_reason_category(reason_category)
        envelope = CommandEnvelope(
            command_id=command_id,
            command_type="RejectInventoryProposal",
            target_type="inventory_proposal",
            target_id=identity,
            semantic_payload={
                "expected_revision": revision,
                "input_fingerprint": fingerprint,
                "reason_category": reason,
            },
            base_revisions={"inventory_proposal": revision},
            authorizing_fingerprints={"proposal": fingerprint},
        )

        def prepare(uow: UnitOfWork) -> PreparedMutation:
            row = uow.connection.execute(
                "SELECT state,input_fingerprint,evidence_kind,evidence_id,revision "
                "FROM inventory_proposals WHERE inventory_proposal_id=?",
                (identity,),
            ).fetchone()
            if row is None:
                raise SomaError("PROPOSAL_STALE", "Inventory proposal is missing")
            if (
                str(row[0]) != "pending"
                or str(row[1]) != fingerprint
                or int(row[4]) != revision
            ):
                raise SomaError("PROPOSAL_STALE", "Inventory proposal changed")
            target_count = int(
                uow.connection.execute(
                    "SELECT COUNT(*) FROM inventory_proposal_targets "
                    "WHERE inventory_proposal_id=?",
                    (identity,),
                ).fetchone()[0]
            )
            if target_count <= 0:
                raise IntegrityFailure("Inventory proposal has no target authority")
            evidence_ref = source_evidence_ref(str(row[2]), str(row[3]))
            resulting_revision = revision + 1

            def apply(inner: UnitOfWork):
                cursor = inner.connection.execute(
                    "UPDATE inventory_proposals SET state='rejected',revision=?,last_command_id=? "
                    "WHERE inventory_proposal_id=? AND state='pending' "
                    "AND revision=? AND input_fingerprint=?",
                    (resulting_revision, command_id, identity, revision, fingerprint),
                )
                if cursor.rowcount != 1:
                    raise SomaError("PROPOSAL_STALE", "Inventory proposal changed")
                return AuditEventInput(
                    audit_event_id=new_uuid4(),
                    action_type="inventory.proposal.decided",
                    action_version=1,
                    actor_kind=actor_kind,
                    actor_id=actor_id,
                    target_type="inventory_proposal",
                    target_id=identity,
                    command_id=command_id,
                    payload_schema="InventoryProposalAuditV1",
                    payload_version=1,
                    payload={
                        "proposal_id": identity,
                        "decision": "REJECT",
                        "input_fingerprint": fingerprint,
                        "accepted_target_count": 0,
                        "deferred_or_rejected_count": target_count,
                        "source_evidence_ref": evidence_ref,
                        "reason_category": reason,
                    },
                    resulting_event_refs=(
                        AuditResultRef("inventory_proposal", identity),
                    ),
                )

            return PreparedMutation(
                no_change=False,
                result_type="inventory_proposal",
                result_id=identity,
                apply=apply,
                response_schema="InventoryMutationResultV1",
                response={
                    "outcome": "APPLIED",
                    "target_refs": [{"type": "inventory_proposal", "id": identity}],
                    "revisions": {identity: resulting_revision},
                },
            )

        return inventory_mutation_result_from_execution(
            self._boundary.execute(envelope, prepare)
        )


__all__ = ["InventoryCorrectionsBulkService"]
