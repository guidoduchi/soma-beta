from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Any

import pytest

from soma.foundation.migrations.manifest import MigrationManifest
from soma.foundation.migrations.runner import MigrationRunner
from soma.foundation.persistence.connections import ConnectionFactory


class TestSecurityProvider:
    """Test-only security seam; production never substitutes plaintext SQLite."""

    def acquire_live_dek_handle(self) -> object:
        return object()

    def key_connection(self, connection: Any, key_handle: object) -> None:
        return None

    def verify_cipher_connection(self, connection: Any) -> None:
        connection.execute("SELECT count(*) FROM sqlite_master").fetchone()


@pytest.fixture
def security_provider() -> TestSecurityProvider:
    return TestSecurityProvider()


@pytest.fixture
def migration_directory() -> Path:
    return Path(__file__).resolve().parents[1] / "src" / "soma" / "migrations"


@pytest.fixture
def initialized_database(tmp_path: Path, migration_directory: Path, security_provider: TestSecurityProvider) -> tuple[Path, callable]:
    database_path = tmp_path / "soma.db"

    def factory_for_path(path: Path) -> ConnectionFactory:
        return ConnectionFactory(path, security_provider, driver=sqlite3)

    runner = MigrationRunner(
        canonical_database_path=database_path,
        manifest=MigrationManifest.load(migration_directory),
        factory_for_path=factory_for_path,
        app_version="test",
        ownership_assertion=lambda: True,
    )
    runner.initialize_or_migrate()
    return database_path, factory_for_path
