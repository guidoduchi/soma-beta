from __future__ import annotations

import re
from collections.abc import Sequence
from dataclasses import dataclass

from soma.foundation.application.command_boundary import CommandBoundary, CommandEnvelope, PreparedMutation
from soma.foundation.audit.registry import AuditActionContract, AuditRegistry
from soma.foundation.audit.writer import AuditEventInput, AuditResultRef, AuditWriter
from soma.foundation.errors import IntegrityFailure, SomaError, ValidationError
from soma.foundation.identifiers import new_uuid4, require_uuid4, utc_epoch_seconds
from soma.foundation.persistence.connections import ConnectionFactory
from soma.foundation.persistence.uow import UnitOfWork
from soma.foundation.strict_json import ObjectContract

from ..audit_registry import build_objectives_tasks_audit_registry
from ..contracts.objectives_tasks import (
    WfmActivityRelationshipReviewResult,
    wfm_activity_review_result_from_execution,
)
from ..queries.task_activity_review import (
    WfmActivityReviewEvaluation,
    WfmActivityRelationshipReviewQueryService,
    validate_activity_review_decision,
)
from .task_planning import validate_task_reason_category

_SHA256_RE = re.compile(r"[0-9a-f]{64}\Z")
_ACTIVITY_AUDIT_FIELDS = frozenset(
    {
        "task_id",
        "activity_lineage_id",
        "prior_lineage_id",
        "lineage_event_id",
        "review_fingerprint",
        "reason_category",
    }
)


def _validate_review_fingerprint(value: object) -> str:
    if not isinstance(value, str) or _SHA256_RE.fullmatch(value) is None:
        raise ValidationError("review_fingerprint must be exact lowercase SHA-256 hex")
    return value


def _canonical_seed_pairs(
    value: Sequence[tuple[str, int]],
) -> tuple[tuple[str, int], ...]:
    if isinstance(value, (str, bytes)) or not isinstance(value, Sequence):
        raise ValidationError("seed_tasks must be a sequence of task_id/task_revision pairs")
    if not 2 <= len(value) <= 1000:
        raise ValidationError("seed_tasks must contain from 2 through 1000 WFM Tasks")
    pairs: list[tuple[str, int]] = []
    seen: set[str] = set()
    for item in value:
        if (
            isinstance(item, (str, bytes))
            or not isinstance(item, Sequence)
            or len(item) != 2
        ):
            raise ValidationError("each seed_tasks item must contain task_id and task_revision")
        task_id_raw, revision = item
        if not isinstance(task_id_raw, str):
            raise ValidationError("seed task_id must be canonical UUIDv4 text")
        task_id = require_uuid4(task_id_raw)
        if type(revision) is not int or revision <= 0:
            raise ValidationError("seed task_revision must be a positive integer")
        if task_id in seen:
            raise ValidationError("seed_tasks must contain unique Task identities")
        seen.add(task_id)
        pairs.append((task_id, revision))
    canonical = tuple(pairs)
    if canonical != tuple(sorted(canonical, key=lambda item: item[0])):
        raise ValidationError("seed_tasks must be canonical-sorted by task_id")
    return canonical


def _validate_activity_audit_payload(payload: dict[str, object]) -> None:
    try:
        task_id = payload.get("task_id")
        lineage_id = payload.get("activity_lineage_id")
        prior_lineage_id = payload.get("prior_lineage_id")
        event_id = payload.get("lineage_event_id")
        if not isinstance(task_id, str) or not isinstance(event_id, str):
            raise ValidationError("activity-review audit identities must be UUID text")
        require_uuid4(task_id)
        require_uuid4(event_id)
        if lineage_id is not None:
            if not isinstance(lineage_id, str):
                raise ValidationError("activity lineage identity must be UUID text or null")
            require_uuid4(lineage_id)
        if prior_lineage_id is not None:
            if not isinstance(prior_lineage_id, str):
                raise ValidationError("prior activity lineage identity must be UUID text or null")
            require_uuid4(prior_lineage_id)
    except ValidationError as exc:
        raise SomaError("AUDIT_PAYLOAD_INVALID", "WFM activity-review audit identity is invalid") from exc
    fingerprint = payload.get("review_fingerprint")
    if fingerprint is not None and (not isinstance(fingerprint, str) or _SHA256_RE.fullmatch(fingerprint) is None):
        raise SomaError("AUDIT_PAYLOAD_INVALID", "WFM activity-review audit fingerprint is invalid")
    reason = payload.get("reason_category")
    if not isinstance(reason, str):
        raise SomaError("AUDIT_PAYLOAD_INVALID", "WFM activity-review reason must be text")
    try:
        encoded = reason.encode("utf-8", errors="strict")
    except UnicodeEncodeError as exc:
        raise SomaError("AUDIT_PAYLOAD_INVALID", "WFM activity-review reason is invalid Unicode") from exc
    if not encoded or len(encoded) > 128 or "\x00" in reason or "\r" in reason or "\n" in reason:
        raise SomaError("AUDIT_PAYLOAD_INVALID", "WFM activity-review reason violates its bound")


