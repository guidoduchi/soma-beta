from __future__ import annotations

import pytest

from soma.foundation.errors import SomaError
from soma.foundation.identifiers import new_uuid4
from soma.foundation.persistence.uow import ReadSnapshot, UnitOfWork
from soma.ticket_import.commands.finalize_run import ImportRunFinalizationService
from soma.ticket_import.repositories.runs import ImportRunRepository


_FINGERPRINT = "5" * 64


def _factory(initialized_database):
    database_path, factory_for_path = initialized_database
    return factory_for_path(database_path)


def _seed(factory):
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
    return prior_run_id, candidate_run_id


def _advance(service, candidate_run_id: str, *, command_id: str | None = None, run_revision: int = 1, checkpoint_revision: int = 1):
    return service.record_newer_identical_source_check(
        command_id=new_uuid4() if command_id is None else command_id,
        job_id=new_uuid4(),
        import_run_id=candidate_run_id,
        expected_run_revision=run_revision,
        expected_checkpoint_revision=checkpoint_revision,
        chronology_kind="filesystem_mtime_ns",
        chronology_value=2000,
        logical_fingerprint=_FINGERPRINT,
    )


def test_newer_identical_advances_checkpoint_and_run_atomically_and_replays(initialized_database) -> None:
    factory = _factory(initialized_database)
    _prior, candidate = _seed(factory)
    service = ImportRunFinalizationService(factory)
    command_id = new_uuid4()
    job_id = new_uuid4()

    result = service.record_newer_identical_source_check(
        command_id=command_id,
        job_id=job_id,
        import_run_id=candidate,
        expected_run_revision=1,
        expected_checkpoint_revision=1,
        chronology_kind="filesystem_mtime_ns",
        chronology_value=2000,
        logical_fingerprint=_FINGERPRINT,
    )
    assert result.run_state == "noop"
    assert result.run_revision == 2
    assert result.checkpoint_revision == 2
    assert result.replayed is False
    assert result.no_change is False

    with ReadSnapshot(factory) as snapshot:
        checkpoint = snapshot.connection.execute(
            "SELECT accepted_import_run_id,accepted_candidate_chronology_value,accepted_logical_fingerprint_sha256,revision "
            "FROM import_source_checkpoints WHERE source_family='rfc_enhanced'"
        ).fetchone()
        assert tuple(checkpoint) == (candidate, 2000, _FINGERPRINT, 2)
        run = snapshot.connection.execute(
            "SELECT run_state,revision,completed_at_utc FROM import_runs WHERE import_run_id=?",
            (candidate,),
        ).fetchone()
        assert run[0] == "noop" and run[1] == 2 and run[2] is not None
        assert snapshot.connection.execute(
            "SELECT COUNT(*) FROM command_receipts WHERE command_id=?", (command_id,)
        ).fetchone()[0] == 1
        assert snapshot.connection.execute(
            "SELECT COUNT(*) FROM audit_events WHERE command_id=? AND action_type='ticket_import.checkpoint_advanced'",
            (command_id,),
        ).fetchone()[0] == 1

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
    assert replay.run_revision == 2
    assert replay.checkpoint_revision == 2
    with ReadSnapshot(factory) as snapshot:
        assert snapshot.connection.execute(
            "SELECT COUNT(*) FROM audit_events WHERE command_id=?", (command_id,)
        ).fetchone()[0] == 1


def test_new_command_on_already_advanced_exact_state_is_semantic_no_change(initialized_database) -> None:
    factory = _factory(initialized_database)
    _prior, candidate = _seed(factory)
    service = ImportRunFinalizationService(factory)
    _advance(service, candidate)

    result = _advance(service, candidate, run_revision=2, checkpoint_revision=2)
    assert result.no_change is True
    assert result.replayed is False
    assert result.run_revision == 2
    assert result.checkpoint_revision == 2
    with ReadSnapshot(factory) as snapshot:
        assert snapshot.connection.execute(
            "SELECT COUNT(*) FROM audit_events WHERE action_type='ticket_import.checkpoint_advanced'"
        ).fetchone()[0] == 1


