from __future__ import annotations

import pytest

from soma.foundation.errors import IntegrityFailure
from soma.foundation.identifiers import new_uuid4
from soma.foundation.persistence.uow import ReadSnapshot, UnitOfWork
from soma.ticket_import.reconciliation.engine import (
    LogicalField,
    LogicalFinding,
    LogicalRow,
    field_logical_sha256,
    row_logical_sha256,
)
from soma.ticket_import.reconciliation.staged import verify_staged_logical_run
from soma.ticket_import.repositories.observations import (
    NormalizedFieldEvidence,
    NormalizedObservationEvidence,
    SourceObservationRepository,
)


def _factory(initialized_database):
    database_path, factory_for_path = initialized_database
    return factory_for_path(database_path)


def _seed_validating_run(
    uow: UnitOfWork,
    *,
    run_id: str,
    source_family: str,
    chronology_kind: str,
    chronology_value: int,
) -> None:
    profiles = {
        "advanced_search_sr": (
            "ADVANCED_SEARCH_SR_V1",
            "ADVANCED_SEARCH_HEADERS_V1",
            "ADVANCED_SEARCH_VOCAB_V1",
            "ADVANCED_SEARCH_PARSER_V1",
        ),
        "rfc_enhanced": (
            "RFC_ENHANCED_V1",
            "RFC_HEADERS_V1",
            "RFC_VOCAB_V1",
            "RFC_PARSER_V1",
        ),
    }
    source_profile_id, header_registry_id, vocabulary_registry_id, parser_profile_id = profiles[source_family]
    uow.connection.execute(
        "INSERT INTO import_runs("
        "import_run_id,source_family,invocation_kind,source_profile_id,header_registry_id,vocabulary_registry_id,parser_profile_id,"
        "candidate_filename,candidate_file_size_bytes,candidate_stable_mtime_ns,candidate_chronology_kind,candidate_chronology_value,"
        "run_state,started_at_utc,revision) VALUES (?,?,?,?,?,?,?,'candidate.xlsx',100,1,?,?,'validating',0,1)",
        (
            run_id,
            source_family,
            "manual",
            source_profile_id,
            header_registry_id,
            vocabulary_registry_id,
            parser_profile_id,
            chronology_kind,
            chronology_value,
        ),
    )


def _seed_rfc_observation(
    uow: UnitOfWork,
    *,
    run_id: str,
    field_hash: str | None = None,
    row_hash: str | None = None,
) -> str:
    logical_field = LogicalField(
        field_key="summary",
        field_class="active",
        value_state="usable",
        value_kind="text",
        normalized_text="Replace fan",
        source_text="Replace fan",
    )
    logical_row = LogicalRow(
        identity_state="valid",
        entity_kind="rfc",
        canonical_primary_id="NC20260908000001",
        canonical_parent_rfc_no=None,
        fields=(logical_field,),
    )
    staged = SourceObservationRepository.stage_observations(
        uow,
        import_run_id=run_id,
        expected_run_revision=1,
        observations=(
            NormalizedObservationEvidence(
                entity_kind="rfc",
                identity_state="valid",
                canonical_primary_id="NC20260908000001",
                canonical_parent_rfc_no=None,
                row_ordinal=1,
                sheet_ordinal=1,
                row_logical_sha256=row_hash or row_logical_sha256(logical_row),
                source_row_chronology_utc=None,
                fields=(
                    NormalizedFieldEvidence(
                        field_key="summary",
                        field_class="active",
                        value_state="usable",
                        value_kind="text",
                        source_text="Replace fan",
                        normalized_text="Replace fan",
                        integer_value=None,
                        vocabulary_id=None,
                        field_logical_sha256=field_hash or field_logical_sha256(logical_field),
                    ),
                ),
            ),
        ),
    )
    return staged[0].source_observation_id


def _seed_checkpoint(
    uow: UnitOfWork,
    *,
    source_family: str,
    source_profile_id: str,
    chronology_kind: str,
    chronology_value: int,
    logical_fingerprint: str,
) -> str:
    prior_run_id = new_uuid4()
    uow.connection.execute(
        "INSERT INTO import_runs("
        "import_run_id,source_family,invocation_kind,source_profile_id,header_registry_id,vocabulary_registry_id,parser_profile_id,"
        "candidate_filename,candidate_file_size_bytes,candidate_stable_mtime_ns,candidate_chronology_kind,candidate_chronology_value,"
        "logical_fingerprint_sha256,run_state,started_at_utc,staged_at_utc,completed_at_utc,revision) "
        "VALUES (?,?,?,?,?,?,?,'accepted.xlsx',100,1,?,?,?,'accepted',0,1,2,2)",
        (
            prior_run_id,
            source_family,
            "manual",
            source_profile_id,
            "RFC_HEADERS_V1" if source_family == "rfc_enhanced" else "ADVANCED_SEARCH_HEADERS_V1",
            "RFC_VOCAB_V1" if source_family == "rfc_enhanced" else "ADVANCED_SEARCH_VOCAB_V1",
            "RFC_PARSER_V1" if source_family == "rfc_enhanced" else "ADVANCED_SEARCH_PARSER_V1",
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
            source_profile_id,
            chronology_kind,
            chronology_value,
            logical_fingerprint,
            prior_run_id,
        ),
    )
    return prior_run_id


