from __future__ import annotations

from soma.foundation.identifiers import new_uuid4, utc_epoch_seconds
from soma.foundation.jobs import DurableJobCoordinator, JobTypeRegistry
from soma.foundation.persistence.uow import ReadSnapshot, UnitOfWork
from soma.ticket_import.commands.publish_staged_run import PublishStagedImportRunService
from soma.ticket_import.jobs import (
    SR_REAPPEARANCE_JOB_TYPE,
    TICKET_IMPORT_JOB_CONTRACTS,
    derive_source_check_dedupe_key,
)
from soma.ticket_import.reconciliation.engine import LogicalRow, row_logical_sha256
from soma.ticket_import.reconciliation.staged import verify_staged_logical_run
from soma.ticket_import.repositories.observations import (
    NormalizedObservationEvidence,
    SourceObservationRepository,
)


def _factory(initialized_database):
    database_path, factory_builder = initialized_database
    return factory_builder(database_path)


def _profiles() -> dict[str, str]:
    return {
        "source_profile_id": "ADVANCED_SEARCH_SR_V1",
        "header_registry_id": "ADVANCED_SEARCH_HEADERS_V1",
        "vocabulary_registry_id": "ADVANCED_SEARCH_VOCAB_V1",
        "parser_profile_id": "ADVANCED_SEARCH_PARSER_V1",
    }


def _candidate(chronology: int) -> dict[str, object]:
    return {
        "filename": "candidate.xlsx",
        "stable_size_bytes": 100,
        "stable_mtime_ns": 1,
        "source_chronology_kind": "embedded_filename_timestamp_utc",
        "source_chronology_value": chronology,
        "locator_fingerprint": "a" * 64,
    }


def _seed_validating_run(uow: UnitOfWork, run_id: str, chronology: int) -> None:
    profiles = _profiles()
    candidate = _candidate(chronology)
    uow.connection.execute(
        "INSERT INTO import_runs(import_run_id,source_family,invocation_kind,source_profile_id,"
        "header_registry_id,vocabulary_registry_id,parser_profile_id,candidate_filename,"
        "candidate_file_size_bytes,candidate_stable_mtime_ns,candidate_chronology_kind,"
        "candidate_chronology_value,run_state,started_at_utc,revision) "
        "VALUES (?,'advanced_search_sr','manual',?,?,?,?,?,?,?,?,?,'validating',0,1)",
        (
            run_id,
            profiles["source_profile_id"],
            profiles["header_registry_id"],
            profiles["vocabulary_registry_id"],
            profiles["parser_profile_id"],
            candidate["filename"],
            candidate["stable_size_bytes"],
            candidate["stable_mtime_ns"],
            candidate["source_chronology_kind"],
            candidate["source_chronology_value"],
        ),
    )


def _stage_row(uow: UnitOfWork, run_id: str, canonical_sr_no: str | None) -> str:
    if canonical_sr_no is None:
        entity_kind = "invalid_row"
        identity_state = "invalid"
    else:
        entity_kind = "service_request"
        identity_state = "valid"
    logical = LogicalRow(
        identity_state=identity_state,
        entity_kind=entity_kind,
        canonical_primary_id=canonical_sr_no,
        canonical_parent_rfc_no=None,
    )
    staged = SourceObservationRepository.stage_observations(
        uow,
        import_run_id=run_id,
        expected_run_revision=1,
        observations=(
            NormalizedObservationEvidence(
                entity_kind=entity_kind,
                identity_state=identity_state,
                canonical_primary_id=canonical_sr_no,
                canonical_parent_rfc_no=None,
                row_ordinal=1,
                sheet_ordinal=1,
                row_logical_sha256=row_logical_sha256(logical),
                source_row_chronology_utc=None,
                fields=(),
            ),
        ),
    )
    return staged[0].source_observation_id


def _seed_checkpoint_population(
    uow: UnitOfWork,
    *,
    chronology: int,
    fingerprint: str,
    canonical_sr_no: str,
) -> str:
    profiles = _profiles()
    prior_run_id = new_uuid4()
    uow.connection.execute(
        "INSERT INTO import_runs(import_run_id,source_family,invocation_kind,source_profile_id,"
        "header_registry_id,vocabulary_registry_id,parser_profile_id,candidate_filename,"
        "candidate_file_size_bytes,candidate_stable_mtime_ns,candidate_chronology_kind,"
        "candidate_chronology_value,logical_fingerprint_sha256,run_state,started_at_utc,staged_at_utc,"
        "completed_at_utc,revision) VALUES (?,'advanced_search_sr','manual',?,?,?,?,"
        "'prior.xlsx',1,1,'embedded_filename_timestamp_utc',?,?,'accepted',0,1,2,2)",
        (
            prior_run_id,
            profiles["source_profile_id"],
            profiles["header_registry_id"],
            profiles["vocabulary_registry_id"],
            profiles["parser_profile_id"],
            chronology,
            fingerprint,
        ),
    )
    uow.connection.execute(
        "INSERT INTO source_observations(source_observation_id,import_run_id,source_family,entity_kind,"
        "identity_state,canonical_primary_id,row_ordinal,sheet_ordinal,row_logical_sha256,"
        "source_row_chronology_utc,presence_state,recorded_at_utc) VALUES (?,?,'advanced_search_sr',"
        "'service_request','valid',?,1,1,?,NULL,'observed_valid_identity',1)",
        (new_uuid4(), prior_run_id, canonical_sr_no, "e" * 64),
    )
    uow.connection.execute(
        "INSERT INTO import_source_checkpoints(source_family,source_profile_id,"
        "accepted_candidate_chronology_kind,accepted_candidate_chronology_value,"
        "accepted_logical_fingerprint_sha256,accepted_import_run_id,last_checked_at_utc,revision) "
        "VALUES ('advanced_search_sr',?,'embedded_filename_timestamp_utc',?,?,?,2,1)",
        (profiles["source_profile_id"], chronology, fingerprint, prior_run_id),
    )
    return prior_run_id


