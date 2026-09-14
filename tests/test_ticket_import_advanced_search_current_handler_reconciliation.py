from __future__ import annotations

import pytest

from soma.foundation.errors import SomaError
from soma.foundation.identifiers import new_uuid4
from soma.foundation.persistence.uow import ReadSnapshot, UnitOfWork
from soma.reference.application.contact_service import ContactReferenceService
from soma.ticket_import.commands.decide_proposal import ProposalDecisionService
from soma.ticket_import.reconciliation.advanced_search_current_handler import (
    build_advanced_search_sr_current_handler_reconciliation_proposals,
)
from soma.tickets.import_mutations import ServiceRequestImportMutationService
from soma.tickets.service_request_import_reader import ServiceRequestImportReader
from soma.tickets.service_requests import ServiceRequestService


def _factory(initialized_database):
    database_path, factory_for_path = initialized_database
    return factory_for_path(database_path)


def _official_sr(factory, sr_no: str):
    return ServiceRequestService(factory).create_manual_service_request(
        command_id=new_uuid4(),
        official_sr_no=sr_no,
    )


def _contact(factory, name: str):
    return ContactReferenceService(factory).create_contact(
        command_id=new_uuid4(),
        name=name,
    )


def _source_base_token(factory, service_request_id: str) -> str:
    with ReadSnapshot(factory) as snapshot:
        return ServiceRequestImportMutationService.source_field_set_base_token(
            snapshot.connection,
            service_request_id,
            ("current_handler_label",),
        )


def _contact_base_token(
    factory,
    *,
    service_request_id: str,
    target_contact_id: str,
    source_observation_field_id: str,
) -> str:
    with ReadSnapshot(factory) as snapshot:
        return ServiceRequestImportMutationService.contact_reconciliation_base_token(
            snapshot.connection,
            service_request_id,
            "current_handler_reference",
            target_contact_id,
            source_observation_field_id,
        )


def _insert_run_handler_field(
    factory,
    *,
    sr_no: str,
    label: str,
    chronology: int,
    run_state: str,
    row_hash: str,
    field_hash: str,
    proposal_count: int = 0,
):
    run_id = new_uuid4()
    observation_id = new_uuid4()
    field_id = new_uuid4()
    pending = proposal_count if run_state == "waiting_review" else 0
    with UnitOfWork(factory) as uow:
        uow.connection.execute(
            "INSERT INTO import_runs("
            "import_run_id,source_family,invocation_kind,source_profile_id,header_registry_id,vocabulary_registry_id,parser_profile_id,"
            "candidate_filename,candidate_file_size_bytes,candidate_stable_mtime_ns,candidate_chronology_kind,candidate_chronology_value,"
            "logical_fingerprint_sha256,run_state,started_at_utc,staged_at_utc,observed_row_count,valid_identity_count,"
            "proposal_count,pending_proposal_count,revision"
            ") VALUES (?, 'advanced_search_sr','manual','ADVANCED_SEARCH_SR_V1','ADVANCED_SEARCH_HEADERS_V1',"
            "'ADVANCED_SEARCH_VOCAB_V1','ADVANCED_SEARCH_PARSER_V1','Advanced Search(Service Request)20260913020000.xlsx',"
            "100,1,'embedded_filename_timestamp_utc',?,? ,?,0,1,1,1,?,?,1)",
            (run_id, chronology, "1" * 64, run_state, proposal_count, pending),
        )
        uow.connection.execute(
            "INSERT INTO source_observations(source_observation_id,import_run_id,source_family,entity_kind,identity_state,"
            "canonical_primary_id,canonical_parent_rfc_no,row_ordinal,sheet_ordinal,row_logical_sha256,source_row_chronology_utc,"
            "presence_state,recorded_at_utc) VALUES (?,?,'advanced_search_sr','service_request','valid',?,NULL,1,1,?,?,"
            "'observed_valid_identity',1)",
            (observation_id, run_id, sr_no, row_hash, chronology),
        )
        uow.connection.execute(
            "INSERT INTO source_observation_fields(source_observation_field_id,source_observation_id,field_key,field_class,"
            "value_state,value_kind,source_text,normalized_text,integer_value,vocabulary_id,field_logical_sha256) "
            "VALUES (?,?,'current_handler_label','active','usable','text',?,?,NULL,NULL,?)",
            (field_id, observation_id, label, label, field_hash),
        )
    return {
        "run_id": run_id,
        "source_observation_id": observation_id,
        "source_observation_field_id": field_id,
    }


