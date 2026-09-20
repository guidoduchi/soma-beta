from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
import re
from types import MappingProxyType

from soma.foundation.errors import IntegrityFailure, ValidationError
from soma.foundation.strict_json import canonical_json_bytes_bounded

_PARAMETER = re.compile(r"^\{([a-z][a-z0-9_]*)\}$")


@dataclass(frozen=True, slots=True)
class ProductLineSlaRouteSpec:
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
        if self.method not in {"GET", "POST"}:
            raise IntegrityFailure("LLD-06 route method is invalid")
        if not self.path.startswith("/api/v1/") or self.path.endswith("/") or any(value in self.path for value in ("?", "#", "//")):
            raise IntegrityFailure("LLD-06 route path is not canonical")
        if self.handler_kind not in {"query", "command"}:
            raise IntegrityFailure("LLD-06 route handler kind is invalid")
        expected_auth = (
            "LLD12_BROWSER_QUERY_V1"
            if self.handler_kind == "query"
            else "LLD12_BROWSER_MUTATION_V1"
        )
        if self.auth_policy != expected_auth:
            raise IntegrityFailure("LLD-06 route auth policy disagrees with owner kind")
        if self.handler_kind == "command" and self.method != "POST":
            raise IntegrityFailure("LLD-06 command route must use POST")
        if self.success_status not in {200, 201, 202}:
            raise IntegrityFailure("LLD-06 route success status is invalid")
        if type(self.max_request_bytes) is not int or self.max_request_bytes <= 0:
            raise IntegrityFailure("LLD-06 route request bound is invalid")
        parameters = [
            match.group(1)
            for segment in self.path.split("/")
            if (match := _PARAMETER.fullmatch(segment)) is not None
        ]
        if any(("{" in segment or "}" in segment) and _PARAMETER.fullmatch(segment) is None
               for segment in self.path.split("/")):
            raise IntegrityFailure("LLD-06 route parameter is invalid")
        if len(parameters) != len(set(parameters)):
            raise IntegrityFailure("LLD-06 route repeats a path parameter")


@dataclass(frozen=True, slots=True)
class ResolvedProductLineSlaRoute:
    spec: ProductLineSlaRouteSpec
    path_parameters: Mapping[str, str] = field(
        default_factory=lambda: MappingProxyType({})
    )

    def __post_init__(self) -> None:
        object.__setattr__(self, "path_parameters", MappingProxyType(dict(self.path_parameters)))


@dataclass(frozen=True, slots=True)
class ProductLineSlaHttpResponse:
    status: int
    response_type: str
    body: Mapping[str, object]

    def __post_init__(self) -> None:
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
) -> ProductLineSlaRouteSpec:
    return ProductLineSlaRouteSpec(
        method, path, handler_kind, handler, request_type, response_type,
        success_status, max_request_bytes,
        "LLD12_BROWSER_QUERY_V1" if handler_kind == "query" else "LLD12_BROWSER_MUTATION_V1",
        tuple(error_codes),
    )


