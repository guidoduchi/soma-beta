from __future__ import annotations

from soma.foundation.identifiers import new_uuid4
from soma.foundation.persistence.uow import UnitOfWork
from soma.ticket_import.queries.proposals import ImportRecoveryQueryService


def _factory(initialized_database):
    database_path, factory_builder = initialized_database
    return factory_builder(database_path)


def _insert_run(
    uow,
    *,
    run_id: str,
    state: str,
    chronology: int,
    fingerprint: str,
    proposal_count: int = 0,
    accepted_count: int = 0,
) -> None:
    completed_at_utc = 1 if state in {"accepted", "rejected", "partially_accepted", "noop", "failed"} else None
    uow.connection.execute(
        "INSERT INTO import_runs(import_run_id,source_family,invocation_kind,source_profile_id,"
        "header_registry_id,vocabulary_registry_id,parser_profile_id,candidate_filename,"
        "candidate_file_size_bytes,candidate_stable_mtime_ns,candidate_chronology_kind,"
        "candidate_chronology_value,logical_fingerprint_sha256,run_state,started_at_utc,staged_at_utc,"
        "completed_at_utc,proposal_count,pending_proposal_count,accepted_proposal_count,rejected_proposal_count,"
        "deferred_proposal_count,revision) VALUES (?,'advanced_search_sr','manual','ADVANCED_SEARCH_SR_V1',"
        "'ADVANCED_SEARCH_HEADERS_V1','ADVANCED_SEARCH_VOCAB_V1','ADVANCED_SEARCH_PARSER_V1','source.xlsx',"
        "1,1,'embedded_filename_timestamp_utc',?,?,?,1,1,?,?,0,?,0,0,1)",
        (run_id, chronology, fingerprint, state, completed_at_utc, proposal_count, accepted_count),
    )


def _insert_checkpoint(uow, *, accepted_run_id: str, chronology: int, fingerprint: str) -> None:
    uow.connection.execute(
        "INSERT INTO import_source_checkpoints(source_family,source_profile_id,"
        "accepted_candidate_chronology_kind,accepted_candidate_chronology_value,"
        "accepted_logical_fingerprint_sha256,accepted_import_run_id,last_checked_at_utc,revision) "
        "VALUES ('advanced_search_sr','ADVANCED_SEARCH_SR_V1','embedded_filename_timestamp_utc',?,?,?,1,1)",
        (chronology, fingerprint, accepted_run_id),
    )


def test_recovery_preview_hides_reject_after_any_accepted_proposal(initialized_database) -> None:
    factory = _factory(initialized_database)
    checkpoint_run_id = new_uuid4()
    recovery_run_id = new_uuid4()

    with UnitOfWork(factory) as uow:
        _insert_run(
            uow,
            run_id=checkpoint_run_id,
            state="accepted",
            chronology=200,
            fingerprint="a" * 64,
        )
        _insert_run(
            uow,
            run_id=recovery_run_id,
            state="recovery_required",
            chronology=200,
            fingerprint="b" * 64,
            proposal_count=1,
            accepted_count=1,
        )
        _insert_checkpoint(
            uow,
            accepted_run_id=checkpoint_run_id,
            chronology=200,
            fingerprint="a" * 64,
        )

    preview = ImportRecoveryQueryService(factory).preview(recovery_run_id)

    assert preview.classification == "equal_chronology_different_content"
    assert preview.allowed_actions == ("defer", "authorize_correction")


def test_recovery_preview_allows_reject_before_any_acceptance(initialized_database) -> None:
    factory = _factory(initialized_database)
    checkpoint_run_id = new_uuid4()
    recovery_run_id = new_uuid4()

    with UnitOfWork(factory) as uow:
        _insert_run(
            uow,
            run_id=checkpoint_run_id,
            state="accepted",
            chronology=200,
            fingerprint="a" * 64,
        )
        _insert_run(
            uow,
            run_id=recovery_run_id,
            state="recovery_required",
            chronology=199,
            fingerprint="b" * 64,
        )
        _insert_checkpoint(
            uow,
            accepted_run_id=checkpoint_run_id,
            chronology=200,
            fingerprint="a" * 64,
        )

    preview = ImportRecoveryQueryService(factory).preview(recovery_run_id)

    assert preview.classification == "older_source"
    assert preview.allowed_actions == ("reject", "defer", "authorize_correction")
