from __future__ import annotations

from soma.foundation.identifiers import new_uuid4
from soma.foundation.persistence.uow import UnitOfWork
from soma.ticket_import.providers.sr_source_presence import (
    TicketImportSrSourcePresenceEvidenceProvider,
)


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
) -> None:
    staged_at = 2 if state != "validating" else None
    completed_at = 3 if state in {"accepted", "partially_accepted", "rejected", "noop", "failed"} else None
    logical_fingerprint = None if state == "validating" else fingerprint
    uow.connection.execute(
        "INSERT INTO import_runs(import_run_id,source_family,invocation_kind,source_profile_id,"
        "header_registry_id,vocabulary_registry_id,parser_profile_id,candidate_filename,"
        "candidate_file_size_bytes,candidate_stable_mtime_ns,candidate_chronology_kind,"
        "candidate_chronology_value,logical_fingerprint_sha256,run_state,started_at_utc,staged_at_utc,"
        "completed_at_utc,revision) VALUES (?,'advanced_search_sr','manual','ADVANCED_SEARCH_SR_V1',"
        "'ADVANCED_SEARCH_HEADERS_V1','ADVANCED_SEARCH_VOCAB_V1','ADVANCED_SEARCH_PARSER_V1',"
        "'source.xlsx',1,1,'embedded_filename_timestamp_utc',?,?,?,?,?,?,1)",
        (run_id, chronology, logical_fingerprint, state, 1, staged_at, completed_at),
    )


def _insert_sr(uow: UnitOfWork, sr_no: str = "12345678") -> str:
    sr_id = new_uuid4()
    uow.connection.execute(
        "INSERT INTO service_requests(service_request_id,official_sr_no,revision,created_at_utc,updated_at_utc) "
        "VALUES (?,?,1,1,1)",
        (sr_id, sr_no),
    )
    return sr_id


def _insert_observation(
    uow: UnitOfWork,
    *,
    run_id: str,
    sr_no: str,
    row_hash: str,
    observation_id: str | None = None,
    row_ordinal: int = 1,
) -> str:
    source_observation_id = new_uuid4() if observation_id is None else observation_id
    uow.connection.execute(
        "INSERT INTO source_observations(source_observation_id,import_run_id,source_family,entity_kind,"
        "identity_state,canonical_primary_id,canonical_parent_rfc_no,row_ordinal,sheet_ordinal,row_logical_sha256,"
        "source_row_chronology_utc,presence_state,recorded_at_utc) VALUES (?,?,'advanced_search_sr',"
        "'service_request','valid',?,NULL,?,1,?,NULL,'observed_valid_identity',1)",
        (source_observation_id, run_id, sr_no, row_ordinal, row_hash),
    )
    return source_observation_id


