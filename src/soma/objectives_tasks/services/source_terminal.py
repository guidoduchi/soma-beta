from __future__ import annotations

import hmac
import re
from collections.abc import Sequence
from typing import Any

from soma.foundation.application.command_boundary import CommandBoundary, CommandEnvelope, PreparedMutation
from soma.foundation.audit.registry import AuditActionContract
from soma.foundation.audit.writer import AuditEventInput, AuditResultRef, AuditWriter
from soma.foundation.errors import IntegrityFailure, SomaError, ValidationError
from soma.foundation.identifiers import new_uuid4, require_uuid4, utc_epoch_seconds
from soma.foundation.persistence.connections import ConnectionFactory
from soma.foundation.persistence.uow import UnitOfWork
from soma.foundation.strict_json import ObjectContract, sha256_canonical_json
from soma.tickets.queries.rfc_terminal_cascade import (
    RfcTerminalCascadeImpactItem,
    RfcTerminalCascadeImpactProviderPage,
    RfcTerminalCascadeProposalSnapshot,
)
from soma.tickets.rfc_terminal_cascade import RfcTerminalCascadeWfmMember
from soma.tickets.rfc_terminal_review import (
    RfcTerminalCascadeExecutionCommandContext,
    RfcTerminalCascadeParticipantApplyResult,
)

from ..audit_registry import build_objectives_tasks_audit_registry
from ..contracts.objectives_tasks import TaskMutationResult, task_mutation_result_from_execution
from ..queries.cascade import RfcTerminalCascadeQueryService
from ..repositories.objectives import ObjectiveProjectionRepository
from ..repositories.tasks import TaskRepository, WfmTaskRepository
from ..source_terminal_authority import (
    current_source_projection,
    get_source_terminal_review,
    source_terminal_review_fingerprint,
)
from .task_execution import TaskExecutionService
from .task_planning import validate_task_reason_category

_SHA256_RE = re.compile(r"[0-9a-f]{64}\Z")
_DECISIONS = frozenset({"retain_local_work", "terminate_local_work"})
_AUDIT_FIELDS = frozenset(
    {
        "task_id",
        "review_id",
        "source_projection_revision",
        "source_evidence_id",
        "review_fingerprint",
        "accepted_local_consequence",
        "execution_event_id",
        "reason_category",
    }
)

_CASCADE_AUDIT_FIELDS = frozenset(
    {
        "task_id",
        "proposal_id",
        "execution_event_id",
        "prior_execution_revision",
        "prior_execution_state",
        "resulting_execution_revision",
        "reviewed_preview_fingerprint",
    }
)


def _require_positive_revision(value: int, *, label: str) -> int:
    if type(value) is not int or value <= 0:
        raise ValidationError(f"{label} must be a positive integer")
    return value


def _require_sha256(value: object, *, label: str) -> str:
    if not isinstance(value, str) or _SHA256_RE.fullmatch(value) is None:
        raise ValidationError(f"{label} must be lowercase SHA-256 hex")
    return value


def _require_decision(value: object) -> str:
    if value not in _DECISIONS:
        raise ValidationError("decision must be retain_local_work or terminate_local_work")
    return str(value)


