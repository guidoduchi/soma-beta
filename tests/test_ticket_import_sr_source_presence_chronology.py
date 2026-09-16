from __future__ import annotations

from soma.foundation.identifiers import new_uuid4
from soma.foundation.persistence.uow import UnitOfWork
from soma.ticket_import.providers.sr_source_presence import (
    TicketImportSrSourcePresenceEvidenceProvider,
)


SOURCE_FAMILY = "advanced_search_sr"
CHRONOLOGY_KIND = "embedded_filename_timestamp_utc"


def _factory(initialized_database):
    database_path, factory_builder = initialized_database
    return factory_builder(database_path)


def _insert_run(
    uow: UnitOfWork,
    *,
    run_id: str,
    chronology: int,
    state: str,
    fingerprint: str = "a" * 64,
    invocation_kind: str = "manual",
) -> None:
    staged = None if state in {"discovering", "validating", "failed"} else 1
    completed = 2 if state in {"accepted", "partially_accepted", "rejected", "noop", "failed"} else None
    logical = None if state in {"discovering", "validating", "failed"} else fingerprint
    uow.connection.execute(
        "INSERT INTO import_runs(import_run_id,source_family,invocation_kind,source_profile_id,"
        "header_registry_id,vocabulary_registry_id,parser_profile_id,candidate_filename,"
        "candidate_file_size_bytes,candidate_stable_mtime_ns,candidate_chronology_kind,"
        "candidate_chronology_value,logical_fingerprint_sha256,run_state,started_at_utc,"
        "staged_at_utc,completed_at_utc,revision) VALUES (?,? ,?,'ADVANCED_SEARCH_SR_V1',"
        "'ADVANCED_SEARCH_HEADERS_V1','ADVANCED_SEARCH_VOCAB_V1','ADVANCED_SEARCH_PARSER_V1',"
        "'source.xlsx',1,1,?,?,?,?,1,?,?,2)",
        (
            run_id,
            SOURCE_FAMILY,
            invocation_kind,
            CHRONOLOGY_KIND,
            chronology,
            logical,
            state,
            staged,
            completed,
        ),
    )


def _insert_sr(uow: UnitOfWork, official: str = "12345678") -> str:
    sr_id = new_uuid4()
    uow.connection.execute(
        "INSERT INTO service_requests(service_request_id,official_sr_no,revision,created_at_utc,updated_at_utc) "
        "VALUES (?,?,1,1,1)",
        (sr_id, official),
    )
    return sr_id


def _insert_observation(
    uow: UnitOfWork,
    *,
    run_id: str,
    observation_id: str | None = None,
    official: str = "12345678",
    row_hash: str = "1" * 64,
    row_ordinal: int = 1,
) -> str:
    observation_id = new_uuid4() if observation_id is None else observation_id
    uow.connection.execute(
        "INSERT INTO source_observations(source_observation_id,import_run_id,source_family,entity_kind,"
        "identity_state,canonical_primary_id,canonical_parent_rfc_no,row_ordinal,sheet_ordinal,"
        "row_logical_sha256,source_row_chronology_utc,presence_state,recorded_at_utc) "
        "VALUES (?,?,'advanced_search_sr','service_request','valid',?,NULL,?,1,?,NULL,"
        "'observed_valid_identity',1)",
        (observation_id, run_id, official, row_ordinal, row_hash),
    )
    return observation_id


def _receipt(
    uow: UnitOfWork,
    *,
    command_id: str,
    command_type: str,
    target_type: str,
    target_id: str,
) -> None:
    uow.connection.execute(
        "INSERT INTO command_receipts(command_id,command_type,request_hash,target_type,target_id,"
        "committed_at_utc,result_type,result_id) VALUES (?,?,?,?,?,1,NULL,NULL)",
        (command_id, command_type, "0" * 64, target_type, target_id),
    )


