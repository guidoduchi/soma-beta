from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass, field

import pytest

from soma.foundation.errors import SomaError
from soma.foundation.identifiers import new_uuid4
from soma.foundation.persistence.uow import ReadSnapshot, UnitOfWork
from soma.objectives_tasks import (
    AcceptedTaskSchedule,
    TaskHardDeleteQueryService,
    TaskHardDeleteService,
    TaskNoStatus,
    TaskPlanningService,
    WfmTaskRepository,
)
from soma.objectives_tasks.audit_registry import build_objectives_tasks_audit_registry
from soma.tickets.device_references import DeviceReferenceService
from soma.tickets.rfcs import RfcService


@dataclass
class _InventoryProvider:
    status: object = "CLEAR"
    calls: list = field(default_factory=list)

    def classify_task_hard_delete_dependency(self, reader, task_id):
        self.calls.append((reader, task_id))
        assert reader.connection.in_transaction
        if isinstance(self.status, BaseException):
            raise self.status
        return self.status


@pytest.fixture
def deletion(initialized_database):
    database_path, factory_for_path = initialized_database
    factory = factory_for_path(database_path)
    inventory = _InventoryProvider()
    planning = TaskPlanningService(factory)
    queries = TaskHardDeleteQueryService(factory, inventory)
    service = TaskHardDeleteService(factory, inventory)
    return factory, inventory, planning, queries, service


def _create_rfc(factory, rfc_no: str = "NC00000000000001") -> str:
    return RfcService(factory).create_or_adopt_identity(
        command_id=new_uuid4(),
        rfc_no=rfc_no,
        creation_context="provisional",
    ).rfc_id


def _register_wfm(planning, rfc_id: str, *, task_no: str = "TK00000000000001", schedule=None):
    command_id = new_uuid4()
    result = planning.register_manual_wfm_task(
        command_id=command_id,
        task_no=task_no,
        rfc_id=rfc_id,
        schedule=schedule,
    )
    return command_id, result


def _insert_receipt(
    uow: UnitOfWork,
    *,
    command_id: str,
    command_type: str,
    target_type: str = "task",
    target_id: str | None = None,
) -> None:
    uow.connection.execute(
        "INSERT INTO command_receipts("
        "command_id,command_type,request_hash,target_type,target_id,committed_at_utc,result_type,result_id"
        ") VALUES (?,?,?,?,?,0,NULL,NULL)",
        (command_id, command_type, "0" * 64, target_type, target_id),
    )


def _hard_delete_args(task_id: str, preview, *, command_id: str | None = None) -> dict[str, object]:
    return {
        "command_id": command_id or new_uuid4(),
        "task_id": task_id,
        "base_revision": preview.task_revision,
        "eligibility_fingerprint": preview.eligibility_fingerprint,
        "confirmation_context_id": "lld05-t036",
    }


def _blocker_codes(preview) -> set[str]:
    return {blocker.code for blocker in preview.blockers}


def _assert_no_delete_artifacts(factory, *, command_id: str, task_id: str, task_no: str) -> None:
    with ReadSnapshot(factory) as snapshot:
        assert snapshot.connection.execute(
            "SELECT 1 FROM tasks WHERE task_id=?", (task_id,)
        ).fetchone() is not None
        assert snapshot.connection.execute(
            "SELECT 1 FROM wfm_task_identities WHERE task_id=? AND task_no=?",
            (task_id, task_no),
        ).fetchone() is not None
        assert snapshot.connection.execute(
            "SELECT count(*) FROM wfm_rfc_assignment_events WHERE task_id=?",
            (task_id,),
        ).fetchone() == (1,)
        assert snapshot.connection.execute(
            "SELECT 1 FROM wfm_task_no_retirements WHERE task_no=?", (task_no,)
        ).fetchone() is None
        assert snapshot.connection.execute(
            "SELECT 1 FROM audit_events WHERE command_id=?", (command_id,)
        ).fetchone() is None
        assert snapshot.connection.execute(
            "SELECT 1 FROM command_receipts WHERE command_id=?", (command_id,)
        ).fetchone() is None
        assert snapshot.connection.execute(
            "SELECT 1 FROM command_receipt_results WHERE command_id=?", (command_id,)
        ).fetchone() is None


def _canonical(value: dict[str, object]) -> str:
    return json.dumps(value, ensure_ascii=False, allow_nan=False, separators=(",", ":"), sort_keys=True)


