from __future__ import annotations

import pytest

from soma.foundation.errors import SomaError
from soma.foundation.identifiers import new_uuid4
from soma.foundation.persistence.uow import UnitOfWork
from soma.ticket_import.providers.rfc_source_evidence import TicketImportRfcSourceEvidenceProvider
from soma.ticket_import.providers.sr_source_evidence import TicketImportSrSourceEvidenceProvider
from soma.tickets.rfc_source_projection import RfcAcceptedFieldDelta
from soma.tickets.rfcs import RfcService
from soma.tickets.service_requests import ServiceRequestService


def _factory(initialized_database):
    database_path, factory_for_path = initialized_database
    return factory_for_path(database_path)


def _seed_mismatched_field(
    factory,
    *,
    run_source_family: str,
    observation_source_family: str,
    source_profile_id: str,
    entity_kind: str,
    canonical_primary_id: str,
    canonical_parent_rfc_no: str | None,
    field_key: str,
    value_kind: str,
    normalized_text: str,
    vocabulary_id: str | None = None,
) -> tuple[str, str, str]:
    run_id = new_uuid4()
    observation_id = new_uuid4()
    field_id = new_uuid4()
    chronology_kind = (
        "embedded_filename_timestamp_utc"
        if run_source_family in {"advanced_search_sr", "wfm_service_provider"}
        else "filesystem_mtime_ns"
    )
    with UnitOfWork(factory) as uow:
        uow.connection.execute(
            "INSERT INTO import_runs("
            "import_run_id,source_family,invocation_kind,source_profile_id,header_registry_id,vocabulary_registry_id,parser_profile_id,"
            "candidate_filename,candidate_file_size_bytes,candidate_stable_mtime_ns,candidate_chronology_kind,candidate_chronology_value,"
            "logical_fingerprint_sha256,run_state,started_at_utc,staged_at_utc,observed_row_count,valid_identity_count,revision"
            ") VALUES (?,?,'manual',?,'HEADERS_V1','VOCAB_V1','PARSER_V1','mismatched.xlsx',100,1,?,200,?,'waiting_review',0,1,1,1,1)",
            (run_id, run_source_family, source_profile_id, chronology_kind, "1" * 64),
        )
        uow.connection.execute(
            "INSERT INTO source_observations("
            "source_observation_id,import_run_id,source_family,entity_kind,identity_state,canonical_primary_id,canonical_parent_rfc_no,"
            "row_ordinal,sheet_ordinal,row_logical_sha256,source_row_chronology_utc,presence_state,recorded_at_utc"
            ") VALUES (?,?,?,?, 'valid',?,?,1,1,?,100,'observed_valid_identity',1)",
            (
                observation_id,
                run_id,
                observation_source_family,
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
            ") VALUES (?,? ,?,'active','usable',?,?,?,NULL,?,?)",
            (
                field_id,
                observation_id,
                field_key,
                value_kind,
                normalized_text,
                normalized_text,
                vocabulary_id,
                "3" * 64,
            ),
        )
    return run_id, observation_id, field_id


def test_rfc_evidence_rejects_observation_whose_import_run_has_another_source_family(initialized_database) -> None:
    factory = _factory(initialized_database)
    rfc = RfcService(factory).create_or_adopt_identity(
        command_id=new_uuid4(),
        rfc_no="NC20260908003001",
        creation_context="manual",
    )
    _run_id, _observation_id, field_id = _seed_mismatched_field(
        factory,
        run_source_family="wfm_service_provider",
        observation_source_family="rfc_enhanced",
        source_profile_id="WFM_SERVICE_PROVIDER_V1",
        entity_kind="rfc",
        canonical_primary_id="NC20260908003001",
        canonical_parent_rfc_no=None,
        field_key="summary",
        value_kind="text",
        normalized_text="Must not become RFC authority",
    )
    delta = RfcAcceptedFieldDelta(
        field_key="summary",
        value_kind="text",
        value="Must not become RFC authority",
        evidence_id=field_id,
    )

    with UnitOfWork(factory) as uow:
        provider = TicketImportRfcSourceEvidenceProvider()
        assert provider.validate_accepted_delta(uow, rfc.rfc_id, delta, field_id) == "INVALID"
        assert provider.has_accepted_source_provenance(uow, rfc.rfc_id) == "NO"


def test_sr_evidence_rejects_observation_whose_import_run_has_another_source_family(initialized_database) -> None:
    factory = _factory(initialized_database)
    sr = ServiceRequestService(factory).create_manual_service_request(
        command_id=new_uuid4(),
        official_sr_no="33445566",
    )
    _run_id, _observation_id, field_id = _seed_mismatched_field(
        factory,
        run_source_family="rfc_enhanced",
        observation_source_family="advanced_search_sr",
        source_profile_id="RFC_ENHANCED_V1",
        entity_kind="service_request",
        canonical_primary_id="33445566",
        canonical_parent_rfc_no=None,
        field_key="problem_summary",
        value_kind="text",
        normalized_text="Must not become SR authority",
    )

    with UnitOfWork(factory) as uow:
        provider = TicketImportSrSourceEvidenceProvider()
        accepted = {
            "value_state": "usable",
            "value_kind": "text",
            "value": "Must not become SR authority",
            "source_chronology_utc": 100,
            "precedence_basis": "source_chronology",
        }
        assert provider.validate_published_field(
            uow,
            sr.service_request_id,
            "problem_summary",
            field_id,
            accepted,
        ) == "INVALID"
        assert provider.has_accepted_source_provenance(uow, sr.service_request_id) == "NO"


@pytest.mark.parametrize(
    ("source_family", "profile_id", "entity_kind", "primary_id", "parent_rfc_no", "field_key"),
    [
        ("rfc_enhanced", "RFC_ENHANCED_V0", "rfc", "NC20260908003002", None, "summary"),
        (
            "wfm_service_provider",
            "WFM_SERVICE_PROVIDER_V0",
            "wfm",
            "TK20260908003002",
            "NC20260908003002",
            "rfc_status",
        ),
    ],
)
def test_rfc_evidence_rejects_wrong_source_profile(
    initialized_database,
    source_family: str,
    profile_id: str,
    entity_kind: str,
    primary_id: str,
    parent_rfc_no: str | None,
    field_key: str,
) -> None:
    factory = _factory(initialized_database)
    rfc = RfcService(factory).create_or_adopt_identity(
        command_id=new_uuid4(),
        rfc_no="NC20260908003002",
        creation_context="manual",
    )
    _run_id, _observation_id, field_id = _seed_mismatched_field(
        factory,
        run_source_family=source_family,
        observation_source_family=source_family,
        source_profile_id=profile_id,
        entity_kind=entity_kind,
        canonical_primary_id=primary_id,
        canonical_parent_rfc_no=parent_rfc_no,
        field_key=field_key,
        value_kind="controlled" if field_key == "rfc_status" else "text",
        normalized_text="Implement" if field_key == "rfc_status" else "Wrong profile",
        vocabulary_id="RFC_STATUS_V1" if field_key == "rfc_status" else None,
    )
    if field_key == "rfc_status":
        delta = RfcAcceptedFieldDelta(
            field_key="status",
            value_kind="controlled",
            value="Implement",
            evidence_id=field_id,
            status_class="implement_eligible",
            status_authority="wfm_provisional",
        )
    else:
        delta = RfcAcceptedFieldDelta(
            field_key="summary",
            value_kind="text",
            value="Wrong profile",
            evidence_id=field_id,
        )

    with UnitOfWork(factory) as uow:
        provider = TicketImportRfcSourceEvidenceProvider()
        assert provider.validate_accepted_delta(uow, rfc.rfc_id, delta, field_id) == "INVALID"
        assert provider.has_accepted_source_provenance(uow, rfc.rfc_id) == "NO"


def test_rfc_status_evidence_rejects_wrong_vocabulary_and_delta_build(initialized_database) -> None:
    factory = _factory(initialized_database)
    rfc = RfcService(factory).create_or_adopt_identity(
        command_id=new_uuid4(),
        rfc_no="NC20260908003003",
        creation_context="manual",
    )
    run_id, observation_id, field_id = _seed_mismatched_field(
        factory,
        run_source_family="rfc_enhanced",
        observation_source_family="rfc_enhanced",
        source_profile_id="RFC_ENHANCED_V1",
        entity_kind="rfc",
        canonical_primary_id="NC20260908003003",
        canonical_parent_rfc_no=None,
        field_key="status",
        value_kind="controlled",
        normalized_text="Implement",
        vocabulary_id="RFC_STATUS_V0",
    )
    delta = RfcAcceptedFieldDelta(
        field_key="status",
        value_kind="controlled",
        value="Implement",
        evidence_id=field_id,
        status_class="implement_eligible",
        status_authority="enhanced_rfc",
    )

    with UnitOfWork(factory) as uow:
        provider = TicketImportRfcSourceEvidenceProvider()
        assert provider.validate_accepted_delta(uow, rfc.rfc_id, delta, field_id) == "INVALID"
        with pytest.raises(SomaError) as excinfo:
            provider.build_source_projection_delta(
                uow.connection,
                rfc_id=rfc.rfc_id,
                expected_import_run_id=run_id,
                expected_source_observation_id=observation_id,
                source_observation_field_id=field_id,
                expected_field_key="status",
            )
        assert excinfo.value.code == "IMPORT_PROPOSAL_STALE"


def test_sr_evidence_rejects_wrong_source_profile(initialized_database) -> None:
    factory = _factory(initialized_database)
    sr = ServiceRequestService(factory).create_manual_service_request(
        command_id=new_uuid4(),
        official_sr_no="33445567",
    )
    _run_id, _observation_id, field_id = _seed_mismatched_field(
        factory,
        run_source_family="advanced_search_sr",
        observation_source_family="advanced_search_sr",
        source_profile_id="ADVANCED_SEARCH_SR_V0",
        entity_kind="service_request",
        canonical_primary_id="33445567",
        canonical_parent_rfc_no=None,
        field_key="problem_summary",
        value_kind="text",
        normalized_text="Wrong profile",
    )

    with UnitOfWork(factory) as uow:
        provider = TicketImportSrSourceEvidenceProvider()
        accepted = {
            "value_state": "usable",
            "value_kind": "text",
            "value": "Wrong profile",
            "source_chronology_utc": 100,
            "precedence_basis": "source_chronology",
        }
        assert provider.validate_published_field(
            uow,
            sr.service_request_id,
            "problem_summary",
            field_id,
            accepted,
        ) == "INVALID"
        assert provider.has_accepted_source_provenance(uow, sr.service_request_id) == "NO"


def test_sr_controlled_evidence_rejects_wrong_vocabulary_and_delta_build(initialized_database) -> None:
    factory = _factory(initialized_database)
    sr = ServiceRequestService(factory).create_manual_service_request(
        command_id=new_uuid4(),
        official_sr_no="33445568",
    )
    run_id, observation_id, field_id = _seed_mismatched_field(
        factory,
        run_source_family="advanced_search_sr",
        observation_source_family="advanced_search_sr",
        source_profile_id="ADVANCED_SEARCH_SR_V1",
        entity_kind="service_request",
        canonical_primary_id="33445568",
        canonical_parent_rfc_no=None,
        field_key="status",
        value_kind="controlled",
        normalized_text="Closed",
        vocabulary_id="ADVANCED_SEARCH_STATUS_V0",
    )

    with UnitOfWork(factory) as uow:
        provider = TicketImportSrSourceEvidenceProvider()
        accepted = {
            "value_state": "usable",
            "value_kind": "controlled",
            "value": "Closed",
            "source_chronology_utc": 100,
            "precedence_basis": "source_chronology",
        }
        assert provider.validate_published_field(
            uow,
            sr.service_request_id,
            "status",
            field_id,
            accepted,
        ) == "INVALID"
        with pytest.raises(SomaError) as excinfo:
            provider.build_source_projection_delta(
                uow.connection,
                service_request_id=sr.service_request_id,
                expected_import_run_id=run_id,
                expected_source_observation_id=observation_id,
                source_observation_field_id=field_id,
                field_key="status",
                change_kind="set",
                change_value_kind="controlled",
                after_text="Closed",
                after_integer=None,
            )
        assert excinfo.value.code == "IMPORT_PROPOSAL_STALE"
