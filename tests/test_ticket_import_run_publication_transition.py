from __future__ import annotations

import pytest

from soma.foundation.errors import IntegrityFailure, SomaError
from soma.foundation.identifiers import new_uuid4
from soma.foundation.persistence.uow import ReadSnapshot, UnitOfWork
from soma.ticket_import.repositories.proposals import (
    PendingProposalWrite,
    ProposalChangeRecord,
    ProposalRepository,
)
from soma.ticket_import.repositories.runs import ImportRunRepository


def _factory(initialized_database):
    database_path, factory_for_path = initialized_database
    return factory_for_path(database_path)


def _seed_run(uow: UnitOfWork, *, run_id: str, observed_counter: int = 0) -> None:
    uow.connection.execute(
        "INSERT INTO import_runs("
        "import_run_id,source_family,invocation_kind,source_profile_id,header_registry_id,vocabulary_registry_id,parser_profile_id,"
        "candidate_filename,candidate_file_size_bytes,candidate_stable_mtime_ns,candidate_chronology_kind,candidate_chronology_value,"
        "run_state,started_at_utc,observed_row_count,revision) "
        "VALUES (?,'wfm_service_provider','manual','WFM_SERVICE_PROVIDER_V1','WFM_HEADERS_V1','WFM_VOCAB_V1','WFM_PARSER_V1',"
        "'WFM Service Provider.xlsx',100,1,'embedded_filename_timestamp_utc',10,'validating',10,?,1)",
        (run_id, observed_counter),
    )


def _seed_valid_observation(
    uow: UnitOfWork,
    *,
    run_id: str,
    observation_id: str,
    row_ordinal: int,
    task_no: str = "TK00000000004444",
) -> None:
    uow.connection.execute(
        "INSERT INTO source_observations("
        "source_observation_id,import_run_id,source_family,entity_kind,identity_state,canonical_primary_id,canonical_parent_rfc_no,"
        "row_ordinal,sheet_ordinal,row_logical_sha256,source_row_chronology_utc,presence_state,recorded_at_utc"
        ") VALUES (?,?,'wfm_service_provider','wfm','valid',?,'NC00000000008888',?,1,?,10,'observed_valid_identity',10)",
        (observation_id, run_id, task_no, row_ordinal, f"{row_ordinal:x}".rjust(64, "a")[-64:]),
    )


def _seed_invalid_observation(uow: UnitOfWork, *, run_id: str, observation_id: str, row_ordinal: int) -> None:
    uow.connection.execute(
        "INSERT INTO source_observations("
        "source_observation_id,import_run_id,source_family,entity_kind,identity_state,canonical_primary_id,canonical_parent_rfc_no,"
        "row_ordinal,sheet_ordinal,row_logical_sha256,source_row_chronology_utc,presence_state,recorded_at_utc"
        ") VALUES (?,?,'wfm_service_provider','invalid_row','invalid',NULL,NULL,?,1,?,NULL,'observed_invalid_identity',10)",
        (observation_id, run_id, row_ordinal, f"{row_ordinal + 100:x}".rjust(64, "b")[-64:]),
    )


def _seed_finding(
    uow: UnitOfWork,
    *,
    run_id: str,
    observation_id: str | None,
    severity: str,
    code: str,
) -> None:
    uow.connection.execute(
        "INSERT INTO import_findings(import_finding_id,import_run_id,source_observation_id,field_key,finding_code,severity,"
        "scope_kind,message_text,recorded_at_utc) VALUES (?,?,?,NULL,?,?, 'row',?,10)",
        (new_uuid4(), run_id, observation_id, code, severity, f"{code} finding"),
    )


def _insert_pending_proposal(
    uow: UnitOfWork,
    *,
    run_id: str,
    observation_id: str,
) -> str:
    result = ProposalRepository.insert_or_reuse_pending(
        uow,
        PendingProposalWrite(
            import_run_id=run_id,
            evidence_mode="observed_row",
            source_observation_id=observation_id,
            prior_source_observation_id=None,
            proposal_kind="wfm_competing_attempt_review",
            target_kind="activity_lineage",
            target_internal_id=new_uuid4(),
            target_business_id="TK00000000004444",
            risk_class="high",
            base_state_token="c" * 64,
            proposal_fingerprint="d" * 64,
            changes=(
                ProposalChangeRecord(
                    ordinal=0,
                    field_key="competing_attempt_counterpart",
                    change_kind="conflict",
                    value_kind="identity",
                    before_text=None,
                    after_text=new_uuid4(),
                    before_integer=None,
                    after_integer=None,
                    source_observation_field_id=None,
                ),
            ),
        ),
    )
    return result.proposal_id


