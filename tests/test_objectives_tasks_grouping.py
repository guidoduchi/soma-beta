from __future__ import annotations

import pytest

from soma.foundation.errors import IntegrityFailure, SomaError
from soma.foundation.identifiers import new_uuid4
from soma.foundation.persistence.uow import ReadSnapshot, UnitOfWork
from soma.objectives_tasks import AcceptedTaskSchedule, TaskPlanningService
from soma.objectives_tasks.domain.objectives import ObjectiveExistingTaskIntent
from soma.objectives_tasks.queries.objectives import ObjectiveQueryService
from soma.objectives_tasks.queries.task_activity_review import WfmActivityRelationshipReviewQueryService
from soma.objectives_tasks.services.objectives import ObjectiveService
from soma.objectives_tasks.services.task_execution import TaskExecutionService
from soma.objectives_tasks.services.task_activity_review import WfmActivityRelationshipReviewService
from soma.objectives_tasks.services.task_explicit_lock import TaskExplicitLockService
from soma.reference.application.customer_service import CustomerReferenceService
from soma.tickets.service_requests import ServiceRequestService
from soma.tickets.rfcs import RfcService
from soma.tickets.sr_references import ServiceRequestReferenceService
from soma.objectives_tasks.queries.grouping import ObjectiveGroupingQueryService
from soma.objectives_tasks.services.grouping import GroupingService
from soma.objectives_tasks.source_terminal_authority import (
    WfmSourceProjectionMutation,
    WfmSourceProjectionParticipant,
)


TZ = "America/Guayaquil"


def _factory(initialized_database):
    path, builder = initialized_database
    return builder(path)


def _task(
    factory,
    name: str,
    start: int,
    end: int,
    *,
    service_request_ids: tuple[str, ...] = (),
):
    return TaskPlanningService(factory).create_local_task(
        command_id=new_uuid4(),
        local_task_name=name,
        schedule=AcceptedTaskSchedule(
            start_utc=start,
            end_utc=end,
            scheduling_timezone_iana=TZ,
        ),
        service_request_ids=service_request_ids,
    )


def _intent(factory, task_id: str) -> ObjectiveExistingTaskIntent:
    with ReadSnapshot(factory) as snapshot:
        row = snapshot.connection.execute(
            "SELECT t.revision,pc.revision,pc.plan_revision_id "
            "FROM tasks t JOIN task_plan_current pc ON pc.task_id=t.task_id "
            "WHERE t.task_id=?",
            (task_id,),
        ).fetchone()
    assert row is not None
    return ObjectiveExistingTaskIntent(
        task_id=task_id,
        expected_task_revision=int(row[0]),
        expected_plan_revision=int(row[1]),
        expected_plan_revision_id=str(row[2]),
    )


def _objective(factory, *task_ids: str) -> str:
    intents = tuple(_intent(factory, task_id) for task_id in task_ids)
    preview = ObjectiveGroupingQueryService(factory).creation_preview(existing_tasks=intents)
    assert preview["mode"] == "CREATE"
    result = ObjectiveService(factory).create_objective_from_preview(
        command_id=new_uuid4(),
        preview_fingerprint=str(preview["fingerprint"]),
        existing_tasks=intents,
    )
    return result.objective_id


class _NoClassificationParticipant:
    def apply_customer_change(
        self,
        _uow,
        _sr_id: str,
        _new_customer_org_id: str | None,
        _command_context,
    ):
        return ()


def _service_request_with_customer(factory, suffix: int, customer_org_id: str | None) -> str:
    sr = ServiceRequestService(factory).create_manual_service_request(
        command_id=new_uuid4(),
        official_sr_no=f"98{suffix:06d}",
    )
    if customer_org_id is not None:
        ServiceRequestReferenceService(
            factory,
            _NoClassificationParticipant(),
        ).set_customer(
            command_id=new_uuid4(),
            service_request_id=sr.service_request_id,
            base_revision=1,
            customer_org_id=customer_org_id,
            reason_category="grouping_context_setup",
        )
    return sr.service_request_id


def test_grouping_sweep_is_transitive_and_exact_touch_separates(initialized_database) -> None:
    factory = _factory(initialized_database)
    _task(factory, "A", 2_400_000_000, 2_400_000_100)
    _task(factory, "B", 2_400_000_050, 2_400_000_200)
    _task(factory, "C", 2_400_000_150, 2_400_000_250)
    _task(factory, "D", 2_400_000_250, 2_400_000_350)

    response = GroupingService(factory).recompute_grouping_proposals(
        command_id=new_uuid4(),
        origin="manual_request",
    )
    assert len(response["proposals"]["items"]) == 2
    details = [
        ObjectiveGroupingQueryService(factory).proposal_detail(item["proposal_id"])
        for item in response["proposals"]["items"]
    ]
    counts = sorted(detail["task_change_exact_count"] for detail in details)
    assert counts == [1, 3]
    assert all(detail["proposal_kind"] == "create" for detail in details)


