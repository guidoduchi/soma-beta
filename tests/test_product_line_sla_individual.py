from __future__ import annotations

from dataclasses import dataclass

from soma.foundation.identifiers import new_uuid4
from soma.foundation.persistence.uow import UnitOfWork
from soma.product_line_sla.algorithms.individual_sla import IndividualSlaCalculator
from soma.product_line_sla.services.catalog import ProductLineSlaCatalogService
from soma.product_line_sla.services.classification import ProductLineSlaClassificationService
from soma.product_line_sla.services.policy import ProductLineSlaPolicyService
from soma.reference.application.customer_service import CustomerReferenceService
from soma.tickets.service_requests import ServiceRequestService
from soma.tickets.sr_references import ServiceRequestReferenceService
from soma.tickets.sr_source_projection import (
    AcceptedSrFieldDelta,
    AcceptedSrFieldDeltaSet,
    SrSourceProjectionService,
)


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


@dataclass(frozen=True)
class _Setup:
    customer_id: str
    cpl_id: str
    service_request_id: str


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
        "suspension_duration": "duration_seconds",
        "suspend_planned_end": "instant",
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


def _classified(factory, *, suffix: str, template: str = "IT_DEFAULT_V1") -> _Setup:
    customer = CustomerReferenceService(factory).create_customer_organization(
        command_id=new_uuid4(),
        name=f"SLA Customer {suffix}",
    )
    catalog = ProductLineSlaCatalogService(factory)
    product = catalog.create_product_line(
        command_id=new_uuid4(),
        name=f"SLA Product {suffix}",
    )
    contract = catalog.create_contract(
        command_id=new_uuid4(),
        customer_org_id=customer.customer_org_id,
        name=f"SLA Contract {suffix}",
        contract_reference=f"SLA-{suffix}",
    )
    cpl = catalog.create_contract_product_line(
        command_id=new_uuid4(),
        contract_id=contract.target_id,
        product_line_id=product.target_id,
        initial_policy_name=f"SLA Policy {suffix}",
        initial_template_source=template,
    )
    classification = ProductLineSlaClassificationService(factory)
    references = ServiceRequestReferenceService(factory, classification)
    sr = ServiceRequestService(factory).create_manual_service_request(
        command_id=new_uuid4(),
        official_sr_no=f"87{int(suffix):06d}",
    )
    references.set_customer(
        command_id=new_uuid4(),
        service_request_id=sr.service_request_id,
        base_revision=1,
        customer_org_id=customer.customer_org_id,
        reason_category="sla_test_customer",
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
        reason_category="sla_test_classification",
    )
    return _Setup(
        customer_id=customer.customer_org_id,
        cpl_id=cpl.target_id,
        service_request_id=sr.service_request_id,
    )


def _calculate(factory, sr_id: str, as_of: int):
    connection = factory.open_authoritative(read_only=True, require_wal=True)
    try:
        return IndividualSlaCalculator.calculate(connection, sr_id, as_of)
    finally:
        connection.close()


def test_unclassified_remains_distinct_from_missing_report_date(initialized_database) -> None:
    factory = _factory(initialized_database)
    sr = ServiceRequestService(factory).create_manual_service_request(
        command_id=new_uuid4(),
        official_sr_no="87990001",
    )

    result = _calculate(factory, sr.service_request_id, 2_000_000)

    assert result.classification_state == "unclassified"
    assert result.calculation_state == "unclassified"
    assert result.report_date_utc is None
    assert result.tier_results == ()


def test_classified_missing_report_date_and_severity_are_explicit(initialized_database) -> None:
    factory = _factory(initialized_database)
    setup = _classified(factory, suffix="1")
    _apply_source(
        factory,
        setup.service_request_id,
        _delta("customer_severity", value="Critical", chronology=100),
    )

    missing_date = _calculate(factory, setup.service_request_id, 2_000_000)
    assert missing_date.classification_state == "classified"
    assert missing_date.calculation_state == "missing_report_date"

    setup2 = _classified(factory, suffix="2")
    _apply_source(
        factory,
        setup2.service_request_id,
        _delta("report_date", value=1_000_000, chronology=100),
    )
    missing_severity = _calculate(factory, setup2.service_request_id, 2_000_000)
    assert missing_severity.calculation_state == "severity_unresolved"


