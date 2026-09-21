from __future__ import annotations

import json

from soma.foundation.identifiers import new_uuid4
from soma.foundation.persistence.uow import UnitOfWork
from soma.ticket_import.commands.finalize_run import ImportRunFinalizationService
from soma.ticket_import.repositories.runs import ImportRunRepository


_FINGERPRINT = "5" * 64


def _factory(initialized_database):
    database_path, factory_for_path = initialized_database
    return factory_for_path(database_path)


def _seed(factory) -> str:
    prior_run_id = new_uuid4()
    candidate_run_id = new_uuid4()
    with UnitOfWork(factory) as uow:
        uow.connection.execute(
            "INSERT INTO import_runs("
            "import_run_id,source_family,invocation_kind,source_profile_id,header_registry_id,vocabulary_registry_id,parser_profile_id,"
            "candidate_filename,candidate_file_size_bytes,candidate_stable_mtime_ns,candidate_chronology_kind,candidate_chronology_value,"
            "logical_fingerprint_sha256,run_state,started_at_utc,staged_at_utc,completed_at_utc,revision"
            ") VALUES (?, 'rfc_enhanced','automatic','RFC_ENHANCED_V1','RFC_HEADERS_V1','RFC_VOCAB_V1','RFC_PARSER_V1',"
            "'prior.xlsx',100,100,'filesystem_mtime_ns',1000,?,'accepted',1,2,3,1)",
            (prior_run_id, _FINGERPRINT),
        )
        uow.connection.execute(
            "INSERT INTO import_source_checkpoints("
            "source_family,source_profile_id,accepted_candidate_chronology_kind,accepted_candidate_chronology_value,"
            "accepted_logical_fingerprint_sha256,accepted_import_run_id,last_checked_at_utc,revision"
            ") VALUES ('rfc_enhanced','RFC_ENHANCED_V1','filesystem_mtime_ns',1000,?,?,3,1)",
            (_FINGERPRINT, prior_run_id),
        )
        uow.connection.execute(
            "INSERT INTO import_runs("
            "import_run_id,source_family,invocation_kind,source_profile_id,header_registry_id,vocabulary_registry_id,parser_profile_id,"
            "candidate_filename,candidate_file_size_bytes,candidate_stable_mtime_ns,candidate_chronology_kind,candidate_chronology_value,"
            "logical_fingerprint_sha256,run_state,started_at_utc,staged_at_utc,revision"
            ") VALUES (?, 'rfc_enhanced','automatic','RFC_ENHANCED_V1','RFC_HEADERS_V1','RFC_VOCAB_V1','RFC_PARSER_V1',"
            "'candidate.xlsx',100,200,'filesystem_mtime_ns',2000,?,'noop_pending_checkpoint',4,5,1)",
            (candidate_run_id, _FINGERPRINT),
        )
    return candidate_run_id


def test_checkpoint_replay_uses_exact_committed_result_without_run_reads(initialized_database, monkeypatch) -> None:
    factory = _factory(initialized_database)
    candidate = _seed(factory)
    service = ImportRunFinalizationService(factory)
    command_id = new_uuid4()
    job_id = new_uuid4()

    first = service.record_newer_identical_source_check(
        command_id=command_id,
        job_id=job_id,
        import_run_id=candidate,
        expected_run_revision=1,
        expected_checkpoint_revision=1,
        chronology_kind="filesystem_mtime_ns",
        chronology_value=2000,
        logical_fingerprint=_FINGERPRINT,
    )
    assert first.replayed is False
    assert first.no_change is False
    assert first.run_state == "noop"
    assert first.run_revision == 2
    assert first.checkpoint_revision == 2

    def forbidden_owner_read(*_args, **_kwargs):
        raise AssertionError("import-run owner state must not be read during committed replay")

    monkeypatch.setattr(ImportRunRepository, "get_checkpoint_transition_run", staticmethod(forbidden_owner_read))
    replay = service.record_newer_identical_source_check(
        command_id=command_id,
        job_id=job_id,
        import_run_id=candidate,
        expected_run_revision=1,
        expected_checkpoint_revision=1,
        chronology_kind="filesystem_mtime_ns",
        chronology_value=2000,
        logical_fingerprint=_FINGERPRINT,
    )
    assert replay.replayed is True
    assert replay.no_change is False
    assert replay.run_state == "noop"
    assert replay.run_revision == 2
    assert replay.checkpoint_revision == 2

    connection = factory.open_authoritative(read_only=True, require_wal=True)
    try:
        stored = connection.execute(
            "SELECT response_schema,response_version,response_json FROM command_receipt_results WHERE command_id=?",
            (command_id,),
        ).fetchone()
        assert tuple(stored[:2]) == ("CheckpointAdvanceResultV1", 1)
        assert json.loads(str(stored[2])) == {
            "checkpoint_revision": 2,
            "import_run_id": candidate,
            "run_revision": 2,
            "run_state": "noop",
            "source_family": "rfc_enhanced",
        }
        assert connection.execute(
            "SELECT COUNT(*) FROM audit_events WHERE command_id=?",
            (command_id,),
        ).fetchone()[0] == 1
    finally:
        connection.close()
