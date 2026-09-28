from __future__ import annotations

import pytest

from soma.foundation.errors import MigrationError
from soma.foundation.migrations.verification import verify_foundation_schema


def _factory(initialized_database):
    database_path, factory_for_path = initialized_database
    return factory_for_path(database_path)


def test_release_schema_manifest_accepts_current_database(initialized_database) -> None:
    connection = _factory(initialized_database).open_authoritative(
        read_only=False,
        require_wal=True,
    )
    try:
        verify_foundation_schema(connection)
    finally:
        connection.close()


def test_same_name_weakened_append_only_trigger_is_rejected(initialized_database) -> None:
    connection = _factory(initialized_database).open_authoritative(
        read_only=False,
        require_wal=True,
    )
    try:
        connection.execute("DROP TRIGGER audit_events_before_update_append_only")
        connection.execute(
            "CREATE TRIGGER audit_events_before_update_append_only "
            "BEFORE UPDATE ON audit_events BEGIN SELECT 1; END"
        )
        with pytest.raises(MigrationError) as raised:
            verify_foundation_schema(connection)
        assert raised.value.code == "MIGRATION_SCHEMA_MISMATCH"
    finally:
        connection.close()


def test_missing_domain_trigger_is_rejected(initialized_database) -> None:
    connection = _factory(initialized_database).open_authoritative(
        read_only=False,
        require_wal=True,
    )
    try:
        connection.execute("DROP TRIGGER contact_affiliation_history_delete_forbidden")
        with pytest.raises(MigrationError) as raised:
            verify_foundation_schema(connection)
        assert raised.value.code == "MIGRATION_SCHEMA_MISMATCH"
    finally:
        connection.close()


def test_extra_authoritative_object_is_rejected(initialized_database) -> None:
    connection = _factory(initialized_database).open_authoritative(
        read_only=False,
        require_wal=True,
    )
    try:
        connection.execute(
            "CREATE TABLE unexpected_schema_object(id TEXT PRIMARY KEY) STRICT"
        )
        with pytest.raises(MigrationError) as raised:
            verify_foundation_schema(connection)
        assert raised.value.code == "MIGRATION_SCHEMA_MISMATCH"
    finally:
        connection.close()


def test_migration_ledger_drift_is_rejected(initialized_database) -> None:
    connection = _factory(initialized_database).open_authoritative(
        read_only=False,
        require_wal=True,
    )
    try:
        connection.execute(
            "UPDATE schema_migrations SET sha256=? WHERE sequence=11",
            ("f" * 64,),
        )
        with pytest.raises(MigrationError) as raised:
            verify_foundation_schema(connection)
        assert raised.value.code == "MIGRATION_SCHEMA_MISMATCH"
    finally:
        connection.close()
