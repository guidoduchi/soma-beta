"""Packaged immutable assets and closed SPA fallback, called by the LLD-12 host."""
import hashlib
import json
import re
from dataclasses import dataclass
from importlib.resources import files

from soma.foundation.errors import IntegrityFailure


@dataclass(frozen=True, slots=True)
class UiAsset:
    content_type: str
    body: bytes
    sha256: str


class UiAssets:
    def __init__(self):
        root = files('soma.ui')
        self._root = root.joinpath('static')
        self._manifest = json.loads(self._root.joinpath('manifest.json').read_text(encoding='utf8'))['files']
        self._routes = json.loads(root.joinpath('registry.json').read_text(encoding='utf8'))['leaves']['ui/client-routes.json']['routes']

    def resolve(self, method, path):
        if method != 'GET' or not isinstance(path, str) or any(char in path for char in ('%', '?', '#', '\\', '\x00', '//')):
            return None
        if path.startswith('/api/'):
            return None
        if path.startswith('/static/ui/'):
            name = path.removeprefix('/static/ui/')
            if name not in self._manifest:
                return None
        else:
            match = False
            for route in self._routes:
                pattern = re.sub(r'\{[a-z_]+\}', r'[A-Za-z0-9][A-Za-z0-9._-]{0,127}', route['path'])
                if re.fullmatch(pattern, path):
                    match = True
                    break
            if not match:
                return None
            name = 'index.html'
        raw = self._root.joinpath(*name.split('/')).read_bytes()
        expected = self._manifest[name]
        digest = hashlib.sha256(raw).hexdigest()
        if len(raw) != expected['bytes'] or digest != expected['sha256']:
            raise IntegrityFailure('Packaged UI resource differs from its frozen asset manifest')
        content_type = {'.html': 'text/html; charset=utf-8', '.css': 'text/css; charset=utf-8', '.js': 'text/javascript; charset=utf-8'}
        return UiAsset(content_type['.' + name.rsplit('.', 1)[-1]], raw, digest)
