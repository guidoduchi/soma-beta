from __future__ import annotations

from soma.foundation.identifiers import new_uuid4
from soma.foundation.persistence.uow import UnitOfWork
from soma.ticket_import.commands.recovery import ResolveImportRecoveryService
from soma.ticket_import.repositories.proposals import ProposalRepository


def _factory(initialized_database):
    database_path, factory_builder = initialized_database
    return factory_builder(database_path)


def _seed_recovery_required_run(factory) -> str:
    checkpoint_run_id = new_uuid4()
    recovery_run_id = new_uuid4()
    with UnitOfWork(factory) as uow:
        uow.connection.execute(
            "INSERT INTO import_runs(import_run_id,source_family,invocation_kind,source_profile_id,"
            "header_registry_id,vocabulary_registry_id,parser_profile_id,candidate_filename,"
            "candidate_file_size_bytes,candidate_stable_mtime_ns,candidate_chronology_kind,"
            "candidate_chronology_value,logical_fingerprint_sha256,run_state,started_at_utc,"
            "staged_at_utc,completed_at_utc,revision) VALUES "
            "(?,'advanced_search_sr','manual','ADVANCED_SEARCH_SR_V1','ADVANCED_SEARCH_HEADERS_V1',"
            "'ADVANCED_SEARCH_VOCAB_V1','ADVANCED_SEARCH_PARSER_V1','checkpoint.xlsx',1,1,"
            "'embedded_filename_timestamp_utc',20,?,'accepted',1,1,1,3)",
            (checkpoint_run_id, "a" * 64),
        )
        uow.connection.execute(
            "INSERT INTO import_source_checkpoints(source_family,source_profile_id,"
            "accepted_candidate_chronology_kind,accepted_candidate_chronology_value,"
            "accepted_logical_fingerprint_sha256,accepted_import_run_id,last_checked_at_utc,revision) "
            "VALUES ('advanced_search_sr','ADVANCED_SEARCH_SR_V1','embedded_filename_timestamp_utc',"
            "20,?,?,1,1)",
            ("a" * 64, checkpoint_run_id),
        )
        uow.connection.execute(
            "INSERT INTO import_runs(import_run_id,source_family,invocation_kind,source_profile_id,"
            "header_registry_id,vocabulary_registry_id,parser_profile_id,candidate_filename,"
            "candidate_file_size_bytes,candidate_stable_mtime_ns,candidate_chronology_kind,"
            "candidate_chronology_value,logical_fingerprint_sha256,run_state,started_at_utc,"
            "staged_at_utc,revision) VALUES "
            "(?,'advanced_search_sr','recovery','ADVANCED_SEARCH_SR_V1','ADVANCED_SEARCH_HEADERS_V1',"
            "'ADVANCED_SEARCH_VOCAB_V1','ADVANCED_SEARCH_PARSER_V1','recovery.xlsx',1,1,"
            "'embedded_filename_timestamp_utc',10,?,'recovery_required',1,1,2)",
            (recovery_run_id, "b" * 64),
        )
    return recovery_run_id


def test_public_recovery_request_replays_before_later_run_state_reads(initialized_database) -> None:
    factory = _factory(initialized_database)
    recovery_run_id = _seed_recovery_required_run(factory)
    with UnitOfWork(factory) as uow:
        run = ProposalRepository.get_run(uow.connection, recovery_run_id)
        fingerprint = ProposalRepository.recovery_review_fingerprint(uow.connection, run)

    command_id = new_uuid4()
    service = ResolveImportRecoveryService(factory)
    first = service.resolve(
        command_id=command_id,
        import_run_id=recovery_run_id,
        review_fingerprint=fingerprint,
        decision="reject",
        reason_category="invalid_recovery_source",
    )
    assert first.run_state == "rejected"
    assert first.run_revision == 3
    assert first.replayed is False

    replay = service.resolve(
        command_id=command_id,
        import_run_id=recovery_run_id,
        review_fingerprint=fingerprint,
        decision="reject",
        reason_category="invalid_recovery_source",
    )
    assert replay == type(replay)(
        import_run_id=first.import_run_id,
        review_ordinal=first.review_ordinal,
        decision=first.decision,
        run_state=first.run_state,
        run_revision=first.run_revision,
        replayed=True,
    )

    connection = factory.open_authoritative(read_only=True, require_wal=True)
    try:
        state = connection.execute(
            "SELECT run_state,revision FROM import_runs WHERE import_run_id=?",
            (recovery_run_id,),
        ).fetchone()
        assert tuple(state) == ("rejected", 3)
        assert connection.execute(
            "SELECT COUNT(*) FROM import_recovery_reviews WHERE import_run_id=?",
            (recovery_run_id,),
        ).fetchone()[0] == 1
    finally:
        connection.close()
