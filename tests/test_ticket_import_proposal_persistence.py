from __future__ import annotations

import pytest

from soma.foundation.errors import IntegrityFailure, SomaError, ValidationError
from soma.foundation.identifiers import new_uuid4, require_uuid4
from soma.foundation.persistence.uow import ReadSnapshot, UnitOfWork
from soma.ticket_import.repositories.proposals import (
    PendingProposalWrite,
    ProposalChangeRecord,
    ProposalRepository,
)


def _factory(initialized_database):
    database_path, factory_for_path = initialized_database
    return factory_for_path(database_path)


def _seed_run_and_observation(uow: UnitOfWork, *, run_id: str, observation_id: str, state: str = "validating") -> None:
    if state == "validating":
        logical_fingerprint = None
        staged_at = None
    else:
        logical_fingerprint = "f" * 64
        staged_at = 1
    uow.connection.execute(
        "INSERT INTO import_runs("
        "import_run_id,source_family,invocation_kind,source_profile_id,header_registry_id,vocabulary_registry_id,parser_profile_id,"
        "candidate_filename,candidate_file_size_bytes,candidate_stable_mtime_ns,candidate_chronology_kind,candidate_chronology_value,"
        "logical_fingerprint_sha256,run_state,started_at_utc,staged_at_utc,observed_row_count,valid_identity_count,revision"
        ") VALUES (?,'wfm_service_provider','manual','WFM_SERVICE_PROVIDER_V1','WFM_HEADERS_V1','WFM_VOCAB_V1','WFM_PARSER_V1',"
        "'WFM Service Provider.xlsx',100,1,'embedded_filename_timestamp_utc',10,?,?,0,?,1,1,1)",
        (run_id, logical_fingerprint, state, staged_at),
    )
    uow.connection.execute(
        "INSERT INTO source_observations("
        "source_observation_id,import_run_id,source_family,entity_kind,identity_state,canonical_primary_id,canonical_parent_rfc_no,"
        "row_ordinal,sheet_ordinal,row_logical_sha256,source_row_chronology_utc,presence_state,recorded_at_utc"
        ") VALUES (?,?,'wfm_service_provider','wfm','valid','TK00000000004444','NC00000000008888',"
        "1,1,?,10,'observed_valid_identity',1)",
        (observation_id, run_id, "e" * 64),
    )


def _write(
    *,
    run_id: str,
    observation_id: str,
    lineage_id: str,
    counterpart_id: str,
    base_state_token: str = "a" * 64,
    proposal_fingerprint: str = "b" * 64,
    ordinal: int = 0,
) -> PendingProposalWrite:
    return PendingProposalWrite(
        import_run_id=run_id,
        evidence_mode="observed_row",
        source_observation_id=observation_id,
        prior_source_observation_id=None,
        proposal_kind="wfm_competing_attempt_review",
        target_kind="activity_lineage",
        target_internal_id=lineage_id,
        target_business_id="TK00000000004444",
        risk_class="high",
        base_state_token=base_state_token,
        proposal_fingerprint=proposal_fingerprint,
        changes=(
            ProposalChangeRecord(
                ordinal=ordinal,
                field_key="competing_attempt_counterpart",
                change_kind="conflict",
                value_kind="identity",
                before_text=None,
                after_text=counterpart_id,
                before_integer=None,
                after_integer=None,
                source_observation_field_id=None,
            ),
        ),
    )


def test_insert_then_exact_reuse_preserves_one_immutable_proposal(initialized_database) -> None:
    factory = _factory(initialized_database)
    run_id = new_uuid4()
    observation_id = new_uuid4()
    lineage_id = new_uuid4()
    counterpart_id = new_uuid4()
    write = _write(
        run_id=run_id,
        observation_id=observation_id,
        lineage_id=lineage_id,
        counterpart_id=counterpart_id,
    )

    with UnitOfWork(factory) as uow:
        _seed_run_and_observation(uow, run_id=run_id, observation_id=observation_id)
        created = ProposalRepository.insert_or_reuse_pending(uow, write)
        reused = ProposalRepository.insert_or_reuse_pending(uow, write)
        require_uuid4(created.proposal_id)
        assert created.reused is False
        assert reused.reused is True
        assert reused.proposal_id == created.proposal_id

    with ReadSnapshot(factory) as snapshot:
        proposal = snapshot.connection.execute(
            "SELECT reconciliation_proposal_id,proposal_state,revision,base_state_token_sha256,proposal_fingerprint_sha256 "
            "FROM reconciliation_proposals"
        ).fetchall()
        assert proposal == [(created.proposal_id, "pending", 1, "a" * 64, "b" * 64)]
        changes = snapshot.connection.execute(
            "SELECT ordinal,field_key,change_kind,value_kind,before_text,after_text,before_integer,after_integer "
            "FROM reconciliation_proposal_changes"
        ).fetchall()
        assert changes == [(0, "competing_attempt_counterpart", "conflict", "identity", None, counterpart_id, None, None)]
        counters = snapshot.connection.execute(
            "SELECT proposal_count,pending_proposal_count,revision FROM import_runs WHERE import_run_id=?",
            (run_id,),
        ).fetchone()
        assert counters == (0, 0, 1)


