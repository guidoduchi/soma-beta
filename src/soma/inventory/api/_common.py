from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
import re
from types import MappingProxyType

from soma.foundation.errors import IntegrityFailure, ValidationError

_API_PREFIX = "/api/v1/inventory"
_QUERY_AUTH = "LLD12_BROWSER_QUERY_V1"
_MUTATION_AUTH = "LLD12_BROWSER_MUTATION_V1"
_ALLOWED_METHODS = frozenset({"GET", "POST", "PATCH"})
_ALLOWED_HANDLER_KINDS = frozenset({"query", "command"})
_PARAMETER = re.compile(r"^\\{([a-z][a-z0-9_]*)\\}$")


@dataclass(frozen=True, slots=True)
class InventoryRouteSpec:
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
            raise IntegrityFailure("LLD-07 route method is invalid")
        if not self.path.startswith(_API_PREFIX) or "?" in self.path or "#" in self.path or "//" in self.path:
            raise IntegrityFailure("LLD-07 route path is not canonical")
        if self.handler_kind not in _ALLOWED_HANDLER_KINDS:
            raise IntegrityFailure("LLD-07 route handler kind is invalid")
        expected_auth = _QUERY_AUTH if self.handler_kind == "query" else _MUTATION_AUTH
        if self.auth_policy != expected_auth:
            raise IntegrityFailure("LLD-07 route auth policy disagrees with handler kind")
        if self.handler_kind == "command" and self.method not in {"POST", "PATCH"}:
            raise IntegrityFailure("LLD-07 command route method is invalid")
        if self.handler_kind == "query" and self.method not in {"GET", "POST"}:
            raise IntegrityFailure("LLD-07 query route method is invalid")
        if self.success_status not in {200, 201}:
            raise IntegrityFailure("LLD-07 route success status is invalid")
        if type(self.max_request_bytes) is not int or self.max_request_bytes <= 0:
            raise IntegrityFailure("LLD-07 route request bound is invalid")
        if not self.handler or not self.request_type or not self.response_type:
            raise IntegrityFailure("LLD-07 route authority identifier is empty")
        if len(set(self.error_codes)) != len(self.error_codes):
            raise IntegrityFailure("LLD-07 route repeats an error code")
        parameters: list[str] = []
        for segment in self.path.split("/"):
            if segment.startswith("{") or segment.endswith("}"):
                match = _PARAMETER.fullmatch(segment)
                if match is None:
                    raise IntegrityFailure("LLD-07 route path parameter is invalid")
                parameters.append(match.group(1))
        if len(parameters) != len(set(parameters)):
            raise IntegrityFailure("LLD-07 route repeats a path parameter")


@dataclass(frozen=True, slots=True)
class ResolvedInventoryRoute:
    spec: InventoryRouteSpec
    path_parameters: Mapping[str, str] = field(default_factory=lambda: MappingProxyType({}))

    def __post_init__(self) -> None:
        object.__setattr__(self, "path_parameters", MappingProxyType(dict(self.path_parameters)))


@dataclass(frozen=True, slots=True)
class InventoryHttpResponse:
    status: int
    response_type: str
    body: Mapping[str, object]

    def __post_init__(self) -> None:
        if type(self.status) is not int or not 100 <= self.status <= 599:
            raise IntegrityFailure("LLD-07 HTTP response status is invalid")
        if not self.response_type:
            raise IntegrityFailure("LLD-07 HTTP response type is empty")
        object.__setattr__(self, "body", MappingProxyType(dict(self.body)))


def route_spec(
    method: str,
    path: str,
    handler_kind: str,
    handler: str,
    request_type: str,
    response_type: str,
    success_status: int,
    max_request_bytes: int,
    auth_policy: str,
    error_codes: list[str],
) -> InventoryRouteSpec:
    return InventoryRouteSpec(
        method=method,
        path=path,
        handler_kind=handler_kind,
        handler=handler,
        request_type=request_type,
        response_type=response_type,
        success_status=success_status,
        max_request_bytes=max_request_bytes,
        auth_policy=auth_policy,
        error_codes=tuple(error_codes),
    )


def resolve_inventory_route(
    specs: Sequence[InventoryRouteSpec],
    method: str,
    path: str,
) -> ResolvedInventoryRoute | None:
    if not isinstance(method, str) or not method:
        raise ValidationError("HTTP method must be nonempty text")
    if not isinstance(path, str) or not path.startswith("/") or "?" in path or "#" in path:
        raise ValidationError("route resolver requires one absolute path without query or fragment")
    actual_method = method.upper()
    actual_segments = path.split("/")
    for spec in specs:
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
            elif not actual or "/" in actual:
                matched = False
                break
            else:
                params[parameter.group(1)] = actual
        if matched:
            return ResolvedInventoryRoute(spec=spec, path_parameters=params)
    return None


OwnerHandler = Callable[[ResolvedInventoryRoute, Mapping[str, object]], Mapping[str, object]]


class InventoryRouteAdapter:
    """Thin already-authenticated transport adapter.

    LLD-12 enforces raw byte bounds/authentication before this adapter. Injected handlers
    bind decoded DTOs to owning query/services; this adapter never calculates Inventory
    eligibility, lifecycle, revisions or authority.
    """

    def __init__(
        self,
        specs: Sequence[InventoryRouteSpec],
        handlers: Mapping[str, OwnerHandler],
    ) -> None:
        keys = [(spec.method, spec.path) for spec in specs]
        if len(keys) != len(set(keys)):
            raise IntegrityFailure("LLD-07 route registry has duplicate method/path authority")
        self._specs = tuple(specs)
        self._handlers = MappingProxyType(dict(handlers))

    @property
    def specs(self) -> tuple[InventoryRouteSpec, ...]:
        return self._specs

    def dispatch(
        self,
        method: str,
        path: str,
        decoded: Mapping[str, object] | None = None,
    ) -> InventoryHttpResponse | None:
        resolved = resolve_inventory_route(self._specs, method, path)
        if resolved is None:
            return None
        if decoded is None:
            payload: dict[str, object] = {}
        elif isinstance(decoded, Mapping):
            payload = dict(decoded)
        else:
            raise ValidationError("decoded LLD-07 request must be a mapping")
        if any(not isinstance(key, str) or not key for key in payload):
            raise ValidationError("decoded LLD-07 request field names must be nonempty text")
        handler = self._handlers.get(resolved.spec.handler)
        if handler is None:
            raise IntegrityFailure(
                f"LLD-07 route handler {resolved.spec.handler!r} is not assembled"
            )
        body = handler(resolved, MappingProxyType(payload))
        if not isinstance(body, Mapping):
            raise IntegrityFailure("LLD-07 owner adapter returned a non-object response")
        return InventoryHttpResponse(
            status=resolved.spec.success_status,
            response_type=resolved.spec.response_type,
            body=body,
        )


__all__ = [
    "InventoryHttpResponse",
    "InventoryRouteAdapter",
    "InventoryRouteSpec",
    "OwnerHandler",
    "ResolvedInventoryRoute",
    "resolve_inventory_route",
    "route_spec",
]
