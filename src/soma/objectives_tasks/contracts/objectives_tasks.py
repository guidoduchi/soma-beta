from __future__ import annotations

from dataclasses import dataclass
from collections.abc import Mapping
from typing import Literal, TypedDict

from soma.foundation.application.command_boundary import CommandExecutionResult
from soma.foundation.errors import IntegrityFailure, SomaError, ValidationError
from soma.foundation.identifiers import require_uuid4
from soma.foundation.strict_json import canonical_json_bytes_bounded


class TaskRelationshipListItemV1(TypedDict):
    kind: Literal["sr", "rfc", "device"]
    relationship_id: str
    related_id: str


class TaskRelationshipPageV1(TypedDict):
    items: list[TaskRelationshipListItemV1]
    continuation: dict[str, object] | None
    exact_total: int


class TaskAttentionListItemV1(TypedDict):
    kind: Literal["source_terminal", "regroup", "historical"]
    item_id: str
    revision: int
    created_at_utc: int
    input_fingerprint: str


class TaskAttentionPageV1(TypedDict):
    items: list[TaskAttentionListItemV1]
    continuation: dict[str, object] | None
    exact_total: int


@dataclass(frozen=True, slots=True)
class TaskRelationshipListQueryV1:
    cursor: dict[str, object] | None = None
    limit: int = 100

    @classmethod
    def from_value(cls, value: Mapping[str, object]) -> "TaskRelationshipListQueryV1":
        if not isinstance(value, Mapping) or set(value) - {"cursor", "limit"}:
            raise ValidationError("Task relationship query has unknown fields")
        canonical_json_bytes_bounded(dict(value), max_bytes=4096, max_depth=32, max_collection_items=64)
        result = cls(**dict(value))
        if type(result.limit) is not int or not 1 <= result.limit <= 500:
            raise ValidationError("Task collection limit must be in 1..500")
        return result


@dataclass(frozen=True, slots=True)
class TaskAttentionListQueryV1:
    kind: str | None = None
    cursor: dict[str, object] | None = None
    limit: int = 100

    @classmethod
    def from_value(cls, value: Mapping[str, object]) -> "TaskAttentionListQueryV1":
        if not isinstance(value, Mapping) or set(value) - {"kind", "cursor", "limit"}:
            raise ValidationError("Task attention query has unknown fields")
        TaskRelationshipListQueryV1.from_value({key: val for key, val in value.items() if key != "kind"})
        result = cls(**dict(value))
        if result.kind is not None and (not isinstance(result.kind, str) or result.kind not in {"source_terminal", "regroup", "historical"}):
            raise ValidationError("Task attention kind is invalid")
        return result


@dataclass(frozen=True, slots=True)
class GroupingProposalListQueryV1:
    """Accepted owner list request; internal raw keyset fields are not public."""

    state: str | None = None
    risk: str | None = None
    origin: str | None = None
    cursor: dict[str, object] | None = None
    limit: int = 100

    @classmethod
    def from_value(cls, value: Mapping[str, object]) -> "GroupingProposalListQueryV1":
        if not isinstance(value, Mapping) or set(value) - {"state", "risk", "origin", "cursor", "limit"}:
            raise ValidationError("grouping list request has unknown fields")
        payload = dict(value)
        canonical_json_bytes_bounded(payload, max_bytes=4096, max_depth=4096, max_collection_items=4096)
        return cls(**payload)


@dataclass(frozen=True, slots=True)
class GroupingProposalListItemV1:
    """Closed owner list facts, distinct from mutation GroupingProposalV1."""

    proposal_id: str
    revision: int
    proposal_kind: str
    risk_tier: str
    origin: str
    state: str
    input_fingerprint: str
    affected_task_exact_count: int
    affected_objective_exact_count: int
    owner_warnings: tuple[str, ...]
    created_at_utc: int

    def to_response(self) -> dict[str, object]:
        require_uuid4(self.proposal_id)
        if (type(self.revision) is not int or self.revision < 1
                or any(type(value) is not int or value < 0 for value in (
                    self.affected_task_exact_count, self.affected_objective_exact_count, self.created_at_utc))
                or self.proposal_kind not in {"create", "join", "move", "repin", "consolidate", "manual_merge", "manual_split"}
                or self.risk_tier not in {"normal", "high"}
                or self.origin not in {"task_created", "task_plan_changed", "source_plan_adopted", "manual_request", "retry_created", "objective_edit"}
                or self.state not in {"pending", "accepted", "rejected", "superseded"}
                or len(self.input_fingerprint) != 64 or any(char not in "0123456789abcdef" for char in self.input_fingerprint)
                or len(set(self.owner_warnings)) != len(self.owner_warnings)
                or any(code not in {"GROUPING_PROPOSAL_STALE", "GROUPING_EQUIVALENT_REJECTION"} for code in self.owner_warnings)):
            raise IntegrityFailure("Invalid owner grouping list projection")
        return {
            "proposal_id": self.proposal_id, "revision": self.revision, "proposal_kind": self.proposal_kind,
            "risk_tier": self.risk_tier, "origin": self.origin, "state": self.state,
            "input_fingerprint": self.input_fingerprint, "affected_task_exact_count": self.affected_task_exact_count,
            "affected_objective_exact_count": self.affected_objective_exact_count, "owner_warnings": list(self.owner_warnings),
            "created_at_utc": self.created_at_utc,
            "diff": {"proposal_kind": self.proposal_kind, "origin": self.origin, "risk_tier": self.risk_tier,
                     "task_change_count": self.affected_task_exact_count, "objective_change_count": self.affected_objective_exact_count},
        }