def _accept_handler_source(
    factory,
    *,
    service_request_id: str,
    sr_no: str,
    label: str,
    chronology: int,
    row_hash: str,
    field_hash: str,
):
    base_token = _source_base_token(factory, service_request_id)
    seeded = _insert_run_handler_field(
        factory,
        sr_no=sr_no,
        label=label,
        chronology=chronology,
        run_state="waiting_review",
        row_hash=row_hash,
        field_hash=field_hash,
        proposal_count=1,
    )
    proposal_id = new_uuid4()
    fingerprint = "4" * 64
    with UnitOfWork(factory) as uow:
        uow.connection.execute(
            "INSERT INTO reconciliation_proposals(reconciliation_proposal_id,import_run_id,evidence_mode,source_observation_id,"
            "prior_source_observation_id,proposal_kind,target_kind,target_internal_id,target_business_id,risk_class,"
            "base_state_token_sha256,proposal_fingerprint_sha256,proposal_state,created_at_utc,revision,decided_at_utc) "
            "VALUES (?,?,'observed_row',?,NULL,'sr_source_projection','service_request',?,?,'medium',?,?,'pending',1,1,NULL)",
            (
                proposal_id,
                seeded["run_id"],
                seeded["source_observation_id"],
                service_request_id,
                sr_no,
                base_token,
                fingerprint,
            ),
        )
        uow.connection.execute(
            "INSERT INTO reconciliation_proposal_changes(reconciliation_proposal_id,ordinal,field_key,change_kind,value_kind,"
            "before_text,after_text,before_integer,after_integer,source_observation_field_id) "
            "VALUES (?,0,'current_handler_label','set','text',NULL,?,NULL,NULL,?)",
            (proposal_id, label, seeded["source_observation_field_id"]),
        )
    result = ProposalDecisionService(factory).accept(
        command_id=new_uuid4(),
        proposal_id=proposal_id,
        proposal_revision=1,
        proposal_fingerprint=fingerprint,
        base_state_token=base_token,
        reason_category="accepted_handler_source",
    )
    assert result.decision == "accepted"
    return {
        **seeded,
        "owner_observation_id": result.owner_result_refs[0][1],
    }


def _seed_handler_contact_proposal(
    factory,
    *,
    service_request_id: str,
    sr_no: str,
    target_contact_id: str,
    current_run_label: str,
    support_field_id: str,
    prior_contact_id: str | None,
    chronology: int,
):
    seeded = _insert_run_handler_field(
        factory,
        sr_no=sr_no,
        label=current_run_label,
        chronology=chronology,
        run_state="waiting_review",
        row_hash="8" * 64,
        field_hash="9" * 64,
        proposal_count=1,
    )
    base_token = _contact_base_token(
        factory,
        service_request_id=service_request_id,
        target_contact_id=target_contact_id,
        source_observation_field_id=support_field_id,
    )
    proposal_id = new_uuid4()
    fingerprint = "5" * 64
    with UnitOfWork(factory) as uow:
        uow.connection.execute(
            "INSERT INTO reconciliation_proposals(reconciliation_proposal_id,import_run_id,evidence_mode,source_observation_id,"
            "prior_source_observation_id,proposal_kind,target_kind,target_internal_id,target_business_id,risk_class,"
            "base_state_token_sha256,proposal_fingerprint_sha256,proposal_state,created_at_utc,revision,decided_at_utc) "
            "VALUES (?,?,'observed_row',?,NULL,'sr_current_handler_reconciliation','service_request',?,?,'high',?,?,'pending',1,1,NULL)",
            (
                proposal_id,
                seeded["run_id"],
                seeded["source_observation_id"],
                service_request_id,
                sr_no,
                base_token,
                fingerprint,
            ),
        )
        uow.connection.execute(
            "INSERT INTO reconciliation_proposal_changes(reconciliation_proposal_id,ordinal,field_key,change_kind,value_kind,"
            "before_text,after_text,before_integer,after_integer,source_observation_field_id) "
            "VALUES (?,0,'contact_id','set','identity',?,?,NULL,NULL,?)",
            (proposal_id, prior_contact_id, target_contact_id, support_field_id),
        )
    return {
        **seeded,
        "proposal_id": proposal_id,
        "fingerprint": fingerprint,
        "base_token": base_token,
    }


def _accept_contact(factory, seeded, *, command_id: str | None = None):
    actual_command_id = new_uuid4() if command_id is None else command_id
    result = ProposalDecisionService(factory).accept(
        command_id=actual_command_id,
        proposal_id=seeded["proposal_id"],
        proposal_revision=1,
        proposal_fingerprint=seeded["fingerprint"],
        base_state_token=seeded["base_token"],
        reason_category="reviewed_current_handler_contact",
    )
    return actual_command_id, result


def _build(factory, *, run_id: str, observation_id: str):
    with ReadSnapshot(factory) as snapshot:
        return build_advanced_search_sr_current_handler_reconciliation_proposals(
            snapshot.connection,
            import_run_id=run_id,
            source_observation_id=observation_id,
        )


