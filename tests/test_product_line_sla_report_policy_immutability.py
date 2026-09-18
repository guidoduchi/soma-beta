from __future__ import annotations

from dataclasses import dataclass

from soma.foundation.identifiers import new_uuid4, utc_epoch_seconds
from soma.foundation.jobs import DurableJobCoordinator, JobTypeRegistry
from soma.foundation.persistence.uow import ReadSnapshot, UnitOfWork
from soma.product_line_sla.algorithms.cohort_state import canonical_month_bounds
from soma.product_line_sla.algorithms.individual_sla import IndividualSlaCalculator
from soma.product_line_sla.artifacts.xlsx_report import (
    BoundReportDestination,
    SlaReportXlsxArtifact,
)
from soma.product_line_sla.jobs import PRODUCT_LINE_SLA_JOB_CONTRACTS
from soma.product_line_sla.jobs.report_generation import SlaReportGenerationWorker
from soma.product_line_sla.repositories.reports import ReportRepository
from soma.product_line_sla.services.catalog import ProductLineSlaCatalogService
from soma.product_line_sla.services.classification import ProductLineSlaClassificationService
from soma.product_line_sla.services.policy import ProductLineSlaPolicyService
from soma.product_line_sla.services.report_orchestration import SlaReportOrchestrationService
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


@dataclass(frozen=True)
class _Setup:
    customer_id: str
    cpl_id: str
    service_request_id: str


def _apply_source(factory, service_request_id: str, report_date: int) -> None:
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
                        value=report_date,
                        source_chronology_utc=report_date,
                        precedence_basis="source_chronology",
                        source_observation_field_id=new_uuid4(),
                    ),
                    AcceptedSrFieldDelta(
                        field_key="customer_severity",
                        value_state="usable",
                        value_kind="controlled",
                        value="Critical",
                        source_chronology_utc=report_date,
                        precedence_basis="source_chronology",
                        source_observation_field_id=new_uuid4(),
                    ),
                ),
            ),
        )


def _setup(factory, report_date: int) -> _Setup:
    customer = CustomerReferenceService(factory).create_customer_organization(
        command_id=new_uuid4(),
        name="Report Policy Customer",
    )
    catalog = ProductLineSlaCatalogService(factory)
    product = catalog.create_product_line(
        command_id=new_uuid4(),
        name="Report Policy Product",
    )
    contract = catalog.create_contract(
        command_id=new_uuid4(),
        customer_org_id=customer.customer_org_id,
        name="Report Policy Contract",
        contract_reference="REPORT-POLICY",
    )
    cpl = catalog.create_contract_product_line(
        command_id=new_uuid4(),
        contract_id=contract.target_id,
        product_line_id=product.target_id,
        initial_policy_name="Initial IT Policy",
        initial_template_source="IT_DEFAULT_V1",
    )
    classification = ProductLineSlaClassificationService(factory)
    references = ServiceRequestReferenceService(factory, classification)
    sr = ServiceRequestService(factory).create_manual_service_request(
        command_id=new_uuid4(),
        official_sr_no="99000006",
    )
    references.set_customer(
        command_id=new_uuid4(),
        service_request_id=sr.service_request_id,
        base_revision=1,
        customer_org_id=customer.customer_org_id,
        reason_category="report_policy_customer",
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
        reason_category="report_policy_classification",
    )
    _apply_source(factory, sr.service_request_id, report_date)
    return _Setup(
        customer_id=customer.customer_org_id,
        cpl_id=cpl.target_id,
        service_request_id=sr.service_request_id,
    )