def test_persisted_rfc_golden_vector_recomputes_exact_run_fingerprint(initialized_database) -> None:
    factory = _factory(initialized_database)
    run_id = new_uuid4()
    with UnitOfWork(factory) as uow:
        _seed_validating_run(
            uow,
            run_id=run_id,
            source_family="rfc_enhanced",
            chronology_kind="filesystem_mtime_ns",
            chronology_value=10,
        )
        observation_id = _seed_rfc_observation(uow, run_id=run_id)

    with ReadSnapshot(factory) as snapshot:
        verified = verify_staged_logical_run(
            snapshot.connection,
            import_run_id=run_id,
            expected_run_revision=1,
        )
        run_state = tuple(
            snapshot.connection.execute(
                "SELECT run_state,logical_fingerprint_sha256,revision,proposal_count FROM import_runs WHERE import_run_id=?",
                (run_id,),
            ).fetchone()
        )

    assert verified.fingerprint.stream_bytes == 397
    assert verified.fingerprint.logical_fingerprint_sha256 == (
        "0752aff5cb09dd68133e02d27abd2f9c3701004c89883f93edf77a5f2efa49c6"
    )
    assert verified.replay_classification == "NEW_SOURCE"
    assert verified.checkpoint is None
    assert verified.observations[0].source_observation_id == observation_id
    assert verified.observations[0].row.canonical_primary_id == "NC20260908000001"
    assert run_state == ("validating", None, 1, 0)


def test_persisted_unknown_controlled_finding_matches_golden_vector(initialized_database) -> None:
    factory = _factory(initialized_database)
    run_id = new_uuid4()
    logical_field = LogicalField(
        field_key="status",
        field_class="active",
        value_state="unknown",
        value_kind="controlled",
        vocabulary_id="ADVANCED_SEARCH_STATUS_V1",
        source_text="mystery",
    )
    finding = LogicalFinding(
        finding_code="SOURCE_CONTROLLED_VALUE_UNKNOWN",
        severity="warning",
        scope_kind="field",
        field_key="status",
    )
    logical_row = LogicalRow(
        identity_state="valid",
        entity_kind="service_request",
        canonical_primary_id="12345678",
        canonical_parent_rfc_no=None,
        fields=(logical_field,),
        findings=(finding,),
    )
    with UnitOfWork(factory) as uow:
        _seed_validating_run(
            uow,
            run_id=run_id,
            source_family="advanced_search_sr",
            chronology_kind="embedded_filename_timestamp_utc",
            chronology_value=10,
        )
        staged = SourceObservationRepository.stage_observations(
            uow,
            import_run_id=run_id,
            expected_run_revision=1,
            observations=(
                NormalizedObservationEvidence(
                    entity_kind="service_request",
                    identity_state="valid",
                    canonical_primary_id="12345678",
                    canonical_parent_rfc_no=None,
                    row_ordinal=1,
                    sheet_ordinal=1,
                    row_logical_sha256=row_logical_sha256(logical_row),
                    source_row_chronology_utc=None,
                    fields=(
                        NormalizedFieldEvidence(
                            field_key="status",
                            field_class="active",
                            value_state="unknown",
                            value_kind="controlled",
                            source_text="mystery",
                            normalized_text=None,
                            integer_value=None,
                            vocabulary_id="ADVANCED_SEARCH_STATUS_V1",
                            field_logical_sha256=field_logical_sha256(logical_field),
                        ),
                    ),
                ),
            ),
        )
        uow.connection.execute(
            "INSERT INTO import_findings("
            "import_finding_id,import_run_id,source_observation_id,field_key,finding_code,severity,scope_kind,message_text,recorded_at_utc) "
            "VALUES (?,?,?,?,?,'warning','field','operator wording is not fingerprint authority',1)",
            (new_uuid4(), run_id, staged[0].source_observation_id, "status", "SOURCE_CONTROLLED_VALUE_UNKNOWN"),
        )

    with ReadSnapshot(factory) as snapshot:
        verified = verify_staged_logical_run(
            snapshot.connection,
            import_run_id=run_id,
            expected_run_revision=1,
        )

    assert verified.fingerprint.stream_bytes == 656
    assert verified.fingerprint.logical_fingerprint_sha256 == (
        "6d022861df6309b779ce0540d7ce065f386ad2dbda6c402c3a3c3e6836cae7cb"
    )


