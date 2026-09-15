from __future__ import annotations

import pytest

from soma.foundation.errors import IntegrityFailure
from soma.foundation.identifiers import new_uuid4
from soma.foundation.persistence.uow import UnitOfWork
from soma.ticket_import.reconciliation.advanced_search_disappearance import (
    build_advanced_search_sr_disappearance_proposals,
)


def _factory(initialized_database):
    database_path, factory_for_path = initialized_database
    return factory_for_path(database_path)


def _insert_run(
    uow: UnitOfWork,
    *,
    run_id: str,
    chronology: int,
    state: str,
    fingerprint: str | None = None,
) -> None:
    staged = None if state == "validating" else 2
    completed = 3 if state in {"accepted", "partially_accepted", "rejected", "noop"} else None
    uow.connection.execute(
        "INSERT INTO import_runs(import_run_id,source_family,invocation_kind,source_profile_id,"
        "header_registry_id,vocabulary_registry_id,parser_profile_id,candidate_filename,"
        "candidate_file_size_bytes,candidate_stable_mtime_ns,candidate_chronology_kind,"
        "candidate_chronology_value,logical_fingerprint_sha256,run_state,started_at_utc,"
        "staged_at_utc,completed_at_utc,revision) "
        "VALUES (?,'advanced_search_sr','manual','ADVANCED_SEARCH_SR_V1','ADVANCED_SEARCH_HEADERS_V1',"
        "'ADVANCED_SEARCH_VOCAB_V1','ADVANCED_SEARCH_PARSER_V1','source.xlsx',1,1,"
        "'embedded_filename_timestamp_utc',?,?,?,?,?,?,1)",
        (run_id, chronology, fingerprint, state, 1, staged, completed),
    )


def _insert_observation(
    uow: UnitOfWork,
    *,
    run_id: str,
    sr_no: str,
    row_ordinal: int,
    row_hash: str,
) -> str:
    observation_id = new_uuid4()
    uow.connection.execute(
        "INSERT INTO source_observations(source_observation_id,import_run_id,source_family,entity_kind,"
        "identity_state,canonical_primary_id,canonical_parent_rfc_no,row_ordinal,sheet_ordinal,"
        "row_logical_sha256,source_row_chronology_utc,presence_state,recorded_at_utc) "
        "VALUES (?,?,'advanced_search_sr','service_request','valid',?,NULL,?,1,?,NULL,"
        "'observed_valid_identity',1)",
        (observation_id, run_id, sr_no, row_ordinal, row_hash),
    )
    return observation_id


def _insert_sr(uow: UnitOfWork, sr_no: str) -> str:
    sr_id = new_uuid4()
    uow.connection.execute(
        "INSERT INTO service_requests(service_request_id,official_sr_no,revision,created_at_utc,updated_at_utc) "
        "VALUES (?,?,1,1,1)",
        (sr_id, sr_no),
    )
    return sr_id


def _checkpoint(uow: UnitOfWork, *, accepted_run_id: str, chronology: int, fingerprint: str) -> None:
    uow.connection.execute(
        "INSERT INTO import_source_checkpoints(source_family,source_profile_id,"
        "accepted_candidate_chronology_kind,accepted_candidate_chronology_value,"
        "accepted_logical_fingerprint_sha256,accepted_import_run_id,last_checked_at_utc,revision) "
        "VALUES ('advanced_search_sr','ADVANCED_SEARCH_SR_V1','embedded_filename_timestamp_utc',?,?,?,3,1)",
        (chronology, fingerprint, accepted_run_id),
    )


