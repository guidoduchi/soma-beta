from __future__ import annotations

import os
from pathlib import Path
from threading import Lock
from typing import BinaryIO

_PROCESS_LOCK = Lock()
_PROCESS_HELD_PATHS: set[Path] = set()
_PROCESS_HELD_FILES: set[tuple[int, int]] = set()

from soma.foundation.errors import SomaError, ValidationError


class DataInstanceLock:
    """Held first-byte OS lock proving canonical data-instance ownership."""

    def __init__(
        self,
        path: Path,
        handle: BinaryIO,
        file_identity: tuple[int, int],
    ) -> None:
        self.path = Path(path).resolve(strict=False)
        self._handle: BinaryIO | None = handle
        self._file_identity = file_identity
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
            # flock locks are associated with this open file description. Unlike
            # POSIX process-scoped record locks, closing a competing descriptor
            # in this process cannot silently release another owner's lock.
            fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
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

        fcntl.flock(handle.fileno(), fcntl.LOCK_UN)

    @staticmethod
    def _identity(handle: BinaryIO) -> tuple[int, int]:
        stat = os.fstat(handle.fileno())
        return int(stat.st_dev), int(stat.st_ino)

    @classmethod
    def acquire(cls, path: Path, *, create: bool = True) -> "DataInstanceLock":
        target = Path(path).resolve(strict=False)
        if not target.is_absolute():
            raise ValidationError("instance lock path must be absolute")

        # Same-process ownership reservation, file opening, OS locking and
        # registration are one serialized operation. A losing contender never
        # gets a chance to undo the winner's ownership during rollback.
        with _PROCESS_LOCK:
            if target in _PROCESS_HELD_PATHS:
                raise SomaError(
                    "INSTANCE_OWNED",
                    "this process already owns the canonical data instance",
                )
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
                if os.fstat(handle.fileno()).st_size == 0:
                    if not create:
                        raise ValidationError(
                            "existing instance lock file has no lock byte"
                        )
                    handle.write(b"\0")
                    handle.flush()
                    os.fsync(handle.fileno())

                file_identity = cls._identity(handle)
                if file_identity in _PROCESS_HELD_FILES:
                    raise SomaError(
                        "INSTANCE_OWNED",
                        "this process already owns the canonical data instance",
                    )

                cls._lock_byte(handle)
                _PROCESS_HELD_PATHS.add(target)
                _PROCESS_HELD_FILES.add(file_identity)
                return cls(target, handle, file_identity)
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
        with _PROCESS_LOCK:
            handle = self._handle
            self._handle = None
            try:
                if self._locked:
                    self._unlock_byte(handle)
            finally:
                _PROCESS_HELD_PATHS.discard(self.path)
                _PROCESS_HELD_FILES.discard(self._file_identity)
                self._locked = False
                handle.close()

    def __enter__(self) -> "DataInstanceLock":
        self.assert_held()
        return self

    def __exit__(self, exc_type, exc, tb) -> bool:
        self.release()
        return False
