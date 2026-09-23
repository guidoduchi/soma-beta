from __future__ import annotations

import pytest

from soma.foundation.errors import IdempotencyConflict
from soma.foundation.identifiers import new_uuid4
from soma.foundation.persistence.uow import ReadSnapshot
from soma.reference.application.contact_service import ContactReferenceService
from soma.reference.application.customer_service import CustomerReferenceService
from soma.reference.application.dispatch_service import DispatchLocationService
from soma.reference.application.settings_service import SettingService
from test_reference_replay_results import _setting_registry


def _factory(initialized_database):
    database_path, factory_for_path = initialized_database
    return factory_for_path(database_path)


def _state(factory, *, customer_id: str, contact_id: str, channel_id: str, dispatch_id: str):
    with ReadSnapshot(factory) as snapshot:
        connection = snapshot.connection
        return {
            "customer_revision": int(
                connection.execute(
                    "SELECT revision FROM customer_organizations WHERE customer_org_id=?",
                    (customer_id,),
                ).fetchone()[0]
            ),
            "contact_revision": int(
                connection.execute(
                    "SELECT revision FROM contacts WHERE contact_id=?",
                    (contact_id,),
                ).fetchone()[0]
            ),
            "channel_revision": int(
                connection.execute(
                    "SELECT revision FROM contact_channels WHERE contact_channel_id=?",
                    (channel_id,),
                ).fetchone()[0]
            ),
            "dispatch_revision": int(
                connection.execute(
                    "SELECT revision FROM dispatch_locations WHERE dispatch_location_id=?",
                    (dispatch_id,),
                ).fetchone()[0]
            ),
            "setting_revision": int(
                connection.execute(
                    "SELECT revision FROM setting_values WHERE setting_key='test.replay.enabled'"
                ).fetchone()[0]
            ),
            "identifier_rows": int(
                connection.execute(
                    "SELECT COUNT(*) FROM customer_org_identifiers WHERE customer_org_id=?",
                    (customer_id,),
                ).fetchone()[0]
            ),
            "channel_rows": int(
                connection.execute(
                    "SELECT COUNT(*) FROM contact_channels WHERE contact_id=?",
                    (contact_id,),
                ).fetchone()[0]
            ),
            "affiliation_rows": int(
                connection.execute(
                    "SELECT COUNT(*) FROM contact_affiliations WHERE contact_id=?",
                    (contact_id,),
                ).fetchone()[0]
            ),
            "lifecycle_rows": int(
                connection.execute("SELECT COUNT(*) FROM reference_lifecycle_events").fetchone()[0]
            ),
            "audit_rows": int(
                connection.execute("SELECT COUNT(*) FROM audit_events").fetchone()[0]
            ),
            "receipt_rows": int(
                connection.execute("SELECT COUNT(*) FROM command_receipts").fetchone()[0]
            ),
            "result_rows": int(
                connection.execute("SELECT COUNT(*) FROM command_receipt_results").fetchone()[0]
            ),
        }


