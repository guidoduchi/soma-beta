from __future__ import annotations

from soma.foundation.identifiers import new_uuid4
from soma.foundation.persistence.uow import ReadSnapshot
from soma.objectives_tasks import TaskPlanningService
from soma.tickets.rfc_hierarchy import RfcHierarchyService
from soma.tickets.rfcs import RfcService


def _factory(initialized_database):
    database_path, factory_for_path = initialized_database
    return factory_for_path(database_path)


def _create_rfc(factory, serial: int):
    return RfcService(factory).create_or_adopt_identity(
        command_id=new_uuid4(),
        rfc_no=f"NC{serial:014d}",
        creation_context="manual",
    )


def test_t047_local_task_may_link_subordinate_rfc_without_mutating_hierarchy(initialized_database) -> None:
    factory = _factory(initialized_database)
    parent = _create_rfc(factory, 4701)
    child = _create_rfc(factory, 4702)
    RfcHierarchyService(factory).add_subordinate(
        command_id=new_uuid4(),
        parent_rfc_id=parent.rfc_id,
        child_rfc_id=child.rfc_id,
        base_revisions={parent.rfc_id: parent.revision, child.rfc_id: child.revision},
        reason_category="manual_review",
    )

    with ReadSnapshot(factory) as snapshot:
        before_edge = snapshot.connection.execute(
            "SELECT rfc_hierarchy_edge_id,parent_rfc_id,child_rfc_id,edge_state,opened_command_id,"
            "closed_command_id,closed_at_utc FROM rfc_hierarchy_edges WHERE child_rfc_id=?",
            (child.rfc_id,),
        ).fetchone()
        before_revisions = dict(
            snapshot.connection.execute(
                "SELECT rfc_id,revision FROM rfcs WHERE rfc_id IN (?,?) ORDER BY rfc_id",
                (parent.rfc_id, child.rfc_id),
            ).fetchall()
        )
    assert before_edge is not None
    assert tuple(before_edge[1:4]) == (parent.rfc_id, child.rfc_id, "active")

    created = TaskPlanningService(factory).create_local_task(
        command_id=new_uuid4(),
        local_task_name="Subordinate RFC local work",
        rfc_ids=[child.rfc_id],
    )
    assert created.outcome == "APPLIED"

    with ReadSnapshot(factory) as snapshot:
        task = snapshot.connection.execute(
            "SELECT task_kind,local_task_name,creation_origin,revision FROM tasks WHERE task_id=?",
            (created.task_id,),
        ).fetchone()
        assert tuple(task) == ("local", "Subordinate RFC local work", "manual", 1)

        link = snapshot.connection.execute(
            "SELECT task_id,rfc_id,active,closed_command_id FROM task_rfc_links WHERE task_id=?",
            (created.task_id,),
        ).fetchone()
        assert tuple(link) == (created.task_id, child.rfc_id, 1, None)

        after_edge = snapshot.connection.execute(
            "SELECT rfc_hierarchy_edge_id,parent_rfc_id,child_rfc_id,edge_state,opened_command_id,"
            "closed_command_id,closed_at_utc FROM rfc_hierarchy_edges WHERE child_rfc_id=?",
            (child.rfc_id,),
        ).fetchone()
        assert tuple(after_edge) == tuple(before_edge)

        after_revisions = dict(
            snapshot.connection.execute(
                "SELECT rfc_id,revision FROM rfcs WHERE rfc_id IN (?,?) ORDER BY rfc_id",
                (parent.rfc_id, child.rfc_id),
            ).fetchall()
        )
        assert after_revisions == before_revisions

        assert snapshot.connection.execute(
            "SELECT 1 FROM wfm_task_identities WHERE task_id=?", (created.task_id,)
        ).fetchone() is None
        assert snapshot.connection.execute(
            "SELECT 1 FROM objective_task_membership_current WHERE task_id=?", (created.task_id,)
        ).fetchone() is None
        assert snapshot.connection.execute(
            "SELECT 1 FROM objectives WHERE created_command_id=(SELECT created_command_id FROM tasks WHERE task_id=?)",
            (created.task_id,),
        ).fetchone() is None
