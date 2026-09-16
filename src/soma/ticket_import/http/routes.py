from __future__ import annotations

from dataclasses import dataclass, field
import re
from types import MappingProxyType
from typing import Mapping

from soma.foundation.errors import IntegrityFailure, ValidationError
from soma.foundation.persistence.connections import ConnectionFactory
from soma.ticket_import.queries.proposals import ImportRecoveryQueryService, ProposalQueryService
from soma.ticket_import.queries.runs import ImportRunQueryService
from soma.ticket_import.queries.source_status import ImportSourceStatusQueryService


_API_PREFIX = "/api/v1"
_QUERY_AUTH = "LLD12_BROWSER_QUERY_V1"
_MUTATION_AUTH = "LLD12_BROWSER_MUTATION_V1"
_ALLOWED_METHODS = frozenset({"GET", "POST"})
_ALLOWED_HANDLER_KINDS = frozenset({"query", "command"})
_PATH_PARAMETER_RE = re.compile(r"^\{([a-z][a-z0-9_]*)\}$")


@dataclass(frozen=True, slots=True)
class TicketImportRouteSpec:
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
    constants: Mapping[str, str] = field(default_factory=lambda: MappingProxyType({}))

    def __post_init__(self) -> None:
        if self.method not in _ALLOWED_METHODS:
            raise IntegrityFailure("LLD-04 route method is outside the closed transport vocabulary")
        if not self.path.startswith(f"{_API_PREFIX}/imports"):
            raise IntegrityFailure("LLD-04 route path is outside the canonical import API prefix")
        if "?" in self.path or "#" in self.path or "//" in self.path:
            raise IntegrityFailure("LLD-04 route path is not canonical")
        if self.handler_kind not in _ALLOWED_HANDLER_KINDS:
            raise IntegrityFailure("LLD-04 route handler kind is invalid")
        if not self.handler or not self.request_type or not self.response_type:
            raise IntegrityFailure("LLD-04 route contract contains an empty authority identifier")
        expected_auth = _QUERY_AUTH if self.handler_kind == "query" else _MUTATION_AUTH
        if self.auth_policy != expected_auth:
            raise IntegrityFailure("LLD-04 route auth policy disagrees with handler kind")
        if self.handler_kind == "query" and self.method != "GET":
            raise IntegrityFailure("LLD-04 query route must use GET")
        if self.handler_kind == "command" and self.method != "POST":
            raise IntegrityFailure("LLD-04 command route must use POST")
        if type(self.success_status) is not int or self.success_status not in {200, 202}:
            raise IntegrityFailure("LLD-04 route success status is invalid")
        if type(self.max_request_bytes) is not int or self.max_request_bytes <= 0:
            raise IntegrityFailure("LLD-04 route request bound is invalid")
        if len(set(self.error_codes)) != len(self.error_codes):
            raise IntegrityFailure("LLD-04 route repeats an error code")
        if any(not isinstance(code, str) or not code for code in self.error_codes):
            raise IntegrityFailure("LLD-04 route contains an invalid error code")

        parameter_names: list[str] = []
        for segment in self.path.split("/"):
            if segment.startswith("{") or segment.endswith("}"):
                match = _PATH_PARAMETER_RE.fullmatch(segment)
                if match is None:
                    raise IntegrityFailure("LLD-04 route path parameter is invalid")
                parameter_names.append(match.group(1))
        if len(set(parameter_names)) != len(parameter_names):
            raise IntegrityFailure("LLD-04 route repeats a path parameter")

        constants = dict(self.constants)
        if any(not isinstance(key, str) or not key for key in constants):
            raise IntegrityFailure("LLD-04 route constant key is invalid")
        if any(not isinstance(value, str) or not value for value in constants.values()):
            raise IntegrityFailure("LLD-04 route constant value is invalid")
        object.__setattr__(self, "constants", MappingProxyType(constants))


@dataclass(frozen=True, slots=True)
class ResolvedImportRoute:
    spec: TicketImportRouteSpec
    path_parameters: Mapping[str, str]

    def __post_init__(self) -> None:
        object.__setattr__(self, "path_parameters", MappingProxyType(dict(self.path_parameters)))


