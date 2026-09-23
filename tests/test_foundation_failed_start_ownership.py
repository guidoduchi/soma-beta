from __future__ import annotations

import threading

import pytest

from soma.foundation.errors import SomaError
from soma.foundation.persistence.uow import UnitOfWork
from soma.foundation.runtime.instance_lock import DataInstanceLock

from test_foundation_runtime_host import _Server, _runtime
from test_foundation_runtime_instance_lock import _child_lock_attempt


@pytest.mark.parametrize(
    ("executor_name", "use_uow"),
    [
        ("request_executor", True),
        ("request_executor", False),
        ("background_executor", True),
        ("background_executor", False),
    ],
)
def test_failed_start_retains_owner_until_running_workers_terminate(
    tmp_path, migration_directory, security_provider, executor_name, use_uow
) -> None:
    entered = threading.Event()
    finish = threading.Event()
    holder = {}

    def worker():
        if use_uow:
            with UnitOfWork(holder["runtime"].connection_factory) as uow:
                uow.connection.execute("SELECT 1").fetchone()
                entered.set()
                assert finish.wait(10)
        else:
            entered.set()
            assert finish.wait(10)

    class Server(_Server):
        def start(self, sock):
            super().start(sock)
            holder["future"] = getattr(holder["runtime"], executor_name).submit(worker)
            assert entered.wait(3)

    runtime, paths, _, security, _ = _runtime(
        tmp_path, migration_directory, security_provider,
        server=Server(self_health=False),
    )
    holder["runtime"] = runtime
    replacement = None
    try:
        with pytest.raises(SomaError) as primary:
            runtime.start()
        assert primary.value.code == "SECURITY_NOT_READY"
        assert any(
            "failed-start cleanup also failed" in note
            for note in getattr(primary.value, "__notes__", ())
        )
        assert runtime.state == "FAILED"
        assert runtime._write_gate.active == int(use_uow)
        assert not holder["future"].done()
        assert getattr(runtime, "_" + executor_name) is not None
        assert runtime._lock is not None and runtime._lock.held
        assert paths.registry.exists()
        assert security.closed == []

        with pytest.raises(SomaError) as same_process:
            DataInstanceLock.acquire(paths.lock, create=False)
        assert same_process.value.code == "INSTANCE_OWNED"
        contender = _child_lock_attempt(paths.lock)
        assert contender.returncode == 3
        assert contender.stdout.strip() == "INSTANCE_OWNED"
        replacement, *_ = _runtime(tmp_path, migration_directory, security_provider)
        with pytest.raises(SomaError) as other_host:
            replacement.start()
        assert other_host.value.code == "INSTANCE_OWNED"

        with pytest.raises(SomaError) as short_retry:
            runtime.retry_failed_cleanup(grace_seconds=0)
        assert short_retry.value.code == "INTERNAL_ERROR"
        assert runtime._lock is not None and runtime._lock.held
        assert security.closed == []
    finally:
        finish.set()
        if "future" in holder:
            holder["future"].result(timeout=3)
        if runtime.state == "FAILED" and runtime._has_runtime_resources():
            assert runtime.retry_failed_cleanup(grace_seconds=3)

    assert runtime.state == "FAILED"
    assert runtime._lock is None
    assert runtime._write_gate.active == 0
    assert not paths.registry.exists()
    assert len(security.closed) == 1
    assert replacement is not None
    replacement.start()
    replacement.shutdown(grace_seconds=2)
    contender = _child_lock_attempt(paths.lock)
    assert contender.returncode == 0
    assert contender.stdout.strip() == "ACQUIRED"


