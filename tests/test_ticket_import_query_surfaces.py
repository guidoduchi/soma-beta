from __future__ import annotations

import pytest

from soma.foundation.errors import SomaError
from soma.foundation.identifiers import new_uuid4
from soma.foundation.persistence.uow import UnitOfWork
from soma.ticket_import.queries.proposals import ProposalQueryService
from soma.ticket_import.queries.runs import ImportRunQueryService
from soma.tickets.service_request_import_reader import ServiceRequestImportReader
from soma.tickets.service_requests import ServiceRequestService


def _factory(initialized_database):
    database_path, factory_builder = initialized_database
    return factory_builder(database_path)


def _run(
    uow,
    *,
    run_id: str,
    state: str = "staged",
    chronology: int = 100,
    fingerprint: str | None = "a" * 64,
    started: int = 1,
) -> None:
    uow.connection.execute(
        "INSERT INTO import_runs(import_run_id,source_family,invocation_kind,source_profile_id,"
        "header_registry_id,vocabulary_registry_id,parser_profile_id,candidate_filename,"
        "candidate_file_size_bytes,candidate_stable_mtime_ns,candidate_chronology_kind,"
        "candidate_chronology_value,logical_fingerprint_sha256,run_state,started_at_utc,"
        "staged_at_utc,completed_at_utc,revision) VALUES (?,'advanced_search_sr','manual',"
        "'ADVANCED_SEARCH_SR_V1','ADVANCED_SEARCH_HEADERS_V1','ADVANCED_SEARCH_VOCAB_V1',"
        "'ADVANCED_SEARCH_PARSER_V1','source.xlsx',1,1,'embedded_filename_timestamp_utc',"
        "?,?,?,?,?,?,1)",
        (
            run_id,
            chronology,
            fingerprint,
            state,
            started,
            started if state not in {"discovering", "validating", "failed"} else None,
            started if state in {"accepted", "rejected", "partially_accepted", "noop", "failed"} else None,
        ),
    )


def _observation(
    uow,
    *,
    run_id: str,
    row: int,
    identity: str,
    sheet: int = 1,
    normalized_text: str | None = None,
) -> tuple[str, str]:
    observation_id = new_uuid4()
    field_id = new_uuid4()
    uow.connection.execute(
        "INSERT INTO source_observations(source_observation_id,import_run_id,source_family,entity_kind,"
        "identity_state,canonical_primary_id,canonical_parent_rfc_no,row_ordinal,sheet_ordinal,"
        "row_logical_sha256,source_row_chronology_utc,presence_state,recorded_at_utc) "
        "VALUES (?,?,'advanced_search_sr','service_request','valid',?,NULL,?,?,?,NULL,"
        "'observed_valid_identity',1)",
        (observation_id, run_id, identity, row, sheet, f"{row:064x}"[-64:]),
    )
    text = identity if normalized_text is None else normalized_text
    uow.connection.execute(
        "INSERT INTO source_observation_fields(source_observation_field_id,source_observation_id,field_key,"
        "field_class,value_state,value_kind,source_text,normalized_text,integer_value,vocabulary_id,"
        "field_logical_sha256) VALUES (?,?,'problem_summary','active','usable','text',?,?,NULL,NULL,?)",
        (field_id, observation_id, text, text, "f" * 64),
    )
    return observation_id, field_id


def _finding(uow, *, run_id: str, severity: str, code: str, observation_id: str | None = None) -> str:
    finding_id = new_uuid4()
    uow.connection.execute(
        "INSERT INTO import_findings(import_finding_id,import_run_id,source_observation_id,field_key,"
        "finding_code,severity,scope_kind,message_text,recorded_at_utc) VALUES (?,?,?,NULL,?,?,'row',?,1)",
        (finding_id, run_id, observation_id, code, severity, f"{code} message"),
    )
    return finding_id


