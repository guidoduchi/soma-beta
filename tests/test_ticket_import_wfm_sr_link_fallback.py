from __future__ import annotations

import pytest

from soma.foundation.errors import SomaError
from soma.foundation.identifiers import new_uuid4
from soma.foundation.persistence.uow import ReadSnapshot, UnitOfWork
from soma.objectives_tasks import TaskPlanningService
from soma.ticket_import.commands.decide_proposal import ProposalDecisionService
from soma.ticket_import.reconciliation.wfm_provisional_eligibility import build_wfm_service_provider_proposals
from soma.tickets.rfcs import RfcService
from soma.tickets.service_requests import ServiceRequestService


def _factory(initialized_database):
    database_path, factory_builder = initialized_database
    return factory_builder(database_path)


def _eligible_rfc(factory, *, rfc_no: str):
    rfc = RfcService(factory).create_or_adopt_identity(
        command_id=new_uuid4(),
        rfc_no=rfc_no,
        creation_context="provisional",
    )
    with UnitOfWork(factory) as uow:
        uow.connection.execute(
            "INSERT INTO rfc_current_source_projection("
            "rfc_id,status_text,status_class,status_authority,status_evidence_id,terminal_epoch_id,revision"
            ") VALUES (?,'Implement','implement_eligible','enhanced_rfc',?,NULL,1)",
            (rfc.rfc_id, new_uuid4()),
        )
    return rfc


def _seed_wfm_task_name_run(
    factory,
    *,
    task_no: str,
    rfc_no: str,
    task_name: str,
) -> tuple[str, str, str]:
    run_id = new_uuid4()
    observation_id = new_uuid4()
    field_id = new_uuid4()
    with UnitOfWork(factory) as uow:
        uow.connection.execute(
            "INSERT INTO import_runs(import_run_id,source_family,invocation_kind,source_profile_id,header_registry_id,"
            "vocabulary_registry_id,parser_profile_id,candidate_filename,candidate_file_size_bytes,"
            "candidate_stable_mtime_ns,candidate_chronology_kind,candidate_chronology_value,"
            "logical_fingerprint_sha256,run_state,started_at_utc,staged_at_utc,observed_row_count,"
            "valid_identity_count,proposal_count,pending_proposal_count,revision) "
            "VALUES (?,'wfm_service_provider','manual','WFM_SERVICE_PROVIDER_V1','WFM_HEADERS_V1',"
            "'WFM_VOCAB_V1','WFM_PARSER_V1','wfm.xlsx',1,1,'embedded_filename_timestamp_utc',1,"
            "NULL,'validating',1,1,1,1,0,0,1)",
            (run_id,),
        )
        uow.connection.execute(
            "INSERT INTO source_observations(source_observation_id,import_run_id,source_family,entity_kind,"
            "identity_state,canonical_primary_id,canonical_parent_rfc_no,row_ordinal,sheet_ordinal,row_logical_sha256,"
            "source_row_chronology_utc,presence_state,recorded_at_utc) "
            "VALUES (?,?,'wfm_service_provider','wfm','valid',?,?,1,1,?,10,'observed_valid_identity',1)",
            (observation_id, run_id, task_no, rfc_no, "a" * 64),
        )
        uow.connection.execute(
            "INSERT INTO source_observation_fields(source_observation_field_id,source_observation_id,field_key,"
            "field_class,value_state,value_kind,source_text,normalized_text,integer_value,vocabulary_id,"
            "field_logical_sha256) VALUES (?,?,'task_name','active','usable','text',?,?,NULL,NULL,?)",
            (field_id, observation_id, task_name, task_name, "b" * 64),
        )
    return run_id, observation_id, field_id


