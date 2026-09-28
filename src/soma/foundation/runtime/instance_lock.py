from __future__ import annotations

import os
from pathlib import Path
from threading import Lock
from typing import BinaryIO

_PROCESS_LOCK = Lock()
_PROCESS_HELD_PATHS: set[Path] = set()
_PROCESS_HELD_FILES: set[tuple[int, int]] = set()
_PROCESS_DEFERRED_HANDLES: dict[tuple[int, int], list[BinaryIO]] = {}

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
            # Keep the established byte-range protocol. In particular, do not
            # switch to flock: on Linux flock and fcntl/lockf are independent
            # namespaces, which would permit an older SOMA process using lockf
            # to coexist with a newer process using flock.
            fcntl.lockf(
                handle.fileno(),
                fcntl.LOCK_EX | fcntl.LOCK_NB,
                1,
                0,
                os.SEEK_SET,
            )
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

    @staticmethod
    def _identity(handle: BinaryIO) -> tuple[int, int]:
        stat = os.fstat(handle.fileno())
        return int(stat.st_dev), int(stat.st_ino)

    @staticmethod
    def _path_identity(path: Path) -> tuple[int, int]:
        stat = path.stat()
        return int(stat.st_dev), int(stat.st_ino)

    @classmethod
    def acquire(cls, path: Path, *, create: bool = True) -> "DataInstanceLock":
        target = Path(path).resolve(strict=False)
        if not target.is_absolute():
            raise ValidationError("instance lock path must be absolute")

        # POSIX record locks are process-scoped: closing another descriptor for
        # the same file can release this process's lock. Therefore ownership
        # lookup, alias detection, opening, OS locking and registration are one
        # serialized operation, and known hard-link aliases are rejected before
        # a second descriptor is opened.
        with _PROCESS_LOCK:
            if target in _PROCESS_HELD_PATHS:
                raise SomaError(
                    "INSTANCE_OWNED",
                    "this process already owns the canonical data instance",
                )
            if not target.parent.exists() or not target.parent.is_dir():
                raise ValidationError("instance lock parent directory is unavailable")

            if create and not target.exists():
                try:
                    with target.open("xb") as created:
                        created.write(b"\0")
                        created.flush()
                        os.fsync(created.fileno())
                except FileExistsError:
                    pass

            try:
                path_identity = cls._path_identity(target)
                path_size = target.stat().st_size
            except FileNotFoundError as exc:
                raise ValidationError("instance lock file does not exist") from exc
            except OSError as exc:
                raise ValidationError("instance lock file cannot be inspected") from exc

            if path_identity in _PROCESS_HELD_FILES:
                raise SomaError(
                    "INSTANCE_OWNED",
                    "this process already owns the canonical data instance",
                )
            if path_size == 0 and not create:
                raise ValidationError("existing instance lock file has no lock byte")

            try:
                handle = target.open("r+b")
            except FileNotFoundError as exc:
                raise ValidationError("instance lock file does not exist") from exc
            except OSError as exc:
                raise ValidationError("instance lock file cannot be opened") from exc

            deferred_close = False
            try:
                file_identity = cls._identity(handle)
                if file_identity != path_identity:
                    # If an external actor swapped the path to a hard-link alias
                    # of an already-held file between stat() and open(), closing
                    # this descriptor immediately could release our POSIX lock.
                    # Defer that close until the real owner explicitly unlocks.
                    if file_identity in _PROCESS_HELD_FILES:
                        _PROCESS_DEFERRED_HANDLES.setdefault(
                            file_identity,
                            [],
                        ).append(handle)
                        deferred_close = True
                        raise SomaError(
                            "INSTANCE_OWNED",
                            "canonical data-instance lock path changed to an owned file",
                        )
                    raise ValidationError(
                        "instance lock file identity changed during acquisition"
                    )

                if os.fstat(handle.fileno()).st_size == 0:
                    handle.write(b"\0")
                    handle.flush()
                    os.fsync(handle.fileno())

                cls._lock_byte(handle)
                _PROCESS_HELD_PATHS.add(target)
                _PROCESS_HELD_FILES.add(file_identity)
                return cls(target, handle, file_identity)
            except BaseException:
                if not deferred_close:
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
            deferred = _PROCESS_DEFERRED_HANDLES.pop(self._file_identity, [])
            try:
                if self._locked:
                    self._unlock_byte(handle)
            finally:
                _PROCESS_HELD_PATHS.discard(self.path)
                _PROCESS_HELD_FILES.discard(self._file_identity)
                self._locked = False
                try:
                    handle.close()
                finally:
                    for deferred_handle in deferred:
                        deferred_handle.close()

    def __enter__(self) -> "DataInstanceLock":
        self.assert_held()
        return self

    def __exit__(self, exc_type, exc, tb) -> bool:
        self.release()
        return False