def test_waiting_review_publication_derives_exact_physical_and_warning_counts(initialized_database) -> None:
    factory = _factory(initialized_database)
    run_id = new_uuid4()
    first = new_uuid4()
    duplicate = new_uuid4()
    invalid = new_uuid4()

    with UnitOfWork(factory) as uow:
        _seed_run(uow, run_id=run_id)
        _seed_valid_observation(uow, run_id=run_id, observation_id=first, row_ordinal=1)
        _seed_valid_observation(uow, run_id=run_id, observation_id=duplicate, row_ordinal=2)
        _seed_invalid_observation(uow, run_id=run_id, observation_id=invalid, row_ordinal=3)
        _seed_finding(uow, run_id=run_id, observation_id=first, severity="warning", code="W")
        _seed_finding(uow, run_id=run_id, observation_id=first, severity="high_risk", code="H")
        _seed_finding(uow, run_id=run_id, observation_id=invalid, severity="error", code="E")
        _seed_finding(uow, run_id=run_id, observation_id=None, severity="info", code="I")
        _insert_pending_proposal(uow, run_id=run_id, observation_id=first)
        result = ImportRunRepository.publish_validating_run(
            uow,
            import_run_id=run_id,
            expected_revision=1,
            logical_fingerprint="f" * 64,
            staged_at_utc=20,
            target_state="waiting_review",
        )
        assert result.run_state == "waiting_review"
        assert result.revision == 2
        assert result.counters.observed_row_count == 3
        assert result.counters.valid_identity_count == 2
        assert result.counters.invalid_row_count == 1
        assert result.counters.warning_count == 1
        assert result.counters.proposal_count == 1
        assert result.counters.pending_proposal_count == 1

    with ReadSnapshot(factory) as snapshot:
        row = snapshot.connection.execute(
            "SELECT run_state,logical_fingerprint_sha256,staged_at_utc,observed_row_count,valid_identity_count,"
            "invalid_row_count,warning_count,proposal_count,pending_proposal_count,accepted_proposal_count,"
            "rejected_proposal_count,deferred_proposal_count,revision FROM import_runs WHERE import_run_id=?",
            (run_id,),
        ).fetchone()
        assert tuple(row) == (
            "waiting_review",
            "f" * 64,
            20,
            3,
            2,
            1,
            1,
            1,
            1,
            0,
            0,
            0,
            2,
        )


def test_staged_publication_requires_zero_pending_proposals(initialized_database) -> None:
    factory = _factory(initialized_database)
    run_id = new_uuid4()
    observation_id = new_uuid4()
    with UnitOfWork(factory) as uow:
        _seed_run(uow, run_id=run_id)
        _seed_valid_observation(uow, run_id=run_id, observation_id=observation_id, row_ordinal=1)
        result = ImportRunRepository.publish_validating_run(
            uow,
            import_run_id=run_id,
            expected_revision=1,
            logical_fingerprint="a" * 64,
            staged_at_utc=20,
            target_state="staged",
        )
        assert result.counters.proposal_count == 0

    with ReadSnapshot(factory) as snapshot:
        row = snapshot.connection.execute(
            "SELECT run_state,proposal_count,pending_proposal_count,revision FROM import_runs WHERE import_run_id=?",
            (run_id,),
        ).fetchone()
        assert tuple(row) == ("staged", 0, 0, 2)


