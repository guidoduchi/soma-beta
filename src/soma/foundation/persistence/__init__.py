"""Verified authoritative persistence boundary."""


from .backup_snapshot import (
    BackupSnapshotProvider,
    DatabaseRestoreVerification,
    RecoveryMarker,
    RestoreCommitResult,
    SnapshotDescriptor,
)

__all__ = [
    "BackupSnapshotProvider",
    "DatabaseRestoreVerification",
    "RecoveryMarker",
    "RestoreCommitResult",
    "SnapshotDescriptor",
]
