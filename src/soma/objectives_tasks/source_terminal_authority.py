from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

from soma.foundation.errors import IntegrityFailure, SomaError, ValidationError
from soma.foundation.identifiers import new_uuid4, require_uuid4, utc_epoch_seconds
from soma.foundation.persistence.uow import UnitOfWork
from soma.foundation.strict_json import sha256_canonical_json

from .repositories.tasks import TaskPlanRepository, TaskRepository, WfmTaskRepository
from .services.task_execution import TaskExecutionService

_TERMINAL_SOURCE_CLASSES = frozenset({"complete", "plan_cancel"})
_SOURCE_CLASSES = frozenset({"unknown", "active", "complete", "plan_cancel"})
_SHA256_RE = re.compile(r"[0-9a-f]{64}\Z")


@dataclass(frozen=True, slots=True)
class WfmSourceProjectionMutation:
    task_id: str
    expected_source_projection_revision: int
    provider_status_token: str | None
    provider_lifecycle_class: str
    source_plan_start_utc: int | None
    source_plan_end_utc: int | None
    accepted_source_observation_id: str | None
    source_base_token: str


@dataclass(frozen=True, slots=True)
class WfmSourceProjectionApplyResult:
    task_id: str
    source_projection_revision: int
    source_terminal_review_id: str | None
    source_terminal_review_fingerprint: str | None
    result_refs: tuple[tuple[str, str], ...]
    audit_events: tuple[object, ...] = ()


@dataclass(frozen=True, slots=True)
class WfmSourceProjectionRecord:
    task_id: str
    provider_status_token: str | None
    provider_lifecycle_class: str
    source_plan_start_utc: int | None
    source_plan_end_utc: int | None
    accepted_source_observation_id: str | None
    source_projection_revision: int
    source_base_token: str
    last_command_id: str


@dataclass(frozen=True, slots=True)
class WfmSourceTerminalReviewRecord:
    source_terminal_review_id: str
    task_id: str
    source_projection_revision: int
    provider_lifecycle_class: str
    input_fingerprint: str
    state: str
    local_consequence_event_id: str | None
    revision: int
    created_at_utc: int
    decided_at_utc: int | None
    last_command_id: str | None


def _require_nonnegative_revision(value: int, *, label: str) -> int:
    if type(value) is not int or value < 0:
        raise ValidationError(f"{label} must be a nonnegative integer")
    return value


def _require_sha256(value: str, *, label: str) -> str:
    if not isinstance(value, str) or _SHA256_RE.fullmatch(value) is None:
        raise ValidationError(f"{label} must be lowercase SHA-256 hex")
    return value


def _bounded_optional_text(value: str | None, *, label: str, max_utf8_bytes: int = 1024) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise ValidationError(f"{label} must be text or null")
    try:
        encoded = value.encode("utf-8", errors="strict")
    except UnicodeEncodeError as exc:
        raise ValidationError(f"{label} must be valid Unicode") from exc
    if len(encoded) > max_utf8_bytes or "\x00" in value or "\r" in value or "\n" in value:
        raise ValidationError(f"{label} violates its bounded one-line contract")
    return value


def _validate_plan(start_utc: int | None, end_utc: int | None) -> tuple[int | None, int | None]:
    if start_utc is None and end_utc is None:
        return None, None
    if type(start_utc) is not int or type(end_utc) is not int:
        raise ValidationError("source plan must be exact integer endpoints or exact absence")
    if start_utc < 0 or end_utc <= start_utc:
        raise ValidationError("source plan interval is invalid")
    return start_utc, end_utc


