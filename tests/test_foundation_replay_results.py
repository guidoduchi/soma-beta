from __future__ import annotations

import hashlib
import json
import shutil
import sqlite3
from pathlib import Path

import pytest

from soma.foundation.application.command_boundary import (
    CommandBoundary,
    CommandEnvelope,
    PreparedMutation,
)
from soma.foundation.application.command_receipts import CommandReceiptStore
from soma.foundation.audit.registry import AuditActionContract, AuditRegistry
from soma.foundation.audit.writer import AuditEventInput, AuditResultRef, AuditWriter
from soma.foundation.errors import (
    IdempotencyResultUnavailable,
    IntegrityFailure,
    PersistenceFailure,
    ValidationError,
)
from soma.foundation.identifiers import new_uuid4
from soma.foundation.migrations.manifest import MigrationManifest
from soma.foundation.migrations.runner import MigrationRunner
from soma.foundation.persistence.connections import ConnectionFactory
from soma.foundation.persistence.uow import UnitOfWork
from soma.foundation.strict_json import ObjectContract, canonical_json_bytes


def _audit_writer() -> AuditWriter:
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
    return AuditWriter(registry)


def _create_test_entity_table(factory) -> None:
    with UnitOfWork(factory) as uow:
        uow.connection.execute(
            "CREATE TABLE IF NOT EXISTS replay_test_entities("
            "entity_id TEXT PRIMARY KEY, value_text TEXT NOT NULL"
            ") STRICT"
        )


def _material_preparation(command_id: str, entity_id: str, counter: list[int]):
    def prepare(uow: UnitOfWork) -> PreparedMutation:
        counter[0] += 1

        def apply(inner_uow: UnitOfWork) -> AuditEventInput:
            inner_uow.connection.execute(
                "INSERT INTO replay_test_entities(entity_id, value_text) VALUES (?, ?)",
                (entity_id, "original"),
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
            response_version=1,
            response={
                "entity_id": entity_id,
                "revision": 1,
                "value_text": "original",
            },
        )

    return prepare


def test_exact_replay_result_is_state_independent(initialized_database) -> None:
    database_path, factory_for_path = initialized_database
    factory = factory_for_path(database_path)
    _create_test_entity_table(factory)

    command_id = new_uuid4()
    entity_id = new_uuid4()
    envelope = CommandEnvelope(
        command_id=command_id,
        command_type="CreateReplayTestEntity",
        target_type="test_entity",
        target_id=entity_id,
        semantic_payload={"value_text": "original"},
    )
    prepare_count = [0]
    boundary = CommandBoundary(factory, _audit_writer())
    prepare = _material_preparation(command_id, entity_id, prepare_count)

    first = boundary.execute(envelope, prepare)
    with UnitOfWork(factory) as uow:
        uow.connection.execute(
            "UPDATE replay_test_entities SET value_text = 'later' WHERE entity_id = ?",
            (entity_id,),
        )

    replay = boundary.execute(envelope, prepare)

    assert prepare_count == [1]
    assert first.replayed is False
    assert replay.replayed is True
    assert replay.response_schema == first.response_schema == "TestEntityResultV1"
    assert replay.response_version == first.response_version == 1
    assert replay.response == first.response == {
        "entity_id": entity_id,
        "revision": 1,
        "value_text": "original",
    }
    assert canonical_json_bytes(replay.response) == canonical_json_bytes(first.response)

    connection = factory.open_authoritative(read_only=True, require_wal=True)
    try:
        row = connection.execute(
            "SELECT response_schema, response_version, response_json, response_sha256 "
            "FROM command_receipt_results WHERE command_id = ?",
            (command_id,),
        ).fetchone()
        assert row is not None
        exact_bytes = canonical_json_bytes(first.response)
        assert row[0] == "TestEntityResultV1"
        assert row[1] == 1
        assert str(row[2]).encode("utf-8") == exact_bytes
        assert row[3] == hashlib.sha256(exact_bytes).hexdigest()
        assert connection.execute("SELECT count(*) FROM audit_events").fetchone()[0] == 1
    finally:
        connection.close()