def test_active_elapsed_uses_as_of_and_inclusive_exact_boundary(initialized_database) -> None:
    factory = _factory(initialized_database)
    setup = _classified(factory, suffix="3")
    report_date = 1_000_000
    seven_days = 7 * 86_400
    _apply_source(
        factory,
        setup.service_request_id,
        _delta("report_date", value=report_date, chronology=100),
        _delta("customer_severity", value="Critical", chronology=100),
    )

    boundary = _calculate(factory, setup.service_request_id, report_date + seven_days)
    assert boundary.endpoint_kind == "current"
    assert boundary.endpoint_utc == report_date + seven_days
    assert boundary.effective_elapsed_numerator_seconds == seven_days
    assert boundary.effective_elapsed_denominator == 1
    assert len(boundary.tier_results) == 1
    assert boundary.tier_results[0].individual_state == "active_within"
    assert boundary.tier_results[0].inclusive_boundary_met is True

    exceeded = _calculate(factory, setup.service_request_id, report_date + seven_days + 1)
    assert exceeded.tier_results[0].individual_state == "active_exceeded"
    assert exceeded.tier_results[0].inclusive_boundary_met is False


def test_suspension_is_source_only_and_elapsed_clamps_to_zero(initialized_database) -> None:
    factory = _factory(initialized_database)
    setup = _classified(factory, suffix="4")
    report_date = 1_000_000
    _apply_source(
        factory,
        setup.service_request_id,
        _delta("report_date", value=report_date, chronology=100),
        _delta("customer_severity", value="Critical", chronology=100),
        _delta("suspension_duration", value=500, chronology=100),
        _delta("status", value="Customer Agreed Suspend", chronology=100),
        _delta("suspend_planned_end", value=report_date + 10_000, chronology=100),
    )

    result = _calculate(factory, setup.service_request_id, report_date + 100)

    assert result.suspension_numerator_seconds == 500
    assert result.effective_elapsed_numerator_seconds == 0
    assert result.effective_elapsed_denominator == 1
    assert result.endpoint_utc == report_date + 100
    assert result.tier_results[0].individual_state == "active_within"


def test_first_resolved_endpoint_wins_over_later_closed(initialized_database) -> None:
    factory = _factory(initialized_database)
    setup = _classified(factory, suffix="5")
    report_date = 1_000_000
    resolved_at = report_date + 5 * 86_400
    closed_at = report_date + 9 * 86_400
    _apply_source(
        factory,
        setup.service_request_id,
        _delta("report_date", value=report_date, chronology=100),
        _delta("customer_severity", value="Critical", chronology=100),
        _delta("status", value="Resolved", chronology=resolved_at),
    )
    _apply_source(
        factory,
        setup.service_request_id,
        _delta(
            "status",
            value="Closed",
            chronology=closed_at,
            precedence="reviewed_correction",
        ),
    )

    result = _calculate(factory, setup.service_request_id, closed_at + 100)

    assert result.status_class == "closed"
    assert result.endpoint_kind == "first_resolved_closed"
    assert result.endpoint_utc == resolved_at
    assert result.effective_elapsed_numerator_seconds == 5 * 86_400
    assert result.tier_results[0].individual_state == "terminal_met"


def test_cancelled_is_excluded_from_individual_tiers(initialized_database) -> None:
    factory = _factory(initialized_database)
    setup = _classified(factory, suffix="6")
    report_date = 1_000_000
    _apply_source(
        factory,
        setup.service_request_id,
        _delta("report_date", value=report_date, chronology=100),
        _delta("customer_severity", value="Critical", chronology=100),
        _delta("status", value="Cancelled", chronology=report_date + 10),
    )

    result = _calculate(factory, setup.service_request_id, report_date + 100)

    assert result.status_class == "cancelled"
    assert result.calculation_state == "cancelled_excluded"
    assert result.endpoint_kind == "cancelled"
    assert result.tier_results == ()


def test_new_current_policy_recalculates_without_rewriting_service_request(initialized_database) -> None:
    factory = _factory(initialized_database)
    setup = _classified(factory, suffix="7")
    report_date = 1_000_000
    five_days = 5 * 86_400
    _apply_source(
        factory,
        setup.service_request_id,
        _delta("report_date", value=report_date, chronology=100),
        _delta("customer_severity", value="Critical", chronology=100),
    )

    before = _calculate(factory, setup.service_request_id, report_date + five_days)
    assert before.tier_results[0].individual_state == "active_within"

    revised = ProductLineSlaPolicyService(factory).revise_policy(
        command_id=new_uuid4(),
        contract_product_line_id=setup.cpl_id,
        base_revision=1,
        policy_name="Retroactive NFV",
        template_source="NFV_DEFAULT_V1",
        reason_category="sla_test_policy_revision",
    )
    after = _calculate(factory, setup.service_request_id, report_date + five_days)

    assert after.policy_revision_id == revised.policy_revision_id
    assert after.policy_revision_id != before.policy_revision_id
    assert after.tier_results[0].individual_state == "active_exceeded"
    assert after.service_request_id == before.service_request_id
