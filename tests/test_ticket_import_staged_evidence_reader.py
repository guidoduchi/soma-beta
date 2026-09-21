from __future__ import annotations

import pytest

from soma.foundation.errors import IntegrityFailure, SomaError
from soma.foundation.identifiers import new_uuid4
from soma.foundation.persistence.uow import ReadSnapshot, UnitOfWork
from soma.ticket_import.reconciliation.engine import field_logical_sha256, row_logical_sha256, LogicalField, LogicalRow
from soma.ticket_import.repositories.observations import (
    NormalizedFieldEvidence,
    NormalizedObservationEvidence,
    SourceObservationRepository,
)


def _factory(initialized_database):
    database_path, factory_for_path = initialized_database
    return factory_for_path(database_path)


def _seed_run(
    uow: UnitOfWork,
    *,
    run_id: str,
    source_family: str = "rfc_enhanced",
    source_profile_id: str = "RFC_ENHANCED_V1",
    header_registry_id: str = "RFC_HEADERS_V1",
    vocabulary_registry_id: str = "RFC_VOCAB_V1",
    parser_profile_id: str = "RFC_PARSER_V1",
) -> None:
    chronology_kind = "filesystem_mtime_ns" if source_family == "rfc_enhanced" else "embedded_filename_timestamp_utc"
    uow.connection.execute(
        "INSERT INTO import_runs("
        "import_run_id,source_family,invocation_kind,source_profile_id,header_registry_id,vocabulary_registry_id,parser_profile_id,"
        "candidate_filename,candidate_file_size_bytes,candidate_stable_mtime_ns,candidate_chronology_kind,candidate_chronology_value,"
        "run_state,started_at_utc,revision) VALUES (?,?,?,?,?,?,?,?,100,1,?,10,'validating',0,1)",
        (
            run_id,
            source_family,
            "manual",
            source_profile_id,
            header_registry_id,
            vocabulary_registry_id,
            parser_profile_id,
            "source.xlsx",
            chronology_kind,
        ),
    )


def _rfc_summary_observation(*, rfc_no: str, row_ordinal: int, text: str) -> NormalizedObservationEvidence:
    logical_field = LogicalField(
        field_key="summary",
        field_class="active",
        value_state="usable",
        value_kind="text",
        source_text=text,
        normalized_text=text,
    )
    logical_row = LogicalRow(
        identity_state="valid",
        entity_kind="rfc",
        canonical_primary_id=rfc_no,
        canonical_parent_rfc_no=None,
        fields=(logical_field,),
    )
    return NormalizedObservationEvidence(
        entity_kind="rfc",
        identity_state="valid",
        canonical_primary_id=rfc_no,
        canonical_parent_rfc_no=None,
        row_ordinal=row_ordinal,
        sheet_ordinal=1,
        row_logical_sha256=row_logical_sha256(logical_row),
        source_row_chronology_utc=None,
        fields=(
            NormalizedFieldEvidence(
                field_key="summary",
                field_class="active",
                value_state="usable",
                value_kind="text",
                source_text=text,
                normalized_text=text,
                integer_value=None,
                vocabulary_id=None,
                field_logical_sha256=field_logical_sha256(logical_field),
            ),
        ),
    )


def test_load_validating_evidence_preserves_physical_rows_fields_and_findings_without_writes(
    initialized_database,
) -> None:
    factory = _factory(initialized_database)
    run_id = new_uuid4()
    with UnitOfWork(factory) as uow:
        _seed_run(uow, run_id=run_id)
        staged = SourceObservationRepository.stage_observations(
            uow,
            import_run_id=run_id,
            expected_run_revision=1,
            observations=(
                _rfc_summary_observation(rfc_no="NC20260913000001", row_ordinal=2, text="Second"),
                _rfc_summary_observation(rfc_no="NC20260913000002", row_ordinal=1, text="First"),
            ),
        )
        first_id = staged[1].source_observation_id
        first_field_id = staged[1].field_ids[0]
        uow.connection.execute(
            "INSERT INTO import_findings(import_finding_id,import_run_id,source_observation_id,field_key,finding_code,severity,"
            "scope_kind,message_text,recorded_at_utc) VALUES (?,?,?,'summary','SOURCE_OPTIONAL_HEADER_MISSING','warning',"
            "'field','linked warning',2)",
            (new_uuid4(), run_id, first_id),
        )
        uow.connection.execute(
            "INSERT INTO import_findings(import_finding_id,import_run_id,source_observation_id,field_key,finding_code,severity,"
            "scope_kind,message_text,recorded_at_utc) VALUES (?,?,NULL,NULL,'GLOBAL_TEST','info','workbook','global info',2)",
            (new_uuid4(), run_id),
        )

    with UnitOfWork(factory) as uow:
        before_changes = uow.connection.total_changes
        evidence = SourceObservationRepository.load_validating_evidence(
            uow.connection,
            import_run_id=run_id,
            expected_run_revision=1,
        )
        assert uow.connection.total_changes == before_changes
        assert evidence.import_run_id == run_id
        assert evidence.source_family == "rfc_enhanced"
        assert evidence.source_profile_id == "RFC_ENHANCED_V1"
        assert evidence.candidate_chronology_kind == "filesystem_mtime_ns"
        assert evidence.candidate_chronology_value == 10
        assert [item.row_ordinal for item in evidence.observations] == [1, 2]
        assert [item.canonical_primary_id for item in evidence.observations] == [
            "NC20260913000002",
            "NC20260913000001",
        ]
        first = evidence.observations[0]
        assert first.source_observation_id == first_id
        assert first.fields[0].source_observation_field_id == first_field_id
        assert first.fields[0].normalized_text == "First"
        assert len(first.findings) == 1
        assert first.findings[0].finding_code == "SOURCE_OPTIONAL_HEADER_MISSING"
        assert len(evidence.global_findings) == 1
        assert evidence.global_findings[0].finding_code == "GLOBAL_TEST"