def _checkpoint(
    uow: UnitOfWork,
    *,
    run_id: str,
    chronology: int,
    fingerprint: str,
) -> None:
    uow.connection.execute(
        "INSERT INTO import_source_checkpoints(source_family,source_profile_id,"
        "accepted_candidate_chronology_kind,accepted_candidate_chronology_value,"
        "accepted_logical_fingerprint_sha256,accepted_import_run_id,last_checked_at_utc,revision) "
        "VALUES ('advanced_search_sr','ADVANCED_SEARCH_SR_V1',?,?,?,?,1,1)",
        (CHRONOLOGY_KIND, chronology, fingerprint, run_id),
    )


def _disappearance_event(
    uow: UnitOfWork,
    *,
    sr_id: str,
    absence_run_id: str,
    prior_observation_id: str,
) -> str:
    command_id = new_uuid4()
    event_id = new_uuid4()
    _receipt(
        uow,
        command_id=command_id,
        command_type="SeedDisappearance",
        target_type="service_request",
        target_id=sr_id,
    )
    uow.connection.execute(
        "INSERT INTO sr_source_presence_events(sr_source_presence_event_id,service_request_id,source_family,"
        "event_kind,prior_presence_event_id,import_run_id,source_observation_id,prior_source_observation_id,"
        "reconciliation_proposal_id,accepted_command_id,recorded_at_utc) "
        "VALUES (?,?,'advanced_search_sr','disappearance_reviewed',NULL,?,NULL,?,?,?,1)",
        (event_id, sr_id, absence_run_id, prior_observation_id, new_uuid4(), command_id),
    )
    return event_id


def _recovery_event(
    uow: UnitOfWork,
    *,
    run_id: str,
    prior_checkpoint_run_id: str,
) -> None:
    command_id = new_uuid4()
    _receipt(
        uow,
        command_id=command_id,
        command_type="FinalizeRecovery",
        target_type="import_run",
        target_id=run_id,
    )
    uow.connection.execute(
        "INSERT INTO import_recovery_events(import_recovery_event_id,source_family,import_run_id,"
        "prior_checkpoint_run_id,recovery_reason_category,review_fingerprint_sha256,occurred_at_utc,command_id) "
        "VALUES (?,'advanced_search_sr',?,?, 'reviewed_chronology',?,1,?)",
        (new_uuid4(), run_id, prior_checkpoint_run_id, "9" * 64, command_id),
    )


def _validate_reappearance(
    uow: UnitOfWork,
    *,
    sr_id: str,
    event_id: str,
    run_id: str,
    observation_id: str,
) -> str:
    return TicketImportSrSourcePresenceEvidenceProvider().validate_reappearance_evidence(
        uow.connection,
        sr_id,
        SOURCE_FAMILY,
        run_id,
        observation_id,
        {
            "command_id": new_uuid4(),
            "expected_active_disappearance_event_id": event_id,
        },
    )


def test_later_new_source_can_confirm_reappearance(initialized_database) -> None:
    factory = _factory(initialized_database)
    prior_run = new_uuid4()
    absence_run = new_uuid4()
    later_run = new_uuid4()
    with UnitOfWork(factory) as uow:
        sr_id = _insert_sr(uow)
        _insert_run(uow, run_id=prior_run, chronology=9, state="accepted", fingerprint="1" * 64)
        prior_observation = _insert_observation(uow, run_id=prior_run)
        _insert_run(uow, run_id=absence_run, chronology=10, state="accepted", fingerprint="2" * 64)
        event_id = _disappearance_event(
            uow,
            sr_id=sr_id,
            absence_run_id=absence_run,
            prior_observation_id=prior_observation,
        )
        _insert_run(uow, run_id=later_run, chronology=11, state="accepted", fingerprint="3" * 64)
        observation_id = _insert_observation(uow, run_id=later_run)

        assert _validate_reappearance(
            uow,
            sr_id=sr_id,
            event_id=event_id,
            run_id=later_run,
            observation_id=observation_id,
        ) == "VALID"


