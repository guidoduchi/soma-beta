from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
import re
from types import MappingProxyType

from soma.foundation.errors import IntegrityFailure, ValidationError
from soma.foundation.strict_json import canonical_json_bytes_bounded

_PARAMETER = re.compile(r"^\{([a-z][a-z0-9_]*)\}$")
_REFERENCE_TYPES = frozenset(
    {"customer_organization", "contact", "dispatch_location"}
)
_QUERY_AUTH = "LLD12_BROWSER_QUERY_V1"
_MUTATION_AUTH = "LLD12_BROWSER_MUTATION_V1"


@dataclass(frozen=True, slots=True)
class ReferenceRouteSpec:
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
        if self.method not in {"GET", "POST", "PATCH", "PUT"}:
            raise IntegrityFailure("LLD-02 route method is invalid")
        if (
            not self.path.startswith("/api/v1/")
            or self.path.endswith("/")
            or any(value in self.path for value in ("?", "#", "//"))
        ):
            raise IntegrityFailure("LLD-02 route path is not canonical")
        if self.handler_kind not in {"query", "command"}:
            raise IntegrityFailure("LLD-02 route handler kind is invalid")
        expected_auth = _QUERY_AUTH if self.handler_kind == "query" else _MUTATION_AUTH
        if self.auth_policy != expected_auth:
            raise IntegrityFailure("LLD-02 route auth policy disagrees with owner kind")
        if self.handler_kind == "query" and self.method not in {"GET", "POST"}:
            raise IntegrityFailure("LLD-02 query route method is invalid")
        if self.handler_kind == "command" and self.method not in {"POST", "PATCH", "PUT"}:
            raise IntegrityFailure("LLD-02 command route method is invalid")
        if self.success_status not in {200, 201}:
            raise IntegrityFailure("LLD-02 route success status is invalid")
        if type(self.max_request_bytes) is not int or self.max_request_bytes <= 0:
            raise IntegrityFailure("LLD-02 route request bound is invalid")
        if not self.handler or not self.request_type or not self.response_type:
            raise IntegrityFailure("LLD-02 route authority identifier is empty")
        if len(set(self.error_codes)) != len(self.error_codes):
            raise IntegrityFailure("LLD-02 route repeats an error code")

        parameters: list[str] = []
        for segment in self.path.split("/"):
            if "{" in segment or "}" in segment:
                match = _PARAMETER.fullmatch(segment)
                if match is None:
                    raise IntegrityFailure("LLD-02 route path parameter is invalid")
                parameters.append(match.group(1))
        if len(parameters) != len(set(parameters)):
            raise IntegrityFailure("LLD-02 route repeats a path parameter")


@dataclass(frozen=True, slots=True)
class ResolvedReferenceRoute:
    spec: ReferenceRouteSpec
    path_parameters: Mapping[str, str] = field(
        default_factory=lambda: MappingProxyType({})
    )

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "path_parameters",
            MappingProxyType(dict(self.path_parameters)),
        )


@dataclass(frozen=True, slots=True)
class ReferenceHttpResponse:
    status: int
    response_type: str
    body: Mapping[str, object]

    def __post_init__(self) -> None:
        if type(self.status) is not int or not 100 <= self.status <= 599:
            raise IntegrityFailure("LLD-02 HTTP response status is invalid")
        if not self.response_type:
            raise IntegrityFailure("LLD-02 HTTP response type is empty")
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
    error_codes: list[str],
) -> ReferenceRouteSpec:
    return ReferenceRouteSpec(
        method=method,
        path=path,
        handler_kind=handler_kind,
        handler=handler,
        request_type=request_type,
        response_type=response_type,
        success_status=success_status,
        max_request_bytes=max_request_bytes,
        auth_policy=_QUERY_AUTH if handler_kind == "query" else _MUTATION_AUTH,
        error_codes=tuple(error_codes),
    )


