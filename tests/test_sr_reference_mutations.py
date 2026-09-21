from __future__ import annotations

import json

import pytest

from soma.foundation.errors import SomaError
from soma.foundation.identifiers import new_uuid4, utc_epoch_seconds
from soma.foundation.persistence.uow import UnitOfWork
from soma.reference.application.contact_service import ContactReferenceService
from soma.reference.application.customer_service import CustomerReferenceService
from soma.tickets.queries.sr_references import ServiceRequestReferenceQueryService
from soma.tickets.service_requests import ServiceRequestService
from soma.tickets.sr_references import ServiceRequestReferenceService


def _factory(initialized_database):
    database_path, factory_for_path = initialized_database
    return factory_for_path(database_path)


def _read(initialized_database):
    return _factory(initialized_database).open_authoritative(read_only=True, require_wal=True)


class FakeClassificationParticipant:
    def __init__(self) -> None:
        self.apply_calls: list[tuple[str, str | None, dict[str, object]]] = []
        self.fail = False
        self.indeterminate = False

    def preview_customer_change(self, reader, sr_id: str, new_customer_org_id: str | None):
        if self.indeterminate:
            return "INDETERMINATE"
        return {"impact": "none", "service_request_id": sr_id, "customer_org_id": new_customer_org_id}

    def apply_customer_change(self, uow, sr_id: str, new_customer_org_id: str | None, command_context):
        assert uow.connection.in_transaction
        if self.fail:
            raise RuntimeError("injected classification participant failure")
        if self.indeterminate:
            return "INDETERMINATE"
        self.apply_calls.append((sr_id, new_customer_org_id, dict(command_context)))
        return ()


