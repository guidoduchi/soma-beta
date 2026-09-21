from __future__ import annotations

import pytest

from soma.foundation.errors import ValidationError
from soma.foundation.identifiers import new_uuid4
from soma.objectives_tasks.services.task_execution import TaskExecutionService


def _factory(initialized_database):
    database_path, factory_for_path = initialized_database
    return factory_for_path(database_path)


def test_end_task_execution_rejects_nonpositive_revisions_and_noninteger_end_before_state_reads(
    initialized_database,
) -> None:
    service = TaskExecutionService(_factory(initialized_database))
    task_id = new_uuid4()

    invalid_requests = (
        {"task_revision": 0, "execution_revision": 1, "effective_end_utc": 1},
        {"task_revision": 1, "execution_revision": 0, "effective_end_utc": 1},
        {"task_revision": 1, "execution_revision": 1, "effective_end_utc": -1},
        {"task_revision": 1, "execution_revision": 1, "effective_end_utc": True},
        {"task_revision": 1, "execution_revision": 1, "effective_end_utc": "canonical-now"},
    )
    for request in invalid_requests:
        with pytest.raises(ValidationError):
            service.end_task_execution(
                command_id=new_uuid4(),
                task_id=task_id,
                **request,
            )