def test_identical_rejected_grouping_input_is_suppressed_until_reconsidered(
    initialized_database,
) -> None:
    factory = _factory(initialized_database)
    _task(factory, "Solo", 2_500_000_000, 2_500_003_600)
    service = GroupingService(factory)
    first = service.recompute_grouping_proposals(
        command_id=new_uuid4(),
        origin="manual_request",
    )
    assert len(first["proposals"]["items"]) == 1
    item = first["proposals"]["items"][0]
    proposal_id = str(item["proposal_id"])
    fingerprint = str(item["input_fingerprint"])
    rejected = service.reject_regroup_proposal(
        command_id=new_uuid4(),
        proposal_id=proposal_id,
        proposal_revision=1,
        input_fingerprint=fingerprint,
        reason_category="operator_rejected",
    )
    assert rejected["state"] == "rejected"
    suppressed = service.recompute_grouping_proposals(
        command_id=new_uuid4(),
        origin="manual_request",
    )
    assert suppressed["proposals"]["items"] == []

    with ReadSnapshot(factory) as snapshot:
        rejection_id = str(
            snapshot.connection.execute(
                "SELECT rejection_event_id FROM regroup_rejection_events "
                "WHERE regroup_proposal_id=?",
                (proposal_id,),
            ).fetchone()[0]
        )
    service.reconsider_regroup_inputs(
        command_id=new_uuid4(),
        proposal_id=proposal_id,
        rejection_event_id=rejection_id,
        input_fingerprint=fingerprint,
        reason_category="reconsider",
    )
    fresh = service.recompute_grouping_proposals(
        command_id=new_uuid4(),
        origin="manual_request",
    )
    assert len(fresh["proposals"]["items"]) == 1


def test_accept_create_grouping_proposal_creates_nonoverlapping_objective(
    initialized_database,
) -> None:
    factory = _factory(initialized_database)
    first = _task(factory, "A", 2_600_000_000, 2_600_000_200)
    second = _task(factory, "B", 2_600_000_100, 2_600_000_300)
    service = GroupingService(factory)
    page = service.recompute_grouping_proposals(
        command_id=new_uuid4(),
        origin="manual_request",
    )
    assert len(page["proposals"]["items"]) == 1
    item = page["proposals"]["items"][0]
    accepted = service.accept_regroup_proposal(
        command_id=new_uuid4(),
        proposal_id=str(item["proposal_id"]),
        proposal_revision=1,
        input_fingerprint=str(item["input_fingerprint"]),
    )
    assert accepted["state"] == "accepted"
    with ReadSnapshot(factory) as snapshot:
        memberships = snapshot.connection.execute(
            "SELECT task_id,objective_id FROM objective_task_membership_current "
            "ORDER BY task_id"
        ).fetchall()
        objectives = snapshot.connection.execute(
            "SELECT objective_id,creation_origin,superseded_by_objective_id "
            "FROM objectives ORDER BY objective_id"
        ).fetchall()
    assert len(memberships) == 2
    assert {str(row[0]) for row in memberships} == {first.task_id, second.task_id}
    assert len({str(row[1]) for row in memberships}) == 1
    assert len(objectives) == 1
    assert str(objectives[0][1]) == "automatic_grouping"


def test_t009_bridging_task_consolidates_existing_objectives_with_lowest_tracking_survivor(
    initialized_database,
) -> None:
    factory = _factory(initialized_database)
    left = _task(factory, "Left objective", 2_610_000_000, 2_610_000_200)
    right = _task(factory, "Right objective", 2_610_000_300, 2_610_000_500)
    left_objective = _objective(factory, left.task_id)
    right_objective = _objective(factory, right.task_id)
    bridge = _task(factory, "Bridge", 2_610_000_150, 2_610_000_350)

    service = GroupingService(factory)
    page = service.recompute_grouping_proposals(
        command_id=new_uuid4(),
        origin="manual_request",
    )
    assert len(page["proposals"]["items"]) == 1
    proposal_id = str(page["proposals"]["items"][0]["proposal_id"])
    detail = ObjectiveGroupingQueryService(factory).proposal_detail(proposal_id)
    assert detail["proposal_kind"] == "consolidate"
    assert detail["stale"] is False
    assert detail["component_envelope"] == {
        "start_utc": 2_610_000_000,
        "end_utc": 2_610_000_500,
    }

    with ReadSnapshot(factory) as snapshot:
        tracking = {
            str(row[0]): int(row[1])
            for row in snapshot.connection.execute(
                "SELECT objective_id,tracking_sequence FROM objectives "
                "WHERE objective_id IN (?,?)",
                (left_objective, right_objective),
            ).fetchall()
        }
    expected_survivor = min(tracking, key=tracking.get)
    expected_superseded = (
        right_objective if expected_survivor == left_objective else left_objective
    )
    assert detail["survivor_objective_id"] == expected_survivor
    assert {
        (item["objective_id"], item["action"])
        for item in detail["objective_changes"]
    } == {
        (expected_survivor, "retain"),
        (expected_superseded, "supersede"),
    }

    accepted = service.accept_regroup_proposal(
        command_id=new_uuid4(),
        proposal_id=proposal_id,
        proposal_revision=1,
        input_fingerprint=str(detail["input_fingerprint"]),
    )
    assert accepted["state"] == "accepted"
    with ReadSnapshot(factory) as snapshot:
        memberships = snapshot.connection.execute(
            "SELECT task_id,objective_id FROM objective_task_membership_current "
            "WHERE task_id IN (?,?,?) ORDER BY task_id",
            (left.task_id, right.task_id, bridge.task_id),
        ).fetchall()
        assert len(memberships) == 3
        assert {str(row[1]) for row in memberships} == {expected_survivor}
        superseded = snapshot.connection.execute(
            "SELECT superseded_by_objective_id FROM objectives WHERE objective_id=?",
            (expected_superseded,),
        ).fetchone()
        assert superseded is not None and str(superseded[0]) == expected_survivor
        assert snapshot.connection.execute(
            "SELECT COUNT(*) FROM objectives WHERE superseded_by_objective_id IS NULL"
        ).fetchone()[0] == 1


