from __future__ import annotations

from collections.abc import Sequence
from typing import Any

from soma.foundation.application.command_boundary import CommandBoundary, CommandEnvelope, PreparedMutation
from soma.foundation.audit.writer import AuditEventInput, AuditResultRef, AuditWriter
from soma.foundation.errors import IntegrityFailure, SomaError, ValidationError
from soma.foundation.identifiers import new_uuid4, require_uuid4, utc_epoch_seconds
from soma.foundation.persistence.connections import ConnectionFactory
from soma.foundation.persistence.uow import UnitOfWork
from soma.foundation.strict_json import sha256_canonical_json

from ..audit_registry import build_objectives_tasks_audit_registry
from ..contracts.objectives_tasks import ObjectiveMutationResult, objective_mutation_result_from_execution
from ..domain.objectives import ObjectiveDraftLocalTaskIntent, ObjectiveExistingTaskIntent
from ..queries.grouping import ObjectiveGroupingQueryService
from ..repositories.objectives import ObjectiveProjectionRepository
from ..repositories.tasks import (
    TaskPlanRecord,
    TaskPlanRepository,
    TaskRecord,
    TaskRelationshipRepository,
    TaskRepository,
)
from .task_execution import TaskExecutionService
from .task_planning import TaskPlanningService, validate_task_reason_category