def _insert_raw_manual_wfm(
    factory,
    rfc_id: str,
    *,
    action_version: int = 1,
    payload_schema: str = "TaskAuditV1",
    payload_version: int = 1,
    payload_mutator=None,
    canonical_payload: bool = True,
) -> tuple[str, str, str]:
    command_id = new_uuid4()
    task_id = new_uuid4()
    task_no = "TK00000000000999"
    assignment_event_id = new_uuid4()
    payload = {
        "task_id": task_id,
        "task_kind": "wfm",
        "creation_origin": "wfm_manual",
        "resulting_revision": 1,
        "task_plan_revision_id": None,
        "reason_category": None,
    }
    if payload_mutator is not None:
        payload_mutator(payload)
    payload_json = _canonical(payload) if canonical_payload else json.dumps(payload, sort_keys=True)
    with UnitOfWork(factory) as uow:
        _insert_receipt(
            uow,
            command_id=command_id,
            command_type="RegisterManualWfmTask",
            target_id=None,
        )
        uow.connection.execute(
            "INSERT INTO tasks(task_id,task_kind,local_task_name,creation_origin,revision,created_at_utc,created_command_id) "
            "VALUES (?,'wfm',NULL,'wfm_manual',1,0,?)",
            (task_id, command_id),
        )
        uow.connection.execute(
            "INSERT INTO wfm_task_identities(task_id,task_no,current_rfc_id,assignment_revision,created_command_id) "
            "VALUES (?,?,?,1,?)",
            (task_id, task_no, rfc_id, command_id),
        )
        uow.connection.execute(
            "INSERT INTO wfm_rfc_assignment_events("
            "assignment_event_id,task_id,prior_rfc_id,new_rfc_id,reason_code,review_risk,recorded_at_utc,command_id"
            ") VALUES (?,?,NULL,?,'manual_registration','low',0,?)",
            (assignment_event_id, task_id, rfc_id, command_id),
        )
        uow.connection.execute(
            "INSERT INTO audit_events("
            "audit_event_id,action_type,action_version,recorded_at_utc,actor_kind,target_type,target_id,"
            "command_id,payload_schema,payload_version,payload_json"
            ") VALUES (?,'task.wfm_registered',?,0,'local_user','task',?,?,?,?,?)",
            (
                new_uuid4(),
                action_version,
                task_id,
                command_id,
                payload_schema,
                payload_version,
                payload_json,
            ),
        )
    return task_id, task_no, command_id


def test_task_creation_audit_registry_contains_both_certified_creation_actions() -> None:
    registry = build_objectives_tasks_audit_registry()
    local = registry.resolve("task.created", 1)
    wfm = registry.resolve("task.wfm_registered", 1)
    assert (local.payload_schema, local.payload_version) == ("TaskAuditV1", 1)
    assert (wfm.payload_schema, wfm.payload_version) == ("TaskAuditV1", 1)


