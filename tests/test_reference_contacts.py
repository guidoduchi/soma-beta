from __future__ import annotations

import json

import pytest

from soma.foundation.errors import SomaError, ValidationError
from soma.foundation.identifiers import new_uuid4
from soma.reference.application.contact_service import ContactReferenceService
from soma.reference.application.customer_service import CustomerReferenceService


def _connection(initialized_database):
    database_path, factory_for_path = initialized_database
    return factory_for_path(database_path).open_authoritative(read_only=True, require_wal=True)


def test_contacts_allow_duplicate_names_and_zero_channels(initialized_database) -> None:
    database_path, factory_for_path = initialized_database
    service = ContactReferenceService(factory_for_path(database_path))
    command_id = new_uuid4()
    first = service.create_contact(command_id=command_id, name="Alex Operator")
    replay = service.create_contact(command_id=command_id, name="Alex Operator")
    second = service.create_contact(command_id=new_uuid4(), name="Alex Operator")

    assert replay.replayed is True
    assert replay.contact_id == first.contact_id
    assert second.contact_id != first.contact_id

    connection = _connection(initialized_database)
    try:
        assert connection.execute("SELECT count(*) FROM contacts").fetchone()[0] == 2
        assert connection.execute("SELECT count(*) FROM contact_channels").fetchone()[0] == 0
        assert connection.execute("SELECT count(*) FROM contact_affiliations").fetchone()[0] == 0
    finally:
        connection.close()


def test_same_email_does_not_merge_contacts(initialized_database) -> None:
    database_path, factory_for_path = initialized_database
    service = ContactReferenceService(factory_for_path(database_path))
    first = service.create_contact(
        command_id=new_uuid4(), name="First", initial_email="ops@example.com"
    )
    second = service.create_contact(
        command_id=new_uuid4(), name="Second", initial_email="OPS@example.com"
    )
    assert first.contact_id != second.contact_id

    connection = _connection(initialized_database)
    try:
        rows = connection.execute(
            "SELECT contact_id,match_key FROM contact_channels WHERE lifecycle_state='active' ORDER BY contact_id"
        ).fetchall()
        assert len(rows) == 2
        assert {row[0] for row in rows} == {first.contact_id, second.contact_id}
        assert {row[1] for row in rows} == {"ops@example.com"}
    finally:
        connection.close()


def test_channel_add_update_archive_and_stale_revision(initialized_database) -> None:
    database_path, factory_for_path = initialized_database
    service = ContactReferenceService(factory_for_path(database_path))
    contact = service.create_contact(command_id=new_uuid4(), name="Channel Owner")
    added = service.add_contact_channel(
        command_id=new_uuid4(),
        contact_id=contact.contact_id,
        contact_base_revision=1,
        channel_kind="email",
        value_text="first@example.com",
    )
    assert added.result_id is not None
    channel_id = added.result_id

    with pytest.raises(SomaError) as exc:
        service.update_contact_channel(
            command_id=new_uuid4(),
            contact_id=contact.contact_id,
            contact_base_revision=1,
            contact_channel_id=channel_id,
            channel_base_revision=1,
            value_text="stale@example.com",
        )
    assert exc.value.code == "STALE_REVISION"

    updated = service.update_contact_channel(
        command_id=new_uuid4(),
        contact_id=contact.contact_id,
        contact_base_revision=2,
        contact_channel_id=channel_id,
        channel_base_revision=1,
        value_text="second@example.com",
    )
    assert updated.no_change is False
    archived = service.archive_contact_channel(
        command_id=new_uuid4(),
        contact_id=contact.contact_id,
        contact_base_revision=3,
        contact_channel_id=channel_id,
        channel_base_revision=2,
        reason_category="channel_retired",
    )
    assert archived.no_change is False

    connection = _connection(initialized_database)
    try:
        contact_revision = connection.execute(
            "SELECT revision FROM contacts WHERE contact_id=?", (contact.contact_id,)
        ).fetchone()[0]
        channel_row = connection.execute(
            "SELECT value_text,lifecycle_state,revision FROM contact_channels WHERE contact_channel_id=?",
            (channel_id,),
        ).fetchone()
        assert contact_revision == 4
        assert tuple(channel_row) == ("second@example.com", "archived", 3)
    finally:
        connection.close()