def _source_projection(reader: Any, task_id: str) -> WfmSourceProjectionRecord | None:
    row = reader.execute(
        "SELECT task_id,provider_status_token,provider_lifecycle_class,source_plan_start_utc,"
        "source_plan_end_utc,accepted_source_observation_id,source_projection_revision,source_base_token,"
        "last_command_id FROM wfm_source_projection_cache WHERE task_id=?",
        (task_id,),
    ).fetchone()
    if row is None:
        return None
    revision = int(row[6])
    source_base_token = str(row[7])
    lifecycle = str(row[2])
    if revision <= 0 or lifecycle not in _SOURCE_CLASSES or _SHA256_RE.fullmatch(source_base_token) is None:
        raise IntegrityFailure("WFM source projection authority is invalid")
    start = None if row[3] is None else int(row[3])
    end = None if row[4] is None else int(row[4])
    if (start is None) != (end is None) or (start is not None and (start < 0 or end is None or end <= start)):
        raise IntegrityFailure("WFM source projection plan interval is invalid")
    return WfmSourceProjectionRecord(
        task_id=str(row[0]),
        provider_status_token=None if row[1] is None else str(row[1]),
        provider_lifecycle_class=lifecycle,
        source_plan_start_utc=start,
        source_plan_end_utc=end,
        accepted_source_observation_id=None if row[5] is None else str(row[5]),
        source_projection_revision=revision,
        source_base_token=source_base_token,
        last_command_id=str(row[8]),
    )


def _pending_review(reader: Any, task_id: str) -> WfmSourceTerminalReviewRecord | None:
    rows = reader.execute(
        "SELECT source_terminal_review_id,task_id,source_projection_revision,provider_lifecycle_class,"
        "input_fingerprint,state,local_consequence_event_id,revision,created_at_utc,decided_at_utc,last_command_id "
        "FROM wfm_source_terminal_reviews WHERE task_id=? AND state='pending' "
        "ORDER BY source_terminal_review_id",
        (task_id,),
    ).fetchall()
    if len(rows) > 1:
        raise IntegrityFailure("WFM source-terminal authority has more than one pending review")
    if not rows:
        return None
    row = rows[0]
    return WfmSourceTerminalReviewRecord(
        source_terminal_review_id=str(row[0]),
        task_id=str(row[1]),
        source_projection_revision=int(row[2]),
        provider_lifecycle_class=str(row[3]),
        input_fingerprint=str(row[4]),
        state=str(row[5]),
        local_consequence_event_id=None if row[6] is None else str(row[6]),
        revision=int(row[7]),
        created_at_utc=int(row[8]),
        decided_at_utc=None if row[9] is None else int(row[9]),
        last_command_id=None if row[10] is None else str(row[10]),
    )


def get_source_terminal_review(reader: Any, review_id: str) -> WfmSourceTerminalReviewRecord | None:
    row = reader.execute(
        "SELECT source_terminal_review_id,task_id,source_projection_revision,provider_lifecycle_class,"
        "input_fingerprint,state,local_consequence_event_id,revision,created_at_utc,decided_at_utc,last_command_id "
        "FROM wfm_source_terminal_reviews WHERE source_terminal_review_id=?",
        (review_id,),
    ).fetchone()
    if row is None:
        return None
    return WfmSourceTerminalReviewRecord(
        source_terminal_review_id=str(row[0]),
        task_id=str(row[1]),
        source_projection_revision=int(row[2]),
        provider_lifecycle_class=str(row[3]),
        input_fingerprint=str(row[4]),
        state=str(row[5]),
        local_consequence_event_id=None if row[6] is None else str(row[6]),
        revision=int(row[7]),
        created_at_utc=int(row[8]),
        decided_at_utc=None if row[9] is None else int(row[9]),
        last_command_id=None if row[10] is None else str(row[10]),
    )


def current_source_projection(reader: Any, task_id: str) -> WfmSourceProjectionRecord | None:
    return _source_projection(reader, task_id)


def _execution_fingerprint_state(reader: Any, task_id: str) -> dict[str, object]:
    authority = TaskExecutionService._execution_authority(reader, task_id)
    if authority.revision == 0:
        return {
            "revision": 0,
            "execution_state": "not_started",
            "actual_start_utc": None,
            "actual_end_utc": None,
            "effective_termination_utc": None,
            "termination_reason": None,
            "last_event_id": None,
        }
    projection = reader.execute(
        "SELECT termination_reason FROM task_execution_projection WHERE task_id=?",
        (task_id,),
    ).fetchone()
    if projection is None:
        raise IntegrityFailure("WFM terminal review execution projection disappeared")
    termination_reason = None if projection[0] is None else str(projection[0])
    if authority.state != "terminated" and termination_reason is not None:
        raise IntegrityFailure("nonterminal Task execution unexpectedly has a termination reason")
    return {
        "revision": authority.revision,
        "execution_state": authority.state,
        "actual_start_utc": authority.actual_start_utc,
        "actual_end_utc": authority.actual_end_utc,
        "effective_termination_utc": authority.effective_termination_utc,
        "termination_reason": termination_reason,
        "last_event_id": authority.last_event_id,
    }


