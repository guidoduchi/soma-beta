from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
import re
from types import MappingProxyType

from soma.foundation.errors import IntegrityFailure, ValidationError

_QUERY_AUTH = "LLD12_BROWSER_QUERY_V1"
_MUTATION_AUTH = "LLD12_BROWSER_MUTATION_V1"
_ALLOWED_METHODS = frozenset({"GET", "POST", "DELETE"})
_PARAMETER = re.compile(r"^\{([a-z][a-z0-9_]*)\}$")


@dataclass(frozen=True, slots=True)
class ObjectiveTaskRouteSpec:
    method: str
    path: str
    handler_kind: str
    handler: str
    request_type: str
    response_type: str
    success_status: int
    max_request_bytes: int
    auth_policy: str
    error_codes: tuple[str, ...]

    def __post_init__(self) -> None:
        if self.method not in _ALLOWED_METHODS:
            raise IntegrityFailure("LLD-05 route method is invalid")
        if not self.path.startswith("/api/v1/") or "?" in self.path or "#" in self.path or "//" in self.path:
            raise IntegrityFailure("LLD-05 route path is not canonical")
        if self.handler_kind not in {"query", "command"}:
            raise IntegrityFailure("LLD-05 route handler kind is invalid")
        expected = _QUERY_AUTH if self.handler_kind == "query" else _MUTATION_AUTH
        if self.auth_policy != expected:
            raise IntegrityFailure("LLD-05 route auth policy disagrees with handler kind")
        if self.handler_kind == "command" and self.method not in {"POST", "DELETE"}:
            raise IntegrityFailure("LLD-05 command route method is invalid")
        if self.handler_kind == "query" and self.method not in {"GET", "POST"}:
            raise IntegrityFailure("LLD-05 query route method is invalid")
        if self.success_status not in {200, 201}:
            raise IntegrityFailure("LLD-05 route success status is invalid")
        if type(self.max_request_bytes) is not int or self.max_request_bytes <= 0:
            raise IntegrityFailure("LLD-05 route request bound is invalid")
        params: list[str] = []
        for segment in self.path.split("/"):
            if segment.startswith("{") or segment.endswith("}"):
                match = _PARAMETER.fullmatch(segment)
                if match is None:
                    raise IntegrityFailure("LLD-05 route parameter is invalid")
                params.append(match.group(1))
        if len(params) != len(set(params)):
            raise IntegrityFailure("LLD-05 route repeats a parameter")


@dataclass(frozen=True, slots=True)
class ResolvedObjectiveTaskRoute:
    spec: ObjectiveTaskRouteSpec
    path_parameters: Mapping[str, str] = field(default_factory=lambda: MappingProxyType({}))

    def __post_init__(self) -> None:
        object.__setattr__(self, "path_parameters", MappingProxyType(dict(self.path_parameters)))


@dataclass(frozen=True, slots=True)
class ObjectiveTaskHttpResponse:
    status: int
    response_type: str
    body: Mapping[str, object]

    def __post_init__(self) -> None:
        object.__setattr__(self, "body", MappingProxyType(dict(self.body)))


def _r(method, path, kind, handler, request, response, status, bound, errors):
    return ObjectiveTaskRouteSpec(
        method, path, kind, handler, request, response, status, bound,
        _QUERY_AUTH if kind == "query" else _MUTATION_AUTH, tuple(errors)
    )