PRODUCT_LINE_SLA_ROUTE_SPECS: tuple[ProductLineSlaRouteSpec, ...] = (
    _route("GET", "/api/v1/product-lines", "query", "ListProductLines", "CatalogListQueryV1", "CatalogPageV1", 200, 4096, ["VALIDATION_FAILED"]),
    _route("POST", "/api/v1/product-lines", "command", "CreateProductLine", "ProductLineCommandRequestV1", "CatalogMutationResultV1", 201, 8192, ["SLA_POLICY_INVALID", "IDEMPOTENCY_CONFLICT"]),
    _route("POST", "/api/v1/product-lines/{id}/edit", "command", "UpdateProductLine", "ProductLineCommandRequestV1", "CatalogMutationResultV1", 200, 8192, ["SLA_CATALOG_NOT_FOUND", "SLA_CATALOG_ARCHIVED", "SLA_STALE", "IDEMPOTENCY_CONFLICT"]),
    _route("POST", "/api/v1/product-lines/{id}/lifecycle", "command", "SetCatalogLifecycle", "ProductLineCommandRequestV1", "CatalogMutationResultV1", 200, 4096, ["SLA_CATALOG_NOT_FOUND", "SLA_DEPENDENCY_INDETERMINATE", "SLA_STALE", "IDEMPOTENCY_CONFLICT"]),
    _route("GET", "/api/v1/contracts", "query", "ListContracts", "CatalogListQueryV1", "CatalogPageV1", 200, 4096, ["VALIDATION_FAILED"]),
    _route("POST", "/api/v1/contracts", "command", "CreateContract", "ContractCommandRequestV1", "CatalogMutationResultV1", 201, 8192, ["SLA_CLASSIFICATION_CUSTOMER_UNRESOLVED", "IDEMPOTENCY_CONFLICT"]),
    _route("POST", "/api/v1/contracts/{id}/lifecycle", "command", "SetCatalogLifecycle", "ContractCommandRequestV1", "CatalogMutationResultV1", 200, 4096, ["SLA_CATALOG_NOT_FOUND", "SLA_DEPENDENCY_INDETERMINATE", "SLA_STALE", "IDEMPOTENCY_CONFLICT"]),
    _route("GET", "/api/v1/contract-product-lines", "query", "ListContractProductLines", "CatalogListQueryV1", "CatalogPageV1", 200, 4096, ["VALIDATION_FAILED"]),
    _route("POST", "/api/v1/contract-product-lines", "command", "CreateContractProductLine", "ContractProductLineCommandRequestV1", "CatalogMutationResultV1", 201, 8192, ["SLA_CATALOG_NOT_FOUND", "SLA_CLASSIFICATION_CROSS_CUSTOMER", "IDEMPOTENCY_CONFLICT"]),
    _route("POST", "/api/v1/contract-product-lines/{id}/policy", "command", "ReviseSlaPolicy", "ReviseSlaPolicyRequestV1", "CatalogMutationResultV1", 200, 32768, ["SLA_CATALOG_NOT_FOUND", "SLA_CATALOG_ARCHIVED", "SLA_POLICY_INVALID", "SLA_POLICY_STALE", "IDEMPOTENCY_CONFLICT"]),
    _route("POST", "/api/v1/contract-product-lines/{id}/lifecycle", "command", "SetCatalogLifecycle", "ContractProductLineCommandRequestV1", "CatalogMutationResultV1", 200, 4096, ["SLA_CATALOG_NOT_FOUND", "SLA_DEPENDENCY_INDETERMINATE", "SLA_STALE", "IDEMPOTENCY_CONFLICT"]),
    _route("GET", "/api/v1/contract-product-lines/{id}/policy-history", "query", "GetPolicyHistory", "PolicyHistoryQueryV1", "PolicyHistoryPageV1", 200, 4096, ["SLA_CATALOG_NOT_FOUND", "VALIDATION_FAILED"]),
    _route("GET", "/api/v1/sla/classification-mappings", "query", "ListClassificationMappings", "ClassificationMappingListQueryV1", "ClassificationMappingPageV1", 200, 4096, ["VALIDATION_FAILED"]),
    _route("POST", "/api/v1/sla/classification-mappings", "command", "CreateClassificationMapping", "ClassificationMappingCommandRequestV1", "CatalogMutationResultV1", 201, 8192, ["SLA_CATALOG_NOT_FOUND", "SLA_CLASSIFICATION_CROSS_CUSTOMER", "IDEMPOTENCY_CONFLICT"]),
    _route("POST", "/api/v1/sla/classification-mappings/{id}/supersede", "command", "SupersedeClassificationMapping", "ClassificationMappingCommandRequestV1", "CatalogMutationResultV1", 200, 8192, ["SLA_CATALOG_NOT_FOUND", "SLA_STALE", "IDEMPOTENCY_CONFLICT"]),
    _route("POST", "/api/v1/service-requests/{sr_id}/classification/preview", "query", "PreviewSrClassification", "ClassificationPreviewQueryV1", "ClassificationPreviewV1", 200, 8192, ["SLA_CLASSIFICATION_CUSTOMER_UNRESOLVED", "SLA_CLASSIFICATION_CROSS_CUSTOMER", "SLA_CLASSIFICATION_MAPPING_MISSING", "SLA_CLASSIFICATION_MAPPING_AMBIGUOUS", "SLA_CLASSIFICATION_INCOMPATIBLE", "SLA_INPUT_INDETERMINATE"]),
    _route("POST", "/api/v1/service-requests/{sr_id}/classification", "command", "ClassifyServiceRequest", "ClassifyServiceRequestRequestV1", "ClassificationMutationResultV1", 200, 8192, ["SLA_CLASSIFICATION_CUSTOMER_UNRESOLVED", "SLA_CLASSIFICATION_CROSS_CUSTOMER", "SLA_CLASSIFICATION_MAPPING_MISSING", "SLA_CLASSIFICATION_MAPPING_AMBIGUOUS", "SLA_CLASSIFICATION_STALE", "SLA_CLASSIFICATION_INCOMPATIBLE", "SLA_INPUT_INDETERMINATE", "IDEMPOTENCY_CONFLICT"]),
    _route("POST", "/api/v1/service-requests/{sr_id}/classification/clear", "command", "ClearSrClassification", "ClearServiceRequestClassificationRequestV1", "ClassificationMutationResultV1", 200, 4096, ["SLA_CLASSIFICATION_STALE", "IDEMPOTENCY_CONFLICT"]),
    _route("GET", "/api/v1/service-requests/{sr_id}/classification-history", "query", "GetSrClassificationHistory", "ClassificationHistoryQueryV1", "ClassificationHistoryPageV1", 200, 4096, ["VALIDATION_FAILED"]),
    _route("POST", "/api/v1/service-requests/classification/batch-preview", "query", "PreviewBatchClassification", "BatchClassificationPreviewQueryV1", "BatchClassificationPreviewV1", 200, 65536, ["SLA_CLASSIFICATION_CUSTOMER_UNRESOLVED", "SLA_CLASSIFICATION_MAPPING_AMBIGUOUS", "SLA_CLASSIFICATION_INCOMPATIBLE", "SLA_INPUT_INDETERMINATE"]),
    _route("POST", "/api/v1/service-requests/classification/batch-apply", "command", "ApplyBatchClassification", "ApplyBatchClassificationRequestV1", "BatchClassificationResultV1", 200, 65536, ["SLA_CLASSIFICATION_STALE", "SLA_CLASSIFICATION_CROSS_CUSTOMER", "SLA_CLASSIFICATION_INCOMPATIBLE", "SLA_INPUT_INDETERMINATE", "IDEMPOTENCY_CONFLICT"]),
    _route("GET", "/api/v1/service-requests/{sr_id}/sla", "query", "GetIndividualSla", "IndividualSlaQueryV1", "IndividualSlaProjectionV1", 200, 4096, ["SLA_INPUT_INDETERMINATE"]),
    _route("GET", "/api/v1/sla/cohorts", "query", "ListCanonicalCohorts", "CohortListQueryV1", "CohortPageV1", 200, 4096, ["SLA_INPUT_INDETERMINATE", "VALIDATION_FAILED"]),
    _route("GET", "/api/v1/sla/cohorts/{cohort_key}", "query", "GetCohortMembers", "CohortDetailQueryV1", "CohortDetailV1", 200, 4096, ["SLA_INPUT_INDETERMINATE", "VALIDATION_FAILED"]),
    _route("GET", "/api/v1/sla/warnings", "query", "ListSlaWarnings", "SlaWarningListQueryV1", "SlaWarningPageV1", 200, 4096, ["SLA_INPUT_INDETERMINATE", "VALIDATION_FAILED"]),
    _route("POST", "/api/v1/reports", "command", "StartSlaReportGeneration", "StartSlaReportGenerationRequestV1", "ReportAttemptV1", 202, 16384, ["SLA_REPORT_SCOPE_INVALID", "SLA_REPORT_CONTRIBUTOR_FAILED", "SLA_INPUT_INDETERMINATE", "IDEMPOTENCY_CONFLICT"]),
    _route("GET", "/api/v1/reports", "query", "ListReportAttempts", "ReportListQueryV1", "ReportPageV1", 200, 4096, ["VALIDATION_FAILED"]),
    _route("GET", "/api/v1/reports/{report_attempt_id}", "query", "GetReportAttempt", "ReportDetailQueryV1", "ReportAttemptV1", 200, 2048, ["SLA_CATALOG_NOT_FOUND"]),
    _route("POST", "/api/v1/reports/{report_attempt_id}/cancel", "command", "CancelSlaReportAttempt", "CancelSlaReportAttemptRequestV1", "ReportAttemptV1", 200, 4096, ["SLA_REPORT_ATTEMPT_STATE", "SLA_REPORT_COMPLETED_IMMUTABLE", "SLA_REPORT_CANCEL_UNSAFE", "IDEMPOTENCY_CONFLICT"]),
)