@dataclass(frozen=True, slots=True)
class TicketImportHttpResponse:
    status: int
    response_type: str
    body: Mapping[str, object]

    def __post_init__(self) -> None:
        if type(self.status) is not int or self.status < 100 or self.status > 599:
            raise IntegrityFailure("LLD-04 HTTP response status is invalid")
        if not isinstance(self.response_type, str) or not self.response_type:
            raise IntegrityFailure("LLD-04 HTTP response type is invalid")
        object.__setattr__(self, "body", MappingProxyType(dict(self.body)))


def _route(
    method: str,
    path: str,
    handler_kind: str,
    handler: str,
    request_type: str,
    response_type: str,
    success_status: int,
    max_request_bytes: int,
    auth_policy: str,
    error_codes: tuple[str, ...],
    *,
    constants: Mapping[str, str] | None = None,
) -> TicketImportRouteSpec:
    return TicketImportRouteSpec(
        method=method,
        path=path,
        handler_kind=handler_kind,
        handler=handler,
        request_type=request_type,
        response_type=response_type,
        success_status=success_status,
        max_request_bytes=max_request_bytes,
        auth_policy=auth_policy,
        error_codes=error_codes,
        constants={} if constants is None else constants,
    )


def _start_route(
    path: str,
    source_family: str,
    invocation_kind: str,
    request_type: str,
    max_request_bytes: int,
    error_codes: tuple[str, ...],
) -> TicketImportRouteSpec:
    return _route(
        "POST",
        path,
        "command",
        "StartTicketSourceImportCheck",
        request_type,
        "ImportJobAcceptedV1",
        202,
        max_request_bytes,
        _MUTATION_AUTH,
        error_codes,
        constants={"source_family": source_family, "invocation_kind": invocation_kind},
    )


_START_CHECK_ERRORS = (
    "IMPORT_SOURCE_NOT_CONFIGURED",
    "IMPORT_SOURCE_UNAVAILABLE",
    "IMPORT_SOURCE_BUSY",
    "IDEMPOTENCY_CONFLICT",
)
_START_SELECT_ERRORS = (
    "IMPORT_SELECTED_PATH_INVALID",
    "IMPORT_SOURCE_UNAVAILABLE",
    "IMPORT_SOURCE_BUSY",
    "IDEMPOTENCY_CONFLICT",
)


