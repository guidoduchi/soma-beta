from __future__ import annotations

from contextvars import ContextVar
from types import TracebackType
from typing import Any, Self

from soma.foundation.errors import (
    PersistenceBusy,
    PersistenceFailure,
    PersistenceRollbackFailure,
)

from .connections import ConnectionFactory

_active_uow: ContextVar[bool] = ContextVar("soma_foundation_active_uow", default=False)


def _is_busy_error(exc: BaseException) -> bool:
    text = str(exc).lower()
    return "database is locked" in text or "database is busy" in text or "sqlite_busy" in text


class UnitOfWork:
    """One authoritative SOMA writer transaction.

    Cross-domain participants receive this instance. They must not open, commit,
    roll back, or nest another UnitOfWork.
    """

    def __init__(self, connection_factory: ConnectionFactory) -> None:
        self._factory = connection_factory
        self._connection: Any | None = None
        self._token: Any | None = None
        self._committed = False

    @property
    def connection(self) -> Any:
        if self._connection is None:
            raise RuntimeError("UnitOfWork has not been entered")
        return self._connection

    def __enter__(self) -> Self:
        if _active_uow.get():
            raise PersistenceFailure("nested authoritative UnitOfWork is forbidden")
        self._token = _active_uow.set(True)
        try:
            self._connection = self._factory.open_authoritative(read_only=False)
            self._connection.execute("BEGIN IMMEDIATE")
            return self
        except BaseException as exc:
            if self._connection is not None:
                self._connection.close()
                self._connection = None
            if self._token is not None:
                _active_uow.reset(self._token)
                self._token = None
            if _is_busy_error(exc):
                raise PersistenceBusy() from exc
            raise

    def commit(self) -> None:
        if self._connection is None:
            raise RuntimeError("UnitOfWork has not been entered")
        if self._committed:
            raise PersistenceFailure("UnitOfWork already committed")
        try:
            self._connection.execute("COMMIT")
            self._committed = True
        except BaseException as exc:
            self.rollback()
            if _is_busy_error(exc):
                raise PersistenceBusy("authoritative commit was busy") from exc
            raise PersistenceFailure("authoritative commit failed") from exc

    def rollback(self) -> None:
        if self._connection is None:
            return
        try:
            if bool(getattr(self._connection, "in_transaction", False)):
                self._connection.execute("ROLLBACK")
        except BaseException as exc:
            self._connection.close()
            self._connection = None
            raise PersistenceRollbackFailure("authoritative rollback failed") from exc

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> bool:
        pending: BaseException | None = exc
        try:
            if pending is None and not self._committed:
                self.commit()
            elif pending is not None:
                self.rollback()
            if self._connection is not None and bool(getattr(self._connection, "in_transaction", False)):
                self.rollback()
        finally:
            if self._connection is not None:
                self._connection.close()
                self._connection = None
            if self._token is not None:
                _active_uow.reset(self._token)
                self._token = None
        return False


class ReadSnapshot:
    """Bounded consistent read snapshot shared by projection providers."""

    def __init__(self, connection_factory: ConnectionFactory) -> None:
        self._factory = connection_factory
        self._connection: Any | None = None

    @property
    def connection(self) -> Any:
        if self._connection is None:
            raise RuntimeError("ReadSnapshot has not been entered")
        return self._connection

    def __enter__(self) -> Self:
        self._connection = self._factory.open_authoritative(read_only=True)
        self._connection.execute("BEGIN")
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> bool:
        try:
            if self._connection is not None and bool(getattr(self._connection, "in_transaction", False)):
                self._connection.execute("COMMIT" if exc is None else "ROLLBACK")
        finally:
            if self._connection is not None:
                self._connection.close()
                self._connection = None
        return False
