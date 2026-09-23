from __future__ import annotations

import sqlite3

import pytest

from soma.foundation.errors import MigrationError
from soma.foundation.migrations.verification import verify_foreign_key_index_coverage


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
