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
from ..domain.fault_tags import (
    FaultTagMembershipIntent,
    WarehouseMembershipTarget,
    validate_fault_tag_effective_at,
    validate_fault_tag_memberships,
    validate_pickup_context,
    validate_warehouse_targets,
)
from ..domain.needs import validate_reason_code
from ..domain.rmas import validate_optional_evidence
from ..repositories.fault_tags import InventoryFaultTagsRepository
from ..repositories.logistics import InventoryLogisticsRepository


class InventoryFaultTagService:
    def __init__(
        self,
        connection_factory: ConnectionFactory,
        *,
        submission_evidence_validator=None,
    ) -> None:
        self._factory = connection_factory
        self._fault_tags = InventoryFaultTagsRepository()
        self._logistics = InventoryLogisticsRepository()
        self._submission_evidence_validator = submission_evidence_validator
        self._boundary = CommandBoundary(
            connection_factory,
            AuditWriter(build_inventory_audit_registry()),
        )

    @staticmethod
    def _validate_sha256(value: str, *, field: str) -> str:
        if (
            not isinstance(value, str)
            or len(value) != 64
            or any(character not in "0123456789abcdef" for character in value)
        ):
            raise ValidationError(f"{field} must be lowercase SHA-256")
        return value

    @staticmethod
    def _inventory_response(
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
        method, location_id, contact_id, instructions = validate_pickup_context(
            return_method=return_method,
            dispatch_location_id=pickup_dispatch_location_id,
            contact_id=pickup_contact_id,
            instructions=pickup_instructions,
        )
        accepted_memberships = validate_fault_tag_memberships(memberships)
        envelope = CommandEnvelope(
            command_id=command_id,
            command_type="CreateFaultTagDraft",
            target_type="fault_tag",
            target_id=None,
            semantic_payload={
                "return_method": method,
                "pickup_dispatch_location_id": location_id,
                "pickup_contact_id": contact_id,
                "pickup_instructions": instructions,
                "memberships": [
                    {"rma_id": item.rma_id, "return_reason": item.return_reason}
                    for item in accepted_memberships
                ],
            },
        )

        def prepare(uow: UnitOfWork) -> PreparedMutation:
            if location_id is not None or contact_id is not None:
                self._logistics.reference_context(
                    uow.connection,
                    dispatch_location_id=location_id,
                    receiver_contact_id=contact_id,
                )
            for item in accepted_memberships:
                self._fault_tags.require_membership_available(
                    uow.connection,
                    rma_id=item.rma_id,
                )
            fault_tag_id = new_uuid4()

            def apply(inner: UnitOfWork):
                result = self._fault_tags.create_draft(
                    inner.connection,
                    fault_tag_id=fault_tag_id,
                    return_method=method,
                    pickup_dispatch_location_id=location_id,
                    pickup_contact_id=contact_id,
                    pickup_instructions=instructions,
                    memberships=accepted_memberships,
                    command_id=command_id,
                )
                apply.result = result
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
                        "tracking_id": str(result["tracking_id"]),
                        "event_kind": "CREATE",
                        "member_count": len(result["membership_ids"]),
                        "resulting_revision": int(result["revision"]),
                        "reason_category": None,
                    },
                    resulting_event_refs=(
                        AuditResultRef("fault_tag", fault_tag_id),
                    ),
                )

            apply.result = {}
            return PreparedMutation(
                no_change=False,
                result_type="fault_tag",
                result_id=fault_tag_id,
                apply=apply,
                response_schema="FaultTagV1",
                response_factory=lambda inner: self._fault_tags.response(
                    inner.connection,
                    fault_tag_id,
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
        expected_draft_fingerprint: str,
        return_method: str,
        add_memberships: tuple[FaultTagMembershipIntent, ...] = (),
        remove_membership_ids: tuple[str, ...] = (),
        pickup_dispatch_location_id: str | None = None,
        pickup_contact_id: str | None = None,
        pickup_instructions: str | None = None,
        actor_kind: str = "local_user",
        actor_id: str | None = None,
    ) -> dict[str, object]:
        tag_id = require_uuid4(fault_tag_id)
        if type(base_revision) is not int or base_revision <= 0:
            raise ValidationError("base_revision must be positive")
        expected_fingerprint = self._validate_sha256(
            expected_draft_fingerprint,
            field="expected_draft_fingerprint",
        )
        method, location_id, contact_id, instructions = validate_pickup_context(
            return_method=return_method,
            dispatch_location_id=pickup_dispatch_location_id,
            contact_id=pickup_contact_id,
            instructions=pickup_instructions,
        )
        additions = validate_fault_tag_memberships(add_memberships)
        if not isinstance(remove_membership_ids, tuple) or len(remove_membership_ids) > 5000:
            raise ValidationError("remove_membership_ids must be a tuple of at most 5000 UUIDs")
        removals = tuple(sorted((require_uuid4(value) for value in remove_membership_ids)))
        if len(set(removals)) != len(removals):
            raise ValidationError("remove_membership_ids contains duplicates")

        envelope = CommandEnvelope(
            command_id=command_id,
            command_type="UpdateFaultTagDraft",
            target_type="fault_tag",
            target_id=tag_id,
            semantic_payload={
                "return_method": method,
                "pickup_dispatch_location_id": location_id,
                "pickup_contact_id": contact_id,
                "pickup_instructions": instructions,
                "add_memberships": [
                    {"rma_id": item.rma_id, "return_reason": item.return_reason}
                    for item in additions
                ],
                "remove_membership_ids": list(removals),
            },
            base_revisions={"fault_tag": base_revision},
            authorizing_fingerprints={"draft": expected_fingerprint},
        )

        def prepare(uow: UnitOfWork) -> PreparedMutation:
            current = self._fault_tags.require_exact_draft(
                uow.connection,
                fault_tag_id=tag_id,
                expected_revision=base_revision,
                expected_fingerprint=expected_fingerprint,
            )
            if location_id is not None or contact_id is not None:
                self._logistics.reference_context(
                    uow.connection,
                    dispatch_location_id=location_id,
                    receiver_contact_id=contact_id,
                )
            current_members = self._fault_tags.current_members(uow.connection, tag_id)
            current_rmas = {str(item["rma_id"]) for item in current_members}
            resulting_rmas = (current_rmas - {
                str(item["rma_id"])
                for item in current_members
                if str(item["fault_tag_membership_id"]) in removals
            }) | {item.rma_id for item in additions}
            same_logistics = (
                str(current[2]) == method
                and (None if current[3] is None else str(current[3])) == location_id
                and (None if current[4] is None else str(current[4])) == contact_id
                and (None if current[5] is None else str(current[5])) == instructions
            )
            if same_logistics and not additions and not removals:
                return PreparedMutation(
                    no_change=True,
                    result_type=None,
                    result_id=None,
                    response_schema="FaultTagV1",
                    response=self._fault_tags.response(uow.connection, tag_id),
                )
            if len(resulting_rmas) > 5000:
                raise ValidationError("Fault Tag membership limit exceeded")

            def apply(inner: UnitOfWork):
                result = self._fault_tags.update_draft(
                    inner.connection,
                    fault_tag_id=tag_id,
                    expected_revision=base_revision,
                    expected_fingerprint=expected_fingerprint,
                    return_method=method,
                    pickup_dispatch_location_id=location_id,
                    pickup_contact_id=contact_id,
                    pickup_instructions=instructions,
                    add_memberships=additions,
                    remove_membership_ids=removals,
                    command_id=command_id,
                )
                apply.result = result
                response = self._fault_tags.response(inner.connection, tag_id)
                return AuditEventInput(
                    audit_event_id=new_uuid4(),
                    action_type="inventory.fault_tag.draft_changed",
                    action_version=1,
                    actor_kind=actor_kind,
                    actor_id=actor_id,
                    target_type="fault_tag",
                    target_id=tag_id,
                    command_id=command_id,
                    payload_schema="FaultTagAuditV1",
                    payload_version=1,
                    payload={
                        "fault_tag_id": tag_id,
                        "tracking_id": str(response["tracking_handle"]),
                        "event_kind": "DRAFT_UPDATE",
                        "member_count": len(response["members"]),
                        "resulting_revision": int(result["revision"]),
                        "reason_category": None,
                    },
                    resulting_event_refs=(
                        AuditResultRef("fault_tag", tag_id),
                    ),
                )

            apply.result = {}
            return PreparedMutation(
                no_change=False,
                result_type="fault_tag",
                result_id=tag_id,
                apply=apply,
                response_schema="FaultTagV1",
                response_factory=lambda inner: self._fault_tags.response(
                    inner.connection,
                    tag_id,
                ),
            )

        execution = self._boundary.execute(envelope, prepare)
        if not isinstance(execution.response, dict):
            raise IntegrityFailure("Fault Tag draft update response is not an object")
        return dict(execution.response)

    def correct_false_fault_tag_submission(
        self,
        *,
        command_id: str,
        fault_tag_id: str,
        submission_event_id: str,
        reason_code: str,
        confirmed_no_real_send: bool,
        actor_kind: str = "local_user",
        actor_id: str | None = None,
    ) -> dict[str, object]:
        tag_id = require_uuid4(fault_tag_id)
        event_id = require_uuid4(submission_event_id)
        reason = validate_reason_code(reason_code)
        if confirmed_no_real_send is not True:
            raise ValidationError(
                "confirmed_no_real_send must be true for false-submission correction"
            )
        envelope = CommandEnvelope(
            command_id=command_id,
            command_type="CorrectFalseFaultTagSubmission",
            target_type="fault_tag",
            target_id=tag_id,
            semantic_payload={
                "submission_event_id": event_id,
                "reason_code": reason,
                "confirmed_no_real_send": confirmed_no_real_send,
            },
        )

        def prepare(uow: UnitOfWork) -> PreparedMutation:
            current = self._fault_tags.current_tag(uow.connection, tag_id)
            if current is None:
                raise SomaError("INV_STALE", "Fault Tag no longer exists")
            snapshot_id = current[9]
            if snapshot_id is None:
                raise SomaError(
                    "CORRECTION_TARGET_INVALID",
                    "Fault Tag has no current submission snapshot",
                )
            snapshot = uow.connection.execute(
                "SELECT submission_event_id,effective_submission_at_utc,snapshot_hash "
                "FROM fault_tag_submission_snapshots "
                "WHERE fault_tag_submission_snapshot_id=? AND fault_tag_id=?",
                (str(snapshot_id), tag_id),
            ).fetchone()
            if snapshot is None or str(snapshot[0]) != event_id:
                raise SomaError(
                    "CORRECTION_TARGET_INVALID",
                    "Fault Tag submission event is not current",
                )
            membership_count = int(
                uow.connection.execute(
                    "SELECT COUNT(*) FROM fault_tag_membership_submission_snapshots "
                    "WHERE fault_tag_submission_snapshot_id=?",
                    (str(snapshot_id),),
                ).fetchone()[0]
            )
            snapshot_effective = None if snapshot[1] is None else int(snapshot[1])
            snapshot_hash = str(snapshot[2])

            def apply(inner: UnitOfWork):
                result = self._fault_tags.correct_false_submission(
                    inner.connection,
                    fault_tag_id=tag_id,
                    submission_event_id=event_id,
                    reason_code=reason,
                    confirmed_no_real_send=confirmed_no_real_send,
                    command_id=command_id,
                )
                apply.result = result
                return AuditEventInput(
                    audit_event_id=new_uuid4(),
                    action_type="inventory.fault_tag.submitted",
                    action_version=1,
                    actor_kind=actor_kind,
                    actor_id=actor_id,
                    target_type="fault_tag",
                    target_id=tag_id,
                    command_id=command_id,
                    reason_category=reason,
                    payload_schema="FaultTagSubmissionAuditV1",
                    payload_version=1,
                    payload={
                        "fault_tag_id": tag_id,
                        "submission_event_id": event_id,
                        "submission_snapshot_id": str(snapshot_id),
                        "event_kind": "CORRECT_FALSE",
                        "membership_count": membership_count,
                        "input_fingerprint": snapshot_hash,
                        "effective_at_utc": snapshot_effective,
                    },
                    resulting_event_refs=(
                        AuditResultRef("fault_tag_submission_snapshot", str(snapshot_id)),
                    ),
                )

            apply.result = {}
            return PreparedMutation(
                no_change=False,
                result_type="fault_tag",
                result_id=tag_id,
                apply=apply,
                response_schema="FaultTagV1",
                response_factory=lambda inner: self._fault_tags.response(
                    inner.connection,
                    tag_id,
                ),
            )

        execution = self._boundary.execute(envelope, prepare)
        if not isinstance(execution.response, dict):
            raise IntegrityFailure("Fault Tag false-submission response is not an object")
        return dict(execution.response)

    def accept_fault_tag_submission(
        self,
        *,
        command_id: str,
        fault_tag_id: str,
        base_revision: int,
        expected_draft_fingerprint: str,
        effective_submission_at_utc: int | None = None,
        evidence_kind: str | None = None,
        evidence_id: str | None = None,
        actor_kind: str = "local_user",
        actor_id: str | None = None,
    ) -> dict[str, object]:
        tag_id = require_uuid4(fault_tag_id)
        if type(base_revision) is not int or base_revision <= 0:
            raise ValidationError("base_revision must be positive")
        expected_fingerprint = self._validate_sha256(
            expected_draft_fingerprint,
            field="expected_draft_fingerprint",
        )
        effective = validate_fault_tag_effective_at(effective_submission_at_utc)
        evidence_kind_value, evidence_id_value = validate_optional_evidence(
            evidence_kind,
            evidence_id,
        )
        envelope = CommandEnvelope(
            command_id=command_id,
            command_type="AcceptFaultTagSubmission",
            target_type="fault_tag",
            target_id=tag_id,
            semantic_payload={
                "effective_submission_at_utc": effective,
                "evidence_kind": evidence_kind_value,
                "evidence_id": evidence_id_value,
            },
            base_revisions={"fault_tag": base_revision},
            authorizing_fingerprints={"draft": expected_fingerprint},
        )

        def prepare(uow: UnitOfWork) -> PreparedMutation:
            current = self._fault_tags.require_exact_draft(
                uow.connection,
                fault_tag_id=tag_id,
                expected_revision=base_revision,
                expected_fingerprint=expected_fingerprint,
            )
            if evidence_kind_value is not None:
                validator = self._submission_evidence_validator
                if validator is None:
                    raise SomaError(
                        "DEPENDENCY_INDETERMINATE",
                        "Indexed Fault Tag sent-evidence validator is unavailable",
                    )
                verdict = validator.validate_indexed_sent_evidence(
                    uow,
                    fault_tag_id=tag_id,
                    fault_tag_revision=base_revision,
                    evidence_kind=evidence_kind_value,
                    evidence_id=evidence_id_value,
                )
                if verdict == "STALE":
                    raise SomaError("PROPOSAL_STALE", "Indexed sent evidence is stale")
                if verdict != "VALID":
                    raise SomaError(
                        "DEPENDENCY_INDETERMINATE",
                        "Indexed sent evidence cannot be proven",
                    )

            if str(current[2]) == "pickup":
                if current[3] is None:
                    raise SomaError(
                        "FAULT_TAG_PICKUP_ORIGIN_REQUIRED",
                        "Pickup Fault Tag requires one pickup-origin Dispatch Location",
                    )
                pickup_context = self._logistics.reference_context(
                    uow.connection,
                    dispatch_location_id=str(current[3]),
                    receiver_contact_id=None if current[4] is None else str(current[4]),
                )
            else:
                pickup_context = self._logistics.reference_context(
                    uow.connection,
                    dispatch_location_id=None,
                    receiver_contact_id=None,
                )

            def apply(inner: UnitOfWork):
                result = self._fault_tags.accept_submission(
                    inner.connection,
                    fault_tag_id=tag_id,
                    expected_revision=base_revision,
                    expected_fingerprint=expected_fingerprint,
                    pickup_context=pickup_context,
                    effective_submission_at_utc=effective,
                    evidence_kind=evidence_kind_value,
                    evidence_id=evidence_id_value,
                    command_id=command_id,
                )
                apply.result = result
                return AuditEventInput(
                    audit_event_id=new_uuid4(),
                    action_type="inventory.fault_tag.submitted",
                    action_version=1,
                    actor_kind=actor_kind,
                    actor_id=actor_id,
                    target_type="fault_tag",
                    target_id=tag_id,
                    command_id=command_id,
                    payload_schema="FaultTagSubmissionAuditV1",
                    payload_version=1,
                    payload={
                        "fault_tag_id": tag_id,
                        "submission_event_id": str(result["submission_event_id"]),
                        "submission_snapshot_id": str(result["submission_snapshot_id"]),
                        "event_kind": "ACCEPT",
                        "membership_count": len(result["membership_snapshot_ids"]),
                        "input_fingerprint": str(result["snapshot_hash"]),
                        "effective_at_utc": effective,
                    },
                    resulting_event_refs=(
                        AuditResultRef(
                            "fault_tag_submission_snapshot",
                            str(result["submission_snapshot_id"]),
                        ),
                    ),
                )

            apply.result = {}
            return PreparedMutation(
                no_change=False,
                result_type="fault_tag",
                result_id=tag_id,
                apply=apply,
                response_schema="FaultTagV1",
                response_factory=lambda inner: self._fault_tags.response(
                    inner.connection,
                    tag_id,
                ),
            )

        execution = self._boundary.execute(envelope, prepare)
        if not isinstance(execution.response, dict):
            raise IntegrityFailure("Fault Tag submission response is not an object")
        return dict(execution.response)


    def record_warehouse_receipt(
        self,
        *,
        command_id: str,
        targets: tuple[WarehouseMembershipTarget, ...],
        effective_at_utc: int | None = None,
        evidence_kind: str | None = None,
        evidence_id: str | None = None,
        actor_kind: str = "local_user",
        actor_id: str | None = None,
    ) -> InventoryMutationResult:
        accepted_targets = validate_warehouse_targets(targets)
        effective = validate_fault_tag_effective_at(effective_at_utc)
        evidence_kind_value, evidence_id_value = validate_optional_evidence(
            evidence_kind,
            evidence_id,
        )
        if evidence_kind_value is not None:
            raise SomaError(
                "DEPENDENCY_INDETERMINATE",
                "Warehouse proposal evidence validator is unavailable",
            )
        target_pairs = tuple(
            (item.fault_tag_membership_id, item.revision)
            for item in accepted_targets
        )
        envelope = CommandEnvelope(
            command_id=command_id,
            command_type="RecordWarehouseReceipt",
            target_type="fault_tag_membership",
            target_id=accepted_targets[0].fault_tag_membership_id,
            semantic_payload={
                "targets": [
                    {
                        "fault_tag_membership_id": item.fault_tag_membership_id,
                        "revision": item.revision,
                    }
                    for item in accepted_targets
                ],
                "effective_at_utc": effective,
                "evidence_kind": evidence_kind_value,
                "evidence_id": evidence_id_value,
            },
        )

        def prepare(uow: UnitOfWork) -> PreparedMutation:
            for membership_id, revision in target_pairs:
                self._fault_tags._require_warehouse_member(
                    uow.connection,
                    membership_id=membership_id,
                    expected_revision=revision,
                    expected_state="submitted_awaiting_receipt",
                )

            def apply(inner: UnitOfWork):
                result = self._fault_tags.record_warehouse_receipt(
                    inner.connection,
                    targets=target_pairs,
                    effective_at_utc=effective,
                    evidence_kind=evidence_kind_value,
                    evidence_id=evidence_id_value,
                    command_id=command_id,
                )
                apply.result = result
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
                        batch_id=(
                            None if result["batch_id"] is None else str(result["batch_id"])
                        ),
                        payload_schema="WarehouseDecisionAuditV1",
                        payload_version=1,
                        payload={
                            "membership_id": str(item["membership_id"]),
                            "event_kind": "RECEIVED",
                            "rma_id": str(item["rma_id"]),
                            "return_obligation_id": str(item["rma_id"]),
                            "batch_id": (
                                None
                                if result["batch_id"] is None
                                else str(result["batch_id"])
                            ),
                            "effective_at_utc": effective,
                            "explicit_confirmation": False,
                        },
                        resulting_event_refs=(
                            AuditResultRef(
                                "fault_tag_membership_event",
                                str(item["membership_event_id"]),
                            ),
                            AuditResultRef("rma_return_obligation", str(item["rma_id"])),
                        ),
                    )
                    for item in result["events"]
                )

            apply.result = {}
            return PreparedMutation(
                no_change=False,
                result_type="fault_tag_membership",
                result_id=accepted_targets[0].fault_tag_membership_id,
                apply=apply,
                response_schema="InventoryMutationResultV1",
                response_factory=lambda _inner: self._inventory_response(
                    [
                        (
                            "fault_tag_membership",
                            accepted_targets[0].fault_tag_membership_id,
                        ),
                        *(
                            []
                            if apply.result["batch_id"] is None
                            else [("inventory_batch", str(apply.result["batch_id"]))]
                        ),
                        *[
                            ("fault_tag_membership_event", str(item["membership_event_id"]))
                            for item in apply.result["events"]
                        ],
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
        targets: tuple[WarehouseMembershipTarget, ...],
        decision: str,
        explicit_confirmation: bool,
        reason_code: str | None = None,
        effective_at_utc: int | None = None,
        evidence_kind: str | None = None,
        evidence_id: str | None = None,
        actor_kind: str = "local_user",
        actor_id: str | None = None,
    ) -> InventoryMutationResult:
        accepted_targets = validate_warehouse_targets(targets)
        if decision not in {"accepted", "rejected"}:
            raise ValidationError("warehouse decision must be accepted or rejected")
        if explicit_confirmation is not True:
            raise SomaError(
                "WAREHOUSE_FINAL_CONFIRMATION_REQUIRED",
                "Warehouse final decision requires explicit operator confirmation",
            )
        if decision == "rejected":
            if reason_code is None:
                raise ValidationError("warehouse rejection requires reason_code")
            reason = validate_reason_code(reason_code)
        else:
            if reason_code is not None:
                raise ValidationError("warehouse acceptance does not accept rejection reason_code")
            reason = None
        effective = validate_fault_tag_effective_at(effective_at_utc)
        evidence_kind_value, evidence_id_value = validate_optional_evidence(
            evidence_kind,
            evidence_id,
        )
        if evidence_kind_value is not None:
            raise SomaError(
                "DEPENDENCY_INDETERMINATE",
                "Warehouse proposal evidence validator is unavailable",
            )
        target_pairs = tuple(
            (item.fault_tag_membership_id, item.revision)
            for item in accepted_targets
        )
        envelope = CommandEnvelope(
            command_id=command_id,
            command_type="RecordWarehouseFinalDecision",
            target_type="fault_tag_membership",
            target_id=accepted_targets[0].fault_tag_membership_id,
            semantic_payload={
                "targets": [
                    {
                        "fault_tag_membership_id": item.fault_tag_membership_id,
                        "revision": item.revision,
                    }
                    for item in accepted_targets
                ],
                "decision": decision,
                "explicit_confirmation": True,
                "reason_code": reason,
                "effective_at_utc": effective,
                "evidence_kind": evidence_kind_value,
                "evidence_id": evidence_id_value,
            },
        )

        def prepare(uow: UnitOfWork) -> PreparedMutation:
            for membership_id, revision in target_pairs:
                self._fault_tags._require_warehouse_member(
                    uow.connection,
                    membership_id=membership_id,
                    expected_revision=revision,
                    expected_state="warehouse_received",
                )

            def apply(inner: UnitOfWork):
                result = self._fault_tags.record_warehouse_final_decision(
                    inner.connection,
                    targets=target_pairs,
                    decision=decision,
                    reason_code=reason,
                    effective_at_utc=effective,
                    evidence_kind=evidence_kind_value,
                    evidence_id=evidence_id_value,
                    command_id=command_id,
                )
                apply.result = result
                audit_kind = "ACCEPTED" if decision == "accepted" else "REJECTED"
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
                        batch_id=(
                            None if result["batch_id"] is None else str(result["batch_id"])
                        ),
                        payload_schema="WarehouseDecisionAuditV1",
                        payload_version=1,
                        payload={
                            "membership_id": str(item["membership_id"]),
                            "event_kind": audit_kind,
                            "rma_id": str(item["rma_id"]),
                            "return_obligation_id": str(item["rma_id"]),
                            "batch_id": (
                                None
                                if result["batch_id"] is None
                                else str(result["batch_id"])
                            ),
                            "effective_at_utc": effective,
                            "explicit_confirmation": True,
                        },
                        resulting_event_refs=(
                            AuditResultRef(
                                "fault_tag_membership_event",
                                str(item["membership_event_id"]),
                            ),
                            AuditResultRef("rma_return_obligation", str(item["rma_id"])),
                        ),
                    )
                    for item in result["events"]
                )

            apply.result = {}
            return PreparedMutation(
                no_change=False,
                result_type="fault_tag_membership",
                result_id=accepted_targets[0].fault_tag_membership_id,
                apply=apply,
                response_schema="InventoryMutationResultV1",
                response_factory=lambda _inner: self._inventory_response(
                    [
                        (
                            "fault_tag_membership",
                            accepted_targets[0].fault_tag_membership_id,
                        ),
                        *(
                            []
                            if apply.result["batch_id"] is None
                            else [("inventory_batch", str(apply.result["batch_id"]))]
                        ),
                        *[
                            ("fault_tag_membership_event", str(item["membership_event_id"]))
                            for item in apply.result["events"]
                        ],
                        *[
                            ("rma_return_obligation", str(item["rma_id"]))
                            for item in apply.result["events"]
                        ],
                    ],
                    {
                        **{
                            f"fault_tag_membership:{item['membership_id']}": int(
                                item["membership_revision"]
                            )
                            for item in apply.result["events"]
                        },
                        **{
                            f"rma_return_obligation:{item['rma_id']}": int(
                                item["obligation_revision"]
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
                    },
                ),
            )

        return inventory_mutation_result_from_execution(
            self._boundary.execute(envelope, prepare)
        )


    def create_fault_tag_replacement(
        self,
        *,
        command_id: str,
        predecessor_fault_tag_id: str,
        expected_predecessor_revision: int,
        expected_lineage_fingerprint: str,
        return_method: str,
        memberships: tuple[FaultTagMembershipIntent, ...],
        reason_code: str,
        pickup_dispatch_location_id: str | None = None,
        pickup_contact_id: str | None = None,
        pickup_instructions: str | None = None,
        actor_kind: str = "local_user",
        actor_id: str | None = None,
    ) -> dict[str, object]:
        predecessor_id = require_uuid4(predecessor_fault_tag_id)
        if type(expected_predecessor_revision) is not int or expected_predecessor_revision <= 0:
            raise ValidationError("expected_predecessor_revision must be positive")
        lineage_fingerprint = self._validate_sha256(
            expected_lineage_fingerprint,
            field="expected_lineage_fingerprint",
        )
        method, location_id, contact_id, instructions = validate_pickup_context(
            return_method=return_method,
            dispatch_location_id=pickup_dispatch_location_id,
            contact_id=pickup_contact_id,
            instructions=pickup_instructions,
        )
        accepted_memberships = validate_fault_tag_memberships(memberships)
        if not accepted_memberships:
            raise ValidationError("Fault Tag replacement requires at least one membership")
        reason = validate_reason_code(reason_code)
        envelope = CommandEnvelope(
            command_id=command_id,
            command_type="CreateFaultTagReplacement",
            target_type="fault_tag",
            target_id=predecessor_id,
            semantic_payload={
                "expected_predecessor_revision": expected_predecessor_revision,
                "return_method": method,
                "pickup_dispatch_location_id": location_id,
                "pickup_contact_id": contact_id,
                "pickup_instructions": instructions,
                "memberships": [
                    {"rma_id": item.rma_id, "return_reason": item.return_reason}
                    for item in accepted_memberships
                ],
                "reason_code": reason,
            },
            base_revisions={"fault_tag": expected_predecessor_revision},
            authorizing_fingerprints={"lineage": lineage_fingerprint},
        )

        def prepare(uow: UnitOfWork) -> PreparedMutation:
            authority = self._fault_tags.lineage_authority(
                uow.connection,
                predecessor_id,
            )
            if (
                int(authority["projection_revision"]) != expected_predecessor_revision
                or str(authority["fingerprint"]) != lineage_fingerprint
            ):
                raise SomaError("INV_STALE", "Fault Tag replacement authority changed")
            if location_id is not None or contact_id is not None:
                self._logistics.reference_context(
                    uow.connection,
                    dispatch_location_id=location_id,
                    receiver_contact_id=contact_id,
                )
            for item in accepted_memberships:
                self._fault_tags.require_membership_available(
                    uow.connection,
                    rma_id=item.rma_id,
                    allow_fault_tag_id=predecessor_id,
                )
            successor_id = new_uuid4()

            def apply(inner: UnitOfWork):
                result = self._fault_tags.create_replacement(
                    inner.connection,
                    predecessor_fault_tag_id=predecessor_id,
                    expected_predecessor_revision=expected_predecessor_revision,
                    expected_lineage_fingerprint=lineage_fingerprint,
                    successor_fault_tag_id=successor_id,
                    return_method=method,
                    pickup_dispatch_location_id=location_id,
                    pickup_contact_id=contact_id,
                    pickup_instructions=instructions,
                    memberships=accepted_memberships,
                    reason_code=reason,
                    command_id=command_id,
                )
                apply.result = result
                return AuditEventInput(
                    audit_event_id=new_uuid4(),
                    action_type="inventory.fault_tag.replacement_or_resend_created",
                    action_version=1,
                    actor_kind=actor_kind,
                    actor_id=actor_id,
                    target_type="fault_tag",
                    target_id=predecessor_id,
                    command_id=command_id,
                    reason_category=reason,
                    payload_schema="FaultTagLineageAuditV1",
                    payload_version=1,
                    payload={
                        "predecessor_fault_tag_id": predecessor_id,
                        "successor_fault_tag_id": successor_id,
                        "lineage_kind": "CORRECTS_REPLACES",
                        "membership_scope_fingerprint": str(
                            result["membership_scope_fingerprint"]
                        ),
                        "reason_category": reason,
                        "resulting_revision": int(result["revision"]),
                    },
                    resulting_event_refs=(
                        AuditResultRef("fault_tag", successor_id),
                        AuditResultRef("fault_tag_lineage", str(result["lineage_id"])),
                    ),
                )

            apply.result = {}
            return PreparedMutation(
                no_change=False,
                result_type="fault_tag",
                result_id=successor_id,
                apply=apply,
                response_schema="FaultTagV1",
                response_factory=lambda inner: self._fault_tags.response(
                    inner.connection,
                    successor_id,
                ),
            )

        execution = self._boundary.execute(envelope, prepare)
        if not isinstance(execution.response, dict):
            raise IntegrityFailure("Fault Tag replacement response is not an object")
        return dict(execution.response)

    def create_fault_tag_resend(
        self,
        *,
        command_id: str,
        predecessor_fault_tag_id: str,
        expected_lineage_fingerprint: str,
        return_method: str,
        memberships: tuple[FaultTagMembershipIntent, ...],
        reason_code: str,
        pickup_dispatch_location_id: str | None = None,
        pickup_contact_id: str | None = None,
        pickup_instructions: str | None = None,
        actor_kind: str = "local_user",
        actor_id: str | None = None,
    ) -> dict[str, object]:
        predecessor_id = require_uuid4(predecessor_fault_tag_id)
        lineage_fingerprint = self._validate_sha256(
            expected_lineage_fingerprint,
            field="expected_lineage_fingerprint",
        )
        method, location_id, contact_id, instructions = validate_pickup_context(
            return_method=return_method,
            dispatch_location_id=pickup_dispatch_location_id,
            contact_id=pickup_contact_id,
            instructions=pickup_instructions,
        )
        accepted_memberships = validate_fault_tag_memberships(memberships)
        if not accepted_memberships:
            raise ValidationError("Fault Tag resend requires at least one membership")
        reason = validate_reason_code(reason_code)
        envelope = CommandEnvelope(
            command_id=command_id,
            command_type="CreateFaultTagResend",
            target_type="fault_tag",
            target_id=predecessor_id,
            semantic_payload={
                "return_method": method,
                "pickup_dispatch_location_id": location_id,
                "pickup_contact_id": contact_id,
                "pickup_instructions": instructions,
                "memberships": [
                    {"rma_id": item.rma_id, "return_reason": item.return_reason}
                    for item in accepted_memberships
                ],
                "reason_code": reason,
            },
            authorizing_fingerprints={"lineage": lineage_fingerprint},
        )

        def prepare(uow: UnitOfWork) -> PreparedMutation:
            authority = self._fault_tags.lineage_authority(
                uow.connection,
                predecessor_id,
            )
            if str(authority["fingerprint"]) != lineage_fingerprint:
                raise SomaError("INV_STALE", "Fault Tag resend authority changed")
            if location_id is not None or contact_id is not None:
                self._logistics.reference_context(
                    uow.connection,
                    dispatch_location_id=location_id,
                    receiver_contact_id=contact_id,
                )
            successor_id = new_uuid4()

            def apply(inner: UnitOfWork):
                result = self._fault_tags.create_resend(
                    inner.connection,
                    predecessor_fault_tag_id=predecessor_id,
                    expected_lineage_fingerprint=lineage_fingerprint,
                    successor_fault_tag_id=successor_id,
                    return_method=method,
                    pickup_dispatch_location_id=location_id,
                    pickup_contact_id=contact_id,
                    pickup_instructions=instructions,
                    memberships=accepted_memberships,
                    reason_code=reason,
                    command_id=command_id,
                )
                apply.result = result
                return AuditEventInput(
                    audit_event_id=new_uuid4(),
                    action_type="inventory.fault_tag.replacement_or_resend_created",
                    action_version=1,
                    actor_kind=actor_kind,
                    actor_id=actor_id,
                    target_type="fault_tag",
                    target_id=predecessor_id,
                    command_id=command_id,
                    reason_category=reason,
                    payload_schema="FaultTagLineageAuditV1",
                    payload_version=1,
                    payload={
                        "predecessor_fault_tag_id": predecessor_id,
                        "successor_fault_tag_id": successor_id,
                        "lineage_kind": "RESEND_OF",
                        "membership_scope_fingerprint": str(
                            result["membership_scope_fingerprint"]
                        ),
                        "reason_category": reason,
                        "resulting_revision": int(result["revision"]),
                    },
                    resulting_event_refs=(
                        AuditResultRef("fault_tag", successor_id),
                        AuditResultRef("fault_tag_lineage", str(result["lineage_id"])),
                    ),
                )

            apply.result = {}
            return PreparedMutation(
                no_change=False,
                result_type="fault_tag",
                result_id=successor_id,
                apply=apply,
                response_schema="FaultTagV1",
                response_factory=lambda inner: self._fault_tags.response(
                    inner.connection,
                    successor_id,
                ),
            )

        execution = self._boundary.execute(envelope, prepare)
        if not isinstance(execution.response, dict):
            raise IntegrityFailure("Fault Tag resend response is not an object")
        return dict(execution.response)


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
        tag_id = require_uuid4(fault_tag_id)
        if type(base_revision) is not int or base_revision <= 0:
            raise ValidationError("base_revision must be positive")
        if action not in {"archive", "restore"}:
            raise ValidationError("Fault Tag archive action must be archive or restore")
        if action == "archive":
            if reason_code is None:
                raise ValidationError("Fault Tag archive requires reason_code")
            reason = validate_reason_code(reason_code)
        else:
            if reason_code is not None:
                raise ValidationError("Fault Tag restore does not accept reason_code")
            reason = None
        envelope = CommandEnvelope(
            command_id=command_id,
            command_type="ArchiveOrRestoreFaultTag",
            target_type="fault_tag",
            target_id=tag_id,
            semantic_payload={"action": action, "reason_code": reason},
            base_revisions={"fault_tag": base_revision},
        )

        def prepare(uow: UnitOfWork) -> PreparedMutation:
            current = self._fault_tags.current_tag(uow.connection, tag_id)
            if current is None or int(current[15]) != base_revision:
                raise SomaError("INV_STALE", "Fault Tag revision changed")
            target_archived = action == "archive"
            if bool(current[8]) == target_archived:
                return PreparedMutation(
                    no_change=True,
                    result_type=None,
                    result_id=None,
                    response_schema="FaultTagV1",
                    response=self._fault_tags.response(uow.connection, tag_id),
                )
            tracking_id = str(current[1])

            def apply(inner: UnitOfWork):
                result = self._fault_tags.archive_or_restore(
                    inner.connection,
                    fault_tag_id=tag_id,
                    expected_revision=base_revision,
                    action=action,
                    reason_code=reason,
                    command_id=command_id,
                )
                apply.result = result
                return AuditEventInput(
                    audit_event_id=new_uuid4(),
                    action_type="inventory.fault_tag.draft_changed",
                    action_version=1,
                    actor_kind=actor_kind,
                    actor_id=actor_id,
                    target_type="fault_tag",
                    target_id=tag_id,
                    command_id=command_id,
                    reason_category=reason,
                    payload_schema="FaultTagAuditV1",
                    payload_version=1,
                    payload={
                        "fault_tag_id": tag_id,
                        "tracking_id": tracking_id,
                        "event_kind": "ARCHIVE" if action == "archive" else "RESTORE",
                        "member_count": len(self._fault_tags.current_members(inner.connection, tag_id)),
                        "resulting_revision": int(result["revision"]),
                        "reason_category": reason,
                    },
                    resulting_event_refs=(AuditResultRef("fault_tag", tag_id),),
                )

            apply.result = {}
            return PreparedMutation(
                no_change=False,
                result_type="fault_tag",
                result_id=tag_id,
                apply=apply,
                response_schema="FaultTagV1",
                response_factory=lambda inner: self._fault_tags.response(inner.connection, tag_id),
            )

        execution = self._boundary.execute(envelope, prepare)
        if not isinstance(execution.response, dict):
            raise IntegrityFailure("Fault Tag archive response is not an object")
        return dict(execution.response)


__all__ = ["InventoryFaultTagService"]
