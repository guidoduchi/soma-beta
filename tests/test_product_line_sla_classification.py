from __future__ import annotations

import pytest

from soma.foundation.errors import SomaError
from soma.foundation.identifiers import new_uuid4
from soma.product_line_sla.services.catalog import ProductLineSlaCatalogService
from soma.product_line_sla.services.classification import (
    ProductLineSlaClassificationService,
    ServiceRequestCustomerClassificationParticipant,
)
from soma.reference.application.customer_service import CustomerReferenceService
from soma.tickets.service_requests import ServiceRequestService
from soma.tickets.sr_references import ServiceRequestReferenceService


def _factory(initialized_database):
    database_path, factory_builder = initialized_database
    return factory_builder(database_path)


def _customer(factory, name: str):
    return CustomerReferenceService(factory).create_customer_organization(
        command_id=new_uuid4(),
        name=name,
    )


def _cpl(factory, *, customer_org_id: str, suffix: str):
    catalog = ProductLineSlaCatalogService(factory)
    product = catalog.create_product_line(
        command_id=new_uuid4(),
        name=f"Product {suffix}",
    )
    contract = catalog.create_contract(
        command_id=new_uuid4(),
        customer_org_id=customer_org_id,
        name=f"Contract {suffix}",
        contract_reference=f"REF-{suffix}",
    )
    return catalog.create_contract_product_line(
        command_id=new_uuid4(),
        contract_id=contract.target_id,
        product_line_id=product.target_id,
        initial_policy_name=f"Policy {suffix}",
        initial_template_source="IT_DEFAULT_V1",
    )


def test_manual_classification_replay_no_change_and_customer_change_invalidation(
    initialized_database,
) -> None:
    factory = _factory(initialized_database)
    customer_a = _customer(factory, "Customer A")
    customer_b = _customer(factory, "Customer B")
    cpl_a = _cpl(factory, customer_org_id=customer_a.customer_org_id, suffix="A")

    classification = ProductLineSlaClassificationService(factory)
    references = ServiceRequestReferenceService(factory, classification)
    sr = ServiceRequestService(factory).create_manual_service_request(
        command_id=new_uuid4(),
        official_sr_no="86111111",
    )
    set_a = references.set_customer(
        command_id=new_uuid4(),
        service_request_id=sr.service_request_id,
        base_revision=1,
        customer_org_id=customer_a.customer_org_id,
        reason_category="initial_customer_review",
    )
    assert set_a.revision == 2

    preview = classification.preview_manual(
        service_request_id=sr.service_request_id,
        contract_product_line_id=cpl_a.target_id,
    )
    assert preview.state == "eligible"
    assert preview.customer_org_id == customer_a.customer_org_id
    assert preview.current_revision == 0

    command_id = new_uuid4()
    applied = classification.classify_service_request(
        command_id=command_id,
        service_request_id=sr.service_request_id,
        target_contract_product_line_id=cpl_a.target_id,
        preview_fingerprint=preview.input_fingerprint,
        origin="manual_review",
        reason_category="reviewed_contract_match",
    )
    replay = classification.classify_service_request(
        command_id=command_id,
        service_request_id=sr.service_request_id,
        target_contract_product_line_id=cpl_a.target_id,
        preview_fingerprint=preview.input_fingerprint,
        origin="manual_review",
        reason_category="reviewed_contract_match",
    )
    assert replay.replayed is True
    assert replay.classification_event_id == applied.classification_event_id
    assert applied.revision == 1

    unchanged_preview = classification.preview_manual(
        service_request_id=sr.service_request_id,
        contract_product_line_id=cpl_a.target_id,
    )
    assert unchanged_preview.state == "unchanged"
    unchanged = classification.classify_service_request(
        command_id=new_uuid4(),
        service_request_id=sr.service_request_id,
        target_contract_product_line_id=cpl_a.target_id,
        preview_fingerprint=unchanged_preview.input_fingerprint,
        origin="manual_review",
        reason_category="confirm_existing_classification",
    )
    assert unchanged.outcome == "NO_CHANGE"
    assert unchanged.classification_event_id == applied.classification_event_id
    assert unchanged.revision == 1

    participant_results: list[object] = []
    original_apply = classification.apply_customer_change

    def capture_apply(uow, sr_id, new_customer_org_id, command_context):
        result = original_apply(uow, sr_id, new_customer_org_id, command_context)
        participant_results.append(result)
        return result

    classification.apply_customer_change = capture_apply
    customer_change_command = new_uuid4()
    set_b = references.set_customer(
        command_id=customer_change_command,
        service_request_id=sr.service_request_id,
        base_revision=2,
        customer_org_id=customer_b.customer_org_id,
        reason_category="customer_correction",
    )
    assert set_b.revision == 3
    assert len(participant_results) == 1
    assert isinstance(participant_results[0], tuple)
    assert participant_results[0][0][0] == "sr_classification_event"
    assert ServiceRequestCustomerClassificationParticipant is ProductLineSlaClassificationService

    connection = factory.open_authoritative(read_only=True, require_wal=True)
    try:
        assert connection.execute(
            "SELECT COUNT(*) FROM sr_classification_current WHERE service_request_id=?",
            (sr.service_request_id,),
        ).fetchone()[0] == 0
        events = connection.execute(
            "SELECT event_kind,prior_contract_product_line_id,new_contract_product_line_id,origin "
            "FROM sr_classification_events WHERE service_request_id=?",
            (sr.service_request_id,),
        ).fetchall()
        assert {tuple(row) for row in events} == {
            ("assign", None, cpl_a.target_id, "manual_review"),
            ("invalidate_customer", cpl_a.target_id, None, "customer_correction"),
        }
        audit_actions = connection.execute(
            "SELECT action_type FROM audit_events WHERE command_id=? ORDER BY action_type",
            (customer_change_command,),
        ).fetchall()
        assert [str(row[0]) for row in audit_actions] == [
            "sla.service_request.classification_changed",
            "ticket.service_request.customer_changed",
        ]
    finally:
        connection.close()


