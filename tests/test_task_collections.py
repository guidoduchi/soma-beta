from __future__ import annotations

from copy import deepcopy

import pytest

from soma.foundation.errors import SomaError, ValidationError
from soma.foundation.identifiers import new_uuid4
from soma.foundation.persistence.uow import ReadSnapshot, UnitOfWork
from soma.objectives_tasks import AcceptedTaskSchedule, TaskPlanningService
from soma.objectives_tasks.api.routes_objectives_tasks import ObjectiveTaskRouteAdapter, task_collection_handlers
from soma.objectives_tasks.queries.tasks import TaskQueryService
from soma.objectives_tasks.services.task_relationships import TaskRelationshipService
from soma.tickets.device_references import DeviceReferenceService
from soma.tickets.rfcs import RfcService
from soma.tickets.service_requests import ServiceRequestService


@pytest.fixture
def task_owner(initialized_database):
    path, builder = initialized_database
    factory = builder(path)
    planning = TaskPlanningService(factory)
    rfc = RfcService(factory).create_or_adopt_identity(
        command_id=new_uuid4(), rfc_no="NC00000000000001", creation_context="manual"
    ).rfc_id
    task = planning.register_manual_wfm_task(
        command_id=new_uuid4(), task_no="TK00000000000001", rfc_id=rfc,
        schedule=AcceptedTaskSchedule(100, 200, "America/Guayaquil"),
    )
    other = planning.create_local_task(command_id=new_uuid4(), local_task_name="Other")
    with ReadSnapshot(factory) as snapshot:
        plan = snapshot.connection.execute(
            "SELECT plan_revision_id FROM task_plan_current WHERE task_id=?", (task.task_id,)
        ).fetchone()[0]
    return factory, task.task_id, other.task_id, plan


def _seed_attention(factory, task_id, plan, count=9, kinds=("historical", "regroup", "source_terminal")):
    # Synthetic owner evidence through the real schema. No classification/eligibility claim.
    expected = []
    with UnitOfWork(factory) as uow:
        c = uow.connection
        for index in range(count + 1):
            pending = index < count
            state = "pending" if pending else "superseded"
            for kind in kinds:
                identity = new_uuid4()
                created = 100 + index // 3  # tied timestamps exercise the complete source key.
                if kind == "historical":
                    c.execute(
                        "INSERT INTO historical_objective_proposals(historical_proposal_id,task_id,"
                        "expected_wfm_source_projection_revision,expected_source_plan_start_utc,"
                        "expected_source_plan_end_utc,expected_source_observation_id,input_fingerprint,"
                        "state,revision,created_at_utc) VALUES(?,?,1,100,200,?,?,?,1,?)",
                        (identity, task_id, new_uuid4(), "a" * 64, state, created),
                    )
                elif kind == "source_terminal":
                    c.execute(
                        "INSERT INTO wfm_source_terminal_reviews(source_terminal_review_id,task_id,"
                        "source_projection_revision,provider_lifecycle_class,input_fingerprint,state,"
                        "revision,created_at_utc) VALUES(?,?,1,'complete',?,?,1,?)",
                        (identity, task_id, "a" * 64, state, created),
                    )
                else:
                    c.execute(
                        "INSERT INTO regroup_proposals(regroup_proposal_id,proposal_kind,origin,"
                        "risk_tier,input_fingerprint,state,revision,created_at_utc) "
                        "VALUES(?,'create','task_created','normal',?,?,1,?)",
                        (identity, "a" * 64, state, created),
                    )
                    c.execute(
                        "INSERT INTO regroup_proposal_task_changes(proposal_task_change_id,"
                        "regroup_proposal_id,task_id,expected_task_revision,"
                        "expected_current_plan_revision_id,change_kind) VALUES(?,?,?,1,?,'add')",
                        (new_uuid4(), identity, task_id, plan),
                    )
                if pending:
                    expected.append((kind, created if kind == "source_terminal" else 0, identity))
        uow.commit()
    return sorted(expected)


