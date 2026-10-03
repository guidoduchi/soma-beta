"""Real source composition, encrypted data and native Windows trust."""
import hashlib
import http.client
import json
import os
from pathlib import Path
import sys
import subprocess

import pytest

from soma.application import SourceApplication
from soma.foundation.identifiers import new_uuid4
from soma.foundation.errors import SomaError
from soma.security.runtime.control import direct_request, read_owned_file, publish_owned_file
from soma.security.runtime.trust import TrustedInstanceVerifier
from soma.security.runtime.windows import WindowsAclProvider

pytestmark = pytest.mark.skipif(os.name != "nt", reason="native source application")


def test_reset_provisioning_rollback_and_validated_orphan_replacement(tmp_path, monkeypatch):
    pytest.importorskip("sqlcipher3")
    files = WindowsAclProvider()
    root = tmp_path / "instance"
    files.ensure_owner_only_directory(root)
    app = SourceApplication(root)
    try:
        app.host.start()
        path = root / "security" / "admin-reset.dpapi"
        original = app.auth.profiles.ensure_singleton_local_administrator

        def fail_after_profile(*args, **kwargs):
            original(*args, **kwargs)
            raise SomaError("INJECTED_FAILURE", "rollback test")

        monkeypatch.setattr(app.auth.profiles, "ensure_singleton_local_administrator", fail_after_profile)
        body = {"command_id": new_uuid4(), "password": "local native password", "password_confirmation": "local native password"}
        with pytest.raises(SomaError, match="rollback test"):
            app.auth.setup(body)
        assert not path.exists()
        connection = app.factory.open_authoritative(read_only=True, require_wal=True)
        try:
            assert connection.execute("SELECT count(*) FROM security_auth_credentials").fetchone() == (0,)
            assert connection.execute("SELECT count(*) FROM local_user_profiles").fetchone() == (0,)
            assert connection.execute("SELECT count(*) FROM command_receipts WHERE command_id=?", (body["command_id"],)).fetchone() == (0,)
        finally:
            connection.close()

        monkeypatch.setattr(app.auth.profiles, "ensure_singleton_local_administrator", original)
        orphan = app.security.dpapi.protect_current_user(os.urandom(32), "admin_password_reset", app.security.installation_id)
        publish_owned_file(path, orphan, files)
        response, _ = app.auth.setup({**body, "command_id": new_uuid4()})
        assert response["authenticated"] is True
        protected = read_owned_file(path, files)
        assert protected != orphan
        secret = app.security.dpapi.unprotect_current_user(protected, "admin_password_reset", app.security.installation_id)
        assert app.auth._credential()[4] == hashlib.sha256(secret).digest()
    finally:
        if app.host.state in {"READY", "QUIESCING", "LISTENING_NOT_READY"}:
            app.host.shutdown(grace_seconds=10)


def request(origin, method, path, body=None, *, cookie=None, headers=None):
    connection = http.client.HTTPConnection("127.0.0.1", int(origin.rsplit(":", 1)[1]), timeout=5)
    actual = {"Origin": origin, **(headers or {})}
    if cookie:
        actual["Cookie"] = cookie
    payload = None if body is None else json.dumps(body).encode()
    if payload is not None:
        actual["Content-Type"] = "application/json"
    try:
        connection.request(method, path, payload, actual)
        response = connection.getresponse()
        raw = response.read()
        return response.status, dict(response.getheaders()), raw
    finally:
        connection.close()


