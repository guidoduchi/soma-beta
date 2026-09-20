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