def test_reader_detects_duplicate_physical_locator_across_staging_batches(initialized_database) -> None:
    factory = _factory(initialized_database)
    run_id = new_uuid4()
    with UnitOfWork(factory) as uow:
        _seed_run(uow, run_id=run_id)
        SourceObservationRepository.stage_observations(
            uow,
            import_run_id=run_id,
            expected_run_revision=1,
            observations=(_rfc_summary_observation(rfc_no="NC20260913000001", row_ordinal=1, text="A"),),
        )
        SourceObservationRepository.stage_observations(
            uow,
            import_run_id=run_id,
            expected_run_revision=1,
            observations=(_rfc_summary_observation(rfc_no="NC20260913000002", row_ordinal=1, text="B"),),
        )
        with pytest.raises(IntegrityFailure):
            SourceObservationRepository.load_validating_evidence(
                uow.connection,
                import_run_id=run_id,
                expected_run_revision=1,
            )


def test_reader_rejects_cross_run_finding_link(initialized_database) -> None:
    factory = _factory(initialized_database)
    first_run = new_uuid4()
    second_run = new_uuid4()
    with UnitOfWork(factory) as uow:
        _seed_run(uow, run_id=first_run)
        _seed_run(uow, run_id=second_run)
        staged = SourceObservationRepository.stage_observations(
            uow,
            import_run_id=first_run,
            expected_run_revision=1,
            observations=(_rfc_summary_observation(rfc_no="NC20260913000001", row_ordinal=1, text="A"),),
        )
        uow.connection.execute(
            "INSERT INTO import_findings(import_finding_id,import_run_id,source_observation_id,field_key,finding_code,severity,"
            "scope_kind,message_text,recorded_at_utc) VALUES (?,?,?,NULL,'CROSS_RUN','warning','row','bad link',2)",
            (new_uuid4(), second_run, staged[0].source_observation_id),
        )
        with pytest.raises(IntegrityFailure):
            SourceObservationRepository.load_validating_evidence(
                uow.connection,
                import_run_id=second_run,
                expected_run_revision=1,
            )


def test_reader_rejects_profile_drift_and_field_registry_drift(initialized_database) -> None:
    factory = _factory(initialized_database)
    profile_run = new_uuid4()
    with UnitOfWork(factory) as uow:
        _seed_run(uow, run_id=profile_run, source_profile_id="WRONG_PROFILE")
        with pytest.raises(SomaError) as exc:
            SourceObservationRepository.load_validating_evidence(
                uow.connection,
                import_run_id=profile_run,
                expected_run_revision=1,
            )
        assert exc.value.code == "IMPORT_SOURCE_PROFILE_MISMATCH"

    field_run = new_uuid4()
    observation_id = new_uuid4()
    with UnitOfWork(factory) as uow:
        _seed_run(uow, run_id=field_run)
        uow.connection.execute(
            "INSERT INTO source_observations("
            "source_observation_id,import_run_id,source_family,entity_kind,identity_state,canonical_primary_id,canonical_parent_rfc_no,"
            "row_ordinal,sheet_ordinal,row_logical_sha256,source_row_chronology_utc,presence_state,recorded_at_utc) "
            "VALUES (?,?,'rfc_enhanced','rfc','valid','NC20260913000001',NULL,1,1,?,NULL,'observed_valid_identity',2)",
            (observation_id, field_run, "a" * 64),
        )
        uow.connection.execute(
            "INSERT INTO source_observation_fields("
            "source_observation_field_id,source_observation_id,field_key,field_class,value_state,value_kind,source_text,"
            "normalized_text,integer_value,vocabulary_id,field_logical_sha256) "
            "VALUES (?,?, 'summary','deferred','usable','text','A','A',NULL,NULL,?)",
            (new_uuid4(), observation_id, "b" * 64),
        )
        with pytest.raises(SomaError) as exc:
            SourceObservationRepository.load_validating_evidence(
                uow.connection,
                import_run_id=field_run,
                expected_run_revision=1,
            )
        assert exc.value.code == "IMPORT_SOURCE_PROFILE_MISMATCH"


def test_reader_rejects_noncanonical_persisted_identifiers_and_stale_revision(initialized_database) -> None:
    factory = _factory(initialized_database)
    run_id = new_uuid4()
    with UnitOfWork(factory) as uow:
        _seed_run(uow, run_id=run_id)
        uow.connection.execute(
            "INSERT INTO source_observations("
            "source_observation_id,import_run_id,source_family,entity_kind,identity_state,canonical_primary_id,canonical_parent_rfc_no,"
            "row_ordinal,sheet_ordinal,row_logical_sha256,source_row_chronology_utc,presence_state,recorded_at_utc) "
            "VALUES ('not-a-uuid',?,'rfc_enhanced','rfc','valid','NC20260913000001',NULL,1,1,?,NULL,"
            "'observed_valid_identity',2)",
            (run_id, "a" * 64),
        )
        with pytest.raises(IntegrityFailure):
            SourceObservationRepository.load_validating_evidence(
                uow.connection,
                import_run_id=run_id,
                expected_run_revision=1,
            )

    stale_run = new_uuid4()
    with UnitOfWork(factory) as uow:
        _seed_run(uow, run_id=stale_run)
        with pytest.raises(SomaError) as exc:
            SourceObservationRepository.load_validating_evidence(
                uow.connection,
                import_run_id=stale_run,
                expected_run_revision=2,
            )
        assert exc.value.code == "IMPORT_RUN_STALE"
