from __future__ import annotations

import hmac
from dataclasses import dataclass
from typing import Any

from soma.foundation.audit.writer import AuditEventInput, AuditResultRef
from soma.foundation.errors import IntegrityFailure, SomaError
from soma.foundation.identifiers import new_uuid4, require_uuid4, utc_epoch_seconds
from soma.foundation.persistence.uow import UnitOfWork
from soma.foundation.strict_json import sha256_canonical_json

from ..repositories.tasks import TaskRepository, WfmTaskRepository
from .task_planning import TaskPlanningService, validate_task_reason_category, validate_wfm_task_no
from .wfm_import import (
    WfmImportMutationResult,
    _effective_plan_lock_token,
    _execution_fingerprint_state,
    _objective_plan_context_token,
    _operational_plan_token,
    _source_projection_token,
)

_TERMINAL_SOURCE_CLASSES = frozenset({"complete", "plan_cancel"})
_SOURCE_CLASSES = frozenset({"unknown", "active", "complete", "plan_cancel"})


@dataclass(frozen=True, slots=True)
class WfmParentReassignmentFromSourceMutation:
    task_id: str
    task_no: str
    new_rfc_id: str
    source_lifecycle_class: str
    base_state_token: str
    accepted_command_id: str
    reason_category: str = "wfm_source_parent_correction"
    actor_kind: str = "local_user"
    actor_id: str | None = None