def _proposal(
    uow,
    *,
    run_id: str,
    observation_id: str,
    business_id: str,
    risk: str,
    base_token: str,
    proposal_kind: str = "sr_create_or_adopt",
    target_kind: str = "service_request",
) -> str:
    proposal_id = new_uuid4()
    uow.connection.execute(
        "INSERT INTO reconciliation_proposals(reconciliation_proposal_id,import_run_id,evidence_mode,"
        "source_observation_id,prior_source_observation_id,proposal_kind,target_kind,target_internal_id,"
        "target_business_id,risk_class,base_state_token_sha256,proposal_fingerprint_sha256,proposal_state,"
        "created_at_utc,revision,decided_at_utc) VALUES (?,?,'observed_row',?,NULL,?,?,NULL,?,?,?,?,'pending',1,1,NULL)",
        (
            proposal_id,
            run_id,
            observation_id,
            proposal_kind,
            target_kind,
            business_id,
            risk,
            base_token,
            "b" * 64,
        ),
    )
    return proposal_id


def test_published_observations_are_typed_paged_and_filter_bound(initialized_database) -> None:
    factory = _factory(initialized_database)
    run_id = new_uuid4()
    unpublished_run_id = new_uuid4()
    with UnitOfWork(factory) as uow:
        _run(uow, run_id=run_id)
        _run(uow, run_id=unpublished_run_id, state="validating", fingerprint=None, started=2)
        for row, identity in ((3, "00000003"), (1, "00000001"), (2, "00000002")):
            _observation(uow, run_id=run_id, row=row, identity=identity, normalized_text=f"summary-{row}")

    service = ImportRunQueryService(factory)
    first = service.list_published_observations(run_id, limit=2)
    assert [item.row_ordinal for item in first.items] == [1, 2]
    assert [item.fields[0].display_value for item in first.items] == ["summary-1", "summary-2"]
    assert first.next_cursor is not None

    second = service.list_published_observations(run_id, cursor=first.next_cursor, limit=2)
    assert [item.row_ordinal for item in second.items] == [3]

    with pytest.raises(SomaError) as excinfo:
        service.list_published_observations(
            run_id,
            identity_state="valid",
            cursor=first.next_cursor,
            limit=2,
        )
    assert excinfo.value.code == "IMPORT_CURSOR_INVALID"

    with pytest.raises(SomaError) as excinfo:
        service.list_published_observations(unpublished_run_id)
    assert excinfo.value.code == "IMPORT_RUN_UNPUBLISHED"


def test_findings_are_ranked_paged_and_unpublished_evidence_is_hidden(initialized_database) -> None:
    factory = _factory(initialized_database)
    run_id = new_uuid4()
    unpublished_run_id = new_uuid4()
    with UnitOfWork(factory) as uow:
        _run(uow, run_id=run_id)
        _run(uow, run_id=unpublished_run_id, state="validating", fingerprint=None, started=2)
        observation_id, _field_id = _observation(uow, run_id=run_id, row=1, identity="00000001")
        _finding(uow, run_id=run_id, severity="high_risk", code="HIGH", observation_id=observation_id)
        _finding(uow, run_id=run_id, severity="info", code="INFO", observation_id=observation_id)
        _finding(uow, run_id=run_id, severity="warning", code="WARN", observation_id=observation_id)

    service = ImportRunQueryService(factory)
    first = service.list_findings(run_id, limit=2)
    assert [item.severity for item in first.items] == ["info", "warning"]
    assert first.next_cursor is not None
    second = service.list_findings(run_id, cursor=first.next_cursor, limit=2)
    assert [item.severity for item in second.items] == ["high_risk"]

    with pytest.raises(SomaError) as excinfo:
        service.list_findings(run_id, severity="warning", cursor=first.next_cursor, limit=2)
    assert excinfo.value.code == "IMPORT_CURSOR_INVALID"
    assert service.list_findings(unpublished_run_id).items == ()


def test_proposal_list_uses_risk_desc_keyset_and_filter_bound_cursor(initialized_database) -> None:
    factory = _factory(initialized_database)
    run_id = new_uuid4()
    with UnitOfWork(factory) as uow:
        _run(uow, run_id=run_id)
        observation_id, _field_id = _observation(uow, run_id=run_id, row=1, identity="00000001")
        for suffix, risk in (("01", "low"), ("02", "blocked"), ("03", "high")):
            _proposal(
                uow,
                run_id=run_id,
                observation_id=observation_id,
                business_id=f"000000{suffix}",
                risk=risk,
                base_token="c" * 64,
            )

    service = ProposalQueryService(factory)
    first = service.list_proposals(run_id, limit=2)
    assert [item.risk_class for item in first.items] == ["blocked", "high"]
    assert first.next_cursor is not None
    second = service.list_proposals(run_id, cursor=first.next_cursor, limit=2)
    assert [item.risk_class for item in second.items] == ["low"]

    with pytest.raises(SomaError) as excinfo:
        service.list_proposals(run_id, risk="high", cursor=first.next_cursor, limit=2)
    assert excinfo.value.code == "IMPORT_CURSOR_INVALID"


