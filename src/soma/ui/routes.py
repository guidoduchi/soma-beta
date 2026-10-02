"""UI DTO binding after LLD-12 authentication; no session or domain authority."""
import json
from dataclasses import dataclass
from importlib.resources import files
from types import MappingProxyType

from soma.foundation.errors import SomaError, ValidationError
from soma.foundation.identifiers import require_uuid4
from soma.foundation.strict_json import canonical_json_bytes_bounded

_ROUTES = json.loads(files('soma.ui').joinpath('registry.json').read_text(encoding='utf8'))['leaves']['routes/working-copies.json']['routes']
UI_ROUTE_SPECS = tuple(MappingProxyType(dict(row, response_type='WorkingCopyCheckpointResultV1') if row['handler'] == 'CheckpointWorkingCopy' else dict(row)) for row in _ROUTES)


@dataclass(frozen=True, slots=True)
class UiHttpResponse:
    status: int
    response_type: str
    body: dict


class WorkingCopyRoutes:
    def __init__(self, commands, queries, session_security):
        self._commands, self._queries, self._security = commands, queries, session_security

    def dispatch(self, method, path, request, decoded=None):
        if not isinstance(path, str) or any(item in path for item in ('?', '#', '//', '\\', '%', '\x00')):
            raise ValidationError('UI route path is invalid')
        resolved = None
        for row in UI_ROUTE_SPECS:
            if row['method'] != method:
                continue
            if row['path'] == path:
                resolved = row, None
                break
            if row['path'].endswith('/{working_copy_id}') and path.startswith('/api/v1/ui/working-copies/'):
                identity = path.removeprefix('/api/v1/ui/working-copies/')
                if '/' not in identity:
                    resolved = row, require_uuid4(identity)
                    break
        if resolved is None:
            return None
        row, identity = resolved
        context = self._security.validate_request(request, mutation=row['handler_kind'] == 'command')
        profile = require_uuid4(context.actor_id)
        if decoded is not None and not isinstance(decoded, dict):
            raise ValidationError('UI request must be an object')
        body = dict(decoded or {})
        canonical_json_bytes_bounded(body, max_bytes=row['max_request_bytes'] or 4096, max_depth=32, max_collection_items=262144)
        if row['handler'] == 'CheckpointWorkingCopy':
            result = self._commands.checkpoint_working_copy(body, owner_profile_id=profile)
        elif row['handler'] == 'DiscardWorkingCopy':
            if set(body) != {'command_id', 'expected_generation'}:
                raise ValidationError('Discard body must not carry path identity or unknown fields')
            result = self._commands.discard_working_copy(dict(body, working_copy_id=identity), owner_profile_id=profile)
        elif row['handler'] == 'GetWorkingCopy':
            if body:
                raise ValidationError('Recovery detail has no request body')
            result = self._queries.get_working_copy({'working_copy_id': identity}, owner_profile_id=profile)
        else:
            result = self._queries.list_restore_candidates(body, owner_profile_id=profile)
        return UiHttpResponse(row['success_status'], row['response_type'], result)
