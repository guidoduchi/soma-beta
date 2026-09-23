from __future__ import annotations

import asyncio
import json
import sqlite3
import threading
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pytest
from starlette.applications import Starlette
from starlette.responses import JSONResponse
from starlette.routing import Route

from soma.foundation.api.routes_foundation import FoundationRoutes
from soma.foundation.errors import SomaError
from soma.foundation.identifiers import new_uuid4
from soma.foundation.migrations.manifest import MigrationManifest
from soma.foundation.migrations.runner import MigrationRunner
from soma.foundation.persistence.connections import ConnectionFactory
from soma.foundation.queries.status import FoundationStatusQueries
from soma.foundation.runtime import HostRuntime, InstancePaths, UvicornLoopbackServer


_TOKEN = "Bearer test-only-run-control"


@dataclass(frozen=True)
class _RunContext:
    run_id: str
    data_instance_id: str


class _SmokeRunSecurity:
    def __init__(self) -> None:
        self.prepared: list[dict[str, object]] = []
        self.closed: list[dict[str, object]] = []
        self.readiness_locator: str | None = None

    def prepare_run(self, **values) -> None:
        self.prepared.append(dict(values))
        locator = values.get("readiness_locator")
        assert isinstance(locator, str)
        self.readiness_locator = locator

    def close_run(self, **values) -> None:
        self.closed.append(dict(values))


class _SmokeRunControl:
    """Explicit test-only LLD-12 seam; no production credential behavior."""

    def __init__(self, holder: dict[str, Any]) -> None:
        self._holder = holder
        self.calls: list[tuple[str | None, str]] = []

    def authenticate_control_request(self, headers, expected_run_id: str):
        authorization = headers.get("authorization")
        self.calls.append((authorization, expected_run_id))
        if authorization != _TOKEN:
            raise SomaError("UNAUTHENTICATED", "test run-control token is missing")
        current = self._holder["runtime"].health()
        if current.run_id != expected_run_id:
            raise SomaError("FORBIDDEN", "test run-control identity changed")
        return _RunContext(expected_run_id, current.data_instance_id)


class _SmokeSession:
    def validate_request(self, request, *, mutation: bool):
        if request != "test-only-browser-session":
            raise SomaError("UNAUTHENTICATED", "test browser session is missing")
        return object()


def _json_request(
    url: str,
    *,
    method: str = "GET",
    body: dict[str, object] | None = None,
) -> dict[str, object]:
    encoded = None if body is None else json.dumps(body).encode("utf-8")
    request = urllib.request.Request(
        url,
        data=encoded,
        method=method,
        headers={
            "Authorization": _TOKEN,
            **({"Content-Type": "application/json"} if encoded is not None else {}),
        },
    )
    with urllib.request.urlopen(request, timeout=5) as response:
        assert response.status in {200, 202}
        return json.loads(response.read().decode("utf-8"))


