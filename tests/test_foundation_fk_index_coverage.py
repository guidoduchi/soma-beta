from __future__ import annotations

import json
import shutil
import sqlite3
from pathlib import Path

import pytest

from soma.foundation.errors import MigrationError
from soma.foundation.migrations.manifest import MigrationManifest
from soma.foundation.migrations.runner import MigrationRunner
from soma.foundation.migrations.verification import (
    verify_foreign_key_index_coverage,
    verify_foundation_schema,
)
from soma.foundation.persistence.connections import ConnectionFactory


def _connection() -> sqlite3.Connection:
    connection = sqlite3.connect(":memory:")
    connection.execute("PRAGMA foreign_keys=ON")
    return connection


def _assert_schema_mismatch(connection: sqlite3.Connection) -> None:
    with pytest.raises(MigrationError) as raised:
        verify_foreign_key_index_coverage(connection, exceptions=())
    assert raised.value.code == "MIGRATION_SCHEMA_MISMATCH"


def test_fk_index_coverage_accepts_full_leading_prefix_and_wider_index() -> None:
    connection = _connection()
    try:
        connection.execute(
            "CREATE TABLE parent(a TEXT,b TEXT,PRIMARY KEY(a,b))"
        )
        connection.execute(
            "CREATE TABLE child(x TEXT,y TEXT,other TEXT,"
            "FOREIGN KEY(x,y) REFERENCES parent(a,b))"
        )
        connection.execute("CREATE INDEX ix_child_fk ON child(x,y,other)")
        verify_foreign_key_index_coverage(connection, exceptions=())
    finally:
        connection.close()


def test_fk_index_coverage_accepts_sqlite_owned_primary_key_autoindex() -> None:
    connection = _connection()
    try:
        connection.execute("CREATE TABLE parent(id TEXT PRIMARY KEY)")
        connection.execute(
            "CREATE TABLE child(id TEXT PRIMARY KEY REFERENCES parent(id))"
        )
        verify_foreign_key_index_coverage(connection, exceptions=())
    finally:
        connection.close()


def test_fk_index_coverage_rejects_missing_or_dropped_index() -> None:
    connection = _connection()
    try:
        connection.execute("CREATE TABLE parent(id TEXT PRIMARY KEY)")
        connection.execute("CREATE TABLE child(parent_id TEXT REFERENCES parent(id))")
        _assert_schema_mismatch(connection)

        connection.execute("CREATE INDEX ix_child_parent ON child(parent_id)")
        verify_foreign_key_index_coverage(connection, exceptions=())
        connection.execute("DROP INDEX ix_child_parent")
        _assert_schema_mismatch(connection)
    finally:
        connection.close()


@pytest.mark.parametrize(
    "index_sql",
    [
        "CREATE INDEX ix_bad ON child(other,x,y)",
        "CREATE INDEX ix_bad ON child(y,x)",
        "CREATE INDEX ix_bad ON child(lower(x),y)",
    ],
)
def test_fk_index_coverage_rejects_wrong_leading_order_and_expression_keys(
    index_sql: str,
) -> None:
    connection = _connection()
    try:
        connection.execute(
            "CREATE TABLE parent(a TEXT,b TEXT,PRIMARY KEY(a,b))"
        )
        connection.execute(
            "CREATE TABLE child(x TEXT,y TEXT,other TEXT,"
            "FOREIGN KEY(x,y) REFERENCES parent(a,b))"
        )
        connection.execute(index_sql)
        _assert_schema_mismatch(connection)
    finally:
        connection.close()


def test_fk_index_coverage_rejects_structural_match_with_unusable_collation() -> None:
    connection = _connection()
    try:
        connection.execute(
            "CREATE TABLE parent(id TEXT COLLATE NOCASE PRIMARY KEY)"
        )
        connection.execute(
            "CREATE TABLE child(parent_id TEXT COLLATE NOCASE REFERENCES parent(id))"
        )
        connection.execute(
            "CREATE INDEX ix_child_parent_wrong_collation "
            "ON child(parent_id COLLATE BINARY)"
        )
        _assert_schema_mismatch(connection)

        connection.execute("DROP INDEX ix_child_parent_wrong_collation")
        connection.execute(
            "CREATE INDEX ix_child_parent_nocase "
            "ON child(parent_id COLLATE NOCASE)"
        )
        verify_foreign_key_index_coverage(connection, exceptions=())
    finally:
        connection.close()


