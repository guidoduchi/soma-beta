from __future__ import annotations

import pytest

from soma.foundation.errors import SomaError
from soma.foundation.identifiers import new_uuid4, utc_epoch_seconds
from soma.foundation.jobs import DurableJobCoordinator, JobTypeRegistry
from soma.foundation.persistence.uow import ReadSnapshot, UnitOfWork
from soma.product_line_sla.algorithms.cohort_state import canonical_month_bounds
from soma.product_line_sla.artifacts.xlsx_report import (
    BoundReportDestination,
    SlaReportXlsxArtifact,
)
from soma.product_line_sla.jobs import PRODUCT_LINE_SLA_JOB_CONTRACTS
from soma.product_line_sla.jobs.report_generation import SlaReportGenerationWorker
from soma.product_line_sla.repositories.reports import ReportRepository
from soma.product_line_sla.services.catalog import ProductLineSlaCatalogService
from soma.product_line_sla.services.classification import (
    ProductLineSlaClassificationService,
)
from soma.product_line_sla.services.report_orchestration import (
    SlaReportOrchestrationService,
)
from soma.reference.application.customer_service import CustomerReferenceService
from soma.tickets.service_requests import ServiceRequestService
from soma.tickets.sr_references import ServiceRequestReferenceService
from soma.tickets.sr_source_projection import (
    AcceptedSrFieldDelta,
    AcceptedSrFieldDeltaSet,
    SrSourceProjectionService,
)

MONTH = "2026-09"
DESTINATION_TOKEN = "d" * 64
DAY = 86_400


def _factory(initialized_database):
    database_path, factory_builder = initialized_database
    return factory_builder(database_path)


class _EvidenceProvider:
    def validate_published_field(self, *_args, **_kwargs) -> str:
        return "VALID"

    def source_freshness_token(self, *_args, **_kwargs) -> str:
        return "a" * 64

    def has_accepted_source_provenance(self, *_args, **_kwargs) -> str:
        return "YES"


def _customer(factory, name: str):
    return CustomerReferenceService(factory).create_customer_organization(
        command_id=new_uuid4(),
        name=name,
    )


def _product(factory, name: str):
    return ProductLineSlaCatalogService(factory).create_product_line(
        command_id=new_uuid4(),
        name=name,
    )


def _contract_cpl(
    factory,
    *,
    customer_org_id: str,
    product_line_id: str,
    suffix: str,
    template: str | None = "IT_DEFAULT_V1",
):
    catalog = ProductLineSlaCatalogService(factory)
    contract = catalog.create_contract(
        command_id=new_uuid4(),
        customer_org_id=customer_org_id,
        name=f"Contract {suffix}",
        contract_reference=f"REF-{suffix}",
    )
    if template is None:
        cpl = catalog.create_contract_product_line(
            command_id=new_uuid4(),
            contract_id=contract.target_id,
            product_line_id=product_line_id,
        )
    else:
        cpl = catalog.create_contract_product_line(
            command_id=new_uuid4(),
            contract_id=contract.target_id,
            product_line_id=product_line_id,
            initial_policy_name=f"Policy {suffix}",
            initial_template_source=template,
        )
    return contract, cpl


def _service_request(
    factory,
    references: ServiceRequestReferenceService,
    *,
    official_sr_no: str,
    customer_org_id: str,
):
    sr = ServiceRequestService(factory).create_manual_service_request(
        command_id=new_uuid4(),
        official_sr_no=official_sr_no,
    )
    changed = references.set_customer(
        command_id=new_uuid4(),
        service_request_id=sr.service_request_id,
        base_revision=1,
        customer_org_id=customer_org_id,
        reason_category="lld06_acceptance_customer",
    )
    assert changed.revision == 2
    return sr


