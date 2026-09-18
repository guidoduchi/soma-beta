from __future__ import annotations

import pytest

from soma.foundation.errors import SomaError
from soma.foundation.identifiers import new_uuid4
from soma.foundation.persistence.uow import ReadSnapshot, UnitOfWork
from soma.product_line_sla.algorithms.cohort_state import (
    CanonicalCohortCalculator,
    canonical_month_bounds,
)
from soma.product_line_sla.algorithms.individual_sla import IndividualSlaCalculator
from soma.product_line_sla.repositories.catalog import ProductLineRepository
from soma.product_line_sla.repositories.classification import SrClassificationRepository
from soma.product_line_sla.repositories.policy import SlaPolicyRepository
from soma.product_line_sla.services.catalog import ProductLineSlaCatalogService
from soma.product_line_sla.services.classification import (
    ProductLineSlaClassificationService,
)
from soma.product_line_sla.services.policy import ProductLineSlaPolicyService
from soma.reference.application.customer_service import CustomerReferenceService
from soma.tickets.service_requests import ServiceRequestService
from soma.tickets.sr_references import ServiceRequestReferenceService
from soma.tickets.sr_source_projection import (
    AcceptedSrFieldDelta,
    AcceptedSrFieldDeltaSet,
    SrSourceProjectionService,
)

MONTH = "2026-09"
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


def _receipt(uow: UnitOfWork, command_id: str, target_id: str) -> None:
    uow.connection.execute(
        "INSERT INTO command_receipts(command_id,command_type,request_hash,target_type,target_id,"
        "committed_at_utc,result_type,result_id) VALUES (?,?,?,?,?,?,?,?)",
        (
            command_id,
            "TestAcceptedSourceProjection",
            "a" * 64,
            "service_request",
            target_id,
            1,
            None,
            None,
        ),
    )


def _delta(
    field_key: str,
    *,
    value: str | int,
    chronology: int,
    precedence: str = "source_chronology",
) -> AcceptedSrFieldDelta:
    kinds = {
        "report_date": "instant",
        "customer_severity": "controlled",
        "status": "controlled",
        "customer_account_code": "text",
    }
    return AcceptedSrFieldDelta(
        field_key=field_key,
        value_state="usable",
        value_kind=kinds[field_key],
        value=value,
        source_chronology_utc=chronology,
        precedence_basis=precedence,
        source_observation_field_id=new_uuid4(),
    )


def _apply_source(factory, service_request_id: str, *deltas: AcceptedSrFieldDelta) -> None:
    command_id = new_uuid4()
    with UnitOfWork(factory) as uow:
        _receipt(uow, command_id, service_request_id)
        SrSourceProjectionService(_EvidenceProvider()).apply_accepted_field_deltas(
            uow,
            service_request_id,
            AcceptedSrFieldDeltaSet(
                accepted_command_id=command_id,
                deltas=tuple(deltas),
            ),
        )


def _catalog_environment(factory, suffix: str):
    customer = CustomerReferenceService(factory).create_customer_organization(
        command_id=new_uuid4(),
        name=f"Failure Customer {suffix}",
    )
    catalog = ProductLineSlaCatalogService(factory)
    product = catalog.create_product_line(
        command_id=new_uuid4(),
        name=f"Failure Product {suffix}",
    )
    contract = catalog.create_contract(
        command_id=new_uuid4(),
        customer_org_id=customer.customer_org_id,
        name=f"Failure Contract {suffix}",
        contract_reference=f"FAIL-{suffix}",
    )
    cpl = catalog.create_contract_product_line(
        command_id=new_uuid4(),
        contract_id=contract.target_id,
        product_line_id=product.target_id,
        initial_policy_name=f"Failure Policy {suffix}",
        initial_template_source="IT_DEFAULT_V1",
    )
    return customer, product, contract, cpl