def test_fk_index_coverage_accepts_closed_nullable_partial_shape() -> None:
    connection = _connection()
    try:
        connection.execute(
            "CREATE TABLE parent(a TEXT,b TEXT,PRIMARY KEY(a,b))"
        )
        connection.execute(
            "CREATE TABLE child(x TEXT,y TEXT,"
            "FOREIGN KEY(x,y) REFERENCES parent(a,b))"
        )
        connection.execute(
            "CREATE INDEX ix_child_nullable_fk ON child(x,y) "
            "WHERE x IS NOT NULL AND y IS NOT NULL"
        )
        verify_foreign_key_index_coverage(connection, exceptions=())
    finally:
        connection.close()


@pytest.mark.parametrize(
    "child_definition,index_sql",
    [
        (
            "x TEXT,state TEXT,FOREIGN KEY(x) REFERENCES parent(id)",
            "CREATE INDEX ix_bad ON child(x) WHERE state='active'",
        ),
        (
            "x TEXT,other TEXT,FOREIGN KEY(x) REFERENCES parent(id)",
            "CREATE INDEX ix_bad ON child(x) WHERE other IS NOT NULL",
        ),
        (
            "x TEXT,state TEXT,FOREIGN KEY(x) REFERENCES parent(id)",
            "CREATE INDEX ix_bad ON child(x) "
            "WHERE x IS NOT NULL AND state='active'",
        ),
        (
            "x TEXT,FOREIGN KEY(x) REFERENCES parent(id)",
            "CREATE INDEX ix_bad ON child(x) "
            "WHERE x IS NOT NULL OR x='special'",
        ),
        (
            "x TEXT NOT NULL,FOREIGN KEY(x) REFERENCES parent(id)",
            "CREATE INDEX ix_bad ON child(x) WHERE x IS NOT NULL",
        ),
    ],
)
def test_fk_index_coverage_rejects_unsafe_partial_predicates(
    child_definition: str,
    index_sql: str,
) -> None:
    connection = _connection()
    try:
        connection.execute("CREATE TABLE parent(id TEXT PRIMARY KEY)")
        connection.execute(f"CREATE TABLE child({child_definition})")
        connection.execute(index_sql)
        _assert_schema_mismatch(connection)
    finally:
        connection.close()


def test_fk_index_coverage_accepts_exact_measured_exception_only_when_needed() -> None:
    connection = _connection()
    exception = {
        "table": "child",
        "fk_id": 0,
        "measured_reason": "accepted measured write/read profile",
        "accepted_lld_or_decision_reference": "LLD-01/T002-test",
    }
    try:
        connection.execute("CREATE TABLE parent(id TEXT PRIMARY KEY)")
        connection.execute("CREATE TABLE child(parent_id TEXT REFERENCES parent(id))")
        verify_foreign_key_index_coverage(
            connection,
            exceptions=(exception,),
        )

        connection.execute("CREATE INDEX ix_child_parent ON child(parent_id)")
        with pytest.raises(MigrationError, match="redundant"):
            verify_foreign_key_index_coverage(
                connection,
                exceptions=(exception,),
            )
    finally:
        connection.close()


def test_fk_index_coverage_rejects_stale_exception_without_matching_fk() -> None:
    connection = _connection()
    try:
        connection.execute("CREATE TABLE parent(id TEXT PRIMARY KEY)")
        connection.execute("CREATE TABLE child(value TEXT)")
        with pytest.raises(MigrationError, match="unknown foreign key"):
            verify_foreign_key_index_coverage(
                connection,
                exceptions=(
                    {
                        "table": "child",
                        "fk_id": 0,
                        "measured_reason": "stale",
                        "accepted_lld_or_decision_reference": "LLD-01/stale-test",
                    },
                ),
            )
    finally:
        connection.close()