def test_manual_wfm_hard_delete_retires_identity_before_delete_and_replays_without_owner_reads(
    deletion, monkeypatch
) -> None:
    factory, inventory, planning, queries, service = deletion
    rfc_id = _create_rfc(factory)
    task_no = "TK00000000000001"
    _, registered = _register_wfm(planning, rfc_id, task_no=task_no)
    preview = queries.preview(task_id=registered.task_id, base_revision=1)
    assert preview.eligible
    assert preview.status == "ELIGIBLE"
    assert preview.blockers == ()
    assert set(preview.to_response()) == {"eligible", "fingerprint", "blockers"}
    assert preview.to_response() == {
        "eligible": True,
        "fingerprint": preview.eligibility_fingerprint,
        "blockers": [],
    }
    assert len(inventory.calls) == 1
    assert isinstance(inventory.calls[0][0], ReadSnapshot)

    with UnitOfWork(factory) as uow:
        uow.connection.execute(
            "CREATE TRIGGER test_task_delete_requires_retirement_and_audit "
            "BEFORE DELETE ON wfm_task_identities BEGIN "
            "SELECT CASE WHEN NOT EXISTS("
            "SELECT 1 FROM wfm_task_no_retirements r "
            "WHERE r.task_no=OLD.task_no AND r.retired_task_id=OLD.task_id"
            ") THEN RAISE(ABORT,'retirement must precede identity delete') END; "
            "SELECT CASE WHEN NOT EXISTS("
            "SELECT 1 FROM audit_events a JOIN audit_event_results ar ON ar.audit_event_id=a.audit_event_id "
            "WHERE a.action_type='task.hard_deleted' AND a.target_id=OLD.task_id "
            "AND ar.result_type='hard_delete_evidence' AND ar.result_id=a.audit_event_id"
            ") THEN RAISE(ABORT,'audit must precede identity delete') END; "
            "END"
        )

    delete_command = new_uuid4()
    result = service.hard_delete(**_hard_delete_args(registered.task_id, preview, command_id=delete_command))
    assert result.outcome == "APPLIED"
    assert result.revision == 1
    assert not result.replayed
    assert len(result.result_refs) == 1
    evidence_id = result.result_refs[0].result_id
    assert result.result_refs[0].result_type == "hard_delete_evidence"

    with ReadSnapshot(factory) as snapshot:
        assert snapshot.connection.execute(
            "SELECT 1 FROM tasks WHERE task_id=?", (registered.task_id,)
        ).fetchone() is None
        assert snapshot.connection.execute(
            "SELECT 1 FROM wfm_task_identities WHERE task_id=?", (registered.task_id,)
        ).fetchone() is None
        assert snapshot.connection.execute(
            "SELECT 1 FROM wfm_rfc_assignment_events WHERE task_id=?", (registered.task_id,)
        ).fetchone() is None
        retirement = snapshot.connection.execute(
            "SELECT retirement_id,retired_task_id,hard_delete_command_id "
            "FROM wfm_task_no_retirements WHERE task_no=?",
            (task_no,),
        ).fetchone()
        assert retirement is not None
        retirement_id = str(retirement[0])
        assert tuple(retirement[1:]) == (registered.task_id, delete_command)
        assert WfmTaskRepository.task_no_status(snapshot.connection, task_no) is TaskNoStatus.RETIRED

        audit = snapshot.connection.execute(
            "SELECT audit_event_id,action_version,target_type,target_id,payload_schema,payload_version,payload_json "
            "FROM audit_events WHERE command_id=?",
            (delete_command,),
        ).fetchone()
        assert tuple(audit[:6]) == (
            evidence_id,
            1,
            "task",
            registered.task_id,
            "HardDeleteAuditV1",
            1,
        )
        assert json.loads(str(audit[6])) == {
            "confirmation_context_id": "lld05-t036",
            "eligibility_fingerprint": preview.eligibility_fingerprint,
            "result": "deleted",
            "retained_related_ids": [retirement_id],
            "reviewed_revision": 1,
            "target_id": registered.task_id,
            "target_type": "task",
        }
        assert task_no not in str(audit[6])
        assert snapshot.connection.execute(
            "SELECT result_type,result_id FROM audit_event_results WHERE audit_event_id=?",
            (evidence_id,),
        ).fetchone() == ("hard_delete_evidence", evidence_id)
        exact = snapshot.connection.execute(
            "SELECT response_schema,response_version,response_json FROM command_receipt_results WHERE command_id=?",
            (delete_command,),
        ).fetchone()
        assert tuple(exact[:2]) == ("TaskMutationResultV1", 1)
        assert json.loads(str(exact[2])) == {
            "outcome": "APPLIED",
            "result_refs": [{"id": evidence_id, "type": "hard_delete_evidence"}],
            "revision": 1,
            "task_id": registered.task_id,
        }

    inventory.status = RuntimeError("must not be called during replay")

    def fail_owner_read(*args, **kwargs):
        pytest.fail("replay must occur before now-missing Task owner state is read")

    monkeypatch.setattr(service._queries, "load_task", fail_owner_read)
    replay = service.hard_delete(**_hard_delete_args(registered.task_id, preview, command_id=delete_command))
    assert replay.replayed
    assert replay.outcome == result.outcome
    assert replay.task_id == result.task_id
    assert replay.revision == result.revision
    assert replay.result_refs == result.result_refs
    assert len(inventory.calls) == 2

    rejected_command = new_uuid4()
    with pytest.raises(SomaError, match="WFM_TASK_NO_RETIRED"):
        planning.register_manual_wfm_task(
            command_id=rejected_command,
            task_no=task_no,
            rfc_id=rfc_id,
        )
    with ReadSnapshot(factory) as snapshot:
        assert snapshot.connection.execute(
            "SELECT 1 FROM command_receipts WHERE command_id=?", (rejected_command,)
        ).fetchone() is None

    bypass_command = new_uuid4()
    bypass_task = new_uuid4()
    with pytest.raises(sqlite3.IntegrityError):
        with UnitOfWork(factory) as uow:
            _insert_receipt(
                uow,
                command_id=bypass_command,
                command_type="CreateOrAdoptWfmFromSource",
                target_id=bypass_task,
            )
            uow.connection.execute(
                "INSERT INTO tasks(task_id,task_kind,local_task_name,creation_origin,revision,created_at_utc,created_command_id) "
                "VALUES (?,'wfm',NULL,'wfm_source_adoption',1,0,?)",
                (bypass_task, bypass_command),
            )
            uow.connection.execute(
                "INSERT INTO wfm_task_identities(task_id,task_no,current_rfc_id,assignment_revision,created_command_id) "
                "VALUES (?,?,?,1,?)",
                (bypass_task, task_no, rfc_id, bypass_command),
            )