def test_exact_metadata_with_different_change_evidence_fails_closed(initialized_database) -> None:
    factory = _factory(initialized_database)
    run_id = new_uuid4()
    observation_id = new_uuid4()
    lineage_id = new_uuid4()
    counterpart_id = new_uuid4()
    conflicting_counterpart_id = new_uuid4()
    existing_proposal_id = new_uuid4()
    write = _write(
        run_id=run_id,
        observation_id=observation_id,
        lineage_id=lineage_id,
        counterpart_id=counterpart_id,
    )

    with UnitOfWork(factory) as uow:
        _seed_run_and_observation(uow, run_id=run_id, observation_id=observation_id)
        uow.connection.execute(
            "INSERT INTO reconciliation_proposals("
            "reconciliation_proposal_id,import_run_id,evidence_mode,source_observation_id,prior_source_observation_id,proposal_kind,"
            "target_kind,target_internal_id,target_business_id,risk_class,base_state_token_sha256,proposal_fingerprint_sha256,"
            "proposal_state,created_at_utc,revision,decided_at_utc) "
            "VALUES (?,?,'observed_row',?,NULL,'wfm_competing_attempt_review','activity_lineage',?,'TK00000000004444',"
            "'high',?,?,'pending',1,1,NULL)",
            (existing_proposal_id, run_id, observation_id, lineage_id, "a" * 64, "b" * 64),
        )
        uow.connection.execute(
            "INSERT INTO reconciliation_proposal_changes("
            "reconciliation_proposal_id,ordinal,field_key,change_kind,value_kind,before_text,after_text,before_integer,after_integer,"
            "source_observation_field_id) VALUES (?,0,'competing_attempt_counterpart','conflict','identity',NULL,?,NULL,NULL,NULL)",
            (existing_proposal_id, conflicting_counterpart_id),
        )
        with pytest.raises(IntegrityFailure):
            ProposalRepository.insert_or_reuse_pending(uow, write)


def test_cross_run_observation_cannot_back_new_proposal(initialized_database) -> None:
    factory = _factory(initialized_database)
    source_run_id = new_uuid4()
    target_run_id = new_uuid4()
    observation_id = new_uuid4()
    write = _write(
        run_id=target_run_id,
        observation_id=observation_id,
        lineage_id=new_uuid4(),
        counterpart_id=new_uuid4(),
    )

    with UnitOfWork(factory) as uow:
        _seed_run_and_observation(uow, run_id=source_run_id, observation_id=observation_id)
        uow.connection.execute(
            "INSERT INTO import_runs("
            "import_run_id,source_family,invocation_kind,source_profile_id,header_registry_id,vocabulary_registry_id,parser_profile_id,"
            "candidate_filename,candidate_file_size_bytes,candidate_stable_mtime_ns,candidate_chronology_kind,candidate_chronology_value,"
            "run_state,started_at_utc,revision) VALUES (?,'wfm_service_provider','manual','WFM_SERVICE_PROVIDER_V1','WFM_HEADERS_V1',"
            "'WFM_VOCAB_V1','WFM_PARSER_V1','WFM Service Provider 2.xlsx',100,2,'embedded_filename_timestamp_utc',20,'validating',0,1)",
            (target_run_id,),
        )
        with pytest.raises(SomaError) as exc:
            ProposalRepository.insert_or_reuse_pending(uow, write)
        assert exc.value.code == "IMPORT_RUN_STALE"


def test_published_run_cannot_append_new_pending_proposal(initialized_database) -> None:
    factory = _factory(initialized_database)
    run_id = new_uuid4()
    observation_id = new_uuid4()
    write = _write(
        run_id=run_id,
        observation_id=observation_id,
        lineage_id=new_uuid4(),
        counterpart_id=new_uuid4(),
    )

    with UnitOfWork(factory) as uow:
        _seed_run_and_observation(uow, run_id=run_id, observation_id=observation_id, state="waiting_review")
        with pytest.raises(SomaError) as exc:
            ProposalRepository.insert_or_reuse_pending(uow, write)
        assert exc.value.code == "IMPORT_RUN_STALE"


def test_noncontiguous_change_ordinals_reject_before_write(initialized_database) -> None:
    factory = _factory(initialized_database)
    run_id = new_uuid4()
    observation_id = new_uuid4()
    write = _write(
        run_id=run_id,
        observation_id=observation_id,
        lineage_id=new_uuid4(),
        counterpart_id=new_uuid4(),
        ordinal=1,
    )

    with UnitOfWork(factory) as uow:
        _seed_run_and_observation(uow, run_id=run_id, observation_id=observation_id)
        with pytest.raises(ValidationError):
            ProposalRepository.insert_or_reuse_pending(uow, write)
        assert uow.connection.execute("SELECT count(*) FROM reconciliation_proposals").fetchone()[0] == 0


def test_outer_uow_failure_rolls_back_proposal_and_changes(initialized_database) -> None:
    factory = _factory(initialized_database)
    run_id = new_uuid4()
    observation_id = new_uuid4()
    write = _write(
        run_id=run_id,
        observation_id=observation_id,
        lineage_id=new_uuid4(),
        counterpart_id=new_uuid4(),
    )
    with UnitOfWork(factory) as uow:
        _seed_run_and_observation(uow, run_id=run_id, observation_id=observation_id)

    with pytest.raises(RuntimeError):
        with UnitOfWork(factory) as uow:
            ProposalRepository.insert_or_reuse_pending(uow, write)
            raise RuntimeError("inject rollback")

    with ReadSnapshot(factory) as snapshot:
        assert snapshot.connection.execute("SELECT count(*) FROM reconciliation_proposals").fetchone()[0] == 0
        assert snapshot.connection.execute("SELECT count(*) FROM reconciliation_proposal_changes").fetchone()[0] == 0
