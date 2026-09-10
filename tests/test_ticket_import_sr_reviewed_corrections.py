from __future__ import annotations

import pytest

from soma.foundation.errors import SomaError
from soma.foundation.identifiers import new_uuid4
from soma.foundation.persistence.uow import ReadSnapshot, UnitOfWork
from soma.ticket_import.commands.decide_proposal import ProposalDecisionService
from soma.tickets.import_mutations import ServiceRequestImportMutationService
from soma.tickets.service_requests import ServiceRequestService


def _factory(initialized_database):
    database_path, factory_for_path = initialized_database
    return factory_for_path(database_path)


def _official_sr(factory, sr_no: str):
    return ServiceRequestService(factory).create_manual_service_request(
        command_id=new_uuid4(),
        official_sr_no=sr_no,
    )


def _base_token(factory, service_request_id: str) -> str:
    with ReadSnapshot(factory) as snapshot:
        return ServiceRequestImportMutationService.source_acceptance_base_token(
            snapshot.connection,
            service_request_id,
        )


def _seed_proposal(
    factory,
    *,
    service_request_id: str,
    sr_no: str,
    proposal_kind: str,
    risk_class: str,
    field_key: str,
    value_kind: str,
    chronology: int,
    before_text: str | None = None,
    after_text: str | None = None,
    before_integer: int | None = None,
    after_integer: int | None = None,
    vocabulary_id: str | None = None,
):
    run_id = new_uuid4()
    observation_id = new_uuid4()
    field_id = new_uuid4()
    proposal_id = new_uuid4()
    fingerprint = new_uuid4().replace("-", "") + new_uuid4().replace("-", "")
    fingerprint = fingerprint[:64]
    base_token = _base_token(factory, service_request_id)
    normalized_text = after_text if value_kind in {"text", "controlled"} else None
    integer_value = after_integer if value_kind in {"instant", "duration_seconds"} else None
    source_text = after_text if after_text is not None else str(after_integer)
    with UnitOfWork(factory) as uow:
        uow.connection.execute(
            "INSERT INTO import_runs("
            "import_run_id,source_family,invocation_kind,source_profile_id,header_registry_id,vocabulary_registry_id,parser_profile_id,"
            "candidate_filename,candidate_file_size_bytes,candidate_stable_mtime_ns,candidate_chronology_kind,candidate_chronology_value,"
            "logical_fingerprint_sha256,run_state,started_at_utc,staged_at_utc,observed_row_count,valid_identity_count,"
            "proposal_count,pending_proposal_count,revision"
            ") VALUES (?, 'advanced_search_sr','manual','ADVANCED_SEARCH_SR_V1','ADVANCED_SEARCH_HEADERS_V1',"
            "'ADVANCED_SEARCH_VOCAB_V1','ADVANCED_SEARCH_PARSER_V1','Advanced Search(Service Request)20260908010000.xlsx',"
            "100,1,'embedded_filename_timestamp_utc',200,?,'waiting_review',0,1,1,1,1,1,1)",
            (run_id, "1" * 64),
        )
        uow.connection.execute(
            "INSERT INTO source_observations(source_observation_id,import_run_id,source_family,entity_kind,identity_state,"
            "canonical_primary_id,canonical_parent_rfc_no,row_ordinal,sheet_ordinal,row_logical_sha256,source_row_chronology_utc,"
            "presence_state,recorded_at_utc) VALUES (?,?,'advanced_search_sr','service_request','valid',?,NULL,1,1,?,?,"
            "'observed_valid_identity',1)",
            (observation_id, run_id, sr_no, "2" * 64, chronology),
        )
        uow.connection.execute(
            "INSERT INTO source_observation_fields(source_observation_field_id,source_observation_id,field_key,field_class,"
            "value_state,value_kind,source_text,normalized_text,integer_value,vocabulary_id,field_logical_sha256) "
            "VALUES (?,?,?,'active','usable',?,?,?,?,?,?)",
            (
                field_id,
                observation_id,
                field_key,
                value_kind,
                source_text,
                normalized_text,
                integer_value,
                vocabulary_id,
                "3" * 64,
            ),
        )
        uow.connection.execute(
            "INSERT INTO reconciliation_proposals(reconciliation_proposal_id,import_run_id,evidence_mode,source_observation_id,"
            "prior_source_observation_id,proposal_kind,target_kind,target_internal_id,target_business_id,risk_class,"
            "base_state_token_sha256,proposal_fingerprint_sha256,proposal_state,created_at_utc,revision,decided_at_utc) "
            "VALUES (?,?, 'observed_row',?,NULL,?,'service_request',?,?,?, ?,?,'pending',1,1,NULL)",
            (
                proposal_id,
                run_id,
                observation_id,
                proposal_kind,
                service_request_id,
                sr_no,
                risk_class,
                base_token,
                fingerprint,
            ),
        )
        uow.connection.execute(
            "INSERT INTO reconciliation_proposal_changes(reconciliation_proposal_id,ordinal,field_key,change_kind,value_kind,"
            "before_text,after_text,before_integer,after_integer,source_observation_field_id) "
            "VALUES (?,0,?,'set',?,?,?,?,?,?)",
            (
                proposal_id,
                field_key,
                value_kind,
                before_text,
                after_text,
                before_integer,
                after_integer,
                field_id,
            ),
        )
    return {
        "run_id": run_id,
        "observation_id": observation_id,
        "field_id": field_id,
        "proposal_id": proposal_id,
        "fingerprint": fingerprint,
        "base_token": base_token,
    }