def _source_delta(
    field_key: str,
    value: str | int,
    *,
    chronology: int,
) -> AcceptedSrFieldDelta:
    kinds = {
        "product": "text",
        "customer_account_code": "text",
        "report_date": "instant",
        "customer_severity": "controlled",
    }
    return AcceptedSrFieldDelta(
        field_key=field_key,
        value_state="usable",
        value_kind=kinds[field_key],
        value=value,
        source_chronology_utc=chronology,
        precedence_basis="source_chronology",
        source_observation_field_id=new_uuid4(),
    )


def _apply_source(factory, service_request_id: str, *deltas: AcceptedSrFieldDelta) -> None:
    command_id = new_uuid4()
    with UnitOfWork(factory) as uow:
        uow.connection.execute(
            "INSERT INTO command_receipts("
            "command_id,command_type,request_hash,target_type,target_id,"
            "committed_at_utc,result_type,result_id"
            ") VALUES (?,?,?,?,?,?,?,?)",
            (
                command_id,
                "TestAcceptedSourceProjection",
                "a" * 64,
                "service_request",
                service_request_id,
                1,
                None,
                None,
            ),
        )
        SrSourceProjectionService(_EvidenceProvider()).apply_accepted_field_deltas(
            uow,
            service_request_id,
            AcceptedSrFieldDeltaSet(
                accepted_command_id=command_id,
                deltas=tuple(deltas),
            ),
        )


def _classify_manual(
    classification: ProductLineSlaClassificationService,
    *,
    service_request_id: str,
    contract_product_line_id: str,
    reason: str,
):
    preview = classification.preview_manual(
        service_request_id=service_request_id,
        contract_product_line_id=contract_product_line_id,
    )
    result = classification.classify_service_request(
        command_id=new_uuid4(),
        service_request_id=service_request_id,
        target_contract_product_line_id=contract_product_line_id,
        preview_fingerprint=preview.input_fingerprint,
        origin="manual_review",
        reason_category=reason,
    )
    return preview, result


def _complete_monthly_report(
    factory,
    tmp_path,
    *,
    customer_org_id: str,
    as_of_utc: int,
) -> str:
    started = SlaReportOrchestrationService(factory).start_monthly(
        command_id=new_uuid4(),
        calendar_month=MONTH,
        as_of_utc=as_of_utc,
        customer_org_id=customer_org_id,
        destination_request_token=DESTINATION_TOKEN,
    )
    jobs = DurableJobCoordinator(
        factory,
        JobTypeRegistry(PRODUCT_LINE_SLA_JOB_CONTRACTS),
    )
    claim = jobs.claim_next(new_uuid4(), utc_epoch_seconds())
    assert claim is not None
    artifact = SlaReportXlsxArtifact(
        factory,
        BoundReportDestination(DESTINATION_TOKEN, tmp_path),
    )
    SlaReportGenerationWorker(factory, artifact=artifact).run_to_completion(claim)
    return str(started["report_attempt_id"])


