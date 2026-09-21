from __future__ import annotations

from soma.foundation.identifiers import new_uuid4
from soma.foundation.persistence.uow import ReadSnapshot, UnitOfWork
from soma.objectives_tasks import AcceptedTaskSchedule, TaskPlanningService
from soma.product_line_sla.algorithms.cohort_state import (
    CanonicalCohortCalculator,
    canonical_month_bounds,
)
from soma.product_line_sla.algorithms.individual_sla import IndividualSlaCalculator
from soma.product_line_sla.services.catalog import ProductLineSlaCatalogService
from soma.product_line_sla.services.classification import (
    ProductLineSlaClassificationService,
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


def _apply_sla_source(
    factory,
    service_request_id: str,
    *,
    report_date_utc: int,
) -> None:
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
                deltas=(
                    AcceptedSrFieldDelta(
                        field_key="report_date",
                        value_state="usable",
                        value_kind="instant",
                        value=report_date_utc,
                        source_chronology_utc=report_date_utc,
                        precedence_basis="source_chronology",
                        source_observation_field_id=new_uuid4(),
                    ),
                    AcceptedSrFieldDelta(
                        field_key="customer_severity",
                        value_state="usable",
                        value_kind="controlled",
                        value="Critical",
                        source_chronology_utc=report_date_utc,
                        precedence_basis="source_chronology",
                        source_observation_field_id=new_uuid4(),
                    ),
                ),
            ),
        )


def _setup_classified_sr(factory, report_date_utc: int):
    customer = CustomerReferenceService(factory).create_customer_organization(
        command_id=new_uuid4(),
        name="Timezone Isolation Customer",
    )
    catalog = ProductLineSlaCatalogService(factory)
    product = catalog.create_product_line(
        command_id=new_uuid4(),
        name="Timezone Isolation Product",
    )
    contract = catalog.create_contract(
        command_id=new_uuid4(),
        customer_org_id=customer.customer_org_id,
        name="Timezone Isolation Contract",
        contract_reference="TZ-ISOLATION",
    )
    cpl = catalog.create_contract_product_line(
        command_id=new_uuid4(),
        contract_id=contract.target_id,
        product_line_id=product.target_id,
        initial_policy_name="Timezone Isolation Policy",
        initial_template_source="IT_DEFAULT_V1",
    )

    classification = ProductLineSlaClassificationService(factory)
    references = ServiceRequestReferenceService(factory, classification)
    sr = ServiceRequestService(factory).create_manual_service_request(
        command_id=new_uuid4(),
        official_sr_no="97400001",
    )
    references.set_customer(
        command_id=new_uuid4(),
        service_request_id=sr.service_request_id,
        base_revision=1,
        customer_org_id=customer.customer_org_id,
        reason_category="timezone_isolation_customer",
    )
    preview = classification.preview_manual(
        service_request_id=sr.service_request_id,
        contract_product_line_id=cpl.target_id,
    )
    classified = classification.classify_service_request(
        command_id=new_uuid4(),
        service_request_id=sr.service_request_id,
        target_contract_product_line_id=cpl.target_id,
        preview_fingerprint=preview.input_fingerprint,
        origin="manual_review",
        reason_category="timezone_isolation_classification",
    )
    assert classified.outcome == "APPLIED"
    _apply_sla_source(
        factory,
        sr.service_request_id,
        report_date_utc=report_date_utc,
    )
    return customer.customer_org_id, sr.service_request_id


def _sla_and_cohort(
    factory,
    *,
    service_request_id: str,
    customer_org_id: str,
    as_of_utc: int,
):
    with ReadSnapshot(factory) as snapshot:
        individual = IndividualSlaCalculator.calculate(
            snapshot.connection,
            service_request_id,
            as_of_utc,
        )
        cohort = CanonicalCohortCalculator.calculate_month(
            snapshot.connection,
            calendar_month=MONTH,
            as_of_utc=as_of_utc,
            customer_scope=customer_org_id,
        )
    return individual, cohort


