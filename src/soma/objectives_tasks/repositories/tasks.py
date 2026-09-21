from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Any

from soma.foundation.errors import IntegrityFailure, ValidationError
from soma.foundation.persistence.uow import UnitOfWork


class TaskNoStatus(StrEnum):
    ACTIVE = "ACTIVE"
    RETIRED = "RETIRED"
    ABSENT = "ABSENT"


@dataclass(frozen=True, slots=True)
class TaskRecord:
    task_id: str
    task_kind: str
    local_task_name: str | None
    creation_origin: str
    revision: int
    created_at_utc: int
    created_command_id: str


@dataclass(frozen=True, slots=True)
class WfmTaskIdentityRecord:
    task_id: str
    task_no: str
    current_rfc_id: str
    assignment_revision: int
    created_command_id: str


@dataclass(frozen=True, slots=True)
class TaskPlanRecord:
    plan_revision_id: str
    task_id: str
    start_utc: int
    end_utc: int
    origin: str
    scheduling_timezone_iana: str
    source_observation_id: str | None
    predecessor_plan_revision_id: str | None
    reason_code: str | None
    accepted_at_utc: int
    command_id: str


@dataclass(frozen=True, slots=True)
class TaskPlanCurrentPointer:
    task_id: str
    plan_revision_id: str
    revision: int
    last_command_id: str


@dataclass(frozen=True, slots=True)
class TaskRelationshipRecord:
    relationship_id: str
    task_id: str
    relationship_kind: str
    related_id: str
    opened_command_id: str


class TaskRepository:
    @staticmethod
    def get(reader: Any, task_id: str) -> TaskRecord | None:
        row = reader.execute(
            "SELECT task_id,task_kind,local_task_name,creation_origin,revision,created_at_utc,created_command_id "
            "FROM tasks WHERE task_id=?",
            (task_id,),
        ).fetchone()
        if row is None:
            return None
        return TaskRecord(
            task_id=str(row[0]),
            task_kind=str(row[1]),
            local_task_name=None if row[2] is None else str(row[2]),
            creation_origin=str(row[3]),
            revision=int(row[4]),
            created_at_utc=int(row[5]),
            created_command_id=str(row[6]),
        )

    @staticmethod
    def insert(uow: UnitOfWork, row: TaskRecord) -> None:
        uow.connection.execute(
            "INSERT INTO tasks(task_id,task_kind,local_task_name,creation_origin,revision,created_at_utc,created_command_id) "
            "VALUES (?,?,?,?,?,?,?)",
            (
                row.task_id,
                row.task_kind,
                row.local_task_name,
                row.creation_origin,
                row.revision,
                row.created_at_utc,
                row.created_command_id,
            ),
        )

    @staticmethod
    def increment_revision(uow: UnitOfWork, *, task_id: str, expected_revision: int) -> None:
        updated = uow.connection.execute(
            "UPDATE tasks SET revision=revision+1 WHERE task_id=? AND revision=?",
            (task_id, expected_revision),
        )
        if updated.rowcount != 1:
            raise IntegrityFailure("Task revision changed during guarded mutation")


