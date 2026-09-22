from __future__ import annotations

from pathlib import Path
from typing import Any, Protocol

from soma.foundation.contracts.foundation import (
    FoundationDiagnosticsState,
    MigrationIdentity,
    MigrationStatus,
    RuntimeHealth,
)
from soma.foundation.errors import IntegrityFailure, MigrationError, SomaError
from soma.foundation.migrations.manifest import MigrationManifest
from soma.foundation.migrations.verification import verify_foundation_schema_readonly
from soma.foundation.persistence.connections import ConnectionFactory
from soma.foundation.persistence.uow import ReadSnapshot
from soma.foundation.runtime.host import HostRuntime
from soma.foundation.runtime.instance_lock import DataInstanceLock
from soma.foundation.runtime.paths import InstancePaths
from soma.foundation.runtime.registry import RuntimeRegistry, RuntimeRegistryRecord


class OfflineDatabaseInspector(Protocol):
    def open_immutable(self, path: Path) -> Any: ...


class LiveRuntimeStatusClient(Protocol):
    def verified_health(self, registry: RuntimeRegistryRecord) -> RuntimeHealth | None: ...


class MigrationStatusReader:
    def __init__(
        self,
        *,
        paths: InstancePaths,
        manifest: MigrationManifest,
        offline_inspector: OfflineDatabaseInspector,
        live_client: LiveRuntimeStatusClient | None = None,
    ) -> None:
        self._paths = paths
        self._manifest = manifest
        self._offline = offline_inspector
        self._live = live_client

    def _status(
        self,
        state: str,
        *,
        sequence: int | None = None,
        migration_id: str | None = None,
        integrity: str | None = None,
    ) -> MigrationStatus:
        return MigrationStatus(
            state=state,  # type: ignore[arg-type]
            current_sequence=sequence,
            current_migration_id=migration_id,
            target_sequence=len(self._manifest.entries),
            integrity_state=integrity,
        )

    def _verified_live(self) -> MigrationStatus | None:
        if self._live is None:
            return None
        try:
            registry = RuntimeRegistry.read(self._paths.registry)
        except IntegrityFailure:
            return None
        if registry is None:
            return None
        health = self._live.verified_health(registry)
        if health is None:
            return None
        if (
            health.run_id != registry.run_id
            or health.data_instance_id != registry.data_instance_id
        ):
            return None
        state = (
            "LIVE_CURRENT"
            if health.migration_sequence == len(self._manifest.entries)
            else "LIVE_MIGRATIONS_PENDING"
        )
        return self._status(
            state,
            sequence=health.migration_sequence,
            migration_id=health.migration_id,
            integrity=health.integrity_state,
        )

    def inspect(self) -> MigrationStatus:
        try:
            self._manifest.validate()
        except MigrationError:
            return self._status("DRIFT", integrity="MIGRATION_DRIFT")

        database = self._paths.database
        if not database.exists():
            return self._status("NOT_INITIALIZED")
        if not self._paths.lock.exists():
            return self._status("INSTANCE_LAYOUT_INVALID")

        live = self._verified_live()
        if live is not None:
            return live

        try:
            inspection_lock = DataInstanceLock.acquire(self._paths.lock, create=False)
        except SomaError as exc:
            if exc.code == "INSTANCE_OWNED":
                return self._status("LOCKED_UNVERIFIED")
            return self._status("INSPECTION_FAILURE")
        except BaseException:
            return self._status("INSPECTION_FAILURE")

        try:
            for suffix in ("-wal", "-shm"):
                if Path(str(database) + suffix).exists():
                    return self._status("OFFLINE_SIDECAR_STATE_UNSAFE")
            try:
                connection = self._offline.open_immutable(database)
            except BaseException:
                return self._status("INVALID_DATABASE")
            try:
                try:
                    rows = connection.execute(
                        "SELECT sequence,migration_id,sha256 "
                        "FROM schema_migrations ORDER BY sequence"
                    ).fetchall()
                except BaseException:
                    return self._status("INVALID_DATABASE")
                applied = [
                    (int(row[0]), str(row[1]), str(row[2]))
                    for row in rows
                ]
                target = self._manifest.entries
                if len(applied) > len(target):
                    last = applied[-1]
                    return self._status(
                        "UNSUPPORTED_FUTURE_VERSION",
                        sequence=last[0],
                        migration_id=last[1],
                    )
                for index, actual in enumerate(applied):
                    expected = target[index]
                    if actual != (
                        expected.sequence,
                        expected.migration_id,
                        expected.sha256,
                    ):
                        last = applied[-1] if applied else None
                        return self._status(
                            "LEDGER_MISMATCH",
                            sequence=None if last is None else last[0],
                            migration_id=None if last is None else last[1],
                        )
                last = applied[-1] if applied else None
                if len(applied) < len(target):
                    return self._status(
                        "MIGRATIONS_PENDING",
                        sequence=None if last is None else last[0],
                        migration_id=None if last is None else last[1],
                        integrity="PREFIX_VERIFIED",
                    )
                try:
                    current = verify_foundation_schema_readonly(connection)
                except BaseException:
                    return self._status(
                        "INTEGRITY_FAILURE",
                        sequence=None if last is None else last[0],
                        migration_id=None if last is None else last[1],
                        integrity="FAILED",
                    )
                if not current:
                    return self._status(
                        "INTEGRITY_FAILURE",
                        sequence=None if last is None else last[0],
                        migration_id=None if last is None else last[1],
                        integrity="FAILED",
                    )
                return self._status(
                    "CURRENT",
                    sequence=None if last is None else last[0],
                    migration_id=None if last is None else last[1],
                    integrity="VERIFIED",
                )
            finally:
                connection.close()
        finally:
            inspection_lock.release()


class FoundationStatusQueries:
    def __init__(
        self,
        *,
        runtime: HostRuntime,
        connection_factory: ConnectionFactory,
    ) -> None:
        self._runtime = runtime
        self._factory = connection_factory

    def get_runtime_health(self) -> RuntimeHealth:
        return self._runtime.health()

    def get_foundation_diagnostics_state(self) -> FoundationDiagnosticsState:
        if self._runtime.state != "READY":
            raise SomaError("HOST_NOT_READY", "Foundation diagnostics require READY runtime")
        request_state = self._runtime.request_executor.state()
        background_state = self._runtime.background_executor.state()
        metrics = self._factory.metrics.snapshot()
        job_states = {
            "queued": 0,
            "running": 0,
            "waiting_review": 0,
            "retry_wait": 0,
            "completed": 0,
            "failed": 0,
            "cancelled": 0,
        }
        last_migration = None
        with ReadSnapshot(self._factory) as snapshot:
            for row in snapshot.connection.execute(
                "SELECT state,COUNT(*) FROM durable_jobs GROUP BY state"
            ).fetchall():
                state = str(row[0])
                if state not in job_states:
                    raise IntegrityFailure("durable job has unknown state")
                job_states[state] = int(row[1])
            row = snapshot.connection.execute(
                "SELECT sequence,migration_id FROM schema_migrations "
                "ORDER BY sequence DESC LIMIT 1"
            ).fetchone()
            if row is not None:
                last_migration = MigrationIdentity(int(row[0]), str(row[1]))
        return FoundationDiagnosticsState(
            request_executor_depth=request_state.category,  # type: ignore[arg-type]
            background_executor_depth=background_state.category,  # type: ignore[arg-type]
            open_authoritative_connections=metrics.open_authoritative_connections,
            active_transactions=metrics.active_transactions,
            durable_jobs_by_state=job_states,
            last_completed_migration=last_migration,
            recent_error_codes=self._runtime.recent_error_codes,
        )
