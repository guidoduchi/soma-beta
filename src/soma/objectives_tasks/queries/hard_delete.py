from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Protocol

from soma.foundation.errors import IntegrityFailure, SomaError, ValidationError
from soma.foundation.identifiers import require_uuid4
from soma.foundation.persistence.connections import ConnectionFactory
from soma.foundation.persistence.uow import ReadSnapshot, UnitOfWork
from soma.foundation.strict_json import loads_canonical_json, sha256_canonical_json

from ..audit_registry import build_objectives_tasks_audit_registry
from ..repositories.tasks import TaskNoStatus, TaskRecord, TaskRepository, WfmTaskRepository

Reader = ReadSnapshot | UnitOfWork
_AUDIT_REGISTRY = build_objectives_tasks_audit_registry()
_MAX_CREATION_AUDIT_REFS = 64
_MAX_LOCAL_CREATION_RELATIONSHIP_REFS = 62


class InventoryTaskDependencyProvider(Protocol):
    def classify_task_hard_delete_dependency(self, reader: Reader, task_id: str) -> str: ...


@dataclass(frozen=True, slots=True)
class TaskHardDeleteBlocker:
    code: str
    source: str
    status: str = "BLOCKED"


@dataclass(frozen=True, slots=True)
class TaskHardDeleteDraftRows:
    plan_revision_id: str | None
    lock_projection_present: bool
    sr_link_ids: tuple[str, ...]
    rfc_link_ids: tuple[str, ...]
    device_link_ids: tuple[str, ...]
    wfm_assignment_event_id: str | None


@dataclass(frozen=True, slots=True)
class TaskHardDeletePreview:
    status: str
    task_id: str
    task_kind: str
    task_no: str | None
    task_revision: int
    eligibility_fingerprint: str
    blockers: tuple[TaskHardDeleteBlocker, ...]
    draft_rows: TaskHardDeleteDraftRows
    inventory_status: str
    inventory_freshness_token: str

    @property
    def eligible(self) -> bool:
        return self.status == "ELIGIBLE"

    def to_response(self) -> dict[str, object]:
        """Return the closed public HardDeletePreviewV1 transport shape."""
        return {
            "eligible": self.eligible,
            "fingerprint": self.eligibility_fingerprint,
            "blockers": [blocker.code for blocker in self.blockers],
        }


@dataclass(frozen=True, slots=True)
class _CreationAuditEvidence:
    status: str
    plan_revision_id: str | None = None
    relationship_ids: frozenset[str] = frozenset()
    wfm_assignment_event_id: str | None = None


