from __future__ import annotations

from soma.foundation.identifiers import new_uuid4
from soma.reference.application.contact_service import ContactReferenceService
from soma.reference.application.customer_service import CustomerReferenceService
from soma.reference.queries.channels import ContactChannelQueries
from soma.reference.queries.matching import ReferenceMatchingQueries


def _connection(initialized_database):
    database_path, factory_for_path = initialized_database
    return factory_for_path(database_path).open_authoritative(read_only=True, require_wal=True)


def test_customer_account_code_conflicting_name_is_ambiguous_and_read_only(initialized_database) -> None:
    database_path, factory_for_path = initialized_database
    factory = factory_for_path(database_path)
    customers = CustomerReferenceService(factory)
    matcher = ReferenceMatchingQueries(factory)
    code_owner = customers.create_customer_organization(
        command_id=new_uuid4(), name="Code Owner", account_code="CUST-100"
    )
    name_owner = customers.create_customer_organization(
        command_id=new_uuid4(), name="Conflicting Name"
    )

    connection = _connection(initialized_database)
    try:
        before = (
            connection.execute("SELECT count(*) FROM command_receipts").fetchone()[0],
            connection.execute("SELECT count(*) FROM audit_events").fetchone()[0],
            connection.execute("SELECT count(*) FROM reference_lifecycle_events").fetchone()[0],
        )
    finally:
        connection.close()

    result = matcher.match_customer_organization(
        raw_account_code="cust-100", raw_name="Conflicting Name"
    )
    assert result.state == "AMBIGUOUS"
    assert result.explanation == "ACCOUNT_CODE_NAME_CONFLICT"
    assert result.candidate_count == 2
    assert set(result.candidate_ids) == {code_owner.customer_org_id, name_owner.customer_org_id}

    connection = _connection(initialized_database)
    try:
        after = (
            connection.execute("SELECT count(*) FROM command_receipts").fetchone()[0],
            connection.execute("SELECT count(*) FROM audit_events").fetchone()[0],
            connection.execute("SELECT count(*) FROM reference_lifecycle_events").fetchone()[0],
        )
        assert after == before
    finally:
        connection.close()


def test_customer_candidate_page_does_not_change_ambiguity_state(initialized_database) -> None:
    database_path, factory_for_path = initialized_database
    factory = factory_for_path(database_path)
    customers = CustomerReferenceService(factory)
    matcher = ReferenceMatchingQueries(factory)
    for _ in range(3):
        customers.create_customer_organization(command_id=new_uuid4(), name="Duplicate Customer")

    first = matcher.match_customer_organization(raw_name="Duplicate Customer", limit=1)
    assert first.state == "AMBIGUOUS"
    assert first.candidate_count == 3
    assert len(first.candidate_ids) == 1
    assert first.continuation_after_id is not None
    second = matcher.match_customer_organization(
        raw_name="Duplicate Customer", limit=1, after_candidate_id=first.continuation_after_id
    )
    assert second.state == "AMBIGUOUS"
    assert second.candidate_count == 3
    assert len(second.candidate_ids) == 1
    assert second.candidate_ids != first.candidate_ids


def test_contact_email_matching_is_customer_scoped_and_unbound_scope_isolated(initialized_database) -> None:
    database_path, factory_for_path = initialized_database
    factory = factory_for_path(database_path)
    customers = CustomerReferenceService(factory)
    contacts = ContactReferenceService(factory)
    matcher = ReferenceMatchingQueries(factory)
    customer_a = customers.create_customer_organization(command_id=new_uuid4(), name="A")
    customer_b = customers.create_customer_organization(command_id=new_uuid4(), name="B")
    contact_a = contacts.create_contact(
        command_id=new_uuid4(),
        name="Same Person",
        initial_email="same@example.com",
        initial_customer_org_id=customer_a.customer_org_id,
    )
    contact_b = contacts.create_contact(
        command_id=new_uuid4(),
        name="Same Person",
        initial_email="same@example.com",
        initial_customer_org_id=customer_b.customer_org_id,
    )
    unbound = contacts.create_contact(
        command_id=new_uuid4(), name="Same Person", initial_email="same@example.com"
    )

    result_a = matcher.match_contact(scope=customer_a.customer_org_id, raw_email="SAME@example.com")
    result_b = matcher.match_contact(scope=customer_b.customer_org_id, raw_email="same@example.com")
    result_unbound = matcher.match_contact(scope="UNBOUND", raw_email="same@example.com")
    assert result_a.state == result_b.state == result_unbound.state == "UNIQUE_CANDIDATE"
    assert result_a.candidate_ids == (contact_a.contact_id,)
    assert result_b.candidate_ids == (contact_b.contact_id,)
    assert result_unbound.candidate_ids == (unbound.contact_id,)


def test_multiple_same_scope_contacts_remain_ambiguous(initialized_database) -> None:
    database_path, factory_for_path = initialized_database
    factory = factory_for_path(database_path)
    customers = CustomerReferenceService(factory)
    contacts = ContactReferenceService(factory)
    matcher = ReferenceMatchingQueries(factory)
    customer = customers.create_customer_organization(command_id=new_uuid4(), name="Scope")
    for name in ("One", "Two"):
        contacts.create_contact(
            command_id=new_uuid4(),
            name=name,
            initial_email="dup@example.com",
            initial_customer_org_id=customer.customer_org_id,
        )
    result = matcher.match_contact(scope=customer.customer_org_id, raw_email="dup@example.com", limit=1)
    assert result.state == "AMBIGUOUS"
    assert result.candidate_count == 2
    assert len(result.candidate_ids) == 1


def test_channel_auto_select_refuses_to_guess_between_multiple_usable_emails(initialized_database) -> None:
    database_path, factory_for_path = initialized_database
    factory = factory_for_path(database_path)
    contacts = ContactReferenceService(factory)
    channels = ContactChannelQueries(factory)
    contact = contacts.create_contact(
        command_id=new_uuid4(), name="Recipient", initial_email="first@example.com"
    )
    added = contacts.add_contact_channel(
        command_id=new_uuid4(),
        contact_id=contact.contact_id,
        contact_base_revision=1,
        channel_kind="email",
        value_text="second@example.com",
    )

    automatic = channels.validate_for_use(contact_id=contact.contact_id, auto_select=True)
    assert automatic.state == "MULTIPLE_USABLE"
    assert automatic.usable_count == 2
    assert len(automatic.candidate_channel_ids) == 2
    assert automatic.reason_code == "CHANNEL_SELECTION_REQUIRED"

    assert added.result_id is not None
    explicit = channels.validate_for_use(
        contact_id=contact.contact_id, contact_channel_id=added.result_id
    )
    assert explicit.state == "USABLE"
    assert explicit.value_text == "second@example.com"


def test_channel_auto_select_one_or_none(initialized_database) -> None:
    database_path, factory_for_path = initialized_database
    factory = factory_for_path(database_path)
    contacts = ContactReferenceService(factory)
    channels = ContactChannelQueries(factory)
    no_email = contacts.create_contact(command_id=new_uuid4(), name="No Email")
    one_email = contacts.create_contact(
        command_id=new_uuid4(), name="One Email", initial_email="one@example.com"
    )
    missing = channels.validate_for_use(contact_id=no_email.contact_id, auto_select=True)
    usable = channels.validate_for_use(contact_id=one_email.contact_id, auto_select=True)
    assert missing.state == "MISSING"
    assert usable.state == "USABLE"
    assert usable.value_text == "one@example.com"