def test_t010_grouping_is_global_and_multi_customer_context_is_explicit(
    initialized_database,
) -> None:
    factory = _factory(initialized_database)
    customers = CustomerReferenceService(factory)
    customer_a = customers.create_customer_organization(
        command_id=new_uuid4(),
        name="Grouping Customer A",
    )
    customer_b = customers.create_customer_organization(
        command_id=new_uuid4(),
        name="Grouping Customer B",
    )
    sr_a = _service_request_with_customer(factory, 10, customer_a.customer_org_id)
    sr_b = _service_request_with_customer(factory, 11, customer_b.customer_org_id)
    sr_unknown = _service_request_with_customer(factory, 12, None)

    first = _task(
        factory,
        "Customer A task",
        2_620_000_000,
        2_620_000_300,
        service_request_ids=(sr_a,),
    )
    second = _task(
        factory,
        "Customer B task",
        2_620_000_100,
        2_620_000_400,
        service_request_ids=(sr_b,),
    )
    third = _task(
        factory,
        "Unknown customer task",
        2_620_000_200,
        2_620_000_500,
        service_request_ids=(sr_unknown,),
    )

    service = GroupingService(factory)
    page = service.recompute_grouping_proposals(
        command_id=new_uuid4(),
        origin="manual_request",
    )
    assert len(page["proposals"]["items"]) == 1
    proposal_id = str(page["proposals"]["items"][0]["proposal_id"])
    detail = ObjectiveGroupingQueryService(factory).proposal_detail(proposal_id)
    assert detail["proposal_kind"] == "create"
    assert detail["task_change_exact_count"] == 3
    assert detail["component_envelope"] == {
        "start_utc": 2_620_000_000,
        "end_utc": 2_620_000_500,
    }
    partitions = detail["explanatory_partitions"]
    assert partitions["customer_org_ids"] == sorted(
        [customer_a.customer_org_id, customer_b.customer_org_id]
    )
    assert partitions["multi_customer"] is True
    assert partitions["unresolved_customer_task_ids"] == [third.task_id]

    accepted = service.accept_regroup_proposal(
        command_id=new_uuid4(),
        proposal_id=proposal_id,
        proposal_revision=1,
        input_fingerprint=str(detail["input_fingerprint"]),
    )
    assert accepted["state"] == "accepted"
    with ReadSnapshot(factory) as snapshot:
        objective_rows = snapshot.connection.execute(
            "SELECT objective_id FROM objective_task_membership_current "
            "WHERE task_id IN (?,?,?) ORDER BY objective_id",
            (first.task_id, second.task_id, third.task_id),
        ).fetchall()
    assert len(objective_rows) == 3
    assert len({str(row[0]) for row in objective_rows}) == 1
    objective_id = str(objective_rows[0][0])
    context = ObjectiveQueryService(factory).context_by_task_relationships(
        objective_id,
        limit=100,
    )
    customer_rows = [
        item for item in context["items"] if item["context_type"] == "customer"
    ]
    assert {
        (item["related_id"], item["source_task_id"], item["resolution_state"])
        for item in customer_rows
    } == {
        (customer_a.customer_org_id, first.task_id, "resolved"),
        (customer_b.customer_org_id, second.task_id, "resolved"),
        (None, third.task_id, "unresolved"),
    }
    assert context["exact_totals_by_context_type"]["customer"] == 3


def test_t041_in_progress_regroup_requires_high_risk_and_blocks_started_consolidation(
    initialized_database,
) -> None:
    factory = _factory(initialized_database)
    base = _task(factory, "In-progress base", 2_740_000_000, 2_740_000_500)
    base_objective = _objective(factory, base.task_id)

    current_base = _intent(factory, base.task_id)
    started = TaskExecutionService(factory).start_task_execution(
        command_id=new_uuid4(),
        task_id=base.task_id,
        task_revision=current_base.expected_task_revision,
        execution_revision=0,
        effective_start_utc=2_740_000_050,
    )
    assert started.outcome == "APPLIED"

    inside = _task(factory, "Unstarted inside envelope", 2_740_000_200, 2_740_000_300)
    service = GroupingService(factory)
    page = service.recompute_grouping_proposals(
        command_id=new_uuid4(),
        origin="manual_request",
    )
    assert len(page["proposals"]["items"]) == 1
    proposal_id = str(page["proposals"]["items"][0]["proposal_id"])
    detail = ObjectiveGroupingQueryService(factory).proposal_detail(proposal_id)
    assert detail["proposal_kind"] == "join"
    assert detail["risk_tier"] == "high"
    assert detail["survivor_objective_id"] == base_objective
    assert {
        (row["task_id"], row["change_kind"])
        for row in detail["task_changes"]
    } == {(inside.task_id, "add")}

    rejected_command = new_uuid4()
    with pytest.raises(SomaError) as missing_review:
        service.accept_regroup_proposal(
            command_id=rejected_command,
            proposal_id=proposal_id,
            proposal_revision=1,
            input_fingerprint=str(detail["input_fingerprint"]),
            accept_high_risk=False,
        )
    assert missing_review.value.code == "OBJECTIVE_IN_PROGRESS_RESTRUCTURE_LIMIT"
    with ReadSnapshot(factory) as snapshot:
        assert snapshot.connection.execute(
            "SELECT 1 FROM command_receipts WHERE command_id=?",
            (rejected_command,),
        ).fetchone() is None
        assert snapshot.connection.execute(
            "SELECT 1 FROM objective_task_membership_current WHERE task_id=?",
            (inside.task_id,),
        ).fetchone() is None

    accepted = service.accept_regroup_proposal(
        command_id=new_uuid4(),
        proposal_id=proposal_id,
        proposal_revision=1,
        input_fingerprint=str(detail["input_fingerprint"]),
        accept_high_risk=True,
    )
    assert accepted["state"] == "accepted"
    with ReadSnapshot(factory) as snapshot:
        inside_membership = snapshot.connection.execute(
            "SELECT objective_id FROM objective_task_membership_current WHERE task_id=?",
            (inside.task_id,),
        ).fetchone()
        assert inside_membership is not None
        assert str(inside_membership[0]) == base_objective
        base_execution = snapshot.connection.execute(
            "SELECT execution_state FROM task_execution_projection WHERE task_id=?",
            (base.task_id,),
        ).fetchone()
        assert base_execution is not None and str(base_execution[0]) == "in_progress"

    adjacent = _task(factory, "Adjacent planned objective", 2_740_000_500, 2_740_000_900)
    adjacent_objective = _objective(factory, adjacent.task_id)
    assert adjacent_objective != base_objective
    bridge = _task(factory, "Started consolidation bridge", 2_740_000_400, 2_740_000_600)

    blocked = service.recompute_grouping_proposals(
        command_id=new_uuid4(),
        origin="manual_request",
    )
    for item in blocked["proposals"]["items"]:
        candidate = ObjectiveGroupingQueryService(factory).proposal_detail(
            str(item["proposal_id"])
        )
        changed_ids = {
            str(row["task_id"])
            for row in candidate["task_changes"]
        }
        assert bridge.task_id not in changed_ids


