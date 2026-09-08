from __future__ import annotations

from dataclasses import dataclass

from soma.foundation.application.command_boundary import (
    CommandBoundary,
    CommandEnvelope,
    CommandExecutionResult,
    PreparedMutation,
)
from soma.foundation.audit.writer import AuditEventInput, AuditResultRef, AuditWriter
from soma.foundation.errors import SomaError
from soma.foundation.identifiers import new_uuid4, require_uuid4, utc_epoch_seconds
from soma.foundation.persistence.connections import ConnectionFactory
from soma.foundation.persistence.uow import ReadSnapshot, UnitOfWork
from soma.reference.audit_registry import build_reference_audit_registry
from soma.reference.domain.validation import validate_display_name


@dataclass(frozen=True, slots=True)
class LocalUserProfile:
    local_user_profile_id: str
    display_name: str
    revision: int


class LocalUserProfileService:
    def __init__(self, connection_factory: ConnectionFactory) -> None:
        self._factory = connection_factory
        self._audit_writer = AuditWriter(build_reference_audit_registry())
        self._boundary = CommandBoundary(connection_factory, self._audit_writer)

    def ensure_singleton_local_administrator(
        self,
        uow: UnitOfWork,
        *,
        parent_command_id: str,
        profile_id: str | None = None,
        default_display_name: str = "Local Administrator",
        actor_kind: str = "system",
    ) -> str:
        """LLD-12 setup participant. Uses the existing setup receipt/UoW and never commits."""
        display_name = validate_display_name(default_display_name)
        receipt = uow.connection.execute(
            "SELECT command_id FROM command_receipts WHERE command_id=?",
            (parent_command_id,),
        ).fetchone()
        if receipt is None:
            raise SomaError("PERSISTENCE_FAILURE", "parent setup receipt is required")
        existing = uow.connection.execute(
            "SELECT local_user_profile_id FROM local_user_profiles WHERE singleton_guard=1"
        ).fetchone()
        if existing is not None:
            raise SomaError("SINGLETON_PROFILE_EXISTS", "Local User Profile already exists")
        assigned_id = profile_id or new_uuid4()
        require_uuid4(assigned_id)
        now = utc_epoch_seconds()
        uow.connection.execute(
            "INSERT INTO local_user_profiles(local_user_profile_id,singleton_guard,display_name,revision,created_at_utc,updated_at_utc) "
            "VALUES (?, 1, ?, 1, ?, ?)",
            (assigned_id, display_name, now, now),
        )
        self._audit_writer.write(
            uow,
            AuditEventInput(
                audit_event_id=new_uuid4(),
                action_type="local_user_profile.created",
                action_version=1,
                actor_kind=actor_kind,
                actor_id=assigned_id,
                target_type="local_user_profile",
                target_id=assigned_id,
                command_id=parent_command_id,
                payload_schema="LocalUserProfileAuditV1",
                payload_version=1,
                payload={"local_user_profile_id": assigned_id, "metadata_revision": 1},
                resulting_event_refs=(AuditResultRef("local_user_profile", assigned_id),),
            ),
        )
        return assigned_id

    def get_singleton(self) -> LocalUserProfile | None:
        with ReadSnapshot(self._factory) as snapshot:
            row = snapshot.connection.execute(
                "SELECT local_user_profile_id,display_name,revision FROM local_user_profiles WHERE singleton_guard=1"
            ).fetchone()
        if row is None:
            return None
        return LocalUserProfile(str(row[0]), str(row[1]), int(row[2]))

    def update_display_name(
        self,
        *,
        command_id: str,
        base_revision: int,
        display_name: str,
        actor_id: str,
    ) -> CommandExecutionResult:
        stored = validate_display_name(display_name)
        require_uuid4(actor_id)
        envelope = CommandEnvelope(
            command_id=command_id,
            command_type="UpdateLocalUserProfileDisplayName",
            target_type="local_user_profile",
            target_id=actor_id,
            semantic_payload={"display_name": stored},
            base_revisions={"local_user_profile": base_revision},
        )

        def prepare(uow: UnitOfWork) -> PreparedMutation:
            row = uow.connection.execute(
                "SELECT local_user_profile_id,display_name,revision FROM local_user_profiles WHERE singleton_guard=1"
            ).fetchone()
            if row is None:
                raise SomaError("NOT_FOUND", "Local User Profile does not exist")
            if str(row[0]) != actor_id:
                raise SomaError("NOT_FOUND", "Local User Profile actor identity does not match")
            if int(row[2]) != base_revision:
                raise SomaError("STALE_REVISION", "Local User Profile metadata revision changed")
            if str(row[1]) == stored:
                return PreparedMutation(True, None, None)
            audit_event_id = new_uuid4()
            now = utc_epoch_seconds()

            def apply(inner: UnitOfWork) -> AuditEventInput:
                inner.connection.execute(
                    "UPDATE local_user_profiles SET display_name=?,revision=revision+1,updated_at_utc=? "
                    "WHERE local_user_profile_id=?",
                    (stored, now, actor_id),
                )
                return AuditEventInput(
                    audit_event_id=audit_event_id,
                    action_type="local_user_profile.display_name_updated",
                    action_version=1,
                    actor_kind="local_user",
                    actor_id=actor_id,
                    target_type="local_user_profile",
                    target_id=actor_id,
                    command_id=command_id,
                    payload_schema="LocalUserProfileDisplayNameAuditV1",
                    payload_version=1,
                    payload={
                        "local_user_profile_id": actor_id,
                        "prior_revision": base_revision,
                        "new_revision": base_revision + 1,
                        "changed_field": "display_name",
                    },
                    resulting_event_refs=(AuditResultRef("local_user_profile", actor_id),),
                )

            return PreparedMutation(False, "local_user_profile", actor_id, apply)

        return self._boundary.execute(envelope, prepare)
