from __future__ import annotations

from dataclasses import dataclass

import pytest

from soma.foundation.errors import SomaError
from soma.foundation.api.routes_foundation import FoundationRoutes
from soma.foundation.queries.status import FoundationStatusQueries
from soma.foundation.migrations.manifest import MigrationManifest
from soma.foundation.migrations.runner import MigrationRunner
from soma.foundation.persistence.connections import ConnectionFactory
from soma.foundation.runtime import HostRuntime, InstancePaths
import sqlite3



@dataclass(frozen=True)
class _RunContext:
    run_id: str
    data_instance_id: str


class _RunControl:
    def __init__(self, context: _RunContext) -> None:
        self.context = context
        self.calls = []

    def authenticate_control_request(self, headers, expected_run_id):
        self.calls.append((headers, expected_run_id))
        return self.context


class _RouteServer:
    def start(self, bound_socket) -> None:
        bound_socket.listen(8)

    def authenticated_self_health(self, expected) -> bool:
        return True

    def stop(self) -> None:
        return None


class _RouteRunSecurity:
    def prepare_run(self, **values) -> None:
        return None

    def close_run(self, **values) -> None:
        return None


def _runtime(tmp_path, migration_directory, security_provider):
    paths = InstancePaths.from_root(tmp_path.resolve())
    factory = ConnectionFactory(paths.database, security_provider, driver=sqlite3)
    manifest = MigrationManifest.load(migration_directory)

    def runner_factory(ownership_assertion):
        return MigrationRunner(
            canonical_database_path=paths.database,
            manifest=manifest,
            factory_for_path=lambda path: ConnectionFactory(
                path,
                security_provider,
                driver=sqlite3,
            ),
            app_version="routes-test",
            ownership_assertion=ownership_assertion,
        )

    runtime = HostRuntime(
        paths=paths,
        connection_factory=factory,
        migration_manifest=manifest,
        migration_runner_factory=runner_factory,
        server=_RouteServer(),
        run_security=_RouteRunSecurity(),
        startup_reconciler=lambda run_id, now: None,
        app_version="test",
        protocol_version="1",
        process_birth_id="routes-test-process",
    )
    return runtime, paths, None, None, []


class _Session:
    def __init__(self) -> None:
        self.calls = []

    def validate_request(self, request, *, mutation: bool):
        self.calls.append((request, mutation))
        return object()


def test_foundation_route_facade_authenticates_before_runtime_queries(
    tmp_path,
    migration_directory,
    security_provider,
) -> None:
    runtime, _paths, _server, _security, _reconciled = _runtime(
        tmp_path,
        migration_directory,
        security_provider,
    )
    health = runtime.start()
    run_control = _RunControl(_RunContext(health.run_id, health.data_instance_id))
    session = _Session()
    routes = FoundationRoutes(
        runtime=runtime,
        status_queries=FoundationStatusQueries(
            runtime=runtime,
            connection_factory=runtime.connection_factory,
        ),
        run_control=run_control,
        session_security=session,
    )

    returned = routes.get_runtime_health(headers={"authorization": "opaque"})
    assert returned["run_id"] == health.run_id
    assert run_control.calls == [({"authorization": "opaque"}, health.run_id)]

    migration = routes.get_live_migration_status(request="browser-request")
    assert migration["state"] == "LIVE_CURRENT"
    diagnostics = routes.get_foundation_diagnostics(request="browser-request-2")
    assert diagnostics["open_authoritative_connections"] >= 0
    assert session.calls == [
        ("browser-request", False),
        ("browser-request-2", False),
    ]

    command_id = __import__("soma.foundation.identifiers", fromlist=["new_uuid4"]).new_uuid4()
    shutdown = routes.shutdown_host(
        headers={"authorization": "opaque"},
        body={
            "run_id": health.run_id,
            "data_instance_id": health.data_instance_id,
            "command_id": command_id,
        },
    )
    assert shutdown["shutdown_state"] == "QUIESCING"
    runtime.shutdown(grace_seconds=1)


def test_foundation_route_facade_rejects_mismatched_authenticated_run(
    tmp_path,
    migration_directory,
    security_provider,
) -> None:
    runtime, _paths, _server, _security, _reconciled = _runtime(
        tmp_path,
        migration_directory,
        security_provider,
    )
    health = runtime.start()
    wrong = __import__("soma.foundation.identifiers", fromlist=["new_uuid4"]).new_uuid4()
    routes = FoundationRoutes(
        runtime=runtime,
        status_queries=FoundationStatusQueries(
            runtime=runtime,
            connection_factory=runtime.connection_factory,
        ),
        run_control=_RunControl(_RunContext(wrong, health.data_instance_id)),
        session_security=_Session(),
    )
    with pytest.raises(SomaError) as raised:
        routes.get_runtime_health(headers={})
    assert raised.value.code == "FORBIDDEN"
    runtime.shutdown(grace_seconds=1)


def test_runtime_factory_rejects_writer_before_start(
    tmp_path,
    migration_directory,
    security_provider,
) -> None:
    runtime, _paths, _server, _security, _reconciled = _runtime(
        tmp_path,
        migration_directory,
        security_provider,
    )
    from soma.foundation.persistence.uow import UnitOfWork

    with pytest.raises(SomaError) as raised:
        with UnitOfWork(runtime.connection_factory):
            pass
    assert raised.value.code == "HOST_QUIESCING"
