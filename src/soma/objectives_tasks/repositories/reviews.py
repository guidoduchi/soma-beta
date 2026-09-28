from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from soma.foundation.errors import IntegrityFailure
from soma.foundation.identifiers import new_uuid4, utc_epoch_seconds
from soma.foundation.persistence.uow import UnitOfWork


@dataclass(frozen=True, slots=True)
class HistoricalObjectiveProposalRecord:
    proposal_id: str
    task_id: str
    expected_source_projection_revision: int
    expected_source_plan_start_utc: int
    expected_source_plan_end_utc: int
    expected_source_observation_id: str
    expected_matching_operational_plan_revision_id: str | None
    input_fingerprint: str
    state: str
    revision: int
    created_at_utc: int
    last_command_id: str | None


class HistoricalObjectiveProposalRepository:
    @staticmethod
    def get(reader: Any, proposal_id: str) -> HistoricalObjectiveProposalRecord | None:
        row = reader.execute(
            "SELECT historical_proposal_id,task_id,"
            "expected_wfm_source_projection_revision,"
            "expected_source_plan_start_utc,expected_source_plan_end_utc,"
            "expected_source_observation_id,"
            "expected_matching_operational_plan_revision_id,input_fingerprint,"
            "state,revision,created_at_utc,last_command_id "
            "FROM historical_objective_proposals WHERE historical_proposal_id=?",
            (proposal_id,),
        ).fetchone()
        if row is None:
            return None
        return HistoricalObjectiveProposalRecord(
            proposal_id=str(row[0]),
            task_id=str(row[1]),
            expected_source_projection_revision=int(row[2]),
            expected_source_plan_start_utc=int(row[3]),
            expected_source_plan_end_utc=int(row[4]),
            expected_source_observation_id=str(row[5]),
            expected_matching_operational_plan_revision_id=(
                None if row[6] is None else str(row[6])
            ),
            input_fingerprint=str(row[7]),
            state=str(row[8]),
            revision=int(row[9]),
            created_at_utc=int(row[10]),
            last_command_id=None if row[11] is None else str(row[11]),
        )

    @classmethod
    def insert_pending(
        cls,
        uow: UnitOfWork,
        *,
        task_id: str,
        expected_source_projection_revision: int,
        expected_source_plan_start_utc: int,
        expected_source_plan_end_utc: int,
        expected_source_observation_id: str,
        expected_matching_operational_plan_revision_id: str | None,
        input_fingerprint: str,
        created_at_utc: int | None = None,
    ) -> HistoricalObjectiveProposalRecord:
        proposal_id = new_uuid4()
        created = utc_epoch_seconds() if created_at_utc is None else created_at_utc
        uow.connection.execute(
            "INSERT INTO historical_objective_proposals("
            "historical_proposal_id,task_id,"
            "expected_wfm_source_projection_revision,"
            "expected_source_plan_start_utc,expected_source_plan_end_utc,"
            "expected_source_observation_id,"
            "expected_matching_operational_plan_revision_id,input_fingerprint,"
            "state,revision,created_at_utc,last_command_id"
            ") VALUES (?,?,?,?,?,?,?,?,'pending',1,?,NULL)",
            (
                proposal_id,
                task_id,
                expected_source_projection_revision,
                expected_source_plan_start_utc,
                expected_source_plan_end_utc,
                expected_source_observation_id,
                expected_matching_operational_plan_revision_id,
                input_fingerprint,
                created,
            ),
        )
        record = cls.get(uow.connection, proposal_id)
        if record is None:
            raise IntegrityFailure(
                "historical Objective proposal did not persist"
            )
        return record

    @classmethod
    def current_for_fingerprint(
        cls,
        reader: Any,
        *,
        task_id: str,
        input_fingerprint: str,
    ) -> HistoricalObjectiveProposalRecord | None:
        row = reader.execute(
            "SELECT historical_proposal_id FROM historical_objective_proposals "
            "WHERE task_id=? AND input_fingerprint=? "
            "AND state IN ('pending','rejected','accepted') "
            "ORDER BY created_at_utc DESC,historical_proposal_id DESC LIMIT 1",
            (task_id, input_fingerprint),
        ).fetchone()
        return None if row is None else cls.get(reader, str(row[0]))

    @staticmethod
    def supersede_pending_except(
        uow: UnitOfWork,
        *,
        task_id: str,
        command_id: str,
        keep_fingerprint: str | None,
    ) -> int:
        if keep_fingerprint is None:
            changed = uow.connection.execute(
                "UPDATE historical_objective_proposals "
                "SET state='superseded',revision=revision+1,last_command_id=? "
                "WHERE task_id=? AND state='pending'",
                (command_id, task_id),
            )
        else:
            changed = uow.connection.execute(
                "UPDATE historical_objective_proposals "
                "SET state='superseded',revision=revision+1,last_command_id=? "
                "WHERE task_id=? AND state='pending' AND input_fingerprint<>?",
                (command_id, task_id, keep_fingerprint),
            )
        return int(changed.rowcount)

    @staticmethod
    def transition(
        uow: UnitOfWork,
        *,
        proposal_id: str,
        expected_revision: int,
        expected_fingerprint: str,
        new_state: str,
        command_id: str,
    ) -> int:
        changed = uow.connection.execute(
            "UPDATE historical_objective_proposals "
            "SET state=?,revision=revision+1,last_command_id=? "
            "WHERE historical_proposal_id=? AND state='pending' "
            "AND revision=? AND input_fingerprint=?",
            (
                new_state,
                command_id,
                proposal_id,
                expected_revision,
                expected_fingerprint,
            ),
        )
        if changed.rowcount != 1:
            raise IntegrityFailure(
                "historical Objective proposal changed during guarded transition"
            )
        return expected_revision + 1


__all__ = [
    "HistoricalObjectiveProposalRecord",
    "HistoricalObjectiveProposalRepository",
]