def _build_activity_review_audit_registry() -> AuditRegistry:
    registry = build_objectives_tasks_audit_registry()
    registry.register(
        AuditActionContract(
            action_type="task.activity_relationship_reviewed",
            action_version=1,
            payload_schema="TaskActivityAuditV1",
            payload_version=1,
            payload_contract=ObjectContract(
                name="TaskActivityAuditV1",
                version=1,
                required_fields=_ACTIVITY_AUDIT_FIELDS,
                allowed_fields=_ACTIVITY_AUDIT_FIELDS,
                max_depth=4,
                max_collection_items=16,
                max_utf8_bytes=16_384,
            ),
            sensitivity_validator=_validate_activity_audit_payload,
        )
    )
    return registry


@dataclass(frozen=True, slots=True)
class _TaskLineageMutation:
    task_id: str
    expected_task_revision: int
    prior_lineage_id: str | None
    expected_lineage_revision: int
    expected_last_event_id: str | None
    new_lineage_id: str
    lineage_event_id: str
    audit_event_id: str
    resulting_task_revision: int
    resulting_lineage_revision: int


@dataclass(frozen=True, slots=True)
class _ReviewMutationPlan:
    new_lineage_ids: tuple[str, ...]
    task_mutations: tuple[_TaskLineageMutation, ...]

    @property
    def primary_event_id(self) -> str:
        if not self.task_mutations:
            raise IntegrityFailure("material WFM activity review has no Task mutation")
        return self.task_mutations[0].lineage_event_id


