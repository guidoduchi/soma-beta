from __future__ import annotations

import stat
from dataclasses import dataclass
from pathlib import Path

from soma.foundation.errors import ValidationError


def _is_reparse_or_symlink(path: Path) -> bool:
    try:
        if path.is_symlink():
            return True
        attributes = getattr(path.stat(follow_symlinks=False), "st_file_attributes", 0)
    except OSError as exc:
        raise ValidationError("instance path cannot be inspected safely") from exc
    reparse = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0)
    return bool(reparse and attributes & reparse)


@dataclass(frozen=True, slots=True)
class InstancePaths:
    root: Path
    database: Path
    lock: Path
    registry: Path
    diagnostics: Path

    @classmethod
    def from_root(cls, root: Path) -> "InstancePaths":
        candidate = Path(root)
        if not candidate.is_absolute():
            raise ValidationError("instance root must be absolute")
        try:
            resolved = candidate.resolve(strict=True)
        except OSError as exc:
            raise ValidationError("instance root does not exist") from exc
        if not resolved.is_dir() or _is_reparse_or_symlink(candidate):
            raise ValidationError("instance root must be a real directory")
        paths = cls(
            root=resolved,
            database=resolved / "data" / "soma.db",
            lock=resolved / "data" / "soma.instance.lock",
            registry=resolved / "runtime" / "runtime.json",
            diagnostics=resolved / "diagnostics",
        )
        paths.assert_safe_layout()
        return paths

    def assert_safe_layout(self) -> None:
        for path in (self.database, self.lock, self.registry, self.diagnostics):
            try:
                path.relative_to(self.root)
            except ValueError as exc:
                raise ValidationError("instance path escapes canonical instance root") from exc

        for directory in (self.root / "data", self.root / "runtime", self.diagnostics):
            if directory.exists() and (
                not directory.is_dir() or _is_reparse_or_symlink(directory)
            ):
                raise ValidationError("instance layout contains redirected directory authority")
        for file_path in (self.database, self.lock, self.registry):
            if file_path.exists() and _is_reparse_or_symlink(file_path):
                raise ValidationError("instance layout contains redirected file authority")

    def prepare_for_start(self) -> None:
        self.assert_safe_layout()
        for directory in (self.root / "data", self.root / "runtime", self.diagnostics):
            if not directory.exists():
                directory.mkdir(mode=0o700)
            if not directory.is_dir() or _is_reparse_or_symlink(directory):
                raise ValidationError("instance runtime directory is unsafe")
        self.assert_safe_layout()