def test_product_line_reuse_keeps_contract_and_cpl_authority_distinct_t001_t002(
    initialized_database,
) -> None:
    factory = _factory(initialized_database)
    customer_a = _customer(factory, "Reusable Customer A")
    customer_b = _customer(factory, "Reusable Customer B")
    product = _product(factory, "Shared Reusable Product Line")

    contract_a1, cpl_a1 = _contract_cpl(
        factory,
        customer_org_id=customer_a.customer_org_id,
        product_line_id=product.target_id,
        suffix="A1",
        template="IT_DEFAULT_V1",
    )
    contract_a2, cpl_a2 = _contract_cpl(
        factory,
        customer_org_id=customer_a.customer_org_id,
        product_line_id=product.target_id,
        suffix="A2",
        template="NFV_DEFAULT_V1",
    )
    contract_b1, cpl_b1 = _contract_cpl(
        factory,
        customer_org_id=customer_b.customer_org_id,
        product_line_id=product.target_id,
        suffix="B1",
        template="IT_DEFAULT_V1",
    )

    with ReadSnapshot(factory) as snapshot:
        rows = snapshot.connection.execute(
            "SELECT c.contract_product_line_id,c.product_line_id,ct.contract_id,"
            "ct.customer_org_id,c.current_policy_revision_id "
            "FROM contract_product_lines c "
            "JOIN contracts ct ON ct.contract_id=c.contract_id "
            "WHERE c.contract_product_line_id IN (?,?,?)",
            (cpl_a1.target_id, cpl_a2.target_id, cpl_b1.target_id),
        ).fetchall()
        resolved = {
            str(row[0]): (
                str(row[1]),
                str(row[2]),
                str(row[3]),
                None if row[4] is None else str(row[4]),
            )
            for row in rows
        }

    assert {value[0] for value in resolved.values()} == {product.target_id}
    assert resolved[cpl_a1.target_id][1] == contract_a1.target_id
    assert resolved[cpl_a2.target_id][1] == contract_a2.target_id
    assert resolved[cpl_b1.target_id][1] == contract_b1.target_id
    assert resolved[cpl_a1.target_id][2] == customer_a.customer_org_id
    assert resolved[cpl_a2.target_id][2] == customer_a.customer_org_id
    assert resolved[cpl_b1.target_id][2] == customer_b.customer_org_id
    assert len({resolved[cpl_a1.target_id][3], resolved[cpl_a2.target_id][3], resolved[cpl_b1.target_id][3]}) == 3

    classification = ProductLineSlaClassificationService(factory)
    references = ServiceRequestReferenceService(factory, classification)
    sr_a1 = _service_request(
        factory,
        references,
        official_sr_no="97100001",
        customer_org_id=customer_a.customer_org_id,
    )
    sr_a2 = _service_request(
        factory,
        references,
        official_sr_no="97100002",
        customer_org_id=customer_a.customer_org_id,
    )
    _classify_manual(
        classification,
        service_request_id=sr_a1.service_request_id,
        contract_product_line_id=cpl_a1.target_id,
        reason="select_customer_a_contract_one",
    )
    _classify_manual(
        classification,
        service_request_id=sr_a2.service_request_id,
        contract_product_line_id=cpl_a2.target_id,
        reason="select_customer_a_contract_two",
    )

    with ReadSnapshot(factory) as snapshot:
        current = snapshot.connection.execute(
            "SELECT service_request_id,contract_product_line_id "
            "FROM sr_classification_current WHERE service_request_id IN (?,?)",
            (sr_a1.service_request_id, sr_a2.service_request_id),
        ).fetchall()
    assert {tuple(map(str, row)) for row in current} == {
        (sr_a1.service_request_id, cpl_a1.target_id),
        (sr_a2.service_request_id, cpl_a2.target_id),
    }


