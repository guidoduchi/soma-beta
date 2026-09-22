from __future__ import annotations

import os
from pathlib import Path
from typing import BinaryIO

from soma.foundation.errors import SomaError, ValidationError


class DataInstanceLock:
    """Held first-byte OS lock proving canonical data-instance ownership."""

    def __init__(self, path: Path, handle: BinaryIO) -> None:
        self.path = Path(path)
        self._handle: BinaryIO | None = handle
        self._locked = True

    @staticmethod
    def _lock_byte(handle: BinaryIO) -> None:
        handle.seek(0)
        if os.name == "nt":
            import msvcrt

            try:
                msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
            except OSError as exc:
                raise SomaError(
                    "INSTANCE_OWNED",
                    "another process owns the canonical data instance",
                ) from exc
            return

        import fcntl

        try:
            fcntl.lockf(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB, 1, 0, os.SEEK_SET)
        except OSError as exc:
            raise SomaError(
                "INSTANCE_OWNED",
                "another process owns the canonical data instance",
            ) from exc

    @staticmethod
    def _unlock_byte(handle: BinaryIO) -> None:
        handle.seek(0)
        if os.name == "nt":
            import msvcrt

            msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
            return

        import fcntl

        fcntl.lockf(handle.fileno(), fcntl.LOCK_UN, 1, 0, os.SEEK_SET)

    @classmethod
    def acquire(cls, path: Path, *, create: bool = True) -> "DataInstanceLock":
        target = Path(path)
        if not target.is_absolute():
            raise ValidationError("instance lock path must be absolute")
        if not target.parent.exists() or not target.parent.is_dir():
            raise ValidationError("instance lock parent directory is unavailable")
        mode = "r+b"
        if create and not target.exists():
            try:
                with target.open("xb") as created:
                    created.write(b"\0")
                    created.flush()
                    os.fsync(created.fileno())
            except FileExistsError:
                pass
        try:
            handle = target.open(mode)
        except FileNotFoundError as exc:
            raise ValidationError("instance lock file does not exist") from exc
        except OSError as exc:
            raise ValidationError("instance lock file cannot be opened") from exc

        try:
            if target.stat().st_size == 0:
                if not create:
                    raise ValidationError("existing instance lock file has no lock byte")
                handle.write(b"\0")
                handle.flush()
                os.fsync(handle.fileno())
            cls._lock_byte(handle)
            return cls(target, handle)
        except BaseException:
            handle.close()
            raise

    @property
    def held(self) -> bool:
        return self._locked and self._handle is not None

    def assert_held(self) -> None:
        if not self.held:
            raise SomaError("INSTANCE_OWNED", "canonical data-instance ownership is not held")

    def release(self) -> None:
        if self._handle is None:
            self._locked = False
            return
        handle = self._handle
        self._handle = None
        try:
            if self._locked:
                self._unlock_byte(handle)
        finally:
            self._locked = False
            handle.close()

    def __enter__(self) -> "DataInstanceLock":
        self.assert_held()
        return self

    def __exit__(self, exc_type, exc, tb) -> bool:
        self.release()
        return False
