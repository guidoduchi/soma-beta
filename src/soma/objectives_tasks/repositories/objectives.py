from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from soma.foundation.errors import IntegrityFailure
from soma.foundation.identifiers import require_uuid4
from soma.foundation.persistence.uow import UnitOfWork
from soma.foundation.strict_json import sha256_canonical_json

_AGGREGATE_SCHEMA = "SOMA_OBJECTIVE_AGGREGATE_INPUT_V1"
_REVIEW_SCHEMA = "OBJECTIVE_REVIEW_INPUT_V1"
_EXECUTION_STATES = frozenset({"not_started", "in_progress", "ended", "terminated"})
_OUTCOMES = frozenset({"completed", "incomplete", "cancelled_without_execution"})
_OBJECTIVE_STATES = frozenset(
    {"planned", "historical_structure", "in_progress", "awaiting_review", "reviewed", "superseded"}
)
_AGGREGATE_OUTCOMES = frozenset(
    {"completed", "incomplete", "cancelled", "mixed", "excluded_from_operational_counts"}
)
_ATTENTION_REASONS = frozenset(
    {"lost_last_executable", "mixed_outcomes", "plan_membership_mismatch"}
)


@dataclass(frozen=True, slots=True)
class ObjectiveMembershipRecord:
    task_id: str
    objective_id: str
    accepted_plan_revision_id: str
    membership_revision: int
    last_event_id: str


@dataclass(frozen=True, slots=True)
class ObjectiveAggregateProjection:
    objective_id: str
    execution_state: str
    aggregate_outcome: str | None
    actual_start_utc: int | None
    actual_end_utc: int | None
    attention_reason: str | None
    included_task_count: int
    excluded_task_count: int
    aggregate_input_fingerprint: str
    revision: int
    last_command_id: str


@dataclass(frozen=True, slots=True)
class _MemberAuthority:
    task_id: str
    membership_revision: int
    accepted_plan_revision_id: str
    accepted_plan_start_utc: int
    accepted_plan_end_utc: int
    current_plan_revision: int
    current_plan_revision_id: str
    execution_revision: int
    execution_state: str
    actual_start_utc: int | None
    actual_end_utc: int | None
    effective_termination_utc: int | None
    outcome_revision: int
    outcome_event_id: str | None
    accepted_outcome: str | None
    operational_count_revision: int
    included: bool

    def aggregate_object(self) -> dict[str, object]:
        return {
            "task_id": self.task_id,
            "membership_revision": self.membership_revision,
            "accepted_plan": {
                "plan_revision_id": self.accepted_plan_revision_id,
                "start_utc": self.accepted_plan_start_utc,
                "end_utc": self.accepted_plan_end_utc,
            },
            "current_plan": {
                "revision": self.current_plan_revision,
                "plan_revision_id": self.current_plan_revision_id,
            },
            "execution": {
                "revision": self.execution_revision,
                "state": self.execution_state,
                "actual_start_utc": self.actual_start_utc,
                "actual_end_utc": self.actual_end_utc,
                "effective_termination_utc": self.effective_termination_utc,
            },
            "outcome": {
                "revision": self.outcome_revision,
                "outcome_event_id": self.outcome_event_id,
                "accepted_outcome": self.accepted_outcome,
            },
            "operational_count": {
                "revision": self.operational_count_revision,
                "included": self.included,
            },
        }

    def review_object(self) -> dict[str, object]:
        return {
            "task_id": self.task_id,
            "membership_revision": self.membership_revision,
            "accepted_plan_revision_id": self.accepted_plan_revision_id,
            "execution_revision": self.execution_revision,
            "outcome_event_id": self.outcome_event_id,
            "outcome_revision": self.outcome_revision,
            "operational_count_revision": self.operational_count_revision,
            "included": self.included,
        }

    @property
    def has_started(self) -> bool:
        return self.actual_start_utc is not None

    @property
    def locally_executable(self) -> bool:
        return self.execution_state == "not_started" and self.accepted_outcome is None


def _stored_uuid(value: object, *, label: str) -> str:
    if not isinstance(value, str):
        raise IntegrityFailure(f"stored {label} is not UUID text")
    try:
        return require_uuid4(value)
    except Exception as exc:
        raise IntegrityFailure(f"stored {label} is not canonical UUIDv4") from exc


def _positive(value: object, *, label: str) -> int:
    if type(value) is not int or value <= 0:
        raise IntegrityFailure(f"stored {label} is not a positive integer")
    return value