def _classified_sr(factory, suffix: int):
    customer, _product, _contract, cpl = _catalog_environment(factory, str(suffix))
    classification = ProductLineSlaClassificationService(factory)
    references = ServiceRequestReferenceService(factory, classification)
    sr = ServiceRequestService(factory).create_manual_service_request(
        command_id=new_uuid4(),
        official_sr_no=f"98{suffix:06d}",
    )
    references.set_customer(
        command_id=new_uuid4(),
        service_request_id=sr.service_request_id,
        base_revision=1,
        customer_org_id=customer.customer_org_id,
        reason_category="failure_test_customer",
    )
    preview = classification.preview_manual(
        service_request_id=sr.service_request_id,
        contract_product_line_id=cpl.target_id,
    )
    classification.classify_service_request(
        command_id=new_uuid4(),
        service_request_id=sr.service_request_id,
        target_contract_product_line_id=cpl.target_id,
        preview_fingerprint=preview.input_fingerprint,
        origin="manual_review",
        reason_category="failure_test_classification",
    )
    return customer, cpl, sr


def test_f001_receipt_rolls_back_when_catalog_insert_fails(
    initialized_database,
    monkeypatch,
) -> None:
    factory = _factory(initialized_database)
    service = ProductLineSlaCatalogService(factory)
    command_id = new_uuid4()
    original = ProductLineRepository.insert

    def fail_before_product_write(*_args, **_kwargs):
        raise RuntimeError("injected F001 catalog failure")

    monkeypatch.setattr(
        ProductLineRepository,
        "insert",
        staticmethod(fail_before_product_write),
    )
    with pytest.raises(RuntimeError, match="injected F001"):
        service.create_product_line(
            command_id=command_id,
            name="F001 Product",
        )

    with ReadSnapshot(factory) as snapshot:
        assert snapshot.connection.execute(
            "SELECT COUNT(*) FROM command_receipts WHERE command_id=?",
            (command_id,),
        ).fetchone()[0] == 0
        assert snapshot.connection.execute(
            "SELECT COUNT(*) FROM product_lines WHERE created_command_id=?",
            (command_id,),
        ).fetchone()[0] == 0
        assert snapshot.connection.execute(
            "SELECT COUNT(*) FROM audit_events WHERE command_id=?",
            (command_id,),
        ).fetchone()[0] == 0

    monkeypatch.setattr(ProductLineRepository, "insert", staticmethod(original))
    retried = service.create_product_line(
        command_id=command_id,
        name="F001 Product",
    )
    assert retried.replayed is False
    assert retried.revision == 1


