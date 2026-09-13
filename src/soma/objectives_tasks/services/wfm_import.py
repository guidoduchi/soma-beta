from __future__ import annotations

import hmac
import re
from dataclasses import dataclass
from typing import Any

from soma.foundation.audit.writer import AuditEventInput, AuditResultRef
from soma.foundation.errors import IntegrityFailure, SomaError, ValidationError
from soma.foundation.identifiers import new_uuid4, require_uuid4, utc_epoch_seconds
from soma.foundation.persistence.uow import UnitOfWork
from soma.foundation.strict_json import sha256_canonical_json

from ..queries.task_activity_review import _load_authorities
from ..repositories.tasks import (
    TaskNoStatus,
    TaskPlanRecord,
    TaskPlanRepository,
    TaskRecord,
    TaskRepository,
    WfmTaskRepository,
)
from ..source_terminal_authority import (
    WfmSourceProjectionMutation,
    WfmSourceProjectionParticipant,
    _execution_fingerprint_state,
    _lock_fingerprint_state,
    current_source_projection,
)
from .task_planning import TaskPlanningService, validate_task_reason_category, validate_wfm_task_no

_PROPOSAL_KINDS = frozenset({"wfm_create_or_adopt", "wfm_source_projection", "wfm_plan_reconciliation"})
_SOURCE_CLASSES = frozenset({"unknown", "active", "complete", "plan_cancel"})
_TERMINAL_SOURCE_CLASSES = frozenset({"complete", "plan_cancel"})
_WFM_SOURCE_SCHEDULING_TIMEZONE_IANA = "America/Guayaquil"
_WFM_ACTIVITY_CONFLICT_SCHEMA = "SOMA_WFM_IMPORT_ACTIVITY_CONFLICT_V1"
_SHA256_RE = re.compile(r"[0-9a-f]{64}\Z")


@dataclass(frozen=True, slots=True)
class WfmImportBaseTarget:
    proposal_kind: str
    task_no: str
    task_id: str | None


@dataclass(frozen=True, slots=True)
class WfmCreateOrAdoptFromSourceMutation:
    task_no: str
    expected_task_id: str | None
    rfc_id: str
    source_lifecycle_class: str
    base_state_token: str
    accepted_command_id: str
    actor_kind: str = "local_user"
    actor_id: str | None = None


@dataclass(frozen=True, slots=True)
class WfmSourceProjectionAcceptanceMutation:
    task_id: str
    task_no: str
    expected_source_projection_revision: int
    provider_status_token: str | None
    provider_lifecycle_class: str
    source_plan_start_utc: int | None
    source_plan_end_utc: int | None
    accepted_source_observation_id: str
    base_state_token: str
    accepted_command_id: str


@dataclass(frozen=True, slots=True)
class WfmReviewedOperationalPlanMutation:
    task_id: str
    task_no: str
    expected_task_revision: int
    expected_current_plan_revision: int
    expected_source_projection_revision: int
    accepted_source_observation_id: str
    start_utc: int
    end_utc: int
    base_state_token: str
    accepted_command_id: str
    reason_category: str | None = None
    actor_kind: str = "local_user"
    actor_id: str | None = None


@dataclass(frozen=True, slots=True)
class WfmImportMutationResult:
    task_id: str
    resulting_task_revision: int
    result_refs: tuple[tuple[str, str], ...]
    audit_events: tuple[AuditEventInput, ...]
    source_projection_revision: int | None = None


def _require_sha256(value: object, *, label: str) -> str:
    if not isinstance(value, str) or _SHA256_RE.fullmatch(value) is None:
        raise ValidationError(f"{label} must be lowercase SHA-256 hex")
    return value


def _require_source_class(value: object) -> str:
    if not isinstance(value, str) or value not in _SOURCE_CLASSES:
        raise ValidationError("provider lifecycle class is invalid")
    return value


def _require_receipt(uow: UnitOfWork, command_id: str) -> None:
    if uow.connection.execute(
        "SELECT 1 FROM command_receipts WHERE command_id=?",
        (command_id,),
    ).fetchone() is None:
        raise IntegrityFailure("WFM import participant requires caller-owned command receipt")