def test_newer_identical_rejects_stale_or_nonidentical_inputs_before_receipt(initialized_database) -> None:
    factory = _factory(initialized_database)
    _prior, candidate = _seed(factory)
    service = ImportRunFinalizationService(factory)
    command_id = new_uuid4()

    with pytest.raises(SomaError) as failure:
        service.record_newer_identical_source_check(
            command_id=command_id,
            job_id=new_uuid4(),
            import_run_id=candidate,
            expected_run_revision=1,
            expected_checkpoint_revision=1,
            chronology_kind="filesystem_mtime_ns",
            chronology_value=2000,
            logical_fingerprint="6" * 64,
        )
    assert failure.value.code == "IMPORT_RUN_STALE"
    with ReadSnapshot(factory) as snapshot:
        assert snapshot.connection.execute(
            "SELECT 1 FROM command_receipts WHERE command_id=?", (command_id,)
        ).fetchone() is None
        assert snapshot.connection.execute(
            "SELECT run_state FROM import_runs WHERE import_run_id=?", (candidate,)
        ).fetchone()[0] == "noop_pending_checkpoint"


def test_newer_identical_rejects_published_row_authority(initialized_database) -> None:
    factory = _factory(initialized_database)
    _prior, candidate = _seed(factory)
    with UnitOfWork(factory) as uow:
        uow.connection.execute(
            "INSERT INTO source_observations(source_observation_id,import_run_id,source_family,entity_kind,identity_state,"
            "canonical_primary_id,canonical_parent_rfc_no,row_ordinal,sheet_ordinal,row_logical_sha256,source_row_chronology_utc,"
            "presence_state,recorded_at_utc) VALUES (?,?,'rfc_enhanced','rfc','valid','NC20260908000001',NULL,1,1,?,10,"
            "'observed_valid_identity',10)",
            (new_uuid4(), candidate, "7" * 64),
        )
    command_id = new_uuid4()

    with pytest.raises(SomaError) as failure:
        _advance(ImportRunFinalizationService(factory), candidate, command_id=command_id)
    assert failure.value.code == "IMPORT_RUN_STALE"
    with ReadSnapshot(factory) as snapshot:
        assert snapshot.connection.execute(
            "SELECT 1 FROM command_receipts WHERE command_id=?", (command_id,)
        ).fetchone() is None


class _FailAfterCheckpointRuns:
    @staticmethod
    def get_checkpoint_transition_run(reader, import_run_id):
        return ImportRunRepository.get_checkpoint_transition_run(reader, import_run_id)

    @staticmethod
    def has_published_row_authority(reader, import_run_id):
        return ImportRunRepository.has_published_row_authority(reader, import_run_id)

    @staticmethod
    def mark_noop(uow, **kwargs):
        raise SomaError("INJECTED_RUN_FAILURE", "failure after checkpoint update")


def test_run_transition_failure_rolls_back_checkpoint_receipt_and_audit(initialized_database) -> None:
    factory = _factory(initialized_database)
    prior, candidate = _seed(factory)
    service = ImportRunFinalizationService(factory)
    service._runs = _FailAfterCheckpointRuns()
    command_id = new_uuid4()

    with pytest.raises(SomaError) as failure:
        _advance(service, candidate, command_id=command_id)
    assert failure.value.code == "INJECTED_RUN_FAILURE"
    with ReadSnapshot(factory) as snapshot:
        checkpoint = snapshot.connection.execute(
            "SELECT accepted_import_run_id,accepted_candidate_chronology_value,revision "
            "FROM import_source_checkpoints WHERE source_family='rfc_enhanced'"
        ).fetchone()
        assert tuple(checkpoint) == (prior, 1000, 1)
        assert snapshot.connection.execute(
            "SELECT run_state,revision FROM import_runs WHERE import_run_id=?", (candidate,)
        ).fetchone() == ("noop_pending_checkpoint", 1)
        assert snapshot.connection.execute(
            "SELECT 1 FROM command_receipts WHERE command_id=?", (command_id,)
        ).fetchone() is None
        assert snapshot.connection.execute(
            "SELECT COUNT(*) FROM audit_events WHERE command_id=?", (command_id,)
        ).fetchone()[0] == 0
