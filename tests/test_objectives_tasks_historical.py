from __future__ import annotations

import pytest

from soma.foundation.audit.writer import AuditWriter
from soma.foundation.errors import SomaError
from soma.foundation.identifiers import new_uuid4
from soma.foundation.persistence.uow import ReadSnapshot, UnitOfWork
from soma.objectives_tasks import TaskPlanningService
from soma.objectives_tasks.audit_registry import build_objectives_tasks_audit_registry
from soma.objectives_tasks.queries.reviews import HistoricalObjectiveQueryService
from soma.objectives_tasks.repositories.reviews import HistoricalObjectiveProposalRepository
from soma.objectives_tasks.services.historical import HistoricalObjectiveService
from soma.objectives_tasks.services.wfm_import import (
    WfmSourceProjectionAcceptanceMutation,
    WfmImportBaseTarget,
    WfmImportMutationParticipant,
    WfmImportReader,
)
from soma.tickets.rfcs import RfcService


def _factory(initialized_database):
    path, builder = initialized_database
    return builder(path)


def _outer_receipt(uow: UnitOfWork, command_id: str) -> None:
    target = new_uuid4()
    uow.connection.execute(
        "INSERT INTO command_receipts("
        "command_id,command_type,request_hash,target_type,target_id,"
        "committed_at_utc,result_type,result_id"
        ") VALUES (?,'AcceptReconciliationProposal',?,"
        "'reconciliation_proposal',?,0,NULL,NULL)",
        (command_id, "a" * 64, target),
    )


def _historical_wfm(factory, suffix: int):
    rfc = RfcService(factory).create_or_adopt_identity(
        command_id=new_uuid4(),
        rfc_no=f"NC{suffix:014d}",
        creation_context="provisional",
    )
    task_no = f"TK{suffix:014d}"
    task = TaskPlanningService(factory).register_manual_wfm_task(
        command_id=new_uuid4(),
        task_no=task_no,
        rfc_id=rfc.rfc_id,
    )
    observation_id = new_uuid4()
    with ReadSnapshot(factory) as snapshot:
        token = WfmImportReader.source_acceptance_base_token(
            snapshot.connection,
            WfmImportBaseTarget(
                "wfm_source_projection",
                task_no,
                task.task_id,
            ),
        )
    start = 2_500_000_000 + suffix * 10_000
    end = start + 3600
    command_id = new_uuid4()
    with UnitOfWork(factory) as uow:
        _outer_receipt(uow, command_id)
        result = WfmImportMutationParticipant.apply_wfm_source_projection(
            uow,
            WfmSourceProjectionAcceptanceMutation(
                task_id=task.task_id,
                task_no=task_no,
                expected_source_projection_revision=0,
                provider_status_token="Complete",
                provider_lifecycle_class="complete",
                source_plan_start_utc=start,
                source_plan_end_utc=end,
                accepted_source_observation_id=observation_id,
                base_state_token=token,
                accepted_command_id=command_id,
            ),
        )
        for event in result.audit_events:
            AuditWriter(build_objectives_tasks_audit_registry()).write(
                uow, event
            )
    return task, observation_id, start, end


def _proposal(factory, task_id: str, observation_id: str, start: int, end: int):
    with UnitOfWork(factory) as uow:
        fingerprint = HistoricalObjectiveQueryService.input_fingerprint(
            uow.connection, task_id
        )
        return HistoricalObjectiveProposalRepository.insert_pending(
            uow,
            task_id=task_id,
            expected_source_projection_revision=1,
            expected_source_plan_start_utc=start,
            expected_source_plan_end_utc=end,
            expected_source_observation_id=observation_id,
            expected_matching_operational_plan_revision_id=None,
            input_fingerprint=fingerprint,
            created_at_utc=100,
        )


def test_historical_accept_creates_structure_only_and_replays(initialized_database) -> None:
    factory = _factory(initialized_database)
    task, observation_id, start, end = _historical_wfm(factory, 701)
    proposal = _proposal(
        factory, task.task_id, observation_id, start, end
    )
    service = HistoricalObjectiveService(factory)
    command_id = new_uuid4()
    accepted = service.accept_proposal(
        command_id=command_id,
        proposal_id=proposal.proposal_id,
        proposal_revision=1,
        input_fingerprint=proposal.input_fingerprint,
    )
    assert accepted.state == "accepted"
    assert accepted.objective_id is not None
    replayed = service.accept_proposal(
        command_id=command_id,
        proposal_id=proposal.proposal_id,
        proposal_revision=1,
        input_fingerprint=proposal.input_fingerprint,
    )
    assert replayed.replayed is True
    assert replayed.objective_id == accepted.objective_id

    with ReadSnapshot(factory) as snapshot:
        plan = snapshot.connection.execute(
            "SELECT p.origin,p.scheduling_timezone_iana,"
            "p.source_observation_id,p.start_utc,p.end_utc "
            "FROM task_plan_current c JOIN task_plan_revisions p "
            "ON p.plan_revision_id=c.plan_revision_id "
            "WHERE c.task_id=?",
            (task.task_id,),
        ).fetchone()
        assert tuple(plan) == (
            "historical_source_structure",
            "America/Guayaquil",
            observation_id,
            start,
            end,
        )
        objective = snapshot.connection.execute(
            "SELECT creation_origin FROM objectives WHERE objective_id=?",
            (accepted.objective_id,),
        ).fetchone()
        assert str(objective[0]) == "historical_provider_complete"
        aggregate = snapshot.connection.execute(
            "SELECT execution_state,actual_start_utc,actual_end_utc "
            "FROM objective_aggregate_projection WHERE objective_id=?",
            (accepted.objective_id,),
        ).fetchone()
        assert tuple(aggregate) == ("historical_structure", None, None)
        assert snapshot.connection.execute(
            "SELECT count(*) FROM task_execution_events WHERE task_id=?",
            (task.task_id,),
        ).fetchone()[0] == 0
        assert snapshot.connection.execute(
            "SELECT count(*) FROM task_outcome_events WHERE task_id=?",
            (task.task_id,),
        ).fetchone()[0] == 0


