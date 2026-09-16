from __future__ import annotations

from openpyxl import Workbook

from soma.foundation.identifiers import new_uuid4, utc_epoch_seconds
from soma.foundation.jobs import DurableJobCoordinator, JobTypeRegistry
from soma.foundation.persistence.uow import UnitOfWork
from soma.foundation.strict_json import canonical_json_bytes
from soma.ticket_import.commands.start_source_check import StartTicketSourceImportCheckService
from soma.ticket_import.jobs import TICKET_IMPORT_JOB_CONTRACTS
from soma.ticket_import.jobs.source_check import TicketImportSourceCheckWorker
from soma.ticket_import.parsing.discovery import discover_advanced_search_automatic


def _factory(initialized_database):
    database_path, factory_builder = initialized_database
    return factory_builder(database_path)


def test_automatic_advanced_search_source_check_reaches_publication(
    initialized_database,
    tmp_path,
    monkeypatch,
) -> None:
    inbox = tmp_path / "advanced-search"
    inbox.mkdir()
    workbook_path = inbox / "Advanced Search(Service Request)20260916080000.xlsx"
    workbook = Workbook()
    sheet = workbook.active
    sheet.append(["SRNo"])
    sheet.append(["12345678"])
    workbook.save(workbook_path)

    factory = _factory(initialized_database)
    setting_command_id = new_uuid4()
    with UnitOfWork(factory) as uow:
        uow.connection.execute(
            "INSERT INTO command_receipts(command_id,command_type,request_hash,target_type,target_id,"
            "committed_at_utc,result_type,result_id) VALUES (?,'WriteSetting',?,'setting',"
            "'advanced_search_import_directory',1,NULL,NULL)",
            (setting_command_id, "a" * 64),
        )
        uow.connection.execute(
            "INSERT INTO setting_values(setting_key,contract_name,contract_version,value_json,revision,"
            "updated_at_utc,command_id) VALUES ('advanced_search_import_directory',"
            "'ADVANCED_SEARCH_IMPORT_DIRECTORY',1,?,1,1,?)",
            (canonical_json_bytes({"path": str(inbox)}).decode("utf-8"), setting_command_id),
        )

    command_id = new_uuid4()
    started = StartTicketSourceImportCheckService(factory).start(
        command_id=command_id,
        source_family="advanced_search_sr",
        invocation_kind="automatic",
        setting_revision=1,
    )
    replay = StartTicketSourceImportCheckService(factory).start(
        command_id=command_id,
        source_family="advanced_search_sr",
        invocation_kind="automatic",
        setting_revision=1,
    )
    assert replay.replayed is True
    assert replay.job_id == started.job_id

    coordinator = DurableJobCoordinator(factory, JobTypeRegistry(TICKET_IMPORT_JOB_CONTRACTS))
    claim = coordinator.claim_next(new_uuid4(), utc_epoch_seconds())
    assert claim is not None and claim.job_id == started.job_id

    monkeypatch.setattr(
        "soma.ticket_import.jobs.source_check.discover_advanced_search_automatic",
        lambda directory: discover_advanced_search_automatic(directory, sleep_fn=lambda _seconds: None),
    )
    import_run_id = TicketImportSourceCheckWorker(factory).run(claim)

    connection = factory.open_authoritative(read_only=True, require_wal=True)
    try:
        run = connection.execute(
            "SELECT run_state,observed_row_count,valid_identity_count,proposal_count,"
            "pending_proposal_count FROM import_runs WHERE import_run_id=?",
            (import_run_id,),
        ).fetchone()
        assert tuple(run) == ("waiting_review", 1, 1, 1, 1)
        assert connection.execute(
            "SELECT state FROM durable_jobs WHERE job_id=?",
            (started.job_id,),
        ).fetchone()[0] == "completed"
        assert connection.execute(
            "SELECT COUNT(*) FROM durable_jobs WHERE job_type="
            "'ticket_import.sr_reappearance_reconcile' AND state='queued'",
        ).fetchone()[0] == 1
        assert connection.execute(
            "SELECT COUNT(*) FROM audit_events WHERE command_id=? AND action_type="
            "'ticket_import.check_started'",
            (command_id,),
        ).fetchone()[0] == 1
    finally:
        connection.close()