def test_t045_clock_passage_is_read_only_and_never_creates_a_grouping_lock(
    initialized_database,
) -> None:
    factory = _factory(initialized_database)
    task = _task(factory, "Future grouping clock", 2_750_000_100, 2_750_000_300)
    objective_id = _objective(factory, task.task_id)
    query = ObjectiveGroupingQueryService(factory)

    before = query.grouping_eligibility(
        task.task_id,
        as_of_utc=2_750_000_000,
    )
    assert before["classification"] == "ordinary_future"
    assert before["eligible"] is True
    assert before["membership"]["objective_id"] == objective_id
    assert before["lock_revision"] == 0

    with ReadSnapshot(factory) as snapshot:
        counts_before = {
            "receipts": int(snapshot.connection.execute(
                "SELECT COUNT(*) FROM command_receipts"
            ).fetchone()[0]),
            "audits": int(snapshot.connection.execute(
                "SELECT COUNT(*) FROM audit_events"
            ).fetchone()[0]),
            "lock_events": int(snapshot.connection.execute(
                "SELECT COUNT(*) FROM task_lock_events WHERE task_id=?",
                (task.task_id,),
            ).fetchone()[0]),
            "execution_events": int(snapshot.connection.execute(
                "SELECT COUNT(*) FROM task_execution_events WHERE task_id=?",
                (task.task_id,),
            ).fetchone()[0]),
        }
        membership_before = tuple(
            snapshot.connection.execute(
                "SELECT objective_id,accepted_plan_revision_id,membership_revision,last_event_id "
                "FROM objective_task_membership_current WHERE task_id=?",
                (task.task_id,),
            ).fetchone()
        )

    after_clock = query.grouping_eligibility(
        task.task_id,
        as_of_utc=2_750_000_150,
    )
    assert after_clock["classification"] == "ordinary_future"
    assert after_clock["eligible"] is False
    assert after_clock["membership"] == before["membership"]
    assert after_clock["lock_revision"] == 0

    with ReadSnapshot(factory) as snapshot:
        assert int(snapshot.connection.execute(
            "SELECT COUNT(*) FROM command_receipts"
        ).fetchone()[0]) == counts_before["receipts"]
        assert int(snapshot.connection.execute(
            "SELECT COUNT(*) FROM audit_events"
        ).fetchone()[0]) == counts_before["audits"]
        assert int(snapshot.connection.execute(
            "SELECT COUNT(*) FROM task_lock_events WHERE task_id=?",
            (task.task_id,),
        ).fetchone()[0]) == counts_before["lock_events"] == 0
        assert int(snapshot.connection.execute(
            "SELECT COUNT(*) FROM task_execution_events WHERE task_id=?",
            (task.task_id,),
        ).fetchone()[0]) == counts_before["execution_events"] == 0
        assert tuple(
            snapshot.connection.execute(
                "SELECT objective_id,accepted_plan_revision_id,membership_revision,last_event_id "
                "FROM objective_task_membership_current WHERE task_id=?",
                (task.task_id,),
            ).fetchone()
        ) == membership_before

    current = _intent(factory, task.task_id)
    started = TaskExecutionService(factory).start_task_execution(
        command_id=new_uuid4(),
        task_id=task.task_id,
        task_revision=current.expected_task_revision,
        execution_revision=0,
        effective_start_utc=2_750_000_160,
    )
    assert started.outcome == "APPLIED"
    after_explicit_execution = query.grouping_eligibility(
        task.task_id,
        as_of_utc=2_750_000_170,
    )
    assert after_explicit_execution["classification"] == "started_or_protected"
    assert after_explicit_execution["eligible"] is False



def test_accept_regroup_plans_globally_only_on_read_snapshot(
    initialized_database,
    monkeypatch,
) -> None:
    factory = _factory(initialized_database)
    _task(factory, "A11 read A", 2_880_000_000, 2_880_000_200)
    _task(factory, "A11 read B", 2_880_000_100, 2_880_000_300)
    service = GroupingService(factory)
    page = service.recompute_grouping_proposals(
        command_id=new_uuid4(),
        origin="manual_request",
    )
    item = page["proposals"]["items"][0]

    original = GroupingService._load_snapshot
    query_only_values: list[int] = []

    def tracked(connection):
        query_only_values.append(int(connection.execute("PRAGMA query_only").fetchone()[0]))
        return original(connection)

    monkeypatch.setattr(GroupingService, "_load_snapshot", staticmethod(tracked))
    accepted = service.accept_regroup_proposal(
        command_id=new_uuid4(),
        proposal_id=str(item["proposal_id"]),
        proposal_revision=1,
        input_fingerprint=str(item["input_fingerprint"]),
    )
    assert accepted["state"] == "accepted"
    assert query_only_values == [1]