def test_waiting_review_rejects_zero_pending_proposals_without_publication(initialized_database) -> None:
    factory = _factory(initialized_database)
    run_id = new_uuid4()
    with UnitOfWork(factory) as uow:
        _seed_run(uow, run_id=run_id)
        with pytest.raises(SomaError) as exc:
            ImportRunRepository.publish_validating_run(
                uow,
                import_run_id=run_id,
                expected_revision=1,
                logical_fingerprint="a" * 64,
                staged_at_utc=20,
                target_state="waiting_review",
            )
        assert exc.value.code == "IMPORT_RUN_STALE"

    with ReadSnapshot(factory) as snapshot:
        row = snapshot.connection.execute(
            "SELECT run_state,logical_fingerprint_sha256,revision FROM import_runs WHERE import_run_id=?",
            (run_id,),
        ).fetchone()
        assert tuple(row) == ("validating", None, 1)


def test_staged_rejects_current_pending_proposal(initialized_database) -> None:
    factory = _factory(initialized_database)
    run_id = new_uuid4()
    observation_id = new_uuid4()
    with UnitOfWork(factory) as uow:
        _seed_run(uow, run_id=run_id)
        _seed_valid_observation(uow, run_id=run_id, observation_id=observation_id, row_ordinal=1)
        _insert_pending_proposal(uow, run_id=run_id, observation_id=observation_id)
        with pytest.raises(SomaError) as exc:
            ImportRunRepository.publish_validating_run(
                uow,
                import_run_id=run_id,
                expected_revision=1,
                logical_fingerprint="a" * 64,
                staged_at_utc=20,
                target_state="staged",
            )
        assert exc.value.code == "IMPORT_RUN_STALE"
        assert uow.connection.execute(
            "SELECT run_state FROM import_runs WHERE import_run_id=?", (run_id,)
        ).fetchone()[0] == "validating"


def test_recovery_required_allows_zero_pending_proposals(initialized_database) -> None:
    factory = _factory(initialized_database)
    run_id = new_uuid4()
    with UnitOfWork(factory) as uow:
        _seed_run(uow, run_id=run_id)
        result = ImportRunRepository.publish_validating_run(
            uow,
            import_run_id=run_id,
            expected_revision=1,
            logical_fingerprint="e" * 64,
            staged_at_utc=20,
            target_state="recovery_required",
        )
        assert result.run_state == "recovery_required"
        assert result.counters.pending_proposal_count == 0


def test_noop_publication_requires_complete_unpublished_cleanup(initialized_database) -> None:
    factory = _factory(initialized_database)
    blocked_run_id = new_uuid4()
    blocked_observation_id = new_uuid4()
    with UnitOfWork(factory) as uow:
        _seed_run(uow, run_id=blocked_run_id)
        _seed_valid_observation(uow, run_id=blocked_run_id, observation_id=blocked_observation_id, row_ordinal=1)
        _seed_finding(uow, run_id=blocked_run_id, observation_id=blocked_observation_id, severity="warning", code="W")
        with pytest.raises(SomaError) as exc:
            ImportRunRepository.publish_validating_run(
                uow,
                import_run_id=blocked_run_id,
                expected_revision=1,
                logical_fingerprint="1" * 64,
                staged_at_utc=20,
                target_state="noop",
                completed_at_utc=20,
            )
        assert exc.value.code == "IMPORT_RUN_STALE"

    clean_run_id = new_uuid4()
    with UnitOfWork(factory) as uow:
        _seed_run(uow, run_id=clean_run_id)
        result = ImportRunRepository.publish_validating_run(
            uow,
            import_run_id=clean_run_id,
            expected_revision=1,
            logical_fingerprint="2" * 64,
            staged_at_utc=20,
            target_state="noop",
            completed_at_utc=21,
        )
        assert result.run_state == "noop"

    with ReadSnapshot(factory) as snapshot:
        row = snapshot.connection.execute(
            "SELECT run_state,staged_at_utc,completed_at_utc,revision FROM import_runs WHERE import_run_id=?",
            (clean_run_id,),
        ).fetchone()
        assert tuple(row) == ("noop", 20, 21, 2)