def _accept(factory, seeded, *, reason="reviewed_correction"):
    return ProposalDecisionService(factory).accept(
        command_id=new_uuid4(),
        proposal_id=seeded["proposal_id"],
        proposal_revision=1,
        proposal_fingerprint=seeded["fingerprint"],
        base_state_token=seeded["base_token"],
        reason_category=reason,
    )


def _current_field(factory, service_request_id: str, projection_column: str):
    with ReadSnapshot(factory) as snapshot:
        row = snapshot.connection.execute(
            f"SELECT o.value_state,o.value_kind,o.text_value,o.integer_value,o.source_chronology_utc,"
            "o.precedence_basis,o.source_observation_field_id,o.accepted_command_id "
            "FROM sr_current_source_projection p JOIN sr_source_field_observations o "
            f"ON o.sr_source_field_observation_id=p.{projection_column} WHERE p.service_request_id=?",
            (service_request_id,),
        ).fetchone()
        return None if row is None else tuple(row)


def _receipt_count(factory, command_id: str) -> int:
    with ReadSnapshot(factory) as snapshot:
        return int(
            snapshot.connection.execute(
                "SELECT COUNT(*) FROM command_receipts WHERE command_id=?",
                (command_id,),
            ).fetchone()[0]
        )


def test_terminal_reviewed_correction_can_override_older_source_chronology(initialized_database) -> None:
    factory = _factory(initialized_database)
    sr = _official_sr(factory, "33000001")
    initial = _seed_proposal(
        factory,
        service_request_id=sr.service_request_id,
        sr_no="33000001",
        proposal_kind="sr_source_projection",
        risk_class="high",
        field_key="status",
        value_kind="controlled",
        chronology=200,
        after_text="Closed",
        vocabulary_id="ADVANCED_SEARCH_STATUS_V1",
    )
    _accept(factory, initial, reason="terminal_entry")

    correction = _seed_proposal(
        factory,
        service_request_id=sr.service_request_id,
        sr_no="33000001",
        proposal_kind="sr_terminal_reversal_review",
        risk_class="high",
        field_key="status",
        value_kind="controlled",
        chronology=100,
        before_text="Closed",
        after_text="Customer Agreed Suspend",
        vocabulary_id="ADVANCED_SEARCH_STATUS_V1",
    )
    command_id = new_uuid4()
    service = ProposalDecisionService(factory)
    result = service.accept(
        command_id=command_id,
        proposal_id=correction["proposal_id"],
        proposal_revision=1,
        proposal_fingerprint=correction["fingerprint"],
        base_state_token=correction["base_token"],
        reason_category="reviewed_terminal_reversal",
    )

    assert result.decision == "accepted"
    assert result.replayed is False
    current = _current_field(factory, sr.service_request_id, "status_observation_id")
    assert current is not None
    assert current[:6] == (
        "usable",
        "controlled",
        "Customer Agreed Suspend",
        None,
        100,
        "reviewed_correction",
    )
    assert current[6] == correction["field_id"]
    assert current[7] == command_id

    replay = service.accept(
        command_id=command_id,
        proposal_id=correction["proposal_id"],
        proposal_revision=1,
        proposal_fingerprint=correction["fingerprint"],
        base_state_token=correction["base_token"],
        reason_category="reviewed_terminal_reversal",
    )
    assert replay.replayed is True
    assert replay.owner_result_refs == result.owner_result_refs


