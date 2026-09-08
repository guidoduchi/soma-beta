from __future__ import annotations

import os
import sqlite3
import uuid
from collections.abc import Callable, Iterator
from pathlib import Path
from typing import Any

from soma.foundation.errors import MigrationError
from soma.foundation.identifiers import utc_epoch_seconds
from soma.foundation.persistence.connections import ConnectionFactory

from .manifest import MigrationEntry, MigrationManifest
from .verification import verify_foundation_schema

ConnectionFactoryBuilder = Callable[[Path], ConnectionFactory]
VerificationCallback = Callable[[Any], None]


def _contains_sql_token(statement: str) -> bool:
    """Return True when text contains SQL outside comments/whitespace.

    This is used only to skip comment-only chunks after sqlite3.complete_statement()
    has identified a legal SQLite boundary.
    """

    i = 0
    state = "plain"
    while i < len(statement):
        ch = statement[i]
        nxt = statement[i + 1] if i + 1 < len(statement) else ""
        if state == "line_comment":
            if ch == "\n":
                state = "plain"
            i += 1
            continue
        if state == "block_comment":
            if ch == "*" and nxt == "/":
                state = "plain"
                i += 2
            else:
                i += 1
            continue
        if state == "single_quote":
            if ch == "'":
                if nxt == "'":
                    i += 2
                    continue
                state = "plain"
            i += 1
            continue
        if state == "double_quote":
            if ch == '"':
                if nxt == '"':
                    i += 2
                    continue
                state = "plain"
            i += 1
            continue
        if ch == "-" and nxt == "-":
            state = "line_comment"
            i += 2
            continue
        if ch == "/" and nxt == "*":
            state = "block_comment"
            i += 2
            continue
        if ch == "'":
            state = "single_quote"
            i += 1
            continue
        if ch == '"':
            state = "double_quote"
            i += 1
            continue
        if not ch.isspace() and ch != ";":
            return True
        i += 1
    return False


def iter_migration_statements(text: str) -> Iterator[str]:
    buffer = ""
    for line in text.splitlines(keepends=True):
        buffer += line
        if sqlite3.complete_statement(buffer):
            candidate = buffer.strip()
            if candidate and _contains_sql_token(candidate):
                yield candidate
            buffer = ""
    if buffer.strip() and _contains_sql_token(buffer):
        raise MigrationError("MIGRATION_SYNTAX_INCOMPLETE", "migration contains an incomplete SQL tail")


