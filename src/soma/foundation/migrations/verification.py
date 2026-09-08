from __future__ import annotations

from collections.abc import Iterable
from typing import Any

from soma.foundation.errors import MigrationError

FOUNDATION_TABLES = {
    "instance_metadata",
    "schema_migrations",
    "command_receipts",
    "audit_events",
    "audit_event_results",
    "durable_jobs",
    "job_attempts",
}

FOUNDATION_INDEXES = {
    "idx_audit_recorded_at",
    "idx_audit_target",
    "idx_audit_command",
    "idx_jobs_state_due",
    "idx_jobs_type_state",
}

FOUNDATION_TRIGGERS = {
    "audit_events_before_update_append_only",
    "audit_events_before_delete_append_only",
    "audit_event_results_before_update_append_only",
    "audit_event_results_before_delete_append_only",
}


def verify_foreign_keys(connection: Any) -> None:
    failures = connection.execute("PRAGMA foreign_key_check").fetchall()
    if failures:
        raise MigrationError("MIGRATION_FOREIGN_KEY_FAILURE", f"foreign_key_check returned {len(failures)} row(s)")


def _sqlite_master_names(connection: Any, object_type: str) -> set[str]:
    rows = connection.execute(
        "SELECT name FROM sqlite_master WHERE type = ? AND name NOT LIKE 'sqlite_%'",
        (object_type,),
    ).fetchall()
    return {str(row[0]) for row in rows}


def verify_foundation_schema(connection: Any) -> None:
    verify_foreign_keys(connection)
    tables = _sqlite_master_names(connection, "table")
    indexes = _sqlite_master_names(connection, "index")
    triggers = _sqlite_master_names(connection, "trigger")

    missing_tables = FOUNDATION_TABLES - tables
    missing_indexes = FOUNDATION_INDEXES - indexes
    missing_triggers = FOUNDATION_TRIGGERS - triggers
    if missing_tables or missing_indexes or missing_triggers:
        raise MigrationError(
            "MIGRATION_SCHEMA_MISMATCH",
            f"Foundation schema objects missing: tables={sorted(missing_tables)!r} "
            f"indexes={sorted(missing_indexes)!r} triggers={sorted(missing_triggers)!r}",
        )

    table_list = connection.execute("PRAGMA table_list").fetchall()
    strict_by_name = {str(row[1]): int(row[5]) for row in table_list if len(row) >= 6}
    non_strict = sorted(name for name in FOUNDATION_TABLES if strict_by_name.get(name) != 1)
    if non_strict:
        raise MigrationError("MIGRATION_SCHEMA_MISMATCH", f"Foundation tables must be STRICT: {non_strict!r}")

    rows = connection.execute("SELECT singleton, data_instance_id FROM instance_metadata").fetchall()
    if len(rows) != 1 or int(rows[0][0]) != 1:
        raise MigrationError("MIGRATION_SCHEMA_MISMATCH", "instance_metadata must contain exactly one singleton row")


def verify_expected_objects(
    connection: Any,
    *,
    tables: Iterable[str] = (),
    indexes: Iterable[str] = (),
    triggers: Iterable[str] = (),
) -> None:
    expected = {
        "table": set(tables),
        "index": set(indexes),
        "trigger": set(triggers),
    }
    for object_type, names in expected.items():
        missing = names - _sqlite_master_names(connection, object_type)
        if missing:
            raise MigrationError(
                "MIGRATION_SCHEMA_MISMATCH",
                f"missing {object_type} objects: {sorted(missing)!r}",
            )