def _validate_source_terminal_audit(payload: dict[str, object]) -> None:
    try:
        task_id = payload.get("task_id")
        review_id = payload.get("review_id")
        source_evidence_id = payload.get("source_evidence_id")
        execution_event_id = payload.get("execution_event_id")
        for value in (task_id, review_id, source_evidence_id):
            if not isinstance(value, str):
                raise ValidationError("source-terminal audit identity must be UUID text")
            require_uuid4(value)
        if execution_event_id is not None:
            if not isinstance(execution_event_id, str):
                raise ValidationError("execution_event_id must be UUID text or null")
            require_uuid4(execution_event_id)
    except ValidationError as exc:
        raise SomaError("AUDIT_PAYLOAD_INVALID", "source-terminal audit identity is invalid") from exc

    revision = payload.get("source_projection_revision")
    if type(revision) is not int or revision <= 0:
        raise SomaError("AUDIT_PAYLOAD_INVALID", "source-terminal audit source revision is invalid")
    fingerprint = payload.get("review_fingerprint")
    if not isinstance(fingerprint, str) or _SHA256_RE.fullmatch(fingerprint) is None:
        raise SomaError("AUDIT_PAYLOAD_INVALID", "source-terminal audit fingerprint is invalid")
    decision = payload.get("accepted_local_consequence")
    if decision not in _DECISIONS:
        raise SomaError("AUDIT_PAYLOAD_INVALID", "source-terminal audit decision is invalid")
    if (decision == "retain_local_work") != (payload.get("execution_event_id") is None):
        raise SomaError("AUDIT_PAYLOAD_INVALID", "source-terminal audit consequence identity is inconsistent")
    try:
        validate_task_reason_category(payload.get("reason_category"))
    except ValidationError as exc:
        raise SomaError("AUDIT_PAYLOAD_INVALID", "source-terminal audit reason is invalid") from exc



def _validate_rfc_terminal_cascade_audit(payload: dict[str, object]) -> None:
    try:
        for field in ("task_id", "proposal_id", "execution_event_id"):
            value = payload.get(field)
            if not isinstance(value, str):
                raise ValidationError(f"{field} must be UUID text")
            require_uuid4(value)
    except ValidationError as exc:
        raise SomaError(
            "AUDIT_PAYLOAD_INVALID",
            "RFC terminal cascade audit identity is invalid",
        ) from exc
    prior_revision = payload.get("prior_execution_revision")
    resulting_revision = payload.get("resulting_execution_revision")
    if (
        type(prior_revision) is not int
        or prior_revision < 0
        or type(resulting_revision) is not int
        or resulting_revision != prior_revision + 1
    ):
        raise SomaError(
            "AUDIT_PAYLOAD_INVALID",
            "RFC terminal cascade execution revisions are invalid",
        )
    if payload.get("prior_execution_state") not in {"not_started", "in_progress"}:
        raise SomaError(
            "AUDIT_PAYLOAD_INVALID",
            "RFC terminal cascade prior execution state is invalid",
        )
    fingerprint = payload.get("reviewed_preview_fingerprint")
    if not isinstance(fingerprint, str) or _SHA256_RE.fullmatch(fingerprint) is None:
        raise SomaError(
            "AUDIT_PAYLOAD_INVALID",
            "RFC terminal cascade reviewed preview fingerprint is invalid",
        )

def _build_source_terminal_audit_registry():
    registry = build_objectives_tasks_audit_registry()
    registry.register(
        AuditActionContract(
            action_type="task.source_terminal_consequence_resolved",
            action_version=1,
            payload_schema="TaskSourceTerminalAuditV1",
            payload_version=1,
            payload_contract=ObjectContract(
                name="TaskSourceTerminalAuditV1",
                version=1,
                required_fields=_AUDIT_FIELDS,
                allowed_fields=_AUDIT_FIELDS,
                max_depth=3,
                max_collection_items=16,
                max_utf8_bytes=16_384,
            ),
            sensitivity_validator=_validate_source_terminal_audit,
        )
    )
    registry.register(
        AuditActionContract(
            action_type="task.rfc_terminal_cascade_applied",
            action_version=1,
            payload_schema="TaskRfcTerminalCascadeAuditV1",
            payload_version=1,
            payload_contract=ObjectContract(
                name="TaskRfcTerminalCascadeAuditV1",
                version=1,
                required_fields=_CASCADE_AUDIT_FIELDS,
                allowed_fields=_CASCADE_AUDIT_FIELDS,
                max_depth=3,
                max_collection_items=16,
                max_utf8_bytes=16_384,
            ),
            sensitivity_validator=_validate_rfc_terminal_cascade_audit,
        )
    )
    return registry


