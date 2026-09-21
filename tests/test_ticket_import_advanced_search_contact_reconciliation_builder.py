from __future__ import annotations

from soma.foundation.identifiers import new_uuid4
from soma.foundation.persistence.uow import ReadSnapshot, UnitOfWork
from soma.reference.application.contact_service import ContactReferenceService
from soma.reference.application.customer_service import CustomerReferenceService
from soma.ticket_import.reconciliation.advanced_search_contact import (
    build_advanced_search_sr_contact_reconciliation_proposals,
)
from soma.tickets.service_request_import_reader import ServiceRequestImportReader
from soma.tickets.service_requests import ServiceRequestService
from soma.tickets.sr_references import ServiceRequestReferenceService


def _factory(initialized_database):
    database_path, factory_for_path = initialized_database
    return factory_for_path(database_path)


class _NoopClassificationParticipant:
    def preview_customer_change(self, reader, sr_id: str, new_customer_org_id: str | None):
        return {"impact": "none", "service_request_id": sr_id, "customer_org_id": new_customer_org_id}

    def apply_customer_change(self, uow, sr_id: str, new_customer_org_id: str | None, command_context):
        assert uow.connection.in_transaction
        return ()


def _customer(factory, name: str):
    return CustomerReferenceService(factory).create_customer_organization(
        command_id=new_uuid4(),
        name=name,
    )


def _contact(factory, name: str, *, customer_org_id: str | None = None):
    return ContactReferenceService(factory).create_contact(
        command_id=new_uuid4(),
        name=name,
        initial_customer_org_id=customer_org_id,
    )


def _official_sr(factory, sr_no: str):
    return ServiceRequestService(factory).create_manual_service_request(
        command_id=new_uuid4(),
        official_sr_no=sr_no,
    )


def _sr_revision(factory, service_request_id: str) -> int:
    with ReadSnapshot(factory) as snapshot:
        row = snapshot.connection.execute(
            "SELECT revision FROM service_requests WHERE service_request_id=?",
            (service_request_id,),
        ).fetchone()
        assert row is not None
        return int(row[0])


def _set_customer(factory, *, service_request_id: str, customer_org_id: str) -> None:
    ServiceRequestReferenceService(factory, _NoopClassificationParticipant()).set_customer(
        command_id=new_uuid4(),
        service_request_id=service_request_id,
        base_revision=_sr_revision(factory, service_request_id),
        customer_org_id=customer_org_id,
        reason_category="test_contact_scope",
    )


def _set_customer_contact(factory, *, service_request_id: str, contact_id: str) -> None:
    ServiceRequestReferenceService(factory, _NoopClassificationParticipant()).set_contact_reference(
        command_id=new_uuid4(),
        service_request_id=service_request_id,
        base_revision=_sr_revision(factory, service_request_id),
        reference_role="customer_contact",
        contact_id=contact_id,
        supporting_sr_source_field_observation_id=None,
        reason_category="test_customer_contact",
    )


def _seed_validating_run(factory) -> str:
    run_id = new_uuid4()
    with UnitOfWork(factory) as uow:
        uow.connection.execute(
            "INSERT INTO import_runs("
            "import_run_id,source_family,invocation_kind,source_profile_id,header_registry_id,vocabulary_registry_id,parser_profile_id,"
            "candidate_filename,candidate_file_size_bytes,candidate_stable_mtime_ns,candidate_chronology_kind,candidate_chronology_value,"
            "logical_fingerprint_sha256,run_state,started_at_utc,staged_at_utc,observed_row_count,valid_identity_count,"
            "proposal_count,pending_proposal_count,revision"
            ") VALUES (?, 'advanced_search_sr','manual','ADVANCED_SEARCH_SR_V1','ADVANCED_SEARCH_HEADERS_V1',"
            "'ADVANCED_SEARCH_VOCAB_V1','ADVANCED_SEARCH_PARSER_V1','Advanced Search(Service Request)20260913010000.xlsx',"
            "100,1,'embedded_filename_timestamp_utc',400,?,'validating',0,1,0,0,0,0,1)",
            (run_id, "1" * 64),
        )
    return run_id