def test_accept_regroup_detects_commit_between_planning_snapshot_and_writer(
    initialized_database,
    monkeypatch,
) -> None:
    factory = _factory(initialized_database)
    first = _task(factory, "A11 stale A", 2_881_000_000, 2_881_000_200)
    second = _task(factory, "A11 stale B", 2_881_000_100, 2_881_000_300)
    service = GroupingService(factory)
    page = service.recompute_grouping_proposals(
        command_id=new_uuid4(),
        origin="manual_request",
    )
    item = page["proposals"]["items"][0]
    command_id = new_uuid4()

    original = GroupingService._candidate_for_proposal.__func__
    injected = [False]

    def with_intervening_commit(cls, connection, proposal):
        candidate = original(cls, connection, proposal)
        if not injected[0]:
            injected[0] = True
            _task(factory, "A11 unrelated commit", 2_990_000_000, 2_990_000_100)
        return candidate

    monkeypatch.setattr(
        GroupingService,
        "_candidate_for_proposal",
        classmethod(with_intervening_commit),
    )
    with pytest.raises(SomaError) as raised:
        service.accept_regroup_proposal(
            command_id=command_id,
            proposal_id=str(item["proposal_id"]),
            proposal_revision=1,
            input_fingerprint=str(item["input_fingerprint"]),
        )
    assert raised.value.code == "GROUPING_PROPOSAL_STALE"
    assert injected == [True]

    with ReadSnapshot(factory) as snapshot:
        assert snapshot.connection.execute(
            "SELECT 1 FROM command_receipts WHERE command_id=?",
            (command_id,),
        ).fetchone() is None
        assert snapshot.connection.execute(
            "SELECT COUNT(*) FROM objective_task_membership_current "
            "WHERE task_id IN (?,?)",
            (first.task_id, second.task_id),
        ).fetchone()[0] == 0


def test_lld05_f006_regroup_failure_after_first_membership_rolls_back_whole_create(
    initialized_database,
    monkeypatch,
) -> None:
    factory = _factory(initialized_database)
    first = _task(factory, "F006 first", 2_323_000_000, 2_323_000_300)
    second = _task(factory, "F006 second", 2_323_000_100, 2_323_000_400)
    service = GroupingService(factory)
    page = service.recompute_grouping_proposals(
        command_id=new_uuid4(),
        origin="manual_request",
    )
    item = page["proposals"]["items"][0]
    proposal_id = str(item["proposal_id"])
    command_id = new_uuid4()
    original = service._apply_membership_change
    calls = [0]

    def fail_after_first_membership(connection, **kwargs):
        event_id = original(connection, **kwargs)
        calls[0] += 1
        if calls[0] == 1:
            raise IntegrityFailure("LLD05-F006 injected after first regroup membership")
        return event_id

    monkeypatch.setattr(
        service,
        "_apply_membership_change",
        fail_after_first_membership,
    )
    with pytest.raises(IntegrityFailure, match="LLD05-F006"):
        service.accept_regroup_proposal(
            command_id=command_id,
            proposal_id=proposal_id,
            proposal_revision=1,
            input_fingerprint=str(item["input_fingerprint"]),
        )

    with ReadSnapshot(factory) as snapshot:
        assert snapshot.connection.execute(
            "SELECT count(*) FROM objectives"
        ).fetchone()[0] == 0
        assert snapshot.connection.execute(
            "SELECT count(*) FROM objective_task_membership_current "
            "WHERE task_id IN (?,?)",
            (first.task_id, second.task_id),
        ).fetchone()[0] == 0
        assert snapshot.connection.execute(
            "SELECT count(*) FROM objective_membership_events "
            "WHERE grouping_proposal_id=?",
            (proposal_id,),
        ).fetchone()[0] == 0
        assert tuple(
            snapshot.connection.execute(
                "SELECT state,revision FROM regroup_proposals "
                "WHERE regroup_proposal_id=?",
                (proposal_id,),
            ).fetchone()
        ) == ("pending", 1)
        assert snapshot.connection.execute(
            "SELECT count(*) FROM command_receipts WHERE command_id=?",
            (command_id,),
        ).fetchone()[0] == 0


