from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from threading import Condition, Lock
from time import monotonic
from typing import Any, Protocol

from soma.foundation.errors import PersistenceConnectionUnsafe, SecurityNotReady, SomaError


class SqlCipherConnectionSecurityProvider(Protocol):
    """LLD-12-owned security seam consumed by LLD-01."""

    def acquire_live_dek_handle(self) -> Any: ...

    def key_connection(self, connection: Any, key_handle: Any) -> None: ...

    def verify_cipher_connection(self, connection: Any) -> None: ...


class DbApiDriver(Protocol):
    def connect(self, database: str, *, timeout: float, check_same_thread: bool = True) -> Any: ...


def load_sqlcipher_driver() -> DbApiDriver:
    """Load the authoritative runtime driver lazily.

    No plaintext sqlite3 fallback is permitted. Tests may inject a DB-API compatible
    driver explicitly, but application startup must fail if sqlcipher3 is absent.
    """

    try:
        import sqlcipher3  # type: ignore[import-not-found]
    except ImportError as exc:  # pragma: no cover - depends on packaged runtime
        raise SecurityNotReady("sqlcipher3 authoritative provider is unavailable") from exc
    return sqlcipher3


class WriteAdmissionGate:
    """Atomically closes new writer admission while existing UnitOfWork instances drain."""

    def __init__(self) -> None:
        self._condition = Condition()
        self._accepting = True
        self._active = 0

    def enter(self) -> None:
        with self._condition:
            if not self._accepting:
                raise SomaError("HOST_QUIESCING", "new authoritative writes are disabled")
            self._active += 1

    def exit(self) -> None:
        with self._condition:
            if self._active <= 0:
                raise RuntimeError("write admission gate underflow")
            self._active -= 1
            if self._active == 0:
                self._condition.notify_all()

    def quiesce(self) -> None:
        with self._condition:
            self._accepting = False
            if self._active == 0:
                self._condition.notify_all()

    def reopen(self) -> None:
        with self._condition:
            if self._active:
                raise RuntimeError("cannot reopen write admission with active writers")
            self._accepting = True

    def wait_for_drain(self, timeout_seconds: float) -> bool:
        deadline = monotonic() + max(0.0, timeout_seconds)
        with self._condition:
            while self._active:
                remaining = deadline - monotonic()
                if remaining <= 0:
                    return False
                self._condition.wait(remaining)
            return True

    @property
    def active(self) -> int:
        with self._condition:
            return self._active


@dataclass(frozen=True, slots=True)
class PersistenceMetricsSnapshot:
    open_authoritative_connections: int
    active_transactions: int


class PersistenceMetrics:
    def __init__(self) -> None:
        self._lock = Lock()
        self._open_connections = 0
        self._active_transactions = 0

    def _opened(self) -> None:
        with self._lock:
            self._open_connections += 1

    def _closed(self, *, was_in_transaction: bool) -> None:
        with self._lock:
            if self._open_connections <= 0:
                raise RuntimeError("persistence connection metric underflow")
            self._open_connections -= 1
            if was_in_transaction:
                if self._active_transactions <= 0:
                    raise RuntimeError("persistence transaction metric underflow")
                self._active_transactions -= 1

    def _transaction_transition(self, before: bool, after: bool) -> None:
        if before == after:
            return
        with self._lock:
            if after:
                self._active_transactions += 1
            else:
                if self._active_transactions <= 0:
                    raise RuntimeError("persistence transaction metric underflow")
                self._active_transactions -= 1

    def snapshot(self) -> PersistenceMetricsSnapshot:
        with self._lock:
            return PersistenceMetricsSnapshot(
                open_authoritative_connections=self._open_connections,
                active_transactions=self._active_transactions,
            )


class _TrackedConnection:
    def __init__(self, connection: Any, metrics: PersistenceMetrics) -> None:
        object.__setattr__(self, "_connection", connection)
        object.__setattr__(self, "_metrics", metrics)
        object.__setattr__(self, "_closed", False)
        metrics._opened()

    def _call_with_transaction_tracking(self, name: str, *args, **kwargs):
        connection = object.__getattribute__(self, "_connection")
        metrics = object.__getattribute__(self, "_metrics")
        before = bool(getattr(connection, "in_transaction", False))
        try:
            return getattr(connection, name)(*args, **kwargs)
        finally:
            after = bool(getattr(connection, "in_transaction", False))
            metrics._transaction_transition(before, after)

    def execute(self, *args, **kwargs):
        return self._call_with_transaction_tracking("execute", *args, **kwargs)

    def executemany(self, *args, **kwargs):
        return self._call_with_transaction_tracking("executemany", *args, **kwargs)

    def executescript(self, *args, **kwargs):
        return self._call_with_transaction_tracking("executescript", *args, **kwargs)

    def backup(self, target, *args, **kwargs):
        raw_target = (
            object.__getattribute__(target, "_connection")
            if isinstance(target, _TrackedConnection)
            else target
        )
        return object.__getattribute__(self, "_connection").backup(
            raw_target,
            *args,
            **kwargs,
        )

    def commit(self) -> None:
        self._call_with_transaction_tracking("commit")

    def rollback(self) -> None:
        self._call_with_transaction_tracking("rollback")

    def close(self) -> None:
        if object.__getattribute__(self, "_closed"):
            return
        connection = object.__getattribute__(self, "_connection")
        metrics = object.__getattribute__(self, "_metrics")
        was_in_transaction = bool(getattr(connection, "in_transaction", False))
        try:
            connection.close()
        finally:
            object.__setattr__(self, "_closed", True)
            metrics._closed(was_in_transaction=was_in_transaction)

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb) -> bool:
        connection = object.__getattribute__(self, "_connection")
        before = bool(getattr(connection, "in_transaction", False))
        try:
            result = connection.__exit__(exc_type, exc, tb)
        finally:
            after = bool(getattr(connection, "in_transaction", False))
            object.__getattribute__(self, "_metrics")._transaction_transition(before, after)
        return bool(result)

    def __getattr__(self, name: str):
        return getattr(object.__getattribute__(self, "_connection"), name)

    def __setattr__(self, name: str, value: object) -> None:
        if name in {"_connection", "_metrics", "_closed"}:
            object.__setattr__(self, name, value)
            return
        setattr(object.__getattribute__(self, "_connection"), name, value)


