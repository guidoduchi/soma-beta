from __future__ import annotations

from soma.foundation.identifiers import new_uuid4
from soma.foundation.persistence.uow import UnitOfWork
from soma.ticket_import.providers.rfc_source_evidence import TicketImportRfcSourceEvidenceProvider
from soma.tickets.rfc_source_projection import RfcAcceptedFieldDelta
from soma.tickets.rfcs import RfcService


def _factory(initialized_database):
    database_path, factory_for_path = initialized_database
    return factory_for_path(database_path)


def _rfc(factory, rfc_no: str):
    return RfcService(factory).create_or_adopt_identity(
        command_id=new_uuid4(),
        rfc_no=rfc_no,
        creation_context="manual",
    )


def _seed_field(
    factory,
    *,
    source_family: str,
    canonical_primary_id: str,
    field_key: str,
    value_kind: str,
    normalized_text: str | None = None,
    integer_value: int | None = None,
    canonical_parent_rfc_no: str | None = None,
    vocabulary_id: str | None = None,
    chronology: int | None = 100,
):
    run_id = new_uuid4()
    observation_id = new_uuid4()
    field_id = new_uuid4()
    entity_kind = "rfc" if source_family == "rfc_enhanced" else "wfm"
    profile_id = "RFC_ENHANCED_V1" if source_family == "rfc_enhanced" else "WFM_SERVICE_PROVIDER_V1"
    chronology_kind = "filesystem_mtime_ns" if source_family == "rfc_enhanced" else "embedded_filename_timestamp_utc"
    filename = (
        "Enhanced Excel Data Export.xlsx"
        if source_family == "rfc_enhanced"
        else "Service Provider Plan Creation20260908010000.xlsx"
    )
    source_text = str(normalized_text if normalized_text is not None else integer_value)
    with UnitOfWork(factory) as uow:
        uow.connection.execute(
            "INSERT INTO import_runs("
            "import_run_id,source_family,invocation_kind,source_profile_id,header_registry_id,vocabulary_registry_id,parser_profile_id,"
            "candidate_filename,candidate_file_size_bytes,candidate_stable_mtime_ns,candidate_chronology_kind,candidate_chronology_value,"
            "logical_fingerprint_sha256,run_state,started_at_utc,staged_at_utc,observed_row_count,valid_identity_count,revision"
            ") VALUES (?,?,'manual',?,'HEADERS_V1','VOCAB_V1','PARSER_V1',?,100,1,?,200,?,'waiting_review',0,1,1,1,1)",
            (run_id, source_family, profile_id, filename, chronology_kind, "1" * 64),
        )
        uow.connection.execute(
            "INSERT INTO source_observations("
            "source_observation_id,import_run_id,source_family,entity_kind,identity_state,canonical_primary_id,canonical_parent_rfc_no,"
            "row_ordinal,sheet_ordinal,row_logical_sha256,source_row_chronology_utc,presence_state,recorded_at_utc"
            ") VALUES (?,?,?,?, 'valid',?,?,1,1,?,?, 'observed_valid_identity',1)",
            (
                observation_id,
                run_id,
                source_family,
                entity_kind,
                canonical_primary_id,
                canonical_parent_rfc_no,
                "2" * 64,
                chronology,
            ),
        )
        uow.connection.execute(
            "INSERT INTO source_observation_fields("
            "source_observation_field_id,source_observation_id,field_key,field_class,value_state,value_kind,source_text,"
            "normalized_text,integer_value,vocabulary_id,field_logical_sha256"
            ") VALUES (?, ?, ?, 'active', 'usable', ?, ?, ?, ?, ?, ?)",
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
    return run_id, observation_id, field_id


def test_enhanced_rfc_field_builds_and_validates_exact_delta(initialized_database) -> None:
    factory = _factory(initialized_database)
    rfc = _rfc(factory, "NC20260908001001")
    run_id, observation_id, field_id = _seed_field(
        factory,
        source_family="rfc_enhanced",
        canonical_primary_id="NC20260908001001",
        field_key="summary",
        value_kind="text",
        normalized_text="Replace access switch",
    )
    provider = TicketImportRfcSourceEvidenceProvider()

    with UnitOfWork(factory) as uow:
        delta = provider.build_source_projection_delta(
            uow.connection,
            rfc_id=rfc.rfc_id,
            expected_import_run_id=run_id,
            expected_source_observation_id=observation_id,
            source_observation_field_id=field_id,
            expected_field_key="summary",
        )
        assert delta == RfcAcceptedFieldDelta(
            field_key="summary",
            value_kind="text",
            value="Replace access switch",
            evidence_id=field_id,
        )
        assert provider.validate_accepted_delta(uow, rfc.rfc_id, delta, field_id) == "VALID"
        assert provider.has_accepted_source_provenance(uow, rfc.rfc_id) == "YES"
        assert len(provider.source_freshness_token(uow, rfc.rfc_id)) == 64


def test_enhanced_rfc_field_cannot_be_substituted_across_rfc_identity(initialized_database) -> None:
    factory = _factory(initialized_database)
    target = _rfc(factory, "NC20260908001002")
    _other = _rfc(factory, "NC20260908001003")
    _run_id, _observation_id, field_id = _seed_field(
        factory,
        source_family="rfc_enhanced",
        canonical_primary_id="NC20260908001003",
        field_key="summary",
        value_kind="text",
        normalized_text="Other RFC summary",
    )
    provider = TicketImportRfcSourceEvidenceProvider()
    delta = RfcAcceptedFieldDelta(
        field_key="summary",
        value_kind="text",
        value="Other RFC summary",
        evidence_id=field_id,
    )

    with UnitOfWork(factory) as uow:
        assert provider.validate_accepted_delta(uow, target.rfc_id, delta, field_id) == "INVALID"


def test_enhanced_status_requires_exact_vocabulary_class_and_authority(initialized_database) -> None:
    factory = _factory(initialized_database)
    rfc = _rfc(factory, "NC20260908001004")
    run_id, observation_id, field_id = _seed_field(
        factory,
        source_family="rfc_enhanced",
        canonical_primary_id="NC20260908001004",
        field_key="status",
        value_kind="controlled",
        normalized_text="Closed",
        vocabulary_id="RFC_STATUS_V1",
    )
    provider = TicketImportRfcSourceEvidenceProvider()

    with UnitOfWork(factory) as uow:
        delta = provider.build_source_projection_delta(
            uow.connection,
            rfc_id=rfc.rfc_id,
            expected_import_run_id=run_id,
            expected_source_observation_id=observation_id,
            source_observation_field_id=field_id,
            expected_field_key="status",
        )
        assert delta.status_class == "terminal_closed"
        assert delta.status_authority == "enhanced_rfc"
        assert provider.validate_accepted_delta(uow, rfc.rfc_id, delta, field_id) == "VALID"
        wrong_class = RfcAcceptedFieldDelta(
            field_key="status",
            value_kind="controlled",
            value="Closed",
            evidence_id=field_id,
            status_class="terminal_cancelled",
            status_authority="enhanced_rfc",
        )
        wrong_authority = RfcAcceptedFieldDelta(
            field_key="status",
            value_kind="controlled",
            value="Closed",
            evidence_id=field_id,
            status_class="terminal_closed",
            status_authority="wfm_provisional",
        )
        assert provider.validate_accepted_delta(uow, rfc.rfc_id, wrong_class, field_id) == "INVALID"
        assert provider.validate_accepted_delta(uow, rfc.rfc_id, wrong_authority, field_id) == "INVALID"


def test_unknown_enhanced_status_never_acquires_current_lifecycle_authority(initialized_database) -> None:
    factory = _factory(initialized_database)
    rfc = _rfc(factory, "NC20260908001005")
    run_id, observation_id, field_id = _seed_field(
        factory,
        source_family="rfc_enhanced",
        canonical_primary_id="NC20260908001005",
        field_key="status",
        value_kind="controlled",
        normalized_text="Waiting Customer",
        vocabulary_id="RFC_STATUS_V1",
    )
    provider = TicketImportRfcSourceEvidenceProvider()
    candidate = RfcAcceptedFieldDelta(
        field_key="status",
        value_kind="controlled",
        value="Waiting Customer",
        evidence_id=field_id,
        status_class="implement_eligible",
        status_authority="enhanced_rfc",
    )

    with UnitOfWork(factory) as uow:
        assert provider.validate_accepted_delta(uow, rfc.rfc_id, candidate, field_id) == "INVALID"
        try:
            provider.build_source_projection_delta(
                uow.connection,
                rfc_id=rfc.rfc_id,
                expected_import_run_id=run_id,
                expected_source_observation_id=observation_id,
                source_observation_field_id=field_id,
                expected_field_key="status",
            )
        except Exception as exc:
            assert getattr(exc, "code", None) == "IMPORT_PROPOSAL_STALE"
        else:
            raise AssertionError("unknown RFC status unexpectedly acquired current lifecycle authority")


def test_wfm_rfc_status_is_provisional_and_only_status_can_cross_into_rfc_projection(initialized_database) -> None:
    factory = _factory(initialized_database)
    rfc = _rfc(factory, "NC20260908001006")
    run_id, observation_id, status_field_id = _seed_field(
        factory,
        source_family="wfm_service_provider",
        canonical_primary_id="TK20260908002001",
        canonical_parent_rfc_no="NC20260908001006",
        field_key="rfc_status",
        value_kind="controlled",
        normalized_text="Implement",
        vocabulary_id="RFC_STATUS_V1",
    )
    _run2, _obs2, task_name_field_id = _seed_field(
        factory,
        source_family="wfm_service_provider",
        canonical_primary_id="TK20260908002002",
        canonical_parent_rfc_no="NC20260908001006",
        field_key="task_name",
        value_kind="text",
        normalized_text="Provider task name",
    )
    provider = TicketImportRfcSourceEvidenceProvider()

    with UnitOfWork(factory) as uow:
        delta = provider.build_source_projection_delta(
            uow.connection,
            rfc_id=rfc.rfc_id,
            expected_import_run_id=run_id,
            expected_source_observation_id=observation_id,
            source_observation_field_id=status_field_id,
            expected_field_key="status",
        )
        assert delta.status_class == "implement_eligible"
        assert delta.status_authority == "wfm_provisional"
        assert provider.validate_accepted_delta(uow, rfc.rfc_id, delta, status_field_id) == "VALID"
        smuggled = RfcAcceptedFieldDelta(
            field_key="summary",
            value_kind="text",
            value="Provider task name",
            evidence_id=task_name_field_id,
        )
        assert provider.validate_accepted_delta(uow, rfc.rfc_id, smuggled, task_name_field_id) == "INVALID"


def test_wfm_rfc_status_must_bind_exact_parent_rfc(initialized_database) -> None:
    factory = _factory(initialized_database)
    target = _rfc(factory, "NC20260908001007")
    _other = _rfc(factory, "NC20260908001008")
    _run_id, _observation_id, field_id = _seed_field(
        factory,
        source_family="wfm_service_provider",
        canonical_primary_id="TK20260908002003",
        canonical_parent_rfc_no="NC20260908001008",
        field_key="rfc_status",
        value_kind="controlled",
        normalized_text="Implement",
        vocabulary_id="RFC_STATUS_V1",
    )
    provider = TicketImportRfcSourceEvidenceProvider()
    delta = RfcAcceptedFieldDelta(
        field_key="status",
        value_kind="controlled",
        value="Implement",
        evidence_id=field_id,
        status_class="implement_eligible",
        status_authority="wfm_provisional",
    )

    with UnitOfWork(factory) as uow:
        assert provider.validate_accepted_delta(uow, target.rfc_id, delta, field_id) == "INVALID"
