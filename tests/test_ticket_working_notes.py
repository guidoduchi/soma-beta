from __future__ import annotations

import json

import pytest

from soma.foundation.errors import SomaError, ValidationError
from soma.foundation.identifiers import new_uuid4
from soma.foundation.persistence.uow import UnitOfWork
from soma.reference.application.profile_service import LocalUserProfileService
from soma.tickets.audit_registry import build_tickets_audit_registry
from soma.tickets.rfcs import RfcService
from soma.tickets.service_requests import ServiceRequestService
from soma.tickets.working_notes import WorkingNoteService


def _factory(initialized_database):
    database_path, factory_for_path = initialized_database
    return factory_for_path(database_path)


def _read(initialized_database):
    return _factory(initialized_database).open_authoritative(read_only=True, require_wal=True)


def _ensure_profile(factory) -> str:
    profiles = LocalUserProfileService(factory)
    profile_id = new_uuid4()
    with UnitOfWork(factory) as uow:
        command_id = new_uuid4()
        uow.connection.execute(
            "INSERT INTO command_receipts(command_id,command_type,request_hash,target_type,target_id,committed_at_utc,result_type,result_id) "
            "VALUES (?, 'TestSetupProfile', ?, 'local_user_profile', NULL, 1, NULL, NULL)",
            (command_id, "0" * 64),
        )
        profiles.ensure_singleton_local_administrator(
            uow,
            parent_command_id=command_id,
            profile_id=profile_id,
        )
    return profile_id


def test_working_notes_preserve_creator_edit_history_and_removal_evidence(initialized_database) -> None:
    factory = _factory(initialized_database)
    profile_id = _ensure_profile(factory)
    srs = ServiceRequestService(factory)
    rfcs = RfcService(factory)
    notes = WorkingNoteService(factory)
    profiles = LocalUserProfileService(factory)

    sr = srs.create_manual_service_request(command_id=new_uuid4())
    rfc = rfcs.create_or_adopt_identity(
        command_id=new_uuid4(),
        rfc_no="NC20260804005001",
        creation_context="manual",
    )

    sr_note = notes.add(
        command_id=new_uuid4(),
        owner_type="service_request",
        owner_id=sr.service_request_id,
        body_text="first SR note",
    )
    rfc_note = notes.add(
        command_id=new_uuid4(),
        owner_type="rfc",
        owner_id=rfc.rfc_id,
        body_text="RFC note remains",
    )
    assert sr_note.revision == 1
    assert rfc_note.revision == 1

    connection = _read(initialized_database)
    try:
        original = connection.execute(
            "SELECT created_by_local_user_profile_id,created_at_utc,updated_at_utc FROM sr_working_notes WHERE working_note_id=?",
            (sr_note.working_note_id,),
        ).fetchone()
        assert original is not None
        assert str(original[0]) == profile_id
        original_created_at = int(original[1])
    finally:
        connection.close()

    profiles.update_display_name(
        command_id=new_uuid4(),
        base_revision=1,
        display_name="Renamed Local Administrator",
        actor_id=profile_id,
    )

    edited = notes.edit(
        command_id=new_uuid4(),
        owner_type="service_request",
        owner_id=sr.service_request_id,
        working_note_id=sr_note.working_note_id,
        base_revision=1,
        body_text="second SR note",
    )
    assert edited.revision == 2
    assert edited.no_change is False

    no_change = notes.edit(
        command_id=new_uuid4(),
        owner_type="service_request",
        owner_id=sr.service_request_id,
        working_note_id=sr_note.working_note_id,
        base_revision=2,
        body_text="second SR note",
    )
    assert no_change.no_change is True
    assert no_change.revision == 2

    remove_command = new_uuid4()
    removed = notes.remove(
        command_id=remove_command,
        owner_type="service_request",
        owner_id=sr.service_request_id,
        working_note_id=sr_note.working_note_id,
        base_revision=2,
        reason_category="operator_remove",
    )
    assert removed.removed is True
    assert removed.revision == 2

    replay = notes.remove(
        command_id=remove_command,
        owner_type="service_request",
        owner_id=sr.service_request_id,
        working_note_id=sr_note.working_note_id,
        base_revision=2,
        reason_category="operator_remove",
    )
    assert replay.replayed is True
    assert replay.removed is True

    connection = _read(initialized_database)
    try:
        assert connection.execute(
            "SELECT count(*) FROM sr_working_notes WHERE working_note_id=?",
            (sr_note.working_note_id,),
        ).fetchone()[0] == 0
        rfc_row = connection.execute(
            "SELECT body_text,created_by_local_user_profile_id FROM rfc_working_notes WHERE working_note_id=?",
            (rfc_note.working_note_id,),
        ).fetchone()
        assert rfc_row is not None
        assert str(rfc_row[0]) == "RFC note remains"
        assert str(rfc_row[1]) == profile_id

        note_audits = connection.execute(
            "SELECT action_type,payload_json FROM audit_events WHERE action_type LIKE 'ticket.working_note.%' ORDER BY recorded_at_utc,audit_event_id"
        ).fetchall()
        assert len(note_audits) == 4
        payloads = [(str(row[0]), json.loads(str(row[1]))) for row in note_audits]
        added_payloads = [payload for action, payload in payloads if action == "ticket.working_note.added"]
        edited_payload = next(payload for action, payload in payloads if action == "ticket.working_note.edited")
        removed_payload = next(payload for action, payload in payloads if action == "ticket.working_note.removed")
        assert len(added_payloads) == 2
        assert all(
            payload["bounded_prior_or_new_body_when_required_by_removal_or_edit_policy"] is None
            for payload in added_payloads
        )
        assert edited_payload["bounded_prior_or_new_body_when_required_by_removal_or_edit_policy"] == "first SR note"
        assert removed_payload["bounded_prior_or_new_body_when_required_by_removal_or_edit_policy"] == "second SR note"
        assert edited_payload["created_by_local_user_profile_id"] == profile_id
        assert removed_payload["created_by_local_user_profile_id"] == profile_id

        creation_audit = connection.execute(
            "SELECT recorded_at_utc FROM audit_events WHERE action_type='ticket.working_note.added' AND target_id=?",
            (sr_note.working_note_id,),
        ).fetchone()
        assert creation_audit is not None
        assert original_created_at >= 0
    finally:
        connection.close()