def _plan_fingerprint_state(reader: Any, task_id: str) -> dict[str, object] | None:
    pointer = TaskPlanRepository.current_pointer(reader, task_id)
    if pointer is None:
        return None
    plan = TaskPlanRepository.get_revision(reader, pointer.plan_revision_id)
    if plan is None or plan.task_id != task_id:
        raise IntegrityFailure("current Task plan pointer is not bound to same-Task plan history")
    return {"plan_revision_id": pointer.plan_revision_id, "revision": pointer.revision}


def _membership_fingerprint_state(reader: Any, task_id: str) -> dict[str, object] | None:
    row = reader.execute(
        "SELECT m.objective_id,m.accepted_plan_revision_id,m.membership_revision,m.last_event_id,"
        "a.revision,a.aggregate_input_fingerprint FROM objective_task_membership_current m "
        "LEFT JOIN objective_aggregate_projection a ON a.objective_id=m.objective_id WHERE m.task_id=?",
        (task_id,),
    ).fetchone()
    if row is None:
        return None
    if row[4] is None or row[5] is None:
        raise IntegrityFailure("current Objective membership lacks aggregate consequence authority")
    objective_id = str(row[0])
    accepted_plan_revision_id = str(row[1])
    membership_revision = int(row[2])
    last_event_id = str(row[3])
    aggregate_revision = int(row[4])
    aggregate_fingerprint = str(row[5])
    if membership_revision <= 0 or aggregate_revision <= 0 or _SHA256_RE.fullmatch(aggregate_fingerprint) is None:
        raise IntegrityFailure("current Objective membership/aggregate authority is invalid")
    event = reader.execute(
        "SELECT to_objective_id,accepted_plan_revision_id FROM objective_membership_events "
        "WHERE membership_event_id=? AND task_id=?",
        (last_event_id, task_id),
    ).fetchone()
    if event is None or str(event[0]) != objective_id or str(event[1]) != accepted_plan_revision_id:
        raise IntegrityFailure("current Objective membership is not bound to same-Task history")
    return {
        "objective_id": objective_id,
        "accepted_plan_revision_id": accepted_plan_revision_id,
        "membership_revision": membership_revision,
        "last_event_id": last_event_id,
        "objective_aggregate_revision": aggregate_revision,
        "objective_aggregate_input_fingerprint": aggregate_fingerprint,
    }


def _lock_fingerprint_state(reader: Any, task_id: str) -> dict[str, object]:
    row = reader.execute(
        "SELECT explicit_plan_lock,explicit_membership_lock,revision,last_event_id "
        "FROM task_lock_projection WHERE task_id=?",
        (task_id,),
    ).fetchone()
    event_count = int(
        reader.execute("SELECT count(*) FROM task_lock_events WHERE task_id=?", (task_id,)).fetchone()[0]
    )
    if row is None:
        if event_count:
            raise IntegrityFailure("Task lock history exists without current projection")
        return {
            "revision": 0,
            "explicit_plan_lock": False,
            "explicit_membership_lock": False,
            "last_event_id": None,
        }
    plan = int(row[0])
    membership = int(row[1])
    revision = int(row[2])
    last_event_id = None if row[3] is None else str(row[3])
    if plan not in {0, 1} or membership not in {0, 1} or revision <= 0 or revision != event_count:
        raise IntegrityFailure("Task lock projection cannot be reconciled to lock history")
    if last_event_id is None:
        raise IntegrityFailure("positive Task lock projection lacks final history identity")
    if reader.execute(
        "SELECT 1 FROM task_lock_events WHERE lock_event_id=? AND task_id=?",
        (last_event_id, task_id),
    ).fetchone() is None:
        raise IntegrityFailure("Task lock projection last event is not owned by Task")
    return {
        "revision": revision,
        "explicit_plan_lock": bool(plan),
        "explicit_membership_lock": bool(membership),
        "last_event_id": last_event_id,
    }


