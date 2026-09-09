from __future__ import annotations

from soma.foundation.application.command_receipts import CommandReceipt, CommandReceiptStore
from soma.foundation.audit.writer import AuditWriter
from soma.foundation.identifiers import new_uuid4
from soma.foundation.persistence.uow import UnitOfWork
from soma.ticket_import.providers.rfc_source_evidence import TicketImportRfcSourceEvidenceProvider
from soma.tickets.audit_registry import build_tickets_audit_registry
from soma.tickets.rfc_source_projection import RfcSourceProjectionService
from soma.tickets.rfcs import RfcService


def _factory(initialized_database):
    database_path, factory_for_path = initialized_database
    return factory_for_path(database_path)


def _insert_outer_receipt(uow: UnitOfWork, command_id: str, rfc_id: str) -> None:
    CommandReceiptStore().insert(
        uow,
        CommandReceipt(
            command_id=command_id,
            command_type="AcceptReconciliationProposal",
            request_hash="0" * 64,
            target_type="reconciliation_proposal",
            target_id=rfc_id,
            committed_at_utc=1,
            result_type=None,
            result_id=None,
        ),
    )


def _seed_status(
    factory,
    *,
    source_family: str,
    rfc_no: str,
    status_text: str,
    task_no: str | None = None,
):
    run_id = new_uuid4()
    observation_id = new_uuid4()
    field_id = new_uuid4()
    if source_family == "rfc_enhanced":
        entity_kind = "rfc"
        canonical_primary_id = rfc_no
        canonical_parent_rfc_no = None
        field_key = "status"
        chronology_kind = "filesystem_mtime_ns"
        profile_id = "RFC_ENHANCED_V1"
        filename = "Enhanced Excel Data Export.xlsx"
    else:
        assert task_no is not None
        entity_kind = "wfm"
        canonical_primary_id = task_no
        canonical_parent_rfc_no = rfc_no
        field_key = "rfc_status"
        chronology_kind = "embedded_filename_timestamp_utc"
        profile_id = "WFM_SERVICE_PROVIDER_V1"
        filename = "Service Provider Plan Creation20260908010000.xlsx"
    with UnitOfWork(factory) as uow:
        uow.connection.execute(
            "INSERT INTO import_runs("
            "import_run_id,source_family,invocation_kind,source_profile_id,header_registry_id,vocabulary_registry_id,parser_profile_id,"
            "candidate_filename,candidate_file_size_bytes,candidate_stable_mtime_ns,candidate_chronology_kind,candidate_chronology_value,"
            "logical_fingerprint_sha256,run_state,started_at_utc,staged_at_utc,observed_row_count,valid_identity_count,revision"
            ") VALUES (?,?,'manual',?,'HEADERS_V1','RFC_STATUS_V1','PARSER_V1',?,100,1,?,200,?,'waiting_review',0,1,1,1,1)",
            (run_id, source_family, profile_id, filename, chronology_kind, "1" * 64),
        )
        uow.connection.execute(
            "INSERT INTO source_observations("
            "source_observation_id,import_run_id,source_family,entity_kind,identity_state,canonical_primary_id,canonical_parent_rfc_no,"
            "row_ordinal,sheet_ordinal,row_logical_sha256,source_row_chronology_utc,presence_state,recorded_at_utc"
            ") VALUES (?,?,?,?, 'valid',?,?,1,1,?,100,'observed_valid_identity',1)",
            (
                observation_id,
                run_id,
                source_family,
                entity_kind,
                canonical_primary_id,
                canonical_parent_rfc_no,
                "2" * 64,
            ),
        )
        uow.connection.execute(
            "INSERT INTO source_observation_fields("
            "source_observation_field_id,source_observation_id,field_key,field_class,value_state,value_kind,source_text,"
            "normalized_text,integer_value,vocabulary_id,field_logical_sha256"
            ") VALUES (?, ?, ?, 'active', 'usable', 'controlled', ?, ?, NULL, 'RFC_STATUS_V1', ?)",
            (field_id, observation_id, field_key, status_text, status_text, "3" * 64),
        )
    return run_id, observation_id, field_id


