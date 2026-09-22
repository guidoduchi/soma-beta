from __future__ import annotations

from dataclasses import dataclass

import pytest

from soma.foundation.errors import ValidationError
from soma.foundation.identifiers import new_uuid4
from soma.foundation.persistence.uow import UnitOfWork
from soma.reference.application.contact_service import ContactReferenceService
from soma.reference.application.customer_service import CustomerReferenceService
from soma.reference.application.dispatch_service import DispatchLocationService
from soma.reference.queries.history import ReferenceHistoryQueries
from soma.reference.queries.references import (
    ReferenceQueries,
    SiteDispatchLink,
)


def _factory(initialized_database):
    database_path, factory_for_path = initialized_database
    return factory_for_path(database_path)


def test_active_reference_lists_are_keyset_paged_and_archived_lookup_remains_available(
    initialized_database,
) -> None:
    factory = _factory(initialized_database)
    customers = CustomerReferenceService(factory)
    alpha = customers.create_customer_organization(command_id=new_uuid4(), name="Alpha")
    beta = customers.create_customer_organization(command_id=new_uuid4(), name="Beta")
    gamma = customers.create_customer_organization(command_id=new_uuid4(), name="Gamma")

    with UnitOfWork(factory) as uow:
        uow.connection.execute(
            "UPDATE customer_organizations SET lifecycle_state='archived' WHERE customer_org_id=?",
            (beta.customer_org_id,),
        )

    queries = ReferenceQueries(factory)
    first = queries.list_active_references(reference_type="customer_organization", limit=1)
    assert [item.display_name for item in first.items] == ["Alpha"]
    assert first.continuation is not None
    second = queries.list_active_references(
        reference_type="customer_organization",
        cursor=first.continuation,
        limit=1,
    )
    assert [item.display_name for item in second.items] == ["Gamma"]
    assert second.continuation is None
    assert {item.reference_id for item in (*first.items, *second.items)} == {
        alpha.customer_org_id,
        gamma.customer_org_id,
    }

    archived = queries.get_reference_by_id(
        reference_type="customer_organization",
        reference_id=beta.customer_org_id,
    )
    assert archived.lifecycle_state == "archived"
    assert archived.projection["name"] == "Beta"

    with pytest.raises(ValidationError):
        queries.list_active_references(
            reference_type="contact",
            cursor=first.continuation,
            limit=1,
        )


def test_customer_detail_and_account_code_history_preserve_superseded_claims(
    initialized_database,
) -> None:
    factory = _factory(initialized_database)
    customers = CustomerReferenceService(factory)
    created = customers.create_customer_organization(
        command_id=new_uuid4(),
        name="Customer",
        account_code="ACC-ONE",
    )
    customers.set_customer_account_code(
        command_id=new_uuid4(),
        customer_org_id=created.customer_org_id,
        base_revision=1,
        account_code="ACC-TWO",
        reason_category="provider_correction",
    )

    detail = ReferenceQueries(factory).get_reference_by_id(
        reference_type="customer_organization",
        reference_id=created.customer_org_id,
    )
    assert detail.revision == 2
    assert detail.projection["account_code_history_count"] == 2
    assert detail.projection["current_account_code"]["value_text"] == "ACC-TWO"

    history = ReferenceHistoryQueries(factory)
    first = history.get_customer_account_code_history(
        customer_org_id=created.customer_org_id,
        limit=1,
    )
    assert first.exact_count == 2
    assert len(first.items) == 1
    assert first.continuation is not None
    second = history.get_customer_account_code_history(
        customer_org_id=created.customer_org_id,
        cursor=first.continuation,
        limit=1,
    )
    assert second.exact_count == 2
    assert len(second.items) == 1
    assert second.continuation is None
    items = (*first.items, *second.items)
    by_value = {item.value_text: item for item in items}
    assert set(by_value) == {"ACC-ONE", "ACC-TWO"}
    assert by_value["ACC-ONE"].lifecycle_state == "superseded"
    assert by_value["ACC-ONE"].superseded_command_id is not None
    assert by_value["ACC-TWO"].lifecycle_state == "active"