class WfmSourceTerminalService:
    """Resolve reviewed WFM terminal source evidence into an explicit local consequence."""

    def __init__(self, connection_factory: ConnectionFactory) -> None:
        self._tasks = TaskRepository()
        self._objectives = ObjectiveProjectionRepository()
        self._boundary = CommandBoundary(
            connection_factory,
            AuditWriter(_build_source_terminal_audit_registry()),
        )

    @staticmethod
    def _require_current_review(
        connection: Any,
        *,
        review_id: str,
        task_id: str,
        source_projection_revision: int,
        input_fingerprint: str,
    ):
        review = get_source_terminal_review(connection, review_id)
        if review is None:
            raise SomaError("WFM_SOURCE_TERMINAL_STALE", "WFM source-terminal review is missing")
        if (
            review.task_id != task_id
            or review.source_projection_revision != source_projection_revision
            or review.input_fingerprint != input_fingerprint
            or review.state != "pending"
            or review.revision != 1
            or review.local_consequence_event_id is not None
            or review.decided_at_utc is not None
        ):
            raise SomaError("WFM_SOURCE_TERMINAL_STALE", "WFM source-terminal review changed after review")
        return review

    @staticmethod
    def _advance_termination_projection(
        uow: UnitOfWork,
        *,
        task_id: str,
        authority: Any,
        execution_event_id: str,
        reason: str,
    ) -> None:
        if authority.revision == 0:
            uow.connection.execute(
                "INSERT INTO task_execution_projection(task_id,execution_state,actual_start_utc,actual_end_utc,"
                "effective_termination_utc,termination_reason,revision,last_event_id) "
                "VALUES (?,'terminated',NULL,NULL,NULL,?,1,?)",
                (task_id, reason, execution_event_id),
            )
            return
        updated = uow.connection.execute(
            "UPDATE task_execution_projection SET execution_state='terminated',actual_end_utc=NULL,"
            "effective_termination_utc=NULL,termination_reason=?,revision=revision+1,last_event_id=? "
            "WHERE task_id=? AND revision=?",
            (reason, execution_event_id, task_id, authority.revision),
        )
        if updated.rowcount != 1:
            raise IntegrityFailure("Task execution projection changed during source-terminal consequence")

    def resolve_wfm_source_terminal_consequence(
        self,
        *,
        command_id: str,
        source_terminal_review_id: str,
        task_id: str,
        source_projection_revision: int,
        input_fingerprint: str,
        decision: str,
        reason_category: str,
        actor_kind: str = "local_user",
        actor_id: str | None = None,
    ) -> TaskMutationResult:
        canonical_review_id = require_uuid4(source_terminal_review_id)
        canonical_task_id = require_uuid4(task_id)
        expected_source_revision = _require_positive_revision(
            source_projection_revision,
            label="source_projection_revision",
        )
        reviewed_fingerprint = _require_sha256(input_fingerprint, label="input_fingerprint")
        accepted_decision = _require_decision(decision)
        reason = validate_task_reason_category(reason_category)

        envelope = CommandEnvelope(
            command_id=command_id,
            command_type="ResolveWfmSourceTerminalConsequence",
            target_type="task",
            target_id=canonical_task_id,
            semantic_payload={
                "source_terminal_review_id": canonical_review_id,
                "source_projection_revision": expected_source_revision,
                "input_fingerprint": reviewed_fingerprint,
                "decision": accepted_decision,
                "reason_category": reason,
            },
        )

        def prepare(uow: UnitOfWork) -> PreparedMutation:
            task = self._tasks.get(uow.connection, canonical_task_id)
            if task is None:
                raise SomaError("TASK_NOT_FOUND", "Task does not exist")
            if task.task_kind != "wfm" or WfmTaskRepository.get_identity(uow.connection, canonical_task_id) is None:
                raise IntegrityFailure("source-terminal review target lacks canonical WFM identity")

            review = self._require_current_review(
                uow.connection,
                review_id=canonical_review_id,
                task_id=canonical_task_id,
                source_projection_revision=expected_source_revision,
                input_fingerprint=reviewed_fingerprint,
            )
            source = current_source_projection(uow.connection, canonical_task_id)
            if (
                source is None
                or source.provider_lifecycle_class not in {"complete", "plan_cancel"}
                or source.source_projection_revision != expected_source_revision
                or source.provider_lifecycle_class != review.provider_lifecycle_class
                or source.accepted_source_observation_id is None
            ):
                raise SomaError("WFM_SOURCE_TERMINAL_STALE", "accepted WFM terminal source authority changed")

            current_fingerprint = source_terminal_review_fingerprint(uow.connection, canonical_task_id)
            if (
                not hmac.compare_digest(review.input_fingerprint, reviewed_fingerprint)
                or not hmac.compare_digest(current_fingerprint, reviewed_fingerprint)
            ):
                raise SomaError("WFM_SOURCE_TERMINAL_STALE", "WFM source-terminal review authority changed")

            execution = TaskExecutionService._execution_authority(uow.connection, canonical_task_id)
            if accepted_decision == "terminate_local_work" and execution.state in {"ended", "terminated"}:
                raise SomaError("TASK_EXECUTION_ALREADY_TERMINAL", "Task execution is already terminal")

            now = utc_epoch_seconds()
            audit_event_id = new_uuid4()
            execution_event_id = new_uuid4() if accepted_decision == "terminate_local_work" else None
            resulting_task_revision = task.revision + (1 if execution_event_id is not None else 0)
            resulting_execution_revision = execution.revision + (1 if execution_event_id is not None else 0)
            result_refs = [{"type": "wfm_source_terminal_review", "id": canonical_review_id}]
            if execution_event_id is not None:
                result_refs.append({"type": "task_execution_event", "id": execution_event_id})

            def apply(inner: UnitOfWork) -> AuditEventInput:
                if execution_event_id is not None:
                    inner.connection.execute(
                        "INSERT INTO task_execution_events(execution_event_id,task_id,execution_revision,event_kind,"
                        "effective_at_utc,target_event_id,correction_action,reason_code,recorded_at_utc,command_id) "
                        "VALUES (?,?,?,'source_terminal_consequence',NULL,NULL,NULL,?,?,?)",
                        (
                            execution_event_id,
                            canonical_task_id,
                            resulting_execution_revision,
                            reason,
                            now,
                            command_id,
                        ),
                    )
                    self._advance_termination_projection(
                        inner,
                        task_id=canonical_task_id,
                        authority=execution,
                        execution_event_id=execution_event_id,
                        reason=reason,
                    )
                    self._tasks.increment_revision(
                        inner,
                        task_id=canonical_task_id,
                        expected_revision=task.revision,
                    )

                updated = inner.connection.execute(
                    "UPDATE wfm_source_terminal_reviews SET state=?,local_consequence_event_id=?,"
                    "revision=revision+1,decided_at_utc=?,last_command_id=? "
                    "WHERE source_terminal_review_id=? AND task_id=? AND state='pending' AND revision=?",
                    (
                        accepted_decision,
                        execution_event_id,
                        now,
                        command_id,
                        canonical_review_id,
                        canonical_task_id,
                        review.revision,
                    ),
                )
                if updated.rowcount != 1:
                    raise SomaError("WFM_SOURCE_TERMINAL_STALE", "WFM source-terminal review changed during decision")

                if execution_event_id is not None:
                    membership = self._objectives.current_membership_for_task(
                        inner.connection,
                        canonical_task_id,
                    )
                    if membership is not None:
                        self._objectives.rebuild_aggregate(
                            inner,
                            objective_id=membership.objective_id,
                            command_id=command_id,
                        )

                refs = [AuditResultRef("wfm_source_terminal_review", canonical_review_id)]
                if execution_event_id is not None:
                    refs.append(AuditResultRef("task_execution_event", execution_event_id))
                return AuditEventInput(
                    audit_event_id=audit_event_id,
                    action_type="task.source_terminal_consequence_resolved",
                    action_version=1,
                    actor_kind=actor_kind,
                    actor_id=actor_id,
                    target_type="task",
                    target_id=canonical_task_id,
                    reason_category=reason,
                    command_id=command_id,
                    payload_schema="TaskSourceTerminalAuditV1",
                    payload_version=1,
                    payload={
                        "task_id": canonical_task_id,
                        "review_id": canonical_review_id,
                        "source_projection_revision": expected_source_revision,
                        "source_evidence_id": source.accepted_source_observation_id,
                        "review_fingerprint": reviewed_fingerprint,
                        "accepted_local_consequence": accepted_decision,
                        "execution_event_id": execution_event_id,
                        "reason_category": reason,
                    },
                    resulting_event_refs=tuple(refs),
                )

            return PreparedMutation(
                False,
                "wfm_source_terminal_review",
                canonical_review_id,
                apply,
                response_schema="TaskMutationResultV1",
                response_version=1,
                response={
                    "outcome": "APPLIED",
                    "task_id": canonical_task_id,
                    "revision": resulting_task_revision,
                    "result_refs": result_refs,
                },
            )

        return task_mutation_result_from_execution(self._boundary.execute(envelope, prepare))