def test_no_change_persists_exact_response_without_audit(initialized_database) -> None:
    database_path, factory_for_path = initialized_database
    factory = factory_for_path(database_path)
    boundary = CommandBoundary(factory, AuditWriter(AuditRegistry()))
    command_id = new_uuid4()
    envelope = CommandEnvelope(
        command_id=command_id,
        command_type="NoChangeProbe",
        target_type="probe",
        target_id=None,
        semantic_payload={"desired": "already"},
    )
    prepare_count = [0]

    def prepare(uow: UnitOfWork) -> PreparedMutation:
        prepare_count[0] += 1
        return PreparedMutation(
            no_change=True,
            result_type="NO_CHANGE",
            result_id=None,
            response_schema="NoChangeProbeResultV1",
            response_version=1,
            response={"outcome": "NO_CHANGE", "revision": 7},
        )

    first = boundary.execute(envelope, prepare)
    replay = boundary.execute(envelope, prepare)

    assert prepare_count == [1]
    assert first.no_change is True
    assert replay.no_change is True
    assert replay.replayed is True
    assert replay.response == first.response == {"outcome": "NO_CHANGE", "revision": 7}

    connection = factory.open_authoritative(read_only=True, require_wal=True)
    try:
        assert connection.execute(
            "SELECT count(*) FROM command_receipts WHERE command_id = ?",
            (command_id,),
        ).fetchone()[0] == 1
        assert connection.execute(
            "SELECT count(*) FROM command_receipt_results WHERE command_id = ?",
            (command_id,),
        ).fetchone()[0] == 1
        assert connection.execute(
            "SELECT count(*) FROM audit_events WHERE command_id = ?",
            (command_id,),
        ).fetchone()[0] == 0
    finally:
        connection.close()


def test_legacy_receipt_without_exact_result_never_prepares(initialized_database) -> None:
    database_path, factory_for_path = initialized_database
    factory = factory_for_path(database_path)
    command_id = new_uuid4()
    envelope = CommandEnvelope(
        command_id=command_id,
        command_type="LegacyCommittedCommand",
        target_type="legacy",
        target_id="legacy-1",
        semantic_payload={"value": 1},
    )
    with UnitOfWork(factory) as uow:
        uow.connection.execute(
            "INSERT INTO command_receipts("
            "command_id,command_type,request_hash,target_type,target_id,committed_at_utc,result_type,result_id"
            ") VALUES (?, ?, ?, ?, ?, 1, 'legacy', 'legacy-1')",
            (
                command_id,
                envelope.command_type,
                envelope.request_hash(),
                envelope.target_type,
                envelope.target_id,
            ),
        )

    prepare_count = [0]

    def prepare(uow: UnitOfWork) -> PreparedMutation:
        prepare_count[0] += 1
        pytest.fail("legacy replay invoked command preparation")

    with pytest.raises(IdempotencyResultUnavailable) as failure:
        CommandBoundary(factory, AuditWriter(AuditRegistry())).execute(envelope, prepare)
    assert failure.value.code == "IDEMPOTENCY_RESULT_UNAVAILABLE"
    assert prepare_count == [0]


@pytest.mark.parametrize(
    ("response_json", "digest"),
    [
        ('{"b":1, "a":2}', hashlib.sha256(b'{"b":1, "a":2}').hexdigest()),
        ('{"a":1}', "0" * 64),
    ],
)
def test_corrupt_or_noncanonical_result_snapshot_fails_closed(
    initialized_database,
    response_json,
    digest,
) -> None:
    database_path, factory_for_path = initialized_database
    factory = factory_for_path(database_path)
    command_id = new_uuid4()
    envelope = CommandEnvelope(
        command_id=command_id,
        command_type="CorruptReplayProbe",
        target_type="probe",
        target_id=None,
        semantic_payload={},
    )
    with UnitOfWork(factory) as uow:
        uow.connection.execute(
            "INSERT INTO command_receipts("
            "command_id,command_type,request_hash,target_type,target_id,committed_at_utc,result_type,result_id"
            ") VALUES (?, ?, ?, ?, NULL, 1, 'probe', NULL)",
            (command_id, envelope.command_type, envelope.request_hash(), envelope.target_type),
        )
        uow.connection.execute(
            "INSERT INTO command_receipt_results("
            "command_id,response_schema,response_version,response_json,response_sha256"
            ") VALUES (?, 'CorruptProbeV1', 1, ?, ?)",
            (command_id, response_json, digest),
        )

    with pytest.raises(IntegrityFailure) as failure:
        CommandBoundary(factory, AuditWriter(AuditRegistry())).execute(
            envelope,
            lambda uow: pytest.fail("corrupt replay invoked command preparation"),
        )
    assert failure.value.code == "INTEGRITY_FAILURE"