def _all_pages(query, task_id, *, limit=4, **filters):
    items, cursor = [], None
    for _ in range(100):
        page = query(task_id, limit=limit, cursor=cursor, **filters)
        assert len(page["items"]) <= limit
        items.extend(page["items"])
        cursor = page["continuation"]
        if cursor is None:
            assert len(items) == page["exact_total"]
            return items
    pytest.fail("collection continuation did not terminate")


def test_relationships_grow_beyond_creation_limit_and_detail_stays_a_summary(task_owner):
    factory, _, task_id, _ = task_owner
    service = TaskRelationshipService(factory)
    # Grow through the real post-creation command, beyond the initial-only 62 limit.
    for index in range(64):
        target = ServiceRequestService(factory).create_manual_service_request(
            command_id=new_uuid4()
        ).service_request_id
        service.change_task_relationship(command_id=new_uuid4(), task_id=task_id,
            task_revision=index + 1, relationship_kind="sr", target_id=target, action="link")
    device = DeviceReferenceService(factory).create(command_id=new_uuid4(), operational_name="Device").device_reference_id
    rfc = RfcService(factory).create_or_adopt_identity(
        command_id=new_uuid4(), rfc_no="NC00000000000002", creation_context="manual"
    ).rfc_id
    for offset, (kind, target) in enumerate((("device", device), ("rfc", rfc))):
        service.change_task_relationship(command_id=new_uuid4(), task_id=task_id,
            task_revision=65 + offset, relationship_kind=kind, target_id=target, action="link")
    query = TaskQueryService(factory)
    before = query.workbench(task_id)
    assert before["relationship_summary"] == {"exact_total": 66, "sr_exact_count": 64, "rfc_exact_count": 1, "device_exact_count": 1}
    assert "relationships" not in before and "warnings" not in before
    items = _all_pages(query.list_relationships, task_id)
    assert len(items) == len({item["relationship_id"] for item in items}) == 66
    assert [(item["kind"], item["related_id"]) for item in items] == sorted(
        (item["kind"], item["related_id"]) for item in items)
    assert query.workbench(task_id) == before  # reads create no revisions/evidence.
    cursor = query.list_relationships(task_id, limit=1)["continuation"]
    with pytest.raises(ValidationError):
        query.list_relationships(task_owner[1], cursor=cursor)
    with pytest.raises(ValidationError):
        query.list_attention(task_id, cursor=cursor)
    observed = ObservedFactory(factory)
    TaskQueryService(observed).list_relationships(task_id, limit=7)
    assert max(observed.loaded_rows) <= 8
    assert len([sql for sql, params in observed.statements if sql.startswith("SELECT")]) == 7


def test_attention_counts_complete_pending_collections_without_warning_guesses(task_owner):
    factory, task_id, other, plan = task_owner
    expected = _seed_attention(factory, task_id, plan)
    query = TaskQueryService(factory)
    before = query.workbench(task_id)
    assert before["attention_summary"] == {
        "source_terminal_reviews_exact_pending_count": 9,
        "regroup_proposals_exact_pending_count": 9,
        "historical_proposals_exact_pending_count": 9,
        "warning_codes": ["SOURCE_TERMINAL_REVIEW_PENDING", "REGROUP_PROPOSAL_PENDING", "HISTORICAL_OBJECTIVE_PROPOSAL_PENDING"],
    }
    assert "warnings" not in before
    items = _all_pages(query.list_attention, task_id)
    assert [(item["kind"], item["created_at_utc"] if item["kind"] == "source_terminal" else 0,
             item["item_id"]) for item in items] == expected
    for kind in ("source_terminal", "regroup", "historical"):
        assert len(_all_pages(query.list_attention, task_id, kind=kind)) == 9
    assert query.list_attention(other) == {"items": [], "continuation": None, "exact_total": 0}
    assert query.workbench(task_id) == before