def test_exact_checkpoint_replay_uses_recomputed_fingerprint(initialized_database) -> None:
    factory = _factory(initialized_database)
    run_id = new_uuid4()
    golden = "0752aff5cb09dd68133e02d27abd2f9c3701004c89883f93edf77a5f2efa49c6"
    with UnitOfWork(factory) as uow:
        _seed_validating_run(
            uow,
            run_id=run_id,
            source_family="rfc_enhanced",
            chronology_kind="filesystem_mtime_ns",
            chronology_value=10,
        )
        _seed_rfc_observation(uow, run_id=run_id)
        prior_run_id = _seed_checkpoint(
            uow,
            source_family="rfc_enhanced",
            source_profile_id="RFC_ENHANCED_V1",
            chronology_kind="filesystem_mtime_ns",
            chronology_value=10,
            logical_fingerprint=golden,
        )

    with ReadSnapshot(factory) as snapshot:
        verified = verify_staged_logical_run(
            snapshot.connection,
            import_run_id=run_id,
            expected_run_revision=1,
        )

    assert verified.replay_classification == "EXACT_REPLAY_NOOP"
    assert verified.checkpoint is not None
    assert verified.checkpoint.accepted_import_run_id == prior_run_id
    assert verified.fingerprint.logical_fingerprint_sha256 == golden


def test_newer_identical_checkpoint_classification_is_preserved(initialized_database) -> None:
    factory = _factory(initialized_database)
    run_id = new_uuid4()
    golden = "0752aff5cb09dd68133e02d27abd2f9c3701004c89883f93edf77a5f2efa49c6"
    with UnitOfWork(factory) as uow:
        _seed_validating_run(
            uow,
            run_id=run_id,
            source_family="rfc_enhanced",
            chronology_kind="filesystem_mtime_ns",
            chronology_value=11,
        )
        _seed_rfc_observation(uow, run_id=run_id)
        _seed_checkpoint(
            uow,
            source_family="rfc_enhanced",
            source_profile_id="RFC_ENHANCED_V1",
            chronology_kind="filesystem_mtime_ns",
            chronology_value=10,
            logical_fingerprint=golden,
        )

    with ReadSnapshot(factory) as snapshot:
        verified = verify_staged_logical_run(
            snapshot.connection,
            import_run_id=run_id,
            expected_run_revision=1,
        )

    assert verified.replay_classification == "NEWER_IDENTICAL_NO_DOMAIN_CHANGE"


def test_wrong_staged_field_hash_fails_closed_before_run_fingerprint(initialized_database) -> None:
    factory = _factory(initialized_database)
    run_id = new_uuid4()
    with UnitOfWork(factory) as uow:
        _seed_validating_run(
            uow,
            run_id=run_id,
            source_family="rfc_enhanced",
            chronology_kind="filesystem_mtime_ns",
            chronology_value=10,
        )
        _seed_rfc_observation(uow, run_id=run_id, field_hash="0" * 64)

    with ReadSnapshot(factory) as snapshot:
        with pytest.raises(IntegrityFailure, match="field logical hash"):
            verify_staged_logical_run(
                snapshot.connection,
                import_run_id=run_id,
                expected_run_revision=1,
            )


def test_wrong_staged_row_hash_fails_closed_after_field_verification(initialized_database) -> None:
    factory = _factory(initialized_database)
    run_id = new_uuid4()
    with UnitOfWork(factory) as uow:
        _seed_validating_run(
            uow,
            run_id=run_id,
            source_family="rfc_enhanced",
            chronology_kind="filesystem_mtime_ns",
            chronology_value=10,
        )
        _seed_rfc_observation(uow, run_id=run_id, row_hash="0" * 64)

    with ReadSnapshot(factory) as snapshot:
        with pytest.raises(IntegrityFailure, match="row logical hash"):
            verify_staged_logical_run(
                snapshot.connection,
                import_run_id=run_id,
                expected_run_revision=1,
            )


def test_checkpoint_chronology_kind_mismatch_fails_closed(initialized_database) -> None:
    factory = _factory(initialized_database)
    run_id = new_uuid4()
    golden = "0752aff5cb09dd68133e02d27abd2f9c3701004c89883f93edf77a5f2efa49c6"
    with UnitOfWork(factory) as uow:
        _seed_validating_run(
            uow,
            run_id=run_id,
            source_family="rfc_enhanced",
            chronology_kind="filesystem_mtime_ns",
            chronology_value=10,
        )
        _seed_rfc_observation(uow, run_id=run_id)
        _seed_checkpoint(
            uow,
            source_family="rfc_enhanced",
            source_profile_id="RFC_ENHANCED_V1",
            chronology_kind="embedded_filename_timestamp_utc",
            chronology_value=10,
            logical_fingerprint=golden,
        )

    with ReadSnapshot(factory) as snapshot:
        with pytest.raises(IntegrityFailure, match="chronology kind"):
            verify_staged_logical_run(
                snapshot.connection,
                import_run_id=run_id,
                expected_run_revision=1,
            )