IMPORT_ROUTE_SPECS = (
    _start_route("/api/v1/imports/sr/check", "advanced_search_sr", "automatic", "StartImportCheckRequestV1", 4096, _START_CHECK_ERRORS),
    _start_route("/api/v1/imports/sr/select", "advanced_search_sr", "manual", "StartImportSelectionRequestV1", 8192, _START_SELECT_ERRORS),
    _start_route("/api/v1/imports/rfc/check", "rfc_enhanced", "automatic", "StartImportCheckRequestV1", 4096, _START_CHECK_ERRORS),
    _start_route("/api/v1/imports/rfc/select", "rfc_enhanced", "manual", "StartImportSelectionRequestV1", 8192, _START_SELECT_ERRORS),
    _start_route("/api/v1/imports/wfm/check", "wfm_service_provider", "automatic", "StartImportCheckRequestV1", 4096, _START_CHECK_ERRORS),
    _start_route("/api/v1/imports/wfm/select", "wfm_service_provider", "manual", "StartImportSelectionRequestV1", 8192, _START_SELECT_ERRORS),
    _route("GET", "/api/v1/imports/sources/{source_family}", "query", "GetImportSourceStatus", "ImportSourceStatusQueryV1", "ImportSourceStatusV1", 200, 2048, _QUERY_AUTH, ("IMPORT_SOURCE_FAMILY_INVALID",)),
    _route("GET", "/api/v1/imports/runs", "query", "ListImportRuns", "ImportRunListQueryV1", "ImportRunPageV1", 200, 4096, _QUERY_AUTH, ("IMPORT_CURSOR_INVALID",)),
    _route("GET", "/api/v1/imports/runs/{import_run_id}", "query", "GetImportRun", "ImportRunQueryV1", "ImportRunDetailV1", 200, 2048, _QUERY_AUTH, ("IMPORT_RUN_NOT_FOUND",)),
    _route("GET", "/api/v1/imports/runs/{import_run_id}/observations", "query", "ListPublishedSourceObservations", "ObservationListQueryV1", "ObservationPageV1", 200, 4096, _QUERY_AUTH, ("IMPORT_RUN_NOT_FOUND", "IMPORT_RUN_UNPUBLISHED", "IMPORT_CURSOR_INVALID")),
    _route("GET", "/api/v1/imports/runs/{import_run_id}/findings", "query", "ListImportFindings", "FindingListQueryV1", "FindingPageV1", 200, 4096, _QUERY_AUTH, ("IMPORT_RUN_NOT_FOUND", "IMPORT_CURSOR_INVALID")),
    _route("GET", "/api/v1/imports/runs/{import_run_id}/proposals", "query", "ListReconciliationProposals", "ProposalListQueryV1", "ProposalPageV1", 200, 4096, _QUERY_AUTH, ("IMPORT_RUN_NOT_FOUND", "IMPORT_CURSOR_INVALID")),
    _route("GET", "/api/v1/imports/proposals/{proposal_id}", "query", "GetProposalReview", "ProposalReviewQueryV1", "ProposalReviewV1", 200, 2048, _QUERY_AUTH, ("IMPORT_PROPOSAL_NOT_FOUND",)),
    _route("POST", "/api/v1/imports/proposals/{proposal_id}/accept", "command", "AcceptReconciliationProposal", "AcceptProposalRequestV1", "ProposalDecisionResultV1", 200, 8192, _MUTATION_AUTH, ("IMPORT_PROPOSAL_NOT_FOUND", "IMPORT_PROPOSAL_STALE", "IMPORT_PROPOSAL_BLOCKED", "IMPORT_RECOVERY_AUTHORIZATION_REQUIRED", "IMPORT_RECOVERY_REVIEW_STALE", "IDEMPOTENCY_CONFLICT")),
    _route("POST", "/api/v1/imports/proposals/{proposal_id}/wfm-competing-attempt-review", "command", "ResolveWfmCompetingAttemptReview", "ResolveWfmCompetingAttemptReviewRequestV1", "ProposalDecisionResultV1", 200, 8192, _MUTATION_AUTH, ("IMPORT_PROPOSAL_NOT_FOUND", "IMPORT_PROPOSAL_STALE", "IMPORT_PROPOSAL_BLOCKED", "IMPORT_RECOVERY_AUTHORIZATION_REQUIRED", "IMPORT_RECOVERY_REVIEW_STALE", "IDEMPOTENCY_CONFLICT")),
    _route("POST", "/api/v1/imports/proposals/{proposal_id}/reject", "command", "RejectReconciliationProposal", "DecideProposalRequestV1", "ProposalDecisionResultV1", 200, 8192, _MUTATION_AUTH, ("IMPORT_PROPOSAL_NOT_FOUND", "IMPORT_PROPOSAL_STALE", "IMPORT_RECOVERY_REVIEW_STALE", "IDEMPOTENCY_CONFLICT")),
    _route("POST", "/api/v1/imports/proposals/{proposal_id}/defer", "command", "DeferReconciliationProposal", "DecideProposalRequestV1", "ProposalDecisionResultV1", 200, 8192, _MUTATION_AUTH, ("IMPORT_PROPOSAL_NOT_FOUND", "IMPORT_PROPOSAL_STALE", "IMPORT_RECOVERY_REVIEW_STALE", "IDEMPOTENCY_CONFLICT")),
    _route("POST", "/api/v1/imports/runs/{import_run_id}/finalize", "command", "FinalizeImportRunReview", "FinalizeImportRunRequestV1", "ImportRunFinalizeResultV1", 200, 4096, _MUTATION_AUTH, ("IMPORT_RUN_NOT_FOUND", "IMPORT_RUN_STALE", "IMPORT_PENDING_PROPOSALS", "IMPORT_RECOVERY_AUTHORIZATION_REQUIRED", "IMPORT_RECOVERY_REVIEW_STALE", "IDEMPOTENCY_CONFLICT")),
    _route("GET", "/api/v1/imports/runs/{import_run_id}/recovery-preview", "query", "PreviewImportRecovery", "RecoveryPreviewQueryV1", "RecoveryPreviewV1", 200, 2048, _QUERY_AUTH, ("IMPORT_RUN_NOT_FOUND", "IMPORT_RUN_NOT_RECOVERY_REQUIRED")),
    _route("POST", "/api/v1/imports/runs/{import_run_id}/recovery", "command", "ResolveImportRecovery", "ResolveRecoveryRequestV1", "RecoveryDecisionResultV1", 200, 8192, _MUTATION_AUTH, ("IMPORT_RUN_NOT_FOUND", "IMPORT_RUN_NOT_RECOVERY_REQUIRED", "IMPORT_RECOVERY_REVIEW_STALE", "IMPORT_RECOVERY_REJECT_AFTER_ACCEPTANCE", "IDEMPOTENCY_CONFLICT")),
)