def source_terminal_review_payload(reader: Any, task_id: str) -> dict[str, object]:
    canonical_task_id = require_uuid4(task_id)
    task = TaskRepository.get(reader, canonical_task_id)
    if task is None:
        raise SomaError("TASK_NOT_FOUND", "Task does not exist")
    if task.task_kind != "wfm" or WfmTaskRepository.get_identity(reader, canonical_task_id) is None:
        raise IntegrityFailure("source-terminal review requires canonical WFM Task identity")
    source = _source_projection(reader, canonical_task_id)
    if source is None or source.provider_lifecycle_class not in _TERMINAL_SOURCE_CLASSES:
        raise SomaError("WFM_SOURCE_TERMINAL_STALE", "current WFM source projection is not terminal")
    if source.accepted_source_observation_id is None:
        raise IntegrityFailure("terminal WFM source projection lacks accepted source observation")
    try:
        require_uuid4(source.accepted_source_observation_id)
    except ValidationError as exc:
        raise IntegrityFailure("terminal WFM source observation identity is invalid") from exc
    return {
        "schema": "SOMA_WFM_SOURCE_TERMINAL_REVIEW_V1",
        "task_id": canonical_task_id,
        "source": {
            "source_projection_revision": source.source_projection_revision,
            "provider_lifecycle_class": source.provider_lifecycle_class,
            "accepted_source_observation_id": source.accepted_source_observation_id,
            "source_base_token": source.source_base_token,
        },
        "execution": _execution_fingerprint_state(reader, canonical_task_id),
        "plan": _plan_fingerprint_state(reader, canonical_task_id),
        "membership": _membership_fingerprint_state(reader, canonical_task_id),
        "lock": _lock_fingerprint_state(reader, canonical_task_id),
    }


def source_terminal_review_fingerprint(reader: Any, task_id: str) -> str:
    return sha256_canonical_json(source_terminal_review_payload(reader, task_id))


def _local_terminal_decision_required(reader: Any, task_id: str) -> bool:
    execution = TaskExecutionService._execution_authority(reader, task_id)
    if execution.state in {"ended", "terminated"}:
        return False
    if execution.state == "in_progress":
        return True
    if TaskPlanRepository.current_pointer(reader, task_id) is not None:
        return True
    return reader.execute(
        "SELECT 1 FROM objective_task_membership_current WHERE task_id=?",
        (task_id,),
    ).fetchone() is not None


