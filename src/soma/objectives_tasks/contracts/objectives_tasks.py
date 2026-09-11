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


@dataclass(frozen=True, slots=True)
class ObjectiveMutationResult:
    outcome: str
    objective_id: str
    revision: int
    result_refs: tuple[TaskResultRef, ...]
    replayed: bool

    @property
    def no_change(self) -> bool:
        return self.outcome == "NO_CHANGE"


@dataclass(frozen=True, slots=True)
class WfmActivityRelationshipReviewResult:
    outcome: str
    decision: str
    review_fingerprint: str
    affected_task_count: int
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


def _parse_result_refs(raw_refs: object, *, max_items: int) -> tuple[TaskResultRef, ...]:
    if not isinstance(raw_refs, list) or len(raw_refs) > max_items:
        raise IntegrityFailure("Task mutation result refs are invalid")
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
    return tuple(refs)


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
    refs = _parse_result_refs(response.get("result_refs"), max_items=64)
    if outcome == "NO_CHANGE" and refs:
        raise IntegrityFailure("Task mutation NO_CHANGE response cannot claim material result refs")
    if outcome == "APPLIED":
        if not isinstance(result.result_type, str) or not isinstance(result.result_id, str):
            raise IntegrityFailure("Task mutation material receipt is missing result identity")
        if (result.result_type, result.result_id) not in {(ref.result_type, ref.result_id) for ref in refs}:
            raise IntegrityFailure("Task mutation response does not include its material receipt result")
    return TaskMutationResult(
        outcome=str(outcome),
        task_id=task_id,
        revision=revision,
        result_refs=refs,
        replayed=result.replayed,
    )


def objective_mutation_result_from_execution(result: CommandExecutionResult) -> ObjectiveMutationResult:
    expected_fields = {"outcome", "objective_id", "revision", "result_refs"}
    if (
        result.response_schema != "ObjectiveMutationResultV1"
        or result.response_version != 1
        or not isinstance(result.response, dict)
        or set(result.response) != expected_fields
    ):
        raise IntegrityFailure("Objective mutation replay result has the wrong response contract")
    response = result.response
    outcome = response.get("outcome")
    objective_id = response.get("objective_id")
    revision = response.get("revision")
    if outcome not in {"APPLIED", "NO_CHANGE"} or bool(result.no_change) != (outcome == "NO_CHANGE"):
        raise IntegrityFailure("Objective mutation replay result has inconsistent outcome")
    try:
        if not isinstance(objective_id, str):
            raise ValidationError("objective_id must be UUID text")
        require_uuid4(objective_id)
    except ValidationError as exc:
        raise IntegrityFailure("Objective mutation replay result has invalid Objective identity") from exc
    if type(revision) is not int or revision <= 0:
        raise IntegrityFailure("Objective mutation replay result has invalid Objective revision")
    refs = _parse_result_refs(response.get("result_refs"), max_items=100)
    if outcome == "NO_CHANGE" and refs:
        raise IntegrityFailure("Objective mutation NO_CHANGE response cannot claim material result refs")
    if outcome == "APPLIED":
        if not isinstance(result.result_type, str) or not isinstance(result.result_id, str):
            raise IntegrityFailure("Objective mutation material receipt is missing result identity")
        if (result.result_type, result.result_id) not in {(ref.result_type, ref.result_id) for ref in refs}:
            raise IntegrityFailure("Objective mutation response does not include its material receipt result")
    return ObjectiveMutationResult(
        outcome=str(outcome),
        objective_id=objective_id,
        revision=revision,
        result_refs=refs,
        replayed=result.replayed,
    )


def wfm_activity_review_result_from_execution(
    result: CommandExecutionResult,
) -> WfmActivityRelationshipReviewResult:
    expected_fields = {
        "outcome",
        "decision",
        "review_fingerprint",
        "affected_task_count",
        "result_refs",
    }
    if (
        result.response_schema != "WfmActivityRelationshipReviewResultV1"
        or result.response_version != 1
        or not isinstance(result.response, dict)
        or set(result.response) != expected_fields
    ):
        raise IntegrityFailure("WFM activity-review replay result has the wrong response contract")
    response = result.response
    outcome = response.get("outcome")
    decision = response.get("decision")
    review_fingerprint = response.get("review_fingerprint")
    affected_task_count = response.get("affected_task_count")
    if outcome not in {"APPLIED", "NO_CHANGE"} or bool(result.no_change) != (outcome == "NO_CHANGE"):
        raise IntegrityFailure("WFM activity-review replay result has inconsistent outcome")
    if decision not in {
        "distinct_activity",
        "same_activity",
        "retry_lineage",
        "unresolved_source_error",
    }:
        raise IntegrityFailure("WFM activity-review replay result has invalid decision")
    if (
        not isinstance(review_fingerprint, str)
        or len(review_fingerprint) != 64
        or any(character not in "0123456789abcdef" for character in review_fingerprint)
    ):
        raise IntegrityFailure("WFM activity-review replay result has invalid fingerprint")
    if type(affected_task_count) is not int or affected_task_count < 2:
        raise IntegrityFailure("WFM activity-review replay result has invalid affected Task count")
    refs = _parse_result_refs(response.get("result_refs"), max_items=8)
    for ref in refs:
        if ref.result_type not in {"task_activity_lineage_event", "task_activity_lineage"}:
            raise IntegrityFailure("WFM activity-review replay result contains an unsupported result ref type")
        try:
            require_uuid4(ref.result_id)
        except ValidationError as exc:
            raise IntegrityFailure("WFM activity-review replay result contains invalid result identity") from exc
    if outcome == "NO_CHANGE":
        if refs or result.result_id is not None or result.result_type not in {None, "NO_CHANGE"}:
            raise IntegrityFailure("WFM activity-review NO_CHANGE result claims material authority")
    else:
        if not isinstance(result.result_type, str) or not isinstance(result.result_id, str):
            raise IntegrityFailure("WFM activity-review material receipt is missing result identity")
        if (result.result_type, result.result_id) not in {(ref.result_type, ref.result_id) for ref in refs}:
            raise IntegrityFailure("WFM activity-review response does not include its material receipt result")
    return WfmActivityRelationshipReviewResult(
        outcome=str(outcome),
        decision=str(decision),
        review_fingerprint=review_fingerprint,
        affected_task_count=affected_task_count,
        result_refs=refs,
        replayed=result.replayed,
    )