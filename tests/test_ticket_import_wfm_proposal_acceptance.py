from __future__ import annotations

from soma.foundation.identifiers import new_uuid4
from soma.foundation.persistence.uow import ReadSnapshot, UnitOfWork
from soma.objectives_tasks import TaskPlanningService
from soma.objectives_tasks.services.wfm_import import WfmImportBaseTarget, WfmImportReader
from soma.ticket_import.commands.decide_proposal import ProposalDecisionService
from soma.ticket_import.profiles import require_profile_versions
from soma.tickets.rfc_import_mutations import RfcImportMutationService
from soma.tickets.rfc_import_reader import RfcImportReader
from soma.tickets.rfcs import RfcService


def _factory(initialized_database):
    database_path, factory_for_path = initialized_database
    return factory_for_path(database_path)


def _create_rfc(factory, suffix: int):
    rfc_no = f"NC{suffix:014d}"
    result = RfcService(factory).create_or_adopt_identity(
        command_id=new_uuid4(),
        rfc_no=rfc_no,
        creation_context="provisional",
    )
    return result, rfc_no


def _seed_run_and_observation(
    factory,
    *,
    task_no: str,
    rfc_no: str,
    fields: tuple[dict[str, object], ...],
) -> tuple[str, str, dict[str, str]]:
    versions = require_profile_versions("wfm_service_provider")
    run_id = new_uuid4()
    observation_id = new_uuid4()
    field_ids: dict[str, str] = {}
    with UnitOfWork(factory) as uow:
        uow.connection.execute(
            "INSERT INTO import_runs("
            "import_run_id,source_family,invocation_kind,source_profile_id,header_registry_id,vocabulary_registry_id,parser_profile_id,"
            "candidate_filename,candidate_file_size_bytes,candidate_stable_mtime_ns,candidate_chronology_kind,candidate_chronology_value,"
            "logical_fingerprint_sha256,run_state,started_at_utc,staged_at_utc,observed_row_count,valid_identity_count,"
            "proposal_count,pending_proposal_count,revision"
            ") VALUES (?,'wfm_service_provider','manual',?,?,?,?,"
            "'operator-wfm.xlsx',100,1,'embedded_filename_timestamp_utc',200,?,'waiting_review',0,1,1,1,1,1,1)",
            (
                run_id,
                versions.source_profile_id,
                versions.header_registry_id,
                versions.vocabulary_registry_id,
                versions.parser_profile_id,
                "1" * 64,
            ),
        )
        uow.connection.execute(
            "INSERT INTO source_observations(source_observation_id,import_run_id,source_family,entity_kind,identity_state,"
            "canonical_primary_id,canonical_parent_rfc_no,row_ordinal,sheet_ordinal,row_logical_sha256,source_row_chronology_utc,"
            "presence_state,recorded_at_utc) VALUES (?,?,'wfm_service_provider','wfm','valid',?,?,1,1,?,200,"
            "'observed_valid_identity',1)",
            (observation_id, run_id, task_no, rfc_no, "2" * 64),
        )
        for ordinal, field in enumerate(fields):
            field_id = new_uuid4()
            key = str(field["field_key"])
            field_ids[key] = field_id
            uow.connection.execute(
                "INSERT INTO source_observation_fields(source_observation_field_id,source_observation_id,field_key,field_class,"
                "value_state,value_kind,source_text,normalized_text,integer_value,vocabulary_id,field_logical_sha256) "
                "VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                (
                    field_id,
                    observation_id,
                    key,
                    field.get("field_class", "active"),
                    field["value_state"],
                    field["value_kind"],
                    field.get("source_text"),
                    field.get("normalized_text"),
                    field.get("integer_value"),
                    field.get("vocabulary_id"),
                    f"{ordinal + 3:064x}",
                ),
            )
    return run_id, observation_id, field_ids


def _unknown_status(value: str = "Implementation") -> dict[str, object]:
    return {
        "field_key": "task_status",
        "value_state": "unknown",
        "value_kind": "controlled",
        "source_text": value,
        "vocabulary_id": "WFM_TASK_STATUS_V1",
    }


def _usable_instant(field_key: str, value: int) -> dict[str, object]:
    return {
        "field_key": field_key,
        "value_state": "usable",
        "value_kind": "instant",
        "source_text": str(value),
        "integer_value": value,
    }