def _persist_single_pending(factory, draft) -> str:
    proposal_id = new_uuid4()
    with UnitOfWork(factory) as uow:
        uow.connection.execute(
            "INSERT INTO reconciliation_proposals(reconciliation_proposal_id,import_run_id,evidence_mode,"
            "source_observation_id,prior_source_observation_id,proposal_kind,target_kind,target_internal_id,"
            "target_business_id,risk_class,base_state_token_sha256,proposal_fingerprint_sha256,proposal_state,"
            "created_at_utc,revision,decided_at_utc) VALUES (?,?,?,?,NULL,?,?,?,?,?,?,?,'pending',1,1,NULL)",
            (
                proposal_id,
                draft.import_run_id,
                draft.evidence_mode,
                draft.source_observation_id,
                draft.proposal_kind,
                draft.target_kind,
                draft.target_internal_id,
                draft.target_business_id,
                draft.risk_class,
                draft.base_state_token_sha256,
                draft.proposal_fingerprint_sha256,
            ),
        )
        for change in draft.changes:
            uow.connection.execute(
                "INSERT INTO reconciliation_proposal_changes(reconciliation_proposal_id,ordinal,field_key,"
                "change_kind,value_kind,before_text,after_text,before_integer,after_integer,"
                "source_observation_field_id) VALUES (?,?,?,?,?,?,?,?,?,?)",
                (
                    proposal_id,
                    change.ordinal,
                    change.field_key,
                    change.change_kind,
                    change.value_kind,
                    change.before_text,
                    change.after_text,
                    change.before_integer,
                    change.after_integer,
                    change.source_observation_field_id,
                ),
            )
        uow.connection.execute(
            "UPDATE import_runs SET logical_fingerprint_sha256=?,run_state='waiting_review',"
            "proposal_count=1,pending_proposal_count=1,revision=revision+1 WHERE import_run_id=?",
            ("c" * 64, draft.import_run_id),
        )
    return proposal_id


def test_wfm_task_name_fallback_proposes_and_accepts_existing_sr_link(initialized_database) -> None:
    factory = _factory(initialized_database)
    rfc = _eligible_rfc(factory, rfc_no="NC00000000008101")
    task_no = "TK00000000008101"
    task = TaskPlanningService(factory).register_manual_wfm_task(
        command_id=new_uuid4(),
        task_no=task_no,
        rfc_id=rfc.rfc_id,
    )
    sr = ServiceRequestService(factory).create_manual_service_request(
        command_id=new_uuid4(),
        official_sr_no="81234567",
    )
    run_id, observation_id, field_id = _seed_wfm_task_name_run(
        factory,
        task_no=task_no,
        rfc_no=rfc.rfc_no,
        task_name="Prepare implementation for SR81234567",
    )

    with ReadSnapshot(factory) as snapshot:
        built = build_wfm_service_provider_proposals(
            snapshot.connection,
            import_run_id=run_id,
            source_observation_id=observation_id,
        )
    links = [proposal for proposal in built.proposals if proposal.proposal_kind == "sr_rfc_link_candidate"]
    assert len(links) == 1
    draft = links[0]
    assert draft.target_kind == "sr_rfc_relationship"
    assert draft.target_internal_id == rfc.rfc_id
    assert draft.target_business_id == rfc.rfc_no
    assert len(draft.changes) == 1
    assert draft.changes[0].after_text == sr.service_request_id
    assert draft.changes[0].source_observation_field_id == field_id

    proposal_id = _persist_single_pending(factory, draft)
    result = ProposalDecisionService(factory).accept(
        command_id=new_uuid4(),
        proposal_id=proposal_id,
        proposal_revision=1,
        proposal_fingerprint=draft.proposal_fingerprint_sha256,
        base_state_token=draft.base_state_token_sha256,
        reason_category="reviewed_wfm_task_name_sr_candidate",
    )
    assert result.decision == "accepted"
    assert result.replayed is False

    with ReadSnapshot(factory) as snapshot:
        links = snapshot.connection.execute(
            "SELECT service_request_id,rfc_id,link_state FROM sr_rfc_links "
            "WHERE service_request_id=? AND rfc_id=?",
            (sr.service_request_id, rfc.rfc_id),
        ).fetchall()
        assert [tuple(row) for row in links] == [(sr.service_request_id, rfc.rfc_id, "active")]
        run = snapshot.connection.execute(
            "SELECT pending_proposal_count,accepted_proposal_count,revision FROM import_runs WHERE import_run_id=?",
            (run_id,),
        ).fetchone()
        assert tuple(run) == (0, 1, 3)
        identity = snapshot.connection.execute(
            "SELECT task_id FROM wfm_task_identities WHERE task_no=?",
            (task_no,),
        ).fetchone()
        assert identity is not None and identity[0] == task.task_id