def _identity_token(reader: Any, task_no: str) -> tuple[TaskNoStatus, dict[str, object] | None]:
    status = WfmTaskRepository.task_no_status(reader, task_no)
    identity = WfmTaskRepository.get_by_task_no(reader, task_no)
    if status is TaskNoStatus.ACTIVE:
        if identity is None:
            raise IntegrityFailure("ACTIVE WFM Task No lacks identity authority")
        return status, {
            "task_id": identity.task_id,
            "current_rfc_id": identity.current_rfc_id,
            "assignment_revision": identity.assignment_revision,
        }
    if identity is not None:
        raise IntegrityFailure("non-ACTIVE WFM Task No unexpectedly resolves a current identity")
    return status, None


def _source_projection_token(reader: Any, task_id: str) -> dict[str, object] | None:
    source = current_source_projection(reader, task_id)
    if source is None:
        return None
    return {
        "source_projection_revision": source.source_projection_revision,
        "provider_status_token": source.provider_status_token,
        "provider_lifecycle_class": source.provider_lifecycle_class,
        "source_plan_start_utc": source.source_plan_start_utc,
        "source_plan_end_utc": source.source_plan_end_utc,
        "accepted_source_observation_id": source.accepted_source_observation_id,
        "source_base_token": source.source_base_token,
    }


def _operational_plan_token(reader: Any, task_id: str) -> dict[str, object] | None:
    pointer = TaskPlanRepository.current_pointer(reader, task_id)
    if pointer is None:
        return None
    plan = TaskPlanRepository.get_revision(reader, pointer.plan_revision_id)
    if plan is None or plan.task_id != task_id:
        raise IntegrityFailure("WFM current plan pointer is not bound to same-Task immutable history")
    return {
        "plan_revision_id": plan.plan_revision_id,
        "revision": pointer.revision,
        "start_utc": plan.start_utc,
        "end_utc": plan.end_utc,
        "origin": plan.origin,
        "source_observation_id": plan.source_observation_id,
    }


def _objective_plan_context_token(reader: Any, task_id: str) -> dict[str, object] | None:
    context = TaskPlanningService._load_current_objective_plan_context(reader, task_id)
    if context is None:
        return None
    (
        objective_id,
        accepted_plan_revision_id,
        creation_origin,
        superseded_by_objective_id,
        execution_state,
        attention_reason,
        aggregate_revision,
    ) = context
    return {
        "objective_id": objective_id,
        "accepted_plan_revision_id": accepted_plan_revision_id,
        "creation_origin": creation_origin,
        "superseded_by_objective_id": superseded_by_objective_id,
        "execution_state": execution_state,
        "attention_reason": attention_reason,
        "aggregate_revision": aggregate_revision,
    }


def _effective_plan_lock_token(reader: Any, task_id: str) -> dict[str, object]:
    explicit = dict(_lock_fingerprint_state(reader, task_id))
    source = current_source_projection(reader, task_id)
    terminal_guard: dict[str, object] | None = None
    if source is not None and source.provider_lifecycle_class in _TERMINAL_SOURCE_CLASSES:
        row = reader.execute(
            "SELECT "
            "SUM(CASE WHEN state='pending' AND source_projection_revision=? THEN 1 ELSE 0 END),"
            "SUM(CASE WHEN state='retain_local_work' AND source_projection_revision=? THEN 1 ELSE 0 END) "
            "FROM wfm_source_terminal_reviews WHERE task_id=?",
            (source.source_projection_revision, source.source_projection_revision, task_id),
        ).fetchone()
        if row is None:
            raise IntegrityFailure("terminal-source plan guard query produced no row")
        pending_count = int(row[0] or 0)
        retain_count = int(row[1] or 0)
        if pending_count > 1 or retain_count > 1:
            raise IntegrityFailure("terminal-source plan guard cardinality is invalid")
        terminal_guard = {
            "source_projection_revision": source.source_projection_revision,
            "pending_review_exists": bool(pending_count),
            "retain_review_exists": bool(retain_count),
        }
    explicit["terminal_source_plan_guard"] = terminal_guard
    return explicit