@pytest.mark.parametrize(
    "mutation",
    [
        "action_version",
        "payload_schema",
        "payload_version",
        "noncanonical_payload",
        "wrong_task_id",
        "wrong_plan_id",
    ],
)
def test_creation_audit_provenance_fails_closed_when_exact_contract_is_not_proven(deletion, mutation) -> None:
    factory, _, _, queries, _ = deletion
    rfc_id = _create_rfc(factory)

    kwargs: dict[str, object] = {}
    if mutation == "action_version":
        kwargs["action_version"] = 2
    elif mutation == "payload_schema":
        kwargs["payload_schema"] = "ForgedTaskAuditV1"
    elif mutation == "payload_version":
        kwargs["payload_version"] = 2
    elif mutation == "noncanonical_payload":
        kwargs["canonical_payload"] = False
    elif mutation == "wrong_task_id":
        kwargs["payload_mutator"] = lambda payload: payload.__setitem__("task_id", new_uuid4())
    elif mutation == "wrong_plan_id":
        kwargs["payload_mutator"] = lambda payload: payload.__setitem__("task_plan_revision_id", new_uuid4())

    task_id, _, _ = _insert_raw_manual_wfm(factory, rfc_id, **kwargs)
    preview = queries.preview(task_id=task_id, base_revision=1)
    assert preview.status == "INDETERMINATE"
    assert "TASK_AUDIT_HISTORY_PRESENT" in _blocker_codes(preview)


@pytest.mark.parametrize(
    "provider_value,expected_status,expected_code",
    [
        ("BLOCKED", "BLOCKED", "TASK_INVENTORY_DEPENDENCY_PRESENT"),
        ("INDETERMINATE", "INDETERMINATE", "TASK_INVENTORY_DEPENDENCY_INDETERMINATE"),
        ("unknown", "INDETERMINATE", "TASK_INVENTORY_DEPENDENCY_INDETERMINATE"),
        (None, "INDETERMINATE", "TASK_INVENTORY_DEPENDENCY_INDETERMINATE"),
        (RuntimeError("private provider detail"), "INDETERMINATE", "TASK_INVENTORY_DEPENDENCY_INDETERMINATE"),
    ],
)
def test_inventory_dependency_is_fail_closed_in_preview_and_writer(
    deletion, provider_value, expected_status, expected_code
) -> None:
    factory, inventory, planning, queries, service = deletion
    rfc_id = _create_rfc(factory)
    _, registered = _register_wfm(planning, rfc_id)
    reviewed = queries.preview(task_id=registered.task_id, base_revision=1)
    assert reviewed.eligible

    inventory.status = provider_value
    current = queries.preview(task_id=registered.task_id, base_revision=1)
    assert current.status == expected_status
    assert expected_code in _blocker_codes(current)
    assert current.eligibility_fingerprint != reviewed.eligibility_fingerprint

    delete_command = new_uuid4()
    expected_error = "HARD_DELETE_BLOCKED" if expected_status == "BLOCKED" else "HARD_DELETE_INDETERMINATE"
    with pytest.raises(SomaError, match=expected_error):
        service.hard_delete(**_hard_delete_args(registered.task_id, reviewed, command_id=delete_command))
    _assert_no_delete_artifacts(
        factory,
        command_id=delete_command,
        task_id=registered.task_id,
        task_no="TK00000000000001",
    )


