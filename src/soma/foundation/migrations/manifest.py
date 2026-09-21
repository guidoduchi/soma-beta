from __future__ import annotations

import hashlib
import re
import unicodedata
from dataclasses import dataclass
from pathlib import Path

from soma.foundation.errors import MigrationError
from soma.foundation.strict_json import loads_strict_bytes

_MIGRATION_FILENAME = re.compile(r"^(?P<seq>\d{4})_(?P<slug>[a-z0-9_]+)\.sql$")


@dataclass(frozen=True, slots=True)
class MigrationEntry:
    sequence: int
    migration_id: str
    filename: str
    sha256: str

    @property
    def path_sequence(self) -> int:
        match = _MIGRATION_FILENAME.fullmatch(self.filename)
        if not match:
            raise MigrationError("MIGRATION_MANIFEST_INVALID", f"invalid migration filename: {self.filename}")
        return int(match.group("seq"))


@dataclass(frozen=True, slots=True)
class MigrationManifest:
    directory: Path
    entries: tuple[MigrationEntry, ...]

    @classmethod
    def load(cls, directory: Path) -> "MigrationManifest":
        directory = Path(directory)
        manifest_path = directory / "manifest.json"
        try:
            raw_manifest = manifest_path.read_bytes()
        except OSError as exc:
            raise MigrationError("MIGRATION_MANIFEST_MISSING", "migration manifest is unavailable") from exc
        parsed = loads_strict_bytes(raw_manifest, max_bytes=1_048_576)
        if not isinstance(parsed, dict) or set(parsed) != {"schema", "migrations"}:
            raise MigrationError("MIGRATION_MANIFEST_INVALID", "manifest top-level shape is invalid")
        if parsed["schema"] != "SOMA-MIGRATION-MANIFEST-V1" or not isinstance(parsed["migrations"], list):
            raise MigrationError("MIGRATION_MANIFEST_INVALID", "manifest schema/version is invalid")

        entries: list[MigrationEntry] = []
        for index, item in enumerate(parsed["migrations"], start=1):
            if not isinstance(item, dict) or set(item) != {"sequence", "migration_id", "filename", "sha256"}:
                raise MigrationError("MIGRATION_MANIFEST_INVALID", f"manifest entry {index} has invalid fields")
            if type(item["sequence"]) is not int or item["sequence"] <= 0:
                raise MigrationError("MIGRATION_MANIFEST_INVALID", f"manifest entry {index} sequence is invalid")
            for field in ("migration_id", "filename", "sha256"):
                if not isinstance(item[field], str) or not item[field]:
                    raise MigrationError("MIGRATION_MANIFEST_INVALID", f"manifest entry {index} {field} is invalid")
            entries.append(MigrationEntry(**item))

        manifest = cls(directory=directory, entries=tuple(entries))
        manifest.validate()
        return manifest

    def validate(self) -> None:
        seen_ids: set[str] = set()
        seen_files: set[str] = set()
        for expected_sequence, entry in enumerate(self.entries, start=1):
            if entry.sequence != expected_sequence or entry.path_sequence != expected_sequence:
                raise MigrationError("MIGRATION_MANIFEST_INVALID", "migration sequence must start at 1 and be contiguous")
            if entry.migration_id in seen_ids or entry.filename in seen_files:
                raise MigrationError("MIGRATION_MANIFEST_INVALID", "migration IDs and filenames must be unique")
            seen_ids.add(entry.migration_id)
            seen_files.add(entry.filename)
            self.raw_bytes(entry)

        on_disk = {
            path.name
            for path in self.directory.iterdir()
            if path.is_file() and _MIGRATION_FILENAME.fullmatch(path.name)
        }
        if on_disk != seen_files:
            raise MigrationError(
                "MIGRATION_MANIFEST_INVALID",
                f"listed migration files differ from directory: listed={sorted(seen_files)!r} on_disk={sorted(on_disk)!r}",
            )

    def raw_bytes(self, entry: MigrationEntry) -> bytes:
        raw = self._validated_raw_bytes(entry)
        if hashlib.sha256(raw).hexdigest() != entry.sha256:
            raise MigrationError("MIGRATION_HASH_MISMATCH", "migration bytes disagree with the accepted manifest")
        return raw

    def text(self, entry: MigrationEntry) -> str:
        return self.raw_bytes(entry).decode("utf-8", errors="strict")

    def _validated_raw_bytes(self, entry: MigrationEntry) -> bytes:
        path = self.directory / entry.filename
        try:
            raw = path.read_bytes()
        except OSError as exc:
            raise MigrationError("MIGRATION_FILE_MISSING", f"migration file is unavailable: {entry.filename}") from exc
        if raw.startswith(b"\xef\xbb\xbf"):
            raise MigrationError("MIGRATION_BYTES_INVALID", f"UTF-8 BOM is forbidden: {entry.filename}")
        if b"\r" in raw:
            raise MigrationError("MIGRATION_BYTES_INVALID", f"CR/CRLF bytes are forbidden: {entry.filename}")
        if not raw.endswith(b"\n") or raw.endswith(b"\n\n"):
            raise MigrationError("MIGRATION_BYTES_INVALID", f"exactly one final LF is required: {entry.filename}")
        try:
            text = raw.decode("utf-8", errors="strict")
        except UnicodeDecodeError as exc:
            raise MigrationError("MIGRATION_BYTES_INVALID", f"migration is not strict UTF-8: {entry.filename}") from exc
        if unicodedata.normalize("NFC", text) != text:
            raise MigrationError("MIGRATION_BYTES_INVALID", f"migration text is not NFC: {entry.filename}")
        return raw