REFERENCE_ROUTE_SPECS: tuple[ReferenceRouteSpec, ...] = (
    _route("GET", "/api/v1/reference/customer-organizations", "query", "ListActiveReferences(customer_organization)", "ReferenceListQueryV1", "ReferencePageV1", 200, 4096, ["VALIDATION_FAILED"]),
    _route("POST", "/api/v1/reference/customer-organizations", "command", "CreateCustomerOrganization", "CreateCustomerOrganizationRequestV1", "ReferenceMutationResultV1", 201, 8192, ["VALIDATION_FAILED","FIELD_BOUND_EXCEEDED","ACCOUNT_CODE_CONFLICT_REVIEW","IDEMPOTENCY_CONFLICT"]),
    _route("GET", "/api/v1/reference/customer-organizations/{customer_org_id}", "query", "GetReferenceById(customer_organization)", "ReferenceByIdQueryV1", "ReferenceDetailV1", 200, 2048, ["NOT_FOUND"]),
    _route("PATCH", "/api/v1/reference/customer-organizations/{customer_org_id}", "command", "UpdateReferenceDescriptiveData(customer_organization)", "UpdateReferenceRequestV1", "ReferenceMutationResultV1", 200, 8192, ["NOT_FOUND","REFERENCE_ARCHIVED","STALE_REVISION","FIELD_BOUND_EXCEEDED","IDEMPOTENCY_CONFLICT"]),
    _route("PUT", "/api/v1/reference/customer-organizations/{customer_org_id}/customer-account-code", "command", "SetCustomerAccountCode", "SetCustomerAccountCodeRequestV1", "ReferenceMutationResultV1", 200, 8192, ["NOT_FOUND","REFERENCE_ARCHIVED","STALE_REVISION","ACCOUNT_CODE_CONFLICT_REVIEW","FIELD_BOUND_EXCEEDED","IDEMPOTENCY_CONFLICT"]),
    _route("POST", "/api/v1/reference/customer-organizations/{customer_org_id}/customer-account-code/confirm-shared-claim", "command", "ConfirmCustomerAccountCodeSharedClaim", "ConfirmSharedClaimRequestV1", "ReferenceMutationResultV1", 200, 8192, ["NOT_FOUND","STALE_REVISION","ACCOUNT_CODE_SHARED_CONTEXT_REQUIRED","REVIEW_CONTEXT_STALE","FIELD_BOUND_EXCEEDED","IDEMPOTENCY_CONFLICT"]),
    _route("GET", "/api/v1/reference/customer-organizations/{customer_org_id}/customer-account-code/history", "query", "GetCustomerAccountCodeHistory", "AccountCodeHistoryQueryV1", "AccountCodeHistoryPageV1", 200, 4096, ["NOT_FOUND","VALIDATION_FAILED"]),
    _route("POST", "/api/v1/reference/customer-account-code/reassign", "command", "ReassignCustomerAccountCode", "ReassignAccountCodeRequestV1", "ReferenceMutationResultV1", 200, 8192, ["NOT_FOUND","STALE_REVISION","ACCOUNT_CODE_SOURCE_NOT_OWNER","REVIEW_CONTEXT_STALE","FIELD_BOUND_EXCEEDED","IDEMPOTENCY_CONFLICT"]),
    _route("GET", "/api/v1/reference/contacts", "query", "ListActiveReferences(contact)", "ReferenceListQueryV1", "ReferencePageV1", 200, 4096, ["VALIDATION_FAILED"]),
    _route("POST", "/api/v1/reference/contacts", "command", "CreateContact", "CreateContactRequestV1", "ReferenceMutationResultV1", 201, 8192, ["VALIDATION_FAILED","FIELD_BOUND_EXCEEDED","CHANNEL_INVALID","CUSTOMER_ORG_INACTIVE","IDEMPOTENCY_CONFLICT"]),
    _route("GET", "/api/v1/reference/contacts/{contact_id}", "query", "GetReferenceById(contact)", "ReferenceByIdQueryV1", "ReferenceDetailV1", 200, 2048, ["NOT_FOUND"]),
    _route("PATCH", "/api/v1/reference/contacts/{contact_id}", "command", "UpdateContactDescriptiveData", "UpdateContactRequestV1", "ReferenceMutationResultV1", 200, 8192, ["NOT_FOUND","REFERENCE_ARCHIVED","STALE_REVISION","FIELD_BOUND_EXCEEDED","IDEMPOTENCY_CONFLICT"]),
    _route("GET", "/api/v1/reference/contacts/{contact_id}/channels", "query", "GetContactChannels", "ContactChannelsQueryV1", "ContactChannelPageV1", 200, 4096, ["NOT_FOUND","VALIDATION_FAILED"]),
    _route("POST", "/api/v1/reference/contacts/{contact_id}/channels", "command", "AddContactChannel", "AddContactChannelRequestV1", "ReferenceMutationResultV1", 201, 8192, ["NOT_FOUND","REFERENCE_ARCHIVED","STALE_REVISION","CHANNEL_INVALID","FIELD_BOUND_EXCEEDED","IDEMPOTENCY_CONFLICT"]),
    _route("PATCH", "/api/v1/reference/contacts/{contact_id}/channels/{contact_channel_id}", "command", "UpdateContactChannel", "UpdateContactChannelRequestV1", "ReferenceMutationResultV1", 200, 8192, ["NOT_FOUND","CHANNEL_NOT_OWNED","REFERENCE_ARCHIVED","STALE_REVISION","CHANNEL_INVALID","FIELD_BOUND_EXCEEDED","IDEMPOTENCY_CONFLICT"]),
    _route("POST", "/api/v1/reference/contacts/{contact_id}/channels/{contact_channel_id}/archive", "command", "ArchiveContactChannel", "ArchiveContactChannelRequestV1", "ReferenceMutationResultV1", 200, 8192, ["NOT_FOUND","CHANNEL_NOT_OWNED","STALE_REVISION","IDEMPOTENCY_CONFLICT"]),
    _route("POST", "/api/v1/reference/contacts/{contact_id}/affiliation", "command", "ChangeContactAffiliation", "ChangeContactAffiliationRequestV1", "ReferenceMutationResultV1", 200, 8192, ["NOT_FOUND","REFERENCE_ARCHIVED","STALE_REVISION","CUSTOMER_ORG_INACTIVE","IDEMPOTENCY_CONFLICT"]),
    _route("GET", "/api/v1/reference/contacts/{contact_id}/affiliation-history", "query", "GetContactAffiliationHistory", "ContactAffiliationHistoryQueryV1", "ContactAffiliationHistoryPageV1", 200, 4096, ["NOT_FOUND","VALIDATION_FAILED"]),
    _route("GET", "/api/v1/reference/dispatch-locations", "query", "ListActiveReferences(dispatch_location)", "ReferenceListQueryV1", "ReferencePageV1", 200, 4096, ["VALIDATION_FAILED"]),
    _route("POST", "/api/v1/reference/dispatch-locations", "command", "CreateStandaloneDispatchLocation", "CreateDispatchLocationRequestV1", "ReferenceMutationResultV1", 201, 8192, ["VALIDATION_FAILED","FIELD_BOUND_EXCEEDED","IDEMPOTENCY_CONFLICT"]),
    _route("GET", "/api/v1/reference/dispatch-locations/{dispatch_location_id}", "query", "GetReferenceById(dispatch_location)", "ReferenceByIdQueryV1", "ReferenceDetailV1", 200, 2048, ["NOT_FOUND"]),
    _route("PATCH", "/api/v1/reference/dispatch-locations/{dispatch_location_id}", "command", "UpdateReferenceDescriptiveData(dispatch_location)", "UpdateReferenceRequestV1", "ReferenceMutationResultV1", 200, 8192, ["NOT_FOUND","REFERENCE_ARCHIVED","STALE_REVISION","FIELD_BOUND_EXCEEDED","IDEMPOTENCY_CONFLICT"]),
    _route("POST", "/api/v1/reference/{reference_type}/{reference_id}/archive-preview", "query", "PreviewReferenceArchive", "ReferenceArchivePreviewQueryV1", "ArchivePreviewV1", 200, 4096, ["NOT_FOUND","DEPENDENCY_VALIDATION_FAILED","VALIDATION_FAILED"]),
    _route("POST", "/api/v1/reference/{reference_type}/{reference_id}/archive", "command", "ArchiveReference", "ArchiveReferenceRequestV1", "ReferenceMutationResultV1", 200, 8192, ["NOT_FOUND","STALE_REVISION","ARCHIVE_BLOCKED","DEPENDENCY_VALIDATION_FAILED","IDEMPOTENCY_CONFLICT"]),
    _route("POST", "/api/v1/reference/{reference_type}/{reference_id}/reactivate", "command", "ReactivateReference", "ReactivateReferenceRequestV1", "ReferenceMutationResultV1", 200, 8192, ["NOT_FOUND","STALE_REVISION","REACTIVATION_BLOCKED","DEPENDENCY_VALIDATION_FAILED","IDEMPOTENCY_CONFLICT"]),
    _route("GET", "/api/v1/settings/{setting_key}", "query", "GetSetting", "GetSettingQueryV1", "SettingValueV1", 200, 2048, ["SETTING_UNKNOWN","SETTING_CONTRACT_MISMATCH","SETTING_SECRET_FORBIDDEN"]),
    _route("PUT", "/api/v1/settings/{setting_key}", "command", "WriteSetting", "WriteSettingRequestV1", "SettingValueV1", 200, 16384, ["SETTING_UNKNOWN","SETTING_CONTRACT_MISMATCH","SETTING_SECRET_FORBIDDEN","STALE_REVISION","VALIDATION_FAILED","IDEMPOTENCY_CONFLICT"]),
    _route("POST", "/api/v1/reference/customer-account-code/review-preview", "query", "PreviewCustomerAccountCodeConflict", "AccountCodeReviewPreviewQueryV1", "AccountCodeReviewPreviewV1", 200, 8192, ["MATCH_INPUT_INVALID","MATCH_PROFILE_UNSUPPORTED","NOT_FOUND"]),
    _route("POST", "/api/v1/reference/contacts/{contact_id}/channels/validate-for-use", "query", "ValidateContactChannelForUse", "ValidateContactChannelQueryV1", "ChannelUseValidationV1", 200, 4096, ["NOT_FOUND","CHANNEL_NOT_OWNED","MATCH_INPUT_INVALID"]),
    _route("POST", "/api/v1/reference/match/customer-organization", "query", "MatchCustomerOrganization", "MatchCustomerOrganizationQueryV1", "CandidateResultV1", 200, 8192, ["MATCH_INPUT_INVALID","MATCH_PROFILE_UNSUPPORTED","VALIDATION_FAILED"]),
    _route("POST", "/api/v1/reference/match/contact", "query", "MatchContact", "MatchContactQueryV1", "CandidateResultV1", 200, 8192, ["MATCH_INPUT_INVALID","MATCH_PROFILE_UNSUPPORTED","VALIDATION_FAILED"]),
    _route("PATCH", "/api/v1/local-user-profile/display-name", "command", "UpdateLocalUserProfileDisplayName", "UpdateLocalUserProfileDisplayNameRequestV1", "LocalUserProfileV1", 200, 4096, ["NOT_FOUND","STALE_REVISION","FIELD_BOUND_EXCEEDED","VALIDATION_FAILED","IDEMPOTENCY_CONFLICT"]),
)