@pytest.mark.parametrize("stale_kind", ["revision", "fingerprint"])
def test_stale_base_revision_or_fingerprint_rejects_before_destructive_mutation(deletion, stale_kind) -> None:
    factory, _, planning, queries, service = deletion
    rfc_id = _create_rfc(factory)
    _, registered = _register_wfm(planning, rfc_id)
    reviewed = queries.preview(task_id=registered.task_id, base_revision=1)
    delete_command = new_uuid4()
    request = _hard_delete_args(registered.task_id, reviewed, command_id=delete_command)

    if stale_kind == "revision":
        with UnitOfWork(factory) as uow:
            uow.connection.execute(
                "UPDATE tasks SET revision=2 WHERE task_id=?",
                (registered.task_id,),
            )
    else:
        request["eligibility_fingerprint"] = "0" * 64

    with pytest.raises(SomaError, match="TASK_STALE"):
        service.hard_delete(**request)
    with ReadSnapshot(factory) as snapshot:
        assert snapshot.connection.execute(
            "SELECT 1 FROM command_receipts WHERE command_id=?", (delete_command,)
        ).fetchone() is None
        assert snapshot.connection.execute(
            "SELECT 1 FROM wfm_task_no_retirements WHERE task_no='TK00000000000001'"
        ).fetchone() is None


def test_second_wfm_assignment_event_permanently_blocks_narrow_delete_path(deletion) -> None:
    factory, _, planning, queries, service = deletion
    rfc_id = _create_rfc(factory)
    _, registered = _register_wfm(planning, rfc_id)
    reviewed = queries.preview(task_id=registered.task_id, base_revision=1)
    assert reviewed.eligible

    history_command = new_uuid4()
    with UnitOfWork(factory) as uow:
        _insert_receipt(
            uow,
            command_id=history_command,
            command_type="ReassignWfmParent",
            target_id=registered.task_id,
        )
        uow.connection.execute(
            "INSERT INTO wfm_rfc_assignment_events("
            "assignment_event_id,task_id,prior_rfc_id,new_rfc_id,reason_code,review_risk,recorded_at_utc,command_id"
            ") VALUES (?,?,?,?, 'reviewed_reassignment','high',1,?)",
            (new_uuid4(), registered.task_id, rfc_id, rfc_id, history_command),
        )

    current = queries.preview(task_id=registered.task_id, base_revision=1)
    assert not current.eligible
    assert "WFM_IDENTITY_OR_ASSIGNMENT_HISTORY_PRESENT" in _blocker_codes(current)
    delete_command = new_uuid4()
    with pytest.raises(SomaError, match="HARD_DELETE_BLOCKED"):
        service.hard_delete(**_hard_delete_args(registered.task_id, reviewed, command_id=delete_command))
    with ReadSnapshot(factory) as snapshot:
        assert snapshot.connection.execute(
            "SELECT count(*) FROM wfm_rfc_assignment_events WHERE task_id=?",
            (registered.task_id,),
        ).fetchone() == (2,)
        assert snapshot.connection.execute(
            "SELECT 1 FROM command_receipts WHERE command_id=?", (delete_command,)
        ).fetchone() is None


def test_accepted_wfm_source_projection_blocks_hard_delete(deletion) -> None:
    factory, _, planning, queries, service = deletion
    rfc_id = _create_rfc(factory)
    creation_command, registered = _register_wfm(planning, rfc_id)
    reviewed = queries.preview(task_id=registered.task_id, base_revision=1)
    with UnitOfWork(factory) as uow:
        uow.connection.execute(
            "INSERT INTO wfm_source_projection_cache("
            "task_id,provider_status_token,provider_lifecycle_class,source_plan_start_utc,source_plan_end_utc,"
            "accepted_source_observation_id,source_projection_revision,source_base_token,last_command_id"
            ") VALUES (?,?,'active',NULL,NULL,?,1,?,?)",
            (registered.task_id, "provider-active", "source-observation-1", "a" * 64, creation_command),
        )
    current = queries.preview(task_id=registered.task_id, base_revision=1)
    assert "WFM_SOURCE_HISTORY_PRESENT" in _blocker_codes(current)
    delete_command = new_uuid4()
    with pytest.raises(SomaError, match="HARD_DELETE_BLOCKED"):
        service.hard_delete(**_hard_delete_args(registered.task_id, reviewed, command_id=delete_command))
    with ReadSnapshot(factory) as snapshot:
        assert WfmTaskRepository.task_no_status(
            snapshot.connection, "TK00000000000001"
        ) is TaskNoStatus.ACTIVE


