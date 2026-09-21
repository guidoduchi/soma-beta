from __future__ import annotations

from typing import Any

from soma.foundation.errors import IntegrityFailure, SomaError, ValidationError
from soma.foundation.identifiers import require_uuid4
from soma.foundation.persistence.connections import ConnectionFactory
from soma.foundation.persistence.uow import ReadSnapshot
from soma.foundation.strict_json import sha256_canonical_json


class RfcTerminalCascadeQueryService:
    """Pure complete-set LLD-05 Task/Objective impact authority."""

    def __init__(self, connection_factory: ConnectionFactory) -> None:
        self._factory = connection_factory

    @staticmethod
    def _indeterminate(proposal_id: str, warning_code: str) -> dict[str, object]:
        return {
            "domain": "TASKS_OBJECTIVES",
            "classification": "INDETERMINATE",
            "status": "INDETERMINATE",
            "warning_code": warning_code,
            "proposal_id": proposal_id,
            "exact_count": None,
            "provider_fingerprint": None,
            "items": [],
            "continuation_key": None,
            "captured_wfms": [],
            "objective_impacts": [],
        }

    @classmethod
    def preview_with_reader(
        cls,
        reader: Any,
        proposal_id: str,
    ) -> dict[str, object]:
        identity = require_uuid4(proposal_id)
        proposal = reader.execute(
            "SELECT trigger_rfc_id,terminal_epoch_id,terminal_status_class,"
            "terminal_status_evidence_id,scope_kind,scope_fingerprint,proposal_state,revision "
            "FROM rfc_terminal_cascade_proposals "
            "WHERE rfc_terminal_cascade_proposal_id=?",
            (identity,),
        ).fetchone()
        if proposal is None:
            raise SomaError(
                "RFC_TERMINAL_CASCADE_NOT_FOUND",
                "RFC terminal cascade proposal is missing",
            )
        if str(proposal[6]) != "pending":
            return cls._indeterminate(identity, "RFC_TERMINAL_CASCADE_NOT_PENDING")

        captured = reader.execute(
            "SELECT m.task_id,m.owning_rfc_id,m.captured_task_revision,"
            "m.captured_task_no,m.ordinal,t.revision,w.task_no,w.current_rfc_id,"
            "COALESCE(e.revision,0),COALESCE(e.execution_state,'not_started'),"
            "CASE WHEN oc.task_id IS NULL THEN 0 ELSE 1 END "
            "FROM rfc_terminal_cascade_wfm_members m "
            "LEFT JOIN tasks t ON t.task_id=m.task_id "
            "LEFT JOIN wfm_task_identities w ON w.task_id=m.task_id "
            "LEFT JOIN task_execution_projection e ON e.task_id=m.task_id "
            "LEFT JOIN task_outcome_current oc ON oc.task_id=m.task_id "
            "WHERE m.rfc_terminal_cascade_proposal_id=? "
            "ORDER BY m.ordinal,m.task_id",
            (identity,),
        ).fetchall()
        if len({int(row[4]) for row in captured}) != len(captured):
            raise IntegrityFailure("RFC cascade captured WFM ordinals are not unique")

        captured_rows: list[dict[str, object]] = []
        task_ids: list[str] = []
        impact_items: list[dict[str, object]] = []
        for row in captured:
            task_id = str(row[0])
            try:
                require_uuid4(task_id)
            except ValidationError:
                return cls._indeterminate(identity, "CAPTURED_TASK_ID_INVALID")
            if (
                row[5] is None
                or row[6] is None
                or row[7] is None
                or int(row[5]) != int(row[2])
                or str(row[6]) != str(row[3])
                or str(row[7]) != str(row[1])
            ):
                return cls._indeterminate(identity, "CAPTURED_WFM_STALE")
            execution_revision = int(row[8])
            execution_state = str(row[9])
            has_outcome = int(row[10]) == 1
            if execution_state not in {"not_started", "in_progress"} or has_outcome:
                return cls._indeterminate(identity, "CAPTURED_WFM_NOT_LOCALLY_ACTIVE")
            task_ids.append(task_id)
            authority = {
                "task_id": task_id,
                "owning_rfc_id": str(row[1]),
                "task_revision": int(row[2]),
                "task_no": str(row[3]),
                "ordinal": int(row[4]),
                "execution_revision": execution_revision,
                "execution_state": execution_state,
            }
            captured_rows.append(authority)
            impact_items.append(
                {
                    "domain": "TASKS_OBJECTIVES",
                    "impact_kind": "WFM_TERMINATION",
                    "entity_type": "WFM_TASK",
                    "entity_id": task_id,
                    "current_state": execution_state,
                    "resulting_state": "terminated",
                    "current_count": None,
                    "resulting_count": None,
                    "attention_code": None,
                }
            )

        captured_set = set(task_ids)
        affected_ids = [
            str(row[0])
            for row in reader.execute(
                "SELECT DISTINCT m.objective_id "
                "FROM objective_task_membership_current m "
                "JOIN rfc_terminal_cascade_wfm_members c ON c.task_id=m.task_id "
                "WHERE c.rfc_terminal_cascade_proposal_id=? "
                "ORDER BY m.objective_id",
                (identity,),
            ).fetchall()
        ]
        objective_impacts: list[dict[str, object]] = []
        for objective_id in affected_ids:
            obj = reader.execute(
                "SELECT o.revision,a.execution_state,a.revision,"
                "a.aggregate_input_fingerprint "
                "FROM objectives o JOIN objective_aggregate_projection a "
                "ON a.objective_id=o.objective_id WHERE o.objective_id=?",
                (objective_id,),
            ).fetchone()
            if obj is None:
                return cls._indeterminate(identity, "OBJECTIVE_AUTHORITY_MISSING")
            members = reader.execute(
                "SELECT m.task_id,COALESCE(e.execution_state,'not_started'),"
                "CASE WHEN oc.task_id IS NULL THEN 0 ELSE 1 END "
                "FROM objective_task_membership_current m "
                "LEFT JOIN task_execution_projection e ON e.task_id=m.task_id "
                "LEFT JOIN task_outcome_current oc ON oc.task_id=m.task_id "
                "WHERE m.objective_id=? ORDER BY m.task_id",
                (objective_id,),
            ).fetchall()
            current_executable = sum(
                1
                for row in members
                if str(row[1]) not in {"ended", "terminated"} and int(row[2]) == 0
            )
            resulting_executable = sum(
                1
                for row in members
                if str(row[0]) not in captured_set
                and str(row[1]) not in {"ended", "terminated"}
                and int(row[2]) == 0
            )
            affected_tasks = [
                str(row[0]) for row in members if str(row[0]) in captured_set
            ]
            attention = (
                "LOST_LAST_EXECUTABLE"
                if current_executable > 0
                and resulting_executable == 0
                and str(obj[1]) == "in_progress"
                else None
            )
            item = {
                "objective_id": objective_id,
                "objective_revision": int(obj[0]),
                "aggregate_revision": int(obj[2]),
                "aggregate_input_fingerprint": str(obj[3]),
                "execution_state": str(obj[1]),
                "affected_task_ids": affected_tasks,
                "current_executable_count": current_executable,
                "resulting_executable_count": resulting_executable,
                "attention_code": attention,
            }
            objective_impacts.append(item)
            impact_items.append(
                {
                    "domain": "TASKS_OBJECTIVES",
                    "impact_kind": "OBJECTIVE_EXECUTABLE_COUNT",
                    "entity_type": "OBJECTIVE",
                    "entity_id": objective_id,
                    "current_state": None,
                    "resulting_state": None,
                    "current_count": current_executable,
                    "resulting_count": resulting_executable,
                    "attention_code": attention,
                }
            )

        impact_items.sort(
            key=lambda item: (
                str(item["impact_kind"]).encode("utf-8"),
                str(item["entity_id"]).encode("utf-8"),
            )
        )
        material = {
            "schema": "SOMA_RFC_TERMINAL_TASK_IMPACT_V1",
            "proposal": {
                "proposal_id": identity,
                "revision": int(proposal[7]),
                "trigger_rfc_id": str(proposal[0]),
                "terminal_epoch_id": str(proposal[1]),
                "terminal_status_class": str(proposal[2]),
                "terminal_status_evidence_id": str(proposal[3]),
                "scope_kind": str(proposal[4]),
                "scope_fingerprint": str(proposal[5]),
            },
            "captured_wfms": captured_rows,
            "objective_impacts": objective_impacts,
            "impact_items": impact_items,
        }
        return {
            "domain": "TASKS_OBJECTIVES",
            "classification": "READY",
            "status": "READY",
            "warning_code": None,
            "proposal_id": identity,
            "proposal_revision": int(proposal[7]),
            "scope_fingerprint": str(proposal[5]),
            "exact_count": len(impact_items),
            "provider_fingerprint": sha256_canonical_json(material),
            "items": impact_items,
            "continuation_key": None,
            "captured_wfms": captured_rows,
            "affected_objective_ids": affected_ids,
            "objective_impacts": objective_impacts,
        }

    def preview(self, proposal_id: str) -> dict[str, object]:
        with ReadSnapshot(self._factory) as snapshot:
            return self.preview_with_reader(snapshot.connection, proposal_id)


__all__ = ["RfcTerminalCascadeQueryService"]