def test_disappearance_uses_valid_identity_population_even_when_current_rows_conflict(
    initialized_database,
) -> None:
    factory = _factory(initialized_database)
    fingerprint = "a" * 64
    prior_run = new_uuid4()
    current_run = new_uuid4()
    with UnitOfWork(factory) as uow:
        _insert_run(uow, run_id=prior_run, chronology=10, state="accepted", fingerprint=fingerprint)
        _insert_observation(uow, run_id=prior_run, sr_no="12345678", row_ordinal=1, row_hash="1" * 64)
        prior_missing_observation = _insert_observation(
            uow, run_id=prior_run, sr_no="87654321", row_ordinal=2, row_hash="2" * 64
        )
        _checkpoint(uow, accepted_run_id=prior_run, chronology=10, fingerprint=fingerprint)
        _insert_sr(uow, "12345678")
        missing_sr_id = _insert_sr(uow, "87654321")
        _insert_run(uow, run_id=current_run, chronology=11, state="validating")
        _insert_observation(uow, run_id=current_run, sr_no="12345678", row_ordinal=1, row_hash="3" * 64)
        _insert_observation(uow, run_id=current_run, sr_no="12345678", row_ordinal=2, row_hash="4" * 64)

        proposals = build_advanced_search_sr_disappearance_proposals(
            uow.connection,
            import_run_id=current_run,
            logical_fingerprint_sha256="b" * 64,
        )

    assert len(proposals) == 1
    proposal = proposals[0]
    assert proposal.target_internal_id == missing_sr_id
    assert proposal.target_business_id == "87654321"
    assert proposal.prior_source_observation_id == prior_missing_observation
    assert proposal.changes[0].field_key == "source_presence"
    assert proposal.changes[0].change_kind == "absent"
    assert proposal.changes[0].before_text == "87654321"
    assert proposal.changes[0].after_text is None


def test_disappearance_resolves_row_bearing_population_behind_newer_identical_noop(
    initialized_database,
) -> None:
    factory = _factory(initialized_database)
    fingerprint = "c" * 64
    prior_run = new_uuid4()
    noop_run = new_uuid4()
    current_run = new_uuid4()
    with UnitOfWork(factory) as uow:
        _insert_run(uow, run_id=prior_run, chronology=10, state="accepted", fingerprint=fingerprint)
        prior_observation = _insert_observation(
            uow, run_id=prior_run, sr_no="11223344", row_ordinal=1, row_hash="5" * 64
        )
        _insert_run(uow, run_id=noop_run, chronology=20, state="noop", fingerprint=fingerprint)
        _checkpoint(uow, accepted_run_id=noop_run, chronology=20, fingerprint=fingerprint)
        sr_id = _insert_sr(uow, "11223344")
        _insert_run(uow, run_id=current_run, chronology=21, state="validating")

        proposals = build_advanced_search_sr_disappearance_proposals(
            uow.connection,
            import_run_id=current_run,
            logical_fingerprint_sha256="d" * 64,
        )

    assert len(proposals) == 1
    assert proposals[0].target_internal_id == sr_id
    assert proposals[0].prior_source_observation_id == prior_observation


def test_disappearance_without_prior_checkpoint_has_no_population_absence(initialized_database) -> None:
    factory = _factory(initialized_database)
    current_run = new_uuid4()
    with UnitOfWork(factory) as uow:
        _insert_run(uow, run_id=current_run, chronology=1, state="validating")
        assert build_advanced_search_sr_disappearance_proposals(
            uow.connection,
            import_run_id=current_run,
            logical_fingerprint_sha256="e" * 64,
        ) == ()


def test_checkpoint_without_row_bearing_logical_population_fails_closed(initialized_database) -> None:
    factory = _factory(initialized_database)
    fingerprint = "f" * 64
    noop_run = new_uuid4()
    current_run = new_uuid4()
    with UnitOfWork(factory) as uow:
        _insert_run(uow, run_id=noop_run, chronology=20, state="noop", fingerprint=fingerprint)
        _checkpoint(uow, accepted_run_id=noop_run, chronology=20, fingerprint=fingerprint)
        _insert_run(uow, run_id=current_run, chronology=21, state="validating")
        with pytest.raises(IntegrityFailure, match="row-bearing published representative"):
            build_advanced_search_sr_disappearance_proposals(
                uow.connection,
                import_run_id=current_run,
                logical_fingerprint_sha256="0" * 64,
            )
