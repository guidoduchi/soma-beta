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
                if action_kind != "warehouse_receipt":
                    result_refs.extend(
                        {
                            "type": "rma_return_obligation",
                            "id": str(item["rma_id"]),
                        }
                        for item in result["events"]
                    )
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
                        "retained_related_ids": list(retained),
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
