from __future__ import annotations

from soma.foundation.identifiers import new_uuid4
from soma.foundation.persistence.uow import ReadSnapshot
from soma.objectives_tasks import AcceptedTaskSchedule, TaskPlanningService
from soma.objectives_tasks.queries.grouping import ObjectiveGroupingQueryService
from soma.objectives_tasks.services.grouping import GroupingService


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


def test_grouping_sweep_is_transitive_and_exact_touch_separates(initialized_database) -> None:
    factory = _factory(initialized_database)
    _task(factory, "A", 2_400_000_000, 2_400_000_100)
    _task(factory, "B", 2_400_000_050, 2_400_000_200)
    _task(factory, "C", 2_400_000_150, 2_400_000_250)
    _task(factory, "D", 2_400_000_250, 2_400_000_350)

    response = GroupingService(factory).recompute_grouping_proposals(
        command_id=new_uuid4(),
        origin="manual_request",
    )
    assert len(response["items"]) == 2
    details = [
        ObjectiveGroupingQueryService(factory).proposal_detail(item["proposal_id"])
        for item in response["items"]
    ]
    counts = sorted(detail["task_change_exact_count"] for detail in details)
    assert counts == [1, 3]
    assert all(detail["proposal_kind"] == "create" for detail in details)


def test_identical_rejected_grouping_input_is_suppressed_until_reconsidered(
    initialized_database,
) -> None:
    factory = _factory(initialized_database)
    _task(factory, "Solo", 2_500_000_000, 2_500_003_600)
    service = GroupingService(factory)
    first = service.recompute_grouping_proposals(
        command_id=new_uuid4(),
        origin="manual_request",
    )
    assert len(first["items"]) == 1
    item = first["items"][0]
    proposal_id = str(item["proposal_id"])
    fingerprint = str(item["input_fingerprint"])
    rejected = service.reject_regroup_proposal(
        command_id=new_uuid4(),
        proposal_id=proposal_id,
        proposal_revision=1,
        input_fingerprint=fingerprint,
        reason_category="operator_rejected",
    )
    assert rejected["state"] == "rejected"
    suppressed = service.recompute_grouping_proposals(
        command_id=new_uuid4(),
        origin="manual_request",
    )
    assert suppressed["items"] == []

    with ReadSnapshot(factory) as snapshot:
        rejection_id = str(
            snapshot.connection.execute(
                "SELECT rejection_event_id FROM regroup_rejection_events "
                "WHERE regroup_proposal_id=?",
                (proposal_id,),
            ).fetchone()[0]
        )
    service.reconsider_regroup_inputs(
        command_id=new_uuid4(),
        proposal_id=proposal_id,
        rejection_event_id=rejection_id,
        input_fingerprint=fingerprint,
        reason_category="reconsider",
    )
    fresh = service.recompute_grouping_proposals(
        command_id=new_uuid4(),
        origin="manual_request",
    )
    assert len(fresh["items"]) == 1


def test_accept_create_grouping_proposal_creates_nonoverlapping_objective(
    initialized_database,
) -> None:
    factory = _factory(initialized_database)
    first = _task(factory, "A", 2_600_000_000, 2_600_000_200)
    second = _task(factory, "B", 2_600_000_100, 2_600_000_300)
    service = GroupingService(factory)
    page = service.recompute_grouping_proposals(
        command_id=new_uuid4(),
        origin="manual_request",
    )
    assert len(page["items"]) == 1
    item = page["items"][0]
    accepted = service.accept_regroup_proposal(
        command_id=new_uuid4(),
        proposal_id=str(item["proposal_id"]),
        proposal_revision=1,
        input_fingerprint=str(item["input_fingerprint"]),
    )
    assert accepted["state"] == "accepted"
    with ReadSnapshot(factory) as snapshot:
        memberships = snapshot.connection.execute(
            "SELECT task_id,objective_id FROM objective_task_membership_current "
            "ORDER BY task_id"
        ).fetchall()
        objectives = snapshot.connection.execute(
            "SELECT objective_id,creation_origin,superseded_by_objective_id "
            "FROM objectives ORDER BY objective_id"
        ).fetchall()
    assert len(memberships) == 2
    assert {str(row[0]) for row in memberships} == {first.task_id, second.task_id}
    assert len({str(row[1]) for row in memberships}) == 1
    assert len(objectives) == 1
    assert str(objectives[0][1]) == "automatic_grouping"