def test_cross_customer_preview_rejects_and_mapping_creation_revalidates_customer(
    initialized_database,
) -> None:
    factory = _factory(initialized_database)
    customer_a = _customer(factory, "Customer A2")
    customer_b = _customer(factory, "Customer B2")
    cpl_a = _cpl(factory, customer_org_id=customer_a.customer_org_id, suffix="A2")
    cpl_b = _cpl(factory, customer_org_id=customer_b.customer_org_id, suffix="B2")

    classification = ProductLineSlaClassificationService(factory)
    references = ServiceRequestReferenceService(factory, classification)
    sr = ServiceRequestService(factory).create_manual_service_request(
        command_id=new_uuid4(),
        official_sr_no="86222222",
    )
    references.set_customer(
        command_id=new_uuid4(),
        service_request_id=sr.service_request_id,
        base_revision=1,
        customer_org_id=customer_a.customer_org_id,
        reason_category="initial_customer_review",
    )

    preview = classification.preview_manual(
        service_request_id=sr.service_request_id,
        contract_product_line_id=cpl_b.target_id,
    )
    assert preview.state == "cross_customer"
    with pytest.raises(SomaError) as excinfo:
        classification.classify_service_request(
            command_id=new_uuid4(),
            service_request_id=sr.service_request_id,
            target_contract_product_line_id=cpl_b.target_id,
            preview_fingerprint=preview.input_fingerprint,
            origin="manual_review",
            reason_category="bad_cross_customer_attempt",
        )
    assert excinfo.value.code == "SLA_CLASSIFICATION_CROSS_CUSTOMER"

    mapping = classification.create_mapping(
        command_id=new_uuid4(),
        customer_org_id=customer_a.customer_org_id,
        customer_account_code="ACCT-A2",
        contract_product_line_id=cpl_a.target_id,
    )
    assert mapping.target_type == "classification_mapping"
    assert mapping.revision == 1

    with pytest.raises(SomaError) as mapping_error:
        classification.create_mapping(
            command_id=new_uuid4(),
            customer_org_id=customer_a.customer_org_id,
            customer_account_code="ACCT-WRONG",
            contract_product_line_id=cpl_b.target_id,
        )
    assert mapping_error.value.code == "SLA_CLASSIFICATION_CROSS_CUSTOMER"
