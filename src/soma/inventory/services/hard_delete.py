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
from ..queries.previews import (
    InventoryCommunicationDependencyProvider,
    InventoryDestructivePreviewQuery,
)

_TARGET_KINDS = frozenset(
    {"spare_need", "spare_request", "spare_part_unit", "fault_tag"}
)


class InventoryHardDeleteService:
    def __init__(
        self,
        connection_factory: ConnectionFactory,
        communication_dependency_provider: InventoryCommunicationDependencyProvider | None = None,
    ) -> None:
        self._factory = connection_factory
        self._communications = communication_dependency_provider
        self._boundary = CommandBoundary(
            connection_factory,
            AuditWriter(build_inventory_audit_registry()),
        )

    @staticmethod
    def _delete_rows(
        uow: UnitOfWork,
        *,
        target_kind: str,
        target_id: str,
    ) -> None:
        connection = uow.connection
        connection.execute(
            "DELETE FROM inventory_attention_projection WHERE target_kind=? AND target_id=?",
            (target_kind, target_id),
        )
        if target_kind == "spare_need":
            connection.execute("DELETE FROM spare_need_active_keys WHERE spare_need_id=?", (target_id,))
            connection.execute("DELETE FROM spare_need_current_projection WHERE spare_need_id=?", (target_id,))
            connection.execute("DELETE FROM spare_need_lifecycle_events WHERE spare_need_id=?", (target_id,))
            connection.execute("DELETE FROM spare_needs WHERE spare_need_id=?", (target_id,))
        elif target_kind == "spare_request":
            connection.execute("DELETE FROM spare_request_draft_logistics WHERE spare_request_id=?", (target_id,))
            connection.execute("DELETE FROM spare_request_need_allocations WHERE spare_request_id=?", (target_id,))
            connection.execute("DELETE FROM spare_request_current_projection WHERE spare_request_id=?", (target_id,))
            connection.execute("DELETE FROM spare_request_lifecycle_events WHERE spare_request_id=?", (target_id,))
            connection.execute("DELETE FROM spare_requests WHERE spare_request_id=?", (target_id,))
        elif target_kind == "spare_part_unit":
            connection.execute("DELETE FROM spare_part_current_projection WHERE spare_part_unit_id=?", (target_id,))
            connection.execute("DELETE FROM spare_part_lifecycle_events WHERE spare_part_unit_id=?", (target_id,))
            connection.execute("DELETE FROM spare_part_units WHERE spare_part_unit_id=?", (target_id,))
        elif target_kind == "fault_tag":
            membership_ids = [
                str(row[0])
                for row in connection.execute(
                    "SELECT fault_tag_membership_id FROM fault_tag_memberships "
                    "WHERE fault_tag_id=?",
                    (target_id,),
                ).fetchall()
            ]
            for membership_id in membership_ids:
                connection.execute(
                    "DELETE FROM fault_tag_membership_current WHERE fault_tag_membership_id=?",
                    (membership_id,),
                )
            connection.execute("DELETE FROM fault_tag_memberships WHERE fault_tag_id=?", (target_id,))
            connection.execute("DELETE FROM fault_tag_current_projection WHERE fault_tag_id=?", (target_id,))
            connection.execute("DELETE FROM fault_tag_lifecycle_events WHERE fault_tag_id=?", (target_id,))
            connection.execute("DELETE FROM fault_tags WHERE fault_tag_id=?", (target_id,))
        else:
            raise IntegrityFailure("unsupported Inventory hard-delete target kind")

    def hard_delete_untouched_inventory_draft(
        self,
        *,
        command_id: str,
        target_kind: str,
        target_id: str,
        expected_revision: int,
        preview_fingerprint: str,
        deliberate_confirmation: bool,
        actor_kind: str = "local_user",
        actor_id: str | None = None,
    ) -> InventoryMutationResult:
        if target_kind not in _TARGET_KINDS:
            raise ValidationError("unsupported Inventory hard-delete target kind")
        identity = require_uuid4(target_id)
        if type(expected_revision) is not int or expected_revision <= 0:
            raise ValidationError("expected_revision must be positive")
        if (
            not isinstance(preview_fingerprint, str)
            or len(preview_fingerprint) != 64
            or any(ch not in "0123456789abcdef" for ch in preview_fingerprint)
        ):
            raise ValidationError("preview_fingerprint must be lowercase SHA-256 hex")
        if deliberate_confirmation is not True:
            raise SomaError("HARD_DELETE_BLOCKED", "Inventory hard delete requires deliberate confirmation")
        envelope = CommandEnvelope(
            command_id=command_id,
            command_type="HardDeleteUntouchedInventoryDraft",
            target_type=target_kind,
            target_id=identity,
            semantic_payload={
                "target_kind": target_kind,
                "expected_revision": expected_revision,
                "preview_fingerprint": preview_fingerprint,
                "deliberate_confirmation": True,
            },
            base_revisions={target_kind: expected_revision},
            authorizing_fingerprints={"hard_delete_preview": preview_fingerprint},
        )

        def prepare(uow: UnitOfWork) -> PreparedMutation:
            preview = InventoryDestructivePreviewQuery.classify_hard_delete(
                uow,
                target_kind=target_kind,
                target_id=identity,
                communication_dependency_provider=self._communications,
            )
            if preview["classification"] != "CLEAR":
                raise SomaError(
                    "HARD_DELETE_BLOCKED",
                    "Inventory draft is not hard-delete eligible: "
                    + ",".join(str(x) for x in preview["blockers"]),
                )
            if preview["reviewed_revision"] != expected_revision:
                raise SomaError("INV_STALE", "Inventory draft revision changed")
            if preview["input_fingerprint"] != preview_fingerprint:
                raise SomaError("INV_STALE", "Inventory hard-delete preview changed")
            retained = tuple(str(x) for x in preview["retained_related_ids"])

            def apply(inner: UnitOfWork):
                self._delete_rows(
                    inner,
                    target_kind=target_kind,
                    target_id=identity,
                )
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
                        "target_type": target_kind,
                        "target_id": identity,
                        "reviewed_revision": expected_revision,
                        "eligibility_fingerprint": preview_fingerprint,
                        "retained_related_ids": list(retained),
                        "result": "DELETED",
                    },
                    resulting_event_refs=(
                        AuditResultRef("hard_delete_evidence", identity),
                    ),
                )

            return PreparedMutation(
                no_change=False,
                result_type="hard_delete_evidence",
                result_id=identity,
                apply=apply,
                response_schema="InventoryMutationResultV1",
                response={
                    "outcome": "APPLIED",
                    "target_refs": [
                        {"type": "hard_delete_evidence", "id": identity}
                    ],
                    "revisions": {},
                },
            )

        return inventory_mutation_result_from_execution(
            self._boundary.execute(envelope, prepare)
        )


__all__ = ["InventoryHardDeleteService"]