def test_result_insert_failure_rolls_back_receipt_domain_audit_and_snapshot(initialized_database) -> None:
    database_path, factory_for_path = initialized_database
    factory = factory_for_path(database_path)
    _create_test_entity_table(factory)

    class FailingResultStore(CommandReceiptStore):
        def insert_exact_result(self, uow, result) -> None:
            super().insert_exact_result(uow, result)
            raise PersistenceFailure("injected result persistence failure")

    command_id = new_uuid4()
    entity_id = new_uuid4()
    envelope = CommandEnvelope(
        command_id=command_id,
        command_type="CreateReplayTestEntity",
        target_type="test_entity",
        target_id=entity_id,
        semantic_payload={"value_text": "original"},
    )
    boundary = CommandBoundary(factory, _audit_writer(), FailingResultStore())

    with pytest.raises(PersistenceFailure):
        boundary.execute(envelope, _material_preparation(command_id, entity_id, [0]))

    connection = factory.open_authoritative(read_only=True, require_wal=True)
    try:
        assert connection.execute("SELECT count(*) FROM replay_test_entities").fetchone()[0] == 0
        assert connection.execute(
            "SELECT count(*) FROM command_receipts WHERE command_id = ?",
            (command_id,),
        ).fetchone()[0] == 0
        assert connection.execute(
            "SELECT count(*) FROM command_receipt_results WHERE command_id = ?",
            (command_id,),
        ).fetchone()[0] == 0
        assert connection.execute(
            "SELECT count(*) FROM audit_events WHERE command_id = ?",
            (command_id,),
        ).fetchone()[0] == 0
    finally:
        connection.close()


def test_oversized_exact_response_rolls_back_material_command(initialized_database) -> None:
    database_path, factory_for_path = initialized_database
    factory = factory_for_path(database_path)
    _create_test_entity_table(factory)
    command_id = new_uuid4()
    entity_id = new_uuid4()
    envelope = CommandEnvelope(
        command_id=command_id,
        command_type="OversizedReplayResult",
        target_type="test_entity",
        target_id=entity_id,
        semantic_payload={},
    )

    def prepare(uow: UnitOfWork) -> PreparedMutation:
        material = _material_preparation(command_id, entity_id, [0])(uow)
        return PreparedMutation(
            no_change=material.no_change,
            result_type=material.result_type,
            result_id=material.result_id,
            apply=material.apply,
            response_schema="OversizedResultV1",
            response_version=1,
            response={"value": "x" * 524_289},
        )

    with pytest.raises(ValidationError):
        CommandBoundary(factory, _audit_writer()).execute(envelope, prepare)

    connection = factory.open_authoritative(read_only=True, require_wal=True)
    try:
        assert connection.execute("SELECT count(*) FROM replay_test_entities").fetchone()[0] == 0
        assert connection.execute(
            "SELECT count(*) FROM command_receipts WHERE command_id = ?",
            (command_id,),
        ).fetchone()[0] == 0
        assert connection.execute(
            "SELECT count(*) FROM audit_events WHERE command_id = ?",
            (command_id,),
        ).fetchone()[0] == 0
    finally:
        connection.close()


def test_replay_result_rows_are_append_only(initialized_database) -> None:
    database_path, factory_for_path = initialized_database
    factory = factory_for_path(database_path)
    command_id = new_uuid4()
    envelope = CommandEnvelope(
        command_id=command_id,
        command_type="AppendOnlyNoChange",
        target_type="probe",
        target_id=None,
        semantic_payload={},
    )
    CommandBoundary(factory, AuditWriter(AuditRegistry())).execute(
        envelope,
        lambda uow: PreparedMutation(
            no_change=True,
            result_type="NO_CHANGE",
            result_id=None,
            response_schema="AppendOnlyNoChangeResultV1",
            response={"outcome": "NO_CHANGE"},
        ),
    )

    with pytest.raises(Exception, match="COMMAND_REPLAY_RESULT_APPEND_ONLY"):
        with UnitOfWork(factory) as uow:
            uow.connection.execute(
                "UPDATE command_receipt_results SET response_version = 2 WHERE command_id = ?",
                (command_id,),
            )
    with pytest.raises(Exception, match="COMMAND_REPLAY_RESULT_APPEND_ONLY"):
        with UnitOfWork(factory) as uow:
            uow.connection.execute(
                "DELETE FROM command_receipt_results WHERE command_id = ?",
                (command_id,),
            )