@pytest.mark.parametrize("operation", ["list_relationships", "list_attention"])
@pytest.mark.parametrize("payload", [
    {"limit": True}, {"limit": 0}, {"limit": 501}, {"limit": "1"},
    {"after_id": new_uuid4()}, {"cursor": {}}, {"cursor": []},
])
def test_closed_queries_reject_invalid_limits_fields_and_cursors(task_owner, operation, payload):
    factory, task_id, _, _ = task_owner
    with pytest.raises(ValidationError):
        getattr(TaskQueryService(factory), operation)(task_id, **payload)


def test_attention_cursor_binds_task_kind_collection_version_and_full_order(task_owner):
    factory, task_id, other, plan = task_owner
    _seed_attention(factory, task_id, plan)
    query = TaskQueryService(factory)
    cursor = query.list_attention(task_id, kind="source_terminal", limit=1)["continuation"]
    for args in ({"task_id": other, "kind": "source_terminal"}, {"task_id": task_id, "kind": "regroup"},
                 {"task_id": task_id, "kind": None}):
        with pytest.raises(ValidationError):
            query.list_attention(cursor=cursor, **args)
    for field, value in (("version", True), ("version", 2), ("query_id", "TaskRelationshipList"),
                         ("sort_registry_id", "other"), ("null_order", "last"), ("filter_fingerprint", "0" * 64),
                         ("extra", 1), ("last_key_tuple", ["source_terminal", 100]),
                         ("last_key_tuple", ["source_terminal", True, new_uuid4()])):
        changed = {**deepcopy(cursor), field: value}
        with pytest.raises(ValidationError):
            query.list_attention(task_id, kind="source_terminal", cursor=changed)
    with pytest.raises(ValidationError):
        query.list_relationships(task_id, cursor=cursor)
    for kind in ("unknown", [], True):
        with pytest.raises(ValidationError):
            query.list_attention(task_id, kind=kind)


def test_routes_dispatch_only_the_task_owner_and_missing_tasks_fail(task_owner):
    factory, task_id, _, _ = task_owner
    query = TaskQueryService(factory)
    adapter = ObjectiveTaskRouteAdapter(task_collection_handlers(query))
    for suffix, response_type in (("relationships", "TaskRelationshipPageV1"), ("attention", "TaskAttentionPageV1")):
        response = adapter.dispatch("GET", f"/api/v1/tasks/{task_id}/{suffix}", {"limit": 500})
        assert response.response_type == response_type
        assert response.body == {"items": [], "continuation": None, "exact_total": 0}
        with pytest.raises(ValidationError):
            adapter.dispatch("GET", f"/api/v1/tasks/{task_id}/{suffix}", {"task_id": new_uuid4()})
        with pytest.raises(SomaError) as exc:
            adapter.dispatch("GET", f"/api/v1/tasks/{new_uuid4()}/{suffix}")
        assert exc.value.code == "TASK_NOT_FOUND"


def test_retry_middle_task_exposes_both_immediate_edges(task_owner):
    factory, middle, before, _ = task_owner
    after = TaskPlanningService(factory).create_local_task(command_id=new_uuid4(), local_task_name="After").task_id
    with ReadSnapshot(factory) as snapshot:
        receipt = snapshot.connection.execute("SELECT created_command_id FROM tasks WHERE task_id=?", (middle,)).fetchone()[0]
    with UnitOfWork(factory) as uow:
        for predecessor, successor in ((before, middle), (middle, after)):
            uow.connection.execute("INSERT INTO task_retry_relations VALUES(?,?,?,100,?)",
                (new_uuid4(), predecessor, successor, receipt))
        uow.commit()
    detail = TaskQueryService(factory).workbench(middle)
    assert detail["retry"]["predecessor"]["predecessor_task_id"] == before
    assert detail["retry"]["successor"]["successor_task_id"] == after