def _activity_candidate(value: object) -> tuple[str, str, str | None]:
    if not isinstance(value, dict) or set(value) != {"task_no", "current_rfc_id", "task_id"}:
        raise ValidationError("WFM activity candidate must contain exactly task_no, current_rfc_id, and task_id")
    task_no = validate_wfm_task_no(value["task_no"])
    current_rfc_id = value["current_rfc_id"]
    if not isinstance(current_rfc_id, str):
        raise ValidationError("WFM activity candidate current_rfc_id must be canonical UUIDv4 text")
    current_rfc_id = require_uuid4(current_rfc_id)
    task_id_raw = value["task_id"]
    if task_id_raw is None:
        task_id = None
    elif isinstance(task_id_raw, str):
        task_id = require_uuid4(task_id_raw)
    else:
        raise ValidationError("WFM activity candidate task_id must be canonical UUIDv4 text or null")
    return task_no, current_rfc_id, task_id


def _activity_interval(value: object) -> tuple[int, int]:
    if not isinstance(value, dict) or set(value) != {"start_utc", "end_utc"}:
        raise ValidationError("WFM activity interval must contain exactly start_utc and end_utc")
    start = value["start_utc"]
    end = value["end_utc"]
    if type(start) is not int or type(end) is not int or start < 0 or end <= start:
        raise ValidationError("WFM activity interval must be a valid nonnegative whole-second interval")
    return start, end


def _activity_conflict_entry(authority: Any) -> dict[str, object]:
    interval = authority.conflict_interval
    if interval is None:
        raise IntegrityFailure("WFM activity conflict entry has no conflict interval")
    if authority.operational_plan_start_utc is not None:
        basis = "operational_plan"
        interval_revision = authority.operational_plan_revision
        interval_revision_id = authority.operational_plan_revision_id
    else:
        basis = "source_plan"
        interval_revision = authority.source_projection_revision
        interval_revision_id = None
    if interval_revision <= 0:
        raise IntegrityFailure("WFM activity conflict interval has no positive revision authority")
    execution_state = authority.execution_state or "not_started"
    return {
        "task_id": authority.task_id,
        "task_no": authority.task_no,
        "current_rfc_id": authority.current_rfc_id,
        "assignment_revision": authority.assignment_revision,
        "task_revision": authority.task_revision,
        "activity_lineage_id": authority.activity_lineage_id,
        "lineage_revision": authority.lineage_revision,
        "last_lineage_event_id": authority.last_lineage_event_id,
        "interval_basis": basis,
        "interval_revision": interval_revision,
        "interval_revision_id": interval_revision_id,
        "start_utc": interval[0],
        "end_utc": interval[1],
        "execution_revision": authority.execution_revision,
        "execution_state": execution_state,
        "outcome_revision": authority.outcome_revision,
        "accepted_outcome": authority.accepted_outcome,
    }


def _activity_conflict_fingerprint(
    *,
    subject: dict[str, object],
    start_utc: int,
    end_utc: int,
    conflicts: tuple[dict[str, object], ...],
) -> str:
    return sha256_canonical_json(
        {
            "schema": _WFM_ACTIVITY_CONFLICT_SCHEMA,
            "subject": subject,
            "candidate_interval": {"start_utc": start_utc, "end_utc": end_utc},
            "conflicts": list(conflicts),
        }
    )


