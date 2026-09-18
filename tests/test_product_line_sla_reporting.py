from __future__ import annotations

import pytest

from soma.foundation.identifiers import new_uuid4, utc_epoch_seconds
from soma.foundation.jobs import DurableJobCoordinator, JobTypeRegistry
from soma.foundation.persistence.uow import ReadSnapshot, UnitOfWork
from soma.product_line_sla.algorithms.cohort_state import canonical_month_bounds
from soma.product_line_sla.jobs import PRODUCT_LINE_SLA_JOB_CONTRACTS
from soma.product_line_sla.repositories.reports import ReportRepository
from soma.product_line_sla.services.report_orchestration import (
    SlaReportOrchestrationService,
)
from soma.product_line_sla.services.report_worker import SlaReportWorkerService
from soma.tickets.service_requests import ServiceRequestService

MONTH = "2026-09"


def _factory(initialized_database):
    database_path, factory_builder = initialized_database
    return factory_builder(database_path)


def _start_and_claim(factory):
    month_start, _month_end = canonical_month_bounds(MONTH)
    attempt = SlaReportOrchestrationService(factory).start_monthly(
        command_id=new_uuid4(),
        calendar_month=MONTH,
        as_of_utc=month_start + 1,
        customer_org_id=None,
        destination_request_token="d" * 64,
    )
    jobs = DurableJobCoordinator(
        factory,
        JobTypeRegistry(PRODUCT_LINE_SLA_JOB_CONTRACTS),
    )
    claim = jobs.claim_next(new_uuid4(), utc_epoch_seconds())
    assert claim is not None
    token = "snapshot-generation-test-1"
    jobs.checkpoint(
        claim,
        {
            "phase": "snapshotting",
            "attempt_revision": 1,
            "snapshot_generation_token": token,
            "next_batch_ordinal": 1,
            "pending_command": None,
            "candidate_filename": None,
            "published_artifact": None,
        },
    )
    return attempt, claim, jobs, token


def _member_row(service_request_id: str) -> dict[str, object]:
    return {
        "report_member_snapshot_id": new_uuid4(),
        "member_ordinal": 1,
        "service_request_id": service_request_id,
        "customer_org_id": None,
        "contract_id": None,
        "contract_product_line_id": None,
        "policy_revision_id": None,
        "classification_event_id": None,
        "severity": None,
        "report_date_utc": None,
        "status_class": "active",
        "endpoint_utc": None,
        "suspension_num": 0,
        "suspension_den": 1,
        "elapsed_num": None,
        "elapsed_den": None,
        "calculation_state": "missing_report_date",
        "sla_input_token": "a" * 64,
        "source_report_date_evidence_id": None,
        "source_status_evidence_id": None,
        "source_suspension_evidence_id": None,
        "display_values_json": None,
    }


