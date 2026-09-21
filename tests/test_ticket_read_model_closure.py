from __future__ import annotations

from dataclasses import dataclass

import pytest

from soma.foundation.errors import IntegrityFailure, ValidationError
from soma.foundation.identifiers import new_uuid4
from soma.foundation.persistence.uow import ReadSnapshot, UnitOfWork
from soma.reference.application.profile_service import LocalUserProfileService
from soma.tickets.device_references import DeviceReferenceService
from soma.tickets.queries.device_references import TicketDeviceReferenceQueryService
from soma.tickets.queries.relationship_previews import SrRfcLinkPreviewQueryService
from soma.tickets.queries.relationships import ServiceRequestRfcQueryService
from soma.tickets.queries.working_notes import WorkingNoteQueryService
from soma.tickets.relationships import (
    ServiceRequestRfcRelationshipService,
    TicketDeviceReferenceRelationshipService,
)
from soma.tickets.rfc_hierarchy import RfcHierarchyService
from soma.tickets.rfcs import RfcService
from soma.tickets.service_requests import ServiceRequestService
from soma.tickets.working_notes import WorkingNoteService


def _factory(initialized_database):
    database_path, factory_for_path = initialized_database
    return factory_for_path(database_path)


def _rfc(rfcs: RfcService, ordinal: int):
    return rfcs.create_or_adopt_identity(
        command_id=new_uuid4(),
        rfc_no=f"NC20260910{ordinal:06d}",
        creation_context="manual",
    )


def _add_children(factory, root, children):
    hierarchy = RfcHierarchyService(factory)
    root_revision = root.revision
    for child in children:
        result = hierarchy.add_subordinate(
            command_id=new_uuid4(),
            parent_rfc_id=root.rfc_id,
            child_rfc_id=child.rfc_id,
            base_revisions={root.rfc_id: root_revision, child.rfc_id: child.revision},
            reason_category="reviewed_hierarchy",
        )
        root_revision = result.root.revision
    return root_revision


def _ensure_profile(factory) -> str:
    profile_id = new_uuid4()
    profiles = LocalUserProfileService(factory)
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


def test_service_request_rfc_branch_projection_pages_and_preserves_direct_root_provenance(initialized_database) -> None:
    factory = _factory(initialized_database)
    srs = ServiceRequestService(factory)
    rfcs = RfcService(factory)
    links = ServiceRequestRfcRelationshipService(factory)
    query = ServiceRequestRfcQueryService(factory)

    sr = srs.create_manual_service_request(command_id=new_uuid4())
    other_sr = srs.create_manual_service_request(command_id=new_uuid4())
    root_a = _rfc(rfcs, 1001)
    child_a1 = _rfc(rfcs, 1002)
    child_a2 = _rfc(rfcs, 1003)
    root_b = _rfc(rfcs, 1004)
    root_a_revision = _add_children(factory, root_a, (child_a1, child_a2))

    links.link(
        command_id=new_uuid4(),
        service_request_id=sr.service_request_id,
        rfc_id=root_a.rfc_id,
        sr_base_revision=sr.revision,
        rfc_base_revision=root_a_revision,
    )
    links.link(
        command_id=new_uuid4(),
        service_request_id=sr.service_request_id,
        rfc_id=root_b.rfc_id,
        sr_base_revision=sr.revision + 1,
        rfc_base_revision=root_b.revision,
    )

    pages = []
    cursor = None
    while True:
        page = query.list_branches(
            service_request_id=sr.service_request_id,
            cursor=cursor,
            limit=2,
        )
        pages.extend(page.items)
        cursor = page.continuation
        if cursor is None:
            break

    expected = sorted(
        (
            (root_a.rfc_id, 0, root_a.rfc_id, "root"),
            (root_a.rfc_id, 1, child_a1.rfc_id, "subordinate"),
            (root_a.rfc_id, 1, child_a2.rfc_id, "subordinate"),
            (root_b.rfc_id, 0, root_b.rfc_id, "root"),
        ),
        key=lambda item: (item[0], item[1], item[2]),
    )
    assert [(item.root_rfc_id, 0 if item.role == "root" else 1, item.member_rfc_id, item.role) for item in pages] == expected
    assert len({item.member_rfc_id for item in pages}) == 4
    for root_id in {root_a.rfc_id, root_b.rfc_id}:
        direct_ids = {item.direct_link_id for item in pages if item.root_rfc_id == root_id}
        assert len(direct_ids) == 1

    first_page = query.list_branches(service_request_id=sr.service_request_id, limit=1)
    assert first_page.continuation is not None
    with pytest.raises(ValidationError):
        query.list_branches(
            service_request_id=other_sr.service_request_id,
            cursor=first_page.continuation,
            limit=1,
        )