def _seed_observation(
    factory,
    *,
    run_id: str,
    sr_no: str,
    row_hash: str,
    label: str | None,
    value_state: str = "usable",
) -> dict[str, str]:
    observation_id = new_uuid4()
    field_id = new_uuid4()
    normalized_text = label if value_state == "usable" else None
    source_text = "" if label is None else label
    with UnitOfWork(factory) as uow:
        uow.connection.execute(
            "INSERT INTO source_observations(source_observation_id,import_run_id,source_family,entity_kind,identity_state,"
            "canonical_primary_id,canonical_parent_rfc_no,row_ordinal,sheet_ordinal,row_logical_sha256,source_row_chronology_utc,"
            "presence_state,recorded_at_utc) VALUES (?,?,'advanced_search_sr','service_request','valid',?,NULL,1,1,?,100,"
            "'observed_valid_identity',1)",
            (observation_id, run_id, sr_no, row_hash),
        )
        uow.connection.execute(
            "INSERT INTO source_observation_fields(source_observation_field_id,source_observation_id,field_key,field_class,"
            "value_state,value_kind,source_text,normalized_text,integer_value,vocabulary_id,field_logical_sha256) "
            "VALUES (?,?,'customer_contact_label','active',?,'text',?,?,NULL,NULL,?)",
            (field_id, observation_id, value_state, source_text, normalized_text, "2" * 64),
        )
    return {"observation_id": observation_id, "field_id": field_id}


def _build(factory, *, run_id: str, observation_id: str):
    with ReadSnapshot(factory) as snapshot:
        return build_advanced_search_sr_contact_reconciliation_proposals(
            snapshot.connection,
            import_run_id=run_id,
            source_observation_id=observation_id,
        )


def test_customer_contact_builder_emits_exact_scoped_high_risk_proposal(initialized_database) -> None:
    factory = _factory(initialized_database)
    customer = _customer(factory, "Scoped Customer")
    target = _contact(factory, "Alice Contact", customer_org_id=customer.customer_org_id)
    sr = _official_sr(factory, "44000200")
    _set_customer(factory, service_request_id=sr.service_request_id, customer_org_id=customer.customer_org_id)
    run_id = _seed_validating_run(factory)
    seeded = _seed_observation(
        factory,
        run_id=run_id,
        sr_no="44000200",
        row_hash="a" * 64,
        label="Alice Contact",
    )

    result = _build(factory, run_id=run_id, observation_id=seeded["observation_id"])
    assert result.scope_status == "unique"
    assert result.resolution_state == "unique_candidate"
    assert result.matcher_scope == customer.customer_org_id
    assert result.matcher_explanation == "EXACT_SCOPED_REFERENCE_MATCH"
    assert result.service_request_id == sr.service_request_id
    assert len(result.proposals) == 1
    proposal = result.proposals[0]
    assert proposal.proposal_kind == "sr_contact_reconciliation"
    assert proposal.risk_class == "high"
    assert proposal.target_internal_id == sr.service_request_id
    assert proposal.target_business_id == "44000200"
    assert len(proposal.changes) == 1
    change = proposal.changes[0]
    assert change.ordinal == 0
    assert change.field_key == "contact_id"
    assert change.change_kind == "set"
    assert change.value_kind == "identity"
    assert change.before_text is None
    assert change.after_text == target.contact_id
    assert change.before_integer is None
    assert change.after_integer is None
    assert change.source_observation_field_id == seeded["field_id"]
    with ReadSnapshot(factory) as snapshot:
        expected = ServiceRequestImportReader.contact_reconciliation_base_token(
            snapshot.connection,
            sr.service_request_id,
            "customer_contact",
            target.contact_id,
            seeded["field_id"],
        )
    assert proposal.base_state_token_sha256 == expected


def test_customer_contact_builder_uses_affiliation_scope_and_ignores_same_name_elsewhere(initialized_database) -> None:
    factory = _factory(initialized_database)
    first_customer = _customer(factory, "First Customer")
    second_customer = _customer(factory, "Second Customer")
    target = _contact(factory, "Shared Name", customer_org_id=first_customer.customer_org_id)
    other = _contact(factory, "Shared Name", customer_org_id=second_customer.customer_org_id)
    assert target.contact_id != other.contact_id
    sr = _official_sr(factory, "44000201")
    _set_customer(factory, service_request_id=sr.service_request_id, customer_org_id=first_customer.customer_org_id)
    run_id = _seed_validating_run(factory)
    seeded = _seed_observation(
        factory,
        run_id=run_id,
        sr_no="44000201",
        row_hash="b" * 64,
        label="Shared Name",
    )

    result = _build(factory, run_id=run_id, observation_id=seeded["observation_id"])
    assert result.resolution_state == "unique_candidate"
    assert result.proposals[0].changes[0].after_text == target.contact_id


