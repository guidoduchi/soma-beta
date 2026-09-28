from __future__ import annotations

from soma.foundation.identifiers import new_uuid4
from soma.foundation.persistence.uow import ReadSnapshot
from soma.objectives_tasks import AcceptedTaskSchedule, TaskPlanningService
from soma.objectives_tasks.domain.objectives import ObjectiveExistingTaskIntent
from soma.objectives_tasks.queries.grouping import ObjectiveGroupingQueryService
from soma.objectives_tasks.queries.objectives import ObjectiveQueryService
from soma.objectives_tasks.services.objectives import ObjectiveService
from soma.objectives_tasks.services.task_relationships import TaskRelationshipService
from soma.reference.application.customer_service import CustomerReferenceService
from soma.tickets.device_references import DeviceReferenceService
from soma.tickets.relationships import ServiceRequestRfcRelationshipService
from soma.tickets.rfc_hierarchy import RfcHierarchyService
from soma.tickets.rfcs import RfcService
from soma.tickets.service_requests import ServiceRequestService


TZ = "America/Guayaquil"


def _factory(initialized_database):
    path, builder = initialized_database
    return builder(path)


def _intent(factory, task_id: str) -> ObjectiveExistingTaskIntent:
    with ReadSnapshot(factory) as snapshot:
        row = snapshot.connection.execute(
            "SELECT t.revision,c.revision,c.plan_revision_id "
            "FROM tasks t JOIN task_plan_current c ON c.task_id=t.task_id "
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


def _objective_for(factory, task_id: str) -> str:
    intent = _intent(factory, task_id)
    preview = ObjectiveGroupingQueryService(factory).creation_preview(
        existing_tasks=(intent,),
    )
    assert preview["mode"] == "CREATE"
    return ObjectiveService(factory).create_objective_from_preview(
        command_id=new_uuid4(),
        preview_fingerprint=str(preview["fingerprint"]),
        existing_tasks=(intent,),
    ).objective_id


def _objective_pins(factory, objective_id: str, task_id: str):
    with ReadSnapshot(factory) as snapshot:
        membership = tuple(
            snapshot.connection.execute(
                "SELECT accepted_plan_revision_id,membership_revision,last_event_id "
                "FROM objective_task_membership_current "
                "WHERE objective_id=? AND task_id=?",
                (objective_id, task_id),
            ).fetchone()
        )
        envelope = tuple(
            snapshot.connection.execute(
                "SELECT start_utc,end_utc,member_count,revision,"
                "membership_input_fingerprint,last_command_id "
                "FROM objective_envelope_projection WHERE objective_id=?",
                (objective_id,),
            ).fetchone()
        )
    return membership, envelope


def test_t035_objective_relationship_context_is_task_derived_without_objective_mutation(
    initialized_database,
) -> None:
    factory = _factory(initialized_database)
    task = TaskPlanningService(factory).create_local_task(
        command_id=new_uuid4(),
        local_task_name="T035 derived relationship context",
        schedule=AcceptedTaskSchedule(
            start_utc=2_910_000_000,
            end_utc=2_910_003_600,
            scheduling_timezone_iana=TZ,
        ),
    )
    objective_id = _objective_for(factory, task.task_id)
    membership_before, envelope_before = _objective_pins(
        factory,
        objective_id,
        task.task_id,
    )

    sr = ServiceRequestService(factory).create_manual_service_request(
        command_id=new_uuid4(),
    )
    rfc = RfcService(factory).create_or_adopt_identity(
        command_id=new_uuid4(),
        rfc_no="NC00000000003501",
        creation_context="manual",
    )
    device = DeviceReferenceService(factory).create(
        command_id=new_uuid4(),
        operational_name="NE-T035-CONTEXT",
    )

    with ReadSnapshot(factory) as snapshot:
        task_revision = int(
            snapshot.connection.execute(
                "SELECT revision FROM tasks WHERE task_id=?",
                (task.task_id,),
            ).fetchone()[0]
        )

    relationships = TaskRelationshipService(factory)
    for kind, target_id in (
        ("sr", sr.service_request_id),
        ("rfc", rfc.rfc_id),
        ("device", device.device_reference_id),
    ):
        changed = relationships.change_task_relationship(
            command_id=new_uuid4(),
            task_id=task.task_id,
            task_revision=task_revision,
            relationship_kind=kind,
            target_id=target_id,
            action="link",
        )
        assert changed.outcome == "APPLIED"
        task_revision = changed.revision

    context = ObjectiveQueryService(factory).context_by_task_relationships(
        objective_id,
        limit=100,
    )
    direct = {
        (str(item["context_type"]), str(item["related_id"])): item
        for item in context["items"]
        if str(item["provenance"]).startswith("direct_task_")
    }
    assert set(direct) == {
        ("sr", sr.service_request_id),
        ("rfc", rfc.rfc_id),
        ("device", device.device_reference_id),
    }
    for (kind, _target), item in direct.items():
        assert item["source_task_id"] == task.task_id
        assert item["provenance"] == f"direct_task_{kind}_relationship"
        assert item["resolution_state"] == "resolved"

    membership_after, envelope_after = _objective_pins(
        factory,
        objective_id,
        task.task_id,
    )
    assert membership_after == membership_before
    assert envelope_after == envelope_before
    with ReadSnapshot(factory) as snapshot:
        assert snapshot.connection.execute(
            "SELECT 1 FROM task_execution_projection WHERE task_id=?",
            (task.task_id,),
        ).fetchone() is None
        assert snapshot.connection.execute(
            "SELECT 1 FROM task_outcome_current WHERE task_id=?",
            (task.task_id,),
        ).fetchone() is None


def test_t034_wfm_objective_context_derives_owning_rfc_and_governing_root_authority(
    initialized_database,
) -> None:
    factory = _factory(initialized_database)
    customer = CustomerReferenceService(factory).create_customer_organization(
        command_id=new_uuid4(),
        name="T034 Governing Customer",
    )
    rfcs = RfcService(factory)
    root = rfcs.create_or_adopt_identity(
        command_id=new_uuid4(),
        rfc_no="NC00000000003401",
        creation_context="manual",
        customer_org_id=customer.customer_org_id,
    )
    child = rfcs.create_or_adopt_identity(
        command_id=new_uuid4(),
        rfc_no="NC00000000003402",
        creation_context="manual",
        customer_org_id=customer.customer_org_id,
    )
    RfcHierarchyService(factory).add_subordinate(
        command_id=new_uuid4(),
        parent_rfc_id=root.rfc_id,
        child_rfc_id=child.rfc_id,
        base_revisions={root.rfc_id: 1, child.rfc_id: 1},
        reason_category="reviewed_hierarchy",
    )

    sr = ServiceRequestService(factory).create_manual_service_request(
        command_id=new_uuid4(),
    )
    ticket_links = ServiceRequestRfcRelationshipService(factory)
    preview = ticket_links.preview_link(
        service_request_id=sr.service_request_id,
        rfc_id=root.rfc_id,
    )
    linked = ticket_links.link(
        command_id=new_uuid4(),
        service_request_id=sr.service_request_id,
        rfc_id=root.rfc_id,
        sr_base_revision=preview.sr_revision,
        rfc_base_revision=preview.rfc_revision,
        review_fingerprint=preview.review_fingerprint,
    )
    assert linked.outcome == "APPLIED"

    task = TaskPlanningService(factory).register_manual_wfm_task(
        command_id=new_uuid4(),
        task_no="TK00000000003401",
        rfc_id=child.rfc_id,
        schedule=AcceptedTaskSchedule(
            start_utc=2_920_000_000,
            end_utc=2_920_003_600,
            scheduling_timezone_iana=TZ,
        ),
    )
    objective_id = _objective_for(factory, task.task_id)

    context = ObjectiveQueryService(factory).context_by_task_relationships(
        objective_id,
        limit=100,
    )
    items = context["items"]
    assert {
        (
            str(item["context_type"]),
            item["related_id"],
            str(item["provenance"]),
            str(item["source_task_id"]),
        )
        for item in items
    } == {
        ("rfc", child.rfc_id, "wfm_owning_rfc", task.task_id),
        ("sr", sr.service_request_id, "wfm_governing_root_sr", task.task_id),
        (
            "customer",
            customer.customer_org_id,
            "wfm_governing_root_customer",
            task.task_id,
        ),
    }
    assert context["exact_totals_by_context_type"] == {
        "customer": 1,
        "rfc": 1,
        "sr": 1,
    }

    with ReadSnapshot(factory) as snapshot:
        assert snapshot.connection.execute(
            "SELECT current_rfc_id FROM wfm_task_identities WHERE task_id=?",
            (task.task_id,),
        ).fetchone() == (child.rfc_id,)
        assert snapshot.connection.execute(
            "SELECT COUNT(*) FROM task_sr_links WHERE task_id=?",
            (task.task_id,),
        ).fetchone()[0] == 0
        assert snapshot.connection.execute(
            "SELECT COUNT(*) FROM task_rfc_links WHERE task_id=?",
            (task.task_id,),
        ).fetchone()[0] == 0