def test_live_host_packaged_assets_precede_auth_and_closed_spa_fallback(tmp_path):
    pytest.importorskip("sqlcipher3")
    files = WindowsAclProvider()
    root = tmp_path / "instance"
    files.ensure_owner_only_directory(root)
    app = SourceApplication(root)
    try:
        app.host.start()
        origin = app.security.control._origin
        manifest = json.loads((app.static / "manifest.json").read_text())["files"]

        def check_routes(cookie=None):
            status, headers, html = request(origin, "GET", "/", cookie=cookie)
            assert status == 200 and headers["content-type"] == "text/html; charset=utf-8"
            if cookie:
                assert html == (app.static / "index.html").read_bytes()
                assert request(origin, "GET", "/objectives", cookie=cookie)[2] == html
            for name, content_type in (
                ("assets/index-CC0C6mm0.js", "text/javascript; charset=utf-8"),
                ("assets/index-CoKe4wwi.css", "text/css; charset=utf-8"),
            ):
                status, headers, body = request(origin, "GET", "/static/ui/" + name, cookie=cookie)
                assert status == 200 and headers["content-type"] == content_type
                assert body == (app.static / name).read_bytes()
                assert len(body) == manifest[name]["bytes"]
                assert hashlib.sha256(body).hexdigest() == manifest[name]["sha256"]
            for path in ("/static/ui/assets/missing.js", "/static/ui/missing.css", "/unknown", "/assets/missing.js",
                "/static/ui/assets/%69ndex-CC0C6mm0.js", "/static/ui/../registry.json"):
                status, _, body = request(origin, "GET", path, cookie=cookie)
                assert status == 404 and body != html and b"<html" not in body.lower()
            for path in ("/api/v1/no-such-route", "/api/no-such-route"):
                status, headers, body = request(origin, "GET", path, cookie=cookie)
                assert status == (404 if cookie else 401)
                assert headers["content-type"] == "application/json" and b"<html" not in body.lower()

        check_routes()
        status, headers, _ = request(origin, "POST", "/api/v1/auth/setup", {
            "command_id": new_uuid4(), "password": "local native password", "password_confirmation": "local native password"})
        assert status == 201
        cookie = headers["set-cookie"].split(";", 1)[0]
        check_routes(cookie)
    finally:
        if app.host.state in {"READY", "QUIESCING", "LISTENING_NOT_READY"}:
            app.host.shutdown(grace_seconds=10)


def test_real_browser_login_executes_packaged_module_and_mounts_react(tmp_path):
    pytest.importorskip("sqlcipher3")
    checkout = Path(__file__).resolve().parents[1]
    node = checkout / "tmp/lld10-build-tools/node-v24.21.0-win-x64/node.exe"
    browser = Path("C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe")
    if not node.is_file() or not browser.is_file() or not (checkout / "src/web/node_modules/@playwright/test").is_dir():
        pytest.skip("existing repository Node/Playwright and native Edge test prerequisites are required")
    files = WindowsAclProvider()
    root = tmp_path / "instance"
    files.ensure_owner_only_directory(root)
    app = SourceApplication(root)
    try:
        app.host.start()
        origin = app.security.control._origin
        password = "local native password"
        assert request(origin, "POST", "/api/v1/auth/setup", {"command_id": new_uuid4(),
            "password": password, "password_confirmation": password})[0] == 201
        result = subprocess.run([str(node), str(checkout / "tests/source_runtime_browser.mjs")],
            input=json.dumps({"origin": origin, "password": password, "browserPath": str(browser)}),
            capture_output=True, text=True, timeout=45, check=False)
        assert result.returncode == 0, result.stderr
        evidence = json.loads(result.stdout)
        assert evidence["login_completed"] is True and evidence["react_mounted"] is True
        assert len(evidence["resources"]) >= 2
    finally:
        if app.host.state in {"READY", "QUIESCING", "LISTENING_NOT_READY"}:
            app.host.shutdown(grace_seconds=10)


