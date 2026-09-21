from __future__ import annotations

from soma.foundation.identifiers import new_uuid4
from soma.foundation.persistence.uow import ReadSnapshot
from soma.objectives_tasks import AcceptedTaskSchedule, TaskPlanningService
from soma.objectives_tasks.domain.objectives import ObjectiveExistingTaskIntent
from soma.objectives_tasks.queries.objectives import ObjectiveQueryService
from soma.objectives_tasks.services.objectives import ObjectiveService
from soma.reference.application.customer_service import CustomerReferenceService
from soma.tickets.service_requests import ServiceRequestService
from soma.tickets.sr_references import ServiceRequestReferenceService
from soma.objectives_tasks.queries.grouping import ObjectiveGroupingQueryService
from soma.objectives_tasks.services.grouping import GroupingService


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
    assert len(response["items"]) == 2
    details = [
        ObjectiveGroupingQueryService(factory).proposal_detail(item["proposal_id"])
        for item in response["items"]
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
    assert len(first["items"]) == 1
    item = first["items"][0]
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
    assert suppressed["items"] == []

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
    assert len(fresh["items"]) == 1


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
    assert len(page["items"]) == 1
    item = page["items"][0]
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
    assert len(page["items"]) == 1
    proposal_id = str(page["items"][0]["proposal_id"])
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
    assert len(page["items"]) == 1
    proposal_id = str(page["items"][0]["proposal_id"])
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
    objective_id = str(accepted["objective_id"])
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
