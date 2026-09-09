from __future__ import annotations

import json

import pytest

from soma.foundation.errors import SomaError
from soma.foundation.identifiers import new_uuid4, utc_epoch_seconds
from soma.foundation.persistence.uow import UnitOfWork
from soma.reference.application.customer_service import CustomerReferenceService
from soma.tickets.relationships import ServiceRequestRfcRelationshipService
from soma.tickets.rfc_hierarchy import RfcHierarchyService
from soma.tickets.rfcs import RfcService
from soma.tickets.service_requests import ServiceRequestService


def _factory(initialized_database):
    database_path, factory_for_path = initialized_database
    return factory_for_path(database_path)


def _read(initialized_database):
    return _factory(initialized_database).open_authoritative(read_only=True, require_wal=True)


def _seed_terminal_sr(factory, service_request_id: str, accepted_command_id: str, *, status: str = "Closed") -> None:
    observation_id = new_uuid4()
    now = utc_epoch_seconds()
    with UnitOfWork(factory) as uow:
        uow.connection.execute(
            "INSERT INTO sr_source_field_observations("
            "sr_source_field_observation_id,service_request_id,field_key,value_state,value_kind,text_value,"
            "source_chronology_utc,precedence_basis,source_observation_field_id,accepted_command_id,recorded_at_utc"
            ") VALUES (?, ?, 'status', 'usable', 'controlled', ?, ?, 'source_chronology', ?, ?, ?)",
            (
                observation_id,
                service_request_id,
                status,
                now,
                f"test-source-status-{observation_id}",
                accepted_command_id,
                now,
            ),
        )
        current = uow.connection.execute(
            "SELECT revision FROM sr_current_source_projection WHERE service_request_id=?",
            (service_request_id,),
        ).fetchone()
        if current is None:
            uow.connection.execute(
                "INSERT INTO sr_current_source_projection(service_request_id,status_observation_id,revision) VALUES (?, ?, 1)",
                (service_request_id, observation_id),
            )
        else:
            uow.connection.execute(
                "UPDATE sr_current_source_projection SET status_observation_id=?,revision=revision+1 WHERE service_request_id=?",
                (observation_id, service_request_id),
            )


