from __future__ import annotations

import regex

from soma.foundation.application.command_boundary import (
    CommandBoundary,
    CommandEnvelope,
    PreparedMutation,
)
from soma.foundation.audit.writer import AuditEventInput, AuditResultRef, AuditWriter
from soma.foundation.errors import IntegrityFailure, SomaError, ValidationError
from soma.foundation.identifiers import new_uuid4, require_uuid4
from soma.foundation.persistence.connections import ConnectionFactory
from soma.foundation.persistence.uow import ReadSnapshot, UnitOfWork
from soma.foundation.strict_json import canonical_json_bytes, loads_canonical_json, sha256_canonical_json

from ..audit_registry import build_inventory_audit_registry
from ..contracts.inventory import (
    InventoryMutationResult,
    inventory_mutation_result_from_execution,
)
from ..domain.needs import validate_reason_code
from ..domain.rmas import (
    RmaAuthorizationIntent,
    validate_authorization_time,
    validate_c10,
    validate_optional_evidence,
    validate_rma_authorization_batch,
)
from ..domain.requests import (
    SpareRequestAllocationIntent,
    validate_allocation_intents,
    validate_logistics_mode,
    validate_positive_revision,
    validate_request_origin,
    validate_submission_evidence,
    validate_submission_time,
    validate_sr7,
    validate_sr7_action,
)
from ..interfaces import SpareRequestSubmissionEvidenceValidator
from ..repositories.requests import InventoryRequestsRepository
from ..repositories.rmas import InventoryRmasRepository


def _requester_context(
    *,
    contact_id: str,
    display_name: str,
    revision: int,
    affiliation_id: str | None,
    customer_org_id: str | None,
) -> dict[str, object]:
    if not display_name or len(display_name.encode("utf-8", errors="strict")) > 2000:
        raise ValidationError("Requester display-name snapshot exceeds Inventory bound")
    if len(regex.findall(r"\X", display_name)) > 500:
        raise ValidationError("Requester display-name snapshot exceeds Inventory grapheme bound")
    return {
        "contact_id": contact_id,
        "contact_revision_at_creation": revision,
        "affiliation_id_at_creation": affiliation_id,
        "customer_org_id_at_creation": customer_org_id,
        "display_name_snapshot": display_name,
    }


def _require_sha256(value: str, *, field: str) -> str:
    if not isinstance(value, str) or regex.fullmatch(r"[0-9a-f]{64}", value) is None:
        raise ValidationError(f"{field} must be lowercase SHA-256 hex")
    return value


def _transport_request_state(value: str) -> str:
    mapping = {
        "draft": "draft",
        "submitted_awaiting_response": "submitted",
        "acknowledged": "submitted",
        "partially_authorized": "authorizing",
        "authorized": "authorized",
        "cancelled": "terminal",
        "rejected": "terminal",
    }
    try:
        return mapping[value]
    except KeyError as exc:
        raise IntegrityFailure("Spare Request projection state is invalid") from exc


