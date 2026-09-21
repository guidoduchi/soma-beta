from __future__ import annotations

import pytest

from soma.foundation.errors import SomaError
from soma.foundation.identifiers import new_uuid4
from soma.foundation.persistence.uow import ReadSnapshot, UnitOfWork
from soma.ticket_import.commands.decide_proposal import ProposalDecisionService
from soma.ticket_import.repositories.proposals import ProposalRepository


def _factory(initialized_database):
    database_path, factory_for_path = initialized_database
    return factory_for_path(database_path)


def _receipt(uow: UnitOfWork, command_id: str) -> None:
    uow.connection.execute(
        "INSERT INTO command_receipts(command_id,command_type,request_hash,target_type,target_id,committed_at_utc,result_type,result_id) "
        "VALUES (?, 'SeedImportAuthority', ?, 'import_run', NULL, 0, NULL, NULL)",
        (command_id, "0" * 64),
    )


def _seed_run(
    uow: UnitOfWork,
    *,
    run_id: str,
    state: str = "waiting_review",
    pending: int = 1,
    chronology: int = 200,
    fingerprint: str = "1" * 64,
) -> None:
    uow.connection.execute(
        "INSERT INTO import_runs("
        "import_run_id,source_family,invocation_kind,source_profile_id,header_registry_id,vocabulary_registry_id,parser_profile_id,"
        "candidate_filename,candidate_file_size_bytes,candidate_stable_mtime_ns,candidate_chronology_kind,candidate_chronology_value,"
        "logical_fingerprint_sha256,run_state,started_at_utc,staged_at_utc,proposal_count,pending_proposal_count,revision"
        ") VALUES (?, 'advanced_search_sr','manual','ADVANCED_SEARCH_SR_V1','ADVANCED_SEARCH_HEADERS_V1','ADVANCED_SEARCH_VOCAB_V1',"
        "'ADVANCED_SEARCH_PARSER_V1','Advanced Search(Service Request)20260908010000.xlsx',100,1,"
        "'embedded_filename_timestamp_utc',?,?,?,0,1,?,?,1)",
        (run_id, chronology, fingerprint, state, pending, pending),
    )


def _seed_observation(uow: UnitOfWork, *, run_id: str, observation_id: str, sr_no: str) -> None:
    uow.connection.execute(
        "INSERT INTO source_observations(source_observation_id,import_run_id,source_family,entity_kind,identity_state,"
        "canonical_primary_id,canonical_parent_rfc_no,row_ordinal,sheet_ordinal,row_logical_sha256,source_row_chronology_utc,"
        "presence_state,recorded_at_utc) VALUES (?,?,'advanced_search_sr','service_request','valid',?,NULL,1,1,?,100,"
        "'observed_valid_identity',1)",
        (observation_id, run_id, sr_no, "2" * 64),
    )


def _seed_proposal(
    uow: UnitOfWork,
    *,
    run_id: str,
    observation_id: str,
    proposal_id: str,
    business_id: str,
    proposal_fingerprint: str,
    base_state_token: str = "4" * 64,
) -> None:
    uow.connection.execute(
        "INSERT INTO reconciliation_proposals(reconciliation_proposal_id,import_run_id,evidence_mode,source_observation_id,"
        "prior_source_observation_id,proposal_kind,target_kind,target_internal_id,target_business_id,risk_class,"
        "base_state_token_sha256,proposal_fingerprint_sha256,proposal_state,created_at_utc,revision,decided_at_utc) "
        "VALUES (?,?,'observed_row',?,NULL,'sr_source_projection','service_request',NULL,?,'medium',?,?,'pending',1,1,NULL)",
        (proposal_id, run_id, observation_id, business_id, base_state_token, proposal_fingerprint),
    )


