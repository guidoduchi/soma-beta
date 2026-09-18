from __future__ import annotations

from openpyxl import load_workbook

from soma.foundation.identifiers import new_uuid4, utc_epoch_seconds
from soma.foundation.jobs import DurableJobCoordinator, JobTypeRegistry
from soma.foundation.persistence.uow import ReadSnapshot
from soma.product_line_sla.algorithms.cohort_state import canonical_month_bounds
from soma.product_line_sla.artifacts.xlsx_report import (
    BoundReportDestination,
    SlaReportXlsxArtifact,
)
from soma.product_line_sla.jobs import PRODUCT_LINE_SLA_JOB_CONTRACTS
from soma.product_line_sla.jobs.report_generation import SlaReportGenerationWorker
from soma.product_line_sla.repositories.reports import ReportRepository
from soma.product_line_sla.services.report_orchestration import SlaReportOrchestrationService

MONTH = "2026-09"
DESTINATION_TOKEN = "d" * 64


def _factory(initialized_database):
    database_path, factory_builder = initialized_database
    return factory_builder(database_path)


def test_report_worker_writes_verifies_publishes_and_completes_xlsx(
    initialized_database,
    tmp_path,
) -> None:
    factory = _factory(initialized_database)
    month_start, _month_end = canonical_month_bounds(MONTH)
    started = SlaReportOrchestrationService(factory).start_monthly(
        command_id=new_uuid4(),
        calendar_month=MONTH,
        as_of_utc=month_start + 1,
        customer_org_id=None,
        destination_request_token=DESTINATION_TOKEN,
    )
    report_id = str(started["report_attempt_id"])

    jobs = DurableJobCoordinator(
        factory,
        JobTypeRegistry(PRODUCT_LINE_SLA_JOB_CONTRACTS),
    )
    claim = jobs.claim_next(new_uuid4(), utc_epoch_seconds())
    assert claim is not None

    artifact = SlaReportXlsxArtifact(
        factory,
        BoundReportDestination(
            destination_request_token=DESTINATION_TOKEN,
            directory=tmp_path,
        ),
    )
    completed_id = SlaReportGenerationWorker(
        factory,
        artifact=artifact,
    ).run_to_completion(claim)
    assert completed_id == report_id

    with ReadSnapshot(factory) as snapshot:
        attempt = ReportRepository.get_attempt(snapshot.connection, report_id)
        assert attempt is not None
        assert attempt.state == "completed"
        assert attempt.snapshot_hash is not None
        assert attempt.artifact_filename is not None
        assert attempt.artifact_sha256 is not None
        assert attempt.artifact_size_bytes is not None
        assert attempt.artifact_size_bytes > 0
        assert attempt.verified_at_utc is not None
        assert attempt.snapshot_member_count == 0
        assert attempt.snapshot_cohort_count == 0
        assert attempt.snapshot_section_row_count == 0
        final_path = tmp_path / attempt.artifact_filename
        assert final_path.is_file()
        assert final_path.stat().st_size == attempt.artifact_size_bytes

        job = snapshot.connection.execute(
            "SELECT state,claimed_run_id,claim_started_at_utc FROM durable_jobs WHERE job_id=?",
            (claim.job_id,),
        ).fetchone()
        assert tuple(job) == ("completed", None, None)

        checkpoint = snapshot.connection.execute(
            "SELECT checkpoint_json FROM durable_jobs WHERE job_id=?",
            (claim.job_id,),
        ).fetchone()[0]
        assert '"phase":"terminal"' in str(checkpoint)

    workbook = load_workbook(final_path, read_only=True, data_only=True)
    try:
        assert workbook.sheetnames == [
            "_SOMA_Metadata",
            "Members",
            "Tiers",
            "Cohorts",
            "Sections",
        ]
        metadata = dict(
            row
            for row in workbook["_SOMA_Metadata"].iter_rows(min_row=2, values_only=True)
        )
        assert metadata["contract_id"] == "SLA_REPORT_XLSX_V1"
        assert metadata["report_attempt_id"] == report_id
        assert metadata["snapshot_hash"] == attempt.snapshot_hash
        assert metadata["represented_content_sha256"] == attempt.snapshot_hash
        assert metadata["member_count"] == 0
        assert metadata["cohort_count"] == 0
        assert metadata["section_count"] == 0
    finally:
        workbook.close()


def test_sealed_snapshot_regeneration_produces_identical_candidate_bytes(
    initialized_database,
    tmp_path,
) -> None:
    factory = _factory(initialized_database)
    month_start, _month_end = canonical_month_bounds(MONTH)
    started = SlaReportOrchestrationService(factory).start_monthly(
        command_id=new_uuid4(),
        calendar_month=MONTH,
        as_of_utc=month_start + 1,
        customer_org_id=None,
        destination_request_token=DESTINATION_TOKEN,
    )
    report_id = str(started["report_attempt_id"])
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
    worker = SlaReportGenerationWorker(factory, artifact=artifact)
    worker.snapshot_and_seal(claim)

    with ReadSnapshot(factory) as snapshot:
        attempt = ReportRepository.get_attempt(snapshot.connection, report_id)
        assert attempt is not None
        assert attempt.state == "ready_to_generate"
        assert attempt.snapshot_hash is not None
        snapshot_hash = attempt.snapshot_hash

    candidate = artifact.write_candidate(
        report_attempt_id=report_id,
        snapshot_hash=snapshot_hash,
        destination_request_token=DESTINATION_TOKEN,
    )
    first_path = tmp_path / candidate
    first_bytes = first_path.read_bytes()
    first_path.unlink()

    second = artifact.write_candidate(
        report_attempt_id=report_id,
        snapshot_hash=snapshot_hash,
        destination_request_token=DESTINATION_TOKEN,
        candidate_filename=candidate,
    )
    assert second == candidate
    assert (tmp_path / second).read_bytes() == first_bytes
