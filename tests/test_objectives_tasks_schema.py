from __future__ import annotations

import hashlib
import json
import sqlite3
from pathlib import Path
from typing import Any

import pytest

from soma.foundation.migrations.manifest import MigrationManifest
from soma.foundation.migrations.runner import MigrationRunner
from soma.foundation.persistence.connections import ConnectionFactory
from soma.foundation.persistence.uow import ReadSnapshot


_MIGRATION_6_SHA256 = "af73f2551a5022e91a5b37f9cdb4b41e6ac79a85dde9c99480b1eff506cd361d"
_TABLES = {
    "objectives",
    "objective_history",
    "tasks",
    "task_history",
    "task_dependencies",
    "task_dependency_history",
    "task_sr_links",
    "task_sr_link_history",
    "task_rfc_links",
    "task_rfc_link_history",
    "task_spare_links",
    "task_spare_link_history",
    "objective_task_links",
    "objective_task_link_history",
    "task_source_projection",
    "task_source_projection_history",
    "task_source_observations",
    "task_source_observation_fields",
    "task_source_activity_attempts",
    "task_source_activity_attempt_history",
    "task_activity_review_events",
    "task_activity_review_heads",
    "task_execution_events",
    "task_execution_current",
    "task_plan_history",
    "task_plan_current",
    "objective_schedule_history",
    "objective_schedule_current",
    "objective_tracking_allocator",
    "objective_execution_events",
    "objective_execution_current",
    "objective_review_events",
    "objective_review_current",
    "task_review_events",
    "task_review_current",
    "objective_rfc_context",
    "objective_rfc_context_history",
}
_REQUIRED_QUERY_INDEXES = {
    "idx_objectives_window",
    "idx_tasks_objective",
    "idx_tasks_status",
    "idx_task_dependencies_predecessor",
    "idx_task_sr_links_sr",
    "idx_task_rfc_links_rfc",
    "idx_task_spare_links_spare",
    "idx_task_source_projection_task",
    "idx_task_source_observations_task",
    "idx_task_source_activity_attempts_task",
    "idx_task_activity_review_heads_task",
    "idx_task_execution_current_task",
    "idx_task_plan_current_task",
    "idx_objective_schedule_current_objective",
    "idx_objective_execution_current_objective",
    "idx_objective_review_current_objective",
    "idx_task_review_current_task",
    "idx_objective_rfc_context_rfc",
}


def _factory(initialized_database) -> ConnectionFactory:
    path, builder = initialized_database
    return builder(path)


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


def _leading_index_columns(connection: Any, table: str) -> set[str]:
    columns: set[str] = set()
    for index in connection.execute(f"PRAGMA index_list('{table}')").fetchall():
        name = str(index[1])
        info = connection.execute(f"PRAGMA index_info('{name}')").fetchall()
        if info:
            columns.add(str(info[0][2]))
    return columns


def test_objectives_tasks_schema_is_complete_strict_indexed_and_fk_clean(initialized_database) -> None:
    factory = _factory(initialized_database)
    assert len(_TABLES) == 37
    with ReadSnapshot(factory) as snapshot:
        rows = snapshot.connection.execute(
            "SELECT name FROM sqlite_schema WHERE type='table' AND name IN ("
            + ",".join("?" for _ in _TABLES)
            + ")",
            tuple(sorted(_TABLES)),
        ).fetchall()
        assert {str(row[0]) for row in rows} == _TABLES

        strict = {
            str(row[1]): int(row[5])
            for row in snapshot.connection.execute("PRAGMA table_list").fetchall()
            if len(row) >= 6
        }
        assert all(strict.get(table) == 1 for table in _TABLES)

        indexes = {
            str(row[0])
            for row in snapshot.connection.execute(
                "SELECT name FROM sqlite_schema WHERE type='index' AND name IS NOT NULL"
            ).fetchall()
        }
        assert _REQUIRED_QUERY_INDEXES <= indexes

        for table in sorted(_TABLES):
            leading = _leading_index_columns(snapshot.connection, table)
            for fk in snapshot.connection.execute(f"PRAGMA foreign_key_list('{table}')").fetchall():
                child_column = str(fk[3])
                assert child_column in leading, f"{table}.{child_column} lacks a leading-prefix FK index"

        assert snapshot.connection.execute("PRAGMA foreign_key_check").fetchall() == []
        assert snapshot.connection.execute(
            "SELECT next_sequence,revision,last_command_id FROM objective_tracking_allocator WHERE singleton_id=1"
        ).fetchone() == (1, 1, None)
        ledger = snapshot.connection.execute(
            "SELECT sequence,migration_id,sha256 FROM schema_migrations ORDER BY sequence"
        ).fetchall()
        assert len(ledger) >= 6
        assert [int(row[0]) for row in ledger[:6]] == list(range(1, 7))
        assert tuple(ledger[5]) == (6, "beta_0006_objectives_tasks", _MIGRATION_6_SHA256)


