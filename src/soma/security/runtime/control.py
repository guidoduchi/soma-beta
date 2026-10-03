"""Launcher credentials only. Browser credentials never authenticate this provider."""
from __future__ import annotations

import base64
import hashlib
import hmac
import http.client
import os
from pathlib import Path
import secrets
import socket
from threading import Timer
import time
import uuid

from soma.foundation.errors import SecurityNotReady, SomaError
from soma.foundation.identifiers import require_uuid4
from soma.foundation.strict_json import canonical_json_bytes, loads_strict_bytes
from soma.security.contracts.security import RunControlContextV1
from soma.security.crypto.dpapi import WindowsDpapiProvider
from soma.security.runtime.windows import WindowsAclProvider, reject_redirects


def encode_secret(secret):
    return base64.urlsafe_b64encode(secret).rstrip(b"=").decode("ascii")


def read_owned_file(path, file_security, *, limit=65536 + 128):
    target = reject_redirects(Path(path))
    file_security.verify(target.parent)
    file_security.ensure_owner_only_file(target)
    before = target.stat(follow_symlinks=False)
    with target.open("rb") as handle:
        opened = os.fstat(handle.fileno())
        if (before.st_dev, before.st_ino) != (opened.st_dev, opened.st_ino) or opened.st_nlink != 1:
            raise SecurityNotReady("security file identity is unsafe")
        value = handle.read(limit + 1)
    file_security.ensure_owner_only_file(target)
    after = target.stat(follow_symlinks=False)
    if len(value) > limit or (after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns) != (opened.st_dev, opened.st_ino, opened.st_size, opened.st_mtime_ns):
        raise SecurityNotReady("security file changed or exceeds its bound")
    return value


def publish_owned_file(path, payload, file_security):
    target = reject_redirects(Path(path))
    file_security.verify(target.parent)
    temporary = target.parent / f".{target.name}-{uuid.uuid4()}.tmp"
    created = False
    try:
        with file_security.create_file(temporary) as handle:
            created = True
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        file_security.ensure_owner_only_file(temporary)
        # All runtime credentials are newly owned artifacts, never blind replacements.
        if os.name == "nt":
            os.rename(temporary, target)
        else:
            os.link(temporary, target)
            temporary.unlink()
        file_security.ensure_owner_only_file(target)
    finally:
        if created:
            temporary.unlink(missing_ok=True)


def guard_headers(headers, origin):
    expected_host = origin.removeprefix("http://")
    pairs = list(headers.items())
    host = [value for key, value in pairs if key.lower() == "host"]
    if host != [expected_host] or any(key.lower() == "forwarded" or key.lower().startswith("x-forwarded-") for key, _ in pairs):
        raise SomaError("FORBIDDEN", "request host/proxy context is invalid")