def test_migration_five_preserves_legacy_receipts(
    tmp_path: Path,
    migration_directory: Path,
    security_provider,
) -> None:
    current_manifest = MigrationManifest.load(migration_directory)
    legacy_directory = tmp_path / "legacy-migrations"
    legacy_directory.mkdir()
    legacy_entries = current_manifest.entries[:4]
    for entry in legacy_entries:
        shutil.copyfile(
            migration_directory / entry.filename,
            legacy_directory / entry.filename,
        )
    legacy_document = {
        "schema": "SOMA-MIGRATION-MANIFEST-V1",
        "migrations": [
            {
                "sequence": entry.sequence,
                "migration_id": entry.migration_id,
                "filename": entry.filename,
                "sha256": entry.sha256,
            }
            for entry in legacy_entries
        ],
    }
    (legacy_directory / "manifest.json").write_text(
        json.dumps(legacy_document, indent=2) + "\n",
        encoding="utf-8",
        newline="\n",
    )

    database_path = tmp_path / "legacy.db"

    def factory_for_path(path: Path) -> ConnectionFactory:
        return ConnectionFactory(path, security_provider, driver=sqlite3)

    MigrationRunner(
        canonical_database_path=database_path,
        manifest=MigrationManifest.load(legacy_directory),
        factory_for_path=factory_for_path,
        app_version="legacy-test",
        ownership_assertion=lambda: True,
        verifier=lambda connection: None,
    ).initialize_or_migrate()

    factory = factory_for_path(database_path)
    command_id = new_uuid4()
    legacy_values = (
        command_id,
        "LegacyCommand",
        "a" * 64,
        "legacy_target",
        "target-1",
        123,
        "legacy_result",
        "result-1",
    )
    with UnitOfWork(factory) as uow:
        uow.connection.execute(
            "INSERT INTO command_receipts("
            "command_id,command_type,request_hash,target_type,target_id,committed_at_utc,result_type,result_id"
            ") VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            legacy_values,
        )

    before = factory.open_authoritative(read_only=True, require_wal=True)
    try:
        receipt_before = tuple(
            before.execute(
                "SELECT command_id,command_type,request_hash,target_type,target_id,"
                "committed_at_utc,result_type,result_id FROM command_receipts WHERE command_id = ?",
                (command_id,),
            ).fetchone()
        )
        ledger_before = [
            tuple(row)
            for row in before.execute(
                "SELECT sequence,migration_id,sha256 FROM schema_migrations ORDER BY sequence"
            ).fetchall()
        ]
    finally:
        before.close()

    MigrationRunner(
        canonical_database_path=database_path,
        manifest=current_manifest,
        factory_for_path=factory_for_path,
        app_version="current-test",
        ownership_assertion=lambda: True,
    ).initialize_or_migrate()

    after = factory.open_authoritative(read_only=True, require_wal=True)
    try:
        receipt_after = tuple(
            after.execute(
                "SELECT command_id,command_type,request_hash,target_type,target_id,"
                "committed_at_utc,result_type,result_id FROM command_receipts WHERE command_id = ?",
                (command_id,),
            ).fetchone()
        )
        ledger_after = [
            tuple(row)
            for row in after.execute(
                "SELECT sequence,migration_id,sha256 FROM schema_migrations ORDER BY sequence"
            ).fetchall()
        ]
        assert receipt_after == receipt_before == legacy_values
        assert ledger_after[:4] == ledger_before
        assert ledger_after[4][0] == 5
        assert ledger_after[4][1] == "beta_0005_command_replay_results"
        assert after.execute(
            "SELECT count(*) FROM command_receipt_results WHERE command_id = ?",
            (command_id,),
        ).fetchone()[0] == 0
        names = {
            str(row[0])
            for row in after.execute(
                "SELECT name FROM sqlite_schema WHERE name LIKE 'command_receipt_results%'"
            ).fetchall()
        }
        assert names == {
            "command_receipt_results",
            "command_receipt_results_before_update_append_only",
            "command_receipt_results_before_delete_append_only",
        }
    finally:
        after.close()
