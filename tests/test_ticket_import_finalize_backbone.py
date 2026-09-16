from __future__ import annotations

from soma.foundation.identifiers import new_uuid4
from soma.foundation.persistence.uow import UnitOfWork
from soma.ticket_import.commands.finalize_run import ImportRunFinalizationService
from soma.ticket_import.commands.recovery import ResolveImportRecoveryService
from soma.ticket_import.repositories.proposals import ProposalRepository


def _factory(initialized_database):
    database_path, factory_builder = initialized_database
    return factory_builder(database_path)


def _staged_run(uow, run_id: str, chronology: int) -> None:
    uow.connection.execute(
        "INSERT INTO import_runs(import_run_id,source_family,invocation_kind,source_profile_id,"
        "header_registry_id,vocabulary_registry_id,parser_profile_id,candidate_filename,"
        "candidate_file_size_bytes,candidate_stable_mtime_ns,candidate_chronology_kind,"
        "candidate_chronology_value,logical_fingerprint_sha256,run_state,started_at_utc,"
        "staged_at_utc,revision) VALUES (?,'advanced_search_sr','manual','ADVANCED_SEARCH_SR_V1',"
        "'ADVANCED_SEARCH_HEADERS_V1','ADVANCED_SEARCH_VOCAB_V1','ADVANCED_SEARCH_PARSER_V1',"
        "'source.xlsx',1,1,'embedded_filename_timestamp_utc',?,?,'staged',1,1,2)",
        (run_id, chronology, f"{chronology:064x}"),
    )


def _checkpoint_and_recovery(
    uow,
    *,
    checkpoint_run_id: str,
    recovery_run_id: str,
    checkpoint_chronology: int,
    recovery_chronology: int,
) -> None:
    _staged_run(uow, checkpoint_run_id, checkpoint_chronology)
    uow.connection.execute(
        "UPDATE import_runs SET run_state='accepted',completed_at_utc=1,revision=revision+1 "
        "WHERE import_run_id=?",
        (checkpoint_run_id,),
    )
    uow.connection.execute(
        "INSERT INTO import_source_checkpoints(source_family,source_profile_id,"
        "accepted_candidate_chronology_kind,accepted_candidate_chronology_value,"
        "accepted_logical_fingerprint_sha256,accepted_import_run_id,last_checked_at_utc,revision) "
        "VALUES ('advanced_search_sr','ADVANCED_SEARCH_SR_V1','embedded_filename_timestamp_utc',"
        "?,?,?,?,1)",
        (checkpoint_chronology, f"{checkpoint_chronology:064x}", checkpoint_run_id, 1),
    )
    uow.connection.execute(
        "INSERT INTO import_runs(import_run_id,source_family,invocation_kind,source_profile_id,"
        "header_registry_id,vocabulary_registry_id,parser_profile_id,candidate_filename,"
        "candidate_file_size_bytes,candidate_stable_mtime_ns,candidate_chronology_kind,"
        "candidate_chronology_value,logical_fingerprint_sha256,run_state,started_at_utc,"
        "staged_at_utc,revision) VALUES (?,'advanced_search_sr','recovery','ADVANCED_SEARCH_SR_V1',"
        "'ADVANCED_SEARCH_HEADERS_V1','ADVANCED_SEARCH_VOCAB_V1','ADVANCED_SEARCH_PARSER_V1',"
        "'recovery.xlsx',1,1,'embedded_filename_timestamp_utc',?,?,'recovery_required',1,1,2)",
        (recovery_run_id, recovery_chronology, "f" * 64),
    )


def _authorize_recovery(factory, recovery_run_id: str) -> str:
    with UnitOfWork(factory) as uow:
        run = ProposalRepository.get_run(uow.connection, recovery_run_id)
        fingerprint = ProposalRepository.recovery_review_fingerprint(uow.connection, run)
    result = ResolveImportRecoveryService(factory).resolve(
        command_id=new_uuid4(),
        import_run_id=recovery_run_id,
        expected_run_revision=2,
        expected_checkpoint_revision=1,
        review_fingerprint=fingerprint,
        decision="authorize_correction",
        reason_category="operator_verified_recovery",
    )
    assert result.decision == "authorized"
    assert result.run_revision == 2
    return fingerprint


