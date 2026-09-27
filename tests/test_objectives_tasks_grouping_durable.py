from __future__ import annotations

import inspect

import pytest

from soma.foundation.errors import JobClaimConflict, SomaError
from soma.foundation.identifiers import new_uuid4, utc_epoch_seconds
from soma.foundation.jobs import DurableJobCoordinator, JobTypeRegistry
from soma.foundation.persistence.uow import ReadSnapshot, UnitOfWork
from soma.objectives_tasks import AcceptedTaskSchedule, TaskPlanningService
from soma.objectives_tasks.domain.objectives import ObjectiveExistingTaskIntent
from soma.objectives_tasks.jobs import OBJECTIVES_TASKS_JOB_CONTRACTS
from soma.objectives_tasks.jobs.grouping_recompute import ObjectiveGroupingRecomputeWorker
from soma.objectives_tasks.queries.grouping import ObjectiveGroupingQueryService
from soma.objectives_tasks.repositories.grouping import RegroupProposalRepository
from soma.objectives_tasks.services.grouping import GroupingService
from soma.objectives_tasks.services.objectives import ObjectiveService


TZ = "America/Guayaquil"


def _factory(initialized_database):
    path, builder = initialized_database
    return builder(path)


def _task(factory, name: str, start: int, end: int):
    return TaskPlanningService(factory).create_local_task(
        command_id=new_uuid4(),
        local_task_name=name,
        schedule=AcceptedTaskSchedule(
            start_utc=start,
            end_utc=end,
            scheduling_timezone_iana=TZ,
        ),
    )


def _coordinator(factory, *, clock=None):
    kwargs = {} if clock is None else {"clock": clock}
    return DurableJobCoordinator(
        factory,
        JobTypeRegistry(OBJECTIVES_TASKS_JOB_CONTRACTS),
        **kwargs,
    )


def test_t039_large_threshold_uses_durable_job_and_replay_precedes_owner_reads(
    initialized_database,
    monkeypatch,
) -> None:
    factory = _factory(initialized_database)
    _task(factory, "Threshold A", 2_810_000_000, 2_810_000_100)
    _task(factory, "Threshold B", 2_810_000_200, 2_810_000_300)
    monkeypatch.setattr(
        GroupingService,
        "_eligible_workset_count",
        staticmethod(lambda _reader: 100_001),
    )

    service = GroupingService(factory)
    command_id = new_uuid4()
    first = service.recompute_grouping_proposals(
        command_id=command_id,
        origin="manual_request",
    )
    assert first["execution_mode"] == "durable_job"
    assert first["job_id"] is not None
    assert first["proposals"] == {
        "items": [],
        "continuation": None,
        "exact_total": 0,
    }

    monkeypatch.setattr(
        GroupingService,
        "_eligible_workset_count",
        staticmethod(lambda _reader: pytest.fail("replay read mutable grouping authority")),
    )
    assert service.recompute_grouping_proposals(
        command_id=command_id,
        origin="manual_request",
    ) == first
    with pytest.raises(SomaError) as collision:
        service.recompute_grouping_proposals(
            command_id=command_id,
            origin="task_created",
        )
    assert collision.value.code == "IDEMPOTENCY_CONFLICT"

    with ReadSnapshot(factory) as snapshot:
        assert snapshot.connection.execute(
            "SELECT COUNT(*) FROM durable_jobs WHERE job_id=?",
            (first["job_id"],),
        ).fetchone()[0] == 1
        assert snapshot.connection.execute(
            "SELECT COUNT(*) FROM audit_events "
            "WHERE command_id=? AND action_type='grouping.recompute_deferred'",
            (command_id,),
        ).fetchone()[0] == 1


def test_t039_active_recompute_requests_coalesce_by_origin(
    initialized_database,
    monkeypatch,
) -> None:
    factory = _factory(initialized_database)
    _task(factory, "Coalesce", 2_811_000_000, 2_811_000_100)
    monkeypatch.setattr(
        GroupingService,
        "_eligible_workset_count",
        staticmethod(lambda _reader: 100_001),
    )
    service = GroupingService(factory)

    first = service.recompute_grouping_proposals(
        command_id=new_uuid4(),
        origin="manual_request",
    )
    second = service.recompute_grouping_proposals(
        command_id=new_uuid4(),
        origin="manual_request",
    )
    assert first["execution_mode"] == second["execution_mode"] == "durable_job"
    assert first["job_id"] == second["job_id"]
    with ReadSnapshot(factory) as snapshot:
        assert snapshot.connection.execute(
            "SELECT COUNT(*) FROM durable_jobs "
            "WHERE job_type='OBJECTIVE_GROUPING_RECOMPUTE_V1'",
        ).fetchone()[0] == 1


