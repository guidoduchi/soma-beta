from __future__ import annotations

import pytest

from soma.foundation.errors import SomaError, ValidationError
from soma.foundation.identifiers import new_uuid4
from soma.foundation.persistence.uow import ReadSnapshot, UnitOfWork
from soma.ticket_import.repositories.observations import (
    NormalizedFieldEvidence,
    NormalizedObservationEvidence,
    SourceObservationRepository,
)


def _factory(initialized_database):
    database_path, factory_for_path = initialized_database
    return factory_for_path(database_path)


def _seed_validating_run(factory, source_family: str = "advanced_search_sr") -> str:
    run_id = new_uuid4()
    profiles = {
        "advanced_search_sr": (
            "ADVANCED_SEARCH_SR_V1",
            "ADVANCED_SEARCH_HEADERS_V1",
            "ADVANCED_SEARCH_VOCAB_V1",
            "ADVANCED_SEARCH_PARSER_V1",
            "embedded_filename_timestamp_utc",
        ),
        "rfc_enhanced": (
            "RFC_ENHANCED_V1",
            "RFC_HEADERS_V1",
            "RFC_VOCAB_V1",
            "RFC_PARSER_V1",
            "filesystem_mtime_ns",
        ),
        "wfm_service_provider": (
            "WFM_SERVICE_PROVIDER_V1",
            "WFM_HEADERS_V1",
            "WFM_VOCAB_V1",
            "WFM_PARSER_V1",
            "embedded_filename_timestamp_utc",
        ),
    }
    profile, headers, vocabulary, parser, chronology_kind = profiles[source_family]
    with UnitOfWork(factory) as uow:
        uow.connection.execute(
            "INSERT INTO import_runs("
            "import_run_id,source_family,invocation_kind,source_profile_id,header_registry_id,vocabulary_registry_id,parser_profile_id,"
            "candidate_filename,candidate_file_size_bytes,candidate_stable_mtime_ns,candidate_chronology_kind,candidate_chronology_value,"
            "run_state,started_at_utc,revision) VALUES (?,?,?,?,?,?,?,'fixture.xlsx',100,10,?,100,'validating',1,1)",
            (run_id, source_family, "automatic", profile, headers, vocabulary, parser, chronology_kind),
        )
    return run_id


def _field(
    key: str,
    *,
    field_class: str = "active",
    kind: str = "text",
    state: str = "usable",
    source_text: str | None = "value",
    normalized_text: str | None = "value",
    integer_value: int | None = None,
    vocabulary_id: str | None = None,
    digest: str = "1" * 64,
) -> NormalizedFieldEvidence:
    return NormalizedFieldEvidence(
        field_key=key,
        field_class=field_class,
        value_state=state,
        value_kind=kind,
        source_text=source_text,
        normalized_text=normalized_text,
        integer_value=integer_value,
        vocabulary_id=vocabulary_id,
        field_logical_sha256=digest,
    )


def _sr_observation(*fields: NormalizedFieldEvidence) -> NormalizedObservationEvidence:
    return NormalizedObservationEvidence(
        entity_kind="service_request",
        identity_state="valid",
        canonical_primary_id="12345678",
        canonical_parent_rfc_no=None,
        row_ordinal=2,
        sheet_ordinal=1,
        row_logical_sha256="2" * 64,
        source_row_chronology_utc=100,
        fields=tuple(fields),
    )