def _apply_published_status(factory, *, rfc_id: str, run_id: str, observation_id: str, field_id: str):
    provider = TicketImportRfcSourceEvidenceProvider()
    service = RfcSourceProjectionService(provider)
    command_id = new_uuid4()
    with UnitOfWork(factory) as uow:
        delta = provider.build_source_projection_delta(
            uow.connection,
            rfc_id=rfc_id,
            expected_import_run_id=run_id,
            expected_source_observation_id=observation_id,
            source_observation_field_id=field_id,
            expected_field_key="status",
        )
        _insert_outer_receipt(uow, command_id, rfc_id)
        result = service.apply_accepted_field_deltas(
            uow,
            rfc_id=rfc_id,
            accepted_command_id=command_id,
            deltas=(delta,),
        )
        if result.audit_events:
            AuditWriter(build_tickets_audit_registry()).write_many(uow, result.audit_events)
        return result, command_id


def _projection(factory, rfc_id: str):
    connection = factory.open_authoritative(read_only=True, require_wal=True)
    try:
        return connection.execute(
            "SELECT status_text,status_class,status_authority,status_evidence_id,terminal_epoch_id,revision "
            "FROM rfc_current_source_projection WHERE rfc_id=?",
            (rfc_id,),
        ).fetchone()
    finally:
        connection.close()


def test_published_wfm_then_enhanced_status_respects_authority_and_blocks_later_wfm_override(initialized_database) -> None:
    factory = _factory(initialized_database)
    rfc = RfcService(factory).create_or_adopt_identity(
        command_id=new_uuid4(),
        rfc_no="NC20260908004001",
        creation_context="manual",
    )

    wfm_run, wfm_observation, wfm_field = _seed_status(
        factory,
        source_family="wfm_service_provider",
        rfc_no="NC20260908004001",
        task_no="TK20260908005001",
        status_text="Implement",
    )
    provisional, _ = _apply_published_status(
        factory,
        rfc_id=rfc.rfc_id,
        run_id=wfm_run,
        observation_id=wfm_observation,
        field_id=wfm_field,
    )
    assert provisional.no_change is False
    assert tuple(_projection(factory, rfc.rfc_id)) == (
        "Implement",
        "implement_eligible",
        "wfm_provisional",
        wfm_field,
        None,
        1,
    )

    enhanced_run, enhanced_observation, enhanced_field = _seed_status(
        factory,
        source_family="rfc_enhanced",
        rfc_no="NC20260908004001",
        status_text="Implement",
    )
    authoritative, authoritative_command = _apply_published_status(
        factory,
        rfc_id=rfc.rfc_id,
        run_id=enhanced_run,
        observation_id=enhanced_observation,
        field_id=enhanced_field,
    )
    assert authoritative.no_change is False
    assert tuple(_projection(factory, rfc.rfc_id)) == (
        "Implement",
        "implement_eligible",
        "enhanced_rfc",
        enhanced_field,
        None,
        2,
    )

    later_wfm_run, later_wfm_observation, later_wfm_field = _seed_status(
        factory,
        source_family="wfm_service_provider",
        rfc_no="NC20260908004001",
        task_no="TK20260908005002",
        status_text="Cancelled",
    )
    ignored, ignored_command = _apply_published_status(
        factory,
        rfc_id=rfc.rfc_id,
        run_id=later_wfm_run,
        observation_id=later_wfm_observation,
        field_id=later_wfm_field,
    )
    assert ignored.no_change is True
    assert ignored.audit_events == ()
    assert tuple(_projection(factory, rfc.rfc_id)) == (
        "Implement",
        "implement_eligible",
        "enhanced_rfc",
        enhanced_field,
        None,
        2,
    )

    connection = factory.open_authoritative(read_only=True, require_wal=True)
    try:
        assert connection.execute(
            "SELECT COUNT(*) FROM audit_events WHERE command_id=? AND action_type='ticket.rfc.source_projection_applied'",
            (authoritative_command,),
        ).fetchone()[0] == 1
        assert connection.execute(
            "SELECT COUNT(*) FROM audit_events WHERE command_id=? AND action_type='ticket.rfc.source_projection_applied'",
            (ignored_command,),
        ).fetchone()[0] == 0
    finally:
        connection.close()