def test_f002_partial_policy_materialization_rolls_back_revision_tiers_pointer_and_receipt(
    initialized_database,
    monkeypatch,
) -> None:
    factory = _factory(initialized_database)
    _customer, _product, _contract, cpl = _catalog_environment(factory, "F002")
    service = ProductLineSlaPolicyService(factory)
    command_id = new_uuid4()
    original = SlaPolicyRepository.insert_revision_with_tiers

    with ReadSnapshot(factory) as snapshot:
        before = snapshot.connection.execute(
            "SELECT revision,current_policy_revision_id FROM contract_product_lines "
            "WHERE contract_product_line_id=?",
            (cpl.target_id,),
        ).fetchone()
        assert before is not None
        prior_revision = int(before[0])
        prior_policy_id = str(before[1])
        prior_policy_count = snapshot.connection.execute(
            "SELECT COUNT(*) FROM sla_policy_revisions WHERE contract_product_line_id=?",
            (cpl.target_id,),
        ).fetchone()[0]
        prior_tier_count = snapshot.connection.execute(
            "SELECT COUNT(*) FROM sla_policy_tiers t JOIN sla_policy_revisions r "
            "ON r.policy_revision_id=t.policy_revision_id "
            "WHERE r.contract_product_line_id=?",
            (cpl.target_id,),
        ).fetchone()[0]

    def fail_after_revision_row(uow, revision, tiers):
        uow.connection.execute(
            "INSERT INTO sla_policy_revisions("
            "policy_revision_id,contract_product_line_id,revision_ordinal,"
            "policy_name,template_source,created_at_utc,created_command_id"
            ") VALUES (?,?,?,?,?,?,?)",
            (
                revision.policy_revision_id,
                revision.contract_product_line_id,
                revision.revision_ordinal,
                revision.policy_name,
                revision.template_source,
                revision.created_at_utc,
                revision.created_command_id,
            ),
        )
        raise RuntimeError("injected F002 after policy revision row")

    monkeypatch.setattr(
        SlaPolicyRepository,
        "insert_revision_with_tiers",
        staticmethod(fail_after_revision_row),
    )
    with pytest.raises(RuntimeError, match="injected F002"):
        service.revise_policy(
            command_id=command_id,
            contract_product_line_id=cpl.target_id,
            base_revision=prior_revision,
            policy_name="F002 Revised Policy",
            template_source="NFV_DEFAULT_V1",
            reason_category="f002_failure_probe",
        )

    with ReadSnapshot(factory) as snapshot:
        after = snapshot.connection.execute(
            "SELECT revision,current_policy_revision_id FROM contract_product_lines "
            "WHERE contract_product_line_id=?",
            (cpl.target_id,),
        ).fetchone()
        assert tuple(after) == (prior_revision, prior_policy_id)
        assert snapshot.connection.execute(
            "SELECT COUNT(*) FROM sla_policy_revisions WHERE contract_product_line_id=?",
            (cpl.target_id,),
        ).fetchone()[0] == prior_policy_count
        assert snapshot.connection.execute(
            "SELECT COUNT(*) FROM sla_policy_tiers t JOIN sla_policy_revisions r "
            "ON r.policy_revision_id=t.policy_revision_id "
            "WHERE r.contract_product_line_id=?",
            (cpl.target_id,),
        ).fetchone()[0] == prior_tier_count
        assert snapshot.connection.execute(
            "SELECT COUNT(*) FROM command_receipts WHERE command_id=?",
            (command_id,),
        ).fetchone()[0] == 0
        assert snapshot.connection.execute(
            "SELECT COUNT(*) FROM audit_events WHERE command_id=?",
            (command_id,),
        ).fetchone()[0] == 0

    monkeypatch.setattr(
        SlaPolicyRepository,
        "insert_revision_with_tiers",
        staticmethod(original),
    )
    retried = service.revise_policy(
        command_id=command_id,
        contract_product_line_id=cpl.target_id,
        base_revision=prior_revision,
        policy_name="F002 Revised Policy",
        template_source="NFV_DEFAULT_V1",
        reason_category="f002_failure_probe",
    )
    assert retried.replayed is False
    assert retried.revision == prior_revision + 1


def test_f005_second_mapping_after_preview_blocks_automatic_acceptance(
    initialized_database,
) -> None:
    factory = _factory(initialized_database)
    customer, product, _contract, cpl_a = _catalog_environment(factory, "F005-A")
    catalog = ProductLineSlaCatalogService(factory)
    contract_b = catalog.create_contract(
        command_id=new_uuid4(),
        customer_org_id=customer.customer_org_id,
        name="Failure Contract F005-B",
        contract_reference="FAIL-F005-B",
    )
    cpl_b = catalog.create_contract_product_line(
        command_id=new_uuid4(),
        contract_id=contract_b.target_id,
        product_line_id=product.target_id,
        initial_policy_name="Failure Policy F005-B",
        initial_template_source="IT_DEFAULT_V1",
    )

    classification = ProductLineSlaClassificationService(factory)
    references = ServiceRequestReferenceService(factory, classification)
    sr = ServiceRequestService(factory).create_manual_service_request(
        command_id=new_uuid4(),
        official_sr_no="98500001",
    )
    references.set_customer(
        command_id=new_uuid4(),
        service_request_id=sr.service_request_id,
        base_revision=1,
        customer_org_id=customer.customer_org_id,
        reason_category="f005_customer",
    )
    _apply_source(
        factory,
        sr.service_request_id,
        _delta(
            "customer_account_code",
            value="F005-ACCOUNT",
            chronology=100,
        ),
    )
    mapping_a = classification.create_mapping(
        command_id=new_uuid4(),
        customer_org_id=customer.customer_org_id,
        customer_account_code="F005-ACCOUNT",
        contract_product_line_id=cpl_a.target_id,
    )
    preview = classification.preview_automatic(
        service_request_id=sr.service_request_id,
    )
    assert preview.state == "eligible"
    assert preview.mapping_id == mapping_a.target_id

    classification.create_mapping(
        command_id=new_uuid4(),
        customer_org_id=customer.customer_org_id,
        customer_account_code="F005-ACCOUNT",
        contract_product_line_id=cpl_b.target_id,
    )

    with pytest.raises(SomaError) as stale:
        classification.classify_service_request(
            command_id=new_uuid4(),
            service_request_id=sr.service_request_id,
            target_contract_product_line_id=cpl_a.target_id,
            preview_fingerprint=preview.input_fingerprint,
            origin="automatic_mapping",
            mapping_id=mapping_a.target_id,
            reason_category="f005_stale_automatic",
        )
    assert stale.value.code == "SLA_CLASSIFICATION_STALE"
    refreshed = classification.preview_automatic(
        service_request_id=sr.service_request_id,
    )
    assert refreshed.state == "ambiguous"

    with ReadSnapshot(factory) as snapshot:
        assert snapshot.connection.execute(
            "SELECT COUNT(*) FROM sr_classification_events WHERE service_request_id=?",
            (sr.service_request_id,),
        ).fetchone()[0] == 0
        assert snapshot.connection.execute(
            "SELECT COUNT(*) FROM sr_classification_current WHERE service_request_id=?",
            (sr.service_request_id,),
        ).fetchone()[0] == 0