class WfmSourceProjectionParticipant:
    """LLD-05 participant used inside the caller LLD-04 proposal-acceptance UnitOfWork."""

    @staticmethod
    def apply_wfm_source_projection(
        uow: UnitOfWork,
        mutation: WfmSourceProjectionMutation,
        *,
        command_id: str,
    ) -> WfmSourceProjectionApplyResult:
        task_id = require_uuid4(mutation.task_id)
        expected_revision = _require_nonnegative_revision(
            mutation.expected_source_projection_revision,
            label="expected_source_projection_revision",
        )
        lifecycle = mutation.provider_lifecycle_class
        if lifecycle not in _SOURCE_CLASSES:
            raise ValidationError("provider_lifecycle_class is invalid")
        status_token = _bounded_optional_text(mutation.provider_status_token, label="provider_status_token")
        start_utc, end_utc = _validate_plan(mutation.source_plan_start_utc, mutation.source_plan_end_utc)
        source_base_token = _require_sha256(mutation.source_base_token, label="source_base_token")
        observation_id = mutation.accepted_source_observation_id
        if observation_id is not None:
            observation_id = require_uuid4(observation_id)
        if lifecycle in _TERMINAL_SOURCE_CLASSES and observation_id is None:
            raise ValidationError("terminal WFM source projection requires accepted source observation")

        task = TaskRepository.get(uow.connection, task_id)
        identity = WfmTaskRepository.get_identity(uow.connection, task_id)
        if task is None:
            raise SomaError("TASK_NOT_FOUND", "Task does not exist")
        if task.task_kind != "wfm" or identity is None:
            raise IntegrityFailure("WFM source projection target lacks WFM identity authority")
        receipt = uow.connection.execute(
            "SELECT 1 FROM command_receipts WHERE command_id=?",
            (command_id,),
        ).fetchone()
        if receipt is None:
            raise IntegrityFailure("WFM source participant requires caller-owned command receipt")

        current = _source_projection(uow.connection, task_id)
        current_revision = 0 if current is None else current.source_projection_revision
        if current_revision != expected_revision:
            raise SomaError("TASK_STALE", "WFM source projection revision changed")
        resulting_revision = current_revision + 1
        if current is None:
            uow.connection.execute(
                "INSERT INTO wfm_source_projection_cache(task_id,provider_status_token,provider_lifecycle_class,"
                "source_plan_start_utc,source_plan_end_utc,accepted_source_observation_id,source_projection_revision,"
                "source_base_token,last_command_id) VALUES (?,?,?,?,?,?,?,?,?)",
                (
                    task_id,
                    status_token,
                    lifecycle,
                    start_utc,
                    end_utc,
                    observation_id,
                    resulting_revision,
                    source_base_token,
                    command_id,
                ),
            )
        else:
            updated = uow.connection.execute(
                "UPDATE wfm_source_projection_cache SET provider_status_token=?,provider_lifecycle_class=?,"
                "source_plan_start_utc=?,source_plan_end_utc=?,accepted_source_observation_id=?,"
                "source_projection_revision=source_projection_revision+1,source_base_token=?,last_command_id=? "
                "WHERE task_id=? AND source_projection_revision=?",
                (
                    status_token,
                    lifecycle,
                    start_utc,
                    end_utc,
                    observation_id,
                    source_base_token,
                    command_id,
                    task_id,
                    expected_revision,
                ),
            )
            if updated.rowcount != 1:
                raise IntegrityFailure("WFM source projection changed during guarded participant mutation")

        now = utc_epoch_seconds()
        pending = _pending_review(uow.connection, task_id)
        should_review = lifecycle in _TERMINAL_SOURCE_CLASSES and _local_terminal_decision_required(
            uow.connection,
            task_id,
        )
        fingerprint: str | None = None
        if should_review:
            fingerprint = source_terminal_review_fingerprint(uow.connection, task_id)

        if pending is not None and (
            not should_review
            or pending.source_projection_revision != resulting_revision
            or pending.provider_lifecycle_class != lifecycle
            or pending.input_fingerprint != fingerprint
        ):
            updated = uow.connection.execute(
                "UPDATE wfm_source_terminal_reviews SET state='superseded',revision=revision+1,"
                "decided_at_utc=?,last_command_id=? WHERE source_terminal_review_id=? AND state='pending' AND revision=?",
                (now, command_id, pending.source_terminal_review_id, pending.revision),
            )
            if updated.rowcount != 1:
                raise IntegrityFailure("WFM source-terminal pending review changed during supersession")
            pending = None

        review_id: str | None = None
        if should_review:
            if pending is not None:
                review_id = pending.source_terminal_review_id
            else:
                if fingerprint is None:
                    raise IntegrityFailure("terminal review fingerprint was not computed")
                review_id = new_uuid4()
                uow.connection.execute(
                    "INSERT INTO wfm_source_terminal_reviews(source_terminal_review_id,task_id,"
                    "source_projection_revision,provider_lifecycle_class,input_fingerprint,state,"
                    "local_consequence_event_id,revision,created_at_utc,decided_at_utc,last_command_id) "
                    "VALUES (?,?,?,?,?,'pending',NULL,1,?,NULL,?)",
                    (
                        review_id,
                        task_id,
                        resulting_revision,
                        lifecycle,
                        fingerprint,
                        now,
                        command_id,
                    ),
                )

        refs: list[tuple[str, str]] = []
        if review_id is not None:
            refs.append(("wfm_source_terminal_review", review_id))
        return WfmSourceProjectionApplyResult(
            task_id=task_id,
            source_projection_revision=resulting_revision,
            source_terminal_review_id=review_id,
            source_terminal_review_fingerprint=fingerprint,
            result_refs=tuple(refs),
        )
