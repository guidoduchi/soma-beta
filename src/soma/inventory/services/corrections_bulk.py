from __future__ import annotations

from soma.foundation.application.command_boundary import (
    CommandBoundary,
    CommandEnvelope,
    PreparedMutation,
)
from soma.foundation.audit.writer import AuditEventInput, AuditResultRef, AuditWriter
from soma.foundation.errors import IntegrityFailure, SomaError, ValidationError
from soma.foundation.identifiers import new_uuid4, require_uuid4, utc_epoch_seconds
from soma.foundation.persistence.connections import ConnectionFactory
from soma.foundation.persistence.uow import UnitOfWork
from soma.foundation.strict_json import loads_canonical_json
from soma.objectives_tasks.queries.tasks import TaskOperationalEvidenceReader

from ..audit_registry import build_inventory_audit_registry
from ..contracts.inventory import (
    InventoryMutationResult,
    inventory_mutation_result_from_execution,
)
from ..domain.consequences import PhysicalConsequenceIntent
from ..domain.fault_tags import WarehouseMembershipTarget, validate_warehouse_targets
from ..domain.needs import validate_reason_code
from ..domain.rmas import validate_c10
from ..queries.previews import InventoryBulkPreviewTarget, InventoryPreviewsQueryService
from ..repositories.fault_tags import InventoryFaultTagsRepository
from ..repositories.logistics import InventoryLogisticsRepository
from ..repositories.projections import InventoryPhysicalConsequenceRepository
from ..repositories.requests import InventoryRequestsRepository
from ..repositories.rmas import InventoryRmasRepository