def test_f006_event_before_current_pointer_failure_rolls_back_classification(
    initialized_database,
    monkeypatch,
) -> None:
    factory = _factory(initialized_database)
    customer, _product, _contract, cpl = _catalog_environment(factory, "F006")
    classification = ProductLineSlaClassificationService(factory)
    references = ServiceRequestReferenceService(factory, classification)
    sr = ServiceRequestService(factory).create_manual_service_request(
        command_id=new_uuid4(),
        official_sr_no="98600001",
    )
    references.set_customer(
        command_id=new_uuid4(),
        service_request_id=sr.service_request_id,
        base_revision=1,
        customer_org_id=customer.customer_org_id,
        reason_category="f006_customer",
    )
    preview = classification.preview_manual(
        service_request_id=sr.service_request_id,
        contract_product_line_id=cpl.target_id,
    )
    command_id = new_uuid4()
    original = SrClassificationRepository.set_current

    def fail_after_event(*_args, **_kwargs):
        raise RuntimeError("injected F006 after classification event")

    monkeypatch.setattr(
        SrClassificationRepository,
        "set_current",
        staticmethod(fail_after_event),
    )
    with pytest.raises(RuntimeError, match="injected F006"):
        classification.classify_service_request(
            command_id=command_id,
            service_request_id=sr.service_request_id,
            target_contract_product_line_id=cpl.target_id,
            preview_fingerprint=preview.input_fingerprint,
            origin="manual_review",
            reason_category="f006_failure_probe",
        )

    with ReadSnapshot(factory) as snapshot:
        assert snapshot.connection.execute(
            "SELECT COUNT(*) FROM command_receipts WHERE command_id=?",
            (command_id,),
        ).fetchone()[0] == 0
        assert snapshot.connection.execute(
            "SELECT COUNT(*) FROM sr_classification_events WHERE service_request_id=?",
            (sr.service_request_id,),
        ).fetchone()[0] == 0
        assert snapshot.connection.execute(
            "SELECT COUNT(*) FROM sr_classification_current WHERE service_request_id=?",
            (sr.service_request_id,),
        ).fetchone()[0] == 0
        assert snapshot.connection.execute(
            "SELECT COUNT(*) FROM audit_events WHERE command_id=?",
            (command_id,),
        ).fetchone()[0] == 0

    monkeypatch.setattr(
        SrClassificationRepository,
        "set_current",
        staticmethod(original),
    )
    retried = classification.classify_service_request(
        command_id=command_id,
        service_request_id=sr.service_request_id,
        target_contract_product_line_id=cpl.target_id,
        preview_fingerprint=preview.input_fingerprint,
        origin="manual_review",
        reason_category="f006_failure_probe",
    )
    assert retried.outcome == "APPLIED"
    assert retried.revision == 1