def test_later_recovery_lineage_cannot_auto_confirm_reappearance(initialized_database) -> None:
    factory = _factory(initialized_database)
    prior_run = new_uuid4()
    absence_run = new_uuid4()
    recovery_run = new_uuid4()
    with UnitOfWork(factory) as uow:
        sr_id = _insert_sr(uow)
        _insert_run(uow, run_id=prior_run, chronology=9, state="accepted", fingerprint="1" * 64)
        prior_observation = _insert_observation(uow, run_id=prior_run)
        _insert_run(uow, run_id=absence_run, chronology=10, state="accepted", fingerprint="2" * 64)
        event_id = _disappearance_event(
            uow,
            sr_id=sr_id,
            absence_run_id=absence_run,
            prior_observation_id=prior_observation,
        )
        _insert_run(
            uow,
            run_id=recovery_run,
            chronology=11,
            state="accepted",
            fingerprint="3" * 64,
            invocation_kind="recovery",
        )
        observation_id = _insert_observation(uow, run_id=recovery_run)
        _recovery_event(uow, run_id=recovery_run, prior_checkpoint_run_id=prior_run)

        assert _validate_reappearance(
            uow,
            sr_id=sr_id,
            event_id=event_id,
            run_id=recovery_run,
            observation_id=observation_id,
        ) == "INVALID"


def test_equal_chronology_correction_can_confirm_only_after_becoming_checkpoint(
    initialized_database,
) -> None:
    factory = _factory(initialized_database)
    prior_run = new_uuid4()
    absence_run = new_uuid4()
    correction_run = new_uuid4()
    correction_fingerprint = "4" * 64
    with UnitOfWork(factory) as uow:
        sr_id = _insert_sr(uow)
        _insert_run(uow, run_id=prior_run, chronology=9, state="accepted", fingerprint="1" * 64)
        prior_observation = _insert_observation(uow, run_id=prior_run)
        _insert_run(uow, run_id=absence_run, chronology=10, state="accepted", fingerprint="2" * 64)
        event_id = _disappearance_event(
            uow,
            sr_id=sr_id,
            absence_run_id=absence_run,
            prior_observation_id=prior_observation,
        )
        _insert_run(
            uow,
            run_id=correction_run,
            chronology=10,
            state="accepted",
            fingerprint=correction_fingerprint,
            invocation_kind="recovery",
        )
        observation_id = _insert_observation(uow, run_id=correction_run)
        _recovery_event(uow, run_id=correction_run, prior_checkpoint_run_id=prior_run)

        assert _validate_reappearance(
            uow,
            sr_id=sr_id,
            event_id=event_id,
            run_id=correction_run,
            observation_id=observation_id,
        ) == "INVALID"

        _checkpoint(
            uow,
            run_id=correction_run,
            chronology=10,
            fingerprint=correction_fingerprint,
        )
        assert _validate_reappearance(
            uow,
            sr_id=sr_id,
            event_id=event_id,
            run_id=correction_run,
            observation_id=observation_id,
        ) == "VALID"


def test_equivalent_duplicate_reappearance_uses_only_lowest_observation_id(
    initialized_database,
) -> None:
    factory = _factory(initialized_database)
    prior_run = new_uuid4()
    absence_run = new_uuid4()
    later_run = new_uuid4()
    low_id = "00000000-0000-4000-8000-000000000001"
    high_id = "00000000-0000-4000-8000-000000000002"
    with UnitOfWork(factory) as uow:
        sr_id = _insert_sr(uow)
        _insert_run(uow, run_id=prior_run, chronology=9, state="accepted", fingerprint="1" * 64)
        prior_observation = _insert_observation(uow, run_id=prior_run)
        _insert_run(uow, run_id=absence_run, chronology=10, state="accepted", fingerprint="2" * 64)
        event_id = _disappearance_event(
            uow,
            sr_id=sr_id,
            absence_run_id=absence_run,
            prior_observation_id=prior_observation,
        )
        _insert_run(uow, run_id=later_run, chronology=11, state="accepted", fingerprint="3" * 64)
        _insert_observation(uow, run_id=later_run, observation_id=high_id, row_hash="7" * 64, row_ordinal=2)
        _insert_observation(uow, run_id=later_run, observation_id=low_id, row_hash="7" * 64, row_ordinal=1)

        assert _validate_reappearance(
            uow,
            sr_id=sr_id,
            event_id=event_id,
            run_id=later_run,
            observation_id=low_id,
        ) == "VALID"
        assert _validate_reappearance(
            uow,
            sr_id=sr_id,
            event_id=event_id,
            run_id=later_run,
            observation_id=high_id,
        ) == "INVALID"


