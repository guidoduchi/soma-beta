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
from soma.foundation.persistence.uow import ReadSnapshot, UnitOfWork

from ..audit_registry import build_inventory_audit_registry
from ..contracts.inventory import (
    InventoryMutationResult,
    inventory_mutation_result_from_execution,
)
from soma.objectives_tasks.queries.tasks import TaskOperationalEvidenceReader

from ..domain.consequences import (
    optional_uuid as consequence_optional_uuid,
    validate_consequence_shape,
    validate_disposition,
    validate_effective_at_utc as validate_consequence_effective_at_utc,
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
from ..repositories.projections import InventoryProjectionsRepository


class InventoryConsequencesLogisticsService:
    def __init__(self, connection_factory: ConnectionFactory) -> None:
        self._factory = connection_factory
        self._repository = InventoryLogisticsRepository()
        self._projections = InventoryProjectionsRepository()
        self._task_evidence = TaskOperationalEvidenceReader()
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
                    recorded_spare_part_unit_id,
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
                if recorded_spare_part_unit_id != spare_part_unit_id:
                    raise IntegrityFailure("RMA receipt returned a different pre-bound Spare Part Unit identity")
                apply.unit_id = recorded_spare_part_unit_id
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
                    logistics_event_id=event_id,
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


    def accept_inventory_physical_consequence(
        self,
        *,
        command_id: str,
        task_id: str,
        task_review_fingerprint: str,
        physical_disposition: str,
        target_device_part_unit_id: str | None = None,
        rma_id: str | None = None,
        installed_spare_part_unit_id: str | None = None,
        removed_device_part_unit_id: str | None = None,
        inbound_spare_part_unit_id: str | None = None,
        parent_dismantled_unit_id: str | None = None,
        effective_at_utc: int | None = None,
        actor_kind: str = "local_user",
        actor_id: str | None = None,
    ) -> InventoryMutationResult:
        task = require_uuid4(task_id)
        if (
            not isinstance(task_review_fingerprint, str)
            or regex.fullmatch(r"[0-9a-f]{64}", task_review_fingerprint) is None
        ):
            raise ValidationError("task_review_fingerprint must be lowercase SHA-256 hex")
        disposition = validate_disposition(physical_disposition)
        target_device = consequence_optional_uuid(
            target_device_part_unit_id, "target_device_part_unit_id"
        )
        rma = consequence_optional_uuid(rma_id, "rma_id")
        installed = consequence_optional_uuid(
            installed_spare_part_unit_id, "installed_spare_part_unit_id"
        )
        removed = consequence_optional_uuid(
            removed_device_part_unit_id, "removed_device_part_unit_id"
        )
        inbound = consequence_optional_uuid(
            inbound_spare_part_unit_id, "inbound_spare_part_unit_id"
        )
        parent = consequence_optional_uuid(
            parent_dismantled_unit_id, "parent_dismantled_unit_id"
        )
        effective = validate_consequence_effective_at_utc(effective_at_utc)
        selection = validate_consequence_shape(
            disposition=disposition,
            installed_spare_part_unit_id=installed,
            removed_device_part_unit_id=removed,
            inbound_spare_part_unit_id=inbound,
            parent_dismantled_unit_id=parent,
        )
        with ReadSnapshot(self._factory) as snapshot:
            outcome = self._task_evidence.task_outcome(snapshot, task)
            if outcome is None:
                raise SomaError(
                    "TASK_REVIEW_STALE",
                    "Inventory physical consequence requires reviewed Task outcome",
                )
            current_fingerprint = self._task_evidence.review_fingerprint(snapshot, task)
            if current_fingerprint != task_review_fingerprint:
                raise SomaError(
                    "TASK_REVIEW_STALE",
                    "Task operational review fingerprint changed",
                )

        consequence_id = new_uuid4()
        envelope = CommandEnvelope(
            command_id=command_id,
            command_type="AcceptInventoryPhysicalConsequence",
            target_type="inventory_physical_consequence",
            target_id=consequence_id,
            semantic_payload={
                "task_id": task,
                "physical_disposition": disposition,
                "target_device_part_unit_id": target_device,
                "rma_id": rma,
                "installed_spare_part_unit_id": installed,
                "removed_device_part_unit_id": removed,
                "inbound_spare_part_unit_id": inbound,
                "parent_dismantled_unit_id": parent,
                "effective_at_utc": effective,
            },
            authorizing_fingerprints={"task_review": task_review_fingerprint},
        )

        def prepare(uow: UnitOfWork) -> PreparedMutation:
            outcome = self._task_evidence.task_outcome(uow, task)
            if outcome is None:
                raise SomaError(
                    "TASK_REVIEW_STALE",
                    "Reviewed Task outcome disappeared before consequence commit",
                )
            current_fingerprint = self._task_evidence.review_fingerprint(uow, task)
            if current_fingerprint != task_review_fingerprint:
                raise SomaError(
                    "TASK_REVIEW_STALE",
                    "Task operational review fingerprint changed before consequence commit",
                )
            self._projections.require_no_current_task_consequence(uow.connection, task)

            def apply(inner: UnitOfWork):
                result = self._projections.accept_physical_consequence(
                    inner.connection,
                    physical_consequence_id=consequence_id,
                    task_id=task,
                    task_review_fingerprint=task_review_fingerprint,
                    target_device_part_unit_id=target_device,
                    rma_id=rma,
                    disposition=disposition,
                    installed_spare_part_unit_id=installed,
                    removed_device_part_unit_id=removed,
                    inbound_spare_part_unit_id=inbound,
                    parent_dismantled_unit_id=parent,
                    effective_at_utc=effective,
                    selection=selection,
                    command_id=command_id,
                )
                apply.result = result
                refs = [AuditResultRef("inventory_physical_consequence", consequence_id)]
                if rma is not None and result["obligation_revision"] is not None:
                    refs.append(AuditResultRef("rma_return_obligation", rma))
                return AuditEventInput(
                    audit_event_id=new_uuid4(),
                    action_type="inventory.task_physical_consequence.accepted_or_corrected",
                    action_version=1,
                    actor_kind=actor_kind,
                    actor_id=actor_id,
                    target_type="task",
                    target_id=task,
                    command_id=command_id,
                    payload_schema="PhysicalConsequenceAuditV1",
                    payload_version=1,
                    payload={
                        "physical_consequence_id": consequence_id,
                        "task_id": task,
                        "task_review_fingerprint": task_review_fingerprint,
                        "event_kind": "ACCEPT",
                        "disposition": disposition,
                        "return_obligation_id": (
                            rma
                            if result["obligation_revision"] is not None
                            else None
                        ),
                        "resulting_revision": int(result["consequence_revision"]),
                    },
                    resulting_event_refs=tuple(refs),
                )

            apply.result = {
                "consequence_revision": 1,
                "obligation_revision": None,
            }
            return PreparedMutation(
                no_change=False,
                result_type="inventory_physical_consequence",
                result_id=consequence_id,
                apply=apply,
                response_schema="InventoryMutationResultV1",
                response_factory=lambda _inner: self._response(
                    [("inventory_physical_consequence", consequence_id)]
                    + (
                        []
                        if rma is None
                        or apply.result["obligation_revision"] is None
                        else [("rma_return_obligation", rma)]
                    ),
                    {
                        f"inventory_physical_consequence:{consequence_id}": int(
                            apply.result["consequence_revision"]
                        )
                    }
                    | (
                        {}
                        if rma is None
                        or apply.result["obligation_revision"] is None
                        else {
                            f"rma_return_obligation:{rma}": int(
                                apply.result["obligation_revision"]
                            )
                        }
                    ),
                ),
            )

        return inventory_mutation_result_from_execution(
            self._boundary.execute(envelope, prepare)
        )

    def correct_inventory_physical_consequence(
        self,
        *,
        command_id: str,
        physical_consequence_id: str,
        expected_revision: int,
        expected_event_id: str,
        task_review_fingerprint: str,
        physical_disposition: str,
        installed_spare_part_unit_id: str | None = None,
        removed_device_part_unit_id: str | None = None,
        inbound_spare_part_unit_id: str | None = None,
        parent_dismantled_unit_id: str | None = None,
        effective_at_utc: int | None = None,
        reason_code: str,
        actor_kind: str = "local_user",
        actor_id: str | None = None,
    ) -> InventoryMutationResult:
        identity = require_uuid4(physical_consequence_id)
        if type(expected_revision) is not int or expected_revision <= 0:
            raise ValidationError("expected_revision must be positive")
        current_event = require_uuid4(expected_event_id)
        if (
            not isinstance(task_review_fingerprint, str)
            or regex.fullmatch(r"[0-9a-f]{64}", task_review_fingerprint) is None
        ):
            raise ValidationError("task_review_fingerprint must be lowercase SHA-256 hex")
        disposition = validate_disposition(physical_disposition)
        installed = consequence_optional_uuid(
            installed_spare_part_unit_id, "installed_spare_part_unit_id"
        )
        removed = consequence_optional_uuid(
            removed_device_part_unit_id, "removed_device_part_unit_id"
        )
        inbound = consequence_optional_uuid(
            inbound_spare_part_unit_id, "inbound_spare_part_unit_id"
        )
        parent = consequence_optional_uuid(
            parent_dismantled_unit_id, "parent_dismantled_unit_id"
        )
        effective = validate_consequence_effective_at_utc(effective_at_utc)
        selection = validate_consequence_shape(
            disposition=disposition,
            installed_spare_part_unit_id=installed,
            removed_device_part_unit_id=removed,
            inbound_spare_part_unit_id=inbound,
            parent_dismantled_unit_id=parent,
        )
        reason = reason_code.strip() if isinstance(reason_code, str) else ""
        if not reason or len(reason.encode("utf-8", errors="strict")) > 384:
            raise ValidationError("reason_code is invalid")

        with ReadSnapshot(self._factory) as snapshot:
            current = self._projections.current_physical_consequence(
                snapshot.connection, identity
            )
            if current is None:
                raise SomaError("CORRECTION_TARGET_INVALID", "Physical consequence is missing")
            task_id = str(current[1])
            if int(current[10]) != expected_revision or str(current[12]) != current_event:
                raise SomaError("INV_STALE", "Physical consequence changed")
            if self._task_evidence.review_fingerprint(snapshot, task_id) != task_review_fingerprint:
                raise SomaError("TASK_REVIEW_STALE", "Task review fingerprint changed")

        envelope = CommandEnvelope(
            command_id=command_id,
            command_type="CorrectInventoryPhysicalConsequence",
            target_type="inventory_physical_consequence",
            target_id=identity,
            semantic_payload={
                "expected_event_id": current_event,
                "physical_disposition": disposition,
                "installed_spare_part_unit_id": installed,
                "removed_device_part_unit_id": removed,
                "inbound_spare_part_unit_id": inbound,
                "parent_dismantled_unit_id": parent,
                "effective_at_utc": effective,
                "reason_code": reason,
            },
            base_revisions={"inventory_physical_consequence": expected_revision},
            authorizing_fingerprints={"task_review": task_review_fingerprint},
        )

        def prepare(uow: UnitOfWork) -> PreparedMutation:
            current = self._projections.current_physical_consequence(
                uow.connection, identity
            )
            if (
                current is None
                or int(current[10]) != expected_revision
                or str(current[12]) != current_event
            ):
                raise SomaError("INV_STALE", "Physical consequence changed")
            task_id = str(current[1])
            if self._task_evidence.review_fingerprint(uow, task_id) != task_review_fingerprint:
                raise SomaError("TASK_REVIEW_STALE", "Task review fingerprint changed")
            rma_id = None if current[3] is None else str(current[3])

            def apply(inner: UnitOfWork):
                result = self._projections.correct_physical_consequence(
                    inner.connection,
                    physical_consequence_id=identity,
                    expected_revision=expected_revision,
                    expected_event_id=current_event,
                    task_review_fingerprint=task_review_fingerprint,
                    disposition=disposition,
                    installed_spare_part_unit_id=installed,
                    removed_device_part_unit_id=removed,
                    inbound_spare_part_unit_id=inbound,
                    parent_dismantled_unit_id=parent,
                    effective_at_utc=effective,
                    selection=selection,
                    reason_code=reason,
                    command_id=command_id,
                )
                apply.result = result
                refs = [AuditResultRef("inventory_physical_consequence", identity)]
                if rma_id is not None and result["obligation_revision"] is not None:
                    refs.append(AuditResultRef("rma_return_obligation", rma_id))
                return AuditEventInput(
                    audit_event_id=new_uuid4(),
                    action_type="inventory.task_physical_consequence.accepted_or_corrected",
                    action_version=1,
                    actor_kind=actor_kind,
                    actor_id=actor_id,
                    target_type="task",
                    target_id=task_id,
                    command_id=command_id,
                    reason_category=reason,
                    payload_schema="PhysicalConsequenceAuditV1",
                    payload_version=1,
                    payload={
                        "physical_consequence_id": identity,
                        "task_id": task_id,
                        "task_review_fingerprint": task_review_fingerprint,
                        "event_kind": "CORRECT",
                        "disposition": disposition,
                        "return_obligation_id": (
                            rma_id if result["obligation_revision"] is not None else None
                        ),
                        "resulting_revision": int(result["consequence_revision"]),
                    },
                    resulting_event_refs=tuple(refs),
                )

            apply.result = {
                "consequence_revision": expected_revision + 1,
                "obligation_revision": None,
            }
            return PreparedMutation(
                no_change=False,
                result_type="inventory_physical_consequence",
                result_id=identity,
                apply=apply,
                response_schema="InventoryMutationResultV1",
                response_factory=lambda _inner: self._response(
                    [("inventory_physical_consequence", identity)]
                    + (
                        []
                        if rma_id is None or apply.result["obligation_revision"] is None
                        else [("rma_return_obligation", rma_id)]
                    ),
                    {
                        f"inventory_physical_consequence:{identity}": int(
                            apply.result["consequence_revision"]
                        )
                    }
                    | (
                        {}
                        if rma_id is None or apply.result["obligation_revision"] is None
                        else {
                            f"rma_return_obligation:{rma_id}": int(
                                apply.result["obligation_revision"]
                            )
                        }
                    ),
                ),
            )

        return inventory_mutation_result_from_execution(
            self._boundary.execute(envelope, prepare)
        )


__all__ = ["InventoryConsequencesLogisticsService"]