class RunControlProvider:
    def __init__(self, runtime_directory, installation_id, *, file_security=None, dpapi=None):
        require_uuid4(installation_id)
        self.directory = reject_redirects(Path(runtime_directory))
        self.installation_id = installation_id
        self.file_security = file_security or WindowsAclProvider()
        self.dpapi = dpapi or WindowsDpapiProvider()
        self._secret = None
        self._run_id = None
        self._data_id = None
        self._origin = None
        self._protected_digest = None

    def create_run_secret(self, run_id, data_instance_id):
        require_uuid4(run_id)
        require_uuid4(data_instance_id)
        if self._secret is not None:
            raise SecurityNotReady("run credential is already active")
        self.file_security.ensure_owner_only_directory(self.directory)
        secret = secrets.token_bytes(32)
        protected = self.dpapi.protect_current_user(secret, "run_control", self.installation_id)
        path = self.directory / f"run-{run_id}.dpapi"
        if path.exists():
            raise SecurityNotReady("run credential locator already exists")
        # Capture ownership before publication so failed preparation can unwind.
        self._run_id, self._data_id = run_id, data_instance_id
        self._secret = secret
        self._protected_digest = hashlib.sha256(protected).digest()
        publish_owned_file(path, protected, self.file_security)
        captured = read_owned_file(path, self.file_security)
        if not hmac.compare_digest(secret, self.dpapi.unprotect_current_user(captured, "run_control", self.installation_id)):
            raise SecurityNotReady("published run credential did not verify")
        return path.name

    def prepare_run(self, *, run_id, data_instance_id, readiness_locator):
        # Foundation supplies its retained socket origin; locator remains a private
        # adapter argument. The published locator is the protected filename.
        self._origin = readiness_locator
        return self.create_run_secret(run_id, data_instance_id)

    def authenticate_control_request(self, headers, expected_run_id):
        if self._secret is None or expected_run_id != self._run_id:
            raise SomaError("UNAUTHENTICATED", "run authentication failed")
        guard_headers(headers, self._origin)
        values = [value for key, value in headers.items() if key.lower() == "x-soma-run-auth"]
        expected = encode_secret(self._secret)
        if len(values) != 1 or not isinstance(values[0], str) or not values[0].isascii() or not hmac.compare_digest(values[0], expected):
            raise SomaError("UNAUTHENTICATED", "run authentication failed")
        return RunControlContextV1(self._run_id, self._data_id)

    def self_health(self, expected):
        from dataclasses import asdict
        response = direct_request(self._origin, self._secret, "GET", "/api/v1/runtime/health", timeout=2)
        return response == asdict(expected)

    def close_run(self, *, run_id, data_instance_id):
        if self._run_id is None:
            return
        if (run_id, data_instance_id) != (self._run_id, self._data_id):
            raise SecurityNotReady("credential cleanup identity mismatch")
        path = self.directory / f"run-{run_id}.dpapi"
        if path.exists():
            captured = read_owned_file(path, self.file_security)
            if not hmac.compare_digest(hashlib.sha256(captured).digest(), self._protected_digest):
                raise SecurityNotReady("credential cleanup ownership is unproven")
            if not self.file_security.remove_exact_file(path, captured):
                raise SecurityNotReady("credential cleanup ownership changed")
        self._secret = self._run_id = self._data_id = self._origin = self._protected_digest = None


def direct_request(origin, secret, method, path, *, body=None, timeout=2):
    from soma.foundation.runtime.registry import _ORIGIN
    match = _ORIGIN.fullmatch(origin) if isinstance(origin, str) else None
    if match is None or int(match[1]) > 65535 or len(secret) != 32 or not 0 < timeout <= 10:
        raise SecurityNotReady("run-control destination/credential is invalid")
    if (method, path) not in {("GET", "/api/v1/runtime/health"), ("POST", "/api/v1/runtime/shutdown")}:
        raise SecurityNotReady("run-control route is invalid")
    if method == "POST":
        if not isinstance(body, dict) or set(body) != {"run_id", "data_instance_id", "command_id"}:
            raise SecurityNotReady("shutdown request shape is invalid")
        for value in body.values():
            require_uuid4(value)
    elif body is not None or timeout > 2:
        raise SecurityNotReady("health request context is invalid")
    connection = http.client.HTTPConnection("127.0.0.1", int(match[1]), timeout=timeout)
    deadline = time.monotonic() + timeout
    timer = None
    try:
        connection.connect()
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise SecurityNotReady("authenticated control request deadline expired")
        active_socket = connection.sock
        active_socket.settimeout(remaining)
        def expire():
            # Retain the socket even when HTTP/1.0 getresponse detaches it from
            # HTTPConnection: a slow body must still obey the overall deadline.
            try:
                active_socket.shutdown(socket.SHUT_RDWR)
            except OSError:
                pass
        timer = Timer(remaining, expire)
        timer.daemon = True
        timer.start()
        payload = None if body is None else canonical_json_bytes(body)
        headers = {"Host": origin.removeprefix("http://"), "X-SOMA-Run-Auth": encode_secret(secret)}
        if payload is not None:
            headers["Content-Type"] = "application/json"
        connection.request(method, path, body=payload, headers=headers)
        response = connection.getresponse()
        expected_status = 200 if method == "GET" else 202
        if response.status != expected_status or response.getheader("Location") is not None:
            raise SecurityNotReady("authenticated control response was rejected")
        raw = response.read(16_385)
        if time.monotonic() >= deadline:
            raise SecurityNotReady("authenticated control request deadline expired")
        value = loads_strict_bytes(raw, max_bytes=16_384)
        if not isinstance(value, dict):
            raise SecurityNotReady("authenticated control response shape is invalid")
        return value
    except (OSError, http.client.HTTPException):
        raise SecurityNotReady("authenticated control connection failed") from None
    finally:
        if timer is not None:
            timer.cancel()
        connection.close()