def _seed_provisional_rfc_proposal(
    factory,
    *,
    run_id: str,
    observation_id: str,
    rfc_no: str,
    base_token: str,
    fingerprint: str,
) -> str:
    proposal_id = new_uuid4()
    with UnitOfWork(factory) as uow:
        uow.connection.execute(
            "INSERT INTO reconciliation_proposals(reconciliation_proposal_id,import_run_id,evidence_mode,source_observation_id,"
            "prior_source_observation_id,proposal_kind,target_kind,target_internal_id,target_business_id,risk_class,"
            "base_state_token_sha256,proposal_fingerprint_sha256,proposal_state,created_at_utc,revision,decided_at_utc) "
            "VALUES (?,?,'observed_row',?,NULL,'wfm_provisional_rfc','rfc',NULL,?,'high',?,?,'pending',1,1,NULL)",
            (proposal_id, run_id, observation_id, rfc_no, base_token, fingerprint),
        )
        uow.connection.execute(
            "INSERT INTO reconciliation_proposal_changes(reconciliation_proposal_id,ordinal,field_key,change_kind,value_kind,"
            "before_text,after_text,before_integer,after_integer,source_observation_field_id) "
            "VALUES (?,0,'rfc_no','create','identity',NULL,?,NULL,NULL,NULL)",
            (proposal_id, rfc_no),
        )
    return proposal_id


def _seed_create_proposal(
    factory,
    *,
    run_id: str,
    observation_id: str,
    task_no: str,
    rfc_no: str,
    base_token: str,
    fingerprint: str,
) -> str:
    proposal_id = new_uuid4()
    with UnitOfWork(factory) as uow:
        uow.connection.execute(
            "INSERT INTO reconciliation_proposals(reconciliation_proposal_id,import_run_id,evidence_mode,source_observation_id,"
            "prior_source_observation_id,proposal_kind,target_kind,target_internal_id,target_business_id,risk_class,"
            "base_state_token_sha256,proposal_fingerprint_sha256,proposal_state,created_at_utc,revision,decided_at_utc) "
            "VALUES (?,?,'observed_row',?,NULL,'wfm_create_or_adopt','wfm',NULL,?,'medium',?,?,'pending',1,1,NULL)",
            (proposal_id, run_id, observation_id, task_no, base_token, fingerprint),
        )
        uow.connection.execute(
            "INSERT INTO reconciliation_proposal_changes(reconciliation_proposal_id,ordinal,field_key,change_kind,value_kind,"
            "before_text,after_text,before_integer,after_integer,source_observation_field_id) "
            "VALUES (?,0,'task_no','create','identity',NULL,?,NULL,NULL,NULL)",
            (proposal_id, task_no),
        )
        uow.connection.execute(
            "INSERT INTO reconciliation_proposal_changes(reconciliation_proposal_id,ordinal,field_key,change_kind,value_kind,"
            "before_text,after_text,before_integer,after_integer,source_observation_field_id) "
            "VALUES (?,1,'rfc_no','link','identity',NULL,?,NULL,NULL,NULL)",
            (proposal_id, rfc_no),
        )
    return proposal_id


def _seed_source_projection_proposal(
    factory,
    *,
    run_id: str,
    observation_id: str,
    task_id: str,
    task_no: str,
    base_token: str,
    fingerprint: str,
    status_field_id: str,
    start_field_id: str,
    end_field_id: str,
    start: int,
    end: int,
) -> str:
    proposal_id = new_uuid4()
    with UnitOfWork(factory) as uow:
        uow.connection.execute(
            "INSERT INTO reconciliation_proposals(reconciliation_proposal_id,import_run_id,evidence_mode,source_observation_id,"
            "prior_source_observation_id,proposal_kind,target_kind,target_internal_id,target_business_id,risk_class,"
            "base_state_token_sha256,proposal_fingerprint_sha256,proposal_state,created_at_utc,revision,decided_at_utc) "
            "VALUES (?,?,'observed_row',?,NULL,'wfm_source_projection','wfm',?,?,'medium',?,?,'pending',1,1,NULL)",
            (proposal_id, run_id, observation_id, task_id, task_no, base_token, fingerprint),
        )
        uow.connection.execute(
            "INSERT INTO reconciliation_proposal_changes(reconciliation_proposal_id,ordinal,field_key,change_kind,value_kind,"
            "before_text,after_text,before_integer,after_integer,source_observation_field_id) "
            "VALUES (?,0,'task_status','set','controlled',NULL,'Implementation',NULL,NULL,?)",
            (proposal_id, status_field_id),
        )
        uow.connection.execute(
            "INSERT INTO reconciliation_proposal_changes(reconciliation_proposal_id,ordinal,field_key,change_kind,value_kind,"
            "before_text,after_text,before_integer,after_integer,source_observation_field_id) "
            "VALUES (?,1,'planned_start','set','instant',NULL,NULL,NULL,?,?)",
            (proposal_id, start, start_field_id),
        )
        uow.connection.execute(
            "INSERT INTO reconciliation_proposal_changes(reconciliation_proposal_id,ordinal,field_key,change_kind,value_kind,"
            "before_text,after_text,before_integer,after_integer,source_observation_field_id) "
            "VALUES (?,2,'planned_end','set','instant',NULL,NULL,NULL,?,?)",
            (proposal_id, end, end_field_id),
        )
    return proposal_id


