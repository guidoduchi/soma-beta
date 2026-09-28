from __future__ import annotations

import pytest

from soma.foundation.errors import MigrationError
from soma.foundation.identifiers import new_uuid4
from soma.foundation.migrations.verification import verify_foundation_schema
from soma.foundation.persistence.uow import UnitOfWork
from soma.reference.application.contact_service import ContactReferenceService


_LLD02_TABLES = {
    "reference_metadata",
    "local_user_profiles",
    "customer_organizations",
    "customer_org_identifiers",
    "contacts",
    "contact_channels",
    "contact_affiliations",
    "dispatch_locations",
    "reference_lifecycle_events",
    "setting_values",
}


def _factory(initialized_database):
    database_path, factory_for_path = initialized_database
    return factory_for_path(database_path)


def test_every_lld02_table_is_sqlite_strict(initialized_database) -> None:
    factory = _factory(initialized_database)
    connection = factory.open_authoritative(read_only=True, require_wal=True)
    try:
        rows = connection.execute("PRAGMA table_list").fetchall()
        strict_by_name = {str(row[1]): int(row[5]) for row in rows}
        assert _LLD02_TABLES <= set(strict_by_name)
        assert {name: strict_by_name[name] for name in _LLD02_TABLES} == {
            name: 1 for name in _LLD02_TABLES
        }
    finally:
        connection.close()


def test_direct_non_email_contact_channel_insert_is_rejected_by_database(
    initialized_database,
) -> None:
    factory = _factory(initialized_database)
    contact = ContactReferenceService(factory).create_contact(
        command_id=new_uuid4(),
        name="DB Constraint Contact",
    )
    with pytest.raises(Exception):
        with UnitOfWork(factory) as uow:
            uow.connection.execute(
                "INSERT INTO contact_channels("
                "contact_channel_id,contact_id,channel_kind,value_text,match_key,"
                "lifecycle_state,revision,created_at_utc,updated_at_utc"
                ") VALUES (?,?,'phone','+593999999999','+593999999999','active',1,1,1)",
                (new_uuid4(), contact.contact_id),
            )


def test_release_schema_verifier_detects_missing_lld02_supporting_index(
    initialized_database,
) -> None:
    factory = _factory(initialized_database)
    connection = factory.open_authoritative(read_only=False, require_wal=True)
    try:
        connection.execute("DROP INDEX idx_contacts_active_name_match")
        with pytest.raises(MigrationError) as raised:
            verify_foundation_schema(connection)
        assert raised.value.code == "MIGRATION_SCHEMA_MISMATCH"
    finally:
        connection.close()


def test_release_schema_verifier_detects_missing_lld02_history_protection_trigger(
    initialized_database,
) -> None:
    factory = _factory(initialized_database)
    connection = factory.open_authoritative(read_only=False, require_wal=True)
    try:
        connection.execute("DROP TRIGGER contact_affiliation_history_delete_forbidden")
        with pytest.raises(MigrationError) as raised:
            verify_foundation_schema(connection)
        assert raised.value.code == "MIGRATION_SCHEMA_MISMATCH"
    finally:
        connection.close()