def test_effective_sr_context_and_preview_resolve_subordinate_without_fabricating_direct_link(initialized_database) -> None:
    factory = _factory(initialized_database)
    srs = ServiceRequestService(factory)
    rfcs = RfcService(factory)
    links = ServiceRequestRfcRelationshipService(factory)
    relationship_query = ServiceRequestRfcQueryService(factory)
    preview_query = SrRfcLinkPreviewQueryService(factory)

    sr = srs.create_manual_service_request(command_id=new_uuid4())
    root = _rfc(rfcs, 1101)
    child = _rfc(rfcs, 1102)
    root_revision = _add_children(factory, root, (child,))

    with ReadSnapshot(factory) as snapshot:
        receipts_before = int(snapshot.connection.execute("SELECT count(*) FROM command_receipts").fetchone()[0])
    preview = preview_query.preview(service_request_id=sr.service_request_id, rfc_id=child.rfc_id)
    with ReadSnapshot(factory) as snapshot:
        receipts_after = int(snapshot.connection.execute("SELECT count(*) FROM command_receipts").fetchone()[0])

    assert receipts_after == receipts_before
    assert preview.requested_rfc_id == child.rfc_id
    assert preview.governing_root_rfc_id == root.rfc_id
    assert preview.subordinate_origin_rfc_id == child.rfc_id
    assert preview.duplicate_active is False

    links.link(
        command_id=new_uuid4(),
        service_request_id=sr.service_request_id,
        rfc_id=preview.governing_root_rfc_id,
        subordinate_origin_rfc_id=preview.subordinate_origin_rfc_id,
        sr_base_revision=preview.sr_revision,
        rfc_base_revision=preview.rfc_revision,
        review_fingerprint=preview.review_fingerprint if preview.review_required else None,
    )

    inherited = relationship_query.effective_context_for_rfc(rfc_id=child.rfc_id)
    assert len(inherited.items) == 1
    assert inherited.items[0].service_request_id == sr.service_request_id
    assert inherited.items[0].governing_root_rfc_id == root.rfc_id
    assert inherited.items[0].requested_rfc_id == child.rfc_id
    assert inherited.items[0].inherited_via_root == root.rfc_id

    direct = relationship_query.effective_context_for_rfc(rfc_id=root.rfc_id)
    assert len(direct.items) == 1
    assert direct.items[0].inherited_via_root is None

    with ReadSnapshot(factory) as snapshot:
        assert snapshot.connection.execute(
            "SELECT count(*) FROM sr_rfc_links WHERE service_request_id=? AND rfc_id=?",
            (sr.service_request_id, child.rfc_id),
        ).fetchone()[0] == 0

    duplicate = preview_query.preview(service_request_id=sr.service_request_id, rfc_id=child.rfc_id)
    assert duplicate.duplicate_active is True
    assert duplicate.governing_root_rfc_id == root.rfc_id
    assert duplicate.subordinate_origin_rfc_id == child.rfc_id


@dataclass(frozen=True)
class _Resolution:
    network_element_id: str


class _ResolutionReader:
    def __init__(self, mapping):
        self.mapping = mapping
        self.calls = []

    def resolution_for(self, reader, device_reference_id):
        assert isinstance(reader, ReadSnapshot)
        self.calls.append(device_reference_id)
        network_element_id = self.mapping.get(device_reference_id)
        return None if network_element_id is None else _Resolution(network_element_id)


class _MalformedResolutionReader:
    def resolution_for(self, reader, device_reference_id):
        del reader, device_reference_id
        return {"unexpected": "value"}


def test_device_reference_queries_keep_owner_provenance_equal_names_and_optional_resolution(initialized_database) -> None:
    factory = _factory(initialized_database)
    rfcs = RfcService(factory)
    devices = DeviceReferenceService(factory)
    relationships = TicketDeviceReferenceRelationshipService(factory)

    root = _rfc(rfcs, 1201)
    child = _rfc(rfcs, 1202)
    _add_children(factory, root, (child,))
    device_root = devices.create(command_id=new_uuid4(), operational_name="same-hostname")
    device_child = devices.create(command_id=new_uuid4(), operational_name="same-hostname")
    assert device_root.device_reference_id != device_child.device_reference_id

    relationships.link(
        command_id=new_uuid4(),
        ticket_type="rfc",
        ticket_id=root.rfc_id,
        device_reference_id=device_root.device_reference_id,
        target_base_revision=2,
    )
    relationships.link(
        command_id=new_uuid4(),
        ticket_type="rfc",
        ticket_id=child.rfc_id,
        device_reference_id=device_child.device_reference_id,
        target_base_revision=2,
    )

    network_element_id = new_uuid4()
    resolver = _ResolutionReader({device_root.device_reference_id: network_element_id})
    query = TicketDeviceReferenceQueryService(factory, resolver)

    root_page = query.list_for_ticket(ticket_type="rfc", ticket_id=root.rfc_id)
    assert len(root_page.items) == 1
    assert root_page.items[0].device_reference_id == device_root.device_reference_id
    assert root_page.items[0].operational_name == "same-hostname"
    assert root_page.items[0].registered_network_element_id == network_element_id

    child_page = query.list_for_ticket(ticket_type="rfc", ticket_id=child.rfc_id)
    assert len(child_page.items) == 1
    assert child_page.items[0].device_reference_id == device_child.device_reference_id
    assert child_page.items[0].operational_name == "same-hostname"
    assert child_page.items[0].registered_network_element_id is None

    rows = []
    cursor = None
    while True:
        page = query.branch_context(root_rfc_id=root.rfc_id, cursor=cursor, limit=1)
        rows.extend(page.items)
        cursor = page.continuation
        if cursor is None:
            break
    assert {(row.owning_rfc_id, row.role, row.device_reference.device_reference_id) for row in rows} == {
        (root.rfc_id, "root", device_root.device_reference_id),
        (child.rfc_id, "subordinate", device_child.device_reference_id),
    }
    assert all(row.device_reference.operational_name == "same-hostname" for row in rows)
    assert resolver.calls.count(device_root.device_reference_id) >= 2
    assert resolver.calls.count(device_child.device_reference_id) >= 2

    with pytest.raises(IntegrityFailure):
        TicketDeviceReferenceQueryService(factory, _MalformedResolutionReader()).list_for_ticket(
            ticket_type="rfc",
            ticket_id=root.rfc_id,
        )


