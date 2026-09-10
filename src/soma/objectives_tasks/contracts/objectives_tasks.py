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
class TaskResultRef:
    result_type: str
    result_id: str

    def to_response(self) -> dict[str, str]:
        return {"type": self.result_type, "id": self.result_id}


@dataclass(frozen=True, slots=True)
class TaskMutationResult:
    outcome: str
    task_id: str
    revision: int
    result_refs: tuple[TaskResultRef, ...]
    replayed: bool

    @property
    def no_change(self) -> bool:
        return self.outcome == "NO_CHANGE"


def _validate_ref_text(value: object, *, field: str, max_utf8_bytes: int) -> str:
    if not isinstance(value, str):
        raise IntegrityFailure(f"Task mutation {field} must be text")
    try:
        encoded = value.encode("utf-8", errors="strict")
    except UnicodeEncodeError as exc:
        raise IntegrityFailure(f"Task mutation {field} must be valid Unicode") from exc
    if not encoded or len(encoded) > max_utf8_bytes or "\x00" in value or "\r" in value or "\n" in value:
        raise IntegrityFailure(f"Task mutation {field} violates its bounded one-line contract")
    return value


def task_mutation_result_from_execution(result: CommandExecutionResult) -> TaskMutationResult:
    expected_fields = {"outcome", "task_id", "revision", "result_refs"}
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
    revision = response.get("revision")
    raw_refs = response.get("result_refs")
    if outcome not in {"APPLIED", "NO_CHANGE"} or bool(result.no_change) != (outcome == "NO_CHANGE"):
        raise IntegrityFailure("Task mutation replay result has inconsistent outcome")
    try:
        if not isinstance(task_id, str):
            raise ValidationError("task_id must be UUID text")
        require_uuid4(task_id)
    except ValidationError as exc:
        raise IntegrityFailure("Task mutation replay result has invalid Task identity") from exc
    if type(revision) is not int or revision <= 0:
        raise IntegrityFailure("Task mutation replay result has invalid Task revision")
    if not isinstance(raw_refs, list) or len(raw_refs) > 64:
        raise IntegrityFailure("Task mutation replay result refs are invalid")
    refs: list[TaskResultRef] = []
    seen: set[tuple[str, str]] = set()
    for raw in raw_refs:
        if not isinstance(raw, dict) or set(raw) != {"type", "id"}:
            raise IntegrityFailure("Task mutation result ref has the wrong shape")
        result_type = _validate_ref_text(raw.get("type"), field="result ref type", max_utf8_bytes=128)
        result_id = _validate_ref_text(raw.get("id"), field="result ref id", max_utf8_bytes=1024)
        identity = (result_type, result_id)
        if identity in seen:
            raise IntegrityFailure("Task mutation result refs contain a duplicate")
        seen.add(identity)
        refs.append(TaskResultRef(result_type, result_id))
    if outcome == "NO_CHANGE" and refs:
        raise IntegrityFailure("Task mutation NO_CHANGE response cannot claim material result refs")
    if outcome == "APPLIED":
        if not isinstance(result.result_type, str) or not isinstance(result.result_id, str):
            raise IntegrityFailure("Task mutation material receipt is missing result identity")
        if (result.result_type, result.result_id) not in seen:
            raise IntegrityFailure("Task mutation response does not include its material receipt result")
    return TaskMutationResult(
        outcome=str(outcome),
        task_id=task_id,
        revision=revision,
        result_refs=tuple(refs),
        replayed=result.replayed,
    )