class WfmActivityRelationshipReviewService:
    """Preview-bound multi-Task WFM activity-lineage review authority."""

    def __init__(self, connection_factory: ConnectionFactory) -> None:
        self._reviews = WfmActivityRelationshipReviewQueryService(connection_factory)
        self._boundary = CommandBoundary(
            connection_factory,
            AuditWriter(_build_activity_review_audit_registry()),
        )

    @staticmethod
    def _require_seed_freshness(
        uow: UnitOfWork,
        seed_pairs: tuple[tuple[str, int], ...],
    ) -> None:
        seen_task_nos: set[str] = set()
        for task_id, expected_revision in seed_pairs:
            row = uow.connection.execute(
                "SELECT t.task_kind,t.revision,w.task_no FROM tasks t "
                "LEFT JOIN wfm_task_identities w ON w.task_id=t.task_id WHERE t.task_id=?",
                (task_id,),
            ).fetchone()
            if row is None or str(row[0]) != "wfm" or row[2] is None:
                raise SomaError("TASK_NOT_FOUND", "reviewed Task is not current WFM Task authority")
            revision = row[1]
            if type(revision) is not int or revision <= 0:
                raise IntegrityFailure("stored Task revision is invalid")
            if int(revision) != expected_revision:
                raise SomaError("TASK_STALE", "reviewed Task revision changed since preview")
            task_no = str(row[2])
            if task_no in seen_task_nos:
                raise IntegrityFailure("review seed contains duplicate canonical WFM Task No authority")
            seen_task_nos.add(task_no)

    @staticmethod
    def _plan_material_review(
        evaluation: WfmActivityReviewEvaluation,
    ) -> _ReviewMutationPlan:
        authorities = evaluation.authorities
        if not authorities:
            raise IntegrityFailure("WFM activity review resolved an empty affected set")

        target_by_task: dict[str, str] = {}
        new_lineages: list[str] = []
        changed_task_ids: set[str]

        if evaluation.decision == "distinct_activity":
            changed_task_ids = {authority.task_id for authority in authorities}
            for authority in authorities:
                lineage_id = new_uuid4()
                target_by_task[authority.task_id] = lineage_id
                new_lineages.append(lineage_id)
        else:
            current_lineages = {authority.activity_lineage_id for authority in authorities}
            if None not in current_lineages and len(current_lineages) == 1:
                target_lineage_id = next(iter(current_lineages))
                assert target_lineage_id is not None
                changed_task_ids = {
                    authority.task_id
                    for authority in authorities
                    if authority.last_decision != evaluation.decision
                }
            else:
                target_lineage_id = new_uuid4()
                new_lineages.append(target_lineage_id)
                changed_task_ids = {authority.task_id for authority in authorities}
            for authority in authorities:
                target_by_task[authority.task_id] = target_lineage_id

        if not changed_task_ids:
            raise IntegrityFailure("material WFM activity review resolved no changed Task")

        mutations: list[_TaskLineageMutation] = []
        for authority in authorities:
            if authority.task_id not in changed_task_ids:
                continue
            mutations.append(
                _TaskLineageMutation(
                    task_id=authority.task_id,
                    expected_task_revision=authority.task_revision,
                    prior_lineage_id=authority.activity_lineage_id,
                    expected_lineage_revision=authority.lineage_revision,
                    expected_last_event_id=authority.last_lineage_event_id,
                    new_lineage_id=target_by_task[authority.task_id],
                    lineage_event_id=new_uuid4(),
                    audit_event_id=new_uuid4(),
                    resulting_task_revision=authority.task_revision + 1,
                    resulting_lineage_revision=authority.lineage_revision + 1,
                )
            )
        return _ReviewMutationPlan(
            new_lineage_ids=tuple(new_lineages),
            task_mutations=tuple(mutations),
        )

    @staticmethod
    def _apply_material_review(
        uow: UnitOfWork,
        *,
        command_id: str,
        evaluation: WfmActivityReviewEvaluation,
        plan: _ReviewMutationPlan,
        reason_category: str,
        actor_kind: str,
        actor_id: str | None,
    ) -> tuple[AuditEventInput, ...]:
        now = utc_epoch_seconds()
        for lineage_id in plan.new_lineage_ids:
            uow.connection.execute(
                "INSERT INTO task_activity_lineages(activity_lineage_id,created_at_utc,created_command_id) "
                "VALUES (?,?,?)",
                (lineage_id, now, command_id),
            )

        audits: list[AuditEventInput] = []
        for mutation in plan.task_mutations:
            uow.connection.execute(
                "INSERT INTO task_activity_lineage_events("
                "lineage_event_id,task_id,prior_lineage_id,new_lineage_id,reason_code,recorded_at_utc,command_id"
                ") VALUES (?,?,?,?,?,?,?)",
                (
                    mutation.lineage_event_id,
                    mutation.task_id,
                    mutation.prior_lineage_id,
                    mutation.new_lineage_id,
                    evaluation.decision,
                    now,
                    command_id,
                ),
            )
            if mutation.expected_lineage_revision == 0:
                if mutation.expected_last_event_id is not None or mutation.prior_lineage_id is not None:
                    raise IntegrityFailure("unassigned Task unexpectedly carries current lineage history")
                uow.connection.execute(
                    "INSERT INTO task_activity_lineage_current("
                    "task_id,activity_lineage_id,revision,last_event_id) VALUES (?,?,1,?)",
                    (mutation.task_id, mutation.new_lineage_id, mutation.lineage_event_id),
                )
            else:
                if mutation.expected_last_event_id is None or mutation.prior_lineage_id is None:
                    raise IntegrityFailure("assigned Task is missing guarded current lineage identity")
                updated_lineage = uow.connection.execute(
                    "UPDATE task_activity_lineage_current "
                    "SET activity_lineage_id=?,revision=revision+1,last_event_id=? "
                    "WHERE task_id=? AND activity_lineage_id=? AND revision=? AND last_event_id=?",
                    (
                        mutation.new_lineage_id,
                        mutation.lineage_event_id,
                        mutation.task_id,
                        mutation.prior_lineage_id,
                        mutation.expected_lineage_revision,
                        mutation.expected_last_event_id,
                    ),
                )
                if updated_lineage.rowcount != 1:
                    raise IntegrityFailure("Task activity-lineage authority changed during guarded review")

            updated_task = uow.connection.execute(
                "UPDATE tasks SET revision=revision+1 WHERE task_id=? AND revision=?",
                (mutation.task_id, mutation.expected_task_revision),
            )
            if updated_task.rowcount != 1:
                raise IntegrityFailure("Task revision changed during guarded activity review")

            audits.append(
                AuditEventInput(
                    audit_event_id=mutation.audit_event_id,
                    action_type="task.activity_relationship_reviewed",
                    action_version=1,
                    actor_kind=actor_kind,
                    actor_id=actor_id,
                    target_type="task_activity_lineage",
                    target_id=mutation.new_lineage_id,
                    reason_category=reason_category,
                    command_id=command_id,
                    payload_schema="TaskActivityAuditV1",
                    payload_version=1,
                    payload={
                        "task_id": mutation.task_id,
                        "activity_lineage_id": mutation.new_lineage_id,
                        "prior_lineage_id": mutation.prior_lineage_id,
                        "lineage_event_id": mutation.lineage_event_id,
                        "review_fingerprint": evaluation.review_fingerprint,
                        "reason_category": reason_category,
                    },
                    resulting_event_refs=(AuditResultRef("task", mutation.task_id),),
                )
            )
        return tuple(audits)

    def review_wfm_activity_relationship(
        self,
        *,
        command_id: str,
        seed_tasks: Sequence[tuple[str, int]],
        decision: str,
        review_fingerprint: str,
        reason_category: str,
        actor_kind: str = "local_user",
        actor_id: str | None = None,
    ) -> WfmActivityRelationshipReviewResult:
        seed_pairs = _canonical_seed_pairs(seed_tasks)
        canonical_decision = validate_activity_review_decision(decision)
        fingerprint = _validate_review_fingerprint(review_fingerprint)
        reason = validate_task_reason_category(reason_category)
        seed_ids = tuple(task_id for task_id, _ in seed_pairs)

        envelope = CommandEnvelope(
            command_id=command_id,
            command_type="ReviewWfmActivityRelationship",
            target_type="task_activity_lineage",
            target_id=None,
            semantic_payload={
                "seed_task_ids": list(seed_ids),
                "decision": canonical_decision,
                "reason_category": reason,
            },
            base_revisions={task_id: revision for task_id, revision in seed_pairs},
            authorizing_fingerprints={"review_fingerprint": fingerprint},
        )

        def prepare(uow: UnitOfWork) -> PreparedMutation:
            self._require_seed_freshness(uow, seed_pairs)
            evaluation = self._reviews.evaluate_connection(
                uow.connection,
                seed_task_ids=seed_ids,
                decision=canonical_decision,
            )
            if evaluation.review_fingerprint != fingerprint:
                raise SomaError(
                    "TASK_ACTIVITY_REVIEW_STALE",
                    "WFM activity-review authority changed since preview",
                )

            if evaluation.semantic_no_change:
                return PreparedMutation(
                    True,
                    None,
                    None,
                    response_schema="WfmActivityRelationshipReviewResultV1",
                    response_version=1,
                    response={
                        "outcome": "NO_CHANGE",
                        "decision": canonical_decision,
                        "review_fingerprint": fingerprint,
                        "affected_task_count": evaluation.affected_task_count,
                        "result_refs": [],
                    },
                )

            plan = self._plan_material_review(evaluation)
            primary_event_id = plan.primary_event_id
            response_refs = [
                {"type": "task_activity_lineage_event", "id": primary_event_id}
            ]
            if len(plan.new_lineage_ids) == 1:
                response_refs.append(
                    {"type": "task_activity_lineage", "id": plan.new_lineage_ids[0]}
                )

            def apply(inner: UnitOfWork) -> tuple[AuditEventInput, ...]:
                return self._apply_material_review(
                    inner,
                    command_id=command_id,
                    evaluation=evaluation,
                    plan=plan,
                    reason_category=reason,
                    actor_kind=actor_kind,
                    actor_id=actor_id,
                )

            return PreparedMutation(
                False,
                "task_activity_lineage_event",
                primary_event_id,
                apply,
                response_schema="WfmActivityRelationshipReviewResultV1",
                response_version=1,
                response={
                    "outcome": "APPLIED",
                    "decision": canonical_decision,
                    "review_fingerprint": fingerprint,
                    "affected_task_count": evaluation.affected_task_count,
                    "result_refs": response_refs,
                },
            )

        return wfm_activity_review_result_from_execution(self._boundary.execute(envelope, prepare))


