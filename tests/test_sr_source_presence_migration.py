from __future__ import annotations

import hashlib
import json
import shutil
import sqlite3
from pathlib import Path

import pytest

from soma.foundation.migrations.manifest import MigrationManifest
from soma.foundation.migrations.runner import MigrationRunner
from soma.foundation.persistence.connections import ConnectionFactory


_PREFIX_HASHES = {
    "0001_foundation.sql": "55fb2128a91fdb9e6851b43f88dd807a6f8050b78fe4f37d50069889b0c512b2",
    "0002_identity_reference.sql": "8fc0216adf7602b208e456f8c8996dcba1a65d1db8cac89c9a19afe308797e41",
    "0003_tickets_core.sql": "2ea24d491daa3ce564e8ee9f92d9e5a4d522c1941758d9646c505aeaaa875e56",
    "0004_ticket_import.sql": "50c73b844cf2cfeb6e7273ca1d4886cfd6992653dec3d1c7ca03d98cced607dd",
    "0005_command_replay_results.sql": "2aa0b287431d72c47af0e89d5ad28b00e4f21667c40e407fea87390caf826ba7",
    "0006_objectives_tasks.sql": "af73f2551a5022e91a5b37f9cdb4b41e6ac79a85dde9c99480b1eff506cd361d",
}


def _factory_builder(security_provider):
    return lambda path: ConnectionFactory(path, security_provider, driver=sqlite3)


def _runner(path: Path, directory: Path, security_provider) -> MigrationRunner:
    return MigrationRunner(
        canonical_database_path=path,
        manifest=MigrationManifest.load(directory),
        factory_for_path=_factory_builder(security_provider),
        app_version="test",
        ownership_assertion=lambda: True,
    )


def _stage_prefix(source: Path, target: Path, count: int) -> None:
    target.mkdir()
    manifest = json.loads((source / "manifest.json").read_text(encoding="utf-8"))
    prefix = {"schema": manifest["schema"], "migrations": manifest["migrations"][:count]}
    for entry in prefix["migrations"]:
        shutil.copyfile(source / entry["filename"], target / entry["filename"])
    (target / "manifest.json").write_text(
        json.dumps(prefix, ensure_ascii=False, indent=2) + "\n", encoding="utf-8", newline="\n"
    )


def _schema(path: Path) -> list[tuple[str, str, str]]:
    connection = sqlite3.connect(path)
    try:
        return [
            (str(row[0]), str(row[1]), str(row[2]))
            for row in connection.execute(
                "SELECT type,name,sql FROM sqlite_master WHERE name NOT LIKE 'sqlite_%' ORDER BY type,name"
            ).fetchall()
        ]
    finally:
        connection.close()


def test_runtime_prefix_bytes_are_unchanged_and_sequence_seven_remains_exact(migration_directory) -> None:
    manifest = MigrationManifest.load(migration_directory)
    assert [entry.sequence for entry in manifest.entries[:7]] == list(range(1, 8))
    sequence_seven = manifest.entries[6]
    assert sequence_seven.migration_id == "beta_0007_sr_source_presence"
    assert sequence_seven.filename == "0007_sr_source_presence.sql"
    for filename, expected in _PREFIX_HASHES.items():
        assert hashlib.sha256((migration_directory / filename).read_bytes()).hexdigest() == expected


def test_exact_prefix_six_upgrade_matches_fresh_sequence_seven_schema(
    tmp_path, migration_directory, security_provider
) -> None:
    prefix = tmp_path / "prefix"
    release_seven = tmp_path / "release-seven"
    _stage_prefix(migration_directory, prefix, 6)
    _stage_prefix(migration_directory, release_seven, 7)
    upgraded = tmp_path / "upgraded.db"
    fresh = tmp_path / "fresh.db"
    assert _runner(upgraded, prefix, security_provider).initialize_or_migrate() == 6
    assert _runner(upgraded, release_seven, security_provider).initialize_or_migrate() == 7
    assert _runner(fresh, release_seven, security_provider).initialize_or_migrate() == 7
    assert _schema(upgraded) == _schema(fresh)
    connection = sqlite3.connect(upgraded)
    try:
        assert connection.execute("PRAGMA foreign_key_check").fetchall() == []
        assert connection.execute(
            "SELECT sequence,migration_id FROM schema_migrations ORDER BY sequence"
        ).fetchall()[-1] == (7, "beta_0007_sr_source_presence")
    finally:
        connection.close()


def test_failed_sequence_seven_upgrade_leaves_exact_prefix_six(
    tmp_path, migration_directory, security_provider
) -> None:
    prefix = tmp_path / "prefix"
    broken = tmp_path / "broken"
    _stage_prefix(migration_directory, prefix, 6)
    _stage_prefix(migration_directory, broken, 7)
    migration = broken / "0007_sr_source_presence.sql"
    migration.write_text(
        migration.read_text(encoding="utf-8") + "INSERT INTO table_that_does_not_exist VALUES (1);\n",
        encoding="utf-8",
        newline="\n",
    )
    manifest = json.loads((broken / "manifest.json").read_text(encoding="utf-8"))
    manifest["migrations"][-1]["sha256"] = hashlib.sha256(migration.read_bytes()).hexdigest()
    (broken / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8", newline="\n"
    )
    database = tmp_path / "failed-upgrade.db"
    _runner(database, prefix, security_provider).initialize_or_migrate()
    with pytest.raises(sqlite3.OperationalError):
        _runner(database, broken, security_provider).initialize_or_migrate()
    connection = sqlite3.connect(database)
    try:
        assert connection.execute("SELECT MAX(sequence) FROM schema_migrations").fetchone()[0] == 6
        assert connection.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name='sr_source_presence_events'"
        ).fetchone() is None
        assert connection.execute("PRAGMA foreign_key_check").fetchall() == []
    finally:
        connection.close()
