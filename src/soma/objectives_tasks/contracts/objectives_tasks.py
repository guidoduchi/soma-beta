from __future__ import annotations

from dataclasses import dataclass

from soma.foundation.application.command_boundary import CommandExecutionResult
from soma.foundation.errors import IntegrityFailure, SomaError, ValidationError
from soma.foundation.identifiers import require_uuid4


@dataclass(frozen=True, slots=True)
class AcceptedTaskSchedule:
    """Already-canonical schedule evidence accepted before the writer lock is acquired."""

    start_utc: int
    end_utc: int
    scheduling_timezone_iana: str

    def validate(self) -> "AcceptedTaskSchedule":
        if type(self.start_utc) is not int or self.start_utc < 0:
            raise SomaError("TASK_PLAN_INVALID_INTERVAL", "Task plan start must be a nonnegative UTC second")
        if type(self.end_utc) is not int or self.end_utc <= self.start_utc:
            raise SomaError("TASK_PLAN_INVALID_INTERVAL", "Task plan end must be after Task plan start")
        if not isinstance(self.scheduling_timezone_iana, str):
            raise SomaError("TIMEZONE_UNKNOWN", "accepted Task schedule requires an IANA timezone identifier")
        try:
            timezone_bytes = self.scheduling_timezone_iana.encode("utf-8", errors="strict")
        except UnicodeEncodeError as exc:
            raise SomaError("TIMEZONE_UNKNOWN", "accepted Task schedule timezone must be valid Unicode") from exc
        if (
            not timezone_bytes
            or len(timezone_bytes) > 255
            or "\x00" in self.scheduling_timezone_iana
            or "\r" in self.scheduling_timezone_iana
            or "\n" in self.scheduling_timezone_iana
        ):
            raise SomaError("TIMEZONE_UNKNOWN", "accepted Task schedule requires a bounded IANA timezone identifier")
        return self

    def semantic_payload(self) -> dict[str, object]:
        return {
            "start_utc": self.start_utc,
            "end_utc": self.end_utc,
            "scheduling_timezone_iana": self.scheduling_timezone_iana,
        }


@dataclass(frozen=True, slots=True)
class TaskMutationResult:
    outcome: str
    task_id: str
    task_no: str
    rfc_id: str
    task_revision: int
    assignment_revision: int
    plan_revision_id: str | None
    replayed: bool

    @property
    def no_change(self) -> bool:
        return self.outcome == "NO_CHANGE"


def task_mutation_result_from_execution(result: CommandExecutionResult) -> TaskMutationResult:
    expected_fields = {
        "outcome",
        "task_id",
        "task_no",
        "rfc_id",
        "task_revision",
        "assignment_revision",
        "plan_revision_id",
    }
    if (
        result.response_schema != "TaskMutationResultV1"
        or result.response_version != 1
        or not isinstance(result.response, dict)
        or set(result.response) != expected_fields
    ):
        raise IntegrityFailure("Task mutation replay result has the wrong response contract")
    response = result.response
    outcome = response.get("outcome")
    task_id = response.get("task_id")
    task_no = response.get("task_no")
    rfc_id = response.get("rfc_id")
    task_revision = response.get("task_revision")
    assignment_revision = response.get("assignment_revision")
    plan_revision_id = response.get("plan_revision_id")
    if outcome not in {"APPLIED", "NO_CHANGE"} or bool(result.no_change) != (outcome == "NO_CHANGE"):
        raise IntegrityFailure("Task mutation replay result has inconsistent outcome")
    try:
        if not isinstance(task_id, str) or not isinstance(rfc_id, str):
            raise ValidationError("Task mutation identity metadata must be UUID text")
        require_uuid4(task_id)
        require_uuid4(rfc_id)
        if plan_revision_id is not None:
            if not isinstance(plan_revision_id, str):
                raise ValidationError("Task plan revision identity must be UUID text")
            require_uuid4(plan_revision_id)
    except (ValidationError, TypeError, ValueError) as exc:
        raise IntegrityFailure("Task mutation replay result has invalid identity metadata") from exc
    if (
        not isinstance(task_no, str)
        or len(task_no) != 16
        or not task_no.startswith("TK")
        or any(character < "0" or character > "9" for character in task_no[2:])
    ):
        raise IntegrityFailure("Task mutation replay result has invalid WFM Task No")
    if type(task_revision) is not int or task_revision <= 0:
        raise IntegrityFailure("Task mutation replay result has invalid Task revision")
    if type(assignment_revision) is not int or assignment_revision <= 0:
        raise IntegrityFailure("Task mutation replay result has invalid assignment revision")
    return TaskMutationResult(
        outcome=str(outcome),
        task_id=task_id,
        task_no=task_no,
        rfc_id=rfc_id,
        task_revision=task_revision,
        assignment_revision=assignment_revision,
        plan_revision_id=plan_revision_id,
        replayed=result.replayed,
    )
