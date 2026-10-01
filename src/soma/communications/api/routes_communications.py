"""Static route dispatch after the owning LLD-12 authentication/CSRF boundary."""
import json
import re
from dataclasses import dataclass
from importlib.resources import files
from types import MappingProxyType
from collections.abc import Mapping

from soma.foundation.errors import IntegrityFailure, ValidationError
from soma.foundation.identifiers import require_uuid4
from soma.foundation.strict_json import canonical_json_bytes_bounded
from soma.communications.contracts.common import TARGET_TYPES


_REGISTRY = json.loads(files("soma.communications.contracts").joinpath("registry.json").read_text(encoding="utf-8"))
COMMUNICATION_ROUTE_SPECS = tuple(MappingProxyType(row) for row in _REGISTRY["leaves"]["routes.json"]["routes"])
_PARAMETER = re.compile(r"^\{([a-z][a-z0-9_]*)\}$")
_KEYS = [(row["method"], row["path"]) for row in COMMUNICATION_ROUTE_SPECS]
if len(set(_KEYS)) != len(_KEYS):
    raise IntegrityFailure("Communications route registry repeats authority")


def resolve_route(method, path):
    if (not isinstance(method, str) or not isinstance(path, str) or not path.startswith("/")
            or any(value in path for value in ("?", "#", "//", "\\", "%", "\x00"))):
        raise ValidationError("Communication route requires an absolute decoded path")
    actual = path.split("/")
    for row in COMMUNICATION_ROUTE_SPECS:
        if method.upper() != row["method"]:
            continue
        expected = row["path"].split("/")
        if len(actual) != len(expected):
            continue
        parameters = {}
        for left, right in zip(expected, actual):
            parameter = _PARAMETER.fullmatch(left)
            if parameter:
                if not right:
                    break
                parameters[parameter.group(1)] = right
            elif left != right:
                break
        else:
            return row, parameters
    return None


@dataclass(frozen=True, slots=True)
class CommunicationHttpResponse:
    status: int
    response_type: str
    body: Mapping


class CommunicationRouteAdapter:
    """Decode-size and path identity guards; application owners validate DTOs."""

    def __init__(self, handlers):
        expected = {row["handler"] for row in COMMUNICATION_ROUTE_SPECS}
        if set(handlers) != expected or any(not callable(handler) for handler in handlers.values()):
            raise IntegrityFailure("Communications routes require their complete static owner assembly")
        self._handlers = MappingProxyType(dict(handlers))

    def dispatch(self, method, path, decoded=None):
        resolved = resolve_route(method, path)
        if resolved is None:
            return None
        row, parameters = resolved
        if decoded is not None and not isinstance(decoded, Mapping):
            raise ValidationError("Communication request must be an object")
        body = dict(decoded or {})
        canonical_json_bytes_bounded(body, max_bytes=row["max_request_bytes"], max_depth=32,
            max_collection_items=row["max_request_bytes"])
        for field, value in parameters.items():
            if field == "target_type":
                if value not in TARGET_TYPES:
                    raise ValidationError("Communication route target type is invalid")
            else:
                require_uuid4(value)
            if field in body and body[field] != value:
                raise ValidationError("Communication path identity disagrees with request")
            body[field] = value
        if row["handler_kind"] == "command":
            require_uuid4(body.get("command_id"))
        result = self._handlers[row["handler"]](body)
        if not isinstance(result, Mapping):
            raise IntegrityFailure("Communication owner returned an invalid response")
        return CommunicationHttpResponse(row["success_status"], row["response_type"], MappingProxyType(dict(result)))
