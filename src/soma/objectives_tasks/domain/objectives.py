from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

from soma.foundation.errors import ValidationError
from soma.foundation.identifiers import require_uuid4
from soma.objectives_tasks.contracts.objectives_tasks import AcceptedTaskSchedule
from soma.objectives_tasks.services.task_planning import validate_local_task_name


_MAX_RELATIONSHIPS = 62


def _ids(values: Sequence[str], field: str) -> tuple[str, ...]:
    if isinstance(values, (str, bytes)) or not isinstance(values, Sequence):
        raise ValidationError(f"{field} must be a sequence")
    result: list[str] = []
    seen: set[str] = set()
    for raw in values:
        if not isinstance(raw, str):
            raise ValidationError(f"{field} must contain UUID text")
        value = require_uuid4(raw)
        if value in seen:
            raise ValidationError(f"{field} contains a duplicate")
        seen.add(value)
        result.append(value)
    result.sort()
    return tuple(result)


@dataclass(frozen=True, slots=True)
class ObjectiveExistingTaskIntent:
    task_id: str
    expected_task_revision: int
    expected_plan_revision: int
    expected_plan_revision_id: str

    def validate(self) -> "ObjectiveExistingTaskIntent":
        task_id = require_uuid4(self.task_id)
        plan_id = require_uuid4(self.expected_plan_revision_id)
        if type(self.expected_task_revision) is not int or self.expected_task_revision <= 0:
            raise ValidationError("expected_task_revision must be positive")
        if type(self.expected_plan_revision) is not int or self.expected_plan_revision <= 0:
            raise ValidationError("expected_plan_revision must be positive")
        return ObjectiveExistingTaskIntent(
            task_id=task_id,
            expected_task_revision=self.expected_task_revision,
            expected_plan_revision=self.expected_plan_revision,
            expected_plan_revision_id=plan_id,
        )


@dataclass(frozen=True, slots=True)
class ObjectiveDraftLocalTaskIntent:
    local_task_name: str
    schedule: AcceptedTaskSchedule
    service_request_ids: tuple[str, ...] = ()
    rfc_ids: tuple[str, ...] = ()
    device_reference_ids: tuple[str, ...] = ()

    def validate(self) -> "ObjectiveDraftLocalTaskIntent":
        name = validate_local_task_name(self.local_task_name)
        if not isinstance(self.schedule, AcceptedTaskSchedule):
            raise ValidationError("draft Objective Task requires AcceptedTaskSchedule")
        schedule = self.schedule.validate()
        sr_ids = _ids(self.service_request_ids, "service_request_ids")
        rfc_ids = _ids(self.rfc_ids, "rfc_ids")
        device_ids = _ids(self.device_reference_ids, "device_reference_ids")
        if len(sr_ids) + len(rfc_ids) + len(device_ids) > _MAX_RELATIONSHIPS:
            raise ValidationError("draft Objective Task has too many initial relationships")
        return ObjectiveDraftLocalTaskIntent(
            local_task_name=name,
            schedule=schedule,
            service_request_ids=sr_ids,
            rfc_ids=rfc_ids,
            device_reference_ids=device_ids,
        )

    def semantic_value(self) -> dict[str, object]:
        validated = self.validate()
        return {
            "local_task_name": validated.local_task_name,
            "schedule": validated.schedule.semantic_payload(),
            "relationships": {
                "service_request_ids": list(validated.service_request_ids),
                "rfc_ids": list(validated.rfc_ids),
                "device_reference_ids": list(validated.device_reference_ids),
            },
        }


__all__ = ["ObjectiveDraftLocalTaskIntent", "ObjectiveExistingTaskIntent"]
