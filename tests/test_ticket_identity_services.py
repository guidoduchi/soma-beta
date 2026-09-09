from __future__ import annotations

import json

import pytest

from soma.foundation.errors import SomaError
from soma.foundation.identifiers import new_uuid4
from soma.reference.application.customer_service import CustomerReferenceService
from soma.tickets.device_references import DeviceReferenceService
from soma.tickets.queries.rfcs import RfcQueryService
from soma.tickets.queries.service_requests import ServiceRequestQueryService
from soma.tickets.rfcs import RfcService
from soma.tickets.service_requests import ServiceRequestService


def _factory(initialized_database):
    database_path, factory_for_path = initialized_database
    return factory_for_path(database_path)


def _read(initialized_database):
    return _factory(initialized_database).open_authoritative(read_only=True, require_wal=True)


def _write(initialized_database):
    return _factory(initialized_database).open_authoritative(read_only=False, require_wal=True)


def _receipt(connection) -> str:
    command_id = new_uuid4()
    connection.execute(
        "INSERT INTO command_receipts("
        "command_id,command_type,request_hash,target_type,target_id,committed_at_utc,result_type,result_id"
        ") VALUES (?, 'TestHierarchy', ?, 'rfc', NULL, 1, NULL, NULL)",
        (command_id, "0" * 64),
    )
    return command_id


def test_manual_sr_allocation_replay_conflict_and_exhaustion(initialized_database) -> None:
    service = ServiceRequestService(_factory(initialized_database))
    command_id = new_uuid4()
    first = service.create_manual_service_request(command_id=command_id)
    assert first.local_sr_no == "LSR-00000001"
    assert first.official_sr_no is None
    assert first.revision == 1
    assert first.replayed is False

    replay = service.create_manual_service_request(command_id=command_id)
    assert replay.service_request_id == first.service_request_id
    assert replay.local_sr_no == first.local_sr_no
    assert replay.replayed is True

    second = service.create_manual_service_request(command_id=new_uuid4())
    assert second.local_sr_no == "LSR-00000002"

    official = service.create_manual_service_request(
        command_id=new_uuid4(), official_sr_no="12345678"
    )
    assert official.official_sr_no == "12345678"
    assert official.local_sr_no is None

    with pytest.raises(SomaError) as conflict:
        service.create_manual_service_request(
            command_id=new_uuid4(), official_sr_no="12345678"
        )
    assert conflict.value.code == "SR_OFFICIAL_ID_CONFLICT"

    connection = _write(initialized_database)
    try:
        connection.execute("BEGIN IMMEDIATE")
        before_receipts = connection.execute("SELECT count(*) FROM command_receipts").fetchone()[0]
        before_audits = connection.execute("SELECT count(*) FROM audit_events").fetchone()[0]
        connection.execute(
            "UPDATE sr_local_id_allocator SET next_value=100000000 WHERE singleton_guard=1"
        )
        connection.execute("COMMIT")
    finally:
        connection.close()

    with pytest.raises(SomaError) as exhausted:
        service.create_manual_service_request(command_id=new_uuid4())
    assert exhausted.value.code == "SR_LOCAL_ID_EXHAUSTED"

    connection = _read(initialized_database)
    try:
        assert connection.execute("SELECT count(*) FROM command_receipts").fetchone()[0] == before_receipts
        assert connection.execute("SELECT count(*) FROM audit_events").fetchone()[0] == before_audits
        assert connection.execute(
            "SELECT next_value FROM sr_local_id_allocator WHERE singleton_guard=1"
        ).fetchone()[0] == 100000000
        assert connection.execute(
            "SELECT count(*) FROM audit_events WHERE action_type='ticket.service_request.created'"
        ).fetchone()[0] == 3
    finally:
        connection.close()


def test_reviewed_official_sr_adoption_preserves_local_identity_and_history(initialized_database) -> None:
    factory = _factory(initialized_database)
    service = ServiceRequestService(factory)
    queries = ServiceRequestQueryService(factory)
    local = service.create_manual_service_request(command_id=new_uuid4())
    adopted = service.attach_official_identity(
        command_id=new_uuid4(),
        service_request_id=local.service_request_id,
        base_revision=1,
        official_sr_no="87654321",
        review_context_id="review-sr-identity-1",
    )
    assert adopted.target_id == local.service_request_id
    assert adopted.outcome == "APPLIED"
    assert adopted.revision == 2
    detail = queries.get(service_request_id=local.service_request_id)
    assert detail.identity["local_sr_no"] == local.local_sr_no
    assert detail.identity["official_sr_no"] == "87654321"

    no_change = service.attach_official_identity(
        command_id=new_uuid4(),
        service_request_id=local.service_request_id,
        base_revision=2,
        official_sr_no="87654321",
        review_context_id="review-sr-identity-2",
    )
    assert no_change.no_change is True
    assert no_change.revision == 2

    other = service.create_manual_service_request(command_id=new_uuid4())
    with pytest.raises(SomaError) as conflict:
        service.attach_official_identity(
            command_id=new_uuid4(),
            service_request_id=other.service_request_id,
            base_revision=1,
            official_sr_no="87654321",
            review_context_id="review-sr-identity-conflict",
        )
    assert conflict.value.code == "SR_OFFICIAL_ID_CONFLICT"

    connection = _read(initialized_database)
    try:
        payload = connection.execute(
            "SELECT payload_json FROM audit_events "
            "WHERE action_type='ticket.service_request.official_identity_attached'"
        ).fetchone()[0]
        parsed = json.loads(payload)
        assert "87654321" not in payload
        assert len(parsed["official_sr_no_fingerprint"]) == 64
        assert connection.execute(
            "SELECT count(*) FROM audit_events "
            "WHERE action_type='ticket.service_request.official_identity_attached'"
        ).fetchone()[0] == 1
    finally:
        connection.close()