def test_failed_start_preserves_worker_rollback_before_restart(
    tmp_path, migration_directory, security_provider
) -> None:
    entered = threading.Event()
    finish = threading.Event()
    holder = {}

    def worker():
        with UnitOfWork(holder["runtime"].connection_factory) as uow:
            uow.connection.execute(
                "CREATE TABLE injected_failed_start_uncommitted(id INTEGER)"
            )
            entered.set()
            assert finish.wait(10)
            raise RuntimeError("injected worker rollback")

    class Server(_Server):
        def start(self, sock):
            super().start(sock)
            holder["future"] = holder["runtime"].background_executor.submit(worker)
            assert entered.wait(3)

    runtime, paths, _, security, _ = _runtime(
        tmp_path, migration_directory, security_provider,
        server=Server(self_health=False),
    )
    holder["runtime"] = runtime
    try:
        with pytest.raises(SomaError) as primary:
            runtime.start()
        assert primary.value.code == "SECURITY_NOT_READY"
        assert runtime._write_gate.active == 1
        assert runtime._lock is not None and runtime._lock.held
        assert security.closed == []
        assert paths.registry.exists()
    finally:
        finish.set()
        if "future" in holder:
            with pytest.raises(RuntimeError, match="injected worker rollback"):
                holder["future"].result(timeout=3)
        if runtime.state == "FAILED" and runtime._has_runtime_resources():
            assert runtime.retry_failed_cleanup(grace_seconds=3)

    connection = runtime.connection_factory.open_authoritative(read_only=True)
    try:
        assert connection.execute(
            "SELECT name FROM sqlite_master "
            "WHERE name='injected_failed_start_uncommitted'"
        ).fetchone() is None
    finally:
        connection.close()
    replacement, *_ = _runtime(tmp_path, migration_directory, security_provider)
    replacement.start()
    replacement.shutdown(grace_seconds=2)


def test_partial_server_start_with_non_uow_worker_preserves_instance_lock(
    tmp_path, migration_directory, security_provider
) -> None:
    entered = threading.Event()
    finish = threading.Event()
    holder = {}

    def worker():
        entered.set()
        assert finish.wait(10)

    class Server(_Server):
        def start(self, sock):
            super().start(sock)
            holder["future"] = holder["runtime"].request_executor.submit(worker)
            assert entered.wait(3)
            raise RuntimeError("injected partial server startup")

    runtime, paths, _, security, _ = _runtime(
        tmp_path, migration_directory, security_provider, server=Server()
    )
    holder["runtime"] = runtime
    try:
        with pytest.raises(RuntimeError, match="injected partial server startup"):
            runtime.start()
        assert runtime.state == "FAILED"
        assert runtime._write_gate.active == 0
        assert runtime._request_executor is not None
        assert runtime._lock is not None and runtime._lock.held
        assert security.closed == []
        assert not paths.registry.exists()
        with pytest.raises(SomaError) as blocked:
            DataInstanceLock.acquire(paths.lock, create=False)
        assert blocked.value.code == "INSTANCE_OWNED"
    finally:
        finish.set()
        if "future" in holder:
            holder["future"].result(timeout=3)
        if runtime.state == "FAILED" and runtime._has_runtime_resources():
            assert runtime.retry_failed_cleanup(grace_seconds=3)
    assert runtime._lock is None
    assert len(security.closed) == 1
    replacement, *_ = _runtime(tmp_path, migration_directory, security_provider)
    replacement.start()
    replacement.shutdown(grace_seconds=2)


def test_start_rejects_uow_in_prelock_window(
    tmp_path, migration_directory, security_provider, monkeypatch
) -> None:
    reached = threading.Event()
    proceed = threading.Event()
    runtime, _, _, _, _ = _runtime(
        tmp_path, migration_directory, security_provider
    )
    original = DataInstanceLock.acquire

    def paused_acquire(cls, path, *, create=True):
        reached.set()
        assert proceed.wait(5)
        return original(path, create=create)

    monkeypatch.setattr(DataInstanceLock, "acquire", classmethod(paused_acquire))
    outcome = []

    def start_host():
        try:
            outcome.append(runtime.start())
        except BaseException as exc:
            outcome.append(exc)

    thread = threading.Thread(target=start_host, daemon=True)
    try:
        thread.start()
        assert reached.wait(3)
        with pytest.raises(SomaError) as blocked:
            with UnitOfWork(runtime.connection_factory):
                pass
        assert blocked.value.code == "HOST_QUIESCING"
    finally:
        proceed.set()
        thread.join(timeout=10)

    assert not thread.is_alive()
    assert len(outcome) == 1
    assert not isinstance(outcome[0], BaseException), repr(outcome[0])
    assert runtime.state == "READY"
    runtime.shutdown(grace_seconds=2)
