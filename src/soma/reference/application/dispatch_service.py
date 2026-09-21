from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from soma.foundation.application.command_boundary import CommandBoundary, CommandEnvelope, PreparedMutation
from soma.foundation.audit.writer import AuditEventInput, AuditResultRef, AuditWriter
from soma.foundation.errors import SomaError, ValidationError
from soma.foundation.identifiers import new_uuid4, utc_epoch_seconds
from soma.foundation.persistence.connections import ConnectionFactory
from soma.foundation.persistence.uow import UnitOfWork
from soma.reference.audit_registry import build_reference_audit_registry
from soma.reference.domain.validation import (
    validate_dispatch_name,
    validate_standalone_address,
)
from soma.reference.results import ReferenceMutationResult, reference_mutation_result_from_execution


@dataclass(frozen=True, slots=True)
class DispatchCreateResult:
    dispatch_location_id: str
    replayed: bool


class DispatchLocationService:
    def __init__(self, connection_factory: ConnectionFactory) -> None:
        self._boundary = CommandBoundary(
            connection_factory,
            AuditWriter(build_reference_audit_registry()),
        )

    @staticmethod
    def _active_dispatch(connection: Any, dispatch_location_id: str, base_revision: int | None = None) -> Any:
        row = connection.execute(
            "SELECT dispatch_location_id,name,name_match_key,address_mode,standalone_address_text,lifecycle_state,revision "
            "FROM dispatch_locations WHERE dispatch_location_id=?",
            (dispatch_location_id,),
        ).fetchone()
        if row is None:
            raise SomaError("NOT_FOUND", "Dispatch Location does not exist")
        if str(row[5]) != "active":
            raise SomaError("REFERENCE_ARCHIVED", "Dispatch Location is archived")
        if base_revision is not None and int(row[6]) != base_revision:
            raise SomaError("STALE_REVISION", "Dispatch Location revision changed")
        return row

    def create_standalone(
        self,
        *,
        command_id: str,
        name: str,
        address_text: str,
        actor_kind: str = "local_user",
        actor_id: str | None = None,
    ) -> DispatchCreateResult:
        stored_name, match_key = validate_dispatch_name(name)
        stored_address = validate_standalone_address(address_text)
        envelope = CommandEnvelope(
            command_id=command_id,
            command_type="CreateStandaloneDispatchLocation",
            target_type="dispatch_location",
            target_id=None,
            semantic_payload={"name": stored_name, "address_text": stored_address},
        )

        def prepare(uow: UnitOfWork) -> PreparedMutation:
            dispatch_id = new_uuid4()
            lifecycle_event_id = new_uuid4()
            audit_event_id = new_uuid4()
            now = utc_epoch_seconds()

            def apply(inner: UnitOfWork) -> AuditEventInput:
                inner.connection.execute(
                    "INSERT INTO dispatch_locations(dispatch_location_id,name,name_match_key,address_mode,standalone_address_text,"
                    "lifecycle_state,revision,created_at_utc,updated_at_utc) "
                    "VALUES (?, ?, ?, 'standalone', ?, 'active', 1, ?, ?)",
                    (dispatch_id, stored_name, match_key, stored_address, now, now),
                )
                inner.connection.execute(
                    "INSERT INTO reference_lifecycle_events(reference_lifecycle_event_id,target_type,target_id,event_type,"
                    "occurred_at_utc,command_id,reason_category) VALUES (?, 'dispatch_location', ?, 'created', ?, ?, NULL)",
                    (lifecycle_event_id, dispatch_id, now, command_id),
                )
                return AuditEventInput(
                    audit_event_id=audit_event_id,
                    action_type="reference.dispatch_location.created",
                    action_version=1,
                    actor_kind=actor_kind,
                    actor_id=actor_id,
                    target_type="dispatch_location",
                    target_id=dispatch_id,
                    command_id=command_id,
                    payload_schema="DispatchLocationAuditV1",
                    payload_version=1,
                    payload={
                        "dispatch_location_id": dispatch_id,
                        "address_mode": "standalone",
                        "new_revision": 1,
                        "lifecycle_event_id": lifecycle_event_id,
                    },
                    resulting_event_refs=(
                        AuditResultRef("dispatch_location", dispatch_id),
                        AuditResultRef("reference_lifecycle_event", lifecycle_event_id),
                    ),
                )

            return PreparedMutation(
                False,
                "dispatch_location",
                dispatch_id,
                apply,
                response_schema="ReferenceMutationResultV1",
                response_version=1,
                response={"outcome": "APPLIED", "target_id": dispatch_id, "revision": 1},
            )

        exact = reference_mutation_result_from_execution(self._boundary.execute(envelope, prepare))
        return DispatchCreateResult(exact.target_id, exact.replayed)

    @staticmethod
    def create_dedicated_for_site(
        uow: UnitOfWork,
        *,
        parent_command_id: str,
        name: str,
        precomputed_match_key: str,
    ) -> str:
        """LLD-08 shared-UoW participant; never inserts a second receipt or commits."""
        stored_name, computed_key = validate_dispatch_name(name)
        if computed_key != precomputed_match_key:
            raise ValidationError("precomputed Dispatch Location match key is stale or invalid")
        receipt = uow.connection.execute(
            "SELECT command_id FROM command_receipts WHERE command_id=?",
            (parent_command_id,),
        ).fetchone()
        if receipt is None:
            raise SomaError("PERSISTENCE_FAILURE", "parent command receipt must exist before shared Dispatch participant")
        dispatch_id = new_uuid4()
        lifecycle_event_id = new_uuid4()
        now = utc_epoch_seconds()
        uow.connection.execute(
            "INSERT INTO dispatch_locations(dispatch_location_id,name,name_match_key,address_mode,standalone_address_text,"
            "lifecycle_state,revision,created_at_utc,updated_at_utc) "
            "VALUES (?, ?, ?, 'site_derived', NULL, 'active', 1, ?, ?)",
            (dispatch_id, stored_name, computed_key, now, now),
        )
        uow.connection.execute(
            "INSERT INTO reference_lifecycle_events(reference_lifecycle_event_id,target_type,target_id,event_type,"
            "occurred_at_utc,command_id,reason_category) VALUES (?, 'dispatch_location', ?, 'created', ?, ?, NULL)",
            (lifecycle_event_id, dispatch_id, now, parent_command_id),
        )
        return dispatch_id

    def update_descriptive_data(
        self,
        *,
        command_id: str,
        dispatch_location_id: str,
        base_revision: int,
        name: str,
        address_text: str | None = None,
        actor_kind: str = "local_user",
        actor_id: str | None = None,
    ) -> ReferenceMutationResult:
        stored_name, match_key = validate_dispatch_name(name)
        requested_address = None if address_text is None else validate_standalone_address(address_text)
        envelope = CommandEnvelope(
            command_id=command_id,
            command_type="UpdateReferenceDescriptiveData",
            target_type="dispatch_location",
            target_id=dispatch_location_id,
            semantic_payload={"name": stored_name, "address_text": requested_address},
            base_revisions={"dispatch_location": base_revision},
        )

        def prepare(uow: UnitOfWork) -> PreparedMutation:
            row = self._active_dispatch(uow.connection, dispatch_location_id, base_revision)
            address_mode = str(row[3])
            current_address = None if row[4] is None else str(row[4])
            if address_mode == "site_derived" and requested_address is not None:
                raise ValidationError("site-derived Dispatch Location address is owned by its Site")
            effective_address = current_address if address_mode == "site_derived" else requested_address
            if address_mode == "standalone" and effective_address is None:
                raise ValidationError("standalone Dispatch Location requires address_text")
            changed_fields: list[str] = []
            if str(row[1]) != stored_name or str(row[2]) != match_key:
                changed_fields.append("name")
            if address_mode == "standalone" and current_address != effective_address:
                changed_fields.append("standalone_address_text")
            if not changed_fields:
                return PreparedMutation(
                    True,
                    None,
                    None,
                    response_schema="ReferenceMutationResultV1",
                    response_version=1,
                    response={"outcome": "NO_CHANGE", "target_id": dispatch_location_id, "revision": base_revision},
                )
            lifecycle_event_id = new_uuid4()
            audit_event_id = new_uuid4()
            now = utc_epoch_seconds()

            def apply(inner: UnitOfWork) -> AuditEventInput:
                inner.connection.execute(
                    "UPDATE dispatch_locations SET name=?,name_match_key=?,standalone_address_text=?,revision=revision+1,"
                    "updated_at_utc=? WHERE dispatch_location_id=?",
                    (stored_name, match_key, effective_address, now, dispatch_location_id),
                )
                inner.connection.execute(
                    "INSERT INTO reference_lifecycle_events(reference_lifecycle_event_id,target_type,target_id,event_type,"
                    "occurred_at_utc,command_id,reason_category) VALUES (?, 'dispatch_location', ?, 'descriptive_corrected', ?, ?, NULL)",
                    (lifecycle_event_id, dispatch_location_id, now, command_id),
                )
                return AuditEventInput(
                    audit_event_id=audit_event_id,
                    action_type="reference.dispatch_location.descriptive_updated",
                    action_version=1,
                    actor_kind=actor_kind,
                    actor_id=actor_id,
                    target_type="dispatch_location",
                    target_id=dispatch_location_id,
                    command_id=command_id,
                    payload_schema="ReferenceDescriptiveAuditV1",
                    payload_version=1,
                    payload={
                        "target_type": "dispatch_location",
                        "target_id": dispatch_location_id,
                        "prior_revision": base_revision,
                        "new_revision": base_revision + 1,
                        "changed_fields": changed_fields,
                        "lifecycle_event_id": lifecycle_event_id,
                    },
                    resulting_event_refs=(
                        AuditResultRef("dispatch_location", dispatch_location_id),
                        AuditResultRef("reference_lifecycle_event", lifecycle_event_id),
                    ),
                )

            return PreparedMutation(
                False,
                "dispatch_location",
                dispatch_location_id,
                apply,
                response_schema="ReferenceMutationResultV1",
                response_version=1,
                response={"outcome": "APPLIED", "target_id": dispatch_location_id, "revision": base_revision + 1},
            )

        return reference_mutation_result_from_execution(self._boundary.execute(envelope, prepare))
