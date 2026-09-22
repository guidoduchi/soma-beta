from __future__ import annotations

import os
import sqlite3
from pathlib import Path

from soma.foundation.migrations.manifest import MigrationManifest
from soma.foundation.persistence.connections import ConnectionFactory
from soma.foundation.persistence.uow import ReadSnapshot
from soma.foundation.queries.status import FoundationStatusQueries, MigrationStatusReader
from soma.foundation.runtime import DataInstanceLock, InstancePaths
from test_foundation_runtime_host import _runtime


class _ImmutableSqliteInspector:
    def open_immutable(self, path: Path):
        return sqlite3.connect(
            f"file:{path.as_posix()}?mode=ro&immutable=1",
            uri=True,
            check_same_thread=True,
        )


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
    factory = runtime._factory
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