_ROUTE_KEYS = tuple((spec.method, spec.path) for spec in IMPORT_ROUTE_SPECS)
if len(set(_ROUTE_KEYS)) != len(_ROUTE_KEYS):
    raise IntegrityFailure("LLD-04 route registry contains duplicate method/path authorities")

_PUBLIC_HANDLERS = frozenset(spec.handler for spec in IMPORT_ROUTE_SPECS)
if _PUBLIC_HANDLERS & {"PublishStagedImportRun", "RecordNewerIdenticalSourceCheck"}:
    raise IntegrityFailure("LLD-04 internal command was exposed as a browser route")


def _match_template(template: str, path: str) -> dict[str, str] | None:
    template_segments = template.split("/")
    path_segments = path.split("/")
    if len(template_segments) != len(path_segments):
        return None
    parameters: dict[str, str] = {}
    for expected, actual in zip(template_segments, path_segments, strict=True):
        match = _PATH_PARAMETER_RE.fullmatch(expected)
        if match is None:
            if actual != expected:
                return None
            continue
        if not actual or "/" in actual:
            return None
        parameters[match.group(1)] = actual
    return parameters


def resolve_import_route(method: str, path: str) -> ResolvedImportRoute | None:
    """Resolve one canonical path; LLD-12 owns authentication and HTTP server binding."""

    if not isinstance(method, str) or not method:
        raise ValidationError("HTTP method must be a nonempty string")
    if not isinstance(path, str) or not path.startswith("/"):
        raise ValidationError("HTTP route path must be an absolute path")
    if "?" in path or "#" in path:
        raise ValidationError("HTTP route resolver accepts path only, not query or fragment")
    canonical_method = method.upper()
    for spec in IMPORT_ROUTE_SPECS:
        if spec.method != canonical_method:
            continue
        parameters = _match_template(spec.path, path)
        if parameters is not None:
            return ResolvedImportRoute(spec=spec, path_parameters=parameters)
    return None


def _request_data(value: Mapping[str, object] | None, *, allowed: frozenset[str]) -> dict[str, object]:
    if value is None:
        data: dict[str, object] = {}
    elif isinstance(value, Mapping):
        data = dict(value)
    else:
        raise ValidationError("LLD-04 decoded query parameters must be a mapping")
    unexpected = set(data) - allowed
    if unexpected:
        raise ValidationError(f"unexpected LLD-04 query field: {sorted(unexpected)[0]}")
    if any(not isinstance(key, str) or not key for key in data):
        raise ValidationError("LLD-04 query field names must be nonempty strings")
    return data


def _optional_string(data: Mapping[str, object], key: str) -> str | None:
    value = data.get(key)
    if value is None:
        return None
    if not isinstance(value, str):
        raise ValidationError(f"{key} must be a string or null")
    return value


def _cursor(data: Mapping[str, object]) -> dict[str, object] | None:
    value = data.get("cursor")
    if value is None:
        return None
    if not isinstance(value, dict):
        raise ValidationError("cursor must be a decoded CURSOR_V1 object or null")
    return dict(value)


