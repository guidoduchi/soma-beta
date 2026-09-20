from __future__ import annotations

from soma.foundation.application.command_boundary import (
    CommandBoundary,
    CommandEnvelope,
    PreparedMutation,
)
from soma.foundation.audit.writer import AuditEventInput, AuditResultRef, AuditWriter
from soma.foundation.errors import IntegrityFailure, SomaError, ValidationError
from soma.foundation.identifiers import new_uuid4, require_uuid4
from soma.foundation.persistence.connections import ConnectionFactory
from soma.foundation.persistence.uow import UnitOfWork
from soma.objectives_tasks.queries.tasks import TaskOperationalEvidenceReader

from ..audit_registry import build_inventory_audit_registry
from ..contracts.inventory import (
    InventoryMutationResult,
    inventory_mutation_result_from_execution,
)
from ..domain.consequences import (
    optional_uuid as consequence_optional_uuid,
    validate_consequence_shape,
    validate_disposition,
    validate_effective_at_utc as validate_consequence_effective_at_utc,
)
from ..domain.fault_tags import WarehouseMembershipIntent, validate_warehouse_memberships
from ..domain.rmas import normalize_c10
from ..domain.proposals import (
    ParsedInventoryProposalTarget,
    normalize_reason_category,
    parse_inventory_proposal_target,
    source_evidence_ref,
    validate_fingerprint,
    validate_positive_revision,
    validate_proposal_id,
)
from ..queries.previews import InventoryBulkPreviewQuery
from ..repositories.fault_tags import InventoryFaultTagsRepository
from ..repositories.logistics import InventoryLogisticsRepository
from ..repositories.projections import InventoryProjectionsRepository
from ..repositories.requests import InventoryRequestsRepository
from ..repositories.rmas import InventoryRmasRepository


