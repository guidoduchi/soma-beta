from __future__ import annotations

import multiprocessing
import os
import socket
from pathlib import Path

import pytest

from soma.foundation.errors import SomaError, ValidationError
from soma.foundation.identifiers import new_uuid4
from soma.foundation.runtime import (
    BoundLoopbackSocket,
    DataInstanceLock,
    InstancePaths,
    RuntimeRegistry,
    RuntimeRegistryRecord,
)


def _hold_lock(path_text: str, ready, release) -> None:
    lock = DataInstanceLock.acquire(Path(path_text), create=False)
    try:
        ready.set()
        release.wait(15)
    finally:
        lock.release()


def test_instance_paths_prepare_only_expected_local_layout(tmp_path) -> None:
    root = tmp_path.resolve()
    paths = InstancePaths.from_root(root)
    paths.prepare_for_start()

    assert paths.database == root / "data" / "soma.db"
    assert paths.lock == root / "data" / "soma.instance.lock"
    assert paths.registry == root / "runtime" / "runtime.json"
    assert paths.diagnostics == root / "diagnostics"
    assert (root / "data").is_dir()
    assert (root / "runtime").is_dir()
    assert paths.diagnostics.is_dir()


def test_instance_root_must_be_absolute_and_existing(tmp_path) -> None:
    with pytest.raises(ValidationError):
        InstancePaths.from_root(Path("relative-instance"))
    with pytest.raises(ValidationError):
        InstancePaths.from_root(tmp_path / "missing")


def test_data_instance_lock_is_cross_process_exclusive(tmp_path) -> None:
    paths = InstancePaths.from_root(tmp_path.resolve())
    paths.prepare_for_start()
    first = DataInstanceLock.acquire(paths.lock)
    first.release()

    context = multiprocessing.get_context("spawn")
    ready = context.Event()
    release = context.Event()
    process = context.Process(
        target=_hold_lock,
        args=(str(paths.lock), ready, release),
    )
    process.start()
    try:
        assert ready.wait(10)
        with pytest.raises(SomaError) as raised:
            DataInstanceLock.acquire(paths.lock, create=False)
        assert raised.value.code == "INSTANCE_OWNED"
    finally:
        release.set()
        process.join(10)
        if process.is_alive():
            process.kill()
            process.join(5)
    assert process.exitcode == 0

    with DataInstanceLock.acquire(paths.lock, create=False) as acquired:
        assert acquired.held


def test_loopback_socket_is_prebound_only_to_ipv4_loopback() -> None:
    with BoundLoopbackSocket.bind() as bound:
        assert bound.host == "127.0.0.1"
        assert 1 <= bound.port <= 65535
        assert bound.socket.family == __import__("socket").AF_INET
        assert bound.socket.getsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR) == 0
        if hasattr(socket, "SO_EXCLUSIVEADDRUSE"):
            assert bound.socket.getsockopt(
                socket.SOL_SOCKET,
                socket.SO_EXCLUSIVEADDRUSE,
            ) == 1


def test_runtime_registry_is_atomic_exact_owned_and_contains_no_secret_fields(tmp_path) -> None:
    paths = InstancePaths.from_root(tmp_path.resolve())
    paths.prepare_for_start()
    run_id = new_uuid4()
    data_instance_id = new_uuid4()
    record = RuntimeRegistryRecord(
        registry_version=1,
        origin="SOMA",
        pid=os.getpid(),
        process_birth_id="test-process-birth",
        run_id=run_id,
        protocol_version="1",
        data_instance_id=data_instance_id,
        readiness_locator="http://127.0.0.1:12345",
    )

    RuntimeRegistry.publish(paths.registry, record)
    raw = paths.registry.read_text(encoding="utf-8")
    assert raw.endswith("\n")
    assert "password" not in raw.lower()
    assert "token" not in raw.lower()
    assert "key" not in raw.lower()
    assert RuntimeRegistry.read(paths.registry) == record

    assert RuntimeRegistry.remove_owned(
        paths.registry,
        run_id=new_uuid4(),
        data_instance_id=data_instance_id,
    ) is False
    assert paths.registry.exists()
    assert RuntimeRegistry.remove_owned(
        paths.registry,
        run_id=run_id,
        data_instance_id=data_instance_id,
    ) is True
    assert not paths.registry.exists()


@pytest.mark.parametrize(
    "locator",
    [
        "http://0.0.0.0:8080",
        "http://192.168.1.10:8080",
        "http://localhost:8080",
        "https://127.0.0.1:8080",
    ],
)
def test_runtime_registry_rejects_nonloopback_locator(tmp_path, locator) -> None:
    paths = InstancePaths.from_root(tmp_path.resolve())
    paths.prepare_for_start()
    with pytest.raises(ValidationError):
        RuntimeRegistry.publish(
            paths.registry,
            RuntimeRegistryRecord(
                registry_version=1,
                origin="SOMA",
                pid=os.getpid(),
                process_birth_id="birth",
                run_id=new_uuid4(),
                protocol_version="1",
                data_instance_id=new_uuid4(),
                readiness_locator=locator,
            ),
        )