def test_discarded_product_and_mapping_cardinality_have_exact_authority_t004_t005_t006(
    initialized_database,
) -> None:
    factory = _factory(initialized_database)
    customer_a = _customer(factory, "Mapping Customer A")
    customer_b = _customer(factory, "Mapping Customer B")
    product = _product(factory, "UNTRUSTED-SOURCE-PRODUCT")
    _contract_a, cpl_a = _contract_cpl(
        factory,
        customer_org_id=customer_a.customer_org_id,
        product_line_id=product.target_id,
        suffix="MAP-A",
    )
    _contract_a2, cpl_a2 = _contract_cpl(
        factory,
        customer_org_id=customer_a.customer_org_id,
        product_line_id=product.target_id,
        suffix="MAP-A2",
    )
    product_b = _product(factory, "Mapping Product B")
    _contract_b, cpl_b = _contract_cpl(
        factory,
        customer_org_id=customer_b.customer_org_id,
        product_line_id=product_b.target_id,
        suffix="MAP-B",
    )

    classification = ProductLineSlaClassificationService(factory)
    references = ServiceRequestReferenceService(factory, classification)

    product_only = _service_request(
        factory,
        references,
        official_sr_no="97200001",
        customer_org_id=customer_a.customer_org_id,
    )
    with pytest.raises(SomaError) as discarded:
        _apply_source(
            factory,
            product_only.service_request_id,
            _source_delta(
                "product",
                "UNTRUSTED-SOURCE-PRODUCT",
                chronology=100,
            ),
        )
    assert discarded.value.code == "SR_SOURCE_EVIDENCE_INVALID"
    product_preview = classification.preview_automatic(
        service_request_id=product_only.service_request_id,
    )
    assert product_preview.state == "unclassified"
    assert product_preview.target_contract_product_line_id is None

    zero = _service_request(
        factory,
        references,
        official_sr_no="97200002",
        customer_org_id=customer_a.customer_org_id,
    )
    _apply_source(
        factory,
        zero.service_request_id,
        _source_delta("customer_account_code", "ZERO-ACCOUNT", chronology=110),
    )
    zero_preview = classification.preview_automatic(
        service_request_id=zero.service_request_id,
    )
    assert zero_preview.state == "unclassified"

    unique = _service_request(
        factory,
        references,
        official_sr_no="97200003",
        customer_org_id=customer_a.customer_org_id,
    )
    _apply_source(
        factory,
        unique.service_request_id,
        _source_delta("customer_account_code", "UNIQUE-ACCOUNT", chronology=120),
    )
    unique_mapping = classification.create_mapping(
        command_id=new_uuid4(),
        customer_org_id=customer_a.customer_org_id,
        customer_account_code="UNIQUE-ACCOUNT",
        contract_product_line_id=cpl_a.target_id,
    )
    unique_preview = classification.preview_automatic(
        service_request_id=unique.service_request_id,
    )
    assert unique_preview.state == "eligible"
    assert unique_preview.mapping_id == unique_mapping.target_id
    assert unique_preview.target_contract_product_line_id == cpl_a.target_id
    unique_result = classification.classify_service_request(
        command_id=new_uuid4(),
        service_request_id=unique.service_request_id,
        target_contract_product_line_id=cpl_a.target_id,
        preview_fingerprint=unique_preview.input_fingerprint,
        origin="automatic_mapping",
        mapping_id=unique_preview.mapping_id,
        reason_category="unique_trusted_mapping",
    )
    assert unique_result.outcome == "APPLIED"

    ambiguous = _service_request(
        factory,
        references,
        official_sr_no="97200004",
        customer_org_id=customer_a.customer_org_id,
    )
    _apply_source(
        factory,
        ambiguous.service_request_id,
        _source_delta("customer_account_code", "AMBIG-ACCOUNT", chronology=130),
    )
    classification.create_mapping(
        command_id=new_uuid4(),
        customer_org_id=customer_a.customer_org_id,
        customer_account_code="AMBIG-ACCOUNT",
        contract_product_line_id=cpl_a.target_id,
    )
    classification.create_mapping(
        command_id=new_uuid4(),
        customer_org_id=customer_a.customer_org_id,
        customer_account_code="AMBIG-ACCOUNT",
        contract_product_line_id=cpl_a2.target_id,
    )
    ambiguous_preview = classification.preview_automatic(
        service_request_id=ambiguous.service_request_id,
    )
    assert ambiguous_preview.state == "ambiguous"
    assert ambiguous_preview.mapping_id is None
    assert ambiguous_preview.target_contract_product_line_id is None

    with pytest.raises(SomaError) as cross_customer_mapping:
        classification.create_mapping(
            command_id=new_uuid4(),
            customer_org_id=customer_a.customer_org_id,
            customer_account_code="BAD-CROSS-CUSTOMER",
            contract_product_line_id=cpl_b.target_id,
        )
    assert cross_customer_mapping.value.code == "SLA_CLASSIFICATION_CROSS_CUSTOMER"

    stale = _service_request(
        factory,
        references,
        official_sr_no="97200005",
        customer_org_id=customer_a.customer_org_id,
    )
    _apply_source(
        factory,
        stale.service_request_id,
        _source_delta("customer_account_code", "STALE-ACCOUNT", chronology=140),
    )
    stale_mapping = classification.create_mapping(
        command_id=new_uuid4(),
        customer_org_id=customer_a.customer_org_id,
        customer_account_code="STALE-ACCOUNT",
        contract_product_line_id=cpl_a2.target_id,
    )
    stale_preview = classification.preview_automatic(
        service_request_id=stale.service_request_id,
    )
    assert stale_preview.state == "eligible"
    assert stale_preview.mapping_id == stale_mapping.target_id

    ProductLineSlaCatalogService(factory).set_catalog_lifecycle(
        command_id=new_uuid4(),
        target_type="contract_product_line",
        target_id=cpl_a2.target_id,
        base_revision=1,
        lifecycle_state="archived",
        reason_category="mapping_target_archived_after_preview",
    )
    with pytest.raises(SomaError) as stale_apply:
        classification.classify_service_request(
            command_id=new_uuid4(),
            service_request_id=stale.service_request_id,
            target_contract_product_line_id=cpl_a2.target_id,
            preview_fingerprint=stale_preview.input_fingerprint,
            origin="automatic_mapping",
            mapping_id=stale_preview.mapping_id,
            reason_category="stale_mapping_attempt",
        )
    assert stale_apply.value.code == "SLA_CLASSIFICATION_STALE"
    refreshed = classification.preview_automatic(
        service_request_id=stale.service_request_id,
    )
    assert refreshed.state == "incompatible"

    with ReadSnapshot(factory) as snapshot:
        assert snapshot.connection.execute(
            "SELECT COUNT(*) FROM sr_classification_current "
            "WHERE service_request_id IN (?,?,?)",
            (
                zero.service_request_id,
                ambiguous.service_request_id,
                stale.service_request_id,
            ),
        ).fetchone()[0] == 0


