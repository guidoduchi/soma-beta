from __future__ import annotations

import os
import re
from collections import deque
from concurrent.futures import Future, ThreadPoolExecutor, wait
from dataclasses import dataclass
from threading import Lock
from typing import Callable, Protocol

from soma.foundation.contracts.foundation import RuntimeHealth, ShutdownResult
from soma.foundation.errors import IntegrityFailure, PersistenceFailure, SomaError
from soma.foundation.identifiers import new_uuid4, require_uuid4, utc_epoch_seconds
from soma.foundation.migrations.manifest import MigrationManifest
from soma.foundation.migrations.runner import MigrationRunner
from soma.foundation.migrations.verification import verify_foundation_schema
from soma.foundation.persistence.connections import ConnectionFactory

from .instance_lock import DataInstanceLock
from .loopback import BoundLoopbackSocket
from .paths import InstancePaths
from .registry import RuntimeRegistry, RuntimeRegistryRecord

_HOST_STATES = frozenset(
    {
        "STARTING",
        "MIGRATING",
        "VERIFYING",
        "LISTENING_NOT_READY",
        "READY",
        "QUIESCING",
        "STOPPED",
        "FAILED",
    }
)


class RuntimeSecurityProvider(Protocol):
    def prepare_run(
        self,
        *,
        run_id: str,
        data_instance_id: str,
        readiness_locator: str,
    ) -> None: ...

    def close_run(self, *, run_id: str, data_instance_id: str) -> None: ...


class LoopbackServerAdapter(Protocol):
    def start(self, bound_socket) -> None: ...

    def authenticated_self_health(self, expected: RuntimeHealth) -> bool: ...

    def stop(self) -> None: ...


MigrationRunnerFactory = Callable[[Callable[[], bool]], MigrationRunner]
StartupReconciler = Callable[[str, int], None]


@dataclass(frozen=True, slots=True)
class ExecutorState:
    outstanding: int
    capacity: int

    @property
    def category(self) -> str:
        if self.outstanding <= 0:
            return "EMPTY"
        ratio = self.outstanding / self.capacity
        if ratio <= 0.5:
            return "LOW"
        if ratio < 1:
            return "ELEVATED"
        return "SATURATED"


class HostExecutor:
    def __init__(self, max_workers: int, thread_name_prefix: str) -> None:
        self._executor = ThreadPoolExecutor(
            max_workers=max_workers,
            thread_name_prefix=thread_name_prefix,
        )
        self._max_workers = max_workers
        self._lock = Lock()
        self._futures: set[Future] = set()
        self._accepting = True

    def submit(self, function, /, *args, **kwargs) -> Future:
        with self._lock:
            if not self._accepting:
                raise SomaError("HOST_QUIESCING", "runtime executor is not accepting new work")
            future = self._executor.submit(function, *args, **kwargs)
            self._futures.add(future)
        future.add_done_callback(self._discard)
        return future

    def _discard(self, future: Future) -> None:
        with self._lock:
            self._futures.discard(future)

    def state(self) -> ExecutorState:
        with self._lock:
            return ExecutorState(len(self._futures), self._max_workers)

    def quiesce(self) -> None:
        with self._lock:
            self._accepting = False

    def drain(self, timeout_seconds: float) -> bool:
        self.quiesce()
        with self._lock:
            pending = set(self._futures)
        if not pending:
            return True
        _done, not_done = wait(pending, timeout=timeout_seconds)
        return not not_done

    def close(self) -> None:
        self.quiesce()
        self._executor.shutdown(wait=False, cancel_futures=True)


