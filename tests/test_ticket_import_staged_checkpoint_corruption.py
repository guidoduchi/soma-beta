from __future__ import annotations

import pytest

from soma.foundation.errors import IntegrityFailure
from soma.foundation.identifiers import new_uuid4
from soma.foundation.persistence.uow import ReadSnapshot, UnitOfWork
from soma.ticket_import.reconciliation.staged import verify_staged_logical_run


def _factory(initialized_database):
    database_path, factory_for_path = initialized_database
    return factory_for_path(database_path)


def _seed_current_run(uow: UnitOfWork, run_id: str) -> None:
    uow.connection.execute(
        "INSERT INTO import_runs("
        "import_run_id,source_family,invocation_kind,source_profile_id,header_registry_id,vocabulary_registry_id,parser_profile_id,"
        "candidate_filename,candidate_file_size_bytes,candidate_stable_mtime_ns,candidate_chronology_kind,candidate_chronology_value,"
        "run_state,started_at_utc,revision) VALUES (?,'rfc_enhanced','manual','RFC_ENHANCED_V1','RFC_HEADERS_V1',"
        "'RFC_VOCAB_V1','RFC_PARSER_V1','candidate.xlsx',100,1,'filesystem_mtime_ns',10,'validating',0,1)",
        (run_id,),
    )


def _seed_checkpoint(uow: UnitOfWork, *, prior_run_id: str, fingerprint: str) -> None:
    uow.connection.execute(
        "INSERT INTO import_runs("
        "import_run_id,source_family,invocation_kind,source_profile_id,header_registry_id,vocabulary_registry_id,parser_profile_id,"
        "candidate_filename,candidate_file_size_bytes,candidate_stable_mtime_ns,candidate_chronology_kind,candidate_chronology_value,"
        "logical_fingerprint_sha256,run_state,started_at_utc,staged_at_utc,completed_at_utc,revision) "
        "VALUES (?,'rfc_enhanced','manual','RFC_ENHANCED_V1','RFC_HEADERS_V1','RFC_VOCAB_V1','RFC_PARSER_V1',"
        "'accepted.xlsx',100,1,'filesystem_mtime_ns',9,?,'accepted',0,1,2,2)",
        (prior_run_id, fingerprint),
    )
    uow.connection.execute(
        "INSERT INTO import_source_checkpoints("
        "source_family,source_profile_id,accepted_candidate_chronology_kind,accepted_candidate_chronology_value,"
        "accepted_logical_fingerprint_sha256,accepted_import_run_id,last_checked_at_utc,revision) "
        "VALUES ('rfc_enhanced','RFC_ENHANCED_V1','filesystem_mtime_ns',9,?,?,2,1)",
        (fingerprint, prior_run_id),
    )


def test_nonhex_checkpoint_fingerprint_fails_closed(initialized_database) -> None:
    factory = _factory(initialized_database)
    run_id = new_uuid4()
    with UnitOfWork(factory) as uow:
        _seed_current_run(uow, run_id)
        _seed_checkpoint(uow, prior_run_id=new_uuid4(), fingerprint="g" * 64)

    with ReadSnapshot(factory) as snapshot:
        with pytest.raises(IntegrityFailure, match="lowercase SHA-256 hex"):
            verify_staged_logical_run(
                snapshot.connection,
                import_run_id=run_id,
                expected_run_revision=1,
            )


def test_noncanonical_checkpoint_import_run_identity_fails_closed(initialized_database) -> None:
    factory = _factory(initialized_database)
    run_id = new_uuid4()
    with UnitOfWork(factory) as uow:
        _seed_current_run(uow, run_id)
        _seed_checkpoint(uow, prior_run_id="legacy-run-id", fingerprint="a" * 64)

    with ReadSnapshot(factory) as snapshot:
        with pytest.raises(IntegrityFailure, match="accepted import-run identity"):
            verify_staged_logical_run(
                snapshot.connection,
                import_run_id=run_id,
                expected_run_revision=1,
            )