@dataclass(frozen=True, slots=True)
class WfmActivityReviewCommandContext:
    command_id: str
    actor_kind: str = "local_user"
    actor_id: str | None = None


@dataclass(frozen=True, slots=True)
class WfmActivityReviewParticipantResult:
    outcome: str
    decision: str
    review_fingerprint: str
    affected_task_count: int
    result_refs: tuple[tuple[str, str], ...]


class WfmActivityReviewParticipant:
    """Same-UoW activity-lineage review participant consumed by LLD-04."""

    @staticmethod
    def apply_reviewed_activity_relationship(
        uow: UnitOfWork,
        *,
        seed_tasks: Sequence[tuple[str, int]],
        decision: str,
        review_fingerprint: str,
        reason_category: str,
        command_context: WfmActivityReviewCommandContext,
    ) -> WfmActivityReviewParticipantResult:
        if not isinstance(command_context, WfmActivityReviewCommandContext):
            raise ValidationError("command_context must be WfmActivityReviewCommandContext")
        command_id = require_uuid4(command_context.command_id)
        if uow.connection.execute(
            "SELECT 1 FROM command_receipts WHERE command_id=?",
            (command_id,),
        ).fetchone() is None:
            raise IntegrityFailure("WFM activity-review participant requires caller-owned command receipt")
        seed_pairs = _canonical_seed_pairs(seed_tasks)
        canonical_decision = validate_activity_review_decision(decision)
        fingerprint = _validate_review_fingerprint(review_fingerprint)
        reason = validate_task_reason_category(reason_category)
        seed_ids = tuple(task_id for task_id, _ in seed_pairs)

        WfmActivityRelationshipReviewService._require_seed_freshness(uow, seed_pairs)
        evaluation = WfmActivityRelationshipReviewQueryService.evaluate_connection(
            uow.connection,
            seed_task_ids=seed_ids,
            decision=canonical_decision,
        )
        if evaluation.review_fingerprint != fingerprint:
            raise SomaError(
                "TASK_ACTIVITY_REVIEW_STALE",
                "WFM activity-review authority changed since preview",
            )
        if evaluation.semantic_no_change:
            return WfmActivityReviewParticipantResult(
                outcome="NO_CHANGE",
                decision=canonical_decision,
                review_fingerprint=fingerprint,
                affected_task_count=evaluation.affected_task_count,
                result_refs=(),
            )

        plan = WfmActivityRelationshipReviewService._plan_material_review(evaluation)
        audits = WfmActivityRelationshipReviewService._apply_material_review(
            uow,
            command_id=command_id,
            evaluation=evaluation,
            plan=plan,
            reason_category=reason,
            actor_kind=command_context.actor_kind,
            actor_id=command_context.actor_id,
        )
        audit_writer = AuditWriter(_build_activity_review_audit_registry())
        for audit in audits:
            audit_writer.write(uow, audit)

        refs: list[tuple[str, str]] = [
            ("task_activity_lineage_event", plan.primary_event_id)
        ]
        if len(plan.new_lineage_ids) == 1:
            refs.append(("task_activity_lineage", plan.new_lineage_ids[0]))
        return WfmActivityReviewParticipantResult(
            outcome="APPLIED",
            decision=canonical_decision,
            review_fingerprint=fingerprint,
            affected_task_count=evaluation.affected_task_count,
            result_refs=tuple(refs),
        )
