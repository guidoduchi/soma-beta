from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime

from soma.foundation.identifiers import new_uuid4
from soma.foundation.persistence.uow import UnitOfWork
from soma.product_line_sla.algorithms.individual_sla import IndividualSlaCalculator
from soma.product_line_sla.algorithms.warnings import SlaWarningCalculator
from soma.product_line_sla.queries.sla import SlaWarningQueryService
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


def test_suspension_warning_is_separate_from_sla_state_t037(initialized_database) -> None:
    factory = _factory(initialized_database)
    setup = _classified(factory, suffix="8")
    report_date = 1_000_000
    planned_end = report_date + 20_000
    _apply_source(
        factory,
        setup.service_request_id,
        _delta("report_date", value=report_date, chronology=100),
        _delta("customer_severity", value="Critical", chronology=100),
        _delta("suspension_duration", value=500, chronology=100),
        _delta("status", value="Customer Agreed Suspend", chronology=100),
        _delta("suspend_planned_end", value=planned_end, chronology=100),
    )

    connection = factory.open_authoritative(read_only=True, require_wal=True)
    try:
        as_of = planned_end - 100
        individual = IndividualSlaCalculator.calculate(
            connection,
            setup.service_request_id,
            as_of,
        )
        warnings = SlaWarningCalculator.individual(
            connection,
            service_request_id=setup.service_request_id,
            as_of_utc=as_of,
            suspension_ending_soon_threshold_seconds=300,
        )
        assert individual.suspension_numerator_seconds == 500
        assert individual.suspension_denominator == 1
        assert individual.tier_results[0].individual_state == "active_within"
        assert [warning.warning_kind for warning in warnings] == [
            "suspension_ending_soon"
        ]

        expired_as_of = planned_end + 1
        expired = SlaWarningCalculator.individual(
            connection,
            service_request_id=setup.service_request_id,
            as_of_utc=expired_as_of,
            suspension_ending_soon_threshold_seconds=300,
        )
        assert [warning.warning_kind for warning in expired] == [
            "suspension_end_missing_or_expired"
        ]
        after = IndividualSlaCalculator.calculate(
            connection,
            setup.service_request_id,
            expired_as_of,
        )
        assert after.suspension_numerator_seconds == 500
        assert after.suspension_denominator == 1
    finally:
        connection.close()



def test_policy_revision_recalculates_terminal_current_classification_t014(
    initialized_database,
) -> None:
    factory = _factory(initialized_database)
    setup = _classified(factory, suffix="9")
    report_date = 1_000_000
    resolved_at = report_date + 5 * 86_400
    as_of = resolved_at + 123
    _apply_source(
        factory,
        setup.service_request_id,
        _delta("report_date", value=report_date, chronology=100),
        _delta("customer_severity", value="Critical", chronology=100),
        _delta("status", value="Resolved", chronology=resolved_at),
    )

    before = _calculate(factory, setup.service_request_id, as_of)
    assert before.status_class == "resolved"
    assert before.endpoint_kind == "first_resolved_closed"
    assert before.endpoint_utc == resolved_at
    assert before.tier_results[0].individual_state == "terminal_met"
    source_token = before.sla_input_token
    classification_event = before.classification_event_id

    revised = ProductLineSlaPolicyService(factory).revise_policy(
        command_id=new_uuid4(),
        contract_product_line_id=setup.cpl_id,
        base_revision=1,
        policy_name="Retroactive Terminal NFV",
        template_source="NFV_DEFAULT_V1",
        reason_category="terminal_retroactive_policy_revision",
    )
    after = _calculate(factory, setup.service_request_id, as_of)

    assert after.policy_revision_id == revised.policy_revision_id
    assert after.policy_revision_id != before.policy_revision_id
    assert after.status_class == "resolved"
    assert after.endpoint_kind == "first_resolved_closed"
    assert after.endpoint_utc == resolved_at
    assert after.effective_elapsed_numerator_seconds == 5 * 86_400
    assert after.tier_results[0].individual_state == "terminal_exceeded"
    assert after.sla_input_token == source_token
    assert after.classification_event_id == classification_event
    assert after.service_request_id == before.service_request_id


def test_repeated_explicit_as_of_is_bit_for_bit_deterministic_t016(
    initialized_database,
) -> None:
    factory = _factory(initialized_database)
    setup = _classified(factory, suffix="10")
    report_date = 2_000_000
    as_of = report_date + 2 * 86_400 + 37
    _apply_source(
        factory,
        setup.service_request_id,
        _delta("report_date", value=report_date, chronology=100),
        _delta("customer_severity", value="Major", chronology=100),
    )

    first = _calculate(factory, setup.service_request_id, as_of)
    second = _calculate(factory, setup.service_request_id, as_of)

    assert first == second
    assert first.as_of_utc == as_of
    assert first.endpoint_kind == "current"
    assert first.endpoint_utc == as_of
    assert first.effective_elapsed_numerator_seconds == as_of - report_date
    assert first.input_fingerprint == second.input_fingerprint
    assert first.sla_input_token == second.sla_input_token