class WfmImportParentReassignmentParticipant:
    """LLD-05 reviewed WFM parent correction inside LLD-04's outer UnitOfWork."""

    @staticmethod
    def base_state_token(reader: Any, *, task_no: str, task_id: str, new_rfc_id: str) -> str:
        canonical_task_no = validate_wfm_task_no(task_no)
        canonical_task_id = require_uuid4(task_id)
        canonical_new_rfc_id = require_uuid4(new_rfc_id)
        identity = WfmTaskRepository.get_by_task_no(reader, canonical_task_no)
        task = TaskRepository.get(reader, canonical_task_id)
        if identity is None or identity.task_id != canonical_task_id or task is None or task.task_kind != "wfm":
            raise SomaError("TASK_STALE", "reviewed WFM reassignment target is not current ACTIVE authority")
        current_rfc = TaskPlanningService._load_rfc_parent_authority(reader, identity.current_rfc_id)
        new_rfc = TaskPlanningService._load_rfc_parent_authority(reader, canonical_new_rfc_id)
        if current_rfc is None or new_rfc is None:
            raise SomaError("WFM_PARENT_STALE", "reviewed WFM parent RFC authority is incomplete")
        history_risk = TaskPlanningService._classify_wfm_parent_history_risk(reader, canonical_task_id)
        return sha256_canonical_json(
            {
                "schema": "SOMA_WFM_IMPORT_PARENT_REASSIGN_BASE_V1",
                "task_no": canonical_task_no,
                "task_id": canonical_task_id,
                "task_revision": task.revision,
                "assignment": {
                    "current_rfc_id": identity.current_rfc_id,
                    "assignment_revision": identity.assignment_revision,
                },
                "current_rfc_authority": {
                    "revision": current_rfc[0],
                    "source_projection_revision": current_rfc[1],
                    "archive_state": current_rfc[2],
                    "status_class": current_rfc[3],
                },
                "new_rfc_id": canonical_new_rfc_id,
                "new_rfc_authority": {
                    "revision": new_rfc[0],
                    "source_projection_revision": new_rfc[1],
                    "archive_state": new_rfc[2],
                    "status_class": new_rfc[3],
                },
                "history_risk": history_risk,
                "source_projection": _source_projection_token(reader, canonical_task_id),
                "operational_plan": _operational_plan_token(reader, canonical_task_id),
                "execution": _execution_fingerprint_state(reader, canonical_task_id),
                "objective_plan_context": _objective_plan_context_token(reader, canonical_task_id),
                "lock": _effective_plan_lock_token(reader, canonical_task_id),
            }
        )

    @staticmethod
    def require_import_eligible_rfc(reader: Any, *, rfc_id: str, source_lifecycle_class: str) -> None:
        if source_lifecycle_class not in _SOURCE_CLASSES:
            raise SomaError("VALIDATION_ERROR", "provider lifecycle class is invalid")
        authority = TaskPlanningService._load_rfc_parent_authority(reader, require_uuid4(rfc_id))
        if authority is None:
            raise SomaError("WFM_RFC_NOT_ELIGIBLE", "reviewed WFM parent RFC disappeared")
        if source_lifecycle_class in _TERMINAL_SOURCE_CLASSES:
            return
        _rfc_revision, _source_revision, archive_state, status_class = authority
        if archive_state != "active" or status_class != "implement_eligible":
            raise SomaError(
                "WFM_RFC_NOT_ELIGIBLE",
                "active/nonterminal WFM requires an active Implement-eligible owning RFC",
            )

    @staticmethod
    def reassign_parent_from_source(
        uow: UnitOfWork,
        mutation: WfmParentReassignmentFromSourceMutation,
    ) -> WfmImportMutationResult:
        task_id = require_uuid4(mutation.task_id)
        task_no = validate_wfm_task_no(mutation.task_no)
        new_rfc_id = require_uuid4(mutation.new_rfc_id)
        if mutation.source_lifecycle_class not in _SOURCE_CLASSES:
            raise SomaError("VALIDATION_ERROR", "provider lifecycle class is invalid")
        reason = validate_task_reason_category(mutation.reason_category)
        receipt = uow.connection.execute(
            "SELECT 1 FROM command_receipts WHERE command_id=?",
            (mutation.accepted_command_id,),
        ).fetchone()
        if receipt is None:
            raise IntegrityFailure("WFM import reassignment requires caller-owned command receipt")
        current_token = WfmImportParentReassignmentParticipant.base_state_token(
            uow.connection,
            task_no=task_no,
            task_id=task_id,
            new_rfc_id=new_rfc_id,
        )
        if not hmac.compare_digest(current_token, mutation.base_state_token):
            raise SomaError("TASK_STALE", "reviewed WFM parent reassignment base state changed")

        identity = WfmTaskRepository.get_by_task_no(uow.connection, task_no)
        task = TaskRepository.get(uow.connection, task_id)
        if identity is None or identity.task_id != task_id or task is None or task.task_kind != "wfm":
            raise SomaError("TASK_STALE", "reviewed WFM reassignment identity changed")
        prior_rfc_id = identity.current_rfc_id
        if prior_rfc_id == new_rfc_id:
            raise SomaError("TASK_STALE", "reviewed WFM parent correction no longer represents a change")
        WfmImportParentReassignmentParticipant.require_import_eligible_rfc(
            uow.connection,
            rfc_id=new_rfc_id,
            source_lifecycle_class=mutation.source_lifecycle_class,
        )

        review_risk = TaskPlanningService._classify_wfm_parent_history_risk(uow.connection, task_id)
        assignment_event_id = new_uuid4()
        audit_event_id = new_uuid4()
        now = utc_epoch_seconds()
        resulting_revision = task.revision + 1
        WfmTaskRepository.reassign_rfc(
            uow,
            assignment_event_id=assignment_event_id,
            task_id=task_id,
            prior_rfc_id=prior_rfc_id,
            new_rfc_id=new_rfc_id,
            expected_assignment_revision=identity.assignment_revision,
            reason_code=reason,
            review_risk=review_risk,
            command_id=mutation.accepted_command_id,
            recorded_at_utc=now,
        )
        TaskRepository.increment_revision(uow, task_id=task_id, expected_revision=task.revision)
        audit = AuditEventInput(
            audit_event_id=audit_event_id,
            action_type="task.wfm_parent_reassigned",
            action_version=1,
            actor_kind=mutation.actor_kind,
            actor_id=mutation.actor_id,
            target_type="task",
            target_id=task_id,
            reason_category=reason,
            command_id=mutation.accepted_command_id,
            payload_schema="TaskRelationshipAuditV1",
            payload_version=1,
            payload={
                "task_id": task_id,
                "relationship_kind": "wfm_parent",
                "action": "REASSIGN",
                "relationship_id": assignment_event_id,
                "related_id": new_rfc_id,
                "prior_related_id": prior_rfc_id,
                "resulting_revision": resulting_revision,
                "reason_category": reason,
            },
            resulting_event_refs=(AuditResultRef("wfm_assignment", assignment_event_id),),
        )
        return WfmImportMutationResult(
            task_id=task_id,
            resulting_task_revision=resulting_revision,
            result_refs=(("task", task_id), ("wfm_assignment", assignment_event_id)),
            audit_events=(audit,),
        )