def test_only_exact_initial_manual_plan_is_removable_and_later_plan_history_blocks(deletion) -> None:
    factory, _, planning, queries, service = deletion
    rfc_id = _create_rfc(factory)
    schedule = AcceptedTaskSchedule(
        start_utc=1_800_000_000,
        end_utc=1_800_003_600,
        scheduling_timezone_iana="America/Guayaquil",
    )
    _, registered = _register_wfm(planning, rfc_id, schedule=schedule)
    reviewed = queries.preview(task_id=registered.task_id, base_revision=1)
    assert reviewed.eligible
    initial_plan = reviewed.draft_rows.plan_revision_id
    assert initial_plan is not None

    correction_command = new_uuid4()
    with UnitOfWork(factory) as uow:
        _insert_receipt(
            uow,
            command_id=correction_command,
            command_type="CorrectTaskPlan",
            target_id=registered.task_id,
        )
        uow.connection.execute(
            "INSERT INTO task_plan_revisions("
            "plan_revision_id,task_id,start_utc,end_utc,origin,scheduling_timezone_iana,source_observation_id,"
            "predecessor_plan_revision_id,reason_code,accepted_at_utc,command_id"
            ") VALUES (?,?,?,?,'correction','America/Guayaquil',NULL,?,'reviewed_correction',1,?)",
            (
                new_uuid4(),
                registered.task_id,
                schedule.start_utc + 60,
                schedule.end_utc + 60,
                initial_plan,
                correction_command,
            ),
        )
    current = queries.preview(task_id=registered.task_id, base_revision=1)
    assert "TASK_PLAN_HISTORY_PRESENT" in _blocker_codes(current)
    delete_command = new_uuid4()
    with pytest.raises(SomaError, match="HARD_DELETE_BLOCKED"):
        service.hard_delete(**_hard_delete_args(registered.task_id, reviewed, command_id=delete_command))
    with ReadSnapshot(factory) as snapshot:
        assert snapshot.connection.execute(
            "SELECT count(*) FROM task_plan_revisions WHERE task_id=?", (registered.task_id,)
        ).fetchone() == (2,)


@pytest.mark.parametrize("history_kind", ["execution", "outcome"])
def test_execution_or_outcome_history_blocks_hard_delete(deletion, history_kind) -> None:
    factory, _, planning, queries, service = deletion
    rfc_id = _create_rfc(factory)
    _, registered = _register_wfm(planning, rfc_id)
    reviewed = queries.preview(task_id=registered.task_id, base_revision=1)
    history_command = new_uuid4()
    with UnitOfWork(factory) as uow:
        _insert_receipt(
            uow,
            command_id=history_command,
            command_type="TestProtectedTaskHistory",
            target_id=registered.task_id,
        )
        if history_kind == "execution":
            uow.connection.execute(
                "INSERT INTO task_execution_events("
                "execution_event_id,task_id,event_kind,effective_at_utc,target_event_id,correction_action,"
                "reason_code,recorded_at_utc,command_id"
                ") VALUES (?,?,'start',1,NULL,NULL,NULL,1,?)",
                (new_uuid4(), registered.task_id, history_command),
            )
            expected = "TASK_EXECUTION_HISTORY_PRESENT"
        else:
            uow.connection.execute(
                "INSERT INTO task_outcome_events("
                "outcome_event_id,task_id,accepted_outcome,correction_of_event_id,reason_code,reviewed_at_utc,command_id"
                ") VALUES (?,?,'completed',NULL,NULL,1,?)",
                (new_uuid4(), registered.task_id, history_command),
            )
            expected = "TASK_OUTCOME_HISTORY_PRESENT"

    current = queries.preview(task_id=registered.task_id, base_revision=1)
    assert expected in _blocker_codes(current)
    delete_command = new_uuid4()
    with pytest.raises(SomaError, match="HARD_DELETE_BLOCKED"):
        service.hard_delete(**_hard_delete_args(registered.task_id, reviewed, command_id=delete_command))
    with ReadSnapshot(factory) as snapshot:
        assert snapshot.connection.execute(
            "SELECT 1 FROM command_receipts WHERE command_id=?", (delete_command,)
        ).fetchone() is None


