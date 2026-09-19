from __future__ import annotations

import json

import pytest

from soma.foundation.errors import IdempotencyConflict
from soma.foundation.identifiers import new_uuid4
from soma.foundation.persistence.uow import ReadSnapshot
from soma.product_line_sla.queries.classification import (
    ProductLineSlaClassificationQueryService,
)
from soma.product_line_sla.services.batch_classification import (
    ProductLineSlaBatchClassificationService,
)
from soma.product_line_sla.services.catalog import ProductLineSlaCatalogService
from soma.product_line_sla.services.classification import (
    ProductLineSlaClassificationService,
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


def _cpl(factory, *, customer_org_id: str):
    catalog = ProductLineSlaCatalogService(factory)
    product = catalog.create_product_line(
        command_id=new_uuid4(),
        name="Batch Product",
    )
    contract = catalog.create_contract(
        command_id=new_uuid4(),
        customer_org_id=customer_org_id,
        name="Batch Contract",
        contract_reference="BATCH-REF",
    )
    return catalog.create_contract_product_line(
        command_id=new_uuid4(),
        contract_id=contract.target_id,
        product_line_id=product.target_id,
        initial_policy_name="Batch Policy",
        initial_template_source="IT_DEFAULT_V1",
    )


def _service_request(factory, references, *, official_sr_no: str, customer_org_id: str):
    sr = ServiceRequestService(factory).create_manual_service_request(
        command_id=new_uuid4(),
        official_sr_no=official_sr_no,
    )
    changed = references.set_customer(
        command_id=new_uuid4(),
        service_request_id=sr.service_request_id,
        base_revision=1,
        customer_org_id=customer_org_id,
        reason_category="batch_initial_customer",
    )
    assert changed.revision == 2
    return sr


def test_batch_classification_independent_results_t036_and_f029(
    initialized_database,
) -> None:
    factory = _factory(initialized_database)
    customer_a = _customer(factory, "Batch Customer A")
    customer_b = _customer(factory, "Batch Customer B")
    cpl = _cpl(factory, customer_org_id=customer_a.customer_org_id)

    classification = ProductLineSlaClassificationService(factory)
    references = ServiceRequestReferenceService(factory, classification)
    sr1 = _service_request(
        factory,
        references,
        official_sr_no="96300001",
        customer_org_id=customer_a.customer_org_id,
    )
    sr2 = _service_request(
        factory,
        references,
        official_sr_no="96300002",
        customer_org_id=customer_a.customer_org_id,
    )
    sr3 = _service_request(
        factory,
        references,
        official_sr_no="96300003",
        customer_org_id=customer_a.customer_org_id,
    )
    sr4 = _service_request(
        factory,
        references,
        official_sr_no="96300004",
        customer_org_id=customer_a.customer_org_id,
    )

    # Make SR2 a semantic NO_CHANGE member before the batch preview.
    sr2_preview = classification.preview_manual(
        service_request_id=sr2.service_request_id,
        contract_product_line_id=cpl.target_id,
    )
    sr2_initial = classification.classify_service_request(
        command_id=new_uuid4(),
        service_request_id=sr2.service_request_id,
        target_contract_product_line_id=cpl.target_id,
        preview_fingerprint=sr2_preview.input_fingerprint,
        origin="manual_review",
        reason_category="batch_preexisting_classification",
    )
    assert sr2_initial.outcome == "APPLIED"

    query = ProductLineSlaClassificationQueryService(factory)
    preview = query.preview_batch(
        service_request_ids=(
            sr1.service_request_id,
            sr2.service_request_id,
            sr3.service_request_id,
            sr4.service_request_id,
        ),
        contract_product_line_id=cpl.target_id,
    )
    assert [item.state for item in preview.items] == [
        "eligible",
        "unchanged",
        "eligible",
        "eligible",
    ]
    assert preview.exact_count == 4

    # Race the third target after preview. It must reject independently while
    # the fourth target still commits.
    changed = references.set_customer(
        command_id=new_uuid4(),
        service_request_id=sr3.service_request_id,
        base_revision=2,
        customer_org_id=customer_b.customer_org_id,
        reason_category="batch_customer_race",
    )
    assert changed.revision == 3

    batch_command_id = new_uuid4()
    service = ProductLineSlaBatchClassificationService(factory)
    result = service.apply_batch(
        command_id=batch_command_id,
        batch_correlation_id="batch-t036-independent-results",
        preview_fingerprint=preview.batch_fingerprint,
        preview_items=preview.items,
        candidate_contract_product_line_id=cpl.target_id,
        reason_category="batch_reviewed_apply",
    )
    assert result.replayed is False
    assert result.applied == (sr1.service_request_id, sr4.service_request_id)
    assert result.unchanged == (sr2.service_request_id,)
    assert result.rejected == (
        {
            "service_request_id": sr3.service_request_id,
            "error_code": "SLA_CLASSIFICATION_STALE",
        },
    )

    with ReadSnapshot(factory) as snapshot:
        current_rows = snapshot.connection.execute(
            "SELECT service_request_id,contract_product_line_id "
            "FROM sr_classification_current "
            "WHERE service_request_id IN (?,?,?,?) "
            "ORDER BY service_request_id",
            (
                sr1.service_request_id,
                sr2.service_request_id,
                sr3.service_request_id,
                sr4.service_request_id,
            ),
        ).fetchall()
        current = {str(row[0]): str(row[1]) for row in current_rows}
        assert current == {
            sr1.service_request_id: cpl.target_id,
            sr2.service_request_id: cpl.target_id,
            sr4.service_request_id: cpl.target_id,
        }

        event_counts = {
            sr_id: int(
                snapshot.connection.execute(
                    "SELECT COUNT(*) FROM sr_classification_events WHERE service_request_id=?",
                    (sr_id,),
                ).fetchone()[0]
            )
            for sr_id in (
                sr1.service_request_id,
                sr2.service_request_id,
                sr3.service_request_id,
                sr4.service_request_id,
            )
        }
        assert event_counts == {
            sr1.service_request_id: 1,
            sr2.service_request_id: 1,
            sr3.service_request_id: 0,
            sr4.service_request_id: 1,
        }

        batch_audit = snapshot.connection.execute(
            "SELECT payload_json FROM audit_events "
            "WHERE command_id=? AND action_type='sla.service_request.batch_classification_applied'",
            (batch_command_id,),
        ).fetchone()
        assert batch_audit is not None
        payload = json.loads(str(batch_audit[0]))
        assert payload["requested_count"] == 4
        assert payload["eligible_count"] == 4
        assert payload["applied_count"] == 2
        assert payload["unchanged_count"] == 1
        assert payload["rejected_count"] == 1
        assert payload["preview_fingerprint"] == preview.batch_fingerprint
        assert len(payload["result_refs"]) == 2

        batch_results = snapshot.connection.execute(
            "SELECT result_type,result_id FROM audit_event_results "
            "WHERE audit_event_id=("
            "SELECT audit_event_id FROM audit_events "
            "WHERE command_id=? AND action_type='sla.service_request.batch_classification_applied'"
            ") ORDER BY ordinal",
            (batch_command_id,),
        ).fetchall()
        assert len(batch_results) == 2
        assert {str(row[0]) for row in batch_results} == {"sr_classification_event"}

    replay = service.apply_batch(
        command_id=batch_command_id,
        batch_correlation_id="batch-t036-independent-results",
        preview_fingerprint=preview.batch_fingerprint,
        preview_items=preview.items,
        candidate_contract_product_line_id=cpl.target_id,
        reason_category="batch_reviewed_apply",
    )
    assert replay.replayed is True
    assert replay.applied == result.applied
    assert replay.unchanged == result.unchanged
    assert replay.rejected == result.rejected

    with ReadSnapshot(factory) as snapshot:
        assert snapshot.connection.execute(
            "SELECT COUNT(*) FROM audit_events "
            "WHERE command_id=? AND action_type='sla.service_request.batch_classification_applied'",
            (batch_command_id,),
        ).fetchone()[0] == 1
        assert snapshot.connection.execute(
            "SELECT COUNT(*) FROM sr_classification_events",
        ).fetchone()[0] == 3

    with pytest.raises(IdempotencyConflict):
        service.apply_batch(
            command_id=batch_command_id,
            batch_correlation_id="batch-t036-independent-results",
            preview_fingerprint=preview.batch_fingerprint,
            preview_items=preview.items,
            candidate_contract_product_line_id=cpl.target_id,
            reason_category="changed_batch_semantics",
        )