def test_missing_suspension_planned_end_warns_without_inferred_pause_t037(
    initialized_database,
) -> None:
    factory = _factory(initialized_database)
    setup = _classified(factory, suffix="11")
    report_date = 3_000_000
    as_of = report_date + 1_000
    _apply_source(
        factory,
        setup.service_request_id,
        _delta("report_date", value=report_date, chronology=100),
        _delta("customer_severity", value="Critical", chronology=100),
        _delta("suspension_duration", value=400, chronology=100),
        _delta("status", value="Customer Agreed Suspend", chronology=100),
    )

    connection = factory.open_authoritative(read_only=True, require_wal=True)
    try:
        individual = IndividualSlaCalculator.calculate(
            connection,
            setup.service_request_id,
            as_of,
        )
        warnings = SlaWarningCalculator.individual(
            connection,
            service_request_id=setup.service_request_id,
            as_of_utc=as_of,
            suspension_ending_soon_threshold_seconds=300,
        )
    finally:
        connection.close()

    assert individual.status_class == "active"
    assert individual.suspension_numerator_seconds == 400
    assert individual.suspension_denominator == 1
    assert individual.effective_elapsed_numerator_seconds == 600
    assert individual.effective_elapsed_denominator == 1
    assert individual.tier_results[0].individual_state == "active_within"
    assert [warning.warning_kind for warning in warnings] == [
        "suspension_end_missing_or_expired"
    ]


def test_warning_query_preserves_multiple_exceeded_tiers_across_cursor(
    initialized_database,
) -> None:
    factory = _factory(initialized_database)
    setup = _classified(factory, suffix="50")
    report_date = 1_000_000
    _apply_source(
        factory,
        setup.service_request_id,
        _delta("report_date", value=report_date, chronology=100),
        _delta("customer_severity", value="Major", chronology=100),
    )
    as_of = report_date + 31 * 86_400
    query = SlaWarningQueryService(factory)

    first = query.list_warnings(
        customer_org_id=setup.customer_id,
        warning_kind="individual_tier_exceeded",
        as_of_utc=as_of,
        limit=1,
    )
    assert len(first.items) == 1
    assert first.next_cursor is not None
    assert first.items[0].policy_tier_id is not None

    second = query.list_warnings(
        customer_org_id=setup.customer_id,
        warning_kind="individual_tier_exceeded",
        as_of_utc=as_of,
        cursor=first.next_cursor,
        limit=1,
    )
    assert len(second.items) == 1
    assert second.next_cursor is None
    assert second.items[0].policy_tier_id is not None
    assert second.items[0].policy_tier_id != first.items[0].policy_tier_id
    assert second.items[0].target_id == first.items[0].target_id


def test_warning_query_applies_configured_suspension_ending_threshold(
    initialized_database,
) -> None:
    factory = _factory(initialized_database)
    setup = _classified(factory, suffix="51")
    as_of = 2_000_000
    _apply_source(
        factory,
        setup.service_request_id,
        _delta("status", value="Customer Agreed Suspend", chronology=100),
        _delta("suspend_planned_end", value=as_of + 120, chronology=100),
    )
    page = SlaWarningQueryService(
        factory,
        suspension_ending_soon_threshold_seconds=300,
    ).list_warnings(
        customer_org_id=setup.customer_id,
        warning_kind="suspension_ending_soon",
        as_of_utc=as_of,
    )

    assert len(page.items) == 1
    assert page.items[0].warning_kind == "suspension_ending_soon"
    assert page.items[0].target_id == setup.service_request_id
    assert page.next_cursor is None


def test_warning_query_derives_cohort_warning_from_as_of_guayaquil_month(
    initialized_database,
) -> None:
    factory = _factory(initialized_database)
    setup = _classified(factory, suffix="52")
    report_date = int(datetime(2026, 9, 1, 5, tzinfo=UTC).timestamp())
    as_of = report_date + 20 * 86_400
    _apply_source(
        factory,
        setup.service_request_id,
        _delta("report_date", value=report_date, chronology=100),
        _delta("customer_severity", value="Major", chronology=100),
    )

    page = SlaWarningQueryService(factory).list_warnings(
        customer_org_id=setup.customer_id,
        warning_kind="cohort_breached",
        as_of_utc=as_of,
    )

    assert len(page.items) == 1
    assert page.items[0].warning_kind == "cohort_breached"
    assert page.items[0].target_type == "sla_cohort"
    assert page.items[0].policy_tier_id is not None
    assert page.next_cursor is None
