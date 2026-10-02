from __future__ import annotations

import pytest

from soma.foundation.errors import ValidationError, IntegrityFailure
from soma.foundation.identifiers import new_uuid4
from soma.objectives_tasks import TaskPlanningService, AcceptedTaskSchedule
from soma.objectives_tasks.services.grouping import GroupingService
from soma.objectives_tasks.services.objectives import ObjectiveService
from soma.objectives_tasks.domain.objectives import ObjectiveExistingTaskIntent
from soma.foundation.errors import SomaError
from soma.foundation.persistence.uow import UnitOfWork, ReadSnapshot
from soma.objectives_tasks.queries.grouping import ObjectiveGroupingQueryService


def _seed(initialized_database):
    path, builder = initialized_database
    factory = builder(path)
    with UnitOfWork(factory) as uow:
        for i in range(1, 9):
            identity = f"{i:08x}-1111-4111-8111-111111111111"
            uow.connection.execute(
                "INSERT INTO regroup_proposals(regroup_proposal_id,proposal_kind,origin,"
                "risk_tier,input_fingerprint,state,revision,created_at_utc) "
                "VALUES (?,'create',?,?,?, ?,1,?)",
                (identity, "manual_request" if i <= 4 else "task_created",
                 "normal" if i <= 4 else "high", f"{i:064x}",
                 ("pending", "accepted", "rejected", "superseded")[(i - 1) % 4],
                 100 if i <= 6 else 101),
            )
        uow.commit()
    return factory


def test_grouping_complete_cursor_preserves_timestamp_ties_and_total(initialized_database):
    factory = _seed(initialized_database)
    query = ObjectiveGroupingQueryService(factory)
    with ReadSnapshot(factory) as snapshot:
        before = snapshot.connection.execute("SELECT COUNT(*) FROM command_receipts").fetchone()[0]
    cursor, identities = None, []
    while True:
        page = query.list_proposals(cursor=cursor, limit=2)
        assert page["exact_total"] == 8
        identities.extend(item["proposal_id"] for item in page["items"])
        cursor = page["continuation"]
        if cursor is None:
            break
        assert len(cursor["last_key_tuple"]) == 2
        assert cursor["query_id"] == "GroupingProposalList"
        assert cursor["sort_registry_id"] == "GROUPING_PROPOSAL_CREATED_ID_ASC_V1"
    assert len(identities) == len(set(identities)) == 8
    assert identities == sorted(identities)
    assert query.list_proposals(state="superseded")["exact_total"] == 2
    assert query.list_proposals(risk="normal", origin="manual_request")["exact_total"] == 4
    with ReadSnapshot(factory) as snapshot:
        assert snapshot.connection.execute("SELECT COUNT(*) FROM command_receipts").fetchone()[0] == before


def test_grouping_cursor_rejects_filter_drift_and_incomplete_keys(initialized_database):
    query = ObjectiveGroupingQueryService(_seed(initialized_database))
    cursor = query.list_proposals(limit=1)["continuation"]
    for changed in ({"state": "superseded"}, {"risk": "high"}, {"origin": "task_created"}):
        with pytest.raises(ValidationError):
            query.list_proposals(cursor=cursor, **changed)
    for changed in ({"version": True}, {"version": 2}, {"query_id": "OtherQuery"},
                    {"sort_registry_id": "OTHER_ORDER"}, {"null_order": "first"},
                    {"last_key_tuple": [100]}, {"last_key_tuple": [True, cursor["last_key_tuple"][1]]},
                    {"last_key_tuple": [100, "invalid"]}, {"unexpected": 1}):
        with pytest.raises(ValidationError):
            query.list_proposals(cursor={**cursor, **changed})
    with pytest.raises(ValidationError):
        query.list_proposals(cursor={"created_at_utc": 100, "proposal_id": cursor["last_key_tuple"][1]})
    with pytest.raises(ValidationError):
        query.list_proposals(cursor=cursor, after_created_at_utc=100)