def test_lld05_f007_consolidation_failure_after_all_memberships_rolls_back_original_objectives(
    initialized_database,
    monkeypatch,
) -> None:
    factory = _factory(initialized_database)
    left = _task(factory, "F007 left", 2_324_000_000, 2_324_000_200)
    right = _task(factory, "F007 right", 2_324_000_300, 2_324_000_500)
    left_objective = _objective(factory, left.task_id)
    right_objective = _objective(factory, right.task_id)
    bridge = _task(factory, "F007 bridge", 2_324_000_150, 2_324_000_350)
    service = GroupingService(factory)
    page = service.recompute_grouping_proposals(
        command_id=new_uuid4(),
        origin="manual_request",
    )
    item = page["proposals"]["items"][0]
    proposal_id = str(item["proposal_id"])
    detail = ObjectiveGroupingQueryService(factory).proposal_detail(proposal_id)
    original = service._apply_membership_change
    calls = [0]

    def fail_before_supersession(connection, **kwargs):
        event_id = original(connection, **kwargs)
        calls[0] += 1
        if calls[0] == len(detail["task_changes"]):
            raise IntegrityFailure("LLD05-F007 injected before Objective supersession")
        return event_id

    monkeypatch.setattr(
        service,
        "_apply_membership_change",
        fail_before_supersession,
    )
    command_id = new_uuid4()
    with pytest.raises(IntegrityFailure, match="LLD05-F007"):
        service.accept_regroup_proposal(
            command_id=command_id,
            proposal_id=proposal_id,
            proposal_revision=1,
            input_fingerprint=str(detail["input_fingerprint"]),
        )

    with ReadSnapshot(factory) as snapshot:
        memberships = {
            str(row[0]): str(row[1])
            for row in snapshot.connection.execute(
                "SELECT task_id,objective_id FROM objective_task_membership_current "
                "WHERE task_id IN (?,?,?)",
                (left.task_id, right.task_id, bridge.task_id),
            ).fetchall()
        }
        assert memberships == {
            left.task_id: left_objective,
            right.task_id: right_objective,
        }
        objective_rows = snapshot.connection.execute(
            "SELECT objective_id,superseded_by_objective_id "
            "FROM objectives WHERE objective_id IN (?,?)",
            (left_objective, right_objective),
        ).fetchall()
        assert len(objective_rows) == 2
        assert all(row[1] is None for row in objective_rows)
        assert snapshot.connection.execute(
            "SELECT count(*) FROM objective_membership_events "
            "WHERE grouping_proposal_id=?",
            (proposal_id,),
        ).fetchone()[0] == 0
        assert tuple(
            snapshot.connection.execute(
                "SELECT state,revision FROM regroup_proposals "
                "WHERE regroup_proposal_id=?",
                (proposal_id,),
            ).fetchone()
        ) == ("pending", 1)
        assert snapshot.connection.execute(
            "SELECT count(*) FROM command_receipts WHERE command_id=?",
            (command_id,),
        ).fetchone()[0] == 0

def test_lld05_f008_overlapping_objective_after_proposal_blocks_acceptance(
    initialized_database,
) -> None:
    factory = _factory(initialized_database)
    target = _task(factory, "F008 target", 2_882_000_000, 2_882_000_200)
    service = GroupingService(factory)
    page = service.recompute_grouping_proposals(
        command_id=new_uuid4(),
        origin="manual_request",
    )
    assert len(page["proposals"]["items"]) == 1
    item = page["proposals"]["items"][0]
    proposal_id = str(item["proposal_id"])
    fingerprint = str(item["input_fingerprint"])

    blocker = _task(factory, "F008 accepted overlap", 2_882_000_100, 2_882_000_300)
    blocker_objective_id = _objective(factory, blocker.task_id)
    command_id = new_uuid4()

    with pytest.raises(SomaError) as raised:
        service.accept_regroup_proposal(
            command_id=command_id,
            proposal_id=proposal_id,
            proposal_revision=1,
            input_fingerprint=fingerprint,
        )
    assert raised.value.code in {"GROUPING_PROPOSAL_STALE", "OBJECTIVE_OVERLAP"}

    with ReadSnapshot(factory) as snapshot:
        assert snapshot.connection.execute(
            "SELECT state,revision,input_fingerprint FROM regroup_proposals "
            "WHERE regroup_proposal_id=?",
            (proposal_id,),
        ).fetchone() == ("pending", 1, fingerprint)
        assert snapshot.connection.execute(
            "SELECT 1 FROM command_receipts WHERE command_id=?",
            (command_id,),
        ).fetchone() is None
        assert snapshot.connection.execute(
            "SELECT 1 FROM objective_task_membership_current WHERE task_id=?",
            (target.task_id,),
        ).fetchone() is None
        blocker_membership = snapshot.connection.execute(
            "SELECT objective_id FROM objective_task_membership_current WHERE task_id=?",
            (blocker.task_id,),
        ).fetchone()
        assert blocker_membership == (blocker_objective_id,)
        assert snapshot.connection.execute(
            "SELECT superseded_by_objective_id FROM objectives WHERE objective_id=?",
            (blocker_objective_id,),
        ).fetchone() == (None,)


def test_lld05_f009_task_lock_drift_keeps_regroup_proposal_immutable(
    initialized_database,
) -> None:
    factory = _factory(initialized_database)
    target = _task(factory, "F009 target", 2_883_000_000, 2_883_000_200)
    service = GroupingService(factory)
    page = service.recompute_grouping_proposals(
        command_id=new_uuid4(),
        origin="manual_request",
    )
    assert len(page["proposals"]["items"]) == 1
    item = page["proposals"]["items"][0]
    proposal_id = str(item["proposal_id"])
    fingerprint = str(item["input_fingerprint"])

    locked = TaskExplicitLockService(factory).set_explicit_task_lock(
        command_id=new_uuid4(),
        task_id=target.task_id,
        task_revision=target.revision,
        lock_projection_revision=0,
        lock_kind="membership",
        action="lock",
        reason_category="f009_membership_lock_drift",
    )
    assert locked.outcome == "APPLIED"
    command_id = new_uuid4()

    with pytest.raises(SomaError) as raised:
        service.accept_regroup_proposal(
            command_id=command_id,
            proposal_id=proposal_id,
            proposal_revision=1,
            input_fingerprint=fingerprint,
        )
    assert raised.value.code == "GROUPING_PROPOSAL_STALE"

    with ReadSnapshot(factory) as snapshot:
        assert snapshot.connection.execute(
            "SELECT state,revision,input_fingerprint FROM regroup_proposals "
            "WHERE regroup_proposal_id=?",
            (proposal_id,),
        ).fetchone() == ("pending", 1, fingerprint)
        assert snapshot.connection.execute(
            "SELECT 1 FROM command_receipts WHERE command_id=?",
            (command_id,),
        ).fetchone() is None
        assert snapshot.connection.execute(
            "SELECT explicit_plan_lock,explicit_membership_lock,revision "
            "FROM task_lock_projection WHERE task_id=?",
            (target.task_id,),
        ).fetchone() == (0, 1, 1)
        assert snapshot.connection.execute(
            "SELECT 1 FROM objective_task_membership_current WHERE task_id=?",
            (target.task_id,),
        ).fetchone() is None