def test_affiliation_changes_close_history_and_keep_one_current(initialized_database) -> None:
    database_path, factory_for_path = initialized_database
    customers = CustomerReferenceService(factory_for_path(database_path))
    contacts = ContactReferenceService(factory_for_path(database_path))
    first_customer = customers.create_customer_organization(command_id=new_uuid4(), name="Customer A")
    second_customer = customers.create_customer_organization(command_id=new_uuid4(), name="Customer B")
    contact = contacts.create_contact(
        command_id=new_uuid4(),
        name="Affiliated Person",
        initial_customer_org_id=first_customer.customer_org_id,
    )

    contacts.change_contact_affiliation(
        command_id=new_uuid4(),
        contact_id=contact.contact_id,
        base_revision=1,
        new_customer_org_id=second_customer.customer_org_id,
        reason_category="role_changed",
    )

    connection = _connection(initialized_database)
    try:
        rows = connection.execute(
            "SELECT customer_org_id,is_current,closed_command_id FROM contact_affiliations "
            "WHERE contact_id=? ORDER BY opened_at_utc,contact_affiliation_id",
            (contact.contact_id,),
        ).fetchall()
        assert len(rows) == 2
        assert sum(int(row[1]) for row in rows) == 1
        historical = [row for row in rows if int(row[1]) == 0]
        current = [row for row in rows if int(row[1]) == 1]
        assert historical[0][0] == first_customer.customer_org_id
        assert historical[0][2] is not None
        assert current[0][0] == second_customer.customer_org_id

        historical_id = connection.execute(
            "SELECT contact_affiliation_id FROM contact_affiliations WHERE contact_id=? AND is_current=0",
            (contact.contact_id,),
        ).fetchone()[0]
        with pytest.raises(Exception):
            connection.execute(
                "UPDATE contact_affiliations SET customer_org_id=? WHERE contact_affiliation_id=?",
                (second_customer.customer_org_id, historical_id),
            )
    finally:
        connection.close()


def test_affiliation_same_target_is_semantic_no_change(initialized_database) -> None:
    database_path, factory_for_path = initialized_database
    customers = CustomerReferenceService(factory_for_path(database_path))
    contacts = ContactReferenceService(factory_for_path(database_path))
    customer = customers.create_customer_organization(command_id=new_uuid4(), name="Customer")
    contact = contacts.create_contact(
        command_id=new_uuid4(), name="Person", initial_customer_org_id=customer.customer_org_id
    )
    result = contacts.change_contact_affiliation(
        command_id=new_uuid4(),
        contact_id=contact.contact_id,
        base_revision=1,
        new_customer_org_id=customer.customer_org_id,
        reason_category="confirmed_unchanged",
    )
    assert result.no_change is True

    connection = _connection(initialized_database)
    try:
        assert connection.execute(
            "SELECT revision FROM contacts WHERE contact_id=?", (contact.contact_id,)
        ).fetchone()[0] == 1
        assert connection.execute(
            "SELECT count(*) FROM contact_affiliations WHERE contact_id=?", (contact.contact_id,)
        ).fetchone()[0] == 1
    finally:
        connection.close()


def test_email_channel_rejects_header_injection_and_non_email_kind(initialized_database) -> None:
    database_path, factory_for_path = initialized_database
    service = ContactReferenceService(factory_for_path(database_path))
    contact = service.create_contact(command_id=new_uuid4(), name="Recipient")

    with pytest.raises(ValidationError):
        service.add_contact_channel(
            command_id=new_uuid4(),
            contact_id=contact.contact_id,
            contact_base_revision=1,
            channel_kind="email",
            value_text="victim@example.com\r\nBcc: attacker@example.com",
        )
    with pytest.raises(ValidationError):
        service.add_contact_channel(
            command_id=new_uuid4(),
            contact_id=contact.contact_id,
            contact_base_revision=1,
            channel_kind="phone",
            value_text="+593999999999",
        )


def test_contact_audit_payload_does_not_duplicate_names_or_email_addresses(initialized_database) -> None:
    database_path, factory_for_path = initialized_database
    service = ContactReferenceService(factory_for_path(database_path))
    service.create_contact(
        command_id=new_uuid4(),
        name="Private Contact Label",
        initial_email="private-address@example.com",
    )
    connection = _connection(initialized_database)
    try:
        payloads = [str(row[0]) for row in connection.execute("SELECT payload_json FROM audit_events").fetchall()]
        joined = "\n".join(payloads)
        assert "Private Contact Label" not in joined
        assert "private-address@example.com" not in joined
        for payload in payloads:
            json.loads(payload)
    finally:
        connection.close()