class WfmImportReader:
    """Read-only LLD-05 import owner context consumed by LLD-04."""

    @staticmethod
    def get_by_task_no(reader: Any, task_no: str) -> dict[str, object] | None:
        canonical = validate_wfm_task_no(task_no)
        identity = WfmTaskRepository.get_by_task_no(reader, canonical)
        if identity is None:
            return None
        task = TaskRepository.get(reader, identity.task_id)
        if task is None or task.task_kind != "wfm":
            raise IntegrityFailure("WFM identity is not backed by canonical Task authority")
        return {
            "task_id": identity.task_id,
            "task_no": identity.task_no,
            "current_rfc_id": identity.current_rfc_id,
            "assignment_revision": identity.assignment_revision,
            "task_revision": task.revision,
        }

    @staticmethod
    def task_no_status(reader: Any, task_no: str) -> str:
        return WfmTaskRepository.task_no_status(reader, validate_wfm_task_no(task_no)).value

    @staticmethod
    def source_projection(reader: Any, task_id: str) -> dict[str, object] | None:
        return _source_projection_token(reader, require_uuid4(task_id))

    @staticmethod
    def source_plan(reader: Any, task_id: str) -> dict[str, int] | None:
        source = current_source_projection(reader, require_uuid4(task_id))
        if source is None or source.source_plan_start_utc is None:
            return None
        if source.source_plan_end_utc is None:
            raise IntegrityFailure("WFM source plan has only one endpoint")
        return {"start_utc": source.source_plan_start_utc, "end_utc": source.source_plan_end_utc}

    @staticmethod
    def operational_plan_context(reader: Any, task_id: str) -> dict[str, object] | None:
        return _operational_plan_token(reader, require_uuid4(task_id))

    @staticmethod
    def activity_conflicts(
        reader: Any,
        task_id_or_candidate: object,
        interval: object,
        counterpart_task_id: str | None = None,
    ) -> dict[str, object]:
        task_no, current_rfc_id, task_id = _activity_candidate(task_id_or_candidate)
        start_utc, end_utc = _activity_interval(interval)
        counterpart = None if counterpart_task_id is None else require_uuid4(counterpart_task_id)
        status = WfmTaskRepository.task_no_status(reader, task_no)
        identity = WfmTaskRepository.get_by_task_no(reader, task_no)
        if status is TaskNoStatus.RETIRED:
            raise SomaError("WFM_TASK_NO_RETIRED", "retired WFM Task No cannot become activity-conflict authority")
        if task_id is None:
            if status is TaskNoStatus.ACTIVE or identity is not None:
                raise SomaError("TASK_STALE", "WFM activity candidate omits current ACTIVE identity authority")
            if counterpart is not None:
                raise SomaError("TASK_STALE", "unadopted WFM candidate cannot validate a counterpart")
            subject = {
                "task_id": None,
                "task_no": task_no,
                "current_rfc_id": current_rfc_id,
                "assignment_revision": None,
                "task_revision": None,
                "activity_lineage_id": None,
                "lineage_revision": None,
                "last_lineage_event_id": None,
            }
            return {
                "classification": "NO_REVIEWED_LINEAGE",
                "subject_task_id": None,
                "activity_lineage_id": None,
                "exact_conflict_count": 0,
                "suggested_counterpart_task_id": None,
                "selected_counterpart": None,
                "conflict_fingerprint": _activity_conflict_fingerprint(
                    subject=subject,
                    start_utc=start_utc,
                    end_utc=end_utc,
                    conflicts=(),
                ),
            }
        if status is not TaskNoStatus.ACTIVE or identity is None:
            raise SomaError("TASK_STALE", "WFM activity target is not current ACTIVE identity authority")
        if identity.task_id != task_id or identity.current_rfc_id != current_rfc_id:
            raise SomaError("TASK_STALE", "WFM activity target identity or RFC authority changed")

        subject_authority = _load_authorities(reader, (task_id,))[0]
        if subject_authority.task_no != task_no or subject_authority.current_rfc_id != current_rfc_id:
            raise IntegrityFailure("WFM activity subject authority disagrees with canonical identity")
        subject = {
            "task_id": subject_authority.task_id,
            "task_no": subject_authority.task_no,
            "current_rfc_id": subject_authority.current_rfc_id,
            "assignment_revision": subject_authority.assignment_revision,
            "task_revision": subject_authority.task_revision,
            "activity_lineage_id": subject_authority.activity_lineage_id,
            "lineage_revision": subject_authority.lineage_revision,
            "last_lineage_event_id": subject_authority.last_lineage_event_id,
        }
        lineage_id = subject_authority.activity_lineage_id
        if lineage_id is not None and not subject_authority.locally_active:
            if counterpart is not None:
                raise SomaError("TASK_STALE", "locally terminal WFM activity target has no current competing-attempt authority")
            return {
                "classification": "CLEAR",
                "subject_task_id": task_id,
                "activity_lineage_id": lineage_id,
                "exact_conflict_count": 0,
                "suggested_counterpart_task_id": None,
                "selected_counterpart": None,
                "conflict_fingerprint": _activity_conflict_fingerprint(
                    subject=subject,
                    start_utc=start_utc,
                    end_utc=end_utc,
                    conflicts=(),
                ),
            }
        if lineage_id is None:
            if counterpart is not None:
                raise SomaError("TASK_STALE", "WFM activity target has no reviewed lineage counterpart authority")
            return {
                "classification": "NO_REVIEWED_LINEAGE",
                "subject_task_id": task_id,
                "activity_lineage_id": None,
                "exact_conflict_count": 0,
                "suggested_counterpart_task_id": None,
                "selected_counterpart": None,
                "conflict_fingerprint": _activity_conflict_fingerprint(
                    subject=subject,
                    start_utc=start_utc,
                    end_utc=end_utc,
                    conflicts=(),
                ),
            }

        rows = reader.execute(
            "SELECT task_id FROM task_activity_lineage_current "
            "WHERE activity_lineage_id=? AND task_id<>? ORDER BY task_id",
            (lineage_id, task_id),
        ).fetchall()
        other_ids = tuple(str(row[0]) for row in rows)
        authorities = () if not other_ids else _load_authorities(reader, other_ids)
        conflicts: list[dict[str, object]] = []
        authority_by_id: dict[str, Any] = {}
        for authority in authorities:
            if authority.activity_lineage_id != lineage_id:
                raise IntegrityFailure("WFM activity conflict closure escaped reviewed lineage authority")
            if not authority.locally_active:
                continue
            other_interval = authority.conflict_interval
            if other_interval is None:
                continue
            if start_utc < other_interval[1] and other_interval[0] < end_utc:
                conflicts.append(_activity_conflict_entry(authority))
                authority_by_id[authority.task_id] = authority
        conflicts.sort(key=lambda item: str(item["task_id"]))
        exact_conflicts = tuple(conflicts)
        suggested = None if not exact_conflicts else str(exact_conflicts[0]["task_id"])
        selected = None
        if counterpart is not None:
            selected_authority = authority_by_id.get(counterpart)
            if selected_authority is None:
                raise SomaError("TASK_STALE", "reviewed WFM competing-attempt counterpart is no longer a current conflict")
            selected = {
                "task_id": selected_authority.task_id,
                "task_revision": selected_authority.task_revision,
            }
        return {
            "classification": "CLEAR" if not exact_conflicts else "SAME_REVIEWED_LINEAGE_OVERLAP",
            "subject_task_id": task_id,
            "activity_lineage_id": lineage_id,
            "exact_conflict_count": len(exact_conflicts),
            "suggested_counterpart_task_id": suggested,
            "selected_counterpart": selected,
            "conflict_fingerprint": _activity_conflict_fingerprint(
                subject=subject,
                start_utc=start_utc,
                end_utc=end_utc,
                conflicts=exact_conflicts,
            ),
        }

    @staticmethod
    def source_acceptance_base_token(reader: Any, target: WfmImportBaseTarget) -> str:
        if not isinstance(target, WfmImportBaseTarget):
            raise ValidationError("WFM import base target is invalid")
        if target.proposal_kind not in _PROPOSAL_KINDS:
            raise ValidationError("WFM import proposal kind is invalid")
        task_no = validate_wfm_task_no(target.task_no)
        target_task_id = None if target.task_id is None else require_uuid4(target.task_id)
        status, identity = _identity_token(reader, task_no)
        if status is TaskNoStatus.RETIRED:
            raise SomaError("WFM_TASK_NO_RETIRED", "retired WFM Task No cannot become import mutation authority")
        if status is TaskNoStatus.ACTIVE:
            if identity is None:
                raise IntegrityFailure("ACTIVE WFM import target lacks identity")
            if target_task_id is not None and identity["task_id"] != target_task_id:
                raise SomaError("TASK_STALE", "WFM import target identity changed")
        elif target_task_id is not None:
            raise SomaError("TASK_STALE", "WFM import target disappeared")

        payload: dict[str, object] = {
            "schema": "SOMA_WFM_IMPORT_BASE_V1",
            "proposal_kind": target.proposal_kind,
            "task_no": task_no,
            "task_no_status": status.value,
            "identity": identity,
        }
        if target.proposal_kind == "wfm_create_or_adopt":
            return sha256_canonical_json(payload)
        if status is not TaskNoStatus.ACTIVE or identity is None or target_task_id is None:
            raise SomaError("TASK_STALE", "WFM import target is not current ACTIVE authority")

        source = _source_projection_token(reader, target_task_id)
        payload["source_projection"] = source
        if target.proposal_kind == "wfm_source_projection":
            return sha256_canonical_json(payload)
        if source is None:
            raise SomaError("TASK_STALE", "WFM plan reconciliation requires accepted source projection")

        task = TaskRepository.get(reader, target_task_id)
        if task is None or task.task_kind != "wfm":
            raise SomaError("TASK_STALE", "WFM Task authority disappeared")
        payload.update(
            {
                "task_revision": task.revision,
                "operational_plan": _operational_plan_token(reader, target_task_id),
                "execution": _execution_fingerprint_state(reader, target_task_id),
                "objective_plan_context": _objective_plan_context_token(reader, target_task_id),
                "lock": _effective_plan_lock_token(reader, target_task_id),
            }
        )
        return sha256_canonical_json(payload)