def test_t039_worker_can_publish_snapshot_candidate_that_becomes_stale_after_drift(
    initialized_database,
    monkeypatch,
) -> None:
    factory = _factory(initialized_database)
    _task(factory, "Snapshot A", 2_812_000_000, 2_812_000_200)
    monkeypatch.setattr(
        GroupingService,
        "_eligible_workset_count",
        staticmethod(lambda _reader: 100_001),
    )
    service = GroupingService(factory)
    deferred = service.recompute_grouping_proposals(
        command_id=new_uuid4(),
        origin="manual_request",
    )

    with ReadSnapshot(factory) as snapshot:
        frozen = GroupingService._candidates(
            snapshot.connection,
            origin="manual_request",
        )
    assert len(frozen) == 1

    _task(factory, "Snapshot drift", 2_812_000_100, 2_812_000_300)
    coordinator = _coordinator(factory)
    claim = coordinator.claim_next(new_uuid4(), utc_epoch_seconds())
    assert claim is not None
    assert claim.job_id == deferred["job_id"]
    with monkeypatch.context() as worker_patch:
        worker_patch.setattr(
            GroupingService,
            "_candidates",
            classmethod(lambda _cls, _reader, *, origin: frozen),
        )
        result = ObjectiveGroupingRecomputeWorker(factory).run(claim)
    assert result.published_proposal_count == 1

    page = ObjectiveGroupingQueryService(factory).list_proposals(limit=10)
    assert page["exact_total"] == 1
    proposal_id = str(page["items"][0]["proposal_id"])
    detail = ObjectiveGroupingQueryService(factory).proposal_detail(proposal_id)
    assert detail["stale"] is True
    with pytest.raises(SomaError) as stale:
        service.accept_regroup_proposal(
            command_id=new_uuid4(),
            proposal_id=proposal_id,
            proposal_revision=1,
            input_fingerprint=str(detail["input_fingerprint"]),
        )
    assert stale.value.code == "GROUPING_PROPOSAL_STALE"


def test_t039_cancelled_job_revokes_worker_claim_without_domain_mutation(
    initialized_database,
    monkeypatch,
) -> None:
    factory = _factory(initialized_database)
    _task(factory, "Cancel durable grouping", 2_813_000_000, 2_813_000_100)
    monkeypatch.setattr(
        GroupingService,
        "_eligible_workset_count",
        staticmethod(lambda _reader: 100_001),
    )
    deferred = GroupingService(factory).recompute_grouping_proposals(
        command_id=new_uuid4(),
        origin="manual_request",
    )

    coordinator = _coordinator(factory)
    claim = coordinator.claim_next(new_uuid4(), utc_epoch_seconds())
    assert claim is not None and claim.job_id == deferred["job_id"]
    with UnitOfWork(factory) as uow:
        cancelled = coordinator.cancel(
            uow,
            claim.job_id,
            "OBJECTIVE_GROUPING_RECOMPUTE_V1",
            1,
            {"command_id": new_uuid4()},
        )
    assert cancelled.outcome == "CANCELLED"
    with pytest.raises(JobClaimConflict):
        ObjectiveGroupingRecomputeWorker(factory).run(claim)
    with ReadSnapshot(factory) as snapshot:
        assert snapshot.connection.execute(
            "SELECT COUNT(*) FROM regroup_proposals",
        ).fetchone()[0] == 0