def test_real_application_setup_session_registry_and_owned_shutdown(tmp_path):
    pytest.importorskip("sqlcipher3")
    files = WindowsAclProvider()
    root = tmp_path / "instance"
    files.ensure_owner_only_directory(root)
    app = SourceApplication(root)
    try:
        health = app.host.start()
        assert health.host_state == "READY" and health.migration_sequence == 19
        origin = app.security.control._origin
        verifier = TrustedInstanceVerifier(root, sys._base_executable, app.security.installation_id,
            file_security=files, dpapi=app.security.dpapi)
        trusted = verifier.verify()
        assert trusted.registry.run_id == health.run_id
        assert app.security.control._secret not in app.paths.registry.read_bytes()
        status, _, html = request(origin, "GET", "/")
        assert status == 200 and b"first" in html.lower()
        assert request(origin, "GET", "/api/v1/runtime/health")[0] == 401
        assert request(origin, "GET", "/api/v1/auth/status", headers={"Host": "localhost"})[0] == 403
        setup = {"command_id": new_uuid4(), "password": "local native password", "password_confirmation": "local native password"}
        status, headers, raw = request(origin, "POST", "/api/v1/auth/setup", setup)
        assert status == 201, raw
        response = json.loads(raw)
        cookie = headers["set-cookie"].split(";", 1)[0]
        assert "HttpOnly" in headers["set-cookie"] and "SameSite=Strict" in headers["set-cookie"]
        assert response["authenticated"] is True
        reset_path = root / "security" / "admin-reset.dpapi"
        protected = read_owned_file(reset_path, files)
        reset_secret = app.security.dpapi.unprotect_current_user(protected, "admin_password_reset", app.security.installation_id)
        connection = app.factory.open_authoritative(read_only=True, require_wal=True)
        try:
            assert connection.execute("SELECT reset_verifier_sha256 FROM security_auth_credentials").fetchone() == (hashlib.sha256(reset_secret).digest(),)
            assert connection.execute("SELECT count(*) FROM local_user_profiles").fetchone() == (1,)
            evidence = str(connection.execute("SELECT response_json FROM command_receipt_results").fetchall())
            audit = str(connection.execute("SELECT payload_json FROM audit_events").fetchall())
            assert setup["password"] not in evidence + audit
            assert response["csrf_token"] not in evidence + audit
        finally:
            connection.close()
        assert request(origin, "POST", "/api/v1/auth/setup", setup)[0] == 201
        assert reset_path.read_bytes() == protected
        assert request(origin, "POST", "/api/v1/auth/login", {"password": "wrong password"})[0] == 401
        assert request(origin, "GET", "/", cookie=cookie)[2] == (app.static / "index.html").read_bytes()
        assert request(origin, "GET", "/api/v1/objectives?limit=20", cookie=cookie)[0] == 200
        assert request(origin, "GET", "/api/v1/tasks?limit=20", cookie=cookie)[0] == 200
        for path in ("/api/v1/inventory/stock?limit=20", "/api/v1/inventory/attention?limit=20", "/api/v1/inventory/requests?limit=20",
            "/api/v1/reference/customer-organizations?limit=20", "/api/v1/product-lines?limit=20", "/api/v1/contracts?limit=20",
            "/api/v1/contract-product-lines?limit=20", "/api/v1/sla/classification-mappings?limit=20", "/api/v1/settings/OBJECTIVE_TIMEZONE_V1",
            "/api/v1/infrastructure/tree?limit=20", "/api/v1/communications/source-scopes?limit=20"):
            status, _, raw = request(origin, "GET", path, cookie=cookie)
            assert status == 200, (path, raw)
        command = {"command_id": new_uuid4(), "run_id": health.run_id, "data_instance_id": health.data_instance_id}
        accepted = direct_request(origin, trusted.secret, "POST", "/api/v1/runtime/shutdown", body=command)
        assert accepted["shutdown_state"] == "QUIESCING"
        assert direct_request(origin, trusted.secret, "POST", "/api/v1/runtime/shutdown", body=command) == accepted
        app.host.shutdown(grace_seconds=10)
        assert not app.paths.registry.exists() and not (root / "runtime" / trusted.registry.readiness_locator).exists()
        assert reset_path.read_bytes() == protected
    finally:
        if app.host.state in {"READY", "QUIESCING", "LISTENING_NOT_READY"}:
            app.host.shutdown(grace_seconds=10)