def test_reclassification_history_and_completed_report_survive_archive_t007_t009(
    initialized_database,
    tmp_path,
) -> None:
    factory = _factory(initialized_database)
    month_start, _month_end = canonical_month_bounds(MONTH)
    report_date = month_start + DAY
    as_of_utc = report_date + 4 * DAY

    customer = _customer(factory, "History Customer")
    product = _product(factory, "History Shared Product")
    _contract_a, cpl_a = _contract_cpl(
        factory,
        customer_org_id=customer.customer_org_id,
        product_line_id=product.target_id,
        suffix="HIST-A",
        template="IT_DEFAULT_V1",
    )
    _contract_b, cpl_b = _contract_cpl(
        factory,
        customer_org_id=customer.customer_org_id,
        product_line_id=product.target_id,
        suffix="HIST-B",
        template="NFV_DEFAULT_V1",
    )
    _contract_none, cpl_policyless = _contract_cpl(
        factory,
        customer_org_id=customer.customer_org_id,
        product_line_id=product.target_id,
        suffix="HIST-NONE",
        template=None,
    )

    classification = ProductLineSlaClassificationService(factory)
    references = ServiceRequestReferenceService(factory, classification)
    sr = _service_request(
        factory,
        references,
        official_sr_no="97300001",
        customer_org_id=customer.customer_org_id,
    )
    first_preview, first = _classify_manual(
        classification,
        service_request_id=sr.service_request_id,
        contract_product_line_id=cpl_a.target_id,
        reason="initial_contract_classification",
    )
    assert first_preview.state == "eligible"
    assert first.outcome == "APPLIED"

    _apply_source(
        factory,
        sr.service_request_id,
        _source_delta("report_date", report_date, chronology=report_date),
        _source_delta("customer_severity", "Critical", chronology=report_date),
    )
    report_id = _complete_monthly_report(
        factory,
        tmp_path,
        customer_org_id=customer.customer_org_id,
        as_of_utc=as_of_utc,
    )

    with ReadSnapshot(factory) as snapshot:
        completed_before = ReportRepository.get_attempt(snapshot.connection, report_id)
        assert completed_before is not None
        assert completed_before.state == "completed"
        assert completed_before.snapshot_hash is not None
        frozen_hash = completed_before.snapshot_hash
        frozen_semantic = ReportRepository.snapshot_semantic_value(
            snapshot.connection,
            report_id,
        )
        assert len(frozen_semantic["members"]) == 1
        assert (
            frozen_semantic["members"][0]["contract_product_line_id"]
            == cpl_a.target_id
        )

    second_preview, second = _classify_manual(
        classification,
        service_request_id=sr.service_request_id,
        contract_product_line_id=cpl_b.target_id,
        reason="reviewed_reclassification",
    )
    assert second_preview.state == "eligible"
    assert second.outcome == "APPLIED"
    assert second.revision == 2

    ProductLineSlaCatalogService(factory).set_catalog_lifecycle(
        command_id=new_uuid4(),
        target_type="contract_product_line",
        target_id=cpl_a.target_id,
        base_revision=1,
        lifecycle_state="archived",
        reason_category="archive_prior_historical_cpl",
    )

    archived_preview = classification.preview_manual(
        service_request_id=sr.service_request_id,
        contract_product_line_id=cpl_a.target_id,
    )
    assert archived_preview.state == "incompatible"
    with pytest.raises(SomaError) as archived_apply:
        classification.classify_service_request(
            command_id=new_uuid4(),
            service_request_id=sr.service_request_id,
            target_contract_product_line_id=cpl_a.target_id,
            preview_fingerprint=archived_preview.input_fingerprint,
            origin="manual_review",
            reason_category="archived_cpl_attempt",
        )
    assert archived_apply.value.code == "SLA_CLASSIFICATION_INCOMPATIBLE"

    policyless_preview = classification.preview_manual(
        service_request_id=sr.service_request_id,
        contract_product_line_id=cpl_policyless.target_id,
    )
    assert policyless_preview.state == "incompatible"
    with pytest.raises(SomaError) as policyless_apply:
        classification.classify_service_request(
            command_id=new_uuid4(),
            service_request_id=sr.service_request_id,
            target_contract_product_line_id=cpl_policyless.target_id,
            preview_fingerprint=policyless_preview.input_fingerprint,
            origin="manual_review",
            reason_category="policyless_cpl_attempt",
        )
    assert policyless_apply.value.code == "SLA_CLASSIFICATION_INCOMPATIBLE"

    with ReadSnapshot(factory) as snapshot:
        current = snapshot.connection.execute(
            "SELECT contract_product_line_id,revision FROM sr_classification_current "
            "WHERE service_request_id=?",
            (sr.service_request_id,),
        ).fetchone()
        assert tuple(current) == (cpl_b.target_id, 2)

        history = snapshot.connection.execute(
            "SELECT event_kind,prior_contract_product_line_id,new_contract_product_line_id "
            "FROM sr_classification_events WHERE service_request_id=?",
            (sr.service_request_id,),
        ).fetchall()
        assert {tuple(row) for row in history} == {
            ("assign", None, cpl_a.target_id),
            ("reclassify", cpl_a.target_id, cpl_b.target_id),
        }

        completed_after = ReportRepository.get_attempt(snapshot.connection, report_id)
        assert completed_after is not None
        assert completed_after.state == "completed"
        assert completed_after.snapshot_hash == frozen_hash
        assert ReportRepository.snapshot_hash(snapshot.connection, report_id) == frozen_hash
        assert (
            ReportRepository.snapshot_semantic_value(snapshot.connection, report_id)
            == frozen_semantic
        )

        cpl_history = snapshot.connection.execute(
            "SELECT lifecycle_state,current_policy_revision_id FROM contract_product_lines "
            "WHERE contract_product_line_id=?",
            (cpl_a.target_id,),
        ).fetchone()
        assert str(cpl_history[0]) == "archived"
        assert cpl_history[1] is not None
