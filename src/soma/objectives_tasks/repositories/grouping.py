from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from soma.foundation.errors import IntegrityFailure, SomaError
from soma.foundation.identifiers import new_uuid4, utc_epoch_seconds

from ..domain.grouping import RegroupCandidate


@dataclass(frozen=True, slots=True)
class RegroupProposalRecord:
    proposal_id: str
    proposal_kind: str
    origin: str
    risk_tier: str
    input_fingerprint: str
    state: str
    survivor_objective_id: str | None
    revision: int
    created_at_utc: int


class RegroupProposalRepository:
    @staticmethod
    def get(reader: Any, proposal_id: str) -> RegroupProposalRecord | None:
        row = reader.execute(
            "SELECT regroup_proposal_id,proposal_kind,origin,risk_tier,input_fingerprint,"
            "state,survivor_objective_id,revision,created_at_utc "
            "FROM regroup_proposals WHERE regroup_proposal_id=?",
            (proposal_id,),
        ).fetchone()
        if row is None:
            return None
        return RegroupProposalRecord(
            proposal_id=str(row[0]),
            proposal_kind=str(row[1]),
            origin=str(row[2]),
            risk_tier=str(row[3]),
            input_fingerprint=str(row[4]),
            state=str(row[5]),
            survivor_objective_id=None if row[6] is None else str(row[6]),
            revision=int(row[7]),
            created_at_utc=int(row[8]),
        )

    @staticmethod
    def exact_pending_by_fingerprint(reader: Any, fingerprint: str):
        return reader.execute(
            "SELECT regroup_proposal_id FROM regroup_proposals "
            "WHERE state='pending' AND input_fingerprint=? "
            "ORDER BY created_at_utc,regroup_proposal_id LIMIT 1",
            (fingerprint,),
        ).fetchone()

    @staticmethod
    def rejection_suppressed(reader: Any, fingerprint: str) -> bool:
        return reader.execute(
            "SELECT 1 FROM regroup_rejection_events "
            "WHERE input_fingerprint=? AND reconsidered_at_utc IS NULL LIMIT 1",
            (fingerprint,),
        ).fetchone() is not None

    @classmethod
    def insert_candidate(
        cls,
        connection: Any,
        *,
        candidate: RegroupCandidate,
        command_id: str,
    ) -> str:
        proposal_id = new_uuid4()
        now = utc_epoch_seconds()
        connection.execute(
            "INSERT INTO regroup_proposals("
            "regroup_proposal_id,proposal_kind,origin,risk_tier,input_fingerprint,state,"
            "survivor_objective_id,revision,created_at_utc,last_command_id"
            ") VALUES (?,?,?,?,?,'pending',?,1,?,?)",
            (
                proposal_id,
                candidate.proposal_kind,
                candidate.origin,
                candidate.risk_tier,
                candidate.input_fingerprint,
                candidate.survivor_objective_id,
                now,
                command_id,
            ),
        )
        for change in candidate.task_changes:
            connection.execute(
                "INSERT INTO regroup_proposal_task_changes("
                "proposal_task_change_id,regroup_proposal_id,task_id,from_objective_id,"
                "to_objective_id,expected_task_revision,expected_current_plan_revision_id,"
                "expected_membership_revision,change_kind"
                ") VALUES (?,?,?,?,?,?,?,?,?)",
                (
                    new_uuid4(),
                    proposal_id,
                    change.task_id,
                    change.from_objective_id,
                    change.to_objective_id,
                    change.expected_task_revision,
                    change.expected_current_plan_revision_id,
                    change.expected_membership_revision,
                    change.change_kind,
                ),
            )
        for change in candidate.objective_changes:
            connection.execute(
                "INSERT INTO regroup_proposal_objective_changes("
                "proposal_objective_change_id,regroup_proposal_id,objective_id,action,"
                "expected_objective_revision,expected_envelope_revision"
                ") VALUES (?,?,?,?,?,?)",
                (
                    new_uuid4(),
                    proposal_id,
                    change.objective_id,
                    change.action,
                    change.expected_objective_revision,
                    change.expected_envelope_revision,
                ),
            )
        return proposal_id

    @staticmethod
    def task_changes(reader: Any, proposal_id: str):
        return reader.execute(
            "SELECT proposal_task_change_id,task_id,from_objective_id,to_objective_id,"
            "expected_task_revision,expected_current_plan_revision_id,"
            "expected_membership_revision,change_kind "
            "FROM regroup_proposal_task_changes WHERE regroup_proposal_id=? "
            "ORDER BY task_id,proposal_task_change_id",
            (proposal_id,),
        ).fetchall()

    @staticmethod
    def objective_changes(reader: Any, proposal_id: str):
        return reader.execute(
            "SELECT proposal_objective_change_id,objective_id,action,"
            "expected_objective_revision,expected_envelope_revision "
            "FROM regroup_proposal_objective_changes WHERE regroup_proposal_id=? "
            "ORDER BY COALESCE(objective_id,''),proposal_objective_change_id",
            (proposal_id,),
        ).fetchall()

    @staticmethod
    def transition(
        connection: Any,
        *,
        proposal_id: str,
        expected_revision: int,
        expected_fingerprint: str,
        new_state: str,
        command_id: str,
    ) -> int:
        if new_state not in {"accepted", "rejected", "superseded"}:
            raise IntegrityFailure("invalid regroup proposal transition")
        changed = connection.execute(
            "UPDATE regroup_proposals SET state=?,revision=revision+1,last_command_id=? "
            "WHERE regroup_proposal_id=? AND state='pending' AND revision=? "
            "AND input_fingerprint=?",
            (
                new_state,
                command_id,
                proposal_id,
                expected_revision,
                expected_fingerprint,
            ),
        )
        if changed.rowcount != 1:
            raise SomaError("GROUPING_PROPOSAL_STALE", "regroup proposal changed")
        return expected_revision + 1

    @staticmethod
    def reject(
        connection: Any,
        *,
        proposal_id: str,
        expected_revision: int,
        expected_fingerprint: str,
        reason_code: str,
        command_id: str,
    ) -> tuple[str, int]:
        rejection_id = new_uuid4()
        now = utc_epoch_seconds()
        next_revision = RegroupProposalRepository.transition(
            connection,
            proposal_id=proposal_id,
            expected_revision=expected_revision,
            expected_fingerprint=expected_fingerprint,
            new_state="rejected",
            command_id=command_id,
        )
        connection.execute(
            "INSERT INTO regroup_rejection_events("
            "rejection_event_id,regroup_proposal_id,input_fingerprint,reason_code,"
            "reconsidered_at_utc,recorded_at_utc,command_id"
            ") VALUES (?,?,?,?,NULL,?,?)",
            (
                rejection_id,
                proposal_id,
                expected_fingerprint,
                reason_code,
                now,
                command_id,
            ),
        )
        return rejection_id, next_revision

    @staticmethod
    def reconsider_rejection(
        connection: Any,
        *,
        proposal_id: str,
        input_fingerprint: str,
        reason_code: str,
        command_id: str,
    ) -> str:
        row = connection.execute(
            "SELECT rejection_event_id FROM regroup_rejection_events "
            "WHERE regroup_proposal_id=? AND input_fingerprint=? "
            "AND reconsidered_at_utc IS NULL "
            "ORDER BY recorded_at_utc DESC,rejection_event_id DESC LIMIT 1",
            (proposal_id, input_fingerprint),
        ).fetchone()
        if row is None:
            raise SomaError(
                "GROUPING_EQUIVALENT_REJECTION",
                "exact regroup rejection is absent or already reconsidered",
            )
        rejection_id = str(row[0])
        changed = connection.execute(
            "UPDATE regroup_rejection_events SET reconsidered_at_utc=? "
            "WHERE rejection_event_id=? AND reconsidered_at_utc IS NULL",
            (utc_epoch_seconds(), rejection_id),
        )
        if changed.rowcount != 1:
            raise SomaError(
                "GROUPING_EQUIVALENT_REJECTION",
                "regroup rejection was already reconsidered",
            )
        return rejection_id


__all__ = ["RegroupProposalRecord", "RegroupProposalRepository"]