def test_service_request_replay_is_independent_of_later_owner_state(initialized_database) -> None:
    factory = _factory(initialized_database)
    service = ServiceRequestService(factory)
    queries = ServiceRequestQueryService(factory)

    create_command_id = new_uuid4()
    created = service.create_manual_service_request(command_id=create_command_id)
    attach_command_id = new_uuid4()
    applied = service.attach_official_identity(
        command_id=attach_command_id,
        service_request_id=created.service_request_id,
        base_revision=1,
        official_sr_no="11223344",
        review_context_id="review-replay-independence",
    )
    assert applied.revision == 2

    create_replay = service.create_manual_service_request(command_id=create_command_id)
    assert create_replay.replayed is True
    assert create_replay.revision == 1
    assert create_replay.official_sr_no is None
    assert create_replay.local_sr_no == created.local_sr_no

    connection = _write(initialized_database)
    try:
        connection.execute("BEGIN IMMEDIATE")
        connection.execute(
            "UPDATE service_requests SET revision=9 WHERE service_request_id=?",
            (created.service_request_id,),
        )
        connection.execute("COMMIT")
    finally:
        connection.close()

    attach_replay = service.attach_official_identity(
        command_id=attach_command_id,
        service_request_id=created.service_request_id,
        base_revision=1,
        official_sr_no="11223344",
        review_context_id="review-replay-independence",
    )
    assert attach_replay.replayed is True
    assert attach_replay.outcome == "APPLIED"
    assert attach_replay.revision == 2
    assert queries.get(service_request_id=created.service_request_id).revision == 9


def test_rfc_exact_identity_adoption_and_customer_branch_consistency(initialized_database) -> None:
    factory = _factory(initialized_database)
    customers = CustomerReferenceService(factory)
    customer_a = customers.create_customer_organization(command_id=new_uuid4(), name="Customer A")
    customer_b = customers.create_customer_organization(command_id=new_uuid4(), name="Customer B")
    service = RfcService(factory)
    queries = RfcQueryService(factory)

    root = service.create_or_adopt_identity(
        command_id=new_uuid4(),
        rfc_no="NC20260804000241",
        creation_context="manual",
        customer_org_id=customer_a.customer_org_id,
    )
    adopted = service.create_or_adopt_identity(
        command_id=new_uuid4(),
        rfc_no="NC20260804000241",
        creation_context="accepted_source_adoption",
        customer_org_id=customer_b.customer_org_id,
    )
    assert adopted.rfc_id == root.rfc_id
    assert adopted.no_change is True
    assert adopted.customer_org_id == customer_a.customer_org_id

    child = service.create_or_adopt_identity(
        command_id=new_uuid4(),
        rfc_no="NC20260804000242",
        creation_context="manual",
        customer_org_id=customer_a.customer_org_id,
    )
    standalone = service.create_or_adopt_identity(
        command_id=new_uuid4(),
        rfc_no="NC20260804000243",
        creation_context="manual",
    )

    connection = _write(initialized_database)
    try:
        connection.execute("BEGIN IMMEDIATE")
        hierarchy_command = _receipt(connection)
        connection.execute(
            "INSERT INTO rfc_hierarchy_edges("
            "rfc_hierarchy_edge_id,parent_rfc_id,child_rfc_id,edge_state,opened_at_utc,opened_command_id"
            ") VALUES (?, ?, ?, 'active', 1, ?)",
            (new_uuid4(), root.rfc_id, child.rfc_id, hierarchy_command),
        )
        connection.execute("COMMIT")
    finally:
        connection.close()

    with pytest.raises(SomaError) as mismatch:
        service.set_customer(
            command_id=new_uuid4(),
            rfc_id=child.rfc_id,
            base_revision=1,
            customer_org_id=customer_b.customer_org_id,
            reason_category="customer_correction",
            review_fingerprint="a" * 64,
        )
    assert mismatch.value.code == "RFC_CUSTOMER_MISMATCH"

    changed = service.set_customer(
        command_id=new_uuid4(),
        rfc_id=standalone.rfc_id,
        base_revision=1,
        customer_org_id=customer_a.customer_org_id,
        reason_category="customer_assignment",
    )
    assert changed.target_id == standalone.rfc_id
    assert changed.outcome == "APPLIED"
    assert changed.revision == 2
    assert queries.get(rfc_id=standalone.rfc_id).customer_org_id == customer_a.customer_org_id

    same = service.set_customer(
        command_id=new_uuid4(),
        rfc_id=standalone.rfc_id,
        base_revision=2,
        customer_org_id=customer_a.customer_org_id,
        reason_category="customer_assignment",
    )
    assert same.no_change is True
    assert same.revision == 2

    connection = _read(initialized_database)
    try:
        assert connection.execute(
            "SELECT count(*) FROM rfcs WHERE rfc_no='NC20260804000241'"
        ).fetchone()[0] == 1
        assert connection.execute(
            "SELECT count(*) FROM audit_events WHERE action_type='ticket.rfc.identity_created_or_adopted'"
        ).fetchone()[0] == 3
    finally:
        connection.close()


