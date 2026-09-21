from __future__ import annotations

from datetime import datetime, timezone

import pytest

from soma.foundation.errors import SomaError, ValidationError
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


def _epoch_seconds(value: datetime) -> int:
    assert value.tzinfo is timezone.utc and value.microsecond == 0
    epoch = datetime(1970, 1, 1, tzinfo=timezone.utc)
    delta = value - epoch
    return delta.days * 86_400 + delta.seconds


def test_t031_local_time_validation_is_offline_dst_safe_and_path_safe() -> None:
    galapagos = ObjectiveTimezoneService.validate_local_input(
        datetime(2026, 1, 15, 12, 0, 0),
        "Pacific/Galapagos",
    )
    assert galapagos == _epoch_seconds(
        datetime(2026, 1, 15, 18, 0, 0, tzinfo=timezone.utc)
    )

    ambiguous = datetime(2026, 11, 1, 1, 30, 0)
    with pytest.raises(SomaError) as missing_fold:
        ObjectiveTimezoneService.validate_local_input(
            ambiguous,
            "America/New_York",
        )
    assert missing_fold.value.code == "TIMEZONE_AMBIGUOUS_LOCAL_TIME"

    first = ObjectiveTimezoneService.validate_local_input(
        ambiguous,
        "America/New_York",
        0,
    )
    second = ObjectiveTimezoneService.validate_local_input(
        ambiguous,
        "America/New_York",
        1,
    )
    assert second - first == 3_600
    assert first == _epoch_seconds(
        datetime(2026, 11, 1, 5, 30, 0, tzinfo=timezone.utc)
    )
    assert second == _epoch_seconds(
        datetime(2026, 11, 1, 6, 30, 0, tzinfo=timezone.utc)
    )

    with pytest.raises(SomaError) as invalid_fold:
        ObjectiveTimezoneService.validate_local_input(
            ambiguous,
            "America/New_York",
            2,
        )
    assert invalid_fold.value.code == "TIMEZONE_AMBIGUOUS_LOCAL_TIME"

    with pytest.raises(SomaError) as nonexistent:
        ObjectiveTimezoneService.validate_local_input(
            datetime(2026, 3, 8, 2, 30, 0),
            "America/New_York",
        )
    assert nonexistent.value.code == "TIMEZONE_NONEXISTENT_LOCAL_TIME"

    with pytest.raises(SomaError) as path_like:
        ObjectiveTimezoneService.validate_local_input(
            datetime(2026, 1, 1, 0, 0, 0),
            "../UTC",
        )
    assert path_like.value.code == "TIMEZONE_UNKNOWN"

    with pytest.raises(ValidationError):
        ObjectiveTimezoneService.validate_local_input(
            datetime(2026, 1, 1, 0, 0, 0, 1),
            "America/Guayaquil",
        )
    with pytest.raises(ValidationError):
        ObjectiveTimezoneService.validate_local_input(
            datetime(2026, 1, 1, 0, 0, 0, tzinfo=timezone.utc),
            "America/Guayaquil",
        )