def test_f008_policy_change_does_not_mix_inside_existing_read_snapshot(
    initialized_database,
) -> None:
    factory = _factory(initialized_database)
    _customer, cpl, sr = _classified_sr(factory, 8)
    report_date = 1_000_000
    as_of = report_date + 5 * DAY
    _apply_source(
        factory,
        sr.service_request_id,
        _delta("report_date", value=report_date, chronology=100),
        _delta("customer_severity", value="Critical", chronology=100),
    )

    with ReadSnapshot(factory) as snapshot:
        before = IndividualSlaCalculator.calculate(
            snapshot.connection,
            sr.service_request_id,
            as_of,
        )
        assert before.tier_results[0].individual_state == "active_within"

        revised = ProductLineSlaPolicyService(factory).revise_policy(
            command_id=new_uuid4(),
            contract_product_line_id=cpl.target_id,
            base_revision=1,
            policy_name="F008 New Policy",
            template_source="NFV_DEFAULT_V1",
            reason_category="f008_policy_race",
        )
        same_snapshot = IndividualSlaCalculator.calculate(
            snapshot.connection,
            sr.service_request_id,
            as_of,
        )
        assert same_snapshot == before

    with ReadSnapshot(factory) as newer:
        after = IndividualSlaCalculator.calculate(
            newer.connection,
            sr.service_request_id,
            as_of,
        )
    assert after.policy_revision_id == revised.policy_revision_id
    assert after.policy_revision_id != before.policy_revision_id
    assert after.tier_results[0].individual_state == "active_exceeded"


def test_f012_terminal_endpoint_before_report_date_clamps_elapsed_to_zero(
    initialized_database,
) -> None:
    factory = _factory(initialized_database)
    _customer, _cpl, sr = _classified_sr(factory, 12)
    report_date = 2_000_000
    resolved_at = report_date - 100
    _apply_source(
        factory,
        sr.service_request_id,
        _delta("report_date", value=report_date, chronology=report_date),
        _delta("customer_severity", value="Critical", chronology=report_date),
        _delta(
            "status",
            value="Resolved",
            chronology=resolved_at,
            precedence="reviewed_correction",
        ),
    )

    with ReadSnapshot(factory) as snapshot:
        result = IndividualSlaCalculator.calculate(
            snapshot.connection,
            sr.service_request_id,
            report_date + DAY,
        )

    assert result.endpoint_kind == "first_resolved_closed"
    assert result.endpoint_utc == resolved_at
    assert result.effective_elapsed_numerator_seconds == 0
    assert result.effective_elapsed_denominator == 1
    assert result.tier_results[0].individual_state == "terminal_met"


def test_f013_terminal_correction_is_isolated_by_cohort_read_snapshot(
    initialized_database,
) -> None:
    factory = _factory(initialized_database)
    customer, _cpl, sr = _classified_sr(factory, 13)
    month_start, _month_end = canonical_month_bounds(MONTH)
    report_date = month_start + 2 * DAY
    resolved_at = report_date + DAY
    as_of = report_date + 2 * DAY
    _apply_source(
        factory,
        sr.service_request_id,
        _delta("report_date", value=report_date, chronology=report_date),
        _delta("customer_severity", value="Critical", chronology=report_date),
        _delta("status", value="Resolved", chronology=resolved_at),
    )

    with ReadSnapshot(factory) as snapshot:
        before = CanonicalCohortCalculator.calculate_month(
            snapshot.connection,
            calendar_month=MONTH,
            as_of_utc=as_of,
            customer_scope=customer.customer_org_id,
        )
        assert len(before.members) == 1
        assert before.members[0].individual_result.status_class == "resolved"

        _apply_source(
            factory,
            sr.service_request_id,
            _delta(
                "status",
                value="Cancelled",
                chronology=resolved_at + 100,
                precedence="reviewed_correction",
            ),
        )

        same_snapshot = CanonicalCohortCalculator.calculate_month(
            snapshot.connection,
            calendar_month=MONTH,
            as_of_utc=as_of,
            customer_scope=customer.customer_org_id,
        )
        assert same_snapshot == before

    with ReadSnapshot(factory) as newer:
        after = CanonicalCohortCalculator.calculate_month(
            newer.connection,
            calendar_month=MONTH,
            as_of_utc=as_of,
            customer_scope=customer.customer_org_id,
        )
        individual_after = IndividualSlaCalculator.calculate(
            newer.connection,
            sr.service_request_id,
            as_of,
        )
    assert individual_after.status_class == "cancelled"
    assert individual_after.calculation_state == "cancelled_excluded"
    assert after.members == ()
    assert after.cohorts == ()