def _grouping_wfm(factory, *, suffix: int, rfc_id: str, start_utc: int):
    return TaskPlanningService(factory).register_manual_wfm_task(
        command_id=new_uuid4(),
        task_no=f"TK{suffix:014d}",
        rfc_id=rfc_id,
        schedule=AcceptedTaskSchedule(
            start_utc=start_utc,
            end_utc=start_utc + 3_600,
            scheduling_timezone_iana=TZ,
        ),
    )


def _review_grouping_activity(factory, task_ids: tuple[str, str], decision: str) -> None:
    canonical = tuple(sorted(task_ids))
    preview = WfmActivityRelationshipReviewQueryService(factory).preview(
        seed_task_ids=canonical,
        decision=decision,
    )
    result = WfmActivityRelationshipReviewService(factory).review_wfm_activity_relationship(
        command_id=new_uuid4(),
        seed_tasks=tuple(
            (seed.task_id, seed.task_revision)
            for seed in preview.seed_tasks
        ),
        decision=decision,
        review_fingerprint=preview.review_fingerprint,
        reason_category=f"grouping_{decision}",
    )
    assert result.outcome == "APPLIED"


def test_t012_distinct_same_rfc_wfm_activities_group_normally(
    initialized_database,
) -> None:
    factory = _factory(initialized_database)
    rfc = RfcService(factory).create_or_adopt_identity(
        command_id=new_uuid4(),
        rfc_no="NC00000000008840",
        creation_context="provisional",
    )
    start = 2_884_000_000
    first = _grouping_wfm(factory, suffix=8840, rfc_id=rfc.rfc_id, start_utc=start)
    second = _grouping_wfm(factory, suffix=8841, rfc_id=rfc.rfc_id, start_utc=start + 600)
    _review_grouping_activity(
        factory,
        (first.task_id, second.task_id),
        "distinct_activity",
    )

    query = ObjectiveGroupingQueryService(factory)
    for task_id in (first.task_id, second.task_id):
        eligibility = query.grouping_eligibility(task_id, as_of_utc=start - 1)
        assert eligibility["classification"] == "ordinary_future"
        assert eligibility["eligible"] is True

    service = GroupingService(factory)
    page = service.recompute_grouping_proposals(
        command_id=new_uuid4(),
        origin="manual_request",
    )
    assert page["proposals"]["exact_total"] == 1
    item = page["proposals"]["items"][0]
    detail = query.proposal_detail(str(item["proposal_id"]))
    assert detail["task_change_exact_count"] == 2

    accepted = service.accept_regroup_proposal(
        command_id=new_uuid4(),
        proposal_id=str(item["proposal_id"]),
        proposal_revision=1,
        input_fingerprint=str(item["input_fingerprint"]),
    )
    assert accepted["state"] == "accepted"
    with ReadSnapshot(factory) as snapshot:
        rows = snapshot.connection.execute(
            "SELECT task_id,objective_id FROM objective_task_membership_current "
            "WHERE task_id IN (?,?) ORDER BY task_id",
            (first.task_id, second.task_id),
        ).fetchall()
        assert len(rows) == 2
        assert len({str(row[1]) for row in rows}) == 1


def test_t013_same_activity_overlap_is_excluded_from_automatic_grouping(
    initialized_database,
) -> None:
    factory = _factory(initialized_database)
    rfc = RfcService(factory).create_or_adopt_identity(
        command_id=new_uuid4(),
        rfc_no="NC00000000008850",
        creation_context="provisional",
    )
    start = 2_885_000_000
    first = _grouping_wfm(factory, suffix=8850, rfc_id=rfc.rfc_id, start_utc=start)
    second = _grouping_wfm(factory, suffix=8851, rfc_id=rfc.rfc_id, start_utc=start + 600)
    _review_grouping_activity(
        factory,
        (first.task_id, second.task_id),
        "same_activity",
    )

    query = ObjectiveGroupingQueryService(factory)
    for task_id in (first.task_id, second.task_id):
        eligibility = query.grouping_eligibility(task_id, as_of_utc=start - 1)
        assert eligibility["classification"] == "competing_attempt"
        assert eligibility["eligible"] is False

    page = GroupingService(factory).recompute_grouping_proposals(
        command_id=new_uuid4(),
        origin="manual_request",
    )
    assert page["proposals"] == {
        "items": [],
        "continuation": None,
        "exact_total": 0,
    }
    with ReadSnapshot(factory) as snapshot:
        assert snapshot.connection.execute(
            "SELECT COUNT(*) FROM objective_task_membership_current "
            "WHERE task_id IN (?,?)",
            (first.task_id, second.task_id),
        ).fetchone()[0] == 0
        assert snapshot.connection.execute(
            "SELECT COUNT(*) FROM objectives",
        ).fetchone()[0] == 0