def _seed_sr(uow: UnitOfWork, sr_no: str) -> str:
    sr_id = new_uuid4()
    uow.connection.execute(
        "INSERT INTO service_requests(service_request_id,official_sr_no,revision,created_at_utc,updated_at_utc) "
        "VALUES (?,?,1,1,1)",
        (sr_id, sr_no),
    )
    return sr_id


def _fingerprint(factory, run_id: str) -> str:
    with ReadSnapshot(factory) as snapshot:
        return verify_staged_logical_run(
            snapshot.connection,
            import_run_id=run_id,
            expected_run_revision=1,
        ).fingerprint.logical_fingerprint_sha256


def _claim(factory, run_id: str, chronology: int):
    profiles = _profiles()
    candidate = _candidate(chronology)
    payload = {
        "source_family": "advanced_search_sr",
        "invocation_kind": "manual",
        "profile_ids": profiles,
        "source_locator": {"kind": "manual_path", "selected_path": r"C:\Imports\candidate.xlsx"},
        "requested_by_command_id": new_uuid4(),
    }
    coordinator = DurableJobCoordinator(factory, JobTypeRegistry(TICKET_IMPORT_JOB_CONTRACTS))
    with UnitOfWork(factory) as uow:
        coordinator.enqueue_or_coalesce(
            uow,
            "ticket_import.source_check",
            1,
            payload,
            derive_source_check_dedupe_key(payload),
        )
    claim = coordinator.claim_next(new_uuid4(), utc_epoch_seconds())
    assert claim is not None
    checkpoint = {
        "phase": "publishing",
        "import_run_id": run_id,
        "run_revision": 1,
        "parser_profile_id": profiles["parser_profile_id"],
        "candidate_identity": candidate,
        "last_committed_batch": None,
    }
    coordinator.checkpoint(claim, checkpoint)
    return claim, checkpoint


def _publish(factory, run_id: str, chronology: int, fingerprint: str):
    claim, checkpoint = _claim(factory, run_id, chronology)
    return PublishStagedImportRunService(factory).publish(
        command_id=new_uuid4(),
        claim=claim,
        import_run_id=run_id,
        expected_run_revision=1,
        profile_ids=_profiles(),
        publishing_checkpoint=checkpoint,
        logical_fingerprint=fingerprint,
    )


def test_equal_chronology_conflict_publishes_without_reappearance_job(initialized_database) -> None:
    factory = _factory(initialized_database)
    run_id = new_uuid4()
    with UnitOfWork(factory) as uow:
        _seed_validating_run(uow, run_id, 10)
        _seed_sr(uow, "12345678")
        _stage_row(uow, run_id, "12345678")
    current_fingerprint = _fingerprint(factory, run_id)
    checkpoint_fingerprint = "f" * 64
    assert current_fingerprint != checkpoint_fingerprint
    with UnitOfWork(factory) as uow:
        _seed_checkpoint_population(
            uow,
            chronology=10,
            fingerprint=checkpoint_fingerprint,
            canonical_sr_no="12345678",
        )

    result = _publish(factory, run_id, 10, current_fingerprint)
    assert result.run_state == "recovery_required"
    with ReadSnapshot(factory) as snapshot:
        assert snapshot.connection.execute(
            "SELECT COUNT(*) FROM durable_jobs WHERE job_type=?",
            (SR_REAPPEARANCE_JOB_TYPE,),
        ).fetchone()[0] == 0


def test_older_recovery_neither_infers_disappearance_nor_queues_reappearance(initialized_database) -> None:
    factory = _factory(initialized_database)
    run_id = new_uuid4()
    missing_sr_no = "87654321"
    with UnitOfWork(factory) as uow:
        _seed_validating_run(uow, run_id, 10)
        _stage_row(uow, run_id, None)
        _seed_sr(uow, missing_sr_no)
    current_fingerprint = _fingerprint(factory, run_id)
    with UnitOfWork(factory) as uow:
        _seed_checkpoint_population(
            uow,
            chronology=20,
            fingerprint="d" * 64,
            canonical_sr_no=missing_sr_no,
        )

    result = _publish(factory, run_id, 10, current_fingerprint)
    assert result.run_state == "recovery_required"
    with ReadSnapshot(factory) as snapshot:
        assert snapshot.connection.execute(
            "SELECT COUNT(*) FROM reconciliation_proposals WHERE import_run_id=? "
            "AND proposal_kind='sr_source_disappearance_review'",
            (run_id,),
        ).fetchone()[0] == 0
        assert snapshot.connection.execute(
            "SELECT COUNT(*) FROM durable_jobs WHERE job_type=?",
            (SR_REAPPEARANCE_JOB_TYPE,),
        ).fetchone()[0] == 0