def test_rfc_replay_is_independent_of_later_owner_state(initialized_database) -> None:
    factory = _factory(initialized_database)
    customers = CustomerReferenceService(factory)
    customer = customers.create_customer_organization(command_id=new_uuid4(), name="Replay Customer")
    service = RfcService(factory)
    queries = RfcQueryService(factory)

    create_command_id = new_uuid4()
    created = service.create_or_adopt_identity(
        command_id=create_command_id,
        rfc_no="NC20260908000001",
        creation_context="manual",
    )
    set_customer_command_id = new_uuid4()
    changed = service.set_customer(
        command_id=set_customer_command_id,
        rfc_id=created.rfc_id,
        base_revision=1,
        customer_org_id=customer.customer_org_id,
        reason_category="customer_assignment",
    )
    assert changed.revision == 2

    create_replay = service.create_or_adopt_identity(
        command_id=create_command_id,
        rfc_no="NC20260908000001",
        creation_context="manual",
    )
    assert create_replay.replayed is True
    assert create_replay.revision == 1
    assert create_replay.customer_org_id is None

    connection = _write(initialized_database)
    try:
        connection.execute("BEGIN IMMEDIATE")
        connection.execute("UPDATE rfcs SET revision=8 WHERE rfc_id=?", (created.rfc_id,))
        connection.execute("COMMIT")
    finally:
        connection.close()

    customer_replay = service.set_customer(
        command_id=set_customer_command_id,
        rfc_id=created.rfc_id,
        base_revision=1,
        customer_org_id=customer.customer_org_id,
        reason_category="customer_assignment",
    )
    assert customer_replay.replayed is True
    assert customer_replay.outcome == "APPLIED"
    assert customer_replay.revision == 2
    assert queries.get(rfc_id=created.rfc_id).revision == 8


def test_device_reference_equal_names_stale_correction_and_audit_privacy(initialized_database) -> None:
    service = DeviceReferenceService(_factory(initialized_database))
    first = service.create(command_id=new_uuid4(), operational_name="host-a")
    second = service.create(command_id=new_uuid4(), operational_name="host-a")
    assert first.device_reference_id != second.device_reference_id

    corrected = service.correct_name(
        command_id=new_uuid4(),
        device_reference_id=first.device_reference_id,
        base_revision=1,
        operational_name="host-a-corrected",
        reason_category="operator_correction",
    )
    assert corrected.device_reference_id == first.device_reference_id
    assert corrected.operational_name == "host-a-corrected"
    assert corrected.revision == 2

    no_change = service.correct_name(
        command_id=new_uuid4(),
        device_reference_id=first.device_reference_id,
        base_revision=2,
        operational_name="host-a-corrected",
        reason_category="operator_correction",
    )
    assert no_change.no_change is True
    assert no_change.revision == 2

    with pytest.raises(SomaError) as stale:
        service.correct_name(
            command_id=new_uuid4(),
            device_reference_id=first.device_reference_id,
            base_revision=1,
            operational_name="stale-write",
            reason_category="operator_correction",
        )
    assert stale.value.code == "STALE_REVISION"

    with pytest.raises(SomaError) as invalid:
        service.create(command_id=new_uuid4(), operational_name="bad\nname")
    assert invalid.value.code == "DEVICE_REFERENCE_INVALID"

    connection = _read(initialized_database)
    try:
        rows = connection.execute(
            "SELECT payload_json FROM audit_events WHERE action_type IN "
            "('ticket.device_reference.created','ticket.device_reference.corrected')"
        ).fetchall()
        assert len(rows) == 3
        assert all("host-a" not in str(row[0]) for row in rows)
        assert connection.execute(
            "SELECT count(*) FROM device_references WHERE device_reference_id IN (?, ?) ",
            (first.device_reference_id, second.device_reference_id),
        ).fetchone()[0] == 2
    finally:
        connection.close()