def _complete_report(factory, tmp_path, *, customer_id: str, as_of_utc: int) -> str:
    started = SlaReportOrchestrationService(factory).start_monthly(
        command_id=new_uuid4(),
        calendar_month=MONTH,
        as_of_utc=as_of_utc,
        customer_org_id=customer_id,
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
    SlaReportGenerationWorker(
        factory,
        artifact=artifact,
    ).run_to_completion(claim)
    return str(started["report_attempt_id"])


def _live(factory, service_request_id: str, as_of_utc: int):
    with ReadSnapshot(factory) as snapshot:
        return IndividualSlaCalculator.calculate(
            snapshot.connection,
            service_request_id,
            as_of_utc,
        )


def test_completed_report_remains_immutable_after_policy_revision_t033(
    initialized_database,
    tmp_path,
) -> None:
    factory = _factory(initialized_database)
    month_start, _month_end = canonical_month_bounds(MONTH)
    report_date = month_start + DAY
    as_of_utc = report_date + 4 * DAY
    setup = _setup(factory, report_date)

    before_live = _live(factory, setup.service_request_id, as_of_utc)
    assert before_live.calculation_state == "calculable"
    assert before_live.tier_results[0].individual_state == "active_within"
    old_policy_revision = before_live.policy_revision_id
    assert old_policy_revision is not None

    first_report_id = _complete_report(
        factory,
        tmp_path,
        customer_id=setup.customer_id,
        as_of_utc=as_of_utc,
    )
    with ReadSnapshot(factory) as snapshot:
        first_attempt = ReportRepository.get_attempt(
            snapshot.connection,
            first_report_id,
        )
        assert first_attempt is not None
        assert first_attempt.state == "completed"
        assert first_attempt.snapshot_hash is not None
        first_snapshot_hash = first_attempt.snapshot_hash
        first_semantic = ReportRepository.snapshot_semantic_value(
            snapshot.connection,
            first_report_id,
        )
        assert first_semantic["members"][0]["policy_revision_id"] == old_policy_revision
        assert first_semantic["tiers"][0]["individual_state"] == "active_within"
        assert first_semantic["cohorts"][0]["policy_revision_id"] == old_policy_revision
        first_artifact = (
            first_attempt.artifact_filename,
            first_attempt.artifact_sha256,
            first_attempt.artifact_size_bytes,
            first_attempt.verified_at_utc,
        )

    revised = ProductLineSlaPolicyService(factory).revise_policy(
        command_id=new_uuid4(),
        contract_product_line_id=setup.cpl_id,
        base_revision=1,
        policy_name="Revised NFV Policy",
        reason_category="report_policy_revision",
        template_source="NFV_DEFAULT_V1",
    )
    assert revised.policy_revision_id != old_policy_revision

    after_live = _live(factory, setup.service_request_id, as_of_utc)
    assert after_live.policy_revision_id == revised.policy_revision_id
    assert after_live.tier_results[0].individual_state == "active_exceeded"

    with ReadSnapshot(factory) as snapshot:
        frozen_attempt = ReportRepository.get_attempt(
            snapshot.connection,
            first_report_id,
        )
        assert frozen_attempt is not None
        assert frozen_attempt.state == "completed"
        assert frozen_attempt.snapshot_hash == first_snapshot_hash
        assert (
            frozen_attempt.artifact_filename,
            frozen_attempt.artifact_sha256,
            frozen_attempt.artifact_size_bytes,
            frozen_attempt.verified_at_utc,
        ) == first_artifact
        frozen_semantic = ReportRepository.snapshot_semantic_value(
            snapshot.connection,
            first_report_id,
        )
        assert frozen_semantic == first_semantic
        assert ReportRepository.snapshot_hash(
            snapshot.connection,
            first_report_id,
        ) == first_snapshot_hash

    second_report_id = _complete_report(
        factory,
        tmp_path,
        customer_id=setup.customer_id,
        as_of_utc=as_of_utc,
    )
    with ReadSnapshot(factory) as snapshot:
        second = ReportRepository.get_attempt(snapshot.connection, second_report_id)
        assert second is not None
        assert second.state == "completed"
        assert second.snapshot_hash is not None
        assert second.snapshot_hash != first_snapshot_hash
        second_semantic = ReportRepository.snapshot_semantic_value(
            snapshot.connection,
            second_report_id,
        )
        assert (
            second_semantic["members"][0]["policy_revision_id"]
            == revised.policy_revision_id
        )
        assert second_semantic["tiers"][0]["individual_state"] == "active_exceeded"
        assert (
            second_semantic["cohorts"][0]["policy_revision_id"]
            == revised.policy_revision_id
        )

    assert second_report_id != first_report_id