class InventoryCorrectionsBulkService:
    def __init__(self, connection_factory: ConnectionFactory) -> None:
        self._factory = connection_factory
        self._fault_tags = InventoryFaultTagsRepository()
        self._logistics = InventoryLogisticsRepository()
        self._consequences = InventoryPhysicalConsequenceRepository()
        self._requests = InventoryRequestsRepository()
        self._rmas = InventoryRmasRepository()
        self._boundary = CommandBoundary(
            connection_factory,
            AuditWriter(build_inventory_audit_registry()),
        )

    @staticmethod
    def _sha256(value: str, *, field: str) -> str:
        if (
            not isinstance(value, str)
            or len(value) != 64
            or any(character not in "0123456789abcdef" for character in value)
        ):
            raise ValidationError(f"{field} must be lowercase SHA-256")
        return value

    @staticmethod
    def _response(
        refs: list[tuple[str, str]],
        revisions: dict[str, int],
    ) -> dict[str, object]:
        return {
            "outcome": "APPLIED",
            "target_refs": [
                {"type": result_type, "id": result_id}
                for result_type, result_id in refs
            ],
            "revisions": dict(revisions),
        }

    @staticmethod
    def _proposal_row(connection, proposal_id: str):
        return connection.execute(
            "SELECT inventory_proposal_id,proposal_kind,evidence_kind,evidence_id,"
            "source_proposal_key,state,input_fingerprint,risk_tier,created_at_utc,"
            "revision,last_command_id FROM inventory_proposals "
            "WHERE inventory_proposal_id=?",
            (proposal_id,),
        ).fetchone()

    @staticmethod
    def _proposal_targets(connection, proposal_id: str) -> list[dict[str, object]]:
        rows = connection.execute(
            "SELECT inventory_proposal_target_id,target_kind,spare_request_id,rma_id,"
            "spare_part_unit_id,fault_tag_id,fault_tag_membership_id,expected_revision,"
            "proposed_action,payload_json FROM inventory_proposal_targets "
            "WHERE inventory_proposal_id=? "
            "ORDER BY inventory_proposal_target_id",
            (proposal_id,),
        ).fetchall()
        return [
            {
                "inventory_proposal_target_id": str(row[0]),
                "target_kind": str(row[1]),
                "spare_request_id": None if row[2] is None else str(row[2]),
                "rma_id": None if row[3] is None else str(row[3]),
                "spare_part_unit_id": None if row[4] is None else str(row[4]),
                "fault_tag_id": None if row[5] is None else str(row[5]),
                "fault_tag_membership_id": None if row[6] is None else str(row[6]),
                "expected_revision": int(row[7]),
                "proposed_action": str(row[8]),
                "payload_json": str(row[9]),
            }
            for row in rows
        ]

    @staticmethod
    def _parse_proposal_target(
        *,
        proposal_kind: str,
        risk_tier: str,
        target: dict[str, object],
        explicit_confirmation: bool,
    ) -> dict[str, object]:
        if target["target_kind"] != "fault_tag_membership":
            raise SomaError(
                "DEPENDENCY_INDETERMINATE",
                "Inventory proposal target kind is not supported in Beta 1.0",
            )
        membership_id = target["fault_tag_membership_id"]
        if not isinstance(membership_id, str):
            raise SomaError(
                "DEPENDENCY_INDETERMINATE",
                "Inventory proposal target lacks Fault Tag membership identity",
            )
        payload = loads_canonical_json(
            str(target["payload_json"]),
            max_bytes=16_384,
            max_depth=4,
            max_collection_items=16,
        )
        if not isinstance(payload, dict) or payload.get("schema") != "INVENTORY_PROPOSAL_TARGET_V1":
            raise SomaError(
                "DEPENDENCY_INDETERMINATE",
                "Inventory proposal target payload schema is unsupported",
            )
        action = str(target["proposed_action"])
        if proposal_kind == "warehouse_received" and action == "warehouse_received":
            if set(payload) != {"schema", "effective_at_utc"}:
                raise SomaError(
                    "DEPENDENCY_INDETERMINATE",
                    "warehouse_received proposal payload is not closed",
                )
            effective = payload["effective_at_utc"]
            if effective is not None and (type(effective) is not int or effective < 0):
                raise SomaError(
                    "DEPENDENCY_INDETERMINATE",
                    "warehouse_received proposal effective time is invalid",
                )
            if risk_tier not in {"normal", "high"}:
                raise SomaError(
                    "DEPENDENCY_INDETERMINATE",
                    "warehouse_received proposal risk tier is invalid",
                )
            return {
                "owner_action": "warehouse_received",
                "membership_id": membership_id,
                "expected_revision": int(target["expected_revision"]),
                "effective_at_utc": effective,
                "decision": None,
                "reason_code": None,
            }
        if (
            proposal_kind == "warehouse_final_decision"
            and action == "warehouse_final_decision"
        ):
            if set(payload) != {
                "schema",
                "decision",
                "reason_code",
                "effective_at_utc",
            }:
                raise SomaError(
                    "DEPENDENCY_INDETERMINATE",
                    "warehouse final proposal payload is not closed",
                )
            if risk_tier != "material_final":
                raise SomaError(
                    "DEPENDENCY_INDETERMINATE",
                    "warehouse final proposal must be material_final",
                )
            if explicit_confirmation is not True:
                raise SomaError(
                    "WAREHOUSE_FINAL_CONFIRMATION_REQUIRED",
                    "Warehouse final proposal requires explicit operator confirmation",
                )
            decision = payload["decision"]
            if decision not in {"accepted", "rejected"}:
                raise SomaError(
                    "DEPENDENCY_INDETERMINATE",
                    "warehouse final proposal decision is invalid",
                )
            raw_reason = payload["reason_code"]
            if decision == "rejected":
                if not isinstance(raw_reason, str):
                    raise SomaError(
                        "DEPENDENCY_INDETERMINATE",
                        "warehouse rejection proposal requires reason_code",
                    )
                reason = validate_reason_code(raw_reason)
            else:
                if raw_reason is not None:
                    raise SomaError(
                        "DEPENDENCY_INDETERMINATE",
                        "warehouse acceptance proposal cannot carry rejection reason",
                    )
                reason = None
            effective = payload["effective_at_utc"]
            if effective is not None and (type(effective) is not int or effective < 0):
                raise SomaError(
                    "DEPENDENCY_INDETERMINATE",
                    "warehouse final proposal effective time is invalid",
                )
            return {
                "owner_action": "warehouse_final_decision",
                "membership_id": membership_id,
                "expected_revision": int(target["expected_revision"]),
                "effective_at_utc": effective,
                "decision": decision,
                "reason_code": reason,
            }
        raise SomaError(
            "DEPENDENCY_INDETERMINATE",
            "Inventory proposal action is not supported in Beta 1.0",
        )

    def accept_inventory_proposal(
        self,
        *,
        command_id: str,
        proposal_id: str,
        revision: int,
        input_fingerprint: str,
        selected_target_ids: tuple[str, ...] | None = None,
        explicit_confirmation: bool = False,
        actor_kind: str = "local_user",
        actor_id: str | None = None,
    ) -> InventoryMutationResult:
        identity = require_uuid4(proposal_id)
        if type(revision) is not int or revision <= 0:
            raise ValidationError("proposal revision must be positive")
        fingerprint = self._sha256(input_fingerprint, field="input_fingerprint")
        if selected_target_ids is not None:
            if not isinstance(selected_target_ids, tuple):
                raise ValidationError("selected_target_ids must be tuple or null")
            selected = tuple(sorted(require_uuid4(value) for value in selected_target_ids))
            if len(set(selected)) != len(selected):
                raise ValidationError("selected_target_ids contains duplicates")
        else:
            selected = None
        if type(explicit_confirmation) is not bool:
            raise ValidationError("explicit_confirmation must be boolean")

        envelope = CommandEnvelope(
            command_id=command_id,
            command_type="AcceptInventoryProposal",
            target_type="inventory_proposal",
            target_id=identity,
            semantic_payload={
                "selected_target_ids": None if selected is None else list(selected),
                "explicit_confirmation": explicit_confirmation,
            },
            base_revisions={"inventory_proposal": revision},
            authorizing_fingerprints={"proposal": fingerprint},
        )

        def prepare(uow: UnitOfWork) -> PreparedMutation:
            proposal = self._proposal_row(uow.connection, identity)
            if proposal is None:
                raise SomaError("PROPOSAL_STALE", "Inventory proposal no longer exists")
            if str(proposal[5]) != "pending":
                raise SomaError("PROPOSAL_STALE", "Inventory proposal is no longer pending")
            if int(proposal[9]) != revision or str(proposal[6]) != fingerprint:
                raise SomaError("PROPOSAL_STALE", "Inventory proposal revision/fingerprint changed")
            targets = self._proposal_targets(uow.connection, identity)
            if not targets:
                raise SomaError(
                    "DEPENDENCY_INDETERMINATE",
                    "Inventory proposal has no persisted targets",
                )
            all_target_ids = tuple(
                sorted(str(item["inventory_proposal_target_id"]) for item in targets)
            )
            if selected is not None and selected != all_target_ids:
                raise SomaError(
                    "DEPENDENCY_INDETERMINATE",
                    "Beta 1.0 proposal acceptance requires the complete target set",
                )
            parsed = tuple(
                self._parse_proposal_target(
                    proposal_kind=str(proposal[1]),
                    risk_tier=str(proposal[7]),
                    target=target,
                    explicit_confirmation=explicit_confirmation,
                )
                for target in targets
            )
            owner_keys = [
                (str(item["owner_action"]), str(item["membership_id"]))
                for item in parsed
            ]
            if len(set(owner_keys)) != len(owner_keys):
                raise SomaError(
                    "DEPENDENCY_INDETERMINATE",
                    "Inventory proposal contains duplicate owner targets",
                )
            for item in parsed:
                expected_state = (
                    "submitted_awaiting_receipt"
                    if item["owner_action"] == "warehouse_received"
                    else "warehouse_received"
                )
                try:
                    self._fault_tags._require_warehouse_member(
                        uow.connection,
                        membership_id=str(item["membership_id"]),
                        expected_revision=int(item["expected_revision"]),
                        expected_state=expected_state,
                    )
                except SomaError as exc:
                    if exc.code in {
                        "INV_STALE",
                        "BULK_INCOMPATIBLE",
                        "WAREHOUSE_RECEIPT_REQUIRED",
                        "RETURN_SELECTION_INVALID",
                    }:
                        raise SomaError(
                            "PROPOSAL_STALE",
                            "Inventory proposal target no longer matches owner state",
                        ) from exc
                    raise

            batch_id = new_uuid4()
            source_ref = f"{proposal[2]}:{proposal[3]}"

            def apply(inner: UnitOfWork):
                current = self._proposal_row(inner.connection, identity)
                if (
                    current is None
                    or str(current[5]) != "pending"
                    or int(current[9]) != revision
                    or str(current[6]) != fingerprint
                ):
                    raise SomaError("PROPOSAL_STALE", "Inventory proposal changed before commit")
                current_targets = self._proposal_targets(inner.connection, identity)
                if tuple(
                    sorted(str(item["inventory_proposal_target_id"]) for item in current_targets)
                ) != all_target_ids:
                    raise SomaError("PROPOSAL_STALE", "Inventory proposal target set changed")

                inner.connection.execute(
                    "INSERT INTO inventory_lifecycle_batches("
                    "inventory_batch_id,batch_kind,target_count,recorded_at_utc,command_id"
                    ") VALUES (?,'proposal_acceptance',?,?,?)",
                    (batch_id, len(parsed), utc_epoch_seconds(), command_id),
                )
                events: list[dict[str, object]] = []
                tag_revisions: dict[str, int] = {}
                owner_audits: list[AuditEventInput] = []
                revisions: dict[str, int] = {}
                refs: list[tuple[str, str]] = [("inventory_batch", batch_id)]

                for item in parsed:
                    membership_id = str(item["membership_id"])
                    expected_revision = int(item["expected_revision"])
                    if item["owner_action"] == "warehouse_received":
                        result = self._fault_tags.record_warehouse_receipt(
                            inner.connection,
                            targets=((membership_id, expected_revision),),
                            effective_at_utc=item["effective_at_utc"],
                            evidence_kind=str(proposal[2]),
                            evidence_id=str(proposal[3]),
                            command_id=command_id,
                        )
                        audit_kind = "RECEIVED"
                        confirmation = False
                    else:
                        result = self._fault_tags.record_warehouse_final_decision(
                            inner.connection,
                            targets=((membership_id, expected_revision),),
                            decision=str(item["decision"]),
                            reason_code=item["reason_code"],
                            effective_at_utc=item["effective_at_utc"],
                            evidence_kind=str(proposal[2]),
                            evidence_id=str(proposal[3]),
                            command_id=command_id,
                        )
                        audit_kind = (
                            "ACCEPTED"
                            if item["decision"] == "accepted"
                            else "REJECTED"
                        )
                        confirmation = True
                    event = result["events"][0]
                    events.append(event)
                    tag_revisions.update(
                        {
                            str(tag_id): int(value)
                            for tag_id, value in result["tag_revisions"].items()
                        }
                    )
                    refs.append(
                        (
                            "fault_tag_membership_event",
                            str(event["membership_event_id"]),
                        )
                    )
                    if item["owner_action"] == "warehouse_final_decision":
                        refs.append(("rma_return_obligation", str(event["rma_id"])))
                        revisions[
                            f"rma_return_obligation:{event['rma_id']}"
                        ] = int(event["obligation_revision"])
                    revisions[
                        f"fault_tag_membership:{event['membership_id']}"
                    ] = int(event["membership_revision"])
                    revisions[f"rma:{event['rma_id']}"] = int(event["rma_revision"])
                    owner_audits.append(
                        AuditEventInput(
                            audit_event_id=new_uuid4(),
                            action_type="inventory.fault_tag.warehouse_state_changed",
                            action_version=1,
                            actor_kind=actor_kind,
                            actor_id=actor_id,
                            target_type="fault_tag_membership",
                            target_id=str(event["membership_id"]),
                            command_id=command_id,
                            reason_category=item["reason_code"],
                            batch_id=batch_id,
                            payload_schema="WarehouseDecisionAuditV1",
                            payload_version=1,
                            payload={
                                "membership_id": str(event["membership_id"]),
                                "event_kind": audit_kind,
                                "rma_id": str(event["rma_id"]),
                                "return_obligation_id": str(event["rma_id"]),
                                "batch_id": batch_id,
                                "effective_at_utc": item["effective_at_utc"],
                                "explicit_confirmation": confirmation,
                            },
                            resulting_event_refs=(
                                AuditResultRef(
                                    "fault_tag_membership_event",
                                    str(event["membership_event_id"]),
                                ),
                                AuditResultRef(
                                    "rma_return_obligation",
                                    str(event["rma_id"]),
                                ),
                            ),
                        )
                    )

                changed = inner.connection.execute(
                    "UPDATE inventory_proposals SET state='accepted',revision=?,last_command_id=? "
                    "WHERE inventory_proposal_id=? AND state='pending' AND revision=? "
                    "AND input_fingerprint=?",
                    (revision + 1, command_id, identity, revision, fingerprint),
                )
                if changed.rowcount != 1:
                    raise SomaError("PROPOSAL_STALE", "Inventory proposal changed during acceptance")
                inner.connection.execute(
                    "DELETE FROM inventory_attention_projection "
                    "WHERE target_kind='inventory_proposal' AND target_id=? "
                    "AND attention_kind='proposal_review_required'",
                    (identity,),
                )
                revisions[f"inventory_proposal:{identity}"] = revision + 1
                revisions.update(
                    {
                        f"fault_tag:{tag_id}": value
                        for tag_id, value in tag_revisions.items()
                    }
                )
                apply.refs = refs
                apply.revisions = revisions
                proposal_audit = AuditEventInput(
                    audit_event_id=new_uuid4(),
                    action_type="inventory.proposal.decided",
                    action_version=1,
                    actor_kind=actor_kind,
                    actor_id=actor_id,
                    target_type="inventory_proposal",
                    target_id=identity,
                    command_id=command_id,
                    batch_id=batch_id,
                    payload_schema="InventoryProposalAuditV1",
                    payload_version=1,
                    payload={
                        "proposal_id": identity,
                        "decision": "ACCEPT",
                        "input_fingerprint": fingerprint,
                        "accepted_target_count": len(parsed),
                        "deferred_or_rejected_count": 0,
                        "source_evidence_ref": source_ref,
                        "reason_category": None,
                    },
                    resulting_event_refs=tuple(
                        AuditResultRef(
                            "fault_tag_membership_event",
                            str(item["membership_event_id"]),
                        )
                        for item in events
                    ),
                )
                return (*owner_audits, proposal_audit)

            apply.refs = []
            apply.revisions = {}
            return PreparedMutation(
                no_change=False,
                result_type="inventory_batch",
                result_id=batch_id,
                apply=apply,
                response_schema="InventoryMutationResultV1",
                response_factory=lambda _inner: self._response(
                    list(apply.refs),
                    dict(apply.revisions),
                ),
            )

        return inventory_mutation_result_from_execution(
            self._boundary.execute(envelope, prepare)
        )

    def reject_inventory_proposal(
        self,
        *,
        command_id: str,
        proposal_id: str,
        revision: int,
        reason_code: str,
        actor_kind: str = "local_user",
        actor_id: str | None = None,
    ) -> InventoryMutationResult:
        identity = require_uuid4(proposal_id)
        if type(revision) is not int or revision <= 0:
            raise ValidationError("proposal revision must be positive")
        reason = validate_reason_code(reason_code)
        envelope = CommandEnvelope(
            command_id=command_id,
            command_type="RejectInventoryProposal",
            target_type="inventory_proposal",
            target_id=identity,
            semantic_payload={"reason_code": reason},
            base_revisions={"inventory_proposal": revision},
        )

        def prepare(uow: UnitOfWork) -> PreparedMutation:
            proposal = self._proposal_row(uow.connection, identity)
            if proposal is None or str(proposal[5]) != "pending" or int(proposal[9]) != revision:
                raise SomaError("PROPOSAL_STALE", "Inventory proposal is not exact pending authority")
            target_count = len(self._proposal_targets(uow.connection, identity))
            source_ref = f"{proposal[2]}:{proposal[3]}"
            fingerprint = str(proposal[6])

            def apply(inner: UnitOfWork):
                changed = inner.connection.execute(
                    "UPDATE inventory_proposals SET state='rejected',revision=?,last_command_id=? "
                    "WHERE inventory_proposal_id=? AND state='pending' AND revision=? "
                    "AND input_fingerprint=?",
                    (revision + 1, command_id, identity, revision, fingerprint),
                )
                if changed.rowcount != 1:
                    raise SomaError("PROPOSAL_STALE", "Inventory proposal changed during rejection")
                inner.connection.execute(
                    "DELETE FROM inventory_attention_projection "
                    "WHERE target_kind='inventory_proposal' AND target_id=? "
                    "AND attention_kind='proposal_review_required'",
                    (identity,),
                )
                return AuditEventInput(
                    audit_event_id=new_uuid4(),
                    action_type="inventory.proposal.decided",
                    action_version=1,
                    actor_kind=actor_kind,
                    actor_id=actor_id,
                    target_type="inventory_proposal",
                    target_id=identity,
                    command_id=command_id,
                    reason_category=reason,
                    payload_schema="InventoryProposalAuditV1",
                    payload_version=1,
                    payload={
                        "proposal_id": identity,
                        "decision": "REJECT",
                        "input_fingerprint": fingerprint,
                        "accepted_target_count": 0,
                        "deferred_or_rejected_count": target_count,
                        "source_evidence_ref": source_ref,
                        "reason_category": reason,
                    },
                )

            return PreparedMutation(
                no_change=False,
                result_type="inventory_proposal",
                result_id=identity,
                apply=apply,
                response_schema="InventoryMutationResultV1",
                response=self._response(
                    [("inventory_proposal", identity)],
                    {f"inventory_proposal:{identity}": revision + 1},
                ),
            )

        return inventory_mutation_result_from_execution(
            self._boundary.execute(envelope, prepare)
        )

    def accept_inventory_bulk_action(
        self,
        *,
        command_id: str,
        action_kind: str,
        targets: tuple[WarehouseMembershipTarget, ...],
        preview_fingerprint: str,
        effective_at_utc: int | None = None,
        reason_code: str | None = None,
        explicit_confirmation: bool = False,
        actor_kind: str = "local_user",
        actor_id: str | None = None,
    ) -> InventoryMutationResult:
        accepted_targets = validate_warehouse_targets(targets)
        fingerprint = self._sha256(
            preview_fingerprint,
            field="preview_fingerprint",
        )
        if action_kind not in {
            "warehouse_receipt",
            "warehouse_accept",
            "warehouse_reject",
        }:
            raise ValidationError("Inventory bulk action kind is invalid")
        if effective_at_utc is not None and (
            type(effective_at_utc) is not int or effective_at_utc < 0
        ):
            raise ValidationError("effective_at_utc must be nonnegative or null")
        if action_kind == "warehouse_reject":
            if reason_code is None:
                raise ValidationError("warehouse_reject requires reason_code")
            reason = validate_reason_code(reason_code)
        else:
            if reason_code is not None:
                raise ValidationError("reason_code is accepted only for warehouse_reject")
            reason = None
        if action_kind in {"warehouse_accept", "warehouse_reject"}:
            if explicit_confirmation is not True:
                raise SomaError(
                    "WAREHOUSE_FINAL_CONFIRMATION_REQUIRED",
                    "Warehouse final bulk decision requires explicit operator confirmation",
                )
        elif type(explicit_confirmation) is not bool:
            raise ValidationError("explicit_confirmation must be boolean")

        preview_targets = tuple(
            InventoryBulkPreviewTarget(
                item.fault_tag_membership_id,
                item.revision,
            )
            for item in accepted_targets
        )
        envelope = CommandEnvelope(
            command_id=command_id,
            command_type="AcceptInventoryBulkAction",
            target_type="inventory_batch",
            target_id=None,
            semantic_payload={
                "action_kind": action_kind,
                "targets": [
                    {
                        "fault_tag_membership_id": item.fault_tag_membership_id,
                        "expected_revision": item.revision,
                    }
                    for item in accepted_targets
                ],
                "effective_at_utc": effective_at_utc,
                "reason_code": reason,
                "explicit_confirmation": explicit_confirmation,
            },
            authorizing_fingerprints={"preview": fingerprint},
        )

        def prepare(uow: UnitOfWork) -> PreparedMutation:
            preview = InventoryPreviewsQueryService._bulk_preview(
                uow.connection,
                action_kind=action_kind,
                targets=preview_targets,
                effective_at_utc=effective_at_utc,
                reason_code=reason,
                explicit_confirmation=explicit_confirmation,
            )
            if str(preview["input_fingerprint"]) != fingerprint:
                raise SomaError("INV_STALE", "Inventory bulk preview changed")
            if int(preview["eligible_count"]) != len(accepted_targets):
                raise SomaError(
                    "BULK_INCOMPATIBLE",
                    "Reviewed Inventory bulk scope is no longer fully eligible",
                )
            target_pairs = tuple(
                (item.fault_tag_membership_id, item.revision)
                for item in accepted_targets
            )
            batch_id = new_uuid4()

            def apply(inner: UnitOfWork):
                # Recompute again immediately before owner mutation so the material
                # fingerprint covers the same writer transaction.
                current = InventoryPreviewsQueryService._bulk_preview(
                    inner.connection,
                    action_kind=action_kind,
                    targets=preview_targets,
                    effective_at_utc=effective_at_utc,
                    reason_code=reason,
                    explicit_confirmation=explicit_confirmation,
                )
                if str(current["input_fingerprint"]) != fingerprint:
                    raise SomaError("INV_STALE", "Inventory bulk preview changed")
                if int(current["eligible_count"]) != len(accepted_targets):
                    raise SomaError(
                        "BULK_INCOMPATIBLE",
                        "Inventory bulk target became incompatible",
                    )

                if action_kind == "warehouse_receipt":
                    result = self._fault_tags.record_warehouse_receipt(
                        inner.connection,
                        targets=target_pairs,
                        effective_at_utc=effective_at_utc,
                        evidence_kind=None,
                        evidence_id=None,
                        command_id=command_id,
                        force_batch=True,
                        requested_batch_id=batch_id,
                    )
                    audit_kind = "RECEIVED"
                    final_confirmation = False
                else:
                    decision = (
                        "accepted"
                        if action_kind == "warehouse_accept"
                        else "rejected"
                    )
                    result = self._fault_tags.record_warehouse_final_decision(
                        inner.connection,
                        targets=target_pairs,
                        decision=decision,
                        reason_code=reason,
                        effective_at_utc=effective_at_utc,
                        evidence_kind=None,
                        evidence_id=None,
                        command_id=command_id,
                        force_batch=True,
                        requested_batch_id=batch_id,
                    )
                    audit_kind = (
                        "ACCEPTED"
                        if action_kind == "warehouse_accept"
                        else "REJECTED"
                    )
                    final_confirmation = True

                actual_batch = result["batch_id"]
                if actual_batch is None:
                    raise IntegrityFailure("Bulk owner failed to allocate lifecycle batch")
                apply.result = result
                apply.batch_id = str(actual_batch)

                per_target_audits = tuple(
                    AuditEventInput(
                        audit_event_id=new_uuid4(),
                        action_type="inventory.fault_tag.warehouse_state_changed",
                        action_version=1,
                        actor_kind=actor_kind,
                        actor_id=actor_id,
                        target_type="fault_tag_membership",
                        target_id=str(item["membership_id"]),
                        command_id=command_id,
                        reason_category=reason,
                        batch_id=str(actual_batch),
                        payload_schema="WarehouseDecisionAuditV1",
                        payload_version=1,
                        payload={
                            "membership_id": str(item["membership_id"]),
                            "event_kind": audit_kind,
                            "rma_id": str(item["rma_id"]),
                            "return_obligation_id": str(item["rma_id"]),
                            "batch_id": str(actual_batch),
                            "effective_at_utc": effective_at_utc,
                            "explicit_confirmation": final_confirmation,
                        },
                        resulting_event_refs=(
                            AuditResultRef(
                                "fault_tag_membership_event",
                                str(item["membership_event_id"]),
                            ),
                            AuditResultRef(
                                "rma_return_obligation",
                                str(item["rma_id"]),
                            ),
                        ),
                    )
                    for item in result["events"]
                )

                result_refs = [
                    {
                        "type": "fault_tag_membership_event",
                        "id": str(item["membership_event_id"]),
                    }
                    for item in result["events"]
                ]
                bulk_audit = AuditEventInput(
                    audit_event_id=new_uuid4(),
                    action_type="inventory.bulk.accepted",
                    action_version=1,
                    actor_kind=actor_kind,
                    actor_id=actor_id,
                    target_type="inventory_batch",
                    target_id=str(actual_batch),
                    command_id=command_id,
                    batch_id=str(actual_batch),
                    payload_schema="InventoryBulkAuditV1",
                    payload_version=1,
                    payload={
                        "batch_id": str(actual_batch),
                        "action_kind": action_kind,
                        "input_fingerprint": fingerprint,
                        "target_count": len(result["events"]),
                        "result_refs": result_refs,
                        "result": "APPLIED",
                    },
                    resulting_event_refs=tuple(
                        AuditResultRef(
                            "fault_tag_membership_event",
                            str(item["membership_event_id"]),
                        )
                        for item in result["events"]
                    ),
                )
                return (*per_target_audits, bulk_audit)

            apply.result = {}
            apply.batch_id = batch_id
            return PreparedMutation(
                no_change=False,
                result_type="inventory_batch",
                result_id=batch_id,
                apply=apply,
                response_schema="InventoryMutationResultV1",
                response_factory=lambda _inner: self._response(
                    [
                        ("inventory_batch", apply.batch_id),
                        *[
                            (
                                "fault_tag_membership_event",
                                str(item["membership_event_id"]),
                            )
                            for item in apply.result["events"]
                        ],
                        *(
                            []
                            if action_kind == "warehouse_receipt"
                            else [
                                ("rma_return_obligation", str(item["rma_id"]))
                                for item in apply.result["events"]
                            ]
                        ),
                    ],
                    {
                        **{
                            f"fault_tag_membership:{item['membership_id']}": int(
                                item["membership_revision"]
                            )
                            for item in apply.result["events"]
                        },
                        **{
                            f"fault_tag:{tag_id}": int(revision)
                            for tag_id, revision in apply.result["tag_revisions"].items()
                        },
                        **{
                            f"rma:{item['rma_id']}": int(item["rma_revision"])
                            for item in apply.result["events"]
                        },
                        **(
                            {}
                            if action_kind == "warehouse_receipt"
                            else {
                                f"rma_return_obligation:{item['rma_id']}": int(
                                    item["obligation_revision"]
                                )
                                for item in apply.result["events"]
                            }
                        ),
                    },
                ),
            )

        return inventory_mutation_result_from_execution(
            self._boundary.execute(envelope, prepare)
        )

    def correct_inventory_evidence(
        self,
        *,
        command_id: str,
        correction_kind: str,
        target_id: str,
        reason_code: str,
        target_event_id: str | None = None,
        expected_revision: int | None = None,
        confirmed_no_real_send: bool | None = None,
        current_c10: str | None = None,
        new_c10: str | None = None,
        replacement_kind: str | None = None,
        replacement_id: str | None = None,
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
        supported = {
            "false_spare_request_submission",
            "rma_identifier_alias",
            "logistics_participant_relationship",
            "false_fault_tag_submission",
            "physical_consequence",
            "submitted_fault_tag_material",
            "genuine_later_development",
        }
        if correction_kind not in supported:
            raise ValidationError("correction_kind is invalid")
        identity = require_uuid4(target_id)
        reason = validate_reason_code(reason_code)

        if correction_kind == "submitted_fault_tag_material":
            raise SomaError(
                "REPLACEMENT_LINEAGE_CONFLICT",
                "Submitted Fault Tag material changes require replacement workflow",
            )
        if correction_kind == "genuine_later_development":
            raise SomaError(
                "CORRECTION_TARGET_INVALID",
                "Genuine later development must use the normal Inventory lifecycle command",
            )

        normalized: dict[str, object] = {}
        if correction_kind in {
            "false_spare_request_submission",
            "false_fault_tag_submission",
            "physical_consequence",
        }:
            if target_event_id is None:
                raise ValidationError("target_event_id is required for this correction")
            normalized["target_event_id"] = require_uuid4(target_event_id)

        if correction_kind == "false_spare_request_submission":
            if type(expected_revision) is not int or expected_revision <= 0:
                raise ValidationError("expected_revision is required and must be positive")
            if confirmed_no_real_send is not True:
                raise ValidationError("confirmed_no_real_send must be true")
            normalized["expected_revision"] = expected_revision
            normalized["confirmed_no_real_send"] = True
        elif correction_kind == "rma_identifier_alias":
            if current_c10 is None or new_c10 is None:
                raise ValidationError("current_c10 and new_c10 are required")
            current_value = validate_c10(current_c10)
            replacement_value = validate_c10(new_c10)
            if current_value == replacement_value:
                raise ValidationError("RMA identifier correction must change C10")
            normalized["current_c10"] = current_value
            normalized["new_c10"] = replacement_value
        elif correction_kind == "logistics_participant_relationship":
            if (replacement_kind is None) != (replacement_id is None):
                raise ValidationError(
                    "replacement_kind and replacement_id must both be null or both present"
                )
            if replacement_kind is not None and replacement_kind not in {
                "rma",
                "spare_part_unit",
                "device_part_unit",
            }:
                raise ValidationError("replacement_kind is invalid")
            normalized["replacement_kind"] = replacement_kind
            normalized["replacement_id"] = (
                None if replacement_id is None else require_uuid4(replacement_id)
            )
        elif correction_kind == "false_fault_tag_submission":
            if confirmed_no_real_send is not True:
                raise ValidationError("confirmed_no_real_send must be true")
            normalized["confirmed_no_real_send"] = True
        elif correction_kind == "physical_consequence":
            if type(expected_revision) is not int or expected_revision <= 0:
                raise ValidationError("expected_revision is required and must be positive")
            if task_review_fingerprint is None:
                raise ValidationError("task_review_fingerprint is required")
            review_fp = self._sha256(
                task_review_fingerprint,
                field="task_review_fingerprint",
            )
            if physical_disposition is None:
                raise ValidationError("physical_disposition is required")
            intent = PhysicalConsequenceIntent(
                physical_disposition=physical_disposition,
                installed_spare_part_unit_id=installed_spare_part_unit_id,
                removed_device_part_unit_id=removed_device_part_unit_id,
                inbound_spare_part_unit_id=inbound_spare_part_unit_id,
                parent_dismantled_unit_id=parent_dismantled_unit_id,
                effective_at_utc=effective_at_utc,
            ).validate()
            normalized["expected_revision"] = expected_revision
            normalized["task_review_fingerprint"] = review_fp
            normalized["physical_disposition"] = intent.physical_disposition
            normalized["installed_spare_part_unit_id"] = intent.installed_spare_part_unit_id
            normalized["removed_device_part_unit_id"] = intent.removed_device_part_unit_id
            normalized["inbound_spare_part_unit_id"] = intent.inbound_spare_part_unit_id
            normalized["parent_dismantled_unit_id"] = intent.parent_dismantled_unit_id
            normalized["effective_at_utc"] = intent.effective_at_utc
        envelope = CommandEnvelope(
            command_id=command_id,
            command_type="CorrectInventoryEvidence",
            target_type=(
                "inventory_relationship"
                if correction_kind == "logistics_participant_relationship"
                else "inventory_event"
            ),
            target_id=identity,
            semantic_payload={
                "correction_kind": correction_kind,
                "reason_code": reason,
                **normalized,
            },
            base_revisions=(
                {}
                if expected_revision is None
                else {"target": int(expected_revision)}
            ),
            authorizing_fingerprints=(
                {}
                if correction_kind != "physical_consequence"
                else {
                    "task_review_fingerprint": str(
                        normalized["task_review_fingerprint"]
                    )
                }
            ),
        )

        def prepare(uow: UnitOfWork) -> PreparedMutation:
            owner_context: dict[str, object] = {}
            generic_target_type = (
                "inventory_relationship"
                if correction_kind == "logistics_participant_relationship"
                else "inventory_event"
            )

            if correction_kind == "false_spare_request_submission":
                current = self._requests.current_submission(uow.connection, identity)
                if (
                    current is None
                    or int(current[6]) != int(normalized["expected_revision"])
                    or str(current[1]) != str(normalized["target_event_id"])
                ):
                    raise SomaError(
                        "CORRECTION_TARGET_INVALID",
                        "Spare Request false-submission target is not current",
                    )
                owner_context.update(
                    {
                        "snapshot_id": str(current[0]),
                        "snapshot_hash": str(current[4]),
                        "effective_at": None if current[5] is None else int(current[5]),
                    }
                )
                result_type = "spare_request"
                result_id = identity
            elif correction_kind == "rma_identifier_alias":
                row = self._rmas.current_rma(uow.connection, identity)
                if row is None or str(row[4]) != str(normalized["current_c10"]):
                    raise SomaError("INV_STALE", "RMA current C10 changed")
                alias = uow.connection.execute(
                    "SELECT alias_id FROM rma_identifier_aliases "
                    "WHERE rma_id=? AND c10=? AND alias_kind='current'",
                    (identity, str(normalized["current_c10"])),
                ).fetchone()
                if alias is None:
                    raise SomaError(
                        "CORRECTION_TARGET_INVALID",
                        "RMA current alias relationship is missing",
                    )
                if self._rmas.c10_alias_owner(
                    uow.connection,
                    str(normalized["new_c10"]),
                ) is not None:
                    raise SomaError("C10_CONFLICT", "C10 is already current or former history")
                owner_context.update(
                    {
                        "row": row,
                        "old_alias_id": str(alias[0]),
                    }
                )
                generic_target_type = "inventory_relationship"
                result_type = "rma"
                result_id = identity
            elif correction_kind == "logistics_participant_relationship":
                located = self._logistics.locate_participant(uow.connection, identity)
                if located is None or located[3] != 1:
                    raise SomaError(
                        "CORRECTION_TARGET_INVALID",
                        "Logistics participant is not current-active",
                    )
                owner_context["logistics_event_id"] = str(located[2])
                result_type = "logistics_participant"
                result_id = identity
            elif correction_kind == "false_fault_tag_submission":
                current = self._fault_tags.current_tag(uow.connection, identity)
                if current is None or current[9] is None:
                    raise SomaError(
                        "CORRECTION_TARGET_INVALID",
                        "Fault Tag has no current submission snapshot",
                    )
                snapshot = uow.connection.execute(
                    "SELECT submission_event_id,effective_submission_at_utc,snapshot_hash "
                    "FROM fault_tag_submission_snapshots "
                    "WHERE fault_tag_submission_snapshot_id=? AND fault_tag_id=?",
                    (str(current[9]), identity),
                ).fetchone()
                if (
                    snapshot is None
                    or str(snapshot[0]) != str(normalized["target_event_id"])
                ):
                    raise SomaError(
                        "CORRECTION_TARGET_INVALID",
                        "Fault Tag false-submission target is not current",
                    )
                membership_count = int(
                    uow.connection.execute(
                        "SELECT COUNT(*) FROM fault_tag_membership_submission_snapshots "
                        "WHERE fault_tag_submission_snapshot_id=?",
                        (str(current[9]),),
                    ).fetchone()[0]
                )
                owner_context.update(
                    {
                        "snapshot_id": str(current[9]),
                        "snapshot_hash": str(snapshot[2]),
                        "effective_at": None if snapshot[1] is None else int(snapshot[1]),
                        "membership_count": membership_count,
                    }
                )
                result_type = "fault_tag"
                result_id = identity
            else:
                current = self._consequences.current(uow.connection, identity)
                if (
                    current is None
                    or int(current[10]) != int(normalized["expected_revision"])
                    or str(current[12]) != str(normalized["target_event_id"])
                ):
                    raise SomaError(
                        "CORRECTION_TARGET_INVALID",
                        "Physical consequence correction target is not current",
                    )
                task_id = str(current[1])
                review_fp = TaskOperationalEvidenceReader.review_fingerprint(
                    uow.connection,
                    task_id,
                )
                if (
                    review_fp != str(normalized["task_review_fingerprint"])
                    or review_fp != str(current[2])
                ):
                    raise SomaError(
                        "TASK_REVIEW_STALE",
                        "Task operational evidence changed after correction preview",
                    )
                intent = PhysicalConsequenceIntent(
                    physical_disposition=str(normalized["physical_disposition"]),
                    installed_spare_part_unit_id=normalized[
                        "installed_spare_part_unit_id"
                    ],
                    removed_device_part_unit_id=normalized[
                        "removed_device_part_unit_id"
                    ],
                    inbound_spare_part_unit_id=normalized[
                        "inbound_spare_part_unit_id"
                    ],
                    parent_dismantled_unit_id=normalized[
                        "parent_dismantled_unit_id"
                    ],
                    effective_at_utc=normalized["effective_at_utc"],
                ).validate()
                self._consequences.require_context(
                    uow.connection,
                    task_id=task_id,
                    rma_id=None if current[4] is None else str(current[4]),
                    target_device_part_unit_id=None
                    if current[3] is None
                    else str(current[3]),
                    intent=intent,
                )
                owner_context.update(
                    {
                        "current": current,
                        "task_id": task_id,
                        "intent": intent,
                    }
                )
                result_type = "inventory_physical_consequence"
                result_id = identity

            def apply(inner: UnitOfWork):
                owner_audit: AuditEventInput
                refs: list[tuple[str, str]]
                revisions: dict[str, int]
                correction_event_id: str
                resulting_revision: int

                if correction_kind == "false_spare_request_submission":
                    (
                        correction_event_id,
                        snapshot_id,
                        snapshot_hash,
                        effective_at,
                        allocation_count,
                        resulting_revision,
                    ) = self._requests.correct_false_submission(
                        inner.connection,
                        spare_request_id=identity,
                        base_revision=int(normalized["expected_revision"]),
                        submission_event_id=str(normalized["target_event_id"]),
                        reason_code=reason,
                        command_id=command_id,
                    )
                    owner_audit = AuditEventInput(
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
                            "submission_event_id": str(normalized["target_event_id"]),
                            "submission_snapshot_id": snapshot_id,
                            "event_kind": "CORRECT_FALSE",
                            "allocation_count": allocation_count,
                            "input_fingerprint": snapshot_hash,
                            "effective_at_utc": effective_at,
                        },
                        resulting_event_refs=(
                            AuditResultRef(
                                "spare_request_submission_snapshot",
                                snapshot_id,
                            ),
                        ),
                    )
                    refs = [("spare_request", identity)]
                    revisions = {f"spare_request:{identity}": resulting_revision}
                    generic_target_id = str(normalized["target_event_id"])
                elif correction_kind == "rma_identifier_alias":
                    row = owner_context["row"]
                    event_id, alias_id, resulting_revision = self._rmas.correct_c10(
                        inner.connection,
                        rma_id=identity,
                        expected_current_c10=str(normalized["current_c10"]),
                        new_c10=str(normalized["new_c10"]),
                        reason_code=reason,
                        command_id=command_id,
                    )
                    correction_event_id = event_id
                    owner_audit = AuditEventInput(
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
                            "spare_request_id": str(row[1]),
                            "authorization_batch_id": None,
                            "rma_id": identity,
                            "event_kind": "C10_CORRECT",
                            "current_c10": str(normalized["new_c10"]),
                            "target_device_part_unit_id": (
                                None if row[6] is None else str(row[6])
                            ),
                            "resulting_revision": resulting_revision,
                        },
                        resulting_event_refs=(AuditResultRef("rma", identity),),
                    )
                    refs = [("rma", identity), ("rma_identifier", alias_id)]
                    revisions = {f"rma:{identity}": resulting_revision}
                    generic_target_id = str(owner_context["old_alias_id"])
                elif correction_kind == "logistics_participant_relationship":
                    (
                        logistics_event_id,
                        corrected_participant_id,
                        replacement_participant_id,
                    ) = self._logistics.correct_participant_relationship(
                        inner.connection,
                        participant_id=identity,
                        replacement_kind=normalized["replacement_kind"],
                        replacement_id=normalized["replacement_id"],
                        reason_code=reason,
                        command_id=command_id,
                    )
                    generic_audit_id = new_uuid4()
                    correction_event_id = (
                        replacement_participant_id
                        if replacement_participant_id is not None
                        else generic_audit_id
                    )
                    owner_audit = AuditEventInput(
                        audit_event_id=new_uuid4(),
                        action_type="inventory.logistics.recorded_or_corrected",
                        action_version=1,
                        actor_kind=actor_kind,
                        actor_id=actor_id,
                        target_type="logistics_event",
                        target_id=logistics_event_id,
                        command_id=command_id,
                        reason_category=reason,
                        payload_schema="LogisticsAuditV1",
                        payload_version=1,
                        payload={
                            "logistics_event_id": logistics_event_id,
                            "event_kind": "correction",
                            "effective_at_utc": None,
                            "participant_count": 1,
                            "corrected_participant_id": corrected_participant_id,
                            "resulting_revision": 2,
                        },
                        resulting_event_refs=(
                            AuditResultRef("logistics_event", logistics_event_id),
                            AuditResultRef(
                                "logistics_participant",
                                corrected_participant_id,
                            ),
                            *(
                                ()
                                if replacement_participant_id is None
                                else (
                                    AuditResultRef(
                                        "logistics_participant",
                                        replacement_participant_id,
                                    ),
                                )
                            ),
                        ),
                    )
                    refs = [
                        ("logistics_participant", corrected_participant_id),
                        ("logistics_event", logistics_event_id),
                    ]
                    revisions = {
                        f"logistics_participant:{corrected_participant_id}": 2
                    }
                    if replacement_participant_id is not None:
                        refs.append(
                            ("logistics_participant", replacement_participant_id)
                        )
                        revisions[
                            f"logistics_participant:{replacement_participant_id}"
                        ] = 1
                    generic_target_id = corrected_participant_id
                    resulting_revision = 2
                elif correction_kind == "false_fault_tag_submission":
                    result = self._fault_tags.correct_false_submission(
                        inner.connection,
                        fault_tag_id=identity,
                        submission_event_id=str(normalized["target_event_id"]),
                        reason_code=reason,
                        confirmed_no_real_send=True,
                        command_id=command_id,
                    )
                    correction_event_id = str(result["correction_event_id"])
                    resulting_revision = int(result["revision"])
                    owner_audit = AuditEventInput(
                        audit_event_id=new_uuid4(),
                        action_type="inventory.fault_tag.submitted",
                        action_version=1,
                        actor_kind=actor_kind,
                        actor_id=actor_id,
                        target_type="fault_tag",
                        target_id=identity,
                        command_id=command_id,
                        reason_category=reason,
                        payload_schema="FaultTagSubmissionAuditV1",
                        payload_version=1,
                        payload={
                            "fault_tag_id": identity,
                            "submission_event_id": str(normalized["target_event_id"]),
                            "submission_snapshot_id": str(owner_context["snapshot_id"]),
                            "event_kind": "CORRECT_FALSE",
                            "membership_count": int(owner_context["membership_count"]),
                            "input_fingerprint": str(owner_context["snapshot_hash"]),
                            "effective_at_utc": owner_context["effective_at"],
                        },
                        resulting_event_refs=(
                            AuditResultRef(
                                "fault_tag_submission_snapshot",
                                str(owner_context["snapshot_id"]),
                            ),
                        ),
                    )
                    refs = [("fault_tag", identity)]
                    revisions = {f"fault_tag:{identity}": resulting_revision}
                    generic_target_id = str(normalized["target_event_id"])
                else:
                    current = owner_context["current"]
                    intent = owner_context["intent"]
                    task_id = str(owner_context["task_id"])
                    result = self._consequences.correct(
                        inner.connection,
                        physical_consequence_id=identity,
                        expected_revision=int(normalized["expected_revision"]),
                        expected_event_id=str(normalized["target_event_id"]),
                        intent=intent,
                        reason_code=reason,
                        command_id=command_id,
                    )
                    correction_event_id = str(result["consequence_event_id"])
                    resulting_revision = int(result["consequence_revision"])
                    owner_audit = AuditEventInput(
                        audit_event_id=new_uuid4(),
                        action_type=(
                            "inventory.task_physical_consequence."
                            "accepted_or_corrected"
                        ),
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
                            "task_review_fingerprint": str(current[2]),
                            "event_kind": "CORRECT",
                            "disposition": intent.physical_disposition,
                            "return_obligation_id": (
                                None if current[4] is None else str(current[4])
                            ),
                            "resulting_revision": resulting_revision,
                        },
                        resulting_event_refs=tuple(
                            AuditResultRef(result_type, result_id_value)
                            for result_type, result_id_value in result["refs"]
                            if result_type
                            in {
                                "inventory_physical_consequence",
                                "rma_return_obligation",
                            }
                        ),
                    )
                    refs = list(result["refs"])
                    revisions = {
                        f"inventory_physical_consequence:{identity}": resulting_revision
                    }
                    if (
                        intent.inbound_spare_part_unit_id is not None
                        and result["unit_revision"] is not None
                    ):
                        revisions[
                            f"spare_part_unit:{intent.inbound_spare_part_unit_id}"
                        ] = int(result["unit_revision"])
                    if current[4] is not None and result["obligation_revision"] is not None:
                        revisions[
                            f"rma_return_obligation:{current[4]}"
                        ] = int(result["obligation_revision"])
                    generic_target_id = str(normalized["target_event_id"])

                generic_audit_id = new_uuid4()
                generic_audit = AuditEventInput(
                    audit_event_id=generic_audit_id,
                    action_type="inventory.evidence.corrected",
                    action_version=1,
                    actor_kind=actor_kind,
                    actor_id=actor_id,
                    target_type=generic_target_type,
                    target_id=generic_target_id,
                    command_id=command_id,
                    reason_category=reason,
                    payload_schema="InventoryCorrectionAuditV1",
                    payload_version=1,
                    payload={
                        "target_type": generic_target_type,
                        "target_id": generic_target_id,
                        "correction_event_id": correction_event_id,
                        "correction_kind": correction_kind,
                        "resulting_revision": resulting_revision,
                        "reason_category": reason,
                    },
                    resulting_event_refs=tuple(
                        AuditResultRef(result_type_value, result_id_value)
                        for result_type_value, result_id_value in refs[:16]
                    ),
                )
                apply.refs = refs
                apply.revisions = revisions
                return (owner_audit, generic_audit)

            apply.refs = []
            apply.revisions = {}
            return PreparedMutation(
                no_change=False,
                result_type=result_type,
                result_id=result_id,
                apply=apply,
                response_schema="InventoryMutationResultV1",
                response_factory=lambda _inner: self._response(
                    list(apply.refs),
                    dict(apply.revisions),
                ),
            )

        return inventory_mutation_result_from_execution(
            self._boundary.execute(envelope, prepare)
        )

    def hard_delete_untouched_fault_tag(
        self,
        *,
        command_id: str,
        fault_tag_id: str,
        reviewed_revision: int,
        eligibility_fingerprint: str,
        deliberate_confirmation: bool,
        actor_kind: str = "local_user",
        actor_id: str | None = None,
    ) -> InventoryMutationResult:
        identity = require_uuid4(fault_tag_id)
        if type(reviewed_revision) is not int or reviewed_revision <= 0:
            raise ValidationError("reviewed_revision must be positive")
        fingerprint = self._sha256(
            eligibility_fingerprint,
            field="eligibility_fingerprint",
        )
        if deliberate_confirmation is not True:
            raise SomaError(
                "HARD_DELETE_BLOCKED",
                "Inventory hard delete requires deliberate confirmation",
            )
        envelope = CommandEnvelope(
            command_id=command_id,
            command_type="HardDeleteUntouchedInventoryDraft",
            target_type="fault_tag",
            target_id=identity,
            semantic_payload={
                "target_kind": "fault_tag",
                "reviewed_revision": reviewed_revision,
                "deliberate_confirmation": True,
            },
            base_revisions={"fault_tag": reviewed_revision},
            authorizing_fingerprints={"eligibility": fingerprint},
        )

        def require_clear(connection) -> dict[str, object]:
            preview = InventoryPreviewsQueryService._hard_delete_fault_tag_preview(
                connection,
                identity,
            )
            if preview["classification"] == "INDETERMINATE":
                raise SomaError(
                    "DEPENDENCY_INDETERMINATE",
                    "Fault Tag hard-delete eligibility is indeterminate",
                )
            if preview["classification"] != "CLEAR":
                raise SomaError(
                    "HARD_DELETE_BLOCKED",
                    "Fault Tag has protected Inventory history",
                )
            if (
                int(preview["reviewed_revision"]) != reviewed_revision
                or str(preview["eligibility_fingerprint"]) != fingerprint
            ):
                raise SomaError("INV_STALE", "Fault Tag hard-delete preview changed")
            return preview

        def prepare(uow: UnitOfWork) -> PreparedMutation:
            preview = require_clear(uow.connection)
            retained = tuple(str(value) for value in preview["retained_related_ids"])
            evidence_id = command_id

            def apply(inner: UnitOfWork):
                current_preview = require_clear(inner.connection)
                member_ids = [
                    str(value)
                    for row in current_preview["removable_rows"]
                    if row["table"] == "fault_tag_memberships"
                    for value in row["ids"]
                ]
                if member_ids:
                    placeholders = ",".join("?" for _ in member_ids)
                    inner.connection.execute(
                        f"DELETE FROM fault_tag_membership_current "
                        f"WHERE fault_tag_membership_id IN ({placeholders})",
                        tuple(member_ids),
                    )
                    inner.connection.execute(
                        f"DELETE FROM fault_tag_memberships "
                        f"WHERE fault_tag_membership_id IN ({placeholders})",
                        tuple(member_ids),
                    )
                inner.connection.execute(
                    "DELETE FROM fault_tag_current_projection WHERE fault_tag_id=?",
                    (identity,),
                )
                inner.connection.execute(
                    "DELETE FROM fault_tag_lifecycle_events WHERE fault_tag_id=?",
                    (identity,),
                )
                deleted = inner.connection.execute(
                    "DELETE FROM fault_tags WHERE fault_tag_id=?",
                    (identity,),
                )
                if deleted.rowcount != 1:
                    raise SomaError("INV_STALE", "Fault Tag disappeared during hard delete")
                return AuditEventInput(
                    audit_event_id=new_uuid4(),
                    action_type="inventory.untouched_draft.hard_deleted",
                    action_version=1,
                    actor_kind=actor_kind,
                    actor_id=actor_id,
                    target_type="inventory_draft",
                    target_id=identity,
                    command_id=command_id,
                    payload_schema="InventoryHardDeleteAuditV1",
                    payload_version=1,
                    payload={
                        "target_type": "fault_tag",
                        "target_id": identity,
                        "reviewed_revision": reviewed_revision,
                        "eligibility_fingerprint": fingerprint,
                        "retained_related_ids": list(retained[:16]),
                        "result": "DELETED",
                    },
                    resulting_event_refs=(
                        AuditResultRef("hard_delete_evidence", evidence_id),
                    ),
                )

            return PreparedMutation(
                no_change=False,
                result_type="hard_delete_evidence",
                result_id=evidence_id,
                apply=apply,
                response_schema="InventoryMutationResultV1",
                response=self._response(
                    [("hard_delete_evidence", evidence_id)],
                    {},
                ),
            )

        return inventory_mutation_result_from_execution(
            self._boundary.execute(envelope, prepare)
        )


__all__ = ["InventoryCorrectionsBulkService"]
