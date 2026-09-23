from __future__ import annotations

import pytest

from soma.foundation.errors import SomaError
from soma.foundation.identifiers import new_uuid4
from soma.foundation.persistence.uow import ReadSnapshot
from soma.reference.application.contact_service import ContactReferenceService
from soma.reference.application.customer_service import CustomerReferenceService
from soma.reference.application.dispatch_service import DispatchLocationService
from soma.reference.application.lifecycle_service import ReferenceLifecycleService
from soma.reference.domain.dependencies import ReferenceDependencyRegistry


def _factory(initialized_database):
    database_path, factory_for_path = initialized_database
    return factory_for_path(database_path)


def test_t001_descriptive_renames_preserve_reference_identity_and_relationship_resolution(
    initialized_database,
) -> None:
    factory = _factory(initialized_database)
    customers = CustomerReferenceService(factory)
    contacts = ContactReferenceService(factory)
    dispatches = DispatchLocationService(factory)

    customer = customers.create_customer_organization(
        command_id=new_uuid4(),
        name="Identity Customer",
    )
    contact = contacts.create_contact(
        command_id=new_uuid4(),
        name="Identity Contact",
        initial_customer_org_id=customer.customer_org_id,
    )
    dispatch = dispatches.create_standalone(
        command_id=new_uuid4(),
        name="Identity Dispatch",
        address_text="Original Address 1",
    )

    customer_edit = customers.update_descriptive_data(
        command_id=new_uuid4(),
        customer_org_id=customer.customer_org_id,
        base_revision=1,
        name="Identity Customer Renamed",
    )
    contact_edit = contacts.update_contact_descriptive_data(
        command_id=new_uuid4(),
        contact_id=contact.contact_id,
        base_revision=1,
        name="Identity Contact Renamed",
    )
    dispatch_edit = dispatches.update_descriptive_data(
        command_id=new_uuid4(),
        dispatch_location_id=dispatch.dispatch_location_id,
        base_revision=1,
        name="Identity Dispatch Renamed",
        address_text="Original Address 1",
    )

    assert customer_edit.target_id == customer.customer_org_id
    assert contact_edit.target_id == contact.contact_id
    assert dispatch_edit.target_id == dispatch.dispatch_location_id

    with ReadSnapshot(factory) as snapshot:
        affiliation = snapshot.connection.execute(
            "SELECT contact_id,customer_org_id,is_current "
            "FROM contact_affiliations WHERE contact_id=? AND is_current=1",
            (contact.contact_id,),
        ).fetchone()
        assert tuple(affiliation) == (
            contact.contact_id,
            customer.customer_org_id,
            1,
        )
        assert snapshot.connection.execute(
            "SELECT name,revision FROM customer_organizations WHERE customer_org_id=?",
            (customer.customer_org_id,),
        ).fetchone() == ("Identity Customer Renamed", 2)
        assert snapshot.connection.execute(
            "SELECT name,revision FROM contacts WHERE contact_id=?",
            (contact.contact_id,),
        ).fetchone() == ("Identity Contact Renamed", 2)
        assert snapshot.connection.execute(
            "SELECT name,revision FROM dispatch_locations WHERE dispatch_location_id=?",
            (dispatch.dispatch_location_id,),
        ).fetchone() == ("Identity Dispatch Renamed", 2)


def test_t029_second_editor_cannot_overwrite_fresh_descriptive_reference_edit(
    initialized_database,
) -> None:
    factory = _factory(initialized_database)
    service = CustomerReferenceService(factory)
    customer = service.create_customer_organization(
        command_id=new_uuid4(),
        name="Concurrent Customer",
    )

    first = service.update_descriptive_data(
        command_id=new_uuid4(),
        customer_org_id=customer.customer_org_id,
        base_revision=1,
        name="First Editor Wins",
    )
    assert first.revision == 2

    losing_command = new_uuid4()
    with pytest.raises(SomaError) as stale:
        service.update_descriptive_data(
            command_id=losing_command,
            customer_org_id=customer.customer_org_id,
            base_revision=1,
            name="Second Editor Must Lose",
        )
    assert stale.value.code == "STALE_REVISION"

    with ReadSnapshot(factory) as snapshot:
        assert snapshot.connection.execute(
            "SELECT name,revision FROM customer_organizations WHERE customer_org_id=?",
            (customer.customer_org_id,),
        ).fetchone() == ("First Editor Wins", 2)
        assert snapshot.connection.execute(
            "SELECT 1 FROM command_receipts WHERE command_id=?",
            (losing_command,),
        ).fetchone() is None


def test_t028_lifecycle_audit_failure_rolls_back_receipt_state_and_event(
    initialized_database,
    monkeypatch,
) -> None:
    factory = _factory(initialized_database)
    contact = ContactReferenceService(factory).create_contact(
        command_id=new_uuid4(),
        name="Audit Rollback Contact",
    )
    lifecycle = ReferenceLifecycleService(
        factory,
        ReferenceDependencyRegistry.isolated_for_tests(),
    )
    command_id = new_uuid4()

    def fail_audit(*_args, **_kwargs):
        raise SomaError("AUDIT_INJECTED_FAILURE", "injected audit failure")

    monkeypatch.setattr(lifecycle._boundary._audit_writer, "write", fail_audit)

    with pytest.raises(SomaError) as failed:
        lifecycle.archive_reference(
            command_id=command_id,
            target_type="contact",
            target_id=contact.contact_id,
            base_revision=1,
            reason_category="operator_archive",
        )
    assert failed.value.code == "AUDIT_INJECTED_FAILURE"

    with ReadSnapshot(factory) as snapshot:
        assert snapshot.connection.execute(
            "SELECT lifecycle_state,revision FROM contacts WHERE contact_id=?",
            (contact.contact_id,),
        ).fetchone() == ("active", 1)
        assert snapshot.connection.execute(
            "SELECT 1 FROM command_receipts WHERE command_id=?",
            (command_id,),
        ).fetchone() is None
        assert snapshot.connection.execute(
            "SELECT 1 FROM reference_lifecycle_events "
            "WHERE target_id=? AND event_type='archived'",
            (contact.contact_id,),
        ).fetchone() is None
        assert snapshot.connection.execute(
            "SELECT 1 FROM audit_events WHERE command_id=?",
            (command_id,),
        ).fetchone() is None