def _seed_handler_observation(factory, service_request_id: str, accepted_command_id: str, label: str) -> str:
    observation_id = new_uuid4()
    now = utc_epoch_seconds()
    with UnitOfWork(factory) as uow:
        uow.connection.execute(
            "INSERT INTO sr_source_field_observations("
            "sr_source_field_observation_id,service_request_id,field_key,value_state,value_kind,text_value,"
            "source_chronology_utc,precedence_basis,source_observation_field_id,accepted_command_id,recorded_at_utc"
            ") VALUES (?, ?, 'current_handler_label', 'usable', 'text', ?, ?, 'source_chronology', ?, ?, ?)",
            (
                observation_id,
                service_request_id,
                label,
                now,
                f"handler-evidence-{observation_id}",
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
                "INSERT INTO sr_current_source_projection(service_request_id,current_handler_observation_id,revision) "
                "VALUES (?, ?, 1)",
                (service_request_id, observation_id),
            )
        else:
            uow.connection.execute(
                "UPDATE sr_current_source_projection SET current_handler_observation_id=?,revision=revision+1 "
                "WHERE service_request_id=?",
                (observation_id, service_request_id),
            )
    return observation_id


def test_customer_relationship_history_revision_no_change_clear_and_exact_replay(initialized_database) -> None:
    factory = _factory(initialized_database)
    customers = CustomerReferenceService(factory)
    customer_a = customers.create_customer_organization(command_id=new_uuid4(), name="Reference Customer A")
    customer_b = customers.create_customer_organization(command_id=new_uuid4(), name="Reference Customer B")
    sr = ServiceRequestService(factory).create_manual_service_request(command_id=new_uuid4())
    participant = FakeClassificationParticipant()
    service = ServiceRequestReferenceService(factory, participant)
    queries = ServiceRequestReferenceQueryService(factory, participant)

    preview = queries.preview_customer_change(
        service_request_id=sr.service_request_id,
        customer_org_id=customer_a.customer_org_id,
    )
    assert preview.eligible is True
    first_command = new_uuid4()
    first = service.set_customer(
        command_id=first_command,
        service_request_id=sr.service_request_id,
        base_revision=1,
        customer_org_id=customer_a.customer_org_id,
        reason_category="manual_customer_review",
        review_fingerprint=preview.review_fingerprint,
    )
    assert first.outcome == "APPLIED"
    assert first.target_id == sr.service_request_id
    assert first.revision == 2
    assert participant.apply_calls[-1][1] == customer_a.customer_org_id
    assert participant.apply_calls[-1][2]["resulting_revision"] == 2

    no_change = service.set_customer(
        command_id=new_uuid4(),
        service_request_id=sr.service_request_id,
        base_revision=2,
        customer_org_id=customer_a.customer_org_id,
        reason_category="manual_customer_review",
    )
    assert no_change.no_change is True
    assert no_change.target_id == sr.service_request_id
    assert no_change.revision == 2
    assert len(participant.apply_calls) == 1

    second = service.set_customer(
        command_id=new_uuid4(),
        service_request_id=sr.service_request_id,
        base_revision=2,
        customer_org_id=customer_b.customer_org_id,
        reason_category="customer_correction",
    )
    assert second.outcome == "APPLIED"
    assert second.target_id == sr.service_request_id
    assert second.revision == 3
    assert len(participant.apply_calls) == 2

    clear = service.set_customer(
        command_id=new_uuid4(),
        service_request_id=sr.service_request_id,
        base_revision=3,
        customer_org_id=None,
        reason_category="customer_cleared",
    )
    assert clear.outcome == "APPLIED"
    assert clear.target_id == sr.service_request_id
    assert clear.revision == 4
    assert len(participant.apply_calls) == 3
    assert participant.apply_calls[-1][1] is None

    replay = service.set_customer(
        command_id=first_command,
        service_request_id=sr.service_request_id,
        base_revision=1,
        customer_org_id=customer_a.customer_org_id,
        reason_category="manual_customer_review",
        review_fingerprint=preview.review_fingerprint,
    )
    assert replay.replayed is True
    assert replay.outcome == "APPLIED"
    assert replay.target_id == sr.service_request_id
    assert replay.revision == 2
    assert len(participant.apply_calls) == 3

    connection = _read(initialized_database)
    try:
        history = connection.execute(
            "SELECT customer_org_id,relationship_state,reason_category,closed_command_id "
            "FROM sr_customer_relationships WHERE service_request_id=? ORDER BY opened_at_utc,sr_customer_relationship_id",
            (sr.service_request_id,),
        ).fetchall()
        assert len(history) == 2
        assert {str(row[0]) for row in history} == {customer_a.customer_org_id, customer_b.customer_org_id}
        assert all(str(row[1]) == "superseded" for row in history)
        assert {str(row[2]) for row in history} == {"manual_customer_review", "customer_correction"}
        assert all(row[3] is not None for row in history)
        assert connection.execute(
            "SELECT COUNT(*) FROM sr_customer_relationships WHERE service_request_id=? AND relationship_state='active'",
            (sr.service_request_id,),
        ).fetchone()[0] == 0
        assert connection.execute(
            "SELECT revision FROM service_requests WHERE service_request_id=?",
            (sr.service_request_id,),
        ).fetchone()[0] == 4
        customer_revisions = connection.execute(
            "SELECT customer_org_id,revision FROM customer_organizations WHERE customer_org_id IN (?,?) ORDER BY customer_org_id",
            (customer_a.customer_org_id, customer_b.customer_org_id),
        ).fetchall()
        assert all(int(row[1]) == 1 for row in customer_revisions)
        audits = connection.execute(
            "SELECT payload_json FROM audit_events WHERE target_id=? AND action_type='ticket.service_request.customer_changed'",
            (sr.service_request_id,),
        ).fetchall()
        assert len(audits) == 3
        assert all("Reference Customer" not in str(row[0]) for row in audits)
        assert all(json.loads(str(row[0]))["resulting_revision"] in {2, 3, 4} for row in audits)
        stored = connection.execute(
            "SELECT response_schema,response_json FROM command_receipt_results WHERE command_id=?",
            (first_command,),
        ).fetchone()
        assert stored[0] == "TicketMutationResultV1"
        assert json.loads(str(stored[1])) == {
            "outcome": "APPLIED",
            "revision": 2,
            "target_id": sr.service_request_id,
        }
    finally:
        connection.close()


def test_customer_participant_failure_rolls_back_receipt_relationship_and_revision(initialized_database) -> None:
    factory = _factory(initialized_database)
    customer = CustomerReferenceService(factory).create_customer_organization(
        command_id=new_uuid4(), name="Rollback Customer"
    )
    sr = ServiceRequestService(factory).create_manual_service_request(command_id=new_uuid4())
    participant = FakeClassificationParticipant()
    participant.fail = True
    service = ServiceRequestReferenceService(factory, participant)
    failed_command = new_uuid4()

    with pytest.raises(SomaError) as excinfo:
        service.set_customer(
            command_id=failed_command,
            service_request_id=sr.service_request_id,
            base_revision=1,
            customer_org_id=customer.customer_org_id,
            reason_category="classification_failure_test",
        )
    assert excinfo.value.code == "SR_CUSTOMER_CLASSIFICATION_PARTICIPANT_FAILED"

    connection = _read(initialized_database)
    try:
        assert connection.execute(
            "SELECT revision FROM service_requests WHERE service_request_id=?", (sr.service_request_id,)
        ).fetchone()[0] == 1
        assert connection.execute(
            "SELECT COUNT(*) FROM sr_customer_relationships WHERE service_request_id=?", (sr.service_request_id,)
        ).fetchone()[0] == 0
        assert connection.execute(
            "SELECT 1 FROM command_receipts WHERE command_id=?", (failed_command,)
        ).fetchone() is None
        assert connection.execute(
            "SELECT 1 FROM audit_events WHERE command_id=?", (failed_command,)
        ).fetchone() is None
    finally:
        connection.close()


def test_contact_affiliation_mismatch_requires_fresh_review_preserves_affiliation_and_replays_exactly(initialized_database) -> None:
    factory = _factory(initialized_database)
    customers = CustomerReferenceService(factory)
    customer_a = customers.create_customer_organization(command_id=new_uuid4(), name="Customer Context A")
    customer_b = customers.create_customer_organization(command_id=new_uuid4(), name="Customer Context B")
    contact = ContactReferenceService(factory).create_contact(
        command_id=new_uuid4(),
        name="Reviewed Contact",
        initial_customer_org_id=customer_b.customer_org_id,
    )
    sr = ServiceRequestService(factory).create_manual_service_request(command_id=new_uuid4())
    participant = FakeClassificationParticipant()
    service = ServiceRequestReferenceService(factory, participant)
    queries = ServiceRequestReferenceQueryService(factory, participant)
    service.set_customer(
        command_id=new_uuid4(),
        service_request_id=sr.service_request_id,
        base_revision=1,
        customer_org_id=customer_a.customer_org_id,
        reason_category="customer_context",
    )

    preview = queries.preview_contact_reference(
        service_request_id=sr.service_request_id,
        reference_role="customer_contact",
        contact_id=contact.contact_id,
    )
    assert preview.eligible is False
    assert "SR_CONTACT_AFFILIATION_REVIEW_REQUIRED" in preview.warnings

    failed_command = new_uuid4()
    with pytest.raises(SomaError) as excinfo:
        service.set_contact_reference(
            command_id=failed_command,
            service_request_id=sr.service_request_id,
            base_revision=2,
            reference_role="customer_contact",
            contact_id=contact.contact_id,
            supporting_sr_source_field_observation_id=None,
            reason_category="contact_review",
        )
    assert excinfo.value.code == "SR_CONTACT_AFFILIATION_REVIEW_REQUIRED"

    accepted_command = new_uuid4()
    accepted = service.set_contact_reference(
        command_id=accepted_command,
        service_request_id=sr.service_request_id,
        base_revision=2,
        reference_role="customer_contact",
        contact_id=contact.contact_id,
        supporting_sr_source_field_observation_id=None,
        reason_category="contact_review",
        review_fingerprint=preview.review_fingerprint,
    )
    assert accepted.outcome == "APPLIED"
    assert accepted.target_id == sr.service_request_id
    assert accepted.revision == 3

    no_change = service.set_contact_reference(
        command_id=new_uuid4(),
        service_request_id=sr.service_request_id,
        base_revision=3,
        reference_role="customer_contact",
        contact_id=contact.contact_id,
        supporting_sr_source_field_observation_id=None,
        reason_category="contact_review",
    )
    assert no_change.no_change is True
    assert no_change.target_id == sr.service_request_id
    assert no_change.revision == 3

    service.set_customer(
        command_id=new_uuid4(),
        service_request_id=sr.service_request_id,
        base_revision=3,
        customer_org_id=customer_b.customer_org_id,
        reason_category="customer_context_changed",
    )
    refreshed_preview = queries.preview_contact_reference(
        service_request_id=sr.service_request_id,
        reference_role="customer_contact",
        contact_id=contact.contact_id,
    )
    assert refreshed_preview.eligible is True
    refreshed = service.set_contact_reference(
        command_id=new_uuid4(),
        service_request_id=sr.service_request_id,
        base_revision=4,
        reference_role="customer_contact",
        contact_id=contact.contact_id,
        supporting_sr_source_field_observation_id=None,
        reason_category="refresh_organization_at_use",
        review_fingerprint=refreshed_preview.review_fingerprint,
    )
    assert refreshed.no_change is False
    assert refreshed.target_id == sr.service_request_id
    assert refreshed.revision == 5

    replay = service.set_contact_reference(
        command_id=accepted_command,
        service_request_id=sr.service_request_id,
        base_revision=2,
        reference_role="customer_contact",
        contact_id=contact.contact_id,
        supporting_sr_source_field_observation_id=None,
        reason_category="contact_review",
        review_fingerprint=preview.review_fingerprint,
    )
    assert replay.replayed is True
    assert replay.outcome == "APPLIED"
    assert replay.target_id == sr.service_request_id
    assert replay.revision == 3

    connection = _read(initialized_database)
    try:
        affiliation = connection.execute(
            "SELECT customer_org_id,is_current FROM contact_affiliations WHERE contact_id=? AND is_current=1",
            (contact.contact_id,),
        ).fetchone()
        assert str(affiliation[0]) == customer_b.customer_org_id
        assert int(affiliation[1]) == 1
        assert connection.execute(
            "SELECT revision FROM contacts WHERE contact_id=?", (contact.contact_id,)
        ).fetchone()[0] == 1
        history = connection.execute(
            "SELECT customer_org_context_id,relationship_state FROM sr_contact_relationships "
            "WHERE service_request_id=? AND reference_role='customer_contact' ORDER BY opened_at_utc,sr_contact_relationship_id",
            (sr.service_request_id,),
        ).fetchall()
        assert len(history) == 2
        assert {str(row[0]) for row in history} == {customer_a.customer_org_id, customer_b.customer_org_id}
        assert sorted(str(row[1]) for row in history) == ["active", "superseded"]
        assert connection.execute(
            "SELECT 1 FROM command_receipts WHERE command_id=?", (failed_command,)
        ).fetchone() is None
    finally:
        connection.close()


def test_current_handler_reference_binds_exact_current_source_observation(initialized_database) -> None:
    factory = _factory(initialized_database)
    create_sr_command = new_uuid4()
    sr = ServiceRequestService(factory).create_manual_service_request(command_id=create_sr_command)
    contact = ContactReferenceService(factory).create_contact(
        command_id=new_uuid4(), name="Handler Contact"
    )
    participant = FakeClassificationParticipant()
    service = ServiceRequestReferenceService(factory, participant)
    queries = ServiceRequestReferenceQueryService(factory, participant)

    handler_h1 = _seed_handler_observation(factory, sr.service_request_id, create_sr_command, "handler-one")
    preview_h1 = queries.preview_contact_reference(
        service_request_id=sr.service_request_id,
        reference_role="current_handler_reference",
        contact_id=contact.contact_id,
        supporting_sr_source_field_observation_id=handler_h1,
    )
    assert preview_h1.eligible is True
    applied = service.set_contact_reference(
        command_id=new_uuid4(),
        service_request_id=sr.service_request_id,
        base_revision=1,
        reference_role="current_handler_reference",
        contact_id=contact.contact_id,
        supporting_sr_source_field_observation_id=handler_h1,
        reason_category="handler_identity_review",
        review_fingerprint=preview_h1.review_fingerprint,
    )
    assert applied.outcome == "APPLIED"
    assert applied.target_id == sr.service_request_id
    assert applied.revision == 2

    handler_h2 = _seed_handler_observation(factory, sr.service_request_id, create_sr_command, "handler-two")
    context = queries.get(service_request_id=sr.service_request_id)
    handler_context = context["contacts"]["current_handler_reference"]
    assert handler_context["supporting_sr_source_field_observation_id"] == handler_h1
    assert handler_context["alignment"] == "stale"
    assert "SR_HANDLER_REFERENCE_STALE" in context["warnings"]

    stale_command = new_uuid4()
    with pytest.raises(SomaError) as excinfo:
        service.set_contact_reference(
            command_id=stale_command,
            service_request_id=sr.service_request_id,
            base_revision=2,
            reference_role="current_handler_reference",
            contact_id=contact.contact_id,
            supporting_sr_source_field_observation_id=handler_h1,
            reason_category="handler_identity_review",
        )
    assert excinfo.value.code == "SR_HANDLER_REFERENCE_STALE"

    preview_h2 = queries.preview_contact_reference(
        service_request_id=sr.service_request_id,
        reference_role="current_handler_reference",
        contact_id=contact.contact_id,
        supporting_sr_source_field_observation_id=handler_h2,
    )
    refreshed = service.set_contact_reference(
        command_id=new_uuid4(),
        service_request_id=sr.service_request_id,
        base_revision=2,
        reference_role="current_handler_reference",
        contact_id=contact.contact_id,
        supporting_sr_source_field_observation_id=handler_h2,
        reason_category="handler_identity_refresh",
        review_fingerprint=preview_h2.review_fingerprint,
    )
    assert refreshed.outcome == "APPLIED"
    assert refreshed.target_id == sr.service_request_id
    assert refreshed.revision == 3

    connection = _read(initialized_database)
    try:
        rows = connection.execute(
            "SELECT supporting_sr_source_field_observation_id,relationship_state FROM sr_contact_relationships "
            "WHERE service_request_id=? AND reference_role='current_handler_reference' ORDER BY opened_at_utc,sr_contact_relationship_id",
            (sr.service_request_id,),
        ).fetchall()
        assert len(rows) == 2
        assert {str(row[0]) for row in rows} == {handler_h1, handler_h2}
        assert sorted(str(row[1]) for row in rows) == ["active", "superseded"]
        assert connection.execute(
            "SELECT 1 FROM command_receipts WHERE command_id=?", (stale_command,)
        ).fetchone() is None
    finally:
        connection.close()