def test_accepted_rfc_summary_suppresses_wfm_task_name_sr_fallback(initialized_database) -> None:
    factory = _factory(initialized_database)
    rfc = _eligible_rfc(factory, rfc_no="NC00000000008102")
    task_no = "TK00000000008102"
    TaskPlanningService(factory).register_manual_wfm_task(
        command_id=new_uuid4(),
        task_no=task_no,
        rfc_id=rfc.rfc_id,
    )
    ServiceRequestService(factory).create_manual_service_request(
        command_id=new_uuid4(),
        official_sr_no="81234568",
    )
    ServiceRequestService(factory).create_manual_service_request(
        command_id=new_uuid4(),
        official_sr_no="81234569",
    )
    with UnitOfWork(factory) as uow:
        uow.connection.execute(
            "UPDATE rfc_current_source_projection SET summary_text=?,summary_evidence_id=?,revision=revision+1 "
            "WHERE rfc_id=?",
            ("Primary work is for SR81234568", new_uuid4(), rfc.rfc_id),
        )

    run_id, observation_id, _field_id = _seed_wfm_task_name_run(
        factory,
        task_no=task_no,
        rfc_no=rfc.rfc_no,
        task_name="Fallback mentions SR81234569",
    )
    with ReadSnapshot(factory) as snapshot:
        built = build_wfm_service_provider_proposals(
            snapshot.connection,
            import_run_id=run_id,
            source_observation_id=observation_id,
        )
    assert [proposal for proposal in built.proposals if proposal.proposal_kind == "sr_rfc_link_candidate"] == []


def test_rfc_summary_candidate_makes_pending_wfm_task_name_fallback_stale(initialized_database) -> None:
    factory = _factory(initialized_database)
    rfc = _eligible_rfc(factory, rfc_no="NC00000000008103")
    task_no = "TK00000000008103"
    TaskPlanningService(factory).register_manual_wfm_task(
        command_id=new_uuid4(),
        task_no=task_no,
        rfc_id=rfc.rfc_id,
    )
    fallback_sr = ServiceRequestService(factory).create_manual_service_request(
        command_id=new_uuid4(),
        official_sr_no="81234570",
    )
    ServiceRequestService(factory).create_manual_service_request(
        command_id=new_uuid4(),
        official_sr_no="81234571",
    )
    run_id, observation_id, _field_id = _seed_wfm_task_name_run(
        factory,
        task_no=task_no,
        rfc_no=rfc.rfc_no,
        task_name="Fallback work for SR81234570",
    )
    with ReadSnapshot(factory) as snapshot:
        built = build_wfm_service_provider_proposals(
            snapshot.connection,
            import_run_id=run_id,
            source_observation_id=observation_id,
        )
    draft = next(proposal for proposal in built.proposals if proposal.proposal_kind == "sr_rfc_link_candidate")
    proposal_id = _persist_single_pending(factory, draft)

    with UnitOfWork(factory) as uow:
        uow.connection.execute(
            "UPDATE rfc_current_source_projection SET summary_text=?,summary_evidence_id=?,revision=revision+1 "
            "WHERE rfc_id=?",
            ("Higher precedence SR81234571", new_uuid4(), rfc.rfc_id),
        )

    command_id = new_uuid4()
    with pytest.raises(SomaError) as caught:
        ProposalDecisionService(factory).accept(
            command_id=command_id,
            proposal_id=proposal_id,
            proposal_revision=1,
            proposal_fingerprint=draft.proposal_fingerprint_sha256,
            base_state_token=draft.base_state_token_sha256,
            reason_category="stale_wfm_fallback",
        )
    assert caught.value.code == "IMPORT_PROPOSAL_STALE"

    with ReadSnapshot(factory) as snapshot:
        assert snapshot.connection.execute(
            "SELECT COUNT(*) FROM sr_rfc_links WHERE service_request_id=? AND rfc_id=? AND link_state='active'",
            (fallback_sr.service_request_id, rfc.rfc_id),
        ).fetchone()[0] == 0
        assert snapshot.connection.execute(
            "SELECT COUNT(*) FROM command_receipts WHERE command_id=?",
            (command_id,),
        ).fetchone()[0] == 0
        assert snapshot.connection.execute(
            "SELECT proposal_state,revision FROM reconciliation_proposals WHERE reconciliation_proposal_id=?",
            (proposal_id,),
        ).fetchone() == ("pending", 1)