def test_objective_membership_history_blocks_hard_delete(deletion) -> None:
    factory, _, planning, queries, service = deletion
    rfc_id = _create_rfc(factory)
    schedule = AcceptedTaskSchedule(
        start_utc=1_800_000_000,
        end_utc=1_800_003_600,
        scheduling_timezone_iana="America/Guayaquil",
    )
    _, registered = _register_wfm(planning, rfc_id, schedule=schedule)
    reviewed = queries.preview(task_id=registered.task_id, base_revision=1)
    plan_id = reviewed.draft_rows.plan_revision_id
    assert plan_id is not None

    objective_id = new_uuid4()
    objective_command = new_uuid4()
    with UnitOfWork(factory) as uow:
        _insert_receipt(
            uow,
            command_id=objective_command,
            command_type="CreateObjective",
            target_type="objective",
            target_id=objective_id,
        )
        uow.connection.execute(
            "INSERT INTO objectives("
            "objective_id,tracking_sequence,tracking_id,creation_origin,superseded_by_objective_id,"
            "revision,created_at_utc,created_command_id"
            ") VALUES (?,1,'MW-00000001','manual',NULL,1,0,?)",
            (objective_id, objective_command),
        )
        uow.connection.execute(
            "INSERT INTO objective_membership_events("
            "membership_event_id,task_id,event_kind,from_objective_id,to_objective_id,accepted_plan_revision_id,"
            "grouping_proposal_id,reason_code,recorded_at_utc,command_id"
            ") VALUES (?,?,'add',NULL,?,?,NULL,NULL,0,?)",
            (new_uuid4(), registered.task_id, objective_id, plan_id, objective_command),
        )

    current = queries.preview(task_id=registered.task_id, base_revision=1)
    assert "TASK_OBJECTIVE_HISTORY_PRESENT" in _blocker_codes(current)
    delete_command = new_uuid4()
    with pytest.raises(SomaError, match="HARD_DELETE_BLOCKED"):
        service.hard_delete(**_hard_delete_args(registered.task_id, reviewed, command_id=delete_command))


@pytest.mark.parametrize("history_kind", ["retry", "activity", "lock", "count", "relationship", "audit"])
def test_other_protected_history_is_never_deleted_to_manufacture_eligibility(deletion, history_kind) -> None:
    factory, _, planning, queries, service = deletion
    rfc_id = _create_rfc(factory)
    creation_command, registered = _register_wfm(planning, rfc_id)
    reviewed = queries.preview(task_id=registered.task_id, base_revision=1)
    history_command = new_uuid4()

    device_reference_id = None
    if history_kind == "relationship":
        device_reference_id = DeviceReferenceService(factory).create(
            command_id=new_uuid4(),
            operational_name="NE-T036",
        ).device_reference_id

    with UnitOfWork(factory) as uow:
        if history_kind == "relationship":
            assert device_reference_id is not None
            uow.connection.execute(
                "INSERT INTO task_device_links("
                "link_id,task_id,device_reference_id,active,opened_command_id,closed_command_id"
                ") VALUES (?,?,?,1,?,NULL)",
                (new_uuid4(), registered.task_id, device_reference_id, creation_command),
            )
            expected = "TASK_RELATIONSHIP_HISTORY_PRESENT"
        elif history_kind == "audit":
            uow.connection.execute(
                "INSERT INTO audit_events("
                "audit_event_id,action_type,action_version,recorded_at_utc,actor_kind,target_type,target_id,"
                "command_id,payload_schema,payload_version,payload_json"
                ") VALUES (?,'task.test_history',1,1,'local_user','task',?,?,'TestAuditV1',1,'{}')",
                (new_uuid4(), registered.task_id, creation_command),
            )
            expected = "TASK_AUDIT_HISTORY_PRESENT"
        else:
            _insert_receipt(
                uow,
                command_id=history_command,
                command_type="TestProtectedTaskHistory",
                target_id=registered.task_id,
            )
            if history_kind == "retry":
                other_task = new_uuid4()
                other_creation = new_uuid4()
                _insert_receipt(
                    uow,
                    command_id=other_creation,
                    command_type="CreateLocalTask",
                    target_id=other_task,
                )
                uow.connection.execute(
                    "INSERT INTO tasks("
                    "task_id,task_kind,local_task_name,creation_origin,revision,created_at_utc,created_command_id"
                    ") VALUES (?,'local','retry target','manual',1,0,?)",
                    (other_task, other_creation),
                )
                uow.connection.execute(
                    "INSERT INTO task_retry_relations("
                    "retry_relation_id,predecessor_task_id,successor_task_id,created_at_utc,command_id"
                    ") VALUES (?,?,?,1,?)",
                    (new_uuid4(), registered.task_id, other_task, history_command),
                )
                expected = "TASK_RETRY_HISTORY_PRESENT"
            elif history_kind == "activity":
                lineage_id = new_uuid4()
                uow.connection.execute(
                    "INSERT INTO task_activity_lineages(activity_lineage_id,created_at_utc,created_command_id) "
                    "VALUES (?,1,?)",
                    (lineage_id, history_command),
                )
                uow.connection.execute(
                    "INSERT INTO task_activity_lineage_events("
                    "lineage_event_id,task_id,prior_lineage_id,new_lineage_id,reason_code,recorded_at_utc,command_id"
                    ") VALUES (?,?,NULL,?,'reviewed_same_activity',1,?)",
                    (new_uuid4(), registered.task_id, lineage_id, history_command),
                )
                expected = "TASK_ACTIVITY_HISTORY_PRESENT"
            elif history_kind == "lock":
                uow.connection.execute(
                    "INSERT INTO task_lock_events("
                    "lock_event_id,task_id,lock_kind,action,reason_code,recorded_at_utc,command_id"
                    ") VALUES (?,?,'plan','lock','manual_lock',1,?)",
                    (new_uuid4(), registered.task_id, history_command),
                )
                expected = "TASK_LOCK_HISTORY_PRESENT"
            else:
                uow.connection.execute(
                    "INSERT INTO task_operational_count_events("
                    "inclusion_event_id,task_id,included,reason_code,recorded_at_utc,command_id"
                    ") VALUES (?,?,0,'reviewed_exclusion',1,?)",
                    (new_uuid4(), registered.task_id, history_command),
                )
                expected = "TASK_COUNT_HISTORY_PRESENT"

    current = queries.preview(task_id=registered.task_id, base_revision=1)
    assert expected in _blocker_codes(current)
    delete_command = new_uuid4()
    with pytest.raises(SomaError, match="HARD_DELETE_BLOCKED"):
        service.hard_delete(**_hard_delete_args(registered.task_id, reviewed, command_id=delete_command))
    with ReadSnapshot(factory) as snapshot:
        assert snapshot.connection.execute(
            "SELECT 1 FROM tasks WHERE task_id=?", (registered.task_id,)
        ).fetchone() is not None
        assert snapshot.connection.execute(
            "SELECT 1 FROM command_receipts WHERE command_id=?", (delete_command,)
        ).fetchone() is None