def test_stage_advanced_search_normalized_evidence_is_unpublished_and_typed(initialized_database) -> None:
    factory = _factory(initialized_database)
    run_id = _seed_validating_run(factory)
    fields = (
        _field("problem_summary", source_text="Summary", normalized_text="Summary"),
        _field(
            "status",
            kind="controlled",
            source_text="Closed",
            normalized_text="Closed",
            vocabulary_id="ADVANCED_SEARCH_STATUS_V1",
            digest="3" * 64,
        ),
        _field(
            "last_update",
            kind="instant",
            source_text="2026-08-29 04:30:00",
            normalized_text=None,
            integer_value=1_777_000_000,
            digest="4" * 64,
        ),
        _field(
            "resolve_by",
            field_class="deferred",
            kind="instant",
            source_text="2026-08-30 04:30:00",
            normalized_text=None,
            integer_value=1_777_086_400,
            digest="5" * 64,
        ),
    )

    with UnitOfWork(factory) as uow:
        result = SourceObservationRepository.stage_observations(
            uow,
            import_run_id=run_id,
            expected_run_revision=1,
            observations=(_sr_observation(*fields),),
        )
    assert len(result) == 1 and len(result[0].field_ids) == 4

    with ReadSnapshot(factory) as snapshot:
        run = snapshot.connection.execute(
            "SELECT run_state,logical_fingerprint_sha256,observed_row_count FROM import_runs WHERE import_run_id=?",
            (run_id,),
        ).fetchone()
        assert tuple(run) == ("validating", None, 0)
        observation = snapshot.connection.execute(
            "SELECT source_family,entity_kind,identity_state,canonical_primary_id,row_ordinal,sheet_ordinal "
            "FROM source_observations WHERE source_observation_id=?",
            (result[0].source_observation_id,),
        ).fetchone()
        assert tuple(observation) == ("advanced_search_sr", "service_request", "valid", "12345678", 2, 1)
        stored_fields = snapshot.connection.execute(
            "SELECT field_key,field_class,value_state,value_kind,vocabulary_id FROM source_observation_fields "
            "WHERE source_observation_id=? ORDER BY field_key",
            (result[0].source_observation_id,),
        ).fetchall()
        assert [tuple(row) for row in stored_fields] == [
            ("last_update", "active", "usable", "instant", None),
            ("problem_summary", "active", "usable", "text", None),
            ("resolve_by", "deferred", "usable", "instant", None),
            ("status", "active", "usable", "controlled", "ADVANCED_SEARCH_STATUS_V1"),
        ]


def test_staging_rejects_field_registry_kind_vocabulary_and_text_violations(initialized_database) -> None:
    factory = _factory(initialized_database)
    cases = (
        _field("not_registered"),
        _field("status", kind="text"),
        _field("status", kind="controlled", vocabulary_id="WRONG_VOCAB"),
        _field("problem_summary", source_text="bad\x00text", normalized_text="bad\x00text"),
        _field("problem_summary", source_text="x" * 65_537, normalized_text="x" * 65_537),
    )
    for field in cases:
        run_id = _seed_validating_run(factory)
        with pytest.raises((SomaError, ValidationError)):
            with UnitOfWork(factory) as uow:
                SourceObservationRepository.stage_observations(
                    uow,
                    import_run_id=run_id,
                    expected_run_revision=1,
                    observations=(_sr_observation(field),),
                )
        with ReadSnapshot(factory) as snapshot:
            assert snapshot.connection.execute(
                "SELECT COUNT(*) FROM source_observations WHERE import_run_id=?", (run_id,)
            ).fetchone()[0] == 0


def test_staging_identity_grammars_are_exact_for_all_source_families(initialized_database) -> None:
    factory = _factory(initialized_database)
    run_rfc = _seed_validating_run(factory, "rfc_enhanced")
    run_wfm = _seed_validating_run(factory, "wfm_service_provider")
    rfc = NormalizedObservationEvidence(
        entity_kind="rfc",
        identity_state="valid",
        canonical_primary_id="NC20260829000001",
        canonical_parent_rfc_no=None,
        row_ordinal=2,
        sheet_ordinal=1,
        row_logical_sha256="6" * 64,
        source_row_chronology_utc=100,
        fields=(_field("summary", source_text="RFC", normalized_text="RFC", digest="7" * 64),),
    )
    wfm = NormalizedObservationEvidence(
        entity_kind="wfm",
        identity_state="valid",
        canonical_primary_id="TK20260829000001",
        canonical_parent_rfc_no="NC20260829000001",
        row_ordinal=2,
        sheet_ordinal=1,
        row_logical_sha256="8" * 64,
        source_row_chronology_utc=100,
        fields=(_field("task_name", source_text="Task", normalized_text="Task", digest="9" * 64),),
    )
    with UnitOfWork(factory) as uow:
        SourceObservationRepository.stage_observations(
            uow, import_run_id=run_rfc, expected_run_revision=1, observations=(rfc,)
        )
    with UnitOfWork(factory) as uow:
        SourceObservationRepository.stage_observations(
            uow, import_run_id=run_wfm, expected_run_revision=1, observations=(wfm,)
        )

    invalid = NormalizedObservationEvidence(
        entity_kind="wfm",
        identity_state="valid",
        canonical_primary_id="TK2026082900001",
        canonical_parent_rfc_no="NC20260829000001",
        row_ordinal=3,
        sheet_ordinal=1,
        row_logical_sha256="a" * 64,
        source_row_chronology_utc=100,
    )
    with pytest.raises(ValidationError):
        with UnitOfWork(factory) as uow:
            SourceObservationRepository.stage_observations(
                uow, import_run_id=run_wfm, expected_run_revision=1, observations=(invalid,)
            )