def test_working_note_owner_and_revision_are_authoritative(initialized_database) -> None:
    factory = _factory(initialized_database)
    _ensure_profile(factory)
    srs = ServiceRequestService(factory)
    rfcs = RfcService(factory)
    notes = WorkingNoteService(factory)
    sr = srs.create_manual_service_request(command_id=new_uuid4())
    rfc = rfcs.create_or_adopt_identity(
        command_id=new_uuid4(),
        rfc_no="NC20260804005002",
        creation_context="manual",
    )
    note = notes.add(
        command_id=new_uuid4(),
        owner_type="service_request",
        owner_id=sr.service_request_id,
        body_text="owned by SR",
    )

    with pytest.raises(SomaError) as wrong_owner:
        notes.edit(
            command_id=new_uuid4(),
            owner_type="rfc",
            owner_id=rfc.rfc_id,
            working_note_id=note.working_note_id,
            base_revision=1,
            body_text="wrong owner",
        )
    assert wrong_owner.value.code == "WORKING_NOTE_NOT_FOUND"

    notes.edit(
        command_id=new_uuid4(),
        owner_type="service_request",
        owner_id=sr.service_request_id,
        working_note_id=note.working_note_id,
        base_revision=1,
        body_text="revision two",
    )
    with pytest.raises(SomaError) as stale:
        notes.remove(
            command_id=new_uuid4(),
            owner_type="service_request",
            owner_id=sr.service_request_id,
            working_note_id=note.working_note_id,
            base_revision=1,
        )
    assert stale.value.code == "STALE_REVISION"


