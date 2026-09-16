from __future__ import annotations

from dataclasses import dataclass

from soma.foundation.errors import IntegrityFailure, SomaError
from soma.foundation.identifiers import require_uuid4
from soma.foundation.persistence.connections import ConnectionFactory
from soma.foundation.persistence.uow import ReadSnapshot

from ..repositories.proposals import ProposalRepository
from ..repositories.runs import SourceCheckpointRepository


@dataclass(frozen=True, slots=True)
class ImportRecoveryPreview:
    import_run_id: str
    review_fingerprint: str
    classification: str
    candidate: dict[str, object]
    checkpoint: dict[str, object]
    proposal_count: int
    finding_count: int
    allowed_actions: tuple[str, ...]

    def to_response(self) -> dict[str, object]:
        return {
            "import_run_id": self.import_run_id,
            "review_fingerprint": self.review_fingerprint,
            "classification": self.classification,
            "candidate": dict(self.candidate),
            "checkpoint": dict(self.checkpoint),
            "proposal_count": self.proposal_count,
            "finding_count": self.finding_count,
            "allowed_actions": list(self.allowed_actions),
        }


class ImportRecoveryQueryService:
    def __init__(self, connection_factory: ConnectionFactory) -> None:
        self._factory = connection_factory

    def preview(self, import_run_id: str) -> ImportRecoveryPreview:
        run_id = require_uuid4(import_run_id)
        with ReadSnapshot(self._factory) as snapshot:
            run = ProposalRepository.get_run(snapshot.connection, run_id)
            if run.run_state != "recovery_required":
                raise SomaError("IMPORT_RUN_NOT_RECOVERY_REQUIRED", "import run is not awaiting recovery review")
            checkpoint = SourceCheckpointRepository.get(snapshot.connection, run.source_family)
            if checkpoint is None:
                raise IntegrityFailure("recovery-required import run has no source checkpoint")
            profile = snapshot.connection.execute(
                "SELECT source_profile_id FROM import_runs WHERE import_run_id=?",
                (run_id,),
            ).fetchone()
            if profile is None or str(profile[0]) != checkpoint.source_profile_id:
                raise IntegrityFailure("recovery run and checkpoint source profiles disagree")
            if run.candidate_chronology_kind != checkpoint.chronology_kind:
                raise IntegrityFailure("recovery run and checkpoint chronology kinds disagree")
            if run.candidate_chronology_value < checkpoint.chronology_value:
                classification = "older_source"
            elif (
                run.candidate_chronology_value == checkpoint.chronology_value
                and run.logical_fingerprint != checkpoint.logical_fingerprint
            ):
                classification = "equal_chronology_different_content"
            else:
                raise IntegrityFailure("recovery-required run no longer has a recovery classification")
            finding = snapshot.connection.execute(
                "SELECT COUNT(*) FROM import_findings WHERE import_run_id=?",
                (run_id,),
            ).fetchone()
            proposal = snapshot.connection.execute(
                "SELECT COUNT(*) FROM reconciliation_proposals WHERE import_run_id=?",
                (run_id,),
            ).fetchone()
            if finding is None or proposal is None:
                raise IntegrityFailure("recovery evidence count query returned no aggregate row")
            actions = ["defer", "authorize_correction"]
            if run.accepted_count == 0:
                actions.insert(0, "reject")
            return ImportRecoveryPreview(
                import_run_id=run_id,
                review_fingerprint=ProposalRepository.recovery_review_fingerprint(snapshot.connection, run),
                classification=classification,
                candidate={
                    "chronology_kind": run.candidate_chronology_kind,
                    "chronology_value": run.candidate_chronology_value,
                    "logical_fingerprint": run.logical_fingerprint,
                    "import_run_id": run_id,
                },
                checkpoint={
                    "chronology_kind": checkpoint.chronology_kind,
                    "chronology_value": checkpoint.chronology_value,
                    "logical_fingerprint": checkpoint.logical_fingerprint,
                    "import_run_id": checkpoint.accepted_import_run_id,
                },
                proposal_count=int(proposal[0]),
                finding_count=int(finding[0]),
                allowed_actions=tuple(actions),
            )


__all__ = ["ImportRecoveryPreview", "ImportRecoveryQueryService"]
