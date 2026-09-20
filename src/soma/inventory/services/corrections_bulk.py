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

from ..audit_registry import build_inventory_audit_registry
from ..contracts.inventory import (
    InventoryMutationResult,
    inventory_mutation_result_from_execution,
)
from ..domain.fault_tags import WarehouseMembershipTarget, validate_warehouse_targets
from ..domain.needs import validate_reason_code
from ..queries.previews import InventoryBulkPreviewTarget, InventoryPreviewsQueryService
from ..repositories.fault_tags import InventoryFaultTagsRepository


class InventoryCorrectionsBulkService:
    def __init__(self, connection_factory: ConnectionFactory) -> None:
        self._factory = connection_factory
        self._fault_tags = InventoryFaultTagsRepository()
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
