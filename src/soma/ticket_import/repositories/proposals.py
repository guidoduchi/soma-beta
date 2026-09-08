from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from soma.foundation.errors import SomaError
from soma.foundation.persistence.uow import UnitOfWork
from soma.foundation.strict_json import sha256_canonical_json


@dataclass(frozen=True, slots=True)
class ProposalRecord:
    proposal_id: str
    import_run_id: str
    proposal_kind: str
    target_kind: str
    target_internal_id: str | None
    target_business_id: str | None
    risk_class: str
    base_state_token: str
    proposal_fingerprint: str
    proposal_state: str
    revision: int


@dataclass(frozen=True, slots=True)
class ImportRunDecisionState:
    import_run_id: str
    source_family: str
    run_state: str
    candidate_chronology_kind: str
    candidate_chronology_value: int
    logical_fingerprint: str
    pending_count: int
    rejected_count: int
    deferred_count: int
    revision: int


class ProposalRepository:
    @staticmethod
    def get(reader: Any, proposal_id: str) -> ProposalRecord | None:
        row = reader.execute(
            "SELECT reconciliation_proposal_id,import_run_id,proposal_kind,target_kind,target_internal_id,"
            "target_business_id,risk_class,base_state_token_sha256,proposal_fingerprint_sha256,proposal_state,revision "
            "FROM reconciliation_proposals WHERE reconciliation_proposal_id=?",
            (proposal_id,),
        ).fetchone()
        if row is None:
            return None
        return ProposalRecord(
            proposal_id=str(row[0]),
            import_run_id=str(row[1]),
            proposal_kind=str(row[2]),
            target_kind=str(row[3]),
            target_internal_id=None if row[4] is None else str(row[4]),
            target_business_id=None if row[5] is None else str(row[5]),
            risk_class=str(row[6]),
            base_state_token=str(row[7]),
            proposal_fingerprint=str(row[8]),
            proposal_state=str(row[9]),
            revision=int(row[10]),
        )

    @staticmethod
    def require_pending(reader: Any, proposal_id: str) -> ProposalRecord:
        proposal = ProposalRepository.get(reader, proposal_id)
        if proposal is None:
            raise SomaError("IMPORT_PROPOSAL_NOT_FOUND", "reconciliation proposal does not exist")
        if proposal.proposal_state != "pending":
            raise SomaError("IMPORT_PROPOSAL_STALE", "reconciliation proposal is no longer pending")
        return proposal

    @staticmethod
    def get_run(reader: Any, import_run_id: str) -> ImportRunDecisionState:
        row = reader.execute(
            "SELECT import_run_id,source_family,run_state,candidate_chronology_kind,candidate_chronology_value,"
            "logical_fingerprint_sha256,pending_proposal_count,rejected_proposal_count,deferred_proposal_count,revision "
            "FROM import_runs WHERE import_run_id=?",
            (import_run_id,),
        ).fetchone()
        if row is None:
            raise SomaError("IMPORT_RUN_NOT_FOUND", "parent import run does not exist")
        if row[5] is None:
            raise SomaError("IMPORT_RUN_UNPUBLISHED", "proposal parent run is not published")
        return ImportRunDecisionState(
            import_run_id=str(row[0]),
            source_family=str(row[1]),
            run_state=str(row[2]),
            candidate_chronology_kind=str(row[3]),
            candidate_chronology_value=int(row[4]),
            logical_fingerprint=str(row[5]),
            pending_count=int(row[6]),
            rejected_count=int(row[7]),
            deferred_count=int(row[8]),
            revision=int(row[9]),
        )

    @staticmethod
    def material_equivalence_fingerprint(proposal: ProposalRecord) -> str:
        return sha256_canonical_json(
            {
                "schema": "IMPORT_PROPOSAL_EQUIVALENCE_V1",
                "proposal_kind": proposal.proposal_kind,
                "target_kind": proposal.target_kind,
                "target_internal_id": proposal.target_internal_id,
                "target_business_id": proposal.target_business_id,
                "base_state_token": proposal.base_state_token,
                "proposal_fingerprint": proposal.proposal_fingerprint,
            }
        )

    @staticmethod
    def recovery_review_fingerprint(reader: Any, run: ImportRunDecisionState) -> str:
        checkpoint = reader.execute(
            "SELECT accepted_import_run_id,accepted_candidate_chronology_kind,accepted_candidate_chronology_value,"
            "accepted_logical_fingerprint_sha256,revision FROM import_source_checkpoints WHERE source_family=?",
            (run.source_family,),
        ).fetchone()
        if checkpoint is None:
            raise SomaError("IMPORT_RECOVERY_REVIEW_STALE", "recovery run has no current source checkpoint")
        pending_rows = reader.execute(
            "SELECT reconciliation_proposal_id,revision,base_state_token_sha256,proposal_fingerprint_sha256 "
            "FROM reconciliation_proposals WHERE import_run_id=? AND proposal_state='pending' "
            "ORDER BY reconciliation_proposal_id ASC",
            (run.import_run_id,),
        ).fetchall()
        return sha256_canonical_json(
            {
                "schema": "IMPORT_RECOVERY_REVIEW_V1",
                "run": {
                    "import_run_id": run.import_run_id,
                    "revision": run.revision,
                    "chronology_kind": run.candidate_chronology_kind,
                    "chronology_value": run.candidate_chronology_value,
                    "logical_fingerprint": run.logical_fingerprint,
                },
                "checkpoint": {
                    "import_run_id": str(checkpoint[0]),
                    "revision": int(checkpoint[4]),
                    "chronology_kind": str(checkpoint[1]),
                    "chronology_value": int(checkpoint[2]),
                    "logical_fingerprint": str(checkpoint[3]),
                },
                "pending_proposals": [
                    {
                        "proposal_id": str(row[0]),
                        "revision": int(row[1]),
                        "base_state_token": str(row[2]),
                        "proposal_fingerprint": str(row[3]),
                    }
                    for row in pending_rows
                ],
            }
        )

    @staticmethod
    def require_current_recovery_authorization(reader: Any, run: ImportRunDecisionState) -> None:
        if run.run_state != "recovery_required":
            return
        current_fingerprint = ProposalRepository.recovery_review_fingerprint(reader, run)
        review = reader.execute(
            "SELECT review_fingerprint_sha256,decision FROM import_recovery_reviews "
            "WHERE import_run_id=? ORDER BY review_ordinal DESC LIMIT 1",
            (run.import_run_id,),
        ).fetchone()
        if review is None or str(review[0]) != current_fingerprint or str(review[1]) != "authorized":
            raise SomaError(
                "IMPORT_RECOVERY_REVIEW_STALE",
                "recovery proposal decision requires the latest exact authorized review",
            )

    @staticmethod
    def transition_decision(
        uow: UnitOfWork,
        *,
        proposal: ProposalRecord,
        run: ImportRunDecisionState,
        decision: str,
        decided_at_utc: int,
        disposition_id: str,
        equivalence_id: str,
        reason_category: str,
        command_id: str,
    ) -> None:
        if decision not in {"rejected", "deferred"}:
            raise SomaError("VALIDATION_ERROR", "decision must be rejected or deferred")
        proposal_update = uow.connection.execute(
            "UPDATE reconciliation_proposals SET proposal_state=?,revision=revision+1,decided_at_utc=? "
            "WHERE reconciliation_proposal_id=? AND proposal_state='pending' AND revision=?",
            (decision, decided_at_utc, proposal.proposal_id, proposal.revision),
        )
        if proposal_update.rowcount != 1:
            raise SomaError("IMPORT_PROPOSAL_STALE", "reconciliation proposal changed before decision commit")

        uow.connection.execute(
            "INSERT INTO proposal_dispositions(proposal_disposition_id,reconciliation_proposal_id,decision,proposal_revision,"
            "proposal_fingerprint_sha256,base_state_token_sha256,reason_category,decision_origin,occurred_at_utc,command_id) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, 'operator', ?, ?)",
            (
                disposition_id,
                proposal.proposal_id,
                decision,
                proposal.revision,
                proposal.proposal_fingerprint,
                proposal.base_state_token,
                reason_category,
                decided_at_utc,
                command_id,
            ),
        )
        uow.connection.execute(
            "INSERT INTO proposal_equivalence_decisions(proposal_equivalence_decision_id,proposal_kind,target_internal_id,"
            "target_business_id,material_input_fingerprint_sha256,decision,source_proposal_id,created_at_utc,command_id) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                equivalence_id,
                proposal.proposal_kind,
                proposal.target_internal_id,
                proposal.target_business_id,
                ProposalRepository.material_equivalence_fingerprint(proposal),
                decision,
                proposal.proposal_id,
                decided_at_utc,
                command_id,
            ),
        )

        counter_column = "rejected_proposal_count" if decision == "rejected" else "deferred_proposal_count"
        target_state = "recovery_required" if run.run_state == "recovery_required" else "waiting_review"
        run_update = uow.connection.execute(
            f"UPDATE import_runs SET run_state=?,pending_proposal_count=pending_proposal_count-1,"
            f"{counter_column}={counter_column}+1,revision=revision+1 "
            "WHERE import_run_id=? AND revision=? AND pending_proposal_count>0 AND run_state IN ('staged','waiting_review','recovery_required')",
            (target_state, run.import_run_id, run.revision),
        )
        if run_update.rowcount != 1:
            raise SomaError("IMPORT_PROPOSAL_STALE", "parent import run changed before proposal decision commit")