def test_suspension_regression_review_can_accept_zero_with_older_source_chronology(initialized_database) -> None:
    factory = _factory(initialized_database)
    sr = _official_sr(factory, "33000002")
    initial = _seed_proposal(
        factory,
        service_request_id=sr.service_request_id,
        sr_no="33000002",
        proposal_kind="sr_source_projection",
        risk_class="medium",
        field_key="suspension_duration",
        value_kind="duration_seconds",
        chronology=300,
        after_integer=7200,
    )
    _accept(factory, initial, reason="source_duration")

    correction = _seed_proposal(
        factory,
        service_request_id=sr.service_request_id,
        sr_no="33000002",
        proposal_kind="sr_suspension_regression_review",
        risk_class="high",
        field_key="suspension_duration",
        value_kind="duration_seconds",
        chronology=100,
        before_integer=7200,
        after_integer=0,
    )
    result = _accept(factory, correction)

    assert result.decision == "accepted"
    current = _current_field(factory, sr.service_request_id, "suspension_duration_observation_id")
    assert current is not None
    assert current[:6] == (
        "usable",
        "duration_seconds",
        None,
        0,
        100,
        "reviewed_correction",
    )
    assert current[6] == correction["field_id"]


@pytest.mark.parametrize(
    ("proposal_kind", "field_key", "value_kind", "before_text", "after_text", "before_integer", "after_integer", "vocabulary"),
    [
        (
            "sr_terminal_reversal_review",
            "status",
            "controlled",
            "Closed",
            "Customer Agreed Suspend",
            None,
            None,
            "ADVANCED_SEARCH_STATUS_V1",
        ),
        (
            "sr_suspension_regression_review",
            "suspension_duration",
            "duration_seconds",
            None,
            None,
            7200,
            0,
            None,
        ),
    ],
)
def test_reviewed_source_correction_must_remain_high_risk(
    initialized_database,
    proposal_kind,
    field_key,
    value_kind,
    before_text,
    after_text,
    before_integer,
    after_integer,
    vocabulary,
) -> None:
    factory = _factory(initialized_database)
    sr = _official_sr(factory, "33000003")
    initial_value_text = "Closed" if field_key == "status" else None
    initial_value_integer = 7200 if field_key == "suspension_duration" else None
    initial = _seed_proposal(
        factory,
        service_request_id=sr.service_request_id,
        sr_no="33000003",
        proposal_kind="sr_source_projection",
        risk_class="high" if field_key == "status" else "medium",
        field_key=field_key,
        value_kind=value_kind,
        chronology=200,
        after_text=initial_value_text,
        after_integer=initial_value_integer,
        vocabulary_id=vocabulary,
    )
    _accept(factory, initial, reason="initial_source")
    correction = _seed_proposal(
        factory,
        service_request_id=sr.service_request_id,
        sr_no="33000003",
        proposal_kind=proposal_kind,
        risk_class="medium",
        field_key=field_key,
        value_kind=value_kind,
        chronology=100,
        before_text=before_text,
        after_text=after_text,
        before_integer=before_integer,
        after_integer=after_integer,
        vocabulary_id=vocabulary,
    )
    command_id = new_uuid4()

    with pytest.raises(SomaError) as excinfo:
        ProposalDecisionService(factory).accept(
            command_id=command_id,
            proposal_id=correction["proposal_id"],
            proposal_revision=1,
            proposal_fingerprint=correction["fingerprint"],
            base_state_token=correction["base_token"],
        )
    assert excinfo.value.code == "IMPORT_PROPOSAL_STALE"
    assert _receipt_count(factory, command_id) == 0