def test_t039_publication_failure_rolls_back_and_retry_publishes_once(
    initialized_database,
    monkeypatch,
) -> None:
    factory = _factory(initialized_database)
    _task(factory, "Retry durable grouping", 2_814_000_000, 2_814_000_100)
    monkeypatch.setattr(
        GroupingService,
        "_eligible_workset_count",
        staticmethod(lambda _reader: 100_001),
    )
    deferred = GroupingService(factory).recompute_grouping_proposals(
        command_id=new_uuid4(),
        origin="manual_request",
    )

    coordinator = _coordinator(factory)
    claim = coordinator.claim_next(new_uuid4(), utc_epoch_seconds())
    assert claim is not None and claim.job_id == deferred["job_id"]
    original_insert = RegroupProposalRepository.insert_candidate

    with monkeypatch.context() as local_patch:
        def fail_after_insert(cls, connection, *, candidate, command_id):
            original_insert(
                connection,
                candidate=candidate,
                command_id=command_id,
            )
            raise RuntimeError("injected publication failure")

        local_patch.setattr(
            RegroupProposalRepository,
            "insert_candidate",
            classmethod(fail_after_insert),
        )
        with pytest.raises(RuntimeError, match="injected publication failure"):
            ObjectiveGroupingRecomputeWorker(factory).run(claim)

    with ReadSnapshot(factory) as snapshot:
        assert snapshot.connection.execute(
            "SELECT COUNT(*) FROM regroup_proposals",
        ).fetchone()[0] == 0

    failure_now = max(utc_epoch_seconds(), claim.claim_started_at_utc)
    retry_at = failure_now + 5
    failing = _coordinator(factory, clock=lambda: failure_now)
    failing.fail(claim, "PERSISTENCE_BUSY", retry_at)
    retry_claim = coordinator.claim_next(new_uuid4(), retry_at)
    assert retry_claim is not None
    assert retry_claim.job_id == claim.job_id
    retried = ObjectiveGroupingRecomputeWorker(
        factory,
        clock=lambda: retry_at,
    ).run(retry_claim)
    assert retried.published_proposal_count == 1
    with ReadSnapshot(factory) as snapshot:
        assert snapshot.connection.execute(
            "SELECT COUNT(*) FROM regroup_proposals",
        ).fetchone()[0] == 1


def test_t039_grouping_proposal_page_exact_total_is_independent_of_page_length(
    initialized_database,
) -> None:
    factory = _factory(initialized_database)
    _task(factory, "Page A", 2_815_000_000, 2_815_000_100)
    _task(factory, "Page B", 2_815_000_200, 2_815_000_300)
    result = GroupingService(factory).recompute_grouping_proposals(
        command_id=new_uuid4(),
        origin="manual_request",
    )
    assert result["execution_mode"] == "synchronous"
    assert result["proposals"]["exact_total"] == 2

    page = ObjectiveGroupingQueryService(factory).list_proposals(limit=1)
    assert len(page["items"]) == 1
    assert page["exact_total"] == 2
    assert page["continuation"] is not None


def test_t039_candidate_builder_has_no_component_times_full_workset_scan() -> None:
    source = inspect.getsource(GroupingService._candidates)
    assert "for objective in snapshot.objectives.values()" not in source
    assert "for task in snapshot.tasks\n                    if task.task_id" not in source
    assert "members_by_objective" in source
    assert "objective_cursor" in source

