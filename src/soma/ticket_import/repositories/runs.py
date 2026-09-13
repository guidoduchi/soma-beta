from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

from soma.foundation.errors import IntegrityFailure, SomaError, ValidationError
from soma.foundation.identifiers import require_uuid4
from soma.foundation.persistence.uow import UnitOfWork


_HEX64_RE = re.compile(r"[0-9a-f]{64}\Z")
_PUBLICATION_STATES = frozenset({"staged", "waiting_review", "recovery_required", "noop_pending_checkpoint", "noop"})
_NOOP_STATES = frozenset({"noop_pending_checkpoint", "noop"})


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


@dataclass(frozen=True, slots=True)
class ImportRunPublicationCounters:
    observed_row_count: int
    valid_identity_count: int
    invalid_row_count: int
    warning_count: int
    proposal_count: int
    pending_proposal_count: int
    accepted_proposal_count: int
    rejected_proposal_count: int
    deferred_proposal_count: int


@dataclass(frozen=True, slots=True)
class ImportRunPublicationResult:
    import_run_id: str
    run_state: str
    revision: int
    logical_fingerprint: str
    counters: ImportRunPublicationCounters


def _validate_sha256(value: str, *, label: str) -> str:
    if not isinstance(value, str) or _HEX64_RE.fullmatch(value) is None:
        raise ValidationError(f"{label} must be lowercase SHA-256 hex")
    return value


