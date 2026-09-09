from __future__ import annotations

import json

from soma.foundation.identifiers import new_uuid4
from soma.reference.application.contact_service import ContactReferenceService


def _factory(initialized_database):
    database_path, factory_for_path = initialized_database
    return factory_for_path(database_path)


def test_contact_channel_update_replay_keeps_original_channel_revision(initialized_database, monkeypatch) -> None:
    factory = _factory(initialized_database)
    service = ContactReferenceService(factory)
    contact = service.create_contact(command_id=new_uuid4(), name="Replay Channel Owner")
    added = service.add_contact_channel(
        command_id=new_uuid4(),
        contact_id=contact.contact_id,
        contact_base_revision=1,
        channel_kind="email",
        value_text="first@example.com",
    )
    assert added.outcome == "APPLIED"
    assert added.revision == 1
    channel_id = added.target_id

    command_id = new_uuid4()
    first = service.update_contact_channel(
        command_id=command_id,
        contact_id=contact.contact_id,
        contact_base_revision=2,
        contact_channel_id=channel_id,
        channel_base_revision=1,
        value_text="second@example.com",
    )
    assert first.outcome == "APPLIED"
    assert first.target_id == channel_id
    assert first.revision == 2
    assert first.replayed is False

    archived = service.archive_contact_channel(
        command_id=new_uuid4(),
        contact_id=contact.contact_id,
        contact_base_revision=3,
        contact_channel_id=channel_id,
        channel_base_revision=2,
        reason_category="channel_retired",
    )
    assert archived.revision == 3

    monkeypatch.setattr(
        ContactReferenceService,
        "_active_contact",
        staticmethod(lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("Contact owner read during replay"))),
    )
    monkeypatch.setattr(
        ContactReferenceService,
        "_channel",
        staticmethod(lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("Channel owner read during replay"))),
    )
    replay = service.update_contact_channel(
        command_id=command_id,
        contact_id=contact.contact_id,
        contact_base_revision=2,
        contact_channel_id=channel_id,
        channel_base_revision=1,
        value_text="second@example.com",
    )
    assert replay.replayed is True
    assert replay.outcome == "APPLIED"
    assert replay.target_id == channel_id
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
            "target_id": channel_id,
        }
        live_channel = connection.execute(
            "SELECT lifecycle_state,revision FROM contact_channels WHERE contact_channel_id=?",
            (channel_id,),
        ).fetchone()
        assert tuple(live_channel) == ("archived", 3)
        live_contact_revision = connection.execute(
            "SELECT revision FROM contacts WHERE contact_id=?",
            (contact.contact_id,),
        ).fetchone()[0]
        assert live_contact_revision == 4
    finally:
        connection.close()
