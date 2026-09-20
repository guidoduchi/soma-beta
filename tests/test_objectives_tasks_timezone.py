from __future__ import annotations

import pytest

from soma.foundation.errors import SomaError
from soma.foundation.identifiers import new_uuid4
from soma.foundation.persistence.uow import ReadSnapshot
from soma.objectives_tasks import AcceptedTaskSchedule, TaskPlanningService
from soma.objectives_tasks.queries.timezone import ObjectiveTimezoneQueryService
from soma.objectives_tasks.services.timezone import ObjectiveTimezoneService


def _factory(initialized_database):
    path, builder = initialized_database
    return builder(path)


def test_objective_timezone_default_write_replay_and_update(initialized_database) -> None:
    factory = _factory(initialized_database)
    query = ObjectiveTimezoneQueryService(factory)
    assert query.get() == {
        "iana_timezone": "America/Guayaquil",
        "source": "DEFAULT",
        "revision": None,
    }

    service = ObjectiveTimezoneService(factory)
    command_id = new_uuid4()
    first = service.set_timezone(
        command_id=command_id,
        new_timezone="Asia/Tokyo",
        base_revision=None,
    )
    assert first.iana_timezone == "Asia/Tokyo"
    assert first.revision == 1
    assert first.no_change is False
    replay = service.set_timezone(
        command_id=command_id,
        new_timezone="Asia/Tokyo",
        base_revision=None,
    )
    assert replay.replayed is True
    assert query.get() == {
        "iana_timezone": "Asia/Tokyo",
        "source": "PERSISTED",
        "revision": 1,
    }

    same = service.set_timezone(
        command_id=new_uuid4(),
        new_timezone="Asia/Tokyo",
        base_revision=1,
    )
    assert same.no_change is True
    assert same.revision == 1

    changed = service.set_timezone(
        command_id=new_uuid4(),
        new_timezone="Europe/Oslo",
        base_revision=1,
    )
    assert changed.revision == 2
    assert query.get()["revision"] == 2


def test_objective_timezone_rejects_unknown_and_never_rewrites_task_plan_utc(initialized_database) -> None:
    factory = _factory(initialized_database)
    task = TaskPlanningService(factory).create_local_task(
        command_id=new_uuid4(),
        local_task_name="Timezone stability",
        schedule=AcceptedTaskSchedule(
            start_utc=2_400_000_000,
            end_utc=2_400_003_600,
            scheduling_timezone_iana="America/Guayaquil",
        ),
    )
    with ReadSnapshot(factory) as snapshot:
        before = tuple(
            snapshot.connection.execute(
                "SELECT p.start_utc,p.end_utc,p.scheduling_timezone_iana "
                "FROM task_plan_current c JOIN task_plan_revisions p "
                "ON p.plan_revision_id=c.plan_revision_id WHERE c.task_id=?",
                (task.task_id,),
            ).fetchone()
        )

    service = ObjectiveTimezoneService(factory)
    service.set_timezone(
        command_id=new_uuid4(),
        new_timezone="Asia/Tokyo",
        base_revision=None,
    )
    with ReadSnapshot(factory) as snapshot:
        after = tuple(
            snapshot.connection.execute(
                "SELECT p.start_utc,p.end_utc,p.scheduling_timezone_iana "
                "FROM task_plan_current c JOIN task_plan_revisions p "
                "ON p.plan_revision_id=c.plan_revision_id WHERE c.task_id=?",
                (task.task_id,),
            ).fetchone()
        )
    assert after == before

    with pytest.raises(SomaError) as excinfo:
        service.set_timezone(
            command_id=new_uuid4(),
            new_timezone="Mars/Olympus_Mons",
            base_revision=1,
        )
    assert excinfo.value.code == "TIMEZONE_UNKNOWN"