def test_accept_wfm_provisional_rfc_commits_identity_disposition_and_replays(initialized_database) -> None:
    factory = _factory(initialized_database)
    task_no = "TK00000000000600"
    rfc_no = "NC00000000000600"
    run_id, observation_id, _ = _seed_run_and_observation(
        factory,
        task_no=task_no,
        rfc_no=rfc_no,
        fields=(_unknown_status(),),
    )
    with ReadSnapshot(factory) as snapshot:
        base_token = RfcImportMutationService.source_identity_base_token(snapshot.connection, rfc_no)
    fingerprint = "2" * 64
    proposal_id = _seed_provisional_rfc_proposal(
        factory,
        run_id=run_id,
        observation_id=observation_id,
        rfc_no=rfc_no,
        base_token=base_token,
        fingerprint=fingerprint,
    )
    command_id = new_uuid4()
    service = ProposalDecisionService(factory)
    first = service.accept(
        command_id=command_id,
        proposal_id=proposal_id,
        proposal_revision=1,
        proposal_fingerprint=fingerprint,
        base_state_token=base_token,
    )
    assert first.decision == "accepted"
    assert first.replayed is False
    rfc_refs = [ref for ref in first.owner_result_refs if ref[0] == "rfc"]
    assert len(rfc_refs) == 1

    replay = service.accept(
        command_id=command_id,
        proposal_id=proposal_id,
        proposal_revision=1,
        proposal_fingerprint=fingerprint,
        base_state_token=base_token,
    )
    assert replay.replayed is True
    assert replay.owner_result_refs == first.owner_result_refs

    with ReadSnapshot(factory) as snapshot:
        identity = RfcImportReader().get_by_number(snapshot.connection, rfc_no)
        assert identity is not None
        assert identity["rfc_id"] == rfc_refs[0][1]
        proposal = snapshot.connection.execute(
            "SELECT proposal_state,revision FROM reconciliation_proposals WHERE reconciliation_proposal_id=?",
            (proposal_id,),
        ).fetchone()
        assert tuple(proposal) == ("accepted", 2)
        run = snapshot.connection.execute(
            "SELECT pending_proposal_count,accepted_proposal_count,revision FROM import_runs WHERE import_run_id=?",
            (run_id,),
        ).fetchone()
        assert tuple(run) == (0, 1, 2)


