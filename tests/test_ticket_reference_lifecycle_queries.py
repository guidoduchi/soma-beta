from __future__ import annotations

from soma.foundation.identifiers import new_uuid4, utc_epoch_seconds
from soma.foundation.persistence.uow import UnitOfWork
from soma.reference.application.customer_service import CustomerReferenceService
from soma.tickets.queries.rfc_lifecycle import RfcLifecycleQueryService
from soma.tickets.queries.service_requests import ServiceRequestQueryService
from soma.tickets.queries.sr_references import ServiceRequestReferenceQueryService
from soma.tickets.rfcs import RfcService
from soma.tickets.service_requests import ServiceRequestService


def _factory(initialized_database):
    database_path, factory_for_path = initialized_database
    return factory_for_path(database_path)


def _counts(factory) -> tuple[int, int]:
    connection = factory.open_authoritative(read_only=True, require_wal=True)
    try:
        return (
            int(connection.execute("SELECT COUNT(*) FROM command_receipts").fetchone()[0]),
            int(connection.execute("SELECT COUNT(*) FROM audit_events").fetchone()[0]),
        )
    finally:
        connection.close()


def test_service_request_reference_context_is_shared_read_only_projection(initialized_database) -> None:
    factory = _factory(initialized_database)
    create_command = new_uuid4()
    sr = ServiceRequestService(factory).create_manual_service_request(command_id=create_command)
    observation_id = new_uuid4()
    now = utc_epoch_seconds()
    with UnitOfWork(factory) as uow:
        uow.connection.execute(
            "INSERT INTO sr_source_field_observations("
            "sr_source_field_observation_id,service_request_id,field_key,value_state,value_kind,text_value,"
            "source_chronology_utc,precedence_basis,source_observation_field_id,accepted_command_id,recorded_at_utc"
            ") VALUES (?, ?, 'customer_account_code', 'usable', 'text', ?, ?, 'source_chronology', ?, ?, ?)",
            (
                observation_id,
                sr.service_request_id,
                "ACCT-UNRESOLVED",
                now,
                f"test-account-code-{observation_id}",
                create_command,
                now,
            ),
        )
        uow.connection.execute(
            "INSERT INTO sr_current_source_projection(service_request_id,customer_account_code_observation_id,revision) "
            "VALUES (?, ?, 1)",
            (sr.service_request_id, observation_id),
        )

    before = _counts(factory)
    standalone = ServiceRequestReferenceQueryService(factory).get(service_request_id=sr.service_request_id)
    detail = ServiceRequestQueryService(factory).get(service_request_id=sr.service_request_id)
    after = _counts(factory)

    assert before == after
    assert standalone == detail.reference_context
    assert standalone["warnings"] == ("SR_CUSTOMER_UNRESOLVED",)
    assert detail.warnings == standalone["warnings"]
    assert standalone["customer"] is None
    assert standalone["contacts"] == {
        "customer_contact": None,
        "current_handler_reference": None,
    }
    assert len(standalone["review_fingerprint"]) == 64


def test_rfc_lifecycle_projection_is_closed_and_read_only(initialized_database) -> None:
    factory = _factory(initialized_database)
    rfc = RfcService(factory).create_or_adopt_identity(
        command_id=new_uuid4(),
        rfc_no="NC20260804003001",
        creation_context="manual",
    )
    queries = RfcLifecycleQueryService(factory)

    before = _counts(factory)
    projection = queries.get(rfc_id=rfc.rfc_id)
    after = _counts(factory)

    assert before == after
    assert projection.rfc_id == rfc.rfc_id
    assert projection.local_archive_state == "active"
    assert projection.terminal_epoch_id is None
    assert projection.accepted_source_state["status_class"] == "unknown"
    assert projection.accepted_source_state["status_text"] is None
    assert projection.accepted_source_state["status_evidence_id"] is None
    assert projection.accepted_source_state["revision"] is None
    assert projection.warnings == ("RFC_CUSTOMER_UNRESOLVED",)


def test_rfc_lifecycle_projection_returns_exact_terminal_evidence(initialized_database) -> None:
    factory = _factory(initialized_database)
    customer = CustomerReferenceService(factory).create_customer_organization(
        command_id=new_uuid4(),
        name="Lifecycle Query Customer",
    )
    rfc = RfcService(factory).create_or_adopt_identity(
        command_id=new_uuid4(),
        rfc_no="NC20260804003002",
        creation_context="manual",
        customer_org_id=customer.customer_org_id,
    )
    with UnitOfWork(factory) as uow:
        uow.connection.execute(
            "INSERT INTO rfc_current_source_projection("
            "rfc_id,summary_text,summary_evidence_id,status_text,status_class,status_authority,status_evidence_id,terminal_epoch_id,revision"
            ") VALUES (?, ?, ?, ?, 'terminal_closed', 'enhanced_rfc', ?, ?, 1)",
            (
                rfc.rfc_id,
                "Terminal maintenance RFC",
                "rfc-summary-evidence-1",
                "Closed",
                "rfc-status-evidence-1",
                "terminal-epoch-1",
            ),
        )

    before = _counts(factory)
    projection = RfcLifecycleQueryService(factory).get(rfc_id=rfc.rfc_id)
    after = _counts(factory)

    assert before == after
    assert projection.local_archive_state == "active"
    assert projection.terminal_epoch_id == "terminal-epoch-1"
    assert projection.accepted_source_state["summary_text"] == "Terminal maintenance RFC"
    assert projection.accepted_source_state["summary_evidence_id"] == "rfc-summary-evidence-1"
    assert projection.accepted_source_state["status_text"] == "Closed"
    assert projection.accepted_source_state["status_class"] == "terminal_closed"
    assert projection.accepted_source_state["status_authority"] == "enhanced_rfc"
    assert projection.accepted_source_state["status_evidence_id"] == "rfc-status-evidence-1"
    assert projection.accepted_source_state["revision"] == 1
    assert projection.warnings == ()
