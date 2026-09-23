from __future__ import annotations

import os
import re
import time
from collections import deque
from concurrent.futures import Future, ThreadPoolExecutor, wait
from dataclasses import dataclass
from threading import Lock
from typing import Callable, Protocol

from soma.foundation.application.command_boundary import (
    CommandBoundary,
    CommandEnvelope,
    PreparedMutation,
)
from soma.foundation.audit.registry import AuditActionContract, AuditRegistry
from soma.foundation.audit.writer import AuditEventInput, AuditResultRef, AuditWriter
from soma.foundation.contracts.foundation import RuntimeHealth, ShutdownResult
from soma.foundation.errors import IntegrityFailure, PersistenceFailure, SomaError
from soma.foundation.identifiers import new_uuid4, require_uuid4, utc_epoch_seconds
from soma.foundation.migrations.manifest import MigrationManifest
from soma.foundation.migrations.runner import MigrationRunner
from soma.foundation.migrations.verification import verify_foundation_schema
from soma.foundation.persistence.connections import ConnectionFactory, WriteAdmissionGate
from soma.foundation.strict_json import ObjectContract

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

    def stop(self, timeout_seconds: float | None = None) -> None: ...

    def is_stopped(self) -> bool: ...


MigrationRunnerFactory = Callable[[Callable[[], bool]], MigrationRunner]
StartupReconciler = Callable[[str, int], None]


