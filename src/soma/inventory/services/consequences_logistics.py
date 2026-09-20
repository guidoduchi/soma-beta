from __future__ import annotations

import hashlib

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
from soma.foundation.strict_json import sha256_canonical_json
from soma.objectives_tasks.queries.tasks import TaskOperationalEvidenceReader

from ..audit_registry import build_inventory_audit_registry
from ..contracts.inventory import (
    InventoryMutationResult,
    inventory_mutation_result_from_execution,
)
from ..domain.consequences import PhysicalConsequenceIntent
from ..domain.logistics import (
    LogisticsParticipants,
    normalize_optional_logistics_text,
    validate_logistics_event_kind,
    validate_logistics_time,
)
from ..domain.rmas import validate_optional_evidence
from ..domain.units import (
    initial_disposition_for_condition,
    normalize_spare_part_identity,
    validate_spare_condition,
)
from ..domain.needs import validate_reason_code
from ..repositories.logistics import InventoryLogisticsRepository
from ..repositories.projections import InventoryPhysicalConsequenceRepository
from ..repositories.rmas import InventoryRmasRepository


class InventoryConsequencesLogisticsService:
    def __init__(self, connection_factory: ConnectionFactory) -> None:
        self._factory = connection_factory
        self._logistics = InventoryLogisticsRepository()
        self._rmas = InventoryRmasRepository()
        self._consequences = InventoryPhysicalConsequenceRepository()
        self._boundary = CommandBoundary(
            connection_factory,
            AuditWriter(build_inventory_audit_registry()),
        )

    @staticmethod
    def _fingerprint(value: str | None) -> str | None:
        if value is None:
            return None
        return hashlib.sha256(value.encode("utf-8", errors="strict")).hexdigest()

    @staticmethod
    def _response(
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
        custody_text: str | None = None,
        evidence_kind: str | None = None,
        evidence_id: str | None = None,
        actor_kind: str = "local_user",
        actor_id: str | None = None,
    ) -> InventoryMutationResult:
        identity = require_uuid4(rma_id)
        (
            stored_bom,
            bom_key,
            stored_serial,
            serial_key,
        ) = normalize_spare_part_identity(
            actual_bom_code,
            manufacturer_serial,
        )
        condition = validate_spare_condition(condition_token)
        disposition = initial_disposition_for_condition(condition)
        effective = validate_logistics_time(effective_at_utc)
        location_id = (
            None
            if dispatch_location_id is None
            else require_uuid4(dispatch_location_id)
        )
        receiver_id = (
            None
            if receiver_contact_id is None
            else require_uuid4(receiver_contact_id)
        )
        custody = normalize_optional_logistics_text(
            custody_text,
            field="custody_text",
        )
        evidence_kind_value, evidence_id_value = validate_optional_evidence(
            evidence_kind,
            evidence_id,
        )
        if evidence_kind_value is not None:
            raise SomaError(
                "DEPENDENCY_INDETERMINATE",
                "RMA receipt evidence validator is unavailable",
            )

        envelope = CommandEnvelope(
            command_id=command_id,
            command_type="RecordRmaInboundReceipt",
            target_type="rma",
            target_id=identity,
            semantic_payload={
                "actual_bom_code": stored_bom,
                "actual_bom_key": bom_key,
                "manufacturer_serial": stored_serial,
                "serial_key": serial_key,
                "condition_token": condition,
                "effective_at_utc": effective,
                "dispatch_location_id": location_id,
                "receiver_contact_id": receiver_id,
                "custody_text": custody,
                "evidence_kind": evidence_kind_value,
                "evidence_id": evidence_id_value,
            },
        )

        def prepare(uow: UnitOfWork) -> PreparedMutation:
            current = self._rmas.current_rma(uow.connection, identity)
            if current is None:
                raise SomaError("INV_STALE", "RMA no longer exists")
            if uow.connection.execute(
                "SELECT 1 FROM rma_direct_inbound_units WHERE rma_id=?",
                (identity,),
            ).fetchone() is not None:
                raise SomaError("RMA_INBOUND_EXISTS", "RMA already has a direct inbound unit")
            reference_context = self._logistics.reference_context(
                uow.connection,
                dispatch_location_id=location_id,
                receiver_contact_id=receiver_id,
            )
            spare_part_unit_id = new_uuid4()

            def apply(inner: UnitOfWork):
                result = self._logistics.record_rma_inbound_receipt(
                    inner.connection,
                    rma_id=identity,
                    spare_part_unit_id=spare_part_unit_id,
                    actual_bom_code=stored_bom,
                    actual_bom_key=bom_key,
                    manufacturer_serial=stored_serial,
                    serial_key=serial_key,
                    condition_token=condition,
                    disposition_token=disposition,
                    effective_at_utc=effective,
                    reference_context=reference_context,
                    custody_text=custody,
                    evidence_kind=evidence_kind_value,
                    evidence_id=evidence_id_value,
                    command_id=command_id,
                )
                apply.result = result
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
                        "receipt_event_id": str(result["received_event_id"]),
                        "logistics_event_id": str(result["logistics_event_id"]),
                        "actual_bom_fingerprint": self._fingerprint(bom_key),
                        "actual_serial_fingerprint": self._fingerprint(serial_key),
                        "effective_at_utc": effective,
                    },
                    resulting_event_refs=(
                        AuditResultRef("spare_part_unit", spare_part_unit_id),
                        AuditResultRef(
                            "logistics_event",
                            str(result["logistics_event_id"]),
                        ),
                    ),
                )


            apply.result = {}
            return PreparedMutation(
                no_change=False,
                result_type="spare_part_unit",
                result_id=spare_part_unit_id,
                apply=apply,
                response_schema="InventoryMutationResultV1",
                response_factory=lambda _inner: self._response(
                    [
                        ("spare_part_unit", spare_part_unit_id),
                        (
                            "logistics_event",
                            str(apply.result["logistics_event_id"]),
                        ),
                    ],
                    {
                        f"spare_part_unit:{spare_part_unit_id}": int(
                            apply.result["unit_revision"]
                        ),
                        f"rma:{identity}": int(apply.result["rma_revision"]),
                    },
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
        intent: PhysicalConsequenceIntent,
        target_device_part_unit_id: str | None = None,
        rma_id: str | None = None,
        actor_kind: str = "local_user",
        actor_id: str | None = None,
    ) -> InventoryMutationResult:
        task = require_uuid4(task_id)
        target = (
            None
            if target_device_part_unit_id is None
            else require_uuid4(target_device_part_unit_id)
        )
        rma = None if rma_id is None else require_uuid4(rma_id)
        accepted = intent.validate()
        extracted_children = tuple(
            {
                "bom_code": stored_bom,
                "bom_key": bom_key,
                "manufacturer_serial": stored_serial,
                "serial_key": serial_key,
                "condition_token": condition,
                "disposition_token": initial_disposition_for_condition(condition),
            }
            for child in accepted.extracted_units
            for stored_bom, bom_key, stored_serial, serial_key in (
                normalize_spare_part_identity(
                    child.bom_code,
                    child.manufacturer_serial,
                ),
            )
            for condition in (validate_spare_condition(child.condition_token),)
        )
        if (
            not isinstance(task_review_fingerprint, str)
            or len(task_review_fingerprint) != 64
            or any(
                character not in "0123456789abcdef"
                for character in task_review_fingerprint
            )
        ):
            raise ValidationError("task_review_fingerprint must be lowercase SHA-256")

        envelope = CommandEnvelope(
            command_id=command_id,
            command_type="AcceptInventoryPhysicalConsequence",
            target_type="task",
            target_id=task,
            semantic_payload={
                "target_device_part_unit_id": target,
                "rma_id": rma,
                "physical_disposition": accepted.physical_disposition,
                "installed_spare_part_unit_id": accepted.installed_spare_part_unit_id,
                "removed_device_part_unit_id": accepted.removed_device_part_unit_id,
                "inbound_spare_part_unit_id": accepted.inbound_spare_part_unit_id,
                "parent_dismantled_unit_id": accepted.parent_dismantled_unit_id,
                "explicit_return_device_part_unit_id": (
                    accepted.explicit_return_device_part_unit_id
                ),
                "explicit_return_spare_part_unit_id": (
                    accepted.explicit_return_spare_part_unit_id
                ),
                "effective_at_utc": accepted.effective_at_utc,
                "extracted_units": [
                    {
                        "bom_code": child["bom_code"],
                        "bom_key": child["bom_key"],
                        "manufacturer_serial": child["manufacturer_serial"],
                        "serial_key": child["serial_key"],
                        "condition_token": child["condition_token"],
                        "disposition_token": child["disposition_token"],
                    }
                    for child in extracted_children
                ],
            },
            authorizing_fingerprints={
                "task_review_fingerprint": task_review_fingerprint,
            },
        )

        def require_task_authority(connection) -> None:
            outcome = TaskOperationalEvidenceReader.task_outcome(connection, task)
            if outcome is None:
                raise SomaError(
                    "TASK_REVIEW_STALE",
                    "Task has no accepted reviewed outcome",
                )
            current_fingerprint = TaskOperationalEvidenceReader.review_fingerprint(
                connection,
                task,
            )
            if current_fingerprint != task_review_fingerprint:
                raise SomaError(
                    "TASK_REVIEW_STALE",
                    "Task operational evidence changed after review",
                )

        def prepare(uow: UnitOfWork) -> PreparedMutation:
            require_task_authority(uow.connection)
            self._consequences.require_context(
                uow.connection,
                task_id=task,
                rma_id=rma,
                target_device_part_unit_id=target,
                intent=accepted,
            )
            physical_consequence_id = new_uuid4()

            def apply(inner: UnitOfWork):
                require_task_authority(inner.connection)
                result = self._consequences.accept(
                    inner.connection,
                    physical_consequence_id=physical_consequence_id,
                    task_id=task,
                    task_review_fingerprint=task_review_fingerprint,
                    target_device_part_unit_id=target,
                    rma_id=rma,
                    intent=accepted,
                    extracted_children=extracted_children,
                    command_id=command_id,
                )
                apply.result = result
                consequence_audit = AuditEventInput(
                    audit_event_id=new_uuid4(),
                    action_type=(
                        "inventory.task_physical_consequence."
                        "accepted_or_corrected"
                    ),
                    action_version=1,
                    actor_kind=actor_kind,
                    actor_id=actor_id,
                    target_type="task",
                    target_id=task,
                    command_id=command_id,
                    payload_schema="PhysicalConsequenceAuditV1",
                    payload_version=1,
                    payload={
                        "physical_consequence_id": physical_consequence_id,
                        "task_id": task,
                        "task_review_fingerprint": task_review_fingerprint,
                        "event_kind": "ACCEPT",
                        "disposition": accepted.physical_disposition,
                        "return_obligation_id": rma,
                        "resulting_revision": int(
                            result["consequence_revision"]
                        ),
                    },
                    resulting_event_refs=tuple(
                        AuditResultRef(result_type, result_id)
                        for result_type, result_id in result["refs"]
                        if result_type
                        in {
                            "inventory_physical_consequence",
                            "rma_return_obligation",
                        }
                    ),
                )
                child_audits = tuple(
                    AuditEventInput(
                        audit_event_id=new_uuid4(),
                        action_type="inventory.spare_unit.registered_or_reserved",
                        action_version=1,
                        actor_kind=actor_kind,
                        actor_id=actor_id,
                        target_type="spare_part_unit",
                        target_id=str(child["spare_part_unit_id"]),
                        command_id=command_id,
                        payload_schema="SpareUnitAuditV1",
                        payload_version=1,
                        payload={
                            "spare_part_unit_id": str(child["spare_part_unit_id"]),
                            "event_kind": "REGISTER",
                            "task_id": task,
                            "allocation_id": None,
                            "spare_need_id": None,
                            "resulting_revision": int(child["revision"]),
                        },
                        resulting_event_refs=(
                            AuditResultRef(
                                "spare_part_unit",
                                str(child["spare_part_unit_id"]),
                            ),
                        ),
                    )
                    for child in result["extracted_units"]
                )
                return (consequence_audit, *child_audits)

            apply.result = {}
            return PreparedMutation(
                no_change=False,
                result_type="inventory_physical_consequence",
                result_id=physical_consequence_id,
                apply=apply,
                response_schema="InventoryMutationResultV1",
                response_factory=lambda _inner: self._response(
                    list(apply.result["refs"]),
                    {
                        f"inventory_physical_consequence:{physical_consequence_id}": int(
                            apply.result["consequence_revision"]
                        ),
                        **(
                            {}
                            if rma is None
                            else {
                                f"rma_return_obligation:{rma}": int(
                                    apply.result["obligation_revision"]
                                ),
                                f"rma:{rma}": int(
                                    apply.result["rma_revision"]
                                ),
                            }
                        ),
                        **{
                            f"spare_part_unit:{child['spare_part_unit_id']}": int(
                                child["revision"]
                            )
                            for child in apply.result["extracted_units"]
                        },
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
        participants: LogisticsParticipants,
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
        if kind == "correction":
            raise ValidationError(
                "correction logistics occurrence is reserved for targeted correction workflow"
            )
        accepted_participants = participants.validate()
        effective = validate_logistics_time(effective_at_utc)
        location_id = (
            None
            if dispatch_location_id is None
            else require_uuid4(dispatch_location_id)
        )
        receiver_id = (
            None
            if receiver_contact_id is None
            else require_uuid4(receiver_contact_id)
        )
        custody = normalize_optional_logistics_text(
            custody_text,
            field="custody_text",
        )
        condition = normalize_optional_logistics_text(
            observed_condition,
            field="observed_condition",
            max_graphemes=160,
            max_utf8_bytes=640,
        )
        evidence_kind_value, evidence_id_value = validate_optional_evidence(
            evidence_kind,
            evidence_id,
        )
        if evidence_kind_value is not None:
            raise SomaError(
                "DEPENDENCY_INDETERMINATE",
                "Actual logistics evidence validator is unavailable",
            )

        event_id = new_uuid4()
        envelope = CommandEnvelope(
            command_id=command_id,
            command_type="RecordActualLogisticsEvent",
            target_type="logistics_event",
            target_id=event_id,
            semantic_payload={
                "event_kind": kind,
                "effective_at_utc": effective,
                "dispatch_location_id": location_id,
                "receiver_contact_id": receiver_id,
                "custody_text": custody,
                "observed_condition": condition,
                "participants": {
                    "rma_ids": list(accepted_participants.rma_ids),
                    "spare_part_unit_ids": list(
                        accepted_participants.spare_part_unit_ids
                    ),
                    "device_part_unit_ids": list(
                        accepted_participants.device_part_unit_ids
                    ),
                },
                "evidence_kind": evidence_kind_value,
                "evidence_id": evidence_id_value,
            },
        )

        def prepare(uow: UnitOfWork) -> PreparedMutation:
            reference_context = self._logistics.reference_context(
                uow.connection,
                dispatch_location_id=location_id,
                receiver_contact_id=receiver_id,
            )
            self._logistics.require_participants(
                uow.connection,
                rma_ids=accepted_participants.rma_ids,
                spare_part_unit_ids=accepted_participants.spare_part_unit_ids,
                device_part_unit_ids=accepted_participants.device_part_unit_ids,
            )

            def apply(inner: UnitOfWork):
                inserted_event_id, participant_refs = (
                    self._logistics.insert_logistics_event(
                        inner.connection,
                        event_kind=kind,
                        effective_at_utc=effective,
                        reference_context=reference_context,
                        custody_text=custody,
                        observed_condition=condition,
                        rma_ids=accepted_participants.rma_ids,
                        spare_part_unit_ids=accepted_participants.spare_part_unit_ids,
                        device_part_unit_ids=accepted_participants.device_part_unit_ids,
                        evidence_kind=evidence_kind_value,
                        evidence_id=evidence_id_value,
                        reason_code=None,
                        target_event_id=None,
                        command_id=command_id,
                        logistics_event_id=event_id,
                    )
                )
                if inserted_event_id != event_id:
                    raise SomaError(
                        "INV_STALE",
                        "Actual logistics event identity changed unexpectedly",
                    )
                apply.participant_refs = participant_refs
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
                        "participant_count": len(participant_refs),
                        "corrected_participant_id": None,
                        "resulting_revision": 1,
                    },
                    resulting_event_refs=(
                        AuditResultRef("logistics_event", event_id),
                    ),
                )

            apply.participant_refs = ()
            return PreparedMutation(
                no_change=False,
                result_type="logistics_event",
                result_id=event_id,
                apply=apply,
                response_schema="InventoryMutationResultV1",
                response=self._response(
                    [("logistics_event", event_id)],
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
        reason_code: str,
        actor_kind: str = "local_user",
        actor_id: str | None = None,
    ) -> InventoryMutationResult:
        identity = require_uuid4(participant_id)
        reason = validate_reason_code(reason_code)
        envelope = CommandEnvelope(
            command_id=command_id,
            command_type="CorrectLogisticsParticipant",
            target_type="logistics_participant",
            target_id=identity,
            semantic_payload={"reason_code": reason},
        )

        def prepare(uow: UnitOfWork) -> PreparedMutation:
            located = self._logistics.locate_participant(
                uow.connection,
                identity,
            )
            if located is None or located[3] != 1:
                raise SomaError(
                    "CORRECTION_TARGET_INVALID",
                    "Logistics participant is not current-active",
                )
            logistics_event_id = str(located[2])

            def apply(inner: UnitOfWork):
                _kind, event_id = self._logistics.close_participant(
                    inner.connection,
                    participant_id=identity,
                    reason_code=reason,
                    command_id=command_id,
                )
                if event_id != logistics_event_id:
                    raise SomaError(
                        "INV_STALE",
                        "Logistics participant event changed unexpectedly",
                    )
                return AuditEventInput(
                    audit_event_id=new_uuid4(),
                    action_type="inventory.logistics.recorded_or_corrected",
                    action_version=1,
                    actor_kind=actor_kind,
                    actor_id=actor_id,
                    target_type="logistics_event",
                    target_id=logistics_event_id,
                    command_id=command_id,
                    reason_category=reason,
                    payload_schema="LogisticsAuditV1",
                    payload_version=1,
                    payload={
                        "logistics_event_id": logistics_event_id,
                        "event_kind": "correction",
                        "effective_at_utc": None,
                        "participant_count": 1,
                        "corrected_participant_id": identity,
                        "resulting_revision": 2,
                    },
                    resulting_event_refs=(
                        AuditResultRef("logistics_event", logistics_event_id),
                        AuditResultRef("logistics_participant", identity),
                    ),
                )

            return PreparedMutation(
                no_change=False,
                result_type="logistics_participant",
                result_id=identity,
                apply=apply,
                response_schema="InventoryMutationResultV1",
                response=self._response(
                    [
                        ("logistics_participant", identity),
                        ("logistics_event", logistics_event_id),
                    ],
                    {f"logistics_participant:{identity}": 2},
                ),
            )

        return inventory_mutation_result_from_execution(
            self._boundary.execute(envelope, prepare)
        )


__all__ = ["InventoryConsequencesLogisticsService"]
