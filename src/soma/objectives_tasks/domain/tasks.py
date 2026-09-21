from __future__ import annotations

from dataclasses import dataclass

from soma.foundation.errors import ValidationError

GROUPING_CLASSIFICATIONS = frozenset(
    {
        "ordinary_future",
        "unscheduled",
        "cancelled",
        "terminal_history",
        "started_or_protected",
        "competing_attempt",
        "plan_membership_mismatch",
        "historical_candidate",
    }
)


@dataclass(frozen=True, slots=True)
class TaskListCursor:
    unscheduled: int
    start_utc: int | None
    task_id: str

    def validate(self) -> "TaskListCursor":
        if self.unscheduled not in {0, 1}:
            raise ValidationError("Task cursor unscheduled discriminator is invalid")
        if self.unscheduled == 0 and (type(self.start_utc) is not int or self.start_utc < 0):
            raise ValidationError("scheduled Task cursor requires start_utc")
        if self.unscheduled == 1 and self.start_utc is not None:
            raise ValidationError("unscheduled Task cursor cannot carry start_utc")
        return self


__all__ = ["GROUPING_CLASSIFICATIONS", "TaskListCursor"]