def test_working_note_bounds_reject_without_mutation_and_accept_maximum_bytes(initialized_database) -> None:
    factory = _factory(initialized_database)
    _ensure_profile(factory)
    sr = ServiceRequestService(factory).create_manual_service_request(command_id=new_uuid4())
    notes = WorkingNoteService(factory)

    maximum = notes.add(
        command_id=new_uuid4(),
        owner_type="service_request",
        owner_id=sr.service_request_id,
        body_text="x" * 65_536,
    )
    assert maximum.revision == 1

    invalid_values = [
        "",
        "x\x00y",
        "x" * 65_537,
        ("line\n" * 512) + "line",
    ]
    for value in invalid_values:
        with pytest.raises(ValidationError):
            notes.add(
                command_id=new_uuid4(),
                owner_type="service_request",
                owner_id=sr.service_request_id,
                body_text=value,
            )

    connection = _read(initialized_database)
    try:
        assert connection.execute(
            "SELECT count(*) FROM sr_working_notes WHERE service_request_id=?",
            (sr.service_request_id,),
        ).fetchone()[0] == 1
    finally:
        connection.close()


def test_working_note_edit_and_remove_allow_bounded_json_escape_expansion(initialized_database) -> None:
    factory = _factory(initialized_database)
    _ensure_profile(factory)
    sr = ServiceRequestService(factory).create_manual_service_request(command_id=new_uuid4())
    notes = WorkingNoteService(factory)
    escaping_body = "\x01" * 65_536

    edited_note = notes.add(
        command_id=new_uuid4(),
        owner_type="service_request",
        owner_id=sr.service_request_id,
        body_text=escaping_body,
    )
    edited = notes.edit(
        command_id=new_uuid4(),
        owner_type="service_request",
        owner_id=sr.service_request_id,
        working_note_id=edited_note.working_note_id,
        base_revision=1,
        body_text="replacement",
    )
    assert edited.revision == 2

    removed_note = notes.add(
        command_id=new_uuid4(),
        owner_type="service_request",
        owner_id=sr.service_request_id,
        body_text=escaping_body,
    )
    removed = notes.remove(
        command_id=new_uuid4(),
        owner_type="service_request",
        owner_id=sr.service_request_id,
        working_note_id=removed_note.working_note_id,
        base_revision=1,
        reason_category="operator_remove",
    )
    assert removed.removed is True

    connection = _read(initialized_database)
    try:
        payload_rows = connection.execute(
            "SELECT action_type,payload_json FROM audit_events "
            "WHERE target_id IN (?,?) AND action_type IN ('ticket.working_note.edited','ticket.working_note.removed') "
            "ORDER BY action_type",
            (edited_note.working_note_id, removed_note.working_note_id),
        ).fetchall()
        assert len(payload_rows) == 2
        assert all(len(str(row[1]).encode("utf-8")) > 16_384 for row in payload_rows)
        assert all(len(str(row[1]).encode("utf-8")) <= 524_288 for row in payload_rows)
        assert all(
            json.loads(str(row[1]))["bounded_prior_or_new_body_when_required_by_removal_or_edit_policy"]
            == escaping_body
            for row in payload_rows
        )
    finally:
        connection.close()


def test_working_note_large_audit_allowance_is_body_scoped() -> None:
    registry = build_tickets_audit_registry()
    added = registry.resolve("ticket.working_note.added", 1)
    edited = registry.resolve("ticket.working_note.edited", 1)
    removed = registry.resolve("ticket.working_note.removed", 1)
    assert added.payload_contract.max_utf8_bytes == 16_384
    assert edited.payload_contract.max_utf8_bytes == 524_288
    assert removed.payload_contract.max_utf8_bytes == 524_288
    assert edited.sensitivity_validator is not None

    payload = {
        "working_note_id": "w" * 17_000,
        "owner_type": "service_request",
        "owner_id": "owner",
        "resulting_revision": 2,
        "created_by_local_user_profile_id": "profile",
        "change_kind": "edited",
        "reason_category": None,
        "bounded_prior_or_new_body_when_required_by_removal_or_edit_policy": "body",
    }
    validated = edited.payload_contract.validate(payload)
    with pytest.raises(SomaError) as oversized_metadata:
        edited.sensitivity_validator(validated)
    assert oversized_metadata.value.code == "AUDIT_PAYLOAD_INVALID"
