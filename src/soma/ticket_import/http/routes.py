from __future__ import annotations

from dataclasses import dataclass
import re
from types import MappingProxyType
from typing import Mapping

from soma.foundation.errors import IntegrityFailure, ValidationError


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
    constants: Mapping[str, str] = MappingProxyType({})

    def __post_init__(self) -> None:
        if self.method not in _ALLOWED_METHODS:
            raise IntegrityFailure("LLD-04 route method is outside the closed transport vocabulary")
        if not self.path.startswith(f"{_API_PREFIX}/imports"):
            raise IntegrityFailure("LLD-04 route path is outside the canonical import API prefix")
        if "?" in self.path or "#" in self.path or "//" in self.path:
            raise IntegrityFailure("LLD-04 route path is not canonical")
        if self.handler_kind not in _ALLOWED_HANDLER_KINDS:
            raise IntegrityFailure("LLD-04 route handler kind is invalid")
        if not self.handler:
            raise IntegrityFailure("LLD-04 route handler is empty")
        if not self.request_type or not self.response_type:
            raise IntegrityFailure("LLD-04 route transport type is empty")
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
    *,
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


IMPORT_ROUTE_SPECS = (
    _start_route(
        path="/api/v1/imports/sr/check",
        source_family="advanced_search_sr",
        invocation_kind="automatic",
        request_type="StartImportCheckRequestV1",
        max_request_bytes=4096,
        error_codes=(
            "IMPORT_SOURCE_NOT_CONFIGURED",
            "IMPORT_SOURCE_UNAVAILABLE",
            "IMPORT_SOURCE_BUSY",
            "IDEMPOTENCY_CONFLICT",
        ),
    ),
    _start_route(
        path="/api/v1/imports/sr/select",
        source_family="advanced_search_sr",
        invocation_kind="manual",
        request_type="StartImportSelectionRequestV1",
        max_request_bytes=8192,
        error_codes=(
            "IMPORT_SELECTED_PATH_INVALID",
            "IMPORT_SOURCE_UNAVAILABLE",
            "IMPORT_SOURCE_BUSY",
            "IDEMPOTENCY_CONFLICT",
        ),
    ),
    _start_route(
        path="/api/v1/imports/rfc/check",
        source_family="rfc_enhanced",
        invocation_kind="automatic",
        request_type="StartImportCheckRequestV1",
        max_request_bytes=4096,
        error_codes=(
            "IMPORT_SOURCE_NOT_CONFIGURED",
            "IMPORT_SOURCE_UNAVAILABLE",
            "IMPORT_SOURCE_BUSY",
            "IDEMPOTENCY_CONFLICT",
        ),
    ),
    _start_route(
        path="/api/v1/imports/rfc/select",
        source_family="rfc_enhanced",
        invocation_kind="manual",
        request_type="StartImportSelectionRequestV1",
        max_request_bytes=8192,
        error_codes=(
            "IMPORT_SELECTED_PATH_INVALID",
            "IMPORT_SOURCE_UNAVAILABLE",
            "IMPORT_SOURCE_BUSY",
            "IDEMPOTENCY_CONFLICT",
        ),
    ),
    _start_route(
        path="/api/v1/imports/wfm/check",
        source_family="wfm_service_provider",
        invocation_kind="automatic",
        request_type="StartImportCheckRequestV1",
        max_request_bytes=4096,
        error_codes=(
            "IMPORT_SOURCE_NOT_CONFIGURED",
            "IMPORT_SOURCE_UNAVAILABLE",
            "IMPORT_SOURCE_BUSY",
            "IDEMPOTENCY_CONFLICT",
        ),
    ),
    _start_route(
        path="/api/v1/imports/wfm/select",
        source_family="wfm_service_provider",
        invocation_kind="manual",
        request_type="StartImportSelectionRequestV1",
        max_request_bytes=8192,
        error_codes=(
            "IMPORT_SELECTED_PATH_INVALID",
            "IMPORT_SOURCE_UNAVAILABLE",
            "IMPORT_SOURCE_BUSY",
            "IDEMPOTENCY_CONFLICT",
        ),
    ),
    _route(
        "GET",
        "/api/v1/imports/sources/{source_family}",
        "query",
        "GetImportSourceStatus",
        "ImportSourceStatusQueryV1",
        "ImportSourceStatusV1",
        200,
        2048,
        _QUERY_AUTH,
        ("IMPORT_SOURCE_FAMILY_INVALID",),
    ),
    _route(
        "GET",
        "/api/v1/imports/runs",
        "query",
        "ListImportRuns",
        "ImportRunListQueryV1",
        "ImportRunPageV1",
        200,
        4096,
        _QUERY_AUTH,
        ("IMPORT_CURSOR_INVALID",),
    ),
    _route(
        "GET",
        "/api/v1/imports/runs/{import_run_id}",
        "query",
        "GetImportRun",
        "ImportRunQueryV1",
        "ImportRunDetailV1",
        200,
        2048,
        _QUERY_AUTH,
        ("IMPORT_RUN_NOT_FOUND",),
    ),
    _route(
        "GET",
        "/api/v1/imports/runs/{import_run_id}/observations",
        "query",
        "ListPublishedSourceObservations",
        "ObservationListQueryV1",
        "ObservationPageV1",
        200,
        4096,
        _QUERY_AUTH,
        ("IMPORT_RUN_NOT_FOUND", "IMPORT_RUN_UNPUBLISHED", "IMPORT_CURSOR_INVALID"),
    ),
    _route(
        "GET",
        "/api/v1/imports/runs/{import_run_id}/findings",
        "query",
        "ListImportFindings",
        "FindingListQueryV1",
        "FindingPageV1",
        200,
        4096,
        _QUERY_AUTH,
        ("IMPORT_RUN_NOT_FOUND", "IMPORT_CURSOR_INVALID"),
    ),
    _route(
        "GET",
        "/api/v1/imports/runs/{import_run_id}/proposals",
        "query",
        "ListReconciliationProposals",
        "ProposalListQueryV1",
        "ProposalPageV1",
        200,
        4096,
        _QUERY_AUTH,
        ("IMPORT_RUN_NOT_FOUND", "IMPORT_CURSOR_INVALID"),
    ),
    _route(
        "GET",
        "/api/v1/imports/proposals/{proposal_id}",
        "query",
        "GetProposalReview",
        "ProposalReviewQueryV1",
        "ProposalReviewV1",
        200,
        2048,
        _QUERY_AUTH,
        ("IMPORT_PROPOSAL_NOT_FOUND",),
    ),
    _route(
        "POST",
        "/api/v1/imports/proposals/{proposal_id}/accept",
        "command",
        "AcceptReconciliationProposal",
        "AcceptProposalRequestV1",
        "ProposalDecisionResultV1",
        200,
        8192,
        _MUTATION_AUTH,
        (
            "IMPORT_PROPOSAL_NOT_FOUND",
            "IMPORT_PROPOSAL_STALE",
            "IMPORT_PROPOSAL_BLOCKED",
            "IMPORT_RECOVERY_AUTHORIZATION_REQUIRED",
            "IMPORT_RECOVERY_REVIEW_STALE",
            "IDEMPOTENCY_CONFLICT",
        ),
    ),
    _route(
        "POST",
        "/api/v1/imports/proposals/{proposal_id}/wfm-competing-attempt-review",
        "command",
        "ResolveWfmCompetingAttemptReview",
        "ResolveWfmCompetingAttemptReviewRequestV1",
        "ProposalDecisionResultV1",
        200,
        8192,
        _MUTATION_AUTH,
        (
            "IMPORT_PROPOSAL_NOT_FOUND",
            "IMPORT_PROPOSAL_STALE",
            "IMPORT_PROPOSAL_BLOCKED",
            "IMPORT_RECOVERY_AUTHORIZATION_REQUIRED",
            "IMPORT_RECOVERY_REVIEW_STALE",
            "IDEMPOTENCY_CONFLICT",
        ),
    ),
    _route(
        "POST",
        "/api/v1/imports/proposals/{proposal_id}/reject",
        "command",
        "RejectReconciliationProposal",
        "DecideProposalRequestV1",
        "ProposalDecisionResultV1",
        200,
        8192,
        _MUTATION_AUTH,
        (
            "IMPORT_PROPOSAL_NOT_FOUND",
            "IMPORT_PROPOSAL_STALE",
            "IMPORT_RECOVERY_REVIEW_STALE",
            "IDEMPOTENCY_CONFLICT",
        ),
    ),
    _route(
        "POST",
        "/api/v1/imports/proposals/{proposal_id}/defer",
        "command",
        "DeferReconciliationProposal",
        "DecideProposalRequestV1",
        "ProposalDecisionResultV1",
        200,
        8192,
        _MUTATION_AUTH,
        (
            "IMPORT_PROPOSAL_NOT_FOUND",
            "IMPORT_PROPOSAL_STALE",
            "IMPORT_RECOVERY_REVIEW_STALE",
            "IDEMPOTENCY_CONFLICT",
        ),
    ),
    _route(
        "POST",
        "/api/v1/imports/runs/{import_run_id}/finalize",
        "command",
        "FinalizeImportRunReview",
        "FinalizeImportRunRequestV1",
        "ImportRunFinalizeResultV1",
        200,
        4096,
        _MUTATION_AUTH,
        (
            "IMPORT_RUN_NOT_FOUND",
            "IMPORT_RUN_STALE",
            "IMPORT_PENDING_PROPOSALS",
            "IMPORT_RECOVERY_AUTHORIZATION_REQUIRED",
            "IMPORT_RECOVERY_REVIEW_STALE",
            "IDEMPOTENCY_CONFLICT",
        ),
    ),
    _route(
        "GET",
        "/api/v1/imports/runs/{import_run_id}/recovery-preview",
        "query",
        "PreviewImportRecovery",
        "RecoveryPreviewQueryV1",
        "RecoveryPreviewV1",
        200,
        2048,
        _QUERY_AUTH,
        ("IMPORT_RUN_NOT_FOUND", "IMPORT_RUN_NOT_RECOVERY_REQUIRED"),
    ),
    _route(
        "POST",
        "/api/v1/imports/runs/{import_run_id}/recovery",
        "command",
        "ResolveImportRecovery",
        "ResolveRecoveryRequestV1",
        "RecoveryDecisionResultV1",
        200,
        8192,
        _MUTATION_AUTH,
        (
            "IMPORT_RUN_NOT_FOUND",
            "IMPORT_RUN_NOT_RECOVERY_REQUIRED",
            "IMPORT_RECOVERY_REVIEW_STALE",
            "IMPORT_RECOVERY_REJECT_AFTER_ACCEPTANCE",
            "IDEMPOTENCY_CONFLICT",
        ),
    ),
)


_ROUTE_KEYS = tuple((spec.method, spec.path) for spec in IMPORT_ROUTE_SPECS)
if len(set(_ROUTE_KEYS)) != len(_ROUTE_KEYS):
    raise IntegrityFailure("LLD-04 route registry contains duplicate method/path authorities")

_PUBLIC_HANDLERS = frozenset(spec.handler for spec in IMPORT_ROUTE_SPECS)
_FORBIDDEN_PUBLIC_HANDLERS = frozenset({"PublishStagedImportRun", "RecordNewerIdenticalSourceCheck"})
if _PUBLIC_HANDLERS & _FORBIDDEN_PUBLIC_HANDLERS:
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
    """Resolve one canonical path without doing auth, decoding query/body data, or domain work."""

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


__all__ = [
    "IMPORT_ROUTE_SPECS",
    "ResolvedImportRoute",
    "TicketImportRouteSpec",
    "resolve_import_route",
]
