from __future__ import annotations

from pathlib import Path

import pytest

from soma.foundation.application.command_boundary import (
    CommandBoundary,
    CommandEnvelope,
    PreparedMutation,
)
from soma.foundation.audit.registry import AuditActionContract, AuditRegistry
from soma.foundation.audit.writer import AuditEventInput, AuditResultRef, AuditWriter
from soma.foundation.errors import IdempotencyConflict, PersistenceFailure
from soma.foundation.identifiers import new_uuid4
from soma.foundation.migrations.runner import iter_migration_statements
from soma.foundation.persistence.uow import UnitOfWork
from soma.foundation.strict_json import ObjectContract


def test_manifest_and_clean_initialization_are_current(initialized_database, migration_directory) -> None:
    database_path, factory_for_path = initialized_database
    factory = factory_for_path(database_path)
    from soma.foundation.migrations.manifest import MigrationManifest

    manifest = MigrationManifest.load(migration_directory)
    connection = factory.open_authoritative(read_only=True, require_wal=True)
    try:
        ledger = connection.execute(
            "SELECT sequence, migration_id, sha256 FROM schema_migrations ORDER BY sequence"
        ).fetchall()
        assert len(ledger) == len(manifest.entries)
        assert [int(row[0]) for row in ledger] == [entry.sequence for entry in manifest.entries]
        assert [str(row[1]) for row in ledger] == [entry.migration_id for entry in manifest.entries]
        assert [str(row[2]) for row in ledger] == [entry.sha256 for entry in manifest.entries]
        instance_rows = connection.execute(
            "SELECT singleton, data_instance_id FROM instance_metadata"
        ).fetchall()
        assert len(instance_rows) == 1
        assert instance_rows[0][0] == 1
        assert len(instance_rows[0][1]) == 36
        assert str(connection.execute("PRAGMA journal_mode").fetchone()[0]).lower() == "wal"
        assert connection.execute("PRAGMA foreign_key_check").fetchall() == []
    finally:
        connection.close()


def test_statement_parser_keeps_trigger_case_body_and_ignores_comment_semicolon() -> None:
    text = """-- comment with a semicolon; that is not a statement boundary\nCREATE TABLE t(id INTEGER PRIMARY KEY, value INTEGER);\n\nCREATE TRIGGER t_guard\nBEFORE UPDATE ON t\nBEGIN\n    SELECT CASE WHEN NEW.value < 0 THEN RAISE(ABORT, 'negative; forbidden') END;\nEND;\n"""
    statements = list(iter_migration_statements(text))
    assert len(statements) == 2
    assert statements[0].startswith("-- comment")
    assert "CREATE TRIGGER t_guard" in statements[1]
    assert "CASE WHEN" in statements[1]


def test_nested_authoritative_uow_is_rejected(initialized_database) -> None:
    database_path, factory_for_path = initialized_database
    factory = factory_for_path(database_path)
    with UnitOfWork(factory):
        with pytest.raises(PersistenceFailure):
            with UnitOfWork(factory):
                pass