class ObservedFactory:
    def __init__(self, factory, hook=None):
        self.factory = factory
        self.statements = []
        self.loaded_rows = []
        self.hook = hook

    def open_authoritative(self, **kwargs):
        underlying = self.factory.open_authoritative(**kwargs)
        owner = self

        class Cursor:
            def __init__(self, cursor):
                self.cursor = cursor

            def __getattr__(self, name):
                return getattr(self.cursor, name)

            def fetchall(self):
                rows = self.cursor.fetchall()
                owner.loaded_rows.append(len(rows))
                return rows

        class Connection:
            def __getattr__(self, name):
                return getattr(underlying, name)

            def execute(self, sql, params=()):
                owner.statements.append((sql, params))
                cursor = underlying.execute(sql, params)
                if owner.hook is not None and "COUNT(*)" in sql:
                    hook, owner.hook = owner.hook, None
                    hook()
                return Cursor(cursor)

        return Connection()


def test_attention_page_has_bounded_loads_constant_queries_and_indexed_order(task_owner):
    factory, task_id, _, plan = task_owner
    _seed_attention(factory, task_id, plan, count=80)
    observed = ObservedFactory(factory)
    page = TaskQueryService(observed).list_attention(task_id, limit=7)
    assert page["exact_total"] == 240 and len(page["items"]) == 7
    assert max(observed.loaded_rows) == 8 and sum(observed.loaded_rows) == 24
    selects = [(sql, params) for sql, params in observed.statements if sql.startswith("SELECT")]
    assert len(selects) == 7  # existence, three counts, three pages; never a per-item query.
    with ReadSnapshot(factory) as snapshot:
        for sql, params in selects:
            steps = [row[3] for row in snapshot.connection.execute("EXPLAIN QUERY PLAN " + sql, params).fetchall()]
            assert not any("USE TEMP B-TREE" in step or step.startswith("SCAN ") for step in steps), steps


def test_attention_count_and_rows_use_one_snapshot_during_concurrent_publication(task_owner):
    factory, task_id, _, plan = task_owner
    _seed_attention(factory, task_id, plan, count=1)
    observed = ObservedFactory(factory, hook=lambda: _seed_attention(factory, task_id, plan, count=1))
    page = TaskQueryService(observed).list_attention(task_id)
    assert page["exact_total"] == len(page["items"]) == 3
    assert TaskQueryService(factory).list_attention(task_id)["exact_total"] == 6


@pytest.mark.parametrize('mask', range(8))
def test_task_warning_enum_uses_only_exact_pending_owner_predicates(task_owner, mask):
    factory, task_id, _, plan = task_owner
    kinds = ('source_terminal', 'regroup', 'historical')
    codes = ('SOURCE_TERMINAL_REVIEW_PENDING', 'REGROUP_PROPOSAL_PENDING', 'HISTORICAL_OBJECTIVE_PROPOSAL_PENDING')
    selected = tuple(kind for index, kind in enumerate(kinds) if mask & (1 << index))
    _seed_attention(factory, task_id, plan, count=1, kinds=selected)
    detail = TaskQueryService(factory).workbench(task_id)
    summary = detail['attention_summary']
    assert summary['warning_codes'] == [code for index, code in enumerate(codes) if mask & (1 << index)]
    for index, name in enumerate(('source_terminal_reviews', 'regroup_proposals', 'historical_proposals')):
        assert summary[name + '_exact_pending_count'] == int(bool(mask & (1 << index)))
    assert 'service_request_ids' not in detail['wfm_context']
    assert detail['retry'] is None
    assert detail['provider_source_projection'] is None
    assert detail['actual_execution']['execution_state'] == 'not_started'


def test_nonpending_owner_evidence_does_not_create_task_warnings(task_owner):
    factory, task_id, _, plan = task_owner
    _seed_attention(factory, task_id, plan, count=0)
    assert TaskQueryService(factory).workbench(task_id)['attention_summary'] == {
        'source_terminal_reviews_exact_pending_count': 0,
        'regroup_proposals_exact_pending_count': 0,
        'historical_proposals_exact_pending_count': 0,
        'warning_codes': [],
    }