def resolve_reference_route(
    method: str,
    path: str,
    specs: Sequence[ReferenceRouteSpec] = REFERENCE_ROUTE_SPECS,
) -> ResolvedReferenceRoute | None:
    if (
        not isinstance(method, str)
        or not method
        or not isinstance(path, str)
        or not path.startswith("/")
        or "?" in path
        or "#" in path
        or "//" in path
    ):
        raise ValidationError(
            "LLD-02 route resolver requires method and one absolute path without query"
        )
    actual_method = method.upper()
    actual_segments = path.split("/")

    # Prefer literal authority over parameterized authority independently of
    # registry order. Route values are never interpolated into SQL identifiers.
    ordered = sorted(
        specs,
        key=lambda item: sum(
            1 for segment in item.path.split("/") if _PARAMETER.fullmatch(segment)
        ),
    )
    for spec in ordered:
        if spec.method != actual_method:
            continue
        expected_segments = spec.path.split("/")
        if len(expected_segments) != len(actual_segments):
            continue
        params: dict[str, str] = {}
        for expected, supplied in zip(expected_segments, actual_segments, strict=True):
            parameter = _PARAMETER.fullmatch(expected)
            if parameter is None:
                if expected != supplied:
                    break
                continue
            if not supplied or "/" in supplied:
                break
            name = parameter.group(1)
            if name == "reference_type" and supplied not in _REFERENCE_TYPES:
                break
            params[name] = supplied
        else:
            return ResolvedReferenceRoute(spec=spec, path_parameters=params)
    return None