def test_grouping_public_transport_excludes_raw_continuation_keys(initialized_database):
    query = ObjectiveGroupingQueryService(_seed(initialized_database))
    first = query.list_transport({"state": "superseded", "limit": 1})
    second = query.list_transport({"state": "superseded", "limit": 1, "cursor": first["continuation"]})
    assert first["exact_total"] == second["exact_total"] == 2
    assert first["items"][0]["proposal_id"] != second["items"][0]["proposal_id"]
    for field in ("after_created_at_utc", "after_proposal_id", "unrecognized"):
        with pytest.raises(ValidationError):
            query.list_transport({field: 100})
    assert second["items"][0]["affected_task_exact_count"] == 0
    assert second["items"][0]["affected_objective_exact_count"] == 0


def test_grouping_all_states_use_fixed_indexed_seeks_without_global_sort(initialized_database, monkeypatch):
    import soma.objectives_tasks.queries.grouping as module

    factory = _seed(initialized_database)
    statements = []
    original = module.ReadSnapshot

    class TracedSnapshot(original):
        def __enter__(self):
            snapshot = super().__enter__()
            snapshot.connection.set_trace_callback(statements.append)
            return snapshot

    monkeypatch.setattr(module, "ReadSnapshot", TracedSnapshot)
    page = ObjectiveGroupingQueryService(factory).list_proposals(limit=1)
    assert len(page["items"]) == 1
    seeks = [sql for sql in statements if sql.startswith("SELECT p.regroup_proposal_id")]
    assert len(seeks) == 4
    with original(factory) as snapshot:
        for sql in seeks:
            plan = [str(row[3]) for row in snapshot.connection.execute("EXPLAIN QUERY PLAN " + sql)]
            assert any("idx_regroup_proposals_state_created" in row for row in plan)
            assert not any("TEMP B-TREE FOR ORDER BY" in row for row in plan)
            assert sql.endswith("LIMIT 2")


def _current_proposals(initialized_database):
    path, builder = initialized_database
    factory = builder(path)
    tasks = [TaskPlanningService(factory).create_local_task(command_id=new_uuid4(),local_task_name=f"Synthetic {i}",
        schedule=AcceptedTaskSchedule(2_880_000_000+i*1000,2_880_000_100+i*1000,"America/Guayaquil")) for i in range(3)]
    GroupingService(factory).recompute_grouping_proposals(command_id=new_uuid4(),origin="manual_request")
    return factory,tasks


def test_grouping_page_warnings_reuse_exact_owner_classification_and_single_capture(initialized_database,monkeypatch):
    factory,tasks = _current_proposals(initialized_database)
    query = ObjectiveGroupingQueryService(factory)
    original = GroupingService._load_snapshot
    captures=[]
    monkeypatch.setattr(GroupingService,"_load_snapshot",staticmethod(lambda reader:(captures.append(True),original(reader))[1]))
    monkeypatch.setattr(query,"proposal_detail",lambda *args,**kwargs:pytest.fail("List cannot invoke detail per item"))
    page=query.list_transport({"limit":200})
    assert len(page["items"]) == 3
    assert all(item["owner_warnings"] == [] for item in page["items"])
    assert len(captures) == 1
    item=page["items"][0]
    GroupingService(factory).reject_regroup_proposal(command_id=new_uuid4(),proposal_id=item["proposal_id"],
        proposal_revision=item["revision"],input_fingerprint=item["input_fingerprint"],reason_category="operator_rejected")
    row=next(row for row in query.list_proposals()["items"] if row["proposal_id"]==item["proposal_id"])
    assert row["owner_warnings"] == ["GROUPING_EQUIVALENT_REJECTION"]
    detail=ObjectiveGroupingQueryService(factory).proposal_detail(item["proposal_id"],task_limit=1)
    assert detail["stale"] is False and detail["equivalent_rejection_suppressed"] is True
    with ReadSnapshot(factory) as snapshot:
        task_id=snapshot.connection.execute("SELECT task_id FROM regroup_proposal_task_changes WHERE regroup_proposal_id=?",(item["proposal_id"],)).fetchone()[0]
        revision,plan_revision=snapshot.connection.execute("SELECT t.revision,p.revision FROM tasks t JOIN task_plan_current p ON p.task_id=t.task_id WHERE t.task_id=?",(task_id,)).fetchone()
    TaskPlanningService(factory).set_task_plan(command_id=new_uuid4(),task_id=task_id,task_revision=revision,current_plan_revision=plan_revision,
        schedule=AcceptedTaskSchedule(2_890_000_000,2_890_000_100,"America/Guayaquil"),reason_category="operator_change")
    row=next(row for row in query.list_proposals()["items"] if row["proposal_id"]==item["proposal_id"])
    assert row["owner_warnings"] == ["GROUPING_PROPOSAL_STALE","GROUPING_EQUIVALENT_REJECTION"]
    assert ObjectiveGroupingQueryService(factory).proposal_detail(item["proposal_id"],task_limit=1)["stale"] is True