def _real_runtime(
    root: Path,
    migration_directory: Path,
    security_provider,
    *,
    process_birth_id: str,
):
    paths = InstancePaths.from_root(root.resolve())
    factory = ConnectionFactory(paths.database, security_provider, driver=sqlite3)
    manifest = MigrationManifest.load(migration_directory)
    holder: dict[str, Any] = {"request_threads": []}
    run_security = _SmokeRunSecurity()
    run_control = _SmokeRunControl(holder)
    session = _SmokeSession()

    async def health_endpoint(request):
        headers = dict(request.headers)

        def invoke():
            holder["request_threads"].append(threading.current_thread().name)
            return holder["routes"].get_runtime_health(headers=headers)

        result = await asyncio.wrap_future(
            holder["runtime"].request_executor.submit(invoke)
        )
        return JSONResponse(result, status_code=200)

    async def shutdown_endpoint(request):
        headers = dict(request.headers)
        body = await request.json()

        def invoke():
            holder["request_threads"].append(threading.current_thread().name)
            return holder["routes"].shutdown_host(headers=headers, body=body)

        result = await asyncio.wrap_future(
            holder["runtime"].request_executor.submit(invoke)
        )
        return JSONResponse(result, status_code=202)

    app = Starlette(
        routes=[
            Route("/api/v1/runtime/health", health_endpoint, methods=["GET"]),
            Route("/api/v1/runtime/shutdown", shutdown_endpoint, methods=["POST"]),
        ]
    )

    def self_health(expected) -> bool:
        locator = run_security.readiness_locator
        if locator is None:
            return False
        payload = _json_request(locator + "/api/v1/runtime/health")
        return (
            payload.get("run_id") == expected.run_id
            and payload.get("data_instance_id") == expected.data_instance_id
            and payload.get("host_state") == expected.host_state
            and payload.get("migration_sequence") == expected.migration_sequence
        )

    server = UvicornLoopbackServer(
        app,
        self_health_probe=self_health,
        startup_timeout_seconds=5,
        shutdown_timeout_seconds=5,
    )

    def runner_factory(ownership_assertion):
        return MigrationRunner(
            canonical_database_path=paths.database,
            manifest=manifest,
            factory_for_path=lambda path: ConnectionFactory(
                path,
                security_provider,
                driver=sqlite3,
            ),
            app_version="foundation-smoke-test",
            ownership_assertion=ownership_assertion,
        )

    runtime = HostRuntime(
        paths=paths,
        connection_factory=factory,
        migration_manifest=manifest,
        migration_runner_factory=runner_factory,
        server=server,
        run_security=run_security,
        startup_reconciler=lambda run_id, now: None,
        app_version="test",
        protocol_version="1",
        process_birth_id=process_birth_id,
    )
    holder["runtime"] = runtime
    holder["routes"] = FoundationRoutes(
        runtime=runtime,
        status_queries=FoundationStatusQueries(
            runtime=runtime,
            connection_factory=runtime.connection_factory,
        ),
        run_control=run_control,
        session_security=session,
    )
    return runtime, paths, server, run_security, run_control, holder


def test_real_starlette_uvicorn_foundation_flow_dispatches_through_host_and_restarts(
    tmp_path,
    migration_directory,
    security_provider,
) -> None:
    runtime, paths, server, security, run_control, holder = _real_runtime(
        tmp_path,
        migration_directory,
        security_provider,
        process_birth_id="foundation-smoke-process-1",
    )

    health = runtime.start()
    assert health.host_state == "READY"
    assert paths.registry.exists()
    assert security.readiness_locator is not None

    ready = _json_request(
        security.readiness_locator + "/api/v1/runtime/health"
    )
    assert ready["host_state"] == "READY"
    assert ready["run_id"] == health.run_id
    assert ready["data_instance_id"] == health.data_instance_id
    assert run_control.calls
    assert holder["request_threads"]
    assert all(
        str(name).startswith("soma-request")
        for name in holder["request_threads"]
    )

    shutdown = _json_request(
        security.readiness_locator + "/api/v1/runtime/shutdown",
        method="POST",
        body={
            "run_id": health.run_id,
            "data_instance_id": health.data_instance_id,
            "command_id": new_uuid4(),
        },
    )
    assert shutdown["shutdown_state"] == "QUIESCING"
    assert runtime.state == "QUIESCING"

    with pytest.raises(SomaError) as rejected:
        runtime.request_executor.submit(lambda: None)
    assert rejected.value.code == "HOST_QUIESCING"

    stopped = runtime.shutdown(grace_seconds=5)
    assert stopped.shutdown_state == "STOPPED"
    assert runtime.state == "STOPPED"
    assert server.is_stopped()
    assert not paths.registry.exists()
    assert len(security.closed) == 1
    assert runtime._lock is None

    replacement, replacement_paths, replacement_server, replacement_security, _control, _holder = (
        _real_runtime(
            tmp_path,
            migration_directory,
            security_provider,
            process_birth_id="foundation-smoke-process-2",
        )
    )
    replacement_health = replacement.start()
    assert replacement_health.host_state == "READY"
    assert replacement_health.data_instance_id == health.data_instance_id
    assert replacement_health.run_id != health.run_id
    assert replacement_paths.registry.exists()

    replacement.shutdown(grace_seconds=5)
    assert replacement.state == "STOPPED"
    assert replacement_server.is_stopped()
    assert not replacement_paths.registry.exists()
    assert len(replacement_security.closed) == 1
