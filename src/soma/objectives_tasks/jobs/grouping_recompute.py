from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from soma.foundation.audit.writer import AuditEventInput, AuditResultRef, AuditWriter
from soma.foundation.contracts.foundation import DurableJobClaim
from soma.foundation.errors import IntegrityFailure, ValidationError
from soma.foundation.identifiers import new_uuid4
from soma.foundation.jobs import DurableJobCoordinator, JobTypeRegistry
from soma.foundation.persistence.connections import ConnectionFactory
from soma.foundation.persistence.uow import ReadSnapshot, UnitOfWork
from soma.foundation.strict_json import loads_canonical_json

from ..audit_registry import build_objectives_tasks_audit_registry
from ..repositories.grouping import RegroupProposalRepository
from ..services.grouping import GroupingService
from . import (
    GROUPING_RECOMPUTE_JOB_CONTRACT_VERSION,
    GROUPING_RECOMPUTE_JOB_TYPE,
    OBJECTIVES_TASKS_JOB_CONTRACTS,
    validate_grouping_recompute_payload,
)

_JOB_JSON_BYTES = 65_536


@dataclass(frozen=True, slots=True)
class GroupingRecomputeJobRunResult:
    job_id: str
    origin: str
    candidate_exact_count: int
    published_proposal_count: int


class ObjectiveGroupingRecomputeWorker:
    """Durable T039 grouping calculator and non-authoritative proposal publisher."""

    def __init__(self, connection_factory: ConnectionFactory) -> None:
        self._factory = connection_factory
        self._jobs = DurableJobCoordinator(
            connection_factory,
            JobTypeRegistry(OBJECTIVES_TASKS_JOB_CONTRACTS),
        )
        self._audit = AuditWriter(build_objectives_tasks_audit_registry())

    @staticmethod
    def _payload(claim: DurableJobClaim) -> dict[str, Any]:
        if (
            claim.job_type != GROUPING_RECOMPUTE_JOB_TYPE
            or claim.contract_version != GROUPING_RECOMPUTE_JOB_CONTRACT_VERSION
        ):
            raise ValidationError("claim is not OBJECTIVE_GROUPING_RECOMPUTE_V1")
        value = loads_canonical_json(
            claim.payload_json,
            max_bytes=_JOB_JSON_BYTES,
            max_depth=3,
            max_collection_items=8,
        )
        if not isinstance(value, dict):
            raise IntegrityFailure("persisted grouping recompute payload must be an object")
        try:
            validate_grouping_recompute_payload(value)
        except ValidationError as exc:
            raise IntegrityFailure(
                "persisted grouping recompute payload violates its registered contract"
            ) from exc
        return value

    @staticmethod
    def _audit_event(
        *,
        command_id: str,
        proposal_id: str,
        candidate: Any,
        actor_kind: str,
        actor_id: str | None,
        job_id: str,
    ) -> AuditEventInput:
        return AuditEventInput(
            audit_event_id=new_uuid4(),
            action_type="grouping.proposal_recomputed",
            action_version=1,
            actor_kind=actor_kind,
            actor_id=actor_id,
            target_type="grouping_proposal",
            target_id=proposal_id,
            command_id=command_id,
            job_id=job_id,
            payload_schema="GroupingAuditV1",
            payload_version=1,
            payload={
                "proposal_id": proposal_id,
                "event_kind": "RECOMPUTED",
                "proposal_kind": candidate.proposal_kind,
                "risk_tier": candidate.risk_tier,
                "input_fingerprint": candidate.input_fingerprint,
                "task_change_count": len(candidate.task_changes),
                "objective_change_count": len(candidate.objective_changes),
                "reason_category": None,
            },
            resulting_event_refs=(
                AuditResultRef("grouping_proposal", proposal_id),
            ),
        )

    def run(
        self,
        claim: DurableJobClaim,
        *,
        actor_kind: str = "system",
        actor_id: str | None = None,
    ) -> GroupingRecomputeJobRunResult:
        payload = self._payload(claim)
        origin = str(payload["origin"])
        command_id = str(payload["requested_by_command_id"])

        self._jobs.checkpoint(
            claim,
            {"phase": "scanning", "published_proposal_count": 0},
        )
        with ReadSnapshot(self._factory) as snapshot:
            candidates = GroupingService._candidates(
                snapshot.connection,
                origin=origin,
            )

        published = 0
        self._jobs.checkpoint(
            claim,
            {"phase": "publishing", "published_proposal_count": published},
        )
        for candidate in candidates:
            with UnitOfWork(self._factory) as uow:
                self._jobs.assert_claim_current(uow, claim)
                if (
                    RegroupProposalRepository.exact_pending_by_fingerprint(
                        uow.connection,
                        candidate.input_fingerprint,
                    )
                    is not None
                    or RegroupProposalRepository.rejection_suppressed(
                        uow.connection,
                        candidate.input_fingerprint,
                    )
                ):
                    continue
                proposal_id = RegroupProposalRepository.insert_candidate(
                    uow.connection,
                    candidate=candidate,
                    command_id=command_id,
                )
                self._audit.write(
                    uow,
                    self._audit_event(
                        command_id=command_id,
                        proposal_id=proposal_id,
                        candidate=candidate,
                        actor_kind=actor_kind,
                        actor_id=actor_id,
                        job_id=claim.job_id,
                    ),
                )
                published += 1
                self._jobs.checkpoint_in_uow(
                    uow,
                    claim,
                    {
                        "phase": "publishing",
                        "published_proposal_count": published,
                    },
                )

        self._jobs.complete(claim)
        return GroupingRecomputeJobRunResult(
            job_id=claim.job_id,
            origin=origin,
            candidate_exact_count=len(candidates),
            published_proposal_count=published,
        )


def run(
    claim: DurableJobClaim,
    connection_factory: ConnectionFactory,
) -> GroupingRecomputeJobRunResult:
    """Canonical handler entry point registered as objectives_tasks.jobs.grouping_recompute.run."""

    return ObjectiveGroupingRecomputeWorker(connection_factory).run(claim)


__all__ = [
    "GroupingRecomputeJobRunResult",
    "ObjectiveGroupingRecomputeWorker",
    "run",
]