def _seed_reviewable_run(factory, *, pending: int = 1, state: str = "waiting_review"):
    run_id = new_uuid4()
    observations: list[str] = []
    proposals: list[tuple[str, str]] = []
    with UnitOfWork(factory) as uow:
        _seed_run(uow, run_id=run_id, state=state, pending=pending)
        for ordinal in range(pending):
            observation_id = new_uuid4()
            proposal_id = new_uuid4()
            proposal_fingerprint = f"{ordinal + 5:064x}"
            _seed_observation(
                uow,
                run_id=run_id,
                observation_id=observation_id,
                sr_no=f"{12345678 + ordinal:08d}",
            )
            _seed_proposal(
                uow,
                run_id=run_id,
                observation_id=observation_id,
                proposal_id=proposal_id,
                business_id=f"{12345678 + ordinal:08d}",
                proposal_fingerprint=proposal_fingerprint,
            )
            observations.append(observation_id)
            proposals.append((proposal_id, proposal_fingerprint))
    return run_id, observations, proposals


def test_reject_is_atomic_preserves_published_presence_and_updates_exact_counters(initialized_database) -> None:
    factory = _factory(initialized_database)
    run_id, observations, proposals = _seed_reviewable_run(factory)
    proposal_id, fingerprint = proposals[0]
    command_id = new_uuid4()

    result = ProposalDecisionService(factory).reject(
        command_id=command_id,
        proposal_id=proposal_id,
        proposal_revision=1,
        proposal_fingerprint=fingerprint,
        reason_category="operator_rejected",
    )
    assert result.decision == "rejected"
    assert result.revision == 2
    assert result.owner_result_refs == ()
    assert result.replayed is False

    with ReadSnapshot(factory) as snapshot:
        proposal = snapshot.connection.execute(
            "SELECT proposal_state,revision FROM reconciliation_proposals WHERE reconciliation_proposal_id=?",
            (proposal_id,),
        ).fetchone()
        run = snapshot.connection.execute(
            "SELECT run_state,pending_proposal_count,rejected_proposal_count,deferred_proposal_count,revision "
            "FROM import_runs WHERE import_run_id=?",
            (run_id,),
        ).fetchone()
        assert tuple(proposal) == ("rejected", 2)
        assert tuple(run) == ("waiting_review", 0, 1, 0, 2)
        assert snapshot.connection.execute(
            "SELECT 1 FROM source_observations WHERE source_observation_id=?",
            (observations[0],),
        ).fetchone() is not None
        disposition = snapshot.connection.execute(
            "SELECT decision,proposal_revision,reason_category,command_id FROM proposal_dispositions "
            "WHERE reconciliation_proposal_id=?",
            (proposal_id,),
        ).fetchone()
        assert tuple(disposition) == ("rejected", 1, "operator_rejected", command_id)
        equivalence = snapshot.connection.execute(
            "SELECT decision,source_proposal_id FROM proposal_equivalence_decisions WHERE source_proposal_id=?",
            (proposal_id,),
        ).fetchone()
        assert tuple(equivalence) == ("rejected", proposal_id)
        audit = snapshot.connection.execute(
            "SELECT action_type,command_id,payload_json FROM audit_events WHERE command_id=?",
            (command_id,),
        ).fetchone()
        assert audit is not None
        assert str(audit[0]) == "ticket_import.proposal_decided"
        assert str(audit[1]) == command_id
        assert "operator_rejected" in str(audit[2])


def test_defer_is_independent_smallest_scope_and_other_proposal_stays_pending(initialized_database) -> None:
    factory = _factory(initialized_database)
    run_id, _observations, proposals = _seed_reviewable_run(factory, pending=2)
    proposal_id, fingerprint = proposals[0]
    other_id, _other_fingerprint = proposals[1]

    result = ProposalDecisionService(factory).defer(
        command_id=new_uuid4(),
        proposal_id=proposal_id,
        proposal_revision=1,
        proposal_fingerprint=fingerprint,
        reason_category="needs_more_context",
    )
    assert result.decision == "deferred"
    with ReadSnapshot(factory) as snapshot:
        assert snapshot.connection.execute(
            "SELECT proposal_state FROM reconciliation_proposals WHERE reconciliation_proposal_id=?",
            (other_id,),
        ).fetchone()[0] == "pending"
        run = snapshot.connection.execute(
            "SELECT pending_proposal_count,deferred_proposal_count,rejected_proposal_count,revision FROM import_runs WHERE import_run_id=?",
            (run_id,),
        ).fetchone()
        assert tuple(run) == (1, 1, 0, 2)