class ObjectiveService:
    def __init__(self, connection_factory: ConnectionFactory) -> None:
        self._tasks = TaskRepository()
        self._plans = TaskPlanRepository()
        self._relationships = TaskRelationshipRepository()
        self._objectives = ObjectiveProjectionRepository()
        self._boundary = CommandBoundary(
            connection_factory,
            AuditWriter(build_objectives_tasks_audit_registry()),
        )

    @staticmethod
    def _tracking_allocator(connection: Any) -> tuple[int, int]:
        row = connection.execute(
            "SELECT next_sequence,revision FROM objective_tracking_allocator WHERE singleton_id=1"
        ).fetchone()
        if row is None:
            raise IntegrityFailure("Objective tracking allocator is missing")
        sequence, revision = int(row[0]), int(row[1])
        if sequence >= 100_000_000:
            raise SomaError("OBJECTIVE_TRACKING_ID_EXHAUSTED", "Objective tracking identity is exhausted")
        return sequence, revision

    @staticmethod
    def _advance_tracking_allocator(
        connection: Any,
        *,
        sequence: int,
        revision: int,
        command_id: str,
    ) -> None:
        changed = connection.execute(
            "UPDATE objective_tracking_allocator SET next_sequence=?,revision=revision+1,last_command_id=? "
            "WHERE singleton_id=1 AND next_sequence=? AND revision=?",
            (sequence + 1, command_id, sequence, revision),
        )
        if changed.rowcount != 1:
            raise SomaError("OBJECTIVE_STALE", "Objective tracking allocator changed")

    @staticmethod
    def _insert_membership(
        connection: Any,
        *,
        task_id: str,
        objective_id: str,
        plan_revision_id: str,
        command_id: str,
        event_kind: str = "add",
    ) -> str:
        event_id = new_uuid4()
        connection.execute(
            "INSERT INTO objective_membership_events("
            "membership_event_id,task_id,event_kind,from_objective_id,to_objective_id,"
            "accepted_plan_revision_id,grouping_proposal_id,reason_code,recorded_at_utc,command_id"
            ") VALUES (?,?,?,NULL,?,?,NULL,NULL,?,?)",
            (
                event_id,
                task_id,
                event_kind,
                objective_id,
                plan_revision_id,
                utc_epoch_seconds(),
                command_id,
            ),
        )
        connection.execute(
            "INSERT INTO objective_task_membership_current("
            "task_id,objective_id,accepted_plan_revision_id,membership_revision,last_event_id,last_command_id"
            ") VALUES (?,?,?,1,?,?)",
            (task_id, objective_id, plan_revision_id, event_id, command_id),
        )
        return event_id

    @staticmethod
    def _insert_envelope(
        connection: Any,
        *,
        objective_id: str,
        members: Sequence[tuple[str, str, int, int]],
        command_id: str,
    ) -> str:
        if not members:
            raise IntegrityFailure("Objective cannot publish an empty envelope")
        material = [
            {
                "task_id": task_id,
                "plan_revision_id": plan_id,
                "start_utc": start,
                "end_utc": end,
            }
            for task_id, plan_id, start, end in sorted(members)
        ]
        fingerprint = sha256_canonical_json(
            {"schema": "OBJECTIVE_MEMBERSHIP_INPUT_V1", "members": material}
        )
        connection.execute(
            "INSERT INTO objective_envelope_projection("
            "objective_id,start_utc,end_utc,member_count,membership_input_fingerprint,"
            "revision,last_command_id) VALUES (?,?,?,?,?,1,?)",
            (
                objective_id,
                min(item[2] for item in members),
                max(item[3] for item in members),
                len(members),
                fingerprint,
                command_id,
            ),
        )
        return fingerprint

    @staticmethod
    def _assert_no_overlap(connection: Any, objective_id: str) -> None:
        row = connection.execute(
            "SELECT start_utc,end_utc FROM objective_envelope_projection WHERE objective_id=?",
            (objective_id,),
        ).fetchone()
        if row is None:
            raise IntegrityFailure("Objective envelope disappeared before overlap guard")
        conflict = connection.execute(
            "SELECT e.objective_id FROM objective_envelope_projection e "
            "JOIN objectives o ON o.objective_id=e.objective_id "
            "WHERE e.objective_id<>? AND o.superseded_by_objective_id IS NULL "
            "AND e.start_utc<? AND e.end_utc>? ORDER BY e.start_utc,e.objective_id LIMIT 1",
            (objective_id, int(row[1]), int(row[0])),
        ).fetchone()
        if conflict is not None:
            raise SomaError("OBJECTIVE_OVERLAP", "Objective would overlap current accepted Objective authority")

    def create_objective_from_preview(
        self,
        *,
        command_id: str,
        preview_fingerprint: str,
        existing_tasks: Sequence[ObjectiveExistingTaskIntent] = (),
        draft_tasks: Sequence[ObjectiveDraftLocalTaskIntent] = (),
        actor_kind: str = "local_user",
        actor_id: str | None = None,
    ) -> ObjectiveMutationResult:
        if (
            not isinstance(preview_fingerprint, str)
            or len(preview_fingerprint) != 64
            or any(ch not in "0123456789abcdef" for ch in preview_fingerprint)
        ):
            raise ValidationError("preview_fingerprint must be lowercase SHA-256")
        existing = tuple(item.validate() for item in existing_tasks)
        drafts = tuple(item.validate() for item in draft_tasks)
        envelope = CommandEnvelope(
            command_id=command_id,
            command_type="CreateObjectiveFromPreview",
            target_type="objective",
            target_id=None,
            semantic_payload={
                "preview_fingerprint": preview_fingerprint,
                "existing_tasks": [
                    {
                        "task_id": item.task_id,
                        "task_revision": item.expected_task_revision,
                        "plan_revision": item.expected_plan_revision,
                        "plan_revision_id": item.expected_plan_revision_id,
                    }
                    for item in existing
                ],
                "draft_tasks": [item.semantic_value() for item in drafts],
            },
            authorizing_fingerprints={"objective_creation_preview": preview_fingerprint},
        )

        def prepare(uow: UnitOfWork) -> PreparedMutation:
            preview = ObjectiveGroupingQueryService.evaluate_creation(
                uow.connection,
                existing_tasks=existing,
                draft_tasks=drafts,
            )
            if preview["fingerprint"] != preview_fingerprint:
                raise SomaError("TASK_STALE", "Objective creation preview changed")
            if preview["mode"] != "CREATE":
                if preview["current_memberships"]:
                    raise SomaError("TASK_ALREADY_IN_OBJECTIVE", "A selected Task already belongs to an Objective")
                raise SomaError("OBJECTIVE_OVERLAP", "Objective creation now requires regroup review")

            sequence, allocator_revision = self._tracking_allocator(uow.connection)
            objective_id = new_uuid4()
            tracking_id = f"MW-{sequence:08d}"
            now = utc_epoch_seconds()
            draft_authority: list[dict[str, object]] = []
            for draft in drafts:
                TaskPlanningService._revalidate_local_relationship_targets(
                    uow.connection,
                    service_request_ids=draft.service_request_ids,
                    rfc_ids=draft.rfc_ids,
                    device_reference_ids=draft.device_reference_ids,
                )
                task_id = new_uuid4()
                plan_id = new_uuid4()
                relationships = TaskPlanningService._initial_relationship_rows(
                    task_id=task_id,
                    command_id=command_id,
                    service_request_ids=draft.service_request_ids,
                    rfc_ids=draft.rfc_ids,
                    device_reference_ids=draft.device_reference_ids,
                )
                draft_authority.append(
                    {
                        "intent": draft,
                        "task_id": task_id,
                        "plan_id": plan_id,
                        "relationships": relationships,
                    }
                )

            membership_refs: list[str] = []
            created_task_ids = [str(item["task_id"]) for item in draft_authority]

            def apply(inner: UnitOfWork):
                self._advance_tracking_allocator(
                    inner.connection,
                    sequence=sequence,
                    revision=allocator_revision,
                    command_id=command_id,
                )
                inner.connection.execute(
                    "INSERT INTO objectives("
                    "objective_id,tracking_sequence,tracking_id,creation_origin,"
                    "superseded_by_objective_id,revision,created_at_utc,created_command_id"
                    ") VALUES (?,?,?,'manual',NULL,1,?,?)",
                    (objective_id, sequence, tracking_id, now, command_id),
                )

                member_rows: list[tuple[str, str, int, int]] = []
                task_audits: list[AuditEventInput] = []
                for item in existing:
                    plan = self._plans.get_revision(inner.connection, item.expected_plan_revision_id)
                    if plan is None or plan.task_id != item.task_id:
                        raise SomaError("TASK_STALE", "Existing Task plan disappeared")
                    event_id = self._insert_membership(
                        inner.connection,
                        task_id=item.task_id,
                        objective_id=objective_id,
                        plan_revision_id=item.expected_plan_revision_id,
                        command_id=command_id,
                    )
                    membership_refs.append(event_id)
                    member_rows.append((item.task_id, item.expected_plan_revision_id, plan.start_utc, plan.end_utc))

                for authority in draft_authority:
                    draft = authority["intent"]
                    assert isinstance(draft, ObjectiveDraftLocalTaskIntent)
                    task_id = str(authority["task_id"])
                    plan_id = str(authority["plan_id"])
                    relationships = authority["relationships"]
                    self._tasks.insert(
                        inner,
                        TaskRecord(
                            task_id=task_id,
                            task_kind="local",
                            local_task_name=draft.local_task_name,
                            creation_origin="manual",
                            revision=1,
                            created_at_utc=now,
                            created_command_id=command_id,
                        ),
                    )
                    self._plans.insert_initial(
                        inner,
                        TaskPlanRecord(
                            plan_revision_id=plan_id,
                            task_id=task_id,
                            start_utc=draft.schedule.start_utc,
                            end_utc=draft.schedule.end_utc,
                            origin="objective_initialization",
                            scheduling_timezone_iana=draft.schedule.scheduling_timezone_iana,
                            source_observation_id=None,
                            predecessor_plan_revision_id=None,
                            reason_code=None,
                            accepted_at_utc=now,
                            command_id=command_id,
                        ),
                    )
                    for relationship in relationships:
                        self._relationships.link(inner, relationship)
                    event_id = self._insert_membership(
                        inner.connection,
                        task_id=task_id,
                        objective_id=objective_id,
                        plan_revision_id=plan_id,
                        command_id=command_id,
                    )
                    membership_refs.append(event_id)
                    member_rows.append((task_id, plan_id, draft.schedule.start_utc, draft.schedule.end_utc))
                    task_refs = [AuditResultRef("task", task_id), AuditResultRef("task_plan", plan_id)]
                    task_refs.extend(
                        AuditResultRef("task_relationship", relationship.relationship_id)
                        for relationship in relationships
                    )
                    task_audits.append(
                        AuditEventInput(
                            audit_event_id=new_uuid4(),
                            action_type="task.created",
                            action_version=1,
                            actor_kind=actor_kind,
                            actor_id=actor_id,
                            target_type="task",
                            target_id=task_id,
                            command_id=command_id,
                            payload_schema="TaskAuditV1",
                            payload_version=1,
                            payload={
                                "task_id": task_id,
                                "task_kind": "local",
                                "creation_origin": "manual",
                                "resulting_revision": 1,
                                "task_plan_revision_id": plan_id,
                                "reason_category": None,
                            },
                            resulting_event_refs=tuple(task_refs),
                        )
                    )

                membership_fingerprint = self._insert_envelope(
                    inner.connection,
                    objective_id=objective_id,
                    members=member_rows,
                    command_id=command_id,
                )
                inner.connection.execute(
                    "INSERT INTO objective_archive_projection("
                    "objective_id,archived,revision,last_event_id) VALUES (?,0,1,NULL)",
                    (objective_id,),
                )
                self._assert_no_overlap(inner.connection, objective_id)
                self._objectives.rebuild_aggregate(
                    inner,
                    objective_id=objective_id,
                    command_id=command_id,
                )
                objective_audit = AuditEventInput(
                    audit_event_id=new_uuid4(),
                    action_type="objective.created",
                    action_version=1,
                    actor_kind=actor_kind,
                    actor_id=actor_id,
                    target_type="objective",
                    target_id=objective_id,
                    command_id=command_id,
                    payload_schema="ObjectiveAuditV1",
                    payload_version=1,
                    payload={
                        "objective_id": objective_id,
                        "tracking_id": tracking_id,
                        "creation_origin": "manual",
                        "resulting_revision": 1,
                        "membership_input_fingerprint": membership_fingerprint,
                        "archive_action": None,
                        "reason_category": None,
                    },
                    resulting_event_refs=(
                        AuditResultRef("objective", objective_id),
                        *(
                            AuditResultRef("objective_membership", event_id)
                            for event_id in membership_refs
                        ),
                    ),
                )
                return (*task_audits, objective_audit)

            response_refs = [{"type": "objective", "id": objective_id}]
            response_refs.extend(
                {"type": "task", "id": task_id} for task_id in created_task_ids
            )
            # Pre-bound membership event ids are produced during apply, so replay-safe response
            # exposes stable Objective + created draft Task identities only.
            return PreparedMutation(
                False,
                "objective",
                objective_id,
                apply,
                response_schema="ObjectiveMutationResultV1",
                response_version=1,
                response={
                    "outcome": "APPLIED",
                    "objective_id": objective_id,
                    "revision": 1,
                    "result_refs": response_refs,
                },
            )

        return objective_mutation_result_from_execution(
            self._boundary.execute(envelope, prepare)
        )

    def review_objective(
        self,
        *,
        command_id: str,
        objective_id: str,
        review_fingerprint: str,
        reason_category: str | None = None,
        actor_kind: str = "local_user",
        actor_id: str | None = None,
    ) -> ObjectiveMutationResult:
        identity = require_uuid4(objective_id)
        if (
            not isinstance(review_fingerprint, str)
            or len(review_fingerprint) != 64
            or any(ch not in "0123456789abcdef" for ch in review_fingerprint)
        ):
            raise ValidationError("review_fingerprint must be lowercase SHA-256")
        reason = None if reason_category is None else validate_task_reason_category(reason_category)
        envelope = CommandEnvelope(
            command_id=command_id,
            command_type="ReviewObjective",
            target_type="objective",
            target_id=identity,
            semantic_payload={"review_fingerprint": review_fingerprint, "reason_category": reason},
            authorizing_fingerprints={"objective_review": review_fingerprint},
        )

        def prepare(uow: UnitOfWork) -> PreparedMutation:
            row = uow.connection.execute(
                "SELECT revision,creation_origin,superseded_by_objective_id FROM objectives WHERE objective_id=?",
                (identity,),
            ).fetchone()
            if row is None:
                raise SomaError("OBJECTIVE_NOT_FOUND", "Objective does not exist")
            objective_revision = int(row[0])
            if str(row[1]) == "historical_provider_complete" or row[2] is not None:
                raise SomaError("OBJECTIVE_REVIEW_NOT_READY", "Objective is not eligible for operational review")
            members = self._objectives._load_members(uow.connection, identity)
            if not members or any(member.accepted_outcome is None for member in members):
                raise SomaError("OBJECTIVE_REVIEW_NOT_READY", "Every Objective member requires accepted Task outcome")
            current_fingerprint = self._objectives._review_fingerprint(
                objective_id=identity,
                objective_revision=objective_revision,
                superseded_by=None,
                members=members,
            )
            if current_fingerprint != review_fingerprint:
                raise SomaError("OBJECTIVE_REVIEW_STALE", "Objective review fingerprint changed")
            outcome = self._objectives._derive_outcome(members)
            if outcome is None:
                raise SomaError("OBJECTIVE_REVIEW_NOT_READY", "Objective outcome cannot yet be derived")
            if outcome in {"incomplete", "mixed"} and reason is None:
                raise ValidationError("incomplete or mixed Objective review requires reason_category")
            prior = self._objectives._current_review(uow.connection, identity, current_fingerprint)
            if prior is not None:
                return PreparedMutation(
                    True,
                    None,
                    None,
                    response_schema="ObjectiveMutationResultV1",
                    response_version=1,
                    response={
                        "outcome": "NO_CHANGE",
                        "objective_id": identity,
                        "revision": objective_revision,
                        "result_refs": [],
                    },
                )
            review_event_id = new_uuid4()
            reviewed_at = utc_epoch_seconds()

            def apply(inner: UnitOfWork):
                inner.connection.execute(
                    "INSERT INTO objective_review_events("
                    "objective_review_event_id,objective_id,review_fingerprint,derived_outcome,"
                    "reviewed_at_utc,reason_code,command_id) VALUES (?,?,?,?,?,?,?)",
                    (
                        review_event_id,
                        identity,
                        current_fingerprint,
                        outcome,
                        reviewed_at,
                        reason,
                        command_id,
                    ),
                )
                aggregate = self._objectives.rebuild_aggregate(
                    inner,
                    objective_id=identity,
                    command_id=command_id,
                )
                return AuditEventInput(
                    audit_event_id=new_uuid4(),
                    action_type="objective.reviewed",
                    action_version=1,
                    actor_kind=actor_kind,
                    actor_id=actor_id,
                    target_type="objective",
                    target_id=identity,
                    command_id=command_id,
                    reason_category=reason,
                    payload_schema="ObjectiveReviewAuditV1",
                    payload_version=1,
                    payload={
                        "objective_id": identity,
                        "objective_review_event_id": review_event_id,
                        "review_fingerprint": current_fingerprint,
                        "derived_outcome": outcome,
                        "included_task_count": aggregate.included_task_count,
                        "excluded_task_count": aggregate.excluded_task_count,
                        "reason_category": reason,
                    },
                    resulting_event_refs=(
                        AuditResultRef("objective_review_event", review_event_id),
                    ),
                )

            return PreparedMutation(
                False,
                "objective_review_event",
                review_event_id,
                apply,
                response_schema="ObjectiveMutationResultV1",
                response_version=1,
                response={
                    "outcome": "APPLIED",
                    "objective_id": identity,
                    "revision": objective_revision,
                    "result_refs": [
                        {"type": "objective_review_event", "id": review_event_id}
                    ],
                },
            )

        return objective_mutation_result_from_execution(
            self._boundary.execute(envelope, prepare)
        )

    def _set_archive_state(
        self,
        *,
        command_id: str,
        objective_id: str,
        objective_revision: int,
        archive_revision: int,
        aggregate_revision: int,
        action: str,
        reason_category: str | None,
        actor_kind: str,
        actor_id: str | None,
    ) -> ObjectiveMutationResult:
        identity = require_uuid4(objective_id)
        if type(objective_revision) is not int or objective_revision <= 0:
            raise ValidationError("objective_revision must be positive")
        if type(archive_revision) is not int or archive_revision <= 0:
            raise ValidationError("archive_revision must be positive")
        if type(aggregate_revision) is not int or aggregate_revision <= 0:
            raise ValidationError("aggregate_revision must be positive")
        reason = None if reason_category is None else validate_task_reason_category(reason_category)
        desired = 1 if action == "archive" else 0
        envelope = CommandEnvelope(
            command_id=command_id,
            command_type="ArchiveObjective" if action == "archive" else "RestoreObjective",
            target_type="objective",
            target_id=identity,
            semantic_payload={
                "archive_revision": archive_revision,
                "aggregate_revision": aggregate_revision,
                "action": action,
                "reason_category": reason,
            },
            base_revisions={
                identity: objective_revision,
                f"objective_archive:{identity}": archive_revision,
                f"objective_aggregate:{identity}": aggregate_revision,
            },
        )

        def prepare(uow: UnitOfWork) -> PreparedMutation:
            row = uow.connection.execute(
                "SELECT o.revision,o.tracking_id,o.creation_origin,o.superseded_by_objective_id,"
                "a.execution_state,a.aggregate_outcome "
                "FROM objectives o JOIN objective_aggregate_projection a "
                "ON a.objective_id=o.objective_id WHERE o.objective_id=?",
                (identity,),
            ).fetchone()
            if row is None:
                raise SomaError("OBJECTIVE_NOT_FOUND", "Objective does not exist")
            if int(row[0]) != objective_revision:
                raise SomaError("OBJECTIVE_STALE", "Objective revision changed")
            aggregate = self._objectives.aggregate(uow.connection, identity)
            if aggregate is None or aggregate.revision != aggregate_revision:
                raise SomaError("OBJECTIVE_STALE", "Objective aggregate revision changed")
            archive = uow.connection.execute(
                "SELECT archived,revision FROM objective_archive_projection WHERE objective_id=?",
                (identity,),
            ).fetchone()
            if archive is None or int(archive[1]) != archive_revision:
                raise SomaError("OBJECTIVE_STALE", "Objective archive revision changed")
            if int(archive[0]) == desired:
                return PreparedMutation(
                    True,
                    None,
                    None,
                    response_schema="ObjectiveMutationResultV1",
                    response_version=1,
                    response={
                        "outcome": "NO_CHANGE",
                        "objective_id": identity,
                        "revision": objective_revision,
                        "result_refs": [],
                    },
                )
            if action == "archive" and str(row[4]) in {"planned", "in_progress"}:
                raise SomaError("OBJECTIVE_STALE", "Active unfinished Objective is not archive-eligible")
            if action == "restore":
                self._assert_no_overlap(uow.connection, identity)
            event_id = new_uuid4()
            next_archive_revision = archive_revision + 1

            def apply(inner: UnitOfWork):
                inner.connection.execute(
                    "INSERT INTO objective_archive_events("
                    "archive_event_id,objective_id,action,reason_code,recorded_at_utc,command_id"
                    ") VALUES (?,?,?,?,?,?)",
                    (event_id, identity, action, reason, utc_epoch_seconds(), command_id),
                )
                changed = inner.connection.execute(
                    "UPDATE objective_archive_projection SET archived=?,revision=revision+1,last_event_id=? "
                    "WHERE objective_id=? AND revision=?",
                    (desired, event_id, identity, archive_revision),
                )
                if changed.rowcount != 1:
                    raise SomaError("OBJECTIVE_STALE", "Objective archive state changed")
                return AuditEventInput(
                    audit_event_id=new_uuid4(),
                    action_type="objective.archive_state_changed",
                    action_version=1,
                    actor_kind=actor_kind,
                    actor_id=actor_id,
                    target_type="objective",
                    target_id=identity,
                    command_id=command_id,
                    reason_category=reason,
                    payload_schema="ObjectiveAuditV1",
                    payload_version=1,
                    payload={
                        "objective_id": identity,
                        "tracking_id": str(row[1]),
                        "creation_origin": str(row[2]),
                        "resulting_revision": next_archive_revision,
                        "membership_input_fingerprint": None,
                        "archive_action": action,
                        "reason_category": reason,
                    },
                    resulting_event_refs=(AuditResultRef("objective", identity),),
                )

            return PreparedMutation(
                False,
                "objective",
                identity,
                apply,
                response_schema="ObjectiveMutationResultV1",
                response_version=1,
                response={
                    "outcome": "APPLIED",
                    "objective_id": identity,
                    "revision": objective_revision,
                    "result_refs": [{"type": "objective", "id": identity}],
                },
            )

        return objective_mutation_result_from_execution(
            self._boundary.execute(envelope, prepare)
        )

    def archive_objective(
        self,
        *,
        command_id: str,
        objective_id: str,
        objective_revision: int,
        archive_revision: int,
        aggregate_revision: int,
        reason_category: str | None = None,
        actor_kind: str = "local_user",
        actor_id: str | None = None,
    ) -> ObjectiveMutationResult:
        return self._set_archive_state(
            command_id=command_id,
            objective_id=objective_id,
            objective_revision=objective_revision,
            archive_revision=archive_revision,
            aggregate_revision=aggregate_revision,
            action="archive",
            reason_category=reason_category,
            actor_kind=actor_kind,
            actor_id=actor_id,
        )

    def restore_objective(
        self,
        *,
        command_id: str,
        objective_id: str,
        objective_revision: int,
        archive_revision: int,
        aggregate_revision: int,
        actor_kind: str = "local_user",
        actor_id: str | None = None,
    ) -> ObjectiveMutationResult:
        return self._set_archive_state(
            command_id=command_id,
            objective_id=objective_id,
            objective_revision=objective_revision,
            archive_revision=archive_revision,
            aggregate_revision=aggregate_revision,
            action="restore",
            reason_category=None,
            actor_kind=actor_kind,
            actor_id=actor_id,
        )


    def cancel_objective_before_execution(
        self,
        *,
        command_id: str,
        objective_id: str,
        objective_revision: int,
        aggregate_revision: int,
        effective_cancel_utc: int,
        reason_category: str,
        actor_kind: str = "local_user",
        actor_id: str | None = None,
    ) -> ObjectiveMutationResult:
        identity = require_uuid4(objective_id)
        if type(objective_revision) is not int or objective_revision <= 0:
            raise ValidationError("objective_revision must be positive")
        if type(aggregate_revision) is not int or aggregate_revision <= 0:
            raise ValidationError("aggregate_revision must be positive")
        if type(effective_cancel_utc) is not int or effective_cancel_utc < 0:
            raise ValidationError("effective_cancel_utc must be a nonnegative UTC whole second")
        reason = validate_task_reason_category(reason_category)
        envelope = CommandEnvelope(
            command_id=command_id,
            command_type="CancelObjectiveBeforeExecution",
            target_type="objective",
            target_id=identity,
            semantic_payload={
                "aggregate_revision": aggregate_revision,
                "effective_cancel_utc": effective_cancel_utc,
                "reason_category": reason,
            },
            base_revisions={
                identity: objective_revision,
                f"objective_aggregate:{identity}": aggregate_revision,
            },
        )

        def prepare(uow: UnitOfWork) -> PreparedMutation:
            objective = uow.connection.execute(
                "SELECT revision,tracking_id,creation_origin,superseded_by_objective_id "
                "FROM objectives WHERE objective_id=?",
                (identity,),
            ).fetchone()
            if objective is None:
                raise SomaError("OBJECTIVE_NOT_FOUND", "Objective does not exist")
            if int(objective[0]) != objective_revision or objective[3] is not None:
                raise SomaError("OBJECTIVE_STALE", "Objective revision/currentness changed")
            aggregate = self._objectives.aggregate(uow.connection, identity)
            if aggregate is None or aggregate.revision != aggregate_revision:
                raise SomaError("OBJECTIVE_STALE", "Objective aggregate revision changed")

            members = self._objectives._load_members(uow.connection, identity)
            if not members:
                raise IntegrityFailure("current Objective has no members")
            if any(member.has_started for member in members):
                raise SomaError(
                    "OBJECTIVE_CANCEL_AFTER_EXECUTION",
                    "At least one Objective Task already has accepted start evidence",
                )

            already_cancelled = all(
                member.execution_state == "terminated"
                and member.actual_start_utc is None
                and member.accepted_outcome == "cancelled_without_execution"
                for member in members
            )
            if already_cancelled and aggregate.aggregate_outcome == "cancelled":
                return PreparedMutation(
                    True,
                    None,
                    None,
                    response_schema="ObjectiveMutationResultV1",
                    response_version=1,
                    response={
                        "outcome": "NO_CHANGE",
                        "objective_id": identity,
                        "revision": objective_revision,
                        "result_refs": [],
                    },
                )
            if aggregate.execution_state != "planned":
                raise SomaError(
                    "OBJECTIVE_STALE",
                    "Objective is not in a cancellable pre-execution state",
                )

            authorities: list[tuple[object, object]] = []
            for member in members:
                task = self._tasks.get(uow.connection, member.task_id)
                if task is None:
                    raise IntegrityFailure("Objective member Task disappeared")
                execution = TaskExecutionService._execution_authority(
                    uow.connection, member.task_id
                )
                if execution.state == "in_progress" and execution.actual_start_utc is not None:
                    raise SomaError(
                        "OBJECTIVE_CANCEL_AFTER_EXECUTION",
                        "At least one Objective Task already has accepted start evidence",
                    )
                if execution.state in {"ended", "terminated"}:
                    raise SomaError(
                        "OBJECTIVE_STALE",
                        "Objective member has protected terminal execution state",
                    )
                if execution.state != "not_started" or execution.actual_start_utc is not None:
                    raise IntegrityFailure("Objective cancellation member execution authority is invalid")
                if TaskExecutionService._has_terminal_outcome(
                    uow.connection, member.task_id
                ):
                    raise SomaError(
                        "OBJECTIVE_STALE",
                        "Objective member already has reviewed terminal outcome",
                    )
                authorities.append((task, execution))

            recorded_at = utc_epoch_seconds()
            execution_event_ids = [new_uuid4() for _ in members]
            outcome_event_ids = [new_uuid4() for _ in members]
            review_event_id = new_uuid4()

            def apply(inner: UnitOfWork):
                for member, pair, execution_event_id, outcome_event_id in zip(
                    members,
                    authorities,
                    execution_event_ids,
                    outcome_event_ids,
                    strict=True,
                ):
                    task, execution = pair
                    resulting_execution_revision = execution.revision + 1
                    inner.connection.execute(
                        "INSERT INTO task_execution_events("
                        "execution_event_id,task_id,execution_revision,event_kind,effective_at_utc,"
                        "target_event_id,correction_action,reason_code,recorded_at_utc,command_id"
                        ") VALUES (?,?,?,'manual_cancel',?,NULL,NULL,?,?,?)",
                        (
                            execution_event_id,
                            member.task_id,
                            resulting_execution_revision,
                            effective_cancel_utc,
                            reason,
                            recorded_at,
                            command_id,
                        ),
                    )
                    TaskExecutionService._insert_or_advance_cancel_projection(
                        inner,
                        task_id=member.task_id,
                        authority=execution,
                        event_id=execution_event_id,
                        accepted_cancel=effective_cancel_utc,
                        reason=reason,
                    )
                    inner.connection.execute(
                        "INSERT INTO task_outcome_events("
                        "outcome_event_id,task_id,accepted_outcome,correction_of_event_id,"
                        "reason_code,reviewed_at_utc,command_id"
                        ") VALUES (?,?,'cancelled_without_execution',NULL,?,?,?)",
                        (outcome_event_id, member.task_id, reason, recorded_at, command_id),
                    )
                    inner.connection.execute(
                        "INSERT INTO task_outcome_current("
                        "task_id,outcome_event_id,accepted_outcome,reviewed_at_utc,"
                        "revision,last_command_id"
                        ") VALUES (?,?,'cancelled_without_execution',?,1,?)",
                        (member.task_id, outcome_event_id, recorded_at, command_id),
                    )
                    self._tasks.increment_revision(
                        inner,
                        task_id=member.task_id,
                        expected_revision=task.revision,
                    )

                current_members = self._objectives._load_members(inner.connection, identity)
                review_fingerprint = self._objectives._review_fingerprint(
                    objective_id=identity,
                    objective_revision=objective_revision,
                    superseded_by=None,
                    members=current_members,
                )
                derived = self._objectives._derive_outcome(current_members)
                if derived != "cancelled":
                    raise IntegrityFailure(
                        "Objective cancellation did not derive cancelled aggregate outcome"
                    )
                inner.connection.execute(
                    "INSERT INTO objective_review_events("
                    "objective_review_event_id,objective_id,review_fingerprint,derived_outcome,"
                    "reviewed_at_utc,reason_code,command_id"
                    ") VALUES (?,?,?,'cancelled',?,?,?)",
                    (
                        review_event_id,
                        identity,
                        review_fingerprint,
                        recorded_at,
                        reason,
                        command_id,
                    ),
                )
                rebuilt = self._objectives.rebuild_aggregate(
                    inner,
                    objective_id=identity,
                    command_id=command_id,
                )
                if (
                    rebuilt.execution_state != "reviewed"
                    or rebuilt.aggregate_outcome != "cancelled"
                ):
                    raise IntegrityFailure(
                        "Objective cancellation aggregate rebuild is inconsistent"
                    )
                envelope_row = inner.connection.execute(
                    "SELECT membership_input_fingerprint FROM objective_envelope_projection "
                    "WHERE objective_id=?",
                    (identity,),
                ).fetchone()
                if envelope_row is None:
                    raise IntegrityFailure("Objective cancellation lost envelope authority")
                refs = [AuditResultRef("objective", identity)]
                refs.extend(
                    AuditResultRef("task_outcome_event", event_id)
                    for event_id in outcome_event_ids
                )
                return AuditEventInput(
                    audit_event_id=new_uuid4(),
                    action_type="objective.cancelled",
                    action_version=1,
                    actor_kind=actor_kind,
                    actor_id=actor_id,
                    target_type="objective",
                    target_id=identity,
                    command_id=command_id,
                    reason_category=reason,
                    payload_schema="ObjectiveAuditV1",
                    payload_version=1,
                    payload={
                        "objective_id": identity,
                        "tracking_id": str(objective[1]),
                        "creation_origin": str(objective[2]),
                        "resulting_revision": objective_revision,
                        "membership_input_fingerprint": str(envelope_row[0]),
                        "archive_action": None,
                        "reason_category": reason,
                    },
                    resulting_event_refs=tuple(refs),
                )

            response_refs = [{"type": "objective", "id": identity}]
            response_refs.extend(
                {"type": "task_outcome_event", "id": event_id}
                for event_id in outcome_event_ids
            )
            return PreparedMutation(
                False,
                "objective",
                identity,
                apply,
                response_schema="ObjectiveMutationResultV1",
                response_version=1,
                response={
                    "outcome": "APPLIED",
                    "objective_id": identity,
                    "revision": objective_revision,
                    "result_refs": response_refs,
                },
            )

        return objective_mutation_result_from_execution(
            self._boundary.execute(envelope, prepare)
        )



__all__ = ["ObjectiveService"]