class InventoryRequestsRmaService:
    def __init__(
        self,
        connection_factory: ConnectionFactory,
        submission_evidence_validator: SpareRequestSubmissionEvidenceValidator | None = None,
    ) -> None:
        self._factory = connection_factory
        self._repository = InventoryRequestsRepository()
        self._rmas = InventoryRmasRepository()
        self._submission_evidence_validator = submission_evidence_validator
        self._boundary = CommandBoundary(
            connection_factory,
            AuditWriter(build_inventory_audit_registry()),
        )

    @staticmethod
    def _response(connection, spare_request_id: str) -> dict[str, object]:
        row = InventoryRequestsRepository.current_detail(
            connection,
            spare_request_id,
        )
        if row is None:
            raise IntegrityFailure("Spare Request disappeared after accepted mutation")
        requester = loads_canonical_json(
            str(row[4]),
            max_bytes=4096,
            max_depth=3,
            max_collection_items=16,
        )
        if not isinstance(requester, dict):
            raise IntegrityFailure("Persisted requester context is not an object")
        return {
            "spare_request_id": str(row[0]),
            "local_handle": str(row[1]),
            "official_sr7": None if row[7] is None else str(row[7]),
            "requester": requester,
            "state": _transport_request_state(str(row[6])),
            "revision": int(row[8]),
        }

    @staticmethod
    def _inventory_response(
        refs: list[tuple[str, str]],
        revisions: dict[str, int],
        *,
        outcome: str = "APPLIED",
    ) -> dict[str, object]:
        return {
            "outcome": outcome,
            "target_refs": [
                {"type": result_type, "id": result_id}
                for result_type, result_id in refs
            ],
            "revisions": dict(revisions),
        }

    def create_spare_request_draft(
        self,
        *,
        command_id: str,
        service_request_id: str,
        requester_contact_id: str,
        allocations: tuple[SpareRequestAllocationIntent, ...],
        mode: str,
        receiver_contact_id: str,
        dispatch_location_id: str,
        origin: str = "soma_draft",
        actor_kind: str = "local_user",
        actor_id: str | None = None,
    ) -> dict[str, object]:
        sr_id = require_uuid4(service_request_id)
        requester_id = require_uuid4(requester_contact_id)
        receiver_id = require_uuid4(receiver_contact_id)
        location_id = require_uuid4(dispatch_location_id)
        accepted_allocations = validate_allocation_intents(allocations)
        logistics_mode = validate_logistics_mode(mode)
        creation_origin = validate_request_origin(origin)
        allocation_pairs = tuple(
            (item.spare_need_id, item.quantity)
            for item in accepted_allocations
        )

        with ReadSnapshot(self._factory) as snapshot:
            authority = self._repository.requester_authority(
                snapshot.connection,
                requester_id,
            )
            if authority is None or str(authority[3]) != "active":
                raise SomaError(
                    "REQUEST_SUBMISSION_INVALID",
                    "Requester Contact is not active",
                )
            context = _requester_context(
                contact_id=requester_id,
                display_name=str(authority[1]),
                revision=int(authority[2]),
                affiliation_id=None if authority[4] is None else str(authority[4]),
                customer_org_id=None if authority[5] is None else str(authority[5]),
            )
            self._repository.require_receiver_and_location(
                snapshot.connection,
                receiver_contact_id=receiver_id,
                dispatch_location_id=location_id,
            )
            self._repository.require_sr_need_allocations(
                snapshot.connection,
                service_request_id=sr_id,
                allocations=allocation_pairs,
            )

        requester_context_json = canonical_json_bytes(context).decode("utf-8")
        requester_context_fingerprint = sha256_canonical_json(context)
        envelope = CommandEnvelope(
            command_id=command_id,
            command_type="CreateSpareRequestDraft",
            target_type="spare_request",
            target_id=None,
            semantic_payload={
                "service_request_id": sr_id,
                "requester_contact_id": requester_id,
                "allocations": [
                    {"spare_need_id": need_id, "quantity": quantity}
                    for need_id, quantity in allocation_pairs
                ],
                "mode": logistics_mode,
                "receiver_contact_id": receiver_id,
                "dispatch_location_id": location_id,
                "origin": creation_origin,
            },
            authorizing_fingerprints={
                "requester_context": requester_context_fingerprint,
            },
        )

        def prepare(uow: UnitOfWork) -> PreparedMutation:
            self._repository.require_requester_authority(
                uow.connection,
                contact_id=requester_id,
                expected_revision=int(context["contact_revision_at_creation"]),
                expected_name=str(context["display_name_snapshot"]),
                expected_affiliation_id=context["affiliation_id_at_creation"],
                expected_customer_org_id=context["customer_org_id_at_creation"],
            )
            self._repository.require_receiver_and_location(
                uow.connection,
                receiver_contact_id=receiver_id,
                dispatch_location_id=location_id,
            )
            self._repository.require_sr_need_allocations(
                uow.connection,
                service_request_id=sr_id,
                allocations=allocation_pairs,
            )
            spare_request_id = new_uuid4()

            def apply(inner: UnitOfWork):
                self._repository.require_requester_authority(
                    inner.connection,
                    contact_id=requester_id,
                    expected_revision=int(context["contact_revision_at_creation"]),
                    expected_name=str(context["display_name_snapshot"]),
                    expected_affiliation_id=context["affiliation_id_at_creation"],
                    expected_customer_org_id=context["customer_org_id_at_creation"],
                )
                self._repository.require_receiver_and_location(
                    inner.connection,
                    receiver_contact_id=receiver_id,
                    dispatch_location_id=location_id,
                )
                self._repository.require_sr_need_allocations(
                    inner.connection,
                    service_request_id=sr_id,
                    allocations=allocation_pairs,
                )
                tracking_sequence, tracking_id = (
                    self._repository.allocate_spare_request_tracking(
                        inner.connection,
                        command_id,
                    )
                )
                event_id, allocation_ids, revision = self._repository.insert_draft(
                    inner.connection,
                    spare_request_id=spare_request_id,
                    tracking_sequence=tracking_sequence,
                    tracking_id=tracking_id,
                    service_request_id=sr_id,
                    requester_contact_id=requester_id,
                    requester_context_json=requester_context_json,
                    creation_origin=creation_origin,
                    allocations=allocation_pairs,
                    mode=logistics_mode,
                    receiver_contact_id=receiver_id,
                    dispatch_location_id=location_id,
                    command_id=command_id,
                )
                apply.tracking_id = tracking_id
                apply.event_id = event_id
                apply.allocation_ids = allocation_ids
                apply.revision = revision
                refs = [
                    AuditResultRef("spare_request", spare_request_id),
                ]
                refs.extend(
                    AuditResultRef("spare_request_allocation", allocation_id)
                    for allocation_id in allocation_ids
                )
                return AuditEventInput(
                    audit_event_id=new_uuid4(),
                    action_type="inventory.spare_request.draft_changed",
                    action_version=1,
                    actor_kind=actor_kind,
                    actor_id=actor_id,
                    target_type="spare_request",
                    target_id=spare_request_id,
                    command_id=command_id,
                    payload_schema="SpareRequestAuditV1",
                    payload_version=1,
                    payload={
                        "spare_request_id": spare_request_id,
                        "tracking_id": tracking_id,
                        "event_kind": "CREATE",
                        "requester_contact_id": requester_id,
                        "requester_context_fingerprint": requester_context_fingerprint,
                        "resulting_revision": revision,
                        "allocation_count": len(allocation_pairs),
                        "reason_category": None,
                    },
                    resulting_event_refs=tuple(refs),
                )

            apply.tracking_id = ""
            apply.event_id = ""
            apply.allocation_ids = ()
            apply.revision = 1
            return PreparedMutation(
                no_change=False,
                result_type="spare_request",
                result_id=spare_request_id,
                apply=apply,
                response_schema="SpareRequestV1",
                response_factory=lambda inner: self._response(
                    inner.connection,
                    spare_request_id,
                ),
            )

        execution = self._boundary.execute(envelope, prepare)
        if not isinstance(execution.response, dict):
            raise IntegrityFailure("Spare Request response is not an object")
        return dict(execution.response)


    def update_spare_request_draft(
        self,
        *,
        command_id: str,
        spare_request_id: str,
        base_revision: int,
        allocations: tuple[SpareRequestAllocationIntent, ...],
        mode: str,
        receiver_contact_id: str,
        dispatch_location_id: str,
        actor_kind: str = "local_user",
        actor_id: str | None = None,
    ) -> dict[str, object]:
        request_id = require_uuid4(spare_request_id)
        revision = validate_positive_revision(base_revision, field="base_revision")
        receiver_id = require_uuid4(receiver_contact_id)
        location_id = require_uuid4(dispatch_location_id)
        accepted_allocations = validate_allocation_intents(allocations)
        allocation_pairs = tuple(
            (item.spare_need_id, item.quantity)
            for item in accepted_allocations
        )
        logistics_mode = validate_logistics_mode(mode)

        envelope = CommandEnvelope(
            command_id=command_id,
            command_type="UpdateSpareRequestDraft",
            target_type="spare_request",
            target_id=request_id,
            semantic_payload={
                "allocations": [
                    {"spare_need_id": need_id, "quantity": quantity}
                    for need_id, quantity in allocation_pairs
                ],
                "mode": logistics_mode,
                "receiver_contact_id": receiver_id,
                "dispatch_location_id": location_id,
            },
            base_revisions={"spare_request": revision},
        )

        def prepare(uow: UnitOfWork) -> PreparedMutation:
            material = self._repository.draft_material(
                uow.connection,
                request_id,
            )
            if material["lifecycle_state"] != "draft":
                raise SomaError("REQUEST_NOT_DRAFT", "Spare Request is not editable Draft")
            if int(material["revision"]) != revision:
                raise SomaError("INV_STALE", "Spare Request revision changed")
            self._repository.require_sr_need_allocations(
                uow.connection,
                service_request_id=str(material["service_request_id"]),
                allocations=allocation_pairs,
            )
            self._repository.require_receiver_and_location(
                uow.connection,
                receiver_contact_id=receiver_id,
                dispatch_location_id=location_id,
            )
            current_pairs = tuple(
                sorted(
                    (
                        str(item["spare_need_id"]),
                        int(item["quantity"]),
                    )
                    for item in material["allocations"]
                )
            )
            requested_pairs = tuple(sorted(allocation_pairs))
            if (
                current_pairs == requested_pairs
                and str(material["mode"]) == logistics_mode
                and str(material["receiver_contact_id"]) == receiver_id
                and str(material["dispatch_location_id"]) == location_id
            ):
                return PreparedMutation(
                    no_change=True,
                    result_type=None,
                    result_id=None,
                    response_schema="SpareRequestV1",
                    response=self._response(uow.connection, request_id),
                )

            requester_context = loads_canonical_json(
                str(material["requester_context_json"]),
                max_bytes=4096,
                max_depth=3,
                max_collection_items=16,
            )
            if not isinstance(requester_context, dict):
                raise IntegrityFailure("Persisted requester context is invalid")
            requester_context_fingerprint = sha256_canonical_json(requester_context)

            def apply(inner: UnitOfWork):
                allocation_ids, resulting_revision = self._repository.replace_draft(
                    inner.connection,
                    spare_request_id=request_id,
                    base_revision=revision,
                    allocations=allocation_pairs,
                    mode=logistics_mode,
                    receiver_contact_id=receiver_id,
                    dispatch_location_id=location_id,
                    command_id=command_id,
                )
                apply.allocation_ids = allocation_ids
                apply.revision = resulting_revision
                refs = [AuditResultRef("spare_request", request_id)]
                refs.extend(
                    AuditResultRef("spare_request_allocation", allocation_id)
                    for allocation_id in allocation_ids
                )
                return AuditEventInput(
                    audit_event_id=new_uuid4(),
                    action_type="inventory.spare_request.draft_changed",
                    action_version=1,
                    actor_kind=actor_kind,
                    actor_id=actor_id,
                    target_type="spare_request",
                    target_id=request_id,
                    command_id=command_id,
                    payload_schema="SpareRequestAuditV1",
                    payload_version=1,
                    payload={
                        "spare_request_id": request_id,
                        "tracking_id": str(material["tracking_id"]),
                        "event_kind": "DRAFT_UPDATE",
                        "requester_contact_id": str(material["requester_contact_id"]),
                        "requester_context_fingerprint": requester_context_fingerprint,
                        "resulting_revision": resulting_revision,
                        "allocation_count": len(allocation_pairs),
                        "reason_category": None,
                    },
                    resulting_event_refs=tuple(refs),
                )

            apply.allocation_ids = ()
            apply.revision = revision + 1
            return PreparedMutation(
                no_change=False,
                result_type="spare_request",
                result_id=request_id,
                apply=apply,
                response_schema="SpareRequestV1",
                response_factory=lambda inner: self._response(
                    inner.connection,
                    request_id,
                ),
            )

        execution = self._boundary.execute(envelope, prepare)
        if not isinstance(execution.response, dict):
            raise IntegrityFailure("Spare Request Draft response is not an object")
        return dict(execution.response)

    def accept_spare_request_submission(
        self,
        *,
        command_id: str,
        spare_request_id: str,
        base_revision: int,
        expected_draft_fingerprint: str,
        effective_submission_at_utc: int | None = None,
        evidence_kind: str | None = None,
        evidence_id: str | None = None,
        actor_kind: str = "local_user",
        actor_id: str | None = None,
    ) -> dict[str, object]:
        request_id = require_uuid4(spare_request_id)
        revision = validate_positive_revision(base_revision, field="base_revision")
        expected_fingerprint = _require_sha256(
            expected_draft_fingerprint,
            field="expected_draft_fingerprint",
        )
        effective = validate_submission_time(effective_submission_at_utc)
        evidence_kind_value, evidence_id_value = validate_submission_evidence(
            evidence_kind,
            evidence_id,
        )

        with ReadSnapshot(self._factory) as snapshot:
            material = self._repository.draft_material(
                snapshot.connection,
                request_id,
            )
            if material["lifecycle_state"] != "draft":
                raise SomaError("REQUEST_NOT_DRAFT", "Spare Request is not editable Draft")
            if (
                int(material["revision"]) != revision
                or str(material["input_fingerprint"]) != expected_fingerprint
            ):
                raise SomaError("INV_STALE", "Spare Request Draft changed")
            recipient_context = self._repository.submission_reference_context(
                snapshot.connection,
                receiver_contact_id=str(material["receiver_contact_id"]),
                dispatch_location_id=str(material["dispatch_location_id"]),
            )

        context_fingerprint = sha256_canonical_json(recipient_context)
        envelope = CommandEnvelope(
            command_id=command_id,
            command_type="AcceptSpareRequestSubmission",
            target_type="spare_request",
            target_id=request_id,
            semantic_payload={
                "effective_submission_at_utc": effective,
                "evidence_kind": evidence_kind_value,
                "evidence_id": evidence_id_value,
            },
            base_revisions={"spare_request": revision},
            authorizing_fingerprints={
                "draft": expected_fingerprint,
                "recipient_context": context_fingerprint,
            },
        )

        def prepare(uow: UnitOfWork) -> PreparedMutation:
            material_now = self._repository.draft_material(
                uow.connection,
                request_id,
            )
            if material_now["lifecycle_state"] != "draft":
                raise SomaError("REQUEST_NOT_DRAFT", "Spare Request is not editable Draft")
            if (
                int(material_now["revision"]) != revision
                or str(material_now["input_fingerprint"]) != expected_fingerprint
            ):
                raise SomaError("INV_STALE", "Spare Request Draft changed before submission")
            self._repository.require_submission_reference_context(
                uow.connection,
                expected=recipient_context,
            )
            if evidence_kind_value is not None and evidence_id_value is not None:
                validator = self._submission_evidence_validator
                if validator is None:
                    raise SomaError(
                        "DEPENDENCY_INDETERMINATE",
                        "Indexed sent evidence validator is unavailable",
                    )
                verdict = validator.validate_indexed_sent_evidence(
                    uow,
                    spare_request_id=request_id,
                    spare_request_revision=revision,
                    evidence_kind=evidence_kind_value,
                    evidence_id=evidence_id_value,
                )
                if verdict == "STALE":
                    raise SomaError("PROPOSAL_STALE", "Indexed sent evidence is stale")
                if verdict == "INVALID":
                    raise SomaError(
                        "REQUEST_SUBMISSION_INVALID",
                        "Indexed sent evidence does not authorize this submission",
                    )
                if verdict != "VALID":
                    raise SomaError(
                        "DEPENDENCY_INDETERMINATE",
                        "Indexed sent evidence cannot be proven",
                    )

            def apply(inner: UnitOfWork):
                (
                    submission_event_id,
                    submission_snapshot_id,
                    submission_allocation_ids,
                    snapshot_hash,
                    resulting_revision,
                    warning_start,
                ) = self._repository.accept_submission(
                    inner.connection,
                    spare_request_id=request_id,
                    base_revision=revision,
                    expected_draft_fingerprint=expected_fingerprint,
                    recipient_context=recipient_context,
                    effective_submission_at_utc=effective,
                    evidence_kind=evidence_kind_value,
                    evidence_id=evidence_id_value,
                    command_id=command_id,
                )
                apply.submission_event_id = submission_event_id
                apply.submission_snapshot_id = submission_snapshot_id
                apply.submission_allocation_ids = submission_allocation_ids
                apply.snapshot_hash = snapshot_hash
                apply.revision = resulting_revision
                apply.warning_start = warning_start
                return AuditEventInput(
                    audit_event_id=new_uuid4(),
                    action_type="inventory.spare_request.submitted",
                    action_version=1,
                    actor_kind=actor_kind,
                    actor_id=actor_id,
                    target_type="spare_request",
                    target_id=request_id,
                    command_id=command_id,
                    payload_schema="SpareRequestSubmissionAuditV1",
                    payload_version=1,
                    payload={
                        "spare_request_id": request_id,
                        "submission_event_id": submission_event_id,
                        "submission_snapshot_id": submission_snapshot_id,
                        "event_kind": "ACCEPT",
                        "allocation_count": len(submission_allocation_ids),
                        "input_fingerprint": snapshot_hash,
                        "effective_at_utc": effective,
                    },
                    resulting_event_refs=(
                        AuditResultRef(
                            "spare_request_submission_snapshot",
                            submission_snapshot_id,
                        ),
                    ),
                )

            apply.submission_event_id = ""
            apply.submission_snapshot_id = ""
            apply.submission_allocation_ids = ()
            apply.snapshot_hash = ""
            apply.revision = revision + 1
            apply.warning_start = effective
            return PreparedMutation(
                no_change=False,
                result_type="spare_request",
                result_id=request_id,
                apply=apply,
                response_schema="SpareRequestV1",
                response_factory=lambda inner: self._response(
                    inner.connection,
                    request_id,
                ),
            )

        execution = self._boundary.execute(envelope, prepare)
        if not isinstance(execution.response, dict):
            raise IntegrityFailure("Spare Request submission response is not an object")
        return dict(execution.response)

    def correct_false_spare_request_submission(
        self,
        *,
        command_id: str,
        spare_request_id: str,
        base_revision: int,
        submission_event_id: str,
        reason_code: str,
        confirmed_no_real_send: bool,
        actor_kind: str = "local_user",
        actor_id: str | None = None,
    ) -> dict[str, object]:
        request_id = require_uuid4(spare_request_id)
        revision = validate_positive_revision(base_revision, field="base_revision")
        event_id = require_uuid4(submission_event_id)
        reason = validate_reason_code(reason_code)
        if confirmed_no_real_send is not True:
            raise ValidationError(
                "confirmed_no_real_send must be true for false-submission correction"
            )

        envelope = CommandEnvelope(
            command_id=command_id,
            command_type="CorrectFalseSpareRequestSubmission",
            target_type="spare_request",
            target_id=request_id,
            semantic_payload={
                "submission_event_id": event_id,
                "reason_code": reason,
                "confirmed_no_real_send": True,
            },
            base_revisions={"spare_request": revision},
        )

        def prepare(uow: UnitOfWork) -> PreparedMutation:
            current = self._repository.current_submission(
                uow.connection,
                request_id,
            )
            if current is None or int(current[6]) != revision:
                raise SomaError(
                    "CORRECTION_TARGET_INVALID",
                    "Spare Request current submission changed",
                )
            if str(current[1]) != event_id:
                raise SomaError(
                    "CORRECTION_TARGET_INVALID",
                    "False-submission correction target is not current",
                )

            def apply(inner: UnitOfWork):
                (
                    correction_event_id,
                    submission_snapshot_id,
                    snapshot_hash,
                    effective_at,
                    allocation_count,
                    resulting_revision,
                ) = self._repository.correct_false_submission(
                    inner.connection,
                    spare_request_id=request_id,
                    base_revision=revision,
                    submission_event_id=event_id,
                    reason_code=reason,
                    command_id=command_id,
                )
                apply.correction_event_id = correction_event_id
                apply.submission_snapshot_id = submission_snapshot_id
                apply.snapshot_hash = snapshot_hash
                apply.effective_at = effective_at
                apply.allocation_count = allocation_count
                apply.revision = resulting_revision
                return AuditEventInput(
                    audit_event_id=new_uuid4(),
                    action_type="inventory.spare_request.submitted",
                    action_version=1,
                    actor_kind=actor_kind,
                    actor_id=actor_id,
                    target_type="spare_request",
                    target_id=request_id,
                    command_id=command_id,
                    reason_category=reason,
                    payload_schema="SpareRequestSubmissionAuditV1",
                    payload_version=1,
                    payload={
                        "spare_request_id": request_id,
                        "submission_event_id": event_id,
                        "submission_snapshot_id": submission_snapshot_id,
                        "event_kind": "CORRECT_FALSE",
                        "allocation_count": allocation_count,
                        "input_fingerprint": snapshot_hash,
                        "effective_at_utc": effective_at,
                    },
                    resulting_event_refs=(
                        AuditResultRef(
                            "spare_request_submission_snapshot",
                            submission_snapshot_id,
                        ),
                    ),
                )

            apply.correction_event_id = ""
            apply.submission_snapshot_id = str(current[0])
            apply.snapshot_hash = str(current[4])
            apply.effective_at = None if current[5] is None else int(current[5])
            apply.allocation_count = 1
            apply.revision = revision + 1
            return PreparedMutation(
                no_change=False,
                result_type="spare_request",
                result_id=request_id,
                apply=apply,
                response_schema="SpareRequestV1",
                response_factory=lambda inner: self._response(
                    inner.connection,
                    request_id,
                ),
            )

        execution = self._boundary.execute(envelope, prepare)
        if not isinstance(execution.response, dict):
            raise IntegrityFailure("Spare Request correction response is not an object")
        return dict(execution.response)


    def assign_or_correct_spare_request_official_id(
        self,
        *,
        command_id: str,
        spare_request_id: str,
        base_revision: int,
        sr7: str,
        action: str,
        reason_code: str | None = None,
        actor_kind: str = "local_user",
        actor_id: str | None = None,
    ) -> dict[str, object]:
        request_id = require_uuid4(spare_request_id)
        revision = validate_positive_revision(base_revision, field="base_revision")
        official_sr7 = validate_sr7(sr7)
        accepted_action = validate_sr7_action(action)
        if accepted_action == "correct":
            if reason_code is None:
                raise ValidationError("SR7 correction requires reason_code")
            reason = validate_reason_code(reason_code)
        else:
            if reason_code is not None:
                raise ValidationError("SR7 assignment does not accept correction reason_code")
            reason = None

        with ReadSnapshot(self._factory) as snapshot:
            material = self._repository.draft_material(
                snapshot.connection,
                request_id,
            )
            if int(material["revision"]) != revision:
                raise SomaError("INV_STALE", "Spare Request revision changed")
            current_sr7 = material["current_sr7"]
            if current_sr7 == official_sr7:
                if accepted_action == "assign":
                    existing_response = self._response(snapshot.connection, request_id)
                else:
                    raise SomaError("SR7_CONFLICT", "SR7 correction must change the current alias")
            else:
                existing_response = None
                if self._repository.sr7_alias_owner(
                    snapshot.connection,
                    official_sr7,
                ) is not None:
                    raise SomaError(
                        "SR7_CONFLICT",
                        "Official SR7 is already current or former history",
                    )

        envelope = CommandEnvelope(
            command_id=command_id,
            command_type="AssignOrCorrectSpareRequestOfficialId",
            target_type="spare_request",
            target_id=request_id,
            semantic_payload={
                "sr7": official_sr7,
                "action": accepted_action,
                "reason_code": reason,
            },
            base_revisions={"spare_request": revision},
        )

        def prepare(uow: UnitOfWork) -> PreparedMutation:
            material_now = self._repository.draft_material(
                uow.connection,
                request_id,
            )
            if int(material_now["revision"]) != revision:
                raise SomaError("INV_STALE", "Spare Request revision changed")
            current = material_now["current_sr7"]
            if current == official_sr7:
                if accepted_action != "assign":
                    raise SomaError(
                        "SR7_CONFLICT",
                        "SR7 correction must change the current alias",
                    )
                return PreparedMutation(
                    no_change=True,
                    result_type=None,
                    result_id=None,
                    response_schema="SpareRequestV1",
                    response=self._response(uow.connection, request_id),
                )
            if self._repository.sr7_alias_owner(
                uow.connection,
                official_sr7,
            ) is not None:
                raise SomaError(
                    "SR7_CONFLICT",
                    "Official SR7 is already current or former history",
                )
            former_sr7 = None if current is None else str(current)
            if accepted_action == "assign" and former_sr7 is not None:
                raise SomaError("SR7_CONFLICT", "Spare Request already has a current SR7")
            if accepted_action == "correct" and former_sr7 is None:
                raise SomaError("SR7_CONFLICT", "Spare Request has no current SR7 to correct")

            def apply(inner: UnitOfWork):
                (
                    identifier_event_id,
                    alias_id,
                    acknowledgement_event_id,
                    resulting_revision,
                ) = self._repository.assign_or_correct_sr7(
                    inner.connection,
                    spare_request_id=request_id,
                    base_revision=revision,
                    sr7=official_sr7,
                    action=accepted_action,
                    reason_code=reason,
                    command_id=command_id,
                )
                apply.identifier_event_id = identifier_event_id
                apply.alias_id = alias_id
                apply.acknowledgement_event_id = acknowledgement_event_id
                apply.revision = resulting_revision
                return AuditEventInput(
                    audit_event_id=new_uuid4(),
                    action_type="inventory.spare_request.official_id_changed",
                    action_version=1,
                    actor_kind=actor_kind,
                    actor_id=actor_id,
                    target_type="spare_request",
                    target_id=request_id,
                    command_id=command_id,
                    reason_category=reason,
                    payload_schema="SpareRequestIdentityAuditV1",
                    payload_version=1,
                    payload={
                        "spare_request_id": request_id,
                        "event_kind": (
                            "ASSIGN" if accepted_action == "assign" else "CORRECT"
                        ),
                        "current_sr7": official_sr7,
                        "former_sr7": former_sr7,
                        "resulting_revision": resulting_revision,
                        "reason_category": reason,
                    },
                    resulting_event_refs=(
                        AuditResultRef("spare_request_identifier", alias_id),
                    ),
                )

            apply.identifier_event_id = ""
            apply.alias_id = ""
            apply.acknowledgement_event_id = None
            apply.revision = revision + 1
            return PreparedMutation(
                no_change=False,
                result_type="spare_request",
                result_id=request_id,
                apply=apply,
                response_schema="SpareRequestV1",
                response_factory=lambda inner: self._response(
                    inner.connection,
                    request_id,
                ),
            )

        execution = self._boundary.execute(envelope, prepare)
        if not isinstance(execution.response, dict):
            raise IntegrityFailure("Spare Request SR7 response is not an object")
        return dict(execution.response)


    def accept_rma_authorization_batch(
        self,
        *,
        command_id: str,
        spare_request_id: str,
        expected_request_revision: int,
        rows: tuple[RmaAuthorizationIntent, ...],
        accepted_at_utc: int | None = None,
        evidence_kind: str | None = None,
        evidence_id: str | None = None,
        actor_kind: str = "local_user",
        actor_id: str | None = None,
    ) -> dict[str, object]:
        request_id = require_uuid4(spare_request_id)
        request_revision = validate_positive_revision(
            expected_request_revision,
            field="expected_request_revision",
        )
        normalized_rows = validate_rma_authorization_batch(rows)
        accepted_at = validate_authorization_time(accepted_at_utc)
        evidence_kind_value, evidence_id_value = validate_optional_evidence(
            evidence_kind,
            evidence_id,
        )
        if evidence_kind_value is not None:
            raise SomaError(
                "DEPENDENCY_INDETERMINATE",
                "RMA authorization evidence validator is unavailable",
            )

        envelope = CommandEnvelope(
            command_id=command_id,
            command_type="AcceptRmaAuthorizationBatch",
            target_type="spare_request",
            target_id=request_id,
            semantic_payload={
                "rows": [
                    {
                        "c10": c10,
                        "promised_bom_code": bom_code,
                        "promised_bom_key": bom_key,
                    }
                    for c10, bom_code, bom_key in normalized_rows
                ],
                "accepted_at_utc": accepted_at,
                "evidence_kind": evidence_kind_value,
                "evidence_id": evidence_id_value,
            },
            base_revisions={"spare_request": request_revision},
        )

        def prepare(uow: UnitOfWork) -> PreparedMutation:
            self._rmas.require_authorization_authority(
                uow.connection,
                spare_request_id=request_id,
                expected_revision=request_revision,
                batch_count=len(normalized_rows),
            )
            for c10, _bom_code, _bom_key in normalized_rows:
                if self._rmas.c10_alias_owner(uow.connection, c10) is not None:
                    raise SomaError("C10_CONFLICT", "C10 is already current or former history")

            def apply(inner: UnitOfWork):
                (
                    batch_id,
                    created_rmas,
                    remaining,
                    resulting_request_revision,
                ) = self._rmas.accept_authorization_batch(
                    inner.connection,
                    spare_request_id=request_id,
                    expected_request_revision=request_revision,
                    rows=normalized_rows,
                    accepted_at_utc=accepted_at,
                    evidence_kind=evidence_kind_value,
                    evidence_id=evidence_id_value,
                    command_id=command_id,
                )
                apply.batch_id = batch_id
                apply.created_rmas = created_rmas
                apply.remaining = remaining
                apply.request_revision = resulting_request_revision
                audits: list[AuditEventInput] = []
                for created in created_rmas:
                    refs = [
                        AuditResultRef("rma", str(created["rma_id"])),
                    ]
                    if created["assignment_event_id"] is not None:
                        refs.append(
                            AuditResultRef(
                                "rma_assignment",
                                str(created["assignment_event_id"]),
                            )
                        )
                    audits.append(
                        AuditEventInput(
                            audit_event_id=new_uuid4(),
                            action_type="inventory.rma.authorized_or_assigned",
                            action_version=1,
                            actor_kind=actor_kind,
                            actor_id=actor_id,
                            target_type="rma",
                            target_id=str(created["rma_id"]),
                            command_id=command_id,
                            payload_schema="RmaAuditV1",
                            payload_version=1,
                            payload={
                                "spare_request_id": request_id,
                                "authorization_batch_id": batch_id,
                                "rma_id": str(created["rma_id"]),
                                "event_kind": "AUTHORIZE",
                                "current_c10": str(created["current_c10"]),
                                "target_device_part_unit_id": created[
                                    "target_device_part_unit_id"
                                ],
                                "resulting_revision": 1,
                            },
                            resulting_event_refs=tuple(refs),
                        )
                    )
                return tuple(audits)

            apply.batch_id = ""
            apply.created_rmas = ()
            apply.remaining = 0
            apply.request_revision = request_revision + 1

            def response_factory(_inner: UnitOfWork) -> dict[str, object]:
                return {
                    "spare_request_id": request_id,
                    "created_rmas": [
                        {
                            "rma_id": str(item["rma_id"]),
                            "current_c10": str(item["current_c10"]),
                            "state": "promised",
                            "promised_bom": str(item["promised_bom"]),
                            "direct_inbound_unit_id": None,
                        }
                        for item in apply.created_rmas
                    ],
                    "remaining_unassigned_quantity": apply.remaining,
                }

            return PreparedMutation(
                no_change=False,
                result_type="spare_request",
                result_id=request_id,
                apply=apply,
                response_schema="RmaBatchResultV1",
                response_factory=response_factory,
            )

        execution = self._boundary.execute(envelope, prepare)
        if (
            execution.response_schema != "RmaBatchResultV1"
            or execution.response_version != 1
            or not isinstance(execution.response, dict)
        ):
            raise IntegrityFailure("RMA batch replay result has the wrong response contract")
        return dict(execution.response)

    def correct_rma_official_id(
        self,
        *,
        command_id: str,
        rma_id: str,
        current_c10: str,
        new_c10: str,
        reason_code: str,
        actor_kind: str = "local_user",
        actor_id: str | None = None,
    ) -> InventoryMutationResult:
        identity = require_uuid4(rma_id)
        expected_c10 = validate_c10(current_c10)
        replacement_c10 = validate_c10(new_c10)
        reason = validate_reason_code(reason_code)
        if expected_c10 == replacement_c10:
            raise ValidationError("C10 correction must change the current identifier")

        envelope = CommandEnvelope(
            command_id=command_id,
            command_type="CorrectRmaOfficialId",
            target_type="rma",
            target_id=identity,
            semantic_payload={
                "current_c10": expected_c10,
                "new_c10": replacement_c10,
                "reason_code": reason,
            },
        )

        def prepare(uow: UnitOfWork) -> PreparedMutation:
            row = self._rmas.current_rma(uow.connection, identity)
            if row is None:
                raise SomaError("INV_STALE", "RMA no longer exists")
            if str(row[4]) != expected_c10:
                raise SomaError("INV_STALE", "RMA current C10 changed")
            if self._rmas.c10_alias_owner(
                uow.connection,
                replacement_c10,
            ) is not None:
                raise SomaError("C10_CONFLICT", "C10 is already current or former history")
            spare_request_id = str(row[1])

            def apply(inner: UnitOfWork):
                event_id, alias_id, resulting_revision = self._rmas.correct_c10(
                    inner.connection,
                    rma_id=identity,
                    expected_current_c10=expected_c10,
                    new_c10=replacement_c10,
                    reason_code=reason,
                    command_id=command_id,
                )
                apply.event_id = event_id
                apply.alias_id = alias_id
                apply.revision = resulting_revision
                return AuditEventInput(
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
                        "spare_request_id": spare_request_id,
                        "authorization_batch_id": None,
                        "rma_id": identity,
                        "event_kind": "C10_CORRECT",
                        "current_c10": replacement_c10,
                        "target_device_part_unit_id": (
                            None if row[6] is None else str(row[6])
                        ),
                        "resulting_revision": resulting_revision,
                    },
                    resulting_event_refs=(
                        AuditResultRef("rma", identity),
                    ),
                )

            apply.event_id = ""
            apply.alias_id = ""
            apply.revision = int(row[12]) + 1
            return PreparedMutation(
                no_change=False,
                result_type="rma",
                result_id=identity,
                apply=apply,
                response_schema="InventoryMutationResultV1",
                response_factory=lambda _inner: self._inventory_response(
                    [
                        ("rma", identity),
                        ("rma_identifier", apply.alias_id),
                    ],
                    {f"rma:{identity}": apply.revision},
                ),
            )

        return inventory_mutation_result_from_execution(
            self._boundary.execute(envelope, prepare)
        )

    def set_rma_target_assignment(
        self,
        *,
        command_id: str,
        rma_id: str,
        expected_assignment_revision: int | None,
        new_target_device_part_unit_id: str | None,
        reason_code: str,
        actor_kind: str = "local_user",
        actor_id: str | None = None,
    ) -> InventoryMutationResult:
        identity = require_uuid4(rma_id)
        if expected_assignment_revision is not None:
            validate_positive_revision(
                expected_assignment_revision,
                field="expected_assignment_revision",
            )
        target_id = (
            None
            if new_target_device_part_unit_id is None
            else require_uuid4(new_target_device_part_unit_id)
        )
        reason = validate_reason_code(reason_code)

        envelope = CommandEnvelope(
            command_id=command_id,
            command_type="SetRmaTargetAssignment",
            target_type="rma",
            target_id=identity,
            semantic_payload={
                "expected_assignment_revision": expected_assignment_revision,
                "new_target_device_part_unit_id": target_id,
                "reason_code": reason,
            },
            base_revisions=(
                {}
                if expected_assignment_revision is None
                else {"rma_assignment": expected_assignment_revision}
            ),
        )

        def prepare(uow: UnitOfWork) -> PreparedMutation:
            rma = self._rmas.current_rma(uow.connection, identity)
            if rma is None:
                raise SomaError("INV_STALE", "RMA no longer exists")
            current = uow.connection.execute(
                "SELECT device_part_unit_id,revision FROM rma_current_assignment "
                "WHERE rma_id=?",
                (identity,),
            ).fetchone()
            if expected_assignment_revision is None:
                if current is not None:
                    raise SomaError("INV_STALE", "RMA assignment was created")
            elif current is None or int(current[1]) != expected_assignment_revision:
                raise SomaError("INV_STALE", "RMA assignment revision changed")
            current_target = None if current is None else str(current[0])
            if current_target == target_id:
                return PreparedMutation(
                    no_change=True,
                    result_type=None,
                    result_id=None,
                    response_schema="InventoryMutationResultV1",
                    response=self._inventory_response([], {}, outcome="NO_CHANGE"),
                )
            spare_request_id = str(rma[1])
            current_c10 = str(rma[4])
            prior_exists = current is not None

            def apply(inner: UnitOfWork):
                event_id, resulting_target, lifecycle_revision = (
                    self._rmas.set_target_assignment(
                        inner.connection,
                        rma_id=identity,
                        expected_assignment_revision=expected_assignment_revision,
                        new_target_device_part_unit_id=target_id,
                        reason_code=reason,
                        command_id=command_id,
                    )
                )
                apply.event_id = event_id
                apply.target = resulting_target
                apply.revision = lifecycle_revision
                event_kind = (
                    "CLEAR"
                    if resulting_target is None
                    else ("REASSIGN" if prior_exists else "ASSIGN")
                )
                return AuditEventInput(
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
                        "spare_request_id": spare_request_id,
                        "authorization_batch_id": None,
                        "rma_id": identity,
                        "event_kind": event_kind,
                        "current_c10": current_c10,
                        "target_device_part_unit_id": resulting_target,
                        "resulting_revision": lifecycle_revision,
                    },
                    resulting_event_refs=(
                        AuditResultRef("rma", identity),
                        AuditResultRef("rma_assignment", event_id),
                    ),
                )

            apply.event_id = ""
            apply.target = target_id
            apply.revision = int(rma[12]) + 1
            return PreparedMutation(
                no_change=False,
                result_type="rma",
                result_id=identity,
                apply=apply,
                response_schema="InventoryMutationResultV1",
                response_factory=lambda _inner: self._inventory_response(
                    [
                        ("rma", identity),
                        ("rma_assignment", apply.event_id),
                    ],
                    {f"rma:{identity}": apply.revision},
                ),
            )

        return inventory_mutation_result_from_execution(
            self._boundary.execute(envelope, prepare)
        )


__all__ = ["InventoryRequestsRmaService"]