def _insert_receipt(
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


def _insert_disappearance_event(
    uow: UnitOfWork,
    *,
    sr_id: str,
    absence_run_id: str,
) -> str:
    event_id = new_uuid4()
    command_id = new_uuid4()
    _insert_receipt(
        uow,
        command_id=command_id,
        command_type="PresenceEvidenceTest",
        target_type="service_request",
        target_id=sr_id,
    )
    uow.connection.execute(
        "INSERT INTO sr_source_presence_events(sr_source_presence_event_id,service_request_id,source_family,"
        "event_kind,prior_presence_event_id,import_run_id,source_observation_id,prior_source_observation_id,"
        "reconciliation_proposal_id,accepted_command_id,recorded_at_utc) VALUES (?,?,'advanced_search_sr',"
        "'disappearance_reviewed',NULL,?,NULL,?,?,?,1)",
        (event_id, sr_id, absence_run_id, new_uuid4(), new_uuid4(), command_id),
    )
    return event_id


def _insert_checkpoint(
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
        "VALUES ('advanced_search_sr','ADVANCED_SEARCH_SR_V1','embedded_filename_timestamp_utc',?,?,?,3,1)",
        (chronology, fingerprint, run_id),
    )


def _insert_recovery_lineage(
    uow: UnitOfWork,
    *,
    recovery_run_id: str,
    prior_run_id: str,
) -> None:
    command_id = new_uuid4()
    _insert_receipt(
        uow,
        command_id=command_id,
        command_type="FinalizeRecoveryTest",
        target_type="import_run",
        target_id=recovery_run_id,
    )
    uow.connection.execute(
        "INSERT INTO import_recovery_events(import_recovery_event_id,source_family,import_run_id,"
        "prior_checkpoint_run_id,recovery_reason_category,review_fingerprint_sha256,occurred_at_utc,command_id) "
        "VALUES (?,'advanced_search_sr',?,?,'reviewed_recovery',?,2,?)",
        (new_uuid4(), recovery_run_id, prior_run_id, "b" * 64, command_id),
    )


def _reappearance_context(event_id: str) -> dict[str, object]:
    return {"expected_active_disappearance_event_id": event_id}


def test_reappearance_accepts_strictly_later_ordinary_new_source(initialized_database) -> None:
    factory = _factory(initialized_database)
    provider = TicketImportSrSourcePresenceEvidenceProvider()
    absence_run = new_uuid4()
    candidate_run = new_uuid4()
    with UnitOfWork(factory) as uow:
        sr_id = _insert_sr(uow)
        _insert_run(uow, run_id=absence_run, chronology=10, state="accepted")
        event_id = _insert_disappearance_event(uow, sr_id=sr_id, absence_run_id=absence_run)
        _insert_run(uow, run_id=candidate_run, chronology=11, state="staged")
        observation_id = _insert_observation(
            uow,
            run_id=candidate_run,
            sr_no="12345678",
            row_hash="c" * 64,
        )
        assert provider.validate_reappearance_evidence(
            uow.connection,
            sr_id,
            "advanced_search_sr",
            candidate_run,
            observation_id,
            _reappearance_context(event_id),
        ) == "VALID"


def test_reappearance_rejects_older_candidate(initialized_database) -> None:
    factory = _factory(initialized_database)
    provider = TicketImportSrSourcePresenceEvidenceProvider()
    absence_run = new_uuid4()
    candidate_run = new_uuid4()
    with UnitOfWork(factory) as uow:
        sr_id = _insert_sr(uow)
        _insert_run(uow, run_id=absence_run, chronology=10, state="accepted")
        event_id = _insert_disappearance_event(uow, sr_id=sr_id, absence_run_id=absence_run)
        _insert_run(uow, run_id=candidate_run, chronology=9, state="accepted")
        observation_id = _insert_observation(
            uow,
            run_id=candidate_run,
            sr_no="12345678",
            row_hash="d" * 64,
        )
        assert provider.validate_reappearance_evidence(
            uow.connection,
            sr_id,
            "advanced_search_sr",
            candidate_run,
            observation_id,
            _reappearance_context(event_id),
        ) == "INVALID"


def test_reappearance_rejects_strictly_later_recovery_lineage_even_after_finalization(
    initialized_database,
) -> None:
    factory = _factory(initialized_database)
    provider = TicketImportSrSourcePresenceEvidenceProvider()
    absence_run = new_uuid4()
    recovery_run = new_uuid4()
    with UnitOfWork(factory) as uow:
        sr_id = _insert_sr(uow)
        _insert_run(uow, run_id=absence_run, chronology=10, state="accepted")
        event_id = _insert_disappearance_event(uow, sr_id=sr_id, absence_run_id=absence_run)
        _insert_run(uow, run_id=recovery_run, chronology=11, state="accepted")
        observation_id = _insert_observation(
            uow,
            run_id=recovery_run,
            sr_no="12345678",
            row_hash="e" * 64,
        )
        _insert_recovery_lineage(uow, recovery_run_id=recovery_run, prior_run_id=absence_run)
        assert provider.validate_reappearance_evidence(
            uow.connection,
            sr_id,
            "advanced_search_sr",
            recovery_run,
            observation_id,
            _reappearance_context(event_id),
        ) == "INVALID"


def test_reappearance_rejects_conflicting_duplicate_group(initialized_database) -> None:
    factory = _factory(initialized_database)
    provider = TicketImportSrSourcePresenceEvidenceProvider()
    absence_run = new_uuid4()
    candidate_run = new_uuid4()
    first = "00000000-0000-4000-8000-000000000001"
    second = "00000000-0000-4000-8000-000000000002"
    with UnitOfWork(factory) as uow:
        sr_id = _insert_sr(uow)
        _insert_run(uow, run_id=absence_run, chronology=10, state="accepted")
        event_id = _insert_disappearance_event(uow, sr_id=sr_id, absence_run_id=absence_run)
        _insert_run(uow, run_id=candidate_run, chronology=11, state="staged")
        _insert_observation(
            uow,
            run_id=candidate_run,
            sr_no="12345678",
            row_hash="1" * 64,
            observation_id=first,
            row_ordinal=1,
        )
        _insert_observation(
            uow,
            run_id=candidate_run,
            sr_no="12345678",
            row_hash="2" * 64,
            observation_id=second,
            row_ordinal=2,
        )
        assert provider.validate_reappearance_evidence(
            uow.connection,
            sr_id,
            "advanced_search_sr",
            candidate_run,
            first,
            _reappearance_context(event_id),
        ) == "INVALID"


def test_equivalent_duplicates_accept_only_lexicographically_smallest_representative(
    initialized_database,
) -> None:
    factory = _factory(initialized_database)
    provider = TicketImportSrSourcePresenceEvidenceProvider()
    absence_run = new_uuid4()
    candidate_run = new_uuid4()
    first = "00000000-0000-4000-8000-000000000001"
    second = "00000000-0000-4000-8000-000000000002"
    with UnitOfWork(factory) as uow:
        sr_id = _insert_sr(uow)
        _insert_run(uow, run_id=absence_run, chronology=10, state="accepted")
        event_id = _insert_disappearance_event(uow, sr_id=sr_id, absence_run_id=absence_run)
        _insert_run(uow, run_id=candidate_run, chronology=11, state="staged")
        for ordinal, observation_id in enumerate((first, second), start=1):
            _insert_observation(
                uow,
                run_id=candidate_run,
                sr_no="12345678",
                row_hash="3" * 64,
                observation_id=observation_id,
                row_ordinal=ordinal,
            )
        context = _reappearance_context(event_id)
        assert provider.validate_reappearance_evidence(
            uow.connection,
            sr_id,
            "advanced_search_sr",
            candidate_run,
            first,
            context,
        ) == "VALID"
        assert provider.validate_reappearance_evidence(
            uow.connection,
            sr_id,
            "advanced_search_sr",
            candidate_run,
            second,
            context,
        ) == "INVALID"


def test_equal_chronology_recovery_becomes_valid_only_after_checkpoint_selects_it(
    initialized_database,
) -> None:
    factory = _factory(initialized_database)
    provider = TicketImportSrSourcePresenceEvidenceProvider()
    absence_run = new_uuid4()
    recovery_run = new_uuid4()
    fingerprint = "f" * 64
    with UnitOfWork(factory) as uow:
        sr_id = _insert_sr(uow)
        _insert_run(uow, run_id=absence_run, chronology=10, state="accepted", fingerprint="a" * 64)
        event_id = _insert_disappearance_event(uow, sr_id=sr_id, absence_run_id=absence_run)
        _insert_run(uow, run_id=recovery_run, chronology=10, state="accepted", fingerprint=fingerprint)
        observation_id = _insert_observation(
            uow,
            run_id=recovery_run,
            sr_no="12345678",
            row_hash="4" * 64,
        )
        _insert_recovery_lineage(uow, recovery_run_id=recovery_run, prior_run_id=absence_run)
        _insert_checkpoint(uow, run_id=recovery_run, chronology=10, fingerprint=fingerprint)
        assert provider.validate_reappearance_evidence(
            uow.connection,
            sr_id,
            "advanced_search_sr",
            recovery_run,
            observation_id,
            _reappearance_context(event_id),
        ) == "VALID"


def _insert_disappearance_proposal(
    uow: UnitOfWork,
    *,
    sr_id: str,
    prior_observation_id: str,
    absence_run_id: str,
) -> tuple[str, str, str]:
    proposal_id = new_uuid4()
    command_id = new_uuid4()
    fingerprint = "9" * 64
    uow.connection.execute(
        "INSERT INTO reconciliation_proposals(reconciliation_proposal_id,import_run_id,evidence_mode,"
        "source_observation_id,prior_source_observation_id,proposal_kind,target_kind,target_internal_id,"
        "target_business_id,risk_class,base_state_token_sha256,proposal_fingerprint_sha256,proposal_state,"
        "created_at_utc,revision) VALUES (?,?,'population_absence',NULL,?,'sr_source_disappearance_review',"
        "'source_presence',?,'12345678','high',?,?,'pending',1,1)",
        (proposal_id, absence_run_id, prior_observation_id, sr_id, "8" * 64, fingerprint),
    )
    _insert_receipt(
        uow,
        command_id=command_id,
        command_type="AcceptReconciliationProposal",
        target_type="reconciliation_proposal",
        target_id=proposal_id,
    )
    return proposal_id, command_id, fingerprint


def test_disappearance_acceptance_stales_after_later_ordinary_presence(initialized_database) -> None:
    factory = _factory(initialized_database)
    provider = TicketImportSrSourcePresenceEvidenceProvider()
    prior_run = new_uuid4()
    absence_run = new_uuid4()
    with UnitOfWork(factory) as uow:
        sr_id = _insert_sr(uow)
        _insert_run(uow, run_id=prior_run, chronology=9, state="accepted")
        prior_observation_id = _insert_observation(
            uow,
            run_id=prior_run,
            sr_no="12345678",
            row_hash="5" * 64,
        )
        _insert_run(uow, run_id=absence_run, chronology=10, state="waiting_review")
        proposal_id, command_id, fingerprint = _insert_disappearance_proposal(
            uow,
            sr_id=sr_id,
            prior_observation_id=prior_observation_id,
            absence_run_id=absence_run,
        )
        context = {
            "command_id": command_id,
            "proposal_revision": 1,
            "proposal_fingerprint": fingerprint,
        }
        assert provider.validate_disappearance_acceptance(
            uow.connection,
            proposal_id,
            sr_id,
            "advanced_search_sr",
            absence_run,
            prior_observation_id,
            context,
        ) == "VALID"

        later_run = new_uuid4()
        _insert_run(uow, run_id=later_run, chronology=11, state="staged")
        _insert_observation(
            uow,
            run_id=later_run,
            sr_no="12345678",
            row_hash="6" * 64,
        )
        assert provider.validate_disappearance_acceptance(
            uow.connection,
            proposal_id,
            sr_id,
            "advanced_search_sr",
            absence_run,
            prior_observation_id,
            context,
        ) == "INVALID"
