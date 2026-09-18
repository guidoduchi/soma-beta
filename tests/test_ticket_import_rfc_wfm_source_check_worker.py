from __future__ import annotations

import os

import pytest
from openpyxl import Workbook

from soma.foundation.identifiers import new_uuid4, utc_epoch_seconds
from soma.foundation.jobs import DurableJobCoordinator, JobTypeRegistry
from soma.ticket_import.commands.start_source_check import StartTicketSourceImportCheckService
from soma.ticket_import.jobs import TICKET_IMPORT_JOB_CONTRACTS
from soma.ticket_import.jobs.source_check import TicketImportSourceCheckWorker
from soma.ticket_import.parsing.discovery import (
    discover_rfc_enhanced_manual,
    discover_wfm_service_provider_manual,
)


def _factory(initialized_database):
    database_path, factory_builder = initialized_database
    return factory_builder(database_path)


def _save(path, rows) -> None:
    workbook = Workbook()
    sheet = workbook.active
    for row in rows:
        sheet.append(row)
    workbook.save(path)


def _claim(factory, job_id: str):
    coordinator = DurableJobCoordinator(factory, JobTypeRegistry(TICKET_IMPORT_JOB_CONTRACTS))
    claim = coordinator.claim_next(new_uuid4(), utc_epoch_seconds())
    assert claim is not None
    assert claim.job_id == job_id
    return claim


@pytest.mark.skipif(os.name != "nt", reason="manual import transport requires a drive-absolute local Windows path")
def test_manual_rfc_source_check_runs_through_durable_worker(
    initialized_database,
    tmp_path,
    monkeypatch,
) -> None:
    path = tmp_path / "operator-selected-rfc.xlsx"
    _save(
        path,
        [
            ["Task ID", "Status", "Summary"],
            ["NC12345678901234", "Implement", "manual RFC worker"],
        ],
    )
    factory = _factory(initialized_database)
    started = StartTicketSourceImportCheckService(factory).start(
        command_id=new_uuid4(),
        source_family="rfc_enhanced",
        invocation_kind="manual",
        selected_path=str(path),
    )
    claim = _claim(factory, started.job_id)
    monkeypatch.setattr(
        "soma.ticket_import.jobs.source_check.discover_rfc_enhanced_manual",
        lambda selected: discover_rfc_enhanced_manual(selected, sleep_fn=lambda _seconds: None),
    )

    import_run_id = TicketImportSourceCheckWorker(factory).run(claim)

    connection = factory.open_authoritative(read_only=True, require_wal=True)
    try:
        run = connection.execute(
            "SELECT source_family,run_state,observed_row_count,valid_identity_count,"
            "proposal_count,pending_proposal_count FROM import_runs WHERE import_run_id=?",
            (import_run_id,),
        ).fetchone()
        assert tuple(run) == ("rfc_enhanced", "waiting_review", 1, 1, 1, 1)
        proposal = connection.execute(
            "SELECT proposal_kind,target_business_id,proposal_state FROM reconciliation_proposals "
            "WHERE import_run_id=?",
            (import_run_id,),
        ).fetchone()
        assert tuple(proposal) == ("rfc_create_or_adopt", "NC12345678901234", "pending")
        assert connection.execute(
            "SELECT state FROM durable_jobs WHERE job_id=?",
            (started.job_id,),
        ).fetchone()[0] == "completed"
        assert connection.execute(
            "SELECT COUNT(*) FROM durable_jobs WHERE job_type='ticket_import.sr_reappearance_reconcile'",
        ).fetchone()[0] == 0
    finally:
        connection.close()


@pytest.mark.skipif(os.name != "nt", reason="manual import transport requires a drive-absolute local Windows path")
def test_manual_wfm_source_check_runs_through_durable_worker(
    initialized_database,
    tmp_path,
    monkeypatch,
) -> None:
    path = tmp_path / "Service Provider Plan Creation20260916120000.xlsx"
    _save(
        path,
        [
            ["RFC No.", "Task No.", "Task Name"],
            ["NC22345678901234", "TK22345678901234", "manual WFM worker"],
        ],
    )
    factory = _factory(initialized_database)
    started = StartTicketSourceImportCheckService(factory).start(
        command_id=new_uuid4(),
        source_family="wfm_service_provider",
        invocation_kind="manual",
        selected_path=str(path),
    )
    claim = _claim(factory, started.job_id)
    monkeypatch.setattr(
        "soma.ticket_import.jobs.source_check.discover_wfm_service_provider_manual",
        lambda selected: discover_wfm_service_provider_manual(selected, sleep_fn=lambda _seconds: None),
    )

    import_run_id = TicketImportSourceCheckWorker(factory).run(claim)

    connection = factory.open_authoritative(read_only=True, require_wal=True)
    try:
        run = connection.execute(
            "SELECT source_family,run_state,observed_row_count,valid_identity_count,"
            "proposal_count,pending_proposal_count FROM import_runs WHERE import_run_id=?",
            (import_run_id,),
        ).fetchone()
        assert tuple(run) == ("wfm_service_provider", "waiting_review", 1, 1, 2, 2)
        proposals = connection.execute(
            "SELECT proposal_kind,target_business_id,proposal_state FROM reconciliation_proposals "
            "WHERE import_run_id=? ORDER BY proposal_kind",
            (import_run_id,),
        ).fetchall()
        assert [tuple(row) for row in proposals] == [
            ("wfm_create_or_adopt", "TK22345678901234", "pending"),
            ("wfm_provisional_rfc", "NC22345678901234", "pending"),
        ]
        assert connection.execute(
            "SELECT state FROM durable_jobs WHERE job_id=?",
            (started.job_id,),
        ).fetchone()[0] == "completed"
        assert connection.execute(
            "SELECT COUNT(*) FROM durable_jobs WHERE job_type='ticket_import.sr_reappearance_reconcile'",
        ).fetchone()[0] == 0
    finally:
        connection.close()