ROUTES: tuple[ObjectiveTaskRouteSpec, ...] = (
    _r("GET","/api/v1/objectives","query","ObjectiveList","ObjectiveListQueryV1","ObjectivePageV1",200,4096,["VALIDATION_FAILED"]),
    _r("GET","/api/v1/objectives/{objective_id}","query","ObjectiveWorkbench","ObjectiveIdQueryV1","ObjectiveDetailV1",200,4096,["OBJECTIVE_NOT_FOUND","VALIDATION_FAILED"]),
    _r("POST","/api/v1/objectives/create-preview","query","ObjectiveCreationPreview","ObjectiveCreationPreviewQueryV1","ObjectiveCreationPreviewV1",200,16384,["TASK_NOT_FOUND","TASK_PLAN_INCOMPLETE","TASK_PLAN_INVALID_INTERVAL","OBJECTIVE_OVERLAP","GROUPING_INDETERMINATE","TIMEZONE_UNKNOWN","TIMEZONE_AMBIGUOUS_LOCAL_TIME","TIMEZONE_NONEXISTENT_LOCAL_TIME"]),
    _r("POST","/api/v1/objectives","command","CreateObjectiveFromPreview","CreateObjectiveFromPreviewRequestV1","ObjectiveMutationResultV1",201,32768,["TASK_STALE","TASK_ALREADY_IN_OBJECTIVE","OBJECTIVE_EMPTY","OBJECTIVE_OVERLAP","OBJECTIVE_TRACKING_ID_EXHAUSTED","GROUPING_INDETERMINATE","IDEMPOTENCY_CONFLICT"]),
    _r("POST","/api/v1/objectives/{objective_id}/tasks/start-selected","command","StartSelectedObjectiveTasks","StartSelectedObjectiveTasksRequestV1","ObjectiveMutationResultV1",200,16384,["OBJECTIVE_NOT_FOUND","OBJECTIVE_STALE","TASK_STALE","TASK_EXECUTION_ALREADY_STARTED","TASK_EXECUTION_ALREADY_TERMINAL","IDEMPOTENCY_CONFLICT"]),
    _r("POST","/api/v1/objectives/{objective_id}/cancel","command","CancelObjectiveBeforeExecution","CancelObjectiveBeforeExecutionRequestV1","ObjectiveMutationResultV1",200,8192,["OBJECTIVE_NOT_FOUND","OBJECTIVE_STALE","OBJECTIVE_CANCEL_AFTER_EXECUTION","IDEMPOTENCY_CONFLICT"]),
    _r("POST","/api/v1/objectives/{objective_id}/review","command","ReviewObjective","ReviewObjectiveRequestV1","ObjectiveMutationResultV1",200,8192,["OBJECTIVE_NOT_FOUND","OBJECTIVE_REVIEW_NOT_READY","OBJECTIVE_REVIEW_STALE","IDEMPOTENCY_CONFLICT"]),
    _r("POST","/api/v1/objectives/{objective_id}/archive","command","ArchiveObjective","ArchiveObjectiveRequestV1","ObjectiveMutationResultV1",200,4096,["OBJECTIVE_NOT_FOUND","OBJECTIVE_STALE","IDEMPOTENCY_CONFLICT"]),
    _r("POST","/api/v1/objectives/{objective_id}/restore","command","RestoreObjective","RestoreObjectiveRequestV1","ObjectiveMutationResultV1",200,4096,["OBJECTIVE_NOT_FOUND","OBJECTIVE_STALE","OBJECTIVE_OVERLAP","IDEMPOTENCY_CONFLICT"]),
    _r("POST","/api/v1/objectives/{objective_id}/hard-delete-preview","query","ObjectiveHardDeletePreview","ObjectiveHardDeletePreviewQueryV1","HardDeletePreviewV1",200,4096,["OBJECTIVE_NOT_FOUND","HARD_DELETE_BLOCKED","HARD_DELETE_INDETERMINATE"]),
    _r("DELETE","/api/v1/objectives/{objective_id}","command","HardDeleteObjective","HardDeleteObjectiveRequestV1","ObjectiveMutationResultV1",200,8192,["OBJECTIVE_NOT_FOUND","OBJECTIVE_STALE","HARD_DELETE_BLOCKED","HARD_DELETE_INDETERMINATE","IDEMPOTENCY_CONFLICT"]),
    _r("GET","/api/v1/grouping/proposals","query","GroupingProposalList","GroupingProposalListQueryV1","GroupingProposalPageV1",200,4096,["VALIDATION_FAILED"]),
    _r("POST","/api/v1/grouping/recompute","command","RecomputeGroupingProposals","RecomputeGroupingProposalsRequestV1","GroupingProposalPageV1",200,8192,["GROUPING_INDETERMINATE","IDEMPOTENCY_CONFLICT"]),
    _r("POST","/api/v1/grouping/proposals/{proposal_id}/accept","command","AcceptRegroupProposal","AcceptRegroupProposalRequestV1","GroupingProposalV1",200,16384,["GROUPING_PROPOSAL_NOT_FOUND","GROUPING_PROPOSAL_STALE","GROUPING_INDETERMINATE","TASK_MEMBERSHIP_LOCKED","OBJECTIVE_TERMINAL_RESTRUCTURE","OBJECTIVE_IN_PROGRESS_RESTRUCTURE_LIMIT","OBJECTIVE_OVERLAP","IDEMPOTENCY_CONFLICT"]),
    _r("POST","/api/v1/grouping/proposals/{proposal_id}/reject","command","RejectRegroupProposal","RejectRegroupProposalRequestV1","GroupingProposalV1",200,8192,["GROUPING_PROPOSAL_NOT_FOUND","GROUPING_PROPOSAL_STALE","IDEMPOTENCY_CONFLICT"]),
    _r("POST","/api/v1/grouping/proposals/{proposal_id}/reconsider","command","ReconsiderRegroupInputs","ReconsiderRegroupInputsRequestV1","GroupingProposalV1",200,8192,["GROUPING_PROPOSAL_NOT_FOUND","GROUPING_EQUIVALENT_REJECTION","IDEMPOTENCY_CONFLICT"]),
    _r("GET","/api/v1/objectives/historical-proposals","query","HistoricalObjectiveProposalList","HistoricalObjectiveProposalListQueryV1","HistoricalObjectiveProposalPageV1",200,4096,["VALIDATION_FAILED"]),
    _r("POST","/api/v1/objectives/historical-proposals/{proposal_id}/accept","command","AcceptHistoricalObjectiveProposal","AcceptHistoricalObjectiveProposalRequestV1","HistoricalObjectiveProposalDecisionV1",200,16384,["HISTORICAL_PROPOSAL_STALE","HISTORICAL_PROPOSAL_NOT_ELIGIBLE","OBJECTIVE_OVERLAP","IDEMPOTENCY_CONFLICT"]),
    _r("POST","/api/v1/objectives/historical-proposals/{proposal_id}/reject","command","RejectHistoricalObjectiveProposal","RejectHistoricalObjectiveProposalRequestV1","HistoricalObjectiveProposalDecisionV1",200,8192,["HISTORICAL_PROPOSAL_STALE","IDEMPOTENCY_CONFLICT"]),
    _r("GET","/api/v1/settings/objective-timezone","query","GetObjectiveTimezone","ObjectiveTimezoneQueryV1","ObjectiveTimezoneV1",200,2048,[]),
    _r("POST","/api/v1/settings/objective-timezone","command","SetObjectiveTimezone","SetObjectiveTimezoneRequestV1","ObjectiveTimezoneV1",200,4096,["TIMEZONE_UNKNOWN","IDEMPOTENCY_CONFLICT"]),
    _r("POST","/api/v1/tasks/{task_id}/execution/correct-preview","query","TaskExecutionCorrectionPreview","TaskExecutionCorrectionPreviewQueryV1","TaskExecutionCorrectionPreviewV1",200,8192,["TASK_NOT_FOUND","TASK_STALE","TASK_REVIEW_STALE","TASK_OUTCOME_INVALID_FOR_EXECUTION"]),
    _r("POST","/api/v1/tasks/{task_id}/review-preview","query","TaskOutcomeReviewPreview","TaskOutcomeReviewPreviewQueryV1","TaskOutcomeReviewPreviewV1",200,8192,["TASK_NOT_FOUND","TASK_STALE","TASK_REVIEW_STALE","TASK_OUTCOME_INVALID_FOR_EXECUTION"]),
    _r("POST","/api/v1/tasks/{task_id}/review/correct-preview","query","TaskOutcomeCorrectionPreview","TaskOutcomeCorrectionPreviewQueryV1","TaskOutcomeCorrectionPreviewV1",200,8192,["TASK_NOT_FOUND","TASK_STALE","TASK_REVIEW_STALE","TASK_OUTCOME_INVALID_FOR_EXECUTION"]),
)