@pytest.mark.parametrize(
    "phase",
    ["retirement", "audit", "audit_ref", "assignment_delete", "identity_delete", "task_delete", "result", "commit"],
)
def test_hard_delete_failure_rolls_back_receipt_retirement_audit_and_all_deletes(
    deletion, monkeypatch, phase
) -> None:
    factory, _, planning, queries, service = deletion
    rfc_id = _create_rfc(factory)
    task_no = "TK00000000000001"
    _, registered = _register_wfm(planning, rfc_id, task_no=task_no)
    preview = queries.preview(task_id=registered.task_id, base_revision=1)
    delete_command = new_uuid4()

    if phase == "commit":
        def fail_commit(self):
            self.rollback()
            raise SomaError("PERSISTENCE_FAILURE", "injected commit failure")

        monkeypatch.setattr(UnitOfWork, "commit", fail_commit)
    else:
        table, operation, condition = {
            "retirement": ("wfm_task_no_retirements", "INSERT", "1"),
            "audit": ("audit_events", "INSERT", "NEW.action_type='task.hard_deleted'"),
            "audit_ref": ("audit_event_results", "INSERT", "NEW.result_type='hard_delete_evidence'"),
            "assignment_delete": ("wfm_rfc_assignment_events", "DELETE", f"OLD.task_id='{registered.task_id}'"),
            "identity_delete": ("wfm_task_identities", "DELETE", f"OLD.task_id='{registered.task_id}'"),
            "task_delete": ("tasks", "DELETE", f"OLD.task_id='{registered.task_id}'"),
            "result": ("command_receipt_results", "INSERT", "NEW.response_schema='TaskMutationResultV1'"),
        }[phase]
        with UnitOfWork(factory) as uow:
            uow.connection.execute(
                f"CREATE TRIGGER test_fail_task_hard_delete BEFORE {operation} ON {table} "
                f"WHEN {condition} BEGIN SELECT RAISE(ABORT,'injected failure'); END"
            )

    with pytest.raises((SomaError, sqlite3.IntegrityError)):
        service.hard_delete(**_hard_delete_args(registered.task_id, preview, command_id=delete_command))

    _assert_no_delete_artifacts(
        factory,
        command_id=delete_command,
        task_id=registered.task_id,
        task_no=task_no,
    )
