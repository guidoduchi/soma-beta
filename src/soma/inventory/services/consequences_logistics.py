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
from ..domain.logistics import normalize_optional_uuid, validate_receipt_identity
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

            apply.unit_id = ""
            apply.logistics_id = ""
            apply.unit_event_id = ""
            apply.unit_revision = 1
            apply.rma_revision = int(rma[9]) + 1
            return PreparedMutation(
                no_change=False,
                result_type="spare_part_unit",
                result_id=None,
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

        execution = self._boundary.execute(envelope, prepare)
        # result identity is allocated inside apply, so bind the material receipt result
        # through the exact response refs rather than inventing a provisional unit id.
        if execution.result_type == "spare_part_unit" and execution.result_id is None:
            # CommandBoundary requires a material result identity; this branch is unreachable
            # once apply publishes the allocated unit. Keep fail-closed if runtime semantics change.
            raise IntegrityFailure("Inbound receipt did not bind material result identity")
        return inventory_mutation_result_from_execution(execution)


__all__ = ["InventoryConsequencesLogisticsService"]
