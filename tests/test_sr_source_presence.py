from __future__ import annotations

from soma.foundation.audit.writer import AuditWriter
from soma.foundation.identifiers import new_uuid4
from soma.foundation.persistence.uow import UnitOfWork
from soma.ticket_import.commands.decide_proposal import ProposalDecisionService
from soma.tickets.audit_registry import build_tickets_audit_registry
from soma.tickets.queries.service_requests import ServiceRequestQueryService
from soma.tickets.sr_source_presence import (
    SOURCE_FAMILY,
    WARNING_CODE,
    ServiceRequestSourcePresenceRepository,
    ServiceRequestSourcePresenceService,
    SrSourceDisappearanceMutation,
    SrSourceReappearanceMutation,
)
from soma.tickets.service_requests import ServiceRequestService


class _ValidEvidence:
    def validate_disappearance_acceptance(self, *args, **kwargs):
        return "VALID"

    def validate_reappearance_evidence(self, *args, **kwargs):
        return "VALID"


def _receipt(uow, command_id: str, target_id: str) -> None:
    uow.connection.execute(
        "INSERT INTO command_receipts(command_id,command_type,request_hash,target_type,target_id,"
        "committed_at_utc,result_type,result_id) VALUES (?, 'PresenceTest', ?, 'service_request', ?, 1, NULL, NULL)",
        (command_id, "0" * 64, target_id),
    )


def _service_request(uow) -> str:
    sr_id = new_uuid4()
    uow.connection.execute(
        "INSERT INTO service_requests(service_request_id,official_sr_no,revision,created_at_utc,updated_at_utc) "
        "VALUES (?, '12345678', 1, 1, 1)",
        (sr_id,),
    )
    return sr_id


def test_source_presence_owner_chain_query_and_append_only(initialized_database) -> None:
    database_path, factory_for_path = initialized_database
    factory = factory_for_path(database_path)
    service = ServiceRequestSourcePresenceService(_ValidEvidence())
    writer = AuditWriter(build_tickets_audit_registry())
    proposal_id = new_uuid4()
    prior_observation_id = new_uuid4()
    first_run_id = new_uuid4()
    first_command_id = new_uuid4()

    with UnitOfWork(factory) as uow:
        sr_id = _service_request(uow)
        _receipt(uow, first_command_id, sr_id)
        base = ServiceRequestSourcePresenceRepository.current(
            uow.connection, sr_id, SOURCE_FAMILY
        ).base_token_sha256
        disappeared = service.apply_disappearance(
            uow,
            SrSourceDisappearanceMutation(
                service_request_id=sr_id,
                base_state_token=base,
                reconciliation_proposal_id=proposal_id,
                import_run_id=first_run_id,
                prior_source_observation_id=prior_observation_id,
                accepted_command_id=first_command_id,
                proposal_revision=1,
                proposal_fingerprint="1" * 64,
            ),
        )
        writer.write(uow, disappeared.audit_events[0])

    detail = ServiceRequestQueryService(factory).get(service_request_id=sr_id)
    assert detail.warnings == (WARNING_CODE,)

    second_run_id = new_uuid4()
    observation_id = new_uuid4()
    second_command_id = new_uuid4()
    with UnitOfWork(factory) as uow:
        _receipt(uow, second_command_id, sr_id)
        reappeared = service.apply_reappearance(
            uow,
            SrSourceReappearanceMutation(
                service_request_id=sr_id,
                expected_active_disappearance_event_id=disappeared.presence_event_id,
                import_run_id=second_run_id,
                source_observation_id=observation_id,
                accepted_command_id=second_command_id,
            ),
        )
        writer.write(uow, reappeared.audit_events[0])

    connection = factory.open_authoritative(read_only=True, require_wal=True)
    try:
        state = ServiceRequestSourcePresenceRepository.current(connection, sr_id, SOURCE_FAMILY)
        assert state.warning_active is False
        assert state.latest_event_id == reappeared.presence_event_id
    finally:
        connection.close()
    assert ServiceRequestQueryService(factory).get(service_request_id=sr_id).warnings == ()

    for statement in (
        "UPDATE sr_source_presence_events SET recorded_at_utc=2 WHERE sr_source_presence_event_id=?",
        "DELETE FROM sr_source_presence_events WHERE sr_source_presence_event_id=?",
    ):
        try:
            with UnitOfWork(factory) as uow:
                uow.connection.execute(statement, (disappeared.presence_event_id,))
        except Exception as exc:
            assert "SR_SOURCE_PRESENCE_APPEND_ONLY" in str(exc)
        else:
            raise AssertionError("append-only source-presence mutation unexpectedly succeeded")


def test_source_presence_base_token_binds_sr_revision_and_chain_head(initialized_database) -> None:
    database_path, factory_for_path = initialized_database
    factory = factory_for_path(database_path)
    with UnitOfWork(factory) as uow:
        sr_id = _service_request(uow)
        before = ServiceRequestSourcePresenceRepository.current(uow.connection, sr_id, SOURCE_FAMILY)
        uow.connection.execute("UPDATE service_requests SET revision=2 WHERE service_request_id=?", (sr_id,))
        after = ServiceRequestSourcePresenceRepository.current(uow.connection, sr_id, SOURCE_FAMILY)
        assert before.base_token_sha256 != after.base_token_sha256


