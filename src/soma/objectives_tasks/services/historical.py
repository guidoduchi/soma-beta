from __future__ import annotations

from soma.foundation.application.command_boundary import (
    CommandBoundary,
    CommandEnvelope,
    PreparedMutation,
)
from soma.foundation.audit.writer import AuditEventInput, AuditResultRef, AuditWriter
from soma.foundation.errors import IntegrityFailure, SomaError, ValidationError
from soma.foundation.identifiers import new_uuid4, require_uuid4, utc_epoch_seconds
from soma.foundation.persistence.connections import ConnectionFactory
from soma.foundation.persistence.uow import UnitOfWork

from ..audit_registry import build_objectives_tasks_audit_registry
from ..contracts.objectives_tasks import (
    HistoricalObjectiveProposalDecisionResult,
    TaskMutationResult,
    historical_objective_proposal_decision_from_execution,
    task_mutation_result_from_execution,
)
from ..queries.reviews import HistoricalObjectiveQueryService
from ..repositories.objectives import ObjectiveProjectionRepository
from ..repositories.reviews import HistoricalObjectiveProposalRepository
from ..repositories.tasks import (
    TaskPlanRecord,
    TaskPlanRepository,
    TaskRepository,
    WfmTaskRepository,
)
from ..source_terminal_authority import current_source_projection
from .objectives import ObjectiveService
from .task_execution import TaskExecutionService
from .task_planning import validate_task_reason_category


_HISTORICAL_TIMEZONE = "America/Guayaquil"


def _positive(value: int, label: str) -> int:
    if type(value) is not int or value <= 0:
        raise ValidationError(f"{label} must be positive")
    return value


def _nonnegative(value: int, label: str) -> int:
    if type(value) is not int or value < 0:
        raise ValidationError(f"{label} must be nonnegative")
    return value


def _fingerprint(value: str) -> str:
    if (
        not isinstance(value, str)
        or len(value) != 64
        or any(ch not in "0123456789abcdef" for ch in value)
    ):
        raise ValidationError("input_fingerprint must be lowercase SHA-256")
    return value


