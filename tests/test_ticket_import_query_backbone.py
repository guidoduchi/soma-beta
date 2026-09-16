from __future__ import annotations

import pytest

from soma.foundation.errors import SomaError
from soma.foundation.identifiers import new_uuid4
from soma.foundation.persistence.uow import UnitOfWork
from soma.ticket_import.queries.proposals import ImportRecoveryQueryService
from soma.ticket_import.queries.runs import ImportRunQueryService
from soma.ticket_import.queries.source_status import ImportSourceStatusQueryService


def _factory(initialized_database):
    database_path, factory_builder = initialized_database
    return factory_builder(database_path)


def _run(
    uow,
    *,
    run_id: str,
    state: str,
    chronology: int,
    fingerprint: str,
    started: int,
    invocation: str = "manual",
) -> None:
    terminal = state in {"accepted", "rejected", "partially_accepted", "noop", "failed"}
    uow.connection.execute(
        "INSERT INTO import_runs(import_run_id,source_family,invocation_kind,source_profile_id,"
        "header_registry_id,vocabulary_registry_id,parser_profile_id,candidate_filename,"
        "candidate_file_size_bytes,candidate_stable_mtime_ns,candidate_chronology_kind,"
        "candidate_chronology_value,logical_fingerprint_sha256,run_state,started_at_utc,"
        "staged_at_utc,completed_at_utc,revision) VALUES (?,'advanced_search_sr',?,"
        "'ADVANCED_SEARCH_SR_V1','ADVANCED_SEARCH_HEADERS_V1','ADVANCED_SEARCH_VOCAB_V1',"
        "'ADVANCED_SEARCH_PARSER_V1','source.xlsx',1,1,'embedded_filename_timestamp_utc',"
        "?,?,?,?,?,?,2)",
        (
            run_id,
            invocation,
            chronology,
            fingerprint,
            state,
            started,
            started,
            started if terminal else None,
        ),
    )


def _seed_query_runs(factory):
    checkpoint_run_id = new_uuid4()
    staged_run_id = new_uuid4()
    recovery_run_id = new_uuid4()
    with UnitOfWork(factory) as uow:
        _run(
            uow,
            run_id=checkpoint_run_id,
            state="accepted",
            chronology=20,
            fingerprint="1" * 64,
            started=1,
        )
        _run(
            uow,
            run_id=staged_run_id,
            state="staged",
            chronology=30,
            fingerprint="2" * 64,
            started=3,
        )
        _run(
            uow,
            run_id=recovery_run_id,
            state="recovery_required",
            chronology=20,
            fingerprint="3" * 64,
            started=2,
            invocation="recovery",
        )
        uow.connection.execute(
            "INSERT INTO import_source_checkpoints(source_family,source_profile_id,"
            "accepted_candidate_chronology_kind,accepted_candidate_chronology_value,"
            "accepted_logical_fingerprint_sha256,accepted_import_run_id,last_checked_at_utc,revision) "
            "VALUES ('advanced_search_sr','ADVANCED_SEARCH_SR_V1',"
            "'embedded_filename_timestamp_utc',20,?,?,1,1)",
            ("1" * 64, checkpoint_run_id),
        )
    return checkpoint_run_id, staged_run_id, recovery_run_id


def test_source_status_and_run_detail_use_one_read_projection(initialized_database) -> None:
    factory = _factory(initialized_database)
    _checkpoint_run_id, staged_run_id, _recovery_run_id = _seed_query_runs(factory)

    status = ImportSourceStatusQueryService(factory).get_status("advanced_search_sr")
    assert status.configured is False
    assert status.latest_run is not None
    assert status.latest_run.import_run_id == staged_run_id
    assert status.checkpoint is not None
    assert status.checkpoint["chronology_value"] == 20

    detail = ImportRunQueryService(factory).get_run(staged_run_id)
    assert detail.checkpoint_comparison["classification"] == "newer_changed"
    assert detail.review_state["can_finalize"] is True
    assert detail.run.to_response()["counts"]["pending"] == 0


def test_run_list_cursor_is_descending_and_filter_bound(initialized_database) -> None:
    factory = _factory(initialized_database)
    _seed_query_runs(factory)
    service = ImportRunQueryService(factory)

    first = service.list_runs(source_family="advanced_search_sr", limit=2)
    assert [item.started_at_utc for item in first.items] == [3, 2]
    assert first.next_cursor is not None
    second = service.list_runs(
        source_family="advanced_search_sr",
        cursor=first.next_cursor,
        limit=2,
    )
    assert [item.started_at_utc for item in second.items] == [1]

    with pytest.raises(SomaError) as excinfo:
        service.list_runs(state="accepted", cursor=first.next_cursor, limit=2)
    assert excinfo.value.code == "IMPORT_CURSOR_INVALID"


def test_recovery_preview_exposes_exact_fingerprint_and_allowed_actions(initialized_database) -> None:
    factory = _factory(initialized_database)
    _checkpoint_run_id, _staged_run_id, recovery_run_id = _seed_query_runs(factory)

    preview = ImportRecoveryQueryService(factory).preview(recovery_run_id)
    response = preview.to_response()
    assert response["classification"] == "equal_chronology_different_content"
    assert response["allowed_actions"] == ["reject", "defer", "authorize_correction"]
    assert len(str(response["review_fingerprint"])) == 64

    detail = ImportRunQueryService(factory).get_run(recovery_run_id)
    assert detail.checkpoint_comparison["classification"] == "equal_chronology_changed"
    assert detail.review_state == {
        "pending": 0,
        "accepted": 0,
        "rejected": 0,
        "deferred": 0,
        "can_finalize": False,
        "recovery_authorized": False,
    }