def test_sr_rfc_link_and_unlink_increment_both_ticket_revisions_once_and_replay_exact_result(initialized_database) -> None:
    factory = _factory(initialized_database)
    sr_service = ServiceRequestService(factory)
    rfc_service = RfcService(factory)
    relationships = ServiceRequestRfcRelationshipService(factory)

    sr = sr_service.create_manual_service_request(command_id=new_uuid4())
    rfc = rfc_service.create_or_adopt_identity(
        command_id=new_uuid4(),
        rfc_no="NC20260804002001",
        creation_context="manual",
    )

    before_receipts = _read(initialized_database)
    try:
        receipt_count = int(before_receipts.execute("SELECT COUNT(*) FROM command_receipts").fetchone()[0])
        audit_count = int(before_receipts.execute("SELECT COUNT(*) FROM audit_events").fetchone()[0])
    finally:
        before_receipts.close()

    preview = relationships.preview_link(service_request_id=sr.service_request_id, rfc_id=rfc.rfc_id)
    assert preview.sr_revision == 1
    assert preview.rfc_revision == 1
    assert preview.duplicate_active is False
    assert preview.review_required is False

    after_preview = _read(initialized_database)
    try:
        assert int(after_preview.execute("SELECT COUNT(*) FROM command_receipts").fetchone()[0]) == receipt_count
        assert int(after_preview.execute("SELECT COUNT(*) FROM audit_events").fetchone()[0]) == audit_count
    finally:
        after_preview.close()

    applied = relationships.link(
        command_id=new_uuid4(),
        service_request_id=sr.service_request_id,
        rfc_id=rfc.rfc_id,
        sr_base_revision=1,
        rfc_base_revision=1,
        review_fingerprint=preview.review_fingerprint,
    )
    assert applied.outcome == "APPLIED"
    assert applied.target_id == sr.service_request_id
    assert applied.revision == 2

    connection = _read(initialized_database)
    try:
        link_id = str(
            connection.execute(
                "SELECT sr_rfc_link_id FROM sr_rfc_links WHERE service_request_id=? AND rfc_id=? AND link_state='active'",
                (sr.service_request_id, rfc.rfc_id),
            ).fetchone()[0]
        )
        assert connection.execute(
            "SELECT revision FROM service_requests WHERE service_request_id=?",
            (sr.service_request_id,),
        ).fetchone()[0] == 2
        assert connection.execute(
            "SELECT revision FROM rfcs WHERE rfc_id=?",
            (rfc.rfc_id,),
        ).fetchone()[0] == 2
    finally:
        connection.close()

    duplicate = relationships.link(
        command_id=new_uuid4(),
        service_request_id=sr.service_request_id,
        rfc_id=rfc.rfc_id,
        sr_base_revision=2,
        rfc_base_revision=2,
    )
    assert duplicate.no_change is True
    assert duplicate.target_id == sr.service_request_id
    assert duplicate.revision == 2

    unlink_command = new_uuid4()
    unlinked = relationships.unlink(
        command_id=unlink_command,
        service_request_id=sr.service_request_id,
        root_rfc_id=rfc.rfc_id,
        sr_base_revision=2,
        rfc_base_revision=2,
        reason_category="reviewed_unlink",
    )
    assert unlinked.outcome == "APPLIED"
    assert unlinked.target_id == sr.service_request_id
    assert unlinked.revision == 3

    absent = relationships.unlink(
        command_id=new_uuid4(),
        service_request_id=sr.service_request_id,
        root_rfc_id=rfc.rfc_id,
        sr_base_revision=3,
        rfc_base_revision=3,
        reason_category="reviewed_unlink",
    )
    assert absent.no_change is True
    assert absent.target_id == sr.service_request_id
    assert absent.revision == 3

    with UnitOfWork(factory) as uow:
        uow.connection.execute(
            "UPDATE service_requests SET revision=9 WHERE service_request_id=?",
            (sr.service_request_id,),
        )
        uow.connection.execute(
            "UPDATE rfcs SET revision=10 WHERE rfc_id=?",
            (rfc.rfc_id,),
        )

    replay = relationships.unlink(
        command_id=unlink_command,
        service_request_id=sr.service_request_id,
        root_rfc_id=rfc.rfc_id,
        sr_base_revision=2,
        rfc_base_revision=2,
        reason_category="reviewed_unlink",
    )
    assert replay.replayed is True
    assert replay.outcome == "APPLIED"
    assert replay.target_id == sr.service_request_id
    assert replay.revision == 3

    connection = _read(initialized_database)
    try:
        history = connection.execute(
            "SELECT link_state,closed_at_utc,closed_command_id,reason_category FROM sr_rfc_links WHERE sr_rfc_link_id=?",
            (link_id,),
        ).fetchone()
        assert tuple(history)[:1] == ("unlinked",)
        assert history[1] is not None
        assert history[2] == unlink_command
        assert history[3] is None
        assert connection.execute(
            "SELECT revision FROM service_requests WHERE service_request_id=?",
            (sr.service_request_id,),
        ).fetchone()[0] == 9
        assert connection.execute(
            "SELECT revision FROM rfcs WHERE rfc_id=?",
            (rfc.rfc_id,),
        ).fetchone()[0] == 10
        unlink_audit = connection.execute(
            "SELECT reason_category,payload_json FROM audit_events WHERE command_id=? AND action_type='ticket.sr_rfc_relationship.changed'",
            (unlink_command,),
        ).fetchone()
        assert unlink_audit[0] == "reviewed_unlink"
        assert json.loads(str(unlink_audit[1]))["reason_category"] == "reviewed_unlink"
        stored = connection.execute(
            "SELECT response_schema,response_json FROM command_receipt_results WHERE command_id=?",
            (unlink_command,),
        ).fetchone()
        assert stored[0] == "TicketMutationResultV1"
        assert json.loads(str(stored[1])) == {
            "outcome": "APPLIED",
            "revision": 3,
            "target_id": sr.service_request_id,
        }
    finally:
        connection.close()