def _stage_prefix(source: Path, destination: Path, count: int) -> None:
    manifest = MigrationManifest.load(source)
    destination.mkdir()
    entries = manifest.entries[:count]
    for entry in entries:
        shutil.copy2(source / entry.filename, destination / entry.filename)
    (destination / "manifest.json").write_text(
        json.dumps(
            {
                "schema": "SOMA-MIGRATION-MANIFEST-V1",
                "migrations": [
                    {
                        "sequence": entry.sequence,
                        "migration_id": entry.migration_id,
                        "filename": entry.filename,
                        "sha256": entry.sha256,
                    }
                    for entry in entries
                ],
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
        newline="\n",
    )


def _runner(path: Path, directory: Path, security_provider) -> MigrationRunner:
    manifest = MigrationManifest.load(directory)
    return MigrationRunner(
        canonical_database_path=path,
        manifest=manifest,
        factory_for_path=lambda target: ConnectionFactory(
            target,
            security_provider,
            driver=sqlite3,
        ),
        app_version="fk-index-coverage-test",
        ownership_assertion=lambda: True,
    )


def test_sequence_thirteen_adds_only_missing_fk_lookup_indexes_and_preserves_prefix(
    tmp_path,
    migration_directory,
    security_provider,
) -> None:
    prefix = tmp_path / "prefix-twelve"
    _stage_prefix(migration_directory, prefix, 12)
    database = tmp_path / "upgrade-fk-indexes.db"
    assert _runner(database, prefix, security_provider).initialize_or_migrate() == 12

    connection = sqlite3.connect(database)
    try:
        before = connection.execute(
            "SELECT * FROM schema_migrations WHERE sequence<=12 ORDER BY sequence"
        ).fetchall()
    finally:
        connection.close()

    manifest = MigrationManifest.load(migration_directory)
    entry = manifest.entries[12]
    assert entry.sequence == 13
    assert entry.migration_id == "beta_0013_fk_index_coverage"
    assert entry.filename == "0013_fk_index_coverage.sql"
    assert entry.sha256 == "5135e6ca649020a633d8169c111e25476bafdc2f4255997866618cff6ca23b81"

    assert _runner(database, migration_directory, security_provider).initialize_or_migrate() == 13
    assert _runner(database, migration_directory, security_provider).initialize_or_migrate() == 13

    connection = sqlite3.connect(database)
    try:
        assert connection.execute(
            "SELECT * FROM schema_migrations WHERE sequence<=12 ORDER BY sequence"
        ).fetchall() == before
        actual = {
            str(row[0])
            for row in connection.execute(
                "SELECT name FROM sqlite_schema WHERE type='index' AND name IN ("
                "'idx_report_member_service_request_fk',"
                "'idx_report_cohort_customer_fk',"
                "'idx_report_cohort_cpl_fk'"
                ")"
            ).fetchall()
        }
        assert actual == {
            "idx_report_member_service_request_fk",
            "idx_report_cohort_customer_fk",
            "idx_report_cohort_cpl_fk",
        }
        verify_foreign_key_index_coverage(connection, exceptions=())
    finally:
        connection.close()


@pytest.mark.parametrize(
    "index_name",
    [
        "idx_report_member_service_request_fk",
        "idx_report_cohort_customer_fk",
        "idx_report_cohort_cpl_fk",
    ],
)
def test_current_release_fk_coverage_fails_if_required_forward_index_is_missing(
    initialized_database,
    index_name: str,
) -> None:
    database_path, factory_for_path = initialized_database
    connection = factory_for_path(database_path).open_authoritative(
        read_only=False,
        require_wal=True,
    )
    try:
        connection.execute(f'DROP INDEX "{index_name}"')
        with pytest.raises(MigrationError) as raised:
            verify_foundation_schema(connection)
        assert raised.value.code == "MIGRATION_SCHEMA_MISMATCH"
    finally:
        connection.close()
