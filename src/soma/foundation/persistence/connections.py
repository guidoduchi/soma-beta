from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import Any, Protocol

from soma.foundation.errors import PersistenceConnectionUnsafe, SecurityNotReady


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

    @property
    def database_path(self) -> Path:
        return self._database_path

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
            return connection
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
        connection.execute("PRAGMA foreign_keys=ON")
        if int(connection.execute("PRAGMA foreign_keys").fetchone()[0]) != 1:
            raise PersistenceConnectionUnsafe("foreign_keys pragma could not be enabled")
        connection.execute("PRAGMA busy_timeout=5000")
        connection.execute("PRAGMA trusted_schema=OFF")
        connection.execute("PRAGMA temp_store=MEMORY")
        connection.execute("PRAGMA synchronous=FULL")
        connection.execute("PRAGMA secure_delete=FAST")
        try:
            connection.enable_load_extension(False)
        except (AttributeError, NotImplementedError):
            # Packaged-runtime verification owns support for the driver-level API.
            pass