def test_sr_rfc_link_rejects_subordinate_target_and_preserves_origin_provenance(initialized_database) -> None:
    factory = _factory(initialized_database)
    sr_service = ServiceRequestService(factory)
    rfc_service = RfcService(factory)
    hierarchy = RfcHierarchyService(factory)
    relationships = ServiceRequestRfcRelationshipService(factory)

    sr = sr_service.create_manual_service_request(command_id=new_uuid4())
    root = rfc_service.create_or_adopt_identity(
        command_id=new_uuid4(), rfc_no="NC20260804002002", creation_context="manual"
    )
    child = rfc_service.create_or_adopt_identity(
        command_id=new_uuid4(), rfc_no="NC20260804002003", creation_context="manual"
    )
    hierarchy.add_subordinate(
        command_id=new_uuid4(),
        parent_rfc_id=root.rfc_id,
        child_rfc_id=child.rfc_id,
        base_revisions={root.rfc_id: 1, child.rfc_id: 1},
        reason_category="reviewed_hierarchy",
    )

    with pytest.raises(SomaError) as excinfo:
        relationships.preview_link(service_request_id=sr.service_request_id, rfc_id=child.rfc_id)
    assert excinfo.value.code == "RFC_DIRECT_SR_LINK_ON_SUBORDINATE"

    preview = relationships.preview_link(
        service_request_id=sr.service_request_id,
        rfc_id=root.rfc_id,
        subordinate_origin_rfc_id=child.rfc_id,
    )
    result = relationships.link(
        command_id=new_uuid4(),
        service_request_id=sr.service_request_id,
        rfc_id=root.rfc_id,
        sr_base_revision=1,
        rfc_base_revision=2,
        subordinate_origin_rfc_id=child.rfc_id,
        review_fingerprint=preview.review_fingerprint,
    )
    assert result.outcome == "APPLIED"
    assert result.target_id == sr.service_request_id
    assert result.revision == 2

    connection = _read(initialized_database)
    try:
        assert connection.execute(
            "SELECT COUNT(*) FROM sr_rfc_links WHERE service_request_id=? AND rfc_id=? AND link_state='active'",
            (sr.service_request_id, child.rfc_id),
        ).fetchone()[0] == 0
        audit = connection.execute(
            "SELECT payload_json FROM audit_events WHERE action_type='ticket.sr_rfc_relationship.changed' "
            "AND target_id=? ORDER BY recorded_at_utc DESC,audit_event_id DESC LIMIT 1",
            (sr.service_request_id,),
        ).fetchone()
        payload = json.loads(str(audit[0]))
        assert payload["right_id"] == root.rfc_id
        assert payload["subordinate_origin_rfc_id"] == child.rfc_id
    finally:
        connection.close()