OwnerHandler = Callable[
    [ResolvedReferenceRoute, Mapping[str, object]],
    Mapping[str, object],
]


class ReferenceRouteAdapter:
    """Thin already-authenticated LLD-02 transport binding.

    LLD-12 owns raw HTTP authentication and byte enforcement. This adapter
    resolves only the closed route authority, applies a bounded decoded-object
    sanity check, and invokes an injected owning handler. It never opens
    persistence, derives matching/lifecycle authority, or constructs SQL.
    """

    def __init__(
        self,
        handlers: Mapping[str, OwnerHandler],
        specs: Sequence[ReferenceRouteSpec] = REFERENCE_ROUTE_SPECS,
    ) -> None:
        keys = [(spec.method, spec.path) for spec in specs]
        if len(keys) != len(set(keys)):
            raise IntegrityFailure("LLD-02 route registry has duplicate method/path authority")
        shapes = [
            (
                spec.method,
                "/".join(
                    "{}" if _PARAMETER.fullmatch(part) else part
                    for part in spec.path.split("/")
                ),
            )
            for spec in specs
        ]
        if len(shapes) != len(set(shapes)):
            raise IntegrityFailure("LLD-02 route registry has ambiguous parameter authority")
        if any(spec.method == "DELETE" for spec in specs):
            raise IntegrityFailure("LLD-02 history-bearing references have no DELETE route")
        self._specs = tuple(specs)
        self._handlers = MappingProxyType(dict(handlers))

    @property
    def specs(self) -> tuple[ReferenceRouteSpec, ...]:
        return self._specs

    def dispatch(
        self,
        method: str,
        path: str,
        decoded: Mapping[str, object] | None = None,
    ) -> ReferenceHttpResponse | None:
        resolved = resolve_reference_route(method, path, self._specs)
        if resolved is None:
            return None
        if decoded is None:
            payload: dict[str, object] = {}
        elif isinstance(decoded, Mapping):
            payload = dict(decoded)
        else:
            raise ValidationError("decoded LLD-02 request must be a mapping")
        canonical_json_bytes_bounded(
            payload,
            max_bytes=resolved.spec.max_request_bytes,
            max_depth=32,
            max_collection_items=max(512, resolved.spec.max_request_bytes),
        )
        owner = self._handlers.get(resolved.spec.handler)
        if owner is None:
            raise IntegrityFailure(
                f"LLD-02 route handler {resolved.spec.handler!r} is not assembled"
            )
        body = owner(resolved, MappingProxyType(payload))
        if not isinstance(body, Mapping):
            raise IntegrityFailure("LLD-02 owner adapter returned a non-object response")
        return ReferenceHttpResponse(
            status=resolved.spec.success_status,
            response_type=resolved.spec.response_type,
            body=body,
        )


def build_route_adapter(
    handlers: Mapping[str, OwnerHandler],
) -> ReferenceRouteAdapter:
    return ReferenceRouteAdapter(handlers)


__all__ = [
    "REFERENCE_ROUTE_SPECS",
    "ReferenceHttpResponse",
    "ReferenceRouteAdapter",
    "ReferenceRouteSpec",
    "ResolvedReferenceRoute",
    "build_route_adapter",
    "resolve_reference_route",
]