class MigrationRunner:
    def __init__(
        self,
        *,
        canonical_database_path: Path,
        manifest: MigrationManifest,
        factory_for_path: ConnectionFactoryBuilder,
        app_version: str,
        ownership_assertion: Callable[[], bool],
        verifier: VerificationCallback = verify_foundation_schema,
    ) -> None:
        self._canonical_path = Path(canonical_database_path)
        self._manifest = manifest
        self._factory_for_path = factory_for_path
        self._app_version = app_version
        self._ownership_assertion = ownership_assertion
        self._verifier = verifier

    def initialize_or_migrate(self) -> int:
        if not self._ownership_assertion():
            raise MigrationError("INSTANCE_OWNERSHIP_REQUIRED", "canonical data-instance ownership is not proven")
        if self._canonical_path.exists():
            return self._migrate_existing()
        return self._initialize_clean()

    def _ensure_runtime_wal(self, path: Path) -> None:
        factory = self._factory_for_path(path)
        connection = factory.open_authoritative(read_only=False, require_wal=False)
        try:
            factory.configure_startup_database(connection)
        finally:
            connection.close()

    def _migrate_existing(self) -> int:
        self._ensure_runtime_wal(self._canonical_path)
        applied = self._read_ledger(self._canonical_path)
        pending = self._reconcile_ledger(applied)
        for entry in pending:
            self._apply_entry(self._canonical_path, entry, require_wal=True)
        connection = self._factory_for_path(self._canonical_path).open_authoritative(read_only=False, require_wal=True)
        try:
            self._verifier(connection)
        finally:
            connection.close()
        return len(self._manifest.entries)

    def _initialize_clean(self) -> int:
        parent = self._canonical_path.parent
        if not parent.exists() or not parent.is_dir():
            raise MigrationError("INSTANCE_LAYOUT_INVALID", "canonical data directory must already exist")
        temp_path = parent / f".{self._canonical_path.name}.init-{uuid.uuid4()}.tmp"
        sidecars = [Path(str(temp_path) + suffix) for suffix in ("-journal", "-wal", "-shm")]
        try:
            # Create/key the unpublished database and explicitly hold DELETE mode.
            factory = self._factory_for_path(temp_path)
            connection = factory.open_authoritative(read_only=False, require_wal=False)
            try:
                mode = str(connection.execute("PRAGMA journal_mode=DELETE").fetchone()[0]).lower()
                if mode != "delete":
                    raise MigrationError("MIGRATION_INITIALIZATION_UNSAFE", f"temporary initialization journal mode is {mode!r}")
                connection.execute("PRAGMA synchronous=FULL")
            finally:
                connection.close()

            for entry in self._manifest.entries:
                self._apply_entry(temp_path, entry, require_wal=False)

            connection = self._factory_for_path(temp_path).open_authoritative(read_only=False, require_wal=False)
            try:
                self._verifier(connection)
            finally:
                connection.close()

            for sidecar in sidecars:
                if sidecar.exists():
                    sidecar.unlink()
            os.replace(temp_path, self._canonical_path)
            self._ensure_runtime_wal(self._canonical_path)
            return len(self._manifest.entries)
        except BaseException:
            for candidate in [temp_path, *sidecars]:
                try:
                    candidate.unlink(missing_ok=True)
                except OSError:
                    pass
            raise

    def _apply_entry(self, path: Path, entry: MigrationEntry, *, require_wal: bool) -> None:
        connection = self._factory_for_path(path).open_authoritative(read_only=False, require_wal=require_wal)
        try:
            connection.execute("BEGIN IMMEDIATE")
            for statement in iter_migration_statements(self._manifest.text(entry)):
                connection.execute(statement)
            connection.execute(
                "INSERT INTO schema_migrations(sequence, migration_id, sha256, applied_at_utc, app_version) "
                "VALUES (?, ?, ?, ?, ?)",
                (entry.sequence, entry.migration_id, entry.sha256, utc_epoch_seconds(), self._app_version),
            )
            connection.execute("COMMIT")
        except BaseException:
            try:
                if bool(getattr(connection, "in_transaction", False)):
                    connection.execute("ROLLBACK")
            finally:
                connection.close()
            raise
        else:
            connection.close()

    def _read_ledger(self, path: Path) -> list[tuple[int, str, str]]:
        connection = self._factory_for_path(path).open_authoritative(read_only=True, require_wal=True)
        try:
            try:
                rows = connection.execute(
                    "SELECT sequence, migration_id, sha256 FROM schema_migrations ORDER BY sequence"
                ).fetchall()
            except BaseException as exc:
                raise MigrationError("INVALID_DATABASE", "schema_migrations ledger is unavailable") from exc
            return [(int(row[0]), str(row[1]), str(row[2])) for row in rows]
        finally:
            connection.close()

    def _reconcile_ledger(self, applied: list[tuple[int, str, str]]) -> tuple[MigrationEntry, ...]:
        if len(applied) > len(self._manifest.entries):
            raise MigrationError("UNSUPPORTED_FUTURE_VERSION", "database migration ledger is ahead of this package")
        for offset, (sequence, migration_id, digest) in enumerate(applied):
            expected = self._manifest.entries[offset]
            if sequence != expected.sequence:
                raise MigrationError("LEDGER_MISMATCH", "database migration sequence contains a gap or reorder")
            if migration_id != expected.migration_id or digest != expected.sha256:
                raise MigrationError("LEDGER_MISMATCH", f"database migration ledger disagrees at sequence {sequence}")
        return self._manifest.entries[len(applied):]