def test_terminal_sr_link_requires_exact_fresh_review_and_failure_has_no_receipt(initialized_database) -> None:
    factory = _factory(initialized_database)
    sr_service = ServiceRequestService(factory)
    rfc_service = RfcService(factory)
    relationships = ServiceRequestRfcRelationshipService(factory)

    create_sr_command = new_uuid4()
    sr = sr_service.create_manual_service_request(command_id=create_sr_command)
    rfc = rfc_service.create_or_adopt_identity(
        command_id=new_uuid4(), rfc_no="NC20260804002004", creation_context="manual"
    )
    _seed_terminal_sr(factory, sr.service_request_id, create_sr_command)

    preview = relationships.preview_link(service_request_id=sr.service_request_id, rfc_id=rfc.rfc_id)
    assert preview.review_required is True
    failed_command = new_uuid4()
    with pytest.raises(SomaError) as excinfo:
        relationships.link(
            command_id=failed_command,
            service_request_id=sr.service_request_id,
            rfc_id=rfc.rfc_id,
            sr_base_revision=1,
            rfc_base_revision=1,
        )
    assert excinfo.value.code == "TICKET_RELATIONSHIP_STALE"

    connection = _read(initialized_database)
    try:
        assert connection.execute(
            "SELECT 1 FROM command_receipts WHERE command_id=?", (failed_command,)
        ).fetchone() is None
    finally:
        connection.close()

    applied = relationships.link(
        command_id=new_uuid4(),
        service_request_id=sr.service_request_id,
        rfc_id=rfc.rfc_id,
        sr_base_revision=1,
        rfc_base_revision=1,
        review_fingerprint=preview.review_fingerprint,
    )
    assert applied.outcome == "APPLIED"
    assert applied.target_id == sr.service_request_id
    assert applied.revision == 2


def test_lifecycle_change_after_preview_stales_relationship_review(initialized_database) -> None:
    factory = _factory(initialized_database)
    sr_service = ServiceRequestService(factory)
    rfc_service = RfcService(factory)
    relationships = ServiceRequestRfcRelationshipService(factory)

    create_sr_command = new_uuid4()
    sr = sr_service.create_manual_service_request(command_id=create_sr_command)
    rfc = rfc_service.create_or_adopt_identity(
        command_id=new_uuid4(), rfc_no="NC20260804002005", creation_context="manual"
    )
    preview = relationships.preview_link(service_request_id=sr.service_request_id, rfc_id=rfc.rfc_id)
    assert preview.review_required is False

    _seed_terminal_sr(factory, sr.service_request_id, create_sr_command)
    with pytest.raises(SomaError) as excinfo:
        relationships.link(
            command_id=new_uuid4(),
            service_request_id=sr.service_request_id,
            rfc_id=rfc.rfc_id,
            sr_base_revision=1,
            rfc_base_revision=1,
            review_fingerprint=preview.review_fingerprint,
        )
    assert excinfo.value.code == "TICKET_RELATIONSHIP_STALE"


def test_sr_rfc_link_blocks_known_customer_mismatch(initialized_database) -> None:
    factory = _factory(initialized_database)
    customers = CustomerReferenceService(factory)
    customer_a = customers.create_customer_organization(command_id=new_uuid4(), name="Customer A")
    customer_b = customers.create_customer_organization(command_id=new_uuid4(), name="Customer B")
    sr_service = ServiceRequestService(factory)
    rfc_service = RfcService(factory)
    relationships = ServiceRequestRfcRelationshipService(factory)

    sr_command = new_uuid4()
    sr = sr_service.create_manual_service_request(command_id=sr_command)
    rfc = rfc_service.create_or_adopt_identity(
        command_id=new_uuid4(),
        rfc_no="NC20260804002006",
        creation_context="manual",
        customer_org_id=customer_a.customer_org_id,
    )
    with UnitOfWork(factory) as uow:
        uow.connection.execute(
            "INSERT INTO sr_customer_relationships("
            "sr_customer_relationship_id,service_request_id,customer_org_id,relationship_state,origin_kind,opened_at_utc,opened_command_id"
            ") VALUES (?, ?, ?, 'active', 'manual_review', ?, ?)",
            (new_uuid4(), sr.service_request_id, customer_b.customer_org_id, utc_epoch_seconds(), sr_command),
        )

    with pytest.raises(SomaError) as excinfo:
        relationships.preview_link(service_request_id=sr.service_request_id, rfc_id=rfc.rfc_id)
    assert excinfo.value.code == "RFC_CUSTOMER_MISMATCH"
