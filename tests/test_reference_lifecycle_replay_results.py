from __future__ import annotations

import json

from soma.foundation.identifiers import new_uuid4
from soma.reference.application.contact_service import ContactReferenceService
from soma.reference.application.lifecycle_service import ReferenceLifecycleService


def _factory(initialized_database):
    database_path, factory_for_path = initialized_database
    return factory_for_path(database_path)


def test_archive_replay_returns_original_revision_after_later_reactivation(initialized_database, monkeypatch) -> None:
    factory = _factory(initialized_database)
    contact = ContactReferenceService(factory).create_contact(
        command_id=new_uuid4(),
        name="Lifecycle Replay Contact",
    )
    service = ReferenceLifecycleService(factory)
    archive_command_id = new_uuid4()

    archived = service.archive_reference(
        command_id=archive_command_id,
        target_type="contact",
        target_id=contact.contact_id,
        base_revision=1,
        reason_category="operator_archive",
    )
    assert archived.outcome == "APPLIED"
    assert archived.target_id == contact.contact_id
    assert archived.revision == 2
    assert archived.replayed is False

    reactivated = service.reactivate_reference(
        command_id=new_uuid4(),
        target_type="contact",
        target_id=contact.contact_id,
        base_revision=2,
        reason_category="operator_reactivate",
    )
    assert reactivated.revision == 3

    def forbidden_owner_read(*_args, **_kwargs):
        raise AssertionError("Reference lifecycle owner state must not be read during committed replay")

    monkeypatch.setattr(ReferenceLifecycleService, "_load", classmethod(forbidden_owner_read))
    replay = service.archive_reference(
        command_id=archive_command_id,
        target_type="contact",
        target_id=contact.contact_id,
        base_revision=1,
        reason_category="operator_archive",
    )
    assert replay.replayed is True
    assert replay.outcome == "APPLIED"
    assert replay.target_id == contact.contact_id
    assert replay.revision == 2

    connection = factory.open_authoritative(read_only=True, require_wal=True)
    try:
        stored = connection.execute(
            "SELECT response_schema,response_version,response_json FROM command_receipt_results WHERE command_id=?",
            (archive_command_id,),
        ).fetchone()
        assert tuple(stored[:2]) == ("ReferenceMutationResultV1", 1)
        assert json.loads(str(stored[2])) == {
            "outcome": "APPLIED",
            "revision": 2,
            "target_id": contact.contact_id,
        }
        live = connection.execute(
            "SELECT lifecycle_state,revision FROM contacts WHERE contact_id=?",
            (contact.contact_id,),
        ).fetchone()
        assert tuple(live) == ("active", 3)
        assert connection.execute(
            "SELECT COUNT(*) FROM reference_lifecycle_events WHERE target_id=?",
            (contact.contact_id,),
        ).fetchone()[0] == 3
    finally:
        connection.close()
