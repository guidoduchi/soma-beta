"""Canonical source application composition around the Foundation host."""
import asyncio
from dataclasses import asdict, is_dataclass
import hashlib
import json
import secrets
from pathlib import Path

from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import HTMLResponse, JSONResponse, Response
from starlette.routing import Route

from soma.composition import build_pre_lld08_startup_reconciler
from soma.foundation.api.routes_foundation import FoundationRoutes
from soma.foundation.errors import SomaError, SecurityNotReady, ValidationError
from soma.foundation.migrations.manifest import MigrationManifest
from soma.foundation.migrations.runner import MigrationRunner
from soma.foundation.persistence.connections import ConnectionFactory
from soma.foundation.queries.status import FoundationStatusQueries
from soma.foundation.runtime.host import HostRuntime
from soma.foundation.runtime.paths import InstancePaths
from soma.foundation.runtime.server import UvicornLoopbackServer
from soma.foundation.strict_json import loads_strict_bytes
from soma.security.runtime.control import guard_headers
from soma.security.runtime.installation import SourceInstallationSecurity, prepare_instance_directories
from soma.security.runtime.windows import process_identity
from soma.security.services.auth import AuthenticationService
from soma.ui.assets import UiAssets


def json_value(value):
    if is_dataclass(value):
        return json_value(asdict(value))
    if isinstance(value, dict) or hasattr(value, "items"):
        return {key: json_value(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [json_value(item) for item in value]
    return value


def verify_static_assets():
    static = Path(__file__).parent / "ui" / "static"
    manifest = loads_strict_bytes((static / "manifest.json").read_bytes(), max_bytes=262144)
    if manifest.get("schema") != "SOMA_UI_STATIC_ASSETS_V1":
        raise SecurityNotReady("web asset manifest is invalid")
    for name, entry in manifest["files"].items():
        path = static / name
        if path.resolve().parent not in (static.resolve(), (static / "assets").resolve()) or path.is_symlink():
            raise SecurityNotReady("web asset path is invalid")
        data = path.read_bytes()
        if len(data) != entry["bytes"] or hashlib.sha256(data).hexdigest() != entry["sha256"]:
            raise SecurityNotReady("web assets require their accepted build")
    return static, frozenset(manifest["files"])


class SourceApplication:
    def __init__(self, instance_root):
        self.security = SourceInstallationSecurity(instance_root)
        prepare_instance_directories(instance_root, self.security.file_security)
        self.paths = InstancePaths.from_root(instance_root)
        self.static, self.asset_names = verify_static_assets()
        self.ui_assets = UiAssets()
        self.manifest = MigrationManifest.load(Path(__file__).parent / "migrations")
        self.factory = ConnectionFactory(self.paths.database, self.security)
        self.auth = AuthenticationService(self.factory, self.security)
        asgi = Starlette(routes=[Route("/{path:path}", self.request, methods=["GET", "POST", "PATCH", "PUT", "DELETE", "OPTIONS", "HEAD"])])
        self.server = UvicornLoopbackServer(asgi, self_health_probe=self.security.self_health)

        def runner(ownership):
            self.security.prepare_storage(ownership)
            return MigrationRunner(canonical_database_path=self.paths.database, manifest=self.manifest,
                factory_for_path=lambda target: ConnectionFactory(target, self.security),
                app_version="1.0.0.dev0", ownership_assertion=ownership)

        import os
        identity = process_identity(os.getpid())
        self.host = HostRuntime(paths=self.paths, connection_factory=self.factory, migration_manifest=self.manifest,
            migration_runner_factory=runner, server=self.server, run_security=self.security,
            startup_reconciler=build_pre_lld08_startup_reconciler(self.factory), app_version="1.0.0.dev0",
            protocol_version="1", process_birth_id=identity.process_birth_id)
        self.foundation = FoundationRoutes(runtime=self.host,
            status_queries=FoundationStatusQueries(runtime=self.host, connection_factory=self.factory),
            run_control=self.security, session_security=self.security)
        from soma.runtime_domains import DomainRoutes
        self.domains = DomainRoutes(self.factory, self.security)

    async def request(self, request: Request):
        try:
            origin = self.security.control._origin if self.security.control else None
            guard_headers(request.headers, origin or "")
            path = request.url.path
            if request.url.query and path.startswith("/api/v1/runtime/"):
                raise ValidationError("runtime control has no query parameters")
            if path.startswith("/api/"):
                body = b""
                async for chunk in request.stream():
                    body += chunk
                    # Domain-specific owners apply their stricter accepted bound.
                    if len(body) > (4096 if path.startswith(("/api/v1/runtime/", "/api/v1/auth/")) else 262144):
                        raise ValidationError("request exceeds its byte bound")
                decoded = loads_strict_bytes(body, max_bytes=len(body)) if body else {}
                if request.method not in {"GET", "HEAD"} and body and request.headers.get("content-type", "").split(";", 1)[0] != "application/json":
                    raise ValidationError("request requires JSON content type")
                if path in {"/api/v1/runtime/health", "/api/v1/runtime/shutdown"}:
                    # Technical control remains available after Foundation closes
                    # ordinary request/writer admission during quiescence.
                    result = self.api(request, decoded)
                else:
                    result = await asyncio.wrap_future(self.host.request_executor.submit(self.api, request, decoded))
                return result
            if request.method != "GET":
                return Response(status_code=405)
            # Preserve the escaped wire path for the owner's untrusted-path guard.
            raw_path = request.scope.get("raw_path")
            asset_path = path if raw_path is None else raw_path.decode("utf-8", errors="replace")
            asset = self.ui_assets.resolve(request.method, asset_path)
            if asset is None:
                return Response(status_code=404)
            # Immutable packaged assets never enter browser-auth/page fallback.
            if path.startswith("/static/ui/"):
                return self.asset_response(asset)
            try:
                self.security.validate_request(request, mutation=False)
            except SomaError:
                return self.auth_shell()
            return self.asset_response(asset)
        except SomaError as exc:
            status = 401 if exc.code in {"UNAUTHENTICATED", "AUTH_INVALID_CREDENTIALS"} else 403 if exc.code == "FORBIDDEN" else 429 if exc.code == "AUTH_RATE_LIMITED" else 409 if exc.code in {"AUTH_ALREADY_CONFIGURED", "IDEMPOTENCY_CONFLICT"} else 503 if exc.code in {"HOST_NOT_READY", "HOST_QUIESCING", "SECURITY_NOT_READY"} else 400
            return JSONResponse({"code": exc.code}, status_code=status, headers={"Cache-Control": "no-store"})
        except Exception:
            self.host.record_error_code("INTERNAL_ERROR")
            return JSONResponse({"code": "INTERNAL_ERROR"}, status_code=500)

    @staticmethod
    def asset_response(asset):
        return Response(asset.body, headers={"Content-Type": asset.content_type,
            "Cache-Control": "no-store", "X-Content-Type-Options": "nosniff"})

    def api(self, request, body):
        path, method = request.url.path, request.method
        if (method, path) == ("GET", "/api/v1/runtime/health"):
            return JSONResponse(self.foundation.get_runtime_health(headers=request.headers))
        if (method, path) == ("POST", "/api/v1/runtime/shutdown"):
            return JSONResponse(self.foundation.shutdown_host(headers=request.headers, body=body), status_code=202)
        if self.host.state != "READY":
            raise SomaError("HOST_NOT_READY", "application is not ready")
        if path.startswith("/api/v1/auth/"):
            if request.url.query:
                raise ValidationError("authentication has no query parameters")
            if (method, path) == ("GET", "/api/v1/auth/status") and not body:
                return JSONResponse(self.auth.status(request), headers={"Cache-Control": "no-store"})
            if (method, path) in {("POST", "/api/v1/auth/setup"), ("POST", "/api/v1/auth/login")}:
                if [value for key, value in request.headers.items() if key.lower() == "origin"] != [self.security.control._origin]:
                    raise SomaError("FORBIDDEN", "authentication origin differs")
                result, cookie = self.auth.setup(body) if path.endswith("/setup") else self.auth.login(body)
                return JSONResponse(result, status_code=201 if path.endswith("/setup") else 200,
                    headers={"Set-Cookie": cookie, "Cache-Control": "no-store"})
        self.security.validate_request(request, mutation=method not in {"GET", "HEAD"})
        result = self.domains.dispatch(request, body)
        return JSONResponse(json_value(result.body), status_code=result.status) if result else JSONResponse({"code": "NOT_FOUND"}, status_code=404)

    def auth_shell(self):
        nonce = secrets.token_urlsafe(24)
        # Startup-only composition shell; the existing LLD-10 application is served unchanged after login.
        html = '''<!doctype html><html><head><meta charset="utf-8"><title>SOMA — sign in</title></head>
<body><main><h1>SOMA</h1><p id="state">Checking local authentication…</p>
<form id="auth"><label>Password <input id="password" type="password" autocomplete="current-password" required></label>
<label id="confirmation-label" hidden>Confirm password <input id="confirmation" type="password" autocomplete="new-password"></label>
<button type="submit" id="submit" disabled>Sign in</button></form><p id="error" role="alert"></p></main>
<script nonce="NONCE">let configured=false; const form=document.getElementById('auth');
fetch('/api/v1/auth/status',{credentials:'same-origin',redirect:'error'}).then(r=>r.json()).then(s=>{configured=s.configured;
document.getElementById('state').textContent=configured?'Sign in with your SOMA password.':'First run: create a SOMA password (at least 12 characters).';
document.getElementById('confirmation-label').hidden=configured;document.getElementById('submit').disabled=false;});
form.addEventListener('submit',async e=>{e.preventDefault();const password=document.getElementById('password');const confirmation=document.getElementById('confirmation');
const body=configured?{password:password.value}:{command_id:crypto.randomUUID(),password:password.value,password_confirmation:confirmation.value};
try{const r=await fetch('/api/v1/auth/'+(configured?'login':'setup'),{method:'POST',credentials:'same-origin',redirect:'error',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)});
const result=await r.json();if(!r.ok){document.getElementById('error').textContent=result.code;return;}password.value='';confirmation.value='';location.replace('/');}
catch{document.getElementById('error').textContent='The local host could not complete authentication.';}});</script></body></html>'''.replace("NONCE", nonce)
        return HTMLResponse(html, headers={"Cache-Control": "no-store", "Content-Security-Policy": f"default-src 'none'; script-src 'nonce-{nonce}'; connect-src 'self'; form-action 'self'; base-uri 'none'; frame-ancestors 'none'", "X-Content-Type-Options": "nosniff"})