def resolve_objectives_tasks_route(method: str, path: str) -> ResolvedObjectiveTaskRoute | None:
    if not isinstance(method, str) or not method:
        raise ValidationError("HTTP method must be nonempty text")
    if not isinstance(path, str) or not path.startswith("/") or "?" in path or "#" in path:
        raise ValidationError("route resolver requires one absolute path")
    actual_method = method.upper()
    actual_segments = path.split("/")
    for spec in ROUTES:
        if spec.method != actual_method:
            continue
        expected_segments = spec.path.split("/")
        if len(expected_segments) != len(actual_segments):
            continue
        params: dict[str, str] = {}
        matched = True
        for expected, actual in zip(expected_segments, actual_segments, strict=True):
            parameter = _PARAMETER.fullmatch(expected)
            if parameter is None:
                if expected != actual:
                    matched = False
                    break
            elif not actual:
                matched = False
                break
            else:
                params[parameter.group(1)] = actual
        if matched:
            return ResolvedObjectiveTaskRoute(spec, params)
    return None


OwnerHandler = Callable[[ResolvedObjectiveTaskRoute, Mapping[str, object]], Mapping[str, object]]


class ObjectiveTaskRouteAdapter:
    def __init__(self, handlers: Mapping[str, OwnerHandler]) -> None:
        keys = [(spec.method, spec.path) for spec in ROUTES]
        if len(keys) != len(set(keys)):
            raise IntegrityFailure("LLD-05 route registry has duplicate method/path authority")
        self._handlers = MappingProxyType(dict(handlers))

    @property
    def specs(self) -> tuple[ObjectiveTaskRouteSpec, ...]:
        return ROUTES

    def dispatch(
        self,
        method: str,
        path: str,
        decoded: Mapping[str, object] | None = None,
    ) -> ObjectiveTaskHttpResponse | None:
        resolved = resolve_objectives_tasks_route(method, path)
        if resolved is None:
            return None
        payload = {} if decoded is None else dict(decoded)
        handler = self._handlers.get(resolved.spec.handler)
        if handler is None:
            raise IntegrityFailure(
                f"LLD-05 route handler {resolved.spec.handler!r} is not assembled"
            )
        body = handler(resolved, MappingProxyType(payload))
        if not isinstance(body, Mapping):
            raise IntegrityFailure("LLD-05 owner adapter returned a non-object response")
        return ObjectiveTaskHttpResponse(
            status=resolved.spec.success_status,
            response_type=resolved.spec.response_type,
            body=body,
        )


__all__ = [
    "ObjectiveTaskHttpResponse",
    "ObjectiveTaskRouteAdapter",
    "ObjectiveTaskRouteSpec",
    "ROUTES",
    "ResolvedObjectiveTaskRoute",
    "resolve_objectives_tasks_route",
]