def _runtime_audit_writer() -> AuditWriter:
    registry = AuditRegistry()
    registry.register(
        AuditActionContract(
            action_type="foundation.runtime_shutdown_requested",
            action_version=1,
            payload_schema="FoundationShutdownAuditV1",
            payload_version=1,
            payload_contract=ObjectContract(
                name="FoundationShutdownAuditV1",
                version=1,
                required_fields=frozenset(
                    {"run_id", "data_instance_id", "shutdown_state"}
                ),
                allowed_fields=frozenset(
                    {"run_id", "data_instance_id", "shutdown_state"}
                ),
                max_utf8_bytes=4096,
            ),
        )
    )
    return AuditWriter(registry)


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
        self._write_gate = WriteAdmissionGate()
        self._write_gate.quiesce()
        self._factory.install_write_admission_gate(self._write_gate)
        self._shutdown_boundary = CommandBoundary(
            self._factory,
            _runtime_audit_writer(),
        )

    @property
    def state(self) -> str:
        return self._state

    @property
    def target_migration_sequence(self) -> int:
        return len(self._manifest.entries)

    @property
    def connection_factory(self) -> ConnectionFactory:
        return self._factory

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
        if self._state == "FAILED" and self._has_runtime_resources():
            raise SomaError(
                "INSTANCE_OWNED",
                "failed runtime still owns resources pending safe cleanup",
            )
        self._write_gate.reopen()
        self._set_state("STARTING")
        try:
            self._paths.prepare_for_start()
            self._run_id = new_uuid4()
            self._started_at_utc = utc_epoch_seconds()

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
            # A provider may acquire resources before prepare_run returns. Mark
            # cleanup ownership before entering the provider call so partial
            # preparation is always paired with close_run.
            self._security_started = True
            self._run_security.prepare_run(
                run_id=self._run_id,
                data_instance_id=self._data_instance_id,
                readiness_locator=locator,
            )
            self._set_state("LISTENING_NOT_READY")
            # Likewise, start() may create a listening thread/socket before it
            # raises. Cleanup ownership begins before the call, not after it.
            self._server_started = True
            self._server.start(self._loopback.socket)

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
            self._write_gate.quiesce()
            self._set_state("FAILED")
            self._unwind_failed_start(exc)
            raise

    def health(self) -> RuntimeHealth:
        return self._health_for_state(self._state)

    def request_shutdown(
        self,
        *,
        command_id: str,
        run_id: str,
        data_instance_id: str,
        actor_kind: str = "local_user",
        actor_id: str | None = None,
    ) -> ShutdownResult:
        require_uuid4(command_id)
        require_uuid4(run_id)
        require_uuid4(data_instance_id)
        if run_id != self._run_id or data_instance_id != self._data_instance_id:
            raise SomaError("FORBIDDEN", "shutdown run/data identity does not match current host")
        if self._state == "QUIESCING":
            return ShutdownResult("ALREADY_QUIESCING", run_id, data_instance_id)
        if self._state not in {"READY", "LISTENING_NOT_READY"}:
            raise SomaError("HOST_NOT_READY", "runtime is not available for shutdown")

        envelope = CommandEnvelope(
            command_id=command_id,
            command_type="ShutdownHost",
            target_type="runtime_run",
            target_id=run_id,
            semantic_payload={
                "run_id": run_id,
                "data_instance_id": data_instance_id,
            },
        )

        def prepare(uow) -> PreparedMutation:
            if self._state not in {"READY", "LISTENING_NOT_READY"}:
                raise SomaError("HOST_QUIESCING", "runtime began quiescing before shutdown commit")
            row = uow.connection.execute(
                "SELECT data_instance_id FROM instance_metadata WHERE singleton=1"
            ).fetchone()
            if row is None or str(row[0]) != data_instance_id:
                raise IntegrityFailure("shutdown data instance identity changed")
            audit_event_id = new_uuid4()

            def apply(inner):
                return AuditEventInput(
                    audit_event_id=audit_event_id,
                    action_type="foundation.runtime_shutdown_requested",
                    action_version=1,
                    actor_kind=actor_kind,
                    actor_id=actor_id,
                    target_type="runtime_run",
                    target_id=run_id,
                    command_id=command_id,
                    payload_schema="FoundationShutdownAuditV1",
                    payload_version=1,
                    payload={
                        "run_id": run_id,
                        "data_instance_id": data_instance_id,
                        "shutdown_state": "QUIESCING",
                    },
                    resulting_event_refs=(
                        AuditResultRef("runtime_run", run_id),
                    ),
                )

            return PreparedMutation(
                no_change=False,
                result_type="runtime_shutdown",
                result_id=run_id,
                apply=apply,
                response_schema="ShutdownHostAcceptedV1",
                response_version=1,
                response={
                    "shutdown_state": "QUIESCING",
                    "run_id": run_id,
                    "data_instance_id": data_instance_id,
                },
            )

        result = self._shutdown_boundary.execute(envelope, prepare)
        if (
            result.response_schema != "ShutdownHostAcceptedV1"
            or result.response_version != 1
            or not isinstance(result.response, dict)
        ):
            raise IntegrityFailure("shutdown replay result contract is invalid")
        self.quiesce()
        return ShutdownResult("QUIESCING", run_id, data_instance_id)

    def quiesce(self) -> ShutdownResult:
        if self._run_id is None or self._data_instance_id is None:
            raise SomaError("HOST_NOT_READY", "runtime is not active")
        if self._state == "QUIESCING":
            return ShutdownResult("ALREADY_QUIESCING", self._run_id, self._data_instance_id)
        if self._state not in {"READY", "LISTENING_NOT_READY"}:
            raise SomaError("HOST_NOT_READY", "runtime cannot quiesce from current state")
        self._write_gate.quiesce()
        self._set_state("QUIESCING")
        if self._request_executor is not None:
            self._request_executor.quiesce()
        if self._background_executor is not None:
            self._background_executor.quiesce()
        return ShutdownResult("QUIESCING", self._run_id, self._data_instance_id)

    @staticmethod
    def _remaining_shutdown_seconds(deadline: float) -> float:
        return max(0.0, deadline - time.monotonic())

    def shutdown(self, *, grace_seconds: float = 30.0) -> ShutdownResult:
        if grace_seconds < 0:
            raise ValueError("grace_seconds must be nonnegative")
        if self._run_id is None or self._data_instance_id is None:
            raise SomaError("HOST_NOT_READY", "runtime is not active")
        run_id = self._run_id
        data_instance_id = self._data_instance_id
        if self._state != "QUIESCING":
            self.quiesce()

        deadline = time.monotonic() + grace_seconds
        if not self._write_gate.wait_for_drain(
            self._remaining_shutdown_seconds(deadline)
        ):
            raise SomaError(
                "INTERNAL_ERROR",
                "active authoritative writes did not drain before shutdown deadline",
            )
        request_drained = (
            True
            if self._request_executor is None
            else self._request_executor.drain(
                self._remaining_shutdown_seconds(deadline)
            )
        )
        background_drained = (
            True
            if self._background_executor is None
            else self._background_executor.drain(
                self._remaining_shutdown_seconds(deadline)
            )
        )
        if not request_drained or not background_drained:
            raise SomaError(
                "INTERNAL_ERROR",
                "runtime work did not drain before shutdown deadline",
            )
        connection = self._factory.open_authoritative(read_only=False, require_wal=True)
        try:
            remaining_ms = max(
                0,
                int(self._remaining_shutdown_seconds(deadline) * 1000),
            )
            connection.execute(f"PRAGMA busy_timeout={remaining_ms}")
            row = connection.execute("PRAGMA wal_checkpoint(TRUNCATE)").fetchone()
            if row is None or int(row[0]) != 0:
                raise PersistenceFailure("WAL checkpoint did not complete during shutdown")
        finally:
            connection.close()
        self._close_runtime_resources(deadline=deadline)
        self._set_state("STOPPED")
        return ShutdownResult("STOPPED", run_id, data_instance_id)

    def _has_runtime_resources(self) -> bool:
        return any(
            (
                self._request_executor is not None,
                self._background_executor is not None,
                self._server_started,
                self._loopback is not None,
                self._registry_published,
                self._security_started,
                self._lock is not None,
            )
        )

    def _server_is_stopped(self) -> bool:
        probe = getattr(self._server, "is_stopped", None)
        if probe is None:
            return False
        try:
            return bool(probe())
        except BaseException:
            return False

    def _close_runtime_resources(self, *, deadline: float | None = None) -> None:
        run_id = self._run_id
        data_instance_id = self._data_instance_id
        failures: list[tuple[str, BaseException]] = []
        retain_ownership = False

        if self._request_executor is not None:
            try:
                self._request_executor.close()
            except BaseException as exc:
                failures.append(("request_executor.close", exc))
                retain_ownership = True
            else:
                self._request_executor = None
        if self._background_executor is not None:
            try:
                self._background_executor.close()
            except BaseException as exc:
                failures.append(("background_executor.close", exc))
                retain_ownership = True
            else:
                self._background_executor = None

        if self._server_started:
            try:
                timeout_seconds = (
                    None
                    if deadline is None
                    else self._remaining_shutdown_seconds(deadline)
                )
                self._server.stop(timeout_seconds)
            except BaseException as exc:
                failures.append(("server.stop", exc))
                if self._server_is_stopped():
                    self._server_started = False
                else:
                    retain_ownership = True
            else:
                self._server_started = False

        if self._loopback is not None:
            try:
                self._loopback.close()
            except BaseException as exc:
                failures.append(("loopback.close", exc))
            else:
                self._loopback = None

        # Security and registry identity must remain live while an adapter or
        # executor may still perform authoritative work. The process lock is the
        # final ownership resource and is intentionally retained in that case.
        if (
            not retain_ownership
            and self._security_started
            and run_id is not None
            and data_instance_id is not None
        ):
            try:
                self._run_security.close_run(
                    run_id=run_id,
                    data_instance_id=data_instance_id,
                )
            except BaseException as exc:
                failures.append(("run_security.close_run", exc))
                retain_ownership = True
            else:
                self._security_started = False

        if (
            not retain_ownership
            and self._registry_published
            and run_id is not None
            and data_instance_id is not None
        ):
            try:
                RuntimeRegistry.remove_owned(
                    self._paths.registry,
                    run_id=run_id,
                    data_instance_id=data_instance_id,
                )
            except BaseException as exc:
                failures.append(("runtime_registry.remove_owned", exc))
            else:
                self._registry_published = False

        if not retain_ownership and self._lock is not None:
            try:
                self._lock.release()
            except BaseException as exc:
                failures.append(("instance_lock.release", exc))
            else:
                self._lock = None

        if failures:
            detail = "; ".join(
                f"{stage}: {type(exc).__name__}: {exc}"
                for stage, exc in failures
            )
            raise SomaError(
                "INTERNAL_ERROR",
                f"runtime cleanup incomplete: {detail}",
            )

    def _unwind_failed_start(self, primary_error: BaseException) -> None:
        try:
            self._close_runtime_resources()
        except BaseException as cleanup_error:
            self.record_error_code(
                cleanup_error.code
                if isinstance(cleanup_error, SomaError)
                else "INTERNAL_ERROR"
            )
            primary_error.add_note(
                "failed-start cleanup also failed: "
                f"{type(cleanup_error).__name__}: {cleanup_error}"
            )
