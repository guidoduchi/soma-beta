from __future__ import annotations

import os
import subprocess
import sys
import threading
from pathlib import Path
from unittest.mock import patch

import pytest

from soma.foundation.errors import SomaError
from soma.foundation.runtime.instance_lock import DataInstanceLock


def _child_lock_attempt(path: Path) -> subprocess.CompletedProcess[str]:
    script = (
        "import sys\n"
        "from pathlib import Path\n"
        "from soma.foundation.errors import SomaError\n"
        "from soma.foundation.runtime.instance_lock import DataInstanceLock\n"
        "try:\n"
        "    lock = DataInstanceLock.acquire(Path(sys.argv[1]), create=False)\n"
        "except SomaError as exc:\n"
        "    print(exc.code)\n"
        "    raise SystemExit(3)\n"
        "else:\n"
        "    print('ACQUIRED')\n"
        "    lock.release()\n"
    )
    return subprocess.run(
        [sys.executable, "-c", script, str(path)],
        capture_output=True,
        text=True,
        timeout=10,
        check=False,
    )


def _raw_posix_lock_attempt(path: Path) -> subprocess.CompletedProcess[str]:
    script = (
        "import fcntl, os, sys\n"
        "handle = open(sys.argv[1], 'r+b')\n"
        "try:\n"
        "    fcntl.lockf(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB, 1, 0, os.SEEK_SET)\n"
        "except OSError:\n"
        "    print('INSTANCE_OWNED')\n"
        "    raise SystemExit(3)\n"
        "else:\n"
        "    print('ACQUIRED')\n"
        "    fcntl.lockf(handle.fileno(), fcntl.LOCK_UN, 1, 0, os.SEEK_SET)\n"
    )
    return subprocess.run(
        [sys.executable, "-c", script, str(path)],
        capture_output=True,
        text=True,
        timeout=10,
        check=False,
    )


def test_same_process_contender_cannot_drop_winning_os_lock(tmp_path) -> None:
    path = (tmp_path / "instance.lock").resolve()
    path.write_bytes(b"\0")
    original = DataInstanceLock._lock_byte
    first_locked = threading.Event()
    release_first = threading.Event()
    calls: list[int] = []
    held: list[DataInstanceLock] = []
    errors: list[str] = []

    def interleave(handle) -> None:
        original(handle)
        calls.append(handle.fileno())
        if len(calls) == 1:
            first_locked.set()
            assert release_first.wait(timeout=5)

    def acquire() -> None:
        try:
            held.append(DataInstanceLock.acquire(path, create=False))
        except SomaError as exc:
            errors.append(exc.code)

    with patch.object(
        DataInstanceLock,
        "_lock_byte",
        staticmethod(interleave),
    ):
        first = threading.Thread(target=acquire)
        second = threading.Thread(target=acquire)
        first.start()
        assert first_locked.wait(timeout=5)
        second.start()
        release_first.set()
        first.join(timeout=5)
        second.join(timeout=5)

    assert not first.is_alive()
    assert not second.is_alive()
    assert len(calls) == 1
    assert len(held) == 1
    assert errors == ["INSTANCE_OWNED"]
    assert held[0].held

    blocked = _child_lock_attempt(path)
    assert blocked.returncode == 3
    assert blocked.stdout.strip() == "INSTANCE_OWNED"

    if os.name != "nt":
        legacy_blocked = _raw_posix_lock_attempt(path)
        assert legacy_blocked.returncode == 3
        assert legacy_blocked.stdout.strip() == "INSTANCE_OWNED"

    held[0].release()

    reacquired = _child_lock_attempt(path)
    assert reacquired.returncode == 0
    assert reacquired.stdout.strip() == "ACQUIRED"

    if os.name != "nt":
        legacy_reacquired = _raw_posix_lock_attempt(path)
        assert legacy_reacquired.returncode == 0
        assert legacy_reacquired.stdout.strip() == "ACQUIRED"


def test_hard_link_alias_cannot_bypass_process_ownership(tmp_path) -> None:
    primary = (tmp_path / "instance.lock").resolve()
    alias = (tmp_path / "instance-alias.lock").resolve()
    primary.write_bytes(b"\0")
    try:
        os.link(primary, alias)
    except OSError as exc:
        pytest.skip(f"hard links unavailable on this test filesystem: {exc}")

    owner = DataInstanceLock.acquire(primary, create=False)
    try:
        with pytest.raises(SomaError) as raised:
            DataInstanceLock.acquire(alias, create=False)
        assert raised.value.code == "INSTANCE_OWNED"

        blocked = _child_lock_attempt(alias)
        assert blocked.returncode == 3
        assert blocked.stdout.strip() == "INSTANCE_OWNED"

        if os.name != "nt":
            legacy_blocked = _raw_posix_lock_attempt(alias)
            assert legacy_blocked.returncode == 3
            assert legacy_blocked.stdout.strip() == "INSTANCE_OWNED"
    finally:
        owner.release()

    alias_owner = DataInstanceLock.acquire(alias, create=False)
    alias_owner.release()