def _limit(data: Mapping[str, object]) -> int:
    value = data.get("limit", 100)
    if type(value) is not int or not 1 <= value <= 100:
        raise ValidationError("limit must be an integer from 1 through 100")
    return value


class TicketImportQueryRouteAdapter:
    """Thin authenticated-query adapter; LLD-12 must enforce the route auth policy before calling it."""

    def __init__(self, connection_factory: ConnectionFactory) -> None:
        self._source_status = ImportSourceStatusQueryService(connection_factory)
        self._runs = ImportRunQueryService(connection_factory)
        self._proposals = ProposalQueryService(connection_factory)
        self._recovery = ImportRecoveryQueryService(connection_factory)

    @staticmethod
    def _response(resolved: ResolvedImportRoute, body: Mapping[str, object]) -> TicketImportHttpResponse:
        return TicketImportHttpResponse(
            status=resolved.spec.success_status,
            response_type=resolved.spec.response_type,
            body=body,
        )

    def dispatch(
        self,
        method: str,
        path: str,
        query: Mapping[str, object] | None = None,
    ) -> TicketImportHttpResponse | None:
        """Dispatch one already-authenticated GET route using decoded query values."""

        resolved = resolve_import_route(method, path)
        if resolved is None:
            return None
        if resolved.spec.handler_kind != "query":
            raise ValidationError("mutation route cannot be dispatched through the LLD-04 query adapter")

        handler = resolved.spec.handler
        path_parameters = resolved.path_parameters

        if handler == "GetImportSourceStatus":
            data = _request_data(query, allowed=frozenset())
            assert not data
            result = self._source_status.get_status(path_parameters["source_family"])
        elif handler == "ListImportRuns":
            data = _request_data(query, allowed=frozenset({"source_family", "state", "cursor", "limit"}))
            result = self._runs.list_runs(
                source_family=_optional_string(data, "source_family"),
                state=_optional_string(data, "state"),
                cursor=_cursor(data),
                limit=_limit(data),
            )
        elif handler == "GetImportRun":
            data = _request_data(query, allowed=frozenset())
            assert not data
            result = self._runs.get_run(path_parameters["import_run_id"])
        elif handler == "ListPublishedSourceObservations":
            data = _request_data(query, allowed=frozenset({"identity_state", "cursor", "limit"}))
            result = self._runs.list_published_observations(
                path_parameters["import_run_id"],
                identity_state=_optional_string(data, "identity_state"),
                cursor=_cursor(data),
                limit=_limit(data),
            )
        elif handler == "ListImportFindings":
            data = _request_data(query, allowed=frozenset({"severity", "scope_kind", "cursor", "limit"}))
            result = self._runs.list_findings(
                path_parameters["import_run_id"],
                severity=_optional_string(data, "severity"),
                scope_kind=_optional_string(data, "scope_kind"),
                cursor=_cursor(data),
                limit=_limit(data),
            )
        elif handler == "ListReconciliationProposals":
            data = _request_data(query, allowed=frozenset({"state", "risk", "kind", "cursor", "limit"}))
            result = self._proposals.list_proposals(
                path_parameters["import_run_id"],
                state=_optional_string(data, "state"),
                risk=_optional_string(data, "risk"),
                kind=_optional_string(data, "kind"),
                cursor=_cursor(data),
                limit=_limit(data),
            )
        elif handler == "GetProposalReview":
            data = _request_data(query, allowed=frozenset())
            assert not data
            result = self._proposals.get_review(path_parameters["proposal_id"])
        elif handler == "PreviewImportRecovery":
            data = _request_data(query, allowed=frozenset())
            assert not data
            result = self._recovery.preview(path_parameters["import_run_id"])
        else:
            raise IntegrityFailure("LLD-04 public query route has no query-service dispatch authority")

        body = result.to_response()
        if not isinstance(body, dict):
            raise IntegrityFailure("LLD-04 query service returned a non-object transport payload")
        return self._response(resolved, body)


__all__ = [
    "IMPORT_ROUTE_SPECS",
    "ResolvedImportRoute",
    "TicketImportHttpResponse",
    "TicketImportQueryRouteAdapter",
    "TicketImportRouteSpec",
    "resolve_import_route",
]
