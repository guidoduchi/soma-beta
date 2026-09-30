"""Already-authenticated LLD-08 route resolution and owner dispatch."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
import re
from types import MappingProxyType

from soma.foundation.errors import IntegrityFailure, ValidationError
from soma.foundation.identifiers import require_uuid4
from soma.foundation.strict_json import canonical_json_bytes_bounded
from soma.infrastructure.contracts.infrastructure import REGISTRY, validate_value


_PARAMETER = re.compile(r"^\{([a-z][a-z0-9_]*)\}$")
_COMMAND_TYPE = re.compile(r"^COMMAND_ENVELOPE_V1<([A-Z0-9_]+)>$")


@dataclass(frozen=True, slots=True)
class InfrastructureRouteSpec:
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
    path_fields: tuple[str, ...]

    def __post_init__(self) -> None:
        if self.method not in {"GET", "POST", "PATCH"} or not self.path.startswith(
            "/api/v1/infrastructure/"
        ) or any(token in self.path for token in ("?", "#", "//")):
            raise IntegrityFailure("LLD-08 route method or path is invalid")
        if self.handler_kind not in {"query", "command"}:
            raise IntegrityFailure("LLD-08 route handler kind is invalid")
        expected_auth = (
            "LOCAL_ADMIN_AUTHENTICATED_V1" if self.handler_kind == "query"
            else "LOCAL_ADMIN_AUTHENTICATED_CSRF_V1"
        )
        if self.auth_policy != expected_auth:
            raise IntegrityFailure("LLD-08 route authentication policy disagrees with handler kind")
        if self.method == "GET" and self.handler_kind != "query":
            raise IntegrityFailure("LLD-08 GET cannot mutate")
        if self.method == "PATCH" and self.handler_kind != "command":
            raise IntegrityFailure("LLD-08 PATCH cannot be a query")
        if self.success_status not in {200, 201, 202}:
            raise IntegrityFailure("LLD-08 route success status is invalid")
        if type(self.max_request_bytes) is not int or self.max_request_bytes < 1:
            raise IntegrityFailure("LLD-08 route byte bound is invalid")
        if len(set(self.error_codes)) != len(self.error_codes):
            raise IntegrityFailure("LLD-08 route repeats an error code")
        parameters = tuple(
            match.group(1)
            for segment in self.path.split("/")
            if (match := _PARAMETER.fullmatch(segment)) is not None
        )
        if parameters != self.path_fields or len(parameters) != len(set(parameters)):
            raise IntegrityFailure("LLD-08 route path fields disagree with the contract")
        if self.handler_kind == "command" and _COMMAND_TYPE.fullmatch(self.request_type) is None:
            raise IntegrityFailure("LLD-08 command route lacks a typed command envelope")


def _spec(row: dict) -> InfrastructureRouteSpec:
    return InfrastructureRouteSpec(
        method=row["method"], path=row["path"], handler_kind=row["handler_kind"],
        handler=row["handler"], request_type=row["request_type"],
        response_type=row["response_type"], success_status=row["success_status"],
        max_request_bytes=row["max_request_bytes"], auth_policy=row["auth_policy"],
        error_codes=tuple(row["error_codes"]),
        path_fields=tuple(row["input_ownership"]["path_fields"]),
    )


INFRASTRUCTURE_ROUTE_SPECS = tuple(_spec(row) for row in REGISTRY["routes"])
_ROUTE_KEYS = tuple((spec.method, spec.path) for spec in INFRASTRUCTURE_ROUTE_SPECS)
if len(_ROUTE_KEYS) != len(set(_ROUTE_KEYS)):
    raise IntegrityFailure("LLD-08 route registry has duplicate method/path authority")
_ROUTE_SHAPES = tuple((
    spec.method,
    tuple("{}" if _PARAMETER.fullmatch(part) else part for part in spec.path.split("/")),
) for spec in INFRASTRUCTURE_ROUTE_SPECS)
if len(_ROUTE_SHAPES) != len(set(_ROUTE_SHAPES)):
    raise IntegrityFailure("LLD-08 route registry has ambiguous parameter authority")
_COMMANDS = {item["name"] for item in REGISTRY["commands"]}
_QUERIES = {item["name"] for item in REGISTRY["queries"]}
if any(spec.handler not in (_COMMANDS if spec.handler_kind == "command" else _QUERIES)
       for spec in INFRASTRUCTURE_ROUTE_SPECS):
    raise IntegrityFailure("LLD-08 route targets an undeclared owner handler")
_RESOLUTION_ORDER = tuple(sorted(
    INFRASTRUCTURE_ROUTE_SPECS,
    key=lambda spec: sum(_PARAMETER.fullmatch(part) is not None for part in spec.path.split("/")),
))


@dataclass(frozen=True, slots=True)
class ResolvedInfrastructureRoute:
    spec: InfrastructureRouteSpec
    path_parameters: Mapping[str, str]


def resolve_route(method: str, path: str) -> ResolvedInfrastructureRoute | None:
    if (not isinstance(method, str) or not method or not isinstance(path, str)
            or not path.startswith("/") or any(token in path for token in ("?", "#", "//"))):
        raise ValidationError("LLD-08 route requires method and absolute path without query")
    actual = path.split("/")
    for spec in _RESOLUTION_ORDER:
        if spec.method != method.upper():
            continue
        expected = spec.path.split("/")
        if len(expected) != len(actual):
            continue
        fields = {}
        for left, right in zip(expected, actual, strict=True):
            match = _PARAMETER.fullmatch(left)
            if match is None:
                if left != right:
                    break
            elif not right or any(char in right for char in ("/", "\\", "%", "\x00")):
                break
            else:
                fields[match.group(1)] = right
        else:
            return ResolvedInfrastructureRoute(spec, MappingProxyType(fields))
    return None


OwnerHandler = Callable[[ResolvedInfrastructureRoute, Mapping[str, object]], Mapping[str, object]]


@dataclass(frozen=True, slots=True)
class InfrastructureHttpResponse:
    status: int
    response_type: str
    body: Mapping[str, object]


class InfrastructureRouteAdapter:
    """Bind decoded DTOs to injected owner handlers after LLD-12 auth/CSRF/byte checks."""

    def __init__(self, handlers: Mapping[str, OwnerHandler]) -> None:
        self._handlers = MappingProxyType(dict(handlers))

    def dispatch(self, method: str, path: str,
                 decoded: Mapping[str, object] | None = None) -> InfrastructureHttpResponse | None:
        resolved = resolve_route(method, path)
        if resolved is None:
            return None
        if decoded is None:
            body = {}
        elif isinstance(decoded, Mapping):
            body = dict(decoded)
        else:
            raise ValidationError("Decoded LLD-08 request must be an object")
        if any(not isinstance(key, str) or not key for key in body):
            raise ValidationError("LLD-08 request field names must be nonempty text")
        canonical_json_bytes_bounded(
            body, max_bytes=resolved.spec.max_request_bytes,
            max_depth=32, max_collection_items=resolved.spec.max_request_bytes,
        )
        for key, value in resolved.path_parameters.items():
            if key == "logical_fingerprint":
                validate_value("sha256", value)
            else:
                require_uuid4(value)
            if key in body and body[key] != value:
                raise ValidationError("LLD-08 path-owned identity conflicts with request body")
            body[key] = value
        if resolved.spec.handler_kind == "command":
            command_id = body.pop("command_id", None)
            require_uuid4(command_id)
            request_type = _COMMAND_TYPE.fullmatch(resolved.spec.request_type).group(1)
            values = validate_value(request_type, body)
            body = {"command_id": command_id, **values}
        else:
            body = validate_value(resolved.spec.request_type, body)
        handler = self._handlers.get(resolved.spec.handler)
        if handler is None:
            raise IntegrityFailure("LLD-08 owner route handler is not assembled")
        result = handler(resolved, MappingProxyType(body))
        if not isinstance(result, Mapping):
            raise IntegrityFailure("LLD-08 owner route handler returned a non-object response")
        return InfrastructureHttpResponse(
            resolved.spec.success_status, resolved.spec.response_type,
            MappingProxyType(dict(result)),
        )


def build_route_adapter(handlers: Mapping[str, OwnerHandler]) -> InfrastructureRouteAdapter:
    return InfrastructureRouteAdapter(handlers)


def build_owner_route_adapter(service, *, actor_kind: str, actor_id: str | None) -> InfrastructureRouteAdapter:
    """Assemble installed owners for a caller already authenticated by LLD-12."""
    if not isinstance(actor_kind, str) or not actor_kind:
        raise ValidationError("LLD-08 route assembly requires authenticated actor context")
    if actor_id is not None and (not isinstance(actor_id, str) or not actor_id):
        raise ValidationError("LLD-08 actor identity is invalid")
    from soma.infrastructure.queries.core import InfrastructureQueries
    from soma.infrastructure.queries import candidates, details, explorer, history, workbooks as workbook_queries
    from soma.infrastructure.services import (
        components, network_elements, placement, regularization, relationships,
        sites, workbooks as workbook_services,
    )

    handlers: dict[str, OwnerHandler] = {}
    command_owners = (
        components, network_elements, placement, regularization, relationships,
        sites, workbook_services,
    )
    query_owners = (candidates, details, explorer, history, workbook_queries)
    installed_commands = set().union(*(owner.COMMAND_NAMES for owner in command_owners))
    installed_queries = set().union(*(owner.QUERY_NAMES for owner in query_owners))
    queries = InfrastructureQueries(service)

    def command_handler(route: ResolvedInfrastructureRoute,
                        request: Mapping[str, object]) -> Mapping[str, object]:
        values = dict(request)
        command_id = values.pop("command_id")
        execution = service.execute(
            route.spec.handler, command_id=command_id, payload=values,
            actor_kind=actor_kind, actor_id=actor_id,
        )
        if execution.response_schema != route.spec.response_type:
            raise IntegrityFailure("LLD-08 command response differs from route contract")
        return execution.response

    def query_handler(route: ResolvedInfrastructureRoute,
                      request: Mapping[str, object]) -> Mapping[str, object]:
        return queries.execute(route.spec.handler, dict(request))

    for name in installed_commands:
        handlers[name] = command_handler
    for name in installed_queries:
        if name in handlers:
            raise IntegrityFailure("LLD-08 route owner name is ambiguous")
        handlers[name] = query_handler
    return InfrastructureRouteAdapter(handlers)