def test_accept_wfm_create_commits_owner_disposition_and_replays(initialized_database) -> None:
    factory = _factory(initialized_database)
    rfc, rfc_no = _create_rfc(factory, 601)
    task_no = "TK00000000000601"
    run_id, observation_id, _ = _seed_run_and_observation(
        factory,
        task_no=task_no,
        rfc_no=rfc_no,
        fields=(_unknown_status(),),
    )
    with ReadSnapshot(factory) as snapshot:
        base_token = WfmImportReader.source_acceptance_base_token(
            snapshot.connection,
            WfmImportBaseTarget("wfm_create_or_adopt", task_no, None),
        )
    fingerprint = "3" * 64
    proposal_id = _seed_create_proposal(
        factory,
        run_id=run_id,
        observation_id=observation_id,
        task_no=task_no,
        rfc_no=rfc_no,
        base_token=base_token,
        fingerprint=fingerprint,
    )
    command_id = new_uuid4()
    service = ProposalDecisionService(factory)
    first = service.accept(
        command_id=command_id,
        proposal_id=proposal_id,
        proposal_revision=1,
        proposal_fingerprint=fingerprint,
        base_state_token=base_token,
    )
    assert first.decision == "accepted"
    assert first.replayed is False
    task_refs = [ref for ref in first.owner_result_refs if ref[0] == "task"]
    assert len(task_refs) == 1
    task_id = task_refs[0][1]

    replay = service.accept(
        command_id=command_id,
        proposal_id=proposal_id,
        proposal_revision=1,
        proposal_fingerprint=fingerprint,
        base_state_token=base_token,
    )
    assert replay.replayed is True
    assert replay.owner_result_refs == first.owner_result_refs

    with ReadSnapshot(factory) as snapshot:
        identity = WfmImportReader.get_by_task_no(snapshot.connection, task_no)
        assert identity is not None
        assert identity["task_id"] == task_id
        assert identity["current_rfc_id"] == rfc.rfc_id
        proposal = snapshot.connection.execute(
            "SELECT proposal_state,revision FROM reconciliation_proposals WHERE reconciliation_proposal_id=?",
            (proposal_id,),
        ).fetchone()
        assert tuple(proposal) == ("accepted", 2)
        run = snapshot.connection.execute(
            "SELECT pending_proposal_count,accepted_proposal_count,revision FROM import_runs WHERE import_run_id=?",
            (run_id,),
        ).fetchone()
        assert tuple(run) == (0, 1, 2)
        assert snapshot.connection.execute(
            "SELECT COUNT(*) FROM proposal_dispositions WHERE reconciliation_proposal_id=?",
            (proposal_id,),
        ).fetchone()[0] == 1


def test_accept_wfm_source_projection_applies_exact_reviewed_source_and_replays(initialized_database) -> None:
    factory = _factory(initialized_database)
    rfc, rfc_no = _create_rfc(factory, 602)
    task_no = "TK00000000000602"
    registered = TaskPlanningService(factory).register_manual_wfm_task(
        command_id=new_uuid4(),
        task_no=task_no,
        rfc_id=rfc.rfc_id,
    )
    start = 2_060_000_000
    end = 2_060_003_600
    run_id, observation_id, field_ids = _seed_run_and_observation(
        factory,
        task_no=task_no,
        rfc_no=rfc_no,
        fields=(
            _unknown_status("Implementation"),
            _usable_instant("planned_start", start),
            _usable_instant("planned_end", end),
        ),
    )
    with ReadSnapshot(factory) as snapshot:
        base_token = WfmImportReader.source_acceptance_base_token(
            snapshot.connection,
            WfmImportBaseTarget("wfm_source_projection", task_no, registered.task_id),
        )
    fingerprint = "4" * 64
    proposal_id = _seed_source_projection_proposal(
        factory,
        run_id=run_id,
        observation_id=observation_id,
        task_id=registered.task_id,
        task_no=task_no,
        base_token=base_token,
        fingerprint=fingerprint,
        status_field_id=field_ids["task_status"],
        start_field_id=field_ids["planned_start"],
        end_field_id=field_ids["planned_end"],
        start=start,
        end=end,
    )
    command_id = new_uuid4()
    service = ProposalDecisionService(factory)
    first = service.accept(
        command_id=command_id,
        proposal_id=proposal_id,
        proposal_revision=1,
        proposal_fingerprint=fingerprint,
        base_state_token=base_token,
    )
    assert first.decision == "accepted"
    assert first.replayed is False

    replay = service.accept(
        command_id=command_id,
        proposal_id=proposal_id,
        proposal_revision=1,
        proposal_fingerprint=fingerprint,
        base_state_token=base_token,
    )
    assert replay.replayed is True
    assert replay.owner_result_refs == first.owner_result_refs

    with ReadSnapshot(factory) as snapshot:
        source = WfmImportReader.source_projection(snapshot.connection, registered.task_id)
        assert source is not None
        assert source["source_projection_revision"] == 1
        assert source["provider_status_token"] == "Implementation"
        assert source["provider_lifecycle_class"] == "active"
        assert source["source_plan_start_utc"] == start
        assert source["source_plan_end_utc"] == end
        assert source["accepted_source_observation_id"] == observation_id
        proposal = snapshot.connection.execute(
            "SELECT proposal_state,revision FROM reconciliation_proposals WHERE reconciliation_proposal_id=?",
            (proposal_id,),
        ).fetchone()
        assert tuple(proposal) == ("accepted", 2)
        run = snapshot.connection.execute(
            "SELECT pending_proposal_count,accepted_proposal_count,revision FROM import_runs WHERE import_run_id=?",
            (run_id,),
        ).fetchone()
        assert tuple(run) == (0, 1, 2)