def test_reader_and_builder_reuse_prior_accepted_handler_support(initialized_database) -> None:
    factory = _factory(initialized_database)
    sr = _official_sr(factory, "44000300")
    accepted = _accept_handler_source(
        factory,
        service_request_id=sr.service_request_id,
        sr_no="44000300",
        label="Handler Alpha",
        chronology=400,
        row_hash="a" * 64,
        field_hash="b" * 64,
    )
    target = _contact(factory, "Handler Alpha")
    current = _insert_run_handler_field(
        factory,
        sr_no="44000300",
        label="Handler Alpha",
        chronology=500,
        run_state="validating",
        row_hash="c" * 64,
        field_hash="d" * 64,
    )

    with ReadSnapshot(factory) as snapshot:
        projection = ServiceRequestImportReader.current_source_projection(
            snapshot.connection,
            sr.service_request_id,
        )
        assert projection is not None
        authority = projection["current_handler_authority"]
        assert authority == {
            "sr_source_field_observation_id": accepted["owner_observation_id"],
            "source_observation_field_id": accepted["source_observation_field_id"],
            "field_key": "current_handler_label",
            "value_state": "usable",
            "value_kind": "text",
            "text_value": "Handler Alpha",
            "integer_value": None,
            "source_chronology_utc": 400,
            "precedence_basis": "source_chronology",
        }

    result = _build(factory, run_id=current["run_id"], observation_id=current["source_observation_id"])
    assert result.resolution_state == "unique_candidate"
    assert result.matcher_scope == "UNBOUND"
    assert result.supporting_sr_source_field_observation_id == accepted["owner_observation_id"]
    assert result.supporting_source_observation_field_id == accepted["source_observation_field_id"]
    assert current["source_observation_field_id"] != accepted["source_observation_field_id"]
    proposal = result.proposals[0]
    assert proposal.proposal_kind == "sr_current_handler_reconciliation"
    assert proposal.risk_class == "high"
    assert proposal.changes[0].before_text is None
    assert proposal.changes[0].after_text == target.contact_id
    assert proposal.changes[0].source_observation_field_id == accepted["source_observation_field_id"]


def test_builder_waits_until_current_run_handler_matches_accepted_source(initialized_database) -> None:
    factory = _factory(initialized_database)
    sr = _official_sr(factory, "44000301")
    _accept_handler_source(
        factory,
        service_request_id=sr.service_request_id,
        sr_no="44000301",
        label="Accepted Handler",
        chronology=400,
        row_hash="e" * 64,
        field_hash="f" * 64,
    )
    _contact(factory, "New Handler")
    current = _insert_run_handler_field(
        factory,
        sr_no="44000301",
        label="New Handler",
        chronology=500,
        run_state="validating",
        row_hash="0" * 64,
        field_hash="1" * 64,
    )

    result = _build(factory, run_id=current["run_id"], observation_id=current["source_observation_id"])
    assert result.resolution_state == "current_run_handler_not_accepted"
    assert result.proposals == ()


def test_builder_keeps_handler_ambiguity_unresolved(initialized_database) -> None:
    factory = _factory(initialized_database)
    sr = _official_sr(factory, "44000302")
    _accept_handler_source(
        factory,
        service_request_id=sr.service_request_id,
        sr_no="44000302",
        label="Duplicate Handler",
        chronology=400,
        row_hash="2" * 64,
        field_hash="3" * 64,
    )
    first = _contact(factory, "Duplicate Handler")
    second = _contact(factory, "Duplicate Handler")
    assert first.contact_id != second.contact_id
    current = _insert_run_handler_field(
        factory,
        sr_no="44000302",
        label="Duplicate Handler",
        chronology=500,
        run_state="validating",
        row_hash="4" * 64,
        field_hash="5" * 64,
    )

    result = _build(factory, run_id=current["run_id"], observation_id=current["source_observation_id"])
    assert result.resolution_state == "ambiguous"
    assert result.proposals == ()


