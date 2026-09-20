from __future__ import annotations

from soma.foundation.application.command_boundary import (
    CommandBoundary,
    CommandEnvelope,
    PreparedMutation,
)
from soma.foundation.audit.writer import AuditEventInput, AuditResultRef, AuditWriter
from soma.foundation.errors import IntegrityFailure, SomaError, ValidationError
from soma.foundation.identifiers import new_uuid4
from soma.foundation.persistence.connections import ConnectionFactory
from soma.foundation.persistence.uow import UnitOfWork

from ..audit_registry import build_inventory_audit_registry
from ..contracts.inventory import (
    InventoryMutationResult,
    inventory_mutation_result_from_execution,
)
from ..domain.proposals import (
    ParsedInventoryProposalTarget,
    normalize_reason_category,
    parse_inventory_proposal_target,
    source_evidence_ref,
    validate_fingerprint,
    validate_positive_revision,
    validate_proposal_id,
)
from ..repositories.fault_tags import InventoryFaultTagsRepository


class InventoryCorrectionsBulkService:
    """Proposal decisions and bulk/correction orchestration owned by LLD-07."""

    def __init__(self, connection_factory: ConnectionFactory) -> None:
        self._boundary = CommandBoundary(
            connection_factory,
            AuditWriter(build_inventory_audit_registry()),
        )

    @staticmethod
    def _proposal_targets(
        uow: UnitOfWork,
        *,
        proposal_id: str,
        proposal_kind: str,
        risk_tier: str,
    ) -> tuple[ParsedInventoryProposalTarget, ...]:
        rows = uow.connection.execute(
            "SELECT inventory_proposal_target_id,target_kind,fault_tag_membership_id,"
            "expected_revision,proposed_action,payload_json "
            "FROM inventory_proposal_targets WHERE inventory_proposal_id=? "
            "ORDER BY inventory_proposal_target_id",
            (proposal_id,),
        ).fetchall()
        if not rows:
            raise IntegrityFailure("Inventory proposal has no target authority")
        parsed: list[ParsedInventoryProposalTarget] = []
        try:
            for row in rows:
                parsed.append(
                    parse_inventory_proposal_target(
                        proposal_target_id=str(row[0]),
                        proposal_kind=proposal_kind,
                        risk_tier=risk_tier,
                        target_kind=str(row[1]),
                        membership_id=None if row[2] is None else str(row[2]),
                        expected_revision=int(row[3]),
                        proposed_action=str(row[4]),
                        payload_json=str(row[5]),
                    )
                )
        except ValidationError as exc:
            raise SomaError(
                "DEPENDENCY_INDETERMINATE",
                "Inventory proposal target contract is unsupported or invalid",
            ) from exc
        return tuple(parsed)

    def accept_inventory_proposal(
        self,
        *,
        command_id: str,
        proposal_id: str,
        expected_revision: int,
        input_fingerprint: str,
        selected_target_ids: tuple[str, ...] | None = None,
        explicit_confirmation: bool = False,
        actor_kind: str = "local_user",
        actor_id: str | None = None,
    ) -> InventoryMutationResult:
        identity = validate_proposal_id(proposal_id)
        revision = validate_positive_revision(expected_revision, "expected_revision")
        fingerprint = validate_fingerprint(input_fingerprint)
        selected: tuple[str, ...] | None = None
        if selected_target_ids is not None:
            selected = tuple(validate_proposal_id(value) for value in selected_target_ids)
            if len(set(selected)) != len(selected):
                raise ValidationError("selected proposal targets contain duplicates")

        envelope = CommandEnvelope(
            command_id=command_id,
            command_type="AcceptInventoryProposal",
            target_type="inventory_proposal",
            target_id=identity,
            semantic_payload={
                "expected_revision": revision,
                "input_fingerprint": fingerprint,
                "selected_target_ids": None if selected is None else list(selected),
                "explicit_confirmation": explicit_confirmation,
            },
            base_revisions={"inventory_proposal": revision},
            authorizing_fingerprints={"proposal": fingerprint},
        )

        def prepare(uow: UnitOfWork) -> PreparedMutation:
            proposal = uow.connection.execute(
                "SELECT proposal_kind,evidence_kind,evidence_id,state,input_fingerprint,"
                "risk_tier,revision FROM inventory_proposals WHERE inventory_proposal_id=?",
                (identity,),
            ).fetchone()
            if proposal is None:
                raise SomaError("PROPOSAL_STALE", "Inventory proposal is missing")
            proposal_kind = str(proposal[0])
            evidence_kind = str(proposal[1])
            evidence_id = str(proposal[2])
            if (
                str(proposal[3]) != "pending"
                or str(proposal[4]) != fingerprint
                or int(proposal[6]) != revision
            ):
                raise SomaError("PROPOSAL_STALE", "Inventory proposal changed")
            risk_tier = str(proposal[5])
            targets = self._proposal_targets(
                uow,
                proposal_id=identity,
                proposal_kind=proposal_kind,
                risk_tier=risk_tier,
            )
            complete_ids = tuple(target.proposal_target_id for target in targets)
            if selected is not None and set(selected) != set(complete_ids):
                raise SomaError(
                    "DEPENDENCY_INDETERMINATE",
                    "Beta 1.0 Inventory proposal acceptance is all-target atomic",
                )
            if proposal_kind == "warehouse_final_decision" and explicit_confirmation is not True:
                raise SomaError(
                    "DEPENDENCY_INDETERMINATE",
                    "Material warehouse final-decision proposal requires explicit confirmation",
                )

            repo = InventoryFaultTagsRepository()
            for target in targets:
                repo._require_warehouse_target(
                    uow.connection,
                    membership_id=target.membership_id,
                    expected_revision=target.expected_revision,
                    required_state=(
                        "submitted_awaiting_receipt"
                        if target.action == "warehouse_received"
                        else "warehouse_received"
                    ),
                )

            batch_id = new_uuid4() if len(targets) > 1 else None
            resulting_revision = revision + 1
            result_type = "inventory_batch" if batch_id is not None else "inventory_proposal"
            result_id = batch_id if batch_id is not None else identity
            evidence_ref = source_evidence_ref(evidence_kind, evidence_id)

            def apply(inner: UnitOfWork):
                if batch_id is not None:
                    repo.insert_lifecycle_batch(
                        inner.connection,
                        batch_id=batch_id,
                        batch_kind="proposal_acceptance",
                        target_count=len(targets),
                        command_id=command_id,
                    )
                result_rows: list[dict[str, object]] = []
                tag_revisions: dict[str, int] = {}
                for target in targets:
                    if target.action == "warehouse_received":
                        rows, revisions = repo.record_warehouse_receipt(
                            inner.connection,
                            targets=((target.membership_id, target.expected_revision),),
                            effective_at_utc=target.effective_at_utc,
                            evidence_kind=evidence_kind,
                            evidence_id=evidence_id,
                            batch_id=None,
                            command_id=command_id,
                        )
                    else:
                        rows, revisions = repo.record_warehouse_final_decision(
                            inner.connection,
                            targets=((target.membership_id, target.expected_revision),),
                            decision=str(target.decision),
                            reason_code=target.reason_code,
                            effective_at_utc=target.effective_at_utc,
                            evidence_kind=evidence_kind,
                            evidence_id=evidence_id,
                            batch_id=None,
                            command_id=command_id,
                        )
                    result_rows.extend(rows)
                    tag_revisions.update(revisions)
                changed = inner.connection.execute(
                    "UPDATE inventory_proposals SET state='accepted',revision=?,last_command_id=? "
                    "WHERE inventory_proposal_id=? AND state='pending' AND revision=? "
                    "AND input_fingerprint=?",
                    (resulting_revision, command_id, identity, revision, fingerprint),
                )
                if changed.rowcount != 1:
                    raise SomaError("PROPOSAL_STALE", "Inventory proposal changed")
                apply.result_rows = tuple(result_rows)
                apply.tag_revisions = dict(tag_revisions)
                audits: list[AuditEventInput] = []
                for target, item in zip(targets, result_rows, strict=True):
                    event_kind = (
                        "RECEIVED"
                        if target.action == "warehouse_received"
                        else ("ACCEPTED" if target.decision == "accepted" else "REJECTED")
                    )
                    audits.append(
                        AuditEventInput(
                            audit_event_id=new_uuid4(),
                            action_type="inventory.fault_tag.warehouse_state_changed",
                            action_version=1,
                            actor_kind=actor_kind,
                            actor_id=actor_id,
                            target_type="fault_tag_membership",
                            target_id=target.membership_id,
                            command_id=command_id,
                            reason_category=target.reason_code,
                            payload_schema="WarehouseDecisionAuditV1",
                            payload_version=1,
                            payload={
                                "membership_id": target.membership_id,
                                "event_kind": event_kind,
                                "rma_id": str(item["rma_id"]),
                                "return_obligation_id": str(item["rma_id"]),
                                "batch_id": batch_id,
                                "effective_at_utc": target.effective_at_utc,
                                "explicit_confirmation": True,
                            },
                            resulting_event_refs=(
                                AuditResultRef(
                                    "fault_tag_membership_event",
                                    str(item["membership_event_id"]),
                                ),
                            ),
                        )
                    )
                audits.append(
                    AuditEventInput(
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
                            "decision": "ACCEPT",
                            "input_fingerprint": fingerprint,
                            "accepted_target_count": len(targets),
                            "deferred_or_rejected_count": 0,
                            "source_evidence_ref": evidence_ref,
                            "reason_category": None,
                        },
                        resulting_event_refs=(
                            AuditResultRef("inventory_proposal", identity),
                        ),
                    )
                )
                return tuple(audits)

            apply.result_rows = ()
            apply.tag_revisions = {}
            response_refs = [{"type": "inventory_proposal", "id": identity}]
            if batch_id is not None:
                response_refs.insert(0, {"type": "inventory_batch", "id": batch_id})
            return PreparedMutation(
                no_change=False,
                result_type=result_type,
                result_id=result_id,
                apply=apply,
                response_schema="InventoryMutationResultV1",
                response_factory=lambda _inner: {
                    "outcome": "APPLIED",
                    "target_refs": response_refs,
                    "revisions": {
                        identity: resulting_revision,
                        **{
                            f"fault_tag_membership:{row['membership_id']}": int(
                                row["membership_revision"]
                            )
                            for row in apply.result_rows
                        },
                        **{
                            f"fault_tag:{tag_id}": tag_revision
                            for tag_id, tag_revision in apply.tag_revisions.items()
                        },
                    },
                },
            )

        return inventory_mutation_result_from_execution(
            self._boundary.execute(envelope, prepare)
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