def test_objective_scheduling_timezone_never_enters_sla_authority_t022(
    initialized_database,
) -> None:
    factory = _factory(initialized_database)
    month_start, month_end = canonical_month_bounds(MONTH)
    report_date_utc = month_start + 2 * DAY
    as_of_utc = report_date_utc + 4 * DAY
    assert as_of_utc < month_end

    customer_org_id, service_request_id = _setup_classified_sr(
        factory,
        report_date_utc,
    )
    before_individual, before_cohort = _sla_and_cohort(
        factory,
        service_request_id=service_request_id,
        customer_org_id=customer_org_id,
        as_of_utc=as_of_utc,
    )
    assert before_individual.report_date_utc == report_date_utc
    assert before_individual.effective_elapsed_numerator_seconds == 4 * DAY
    assert before_individual.effective_elapsed_denominator == 1
    assert before_cohort.calendar_month == MONTH
    assert before_cohort.timezone == "America/Guayaquil"
    assert len(before_cohort.cohorts) == 1
    assert before_cohort.cohorts[0].calendar_month == MONTH
    assert before_cohort.cohorts[0].timezone == "America/Guayaquil"

    # LLD-05 scheduling authority is deliberately adjacent but separate. Link a
    # real task to the same SR and change only its scheduling timezone. The UTC
    # interval is held fixed so the mutation is exclusively a scheduling-timezone
    # change rather than a chronology change.
    task_service = TaskPlanningService(factory)
    schedule_guayaquil = AcceptedTaskSchedule(
        start_utc=as_of_utc + DAY,
        end_utc=as_of_utc + DAY + 3_600,
        scheduling_timezone_iana="America/Guayaquil",
    )
    created = task_service.create_local_task(
        command_id=new_uuid4(),
        local_task_name="Timezone isolation maintenance",
        schedule=schedule_guayaquil,
        service_request_ids=[service_request_id],
    )
    assert created.outcome == "APPLIED"
    assert created.revision == 1

    with ReadSnapshot(factory) as snapshot:
        initial_plan = snapshot.connection.execute(
            "SELECT c.plan_revision_id,c.revision,p.start_utc,p.end_utc,"
            "p.scheduling_timezone_iana "
            "FROM task_plan_current c "
            "JOIN task_plan_revisions p ON p.plan_revision_id=c.plan_revision_id "
            "WHERE c.task_id=?",
            (created.task_id,),
        ).fetchone()
        assert initial_plan is not None
        assert (
            int(initial_plan[1]),
            int(initial_plan[2]),
            int(initial_plan[3]),
            str(initial_plan[4]),
        ) == (
            1,
            schedule_guayaquil.start_utc,
            schedule_guayaquil.end_utc,
            "America/Guayaquil",
        )

    schedule_galapagos = AcceptedTaskSchedule(
        start_utc=schedule_guayaquil.start_utc,
        end_utc=schedule_guayaquil.end_utc,
        scheduling_timezone_iana="Pacific/Galapagos",
    )
    changed = task_service.set_task_plan(
        command_id=new_uuid4(),
        task_id=created.task_id,
        task_revision=1,
        current_plan_revision=1,
        schedule=schedule_galapagos,
        reason_category="timezone_isolation_probe",
    )
    assert changed.outcome == "APPLIED"
    assert changed.revision == 2

    with ReadSnapshot(factory) as snapshot:
        current_plan = snapshot.connection.execute(
            "SELECT c.revision,p.start_utc,p.end_utc,p.scheduling_timezone_iana "
            "FROM task_plan_current c "
            "JOIN task_plan_revisions p ON p.plan_revision_id=c.plan_revision_id "
            "WHERE c.task_id=?",
            (created.task_id,),
        ).fetchone()
        assert current_plan is not None
        assert tuple(current_plan) == (
            2,
            schedule_guayaquil.start_utc,
            schedule_guayaquil.end_utc,
            "Pacific/Galapagos",
        )
        assert snapshot.connection.execute(
            "SELECT COUNT(*) FROM task_plan_revisions WHERE task_id=?",
            (created.task_id,),
        ).fetchone()[0] == 2

    after_individual, after_cohort = _sla_and_cohort(
        factory,
        service_request_id=service_request_id,
        customer_org_id=customer_org_id,
        as_of_utc=as_of_utc,
    )

    # No LLD-05 scheduling field is part of the LLD-03/04 typed SLA input.
    # Therefore all exact calculation evidence, fingerprints and canonical cohort
    # authority must remain identical.
    assert after_individual == before_individual
    assert after_cohort == before_cohort
    assert after_cohort.timezone == "America/Guayaquil"
    assert after_cohort.calendar_month == MONTH
