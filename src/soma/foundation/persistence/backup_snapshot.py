from __future__ import annotations

import hashlib
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Any

from soma.foundation.errors import IntegrityFailure, PersistenceFailure, ValidationError
from soma.foundation.identifiers import require_uuid4
from soma.foundation.migrations.verification import verify_foundation_schema
from soma.foundation.persistence.connections import ConnectionFactory
from soma.foundation.persistence.uow import ReadSnapshot

SnapshotFactoryBuilder = Callable[[Path], ConnectionFactory]
RestoreFactoryBuilder = Callable[[Path, object], ConnectionFactory]


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while True:
            chunk = handle.read(4 * 1024 * 1024)
            if not chunk:
                break
            digest.update(chunk)
    return digest.hexdigest()


def _require_plain_file(path: Path, *, label: str) -> None:
    if not path.exists() or not path.is_file() or path.is_symlink():
        raise ValidationError(f"{label} must be an existing ordinary file")


@dataclass(frozen=True, slots=True)
class SnapshotDescriptor:
    path: Path
    size_bytes: int
    sha256: str
    data_instance_id: str
    migration_sequence: int
    migration_id: str | None


@dataclass(frozen=True, slots=True)
class DatabaseRestoreVerification:
    stage_path: Path
    size_bytes: int
    sha256: str
    data_instance_id: str
    migration_sequence: int
    migration_id: str | None
    integrity_state: str


@dataclass(frozen=True, slots=True)
class RecoveryMarker:
    emergency_database_path: Path


@dataclass(frozen=True, slots=True)
class RestoreCommitResult:
    live_database_path: Path
    emergency_database_path: Path
    data_instance_id: str
    sha256: str


