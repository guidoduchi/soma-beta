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
from ..domain.needs import validate_reason_code
from ..domain.requests import (
    SpareRequestAllocationIntent,
    validate_allocation_intents,
    validate_logistics_mode,
    validate_positive_revision,
    validate_request_origin,
    validate_submission_evidence,
    validate_submission_time,
)
from ..interfaces import SpareRequestSubmissionEvidenceValidator
from ..repositories.requests import InventoryRequestsRepository


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


__all__ = ["InventoryRequestsRmaService"]