class HostRuntime:
    """Foundation host lifecycle; framework and LLD-12 details remain injected seams."""

    def __init__(
        self,
        *,
        paths: InstancePaths,
        connection_factory: ConnectionFactory,
        migration_manifest: MigrationManifest,
        migration_runner_factory: MigrationRunnerFactory,
        server: LoopbackServerAdapter,
        run_security: RuntimeSecurityProvider,
        startup_reconciler: StartupReconciler,
        app_version: str,
        protocol_version: str,
        process_birth_id: str,
    ) -> None:
        if connection_factory.database_path.resolve(strict=False) != paths.database:
            raise ValueError("ConnectionFactory database path must equal canonical instance database")
        if not app_version or not protocol_version or not process_birth_id:
            raise ValueError("runtime version/process identity values must be nonempty")
        self._paths = paths
        self._factory = connection_factory
        self._manifest = migration_manifest
        self._runner_factory = migration_runner_factory
        self._server = server
        self._run_security = run_security
        self._startup_reconciler = startup_reconciler
        self._app_version = app_version
        self._protocol_version = protocol_version
        self._process_birth_id = process_birth_id
        self._state = "STOPPED"
        self._lock: DataInstanceLock | None = None
        self._loopback: BoundLoopbackSocket | None = None
        self._request_executor: HostExecutor | None = None
        self._background_executor: HostExecutor | None = None
        self._run_id: str | None = None
        self._data_instance_id: str | None = None
        self._started_at_utc: int | None = None
        self._migration_sequence = 0
        self._migration_id: str | None = None
        self._integrity_state = "NOT_VERIFIED"
        self._registry_published = False
        self._server_started = False
        self._security_started = False
        self._recent_error_codes: deque[str] = deque(maxlen=32)

    @property
    def state(self) -> str:
        return self._state

    @property
    def recent_error_codes(self) -> tuple[str, ...]:
        return tuple(self._recent_error_codes)

    def record_error_code(self, code: str) -> None:
        if not isinstance(code, str) or re.fullmatch(r"[A-Z][A-Z0-9_]{0,63}", code) is None:
            raise ValueError("runtime diagnostic error code is invalid")
        self._recent_error_codes.append(code)

    @property
    def request_executor(self) -> HostExecutor:
        if self._request_executor is None:
            raise SomaError("HOST_NOT_READY", "request executor is unavailable")
        return self._request_executor

    @property
    def background_executor(self) -> HostExecutor:
        if self._background_executor is None:
            raise SomaError("HOST_NOT_READY", "background executor is unavailable")
        return self._background_executor

    def _set_state(self, state: str) -> None:
        if state not in _HOST_STATES:
            raise IntegrityFailure("runtime attempted an unknown host state")
        self._state = state

    def _read_current_identity(self) -> tuple[str, int, str | None]:
        connection = self._factory.open_authoritative(read_only=False, require_wal=True)
        try:
            verify_foundation_schema(connection)
            identity = connection.execute(
                "SELECT data_instance_id FROM instance_metadata WHERE singleton=1"
            ).fetchone()
            if identity is None:
                raise IntegrityFailure("data instance identity is unavailable")
            data_instance_id = str(identity[0])
            require_uuid4(data_instance_id)
            row = connection.execute(
                "SELECT sequence,migration_id FROM schema_migrations ORDER BY sequence DESC LIMIT 1"
            ).fetchone()
            sequence = 0 if row is None else int(row[0])
            migration_id = None if row is None else str(row[1])
            return data_instance_id, sequence, migration_id
        finally:
            connection.close()

    def _health_for_state(self, state: str) -> RuntimeHealth:
        if (
            self._run_id is None
            or self._data_instance_id is None
            or self._started_at_utc is None
        ):
            raise SomaError("HOST_NOT_READY", "runtime identity is unavailable")
        if state not in {"LISTENING_NOT_READY", "READY", "QUIESCING"}:
            raise SomaError("HOST_NOT_READY", "runtime health is unavailable in current state")
        return RuntimeHealth(
            protocol_version=self._protocol_version,
            run_id=self._run_id,
            data_instance_id=self._data_instance_id,
            host_state=state,  # type: ignore[arg-type]
            app_version=self._app_version,
            migration_sequence=self._migration_sequence,
            migration_id=self._migration_id,
            integrity_state=self._integrity_state,
            started_at_utc=self._started_at_utc,
        )

    def start(self) -> RuntimeHealth:
        if self._state not in {"STOPPED", "FAILED"}:
            raise SomaError("INSTANCE_OWNED", "this HostRuntime is already active")
        self._set_state("STARTING")
        self._paths.prepare_for_start()
        self._run_id = new_uuid4()
        self._started_at_utc = utc_epoch_seconds()
        try:
            self._lock = DataInstanceLock.acquire(self._paths.lock)
            runner = self._runner_factory(lambda: bool(self._lock and self._lock.held))
            self._set_state("MIGRATING")
            runner.initialize_or_migrate()

            self._set_state("VERIFYING")
            (
                self._data_instance_id,
                self._migration_sequence,
                self._migration_id,
            ) = self._read_current_identity()
            expected_sequence = len(self._manifest.entries)
            if self._migration_sequence != expected_sequence:
                raise IntegrityFailure("runtime migration sequence is not current")
            self._integrity_state = "VERIFIED"
            self._startup_reconciler(self._run_id, utc_epoch_seconds())

            self._request_executor = HostExecutor(4, "soma-request")
            self._background_executor = HostExecutor(2, "soma-background")
            self._loopback = BoundLoopbackSocket.bind()
            locator = f"http://127.0.0.1:{self._loopback.port}"
            self._run_security.prepare_run(
                run_id=self._run_id,
                data_instance_id=self._data_instance_id,
                readiness_locator=locator,
            )
            self._security_started = True
            self._set_state("LISTENING_NOT_READY")
            self._server.start(self._loopback.socket)
            self._server_started = True

            RuntimeRegistry.publish(
                self._paths.registry,
                RuntimeRegistryRecord(
                    registry_version=1,
                    origin="SOMA",
                    pid=os.getpid(),
                    process_birth_id=self._process_birth_id,
                    run_id=self._run_id,
                    protocol_version=self._protocol_version,
                    data_instance_id=self._data_instance_id,
                    readiness_locator=locator,
                ),
            )
            self._registry_published = True
            expected_health = self._health_for_state("LISTENING_NOT_READY")
            if not self._server.authenticated_self_health(expected_health):
                raise SomaError(
                    "SECURITY_NOT_READY",
                    "authenticated runtime self-health did not verify current run",
                )
            self._set_state("READY")
            return self.health()
        except BaseException as exc:
            self.record_error_code(exc.code if isinstance(exc, SomaError) else "INTERNAL_ERROR")
            self._set_state("FAILED")
            self._unwind_failed_start()
            raise

    def health(self) -> RuntimeHealth:
        return self._health_for_state(self._state)

    def quiesce(self) -> ShutdownResult:
        if self._run_id is None or self._data_instance_id is None:
            raise SomaError("HOST_NOT_READY", "runtime is not active")
        if self._state == "QUIESCING":
            return ShutdownResult("ALREADY_QUIESCING", self._run_id, self._data_instance_id)
        if self._state not in {"READY", "LISTENING_NOT_READY"}:
            raise SomaError("HOST_NOT_READY", "runtime cannot quiesce from current state")
        self._set_state("QUIESCING")
        if self._request_executor is not None:
            self._request_executor.quiesce()
        if self._background_executor is not None:
            self._background_executor.quiesce()
        return ShutdownResult("QUIESCING", self._run_id, self._data_instance_id)

    def shutdown(self, *, grace_seconds: float = 30.0) -> ShutdownResult:
        if grace_seconds < 0:
            raise ValueError("grace_seconds must be nonnegative")
        if self._run_id is None or self._data_instance_id is None:
            raise SomaError("HOST_NOT_READY", "runtime is not active")
        run_id = self._run_id
        data_instance_id = self._data_instance_id
        if self._state != "QUIESCING":
            self.quiesce()

        request_drained = (
            True
            if self._request_executor is None
            else self._request_executor.drain(grace_seconds)
        )
        background_drained = (
            True
            if self._background_executor is None
            else self._background_executor.drain(grace_seconds)
        )
        if not request_drained or not background_drained:
            raise SomaError("INTERNAL_ERROR", "runtime work did not drain before shutdown deadline")

        connection = self._factory.open_authoritative(read_only=False, require_wal=True)
        try:
            row = connection.execute("PRAGMA wal_checkpoint(TRUNCATE)").fetchone()
            if row is None or int(row[0]) != 0:
                raise PersistenceFailure("WAL checkpoint did not complete during shutdown")
        finally:
            connection.close()

        self._close_runtime_resources()
        self._set_state("STOPPED")
        return ShutdownResult("STOPPED", run_id, data_instance_id)

    def _close_runtime_resources(self) -> None:
        run_id = self._run_id
        data_instance_id = self._data_instance_id
        if self._request_executor is not None:
            self._request_executor.close()
            self._request_executor = None
        if self._background_executor is not None:
            self._background_executor.close()
            self._background_executor = None
        if self._server_started:
            try:
                self._server.stop()
            finally:
                self._server_started = False
        if self._loopback is not None:
            self._loopback.close()
            self._loopback = None
        if (
            self._registry_published
            and run_id is not None
            and data_instance_id is not None
        ):
            RuntimeRegistry.remove_owned(
                self._paths.registry,
                run_id=run_id,
                data_instance_id=data_instance_id,
            )
            self._registry_published = False
        if self._security_started and run_id is not None and data_instance_id is not None:
            try:
                self._run_security.close_run(
                    run_id=run_id,
                    data_instance_id=data_instance_id,
                )
            finally:
                self._security_started = False
        if self._lock is not None:
            self._lock.release()
            self._lock = None

    def _unwind_failed_start(self) -> None:
        try:
            self._close_runtime_resources()
        except BaseException:
            # Startup is already failed. Do not replace the original failure with
            # best-effort cleanup details at this boundary.
            pass