class WfmTaskRepository:
    @staticmethod
    def task_no_status(reader: Any, task_no: str) -> TaskNoStatus:
        row = reader.execute(
            "SELECT "
            "(SELECT count(*) FROM wfm_task_identities WHERE task_no=?),"
            "(SELECT count(*) FROM wfm_task_no_retirements WHERE task_no=?)",
            (task_no, task_no),
        ).fetchone()
        if row is None:
            raise IntegrityFailure("WFM Task No status query produced no row")
        active_count, retired_count = int(row[0]), int(row[1])
        if active_count not in {0, 1} or retired_count not in {0, 1}:
            raise IntegrityFailure("WFM Task No status cardinality is invalid")
        if active_count and retired_count:
            raise IntegrityFailure("WFM Task No is simultaneously ACTIVE and RETIRED")
        if active_count:
            return TaskNoStatus.ACTIVE
        if retired_count:
            return TaskNoStatus.RETIRED
        return TaskNoStatus.ABSENT

    @staticmethod
    def get_by_task_no(reader: Any, task_no: str) -> WfmTaskIdentityRecord | None:
        row = reader.execute(
            "SELECT task_id,task_no,current_rfc_id,assignment_revision,created_command_id "
            "FROM wfm_task_identities WHERE task_no=?",
            (task_no,),
        ).fetchone()
        return None if row is None else WfmTaskRepository._identity(row)

    @staticmethod
    def get_identity(reader: Any, task_id: str) -> WfmTaskIdentityRecord | None:
        row = reader.execute(
            "SELECT task_id,task_no,current_rfc_id,assignment_revision,created_command_id "
            "FROM wfm_task_identities WHERE task_id=?",
            (task_id,),
        ).fetchone()
        return None if row is None else WfmTaskRepository._identity(row)

    @staticmethod
    def _identity(row: Any) -> WfmTaskIdentityRecord:
        return WfmTaskIdentityRecord(
            task_id=str(row[0]),
            task_no=str(row[1]),
            current_rfc_id=str(row[2]),
            assignment_revision=int(row[3]),
            created_command_id=str(row[4]),
        )

    @staticmethod
    def insert_identity(
        uow: UnitOfWork,
        *,
        task_id: str,
        task_no: str,
        rfc_id: str,
        created_command_id: str,
    ) -> None:
        uow.connection.execute(
            "INSERT INTO wfm_task_identities(task_id,task_no,current_rfc_id,assignment_revision,created_command_id) "
            "VALUES (?,?,?,1,?)",
            (task_id, task_no, rfc_id, created_command_id),
        )

    @staticmethod
    def insert_initial_assignment(
        uow: UnitOfWork,
        *,
        assignment_event_id: str,
        task_id: str,
        rfc_id: str,
        command_id: str,
        recorded_at_utc: int,
    ) -> None:
        uow.connection.execute(
            "INSERT INTO wfm_rfc_assignment_events(assignment_event_id,task_id,prior_rfc_id,new_rfc_id,reason_code,"
            "review_risk,recorded_at_utc,command_id) VALUES (?,?,NULL,?,'manual_registration','low',?,?)",
            (assignment_event_id, task_id, rfc_id, recorded_at_utc, command_id),
        )

    @staticmethod
    def reassign_rfc(
        uow: UnitOfWork,
        *,
        assignment_event_id: str,
        task_id: str,
        prior_rfc_id: str,
        new_rfc_id: str,
        expected_assignment_revision: int,
        reason_code: str,
        review_risk: str,
        command_id: str,
        recorded_at_utc: int,
    ) -> None:
        updated = uow.connection.execute(
            "UPDATE wfm_task_identities SET current_rfc_id=?,assignment_revision=assignment_revision+1 "
            "WHERE task_id=? AND current_rfc_id=? AND assignment_revision=?",
            (new_rfc_id, task_id, prior_rfc_id, expected_assignment_revision),
        )
        if updated.rowcount != 1:
            raise IntegrityFailure("WFM assignment authority changed during guarded reassignment")
        uow.connection.execute(
            "INSERT INTO wfm_rfc_assignment_events(assignment_event_id,task_id,prior_rfc_id,new_rfc_id,reason_code,"
            "review_risk,recorded_at_utc,command_id) VALUES (?,?,?,?,?,?,?,?)",
            (
                assignment_event_id,
                task_id,
                prior_rfc_id,
                new_rfc_id,
                reason_code,
                review_risk,
                recorded_at_utc,
                command_id,
            ),
        )

    @staticmethod
    def retire_task_no(
        uow: UnitOfWork,
        *,
        retirement_id: str,
        task_no: str,
        task_id: str,
        retired_at_utc: int,
        hard_delete_command_id: str,
    ) -> None:
        uow.connection.execute(
            "INSERT INTO wfm_task_no_retirements(retirement_id,task_no,retired_task_id,retired_at_utc,hard_delete_command_id) "
            "VALUES (?,?,?,?,?)",
            (retirement_id, task_no, task_id, retired_at_utc, hard_delete_command_id),
        )