def _validate_nonnegative_integer(value: int, *, label: str) -> int:
    if type(value) is not int or value < 0:
        raise ValidationError(f"{label} must be a nonnegative integer")
    return value


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
    def derive_publication_counters(reader: Any, import_run_id: str) -> ImportRunPublicationCounters:
        canonical_run_id = require_uuid4(import_run_id)
        observation = reader.execute(
            "SELECT COUNT(*),"
            "COALESCE(SUM(CASE WHEN identity_state='valid' THEN 1 ELSE 0 END),0),"
            "COALESCE(SUM(CASE WHEN identity_state='invalid' THEN 1 ELSE 0 END),0) "
            "FROM source_observations WHERE import_run_id=?",
            (canonical_run_id,),
        ).fetchone()
        if observation is None:
            raise IntegrityFailure("publication observation counter query returned no aggregate row")
        observed_row_count = int(observation[0])
        valid_identity_count = int(observation[1])
        invalid_row_count = int(observation[2])
        if observed_row_count != valid_identity_count + invalid_row_count:
            raise IntegrityFailure("import observation identity counters do not reconcile")

        warning_row = reader.execute(
            "SELECT COUNT(*) FROM import_findings WHERE import_run_id=? AND severity='warning'",
            (canonical_run_id,),
        ).fetchone()
        if warning_row is None:
            raise IntegrityFailure("publication warning counter query returned no aggregate row")
        warning_count = int(warning_row[0])

        proposal = reader.execute(
            "SELECT COUNT(*),"
            "COALESCE(SUM(CASE WHEN proposal_state='pending' THEN 1 ELSE 0 END),0),"
            "COALESCE(SUM(CASE WHEN proposal_state='accepted' THEN 1 ELSE 0 END),0),"
            "COALESCE(SUM(CASE WHEN proposal_state='rejected' THEN 1 ELSE 0 END),0),"
            "COALESCE(SUM(CASE WHEN proposal_state='deferred' THEN 1 ELSE 0 END),0),"
            "COALESCE(SUM(CASE WHEN proposal_state='superseded' THEN 1 ELSE 0 END),0),"
            "COALESCE(SUM(CASE WHEN proposal_state='no_change' THEN 1 ELSE 0 END),0) "
            "FROM reconciliation_proposals WHERE import_run_id=?",
            (canonical_run_id,),
        ).fetchone()
        if proposal is None:
            raise IntegrityFailure("publication proposal counter query returned no aggregate row")
        proposal_count = int(proposal[0])
        pending_count = int(proposal[1])
        accepted_count = int(proposal[2])
        rejected_count = int(proposal[3])
        deferred_count = int(proposal[4])
        superseded_count = int(proposal[5])
        no_change_count = int(proposal[6])
        if proposal_count != (
            pending_count
            + accepted_count
            + rejected_count
            + deferred_count
            + superseded_count
            + no_change_count
        ):
            raise IntegrityFailure("import proposal state counters do not reconcile")
        return ImportRunPublicationCounters(
            observed_row_count=observed_row_count,
            valid_identity_count=valid_identity_count,
            invalid_row_count=invalid_row_count,
            warning_count=warning_count,
            proposal_count=proposal_count,
            pending_proposal_count=pending_count,
            accepted_proposal_count=accepted_count,
            rejected_proposal_count=rejected_count,
            deferred_proposal_count=deferred_count,
        )

    @classmethod
    def publish_validating_run(
        cls,
        uow: UnitOfWork,
        *,
        import_run_id: str,
        expected_revision: int,
        logical_fingerprint: str,
        staged_at_utc: int,
        target_state: str,
        completed_at_utc: int | None = None,
    ) -> ImportRunPublicationResult:
        canonical_run_id = require_uuid4(import_run_id)
        if type(expected_revision) is not int or expected_revision < 1:
            raise ValidationError("expected_revision must be a positive integer")
        fingerprint = _validate_sha256(logical_fingerprint, label="logical_fingerprint")
        staged_at = _validate_nonnegative_integer(staged_at_utc, label="staged_at_utc")
        if target_state not in _PUBLICATION_STATES:
            raise ValidationError("target_state is outside the PublishStagedImportRun publication vocabulary")
        if completed_at_utc is None:
            completed_at = None
        else:
            completed_at = _validate_nonnegative_integer(completed_at_utc, label="completed_at_utc")
        if target_state == "noop":
            if completed_at is None:
                raise ValidationError("direct noop publication requires completed_at_utc")
        elif completed_at is not None:
            raise ValidationError("completed_at_utc is only valid for direct noop publication")

        current = uow.connection.execute(
            "SELECT run_state,revision,logical_fingerprint_sha256,staged_at_utc,completed_at_utc,started_at_utc,"
            "observed_row_count,valid_identity_count,invalid_row_count,warning_count,proposal_count,"
            "pending_proposal_count,accepted_proposal_count,rejected_proposal_count,deferred_proposal_count "
            "FROM import_runs WHERE import_run_id=?",
            (canonical_run_id,),
        ).fetchone()
        if current is None:
            raise SomaError("IMPORT_RUN_NOT_FOUND", "import run does not exist")
        if str(current[0]) != "validating" or int(current[1]) != expected_revision:
            raise SomaError("IMPORT_RUN_STALE", "import run is no longer the expected validating publication target")
        if current[2] is not None or current[3] is not None or current[4] is not None:
            raise IntegrityFailure("validating import run already carries publication or completion authority")
        if any(int(current[index]) != 0 for index in range(6, 15)):
            raise IntegrityFailure("validating import run already carries persisted publication counters")
        started_at = int(current[5])
        if staged_at < started_at:
            raise ValidationError("staged_at_utc cannot precede import run start")
        if completed_at is not None and completed_at < started_at:
            raise ValidationError("completed_at_utc cannot precede import run start")

        counters = cls.derive_publication_counters(uow.connection, canonical_run_id)
        terminal_proposal_count = (
            counters.accepted_proposal_count
            + counters.rejected_proposal_count
            + counters.deferred_proposal_count
        )
        total_proposal_state = uow.connection.execute(
            "SELECT COUNT(*) FROM reconciliation_proposals WHERE import_run_id=? AND proposal_state IN ('superseded','no_change')",
            (canonical_run_id,),
        ).fetchone()
        if total_proposal_state is None:
            raise IntegrityFailure("publication terminal proposal query returned no aggregate row")
        if terminal_proposal_count != 0 or int(total_proposal_state[0]) != 0:
            raise IntegrityFailure("validating import run contains a non-pending reconciliation proposal")
        if counters.proposal_count != counters.pending_proposal_count:
            raise IntegrityFailure("initial publication proposals are not all pending")

        if target_state == "staged" and counters.pending_proposal_count != 0:
            raise SomaError("IMPORT_RUN_STALE", "staged publication requires zero pending proposals")
        if target_state == "waiting_review" and counters.pending_proposal_count == 0:
            raise SomaError("IMPORT_RUN_STALE", "waiting_review publication requires at least one pending proposal")
        if target_state in _NOOP_STATES:
            finding_row = uow.connection.execute(
                "SELECT COUNT(*) FROM import_findings WHERE import_run_id=?",
                (canonical_run_id,),
            ).fetchone()
            if finding_row is None:
                raise IntegrityFailure("publication finding cleanup query returned no aggregate row")
            if (
                counters.observed_row_count != 0
                or counters.proposal_count != 0
                or int(finding_row[0]) != 0
            ):
                raise SomaError(
                    "IMPORT_RUN_STALE",
                    "replay/noop publication requires complete unpublished observation/finding/proposal cleanup",
                )

        changed = uow.connection.execute(
            "UPDATE import_runs SET logical_fingerprint_sha256=?,run_state=?,staged_at_utc=?,completed_at_utc=?,"
            "observed_row_count=?,valid_identity_count=?,invalid_row_count=?,warning_count=?,proposal_count=?,"
            "pending_proposal_count=?,accepted_proposal_count=?,rejected_proposal_count=?,deferred_proposal_count=?,"
            "revision=revision+1 WHERE import_run_id=? AND run_state='validating' AND revision=? "
            "AND logical_fingerprint_sha256 IS NULL AND staged_at_utc IS NULL AND completed_at_utc IS NULL "
            "AND observed_row_count=0 AND valid_identity_count=0 AND invalid_row_count=0 AND warning_count=0 "
            "AND proposal_count=0 AND pending_proposal_count=0 AND accepted_proposal_count=0 "
            "AND rejected_proposal_count=0 AND deferred_proposal_count=0",
            (
                fingerprint,
                target_state,
                staged_at,
                completed_at,
                counters.observed_row_count,
                counters.valid_identity_count,
                counters.invalid_row_count,
                counters.warning_count,
                counters.proposal_count,
                counters.pending_proposal_count,
                counters.accepted_proposal_count,
                counters.rejected_proposal_count,
                counters.deferred_proposal_count,
                canonical_run_id,
                expected_revision,
            ),
        )
        if changed.rowcount != 1:
            raise SomaError("IMPORT_RUN_STALE", "import run changed before publication commit")
        return ImportRunPublicationResult(
            import_run_id=canonical_run_id,
            run_state=target_state,
            revision=expected_revision + 1,
            logical_fingerprint=fingerprint,
            counters=counters,
        )

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