class WfmImportMutationParticipant:
    """LLD-05 WFM import participant executed inside LLD-04's outer UnitOfWork."""

    @staticmethod
    def create_or_adopt_wfm_from_source(
        uow: UnitOfWork,
        mutation: WfmCreateOrAdoptFromSourceMutation,
    ) -> WfmImportMutationResult:
        task_no = validate_wfm_task_no(mutation.task_no)
        expected_task_id = None if mutation.expected_task_id is None else require_uuid4(mutation.expected_task_id)
        rfc_id = require_uuid4(mutation.rfc_id)
        lifecycle = _require_source_class(mutation.source_lifecycle_class)
        base_token = _require_sha256(mutation.base_state_token, label="base_state_token")
        _require_receipt(uow, mutation.accepted_command_id)
        current_token = WfmImportReader.source_acceptance_base_token(
            uow.connection,
            WfmImportBaseTarget("wfm_create_or_adopt", task_no, expected_task_id),
        )
        if not hmac.compare_digest(current_token, base_token):
            raise SomaError("TASK_STALE", "WFM identity import base state changed")
        if uow.connection.execute("SELECT 1 FROM rfcs WHERE rfc_id=?", (rfc_id,)).fetchone() is None:
            raise SomaError("TASK_STALE", "reviewed WFM parent RFC no longer exists")
        if lifecycle not in _TERMINAL_SOURCE_CLASSES:
            TaskPlanningService._require_eligible_rfc(uow.connection, rfc_id)

        status = WfmTaskRepository.task_no_status(uow.connection, task_no)
        if status is TaskNoStatus.RETIRED:
            raise SomaError("WFM_TASK_NO_RETIRED", "retired WFM Task No cannot be source-adopted")
        if status is TaskNoStatus.ACTIVE:
            identity = WfmTaskRepository.get_by_task_no(uow.connection, task_no)
            if identity is None or expected_task_id is None or identity.task_id != expected_task_id:
                raise SomaError("TASK_STALE", "reviewed WFM adoption identity changed")
            if identity.current_rfc_id != rfc_id:
                raise SomaError("TASK_STALE", "reviewed WFM parent RFC changed")
            task = TaskRepository.get(uow.connection, identity.task_id)
            if task is None or task.task_kind != "wfm":
                raise IntegrityFailure("reviewed WFM identity is not backed by canonical Task authority")
            return WfmImportMutationResult(
                task_id=identity.task_id,
                resulting_task_revision=task.revision,
                result_refs=(("task", identity.task_id),),
                audit_events=(),
            )
        if expected_task_id is not None:
            raise SomaError("TASK_STALE", "reviewed WFM creation target is no longer absent")

        task_id = new_uuid4()
        assignment_event_id = new_uuid4()
        audit_event_id = new_uuid4()
        now = utc_epoch_seconds()
        creation_origin = "historical_source" if lifecycle in _TERMINAL_SOURCE_CLASSES else "wfm_source_adoption"
        TaskRepository.insert(
            uow,
            TaskRecord(
                task_id=task_id,
                task_kind="wfm",
                local_task_name=None,
                creation_origin=creation_origin,
                revision=1,
                created_at_utc=now,
                created_command_id=mutation.accepted_command_id,
            ),
        )
        WfmTaskRepository.insert_identity(
            uow,
            task_id=task_id,
            task_no=task_no,
            rfc_id=rfc_id,
            created_command_id=mutation.accepted_command_id,
        )
        uow.connection.execute(
            "INSERT INTO wfm_rfc_assignment_events(assignment_event_id,task_id,prior_rfc_id,new_rfc_id,reason_code,"
            "review_risk,recorded_at_utc,command_id) VALUES (?,?,NULL,?,'source_adoption','low',?,?)",
            (assignment_event_id, task_id, rfc_id, now, mutation.accepted_command_id),
        )
        audit = AuditEventInput(
            audit_event_id=audit_event_id,
            action_type="task.wfm_registered",
            action_version=1,
            actor_kind=mutation.actor_kind,
            actor_id=mutation.actor_id,
            target_type="task",
            target_id=task_id,
            command_id=mutation.accepted_command_id,
            payload_schema="TaskAuditV1",
            payload_version=1,
            payload={
                "task_id": task_id,
                "task_kind": "wfm",
                "creation_origin": creation_origin,
                "resulting_revision": 1,
                "task_plan_revision_id": None,
                "reason_category": None,
            },
            resulting_event_refs=(
                AuditResultRef("task", task_id),
                AuditResultRef("wfm_assignment", assignment_event_id),
            ),
        )
        return WfmImportMutationResult(
            task_id=task_id,
            resulting_task_revision=1,
            result_refs=(("task", task_id), ("wfm_assignment", assignment_event_id)),
            audit_events=(audit,),
        )

    @staticmethod
    def apply_wfm_source_projection(
        uow: UnitOfWork,
        mutation: WfmSourceProjectionAcceptanceMutation,
    ) -> WfmImportMutationResult:
        task_id = require_uuid4(mutation.task_id)
        task_no = validate_wfm_task_no(mutation.task_no)
        base_token = _require_sha256(mutation.base_state_token, label="base_state_token")
        observation_id = require_uuid4(mutation.accepted_source_observation_id)
        _require_receipt(uow, mutation.accepted_command_id)
        current_token = WfmImportReader.source_acceptance_base_token(
            uow.connection,
            WfmImportBaseTarget("wfm_source_projection", task_no, task_id),
        )
        if not hmac.compare_digest(current_token, base_token):
            raise SomaError("TASK_STALE", "WFM source-projection import base state changed")
        result = WfmSourceProjectionParticipant.apply_wfm_source_projection(
            uow,
            WfmSourceProjectionMutation(
                task_id=task_id,
                expected_source_projection_revision=mutation.expected_source_projection_revision,
                provider_status_token=mutation.provider_status_token,
                provider_lifecycle_class=mutation.provider_lifecycle_class,
                source_plan_start_utc=mutation.source_plan_start_utc,
                source_plan_end_utc=mutation.source_plan_end_utc,
                accepted_source_observation_id=observation_id,
                source_base_token=base_token,
            ),
            command_id=mutation.accepted_command_id,
        )
        task = TaskRepository.get(uow.connection, task_id)
        if task is None:
            raise IntegrityFailure("WFM source projection lost owning Task after mutation")
        refs = (("wfm_source_projection", task_id), *result.result_refs)
        return WfmImportMutationResult(
            task_id=task_id,
            resulting_task_revision=task.revision,
            source_projection_revision=result.source_projection_revision,
            result_refs=refs,
            audit_events=(),
        )

    @staticmethod
    def apply_reviewed_operational_plan_from_source(
        uow: UnitOfWork,
        mutation: WfmReviewedOperationalPlanMutation,
    ) -> WfmImportMutationResult:
        task_id = require_uuid4(mutation.task_id)
        task_no = validate_wfm_task_no(mutation.task_no)
        observation_id = require_uuid4(mutation.accepted_source_observation_id)
        base_token = _require_sha256(mutation.base_state_token, label="base_state_token")
        if type(mutation.expected_task_revision) is not int or mutation.expected_task_revision <= 0:
            raise ValidationError("expected_task_revision must be positive")
        if type(mutation.expected_current_plan_revision) is not int or mutation.expected_current_plan_revision < 0:
            raise ValidationError("expected_current_plan_revision must be nonnegative")
        if type(mutation.expected_source_projection_revision) is not int or mutation.expected_source_projection_revision <= 0:
            raise ValidationError("expected_source_projection_revision must be positive")
        if type(mutation.start_utc) is not int or type(mutation.end_utc) is not int or mutation.start_utc < 0 or mutation.end_utc <= mutation.start_utc:
            raise ValidationError("reviewed WFM operational plan interval is invalid")
        reason = None if mutation.reason_category is None else validate_task_reason_category(mutation.reason_category)
        _require_receipt(uow, mutation.accepted_command_id)
        current_token = WfmImportReader.source_acceptance_base_token(
            uow.connection,
            WfmImportBaseTarget("wfm_plan_reconciliation", task_no, task_id),
        )
        if not hmac.compare_digest(current_token, base_token):
            raise SomaError("TASK_STALE", "WFM plan-reconciliation import base state changed")

        task = TaskRepository.get(uow.connection, task_id)
        identity = WfmTaskRepository.get_identity(uow.connection, task_id)
        if task is None or task.task_kind != "wfm" or identity is None or identity.task_no != task_no:
            raise SomaError("TASK_STALE", "reviewed WFM plan target changed")
        if task.revision != mutation.expected_task_revision:
            raise SomaError("TASK_STALE", "Task revision changed before reviewed WFM plan acceptance")
        source = current_source_projection(uow.connection, task_id)
        if (
            source is None
            or source.source_projection_revision != mutation.expected_source_projection_revision
            or source.accepted_source_observation_id != observation_id
            or source.source_plan_start_utc != mutation.start_utc
            or source.source_plan_end_utc != mutation.end_utc
        ):
            raise SomaError("TASK_STALE", "reviewed WFM source plan changed before operational adoption")

        pointer = TaskPlanRepository.current_pointer(uow.connection, task_id)
        prior_plan = None
        if mutation.expected_current_plan_revision == 0:
            if pointer is not None:
                raise SomaError("TASK_STALE", "Task gained an operational plan after WFM plan review")
        else:
            if pointer is None or pointer.revision != mutation.expected_current_plan_revision:
                raise SomaError("TASK_STALE", "Task operational-plan revision changed after WFM plan review")
            prior_plan = TaskPlanRepository.get_revision(uow.connection, pointer.plan_revision_id)
            if prior_plan is None or prior_plan.task_id != task_id:
                raise IntegrityFailure("Task operational-plan pointer is not bound to same-Task history")
        if prior_plan is not None and prior_plan.start_utc == mutation.start_utc and prior_plan.end_utc == mutation.end_utc:
            raise SomaError("TASK_STALE", "reviewed WFM plan no longer represents a material operational change")

        TaskPlanningService._require_eligible_rfc(uow.connection, identity.current_rfc_id)
        objective_context = TaskPlanningService._load_current_objective_plan_context(uow.connection, task_id)
        TaskPlanningService._require_ordinary_plan_unlocked(uow.connection, task_id, objective_context)

        plan_revision_id = new_uuid4()
        audit_event_id = new_uuid4()
        now = utc_epoch_seconds()
        resulting_revision = task.revision + 1
        prior_plan_revision_id = None if prior_plan is None else prior_plan.plan_revision_id
        membership_plan_mismatch = objective_context is not None and objective_context[1] != plan_revision_id
        plan_row = TaskPlanRecord(
            plan_revision_id=plan_revision_id,
            task_id=task_id,
            start_utc=mutation.start_utc,
            end_utc=mutation.end_utc,
            origin="wfm_source_adoption",
            scheduling_timezone_iana=_WFM_SOURCE_SCHEDULING_TIMEZONE_IANA,
            source_observation_id=observation_id,
            predecessor_plan_revision_id=prior_plan_revision_id,
            reason_code=reason,
            accepted_at_utc=now,
            command_id=mutation.accepted_command_id,
        )
        TaskPlanRepository.append_and_set_current(
            uow,
            plan_row,
            expected_current_revision=mutation.expected_current_plan_revision,
        )
        TaskRepository.increment_revision(
            uow,
            task_id=task_id,
            expected_revision=mutation.expected_task_revision,
        )
        if membership_plan_mismatch:
            TaskPlanningService._surface_plan_membership_mismatch(
                uow,
                objective_context=objective_context,
                command_id=mutation.accepted_command_id,
            )
        audit = AuditEventInput(
            audit_event_id=audit_event_id,
            action_type="task.plan_changed",
            action_version=1,
            actor_kind=mutation.actor_kind,
            actor_id=mutation.actor_id,
            target_type="task",
            target_id=task_id,
            reason_category=reason,
            command_id=mutation.accepted_command_id,
            payload_schema="TaskPlanAuditV1",
            payload_version=1,
            payload={
                "task_id": task_id,
                "prior_plan_revision_id": prior_plan_revision_id,
                "new_plan_revision_id": plan_revision_id,
                "resulting_task_revision": resulting_revision,
                "origin": "wfm_source_adoption",
                "reason_category": reason,
                "membership_plan_mismatch": membership_plan_mismatch,
            },
            resulting_event_refs=(AuditResultRef("task_plan", plan_revision_id),),
        )
        return WfmImportMutationResult(
            task_id=task_id,
            resulting_task_revision=resulting_revision,
            result_refs=(("task_plan", plan_revision_id),),
            audit_events=(audit,),
        )