class HistoricalObjectiveService:
    def __init__(self, connection_factory: ConnectionFactory) -> None:
        self._tasks = TaskRepository()
        self._plans = TaskPlanRepository()
        self._wfm = WfmTaskRepository()
        self._objectives = ObjectiveProjectionRepository()
        self._boundary = CommandBoundary(
            connection_factory,
            AuditWriter(build_objectives_tasks_audit_registry()),
        )

    @staticmethod
    def _proposal(
        uow: UnitOfWork,
        proposal_id: str,
        revision: int,
        fingerprint: str,
    ):
        proposal = HistoricalObjectiveProposalRepository.get(
            uow.connection, proposal_id
        )
        if proposal is None:
            raise SomaError(
                "HISTORICAL_PROPOSAL_STALE",
                "historical Objective proposal does not exist",
            )
        if (
            proposal.state != "pending"
            or proposal.revision != revision
            or proposal.input_fingerprint != fingerprint
        ):
            raise SomaError(
                "HISTORICAL_PROPOSAL_STALE",
                "historical Objective proposal changed",
            )
        current = HistoricalObjectiveQueryService.input_fingerprint(
            uow.connection, proposal.task_id
        )
        if current != fingerprint:
            raise SomaError(
                "HISTORICAL_PROPOSAL_STALE",
                "historical Objective supporting authority changed",
            )
        return proposal

    @staticmethod
    def _assert_historical_eligibility(
        uow: UnitOfWork,
        proposal,
    ):
        task = TaskRepository.get(uow.connection, proposal.task_id)
        identity = WfmTaskRepository.get_identity(
            uow.connection, proposal.task_id
        )
        source = current_source_projection(
            uow.connection, proposal.task_id
        )
        if (
            task is None
            or task.task_kind != "wfm"
            or identity is None
            or source is None
            or source.provider_lifecycle_class != "complete"
            or source.source_projection_revision
            != proposal.expected_source_projection_revision
            or source.source_plan_start_utc
            != proposal.expected_source_plan_start_utc
            or source.source_plan_end_utc
            != proposal.expected_source_plan_end_utc
            or source.accepted_source_observation_id
            != proposal.expected_source_observation_id
        ):
            raise SomaError(
                "HISTORICAL_PROPOSAL_NOT_ELIGIBLE",
                "WFM Complete/source-plan authority no longer matches proposal",
            )
        if uow.connection.execute(
            "SELECT 1 FROM objective_task_membership_current "
            "WHERE task_id=? LIMIT 1",
            (proposal.task_id,),
        ).fetchone() is not None:
            raise SomaError(
                "HISTORICAL_PROPOSAL_NOT_ELIGIBLE",
                "WFM Task is already assigned to an Objective",
            )
        execution = TaskExecutionService._execution_authority(
            uow.connection, proposal.task_id
        )
        if (
            execution.revision != 0
            or execution.state != "not_started"
            or TaskExecutionService._has_terminal_outcome(
                uow.connection, proposal.task_id
            )
        ):
            raise SomaError(
                "HISTORICAL_PROPOSAL_NOT_ELIGIBLE",
                "WFM Task has local execution/outcome authority",
            )
        lock = uow.connection.execute(
            "SELECT explicit_plan_lock,explicit_membership_lock "
            "FROM task_lock_projection WHERE task_id=?",
            (proposal.task_id,),
        ).fetchone()
        if lock is not None and (int(lock[0]) == 1 or int(lock[1]) == 1):
            raise SomaError(
                "HISTORICAL_PROPOSAL_NOT_ELIGIBLE",
                "WFM Task is protected by an explicit plan/membership lock",
            )
        pointer = TaskPlanRepository.current_pointer(
            uow.connection, proposal.task_id
        )
        if proposal.expected_matching_operational_plan_revision_id is None:
            if pointer is not None:
                raise SomaError(
                    "HISTORICAL_PROPOSAL_NOT_ELIGIBLE",
                    "WFM Task gained an operational plan after proposal review",
                )
            selected_plan = None
        else:
            if (
                pointer is None
                or pointer.plan_revision_id
                != proposal.expected_matching_operational_plan_revision_id
            ):
                raise SomaError(
                    "HISTORICAL_PROPOSAL_NOT_ELIGIBLE",
                    "WFM operational plan changed after proposal review",
                )
            selected_plan = TaskPlanRepository.get_revision(
                uow.connection, pointer.plan_revision_id
            )
            if (
                selected_plan is None
                or selected_plan.task_id != proposal.task_id
                or selected_plan.start_utc
                != proposal.expected_source_plan_start_utc
                or selected_plan.end_utc
                != proposal.expected_source_plan_end_utc
            ):
                raise SomaError(
                    "HISTORICAL_PROPOSAL_NOT_ELIGIBLE",
                    "WFM operational plan no longer exactly matches source interval",
                )
        overlap = uow.connection.execute(
            "SELECT e.objective_id FROM objective_envelope_projection e "
            "JOIN objectives o ON o.objective_id=e.objective_id "
            "WHERE o.superseded_by_objective_id IS NULL "
            "AND e.start_utc<? AND e.end_utc>? "
            "ORDER BY e.start_utc,e.objective_id LIMIT 1",
            (
                proposal.expected_source_plan_end_utc,
                proposal.expected_source_plan_start_utc,
            ),
        ).fetchone()
        if overlap is not None:
            raise SomaError(
                "OBJECTIVE_OVERLAP",
                "historical Objective interval overlaps current accepted Objective",
            )
        return task, selected_plan

    def accept_proposal(
        self,
        *,
        command_id: str,
        proposal_id: str,
        proposal_revision: int,
        input_fingerprint: str,
        actor_kind: str = "local_user",
        actor_id: str | None = None,
    ) -> HistoricalObjectiveProposalDecisionResult:
        proposal_identity = require_uuid4(proposal_id)
        expected_revision = _positive(
            proposal_revision, "proposal_revision"
        )
        expected_fingerprint = _fingerprint(input_fingerprint)
        envelope = CommandEnvelope(
            command_id=command_id,
            command_type="AcceptHistoricalObjectiveProposal",
            target_type="historical_objective_proposal",
            target_id=proposal_identity,
            semantic_payload={},
            base_revisions={
                f"historical_proposal:{proposal_identity}": expected_revision
            },
            authorizing_fingerprints={
                "input_fingerprint": expected_fingerprint
            },
        )

        def prepare(uow: UnitOfWork) -> PreparedMutation:
            proposal = self._proposal(
                uow,
                proposal_identity,
                expected_revision,
                expected_fingerprint,
            )
            task, selected_plan = self._assert_historical_eligibility(
                uow, proposal
            )
            sequence, allocator_revision = ObjectiveService._tracking_allocator(
                uow.connection
            )
            objective_id = new_uuid4()
            tracking_id = f"MW-{sequence:08d}"
            new_plan_id = (
                new_uuid4() if selected_plan is None else None
            )
            selected_plan_id = (
                new_plan_id
                if selected_plan is None
                else selected_plan.plan_revision_id
            )
            assert selected_plan_id is not None
            now = utc_epoch_seconds()

            def apply(inner: UnitOfWork):
                ObjectiveService._advance_tracking_allocator(
                    inner.connection,
                    sequence=sequence,
                    revision=allocator_revision,
                    command_id=command_id,
                )
                if new_plan_id is not None:
                    self._plans.insert_initial(
                        inner,
                        TaskPlanRecord(
                            plan_revision_id=new_plan_id,
                            task_id=proposal.task_id,
                            start_utc=proposal.expected_source_plan_start_utc,
                            end_utc=proposal.expected_source_plan_end_utc,
                            origin="historical_source_structure",
                            scheduling_timezone_iana=_HISTORICAL_TIMEZONE,
                            source_observation_id=(
                                proposal.expected_source_observation_id
                            ),
                            predecessor_plan_revision_id=None,
                            reason_code=None,
                            accepted_at_utc=now,
                            command_id=command_id,
                        ),
                    )
                    self._tasks.increment_revision(
                        inner,
                        task_id=proposal.task_id,
                        expected_revision=task.revision,
                    )
                inner.connection.execute(
                    "INSERT INTO objectives("
                    "objective_id,tracking_sequence,tracking_id,creation_origin,"
                    "superseded_by_objective_id,revision,created_at_utc,"
                    "created_command_id"
                    ") VALUES (?,?,?,'historical_provider_complete',NULL,1,?,?)",
                    (
                        objective_id,
                        sequence,
                        tracking_id,
                        now,
                        command_id,
                    ),
                )
                membership_event_id = ObjectiveService._insert_membership(
                    inner.connection,
                    task_id=proposal.task_id,
                    objective_id=objective_id,
                    plan_revision_id=selected_plan_id,
                    command_id=command_id,
                    event_kind="historical_add",
                )
                apply.membership_event_id = membership_event_id
                ObjectiveService._insert_envelope(
                    inner.connection,
                    objective_id=objective_id,
                    members=(
                        (
                            proposal.task_id,
                            selected_plan_id,
                            proposal.expected_source_plan_start_utc,
                            proposal.expected_source_plan_end_utc,
                        ),
                    ),
                    command_id=command_id,
                )
                inner.connection.execute(
                    "INSERT INTO objective_archive_projection("
                    "objective_id,archived,revision,last_event_id"
                    ") VALUES (?,0,1,NULL)",
                    (objective_id,),
                )
                ObjectiveService._assert_no_overlap(
                    inner.connection, objective_id
                )
                aggregate = self._objectives.rebuild_aggregate(
                    inner,
                    objective_id=objective_id,
                    command_id=command_id,
                )
                if (
                    aggregate.execution_state != "historical_structure"
                    or aggregate.actual_start_utc is not None
                    or aggregate.actual_end_utc is not None
                ):
                    raise IntegrityFailure(
                        "historical Objective created non-historical execution authority"
                    )
                apply.proposal_revision = (
                    HistoricalObjectiveProposalRepository.transition(
                        inner,
                        proposal_id=proposal_identity,
                        expected_revision=expected_revision,
                        expected_fingerprint=expected_fingerprint,
                        new_state="accepted",
                        command_id=command_id,
                    )
                )
                refs = [
                    AuditResultRef("objective", objective_id),
                    AuditResultRef(
                        "objective_membership", membership_event_id
                    ),
                ]
                if new_plan_id is not None:
                    refs.append(AuditResultRef("task_plan", new_plan_id))
                return AuditEventInput(
                    audit_event_id=new_uuid4(),
                    action_type="objective.historical_proposal_decided",
                    action_version=1,
                    actor_kind=actor_kind,
                    actor_id=actor_id,
                    target_type="historical_objective_proposal",
                    target_id=proposal_identity,
                    command_id=command_id,
                    payload_schema="HistoricalObjectiveAuditV1",
                    payload_version=1,
                    payload={
                        "proposal_id": proposal_identity,
                        "task_id": proposal.task_id,
                        "source_projection_revision": (
                            proposal.expected_source_projection_revision
                        ),
                        "source_evidence_id": (
                            proposal.expected_source_observation_id
                        ),
                        "decision": "ACCEPTED",
                        "objective_id": objective_id,
                        "membership_plan_revision_id": selected_plan_id,
                        "review_fingerprint": expected_fingerprint,
                        "reason_category": None,
                    },
                    resulting_event_refs=tuple(refs),
                )

            apply.membership_event_id = ""
            apply.proposal_revision = expected_revision + 1

            def response_factory(_inner: UnitOfWork):
                refs = [
                    {"type": "objective", "id": objective_id},
                    {
                        "type": "objective_membership",
                        "id": apply.membership_event_id,
                    },
                ]
                if new_plan_id is not None:
                    refs.append({"type": "task_plan", "id": new_plan_id})
                return {
                    "outcome": "APPLIED",
                    "proposal_id": proposal_identity,
                    "proposal_revision": apply.proposal_revision,
                    "state": "accepted",
                    "objective_id": objective_id,
                    "result_refs": refs,
                }

            return PreparedMutation(
                False,
                "objective",
                objective_id,
                apply,
                response_schema="HistoricalObjectiveProposalDecisionV1",
                response_factory=response_factory,
            )

        return historical_objective_proposal_decision_from_execution(
            self._boundary.execute(envelope, prepare)
        )

    def reject_proposal(
        self,
        *,
        command_id: str,
        proposal_id: str,
        proposal_revision: int,
        input_fingerprint: str,
        reason_category: str,
        actor_kind: str = "local_user",
        actor_id: str | None = None,
    ) -> HistoricalObjectiveProposalDecisionResult:
        proposal_identity = require_uuid4(proposal_id)
        expected_revision = _positive(
            proposal_revision, "proposal_revision"
        )
        expected_fingerprint = _fingerprint(input_fingerprint)
        reason = validate_task_reason_category(reason_category)
        envelope = CommandEnvelope(
            command_id=command_id,
            command_type="RejectHistoricalObjectiveProposal",
            target_type="historical_objective_proposal",
            target_id=proposal_identity,
            semantic_payload={"reason_category": reason},
            base_revisions={
                f"historical_proposal:{proposal_identity}": expected_revision
            },
            authorizing_fingerprints={
                "input_fingerprint": expected_fingerprint
            },
        )

        def prepare(uow: UnitOfWork) -> PreparedMutation:
            proposal = self._proposal(
                uow,
                proposal_identity,
                expected_revision,
                expected_fingerprint,
            )

            def apply(inner: UnitOfWork):
                apply.proposal_revision = (
                    HistoricalObjectiveProposalRepository.transition(
                        inner,
                        proposal_id=proposal_identity,
                        expected_revision=expected_revision,
                        expected_fingerprint=expected_fingerprint,
                        new_state="rejected",
                        command_id=command_id,
                    )
                )
                return AuditEventInput(
                    audit_event_id=new_uuid4(),
                    action_type="objective.historical_proposal_decided",
                    action_version=1,
                    actor_kind=actor_kind,
                    actor_id=actor_id,
                    target_type="historical_objective_proposal",
                    target_id=proposal_identity,
                    command_id=command_id,
                    reason_category=reason,
                    payload_schema="HistoricalObjectiveAuditV1",
                    payload_version=1,
                    payload={
                        "proposal_id": proposal_identity,
                        "task_id": proposal.task_id,
                        "source_projection_revision": (
                            proposal.expected_source_projection_revision
                        ),
                        "source_evidence_id": (
                            proposal.expected_source_observation_id
                        ),
                        "decision": "REJECTED",
                        "objective_id": None,
                        "membership_plan_revision_id": None,
                        "review_fingerprint": expected_fingerprint,
                        "reason_category": reason,
                    },
                    resulting_event_refs=(),
                )

            apply.proposal_revision = expected_revision + 1
            return PreparedMutation(
                False,
                "historical_objective_proposal",
                proposal_identity,
                apply,
                response_schema="HistoricalObjectiveProposalDecisionV1",
                response_factory=lambda _inner: {
                    "outcome": "APPLIED",
                    "proposal_id": proposal_identity,
                    "proposal_revision": apply.proposal_revision,
                    "state": "rejected",
                    "objective_id": None,
                    "result_refs": [
                        {
                            "type": "historical_objective_proposal",
                            "id": proposal_identity,
                        }
                    ],
                },
            )

        return historical_objective_proposal_decision_from_execution(
            self._boundary.execute(envelope, prepare)
        )

    def set_operational_count_inclusion(
        self,
        *,
        command_id: str,
        task_id: str,
        expected_inclusion_revision: int,
        included: bool,
        reason_category: str,
        actor_kind: str = "local_user",
        actor_id: str | None = None,
    ) -> TaskMutationResult:
        identity = require_uuid4(task_id)
        expected = _nonnegative(
            expected_inclusion_revision,
            "expected_inclusion_revision",
        )
        if type(included) is not bool:
            raise ValidationError("included must be boolean")
        reason = validate_task_reason_category(reason_category)
        envelope = CommandEnvelope(
            command_id=command_id,
            command_type="SetHistoricalTaskOperationalCountInclusion",
            target_type="task",
            target_id=identity,
            semantic_payload={"included": included, "reason_category": reason},
            base_revisions=(
                {}
                if expected == 0
                else {f"task_operational_count:{identity}": expected}
            ),
        )

        def prepare(uow: UnitOfWork) -> PreparedMutation:
            task = self._tasks.get(uow.connection, identity)
            if task is None:
                raise SomaError("TASK_NOT_FOUND", "Task does not exist")
            source = current_source_projection(uow.connection, identity)
            membership = self._objectives.current_membership_for_task(
                uow.connection, identity
            )
            historical_objective = False
            if membership is not None:
                row = uow.connection.execute(
                    "SELECT creation_origin FROM objectives WHERE objective_id=?",
                    (membership.objective_id,),
                ).fetchone()
                historical_objective = (
                    row is not None
                    and str(row[0]) == "historical_provider_complete"
                )
            if not (
                task.creation_origin == "historical_source"
                or historical_objective
                or (
                    source is not None
                    and source.provider_lifecycle_class == "complete"
                )
            ):
                raise SomaError(
                    "HISTORICAL_TASK_NOT_ELIGIBLE",
                    "Task is not provider-historical/historical Objective work",
                )
            current = uow.connection.execute(
                "SELECT included,revision,last_event_id "
                "FROM task_operational_count_current WHERE task_id=?",
                (identity,),
            ).fetchone()
            current_included = True if current is None else bool(current[0])
            current_revision = 0 if current is None else int(current[1])
            if current_revision != expected:
                raise SomaError(
                    "TASK_STALE",
                    "Task operational-count inclusion revision changed",
                )
            if current_included == included:
                return PreparedMutation(
                    True,
                    None,
                    None,
                    response_schema="TaskMutationResultV1",
                    response_version=1,
                    response={
                        "outcome": "NO_CHANGE",
                        "task_id": identity,
                        "revision": task.revision,
                        "result_refs": [],
                    },
                )
            event_id = new_uuid4()
            resulting_revision = current_revision + 1
            now = utc_epoch_seconds()

            def apply(inner: UnitOfWork):
                inner.connection.execute(
                    "INSERT INTO task_operational_count_events("
                    "inclusion_event_id,task_id,included,reason_code,"
                    "recorded_at_utc,command_id"
                    ") VALUES (?,?,?,?,?,?)",
                    (
                        event_id,
                        identity,
                        1 if included else 0,
                        reason,
                        now,
                        command_id,
                    ),
                )
                if current is None:
                    inner.connection.execute(
                        "INSERT INTO task_operational_count_current("
                        "task_id,included,revision,last_event_id"
                        ") VALUES (?,?,1,?)",
                        (identity, 1 if included else 0, event_id),
                    )
                else:
                    changed = inner.connection.execute(
                        "UPDATE task_operational_count_current "
                        "SET included=?,revision=revision+1,last_event_id=? "
                        "WHERE task_id=? AND revision=?",
                        (
                            1 if included else 0,
                            event_id,
                            identity,
                            current_revision,
                        ),
                    )
                    if changed.rowcount != 1:
                        raise IntegrityFailure(
                            "Task operational-count authority changed during mutation"
                        )
                current_membership = (
                    self._objectives.current_membership_for_task(
                        inner.connection, identity
                    )
                )
                if current_membership is not None:
                    self._objectives.rebuild_aggregate(
                        inner,
                        objective_id=current_membership.objective_id,
                        command_id=command_id,
                    )
                return AuditEventInput(
                    audit_event_id=new_uuid4(),
                    action_type=(
                        "task.operational_count_inclusion_changed"
                    ),
                    action_version=1,
                    actor_kind=actor_kind,
                    actor_id=actor_id,
                    target_type="task",
                    target_id=identity,
                    command_id=command_id,
                    reason_category=reason,
                    payload_schema="TaskCountAuditV1",
                    payload_version=1,
                    payload={
                        "task_id": identity,
                        "included": included,
                        "inclusion_event_id": event_id,
                        "resulting_revision": resulting_revision,
                        "reason_category": reason,
                    },
                    resulting_event_refs=(
                        AuditResultRef("task", identity),
                    ),
                )

            return PreparedMutation(
                False,
                "task",
                identity,
                apply,
                response_schema="TaskMutationResultV1",
                response_version=1,
                response={
                    "outcome": "APPLIED",
                    "task_id": identity,
                    "revision": task.revision,
                    "result_refs": [{"type": "task", "id": identity}],
                },
            )

        return task_mutation_result_from_execution(
            self._boundary.execute(envelope, prepare)
        )


__all__ = ["HistoricalObjectiveService"]
