from __future__ import annotations

from dataclasses import dataclass

from soma.foundation.identifiers import new_uuid4
from soma.foundation.persistence.uow import UnitOfWork
from soma.product_line_sla.algorithms.cohort_state import (
    CanonicalCohortCalculator,
    CohortProjection,
    canonical_month_bounds,
)
from soma.product_line_sla.services.catalog import ProductLineSlaCatalogService
from soma.product_line_sla.services.classification import ProductLineSlaClassificationService
from soma.reference.application.customer_service import CustomerReferenceService
from soma.tickets.service_requests import ServiceRequestService
from soma.tickets.sr_references import ServiceRequestReferenceService
from soma.tickets.sr_source_projection import (
    AcceptedSrFieldDelta,
    AcceptedSrFieldDeltaSet,
    SrSourceProjectionService,
)

DAY = 86_400
MONTH = "2026-09"


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
class _Environment:
    customer_id: str
    cpl_id: str


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
) -> AcceptedSrFieldDelta:
    kinds = {
        "report_date": "instant",
        "customer_severity": "controlled",
        "status": "controlled",
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
        _receipt(uow, command_id, service_request_id)
        SrSourceProjectionService(_EvidenceProvider()).apply_accepted_field_deltas(
            uow,
            service_request_id,
            AcceptedSrFieldDeltaSet(
                accepted_command_id=command_id,
                deltas=tuple(deltas),
            ),
        )


def _environment(factory) -> _Environment:
    customer = CustomerReferenceService(factory).create_customer_organization(
        command_id=new_uuid4(),
        name="Cohort Customer",
    )
    catalog = ProductLineSlaCatalogService(factory)
    product = catalog.create_product_line(
        command_id=new_uuid4(),
        name="Cohort Product",
    )
    contract = catalog.create_contract(
        command_id=new_uuid4(),
        customer_org_id=customer.customer_org_id,
        name="Cohort Contract",
        contract_reference="COHORT-CONTRACT",
    )
    cpl = catalog.create_contract_product_line(
        command_id=new_uuid4(),
        contract_id=contract.target_id,
        product_line_id=product.target_id,
        initial_policy_name="Cohort Policy",
        initial_template_source="IT_DEFAULT_V1",
    )
    return _Environment(
        customer_id=customer.customer_org_id,
        cpl_id=cpl.target_id,
    )


def _classified_sr(factory, env: _Environment, ordinal: int) -> str:
    classification = ProductLineSlaClassificationService(factory)
    references = ServiceRequestReferenceService(factory, classification)
    sr = ServiceRequestService(factory).create_manual_service_request(
        command_id=new_uuid4(),
        official_sr_no=f"88{ordinal:06d}",
    )
    references.set_customer(
        command_id=new_uuid4(),
        service_request_id=sr.service_request_id,
        base_revision=1,
        customer_org_id=env.customer_id,
        reason_category="cohort_test_customer",
    )
    preview = classification.preview_manual(
        service_request_id=sr.service_request_id,
        contract_product_line_id=env.cpl_id,
    )
    classification.classify_service_request(
        command_id=new_uuid4(),
        service_request_id=sr.service_request_id,
        target_contract_product_line_id=env.cpl_id,
        preview_fingerprint=preview.input_fingerprint,
        origin="manual_review",
        reason_category="cohort_test_classification",
    )
    return sr.service_request_id


def _seed_member(
    factory,
    env: _Environment,
    *,
    ordinal: int,
    report_date: int,
    severity: str,
    resolved_at: int | None = None,
) -> str:
    service_request_id = _classified_sr(factory, env, ordinal)
    deltas = [
        _delta("report_date", value=report_date, chronology=report_date),
        _delta("customer_severity", value=severity, chronology=report_date),
    ]
    if resolved_at is not None:
        deltas.append(_delta("status", value="Resolved", chronology=resolved_at))
    _apply_source(factory, service_request_id, *deltas)
    return service_request_id


def _calculate(factory, *, as_of: int):
    connection = factory.open_authoritative(read_only=True, require_wal=True)
    try:
        return CanonicalCohortCalculator.calculate_month(
            connection,
            calendar_month=MONTH,
            as_of_utc=as_of,
        )
    finally:
        connection.close()


def _cohort(
    result,
    *,
    severity: str,
    required_percentage: int,
) -> CohortProjection:
    matches = [
        cohort
        for cohort in result.cohorts
        if cohort.severity == severity
        and cohort.required_percentage_millionths == required_percentage
    ]
    assert len(matches) == 1
    return matches[0]


def test_cohort_key_excludes_individual_outcome_t023(initialized_database) -> None:
    factory = _factory(initialized_database)
    env = _environment(factory)
    month_start, _month_end = canonical_month_bounds(MONTH)
    report_date = month_start + 5 * DAY
    as_of = report_date + 3 * DAY

    _seed_member(
        factory,
        env,
        ordinal=1,
        report_date=report_date,
        severity="Critical",
    )
    _seed_member(
        factory,
        env,
        ordinal=2,
        report_date=report_date,
        severity="Critical",
        resolved_at=report_date + DAY,
    )

    result = _calculate(factory, as_of=as_of)
    cohort = _cohort(
        result,
        severity="critical",
        required_percentage=100_000_000,
    )

    assert len(result.cohorts) == 1
    assert cohort.denominator == 2
    assert cohort.active_within_count == 1
    assert cohort.terminal_met_count == 1
    assert cohort.active_exceeded_count == 0
    assert cohort.terminal_exceeded_count == 0
    assert {member.cohort_key.opaque_key for member in result.members} == {
        cohort.cohort_key
    }


def test_open_cohort_with_only_potential_members_is_pending_t024(
    initialized_database,
) -> None:
    factory = _factory(initialized_database)
    env = _environment(factory)
    month_start, _month_end = canonical_month_bounds(MONTH)
    report_date = month_start + 10 * DAY
    as_of = report_date + 3 * DAY

    _seed_member(
        factory,
        env,
        ordinal=10,
        report_date=report_date,
        severity="Critical",
    )

    cohort = _cohort(
        _calculate(factory, as_of=as_of),
        severity="critical",
        required_percentage=100_000_000,
    )

    assert cohort.lower_bound_met_count == 0
    assert cohort.best_possible_met_count == 1
    assert cohort.state == "pending"
    assert cohort.is_final is False


def test_exceeded_member_with_viable_best_possible_is_at_risk_t025(
    initialized_database,
) -> None:
    factory = _factory(initialized_database)
    env = _environment(factory)
    month_start, _month_end = canonical_month_bounds(MONTH)
    as_of = month_start + 20 * DAY

    for ordinal in range(20, 26):
        _seed_member(
            factory,
            env,
            ordinal=ordinal,
            report_date=month_start + 10 * DAY,
            severity="Major",
        )
    _seed_member(
        factory,
        env,
        ordinal=26,
        report_date=month_start + DAY,
        severity="Major",
    )

    cohort = _cohort(
        _calculate(factory, as_of=as_of),
        severity="major",
        required_percentage=85_000_000,
    )

    assert cohort.denominator == 7
    assert cohort.active_within_count == 6
    assert cohort.active_exceeded_count == 1
    assert cohort.lower_bound_met_count == 0
    assert cohort.best_possible_met_count == 6
    assert cohort.state == "at_risk"


def test_terminal_lower_bound_can_make_nonfinal_cohort_currently_met_t026(
    initialized_database,
) -> None:
    factory = _factory(initialized_database)
    env = _environment(factory)
    month_start, _month_end = canonical_month_bounds(MONTH)
    report_date = month_start + 10 * DAY
    as_of = month_start + 20 * DAY

    for ordinal in range(30, 36):
        _seed_member(
            factory,
            env,
            ordinal=ordinal,
            report_date=report_date,
            severity="Major",
            resolved_at=report_date + 5 * DAY,
        )
    _seed_member(
        factory,
        env,
        ordinal=36,
        report_date=report_date,
        severity="Major",
    )

    cohort = _cohort(
        _calculate(factory, as_of=as_of),
        severity="major",
        required_percentage=85_000_000,
    )

    assert cohort.denominator == 7
    assert cohort.terminal_met_count == 6
    assert cohort.active_within_count == 1
    assert cohort.lower_bound_met_count == 6
    assert cohort.best_possible_met_count == 7
    assert cohort.state == "currently_met"
    assert cohort.is_final is False


def test_best_possible_failure_is_breached_before_month_closes_t027(
    initialized_database,
) -> None:
    factory = _factory(initialized_database)
    env = _environment(factory)
    month_start, _month_end = canonical_month_bounds(MONTH)
    report_date = month_start + DAY
    as_of = month_start + 20 * DAY

    _seed_member(
        factory,
        env,
        ordinal=40,
        report_date=report_date,
        severity="Critical",
    )

    cohort = _cohort(
        _calculate(factory, as_of=as_of),
        severity="critical",
        required_percentage=100_000_000,
    )

    assert cohort.active_exceeded_count == 1
    assert cohort.best_possible_met_count == 0
    assert cohort.state == "breached"
    assert cohort.is_final is False


def test_final_met_requires_closed_month_and_zero_active_members_t028(
    initialized_database,
) -> None:
    factory = _factory(initialized_database)
    env = _environment(factory)
    month_start, month_end = canonical_month_bounds(MONTH)
    report_date = month_start + 10 * DAY
    resolved_at = report_date + 5 * DAY

    _seed_member(
        factory,
        env,
        ordinal=50,
        report_date=report_date,
        severity="Critical",
        resolved_at=resolved_at,
    )

    open_cohort = _cohort(
        _calculate(factory, as_of=month_end - 1),
        severity="critical",
        required_percentage=100_000_000,
    )
    assert open_cohort.state == "currently_met"
    assert open_cohort.is_final is False

    final_cohort = _cohort(
        _calculate(factory, as_of=month_end + DAY),
        severity="critical",
        required_percentage=100_000_000,
    )
    assert final_cohort.state == "final_met"
    assert final_cohort.is_final is True

    _seed_member(
        factory,
        env,
        ordinal=51,
        report_date=month_start + 27 * DAY,
        severity="Critical",
    )
    closed_with_active = _cohort(
        _calculate(factory, as_of=month_end + DAY),
        severity="critical",
        required_percentage=100_000_000,
    )
    assert closed_with_active.active_within_count == 1
    assert closed_with_active.state == "pending"
    assert closed_with_active.is_final is False


def test_daily_or_weekly_position_does_not_redefine_monthly_cohort_t029(
    initialized_database,
) -> None:
    factory = _factory(initialized_database)
    env = _environment(factory)
    month_start, month_end = canonical_month_bounds(MONTH)

    early = _seed_member(
        factory,
        env,
        ordinal=60,
        report_date=month_start + DAY,
        severity="Critical",
    )
    late = _seed_member(
        factory,
        env,
        ordinal=61,
        report_date=month_start + 24 * DAY,
        severity="Critical",
    )

    result = _calculate(factory, as_of=month_end - 1)
    cohort = _cohort(
        result,
        severity="critical",
        required_percentage=100_000_000,
    )
    member_keys = {
        member.service_request_id: member.cohort_key.opaque_key
        for member in result.members
    }

    assert member_keys[early] == cohort.cohort_key
    assert member_keys[late] == cohort.cohort_key
    assert cohort.calendar_month == MONTH
    assert cohort.timezone == "America/Guayaquil"
    assert cohort.denominator == 2
