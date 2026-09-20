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
from ..domain.fault_tags import (
    FaultTagMembershipIntent,
    WarehouseMembershipIntent,
    normalize_optional_instructions,
    normalize_optional_uuid,
    validate_memberships,
    validate_return_method,
    validate_warehouse_memberships,
)
from ..repositories.fault_tags import InventoryFaultTagsRepository


class InventoryFaultTagsService:
    def __init__(self, connection_factory: ConnectionFactory) -> None:
        self._factory = connection_factory
        self._repository = InventoryFaultTagsRepository()
        self._boundary = CommandBoundary(
            connection_factory,
            AuditWriter(build_inventory_audit_registry()),
        )

    @staticmethod
    def _transport_state(owner_state: str) -> str:
        if owner_state == "draft":
            return "draft"
        if owner_state in {"submitted", "in_warehouse_review"}:
            return "submitted"
        if owner_state == "superseded":
            return "superseded"
        if owner_state in {"terminal_completed", "terminal_with_rejected", "cancelled"}:
            return "terminal"
        raise IntegrityFailure("Fault Tag projection state is invalid")

    @classmethod
    def _response(cls, connection, fault_tag_id: str) -> dict[str, object]:
        tag = InventoryFaultTagsRepository.current_tag(connection, fault_tag_id)
        if tag is None:
            raise IntegrityFailure("Fault Tag projection disappeared")
        members = InventoryFaultTagsRepository.current_members(connection, fault_tag_id)
        state = cls._transport_state(str(tag[7]))
        if (
            state == "draft"
            and tag[9] is None
            and InventoryFaultTagsRepository.latest_lifecycle_kind(
                connection, fault_tag_id
            ) == "submission_corrected_false"
        ):
            state = "corrected_false_submission"
        return {
            "fault_tag_id": str(tag[0]),
            "tracking_handle": str(tag[1]),
            "state": state,
            "revision": int(tag[10]),
            "members": [
                {
                    "fault_tag_membership_id": str(row[0]),
                    "rma_id": str(row[1]),
                    "physical_consequence_id": str(row[2]),
                    "device_part_unit_id": None if row[3] is None else str(row[3]),
                    "spare_part_unit_id": None if row[4] is None else str(row[4]),
                    "return_reason": str(row[5]),
                    "state": str(row[6]),
                    "revision": int(row[8]),
                }
                for row in members
            ],
        }

    @staticmethod
    def _base_payload(
        *,
        return_method: str,
        pickup_dispatch_location_id: str | None,
        pickup_contact_id: str | None,
        pickup_instructions: str | None,
        memberships: tuple[tuple[str, str], ...],
    ) -> dict[str, object]:
        return {
            "return_method": return_method,
            "pickup_dispatch_location_id": pickup_dispatch_location_id,
            "pickup_contact_id": pickup_contact_id,
            "pickup_instructions": pickup_instructions,
            "memberships": [
                {"rma_id": rma_id, "return_reason": reason}
                for rma_id, reason in memberships
            ],
        }

    def create_fault_tag_draft(
        self,
        *,
        command_id: str,
        return_method: str,
        memberships: tuple[FaultTagMembershipIntent, ...] = (),
        pickup_dispatch_location_id: str | None = None,
        pickup_contact_id: str | None = None,
        pickup_instructions: str | None = None,
        actor_kind: str = "local_user",
        actor_id: str | None = None,
    ) -> dict[str, object]:
        method = validate_return_method(return_method)
        location_id = normalize_optional_uuid(
            pickup_dispatch_location_id, "pickup_dispatch_location_id"
        )
        contact_id = normalize_optional_uuid(pickup_contact_id, "pickup_contact_id")
        instructions = normalize_optional_instructions(pickup_instructions)
        if method == "non_pickup" and (
            location_id is not None or contact_id is not None or instructions is not None
        ):
            raise ValidationError(
                "non_pickup Fault Tag cannot carry pickup-origin context"
            )
        accepted_memberships = validate_memberships(memberships)
        envelope = CommandEnvelope(
            command_id=command_id,
            command_type="CreateFaultTagDraft",
            target_type="fault_tag",
            target_id=None,
            semantic_payload=self._base_payload(
                return_method=method,
                pickup_dispatch_location_id=location_id,
                pickup_contact_id=contact_id,
                pickup_instructions=instructions,
                memberships=accepted_memberships,
            ),
        )

        def prepare(uow: UnitOfWork) -> PreparedMutation:
            self._repository.require_optional_draft_references(
                uow.connection,
                return_method=method,
                pickup_dispatch_location_id=location_id,
                pickup_contact_id=contact_id,
            )
            for rma_id, _reason in accepted_memberships:
                self._repository.require_membership_eligible(
                    uow.connection,
                    rma_id=rma_id,
                )
            fault_tag_id = new_uuid4()

            def apply(inner: UnitOfWork):
                sequence, tracking_id = self._repository.allocate_fault_tag_tracking(
                    inner.connection, command_id
                )
                event_id, membership_ids, revision = self._repository.insert_draft(
                    inner.connection,
                    fault_tag_id=fault_tag_id,
                    tracking_sequence=sequence,
                    tracking_id=tracking_id,
                    return_method=method,
                    pickup_dispatch_location_id=location_id,
                    pickup_contact_id=contact_id,
                    pickup_instructions=instructions,
                    memberships=accepted_memberships,
                    command_id=command_id,
                )
                apply.tracking_id = tracking_id
                apply.event_id = event_id
                apply.membership_ids = membership_ids
                apply.revision = revision
                refs = [AuditResultRef("fault_tag", fault_tag_id)]
                refs.extend(
                    AuditResultRef("fault_tag_membership", membership_id)
                    for membership_id in membership_ids
                )
                return AuditEventInput(
                    audit_event_id=new_uuid4(),
                    action_type="inventory.fault_tag.draft_changed",
                    action_version=1,
                    actor_kind=actor_kind,
                    actor_id=actor_id,
                    target_type="fault_tag",
                    target_id=fault_tag_id,
                    command_id=command_id,
                    payload_schema="FaultTagAuditV1",
                    payload_version=1,
                    payload={
                        "fault_tag_id": fault_tag_id,
                        "tracking_id": tracking_id,
                        "event_kind": "CREATE",
                        "member_count": len(membership_ids),
                        "resulting_revision": revision,
                        "reason_category": None,
                    },
                    resulting_event_refs=tuple(refs),
                )

            apply.tracking_id = ""
            apply.event_id = ""
            apply.membership_ids = ()
            apply.revision = 1
            return PreparedMutation(
                no_change=False,
                result_type="fault_tag",
                result_id=fault_tag_id,
                apply=apply,
                response_schema="FaultTagV1",
                response_factory=lambda inner: self._response(
                    inner.connection, fault_tag_id
                ),
            )

        execution = self._boundary.execute(envelope, prepare)
        if not isinstance(execution.response, dict):
            raise IntegrityFailure("Fault Tag response is not an object")
        return dict(execution.response)

    def update_fault_tag_draft(
        self,
        *,
        command_id: str,
        fault_tag_id: str,
        base_revision: int,
        return_method: str,
        memberships: tuple[FaultTagMembershipIntent, ...],
        pickup_dispatch_location_id: str | None = None,
        pickup_contact_id: str | None = None,
        pickup_instructions: str | None = None,
        actor_kind: str = "local_user",
        actor_id: str | None = None,
    ) -> dict[str, object]:
        identity = require_uuid4(fault_tag_id)
        if type(base_revision) is not int or base_revision <= 0:
            raise ValidationError("base_revision must be positive")
        method = validate_return_method(return_method)
        location_id = normalize_optional_uuid(
            pickup_dispatch_location_id, "pickup_dispatch_location_id"
        )
        contact_id = normalize_optional_uuid(pickup_contact_id, "pickup_contact_id")
        instructions = normalize_optional_instructions(pickup_instructions)
        if method == "non_pickup" and (
            location_id is not None or contact_id is not None or instructions is not None
        ):
            raise ValidationError(
                "non_pickup Fault Tag cannot carry pickup-origin context"
            )
        accepted_memberships = validate_memberships(memberships)
        envelope = CommandEnvelope(
            command_id=command_id,
            command_type="UpdateFaultTagDraft",
            target_type="fault_tag",
            target_id=identity,
            semantic_payload=self._base_payload(
                return_method=method,
                pickup_dispatch_location_id=location_id,
                pickup_contact_id=contact_id,
                pickup_instructions=instructions,
                memberships=accepted_memberships,
            ),
            base_revisions={"fault_tag": base_revision},
        )

        def prepare(uow: UnitOfWork) -> PreparedMutation:
            tag = self._repository.current_tag(uow.connection, identity)
            if tag is None or int(tag[10]) != base_revision:
                raise SomaError("INV_STALE", "Fault Tag revision changed")
            if str(tag[7]) != "draft" or tag[9] is not None:
                raise SomaError("FAULT_TAG_NOT_DRAFT", "Fault Tag is not editable Draft authority")
            self._repository.require_optional_draft_references(
                uow.connection,
                return_method=method,
                pickup_dispatch_location_id=location_id,
                pickup_contact_id=contact_id,
            )
            current_members = self._repository.current_members(uow.connection, identity)
            current_semantic = tuple(
                sorted((str(row[1]), str(row[5])) for row in current_members)
            )
            if (
                str(tag[2]) == method
                and (None if tag[3] is None else str(tag[3])) == location_id
                and (None if tag[4] is None else str(tag[4])) == contact_id
                and (None if tag[5] is None else str(tag[5])) == instructions
                and current_semantic == accepted_memberships
            ):
                return PreparedMutation(
                    no_change=True,
                    result_type=None,
                    result_id=None,
                    response_schema="FaultTagV1",
                    response=self._response(uow.connection, identity),
                )

            def apply(inner: UnitOfWork):
                membership_ids, revision = self._repository.replace_draft(
                    inner.connection,
                    fault_tag_id=identity,
                    base_revision=base_revision,
                    return_method=method,
                    pickup_dispatch_location_id=location_id,
                    pickup_contact_id=contact_id,
                    pickup_instructions=instructions,
                    memberships=accepted_memberships,
                    command_id=command_id,
                )
                apply.membership_ids = membership_ids
                apply.revision = revision
                tracking_id = str(
                    self._repository.current_tag(inner.connection, identity)[1]
                )
                refs = [AuditResultRef("fault_tag", identity)]
                refs.extend(
                    AuditResultRef("fault_tag_membership", membership_id)
                    for membership_id in membership_ids
                )
                return AuditEventInput(
                    audit_event_id=new_uuid4(),
                    action_type="inventory.fault_tag.draft_changed",
                    action_version=1,
                    actor_kind=actor_kind,
                    actor_id=actor_id,
                    target_type="fault_tag",
                    target_id=identity,
                    command_id=command_id,
                    payload_schema="FaultTagAuditV1",
                    payload_version=1,
                    payload={
                        "fault_tag_id": identity,
                        "tracking_id": tracking_id,
                        "event_kind": "DRAFT_UPDATE",
                        "member_count": len(membership_ids),
                        "resulting_revision": revision,
                        "reason_category": None,
                    },
                    resulting_event_refs=tuple(refs),
                )

            apply.membership_ids = ()
            apply.revision = base_revision + 1
            return PreparedMutation(
                no_change=False,
                result_type="fault_tag",
                result_id=identity,
                apply=apply,
                response_schema="FaultTagV1",
                response_factory=lambda inner: self._response(
                    inner.connection, identity
                ),
            )

        execution = self._boundary.execute(envelope, prepare)
        if not isinstance(execution.response, dict):
            raise IntegrityFailure("Fault Tag response is not an object")
        return dict(execution.response)


    def accept_fault_tag_submission(
        self,
        *,
        command_id: str,
        fault_tag_id: str,
        expected_fingerprint: str,
        effective_submission_at_utc: int | None = None,
        evidence_kind: str = "manual",
        evidence_id: str | None = None,
        actor_kind: str = "local_user",
        actor_id: str | None = None,
    ) -> dict[str, object]:
        identity = require_uuid4(fault_tag_id)
        if (
            not isinstance(expected_fingerprint, str)
            or len(expected_fingerprint) != 64
            or any(ch not in "0123456789abcdef" for ch in expected_fingerprint)
        ):
            raise ValidationError("expected_fingerprint must be lowercase SHA-256 hex")
        if (
            effective_submission_at_utc is not None
            and (type(effective_submission_at_utc) is not int or effective_submission_at_utc < 0)
        ):
            raise ValidationError("effective_submission_at_utc must be non-negative or null")
        if evidence_kind not in {"manual", "indexed_sent"}:
            raise ValidationError("Fault Tag submission evidence kind is invalid")
        if evidence_kind == "indexed_sent" and (
            not isinstance(evidence_id, str) or not evidence_id.strip()
        ):
            raise ValidationError("indexed sent Fault Tag submission requires evidence_id")
        if evidence_kind == "manual" and evidence_id is not None:
            raise ValidationError("manual Fault Tag submission cannot carry evidence_id")
        normalized_evidence_id = None if evidence_id is None else evidence_id.strip()
        envelope = CommandEnvelope(
            command_id=command_id,
            command_type="AcceptFaultTagSubmission",
            target_type="fault_tag",
            target_id=identity,
            semantic_payload={
                "expected_fingerprint": expected_fingerprint,
                "effective_submission_at_utc": effective_submission_at_utc,
                "evidence_kind": evidence_kind,
                "evidence_id": normalized_evidence_id,
            },
            authorizing_fingerprints={"draft": expected_fingerprint},
        )

        def prepare(uow: UnitOfWork) -> PreparedMutation:
            tag = self._repository.current_tag(uow.connection, identity)
            if tag is None or str(tag[11]) != expected_fingerprint:
                raise SomaError("INV_STALE", "Fault Tag draft fingerprint changed")
            if str(tag[7]) != "draft" or tag[9] is not None:
                raise SomaError("FAULT_TAG_NOT_DRAFT", "Fault Tag is not Draft")
            if str(tag[2]) == "pickup" and tag[3] is None:
                raise SomaError(
                    "FAULT_TAG_PICKUP_ORIGIN_REQUIRED",
                    "Pickup Fault Tag requires pickup-origin Dispatch Location",
                )
            if not self._repository.current_members(uow.connection, identity):
                raise SomaError(
                    "FAULT_TAG_NOT_DRAFT",
                    "Fault Tag submission requires one-or-more members",
                )

            def apply(inner: UnitOfWork):
                (
                    event_id,
                    snapshot_id,
                    revision,
                    member_count,
                    snapshot_hash,
                ) = self._repository.accept_submission(
                    inner.connection,
                    fault_tag_id=identity,
                    expected_fingerprint=expected_fingerprint,
                    effective_submission_at_utc=effective_submission_at_utc,
                    evidence_kind=evidence_kind,
                    evidence_id=normalized_evidence_id,
                    command_id=command_id,
                )
                apply.event_id = event_id
                apply.snapshot_id = snapshot_id
                apply.revision = revision
                apply.member_count = member_count
                apply.snapshot_hash = snapshot_hash
                return AuditEventInput(
                    audit_event_id=new_uuid4(),
                    action_type="inventory.fault_tag.submitted",
                    action_version=1,
                    actor_kind=actor_kind,
                    actor_id=actor_id,
                    target_type="fault_tag",
                    target_id=identity,
                    command_id=command_id,
                    payload_schema="FaultTagSubmissionAuditV1",
                    payload_version=1,
                    payload={
                        "fault_tag_id": identity,
                        "submission_event_id": event_id,
                        "submission_snapshot_id": snapshot_id,
                        "event_kind": "ACCEPT",
                        "membership_count": member_count,
                        "input_fingerprint": expected_fingerprint,
                        "effective_at_utc": effective_submission_at_utc,
                    },
                    resulting_event_refs=(
                        AuditResultRef("fault_tag", identity),
                        AuditResultRef("fault_tag_submission_snapshot", snapshot_id),
                    ),
                )

            apply.event_id = ""
            apply.snapshot_id = ""
            apply.revision = int(tag[10]) + 1
            apply.member_count = 0
            apply.snapshot_hash = ""
            return PreparedMutation(
                no_change=False,
                result_type="fault_tag",
                result_id=identity,
                apply=apply,
                response_schema="FaultTagV1",
                response_factory=lambda inner: self._response(inner.connection, identity),
            )

        execution = self._boundary.execute(envelope, prepare)
        if not isinstance(execution.response, dict):
            raise IntegrityFailure("Fault Tag response is not an object")
        return dict(execution.response)

    def correct_false_fault_tag_submission(
        self,
        *,
        command_id: str,
        fault_tag_id: str,
        submission_event_id: str,
        reason_code: str,
        actor_kind: str = "local_user",
        actor_id: str | None = None,
    ) -> dict[str, object]:
        identity = require_uuid4(fault_tag_id)
        target_event = require_uuid4(submission_event_id)
        if not isinstance(reason_code, str) or not reason_code.strip():
            raise ValidationError("False Fault Tag submission correction requires a reason")
        reason = reason_code.strip()
        if len(reason.encode("utf-8", errors="strict")) > 384:
            raise ValidationError("reason_code exceeds UTF-8 byte bound")
        envelope = CommandEnvelope(
            command_id=command_id,
            command_type="CorrectFalseFaultTagSubmission",
            target_type="fault_tag",
            target_id=identity,
            semantic_payload={
                "submission_event_id": target_event,
                "reason_code": reason,
            },
        )

        def prepare(uow: UnitOfWork) -> PreparedMutation:
            current = self._repository.latest_submission(uow.connection, identity)
            if current is None or str(current[1]) != target_event:
                raise SomaError(
                    "CORRECTION_TARGET_INVALID",
                    "Target is not current-effective Fault Tag submission",
                )
            tag = self._repository.current_tag(uow.connection, identity)
            if tag is None:
                raise SomaError("INV_STALE", "Fault Tag no longer exists")
            tracking_id = str(tag[1])

            def apply(inner: UnitOfWork):
                (
                    correction_event_id,
                    snapshot_id,
                    revision,
                    member_count,
                    _prior_snapshot_hash,
                ) = self._repository.correct_false_submission(
                    inner.connection,
                    fault_tag_id=identity,
                    submission_event_id=target_event,
                    reason_code=reason,
                    command_id=command_id,
                )
                apply.event_id = correction_event_id
                apply.snapshot_id = snapshot_id
                apply.revision = revision
                apply.member_count = member_count
                return AuditEventInput(
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
                        "resulting_revision": revision,
                        "reason_category": reason,
                    },
                    resulting_event_refs=(
                        AuditResultRef("fault_tag", identity),
                        AuditResultRef("fault_tag_submission_snapshot", snapshot_id),
                    ),
                )

            apply.event_id = ""
            apply.snapshot_id = str(current[0])
            apply.revision = int(tag[10]) + 1
            apply.member_count = 0
            return PreparedMutation(
                no_change=False,
                result_type="fault_tag",
                result_id=identity,
                apply=apply,
                response_schema="FaultTagV1",
                response_factory=lambda inner: self._response(inner.connection, identity),
            )

        execution = self._boundary.execute(envelope, prepare)
        if not isinstance(execution.response, dict):
            raise IntegrityFailure("Fault Tag response is not an object")
        return dict(execution.response)


    @staticmethod
    def _inventory_response(
        refs: list[tuple[str, str]],
        revisions: dict[str, int],
    ) -> dict[str, object]:
        return {
            "outcome": "APPLIED",
            "target_refs": [{"type": kind, "id": identity} for kind, identity in refs],
            "revisions": dict(revisions),
        }

    def record_warehouse_receipt(
        self,
        *,
        command_id: str,
        memberships: tuple[WarehouseMembershipIntent, ...],
        effective_at_utc: int | None = None,
        evidence_kind: str | None = None,
        evidence_id: str | None = None,
        actor_kind: str = "local_user",
        actor_id: str | None = None,
    ):
        from ..contracts.inventory import inventory_mutation_result_from_execution

        targets = validate_warehouse_memberships(memberships)
        if effective_at_utc is not None and (
            type(effective_at_utc) is not int or effective_at_utc < 0
        ):
            raise ValidationError("effective_at_utc must be non-negative or null")
        if evidence_kind is None and evidence_id is not None:
            raise ValidationError("evidence_id requires evidence_kind")
        normalized_evidence_id = None if evidence_id is None else evidence_id.strip()
        is_batch = len(targets) > 1
        result_type = "inventory_batch" if is_batch else "fault_tag_membership"
        envelope = CommandEnvelope(
            command_id=command_id,
            command_type="RecordWarehouseReceipt",
            target_type=result_type,
            target_id=None if is_batch else targets[0][0],
            semantic_payload={
                "memberships": [
                    {"fault_tag_membership_id": identity, "revision": revision}
                    for identity, revision in targets
                ],
                "effective_at_utc": effective_at_utc,
                "evidence_kind": evidence_kind,
                "evidence_id": normalized_evidence_id,
            },
        )

        def prepare(uow: UnitOfWork) -> PreparedMutation:
            batch_id = new_uuid4() if is_batch else None
            result_id = batch_id if is_batch else targets[0][0]
            for identity, revision in targets:
                self._repository._require_warehouse_target(
                    uow.connection,
                    membership_id=identity,
                    expected_revision=revision,
                    required_state="submitted_awaiting_receipt",
                )

            def apply(inner: UnitOfWork):
                results, tag_revisions = self._repository.record_warehouse_receipt(
                    inner.connection,
                    targets=targets,
                    effective_at_utc=effective_at_utc,
                    evidence_kind=evidence_kind,
                    evidence_id=normalized_evidence_id,
                    batch_id=batch_id,
                    command_id=command_id,
                )
                apply.results = results
                apply.tag_revisions = tag_revisions
                audits = []
                for item in results:
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
                            payload_schema="WarehouseDecisionAuditV1",
                            payload_version=1,
                            payload={
                                "membership_id": str(item["membership_id"]),
                                "event_kind": "RECEIVED",
                                "rma_id": str(item["rma_id"]),
                                "return_obligation_id": str(item["rma_id"]),
                                "batch_id": batch_id,
                                "effective_at_utc": effective_at_utc,
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
                return tuple(audits)

            apply.results = ()
            apply.tag_revisions = {}
            return PreparedMutation(
                no_change=False,
                result_type=result_type,
                result_id=result_id,
                apply=apply,
                response_schema="InventoryMutationResultV1",
                response_factory=lambda _inner: self._inventory_response(
                    (
                        ([] if batch_id is None else [("inventory_batch", batch_id)])
                        + [
                            ("fault_tag_membership", str(item["membership_id"]))
                            for item in apply.results
                        ]
                        + [
                            ("fault_tag_membership_event", str(item["membership_event_id"]))
                            for item in apply.results
                        ]
                    ),
                    {
                        **{
                            f"fault_tag_membership:{item['membership_id']}": int(
                                item["membership_revision"]
                            )
                            for item in apply.results
                        },
                        **{
                            f"fault_tag:{tag_id}": revision
                            for tag_id, revision in apply.tag_revisions.items()
                        },
                    },
                ),
            )

        return inventory_mutation_result_from_execution(
            self._boundary.execute(envelope, prepare)
        )

    def record_warehouse_final_decision(
        self,
        *,
        command_id: str,
        memberships: tuple[WarehouseMembershipIntent, ...],
        decision: str,
        explicit_confirmation: bool,
        reason_code: str | None = None,
        effective_at_utc: int | None = None,
        evidence_kind: str | None = None,
        evidence_id: str | None = None,
        actor_kind: str = "local_user",
        actor_id: str | None = None,
    ):
        from ..contracts.inventory import inventory_mutation_result_from_execution

        targets = validate_warehouse_memberships(memberships)
        if decision not in {"accepted", "rejected"}:
            raise ValidationError("warehouse final decision is invalid")
        if explicit_confirmation is not True:
            raise SomaError(
                "WAREHOUSE_FINAL_CONFIRMATION_REQUIRED",
                "Warehouse final decision requires explicit operator confirmation",
            )
        reason = None
        if reason_code is not None:
            if not isinstance(reason_code, str) or not reason_code.strip():
                raise ValidationError("reason_code is invalid")
            reason = reason_code.strip()
            if len(reason.encode("utf-8", errors="strict")) > 384:
                raise ValidationError("reason_code exceeds UTF-8 byte bound")
        if decision == "rejected" and reason is None:
            raise ValidationError("warehouse rejection requires a reason")
        if effective_at_utc is not None and (
            type(effective_at_utc) is not int or effective_at_utc < 0
        ):
            raise ValidationError("effective_at_utc must be non-negative or null")
        if evidence_kind is None and evidence_id is not None:
            raise ValidationError("evidence_id requires evidence_kind")
        normalized_evidence_id = None if evidence_id is None else evidence_id.strip()
        is_batch = len(targets) > 1
        result_type = "inventory_batch" if is_batch else "fault_tag_membership"
        envelope = CommandEnvelope(
            command_id=command_id,
            command_type="RecordWarehouseFinalDecision",
            target_type=result_type,
            target_id=None if is_batch else targets[0][0],
            semantic_payload={
                "memberships": [
                    {"fault_tag_membership_id": identity, "revision": revision}
                    for identity, revision in targets
                ],
                "decision": decision,
                "explicit_confirmation": True,
                "reason_code": reason,
                "effective_at_utc": effective_at_utc,
                "evidence_kind": evidence_kind,
                "evidence_id": normalized_evidence_id,
            },
        )

        def prepare(uow: UnitOfWork) -> PreparedMutation:
            batch_id = new_uuid4() if is_batch else None
            result_id = batch_id if is_batch else targets[0][0]
            for identity, revision in targets:
                self._repository._require_warehouse_target(
                    uow.connection,
                    membership_id=identity,
                    expected_revision=revision,
                    required_state="warehouse_received",
                )

            def apply(inner: UnitOfWork):
                results, tag_revisions = self._repository.record_warehouse_final_decision(
                    inner.connection,
                    targets=targets,
                    decision=decision,
                    reason_code=reason,
                    effective_at_utc=effective_at_utc,
                    evidence_kind=evidence_kind,
                    evidence_id=normalized_evidence_id,
                    batch_id=batch_id,
                    command_id=command_id,
                )
                apply.results = results
                apply.tag_revisions = tag_revisions
                event_kind = "ACCEPTED" if decision == "accepted" else "REJECTED"
                return tuple(
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
                            AuditResultRef(
                                "fault_tag_membership_event",
                                str(item["membership_event_id"]),
                            ),
                        ),
                    )
                    for item in results
                )

            apply.results = ()
            apply.tag_revisions = {}
            return PreparedMutation(
                no_change=False,
                result_type=result_type,
                result_id=result_id,
                apply=apply,
                response_schema="InventoryMutationResultV1",
                response_factory=lambda _inner: self._inventory_response(
                    (
                        ([] if batch_id is None else [("inventory_batch", batch_id)])
                        + [
                            ("fault_tag_membership", str(item["membership_id"]))
                            for item in apply.results
                        ]
                        + [
                            ("fault_tag_membership_event", str(item["membership_event_id"]))
                            for item in apply.results
                        ]
                    ),
                    {
                        **{
                            f"fault_tag_membership:{item['membership_id']}": int(
                                item["membership_revision"]
                            )
                            for item in apply.results
                        },
                        **{
                            f"fault_tag:{tag_id}": revision
                            for tag_id, revision in apply.tag_revisions.items()
                        },
                    },
                ),
            )

        return inventory_mutation_result_from_execution(
            self._boundary.execute(envelope, prepare)
        )


    def _create_fault_tag_successor(
        self,
        *,
        command_id: str,
        predecessor_fault_tag_id: str,
        relation_type: str,
        return_method: str,
        memberships: tuple[FaultTagMembershipIntent, ...],
        reason_code: str,
        pickup_dispatch_location_id: str | None,
        pickup_contact_id: str | None,
        pickup_instructions: str | None,
        actor_kind: str,
        actor_id: str | None,
    ) -> dict[str, object]:
        predecessor = require_uuid4(predecessor_fault_tag_id)
        method = validate_return_method(return_method)
        location_id = normalize_optional_uuid(
            pickup_dispatch_location_id, "pickup_dispatch_location_id"
        )
        contact_id = normalize_optional_uuid(pickup_contact_id, "pickup_contact_id")
        instructions = normalize_optional_instructions(pickup_instructions)
        if method == "non_pickup" and (
            location_id is not None or contact_id is not None or instructions is not None
        ):
            raise ValidationError("non_pickup Fault Tag cannot carry pickup-origin context")
        accepted_memberships = validate_memberships(memberships)
        if not accepted_memberships:
            raise ValidationError("Fault Tag successor requires one-or-more memberships")
        if not isinstance(reason_code, str) or not reason_code.strip():
            raise ValidationError("Fault Tag successor requires a reason")
        reason = reason_code.strip()
        if len(reason.encode("utf-8", errors="strict")) > 384:
            raise ValidationError("reason_code exceeds UTF-8 byte bound")
        command_type = (
            "CreateFaultTagReplacement"
            if relation_type == "corrects_replaces"
            else "CreateFaultTagResend"
        )
        envelope = CommandEnvelope(
            command_id=command_id,
            command_type=command_type,
            target_type="fault_tag",
            target_id=predecessor,
            semantic_payload={
                "return_method": method,
                "pickup_dispatch_location_id": location_id,
                "pickup_contact_id": contact_id,
                "pickup_instructions": instructions,
                "memberships": [
                    {"rma_id": rma_id, "return_reason": member_reason}
                    for rma_id, member_reason in accepted_memberships
                ],
                "reason_code": reason,
            },
        )

        def prepare(uow: UnitOfWork) -> PreparedMutation:
            successor_id = new_uuid4()
            predecessor_tag = self._repository.current_tag(uow.connection, predecessor)
            if predecessor_tag is None:
                raise SomaError("INV_STALE", "Fault Tag predecessor no longer exists")
            if relation_type == "corrects_replaces":
                if not self._repository.has_submission_history(uow.connection, predecessor):
                    raise SomaError(
                        "REPLACEMENT_LINEAGE_CONFLICT",
                        "Fault Tag replacement requires submitted predecessor history",
                    )
                if self._repository.correction_successor(uow.connection, predecessor) is not None:
                    raise SomaError(
                        "REPLACEMENT_LINEAGE_CONFLICT",
                        "Fault Tag already has a correction successor",
                    )
            else:
                self._repository.require_resend_scope(
                    uow.connection,
                    predecessor_fault_tag_id=predecessor,
                    memberships=accepted_memberships,
                )
            self._repository.require_optional_draft_references(
                uow.connection,
                return_method=method,
                pickup_dispatch_location_id=location_id,
                pickup_contact_id=contact_id,
            )

            def apply(inner: UnitOfWork):
                lineage_id, tracking_id, membership_ids, revision = (
                    self._repository.create_lineage_successor(
                        inner.connection,
                        successor_fault_tag_id=successor_id,
                        predecessor_fault_tag_id=predecessor,
                        relation_type=relation_type,
                        return_method=method,
                        pickup_dispatch_location_id=location_id,
                        pickup_contact_id=contact_id,
                        pickup_instructions=instructions,
                        memberships=accepted_memberships,
                        reason_code=reason,
                        command_id=command_id,
                    )
                )
                apply.lineage_id = lineage_id
                apply.tracking_id = tracking_id
                apply.membership_ids = membership_ids
                apply.revision = revision
                scope_fingerprint = self._repository._lineage_scope_fingerprint(
                    accepted_memberships
                )
                event_kind = (
                    "CORRECTS_REPLACES"
                    if relation_type == "corrects_replaces"
                    else "RESEND_OF"
                )
                return AuditEventInput(
                    audit_event_id=new_uuid4(),
                    action_type="inventory.fault_tag.replacement_or_resend_created",
                    action_version=1,
                    actor_kind=actor_kind,
                    actor_id=actor_id,
                    target_type="fault_tag",
                    target_id=successor_id,
                    command_id=command_id,
                    reason_category=reason,
                    payload_schema="FaultTagLineageAuditV1",
                    payload_version=1,
                    payload={
                        "predecessor_fault_tag_id": predecessor,
                        "successor_fault_tag_id": successor_id,
                        "lineage_kind": event_kind,
                        "membership_scope_fingerprint": scope_fingerprint,
                        "reason_category": reason,
                        "resulting_revision": revision,
                    },
                    resulting_event_refs=(
                        AuditResultRef("fault_tag", successor_id),
                        AuditResultRef("fault_tag_lineage", lineage_id),
                    ),
                )

            apply.lineage_id = ""
            apply.tracking_id = ""
            apply.membership_ids = ()
            apply.revision = 1
            return PreparedMutation(
                no_change=False,
                result_type="fault_tag",
                result_id=successor_id,
                apply=apply,
                response_schema="FaultTagV1",
                response_factory=lambda inner: self._response(
                    inner.connection, successor_id
                ),
            )

        execution = self._boundary.execute(envelope, prepare)
        if not isinstance(execution.response, dict):
            raise IntegrityFailure("Fault Tag successor response is not an object")
        return dict(execution.response)

    def create_fault_tag_replacement(
        self,
        *,
        command_id: str,
        predecessor_fault_tag_id: str,
        return_method: str,
        memberships: tuple[FaultTagMembershipIntent, ...],
        reason_code: str,
        pickup_dispatch_location_id: str | None = None,
        pickup_contact_id: str | None = None,
        pickup_instructions: str | None = None,
        actor_kind: str = "local_user",
        actor_id: str | None = None,
    ) -> dict[str, object]:
        return self._create_fault_tag_successor(
            command_id=command_id,
            predecessor_fault_tag_id=predecessor_fault_tag_id,
            relation_type="corrects_replaces",
            return_method=return_method,
            memberships=memberships,
            reason_code=reason_code,
            pickup_dispatch_location_id=pickup_dispatch_location_id,
            pickup_contact_id=pickup_contact_id,
            pickup_instructions=pickup_instructions,
            actor_kind=actor_kind,
            actor_id=actor_id,
        )

    def create_fault_tag_resend(
        self,
        *,
        command_id: str,
        predecessor_fault_tag_id: str,
        return_method: str,
        memberships: tuple[FaultTagMembershipIntent, ...],
        reason_code: str,
        pickup_dispatch_location_id: str | None = None,
        pickup_contact_id: str | None = None,
        pickup_instructions: str | None = None,
        actor_kind: str = "local_user",
        actor_id: str | None = None,
    ) -> dict[str, object]:
        return self._create_fault_tag_successor(
            command_id=command_id,
            predecessor_fault_tag_id=predecessor_fault_tag_id,
            relation_type="resend_of",
            return_method=return_method,
            memberships=memberships,
            reason_code=reason_code,
            pickup_dispatch_location_id=pickup_dispatch_location_id,
            pickup_contact_id=pickup_contact_id,
            pickup_instructions=pickup_instructions,
            actor_kind=actor_kind,
            actor_id=actor_id,
        )

    def archive_or_restore_fault_tag(
        self,
        *,
        command_id: str,
        fault_tag_id: str,
        base_revision: int,
        action: str,
        reason_code: str | None = None,
        actor_kind: str = "local_user",
        actor_id: str | None = None,
    ) -> dict[str, object]:
        identity = require_uuid4(fault_tag_id)
        if type(base_revision) is not int or base_revision <= 0:
            raise ValidationError("base_revision must be positive")
        if action not in {"archive", "restore"}:
            raise ValidationError("Fault Tag archive action is invalid")
        reason = None
        if reason_code is not None:
            if not isinstance(reason_code, str) or not reason_code.strip():
                raise ValidationError("reason_code is invalid")
            reason = reason_code.strip()
        if action == "archive" and reason is None:
            raise ValidationError("Fault Tag archive requires a reason")
        envelope = CommandEnvelope(
            command_id=command_id,
            command_type="ArchiveOrRestoreFaultTag",
            target_type="fault_tag",
            target_id=identity,
            semantic_payload={"action": action, "reason_code": reason},
            base_revisions={"fault_tag": base_revision},
        )

        def prepare(uow: UnitOfWork) -> PreparedMutation:
            tag = self._repository.current_tag(uow.connection, identity)
            if tag is None or int(tag[10]) != base_revision:
                raise SomaError("INV_STALE", "Fault Tag revision changed")
            desired = action == "archive"
            if bool(int(tag[8])) == desired:
                return PreparedMutation(
                    no_change=True,
                    result_type=None,
                    result_id=None,
                    response_schema="FaultTagV1",
                    response=self._response(uow.connection, identity),
                )
            tracking_id = str(tag[1])
            member_count = len(self._repository.current_members(uow.connection, identity))

            def apply(inner: UnitOfWork):
                event_id, revision = self._repository.set_archive_state(
                    inner.connection,
                    fault_tag_id=identity,
                    base_revision=base_revision,
                    archived=desired,
                    reason_code=reason,
                    command_id=command_id,
                )
                apply.event_id = event_id
                apply.revision = revision
                return AuditEventInput(
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
                        "event_kind": "ARCHIVE" if desired else "RESTORE",
                        "member_count": member_count,
                        "resulting_revision": revision,
                        "reason_category": reason,
                    },
                    resulting_event_refs=(
                        AuditResultRef("fault_tag", identity),
                    ),
                )

            apply.event_id = ""
            apply.revision = base_revision + 1
            return PreparedMutation(
                no_change=False,
                result_type="fault_tag",
                result_id=identity,
                apply=apply,
                response_schema="FaultTagV1",
                response_factory=lambda inner: self._response(inner.connection, identity),
            )

        execution = self._boundary.execute(envelope, prepare)
        if not isinstance(execution.response, dict):
            raise IntegrityFailure("Fault Tag archive response is not an object")
        return dict(execution.response)


__all__ = ["InventoryFaultTagsService"]