def test_decision_replay_returns_committed_result_without_revalidating_terminal_proposal(initialized_database) -> None:
    factory = _factory(initialized_database)
    _run_id, _observations, proposals = _seed_reviewable_run(factory)
    proposal_id, fingerprint = proposals[0]
    command_id = new_uuid4()
    service = ProposalDecisionService(factory)

    first = service.reject(
        command_id=command_id,
        proposal_id=proposal_id,
        proposal_revision=1,
        proposal_fingerprint=fingerprint,
        reason_category="duplicate_source",
    )
    replay = service.reject(
        command_id=command_id,
        proposal_id=proposal_id,
        proposal_revision=1,
        proposal_fingerprint=fingerprint,
        reason_category="duplicate_source",
    )
    assert first.replayed is False
    assert replay.replayed is True
    assert replay.decision == "rejected"
    assert replay.revision == 2

    with ReadSnapshot(factory) as snapshot:
        assert snapshot.connection.execute(
            "SELECT COUNT(*) FROM proposal_dispositions WHERE reconciliation_proposal_id=?",
            (proposal_id,),
        ).fetchone()[0] == 1
        assert snapshot.connection.execute(
            "SELECT COUNT(*) FROM audit_events WHERE command_id=?",
            (command_id,),
        ).fetchone()[0] == 1


def test_stale_fingerprint_or_revision_leaves_no_receipt_or_disposition(initialized_database) -> None:
    factory = _factory(initialized_database)
    run_id, _observations, proposals = _seed_reviewable_run(factory)
    proposal_id, fingerprint = proposals[0]
    service = ProposalDecisionService(factory)

    for proposal_revision, supplied_fingerprint in ((2, fingerprint), (1, "f" * 64)):
        command_id = new_uuid4()
        with pytest.raises(SomaError) as excinfo:
            service.reject(
                command_id=command_id,
                proposal_id=proposal_id,
                proposal_revision=proposal_revision,
                proposal_fingerprint=supplied_fingerprint,
                reason_category="stale_test",
            )
        assert excinfo.value.code == "IMPORT_PROPOSAL_STALE"
        with ReadSnapshot(factory) as snapshot:
            assert snapshot.connection.execute(
                "SELECT 1 FROM command_receipts WHERE command_id=?",
                (command_id,),
            ).fetchone() is None
            assert snapshot.connection.execute(
                "SELECT COUNT(*) FROM proposal_dispositions WHERE reconciliation_proposal_id=?",
                (proposal_id,),
            ).fetchone()[0] == 0
            run = snapshot.connection.execute(
                "SELECT pending_proposal_count,rejected_proposal_count,deferred_proposal_count,revision FROM import_runs WHERE import_run_id=?",
                (run_id,),
            ).fetchone()
            assert tuple(run) == (1, 0, 0, 1)