def test_report_staging_seal_completion_replay_and_immutability_t030_t034_t039(
    initialized_database,
) -> None:
    factory = _factory(initialized_database)
    sr = ServiceRequestService(factory).create_manual_service_request(
        command_id=new_uuid4(),
        official_sr_no="99000001",
    )
    attempt, claim, jobs, token = _start_and_claim(factory)
    report_id = str(attempt["report_attempt_id"])
    worker = SlaReportWorkerService(factory)

    member = _member_row(sr.service_request_id)
    batch_hash = worker.batch_payload_hash(
        member_rows=(member,),
        tier_rows=(),
        cohort_rows=(),
        section_rows=(),
    )
    stage_command = new_uuid4()
    staged = worker.stage_batch(
        command_id=stage_command,
        report_attempt_id=report_id,
        snapshot_generation_token=token,
        batch_ordinal=1,
        batch_payload_sha256=batch_hash,
        expected_attempt_revision=1,
        member_rows=(member,),
    )
    assert staged["snapshot_member_count"] == 1
    assert staged["resulting_attempt_revision"] == 2

    replay = worker.stage_batch(
        command_id=stage_command,
        report_attempt_id=report_id,
        snapshot_generation_token=token,
        batch_ordinal=1,
        batch_payload_sha256=batch_hash,
        expected_attempt_revision=1,
        member_rows=(member,),
    )
    assert replay == staged

    jobs.checkpoint(
        claim,
        {
            "phase": "snapshotting",
            "attempt_revision": 2,
            "snapshot_generation_token": token,
            "next_batch_ordinal": 2,
            "pending_command": None,
            "candidate_filename": None,
            "published_artifact": None,
        },
    )
    with ReadSnapshot(factory) as snapshot:
        snapshot_hash = ReportRepository.snapshot_hash(
            snapshot.connection,
            report_id,
        )

    seal_command = new_uuid4()
    sealed = worker.seal(
        command_id=seal_command,
        report_attempt_id=report_id,
        snapshot_generation_token=token,
        expected_attempt_revision=2,
        final_member_count=1,
        final_cohort_count=0,
        final_section_row_count=0,
        snapshot_hash=snapshot_hash,
    )
    assert sealed["state"] == "ready_to_generate"
    assert sealed["resulting_attempt_revision"] == 3
    assert sealed["snapshot_hash"] == snapshot_hash

    jobs.checkpoint(
        claim,
        {
            "phase": "sealed",
            "attempt_revision": 3,
            "snapshot_generation_token": token,
            "next_batch_ordinal": None,
            "pending_command": None,
            "candidate_filename": None,
            "published_artifact": None,
        },
    )
    generating = worker.mark_generating(
        command_id=new_uuid4(),
        report_attempt_id=report_id,
        expected_attempt_revision=3,
        snapshot_hash=snapshot_hash,
    )
    assert generating["state"] == "generating"

    candidate = f".{report_id}.tmp.xlsx"
    jobs.checkpoint(
        claim,
        {
            "phase": "writing",
            "attempt_revision": 4,
            "snapshot_generation_token": token,
            "next_batch_ordinal": None,
            "pending_command": None,
            "candidate_filename": None,
            "published_artifact": None,
        },
    )
    verifying = worker.mark_verifying(
        command_id=new_uuid4(),
        report_attempt_id=report_id,
        expected_attempt_revision=4,
        snapshot_hash=snapshot_hash,
        candidate_filename=candidate,
    )
    assert verifying["state"] == "verifying"
    assert verifying["candidate_filename"] == candidate

    jobs.checkpoint(
        claim,
        {
            "phase": "verifying",
            "attempt_revision": 5,
            "snapshot_generation_token": token,
            "next_batch_ordinal": None,
            "pending_command": None,
            "candidate_filename": candidate,
            "published_artifact": None,
        },
    )
    completion_command = new_uuid4()
    proof = {
        "report_attempt_id": report_id,
        "snapshot_hash": snapshot_hash,
        "candidate_filename": candidate,
        "artifact_filename": f"SOMA-SLA-{report_id[:8]}.xlsx",
        "artifact_sha256": "e" * 64,
        "artifact_size_bytes": 1234,
        "verified_at_utc": utc_epoch_seconds(),
    }
    completed = worker.complete(
        command_id=completion_command,
        report_attempt_id=report_id,
        expected_attempt_revision=5,
        snapshot_hash=snapshot_hash,
        artifact_completion=proof,
    )
    assert completed["state"] == "completed"
    assert completed["revision"] == 6
    assert completed["snapshot_member_count"] == 1
    assert completed["artifact_sha256"] == "e" * 64

    jobs.complete(claim)

    completion_replay = worker.complete(
        command_id=completion_command,
        report_attempt_id=report_id,
        expected_attempt_revision=5,
        snapshot_hash=snapshot_hash,
        artifact_completion=proof,
    )
    assert completion_replay == completed

    with pytest.raises(Exception):
        with UnitOfWork(factory) as uow:
            uow.connection.execute(
                "DELETE FROM sla_report_member_snapshots WHERE report_attempt_id=?",
                (report_id,),
            )


def test_report_failure_cleans_all_staging_atomically_t032(initialized_database) -> None:
    factory = _factory(initialized_database)
    sr = ServiceRequestService(factory).create_manual_service_request(
        command_id=new_uuid4(),
        official_sr_no="99000002",
    )
    attempt, claim, jobs, token = _start_and_claim(factory)
    report_id = str(attempt["report_attempt_id"])
    worker = SlaReportWorkerService(factory)

    member = _member_row(sr.service_request_id)
    batch_hash = worker.batch_payload_hash(
        member_rows=(member,),
        tier_rows=(),
        cohort_rows=(),
        section_rows=(),
    )
    worker.stage_batch(
        command_id=new_uuid4(),
        report_attempt_id=report_id,
        snapshot_generation_token=token,
        batch_ordinal=1,
        batch_payload_sha256=batch_hash,
        expected_attempt_revision=1,
        member_rows=(member,),
    )

    failed_command = new_uuid4()
    failed = worker.fail(
        command_id=failed_command,
        report_attempt_id=report_id,
        expected_attempt_revision=2,
        failure_code="SLA_REPORT_CONTRIBUTOR_FAILED",
    )
    assert failed["state"] == "failed"
    assert failed["snapshot_member_count"] == 0
    assert failed["snapshot_cohort_count"] == 0
    assert failed["snapshot_section_row_count"] == 0
    assert failed["snapshot_hash"] is None
    assert failed["artifact_filename"] is None
    assert failed["failure_code"] == "SLA_REPORT_CONTRIBUTOR_FAILED"

    replay = worker.fail(
        command_id=failed_command,
        report_attempt_id=report_id,
        expected_attempt_revision=2,
        failure_code="SLA_REPORT_CONTRIBUTOR_FAILED",
    )
    assert replay == failed

    with ReadSnapshot(factory) as snapshot:
        counts = ReportRepository.counts(snapshot.connection, report_id)
        assert counts == (0, 0, 0, 0)

    jobs.fail(claim, "SLA_REPORT_CONTRIBUTOR_FAILED", None)