def test_t034_semantic_no_change_is_committed_without_fabricated_mutation_and_replays_exactly(
    initialized_database,
) -> None:
    factory = _factory(initialized_database)
    customers = CustomerReferenceService(factory)
    contacts = ContactReferenceService(factory)
    dispatches = DispatchLocationService(factory)
    settings = SettingService(factory, _setting_registry())

    customer = customers.create_customer_organization(
        command_id=new_uuid4(),
        name="No Change Customer",
        account_code="NC-ACCOUNT-001",
    )
    contact = contacts.create_contact(
        command_id=new_uuid4(),
        name="No Change Contact",
        initial_email="no-change@example.com",
        initial_customer_org_id=customer.customer_org_id,
    )
    dispatch = dispatches.create_standalone(
        command_id=new_uuid4(),
        name="No Change Dispatch",
        address_text="Warehouse Road 1",
    )
    settings.write(
        command_id=new_uuid4(),
        setting_key="test.replay.enabled",
        base_revision=None,
        value={"enabled": True},
    )

    with ReadSnapshot(factory) as snapshot:
        channel_id = str(
            snapshot.connection.execute(
                "SELECT contact_channel_id FROM contact_channels "
                "WHERE contact_id=? AND lifecycle_state='active'",
                (contact.contact_id,),
            ).fetchone()[0]
        )

    before = _state(
        factory,
        customer_id=customer.customer_org_id,
        contact_id=contact.contact_id,
        channel_id=channel_id,
        dispatch_id=dispatch.dispatch_location_id,
    )

    commands = {
        "customer_name": new_uuid4(),
        "account_code": new_uuid4(),
        "contact_name": new_uuid4(),
        "channel": new_uuid4(),
        "affiliation": new_uuid4(),
        "dispatch": new_uuid4(),
        "setting": new_uuid4(),
    }

    results = (
        customers.update_descriptive_data(
            command_id=commands["customer_name"],
            customer_org_id=customer.customer_org_id,
            base_revision=1,
            name="No Change Customer",
        ),
        customers.set_customer_account_code(
            command_id=commands["account_code"],
            customer_org_id=customer.customer_org_id,
            base_revision=1,
            account_code="NC-ACCOUNT-001",
        ),
        contacts.update_contact_descriptive_data(
            command_id=commands["contact_name"],
            contact_id=contact.contact_id,
            base_revision=1,
            name="No Change Contact",
        ),
        contacts.update_contact_channel(
            command_id=commands["channel"],
            contact_id=contact.contact_id,
            contact_base_revision=1,
            contact_channel_id=channel_id,
            channel_base_revision=1,
            value_text="no-change@example.com",
        ),
        contacts.change_contact_affiliation(
            command_id=commands["affiliation"],
            contact_id=contact.contact_id,
            base_revision=1,
            new_customer_org_id=customer.customer_org_id,
            reason_category="confirmed_unchanged",
        ),
        dispatches.update_descriptive_data(
            command_id=commands["dispatch"],
            dispatch_location_id=dispatch.dispatch_location_id,
            base_revision=1,
            name="No Change Dispatch",
            address_text="Warehouse Road 1",
        ),
        settings.write(
            command_id=commands["setting"],
            setting_key="test.replay.enabled",
            base_revision=1,
            value={"enabled": True},
        ),
    )
    assert all(result.no_change for result in results)
    assert all(result.replayed is False for result in results)

    after = _state(
        factory,
        customer_id=customer.customer_org_id,
        contact_id=contact.contact_id,
        channel_id=channel_id,
        dispatch_id=dispatch.dispatch_location_id,
    )
    for key in (
        "customer_revision",
        "contact_revision",
        "channel_revision",
        "dispatch_revision",
        "setting_revision",
        "identifier_rows",
        "channel_rows",
        "affiliation_rows",
        "lifecycle_rows",
        "audit_rows",
    ):
        assert after[key] == before[key], key
    assert after["receipt_rows"] == before["receipt_rows"] + len(commands)
    assert after["result_rows"] == before["result_rows"] + len(commands)

    with ReadSnapshot(factory) as snapshot:
        stored = snapshot.connection.execute(
            "SELECT command_id,result_type,result_id FROM command_receipts "
            "WHERE command_id IN (?,?,?,?,?,?,?) ORDER BY command_id",
            tuple(commands.values()),
        ).fetchall()
    assert len(stored) == len(commands)
    assert all(str(row[1]) == "NO_CHANGE" and row[2] is None for row in stored)

    later = dispatches.update_descriptive_data(
        command_id=new_uuid4(),
        dispatch_location_id=dispatch.dispatch_location_id,
        base_revision=1,
        name="Changed Later",
        address_text="Warehouse Road 1",
    )
    assert later.no_change is False
    assert later.revision == 2

    replay = dispatches.update_descriptive_data(
        command_id=commands["dispatch"],
        dispatch_location_id=dispatch.dispatch_location_id,
        base_revision=1,
        name="No Change Dispatch",
        address_text="Warehouse Road 1",
    )
    assert replay.replayed is True
    assert replay.no_change is True
    assert replay.revision == 1

    with pytest.raises(IdempotencyConflict):
        dispatches.update_descriptive_data(
            command_id=commands["dispatch"],
            dispatch_location_id=dispatch.dispatch_location_id,
            base_revision=1,
            name="Different Semantic Request",
            address_text="Warehouse Road 1",
        )