def resolve_route(
    method: str,
    path: str,
    specs: Sequence[ProductLineSlaRouteSpec] = PRODUCT_LINE_SLA_ROUTE_SPECS,
) -> ResolvedProductLineSlaRoute | None:
    if not isinstance(method, str) or not isinstance(path, str) or not path.startswith("/") or "?" in path or "#" in path:
        raise ValidationError("LLD-06 route resolver requires method and absolute path without query")
    actual = path.split("/")
    # Literal routes precede parameterized routes, independent of registry order.
    for spec in sorted(specs, key=lambda item: item.path.count("{")):
        expected = spec.path.split("/")
        if spec.method != method.upper() or len(actual) != len(expected):
            continue
        params: dict[str, str] = {}
        for wanted, supplied in zip(expected, actual, strict=True):
            match = _PARAMETER.fullmatch(wanted)
            if match is None and wanted != supplied:
                break
            if match is not None:
                if not supplied:
                    break
                params[match.group(1)] = supplied
        else:
            return ResolvedProductLineSlaRoute(spec, params)
    return None


OwnerHandler = Callable[[ResolvedProductLineSlaRoute, Mapping[str, object]], Mapping[str, object]]


class ProductLineSlaRouteAdapter:
    """Thin binding after browser authentication and strict request decoding.

    The HTTP host enforces the raw wire-byte limit and declared auth policy.
    Injected owner bindings validate their request DTO and serialize their result;
    this adapter neither acquires persistence nor calculates domain authority.
    """

    def __init__(self, handlers: Mapping[str, OwnerHandler], specs: Sequence[ProductLineSlaRouteSpec] = PRODUCT_LINE_SLA_ROUTE_SPECS) -> None:
        keys = [(spec.method, spec.path) for spec in specs]
        if len(keys) != len(set(keys)):
            raise IntegrityFailure("LLD-06 route registry has duplicate authority")
        shapes = [(spec.method, "/".join("{}" if _PARAMETER.fullmatch(part) else part
                                        for part in spec.path.split("/"))) for spec in specs]
        if len(shapes) != len(set(shapes)):
            raise IntegrityFailure("LLD-06 route registry has ambiguous parameter authority")
        self._specs = tuple(specs)
        self._handlers = MappingProxyType(dict(handlers))

    def dispatch(self, method: str, path: str, decoded: Mapping[str, object] | None = None) -> ProductLineSlaHttpResponse | None:
        resolved = resolve_route(method, path, self._specs)
        if resolved is None:
            return None
        if decoded is not None and not isinstance(decoded, Mapping):
            raise ValidationError("decoded LLD-06 request must be a mapping")
        payload = {} if decoded is None else dict(decoded)
        canonical_json_bytes_bounded(
            payload, max_bytes=resolved.spec.max_request_bytes,
            max_depth=resolved.spec.max_request_bytes,
            max_collection_items=resolved.spec.max_request_bytes,
        )
        owner = self._handlers.get(resolved.spec.handler)
        if owner is None:
            raise IntegrityFailure(f"LLD-06 route handler {resolved.spec.handler!r} is not assembled")
        body = owner(resolved, MappingProxyType(payload))
        if not isinstance(body, Mapping):
            raise IntegrityFailure("LLD-06 owner adapter returned a non-object response")
        return ProductLineSlaHttpResponse(resolved.spec.success_status, resolved.spec.response_type, body)


def build_route_adapter(handlers: Mapping[str, OwnerHandler]) -> ProductLineSlaRouteAdapter:
    return ProductLineSlaRouteAdapter(handlers)


__all__ = [
    "PRODUCT_LINE_SLA_ROUTE_SPECS",
    "ProductLineSlaHttpResponse",
    "ProductLineSlaRouteAdapter",
    "ProductLineSlaRouteSpec",
    "ResolvedProductLineSlaRoute",
    "build_route_adapter",
    "resolve_route",
]
