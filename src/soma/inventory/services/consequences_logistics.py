from __future__ import annotations

import hashlib
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
from soma.foundation.persistence.uow import UnitOfWork

from ..audit_registry import build_inventory_audit_registry
from ..contracts.inventory import (
    InventoryMutationResult,
    inventory_mutation_result_from_execution,
)
from ..domain.logistics import (
    LogisticsParticipantIntent,
    normalize_optional_uuid,
    validate_logistics_event_kind,
    validate_logistics_participants,
    validate_receipt_identity,
)
from ..domain.units import initial_disposition_for_condition
from ..repositories.logistics import InventoryLogisticsRepository


class InventoryConsequencesLogisticsService:
    def __init__(self, connection_factory: ConnectionFactory) -> None:
        self._factory = connection_factory
        self._repository = InventoryLogisticsRepository()
        self._boundary = CommandBoundary(
            connection_factory,
            AuditWriter(build_inventory_audit_registry()),
        )

    @staticmethod
    def _response(
        refs: list[tuple[str, str]],
        revisions: dict[str, int],
    ) -> dict[str, object]:
        return {
            "outcome": "APPLIED",
            "target_refs": [{"type": kind, "id": identity} for kind, identity in refs],
            "revisions": dict(revisions),
        }

    @staticmethod
    def _fingerprint(value: str | None) -> str | None:
        if value is None:
            return None
        return hashlib.sha256(value.encode("utf-8", errors="strict")).hexdigest()

    def record_rma_inbound_receipt(
        self,
        *,
        command_id: str,
        rma_id: str,
        actual_bom_code: str,
        manufacturer_serial: str | None = None,
        condition_token: str | None = None,
        effective_at_utc: int | None = None,
        dispatch_location_id: str | None = None,
        receiver_contact_id: str | None = None,
        location_kind: str | None = None,
        location_ref_id: str | None = None,
        custody_text: str | None = None,
        evidence_kind: str | None = None,
        evidence_id: str | None = None,
        actor_kind: str = "local_user",
        actor_id: str | None = None,
    ) -> InventoryMutationResult:
        identity = require_uuid4(rma_id)
        (
            bom_code,
            bom_key,
            stored_serial,
            serial_key,
            condition,
            effective,
            normalized_location_kind,
            normalized_location_ref,
            normalized_custody,
        ) = validate_receipt_identity(
            bom_code=actual_bom_code,
            manufacturer_serial=manufacturer_serial,
            condition_token=condition_token,
            effective_at_utc=effective_at_utc,
            location_kind=location_kind,
            location_ref_id=location_ref_id,
            custody_text=custody_text,
        )
        dispatch_id = normalize_optional_uuid(dispatch_location_id, "dispatch_location_id")
        receiver_id = normalize_optional_uuid(receiver_contact_id, "receiver_contact_id")
        if evidence_kind is None:
            if evidence_id is not None:
                raise ValidationError("evidence_id requires evidence_kind")
        elif evidence_kind not in {"manual", "indexed_receipt"}:
            raise ValidationError("receipt evidence kind is invalid")
        if evidence_kind == "indexed_receipt" and (
            not isinstance(evidence_id, str) or not evidence_id.strip()
        ):
            raise ValidationError("indexed receipt evidence requires evidence_id")
        normalized_evidence_id = None if evidence_id is None else evidence_id.strip()
        disposition = initial_disposition_for_condition(condition)
        envelope = CommandEnvelope(
            command_id=command_id,
            command_type="RecordRmaInboundReceipt",
            target_type="rma",
            target_id=identity,
            semantic_payload={
                "actual_bom_code": bom_code,
                "actual_bom_key": bom_key,
                "manufacturer_serial": stored_serial,
                "serial_key": serial_key,
                "condition_token": condition,
                "effective_at_utc": effective,
                "dispatch_location_id": dispatch_id,
                "receiver_contact_id": receiver_id,
                "location_kind": normalized_location_kind,
                "location_ref_id": normalized_location_ref,
                "custody_text": normalized_custody,
                "evidence_kind": evidence_kind,
                "evidence_id": normalized_evidence_id,
            },
        )

        def prepare(uow: UnitOfWork) -> PreparedMutation:
            rma = self._repository.require_receipt_eligible(uow.connection, identity)
            spare_part_unit_id = new_uuid4()

            def apply(inner: UnitOfWork):
                (
                    spare_part_unit_id,
                    logistics_event_id,
                    receipt_unit_event_id,
                    unit_revision,
                    rma_revision,
                ) = self._repository.record_rma_inbound_receipt(
                    inner.connection,
                    rma_id=identity,
                    spare_part_unit_id=spare_part_unit_id,
                    bom_code=bom_code,
                    bom_key=bom_key,
                    manufacturer_serial=stored_serial,
                    serial_key=serial_key,
                    condition_token=condition,
                    disposition_token=disposition,
                    effective_at_utc=effective,
                    dispatch_location_id=dispatch_id,
                    receiver_contact_id=receiver_id,
                    location_kind=normalized_location_kind,
                    location_ref_id=normalized_location_ref,
                    custody_text=normalized_custody,
                    evidence_kind=evidence_kind,
                    evidence_id=normalized_evidence_id,
                    command_id=command_id,
                )
                apply.unit_id = spare_part_unit_id
                apply.logistics_id = logistics_event_id
                apply.unit_event_id = receipt_unit_event_id
                apply.unit_revision = unit_revision
                apply.rma_revision = rma_revision
                return AuditEventInput(
                    audit_event_id=new_uuid4(),
                    action_type="inventory.rma.inbound_received",
                    action_version=1,
                    actor_kind=actor_kind,
                    actor_id=actor_id,
                    target_type="rma",
                    target_id=identity,
                    command_id=command_id,
                    payload_schema="RmaReceiptAuditV1",
                    payload_version=1,
                    payload={
                        "rma_id": identity,
                        "spare_part_unit_id": spare_part_unit_id,
                        "receipt_event_id": receipt_unit_event_id,
                        "logistics_event_id": logistics_event_id,
                        "actual_bom_fingerprint": self._fingerprint(bom_key),
                        "actual_serial_fingerprint": self._fingerprint(serial_key),
                        "effective_at_utc": effective,
                    },
                    resulting_event_refs=(
                        AuditResultRef("spare_part_unit", spare_part_unit_id),
                        AuditResultRef("logistics_event", logistics_event_id),
                    ),
                )

            apply.unit_id = spare_part_unit_id
            apply.logistics_id = ""
            apply.unit_event_id = ""
            apply.unit_revision = 1
            apply.rma_revision = int(rma[9]) + 1
            return PreparedMutation(
                no_change=False,
                result_type="spare_part_unit",
                result_id=spare_part_unit_id,
                apply=apply,
                response_schema="InventoryMutationResultV1",
                response_factory=lambda _inner: self._response(
                    [
                        ("spare_part_unit", apply.unit_id),
                        ("logistics_event", apply.logistics_id),
                    ],
                    {
                        f"spare_part_unit:{apply.unit_id}": apply.unit_revision,
                        f"rma:{identity}": apply.rma_revision,
                    },
                ),
            )

        return inventory_mutation_result_from_execution(
            self._boundary.execute(envelope, prepare)
        )


    def record_actual_logistics_event(
        self,
        *,
        command_id: str,
        event_kind: str,
        participants: tuple[LogisticsParticipantIntent, ...],
        effective_at_utc: int | None = None,
        dispatch_location_id: str | None = None,
        receiver_contact_id: str | None = None,
        custody_text: str | None = None,
        observed_condition: str | None = None,
        evidence_kind: str | None = None,
        evidence_id: str | None = None,
        actor_kind: str = "local_user",
        actor_id: str | None = None,
    ) -> InventoryMutationResult:
        kind = validate_logistics_event_kind(event_kind)
        accepted = validate_logistics_participants(participants)
        participant_pairs = tuple(
            (item.participant_kind, item.participant_id) for item in accepted
        )
        effective = (
            None
            if effective_at_utc is None
            else (
                effective_at_utc
                if type(effective_at_utc) is int and effective_at_utc >= 0
                else (_ for _ in ()).throw(
                    ValidationError("effective_at_utc must be non-negative or null")
                )
            )
        )
        dispatch_id = normalize_optional_uuid(dispatch_location_id, "dispatch_location_id")
        receiver_id = normalize_optional_uuid(receiver_contact_id, "receiver_contact_id")
        if custody_text is not None and (
            not isinstance(custody_text, str) or len(custody_text.encode("utf-8")) > 1024
        ):
            raise ValidationError("custody_text is invalid")
        if observed_condition is not None and (
            not isinstance(observed_condition, str)
            or len(observed_condition.encode("utf-8")) > 512
        ):
            raise ValidationError("observed_condition is invalid")
        if evidence_kind is None:
            if evidence_id is not None:
                raise ValidationError("evidence_id requires evidence_kind")
        elif evidence_kind not in {"manual", "indexed_logistics"}:
            raise ValidationError("logistics evidence kind is invalid")
        normalized_evidence_id = None if evidence_id is None else evidence_id.strip()
        event_id = new_uuid4()
        envelope = CommandEnvelope(
            command_id=command_id,
            command_type="RecordActualLogisticsEvent",
            target_type="logistics_event",
            target_id=event_id,
            semantic_payload={
                "event_kind": kind,
                "effective_at_utc": effective,
                "dispatch_location_id": dispatch_id,
                "receiver_contact_id": receiver_id,
                "custody_text": custody_text,
                "observed_condition": observed_condition,
                "participants": [
                    {"kind": p_kind, "id": p_id}
                    for p_kind, p_id in participant_pairs
                ],
                "evidence_kind": evidence_kind,
                "evidence_id": normalized_evidence_id,
            },
        )

        def prepare(uow: UnitOfWork) -> PreparedMutation:
            for p_kind, p_id in participant_pairs:
                self._repository.require_participant_identity(
                    uow.connection,
                    participant_kind=p_kind,
                    participant_id=p_id,
                )

            def apply(inner: UnitOfWork):
                actual_event_id, inserted = self._repository.record_actual_logistics_event(
                    inner.connection,
                    event_kind=kind,
                    effective_at_utc=effective,
                    dispatch_location_id=dispatch_id,
                    receiver_contact_id=receiver_id,
                    custody_text=custody_text,
                    observed_condition=observed_condition,
                    participants=participant_pairs,
                    evidence_kind=evidence_kind,
                    evidence_id=normalized_evidence_id,
                    command_id=command_id,
                )
                if actual_event_id != event_id:
                    raise IntegrityFailure("Prepared logistics event identity drifted")
                apply.participants = inserted
                refs = [AuditResultRef("logistics_event", event_id)]
                refs.extend(
                    AuditResultRef("logistics_participant", participant_id)
                    for _p_kind, participant_id in inserted
                )
                return AuditEventInput(
                    audit_event_id=new_uuid4(),
                    action_type="inventory.logistics.recorded_or_corrected",
                    action_version=1,
                    actor_kind=actor_kind,
                    actor_id=actor_id,
                    target_type="logistics_event",
                    target_id=event_id,
                    command_id=command_id,
                    payload_schema="LogisticsAuditV1",
                    payload_version=1,
                    payload={
                        "logistics_event_id": event_id,
                        "event_kind": kind,
                        "effective_at_utc": effective,
                        "participant_count": len(inserted),
                        "corrected_participant_id": None,
                        "resulting_revision": 1,
                    },
                    resulting_event_refs=tuple(refs),
                )

            apply.participants = ()
            return PreparedMutation(
                no_change=False,
                result_type="logistics_event",
                result_id=event_id,
                apply=apply,
                response_schema="InventoryMutationResultV1",
                response_factory=lambda _inner: self._response(
                    [("logistics_event", event_id)]
                    + [
                        ("logistics_participant", participant_id)
                        for _p_kind, participant_id in apply.participants
                    ],
                    {f"logistics_event:{event_id}": 1},
                ),
            )

        return inventory_mutation_result_from_execution(
            self._boundary.execute(envelope, prepare)
        )

    def correct_logistics_participant(
        self,
        *,
        command_id: str,
        participant_id: str,
        replacement: LogisticsParticipantIntent | None,
        reason_code: str,
        actor_kind: str = "local_user",
        actor_id: str | None = None,
    ) -> InventoryMutationResult:
        participant = require_uuid4(participant_id)
        reason = reason_code.strip() if isinstance(reason_code, str) else ""
        if not reason or len(reason.encode("utf-8")) > 384:
            raise ValidationError("reason_code is invalid")
        replacement_kind = None
        replacement_id = None
        if replacement is not None:
            replacement.validate()
            replacement_kind = replacement.participant_kind
            replacement_id = replacement.participant_id
        envelope = CommandEnvelope(
            command_id=command_id,
            command_type="CorrectLogisticsParticipant",
            target_type="logistics_participant",
            target_id=participant,
            semantic_payload={
                "replacement_kind": replacement_kind,
                "replacement_id": replacement_id,
                "reason_code": reason,
            },
        )

        def prepare(uow: UnitOfWork) -> PreparedMutation:
            _kind, event_id, _target_id, active = self._repository.locate_participant(
                uow.connection, participant
            )
            if active != "1":
                raise SomaError("CORRECTION_TARGET_INVALID", "Logistics participant is not active")

            def apply(inner: UnitOfWork):
                actual_event_id, _old_kind, replacement_participant_id = (
                    self._repository.correct_logistics_participant(
                        inner.connection,
                        participant_id=participant,
                        replacement_kind=replacement_kind,
                        replacement_id=replacement_id,
                        reason_code=reason,
                        command_id=command_id,
                    )
                )
                apply.event_id = actual_event_id
                apply.replacement_participant_id = replacement_participant_id
                refs = [AuditResultRef("logistics_participant", participant)]
                if replacement_participant_id is not None:
                    refs.append(
                        AuditResultRef(
                            "logistics_participant", replacement_participant_id
                        )
                    )
                return AuditEventInput(
                    audit_event_id=new_uuid4(),
                    action_type="inventory.logistics.recorded_or_corrected",
                    action_version=1,
                    actor_kind=actor_kind,
                    actor_id=actor_id,
                    target_type="logistics_event",
                    target_id=actual_event_id,
                    command_id=command_id,
                    reason_category=reason,
                    payload_schema="LogisticsAuditV1",
                    payload_version=1,
                    payload={
                        "logistics_event_id": actual_event_id,
                        "event_kind": "correction",
                        "effective_at_utc": None,
                        "participant_count": 1 + int(replacement_participant_id is not None),
                        "corrected_participant_id": participant,
                        "resulting_revision": 1,
                    },
                    resulting_event_refs=tuple(refs),
                )

            apply.event_id = event_id
            apply.replacement_participant_id = None
            return PreparedMutation(
                no_change=False,
                result_type="logistics_participant",
                result_id=participant,
                apply=apply,
                response_schema="InventoryMutationResultV1",
                response_factory=lambda _inner: self._response(
                    [("logistics_participant", participant)]
                    + (
                        []
                        if apply.replacement_participant_id is None
                        else [
                            (
                                "logistics_participant",
                                apply.replacement_participant_id,
                            )
                        ]
                    ),
                    {f"logistics_event:{apply.event_id}": 1},
                ),
            )

        return inventory_mutation_result_from_execution(
            self._boundary.execute(envelope, prepare)
        )


__all__ = ["InventoryConsequencesLogisticsService"]