def test_conflicting_duplicate_reappearance_is_indeterminate(initialized_database) -> None:
    factory = _factory(initialized_database)
    prior_run = new_uuid4()
    absence_run = new_uuid4()
    later_run = new_uuid4()
    first_id = "00000000-0000-4000-8000-000000000011"
    second_id = "00000000-0000-4000-8000-000000000012"
    with UnitOfWork(factory) as uow:
        sr_id = _insert_sr(uow)
        _insert_run(uow, run_id=prior_run, chronology=9, state="accepted", fingerprint="1" * 64)
        prior_observation = _insert_observation(uow, run_id=prior_run)
        _insert_run(uow, run_id=absence_run, chronology=10, state="accepted", fingerprint="2" * 64)
        event_id = _disappearance_event(
            uow,
            sr_id=sr_id,
            absence_run_id=absence_run,
            prior_observation_id=prior_observation,
        )
        _insert_run(uow, run_id=later_run, chronology=11, state="accepted", fingerprint="3" * 64)
        _insert_observation(uow, run_id=later_run, observation_id=first_id, row_hash="7" * 64, row_ordinal=1)
        _insert_observation(uow, run_id=later_run, observation_id=second_id, row_hash="8" * 64, row_ordinal=2)

        assert _validate_reappearance(
            uow,
            sr_id=sr_id,
            event_id=event_id,
            run_id=later_run,
            observation_id=first_id,
        ) == "INVALID"
        assert _validate_reappearance(
            uow,
            sr_id=sr_id,
            event_id=event_id,
            run_id=later_run,
            observation_id=second_id,
        ) == "INVALID"


def test_disappearance_acceptance_stales_after_later_authoritative_presence(
    initialized_database,
) -> None:
    factory = _factory(initialized_database)
    prior_run = new_uuid4()
    absence_run = new_uuid4()
    later_run = new_uuid4()
    proposal_id = new_uuid4()
    proposal_fingerprint = "f" * 64
    command_id = new_uuid4()
    with UnitOfWork(factory) as uow:
        sr_id = _insert_sr(uow)
        _insert_run(uow, run_id=prior_run, chronology=9, state="accepted", fingerprint="1" * 64)
        prior_observation = _insert_observation(uow, run_id=prior_run)
        _insert_run(uow, run_id=absence_run, chronology=10, state="waiting_review", fingerprint="2" * 64)
        uow.connection.execute(
            "INSERT INTO reconciliation_proposals(reconciliation_proposal_id,import_run_id,evidence_mode,"
            "source_observation_id,prior_source_observation_id,proposal_kind,target_kind,target_internal_id,"
            "target_business_id,risk_class,base_state_token_sha256,proposal_fingerprint_sha256,"
            "proposal_state,created_at_utc,revision) VALUES (?,?,'population_absence',NULL,?,"
            "'sr_source_disappearance_review','source_presence',?,'12345678','high',?,?, 'pending',1,1)",
            (proposal_id, absence_run, prior_observation, sr_id, "b" * 64, proposal_fingerprint),
        )
        _receipt(
            uow,
            command_id=command_id,
            command_type="AcceptReconciliationProposal",
            target_type="reconciliation_proposal",
            target_id=proposal_id,
        )
        _insert_run(uow, run_id=later_run, chronology=11, state="accepted", fingerprint="3" * 64)
        _insert_observation(uow, run_id=later_run)

        result = TicketImportSrSourcePresenceEvidenceProvider().validate_disappearance_acceptance(
            uow.connection,
            proposal_id,
            sr_id,
            SOURCE_FAMILY,
            absence_run,
            prior_observation,
            {
                "command_id": command_id,
                "proposal_revision": 1,
                "proposal_fingerprint": proposal_fingerprint,
            },
        )
        assert result == "INVALID"