@dataclass(frozen=True, slots=True)
class GroupingRecomputeProposalV1:
    """Immutable commit-time proposal facts; never contains live classification."""

    proposal_id: str
    revision: int
    input_fingerprint: str
    state: str
    proposal_kind: str
    origin: str
    risk_tier: str
    affected_task_exact_count: int
    affected_objective_exact_count: int

    def to_response(self) -> dict[str, object]:
        require_uuid4(self.proposal_id)
        if (type(self.revision) is not int or self.revision < 1
                or any(type(value) is not int or value < 0 for value in (
                    self.affected_task_exact_count, self.affected_objective_exact_count))
                or self.proposal_kind not in {"create", "join", "move", "repin", "consolidate", "manual_merge", "manual_split"}
                or self.risk_tier not in {"normal", "high"}
                or self.origin not in {"task_created", "task_plan_changed", "source_plan_adopted", "manual_request", "retry_created", "objective_edit"}
                or self.state not in {"pending", "accepted", "rejected", "superseded"}
                or len(self.input_fingerprint) != 64 or any(char not in "0123456789abcdef" for char in self.input_fingerprint)):
            raise IntegrityFailure("Invalid immutable grouping recompute projection")
        return {key: getattr(self, key) for key in self.__dataclass_fields__}



@dataclass(frozen=True, slots=True)
class GroupingRecomputeProposalPageV1:
    """Complete immediate recompute result, distinct from a live cursor page."""

    items: tuple[GroupingRecomputeProposalV1, ...] = ()

    def to_response(self) -> dict[str, object]:
        return {"items": [item.to_response() for item in self.items],
                "continuation": None, "exact_total": len(self.items)}


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
class HistoricalObjectiveProposalDecisionResult:
    outcome: str
    proposal_id: str
    proposal_revision: int
    state: str
    objective_id: str | None
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



def historical_objective_proposal_decision_from_execution(
    result: CommandExecutionResult,
) -> HistoricalObjectiveProposalDecisionResult:
    expected_fields = {
        "outcome",
        "proposal_id",
        "proposal_revision",
        "state",
        "objective_id",
        "result_refs",
    }
    if (
        result.response_schema != "HistoricalObjectiveProposalDecisionV1"
        or result.response_version != 1
        or not isinstance(result.response, dict)
        or set(result.response) != expected_fields
    ):
        raise IntegrityFailure(
            "historical Objective proposal replay result has the wrong response contract"
        )
    response = result.response
    outcome = response.get("outcome")
    if outcome not in {"APPLIED", "NO_CHANGE"} or bool(result.no_change) != (
        outcome == "NO_CHANGE"
    ):
        raise IntegrityFailure(
            "historical Objective proposal replay result has inconsistent outcome"
        )
    proposal_id = response.get("proposal_id")
    objective_id = response.get("objective_id")
    try:
        if not isinstance(proposal_id, str):
            raise ValidationError("proposal_id must be UUID text")
        require_uuid4(proposal_id)
        if objective_id is not None:
            if not isinstance(objective_id, str):
                raise ValidationError("objective_id must be UUID text or null")
            require_uuid4(objective_id)
    except ValidationError as exc:
        raise IntegrityFailure(
            "historical Objective proposal replay identity is invalid"
        ) from exc
    revision = response.get("proposal_revision")
    if type(revision) is not int or revision <= 0:
        raise IntegrityFailure(
            "historical Objective proposal replay revision is invalid"
        )
    state = response.get("state")
    if state not in {"accepted", "rejected"}:
        raise IntegrityFailure(
            "historical Objective proposal replay state is invalid"
        )
    if (state == "accepted") != (objective_id is not None):
        raise IntegrityFailure(
            "historical Objective proposal replay Objective identity is inconsistent"
        )
    refs = _parse_result_refs(response.get("result_refs"), max_items=8)
    if outcome == "NO_CHANGE":
        if refs or result.result_id is not None or result.result_type not in {
            None,
            "NO_CHANGE",
        }:
            raise IntegrityFailure(
                "historical Objective proposal NO_CHANGE claims material authority"
            )
    else:
        if not isinstance(result.result_type, str) or not isinstance(
            result.result_id, str
        ):
            raise IntegrityFailure(
                "historical Objective proposal material receipt lacks result identity"
            )
        if (result.result_type, result.result_id) not in {
            (ref.result_type, ref.result_id) for ref in refs
        }:
            raise IntegrityFailure(
                "historical Objective proposal response omits receipt result identity"
            )
    return HistoricalObjectiveProposalDecisionResult(
        outcome=str(outcome),
        proposal_id=proposal_id,
        proposal_revision=revision,
        state=str(state),
        objective_id=None if objective_id is None else str(objective_id),
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
