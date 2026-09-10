from __future__ import annotations

import json

import pytest

from soma.foundation.identifiers import new_uuid4
from soma.foundation.persistence.uow import ReadSnapshot, UnitOfWork
from soma.objectives_tasks import (
    TaskHardDeleteQueryService,
    TaskHardDeleteService,
    TaskPlanningService,
)
from soma.tickets.rfcs import RfcService
from soma.tickets.service_requests import ServiceRequestService


class _ClearInventoryProvider:
    def classify_task_hard_delete_dependency(self, reader, task_id: str) -> str:
        assert reader.connection.in_transaction
        return "CLEAR"


def _factory(initialized_database):
    database_path, factory_for_path = initialized_database
    return factory_for_path(database_path)


def _insert_receipt(uow: UnitOfWork, *, command_id: str, command_type: str) -> None:
    uow.connection.execute(
        "INSERT INTO command_receipts("
        "command_id,command_type,request_hash,target_type,target_id,committed_at_utc,result_type,result_id"
        ") VALUES (?,?,?,'task',NULL,0,NULL,NULL)",
        (command_id, command_type, "0" * 64),
    )


def _insert_raw_wfm_with_creation_refs(factory, *, ref_case: str) -> str:
    rfc_id = RfcService(factory).create_or_adopt_identity(
        command_id=new_uuid4(),
        rfc_no="NC00000000000991",
        creation_context="manual",
    ).rfc_id
    command_id = new_uuid4()
    task_id = new_uuid4()
    task_no = "TK00000000000991"
    assignment_event_id = new_uuid4()
    audit_event_id = new_uuid4()
    payload = json.dumps(
        {
            "creation_origin": "wfm_manual",
            "reason_category": None,
            "resulting_revision": 1,
            "task_id": task_id,
            "task_kind": "wfm",
            "task_plan_revision_id": None,
        },
        ensure_ascii=False,
        allow_nan=False,
        separators=(",", ":"),
        sort_keys=True,
    )

    with UnitOfWork(factory) as uow:
        _insert_receipt(uow, command_id=command_id, command_type="RegisterManualWfmTask")
        uow.connection.execute(
            "INSERT INTO tasks("
            "task_id,task_kind,local_task_name,creation_origin,revision,created_at_utc,created_command_id"
            ") VALUES (?,'wfm',NULL,'wfm_manual',1,0,?)",
            (task_id, command_id),
        )
        uow.connection.execute(
            "INSERT INTO wfm_task_identities("
            "task_id,task_no,current_rfc_id,assignment_revision,created_command_id"
            ") VALUES (?,?,?,1,?)",
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
            ") VALUES (?,'task.wfm_registered',1,0,'local_user','task',?,?,'TaskAuditV1',1,?)",
            (audit_event_id, task_id, command_id, payload),
        )
        uow.connection.execute(
            "INSERT INTO audit_event_results(audit_event_id,ordinal,result_type,result_id) "
            "VALUES (?,0,'task',?)",
            (audit_event_id, task_id),
        )
        if ref_case == "wrong_assignment":
            uow.connection.execute(
                "INSERT INTO audit_event_results(audit_event_id,ordinal,result_type,result_id) "
                "VALUES (?,1,'wfm_assignment',?)",
                (audit_event_id, new_uuid4()),
            )
        elif ref_case == "ordinal_gap":
            uow.connection.execute(
                "INSERT INTO audit_event_results(audit_event_id,ordinal,result_type,result_id) "
                "VALUES (?,2,'wfm_assignment',?)",
                (audit_event_id, assignment_event_id),
            )
        elif ref_case != "missing_assignment":
            raise AssertionError(f"unsupported ref_case {ref_case}")
    return task_id


def test_local_creation_relationship_refs_are_exact_hard_delete_baseline(initialized_database) -> None:
    factory = _factory(initialized_database)
    inventory = _ClearInventoryProvider()
    planning = TaskPlanningService(factory)
    sr_id = ServiceRequestService(factory).create_manual_service_request(
        command_id=new_uuid4()
    ).service_request_id
    created = planning.create_local_task(
        command_id=new_uuid4(),
        local_task_name="Disposable draft relation",
        service_request_ids=[sr_id],
    )
    queries = TaskHardDeleteQueryService(factory, inventory)
    service = TaskHardDeleteService(factory, inventory)

    preview = queries.preview(task_id=created.task_id, base_revision=1)
    assert preview.eligible
    assert len(preview.draft_rows.sr_link_ids) == 1

    deleted = service.hard_delete(
        command_id=new_uuid4(),
        task_id=created.task_id,
        base_revision=1,
        eligibility_fingerprint=preview.eligibility_fingerprint,
        confirmation_context_id="creation-ref-positive-control",
    )
    assert deleted.outcome == "APPLIED"

    with ReadSnapshot(factory) as snapshot:
        assert snapshot.connection.execute(
            "SELECT 1 FROM tasks WHERE task_id=?", (created.task_id,)
        ).fetchone() is None
        assert snapshot.connection.execute(
            "SELECT 1 FROM task_sr_links WHERE task_id=?", (created.task_id,)
        ).fetchone() is None


def test_forged_extra_local_creation_relationship_ref_makes_delete_indeterminate(initialized_database) -> None:
    factory = _factory(initialized_database)
    inventory = _ClearInventoryProvider()
    planning = TaskPlanningService(factory)
    sr_id = ServiceRequestService(factory).create_manual_service_request(
        command_id=new_uuid4()
    ).service_request_id
    created = planning.create_local_task(
        command_id=new_uuid4(),
        local_task_name="Creation ref tamper probe",
        service_request_ids=[sr_id],
    )

    with UnitOfWork(factory) as uow:
        audit = uow.connection.execute(
            "SELECT audit_event_id FROM audit_events "
            "WHERE target_type='task' AND target_id=? AND action_type='task.created'",
            (created.task_id,),
        ).fetchone()
        assert audit is not None
        audit_event_id = str(audit[0])
        next_ordinal = int(
            uow.connection.execute(
                "SELECT COALESCE(max(ordinal),-1)+1 FROM audit_event_results WHERE audit_event_id=?",
                (audit_event_id,),
            ).fetchone()[0]
        )
        uow.connection.execute(
            "INSERT INTO audit_event_results(audit_event_id,ordinal,result_type,result_id) "
            "VALUES (?,?,'task_relationship','ffffffff-ffff-4fff-bfff-ffffffffffff')",
            (audit_event_id, next_ordinal),
        )

    preview = TaskHardDeleteQueryService(factory, inventory).preview(
        task_id=created.task_id,
        base_revision=1,
    )
    assert preview.status == "INDETERMINATE"
    assert "TASK_AUDIT_HISTORY_PRESENT" in {blocker.code for blocker in preview.blockers}


@pytest.mark.parametrize("ref_case", ["missing_assignment", "wrong_assignment", "ordinal_gap"])
def test_wfm_creation_assignment_ref_must_be_exact_and_contiguous(initialized_database, ref_case: str) -> None:
    factory = _factory(initialized_database)
    task_id = _insert_raw_wfm_with_creation_refs(factory, ref_case=ref_case)
    preview = TaskHardDeleteQueryService(factory, _ClearInventoryProvider()).preview(
        task_id=task_id,
        base_revision=1,
    )
    assert preview.status == "INDETERMINATE"
    assert "TASK_AUDIT_HISTORY_PRESENT" in {blocker.code for blocker in preview.blockers}