def _optional_nonnegative(value: object, *, label: str) -> int | None:
    if value is None:
        return None
    if type(value) is not int or value < 0:
        raise IntegrityFailure(f"stored {label} is invalid")
    return value


class ObjectiveProjectionRepository:
    """Current Objective membership and deterministic rebuildable aggregate authority."""

    @staticmethod
    def current_membership_for_task(reader: Any, task_id: str) -> ObjectiveMembershipRecord | None:
        row = reader.execute(
            "SELECT m.task_id,m.objective_id,m.accepted_plan_revision_id,m.membership_revision,m.last_event_id,"
            "e.task_id,e.to_objective_id,e.accepted_plan_revision_id "
            "FROM objective_task_membership_current m "
            "LEFT JOIN objective_membership_events e ON e.membership_event_id=m.last_event_id "
            "WHERE m.task_id=?",
            (task_id,),
        ).fetchone()
        if row is None:
            return None
        stored_task_id = _stored_uuid(row[0], label="Objective membership Task identity")
        objective_id = _stored_uuid(row[1], label="Objective membership identity")
        accepted_plan_id = _stored_uuid(row[2], label="Objective membership plan identity")
        revision = _positive(row[3], label="Objective membership revision")
        last_event_id = _stored_uuid(row[4], label="Objective membership event identity")
        if row[5] is None or row[6] is None or row[7] is None:
            raise IntegrityFailure("Objective membership current row is not bound to immutable history")
        if (
            _stored_uuid(row[5], label="Objective membership event Task identity") != stored_task_id
            or _stored_uuid(row[6], label="Objective membership event Objective identity") != objective_id
            or _stored_uuid(row[7], label="Objective membership event plan identity") != accepted_plan_id
        ):
            raise IntegrityFailure("Objective membership current row disagrees with immutable history")
        return ObjectiveMembershipRecord(
            task_id=stored_task_id,
            objective_id=objective_id,
            accepted_plan_revision_id=accepted_plan_id,
            membership_revision=revision,
            last_event_id=last_event_id,
        )

    @staticmethod
    def aggregate(reader: Any, objective_id: str) -> ObjectiveAggregateProjection | None:
        row = reader.execute(
            "SELECT objective_id,execution_state,aggregate_outcome,actual_start_utc,actual_end_utc,attention_reason,"
            "included_task_count,excluded_task_count,aggregate_input_fingerprint,revision,last_command_id "
            "FROM objective_aggregate_projection WHERE objective_id=?",
            (objective_id,),
        ).fetchone()
        if row is None:
            return None
        identity = _stored_uuid(row[0], label="Objective aggregate identity")
        state = str(row[1])
        outcome = None if row[2] is None else str(row[2])
        attention = None if row[5] is None else str(row[5])
        fingerprint = str(row[8])
        if state not in _OBJECTIVE_STATES:
            raise IntegrityFailure("Objective aggregate has invalid execution state")
        if outcome is not None and outcome not in _AGGREGATE_OUTCOMES:
            raise IntegrityFailure("Objective aggregate has invalid outcome")
        if attention is not None and attention not in _ATTENTION_REASONS:
            raise IntegrityFailure("Objective aggregate has non-material attention authority")
        if len(fingerprint) != 64 or any(character not in "0123456789abcdef" for character in fingerprint):
            raise IntegrityFailure("Objective aggregate fingerprint is invalid")
        included = row[6]
        excluded = row[7]
        if type(included) is not int or included < 0 or type(excluded) is not int or excluded < 0:
            raise IntegrityFailure("Objective aggregate member counts are invalid")
        command_id = _stored_uuid(row[10], label="Objective aggregate command identity")
        return ObjectiveAggregateProjection(
            objective_id=identity,
            execution_state=state,
            aggregate_outcome=outcome,
            actual_start_utc=_optional_nonnegative(row[3], label="Objective actual start"),
            actual_end_utc=_optional_nonnegative(row[4], label="Objective actual end"),
            attention_reason=attention,
            included_task_count=included,
            excluded_task_count=excluded,
            aggregate_input_fingerprint=fingerprint,
            revision=_positive(row[9], label="Objective aggregate revision"),
            last_command_id=command_id,
        )

    @staticmethod
    def _load_objective(reader: Any, objective_id: str) -> tuple[int, str, str | None]:
        row = reader.execute(
            "SELECT revision,creation_origin,superseded_by_objective_id FROM objectives WHERE objective_id=?",
            (objective_id,),
        ).fetchone()
        if row is None:
            raise IntegrityFailure("Objective aggregate rebuild target does not exist")
        revision = _positive(row[0], label="Objective revision")
        origin = str(row[1])
        if origin not in {"manual", "automatic_grouping", "historical_provider_complete"}:
            raise IntegrityFailure("Objective creation origin is invalid")
        superseded = None if row[2] is None else _stored_uuid(row[2], label="superseding Objective identity")
        return revision, origin, superseded

    @classmethod
    def _load_members(cls, reader: Any, objective_id: str) -> tuple[_MemberAuthority, ...]:
        rows = reader.execute(
            "SELECT m.task_id,m.membership_revision,m.accepted_plan_revision_id,m.last_event_id,"
            "mp.task_id,mp.start_utc,mp.end_utc,"
            "pc.revision,pc.plan_revision_id,cp.task_id,"
            "ep.revision,ep.execution_state,ep.actual_start_utc,ep.actual_end_utc,ep.effective_termination_utc,ep.last_event_id,ee.task_id,"
            "oc.revision,oc.outcome_event_id,oc.accepted_outcome,oe.task_id,oe.accepted_outcome,"
            "ic.revision,ic.included,ic.last_event_id,ie.task_id,ie.included,"
            "me.task_id,me.to_objective_id,me.accepted_plan_revision_id "
            "FROM objective_task_membership_current m "
            "JOIN task_plan_revisions mp ON mp.plan_revision_id=m.accepted_plan_revision_id "
            "LEFT JOIN task_plan_current pc ON pc.task_id=m.task_id "
            "LEFT JOIN task_plan_revisions cp ON cp.plan_revision_id=pc.plan_revision_id "
            "LEFT JOIN task_execution_projection ep ON ep.task_id=m.task_id "
            "LEFT JOIN task_execution_events ee ON ee.execution_event_id=ep.last_event_id "
            "LEFT JOIN task_outcome_current oc ON oc.task_id=m.task_id "
            "LEFT JOIN task_outcome_events oe ON oe.outcome_event_id=oc.outcome_event_id "
            "LEFT JOIN task_operational_count_current ic ON ic.task_id=m.task_id "
            "LEFT JOIN task_operational_count_events ie ON ie.inclusion_event_id=ic.last_event_id "
            "LEFT JOIN objective_membership_events me ON me.membership_event_id=m.last_event_id "
            "WHERE m.objective_id=? ORDER BY m.task_id",
            (objective_id,),
        ).fetchall()
        members: list[_MemberAuthority] = []
        for row in rows:
            task_id = _stored_uuid(row[0], label="Objective member Task identity")
            membership_revision = _positive(row[1], label="Objective membership revision")
            accepted_plan_id = _stored_uuid(row[2], label="Objective membership pinned plan identity")
            _stored_uuid(row[3], label="Objective membership event identity")
            if _stored_uuid(row[4], label="Objective pinned plan owner identity") != task_id:
                raise IntegrityFailure("Objective membership pins another Task's plan")
            start_utc = _optional_nonnegative(row[5], label="Objective pinned plan start")
            end_utc = _optional_nonnegative(row[6], label="Objective pinned plan end")
            if start_utc is None or end_utc is None or end_utc <= start_utc:
                raise IntegrityFailure("Objective membership pins an invalid Task interval")

            if row[7] is None or row[8] is None or row[9] is None:
                raise IntegrityFailure("current Objective member is missing current Task plan authority")
            current_plan_revision = _positive(row[7], label="current Task plan revision")
            current_plan_id = _stored_uuid(row[8], label="current Task plan identity")
            if _stored_uuid(row[9], label="current Task plan owner identity") != task_id:
                raise IntegrityFailure("current Task plan belongs to another Task")

            execution_revision = 0
            execution_state = "not_started"
            actual_start = actual_end = termination = None
            if row[10] is not None:
                execution_revision = _positive(row[10], label="Task execution revision")
                execution_state = str(row[11])
                if execution_state not in _EXECUTION_STATES or row[15] is None or row[16] is None:
                    raise IntegrityFailure("Task execution projection is incomplete")
                if _stored_uuid(row[16], label="Task execution last-event owner identity") != task_id:
                    raise IntegrityFailure("Task execution projection points to another Task's event")
                actual_start = _optional_nonnegative(row[12], label="Task actual start")
                actual_end = _optional_nonnegative(row[13], label="Task actual end")
                termination = _optional_nonnegative(row[14], label="Task termination instant")
                cls._validate_execution_shape(
                    execution_state,
                    actual_start=actual_start,
                    actual_end=actual_end,
                    termination=termination,
                )
            elif any(row[index] is not None for index in (11, 12, 13, 14, 15, 16)):
                raise IntegrityFailure("Task execution absence authority is inconsistent")

            outcome_revision = 0
            outcome_event_id: str | None = None
            accepted_outcome: str | None = None
            if row[17] is not None:
                outcome_revision = _positive(row[17], label="Task outcome revision")
                outcome_event_id = _stored_uuid(row[18], label="Task outcome event identity")
                accepted_outcome = str(row[19])
                if accepted_outcome not in _OUTCOMES or row[20] is None or row[21] is None:
                    raise IntegrityFailure("Task outcome projection is incomplete")
                if _stored_uuid(row[20], label="Task outcome event owner identity") != task_id or str(row[21]) != accepted_outcome:
                    raise IntegrityFailure("Task outcome projection disagrees with immutable history")
                cls._validate_outcome_execution(accepted_outcome, execution_state, actual_start, actual_end)
            elif any(row[index] is not None for index in (18, 19, 20, 21)):
                raise IntegrityFailure("Task outcome absence authority is inconsistent")

            count_revision = 0
            included = True
            if row[22] is not None:
                count_revision = _positive(row[22], label="operational-count revision")
                if row[23] not in (0, 1) or row[24] is None or row[25] is None or row[26] is None:
                    raise IntegrityFailure("operational-count projection is incomplete")
                if _stored_uuid(row[25], label="operational-count event owner identity") != task_id:
                    raise IntegrityFailure("operational-count projection points to another Task")
                if int(row[26]) != int(row[23]):
                    raise IntegrityFailure("operational-count projection disagrees with immutable history")
                included = bool(row[23])
            elif any(row[index] is not None for index in (23, 24, 25, 26)):
                raise IntegrityFailure("operational-count absence authority is inconsistent")

            if row[27] is None or row[28] is None or row[29] is None:
                raise IntegrityFailure("Objective membership current authority is not bound to immutable history")
            if (
                _stored_uuid(row[27], label="Objective membership history Task identity") != task_id
                or _stored_uuid(row[28], label="Objective membership history Objective identity") != objective_id
                or _stored_uuid(row[29], label="Objective membership history plan identity") != accepted_plan_id
            ):
                raise IntegrityFailure("Objective membership current authority disagrees with immutable history")

            members.append(
                _MemberAuthority(
                    task_id=task_id,
                    membership_revision=membership_revision,
                    accepted_plan_revision_id=accepted_plan_id,
                    accepted_plan_start_utc=start_utc,
                    accepted_plan_end_utc=end_utc,
                    current_plan_revision=current_plan_revision,
                    current_plan_revision_id=current_plan_id,
                    execution_revision=execution_revision,
                    execution_state=execution_state,
                    actual_start_utc=actual_start,
                    actual_end_utc=actual_end,
                    effective_termination_utc=termination,
                    outcome_revision=outcome_revision,
                    outcome_event_id=outcome_event_id,
                    accepted_outcome=accepted_outcome,
                    operational_count_revision=count_revision,
                    included=included,
                )
            )

        if len({member.task_id for member in members}) != len(members):
            raise IntegrityFailure("Objective aggregate member query returned duplicate Tasks")
        return tuple(members)

    @staticmethod
    def _validate_execution_shape(
        state: str,
        *,
        actual_start: int | None,
        actual_end: int | None,
        termination: int | None,
    ) -> None:
        if state == "not_started" and any(value is not None for value in (actual_start, actual_end, termination)):
            raise IntegrityFailure("not-started execution projection contains actual evidence")
        if state == "in_progress" and (actual_start is None or actual_end is not None or termination is not None):
            raise IntegrityFailure("in-progress execution projection is invalid")
        if state == "ended" and (
            actual_start is None or actual_end is None or actual_end < actual_start or termination is not None
        ):
            raise IntegrityFailure("ended execution projection is invalid")
        if state == "terminated" and actual_end is not None:
            raise IntegrityFailure("terminated execution projection fabricates actual end")

    @staticmethod
    def _validate_outcome_execution(
        outcome: str,
        state: str,
        actual_start: int | None,
        actual_end: int | None,
    ) -> None:
        if outcome == "completed" and (state != "ended" or actual_start is None or actual_end is None):
            raise IntegrityFailure("completed Task outcome is incompatible with execution authority")
        if outcome == "incomplete" and (state not in {"ended", "terminated"} or actual_start is None):
            raise IntegrityFailure("incomplete Task outcome is incompatible with execution authority")
        if outcome == "cancelled_without_execution" and (state != "terminated" or actual_start is not None):
            raise IntegrityFailure("cancelled Task outcome is incompatible with execution authority")

    @staticmethod
    def _review_fingerprint(
        *,
        objective_id: str,
        objective_revision: int,
        superseded_by: str | None,
        members: tuple[_MemberAuthority, ...],
    ) -> str:
        return sha256_canonical_json(
            {
                "schema": _REVIEW_SCHEMA,
                "objective_id": objective_id,
                "objective_revision": objective_revision,
                "superseded_by_objective_id": superseded_by,
                "members": [member.review_object() for member in members],
            }
        )

    @staticmethod
    def _current_review(reader: Any, objective_id: str, review_fingerprint: str) -> dict[str, object] | None:
        row = reader.execute(
            "SELECT objective_review_event_id,review_fingerprint,derived_outcome "
            "FROM objective_review_events WHERE objective_id=? AND review_fingerprint=? "
            "ORDER BY reviewed_at_utc DESC,objective_review_event_id DESC LIMIT 1",
            (objective_id, review_fingerprint),
        ).fetchone()
        if row is None:
            return None
        event_id = _stored_uuid(row[0], label="Objective review event identity")
        fingerprint = str(row[1])
        outcome = str(row[2])
        if fingerprint != review_fingerprint or outcome not in _AGGREGATE_OUTCOMES:
            raise IntegrityFailure("Objective current review authority is invalid")
        return {
            "objective_review_event_id": event_id,
            "review_fingerprint": fingerprint,
            "derived_outcome": outcome,
        }

    @staticmethod
    def _derive_outcome(members: tuple[_MemberAuthority, ...]) -> str | None:
        included = [member for member in members if member.included]
        if not included:
            return "excluded_from_operational_counts" if members else None
        if any(member.accepted_outcome is None for member in members):
            return None
        outcomes = {member.accepted_outcome for member in included}
        if outcomes == {"completed"}:
            return "completed"
        if outcomes == {"incomplete"}:
            return "incomplete"
        if outcomes == {"cancelled_without_execution"} and all(not member.has_started for member in members):
            return "cancelled"
        if len(outcomes) > 1:
            return "mixed"
        return None

    @classmethod
    def _derive_material_state(
        cls,
        *,
        origin: str,
        superseded_by: str | None,
        members: tuple[_MemberAuthority, ...],
        current_review: dict[str, object] | None,
    ) -> tuple[str, str | None, int | None, int | None, str | None, int, int]:
        included_count = sum(1 for member in members if member.included)
        excluded_count = len(members) - included_count
        starts = [member.actual_start_utc for member in members if member.actual_start_utc is not None]
        actual_start = min(starts) if starts else None
        any_in_progress = any(member.execution_state == "in_progress" for member in members)
        terminal_started = [member for member in members if member.has_started and member.execution_state != "in_progress"]
        actual_end: int | None = None
        if starts and not any_in_progress:
            terminal_times = [
                member.actual_end_utc
                if member.actual_end_utc is not None
                else member.effective_termination_utc
                for member in terminal_started
            ]
            if len(terminal_started) == len(starts) and terminal_times and all(value is not None for value in terminal_times):
                actual_end = max(int(value) for value in terminal_times if value is not None)

        mismatch = any(member.current_plan_revision_id != member.accepted_plan_revision_id for member in members)
        aggregate_outcome = cls._derive_outcome(members)
        attention: str | None = None
        if superseded_by is not None:
            state = "superseded"
        elif origin == "historical_provider_complete" and not starts:
            state = "historical_structure"
        elif any_in_progress:
            state = "in_progress"
            aggregate_outcome = None
        elif members and all(member.accepted_outcome is not None for member in members):
            state = "reviewed" if current_review is not None else "awaiting_review"
            if aggregate_outcome == "mixed":
                attention = "mixed_outcomes"
        elif starts and not any(member.locally_executable for member in members):
            state = "awaiting_review"
            attention = "lost_last_executable"
            aggregate_outcome = None
        else:
            state = "planned"
            aggregate_outcome = None
        if attention is None and mismatch:
            attention = "plan_membership_mismatch"
        return state, aggregate_outcome, actual_start, actual_end, attention, included_count, excluded_count

    @staticmethod
    def _validate_envelope(reader: Any, objective_id: str, members: tuple[_MemberAuthority, ...]) -> None:
        row = reader.execute(
            "SELECT start_utc,end_utc,member_count FROM objective_envelope_projection WHERE objective_id=?",
            (objective_id,),
        ).fetchone()
        if row is None:
            raise IntegrityFailure("current Objective is missing envelope projection")
        if not members:
            raise IntegrityFailure("current Objective has no members")
        expected_start = min(member.accepted_plan_start_utc for member in members)
        expected_end = max(member.accepted_plan_end_utc for member in members)
        if int(row[0]) != expected_start or int(row[1]) != expected_end or int(row[2]) != len(members):
            raise IntegrityFailure("Objective envelope projection disagrees with membership-pinned plans")

    @classmethod
    def rebuild_aggregate(
        cls,
        uow: UnitOfWork,
        *,
        objective_id: str,
        command_id: str,
    ) -> ObjectiveAggregateProjection:
        canonical_objective_id = _stored_uuid(objective_id, label="Objective rebuild identity")
        canonical_command_id = _stored_uuid(command_id, label="Objective rebuild command identity")
        objective_revision, origin, superseded_by = cls._load_objective(uow.connection, canonical_objective_id)
        members = cls._load_members(uow.connection, canonical_objective_id)
        if superseded_by is None:
            cls._validate_envelope(uow.connection, canonical_objective_id, members)
        review_fingerprint = cls._review_fingerprint(
            objective_id=canonical_objective_id,
            objective_revision=objective_revision,
            superseded_by=superseded_by,
            members=members,
        )
        current_review = cls._current_review(uow.connection, canonical_objective_id, review_fingerprint)
        fingerprint = sha256_canonical_json(
            {
                "schema": _AGGREGATE_SCHEMA,
                "objective": {
                    "objective_id": canonical_objective_id,
                    "revision": objective_revision,
                    "creation_origin": origin,
                    "superseded_by_objective_id": superseded_by,
                },
                "members": [member.aggregate_object() for member in members],
                "current_review": current_review,
            }
        )
        (
            state,
            aggregate_outcome,
            actual_start,
            actual_end,
            attention,
            included_count,
            excluded_count,
        ) = cls._derive_material_state(
            origin=origin,
            superseded_by=superseded_by,
            members=members,
            current_review=current_review,
        )
        existing = cls.aggregate(uow.connection, canonical_objective_id)
        material = (
            state,
            aggregate_outcome,
            actual_start,
            actual_end,
            attention,
            included_count,
            excluded_count,
        )
        if existing is not None:
            existing_material = (
                existing.execution_state,
                existing.aggregate_outcome,
                existing.actual_start_utc,
                existing.actual_end_utc,
                existing.attention_reason,
                existing.included_task_count,
                existing.excluded_task_count,
            )
            if existing.aggregate_input_fingerprint == fingerprint:
                if existing_material != material:
                    raise IntegrityFailure("Objective aggregate fingerprint agrees while material fields disagree")
                return existing
            updated = uow.connection.execute(
                "UPDATE objective_aggregate_projection SET execution_state=?,aggregate_outcome=?,actual_start_utc=?,"
                "actual_end_utc=?,attention_reason=?,included_task_count=?,excluded_task_count=?,"
                "aggregate_input_fingerprint=?,revision=revision+1,last_command_id=? "
                "WHERE objective_id=? AND revision=?",
                (
                    state,
                    aggregate_outcome,
                    actual_start,
                    actual_end,
                    attention,
                    included_count,
                    excluded_count,
                    fingerprint,
                    canonical_command_id,
                    canonical_objective_id,
                    existing.revision,
                ),
            )
            if updated.rowcount != 1:
                raise IntegrityFailure("Objective aggregate changed during guarded rebuild")
        else:
            uow.connection.execute(
                "INSERT INTO objective_aggregate_projection(objective_id,execution_state,aggregate_outcome,actual_start_utc,"
                "actual_end_utc,attention_reason,included_task_count,excluded_task_count,aggregate_input_fingerprint,"
                "revision,last_command_id) VALUES (?,?,?,?,?,?,?,?,?,1,?)",
                (
                    canonical_objective_id,
                    state,
                    aggregate_outcome,
                    actual_start,
                    actual_end,
                    attention,
                    included_count,
                    excluded_count,
                    fingerprint,
                    canonical_command_id,
                ),
            )
        rebuilt = cls.aggregate(uow.connection, canonical_objective_id)
        if rebuilt is None:
            raise IntegrityFailure("Objective aggregate rebuild did not publish a projection")
        return rebuilt
