from __future__ import annotations

from dataclasses import dataclass

from soma.foundation.application.command_boundary import CommandBoundary, CommandEnvelope, PreparedMutation
from soma.foundation.audit.writer import AuditEventInput, AuditResultRef, AuditWriter
from soma.foundation.errors import SomaError
from soma.foundation.identifiers import new_uuid4, utc_epoch_seconds
from soma.foundation.persistence.connections import ConnectionFactory
from soma.foundation.persistence.uow import ReadSnapshot, UnitOfWork

from .audit_registry import build_tickets_audit_registry
from .repositories.working_notes import WorkingNoteRecord, WorkingNoteRepository
from .validation import validate_reason_category, validate_working_note_body


@dataclass(frozen=True, slots=True)
class WorkingNoteMutationResult:
    working_note_id: str
    owner_type: str
    owner_id: str
    revision: int
    replayed: bool
    no_change: bool
    removed: bool


class WorkingNoteService:
    def __init__(self, connection_factory: ConnectionFactory) -> None:
        self._factory = connection_factory
        self._repository = WorkingNoteRepository()
        self._boundary = CommandBoundary(
            connection_factory,
            AuditWriter(build_tickets_audit_registry()),
        )

    @staticmethod
    def _authenticated_profile_id(connection) -> str:
        row = connection.execute(
            "SELECT local_user_profile_id FROM local_user_profiles WHERE singleton_guard=1"
        ).fetchone()
        if row is None:
            raise SomaError(
                "PERSISTENCE_FAILURE",
                "authenticated Local User Profile identity is unavailable",
            )
        return str(row[0])

    @staticmethod
    def _optional_reason(value: str | None) -> str | None:
        if value is None:
            return None
        return validate_reason_category(value)

    def _current_result(
        self,
        *,
        owner_type: str,
        owner_id: str,
        working_note_id: str,
        replayed: bool,
        no_change: bool,
    ) -> WorkingNoteMutationResult:
        with ReadSnapshot(self._factory) as snapshot:
            note = self._repository.get(
                snapshot.connection,
                owner_type,
                owner_id,
                working_note_id,
            )
        if note is None:
            raise SomaError("WORKING_NOTE_NOT_FOUND", "Working Note no longer exists")
        return WorkingNoteMutationResult(
            working_note_id=working_note_id,
            owner_type=owner_type,
            owner_id=owner_id,
            revision=note.revision,
            replayed=replayed,
            no_change=no_change,
            removed=False,
        )

    def add(
        self,
        *,
        command_id: str,
        owner_type: str,
        owner_id: str,
        body_text: str,
    ) -> WorkingNoteMutationResult:
        body = validate_working_note_body(body_text)
        self._repository._spec(owner_type)
        envelope = CommandEnvelope(
            command_id=command_id,
            command_type="AddWorkingNote",
            target_type=owner_type,
            target_id=owner_id,
            semantic_payload={
                "owner_type": owner_type,
                "owner_id": owner_id,
                "body_text": body,
            },
        )

        def prepare(uow: UnitOfWork) -> PreparedMutation:
            self._repository.require_owner(uow.connection, owner_type, owner_id)
            profile_id = self._authenticated_profile_id(uow.connection)
            note_id = new_uuid4()
            audit_event_id = new_uuid4()
            now = utc_epoch_seconds()
            note = WorkingNoteRecord(
                working_note_id=note_id,
                owner_type=owner_type,
                owner_id=owner_id,
                created_by_local_user_profile_id=profile_id,
                body_text=body,
                revision=1,
                created_at_utc=now,
                updated_at_utc=now,
                created_command_id=command_id,
            )

            def apply(inner: UnitOfWork) -> AuditEventInput:
                self._repository.insert(inner, note)
                return AuditEventInput(
                    audit_event_id=audit_event_id,
                    action_type="ticket.working_note.added",
                    action_version=1,
                    actor_kind="local_user",
                    actor_id=profile_id,
                    target_type="working_note",
                    target_id=note_id,
                    command_id=command_id,
                    payload_schema="WorkingNoteAuditV1",
                    payload_version=1,
                    payload={
                        "working_note_id": note_id,
                        "owner_type": owner_type,
                        "owner_id": owner_id,
                        "resulting_revision": 1,
                        "created_by_local_user_profile_id": profile_id,
                        "change_kind": "added",
                        "reason_category": None,
                        "bounded_prior_or_new_body_when_required_by_removal_or_edit_policy": None,
                    },
                    resulting_event_refs=(AuditResultRef("working_note", note_id),),
                )

            return PreparedMutation(False, "working_note", note_id, apply)

        result = self._boundary.execute(envelope, prepare)
        if result.result_id is None:
            raise SomaError("PERSISTENCE_FAILURE", "Working Note creation did not return its identity")
        return self._current_result(
            owner_type=owner_type,
            owner_id=owner_id,
            working_note_id=result.result_id,
            replayed=result.replayed,
            no_change=result.no_change,
        )

    def edit(
        self,
        *,
        command_id: str,
        owner_type: str,
        owner_id: str,
        working_note_id: str,
        base_revision: int,
        body_text: str,
    ) -> WorkingNoteMutationResult:
        body = validate_working_note_body(body_text)
        self._repository._spec(owner_type)
        envelope = CommandEnvelope(
            command_id=command_id,
            command_type="EditWorkingNote",
            target_type="working_note",
            target_id=working_note_id,
            semantic_payload={
                "owner_type": owner_type,
                "owner_id": owner_id,
                "body_text": body,
            },
            base_revisions={"working_note": base_revision},
        )

        def prepare(uow: UnitOfWork) -> PreparedMutation:
            note = self._repository.get(
                uow.connection,
                owner_type,
                owner_id,
                working_note_id,
            )
            if note is None:
                raise SomaError("WORKING_NOTE_NOT_FOUND", "Working Note does not exist under this ticket")
            if note.revision != base_revision:
                raise SomaError("STALE_REVISION", "Working Note revision changed")
            if note.body_text == body:
                return PreparedMutation(True, None, None)
            actor_id = self._authenticated_profile_id(uow.connection)
            audit_event_id = new_uuid4()
            now = utc_epoch_seconds()

            def apply(inner: UnitOfWork) -> AuditEventInput:
                self._repository.update(
                    inner,
                    owner_type=owner_type,
                    owner_id=owner_id,
                    working_note_id=working_note_id,
                    base_revision=base_revision,
                    body_text=body,
                    updated_at_utc=now,
                )
                return AuditEventInput(
                    audit_event_id=audit_event_id,
                    action_type="ticket.working_note.edited",
                    action_version=1,
                    actor_kind="local_user",
                    actor_id=actor_id,
                    target_type="working_note",
                    target_id=working_note_id,
                    command_id=command_id,
                    payload_schema="WorkingNoteAuditV1",
                    payload_version=1,
                    payload={
                        "working_note_id": working_note_id,
                        "owner_type": owner_type,
                        "owner_id": owner_id,
                        "resulting_revision": base_revision + 1,
                        "created_by_local_user_profile_id": note.created_by_local_user_profile_id,
                        "change_kind": "edited",
                        "reason_category": None,
                        "bounded_prior_or_new_body_when_required_by_removal_or_edit_policy": note.body_text,
                    },
                    resulting_event_refs=(AuditResultRef("working_note", working_note_id),),
                )

            return PreparedMutation(False, "working_note", working_note_id, apply)

        result = self._boundary.execute(envelope, prepare)
        return self._current_result(
            owner_type=owner_type,
            owner_id=owner_id,
            working_note_id=working_note_id,
            replayed=result.replayed,
            no_change=result.no_change,
        )

    def remove(
        self,
        *,
        command_id: str,
        owner_type: str,
        owner_id: str,
        working_note_id: str,
        base_revision: int,
        reason_category: str | None = None,
    ) -> WorkingNoteMutationResult:
        self._repository._spec(owner_type)
        reason = self._optional_reason(reason_category)
        envelope = CommandEnvelope(
            command_id=command_id,
            command_type="RemoveWorkingNote",
            target_type="working_note",
            target_id=working_note_id,
            semantic_payload={
                "owner_type": owner_type,
                "owner_id": owner_id,
                "reason_category": reason,
            },
            base_revisions={"working_note": base_revision},
        )

        def prepare(uow: UnitOfWork) -> PreparedMutation:
            note = self._repository.get(
                uow.connection,
                owner_type,
                owner_id,
                working_note_id,
            )
            if note is None:
                raise SomaError("WORKING_NOTE_NOT_FOUND", "Working Note does not exist under this ticket")
            if note.revision != base_revision:
                raise SomaError("STALE_REVISION", "Working Note revision changed")
            actor_id = self._authenticated_profile_id(uow.connection)
            audit_event_id = new_uuid4()

            def apply(inner: UnitOfWork) -> AuditEventInput:
                prior = self._repository.remove_with_prior_capture(
                    inner,
                    owner_type=owner_type,
                    owner_id=owner_id,
                    working_note_id=working_note_id,
                    base_revision=base_revision,
                )
                return AuditEventInput(
                    audit_event_id=audit_event_id,
                    action_type="ticket.working_note.removed",
                    action_version=1,
                    actor_kind="local_user",
                    actor_id=actor_id,
                    target_type="working_note",
                    target_id=working_note_id,
                    reason_category=reason,
                    command_id=command_id,
                    payload_schema="WorkingNoteAuditV1",
                    payload_version=1,
                    payload={
                        "working_note_id": working_note_id,
                        "owner_type": owner_type,
                        "owner_id": owner_id,
                        "resulting_revision": None,
                        "created_by_local_user_profile_id": prior.created_by_local_user_profile_id,
                        "change_kind": "removed",
                        "reason_category": reason,
                        "bounded_prior_or_new_body_when_required_by_removal_or_edit_policy": prior.body_text,
                    },
                    resulting_event_refs=(AuditResultRef("working_note_history", working_note_id),),
                )

            return PreparedMutation(False, "working_note_history", working_note_id, apply)

        result = self._boundary.execute(envelope, prepare)
        return WorkingNoteMutationResult(
            working_note_id=working_note_id,
            owner_type=owner_type,
            owner_id=owner_id,
            revision=base_revision,
            replayed=result.replayed,
            no_change=result.no_change,
            removed=True,
        )