def test_customer_contact_builder_keeps_scoped_ambiguity_unresolved(initialized_database) -> None:
    factory = _factory(initialized_database)
    customer = _customer(factory, "Ambiguous Customer")
    first = _contact(factory, "Duplicate Contact", customer_org_id=customer.customer_org_id)
    second = _contact(factory, "Duplicate Contact", customer_org_id=customer.customer_org_id)
    assert first.contact_id != second.contact_id
    sr = _official_sr(factory, "44000202")
    _set_customer(factory, service_request_id=sr.service_request_id, customer_org_id=customer.customer_org_id)
    run_id = _seed_validating_run(factory)
    seeded = _seed_observation(
        factory,
        run_id=run_id,
        sr_no="44000202",
        row_hash="c" * 64,
        label="Duplicate Contact",
    )

    result = _build(factory, run_id=run_id, observation_id=seeded["observation_id"])
    assert result.resolution_state == "ambiguous"
    assert result.matcher_scope == customer.customer_org_id
    assert result.proposals == ()


def test_customer_contact_builder_supports_governed_unbound_scope(initialized_database) -> None:
    factory = _factory(initialized_database)
    affiliated_customer = _customer(factory, "Other Customer")
    target = _contact(factory, "Unbound Contact")
    affiliated = _contact(factory, "Unbound Contact", customer_org_id=affiliated_customer.customer_org_id)
    assert target.contact_id != affiliated.contact_id
    sr = _official_sr(factory, "44000203")
    run_id = _seed_validating_run(factory)
    seeded = _seed_observation(
        factory,
        run_id=run_id,
        sr_no="44000203",
        row_hash="d" * 64,
        label="Unbound Contact",
    )

    result = _build(factory, run_id=run_id, observation_id=seeded["observation_id"])
    assert result.resolution_state == "unique_candidate"
    assert result.matcher_scope == "UNBOUND"
    assert result.proposals[0].changes[0].after_text == target.contact_id


def test_customer_contact_builder_suppresses_already_current_reference(initialized_database) -> None:
    factory = _factory(initialized_database)
    customer = _customer(factory, "Current Customer")
    target = _contact(factory, "Current Contact", customer_org_id=customer.customer_org_id)
    sr = _official_sr(factory, "44000204")
    _set_customer(factory, service_request_id=sr.service_request_id, customer_org_id=customer.customer_org_id)
    _set_customer_contact(factory, service_request_id=sr.service_request_id, contact_id=target.contact_id)
    run_id = _seed_validating_run(factory)
    seeded = _seed_observation(
        factory,
        run_id=run_id,
        sr_no="44000204",
        row_hash="e" * 64,
        label="Current Contact",
    )

    result = _build(factory, run_id=run_id, observation_id=seeded["observation_id"])
    assert result.resolution_state == "already_current"
    assert result.proposals == ()


def test_customer_contact_builder_never_creates_contact_and_ignores_unusable_label(initialized_database) -> None:
    factory = _factory(initialized_database)
    _official_sr(factory, "44000205")
    with ReadSnapshot(factory) as snapshot:
        before_count = int(snapshot.connection.execute("SELECT COUNT(*) FROM contacts").fetchone()[0])
    run_id = _seed_validating_run(factory)
    seeded = _seed_observation(
        factory,
        run_id=run_id,
        sr_no="44000205",
        row_hash="f" * 64,
        label="Does Not Exist",
    )
    unresolved = _build(factory, run_id=run_id, observation_id=seeded["observation_id"])
    assert unresolved.resolution_state == "unresolved"
    assert unresolved.proposals == ()
    with ReadSnapshot(factory) as snapshot:
        assert int(snapshot.connection.execute("SELECT COUNT(*) FROM contacts").fetchone()[0]) == before_count

    _official_sr(factory, "44000206")
    run2 = _seed_validating_run(factory)
    blank = _seed_observation(
        factory,
        run_id=run2,
        sr_no="44000206",
        row_hash="0" * 64,
        label=None,
        value_state="blank",
    )
    ignored = _build(factory, run_id=run2, observation_id=blank["observation_id"])
    assert ignored.resolution_state == "customer_contact_unusable"
    assert ignored.proposals == ()