def test_contact_detail_channels_and_affiliation_histories_are_bounded(
    initialized_database,
) -> None:
    factory = _factory(initialized_database)
    customers = CustomerReferenceService(factory)
    contacts = ContactReferenceService(factory)
    customer_a = customers.create_customer_organization(command_id=new_uuid4(), name="A")
    customer_b = customers.create_customer_organization(command_id=new_uuid4(), name="B")
    contact = contacts.create_contact(
        command_id=new_uuid4(),
        name="Recipient",
        initial_email="first@example.com",
        initial_customer_org_id=customer_a.customer_org_id,
    )
    second_channel = contacts.add_contact_channel(
        command_id=new_uuid4(),
        contact_id=contact.contact_id,
        contact_base_revision=1,
        channel_kind="email",
        value_text="second@example.com",
    )
    contacts.change_contact_affiliation(
        command_id=new_uuid4(),
        contact_id=contact.contact_id,
        base_revision=2,
        new_customer_org_id=customer_b.customer_org_id,
        reason_category="role_changed",
    )

    detail = ReferenceQueries(factory).get_reference_by_id(
        reference_type="contact",
        reference_id=contact.contact_id,
        channel_limit=1,
    )
    assert detail.revision == 3
    assert detail.projection["active_channel_count"] == 2
    assert len(detail.projection["channels"]) == 1
    assert detail.projection["channels_continuation"] is not None
    assert detail.projection["current_affiliation"]["customer_org_id"] == customer_b.customer_org_id

    history = ReferenceHistoryQueries(factory)
    affiliation_first = history.get_contact_affiliation_history(
        contact_id=contact.contact_id,
        limit=1,
    )
    assert affiliation_first.exact_count == 2
    assert affiliation_first.continuation is not None
    affiliation_second = history.get_contact_affiliation_history(
        contact_id=contact.contact_id,
        cursor=affiliation_first.continuation,
        limit=1,
    )
    assert affiliation_second.exact_count == 2
    assert affiliation_second.continuation is None
    affiliations = (*affiliation_first.items, *affiliation_second.items)
    by_customer = {item.customer_org_id: item for item in affiliations}
    assert by_customer[customer_a.customer_org_id].is_current is False
    assert by_customer[customer_a.customer_org_id].closed_command_id is not None
    assert by_customer[customer_b.customer_org_id].is_current is True

    assert second_channel.result_id is not None
    contacts.archive_contact_channel(
        command_id=new_uuid4(),
        contact_id=contact.contact_id,
        contact_base_revision=3,
        contact_channel_id=second_channel.result_id,
        channel_base_revision=1,
        reason_category="channel_retired",
    )
    active = history.get_contact_channels(
        contact_id=contact.contact_id,
        include_exact_count=True,
    )
    all_channels = history.get_contact_channels(
        contact_id=contact.contact_id,
        include_archived=True,
        include_exact_count=True,
        limit=1,
    )
    assert active.exact_count == 1
    assert len(active.items) == 1
    assert all_channels.exact_count == 2
    assert len(all_channels.items) == 1
    assert all_channels.continuation is not None

    with pytest.raises(ValidationError):
        history.get_contact_channels(
            contact_id=contact.contact_id,
            include_archived=False,
            cursor=all_channels.continuation,
        )


@dataclass
class _SiteProvider:
    expected_dispatch_id: str
    calls: list[tuple[str, str]]

    def site_link_for(self, snapshot, dispatch_location_id: str):
        self.calls.append(("link", dispatch_location_id))
        assert snapshot.connection.in_transaction
        if dispatch_location_id != self.expected_dispatch_id:
            return None
        return SiteDispatchLink("site-1", "customer-1")

    def current_site_address(self, snapshot, site_id: str) -> str:
        self.calls.append(("address", site_id))
        assert snapshot.connection.in_transaction
        return "Derived Site Address"


def test_dispatch_address_projection_respects_lld08_provider_boundary(
    initialized_database,
) -> None:
    factory = _factory(initialized_database)
    standalone = DispatchLocationService(factory).create_standalone(
        command_id=new_uuid4(),
        name="Standalone",
        address_text="123 Local Road",
    )
    site_dispatch_id = new_uuid4()
    with UnitOfWork(factory) as uow:
        uow.connection.execute(
            "INSERT INTO dispatch_locations("
            "dispatch_location_id,name,name_match_key,address_mode,standalone_address_text,"
            "lifecycle_state,revision,created_at_utc,updated_at_utc"
            ") VALUES (?, 'Site Dispatch', 'site dispatch', 'site_derived', NULL, 'active', 1, 1, 1)",
            (site_dispatch_id,),
        )

    queries = ReferenceQueries(factory)
    local = queries.get_reference_by_id(
        reference_type="dispatch_location",
        reference_id=standalone.dispatch_location_id,
    )
    assert local.projection["current_address"] == {
        "source": "STANDALONE",
        "state": "READY",
        "site_id": None,
        "customer_org_id": None,
        "address_text": "123 Local Road",
    }

    unavailable = queries.get_reference_by_id(
        reference_type="dispatch_location",
        reference_id=site_dispatch_id,
    )
    assert unavailable.projection["current_address"]["state"] == "UNAVAILABLE"
    assert unavailable.projection["current_address"]["address_text"] is None

    provider = _SiteProvider(site_dispatch_id, [])
    derived = ReferenceQueries(factory, provider).get_reference_by_id(
        reference_type="dispatch_location",
        reference_id=site_dispatch_id,
    )
    assert derived.projection["current_address"] == {
        "source": "SITE",
        "state": "READY",
        "site_id": "site-1",
        "customer_org_id": "customer-1",
        "address_text": "Derived Site Address",
    }
    assert provider.calls == [("link", site_dispatch_id), ("address", "site-1")]


def test_local_user_profile_point_lookup_is_available_without_login_authority(
    initialized_database,
) -> None:
    factory = _factory(initialized_database)
    profile_id = new_uuid4()
    with UnitOfWork(factory) as uow:
        uow.connection.execute(
            "INSERT INTO local_user_profiles("
            "local_user_profile_id,singleton_guard,display_name,revision,created_at_utc,updated_at_utc"
            ") VALUES (?,1,'Local Administrator',1,1,1)",
            (profile_id,),
        )

    detail = ReferenceQueries(factory).get_reference_by_id(
        reference_type="local_user_profile",
        reference_id=profile_id,
    )
    assert detail.lifecycle_state == "active"
    assert detail.projection == {"display_name": "Local Administrator"}