class InventoryCorrectionsBulkService:
    """Proposal decisions and bulk/correction orchestration owned by LLD-07."""

    def __init__(self, connection_factory: ConnectionFactory) -> None:
        self._requests = InventoryRequestsRepository()
        self._rmas = InventoryRmasRepository()
        self._logistics = InventoryLogisticsRepository()
        self._fault_tags = InventoryFaultTagsRepository()
        self._projections = InventoryProjectionsRepository()
        self._task_evidence = TaskOperationalEvidenceReader()
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


    def accept_inventory_bulk_action(
        self,
        *,
        command_id: str,
        preview_fingerprint: str,
        action_kind: str,
        memberships: tuple[WarehouseMembershipIntent, ...],
        effective_at_utc: int | None = None,
        reason_code: str | None = None,
        explicit_confirmation: bool = False,
        actor_kind: str = "local_user",
        actor_id: str | None = None,
    ) -> InventoryMutationResult:
        fingerprint = validate_fingerprint(preview_fingerprint, "preview_fingerprint")
        targets = validate_warehouse_memberships(memberships)
        if len(targets) > InventoryBulkPreviewQuery._MAX_TARGETS:
            raise ValidationError("Inventory bulk target bound exceeded")
        if action_kind in {"warehouse_accept", "warehouse_reject"} and explicit_confirmation is not True:
            raise SomaError(
                "WAREHOUSE_FINAL_CONFIRMATION_REQUIRED",
                "Bulk warehouse final decision requires explicit operator confirmation",
            )
        # Reuse the pure preview's exact context validation before constructing a receipt.
        InventoryBulkPreviewQuery._context(
            action_kind=action_kind,
            effective_at_utc=effective_at_utc,
            reason_code=reason_code,
        )
        envelope = CommandEnvelope(
            command_id=command_id,
            command_type="AcceptInventoryBulkAction",
            target_type="inventory_batch",
            target_id=None,
            semantic_payload={
                "preview_fingerprint": fingerprint,
                "action_kind": action_kind,
                "targets": [
                    {
                        "fault_tag_membership_id": membership_id,
                        "expected_revision": revision,
                    }
                    for membership_id, revision in targets
                ],
                "effective_at_utc": effective_at_utc,
                "reason_code": reason_code,
                "explicit_confirmation": explicit_confirmation,
            },
            authorizing_fingerprints={"bulk_preview": fingerprint},
        )

        def prepare(uow: UnitOfWork) -> PreparedMutation:
            batch_id = new_uuid4()
            preview = InventoryBulkPreviewQuery.classify_bulk(
                uow.connection,
                action_kind=action_kind,
                targets=tuple((membership_id, revision) for membership_id, revision in targets),
                effective_at_utc=effective_at_utc,
                reason_code=reason_code,
            )
            if preview["input_fingerprint"] != fingerprint:
                raise SomaError("INV_STALE", "Inventory bulk preview changed")
            if not preview["targets"] or any(
                item["status"] != "eligible" for item in preview["targets"]
            ):
                raise SomaError(
                    "BULK_INCOMPATIBLE",
                    "Inventory bulk target set is no longer fully eligible",
                )

            repository = InventoryFaultTagsRepository()

            def apply(inner: UnitOfWork):
                if action_kind == "warehouse_receipt":
                    rows, tag_revisions = repository.record_warehouse_receipt(
                        inner.connection,
                        targets=targets,
                        effective_at_utc=effective_at_utc,
                        evidence_kind=None,
                        evidence_id=None,
                        batch_id=batch_id,
                        command_id=command_id,
                    )
                else:
                    decision = "accepted" if action_kind == "warehouse_accept" else "rejected"
                    rows, tag_revisions = repository.record_warehouse_final_decision(
                        inner.connection,
                        targets=targets,
                        decision=decision,
                        reason_code=reason_code,
                        effective_at_utc=effective_at_utc,
                        evidence_kind=None,
                        evidence_id=None,
                        batch_id=batch_id,
                        command_id=command_id,
                    )
                apply.rows = rows
                apply.tag_revisions = tag_revisions
                audits: list[AuditEventInput] = []
                result_refs: list[dict[str, str]] = []
                for item in rows:
                    event_kind = (
                        "RECEIVED"
                        if action_kind == "warehouse_receipt"
                        else ("ACCEPTED" if action_kind == "warehouse_accept" else "REJECTED")
                    )
                    event_id = str(item["membership_event_id"])
                    result_refs.append(
                        {"type": "fault_tag_membership_event", "id": event_id}
                    )
                    audits.append(
                        AuditEventInput(
                            audit_event_id=new_uuid4(),
                            action_type="inventory.fault_tag.warehouse_state_changed",
                            action_version=1,
                            actor_kind=actor_kind,
                            actor_id=actor_id,
                            target_type="fault_tag_membership",
                            target_id=str(item["membership_id"]),
                            command_id=command_id,
                            reason_category=reason_code,
                            payload_schema="WarehouseDecisionAuditV1",
                            payload_version=1,
                            payload={
                                "membership_id": str(item["membership_id"]),
                                "event_kind": event_kind,
                                "rma_id": str(item["rma_id"]),
                                "return_obligation_id": str(item["rma_id"]),
                                "batch_id": batch_id,
                                "effective_at_utc": effective_at_utc,
                                "explicit_confirmation": True,
                            },
                            resulting_event_refs=(
                                AuditResultRef("fault_tag_membership_event", event_id),
                            ),
                        )
                    )
                audits.append(
                    AuditEventInput(
                        audit_event_id=new_uuid4(),
                        action_type="inventory.bulk.accepted",
                        action_version=1,
                        actor_kind=actor_kind,
                        actor_id=actor_id,
                        target_type="inventory_batch",
                        target_id=batch_id,
                        command_id=command_id,
                        payload_schema="InventoryBulkAuditV1",
                        payload_version=1,
                        payload={
                            "batch_id": batch_id,
                            "action_kind": action_kind,
                            "input_fingerprint": fingerprint,
                            "target_count": len(rows),
                            "result_refs": result_refs,
                            "result": "APPLIED",
                        },
                        resulting_event_refs=(
                            AuditResultRef("inventory_batch", batch_id),
                        ),
                    )
                )
                return tuple(audits)

            apply.rows = ()
            apply.tag_revisions = {}
            return PreparedMutation(
                no_change=False,
                result_type="inventory_batch",
                result_id=batch_id,
                apply=apply,
                response_schema="InventoryMutationResultV1",
                response_factory=lambda _inner: {
                    "outcome": "APPLIED",
                    "target_refs": [{"type": "inventory_batch", "id": batch_id}],
                    "revisions": {
                        **{
                            f"fault_tag_membership:{row['membership_id']}": int(
                                row["membership_revision"]
                            )
                            for row in apply.rows
                        },
                        **{
                            f"fault_tag:{tag_id}": revision
                            for tag_id, revision in apply.tag_revisions.items()
                        },
                    },
                },
            )

        return inventory_mutation_result_from_execution(
            self._boundary.execute(envelope, prepare)
        )


    @staticmethod
    def _correction_generic_audit(
        *,
        command_id: str,
        actor_kind: str,
        actor_id: str | None,
        correction_kind: str,
        target_id: str,
        target_event_id: str | None,
        reason: str,
        result_kind: str,
        result_id: str,
    ) -> AuditEventInput:
        return AuditEventInput(
            audit_event_id=new_uuid4(),
            action_type="inventory.evidence.corrected",
            action_version=1,
            actor_kind=actor_kind,
            actor_id=actor_id,
            target_type=result_kind,
            target_id=result_id,
            command_id=command_id,
            reason_category=reason,
            payload_schema="InventoryCorrectionAuditV1",
            payload_version=1,
            payload={
                "correction_kind": correction_kind,
                "target_id": target_id,
                "target_event_id": target_event_id,
                "reason_category": reason,
                "result_kind": result_kind,
                "result_id": result_id,
            },
            resulting_event_refs=(AuditResultRef(result_kind, result_id),),
        )

    @staticmethod
    def _reject_irrelevant_fields(
        *,
        allowed: frozenset[str],
        values: dict[str, object | None],
    ) -> None:
        extras = sorted(
            key for key, value in values.items()
            if key not in allowed and value is not None
        )
        if extras:
            raise ValidationError(
                "correction kind received fields outside its closed contract"
            )

    def correct_inventory_evidence(
        self,
        *,
        command_id: str,
        correction_kind: str,
        target_id: str,
        reason_code: str,
        target_event_id: str | None = None,
        current_c10: str | None = None,
        new_c10: str | None = None,
        replacement_kind: str | None = None,
        replacement_id: str | None = None,
        expected_revision: int | None = None,
        task_review_fingerprint: str | None = None,
        physical_disposition: str | None = None,
        installed_spare_part_unit_id: str | None = None,
        removed_device_part_unit_id: str | None = None,
        inbound_spare_part_unit_id: str | None = None,
        parent_dismantled_unit_id: str | None = None,
        effective_at_utc: int | None = None,
        actor_kind: str = "local_user",
        actor_id: str | None = None,
    ) -> InventoryMutationResult:
        kinds = {
            "false_spare_request_submission",
            "rma_identifier_alias",
            "logistics_participant_relationship",
            "false_fault_tag_submission",
            "physical_consequence",
            "submitted_fault_tag_material",
            "genuine_later_development",
        }
        if correction_kind not in kinds:
            raise ValidationError("Inventory correction kind is invalid")
        identity = require_uuid4(target_id)
        reason = normalize_reason_category(reason_code)
        raw_values: dict[str, object | None] = {
            "target_event_id": target_event_id,
            "current_c10": current_c10,
            "new_c10": new_c10,
            "replacement_kind": replacement_kind,
            "replacement_id": replacement_id,
            "expected_revision": expected_revision,
            "task_review_fingerprint": task_review_fingerprint,
            "physical_disposition": physical_disposition,
            "installed_spare_part_unit_id": installed_spare_part_unit_id,
            "removed_device_part_unit_id": removed_device_part_unit_id,
            "inbound_spare_part_unit_id": inbound_spare_part_unit_id,
            "parent_dismantled_unit_id": parent_dismantled_unit_id,
            "effective_at_utc": effective_at_utc,
        }

        target_event: str | None = None
        semantic: dict[str, object] = {
            "correction_kind": correction_kind,
            "target_id": identity,
            "reason_code": reason,
        }
        target_type = "inventory_event"
        base_revisions: dict[str, int] = {}
        fingerprints: dict[str, str] = {}

        if correction_kind in {
            "false_spare_request_submission",
            "false_fault_tag_submission",
        }:
            self._reject_irrelevant_fields(
                allowed=frozenset({"target_event_id"}),
                values=raw_values,
            )
            if target_event_id is None:
                raise ValidationError("false-event correction requires target_event_id")
            target_event = require_uuid4(target_event_id)
            semantic["target_event_id"] = target_event
            target_type = (
                "spare_request"
                if correction_kind == "false_spare_request_submission"
                else "fault_tag"
            )
        elif correction_kind == "rma_identifier_alias":
            self._reject_irrelevant_fields(
                allowed=frozenset({"current_c10", "new_c10"}),
                values=raw_values,
            )
            if current_c10 is None or new_c10 is None:
                raise ValidationError("RMA alias correction requires current/new C10")
            current = normalize_c10(current_c10)
            replacement = normalize_c10(new_c10)
            if current == replacement:
                raise ValidationError("RMA C10 correction requires a different identifier")
            semantic.update({"current_c10": current, "new_c10": replacement})
            target_type = "rma"
        elif correction_kind == "logistics_participant_relationship":
            self._reject_irrelevant_fields(
                allowed=frozenset({"replacement_kind", "replacement_id"}),
                values=raw_values,
            )
            if (replacement_kind is None) != (replacement_id is None):
                raise ValidationError(
                    "replacement_kind and replacement_id must both be null or both supplied"
                )
            replacement_identity = None
            if replacement_kind is not None:
                if replacement_kind not in {
                    "rma", "spare_part_unit", "device_part_unit"
                }:
                    raise ValidationError("replacement_kind is invalid")
                assert replacement_id is not None
                replacement_identity = require_uuid4(replacement_id)
            semantic.update(
                {
                    "replacement_kind": replacement_kind,
                    "replacement_id": replacement_identity,
                }
            )
            target_type = "logistics_participant"
        elif correction_kind == "physical_consequence":
            self._reject_irrelevant_fields(
                allowed=frozenset(
                    {
                        "target_event_id",
                        "expected_revision",
                        "task_review_fingerprint",
                        "physical_disposition",
                        "installed_spare_part_unit_id",
                        "removed_device_part_unit_id",
                        "inbound_spare_part_unit_id",
                        "parent_dismantled_unit_id",
                        "effective_at_utc",
                    }
                ),
                values=raw_values,
            )
            if (
                target_event_id is None
                or expected_revision is None
                or task_review_fingerprint is None
                or physical_disposition is None
            ):
                raise ValidationError("physical consequence correction is incomplete")
            if type(expected_revision) is not int or expected_revision <= 0:
                raise ValidationError("expected_revision must be positive")
            target_event = require_uuid4(target_event_id)
            fingerprint = validate_fingerprint(
                task_review_fingerprint, "task_review_fingerprint"
            )
            disposition = validate_disposition(physical_disposition)
            installed = consequence_optional_uuid(
                installed_spare_part_unit_id, "installed_spare_part_unit_id"
            )
            removed = consequence_optional_uuid(
                removed_device_part_unit_id, "removed_device_part_unit_id"
            )
            inbound = consequence_optional_uuid(
                inbound_spare_part_unit_id, "inbound_spare_part_unit_id"
            )
            parent = consequence_optional_uuid(
                parent_dismantled_unit_id, "parent_dismantled_unit_id"
            )
            effective = validate_consequence_effective_at_utc(effective_at_utc)
            validate_consequence_shape(
                disposition=disposition,
                installed_spare_part_unit_id=installed,
                removed_device_part_unit_id=removed,
                inbound_spare_part_unit_id=inbound,
                parent_dismantled_unit_id=parent,
            )
            semantic.update(
                {
                    "target_event_id": target_event,
                    "expected_revision": expected_revision,
                    "task_review_fingerprint": fingerprint,
                    "physical_disposition": disposition,
                    "installed_spare_part_unit_id": installed,
                    "removed_device_part_unit_id": removed,
                    "inbound_spare_part_unit_id": inbound,
                    "parent_dismantled_unit_id": parent,
                    "effective_at_utc": effective,
                }
            )
            base_revisions["inventory_physical_consequence"] = expected_revision
            fingerprints["task_review"] = fingerprint
            target_type = "inventory_physical_consequence"
        else:
            self._reject_irrelevant_fields(allowed=frozenset(), values=raw_values)

        envelope = CommandEnvelope(
            command_id=command_id,
            command_type="CorrectInventoryEvidence",
            target_type=target_type,
            target_id=identity,
            semantic_payload=semantic,
            base_revisions=base_revisions,
            authorizing_fingerprints=fingerprints,
        )

        def prepare(uow: UnitOfWork) -> PreparedMutation:
            if correction_kind == "submitted_fault_tag_material":
                exists = uow.connection.execute(
                    "SELECT 1 FROM fault_tag_submission_snapshots "
                    "WHERE fault_tag_id=? LIMIT 1",
                    (identity,),
                ).fetchone()
                if exists is None:
                    raise SomaError(
                        "CORRECTION_TARGET_INVALID",
                        "Fault Tag has no submitted material authority to replace",
                    )
                raise SomaError(
                    "REPLACEMENT_LINEAGE_CONFLICT",
                    "Submitted Fault Tag material correction requires replacement lineage",
                )
            if correction_kind == "genuine_later_development":
                raise SomaError(
                    "CORRECTION_TARGET_INVALID",
                    "Genuine later development must use its normal lifecycle command",
                )

            if correction_kind == "false_spare_request_submission":
                assert target_event is not None
                current_submission = self._requests.current_effective_submission(
                    uow.connection, identity
                )
                if (
                    current_submission is None
                    or str(current_submission[1]) != target_event
                ):
                    raise SomaError(
                        "CORRECTION_TARGET_INVALID",
                        "Target is not current-effective Spare Request submission",
                    )

                def apply(inner: UnitOfWork):
                    (
                        correction_event_id,
                        snapshot_id,
                        resulting_revision,
                        allocation_count,
                        effective_at,
                        prior_fingerprint,
                    ) = self._requests.correct_false_submission(
                        inner.connection,
                        spare_request_id=identity,
                        submission_event_id=target_event,
                        reason_code=reason,
                        command_id=command_id,
                    )
                    apply.result_id = correction_event_id
                    apply.revision = resulting_revision
                    owner = AuditEventInput(
                        audit_event_id=new_uuid4(),
                        action_type="inventory.spare_request.submitted",
                        action_version=1,
                        actor_kind=actor_kind,
                        actor_id=actor_id,
                        target_type="spare_request",
                        target_id=identity,
                        command_id=command_id,
                        reason_category=reason,
                        payload_schema="SpareRequestSubmissionAuditV1",
                        payload_version=1,
                        payload={
                            "spare_request_id": identity,
                            "submission_event_id": target_event,
                            "submission_snapshot_id": snapshot_id,
                            "event_kind": "CORRECT_FALSE",
                            "allocation_count": allocation_count,
                            "input_fingerprint": prior_fingerprint,
                            "effective_at_utc": effective_at,
                        },
                        resulting_event_refs=(
                            AuditResultRef(
                                "spare_request_submission_snapshot", snapshot_id
                            ),
                        ),
                    )
                    generic = self._correction_generic_audit(
                        command_id=command_id,
                        actor_kind=actor_kind,
                        actor_id=actor_id,
                        correction_kind=correction_kind,
                        target_id=identity,
                        target_event_id=target_event,
                        reason=reason,
                        result_kind="inventory_event",
                        result_id=correction_event_id,
                    )
                    return (owner, generic)

                apply.result_id = ""
                apply.revision = 0
                return PreparedMutation(
                    no_change=False,
                    result_type="spare_request",
                    result_id=identity,
                    apply=apply,
                    response_schema="InventoryMutationResultV1",
                    response_factory=lambda _inner: {
                        "outcome": "APPLIED",
                        "target_refs": [{"type": "spare_request", "id": identity}],
                        "revisions": {f"spare_request:{identity}": apply.revision},
                    },
                )

            if correction_kind == "rma_identifier_alias":
                current = str(semantic["current_c10"])
                replacement = str(semantic["new_c10"])
                row = self._rmas.current_rma(uow.connection, identity)
                if row is None or str(row[5]) != current:
                    raise SomaError("INV_STALE", "RMA current C10 changed")
                if self._rmas.c10_owner(uow.connection, replacement) is not None:
                    raise SomaError("C10_CONFLICT", "C10 is already current or former authority")
                request_id = str(row[1])

                def apply(inner: UnitOfWork):
                    event_id, resulting_revision = self._rmas.correct_c10(
                        inner.connection,
                        rma_id=identity,
                        current_c10=current,
                        new_c10=replacement,
                        reason_code=reason,
                        command_id=command_id,
                    )
                    apply.result_id = event_id
                    apply.revision = resulting_revision
                    owner = AuditEventInput(
                        audit_event_id=new_uuid4(),
                        action_type="inventory.rma.authorized_or_assigned",
                        action_version=1,
                        actor_kind=actor_kind,
                        actor_id=actor_id,
                        target_type="rma",
                        target_id=identity,
                        command_id=command_id,
                        reason_category=reason,
                        payload_schema="RmaAuditV1",
                        payload_version=1,
                        payload={
                            "spare_request_id": request_id,
                            "authorization_batch_id": None,
                            "rma_id": identity,
                            "event_kind": "C10_CORRECT",
                            "current_c10": replacement,
                            "target_device_part_unit_id": (
                                None if row[7] is None else str(row[7])
                            ),
                            "resulting_revision": resulting_revision,
                        },
                        resulting_event_refs=(AuditResultRef("rma", identity),),
                    )
                    generic = self._correction_generic_audit(
                        command_id=command_id,
                        actor_kind=actor_kind,
                        actor_id=actor_id,
                        correction_kind=correction_kind,
                        target_id=identity,
                        target_event_id=None,
                        reason=reason,
                        result_kind="inventory_event",
                        result_id=event_id,
                    )
                    return (owner, generic)

                apply.result_id = ""
                apply.revision = int(row[9]) + 1
                return PreparedMutation(
                    no_change=False,
                    result_type="rma",
                    result_id=identity,
                    apply=apply,
                    response_schema="InventoryMutationResultV1",
                    response_factory=lambda _inner: {
                        "outcome": "APPLIED",
                        "target_refs": [{"type": "rma", "id": identity}],
                        "revisions": {f"rma:{identity}": apply.revision},
                    },
                )

            if correction_kind == "logistics_participant_relationship":
                replacement_kind_value = semantic["replacement_kind"]
                replacement_id_value = semantic["replacement_id"]
                _kind, event_id, _target_id, active = self._logistics.locate_participant(
                    uow.connection, identity
                )
                if active != "1":
                    raise SomaError(
                        "CORRECTION_TARGET_INVALID",
                        "Logistics participant is not active",
                    )

                def apply(inner: UnitOfWork):
                    actual_event_id, _old_kind, replacement_participant_id = (
                        self._logistics.correct_logistics_participant(
                            inner.connection,
                            participant_id=identity,
                            replacement_kind=(
                                None
                                if replacement_kind_value is None
                                else str(replacement_kind_value)
                            ),
                            replacement_id=(
                                None
                                if replacement_id_value is None
                                else str(replacement_id_value)
                            ),
                            reason_code=reason,
                            command_id=command_id,
                        )
                    )
                    apply.event_id = actual_event_id
                    apply.replacement_id = replacement_participant_id
                    refs = [AuditResultRef("logistics_participant", identity)]
                    if replacement_participant_id is not None:
                        refs.append(
                            AuditResultRef(
                                "logistics_participant", replacement_participant_id
                            )
                        )
                    owner = AuditEventInput(
                        audit_event_id=new_uuid4(),
                        action_type="inventory.logistics.recorded_or_corrected",
                        action_version=1,
                        actor_kind=actor_kind,
                        actor_id=actor_id,
                        target_type="logistics_event",
                        target_id=actual_event_id,
                        command_id=command_id,
                        reason_category=reason,
                        payload_schema="LogisticsAuditV1",
                        payload_version=1,
                        payload={
                            "logistics_event_id": actual_event_id,
                            "event_kind": "correction",
                            "effective_at_utc": None,
                            "participant_count": 1
                            + int(replacement_participant_id is not None),
                            "corrected_participant_id": identity,
                            "resulting_revision": 1,
                        },
                        resulting_event_refs=tuple(refs),
                    )
                    result_relationship = (
                        identity
                        if replacement_participant_id is None
                        else replacement_participant_id
                    )
                    generic = self._correction_generic_audit(
                        command_id=command_id,
                        actor_kind=actor_kind,
                        actor_id=actor_id,
                        correction_kind=correction_kind,
                        target_id=identity,
                        target_event_id=None,
                        reason=reason,
                        result_kind="inventory_relationship",
                        result_id=result_relationship,
                    )
                    return (owner, generic)

                apply.event_id = event_id
                apply.replacement_id = None
                return PreparedMutation(
                    no_change=False,
                    result_type="logistics_participant",
                    result_id=identity,
                    apply=apply,
                    response_schema="InventoryMutationResultV1",
                    response_factory=lambda _inner: {
                        "outcome": "APPLIED",
                        "target_refs": (
                            [{"type": "logistics_participant", "id": identity}]
                            + (
                                []
                                if apply.replacement_id is None
                                else [
                                    {
                                        "type": "logistics_participant",
                                        "id": apply.replacement_id,
                                    }
                                ]
                            )
                        ),
                        "revisions": {f"logistics_event:{apply.event_id}": 1},
                    },
                )

            if correction_kind == "false_fault_tag_submission":
                assert target_event is not None
                current_submission = self._fault_tags.latest_submission(
                    uow.connection, identity
                )
                if (
                    current_submission is None
                    or str(current_submission[1]) != target_event
                ):
                    raise SomaError(
                        "CORRECTION_TARGET_INVALID",
                        "Target is not current-effective Fault Tag submission",
                    )
                tag = self._fault_tags.current_tag(uow.connection, identity)
                if tag is None:
                    raise SomaError("INV_STALE", "Fault Tag no longer exists")
                tracking_id = str(tag[1])

                def apply(inner: UnitOfWork):
                    (
                        correction_event_id,
                        snapshot_id,
                        resulting_revision,
                        member_count,
                        _prior_snapshot_hash,
                    ) = self._fault_tags.correct_false_submission(
                        inner.connection,
                        fault_tag_id=identity,
                        submission_event_id=target_event,
                        reason_code=reason,
                        command_id=command_id,
                    )
                    apply.result_id = correction_event_id
                    apply.revision = resulting_revision
                    owner = AuditEventInput(
                        audit_event_id=new_uuid4(),
                        action_type="inventory.fault_tag.draft_changed",
                        action_version=1,
                        actor_kind=actor_kind,
                        actor_id=actor_id,
                        target_type="fault_tag",
                        target_id=identity,
                        command_id=command_id,
                        reason_category=reason,
                        payload_schema="FaultTagAuditV1",
                        payload_version=1,
                        payload={
                            "fault_tag_id": identity,
                            "tracking_id": tracking_id,
                            "event_kind": "DRAFT_UPDATE",
                            "member_count": member_count,
                            "resulting_revision": resulting_revision,
                            "reason_category": reason,
                        },
                        resulting_event_refs=(
                            AuditResultRef("fault_tag", identity),
                            AuditResultRef(
                                "fault_tag_submission_snapshot", snapshot_id
                            ),
                        ),
                    )
                    generic = self._correction_generic_audit(
                        command_id=command_id,
                        actor_kind=actor_kind,
                        actor_id=actor_id,
                        correction_kind=correction_kind,
                        target_id=identity,
                        target_event_id=target_event,
                        reason=reason,
                        result_kind="inventory_event",
                        result_id=correction_event_id,
                    )
                    return (owner, generic)

                apply.result_id = ""
                apply.revision = int(tag[10]) + 1
                return PreparedMutation(
                    no_change=False,
                    result_type="fault_tag",
                    result_id=identity,
                    apply=apply,
                    response_schema="InventoryMutationResultV1",
                    response_factory=lambda _inner: {
                        "outcome": "APPLIED",
                        "target_refs": [{"type": "fault_tag", "id": identity}],
                        "revisions": {f"fault_tag:{identity}": apply.revision},
                    },
                )

            assert correction_kind == "physical_consequence"
            assert target_event is not None
            current = self._projections.current_physical_consequence(
                uow.connection, identity
            )
            expected = int(semantic["expected_revision"])
            if (
                current is None
                or int(current[10]) != expected
                or str(current[12]) != target_event
            ):
                raise SomaError("INV_STALE", "Physical consequence changed")
            task_id = str(current[1])
            fingerprint = str(semantic["task_review_fingerprint"])
            if self._task_evidence.review_fingerprint(uow, task_id) != fingerprint:
                raise SomaError("INV_STALE", "Task review fingerprint changed")
            if uow.connection.execute(
                "SELECT 1 FROM fault_tag_membership_submission_snapshots s "
                "JOIN fault_tag_memberships m "
                "ON m.fault_tag_membership_id=s.fault_tag_membership_id "
                "WHERE m.physical_consequence_id=? LIMIT 1",
                (identity,),
            ).fetchone() is not None:
                raise SomaError(
                    "REPLACEMENT_LINEAGE_CONFLICT",
                    "Submitted Fault Tag history requires replacement lineage",
                )
            disposition = str(semantic["physical_disposition"])
            installed = semantic["installed_spare_part_unit_id"]
            removed = semantic["removed_device_part_unit_id"]
            inbound = semantic["inbound_spare_part_unit_id"]
            parent = semantic["parent_dismantled_unit_id"]
            effective = semantic["effective_at_utc"]
            selection = validate_consequence_shape(
                disposition=disposition,
                installed_spare_part_unit_id=(
                    None if installed is None else str(installed)
                ),
                removed_device_part_unit_id=(
                    None if removed is None else str(removed)
                ),
                inbound_spare_part_unit_id=(
                    None if inbound is None else str(inbound)
                ),
                parent_dismantled_unit_id=(
                    None if parent is None else str(parent)
                ),
            )
            rma_id = None if current[3] is None else str(current[3])

            def apply(inner: UnitOfWork):
                result = self._projections.correct_physical_consequence(
                    inner.connection,
                    physical_consequence_id=identity,
                    expected_revision=expected,
                    expected_event_id=target_event,
                    task_review_fingerprint=fingerprint,
                    disposition=disposition,
                    installed_spare_part_unit_id=(
                        None if installed is None else str(installed)
                    ),
                    removed_device_part_unit_id=(
                        None if removed is None else str(removed)
                    ),
                    inbound_spare_part_unit_id=(
                        None if inbound is None else str(inbound)
                    ),
                    parent_dismantled_unit_id=(
                        None if parent is None else str(parent)
                    ),
                    effective_at_utc=(
                        None if effective is None else int(effective)
                    ),
                    selection=selection,
                    reason_code=reason,
                    command_id=command_id,
                )
                apply.result = result
                refs = [AuditResultRef("inventory_physical_consequence", identity)]
                if rma_id is not None and result["obligation_revision"] is not None:
                    refs.append(AuditResultRef("rma_return_obligation", rma_id))
                owner = AuditEventInput(
                    audit_event_id=new_uuid4(),
                    action_type="inventory.task_physical_consequence.accepted_or_corrected",
                    action_version=1,
                    actor_kind=actor_kind,
                    actor_id=actor_id,
                    target_type="task",
                    target_id=task_id,
                    command_id=command_id,
                    reason_category=reason,
                    payload_schema="PhysicalConsequenceAuditV1",
                    payload_version=1,
                    payload={
                        "physical_consequence_id": identity,
                        "task_id": task_id,
                        "task_review_fingerprint": fingerprint,
                        "event_kind": "CORRECT",
                        "disposition": disposition,
                        "return_obligation_id": (
                            rma_id
                            if result["obligation_revision"] is not None
                            else None
                        ),
                        "resulting_revision": int(result["consequence_revision"]),
                    },
                    resulting_event_refs=tuple(refs),
                )
                generic = self._correction_generic_audit(
                    command_id=command_id,
                    actor_kind=actor_kind,
                    actor_id=actor_id,
                    correction_kind=correction_kind,
                    target_id=identity,
                    target_event_id=target_event,
                    reason=reason,
                    result_kind="inventory_event",
                    result_id=str(result["consequence_event_id"]),
                )
                return (owner, generic)

            apply.result = {
                "consequence_revision": expected + 1,
                "obligation_revision": None,
            }
            return PreparedMutation(
                no_change=False,
                result_type="inventory_physical_consequence",
                result_id=identity,
                apply=apply,
                response_schema="InventoryMutationResultV1",
                response_factory=lambda _inner: {
                    "outcome": "APPLIED",
                    "target_refs": (
                        [{"type": "inventory_physical_consequence", "id": identity}]
                        + (
                            []
                            if rma_id is None
                            or apply.result["obligation_revision"] is None
                            else [{"type": "rma_return_obligation", "id": rma_id}]
                        )
                    ),
                    "revisions": {
                        f"inventory_physical_consequence:{identity}": int(
                            apply.result["consequence_revision"]
                        ),
                        **(
                            {}
                            if rma_id is None
                            or apply.result["obligation_revision"] is None
                            else {
                                f"rma_return_obligation:{rma_id}": int(
                                    apply.result["obligation_revision"]
                                )
                            }
                        ),
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