def test_terminal_reviewed_correction_stales_when_reviewed_before_state_is_wrong(initialized_database) -> None:
    factory = _factory(initialized_database)
    sr = _official_sr(factory, "33000004")
    initial = _seed_proposal(
        factory,
        service_request_id=sr.service_request_id,
        sr_no="33000004",
        proposal_kind="sr_source_projection",
        risk_class="high",
        field_key="status",
        value_kind="controlled",
        chronology=200,
        after_text="Closed",
        vocabulary_id="ADVANCED_SEARCH_STATUS_V1",
    )
    _accept(factory, initial, reason="terminal_entry")
    correction = _seed_proposal(
        factory,
        service_request_id=sr.service_request_id,
        sr_no="33000004",
        proposal_kind="sr_terminal_reversal_review",
        risk_class="high",
        field_key="status",
        value_kind="controlled",
        chronology=100,
        before_text="Resolved",
        after_text="Customer Agreed Suspend",
        vocabulary_id="ADVANCED_SEARCH_STATUS_V1",
    )
    command_id = new_uuid4()

    with pytest.raises(SomaError) as excinfo:
        ProposalDecisionService(factory).accept(
            command_id=command_id,
            proposal_id=correction["proposal_id"],
            proposal_revision=1,
            proposal_fingerprint=correction["fingerprint"],
            base_state_token=correction["base_token"],
        )
    assert excinfo.value.code == "IMPORT_PROPOSAL_STALE"
    assert _receipt_count(factory, command_id) == 0
    current = _current_field(factory, sr.service_request_id, "status_observation_id")
    assert current is not None and current[2] == "Closed"


def test_ordinary_source_projection_cannot_smuggle_suspension_regression(initialized_database) -> None:
    factory = _factory(initialized_database)
    sr = _official_sr(factory, "33000005")
    initial = _seed_proposal(
        factory,
        service_request_id=sr.service_request_id,
        sr_no="33000005",
        proposal_kind="sr_source_projection",
        risk_class="medium",
        field_key="suspension_duration",
        value_kind="duration_seconds",
        chronology=100,
        after_integer=7200,
    )
    _accept(factory, initial, reason="source_duration")
    ordinary_regression = _seed_proposal(
        factory,
        service_request_id=sr.service_request_id,
        sr_no="33000005",
        proposal_kind="sr_source_projection",
        risk_class="medium",
        field_key="suspension_duration",
        value_kind="duration_seconds",
        chronology=200,
        before_integer=7200,
        after_integer=0,
    )
    command_id = new_uuid4()

    with pytest.raises(SomaError) as excinfo:
        ProposalDecisionService(factory).accept(
            command_id=command_id,
            proposal_id=ordinary_regression["proposal_id"],
            proposal_revision=1,
            proposal_fingerprint=ordinary_regression["fingerprint"],
            base_state_token=ordinary_regression["base_token"],
        )
    assert excinfo.value.code == "SR_SOURCE_EVIDENCE_INVALID"
    assert _receipt_count(factory, command_id) == 0
    current = _current_field(factory, sr.service_request_id, "suspension_duration_observation_id")
    assert current is not None and current[3] == 7200
