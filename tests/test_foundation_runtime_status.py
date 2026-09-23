from __future__ import annotations

import os
import sqlite3
from pathlib import Path

from soma.foundation.migrations.manifest import MigrationManifest
from soma.foundation.persistence.connections import ConnectionFactory
from soma.foundation.persistence.uow import ReadSnapshot
from soma.foundation.queries.status import FoundationStatusQueries, MigrationStatusReader
from soma.foundation.runtime import DataInstanceLock, InstancePaths



class _ImmutableSqliteInspector:
    def open_immutable(self, path: Path):
        return sqlite3.connect(
            f"file:{path.as_posix()}?mode=ro&immutable=1",
            uri=True,
            check_same_thread=True,
        )

class _StatusServer:
    def __init__(self) -> None:
        self.started = False

    def start(self, bound_socket) -> None:
        bound_socket.listen(8)
        self.started = True

    def authenticated_self_health(self, expected) -> bool:
        return True

    def stop(self, timeout_seconds: float | None = None) -> None:
        self.started = False

    def is_stopped(self) -> bool:
        return not self.started


class _StatusRunSecurity:
    def prepare_run(self, **values) -> None:
        return None

    def close_run(self, **values) -> None:
        return None


def _runtime(tmp_path, migration_directory, security_provider):
    from soma.foundation.migrations.runner import MigrationRunner
    from soma.foundation.runtime import HostRuntime

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
            app_version="status-test",
            ownership_assertion=ownership_assertion,
        )

    runtime = HostRuntime(
        paths=paths,
        connection_factory=factory,
        migration_manifest=manifest,
        migration_runner_factory=runner_factory,
        server=_StatusServer(),
        run_security=_StatusRunSecurity(),
        startup_reconciler=lambda run_id, now: None,
        app_version="test",
        protocol_version="1",
        process_birth_id="status-test-process",
    )
    return runtime, paths, runtime.connection_factory, None, []



def test_persistence_metrics_follow_verified_connections_and_transactions(
    initialized_database,
) -> None:
    path, builder = initialized_database
    factory = builder(path)
    assert factory.metrics.snapshot().open_authoritative_connections == 0
    connection = factory.open_authoritative(read_only=False, require_wal=True)
    try:
        metrics = factory.metrics.snapshot()
        assert metrics.open_authoritative_connections == 1
        assert metrics.active_transactions == 0
        connection.execute("BEGIN")
        assert factory.metrics.snapshot().active_transactions == 1
        connection.execute("ROLLBACK")
        assert factory.metrics.snapshot().active_transactions == 0
    finally:
        connection.close()
    assert factory.metrics.snapshot().open_authoritative_connections == 0


def test_offline_migration_status_is_observational_and_requires_existing_layout(
    tmp_path,
    migration_directory,
    security_provider,
) -> None:
    paths = InstancePaths.from_root(tmp_path.resolve())
    manifest = MigrationManifest.load(migration_directory)
    reader = MigrationStatusReader(
        paths=paths,
        manifest=manifest,
        offline_inspector=_ImmutableSqliteInspector(),
    )
    before = set(tmp_path.iterdir())
    assert reader.inspect().state == "NOT_INITIALIZED"
    assert set(tmp_path.iterdir()) == before

    runtime, paths, _server, _security, _reconciled = _runtime(
        tmp_path,
        migration_directory,
        security_provider,
    )
    health = runtime.start()
    runtime.shutdown(grace_seconds=1)
    assert health.migration_sequence == len(manifest.entries)

    database_stat = paths.database.stat()
    status = MigrationStatusReader(
        paths=paths,
        manifest=manifest,
        offline_inspector=_ImmutableSqliteInspector(),
    ).inspect()
    assert status.state == "CURRENT"
    assert status.integrity_state == "VERIFIED"
    assert paths.database.stat().st_size == database_stat.st_size
    assert paths.database.stat().st_mtime_ns == database_stat.st_mtime_ns


def test_offline_status_refuses_direct_inspection_while_instance_lock_is_held(
    tmp_path,
    migration_directory,
    security_provider,
) -> None:
    runtime, paths, _server, _security, _reconciled = _runtime(
        tmp_path,
        migration_directory,
        security_provider,
    )
    runtime.start()
    try:
        status = MigrationStatusReader(
            paths=paths,
            manifest=MigrationManifest.load(migration_directory),
            offline_inspector=_ImmutableSqliteInspector(),
        ).inspect()
        assert status.state == "LOCKED_UNVERIFIED"
    finally:
        runtime.shutdown(grace_seconds=1)


def test_offline_status_detects_sidecars_without_opening_database(
    tmp_path,
    migration_directory,
    security_provider,
) -> None:
    runtime, paths, _server, _security, _reconciled = _runtime(
        tmp_path,
        migration_directory,
        security_provider,
    )
    runtime.start()
    runtime.shutdown(grace_seconds=1)
    wal = Path(str(paths.database) + "-wal")
    wal.write_bytes(b"unsafe-sidecar")
    try:
        status = MigrationStatusReader(
            paths=paths,
            manifest=MigrationManifest.load(migration_directory),
            offline_inspector=_ImmutableSqliteInspector(),
        ).inspect()
        assert status.state == "OFFLINE_SIDECAR_STATE_UNSAFE"
    finally:
        wal.unlink(missing_ok=True)


def test_foundation_diagnostics_are_bounded_counts_only(
    tmp_path,
    migration_directory,
    security_provider,
) -> None:
    runtime, paths, _server, _security, _reconciled = _runtime(
        tmp_path,
        migration_directory,
        security_provider,
    )
    health = runtime.start()
    factory = runtime.connection_factory
    runtime.record_error_code("PERSISTENCE_BUSY")
    query = FoundationStatusQueries(runtime=runtime, connection_factory=factory)
    assert query.get_runtime_health() == health
    diagnostics = query.get_foundation_diagnostics_state()
    assert diagnostics.request_executor_depth == "EMPTY"
    assert diagnostics.background_executor_depth == "EMPTY"
    assert diagnostics.open_authoritative_connections == 0
    assert diagnostics.active_transactions == 0
    assert set(diagnostics.durable_jobs_by_state) == {
        "queued","running","waiting_review","retry_wait","completed","failed","cancelled"
    }
    assert diagnostics.last_completed_migration is not None
    assert diagnostics.last_completed_migration.sequence == health.migration_sequence
    assert diagnostics.recent_error_codes == ("PERSISTENCE_BUSY",)
    assert "payload" not in repr(diagnostics).lower()
    runtime.shutdown(grace_seconds=1)
