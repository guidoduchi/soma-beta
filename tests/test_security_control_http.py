from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import secrets
from threading import Thread
import time

import pytest

from soma.foundation.errors import SecurityNotReady
from soma.security.runtime.control import direct_request, encode_secret


@contextmanager
def endpoint(status=200, body=None, *, delay=0, body_delay=0):
    calls = []
    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            calls.append((self.path, dict(self.headers)))
            time.sleep(delay)
            self.send_response(status)
            if status == 302:
                self.send_header("Location", "/redirect-target")
            self.end_headers()
            time.sleep(body_delay)
            try:
                self.wfile.write(json.dumps(body or {}).encode())
            except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError):
                pass
        def log_message(self, *args):
            pass
    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_port}", calls
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)


def test_control_http_ignores_proxy_environment_and_keeps_secret_out_of_url(monkeypatch):
    monkeypatch.setenv("HTTP_PROXY", "http://127.0.0.1:1")
    monkeypatch.setenv("HTTPS_PROXY", "http://127.0.0.1:1")
    monkeypatch.setenv("ALL_PROXY", "http://127.0.0.1:1")
    secret = secrets.token_bytes(32)
    with endpoint(body={"ready": True}) as (origin, calls):
        assert direct_request(origin, secret, "GET", "/api/v1/runtime/health") == {"ready": True}
    path, headers = calls[0]
    assert path == "/api/v1/runtime/health"
    assert headers["X-SOMA-Run-Auth"] == encode_secret(secret)
    assert headers["Host"] == origin.removeprefix("http://")


def test_control_http_never_follows_redirect():
    with endpoint(status=302) as (origin, calls):
        with pytest.raises(SecurityNotReady):
            direct_request(origin, secrets.token_bytes(32), "GET", "/api/v1/runtime/health")
    assert len(calls) == 1


def test_control_http_enforces_absolute_request_deadline():
    with endpoint(delay=0.4) as (origin, calls):
        start = time.monotonic()
        with pytest.raises(SecurityNotReady):
            direct_request(origin, secrets.token_bytes(32), "GET", "/api/v1/runtime/health", timeout=0.05)
        assert time.monotonic() - start < 0.3


def test_control_http_deadline_survives_http10_socket_detachment():
    with endpoint(body_delay=0.4) as (origin, calls):
        start = time.monotonic()
        with pytest.raises(SecurityNotReady):
            direct_request(origin, secrets.token_bytes(32), "GET", "/api/v1/runtime/health", timeout=0.05)
        assert time.monotonic() - start < 0.3