def test_sequence_six_upgrades_a_real_five_migration_prefix(
    tmp_path: Path,
    migration_directory: Path,
    security_provider,
) -> None:
    staged = tmp_path / "migrations"
    staged.mkdir()
    full_manifest = json.loads((migration_directory / "manifest.json").read_text(encoding="utf-8"))
    prefix = {"schema": full_manifest["schema"], "migrations": full_manifest["migrations"][:5]}
    for entry in prefix["migrations"]:
        source = migration_directory / entry["filename"]
        (staged / entry["filename"]).write_bytes(source.read_bytes())
    (staged / "manifest.json").write_text(
        json.dumps(prefix, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
        newline="\n",
    )

    database = tmp_path / "upgrade.db"
    assert _runner(database, staged, security_provider).initialize_or_migrate() == 5
    assert _runner(database, migration_directory, security_provider).initialize_or_migrate() >= 6
    connection = sqlite3.connect(database)
    try:
        ledger = connection.execute(
            "SELECT sequence,migration_id,sha256 FROM schema_migrations WHERE sequence<=6 ORDER BY sequence"
        ).fetchall()
        assert len(ledger) == 6
        assert tuple(ledger[5]) == (6, "beta_0006_objectives_tasks", _MIGRATION_6_SHA256)
        assert connection.execute("PRAGMA foreign_key_check").fetchall() == []
    finally:
        connection.close()


def test_sequence_six_migration_failure_rolls_back_as_one_transaction(
    tmp_path: Path,
    migration_directory: Path,
    security_provider,
) -> None:
    source = migration_directory / "0006_objectives_tasks.sql"
    broken = tmp_path / "broken"
    broken.mkdir()
    full_manifest = json.loads((migration_directory / "manifest.json").read_text(encoding="utf-8"))
    prefix = {"schema": full_manifest["schema"], "migrations": full_manifest["migrations"][:6]}
    for entry in prefix["migrations"]:
        data = (migration_directory / entry["filename"]).read_bytes()
        if entry["sequence"] == 6:
            data += b"\nINSERT INTO definitely_missing_object VALUES (1);\n"
            entry["sha256"] = hashlib.sha256(data).hexdigest()
        (broken / entry["filename"]).write_bytes(data)
    (broken / "manifest.json").write_text(
        json.dumps(prefix, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
        newline="\n",
    )
    baseline = tmp_path / "baseline"
    baseline.mkdir()
    baseline_manifest = {"schema": full_manifest["schema"], "migrations": full_manifest["migrations"][:5]}
    for entry in baseline_manifest["migrations"]:
        (baseline / entry["filename"]).write_bytes((migration_directory / entry["filename"]).read_bytes())
    (baseline / "manifest.json").write_text(
        json.dumps(baseline_manifest, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
        newline="\n",
    )

    database = tmp_path / "broken.db"
    assert _runner(database, baseline, security_provider).initialize_or_migrate() == 5
    with pytest.raises(sqlite3.OperationalError):
        _runner(database, broken, security_provider).initialize_or_migrate()
    connection = sqlite3.connect(database)
    try:
        assert connection.execute("SELECT MAX(sequence) FROM schema_migrations").fetchone()[0] == 5
        assert connection.execute(
            "SELECT 1 FROM sqlite_schema WHERE type='table' AND name='objectives'"
        ).fetchone() is None
        assert connection.execute("PRAGMA foreign_key_check").fetchall() == []
    finally:
        connection.close()
