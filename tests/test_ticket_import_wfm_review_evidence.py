from __future__ import annotations

import pytest

from soma.foundation.errors import SomaError
from soma.foundation.identifiers import new_uuid4
from soma.foundation.persistence.uow import ReadSnapshot, UnitOfWork
from soma.objectives_tasks import TaskPlanningService
from soma.objectives_tasks.services.wfm_import import (
    WfmImportBaseTarget,
    WfmImportMutationParticipant,
    WfmImportReader,
    WfmSourceProjectionAcceptanceMutation,
)
from soma.ticket_import.profiles import require_profile_versions
from soma.ticket_import.providers.wfm_review_evidence import TicketImportWfmReviewEvidenceProvider
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


def _seed_published_observation(
    factory,
    *,
    task_no: str,
    rfc_no: str,
    fields: tuple[dict[str, object], ...],
) -> tuple[str, str]:
    versions = require_profile_versions("wfm_service_provider")
    run_id = new_uuid4()
    observation_id = new_uuid4()
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
            uow.connection.execute(
                "INSERT INTO source_observation_fields(source_observation_field_id,source_observation_id,field_key,field_class,"
                "value_state,value_kind,source_text,normalized_text,integer_value,vocabulary_id,field_logical_sha256) "
                "VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                (
                    new_uuid4(),
                    observation_id,
                    field["field_key"],
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
    return run_id, observation_id


def _unknown_status(value: str) -> dict[str, object]:
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


def _insert_receipt(uow: UnitOfWork, command_id: str) -> None:
    uow.connection.execute(
        "INSERT INTO command_receipts(command_id,command_type,request_hash,target_type,target_id,committed_at_utc,result_type,result_id) "
        "VALUES (?,'AcceptReconciliationProposal',?,'reconciliation_proposal',?,0,NULL,NULL)",
        (command_id, "a" * 64, new_uuid4()),
    )


def test_create_review_revalidates_absent_identity_and_goes_stale_if_task_appears(initialized_database) -> None:
    factory = _factory(initialized_database)
    rfc, rfc_no = _create_rfc(factory, 501)
    task_no = "TK00000000000501"
    run_id, observation_id = _seed_published_observation(
        factory,
        task_no=task_no,
        rfc_no=rfc_no,
        fields=(_unknown_status("Implementation"),),
    )
    provider = TicketImportWfmReviewEvidenceProvider()
    with ReadSnapshot(factory) as snapshot:
        candidate = provider.revalidate_create_candidate(
            snapshot.connection,
            expected_import_run_id=run_id,
            expected_source_observation_id=observation_id,
            expected_task_no=task_no,
            expected_parent_rfc_no=rfc_no,
        )
        expected_base = WfmImportReader.source_acceptance_base_token(
            snapshot.connection,
            WfmImportBaseTarget("wfm_create_or_adopt", task_no, None),
        )
    assert candidate.rfc_id == rfc.rfc_id
    assert candidate.source_lifecycle_class == "active"
    assert candidate.base_state_token == expected_base

    TaskPlanningService(factory).register_manual_wfm_task(
        command_id=new_uuid4(),
        task_no=task_no,
        rfc_id=rfc.rfc_id,
    )
    with pytest.raises(SomaError) as exc_info:
        with ReadSnapshot(factory) as snapshot:
            provider.revalidate_create_candidate(
                snapshot.connection,
                expected_import_run_id=run_id,
                expected_source_observation_id=observation_id,
                expected_task_no=task_no,
                expected_parent_rfc_no=rfc_no,
            )
    assert exc_info.value.code == "IMPORT_PROPOSAL_STALE"


def test_source_projection_review_recomputes_exact_current_owner_state(initialized_database) -> None:
    factory = _factory(initialized_database)
    rfc, rfc_no = _create_rfc(factory, 502)
    task_no = "TK00000000000502"
    registered = TaskPlanningService(factory).register_manual_wfm_task(
        command_id=new_uuid4(),
        task_no=task_no,
        rfc_id=rfc.rfc_id,
    )
    start = 2_050_000_000
    end = 2_050_003_600
    run_id, observation_id = _seed_published_observation(
        factory,
        task_no=task_no,
        rfc_no=rfc_no,
        fields=(
            _unknown_status("Implementation"),
            _usable_instant("planned_start", start),
            _usable_instant("planned_end", end),
        ),
    )
    provider = TicketImportWfmReviewEvidenceProvider()
    with ReadSnapshot(factory) as snapshot:
        candidate = provider.revalidate_source_projection_candidate(
            snapshot.connection,
            expected_import_run_id=run_id,
            expected_source_observation_id=observation_id,
            expected_task_id=registered.task_id,
            expected_task_no=task_no,
            expected_parent_rfc_no=rfc_no,
        )
        expected_base = WfmImportReader.source_acceptance_base_token(
            snapshot.connection,
            WfmImportBaseTarget("wfm_source_projection", task_no, registered.task_id),
        )
    assert candidate.expected_source_projection_revision == 0
    assert candidate.provider_status_token == "Implementation"
    assert candidate.provider_lifecycle_class == "active"
    assert candidate.source_plan_start_utc == start
    assert candidate.source_plan_end_utc == end
    assert candidate.base_state_token == expected_base
    assert [(change.field_key, change.change_kind) for change in candidate.changes] == [
        ("task_status", "set"),
        ("planned_start", "set"),
        ("planned_end", "set"),
    ]

    command_id = new_uuid4()
    with UnitOfWork(factory) as uow:
        _insert_receipt(uow, command_id)
        WfmImportMutationParticipant.apply_wfm_source_projection(
            uow,
            WfmSourceProjectionAcceptanceMutation(
                task_id=registered.task_id,
                task_no=task_no,
                expected_source_projection_revision=0,
                provider_status_token="Implementation",
                provider_lifecycle_class="active",
                source_plan_start_utc=start,
                source_plan_end_utc=end,
                accepted_source_observation_id=observation_id,
                base_state_token=expected_base,
                accepted_command_id=command_id,
            ),
        )

    with pytest.raises(SomaError) as exc_info:
        with ReadSnapshot(factory) as snapshot:
            provider.revalidate_source_projection_candidate(
                snapshot.connection,
                expected_import_run_id=run_id,
                expected_source_observation_id=observation_id,
                expected_task_id=registered.task_id,
                expected_task_no=task_no,
                expected_parent_rfc_no=rfc_no,
            )
    assert exc_info.value.code == "IMPORT_PROPOSAL_STALE"