def test_lld05_f005_committed_plan_survives_durable_grouping_publication_crash(
    initialized_database,
    monkeypatch,
) -> None:
    factory = _factory(initialized_database)
    task = _task(
        factory,
        "F005 committed plan",
        2_816_000_000,
        2_816_000_100,
    )
    with ReadSnapshot(factory) as snapshot:
        before = snapshot.connection.execute(
            "SELECT t.revision,c.revision,c.plan_revision_id,p.start_utc,p.end_utc "
            "FROM tasks t JOIN task_plan_current c ON c.task_id=t.task_id "
            "JOIN task_plan_revisions p ON p.plan_revision_id=c.plan_revision_id "
            "WHERE t.task_id=?",
            (task.task_id,),
        ).fetchone()
    assert before is not None
    intent = ObjectiveExistingTaskIntent(
        task_id=task.task_id,
        expected_task_revision=int(before[0]),
        expected_plan_revision=int(before[1]),
        expected_plan_revision_id=str(before[2]),
    )
    creation = ObjectiveGroupingQueryService(factory).creation_preview(
        existing_tasks=(intent,),
    )
    assert creation["mode"] == "CREATE"
    objective = ObjectiveService(factory).create_objective_from_preview(
        command_id=new_uuid4(),
        preview_fingerprint=str(creation["fingerprint"]),
        existing_tasks=(intent,),
    )

    with ReadSnapshot(factory) as snapshot:
        membership_before = tuple(
            snapshot.connection.execute(
                "SELECT accepted_plan_revision_id,membership_revision,last_event_id "
                "FROM objective_task_membership_current WHERE task_id=?",
                (task.task_id,),
            ).fetchone()
        )
        envelope_before = tuple(
            snapshot.connection.execute(
                "SELECT start_utc,end_utc,revision,membership_input_fingerprint "
                "FROM objective_envelope_projection WHERE objective_id=?",
                (objective.objective_id,),
            ).fetchone()
        )

    changed = TaskPlanningService(factory).set_task_plan(
        command_id=new_uuid4(),
        task_id=task.task_id,
        task_revision=int(before[0]),
        current_plan_revision=int(before[1]),
        schedule=AcceptedTaskSchedule(
            start_utc=2_816_001_000,
            end_utc=2_816_001_100,
            scheduling_timezone_iana=TZ,
        ),
        reason_category="f005_plan_change",
    )
    assert changed.outcome == "APPLIED"

    with ReadSnapshot(factory) as snapshot:
        current_plan = tuple(
            snapshot.connection.execute(
                "SELECT c.plan_revision_id,c.revision,p.start_utc,p.end_utc "
                "FROM task_plan_current c JOIN task_plan_revisions p "
                "ON p.plan_revision_id=c.plan_revision_id WHERE c.task_id=?",
                (task.task_id,),
            ).fetchone()
        )
        assert current_plan[0] != membership_before[0]
        assert tuple(current_plan[2:4]) == (2_816_001_000, 2_816_001_100)
        assert tuple(
            snapshot.connection.execute(
                "SELECT accepted_plan_revision_id,membership_revision,last_event_id "
                "FROM objective_task_membership_current WHERE task_id=?",
                (task.task_id,),
            ).fetchone()
        ) == membership_before
        assert tuple(
            snapshot.connection.execute(
                "SELECT start_utc,end_utc,revision,membership_input_fingerprint "
                "FROM objective_envelope_projection WHERE objective_id=?",
                (objective.objective_id,),
            ).fetchone()
        ) == envelope_before

    monkeypatch.setattr(
        GroupingService,
        "_eligible_workset_count",
        staticmethod(lambda _reader: 100_001),
    )
    deferred = GroupingService(factory).recompute_grouping_proposals(
        command_id=new_uuid4(),
        origin="task_plan_changed",
    )
    assert deferred["execution_mode"] == "durable_job"

    coordinator = _coordinator(factory)
    claim = coordinator.claim_next(new_uuid4(), utc_epoch_seconds())
    assert claim is not None and claim.job_id == deferred["job_id"]
    original_insert = RegroupProposalRepository.insert_candidate

    with monkeypatch.context() as local_patch:
        def fail_after_insert(cls, connection, *, candidate, command_id):
            original_insert(
                connection,
                candidate=candidate,
                command_id=command_id,
            )
            raise RuntimeError("LLD05-F005 injected publication crash")

        local_patch.setattr(
            RegroupProposalRepository,
            "insert_candidate",
            classmethod(fail_after_insert),
        )
        with pytest.raises(RuntimeError, match="LLD05-F005"):
            ObjectiveGroupingRecomputeWorker(factory).run(claim)

    with ReadSnapshot(factory) as snapshot:
        assert tuple(
            snapshot.connection.execute(
                "SELECT c.plan_revision_id,c.revision,p.start_utc,p.end_utc "
                "FROM task_plan_current c JOIN task_plan_revisions p "
                "ON p.plan_revision_id=c.plan_revision_id WHERE c.task_id=?",
                (task.task_id,),
            ).fetchone()
        ) == current_plan
        assert tuple(
            snapshot.connection.execute(
                "SELECT accepted_plan_revision_id,membership_revision,last_event_id "
                "FROM objective_task_membership_current WHERE task_id=?",
                (task.task_id,),
            ).fetchone()
        ) == membership_before
        assert tuple(
            snapshot.connection.execute(
                "SELECT start_utc,end_utc,revision,membership_input_fingerprint "
                "FROM objective_envelope_projection WHERE objective_id=?",
                (objective.objective_id,),
            ).fetchone()
        ) == envelope_before
        assert snapshot.connection.execute(
            "SELECT COUNT(*) FROM regroup_proposals",
        ).fetchone()[0] == 0

    failure_now = max(utc_epoch_seconds(), claim.claim_started_at_utc)
    retry_at = failure_now + 5
    _coordinator(factory, clock=lambda: failure_now).fail(
        claim,
        "PERSISTENCE_BUSY",
        retry_at,
    )
    retry_claim = coordinator.claim_next(new_uuid4(), retry_at)
    assert retry_claim is not None and retry_claim.job_id == claim.job_id
    retried = ObjectiveGroupingRecomputeWorker(
        factory,
        clock=lambda: retry_at,
    ).run(retry_claim)
    assert retried.published_proposal_count == 1

    page = ObjectiveGroupingQueryService(factory).list_proposals(limit=10)
    assert page["exact_total"] == 1
    detail = ObjectiveGroupingQueryService(factory).proposal_detail(
        str(page["items"][0]["proposal_id"])
    )
    assert detail["stale"] is False

