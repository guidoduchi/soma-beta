from __future__ import annotations

import pytest

from soma.foundation.errors import IdempotencyConflict
from soma.foundation.identifiers import new_uuid4
from soma.foundation.persistence.uow import ReadSnapshot
from soma.inventory.domain.requests import SpareRequestAllocationIntent
from soma.inventory.services.requests_rma import InventoryRequestsRmaService
from soma.reference.application.contact_service import ContactReferenceService

from test_inventory_requests_rma import _dispatch_location, _factory, _need, _sr


def _creation(factory):
    sr = _sr(factory, "97100991")
    need = _need(factory, sr_id=sr.service_request_id, device_name="Replay", bom="BOM")
    contact = ContactReferenceService(factory).create_contact(
        command_id=new_uuid4(), name="Creation Requester",
    )
    return dict(
        command_id=new_uuid4(), service_request_id=sr.service_request_id,
        requester_contact_id=contact.contact_id,
        allocations=(SpareRequestAllocationIntent(need, 1),),
        mode="delivery", receiver_contact_id=contact.contact_id,
        dispatch_location_id=_dispatch_location(factory, "replay"),
    )


def _counts(factory):
    with ReadSnapshot(factory) as snapshot:
        return tuple(snapshot.connection.execute(f"SELECT count(*) FROM {table}").fetchone()[0]
                     for table in ("command_receipts", "audit_events", "spare_requests"))


def test_creation_replays_original_context_before_any_mutable_owner_read(
    initialized_database, monkeypatch,
):
    factory = _factory(initialized_database)
    arguments = _creation(factory)
    service = InventoryRequestsRmaService(factory)
    original = service.create_spare_request_draft(**arguments)
    ContactReferenceService(factory).update_contact_descriptive_data(
        command_id=new_uuid4(), contact_id=arguments["requester_contact_id"],
        base_revision=1, name="Later Requester",
    )
    before = _counts(factory)

    def forbidden(*args, **kwargs):
        raise AssertionError("Replay must not consult mutable owner state")

    for method in ("requester_authority", "require_requester_authority",
                   "require_receiver_and_location", "require_sr_need_allocations",
                   "current_detail"):
        monkeypatch.setattr(service._repository, method, forbidden)
    assert service.create_spare_request_draft(**arguments) == original
    assert original["requester"]["display_name_snapshot"] == "Creation Requester"
    with pytest.raises(IdempotencyConflict):
        service.create_spare_request_draft(**{**arguments, "mode": "self_pickup"})
    assert _counts(factory) == before


def test_creation_owner_failure_rolls_back_receipt_identity_and_request(
    initialized_database, monkeypatch,
):
    factory = _factory(initialized_database)
    arguments = _creation(factory)
    service = InventoryRequestsRmaService(factory)
    before = _counts(factory)
    insert = service._repository.insert_draft

    def fail_after_write(*args, **kwargs):
        insert(*args, **kwargs)
        raise RuntimeError("injected after draft insertion")

    with monkeypatch.context() as patch:
        patch.setattr(service._repository, "insert_draft", fail_after_write)
        with pytest.raises(RuntimeError, match="injected"):
            service.create_spare_request_draft(**arguments)
    assert _counts(factory) == before
    result = service.create_spare_request_draft(**arguments)
    assert result["local_handle"] == "SPR-00000001"
    assert service.create_spare_request_draft(**arguments) == result