def test_grouping_uncertain_classification_never_returns_authoritative_clear(initialized_database,monkeypatch):
    factory,_ = _current_proposals(initialized_database)
    def broken(reader):
        raise IntegrityFailure("Synthetic authority unavailable")
    monkeypatch.setattr(GroupingService,"_load_snapshot",staticmethod(broken))
    with pytest.raises(IntegrityFailure):
        ObjectiveGroupingQueryService(factory).list_transport({})


def test_grouping_manual_page_reuses_prefetched_exact_authority(initialized_database,monkeypatch):
    path,builder=initialized_database;factory=builder(path);query=ObjectiveGroupingQueryService(factory)
    objectives=[]
    for i in range(4):
        task=TaskPlanningService(factory).create_local_task(command_id=new_uuid4(),local_task_name=f"Manual synthetic {i}",
            schedule=AcceptedTaskSchedule(2_900_000_000+i*100,2_900_000_100+i*100,"America/Guayaquil"))
        with ReadSnapshot(factory) as snapshot:
            row=snapshot.connection.execute("SELECT t.revision,p.revision,p.plan_revision_id FROM tasks t JOIN task_plan_current p ON p.task_id=t.task_id WHERE t.task_id=?",(task.task_id,)).fetchone()
        intent=ObjectiveExistingTaskIntent(task.task_id,int(row[0]),int(row[1]),str(row[2]))
        preview=query.creation_preview(existing_tasks=(intent,))
        objectives.append(ObjectiveService(factory).create_objective_from_preview(command_id=new_uuid4(),preview_fingerprint=preview["fingerprint"],existing_tasks=(intent,)).objective_id)
    for left,right in zip(objectives,objectives[1:]):
        GroupingService(factory).recompute_grouping_proposals(command_id=new_uuid4(),origin="manual_request",
            trigger_scope={"kind":"manual_exact_touch_merge","objective_ids":[left,right]})
    original=GroupingService._manual_exact_touch_candidate;calls=[]
    def prefetched(cls,reader,**kwargs):
        assert kwargs.get("_authority") is not None
        calls.append(kwargs["objective_ids"])
        return original(reader,**kwargs)
    monkeypatch.setattr(GroupingService,"_manual_exact_touch_candidate",classmethod(prefetched))
    page=query.list_proposals()
    assert len(page["items"]) == len(calls) == 3
    assert all(item["owner_warnings"] == [] for item in page["items"])
    for item in page["items"]:
        assert query.proposal_detail(item["proposal_id"])["stale"] is False
    monkeypatch.setattr("soma.objectives_tasks.services.grouping._GROUPING_WORKSET_SOFT_THRESHOLD",1)
    with pytest.raises(SomaError) as error:
        query.list_proposals()
    assert error.value.code == "GROUPING_INDETERMINATE"


@pytest.mark.parametrize("kwargs", [{"state": "invalid"}, {"state": []}, {"risk": "LOW"},
                                  {"origin": True}, {"limit": True}, {"limit": 501}])
def test_grouping_transport_rejects_unknown_filters(initialized_database, kwargs):
    path, builder = initialized_database
    with pytest.raises(ValidationError):
        ObjectiveGroupingQueryService(builder(path)).list_proposals(**kwargs)