def test_finalize_regular_runs_establishes_and_advances_checkpoint(initialized_database) -> None:
    factory = _factory(initialized_database)
    first_run_id = new_uuid4()
    second_run_id = new_uuid4()
    with UnitOfWork(factory) as uow:
        _staged_run(uow, first_run_id, 10)
        _staged_run(uow, second_run_id, 20)

    service = ImportRunFinalizationService(factory)
    first_command_id = new_uuid4()
    first = service.finalize_reviewed_run(
        command_id=first_command_id,
        import_run_id=first_run_id,
        expected_run_revision=2,
        expected_checkpoint_revision=None,
    )
    replay = service.finalize_reviewed_run(
        command_id=first_command_id,
        import_run_id=first_run_id,
        expected_run_revision=2,
        expected_checkpoint_revision=None,
    )
    assert first.final_state == "accepted"
    assert first.revision == 3
    assert first.checkpoint_revision == 1
    assert replay.replayed is True

    second = service.finalize_reviewed_run(
        command_id=new_uuid4(),
        import_run_id=second_run_id,
        expected_run_revision=2,
        expected_checkpoint_revision=1,
    )
    assert second.final_state == "accepted"
    assert second.checkpoint_revision == 2

    connection = factory.open_authoritative(read_only=True, require_wal=True)
    try:
        checkpoint = connection.execute(
            "SELECT accepted_import_run_id,accepted_candidate_chronology_value,revision "
            "FROM import_source_checkpoints WHERE source_family='advanced_search_sr'",
        ).fetchone()
        assert tuple(checkpoint) == (second_run_id, 20, 2)
        assert connection.execute(
            "SELECT COUNT(*) FROM audit_events WHERE action_type='ticket_import.run_finalized'",
        ).fetchone()[0] == 2
    finally:
        connection.close()


def test_older_authorized_recovery_finalizes_without_replacing_checkpoint(initialized_database) -> None:
    factory = _factory(initialized_database)
    checkpoint_run_id = new_uuid4()
    recovery_run_id = new_uuid4()
    with UnitOfWork(factory) as uow:
        _checkpoint_and_recovery(
            uow,
            checkpoint_run_id=checkpoint_run_id,
            recovery_run_id=recovery_run_id,
            checkpoint_chronology=20,
            recovery_chronology=10,
        )
    fingerprint = _authorize_recovery(factory, recovery_run_id)

    result = ImportRunFinalizationService(factory).finalize_recovery_run(
        command_id=new_uuid4(),
        import_run_id=recovery_run_id,
        expected_run_revision=2,
        expected_checkpoint_revision=1,
        review_fingerprint=fingerprint,
    )
    assert result.final_state == "accepted"
    assert result.checkpoint_revision == 1

    connection = factory.open_authoritative(read_only=True, require_wal=True)
    try:
        checkpoint = connection.execute(
            "SELECT accepted_import_run_id,revision FROM import_source_checkpoints "
            "WHERE source_family='advanced_search_sr'",
        ).fetchone()
        assert tuple(checkpoint) == (checkpoint_run_id, 1)
        assert connection.execute("SELECT COUNT(*) FROM import_recovery_events").fetchone()[0] == 1
        assert connection.execute(
            "SELECT COUNT(*) FROM durable_jobs WHERE job_type='ticket_import.sr_reappearance_reconcile'",
        ).fetchone()[0] == 0
    finally:
        connection.close()


def test_equal_chronology_recovery_replaces_checkpoint_and_enqueues_reappearance(initialized_database) -> None:
    factory = _factory(initialized_database)
    checkpoint_run_id = new_uuid4()
    recovery_run_id = new_uuid4()
    with UnitOfWork(factory) as uow:
        _checkpoint_and_recovery(
            uow,
            checkpoint_run_id=checkpoint_run_id,
            recovery_run_id=recovery_run_id,
            checkpoint_chronology=20,
            recovery_chronology=20,
        )
    fingerprint = _authorize_recovery(factory, recovery_run_id)
    command_id = new_uuid4()
    service = ImportRunFinalizationService(factory)
    result = service.finalize_recovery_run(
        command_id=command_id,
        import_run_id=recovery_run_id,
        expected_run_revision=2,
        expected_checkpoint_revision=1,
        review_fingerprint=fingerprint,
    )
    replay = service.finalize_recovery_run(
        command_id=command_id,
        import_run_id=recovery_run_id,
        expected_run_revision=2,
        expected_checkpoint_revision=1,
        review_fingerprint=fingerprint,
    )
    assert result.checkpoint_revision == 2
    assert replay.replayed is True

    connection = factory.open_authoritative(read_only=True, require_wal=True)
    try:
        checkpoint = connection.execute(
            "SELECT accepted_import_run_id,accepted_logical_fingerprint_sha256,revision "
            "FROM import_source_checkpoints WHERE source_family='advanced_search_sr'",
        ).fetchone()
        assert tuple(checkpoint) == (recovery_run_id, "f" * 64, 2)
        job = connection.execute(
            "SELECT state FROM durable_jobs WHERE job_type='ticket_import.sr_reappearance_reconcile'",
        ).fetchone()
        assert tuple(job) == ("queued",)
    finally:
        connection.close()


