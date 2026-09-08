from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from soma.foundation.application.command_boundary import (
    CommandBoundary,
    CommandEnvelope,
    CommandExecutionResult,
    PreparedMutation,
)
from soma.foundation.audit.writer import AuditEventInput, AuditResultRef, AuditWriter
from soma.foundation.errors import SomaError, ValidationError
from soma.foundation.identifiers import new_uuid4, utc_epoch_seconds
from soma.foundation.persistence.connections import ConnectionFactory
from soma.foundation.persistence.uow import UnitOfWork

from soma.reference.audit_registry import build_reference_audit_registry
from soma.reference.domain.validation import (
    validate_contact_name,
    validate_email_channel,
    validate_reason_category,
)


@dataclass(frozen=True, slots=True)
class ContactCreateResult:
    contact_id: str
    replayed: bool


class ContactReferenceService:
    def __init__(self, connection_factory: ConnectionFactory) -> None:
        self._boundary = CommandBoundary(
            connection_factory,
            AuditWriter(build_reference_audit_registry()),
        )

    @staticmethod
    def _active_contact(connection: Any, contact_id: str, *, base_revision: int | None = None) -> Any:
        row = connection.execute(
            "SELECT contact_id,name,name_match_key,lifecycle_state,revision "
            "FROM contacts WHERE contact_id=?",
            (contact_id,),
        ).fetchone()
        if row is None or str(row[3]) != "active":
            raise SomaError("REFERENCE_NOT_ACTIVE", "Contact is missing or archived")
        if base_revision is not None and int(row[4]) != base_revision:
            raise SomaError("STALE_REVISION", "Contact revision changed")
        return row

    @staticmethod
    def _active_customer(connection: Any, customer_org_id: str) -> None:
        row = connection.execute(
            "SELECT lifecycle_state FROM customer_organizations WHERE customer_org_id=?",
            (customer_org_id,),
        ).fetchone()
        if row is None or str(row[0]) != "active":
            raise SomaError("REFERENCE_NOT_ACTIVE", "Customer Organization is missing or archived")

    @staticmethod
    def _channel(
        connection: Any,
        *,
        contact_id: str,
        contact_channel_id: str,
        channel_base_revision: int | None = None,
        require_active: bool = True,
    ) -> Any:
        row = connection.execute(
            "SELECT contact_channel_id,contact_id,channel_kind,value_text,match_key,lifecycle_state,revision "
            "FROM contact_channels WHERE contact_channel_id=?",
            (contact_channel_id,),
        ).fetchone()
        if row is None or str(row[1]) != contact_id:
            raise SomaError("CONTACT_CHANNEL_NOT_FOUND", "Contact channel is missing or belongs to another Contact")
        if require_active and str(row[5]) != "active":
            raise SomaError("CONTACT_CHANNEL_NOT_ACTIVE", "Contact channel is archived")
        if channel_base_revision is not None and int(row[6]) != channel_base_revision:
            raise SomaError("STALE_REVISION", "Contact channel revision changed")
        return row

    @staticmethod
    def _current_affiliation(connection: Any, contact_id: str) -> Any | None:
        return connection.execute(
            "SELECT contact_affiliation_id,customer_org_id FROM contact_affiliations "
            "WHERE contact_id=? AND is_current=1",
            (contact_id,),
        ).fetchone()

    @staticmethod
    def _required_reason(reason_category: str | None) -> str:
        reason = validate_reason_category(reason_category)
        if reason is None:
            raise ValidationError("reason_category is required")
        return reason

    def create_contact(
        self,
        *,
        command_id: str,
        name: str,
        initial_email: str | None = None,
        initial_customer_org_id: str | None = None,
        actor_kind: str = "local_user",
        actor_id: str | None = None,
    ) -> ContactCreateResult:
        stored_name, name_key = validate_contact_name(name)
        email_value: str | None = None
        email_key: str | None = None
        if initial_email is not None:
            email_value, email_key = validate_email_channel(initial_email)

        envelope = CommandEnvelope(
            command_id=command_id,
            command_type="CreateContact",
            target_type="contact",
            target_id=None,
            semantic_payload={
                "name": stored_name,
                "initial_email": email_value,
                "initial_customer_org_id": initial_customer_org_id,
            },
        )

        def prepare(uow: UnitOfWork) -> PreparedMutation:
            if initial_customer_org_id is not None:
                self._active_customer(uow.connection, initial_customer_org_id)

            contact_id = new_uuid4()
            channel_id = new_uuid4() if email_value is not None else None
            affiliation_id = new_uuid4() if initial_customer_org_id is not None else None
            lifecycle_event_id = new_uuid4()
            audit_event_id = new_uuid4()
            now = utc_epoch_seconds()

            def apply(inner: UnitOfWork) -> AuditEventInput:
                inner.connection.execute(
                    "INSERT INTO contacts(contact_id,name,name_match_key,lifecycle_state,revision,created_at_utc,updated_at_utc) "
                    "VALUES (?, ?, ?, 'active', 1, ?, ?)",
                    (contact_id, stored_name, name_key, now, now),
                )
                refs = [AuditResultRef("contact", contact_id)]
                if channel_id is not None and email_value is not None and email_key is not None:
                    inner.connection.execute(
                        "INSERT INTO contact_channels(contact_channel_id,contact_id,channel_kind,value_text,match_key,"
                        "lifecycle_state,revision,created_at_utc,updated_at_utc) "
                        "VALUES (?, ?, 'email', ?, ?, 'active', 1, ?, ?)",
                        (channel_id, contact_id, email_value, email_key, now, now),
                    )
                    refs.append(AuditResultRef("contact_channel", channel_id))
                if affiliation_id is not None and initial_customer_org_id is not None:
                    inner.connection.execute(
                        "INSERT INTO contact_affiliations(contact_affiliation_id,contact_id,customer_org_id,is_current,"
                        "opened_at_utc,closed_at_utc,opened_command_id,closed_command_id) "
                        "VALUES (?, ?, ?, 1, ?, NULL, ?, NULL)",
                        (affiliation_id, contact_id, initial_customer_org_id, now, command_id),
                    )
                    refs.append(AuditResultRef("contact_affiliation", affiliation_id))
                inner.connection.execute(
                    "INSERT INTO reference_lifecycle_events(reference_lifecycle_event_id,target_type,target_id,event_type,"
                    "occurred_at_utc,command_id,reason_category) VALUES (?, 'contact', ?, 'created', ?, ?, NULL)",
                    (lifecycle_event_id, contact_id, now, command_id),
                )
                refs.append(AuditResultRef("reference_lifecycle_event", lifecycle_event_id))
                return AuditEventInput(
                    audit_event_id=audit_event_id,
                    action_type="reference.contact.created",
                    action_version=1,
                    actor_kind=actor_kind,
                    actor_id=actor_id,
                    target_type="contact",
                    target_id=contact_id,
                    command_id=command_id,
                    payload_schema="ContactAuditV1",
                    payload_version=1,
                    payload={
                        "contact_id": contact_id,
                        "new_revision": 1,
                        "initial_channel_id": channel_id,
                        "initial_affiliation_id": affiliation_id,
                    },
                    resulting_event_refs=tuple(refs),
                )

            return PreparedMutation(False, "contact", contact_id, apply)

        result = self._boundary.execute(envelope, prepare)
        assert result.result_id is not None
        return ContactCreateResult(result.result_id, result.replayed)

    def update_contact_descriptive_data(
        self,
        *,
        command_id: str,
        contact_id: str,
        base_revision: int,
        name: str,
        actor_kind: str = "local_user",
        actor_id: str | None = None,
    ) -> CommandExecutionResult:
        stored_name, name_key = validate_contact_name(name)
        envelope = CommandEnvelope(
            command_id=command_id,
            command_type="UpdateContactDescriptiveData",
            target_type="contact",
            target_id=contact_id,
            semantic_payload={"name": stored_name},
            base_revisions={"contact": base_revision},
        )

        def prepare(uow: UnitOfWork) -> PreparedMutation:
            row = self._active_contact(uow.connection, contact_id, base_revision=base_revision)
            if str(row[1]) == stored_name and str(row[2]) == name_key:
                return PreparedMutation(True, None, None)
            lifecycle_event_id = new_uuid4()
            audit_event_id = new_uuid4()
            now = utc_epoch_seconds()

            def apply(inner: UnitOfWork) -> AuditEventInput:
                inner.connection.execute(
                    "UPDATE contacts SET name=?,name_match_key=?,revision=revision+1,updated_at_utc=? WHERE contact_id=?",
                    (stored_name, name_key, now, contact_id),
                )
                inner.connection.execute(
                    "INSERT INTO reference_lifecycle_events(reference_lifecycle_event_id,target_type,target_id,event_type,"
                    "occurred_at_utc,command_id,reason_category) VALUES (?, 'contact', ?, 'descriptive_corrected', ?, ?, NULL)",
                    (lifecycle_event_id, contact_id, now, command_id),
                )
                return AuditEventInput(
                    audit_event_id=audit_event_id,
                    action_type="reference.contact.descriptive_updated",
                    action_version=1,
                    actor_kind=actor_kind,
                    actor_id=actor_id,
                    target_type="contact",
                    target_id=contact_id,
                    command_id=command_id,
                    payload_schema="ReferenceDescriptiveAuditV1",
                    payload_version=1,
                    payload={
                        "target_type": "contact",
                        "target_id": contact_id,
                        "prior_revision": base_revision,
                        "new_revision": base_revision + 1,
                        "changed_fields": ["name"],
                        "lifecycle_event_id": lifecycle_event_id,
                    },
                    resulting_event_refs=(
                        AuditResultRef("contact", contact_id),
                        AuditResultRef("reference_lifecycle_event", lifecycle_event_id),
                    ),
                )

            return PreparedMutation(False, "contact", contact_id, apply)

        return self._boundary.execute(envelope, prepare)

    def add_contact_channel(
        self,
        *,
        command_id: str,
        contact_id: str,
        contact_base_revision: int,
        channel_kind: str,
        value_text: str,
        actor_kind: str = "local_user",
        actor_id: str | None = None,
    ) -> CommandExecutionResult:
        if channel_kind != "email":
            raise ValidationError("Beta 1.0 supports only email Contact channels")
        stored_value, match_key = validate_email_channel(value_text)
        envelope = CommandEnvelope(
            command_id=command_id,
            command_type="AddContactChannel",
            target_type="contact",
            target_id=contact_id,
            semantic_payload={"channel_kind": "email", "value_text": stored_value},
            base_revisions={"contact": contact_base_revision},
        )

        def prepare(uow: UnitOfWork) -> PreparedMutation:
            contact = self._active_contact(uow.connection, contact_id, base_revision=contact_base_revision)
            prior_contact_revision = int(contact[4])
            channel_id = new_uuid4()
            audit_event_id = new_uuid4()
            now = utc_epoch_seconds()

            def apply(inner: UnitOfWork) -> AuditEventInput:
                inner.connection.execute(
                    "INSERT INTO contact_channels(contact_channel_id,contact_id,channel_kind,value_text,match_key,"
                    "lifecycle_state,revision,created_at_utc,updated_at_utc) "
                    "VALUES (?, ?, 'email', ?, ?, 'active', 1, ?, ?)",
                    (channel_id, contact_id, stored_value, match_key, now, now),
                )
                inner.connection.execute(
                    "UPDATE contacts SET revision=revision+1,updated_at_utc=? WHERE contact_id=?",
                    (now, contact_id),
                )
                return AuditEventInput(
                    audit_event_id=audit_event_id,
                    action_type="reference.contact_channel.added",
                    action_version=1,
                    actor_kind=actor_kind,
                    actor_id=actor_id,
                    target_type="contact",
                    target_id=contact_id,
                    command_id=command_id,
                    payload_schema="ContactChannelAuditV1",
                    payload_version=1,
                    payload={
                        "contact_id": contact_id,
                        "contact_channel_id": channel_id,
                        "channel_kind": "email",
                        "prior_channel_revision": None,
                        "new_channel_revision": 1,
                        "prior_contact_revision": prior_contact_revision,
                        "new_contact_revision": prior_contact_revision + 1,
                        "change_kind": "ADD",
                    },
                    resulting_event_refs=(AuditResultRef("contact_channel", channel_id),),
                )

            return PreparedMutation(False, "contact_channel", channel_id, apply)

        return self._boundary.execute(envelope, prepare)

    def update_contact_channel(
        self,
        *,
        command_id: str,
        contact_id: str,
        contact_base_revision: int,
        contact_channel_id: str,
        channel_base_revision: int,
        value_text: str,
        actor_kind: str = "local_user",
        actor_id: str | None = None,
    ) -> CommandExecutionResult:
        stored_value, match_key = validate_email_channel(value_text)
        envelope = CommandEnvelope(
            command_id=command_id,
            command_type="UpdateContactChannel",
            target_type="contact_channel",
            target_id=contact_channel_id,
            semantic_payload={"value_text": stored_value, "contact_id": contact_id},
            base_revisions={"contact": contact_base_revision, "channel": channel_base_revision},
        )

        def prepare(uow: UnitOfWork) -> PreparedMutation:
            contact = self._active_contact(uow.connection, contact_id, base_revision=contact_base_revision)
            channel = self._channel(
                uow.connection,
                contact_id=contact_id,
                contact_channel_id=contact_channel_id,
                channel_base_revision=channel_base_revision,
            )
            if str(channel[3]) == stored_value and str(channel[4]) == match_key:
                return PreparedMutation(True, None, None)
            prior_contact_revision = int(contact[4])
            audit_event_id = new_uuid4()
            now = utc_epoch_seconds()

            def apply(inner: UnitOfWork) -> AuditEventInput:
                inner.connection.execute(
                    "UPDATE contact_channels SET value_text=?,match_key=?,revision=revision+1,updated_at_utc=? "
                    "WHERE contact_channel_id=?",
                    (stored_value, match_key, now, contact_channel_id),
                )
                inner.connection.execute(
                    "UPDATE contacts SET revision=revision+1,updated_at_utc=? WHERE contact_id=?",
                    (now, contact_id),
                )
                return AuditEventInput(
                    audit_event_id=audit_event_id,
                    action_type="reference.contact_channel.updated",
                    action_version=1,
                    actor_kind=actor_kind,
                    actor_id=actor_id,
                    target_type="contact_channel",
                    target_id=contact_channel_id,
                    command_id=command_id,
                    payload_schema="ContactChannelAuditV1",
                    payload_version=1,
                    payload={
                        "contact_id": contact_id,
                        "contact_channel_id": contact_channel_id,
                        "channel_kind": "email",
                        "prior_channel_revision": channel_base_revision,
                        "new_channel_revision": channel_base_revision + 1,
                        "prior_contact_revision": prior_contact_revision,
                        "new_contact_revision": prior_contact_revision + 1,
                        "change_kind": "UPDATE",
                    },
                    resulting_event_refs=(AuditResultRef("contact_channel", contact_channel_id),),
                )

            return PreparedMutation(False, "contact_channel", contact_channel_id, apply)

        return self._boundary.execute(envelope, prepare)

    def archive_contact_channel(
        self,
        *,
        command_id: str,
        contact_id: str,
        contact_base_revision: int,
        contact_channel_id: str,
        channel_base_revision: int,
        reason_category: str | None,
        actor_kind: str = "local_user",
        actor_id: str | None = None,
    ) -> CommandExecutionResult:
        reason = self._required_reason(reason_category)
        envelope = CommandEnvelope(
            command_id=command_id,
            command_type="ArchiveContactChannel",
            target_type="contact_channel",
            target_id=contact_channel_id,
            semantic_payload={"contact_id": contact_id, "reason_category": reason},
            base_revisions={"contact": contact_base_revision, "channel": channel_base_revision},
        )

        def prepare(uow: UnitOfWork) -> PreparedMutation:
            contact = self._active_contact(uow.connection, contact_id, base_revision=contact_base_revision)
            self._channel(
                uow.connection,
                contact_id=contact_id,
                contact_channel_id=contact_channel_id,
                channel_base_revision=channel_base_revision,
            )
            prior_contact_revision = int(contact[4])
            audit_event_id = new_uuid4()
            now = utc_epoch_seconds()

            def apply(inner: UnitOfWork) -> AuditEventInput:
                inner.connection.execute(
                    "UPDATE contact_channels SET lifecycle_state='archived',revision=revision+1,updated_at_utc=? "
                    "WHERE contact_channel_id=?",
                    (now, contact_channel_id),
                )
                inner.connection.execute(
                    "UPDATE contacts SET revision=revision+1,updated_at_utc=? WHERE contact_id=?",
                    (now, contact_id),
                )
                return AuditEventInput(
                    audit_event_id=audit_event_id,
                    action_type="reference.contact_channel.archived",
                    action_version=1,
                    actor_kind=actor_kind,
                    actor_id=actor_id,
                    target_type="contact_channel",
                    target_id=contact_channel_id,
                    reason_category=reason,
                    command_id=command_id,
                    payload_schema="ContactChannelArchiveAuditV1",
                    payload_version=1,
                    payload={
                        "contact_id": contact_id,
                        "contact_channel_id": contact_channel_id,
                        "prior_channel_revision": channel_base_revision,
                        "new_channel_revision": channel_base_revision + 1,
                        "prior_contact_revision": prior_contact_revision,
                        "new_contact_revision": prior_contact_revision + 1,
                        "reason_category": reason,
                    },
                    resulting_event_refs=(AuditResultRef("contact_channel", contact_channel_id),),
                )

            return PreparedMutation(False, "contact_channel", contact_channel_id, apply)

        return self._boundary.execute(envelope, prepare)

    def change_contact_affiliation(
        self,
        *,
        command_id: str,
        contact_id: str,
        base_revision: int,
        new_customer_org_id: str | None,
        reason_category: str | None,
        actor_kind: str = "local_user",
        actor_id: str | None = None,
    ) -> CommandExecutionResult:
        reason = self._required_reason(reason_category)
        envelope = CommandEnvelope(
            command_id=command_id,
            command_type="ChangeContactAffiliation",
            target_type="contact",
            target_id=contact_id,
            semantic_payload={"new_customer_org_id": new_customer_org_id, "reason_category": reason},
            base_revisions={"contact": base_revision},
        )

        def prepare(uow: UnitOfWork) -> PreparedMutation:
            contact = self._active_contact(uow.connection, contact_id, base_revision=base_revision)
            if new_customer_org_id is not None:
                self._active_customer(uow.connection, new_customer_org_id)
            current = self._current_affiliation(uow.connection, contact_id)
            current_customer_id = None if current is None else str(current[1])
            if current_customer_id == new_customer_org_id:
                return PreparedMutation(True, None, None)

            prior_affiliation_id = None if current is None else str(current[0])
            new_affiliation_id = new_uuid4() if new_customer_org_id is not None else None
            prior_contact_revision = int(contact[4])
            audit_event_id = new_uuid4()
            now = utc_epoch_seconds()

            def apply(inner: UnitOfWork) -> AuditEventInput:
                if prior_affiliation_id is not None:
                    inner.connection.execute(
                        "UPDATE contact_affiliations SET is_current=0,closed_at_utc=?,closed_command_id=? "
                        "WHERE contact_affiliation_id=?",
                        (now, command_id, prior_affiliation_id),
                    )
                if new_affiliation_id is not None and new_customer_org_id is not None:
                    inner.connection.execute(
                        "INSERT INTO contact_affiliations(contact_affiliation_id,contact_id,customer_org_id,is_current,"
                        "opened_at_utc,closed_at_utc,opened_command_id,closed_command_id) "
                        "VALUES (?, ?, ?, 1, ?, NULL, ?, NULL)",
                        (new_affiliation_id, contact_id, new_customer_org_id, now, command_id),
                    )
                inner.connection.execute(
                    "UPDATE contacts SET revision=revision+1,updated_at_utc=? WHERE contact_id=?",
                    (now, contact_id),
                )
                refs: list[AuditResultRef] = []
                if prior_affiliation_id is not None:
                    refs.append(AuditResultRef("contact_affiliation", prior_affiliation_id))
                if new_affiliation_id is not None:
                    refs.append(AuditResultRef("contact_affiliation", new_affiliation_id))
                return AuditEventInput(
                    audit_event_id=audit_event_id,
                    action_type="reference.contact_affiliation.changed",
                    action_version=1,
                    actor_kind=actor_kind,
                    actor_id=actor_id,
                    target_type="contact",
                    target_id=contact_id,
                    reason_category=reason,
                    command_id=command_id,
                    payload_schema="ContactAffiliationAuditV1",
                    payload_version=1,
                    payload={
                        "contact_id": contact_id,
                        "prior_affiliation_id": prior_affiliation_id,
                        "new_affiliation_id": new_affiliation_id,
                        "prior_customer_org_id": current_customer_id,
                        "new_customer_org_id": new_customer_org_id,
                        "prior_contact_revision": prior_contact_revision,
                        "new_contact_revision": prior_contact_revision + 1,
                        "reason_category": reason,
                    },
                    resulting_event_refs=tuple(refs),
                )

            return PreparedMutation(False, "contact", contact_id, apply)

        return self._boundary.execute(envelope, prepare)
