from __future__ import annotations

import pytest

from soma.foundation.errors import JobClaimConflict, PersistenceFailure, SomaError
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


def _profiles(source_family: str = "advanced_search_sr") -> dict[str, str]:
    profiles = {
        "advanced_search_sr": {
            "source_profile_id": "ADVANCED_SEARCH_SR_V1",
            "header_registry_id": "ADVANCED_SEARCH_HEADERS_V1",
            "vocabulary_registry_id": "ADVANCED_SEARCH_VOCAB_V1",
            "parser_profile_id": "ADVANCED_SEARCH_PARSER_V1",
        },
        "rfc_enhanced": {
            "source_profile_id": "RFC_ENHANCED_V1",
            "header_registry_id": "RFC_HEADERS_V1",
            "vocabulary_registry_id": "RFC_VOCAB_V1",
            "parser_profile_id": "RFC_PARSER_V1",
        },
    }
    return profiles[source_family]


def _candidate(
    *,
    filename: str = "candidate.xlsx",
    chronology_kind: str = "embedded_filename_timestamp_utc",
    chronology_value: int = 10,
    locator_fingerprint: str = "a" * 64,
) -> dict[str, object]:
    return {
        "filename": filename,
        "stable_size_bytes": 100,
        "stable_mtime_ns": 1,
        "source_chronology_kind": chronology_kind,
        "source_chronology_value": chronology_value,
        "locator_fingerprint": locator_fingerprint,
    }


def _source_payload(
    *,
    source_family: str,
    profiles: dict[str, str],
    requested_by_command_id: str | None = None,
) -> dict[str, object]:
    return {
        "source_family": source_family,
        "invocation_kind": "manual",
        "profile_ids": profiles,
        "source_locator": {
            "kind": "manual_path",
            "selected_path": r"C:\Imports\candidate.xlsx",
        },
        "requested_by_command_id": requested_by_command_id or new_uuid4(),
    }


