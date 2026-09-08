from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from soma.foundation.errors import SomaError
from soma.foundation.persistence.uow import UnitOfWork


@dataclass(frozen=True, slots=True)
class ImportRunCheckpointState:
    import_run_id: str
    source_family: str
    source_profile_id: str
    chronology_kind: str
    chronology_value: int
    logical_fingerprint: str
    run_state: str
    proposal_count: int
    pending_proposal_count: int
    revision: int


@dataclass(frozen=True, slots=True)
class SourceCheckpointState:
    source_family: str
    source_profile_id: str
    chronology_kind: str
    chronology_value: int
    logical_fingerprint: str
    accepted_import_run_id: str
    last_checked_at_utc: int
    revision: int


class ImportRunRepository:
    @staticmethod
    def get_checkpoint_transition_run(reader: Any, import_run_id: str) -> ImportRunCheckpointState | None:
        row = reader.execute(
            "SELECT import_run_id,source_family,source_profile_id,candidate_chronology_kind,"
            "candidate_chronology_value,logical_fingerprint_sha256,run_state,proposal_count,"
            "pending_proposal_count,revision FROM import_runs WHERE import_run_id=?",
            (import_run_id,),
        ).fetchone()
        if row is None:
            return None
        if row[5] is None:
            raise SomaError("IMPORT_RUN_STALE", "import run has no published logical fingerprint")
        return ImportRunCheckpointState(
            import_run_id=str(row[0]),
            source_family=str(row[1]),
            source_profile_id=str(row[2]),
            chronology_kind=str(row[3]),
            chronology_value=int(row[4]),
            logical_fingerprint=str(row[5]),
            run_state=str(row[6]),
            proposal_count=int(row[7]),
            pending_proposal_count=int(row[8]),
            revision=int(row[9]),
        )

    @staticmethod
    def has_published_row_authority(reader: Any, import_run_id: str) -> bool:
        observation = reader.execute(
            "SELECT 1 FROM source_observations WHERE import_run_id=? LIMIT 1",
            (import_run_id,),
        ).fetchone()
        if observation is not None:
            return True
        proposal = reader.execute(
            "SELECT 1 FROM reconciliation_proposals WHERE import_run_id=? LIMIT 1",
            (import_run_id,),
        ).fetchone()
        return proposal is not None

    @staticmethod
    def mark_noop(
        uow: UnitOfWork,
        *,
        import_run_id: str,
        expected_revision: int,
        completed_at_utc: int,
    ) -> None:
        changed = uow.connection.execute(
            "UPDATE import_runs SET run_state='noop',completed_at_utc=?,revision=revision+1 "
            "WHERE import_run_id=? AND run_state='noop_pending_checkpoint' AND revision=?",
            (completed_at_utc, import_run_id, expected_revision),
        )
        if changed.rowcount != 1:
            raise SomaError("IMPORT_RUN_STALE", "import run changed before checkpoint advancement")


class SourceCheckpointRepository:
    @staticmethod
    def get(reader: Any, source_family: str) -> SourceCheckpointState | None:
        row = reader.execute(
            "SELECT source_family,source_profile_id,accepted_candidate_chronology_kind,"
            "accepted_candidate_chronology_value,accepted_logical_fingerprint_sha256,"
            "accepted_import_run_id,last_checked_at_utc,revision "
            "FROM import_source_checkpoints WHERE source_family=?",
            (source_family,),
        ).fetchone()
        if row is None:
            return None
        return SourceCheckpointState(
            source_family=str(row[0]),
            source_profile_id=str(row[1]),
            chronology_kind=str(row[2]),
            chronology_value=int(row[3]),
            logical_fingerprint=str(row[4]),
            accepted_import_run_id=str(row[5]),
            last_checked_at_utc=int(row[6]),
            revision=int(row[7]),
        )

    @staticmethod
    def advance_newer_identical(
        uow: UnitOfWork,
        *,
        checkpoint: SourceCheckpointState,
        run: ImportRunCheckpointState,
        expected_revision: int,
        checked_at_utc: int,
    ) -> None:
        changed = uow.connection.execute(
            "UPDATE import_source_checkpoints SET source_profile_id=?,"
            "accepted_candidate_chronology_kind=?,accepted_candidate_chronology_value=?,"
            "accepted_logical_fingerprint_sha256=?,accepted_import_run_id=?,last_checked_at_utc=?,"
            "revision=revision+1 WHERE source_family=? AND revision=?",
            (
                run.source_profile_id,
                run.chronology_kind,
                run.chronology_value,
                run.logical_fingerprint,
                run.import_run_id,
                checked_at_utc,
                checkpoint.source_family,
                expected_revision,
            ),
        )
        if changed.rowcount != 1:
            raise SomaError("IMPORT_CHECKPOINT_STALE", "source checkpoint changed before advancement")