def test_historical_reject_changes_proposal_only(initialized_database) -> None:
    factory = _factory(initialized_database)
    task, observation_id, start, end = _historical_wfm(factory, 702)
    proposal = _proposal(
        factory, task.task_id, observation_id, start, end
    )
    rejected = HistoricalObjectiveService(factory).reject_proposal(
        command_id=new_uuid4(),
        proposal_id=proposal.proposal_id,
        proposal_revision=1,
        input_fingerprint=proposal.input_fingerprint,
        reason_category="provider history intentionally excluded",
    )
    assert rejected.state == "rejected"
    assert rejected.objective_id is None
    with ReadSnapshot(factory) as snapshot:
        assert snapshot.connection.execute(
            "SELECT state,revision FROM historical_objective_proposals "
            "WHERE historical_proposal_id=?",
            (proposal.proposal_id,),
        ).fetchone() == ("rejected", 2)
        assert snapshot.connection.execute(
            "SELECT count(*) FROM objectives"
        ).fetchone()[0] == 0
        assert snapshot.connection.execute(
            "SELECT count(*) FROM task_plan_current WHERE task_id=?",
            (task.task_id,),
        ).fetchone()[0] == 0


def test_historical_proposal_stales_when_source_material_changes(initialized_database) -> None:
    factory = _factory(initialized_database)
    task, observation_id, start, end = _historical_wfm(factory, 703)
    proposal = _proposal(
        factory, task.task_id, observation_id, start, end
    )
    with UnitOfWork(factory) as uow:
        uow.connection.execute(
            "UPDATE tasks SET revision=revision+1 WHERE task_id=?",
            (task.task_id,),
        )
    with pytest.raises(SomaError) as caught:
        HistoricalObjectiveService(factory).reject_proposal(
            command_id=new_uuid4(),
            proposal_id=proposal.proposal_id,
            proposal_revision=1,
            input_fingerprint=proposal.input_fingerprint,
            reason_category="stale rejection must fail",
        )
    assert caught.value.code == "HISTORICAL_PROPOSAL_STALE"


def test_historical_operational_count_exclusion_is_reporting_only(initialized_database) -> None:
    factory = _factory(initialized_database)
    task, observation_id, start, end = _historical_wfm(factory, 704)
    proposal = _proposal(
        factory, task.task_id, observation_id, start, end
    )
    accepted = HistoricalObjectiveService(factory).accept_proposal(
        command_id=new_uuid4(),
        proposal_id=proposal.proposal_id,
        proposal_revision=1,
        input_fingerprint=proposal.input_fingerprint,
    )
    changed = HistoricalObjectiveService(factory).set_operational_count_inclusion(
        command_id=new_uuid4(),
        task_id=task.task_id,
        expected_inclusion_revision=0,
        included=False,
        reason_category="exclude provider-only historical work",
    )
    assert changed.outcome == "APPLIED"
    with ReadSnapshot(factory) as snapshot:
        inclusion = snapshot.connection.execute(
            "SELECT included,revision FROM task_operational_count_current "
            "WHERE task_id=?",
            (task.task_id,),
        ).fetchone()
        assert tuple(inclusion) == (0, 1)
        aggregate = snapshot.connection.execute(
            "SELECT execution_state,aggregate_outcome,"
            "included_task_count,excluded_task_count "
            "FROM objective_aggregate_projection WHERE objective_id=?",
            (accepted.objective_id,),
        ).fetchone()
        assert tuple(aggregate) == (
            "historical_structure",
            "excluded_from_operational_counts",
            0,
            1,
        )
        assert snapshot.connection.execute(
            "SELECT count(*) FROM task_execution_events WHERE task_id=?",
            (task.task_id,),
        ).fetchone()[0] == 0
        assert snapshot.connection.execute(
            "SELECT count(*) FROM task_outcome_events WHERE task_id=?",
            (task.task_id,),
        ).fetchone()[0] == 0
