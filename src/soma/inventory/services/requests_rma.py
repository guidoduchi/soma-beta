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
from ..domain.requests import (
    SpareRequestAllocationIntent,
    normalize_sr7,
    validate_positive_revision,
    validate_allocation_intents,
    validate_logistics_mode,
    validate_request_origin,
)
from ..repositories.requests import InventoryRequestsRepository
from ..domain.needs import validate_reason_code


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


class InventoryRequestsRmaService:
    def __init__(self, connection_factory: ConnectionFactory) -> None:
        self._factory = connection_factory
        self._repository = InventoryRequestsRepository()
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
            "state": {
                "draft": "draft",
                "submitted_awaiting_response": "submitted",
                "acknowledged": "submitted",
                "partially_authorized": "authorizing",
                "authorized": "authorized",
                "cancelled": "terminal",
                "rejected": "terminal",
            }[str(row[6])],
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
        allocation_pairs = tuple(sorted(
            (
                (item.spare_need_id, item.quantity)
                for item in accepted_allocations
            ),
            key=lambda item: item[0],
        ))

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
                    AuditResultRef("spare_request_event", event_id),
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
        revision = validate_positive_revision(base_revision, "base_revision")
        receiver_id = require_uuid4(receiver_contact_id)
        location_id = require_uuid4(dispatch_location_id)
        accepted_allocations = validate_allocation_intents(allocations)
        allocation_pairs = tuple(sorted(
            ((item.spare_need_id, item.quantity) for item in accepted_allocations),
            key=lambda item: item[0],
        ))
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
            row = self._repository.current_detail(uow.connection, request_id)
            if row is None or int(row[8]) != revision:
                raise SomaError("INV_STALE", "Spare Request revision changed")
            if str(row[6]) != "draft" or row[7] is not None:
                raise SomaError("REQUEST_NOT_DRAFT", "Spare Request is not editable Draft authority")
            service_request_id = str(row[2])
            requester_id = str(row[3])
            tracking_id = str(row[1])
            requester_context = loads_canonical_json(
                str(row[4]), max_bytes=4096, max_depth=3, max_collection_items=16
            )
            if not isinstance(requester_context, dict):
                raise IntegrityFailure("Persisted requester context is invalid")
            requester_context_fingerprint = sha256_canonical_json(requester_context)
            self._repository.require_receiver_and_location(
                uow.connection,
                receiver_contact_id=receiver_id,
                dispatch_location_id=location_id,
            )
            self._repository.require_sr_need_allocations(
                uow.connection,
                service_request_id=service_request_id,
                allocations=allocation_pairs,
            )
            current_allocations = tuple(
                sorted(
                    (
                        (str(item[1]), int(item[2]))
                        for item in self._repository.active_draft_allocations(
                            uow.connection, request_id
                        )
                    ),
                    key=lambda item: item[0],
                )
            )
            if (
                current_allocations == allocation_pairs
                and str(row[10]) == logistics_mode
                and str(row[11]) == receiver_id
                and str(row[12]) == location_id
            ):
                return PreparedMutation(
                    no_change=True,
                    result_type=None,
                    result_id=None,
                    response_schema="SpareRequestV1",
                    response=self._response(uow.connection, request_id),
                )

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
                        "tracking_id": tracking_id,
                        "event_kind": "DRAFT_UPDATE",
                        "requester_contact_id": requester_id,
                        "requester_context_fingerprint": requester_context_fingerprint,
                        "resulting_revision": resulting_revision,
                        "allocation_count": len(allocation_pairs),
                        "reason_category": None,
                    },
                    resulting_event_refs=tuple(
                        AuditResultRef("spare_request_allocation", allocation_id)
                        for allocation_id in allocation_ids
                    ),
                )

            apply.allocation_ids = ()
            apply.revision = revision + 1
            return PreparedMutation(
                no_change=False,
                result_type="spare_request",
                result_id=request_id,
                apply=apply,
                response_schema="SpareRequestV1",
                response_factory=lambda inner: self._response(inner.connection, request_id),
            )

        execution = self._boundary.execute(envelope, prepare)
        if not isinstance(execution.response, dict):
            raise IntegrityFailure("Spare Request response is not an object")
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
        revision = validate_positive_revision(base_revision, "base_revision")
        official = normalize_sr7(sr7)
        if action not in {"assign", "correct"}:
            raise ValidationError("Spare Request official-id action is invalid")
        reason = None
        if action == "correct":
            if reason_code is None:
                raise ValidationError("SR7 correction requires a reason")
            reason = validate_reason_code(reason_code)
        elif reason_code is not None:
            reason = validate_reason_code(reason_code)
        envelope = CommandEnvelope(
            command_id=command_id,
            command_type="AssignOrCorrectSpareRequestOfficialId",
            target_type="spare_request",
            target_id=request_id,
            semantic_payload={"action": action, "sr7": official, "reason_code": reason},
            base_revisions={"spare_request": revision},
        )

        def prepare(uow: UnitOfWork) -> PreparedMutation:
            row = self._repository.current_detail(uow.connection, request_id)
            if row is None or int(row[8]) != revision:
                raise SomaError("INV_STALE", "Spare Request revision changed")
            current = None if row[7] is None else str(row[7])
            if current == official:
                return PreparedMutation(
                    no_change=True,
                    result_type=None,
                    result_id=None,
                    response_schema="SpareRequestV1",
                    response=self._response(uow.connection, request_id),
                )

            def apply(inner: UnitOfWork):
                event_id, former, resulting_revision = self._repository.assign_or_correct_sr7(
                    inner.connection,
                    spare_request_id=request_id,
                    base_revision=revision,
                    new_sr7=official,
                    action=action,
                    reason_code=reason,
                    command_id=command_id,
                )
                apply.event_id = event_id
                apply.former = former
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
                        "event_kind": action.upper(),
                        "current_sr7": official,
                        "former_sr7": former,
                        "resulting_revision": resulting_revision,
                        "reason_category": reason,
                    },
                    resulting_event_refs=(
                        AuditResultRef("spare_request_identifier", event_id),
                    ),
                )

            apply.event_id = ""
            apply.former = None
            apply.revision = revision + 1
            return PreparedMutation(
                no_change=False,
                result_type="spare_request",
                result_id=request_id,
                apply=apply,
                response_schema="SpareRequestV1",
                response_factory=lambda inner: self._response(inner.connection, request_id),
            )

        execution = self._boundary.execute(envelope, prepare)
        if not isinstance(execution.response, dict):
            raise IntegrityFailure("Spare Request response is not an object")
        return dict(execution.response)

    def cancel_or_reject_spare_request(
        self,
        *,
        command_id: str,
        spare_request_id: str,
        base_revision: int,
        action: str,
        reason_code: str,
        actor_kind: str = "local_user",
        actor_id: str | None = None,
    ) -> dict[str, object]:
        request_id = require_uuid4(spare_request_id)
        revision = validate_positive_revision(base_revision, "base_revision")
        if action not in {"cancelled", "rejected"}:
            raise ValidationError("Spare Request terminal action is invalid")
        reason = validate_reason_code(reason_code)
        envelope = CommandEnvelope(
            command_id=command_id,
            command_type="CancelOrRejectSpareRequest",
            target_type="spare_request",
            target_id=request_id,
            semantic_payload={"action": action, "reason_code": reason},
            base_revisions={"spare_request": revision},
        )

        def prepare(uow: UnitOfWork) -> PreparedMutation:
            row = self._repository.current_detail(uow.connection, request_id)
            if row is None or int(row[8]) != revision:
                raise SomaError("INV_STALE", "Spare Request revision changed")
            if str(row[6]) == action:
                return PreparedMutation(
                    no_change=True,
                    result_type=None,
                    result_id=None,
                    response_schema="SpareRequestV1",
                    response=self._response(uow.connection, request_id),
                )
            requester_context = loads_canonical_json(
                str(row[4]), max_bytes=4096, max_depth=3, max_collection_items=16
            )
            if not isinstance(requester_context, dict):
                raise IntegrityFailure("Persisted requester context is invalid")
            requester_context_fingerprint = sha256_canonical_json(requester_context)
            allocation_count = len(
                self._repository.active_draft_allocations(uow.connection, request_id)
            )
            tracking_id = str(row[1])
            requester_id = str(row[3])

            def apply(inner: UnitOfWork):
                event_id, resulting_revision = self._repository.cancel_or_reject(
                    inner.connection,
                    spare_request_id=request_id,
                    base_revision=revision,
                    target_state=action,
                    reason_code=reason,
                    command_id=command_id,
                )
                apply.event_id = event_id
                apply.revision = resulting_revision
                return AuditEventInput(
                    audit_event_id=new_uuid4(),
                    action_type="inventory.spare_request.draft_changed",
                    action_version=1,
                    actor_kind=actor_kind,
                    actor_id=actor_id,
                    target_type="spare_request",
                    target_id=request_id,
                    command_id=command_id,
                    reason_category=reason,
                    payload_schema="SpareRequestAuditV1",
                    payload_version=1,
                    payload={
                        "spare_request_id": request_id,
                        "tracking_id": tracking_id,
                        "event_kind": "TERMINAL",
                        "requester_contact_id": requester_id,
                        "requester_context_fingerprint": requester_context_fingerprint,
                        "resulting_revision": resulting_revision,
                        "allocation_count": allocation_count,
                        "reason_category": reason,
                    },
                    resulting_event_refs=(
                        AuditResultRef("spare_request_event", event_id),
                    ),
                )

            apply.event_id = ""
            apply.revision = revision + 1
            return PreparedMutation(
                no_change=False,
                result_type="spare_request",
                result_id=request_id,
                apply=apply,
                response_schema="SpareRequestV1",
                response_factory=lambda inner: self._response(inner.connection, request_id),
            )

        execution = self._boundary.execute(envelope, prepare)
        if not isinstance(execution.response, dict):
            raise IntegrityFailure("Spare Request response is not an object")
        return dict(execution.response)


__all__ = ["InventoryRequestsRmaService"]