def test_rejected_recovery_supersedes_all_pending_proposals_atomically(initialized_database) -> None:
    factory = _factory(initialized_database)
    checkpoint_run_id = new_uuid4()
    recovery_run_id = new_uuid4()
    observation_id = new_uuid4()
    proposal_id = new_uuid4()
    with UnitOfWork(factory) as uow:
        _checkpoint_and_recovery(
            uow,
            checkpoint_run_id=checkpoint_run_id,
            recovery_run_id=recovery_run_id,
            checkpoint_chronology=20,
            recovery_chronology=10,
        )
        uow.connection.execute(
            "INSERT INTO source_observations(source_observation_id,import_run_id,source_family,entity_kind,"
            "identity_state,canonical_primary_id,row_ordinal,sheet_ordinal,row_logical_sha256,"
            "presence_state,recorded_at_utc) VALUES (?,?,'advanced_search_sr','service_request',"
            "'valid','12345678',1,1,?,'observed_valid_identity',1)",
            (observation_id, recovery_run_id, "1" * 64),
        )
        uow.connection.execute(
            "INSERT INTO reconciliation_proposals(reconciliation_proposal_id,import_run_id,evidence_mode,"
            "source_observation_id,proposal_kind,target_kind,target_business_id,risk_class,"
            "base_state_token_sha256,proposal_fingerprint_sha256,proposal_state,created_at_utc,revision) "
            "VALUES (?,?,'observed_row',?,'sr_create_or_adopt','service_request','12345678','low',"
            "?,?,'pending',1,1)",
            (proposal_id, recovery_run_id, observation_id, "2" * 64, "3" * 64),
        )
        uow.connection.execute(
            "UPDATE import_runs SET observed_row_count=1,valid_identity_count=1,proposal_count=1,"
            "pending_proposal_count=1,revision=revision+1 WHERE import_run_id=?",
            (recovery_run_id,),
        )
        run = ProposalRepository.get_run(uow.connection, recovery_run_id)
        fingerprint = ProposalRepository.recovery_review_fingerprint(uow.connection, run)

    command_id = new_uuid4()
    service = ResolveImportRecoveryService(factory)
    result = service.resolve(
        command_id=command_id,
        import_run_id=recovery_run_id,
        expected_run_revision=3,
        expected_checkpoint_revision=1,
        review_fingerprint=fingerprint,
        decision="reject",
        reason_category="invalid_recovery_source",
    )
    replay = service.resolve(
        command_id=command_id,
        import_run_id=recovery_run_id,
        expected_run_revision=3,
        expected_checkpoint_revision=1,
        review_fingerprint=fingerprint,
        decision="reject",
        reason_category="invalid_recovery_source",
    )
    assert result.run_state == "rejected"
    assert result.run_revision == 4
    assert replay.replayed is True

    connection = factory.open_authoritative(read_only=True, require_wal=True)
    try:
        proposal = connection.execute(
            "SELECT proposal_state,revision FROM reconciliation_proposals "
            "WHERE reconciliation_proposal_id=?",
            (proposal_id,),
        ).fetchone()
        assert tuple(proposal) == ("superseded", 2)
        disposition = connection.execute(
            "SELECT decision,decision_origin FROM proposal_dispositions "
            "WHERE reconciliation_proposal_id=?",
            (proposal_id,),
        ).fetchone()
        assert tuple(disposition) == ("superseded", "recovery")
    finally:
        connection.close()