class BackupSnapshotProvider:
    """Foundation database mechanics only; LLD-12 owns backup crypto and authorization."""

    def __init__(
        self,
        *,
        live_database_path: Path,
        snapshot_factory_builder: SnapshotFactoryBuilder,
        restore_factory_builder: RestoreFactoryBuilder,
        ownership_assertion: Callable[[], bool],
    ) -> None:
        self._live_path = Path(live_database_path).resolve(strict=False)
        self._snapshot_factory_builder = snapshot_factory_builder
        self._restore_factory_builder = restore_factory_builder
        self._ownership_assertion = ownership_assertion
        self._verified_stages: dict[Path, tuple[str, object]] = {}

    @staticmethod
    def _identity(connection: Any) -> tuple[str, int, str | None]:
        identity = connection.execute(
            "SELECT data_instance_id FROM instance_metadata WHERE singleton=1"
        ).fetchone()
        if identity is None:
            raise IntegrityFailure("backup snapshot data instance identity is unavailable")
        data_instance_id = str(identity[0])
        require_uuid4(data_instance_id)
        row = connection.execute(
            "SELECT sequence,migration_id FROM schema_migrations "
            "ORDER BY sequence DESC LIMIT 1"
        ).fetchone()
        sequence = 0 if row is None else int(row[0])
        migration_id = None if row is None else str(row[1])
        return data_instance_id, sequence, migration_id

    @staticmethod
    def _ensure_no_sidecars(path: Path) -> None:
        present = [
            suffix
            for suffix in ("-wal", "-shm", "-journal")
            if Path(str(path) + suffix).exists()
        ]
        if present:
            raise PersistenceFailure(
                "database replacement requires sidecar-free verified files"
            )

    def create_consistent_backup_snapshot(
        self,
        read_context: ReadSnapshot,
        target_path: Path,
    ) -> SnapshotDescriptor:
        target = Path(target_path).resolve(strict=False)
        if not target.is_absolute() or not target.parent.exists():
            raise ValidationError("backup snapshot target parent is unavailable")
        if target == self._live_path:
            raise ValidationError("backup snapshot target cannot be the live database")
        if target.exists():
            raise ValidationError("backup snapshot target must not already exist")

        source = read_context.connection
        data_instance_id, sequence, migration_id = self._identity(source)
        factory = self._snapshot_factory_builder(target)
        destination = factory.open_authoritative(read_only=False, require_wal=False)
        try:
            mode = str(destination.execute("PRAGMA journal_mode=DELETE").fetchone()[0]).lower()
            if mode != "delete":
                raise PersistenceFailure("backup snapshot staging database is not in DELETE mode")
            source.backup(destination)
            verify_foundation_schema(destination)
        except BaseException:
            try:
                destination.close()
            finally:
                target.unlink(missing_ok=True)
                for suffix in ("-wal", "-shm", "-journal"):
                    Path(str(target) + suffix).unlink(missing_ok=True)
            raise
        else:
            destination.close()

        self._ensure_no_sidecars(target)
        _require_plain_file(target, label="backup snapshot")
        digest = _sha256_file(target)
        return SnapshotDescriptor(
            path=target,
            size_bytes=target.stat().st_size,
            sha256=digest,
            data_instance_id=data_instance_id,
            migration_sequence=sequence,
            migration_id=migration_id,
        )

    def verify_restored_database(
        self,
        path: Path,
        key_context: object,
    ) -> DatabaseRestoreVerification:
        stage = Path(path).resolve(strict=False)
        _require_plain_file(stage, label="restore stage")
        self._ensure_no_sidecars(stage)
        factory = self._restore_factory_builder(stage, key_context)
        connection = factory.open_authoritative(read_only=False, require_wal=False)
        try:
            verify_foundation_schema(connection)
            data_instance_id, sequence, migration_id = self._identity(connection)
        finally:
            connection.close()
        digest = _sha256_file(stage)
        resolved = stage.resolve(strict=True)
        self._verified_stages[resolved] = (digest, key_context)
        return DatabaseRestoreVerification(
            stage_path=resolved,
            size_bytes=resolved.stat().st_size,
            sha256=digest,
            data_instance_id=data_instance_id,
            migration_sequence=sequence,
            migration_id=migration_id,
            integrity_state="VERIFIED",
        )

    def replace_live_database_from_verified_stage(
        self,
        stage_descriptor: DatabaseRestoreVerification,
        recovery_marker: RecoveryMarker,
    ) -> RestoreCommitResult:
        if not self._ownership_assertion():
            raise PersistenceFailure("canonical data-instance ownership is required for restore")
        if stage_descriptor.integrity_state != "VERIFIED":
            raise ValidationError("restore stage is not verified")
        stage = Path(stage_descriptor.stage_path).resolve(strict=True)
        remembered = self._verified_stages.get(stage)
        if remembered is None:
            raise ValidationError("restore stage was not verified by this provider")
        remembered_digest, key_context = remembered
        digest = _sha256_file(stage)
        if digest != stage_descriptor.sha256 or digest != remembered_digest:
            raise IntegrityFailure("verified restore stage changed before replacement")
        if stage.stat().st_size != stage_descriptor.size_bytes:
            raise IntegrityFailure("verified restore stage size changed before replacement")

        live = self._live_path
        emergency = Path(recovery_marker.emergency_database_path).resolve(strict=False)
        if not emergency.is_absolute() or not emergency.parent.exists():
            raise ValidationError("restore emergency path parent is unavailable")
        if emergency in {live, stage} or emergency.exists():
            raise ValidationError("restore emergency path must be a distinct absent path")
        if live.exists():
            _require_plain_file(live, label="live database")
        self._ensure_no_sidecars(live)
        self._ensure_no_sidecars(stage)

        if live.parent.stat().st_dev != stage.stat().st_dev:
            raise PersistenceFailure("restore stage must share the live database filesystem")
        if live.exists() and live.parent.stat().st_dev != emergency.parent.stat().st_dev:
            raise PersistenceFailure("emergency recovery path must share the live database filesystem")

        prior_existed = live.exists()
        published = False
        try:
            if prior_existed:
                os.replace(live, emergency)
            os.replace(stage, live)
            published = True

            factory = self._restore_factory_builder(live, key_context)
            connection = factory.open_authoritative(read_only=False, require_wal=False)
            try:
                verify_foundation_schema(connection)
                data_instance_id, _sequence, _migration_id = self._identity(connection)
            finally:
                connection.close()
            live_digest = _sha256_file(live)
            if live_digest != digest or data_instance_id != stage_descriptor.data_instance_id:
                raise IntegrityFailure("published restored database differs from verified stage")
            self._verified_stages.pop(stage, None)
            return RestoreCommitResult(
                live_database_path=live,
                emergency_database_path=emergency,
                data_instance_id=data_instance_id,
                sha256=live_digest,
            )
        except BaseException:
            try:
                if published and live.exists():
                    os.replace(live, stage)
                if prior_existed and emergency.exists():
                    os.replace(emergency, live)
            except OSError as rollback_exc:
                raise PersistenceFailure(
                    "restore replacement failed and prior live database could not be recovered"
                ) from rollback_exc
            raise