def _seed_validating_run(
    uow: UnitOfWork,
    *,
    run_id: str,
    source_family: str,
    profiles: dict[str, str],
    candidate: dict[str, object],
) -> None:
    uow.connection.execute(
        "INSERT INTO import_runs("
        "import_run_id,source_family,invocation_kind,source_profile_id,header_registry_id,vocabulary_registry_id,"
        "parser_profile_id,candidate_filename,candidate_file_size_bytes,candidate_stable_mtime_ns,"
        "candidate_chronology_kind,candidate_chronology_value,run_state,started_at_utc,revision) "
        "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,'validating',0,1)",
        (
            run_id,
            source_family,
            "manual",
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


def _stage_identity_row(
    uow: UnitOfWork,
    *,
    run_id: str,
    source_family: str,
    canonical_primary_id: str | None,
) -> str:
    if source_family == "advanced_search_sr" and canonical_primary_id is None:
        entity_kind = "invalid_row"
        identity_state = "invalid"
        canonical_parent = None
    elif source_family == "advanced_search_sr":
        entity_kind = "service_request"
        identity_state = "valid"
        canonical_parent = None
    elif source_family == "rfc_enhanced":
        entity_kind = "rfc"
        identity_state = "valid"
        canonical_parent = None
    else:
        raise AssertionError("unsupported publication test source family")
    logical = LogicalRow(
        identity_state=identity_state,
        entity_kind=entity_kind,
        canonical_primary_id=canonical_primary_id,
        canonical_parent_rfc_no=canonical_parent,
    )
    staged = SourceObservationRepository.stage_observations(
        uow,
        import_run_id=run_id,
        expected_run_revision=1,
        observations=(
            NormalizedObservationEvidence(
                entity_kind=entity_kind,
                identity_state=identity_state,
                canonical_primary_id=canonical_primary_id,
                canonical_parent_rfc_no=canonical_parent,
                row_ordinal=1,
                sheet_ordinal=1,
                row_logical_sha256=row_logical_sha256(logical),
                source_row_chronology_utc=None,
                fields=(),
            ),
        ),
    )
    return staged[0].source_observation_id


def _fingerprint(factory, run_id: str) -> str:
    with ReadSnapshot(factory) as snapshot:
        return verify_staged_logical_run(
            snapshot.connection,
            import_run_id=run_id,
            expected_run_revision=1,
        ).fingerprint.logical_fingerprint_sha256


def _seed_checkpoint(
    uow: UnitOfWork,
    *,
    source_family: str,
    profiles: dict[str, str],
    chronology_kind: str,
    chronology_value: int,
    logical_fingerprint: str,
) -> str:
    prior_run_id = new_uuid4()
    uow.connection.execute(
        "INSERT INTO import_runs("
        "import_run_id,source_family,invocation_kind,source_profile_id,header_registry_id,vocabulary_registry_id,"
        "parser_profile_id,candidate_filename,candidate_file_size_bytes,candidate_stable_mtime_ns,"
        "candidate_chronology_kind,candidate_chronology_value,logical_fingerprint_sha256,run_state,"
        "started_at_utc,staged_at_utc,completed_at_utc,revision) "
        "VALUES (?,?,?,?,?,?,?,'prior.xlsx',1,1,?,?,?,'accepted',0,1,2,2)",
        (
            prior_run_id,
            source_family,
            "manual",
            profiles["source_profile_id"],
            profiles["header_registry_id"],
            profiles["vocabulary_registry_id"],
            profiles["parser_profile_id"],
            chronology_kind,
            chronology_value,
            logical_fingerprint,
        ),
    )
    uow.connection.execute(
        "INSERT INTO import_source_checkpoints("
        "source_family,source_profile_id,accepted_candidate_chronology_kind,accepted_candidate_chronology_value,"
        "accepted_logical_fingerprint_sha256,accepted_import_run_id,last_checked_at_utc,revision) "
        "VALUES (?,?,?,?,?,?,2,1)",
        (
            source_family,
            profiles["source_profile_id"],
            chronology_kind,
            chronology_value,
            logical_fingerprint,
            prior_run_id,
        ),
    )
    return prior_run_id


def _claim_with_publishing_checkpoint(
    factory,
    *,
    run_id: str,
    source_family: str,
    profiles: dict[str, str],
    candidate: dict[str, object],
):
    coordinator = DurableJobCoordinator(
        factory,
        JobTypeRegistry(TICKET_IMPORT_JOB_CONTRACTS),
    )
    payload = _source_payload(source_family=source_family, profiles=profiles)
    with UnitOfWork(factory) as uow:
        job_id = coordinator.enqueue_or_coalesce(
            uow,
            "ticket_import.source_check",
            1,
            payload,
            derive_source_check_dedupe_key(payload),
        )
    claim = coordinator.claim_next(new_uuid4(), utc_epoch_seconds())
    assert claim is not None
    assert claim.job_id == job_id
    checkpoint = {
        "phase": "publishing",
        "import_run_id": run_id,
        "run_revision": 1,
        "parser_profile_id": profiles["parser_profile_id"],
        "candidate_identity": candidate,
        "last_committed_batch": None,
    }
    coordinator.checkpoint(claim, checkpoint)
    return coordinator, claim, checkpoint


def _publish(
    service: PublishStagedImportRunService,
    *,
    command_id: str,
    claim,
    run_id: str,
    profiles: dict[str, str],
    checkpoint: dict[str, object],
    fingerprint: str,
):
    return service.publish(
        command_id=command_id,
        claim=claim,
        import_run_id=run_id,
        expected_run_revision=1,
        profile_ids=profiles,
        publishing_checkpoint=checkpoint,
        logical_fingerprint=fingerprint,
    )


def test_new_advanced_search_publication_commits_run_audit_and_reappearance_job(
    initialized_database,
) -> None:
    factory = _factory(initialized_database)
    profiles = _profiles()
    candidate = _candidate()
    run_id = new_uuid4()
    with UnitOfWork(factory) as uow:
        _seed_validating_run(
            uow,
            run_id=run_id,
            source_family="advanced_search_sr",
            profiles=profiles,
            candidate=candidate,
        )
        _stage_identity_row(
            uow,
            run_id=run_id,
            source_family="advanced_search_sr",
            canonical_primary_id=None,
        )
    fingerprint = _fingerprint(factory, run_id)
    _coordinator, claim, checkpoint = _claim_with_publishing_checkpoint(
        factory,
        run_id=run_id,
        source_family="advanced_search_sr",
        profiles=profiles,
        candidate=candidate,
    )
    command_id = new_uuid4()
    result = _publish(
        PublishStagedImportRunService(factory),
        command_id=command_id,
        claim=claim,
        run_id=run_id,
        profiles=profiles,
        checkpoint=checkpoint,
        fingerprint=fingerprint,
    )
    assert result.run_state == "staged"
    assert result.revision == 2
    assert result.proposal_count == 0
    assert result.replayed is False

    with ReadSnapshot(factory) as snapshot:
        run = snapshot.connection.execute(
            "SELECT run_state,revision,observed_row_count,valid_identity_count,invalid_row_count,proposal_count "
            "FROM import_runs WHERE import_run_id=?",
            (run_id,),
        ).fetchone()
        assert tuple(run) == ("staged", 2, 1, 0, 1, 0)
        assert snapshot.connection.execute(
            "SELECT COUNT(*) FROM command_receipts WHERE command_id=?", (command_id,)
        ).fetchone()[0] == 1
        assert [str(row[0]) for row in snapshot.connection.execute(
            "SELECT action_type FROM audit_events WHERE command_id=?", (command_id,)
        ).fetchall()] == ["ticket_import.run_published"]
        jobs = snapshot.connection.execute(
            "SELECT state,payload_json FROM durable_jobs WHERE job_type=?",
            (SR_REAPPEARANCE_JOB_TYPE,),
        ).fetchall()
        assert len(jobs) == 1
        assert str(jobs[0][0]) == "queued"
        assert f'\"import_run_id\":\"{run_id}\"' in str(jobs[0][1])


def test_missing_sr_identity_publication_builds_pending_review_proposal(initialized_database) -> None:
    factory = _factory(initialized_database)
    profiles = _profiles()
    candidate = _candidate()
    run_id = new_uuid4()
    with UnitOfWork(factory) as uow:
        _seed_validating_run(
            uow,
            run_id=run_id,
            source_family="advanced_search_sr",
            profiles=profiles,
            candidate=candidate,
        )
        _stage_identity_row(
            uow,
            run_id=run_id,
            source_family="advanced_search_sr",
            canonical_primary_id="12345678",
        )
    fingerprint = _fingerprint(factory, run_id)
    _coordinator, claim, checkpoint = _claim_with_publishing_checkpoint(
        factory,
        run_id=run_id,
        source_family="advanced_search_sr",
        profiles=profiles,
        candidate=candidate,
    )
    result = _publish(
        PublishStagedImportRunService(factory),
        command_id=new_uuid4(),
        claim=claim,
        run_id=run_id,
        profiles=profiles,
        checkpoint=checkpoint,
        fingerprint=fingerprint,
    )
    assert result.run_state == "waiting_review"
    assert result.proposal_count == 1
    with ReadSnapshot(factory) as snapshot:
        proposal = snapshot.connection.execute(
            "SELECT evidence_mode,proposal_kind,target_kind,target_internal_id,target_business_id,risk_class,proposal_state "
            "FROM reconciliation_proposals WHERE import_run_id=?",
            (run_id,),
        ).fetchone()
        assert tuple(proposal) == (
            "observed_row",
            "sr_create_or_adopt",
            "service_request",
            None,
            "12345678",
            "medium",
            "pending",
        )


@pytest.mark.parametrize(
    ("current_chronology", "expected_state"),
    [(10, "noop"), (11, "noop_pending_checkpoint")],
)
def test_replay_classification_cleans_unpublished_evidence_without_source_publication(
    initialized_database,
    current_chronology: int,
    expected_state: str,
) -> None:
    factory = _factory(initialized_database)
    profiles = _profiles()
    candidate = _candidate(chronology_value=current_chronology)
    run_id = new_uuid4()
    with UnitOfWork(factory) as uow:
        _seed_validating_run(
            uow,
            run_id=run_id,
            source_family="advanced_search_sr",
            profiles=profiles,
            candidate=candidate,
        )
        _stage_identity_row(
            uow,
            run_id=run_id,
            source_family="advanced_search_sr",
            canonical_primary_id=None,
        )
    fingerprint = _fingerprint(factory, run_id)
    with UnitOfWork(factory) as uow:
        _seed_checkpoint(
            uow,
            source_family="advanced_search_sr",
            profiles=profiles,
            chronology_kind="embedded_filename_timestamp_utc",
            chronology_value=10,
            logical_fingerprint=fingerprint,
        )
    _coordinator, claim, checkpoint = _claim_with_publishing_checkpoint(
        factory,
        run_id=run_id,
        source_family="advanced_search_sr",
        profiles=profiles,
        candidate=candidate,
    )
    command_id = new_uuid4()
    result = _publish(
        PublishStagedImportRunService(factory),
        command_id=command_id,
        claim=claim,
        run_id=run_id,
        profiles=profiles,
        checkpoint=checkpoint,
        fingerprint=fingerprint,
    )
    assert result.run_state == expected_state
    assert result.proposal_count == 0
    with ReadSnapshot(factory) as snapshot:
        assert snapshot.connection.execute(
            "SELECT COUNT(*) FROM source_observations WHERE import_run_id=?", (run_id,)
        ).fetchone()[0] == 0
        assert snapshot.connection.execute(
            "SELECT COUNT(*) FROM import_findings WHERE import_run_id=?", (run_id,)
        ).fetchone()[0] == 0
        assert snapshot.connection.execute(
            "SELECT COUNT(*) FROM durable_jobs WHERE job_type=?",
            (SR_REAPPEARANCE_JOB_TYPE,),
        ).fetchone()[0] == 0
        assert [str(row[0]) for row in snapshot.connection.execute(
            "SELECT action_type FROM audit_events WHERE command_id=?", (command_id,)
        ).fetchall()] == ["ticket_import.run_noop_classified"]
        completed = snapshot.connection.execute(
            "SELECT completed_at_utc FROM import_runs WHERE import_run_id=?", (run_id,)
        ).fetchone()[0]
        assert (completed is not None) == (expected_state == "noop")


def test_stale_source_check_claim_fails_before_receipt_or_publication(initialized_database) -> None:
    factory = _factory(initialized_database)
    profiles = _profiles()
    candidate = _candidate()
    run_id = new_uuid4()
    with UnitOfWork(factory) as uow:
        _seed_validating_run(
            uow,
            run_id=run_id,
            source_family="advanced_search_sr",
            profiles=profiles,
            candidate=candidate,
        )
        _stage_identity_row(
            uow,
            run_id=run_id,
            source_family="advanced_search_sr",
            canonical_primary_id=None,
        )
    fingerprint = _fingerprint(factory, run_id)
    coordinator, claim, checkpoint = _claim_with_publishing_checkpoint(
        factory,
        run_id=run_id,
        source_family="advanced_search_sr",
        profiles=profiles,
        candidate=candidate,
    )
    coordinator.complete(claim)
    command_id = new_uuid4()
    with pytest.raises(JobClaimConflict):
        _publish(
            PublishStagedImportRunService(factory),
            command_id=command_id,
            claim=claim,
            run_id=run_id,
            profiles=profiles,
            checkpoint=checkpoint,
            fingerprint=fingerprint,
        )
    with ReadSnapshot(factory) as snapshot:
        assert snapshot.connection.execute(
            "SELECT COUNT(*) FROM command_receipts WHERE command_id=?", (command_id,)
        ).fetchone()[0] == 0
        assert snapshot.connection.execute(
            "SELECT run_state FROM import_runs WHERE import_run_id=?", (run_id,)
        ).fetchone()[0] == "validating"


def test_current_publishing_checkpoint_drift_is_retryable_claim_conflict(initialized_database) -> None:
    factory = _factory(initialized_database)
    profiles = _profiles()
    candidate = _candidate()
    run_id = new_uuid4()
    with UnitOfWork(factory) as uow:
        _seed_validating_run(
            uow,
            run_id=run_id,
            source_family="advanced_search_sr",
            profiles=profiles,
            candidate=candidate,
        )
        _stage_identity_row(
            uow,
            run_id=run_id,
            source_family="advanced_search_sr",
            canonical_primary_id=None,
        )
    fingerprint = _fingerprint(factory, run_id)
    _coordinator, claim, checkpoint = _claim_with_publishing_checkpoint(
        factory,
        run_id=run_id,
        source_family="advanced_search_sr",
        profiles=profiles,
        candidate=candidate,
    )
    supplied = {
        **checkpoint,
        "candidate_identity": {
            **candidate,
            "locator_fingerprint": "b" * 64,
        },
    }
    command_id = new_uuid4()
    with pytest.raises(JobClaimConflict) as exc:
        _publish(
            PublishStagedImportRunService(factory),
            command_id=command_id,
            claim=claim,
            run_id=run_id,
            profiles=profiles,
            checkpoint=supplied,
            fingerprint=fingerprint,
        )
    assert exc.value.retryable is True
    with ReadSnapshot(factory) as snapshot:
        assert snapshot.connection.execute(
            "SELECT COUNT(*) FROM command_receipts WHERE command_id=?", (command_id,)
        ).fetchone()[0] == 0


def test_committed_publication_replays_after_source_check_job_is_terminal(initialized_database) -> None:
    factory = _factory(initialized_database)
    profiles = _profiles()
    candidate = _candidate()
    run_id = new_uuid4()
    with UnitOfWork(factory) as uow:
        _seed_validating_run(
            uow,
            run_id=run_id,
            source_family="advanced_search_sr",
            profiles=profiles,
            candidate=candidate,
        )
        _stage_identity_row(
            uow,
            run_id=run_id,
            source_family="advanced_search_sr",
            canonical_primary_id=None,
        )
    fingerprint = _fingerprint(factory, run_id)
    coordinator, claim, checkpoint = _claim_with_publishing_checkpoint(
        factory,
        run_id=run_id,
        source_family="advanced_search_sr",
        profiles=profiles,
        candidate=candidate,
    )
    service = PublishStagedImportRunService(factory)
    command_id = new_uuid4()
    first = _publish(
        service,
        command_id=command_id,
        claim=claim,
        run_id=run_id,
        profiles=profiles,
        checkpoint=checkpoint,
        fingerprint=fingerprint,
    )
    coordinator.complete(claim)
    replay = _publish(
        service,
        command_id=command_id,
        claim=claim,
        run_id=run_id,
        profiles=profiles,
        checkpoint=checkpoint,
        fingerprint=fingerprint,
    )
    assert first.replayed is False
    assert replay.replayed is True
    assert (replay.run_state, replay.revision, replay.proposal_count) == (
        first.run_state,
        first.revision,
        first.proposal_count,
    )
    with ReadSnapshot(factory) as snapshot:
        assert snapshot.connection.execute(
            "SELECT COUNT(*) FROM audit_events WHERE command_id=?", (command_id,)
        ).fetchone()[0] == 1
        assert snapshot.connection.execute(
            "SELECT COUNT(*) FROM durable_jobs WHERE job_type=?",
            (SR_REAPPEARANCE_JOB_TYPE,),
        ).fetchone()[0] == 1
        assert snapshot.connection.execute(
            "SELECT revision FROM import_runs WHERE import_run_id=?", (run_id,)
        ).fetchone()[0] == first.revision


class _FailReappearanceEnqueue:
    def __init__(self, delegate) -> None:
        self._delegate = delegate

    def assert_claim_current(self, uow, claim):
        return self._delegate.assert_claim_current(uow, claim)

    def enqueue_or_coalesce(self, *args, **kwargs):
        raise PersistenceFailure("injected reappearance enqueue failure")


def test_reappearance_enqueue_failure_rolls_back_receipt_proposals_run_and_audit(
    initialized_database,
) -> None:
    factory = _factory(initialized_database)
    profiles = _profiles()
    candidate = _candidate()
    run_id = new_uuid4()
    with UnitOfWork(factory) as uow:
        _seed_validating_run(
            uow,
            run_id=run_id,
            source_family="advanced_search_sr",
            profiles=profiles,
            candidate=candidate,
        )
        _stage_identity_row(
            uow,
            run_id=run_id,
            source_family="advanced_search_sr",
            canonical_primary_id="87654321",
        )
    fingerprint = _fingerprint(factory, run_id)
    _coordinator, claim, checkpoint = _claim_with_publishing_checkpoint(
        factory,
        run_id=run_id,
        source_family="advanced_search_sr",
        profiles=profiles,
        candidate=candidate,
    )
    service = PublishStagedImportRunService(factory)
    service._jobs = _FailReappearanceEnqueue(service._jobs)
    command_id = new_uuid4()
    with pytest.raises(PersistenceFailure, match="injected reappearance enqueue failure"):
        _publish(
            service,
            command_id=command_id,
            claim=claim,
            run_id=run_id,
            profiles=profiles,
            checkpoint=checkpoint,
            fingerprint=fingerprint,
        )
    with ReadSnapshot(factory) as snapshot:
        assert tuple(snapshot.connection.execute(
            "SELECT run_state,revision,proposal_count FROM import_runs WHERE import_run_id=?", (run_id,)
        ).fetchone()) == ("validating", 1, 0)
        assert snapshot.connection.execute(
            "SELECT COUNT(*) FROM reconciliation_proposals WHERE import_run_id=?", (run_id,)
        ).fetchone()[0] == 0
        assert snapshot.connection.execute(
            "SELECT COUNT(*) FROM command_receipts WHERE command_id=?", (command_id,)
        ).fetchone()[0] == 0
        assert snapshot.connection.execute(
            "SELECT COUNT(*) FROM audit_events WHERE command_id=?", (command_id,)
        ).fetchone()[0] == 0
        assert snapshot.connection.execute(
            "SELECT COUNT(*) FROM durable_jobs WHERE job_type=?",
            (SR_REAPPEARANCE_JOB_TYPE,),
        ).fetchone()[0] == 0


def test_changed_rfc_publication_fails_closed_until_rfc_orchestration_slice_exists(
    initialized_database,
) -> None:
    factory = _factory(initialized_database)
    profiles = _profiles("rfc_enhanced")
    candidate = _candidate(
        chronology_kind="filesystem_mtime_ns",
        chronology_value=10,
    )
    run_id = new_uuid4()
    with UnitOfWork(factory) as uow:
        _seed_validating_run(
            uow,
            run_id=run_id,
            source_family="rfc_enhanced",
            profiles=profiles,
            candidate=candidate,
        )
        _stage_identity_row(
            uow,
            run_id=run_id,
            source_family="rfc_enhanced",
            canonical_primary_id="NC20260914000001",
        )
    fingerprint = _fingerprint(factory, run_id)
    _coordinator, claim, checkpoint = _claim_with_publishing_checkpoint(
        factory,
        run_id=run_id,
        source_family="rfc_enhanced",
        profiles=profiles,
        candidate=candidate,
    )
    command_id = new_uuid4()
    with pytest.raises(SomaError) as exc:
        _publish(
            PublishStagedImportRunService(factory),
            command_id=command_id,
            claim=claim,
            run_id=run_id,
            profiles=profiles,
            checkpoint=checkpoint,
            fingerprint=fingerprint,
        )
    assert exc.value.code == "IMPORT_RUN_STALE"
    with ReadSnapshot(factory) as snapshot:
        assert tuple(snapshot.connection.execute(
            "SELECT run_state,revision FROM import_runs WHERE import_run_id=?", (run_id,)
        ).fetchone()) == ("validating", 1)
        assert snapshot.connection.execute(
            "SELECT COUNT(*) FROM command_receipts WHERE command_id=?", (command_id,)
        ).fetchone()[0] == 0