def test_proposal_review_marks_owner_drift_stale_without_losing_decision_history(initialized_database) -> None:
    factory = _factory(initialized_database)
    run_id = new_uuid4()
    official_sr_no = "87654321"
    with UnitOfWork(factory) as uow:
        _run(uow, run_id=run_id)
        observation_id, _field_id = _observation(uow, run_id=run_id, row=1, identity=official_sr_no)
        base_token = ServiceRequestImportReader.source_identity_base_token(uow.connection, official_sr_no)
        proposal_id = _proposal(
            uow,
            run_id=run_id,
            observation_id=observation_id,
            business_id=official_sr_no,
            risk="high",
            base_token=base_token,
        )
        uow.connection.execute(
            "INSERT INTO reconciliation_proposal_changes(reconciliation_proposal_id,ordinal,field_key,"
            "change_kind,value_kind,before_text,after_text,before_integer,after_integer,source_observation_field_id) "
            "VALUES (?,0,'official_sr_no','create','identity',NULL,?,NULL,NULL,NULL)",
            (proposal_id, official_sr_no),
        )

    service = ProposalQueryService(factory)
    review = service.get_review(proposal_id)
    assert review.stale is False
    assert review.allowed_dispositions == ("accept", "reject", "defer")
    assert review.target_preview["identity"] is None
    assert review.changes[0]["after"] == official_sr_no

    with UnitOfWork(factory) as uow:
        now = 10
        uow.connection.execute(
            "INSERT INTO service_requests(service_request_id,official_sr_no,local_sr_no,revision,created_at_utc,updated_at_utc) "
            "VALUES (?,?,NULL,1,?,?)",
            (new_uuid4(), official_sr_no, now, now),
        )

    drifted = service.get_review(proposal_id)
    assert drifted.stale is True
    assert drifted.allowed_dispositions == ("reject", "defer")
    assert drifted.target_preview["identity"] is not None


def test_proposal_review_uses_certified_sr_source_field_set_token(initialized_database) -> None:
    factory = _factory(initialized_database)
    sr_no = "87654322"
    sr = ServiceRequestService(factory).create_manual_service_request(
        command_id=new_uuid4(),
        official_sr_no=sr_no,
    )
    run_id = new_uuid4()
    proposal_id = new_uuid4()
    with UnitOfWork(factory) as uow:
        _run(uow, run_id=run_id)
        observation_id, field_id = _observation(
            uow,
            run_id=run_id,
            row=1,
            identity=sr_no,
            normalized_text="new source summary",
        )
        base_token = ServiceRequestImportReader.source_field_set_base_token(
            uow.connection,
            sr.service_request_id,
            ("problem_summary",),
        )
        uow.connection.execute(
            "INSERT INTO reconciliation_proposals(reconciliation_proposal_id,import_run_id,evidence_mode,"
            "source_observation_id,prior_source_observation_id,proposal_kind,target_kind,target_internal_id,"
            "target_business_id,risk_class,base_state_token_sha256,proposal_fingerprint_sha256,proposal_state,"
            "created_at_utc,revision,decided_at_utc) "
            "VALUES (?,?,'observed_row',?,NULL,'sr_source_projection','service_request',?,?, 'low',?,?,"
            "'pending',1,1,NULL)",
            (proposal_id, run_id, observation_id, sr.service_request_id, sr_no, base_token, "d" * 64),
        )
        uow.connection.execute(
            "INSERT INTO reconciliation_proposal_changes(reconciliation_proposal_id,ordinal,field_key,change_kind,"
            "value_kind,before_text,after_text,before_integer,after_integer,source_observation_field_id) "
            "VALUES (?,0,'problem_summary','set','text',NULL,'new source summary',NULL,NULL,?)",
            (proposal_id, field_id),
        )

    review = ProposalQueryService(factory).get_review(proposal_id)
    assert review.stale is False
    assert review.allowed_dispositions == ("accept", "reject", "defer")
    assert review.proposal.base_state_token == base_token