class RfcTerminalTaskParticipant:
    """LLD-03 same-UoW Task/Objective participant for RFC terminal cascades."""

    @staticmethod
    def _proposal_id(proposal_snapshot: RfcTerminalCascadeProposalSnapshot) -> str:
        if not isinstance(proposal_snapshot, RfcTerminalCascadeProposalSnapshot):
            raise ValidationError(
                "proposal_snapshot must be RfcTerminalCascadeProposalSnapshot"
            )
        return require_uuid4(proposal_snapshot.proposal_id)

    @classmethod
    def _assert_snapshot_matches(
        cls,
        preview: dict[str, object],
        proposal_snapshot: RfcTerminalCascadeProposalSnapshot,
    ) -> None:
        proposal_id = cls._proposal_id(proposal_snapshot)
        if str(preview.get("proposal_id")) != proposal_id:
            raise SomaError(
                "RFC_TERMINAL_CASCADE_STALE",
                "RFC terminal cascade proposal identity changed",
            )
        if (
            int(preview.get("proposal_revision", -1))
            != proposal_snapshot.proposal_revision
            or str(preview.get("scope_fingerprint"))
            != proposal_snapshot.scope_fingerprint
        ):
            raise SomaError(
                "RFC_TERMINAL_CASCADE_STALE",
                "RFC terminal cascade proposal authority changed",
            )
        normalized = tuple(
            sorted(
                (
                    member.task_id,
                    member.owning_rfc_id,
                    member.captured_task_revision,
                    member.captured_task_no,
                )
                for member in proposal_snapshot.wfm_members
            )
        )
        current = tuple(
            sorted(
                (
                    str(item["task_id"]),
                    str(item["owning_rfc_id"]),
                    int(item["task_revision"]),
                    str(item["task_no"]),
                )
                for item in preview.get("captured_wfms", [])
            )
        )
        if normalized != current:
            raise SomaError(
                "RFC_TERMINAL_CASCADE_STALE",
                "RFC terminal cascade captured WFM authority changed",
            )

    @staticmethod
    def _applicable_wfms(
        connection: Any,
        rfc_ids: Sequence[str],
    ) -> tuple[RfcTerminalCascadeWfmMember, ...]:
        if isinstance(rfc_ids, (str, bytes)) or not isinstance(rfc_ids, Sequence):
            raise ValidationError("rfc_ids must be a sequence")
        canonical = tuple(sorted({require_uuid4(value) for value in rfc_ids}))
        if not canonical:
            return ()
        placeholders = ",".join("?" for _ in canonical)
        rows = connection.execute(
            "SELECT t.task_id,w.current_rfc_id,t.revision,w.task_no "
            "FROM tasks t JOIN wfm_task_identities w ON w.task_id=t.task_id "
            "LEFT JOIN task_execution_projection e ON e.task_id=t.task_id "
            "LEFT JOIN task_outcome_current oc ON oc.task_id=t.task_id "
            f"WHERE w.current_rfc_id IN ({placeholders}) "
            "AND COALESCE(e.execution_state,'not_started') "
            "NOT IN ('ended','terminated') AND oc.task_id IS NULL "
            "ORDER BY w.current_rfc_id,t.task_id",
            canonical,
        ).fetchall()
        return tuple(
            RfcTerminalCascadeWfmMember(
                task_id=str(row[0]),
                owning_rfc_id=str(row[1]),
                captured_task_revision=int(row[2]),
                captured_task_no=str(row[3]),
            )
            for row in rows
        )

    @classmethod
    def capture_applicable_wfms(
        cls,
        uow: UnitOfWork,
        rfc_ids: tuple[str, ...],
    ) -> tuple[RfcTerminalCascadeWfmMember, ...]:
        return cls._applicable_wfms(uow.connection, rfc_ids)

    @classmethod
    def snapshot_applicable_wfms(
        cls,
        snapshot: Any,
        rfc_ids: tuple[str, ...],
    ) -> tuple[RfcTerminalCascadeWfmMember, ...]:
        connection = getattr(snapshot, "connection", snapshot)
        return cls._applicable_wfms(connection, rfc_ids)

    @classmethod
    def preview_terminal_cascade(
        cls,
        snapshot: Any,
        proposal_snapshot: RfcTerminalCascadeProposalSnapshot,
        after_key: tuple[str, str] | None,
        limit: int,
    ) -> RfcTerminalCascadeImpactProviderPage:
        if type(limit) is not int or not 1 <= limit <= 500:
            raise ValidationError("terminal cascade participant page size must be 1..500")
        if after_key is not None:
            if (
                not isinstance(after_key, tuple)
                or len(after_key) != 2
                or not isinstance(after_key[0], str)
                or not isinstance(after_key[1], str)
            ):
                raise ValidationError("terminal cascade participant cursor key is invalid")
            require_uuid4(after_key[1])
        connection = getattr(snapshot, "connection", snapshot)
        preview = RfcTerminalCascadeQueryService.preview_with_reader(
            connection,
            cls._proposal_id(proposal_snapshot),
        )
        if preview["status"] != "READY":
            return RfcTerminalCascadeImpactProviderPage(
                domain="TASKS_OBJECTIVES",
                status="INDETERMINATE",
                exact_count=None,
                provider_fingerprint=None,
                items=(),
                continuation_key=None,
                warning_code=str(preview["warning_code"]),
            )
        try:
            cls._assert_snapshot_matches(preview, proposal_snapshot)
        except SomaError:
            return RfcTerminalCascadeImpactProviderPage(
                domain="TASKS_OBJECTIVES",
                status="INDETERMINATE",
                exact_count=None,
                provider_fingerprint=None,
                items=(),
                continuation_key=None,
                warning_code="CAPTURED_WFM_STALE",
            )
        ordered = tuple(
            RfcTerminalCascadeImpactItem(
                domain=str(item["domain"]),
                impact_kind=str(item["impact_kind"]),
                entity_type=str(item["entity_type"]),
                entity_id=str(item["entity_id"]),
                current_state=(
                    None if item["current_state"] is None else str(item["current_state"])
                ),
                resulting_state=(
                    None if item["resulting_state"] is None else str(item["resulting_state"])
                ),
                current_count=(
                    None if item["current_count"] is None else int(item["current_count"])
                ),
                resulting_count=(
                    None
                    if item["resulting_count"] is None
                    else int(item["resulting_count"])
                ),
                attention_code=(
                    None if item["attention_code"] is None else str(item["attention_code"])
                ),
            )
            for item in preview["items"]
        )
        remaining = tuple(
            item
            for item in ordered
            if after_key is None or (item.impact_kind, item.entity_id) > after_key
        )
        page = remaining[:limit]
        continuation = None
        if len(remaining) > len(page) and page:
            continuation = (page[-1].impact_kind, page[-1].entity_id)
        return RfcTerminalCascadeImpactProviderPage(
            domain="TASKS_OBJECTIVES",
            status="READY",
            exact_count=int(preview["exact_count"]),
            provider_fingerprint=str(preview["provider_fingerprint"]),
            items=page,
            continuation_key=continuation,
            warning_code=None,
        )

    @classmethod
    def revalidate_terminal_cascade(
        cls,
        uow: UnitOfWork,
        proposal_snapshot: RfcTerminalCascadeProposalSnapshot,
        reviewed_exact_count: int,
        reviewed_provider_fingerprint: str,
    ) -> str:
        if type(reviewed_exact_count) is not int or reviewed_exact_count < 0:
            raise ValidationError("reviewed_exact_count must be non-negative")
        reviewed = _require_sha256(
            reviewed_provider_fingerprint,
            label="reviewed_provider_fingerprint",
        )
        preview = RfcTerminalCascadeQueryService.preview_with_reader(
            uow.connection,
            cls._proposal_id(proposal_snapshot),
        )
        if preview["status"] != "READY":
            return "INDETERMINATE"
        try:
            cls._assert_snapshot_matches(preview, proposal_snapshot)
        except SomaError:
            return "STALE"
        if (
            int(preview["exact_count"]) != reviewed_exact_count
            or not hmac.compare_digest(
                str(preview["provider_fingerprint"]),
                reviewed,
            )
        ):
            return "STALE"
        return "READY"

    @classmethod
    def apply_terminal_cascade(
        cls,
        uow: UnitOfWork,
        proposal_snapshot: RfcTerminalCascadeProposalSnapshot,
        command_context: RfcTerminalCascadeExecutionCommandContext,
    ) -> RfcTerminalCascadeParticipantApplyResult:
        if not isinstance(
            command_context,
            RfcTerminalCascadeExecutionCommandContext,
        ):
            raise ValidationError(
                "command_context must be RfcTerminalCascadeExecutionCommandContext"
            )
        command_id = require_uuid4(command_context.command_id)
        reviewed_preview = _require_sha256(
            command_context.reviewed_preview_fingerprint,
            label="reviewed_preview_fingerprint",
        )
        if uow.connection.execute(
            "SELECT 1 FROM command_receipts WHERE command_id=?",
            (command_id,),
        ).fetchone() is None:
            raise IntegrityFailure(
                "RFC terminal cascade participant requires caller-owned command receipt"
            )
        proposal_id = cls._proposal_id(proposal_snapshot)
        preview = RfcTerminalCascadeQueryService.preview_with_reader(
            uow.connection,
            proposal_id,
        )
        if preview["status"] != "READY":
            raise SomaError(
                "RFC_TERMINAL_CASCADE_PARTICIPANT_FAILED",
                "Task/Objective cascade authority is indeterminate",
            )
        cls._assert_snapshot_matches(preview, proposal_snapshot)

        now = utc_epoch_seconds()
        result_refs: list[dict[str, str]] = []
        audit_ids: list[str] = []
        audit_writer = AuditWriter(_build_source_terminal_audit_registry())
        tasks = TaskRepository()
        objectives = ObjectiveProjectionRepository()
        affected_objectives: set[str] = set()

        for captured in preview["captured_wfms"]:
            task_id = str(captured["task_id"])
            task = tasks.get(uow.connection, task_id)
            if task is None or task.revision != int(captured["task_revision"]):
                raise SomaError(
                    "RFC_TERMINAL_CASCADE_STALE",
                    "captured WFM Task revision changed",
                )
            execution = TaskExecutionService._execution_authority(
                uow.connection,
                task_id,
            )
            if (
                execution.state not in {"not_started", "in_progress"}
                or execution.revision != int(captured["execution_revision"])
            ):
                raise SomaError(
                    "RFC_TERMINAL_CASCADE_STALE",
                    "captured WFM execution authority changed",
                )
            event_id = new_uuid4()
            audit_id = new_uuid4()
            resulting_execution_revision = execution.revision + 1
            uow.connection.execute(
                "INSERT INTO task_execution_events("
                "execution_event_id,task_id,execution_revision,event_kind,"
                "effective_at_utc,target_event_id,correction_action,reason_code,"
                "recorded_at_utc,command_id"
                ") VALUES (?,?,?,'rfc_terminal_terminate',NULL,NULL,NULL,"
                "'rfc_terminal_cascade',?,?)",
                (
                    event_id,
                    task_id,
                    resulting_execution_revision,
                    now,
                    command_id,
                ),
            )
            WfmSourceTerminalService._advance_termination_projection(
                uow,
                task_id=task_id,
                authority=execution,
                execution_event_id=event_id,
                reason="rfc_terminal_cascade",
            )
            tasks.increment_revision(
                uow,
                task_id=task_id,
                expected_revision=task.revision,
            )
            membership = objectives.current_membership_for_task(
                uow.connection,
                task_id,
            )
            if membership is not None:
                affected_objectives.add(membership.objective_id)
            audit_writer.write(
                uow,
                AuditEventInput(
                    audit_event_id=audit_id,
                    action_type="task.rfc_terminal_cascade_applied",
                    action_version=1,
                    actor_kind=command_context.actor_kind,
                    actor_id=command_context.actor_id,
                    target_type="task",
                    target_id=task_id,
                    command_id=command_id,
                    payload_schema="TaskRfcTerminalCascadeAuditV1",
                    payload_version=1,
                    payload={
                        "task_id": task_id,
                        "proposal_id": proposal_id,
                        "execution_event_id": event_id,
                        "prior_execution_revision": execution.revision,
                        "prior_execution_state": execution.state,
                        "resulting_execution_revision": resulting_execution_revision,
                        "reviewed_preview_fingerprint": reviewed_preview,
                    },
                    resulting_event_refs=(
                        AuditResultRef("task_execution_event", event_id),
                    ),
                ),
            )
            result_refs.append(
                {"type": "task_execution_event", "id": event_id}
            )
            audit_ids.append(audit_id)

        for objective_id in sorted(affected_objectives):
            objectives.rebuild_aggregate(
                uow,
                objective_id=objective_id,
                command_id=command_id,
            )

        canonical_refs = sorted(
            result_refs,
            key=lambda item: (
                item["type"].encode("utf-8"),
                item["id"].encode("utf-8"),
            ),
        )
        canonical_audits = sorted(audit_ids)
        result_fingerprint = sha256_canonical_json(
            {
                "schema": "SOMA_RFC_TERMINAL_CASCADE_PARTICIPANT_RESULT_V1",
                "domain": "TASKS_OBJECTIVES",
                "outer_command_id": command_id,
                "proposal_id": proposal_id,
                "result_refs": canonical_refs,
                "audit_event_ids": canonical_audits,
            }
        )
        return RfcTerminalCascadeParticipantApplyResult(
            domain="TASKS_OBJECTIVES",
            result_ref_count=len(canonical_refs),
            audit_event_count=len(canonical_audits),
            result_fingerprint=result_fingerprint,
        )

    @staticmethod
    def classify_hard_delete_dependency(reader: Any, rfc_id: str) -> str:
        connection = getattr(reader, "connection", reader)
        try:
            identity = require_uuid4(rfc_id)
            checks = (
                (
                    "SELECT 1 FROM wfm_task_identities WHERE current_rfc_id=? LIMIT 1",
                    (identity,),
                ),
                (
                    "SELECT 1 FROM wfm_rfc_assignment_events "
                    "WHERE prior_rfc_id=? OR new_rfc_id=? LIMIT 1",
                    (identity, identity),
                ),
                (
                    "SELECT 1 FROM task_rfc_links WHERE rfc_id=? LIMIT 1",
                    (identity,),
                ),
            )
            for sql, params in checks:
                if connection.execute(sql, params).fetchone() is not None:
                    return "BLOCKED"
            return "CLEAR"
        except Exception:
            return "INDETERMINATE"


__all__ = [
    "RfcTerminalCascadeExecutionCommandContext",
    "RfcTerminalCascadeParticipantApplyResult",
    "RfcTerminalTaskParticipant",
    "WfmSourceTerminalService",
]