def test_reappearance_cannot_be_a_chain_root(initialized_database) -> None:
    database_path, factory_for_path = initialized_database
    factory = factory_for_path(database_path)
    with UnitOfWork(factory) as uow:
        sr_id = _service_request(uow)
        command_id = new_uuid4()
        _receipt(uow, command_id, sr_id)
        try:
            uow.connection.execute(
                "INSERT INTO sr_source_presence_events(sr_source_presence_event_id,service_request_id,"
                "source_family,event_kind,prior_presence_event_id,import_run_id,source_observation_id,"
                "prior_source_observation_id,reconciliation_proposal_id,accepted_command_id,recorded_at_utc) "
                "VALUES (?,?,'advanced_search_sr','reappearance_confirmed',NULL,?,?,NULL,NULL,?,1)",
                (new_uuid4(), sr_id, new_uuid4(), new_uuid4(), command_id),
            )
        except Exception:
            pass
        else:
            raise AssertionError("reappearance root unexpectedly bypassed chain integrity")


def test_population_absence_acceptance_is_one_receipt_two_audits_and_exact_replay(initialized_database) -> None:
    database_path, factory_for_path = initialized_database
    factory = factory_for_path(database_path)
    sr = ServiceRequestService(factory).create_manual_service_request(
        command_id=new_uuid4(), official_sr_no="87654321"
    )
    prior_run_id = new_uuid4()
    current_run_id = new_uuid4()
    prior_observation_id = new_uuid4()
    proposal_id = new_uuid4()
    fingerprint = "7" * 64
    with UnitOfWork(factory) as uow:
        for run_id, state, completed, proposals in (
            (prior_run_id, "accepted", 2, 0),
            (current_run_id, "waiting_review", None, 1),
        ):
            uow.connection.execute(
                "INSERT INTO import_runs(import_run_id,source_family,invocation_kind,source_profile_id,"
                "header_registry_id,vocabulary_registry_id,parser_profile_id,candidate_filename,"
                "candidate_file_size_bytes,candidate_stable_mtime_ns,candidate_chronology_kind,"
                "candidate_chronology_value,logical_fingerprint_sha256,run_state,started_at_utc,staged_at_utc,"
                "completed_at_utc,proposal_count,pending_proposal_count,revision) "
                "VALUES (?,'advanced_search_sr','manual','ADVANCED_SEARCH_SR_V1','HEADERS','VOCAB','PARSER',"
                "'source.xlsx',1,1,'embedded_filename_timestamp_utc',1,?,?,1,1,?,?,?,1)",
                (run_id, "1" * 64, state, completed, proposals, proposals),
            )
        uow.connection.execute(
            "INSERT INTO source_observations(source_observation_id,import_run_id,source_family,entity_kind,"
            "identity_state,canonical_primary_id,row_ordinal,sheet_ordinal,row_logical_sha256,"
            "source_row_chronology_utc,presence_state,recorded_at_utc) "
            "VALUES (?,?,'advanced_search_sr','service_request','valid','87654321',1,1,?,1,"
            "'observed_valid_identity',1)",
            (prior_observation_id, prior_run_id, "2" * 64),
        )
        base = ServiceRequestSourcePresenceRepository.current(
            uow.connection, sr.service_request_id, SOURCE_FAMILY
        ).base_token_sha256
        uow.connection.execute(
            "INSERT INTO reconciliation_proposals(reconciliation_proposal_id,import_run_id,evidence_mode,"
            "source_observation_id,prior_source_observation_id,proposal_kind,target_kind,target_internal_id,"
            "target_business_id,risk_class,base_state_token_sha256,proposal_fingerprint_sha256,"
            "proposal_state,created_at_utc,revision) VALUES (?,?,'population_absence',NULL,?,"
            "'sr_source_disappearance_review','source_presence',?,'87654321','high',?,?,'pending',1,1)",
            (proposal_id, current_run_id, prior_observation_id, sr.service_request_id, base, fingerprint),
        )

    command_id = new_uuid4()
    service = ProposalDecisionService(factory)
    first = service.accept(
        command_id=command_id,
        proposal_id=proposal_id,
        proposal_revision=1,
        proposal_fingerprint=fingerprint,
        base_state_token=base,
        reason_category="reviewed_absence",
    )
    replay = service.accept(
        command_id=command_id,
        proposal_id=proposal_id,
        proposal_revision=1,
        proposal_fingerprint=fingerprint,
        base_state_token=base,
        reason_category="reviewed_absence",
    )
    assert first.replayed is False
    assert replay.replayed is True
    assert replay.owner_result_refs == first.owner_result_refs
    assert first.owner_result_refs[0][0] == "service_request_source_presence_history"
    connection = factory.open_authoritative(read_only=True, require_wal=True)
    try:
        assert connection.execute(
            "SELECT COUNT(*) FROM command_receipts WHERE command_id=?", (command_id,)
        ).fetchone()[0] == 1
        assert connection.execute(
            "SELECT COUNT(*) FROM sr_source_presence_events WHERE accepted_command_id=?", (command_id,)
        ).fetchone()[0] == 1
        assert [str(row[0]) for row in connection.execute(
            "SELECT action_type FROM audit_events WHERE command_id=? ORDER BY action_type", (command_id,)
        ).fetchall()] == [
            "ticket.service_request.source_presence_changed",
            "ticket_import.proposal_decided",
        ]
    finally:
        connection.close()
