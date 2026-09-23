from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from soma.foundation.errors import IntegrityFailure
from soma.foundation.identifiers import new_uuid4, utc_epoch_seconds
from soma.foundation.persistence.backup_snapshot import (
    BackupSnapshotProvider,
    RecoveryMarker,
)
from soma.foundation.persistence.connections import ConnectionFactory
from soma.foundation.persistence.uow import ReadSnapshot, UnitOfWork


def _provider(database_path, security_provider, *, owned=lambda: True):
    return BackupSnapshotProvider(
        live_database_path=database_path,
        snapshot_factory_builder=lambda path: ConnectionFactory(
            path,
            security_provider,
            driver=sqlite3,
        ),
        restore_factory_builder=lambda path, key_context: ConnectionFactory(
            path,
            security_provider,
            driver=sqlite3,
        ),
        ownership_assertion=owned,
    )


def test_consistent_snapshot_freezes_database_before_later_live_mutation(
    initialized_database,
    tmp_path,
    security_provider,
) -> None:
    database_path, factory_for_path = initialized_database
    factory = factory_for_path(database_path)
    provider = _provider(database_path, security_provider)
    snapshot_path = tmp_path / "snapshot.db"

    with ReadSnapshot(factory) as snapshot:
        descriptor = provider.create_consistent_backup_snapshot(snapshot, snapshot_path)

    command_id = new_uuid4()
    with UnitOfWork(factory) as uow:
        uow.connection.execute(
            "INSERT INTO command_receipts("
            "command_id,command_type,request_hash,target_type,target_id,"
            "committed_at_utc,result_type,result_id"
            ") VALUES (?, 'BackupLaterMutation', ?, 'test', NULL, ?, 'test', NULL)",
            (command_id, "a" * 64, utc_epoch_seconds()),
        )

    snapshot_connection = sqlite3.connect(
        f"file:{snapshot_path.as_posix()}?mode=ro&immutable=1",
        uri=True,
    )
    try:
        assert snapshot_connection.execute(
            "SELECT 1 FROM command_receipts WHERE command_id=?",
            (command_id,),
        ).fetchone() is None
        assert snapshot_connection.execute(
            "SELECT data_instance_id FROM instance_metadata WHERE singleton=1"
        ).fetchone()[0] == descriptor.data_instance_id
    finally:
        snapshot_connection.close()
    assert descriptor.sha256
    assert descriptor.size_bytes == snapshot_path.stat().st_size


def test_verified_stage_replacement_restores_exact_snapshot_and_keeps_emergency_copy(
    initialized_database,
    tmp_path,
    security_provider,
) -> None:
    database_path, factory_for_path = initialized_database
    factory = factory_for_path(database_path)
    provider = _provider(database_path, security_provider)
    stage = tmp_path / "restore-stage.db"

    audit_command = new_uuid4()
    audit_id = new_uuid4()
    with UnitOfWork(factory) as uow:
        uow.connection.execute(
            "INSERT INTO command_receipts("
            "command_id,command_type,request_hash,target_type,target_id,"
            "committed_at_utc,result_type,result_id"
            ") VALUES (?, 'BackupAuditEvidence', ?, 'test', NULL, ?, 'test', NULL)",
            (audit_command, "c" * 64, utc_epoch_seconds()),
        )
        uow.connection.execute(
            "INSERT INTO audit_events("
            "audit_event_id,action_type,action_version,recorded_at_utc,actor_kind,"
            "target_type,command_id,payload_schema,payload_version,payload_json"
            ") VALUES (?, 'test.backup_preserved', 1, ?, 'test', 'test', ?, 'BackupAuditV1', 1, '{}')",
            (audit_id, utc_epoch_seconds(), audit_command),
        )

    with ReadSnapshot(factory) as snapshot:
        provider.create_consistent_backup_snapshot(snapshot, stage)

    later_command = new_uuid4()
    with UnitOfWork(factory) as uow:
        uow.connection.execute(
            "INSERT INTO command_receipts("
            "command_id,command_type,request_hash,target_type,target_id,"
            "committed_at_utc,result_type,result_id"
            ") VALUES (?, 'LaterLiveState', ?, 'test', NULL, ?, 'test', NULL)",
            (later_command, "b" * 64, utc_epoch_seconds()),
        )

    verification = provider.verify_restored_database(stage, object())
    emergency = tmp_path / "emergency-prior-live.db"
    result = provider.replace_live_database_from_verified_stage(
        verification,
        RecoveryMarker(emergency),
    )

    assert result.live_database_path == database_path.resolve(strict=False)
    assert result.emergency_database_path == emergency.resolve(strict=False)
    assert emergency.exists()
    restored = factory_for_path(database_path).open_authoritative(
        read_only=True,
        require_wal=False,
    )
    try:
        assert restored.execute(
            "SELECT 1 FROM command_receipts WHERE command_id=?",
            (later_command,),
        ).fetchone() is None
        assert restored.execute(
            "SELECT data_instance_id FROM instance_metadata WHERE singleton=1"
        ).fetchone()[0] == verification.data_instance_id
        assert restored.execute(
            "SELECT action_type,payload_json FROM audit_events WHERE audit_event_id=?",
            (audit_id,),
        ).fetchone() == ("test.backup_preserved", "{}")
    finally:
        restored.close()

    prior = sqlite3.connect(
        f"file:{emergency.as_posix()}?mode=ro&immutable=1",
        uri=True,
    )
    try:
        assert prior.execute(
            "SELECT 1 FROM command_receipts WHERE command_id=?",
            (later_command,),
        ).fetchone() is not None
    finally:
        prior.close()


def test_verified_stage_tamper_is_rejected_before_live_database_moves(
    initialized_database,
    tmp_path,
    security_provider,
) -> None:
    database_path, factory_for_path = initialized_database
    factory = factory_for_path(database_path)
    provider = _provider(database_path, security_provider)
    stage = tmp_path / "tampered-stage.db"

    with ReadSnapshot(factory) as snapshot:
        provider.create_consistent_backup_snapshot(snapshot, stage)
    verification = provider.verify_restored_database(stage, object())
    live_before = database_path.read_bytes()
    with stage.open("ab") as handle:
        handle.write(b"tamper")

    with pytest.raises(IntegrityFailure):
        provider.replace_live_database_from_verified_stage(
            verification,
            RecoveryMarker(tmp_path / "unused-emergency.db"),
        )
    assert database_path.read_bytes() == live_before
    assert not (tmp_path / "unused-emergency.db").exists()
