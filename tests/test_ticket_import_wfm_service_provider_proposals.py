from __future__ import annotations

from soma.foundation.identifiers import new_uuid4
from soma.foundation.persistence.uow import ReadSnapshot, UnitOfWork
from soma.objectives_tasks import TaskHardDeleteQueryService, TaskHardDeleteService, TaskPlanningService
from soma.objectives_tasks.services.wfm_import import (
    WfmImportBaseTarget,
    WfmImportMutationParticipant,
    WfmImportReader,
    WfmSourceProjectionAcceptanceMutation,
)
from soma.ticket_import.profiles import require_profile_versions
from soma.ticket_import.reconciliation.wfm_service_provider import build_wfm_service_provider_proposals
from soma.tickets.rfcs import RfcService


class _ClearInventoryDependencyProvider:
    def classify_task_hard_delete_dependency(self, reader, task_id):
        assert reader.connection.in_transaction
        return "CLEAR"


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


def _seed_observation(
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
            "'operator-wfm.xlsx',100,1,'embedded_filename_timestamp_utc',200,?,'validating',0,1,1,1,0,0,1)",
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


def _blank_instant(field_key: str) -> dict[str, object]:
    return {
        "field_key": field_key,
        "value_state": "blank",
        "value_kind": "instant",
        "source_text": "",
    }


def _build(factory, *, run_id: str, observation_id: str):
    with ReadSnapshot(factory) as snapshot:
        return build_wfm_service_provider_proposals(
            snapshot.connection,
            import_run_id=run_id,
            source_observation_id=observation_id,
        )


def _insert_receipt(uow: UnitOfWork, command_id: str) -> None:
    uow.connection.execute(
        "INSERT INTO command_receipts(command_id,command_type,request_hash,target_type,target_id,committed_at_utc,result_type,result_id) "
        "VALUES (?,'AcceptReconciliationProposal',?,'reconciliation_proposal',?,0,NULL,NULL)",
        (command_id, "a" * 64, new_uuid4()),
    )


def test_absent_task_with_existing_rfc_emits_create_only(initialized_database) -> None:
    factory = _factory(initialized_database)
    rfc, rfc_no = _create_rfc(factory, 401)
    task_no = "TK00000000000401"
    run_id, observation_id, _ = _seed_observation(
        factory,
        task_no=task_no,
        rfc_no=rfc_no,
        fields=(_unknown_status(),),
    )

    result = _build(factory, run_id=run_id, observation_id=observation_id)
    assert result.task_no_status == "ABSENT"
    assert result.rfc_id == rfc.rfc_id
    assert result.resolution_state == "create_review"
    assert result.blocked_finding_code is None
    assert len(result.proposals) == 1
    proposal = result.proposals[0]
    assert proposal.proposal_kind == "wfm_create_or_adopt"
    assert proposal.target_kind == "wfm"
    assert proposal.target_internal_id is None
    assert proposal.target_business_id == task_no
    assert proposal.risk_class == "medium"
    assert [(change.field_key, change.change_kind, change.after_text) for change in proposal.changes] == [
        ("task_no", "create", task_no),
        ("rfc_no", "link", rfc_no),
    ]


def test_retired_task_no_emits_blocking_finding_and_no_mutation_proposal(initialized_database) -> None:
    factory = _factory(initialized_database)
    rfc, rfc_no = _create_rfc(factory, 402)
    task_no = "TK00000000000402"
    registered = TaskPlanningService(factory).register_manual_wfm_task(
        command_id=new_uuid4(),
        task_no=task_no,
        rfc_id=rfc.rfc_id,
    )
    inventory = _ClearInventoryDependencyProvider()
    queries = TaskHardDeleteQueryService(factory, inventory)
    service = TaskHardDeleteService(factory, inventory)
    preview = queries.preview(task_id=registered.task_id, base_revision=1)
    assert preview.eligible
    result = service.hard_delete(
        command_id=new_uuid4(),
        task_id=registered.task_id,
        base_revision=preview.task_revision,
        eligibility_fingerprint=preview.eligibility_fingerprint,
        confirmation_context_id="ticket-import-wfm-retirement-fixture",
    )
    assert result.outcome == "APPLIED"
    with ReadSnapshot(factory) as snapshot:
        assert WfmImportReader.task_no_status(snapshot.connection, task_no) == "RETIRED"

    run_id, observation_id, _ = _seed_observation(
        factory,
        task_no=task_no,
        rfc_no=rfc_no,
        fields=(_unknown_status(),),
    )

    proposal_result = _build(factory, run_id=run_id, observation_id=observation_id)
    assert proposal_result.task_no_status == "RETIRED"
    assert proposal_result.resolution_state == "retired_blocked"
    assert proposal_result.blocked_finding_code == "WFM_TASK_ID_RETIRED"
    assert proposal_result.proposals == ()


def test_missing_parent_rfc_emits_no_lld05_mutation_proposal(initialized_database) -> None:
    factory = _factory(initialized_database)
    task_no = "TK00000000000403"
    missing_rfc_no = "NC00000000000403"
    run_id, observation_id, _ = _seed_observation(
        factory,
        task_no=task_no,
        rfc_no=missing_rfc_no,
        fields=(_unknown_status(),),
    )

    result = _build(factory, run_id=run_id, observation_id=observation_id)
    assert result.task_no_status == "ABSENT"
    assert result.resolution_state == "parent_rfc_missing"
    assert result.rfc_id is None
    assert result.proposals == ()


def test_active_task_emits_source_projection_for_unrecognized_nonterminal_status_and_plan(initialized_database) -> None:
    factory = _factory(initialized_database)
    rfc, rfc_no = _create_rfc(factory, 404)
    task_no = "TK00000000000404"
    registered = TaskPlanningService(factory).register_manual_wfm_task(
        command_id=new_uuid4(),
        task_no=task_no,
        rfc_id=rfc.rfc_id,
    )
    start = 2_040_000_000
    end = 2_040_003_600
    run_id, observation_id, field_ids = _seed_observation(
        factory,
        task_no=task_no,
        rfc_no=rfc_no,
        fields=(_unknown_status("Implementation"), _usable_instant("planned_start", start), _usable_instant("planned_end", end)),
    )

    result = _build(factory, run_id=run_id, observation_id=observation_id)
    assert result.task_no_status == "ACTIVE"
    assert result.task_id == registered.task_id
    assert result.resolution_state == "source_review"
    assert len(result.proposals) == 1
    proposal = result.proposals[0]
    assert proposal.proposal_kind == "wfm_source_projection"
    assert proposal.target_internal_id == registered.task_id
    assert proposal.risk_class == "medium"
    assert [(change.field_key, change.change_kind) for change in proposal.changes] == [
        ("task_status", "set"),
        ("planned_start", "set"),
        ("planned_end", "set"),
    ]
    assert proposal.changes[0].after_text == "Implementation"
    assert proposal.changes[0].source_observation_field_id == field_ids["task_status"]
    assert proposal.changes[1].after_integer == start
    assert proposal.changes[2].after_integer == end


def test_active_task_owned_by_other_rfc_is_not_silently_reassigned(initialized_database) -> None:
    factory = _factory(initialized_database)
    first, _first_no = _create_rfc(factory, 405)
    _second, second_no = _create_rfc(factory, 406)
    task_no = "TK00000000000405"
    registered = TaskPlanningService(factory).register_manual_wfm_task(
        command_id=new_uuid4(),
        task_no=task_no,
        rfc_id=first.rfc_id,
    )
    run_id, observation_id, _ = _seed_observation(
        factory,
        task_no=task_no,
        rfc_no=second_no,
        fields=(_unknown_status(),),
    )

    result = _build(factory, run_id=run_id, observation_id=observation_id)
    assert result.task_no_status == "ACTIVE"
    assert result.task_id == registered.task_id
    assert result.resolution_state == "parent_rfc_review_required"
    assert result.proposals == ()


def test_blank_status_and_incomplete_plan_preserve_prior_source_truth(initialized_database) -> None:
    factory = _factory(initialized_database)
    rfc, rfc_no = _create_rfc(factory, 407)
    task_no = "TK00000000000407"
    registered = TaskPlanningService(factory).register_manual_wfm_task(
        command_id=new_uuid4(),
        task_no=task_no,
        rfc_id=rfc.rfc_id,
    )
    prior_start = 2_041_000_000
    prior_end = 2_041_003_600
    with ReadSnapshot(factory) as snapshot:
        base_token = WfmImportReader.source_acceptance_base_token(
            snapshot.connection,
            WfmImportBaseTarget("wfm_source_projection", task_no, registered.task_id),
        )
    command_id = new_uuid4()
    with UnitOfWork(factory) as uow:
        _insert_receipt(uow, command_id)
        WfmImportMutationParticipant.apply_wfm_source_projection(
            uow,
            WfmSourceProjectionAcceptanceMutation(
                task_id=registered.task_id,
                task_no=task_no,
                expected_source_projection_revision=0,
                provider_status_token="Complete",
                provider_lifecycle_class="complete",
                source_plan_start_utc=prior_start,
                source_plan_end_utc=prior_end,
                accepted_source_observation_id=new_uuid4(),
                base_state_token=base_token,
                accepted_command_id=command_id,
            ),
        )

    run_id, observation_id, _ = _seed_observation(
        factory,
        task_no=task_no,
        rfc_no=rfc_no,
        fields=(
            {
                "field_key": "task_status",
                "value_state": "blank",
                "value_kind": "controlled",
                "source_text": "",
                "vocabulary_id": "WFM_TASK_STATUS_V1",
            },
            _usable_instant("planned_start", prior_start + 100),
            _blank_instant("planned_end"),
        ),
    )

    result = _build(factory, run_id=run_id, observation_id=observation_id)
    assert result.resolution_state == "no_source_change"
    assert result.proposals == ()