class TaskHardDeleteQueryService:
    """Pure LLD-05 hard-delete eligibility shared by preview and writer revalidation."""

    def __init__(
        self,
        connection_factory: ConnectionFactory,
        inventory_dependency_provider: InventoryTaskDependencyProvider,
    ) -> None:
        self._factory = connection_factory
        self._inventory = inventory_dependency_provider

    @staticmethod
    def load_task(reader: Reader, task_id: str) -> TaskRecord:
        task = TaskRepository.get(reader.connection, task_id)
        if task is None:
            raise SomaError("TASK_NOT_FOUND", "Task does not exist")
        return task

    @staticmethod
    def _exists(connection, sql: str, task_id: str) -> bool:
        return connection.execute(sql, (task_id,)).fetchone() is not None

    @staticmethod
    def _allowed_draft_links(
        connection,
        *,
        table: str,
        id_column: str,
        task: TaskRecord,
    ) -> tuple[tuple[str, ...], bool]:
        rows = connection.execute(
            f"SELECT {id_column},active,opened_command_id,closed_command_id FROM {table} "
            "WHERE task_id=? ORDER BY " + id_column,
            (task.task_id,),
        ).fetchall()
        if task.task_kind == "wfm":
            return (), bool(rows)
        allowed: list[str] = []
        history_present = False
        for row in rows:
            if int(row[1]) != 1 or str(row[2]) != task.created_command_id or row[3] is not None:
                history_present = True
                continue
            allowed.append(str(row[0]))
        return tuple(allowed), history_present

    @staticmethod
    def _creation_receipt_status(connection, task: TaskRecord) -> str:
        row = connection.execute(
            "SELECT command_type,target_type,target_id FROM command_receipts WHERE command_id=?",
            (task.created_command_id,),
        ).fetchone()
        expected = "RegisterManualWfmTask" if task.task_kind == "wfm" else "CreateLocalTask"
        if (
            row is None
            or str(row[0]) != expected
            or str(row[1]) != "task"
            or (row[2] is not None and str(row[2]) != task.task_id)
        ):
            return "INDETERMINATE"
        return "CLEAR"

    @staticmethod
    def _creation_audit_evidence(connection, task: TaskRecord) -> _CreationAuditEvidence:
        expected_action = "task.wfm_registered" if task.task_kind == "wfm" else "task.created"
        rows = connection.execute(
            "SELECT audit_event_id,action_type,action_version,command_id,target_type,target_id,"
            "payload_schema,payload_version,payload_json "
            "FROM audit_events WHERE target_type='task' AND target_id=? ORDER BY audit_event_id",
            (task.task_id,),
        ).fetchall()
        if not rows:
            return _CreationAuditEvidence("INDETERMINATE")
        creation = [
            row
            for row in rows
            if str(row[1]) == expected_action and str(row[3]) == task.created_command_id
        ]
        if len(creation) != 1:
            return _CreationAuditEvidence("INDETERMINATE")
        if len(rows) != 1:
            return _CreationAuditEvidence("BLOCKED")

        row = creation[0]
        try:
            audit_event_id = require_uuid4(str(row[0]))
            action_version = int(row[2])
            contract = _AUDIT_REGISTRY.resolve(str(row[1]), action_version)
            if (
                str(row[4]) != "task"
                or str(row[5]) != task.task_id
                or str(row[6]) != contract.payload_schema
                or int(row[7]) != contract.payload_version
                or not isinstance(row[8], str)
            ):
                return _CreationAuditEvidence("INDETERMINATE")
            payload = loads_canonical_json(
                row[8],
                max_bytes=contract.payload_contract.max_utf8_bytes,
                max_depth=contract.payload_contract.max_depth,
                max_collection_items=contract.payload_contract.max_collection_items,
            )
            validated = contract.payload_contract.validate(payload)
            if contract.sensitivity_validator is not None:
                contract.sensitivity_validator(validated)
        except (SomaError, ValidationError, TypeError, ValueError):
            return _CreationAuditEvidence("INDETERMINATE")

        if validated.get("task_id") != task.task_id:
            return _CreationAuditEvidence("INDETERMINATE")
        plan_revision_id = validated.get("task_plan_revision_id")
        if plan_revision_id is not None:
            if not isinstance(plan_revision_id, str):
                return _CreationAuditEvidence("INDETERMINATE")
            try:
                plan_revision_id = require_uuid4(plan_revision_id)
            except ValidationError:
                return _CreationAuditEvidence("INDETERMINATE")

        ref_rows = connection.execute(
            "SELECT ordinal,result_type,result_id FROM audit_event_results "
            "WHERE audit_event_id=? ORDER BY ordinal LIMIT ?",
            (audit_event_id, _MAX_CREATION_AUDIT_REFS + 1),
        ).fetchall()
        if len(ref_rows) > _MAX_CREATION_AUDIT_REFS:
            return _CreationAuditEvidence("INDETERMINATE")
        try:
            ordinals = [int(ref[0]) for ref in ref_rows]
            if ordinals != list(range(len(ref_rows))):
                return _CreationAuditEvidence("INDETERMINATE")
            pairs = [(str(ref[1]), require_uuid4(str(ref[2]))) for ref in ref_rows]
        except (TypeError, ValueError, ValidationError):
            return _CreationAuditEvidence("INDETERMINATE")
        if pairs != sorted(pairs):
            return _CreationAuditEvidence("INDETERMINATE")

        task_refs = [result_id for result_type, result_id in pairs if result_type == "task"]
        if task_refs != [task.task_id]:
            return _CreationAuditEvidence("INDETERMINATE")

        if task.task_kind == "local":
            if any(result_type not in {"task", "task_plan", "task_relationship"} for result_type, _ in pairs):
                return _CreationAuditEvidence("INDETERMINATE")
            plan_refs = [result_id for result_type, result_id in pairs if result_type == "task_plan"]
            expected_plan_refs = [] if plan_revision_id is None else [plan_revision_id]
            if plan_refs != expected_plan_refs:
                return _CreationAuditEvidence("INDETERMINATE")
            relationship_ids = frozenset(
                result_id for result_type, result_id in pairs if result_type == "task_relationship"
            )
            if len(relationship_ids) > _MAX_LOCAL_CREATION_RELATIONSHIP_REFS:
                return _CreationAuditEvidence("INDETERMINATE")
            return _CreationAuditEvidence(
                "CLEAR",
                plan_revision_id=plan_revision_id,
                relationship_ids=relationship_ids,
            )

        if any(result_type not in {"task", "wfm_assignment"} for result_type, _ in pairs):
            return _CreationAuditEvidence("INDETERMINATE")
        assignment_refs = [result_id for result_type, result_id in pairs if result_type == "wfm_assignment"]
        if len(assignment_refs) != 1:
            return _CreationAuditEvidence("INDETERMINATE")
        return _CreationAuditEvidence(
            "CLEAR",
            plan_revision_id=plan_revision_id,
            wfm_assignment_event_id=assignment_refs[0],
        )

    @staticmethod
    def _plan_state(connection, task: TaskRecord) -> tuple[str | None, str]:
        rows = connection.execute(
            "SELECT plan_revision_id,origin,source_observation_id,predecessor_plan_revision_id,command_id "
            "FROM task_plan_revisions WHERE task_id=? ORDER BY plan_revision_id",
            (task.task_id,),
        ).fetchall()
        current = connection.execute(
            "SELECT plan_revision_id,revision,last_command_id FROM task_plan_current WHERE task_id=?",
            (task.task_id,),
        ).fetchone()
        if not rows:
            return (None, "CLEAR") if current is None else (None, "INDETERMINATE")
        if len(rows) != 1 or current is None:
            return None, "BLOCKED"
        row = rows[0]
        plan_id = str(row[0])
        allowed_origins = {"manual"} if task.task_kind == "wfm" else {"manual", "objective_initialization"}
        if (
            str(row[1]) not in allowed_origins
            or row[2] is not None
            or row[3] is not None
            or str(row[4]) != task.created_command_id
            or str(current[0]) != plan_id
            or int(current[1]) != 1
            or str(current[2]) != task.created_command_id
        ):
            return None, "BLOCKED"
        return plan_id, "CLEAR"

    @staticmethod
    def _lock_projection_state(connection, task_id: str) -> tuple[bool, str]:
        rows = connection.execute(
            "SELECT explicit_plan_lock,explicit_membership_lock,revision,last_event_id "
            "FROM task_lock_projection WHERE task_id=?",
            (task_id,),
        ).fetchall()
        if not rows:
            return False, "CLEAR"
        if len(rows) != 1:
            return False, "INDETERMINATE"
        row = rows[0]
        if int(row[0]) != 0 or int(row[1]) != 0 or int(row[2]) != 1 or row[3] is not None:
            return True, "BLOCKED"
        return True, "CLEAR"

    @staticmethod
    def _wfm_state(connection, task: TaskRecord) -> tuple[str | None, str | None, str]:
        if task.task_kind != "wfm":
            return None, None, "CLEAR"
        identity = WfmTaskRepository.get_identity(connection, task.task_id)
        if identity is None:
            return None, None, "INDETERMINATE"
        try:
            status = WfmTaskRepository.task_no_status(connection, identity.task_no)
        except IntegrityFailure:
            return identity.task_no, None, "INDETERMINATE"
        if status is not TaskNoStatus.ACTIVE:
            return identity.task_no, None, "INDETERMINATE"
        rows = connection.execute(
            "SELECT assignment_event_id,prior_rfc_id,new_rfc_id,reason_code,review_risk,command_id "
            "FROM wfm_rfc_assignment_events WHERE task_id=? ORDER BY assignment_event_id",
            (task.task_id,),
        ).fetchall()
        if len(rows) != 1:
            return identity.task_no, None, "BLOCKED"
        row = rows[0]
        if (
            row[1] is not None
            or str(row[2]) != identity.current_rfc_id
            or str(row[3]) != "manual_registration"
            or str(row[4]) != "low"
            or str(row[5]) != identity.created_command_id
            or identity.created_command_id != task.created_command_id
            or identity.assignment_revision != 1
        ):
            return identity.task_no, None, "BLOCKED"
        return identity.task_no, str(row[0]), "CLEAR"

    def evaluate(self, reader: Reader, *, task: TaskRecord) -> TaskHardDeletePreview:
        connection = reader.connection
        blockers: list[TaskHardDeleteBlocker] = []

        def add(code: str, status: str = "BLOCKED", source: str = "local") -> None:
            if status != "CLEAR":
                blockers.append(TaskHardDeleteBlocker(code, source, status))

        expected_origin = "wfm_manual" if task.task_kind == "wfm" else "manual"
        add("TASK_CREATION_NOT_DRAFT", "BLOCKED" if task.creation_origin != expected_origin else "CLEAR")
        add("TASK_REVISION_NOT_INITIAL", "BLOCKED" if task.revision != 1 else "CLEAR")
        add("TASK_CREATION_RECEIPT_INVALID", self._creation_receipt_status(connection, task))

        creation_audit = self._creation_audit_evidence(connection, task)
        creation_audit_status = creation_audit.status

        task_no, assignment_event_id, wfm_status = self._wfm_state(connection, task)
        plan_revision_id, plan_status = self._plan_state(connection, task)

        lock_projection_present, lock_status = self._lock_projection_state(connection, task.task_id)

        sr_links, sr_history = self._allowed_draft_links(
            connection, table="task_sr_links", id_column="link_id", task=task
        )
        rfc_links, rfc_history = self._allowed_draft_links(
            connection, table="task_rfc_links", id_column="link_id", task=task
        )
        device_links, device_history = self._allowed_draft_links(
            connection, table="task_device_links", id_column="link_id", task=task
        )
        relationship_history = sr_history or rfc_history or device_history

        if (
            creation_audit_status == "CLEAR"
            and plan_status == "CLEAR"
            and creation_audit.plan_revision_id != plan_revision_id
        ):
            creation_audit_status = "INDETERMINATE"
        if (
            creation_audit_status == "CLEAR"
            and task.task_kind == "wfm"
            and wfm_status == "CLEAR"
            and creation_audit.wfm_assignment_event_id != assignment_event_id
        ):
            creation_audit_status = "INDETERMINATE"
        if (
            creation_audit_status == "CLEAR"
            and task.task_kind == "local"
            and not relationship_history
            and creation_audit.relationship_ids != frozenset((*sr_links, *rfc_links, *device_links))
        ):
            creation_audit_status = "INDETERMINATE"

        add("WFM_IDENTITY_OR_ASSIGNMENT_HISTORY_PRESENT", wfm_status)
        add("TASK_AUDIT_HISTORY_PRESENT", creation_audit_status)
        add("TASK_PLAN_HISTORY_PRESENT", plan_status)
        add("TASK_LOCK_HISTORY_PRESENT", lock_status)
        add("TASK_RELATIONSHIP_HISTORY_PRESENT", "BLOCKED" if relationship_history else "CLEAR")

        history_checks = (
            ("WFM_SOURCE_HISTORY_PRESENT", "SELECT 1 FROM wfm_source_projection_cache WHERE task_id=? LIMIT 1"),
            ("TASK_EXECUTION_HISTORY_PRESENT", "SELECT 1 FROM task_execution_events WHERE task_id=? LIMIT 1"),
            ("TASK_OUTCOME_HISTORY_PRESENT", "SELECT 1 FROM task_outcome_events WHERE task_id=? LIMIT 1"),
            ("TASK_LOCK_HISTORY_PRESENT", "SELECT 1 FROM task_lock_events WHERE task_id=? LIMIT 1"),
            ("TASK_OBJECTIVE_HISTORY_PRESENT", "SELECT 1 FROM objective_membership_events WHERE task_id=? LIMIT 1"),
            ("TASK_RETRY_HISTORY_PRESENT", "SELECT 1 FROM task_retry_relations WHERE predecessor_task_id=? OR successor_task_id=? LIMIT 1"),
            ("TASK_ACTIVITY_HISTORY_PRESENT", "SELECT 1 FROM task_activity_lineage_events WHERE task_id=? LIMIT 1"),
            ("TASK_COUNT_HISTORY_PRESENT", "SELECT 1 FROM task_operational_count_events WHERE task_id=? LIMIT 1"),
            ("TASK_GROUPING_HISTORY_PRESENT", "SELECT 1 FROM regroup_proposal_task_changes WHERE task_id=? LIMIT 1"),
            ("TASK_HISTORICAL_PROPOSAL_PRESENT", "SELECT 1 FROM historical_objective_proposals WHERE task_id=? LIMIT 1"),
            ("TASK_SOURCE_TERMINAL_REVIEW_PRESENT", "SELECT 1 FROM wfm_source_terminal_reviews WHERE task_id=? LIMIT 1"),
        )
        for code, sql in history_checks:
            if code == "TASK_RETRY_HISTORY_PRESENT":
                present = connection.execute(sql, (task.task_id, task.task_id)).fetchone() is not None
            else:
                present = self._exists(connection, sql, task.task_id)
            add(code, "BLOCKED" if present else "CLEAR")

        projection_checks = (
            "task_execution_projection",
            "task_outcome_current",
            "task_activity_lineage_current",
            "task_operational_count_current",
            "objective_task_membership_current",
        )
        for table in projection_checks:
            if self._exists(connection, f"SELECT 1 FROM {table} WHERE task_id=? LIMIT 1", task.task_id):
                add("TASK_CURRENT_PROJECTION_WITHOUT_ALLOWED_HISTORY", "INDETERMINATE")
                break

        try:
            inventory_status = self._inventory.classify_task_hard_delete_dependency(reader, task.task_id)
            if inventory_status not in {"CLEAR", "BLOCKED", "INDETERMINATE"}:
                inventory_status = "INDETERMINATE"
        except Exception:
            inventory_status = "INDETERMINATE"
        inventory_token = sha256_canonical_json(
            {
                "schema": "SOMA_TASK_HARD_DELETE_INVENTORY_CLASSIFICATION_V1",
                "task_id": task.task_id,
                "status": inventory_status,
            }
        )
        if inventory_status == "BLOCKED":
            add("TASK_INVENTORY_DEPENDENCY_PRESENT", "BLOCKED", "inventory")
        elif inventory_status == "INDETERMINATE":
            add("TASK_INVENTORY_DEPENDENCY_INDETERMINATE", "INDETERMINATE", "inventory")

        draft_rows = TaskHardDeleteDraftRows(
            plan_revision_id=plan_revision_id,
            lock_projection_present=lock_projection_present,
            sr_link_ids=sr_links,
            rfc_link_ids=rfc_links,
            device_link_ids=device_links,
            wfm_assignment_event_id=assignment_event_id,
        )
        blocker_rows = tuple(sorted(blockers, key=lambda item: (item.status, item.source, item.code)))
        if any(item.status == "INDETERMINATE" for item in blocker_rows):
            status = "INDETERMINATE"
        elif blocker_rows:
            status = "BLOCKED"
        else:
            status = "ELIGIBLE"
        fingerprint = sha256_canonical_json(
            {
                "schema": "SOMA_TASK_HARD_DELETE_ELIGIBILITY_V1",
                "task": {
                    "task_id": task.task_id,
                    "task_kind": task.task_kind,
                    "task_no": task_no,
                    "creation_origin": task.creation_origin,
                    "revision": task.revision,
                    "created_command_id": task.created_command_id,
                },
                "status": status,
                "blockers": [asdict(item) for item in blocker_rows],
                "draft_rows": asdict(draft_rows),
                "inventory": {"status": inventory_status, "freshness_token": inventory_token},
            }
        )
        return TaskHardDeletePreview(
            status=status,
            task_id=task.task_id,
            task_kind=task.task_kind,
            task_no=task_no,
            task_revision=task.revision,
            eligibility_fingerprint=fingerprint,
            blockers=blocker_rows,
            draft_rows=draft_rows,
            inventory_status=inventory_status,
            inventory_freshness_token=inventory_token,
        )

    def preview(self, *, task_id: str, base_revision: int) -> TaskHardDeletePreview:
        canonical_id = require_uuid4(task_id)
        if type(base_revision) is not int or base_revision <= 0:
            raise ValidationError("base_revision must be a positive integer")
        with ReadSnapshot(self._factory) as snapshot:
            task = self.load_task(snapshot, canonical_id)
            if task.revision != base_revision:
                raise SomaError("HARD_DELETE_BLOCKED", "Task revision changed; refresh the Task before preview")
            return self.evaluate(snapshot, task=task)
