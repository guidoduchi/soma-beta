from __future__ import annotations

import json

from soma.foundation.identifiers import new_uuid4
from soma.reference.application.customer_service import CustomerReferenceService


def _factory(initialized_database):
    database_path, factory_for_path = initialized_database
    return factory_for_path(database_path)


def test_customer_account_code_replay_keeps_original_customer_revision(initialized_database, monkeypatch) -> None:
    factory = _factory(initialized_database)
    service = CustomerReferenceService(factory)
    customer = service.create_customer_organization(
        command_id=new_uuid4(),
        name="Replay Customer",
    )
    command_id = new_uuid4()

    first = service.set_customer_account_code(
        command_id=command_id,
        customer_org_id=customer.customer_org_id,
        base_revision=1,
        account_code="ACC-REPLAY-1",
        reason_category="operator_set",
    )
    assert first.outcome == "APPLIED"
    assert first.target_id == customer.customer_org_id
    assert first.revision == 2
    assert first.replayed is False

    later = service.update_descriptive_data(
        command_id=new_uuid4(),
        customer_org_id=customer.customer_org_id,
        base_revision=2,
        name="Replay Customer Later",
    )
    assert later.revision == 3

    monkeypatch.setattr(
        CustomerReferenceService,
        "_active_customer",
        staticmethod(lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("Customer owner read during replay"))),
    )
    monkeypatch.setattr(
        CustomerReferenceService,
        "_active_code_claim",
        staticmethod(lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("Account Code owner read during replay"))),
    )
    replay = service.set_customer_account_code(
        command_id=command_id,
        customer_org_id=customer.customer_org_id,
        base_revision=1,
        account_code="ACC-REPLAY-1",
        reason_category="operator_set",
    )
    assert replay.replayed is True
    assert replay.outcome == "APPLIED"
    assert replay.target_id == customer.customer_org_id
    assert replay.revision == 2

    connection = factory.open_authoritative(read_only=True, require_wal=True)
    try:
        stored = connection.execute(
            "SELECT response_schema,response_version,response_json FROM command_receipt_results WHERE command_id=?",
            (command_id,),
        ).fetchone()
        assert tuple(stored[:2]) == ("ReferenceMutationResultV1", 1)
        assert json.loads(str(stored[2])) == {
            "outcome": "APPLIED",
            "revision": 2,
            "target_id": customer.customer_org_id,
        }
        live = connection.execute(
            "SELECT name,revision FROM customer_organizations WHERE customer_org_id=?",
            (customer.customer_org_id,),
        ).fetchone()
        assert tuple(live) == ("Replay Customer Later", 3)
    finally:
        connection.close()


def test_customer_reassignment_replay_keeps_destination_revision_after_later_change(initialized_database, monkeypatch) -> None:
    factory = _factory(initialized_database)
    service = CustomerReferenceService(factory)
    source = service.create_customer_organization(
        command_id=new_uuid4(),
        name="Reassign Source",
        account_code="ACC-REASSIGN-1",
    )
    destination = service.create_customer_organization(
        command_id=new_uuid4(),
        name="Reassign Destination",
    )
    preview = service.preview_account_code_review(
        raw_account_code="ACC-REASSIGN-1",
        proposed_action="REASSIGN_CLAIM",
        target_customer_org_id=destination.customer_org_id,
        from_customer_org_id=source.customer_org_id,
    )
    command_id = new_uuid4()
    first = service.reassign_customer_account_code(
        command_id=command_id,
        from_customer_org_id=source.customer_org_id,
        from_base_revision=1,
        to_customer_org_id=destination.customer_org_id,
        to_base_revision=1,
        account_code="ACC-REASSIGN-1",
        review_snapshot_hash=preview.review_snapshot_hash,
        reason_category="provider_ownership_corrected",
    )
    assert first.outcome == "APPLIED"
    assert first.target_id == destination.customer_org_id
    assert first.revision == 2

    service.update_descriptive_data(
        command_id=new_uuid4(),
        customer_org_id=destination.customer_org_id,
        base_revision=2,
        name="Reassign Destination Later",
    )

    monkeypatch.setattr(
        CustomerReferenceService,
        "_active_customer",
        staticmethod(lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("Customer owner read during replay"))),
    )
    replay = service.reassign_customer_account_code(
        command_id=command_id,
        from_customer_org_id=source.customer_org_id,
        from_base_revision=1,
        to_customer_org_id=destination.customer_org_id,
        to_base_revision=1,
        account_code="ACC-REASSIGN-1",
        review_snapshot_hash=preview.review_snapshot_hash,
        reason_category="provider_ownership_corrected",
    )
    assert replay.replayed is True
    assert replay.outcome == "APPLIED"
    assert replay.target_id == destination.customer_org_id
    assert replay.revision == 2

    connection = factory.open_authoritative(read_only=True, require_wal=True)
    try:
        live = connection.execute(
            "SELECT revision FROM customer_organizations WHERE customer_org_id=?",
            (destination.customer_org_id,),
        ).fetchone()
        assert live[0] == 3
        assert connection.execute(
            "SELECT COUNT(*) FROM audit_events WHERE command_id=?",
            (command_id,),
        ).fetchone()[0] == 1
    finally:
        connection.close()