def test_device_reference_cursor_cannot_be_rebound_to_another_ticket(initialized_database) -> None:
    factory = _factory(initialized_database)
    rfcs = RfcService(factory)
    devices = DeviceReferenceService(factory)
    relationships = TicketDeviceReferenceRelationshipService(factory)
    query = TicketDeviceReferenceQueryService(factory)

    first = _rfc(rfcs, 1301)
    second = _rfc(rfcs, 1302)
    for ordinal in range(2):
        device = devices.create(command_id=new_uuid4(), operational_name=f"first-{ordinal}")
        relationships.link(
            command_id=new_uuid4(),
            ticket_type="rfc",
            ticket_id=first.rfc_id,
            device_reference_id=device.device_reference_id,
            target_base_revision=1,
        )
    page = query.list_for_ticket(ticket_type="rfc", ticket_id=first.rfc_id, limit=1)
    assert page.continuation is not None
    with pytest.raises(ValidationError):
        query.list_for_ticket(
            ticket_type="rfc",
            ticket_id=second.rfc_id,
            cursor=page.continuation,
            limit=1,
        )


def test_working_note_query_pages_current_rows_and_preserves_creator_identity(initialized_database) -> None:
    factory = _factory(initialized_database)
    profile_id = _ensure_profile(factory)
    srs = ServiceRequestService(factory)
    notes = WorkingNoteService(factory)
    query = WorkingNoteQueryService(factory)

    sr = srs.create_manual_service_request(command_id=new_uuid4())
    other_sr = srs.create_manual_service_request(command_id=new_uuid4())
    created = [
        notes.add(
            command_id=new_uuid4(),
            owner_type="service_request",
            owner_id=sr.service_request_id,
            body_text=f"note-{ordinal}",
        )
        for ordinal in range(3)
    ]

    first_page = query.list_notes(
        ticket_type="service_request",
        ticket_id=sr.service_request_id,
        limit=1,
    )
    assert first_page.continuation is not None
    with pytest.raises(ValidationError):
        query.list_notes(
            ticket_type="service_request",
            ticket_id=other_sr.service_request_id,
            cursor=first_page.continuation,
            limit=1,
        )

    rows = []
    cursor = None
    while True:
        page = query.list_notes(
            ticket_type="service_request",
            ticket_id=sr.service_request_id,
            cursor=cursor,
            limit=1,
        )
        rows.extend(page.items)
        cursor = page.continuation
        if cursor is None:
            break
    assert len(rows) == 3
    assert [(row.created_at_utc, row.working_note_id) for row in rows] == sorted(
        (row.created_at_utc, row.working_note_id) for row in rows
    )
    assert {row.working_note_id for row in rows} == {item.working_note_id for item in created}
    assert all(row.created_by_local_user_profile_id == profile_id for row in rows)

    target = rows[0]
    notes.edit(
        command_id=new_uuid4(),
        owner_type="service_request",
        owner_id=sr.service_request_id,
        working_note_id=target.working_note_id,
        base_revision=target.revision,
        body_text="edited-current-body",
    )
    edited_page = query.list_notes(ticket_type="service_request", ticket_id=sr.service_request_id)
    edited = next(row for row in edited_page.items if row.working_note_id == target.working_note_id)
    assert edited.body_text == "edited-current-body"
    assert edited.revision == target.revision + 1
    assert edited.created_at_utc == target.created_at_utc
    assert edited.created_by_local_user_profile_id == profile_id

    removed_target = next(row for row in edited_page.items if row.working_note_id != target.working_note_id)
    notes.remove(
        command_id=new_uuid4(),
        owner_type="service_request",
        owner_id=sr.service_request_id,
        working_note_id=removed_target.working_note_id,
        base_revision=removed_target.revision,
        reason_category="operator_remove",
    )
    remaining = query.list_notes(ticket_type="service_request", ticket_id=sr.service_request_id)
    assert removed_target.working_note_id not in {row.working_note_id for row in remaining.items}
    assert len(remaining.items) == 2