def test_noop_pending_checkpoint_requires_empty_evidence_and_remains_nonterminal(initialized_database) -> None:
    factory = _factory(initialized_database)
    run_id = new_uuid4()
    with UnitOfWork(factory) as uow:
        _seed_run(uow, run_id=run_id)
        result = ImportRunRepository.publish_validating_run(
            uow,
            import_run_id=run_id,
            expected_revision=1,
            logical_fingerprint="3" * 64,
            staged_at_utc=20,
            target_state="noop_pending_checkpoint",
        )
        assert result.run_state == "noop_pending_checkpoint"

    with ReadSnapshot(factory) as snapshot:
        row = snapshot.connection.execute(
            "SELECT run_state,completed_at_utc,revision FROM import_runs WHERE import_run_id=?",
            (run_id,),
        ).fetchone()
        assert tuple(row) == ("noop_pending_checkpoint", None, 2)


def test_validating_run_with_terminal_proposal_fails_closed(initialized_database) -> None:
    factory = _factory(initialized_database)
    run_id = new_uuid4()
    observation_id = new_uuid4()
    with UnitOfWork(factory) as uow:
        _seed_run(uow, run_id=run_id)
        _seed_valid_observation(uow, run_id=run_id, observation_id=observation_id, row_ordinal=1)
        uow.connection.execute(
            "INSERT INTO reconciliation_proposals("
            "reconciliation_proposal_id,import_run_id,evidence_mode,source_observation_id,proposal_kind,target_kind,"
            "target_internal_id,target_business_id,risk_class,base_state_token_sha256,proposal_fingerprint_sha256,"
            "proposal_state,created_at_utc,revision,decided_at_utc) "
            "VALUES (?,?,'observed_row',?,'wfm_competing_attempt_review','activity_lineage',?,'TK00000000004444',"
            "'high',?,?,'accepted',10,1,10)",
            (new_uuid4(), run_id, observation_id, new_uuid4(), "a" * 64, "b" * 64),
        )
        with pytest.raises(IntegrityFailure):
            ImportRunRepository.publish_validating_run(
                uow,
                import_run_id=run_id,
                expected_revision=1,
                logical_fingerprint="4" * 64,
                staged_at_utc=20,
                target_state="recovery_required",
            )


def test_existing_partial_publication_counter_fails_closed(initialized_database) -> None:
    factory = _factory(initialized_database)
    run_id = new_uuid4()
    with UnitOfWork(factory) as uow:
        _seed_run(uow, run_id=run_id, observed_counter=1)
        with pytest.raises(IntegrityFailure):
            ImportRunRepository.publish_validating_run(
                uow,
                import_run_id=run_id,
                expected_revision=1,
                logical_fingerprint="5" * 64,
                staged_at_utc=20,
                target_state="staged",
            )


def test_stale_revision_and_outer_uow_failure_leave_run_unpublished(initialized_database) -> None:
    factory = _factory(initialized_database)
    stale_run_id = new_uuid4()
    with UnitOfWork(factory) as uow:
        _seed_run(uow, run_id=stale_run_id)
        with pytest.raises(SomaError) as exc:
            ImportRunRepository.publish_validating_run(
                uow,
                import_run_id=stale_run_id,
                expected_revision=2,
                logical_fingerprint="6" * 64,
                staged_at_utc=20,
                target_state="staged",
            )
        assert exc.value.code == "IMPORT_RUN_STALE"

    rollback_run_id = new_uuid4()
    with UnitOfWork(factory) as uow:
        _seed_run(uow, run_id=rollback_run_id)

    with pytest.raises(RuntimeError):
        with UnitOfWork(factory) as uow:
            ImportRunRepository.publish_validating_run(
                uow,
                import_run_id=rollback_run_id,
                expected_revision=1,
                logical_fingerprint="7" * 64,
                staged_at_utc=20,
                target_state="staged",
            )
            raise RuntimeError("inject rollback")

    with ReadSnapshot(factory) as snapshot:
        stale = snapshot.connection.execute(
            "SELECT run_state,logical_fingerprint_sha256,revision FROM import_runs WHERE import_run_id=?",
            (stale_run_id,),
        ).fetchone()
        rollback = snapshot.connection.execute(
            "SELECT run_state,logical_fingerprint_sha256,revision FROM import_runs WHERE import_run_id=?",
            (rollback_run_id,),
        ).fetchone()
        assert tuple(stale) == ("validating", None, 1)
        assert tuple(rollback) == ("validating", None, 1)