class TaskPlanRepository:
    @staticmethod
    def current_plan_revision_id(reader: Any, task_id: str) -> str | None:
        row = reader.execute(
            "SELECT plan_revision_id FROM task_plan_current WHERE task_id=?",
            (task_id,),
        ).fetchone()
        return None if row is None else str(row[0])

    @staticmethod
    def current_pointer(reader: Any, task_id: str) -> TaskPlanCurrentPointer | None:
        row = reader.execute(
            "SELECT task_id,plan_revision_id,revision,last_command_id FROM task_plan_current WHERE task_id=?",
            (task_id,),
        ).fetchone()
        if row is None:
            return None
        return TaskPlanCurrentPointer(
            task_id=str(row[0]),
            plan_revision_id=str(row[1]),
            revision=int(row[2]),
            last_command_id=str(row[3]),
        )

    @staticmethod
    def get_revision(reader: Any, plan_revision_id: str) -> TaskPlanRecord | None:
        row = reader.execute(
            "SELECT plan_revision_id,task_id,start_utc,end_utc,origin,scheduling_timezone_iana,"
            "source_observation_id,predecessor_plan_revision_id,reason_code,accepted_at_utc,command_id "
            "FROM task_plan_revisions WHERE plan_revision_id=?",
            (plan_revision_id,),
        ).fetchone()
        if row is None:
            return None
        return TaskPlanRecord(
            plan_revision_id=str(row[0]),
            task_id=str(row[1]),
            start_utc=int(row[2]),
            end_utc=int(row[3]),
            origin=str(row[4]),
            scheduling_timezone_iana=str(row[5]),
            source_observation_id=None if row[6] is None else str(row[6]),
            predecessor_plan_revision_id=None if row[7] is None else str(row[7]),
            reason_code=None if row[8] is None else str(row[8]),
            accepted_at_utc=int(row[9]),
            command_id=str(row[10]),
        )

    @staticmethod
    def _insert_revision(uow: UnitOfWork, row: TaskPlanRecord) -> None:
        uow.connection.execute(
            "INSERT INTO task_plan_revisions(plan_revision_id,task_id,start_utc,end_utc,origin,scheduling_timezone_iana,"
            "source_observation_id,predecessor_plan_revision_id,reason_code,accepted_at_utc,command_id) "
            "VALUES (?,?,?,?,?,?,?,?,?,?,?)",
            (
                row.plan_revision_id,
                row.task_id,
                row.start_utc,
                row.end_utc,
                row.origin,
                row.scheduling_timezone_iana,
                row.source_observation_id,
                row.predecessor_plan_revision_id,
                row.reason_code,
                row.accepted_at_utc,
                row.command_id,
            ),
        )

    @classmethod
    def insert_initial(cls, uow: UnitOfWork, row: TaskPlanRecord) -> None:
        cls._insert_revision(uow, row)
        uow.connection.execute(
            "INSERT INTO task_plan_current(task_id,plan_revision_id,revision,last_command_id) VALUES (?,?,1,?)",
            (row.task_id, row.plan_revision_id, row.command_id),
        )

    @classmethod
    def append_and_set_current(
        cls,
        uow: UnitOfWork,
        row: TaskPlanRecord,
        *,
        expected_current_revision: int,
    ) -> None:
        cls._insert_revision(uow, row)
        if expected_current_revision == 0:
            uow.connection.execute(
                "INSERT INTO task_plan_current(task_id,plan_revision_id,revision,last_command_id) VALUES (?,?,1,?)",
                (row.task_id, row.plan_revision_id, row.command_id),
            )
            return
        updated = uow.connection.execute(
            "UPDATE task_plan_current SET plan_revision_id=?,revision=revision+1,last_command_id=? "
            "WHERE task_id=? AND revision=?",
            (row.plan_revision_id, row.command_id, row.task_id, expected_current_revision),
        )
        if updated.rowcount != 1:
            raise IntegrityFailure("Task current-plan authority changed during guarded mutation")


class TaskRelationshipRepository:
    _INSERT_SQL = {
        "sr": "INSERT INTO task_sr_links(link_id,task_id,service_request_id,active,opened_command_id,closed_command_id) VALUES (?,?,?,1,?,NULL)",
        "rfc": "INSERT INTO task_rfc_links(link_id,task_id,rfc_id,active,opened_command_id,closed_command_id) VALUES (?,?,?,1,?,NULL)",
        "device": "INSERT INTO task_device_links(link_id,task_id,device_reference_id,active,opened_command_id,closed_command_id) VALUES (?,?,?,1,?,NULL)",
    }

    @staticmethod
    def link(uow: UnitOfWork, row: TaskRelationshipRecord) -> None:
        try:
            sql = TaskRelationshipRepository._INSERT_SQL[row.relationship_kind]
        except KeyError as exc:
            raise ValidationError("unsupported Task relationship kind") from exc
        uow.connection.execute(
            sql,
            (row.relationship_id, row.task_id, row.related_id, row.opened_command_id),
        )