def test_recovery_proposal_decision_requires_exact_current_authorization(initialized_database) -> None:
    factory = _factory(initialized_database)
    checkpoint_run = new_uuid4()
    recovery_run, _observations, proposals = _seed_reviewable_run(factory, pending=2, state="recovery_required")
    first_id, first_fingerprint = proposals[0]
    second_id, second_fingerprint = proposals[1]

    with UnitOfWork(factory) as uow:
        _seed_run(uow, run_id=checkpoint_run, state="waiting_review", pending=0, chronology=300, fingerprint="a" * 64)
        uow.connection.execute(
            "INSERT INTO import_source_checkpoints(source_family,source_profile_id,accepted_candidate_chronology_kind,"
            "accepted_candidate_chronology_value,accepted_logical_fingerprint_sha256,accepted_import_run_id,last_checked_at_utc,revision) "
            "VALUES ('advanced_search_sr','ADVANCED_SEARCH_SR_V1','embedded_filename_timestamp_utc',300,?,?,1,1)",
            ("a" * 64, checkpoint_run),
        )

    unauthorised_command = new_uuid4()
    with pytest.raises(SomaError) as excinfo:
        ProposalDecisionService(factory).reject(
            command_id=unauthorised_command,
            proposal_id=first_id,
            proposal_revision=1,
            proposal_fingerprint=first_fingerprint,
            reason_category="recovery_review",
        )
    assert excinfo.value.code == "IMPORT_RECOVERY_REVIEW_STALE"

    with UnitOfWork(factory) as uow:
        run = ProposalRepository.get_run(uow.connection, recovery_run)
        review_fingerprint = ProposalRepository.recovery_review_fingerprint(uow.connection, run)
        review_command = new_uuid4()
        _receipt(uow, review_command)
        uow.connection.execute(
            "INSERT INTO import_recovery_reviews(import_recovery_review_id,import_run_id,checkpoint_import_run_id,review_ordinal,"
            "run_revision,checkpoint_revision,review_fingerprint_sha256,decision,reason_category,occurred_at_utc,command_id) "
            "VALUES (?,?,?,1,1,1,?,'authorized','explicit_recovery_authorization',1,?)",
            (new_uuid4(), recovery_run, checkpoint_run, review_fingerprint, review_command),
        )

    accepted_decision = ProposalDecisionService(factory).defer(
        command_id=new_uuid4(),
        proposal_id=first_id,
        proposal_revision=1,
        proposal_fingerprint=first_fingerprint,
        reason_category="defer_recovery_item",
    )
    assert accepted_decision.decision == "deferred"

    stale_authorization_command = new_uuid4()
    with pytest.raises(SomaError) as excinfo:
        ProposalDecisionService(factory).reject(
            command_id=stale_authorization_command,
            proposal_id=second_id,
            proposal_revision=1,
            proposal_fingerprint=second_fingerprint,
            reason_category="second_item_requires_refresh",
        )
    assert excinfo.value.code == "IMPORT_RECOVERY_REVIEW_STALE"
    with ReadSnapshot(factory) as snapshot:
        assert snapshot.connection.execute(
            "SELECT 1 FROM command_receipts WHERE command_id=?",
            (stale_authorization_command,),
        ).fetchone() is None
        assert snapshot.connection.execute(
            "SELECT proposal_state FROM reconciliation_proposals WHERE reconciliation_proposal_id=?",
            (second_id,),
        ).fetchone()[0] == "pending"


def test_reason_and_fingerprint_bounds_fail_before_any_persistence(initialized_database) -> None:
    factory = _factory(initialized_database)
    _run_id, _observations, proposals = _seed_reviewable_run(factory)
    proposal_id, fingerprint = proposals[0]
    service = ProposalDecisionService(factory)

    cases = (
        ("not-a-sha", "reason"),
        (fingerprint, "x" * 121),
        (fingerprint, "bad\nreason"),
    )
    for supplied_fingerprint, reason in cases:
        command_id = new_uuid4()
        with pytest.raises(SomaError):
            service.defer(
                command_id=command_id,
                proposal_id=proposal_id,
                proposal_revision=1,
                proposal_fingerprint=supplied_fingerprint,
                reason_category=reason,
            )
        with ReadSnapshot(factory) as snapshot:
            assert snapshot.connection.execute(
                "SELECT 1 FROM command_receipts WHERE command_id=?",
                (command_id,),
            ).fetchone() is None
