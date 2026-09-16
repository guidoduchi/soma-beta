from __future__ import annotations

from soma.foundation.identifiers import new_uuid4, utc_epoch_seconds
from soma.foundation.jobs import DurableJobCoordinator, JobTypeRegistry
from soma.foundation.persistence.uow import UnitOfWork
from soma.ticket_import.jobs import TICKET_IMPORT_JOB_CONTRACTS
from soma.ticket_import.jobs.sr_reappearance import AdvancedSearchSrReappearanceWorker
from soma.tickets.service_requests import ServiceRequestService
from soma.tickets.sr_source_presence import ServiceRequestSourcePresenceRepository


def _factory(initialized_database):
    database_path, factory_builder = initialized_database
    return factory_builder(database_path)


def _published_run(uow, run_id: str, chronology: int) -> None:
    uow.connection.execute(
        "INSERT INTO import_runs(import_run_id,source_family,invocation_kind,source_profile_id,"
        "header_registry_id,vocabulary_registry_id,parser_profile_id,candidate_filename,"
        "candidate_file_size_bytes,candidate_stable_mtime_ns,candidate_chronology_kind,"
        "candidate_chronology_value,logical_fingerprint_sha256,run_state,started_at_utc,"
        "staged_at_utc,revision) VALUES (?,'advanced_search_sr','manual','PROFILE','HEADERS',"
        "'VOCAB','PARSER','source.xlsx',1,1,'embedded_filename_timestamp_utc',?,?,"
        "'staged',1,1,1)",
        (run_id, chronology, f"{chronology:064x}"),
    )


def test_reappearance_worker_closes_warning_and_completes_claim(initialized_database) -> None:
    factory = _factory(initialized_database)
    sr = ServiceRequestService(factory).create_manual_service_request(
        command_id=new_uuid4(),
        official_sr_no="12345678",
    )
    absence_run_id = new_uuid4()
    presence_run_id = new_uuid4()
    source_observation_id = new_uuid4()
    disappearance_command_id = new_uuid4()
    disappearance_event_id = new_uuid4()
    scheduling_command_id = new_uuid4()

    with UnitOfWork(factory) as uow:
        _published_run(uow, absence_run_id, 10)
        _published_run(uow, presence_run_id, 20)
        uow.connection.execute(
            "INSERT INTO source_observations(source_observation_id,import_run_id,source_family,"
            "entity_kind,identity_state,canonical_primary_id,row_ordinal,sheet_ordinal,"
            "row_logical_sha256,source_row_chronology_utc,presence_state,recorded_at_utc) "
            "VALUES (?,?,'advanced_search_sr','service_request','valid','12345678',1,1,?,NULL,"
            "'observed_valid_identity',1)",
            (source_observation_id, presence_run_id, "a" * 64),
        )
        uow.connection.execute(
            "INSERT INTO command_receipts(command_id,command_type,request_hash,target_type,target_id,"
            "committed_at_utc,result_type,result_id) VALUES (?,'AcceptReconciliationProposal',?,"
            "'reconciliation_proposal',?,1,NULL,NULL)",
            (disappearance_command_id, "b" * 64, new_uuid4()),
        )
        uow.connection.execute(
            "INSERT INTO sr_source_presence_events(sr_source_presence_event_id,service_request_id,"
            "source_family,event_kind,prior_presence_event_id,import_run_id,source_observation_id,"
            "prior_source_observation_id,reconciliation_proposal_id,accepted_command_id,recorded_at_utc) "
            "VALUES (?,?,'advanced_search_sr','disappearance_reviewed',NULL,?,NULL,?,?,?,1)",
            (
                disappearance_event_id,
                sr.service_request_id,
                absence_run_id,
                new_uuid4(),
                new_uuid4(),
                disappearance_command_id,
            ),
        )

    coordinator = DurableJobCoordinator(factory, JobTypeRegistry(TICKET_IMPORT_JOB_CONTRACTS))
    payload = {
        "import_run_id": presence_run_id,
        "source_family": "advanced_search_sr",
        "published_run_revision": 1,
        "requested_by_command_id": scheduling_command_id,
    }
    with UnitOfWork(factory) as uow:
        job_id = coordinator.enqueue_or_coalesce(
            uow,
            "ticket_import.sr_reappearance_reconcile",
            1,
            payload,
            presence_run_id,
        )
    claim = coordinator.claim_next(new_uuid4(), utc_epoch_seconds())
    assert claim is not None and claim.job_id == job_id

    result = AdvancedSearchSrReappearanceWorker(factory).run(claim)

    assert result.processed_exact_count == 1
    assert result.confirmed_count == 1
    assert result.no_change_count == 0
    connection = factory.open_authoritative(read_only=True, require_wal=True)
    try:
        state = ServiceRequestSourcePresenceRepository.current(
            connection,
            sr.service_request_id,
            "advanced_search_sr",
        )
        assert state.warning_active is False
        assert state.latest_event_kind == "reappearance_confirmed"
        job = connection.execute(
            "SELECT state,checkpoint_json FROM durable_jobs WHERE job_id=?",
            (job_id,),
        ).fetchone()
        assert str(job[0]) == "completed"
        assert '"processed_exact_count":1' in str(job[1])
        assert connection.execute(
            "SELECT COUNT(*) FROM command_receipts WHERE command_type='ReconcileSrSourceReappearance' "
            "AND target_id=?",
            (source_observation_id,),
        ).fetchone()[0] == 1
        assert connection.execute(
            "SELECT COUNT(*) FROM audit_events WHERE action_type="
            "'ticket.service_request.source_presence_changed' AND target_id=?",
            (sr.service_request_id,),
        ).fetchone()[0] == 1
    finally:
        connection.close()


def test_reappearance_command_id_is_deterministic_and_observation_scoped() -> None:
    values = {
        "job_id": "11111111-1111-4111-8111-111111111111",
        "import_run_id": "22222222-2222-4222-8222-222222222222",
        "canonical_sr_no": "12345678",
        "source_observation_id": "33333333-3333-4333-8333-333333333333",
    }
    first = AdvancedSearchSrReappearanceWorker.derive_command_id(**values)
    assert first == AdvancedSearchSrReappearanceWorker.derive_command_id(**values)
    assert first != AdvancedSearchSrReappearanceWorker.derive_command_id(
        **{**values, "source_observation_id": "44444444-4444-4444-8444-444444444444"}
    )