def test_same_contact_new_handler_support_is_material_and_rebinds_history(initialized_database) -> None:
    factory = _factory(initialized_database)
    sr = _official_sr(factory, "44000303")
    h1 = _accept_handler_source(
        factory,
        service_request_id=sr.service_request_id,
        sr_no="44000303",
        label="Handler One",
        chronology=400,
        row_hash="6" * 64,
        field_hash="7" * 64,
    )
    target = _contact(factory, "Handler One")
    first_proposal = _seed_handler_contact_proposal(
        factory,
        service_request_id=sr.service_request_id,
        sr_no="44000303",
        target_contact_id=target.contact_id,
        current_run_label="Handler One",
        support_field_id=h1["source_observation_field_id"],
        prior_contact_id=None,
        chronology=450,
    )
    _, first_result = _accept_contact(factory, first_proposal)
    assert first_result.decision == "accepted"

    ContactReferenceService(factory).update_contact_descriptive_data(
        command_id=new_uuid4(),
        contact_id=target.contact_id,
        base_revision=1,
        name="Handler Two",
    )
    h2 = _accept_handler_source(
        factory,
        service_request_id=sr.service_request_id,
        sr_no="44000303",
        label="Handler Two",
        chronology=500,
        row_hash="a" * 64,
        field_hash="c" * 64,
    )
    current = _insert_run_handler_field(
        factory,
        sr_no="44000303",
        label="Handler Two",
        chronology=600,
        run_state="validating",
        row_hash="d" * 64,
        field_hash="e" * 64,
    )
    built = _build(factory, run_id=current["run_id"], observation_id=current["source_observation_id"])
    assert built.resolution_state == "support_rebind"
    assert built.proposals[0].changes[0].before_text == target.contact_id
    assert built.proposals[0].changes[0].after_text == target.contact_id
    assert built.proposals[0].changes[0].source_observation_field_id == h2["source_observation_field_id"]

    rebind = _seed_handler_contact_proposal(
        factory,
        service_request_id=sr.service_request_id,
        sr_no="44000303",
        target_contact_id=target.contact_id,
        current_run_label="Handler Two",
        support_field_id=h2["source_observation_field_id"],
        prior_contact_id=target.contact_id,
        chronology=650,
    )
    command_id = new_uuid4()
    _, rebind_result = _accept_contact(factory, rebind, command_id=command_id)
    assert rebind_result.decision == "accepted"
    with ReadSnapshot(factory) as snapshot:
        rows = snapshot.connection.execute(
            "SELECT contact_id,relationship_state,supporting_sr_source_field_observation_id,opened_command_id,closed_command_id "
            "FROM sr_contact_relationships WHERE service_request_id=? AND reference_role='current_handler_reference' "
            "ORDER BY opened_at_utc,sr_contact_relationship_id",
            (sr.service_request_id,),
        ).fetchall()
        assert len(rows) == 2
        assert str(rows[0][0]) == target.contact_id
        assert str(rows[0][1]) == "superseded"
        assert str(rows[0][2]) == h1["owner_observation_id"]
        assert rows[0][4] is not None
        assert str(rows[1][0]) == target.contact_id
        assert str(rows[1][1]) == "active"
        assert str(rows[1][2]) == h2["owner_observation_id"]
        assert str(rows[1][3]) == command_id

    replay = ProposalDecisionService(factory).accept(
        command_id=command_id,
        proposal_id=rebind["proposal_id"],
        proposal_revision=1,
        proposal_fingerprint=rebind["fingerprint"],
        base_state_token=rebind["base_token"],
        reason_category="reviewed_current_handler_contact",
    )
    assert replay.replayed is True


def test_exact_same_contact_and_support_is_not_material(initialized_database) -> None:
    factory = _factory(initialized_database)
    sr = _official_sr(factory, "44000304")
    accepted = _accept_handler_source(
        factory,
        service_request_id=sr.service_request_id,
        sr_no="44000304",
        label="Stable Handler",
        chronology=400,
        row_hash="f" * 64,
        field_hash="0" * 64,
    )
    target = _contact(factory, "Stable Handler")
    first = _seed_handler_contact_proposal(
        factory,
        service_request_id=sr.service_request_id,
        sr_no="44000304",
        target_contact_id=target.contact_id,
        current_run_label="Stable Handler",
        support_field_id=accepted["source_observation_field_id"],
        prior_contact_id=None,
        chronology=450,
    )
    _accept_contact(factory, first)
    current = _insert_run_handler_field(
        factory,
        sr_no="44000304",
        label="Stable Handler",
        chronology=500,
        run_state="validating",
        row_hash="1" * 64,
        field_hash="2" * 64,
    )
    built = _build(factory, run_id=current["run_id"], observation_id=current["source_observation_id"])
    assert built.resolution_state == "already_current"
    assert built.proposals == ()

    duplicate = _seed_handler_contact_proposal(
        factory,
        service_request_id=sr.service_request_id,
        sr_no="44000304",
        target_contact_id=target.contact_id,
        current_run_label="Stable Handler",
        support_field_id=accepted["source_observation_field_id"],
        prior_contact_id=target.contact_id,
        chronology=550,
    )
    command_id = new_uuid4()
    with pytest.raises(SomaError) as excinfo:
        _accept_contact(factory, duplicate, command_id=command_id)
    assert excinfo.value.code == "IMPORT_PROPOSAL_STALE"
    with ReadSnapshot(factory) as snapshot:
        assert snapshot.connection.execute(
            "SELECT COUNT(*) FROM command_receipts WHERE command_id=?",
            (command_id,),
        ).fetchone()[0] == 0