class ConnectionFactory:
    def __init__(
        self,
        database_path: Path,
        security_provider: SqlCipherConnectionSecurityProvider,
        *,
        driver: DbApiDriver | None = None,
    ) -> None:
        self._database_path = Path(database_path)
        self._security_provider = security_provider
        self._driver = driver
        self._metrics = PersistenceMetrics()
        self._write_admission_gate: WriteAdmissionGate | None = None

    @property
    def database_path(self) -> Path:
        return self._database_path

    @property
    def metrics(self) -> PersistenceMetrics:
        return self._metrics

    def install_write_admission_gate(self, gate: WriteAdmissionGate) -> None:
        if self._write_admission_gate is not None and self._write_admission_gate is not gate:
            raise RuntimeError("ConnectionFactory write admission gate is already installed")
        self._write_admission_gate = gate

    def enter_authoritative_write(self) -> bool:
        if self._write_admission_gate is None:
            return False
        self._write_admission_gate.enter()
        return True

    def exit_authoritative_write(self, admitted: bool) -> None:
        if admitted:
            if self._write_admission_gate is None:
                raise RuntimeError("ConnectionFactory write admission gate disappeared")
            self._write_admission_gate.exit()

    def _driver_or_runtime(self) -> DbApiDriver:
        return self._driver if self._driver is not None else load_sqlcipher_driver()

    def open_authoritative(
        self,
        *,
        read_only: bool = False,
        require_wal: bool = True,
    ) -> Any:
        connection: Any | None = None
        key_handle: Any | None = None
        try:
            connection = self._driver_or_runtime().connect(
                str(self._database_path),
                timeout=5.0,
                check_same_thread=True,
            )
            key_handle = self._security_provider.acquire_live_dek_handle()
            self._security_provider.key_connection(connection, key_handle)
            self._security_provider.verify_cipher_connection(connection)
            self._apply_common_pragmas(connection)
            if require_wal:
                mode = str(connection.execute("PRAGMA journal_mode").fetchone()[0]).lower()
                if mode != "wal":
                    raise PersistenceConnectionUnsafe(
                        f"authoritative database journal mode must be WAL, got {mode!r}"
                    )
            if read_only:
                connection.execute("PRAGMA query_only=ON")
                query_only = int(connection.execute("PRAGMA query_only").fetchone()[0])
                if query_only != 1:
                    raise PersistenceConnectionUnsafe("read connection could not enable query_only")
            tracked = _TrackedConnection(connection, self._metrics)
            connection = None
            return tracked
        except (SecurityNotReady, PersistenceConnectionUnsafe):
            if connection is not None:
                connection.close()
            raise
        except BaseException as exc:
            if connection is not None:
                connection.close()
            raise PersistenceConnectionUnsafe("authoritative connection verification failed") from exc
        finally:
            # The opaque handle is deliberately not retained on the factory/connection wrapper.
            key_handle = None

    def configure_startup_database(self, connection: Any) -> None:
        """Establish persisted runtime WAL policy while instance ownership is held."""

        mode = str(connection.execute("PRAGMA journal_mode=WAL").fetchone()[0]).lower()
        if mode != "wal":
            raise PersistenceConnectionUnsafe(f"could not establish WAL mode: {mode!r}")
        connection.execute("PRAGMA wal_autocheckpoint=1000")
        checkpoint = int(connection.execute("PRAGMA wal_autocheckpoint").fetchone()[0])
        if checkpoint != 1000:
            raise PersistenceConnectionUnsafe("wal_autocheckpoint verification failed")

    @staticmethod
    def _apply_common_pragmas(connection: Any) -> None:
        # SQLite can silently ignore an unsupported pragma. Verify every required
        # setting on each connection before any repository receives it.
        settings = (
            ("foreign_keys", "ON", 1),
            ("busy_timeout", "5000", 5000),
            ("trusted_schema", "OFF", 0),
            ("temp_store", "MEMORY", 2),
            ("synchronous", "FULL", 2),
            ("secure_delete", "FAST", 2),
            ("read_uncommitted", "OFF", 0),
            ("wal_autocheckpoint", "1000", 1000),
        )
        for name, setting, expected in settings:
            connection.execute(f"PRAGMA {name}={setting}")
            row = connection.execute(f"PRAGMA {name}").fetchone()
            if row is None or row[0] != expected:
                raise PersistenceConnectionUnsafe(f"required {name} pragma verification failed")
        connection.enable_load_extension(False)