def test_t013_same_lineage_exact_touch_is_not_competing_attempt(
    initialized_database,
) -> None:
    factory = _factory(initialized_database)
    rfc = RfcService(factory).create_or_adopt_identity(
        command_id=new_uuid4(),
        rfc_no="NC00000000008860",
        creation_context="provisional",
    )
    start = 2_886_000_000
    first = _grouping_wfm(factory, suffix=8860, rfc_id=rfc.rfc_id, start_utc=start)
    second = _grouping_wfm(factory, suffix=8861, rfc_id=rfc.rfc_id, start_utc=start + 3_600)
    _review_grouping_activity(
        factory,
        (first.task_id, second.task_id),
        "same_activity",
    )

    query = ObjectiveGroupingQueryService(factory)
    for task_id in (first.task_id, second.task_id):
        eligibility = query.grouping_eligibility(task_id, as_of_utc=start - 1)
        assert eligibility["classification"] == "ordinary_future"
        assert eligibility["eligible"] is True

    page = GroupingService(factory).recompute_grouping_proposals(
        command_id=new_uuid4(),
        origin="manual_request",
    )
    assert page["proposals"]["exact_total"] == 2
    assert all(
        ObjectiveGroupingQueryService(factory).proposal_detail(
            str(item["proposal_id"])
        )["task_change_exact_count"] == 1
        for item in page["proposals"]["items"]
    )

def _apply_grouping_terminal_source(
    factory,
    *,
    task_id: str,
    lifecycle: str,
    source_start_utc: int,
) -> None:
    command_id = new_uuid4()
    with UnitOfWork(factory) as uow:
        uow.connection.execute(
            "INSERT INTO command_receipts(command_id,command_type,request_hash,target_type,target_id,"
            "committed_at_utc,result_type,result_id) "
            "VALUES (?,'AcceptReconciliationProposal',?,'reconciliation_proposal',?,0,NULL,NULL)",
            (command_id, "9" * 64, new_uuid4()),
        )
        result = WfmSourceProjectionParticipant.apply_wfm_source_projection(
            uow,
            WfmSourceProjectionMutation(
                task_id=task_id,
                expected_source_projection_revision=0,
                provider_status_token="Complete" if lifecycle == "complete" else "Plan Cancel",
                provider_lifecycle_class=lifecycle,
                source_plan_start_utc=source_start_utc,
                source_plan_end_utc=source_start_utc + 3_600,
                accepted_source_observation_id=new_uuid4(),
                source_base_token="8" * 64,
            ),
            command_id=command_id,
        )
        assert result.source_projection_revision == 1


def test_provider_terminal_wfm_tasks_are_not_ordinary_grouping_work(
    initialized_database,
) -> None:
    factory = _factory(initialized_database)
    rfc = RfcService(factory).create_or_adopt_identity(
        command_id=new_uuid4(),
        rfc_no="NC00000000008870",
        creation_context="provisional",
    )
    start = 2_887_000_000
    completed = _grouping_wfm(
        factory,
        suffix=8870,
        rfc_id=rfc.rfc_id,
        start_utc=start,
    )
    cancelled = _grouping_wfm(
        factory,
        suffix=8871,
        rfc_id=rfc.rfc_id,
        start_utc=start + 10_000,
    )
    _apply_grouping_terminal_source(
        factory,
        task_id=completed.task_id,
        lifecycle="complete",
        source_start_utc=start,
    )
    _apply_grouping_terminal_source(
        factory,
        task_id=cancelled.task_id,
        lifecycle="plan_cancel",
        source_start_utc=start + 10_000,
    )

    query = ObjectiveGroupingQueryService(factory)
    complete_eligibility = query.grouping_eligibility(
        completed.task_id,
        as_of_utc=start - 1,
    )
    cancel_eligibility = query.grouping_eligibility(
        cancelled.task_id,
        as_of_utc=start - 1,
    )
    assert complete_eligibility["classification"] == "historical_candidate"
    assert complete_eligibility["eligible"] is False
    assert cancel_eligibility["classification"] == "cancelled"
    assert cancel_eligibility["eligible"] is False

    page = GroupingService(factory).recompute_grouping_proposals(
        command_id=new_uuid4(),
        origin="manual_request",
    )
    assert page["proposals"] == {
        "items": [],
        "continuation": None,
        "exact_total": 0,
    }
    with ReadSnapshot(factory) as snapshot:
        assert snapshot.connection.execute(
            "SELECT COUNT(*) FROM objective_task_membership_current "
            "WHERE task_id IN (?,?)",
            (completed.task_id, cancelled.task_id),
        ).fetchone()[0] == 0

def test_started_unassigned_task_is_not_automatic_grouping_candidate(
    initialized_database,
) -> None:
    factory = _factory(initialized_database)
    start = 2_888_000_000
    task = _task(factory, "Started unassigned", start, start + 3_600)
    started = TaskExecutionService(factory).start_task_execution(
        command_id=new_uuid4(),
        task_id=task.task_id,
        task_revision=task.revision,
        execution_revision=0,
        effective_start_utc=start + 60,
    )
    assert started.outcome == "APPLIED"

    eligibility = ObjectiveGroupingQueryService(factory).grouping_eligibility(
        task.task_id,
        as_of_utc=start - 1,
    )
    assert eligibility["classification"] == "started_or_protected"
    assert eligibility["eligible"] is False

    page = GroupingService(factory).recompute_grouping_proposals(
        command_id=new_uuid4(),
        origin="manual_request",
    )
    assert page["proposals"] == {
        "items": [],
        "continuation": None,
        "exact_total": 0,
    }
    with ReadSnapshot(factory) as snapshot:
        assert snapshot.connection.execute(
            "SELECT 1 FROM objective_task_membership_current WHERE task_id=?",
            (task.task_id,),
        ).fetchone() is None

