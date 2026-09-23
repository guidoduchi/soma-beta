from __future__ import annotations

import pytest

from soma.composition import (
    build_pre_lld08_reference_dependency_registry,
    build_pre_lld08_reference_lifecycle_service,
)
from soma.foundation.errors import SomaError
from soma.foundation.identifiers import new_uuid4
from soma.reference.application.contact_service import ContactReferenceService
from test_inventory_requester_support_acceptance import _create_request, _factory


def test_pre_lld08_composition_declares_inventory_reference_dependency(
    initialized_database,
) -> None:
    factory = _factory(initialized_database)
    registry = build_pre_lld08_reference_dependency_registry()

    assert tuple(
        validator.validator_id
        for validator in registry.ordered()
    ) == ("inventory",)

    contacts = ContactReferenceService(factory)
    requester = contacts.create_contact(
        command_id=new_uuid4(),
        name="Composed Archive Requester",
    )
    receiver = contacts.create_contact(
        command_id=new_uuid4(),
        name="Composed Archive Receiver",
    )
    _service, request_id = _create_request(
        factory,
        official_sr="97907777",
        requester_contact_id=requester.contact_id,
        receiver_contact_id=receiver.contact_id,
        bom="COMPOSITION-BOM",
    )

    lifecycle = build_pre_lld08_reference_lifecycle_service(factory)
    with pytest.raises(SomaError) as blocked:
        lifecycle.archive_reference(
            command_id=new_uuid4(),
            target_type="contact",
            target_id=requester.contact_id,
            base_revision=1,
            reason_category="operator_archive",
        )

    assert blocked.value.code == "ARCHIVE_BLOCKED"
    assert "active_spare_request_requester" in str(blocked.value)

    # The failed guard remains atomic: no archive event or state transition can
    # slip through merely because the provider is assembled at composition time.
    detail = contacts.get_contact(requester.contact_id)
    assert detail.contact_id == requester.contact_id
    assert detail.lifecycle_state == "active"
    assert request_id
