from __future__ import annotations

from soma.foundation.application.command_boundary import (
    CommandBoundary,
    CommandEnvelope,
    PreparedMutation,
)
from soma.foundation.audit.writer import AuditEventInput, AuditResultRef, AuditWriter
from soma.foundation.errors import SomaError, ValidationError
from soma.foundation.identifiers import new_uuid4, require_uuid4
from soma.foundation.persistence.connections import ConnectionFactory
from soma.foundation.persistence.uow import UnitOfWork

from ..audit_registry import build_inventory_audit_registry
from ..contracts.inventory import (
    InventoryMutationResult,
    inventory_mutation_result_from_execution,
)
from ..queries.previews import InventoryPreviewsQueryService


class InventoryHardDeleteService:
    """Normative LLD-07 hard-delete owner for genuinely untouched drafts."""

    def __init__(self, connection_factory: ConnectionFactory) -> None:
        self._factory = connection_factory
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
    def _response(evidence_id: str) -> dict[str, object]:
        return {
            "outcome": "APPLIED",
            "target_refs": [
                {"type": "hard_delete_evidence", "id": evidence_id}
            ],
            "revisions": {},
        }

    @staticmethod
    def _handler(target_kind: str):
        handlers = {
            "spare_need": InventoryPreviewsQueryService._hard_delete_spare_need_preview,
            "spare_request": InventoryPreviewsQueryService._hard_delete_spare_request_preview,
            "spare_part_unit": InventoryPreviewsQueryService._hard_delete_spare_part_unit_preview,
            "fault_tag": InventoryPreviewsQueryService._hard_delete_fault_tag_preview,
        }
        try:
            return handlers[target_kind]
        except KeyError as exc:
            raise ValidationError(
                "Inventory hard-delete target kind is invalid"
            ) from exc

    @staticmethod
    def _delete_rows(
        inner: UnitOfWork,
        *,
        target_kind: str,
        target_id: str,
        preview: dict[str, object],
    ) -> None:
        if target_kind == "spare_need":
            inner.connection.execute(
                "DELETE FROM spare_need_active_keys WHERE spare_need_id=?",
                (target_id,),
            )
            inner.connection.execute(
                "DELETE FROM spare_need_current_projection WHERE spare_need_id=?",
                (target_id,),
            )
            inner.connection.execute(
                "DELETE FROM spare_need_lifecycle_events WHERE spare_need_id=?",
                (target_id,),
            )
            deleted = inner.connection.execute(
                "DELETE FROM spare_needs WHERE spare_need_id=?",
                (target_id,),
            )
        elif target_kind == "spare_request":
            inner.connection.execute(
                "DELETE FROM spare_request_need_allocations WHERE spare_request_id=?",
                (target_id,),
            )
            inner.connection.execute(
                "DELETE FROM spare_request_draft_logistics WHERE spare_request_id=?",
                (target_id,),
            )
            inner.connection.execute(
                "DELETE FROM spare_request_current_projection WHERE spare_request_id=?",
                (target_id,),
            )
            inner.connection.execute(
                "DELETE FROM spare_request_lifecycle_events WHERE spare_request_id=?",
                (target_id,),
            )
            deleted = inner.connection.execute(
                "DELETE FROM spare_requests WHERE spare_request_id=?",
                (target_id,),
            )
        elif target_kind == "spare_part_unit":
            inner.connection.execute(
                "DELETE FROM spare_part_current_projection WHERE spare_part_unit_id=?",
                (target_id,),
            )
            inner.connection.execute(
                "DELETE FROM spare_part_lifecycle_events WHERE spare_part_unit_id=?",
                (target_id,),
            )
            deleted = inner.connection.execute(
                "DELETE FROM spare_part_units WHERE spare_part_unit_id=?",
                (target_id,),
            )
        else:
            member_ids = [
                str(value)
                for row in preview["removable_rows"]
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
                (target_id,),
            )
            inner.connection.execute(
                "DELETE FROM fault_tag_lifecycle_events WHERE fault_tag_id=?",
                (target_id,),
            )
            deleted = inner.connection.execute(
                "DELETE FROM fault_tags WHERE fault_tag_id=?",
                (target_id,),
            )
        if deleted.rowcount != 1:
            raise SomaError(
                "INV_STALE",
                "Inventory draft disappeared during hard delete",
            )

    def hard_delete_untouched_inventory_draft(
        self,
        *,
        command_id: str,
        target_kind: str,
        target_id: str,
        reviewed_revision: int,
        eligibility_fingerprint: str,
        deliberate_confirmation: bool,
        actor_kind: str = "local_user",
        actor_id: str | None = None,
    ) -> InventoryMutationResult:
        identity = require_uuid4(target_id)
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
        handler = self._handler(target_kind)
        envelope = CommandEnvelope(
            command_id=command_id,
            command_type="HardDeleteUntouchedInventoryDraft",
            target_type=target_kind,
            target_id=identity,
            semantic_payload={
                "target_kind": target_kind,
                "reviewed_revision": reviewed_revision,
                "deliberate_confirmation": True,
            },
            base_revisions={target_kind: reviewed_revision},
            authorizing_fingerprints={"eligibility": fingerprint},
        )

        def require_clear(connection) -> dict[str, object]:
            preview = handler(connection, identity)
            if preview["classification"] == "INDETERMINATE":
                raise SomaError(
                    "DEPENDENCY_INDETERMINATE",
                    "Inventory hard-delete eligibility is indeterminate",
                )
            if preview["classification"] != "CLEAR":
                raise SomaError(
                    "HARD_DELETE_BLOCKED",
                    "Inventory draft has protected history or dependencies",
                )
            if (
                int(preview["reviewed_revision"]) != reviewed_revision
                or str(preview["eligibility_fingerprint"]) != fingerprint
            ):
                raise SomaError(
                    "INV_STALE",
                    "Inventory hard-delete preview changed",
                )
            return preview

        def prepare(uow: UnitOfWork) -> PreparedMutation:
            preview = require_clear(uow.connection)
            retained = tuple(
                str(value) for value in preview["retained_related_ids"]
            )
            evidence_id = command_id

            def apply(inner: UnitOfWork):
                current = require_clear(inner.connection)
                self._delete_rows(
                    inner,
                    target_kind=target_kind,
                    target_id=identity,
                    preview=current,
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
                        "reviewed_revision": reviewed_revision,
                        "eligibility_fingerprint": fingerprint,
                        "retained_related_ids": list(retained[:16]),
                        "result": "DELETED",
                    },
                    resulting_event_refs=(
                        AuditResultRef(
                            "hard_delete_evidence",
                            evidence_id,
                        ),
                    ),
                )

            return PreparedMutation(
                no_change=False,
                result_type="hard_delete_evidence",
                result_id=evidence_id,
                apply=apply,
                response_schema="InventoryMutationResultV1",
                response=self._response(evidence_id),
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
        return self.hard_delete_untouched_inventory_draft(
            command_id=command_id,
            target_kind="fault_tag",
            target_id=fault_tag_id,
            reviewed_revision=reviewed_revision,
            eligibility_fingerprint=eligibility_fingerprint,
            deliberate_confirmation=deliberate_confirmation,
            actor_kind=actor_kind,
            actor_id=actor_id,
        )


__all__ = ["InventoryHardDeleteService"]
