from __future__ import annotations

from dataclasses import dataclass

from soma.foundation.errors import IntegrityFailure, SomaError
from soma.foundation.identifiers import require_uuid4
from soma.foundation.persistence.connections import ConnectionFactory
from soma.foundation.persistence.uow import ReadSnapshot
from soma.objectives_tasks.services.wfm_import import WfmImportBaseTarget, WfmImportReader

from ..repositories.proposals import ProposalRepository


@dataclass(frozen=True, slots=True)
class WfmPlanReviewContext:
    proposal_id: str
    source_plan: dict[str, int]
    operational_plan: dict[str, object] | None
    plan_diff: dict[str, object]
    source_chronology: int | None
    objective_regrouping_consequence: str
    base_state_token: str

    def to_response(self) -> dict[str, object]:
        return {
            "proposal_id": self.proposal_id,
            "source_plan": dict(self.source_plan),
            "operational_plan": None if self.operational_plan is None else dict(self.operational_plan),
            "plan_diff": dict(self.plan_diff),
            "source_chronology": self.source_chronology,
            "objective_regrouping_consequence": self.objective_regrouping_consequence,
            "base_state_token": self.base_state_token,
        }


def _plan_diff(
    source_plan: dict[str, int],
    operational_plan: dict[str, object] | None,
) -> dict[str, object]:
    source_start = source_plan.get("start_utc")
    source_end = source_plan.get("end_utc")
    if type(source_start) is not int or type(source_end) is not int or source_start < 0 or source_end <= source_start:
        raise IntegrityFailure("WFM source plan projection is invalid")

    operational_start: int | None = None
    operational_end: int | None = None
    if operational_plan is not None:
        start = operational_plan.get("start_utc")
        end = operational_plan.get("end_utc")
        if type(start) is not int or type(end) is not int or start < 0 or end <= start:
            raise IntegrityFailure("WFM operational plan projection is invalid")
        operational_start = start
        operational_end = end

    return {
        "start": {
            "source_utc": source_start,
            "operational_utc": operational_start,
            "changed": source_start != operational_start,
        },
        "end": {
            "source_utc": source_end,
            "operational_utc": operational_end,
            "changed": source_end != operational_end,
        },
    }


class WfmPlanReviewQueryService:
    """Read-only LLD-04 WFM plan-review context projected through LLD-05 owner readers."""

    def __init__(self, connection_factory: ConnectionFactory) -> None:
        self._factory = connection_factory
        self._proposals = ProposalRepository()

    def get_context(self, proposal_id: str) -> WfmPlanReviewContext:
        canonical_id = require_uuid4(proposal_id)
        with ReadSnapshot(self._factory) as snapshot:
            proposal = self._proposals.get(snapshot.connection, canonical_id)
            if proposal is None:
                raise SomaError("IMPORT_PROPOSAL_NOT_FOUND", "reconciliation proposal does not exist")
            if proposal.proposal_kind != "wfm_plan_reconciliation":
                raise SomaError("IMPORT_PROPOSAL_KIND_INVALID", "proposal is not a WFM plan reconciliation")
            if (
                proposal.evidence_mode != "observed_row"
                or proposal.source_observation_id is None
                or proposal.target_kind != "task_plan"
                or proposal.target_internal_id is None
                or proposal.target_business_id is None
                or proposal.risk_class != "high"
            ):
                raise IntegrityFailure("WFM plan reconciliation proposal binding is invalid")

            source_row = snapshot.connection.execute(
                "SELECT import_run_id,source_family,entity_kind,identity_state,canonical_primary_id,"
                "source_row_chronology_utc FROM source_observations WHERE source_observation_id=?",
                (proposal.source_observation_id,),
            ).fetchone()
            if source_row is None:
                raise IntegrityFailure("WFM plan reconciliation source observation is missing")
            if (
                str(source_row[0]) != proposal.import_run_id
                or str(source_row[1]) != "wfm_service_provider"
                or str(source_row[2]) != "wfm"
                or str(source_row[3]) != "valid"
                or str(source_row[4]) != proposal.target_business_id
            ):
                raise IntegrityFailure("WFM plan reconciliation source observation binding is invalid")
            source_chronology = None if source_row[5] is None else int(source_row[5])
            if source_chronology is not None and source_chronology < 0:
                raise IntegrityFailure("WFM plan reconciliation source chronology is invalid")

            identity = WfmImportReader.get_by_task_no(snapshot.connection, proposal.target_business_id)
            if identity is None or identity.get("task_id") != proposal.target_internal_id:
                raise IntegrityFailure("WFM plan reconciliation target identity is no longer owner-authoritative")

            source_plan = WfmImportReader.source_plan(snapshot.connection, proposal.target_internal_id)
            if source_plan is None:
                raise IntegrityFailure("WFM plan reconciliation has no current source-plan authority")
            operational_plan = WfmImportReader.operational_plan_context(
                snapshot.connection,
                proposal.target_internal_id,
            )

            # Recompute only as an integrity/readiness check. The response returns the immutable
            # reviewed proposal token, not a silently refreshed authorization token.
            WfmImportReader.source_acceptance_base_token(
                snapshot.connection,
                WfmImportBaseTarget(
                    "wfm_plan_reconciliation",
                    proposal.target_business_id,
                    proposal.target_internal_id,
                ),
            )

            return WfmPlanReviewContext(
                proposal_id=proposal.proposal_id,
                source_plan=dict(source_plan),
                operational_plan=None if operational_plan is None else dict(operational_plan),
                plan_diff=_plan_diff(source_plan, operational_plan),
                source_chronology=source_chronology,
                # LLD-04 has no declared LLD-05 reader that proves a stronger regrouping outcome.
                # Fail conservative rather than reading owner-private Objective tables directly.
                objective_regrouping_consequence="INDETERMINATE",
                base_state_token=proposal.base_state_token,
            )


__all__ = ["WfmPlanReviewContext", "WfmPlanReviewQueryService"]