def test_command_replay_mutates_and_audits_exactly_once(initialized_database) -> None:
    database_path, factory_for_path = initialized_database
    factory = factory_for_path(database_path)
    connection = factory.open_authoritative(read_only=False, require_wal=True)
    try:
        connection.execute("BEGIN IMMEDIATE")
        connection.execute(
            "CREATE TABLE test_entities(entity_id TEXT PRIMARY KEY, value_text TEXT NOT NULL) STRICT"
        )
        connection.execute("COMMIT")
    finally:
        connection.close()

    registry = AuditRegistry()
    registry.register(
        AuditActionContract(
            action_type="test.entity_created",
            action_version=1,
            payload_schema="TestEntityAuditV1",
            payload_version=1,
            payload_contract=ObjectContract(
                name="TestEntityAuditV1",
                version=1,
                required_fields=frozenset({"entity_id"}),
                allowed_fields=frozenset({"entity_id"}),
            ),
        )
    )
    boundary = CommandBoundary(factory, AuditWriter(registry))
    command_id = new_uuid4()
    entity_id = new_uuid4()
    envelope = CommandEnvelope(
        command_id=command_id,
        command_type="CreateTestEntity",
        target_type="test_entity",
        target_id=entity_id,
        semantic_payload={"value_text": "hello"},
    )

    def prepare(uow: UnitOfWork) -> PreparedMutation:
        assert uow.connection.execute(
            "SELECT 1 FROM test_entities WHERE entity_id = ?", (entity_id,)
        ).fetchone() is None

        def apply(inner_uow: UnitOfWork) -> AuditEventInput:
            inner_uow.connection.execute(
                "INSERT INTO test_entities(entity_id, value_text) VALUES (?, ?)",
                (entity_id, "hello"),
            )
            return AuditEventInput(
                audit_event_id=new_uuid4(),
                action_type="test.entity_created",
                action_version=1,
                actor_kind="local_user",
                target_type="test_entity",
                target_id=entity_id,
                command_id=command_id,
                payload_schema="TestEntityAuditV1",
                payload_version=1,
                payload={"entity_id": entity_id},
                resulting_event_refs=(AuditResultRef("test_entity", entity_id),),
            )

        return PreparedMutation(
            no_change=False,
            result_type="test_entity",
            result_id=entity_id,
            apply=apply,
            response_schema="TestEntityResultV1",
            response={"entity_id": entity_id, "value_text": "hello"},
        )

    first = boundary.execute(envelope, prepare)
    replay = boundary.execute(envelope, prepare)
    assert first.replayed is False
    assert replay.replayed is True
    assert replay.result_id == entity_id
    assert first.response == replay.response == {"entity_id": entity_id, "value_text": "hello"}

    changed_request = CommandEnvelope(
        command_id=command_id,
        command_type="CreateTestEntity",
        target_type="test_entity",
        target_id=entity_id,
        semantic_payload={"value_text": "different"},
    )
    with pytest.raises(IdempotencyConflict):
        boundary.execute(changed_request, prepare)

    connection = factory.open_authoritative(read_only=True, require_wal=True)
    try:
        assert connection.execute("SELECT count(*) FROM test_entities").fetchone()[0] == 1
        assert connection.execute("SELECT count(*) FROM command_receipts").fetchone()[0] == 1
        assert connection.execute("SELECT count(*) FROM audit_events").fetchone()[0] == 1
        assert connection.execute("SELECT count(*) FROM audit_event_results").fetchone()[0] == 1
    finally:
        connection.close()


def test_audit_tables_are_append_only(initialized_database) -> None:
    database_path, factory_for_path = initialized_database
    factory = factory_for_path(database_path)
    with UnitOfWork(factory) as uow:
        command_id = new_uuid4()
        uow.connection.execute(
            "INSERT INTO command_receipts(command_id,command_type,request_hash,target_type,target_id,committed_at_utc,result_type,result_id) "
            "VALUES (?, 'Test', ?, 'test', NULL, 1, NULL, NULL)",
            (command_id, "0" * 64),
        )
        audit_id = new_uuid4()
        uow.connection.execute(
            "INSERT INTO audit_events(audit_event_id,action_type,action_version,recorded_at_utc,actor_kind,target_type,command_id,payload_schema,payload_version,payload_json) "
            "VALUES (?, 'test', 1, 1, 'local_user', 'test', ?, 'TestV1', 1, '{}')",
            (audit_id, command_id),
        )

    with pytest.raises(Exception, match="AUDIT_APPEND_ONLY"):
        with UnitOfWork(factory) as uow:
            uow.connection.execute(
                "UPDATE audit_events SET reason_category = 'changed' WHERE audit_event_id = ?",
                (audit_id,),
            )