def test_unpublished_staging_cleanup_is_exact_and_published_state_blocks_cleanup(initialized_database) -> None:
    factory = _factory(initialized_database)
    run_id = _seed_validating_run(factory)
    with UnitOfWork(factory) as uow:
        SourceObservationRepository.stage_observations(
            uow,
            import_run_id=run_id,
            expected_run_revision=1,
            observations=(_sr_observation(_field("problem_summary")),),
        )
    with UnitOfWork(factory) as uow:
        SourceObservationRepository.cleanup_unpublished(
            uow, import_run_id=run_id, expected_run_revision=1
        )
    with ReadSnapshot(factory) as snapshot:
        assert snapshot.connection.execute(
            "SELECT COUNT(*) FROM source_observations WHERE import_run_id=?", (run_id,)
        ).fetchone()[0] == 0
        assert snapshot.connection.execute(
            "SELECT COUNT(*) FROM source_observation_fields"
        ).fetchone()[0] == 0

    with UnitOfWork(factory) as uow:
        SourceObservationRepository.stage_observations(
            uow,
            import_run_id=run_id,
            expected_run_revision=1,
            observations=(_sr_observation(_field("problem_summary")),),
        )
        uow.connection.execute(
            "UPDATE import_runs SET run_state='staged',logical_fingerprint_sha256=?,staged_at_utc=2,revision=2 "
            "WHERE import_run_id=?",
            ("b" * 64, run_id),
        )
    with pytest.raises(SomaError) as failure:
        with UnitOfWork(factory) as uow:
            SourceObservationRepository.cleanup_unpublished(
                uow, import_run_id=run_id, expected_run_revision=2
            )
    assert failure.value.code == "IMPORT_RUN_STALE"
    with ReadSnapshot(factory) as snapshot:
        assert snapshot.connection.execute(
            "SELECT COUNT(*) FROM source_observations WHERE import_run_id=?", (run_id,)
        ).fetchone()[0] == 1


def test_staging_requires_exact_validating_run_revision_and_profile(initialized_database) -> None:
    factory = _factory(initialized_database)
    run_id = _seed_validating_run(factory)
    with pytest.raises(SomaError) as stale:
        with UnitOfWork(factory) as uow:
            SourceObservationRepository.stage_observations(
                uow,
                import_run_id=run_id,
                expected_run_revision=2,
                observations=(_sr_observation(),),
            )
    assert stale.value.code == "IMPORT_RUN_STALE"

    with UnitOfWork(factory) as uow:
        uow.connection.execute(
            "UPDATE import_runs SET source_profile_id='WRONG_PROFILE' WHERE import_run_id=?",
            (run_id,),
        )
    with pytest.raises(SomaError) as mismatch:
        with UnitOfWork(factory) as uow:
            SourceObservationRepository.stage_observations(
                uow,
                import_run_id=run_id,
                expected_run_revision=1,
                observations=(_sr_observation(),),
            )
    assert mismatch.value.code == "IMPORT_SOURCE_PROFILE_MISMATCH"
